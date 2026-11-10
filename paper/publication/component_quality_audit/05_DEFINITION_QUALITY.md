# Component E — Definition Quality

**Audited object:** 6,773 `term_definition` rows in CDM 3.0.3 covering 3,397 distinct terms; plus the 1,150-row `term_definitions.jsonl` in terminology 1.0.1.
**Evidence base:** `diagnostics/results/d17_mapping_definition_quality.json` (`definition_*` blocks), independent re-derivation below, `d02_referential_integrity.json`.
**Independence:** the 6,773 figure was independently confirmed by parsing the JSONL as records (not lines) and by direct SQL count. The earlier 9,126 figure was a `wc -l` artefact caused by embedded newlines.

---

## 1. Population decomposition (independently re-derived)

| Slice | Rows | Note |
|---|---:|---|
| `term_definition` rows in CDM 3.0.3 | **6,773** | direct `COUNT(*)` |
| — `extraction_run_id = 'gap G8'`, `extraction_method = 'LLM_SPAN_EXTRACTION:qwen3.5-4b'` | 6,185 | 91.32% |
| — `extraction_run_id = 'termpipeline_t3_rules_v1'`, `extraction_method = 'rule_pattern'` | 588 | 8.68% |
| Distinct `term_id` covered | **3,397** | |
| Distinct `(term_id, definition_text)` pairs | 6,349 | 424 rows are repeated definitions of the same term |
| `term_definitions.jsonl` in terminology 1.0.1 | **1,150** rows / **838** distinct terms | |
| File definitions present in DB (by `term_id` + text) | **547** | |
| File definitions absent from DB | **526** | |
| DB definitions absent from the file | **5,802** | |

**Correction to an earlier framing.** The release file is a **subset in neither direction**: 526 of its 1,073 distinct definitions are not in the CDM, and 5,802 CDM definitions are not in the file. It is not a clean subset, so "the file is the source and the DB is an extended load" is the wrong description. The correct description is: two partially overlapping artefacts, with the CDM carrying 5,623 more rows produced by a different run label.

---

## 2. Dimensional assessment

| Dimension | Rating | Supporting evidence | Measurable indicator | Limitation | Confidence |
|---|---|---|---|---|---|
| Structural integrity | **STRONG** | 6,773/6,773 rows: `section_text_sha256` matches the referenced section (`definition_section_hash` match 6,773, mismatch **0**); `definition_section_not_found` **0**; `definition_empty_text` **0**; `passage_in_section` 6,773/6,773 | definition anchored in its source section = **6,773/6,773 = 100.0%** | Anchoring proves the passage is quoted from the right section. It does not prove the passage is a definition | high |
| Provenance | **ADEQUATE** | `extraction_run_id` and `extraction_method` populated on every row (2 values); `provenance_class` and `definition_source` present; `verdict_deepseek` present | run attribution = **6,773/6,773 = 100%** | Two run labels only, and `gap G8` is a sentinel-looking identifier, not a resolvable job id; `extraction_run` has no matching row for it | high |
| Internal consistency | **WEAK** | 551 rows (8.14%) whose `definition_text` does **not contain the term it defines**; `definition_equals_term` 444 (6.56%); 424 rows duplicate a `(term,text)` pair; 1,107 duplicate definition-text groups across terms | term absent from its own definition = **551/6,773 = 8.14%** | Some absence is legitimate for pronoun-style contextual descriptions; the 444 `definition_equals_term` rows are not | high |
| Evidence support | **ADEQUATE** | Every definition is a verbatim span from an identified section (100% anchor match; `EXACT` 6,460 / `RELOCATED` 313) | verbatim, section-anchored = **100%** | Verbatim extraction can faithfully capture a sentence that is not a definition at all | high |
| External concordance | **NOT EVALUATED** | No dictionary or ontology was consulted to check whether the definition is correct. Doing so would be new adjudication | — | Deliberately not attempted | high |
| Semantic quality | **WEAK** | `CONTEXTUAL_DESCRIPTION` rows show 447/473 (94.5%) not containing the term — e.g. term `prausnitzii` → "carbohydrate preferences of which have been predicted"; term `pathogenesis` → "eAT of HFD-fed". These are passage fragments, not definitions | contextual-description rows that fail to contain their term = **447/473 = 94.5%** | The category is honest about being contextual, but it should not be counted as a definition | high |
| Coverage | **CRITICAL WEAKNESS** | 3,397 of 162,409 live terms carry any definition | definition coverage = **3,397/162,409 = 2.09%** | Coverage is the component's defining limitation: 97.9% of the vocabulary is undefined | high |
| Reproducibility | **WEAK** | 588 rows re-derivable from rules; 6,185 rows are LLM span extractions under a non-resolvable run label | reproducible from rules = **588/6,773 = 8.68%** | The LLM portion is a frozen artefact | high |
| Reusability | **WEAK** | With 2.09% coverage and 8.14% of rows not containing their term, a consumer cannot treat this as a glossary. It functions as an example set | rows that both contain their term and are ≥20 chars = **≈5,161/6,773 = 76.2%** | Filtering to that subset is possible but undocumented | high |

---

## 3. Definition source mix

| `definition_source` | Rows | % | Anchored EXACT | Anchored RELOCATED | Contains its term |
|---|---:|---:|---:|---:|---:|
| `ABBREVIATION_EXPANSION` | 4,154 | 61.33% | 3,986 | 168 | 4,061 / 4,154 = 97.8% |
| `EXPLICIT_AUTHOR_DEFINITION` | 2,037 | 30.08% | 1,901 | 136 | 2,026 / 2,037 = 99.5% |
| `CONTEXTUAL_DESCRIPTION` | 473 | 6.98% | 473 | 0 | 26 / 473 = **5.5%** |
| `GLOSSARY_DEFINITION` | 109 | 1.61% | 100 | 9 | 109 / 109 = 100% |

The table is well-behaved for three of four categories. `CONTEXTUAL_DESCRIPTION` is the outlier: 94.5% of its rows do not contain the term they claim to define, and 100% are anchored `EXACT` — meaning the pipeline extracted a correct span from the correct place and then labelled it a definition of a term that is not in it.

Only **109 rows (1.61%)** come from an actual glossary. Only **32.3%** of abbreviation expansions carry a parenthetical or trailing form, which is low for a class defined by that shape.

---

## 4. Issues

### CQA-E-01 — Definitions cover 2.09% of the vocabulary
- **Severity:** **CRITICAL**
- **Type:** Confirmed limitation
- **Evidence:** 3,397 distinct `term_id` with ≥1 definition vs 162,409 live terms.
- **Affected:** 97.91% of terms have no definition.
- **Scientific impact:** The CDM cannot serve as a defined vocabulary. Any downstream use that assumes a definition exists — glossary generation, concept disambiguation, human-readable entity explanation — fails for 97.9% of terms.
- **Publication impact:** "The CDM provides definitions for its terms" must be rewritten as "provides definitions for 2.09% of its terms". This is a material claim change.
- **Recommended action:** State coverage as a headline limitation. Do not present the 6,773 figure without its denominator in the same sentence. Defer expansion to a future version.
- **Blocking:** blocks any definitional-completeness claim; does not block release if disclosed.

### CQA-E-02 — 551 definitions do not contain the term they define
- **Severity:** HIGH
- **Type:** Confirmed defect
- **Evidence:** `definition_content_checks.term_absent_from_definition` = 551 (8.14%); concentrated in `CONTEXTUAL_DESCRIPTION` at 447/473 (94.5%); the same class also supplies the term-in-definition rate of 26/473 (5.5%).
- **Affected:** 551/6,773 = 8.14%.
- **Scientific impact:** These rows mislabel a passage as a definition of an absent term. A reader taking the row at face value learns something false about the term.
- **Publication impact:** If any definition is quoted in the manuscript, an 8.14% chance of quoting a non-definition exists — concentrated in one class, so checking the class eliminates the risk.
- **Recommended action:** Publish the `definition_source` column unfiltered so consumers can exclude `CONTEXTUAL_DESCRIPTION`. Document that this class is a passage citation, not a definition. Do not silently delete the rows.
- **Blocking:** blocks unqualified use of the definition set; not release.

### CQA-E-03 — 444 definitions are identical to their term
- **Severity:** MODERATE
- **Type:** Confirmed defect
- **Evidence:** `definition_specificity_flags.definition_equals_term` = 444 (6.56%); `under_20_chars` = 1,168 (17.25%).
- **Affected:** 444 rows + 1,168 short rows (overlapping).
- **Scientific impact:** A definition equal to its term conveys nothing; 17.25% of definitions are under 20 characters, at which length a definition is usually a fragment.
- **Publication impact:** Definition-count headlines include these.
- **Recommended action:** Provide documented filter flags; report the filtered count alongside the raw count.
- **Blocking:** neither, if disclosed.

### CQA-E-04 — The release file and the CDM are partially overlapping, not nested
- **Severity:** MODERATE
- **Type:** Confirmed defect (reproducibility / provenance)
- **Evidence:** 1,150 file rows / 1,073 distinct `(term_id,text)` keys; 547 present in DB; **526 file definitions absent from the DB**; **5,802 DB definitions absent from the file**. The `terminology_file_vs_db` block in D17 reports file 1,150 vs db 5,057 / in_file_not_db 562 / in_db_not_file 4,469 — itself a different comparison basis.
- **Affected:** 526 file rows (45.7% of the file) have no CDM counterpart.
- **Scientific impact:** A reader who treats `term_definitions.jsonl` as the source of the CDM's definitions will miss 5,623 rows and cannot reproduce the CDM's definition table from the release files.
- **Publication impact:** The provenance chain "terminology 1.0.1 → CDM 3.0.3" does not hold for definitions.
- **Recommended action:** Document the definitions layer as *two artefacts*: a 1,150-row rule/LLM release file and a 6,773-row CDM table with 5,623 additional LLM rows under run label `gap G8`. State that the CDM table is not derivable from the release file.
- **Blocking:** blocks a clean provenance claim for definitions.

### CQA-E-05 — `gap G8` is not a resolvable extraction run
- **Severity:** MODERATE
- **Type:** Confirmed defect (provenance)
- **Evidence:** 6,185 rows (91.32%) carry `extraction_run_id='gap G8'` with `extraction_method='LLM_SPAN_EXTRACTION:qwen3.5-4b'`. `extraction_run` has no row with that id (D10: run registry rows are `CATNER_…`, `28619916`, `CATCLEAN_v3`, `CATLINK_v2`, …).
- **Affected:** 91.32% of definitions.
- **Scientific impact:** The bulk of the definition table cannot be traced to a registered run.
- **Publication impact:** Methods cannot cite a run for 91% of definitions.
- **Recommended action:** Document `gap G8` as an internal batch label without a registry entry. Do not invent a job id.
- **Blocking:** neither, if disclosed.

### CQA-E-06 — Verdict labels corrupted in `term_definition.verdict_deepseek`
- **Severity:** MODERATE
- **Type:** Confirmed defect
- **Evidence:** 107/6,773 off-vocabulary values (1.58%), including `MENTIO` (26), `DEFIN` (10) — mid-token truncations. Cross-referenced as CQA-D-04.
- **Affected:** 1.58%.
- **Scientific impact:** Negative-class filtering under-counts.
- **Publication impact:** Minor.
- **Recommended action:** ship the verdict vocabulary; do not rewrite.
- **Blocking:** neither.

### CQA-E-07 — 987 terms carry multiple definitions with near-zero overlap
- **Severity:** LOW
- **Type:** Confirmed property
- **Evidence:** `terms_with_multiple_definitions` = 987; `multi_definition_overlap` shows up to 54 definitions for one term with pairwise Jaccard **0.0**.
- **Affected:** 987/3,397 = 29.1% of defined terms.
- **Scientific impact:** Multiple disjoint definitions of one term means either the term is genuinely context-dependent or the extractions are heterogeneous fragments. Given CQA-E-02, the latter is more likely.
- **Publication impact:** none, if the definition set is not treated as authoritative.
- **Recommended action:** document that definitions are per-occurrence, not per-term canonical.
- **Blocking:** neither.

---

## 5. What this component demonstrates, and what it does not

**Demonstrates (independently verified):**
- Every definition is a verbatim span from a hash-verified section (100%), with `EXACT`/`RELOCATED` anchor status recorded.
- The record count is 6,773 and the earlier 9,126 was a parsing artefact — now closed.
- The three "real" definition classes (`ABBREVIATION_EXPANSION`, `EXPLICIT_AUTHOR_DEFINITION`, `GLOSSARY_DEFINITION`) contain their term 97.8%–100% of the time.

**Does not establish:**
- That any definition is semantically correct (no dictionary check was performed).
- That the definition layer is complete — it covers 2.09% of terms.
- That the CDM's definition table can be regenerated from the release files — it cannot.

---

## 6. Component verdict

Structurally impeccable and substantively thin. Span anchoring and hash verification are as good as any component in the audit. But the layer defines 2.09% of the vocabulary, 8.14% of its rows are passages that do not contain their term, 6.56% are tautologies, and the CDM table cannot be derived from the release file. It is a **high-quality evidence extract for a small number of terms**, not a glossary, and it must be described that way.
