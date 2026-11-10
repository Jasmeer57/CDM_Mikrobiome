-- =====================================================================
-- PASS D3 — Mentions & entities (offsets, anchors, coverage, censuses)
-- FROZEN_DB = releases/cdm_v3/3.0.3/microbiome_cdm_v3.db  (sha256 5d23ba87...)
-- Open strictly read-only, every connection:
--   sqlite3.connect("file:releases/cdm_v3/3.0.3/microbiome_cdm_v3.db?mode=ro&immutable=1", uri=True)
--   PRAGMA query_only=ON
-- No paper-text column is selected anywhere in this file; every bounds
-- check uses stored section.character_count only.
--
-- Performance note: the per-occurrence aggregate cross-check was first
-- attempted as HAVING with correlated subqueries over 1.36M groups and
-- timed out at 900 s. The working form aggregates into a CTE and joins
-- it to term_occurrence (completes in ~1 min).
--
-- Claim-source semantics established in this pass (D3 §3, corrected
-- attribution — earlier ad-hoc notes had it backwards; trust this):
--   claim.claim_source splits the 45,667 claims exactly in two:
--   * catalogue_v3_1 (24,272 rows): carry evidence_anchor_status
--     (WHITESPACE 15,057 / EXACT 3,510 / NORMALISED 2,139 / FUZZY 1,670 /
--      RELOCATED 1,290 / UNANCHORED 560 / NO_EVIDENCE 46), char offsets on
--     23,526 of 24,272 rows (the 746 NULL = evidence_verified=0 rows:
--     UNANCHORED 505 / FUZZY 174 / NO_EVIDENCE 46 / NORMALISED 21),
--     evidence_span on 23,666 rows (606 NULL), evidence_verified 1/0
--     (23,526 / 746), section_id populated, evidence_locator_status NULL,
--     section_id_original-convention section keys.
--   * corpus_stage52 (21,395 rows): carry evidence_locator_status only
--     (verified_exact 2,005 / verified_normalized 16,602 /
--      unresolved_not_in_source 2,788), all char/span offsets NULL,
--     evidence_verified NULL, anchor_status NULL, evidence_section_id
--     populated (section_record_id convention).
--   Cross-tab witness (live):
--     claim_source x (charNULL, spanNULL, locatorNonNull, anchorNonNull, n):
--       catalogue_v3_1  (746,   606,   0,      24272, 24272)
--       corpus_stage52  (21395, 21395, 21395,  0,     21395)
--   746 + 21,395 = 22,141 NULL char pairs; 606 + 21,395 = 22,001 NULL
--   span pairs; 24,272 - 746 = 23,526 = evidence_verified=1 rows. All sums
--   tie exactly.
--
-- Section-id conventions (identifier_crosswalk): children may carry
-- either sec_NNN (section_id_original) or HMPAPER_xxx:sec:NNN
-- (section_record_id); every join below resolves BOTH on the same
-- paper_id.
-- =====================================================================

-- =====================================================================
-- 1. term_mention offset bounds and anchor semantics  ->  ALL CLEAN
-- =====================================================================
-- 1a. Bounds: 0 <= start < end <= stored character_count   /* RESULT: 0 */
SELECT COUNT(*) FROM term_mention m JOIN section s
  ON s.paper_id = m.paper_id
 AND (s.section_id_original = m.section_id OR s.section_record_id = m.section_id)
 WHERE m.start_offset < 0 OR m.start_offset >= m.end_offset OR m.end_offset > s.character_count;

-- 1b. Section resolvability   /* RESULT: 0 */
SELECT COUNT(*) FROM term_mention m WHERE NOT EXISTS (SELECT 1 FROM section s
  WHERE s.paper_id = m.paper_id
    AND (s.section_id_original = m.section_id OR s.section_record_id = m.section_id));

-- 1c. NULL offsets   /* RESULT: 56 */
SELECT COUNT(*) FROM term_mention WHERE start_offset IS NULL OR end_offset IS NULL;

-- 1d. offset_status census   /* EXACT 2348758 / CORRECTED 156870 / UNANCHORED 56
--        (sums to 2,505,684 = D1 term_mention row count) */
SELECT offset_status, COUNT(*) FROM term_mention GROUP BY 1;

-- 1e. UNANCHORED <-> NULL-offset exact correspondence   /* all three exact */
SELECT COUNT(*) FROM term_mention WHERE offset_status='UNANCHORED'
  AND (start_offset IS NULL OR end_offset IS NULL);              -- /* 56 */
SELECT COUNT(*) FROM term_mention WHERE offset_status='UNANCHORED'
  AND start_offset IS NOT NULL AND end_offset IS NOT NULL;       -- /* 0 */
SELECT COUNT(*) FROM term_mention WHERE offset_status<>'UNANCHORED'
  AND (start_offset IS NULL OR end_offset IS NULL);              -- /* 0 */

-- 1f. offset_correction semantics PER DATA DICTIONARY (line 1138): "characters
--     added to both offsets by the 1.0.1 correction (0 if none)". Observed
--     values confirm exactly: 0 on 2,348,814 rows (= EXACT 2,348,758 with no
--     correction + all 56 UNANCHORED), shifts of 1 char on 154,565 rows and
--     2 chars on 2,305 rows — all CORRECTED (154,565 + 2,305 = 156,870).
--     (An earlier draft note called this a "pass-count"; the dictionary's
--      character-delta semantics are the correct reading and fit the data.)
SELECT offset_correction, COUNT(*) FROM term_mention GROUP BY 1;
    -- /* 0: 2348814 / 1: 154565 / 2: 2305 */
SELECT offset_status, offset_correction, COUNT(*) FROM term_mention
 WHERE offset_correction <> 0 GROUP BY 1,2;
    -- /* CORRECTED x 1: 154565 / CORRECTED x 2: 2305 */

-- 1g. term_link_status census   /* ties D2: NULL canonical_term_id = 306,918
--        = NO_CANONICAL_TERM 299,846 + AMBIGUOUS 7,072 */
SELECT term_link_status, COUNT(*) FROM term_mention GROUP BY 1;
    -- /* LINKED 2168717 / NO_CANONICAL_TERM 299846 / LINKED_BY_TYPE 30049 / AMBIGUOUS 7072 */

-- 1h. canonical_term_status   /* '' live 2491757 / 'REMOVED' 13927 (D2 §4) */
SELECT canonical_term_status, COUNT(*) FROM term_mention GROUP BY 1;

-- 1i. confidence column is entirely NULL — DOCUMENTED ("null only",
--     dictionary line 868, status NEEDS_EXPERT_REVIEW), not a defect:
SELECT COUNT(*) FROM term_mention WHERE confidence IS NOT NULL;   -- /* 0 non-null */

-- =====================================================================
-- 2. term_occurrence: bounds + aggregate cross-checks  ->  ALL CLEAN
-- =====================================================================
-- 2a. Bounds vs character_count   /* RESULT: 0 */
SELECT COUNT(*) FROM term_occurrence o JOIN section s
  ON s.paper_id = o.paper_id
 AND (s.section_id_original = o.section_id OR s.section_record_id = o.section_id)
 WHERE o.start_offset < 0 OR o.start_offset >= o.end_offset OR o.end_offset > s.character_count;

-- 2b. Unresolvable sections   /* 0 */
SELECT COUNT(*) FROM term_occurrence o WHERE NOT EXISTS (SELECT 1 FROM section s
  WHERE s.paper_id = o.paper_id
    AND (s.section_id_original = o.section_id OR s.section_record_id = o.section_id));

-- 2c. NULL offsets   /* 48; MIN(start)=0, MAX(end)=242,820 */
SELECT COUNT(*) FROM term_occurrence WHERE start_offset IS NULL OR end_offset IS NULL;
SELECT MIN(start_offset), MAX(end_offset) FROM term_occurrence;

-- 2d. SUM(n_mentions)   /* 2,505,684 = exact tie to term_mention row count */
SELECT SUM(n_mentions) FROM term_occurrence;

-- 2e. Per-occurrence_key cross-check (CTE-join form; correlated HAVING
--     timed out at 900 s):
WITH agg AS (SELECT occurrence_key, COUNT(DISTINCT extraction_model) AS nm, COUNT(*) AS cnt
             FROM term_mention GROUP BY 1)
SELECT SUM(CASE WHEN a.nm <> o.n_models   THEN 1 ELSE 0 END) AS n_models_mismatch,
       SUM(CASE WHEN a.cnt <> o.n_mentions THEN 1 ELSE 0 END) AS n_mentions_mismatch,
       COUNT(*) AS total
FROM agg a JOIN term_occurrence o ON o.occurrence_key = a.occurrence_key;
    -- /* RESULT: 0 / 0 / 1,362,931 — every stored n_models and n_mentions
--        equals the live recomputation from term_mention rows */

-- =====================================================================
-- 3. claim / claim_evidence evidence anchors  ->  ALL CLEAN
--     (attribution per the header block; the mirror columns on claim and
--      claim_evidence are 1:1 identical — every census below was run on
--      both tables and returned the same numbers)
-- =====================================================================
-- 3a. Inverted / negative pairs   /* 0 on both char and span, both tables */
SELECT COUNT(*) FROM claim_evidence WHERE char_start IS NOT NULL AND char_end IS NOT NULL
  AND (char_start < 0 OR char_start >= char_end);
SELECT COUNT(*) FROM claim_evidence WHERE evidence_span_start IS NOT NULL AND evidence_span_end IS NOT NULL
  AND (evidence_span_start < 0 OR evidence_span_start >= evidence_span_end);

-- 3b. Bounds vs stored character_count   /* 0 on both, both tables */
SELECT COUNT(*) FROM claim_evidence e JOIN section s
  ON s.paper_id = e.paper_id
 AND (s.section_id_original = e.section_id OR s.section_record_id = e.section_id)
 WHERE e.char_end > s.character_count;
SELECT COUNT(*) FROM claim_evidence e JOIN section s
  ON s.paper_id = e.paper_id
 AND (s.section_id_original = e.section_id OR s.section_record_id = e.section_id)
 WHERE e.evidence_span_end > s.character_count;
-- claim side via the same unified join on c.section_id, and separately on
-- c.evidence_section_id for the stage52 rows — all 0 violations:
SELECT COUNT(*) FROM claim c JOIN section s
  ON s.paper_id = c.paper_id
 AND (s.section_id_original = c.section_id OR s.section_record_id = c.section_id)
 WHERE c.char_end > s.character_count;                                        -- /* 0 */
SELECT COUNT(*) FROM claim c JOIN section s
  ON s.paper_id = c.paper_id
 AND (s.section_id_original = c.evidence_section_id OR s.section_record_id = c.evidence_section_id)
 WHERE c.evidence_span_end > s.character_count;                                -- /* 0 */

-- 3c. NULL censuses   /* counts as listed; all by-design per attribution */
SELECT COUNT(*) FROM claim_evidence WHERE char_start IS NULL OR char_end IS NULL;                  -- /* 22141 */
SELECT COUNT(*) FROM claim_evidence WHERE evidence_span_start IS NULL OR evidence_span_end IS NULL;-- /* 22001 */
SELECT COUNT(*) FROM claim WHERE char_start IS NULL OR char_end IS NULL;                           -- /* 22141 */

-- 3d. anchor_status census (catalogue rows only; NULL 21,395 = stage52)   /* total 45,667 */
SELECT claim_source, COALESCE(evidence_anchor_status,'(null)'), COUNT(*)
  FROM claim GROUP BY 1,2 ORDER BY 1,3 DESC;
    -- /* catalogue_v3_1: WHITESPACE 15057 / EXACT 3510 / NORMALISED 2139 /
--        FUZZY 1670 / RELOCATED 1290 / UNANCHORED 560 / NO_EVIDENCE 46
--        (sum 24,272); corpus_stage52: (null) 21,395 */

-- 3e. locator_status census (stage52 rows only; NULL 24,272 = catalogue rows)
SELECT claim_source, evidence_locator_status, COUNT(*)
  FROM claim GROUP BY 1,2;
    -- /* corpus_stage52: verified_normalized 16,602 / unresolved_not_in_source 2,788 /
--        verified_exact 2,005 (sum 21,395); catalogue_v3_1: None 24,272 */

-- 3f. claim.evidence_verified   /* catalogue rows only; NULL 21,395 = stage52 */
SELECT claim_source, COALESCE(evidence_verified,'null'), COUNT(*)
  FROM claim GROUP BY 1,2;
    -- /* catalogue_v3_1 x 1: 23526 / catalogue_v3_1 x 0: 746 /
--        corpus_stage52 x null: 21395 */

-- 3g. Decomposition of the 746 evidence_verified=0 rows   /* sums to 746:
--        exactly the catalogue rows with NULL char offsets */
SELECT COALESCE(evidence_anchor_status,'(null)'), COUNT(*) FROM claim
 WHERE evidence_verified=0 GROUP BY 1;
    -- /* UNANCHORED 505 / FUZZY 174 / NO_EVIDENCE 46 / NORMALISED 21 */
SELECT COUNT(*) FROM claim WHERE evidence_verified=0
  AND (char_start IS NULL OR char_end IS NULL);                               -- /* 746 */

-- =====================================================================
-- 4. relation_evidence anchors + bounds  ->  ALL CLEAN
-- =====================================================================
-- 4a. anchor_status census   /* sum = 34,416 = D1 row count */
SELECT anchor_status, COUNT(*) FROM relation_evidence GROUP BY 1;
    -- /* WHITESPACE 24702 / EXACT 5375 / UNANCHORED 2224 / NORMALISED 2115 */

-- 4b. Bounds vs stored character_count (section_record_id convention)   /* 0 */
SELECT COUNT(*) FROM relation_evidence r JOIN section s
  ON s.paper_id = r.paper_id
 AND (s.section_id_original = r.section_record_id OR s.section_record_id = r.section_record_id)
 WHERE r.char_start < 0 OR r.char_start >= r.char_end OR r.char_end > s.character_count;

-- 4c. Unresolvable sections   /* 0 */
SELECT COUNT(*) FROM relation_evidence r WHERE NOT EXISTS (SELECT 1 FROM section s
  WHERE s.paper_id = r.paper_id
    AND (s.section_id_original = r.section_record_id OR s.section_record_id = r.section_record_id));

-- =====================================================================
-- 5. data_asset evidence anchors  ->  ALL CLEAN
-- =====================================================================
SELECT COUNT(*) FROM data_asset WHERE char_start IS NOT NULL AND char_end IS NOT NULL
  AND (char_start < 0 OR char_start >= char_end);                             -- /* 0 */
SELECT COUNT(*) FROM data_asset a JOIN section s
  ON s.paper_id = a.paper_id
 AND (s.section_id_original = a.section_id OR s.section_record_id = a.section_id)
 WHERE a.char_end > s.character_count;                                       -- /* 0 */
SELECT COUNT(*) FROM data_asset WHERE char_start IS NULL OR char_end IS NULL;  -- /* 76 */
SELECT evidence_anchor_status, COUNT(*) FROM data_asset GROUP BY 1;
    -- /* WHITESPACE 957 / EXACT 550 / NORMALISED 203 / FUZZY 125 /
--        RELOCATED 87 / UNANCHORED 70 (sum 1,992) */

-- =====================================================================
-- 6. section_text_sha256 stamps vs section.text_hash_sha256  ->  ALL MATCH
--    (each join is NON-VACUOUS: the coverage witness beside each check
--     equals the child table's full row count — tm 2,505,684 /
--     claim 45,667 / relation_evidence 34,416 / data_asset 1,992)
-- =====================================================================
-- coverage witnesses:
SELECT COUNT(*) FROM term_mention m JOIN section s
  ON s.paper_id = m.paper_id
 AND (s.section_id_original = m.section_id OR s.section_record_id = m.section_id);            -- /* 2505684 */
SELECT COUNT(*) FROM claim c JOIN section s
  ON s.paper_id = c.paper_id
 AND (s.section_id_original = COALESCE(c.section_id, c.evidence_section_id)
   OR s.section_record_id = COALESCE(c.section_id, c.evidence_section_id));                   -- /* 45667 */
SELECT COUNT(*) FROM relation_evidence x JOIN section s
  ON s.paper_id = x.paper_id
 AND (s.section_id_original = x.section_record_id OR s.section_record_id = x.section_record_id); -- /* 34416 */
SELECT COUNT(*) FROM data_asset a JOIN section s
  ON s.paper_id = a.paper_id
 AND (s.section_id_original = a.section_id OR s.section_record_id = a.section_id);            -- /* 1992 */

-- mismatch checks (all 0; zero NULL section_text_sha256 on any child table):
SELECT COUNT(*) FROM term_mention m JOIN section s
  ON s.paper_id = m.paper_id
 AND (s.section_id_original = m.section_id OR s.section_record_id = m.section_id)
 WHERE COALESCE(m.section_text_sha256,'') <> COALESCE(s.text_hash_sha256,'');                 -- /* 0 */
SELECT COUNT(*) FROM claim c JOIN section s
  ON s.paper_id = c.paper_id
 AND (s.section_id_original = COALESCE(c.section_id, c.evidence_section_id)
   OR s.section_record_id = COALESCE(c.section_id, c.evidence_section_id))
 WHERE COALESCE(c.section_text_sha256,'') <> COALESCE(s.text_hash_sha256,'');                 -- /* 0 */
SELECT COUNT(*) FROM relation_evidence x JOIN section s
  ON s.paper_id = x.paper_id
 AND (s.section_id_original = x.section_record_id OR s.section_record_id = x.section_record_id)
 WHERE COALESCE(x.section_text_sha256,'') <> COALESCE(s.text_hash_sha256,'');                 -- /* 0 */
SELECT COUNT(*) FROM data_asset a JOIN section s
  ON s.paper_id = a.paper_id
 AND (s.section_id_original = a.section_id OR s.section_record_id = a.section_id)
 WHERE COALESCE(a.section_text_sha256,'') <> COALESCE(s.text_hash_sha256,'');                 -- /* 0 */

-- =====================================================================
-- 7. Coverage & censuses (context; no paper text selected)
-- =====================================================================
-- 7a. Distinct mention-bearing (paper,section) pairs   /* 2,364 */
SELECT COUNT(*) FROM (SELECT DISTINCT paper_id, section_id FROM term_mention);
-- 7b. Papers with mentions   /* 453 */
SELECT COUNT(*) FROM (SELECT DISTINCT paper_id FROM term_mention);
-- 7c. Sections: zero-char 453 — all `sec_preface` (one per paper); chars>0: 3,553
SELECT COUNT(*) FROM section WHERE character_count > 0;                        -- /* 3553 */
SELECT COUNT(*) FROM section WHERE character_count = 0;                       -- /* 453 */
SELECT COUNT(*) FROM section WHERE character_count = 0
  AND section_id_original = 'sec_preface';                                    -- /* 453 */
-- 7d. Non-empty sections with no mentions   /* 1,189 */
SELECT COUNT(*) FROM section s WHERE s.character_count > 0
  AND NOT EXISTS (SELECT 1 FROM term_mention m
    WHERE m.paper_id = s.paper_id AND m.section_id = s.section_id_original);
-- 7e. section_quality_status census   /* sum 4,006 = D1 section count */
SELECT section_quality_status, COUNT(*) FROM section GROUP BY 1;
    -- /* COMPLETE 2746 / REVIEW_REQUIRED 1236 / PARTIAL 24 */
-- 7f. Mentions by run x model (sum = 2,505,684; ties D1):
--   cpu_ensemble_v1 / ner_model_ensemble:
--     en_core_sci_lg 960,674 / gliner_biomed 297,113 / gliner_medium 168,027
--     en_ner_craft_md 119,092 / en_ner_bc5cdr_md 80,584 / en_ner_jnlpba_md 52,989
--     biobert_diseases 26,970
--   qwen35_vllm_body_v1 / llm_section_ner: Qwen/Qwen3.5-4B 366,123
--   mesh_gazetteer_2026 / gazetteer_dictionary_match: mesh-gazetteer 248,088
--   qwen_ollama_cell7c_v1 / llm_section_ner: qwen3.5:4b 186,024
SELECT extraction_run_id, extraction_method, extraction_model, COUNT(*)
  FROM term_mention GROUP BY 1,2,3 ORDER BY 4 DESC;
-- 7g. review_status   /* UNVERIFIED on all 2,505,684 rows (nothing human-reviewed) */
SELECT review_status, COUNT(*) FROM term_mention GROUP BY 1;
-- 7h. unresolved_flags census (sum = 2,505,684):
--   [] 2,146,364 / ["SENTENCE_CLIPPED"] 357,755 / ["CONTROL_CHAR_SURFACE"] 1,102 /
--   ["SENTENCE_CLIPPED","CONTROL_CHAR_SURFACE"] 395 / ["OFFSET_UNVERIFIED"] 56 /
--   ["OFFSET_RECOVERED"] 12
--   (357,755 + 395 = 358,150 = rows with supporting_sentence_clipped=1;
--    OFFSET_UNVERIFIED 56 = the 56 UNANCHORED NULL-offset rows)
SELECT COALESCE(unresolved_flags,''), COUNT(*) FROM term_mention GROUP BY 1 ORDER BY 2 DESC;
SELECT COALESCE(supporting_sentence_clipped,0), COUNT(*) FROM term_mention
 WHERE unresolved_flags LIKE '%SENTENCE_CLIPPED%' GROUP BY 1;                 -- /* 1: 358150 */
-- 7i. entity_type census (sum = 2,505,684; DATA_ANALYSIS = 67,397 verified exactly):
--   ENTITY 960,674 / ORGANISM 380,345 / CHEMICAL 266,188 / DISEASE 209,648 /
--   CLINICAL 126,486 / DNA_RNA 93,941 / CELL_TYPE 86,215 / PROTEIN 79,316 /
--   DATA_ANALYSIS 67,397 / LAB_METHOD 59,885 / EXPERIMENTAL_METHOD 45,548 /
--   GENOMICS 40,891 / PATHWAY 35,123 / STUDY_DESIGN 29,540 / SAMPLE_METHOD 23,266 /
--   GO 1,221
SELECT entity_type, COUNT(*) FROM term_mention GROUP BY 1 ORDER BY 2 DESC;
SELECT COUNT(*) FROM term_mention WHERE entity_type='DATA_ANALYSIS';          -- /* 67397 */
