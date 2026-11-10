# PASS D10 — Trust flags & transparency markers (final pass)

Date: 2026-11-09. Target: `releases/cdm_v3/3.0.3/microbiome_cdm_v3.db` (read-only,
`mode=ro&immutable=1` + `PRAGMA query_only=ON`) + `releases/terminology/1.0.1/` +
repo documentation pointers. No paper text read (enum/count/flag columns only).
Result: **13 checks — 12 PASS, 1 DISCREPANCY** (a number in my own D3 report, not
in the frozen data; corrected here).

## 1. SENTENCE_CLIPPED 358,150 — confirmed in-DB (ties the documentation)

`term_mention.unresolved_flags` (JSON-encoded): total 2,505,684 rows; `'[]'`
2,146,364; LIKE `%SENTENCE_CLIPPED%` **358,150** — exactly the documented count
(`docs/reports/terminology_catalogue_audit/terminology_catalogue_audit.json`:
`"SENTENCE_CLIPPED": 358150`; reconciliation: "offsets still resolve within the
section"). Of these, 357,755 are exactly `["SENTENCE_CLIPPED"]` and 395 carry it
combined with `CONTROL_CHAR_SURFACE` (flag total 1,497). The CDM column dictionary
(`remediation/dictionary_302/CDM_COLUMN_DICTIONARY.csv`, term_mention row 25)
documents the flag vocabulary and stamps the column `NEEDS_EXPERT_REVIEW`.
Per the reconciliation report, clipped-sentence rows keep resolving offsets —
flagged transparency, not corruption.

## 2. The "129-claim-row" pointer — resolved (report-level DISCREPANCY, D3 line 50)

The frozen session plan cited "the 129-claim-row … AGENTS.md carries". Tracing it:
the only in-repo "129"+"claim" association is **`PASS_D3_mentions_entities.md` line
50**: "129 UNANCHORED+FUZZY+NORMALISED rows verified=1, offset-bearing". That number
is **not reproducible**. Exact re-measurement:

* claim catalogue_v3_1, anchor IN (UNANCHORED, FUZZY, NORMALISED) AND verified=1:
  **3,669** (UNANCHORED 55 + FUZZY 1,496 + NORMALISED 2,118). With non-null char+span
  offsets: 3,614. UNANCHORED&verified=1 alone: 55. No cross-tab cell equals 129 under
  any predicate tried (anchor×verified claim + family tables; anchor×evidence_match:
  the only 129 cell anywhere is `FUZZY`×`FUZZY_0.98` = 129 and `assay`/FUZZY/v0 = 129
  — coincidental, different quantities).
* The verified=0 decomposition in the same D3 line **does tie exactly**:
  505 UNANCHORED + 174 FUZZY + 46 NO_EVIDENCE + 21 NORMALISED = 746 = all
  catalogue rows with NULL char offsets.

Verdict: the data is internally consistent; the D3 prose figure "129" is a
reporting error (correct value 3,669). Corrected in the D10 CSV row; D3's data
checks otherwise stand.

## 3. Anchor-status censuses — tie all prior pointers

* claim (catalogue_v3_1): WHITESPACE 15,057 / EXACT 3,510 / NORMALISED 2,139 /
  FUZZY 1,670 / RELOCATED 1,290 / **UNANCHORED 560 / NO_EVIDENCE 46** (sum 24,272).
  The UNANCHORED/FUZZY/NORMALISED/NO_EVIDENCE quartet ties the documented figures
  and D3/D7 exactly. stage52 claims: NULL by design (21,395).
* relation_evidence: WHITESPACE 24,702 / EXACT 5,375 / NORMALISED 2,115 = **32,192
  anchored; UNANCHORED 2,224** — ties the D5 re-anchor census exactly.
* No cross-table contradictions: claim ↔ claim_evidence are 1:1 on
  (finding_id, claim_source) over all 45,667 rows with **0 disagreements** on
  anchor_status, locator_status, and all four offset columns.
* claim_evidence locator_status (stage52): verified_normalized 16,602 /
  unresolved_not_in_source 2,788 / verified_exact 2,005 (sum 21,395) — ties
  checks_D3.sql §3f. Catalogue rows carry NULL locator (24,272) by convention.

## 4. evidence_verified & review_status — the honesty ledger is complete

* `evidence_verified=0`: dataset 358 / data_asset 76 / cohort 589 / sample 398 /
  assay 415 (family sum 1,836) + claim catalogue 746 = **2,582 unverified rows carry
  the flag**; verified=1: 26,618+1,916+6,496+7,132+8,130 + 23,526.
* `review_status`: **all UNVERIFIED — 52,400 rows** (family 28,128 + catalogue
  claims 24,272), tying the documented "all-UNVERIFIED 52,400" pointer exactly;
  stage52 claims are `pending` 21,395 (ties `data/corpus/annotations/findings.csv`).
* NO_EVIDENCE cells exist and are preserved: claim 46, dataset 142, assay 2.

## 5. Internal status tables agree with live counts (one expected snapshot delta)

* `validation_result`: 8 aggregate checks all `passed=1` (corpus_453, primary_keys,
  counts_plausible, links_resolve, direction_vocab, vocab_labels, no_placeholders,
  csv_matches_jsonl, v2_traceable, accessions_valid) + per_paper_validation 453 rows.
* `evaluation_run`: 3 disclosed runs, all LLM-as-judge and labeled as such
  (Gemma 4 E4B on v2/terminology; Claude Opus 5.5 400-record sample on v3.0.0;
  Gemma 4 E4B full census on v3.1).
* `load_audit` (36 tables) and `cdm_entity_status` (33 entities): kept == live for
  **every table except `extraction_run`** (recorded 28 vs live 45). Documented growth:
  `cdm_change_log` step **R1 INSERT_ROWS rows_affected=17** → 28 + 17 = 45. The
  two status tables snapshot at 3.0.2 load time; the delta is the R1 remediation
  inserts. Characterization, not a mismatch.
* Terminology 1.0.1 carries its calibration honesty markers:
  `mapping_projection_summary.json` → `calibration.status = NOT_CALIBRATED`;
  `PROVENANCE.json` → `"auto_accepted = 0; calibration = NOT_CALIBRATED."`
  (ties D6).

## Checks

See `checks_D10.sql`. Throughout: no paper-text columns selected; anchor/flag/
status enums and counts only.
