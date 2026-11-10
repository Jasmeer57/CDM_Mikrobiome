-- PASS D7 — data-catalogue families: v3.1.1 vs frozen DB
-- Target: file:releases/cdm_v3/3.0.3/microbiome_cdm_v3.db?mode=ro&immutable=1
-- sqlite3 "file:releases/cdm_v3/3.0.3/microbiome_cdm_v3.db?mode=ro&immutable=1"
-- PRAGMA query_only=ON;
-- Release side: releases/data_catalogue_v3/3.1.1 (papers/tables/records/provenance)
-- NEVER select free-text or evidence columns. safe_census guard:
-- cardinality<=40, maxlen<=80 only.
-- CSV/jsonl reads use a NUL-stripped byte reader (findings.csv has 1 NUL byte:
-- taxon_or_feature of HMFINDING_024394; plain csv.DictReader dies with
-- _csv.Error: line contains NUL).

-- 1. Family row counts (CSV=jsonl=manifest=DB; sweep table)
SELECT COUNT(*), COUNT(DISTINCT dataset_id)    FROM dataset;     -- 2976 / 2976
SELECT COUNT(*), COUNT(DISTINCT asset_id)      FROM data_asset;   -- 1992 / 1992
SELECT COUNT(*), COUNT(DISTINCT cohort_id)    FROM cohort;       -- 7085 / 7085
SELECT COUNT(*), COUNT(DISTINCT sample_group_id) FROM sample;    -- 7530 / 7530
SELECT COUNT(*), COUNT(DISTINCT assay_id)     FROM assay;        -- 8545 / 8545
SELECT COUNT(*), COUNT(DISTINCT finding_id) FROM claim
  WHERE claim_source='catalogue_v3_1';                            -- 24272 / 24272
-- (id-set symdiff vs release CSVs = 0 for all six; python NUL-stripped reader)

-- 2. papers-level ties
SELECT COUNT(*) FROM section;                                     -- 4006 rows
SELECT COUNT(DISTINCT paper_id) FROM section;                     -- 453 papers
-- papers.csv: SUM(sections_total)=4006; SUM(n_records_total)=54986 (v3.0 basis)
-- per-paper n_* == _v2_to_v3_map(KEPT+REMOVED+ADDED) per paper: 0/453 mismatches
-- map census (60566): KEPT 52258 / ADDED 142 / MERGED_INTO 5460 / DUP 120 / REMOVED 2586

-- 3. Safe censuses: v3_status, review_status
SELECT v3_status, COUNT(*) FROM dataset GROUP BY 1;  -- KEPT 2834 / ADDED 142
SELECT v3_status, COUNT(*) FROM data_asset GROUP BY 1;  -- KEPT 1992
SELECT v3_status, COUNT(*) FROM cohort GROUP BY 1;    -- KEPT 7085
SELECT v3_status, COUNT(*) FROM sample GROUP BY 1;    -- KEPT 7530
SELECT v3_status, COUNT(*) FROM assay GROUP BY 1;     -- KEPT 8545
SELECT review_status, COUNT(*) FROM dataset GROUP BY 1;   -- UNVERIFIED 2976
SELECT review_status, COUNT(*) FROM data_asset GROUP BY 1;-- UNVERIFIED 1992
SELECT review_status, COUNT(*) FROM cohort GROUP BY 1;    -- UNVERIFIED 7085
SELECT review_status, COUNT(*) FROM sample GROUP BY 1;    -- UNVERIFIED 7530
SELECT review_status, COUNT(*) FROM assay GROUP BY 1;     -- UNVERIFIED 8545
SELECT review_status, COUNT(*) FROM claim GROUP BY 1;     -- UNVERIFIED 45667 total
  -- claim WHERE claim_source='catalogue_v3_1': UNVERIFIED 24272

-- 4. Anchor + verification (trust-flag inventory; safe enums)
SELECT evidence_anchor_status, COUNT(*) FROM claim
  WHERE claim_source='catalogue_v3_1' GROUP BY 1;
  -- WHITESPACE 15057 / EXACT 3510 / NORMALISED 2139 / RELOCATED 1290
  -- / FUZZY 1670 / UNANCHORED 560 / NO_EVIDENCE 46  (sum 24272)
SELECT evidence_verified, COUNT(*) FROM claim
  WHERE claim_source='catalogue_v3_1' GROUP BY 1;      -- 0: 746 / 1: 23526
SELECT evidence_verified, COUNT(*) FROM dataset GROUP BY 1; -- 0:358 / 1:2618
SELECT evidence_verified, COUNT(*) FROM data_asset GROUP BY 1; -- 0:76 / 1:1916
SELECT evidence_verified, COUNT(*) FROM cohort GROUP BY 1;  -- 0:589 / 1:6496
SELECT evidence_verified, COUNT(*) FROM sample GROUP BY 1;  -- 0:398 / 1:7132
SELECT evidence_verified, COUNT(*) FROM assay GROUP BY 1;   -- 0:415 / 1:8130

-- 5. Merge/clean account (CLEAN_REPORT + _v2_to_v3_map + _removed.jsonl)
-- map 60566 rows; _removed.jsonl 8166 rows = REMOVED 2586 + MERGED 5460 + DUP 120
-- v3_status prefix census reads fields.v3_status in jsonl (top-level key absent)
-- (entity_type,id) symdiff map-non-KEPT-vs-jsonl: 0
-- CLEAN_REPORT: input 60424 / output 54986 / A11 5460 / A1 120 / A8 142 (tie 1:1)
-- manifest .records 52400 == KEPT+ADDED == all six family table totals

-- 6. Redaction (python: evidence_redacted=='LICENCE' 18502 == manifest
-- evidence_rows_redacted; per-family LICENCE: assays 3326 / cohorts 2580 /
-- data_assets 478 / datasets 928 / samples 2739 / findings 8451)
-- 80 unflagged REDACT-paper rows = evidence_match NO_QUOTE
--   (63 ADDED datasets + 17 KEPT findings): no evidence text to redact.
-- sha256: all 44 manifest-listed release files verify (hash+bytes).
