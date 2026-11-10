-- PASS D8 — provenance & the 45-run account (CDM 3.0.3)
-- Target: file:releases/cdm_v3/3.0.3/microbiome_cdm_v3.db?mode=ro&immutable=1
-- sqlite3 "file:releases/cdm_v3/3.0.3/microbiome_cdm_v3.db?mode=ro&immutable=1"
-- PRAGMA query_only=ON;
-- NEVER write/ATTACH/execute REVERT_303.sql (parse-only audit).
-- safe_census: only GROUP BY columns with cardinality<=40 and maxlen<=80;
-- provenance_evidence/revert_sql/description are length-bounded metadata,
-- never paper-derived text.

-- 1. run_metadata (11 keys)
SELECT key, CAST(value AS TEXT) FROM run_metadata ORDER BY key;
  -- cdm_version 3.0.3; derived_from sha256 1ddfcee2e90c... == 3.0.2 on-disk
  -- (sha256sum releases/cdm_v3/3.0.2/microbiome_cdm_v3.db)
  -- promoted_at 2026-11-02T08:04:46 == PROMOTION.txt timestamp

-- 2. extraction_run account
SELECT COUNT(*) FROM extraction_run;                                  -- 45
SELECT verification, COUNT(*) FROM extraction_run GROUP BY 1;
  -- VERIFIED_LOG 29 / VERIFIED_CODE_AND_HASH 5 / VERIFIED_RUN_EVENT 4
  -- / RECORDED_IN_DATA 3 / AS_IN_3.0.2_UNVERIFIED 4
SELECT extraction_run_id FROM extraction_run
  WHERE verification='AS_IN_3.0.2_UNVERIFIED';
  -- 28619916, CATNER_20261030T092214_1923898, CATLINK_v2, CATCLEAN_v3
SELECT stage_corrected, COUNT(*) FROM extraction_run GROUP BY 1;
  -- populated exactly for gap apply_G6/G7/G8/G9 (4 rows)
SELECT COUNT(*) FROM extraction_run WHERE completed_at IS NULL;         -- 35

-- 3. source-artifact hashes (verify on disk with sha256sum/hashlib)
SELECT extraction_run_id, source_artifact, source_artifact_sha256
  FROM extraction_run
  WHERE source_artifact_sha256 IS NOT NULL AND source_artifact_sha256 != '';
  -- cpu_ensemble_v1   -> releases/zenodo_v1/ner_453_sections/all_ner_sections_combined.csv  MATCH
  -- qwen_ollama_cell7c_v1 -> releases/zenodo_v1/qwen_sections_ner/qwen_sections_ner.csv      MATCH
  -- qwen35_vllm_body_v1 -> outputs/results/llm_ner_body/vllm_sections_ner.csv               MATCH
  -- mesh_gazetteer_2026 -> outputs/results/mesh_ner/mesh_ner_terms.csv                     MATCH
  -- termpipeline_t3_rules_v1 -> releases/terminology/1.0.0/term_definitions.jsonl           MATCH
  -- mapping_guards_v2 -> releases/frozen_output/02_data_catalogue/terminology/mapping_guards_v2
  --   (sha == member file mapping_remapped.jsonl; path labels the dir)

-- 4. REVERT_303.sql (PARSE-ONLY; python parse against sqlite_master + table_info)
  -- 56 statements; every DROP TABLE/INDEX and ALTER..DROP COLUMN target
  -- exists in 3.0.3; 0 problems

-- 5. cdm_change_log reversibility
SELECT COUNT(*) FROM cdm_change_log WHERE revert_sql IS NULL OR revert_sql='';
  -- 0 of 79
SELECT step, COUNT(*) FROM cdm_change_log GROUP BY 1;
  -- R1 12 / R2 15 / R3 7 / R4 17 / R5 13 / R6 9 / R7 1 / R8 4 / PROMOTE 1
SELECT kind, COUNT(*) FROM cdm_change_log GROUP BY 1;
  -- ADD_COLUMN 39 / FILL_NEW_COLUMN 24 / CREATE_UNIQUE_INDEX 9 / CREATE_TABLE 2
  -- / UPDATE_VALUE 2 / CREATE_INDEX 1 / CHECK 1 / INSERT_ROWS 1
SELECT SUM(rows_affected) FROM cdm_change_log;                           -- 3887671

-- 6. run anchoring (no dangling extraction_run_id anywhere)
SELECT dataset.extraction_run_id  -- actually: GROUP BY counts per table
-- per-table censuses:
-- dataset: CATNER_20261030T092214_1923898 2834 + CATCLEAN_20261030T173958 142 = 2976
-- assay/cohort/sample/data_asset: CATNER_20261030T092214_1923898 only
-- claim.extraction_run_id: CATNER 24272 + NULL 21395
-- claim.extraction_run_id_recovered: NULL 24272
--   + stage52_findings_extract-20261023T192306-2928671 21395 (in run table)
-- relation_evidence: stage53_triples_extract@2.1.0 34416
-- processing_lineage (5 rows): children 'gap G1','gap G9' dangle (D2 L-1 re-confirmed)

-- 7. identifier_crosswalk (4 rows)
SELECT "table", row_key, original_id_column, original_id_unique,
       substr(note,1,80) FROM identifier_crosswalk;
  -- term_mention / term_concept_map: original_id_unique=0 (D2 L-2 basis)
  -- relation / claim: unique

-- 8. new tables
SELECT COUNT(*) FROM identifier_crosswalk;   -- 4
SELECT COUNT(*) FROM relation_evidence;     -- 34416

-- 9. release bundle (shell):
-- (cd releases/cdm_v3/3.0.3 && sha256sum -c MANIFEST.sha256)   -> 0 failures
-- remediation/VERIFICATION_303.json -> pass:true, preservation 41->44 tables,
--   0 violations, regressions []; registry validation FAIL 5 (current) /
--   FAIL 2 (proposed) are design-registry mismatches quoted in-bundle.
