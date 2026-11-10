-- PASS D9 — version isolation: 444 / 452 / 453 paper universes
-- DBs (all read-only):
--   file:releases/cdm_v3/3.0.3/microbiome_cdm_v3.db?mode=ro&immutable=1
--   file:releases/frozen_output/03_common_data_model/database/microbiome_cdm.db?mode=ro&immutable=1
--   file:paper/_multi_ner_runs/cdm_output/microbiome_cdm.db?mode=ro&immutable=1
-- PRAGMA query_only=ON on every connection. No paper text read.

-- 1. the three universes, measured
-- 3.0.3 (453):
SELECT COUNT(*), COUNT(DISTINCT paper_id) FROM paper;      -- 453 / 453
SELECT COUNT(*), COUNT(DISTINCT paper_id) FROM section;    -- 4006 / 453
SELECT COUNT(*), COUNT(DISTINCT paper_id) FROM term_mention; -- 2505684 / 453
-- frozen_output 03 DB (v2 shipped CDM, 453):
SELECT COUNT(*) FROM projects;        -- 453
SELECT COUNT(*) FROM entities;        -- 110981
SELECT COUNT(*) FROM relationships;   -- 24910
-- working 444 build (manuscript totals):
SELECT COUNT(*) FROM projects;        -- 444
SELECT COUNT(*) FROM entities;        -- 113517
SELECT COUNT(*) FROM relationships;  -- 858145

-- 2. per-table paper coverage in 3.0.3 (absence, not loss)
SELECT claim_source, COUNT(*), COUNT(DISTINCT paper_id) FROM claim GROUP BY 1;
  -- catalogue_v3_1 24272/451 ; corpus_stage52 21395/383
SELECT COUNT(*), COUNT(DISTINCT paper_id) FROM dataset;   -- 2976 / 451
SELECT COUNT(*), COUNT(DISTINCT paper_id) FROM data_asset; -- 1992 / 417
SELECT COUNT(*), COUNT(DISTINCT paper_id) FROM cohort;    -- 7085 / 450
SELECT COUNT(*), COUNT(DISTINCT paper_id) FROM sample;    -- 7530 / 443
SELECT COUNT(*), COUNT(DISTINCT paper_id) FROM assay;     -- 8545 / 439
-- missing papers:
SELECT DISTINCT paper_id FROM section
 WHERE paper_id NOT IN (SELECT DISTINCT paper_id FROM claim);
  -- HMPAPER_000075, HMPAPER_000372 (both: zero findings in catalogue too)
SELECT DISTINCT paper_id FROM section
 WHERE paper_id NOT IN (SELECT DISTINCT paper_id FROM dataset);
  -- HMPAPER_000172, HMPAPER_000378 (zero catalogue dataset records; claims present)
-- orphan check: claim/dataset paper ids all inside section universe
SELECT COUNT(*) FROM claim WHERE paper_id NOT IN (SELECT paper_id FROM section); -- 0
SELECT COUNT(*) FROM dataset WHERE paper_id NOT IN (SELECT paper_id FROM section); -- 0
-- 000075/000372/000172/000378 are all on corpus_v2 2.2.0's
-- papers_without_eligible_sections list (json: known_quirks.papers_without_mentions
-- also contains 000372 and 000427)

-- 3. cross-build ties (exact)
-- 52400 family total by two routes (DB census == catalogue jsonl entity_type census)
SELECT (SELECT COUNT(*) FROM dataset)+(SELECT COUNT(*) FROM data_asset)
     +(SELECT COUNT(*) FROM cohort)+(SELECT COUNT(*) FROM sample)
     +(SELECT COUNT(*) FROM assay)
     +(SELECT COUNT(*) FROM claim WHERE claim_source='catalogue_v3_1');  -- 52400
-- relation layer:
SELECT COUNT(*) FROM relation_evidence;  -- 34416 == triple_mentions.jsonl 34416 lines
-- (jsonl line counts via wc -c -approach / python; canonical_triples.jsonl 32713)

-- 4. HMPAPER_000427 recovered sidecars isolated by design
SELECT COUNT(*) FROM relation_evidence WHERE paper_id='HMPAPER_000427'; -- 0
-- triple_mentions.jsonl: 0 lines contain HMPAPER_000427 (34416 total)
-- canonical_triples.jsonl: 0 lines contain HMPAPER_000427 (32713 total)
-- sidecars: triple_mentions_000427_recovered.jsonl 33 lines;
--           canonical_triples_000427_recovered.jsonl 32 lines
-- BUNDLE_INFO.json recovered_000427: id_namespace disjoint, 0 collisions,
-- not_merged documented; provenance outputs/scratch/fix_000427/FIX_REPORT.md

-- 5. char-count states (verifiable from DATA_SEMANTICS.md sources)
-- 26874831 (corpus_v2 2.2.0 manifest counts.characters)
--   > 26871587 (segmented md _conversion_report total_chars)
--   > 26867649 (terminology validation coverage.total_chars_processed)
