-- PASS D5 — findings / triples / evidence anchors
-- Target: file:releases/cdm_v3/3.0.3/microbiome_cdm_v3.db?mode=ro&immutable=1
-- Open with sqlite3 CLI:  sqlite3 "file:releases/cdm_v3/3.0.3/microbiome_cdm_v3.db?mode=ro&immutable=1"
-- Then: PRAGMA query_only=ON;
-- NEVER select free-text columns (source_sentence, evidence_text, evidence_span,
-- verdict_*, removal_reason, unresolved_issues, *_labels). Only enum/id/count
-- columns are used below. Validate offsets against section.character_count only.

-- 1. Partition: live + removed = manifest canonical_triples 32,713
SELECT (SELECT COUNT(DISTINCT canonical_triple_id) FROM relation)
     + (SELECT COUNT(DISTINCT canonical_triple_id) FROM removed_relation) AS union_ids;
SELECT COUNT(*) FROM relation r JOIN removed_relation x
  ON r.canonical_triple_id = x.canonical_triple_id;                 -- expect 0 overlap
SELECT COUNT(*) FROM (                                              -- vs canonical_triples.jsonl ids
  SELECT canonical_triple_id FROM relation
  UNION SELECT canonical_triple_id FROM removed_relation);           -- expect 32713

-- 2. Evidence rows = triple_mentions 34,416; per-table split = SUM(mention_count)
SELECT relation_table, COUNT(*) FROM relation_evidence GROUP BY 1;  -- 27130 / 7286
SELECT SUM(mention_count) FROM relation;                            -- 27130
SELECT SUM(mention_count) FROM removed_relation;                     -- 7286
SELECT COUNT(DISTINCT triple_mention_id) FROM relation_evidence;     -- 34416

-- 3. Per-triple mention_count == evidence rows (per relation_table)
WITH ec AS (SELECT relation_table, canonical_triple_id, COUNT(*) c
              FROM relation_evidence GROUP BY 1,2)
SELECT relation_table,
       SUM(CASE WHEN m.mention_count = ec.c THEN 1 ELSE 0 END) AS ok,
       SUM(CASE WHEN m.mention_count <> ec.c THEN 1 ELSE 0 END) AS bad
FROM ec JOIN (
  SELECT canonical_triple_id, mention_count, 'relation' tb FROM relation
  UNION ALL
  SELECT canonical_triple_id, mention_count, 'removed_relation' FROM removed_relation
) m ON m.canonical_triple_id=ec.canonical_triple_id AND m.tb=ec.relation_table
GROUP BY 1;                                                          -- bad=0 everywhere

-- 4. Manifest resolved/unresolved ties (locator basis)
SELECT (SELECT SUM(evidence_verified_count) FROM relation)
     + (SELECT SUM(evidence_verified_count) FROM removed_relation);  -- 32206
SELECT (SELECT SUM(evidence_unresolved_count) FROM relation)
     + (SELECT SUM(evidence_unresolved_count) FROM removed_relation);-- 2210
-- anchor (re-anchor) basis: non-UNANCHORED = 32192
SELECT anchor_status, COUNT(*) FROM relation_evidence GROUP BY 1;
-- cross-tab with jsonl evidence_locator_status (loaded from
-- data/triple_mentions.jsonl outside SQL; see d5_dbfacts.json):
--   unresolved_not_in_source 2210 -> UNANCHORED 2210
--   verified_exact 30077 -> EXACT 5375 + WHITESPACE 24702
--   verified_normalized 2129 -> NORMALISED 2115 + UNANCHORED 14  (Δ14)

-- 5. Duplicate-group / conflict / cross-paper ties
SELECT 'unique',   (SELECT COUNT(*) FROM relation WHERE duplicate_validation_status='unique_mention'),
                 +(SELECT COUNT(*) FROM removed_relation WHERE duplicate_validation_status='unique_mention');
SELECT 'within',   (SELECT COUNT(*) FROM relation WHERE duplicate_validation_status='within_paper_duplicate'),
                 +(SELECT COUNT(*) FROM removed_relation WHERE duplicate_validation_status='within_paper_duplicate');
SELECT 'cross',    (SELECT COUNT(*) FROM relation WHERE duplicate_validation_status='cross_paper_duplicate'),
                 +(SELECT COUNT(*) FROM removed_relation WHERE duplicate_validation_status='cross_paper_duplicate'); -- 309
SELECT (SELECT COUNT(*) FROM relation WHERE conflict_flag='conflicting_across_mentions')
     + (SELECT COUNT(*) FROM removed_relation WHERE conflict_flag='conflicting_across_mentions'); -- 326
-- >=1 unresolved mention on canonical triples (manifest quirk 2153):
SELECT (SELECT COUNT(*) FROM relation WHERE evidence_unresolved_count>=1)
     + (SELECT COUNT(*) FROM removed_relation WHERE evidence_unresolved_count>=1); -- 2153
-- all-mentions-verified (report 30560):
SELECT (SELECT COUNT(*) FROM relation WHERE evidence_unresolved_count=0 AND evidence_verified_count=mention_count)
     + (SELECT COUNT(*) FROM removed_relation WHERE evidence_unresolved_count=0 AND evidence_verified_count=mention_count);

-- 6. Entities tie 37,907
SELECT COUNT(DISTINCT e) FROM (
  SELECT subject_entity_id e FROM relation UNION SELECT object_entity_id FROM relation
  UNION SELECT subject_entity_id FROM removed_relation UNION SELECT object_entity_id FROM removed_relation);

-- 7. Claim/claim_evidence 1:1 and manifest findings tie
SELECT (SELECT COUNT(*) FROM claim), (SELECT COUNT(*) FROM claim_evidence);       -- 45667 == 45667
SELECT claim_source, COUNT(*) FROM claim GROUP BY 1;        -- catalogue_v3_1 24272 / corpus_stage52 21395
SELECT COUNT(*) FROM claim c WHERE NOT EXISTS (SELECT 1 FROM claim_evidence ce
  WHERE ce.finding_id=c.finding_id);                          -- 0
SELECT COUNT(*) FROM claim_evidence ce WHERE NOT EXISTS (SELECT 1 FROM claim c
  WHERE c.finding_id=ce.finding_id);                          -- 0
SELECT COUNT(DISTINCT paper_id) FROM claim WHERE claim_source='corpus_stage52';   -- 383 = 453 - 70
-- (findings.jsonl ids vs DB stage52 finding_ids symdiff computed in python: 0)

-- 8. Guard demotion census on removed_relation (enum columns only)
SELECT verdict_deepseek, COUNT(*) FROM removed_relation GROUP BY 1;  -- NOT_SUPPORTED 6925
SELECT verdict_gemma_c4, COUNT(*) FROM removed_relation GROUP BY 1;
SELECT record_status, COUNT(*) FROM removed_relation GROUP BY 1;      -- active 6925

-- 9. Offset integrity vs section.character_count (no text)
SELECT COUNT(*),                                                   -- relation_evidence bounds
       SUM(CASE WHEN s.section_record_id IS NULL THEN 1 ELSE 0 END) AS orphan_sections,
       SUM(CASE WHEN e.char_start IS NULL THEN 1 ELSE 0 END)        AS null_off,
       SUM(CASE WHEN e.char_start IS NOT NULL AND (e.char_start<0 OR e.char_end<e.char_start) THEN 1 ELSE 0 END) AS inverted,
       SUM(CASE WHEN e.char_start IS NOT NULL AND e.char_end > s.character_count THEN 1 ELSE 0 END) AS overflow
FROM relation_evidence e LEFT JOIN section s ON s.section_record_id = e.section_record_id;
-- expect: 34416, 0, 2224, 0, 0

SELECT COUNT(*),                                                   -- claim_evidence catalogue bounds
       SUM(CASE WHEN s.section_record_id IS NULL THEN 1 ELSE 0 END),
       SUM(CASE WHEN e.char_start IS NULL THEN 1 ELSE 0 END),
       SUM(CASE WHEN e.char_start IS NOT NULL AND (e.char_start<0 OR e.char_end<e.char_start) THEN 1 ELSE 0 END),
       SUM(CASE WHEN e.char_start IS NOT NULL AND e.char_end > s.character_count THEN 1 ELSE 0 END)
FROM claim_evidence e LEFT JOIN section s
  ON s.paper_id=e.paper_id AND s.section_id_original=e.section_id
WHERE e.claim_source='catalogue_v3_1';
-- expect: 24272, 0, 746, 0, 0   (corpus_stage52 offsets NULL by design)

-- 10. Refcounts: evidence with no live/removed triple; papers/sections
SELECT COUNT(*) FROM relation_evidence e WHERE e.canonical_triple_id NOT IN (
  SELECT canonical_triple_id FROM relation UNION
  SELECT canonical_triple_id FROM removed_relation);          -- 0
SELECT COUNT(DISTINCT paper_id) FROM relation_evidence;       -- 451 (=453-2)
SELECT COUNT(DISTINCT section_record_id) FROM relation_evidence; -- 1770 (=2498-728)
SELECT COUNT(*) FROM relation_evidence e WHERE NOT EXISTS (
  SELECT 1 FROM paper p WHERE p.paper_id=e.paper_id);          -- 0

-- 11. Run lineage (single extraction run each)
SELECT extraction_run_id, COUNT(*) FROM relation GROUP BY 1;   -- stage53_triples_extract@2.1.0 x25788
SELECT extraction_run_id, COUNT(*) FROM relation_evidence GROUP BY 1; -- same x34416
SELECT canonicalization_stage, COUNT(*) FROM removed_relation GROUP BY 1; -- stage56... x6925
