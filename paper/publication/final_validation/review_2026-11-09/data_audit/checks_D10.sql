-- PASS D10 — trust flags & transparency markers
-- Target: file:releases/cdm_v3/3.0.3/microbiome_cdm_v3.db?mode=ro&immutable=1
-- PRAGMA query_only=ON on every connection. No paper text read (enum/count only).

-- 1. term_mention.unresolved_flags (JSON-encoded) census
SELECT COUNT(*) FROM term_mention;                                   -- 2505684
SELECT COUNT(*) FROM term_mention WHERE unresolved_flags='[]';        -- 2146364
SELECT COUNT(*) FROM term_mention
 WHERE unresolved_flags LIKE '%SENTENCE_CLIPPED%';                   -- 358150 (documented)
SELECT COUNT(*) FROM term_mention
 WHERE unresolved_flags='["SENTENCE_CLIPPED"]';                      -- 357755
SELECT COUNT(*) FROM term_mention
 WHERE unresolved_flags LIKE '%CONTROL_CHAR_SURFACE%';               -- 1497

-- 2. claim anchor_status (catalogue_v3_1 only; stage52 NULL by design)
SELECT claim_source, evidence_anchor_status, COUNT(*)
  FROM claim GROUP BY 1,2;
--  catalogue_v3_1: WHITESPACE 15057 / EXACT 3510 / NORMALISED 2139 / FUZZY 1670
--                 / RELOCATED 1290 / UNANCHORED 560 / NO_EVIDENCE 46
--  corpus_stage52: NULL 21395

-- 3. claim anchor x verified cross-tab (the 746 verified=0 decomposition)
SELECT evidence_anchor_status, evidence_verified, COUNT(*) FROM claim
 WHERE claim_source='catalogue_v3_1' GROUP BY 1,2 ORDER BY 1,2;
--  v0: UNANCHORED 505 + FUZZY 174 + NO_EVIDENCE 46 + NORMALISED 21 = 746 (NULL offsets)
--  v1 soft anchors total 3669 (UNANCHORED 55 / FUZZY 1496 / NORMALISED 2118) —
--  NOTE: D3 report line 50 quoted "129" here; corrected in PASS_D10 §2.

-- 4. family anchor x verified
SELECT evidence_anchor_status, evidence_verified, COUNT(*) FROM dataset GROUP BY 1,2;
SELECT evidence_anchor_status, evidence_verified, COUNT(*) FROM data_asset GROUP BY 1,2;
SELECT evidence_anchor_status, evidence_verified, COUNT(*) FROM cohort GROUP BY 1,2;
SELECT evidence_anchor_status, evidence_verified, COUNT(*) FROM sample GROUP BY 1,2;
SELECT evidence_anchor_status, evidence_verified, COUNT(*) FROM assay GROUP BY 1,2;
--  evidence_verified=0: dataset 358 / data_asset 76 / cohort 589 / sample 398 / assay 415

-- 5. relation_evidence anchor census (ties D5)
SELECT anchor_status, COUNT(*) FROM relation_evidence GROUP BY 1;
--  WHITESPACE 24702 / EXACT 5375 / NORMALISED 2115 => 32192 anchored; UNANCHORED 2224

-- 6. review_status honesty ledger
SELECT review_status, COUNT(*) FROM dataset GROUP BY 1;    -- UNVERIFIED 2976
SELECT review_status, COUNT(*) FROM data_asset GROUP BY 1; -- UNVERIFIED 1992
SELECT review_status, COUNT(*) FROM cohort GROUP BY 1;     -- UNVERIFIED 7085
SELECT review_status, COUNT(*) FROM sample GROUP BY 1;     -- UNVERIFIED 7530
SELECT review_status, COUNT(*) FROM assay GROUP BY 1;      -- UNVERIFIED 8545
SELECT claim_source, review_status, COUNT(*) FROM claim GROUP BY 1,2;
--  catalogue_v3_1 UNVERIFIED 24272; corpus_stage52 pending 21395
--  all-UNVERIFIED total: 28128 + 24272 = 52400

-- 7. claim <-> claim_evidence mirror integrity (1:1, 0 disagreements)
SELECT COUNT(*) FROM claim c JOIN claim_evidence ce
  ON c.finding_id=ce.finding_id AND c.claim_source=ce.claim_source;     -- 45667
SELECT COUNT(*) FROM claim c JOIN claim_evidence ce
  ON c.finding_id=ce.finding_id AND c.claim_source=ce.claim_source
 WHERE c.evidence_anchor_status IS NOT ce.evidence_anchor_status
    OR c.evidence_locator_status IS NOT ce.evidence_locator_status
    OR c.char_start IS NOT ce.char_start OR c.char_end IS NOT ce.char_end
    OR c.evidence_span_start IS NOT ce.evidence_span_start
    OR c.evidence_span_end IS NOT ce.evidence_span_end;                  -- 0

-- 8. claim_evidence locator (stage52)
SELECT evidence_locator_status, COUNT(*) FROM claim_evidence GROUP BY 1;
--  verified_normalized 16602 / unresolved_not_in_source 2788 / verified_exact 2005
--  + NULL 24272 (catalogue convention)

-- 9. validation_result / evaluation_run / status snapshots
SELECT "check", passed, COUNT(*) FROM validation_result
 WHERE "check" <> 'per_paper_validation' GROUP BY 1,2;   -- 10 checks passed=1
SELECT evaluation_run_id, method, target FROM evaluation_run;  -- 3 LLM-judge runs
SELECT "table", rows_offered, rows_kept, rows_dropped FROM load_audit ORDER BY 1;
SELECT entity, "table", rows, status FROM cdm_entity_status ORDER BY entity;
--  kept==live everywhere except extraction_run: recorded 28, live 45;
--  growth documented: cdm_change_log R1 INSERT_ROWS rows_affected=17 (see D8)

-- 10. change log INSERT_ROWS (R1 = the +17 extraction_run rows)
--      cdm_change_log cols: step, kind, target, description, rows_affected, revert_sql
SELECT step, kind, rows_affected FROM cdm_change_log
 WHERE kind='INSERT_ROWS';                                -- R1, 17

-- 11. terminology 1.0.1 calibration markers (files, not DB)
--   mapping_projection_summary.json: calibration.status = "NOT_CALIBRATED"
--   PROVENANCE.json: non_claims: "auto_accepted = 0; calibration = NOT_CALIBRATED."
--   (grep -rl NOT_CALIBRATED releases/terminology/1.0.1 -> those 3 files)
