# Human Microbiome Research CDM — Master Design Template

Version 0.1.0 (DRAFT — design phase). Companion files in `template/cdm/`:
`README.md` (inheritance rules), `human_microbiome_cdm.schema.json` (machine-readable
entity registry), `cdm_entity_registry.csv` (one row per entity).

This template reconciles the project's existing template artifacts into one CDM
design. It defines **what a CDM record must contain and prove**, not how it is
physically stored. Field-level definitions are inherited from the sources listed
in `README.md` and are never restated here — the field-level crosswalk
(`cdm_field_crosswalk.csv`, a design-phase deliverable) binds existing fields to
CDM fields record-by-record.

---

## 1. Layered architecture

| Layer | Name | Contents | Populated from (primary sources) |
|---|---|---|---|
| L1 | Source corpus | Papers, sections, paragraphs, source file hashes, raw payloads | `corpus_v2/data/` (papers, sections, segments, source_inventory), `papers_txt/`, `segmented_sections_markdown/` |
| L2 | Extraction & evidence | NER mentions (every model), Qwen mentions, definitions, triples, findings, extraction runs | `zenodo_v1/ner_453_sections/`, `zenodo_v1/qwen_sections_ner/`, `paper_claims/_multi_ner_runs/`, termpipeline `term_mentions.jsonl` / `term_definitions.jsonl`, `corpus_v2/data/findings.jsonl`, triple outputs |
| L3 | Canonical research entities | Canonical terms, deduplicated term registry, taxonomy annotations | termpipeline `canonical_terms.jsonl` (166,012), `data/catalogue/terminology_dedup.csv`, `term_taxonomy_v1` |
| L4 | CDM facts with mappings | Ontology-mapped terms, studies, cohorts, samples, assays, relations, quantitative findings | termpipeline `term_ontology_mappings.jsonl`, `corpus_v2/data/studies.jsonl`, `data_catalogue/tables/`, findings + triples |
| L5 | Validation & releases | Validation results, human review, evaluation runs, release manifests | `corpus_v2/validation/`, `data_catalogue/quality/`, HUMAN_REVIEW (new), `data_catalogue/MANIFEST.json` + `.sha256` |
| — | Catalogue & lineage (cross-layer) | Datasets, data assets, processing lineage, releases | `data_catalogue/records/catalogue_records.jsonl`, `corpus_v2/data/processing_events.jsonl`, `curation_log.csv` |

The catalogue documents all five layers; it never duplicates their content
(README rule 8).

## 2. Module registry

Ten modules. Entity-level detail in `human_microbiome_cdm.schema.json` and
`cdm_entity_registry.csv`.

### M1 Source documents — `PAPER`, `SOURCE_ASSET`
Per-paper bibliographic and source identity, described by the master corpus
record. Primary key `paper_id` (`HMPAPER_[0-9]{6}`). Integrity fields (hashes,
completeness enums, availability) are kept separate and never inferred from one
another (paper.schema.json rule). Populated from `corpus_v2/data/papers.jsonl`
(453 papers).

### M2 Document structure — `SECTION`, `PARAGRAPH`, `SENTENCE`
Full-text hierarchy that carries all evidence locations. Character offsets in
this corpus index `section_text_original` — the only stable text geometry for
the frozen corpus (verified during NER-evaluation work; `section_text_cleaned`
is null). Join keys for sections are `(paper_id, section_id_original)`; the
`section_id` field does not exist in `sections.jsonl`.

### M3 Processing — `EXTRACTION_RUN`, `MODEL_RUN`, `PROCESSING_LINEAGE`
One EXTRACTION_RUN per Slurm execution or pipeline invocation: run id, model +
version, prompt version (for LLM runs), corpus-coverage statistics, elapsed
time, parameter hashes. PROCESSING_LINEAGE records parent–child edges — for
example, a section-level run of a model and the paper-level run of the same
model family are **distinct runs with different geometry**, and the lineage
edge between them must be persisted, not narrated.

**Model-NER preservation rule.** Every model's original predictions are
preserved row-for-row. Competing tags of the same span from different models
remain separate mentions (`mention_id` hashes the `run_id`; two models' tags of
one span never merge).

**Fail-closed run rule.** If a run's parsed row yield or totals mismatch its
run summary, the run is `FAILED`, its outputs quarantined, and any release it
feeds becomes `REVIEW_REQUIRED` — never silently accepted. (Implemented
practice: `parse_check` in the NER evaluation manifest; reproduction tolerance
codified in its stats JSON.)

**Provisional runs.** In-flight jobs (cv-link 28607619 mapping 36,475 terms;
llm-ner-body 28607825 re-running Qwen body NER over 160 segments; the
pubtator3 backfill 28608086) enter the run inventory as `PROVISIONAL` and are
excluded from CDM production tables until their summaries/manifests verify.

### M4 Terminology — `TERM_MENTION`, `CANONICAL_TERM`, `TERM_DEFINITION`
The terminology spine, adopting the termpipeline identity layers as-is:
`TERM_MENTION` (`HMTERM_*`, one row per extractor's tag of one span),
`CANONICAL_TERM` (`HMCTERM_*`, content-hash of `(term_norm, cdm_type)`),
`TERM_DEFINITION` (`HMDEF_*`). Identity layers are never merged. Source-derived
and external definitions are distinct provenance classes (`provenance_class`:
SOURCE_DERIVED | EXTERNAL). `definition_status` rides on the canonical term;
`n_papers`, `n_models`, `n_observations` are observed counts, never a ranking.

Coverage note: the current chain run (`results/_termpipe_chain/`) is
manifest-verified but **smoke-capped** in parts (T1 mentions capped 2,000
rows/source; T3 definitions capped 30 papers; T2 canonical terms uncapped at
166,012). The full-scale termpipe-v1 run (job 28608065, pending) lifts the caps.
The CDM ingest records each run's coverage status; only manifest-verified
full-scale runs populate production tables.

### M5 Semantic mappings — `CONCEPT`, `TERM_CONCEPT_MAP`, `TAXONOMY_ANNOTATION`
`CONCEPT` holds only verified external identifiers (UMLS CUIs, OMOP concept
ids, NCBI taxon ids, MeSH) with their source vocabulary — never fabricated.
`TERM_CONCEPT_MAP` is per-candidate (termpipeline keeps every candidate with
`candidate_rank`; `is_canonical_candidate` and `mapping_disposition`
ACCEPTED / CANDIDATE / REJECTED / UNRESOLVED / REVIEW_REQUIRED distinguish
accepted from candidate). Mapping relations are one of EXACT, EQUIVALENT,
BROADER, NARROWER, RELATED, UNRESOLVED, REJECTED. `TAXONOMY_ANNOTATION` binds
canonical terms to the project term taxonomy (16 categories / 66 subcategories)
— taxonomy categories are project labels, not external CONCEPTs.

### M6 Research context — `STUDY`, `COHORT`, `SAMPLE`, `BODY_SITE`, `INTERVENTION`
`STUDY` from `corpus_v2/data/studies.jsonl` (key `HMPAPER_*_STUDY_NNN`);
`COHORT`, `SAMPLE`, assay-adjacent fields from `data_catalogue/tables/`
(cohorts 9,501; samples 8,421; assays 12,060). BODY_SITE and INTERVENTION are
normalized labels (e.g. `sample_type_normalization.json` vocabulary) — they
become CONCEPT rows only if separately mapped to an external vocabulary.

### M7 Scientific findings — `CLAIM`, `RELATION`, `QUANTITATIVE_RESULT`
`CLAIM` populated from `findings.jsonl` (claim_type, direction + what it refers
to, effect measure/estimate, p/q values, CIs, covariates, sample size, evidence
locator + `evidence_locator_status`). `RELATION` from validated triple outputs
(stage 53/54 pending; leave-K-out evidence suggests ~28% full-triple recovery
— recorded as a limitation, not a success claim). Claim-level evidence quote
integrity: `text[char_start:char_end] == quote` at the recorded `text_version_id`
(inherited from cdm_catalogue_schema.yaml rule 5; enforced by
`evidence_locator_status`). Null results, negative results, and contradictory
statements are all retained; polarity and uncertainty are captured, never
"corrected".

Known quirk to carry, not fix: ~1,088 findings carry p-value-shaped
`effect_estimate` values (849 duplicating `p_value`, 239 sole) — documented in
release notes and review commentary.

### M8 Evidence family — `CLAIM_EVIDENCE`, `MENTION_EVIDENCE`, `DEFINITION_EVIDENCE`
Evidence locator, embedded quote (`supporting_sentence` / `evidence_text`),
locator status, and `text_version_id` always ride together on the record they
evidence — no CDM record points at evidence without a locator status.
`evidence_locator_status` is the automated gate; `verification_status` /
`review_status` is the human gate; they are deliberately separate fields and
neither implies the other.

### M9 Quality & review — `VALIDATION_RESULT`, `HUMAN_REVIEW`, `EVALUATION_RUN`
`VALIDATION_RESULT` from automated checks (per-paper validation, section
span-integrity checks, catalogue integrity report, run yield checks).
`HUMAN_REVIEW` is the **only** mechanism that moves `review_status` from
UNVERIFIED / REVIEW_REQUIRED to ACCEPTED / REJECTED, and requires reviewer,
date, decision, notes. `EVALUATION_RUN` records model-comparison metrics and
evidence samples (e.g. `results/28608068_ner_eval_permodel/`); evaluation
numbers never flow backward into extraction rows. Evaluation-derived error
records (false-positive candidates such as author names tagged ORGANISM,
span-boundary mismatches, paraphrase-not-in-text qwen terms) enter the review
queue as HUMAN_REVIEW candidates referencing the evidence JSONL — evaluation
never annotates the underlying NER rows directly.

**Review-state machine.** `review_status`: UNVERIFIED → REVIEW_REQUIRED →
ACCEPTED / REJECTED (terminal); findings `verification_status`: pending →
human_verified / needs_revision. Automated checks can set locator/validation
statuses and *raise* REVIEW_REQUIRED, never resolve it. Any ACCEPTED without a
matching HUMAN_REVIEW row fails the build.

**Per-build state reporting.** Every CDM build report must include counts by
review state (UNVERIFIED / REVIEW_REQUIRED / ACCEPTED / REJECTED), findings
verification_status distribution, mapping dispositions (accepted vs candidate
vs rejected), per-run parse yields, span-integrity pass rates, evidence-locator
PASS/FAIL counts, and release-status distribution (COMPLETE / PARTIAL / FAILED
/ REVIEW_REQUIRED). Any 100%-verified claim must name its review evidence.

### M10 Catalogue & releases — `DATASET`, `DATA_ASSET`, `DATASET_RELEASE`
From `data_catalogue/tables/` (papers 453, datasets 3,209, data_assets 2,143,
cohorts 9,501, samples 8,421, assays 12,060, findings 16,607) with their
`HMDATA_/HMASSET_/…` sequential stable IDs. `catalogue_records.jsonl` is the
row-level source of truth with provenance; `tables/*.csv` are derived views;
the CDM catalogues these, never redistributes the records. `DATASET_RELEASE`
rows are frozen snapshots with sha256 manifests (existing pattern:
`data_catalogue/MANIFEST.json` + `MANIFEST.sha256`).

## 3. Identifier scheme (consolidated registry)

Existing identifier regimes are both adopted as-is. No identifier is ever
re-minted or re-hashed; the crosswalk maps existing IDs to CDM primary keys.

| ID pattern | Entity | Scheme source | Nature |
|---|---|---|---|
| `HMPAPER_[0-9]{6}` | PAPER | corpus_v2 schema | Assigned, stable |
| `HMPAPER_*_STUDY_[0-9]{3}` | STUDY | study.schema.json | Assigned, stable |
| `HMPAPER_*_FIND_[0-9]{4}` | FINDING/CLAIM | finding.schema.json | Assigned, stable |
| `HMTERM_[0-9a-f]{16}` | TERM_MENTION | termpipeline ids.py | Content-derived hash (includes run_id) |
| `HMOCC_[0-9a-f]{16}` | occurrence key | termpipeline ids.py | Content-derived hash (extractor-independent) |
| `HMCTERM_[0-9a-f]{16}` | CANONICAL_TERM | termpipeline ids.py | Content-derived hash of (term_norm, cdm_type) |
| `HMDEF_[0-9a-f]{16}` | TERM_DEFINITION | termpipeline ids.py | Content-derived hash |
| `HMMAP_[0-9a-f]{16}` | TERM_CONCEPT_MAP | termpipeline ids.py | Content-derived hash |
| `HMDATA_/HMASSET_/HMCOHORT_/HMSAMPLE_/HMASSAY_/HMFINDING_[0-9]{6}` | Catalogue entities | data_catalogue template | Assigned sequentially, stable |
| run id (Slurm job id / manifest id) | EXTRACTION_RUN | run manifests | Assigned per execution |

ID validation uses per-prefix regexes. Hashed ids are pure functions of content
(sha1 over 0x1f-joined parts, 16 hex chars) — deterministic across reruns by
design (termpipeline ids.py, adopted unchanged).

## 4. Data-value conventions (inherited)

- `null` = not yet extracted (unknown) — never reinterpreted as absence.
- `NOT_REPORTED` = checked and explicitly absent.
- `NOT_APPLICABLE`, `NOT_ACCESSIBLE`, `CONFLICTING` per the data-catalogue
  template missing-data vocabulary.
- Never numeric zero as missing; never infer a value from context; keep author
  wording in `*_original` / `*_raw` fields alongside normalized values.
- Missing data is separate from failed processing: a failed stage sets
  `extraction_status` and quarantines outputs; it never silently drops rows.

Normalization disciplines (never mixed):
- `term_norm` / `normalized_mention`: alnum-collapse lowercase (`canon_norm`) —
  the identity normalization, used for canonical keys and exact-dedup joins.
- `word_norm`: fuzzy-dedup key only — never used for entity identity joins.
- The crosswalk must state, for every field carrying a surface-form value,
  which normalization applies.

## 5. Evidence & provenance contract (per record)

Every L2+ record carries, minimally:
- `extraction_run_id` → EXTRACTION_RUN (no row without a run; orphans fail the
  build)
- an evidence locator (paper + section + character offsets, or sentence id), or
  an explicit no-evidence flag with reason (e.g. PubTator3 paper-level rows
  carry offsets 0,0 by construction — that limitation is recorded on the run,
  not hidden per-row)
- `text_version_id` for the text geometry its offsets index
- `extraction_method` plus model and prompt version for LLM runs
- the review/validation status pair (automated + human — separate fields)
- its canonical link (`canonical_term_id`, `definition_status`) where applicable

Every join into a richer CDM view is a view, never a merge that destroys
underlying records.

**Run-inventory complete rule.** The EXTRACTION_RUN table must list every
discovered run, including: zenodo_v1 section runs (7 CPU models + Qwen), the
original paper-level multi-NER runs, the PubTator3 paper-level run (300-paper
coverage, title-lookup-only) and its backfill run (job 28608086, PMID→DOI→title
strategy, 153 papers), the ollama comparison runs, the termpipeline chain
(T1–T9) and full termpipe-v1, stage 53/54 triple runs, llm-ner-body (28607825),
and all corpus_v2 stages. Section-level and paper-level runs of the same model
family are separate runs (different geometry, different limitations) linked by
a PROCESSING_LINEAGE edge.

**Known join anomaly to encode as a check.** BioProject↔paper is many-to-one
in places (DUPLICATE_RECORD studies sharing publications; duplicate_group_id /
canonical_paper_id exist on papers). The CDM stores both BP→paper and
paper→BP mappings and flags asymmetries as CONFLICTING for human review —
catalogue rule: the catalogue never picks a side automatically.

## 6. Standards interoperability (OMOP posture)

Reuse where legitimate:
- OMOP vocabulary infrastructure for accepted mappings: CONCEPT, DOMAIN,
  VOCABULARY, CONCEPT_RELATIONSHIP, CONCEPT_ANCESTOR, CONCEPT_SYNONYM,
  SOURCE_TO_CONCEPT_MAP, CDM_SOURCE — per
  `src/cdm_pipeline/cdm_schema_alignment.py` phase 2 (8 OMOP-style tables).
- OMOP concept identifiers are kept only where genuinely present in the
  downloaded vocabularies / mapping services (omop_local index, UMLS,
  BioPortal, OLS, NCBI Taxonomy); never fabricated, never forced.

Microbiome-specific extensions OMOP cannot represent (kept in the research
CDM's own structures):
- paper-level scientific CLAIMs with evidence passages and locator status
- per-extractor NER mention preservation with competing predictions
- strain-level taxa findings (NCBI taxon + strain)
- sampling and laboratory workflow attributes (studies.jsonl methods block)
- association vs causal claims, polarity, uncertainty, contradictory findings
  (both retained)
- literature-derived QUANTITATIVE_RESULTs with effect/p/q/CI values and their
  quirks

Structural rule: internal stable IDs (HM*) are primary keys everywhere; OMOP
concepts appear only inside TERM_CONCEPT_MAP / CONCEPT rows with validated
relations. OMOP-compatible export views can be built later from the same
tables; the source of truth never reshapes to fit OMOP.

## 7. Physical implementation recommendation

| Engine | Pros | Cons |
|---|---|---|
| SQLite single DB | proven in this project (two CDM DB lineages, 9–12 tables); file = release artifact with sha256 manifest; read-only distribution; sqlite3 CLI everywhere | weak concurrency; SQL dialect limits |
| SQLite per-module DBs | mirrors logical modules; per-module artifacts | cross-file joins need ATTACH; more files to manifest |
| DuckDB + Parquet (analytical layer) | fast columnar queries; serverless | unproven in project; new dependency |
| PostgreSQL | real concurrency, mature | needs a server; against in-repo artifact storage conventions |

Recommendation: **SQLite single DB as the physical CDM, JSONL mirrors per
entity** as the interchange/recovery format (both already project conventions;
releases are frozen files with manifests; jobs run under Slurm against paths,
not services). Rebuild the physical DB each release; the logical schema stays
the contract. DuckDB/Parquet can layer on later for analytics without touching
the release artifacts.

## 8. Traceability milestone (the "one finding end-to-end" test)

The first milestone, before any full migration: a small set of papers where a
single scientific finding traces through the entire system — original full-text
passage → NER mentions from each system (kept separate) → canonical term with
source-derived definition → controlled-vocabulary mapping with explicit
relation and disposition → triple/relation with polarity → study and sample
context → validation results → review status → final CDM record + release
metadata — with no lost provenance, no silently merged competing outputs, and
no dropped fields. If that trace fails, the architecture is not ready to scale.

## 9. Design-phase deliverables that must agree with this template

`cdm_source_inventory.csv`, `cdm_schema_proposal.md`, `cdm_schema.json`,
`cdm_field_crosswalk.csv`, `cdm_relationships.md`,
`cdm_validation_specification.md`, `cdm_migration_risks.md`,
`cdm_architecture_report.md` — the design-phase set. This template is their
normative reference for identifiers, conventions, gating, and interoperability.
