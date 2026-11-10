#!/usr/bin/env python3
"""D4 rows fragment a2: T03R, T04R, T05, T06. Emits d4_rows_a2.json."""
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
    R("ontology_mappings_2837_row_delta_fully_characterized",
      f"{REL}/term_ontology_mappings.jsonl + {DB}:term_concept_map",
      "jsonl 334,231 - DB 331,394 = 2,837 dropped rows, fully characterized as the demotion event (D1: 'demoted mappings'); reverse diff 0",
      "2,837-row delta: 2,784 distinct mapping_ids over those rows absent from DB; missing-row census AMBIGUOUS 1,475 / EXACT_MATCH 881 / RELATED_TO 481 (sum 2,837), all mapping_disposition REVIEW_REQUIRED; all 565 affected term_ids still live in canonical_term; 0 DB mapping_ids absent from jsonl",
      "set difference on mapping_id; join census on missing rows; SELECT COUNT(*) FROM term_concept_map",
      "PASS",
      "supersedes original T03 (naive 334,231-vs-331,394 scored DISCREPANCY) and closes I04; the 2,837 figure matches D1's 'demoted mappings' record exactly — same event; recensed under D4-X01 and I04R"),
    R("term_definition_id_space_decomposition",
      f"{REL}/term_definitions.jsonl + {DB}:term_definition+removed_term_definition",
      "jsonl 1,150 = 588 live (termpipeline_t3_rules_v1) + 562 removed; DB live term_definition census = 588 T3 + 6,185 gap-G8 remediation rows",
      "jsonl 1,150 = 588 live overlap + 562 tombstoned; DB live 6,773 rows / 5,057 distinct ids (gap G8 6,185 rows + T3 588 rows); removed_term_definition 3,865 = 562 non-null-id + 3,303 NULL-id bulk tombstones (D2 L-2 tie); db-only distinct ids 4,469 belong to the gap-G8 remediation lineage outside release 1.0.1",
      "wc -l term_definitions.jsonl; definition_id set containment; GROUP BY extraction_run_id on term_definition",
      "PASS",
      "supersedes original T04 (naive 1,150-vs-6,773 scored DISCREPANCY): jsonl is the 1.0.1 T3 artifact while the DB table carries the separate remediation lineage; no unexplained remainder"),
    R("term_occurrence_sum_n_mentions",
      f"{DB}:term_occurrence",
      "2,505,684",
      "2,505,684",
      "SELECT SUM(n_mentions) FROM term_occurrence (read-only immutable URI)",
      "PASS", ""),
    R("mentions_source_census",
      f"{REL}/_mentions_summary.json",
      "cpu_ensemble 1,705,501 / qwen_vllm_body 366,123 / mesh_gazetteer 248,088 / qwen_ollama 186,024; all statuses OK",
      "cpu_ensemble 1,705,501 / qwen_vllm_body 366,123 / mesh_gazetteer 248,088 / qwen_ollama 186,024; sum 2,505,736; all OK",
      "_mentions_summary.json sources[].rows scan",
      "PASS", ""),
]

with open(os.path.join(HERE, "d4_rows_a2.json"), "w") as f:
    json.dump(rows, f, indent=1)
print(f"a2: wrote {len(rows)} rows")
