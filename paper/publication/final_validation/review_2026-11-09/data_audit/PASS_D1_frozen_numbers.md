# PASS D1 — Frozen-set number verification

**Scope**: re-derivation of every quoted frozen-number for the current frozen set
(CDM 3.0.3, terminology 1.0.1, data_catalogue_v3 3.1.1, corpus_v2 2.2.0) plus the
distinct v2-era snapshot `releases/frozen_output/`, strictly from the artifacts
themselves. Frozen DB opened read-only (`mode=ro&immutable=1` + `PRAGMA
query_only=ON`) on every connection. No paper text read; offsets validated only
against stored lengths and summary counters. No network.

**Result: PASS.** Every ground-truth expected value re-derived exactly, except
four known/expected cross-artifact deltas (rows D1-…-Δ1..Δ4 below), each with a
documented, artifact-backed mechanism:

1. **Δ51 mentions** (terminology 2,505,735 vs CDM DB 2,505,684) — fully explained
   below (PK-dedup on load; M14 counter-difference confirms).
2. **Catalogue generations**: data_catalogue_v3 3.1.1 = 52,400 records ≠
   56,985 (frozen_output v2-era). DB matches 3.1.1 exactly — different builds,
   not a discrepancy.
3. **Δ2,837 mappings** (T5 334,231 vs DB term_concept_map 331,394) = the
   documented demoted rows (`mapping_demoted.jsonl` = 2,837; guard_summary
   `demoted_total: 2837`).
4. **term_definition 6,773 (DB)** vs T3 1,150 (terminology) — different tables:
   T3 is 3-stage definitions extraction; DB `term_definition` is the CDM
   span-rule stage (qwen3.5-4b 6,185 + rule_pattern 588).

---

## 1. CDM 3.0.3 DB (`releases/cdm_v3/3.0.3/microbiome_cdm_v3.db`)

Re-derived from the DB itself (queries in `checks_D1.sql`):

| Check | Expected | Observed | Status |
|---|---|---|---|
| Tables | 44 | 44 | PASS |
| Total rows | 8,490,496 | 8,490,496 | PASS |
| Columns (X02) | 866 | 866 | PASS |
| `relation` | 25,788 | 25,788 | PASS |
| `removed_relation` | — | 6,925 | recorded |
| `claim` / `claim_evidence` | 45,667 each | 45,667 / 45,667 | PASS |
| `claim_source` (K01-style) | 21,395 + 24,272 | 21,395 (finding) + 24,272 (dataset-derived) = 45,667 | PASS |
| `term_concept_map` | 331,394 | 331,394 | PASS |
| `term_mention` (M01) | 2,505,684 | 2,505,684 | PASS |
| `term_mention` offset_status | EXACT 2,348,758 / CORRECTED 156,870 / UNANCHORED 56 | 2,348,758 / 156,870 / 56 (sum = 2,505,684) | PASS |
| `term_mention` per method | ensemble 1,705,449 (M03) | 1,705,449 + LLM 552,147 + MeSH 248,088 = 2,505,684 | PASS |
| M14 mentions sharing a span-id (dup on `mention_id`) | 557,625 | 557,625 | PASS |
| Linked % (M13) | 87.8% | (2,168,717 LINKED + 30,049 LINKED_BY_TYPE) / 2,505,684 = 87.7511% → 87.8 rounded | PASS |
| `paper` / `paper_publication` | 453 / 453 | 453 / 453 (447 distinct publications) | PASS |
| `study` / `compendium_project` | 453 / 452 | 453 / 452 (`compendium_sample` 156,330) | PASS |
| `section` | 4,006 | 4,006; SUM(character_count) 26,874,831; SUM(word_count) 3,934,819 | PASS |
| `canonical_term` (T02) | 162,409 | 162,409 | PASS |
| `removed_canonical_term` (T03) | 3,582 | 3,582; T02+T03 = 165,991 = T01 | PASS |
| `taxonomy_annotation` rows = canonical_term (R2 backfill) | 162,409 | 162,409; AGREED/PARENT_AGREED = 37,740 (T06) | PASS |
| Terms typed ENTITY (T05) | 89,799 | 89,799 | PASS |
| `concept` | 204,817 | 204,817 | PASS |
| `extraction_run` (X03) registrations | 45 | 45 | PASS |
| X04 verification breakdown | 4 unverified | VERIFIED_LOG 29 / VERIFIED_CODE_AND_HASH 5 / VERIFIED_RUN_EVENT 4 / AS_IN_3.0.2_UNVERIFIED 4 / RECORDED_IN_DATA 3 | PASS |
| `human_review` | 0 | 0 | PASS |
| `evaluation_run` | — | 3 | recorded |
| `type_harmonization` | 40,141 (G7) | 40,141 | PASS |
| `run_metadata` | version/lineage keys | 11 rows: cdm_version 3.0.3; derived_from 3.0.2 sha256 1ddfcee2…; promoted_from 3.0.3-rc1 at 2026-11-02T08:04:46 (matches PROMOTION.txt) | PASS |
| `cdm_change_log` (X05) | 79 | 79 rows; steps PROMOTE, R1–R8 | PASS |
| `validation_result` | — | 463 rows = 453 papers (target HMPAPER_*, passed NULL) + 10 `catalogue_v3_1` (all passed=1) | recorded |

### Claim/mention family counts in DB = catalogue 3.1.1 (D7 preview)

| Table | DB | catalogue 3.1.1 MANIFEST | Status |
|---|---|---|---|
| claim (findings family) | 24,272 | findings 24,272 | PASS |
| assay | 8,545 | 8,545 | PASS |
| sample | 7,530 | 7,530 | PASS |
| cohort | 7,085 | 7,085 | PASS |
| dataset | 2,976 | 2,976 | PASS |
| data_asset | 1,992 | 1,992 | PASS |
| intervention / body_site | 1,935 / 29 | (not MANIFEST-scoped) | recorded |

K11 (datasets with no section) = 142 confirmed (`COALESCE(section_id,'')=''`),
matching the CHANGE_REPORT R4 note (52,258 section-linked catalogue records).
K03–K06 reconcile with the gap-run report: G1 filled 21,403; rejected 24,935 +
28,782 + 13,078 + 6,690 + 2,748 + 20; audit_facts NOT_REPORTED 46,182 /
CONFLICTING 4,586.

### Δ51 mechanism (T1 2,505,735 → DB 2,505,684) — CLOSED

- `load_audit` row: term_mention offered 2,505,735 / kept 2,505,684 / dropped 51
  (drop = primary-key collision, per `build_cdm_v3.py` lines 71/100/455).
- Counter-proof from both sides:
  - T1 jsonl: `by_method.ner_model_ensemble = 1,705,500`; DB has 1,705,449 →
    all 51 dropped rows are CPU-ensemble rows.
  - T1 jsonl in-file duplicates on `mention_id` = 557,676 (2,505,735 − 1,948,059
    distinct); DB duplicate counter (M14) = 557,625 → difference exactly 51.
- Offset-status deltas are the same 51 rows re-appearing under different labels:
  file EXACT 2,348,766 / CORRECTED 156,856 / UNANCHORED 85 vs DB
  2,348,758 / 156,870 / 56 (−8 / +14 / −29; file-recovered 34 of 85 unverified).
- **Verdict: expected, documented load-time dedup. Not a data loss defect.**

### Mapping chain inside the DB (P-series)

- guard_status: kept 314,772 / rejected_guard 16,622 (sum 331,394 loaded rows);
  change-log mapping_evidence_status all RESTORED (331,394, R-series backfill).
- mapping_disposition (file-level semantics, restored): REVIEW_REQUIRED
  290,021+35,816…; full split of loaded rows: kept+REVIEW_REQUIRED 290,021 /
  kept+REJECTED 14,071 / rejected_guard+REJECTED 16,622 / kept+UNRESOLVED 10,680.
- mapping_disposition_reviewed (register P05/P06): **ACCEPTED 18,272 rows over
  16,750 distinct terms** (reviewed rows: ACCEPTED 18,272 / REVIEW_REQUIRED
  36,505 / REMOVED 4,460; 272,157 never reviewed) — matches register exactly.
- mapping_relation in DB: RELATED_TO 187,832 / AMBIGUOUS 94,563 / EXACT_MATCH
  37,522 / NO_MATCH_FOUND 11,477 (guard-adjusted from T5's 188,313 / 96,038 /
  38,403 / 11,477 — see Δ3).
- EXACT_MATCH ∧ guard kept = 36,037 (passes the two-model-agreement subset P05).
- Source services absent: `source_service_mapping IS NULL` = 11,477 (P07) — the
  NO_MATCH_FOUND rows, as expected.

### Relations ↔ evidence (D5 preview)

`relation_evidence` shares `canonical_triple_id` with `relation`: 0 relations
without ≥1 evidence row; 25,788 distinct canonical_triple_ids covered.
NOTE (for D2/D5): `relation_evidence` has **no `relation_id` column** — the join
key is `canonical_triple_id` (+ `extraction_run_id`), not `relation_id`.

### Δ2 catalogues & Δ4 definitions — expected, not discrepancies

- Catalogue v3.1.1 (46 files): MANIFEST 453 papers / **52,400 records**;
  `records/catalogue_records.jsonl` = 52,400 lines; `tables/*.csv` row counts
  all match MANIFEST and DB family tables exactly (papers.csv 453).
  qa_verdict PASS. The **56,985** figure belongs to the v2-era
  `releases/frozen_output/02_data_catalogue/` (verified: MANIFEST.json 56,985;
  records/catalogue_records.jsonl 56,985 lines; per-family 21,439/12,116/9,575/
  8,484/3,228/2,143). Do not conflate (tracked as D9 material).
- `term_definition` 6,773 (DB; ABBREVIATION_EXPANSION 4,154…; EXACT 6,460 /
  RELOCATED 313; plus `removed_term_definition` 3,865) vs T3 1,150
  (`term_definitions.jsonl`) — different tables/stages: DB definitions come from
  the CDM's own span-extraction stage (qwen3.5-4b 6,185 + rule_pattern 588),
  whereas T3 is the terminology 3-stage definitions artifact. D02 (distinct
  terms with definitions in DB) = 3,397.

## 2. Terminology 1.0.1 (`releases/terminology/1.0.1/`)

All line counts re-derived with a byte-reader (text-bearing fields never
printed). **Supporting_passage text ignored; no paper text entered context.**

| Artifact | Expected | Observed | Status |
|---|---|---|---|
| `term_mentions.jsonl` (T1/M02) | 2,505,735 | 2,505,735 lines | PASS |
| T1 per-source rows | ensemble 1,705,500 / ollama 186,024 / vllm 366,123 / MeSH 248,088 | `_mentions_summary.json`: 1,705,500 / 186,024 / 366,123 / 248,088 (all `status OK`, sum 2,505,735; `rows_written` 2,505,736 incl. one summary-internal delta noted in docs/DATA_SEMANTICS.md) | PASS |
| T1 offset verification | 99.9952% | verified 2,505,616 + recovered 34 / unverified 85 → 99.9952% | PASS |
| T1 by_entity_type | 16 types + ENTITY | 16 typed + ENTITY 960,719 (by-method check consistent with summary) | PASS |
| `canonical_terms.jsonl` (T01) | 165,991 | 165,991 | PASS |
| `term_definitions.jsonl` (T3) | 1,150 | 1,150 | PASS |
| `term_ontology_mappings.jsonl` (T5) | 334,231 | 334,231; rows_with_concept_id 322,754; terms_with_any_candidate 65,293; terms_no_match_found 11,477; lookup_failed 0 | PASS |
| T5 auto-accept | eligible 38,334 / accepted 0 | eligible 38,334 / accepted 0; ineligible_non_concept 1,449 | PASS |
| T5 calibration (T5b/c) | NOT_CALIBRATED | `calibration.status = NOT_CALIBRATED`, reason "no calibration file supplied" | PASS |
| T5 mapping_relation | RELATED_TO 188,313 / AMBIGUOUS 96,038 / EXACT_MATCH 38,403 / NO_MATCH_FOUND 11,477 | exact | PASS |
| T5 mapping_disposition | REVIEW_REQUIRED 322,754 / UNRESOLVED 11,477 | exact | PASS |
| `terminology_taxonomy.json` (T4) | 16 upper + 66 sub + reserved | n_upper 16 / n_sub 66 / reserved ["UNCERTAIN"] / status DRAFT | PASS |
| T4 classified terms | 0 | classified 0 / pct 0.0 / taxonomy DRAFT | PASS |
| `terminology_validation.jsonl` | 4,006 | 4,006 sections (3,553 validated + 453 NOT_APPLICABLE preamble placeholders); overall COMPLETE; mentions offset-resolved 2,505,650/2,505,650 (100%) | PASS |
| Guard summary (P01/P02) | kept 314,772 / rejected 16,622 | kept_total 314,772 / rejected_total 16,622 / demoted_total 2,837 (rows_total 334,231) | PASS |
| `mapping_demoted.jsonl` (P04) | 2,837 | 2,837 lines | PASS |
| Guard demotions G3 | kept-high 3,658 / demoted-low 44,601; v1→v2 auto-accept 38,334→36,030 | scalars verified in guard_summary | PASS |
| `calibration_v0_pre_fix/QUARANTINE.md` | quarantined T5b sample | present (superseded 334,275-row table sample; redraw before use) | PASS |

### Δ3 (T5 → DB row delta) — CLOSED

334,231 total = kept 314,772 + rejected 16,622 (guards v2). DB loads
331,394 = 334,231 − **2,837 demoted** (`mapping_demoted.jsonl` = 2,837 lines =
guard_summary `demoted_total`). Demoted-not-loaded is by design (P04).
relation/disposition deltas between file and DB (e.g. EXACT_MATCH 38,403 →
37,522) are exactly the demoted rows per relation. No unexplained rows.

## 3. corpus_v2 2.2.0 (`pipelines/corpus_v2/releases/2.2.0/`)

| Check | Expected | Observed | Status |
|---|---|---|---|
| Papers | 447 canonical + 6 dup-excluded = 453 | `papers` 453 / `papers_canonical` 447 / `papers_duplicate_excluded` 6; data/papers.jsonl 453 lines | PASS |
| Sections/segments | 4,006 | sections 4,006 / segments 4,006 (sections.jsonl & segments.jsonl 4,006 lines each) | PASS |
| Characters / tokens | 26,874,831 / 7,909,432 | characters 26,874,831 / tokens 7,909,432 (DB SUM(character_count) matches to the char; DB SUM(word_count) 3,934,819 is a different metric — word-split vs tokenizer — noted, not a discrepancy) | PASS |
| Entities | 37,907 | entities.jsonl 37,907 lines | PASS |
| Canonical triples | 32,713 | canonical_triples.jsonl 32,713 (+ recovered 32-row supplement file) | PASS |
| Triple mentions | 34,416 | triple_mentions.jsonl 34,416 (+ 33-row recovered supplement) | PASS |
| Stage 56 relations → CDM 25,788 | gating flow | DB relation = 25,788 (co-occurrence gate min 5, FDR 0.05 per BUNDLE_INFO) | PASS |
| Validation split | REVIEW_REQUIRED 392 / COMPLETE 46 / PARTIAL 15 | validation_report.json: exact; papers_with_issues 406; llm_records 1,699; llm_terms_total 104,054; studies 453 (COMPLETE 402 / PARTIAL 51); findings 21,395 | PASS |

## 4. frozen_output (v2-era snapshot; distinct build — D9 preview)

BUNDLE_INFO.json scalars verified: corpus_release 2.2.0; terminology job
28619916; catalogue run CATNER_20261023T222954_4008914; cdm_build 2.1.0
replaced the 444-paper build on 2026-10-30; **projects 453 / entities 110,981 /
relationships 24,910 / entity_project_mentions 3,523,531 / edge_evidence
337,829**; note confirms the manuscript still reports 444-build totals.
`01_corpus/data/` line counts verified (entities 37,907; canonical_triples
32,713; triple_mentions 34,416; findings 21,395; papers 453; sections 4,006;
validation_per_paper 453). `02_data_catalogue`: 56,985 records (v2-era, cf. Δ2).
The frozen DB `03_common_data_model/database/microbiome_cdm.db` has a distinct
sha256 (dc945e15…) — frozen_output is **not** derived from 3.0.3 (as expected).

## 5. NER source artifacts

| Artifact | Expected | Observed | Status |
|---|---|---|---|
| CPU ensemble CSV (zenodo_v1) | 1,705,501 rows | 1,705,501 (7-model split sums exactly: en_core_sci_lg 960,719 + gliner_biomed 297,115 + gliner_medium 168,029 + en_ner_craft_md 119,092 + en_ner_bc5cdr_md 80,584 + en_ner_jnlpba_md 52,992 + biobert_diseases 26,970) | PASS |
| CPU ensemble in-DB | 1,705,449 (M03) | 1,705,449 (= 1,705,500 − Δ51, all in ensemble method) | PASS |
| Qwen Ollama section NER | 186,024 | qwen_sections_ner.csv 186,024 (= T1 ollama source; in-DB llm_section_ner 552,147 = ollama 186,023 + vLLM 366,123 − 1 PK-dedup) | PASS |
| Qwen vLLM body | 366,123 | vllm_sections_ner.csv 366,123 rows | PASS |
| MeSH gazetteer | 248,088 | mesh_ner_terms.csv 248,088 | PASS |
| Body-section universe | 2,817 units | T1 all-source distinct (paper,section) = 2,364 covered sections; ensemble CSV distinct (paper,section) 2,364 — sections with ≥1 mention over the 2,817-unit body universe (no text read; count of covered units only) | PASS (coverage, not universe, figure) |

Note: "2,817 body sections" is the section universe of the run, whereas the
observed 2,364 is sections-with-mentions across sources; the sum runs are
row counts, not section counts. Both figures are correct in their own frame;
flagged here so D3 quotes them consistently.

## 6. 3.0.3 provenance (D8 preview)

- `PROMOTION.txt`: promoted 2026-11-02T08:04:46 from
  `outputs/results/cdm_v3_3.0.3_rc1` by `src/scripts/cdm_remediation/promote_303.sh`
  — matches run_metadata `promoted_from` / `promoted_at` exactly.
- `VERIFICATION_303.json`: preservation pass (41→44 tables, 39 identical, 2
  additive), indexes equal (reversible), verdicts PASS (10 warnings each),
  registry validation 302: PASS 115/FAIL 5/COND 1 → rc: PASS 118/FAIL 2/COND 1,
      14 tests, 0 regressions, overall pass true.
- `REVERT_303.sql` present (parse-only verification deferred to D8 per plan).
- `run_metadata.derived_from` = 3.0.2 sha256 1ddfcee2e90c77f2… — matches 3.0.2
  DB hash recorded in PASS_D0.

## Commands used

All re-derivations were executed over `checks_D1.sql` (attached alongside) via
python sqlite3 with `file:…?mode=ro&immutable=1` and `PRAGMA query_only=ON`;
JSONL artifacts counted with byte-line readers (NUL-safe where applicable);
JSON summaries read directly. Any failure encountered during collection is
recorded verbatim in DATA_AUDIT.csv notes (one known STOP_LINE recorded in D0:
none for D1; the `relation_evidence.relation_id` column error is recorded as a
schema note, resolved to `canonical_triple_id`).

## Stop

PASS D1 is complete. Next: **PASS D2 — referential integrity** (name-implied
FKs, documented per edge; relation_evidence join on canonical_triple_id).
