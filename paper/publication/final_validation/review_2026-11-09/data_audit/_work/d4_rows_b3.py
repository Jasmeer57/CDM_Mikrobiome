#!/usr/bin/env python3
"""D4 rows fragment b3: V01..V05, D01..D03 + merge of b1..b3 into d4_rows_b.json.
D03's observed string is read verbatim from _work/d4_results_p3.tsv at runtime."""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
REL = "releases/terminology/1.0.1"
DB = "microbiome_cdm_v3.db"


def R(check_name, artifact, expected, observed, query_or_file, status, note=""):
    return {"pass": "D4", "artifact": artifact, "check_name": check_name,
            "expected": expected, "observed": observed,
            "query_or_file": query_or_file, "status": status, "note": note}


# verbatim observed string for D03 from the raw part-3 run
d03_observed = None
with open(os.path.join(HERE, "d4_results_p3.tsv")) as f:
    for ln in f:
        if ln.startswith("D4-D03_definitions_review_status_all_REVIEW_REQUIRED\t"):
            parts = ln.rstrip("\n").split("\t")
            d03_observed = parts[2]
assert d03_observed is not None, "D4-D03 row missing from d4_results_p3.tsv"

rows = [
    R("validation_papers_coverage",
      f"{REL}/validation_summary.json",
      "453 processed / 0 not processed / 0 flagged",
      "453 / 0 / 0",
      "validation_summary.json papers coverage fields",
      "PASS", ""),
    R("validation_sections_coverage",
      f"{REL}/validation_summary.json",
      "3,553 validated + 453 not_applicable = 4,006 total",
      "3553 + 453 = 4006",
      "validation_summary.json sections coverage",
      "PASS", ""),
    R("validation_mentions_offset_resolved",
      f"{REL}/validation_summary.json",
      "2,505,650 checked, 100.0% resolved, 0 unresolved",
      "2505650 checked, 100.0% resolved, 0 unresolved",
      "validation_summary.json mention_offset_verification",
      "PASS", ""),
    R("validation_overall_status",
      f"{REL}/validation_summary.json",
      "COMPLETE",
      "COMPLETE",
      "validation_summary.json overall status",
      "PASS", ""),
    R("validation_jsonl_status_census",
      f"{REL}/terminology_validation.jsonl",
      "VALIDATED 3,553 (= summary sections_validated) + NOT_APPLICABLE 453, over 453 papers",
      "{'NOT_APPLICABLE': 453, 'VALIDATED': 3553} over 453 papers",
      "terminology_validation.jsonl status census",
      "PASS",
      "jsonl row status is VALIDATED (not 'PASS')"),
    R("definitions_rows_total",
      f"{REL}/_definitions_summary.json",
      "1,150 (= 1,087 EXACT + 63 CORRECTED)",
      "1150",
      "_definitions_summary.json definitions count",
      "PASS", ""),
    R("definitions_by_definition_source",
      f"{REL}/_definitions_summary.json",
      "CONTEXTUAL_DESCRIPTION 1003 / ABBREVIATION_EXPANSION 126 / EXPLICIT_AUTHOR_DEFINITION 21",
      "{'CONTEXTUAL_DESCRIPTION': 1003, 'ABBREVIATION_EXPANSION': 126, 'EXPLICIT_AUTHOR_DEFINITION': 21}",
      "_definitions_summary.json by_definition_source",
      "PASS", ""),
    R("definitions_review_status_all_review_required",
      f"{REL}/term_definitions.jsonl",
      "every jsonl definition row review_status == REVIEW_REQUIRED",
      d03_observed,
      "jsonl predicate scan (review_status + provenance_class censuses)",
      "PASS", ""),
]

with open(os.path.join(HERE, "d4_rows_b3.json"), "w") as f:
    json.dump(rows, f, indent=1)
print(f"b3: wrote {len(rows)} rows (D03 observed verbatim: {d03_observed})")

# ---- merge fragments b1..b3 ----
all_rows = []
for fn in ("d4_rows_b1.json", "d4_rows_b2.json", "d4_rows_b3.json"):
    with open(os.path.join(HERE, fn)) as f:
        all_rows.extend(json.load(f))
with open(os.path.join(HERE, "d4_rows_b.json"), "w") as f:
    json.dump(all_rows, f, indent=1)
print(f"merge: d4_rows_b.json holds {len(all_rows)} rows")
for r in all_rows:
    print(" "+r["check_name"], "->", r["status"])
