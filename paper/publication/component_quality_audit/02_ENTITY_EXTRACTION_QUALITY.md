# Component B — Entity Mention Extraction Quality

**Audited object:** 2,505,684 `term_mention` rows in CDM 3.0.3, produced by 10 extraction sources feeding the terminology 1.0.1 build.
**Evidence base:** `diagnostics/results/d15_entity_extraction.json`, `d01_offset_integrity.json`, `d02_referential_integrity.json`, `d04_duplication.json`, `d20_evidence_tiers.json` (Tier 1 benchmark for context only).
**Independence:** span re-anchoring recomputed against `section.section_text_original` keyed on `(paper_id, section_id_original)`. No prior report supplied these numbers.

> **Measurement discipline.** Nothing below is called precision or recall. The corpus has no human-annotated gold standard (`human_review` = 0 rows). What is measurable is *offset correspondence*, *surface-form hygiene*, *link resolution* and *inter-source overlap*. Those are different quantities.

---

## 1. Source inventory

| Extraction source | Rows | Share | Notes |
|---|---:|---:|---|
| `en_core_sci_lg` | 960,674 | 38.34% | Emits a single generic `ENTITY` label (see limitation below) |
| `Qwen/Qwen3.5-4B` (vLLM, full body) | 366,123 | 14.61% | LLM, no offsets — offsets recomputed downstream |
| `gliner_biomed` | 297,113 | 11.86% | |
| `mesh-gazetteer` | 248,088 | 9.90% | Aho–Corasick over MeSH 2026, dictionary-exact |
| `qwen3.5:4b` (Ollama, historical) | 186,024 | 7.42% | Cell-7c subset, historical |
| `gliner_medium` | 168,027 | 6.71% | |
| `en_ner_craft_md` | 119,092 | 4.75% | |
| `en_ner_bc5cdr_md` | 80,584 | 3.22% | |
| `en_ner_jnlpba_md` | 52,989 | 2.11% | |
| `biobert_diseases` | 26,970 | 1.08% | |
| **Total** | **2,505,684** | 100%* | *D01 counts 2,505,628 offset-verified + 56 unanchored |

---

## 2. Dimensional assessment

| Dimension | Rating | Supporting evidence | Measurable indicator | Limitation | Confidence |
|---|---|---|---|---|---|
| Structural integrity | **STRONG** | Every mention re-anchored against section text: `offset_status` EXACT 2,348,758 / CORRECTED 156,870 / UNANCHORED 56; `section_not_found` 0 | exact offset reproduction = **2,348,758/2,505,628 = 93.74%**; exact + corrected = **99.998%** | CORRECTED means the stored offsets did not reproduce and were re-derived. The stored value was wrong; the mention was salvageable. This is recorded honestly as its own status, not merged into EXACT | high |
| Provenance | **ADEQUATE** | `extraction_model` populated on every row; 10 distinct sources separable; `supporting_sentence` present on 2,455,897/2,505,684 (98.01%) | source attribution = **100% of rows** | No per-row model version string, no run id per mention; a model upgraded in place is indistinguishable | high |
| Internal consistency | **ADEQUATE** | Within-model duplicate spans ≈0 (max 44 rows, 0.0046% of `en_core_sci_lg`); no out-of-range starts except the 56 unanchored | within-model duplicate span rate = **≤0.0046%** | Cross-model duplicates are *expected* and are not counted as defects — 10 models finding the same span is corroboration, not redundancy | high |
| Evidence support | **ADEQUATE** | 99.998% of offsets resolve into section text; `supporting_sentence` covers 98.01% | offset-resolvable = **99.998%** | Offset resolution proves the span exists at that position. It does **not** prove the span is a biomedical entity, only that the characters are there | high |
| External concordance | **NOT EVALUATED** | No gold standard exists for this corpus. Tier 1 public-benchmark F1 for these models (Component I) measures BC5CDR/BioRED performance and cannot be transferred here | — | Reporting BC5CDR F1 as this component's concordance would be a category error | high |
| Semantic quality | **WEAK** | Surface-form issues: `all_caps_short` 221,706; `generic_surface` 150,869; `numeric_only` 16,315; `single_char` 9,239; `trailing_punct` 2,931; `leading_punct` 2,567; `over_200_chars` 89 | rows with at least one surface-form flag ≈ **15.7%** (391,716 flagged instances) | These are flags, not confirmed errors; `all_caps_short` is expected for gene symbols and abbreviations, so most are legitimate. The genuinely suspicious classes are `generic_surface` and `numeric_only` | medium |
| Coverage | **ADEQUATE** | 2,505,684 mentions over 2,817 body sections of 452 papers (plus the 453-section front placeholders); 10 sources with materially different yields — `en_core_sci_lg` alone is 38% | body-section coverage = **2,817/2,817 = 100%** at section level | Section coverage ≠ entity coverage. No measure of what fraction of true entities were found is possible without annotation | high |
| Reproducibility | **WEAK** | Deterministic methods (gazetteer, spaCy, BERT) can be re-run from recorded configs; the two Qwen runs are checkpointed LLM output — vLLM is not bit-deterministic even at `temperature=0` (documented during the repair cycle) | bit-reproducible sources = **8/10** | The 552,147 Qwen rows (22.0%) cannot be regenerated identically. They can be re-derived approximately or treated as a fixed artefact | high |
| Reusability | **ADEQUATE** | Schema is uniform across all 10 sources; `canonical_term_id IS NOT NULL` on 2,198,766 rows (87.75%) = `LINKED` 2,168,717 + `LINKED_BY_TYPE` 30,049 *[corrected 2026-11-05: the original row counted only the `LINKED` token and said 86.55%; see §6, `CQA-B-AMEND-2026-11-05-1`]*; `section_path` allows slicing by paper region | linked-to-term = **2,198,766/2,505,684 = 87.75%** | 299,846 (11.97%) carry `NO_CANONICAL_TERM` and 7,072 (0.28%) are `AMBIGUOUS`; both are unusable for term-level analysis unless re-linked | high |

---

## 3. Issues

### CQA-B-01 — 56 permanently unanchored mentions
- **Severity:** LOW
- **Type:** Confirmed defect
- **Evidence:** `offset_status` = UNANCHORED for 56 rows; they carry no usable start/end or fall outside the section text.
- **Affected:** 56/2,505,684 = 0.0022%.
- **Scientific impact:** Negligible.
- **Publication impact:** None, if disclosed.
- **Recommended action:** Report as a residual; exclude from span-based work by filtering `offset_status != 'UNANCHORED'`.
- **Blocking:** neither.

### CQA-B-02 — 156,870 mentions required offset re-derivation
- **Severity:** MODERATE
- **Type:** Confirmed defect (recovered)
- **Evidence:** `offset_status` = CORRECTED 156,870 (6.26%). The stored `start_offset`/`end_offset` did not index the recorded term in the recorded section.
- **Affected:** 6.26% of mentions.
- **Scientific impact:** Anyone who used the *stored* offsets without re-checking would have been wrong about 1 mention in 16. The audit's re-anchoring recovered them, but the frozen artefact still holds the original values.
- **Publication impact:** Any published claim of "offsets are exact" must be corrected to "93.74% exact, 6.26% re-derived, 0.002% unanchored".
- **Recommended action:** Report the three-way offset status. Do not silently overwrite.
- **Blocking:** neither; it is a reporting correction.

### CQA-B-03 — `en_core_sci_lg` emits a single generic label for 38% of all mentions
- **Severity:** HIGH
- **Type:** Confirmed defect (known limitation)
- **Evidence:** `error_signature` for `en_core_sci_lg`: 960,674 rows, 151,186 distinct surfaces, **1 distinct type**. Every mention is labelled `ENTITY`.
- **Affected:** 960,674/2,505,684 = 38.34% of all mentions are untyped.
- **Scientific impact:** Because it is the largest single source, the terminology layer's type distribution is dominated by an untyped contributor. This is the mechanical origin of the 55.29% `ENTITY` share in Component C. Any per-type analysis inherits it.
- **Publication impact:** Type-coverage figures that include this source are inflated toward `ENTITY` by construction, not by biology.
- **Recommended action:** Either exclude `en_core_sci_lg` from typed analyses and say so, or report type distributions both with and without it. Do not present a single blended type mix as if all sources were typed.
- **Blocking:** blocks submission of any per-type claim presented without this caveat.

### CQA-B-04 — Qwen rows are not bit-reproducible
- **Severity:** MODERATE
- **Type:** Untested assumption / known property
- **Evidence:** vLLM at `temperature=0` is not deterministic on this hardware; documented during the section-cache repair (retries failed at identical character offsets and recovered different rows). 552,147 rows (22.03%) originate from the two Qwen runs.
- **Affected:** 22.03% of rows.
- **Scientific impact:** The artefact is fixed and internally consistent; a future re-run will differ in tail cases.
- **Publication impact:** "Fully reproducible" would be false for this 22%.
- **Recommended action:** Describe Qwen output as a frozen checkpointed artefact with recorded cache, not as a reproducible computation.
- **Blocking:** neither.

### CQA-B-05 — Surface-form noise concentrated in specific classes
- **Severity:** MODERATE
- **Type:** Risk (partly confirmed)
- **Evidence:** `generic_surface` 150,869; `numeric_only` 16,315; `single_char` 9,239; punctuation-adjacent 5,498; `over_200_chars` 89.
- **Affected:** up to 150,869+ (6.0%) for the generic class alone.
- **Scientific impact:** Generic surfaces ("group", "samples", "data") are mention-level noise that inflates totals and pollutes term groups.
- **Publication impact:** Mention totals carry a noise floor of roughly 6%.
- **Recommended action:** Report the generic-surface count; provide a documented filter expression rather than a silently filtered number.
- **Blocking:** neither.

### CQA-B-06 — 11.97% of mentions resolve to no canonical term *[corrected 2026-11-05 — the remainder was mislabelled by including `AMBIGUOUS` in neither complement; see §6, `CQA-B-AMEND-2026-11-05-1`]*
- **Severity:** MODERATE
- **Type:** Confirmed defect (linkage gap)
- **Evidence:** `term_link_status` NO_CANONICAL_TERM 299,846; AMBIGUOUS 7,072; LINKED_BY_TYPE 30,049; LINKED 2,168,717. `canonical_term_id IS NOT NULL` = 2,198,766 (LINKED + LINKED_BY_TYPE).
- **Affected:** 299,846/2,505,684 = 11.97% carry **no canonical term and are not ambiguous**; 7,072 (0.28%) are ambiguous. Together 306,918 = 12.25% do not resolve to a unique term; 87.75% do.
- **Scientific impact:** Term-level statistics silently exclude 12.25% of extracted mentions. If the unlinked 12% is non-random (likely — rare or malformed surfaces fail to link), term counts are biased toward well-formed common terms.
- **Publication impact:** Terminology coverage claims must state the 12.25% remainder. The register's `M13` 87.8% is the correct linked figure and agrees with this one (87.75%); the 11.97% must not be presented as the whole remainder.
- **Recommended action:** Quantify the unlinked remainder's surface distribution; report it as a named residual rather than assuming it is negligible.
- **Blocking:** neither; disclose.

### CQA-B-07 — Sources are partially redundant, not fully complementary
- **Severity:** LOW
- **Type:** Characterisation gap
- **Evidence:** Within-model duplicate span rate ≈0, but cross-model overlap is unquantified in this audit; the frozen comparison reports global inter-model agreement 0.223 (full-body) and 0.156 (historical Ollama) at shared-unit level.
- **Affected:** all sources.
- **Scientific impact:** "Multi-NER ensemble" implies complementarity. Measured agreement of 0.22 suggests substantial divergence — which is either complementarity or mutual error; this audit cannot distinguish them.
- **Publication impact:** The ensemble framing needs the agreement figure attached.
- **Recommended action:** Report inter-model agreement as measured (0.223 full-body / 0.156 historical), explicitly noted as agreement and not accuracy.
- **Blocking:** neither.

---

## 4. What this component demonstrates, and what it does not

**Demonstrates (independently verified):**
- The mention layer is structurally sound: 99.998% of spans resolve into section text, zero section-lookup failures, negligible within-model duplication.
- The offset artefact is honest and three-way-labelled; the 6.26% CORRECTED population is disclosed rather than hidden.
- Ten sources are separable and attributable on every row.

**Does not establish:**
- Precision, recall, F1, or completeness on this corpus. There is no annotation and no possibility of one within this audit's constraints.
- That the ensemble is better than its best member. No per-source accuracy exists, so no selection argument can be made.
- That the 12% unlinked remainder is ignorable.

---

## 5. Component verdict

The strongest part of this component is offset integrity — near-perfect and independently re-derived. The weakest part is semantic: 38% of all mentions come from a source that emits exactly one untyped label, which mechanically propagates into every per-type statistic in Components C, D and F. Extraction is **usable as a span corpus** and **not usable as a type corpus** without separating the untyped contributor. No accuracy statement of any kind is supported.

---

## 6. Amendment record

### `CQA-B-AMEND-2026-11-05-1` — the linkage percentage counted one status token, not the linked population
- **Date:** 2026-11-05
- **Location:** §1 "Reusability" row (indicator and evidence cell) and §3 `CQA-B-06`
  (title, `Affected`, `Scientific impact`, `Publication impact`).
- **Was:** "`term_link_status` resolves 2,168,717 (86.55%) to a canonical term … linked-to-term =
  **2,168,717/2,505,684 = 86.55%**"; and `CQA-B-06` "299,846/2,505,684 = 11.97% unlinked; 7,072
  (0.28%) ambiguous".
- **Now:** "`canonical_term_id IS NOT NULL` on 2,198,766 rows (87.75%) = `LINKED` 2,168,717 +
  `LINKED_BY_TYPE` 30,049 … linked-to-term = **2,198,766/2,505,684 = 87.75%**"; and `CQA-B-06`
  "299,846/2,505,684 = 11.97% carry **no canonical term and are not ambiguous**; 7,072 (0.28%) are
  ambiguous. Together 306,918 = 12.25% do not resolve to a unique term; 87.75% do."
- **Why.** `LINKED_BY_TYPE` is a genuine resolution, not an unresolved state: when the CDM type
  breaks a tie and a unique canonical term results, the loader sets `canonical_term_id` *and* records
  the status as `LINKED_BY_TYPE` rather than `LINKED` (documented in
  `src/cdm_pipeline/…/fix_terminology_offsets.py:13,83` and `cdm_remediation/build_dictionary.py:57`).
  The original row counted only the literal `LINKED` token, so it understated linkage by **30,049
  mentions / 1.20 points**. The 11.97% remainder was likewise labelled "unlinked", which double-counts
  neither but leaves the 0.28% `AMBIGUOUS` block without a home in the complement.
- **Verified read-only in `releases/cdm_v3/3.0.3/microbiome_cdm_v3.db`:**

  | Measure | Rows | Share of 2,505,684 |
  |---|---|---|
  | `canonical_term_id IS NOT NULL` | **2,198,766** | **87.75%** |
  | ├ `term_link_status = 'LINKED'` | 2,168,717 | 86.55% |
  | └ `term_link_status = 'LINKED_BY_TYPE'` | 30,049 | 1.20% |
  | `NO_CANONICAL_TERM` | 299,846 | 11.97% |
  | `AMBIGUOUS` | 7,072 | 0.28% |
  | Sum of the four | 2,505,684 | 100.00% |

- **Consequences checked.** `M13`/`M10` in `MANUSCRIPT_CLAIMS_REGISTER.csv` state 87.8% and are
  **correct and unchanged** — this amendment brings report 02 into agreement with the register rather
  than the reverse. The report's §4 "Does not establish" bullet "the 12% unlinked remainder is
  ignorable" is retained as written and is consistent with the corrected 12.25% (the sentence does not
  quote a precise figure).
- **Scope of the correction:** two figure sentences and one severity-neutral label in this report.
  **No rating changed** — Reusability stays **ADEQUATE**, `CQA-B-06` stays **MODERATE**, and all ten
  Component-B dimension ratings are unchanged. No other report, register row or metric is superseded.
- **Reproducer:**
  ```sql
  SELECT COUNT(*) FROM term_mention WHERE canonical_term_id IS NOT NULL;      -- 2198766
  SELECT term_link_status, COUNT(*) FROM term_mention GROUP BY 1;             -- 4 rows above
  ```
  run against the frozen DB opened `mode=ro`.
- **Type:** reporting defect in this audit, not a data defect.

