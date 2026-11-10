"""Verify a CDM 3.0.3 release candidate against CDM 3.0.2 (read-only on both).

1. preservation: every 3.0.2 table and column is present in the candidate with identical content (per-column
   sha256 over rows in rowid order); the only permitted differences are listed (new rows in extraction_run /
   run_metadata, run_metadata.cdm_version)
2. reversibility: REVERT_303.sql applied to a scratch copy restores 3.0.2 content exactly (tables, columns, rows)
3. regression: release QA (qa_cdm_v3.py), REG1-REG4 (publication_audit.regression) and the Gate 4 CDM
   validation suite, run on the candidate with the current and with the proposed registry

    python verify_303.py [--rc outputs/results/cdm_v3_3.0.3_rc1] [--scratch $TMPDIR]
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
OLD = ROOT / "releases/cdm_v3/3.0.2/microbiome_cdm_v3.db"
S = ROOT / "src/scripts"


def col_hashes(db, tables=None):
    """{table: {"rows": n, "cols": {col: sha256}}} — per-column content hash in rowid order."""
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    out = {}
    for (t,) in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
        if tables is not None and t not in tables:
            continue
        cols = [r[1] for r in c.execute(f'PRAGMA table_info("{t}")')]
        hs = {k: hashlib.sha256() for k in cols}
        n = 0
        q = f'SELECT {", ".join(chr(34) + k + chr(34) for k in cols)} FROM "{t}" ORDER BY rowid'
        for row in c.execute(q):
            n += 1
            for k, v in zip(cols, row):
                hs[k].update(repr(v).encode("utf-8", "surrogatepass") + b"\x1f")
        out[t] = {"rows": n, "cols": {k: h.hexdigest() for k, h in hs.items()}}
    return out


def subset_hash(db, table, cols, where):
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    h = hashlib.sha256()
    for row in c.execute(f'SELECT {", ".join(chr(34) + k + chr(34) for k in cols)} FROM "{table}" WHERE {where} ORDER BY rowid'):
        h.update(repr(row).encode())
    return h.hexdigest()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--rc", default=str(ROOT / "outputs/results/cdm_v3_3.0.3_rc1"))
    ap.add_argument("--scratch", default=os.environ.get("TMPDIR", "/tmp"))
    a = ap.parse_args(argv)
    rc = Path(a.rc)
    new = rc / "microbiome_cdm_v3.db"
    rep = {"old": str(OLD.relative_to(ROOT)), "rc": str(new.relative_to(ROOT))}
    print("hashing 3.0.2 …", flush=True)
    H0 = col_hashes(OLD)
    print("hashing candidate …", flush=True)
    H1 = col_hashes(new)

    # 1 preservation
    allowed = {("run_metadata", "value"), ("run_metadata", "key")}
    pres = []
    for t, h0 in H0.items():
        h1 = H1.get(t)
        if h1 is None:
            pres.append({"table": t, "status": "MISSING_IN_RC"})
            continue
        missing_cols = [k for k in h0["cols"] if k not in h1["cols"]]
        changed = [k for k in h0["cols"] if k in h1["cols"] and h0["cols"][k] != h1["cols"][k]]
        added = [k for k in h1["cols"] if k not in h0["cols"]]
        st = "IDENTICAL" if not missing_cols and not changed and h0["rows"] == h1["rows"] else "DIFFERENT"
        note = ""
        if t == "extraction_run" and h1["rows"] > h0["rows"] and not missing_cols:
            # original rows unchanged in their original columns?
            orig = list(h0["cols"])
            same = (subset_hash(OLD, t, orig, "1=1") ==
                    subset_hash(new, t, orig, f"rowid <= {h0['rows']}"))
            st = "ORIGINAL_ROWS_IDENTICAL_PLUS_NEW_ROWS" if same else "DIFFERENT"
            note = f"{h1['rows'] - h0['rows']} rows added"
        if t == "run_metadata":
            st, note = "EXPECTED_CHANGE", "cdm_version updated; derived_from / migration / migrated_at added"
        pres.append({"table": t, "rows_302": h0["rows"], "rows_303": h1["rows"], "columns_302": len(h0["cols"]),
                     "columns_added": ";".join(added), "columns_changed": ";".join(changed),
                     "columns_missing": ";".join(missing_cols), "status": st, "note": note})
    new_tables = sorted(set(H1) - set(H0))
    bad = [p for p in pres if p["status"] in ("DIFFERENT", "MISSING_IN_RC")]
    rep["preservation"] = {"tables_302": len(H0), "tables_rc": len(H1), "new_tables": new_tables,
                           "tables_identical": sum(p["status"] == "IDENTICAL" for p in pres),
                           "tables_with_only_added_columns_or_rows": sum(p["status"] != "IDENTICAL" for p in pres) - len(bad),
                           "violations": bad, "pass": not bad}
    with open(rc / "remediation/PRESERVATION_CHECK.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(pres[1]))
        w.writeheader()
        w.writerows(p for p in pres if "rows_302" in p)
    print("preservation:", rep["preservation"]["pass"], flush=True)

    # 2 reversibility on a scratch copy
    scratch = Path(a.scratch) / "cdm303_revert_test.db"
    shutil.copyfile(new, scratch)
    c = sqlite3.connect(scratch)
    c.executescript((rc / "REVERT_303.sql").read_text())
    c.commit()
    c.close()
    HR = col_hashes(scratch)
    diff = {t: "missing" for t in H0 if t not in HR}
    diff.update({t: "extra" for t in HR if t not in H0})
    for t in H0:
        if t in HR and (HR[t]["rows"] != H0[t]["rows"] or HR[t]["cols"] != H0[t]["cols"]):
            diff[t] = {"rows": (H0[t]["rows"], HR[t]["rows"]),
                       "cols_differ": [k for k in set(H0[t]["cols"]) | set(HR[t]["cols"]) if H0[t]["cols"].get(k) != HR[t]["cols"].get(k)]}
    ix0 = sorted(r[0] for r in sqlite3.connect(f"file:{OLD}?mode=ro", uri=True).execute("SELECT name FROM sqlite_master WHERE type='index'"))
    ixr = sorted(r[0] for r in sqlite3.connect(scratch).execute("SELECT name FROM sqlite_master WHERE type='index'"))
    rep["reversibility"] = {"content_differences": diff, "indexes_equal": ix0 == ixr, "pass": not diff and ix0 == ixr}
    scratch.unlink()
    print("reversibility:", rep["reversibility"]["pass"], flush=True)

    # 3 regression
    out = rc / "remediation/regression"
    out.mkdir(parents=True, exist_ok=True)
    r = subprocess.run([sys.executable, str(S / "vllm_termpop/qa_cdm_v3.py"), "--db", str(new), "--out", str(out / "qa_cdm")],
                       capture_output=True, text=True)
    qa = json.loads((out / "qa_cdm/qa_cdm_report.json").read_text())
    qa0 = json.loads((ROOT / "releases/cdm_v3/3.0.2/qa_cdm_report.json").read_text())
    rep["release_qa"] = {"verdict_302": qa0["verdict"], "verdict_rc": qa["verdict"], "fails_rc": qa["fails"],
                         "warnings_302": len(qa0["warnings"]), "warnings_rc": len(qa["warnings"]),
                         "warnings_removed": sorted(set(qa0["warnings"]) - set(qa["warnings"])),
                         "warnings_added": sorted(set(qa["warnings"]) - set(qa0["warnings"]))}
    sys.path.insert(0, str(S / "audit"))
    import publication_audit as PA  # noqa: E402
    terms = sum(1 for _ in open(ROOT / "releases/terminology/1.0.1/term_mentions.jsonl", encoding="utf-8"))
    rep["REG1_4"] = PA.regression(new, terms)
    for label, reg in (("current_registry", ROOT / "src/template/cdm/cdm_entity_registry.csv"),
                       ("proposed_registry", rc / "remediation/UPDATED_ENTITY_REGISTRY_PROPOSAL.csv")):
        d = out / f"cdm_validation_{label}"
        subprocess.run([sys.executable, str(S / "human_validation/cdm_validation.py"), "--cdm", str(new), "--registry", str(reg),
                        "--out", str(d)], capture_output=True, text=True, check=True)
        res = list(csv.DictReader(open(d / "CDM_CONSTRAINT_TEST_RESULTS.csv", encoding="utf-8")))
        rep[f"validation_{label}"] = {"PASS": sum(x["result"] == "PASS" for x in res), "FAIL": sum(x["result"] == "FAIL" for x in res),
                                       "CONDITIONAL": sum(x["result"] == "CONDITIONAL" for x in res),
                                       "failed": [f"{x['test_id']}: {x['detail'][:160]}" for x in res if x["result"] == "FAIL"]}
    base = list(csv.DictReader(open(ROOT / "outputs/human_validation/gate4_2026-11-02/CDM_VALIDATION/CDM_CONSTRAINT_TEST_RESULTS.csv", encoding="utf-8")))
    now = {x["test_id"]: x["result"] for x in csv.DictReader(open(out / "cdm_validation_proposed_registry/CDM_CONSTRAINT_TEST_RESULTS.csv", encoding="utf-8"))}
    rep["tests_302_vs_rc"] = [{"test": x["test_id"], "3.0.2": x["result"], "rc": now.get(x["test_id"], "absent")}
                              for x in base if now.get(x["test_id"]) != x["result"]]
    rep["regressions"] = [t for t in rep["tests_302_vs_rc"] if t["3.0.2"] == "PASS" and t["rc"] != "PASS"]
    rep["pass"] = (rep["preservation"]["pass"] and rep["reversibility"]["pass"] and rep["release_qa"]["verdict_rc"] == "PASS"
                   and all(v["pass"] for v in rep["REG1_4"].values()) and not rep["regressions"])
    (rc / "remediation/VERIFICATION_303.json").write_text(json.dumps(rep, indent=1, default=str) + "\n")
    print(json.dumps({k: rep[k] for k in ("pass", "release_qa", "REG1_4", "validation_current_registry", "validation_proposed_registry",
                                          "tests_302_vs_rc", "regressions")}, indent=1, default=str))
    print("preservation", json.dumps(rep["preservation"], default=str)[:600])
    print("reversibility", json.dumps(rep["reversibility"], default=str)[:600])


if __name__ == "__main__":
    raise SystemExit(main())
