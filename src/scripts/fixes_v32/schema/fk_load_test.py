"""FK load test: build an empty SQLite DB from the generated DDL and copy the CDM data into it with foreign keys ON.

Source (attached read-only): the 3.2.0-candidate DB (= 3.1.0 byte copy + human_review rows); every other table is
checked to have the same row count as the frozen 3.1.0 release (schema/db_profile.json, read-only profile).
Target: a scratch location (default Lustre scratch; --out to override). Never touches releases/.

Per table, parents first:
  phase A  PRAGMA foreign_keys=ON; INSERT INTO t SELECT cols FROM src.t   -> OK, or FAILED (FOREIGN KEY constraint)
  phase B  for tables that failed: insert with foreign_keys=OFF, then PRAGMA foreign_key_check counts the violating
           rows per declared FOREIGN KEY.
Also checks the polymorphic human_review.target_id per target_entity and PRAGMA integrity_check.
Writes schema/fk_load_test.json and fk_load_test_violations.csv.

    python src/scripts/fixes_v32/schema/fk_load_test.py [--out DIR] [--source DB]
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from schema_common import CANDIDATE_DB, DB_310, OUT  # noqa: E402

DEFAULT_OUT = Path("/lustre/scratch/data/jkalra_hpc-microbiome_cdm/cdm_v32_fk_test")


def topo(tables, deps):
    done, order = set(), []

    def visit(t, stack=()):
        if t in done or t in stack:
            return
        for p in deps.get(t, ()):
            if p != t:
                visit(p, stack + (t,))
        done.add(t)
        order.append(t)
    for t in sorted(tables):
        visit(t)
    return order


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--source", type=Path, default=CANDIDATE_DB)
    a = ap.parse_args()
    ddl = (OUT / "schema/microbiome_cdm_v3.ddl.sql").read_text()
    a.out.mkdir(parents=True, exist_ok=True)
    tgt = a.out / "cdm_v3.2.0-candidate_from_ddl.db"
    if tgt.exists():
        tgt.unlink()
    con = sqlite3.connect(f"file:{tgt}", uri=True, isolation_level=None)
    con.execute("PRAGMA journal_mode=OFF")
    con.execute("PRAGMA synchronous=OFF")
    con.executescript(ddl)
    con.execute(f"ATTACH DATABASE 'file:{a.source}?mode=ro' AS src")
    tables = [r[0] for r in con.execute("SELECT name FROM main.sqlite_master WHERE type='table'")]
    fkl = {t: con.execute(f'PRAGMA main.foreign_key_list("{t}")').fetchall() for t in tables}
    deps = {t: {r[2] for r in fkl[t]} for t in tables}
    order = topo(tables, deps)
    src_tables = {r[0] for r in con.execute("SELECT name FROM src.sqlite_master WHERE type='table'")}
    # row counts of the frozen 3.1.0 DB as profiled read-only by introspect.py
    rel_counts = {t: e["rows"] for t, e in json.loads((OUT / "schema/db_profile.json").read_text())["tables"].items()
                  if e["type"] == "table"}
    res, t0 = [], time.time()
    for t in order:
        cols = [r[1] for r in con.execute(f'PRAGMA main.table_info("{t}")')]
        scols = {r[1] for r in con.execute(f'PRAGMA src.table_info("{t}")')} if t in src_tables else set()
        if t not in src_tables or set(cols) != scols:
            res.append({"table": t, "phase_a": "SKIPPED", "detail": "missing in source or column mismatch",
                        "missing_cols": sorted(set(cols) - scols), "extra_cols": sorted(scols - set(cols))})
            continue
        cl = ", ".join(f'"{c}"' for c in cols)
        n_src = con.execute(f'SELECT count(*) FROM src."{t}"').fetchone()[0]
        con.execute("PRAGMA foreign_keys=ON")
        rec = {"table": t, "source_rows": n_src, "declared_fks": len({r[0] for r in fkl[t]})}
        try:
            con.execute("BEGIN")
            con.execute(f'INSERT INTO main."{t}" ({cl}) SELECT {cl} FROM src."{t}"')
            con.execute("COMMIT")
            rec["phase_a"] = "OK"
        except sqlite3.IntegrityError as e:
            con.execute("ROLLBACK")
            rec["phase_a"] = f"FAILED: {e}"
            con.execute("PRAGMA foreign_keys=OFF")
            con.execute("BEGIN")
            con.execute(f'INSERT INTO main."{t}" ({cl}) SELECT {cl} FROM src."{t}"')
            con.execute("COMMIT")
        rec["loaded_rows"] = con.execute(f'SELECT count(*) FROM main."{t}"').fetchone()[0]
        exp = rel_counts.get(t)
        if exp is not None and t not in ("human_review", "run_metadata", "cdm_change_log", "cdm_entity_status"):
            rec["rows_equal_3_1_0"] = rec["loaded_rows"] == exp
        res.append(rec)
        print(f"{t}: {rec['phase_a'][:60]} rows {rec['loaded_rows']}", flush=True)
    con.execute("PRAGMA foreign_keys=ON")
    viol = Counter()
    for t, rowid, parent, fkid in con.execute("PRAGMA main.foreign_key_check"):
        viol[(t, fkid)] += 1
    vrows = []
    for (t, fkid), n in sorted(viol.items()):
        parts = [r for r in fkl[t] if r[0] == fkid]
        vrows.append({"child_table": t, "child_columns": "+".join(r[3] for r in parts),
                      "parent_table": parts[0][2], "parent_columns": "+".join(r[4] for r in parts),
                      "violating_rows": n})
    # polymorphic human_review.target_id
    poly = {}
    keycol = {"term_concept_map": "mapping_row_id", "relation": "canonical_triple_id"}
    for ent, n in con.execute("SELECT target_entity, count(*) FROM main.human_review GROUP BY 1").fetchall():
        k = keycol.get(ent)
        miss = con.execute(f'SELECT count(*) FROM main.human_review h WHERE target_entity=? AND NOT EXISTS '
                           f'(SELECT 1 FROM main."{ent}" x WHERE x."{k}"=h.target_id)', (ent,)).fetchone()[0] \
            if k else n
        poly[ent] = {"rows": n, "unresolved": miss}
    integ = con.execute("PRAGMA main.integrity_check").fetchone()[0]
    # cross-check with the read-only orphan counts
    ri = {(r["child_table"], r["child_columns"]): r for r in csv.DictReader(open(OUT / "schema/referential_integrity.csv"))}
    for v in vrows:
        r = ri.get((v["child_table"], v["child_columns"]))
        cols_ = v["child_columns"].split("+")
        # SQL FKs treat '' as a value; the CDM convention (and the read-only check) treats '' as missing
        v["violating_rows_empty_string_reference"] = con.execute(
            f'SELECT count(*) FROM main."{v["child_table"]}" WHERE ' +
            " OR ".join(f'"{c}" = \'\'' for c in cols_)).fetchone()[0]
        v["violating_rows_non_empty"] = v["violating_rows"] - v["violating_rows_empty_string_reference"]
        v["orphan_rows_readonly_check"] = r["orphan_rows"] if r else ""
        v["matches_readonly_check"] = bool(r) and int(r["orphan_rows"]) == v["violating_rows_non_empty"]
        v["resolving_in_archive"] = r.get("orphan_rows_resolving_in_archive", "") if r else ""
    with open(OUT / "schema/fk_load_test_violations.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(vrows[0]) if vrows else ["child_table"])
        w.writeheader()
        w.writerows(vrows)
    summ = {"target_db": str(tgt), "source_db": a.source.name, "ddl": "schema/microbiome_cdm_v3.ddl.sql",
            "tables": len(res), "tables_loaded_fk_on_without_error": sum(r.get("phase_a") == "OK" for r in res),
            "tables_failing_fk_on": [r["table"] for r in res if str(r.get("phase_a", "")).startswith("FAILED")],
            "tables_skipped": [r["table"] for r in res if r.get("phase_a") == "SKIPPED"],
            "declared_foreign_keys": sum(len({x[0] for x in fkl[t]}) for t in tables),
            "fk_with_violations": len(vrows), "violating_rows_total": sum(v["violating_rows"] for v in vrows),
            "violating_rows_empty_string_reference": sum(v["violating_rows_empty_string_reference"] for v in vrows),
            "violating_rows_non_empty": sum(v["violating_rows_non_empty"] for v in vrows),
            "violating_rows_non_empty_resolving_in_archive": sum(int(v["resolving_in_archive"] or 0) for v in vrows),
            "violations": vrows, "violations_match_readonly_orphan_counts": all(v["matches_readonly_check"]
                                                                                 for v in vrows),
            "row_counts_equal_3_1_0": all(r.get("rows_equal_3_1_0", True) for r in res),
            "human_review_polymorphic_targets": poly, "integrity_check": integ,
            "seconds": round(time.time() - t0), "per_table": res}
    (OUT / "schema/fk_load_test.json").write_text(json.dumps(summ, indent=1))
    print(json.dumps({k: v for k, v in summ.items() if k != "per_table"}, indent=1))


if __name__ == "__main__":
    main()
