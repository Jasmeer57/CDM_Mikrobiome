# PASS D3 — Mentions & entities

**FROZEN_DB** = `releases/cdm_v3/3.0.3/microbiome_cdm_v3.db` (sha256 `5d23ba87d29a…`, read-only immutable URI + `PRAGMA query_only=ON` on every connection; all writes confined to this review directory; **no paper-text column selected anywhere in this pass** — every bounds check uses the stored `section.character_count` and stored sha256 stamps only).

**Date**: 2026-11-09 · **Pass scope**: D3 — mentions & entities: offset bounds, anchor/verification semantics, occurrence aggregates, section-text hash stamps, and coverage/census context for `term_mention`, `term_occurrence`, `claim`/`claim_evidence`, `relation_evidence`, and `data_asset`.

**Query file**: `checks_D3.sql` (companion; exact SQL with observed results in `/* … */` comments).

## 0. Method

- **Offsets validated against stored lengths only** — never against paper text (protocol rule). All joins resolve sections under the **unified two-convention** rule from D2 (`section_id_original` = `sec_NNN` OR `section_record_id` = `HMPAPER_xxx:sec:NNN`, always joined on `paper_id` plus section id).
- **Non-vacuity witnesses**: every mismatch-check join in `checks_D3.sql` §6 is paired with a coverage count proving the join covers the child table's *full* row count (term_mention 2,505,684 / claim 45,667 / relation_evidence 34,416 / data_asset 1,992) — so the 0-mismatch results are not artifacts of empty join universes.
- **Performance note**: the per-occurrence aggregate cross-check was first attempted as HAVING with correlated subqueries over 1.36M groups and **timed out at 900 s**; the working CTE-join form completes in ~1 min (recorded in `checks_D3.sql` header).
- **Claim-source attribution corrected in this pass** (earlier ad-hoc readings during query exploration had the two populations backwards; the cross-tab below is live evidence — trust it over any earlier note): `claim.claim_source` splits the 45,667 claims exactly in two:
  - **catalogue_v3_1 (24,272 rows)**: carry `evidence_anchor_status` (WHITESPACE 15,057 / EXACT 3,510 / NORMALISED 2,139 / FUZZY 1,670 / RELOCATED 1,290 / UNANCHORED 560 / NO_EVIDENCE 46), char offsets on 23,526 rows, `evidence_span_*` on 23,666 rows (606 NULL), `evidence_verified` 1/0 = 23,526/746, `section_id` populated (`sec_NNN` convention), `evidence_locator_status` NULL.
  - **corpus_stage52 (21,395 rows)**: carry `evidence_locator_status` only (verified_exact 2,005 / verified_normalized 16,602 / unresolved_not_in_source 2,788), all char/span offsets NULL, `evidence_verified` NULL, `evidence_anchor_status` NULL, `evidence_section_id` populated (`HMPAPER:sec:` convention).
  - Cross-tab witness: `claim_source × (charNULL, spanNULL, locatorNonNull, anchorNonNull, n)` = catalogue_v3_1 (746, 606, 0, 24272, 24272) / corpus_stage52 (21395, 21395, 21395, 0, 21395). All sums tie: 746 + 21,395 = 22,141 NULL char pairs; 606 + 21,395 = 22,001 NULL span pairs; 24,272 − 746 = 23,526 = `evidence_verified=1`.

**Bottom line**: **All offset/anchor checks pass with zero violations.** Every start/end pair across the four offset-bearing child tables satisfies `0 ≤ start < end ≤ stored §length`, every section reference resolves (D2 tie), the `section_text_sha256` stamps equal `section.text_hash_sha256` on **all** rows of all four stamped child tables (joins non-vacuous), and `term_occurrence`'s stored `n_models`/`n_mentions` equal live recomputation from `term_mention` on all 1,362,931 occurrence keys. `SUM(n_mentions) = 2,505,684` ties exactly to the term_mention row count. No new discrepancies; two **PASS-with-note** items (`confidence` all-NULL is dictionary-documented "null only"; `offset_correction` semantics per dictionary = characters added, not a pass-count) and one expected-coverage note (below). One process correction is recorded in-method: my draft reading of the claim-source ↔ evidence-column attribution was backwards and is corrected here against live cross-tabs.

## 1. term_mention (2,505,684 rows) — ALL CLEAN

| Check | Observed | Verdict |
|---|---|---|
| Offset bounds `0 ≤ start < end ≤ character_count` (unified section join) | **0 violations** | PASS |
| Sections unresolvable (either convention) | **0** | PASS |
| NULL offsets | 56 — all 56 `offset_status='UNANCHORED'` (exact correspondence, both directions: 0 UNANCHORED with offsets, 0 non-UNANCHORED with NULL offsets) | PASS |
| `offset_status` census | EXACT 2,348,758 / CORRECTED 156,870 / UNANCHORED 56 → sums to 2,505,684 (ties D1 M01) | PASS |
| `offset_correction` | 0 on 2,348,814 rows (all EXACT + all UNANCHORED); **1 on 154,565 rows and 2 on 2,305 rows — all CORRECTED** (154,565 + 2,305 = 156,870). Dictionary (line 1138): "characters added to both offsets by the 1.0.1 correction (0 if none)" — values are 1- and 2-character shifts, consistent | PASS (note) |
| `term_link_status` | LINKED 2,168,717 / NO_CANONICAL_TERM 299,846 / LINKED_BY_TYPE 30,049 / AMBIGUOUS 7,072; NO_CANONICAL_TERM + AMBIGUOUS = 306,918 = NULL `canonical_term_id` (D2 tie) | PASS |
| `canonical_term_status` | `''` 2,491,757 (live) / `REMOVED` 13,927 (D2 §4 tie) | PASS |
| `confidence` | NULL on all 2,505,684 rows — dictionary line 868 documents the column as "null only" (status NEEDS_EXPERT_REVIEW): **documented, not a defect** | PASS (note) |
| `review_status` | UNVERIFIED on all 2,505,684 rows (nothing human-reviewed) | PASS (context) |
| `unresolved_flags` census | `[]` 2,146,364 / `[SENTENCE_CLIPPED]` 357,755 / `[CONTROL_CHAR_SURFACE]` 1,102 / `[SENTENCE_CLIPPED, CONTROL_CHAR_SURFACE]` 395 / `[OFFSET_UNVERIFIED]` 56 / `[OFFSET_RECOVERED]` 12 → sums to 2,505,684; 357,755+395 = 358,150 = rows with `supporting_sentence_clipped=1`; OFFSET_UNVERIFIED 56 = the 56 UNANCHORED rows | PASS |

Mentions by run × model (sum = 2,505,684): `cpu_ensemble_v1`/ner_model_ensemble — en_core_sci_lg 960,674 / gliner_biomed 297,113 / gliner_medium 168,027 / en_ner_craft_md 119,092 / en_ner_bc5cdr_md 80,584 / en_ner_jnlpba_md 52,989 / biobert_diseases 26,970; `qwen35_vllm_body_v1`/llm_section_ner — Qwen/Qwen3.5-4B 366,123; `mesh_gazetteer_2026`/gazetteer_dictionary_match — mesh-gazetteer 248,088; `qwen_ollama_cell7c_v1`/llm_section_ner — qwen3.5:4b 186,024. (Extraction-method split ensemble 1,705,449 / llm 552,147 / gazetteer 248,088 ties D1 M03.)

## 2. term_occurrence (1,362,931 rows) — ALL CLEAN

- Offset bounds: **0 violations**; 0 unresolvable sections; 48 NULL-offset rows (valid NULLs); `MIN(start)=0`, `MAX(end)=242,820`.
- `SUM(n_mentions) = 2,505,684` — exact tie to term_mention row count.
- **Per-occurrence cross-check**: on all 1,362,931 occurrence keys, stored `n_models` and `n_mentions` equal live recomputation (`COUNT(DISTINCT extraction_model)` / `COUNT(*)` per `occurrence_key`) — **0 / 0 mismatches / 1,362,931 groups**. (`n_models` range 1–9, `n_mentions` range 1–9.)

## 3. claim / claim_evidence evidence anchors (45,667 rows each, 1:1 per D2) — ALL CLEAN

- Inverted/negative offset pairs: **0** (char and span, both tables — mirror columns are 1:1 identical; every census ran on both and matched).
- Bounds vs stored `character_count`: **0 violations** (char_start/char_end, evidence_span_start/end, resolved by own `section_id` for catalogue rows and `evidence_section_id` for stage52 rows).
- NULL censuses: char pairs NULL 22,141 (746 catalogue with `evidence_verified=0` + 21,395 stage52 by design); span pairs NULL 22,001 (606 + 21,395). Attribution per §0 cross-tab.
- **`evidence_verified=0` (746 rows) decomposes exactly**: UNANCHORED 505 + FUZZY 174 + NO_EVIDENCE 46 + NORMALISED 21 = 746, and these 746 are *exactly* the catalogue rows with NULL char offsets. (`evidence_verified=1` spans WHITESPACE 15,057 / EXACT 3,510 / NORMALISED 2,118 / FUZZY 1,496 / RELOCATED 1,290 / UNANCHORED 55.)
- Anchor vs verified cross-tab: matching generally implies verified, with a logically consistent soft edge (129 UNANCHORED+FUZZY+NORMALISED rows verified=1, offset-bearing; 174 FUZZY / 21 NORMALISED rows verified=0, NULL-offset). No internal contradiction; flagged for the trust inventory in D10.

## 4. relation_evidence (34,416 rows) — ALL CLEAN

- `anchor_status` census: WHITESPACE 24,702 / EXACT 5,375 / UNANCHORED 2,224 / NORMALISED 2,115 (sum = 34,416 = D1 row count).
- Offset bounds: **0 violations**; 0 unresolvable sections (record-id convention).

## 5. data_asset (1,992 rows) — ALL CLEAN

- Inverted pairs **0**; `char_end > character_count` **0** (join covers all 1,992 rows); NULL char pairs 76.
- `evidence_anchor_status`: WHITESPACE 957 / EXACT 550 / NORMALISED 203 / FUZZY 125 / RELOCATED 87 / UNANCHORED 70 (sum 1,992).

## 6. section_text_sha256 stamps — ALL MATCH

Stored sha256 stamps on term_mention, claim, relation_evidence, and data_asset equal `section.text_hash_sha256` on **every** row (0 mismatches each; 0 NULL stamps anywhere). Each mismatch join's coverage was separately verified to equal the child table's full row count (2,505,684 / 45,667 / 34,416 / 1,992), so the pass is non-vacuous.

## 7. Coverage & censuses (context)

- 453 papers carry mentions; **2,364 distinct (paper, section) mention-bearing pairs**; 3,553 sections with `character_count>0`; **1,189 non-empty sections have no mentions** — coverage of non-empty sections 66.6% (2,364/3,553). The 453 zero-char sections are all `sec_preface` (one per paper — the known front/(preamble) placeholders; all named "Other" after normalization). The 2,364 vs 2,817 body-unit figure from the working tree is expected (mention coverage ≠ segmentation unit count); **not a discrepancy**.
- `section_quality_status`: COMPLETE 2,746 / REVIEW_REQUIRED 1,236 / PARTIAL 24 (sum 4,006 = D1 section count).
- `entity_type` census (sum = 2,505,684; DATA_ANALYSIS verified 67,397 exactly): ENTITY 960,674 / ORGANISM 380,345 / CHEMICAL 266,188 / DISEASE 209,648 / CLINICAL 126,486 / DNA_RNA 93,941 / CELL_TYPE 86,215 / PROTEIN 79,316 / DATA_ANALYSIS 67,397 / LAB_METHOD 59,885 / EXPERIMENTAL_METHOD 45,548 / GENOMICS 40,891 / PATHWAY 35,123 / STUDY_DESIGN 29,540 / SAMPLE_METHOD 23,266 / GO 1,221.

**Verdict: D3 PASS** — 15/15 checks PASS (2 with notes, 1 expected-coverage context note). New discrepancies: **none**. Cumulative: 12 D0 + 26 D1 + 15 D2 + 15 D3 = **68 rows; 66 PASS / 2 DISCREPANCY** (both D2 findings L-1, L-2 remain the only open discrepancies).
