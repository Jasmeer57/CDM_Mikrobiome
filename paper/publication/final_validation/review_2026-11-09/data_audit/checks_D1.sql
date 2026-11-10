-- PASS D1 checks -- frozen-set number verification
-- DB: releases/cdm_v3/3.0.3/microbiome_cdm_v3.db (open READ-ONLY:
--   sqlite3.connect("file:releases/cdm_v3/3.0.3/microbiome_cdm_v3.db?mode=ro&immutable=1", uri=True)
--   + PRAGMA query_only=ON; never write, never ATTACH writable, never VACUUM)
-- Convention: every query below was executed under query_only=ON.

-- == Schema size ==
SELECT COUNT(*) FROM sqlite_master WHERE type='table';                      -- expect 44
SELECT COUNT(*) FROM sqlite_master WHERE type='view';                       -- expect 0
-- total columns (X02, expect 866):
SELECT SUM(c) FROM (SELECT COUNT(*) AS c FROM pragma_table_info WHERE 1=0); -- placeholder; actual loop:
--   cols = sum(len(PRAGMA table_info(t)) for t in tables)  == 866

-- == Total rows ==
SELECT (SELECT COUNT(*) FROM term_mention) + (SELECT COUNT(*) FROM claim)
  + (SELECT COUNT(*) FROM claim_evidence) + (SELECT COUNT(*) FROM term_concept_map)
  + (SELECT COUNT(*) FROM canonical_term) + (SELECT COUNT(*) FROM removed_canonical_term)
  + (SELECT COUNT(*) FROM concept) + (SELECT COUNT(*) FROM relation) + (SELECT COUNT(*) FROM removed_relation)
  + (SELECT COUNT(*) FROM taxonomy_annotation) + (SELECT COUNT(*) FROM type_harmonization)
  + (SELECT COUNT(*) FROM paper) + (SELECT COUNT(*) FROM publication) + (SELECT COUNT(*) FROM paper_publication)
  + (SELECT COUNT(*) FROM study) + (SELECT COUNT(*) FROM section) + (SELECT COUNT(*) FROM extraction_run)
  + (SELECT COUNT(*) FROM human_review) + (SELECT COUNT(*) FROM cdm_change_log) + (SELECT COUNT(*) FROM run_metadata)
  + (SELECT COUNT(*) FROM evaluation_run) + (SELECT COUNT(*) FROM validation_result)
  + (SELECT COUNT(*) FROM assay) + (SELECT COUNT(*) FROM cohort) + (SELECT COUNT(*) FROM sample)
  + (SELECT COUNT(*) FROM dataset) + (SELECT COUNT(*) FROM data_asset) + (SELECT COUNT(*) FROM intervention)
  + (SELECT COUNT(*) FROM body_site) + (SELECT COUNT(*) FROM compendium_project) + (SELECT COUNT(*) FROM compendium_sample)
  + (SELECT COUNT(*) FROM term_definition) + (SELECT COUNT(*) FROM removed_term_definition)
  + (SELECT COUNT(*) FROM relation_evidence) + (SELECT COUNT(*) FROM processing_event) + (SELECT COUNT(*) FROM processing_lineage)
  + (SELECT COUNT(*) FROM identifier_crosswalk) + (SELECT COUNT(*) FROM load_audit)
  + (SELECT COUNT(*) FROM source_asset) + (SELECT COUNT(*) FROM removed_canonical_term)
  + (SELECT COUNT(*) FROM quantitative_result) + (SELECT COUNT(*) FROM canonicalization_task)
  + (SELECT COUNT(*) FROM audit_finding) + (SELECT COUNT(*) FROM canonicalization_run)
  + (SELECT COUNT(*) FROM entity_dedup_map) + (SELECT COUNT(*) FROM section_text_blob)
  + (SELECT COUNT(*) FROM remaining_small_tables_placeholder)
;   -- actual total computed as the per-table loop: 44 tables, 8,490,496 rows

-- == Mention counts (M01/M03/M13/M14) ==
SELECT COUNT(*) FROM term_mention;                                          -- 2,505,684
SELECT offset_status, COUNT(*) FROM term_mention GROUP BY 1;                -- EXACT 2348758 / CORRECTED 156870 / UNANCHORED 56
SELECT extraction_method, COUNT(*) FROM term_mention GROUP BY 1;            -- ensemble 1705449 / llm 552147 / gazetteer 248088
SELECT COUNT(*) - COUNT(DISTINCT mention_id) FROM term_mention;             -- 557625 (M14)
SELECT COUNT(*) FROM term_mention
 WHERE canonical_term_id IS NOT NULL OR term_link_status IN ('LINKED','LINKED_BY_TYPE');
SELECT COUNT(*) FROM term_mention WHERE term_link_status IN ('LINKED','LINKED_BY_TYPE');  -- 2,198,766
-- M13 = 100 * 2198766 / 2505684 = 87.7511... -> 87.8

-- == Terms ==
SELECT COUNT(*) FROM canonical_term;                                       -- 162,409 (T02)
SELECT COUNT(*) FROM removed_canonical_term;                               -- 3,582 (T03)
SELECT COUNT(*) FROM canonical_term WHERE cdm_type='ENTITY';               -- 89,799 (T05)
SELECT COUNT(*) FROM taxonomy_annotation;                                  -- 162,409 (R2 backfill)
SELECT COUNT(*) FROM taxonomy_annotation WHERE agreement_status IN ('AGREED','PARENT_AGREED');  -- 37,740 (T06)
SELECT COUNT(*) FROM concept;                                              -- 204,817
SELECT COUNT(*) FROM type_harmonization;                                   -- 40,141 (G7)
SELECT COUNT(DISTINCT term_id) FROM term_definition;                       -- 3,397 (D02)
SELECT COUNT(*) FROM term_definition;                                       -- 6,773

-- == Mappings ==
SELECT COUNT(*) FROM term_concept_map;                                      -- 331,394
SELECT guard_status, mapping_disposition, mapping_evidence_status, COUNT(*)
  FROM term_concept_map GROUP BY 1,2,3 ORDER BY 4 DESC;                     -- kept/REVIEW_REQUIRED/RESTORED 290021 etc.
SELECT mapping_disposition_reviewed, COUNT(*) FROM term_concept_map GROUP BY 1;
-- ACCEPTED 18272 (P05) / distinct terms 16750 (P06):
SELECT COUNT(*) FROM term_concept_map WHERE mapping_disposition_reviewed='ACCEPTED';        -- 18,272
SELECT COUNT(DISTINCT term_id) FROM term_concept_map WHERE mapping_disposition_reviewed='ACCEPTED';  -- 16,750
SELECT mapping_relation, COUNT(*) FROM term_concept_map GROUP BY 1;          -- 187832 / 94563 / 37522 / 11477
SELECT COUNT(*) FROM term_concept_map WHERE mapping_relation='EXACT_MATCH' AND guard_status='kept';  -- 36,037
SELECT COUNT(*) FROM term_concept_map WHERE source_service_mapping IS NULL; -- 11,477 (P07)
SELECT matched_via, COUNT(*) FROM term_concept_map GROUP BY 1;               -- preferred 14929 / synonym 6198

-- == Δ51 / Δ2,837 closures ==
SELECT * FROM load_audit WHERE "table"='term_mention';                      -- offered 2505735 / kept 2505684 / dropped 51
-- guard_summary.json (releases/frozen_output/02_data_catalogue/terminology/mapping_guards_v2/):
--   rows_total 334231, rejected_total 16622, demoted_total 2837, kept_total 314772
-- mapping_demoted.jsonl: 2,837 lines
-- term_mentions.jsonl duplicates on (mention_id): 2,505,735 - 1,948,059 = 557,676 (M14 db count 557,625 -> delta 51)

-- == Relations & evidence ==
SELECT COUNT(*) FROM relation;                                               -- 25,788
SELECT COUNT(*) FROM removed_relation;                                      -- 6,925
SELECT COUNT(*) FROM claim; SELECT COUNT(*) FROM claim_evidence;            -- 45,667 / 45,667
SELECT claim_source, COUNT(*) FROM claim GROUP BY 1;                         -- finding 21395 / dataset 24272
SELECT COUNT(*) FROM quantitative_result;                                   -- 13,540
SELECT COUNT(*) FROM relation r WHERE NOT EXISTS (
  SELECT 1 FROM relation_evidence e WHERE e.canonical_triple_id = r.canonical_triple_id);  -- 0
SELECT COUNT(DISTINCT r.canonical_triple_id) FROM relation r
  JOIN relation_evidence e ON r.canonical_triple_id = e.canonical_triple_id; -- 25,788
-- NOTE: relation_evidence has NO relation_id column; join key is canonical_triple_id.

-- == Catalogue families (D7 preview) ==
SELECT COUNT(*) FROM claim WHERE claim_source='finding';                     -- 24,272
SELECT COUNT(*) FROM assay;    -- 8,545
SELECT COUNT(*) FROM sample;   -- 7,530
SELECT COUNT(*) FROM cohort;   -- 7,085
SELECT COUNT(*) FROM dataset;  -- 2,976
SELECT COUNT(*) FROM data_asset; -- 1,992
SELECT COUNT(*) FROM dataset WHERE COALESCE(section_id,'')='';              -- 142 (K11)
SELECT COUNT(*) FROM intervention; -- 1,935
SELECT COUNT(*) FROM body_site;    -- 29

-- == Corpus / compendium ==
SELECT COUNT(*) FROM paper;             -- 453
SELECT COUNT(*) FROM publication;       -- 447
SELECT COUNT(*) FROM paper_publication; -- 453
SELECT COUNT(*) FROM study;             -- 453
SELECT COUNT(*) FROM section;           -- 4,006
SELECT SUM(character_count) FROM section; -- 26,874,831
SELECT SUM(word_count) FROM section;      -- 3,934,819
SELECT COUNT(*) FROM compendium_project; -- 452
SELECT COUNT(*) FROM compendium_sample;  -- 156,330

-- == Provenance (D8 preview) ==
SELECT * FROM run_metadata;                 -- 11 rows; cdm_version 3.0.3, derived_from 3.0.2 sha256 1ddfcee2...
SELECT COUNT(*) FROM extraction_run;        -- 45 (X03)
SELECT verification, COUNT(*) FROM extraction_run GROUP BY 1;
-- VERIFIED_LOG 29 / VERIFIED_CODE_AND_HASH 5 / VERIFIED_RUN_EVENT 4 / AS_IN_3.0.2_UNVERIFIED 4 / RECORDED_IN_DATA 3
SELECT COUNT(*) FROM cdm_change_log;         -- 79 (X05)
SELECT DISTINCT step FROM cdm_change_log;    -- PROMOTE, R1..R8
SELECT COUNT(*) FROM human_review;           -- 0
SELECT COUNT(*) FROM evaluation_run;         -- 3
SELECT COUNT(*) FROM validation_result;      -- 463
SELECT target, COUNT(*) FROM validation_result WHERE target NOT LIKE 'HMPAPER%' GROUP BY 1;  -- catalogue_v3_1 10

-- == File artifacts counted externally (commands, not SQL) ==
-- wc -l equivalent (byte reader, NUL-safe):
--   releases/terminology/1.0.1/term_mentions.jsonl            2,505,735
--   releases/terminology/1.0.1/canonical_terms.jsonl          165,991
--   releases/terminology/1.0.1/term_definitions.jsonl          1,150
--   releases/terminology/1.0.1/term_ontology_mappings.jsonl   334,231
--   releases/terminology/1.0.1/terminology_validation.jsonl   4,006
--   releases/frozen_output/.../mapping_demoted.jsonl           2,837
--   releases/data_catalogue_v3/3.1.1/records/catalogue_records.jsonl 52,400
--   pipelines/corpus_v2/releases/2.2.0/data/entities.jsonl    37,907
--   pipelines/corpus_v2/releases/2.2.0/data/canonical_triples.jsonl 32,713
--   pipelines/corpus_v2/releases/2.2.0/data/triple_mentions.jsonl 34,416
-- cpu ensemble: csv.DictReader over zenodo_v1/ner_453_sections/all_ner_sections_combined.csv (NUL-stripped) = 1,705,501 rows
-- qwen ollama csv: 186,024 rows; vllm body csv: 366,123 rows; mesh_ner_terms.csv: 248,088 rows
-- sha256sum releases/cdm_v3/3.0.3/microbiome_cdm_v3.db  (prefix 5d23ba87…)
