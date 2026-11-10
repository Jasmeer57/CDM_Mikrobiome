# CDM Field Crosswalk — DRAFT 0.1.0

Binding of every CDM field to its real source field(s), record-by-record.
Companion to `template/cdm/` (normative) and `cdm_source_inventory.csv` (inputs).

Legend: **source → CDM field**; `(direct)` = copied verbatim; `(join)` = via the stated key;
`(derive)` = deterministic derivation (no new judgment); `(new)` = CDM-native field
(evidence gate, review state) with no source — its value originates only from the
named CDM mechanism (e.g. HUMAN_REVIEW). Normalization note per surface-form field:
`canon_norm` (alnum-collapse lowercase = identity) or `word_norm` (fuzzy-dedup key only).

## M1 PAPER
| source field | CDM field | mapping |
|---|---|---|
| papers.jsonl `paper_id` | PAPER.paper_id | (direct) PK `^HMPAPER_[0-9]{6}$` |
| papers.jsonl `title` | PAPER.title | (direct); also feeds PAPER.title_norm (derive, canon_norm) |
| papers.jsonl `DOI`,`PMID`,`PMCID`,`corpus_id`,`extern` | PAPER.doi/pmid/pmcid/corpus_id/external_ids | (direct) |
| papers.jsonl `bioproject` (dict→accession) | PAPER.bioproject | (derive) normalized accession string; dual BP↔paper index (template §5 join check) |
| papers.jsonl `publication_year`,`journal`,`venue`,`license_name`,`citation_count`,`language`,`keywords`,`authors` | PAPER.* same names | (direct) |
| papers.jsonl `full_text_availability`,`full_text_completeness`,`full_text_parse_status`,`source_integrity`,`integrity_checks`,`metadata_*`,`processing_status`,`validation_status`,`completeness_checks`,`dedup`,`is_canonical`,`duplicate_group_id`,`canonical_paper_id`,`reviewer`,`review_date`,`annotation_status`,`human_microbiome_relevance`,`exclusion_reason`,`inclusion_decision`,`eligibility_status` | PAPER.* same names | (direct); integrity vs availability enums kept separate (paper.schema.json rule) |
| papers.jsonl `raw_file_hash`,`extracted_text_path`,`original_fulltext_path`,`original_pdf_path`,`original_xml_path`,`text_version_id`,`source_url` | SOURCE_ASSET.* | (direct) per asset row |
| papers.jsonl `extraction_date`,`extraction_tool`,`retrieval_date`,`protocol_version`,`schema_version`,`curation_notes` | PAPER.extraction metadata block | (direct) |

## M2 SECTION
| source field | CDM field | mapping |
|---|---|---|
| sections.jsonl `(paper_id, section_id_original)` | SECTION composite PK | (direct); section_id does not exist as a single field in source |
| sections.jsonl `section_record_id` | SECTION.section_record_id | (direct) unique record id if present |
| sections.jsonl `section_name_original`,`section_name_normalized`,`section_type`,`heading_path`,`section_order`,`parent_section_id`,`is_container_section` | SECTION.* same names | (direct) |
| sections.jsonl `section_text_original` | SECTION.section_text_original | (direct) canonical evidence geometry holder |
| sections.jsonl `source_char_start`,`source_char_end` | SECTION.source_char_start/end | (direct) into source file; SOURCE_ASSET join via `source_file_hash_sha256` |
| sections.jsonl `text_hash_sha256`,`character_count`,`token_count`,`token_count_method`,`word_count`,`sentence_count`,`paragraph_count` | SECTION.* same names | (direct) geometry + stats |
| sections.jsonl `offset_convention`,`counting_convention` | SECTION.offset_convention | (direct); all downstream offset rules reference this |
| sections.jsonl `parsing_status`,`section_quality_status`,`quality_checks`,`validated_at`,`validator_version`,`language`,`language_status`,`cleaning_operations`,`hierarchy_status`,`exclusion_reason`,`extraction_eligibility`,`llm_enrichment` | SECTION.* same names | (direct) |
| sections.jsonl `segment_ids` | SECTION.segment_ids | (direct) → SECTION_SEGMENT join rows (M2) |
| segments.jsonl (one/section) | SECTION chunk geometry fields | (join) via segment_id |

## M3 EXTRACTION_RUN / MODEL_RUN / PROCESSING_LINEAGE
| source field | CDM field | mapping |
|---walk|---|---|
| processing_events.jsonl `run_id` | EXTRACTION_RUN.run_id | (direct) PK |
| processing_events.jsonl `pipeline_stage`,`pipeline_version` | EXTRACTION_RUN.stage/version | (direct) |
| processing_events.jsonl `started_at`,`completed_at`,`run_status`,`error_message`,`retry_count`,`manual_intervention`,`operator_or_reviewer` | EXTRACTION_RUN.* same names | (direct) |
| processing_events.jsonl `input_artifact_hash → output_artifact_hash` | PROCESSING_LINEAGE edges | (derive) run→in-artifact, run→out-artifact; parent/child run edges added for section-mode vs paper-mode run pairs (template §2 M3) |
| zenodo_v1 run summaries (`_sections_ner_summary.json`, `_qwen_sections_summary.json`) | EXTRACTION_RUN coverage stats | (join/direct) yields, paper coverage, model versions per run |
| `_termpipe_chain/terminology_extraction_manifest.json` | EXTRACTION_RUN rows for T1–T9 + MODEL_RUN versions | (direct) manifest = run record |
| run manifests in `results/*` (e.g. 28608068 `run_manifest.json`) | EXTRACTION_RUN rows | (direct); PROVISIONAL rows for in-flight jobs (cv-link, llm-ner-body, termpipe-v1) promoted to verified on manifest check |
| configs/canonical.yaml `environment` | MODEL_RUN pinned versions | (direct; join by model name) |

## M4 TERM_MENTION / TERM_OCCURRENCE
| source field | CDM field | mapping |
|---|---|---|
| _termpipe_chain/term_mentions.jsonl `mention_id` | TERM_MENTION.mention_id | (direct) `^HMTERM_[0-9a-f]{16}$`, content-hash includes extraction_run_id |
| term_mentions `occurrence_key` | TERM_OCCURRENCE.occurrence_key | (direct) `^HMOCC_[0-9a-f]{16}$` extractor-independent span |
| term_mentions `surface_form`,`normalized_mention` | TERM_MENTION.surface_form / .normalized_mention | (direct); normalization = canon_norm |
| term_mentions `start_offset`,`end_offset` | TERM_MENTION.start/end_offset | (direct) into section_text_original |
| term_mentions `entity_type`,`domain`,`subdomain`,`subsection`,`confidence`,`extraction_method`,`extraction_model`,`extraction_run_id`,`source_file_id` | TERM_MENTION.* same names | (direct) |
| term_mentions `paper_id`,`section_id`,`paragraph_id`,`sentence_id` | TERM_MENTION location FKs | (direct) join to SECTION via (paper_id, section_id_original) |
| term_mentions `supporting_passage`,`supporting_sentence`,`supporting_sentence_clipped` | MENTION_EVIDENCE.supporting_* | (direct) |
| term_mentions `canonical_term_id`,`review_status`,`unresolved_flags` | TERM_MENTION.canonical_term_id / .review_status / .unresolved_flags | (direct) |
| term_mentions `section_name` | TERM_MENTION.section_name (locator aid) | (direct); section join is `(paper_id, section_id)` where section_id = sections.jsonl `section_id_original` |
| zenodo_v1/qwen_sections_ner/qwen_sections_ner.csv `term`,`labels`,`model`,`paper`,`section_id`,`section_path`,`char_start`,`char_end`,`llm_occurrence_expanded` | TERM_MENTION (Qwen section rows) | (derive) via termpipe assemble_mentions; preserved row-for-row, never merged with NER rows |
| zenodo_v1/ner_453_sections/*.csv `term`,`labels`,`model`,`paper`,`section_id`,`section_path`,`char_start`,`char_end` | TERM_MENTION (CPU models, section-level) | (derive) same assembling path |
| pubtator3_ner.csv (+ backfill CSV) `term`,`labels`,`model`,`paper`,`char_start`,`char_end` | TERM_MENTION (PubTator3, paper-level) | (derive) offsets 0,0 = paper-level geometry, recorded on the run; backfill rows carry backfill provenance in EXTRACTION_RUN |
| _multi_ner_runs legacy paper-level CSVs (`term`,`labels`,`model`,`paper`,`char_start`,`char_end`) | TERM_MENTION (legacy paper-level) | (derive) 444-era lineage flag on run; migration requires re-validation |
| terminology_raw.csv (1.82M rows) | TERM_MENTION raw pool | (derive) provenance of the pooling, and the remapping table applies to dedup only |
| term_mentions `review_status` values | review-state machine | UNVERIFIED → REVIEW_REQUIRED → ACCEPTED/REJECTED; automated checks only raise REVIEW_REQUIRED |
| terminology_dedup.csv rows | TERM_MENTION → CANONICAL_TERM assignment | (join) via canonical_term_id |
| term_definitions.jsonl `definition_id` | TERM_DEFINITION.definition_id | (direct) `^HMDEF_[0-9a-f]{16}$` |
| term_definitions `term_id`,`term`,`term_norm`,`cdm_type`,`defined_surface`,`definition_text`,`definition_char_start/end`,`definition_formality`,`definition_source`,`provenance_class`,`confidence`,`review_status`,`extraction_method`,`unresolved_flags`,`extraction_run_id`,`paper_id`,`section_id`,`sentence_id` | TERM_DEFINITION/DEFINITION_EVIDENCE fields | (direct) |
| canonical_terms.jsonl `term_id` | CANONICAL_TERM.term_id | (direct) `^HMCTERM_[0-9a-f]{16}$`; content-hash of (term_norm, cdm_type) |
| canonical_terms `term`,`term_norm`,`cdm_type`,`alternative_types`,`n_candidate_types`,`n_models`,`models`,`n_observations`,`mention_count`,`paper_count`,`n_papers`,`top_paper_ids`,`source_names`,`source_table`,`is_generic_type`,`definition_count`,`definition_sources`,`definition_status`,`taxonomy_category`,`taxonomy_subcategory`,`identity_evidence`,`review_status` | CANONICAL_TERM.* same names | (direct); counts are observed only, never rankings; first-record n_papers=2092 oddity goes to the ingest inspection note |

## M5 CONCEPT / TERM_CONCEPT_MAP / TAXONOMY_ANNOTATION
| source field | CDM field | mapping |
|---|---|---|
| term_ontology_mappings.jsonl `mapping_id` | TERM_CONCEPT_MAP.mapping_id | (direct) `^HMMAP_[0-9a-f]{16}$` |
| term_ontology_mappings `term_id`,`term`,`term_norm`,`cdm_type` | TERM_CONCEPT_MAP term FK block | (direct) → CANONICAL_TERM |
| term_ontology_mappings `ontology_name`,`ontology_source`,`source_service`,`concept_id`,`concept_label` | CONCEPT PK (vocabulary, concept_code) + labels | (direct); CONCEPT rows only for verified external IDs — never fabricated |
| term_ontology_mappings `mesh_kind`,`mesh_tree`,`omop_domain`,`omop_concept_class`,`omop_standard`,`standard_concept_id`,`standard_concept_label` | CONCEPT.OMOP projection fields | (direct) where present |
| term_ontology_mappings `mapping_relation`,`candidate_rank`,`is_canonical_candidate`,`auto_accept_eligible`,`competing_candidates`,`matched_via`,`staged_match`,`scores`,`mapping_disposition`,`provenance`,`review_status` | TERM_CONCEPT_MAP.* same names | (direct); disposition ACCEPTED/CANDIDATE/REJECTED/UNRESOLVED/REVIEW_REQUIRED; relation EXACT/EQUIVALENT/BROADER/NARROWER/RELATED/UNRESOLVED/REJECTED |
| term_ontology_mappings `review_status` | review-state machine | see M9 |
| term_taxonomy_v1 (yaml/csv) `category`,`subcategory` bindings | TAXONOMY_ANNOTATION.category/subcategory | (direct) project labels, not concepts |
| canonical_terms `taxonomy_category/subcategory` | TAXONOMY_ANNOTATION (flattened the other way) | (join) same binding, both sources must agree at ingest (check) |

## M6 STUDY / COHORT / SAMPLE / ASSAY / BODY_SITE / INTERVENTION
| source field | CDM field | mapping |
|---|---|---|
| studies.jsonl `bioproject`,`corpus_id`,`paper_id`,(`study_id`) | STUDY PK + FK | (direct) `^HMPAPER_[0-9]{6}_STUDY_[0-9]{3}$` |
| studies.jsonl design/methods block (`study_design`,`research_question`,`assay_type`,`sequencing_platform`,`target_gene_region`,`taxonomic_profiling_method`,`functional_profiling_method`,`statistical_methods`,`multiple_testing_correction`,`software_pipeline_version`,`taxonomic_database_and_version`,`dna_rna_extraction_method`,`collection_method`,`collection_time_points`,`storage_transport_conditions`,`quality_filtering_normalization`,`contamination_handling`,`negative_positive_controls`,`specimen_types`,`body_sites`,`health_conditions`,`eligibility_criteria`,`confounders_covariates_reported`,`limitations_reported`,`recruitment_setting`,`population_description`,`country_region`,`country_iso_from_compendium`,`sra_submission_window`,`data_accessions`,`code_data_availability`,`age_information`,`sex_gender_information`,`comparator_control_group`,`exposures_interventions`,`num_participants_reported`,`num_biological_samples_reported`,`num_technical_replicates_reported`,`num_time_points_reported`) | STUDY.* same names | (direct) |
| studies.jsonl LLM provenance block (`llm_status`,`llm_model`,`llm_model_version`,`llm_prompt_version`,`llm_source_section_ids`,`llm_source_text_hash`,`llm_input_chars`,`llm_degrees`,`llm_error`,`llm_split_retries`,`study_provenance`,`extraction_status`,`_input_fingerprint`) | STUDY.llm provenance block | (direct) — fields carried fully, never summarized away |
| studies.jsonl `assay_type_evidence` | STUDY.assay_type_evidence | (direct) |
| data_catalogue cohorts.csv (cohort_id … evidence) | COHORT.* per csv_templates/cohorts.csv | (direct); UNVERIFIED machine-extracted |
| data_catalogue samples.csv (sample_group_id … sample_type_normalization_reason) | SAMPLE.* per csv_templates/samples.csv | (direct); sample_type normalized per quality/sample_type_normalization.json; review queue feeds HUMAN_REVIEW |
| data_catalogue assays.csv (assay_id … evidence_text) | ASSAY.* per csv_templates/assays.csv | (direct) |
| samples.csv/studies body-site labels | BODY_SITE registry | (derive) labels only; CONCEPT row only via validated mapping |
| studies.csv `exposures_interventions`, findings `exposure_or_comparison` | INTERVENTION registry rows | (derive) label registry, linked to STUDY/CLAIM |
| data_catalogue datasets.csv, data_assets.csv | DATASET / DATA_ASSET | (direct) per csv_templates |

## M7 CLAIM / RELATION / QUANTITATIVE_RESULT
| source field | CDM field | mapping |
|---|---|---|
| findings.jsonl `finding_id` | CLAIM.finding_id | (direct) `^HMPAPER_[0-9]{6}_FIND_[0-9]{4}$` |
| findings.jsonl `paper_id`,`study_id`,`chunk`,`evidence_section_id`,`llm_source_section_status` | CLAIM context FKs | (direct) |
| findings.jsonl `claim_type`,`direction`,`direction_refers_to`,`outcome`,`exposure_or_comparison`,`microbial_function_pathway`,`taxon_original`,`taxonomic_rank`,`body_site_original`,`population_subgroup`,`adjusted_covariates`,`sample_size`,`notes` | CLAIM.* same names | (direct); author wording preserved in *_original fields; ~1,088 p-shaped effect_estimate values (849 dup p, 239 sole) documented, not corrected; NOTE: `author_interpretation` is NOT a findings.jsonl field (verified against actual records — do not carry over from older claim formats) |
| findings.jsonl `effect_measure`,`effect_estimate`,`confidence_interval`,`p_value`,`q_value` | QUANTITATIVE_RESULT.* | (direct) |
| findings.jsonl `corpus_id` | CLAIM.corpus_id | (direct) versioned corpus identity |
| findings.jsonl `chunk_char_offset` | CLAIM.chunk_char_offset | (direct) position of the extraction chunk within the section |
| findings.jsonl `evidence_text`,`evidence_locator`,`evidence_locator_chars`,`evidence_locator_type`,`evidence_locator_convention`,`evidence_locator_status`,`evidence_section_id`,`text_version_id` | CLAIM_EVIDENCE.* | (direct); gate: text[start:end] == quote at text_version_id |
| findings.jsonl `extraction_method`,`extractor_model_and_version`,`extractor_prompt_version`,`extraction_status_section` | CLAIM extraction provenance | (direct) → EXTRACTION_RUN/MODEL_RUN |
| findings.jsonl `verification_status`,`reviewer`,`review_date` | CLAIM.verification_status / HUMAN_REVIEW | (direct) human gate; pending → human_verified / needs_revision |
| catalogue findings.csv row (same id space) | CLAIM catalogue projection | (join) catalogue finding rows (22,439) ⊇ corpus_v2 findings.jsonl (21,395) — both kept; catalogue adds study-level linkage columns (dataset_id, cohort_id, assay_id) |
| stage 53/54 triple_mentions.jsonl (PENDING job 28607588 → stage 56 job 28607924) | RELATION.* | (derive) once verified: subject/predicate/object canonical ids, original triple, polarity, evidence, extraction run; ~28% full-triple recovery limitation recorded |
| triple_domains.json, triple_relation_schema.json | RELATION constraints | (direct) domain/relation vocabularies |

## M9 VALIDATION_RESULT / HUMAN_REVIEW / EVALUATION_RUN
| source field | CDM field | mapping |
|---|---|---|
| validation_per_paper.jsonl `paper_id`,`validation_status`,`validator_version`,`validated_at`,`checks`,`counts`,`full_text_completeness`,`known_issues` | VALIDATION_RESULT.* | (direct) |
| terminology_validation.jsonl (4,006 section checks) | VALIDATION_RESULT rows | (direct) span-integrity checks |
| catalogue quality/integrity_report.json | VALIDATION_RESULT rows | (direct) |
| catalogue quality/sample_type_review_queue.csv | HUMAN_REVIEW input queue | (direct) candidates for review |
| (new) adjudication of ner_comparison_errors.jsonl (735 records) | HUMAN_REVIEW rows | (new) reviewer/date/decision/notes per record; the ONLY mechanism producing ACCEPTED/REJECTED |
| results/28608068_* metrics, errors, stats, inventory, report, manifest | EVALUATION_RUN.* | (direct) whole deliverable set as one evaluation run; numbers never flow back to extraction rows |

## M10 DATASET_RELEASE
| source field | CDM field | mapping |
|---|---|---|
| data_catalogue/MANIFEST.json + .sha256 | DATASET_RELEASE manifest | (direct) artifact list + hashes |
| corpus_v2/releases/2.0.0, 2.1.0 (+ planned 2.2.0) | DATASET_RELEASE rows | (direct) frozen snapshots; 2.2.0 blocked on stage 53/54 + 56 |

## Backfill-specific provenance (new this session)
| source | CDM field | mapping |
|---|---|---|
| results/28608086_pubtator3_backfill/pubtator3_backfill_ner.csv | TERM_MENTION (PubTator3 paper-level, backfill run) | (derive) same 6-col layout; offsets 0,0; run = job 28608086 |
| pubtator3_backfill_status.jsonl | EXTRACTION_RUN resolution provenance + VALIDATION_RESULT (per-paper resolution checks) | (direct) strategy (pmid_direct 142 / doi 1 / title 1), status (OK 134 / zero 6 / no_pmid 9 / api error 4) |
| pubtator3_covered_after.txt | coverage reference set | (direct) 434/453 bioprojects covered post-backfill |
