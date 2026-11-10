# Component A — Literature Corpus Quality

**Audited object:** corpus 2.2.0 as frozen into CDM 3.0.3 (`paper`, `section`, `study` tables) — 453 papers, 4,006 sections, 26,874,831 section characters.
**Evidence base:** `diagnostics/results/d14_corpus_quality.json`, `d01_offset_integrity.json`, `d11_count_reconciliation.json`, `d13_interop_reproducibility.json`.
**Independence:** all values recomputed read-only from the frozen database and the 2.2.0 release files. No prior PASS report was consulted for these numbers.

---

## 1. Dimensional assessment

| Dimension | Rating | Supporting evidence | Measurable indicator | Limitation | Confidence |
|---|---|---|---|---|---|
| Structural integrity | **STRONG** | 453/453 papers have section rows; 4,006/4,006 `section.text_hash_sha256` recompute exactly against `section_text_original` (D01/D13); `conversion_uncovered_chars` total = 0; 453 distinct BioProjects, no sharing | section hash verification **4,006/4,006 = 100.0%** | Hash verification proves the stored text was not altered after segmentation; it does **not** prove the text equals the publisher's article | high |
| Provenance | **ADEQUATE** | 453 distinct `text_version_id`; `extraction_tool`, `raw_file_hash`, `retrieval_date`, `source_url` populated; provenance chain 2.2.0 → catalogue 3.1.1 → CDM 3.0.3 recorded | `text_version_id` distinct = **453/453** | `license_name` is NULL for **453/453** and `reuse_permission_checked` = `unclear` for **453/453**; rights provenance lives only in an external matrix (Component N) | high |
| Internal consistency | **WEAK** | 5 duplicate-DOI groups / 6 extra paper rows still present (`is_canonical=false`); `validation_status` = REVIEW_REQUIRED for 392/453; `full_text_completeness` = `partial` for 407/453; 52 papers carry `metadata_conflicts` | papers marked `REVIEW_REQUIRED` = **392/453 = 86.5%** | REVIEW_REQUIRED is a self-declared upstream flag, not an audited failure count; this audit did not independently re-grade each paper | high |
| Evidence support | **WEAK** | `fulltext_crosscheck_status`: COMPLETE 282, PARTIAL 14, NULL 157. Text-to-PDF agreement was never closed out for 171/453 papers | cross-check closed = **282/453 = 62.3%** | No independent PDF-to-text oracle exists in this audit; the crosscheck flag is inherited, not recomputed | medium |
| External concordance | **ADEQUATE** | DOI format-valid 447/453; PMID format-valid 440/453; BioProject 453/453; identifier values are unique where expected | identifier format validity = **447/453 = 98.7%** (DOI) | Format validity ≠ identifier correctness. No live Crossref/PubMed resolution was performed, so a well-formed but wrong DOI would pass | medium |
| Semantic quality | **ADEQUATE** | Section segmentation yields 4,006 units; `section_hierarchy_status` complete 2,764 / needing review 1,242; exactly 453 zero-char `front/(preamble)` placeholders (one per paper, structurally expected) *[the 453 count is the Python view; SQLite `LENGTH()` reports 454 zero-length rows — see §5, `CQA-A-AMEND-2026-11-05-1`]* | sections complete = **2,764/4,006 = 69.0%** | Section names are publisher-specific; no controlled vocabulary was applied, so cross-paper section comparison needs mapping | high |
| Coverage | **ADEQUATE** | `full_text_availability` = `available_full_text` 453/453; title 447; abstract 413; PMCID 353 | full text present = **453/453 = 100.0%** | "Available" is the upstream claim. `full_text_completeness=partial` for 407 papers means full text was present but not proven complete | high |
| Reproducibility | **STRONG** | Every section carries a SHA-256 of its own text; the 2.2.0 release pins `source_file_hash_sha256`; `_conversion_report.json` present | independently re-verified hashes = **4,006/4,006** | Reproducible *as stored*; the PDF→text step itself is not bit-reproducible (tool versions, OCR variance) | high |
| Reusability | **WEAK** | `eligibility_status` = `pending` for 447/453; `inclusion_decision` = `pending` for 447/453; `annotation_status` = `not_started` for 453/453; `reviewer` unfilled | papers with a closed eligibility decision = **6/453 = 1.3%** | An external group can reuse the text and sections today. What they cannot inherit is a curation decision, because none was ever recorded | high |

**No averaged score is computed.** This component is technically clean (hashing, segmentation, identifiers) and curatorially open (no eligibility closure, no licence in the record).

---

## 2. Issues

### CQA-A-01 — Corpus never reached curation closure
- **Severity:** HIGH
- **Type:** Confirmed defect (process, not data corruption)
- **Evidence:** `paper.eligibility_status` = `pending` 447, `duplicate` 6; `paper.inclusion_decision` = `pending` 447, `exclude` 6; `paper.annotation_status` = `not_started` 453; `paper.reviewer` unpopulated; `human_review` table has **0 rows**.
- **Affected:** 447/453 papers (98.7%) carry no inclusion decision; 453/453 carry no annotation status.
- **Scientific impact:** The corpus is presented as 453 human-microbiome papers, but the recorded state is "gathered", not "screened". Readiness claims that depend on a screened corpus are unsupported by the record.
- **Publication impact:** A reviewer who opens `paper` and sees `pending` × 447 will ask how inclusion was decided. The answer must be documentary, not narrative.
- **Recommended action:** Do not backfill retroactively with new judgments (that would be new annotation). Either (a) state explicitly in the manuscript that inclusion was a retrieval criterion, not a screening decision, and describe the criterion; or (b) record the historical criterion as `inclusion_decision` with its evidence, clearly labelled as reconstructed. Option (a) is honest and requires no new science.
- **Blocking:** blocks submission (as an unstated claim), not public release.

### CQA-A-02 — Six duplicate paper rows remain in the CDM
- **Severity:** MODERATE
- **Type:** Confirmed defect (data)
- **Evidence:** 441 distinct DOIs across 447 DOI-bearing papers; 5 duplicate groups / 6 extra rows (`10.1038/sdata.2018.68` ×3; four groups of ×2). All six carry `is_canonical=false` and `eligibility_status=duplicate`.
- **Affected:** 6/453 rows (1.3%), 5 DOIs.
- **Scientific impact:** Low for aggregates already filtered to `is_canonical`, but any query that joins `paper` without a canonical filter double-counts those papers' entities, sections and claims.
- **Publication impact:** Paper-level counts quoted from unfiltered joins will be slightly wrong.
- **Recommended action:** Document the canonical filter requirement prominently; do not delete (retaining duplicates with a flag is the correct design). Verify every headline count was taken over `is_canonical=1` or is deliberately over 453.
- **Blocking:** neither, provided the filter is documented.

### CQA-A-03 — Eight-six percent of papers self-declare REVIEW_REQUIRED
- **Severity:** MODERATE
- **Type:** Confirmed defect (upstream validation state)
- **Evidence:** `validation_status` REVIEW_REQUIRED 392 / COMPLETE 46 / PARTIAL 15; `full_text_completeness` partial 407 / complete 46; `sections_needing_review` 1,242 of 4,006.
- **Affected:** 392/453 (86.5%) papers; 1,242/4,006 (31.0%) sections.
- **Scientific impact:** The corpus layer's own validator did not reach a clean state for most papers. Downstream components inherit this without a compensating control.
- **Publication impact:** Reporting "453 papers" without this flag overstates corpus cleanliness.
- **Recommended action:** Report the validation distribution in the manuscript's data-availability section rather than a bare count. Do not attempt to close these flags in this audit cycle.
- **Blocking:** neither; it is a reporting requirement.

### CQA-A-04 — Licence absent from the corpus record itself
- **Severity:** MODERATE
- **Type:** Confirmed defect (provenance)
- **Evidence:** `paper.license_name` NULL for 453/453; `reuse_permission_checked` = `unclear` for 453/453. Licence data exists only in `paper/publication/rights/PAPER_RIGHTS_MATRIX.csv` (Component N).
- **Affected:** 453/453 papers.
- **Scientific impact:** None directly.
- **Publication impact:** Two records now disagree in spirit — the CDM says "unclear" while the rights matrix asserts a specific licence for 318 papers. Anyone using the CDM alone will conclude reuse permission was never assessed.
- **Recommended action:** Note in the data dictionary that rights are held externally and that `reuse_permission_checked=unclear` is a not-assessed sentinel, not a finding of no permission.
- **Blocking:** neither; documentation.

### CQA-A-05 — Encoding defects and metadata conflicts
- **Severity:** LOW
- **Type:** Confirmed defect (data)
- **Evidence:** `source_integrity`: 4 papers contain U+0000 bytes (`HMPAPER_000446` from the PRJNA750230/413199/307231/486009 family); `papers_with_metadata_conflicts` = 52.
- **Affected:** 4/453 (encoding); 52/453 = 11.5% (metadata conflicts).
- **Scientific impact:** NUL bytes are documented ligature artefacts and are slice-exact, so offsets remain valid; they are a display/parse hazard, not a corruption.
- **Publication impact:** Any consumer reading these four files as UTF-8 text without NUL handling will see truncated strings.
- **Recommended action:** Document the four paper IDs and the NUL handling rule; do not rewrite the markdown (hash-pinned by 2.2.0).
- **Blocking:** neither.

### CQA-A-06 — Identifier gaps
- **Severity:** LOW
- **Type:** Confirmed defect (coverage)
- **Evidence:** 6 papers without DOI, 13 without PMID, 100 without PMCID, 40 without abstract, 6 without title.
- **Affected:** DOI 1.3%, PMID 2.9%, PMCID 22.1%, abstract 8.8%, title 1.3%.
- **Scientific impact:** PMC-only retrieval and any DOI-keyed join will drop those papers.
- **Publication impact:** Minor; should be stated if identifier-based linkage is quoted.
- **Recommended action:** Report identifier coverage alongside paper count.
- **Blocking:** neither.

---

## 3. What this component demonstrates, and what it does not

**Demonstrates (independently verified):**
- The stored corpus text is internally immutable — 4,006/4,006 hashes reproduce.
- Segmentation is complete in the sense that no source character is uncovered (`conversion_uncovered_chars` = 0) and exactly one zero-char preamble placeholder exists per paper.
- Identifiers are well-formed and BioProjects are 1:1 with papers.
- The layer is regenerable and independently checkable because hashes are stored per section.

**Does not establish:**
- That the text matches the publisher's version of record. The crosscheck flag was never closed for 171/453 papers, and this audit added no independent oracle.
- That the 453 papers were screened for eligibility. The record says the screening was never completed.
- That the corpus is representative of human-microbiome literature. No sampling frame was audited; this is a convenience corpus built from a reference paper's citation network.
- Anything about completeness of the underlying literature (no recall claim is possible without a defined universe).

---

## 4. Component verdict

Structurally one of the strongest components in the audit: hashes verify, offsets are complete, identifiers are clean, and the layer is independently checkable. Curatorially it is open — 98.7% of papers have no eligibility decision and 100% have no annotation status — and its own validator reports REVIEW_REQUIRED for 86.5% of papers. It is **usable as a text corpus today** and **not quotable as a screened corpus** without a stated inclusion criterion. The two must not be conflated in the manuscript.

---

## 5. Amendment record

### `CQA-A-AMEND-2026-11-05-1` — two ways of counting characters give two totals (reporting caveat only)
- **Date:** 2026-11-05
- **Location:** §1 "Semantic quality" row (the "exactly 453 zero-char placeholders" clause), and the
  26,874,831-character figure in the header block.
- **What was incomplete.** The header states 26,874,831 section characters and the dimension table
  states "exactly 453 zero-char `front/(preamble)` placeholders". Both are correct **for a Python
  `len()` read** and both are reproduced by this audit. They are *not* what SQLite reports, because
  `LENGTH()` on a TEXT value stops at the first U+0000 character. Users querying the frozen DB with
  SQL therefore see different numbers than users reading the CSVs, and neither is wrong.
- **Both views, measured on `releases/cdm_v3/3.0.3/microbiome_cdm_v3.db`:**

  | View | Total section characters | Zero-length rows |
  |---|---|---|
  | Python `len(text)` (UTF-8, surrogate-safe decode) | **26,874,831** | **453** |
  | SQLite `SUM(LENGTH(section_text_original))` | **26,781,631** | **454** |

  Difference: **93,200 characters** and **1 row**.
- **Cause.** 14 sections in 4 papers carry at least one U+0000 byte. The extra SQL-zero row is
  `HMPAPER_000120 / sec_gap_000`, which is **4,310 characters long and begins with U+0000**
  (`nulpos = 0`), so `LENGTH()` returns 0 for a section that is not empty. The other 13 are
  *truncated*, not zeroed — `LENGTH()` simply stops at the NUL:

  | Paper | Section | Python chars | SQL chars | NUL at |
  |---|---|---|---|---|
  | `HMPAPER_000120` | `sec_gap_000` | 4,310 | **0** | 0 |
  | `HMPAPER_000187` | `sec_002` | 22,242 | 1,171 | 1,171 |
  | `HMPAPER_000187` | `sec_003` | 8,228 | 485 | 485 |
  | `HMPAPER_000187` | `sec_004` | 31,655 | 11,907 | 11,907 |
  | `HMPAPER_000187` | `sec_005` | 216 | 149 | 149 |
  | `HMPAPER_000187` | `sec_007` | 2,154 | 870 | 870 |
  | `HMPAPER_000240` | `sec_005` | 13,097 | 10,348 | 10,348 |
  | `HMPAPER_000446` | `sec_gap_000` | 631 | 46 | 46 |
  | `HMPAPER_000446` | `sec_001` | 1,881 | 331 | 331 |
  | `HMPAPER_000446` | `sec_002` | 5,740 | 107 | 107 |
  | `HMPAPER_000446` | `sec_003` | 8,114 | 237 | 237 |
  | `HMPAPER_000446` | `sec_004` | 12,474 | 289 | 289 |
  | `HMPAPER_000446` | `sec_005` | 8,417 | 44 | 44 |
  | `HMPAPER_000446` | `sec_postamble_007` | 251 | 226 | 226 |

  Sum of deltas = 93,200, which is exactly `26,874,831 − 26,781,631`. The 205 NULs in the frozen
  markdown are the upstream PDF ligature-extraction artifact already documented in
  `AGENTS.md` ("NUL-byte corpus artifact"); they are **not** introduced here and the markdown must
  **not** be rewritten (it is hash-pinned by corpus 2.2.0 `source_file_hash_sha256`).
- **Consequences, stated rather than fixed.**
  1. **Every "share of the corpus" percentage depends on which total is the denominator.**
     Component N quotes a 37.24% withheld share against the SQL total (26,781,631); the same
     numerator is **37.11%** against the Python total (26,874,831). Both are disclosed in
     `14_RIGHTS_READINESS_QUALITY.md`; neither is superseded.
  2. **Any SQL count of "empty sections" is 454, not 453.** The audit's own 453 is the correct
     semantic answer (453 structurally-expected `front/(preamble)` placeholders, plus zero genuinely
     empty body sections); the SQL 454 is a byte-inspection artifact.
  3. **`term_mention` offsets into the affected sections cannot be reproduced through a naive SQL
     `substr()`.** A consumer must read the text in Python (or strip U+0000 before comparing) or the
     NUL-truncation will make valid mentions look unanchored. Component B's 99.9978% exact-offset
     figure was computed in Python and is unaffected.
- **Scope of the correction:** caveat and measurement only. **No rating changes, no count in any
  other report is superseded, and no artefact is modified.** The only text changed in this report is
  the parenthetical marker added to §1 "Semantic quality".
- **Reproducer:** the two commands in the table above, run against the frozen DB read-only
  (`mode=ro`); the Python figures use `con.text_factory = bytes` plus an explicit
  `.decode("utf-8", "replace")` so that a NUL-containing value is measured rather than truncated.

