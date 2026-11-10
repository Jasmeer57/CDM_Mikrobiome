# Microbiome CDM — Entity Extraction, Ontology Mapping & Common Data Model

A hybrid NLP + LLM pipeline for biomedical entity extraction and standardization
across a 444-paper microbiome research corpus. Five NER models run in parallel,
their outputs are fused via embedding-based clustering, mapped to 15+ biomedical
ontologies, and materialized as a SQLite Common Data Model (CDM) database plus
an OWL ontology. The repository also houses the empirical workbench for the
Microbiome-CDM publication (six differentiator claims, each with a runnable
benchmark).

## Reference paper (motivating context)

> Abdill, R. J., Graham, S. P., Rubinetti, V., et al. (2025). *Integration of
> 168,000 samples reveals global patterns of the human gut microbiome.*
> **Cell** 188(4):1100–1118.e17. DOI:
> [10.1016/j.cell.2024.12.017](https://doi.org/10.1016/j.cell.2024.12.017)

The 168,464 samples and 482 BioProjects in `microbiome_cdm.db` match this paper.
Our CDM is built on the *cited literature* of that compendium. The empirical
claims in this repo are bounded by the 444-paper local text corpus, not the
168K-sample compendium.

## Repository layout

| Path | Role |
|------|------|
| `cdm_pipeline/` | **Modular multi-NER + ontology mapping + CDM build** (5 stages). See `cdm_pipeline/README.md`. |
| `llm_terms/` | LLM pipeline (Ollama-served Qwen 3.5:9b). Orchestrator: `core/pipeline.py`. |
| `spacy_terms/` | sciSpaCy pipeline (4 NER models in parallel). Orchestrator: `src/pipeline.py`. |
| `papers_txt/` | Shared input corpus (444 PRJ-accession-named `.txt` files; gitignored — not in fresh checkouts). |
| `paper_claims/` | Empirical workbench for the 6 publication claims. Each claim has its own folder with a `README.md` and a runnable `benchmark.py`. |
| `notebooks/` | `microbiome_cdm_pipeline.ipynb` — end-to-end interactive notebook (71 cells, logging + tqdm + checkpointing). |
| `tests/` | Root-level integration tests (unittest). |
| `docs/` | MkDocs source and design specs. |
| `bioproject_data_export.json` | BioProject metadata (gitignored). |

The two pipelines (`llm_terms/`, `spacy_terms/`) are **independent** — each has
its own `requirements.txt` and venv. `cdm_pipeline/` pulls deps from both and
expects `papers_txt/` and `bioproject_data_export.json` to be present.

## Quick start

### `cdm_pipeline/` (full multi-NER + CDM build)

```bash
# All 5 NER models on the corpus (GLiNER, PubMedBERT, PubTator3, sciSpaCy, Qwen)
python -m cdm_pipeline.ner.runner --models all --max_files 500

# LLM batch (HPC, Qwen 3.5:9b via Ollama) — checkpoint/resume
python -m cdm_pipeline.qwen_batch

# Ontology mapping + CDM build
python -m cdm_pipeline.mapping.runner
python -m cdm_pipeline.cdm.builder

# Evaluation: pairwise Jaccard, unique contribution, type coverage
python -m cdm_pipeline.evaluation.intra_nlp
```

Outputs go to `paper_claims/_multi_ner_runs/` (NER) and `cdm_output/` (DB + OWL).
14 CDM entity types — see `cdm_pipeline/config.py:CDM_TYPES`.

### `llm_terms/` (LLM pipeline)

```bash
cd llm_terms && pip install -r requirements.txt
python main.py --input "data/paper.txt" --model "qwen3.5:9b"
python api_server.py                              # Dockerfile CMD
python -m unittest discover tests -v              # tests
```

### `spacy_terms/` (sciSpaCy pipeline)

```bash
cd spacy_terms && pip install -r requirements.txt
python -m spacy download en_core_sci_lg           # + other models, see README
python main.py --input_dir ./data --semantic_model nomic --output_formats json csv sqlite
uvicorn src.api.main:app --reload                  # API
pytest tests/                                      # tests
```

### Root integration tests

```bash
python -m unittest tests.test_integration -v       # run from repo root
```

## Docker

```bash
cd llm_terms && docker-compose up --build         # LLM pipeline
cd spacy_terms && docker-compose up --build       # sciSpaCy pipeline
```

There is **no root-level compose file** that wires the two pipelines together.

## The 5 NER models

| Model | Type | Output | Types | Papers |
|-------|------|--------|-------|--------|
| **GLiNER** | zero-shot NER | 186K entities | 14 | 444 |
| **PubMedBERT** | fine-tuned BiomedNLP | 51K entities | 1 (DISEASE) | 444 |
| **PubTator3** | NCBI API | 5.8K entities | 6 | 308 |
| **sciSpaCy** (4 sub-models) | deterministic NER | 1.6M entities | 8 | 444 |
| **Qwen 3.5:9b** | LLM via Ollama | 46K entities | 14 | 444 |

## CDM entity types (14)

`ORGANISM`, `CHEMICAL`, `DISEASE`, `PROTEIN`, `DNA_RNA`, `CELL_TYPE`,
`GENOMICS`, `PATHWAY`, `LAB_METHOD`, `DATA_ANALYSIS`, `SAMPLE_METHOD`,
`CLINICAL`, `EXPERIMENTAL_METHOD`, `STUDY_DESIGN`

See `cdm_pipeline/config.py:CDM_TYPES` and `cdm_pipeline/README.md` for the
type-by-type vocabulary priority (15+ controlled vocabularies: UMLS, MeSH,
NCBI Taxonomy, ChEBI, DOID, MONDO, SNOMED CT, GO, PR, SO, CL, OBI, STATO,
EDAM, Reactome, WikiPathways, OMOP, RxNorm, ICD-9/10).

## Paper claims (4)

See `paper_claims/CLAIMS.md` for full verdicts and reproduction instructions.

| Claim | Verdict | Headline |
|-------|---------|---------|
| **A** — context disambiguation | SUPPORTED | LLM 54.1% vs spaCy best 24.3% (+29.7 pp) |
| **B** — complementary entity recall | SUPPORTED | 393 LLM-only, 4,359 spaCy-only, Jaccard 0.085 |
| **C** — hybrid fusion | SUPPORTED | Complementarity (Jaccard 0.085), not tautological union superiority |
| **E** — speed/efficiency | SUPPORTED | spaCy 104.7× faster, LLM 392.6× more costly |

## Code style & conventions

- Python 3.9+ (`spacy_terms`); Python 3.10+ typical for `llm_terms`.
- Formatters: `black` + `isort` (declared in `spacy_terms/pyproject.toml`).
- Optional/heavy deps are wrapped in `try/except ImportError` with an
  `*_AVAILABLE` flag — follow this pattern for new optional integrations.
- API keys (UMLS, BioPortal, HuggingFace, OpenAI) read from environment
  variables only — never hardcode.
- `llm_terms/` uses **unittest**; `spacy_terms/` uses **pytest** — don't mix
  runners within a pipeline.
- No CI in this repo — run the relevant test command locally before a PR.

## Security

- Never commit secrets — `.env` is gitignored at the root.
- Large data files, model binaries, generated databases, and `papers_txt/`
  are gitignored — do not commit them.

## License

MIT License — see `LICENSE` for details.

## Citation

```bibtex
@software{microbiome_cdm_2025,
  title={Microbiome CDM: Multi-NER Entity Extraction and Common Data Model Construction},
  author={Kalra, Jasmeer Singh},
  year={2025},
  url={https://github.com/SCAI-BIO/Microbiome-CDM}
}
```
