# CDM Architecture Report — DRAFT 0.1.0

Phase-closing summary of the CDM design work: what exists, what was designed,
what was verified, what is blocked, and what is recommended next. Design phase
only — no migration performed, no production outputs touched.

## 1. Deliverable set (this phase)

| # | Deliverable | Location | Status |
|---|---|---|---|
| 0 | CDM template (normative anchor) | `template/cdm/` (README.md, human_microbiome_cdm_template.md, human_microbiome_cdm.schema.json incl. 33-entity registry, cdm_entity_registry.csv) | DONE (DRAFT 0.1.0) |
| 1 | Source inventory | `docs/cdm_design/cdm_source_inventory.csv` (62 resources, all counts session-verified) | DONE |
| 2 | Schema proposal | `docs/cdm_design/cdm_schema_proposal.md` (8 decisions, 10 modules, OMOP view layer) | DONE |
| 3 | Machine-readable schema | `docs/cdm_design/cdm_schema.json` (22 tables, all columns bound to verified source keys) | DONE |
| 4 | Field crosswalk | `docs/cdm_design/cdm_field_crosswalk.md` (M1–M10 field-level bindings, mapping semantics) | DONE |
| 5 | Data relationships | `docs/cdm_design/cdm_relationships.md` (ER graph, cardinality rules, join spec, enforcement) | DONE |
| 6 | Validation specification | `docs/cdm_design/cdm_validation_specification.md` (V0–V6, fail-closed, quarantine procedure) | DONE |
| 7 | Migration risks | `docs/cdm_design/cdm_migration_risks.md` (R1–R4, evidenced, mitigated) | DONE |
| 8 | Architecture report (this file) | `docs/cdm_design/cdm_architecture_report.md` | DONE |

## 2. Reconciliation outcome (what the template had to resolve)

Five pre-existing sources of truth were reconciled, not competed with:

1. `template/corpus_template.json` v1.1.0 — per-paper master record; its fields are
   inherited wholesale into PAPER/SOURCE_ASSET via papers.jsonl (77 keys verified).
2. `template/data_catalogue/` — HM* sequential ID registry + catalogue tables;
   their IDs, table layouts (headers verified column-by-column) and missing-data
   vocabulary are adopted as catalogue entity definitions.
3. `notebooks/cdm_catalogue_schema.yaml` DRAFT 0.1.0 — superseded as a spec by the
   template but its rule 5 (locator gate) and layering survive in the validation
   spec (V3.1). Its dangling dependency (`ner_entity_template.yaml 0.1.0`) remains
   a documented gap, now absorbed by `template/cdm/`.
4. `corpus_v2/schema/*.json` — authoritative record schemas + ID patterns; the CDM
   inherits them and never re-defines a record field.
5. `configs/canonical.yaml` (14 CDM entity types, pinned env v2.1.1) +
   `scripts/termpipeline/ids.py` (deterministic HM* identity) — both adopted
   unchanged; the 33-entity registry generalizes the 14 types without renaming
   anything.

## 3. Verification standard applied (what "grounded" meant in practice)

- Every count in the inventory was recomputed in-session (real CSV parsing —
  the naive line counts over-read catalogue tables by 13–37% due to quoted
  embedded newlines).
- Every column in `cdm_schema.json` was diffed against the actual first-record
  key sets of the ten JSONL sources and the seven catalogue CSV headers. This
  caught: 4 fabricated/wrong field references (`author_interpretation` does not
  exist in findings.jsonl; `section_id_original` is `section_id` in mention and
  definition files; two catalogue header typos), and 21 papers.jsonl fields
  initially unbound — all fixed before release of the deliverable set.
- Known join translation is documented rather than normalized away:
  sections carry `section_id_original`; mentions/definitions carry `section_id`
  that equals it; claims carry `evidence_section_id`. One rule (§join spec),
  no silent renaming at ingest.

## 4. Verified resource scale (baseline the CDM must not lose)

Papers 453; sections/segments 4,006; findings 21,395 (catalogue projection 22,439);
studies 453; processing events 7,339; canonical terms 166,012; chain mappings 30,533
(smoke-scoped; cv-link full run in flight); terminology raw pool 1,820,028;
catalogue: datasets 3,228, data_assets 2,143, cohorts 9,575, samples 8,484,
assays 12,116; PubTator3 coverage 434/453 (300 original + 134 backfilled 2026-10-24,
job 28608086; residual: 9 no-PMID, 6 zero-annotation, 4 transient API errors);
NER eval evidence records 735 (unadjudicated).

## 5. Physical architecture (proposal, per D2/D7)

```
Layer view (L1..L5, template §1)
  └─ 33 logical entities, 10 modules (registry in template/cdm)
       └─ physical: single SQLite DB (cdm_human_microbiome_v0_1.sqlite)
            + per-entity JSONL mirrors (release-distributable, manifest-hashed)
            + OMOP views layer (8 vocabulary-facing views, read-only)
Analytics: DuckDB/Parquet mirrors derived later, never primary.
Legacy DBs (×2, 444-era): migration-input-only, re-validation required.
```

## 6. Blocked items (external to the design)

| Blocker | Gate | Affects |
|---|---|---|
| Stage 53/54 triples (job 28607588 PENDING, resources; 28607924 dependent) | verified triple_mentions.jsonl | RELATION population; release 2.2.0 packaging |
| termpipe-v1 (user job 28608065, PENDING) | full-scale term_mentions/definitions | smoke-capped chain artifacts lift (6,000→full; 59→full) |
| cv-link (job 28607619, RUNNING) | verified mapping manifest | term_concept_map full population |
| llm-ner-body (job 28607825, RUNNING, 7 segment errors) | completion review | body-NER mentions for termpop promotion |
| Human adjudication (735 records + sample_type queue) | HUMAN_REVIEW rows | any accuracy claim; error sections of NER eval report |

## 7. Recommended next actions (in order)

1. **Adjudication**: first-pass human review over
   `results/28608068_ner_eval_permodel/ner_comparison_errors.jsonl` (735 records)
   — it is both the NER-report gate and the pilot of the HUMAN_REVIEW table design.
2. **PubTator3 retry** of the 4 transient-error papers once (new results dir,
   original untouched), then freeze coverage at ≤438/453 and document residuals.
3. **NER eval presentation fixes** in `results/28608068_ner_eval_permodel/`
   (like-for-like span note, all-ensemble span rate, PubTator3 macro mean next to
   macro CI), optionally re-run the PubTator3 leg on merged 434-paper coverage.
4. **Wait state**: 28607588 → 28607924; then verify triple_mentions.jsonl,
   entity_linking_report.json, candidate_entity_mappings.jsonl and package
   release 2.2.0 (quirk list per V5.4 in the release report).
5. **CDM build v0.1.0** (separate go-ahead): implement ingest per the validation
   spec into the SQLite + JSONL layout; quarantine-first, fail-closed.

## 8. Standing constraints honored

Read-only on all production outputs; user-submitted jobs untouched; SLURM-only
compute (no `--account` line, `intelsr_short`); no commits/pushes without explicit
go-ahead; no model treated as ground truth; conflicts retained; no accuracy
claims without adjudication.
