# AGENTS.md

> **HISTORICAL COPY — DO NOT USE AS CURRENT INSTRUCTIONS.** This is an archived
> pre-restructure snapshot, kept as a copy in `docs/guides/` (see the root
> `AGENTS.md`, "old doc copies live in `docs/guides/`"). The authoritative file is
> `/home/jkalra_hpc/Microbiome-CDM/AGENTS.md`. Specifically stale here: the
> `cdm_pipeline/` root layout (now `src/cdm_pipeline/`, needs `PYTHONPATH=src`),
> the Genoa cluster/partitions and `microbiome-cdm-env` conda env (both gone —
> see the root file's HPC section), and the launcher list below, which names
> `smoke_test.sbatch` — retired on 2026-10-30 to
> `outputs/scratch/removed_launchers/` because its `spacy_terms/` target is absent from
> this tree.

Biomedical entity extraction and standardization for the Microbiome Common Data Model (CDM) — two independent Python pipelines (`pipelines/llm_terms/` LLM-based via Ollama, `spacy_terms/` sciSpaCy-based) feeding a modular root package (`cdm_pipeline/`: multi-NER + ontology mapping + CDM build), plus a root integration suite.

> Architectural detail, gotchas, and the empirical-claims workbench context live in `CLAUDE.md` (gitignored by design — local Claude Code config). Agents from other runtimes should rely on this file plus the per-pipeline `README.md`s. For the 5-stage CDM flow and 14 entity types see `cdm_pipeline/README.md` and `cdm_pipeline/config.py:CDM_TYPES`.

## Setup & run commands

The two pipelines are **independent** — each has its own `requirements.txt` and venv. Don't assume a package installed in one is available in the other. `cdm_pipeline/` has its own `requirements.txt` (integrator layer only: DB query, RDF export, audit, release tests — the heavy NER deps live in the two pipeline venvs), imports from both pipelines, and expects `data/papers_txt/` + `bioproject_data_export.json` (both gitignored) to be present.

### `cdm_pipeline/` (full multi-NER + CDM build)
```bash
python -m cdm_pipeline.ner.runner --models all --max_files 500          # --all = DEFAULT_MODELS (6 entries: gliner, pubmedbert, pubtator, 3 sciSpaCy; Qwen is separate)
python -m cdm_pipeline.ner.runner --models gliner                       # single model; also: gliner_biomed pubmedbert pubtator scispacy
python -m cdm_pipeline.ner.runner --models scispacy_all                 # all 4 sciSpaCy sub-models at once
python -m cdm_pipeline.qwen_batch                                       # Qwen LLM batch (HPC, checkpoint/resume)
python -m cdm_pipeline.mapping.runner                                   # ontology mapping
python -m cdm_pipeline.cdm.builder                                       # SQLite DB + OWL
python -m cdm_pipeline.evaluation.intra_nlp                              # pairwise Jaccard + type coverage
```
Add `--incremental` to the NER runner. Outputs: `paper/_multi_ner_runs/` (NER) and `cdm_output/` (DB + OWL). Model keys live in `cdm_pipeline/ner/registry.py:MODEL_REGISTRY`.

### Human-microbiome corpus builder (444-paper corpus)

Root-level pair, independent of `cdm_pipeline/` — now under `corpus_builder/`:
- `corpus_builder/human_microbiome_corpus_builder.py` — restartable Pass-1 builder (PyMuPDF ingestion, rule-based topic/relevance classification, section indexing) + Pass-2 LLM enrichment: `--model <vLLM>` or `--ollama <model>` (node-local Ollama, think=false, thread-parallel, resume-safe via `llm_status`). Python 3.9-compatible, cluster-agnostic. Resume-safe: existing record JSONs are skipped unless `--force`.
- `corpus_builder/run_human_microbiome.slurm` — SBATCH wrapper for the 453-paper `data/papers_txt/` corpus → `outputs/results/human_microbiome_corpus_v1/` (gitignored). gpu-amd (mi200) job: node-local Ollama `qwen3.5:4b` enrichment over all 453 papers, then `build_full_corpus.py` chain. PyMuPDF is optional for txt-only input.
- `corpus_builder/build_full_corpus.py` — v1 → 3-layer transformer (Layer 1 document/full-text, Layer 2 study metadata, Layer 3 verbatim-evidenced findings) → `outputs/results/human_microbiome_corpus/`.
- sbatch from repo root: `sbatch corpus_builder/run_human_microbiome.slurm`. Logs to `outputs/logs/human_microbiome_%j.out`.

### `pipelines/llm_terms/` (LLM pipeline, own venv)
```bash
cd llm_terms && pip install -r requirements.txt
python main.py --input "data/paper.txt" --model "qwen3.5:9b"
python api_server.py                       # Dockerfile CMD
python -m unittest discover tests -v       # single module: python -m unittest tests.test_core -v
mkdocs serve                               # uses pipelines/llm_terms/mkdocs.yml
```

### `spacy_terms/` (sciSpaCy pipeline, own venv — pytest, NOT unittest)
```bash
cd spacy_terms && pip install -r requirements.txt
python -m spacy download en_core_sci_lg    # + 3 other sciSpaCy models, see spacy_terms/README.md
python main.py --input_dir ./data --semantic_model nomic --output_formats json csv sqlite
uvicorn src.api.main:app --reload
pytest src/tests/
```

### Docker
`cd llm_terms && docker-compose up --build` and `cd spacy_terms && docker-compose up --build` — there is **no root-level compose file** wiring the two pipelines together.

## Lint, format, typecheck

- **Linters/formatters: ruff + black + isort** (all configured in root `pyproject.toml`; line-length 100, target py39). Ruff selects `E,F,W,I,B,UP,C4` with several py39-compat ignores — see `[tool.ruff.lint]`.
- **Pre-commit is the real local gate** (`pre-commit run --all-files`): gitleaks, `ruff --fix --exit-non-zero-on-fix`, black, isort. The hands-off scratch scripts below are excluded from ruff/black/isort in both `pyproject.toml` and `.pre-commit-config.yaml`.
- **CI exists but is non-blocking for lint**: `.github/workflows/ci.yml` runs on push/PR to `main`. The ruff step uses `--exit-zero` and the black step uses `|| true`, so lint findings never fail CI — only the import smoke tests (against `cdm_pipeline/`, `src/common/`) actually gate. Run pre-commit locally before opening a PR.

## HPC (SLURM cluster)

- **Cluster**: Genoa nodes (`petersberg*` / `gpu-petersberg*`). Partitions: `short` (8h), `medium` (48h), `long` (72h) for CPU; `gpu-nv` (h100), `gpu-nvrtx` (rtx6000), `gpu-amd` (mi200) for GPU. **No `a100`** — request `gpu:mi200:1` / `gpu:h100:1` / `gpu:rtx6000:1`.
- **Modules**: `Miniforge3/24.11.3-0` (conda: `eval "$(/opt/software/easybuild/genoa/software/Miniforge3/24.11.3-0/bin/conda shell.bash hook)"`), `rocm/6.3.3` or `rocm/7.2.0` for AMD GPU, `ollama-bin/0.32.9`. Do **not** `module purge` on GPU jobs when the smoke test pattern is followed (ROCm needs base system libs) — the GPU scripts that do purge reload rocm explicitly.
- **Conda env**: `microbiome-cdm-env` (Python 3.9) for all `cdm_pipeline/` + builder jobs; `pipelines/llm_terms/venv` is used directly by some Qwen jobs (`pipelines/llm_terms/venv/bin/python`). Heavy NER jobs install from `requirements.lock` + `pip install gliner==0.2.26 --no-deps` (gliner's deps conflict with pinned transformers).
- **Launchers**: `src/scripts/slurm/` holds the real HPC entry points (30+ wrappers). Key ones: ~~`smoke_test.sbatch`~~ (fresh-env acceptance test — **retired 2026-10-30**, moved to `outputs/scratch/removed_launchers/`), `ner_444_rerun.sbatch` (GLiNER/GLiNER-BioMed/PubMedBERT over all 444 papers, CPU `medium`), `qwen_batch_slurm.sh` (Qwen NER batch; starts its own Ollama on `gpu-amd`), `claim_a_5x_rerun.sbatch`, `external_benchmark_rerun.sbatch`. Claim-specific wrappers also in `paper_claims/slurm/`. sbatch from repo root; logs land in `outputs/logs/` (local `*_JOBID.out`/`.err`), outputs in `outputs/results/${SLURM_JOB_ID}_*/` (gitignored, made read-only on completion).
- **Ollama on GPU nodes**: scripts start a node-local `ollama serve` (port 11434 or 11444 to dodge conflicts) with `OLLAMA_MODELS="$PROJECT_ROOT/.ollama/models"` and wait for `/api/tags` before pulling/running `qwen3.5:9b`. Reuse this pattern for any new LLM-using script.
- **GLiNER/PubMedBERT on GPU**: `gpu-amd` (MI200) works via ROCm; run models sequentially on a single GPU. Qwen batch is checkpoint/resume (`qwen_batch_checkpoint.json`) — a timed-out job can be resubmitted and continues.

## Testing

- `pipelines/llm_terms/` uses **unittest**; `spacy_terms/` uses **pytest** — don't mix runners within a pipeline.
- Root-level tests (all unittest, run from repo root):
  - `python -m unittest tests.test_integration -v`
  - `python -m unittest tests.test_cdm_pipeline -v` — config, utils, dedup, mapping.confidence, evaluation.
  - `python -m unittest tests.test_release_artifacts -v` — cross-validates the release dirs (release set hardcoded in the test file's `RELEASES` list; per-release TestCase classes are auto-generated, and tests skip if a release dir is absent).
- New `pipelines/llm_terms/` modules follow `src/tests/test_<module>.py`; `spacy_terms/` follows pytest conventions under `src/tests/`.

## Project layout

- `cdm_pipeline/` — modular multi-NER (GLiNER, PubMedBERT, PubTator3, sciSpaCy) + ontology mapping (OLS/UMLS/BioPortal/OMOP/NCBI Taxonomy) + CDM build (SQLite + OWL + provenance). Stages: `ner/`, `quality/` (dedup + LLM type-correction), `mapping/`, `cdm/`, `evaluation/`. 14 CDM entity types in `cdm_pipeline/config.py:CDM_TYPES`; per-type vocabulary priority in `VOCAB_PRIORITY` (a mapper returning a non-preferred vocab is a bug — `resolve_canonical()` enforces priority).
- `pipelines/llm_terms/` — LLM pipeline (Ollama-served Qwen 3.5:9b). Orchestrator: `core/pipeline.py`. Has its own Docker + MkDocs.
- `spacy_terms/` — sciSpaCy pipeline (4 NER models in parallel). Orchestrator: `src/pipeline.py`. Has its own Docker + MkDocs.
- `data/papers_txt/` — shared input corpus (444 PRJ-accession-named `.txt` files; gitignored — not in fresh checkouts). Contains an `others/` subfolder with scratch files (e.g. `terminology_analysis_results.txt`) that recursive .txt discovery would ingest as a bogus paper — the corpus-builder slurm wrapper stages top-level `*.txt` symlinks into `.staging/` (gitignored) to exclude it; follow that pattern for any recursive scan over `data/papers_txt/`.
- `src/common/` — shared package imported by `cdm_pipeline/` and CI smoke tests (re-exports `CDM_TYPES`).
- `src/tests/` — root-level integration + pipeline + release-artifact tests (unittest).
- `paper_claims/` — empirical workbench for the publication's differentiator claims. Each `claim_*/` folder has `benchmark.py` + `README.md` + `outputs/results/`; run from the claim's own folder. `paper_claims/CLAIMS.md` is the canonical verdict source. `paper/manuscript/` holds the in-progress manuscript, tables, figures, cover letter.
- `src/scripts/slurm/` — HPC launcher scripts (see "HPC (SLURM cluster)" above). The corpus-builder pair lives under `corpus_builder/` (see "Setup & run commands").
- `releases/` — versioned release bundles (`v2.0-qwen-publication/`, `v2.1-full-multiner/`, `v2.1.1-clean/`, `v3.0-cdm/`); validated by `tests.test_release_artifacts`. See the Releases table below for which to use.
- `webapp/` — Streamlit UI (currently deleted from working tree; restore with `git checkout webapp/` if needed).
- `docs/` — deleted from working tree (only tracked file was `COMPREHENSIVE_TECHNICAL_DOCUMENTATION.md`); design specs now live under `pipelines/llm_terms/docs/`, `spacy_terms/docs/`.
- `src/notebooks/microbiome_cdm_pipeline.ipynb` — end-to-end interactive notebook.
- Root lockfiles: `requirements.lock`, `requirements-gpu.lock` (reproducible installs).

## Reference paper & canonical DB

> Abdill, R. J., et al. (2025). *Integration of 168,000 samples reveals global patterns of the human gut microbiome.* **Cell** 188(4):1100–1118.e17. DOI: [10.1016/j.cell.2024.12.017](https://doi.org/10.1016/j.cell.2024.12.017).

The 168K samples / 482 BioProjects in `microbiome_cdm.db` match this paper, but the CDM is built on its **cited literature** (the 444-paper corpus), not on the 168K samples. Do not claim results on the compendium.

### Releases (`releases/`)

The publication-quality databases live in versioned release bundles. Each has its own `README.md` with stats, limitations, and verification commands.

| Release | Role | Entities | Relationships | Notes |
|---|---|---|---|---|
| `v2.0-qwen-publication/` | **Frozen manuscript DB** — every number in the paper traces here. Do not rebuild. | 10,217 | 8,210 | Qwen-primary filter of v2.1; 3.6% edge-evidence; 77.2% edges are generic `ASSOCIATED_WITH`. RDF triple count = 8,210 (no dupes). |
| `v2.1-full-multiner/` | **Parent research build** — all 5 NER models, full co-occurrence + KB. Use when you want everything. | 35,118 | 54,799 | 54,788 unique RDF triples (11 exact dupes kept in SQLite for forensics); 60 self-loop LLM artifacts; 61.6% edge-evidence. |
| `v2.1.1-clean/` | Cleaned copy of v2.1 DB only (no RDF/catalogue). | 34,300 | 54,788 | SQLite only; `-shm`/`-wal` present. |
| `v3.0-cdm/` | **CDM-aligned release** — OMOP v5.4 vocabulary layer + KG + NMDC/MIxS biosample data (168K samples, 3.5M attributes). 3-layer architecture; see `cdm/cdm_schema.md`. | 34,300 | 54,788 | Structured layout: `corpus/`, `releases/data_catalogue/`, `cdm/` (DB + `schema.sql` + `cdm_schema.md`). |

- Each release has `microbiome_cdm.db` (+ `.owl`/`.ttl` fact-graphs where applicable). The `.owl`/`.ttl` files are **fact graphs** (ABox RDF), not ontologies — renamed `cdm_facts_*` deliberately.
- `v2.0` is derived from `v2.1` via `paper_claims/build_qwen_cdm.py` (filter to `ner_qwen=1`, drop co-occurrence edges).
- Verify any release: `RELEASE_DIR=<name> python -m unittest tests.test_release_artifacts -v` — the release set is hardcoded in `test_release_artifacts.py::RELEASES`; per-release TestCase classes are auto-generated and skip absent dirs. To cover `v2.1.1-clean`/`v3.0-cdm`, add an entry there.

### Working DB (not a release)

- `paper/_multi_ner_runs/cdm_output/microbiome_cdm.db` (+ `.owl`/`.ttl`) — the working build DB that feeds releases. Gitignored — rebuild via `cdm_pipeline.cdm.builder` or download (see repo README). Quick-look: `python -m cdm_pipeline.verify_db` (row counts + coverage) and `python -m cdm_pipeline.audit.audit_cdm` (full audit report).
- `microbiome_cdm_qwen.db` (same dir) was an **experimental** Qwen-primary build archived 2026-10-03 after a release-audit manifest mismatch (see the explanatory block in `.gitignore` around line 236; the full audit doc no longer exists). Do not treat it as production.
- Benchmark/claim numbers live in `paper_claims/CLAIMS.md` (canonical). README and CLAUDE.md figures may lag — trust CLAIMS.md and re-run a claim's `benchmark.py` if you need current numbers. Do not edit `paper_claims/CLAIMS.md` numbers without re-running the benchmark and committing fresh `outputs/results/`.

## Code style

- Python 3.9+ (`spacy_terms`); Python 3.10+ typical for `llm_terms`. Both pin via `requirements.txt`.
- Optional / heavy dependencies are wrapped in `try/except ImportError` with an `*_AVAILABLE` flag rather than hard requirements — follow this pattern for new optional integrations (reference: `pipelines/llm_terms/scripts/extract_taxonomic_hierarchy.py`).
- API keys (UMLS, BioPortal, HuggingFace, OpenAI, Entrez) read from environment variables only — never hardcode.

### Hands-off files (do not modify without explicit per-file ask)
- `pipelines/llm_terms/scripts/standalone_pipeline.py` (311 KB) — user's active dev/test scratch for the LLM pipeline.
- `spacy_terms/standalone_scispacy_pipeline.py` (212 KB) — user's active dev/test scratch for the spaCy pipeline.
- Safe-to-edit canonical production entry points: `pipelines/llm_terms/scripts/kg_pipeline.py` (115 KB) and `pipelines/llm_terms/Output_final/scripts/kg_pipeline.py` (110 KB).

## Gotchas (learned the hard way)

- **`en_core_sci_lg` returns a generic `ENTITY` label for every term** — never maps cleanly to CDM types. A 0% score on it is a label-mapping artifact, not a real failure (see `paper_claims/claim_A_context_disambiguation/benchmark.py`).
- **spaCy `relevance_score` is degenerate** (single distinct value, 0.0) — don't feed it to ECE/Brier calibration.
- **PubTator3 resolves only ~308/444 papers** — it depends on PubMed PMID lookup from paper titles; missing papers fail lookup. Not a bug.
- **GLiNER + PubMedBERT want GPU.** With one GPU, run sequentially. `qwen_batch.py` runs Qwen sequentially with checkpoint/resume (`qwen_batch_checkpoint.json`).
- **Claim folder letters ≠ doc claim letters.** `claim_D_speed_efficiency` = "Claim E" in docs; `claim_F_biological_validation` = "Claim F". There are no `claim_D`/`claim_E` folders for the confidence-calibration claim. Always cross-reference `paper_claims/CLAIMS.md`.

## PR, commit, and security conventions

- Branch from `main`; never push to `main` directly. **No `git push` without explicit go-ahead** — all commits stay local until the user says push.
- Commit messages: short, imperative summary. Open PRs via `gh pr create` once the relevant test command(s) pass.
- Never commit secrets — `.env` is gitignored at the root; `.env.example` ships with no secrets.
- Large data files, model binaries, generated databases, `data/papers_txt/`, and `*.db` are gitignored — do not commit them. `CLAUDE.md` is gitignored by design (local Claude Code config).
