# Terminology Extraction + Definition Extraction + CV Linking — Implementation Plan

Status: DRAFT (2026-10-23)
Task spec: "Human Microbiome NER, Terminology Extraction, Definition Extraction, and Controlled-Vocabulary Linking"

This plan maps the spec's five stages and nine required artifacts onto assets that
**already exist** in the working tree, and marks precisely what must be built.
It is written *before* implementation so nothing is duplicated or clobbered.

---

## 1. Actual inputs (discovered, not assumed)

| Input | Path | Shape |
|---|---|---|
| Section-segmented full text | `segmented_sections_markdown/HMPAPER_*.md` | 453 files, 4,006 section units (`SECTION_ID`/`SECTION_PATH`/`SEGMENT` comments) |
| CPU section universe | `cdm_pipeline.ner.runner_sections.load_sections(body_only=True)` | 453 papers / 2,817 units / 20,904,249 body chars |
| CPU ensemble NER | `zenodo_v1/ner_453_sections/all_ner_sections_combined.csv` | 1,705,501 rows, 7 models (one is generic-`ENTITY`-only) |
| Qwen section NER (historical) | `zenodo_v1/qwen_sections_ner/` (Ollama, Cell-7c rule) | 186,024 rows |
| Qwen section NER (new, body) | `results/llm_ner_body/` (vLLM, `--section_filter body`) | job `28607825` (re-run; cache complete) |
| Deduplicated terminology | `data_catalogue/terminology/terminology_dedup.csv` | 166,012 terms (`term,term_norm,cdm_type,all_types,models,source_names,n_models,n_observations,n_papers`) |
| Catalogue entity records | `data_catalogue/records/catalogue_records.jsonl` | 56,985 records, **with `char_start`/`char_end`** → mention-level offsets already exist for this subset |
| Taxonomy v1 | `taxonomy/term_taxonomy_v1.yaml` + `data_catalogue/terminology/taxonomy/term_taxonomy_v1.{yaml,csv}` | version 1.0.0, DRAFT, 16 upper categories + `UNCERTAIN` reserved |
| CV links (in flight) | `results/cv_linking/` | job `28607619` (36,475 net-new pairs) |
| OMOP links | `results/omop_linking/` | 9,615 pairs, 21,881 links |
| MeSH gazetteer | `results/mesh_ner/` | 248,088 rows, 8,652 distinct terms |
| Local OMOP vocabulary | `results/omop_vocab/omop_index.sqlite` (5.68 GB) | `concept` 10,167,185 / `term` 15,647,137 / `maps_to` 7,423,177 |
| Correlation corpus bundle | `data_catalogue/` (155 MB) | prior deliverable — extend, do not clobber |

### Corpus-policy gaps to record honestly
- Full-text availability is **not** 453/453: 435/453 papers `READY`, 18 `BLOCKED`
  (abstract-only/partial). The corpus manifest (`data/corpus/corpus_tracking.csv`,
  `manifests/`) is the authority for eligibility, not the presence of a `.md`.
- `corpus_pipeline` stages 06 (JEV), 11 (embeddings/dense) are **not** run. Not required
  for terminology extraction, but the manifest must say so.
- Supplementary text is included only where section segmentation captured it; that
  must be reported as a known limitation, not silently assumed complete.

---

## 2. Stage-by-stage disposition

### Stage 1 — NER (mention extraction)
**Reuse.** The CPU ensemble + Qwen sections + MeSH gazetteer are the NER sources.
**Gap.** No single mention-level artifact unifies them with canonical offsets, a
stable `mention_id`, sentence/paragraph ids, and a per-mention `extraction_run_id`.
**Build:** `scripts/termpipeline/assemble_mentions.py` → `term_mentions.jsonl`.
- `mention_id` = deterministic `HMTERM_<sha1(paper|section|start|end|norm)>[:16]`
  (stable across reruns; distinct occurrences with different offsets stay distinct).
- Offsets come from the NER row `char_start`/`char_end` (CPU, Qwen, MeSH all carry them).
- `sentence_id`/`paragraph_id` derived deterministically from offsets against the
  section text (no fabrication; null when unresolvable).
- `supporting_sentence` = exact substring slice; `review_status` default `UNVERIFIED`.
- **No new model calls** — this is assembly over existing outputs.

### Stage 2 — Normalization / canonicalization
**Reuse.** `export_terminology.norm_term`, `terminology_dedup.csv` (already
fuzzy/embedding-deduplicated with a protected-taxon rule), `taxonomy.py` validators.
**Gap.** Canonical terms artifact with `identity_evidence`, `alternative_labels`,
`mention_count`, `paper_count`. `terminology_dedup.csv` lacks mention rollups.
**Build:** `scripts/termpipeline/build_canonical_terms.py` → `canonical_terms.jsonl`.
- `term_id` = deterministic from `(term_norm, cdm_type)` — the existing dedup key.
- Homonym guard: a surface form with >1 `cdm_type` yields **one term per type**
  (never a silent merge); flagged `identity_evidence = "multi_type_surface_form"`.
- Keep `all_types` as `alternative_types`; never collapse gene/protein/disease pairs.
- **Must not overwrite** `terminology_dedup.csv`; write alongside + emit a
  reconciliation note.

### Stage 3 — Definition extraction  ← **largest genuine gap**
**Reuse.** None adequate. `scripts/catalogue/llm_term_definitions.py` is
**disqualified**: it *generates* definitions from model knowledge via Ollama, i.e. it
is not source-grounded and the spec explicitly forbids conflation/fabrication.
**Build:** `scripts/termpipeline/extract_definitions.py` → `term_definitions.jsonl`.
- **Source-derived (P0, CPU, regex + rules, no LLM):**
  `EXPLICIT_AUTHOR_DEFINITION` (`X is defined as`, `X refers to`, `X denotes`),
  `ABBREVIATION_EXPANSION` (existing abbreviation patterns; reuse any in
  `cdm_pipeline`), `GLOSSARY_DEFINITION` (definition-looking sections),
  `CONTEXTUAL_DESCRIPTION` (appositive `X, a …`).
  Text is copied verbatim from the section slice + offsets; **nothing is generated**.
- **External (P1):**
  `UMLS_SOURCE_DEFINITION` / `BIOPORTAL_DEFINITION` / `OLS_ONTOLOGY_DEFINITION`
  via existing mappers (see Stage 5); `OMOP_CONCEPT_DESCRIPTION` is **expected to be
  unavailable** — the local bundle has **no definition table** (only `CONCEPT`,
  `CONCEPT_SYNONYM`, `CONCEPT_RELATIONSHIP`, `CONCEPT_ANCESTOR`). Record
  `NO_DEFINITION_FOUND`; do not fabricate.
- **Conflict handling:** paper-vs-ontology → retain both rows, set
  `definition_conflict_status`, mark `REVIEW_REQUIRED`.

### Stage 4 — Semantic classification (domain/subdomain/semantic type)
**Reuse.** `scripts/vllm_termpop/taxonomy.py` + `categorize_terms.py` +
`term_taxonomy_v1.yaml`. Pilot already ran: 500 terms, 493 assigned, mean conf 0.796,
`OTHER`=139 (see `results/taxonomy_pilot/`).
**Gap.** Full 166,012-term run not done; taxonomy is `DRAFT`; the spec's category list
(25 items) is broader than v1's 16 — needs an explicit mapping/version decision, not a
silent rename.
**Build:** extend taxonomy to cover the spec's list **as subcategories where they
already fit** (avoid inventing upper-level concepts), then run
`categorize_terms.py` over the full table on CPU/SLURM.
**Emit:** `terminology_taxonomy.json` (export from the YAML + classification rules).

### Stage 5 — Controlled-vocabulary linking
**Reuse (already good).** `mappers.map_ols/map_umls/map_bioportal/map_ncbi_taxon`,
`confidence.resolve_canonical`, `omop_local.py`, `cv_link_terms.py`, `omop_link_terms.py`.
**Gap vs. spec:** the spec wants per-candidate rows with `mapping_relation`,
`mapping_disposition`, staged-match provenance (`matched_label` vs `matched_synonym`),
`candidate_rank`, and **null** scores when not computed. Current `cv_links.csv` is flatter.
**Build:** `scripts/termpipeline/project_mappings.py` → `term_ontology_mappings.jsonl`
(projection over existing `cv_mapped_entities.jsonl` + `omop_links.csv` + MeSH;
no re-querying). Relation/disposition assigned by documented rules from the
existing match provenance (label vs synonym vs fuzzy vs ncbi tier).
**Not done:** no acceptance threshold is auto-applied — everything not a validated
exact identifier match stays `REVIEW_REQUIRED`/`UNVERIFIED` until calibrated on a
human-reviewed sample (spec §8/§12).

---

## 3. Artifact → source mapping

| Spec artifact | Source | New code |
|---|---|---|
| `term_mentions.jsonl` | CPU+Qwen+MeSH NER rows | `assemble_mentions.py` |
| `canonical_terms.jsonl` | `terminology_dedup.csv` + mentions | `build_canonical_terms.py` |
| `term_definitions.jsonl` | section text + external mappers | `extract_definitions.py` |
| `term_ontology_mappings.jsonl` | `cv_linking/` + `omop_linking/` + `mesh_ner/` | `project_mappings.py` |
| `terminology_taxonomy.json` | `term_taxonomy_v1.yaml` | export in `taxonomy.py` |
| `ontology_registry.json` | config + live/timestamped probes | new `registry.py` |
| `terminology_validation.jsonl` | stage outputs | new `validate.py` |
| `terminology_extraction_manifest.json` | all of the above | new `manifest.py` |
| `terminology_extraction_report.md` | all of the above | new `report.py` |

All nine land in a **new** dir `results/terminology_v1/` (nothing in
`data_catalogue/` or `zenodo_v1/` is modified).

---

## 4. Prerequisites / blockers

1. `results/llm_ner_body/vllm_sections_ner.csv` — job `28607825` (fix landed:
   bare-string entity tolerance, recursive-split retry, error-cache retry).
2. `results/cv_linking/cv_summary.json` — job `28607619`.
3. Decide taxonomy-scope: map spec's 25 categories onto v1's 16 or version-bump.
4. Human-reviewed gold sample for threshold calibration (spec §12) — **not yet
   created**; nothing may be `AUTO_ACCEPTED` before it exists.
5. `python -m unittest` for new modules (mocked APIs only; no live keys).

## 5. Explicitly out of scope for the first pass

- No full-corpus external-lookup expansion beyond what `cv_link_terms.py` already does.
- No OMOP CDM ETL (user-confirmed: local vocabulary linking only).
- No modification of source text, triple outputs, or `zenodo_v1/`.
- No auto-acceptance of any mapping.

## 6. Resource plan (SLURM, CPU-only for linking/NER-gazetteer)

- Stages 1–5 assembly/projection: `intelsr_short` CPU (8 h), no GPU, no network.
- Definition external lookups: reuse cached `cv_linking` candidates where possible;
  only new definition fetches hit the network, with the existing cache/timeout/backoff.
