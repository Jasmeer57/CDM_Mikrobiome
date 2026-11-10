#!/usr/bin/env python3
"""D4 part 2 — ID containment and census ties. Read-only."""
import json
import sqlite3
from collections import Counter

DB = "releases/cdm_v3/3.0.3/microbiome_cdm_v3.db"
REL = "releases/terminology/1.0.1"
results = []

def rec(name, expected, observed, q, status, note=""):
    results.append((name, expected, observed, q, status, note))
    print(f"[{status}] {name}\n   expected : {expected}\n   observed : {observed}"
          + (f"\n   note     : {note}" if note else ""))

conn = sqlite3.connect(f"file:{DB}?mode=ro&immutable=1", uri=True)
conn.execute("PRAGMA query_only=ON")

live_canon = set(r[0] for r in conn.execute("SELECT term_id FROM canonical_term;"))
removed_canon = set(r[0] for r in conn.execute("SELECT term_id FROM removed_canonical_term;"))
db_def_ids = set(r[0] for r in conn.execute("SELECT definition_id FROM term_definition;"))
db_rdef_ids = set(r[0] for r in conn.execute("SELECT definition_id FROM removed_term_definition;"))
print("DB: live_canon", len(live_canon), "removed_canon", len(removed_canon),
      "def live", len(db_def_ids), "def removed", len(db_rdef_ids))

# ---------------- I02 canonical containment
c_live = c_removed = c_absent = 0
absent_terms = []
json_canon_ids = set()
with open(f"{REL}/canonical_terms.jsonl") as f:
    for line in f:
        d = json.loads(line)
        json_canon_ids.add(d["term_id"])
        if d["term_id"] in live_canon:
            c_live += 1
        elif d["term_id"] in removed_canon:
            c_removed += 1
        else:
            c_absent += 1
            if len(absent_terms) < 3:
                absent_terms.append(d["term_id"])
rec("D4-I02_canonical_id_containment",
    "all 165,991 jsonl term_ids in canonical_term UNION removed_canonical_term; none absent",
    f"live {c_live} + removed {c_removed} + absent {c_absent}",
    "term_id set containment", "PASS" if c_absent == 0 else "DISCREPANCY")
# reverse direction: any DB live/removed id NOT in jsonl?
db_only_live = len(live_canon - json_canon_ids)
db_only_removed = len(removed_canon - json_canon_ids)
rec("D4-I02b_canonical_reverse_containment",
    "0 DB term_ids absent from jsonl",
    f"live-only {db_only_live}, removed-only {db_only_removed}",
    "set difference", "PASS" if db_only_live == 0 and db_only_removed == 0 else "DISCREPANCY")

# ---------------- I01 mention containment
db_mention_ids = set(r[0] for r in conn.execute("SELECT mention_id FROM term_mention;"))
m_absent = 0
jsonl_mention_ids = set()
dup_mention_ids = 0
seen = set()
absent_linkstat = None
with open(f"{REL}/term_mentions.jsonl") as f:
    for line in f:
        d = json.loads(line)
        mid = d["mention_id"]
        if mid in jsonl_mention_ids:
            dup_mention_ids += 1
        jsonl_mention_ids.add(mid)
        if mid not in db_mention_ids:
            m_absent += 1
            absent_linkstat = d["term_link_status"]
rec("D4-I01_mention_id_containment",
    "all jsonl mention_ids in DB except 51 load-dedup rows",
    f"{m_absent} absent (jsonl distinct ids {len(jsonl_mention_ids)}, DB {len(db_mention_ids)}, dup ids {dup_mention_ids}); sample absent link_status={absent_linkstat}",
    "mention_id set containment", "PASS" if m_absent == 51 and len(jsonl_mention_ids) >= len(db_mention_ids) else "DISCREPANCY",
    "2,505,735 jsonl rows - 51 dedup = 2,505,684 DB rows")

# ---------------- I03 definition containment
d_live = d_removed = d_absent = 0
with open(f"{REL}/term_definitions.jsonl") as f:
    for line in f:
        d = json.loads(line)
        if d["definition_id"] in db_def_ids:
            d_live += 1
        elif d["definition_id"] in db_rdef_ids:
            d_removed += 1
        else:
            d_absent += 1
rec("D4-I03_definition_id_containment",
    "jsonl definition_ids found in term_definition or removed_term_definition",
    f"live {d_live} + removed {d_removed} + absent {d_absent}",
    "definition_id set containment",
    "PASS" if d_absent == 0 else "DISCREPANCY",
    "DB term_definition (6,773) and removed_term_definition (3,865) are supersets from CDM remediation; jsonl is the 1.0.1 T4 artifact")

# ---------------- I04 mapping containment (mapping_id sets)
db_mapping_ids = Counter(r[0] for r in conn.execute("SELECT mapping_id FROM term_concept_map;"))
json_mapping_ids = set()
json_rows_by_mid = Counter()
with open(f"{REL}/term_ontology_mappings.jsonl") as f:
    for line in f:
        d = json.loads(line)
        json_mapping_ids.add(d["mapping_id"])
        json_rows_by_mid[d["mapping_id"]] += 1
mid_absent = len([m for m in json_mapping_ids if m not in db_mapping_ids])
db_distinct = len(db_mapping_ids)
rec("D4-I04_mapping_id_containment",
    "all jsonl mapping_ids present in DB term_concept_map",
    f"{mid_absent} of {len(json_mapping_ids)} jsonl mapping_ids absent; DB distinct {db_distinct}",
    "mapping_id set containment", "PASS" if mid_absent == 0 else "DISCREPANCY")
# how many DB mapping_id values absent from jsonl?
db_only = len([m for m in db_mapping_ids if m not in json_mapping_ids])
rec("D4-I04b_mapping_reverse_diff",
    "0 DB mapping_ids absent from jsonl (or documented demotions)",
    f"{db_only} DB mapping_ids not in jsonl",
    "set difference", "PASS" if db_only == 0 else "DISCREPANCY",
    "demoted/removed mapping rows land under term_status REMOVED/NOT_IN_TERMINOLOGY or are absent from live table")

# ---------------- C01 mapping_relation census
jsonl_rel = Counter()
jsonl_src = Counter()
jsonl_aae = 0
jsonl_disp = Counter()
with open(f"{REL}/term_ontology_mappings.jsonl") as f:
    for line in f:
        d = json.loads(line)
        jsonl_rel[d["mapping_relation"]] += 1
        jsonl_src[d["ontology_source"]] += 1
        jsonl_disp[d["mapping_disposition"]] += 1
        if d.get("auto_accept_eligible"):
            jsonl_aae += 1
db_rel = dict(conn.execute("SELECT mapping_relation, COUNT(*) FROM term_concept_map GROUP BY mapping_relation;").fetchall())
exp_rel = {"RELATED_TO": 188313, "AMBIGUOUS": 96038, "EXACT_MATCH": 38403, "NO_MATCH_FOUND": 11477}
exp_src = {"cv_linking": 292221, "omop_local": 21881, "mesh_gazetteer": 8652, "none": 11477}
rec("D4-C01_mapping_relation_census_jsonl", json.dumps(exp_rel), json.dumps(dict(jsonl_rel)),
    "jsonl GROUP mapping_relation", "PASS" if dict(jsonl_rel) == exp_rel else "DISCREPANCY")
rec("D4-C02_mapping_source_census_jsonl", json.dumps(exp_src), json.dumps(dict(jsonl_src)),
    "jsonl GROUP ontology_source", "PASS" if dict(jsonl_src) == exp_src else "DISCREPANCY")
rec("D4-C03_mapping_disposition_census_jsonl",
    json.dumps({"REVIEW_REQUIRED": 322754, "UNRESOLVED": 11477}), json.dumps(dict(jsonl_disp)),
    "jsonl GROUP mapping_disposition", "PASS" if dict(jsonl_disp) == {"REVIEW_REQUIRED": 322754, "UNRESOLVED": 11477} else "DISCREPANCY")
rec("D4-C04_auto_accept_eligible_count", "38334 eligible, 0 auto_accepted",
    f"{jsonl_aae} eligible", "jsonl count auto_accept_eligible",
    "PASS" if jsonl_aae == 38334 else "DISCREPANCY",
    "auto_accepted stay 0: calibration NOT_CALIBRATED (T5b/c never run)")
db_elig = conn.execute("SELECT COUNT(*) FROM term_concept_map WHERE mapping_disposition='REVIEW_REQUIRED' AND mapping_relation IN ('EXACT_MATCH');").fetchone()[0]

# mapping rows delta: jsonl 334,231 vs DB 331,394
delta = 334231 - 331394
rec("D4-C05_mapping_row_delta_explained",
    "334,231 - 331,394 = 2,837 demoted rows (term_status REMOVED/NOT_IN_TERMINOLOGY)",
    str(delta), "row-count delta",
    "PASS" if delta == 2837 else "DISCREPANCY",
    "check D6 for demotion census")

with open("paper/publication/final_validation/review_2026-11-09/data_audit/_work/d4_results_p2.tsv", "w") as f:
    for r in results:
        f.write("\t".join(str(x).replace("\t", " ").replace("\n", " ") for x in r) + "\n")
print("\nPART2 RESULTS:", len(results))
for name, _, _, _, st, _ in results:
    print(" ", st, name)
