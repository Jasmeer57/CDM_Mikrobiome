#!/usr/bin/env python3
"""D4 rows fragment c1b: L01, Q01..Q04 + live-DB census assertions (dbfacts)
+ merge of c1a/c1b into d4_rows_c1.json.

Live DB facts asserted here (read-only immutable URI):
  - tcm rows 331,394; mapping_relation census RELATED_TO 187,832 /
    AMBIGUOUS 94,563 / EXACT_MATCH 37,522 / NO_MATCH_FOUND 11,477
  - jsonl-minus-DB per-relation delta == the 2,837 dropped rows exactly.
Emits _work/d4_dbfacts.json too (consumed by d4_rows_c2.py for T03R note).
"""
import json
import os
import sqlite3
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
REL = "releases/terminology/1.0.1"
DB = "releases/cdm_v3/3.0.3/microbiome_cdm_v3.db"

con = sqlite3.connect(f"file:{DB}?mode=ro&immutable=1", uri=True)
con.execute("PRAGMA query_only=ON")

tcm_rows = con.execute("SELECT COUNT(*) FROM term_concept_map").fetchone()[0]
db_rel = dict(con.execute(
    "SELECT mapping_relation, COUNT(*) FROM term_concept_map GROUP BY mapping_relation"))
con.close()

jsonl_rel = Counter()
with open(f"{REL}/term_ontology_mappings.jsonl") as f:
    for ln in f:
        if ln.strip():
            jsonl_rel[json.loads(ln)["mapping_relation"]] += 1
delta = {k: jsonl_rel[k] - db_rel.get(k, 0) for k in jsonl_rel}
assert all(v >= 0 for v in delta.values())

exp_live = {"RELATED_TO": 187832, "AMBIGUOUS": 94563,
            "EXACT_MATCH": 37522, "NO_MATCH_FOUND": 11477}
facts_ok = (tcm_rows == 331394 and db_rel == exp_live
            and sum(delta.values()) == 2837)

dbfacts = {
    "tcm_rows": tcm_rows,
    "db_mapping_relation_census": db_rel,
    "jsonl_relation_census": dict(jsonl_rel),
    "delta_jsonl_minus_db": delta,
    "delta_sum": sum(delta.values()),
    "asserts_expected_live_census": facts_ok,
    "live_census_expected": [
        "RELATED_TO 187,832 (jsonl 188,313 - 481)",
        "AMBIGUOUS 94,563 (jsonl 96,038 - 1,475)",
        "EXACT_MATCH 37,522 (jsonl 38,403 - 881)",
        "NO_MATCH_FOUND 11,477 (jsonl 11,477 - 0)",
    ],
}
with open(os.path.join(HERE, "d4_dbfacts.json"), "w") as f:
    json.dump(dbfacts, f, indent=1)
assert facts_ok, "live DB census does not tie: %r" % (dbfacts,)


def R(check_name, artifact, expected, observed, query_or_file, status, note=""):
    return {"pass": "D4", "artifact": artifact, "check_name": check_name,
            "expected": expected, "observed": observed,
            "query_or_file": query_or_file, "status": status, "note": note}


rows = [
    R("definition_run_lineage",
      f"{REL}/term_definitions.jsonl + {DB}:term_definition",
      "jsonl definitions (1,150) = 588 live in DB (all run termpipeline_t3_rules_v1) + 562 tombstoned; the DB table's extra 4,469 rows are the separate 'gap G8' remediation lineage, not part of release 1.0.1",
      "jsonl runs {'termpipeline_t3_rules_v1': 1150}; DB live overlap 588; DB live ids not in jsonl 4,469; DB live distinct ids 5,057; DB live census {'gap G8': 6,185 rows, 'termpipeline_t3_rules_v1': 588 rows}",
      "definition_id set overlap + GROUP BY extraction_run_id on term_definition",
      "PASS",
      "gap-G8 remediation lineage (D2 L-1/L-2 family); the 588+562=T3 accounting closes the jsonl side with no unexplained remainder"),
    R("calibration_v0_shape",
      f"{REL}/calibration_v0_pre_fix/_calibration_sample_summary.json",
      "mappings_rows_total 334,275 / sampled 390 / primary 300 / control 90",
      "mappings_rows_total 334,275 / sampled_rows 390 / primary_rows 300 / control_rows 90",
      "_calibration_sample_summary.json counts",
      "PASS", ""),
    R("calibration_v0_rows_strata_emptyverdicts",
      f"{REL}/calibration_v0_pre_fix/calibration_sample.csv + .jsonl",
      "390 data rows (300 primary + 90 control, 14 strata: five 60-row EXACT_MATCH strata + nine 10-row strata), csv==jsonl rows, all 390 human_verdict cells empty",
      "csv rows 390, jsonl rows 390, strata 14, empty verdicts 390; census: bioportal|AMBIGUOUS 10, bioportal|EXACT_MATCH 60, bioportal|RELATED_TO 10, mesh|EXACT_MATCH 60, ncbi_taxon|RELATED_TO 10, none|NO_MATCH_FOUND 10, ols|AMBIGUOUS 10, ols|EXACT_MATCH 60, ols|RELATED_TO 10, omop|AMBIGUOUS 10, omop|EXACT_MATCH 60, umls|AMBIGUOUS 10, umls|EXACT_MATCH 60, umls|RELATED_TO 10",
      "calibration_sample.csv/.jsonl census",
      "PASS", ""),
    R("calibration_quarantine_declaration_tokens",
      f"{REL}/calibration_v0_pre_fix/QUARANTINE.md",
      "declares: draw universe 334,275 (pre-fix); current 334,231; producing build 28609294; current build 28619916; status superseded; pooling forbidden",
      "all tokens present: True (the earlier 'verdict statement: False' hit was only a case-sensitivity artifact of the probe; direct empty-cell scan proves the 390 empty verdicts)",
      "QUARANTINE.md text scan + direct empty-cell verification",
      "PASS",
      "verbatim-token probe vs direct scan reconciled"),
    R("calibration_draw_universe_delta",
      f"{REL}/calibration_v0_pre_fix/_calibration_sample_summary.json + {REL}/term_ontology_mappings.jsonl",
      "draw universe 334,275 exceeds current 1.0.1 mappings 334,231 by 44 rows; the v0 sample predates the mapping rebuild and is NOT a sample of the current table",
      "declared draw universe 334,275; current mapping rows 334,231; delta 44",
      "summary vs jsonl row count",
      "PASS",
      "quarantine + mandatory redraw before use is the documented disposition"),
]

with open(os.path.join(HERE, "d4_rows_c1b.json"), "w") as f:
    json.dump(rows, f, indent=1)
print(f"c1b: wrote {len(rows)} rows; dbfacts ok={facts_ok}")
print(" live relation census:", db_rel, "| delta:", delta, "| sum:", sum(delta.values()))

# ---- merge c1a + c1b ----
all_rows = []
for fn in ("d4_rows_c1a.json", "d4_rows_c1b.json"):
    with open(os.path.join(HERE, fn)) as f:
        all_rows.extend(json.load(f))
with open(os.path.join(HERE, "d4_rows_c1.json"), "w") as f:
    json.dump(all_rows, f, indent=1)
print(f"merge: d4_rows_c1.json holds {len(all_rows)} rows")
for r in all_rows:
    print(" "+r["check_name"], "->", r["status"])
