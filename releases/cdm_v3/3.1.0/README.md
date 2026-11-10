# Microbiome-CDM 3.1.0 (frozen 2026-11-10)

**CDM 3.0.3 unchanged + the cleaned, enriched and repaired layers of 2026-11-09/10 as new tables.**
Status: frozen on the first author's instruction; **project-lead approval pending** (development freeze of 2026-11-02;
see paper/publication/final_validation/CHANGE_RECORD.md). 3.0.3 remains in releases/cdm_v3/3.0.3 and is still the
version cited by the manuscript and the claims register until they are switched.

- Database: `microbiome_cdm_v3.1.0.db` (SQLite). All 44 tables of 3.0.3 with identical rows (run_metadata: version keys updated;
  cdm_change_log: one row per added table, step "310").
- New tables (9 + release_provenance_310), source files and checksums in `sources/new_tables_310.json`:
  - `term_dedup_map` (162,409 rows) - every canonical term -> canonical term after exact/fuzzy/abbreviation/embedding dedup; kept flag [DETERMINISTIC+EMBEDDING]
  - `concept_curie_map` (13,330 rows) - every accepted concept IRI -> CURIE -> canonical concept after dedup; kept flag [DETERMINISTIC+EMBEDDING]
  - `term_curation` (157,815 rows) - canonical terms after dedup with relevance verdict (KEEP/UNSURE/NOT_A_CONCEPT/IRRELEVANT) and kept flag [MODEL_JUDGEMENT (DeepSeek-V4.1-Flash, FhGenie)]
  - `concept_curation` (12,182 rows) - canonical concepts after dedup with relevance verdict and kept flag [MODEL_JUDGEMENT (DeepSeek-V4.1-Flash, FhGenie)]
  - `term_concept_map_clean` (15,769 rows) - accepted mappings remapped to canonical term and concept ids; dropped items removed [DERIVED]
  - `term_enrichment` (162,409 rows) - one row per 3.0.3 term: extracted definitions and paper full forms (SOURCE_), contextual definition, kind, full form, synonyms (MODEL_, Qwen3.5-4B) [SOURCE_ + MODEL_ columns]
  - `mapping_enrichment` (18,272 rows) - one row per accepted mapping: ontology definition and synonyms (SOURCE_, BioPortal/OLS/UMLS/NCBI), model description where the ontology has none (MODEL_) [SOURCE_ + MODEL_ columns]
  - `triple_repair` (25,788 rows) - one row per 3.0.3 triple: checked/specific relation or exit, direction, verified cue, endpoint fixes [MODEL_JUDGEMENT (Qwen3.5-4B, schema-constrained)]
  - `triple_tier` (25,788 rows) - gates (cue found, anchored, domain-range, endpoints) and Tier 1/2/3 per triple [DETERMINISTIC]

Key figures (new layers, not yet registered): terms 162,409 -> 157,815 after dedup -> 116,755 kept; accepted concepts
13,330 IRIs -> 12,657 CURIEs -> 12,182 after dedup -> 11,912 kept; accepted mappings 18,272 -> 15,769 clean rows;
triples 25,788 (unchanged) with checked relations: 8,307 specific with a verified cue, Tier 1/2/3 = 1,794 / 6,263 / 17,731.

Columns or tables marked MODEL are model-generated or model-judged (Qwen3.5-4B on local vLLM; DeepSeek-V4.1-Flash via
the Fraunhofer Genie gateway for the relevance screens) and are not curated. Contains paper-derived text: internal;
any public deposit must be rights-filtered like releases/zenodo_frozen.

Verify: `sha256sum -c MANIFEST.sha256`. Rebuild: `python3 build_310.py` (from the repo root, with 3.1.0 absent).
