# Component H — CDM Schema and Database Quality

**Audited object:** the full CDM 3.0.3 SQLite database — **44 tables, 0 views, 866 columns**,
8,490,496 rows — as an engineering artefact: keys, constraints, indexes, rollups, duplication,
documentation, and the eight research queries it is meant to answer.
**Evidence base:** `diagnostics/results/d02_referential_integrity.json`,
`d03_rollup_consistency.json`, `d04_duplication.json`, `d19_cdm_schema_quality.json`,
`d09_usability.json`, `d10_provenance_manifest.json`, `d01_offset_integrity.json`.
**Independence:** every structural fact was read from `PRAGMA table_info` / `PRAGMA index_list` on
the frozen file, and every rollup and referential check was recomputed by SQL against the same file.
The dictionary coverage check was performed against the shipped data dictionary, not asserted.

> **Scope note.** This component judges the *container*, not the contents. Data-quality defects that
> belong to a content component (a wrong catalogue value, an unmapped triple end) are recorded there.
> Where a container defect *causes* a content defect — the missing junction table, the missing
> composite index, the missing provenance columns — it is recorded here and cross-referenced.

---

## 1. Dimensional assessment

| Dimension | Rating | Supporting evidence | Measurable indicator | Limitation | Confidence |
|---|---|---|---|---|---|
| Structural integrity | **ADEQUATE** | 44 tables / 866 columns / 8,490,496 rows; **0 views**; 17 tables carry a primary key; all 44 tables are populated and documented | tables with a declared PK **17 / 44 = 38.6%**; tables with neither PK nor unique index **18 / 44 = 40.9%**; tables with no index at all **5** (`removed_canonical_term`, `removed_relation`, `removed_term_definition`, `term_occurrence`, `type_harmonization`) | The DB is loadable and queryable; "structural integrity" here means it holds together for the shipped queries, not that it is relationally constrained | High |
| Constraint enforcement | **CRITICAL** | **0 declared FOREIGN KEY constraints** across all 44 tables; **866 / 866 columns have no declared type** (`NONE`); `journal_mode` is persisted as `delete`, not WAL; `load_audit` records 79 change-log rows with `revert_sql` but no enforcement | declared FKs **0**; typed columns **0 / 866 = 0.00%** | Nothing prevents an orphan, a duplicate or a type error at write time. Every integrity property in this database is a *post-hoc* property, verified by audit, not by the engine | High |
| Referential integrity (as-found) | **WEAK** | 37 column-level referential checks; **4** find any dangling value; 31,198 dangling ids total, of which **25,961 are explained** by `removed_*` tombstones and **5,237 are not** (`term_concept_map.term_id` rows tagged `NOT_IN_TERMINOLOGY`). Orphans: **1,092 datasets** with no cohort/sample/assay; 9,940 terms with no mention; 93,604 with no mapping; 159,081 with no definition; 0 claims/relations without evidence; 0 papers without sections | unexplained dangling **5,237 / 31,198 = 16.8%** of dangling, **0.06%** of all ids scanned | The 5,237 are a *sentinel* population (a term id that deliberately does not exist, used to mark rows as not-in-terminology), so the referential picture is better than the raw figure suggests — but the sentinel is undocumented in the schema | High |
| Rollup consistency | **WEAK** | 14 rollups checked, **11 stale**: `canonical_term.mention_count` disagrees on **61,839 / 152,333 = 40.59%**; `definition_count` 3,316 / 162,409 = 2.04%; `paper_count` 11,756 / 152,333 = 7.72%; **all six `paper.n_*` rollups disagree on 453 / 453 = 100%**; `relation.evidence_verified_count` 12 rows. Three `relation` rollups are exactly consistent | stale rollups **11 / 14 = 78.6%** | The `paper.n_*` family is **not staleness**: component F proved they are mirrors of the catalogue clean layer (surplus 2,586 rows over 399/453 papers, `n_findings` +405). The `canonical_term.mention_count` staleness is genuine and unexplained | High |
| Duplication | **WEAK** | `term_mention`: **2,505,684 rows → 1,362,888 distinct spans**, i.e. **1,142,796 redundant rows (45.6%)** by span collapse; `canonical_term.term_norm` 68 groups / 71 redundant; `term_norm+cdm_type` 2 / 2; surface near-duplicates 2,452 groups / 2,874 redundant (817 within type, 1,635 across); `term_definition` 272 / 424; `term_concept_map` 4,686 / 5,984; `type_harmonization` 363 / 447; `relation` 0 duplicate canonical triples | mention redundancy **45.6%**; definition redundancy **6.3%** (424/6,773) | Span collapse means "the same section offsets were emitted by more than one model or more than once". It is expected in a multi-model table but it means `term_mention` is not a mention table, it is a mention-*observation* table | High |
| Usability (research queries) | **WEAK** | All **8 / 8** published `RESEARCH_QUERY_VALIDATION.csv` queries run and reproduce their published row and paper counts exactly (Q1 35/35, Q2 63/18, Q3 103/58, Q4 771/442, Q5 24,272/451, Q6 60/60, Q7 603/191, Q8 101/101) | query reproduction **8 / 8 = 100%** | Reproduction is not correctness. **Q7 is a confirmed defect**: it filters `storage_condition LIKE '%80%'`, which returns `80°C` (ambient) as well as `-80°C` (frozen), because the minus glyph was destroyed upstream in 147 rows across 9 surfaces (component F, CQA-F-11). 25 papers depend on the defect; 62–70 of 453 papers contain sign-dropped `80 C`/`20 C` text | High |
| Schema expressiveness | **CRITICAL** | No diet field, no dose field, no effect-size field (all three probes negative); **no sample-group table** and no group column (`sample_group_table_exists=false`); `sample.sample_count` carries an aggregate-vs-per-row ambiguity the schema does not resolve; **183 semicolon multi-value columns**; 59 JSON-encoded columns; 19 tables with no provenance column at all | missing research distinctions **3 / 3 probes** negative; multi-value columns **183 / 866 = 21.1%** | The CDM cannot represent a diet intervention's composition, a dose, or an effect size with uncertainty — three things a microbiome intervention study always has. Multi-value columns store relations that the schema cannot express as relations | High |
| Documentation | **STRONG** | Data dictionary covers **866 / 866 columns = 100.0%**, 0 undocumented; a 79-row `cdm_change_log` with per-row `revert_sql`; `run_metadata` with 11 keys; `MANIFEST.sha256` verifies **36 / 36** CDM files | dictionary coverage **100%**; change-log reversibility **79 / 79 rows carry `revert_sql`** | The dictionary documents the columns, not their *semantics*: three status columns are constants (component G, CQA-G-09) and several columns carry sentinels the dictionary does not name | High |
| Reproducibility | **ADEQUATE** | `run_metadata`: built 2026-10-31T12:19:10, migrated 2026-11-02T02:12:44, promoted 2026-11-02T08:04:46 from `3.0.3-rc1`; 5/5 upstream file hashes MATCH; `section.text_hash_sha256` on 4,006/4,006 sections and `term_mention.section_text_sha256` on 2,505,684/2,505,684 mentions | hash coverage **100%** on sections and mentions; **0%** on `claim_evidence` (`claim_evidence_has_hash=false`) | The build is traceable to inputs, but not *re-executable*: no DDL script ships with the bundle, so the schema cannot be recreated from the release alone | High |
| Query performance | **WEAK** | `term_mention` (2.5 M rows) has **no composite `(paper, section, offset)` index**; any span self-join is quadratic and killed job `28697992` | index coverage: 39/44 tables have ≥1 index; 5 have none; `term_mention` indexes are single-column only | Performance is a usability property, not a correctness one — but on this dataset it decides whether an analysis is feasible | High |

**No averaged score is computed.**

---

## 2. Population and shape

### 2.1 The four structural facts that govern everything else

1. **No types.** 866/866 columns are declared with no type. SQLite's dynamic typing means a column
   can hold `''`, `NOT_REPORTED`, `5` and `"5"` in the same row set. Every sentinel problem in this
   audit (components C, D, F, G) is downstream of this.
2. **No foreign keys.** 0 declared. The schema cannot express `sample → cohort`, so the database
   encodes parenthood as a semicolon list in a text column (`sample.cohort_id =
   "HMCOHORT_1;HMCOHORT_2"`). 183 columns work this way. Splitting them resolves 100%, but no query
   can join on them without a split.
3. **No views.** 0 views over 44 tables means every consumer re-implements the splits, the sentinel
   filters and the anchor logic. This is why the eight research queries are 60–200 lines each.
4. **No sample-group table.** `sample_group_table_exists = false`. The CDM models samples and
   cohorts but not the experimental arm a sample belongs to, which is exactly the distinction most
   microbiome comparisons need.

### 2.2 Table roles

| Group | Tables | Rows |
|---|---|---:|
| Corpus/document | `paper`, `section`, `study`, `publication`, `paper_publication`, `source_asset` | 453 / 4,006 / 453 / … |
| Terminology | `canonical_term`, `term_mention`, `term_definition`, `term_concept_map`, `concept`, `type_harmonization`, `taxonomy_annotation`, `body_site`, `removed_*` | 162,409 / 2,505,684 / 6,773 / 331,394 / 204,817 / … |
| Catalogue | `cohort`, `sample`, `assay`, `dataset`, `data_asset` | 7,085 / 7,530 / 8,545 / 2,976 / 1,992 |
| Claims & triples | `claim`, `claim_evidence`, `relation`, `relation_evidence`, `removed_relation` | 45,667 / 45,667 / 25,788 / 34,416 / 6,925 |
| Compendium | `compendium_project`, `compendium_sample`, `compendium_sample_tag` | present, separate population |
| Governance | `run_metadata`, `load_audit`, `cdm_change_log`, `extraction_run`, `processing_event`, `processing_lineage`, `validation_result`, `evaluation_run`, `human_review`, `cdm_entity_status`, `identifier_crosswalk`, `dataset_release`, `quantitative_result`, `intervention`, `term_occurrence` | mostly empty or thin |

`human_review` holds **0 rows**; `validation_result` holds the pipeline's own check outputs.

---

## 3. Issues

### CQA-H-01 — Zero foreign keys, zero declared types, and no way to enforce either
- **Severity:** **CRITICAL**
- **Type:** Confirmed design defect
- **Evidence:** `PRAGMA foreign_key_list` returns nothing on all 44 tables; 866/866 columns have declared type `NONE`; `journal_mode_persisted='delete'`.
- **Affected:** 44/44 tables, 866/866 columns.
- **Scientific impact:** Every integrity property is post-hoc. A future load can insert a cohort id that does not exist and nothing will stop it. Combined with the semicolon parent lists, the schema cannot represent a many-to-many relation, so it stores one as a string — and then a consumer must split it correctly or silently under-count.
- **Publication impact:** A methods section describing "a relational schema with referential integrity" would be false. The correct description is "a denormalised SQLite export with post-load validation".
- **Recommended action:** Ship the DDL with `FOREIGN KEY` declarations and a junction table for sample↔cohort/dataset, even if enforcement stays off, so the intended shape is documented. Declare column affinities. Do not rebuild the frozen DB.
- **Blocking:** blocks interoperability claims (component M) and any "relational database" framing.

### CQA-H-02 — A fifth of the schema is semicolon multi-value text
- **Severity:** **HIGH**
- **Type:** Confirmed design defect
- **Evidence:** **183** semicolon-separated multi-value columns; **59** JSON-encoded columns (D19). A looser interop scan (D13) counted **119** JSON-valued columns — the two figures measure different things (column declared as JSON carrier vs column whose sampled values parse as JSON) and neither is wrong; they must not be quoted interchangeably. Parent lists (`sample.cohort_id`, `sample.dataset_id`, `assay.dataset_id`, `cohort.dataset_id`, `data_asset.dataset_id`) resolve **100%** into existing ids on every part, so the *content* is sound.
- **Affected:** 183 / 866 columns = 21.1%.
- **Scientific impact:** Resolution at 100% is a property of this load, not of the format. The format has no length limit, no uniqueness guarantee, no ordering guarantee and no null semantics — `""` can mean "none", "unknown" or "not reported", and the CDM uses all three.
- **Publication impact:** Any row count that joins through a semicolon column is a count of *pairs*, not rows, unless it is explicitly deduplicated. The dataset duplicate finding in component F (437 redundant rows) is partly a consequence of this shape.
- **Recommended action:** Document the split rule in the data dictionary next to every such column, and ship a normalised view.
- **Blocking:** blocks clean relational reuse.

### CQA-H-03 — 5,237 dangling `term_concept_map.term_id` values are an undocumented sentinel
- **Severity:** **HIGH**
- **Type:** Confirmed defect (undocumented sentinel)
- **Evidence:** 37 referential checks, 4 with dangling values, 31,198 dangling ids, 25,961 explained by `removed_*` tombstones, **5,237 unexplained** — all in `term_concept_map.term_id`, all tagged `term_status='NOT_IN_TERMINOLOGY'`, i.e. the same 5,237 rows that component D resolved as the live-term filter on the terminology side (331,394 + 11,473 + 5,237 = 348,104 ≠ 334,231 — see component D's reconciliation).
- **Affected:** 5,237 rows.
- **Scientific impact:** A mapping row pointing at a term id that does not exist is indistinguishable from a broken load to anyone who has not read the loader. It is in fact deliberate.
- **Publication impact:** An independent integrity test on this database will report 5,237 unexplained dangling references. That must be answered in the data dictionary, not in a rebuttal.
- **Recommended action:** Document the sentinel, or move those rows to a `orphan_mapping` table. Do not delete.
- **Blocking:** blocks a clean "0 dangling references" claim.

### CQA-H-04 — `canonical_term.mention_count` is wrong on 40.6% of rows
- **Severity:** **HIGH**
- **Type:** Confirmed defect (stale rollup)
- **Evidence:** 61,839 / 152,333 = **40.59%** disagree with the recomputed `term_mention` count. `paper_count` disagrees on 11,756 (7.72%), `definition_count` on 3,316 (2.04%). By contrast all three `relation` rollups are exactly consistent (`mention_count` vs `triple_mention_ids` 0/25,788; `paper_count` vs `paper_ids` 0/25,788).
- **Affected:** 61,839 rows.
- **Scientific impact:** Ranked term lists, "most mentioned term" statements and any mention-weighted statistic read from the rollup column will be wrong for two rows in five. Because the triple layer's rollups *are* consistent, a reader who checks one table and not the other will conclude the database is consistent.
- **Publication impact:** Any mention-frequency figure must be recomputed from `term_mention`, not read from `canonical_term.mention_count`. If the manuscript quotes a top-N term list, state which source it used.
- **Recommended action:** Document the column as stale, or recompute it in a derived view. Do not update in place without a release note.
- **Blocking:** blocks quoting the rollup.

### CQA-H-05 — The `paper.n_*` rollups are mirrors of a different population, not stale counts
- **Severity:** **MODERATE**
- **Type:** Confirmed property (misleading, not broken)
- **Evidence:** All six `paper.n_*` rollups disagree with the CDM's own child tables on **453/453 papers (100%)**, which reads as catastrophic staleness. Component F established the cause: the columns are **catalogue clean-layer mirrors**. Surplus over the CDM tables is **2,586 rows across 399/453 papers**, and `n_findings` differs from the catalogue half by **+405**. The clean layer's own per-entity counts (datasets 3,064, cohorts 7,451, assays 9,292) are the numbers the rollups echo.
- **Affected:** 453 papers.
- **Scientific impact:** A user who trusts `paper.n_samples` gets a number from a population that is not in the database. The mismatch is systematic (mirror of a larger population), not random.
- **Publication impact:** Do not quote `paper.n_*`. If paper-level counts are needed, count the actual child rows and say so.
- **Recommended action:** Rename the columns to `catalogue_clean_*` or drop them from the public schema in the next build.
- **Blocking:** blocks paper-level count claims; does not affect table-level counts.

### CQA-H-06 — 45.6% of `term_mention` rows are redundant
- **Severity:** **HIGH**
- **Type:** Confirmed property (multi-model artefact)
- **Evidence:** 2,505,684 rows collapse to **1,362,888 distinct spans**; 1,142,796 rows (45.6%) duplicate an existing span. Component B verified the *surviving* spans at **99.9978% exact** (2,505,628 exact / 0 mismatch / 56 out-of-range), so the redundancy is not a precision problem — it is four extraction sources emitting the same span.
- **Affected:** 1,142,796 rows.
- **Scientific impact:** Every mention-weighted statistic in the CDM is inflated by up to 1.84× if it is computed over rows rather than spans. The terminology pipeline's dedup (`terminology_dedup.csv`, 166,012 rows) exists precisely to fix this, which confirms the issue is known.
- **Publication impact:** "2.5 M entities extracted" is an observation count, not a mention count. The distinct-span count is 1,362,888.
- **Recommended action:** Publish both counts and name which is used in every denominator.
- **Blocking:** blocks any mention-count claim that does not state its unit.

### CQA-H-07 — Three research distinctions cannot be expressed
- **Severity:** **HIGH**
- **Type:** Confirmed schema gap
- **Evidence:** `research_distinction_probes`: `has_diet_field` **false**, `has_dose_field` **false**, `has_effect_size_field` **false**. `sample_group_table_exists` **false**; no group/arm column on `sample`. `sample_count_column_meaning` = "aggregate vs per-row ambiguity" — the column is used both ways.
- **Affected:** the entire `sample`/`cohort`/`intervention` model.
- **Scientific impact:** Three of the most common questions about a microbiome study — what diet was the cohort on, what dose of the intervention was given, how large was the effect — are not answerable from the schema. `intervention` exists as a table but carries no dose column. Effect size is only present as free text inside `claim`.
- **Publication impact:** The CDM must not be described as supporting intervention or dose–response analysis. It supports association statements.
- **Recommended action:** Document the three gaps explicitly in limitations; they are the honest scope boundary of the model.
- **Blocking:** blocks intervention/dose/effect-size claims.

### CQA-H-08 — Q7 returns the opposite storage condition
- **Severity:** **HIGH**
- **Type:** Confirmed query defect (inherited)
- **Evidence:** Q7 ("stool samples stored at -80 °C") is implemented as `storage_condition LIKE '%80%'` and returns **603 rows / 191 papers**, reproducing exactly. 147 rows across 9 surfaces have the minus destroyed upstream (`stored at 80°C`, `80°C`, `80 C`), so the query returns ambient-stored samples as frozen. Root cause: 6,027 control characters across 122 papers, 220 inside a temperature token across 44 papers (component F, CQA-F-11). The sign loss is **not** introduced by the query and cannot be fixed by the query.
- **Affected:** 147 rows directly; the 603-row answer set includes them.
- **Scientific impact:** A published "N samples stored at -80 °C" figure from this query is contaminated by ambient-stored samples and omits none. The count is right about the string and wrong about the freezer.
- **Publication impact:** Q7 must not be published as a validated query. If the eight-query table is published, Q7 needs a footnote naming the sign-loss artifact and the 44 papers.
- **Recommended action:** Re-express Q7 as a case that requires `-80` or excludes 80-without-minus, and report the exclusion. Do not repair the frozen data.
- **Blocking:** blocks Q7 as a research result.

### CQA-H-09 — The published query package is stored inside the release it validates
- **Severity:** **MODERATE**
- **Type:** Provenance/documentation gap
- **Evidence:** `RESEARCH_QUERY_VALIDATION.csv` is not in `paper/publication/final_validation`; the only copies are under `releases/cdm_v3/3.0.3/remediation/regression/cdm_validation_current_registry/` and `outputs/`. Eight queries, all reproducing.
- **Affected:** the whole validation package.
- **Scientific impact:** A reader following the publication cannot find the queries where the publication says they are. The release validates itself with a package it ships.
- **Publication impact:** The usability table cannot be cited without pointing at a path inside the frozen release, which weakens the reproducibility claim.
- **Recommended action:** Copy the query file into the publication materials (read-only copy) and cite the release path as the origin.
- **Blocking:** blocks a reproducible-usability claim; not a data defect.

### CQA-H-10 — No composite index on the 2.5 M-row mention table
- **Severity:** **MODERATE**
- **Type:** Confirmed usability defect
- **Evidence:** `term_mention` indexes are single-column only; there is no `(paper_id, section_id, start_offset)` index. A span self-join to test overlap is quadratic and **killed job `28697992`**. Five tables have no index at all; 18 have no unique index.
- **Affected:** 2,505,684 rows; any overlap/adjacency analysis.
- **Scientific impact:** The most natural question about an NER table — do two mentions overlap — is not answerable inside the database at this size. This audit had to hash spans in Python to run it.
- **Publication impact:** None directly, but it means "the database supports span-level analysis" is a claim about feasibility that does not hold at this scale.
- **Recommended action:** Add the composite index in the next build (cheap, ~minutes) and document that span joins require it.
- **Blocking:** blocks nothing in the manuscript; blocks practical reuse.

---

## 4. What this component demonstrates, and what it does not

**Demonstrates:**
- 44 tables / 866 columns / 8.49 M rows, 0 views, exact row counts stable across every diagnostic.
- **0 foreign keys, 0 declared types, 27 tables without a PK, 18 without a unique index, 5 without any index.**
- The data dictionary documents **866/866 columns (100%)**, and 79 change-log rows carry reversible SQL — the documentation is the strongest part of this component.
- 8/8 research queries reproduce their published counts exactly, and **Q7 is provably wrong** for a known, upstream, quantified reason.
- `canonical_term.mention_count` is stale on 40.59% of rows; `paper.n_*` disagrees on 100% but is a mirror of another population, not stale.
- 45.6% of `term_mention` rows are duplicate spans; 5,237 dangling ids are a deliberate sentinel.
- Diet, dose and effect size are not representable; there is no sample-group table.

**Does not establish:**
- That the schema is unusable — it answers the eight shipped questions and the whole audit ran on it read-only without corruption.
- That any semantic value in the tables is correct (that is components C–G).
- That adding constraints would change any number in this audit — no content defect found here was caused by the missing PKs.

---

## 5. Component verdict

As an engineering artefact this database is **honest but unconstrained**. It documents all 866 columns, ships a reversible change log, verifies its own manifests, and reproduces all eight of its published queries exactly. Those are not trivial properties and they are why the audit could be done at all.

As a relational database it fails the two properties a reuser will assume: **no declared type** and **no declared foreign key**. A fifth of the schema is semicolon text; a fifth of the terminology table is duplicated rows; the one rollup a reader is most likely to trust (`canonical_term.mention_count`) is wrong on two rows in five; and the column set cannot hold a diet, a dose, or an effect size. Q7 does not merely perform poorly — it returns the opposite storage condition for 147 samples, and the cause is upstream.

The single most consequential item is **CQA-H-07**: the schema's scope boundary. Everything in the CDM is an association statement attached to a paper. It cannot express an intervention's dose, a cohort's diet, or an effect magnitude. A manuscript that respects that boundary is safe; one that implies the CDM supports intervention analysis is not, and no amount of documentation will fix a column that does not exist.
