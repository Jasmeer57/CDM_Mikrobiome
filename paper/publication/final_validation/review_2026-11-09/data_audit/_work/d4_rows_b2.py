#!/usr/bin/env python3
"""D4 rows fragment b2: F01..F07 (OFFSET_FIX_REPORT ties). Emits d4_rows_b2.json."""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
REL = "releases/terminology/1.0.1"
DB = "microbiome_cdm_v3.db"
MAPS = f"{REL}/term_ontology_mappings.jsonl"
MENT = f"{DB}:term_mention"


def R(check_name, artifact, expected, observed, query_or_file, status, note=""):
    return {"pass": "D4", "artifact": artifact, "check_name": check_name,
            "expected": expected, "observed": observed,
            "query_or_file": query_or_file, "status": status, "note": note}


rows = [
    R("term_link_status_jsonl_eq_fixreport",
      f"{REL}/term_mentions.jsonl + OFFSET_FIX_REPORT.json",
      "LINKED 2,168,760 / NO_CANONICAL_TERM 299,854 / LINKED_BY_TYPE 30,049 / AMBIGUOUS 7,072",
      "LINKED 2,168,760 / NO_CANONICAL_TERM 299,854 / LINKED_BY_TYPE 30,049 / AMBIGUOUS 7,072 (jsonl census == OFFSET_FIX_REPORT link.*)",
      "jsonl census vs OFFSET_FIX_REPORT.json link:* fields",
      "PASS", ""),
    R("offset_status_jsonl_eq_fixreport",
      f"{REL}/term_mentions.jsonl + OFFSET_FIX_REPORT.json",
      "EXACT 2,348,766 / CORRECTED 156,884 / UNANCHORED 85",
      "EXACT 2,348,766 / CORRECTED 156,884 / UNANCHORED 85 (jsonl census == OFFSET_FIX_REPORT offsets)",
      "jsonl census vs OFFSET_FIX_REPORT.json offset fields",
      "PASS", ""),
    R("definitions_offset_status_jsonl_eq_fixreport",
      f"{REL}/term_definitions.jsonl + OFFSET_FIX_REPORT.json",
      "EXACT 1,087 / CORRECTED 63",
      "EXACT 1,087 / CORRECTED 63",
      "definitions jsonl census vs OFFSET_FIX_REPORT.json definitions section",
      "PASS", ""),
    R("sections_shifted_census",
      f"{REL}/OFFSET_FIX_REPORT.json",
      "75 sections = 67 shift-1 + 8 shift-2",
      "75 sections ({'1': 67, '2': 8})",
      "OFFSET_FIX_REPORT.json sections_shifted",
      "PASS", ""),
    R("jsonl_minus_db_delta_sums_to_51",
      f"{REL}/term_mentions.jsonl + {MENT}",
      "per-status jsonl-minus-DB deltas sum to exactly 51 (the load dedup), distributed over the statuses of duplicated mentions",
      "delta sums 51 on each axis: link_status LINKED 43 / NO_CANONICAL_TERM 8 / LINKED_BY_TYPE 0 / AMBIGUOUS 0; offset_status EXACT 8 / CORRECTED 14 / UNANCHORED 29; offset_correction 0:37 / >0:14 / 2:0; all non-negative",
      "census diff (jsonl - DB) over term_mention grouped by status axes",
      "PASS",
      "the 51 duplicated rows split cleanly across link/offset statuses with no negative bucket, consistent with pure duplicate removal"),
    R("corrected_rows_have_positive_offset_correction",
      f"{REL}/term_mentions.jsonl",
      "all 156,884 CORRECTED rows offset_correction>0",
      "corrected: >0 156,884, ==0 0",
      "jsonl predicate scan",
      "PASS", ""),
    R("exact_rows_have_zero_offset_correction",
      f"{REL}/term_mentions.jsonl",
      "0 EXACT rows with nonzero offset_correction",
      "0",
      "jsonl predicate scan",
      "PASS", ""),
]

with open(os.path.join(HERE, "d4_rows_b2.json"), "w") as f:
    json.dump(rows, f, indent=1)
print(f"b2: wrote {len(rows)} rows")
