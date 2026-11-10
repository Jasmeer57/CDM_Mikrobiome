# PASS D2 — Referential integrity
**FROZEN_DB** = `releases/cdm_v3/3.0.3/microbiome_cdm_v3.db` (sha256 `5d23ba87d29a…`, re-verified at pass start, read-only immutable URI + `PRAGMA query_only=ON` on every connection; all writes confined to this review directory; no paper text columns selected).

**Date**: 2026-11-09 · **Pass scope**: D2 — referential integrity of the frozen CDM 3.0.3 database (name-implied FKs, PK uniqueness, removal semantics, id conventions) as required by the data-audit protocol.

**Query file**: `checks_D2.sql` (companion, exact SQL used or its documented Python token-level equivalents, with observed results in `/* … */` comments).

## 0. Method

- **The DB declares 0 FK constraints** (D0, `PRAGMA foreign_key_list` empty for all 44 tables). Every edge below is therefore **name-implied**, documented one by one: child column → parent key, single- vs multi-valued, convention, sentinel semantics.
- **Method notes on the two legal section-id conventions** (both inside one DB, unified check used throughout): `section.section_id_original` = `sec_NNN`, `section.section_record_id` = `HMPAPER_xxx:sec:NNN`. Split by claim_source: `corpus_stage52` rows use record-id convention; `catalogue_v3_1` rows use original convention. All child tables other than claim/claim_evidence use `sec_NNN` exclusively.
- **Empty string `''` is a sentinel, not an FK violation** (e.g. `relation.subject_term_id=''` rows all carry `subject_entity_resolution_status='unresolved_string_match_v1'`); NULL FKs are counted separately, never treated as orphans.
- **NOT IN query form used for heavy children** (term_mention, 2,505,684 rows): correlated `NOT EXISTS` timed out at 600 s; the materializing `NOT IN (SELECT pk FROM parent)` form completed in seconds. Multi-valued `;`-joined ID fields were checked at token level in Python (split on `';'`, strip, membership test against the parent key set).

**Bottom line**:

> Every name-implied FK edge resolves: **0 unexplained orphans anywhere in the database**. All orphan-looking references decompose exactly into (a) removed-entity cross-references (self-labeled, resolvable via `removed_canonical_term`/`removed_relation`, consistent with the 3.0.2→3.0.3 removal/reversion semantics), (b) empty-string sentinels (documented string-match-v1 semantics), or (c) term_concept_map rows that were never canonical terms at all (guard-stage candidates, self-labeled `NOT_IN_TERMINOLOGY`, traceable into terminology 1.0.1 `term_ontology_mappings.jsonl` — documented below). **Two genuine latent defects found** (both minor, both here recorded as findings): **L-1** `processing_lineage` has 2 dangling child refs (`gap G1`, `gap G9` — stage labels stored where run ids should be), and **L-2** `term_definition.definition_id` is not unique on its own (6,773 rows / 5,057 ids) but is documented as "PK part" with the compensating `(definition_id, term_id)` unique index — noted as a documentation/definition gap, since uniqueness holds only on the composite.

## 1. Simple single-valued name-implied edges — all 0 orphans

25 edges across 7 groups below (`child.col → parent.key`), each `NOT IN` on the parent key set; NULL counts recorded where non-zero:

- `assay.paper_id`, `assay.study_id`, `cohort.paper_id`, `cohort.study_id`, `dataset.paper_id`, `dataset.study_id`, `data_asset.paper_id`, `data_asset.study_id` → paper/study: 0 orphans.
- `claim.paper_id`, `claim.study_id` (NULL 24,272 = catalogue rows), `claim.study_id_derived`, `claim_evidence.paper_id` → paper/study: 0 orphans.
- `quantitative_result.finding_id` → `claim.finding_id`, `quantitative_result.paper_id`: 0 orphans.
- `relation_evidence.paper_id`, `section.paper_id`, `study.paper_id`, `paper_publication.paper_id`, `paper_publication.publication_id`, `source_asset.paper_id`, `term_occurrence.paper_id` → paper/publication: 0 orphans.
- `processing_event.paper_id` (NULL 31 run-event rows): 0 orphans.
- `compendium_sample.project` → `compendium_project.project`: 0 orphans.
- `term_mention.paper_id`, `term_mention.extraction_run_id`: 0 orphans each (2.5M-row tables, NOT IN form).

Full list with per-edge NULL counts in `checks_D2.sql` §1.

## 2. Multi-valued `;`-joined ID fields — token-level check, 0 token-orphans

Eight multi-valued fields store `;`-joined id lists, with `''` as the no-value sentinel:

| child.col | rows | `''` sentinel rows | multi-id rows | token-orphans |
|---|---:|---:|---:|---:|
| assay.dataset_id | 8,545 | 732 | 1,074 | **0** |
| cohort.dataset_id | 7,085 | 679 | 694 | **0** |
| sample.dataset_id | 7,530 | 343 | 1,870 | **0** |
| sample.cohort_id | 7,530 | 209 | 3,253 | **0** |
| data_asset.dataset_id | 1,992 | 81 | 85 | **0** |
| claim.assay_id | 45,667 | 22,969 | 13,343 | **0** |
| claim.cohort_id | 45,667 | 23,142 | 13,972 | **0** |
| claim.dataset_id | 45,667 | 23,870 | 10,088 | **0** |

Single-valued interpretation of these columns would produce false "orphans" (e.g. `assay.dataset_id` would show ~1,806) — the semicolon lists and `''` sentinels are the design, not a defect. Token-level interpretation resolves **every** token: 0 orphan tokens, 0 rows containing one.

## 3. Heavy tables — 0 unexplained orphans

- `term_mention` (2,505,684 rows): paper_id 0 / extraction_run_id 0 / canonical_term_id 0 orphans vs live `canonical_term` — with 13,927 rows (3,184 distinct ids) referencing **removed** terms (all 3,184 in `removed_canonical_term`; link status LINKED 12,893 / LINKED_BY_TYPE 1,034; self-labeled `canonical_term_status='REMOVED'`), and 306,918 NULL canonical_term_id (unlinked mentions; correct by design, the "not resolved to a term" universe).
- `term_definition` (6,773 rows): term_id 0 live-orphans; 138 rows on 69 distinct ids → all in `removed_canonical_term`; paper_id 0 orphans; extraction_run_id 0 orphans.
- `term_concept_map` (331,394 rows): 16,710 rows outside the live term universe, decomposing exactly (see §4).
- `taxonomy_annotation` (162,409 rows): term_id / extraction_run_id — 0 orphans.
- `type_harmonization` (40,141 rows): canonical_term_id NULL 12,271 / live 27,447 / removed 423 / neither **0**; term_id_llm non-live 30,037 = `''` sentinel 29,893 + removed-term rows 144 (128 distinct ids, all in removed_canonical_term) — 0 rows in neither.
- `relation` (25,788 rows): subject/object_term_id `''` sentinels (2,104 / 3,303) with `*_entity_resolution_status='unresolved_string_match_v1'`; excluding sentinels, 0 live-orphans; extraction_run_id 0 orphans; canonical_triple_id unique 25,788/25,788.
- `claim → claim_evidence` is **exactly 1:1** (see §5) and split by claim_source: catalogue_v3_1 24,272 / corpus_stage52 21,395.
- `quantitative_result` (13,540) → claim/paper: 0 orphans. `relation_evidence` (34,416) → paper: 0 orphans.

## 4. Removed/unknown-term cross-references — every non-live reference explained

Term-id universe: `canonical_term` 162,409 + `removed_canonical_term` 3,582 = **165,991 distinct**, disjoint (0 overlap) — matches D1's T2+T3 (P19).

- **term_mention**: 13,927 rows reference removed terms — all self-labeled (`canonical_term_status='REMOVED'`), all ids present in `removed_canonical_term`. No blind dangling.
- **term_definition**: 138 rows on 69 removed-term ids (all in `removed_canonical_term`).
- **type_harmonization**: 423 canonical_term_id refs, all in `removed_canonical_term`. term_id_llm: 29,893 `''` sentinels + 144 removed-term rows.
- **term_concept_map**: 16,710 non-live rows = **11,473** self-labeled `term_status='REMOVED'` (all ids in `removed_canonical_term`) + **5,237** `term_status='NOT_IN_TERMINOLOGY'` rows. The 5,237 are guard-stage mapping candidates: `candidate_rank=1`, `is_canonical_candidate=0`, whole-table run id `mapping_guards_v2` (all 331,394 tcm rows carry this run id — it is a table-level lineage marker, not a distinguishing property), `mapping_disposition` REVIEW_REQUIRED 5,220 / REJECTED 17; their term ids appear in terminology 1.0.1 `term_ontology_mappings.jsonl` but **not** in `canonical_terms.jsonl` (5/5 spot-checked, 2026-11-09) — i.e. mapping rows for candidates that were canonically rejected before T2; the DB row itself self-labels this via `term_status='NOT_IN_TERMINOLOGY'`. **Self-documented, not orphans.**
- `relation_evidence` → `removed_relation`: 6,925 distinct removed triple ids all present in `removed_relation` (7,286 evidence rows reference them); 27,130 evidence rows reference live relations; 25,788 live + 6,925 removed = 32,713 canonical triples — ties exactly to corpus_v2 2.2.0's 32,713 (D1).
- Live/removed disjointness for relations confirmed: 0 overlap between `relation` and `removed_relation` on canonical_triple_id.

## 5. claim ↔ claim_evidence pairing — exact 1:1

45,667 rows each; distinct finding_id 45,667 both sides; both `EXCEPT` directions 0; 0 paper_id/claim_source contradictions under join; finding_id unique across both claim_sources (corroborated by the R6 unique index on claim(finding_id, claim_source)). One claim per finding, one evidence row per claim. Complementary section columns per source: `claim.section_id` NULL exactly on the 21,395 corpus_stage52 rows (which populate `evidence_section_id` instead); catalogue rows the mirror image (24,272 non-null section_id).

## 6. occurrence_key network — bidirectional exact match

`term_mention` distinct occurrence_key 1,362,931 = `term_occurrence` rows 1,362,931; both EXCEPT directions 0. occurrence_key is a true cross-table key (its columns' provenance: term_mention's mention-occurrence grouping from D1).

## 7. term_definition.definition_id sharing — documented design, with a definition gap (finding L-2)

6,773 rows / 5,057 distinct definition_id (formats: 588 `HMDEF_<hex16>` + 4,469 `HMDEF_LLM_<num>`); unique on `(definition_id, term_id)` (6,773/6,773) — the composite R6 created a unique index on. 1,177 duplicate-id groups (sizes 2–16); **0 groups differ on paper_id/section_id/definition_source/extraction_method/extraction_run_id** — a shared id denotes one extraction-span event (e.g. `HMDEF_LLM_0000002` covering 5 abbreviation-expansion terms in one paper/section), never cross-event reuse. `removed_term_definition`: 3,865 rows — 562 non-null definition_ids (all `HMDEF_<hex16>`), 3,303 rows with NULL definition_id AND NULL term_id (bulk tombstones of definition-less removals), 0 live/removed id collisions.

**Finding L-2 (documentation gap, minor)**: the remediation data dictionary lists `definition_id` as *“PK part”*, but it is not unique in the single-column form (6,773 rows / 5,057 ids; 1,177 dup groups) — uniqueness holds only on the composite `(definition_id, term_id)` (the R6 index). Moreover, the dictionary's documented id pattern `^HMDEF_[0-9a-f]{16}$` matches only the 588 hex-form ids; the 4,469 `HMDEF_LLM_*` ids and the 3,303 NULL tombstone rows fall outside that documented pattern. Anyone treating `definition_id` as a standalone key would silently produce phantom joins (5,057 ids ↔ 6,773 rows). No data loss, no corruption — a data-dictionary precision issue.

## 8. Section references — mixed convention, 100% resolvable (key finding)

Two section-id conventions coexist (D0/D1 known; per-table split fully mapped here):

| child reference | rows using `sec_NNN` | rows using `HMPAPER…:sec:NNN` | unresolvable under unified check |
|---|---:|---:|---:|
| term_mention.section_id | 2,505,684 | 0 | 0 |
| claim.section_id | 24,272 | 0 | 0 |
| claim.evidence_section_id | 0 | 21,395 | 0 |
| claim_evidence.section_id | 24,272 (catalogue) + 0 | 21,395 (stage52) | 0 |
| assay/cohort/sample/dataset/data_asset/term_definition.section_id | all non-empty rows | 0 | 0 |

Every section reference in the DB resolves under the unified `(paper_id, section_id original-or-record)` check. The convention split is 100% aligned with claim_source and is therefore traceable to the two build streams (corpus_stage52 vs catalogue_v3_1), not a data defect — but it is a **trap for any consumer who joins on `section_id` alone** (the two `section_id` columns across tables are not directly comparable without the convention map). The `identifier_crosswalk` table (4 rows) documents exactly these conventions, corroborating the above.

## 9. Relation family

- `relation` canonical_triple_id 25,788/25,788 unique; `removed_relation` 6,925/6,925 unique; 0 live/removed overlap.
- `relation_evidence` 34,416 = 27,130 live-relation evidence rows + 7,286 removed-relation evidence rows.
- 0 live relations without evidence; 0 evidence rows whose triple id is in neither relation nor removed_relation.
- Join key is `canonical_triple_id` (D1 established relation_evidence has no relation_id column).

## 10. processing_lineage — 2 dangling child refs (finding L-1)

5 rows, all `relation='input_of'`. Parent ids all resolve in `extraction_run`; child ids: `CATCLEAN_v3`, `CATLINK_v2`, `gap G8` resolve, **`gap G1` and `gap G9` do not**. Cause identified exactly: the lineage rows record **stage labels**, while the `extraction_run` registry keys those gap runs by **job id** (`28671778` stage=`gap G1`; `28671785` stage=`gap G9`; the self-keyed `gap G8` row resolves only coincidentally because that builder row reused the label as its id). `processing_event.run_id` is a third id domain entirely (31 distinct run ids, 7,347 rows) — lineage endpoints are not processing_event refs at all. The data dictionary marks all 3 processing_lineage columns NEEDS_EXPERT_REVIEW with empty definitions, consistent with this discovery.

**Impact**: 2/5 lineage child endpoints cannot be machine-resolved to a run row; the chain CATNER_20261030T092214_1923898 → CATCLEAN_v3 → CATLINK_v2 → gap-G1 (job 28671778) is recoverable **only** by label→job-id mapping through the stage column, not the id column. Provenance remains traceable for a human reader; automated lineage traversal breaks at these two edges.

## 11. extraction_run FK sweep and the 45 vs load_audit 28 delta — explained

All 13 child-table `extraction_run_id` edges: 0 orphans. `extraction_run` itself: 45 rows / 45 distinct ids. Delta explained: `load_audit` rows_offered=kept=28 for extraction_run + `cdm_change_log` R1 `INSERT_ROWS extraction_run = 17` → 28+17 = 45. ✔ No discrepancy. (D1 X04 verification split: VERIFIED_LOG 29 / VERIFIED_CODE_AND_HASH 5 / VERIFIED_RUN_EVENT 4 / AS_IN_3.0.2_UNVERIFIED 4 / RECORDED_IN_DATA 3.)

## 12. PK / candidate-key uniqueness — all unique

Every tested key is unique (rows = distinct). The one exception is `term_definition.definition_id`, which is unique only on the `(definition_id, term_id)` composite — recorded as finding L-2 in §7.

| table.key | rows | distinct |
|---|---:|---:|
| paper.paper_id | 453 | 453 |
| study.study_id | 453 | 453 |
| section.section_record_id | 4,006 | 4,006 |
| canonical_term.term_id | 162,409 | 162,409 |
| concept.concept_id | 204,817 | 204,817 |
| extraction_run.extraction_run_id | 45 | 45 |
| claim.finding_id | 45,667 | 45,667 |
| dataset.dataset_id | 2,976 | 2,976 |
| assay.assay_id | 8,545 | 8,545 |
| cohort.cohort_id | 7,085 | 7,085 |
| sample.sample_group_id | 7,530 | 7,530 |
| data_asset.asset_id | 1,992 | 1,992 |
| publication.publication_id | 447 | 447 |
| relation.canonical_triple_id | 25,788 | 25,788 |
| removed_relation.canonical_triple_id | 6,925 | 6,925 |
| compendium_project.project | 452 | 452 |
| compendium_sample.srs (and both composites) | 156,330 | 156,330 |
| term_occurrence.occurrence_key | 1,362,931 | 1,362,931 |
| term_mention.mention_row_id | 2,505,684 | 2,505,684 |
| term_concept_map.mapping_row_id | 331,394 | 331,394 |
| claim.(finding_id, claim_source) | 45,667 | 45,667 |
| term_definition.(definition_id, term_id) | 6,773 | 6,773 |

R6's unique indexes corroborate the composite keys: `claim(finding_id, claim_source)`, `term_definition(definition_id, term_id)`, `taxonomy_annotation(term_id, taxonomy_version)`, `quantitative_result(finding_id, claim_source)`, `claim_evidence(finding_id, claim_source)`, `section(paper_id, section_id_original)`, `cohort(cohort_id)`, `sample(sample_group_id)`, `assay(assay_id)`.

## 13. Small tables

intervention (1,935), body_site (29), identifier_crosswalk (4), load_audit (36) — self-contained, no external refs; nothing to check beyond the internal consistency already confirmed in D1.

---

## Findings summary

| id | finding | severity | disposition |
|---|---|---|---|
| L-1 | `processing_lineage.child_id` stores stage labels; 2 of 5 rows (`gap G1`, `gap G9`) have no matching `extraction_run.extraction_run_id` (the run rows exist under job-id keys 28671778/28671785) | minor | DISCREPANCY (documented; label→job-id mapping recoverable via `extraction_run.stage`) |
| L-2 | `term_definition.definition_id` unique only on `(definition_id, term_id)` composite (R6 index); the dictionary's single-column "PK part" label and `^HMDEF_[0-9a-f]{16}$` pattern don't match observed data (6,773 rows / 5,057 ids incl. 4,469 `HMDEF_LLM_*`; 3,303 NULL tombstones) | minor | DISCREPANCY (documentation/definition gap; composite uniqueness intact) |
| —  | `section_id` dual convention (`sec_NNN` vs `HMPAPER…:sec:NNN`), split exactly by claim_source / build stream | info | PASS with convention note (100% resolvable under unified check; identifier_crosswalk table documents the conventions) |
| — | tcm `NOT_IN_TERMINOLOGY` 5,237 rows (guard-stage candidates canonically rejected pre-T2; self-labeled; traceable to terminology 1.0.1 mappings file) | info | PASS with note (self-documented, not orphans) |
| — | `''` sentinels on relation.subject/object_term_id and type_harmonization.term_id_llm (`unresolved_string_match_v1` semantics) | info | PASS with note (documented status; not FK breaks) |

Discipline: no paper-text columns selected anywhere in this pass; reads strictly via the immutable read-only URI with `PRAGMA query_only=ON`; all writes confined to `review_2026-11-09/data_audit/`.
