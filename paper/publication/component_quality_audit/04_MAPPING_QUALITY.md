# Component D — Vocabulary Mapping Quality

**Audited object:** 331,394 `term_concept_map` rows in CDM 3.0.3 (terminology 1.0.1 holds 334,231; the difference is a proved live-term filter, not an error).
**Evidence base:** `diagnostics/results/d17_mapping_definition_quality.json`, `d07_ontology_currency.json`, `d02_referential_integrity.json`, `d11_count_reconciliation.json`.
**Independence:** recomputed from the frozen database. The 331,394 vs 334,231 gap was independently re-derived: 317,521 live-term rows + 11,473 removed-term rows + 5,237 `NOT_IN_TERMINOLOGY` = 334,231; the DB keeps only live-term rows. Residual 2,837 = multiplicity on 2,727 `(term_id, concept_id)` pairs. This is a load-filter artefact, **not a defect**, and is reported here so it is not re-chased.

---

## 1. Dimensional assessment

| Dimension | Rating | Supporting evidence | Measurable indicator | Limitation | Confidence |
|---|---|---|---|---|---|
| Structural integrity | **STRONG** | 331,394 rows; 0 `concept_id` values missing from `concept` (D02/D07); 11,477 `NO_MATCH_FOUND` rows carry no concept by design; `mapping_evidence_status` = `RESTORED` for all rows | referential closure = **100%** (0 dangling concept ids) | Referential closure says the links point somewhere; it says nothing about whether they point to the right concept | high |
| Provenance | **CRITICAL WEAKNESS** | `mapping_provenance` is the literal string *"projected from an existing linking run; not re-queried"* for the whole population; `matched_via` NULL for 310,267/331,394 (93.63%); `source_service_mapping` recorded but no per-row ontology version, no query timestamp, no service response hash | rows with a match path (`matched_via`) = **21,127/331,394 = 6.37%** | The CV-linking run that produced these rows was never re-executed; the mapping cannot be re-derived from the release. Reuse-first design is legitimate but must be labelled as such | high |
| Internal consistency | **WEAK** | `mapping_disposition` REVIEW_REQUIRED 290,021 (87.52%); `is_canonical_candidate` 1 for only 60,352 (18.21%); 49,044 terms have multiple accepted candidates (max 15 per term) | rows closed to a decision = **41,373/331,394 = 12.48%** | An 87.5% open review queue is honest self-labelling, but it means the table is overwhelmingly unadjudicated | high |
| Evidence support | **WEAK** | `relation_vs_label_identity`: EXACT_MATCH with a **non-identical** label = 5,431 rows; AMBIGUOUS with an identical label = 32,078 rows | EXACT_MATCH rows whose label differs = **5,431/26,356+5,431 = 17.09%** of EXACT_MATCH | A relation that says "exact" while the strings differ is a contradiction *unless* the difference is synonymy — which the table does not record per row | high |
| External concordance | **WEAK** | 16,431 terms (10.12%) carry an EXACT_MATCH; 60,315 (37.14%) carry only RELATED_TO or AMBIGUOUS; 11,477 have NO_MATCH_FOUND; 85,663 live terms have **no mapping row at all** | terms with a usable exact link = **16,431/162,409 = 10.12%** | No external oracle was consulted; "concordance" here means internal assignment quality, not agreement with a curated ontology | high |
| Semantic quality | **WEAK** | `relation_deepseek` carries severe label corruption — `WRS`, `RELADED`, `WORNG`, `REATED`, `WORM`, `WRIGHT`, `WRONG`; `(null)||(null)` agreement pairs = 272,164 of 331,394 (82.13%) | model-agreement pairs with both verdicts present = **59,230/331,394 = 17.87%** | Where only one judgement exists there is no second opinion, so "agreement" is undefined rather than positive | high |
| Coverage | **WEAK** | 76,746/162,409 (47.26%) terms have ≥1 mapping row; 85,663 (52.74%) have none; 11,477 rows are NO_MATCH_FOUND | term coverage = **47.26%** | Coverage is measured against the live term set. Because term quality is itself unaudited (Component C), a mapped term need not be a valid concept | high |
| Reproducibility | **CRITICAL WEAKNESS** | `mapping_provenance` explicitly states the run was **not re-queried**; no service version, no timestamp per row; `mapping_evidence_status=RESTORED` on 100% of rows | independently regenerable = **0%** | This is the single largest reproducibility gap in the project. The mapping is a restored artefact with no regeneration path inside the release | high |
| Reusability | **WEAK** | 87.52% REVIEW_REQUIRED; 18.21% canonical-candidate; 93.63% no `matched_via`; separate OMOP view exists but is deliberately outside `VOCAB_PRIORITY` | rows usable without further review ≈ **12.48%** | A consumer must run their own adjudication on 290,021 rows before the table supports ontology-based reasoning | high |

---

## 2. The mapping population, decomposed

| Outcome | Terms | % of live terms |
|---|---:|---:|
| Live terms total | 162,409 | 100.00% |
| With ≥1 mapping row | 76,746 | 47.26% |
| With EXACT_MATCH | 16,431 | 10.12% |
| With RELATED_TO | 56,212 | 34.61% |
| With AMBIGUOUS | 25,396 | 15.64% |
| With NO_MATCH_FOUND | 11,477 | 7.07% |
| With **only** ambiguous/related (no exact) | 60,315 | 37.14% |
| With **no mapping row at all** | 85,663 | 52.74% |

Two facts follow. First, only **1 term in 10** has an exact ontology link. Second, **more than half the vocabulary was never submitted to an ontology lookup** — not failed, not ambiguous, simply absent.

---

## 3. Issues

### CQA-D-01 — The mapping was never re-queried and cannot be regenerated
- **Severity:** **CRITICAL**
- **Type:** Confirmed defect (reproducibility)
- **Evidence:** `mapping_provenance` literal value *"projected from an existing linking run; not re-queried"* on 331,394/331,394 rows (100%); `mapping_evidence_status` = `RESTORED` on 100%; no per-row service version; `matched_via` NULL on 93.63%.
- **Affected:** 331,394/331,394 rows (100%).
- **Scientific impact:** Every ontology link in the release is a restored copy whose originating query is not recorded. If the originating run was wrong, the release is wrong in a way no stored field can reveal.
- **Publication impact:** "Mappings validated against UMLS/OLS/BioPortal" cannot be claimed. What can be claimed is "mappings reused from an earlier linking run; not re-queried for this release".
- **Recommended action:** State the reuse-first design plainly in the methods and in the mapping table's own documentation. Do not describe these as fresh lookups. A future version should re-query a stratified sample and report the agreement rate.
- **Blocking:** blocks any methods statement implying fresh validation. Does not block public release if disclosed.

### CQA-D-02 — 87.52% of mapping rows are REVIEW_REQUIRED
- **Severity:** HIGH
- **Type:** Confirmed defect (unadjudicated population)
- **Evidence:** `mapping_disposition` REVIEW_REQUIRED 290,021 / REJECTED 30,693 / UNRESOLVED 10,680. `human_review` table: 0 rows.
- **Affected:** 290,021/331,394 = 87.52%.
- **Scientific impact:** The mapping table is a candidate set, not an adjudicated mapping. Treating it as a mapping overstates what exists.
- **Publication impact:** Any "X% of terms mapped to ontology concepts" must specify the disposition filter.
- **Recommended action:** Publish the table as candidates with disposition labels intact; never strip the disposition column in an export.
- **Blocking:** blocks claims of an adjudicated mapping.

### CQA-D-03 — 5,431 EXACT_MATCH rows have a non-identical label
- **Severity:** HIGH
- **Type:** Confirmed inconsistency
- **Evidence:** `relation_vs_label_identity`: `EXACT_MATCH|label_differs` = 5,431; `EXACT_MATCH|label_identical` = 26,356. Also `AMBIGUOUS|label_identical` = 32,078.
- **Affected:** 5,431 rows (1.64% of all rows; 17.09% of EXACT_MATCH rows).
- **Scientific impact:** An "exact match" between different strings is only defensible as synonymy, and the table records no synonym evidence per row (`matched_via` is populated for 6.37%). Conversely, 32,078 rows are called AMBIGUOUS while the labels are identical — the reverse contradiction.
- **Publication impact:** The `mapping_relation` field cannot be presented as a validated equivalence relation.
- **Recommended action:** Describe `mapping_relation` as a model-assigned label, not a lexical verdict. Provide the label-identity cross-tab so users can filter.
- **Blocking:** blocks presenting mapping_relation as validated equivalence.

### CQA-D-04 — Model-verdict labels are corrupted by mid-token truncation
- **Severity:** HIGH
- **Type:** Confirmed defect (data hygiene)
- **Evidence:** `relation_deepseek` contains `WRS`, `RELADED`, `WORNG`, `REATED`, `WORM`, `WRIGHT`, `WRONG` — all mid-token truncations of `WRONG`/`RELATED`/`WORD`; the identical defect appears in `relation.verdict_deepseek` (224 off-vocabulary of 25,788, 0.87%) and `term_definition.verdict_deepseek` (107 off-vocabulary of 6,773, 1.58%, including `MENTIO` from `MENTIONED` and `DEFIN` from `DEFINITION`).
- **Affected:** all three verdict columns, at 0.87%–1.58% of their rows.
- **Scientific impact:** A consumer filtering `verdict_deepseek='WRONG'` misses `WORNG`, `WRS`, `WORM`, `WRIGHT`. Filtering `='SUPPORTED'` is safe; filtering any negative class is not. The corruption is silent.
- **Publication impact:** Any count of model-negative verdicts is understated by the truncated remainder.
- **Recommended action:** Ship a documented verdict vocabulary per column and a list of off-vocabulary observed values, so consumers can coalesce them. Do not silently rewrite the frozen values.
- **Blocking:** blocks any negative-verdict count quoted as exact.

### CQA-D-05 — More than half the vocabulary was never mapped
- **Severity:** HIGH
- **Type:** Confirmed defect (coverage)
- **Evidence:** 85,663/162,409 live terms (52.74%) have no `term_concept_map` row of any kind.
- **Affected:** 52.74%.
- **Scientific impact:** Ontology-based reasoning applies to at most 47.26% of the vocabulary. Because unmapped terms are likely also the rare/malformed ones, the mapped subset is biased toward well-formed common concepts.
- **Publication impact:** "Terms are linked to standard ontologies" must be qualified with the 47.26% figure.
- **Recommended action:** Report term-level mapping coverage, not row-level. Distinguish "no candidate found" (11,477) from "never queried" (85,663) — these are different claims and the release currently conflates them.
- **Blocking:** blocks an unqualified linkage claim.

### CQA-D-06 — Concept namespace is unattributable for 90.7% of concepts
- **Severity:** MODERATE
- **Type:** Confirmed defect (provenance)
- **Evidence:** `concept.ontology_name` NULL for 185,822/204,817 (90.72%); `term_concept_map` has **no** `ontology_source` column. `concept` does carry `source_service` (ols 62,383 / bioportal 61,280 / umls 54,381 / omop 18,995 / mesh 6,613 / ncbi_taxon 1,165).
- **Affected:** 90.72% of concepts.
- **Scientific impact:** A concept can be traced to a *service* but not to an *ontology* for 9 in 10 rows. "SNOMED", "MESH", "MONDO" appear for only 9.3% of concepts.
- **Publication impact:** Ontology-level statistics are not obtainable from the release.
- **Recommended action:** State that `source_service` is the attributable field and `ontology_name` is sparse. Do not aggregate by `ontology_name` without stating the 90.7% NULL.
- **Blocking:** blocks any per-ontology breakdown.

### CQA-D-07 — 49,044 terms hold multiple accepted candidates
- **Severity:** MODERATE
- **Type:** Confirmed property
- **Evidence:** `terms_with_multi_accepted` = 49,044 of 76,746 mapped terms (63.9%); `candidate_rank` distributes up to 11+; `is_canonical_candidate` = 1 on 60,352 rows across those terms.
- **Affected:** 63.9% of mapped terms.
- **Scientific impact:** Candidate proliferation without adjudication means "the" mapping of a term does not exist for most mapped terms.
- **Publication impact:** A one-term-one-concept claim is unsupported.
- **Recommended action:** Document that the table is ranked candidates; provide the `candidate_rank=1 AND is_canonical_candidate=1` filter as the documented single-link view, with its caveats.
- **Blocking:** neither, if documented.

### CQA-D-08 — 5,237 rows point at terms that are not in the terminology release
- **Severity:** LOW
- **Type:** Confirmed (self-labelled) defect
- **Evidence:** `term_status` = `NOT_IN_TERMINOLOGY` on 5,237 rows; this is an explicit self-label, so it is honest.
- **Affected:** 5,237/331,394 = 1.58%.
- **Scientific impact:** These rows resolve to no term. They are not anonymous — the status names the condition.
- **Publication impact:** none, if disclosed.
- **Recommended action:** Report the population as "links resolving to no term" alongside the 11,473 REMOVED rows.
- **Blocking:** neither.

### CQA-D-09 — Guard rejections are recorded but unexplained per row
- **Severity:** LOW
- **Type:** Documentation gap
- **Evidence:** `guard_status` kept 314,772 / rejected_guard 16,622; `guard_rejection_reason` column exists.
- **Affected:** 16,622 rows (5.02%).
- **Scientific impact:** Low; the guard did fire and did record.
- **Publication impact:** none.
- **Recommended action:** document the guard rule set.
- **Blocking:** neither.

---

## 4. What this component demonstrates, and what it does not

**Demonstrates (independently verified):**
- Referential closure is exact: every non-null `concept_id` resolves to a `concept` row (0 dangling).
- The row-count difference against terminology 1.0.1 is fully explained by the live-term load filter, with zero unexplained rows.
- The table is honest about its own state: 87.5% REVIEW_REQUIRED, 100% `RESTORED`, explicit "not re-queried" provenance, explicit `NOT_IN_TERMINOLOGY` labelling.

**Does not establish:**
- That any specific mapping is correct. No adjudication exists and none could be performed here.
- That services were queried for this release. The record explicitly says they were not.
- That 47.26% coverage is representative. The unmapped half is likely biased.

---

## 5. Component verdict

This is the weakest of the data components and the one most likely to mislead a reader. The referential and count-layer work is genuinely solid, and the self-labelling discipline (REVIEW_REQUIRED, RESTORED, NOT_IN_TERMINOLOGY, the literal provenance string) is unusually honest. But the substance is thin: **one term in ten has an exact ontology link**, more than half the vocabulary was never looked up, the artefact was restored rather than computed, and the model-verdict column is silently corrupted by truncation. It is a candidate table wearing a mapping table's name, and the release must say so.
