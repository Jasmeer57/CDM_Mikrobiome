-- ============================================================================
-- checks_D4.sql — pass D4 (terminology chain 1.0.1 vs CDM 3.0.3)
-- Audit dir : paper/publication/final_validation/review_2026-11-09/data_audit/
-- Generated : 2026-11-09 (consolidation of _work/d4_part1..5.py runs; raw TSVs
--             in _work/d4_results_p1..5.tsv)
-- Frozen target DB (every connection strictly read-only):
--   sqlite3.connect("file:releases/cdm_v3/3.0.3/microbiome_cdm_v3.db?mode=ro&immutable=1", uri=True)
--   PRAGMA query_only=ON
-- No paper text was read; offsets validated against stored LENGTHs only.
-- File-side checks (wc -l, sha256, jsonl GROUP censuses, set containment)
-- were executed as python scans in _work/d4_part1..5.py; the SQL forms are
-- documented here where a DB table was involved.
-- ============================================================================

-- §1 manifest integrity (M01, M02) ------------------------------------------
--   wc -l releases/terminology/1.0.1/MANIFEST.sha256                         -> 23
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
--   python scans of releases/terminology/1.0.1/term_ontology_mappings.jsonl, term_mentions.jsonl,
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
