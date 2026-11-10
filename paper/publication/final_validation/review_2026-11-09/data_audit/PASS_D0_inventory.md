# PASS D0 — Artifact inventory (2026-11-09)

Read-only data audit. All writes confined to `review_2026-11-09/data_audit/`.
No text/prose columns were selected anywhere in this pass; schema only.

## D0.1 — Databases under `releases/`

| Path | Size (bytes) | mtime | sha256 |
|---|---|---|---|
| `releases/cdm_v3/3.0.0/microbiome_cdm_v3.db` | 2,025,320,448 | 2026-10-31 01:12 | `1b425dd3d75ba93e6f08c892da76e5dd7637899b0f28c9a724ae86a439c017e0` |
| `releases/cdm_v3/3.0.1/microbiome_cdm_v3.db` | 2,649,288,704 | 2026-10-31 11:16 | `b72d58184ebf8519934a2f882004d2f7dc21ad1a7df8ef77cef1cd06a08486fe` |
| `releases/cdm_v3/3.0.2/microbiome_cdm_v3.db` | 2,836,135,936 | 2026-10-31 12:19 | `1ddfcee2e90c77f21aa8593db92e9a4aeb60b35c819854e224d413fa66ca4c45` |
| **`releases/cdm_v3/3.0.3/microbiome_cdm_v3.db` (FROZEN_DB)** | 3,160,592,384 | 2026-11-02 08:04 | `5d23ba87d29ac7a6de831e66b35c0f42bc10312132cf20dd0191526b8b041e3e` |
| `releases/frozen_output/03_common_data_model/database/microbiome_cdm.db` | 612,900,864 | 2026-10-29 01:56 | `dc945e15595eada062d24fb9c70a2c420c0d0ec807b6d7e60519585338d6466e` |

- FROZEN_DB sha256 matches the expected `5d23ba87` prefix ✓ (checked fresh from the artifact in this pass; this is the same fresh hash from the manuscript-review Pass 0, byte-identical).
- Four coexisting CDM v3 versions (3.0.0–3.0.3) under `releases/cdm_v3/` — **all four present on disk**; the fix-target set for this audit is **3.0.3 only**, per your instruction. No `.sqlite` files anywhere.
- Exactly one DB inside `FROZEN_OUTPUT` — confirming `frozen_output` does not contain a second CDM v3-family database (needed for Pass D9 but now confirmed at the inventory level).

## D0.2 — `releases/terminology/1.0.1/` (TERMINOLOGY_DIR) — 26 files

| File | Bytes | mtime |
|---|---|---|
| `canonical_terms.jsonl` | 128,869,681 | 2026-10-25 17:44 |
| `canonical_terms_summary.json` | 2,870 | 2026-10-25 17:44 |
| `_definitions_summary.json` | 2,122 | 2026-10-25 17:43 |
| `_mentions_summary.json` | 1,949 | 2026-10-25 17:43 |
| `MANIFEST.sha256` | 2,249 | 2026-10-31 11:40 |
| `OFFSET_FIX_REPORT.json` | 639 | 2026-10-31 11:40 |
| `mapping_projection_summary.json` | 4,760 | 2026-10-25 17:44 |
| `ontology_registry.json` | 4,275 | 2026-10-25 17:44 |
| `PROVENANCE.json` | 4,478 | 2026-10-31 11:40 |
| `README.md` | 1,285 | 2026-10-31 11:40 |
| `taxonomy_summary.json` | 1,139 | 2026-10-25 17:44 |
| `term_definitions.jsonl` | 864,138 | 2026-10-31 11:40 |
| `terminology_extraction_manifest.json` | 6,940 | 2026-10-25 17:45 |
| `terminology_extraction_report.md` | 8,567 | 2026-10-25 17:45 |
| `terminology_taxonomy.json` | 42,159 | 2026-10-25 17:44 |
| `terminology_validation.jsonl` | 2,593,819 | 2026-10-25 17:45 |
| `term_mentions.jsonl` | 3,824,843,008 | 2026-10-31 11:40 |
| `term_ontology_mappings.jsonl` | 382,755,547 | 2026-10-25 17:44 |
| `validation_summary.json` | 2,255 | 2026-10-25 17:45 |
| `calibration_v0_pre_fix/calibration_review_guide.md` | 2,669 | 2026-10-24 09:15 |
| `calibration_v0_pre_fix/calibration_sample.csv` | 105,023 | 2026-10-24 09:15 |
| `calibration_v0_pre_fix/calibration_sample.jsonl` | 266,734 | 2026-10-24 09:15 |
| `calibration_v0_pre_fix/_calibration_sample_summary.json` | 4,176 | 2026-10-24 09:15 |
| `calibration_v0_pre_fix/QUARANTINE.md` | 657 | 2026-10-26 11:20 |
| 1 further item (`releases/terminology/release_gate_report.json`, 7,345 B, sits one level up at `releases/terminology/`) | | |

Observations:
- Both T1-stage artifacts exist and are **large**: `term_mentions.jsonl` 3.82 GB and `term_ontology_mappings.jsonl` 382.8 MB. Row-count verification in later passes will stream-count rather than trust summaries.
- **`calibration_v0_pre_fix/` exists and contains `QUARANTINE.md`** — this is the superseded T5b sample directory flagged in the pipeline record. Its presence alongside the MANIFEST is the T5b/c `NOT_CALIBRATED` physical marker; verified in D4.
- Terminology also retains sibling `releases/terminology/1.0.0/` (not in the target set).

## D0.3 — `releases/data_catalogue_v3/` (catalogue 3.0.0 / 3.1.0 / 3.1.1) — 38 / 46 / 46 files

All three versions present, each with `MANIFEST.json`, `MANIFEST.sha256`, `provenance/`, `records/`, `review/`, `scripts/`, `tables/`. `3.0.0` has 38 files (39 MB); `3.1.0` and `3.1.1` each have 46 files (46 MB). Records layer for `3.1.1`:
- `records/catalogue_records.jsonl` — 127,916,608 B, single-file record dump.
- `tables/` — 7 CSVs: `findings.csv` (22.5 MB), `assays.csv` (8.7 MB), `cohorts.csv` (11.0 MB), `samples.csv` (9.1 MB), `datasets.csv` (3.7 MB), `data_assets.csv` (1.0 MB), `papers.csv` (1.1 MB). **6 record families + papers** — matches the expected 6-family record set.

## D0.4 — `releases/frozen_output/` (697 files total; top level 945 MB shown by du)

Verified structure (`_build/`, `BUNDLE_INFO.json`, `MANIFEST.sha256` at root):
- `01_corpus/` — `csv/` (14), `data/` (18), `manifest/` (2), `schema/` (8), `segmented_sections_markdown/` (454 files), `validation/` (10)
- `02_data_catalogue/` — `catalogue_ner_v2/` (16), `judge/` (5), `manifest/` (2), `quality/` (4), `records/` (1), `tables/` (7), `terminology/` (10)
- `03_common_data_model/` — `crosswalk/` (3), `database/` (7), `documentation/` (9), `ontology/` (4), `schema/` (8)
- `04_ner/` — 8 subdirs: `multi_ner_444/` (10), `qwen_sections_ner/` (2), `section_ner_453/` (9), plus the four `*_452` variant dirs (`section_ner_bert_variants_452`, `section_ner_extra_variants_452`, `section_ner_gliner_new_452`, `section_ner_java_tools_452`) and `section_ner_hunflair2_trim_452` — **452-paper and 453/444 universes coexist under one parent**, to be kept strictly separate in D1/D9.
- `05_evidence/` — `docs/` (2), `figures/` (11), `llm_judge/` (3), `logs/` (4), `manuscript/` (4), `notes/` (2), `tables/` (7)
- `_build/` — builder script, `carried/`, `__pycache__/`

## D0.5 — `releases/cdm_v3/3.0.3/` ancillary files

- `MANIFEST.sha256` (4,471 B), `PROMOTION.txt` (119 B), `README.md` (921 B), `REVERT_303.sql` (3,563 B) — all present as expected; **`REVERT_303.sql` exists at the 3.0.3 release root**.
- `remediation/` (docs only): `CDM_COLUMN_DICTIONARY.csv`, `CDM_MIGRATION_PLAN.md`, `CHANGE_REPORT_302_vs_303.md`, `COMPLETE_CDM_DATA_DICTIONARY.md`, `dictionary_302/`, `EXPERT_REVIEW_PACKAGE.md`, `INTEROPERABILITY_IMPROVEMENT_PLAN.md`, `MASTER_REMEDIATION_PLAN.md`, `MISSING_PROVENANCE_RECOVERY_MATRIX.csv`, `PRESERVATION_CHECK.csv`, `regression/`, `RELATIONSHIP_REDESIGN_PROPOSAL.md`, `UPDATED_ENTITY_REGISTRY_PROPOSAL.csv`, `VERIFICATION_303.json`, `VOCABULARY_REFERENCE.md`, `vocabulary_violations.json`

## D0.6 — Related registry/symlink bundles

- `releases/CURRENT_FROZEN_SET_2026-11-02/` — symlink pointer set: `01_corpus_release` → `pipelines/corpus_v2/releases/2.2.0`; `02_corpus_segmented` / `03_corpus_markdown` / `04_ner_per_model` → `frozen_output`; `05_terminology` → `terminology/1.0.1`; `06_data_catalogue` → `data_catalogue_v3/3.1.1`; `07_common_data_model` → `cdm_v3/3.0.3`; plus `README.md` and `VERIFY.sh`. **Confirms 1.0.1 / 3.1.1 / 3.0.3 as the current frozen set** — consistent with the audit's target set.
- `releases/` additionally holds `data_catalogue/` (older v1-era bundle), `data_catalogue_v3/`, `zenodo_v1/`, `zenodo_frozen/`, `zenodo_frozen_build1_SUPERSEDED/` (explicitly labelled SUPERSEDED), `ZENODO_UPLOAD_METADATA.json`, `RELEASES.md` — **outside the target set**, listed for D9 context only (the "superseded" labelling is relevant to the 444-appears-only-historically check).
- `docs/reports/pipeline_flowchart.md` (16,151 B, 2026-11-07) — **FLOWCHART_DOC located**, fills the `<path>` placeholder.

## D0.7 — FROZEN_DB schema (`sqlite_master`, column names only; no data read)

Full dump: `frozen_db_schema_D0.txt` in this directory. Summary:
- **44 tables + 57 indexes, 0 views, 0 triggers.** All 57 indexes are `sqlite_autoindex_*` (implicit UNIQUE/PK autoindexes) — e.g. `sqlite_autoindex_term_mention_1`, `sqlite_autoindex_relation_1`, `sqlite_autoindex_paper_1`.
- **0 declared FOREIGN KEY constraints** across all 44 tables (`PRAGMA foreign_key_list` = empty for every table). Referential integrity in D2 must therefore use name-implied FK inference, per your instruction ("explicit or implied by name").
- Table groups relevant to later passes (full column lists in the dump):
  - Corpus paper/publication/study/section (1:1:1:1 chain by name: `paper`, `publication`, `study`, `source_asset`, `section`)
  - Mentions: `term_mention` (29 cols incl. `section_id`, `canonical_term_id`, `paper_id`, `start_offset`, `end_offset`, `offset_status`), `term_occurrence` (1,362,931 rows at last count)
  - Terminology: `canonical_term`, `removed_canonical_term`, `term_definition`, `removed_term_definition`, `taxonomy_annotation`, `term_concept_map`, `concept`
  - Triples: `relation` (25,788), `relation_evidence` (34,416), `removed_relation` (6,925)
  - Catalogue: 6 record-family tables (`findings`-family = `claim` + `claim_evidence` + `quantitative_result`, `assay`, `cohort`, `sample`, `dataset`/`dataset_release`, `data_asset`) + `type_harmonization`
  - Compendium: `compendium_project`, `compendium_sample`, `compendium_sample_tag`
  - Provenance: `extraction_run`, `evaluation_run`, `processing_event`, `processing_lineage`, `cdm_change_log`, `run_metadata`, `load_audit`, `validation_result`, `human_review`, `cdm_entity_status`, `identifier_crosswalk`, `intervention`, `body_site`
- Note on quantitative_result/claim: at 45,667 rows each, `claim` and `claim_evidence` are equal-count tables (expected 1:1 pair from the same catalogue pass) — D2 will verify the id-pairing rather than assume.

## Target set confirmation requested (end of PASS D0)

Everything in the `== INPUTS ==` list exists. Nothing is MISSING. Two items needed explicit resolution, flagged for your confirmation:

1. **`OUT_DIR` collision with the earlier manuscript audit**: this data audit writes to `review_2026-11-09/data_audit/` (created), keeping the manuscript audit's `PASS_0_preflight.md` untouched at `review_2026-11-09/`. Confirm the nesting is acceptable.
2. **Schema-level quirk recorded, not judged**: FROZEN_DB has **0 explicit FK constraints** — every D2 check will be name-implied, and I will report per-edge orphan counts on that basis, with the inference documented in `checks_D2.sql`.

## Files written this pass

- `PASS_D0_inventory.md` (this file)
- `checks_D0.sql`
- `frozen_db_schema_D0.txt`
- `DATA_AUDIT.csv` (initialized; pass column carries `D0` rows)

**Stopping here** per instructions — PASS D1 (layer/version labelling) will run only on your confirmation of the target set above.
