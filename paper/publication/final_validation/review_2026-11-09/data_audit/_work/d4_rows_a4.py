#!/usr/bin/env python3
"""D4 rows fragment a4: I03, I04R, plus T02-definition run lineage is in fragment c.
Also merges all fragment-A json files into d4_rows_a.json (15 rows).
Rows here: I02 breadcrumb lives in a1 (canonical containment is folded there? No) —
this fragment writes I03 and I04R and runs the merge of a1..a4.
"""
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
    R("canonical_id_containment",
      f"{REL}/canonical_terms.jsonl + {DB}:canonical_term+removed_canonical_term",
      "all 165,991 jsonl term_ids present in canonical_term or removed_canonical_term; none absent",
      "live 162,409 + removed 3,582 + absent 0",
      "term_id set containment (jsonl term_ids minus DB live minus DB removed)",
      "PASS",
      "forward direction of the canonical split tie (reverse recorded at canonical_reverse_containment)"),
    R("definition_id_containment",
      f"{REL}/term_definitions.jsonl + {DB}:term_definition+removed_term_definition",
      "all 1,150 jsonl definition_ids found in term_definition or removed_term_definition",
      "live 588 + removed 562 + absent 0",
      "definition_id set containment",
      "PASS",
      "DB term_definition (6,773) and removed_term_definition (3,865) are supersets holding the separate gap-G8 remediation lineage; jsonl is the 1.0.1 T3 artifact"),
    R("mapping_rows_delta_2837_close_reverse_tie",
      f"{REL}/term_ontology_mappings.jsonl + {DB}:term_concept_map",
      "0 DB mapping_ids absent from jsonl (demoted rows are a jsonl-side superset, DB is a filtered subset)",
      "reverse diff 0; jsonl distinct mapping_ids 318,605; DB 315,821; the 2,784 jsonl-only ids correspond exactly to the 2,837 demoted rows documented at D1 and recensed at X01/I04R(T03R)",
      "set difference (DB mapping_ids minus jsonl mapping_ids)",
      "PASS",
      "records the reverse direction of the T03R delta so both sides of the 2,837-row demotion are independently tied"),
]

with open(os.path.join(HERE, "d4_rows_a4.json"), "w") as f:
    json.dump(rows, f, indent=1)
print(f"a4: wrote {len(rows)} rows")

# ---- merge all fragments into the single fragment-A file ----
all_rows = []
for fn in ("d4_rows_a1.json", "d4_rows_a2.json", "d4_rows_a3.json", "d4_rows_a4.json"):
    with open(os.path.join(HERE, fn)) as f:
        all_rows.extend(json.load(f))
with open(os.path.join(HERE, "d4_rows_a.json"), "w") as f:
    json.dump(all_rows, f, indent=1)
print(f"merge: d4_rows_a.json holds {len(all_rows)} rows")
for r in all_rows:
    print(" "+r["check_name"], "->", r["status"])
