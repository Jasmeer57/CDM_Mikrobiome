# AGENTS.md

Biomedical entity extraction and standardization for the Microbiome Common Data Model (CDM) — two independent Python pipelines (`llm_terms/` LLM-based via Ollama, `spacy_terms/` sciSpaCy-based) plus a root integration suite.

> For detailed architecture, module map, and pipeline internals see `CLAUDE.md` at the repo root. This file is the agent-agnostic quick reference.

## Setup commands

The two pipelines are **independent** — each has its own `requirements.txt` and venv. Don't assume a package installed in one is available in the other.

### `llm_terms/` (LLM pipeline)
- Install: `cd llm_terms && pip install -r requirements.txt`
- Run CLI: `python main.py --input "data/paper.txt" --model "phi3:mini"`
- Run API: `python api_server.py`   # also the Dockerfile CMD
- Tests: `python -m unittest discover tests -v`  (single module: `python -m unittest tests.test_core -v`)
- Docs:   `mkdocs serve`  (uses `llm_terms/mkdocs.yml`)

### `spacy_terms/` (sciSpaCy pipeline)
- Install: `cd spacy_terms && pip install -r requirements.txt`
- Install models: `python -m spacy download en_core_sci_lg`  (+ other sciSpaCy models, see `spacy_terms/README.md`)
- Run CLI: `python main.py --input_dir ./data --semantic_model nomic --output_formats json csv sqlite`
- Run API: `uvicorn src.api.main:app --reload`
- Tests: `pytest tests/`  (this pipeline uses pytest, not unittest)

### Root integration
- Cross-pipeline / end-to-end test: `python -m unittest tests.test_integration -v`  (run from repo root)

### Docker (recommended for full runs)
- `cd llm_terms && docker-compose up --build`
- `cd spacy_terms && docker-compose up --build`
- There is **no root-level compose file** that wires the two pipelines together.

## Project layout

- `llm_terms/` — LLM pipeline (Ollama-served Phi-3/Qwen). Orchestrator: `core/pipeline.py`. Has its own Docker + MkDocs.
- `spacy_terms/` — sciSpaCy pipeline (4 NER models in parallel). Orchestrator: `src/pipeline.py`. Has its own Docker + MkDocs.
- `papers_txt/` — shared input corpus (PRJ-accession-named `.txt` files; gitignored — not in fresh checkouts).
- `tests/` — root-level integration tests (unittest).
- `docs/` — MkDocs source and design specs (`docs/superpowers/plans/`, `docs/superpowers/specs/`).
- `paper_claims/` — empirical workbench for the 6 differentiator claims of the Microbiome-CDM paper. Each claim (A context disambiguation, B novel entity recall, C hybrid fusion, D confidence calibration, E speed/efficiency, F biological validation) has its own folder with a README and a runnable `benchmark.py`. Run from the claim's folder; results go to `results/`. `paper_claims/manuscript/` holds the in-progress manuscript, tables, figures, and cover letter.
- `bioproject_data_export.json` — BioProject metadata (gitignored).

## Reference paper for context

> Abdill, R. J., Graham, S. P., Rubinetti, V., et al. (2025). *Integration of 168,000 samples reveals global patterns of the human gut microbiome.* **Cell** 188(4):1100–1118.e17. DOI: [10.1016/j.cell.2024.12.017](https://doi.org/10.1016/j.cell.2024.12.017).

The 168,464 samples and 482 projects in the `microbiome_cdm.db` SQLite database match this paper exactly — the project's CDM is built on the cited literature of that compendium. That DB ships at `llm_terms/Output_final/databases_ontology/microbiome_cdm.db` (plus a sibling `.owl` ontology) and is **gitignored** — don't expect it in a fresh checkout; see the repo README for the Google Drive download link.

## Code style

- Python 3.9+ (spacy_terms); Python 3.10+ typical for llm_terms. Both projects pin via `requirements.txt`.
- Formatters: `black` + `isort` (declared in `spacy_terms/pyproject.toml [project.optional-dependencies.dev]`).
- Optional / heavy dependencies are wrapped in `try/except ImportError` with an `*_AVAILABLE` flag rather than hard requirements. Follow this pattern for new optional integrations — see `llm_terms/scripts/extract_taxonomic_hierarchy.py` for the reference.
- API keys (UMLS, BioPortal, HuggingFace, OpenAI) read from environment variables only — never hardcode.
- **Hands-off files (do not modify without explicit per-file ask):**
  - `llm_terms/scripts/standalone_pipeline.py` (318 KB, user's active dev/test script for the LLM pipeline)
  - `spacy_terms/standalone_scispacy_pipeline.py` (217 KB, user's active dev/test script for the spaCy pipeline)
  - Canonical entry point for production runs is `llm_terms/scripts/kg_pipeline.py` (117 KB) and `llm_terms/Output_final/scripts/kg_pipeline.py` (112 KB) — these are the safe-to-edit canonical pipelines.
- **No `git push` without explicit go-ahead** — all commits stay local until the user says push.

## Testing instructions

- `llm_terms/` uses **unittest**, `spacy_terms/` uses **pytest** — don't mix runners within a pipeline.
- Root: `python -m unittest tests.test_integration -v` (run from repo root).
- New modules in `llm_terms/` follow `tests/test_<module>.py`; in `spacy_terms/` follow pytest conventions under `tests/`.
- There is **no CI in this repo** (no `.github/workflows/`). Run the relevant test command locally before opening a PR.

## PR & commit conventions

- Branch from `main`; never push to `main` directly.
- Commit messages: short, imperative summary.
- Open PR via `gh pr create` once the relevant test command(s) pass.

## Security

- Never commit secrets — `.env` is gitignored at the root.
- API keys and tokens (UMLS, BioPortal, HuggingFace, OpenAI) must come from environment variables.
- Large data files, model binaries, generated databases, and `papers_txt/` are gitignored — do not commit them.
- `CLAUDE.md` is gitignored by design (local Claude Code config); agents from other runtimes should rely on this `AGENTS.md` plus per-pipeline `README.md` instead.
