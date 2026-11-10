# CDM Validation Specification — DRAFT 0.1.0

Normative checks the CDM build must satisfy, in execution order. Every check is
fail-closed: a violation blocks the release rather than being silently patched.
Source bindings: `cdm_schema.json`; ER rules: `cdm_relationships.md` §2.

## V0 — Preconditions (before any ingest)

| Check | Rule | On failure |
|---|---|---|
| V0.1 Input manifests | every input listed in `cdm_source_inventory.csv` exists at the recorded path; MANIFEST sha256 files verify | abort ingest, quarantine batch |
| V0.2 Production immutability | input files' hashes match the snapshot at session start (esp. `paper_claims/_multi_ner_runs/*`, `data_catalogue/MANIFEST.*`, zenodo_v1) | abort — inputs changed under us |
| V0.3 PENDING/PROVISIONAL gating | inputs marked PENDING (stage 53/54+56 triples) or PROVISIONAL (running jobs 28607619, 28607825, 28608065) are ingested only as PROVISIONAL rows or excluded entirely | such rows must be traceable to a verified manifest before promotion |
| V0.4 Schema parse | `cdm_schema.json` + `template/cdm/human_microbiome_cdm.schema.json` parse and their PK patterns compile | abort (build error) |

## V1 — Identity layer (per row)

| Check | Rule | On failure |
|---|---|---|
| V1.1 PK pattern | every id matches its prefix regex (`^HMPAPER_[0-9]{6}$`, `^HMPAPER_[0-9]{6}_FIND_[0-9]{4}$`, `^HMPAPER_[0-9]{6}_STUDY_[0-9]{3}$`, `^HMTERM_`, `^HMOCC_`, `^HMCTERM_`, `^HMDEF_`, `^HMMAP_` + 16-hex, catalogue `HM*_[0-9]{6}`) | reject row to `_cdm_quarantine/`; never auto-reformat an id |
| V1.2 Hash recompute | HMTERM/HMOCC/HMCTERM/HMDEF/HMMAP ids equal the recomputed sha1 content-hash of their natural key parts (per `scripts/termpipeline/ids.py`) | quarantine row + flag ingest as corrupt — hash mismatch = misjoin, not a data fix |
| V1.3 No re-minting | ids already present in a prior release keep their values byte-identically | abort — re-minting violates template §3 |
| V1.4 Uniqueness | no duplicate PKs; `(term_norm, cdm_type)` unique in canonical_term | quarantine later arriving duplicate, record as CONFLICTING |

## V2 — Referential integrity

| Check | Rule | On failure |
|---|---|---|
| V2.1 FK existence | every FK (see `cdm_relationships.md` §3) resolves to an existing parent row | quarantine orphan; orphan counts go in release report |
| V2.2 Run parent | no term_mention / claim / relation row without an extraction_run parent | quarantine (orphan check, template §5) |
| V2.3 Section join | mention.section_id, definition.section_id, claim.evidence_section_id resolve to sections via `(paper_id, section_id_original)` | quarantine |
| V2.4 Text lineage | text_version_id on every L2+ row non-null and resolvable | quarantine |

## V3 — Evidence gates (span/locator integrity)

| Check | Rule | On failure |
|---|---|---|
| V3.1 Claim locator | `text[char_start:char_end] == evidence_text` at the recorded text_version_id | evidence_locator_status="FAIL" — kept, flagged, queued for review; never deleted |
| V3.2 Mention span integrity | `section_text_original[start:end] == surface_form` (sampled full if feasible, else per-section census mode) | mention kept; review_status=REVIEW_REQUIRED |
| V3.3 PubTator3 geometry | PubTator3 rows (original 300-paper run + 28608086 backfill) carry offsets 0,0 = paper-level geometry | fail if presented as section-level; geometry recorded on the run, not the row |
| V3.4 Offsets in range | all offsets within section/paper character counts | quarantine |
| V3.5 Definition spans | definition_char_start/end resolve inside their source section at text_version | review queue |
| V3.6 Claim count reconciliation | claim counts reconcile: catalogue findings.csv (22,439) vs corpus findings.jsonl (21,395) — extra rows identified (catalogue study-level projections) and accounted | unexplained rows → CONFLICTING |

## V4 — Provenance completeness

| Check | Rule | On failure |
|---|---|---|
| V4.1 Run metadata | every extraction_run has stage, version, timestamps, status; PROVISIONAL flag for in-flight jobs | reject |
| V4.2 Model registry | every (run, model) in model_run has a pinned version from canonical.yaml or run manifest | fail-closed |
| V4.3 Yield check | per-run row counts match run summaries/manifests (e.g. 28608086: 2,699 backfill rows; zenodo manifests; 28608068 parse yield 1.00000 × 8) | run marked FAILED + children quarantined |
| V4.4 Review-gate separation | automated fields (validation_status, evidence_locator_status) never hold review values; review/verification fields change only with a HUMAN_REVIEW row | build failure — gate violation (template §2 M9) |
| V4.5 Terminology backfill provenance | backfill rows trace to job 28608086 via extraction_run; per-paper resolution status (pmid_direct 142 / doi 1 / title 1 / OK 134 / zero 6 / no_pmid 9 / error 4) re-derives from status.jsonl | reject |

## V5 — Semantic/vocabulary checks

| Check | Rule | On failure |
|---|---|---|
| V5.1 Enum vocab | mapping_disposition, mapping_relation, review_state, verification_state, missing-data vocab all match schema const lists | reject row |
| V5.2 Type disagreement | canonical_term keeps alternative_types + n_candidate_types; never collapses to the modal type silently | — (recordkeeping by design) |
| V5.3 Conflicts retained | duplicate_group papers, contradictory findings, competing candidates all present; CONFLICTING is a value | fail if any conflict-resolution deleted rows |
| V5.4 Known quirks documented | p-shaped effect_estimate (~1,088: 849 duplicate-p + 239 sole-p), 121 malformed llm_terms, hypernym taxa, off-schema types, 12.4% paraphrase, HMPAPER_000268 failure, HMPAPER_000239 anomaly, canonical_terms first-record n_papers=2092 oddity — all carried as documented caveats | release report must enumerate them |
| V5.5 Taxonomy agreement | term_taxonomy_v1 category/subcategory bindings and canonical_terms taxonomy fields agree for sampled terms | CONFLICTING + review queue |

## V6 — Release checks

| Check | Rule | On failure |
|---|---|---|
| V6.1 Full recount | table counts reconcile with `cdm_source_inventory.csv` counts up to allowed transformations (view-only derivations, join-row expansion) — discrepancy explained in release report | block release |
| V6.2 Coverage report | PubTator3 coverage stated as 434/453 (300 original + 134 backfilled; 9 no-PMID + 6 zero-annotation + 4 transient-error outstanding) | — |
| V6.3 Manifest emission | release ships MANIFEST.json + sha256 per artifact (data_catalogue precedent), plus JSONL mirrors per entity | block release |
| V6.4 Reproducibility | ingesting the same snapshot with the same code yields byte-identical HM* id sets (deterministic hashes) | investigate before release |
| V6.5 No accuracy claims | metrics tables carry agreement framing only; accuracy language gated on adjudication (human review) | edit report language |

## Quarantine review procedure

`_cdm_quarantine/` rows are triaged by a human: re-ingest after source fix,
re-classify as CONFLICTING, or confirm rejection. Quarantine never auto-deletes.
