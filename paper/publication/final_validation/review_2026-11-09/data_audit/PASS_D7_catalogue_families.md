# PASS D7 — Data-catalogue families (v3.1.1 ↔ frozen DB)

Date: 2026-11-09. Targets: `releases/data_catalogue_v3/3.1.1/` (checksummed
release) vs `releases/cdm_v3/3.0.3/microbiome_cdm_v3.db` (read-only immutable
URI, `PRAGMA query_only=ON`). No paper text read; only id/enum/count columns
and safe censuses (cardinality ≤ 40 / maxlen ≤ 80); prose/evidence columns
never selected.

Result: **18 checks, all PASS, 0 discrepancies.** Every family ties to the
manifest, the jsonl, the DB, and the QA report; the v2→v3 fold account closes
to the row; the 18,502-evidence-row redaction account closes exactly.

## 1. Family row ties (CSV = jsonl = manifest = DB)

| family | release CSV | jsonl | manifest | DB table | DB distinct pk | id-symdiff |
|---|---|---|---|---|---|---|
| datasets | 2,976 | 2,976 | 2,976 | dataset 2,976 | 2,976 | 0 |
| data_assets | 1,992 | 1,992 | 1,992 | data_asset 1,992 | 1,992 | 0 |
| cohorts | 7,085 | 7,085 | 7,085 | cohort 7,085 | 7,085 | 0 |
| samples | 7,530 | 7,530 | 7,530 | sample 7,530 | 7,530 | 0 |
| assays | 8,545 | 8,545 | 8,545 | assay 8,545 | 8,545 | 0 |
| findings | 24,272 | 24,272 | 24,272 | `claim` WHERE claim_source='catalogue_v3_1' 24,272 | 24,272 | 0 |
| papers | 453 | — | 453 | distinct paper_id in section 453 | — | 0 |

Sum 52,400 = manifest `.records`. papers.csv `SUM(sections_total)` 4,006 = DB
`section` rows 4,006. Quote policy KEEP 274 / REDACT 164 / KEEP_NC 15 =
manifest. qa_report verdict PASS, 10/10 checks true.

## 2. The `n_*` basis (initially a mismatch — resolved, NOT a discrepancy)

Raw `SUM(n_*)` over papers.csv is **54,986** ≠ 52,400. Resolution:
`n_*` are **pre-fold v3.0 counts** = map(KEPT+REMOVED+ADDED) per paper —
**0/453 per-paper mismatches** on all seven columns (six families +
`n_records_total`) against `provenance/_v2_to_v3_map.csv`. Provenance
census (60,566 rows): KEPT 52,258 / ADDED 142 / MERGED_INTO 5,460 /
DUPLICATE_OF 120 / REMOVED 2,586. Family tables = KEPT+ADDED = 52,400
exactly. CLEAN_REPORT corroborates 1:1: input 60,424 (= 60,566 − 142 ADDED),
output 54,986, A11_records_merged 5,460, A1_exact_duplicates_folded 120,
A8_bioproject_datasets_added 142, and `after.per_entity` per family equals
papers.csv `n_*` sums (3,064/2,041/7,451/8,461/9,292/24,677). QE note: the
142 ADDED are all datasets (`HMDATA_BP_*`, one per paper, BioProject-derived,
per clean step A8).

## 3. Redaction account (18,502) — closes exactly

`evidence_redacted='LICENCE'` totals **18,502** (assays 3,326 / cohorts 2,580 /
data_assets 478 / datasets 928 / samples 2,739 / findings 8,451) = manifest
`evidence_rows_redacted`. Crosstab policy×flag: REDACT papers carry 18,502
LICENCE + 80 unflagged; KEEP 32,168 + KEEP_NC 1,650 unflagged; total 52,400.
The 80 unflagged REDACT-paper rows are all `evidence_match=NO_QUOTE` (63 ADDED
datasets, 17 KEPT findings) — no evidence text exists to redact. No KEEP or
KEEP_NC paper has any redacted row.

## 4. `_removed.jsonl` ledger (name overstates contents — characterization)

8,166 rows = REMOVED 2,586 + MERGED_INTO 5,460 + DUPLICATE_OF 120 (census via
`fields.v3_status`); `(entity_type, id)` set symmetric difference vs the map's
non-KEPT/non-ADDED pairs = **0**. It is the full removed-or-folded ledger.

## 5. Safe censuses (recorded for D10 trust flags)

DB side: `review_status` UNVERIFIED everywhere (52,400 total family rows);
`v3_status` KEPT except dataset ADDED 142. Claim(catalogue_v3_1)
`evidence_anchor_status`: WHITESPACE 15,057 / EXACT 3,510 / NORMALISED 2,139 /
RELOCATED 1,290 / FUZZY 1,670 / UNANCHORED 560 / NO_EVIDENCE 46;
`evidence_verified`: claim-v3_1 0:746 / 1:23,526; family totals verified=0:
datasets 358, data_assets 76, cohorts 589, samples 398, assays 415, findings
746 — consumed in D10. CSV-side `v3_status` censuses equal DB-side.

## 6. Integrity extras

* **Manifest sha256**: all 44 listed files verify (hash + bytes); only
  MANIFEST.json / MANIFEST.sha256 themselves unlisted (self-excluding).
* **NUL artifact**: exactly 1 NUL byte, in `taxon_or_feature` of
  `HMFINDING_024394` (HMPAPER_000446) — the documented NUL-paper artifact.
  **Exact failing command**: the first read used plain `csv.DictReader` on
  `tables/findings.csv` and died `_csv.Error: line contains NUL`; all reads
  use a NUL-stripped byte reader (strip U+0000, then decode) — row count
  24,272 unaffected.
* **Basis note (not a discrepancy)**: `is_primary_finding` and
  `evidence_located_pct` differ between CLEAN_REPORT (v3.0 basis, 54,986
  records) and qa_report (v3.1 basis, 52,400) — documented pipeline-stage
  difference; both internally consistent.

## Checks

See `checks_D7.sql` (DB side; immutable URI + `PRAGMA query_only=ON`).
CSV/jsonl side computed in python (NUL-stripped reader); commands preserved
in the audit transcript. Exact failing commands: one (the NUL read, above).
