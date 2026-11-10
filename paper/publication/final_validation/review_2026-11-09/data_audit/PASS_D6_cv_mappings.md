# PASS D6 — Controlled-Vocabulary Mappings (re-verification)

Date: 2026-11-09
Targets: `releases/terminology/1.0.1/` (frozen, checksummed) vs
`releases/cdm_v3/3.0.3/microbiome_cdm_v3.db` (read-only immutable URI,
`PRAGMA query_only=ON`). Scratch facts: `_work/` (probe transcripts; all
numbers re-derivable from `checks_D6.sql`).

## Scope

Re-verify — not re-derive — the mapping-side facts settled in D4, now at
**row level** (D4 proved them on distinct mapping_ids; D6 adds the
row-denominator accounting). No paper text read; only enum/id/count columns
censused (`safe_census` guard: cardinality ≤ 40, maxlen ≤ 80; `term`,
`match_scores`, `mapping_provenance`, and other long columns never selected).

Result: **12 checks, all PASS, 0 new discrepancies.** Every D4 mapping fact
reproduces exactly, and the row-level accounting closes the 2,837-row
demotion to the row.

## 1. The demotion tie (row level)

| quantity | value |
|---|---|
| `term_ontology_mappings.jsonl` rows | 334,231 (matches `mapping_projection_summary.counts.rows` 334,231) |
| DB `term_concept_map` rows | 331,394 |
| demoted rows (jsonl mapping_id absent from DB) | **2,837** = 334,231 − 331,394 |
| demoted-row `mapping_relation` census | AMBIGUOUS 1,475 / EXACT_MATCH 881 / RELATED_TO 481 |
| demoted-row `review_status` | REVIEW_REQUIRED 2,837 (all) |
| demoted-row `auto_accept_eligible` | False 1,965 / True 872 |
| jsonl distinct mapping_id | 318,605 |
| DB distinct mapping_id | 315,821 |
| jsonl-only mapping_ids | **2,784** (matching D4); DB-only mapping_ids **0** |

* **Accounting closes twice**: at row level 334,231 − 2,837 = 331,394, and
  per-relation — the 322,754 retained rows split AMBIGUOUS 94,563 /
  EXACT_MATCH 37,522 / RELATED_TO 187,832 / NO_MATCH_FOUND 11,477, which is
  exactly the DB `mapping_relation` census (jsonl-retained rows join-equal
  the DB census: True). Denominator note: D4's 1,475/881/481 census was over
  *distinct jsonl-only ids* (2,784); D6's identical-looking census is over
  *rows* (2,837) — 53 demoted rows share mapping_ids across relations. Both
  are correct on their own denominator (see CSV rows).
* All 2,837 demoted rows were REVIEW_REQUIRED — the demotion touched only
  rows awaiting human review; no AUTO row and no UNRESOLVED row was dropped.
* **NOT a discrepancy** (settled in D4, re-observed): the DB is a projected
  subset of the release jsonl; the release remains the artifact of record at
  334,231 mapping rows; the DB carries the guard-reviewed live projection.

## 2. Acceptance / rejection state (DB) — closed characterizations

| quantity | value |
|---|---|
| `mapping_disposition_reviewed='ACCEPTED'` | 18,272 (D4: 18,272) |
| `guard_status='rejected_guard'` | 16,622 (D4: 16,622) |
| `auto_accept_eligible` in jsonl | 38,334 (summary `counts.auto_accept_eligible` 38,334) |
| `auto_accepted` | **0** (summary `counts.auto_accepted` 0; calibration `NOT_CALIBRATED`, reason "no calibration file supplied") |
| jsonl `(disposition, eligible)` crosstab | REVIEW_REQUIRED+False 284,420 / UNRESOLVED+False 11,477 / REVIEW_REQUIRED+True 38,334 (sum 334,231) |

New D6 tie: DB `REJECTED` 30,693 decomposes as `rejected_guard` 16,622 +
`kept`-then-rejected 14,071, and `relation_llm_g9='WRONG'` counts **exactly
14,071** — the G9 LLM-mapper's WRONG verdict is the (and the only) rejection
path for kept rows. `guard_rejection_reason` (free-text) was not selected.
* **Accepted rows are dual-verified**: all 18,272 ACCEPTED rows carry both
  `relation_llm_g9` AND `relation_deepseek` non-null (18,272/18,272; 0
  accepted rows with g9 NULL). Acceptance required both LLM relations.

`mapping_disposition` × `mapping_disposition_reviewed` crosstab (all 8 cells,
non-zero only): REVIEW_REQUIRED/None 244,855; REVIEW_REQUIRED/REVIEW_REQUIRED
25,515; REVIEW_REQUIRED/ACCEPTED 18,272; REJECTED/None 16,622;
REJECTED/REVIEW_REQUIRED 10,990; UNRESOLVED/None 10,680; REJECTED/REMOVED
3,081; REVIEW_REQUIRED/REMOVED 1,379. Sum 331,394. ✓

## 3. Frozen summary reconciliation (artifact vs artifact)

* `mapping_projection_summary.json`: rows 334,231 / rows_with_concept_id
  322,754 / terms_with_any_candidate 65,293 / no_match_found terms 11,477 /
  lookup_failed 0 / eligible 38,334 / accepted 0 — all re-observed.
* `terminology_extraction_manifest.json` `coverage.mapping_rows` 334,231,
  `auto_accepted_mappings` 0, `overall_status` COMPLETE, 9/9 artifacts. ✓
* `mapping_id_status` (DB): '' 312,314 / MISSING 11,477 (= NO_MATCH_FOUND
  rows) / SHARED 7,603. ✓ internally consistent.
* `review_status` (DB): REVIEW_REQUIRED 319,917 / UNRESOLVED 11,477;
  `relation_deepseek` suppressed (d=110, maxlen 83 — exceeds guard), not
  censused, per hygiene rule.
* **G2 off-by-one remains frozen/unpatched** (D4/G2): rows_written 2,505,736
  vs manifest 2,505,736 vs jsonl 2,505,735 (Δ1). Not re-litigated here.

## 4. Settled D4 facts consumed unchanged

2,837-row demotion characterization; 38,334 eligible / 0 auto-accepted;
`NOT_CALIBRATED` thresholds (no verdict promotion without a filled sheet);
T5b quarantine (390 rows, mandatory redraw — D4 §QUARANTINE); G2 Δ1.

## Checks

See `checks_D6.sql`. All runnable read-only from repo root with the immutable
URI. Exact failing commands: none — every check tied.
