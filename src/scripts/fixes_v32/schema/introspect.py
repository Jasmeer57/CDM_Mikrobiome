"""Introspect the frozen CDM 3.1.0 DB (read-only) and check keys + referential integrity.

Writes to outputs/results/schema_exports_v32_2026-11-11/schema/:
  db_profile.json               tables, columns, storage types, null/distinct counts, small value sets
  key_check.csv                 every key in schema_common.KEYS: rows, null rows, duplicate rows -> VALID/INVALID
  referential_integrity.csv     every reference in schema_common.REFS: child values, orphans, orphan examples
  archive_ref_check.csv         removed_* archives vs live tables (expected: disjoint)

    python src/scripts/fixes_v32/schema/introspect.py [--db PATH]
Heavy (3.3 GB DB, 2.5 M-row tables): run as a CPU SLURM job (see run_schema.sbatch).
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from schema_common import ARCHIVE_OF, ARCHIVE_REFS, DB_310, KEYS, OUT, REFS, ro_connect, sha256_file  # noqa: E402

ENUM_MAX = 40  # columns with <= this many distinct non-null values get their value set recorded


def q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def profile(con) -> dict:
    tables = {}
    for name, typ, sql in con.execute(
            "SELECT name, type, sql FROM sqlite_master WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%' "
            "ORDER BY name"):
        info = con.execute(f"PRAGMA table_info({q(name)})").fetchall()
        entry = {"type": typ, "sql": sql, "columns": []}
        if typ == "table":
            entry["rows"] = con.execute(f"SELECT count(*) FROM {q(name)}").fetchone()[0]
        for col in info:
            c = col["name"]
            cinfo = {"name": c, "position": col["cid"], "declared_type": col["type"], "pk": col["pk"]}
            if typ == "table":
                t0 = time.time()
                row = con.execute(
                    f"SELECT sum({q(c)} IS NULL), sum(trim(CAST({q(c)} AS TEXT))=''), count(DISTINCT {q(c)}), "
                    f"max(length(CAST({q(c)} AS TEXT))) FROM {q(name)}").fetchone()
                cinfo.update(null=row[0] or 0, empty=row[1] or 0, distinct=row[2], max_len=row[3])
                cinfo["storage_types"] = {r[0]: r[1] for r in con.execute(
                    f"SELECT typeof({q(c)}), count(*) FROM {q(name)} GROUP BY 1")}
                if row[2] is not None and row[2] <= ENUM_MAX:
                    cinfo["values"] = {str(r[0]): r[1] for r in con.execute(
                        f"SELECT {q(c)}, count(*) FROM {q(name)} WHERE {q(c)} IS NOT NULL GROUP BY 1 ORDER BY 2 DESC")}
                cinfo["semicolon_rows"] = con.execute(
                    f"SELECT count(*) FROM {q(name)} WHERE CAST({q(c)} AS TEXT) LIKE '%;%'").fetchone()[0] \
                    if c.endswith("_id") or c in ("project", "srs") else 0
                cinfo["profile_seconds"] = round(time.time() - t0, 2)
            entry["columns"].append(cinfo)
        tables[name] = entry
        print(f"profiled {name}", flush=True)
    return tables


def check_keys(con, tables) -> list[dict]:
    out = []
    for t, (cols, src) in KEYS.items():
        if not cols:
            out.append({"table": t, "key": "", "source": src, "rows": tables[t]["rows"], "status": "NO_KEY"})
            continue
        if t not in tables:
            out.append({"table": t, "key": "+".join(cols), "source": src, "status": "TABLE_MISSING"})
            continue
        cl = ", ".join(q(c) for c in cols)
        nulls = con.execute(f"SELECT count(*) FROM {q(t)} WHERE " +
                            " OR ".join(f"{q(c)} IS NULL OR trim(CAST({q(c)} AS TEXT))=''" for c in cols)).fetchone()[0]
        dup = con.execute(f"SELECT coalesce(sum(n-1),0), count(*) FROM (SELECT count(*) n FROM {q(t)} GROUP BY {cl} "
                          f"HAVING n>1)").fetchone()
        rows = tables[t]["rows"]
        out.append({"table": t, "key": "+".join(cols), "source": src, "rows": rows, "null_or_empty_rows": nulls,
                    "duplicate_extra_rows": dup[0], "duplicate_groups": dup[1],
                    "status": "VALID" if rows == 0 or (nulls == 0 and dup[0] == 0) else "INVALID"})
    return out


def _split(v):
    return [x.strip() for x in str(v).split(";") if x.strip()]


def check_refs(con, tables) -> list[dict]:
    out = []
    parent_cache: dict = {}
    for ct, cc, pt, pc, mv, src in REFS:
        rec = {"child_table": ct, "child_columns": "+".join(cc), "parent_table": pt, "parent_columns": "+".join(pc),
               "multivalued": mv, "source": src}
        if pt == "*":
            rec.update(status="POLYMORPHIC_CHECKED_IN_CANDIDATE_DB", child_rows=tables[ct]["rows"])
            out.append(rec)
            continue
        if ct not in tables or pt not in tables:
            rec["status"] = "TABLE_MISSING"
            out.append(rec)
            continue
        key = (pt, tuple(pc))
        if key not in parent_cache:
            parent_cache[key] = {tuple(str(x) for x in r) for r in con.execute(
                f"SELECT {', '.join(q(c) for c in pc)} FROM {q(pt)}")}
        parents = parent_cache[key]
        archive = set()
        if pt in ARCHIVE_OF and len(pc) == 1:
            at, ac = ARCHIVE_OF[pt]
            archive = {str(r[0]) for r in con.execute(f"SELECT {q(ac)} FROM {q(at)}")}
        n_arch = 0
        n_rows = n_vals = n_orph_rows = n_orph_vals = n_null = n_list_rows = 0
        examples = []
        for r in con.execute(f"SELECT {', '.join(q(c) for c in cc)} FROM {q(ct)}"):
            n_rows += 1
            if any(v is None or str(v).strip() == "" for v in r):
                n_null += 1
                continue
            if mv and len(cc) == 1:
                vals = [(x,) for x in _split(r[0])]
                if len(vals) > 1:
                    n_list_rows += 1
            else:
                vals = [tuple(str(v) for v in r)]
            bad = [v for v in vals if v not in parents]
            n_vals += len(vals)
            if bad:
                if archive and all(b[0] in archive for b in bad):
                    n_arch += 1
                n_orph_rows += 1
                n_orph_vals += len(bad)
                if len(examples) < 5:
                    examples.append("|".join(bad[0]))
        rec.update(child_rows=n_rows, null_or_empty=n_null, non_null_rows=n_rows - n_null, values_checked=n_vals,
                   list_rows=n_list_rows, orphan_rows=n_orph_rows, orphan_values=n_orph_vals,
                   orphan_rows_resolving_in_archive=n_arch, unexplained_orphan_rows=n_orph_rows - n_arch,
                   orphan_examples=" ; ".join(examples),
                   parent_key_unique=len(parents) == tables[pt]["rows"],
                   status="OK" if n_orph_rows == 0 else "ORPHANS")
        out.append(rec)
        print(f"ref {ct}.{'+'.join(cc)} -> {pt}: orphans {n_orph_rows}/{n_rows - n_null}", flush=True)
    return out


def check_archives(con) -> list[dict]:
    out = []
    for ct, cc, pt, pc in ARCHIVE_REFS:
        n = con.execute(f"SELECT count(*) FROM {q(ct)}").fetchone()[0]
        still = con.execute(f"SELECT count(*) FROM {q(ct)} WHERE {q(cc)} IN (SELECT {q(pc)} FROM {q(pt)})").fetchone()[0]
        out.append({"archive_table": ct, "column": cc, "live_table": pt, "rows": n, "still_in_live": still,
                    "status": "DISJOINT" if still == 0 else "OVERLAP"})
    return out


def write_csv(path: Path, rows: list[dict]):
    fields = []
    for r in rows:
        for k in r:
            if k not in fields:
                fields.append(k)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DB_310)
    ap.add_argument("--skip-sha", action="store_true")
    a = ap.parse_args()
    out = OUT / "schema"
    out.mkdir(parents=True, exist_ok=True)
    con = ro_connect(a.db)
    con.execute("PRAGMA temp_store=FILE")
    t0 = time.time()
    tables = profile(con)
    meta = {"db": str(a.db.relative_to(a.db.parents[3])), "db_sha256": None if a.skip_sha else sha256_file(a.db),
            "opened": "read-only (mode=ro)", "profile_seconds": round(time.time() - t0, 1)}
    (out / "db_profile.json").write_text(json.dumps({"meta": meta, "tables": tables}, indent=1, default=str))
    write_csv(out / "key_check.csv", check_keys(con, tables))
    write_csv(out / "referential_integrity.csv", check_refs(con, tables))
    write_csv(out / "archive_ref_check.csv", check_archives(con))
    print(f"done in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
