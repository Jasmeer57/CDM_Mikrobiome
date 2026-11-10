#!/usr/bin/env python3
"""D4 rows fragment a1: M01, M02, T01, T02R. Emits d4_rows_a1.json.
Run from repo root. No DB access here; figures from raw D4 part-1 run."""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
REL = "releases/terminology/1.0.1"
DB = "microbiome_cdm_v3.db"


def R(check_name, artifact, expected, observed, query_or_file, status, note=""):
    return {"pass": "D4", "artifact": artifact, "check_name": check_name,
            "expected": expected, "observed": observed,
            "query_or_file": query_or_file, "status": status, "note": note}


rows = [
    R("manifest_files_listed",
      f"{REL}/MANIFEST.sha256",
      "23 entries (1.0.0's 22 files + OFFSET_FIX_REPORT.json added in 1.0.1)",
      "23 lines; all 23 files present and hashed",
      "wc -l MANIFEST.sha256; sha256sum -c",
      "PASS",
      "supersedes original M01 expectation (22): AGENTS.md's '22 files' describes release 1.0.0; 1.0.1 legitimately adds OFFSET_FIX_REPORT.json"),
    R("manifest_sha256_all_verified",
      f"{REL}/MANIFEST.sha256",
      "all listed files verify, 0 failures",
      "23 verified, 0 failed; bad=[]",
      "sha256sum -c MANIFEST.sha256 (python hashlib recompute)",
      "PASS", ""),
    R("mentions_jsonl_rows_vs_db_load_dedup",
      f"{REL}/term_mentions.jsonl + {DB}:term_mention",
      "2,505,735 = DB 2,505,684 + 51 documented load dedup",
      "jsonl 2,505,735 rows; DB 2,505,684 rows; delta exactly 51; distinct mention_id sets identical (1,948,059 both sides, symmetric diff 0)",
      "wc -l term_mentions.jsonl; SELECT COUNT(*) FROM term_mention (read-only immutable URI)",
      "PASS",
      "51-row load-dedup is the documented D1 tie; mention_id is not unique per row (multi-source repetition), so a row-level delta with zero id loss is expected"),
    R("canonical_terms_live_removed_split_ties_jsonl",
      f"{REL}/canonical_terms.jsonl + {DB}:canonical_term+removed_canonical_term",
      "jsonl 165,991 == live canonical_term 162,409 + removed_canonical_term 3,582",
      "165,991 == 162,409 + 3,582 exact tie; containment clean both directions (jsonl-absent 0; live-only 0; removed-only 0)",
      "wc -l canonical_terms.jsonl; SELECT COUNT(*) FROM canonical_term, removed_canonical_term",
      "PASS",
      "supersedes original T02 (naive 165,991-vs-162,409 row equality scored DISCREPANCY); live/removed_* split is the correct comparison model; retractions detailed in PASS_D4 report"),
]

with open(os.path.join(HERE, "d4_rows_a1.json"), "w") as f:
    json.dump(rows, f, indent=1)
print(f"a1: wrote {len(rows)} rows")
