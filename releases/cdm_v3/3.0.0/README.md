# Human Microbiome Research CDM — 3.0.0

Template-shaped build (src/template/cdm 0.1.0, modules M1–M10) over the 453-paper corpus, the v3.1 data catalogue, terminology 1.0.0, the GPU gap stages (docs/gpu_gap_plan.md) and the compendium samples for the corpus BioProjects. All rows are machine-derived; `review_status` is UNVERIFIED / REVIEW_REQUIRED everywhere — no human review exists yet (`human_review` is empty by design).

| entity | module | table | rows | status |
|---|---|---|---:|---|
| PAPER | M1_source_documents | `paper` | 453 | POPULATED |
| SOURCE_ASSET | M1_source_documents | `source_asset` | 453 | POPULATED |
| SECTION | M2_document_structure | `section` | 4,006 | POPULATED |
| PARAGRAPH | M2_document_structure | `paragraph` |  | EMBEDDED |
| SENTENCE | M2_document_structure | `sentence` |  | EMBEDDED |
| EXTRACTION_RUN | M3_processing | `extraction_run` | 28 | POPULATED |
| MODEL_RUN | M3_processing | `model_run` |  | EMBEDDED |
| PROCESSING_LINEAGE | M3_processing | `processing_lineage` | 5 | POPULATED |
| TERM_MENTION | M4_terminology | `term_mention` | 1,948,059 | POPULATED |
| TERM_OCCURRENCE | M4_terminology | `term_occurrence` | 1,362,931 | POPULATED |
| CANONICAL_TERM | M4_terminology | `canonical_term` | 162,409 | POPULATED |
| TERM_DEFINITION | M4_terminology | `term_definition` | 6,773 | POPULATED |
| CONCEPT | M5_semantic_mappings | `concept` | 204,817 | POPULATED |
| TERM_CONCEPT_MAP | M5_semantic_mappings | `term_concept_map` | 327,297 | POPULATED |
| TAXONOMY_ANNOTATION | M5_semantic_mappings | `taxonomy_annotation` | 0 | EMPTY |
| STUDY | M6_research_context | `study` | 453 | POPULATED |
| COHORT | M6_research_context | `cohort` | 7,085 | POPULATED |
| SAMPLE | M6_research_context | `sample` | 7,530 | POPULATED |
| ASSAY | M6_research_context | `assay` | 8,545 | POPULATED |
| BODY_SITE | M6_research_context | `body_site` | 29 | POPULATED |
| INTERVENTION | M6_research_context | `intervention` | 1,935 | POPULATED |
| CLAIM | M7_findings | `claim` | 45,667 | POPULATED |
| RELATION | M7_findings | `relation` | 25,788 | POPULATED |
| QUANTITATIVE_RESULT | M7_findings | `quantitative_result` | 13,540 | POPULATED |
| CLAIM_EVIDENCE | M8_evidence | `claim_evidence` | 45,667 | POPULATED |
| MENTION_EVIDENCE | M8_evidence | `mention_evidence` |  | EMBEDDED |
| DEFINITION_EVIDENCE | M8_evidence | `definition_evidence` |  | EMBEDDED |
| VALIDATION_RESULT | M9_quality_review | `validation_result` | 463 | POPULATED |
| HUMAN_REVIEW | M9_quality_review | `human_review` | 0 | EMPTY_NO_HUMAN_REVIEW_YET |
| EVALUATION_RUN | M9_quality_review | `evaluation_run` | 3 | POPULATED |
| DATASET | M10_catalogue_releases | `dataset` | 2,976 | POPULATED |
| DATA_ASSET | M10_catalogue_releases | `data_asset` | 1,992 | POPULATED |
| DATASET_RELEASE | M10_catalogue_releases | `dataset_release` | 10 | POPULATED |

Extra tables: `publication`/`paper_publication` (453 BioProject papers → distinct publications; shared publications flagged CONFLICTING), `compendium_sample`, `compendium_sample_tag`, `compendium_project`, `type_harmonization`, `term_concept_map.relation_llm_g9`.

Verify: `sha256sum -c MANIFEST.sha256`
