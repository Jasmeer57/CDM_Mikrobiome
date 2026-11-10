#!/usr/bin/env python3
"""D4 assembler part 1 (of 2): merge fragments A/B/C1 (48 rows),
mutate the T03R row's note with the actual live-DB relation census
(flip to DISCREPANCY if the census had not tied), and write:
  - _work/d4_rows_final.json  (48 rows, final)
  - ../checks_D4.sql          (annotated SQL actually used)
Run from repo root."""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
AUDIT = os.path.dirname(HERE)          # data_audit/
DB = "releases/cdm_v3/3.0.3/microbiome_cdm_v3.db"
REL = "releases/terminology/1.0.1"

rows = []
for fn in ("d4_rows_a.json", "d4_rows_b.json", "d4_rows_c1.json"):
    with open(os.path.join(HERE, fn)) as f:
        rows.extend(json.load(f))
assert len(rows) == 48, f"expected 48 rows, got {len(rows)}"

with open(os.path.join(HERE, "d4_dbfacts.json")) as f:
    dbfacts = json.load(f)

# --- mutate the T03R row (mapping delta) with the live DB relation census ---
t03r = next(r for r in rows if r["check_name"] == "ontology_mappings_2837_row_delta_fully_characterized")
census = dbfacts["db_mapping_relation_census"]
delta = dbfacts["delta_jsonl_minus_db"]
t03r["observed"] = (
    "2,837-row delta: 2,784 distinct mapping_ids over those rows absent from DB; "
    "missing-row census AMBIGUOUS 1,475 / EXACT_MATCH 881 / RELATED_TO 481 (sum 2,837), "
    "all mapping_disposition REVIEW_REQUIRED; all 565 affected term_ids still live in canonical_term; "
    "0 DB mapping_ids absent from jsonl; live DB mapping_relation census verified in-pass: "
    f"RELATED_TO {census['RELATED_TO']:,} / AMBIGUOUS {census['AMBIGUOUS']:,} / "
    f"EXACT_MATCH {census['EXACT_MATCH']:,} / NO_MATCH_FOUND {census['NO_MATCH_FOUND']:,} "
    f"= 331,394 (jsonl minus per-relation delta "
    f"RELATED_TO {delta['RELATED_TO']} / AMBIGUOUS {delta['AMBIGUOUS']} / "
    f"EXACT_MATCH {delta['EXACT_MATCH']} / NO_MATCH_FOUND {delta['NO_MATCH_FOUND']}, "
    "summing to exactly 2,837)"
)
if not (dbfacts["delta_sum"] == 2837 and dbfacts["tcm_rows"] == 331394
        and dbfacts["asserts_expected_live_census"]):
    t03r["status"] = "DISCREPANCY"

with open(os.path.join(HERE, "d4_rows_final.json"), "w") as f:
    json.dump(rows, f, indent=1)
print(f"final rows: {len(rows)}; statuses:",
      {s: sum(1 for r in rows if r['status'] == s) for s in ('PASS', 'DISCREPANCY')})

# --- checks_D4.sql: annotated SQL actually used in D4 ---
SQL = """-- ============================================================================
-- checks_D4.sql — pass D4 (terminology chain 1.0.1 vs CDM 3.0.3)
-- Audit dir : paper/publication/final_validation/review_2026-11-09/data_audit/
-- Generated : 2026-11-09 (consolidation of _work/d4_part1..5.py runs; raw TSVs
--             in _work/d4_results_p1..5.tsv)
-- Frozen target DB (every connection strictly read-only):
--   sqlite3.connect("file:{DB}?mode=ro&immutable=1", uri=True)
--   PRAGMA query_only=ON
-- No paper text was read; offsets validated against stored LENGTHs only.
-- File-side checks (wc -l, sha256, jsonl GROUP censuses, set containment)
-- were executed as python scans in _work/d4_part1..5.py; the SQL forms are
-- documented here where a DB table was involved.
-- ============================================================================

-- §1 manifest integrity (M01, M02) ------------------------------------------
--   wc -l {REL}/MANIFEST.sha256                         -> 23
--   sha256sum -c MANIFEST.sha256                        -> 23 ok / 0 failed
--   (1.0.1 = 1.0.0's 22 files + OFFSET_FIX_REPORT.json)

-- §2 row-count ties (T01, T02R, T03R, T04R, T05) -----------------------------
SELECT COUNT(*) FROM term_mention;                        -- 2,505,684 (jsonl 2,505,735 - 51 load dedup)
SELECT COUNT(*) FROM term_occurrence;                     -- 1,362,931
SELECT SUM(n_mentions) FROM term_occurrence;              -- 2,505,684 (== term_mention rows)
SELECT COUNT(*) FROM canonical_term;                      -- 162,409 live
SELECT COUNT(*) FROM removed_canonical_term;              -- 3,582 removed (live+removed = jsonl 165,991)
SELECT COUNT(*) FROM term_concept_map;                    -- 331,394 (jsonl 334,231 - 2,837 demoted)
SELECT COUNT(*) FROM term_definition;                     -- 6,773 (5,057 distinct ids; 588 = T3 lineage)
SELECT COUNT(*) FROM removed_term_definition;             -- 3,865 (562 non-null id + 3,303 NULL-id)

-- §3 id-set containment (I01R, I02, I02b, I03, I04R) -------------------------
--   jsonl-vs-DB distinct-id set comparisons were run in python over full scans:
--     term_mentions   : distinct mention_id 1,948,059 vs 1,948,059; symmetric diff 0
--     canonical_terms : jsonl 165,991 -> live 162,409 + removed 3,582 + absent 0; reverse 0/0
--     definitions    : jsonl 1,150 -> live 588 + removed 562 + absent 0
--     mappings        : 2,784 jsonl-only mapping_ids; reverse diff 0
-- SQL form of the DB side (run in-pass, per-table):
SELECT COUNT(DISTINCT mention_id) FROM term_mention;      -- 1,948,059
SELECT COUNT(DISTINCT mapping_id) FROM term_concept_map;  -- 315,821

-- §4 jsonl censuses (C01..C04, F01..F07, D01..D03, R02, R03) -----------------
--   python scans of {REL}/term_ontology_mappings.jsonl, term_mentions.jsonl,
--   term_definitions.jsonl, canonical_terms.jsonl; see d4_results_p*.tsv for
--   the recorded censuses. OFFSET_FIX_REPORT.json ties:
--     mentions  EXACT 2,348,766 / CORRECTED 156,884 / UNANCHORED 85
--     link      LINKED 2,168,760 / NO_CANONICAL_TERM 299,854 / LINKED_BY_TYPE 30,049 / AMBIGUOUS 7,072
--     defs      EXACT 1,087 / CORRECTED 63 ; sections_shifted 75 (67x shift-1, 8x shift-2)

-- §5 live-DB mapping census tie (asserted in _work/d4_rows_c1b.py) -----------
SELECT mapping_relation, COUNT(*) FROM term_concept_map GROUP BY mapping_relation;
--   RELATED_TO 187,832 / AMBIGUOUS 94,563 / EXACT_MATCH 37,522 / NO_MATCH_FOUND 11,477 (sum 331,394)
--   jsonl minus DB per relation: 481 / 1,475 / 881 / 0 -> sum exactly 2,837 (demotion)

-- §6 definition run lineage (L01) ---------------------------------------------
SELECT extraction_run_id, COUNT(*) FROM term_definition GROUP BY extraction_run_id;
--   termpipeline_t3_rules_v1 588 ; gap G8 6,185 (separate remediation lineage)

-- §7 validation + provenance file ties (V01..V05, P01..P03R, R01R, R04, Q01..Q04)
--   python/json scans of validation_summary.json (453/0/0 papers; 3,553+453=4,006
--   sections; 2,505,650 mentions 100.0% resolved; overall COMPLETE),
--   terminology_validation.jsonl (VALIDATED 3553, NOT_APPLICABLE 453),
--   PROVENANCE.json (8 three-way hash ties; counts equal file rows;
--   auto_accept_eligible 38,334 / auto_accepted 0 / NOT_CALIBRATED),
--   terminology_taxonomy.json + taxonomy_summary.json (16 upper / 66 sub /
--   reserved [UNCERTAIN] / DRAFT / classified 0),
--   ontology_registry.json (local-only registry, structural),
--   calibration_v0_pre_fix/ (390 rows / 14 strata / all human_verdict empty;
--   draw universe 334,275 > current 334,231, delta 44; QUARANTINE.md tokens).
"""
SQL = SQL.replace("{DB}", DB).replace("{REL}", REL)
with open(os.path.join(AUDIT, "checks_D4.sql"), "w") as f:
    f.write(SQL)
print("wrote checks_D4.sql")
