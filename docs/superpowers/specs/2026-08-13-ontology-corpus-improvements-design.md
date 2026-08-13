# Ontology + Corpus Improvements — Design

**Date:** 2026-08-13
**Status:** Approved by user, implementing

## Context

Repo mirrored to a second GitHub remote (`jasmeer`) and cleaned up (untracked
oversized/generated files, removed dead `llm_terms/archive/` and a broken
`llm_terms/llama.cpp` gitlink). Corpus (`papers_txt/`, ~500 files) is
intentionally fixed — sourced from DOIs cited in a specific 168,000-sample
paper, not meant to grow via automated ingestion. This spec covers the
remaining actionable gaps identified in the ontology-mapping layer and the
dormant FAISS semantic-search index, all confirmed by reading the actual
code (not assumed from the README).

Five independent, bounded components. Each can ship/be reviewed on its own.

## Component 1: Ontology-source prioritization

**Problem:** `llm_terms/mappers/ols_mapper.py` and `bioportal_mapper.py`
query their respective APIs with no ontology filter — every OLS/BioPortal
result is scored purely on label-text similarity (`_calculate_confidence`).
A generic-ontology hit (MeSH, SNOMED) can outrank a domain-precise one
(ENVO, OHMI, ChEBI, NCBITaxon) at equal string similarity, because source
ontology is never considered.

**Design:**
- Add `ENTITY_TYPE_ONTOLOGY_MAP` to `llm_terms/config/cdm_config.py`:
  entity type → list of preferred ontology acronyms.
  - `ORGANISM` → `ncbitaxon`, `ohmi`
  - `CHEMICAL` → `chebi`
  - `DISEASE` → `doid`, `mondo`
  - `PATHWAY` → `go`
  - `CELL_TYPE` → `cl`
  - `DNA_RNA` → `so`
  - `SAMPLE_METHOD`, `LAB_METHOD` → `obi`, `envo`
  - `GENOMICS`, `EXPERIMENTAL_METHOD` → `edam`
- `OLSMapper.map_entity(entity_name, entity_type, preferred_ontologies=None)`
  — when given, passes OLS API's native `ontology=` filter param
  (comma-joined, lowercase). `_calculate_confidence` gets a `+0.15` boost
  when `result['ontology_name']` is in the preferred set.
- `BioPortalMapper.map_entity(...)` — same shape, BioPortal's native
  `ontologies=` param (comma-joined, uppercase acronyms).
- `ComprehensiveMapper.map_entity_comprehensive` looks up
  `ENTITY_TYPE_ONTOLOGY_MAP.get(entity_type)` and passes it through to both
  mappers.
- **Backward compatible:** param defaults to `None` — omitted filter means
  today's unrestricted-search behavior, unchanged.
- **Error handling:** unknown entity types simply get no filter (falls back
  to current behavior), not an error.
- **Testing:** unit tests on `_calculate_confidence` boost logic with
  mocked API responses; one test per mapper confirming the `ontology=`
  param is included in the outgoing request when preferred set given, and
  absent when not.

## Component 2: OMOP local vocab — fail loud

**Problem:** `llm_terms/mappers/omop_local_mapper.py` logs a `WARNING` and
silently continues with empty lookup tables when `vocab_dir` doesn't exist.
Downstream, the pipeline reports OMOP mapping as "ran successfully" with a
0% hit rate — indistinguishable from "ran and genuinely found nothing."

**Design:**
- `OMOPLocalMapper.__init__`: if `vocab_dir` is given but
  `not os.path.exists(vocab_dir)`, raise `FileNotFoundError` with a message
  naming the missing path and pointing to the Athena OMOP vocabulary
  download (`https://athena.ohdsi.org/`) and required files
  (`CONCEPT.csv`, `CONCEPT_SYNONYM.csv`).
- `ComprehensiveMapper` construction: catch that `FileNotFoundError`,
  log it at `ERROR` (not silently swallow), and fall back to the API-based
  `OMOPMapper()` — so a missing local vocab degrades to a working (slower)
  path instead of a silently-empty one.
- Add a short "OMOP Vocabulary Setup" section to `llm_terms/README.md`
  documenting the Athena download step.
- **Testing:** unit test asserting `FileNotFoundError` on missing dir;
  unit test asserting `ComprehensiveMapper` falls back to `OMOPMapper`
  when local dir is absent.

## Component 3: ChEBI hierarchy builder

**Problem:** `extract_taxonomic_hierarchy.py` builds parent/child lineage
for ORGANISM entities via NCBI Entrez. No equivalent exists for CHEMICAL
entities — `extract_chebi_relationships.py` only pulls flat relationships,
not hierarchy (e.g. "butyrate" is_a "short-chain fatty acid" is_a
"monocarboxylic acid").

**Design:**
- New `llm_terms/scripts/extract_chemical_hierarchy.py`, modeled on the
  taxonomy script's structure (cache, rate-limited requests, ranked output).
- Uses OLS's generic, ontology-agnostic endpoint:
  `GET /api/ontologies/chebi/terms/{url-encoded IRI}/hierarchicalAncestors`
  — works off the ChEBI IRI already resolved by `OLSMapper` for a CHEMICAL
  entity (Component 1 makes that resolution more reliable).
- Output shape mirrors `extract_taxonomic_hierarchy.py`'s exactly: a flat
  list of relationship dicts (`source`, `target`, `relationship_type`,
  `source_db`, `confidence`, `evidence`, ...). Verified against
  `kg_refiner.py`'s `validate_and_enhance_relationships`, which consumes
  `rel.get('relationship_type')` off exactly this flat shape — so the new
  script's output drops into the same downstream code path unchanged.
- **Error handling:** OLS lookup miss or network failure → log + skip
  entity, don't fail the batch (matches existing taxonomy script's pattern).
- **Testing:** unit test with mocked OLS response verifying hierarchy
  parsing; integration smoke test with 2-3 known ChEBI IDs (butyrate,
  propionate) run manually, not in CI (matches existing taxonomy script —
  it isn't in the automated test suite either, since it hits a live API).

## Component 4: NCBI Taxonomy direct-name fallback

**Problem:** `extract_taxonomic_hierarchy.py`'s
`extract_ncbi_taxon_id(ols_id)` only works when OLS has already returned an
`NCBITaxon_` IRI for the entity. If OLS returns nothing, or returns a
different ontology's ID for an ORGANISM entity, taxonomy lookup never runs.

**Design:**
- Add `search_taxon_by_name(organism_name)` to `TaxonomyHierarchyExtractor`
  — calls Entrez `esearch(db="taxonomy", term=organism_name)` directly,
  same auth/rate-limit pattern as existing `get_taxon_info`.
- Call site: when `extract_ncbi_taxon_id` returns `None` for an ORGANISM
  entity, fall back to `search_taxon_by_name` before giving up on that
  entity.
- **Testing:** unit test with mocked Entrez response for the fallback path.

## Component 5: FAISS/corpus semantic index

**Problem:** `papers_txt/others/extraction.py`:
1. `INPUT_DIRECTORY` is a hardcoded absolute path
   (`/home/jkalra/Downloads/CDM/papers_txt`) — breaks on any other machine.
2. Cache check is existence-only (`if os.path.exists(FAISS_INDEX_FILE)`) —
   trusts a stale index forever even if `papers_txt/` content changed.
3. Uses `all-MiniLM-L6-v2` (sentence-transformers) while the rest of the
   pipeline (`semantic_deduplicator.py`) standardizes on
   `nomic-embed-text-v1.5` — two different embedding spaces in one project
   for the same kind of task.
4. `LLM_MODEL_NAME = "dee"` doesn't exist in the local Ollama install
   (confirmed available: `alibayram/Qwen3-30B-A3B-Instruct-2507`,
   `nomic-embed-text`, `gemma4:e4b`, `qwen3.5:9b`) — term-extraction phases
   (2–6, which call the LLM) can't run as-is.

**Design (this pass):**
- Fix `INPUT_DIRECTORY` to resolve relative to the script
  (`Path(__file__).resolve().parents[2] / "papers_txt"`).
- Replace existence-only cache check with a content hash (sorted filenames
  + sizes + mtimes of `papers_txt/*.txt`) stored alongside the index;
  rebuild automatically when the hash differs.
- Switch embedding model from `all-MiniLM-L6-v2` to
  `nomic-ai/nomic-embed-text-v1.5` (`sentence-transformers`,
  `trust_remote_code=True`), matching `semantic_deduplicator.py`'s model
  and task-prefix convention.
- **Scope cut, explicit:** only rebuild Phase 1 (chunking + embedding +
  FAISS index) now — this needs no LLM. Phases 2–6 (LLM-based term
  extraction/definition/categorization) get `LLM_MODEL_NAME` corrected to
  an available model (`qwen3.5:9b`) so the script doesn't hard-fail on
  startup, but are **not executed** in this pass — that's a separate,
  much longer-running task (500 files × LLM calls) left for the user to
  kick off deliberately.
- Install `faiss-cpu` + `sentence-transformers` in this sandbox (user
  confirmed) to actually run the Phase 1 rebuild and produce a fresh
  `corpus_index.faiss` / `corpus_embeddings.npy` against the current
  500-file corpus.
- **Testing:** no new automated test (this is a data-artifact rebuild, not
  library code) — verified by confirming index vector count matches chunk
  count computed from current `papers_txt/`.

## Out of scope (explicitly, per user)

- Automated corpus ingestion (PubMed/PMC pulls) — corpus is intentionally
  fixed to the source paper's DOI list.
- Any edits to `llm_terms/scripts/standalone_pipeline.py` or
  `spacy_terms/standalone_scispacy_pipeline.py` — active dev/test scripts,
  user said hands off.
- Running Phases 2–6 of `extraction.py` (LLM term extraction) — flagged
  above as a separate, longer task.
- Any `git push` — all work stays local until user says go.

## Testing strategy summary

- Components 1, 2, 4: standard `unittest`/mock-based unit tests, added to
  `llm_terms/tests/`, run via existing test runner.
- Component 3: unit test (mocked) + manual smoke test, matching existing
  taxonomy script's precedent (live-API scripts aren't in the CI suite).
- Component 5: verification by vector-count/hash check, not a unit test —
  this is a generated data artifact, not library code.
