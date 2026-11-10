# Component C — Canonical Terminology Quality

**Audited object:** 162,409 live `canonical_term` rows in CDM 3.0.3 (165,991 in terminology 1.0.1 = 162,409 live + 3,582 removed), with 2,505,684 linked mentions and 3,397 defined terms.
**Evidence base:** `diagnostics/results/d16_terminology_quality.json`, `d03_rollup_consistency.json`, `d04_duplication.json`, `d11_count_reconciliation.json`.
**Independence:** recomputed from the frozen database. The `165,991` vs `162,409` gap was independently proved to be an exact partition (0 overlap, 0 missing live ids) rather than accepted from a report.

---

## 1. Dimensional assessment

| Dimension | Rating | Supporting evidence | Measurable indicator | Limitation | Confidence |
|---|---|---|---|---|---|
| Structural integrity | **STRONG** | 162,409 live terms, 162,338 distinct `term_norm`; the 3,582 removed terms are an exact tombstone complement (0 id overlap with live, 0 live id missing) | live + removed = 165,991 exactly; partition verified | Structural cleanliness says nothing about whether each term is a correct biomedical concept | high |
| Provenance | **WEAK** | `type_source` is NULL for 157,446/162,409 (**96.94%**); only 4,963 rows record how the type was assigned | type provenance recorded = **4,963/162,409 = 3.06%** | The 3,582 removed rows also carry `non_concept_reason` NULL for 3,344 (93.4%) — removal rationale is largely unrecorded | high |
| Internal consistency | **WEAK** | `is_generic_type` flag disagrees with `cdm_type` for **93,580 rows (57.6%)**; `type_disagreement_flag` set on 3,082; 68 `term_norm` groups carry multiple surfaces; 66 surface groups span multiple types | flag-vs-type disagreement = **57.6%** | Some disagreement is legitimate (a flag may be intentionally broader than the type). But a 57.6% disagreement rate means the two fields cannot both be treated as authoritative | high |
| Evidence support | **ADEQUATE** | Every live term reaching the DB has at least one mention by construction (9,940 live terms have no mention — see Issue CQA-C-05); mentions re-anchor at 99.998% (Component B) | terms with ≥1 mention = **152,469/162,409** | Mention support proves the string appears in a paper. It does not prove the string is a concept | high |
| External concordance | **NOT EVALUATED** | No mapping-level validation of term identity was attempted here; Component D assesses mapping concordance separately and finds 37.1% of mapped terms have no EXACT_MATCH at all | — | Deliberately not evaluated: term correctness would require human adjudication | high |
| Semantic quality | **CRITICAL WEAKNESS** | **8 of 15 type values are not in the declared 14-type CDM vocabulary** (`CELL_TYPE`, `DATA_ANALYSIS`, `DNA_RNA`, `GENOMICS`, `LAB_METHOD`, `PATHWAY`, `SAMPLE_METHOD`, `STUDY_DESIGN`). `ENTITY` holds 89,799 terms (55.29%) and 285,399 mentions (24.45%). 9,647 of 12,026 ORGANISM rows lack binomial shape | off-vocabulary types = **8/15 = 53.3%** of type values; generic `ENTITY` = **55.29%** of terms | Component B traces most of the ENTITY mass to one untyped extractor; the off-vocabulary types are a separate, independent defect | high |
| Coverage | **ADEQUATE** | 152,469 terms carry mentions; 162,409 live terms exist; term paper reach: 120,908 terms appear in exactly 1 paper, 1,301 in 50+ | multi-paper terms = **41,501/162,409 = 25.6%** | Long-tail dominance is expected for a literature vocabulary; it also means most terms have a single-paper evidence base | high |
| Reproducibility | **WEAK** | 2,168,717 mentions link to terms; the linking rule is in code, but `type_source` (96.94% NULL) means the type assignment path cannot be re-derived from the data | type assignment reproducible from data = **3.06%** | Term identity (term_norm grouping) is reproducible; type assignment largely is not | high |
| Reusability | **WEAK** | 9,940 live terms have no mention, 93,604 have no concept map, 159,081 have no definition (Component H/P-D02); only 2.09% of terms are defined | terms with definition = **3,397/162,409 = 2.09%** | A consumer wanting definitions or ontology links finds them for a small minority of terms | high |

---

## 2. The type-vocabulary defect in detail

This is the component's most serious finding and it is confirmed, not inferred.

**Declared vocabulary** (`src/cdm_pipeline/config.py:CDM_TYPES`, mirrored in `src/common/__init__.py`): 14 types.
**Observed vocabulary in `canonical_term.cdm_type`:** 15 values, of which **8 are outside the declared set**.

| Type | Terms | % terms | Mentions | % mentions | In declared vocabulary? |
|---|---:|---:|---:|---:|---|
| `ENTITY` | 89,799 | 55.29% | 285,399 | 24.45% | yes (generic) |
| `ORGANISM` | 12,026 | 7.41% | 273,039 | 23.39% | yes |
| `CHEMICAL` | 9,488 | 5.84% | 170,220 | 14.58% | yes |
| `PROTEIN` | 8,472 | 5.22% | 39,274 | 3.37% | yes |
| `DISEASE` | 7,055 | 4.34% | 152,179 | 13.04% | yes |
| `DNA_RNA` | 5,838 | 3.60% | 26,036 | 2.23% | **no** |
| `CELL_TYPE` | 5,148 | 3.17% | 37,132 | 3.18% | **no** |
| `DATA_ANALYSIS` | 5,104 | 3.14% | 42,776 | 3.67% | **no** |
| `CLINICAL` | 4,103 | 2.53% | 51,717 | 4.43% | yes |
| `EXPERIMENTAL_METHOD` | 3,602 | 2.22% | 12,902 | 1.11% | yes |
| `LAB_METHOD` | 3,485 | 2.15% | 18,905 | 1.62% | **no** |
| `GENOMICS` | 2,338 | 1.44% | 24,192 | 2.07% | **no** |
| `STUDY_DESIGN` | 2,048 | 1.26% | 11,510 | 0.99% | **no** |
| `PATHWAY` | 1,958 | 1.21% | 9,271 | 0.79% | **no** |
| `SAMPLE_METHOD` | 1,945 | 1.20% | 12,670 | 1.09% | **no** |

The eight undeclared types carry **31,864 terms (19.62%)** and **181,392 mentions (7.24%)**. They are not random noise — `CELL_TYPE`, `PATHWAY`, `GENOMICS` and `STUDY_DESIGN` are perfectly reasonable *vocabulary extensions*, but they are not the CDM's declared vocabulary, and no documented extension mechanism authorises them. A consumer who codes against `config.py:CDM_TYPES` will silently drop 19.6% of terms.

---

## 3. Issues

### CQA-C-01 — Type vocabulary diverges from the declared CDM vocabulary
- **Severity:** **CRITICAL**
- **Type:** Confirmed defect
- **Evidence:** `cdm_type_not_in_declared_vocabulary` = `["CELL_TYPE","DATA_ANALYSIS","DNA_RNA","GENOMICS","LAB_METHOD","PATHWAY","SAMPLE_METHOD","STUDY_DESIGN"]`; these carry 31,864 terms / 181,392 mentions.
- **Affected:** 19.62% of terms, 7.24% of mentions.
- **Scientific impact:** Every per-type analysis in the project (catalogue type distributions, triple entity types, KG edge typing) is computed over an undocumented 15-value vocabulary while the code and the data dictionary advertise 14. Any claim of the form "X% of terms are type Y" is only valid relative to the observed vocabulary.
- **Publication impact:** A reviewer cross-checking `CDM_TYPES` against the released data finds an inconsistency immediately. It reads as a schema violation.
- **Recommended action:** Do not remap now (that would change frozen records). In the released documentation, publish the **observed** 15-value typology with the 8 extensions explicitly declared as extensions, and state that `config.py:CDM_TYPES` reflects the original 14 and needs alignment in a future version. Add a validation rule for version 4.
- **Blocking:** blocks submission until disclosed; blocks public release until documented.

### CQA-C-02 — `ENTITY` holds 55.29% of terms
- **Severity:** HIGH
- **Type:** Confirmed defect (downstream of CQA-B-03)
- **Evidence:** 89,799 terms / 285,399 mentions typed `ENTITY`; 960,674 mentions (38.3% of all) come from the single-labelled `en_core_sci_lg` source.
- **Affected:** 55.29% of terms.
- **Scientific impact:** Slightly more than half the terminology layer is untyped. Entity-type-based reasoning — a headline capability of a CDM — is available for the other 44.7%.
- **Publication impact:** Type-coverage tables must be read as "typed subset" tables.
- **Recommended action:** Report typed coverage as 72,610/162,409 = 44.71%, and state the ENTITY mass's origin. Do not present the blended mix.
- **Blocking:** blocks any per-type claim stated over all 162,409 terms.

### CQA-C-03 — Type provenance recorded for 3.06% of terms
- **Severity:** HIGH
- **Type:** Confirmed defect (provenance gap)
- **Evidence:** `type_source` NULL 157,446; `deepseek+alternative_seen` 3,676; `deepseek+gemma` 1,287.
- **Affected:** 96.94% of terms.
- **Scientific impact:** For 96.94% of terms there is no record of whether the type came from a model, a gazetteer, a rule, or a default. The type field is therefore not auditable at row level.
- **Publication impact:** Methods text cannot truthfully describe the typing procedure for the bulk of the vocabulary.
- **Recommended action:** Describe typing as "assigned during canonicalisation; per-term provenance not retained" — an honest limitation. Do not reconstruct provenance.
- **Blocking:** blocks a methods claim of per-term type provenance.

### CQA-C-04 — The generic-type flag contradicts the type on 57.6% of rows
- **Severity:** MODERATE
- **Type:** Confirmed inconsistency (partly interpretive)
- **Evidence:** `is_generic_type_flag` = 93,580 rows; `flag_vs_type_disagreement` = 93,580 (identical count — the flag disagrees in exactly the rows where it is set).
- **Affected:** 57.63% of terms.
- **Scientific impact:** Two fields purport to describe the same property and disagree in the majority of flagged rows. A consumer cannot tell which is authoritative.
- **Publication impact:** Any "generic term" statistic is ambiguous.
- **Recommended action:** Document the flag's semantics precisely (it appears to mean "type is not specific enough to be useful", not "type is ENTITY"). Provide the exact filter expression for each intended use.
- **Blocking:** neither, if documented.

### CQA-C-05 — 9,940 live terms have no mention and 3,184 removed terms still carry live mentions
- **Severity:** MODERATE
- **Type:** Confirmed defect
- **Evidence:** `term_mention` join: 152,469 of 162,409 live terms carry ≥1 mention (D02 orphan count 9,940). `removed_terms_with_live_mentions` = 3,184 of 3,582 (88.9%).
- **Affected:** 6.12% of live terms unsupported; 88.9% of removed terms still referenced.
- **Scientific impact:** A live term with no mention has no corpus evidence at all — it exists only in the vocabulary. A removed term with live mentions means 13,927 mentions (per D02) point at a tombstone.
- **Publication impact:** "Every term is grounded in the corpus" is false for 9,940 terms.
- **Recommended action:** Report both residuals. The tombstone design is defensible (removal is recorded, not deleted); what must not be claimed is that the live set is fully grounded.
- **Blocking:** neither; disclose.

### CQA-C-06 — 9,647 ORGANISM terms lack taxonomic shape; no TAXON type exists
- **Severity:** MODERATE
- **Type:** Confirmed defect (semantic)
- **Evidence:** `binomial_like` 18,138 vs `type_ORGANISM_rows` 12,026; `organism_rows_without_binomial_shape` 9,647; `type_TAXON_rows` = 0; `strain_designation_rows` 801.
- **Affected:** 9,647/12,026 = 80.2% of ORGANISM terms.
- **Scientific impact:** ORGANISM appears to hold everything from species binomials to study cohorts ("patients", "mice"), with no separate taxon rank and no strain type. Taxonomic specificity — a core microbiome requirement — is not represented in the type system.
- **Publication impact:** Any claim about taxonomic resolution at term level is unsupported.
- **Recommended action:** State that taxonomic rank is not modelled in 1.0.1/3.0.3; defer to a future version.
- **Blocking:** blocks taxonomic-resolution claims.

### CQA-C-07 — Under-merging of plural forms not detected
- **Severity:** LOW
- **Type:** Risk (tested, negative)
- **Evidence:** `undermerge_plural_count_at_least` = 0; `undermerge_plural_examples` empty.
- **Affected:** none detected.
- **Scientific impact:** None found. Recorded here because the audit tested for it and the result is a genuine negative.
- **Publication impact:** none.
- **Recommended action:** none.
- **Blocking:** neither.

### CQA-C-08 — 68 `term_norm` groups hold multiple surfaces, including control characters
- **Severity:** LOW
- **Type:** Confirmed defect
- **Evidence:** `term_norm_groups_with_multiple_surfaces` = 68; examples include `-diversity`, `80oc`/`80°c freezer`, NUL/control-character artefacts; `removed_reason_non_concept_reason` includes `CONTROL_CHAR` 59.
- **Affected:** 68/162,338 = 0.04%.
- **Scientific impact:** Negligible volume; the NUL cases trace to the four papers in Component A.
- **Publication impact:** none.
- **Recommended action:** document the control-character normalisation rule.
- **Blocking:** neither.

### CQA-C-09 — Removal rationale absent for 93.4% of removed terms
- **Severity:** MODERATE
- **Type:** Confirmed defect (provenance)
- **Evidence:** `non_concept_reason` NULL 3,344 / 3,582; populated for `URL_OR_LICENSE` 156, `CONTROL_CHAR` 59, `FIGURE_TABLE_REF` 14, `SIGNIFICANCE_MARKER` 9.
- **Affected:** 93.4%.
- **Scientific impact:** The removal step is largely unexplained, so a reader cannot tell whether removed entries were non-concepts or merely unlucky.
- **Publication impact:** Cannot defend the word "non-term" for 3,344 entries.
- **Recommended action:** Describe removed entries as "removed during canonicalisation; reason not retained for 93.4%". Do not call them all non-terms.
- **Blocking:** neither, if worded accurately.

---

## 4. What this component demonstrates, and what it does not

**Demonstrates (independently verified):**
- The live/removed partition is exact and internally consistent (0 overlap, 0 missing).
- `term_norm` grouping is nearly 1:1 (162,409 terms / 162,338 norms) — over-merging was not detected, and plural under-merging was tested and not found.
- Abbreviations are typed consistently: 3,445 abbreviation rows with **0** multi-type conflicts.

**Does not establish:**
- That terms are correct biomedical concepts. No adjudication exists.
- That the type distribution reflects biology. It reflects the extractor mix, and 38% of mentions come from an untyped extractor.
- That the vocabulary is the declared one. It is not (CQA-C-01).

---

## 5. Component verdict

The vocabulary is structurally clean and free of gross merge/split errors, and its tombstone discipline is better than most literature-derived resources. It fails on the two things a CDM exists to provide: a **declared type vocabulary that the data actually follows** (it does not — 8 undeclared types, 19.6% of terms) and **typed coverage** (55.3% `ENTITY`). Provenance for typing is 96.9% absent. This component cannot be described as ready for type-based reuse, and its type vocabulary defect is the audit's single clearest schema-level contradiction.
