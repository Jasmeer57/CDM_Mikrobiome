-- =====================================================================
-- PASS D2 — Referential integrity
-- FROZEN_DB = releases/cdm_v3/3.0.3/microbiome_cdm_v3.db  (sha256 5d23ba87d29ac...)
-- Open strictly read-only, every connection:
--   sqlite3.connect("file:releases/cdm_v3/3.0.3/microbiome_cdm_v3.db?mode=ro&immutable=1", uri=True)
--   PRAGMA query_only=ON
-- No paper text columns are selected anywhere in this file.
--
-- The DB declares 0 FK constraints (verified in D0 via PRAGMA foreign_key_list,
-- empty for all 44 tables). All edges below are NAME-IMPLIED and were
-- documented per-edge in PASS_D2_referential_integrity.md.
--
-- NOTE ON QUERY FORM: the "col NOT IN (SELECT pk FROM parent)" form lets
-- SQLite materialize the parent key list once. Correlated NOT EXISTS forms
-- on multimillion-row children (term_mention, 2,505,684 rows) timed out at
-- 600s in this environment; NOT IN completed in seconds.
--
-- Historical precision notes kept after each /* RESULT: ... */ marker.
-- =====================================================================

(PRAGMA query_only = ON);

-- =====================================================================
-- 1. Simple single-valued name-implied edges  -> ALL 0 ORPHANS
--    (NULL counts in PASS md; every non-null value resolves)
-- =====================================================================
SELECT COUNT(*) FROM assay            WHERE paper_id IS NOT NULL AND paper_id NOT IN (SELECT paper_id FROM paper);          -- /* 0 */
SELECT COUNT(*) FROM assay            WHERE study_id IS NOT NULL AND study_id NOT IN (SELECT study_id FROM study);          -- /* 0 */
SELECT COUNT(*) FROM cohort           WHERE paper_id IS NOT NULL AND paper_id NOT IN (SELECT paper_id FROM paper);          -- /* 0 */
SELECT COUNT(*) FROM cohort           WHERE study_id IS NOT NULL AND study_id NOT IN (SELECT study_id FROM study);          -- /* 0 */
SELECT COUNT(*) FROM dataset          WHERE paper_id IS NOT NULL AND paper_id NOT IN (SELECT paper_id FROM paper);          -- /* 0 */
SELECT COUNT(*) FROM dataset          WHERE study_id IS NOT NULL AND study_id NOT IN (SELECT study_id FROM study);          -- /* 0 */
SELECT COUNT(*) FROM data_asset       WHERE paper_id IS NOT NULL AND paper_id NOT IN (SELECT paper_id FROM paper);          -- /* 0 */
SELECT COUNT(*) FROM data_asset       WHERE study_id IS NOT NULL AND study_id NOT IN (SELECT study_id FROM study);          -- /* 0 */
SELECT COUNT(*) FROM claim            WHERE paper_id IS NOT NULL AND paper_id NOT IN (SELECT paper_id FROM paper);          -- /* 0 */
SELECT COUNT(*) FROM claim            WHERE study_id IS NOT NULL AND study_id NOT IN (SELECT study_id FROM study);          -- /* 0 (NULL 24272 = catalogue rows) */
SELECT COUNT(*) FROM claim            WHERE study_id_derived NOT IN (SELECT study_id FROM study);                           -- /* 0 */
SELECT COUNT(*) FROM claim_evidence   WHERE paper_id NOT IN (SELECT paper_id FROM paper);                                   -- /* 0 */
SELECT COUNT(*) FROM quantitative_result WHERE finding_id NOT IN (SELECT finding_id FROM claim);                           -- /* 0 */
SELECT COUNT(*) FROM quantitative_result WHERE paper_id NOT IN (SELECT paper_id FROM paper);                               -- /* 0 */
SELECT COUNT(*) FROM relation_evidence WHERE paper_id NOT IN (SELECT paper_id FROM paper);                                 -- /* 0 */
SELECT COUNT(*) FROM section          WHERE paper_id NOT IN (SELECT paper_id FROM paper);                                   -- /* 0 */
SELECT COUNT(*) FROM study            WHERE paper_id NOT IN (SELECT paper_id FROM paper);                                    -- /* 0 */
SELECT COUNT(*) FROM paper_publication WHERE paper_id NOT IN (SELECT paper_id FROM paper);                                  -- /* 0 */
SELECT COUNT(*) FROM paper_publication WHERE publication_id NOT IN (SELECT publication_id FROM publication);                -- /* 0 */
SELECT COUNT(*) FROM processing_event WHERE paper_id IS NOT NULL AND paper_id NOT IN (SELECT paper_id FROM paper);         -- /* 0 (NULL 31 run-event rows) */
SELECT COUNT(*) FROM source_asset    WHERE paper_id NOT IN (SELECT paper_id FROM paper);                                    -- /* 0 */
SELECT COUNT(*) FROM term_occurrence WHERE paper_id NOT IN (SELECT paper_id FROM paper);                                    -- /* 0 */
SELECT COUNT(*) FROM compendium_sample WHERE project NOT IN (SELECT project FROM compendium_project);                       -- /* 0 */

-- =====================================================================
-- 2. MULTI-VALUED ';'-joined id fields
--    These are NOT single-valued FKs: values are ';'-joined id lists and/or
--    the empty string '' as a null sentinel. Single-valued interpretation
--    produced FALSE "orphans" (e.g. assay.dataset_id "orphans=1806" that
--    were really multi-id strings or ''). Token-level check:
--      for each row value v (v not null, coalesce(v,'') <> ''):
--        tokens = [t.strip() for t in v.split(';') if t.strip()]
--        every token must exist in parent key set
--    Executed in Python (split logic not expressible without json extensions).
--    RESULT: 0 token-orphans, 0 rows containing an orphan token, for all:
--      assay.dataset_id       rows 8545   empty_str  732   multi(';')  1074
--      cohort.dataset_id      rows 7085   empty_str  679   multi        694
--      sample.dataset_id     rows 7530   empty_str  343   multi       1870
--      sample.cohort_id      rows 7530   empty_str  209   multi       3253
--      data_asset.dataset_id  rows 1992   empty_str   81   multi         85
--      claim.assay_id        rows 45667   empty_str 22969   multi     13343
--      claim.cohort_id       rows 45667   empty_str 23142   multi     13972
--      claim.dataset_id      rows 45667   empty_str 23870   multi     10088
-- =====================================================================
-- (results recorded above from the Python pass; no further SQL needed)

-- =====================================================================
-- 3. Heavy tables
-- =====================================================================
SELECT COUNT(*) FROM term_mention WHERE paper_id NOT IN (SELECT paper_id FROM paper);                        -- /* 0 */
SELECT COUNT(*) FROM term_mention WHERE canonical_term_id IS NOT NULL
  AND canonical_term_id NOT IN (SELECT term_id FROM canonical_term);                                       -- /* 0 vs live; 13,927 rows reference removed terms -> "removed-term cross-refs", section 4 */
SELECT COUNT(*) FROM term_mention WHERE extraction_run_id NOT IN (SELECT extraction_run_id FROM extraction_run);  -- /* 0 */

SELECT COUNT(*) FROM term_definition WHERE term_id IN (SELECT term_id FROM canonical_term);                  -- /* live rows */
SELECT COUNT(*) FROM term_definition WHERE term_id NOT IN (SELECT term_id FROM canonical_term);              -- /* 0 live-orphan rows: 138 rows on 69 distinct removed-term ids, all in removed_canonical_term (section 4) */
SELECT COUNT(*) FROM term_definition WHERE paper_id NOT IN (SELECT paper_id FROM paper);                     -- /* 0 */

SELECT COUNT(*) FROM term_concept_map WHERE term_id NOT IN (SELECT term_id FROM canonical_term);             -- /* 16,710 rows outside live term universe -> section 4, fully explained */
SELECT COUNT(*) FROM term_concept_map WHERE concept_id IS NOT NULL
  AND concept_id NOT IN (SELECT concept_id FROM concept);                                                    -- /* 0 (NULL 11,477 = NO_MATCH_FOUND rows, P07) */
SELECT COUNT(*) FROM term_concept_map WHERE extraction_run_id NOT IN (SELECT extraction_run_id FROM extraction_run);  -- /* 0 */

SELECT COUNT(*) FROM taxonomy_annotation WHERE term_id NOT IN (SELECT term_id FROM canonical_term);           -- /* 0 */
SELECT COUNT(*) FROM taxonomy_annotation WHERE extraction_run_id NOT IN (SELECT extraction_run_id FROM extraction_run);  -- /* 0 */

SELECT COUNT(*) FROM type_harmonization WHERE canonical_term_id IS NOT NULL
  AND canonical_term_id NOT IN (SELECT term_id FROM canonical_term);                                         -- /* 0 vs live; 423 rows = removed-term cross-refs (423 distinct ids, all in removed_canonical_term) */
SELECT COUNT(*) FROM type_harmonization WHERE term_id_llm NOT IN (SELECT term_id FROM canonical_term);       -- /* 0 vs live; 30,037 rows -> section 4 ('' sentinel 29,893 + removed-term 144) */
SELECT COUNT(*) FROM type_harmonization WHERE extraction_run_id NOT IN (SELECT extraction_run_id FROM extraction_run);  -- /* 0 */

SELECT COUNT(*) FROM relation WHERE subject_term_id <> '' AND subject_term_id NOT IN (SELECT term_id FROM canonical_term);  -- /* 0 vs live */
SELECT COUNT(*) FROM relation WHERE object_term_id <> '' AND object_term_id NOT IN (SELECT term_id FROM canonical_term);   -- /* 0 vs live */
-- '' sentinels: subject_term_id = '' on 2,104 rows, object_term_id = '' on 3,303 rows —
-- attribute not an FK violation: subject/object_entity_resolution_status = 'unresolved_string_match_v1'
-- (data-dictionary documented status meaning the endpoint never resolved to a term).
SELECT COUNT(*) FROM relation WHERE extraction_run_id NOT IN (SELECT extraction_run_id FROM extraction_run);  -- /* 0 */

-- =====================================================================
-- 4. Removed/unknown-term cross-references — EVERY non-live reference explained
--    term id universe: canonical_term 162,409 + removed_canonical_term 3,582
--                     = 165,991 distinct (= T02+T03, D1 row 24)
-- =====================================================================
SELECT COUNT(*) FROM (SELECT term_id FROM canonical_term
  UNION SELECT term_id FROM removed_canonical_term);                        -- /* 165991, disjoint union (0 overlaps) */

-- term_mention: every non-live canonical_term_id is self-labeled REMOVED
SELECT canonical_term_status, COUNT(*) FROM term_mention GROUP BY 1;        -- /* '' 2,491,757 / REMOVED 13,927 */
SELECT COUNT(*) FROM term_mention WHERE canonical_term_id IS NOT NULL
  AND canonical_term_id NOT IN (SELECT term_id FROM canonical_term)
  AND canonical_term_id IN (SELECT term_id FROM removed_canonical_term);    -- /* 13927 rows; ALL non-live refs are REMOVED terms */

-- term_definition: 138 rows on 69 distinct removed-term ids, all in removed_canonical_term
SELECT COUNT(*) FROM term_definition WHERE term_id IN (SELECT term_id FROM removed_canonical_term);  -- /* 138 */

-- term_concept_map: 16,710 rows outside the live term universe decompose exactly:
SELECT term_status, COUNT(*) FROM term_concept_map GROUP BY 1;
  -- /* '' 314,684 (live) / NOT_IN_TERMINOLOGY 5,237 / REMOVED 11,473 */
SELECT term_status, COUNT(*) FROM term_concept_map
  WHERE term_id IN (SELECT term_id FROM removed_canonical_term) GROUP BY 1;  -- /* REMOVED = 11,473 rows, all resolve */
SELECT candidate_rank, is_canonical_candidate, extraction_run_id, COUNT(*)
  FROM term_concept_map
  WHERE term_id NOT IN (SELECT term_id FROM canonical_term)
    AND term_id NOT IN (SELECT term_id FROM removed_canonical_term)
  GROUP BY 1,2,3;   -- /* 5,237 rows: candidate_rank=1, is_canonical_candidate=0, run=mapping_guards_v2;
                     --   mapping_disposition: REVIEW_REQUIRED 5,220 / REJECTED 17;
                     --   guard_status: kept 5,220 / rejected_guard 17;
                     --   data dictionary: term_status NOT_IN_TERMINOLOGY = "if unknown" */
-- spot-check: 5/5 sampled NOT_IN_TERMINOLOGY ids appear in terminology 1.0.1
--   term_ontology_mappings.jsonl but match zero canonical_terms.jsonl entries
--   (grep -c on releases/terminology/1.0.1/, 2026-11-09).

-- type_harmonization (40,141 rows): canonical_term_id NULL 12,271 / live 27,447 /
--   removed 423 / neither 0 (12,271+27,447+423 = 40,141). All 423
--   canonical_term_id refs outside live -> in removed_canonical_term.
--   term_id_llm non-live = 30,037 = '' sentinel 29,893 + removed-term ids
--   144 rows (128 distinct, all in removed_canonical_term); 0 rows in neither.
--   ('' here = string-match candidates that never got a term id; the classic
--   string-match v1 semantics, same family as relation.subject/object_term_id=''.)

-- =====================================================================
-- 5. claim <-> claim_evidence pairing (equal counts do NOT prove 1:1 — verified)
-- =====================================================================
SELECT COUNT(*) FROM claim;                                   -- /* 45667 */
SELECT COUNT(*) FROM claim_evidence;                          -- /* 45667 */
SELECT COUNT(DISTINCT finding_id) FROM claim;                 -- /* 45667 (unique across BOTH claim_sources) */
SELECT COUNT(DISTINCT finding_id) FROM claim_evidence;        -- /* 45667 */
SELECT COUNT(*) FROM (SELECT finding_id FROM claim
  EXCEPT SELECT finding_id FROM claim_evidence);              -- /* 0 */
SELECT COUNT(*) FROM (SELECT finding_id FROM claim_evidence
  EXCEPT SELECT finding_id FROM claim);                       -- /* 0 */
SELECT COUNT(*) FROM (SELECT finding_id FROM claim GROUP BY 1 HAVING COUNT(*)>1);        -- /* 0 */
SELECT COUNT(*) FROM (SELECT finding_id FROM claim_evidence GROUP BY 1 HAVING COUNT(*)>1); -- /* 0 */
SELECT claim_source, COUNT(*) FROM claim_evidence GROUP BY 1;
  -- /* catalogue_v3_1 24,272 / corpus_stage52 21,395 */
SELECT COUNT(*) FROM claim c JOIN claim_evidence e ON e.finding_id = c.finding_id
  WHERE c.paper_id <> e.paper_id OR c.claim_source <> e.claim_source;                      -- /* 0 contradiction rows */
-- conclusion: strict one-to-one, join key = finding_id (globally unique), no row mismatched.

-- =====================================================================
-- 6. occurrence_key network
-- =====================================================================
SELECT COUNT(DISTINCT occurrence_key) FROM term_mention;      -- /* 1362931 */
SELECT COUNT(*), COUNT(DISTINCT occurrence_key) FROM term_occurrence;  -- /* 1362931 / 1362931 */
SELECT COUNT(*) FROM (SELECT DISTINCT occurrence_key FROM term_mention
  EXCEPT SELECT occurrence_key FROM term_occurrence);         -- /* 0 */
SELECT COUNT(*) FROM (SELECT occurrence_key FROM term_occurrence
  EXCEPT SELECT DISTINCT occurrence_key FROM term_mention);   -- /* 0 */

-- =====================================================================
-- 7. term_definition.definition_id sharing — documented design, not corruption
-- =====================================================================
SELECT COUNT(*), COUNT(DISTINCT definition_id) FROM term_definition;                    -- /* 6773 / 5057 */
SELECT COUNT(*), COUNT(DISTINCT definition_id || '#' || term_id) FROM term_definition;  -- /* 6773 / 6773 */
SELECT COUNT(*) FROM (SELECT definition_id FROM term_definition GROUP BY 1 HAVING COUNT(*)>1);  -- /* 1177 groups */
SELECT COUNT(*) FROM (SELECT definition_id FROM term_definition GROUP BY 1
  HAVING COUNT(*)>1 AND (COUNT(DISTINCT paper_id)>1 OR COUNT(DISTINCT section_id)>1
    OR COUNT(DISTINCT definition_source)>1 OR COUNT(DISTINCT extraction_method)>1
    OR COUNT(DISTINCT extraction_run_id)>1));            -- /* 0: every dup group differs ONLY by term_id */
SELECT COUNT(*), COUNT(DISTINCT definition_id) FROM removed_term_definition;             -- /* 3865 / 562 (562 non-null, all HMDEF_<hex16>; 3303 rows NULL on BOTH definition_id and term_id = bulk tombstones) */
SELECT COUNT(*) FROM removed_term_definition r
  WHERE EXISTS (SELECT 1 FROM term_definition d WHERE d.definition_id = r.definition_id);  -- /* 0 live/removed collision */
-- interpretation: one HMDEF id per extraction span EVENT (e.g. ABBREVIATION_EXPANSION
-- span yielding 5 term definitions shares HMDEF_LLM_0000002); unique on
-- (definition_id, term_id) — the exact composite R6 created a unique index on
-- (cdm_change_log R6: CREATE_UNIQUE_INDEX term_definition(definition_id, term_id)).
-- Live id formats: 588 HMDEF_<hex16> + 4,469 HMDEF_LLM_<num> = 5,057 distinct.
-- The data dictionary documents the id pattern as ^HMDEF_[0-9a-f]{16}$ —
-- covering ONLY the 588 hex ids, not the 4,469 HMDEF_LLM_* ids (finding L-2).

-- =====================================================================
-- 8. Section references — MIXED CONVENTION, 100% resolvable (key finding)
--    Two id conventions coexist:
--      section_id_original = 'sec_NNN'   (catalogue-family + term_mention rows)
--      section_record_id   = 'HMPAPER_xxxxxxx:sec:NNN' (corpus_stage52 rows)
--    Unified check used throughout: value resolves if it matches EITHER
--    section.section_id_original OR section.section_record_id on the same paper.
-- =====================================================================
-- term_mention: single convention (sec_NNN only)
SELECT COUNT(*) FROM term_mention x WHERE x.section_id LIKE '%:sec:%';      -- /* 0 */
SELECT COUNT(*) FROM term_mention x WHERE x.section_id NOT IN (
  SELECT section_id_original FROM section);                                 -- /* 0 via (paper,section) composite; unified: 0 unresolvable of 2,505,684 */

-- claim.section_id: catalogue rows sec_NNN; claim.evidence_section_id: stage52 rows record_id
SELECT claim_source, section_id, evidence_section_id FROM claim LIMIT 0;  -- (cols below)
SELECT COUNT(*) FROM claim x WHERE x.section_id LIKE '%:sec:%';            -- /* 0 (all 24,272 non-null are sec_NNN) */
SELECT COUNT(*) FROM claim x WHERE x.evidence_section_id LIKE '%:sec:%';   -- /* 21,395 (all non-null are record_id) */

-- claim_evidence.section_id: BOTH conventions, split exactly by claim_source
SELECT claim_source,
       SUM(CASE WHEN section_id LIKE '%:sec:%' THEN 1 ELSE 0 END) AS record_id_conv,
       SUM(CASE WHEN section_id NOT LIKE '%:sec:%' THEN 1 ELSE 0 END) AS orig_conv
FROM claim_evidence WHERE section_id IS NOT NULL AND section_id <> '' GROUP BY 1;
  -- /* catalogue_v3_1: 0 / 24,272   corpus_stage52: 21,395 / 0 */

-- unified-resolution sweeps: any row failing BOTH conventions would count here
SELECT COUNT(*) FROM claim_evidence e
  WHERE e.section_id IS NOT NULL AND e.section_id <> ''
  AND NOT EXISTS (SELECT 1 FROM section s WHERE s.paper_id = e.paper_id
    AND (s.section_record_id = e.section_id OR s.section_id_original = e.section_id));   -- /* 0 */
SELECT COUNT(*) FROM claim x
  WHERE (x.section_id IS NOT NULL AND x.section_id <> ''
         AND NOT EXISTS (SELECT 1 FROM section s WHERE s.paper_id = x.paper_id
           AND (s.section_record_id = x.section_id OR s.section_id_original = x.section_id)))
     OR (x.evidence_section_id IS NOT NULL AND x.evidence_section_id <> ''
         AND NOT EXISTS (SELECT 1 FROM section s WHERE s.paper_id = x.paper_id
           AND (s.section_record_id = x.evidence_section_id OR s.section_id_original = x.evidence_section_id)));
  -- /* 0 */
-- same unified check on assay / cohort / sample / dataset / data_asset /
-- term_definition (all sec_NNN convention): 0 unresolvable each.
-- NULLs: claim.section_id NULL 21,395 (= corpus_stage52, which instead populates
--        evidence_section_id; the two columns are complementary by claim_source).

-- relation_evidence.section_record_id
SELECT COUNT(*) FROM relation_evidence e WHERE e.section_record_id IS NOT NULL
  AND e.section_record_id NOT IN (SELECT section_record_id FROM section);  -- /* 0 */

-- identifier_crosswalk rows corroborate the conventions (4 rows, read verbatim):
--   term_mention:   mention_row_id = mention_id|extraction_model (since 3.0.1)
--   term_concept_map: mapping_row_id = HMMAPROW_<row order>       (since 3.0.1)
--   relation:       canonical_triple_id unchanged
--   claim:          finding_id unique within each claim_source

-- =====================================================================
-- 9. Relation family
-- =====================================================================
SELECT COUNT(*), COUNT(DISTINCT canonical_triple_id) FROM relation;           -- /* 25788 / 25788 */
SELECT COUNT(*), COUNT(DISTINCT canonical_triple_id) FROM removed_relation;   -- /* 6925 / 6925 */
SELECT COUNT(*) FROM removed_relation r
  WHERE EXISTS (SELECT 1 FROM relation x WHERE x.canonical_triple_id = r.canonical_triple_id);  -- /* 0 overlap */
SELECT COUNT(DISTINCT canonical_triple_id) FROM relation_evidence
  WHERE canonical_triple_id NOT IN (SELECT canonical_triple_id FROM relation);   -- /* 0 evidence orphan ids */
SELECT COUNT(*) FROM relation
  WHERE NOT EXISTS (SELECT 1 FROM relation_evidence e
                    WHERE e.canonical_triple_id = relation.canonical_triple_id);  -- /* 0 relations without evidence */
SELECT COUNT(*) FROM relation_evidence
  WHERE canonical_triple_id IN (SELECT canonical_triple_id FROM relation);        -- /* 27,130 */
SELECT COUNT(*) FROM relation_evidence
  WHERE canonical_triple_id IN (SELECT canonical_triple_id FROM removed_relation);-- /* 7,286 */
SELECT COUNT(*) FROM relation_evidence;                                          -- /* 34,416 = 27,130 + 7,286 */
-- (D1 established relation_evidence has NO relation_id column; join key canonical_triple_id.)

-- =====================================================================
-- 10. processing_lineage — 2 DANGLING CHILD REFS (finding L-1)
-- =====================================================================
SELECT parent_id, child_id, relation FROM processing_lineage;   -- /* 5 rows, all 'input_of' */
--   ('CATNER_20261030T092214_1923898', 'CATCLEAN_v3')
--   ('CATCLEAN_v3',                   'CATLINK_v2')
--   ('CATLINK_v2',                    'gap G1')   <- DANGLING
--   ('28619916',                      'gap G8')
--   ('28619916',                      'gap G9')   <- DANGLING
-- Membership test against extraction_run.extraction_run_id:
SELECT parent_id, child_id,
       (SELECT COUNT(*) FROM extraction_run e WHERE e.extraction_run_id = processing_lineage.parent_id),
       (SELECT COUNT(*) FROM extraction_run e WHERE e.extraction_run_id = processing_lineage.child_id)
FROM processing_lineage;
--   parents: 5/5 resolve.  children: CATCLEAN_v3, CATLINK_v2, gap G8 resolve;
--   'gap G1' and 'gap G9' DO NOT.
-- Cause: lineage stores STAGE LABELS, but the extraction_run registry keys
-- those runs by JOB ID ('28671778' stage='gap G1'; '28671785' stage='gap G9';
-- '28671784' stage='gap G8'). 'gap G8' resolves only coincidentally — that
-- builder row reused the label as its id. processing_event.run_id is a THIRD
-- id domain (31 distinct run_ids, 7,347 event rows) — lineage ids are not
-- processing_event refs at all.
-- Data dictionary: all 3 processing_lineage columns NEEDS_EXPERT_REVIEW with
-- empty definitions.

-- =====================================================================
-- 11. extraction_run_id FK sweep on every child table — ALL 0 ORPHANS
-- =====================================================================
SELECT COUNT(*) FROM term_mention      WHERE extraction_run_id NOT IN (SELECT extraction_run_id FROM extraction_run);  -- /* 0 */
SELECT COUNT(*) FROM term_definition   WHERE extraction_run_id NOT IN (SELECT extraction_run_id FROM extraction_run);  -- /* 0 */
SELECT COUNT(*) FROM term_concept_map  WHERE extraction_run_id NOT IN (SELECT extraction_run_id FROM extraction_run);  -- /* 0 */
SELECT COUNT(*) FROM claim              WHERE extraction_run_id IS NOT NULL
  AND extraction_run_id NOT IN (SELECT extraction_run_id FROM extraction_run);  -- /* 0 (non-null col variant: extraction_run_id_recovered, R2) */
SELECT COUNT(*) FROM relation           WHERE extraction_run_id NOT IN (SELECT extraction_run_id FROM extraction_run);  -- /* 0 */
SELECT COUNT(*) FROM relation_evidence WHERE extraction_run_id NOT IN (SELECT extraction_run_id FROM extraction_run);  -- /* 0 */
SELECT COUNT(*) FROM taxonomy_annotation WHERE extraction_run_id NOT IN (SELECT extraction_run_id FROM extraction_run);  -- /* 0 */
SELECT COUNT(*) FROM type_harmonization WHERE extraction_run_id NOT IN (SELECT extraction_run_id FROM extraction_run);  -- /* 0 */
SELECT COUNT(*) FROM assay              WHERE extraction_run_id NOT IN (SELECT extraction_run_id FROM extraction_run);  -- /* 0 */
SELECT COUNT(*) FROM cohort             WHERE extraction_run_id NOT IN (SELECT extraction_run_id FROM extraction_run);  -- /* 0 */
SELECT COUNT(*) FROM sample             WHERE extraction_run_id NOT IN (SELECT extraction_run_id FROM extraction_run);  -- /* 0 */
SELECT COUNT(*) FROM dataset             WHERE extraction_run_id NOT IN (SELECT extraction_run_id FROM extraction_run);  -- /* 0 */
SELECT COUNT(*) FROM data_asset          WHERE extraction_run_id NOT IN (SELECT extraction_run_id FROM extraction_run);  -- /* 0 */
-- Only 4 distinct runs are used by term_mention (cpu_ensemble_v1 /
-- qwen_ollama_cell7c_v1 / qwen35_vllm_body_v1 / mesh_gazetteer_2026), matching the D1 method split.

-- =====================================================================
-- 12. extraction_run 45 vs load_audit 28 — explained, no discrepancy
-- =====================================================================
SELECT rows_offered, rows_kept, rows_dropped FROM load_audit WHERE "table" = 'extraction_run';  -- /* 28 / 28 / 0 */
SELECT COUNT(*), COUNT(DISTINCT extraction_run_id) FROM extraction_run;                        -- /* 45 / 45 */
-- cdm_change_log R1: INSERT_ROWS extraction_run = 17.  28 + 17 = 45. ✔
-- (D1 X04 verification split: VERIFIED_LOG 29 / VERIFIED_CODE_AND_HASH 5 /
--  VERIFIED_RUN_EVENT 4 / AS_IN_3.0.2_UNVERIFIED 4 / RECORDED_IN_DATA 3.)

-- =====================================================================
-- 13. PK / candidate-key uniqueness — ALL UNIQUE
-- =====================================================================
SELECT COUNT(*), COUNT(DISTINCT paper_id)             FROM paper;               -- /* 453 / 453 */
SELECT COUNT(*), COUNT(DISTINCT study_id)             FROM study;               -- /* 453 / 453 */
SELECT COUNT(*), COUNT(DISTINCT section_record_id)    FROM section;             -- /* 4006 / 4006 */
SELECT COUNT(*), COUNT(DISTINCT term_id)             FROM canonical_term;      -- /* 162409 / 162409 */
SELECT COUNT(*), COUNT(DISTINCT concept_id)          FROM concept;             -- /* 204817 / 204817 */
SELECT COUNT(*), COUNT(DISTINCT extraction_run_id)   FROM extraction_run;      -- /* 45 / 45 */
SELECT COUNT(*), COUNT(DISTINCT finding_id)           FROM claim;               -- /* 45667 / 45667 */
SELECT COUNT(*), COUNT(DISTINCT dataset_id)           FROM dataset;             -- /* 2976 / 2976 */
SELECT COUNT(*), COUNT(DISTINCT assay_id)             FROM assay;               -- /* 8545 / 8545 */
SELECT COUNT(*), COUNT(DISTINCT cohort_id)            FROM cohort;              -- /* 7085 / 7085 */
SELECT COUNT(*), COUNT(DISTINCT sample_group_id)      FROM sample;              -- /* 7530 / 7530 */
SELECT COUNT(*), COUNT(DISTINCT asset_id)             FROM data_asset;          -- /* 1992 / 1992 */
SELECT COUNT(*), COUNT(DISTINCT publication_id)       FROM publication;         -- /* 447 / 447 */
SELECT COUNT(*), COUNT(DISTINCT canonical_triple_id)  FROM relation;            -- /* 25788 / 25788 */
SELECT COUNT(*), COUNT(DISTINCT canonical_triple_id)  FROM removed_relation;   -- /* 6925 / 6925 */
SELECT COUNT(*), COUNT(DISTINCT project)              FROM compendium_project;  -- /* 452 / 452 */
SELECT COUNT(*), COUNT(DISTINCT srs)                  FROM compendium_sample;   -- /* 156330 / 156330 */
SELECT COUNT(*), COUNT(DISTINCT occurrence_key)       FROM term_occurrence;    -- /* 1362931 / 1362931 */
SELECT COUNT(*), COUNT(DISTINCT mention_row_id)       FROM term_mention;       -- /* 2505684 / 2505684 */
SELECT COUNT(*), COUNT(DISTINCT mapping_row_id)       FROM term_concept_map;   -- /* 331394 / 331394 */
SELECT COUNT(*), COUNT(DISTINCT finding_id || '#' || claim_source) FROM claim; -- /* 45667 / 45667 */
-- term_definition: definition_id alone NOT unique (6773/5057, section 7);
-- unique on (definition_id, term_id). R6 unique indexes corroborate:
-- claim(finding_id, claim_source); term_definition(definition_id, term_id);
-- taxonomy_annotation(term_id, taxonomy_version); quantitative_result(finding_id, claim_source);
-- claim_evidence(finding_id, claim_source); section(paper_id, section_id_original);
-- cohort(cohort_id); sample(sample_group_id); assay(assay_id).
-- Note: type_harmonization.term_id_llm = '' sentinel on 29,893 rows; those 30,037
-- non-live term_id_llm values are discussed in section 4.

-- =====================================================================
-- 14. compendium family composite
-- =====================================================================
SELECT COUNT(*) FROM compendium_sample_tag t
  WHERE NOT EXISTS (SELECT 1 FROM compendium_sample s
    WHERE s.project = t.project AND s.srr = t.srr AND s.srs = t.srs);  -- /* 0 of 3,333,310 rows */
SELECT COUNT(*), COUNT(DISTINCT project || '|' || srs) FROM compendium_sample;      -- /* 156330 / 156330 */
SELECT COUNT(*), COUNT(DISTINCT project || '|' || srr || '|' || srs) FROM compendium_sample;  -- /* 156330 / 156330 */

-- =====================================================================
-- 15. Small tables (no external refs by construction)
-- =====================================================================
-- intervention 1,935 rows (intervention_id / category / agent / n_findings)
-- body_site      29 rows (body_site_label / ontology_id / n_records)
-- identifier_crosswalk 4 rows (conventions, verbatim in section 8)
-- load_audit    36 rows (rows_offered/kept/dropped per table; extraction_run row in section 12)
