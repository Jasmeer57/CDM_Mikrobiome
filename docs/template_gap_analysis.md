# Template gap analysis — CDM and data catalogue (2026-10-30)

Templates checked: `src/template/cdm/` (design template 0.1.0, 34-entity registry),
`src/template/data_catalogue/` (schema, CSV templates, workflow sheet),
`src/template/corpus_template.json`. Compared against the 453-paper CDM build
(`releases/frozen_output/03_common_data_model/database/microbiome_cdm.db`) and the
v3 catalogue (`releases/data_catalogue_v3/3.0.0/`).

## 1. Headline

1. **The physical CDM database does not implement the template.** The SQLite DB
   has an older flat schema (`entities`, `relationships`, `projects`, `samples`,
   `controlled_vocabularies`, `edge_evidence`, …). The template defines 34
   entities in 10 modules (M1–M10) with HM* keys, run/review/evidence fields on
   every record. None of the M3 (runs), M4 identity layers, M6 catalogue
   entities, M7 claims/relations or M9 review tables exist as tables.
2. **The template's own registry is stale** — it still marks terminology as
   smoke-capped and the catalogue at v1 counts. Real state is better (below).
3. **The catalogue uses only one of the six missing-data values.** Every empty
   cell is blank (= not extracted). The template requires `NOT_REPORTED`
   (checked and absent), `NOT_APPLICABLE`, `NOT_ACCESSIBLE`, `CONFLICTING`. A
   field is "complete" only when it holds a value or one of these codes.

## 2. CDM entity status (template registry vs reality)

| Module / entity | Template says | Actually available | Gap |
|---|---|---|---|
| M1 PAPER, SOURCE_ASSET | populated | 453 papers, source inventory | dup handling: only 11 papers flagged in `duplicate_group_id`, but compendium links 482 BioProjects → 413 distinct publications |
| M2 SECTION / PARAGRAPH / SENTENCE | section populated, others partial | 4,006 sections | paragraph/sentence tables not built |
| M3 EXTRACTION_RUN / MODEL_RUN / LINEAGE | partial | 7,347 processing events + run manifests | no unified run table; catalogue/link/vocab runs not registered |
| M4 TERM_MENTION / OCCURRENCE / CANONICAL / DEFINITION | partial (smoke-capped) | **2,505,735 mentions, 165,991 canonical (terminology 1.0.0)**; definitions **1,150** | definitions cover few terms; DB `entities` is a different registry (110,981) |
| M5 CONCEPT / TERM_CONCEPT_MAP / TAXONOMY | partial | 334,231 mappings (+ guards v2: 16,622 rejected); taxonomy v1 | mapping validity 38.9% (judge); crosswalk L3→L2 69% matched, 16.8% type agreement |
| M6 STUDY / COHORT / SAMPLE / ASSAY | partial | studies 453; catalogue v3 cohorts 7,451, samples 8,461, assays 9,292 | not in the DB; strict precision 38–57% |
| M6 BODY_SITE | PLANNED | v3 `body_site_normalized` + UBERON ids (verified) | not a table |
| M6 INTERVENTION | PLANNED | free text only (`comparison_or_exposure`, studies exposures) | **missing** |
| M7 CLAIM / QUANTITATIVE_RESULT | populated / partial | corpus findings 21,395; catalogue findings 24,677 | two findings sets, not reconciled; not in DB |
| M7 RELATION | PLANNED | **32,713 canonical triples, 34,416 triple mentions (stage 53/56 done)** | not loaded; triple entities not linked to canonical terms |
| M8 evidence | partial | quotes + spans | template rule 5 needs `text[start:end] == quote` exactly; v3 catalogue has 4,725 normalized + ~4,000 fuzzy matches (not exact) |
| M9 VALIDATION_RESULT / EVALUATION_RUN | populated | QA reports, judges, Claude evaluation | — |
| M9 HUMAN_REVIEW | PLANNED | none | **no human review**; template: only gate to ACCEPTED |
| M10 DATASET / DATA_ASSET / RELEASE | partial | v3 tables, releases with manifests | asset.dataset_id required by schema but 7.2% empty |
| Compendium samples (`samples`, `sample_tags` tables) | — | 168,464 samples, tags | **tables empty in DB** |
| Ontology (OWL) | — | 14 classes, no hierarchy | stub TBox |

## 3. Catalogue template compliance (v3.0.0)

| Template requirement | Status |
|---|---|
| Stable HM* ids per entity | ✅ |
| Required fields (`*_id`, `paper_id`; `dataset_id` on assets) | ⚠ 148 assets (7.2%) lack `dataset_id` |
| Six-value missing-data vocabulary | ❌ only blank used |
| `evidence_text` + `evidence_location` on critical values | ✅ (quotes redacted for 164 non-CC papers in the public release) |
| Papers: keywords, full_text_format, primary_research_domain, human_study_design, curation_status | ❌ 0% filled; licence ✅ (Europe PMC) |
| Workflow step 5: verify repository landing pages / accession types | ❌ not done |
| Workflow step 9: manual review of a stratified sample | ⚠ LLM-as-judge only (Claude Opus 5.5, 400 records) |
| Cross-paper dataset reuse (canonical dataset + link table) | ❌ datasets are per paper |
| `workflow.csv` statuses | ❌ all NOT_STARTED |

## 4. What closes each gap

| Gap | GPU? | Plan reference |
|---|---|---|
| NOT_REPORTED / value recovery for key fields | GPU | `gpu_gap_plan.md` G1 |
| Paper-level fields (domain, design, keywords, availability) | GPU | G2 |
| Catalogue record verify-and-repair (types, fields, primary, direction) | GPU | G3 |
| Link repair + required `dataset_id` on assets | GPU | G4 |
| INTERVENTION entity | GPU | G5 |
| RELATION: link triple entities to canonical terms | GPU | G6 |
| Crosswalk / type harmonization | GPU | G7 |
| Definitions coverage | GPU | G8 |
| Mapping validity (re-adjudicate guarded mappings) | GPU | G9 |
| Full-census judge of the v3.1 catalogue | GPU | G10 |
| Exact evidence quotes (rule 5) | CPU | re-anchor: replace fuzzy quotes by the exact source span |
| Compendium samples/tags into DB; publications table; duplicate flags | CPU | C1 |
| Build template-shaped CDM (M1–M10 tables) from all sources | CPU | C2 |
| Repository/accession verification | network (login node) | C3 |
| Ontology hierarchy (TBox) | CPU/manual | C4 |
| HUMAN_REVIEW | people | — (LLM evaluation is not a substitute under template rule 3) |
