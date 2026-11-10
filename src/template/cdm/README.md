# Human Microbiome Research CDM — Template

Template for the Human Microbiome Research Common Data Model (CDM): the
standardized structure into which the corpus, NER/LLM extraction outputs,
terminology, mappings, findings, and review records are organized, validated,
linked, and versioned.

**Status: DRAFT 0.1.0 — design phase.** This template is a reconciliation of the
project's existing template artifacts, not a new parallel schema. It inherits
from, and defers to, the following sources of truth:

| Inherits from | Governs |
|---|---|
| `template/corpus_template.json` (v1.1.0) | Per-paper master record conventions; `null` vs `not_reported` rule; never-infer rule; `*_raw` alongside normalized values |
| `template/data_catalogue/` (schema.json, template.json, csv_templates) | Catalogue entity templates; stable `HM*` identifier registry; missing-data vocabulary; evidence-and-provenance workflow |
| `notebooks/cdm_catalogue_schema.yaml` (DRAFT 0.1.0) | Curated-value objects; value-selection rules; evidence-quote integrity rule (quote must equal `text[start:end]`) |
| `corpus_v2/schema/*.json` | Authoritative JSON Schemas (paper, section, finding, study, processing_event, validation); `HMPAPER_*_FIND_NNNN` / `HMPAPER_*_STUDY_NNN` ID patterns |
| `scripts/termpipeline/ids.py` | Deterministic content-derived identifier layers: `HMTERM_*` (mention per extractor), `HMOCC_*` (extractor-independent occurrence), `HMCTERM_*` (canonical term), `HMDEF_*` (definition), `HMMAP_*` (mapping) |
| `configs/canonical.yaml` (v2.1.1) | The 14 CDM entity types (ORGANISM … STUDY_DESIGN) and pinned extraction environment |

## Files

- `human_microbiome_cdm_template.md` — the master design template: layered
  architecture, module registry, identifier scheme (consolidated), data-value
  conventions, evidence/provenance/mapping/review rules, and the traceability
  contract every CDM record must satisfy.
- `human_microbiome_cdm.schema.json` — machine-readable registry of CDM
  entities: layer, purpose, primary key, foreign keys, ID scheme, source
  populations, and which existing schema each entity inherits. Field-level
  definitions live in the inherited schemas; this registry never duplicates them.
- `cdm_entity_registry.csv` — one row per CDM entity: identifier scheme,
  population sources, inheritance, and status.

## Design phase deliverables that build on this template

The template is the foundation; the CDM design-phase deliverables
(`cdm_source_inventory.csv`, `cdm_schema_proposal.md`, `cdm_field_crosswalk.csv`,
`cdm_relationships.md`, `cdm_validation_specification.md`,
`cdm_migration_risks.md`, `cdm_architecture_report.md`) reference it rather
than restate it.

## Non-negotiable rules (short form)

1. Original source text, hashes, and exact evidence locations are never
   destroyed, rewritten, or re-derived.
2. Every model's original predictions survive; competing mentions of the same
   span stay separate rows (`mention_id` includes `run_id`).
3. No model output is treated as ground truth; human review is the only
   verification gate, and review status is carried on every record.
4. Mentions, occurrences, canonical terms, definitions, and mappings are
   distinct identity layers; they are never merged into one key.
5. Evidence quotes must satisfy `text[char_start:char_end] == quote` at the
   recorded text version.
6. Candidate mappings are kept alongside accepted mappings; mapping relations
   distinguish EXACT, EQUIVALENT, BROADER, NARROWER, RELATED, UNRESOLVED,
   REJECTED. External concept identifiers are never fabricated.
7. Missing data uses the six-value vocabulary (`null`, `NOT_REPORTED`,
   `NOT_APPLICABLE`, `NOT_ACCESSIBLE`, `CONFLICTING`, never numeric zero).
8. The catalogue documents all five layers; it does not become a second
   database.
