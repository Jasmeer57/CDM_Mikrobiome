#!/usr/bin/env python3
"""D4 assembler part 2 (of 2): write PASS_D4_terminology_chain.md, append the
48 rows to DATA_AUDIT.csv (csv.writer), re-parse-validate the CSV.
Expects _work/d4_rows_final.json (48 rows) from d4_rows_c2a.py.
Run from repo root."""
import csv
import json
import os
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
AUDIT = os.path.dirname(HERE)
CSV_PATH = os.path.join(AUDIT, "DATA_AUDIT.csv")

with open(os.path.join(HERE, "d4_rows_final.json")) as f:
    rows = json.load(f)
assert len(rows) == 48

HEADER = ["pass", "artifact", "check_name", "expected", "observed",
          "query_or_file", "status", "note"]
with open(CSV_PATH, newline="") as f:
    reader = list(csv.reader(f))
prior_data = reader[1:]
# CSV files produced by csv.writer use \r\n; the file has been maintained
# via csv.writer appends throughout, so match its existing newline form.
NL = "\r\n" if any(ln.endswith("\r\n") for ln in open(CSV_PATH, newline="")) else "\n"

# ---- append the 48 rows ----
with open(CSV_PATH, "a", newline="") as f:
    w = csv.writer(f)
    for r in rows:
        w.writerow([r["pass"], r["artifact"], r["check_name"], r["expected"],
                    r["observed"], r["query_or_file"], r["status"], r["note"]])

# ---- re-parse-validate ----
with open(CSV_PATH, newline="") as f:
    parsed = list(csv.reader(f))
header = parsed[0]
data = parsed[1:]
assert header == HEADER, f"header mismatch: {header}"
bad = [i for i, r in enumerate(data) if len(r) != 8]
assert not bad, f"rows with wrong col count: {bad}"
assert len(data) == 116, f"expected 116 data rows, got {len(data)}"
census = Counter((r[0], r[6]) for r in data)
print("CSV validated: header +", len(data), "data rows")
print("census:", dict(census))

with open(os.path.join(HERE, "d4_csv_state.json"), "w") as f:
    json.dump({"data_rows": len(data), "census": {f"{k[0]}|{k[1]}": v
              for k, v in census.items()}}, f, indent=1)
print("c2b phase A done (CSV appended + validated; report written by c2c)")
