# CDM Schema Proposal — DRAFT 0.1.0

Proposed logical schema for the Human Microbiome Research CDM, derived from the
reconciled template (`template/cdm/`, DRAFT 0.1.0) and the verified source inventory
(`cdm_source_inventory.csv`). This is a **design-phase proposal**: no migration is
implemented here. Field-level source bindings: `cdm_field_crosswalk.md`.

## 1. Design decisions

| # | Decision | Rationale |
|---|---|---|
| D1 | Logical: 33 entities in 10 modules over 5 layers (template §1–2) | reconciliation of the five existing template artifacts; every existing id scheme adopted as-is |
| D2 | Physical: SQLite single DB + per-entity JSONL mirrors | proven project pattern (two legacy CDM DBs, 9–12 tables; releases = files + sha256 manifests); no server dependency; sqlite3 CLI everywhere |
| D3 | Identity: termpipeline content-hash layers (HMTERM/HMOCC/HMCTERM/HMDEF/HMMAP) + assigned catalogue/paper IDs, never re-minted | template §3; recompute-verifiable migration |
| D4 | Every L2+ row requires an EXTRACTION_RUN parent + locator + text_version_id | provenance contract, template §5 |
| D5 | Review states separate from automated validation states; HUMAN_REVIEW is the only resolution mechanism | template §2 M9; no model treated as ground truth |
| D6 | All model outputs preserved side by side; conflicts are values (CONFLICTING), not deletions | user requirement; catalogue rule |
| D7 | OMOP reconciliation at vocabulary layer only (CONCEPT/TERM_CONCEPT_MAP + 8 OMOP-style tables per cdm_schema_alignment.py phase 2); internal HM* PKs everywhere | template §6; no reshaping of the source of truth |
| D8 | Ingest adopts – never rewrites – source rows; derived artifacts (dedup, catalogue views) are views or child-run products with lineage | no destruction of records (template §5) |

## 2. Proposed tables (logical → physical SQLite)

Per module, with row-scale estimates from the verified inventory:

### M1–M2: corpus backbone
```
paper               (453)          PK paper_id
source_asset        (~1,359)       PK (paper_id, path, hash) from source_inventory
section             (4,006)        PK (paper_id, section_id_original)
paragraph           (derive)       PK paragraph_id = section:sN form
sentence            (derive)       PK sentence_id
section_segment     (4,006→n)      chunk geometry from segments.jsonl
```

### M3: processing
```
extraction_run      (n≈25+ known; PENDING inventory)   PK run_id
model_run           (per model×run)                     PK (run_id, model)
processing_lineage  (edges)                             PK (parent, child, relation)
```
Known run families to inventory: zenodo_v1 section CPU runs (SLURM 418086), Qwen section
run (418089), legacy paper-level multi-NER (`_multi_ner_runs`), PubTator3 original +
backfill (28608086), termpipeline chain T1–T9, termpipe-v1 (28608065, pending),
cv-link (28607619, running), llm-ner-body (28607825, running), stage 53/54 (28607588
pending), stage 56 (28607924, dependency), corpus_v2 stages, NER eval runs (28608068).
PROVISIONAL rows for in-flight jobs; verified on manifest check.

### M4: terminology spine
```
term_mention        (~1.8M raw → assembled)  PK mention_id HMTERM_
term_occurrence     (subset of mentions)      PK occurrence_key HMOCC_
canonical_term      (166,012)                 PK term_id HMCTERM_
term_definition      (59 smoke → full-scale)   PK definition_id HMDEF_
```

### M5: mappings
```
concept             (verified external only)             PK (vocabulary, concept_code)
term_concept_map    (30,533 chain → cv-link full)        PK mapping_id HMMAP_
taxonomy_annotation (166,012 bindings)                   PK (term_id, taxonomy_version)
```

### M6: research context
```
study               (453)      PK study_id HMPAPER_*_STUDY_NNN
cohort              (9,575)    PK cohort_id HMCOHORT_
sample              (8,484)    PK sample_group_id HMSAMPLE_
assay               (12,116)   PK assay_id HMASSAY_
body_site           (registry) PK body_site_id (label key)
intervention        (registry) PK intervention_id (label key)
```

### M7–M8: findings & evidence
```
claim               (21,395 corpus; catalogue projection 22,439)  PK finding_id
quantitative_result (per-claim stats)                             PK (finding_id, stat_key)
claim_evidence      (per-claim locator+quote+status)              rides on claim rows
relation            (PENDING stage 53/54+56)                      PK relation_id (to mint per triple schema)
claim_intervention  (join table)                                  exposure/comparison links
```

### M9: quality & review
```
validation_result   (453 paper + 4,006 section + catalogue integrity)  PK (check, target, run)
human_review        (PLANNED: 735 adjudication + sample-type queue)     PK review_id
evaluation_run      (28608068 per-model comparison + prior runs)        PK evaluation_run_id
```

### M10: catalogue & releases
```
dataset             (3,228)                      PK dataset_id HMDATA_
data_asset          (2,143)                      PK asset_id HMASSET_
dataset_release     (frozen snapshots)            PK release_id + MANIFEST sha256
dataset_paper       (join)                       catalogue papers↔datasets
```

## 3. Entity folds (33 logical entities → 22 physical tables)

Per registry (`template/cdm/cdm_entity_registry.csv`), 11 entities are carried
*within* other tables rather than dropped:

| Folded entity | Carried by | Rationale |
|---|---|---|
| PARAGRAPH, SENTENCE | `section` geometry (+ `paragraph_id`/`sentence_id` refs on mentions/definitions) | derivable from section_text_original + offset_convention; no independent facts |
| PROCESSING_LINEAGE | `extraction_run` hash-pair edges (input/output_artifact_hash, parent/child runs) | edges are run attributes; proposal §2 M3 |
| TERM_OCCURRENCE | `term_mention.occurrence_key` (HMOCC_, extractor-independent) | one column carries the dedup identity; competing mentions share it |
| TAXONOMY_ANNOTATION | `canonical_term.taxonomy_category/subcategory` | 1:1 with canonical term at taxonomy version |
| BODY_SITE, INTERVENTION | registries as constraint-backed value sets on study/sample/claim fields | labels only; CONCEPT rows appear only via validated mappings |
| QUANTITATIVE_RESULT | `claim` stat columns (effect_measure…q_value) | 1:1 with claim extraction row; verbatim + quirk annotation |
| CLAIM_EVIDENCE, MENTION_EVIDENCE, DEFINITION_EVIDENCE | evidence columns riding their parent rows (locator + status + quote) | evidence is inseparable from its mention/claim; gate V3 checks it in place |

Nothing is deleted by folding: every folded field appears in `cdm_schema.json`
with its source binding; the fold is a physical-layout choice, revisitable at
build time if analytics need them as separate tables.

## 4. OMOP compatibility layer (phase 2 of cdm_schema_alignment.py)

Eight OMOP-style tables as *views over* the CDM tables (D7), keyed to OMOP-compatible
vocabularies where genuinely present (omop_local index, UMLS, MeSH: fields
`omop_domain`, `omop_concept_class`, `omop_standard`, `standard_concept_id` already
exist in term_ontology_mappings.jsonl): CONCEPT, DOMAIN, VOCABULARY,
CONCEPT_RELATIONSHIP, CONCEPT_ANCESTOR, CONCEPT_SYNONYM, SOURCE_TO_CONCEPT_MAP,
CDM_SOURCE. Views are rebuilt, never migrated into; the source of truth keeps HM* PKs.

## 5. Index & integrity plan

- PK + FK indexes on every join column listed in `cdm_relationships.md` §3.
- NOT NULL: PK fields, `extraction_run_id` on L2+ rows, locator fields on evidence rides.
- CHECK constraints: pk patterns per prefix (regex-lite via triggers), review_state vocab,
  mapping_disposition vocab, missing-data vocab (never 0).
- Content-hash re-verification path: recompute HM* hashes from source rows at ingest
  (template "traceability milestone" requirement); mismatch → quarantine, not fix.

## 6. Open design questions (for review, not decided here)

1. `relation_id` minting scheme for RELATION rows once stage 53/54 lands (follow
   triple_relation_schema.json pattern vs termpipeline hash style) — propose hash style
   for consistency, pending the actual triple_mentions.jsonl fields.
2. Whether PARAGRAPH/SENTENCE get physical tables (needed for definition/mention evidence
   granularity) or remain derivable from section text + offset conventions.
3. Omop CDM_SOURCE content (project provenance block) — draft in validation spec.
4. Whether the two legacy microbiome_cdm.db files ship as DATASET_RELEASE rows
   (superseded lineage) or stay flagged migration-input-only (current proposal: the latter).
5. catalogue_records.jsonl ingestion (83 MB, 56,985 lines vs 51,941 records) — parse and
   ingest record-wise, keeping line-level JSON-parse failures as CONFLICTING row states.

## 7. What this proposal deliberately does NOT do

- No migration, no writes to production outputs (design phase only).
- No new extractions beyond the already-approved PubTator3 backfill run (28608086,
  completed: 134/153 papers recovered → coverage 434/453; original outputs untouched).
- No accuracy claims anywhere — those remain gated on adjudicated human review.
