-- PASS D6 — controlled-vocabulary mapping re-verification
-- Target: file:releases/cdm_v3/3.0.3/microbiome_cdm_v3.db?mode=ro&immutable=1
-- sqlite3 "file:releases/cdm_v3/3.0.3/microbiome_cdm_v3.db?mode=ro&immutable=1"
-- PRAGMA query_only=ON;
-- NEVER select free-text columns (term, match_scores, mapping_provenance,
-- guard_rejection_reason, source_service_mapping, concept labels).
-- safe_census guard: only GROUP BY columns with cardinality<=40 and maxlen<=80.

-- 1. Row counts and demotion arithmetic
SELECT COUNT(*) FROM term_concept_map;                      -- 331394
-- jsonl rows 334231 (releases/terminology/1.0.1/term_ontology_mappings.jsonl)
-- demoted rows = 334231 - 331394 = 2837 (computed in python on mapping_id absent)

-- 2. DB mapping_relation census (must equal D4 settled values)
SELECT mapping_relation, COUNT(*) FROM term_concept_map GROUP BY 1 ORDER BY 2 DESC;
-- RELATED_TO 187832 / AMBIGUOUS 94563 / EXACT_MATCH 37522 / NO_MATCH_FOUND 11477

-- 3. Acceptance/rejection state
SELECT COUNT(*) FROM term_concept_map WHERE mapping_disposition_reviewed='ACCEPTED'; -- 18272
SELECT COUNT(*) FROM term_concept_map WHERE guard_status='rejected_guard';          -- 16622
SELECT mapping_disposition, COUNT(*) FROM term_concept_map GROUP BY 1;
-- REVIEW_REQUIRED 290021 / REJECTED 30693 / UNRESOLVED 10680

-- 4. REJECTED decomposition: guard-rejected + G9-WRONG
SELECT guard_status, mapping_disposition, COUNT(*) FROM term_concept_map
  GROUP BY 1,2 ORDER BY 3 DESC;
-- (rejected_guard, REJECTED) 16622 + (kept, REJECTED) 14071 = 30693
SELECT COUNT(*) FROM term_concept_map WHERE relation_llm_g9='WRONG';  -- 14071

-- 5. Disposition x reviewed-status crosstab (sums to 331394)
SELECT mapping_disposition, mapping_disposition_reviewed, COUNT(*)
  FROM term_concept_map GROUP BY 1,2 ORDER BY 3 DESC;
-- REVIEW_REQUIRED/None 244855; /REVIEW_REQUIRED 25515; /ACCEPTED 18272; /REMOVED 1379
-- REJECTED/None 16622; /REVIEW_REQUIRED 10990; /REMOVED 3081
-- UNRESOLVED/None 10680

-- 6. mapping_id_status / review_status / candidate flags
SELECT mapping_id_status, COUNT(*) FROM term_concept_map GROUP BY 1; -- '' 312314 / MISSING 11477 / SHARED 7603
SELECT review_status, COUNT(*) FROM term_concept_map GROUP BY 1;     -- REVIEW_REQUIRED 319917 / UNRESOLVED 11477
SELECT is_canonical_candidate, COUNT(*) FROM term_concept_map GROUP BY 1; -- 0: 271042 / 1: 60352

-- 7. relation_llm_g9 enum census (safe: d=5, maxlen<=80)
SELECT relation_llm_g9, COUNT(*) FROM term_concept_map GROUP BY 1;
-- None 272238 / EXACT 20632 / RELATED 17861 / WRONG 14071 / NARROWER 4339 / BROADER 2253

-- 8. relation_deepseek is high-cardinality (d=110, maxlen 83) — suppressed
-- by hygiene rule; only its non-null count is safe:
SELECT COUNT(relation_deepseek) FROM term_concept_map;  -- 52020

-- 9. Accepted rows require both LLM verdicts (observed 18,272/18,272):
SELECT COUNT(*) FROM term_concept_map
  WHERE mapping_disposition_reviewed='ACCEPTED'
    AND relation_llm_g9 IS NOT NULL AND relation_deepseek IS NOT NULL;  -- 18272
SELECT COUNT(*) FROM term_concept_map
  WHERE mapping_disposition_reviewed='ACCEPTED' AND relation_llm_g9 IS NULL;  -- 0

-- 10. jsonl vs DB id-set ties (python-side; recorded):
--   jsonl rows 334231; distinct mapping_id 318605; DB distinct 315821
--   jsonl-only ids 2784; DB-only ids 0
--   demoted rows 2837 by relation: AMBIGUOUS 1475 / EXACT_MATCH 881 / RELATED_TO 481
--   demoted rows all review_status=REVIEW_REQUIRED; auto_accept_eligible False 1965 / True 872
--   retained-rows join census == DB mapping_relation census (True)

-- 11. Frozen summary scalars (releases/terminology/1.0.1/, artifact reads):
-- mapping_projection_summary.counts: rows 334231 / rows_with_concept_id 322754 /
--   terms_with_any_candidate 65293 / no_match_found 11477 / lookup_failed 0 /
--   auto_accept_eligible 38334 / auto_accepted 0; calibration NOT_CALIBRATED.
-- terminology_extraction_manifest.coverage: mapping_rows 334231 /
--   terms_with_any_mapping_candidate 65293 / auto_accepted_mappings 0;
--   overall_status COMPLETE; 9/9 artifacts present.
