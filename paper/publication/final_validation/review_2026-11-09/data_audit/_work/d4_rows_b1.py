#!/usr/bin/env python3
"""D4 rows fragment b1: C01, C02R, C03, C04, C05. Emits d4_rows_b1.json."""
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
    R("mapping_relation_census_jsonl",
      f"{REL}/term_ontology_mappings.jsonl",
      "RELATED_TO 188,313 / AMBIGUOUS 96,038 / EXACT_MATCH 38,403 / NO_MATCH_FOUND 11,477 (sum 334,231)",
      "RELATED_TO 188,313 / AMBIGUOUS 96,038 / EXACT_MATCH 38,403 / NO_MATCH_FOUND 11,477",
      "jsonl GROUP BY mapping_relation",
      "PASS", ""),
    R("mapping_source_census_jsonl_null_spelling",
      f"{REL}/term_ontology_mappings.jsonl + mapping_projection_summary.json",
      "cv_linking 292,221 / omop_local 21,881 / mesh_gazetteer 8,652 / JSON null 11,477 (summary spells null as 'none')",
      "jsonl: cv_linking 292,221 / omop_local 21,881 / mesh_gazetteer 8,652 / null 11,477; summary: cv_linking 292,221 / omop_local 21,881 / mesh_gazetteer 8,652 / none 11,477",
      "jsonl GROUP BY ontology_source vs mapping_projection_summary.json",
      "PASS",
      "supersedes original C02 (scored DISCREPANCY on the literal string 'none' vs JSON null): the summary file spells JSON null as \"none\"; counts tie exactly"),
    R("mapping_disposition_census_jsonl",
      f"{REL}/term_ontology_mappings.jsonl",
      "REVIEW_REQUIRED 322,754 / UNRESOLVED 11,477 (sum 334,231)",
      "REVIEW_REQUIRED 322,754 / UNRESOLVED 11,477",
      "jsonl GROUP BY mapping_disposition",
      "PASS", ""),
    R("auto_accept_eligible_and_accepted",
      f"{REL}/term_ontology_mappings.jsonl",
      "auto_accept_eligible 38,334 / auto_accepted 0",
      "auto_accept_eligible 38,334; auto_accepted 0",
      "jsonl count of auto_accept_eligible=true",
      "PASS",
      "auto_accepted stays 0 because calibration is NOT_CALIBRATED (T5b/c never produced a filled review sheet); consistent with mapping_projection_summary.json"),
    R("mapping_row_delta_2837_equals_demotion",
      f"{REL}/term_ontology_mappings.jsonl + {DB}:term_concept_map",
      "jsonl 334,231 - DB 331,394 = 2,837, matching D1's demoted-mappings figure",
      "delta exactly 2,837 rows; same event as the D1 'demoted mappings' record and the D4 T03R/I04R/X01 characterizations",
      "row-count delta tied across censuses",
      "PASS",
      "re-verification of the D4 delta tie ahead of the D6 mappings pass"),
]

with open(os.path.join(HERE, "d4_rows_b1.json"), "w") as f:
    json.dump(rows, f, indent=1)
print(f"b1: wrote {len(rows)} rows")
