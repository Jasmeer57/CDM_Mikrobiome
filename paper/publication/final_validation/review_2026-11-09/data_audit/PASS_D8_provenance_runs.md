# PASS D8 — Provenance & the 45-run account (CDM 3.0.3)

Date: 2026-11-09. Target: `releases/cdm_v3/3.0.3/` — frozen DB (read-only
immutable URI, `PRAGMA query_only=ON`) plus the release bundle
(`MANIFEST.sha256`, `REVERT_303.sql`, `remediation/`). No paper text read;
only id/enum/hash/count columns censused (`safe_census` guard: cardinality
≤ 40, maxlen ≤ 80; `provenance_evidence`, `revert_sql`, `description` and
other prose columns never selected whole except where length-bounded and
clearly provenance metadata, never paper-derived text).

Result: **16 checks, all PASS; 1 re-confirmed D2 discrepancy (L-1); 0 new
discrepancies.** `REVERT_303.sql` was audited **parse-only** — never executed
(per frozen-release rule).

## 1. run_metadata (11 keys) — internal ties

| key | value (or prefix) | tie |
|---|---|---|
| cdm_version | 3.0.3 | matches release dir |
| derived_from | `releases/cdm_v3/3.0.2 (sha256 1ddfcee2e90c…)` | **matches 3.0.2 on-disk DB sha256 exactly** |
| migration / migrated_at | `src/scripts/cdm_remediation/migrate_303.py` / 2026-11-02T02:12:44 | consistent with REVERT/PROMOTE |
| promoted_from / promoted_at | `outputs/results/cdm_v3_3.0.3_rc1 (3.0.3-rc1)` / 2026-11-02T08:04:46 | matches PROMOTION.txt timestamp to the second |
| built_at | 2026-10-31T12:19:10 | inherited from the 3.0.2 build (dir mtime 12:19) |
| papers / catalogue / terminology / template | 453 / `outputs/results/catalogue_v3_1` / `releases/terminology/1.0.1` / `src/template/cdm 0.1.0` | match the D0-D7 targets |

## 2. extraction_run (45 rows)

Verification census: **VERIFIED_LOG 29 / VERIFIED_CODE_AND_HASH 5 /
VERIFIED_RUN_EVENT 4 / RECORDED_IN_DATA 3 / AS_IN_3.0.2_UNVERIFIED 4.**
The 4 unverified runs are named exactly: `28619916` (terminology 1.0.0 build),
`CATNER_20261030T092214_1923898`, `CATLINK_v2`, `CATCLEAN_v3` — consistent with
the D5/D7 account of catalogue lineage being carried by the release suite
rather than per-run event logs. 35/45 runs have `completed_at` NULL (gap eps
record completion via `stage_corrected`/logs instead). `stage_corrected`
populated for exactly the 4 G6/G7/G8/G9 apply rows, matching cdm_change_log's
apply steps.

## 3. Source-artifact hashes — all 6 tie on disk

| run | artifact | on-disk sha256 |
|---|---|---|
| cpu_ensemble_v1 | `releases/zenodo_v1/ner_453_sections/all_ner_sections_combined.csv` | MATCH (e682e224…) |
| qwen_ollama_cell7c_v1 | `releases/zenodo_v1/qwen_sections_ner/qwen_sections_ner.csv` | MATCH (c8dfeda2…) |
| qwen35_vllm_body_v1 | `outputs/results/llm_ner_body/vllm_sections_ner.csv` | MATCH (78323cc9…) |
| mesh_gazetteer_2026 | `outputs/results/mesh_ner/mesh_ner_terms.csv` | MATCH (15849f2b…) |
| termpipeline_t3_rules_v1 | `releases/terminology/1.0.0/term_definitions.jsonl` | MATCH (05e12495…) |
| mapping_guards_v2 | `releases/frozen_output/02_data_catalogue/terminology/mapping_guards_v2` | sha equals member file `mapping_remapped.jsonl` |

Only the 5 `VERIFIED_CODE_AND_HASH` runs carry hashes; the mapping_guards_v2
row (RECORDED_IN_DATA) records the directory path but hashes its
`mapping_remapped.jsonl` member — ambiguous labeling, not a mismatch; noted
as characterization.

## 4. REVERT_303.sql (parse-only, never executed)

56 statements parsed against the actual 3.0.3 schema: every DROP TABLE
(`cdm_change_log`, `identifier_crosswalk`, `relation_evidence`), every DROP
INDEX (11 × `ux303_*`), and every `ALTER TABLE … DROP COLUMN` (11 columns
across claim/data_asset/dataset/assay/sample/cohort/taxonomy_annotation/
term_definition/quantitative_result/section) targets an object/column that
**exists in 3.0.3**. 0 problems; 0 unparseable statements. The DELETE/UPDATE
statements against `run_metadata` reference keys that exist. Reversibility is
additionally corroborated inside the DB: **all 79 `cdm_change_log` rows carry
non-empty `revert_sql`** (steps R1-R8 + PROMOTE; kinds ADD_COLUMN 39 /
FILL_NEW_COLUMN 24 / CREATE_UNIQUE_INDEX 9 / CREATE_TABLE 2 / UPDATE_VALUE 2 /
CREATE_INDEX 1 / CHECK 1 / INSERT_ROWS 1; `rows_affected` sum 3,887,671).

## 5. Run anchoring — zero dangling references

Every `extraction_run_id`-bearing column in the DB resolves into
`extraction_run` (45 rows): dataset (2 runs: CATNER 2,834 + CATCLEAN 142 = 2,976),
assay/cohort/sample/data_asset (CATNER only), claim (CATNER 24,272 + 21,395
NULL), and relation_evidence (34,416 rows → `stage53_triples_extract@2.1.0`).
The NULL `claim.extraction_run_id` rows (21,395 stage52) all carry
`extraction_run_id_recovered = 'stage52_findings_extract-20261023T192306-2928671'`,
which IS in the run table (VERIFIED_RUN_EVENT) — ties the settled D5 finding
count exactly.

**Re-confirmed (D2 L-1, no new finding):** `processing_lineage` (5 rows) has 2
dangling `child_id` values (`gap G1`, `gap G9`) — stage labels, not run ids;
the other 5 endpoints (28619916, CATNER…, CATCLEAN_v3, CATLINK_v2, gap G8)
anchor.

## 6. Release bundle integrity

* `sha256sum -c MANIFEST.sha256`: **all files OK, 0 failures** (includes the
  frozen DB 5d23ba87… recorded in D0).
* `remediation/VERIFICATION_303.json`: overall `pass: true`; preservation
  41→44 tables (39 identical + 2 additive, 3 new: cdm_change_log,
  identifier_crosswalk, relation_evidence), 0 violations; reversibility
  indexes_equal; release_qa PASS on both 3.0.2 and rc, 10 warnings unchanged;
  REG1 2,505,684 vs release 2,505,735 (Δ51 documented, matches G2 history);
  REG2 52,020/0 mismatched; REG3 canonical-link statuses sum consistent;
  REG4 offsets exact 2,505,628 / mismatch 0 / no_section_or_offset 56;
  regressions empty. registry validation PASS 115 / FAIL 5 (current) and
  PASS 118 / FAIL 2 (proposed) — the 5 current failures are
  registry-vs-release population-status mismatches (B2 BODY_SITE/INTERVENTION/
  RELATION + 2 more), **design-proposal-level failures, quoted in the bundle
  itself, not data-integrity defects**.
* `identifier_crosswalk` (4 rows): documents that `term_mention.mention_id`
  and `term_concept_map.mapping_id` are **not unique** in this build
  (original_id_unique=0) with the recovered row-key definitions — matches
  D2's L-2 finding; `relation.canonical_triple_id` unique; `claim.finding_id`
  unique within each claim_source (matches D5 24,272+21,395 account).

## 7. Characterization notes (recorded, not discrepancies)

* `extraction_run.completed_at` mixes formats (ISO `…Z` for 4 corpus runs;
  shell-date strings like `Fri Oct 30 11:02:57 PM CET 2026` for 6 gap/apply
  runs; plain ISO for 1) — inconsistent presentation of an internal column.
* `verification = RECORDED_IN_DATA` (3 runs) means provenance is asserted by
  in-data labels rather than external logs — a weaker tier, correctly labeled.

## Checks

See `checks_D8.sql`. Parse-only REVERT check re-implemented there as
commented procedure (python parse, `sqlite_master`/`PRAGMA table_info` as the
schema authority). All hashes verified with `sha256sum` / hashlib.
