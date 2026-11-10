# PASS D4 — Terminology chain audit (release 1.0.1 vs CDM 3.0.3)

**Status: COMPLETE — 48 checks, 48 PASS, 0 new genuine DISCREPANCY.**

Scope: `releases/terminology/1.0.1/` (23-file checksummed bundle) cross-checked
against frozen `releases/cdm_v3/3.0.3/microbiome_cdm_v3.db` (all connections
read-only: `file:...?mode=ro&immutable=1` + `PRAGMA query_only=ON`).
No paper text was read; offsets validated against stored section LENGTHs only.
Raw runs: `_work/d4_part1..5.py` → `_work/d4_results_p1..5.tsv`.
SQL documentation: `checks_D4.sql`. All 48 rows appended to `DATA_AUDIT.csv`
(now header + 116 data rows: 12 D0 + 26 D1 + 15 D2 + 15 D3 + 48 D4).

## Headline ties

- **Manifest**: 23 files, all sha256 verified. 1.0.1 = 1.0.0's 22 files +
  `OFFSET_FIX_REPORT.json`.
- **Mentions chain**: rows_written 2,505,736 → extraction manifest
  coverage.mention_records 2,505,736 (identical in 1.0.0 and 1.0.1) → shipped
  jsonl 2,505,735 (delta 1 = the frozen G2 off-by-one; **must not be patched**)
  → DB 2,505,684 (delta 51 = documented load dedup; distinct mention_id sets
  identical at 1,948,059 both sides, symmetric difference 0).
- **Canonical terms**: jsonl 165,991 = live 162,409 + removed 3,582, exact
  tie, containment clean in both directions.
- **Mappings**: jsonl 334,231 − DB 331,394 = **2,837** dropped rows
  (the D1 "demoted mappings" event): 2,784 distinct mapping_ids, relation
  census AMBIGUOUS 1,475 / EXACT_MATCH 881 / RELATED_TO 481, all
  REVIEW_REQUIRED; all 565 affected term_ids still live; reverse diff 0.
  Live DB relation census verified: RELATED_TO 187,832 / AMBIGUOUS 94,563 /
  EXACT_MATCH 37,522 / NO_MATCH_FOUND 11,477 — jsonl minus per-relation delta
  sums to exactly 2,837.
- **Definitions**: jsonl 1,150 = 588 live T3 (`termpipeline_t3_rules_v1`) +
  562 tombstoned; DB `term_definition` holds a further `gap G8` remediation
  lineage (6,185 rows) outside release 1.0.1.
- **OFFSET_FIX_REPORT**: all censuses exact (mentions EXACT 2,348,766 /
  CORRECTED 156,884 / UNANCHORED 85; link LINKED 2,168,760 /
  NO_CANONICAL_TERM 299,854 / LINKED_BY_TYPE 30,049 / AMBIGUOUS 7,072;
  definitions EXACT 1,087 / CORRECTED 63; 75 shifted sections = 67×shift-1 +
  8×shift-2). jsonl−DB per-status deltas sum to exactly 51, non-negative,
  split cleanly (LINKED 43 / NO_CANONICAL_TERM 8). All CORRECTED rows have
  offset_correction>0; no EXACT row does.
- **Validation**: COMPLETE — 453/453 papers, 3,553 VALIDATED + 453
  NOT_APPLICABLE = 4,006 sections, 2,505,650 mentions checked, 100.0% resolved.
- **Calibration v0 quarantine verified**: 390 rows / 14 strata, all
  human_verdict cells empty; draw universe 334,275 > current 334,231 (Δ44);
  QUARANTINE.md tokens all present.
- **PROVENANCE.json**: 8 artifacts hash three-way ties
  (PROVENANCE == MANIFEST.sha256 == recomputed); counts match file rows.

## Superseded rows — retractions and corrections

Ten check IDs from the original raw runs recorded wrong expectations and are
**superseded by corrected rows** (originals preserved in `_work/d4_results_p*.tsv`):

| Original | Correction | Reason |
|---|---|---|
| M01 (22 files) | corrected in-row | AGENTS.md's "22 files" describes 1.0.0; 1.0.1 adds OFFSET_FIX_REPORT.json → 23 |
| T02 | T03R-era fix (row `canonical_terms_live_removed_split_ties_jsonl`) | naive jsonl-vs-live-only row equality ignored the live/removed_* split |
| T03 | row `ontology_mappings_2837_row_delta_fully_characterized` | 2,837-row delta is the documented demotion, not a discrepancy |
| T04 | row `term_definition_id_space_decomposition` | jsonl is the T3 artifact; DB table holds the separate gap-G8 remediation lineage |
| T08 | row `mentions_offsets_verified_recovered_unverified_census` | census closes against rows_written, not shipped jsonl |
| I01 | row `mention_id_sets_identical_symmetric_diff_0` | expected "51 absent ids" was a wrong model of the documented dedup |
| I04 | row `mapping_rows_delta_2837_close_reverse_tie` | the 2,784 absent ids are exactly the demotion's remnant, recensed at X01 |
| C02 | row `mapping_source_census_jsonl_null_spelling` | "none" in the summary is JSON null in the jsonl — spelling only |
| P03 | row `mention_count_chain_deltas_documented` | manifest writes 2,505,736 (not 2,505,735) in both releases; the off-by-one is written-vs-shipped |
| R01 | row `taxonomy_shape_keys_reverified` | original keyed a nonexistent `categories` field; actual schema is `upper_categories`/`subcategories` |

**No new genuine DISCREPANCY was found in D4.** All corrections are
expectation-model fixes on the audit side; every artifact figure ties exactly
once the correct comparison (containment + census + lineage) is used.

## Notes for later passes

- The 2,837-row demotion and the 38,334 auto_accept_eligible / 0 auto_accepted
  figures feed pass **D6** (mappings) — re-verified there, not re-derived.
- The gap-G8 remediation lineage in `term_definition`/`removed_term_definition`
  is the D2 L-1/L-2 family; nothing further to audit in D4.
- G2 off-by-one (2,505,736 written vs 2,505,735 shipped) is frozen in both
  1.0.0 and 1.0.1 and **must not be patched** anywhere.
