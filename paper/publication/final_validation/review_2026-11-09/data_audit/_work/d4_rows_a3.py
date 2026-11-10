#!/usr/bin/env python3
"""D4 rows fragment a3: T07, T08R, I01R, I02b. Emits d4_rows_a3.json."""
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
    R("mentions_rows_written_vs_manifest_coverage",
      f"{REL}/_mentions_summary.json + terminology_extraction_manifest.json",
      "rows_written 2,505,736 == extraction manifest coverage.mention_records 2,505,736 (both releases)",
      "written 2,505,736; manifest coverage.mention_records 2,505,736 in BOTH 1.0.0 and 1.0.1; shipped jsonl 2,505,735 (delta 1, the frozen G2 off-by-one — must not be patched); DB 2,505,684 (delta 51 vs jsonl = documented load dedup)",
      "chain across _mentions_summary.rows_written, terminology_extraction_manifest.coverage.mention_records, wc -l term_mentions.jsonl, COUNT(*) term_mention",
      "PASS",
      "supersedes original T07 note (its expected 2,505,735 was wrong): the frozen off-by-one is between rows written and rows shipped, present identically in 1.0.0 and 1.0.1"),
    R("mentions_offsets_verified_recovered_unverified_census",
      f"{REL}/_mentions_summary.json",
      "verified 2,505,616 + recovered 34 + unverified 85 = rows_written 2,505,736",
      "verified 2,505,616 + recovered 34 + unverified 85 = 2,505,736; control_char_surfaces 1,497",
      "_mentions_summary.json offsets_unverified/recovered scan",
      "PASS",
      "supersedes original T08 (expected sum==jsonl rows, a wrong model): census closes against rows_written as the artifact defines it"),
    R("mention_id_sets_identical_symmetric_diff_0",
      f"{REL}/term_mentions.jsonl + {DB}:term_mention",
      "distinct mention_id sets identical across jsonl and DB after the documented 51-row load dedup",
      "jsonl distinct 1,948,059; DB distinct 1,948,059; symmetric difference 0; row delta exactly 51 with no id lost (dup ids in jsonl 557,676 — multi-source repetition)",
      "distinct mention_id set comparison",
      "PASS",
      "supersedes original I01 (expected 51 absent ids — a wrong model of the documented dedup); corrected and re-recorded"),
    R("canonical_reverse_containment",
      f"{REL}/canonical_terms.jsonl + {DB}:canonical_term+removed_canonical_term",
      "0 DB term_ids absent from jsonl",
      "live-only 0, removed-only 0",
      "set difference (DB term_ids minus jsonl term_ids, both live and removed tables)",
      "PASS", ""),
]

with open(os.path.join(HERE, "d4_rows_a3.json"), "w") as f:
    json.dump(rows, f, indent=1)
print(f"a3: wrote {len(rows)} rows")
