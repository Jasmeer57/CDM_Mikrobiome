# Terminology Catalogue Audit — Microbiome-CDM

- **Audit ID:** `terminology_catalogue_audit` (version 1, 2026-10-25)
- **Scope:** the terminology build at `results/terminology_v1/` (authoritative build = Slurm job `28619916`), its upstream inputs (`data_catalogue/`, `zenodo_v1/`, `results/{llm_ner_body,mesh_ner,cv_linking,omop_linking,omop_vocab}/`), and its downstream consumer `corpus_v2/releases/2.2.0/`.
- **Mode:** read-only. No pipeline output was overwritten, deleted, or regenerated. No extraction or normalization logic was modified during verification. No extraction rerun was launched.
- **Method:** every number below comes from an executable read-only probe over the artifacts on disk. Probe scripts live in `.audit_tmp/` (scratch, not to be committed); they import the *real* `scripts/termpipeline/textnorm.py` and `ids.py` and the project's canonical section loader `cdm_pipeline.ner.runner_sections.load_sections`, so counts are not re-implementations.

---

## 1. Executive verdict

**Verdict: READY WITH LIMITATIONS — not ready to serve as the terminology layer of the Human Microbiome CDM in its current form.**

The build is *technically consistent and mechanically reproducible*: the manifest verifies (9/9 artifacts present, 8/8 external sha256 OK), identifiers re-derive exactly, definition spans reproduce byte-for-byte, and the stored frequency counters recompute with zero mismatches. It is **not yet a complete, evidence-backed terminology catalogue**, for four independent reasons:

1. **The mention ⇄ term link is not materialised and loses 53.1% of mention rows.** `term_mentions.jsonl` carries `canonical_term_id: null` on **all 2,505,735 rows**, so "every canonical term can be traced to its original mentions" is satisfied only by an implicit, type-constrained string join that fails for the majority of rows (1,330,766 / 2,505,735 = 53.11%).
2. **Frequency is not deduplicated across models.** `mention_count` on a canonical term is the raw count of matching mention *rows*; with 4 extractors over the same text the same span is counted up to 4× (overall row-to-occurrence inflation **1.8385**; **1.6065** on matched rows). No section-level frequency is materialised at all.
3. **Coverage of definitions and mappings is low and the fields the spec expects are only partly present.** Definitions: **838 / 165,991 = 0.5049%** of canonical terms. Mappings: **60,056 / 165,991 = 36.18%** of canonical terms carry a vocabulary concept id; **94,458 (56.90%)** have no mapping row at all.
4. **The broader data catalogue does not describe this resource.** `data_catalogue/` documents a *different* terminology artifact, and `corpus_v2/releases/2.2.0/` ships a *third*, unrelated `terminology_inventory.csv` (39,694 rows) with no reference to `results/terminology_v1/` anywhere.

Separately and emphatically: **nothing in this resource is human-reviewed.** Every one of the 2,505,735 mentions is `review_status=UNVERIFIED`; every one of the 1,150 definitions and 334,231 mapping rows is `REVIEW_REQUIRED`/`UNRESOLVED`; every row of the 2.2.0 inventory is `verification_status=pending`. There is **no human-review evidence anywhere** in the terminology build. Structural completeness must not be read as scientific validation.

### The three axes, stated separately

| Axis | Status | Basis |
|---|---|---|
| **Technically consistent** | **YES (with defects)** | Manifest hashes verify; ids re-derive (165,991/165,991); validation 3,553/3,553 sections pass; stored counters recompute (0 mismatches); definition spans reproduce 1,150/1,150 byte-exact. Defects: off-by-one in a declared count, 5,237 orphan mapping rows, 3,556 duplicated `mapping_id`s. |
| **Semantically reliable** | **NOT ESTABLISHED** | No gold standard, no human verdicts, no accuracy measurement is possible. Mappings are lexical/candidate matches (`RELATED_TO` 188,313 = 56.3% of rows), not equivalence assertions. 56.90% of terms are unmapped; taxonomy classification is 0/165,991. |
| **Human-reviewed** | **NO** | 0 human verdicts in `calibration/calibration_sample.csv` (390 rows, 14 strata, empty human columns). 0 records marked human-reviewed. |

---

## 2. Artifact inventory and authoritative-source decisions

### 2.1 The terminology build — `results/terminology_v1/` (job `28619916`)

All 9 manifest artifacts are **PRESENT**; all **8** external `sha256` values **verify OK** on disk; the manifest's own hash is `n/a` (self-reference, by design). One JSONL file per logical dataset (A–E below) plus a run report and manifest.

| Artifact | Format | Bytes | Records | Verification |
|---|---|---|---|---|
| `term_mentions.jsonl` | JSONL | 3,571,822,409 | 2,505,735 | sha256 OK |
| `canonical_terms.jsonl` | JSONL | 128,869,681 | 165,991 | sha256 OK |
| `term_definitions.jsonl` | JSONL | 806,386 | 1,150 | sha256 OK |
| `term_ontology_mappings.jsonl` | JSONL | 382,755,547 | 334,231 | sha256 OK |
| `terminology_validation.jsonl` | JSONL | 2,593,819 | 4,006 | sha256 OK |
| `terminology_taxonomy.json` | JSON | 42,159 | — | sha256 OK |
| `ontology_registry.json` | JSON | 4,275 | — | sha256 OK |
| `terminology_extraction_report.md` | Markdown | 8,567 | — | sha256 OK |
| `terminology_extraction_manifest.json` | JSON | 6,940 | — | `n/a` (self) |

Per-stage summary JSONs: `_mentions_summary.json`, `canonical_terms_summary.json`, `_definitions_summary.json`, `mapping_projection_summary.json`, `taxonomy_summary.json`, `validation_summary.json`. Note the file is `_definitions_summary.json`, not `definitions_summary.json`.

**Authoritative-source decision:** `results/terminology_v1/` (job `28619916`, post-fix rebuild) is the authoritative terminology build. It supersedes the pre-fix build `28609294` (preserved in `scratch/pre_fix_snapshot/`). No release-scoped copy of this build exists — see §2.3.

### 2.2 Upstream inputs (read-only)

| Source | Role | Count |
|---|---|---|
| `data_catalogue/terminology/terminology_dedup.csv` | T2/T3 input | 166,012 rows |
| `zenodo_v1/ner_453_sections/all_ner_sections_combined.csv` | T1 `cpu_ensemble` | 1,705,501 data rows (1 empty-surface skipped) |
| `zenodo_v1/qwen_sections_ner/qwen_sections_ner.csv` | T1 `qwen_ollama` | 186,024 |
| `results/llm_ner_body/vllm_sections_ner.csv` | T1 `qwen_vllm_body` | 366,123 |
| `results/mesh_ner/mesh_ner_terms.csv` | T1 `mesh_gazetteer` | 248,088 |
| `results/cv_linking/cv_mapped_entities.jsonl` | T5 candidates (cv_linking) | — |
| `results/omop_linking/omop_links.csv` | T5 candidates (omop_local) | — |
| `results/omop_vocab/omop_index.sqlite` | local OMOP index (spot-check target) | 10,167,185 concepts |
| `segmented_sections_markdown/` | section text (offset ground truth) | 453 papers, 4,006 units, 26,867,649 chars |

`data_catalogue/` and `zenodo_v1/` are frozen/checksummed bundles and were **not** modified.

### 2.3 `corpus_v2/releases/2.2.0/` — confirmed, but does NOT contain this build

The release is genuine: `corpus_manifest.json` declares `corpus_version 2.2.0`, `schema_version 1.1.0`, 453 papers (447 canonical), 4,006 sections, 26,874,831 chars, 7,909,432 tokens; `MANIFEST.sha256` re-verifies **42/42 entries OK, 0 bad, 0 missing**. Validation outcome `{REVIEW_REQUIRED 392, COMPLETE 46, PARTIAL 15}`.

**However:** 2.2.0 ships `terminology_inventory.csv` (39,694 rows, schema `term_normalized, term_original_variants, term_type, papers_count, sections_count, occurrences, mean_llm_confidence, example_context, verification_status`; **all 39,694 rows `verification_status=pending`**), and a grep of the *entire* release tree for `terminology_v1`, `term_mentions`, or `canonical_terms` returns **nothing**. 2.2.0's `data/` holds 16 unrelated JSONL files. The release does **not** carry, reference, or checksum the terminology build audited here.

**Consequence:** the audited build has no release-scoped manifest. `results/terminology_v1/` is a mutable `results/` working directory. This is itself a provenance gap (see Issue `ISS-010`).

---

## 3. Required-field coverage (datasets A–E)

Full matrix in `terminology_catalogue_field_coverage.csv`. Headline: the spec's expected fields are **present under different names** in most cases, **absent in three**, and **present but with a different counting scope** in two.

### A. Deduplicated terminology catalogue — `canonical_terms.jsonl` (165,991 rows, 25 fields, all 100% populated)

| Spec field | Actual | Coverage | Status |
|---|---|---|---|
| `canonical_term_id` | `term_id` (`HMCTERM_<sha1(term_norm,cdm_type)[:16]>`) | 165,991/165,991 | **PASS** |
| `normalized_term` | `term_norm` | 165,991/165,991 | **PASS** |
| `preferred_label` | `term` (display form from upstream row) | 165,991/165,991 | **PARTIAL** — no explicit "preferred" logic |
| `alternative_labels` | *none* (`alternative_types` is a list of **CDM types**, not labels) | 0/165,991 | **FAIL — field absent** |
| `term_type` | `cdm_type` (+ `alternative_types`, `n_candidate_types`) | 165,991/165,991 | **PASS** |
| `definition` | via `definition_status` flag; text in `term_definitions.jsonl` | 838/165,991 flagged found | **PARTIAL** — linked, not inline; 0.5049% populated |
| `definition_source` | `term_definitions.definition_source` | linked | **PARTIAL** |
| `definition_evidence_id` | `term_definitions.definition_id` + offsets | linked | **PASS** (linked) |
| `mention_frequency` | `mention_count` | 155,514/165,991 non-null | **PARTIAL** — scope is *raw cross-model rows*, not deduplicated occurrences |
| `paper_frequency` | `paper_count` | 155,514/165,991 non-null | **PASS** |
| `section_frequency` | *none* | 0 | **FAIL — field absent, not materialised anywhere** |
| `first_seen` / `last_seen` | *none* | 0 | **NOT_APPLICABLE** — no timestamps in the corpus; not derivable |
| `normalization_method` / `normalization_status` | *no explicit fields* | 0 | **PARTIAL** — implied by `term_norm` (see §4 dedup findings) |
| `mapping_status` | via `term_ontology_mappings` (`mapping_relation`/`mapping_disposition`) | linked | **PARTIAL** — not reflected on the canonical row |
| `verification_status` | `review_status` = `UNVERIFIED` | 165,991/165,991 | **PASS** (honest machine status) |
| `source_release`, run ids | `source_table` only | 165,991/165,991 | **PARTIAL** — canonical rows carry no `extraction_run_id` |

### B. Terminology mention evidence — `term_mentions.jsonl` (2,505,735 rows, 26 fields, all 100% populated)

Surface form, normalized form, paper/section/paragraph/sentence ids, char offsets, supporting sentence/passage, extraction method/model/run id, and offsets are all present. Two spec requirements fail on **content, not presence**:

- `canonical_term_id` **present but `null` on 2,505,735/2,505,735 rows (100%)** — the mention→term link is not materialised. **FAIL.**
- `confidence` `null` on 100% of rows; `normalization decision/status` has no dedicated field (only `unresolved_flags`). **PARTIAL.**

### C. Definitions — `term_definitions.jsonl` (1,150 rows, 19 fields, all 100% populated)

Source paper, section, sentence, char span, `definition_text`, `definition_source`, `definition_formality` (`contextual` 1,003 / `formal` 147), `provenance_class` (`SOURCE_DERIVED` 100%), and `review_status` are present. Definition-vs-external-resource separation exists via `definition_source`/`provenance_class`. **All 1,150 reproduce byte-exact at section-body-relative offsets (1,150/1,150).**

Caveats that cap this at PARTIAL: `CONTEXTUAL_DESCRIPTION` (1,003/1,150 = 87.2%) is *not* a formal definition (the stage says so itself); `EXPLICIT_AUTHOR_DEFINITION` is only 21 rows and its figure-legend contamination was tightened (56→21); zero rows are human-reviewed.

### D. Controlled-vocabulary mappings — `term_ontology_mappings.jsonl` (334,231 rows)

Present: `term_id`, `ontology_source`, `source_service`, `concept_id`, `concept_label`, `mapping_relation`, `mapping_disposition`, `candidate_rank`, `is_canonical_candidate`, `competing_candidates`, `scores`, `staged_match`, `provenance`, `auto_accept_eligible`. Vocabulary versioning lives in `ontology_registry.json` (MeSH 2026; OMOP `vocabulary_download_v5 (2018-06-02)`; live UMLS/BioPortal/OLS4/NCBI Taxonomy). Concept-existence spot check: **40/40 sampled `omop_local` concept ids found in `omop_index.sqlite`**.

Defects (details §6): 5,237 orphan rows (term_id absent from canonical), `mapping_id` is not a unique row key (3,556 ids repeat, 4,150 extra rows), `NO_MATCH_FOUND` 11,477 vs `LOOKUP_FAILED` **0** (the no-match/failed-lookup distinction the spec requires is present in the schema but unexercised in this build).

### E. Frequency definitions

**No frequency rule is materialised or documented as data anywhere.** See §7. This is the weakest dataset of the five.

---

## 4. Deduplication and normalization findings

Recount performed with the *real* `textnorm.sanitize` and `ids.term_id` (an earlier hand-rolled sanitizer missing the C1 block `\x7f-\x9f` under-counted collisions; it is not used here).

| Step | Count |
|---|---|
| Upstream dedup table rows | 166,012 |
| Distinct sanitized `(term_norm, cdm_type)` pairs | **165,991** |
| T2 kept | 165,991 |
| Collapsed by sanitize (`deduped_after_sanitize`) | **21** |
| Non-concept surfaces flagged (`is_non_concept_surface=True`) | 1,090 |
| Distinct kept `term_norm` | 165,905 |
| Norms carrying >1 CDM type | 81 |

- **`term_id` re-derivation reproduces 165,991/165,991 ids (0 mismatches).** One term per `(term_norm, cdm_type)`; no duplicate `term_id`.
- **Correctly merged (deterministic, intended):** case (`Bacteroides`/`bacteroides`/`BACTEROIDES`), Unicode NFKD (`Bacteröides`), fullwidth forms, en/em-dash, slash/underscore, trailing dash, whitespace collapse. **No norm is both generic (`ENTITY`) and typed** — there is no `ENTITY`-swallowing false merge at the norm level.
- **Not merged (documented, intentional gaps):** singular/plural (`antibiotic`/`antibiotics`, `microbiome`/`microbiomes`, `protein`/`proteins`, `analysis`/`analyses`), hyphen-vs-space, acronym vs expansion (`PSC` ≠ `primary sclerosing cholangitis`), taxon abbreviation (`E. coli` ≠ `Escherichia coli`), strain designations. These are correctly kept separate (merging them string-wise would be unsafe) but they *do* fragment frequency counts.
- **Latent defect (T3 only):** `extract_definitions.load_terms` keys its dict on `term_norm` **alone**, not `(term_norm, cdm_type)`. In *this* build it is harmless — every multi-type norm's alternate row carries a control byte and is dropped by the non-concept filter, so **0 surviving collisions** — but it is fragile: any future clean multi-type norm would be silently overwritten. Precise test available (`ISS-009`).
- **Collision semantics:** of 97 norms appearing in >1 upstream row (107 extra rows), **21** are same-type control-byte duplicates (the sanitize collapses above) and **86** are same-norm/different-type pairs legitimately kept as separate canonical terms.

**Counts before/after reconciliation:** 166,012 upstream rows → 165,991 canonical terms (−21 collisions) → 155,514 terms receive a mention rollup → 838 receive a definition. Unresolved candidates: **10,477 canonical terms (6.31%) have no mention at all**; **94,458 (56.90%) have no mapping row**. No false merges were found; the missed merges are the listed plural/hyphen/acronym gaps.

---

## 5. Count and provenance reconciliation

| Check | Result |
|---|---|
| Manifest sha256 (8 external artifacts) | 8/8 **OK** |
| `corpus_v2/releases/2.2.0/MANIFEST.sha256` | 42/42 **OK** |
| `term_id` re-derivation | 165,991/165,991 match |
| Definition span reproduction (section-body-relative) | **1,150/1,150 byte-exact** |
| Definition `term_id` in canonical | 0 missing; 0 norm/type mismatch |
| Stored `mention_count` recompute | **0 mismatches** |
| Stored `paper_count` recompute | **0 mismatches** |
| Validation | 3,553 VALIDATED + 453 NOT_APPLICABLE; **0 flagged**; 453/453 papers |
| Sections with content / total | 3,553 / 4,006 (453 zero-char `front/(preamble)` = NOT_APPLICABLE) |
| Chars processed | 26,867,649 |
| Mentions checked / resolved / unresolved | 2,505,650 / 2,505,650 / **0** |
| Mapping concept-id spot check (OMOP) | 40/40 found |

### 5.1 The mention ⇄ canonical join loses 53.11% of rows

`term_mentions.jsonl` → `canonical_terms.jsonl` is an implicit join on `(normalized_mention, entity_type) = (term_norm, cdm_type)`.

- matched rows **1,174,969 / 2,505,735 = 46.89%**
- unmatched rows **1,330,766 / 2,505,735 = 53.11%**
  - **Class A — 1,030,912 rows (77.47% of unmatched):** the surface exists in canonical under a *different* CDM type (e.g. `patients` tagged `CLINICAL` in the mention, canonicalised under `DISEASE`). Top offenders: `patients`, `samples`, `abundance`, `study`, `gut microbiome`.
  - **Class B — 299,854 rows (22.53% of unmatched):** the surface is absent from canonical entirely (plural/case divergence).

This is **not** a silent-write bug — no records were dropped — but it means the naive mention→term traceability the spec requires is **not available from the artifacts**: any consumer that joins on the string gets less than half the evidence. `mention_count`/`paper_count` are *defined by this same constrained join*, which is why they recompute with 0 mismatches: they are internally consistent yet systematically under-inclusive relative to the mention file.

### 5.2 Cross-run double counting

- 2,505,735 mention rows vs **1,362,931** distinct `occurrence_key` → **1.8385 rows per occurrence** overall.
- On matched rows: 1,174,969 rows vs **731,369** distinct occurrences → **1.6065× inflation**.
- **23,921 canonical terms** have a stored `mention_count` greater than their distinct-occurrence count.
- Extractor composition of the 2,505,735 rows: `cpu_ensemble_v1` 1,705,500 / `qwen35_vllm_body_v1` 366,123 / `mesh_gazetteer_2026` 248,088 / `qwen_ollama_cell7c_v1` 186,024. **These must never be summed as independent occurrences** — the correct dedup unit is `occurrence_key`.

### 5.3 Declared-count off-by-one (reproduced exactly)

The report §2 and `_mentions_summary.json` declare **2,505,736** mention records; the artifact and the manifest hold **2,505,735**. Root cause, confirmed against source: `assemble_mentions.py` increments `n` *before* `if not surface: continue` (line 242 vs 246–247), so the one empty-surface row in the `cpu_ensemble` CSV (verified: 1,705,501 data rows, **exactly 1** empty `term`) is counted in `rows`/`rows_written` but never written. Declared `cpu_ensemble` rows 1,705,501 vs actual emitted 1,705,500.

The report's §1 "Mentions checked 2,505,650 / Unresolved 0 / 100%" uses a *different* denominator from §2: 2,505,650 = offsets **verified 2,505,616 + recovered 34**, which **excludes the 85 `OFFSET_UNVERIFIED` rows**. §1 reads as "all mentions", §2 reads as "rows written"; neither is wrong alone, but the report does not state that the 85 are outside §1's denominator.

### 5.4 Mapping-file integrity

| Finding | Count |
|---|---|
| Rows | 334,231 |
| Orphan rows (`term_id` not in canonical) — **all** `source_service: mesh` | **5,237** |
| ↳ `NORM_EXISTS_OTHER_TYPE` | 3,268 |
| ↳ `NORM_ABSENT` | 1,969 |
| ↳ `BROKEN_ID` | 0 |
| Non-null `mapping_id` rows | 322,754 |
| Distinct non-null `mapping_id` | 318,604 |
| Repeated `mapping_id`s / extra rows | **3,556 / 4,150** (max 3 repeats) |
| Distinct `(term_id, source_tier, concept_id)` / extra rows | 316,657 / **6,097** (max 6) |
| Exact duplicate rows (all fields identical) | **0** |
| Canonical terms with a mapping row | 71,533 / 165,991 = **43.09%** |
| Canonical terms with **no** mapping row (all generic `ENTITY`) | 94,458 / 165,991 = **56.90%** |
| Canonical terms with a concept id | 60,056 / 165,991 = **36.18%** |
| Distinct concept ids | 206,805 |
| Concept ids owned by >1 term | 41,759 |
| `terms_lookup_failed` | **0** |

`mapping_id` therefore **is not a unique row key** (a concept repeated across `candidate_rank` 1..n yields the same id). The report's "terms with any candidate = 65,293" **includes the 5,237 orphan term_ids**; the honest in-canonical figure is 60,056 with a concept id.

---

## 6. Controlled-vocabulary mapping coverage and validity

Composition of 334,231 rows: relations `RELATED_TO` 188,313 (56.35%) / `AMBIGUOUS` 96,038 (28.73%) / `EXACT_MATCH` 38,403 (11.49%) / `NO_MATCH_FOUND` 11,477 (3.43%). Services: `bioportal` 136,417 / `ols` 84,859 / `umls` 68,989 / `omop` 21,881 / `mesh` 8,652 / none 11,477. `auto_accept_eligible=True` on 38,334 rows (11.47% of rows; **0 auto-accepted** — no human calibration). Ineligible reasons: `CONTROL_CHAR` 875 / `URL_OR_LICENSE` 274 / `FIGURE_TABLE_REF` 130 / `SIGNIFICANCE_MARKER` 112 / `ROMAN_NUMERAL` 43 / `CITATION_FRAGMENT` 15.

Validity: source terms and vocabulary ids are kept in separate columns (good); MeSH rows carry `mesh_ui`, `concept_label`, `mesh_tree` (7,522 with tree), `mesh_kind`; OMOP rows propagate `matched_via`, `standard_concept_id/label`, `omop_domain/concept_class/standard`, and follow `Maps to`; CV rows carry `origin`/`canonical`/`all_mappings`/`provenance` with the explicit note "projected from an existing linking run; not re-queried". OMOP is a **separate view, deliberately not in `VOCAB_PRIORITY`**; local index is 2018-06-02. Distinguishing genuine no-match from failed lookup is *modelled* (`NO_MATCH_FOUND` vs `LOOKUP_FAILED`) but **only the former occurs (11,477 vs 0)**.

Qualification: `RELATED_TO` and `AMBIGUOUS` together are 284,351/334,231 = **85.08%** of rows and are **candidates, not equivalence claims**. Treating any of them as validated mappings would be unsupported.

---

## 7. Mention, paper, and section frequency reconciliation

**No frequency definition is materialised.** The rule must be inferred from code:

- **Mention frequency** → `canonical_terms.mention_count` = number of mention **rows** whose `(normalized_mention, entity_type)` equals the term's `(term_norm, cdm_type)`. Scope: **raw, cross-model, undeduplicated rows** (see §5.2). Reproductible, but it is *not* a count of distinct occurrences.
- **Paper frequency** → `canonical_terms.paper_count` = distinct `paper_id` among those same rows. Reproductible; 0 mismatches.
- **Section frequency** → **not materialised anywhere**. Derivable (`distinct (paper_id, section_id)` per term) but absent, so the spec's third frequency is **FAIL**.
- Upstream `n_observations`/`n_papers` (from `terminology_dedup.csv`) are a **third scope** and do **not** equal `mention_count`/`paper_count` — e.g. `Bacteroides`: `n_observations` 4,536 / `n_papers` 246 vs `mention_count` 6,040 / `paper_count` 252.

Correct dedup unit: `occurrence_key = HMOCC_<sha1(paper|section|start|end|norm)>` — extractor-independent. Distinct occurrences: **1,362,931** (overall) / **731,369** (matched). Paper scope: **453**. Section scope: **2,364 distinct `(paper, section)` units** in the mention file; validation covers 3,553 content sections.

---

## 8. Data-catalogue integration status

**FAIL.** Three mutually inconsistent terminology artifacts exist, and none references the others:

| Artifact | Rows | Schema | Status | Referenced by |
|---|---|---|---|---|
| `results/terminology_v1/canonical_terms.jsonl` (this build) | 165,991 | 25 fields, `HMCTERM_` ids | `UNVERIFIED` | **nothing** |
| `data_catalogue/terminology/terminology_dedup.csv` (upstream input) | 166,012 | dedup table | — | `data_catalogue/README.md` |
| `corpus_v2/releases/2.2.0/terminology_inventory.csv` | 39,694 | `term_normalized…verification_status` | `pending` | 2.2.0 release only |

- `data_catalogue/README.md` documents **only** the inner `terminology/` files and does **not** mention `results/terminology_v1/`.
- `corpus_v2/releases/2.2.0/` contains **no** reference to `terminology_v1`, `term_mentions`, or `canonical_terms`.
- `data_catalogue/MANIFEST.json` (453 papers / 56,985 records / 1,003 files / `char_coverage_pct` 90.857 / `REVIEW_REQUIRED`) describes the inner bundle; its own `README.md` still quotes the pre-finalize count 51,941 vs the authoritative 56,985.

None of the spec's integration requirements (resource name/purpose, schema, record counts with scope, extraction/normalization/mapping run ids, vocabulary versions, quality checks, human-review status, integrity hashes, relationships to mentions/papers/definitions/concepts) are satisfied *for this build* by any catalogue document.

---

## 9. Human-review and scientific-quality limitations

- **0** of 2,505,735 mentions human-reviewed (`UNVERIFIED`).
- **0** of 1,150 definitions human-reviewed (`REVIEW_REQUIRED`).
- **0** of 334,231 mapping rows human-approved (322,754 `REVIEW_REQUIRED`, 11,477 `UNRESOLVED`); **0** `auto_accepted`.
- **0** of 165,991 terms taxonomy-classified (`classified_terms: 0`; taxonomy DRAFT, 16 upper / 66 sub + reserved `UNCERTAIN`); every `taxonomy_category` is `null`.
- **0** human verdicts in `calibration/calibration_sample.csv` (390 rows / 14 strata; human columns empty — the sheet was preserved untouched, which is correct).
- Lacking human verdicts, **no accuracy, precision, recall, or F1 can be reported** for NER, dedup, definitions, or mappings. Only agreement/coverage/reproducibility are measurable, and only those are reported here.

Reaching any `auto_accepted > 0` requires filling the sheet: a 95% Wilson lower bound needs **n ≥ 73** per stratum; the current 60/stratum gives lo ≈ 0.9398.

---

## 10. Requirement classification

| # | Requirement | Status | Severity | Smallest corrective action |
|---|---|---|---|---|
| 1 | Inspect project; artifact inventory with counts/versions/verification | **PASS** | — | none |
| 2A | Dedup catalogue has all required fields | **PARTIAL** | Medium | add `alternative_labels`, `section_frequency`, `normalization_method/status`; add `extraction_run_id` to canonical rows |
| 2B | Mention evidence preserves link to canonical term | **FAIL** | **High** | materialise `canonical_term_id` (type-constrained join) in T1/T2, or add a `term_mentions` backlink + a documented fallback for the 53.11% type-divergent rows |
| 2C | Definitions supported by identifiable evidence | **PARTIAL** | Medium | schedule human review; separate `CONTEXTUAL_DESCRIPTION` from formal definitions in any "definition" rollup; add `section_path` |
| 2D | Mappings valid, versioned, qualified | **PARTIAL** | **High** | fix 5,237 orphans + duplicate `mapping_id` key; do not report `RELATED_TO`/`AMBIGUOUS` as mappings |
| 2E | Frequency rules defined + reproducible | **PARTIAL** | **High** | materialise `section_frequency`; define `mention_count` on distinct `occurrence_key` (or state the row scope in the schema) |
| 3 | Dedup/normalization verified without unsafe merges | **PARTIAL** | Low | document the plural/hyphen/acronym gaps; add the T3 norm-key regression test |
| 4 | Counts + provenance reconciled, no silent loss | **PARTIAL** | **High** | fix the 53.11% join gap, the off-by-one count, and the orphan/dup rows; reconcile `n_observations` vs `mention_count` scopes in the report |
| 5 | Data catalogue describes the terminology resource | **FAIL** | **High** | add a dataset entry for `results/terminology_v1/` (or promote it into a release) with schema, counts, provenance, hashes; reconcile the three inventories |
| 6 | Verification report with required sections | **PASS** | — | this document |
| 7 | Six deliverables produced | **PASS** | — | these files |
| 8 | Read-only; no logic changes; no secrets | **PASS** | — | none |
| — | Human scientific verification | **NOT_VERIFIABLE** | **High** | fill `calibration_sample.csv`; commission term/definition/mapping review |
| — | `first_seen`/`last_seen` | **NOT_APPLICABLE** | — | not derivable from a static corpus |

---

## 11. Prioritized fix list (only what is actually required)

**P1 — correctness of the resource itself**
1. **Materialise the mention→term link.** Emit `canonical_term_id` in `term_mentions.jsonl` via the type-constrained join and add an explicit, documented resolution for the 1,330,766 rows (53.11%) whose `entity_type` disagrees with the canonical `cdm_type` (e.g. a `canonical_term_id_loose` + `link_status`). Without this the resource cannot be audited claim-by-claim.
2. **Fix the off-by-one.** Move `n += 1` after the empty-surface `continue` in `assemble_mentions.py` (or count written rows), so `rows_written` == artifact rows (2,505,735). Correct report §1/§2 denominators and state that the 85 `OFFSET_UNVERIFIED` rows are excluded from "checked".
3. **Fix mapping-file key integrity.** De-duplicate the 5,237 orphan MeSH rows (or re-key them to the correct `(term_norm, cdm_type)`) and make `mapping_id` unique per row (include `candidate_rank` or emit a separate `candidate_id`). Correct the "65,293 terms with any candidate" claim to exclude orphans.

**P2 — the fields the spec requires**
4. **Materialise and document frequency.** Add `section_frequency`; define `mention_count` over distinct `occurrence_key` (and keep the raw row count as `mention_rows`) so cross-model double counting (1.6065×) cannot be mistaken for corpus frequency.
5. **Add the missing A-fields** (`alternative_labels` from the upstream variants, `normalization_method`/`normalization_status`), or record them explicitly as unavailable in the catalogue schema.

**P3 — discoverability and review**
6. **Integrate with the catalogue.** Add a `results/terminology_v1/` (or a frozen release) entry to `data_catalogue/` and/or `corpus_v2/releases/2.2.0/` with schema, counts+scope, run ids, vocabulary versions, hashes, and known limitations; reconcile the 165,991 / 166,012 / 39,694 inventories or state why they differ.
7. **Enable human review.** Fill `calibration_sample.csv` (≥73/stratum for a 95% bound) and commission term/definition/mapping adjudication; only then can any accuracy claim be made.

**P4 — hardening**
8. Add the T3 norm-only-key regression test and document the intentional non-merges (plural/hyphen/acronym/taxon).

---

## 12. Final decision — the seven questions

1. **Do we already have a complete deduplicated terminology catalogue?**
   **No.** We have a *consistently deduplicated* catalogue of **165,991** terms (from 166,012 rows, 21 control-byte collisions collapsed; ids re-derive exactly), but it is not *complete*: **94,458/165,991 = 56.90%** of terms have no mapping row, only **838/165,991 = 0.5049%** have any definition, **10,477/165,991 = 6.31%** have no mention at all, and **0/165,991** are human-reviewed. It is structurally sound and semantically unvalidated.

2. **Can every canonical term be traced to its original mentions and source papers?**
   **Not from the artifacts as shipped.** `canonical_term_id` is `null` on **2,505,735/2,505,735** mention rows; the link exists only as an implicit type-constrained string join that resolves **1,174,969/2,505,735 = 46.89%** of rows and loses **53.11%**. Traceability is *possible in principle* (both sides are present and `occurrence_key` is stable) but **not materialised**, and 10,477 canonical terms (6.31%) have no mention to trace to.

3. **Are definitions available and traceable where they exist?**
   **Where they exist, yes — but they barely exist.** All **1,150/1,150** definition rows have a valid `term_id`, correct `(term_norm, cdm_type)`, and a byte-exact reproducing span (1,150/1,150 verified). Coverage is **838/165,991 = 0.5049%** of canonical terms, with **1,003/1,150 = 87.2%** being `CONTEXTUAL_DESCRIPTION` (not formal definitions). **0** are human-reviewed. No definition was fabricated for a term that lacked one.

4. **Are CV mappings valid, versioned where possible, and appropriately qualified?**
   **Versioning and qualification: yes. Validity: unproven, with defects.** Vocabularies are versioned (`ontology_registry.json`: MeSH 2026, OMOP 2018-06-02, live UMLS/BioPortal/OLS4/NCBI Taxonomy); OMOP concept ids spot-check 40/40 in the local index; `RELATED_TO`+`AMBIGUOUS` (85.08% of rows) are correctly flagged as candidates, not equivalence. But **5,237 rows are orphans** (term_id not in canonical) and `mapping_id` is not unique (3,556 repeats / 4,150 extra rows); only **38,403/334,231 = 11.49%** are `EXACT_MATCH`, and **0** are auto-accepted. Do not treat any row as a validated mapping.

5. **Are frequencies reproducible and free from cross-run double-counting?**
   **Reproducible: yes. Free from double-counting: no.** Stored `mention_count`/`paper_count` recompute with **0 mismatches**, but `mention_count` counts raw mention *rows* across four extractors — the same span is counted up to 4× (**1.8385** overall; **1.6065** on matched rows), and 23,921 terms have `mention_count` > their distinct-occurrence count. **Section frequency is not materialised at all.** Only distinct `occurrence_key` (1,362,931) is a valid occurrence unit.

6. **Is the terminology resource correctly described by the broader data catalogue?**
   **No.** `data_catalogue/` documents a different artifact and never mentions `results/terminology_v1/`; `corpus_v2/releases/2.2.0/` ships an unrelated 39,694-row `terminology_inventory.csv` and has **zero** references to this build. Three inconsistent terminology inventories coexist with no cross-reference, and this build has no release-scoped manifest.

7. **What must be fixed before this resource can serve as the terminology layer of the Human Microbiome CDM?**
   At minimum, in order: **(P1)** materialise the mention→term link and resolve the 53.11% type-divergent rows; fix the off-by-one declared count; de-duplicate/orphan-fix the mapping file and make `mapping_id` unique. **(P2)** materialise and document `section_frequency` and define `mention_count` on distinct occurrences; add the missing catalogue fields. **(P3)** add a discoverable, checksummed catalogue/release entry for this build and reconcile the three inventories. **(P4)** commission human review (fill `calibration_sample.csv`) — without it the resource is a *candidate* terminology layer, not a validated one.

**Bottom line:** *technically consistent* (with three concrete defects), *not semantically reliable*, and *not human-reviewed*. Structurally complete enough to iterate on; not yet complete, completeable, or scientifically validated as the CDM terminology layer.
