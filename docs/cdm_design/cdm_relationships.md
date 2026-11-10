# CDM Data Relationships — DRAFT 0.1.0

Entity-relationship documentation for the Human Microbiome Research CDM.
Entity-level detail: `template/cdm/human_microbiome_cdm.schema.json` (33 entities);
field-level bindings: `cdm_field_crosswalk.md`; inputs: `cdm_source_inventory.csv`.

## 1. Graph overview (textual ER)

```
PAPER 1──n SECTION 1──n PARAGRAPH / SENTENCE            (M1–M2)
PAPER 1──n STUDY                                         (M6)
PAPER 1──n SOURCE_ASSET                                  (M1)
PAPER 1──n DATASET 1──n DATA_ASSET                       (M10)
PAPER 1──n COHORT, SAMPLE, ASSAY, CLAIM                  (M6/M7 via paper_id FKs)
PAPER 1──n EXTRACTION_RUN (via run→paper coverage)       (M3)
PAPER 1──n VALIDATION_RESULT, HUMAN_REVIEW targets       (M9)

SECTION 1──n TERM_MENTION                                 (M4 evidence)
SECTION 1──n TERM_DEFINITION, DEFINITION_EVIDENCE          (M4/M8)
SECTION 1──n CLAIM (via evidence_section_id)              (M7/M8)

EXTRACTION_RUN 1──n MODEL_RUN                            (M3)
EXTRACTION_RUN → PROCESSING_LINEAGE → EXTRACTION_RUN     (M3 parent/child runs)
EXTRACTION_RUN 1──n TERM_MENTION / CLAIM / RELATION       (no row without a run)

TERM_OCCURRENCE 1──n TERM_MENTION                        (competing tags stay separate)
TERM_MENTION n──1 CANONICAL_TERM                          (M4→L3)
CANONICAL_TERM 1──n TERM_DEFINITION                      (M4)
CANONICAL_TERM 1──n TAXONOMY_ANNOTATION                  (M5)
CANONICAL_TERM 1──n TERM_CONCEPT_MAP n──1 CONCEPT         (M5; every candidate kept)
CANONICAL_TERM n──n RELATION (subject/object)            (M7 triples)

STUDY 1──n COHORT 1──n SAMPLE                            (M6)
STUDY 1──n ASSAY; ASSAY 1──n CLAIM (catalogue linkage)    (M6/M7)
CLAIM 1──n QUANTITATIVE_RESULT                            (M7)
CLAIM 1──n CLAIM_EVIDENCE                                 (M8; locator + status mandatory)
CLAIM n──n INTERVENTION (via exposure_or_comparison)      (M6/M7)

HUMAN_REVIEW n──1 (any entity)                           (M9; the only ACCEPTED/REJECTED gate)
VALIDATION_RESULT n──1 (PAPER | run | check target)      (M9)
EVALUATION_RUN n──n EXTRACTION_RUN (per model compared)   (M9)
DATASET_RELEASE 1──n (artifact manifest entries)          (M10)
```

## 2. Cardinality and identity rules (normative)

1. **PKs never re-minted.** Existing assigned IDs (HMPAPER, HMDATA…) and content-hash IDs
   (HMTERM, HMOCC, HMCTERM, HMDEF, HMMAP) are adopted as-is (template §3). Hashed ids are
   deterministic across reruns (sha1 of 0x1f-joined natural key parts, 16 hex) — an ingest
   that produces a new id for an unchanged row is a build error.
2. **PK pattern validation** at ingest: per-prefix regex (e.g. `^HMCTERM_[0-9a-f]{16}$`);
   malformed ids fail the build closed.
3. **TERM_MENTION is per-extractor**: (extraction_run_id, occurrence_key) is unique — same
   span from two models = two mention rows sharing one occurrence_key; never merged.
4. **CANONICAL_TERM uniqueness** is `(term_norm, cdm_type)`; `alternative_types` and
   `n_candidate_types` record type disagreement rather than resolving it silently.
5. **Every L2+ row** carries `extraction_run_id` (orphan check fails the build),
   an evidence locator or explicit no-evidence reason, and `text_version_id`.
6. **Claim evidence gate:** `text[char_start:char_end] == quote` at recorded text_version_id
   (from cdm_catalogue_schema.yaml rule 5, finding.schema.json evidence convention).
7. **Human-gate separation:** `evidence_locator_status` and `validation_status` are automated;
   `review_status`/`verification_status` change only via HUMAN_REVIEW rows (template §2 M9).
   ACCEPTED without a HUMAN_REVIEW row = build failure.
8. **Conflict retention:** contradictory findings, competing mappings, duplicate-group papers all
   kept; CONFLICTING is a value, never a deletion (catalogue rule: never auto-pick a side).

## 3. Join specification (physical keys)

| Join | On | Notes |
|---|---|---|
| papers ↔ sections | `(paper_id)` | composite section PK adds `section_id_original` |
| sections ↔ source asset | `source_file_hash_sha256` | asset provenance |
| findings ↔ studies | `(paper_id, study_id)` | catalogue adds dataset_id/cohort_id/assay_id columns |
| findings ↔ sections | `evidence_section_id` + text_version_id | locator integrity join |
| term_mentions ↔ sections | `(paper_id, section_id)` | sections keyed by section_id_original |
| term_mentions ↔ canonical_terms | `canonical_term_id` (HMCTERM) | many-mentions-per-canonical |
| term_mentions ↔ runs | `extraction_run_id` | orphan check |
| mappings ↔ concepts | `(ontology_name/vocabulary, concept_id)` | CONCEPT PK is (vocabulary, code) |
| cohorts/samples/assays ↔ papers | `paper_id` | catalogue tables |
| samples ↔ cohorts | `cohort_id` | nullable for standalone sample groups |
| catalogue findings ↔ corpus findings | `finding_id` shared id space | 22,439 ⊇ 21,395 — extra rows are catalogue study-level projections; both retained |
| evaluation evidence ↔ mentions | via model name + span + paper in ner_comparison_errors.jsonl | indirect (evidence-record based), adjudication adds explicit review rows |
| BP ↔ paper | bioproject accession, both directions | many-to-one tolerated; asymmetries (DUPLICATE_RECORD groups) flagged CONFLICTING |

## 4. Referential enforcement (per CDM validation spec)

- Ingest-time: PK-pattern regex per prefix; FK existence checks before commit; orphan
  TERM_MENTION/CLAIM rows (no run parent) quarantined to `_cdm_quarantine/`.
- Post-ingest: section span-integrity recheck (sampled or full); locator PASS/FAIL recount;
  per-run yield check against run manifests (fail-closed, template §2 M3).
- Release-time: MANIFEST sha256 verification (both `data_catalogue/MANIFEST.sha256` pattern
  and `MANIFEST_v1.txt` zenodo pattern are the precedents).
- Preencryption note: hashed IDs are content-addressed, so heavyweight migration can be
  re-verified by recomputing id hashes against the source rows — a corrupted/misjoined
  migration breaks the hash and fails the build, not silently ships.
