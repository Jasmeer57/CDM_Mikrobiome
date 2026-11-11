"""Check that CDM rows conform to the generated LinkML schema (linkml validator, JSON-Schema plugin).

For every class (= table) a random sample of rows (default up to 1,000; all rows for small tables) is read from the
DB (read-only) and validated as instances of that class.  Row -> instance conversion: NULL and '' are omitted
(empty string = missing), ';'-list reference columns are split into lists, values of mixed-storage string columns
are cast to str.  Default DB: the 3.2.0-candidate copy (3.1.0 + human_review).

    python src/scripts/fixes_v32/schema/validate_data.py [--db PATH] [--n 1000]
Writes schema/data_validation.csv and data_validation.json.
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import sqlite3
import sys
from collections import Counter
from pathlib import Path

import yaml
from linkml.validator import Validator
from linkml.validator.plugins import JsonschemaValidationPlugin

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from schema_common import CANDIDATE_DB, OUT  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=CANDIDATE_DB)
    ap.add_argument("--n", type=int, default=1000)
    a = ap.parse_args()
    sdir = OUT / "schema"
    spath = sdir / "microbiome_cdm_v3.linkml.yaml"
    schema = yaml.safe_load(spath.read_text())
    val = Validator(str(spath), validation_plugins=[JsonschemaValidationPlugin(closed=True)])
    con = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    rng = random.Random(20261111)
    out = []
    for cname, cls in schema["classes"].items():
        t = cls["annotations"]["sql_table"]
        attrs = cls["attributes"]
        n = con.execute(f'SELECT max(rowid) FROM "{t}"').fetchone()[0] or 0
        if n <= a.n:
            rows = con.execute(f'SELECT * FROM "{t}"').fetchall()
        else:
            ids = sorted(rng.sample(range(1, n + 1), a.n))
            rows = []
            for i in range(0, len(ids), 500):
                chunk = ids[i:i + 500]
                rows += con.execute(f'SELECT * FROM "{t}" WHERE rowid IN ({",".join("?" * len(chunk))})',
                                    chunk).fetchall()
        bad, msgs = 0, Counter()
        for r in rows:
            inst = {}
            for k in r.keys():
                v = r[k]
                if v is None or (isinstance(v, str) and v.strip() == ""):
                    continue
                spec = attrs.get(k, {})
                if spec.get("multivalued"):
                    v = [x.strip() for x in str(v).split(";") if x.strip()]
                elif spec.get("range") in ("string", None) or "mixed_storage" in spec.get("annotations", {}):
                    if spec.get("range") in ("integer", "float"):
                        pass
                    else:
                        v = str(v)
                elif spec.get("range") == "float" and isinstance(v, int):
                    v = float(v)
                elif spec.get("range") not in ("integer", "float") and not isinstance(v, str):
                    v = str(v)  # enum / class-reference ranges hold string values
                inst[k] = v
            rep = val.validate(inst, target_class=cname)
            if rep.results:
                bad += 1
                for res in rep.results[:3]:
                    msgs[res.message[:160]] += 1
        out.append({"class": cname, "table": t, "rows_checked": len(rows), "rows_invalid": bad,
                    "status": "PASS" if bad == 0 else "FAIL", "top_messages": " || ".join(
                        f"{m} (x{c})" for m, c in msgs.most_common(3))})
        print(f"{cname}: {len(rows)} rows, {bad} invalid", flush=True)
    with open(sdir / "data_validation.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)
    summ = {"db": str(a.db.name), "sample_per_table": a.n, "classes": len(out),
            "classes_pass": sum(r["status"] == "PASS" for r in out),
            "rows_checked": sum(r["rows_checked"] for r in out), "rows_invalid": sum(r["rows_invalid"] for r in out)}
    (sdir / "data_validation.json").write_text(json.dumps(summ, indent=1))
    print(json.dumps(summ, indent=1))


if __name__ == "__main__":
    main()
