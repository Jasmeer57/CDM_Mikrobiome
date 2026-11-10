# Microbiome CDM — Corpus, Multi-NER, Terminology Extraction & Controlled-Vocabulary Linking

Biomedical entity extraction and standardization over a **453-paper human-microbiome
research corpus**. The repository builds a section-segmented full-text corpus,
runs a CPU multi-NER ensemble plus LLM extractors, assembles a structured **data
catalogue**, and drives a five-stage **terminology pipeline** (NER →
canonicalization → definition extraction → semantic classification →
controlled-vocabulary linking) that materializes auditable, provenance-tracked
JSONL artifacts. A modular integrator package (`src/cdm_pipeline/`) additionally
builds a SQLite Common Data Model (CDM) database and an OWL ontology.

> **Update 2026-11-02:**
> - The current frozen products are CDM **3.0.3**, terminology **1.0.1**, catalogue **3.1.1** and corpus **2.2.0**, linked together in [`releases/CURRENT_FROZEN_SET_2026-11-02/`](releases/CURRENT_FROZEN_SET_2026-11-02/README.md). See [Where to find things](#where-to-find-things-current-2026-11-02).
> - The CDM inside `releases/frozen_output/` (build 2.1.0) is **superseded** and kept for history.
> - `outputs/results/` is grouped by stage; the old paths still work as symlinks ([`outputs/README.md`](outputs/README.md)).
> - The project is in a development freeze; the publication index is [`paper/publication/PUBLICATION_INDEX.md`](paper/publication/PUBLICATION_INDEX.md).

> **Last updated:** 2026-10-30 — repository restructured into seven top-level
> folders with run-time path discovery (see [Repository layout](#repository-layout)
> and [What moved where](#what-moved-where)). The CDM shipped in
> `releases/frozen_output/` is now the 453-paper build. See `AGENTS.md` for the
> agent-facing operating manual and gotchas.

> **Counts as of build `28619916`.** Every figure below is the terminology
> production build (`outputs/results/terminology_v1/`). The machine-readable source of
> truth is
> [`outputs/results/terminology_v1/terminology_extraction_manifest.json`](outputs/results/terminology_v1/terminology_extraction_manifest.json);
> for how to read the numbers without conflating them, see
> [`docs/DATA_SEMANTICS.md`](docs/DATA_SEMANTICS.md), and for how L1/L2/L3 relate,
> [`docs/terminology_crosswalk.md`](docs/terminology_crosswalk.md). Outstanding
> in-bundle corrections are tracked in
> [`docs/PENDING_VERSION_BUMPS.md`](docs/PENDING_VERSION_BUMPS.md).

## Where to find things (current, 2026-11-02)

Everything current and frozen is linked from one folder: **`releases/CURRENT_FROZEN_SET_2026-11-02/`**. Run its `VERIFY.sh` to check every component against its manifest.

| What | Where (via the current set) | Underlying location |
|---|---|---|
| Corpus release (453 papers, 447 publications) | `01_corpus_release/` | `pipelines/corpus_v2/releases/2.2.0/` |
| Segmented corpus (4,006 hash-verified sections) | `02_corpus_segmented/sections.jsonl`, `segments.jsonl`, `papers.jsonl` | `releases/frozen_output/01_corpus/data/` (identical to `pipelines/corpus_v2/data/`) |
| Corpus as markdown (one file per paper) | `03_corpus_markdown/HMPAPER_*.md` | `releases/frozen_output/01_corpus/segmented_sections_markdown/` (also `data/segmented_sections_markdown/`) |
| Raw input text (not frozen, gitignored) | — | `data/papers_txt/` (BioProject-named), `data/corpus/text/` (HMPAPER-named) |
| Raw NER output, one CSV per model | `04_ner_per_model/section_ner_*` | `releases/frozen_output/04_ner/` |
| LLM extraction output | `04_ner_per_model/qwen_sections_ner/` and the LLM runs inside the terminology | `releases/frozen_output/04_ner/qwen_sections_ner/`; `pipelines/corpus_v2/data/llm_terms.jsonl` |
| Terminology, all sources (NER ensemble, 2 LLM runs, MeSH), source kept per mention | `05_terminology/term_mentions.jsonl`, `canonical_terms.jsonl` | `releases/terminology/1.0.1/` |
| Data catalogue | `06_data_catalogue/` | `releases/data_catalogue_v3/3.1.1/` |
| **Common data model** (SQLite, 44 tables) | `07_common_data_model/microbiome_cdm_v3.db` | `releases/cdm_v3/3.0.3/` |
| NER benchmark (public + corpus) | — | `outputs/results/benchmark/` |
| Validation reports, manuscript, review packages | — | `paper/publication/` |

**Terms from one model:** each mention keeps `extraction_run_id` and `extraction_model`.
- NER models are in run `cpu_ensemble_v1`: scispaCy lg / craft / bc5cdr / jnlpba, GLiNER medium / biomed, BioBERT-diseases.
- LLM runs: `qwen35_vllm_body_v1` (Qwen3.5-4B via vLLM) and `qwen_ollama_cell7c_v1` (qwen3.5:4b via Ollama).
- Dictionary run: `mesh_gazetteer_2026`.
- Example: `SELECT * FROM term_mention WHERE extraction_run_id = 'qwen35_vllm_body_v1';`

Per-source counts are in the current set's README.

## Reference paper (motivating context)

> Abdill, R. J., Graham, S. P., Rubinetti, V., et al. (2025). *Integration of
> 168,000 samples reveals global patterns of the human gut microbiome.*
> **Cell** 188(4):1100–1118.e17. DOI:
> [10.1016/j.cell.2024.12.017](https://doi.org/10.1016/j.cell.2024.12.017)

The 168K samples / 482 BioProjects match that paper. This repository's CDM is
built on the paper's **cited literature** — the local 453-paper text corpus, not
the 168K-sample compendium. Do not claim results on the compendium.

## Repository layout

Restructured on **2026-10-30**: the top level holds only seven modular folders.
Every other folder was nested into one of them — see
[What moved where](#what-moved-where).

```
Microbiome-CDM/
├── src/          all code
│   ├── cdm_pipeline/     integrator: multi-NER runner, mapping, CDM builder (paths.py = path registry)
│   ├── corpus_builder/   corpus assembly / catalogue extraction helpers
│   ├── pipeline/         stage-ordered consolidation s01–s12 (work in progress)
│   ├── paper_claims/     claim-analysis package
│   ├── scripts/          build tooling: slurm/, termpipeline/, vllm_termpop/, catalogue/, release_gates/
│   ├── tests/            unittest suite
│   ├── common/           shared CDM type constants (imported as `common`)
│   ├── configs/          canonical.yaml, relation_vocabulary.yaml
│   ├── notebooks/        pipeline_standalone.ipynb
│   └── template/         corpus / catalogue / CDM templates
├── pipelines/    self-contained pipelines with their own scripts, config and outputs
│   ├── corpus_v2/        versioned corpus build (stages 10–70; release 2.2.0 is canonical)
│   ├── llm_terms/        LLM pipeline cited by the manuscript (own venv)
│   └── corpus_pipeline/  earlier staged corpus build (superseded by corpus_v2)
├── data/         inputs
│   ├── papers_txt/                    453 PRJ-named .txt papers
│   ├── segmented_sections_markdown/   453 HMPAPER_*.md section files
│   ├── 168000-samples-paper/          Abdill 2025 compendium metadata
│   ├── corpus/ catalogue/ data/fulltext/   corpus records, raw terminology, 73 JATS XML
│   ├── reference/                     data/reference/ontologies/ (ECO), data/reference/taxonomy/ (term taxonomy v1)
│   └── bioproject_data_export.json
├── outputs/      everything runs produce
│   ├── results/          run outputs (CDM 453 build, NER runs, terminology, OMOP, …)
│   ├── logs/             LLM-judge results, gold standard, coverage audit, build logs
│   └── scratch/          working analyses (evidence calibration, pilot, ontology export)
├── releases/     frozen, checksummed deliverables — never edit in place
│   ├── frozen_output/    the paper bundle (rebuild with its _build/ script)
│   ├── data_catalogue/   data catalogue bundle (1,003-entry manifest)
│   ├── terminology/      terminology release 1.0.0
│   └── zenodo_v1/        section-level NER deposit
├── paper/        manuscript/ + _multi_ner_runs/ (444-paper build the manuscript cites)
└── docs/         design specs, reports, guides
```

`spacy_terms/` (the sciSpaCy pipeline described further down) is not part of
this working tree.

Tooling that used to sit in the repo now lives beside it: `~/tools/ner_tools`
(JDK + Java NER tools), `~/venvs/ner_variants`, `~/venvs/gliner_overlay`,
`~/llm/hf-cache-gliner` and `~/llm/hf-cache-gemma4-w4a16` (HuggingFace models).

### What moved where

| Old location | New location |
|---|---|
| `scripts/` | `src/scripts/` |
| `tests/` | `src/tests/` |
| `common/` | `src/common/` |
| `configs/` | `src/configs/` |
| `notebooks/` | `src/notebooks/` |
| `template/` | `src/template/` |
| `corpus_v2/` | `pipelines/corpus_v2/` |
| `llm_terms/` | `pipelines/llm_terms/` |
| `corpus_pipeline/` | `pipelines/corpus_pipeline/` |
| `papers_txt/` | `data/papers_txt/` |
| `segmented_sections_markdown/` | `data/segmented_sections_markdown/` |
| `168000-samples-paper/` | `data/168000-samples-paper/` |
| `fulltext/` | `data/fulltext/` |
| `bioproject_data_export.json` | `data/bioproject_data_export.json` |
| `ontologies/` | `data/reference/ontologies/` |
| `taxonomy/` | `data/reference/taxonomy/` |
| `results/` | `outputs/results/` |
| `logs/` | `outputs/logs/` |
| `scratch/` | `outputs/scratch/` |
| `frozen_output/` | `releases/frozen_output/` |
| `data_catalogue/` | `releases/data_catalogue/` |
| `zenodo_v1/` | `releases/zenodo_v1/` |
| `paper_claims/` (manuscript + multi-NER runs) | `paper/` |
| `ner_tools/` | `~/tools/ner_tools` (override: `CDM_NER_TOOLS`) |
| `venvs/ner_variants`, `venvs/gliner_overlay` | `~/venvs/` |
| `.hf_home/`, `.cache/huggingface/` | `~/llm/hf-cache-gliner`, `~/llm/hf-cache-gemma4-w4a16` |

Removed during the cleanup (recoverable from ZFS snapshots for a few days):
plain `.log/.out/.err` run logs, superseded result runs (`cdm_452`,
`_termpipe_*`, smoke and per-job runs), catalogue cache backups, obsolete
reports, and `frozen_output.zip` (a duplicate of `releases/frozen_output/`).

### Paths are found at run time

No code hard-codes `/home/...` or counts parent directories to reach the repo
root. The root is the nearest ancestor that contains the marker file
**`.cdm_root`**:

| Where | How the root is found |
|---|---|
| Python package code | `from cdm_pipeline.paths import REPO_ROOT`, plus named locations such as `RESULTS_DIR`, `CORPUS_V2_DIR`, `segmented_markdown_dir()` |
| Standalone Python scripts | `next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())` |
| Shell / SLURM launchers | a `CDM_ROOT=…` line that walks up from `$SLURM_SUBMIT_DIR` (or the script's folder) to `.cdm_root`, and stops with an error if it is not found |

Set **`CDM_REPO_ROOT`** to override the discovered root (for example, a copy of
the repo elsewhere). Do not delete `.cdm_root`.

`#SBATCH --output=` / `--error=` cannot use variables, so launchers give log
paths relative to the repo root (`outputs/logs/slurm/…`,
`pipelines/corpus_v2/logs/slurm/…`): **submit from the repo root**.

Corpus records written before the move keep their original absolute paths (they
are hash-pinned). `pipelines/corpus_v2/scripts/common.py:resolve_recorded_path()`
maps them to the new layout when a stage reopens them.

## Usage

`cdm_pipeline` and `corpus_builder` live under `src/`, so Python invocations
from the repo root need `PYTHONPATH=src`. Each pipeline keeps its own
dependencies (`pip install -r pipelines/llm_terms/requirements.txt`; the
integrator uses `requirements.lock`).

```bash
cd Microbiome-CDM                       # always run from the repo root
PYTHONPATH=src python -m cdm_pipeline.ner.runner --models all
PYTHONPATH=src python -m unittest discover -s src/tests -t src
sbatch src/scripts/slurm/ner_java_tools.sbatch
sbatch pipelines/corpus_v2/slurm/40_sectionize.sbatch
python releases/frozen_output/_build/build_frozen_output.py   # rebuild the paper bundle
```

SLURM wrappers export `PYTHONPATH="$CDM_ROOT/src"` themselves. Dataset paths
resolve through `src/cdm_pipeline/paths.py`; env overrides: `CDM_REPO_ROOT`,
`CDM_PAPERS_TXT`, `CDM_PDFS`, `CDM_FULLTEXT`, `CDM_SAMPLES_PAPER`,
`CDM_BIOPROJECT_EXPORT`, `CDM_SEGMENTED_MD`, `CDM_NER_TOOLS`.

## End-to-end data flow

```
 data/fulltext/ (73 JATS XML) ─┐
 data/papers_txt/ (453 .txt)  ─┼─► pipelines/corpus_v2/  (stages 10–70)  ──►  pipelines/corpus_v2/releases/2.1.0/
 data/corpus/ (453 recs) ─┘        │                                   │
                                   ▼                                   ▼
                    data/segmented_sections_markdown/  (4,006 section units, 26.87M chars)
                                   │
        ┌──────────────────────────┼───────────────────────────┐
        ▼                          ▼                           ▼
 CPU NER ensemble            LLM section NER              MeSH gazetteer NER
 (7 models, 1.70M rows)   Qwen (Ollama + vLLM body)    (Aho–Corasick, offline)
        │                          │                           │
        └──────────────┬───────────┴───────────────┬───────────┘
                       ▼                           ▼
          vocab NER + mention locations      catalogue extraction (Qwen via vLLM)
                       │                           │
                       ▼                           ▼
     src/scripts/termpipeline/ (T1→T3→T2→T5→T4)   releases/data_catalogue/  (tables + terminology)
                       │
                       ▼
        outputs/results/terminology_v1/  (9 artifacts)
                       ▲
     CV linking: reuse CPU mappings + net-new (UMLS/BioPortal/OMOP/MeSH)
```

## Section segmentation & markdown conversion

`src/scripts/segment_all_to_markdown.py` converts all 453 papers to
`data/segmented_sections_markdown/HMPAPER_*.md` from `data/corpus/records/HMPAPER_*.json`
(section inventory with char offsets) and `data/corpus/text/HMPAPER_*.txt`.

* **453 papers, 4,006 section units, 26,871,587 total chars**, 0 uncovered, 13
  warnings across 8 papers (`_conversion_report.json`).
* Marker format consumed by notebook cell 2: `<!-- SEGMENT -->`, `<!-- SECTION_ID -->`,
  `<!-- SECTION_PATH -->`, `<!-- SEGMENT_ORDINAL_WITHIN_SECTION -->`, `<!-- END_SEGMENT -->`.
* **Offsets in downstream records are section-body relative, not file relative** —
  always validate against a section unit, never the whole `.md`.
* Of the 4,006 units, exactly **453 are zero-char `front/(preamble)` placeholders**
  (one per paper). Excluding backmatter gives the **2,817-unit / 20,904,249-char
  CPU body universe**.

## NER runs

### CPU section ensemble (`releases/zenodo_v1/ner_453_sections/`)

Seven local CPU models over 2,817 body units, **1,705,501 combined rows**:

| Model | Rows | Notes |
|---|---:|---|
| `en_core_sci_lg` | 960,719 | emits generic `ENTITY` for every term |
| `gliner_biomed` | 297,115 | |
| `gliner_medium` | 168,029 | |
| `en_ner_craft_md` | 119,092 | also emits `GO` |
| `en_ner_bc5cdr_md` | 80,584 | |
| `en_ner_jnlpba_md` | 52,992 | |
| `biobert_diseases` | 26,970 | DISEASE only |

Columns: `term,labels,model,paper,section_id,section_path,char_start,char_end`.
Launcher: `src/scripts/slurm/ner_453_sections.sbatch`.

**PubTator3** is PMID-lookup based and is **excluded from section-mode NER**
(`predict_text` is not implemented). Its parent run resolved ~300 papers from a
title-only PubMed lookup; a subsequent backfill raised coverage to **438/453
papers** via PMID-direct → DOI → title lookup (15 remain: 9 no-PMID, 6
zero-annotation). Those backfill outputs are not yet consolidated — they live
under `outputs/results/<jobid>_pubtator3_*/`, and their annotations carry PubMed
abstract/passage offsets (`0,0`), not corpus section spans.

### LLM section NER — Qwen

* **Historical Ollama run** (Cell-7c restricted): `releases/zenodo_v1/qwen_sections_ner/`,
  model `qwen3.5:4b`, 2,601 sections / 14,591 chunks, **0 errors, 186,024 located rows**.
* **New vLLM full-body run**: `src/scripts/vllm_termpop/qwen_sections_vllm.py`
  (`--section_filter {cell7c,body,all}`), launched by
  `src/scripts/vllm_termpop/qwen_sections_body_a40.sbatch` → `outputs/results/llm_ner_body/`.
  Per-segment checkpoint/resume in `_vllm_sections_cache.json`.
  **Status: assembled — `vllm_sections_ner.csv` (366,123 rows), cache fully clean
  (3,986 entries, 3,986 ok / 0 errored).** The 15 residual failures were handled
  by `src/scripts/vllm_termpop/repair_sections_cache.py`, which re-attempted only
  those segments under the original cache keys — never a full rerun. A later
  assembly crash (`AttributeError: 'int' object has no attribute 'strip'`, a bare
  numeric entity) was fixed with a type guard in the assembly loop; because a
  running process keeps the module it imported, only a fresh run emitted the CSV.
  Reported coverage in `_vllm_sections_summary.json`: **2,817/2,817 body sections,
  4,051/4,051 segments, 0 failed, 20,904,249/20,904,249 chars = 100.0%**, and
  453 zero-char `front/(preamble)` placeholders counted as empty, not failures.

### MeSH gazetteer NER (CPU, offline)

`src/scripts/vllm_termpop/mesh_gazetteer_ner.py` + `src/scripts/slurm/mesh_ner.sbatch`
build an Aho–Corasick dictionary from local MeSH 2026 XML dumps and match it
against the segmented sections. **822,910 gazetteer terms** (30,359/31,110
descriptors + 324,046 supplementals) → **248,088 rows**, 8,652 distinct terms,
over 453 papers / 2,817 sections / 20.9M chars in 53 s. Filters: tree-branch
whitelist, `--min_chars 4`, code-token drop, word-boundary enforcement, ambiguous
deny-list, longest-match-first. Outputs: `outputs/results/mesh_ner/mesh_ner_terms.csv`,
`mesh_term_stats.csv` (typed, 0 duplicate `(term, cdm_type)` pairs).

### LLM vs NER comparison

`src/scripts/vllm_termpop/compare_llm_vs_ner.py` (+ `src/scripts/slurm/compare_llm_vs_ner.sbatch`)
reports **inter-model agreement, not accuracy** (no gold standard exists, so
precision/recall/F1 are not computable). Two views exist, both on a common unit
universe (2,124 units), and are not interchangeable:

| View | LLM side | Jaccard global | pooled-within-unit | mean-per-unit | typed pooled | LLM span-exact |
|---|---|---|---|---|---|---|
| `ollama/` | historical Ollama `qwen3.5:4b`, cell-7c | 0.156 | 0.117 | 0.112 | — | — |
| `full_body/` | vLLM full-section body, 366,096 rows | 0.223 | 0.176 | 0.175 | 0.158 | 0.700 |

The generic-`ENTITY`-dominated raw ensemble is reported alongside
**`cpu-ensemble-excl-generic`** (`full_body/` global 0.245 / pooled 0.249 /
mean 0.256); neither replaces the other. `full_body/` carries a `label_caveat`
noting that `en_core_sci_lg` emits only `ENTITY` and `en_ner_craft_md` also emits
`GO`, so the excl-generic ensemble is the fairer term-level comparison. Results in
`outputs/results/llm_vs_ner_comparison/{ollama,full_body}/`.

A **per-model** agreement study also exists under `outputs/results/<jobid>_ner_eval_permodel/`
(`metrics_full.json`, `ner_comparison_metrics.csv`, report + permutation tests) — it
compares each CPU NER model against the historical Ollama Qwen run, per model, again as
**agreement rather than accuracy**. It is not consolidated into a stable directory, and
its "Qwen span-exact" column is per-model (not comparable to the ensemble union rate).

## Corpus builds

### `pipelines/corpus_v2/` — versioned LLM-ready corpus (release 2.1.0)

Stages 10→70 (`slurm/submit_all.sh`, `afterok` chain). Release `2.1.0`
(2026-10-24) quality report:

* **453 papers** (447 canonical, 6 duplicate-excluded), **4,006 sections**,
  **26,874,831 chars / 7,909,432 tokens**.
* Validation `{REVIEW_REQUIRED 392, COMPLETE 46, PARTIAL 15}`; full-text
  completeness `{partial 407, complete 46}`; independent JATS XML cross-check
  `{COMPLETE 282, PARTIAL 14}` over the 296 papers that have an original XML;
  LLM enrichment `{COMPLETE 1639, PARTIAL 49, FAILED 11}`.
* BioProject linkage **452/453**. `data/`: papers 453, sections 4,006, segments
  4,006, llm_terms 1,699, findings 21,395, studies 453.
* Every stage refuses to run outside Slurm (`common.require_slurm`); restartable,
  event-logged, with per-stage checkpoints and artifact hashes.

### `pipelines/corpus_pipeline/` — staged 453-paper build

`./corpus_pipeline/run_local.sh` runs stages 01 → 04 → 08 → 12 → 14; GPU stages
`06_jev.sbatch` and `11_embeddings.sbatch` are launched separately.
**Current state:** 435/453 papers `READY`, 18 `BLOCKED` (abstract-only/partial);
3,105 sections, 11,980 chunks, 134,960 BM25 terms, 2 validation failures. JEV,
embeddings and dense index are **not run**; retrieval evaluation is blocked on
missing human-reviewed labels.

## Data catalogue (`releases/data_catalogue/`)

Assembled by Qwen extraction over every section of every paper
(`src/scripts/vllm_termpop/catalogue_ner.py` → `catalogue_finalize.sbatch`) —
**453 papers, 56,985 machine-extracted records**:

| table | rows | papers covered | evidence quote |
|---|---:|---:|---:|
| findings | 21,439 | 451 | 99.8% |
| assays | 12,116 | 439 | 100.0% |
| cohorts | 9,575 | 452 | 100.0% |
| samples | 8,484 | 448 | 100.0% |
| datasets | 3,228 | 440 | 100.0% |
| data_assets | 2,143 | 422 | 100.0% |

* Extraction coverage: **3,443/4,006 sections complete**, char coverage
  **90.857%**, 127 failed segments, verdict **`REVIEW_REQUIRED`**.
* Evidence grounding: exact 11,469 / reflowed 40,807 / not located 13,199.
* `terminology/terminology_dedup.csv` holds **166,012** deduplicated terms and
  `terminology/taxonomy/term_taxonomy_v1.{yaml,csv}` the versioned taxonomy.
* Bundle contents: `tables/`, `records/catalogue_records.jsonl`, `quality/`,
  `provenance/`, `terminology/`, a copy of the `pipelines/corpus_v2/` build, `src/scripts/`,
  `slurm/`, `README.md`, `MANIFEST.sha256`, `MANIFEST.json` (1,003 files).
* **Every row is machine-extracted and unverified** — a candidate for human
  curation, not a curated result. `sample_type` normalization is deterministic
  (alias table + regex, no model call).
* Note: `releases/data_catalogue/README.md` inside the hashed bundle still quotes older
  pre-finalize counts; `MANIFEST.json` / `quality/quality_report.md` are current.
  The bundle is checksummed, so it is not edited in place.

## Terminology pipeline (`src/scripts/termpipeline/`)

The five-stage terminology build over the section corpus. **CPU-only, offline,
deterministic**; Stage T3 makes no LLM and no network call. Implemented as its
own package writing to a new `outputs/results/terminology_v1/` directory — nothing in
`releases/data_catalogue/` or `releases/zenodo_v1/` is modified.

```bash
# Local chain validation (fast, capped inputs)
PYTHONPATH=src /home/jkalra_hpc/venvs/vllm/bin/python -m scripts.termpipeline.assemble_mentions --help
sbatch src/scripts/slurm/termpipe_v1.sbatch          # full chain on SLURM (SMOKE=1 to smoke-test)
```

| Stage | Script | Output |
|---|---|---|
| T1 mentions | `assemble_mentions.py` | `term_mentions.jsonl` — offsets re-verified |
| T3 definitions | `extract_definitions.py` | `term_definitions.jsonl` — source-grounded, no LLM |
| T2 canonical | `build_canonical_terms.py` | `canonical_terms.jsonl` |
| T5 mappings | `project_mappings.py` | `term_ontology_mappings.jsonl` |
| T4 taxonomy | `export_taxonomy.py` | `terminology_taxonomy.json` (exported as-is) |
| registry | `build_registry.py` | `ontology_registry.json` |
| validation | `validate_outputs.py` | `terminology_validation.jsonl` (fail-closed) |
| report | `build_report.py` | `terminology_extraction_report.md` |
| manifest | `build_manifest.py` | `terminology_extraction_manifest.json` (hashes the report) |
| T5b calibration sample | `build_calibration_sample.py` | `calibration/calibration_sample.csv` — supporting, not one of the 9 |
| T5c thresholds | `calibrate_thresholds.py` | `calibration/calibration_thresholds.json` — only from labelled rows |

Design rules (see `docs/reports/terminology_pipeline_plan.md` for the full plan):

* **Identity layers stay distinct**: `mention_id` (one occurrence *as tagged by one
  extractor*) vs extractor-independent `occurrence_key` vs `term_id` vs
  `mapping_id`. Competing type assignments from different models are preserved as
  distinct mentions and never merged.
* **Mentions** are re-verified by copying text at reproducible offsets; a candidate
  is dropped unless `text[start:end] == surface`.
* **Definitions** are source-derived only, extracted deterministically by anchoring
  on a definition cue and resolving the term leftward against the canonical term
  table; `review_status=REVIEW_REQUIRED`, `confidence=null`. Contextual
  descriptions are never promoted to formal definitions. External/ontology
  definitions are a separate provenance class and are not produced by this stage.
* **Mappings** never auto-accept: `auto_accepted` is always 0 unless a
  **human-reviewed** calibration file enables a stratum; `auto_accept_eligible`
  records what would qualify once thresholds are calibrated. Spec §12 is a
  supporting stage pair (T5b sample / T5c thresholds) writing into
  `<out_dir>/calibration/`; T5b is skipped when a sheet already exists so a
  reviewer's verdicts are never clobbered, and T5c only runs when
  `CAL_REVIEW_SHEET=<filled sheet>` is set. Thresholds are Wilson lower bounds
  per `(source_service, mapping_relation)` stratum, fail-closed
  (`NOT_CALIBRATED` / `INSUFFICIENT_SAMPLE` / below-bound). Consumption is
  opt-in via `project_mappings.py --calibration`, which changes **only**
  `mapping_disposition` (`REVIEW_REQUIRED → AUTO_ACCEPTED`) on eligible rows.
  `AMBIGUOUS` is scoped within a single vocabulary. Omitting the flag is
  byte-identical to the default build.
* **Validation** is fail-closed: `COMPLETE` requires no failures, all corpus papers
  present, ≥1 mention per paper with content, and a supplied mention stream.
  Zero-char placeholder units are `NOT_APPLICABLE`, excluded from the denominator.

Reference local-chain run (formerly `results/_termpipe_chain/`, removed 2026-10-30) — a **separate 6,000-mention
chain validation**, not a subset of the production build and not comparable to it
row-for-row: 6,000 mentions with **100% offsets verified**, 59 definition rows /
47 terms, 166,012 canonical terms (a **separate chain run** — it fed the L1 table
straight through, so it equals L1's row count, not the production 165,991),
30,533 mapping rows
(`EXACT_MATCH` 26,897 / `AMBIGUOUS` 3,636; `auto_accepted` 0,
`auto_accept_eligible` 26,897), taxonomy 16 upper / 66 sub with `UNCERTAIN`
reserved, 3,553 sections validated, 453 `NOT_APPLICABLE`, overall
`REVIEW_REQUIRED`.

Full-corpus production build (`outputs/results/terminology_v1/`, job **`28619916`**) — **all
four mention sources present**, so this is the honest all-sources number:

| Artifact | Value |
|---|---|
| `term_mentions.jsonl` rows | **2,505,735** (2,505,650 offset-verified; 85 excluded by the build's own check and accounted for by gate G4) |
| sources | `cpu_ensemble` 1,705,500 / `qwen_vllm_body` 366,123 / `mesh_gazetteer` 248,088 / `qwen_ollama` 186,024 — all `OK` |
| `canonical_terms.jsonl` | **165,991** (165,905 distinct `term_norm`; 81 norms carry >1 type) |
| `term_definitions.jsonl` | **1,150** rows |
| `term_ontology_mappings.jsonl` | **334,231** rows (`RELATED_TO` 188,313 / `AMBIGUOUS` 96,038 / `EXACT_MATCH` 38,403 / `NO_MATCH_FOUND` 11,477) |
| terms with no match / lookup failed | 11,477 / 0 |
| `auto_accept_eligible` / `auto_accepted` | **38,334** / **0** |
| validation | `COMPLETE` — 453/453 papers, 3,553 sections validated, 2,505,650 mentions resolved exactly (100%) |
| manifest | 9/9 artifacts present, 8 hashes verified, 0 mismatched |

**`166,012` is the L1 dedup row count, not the canonical count.** L1
(`releases/data_catalogue/terminology/terminology_dedup.csv`) → L2 (`canonical_terms.jsonl`,
165,991) loses 21 rows to control-byte sanitisation collisions; see
`docs/terminology_crosswalk.md`.

Offset caveat: the "100%" above is the build's self-check. Re-verified
independently against `section_text_original`, **93.74% slice exactly and 6.26%
need a bounded shift** (mostly +1, across 75 sections); 0 are unresolvable. Both
figures measure plumbing, **not** accuracy — see `docs/DATA_SEMANTICS.md` §6–§7.

The build also wrote the Spec §12 review sample to
`outputs/results/terminology_v1/calibration/` (390 rows over 14 strata: 300 primary / 90
control). It was drawn against the **superseded 334,275-row** mapping table, so it
is quarantined as `releases/terminology/1.0.0/calibration_v0_pre_fix/` and must be
redrawn before any use. T5c never ran (no filled sheet), so thresholds are
`NOT_CALIBRATED` and `auto_accepted` stays **0**.

This build is frozen as **`releases/terminology/1.0.0/`** — a read-only copy, 22
files, `sha256sum -c` 22/22 OK. Release gates
(`python -m scripts.release_gates.check_all --release <path> [--deep]`) pass 8/9;
the single failure is **G2**, the genuine `2,505,736` vs `2,505,735` off-by-one in
the manifest's `coverage.mention_records`. It is recorded, not patched.

## Controlled-vocabulary linking

### Reused + net-new CV linking (`outputs/results/cv_linking/`)

`src/scripts/vllm_termpop/cv_link_terms.py` (+ `src/scripts/slurm/cv_link.sbatch`, CPU)
links the terminology term table to external vocabularies. **71,538 typed
`(term, cdm_type)` pairs**; 94,474 generic `ENTITY` pairs skipped on purpose;
**35,063 reused** from the existing CPU `mapped_entities.json`; **36,475 net-new**
to resolve. Checkpoint every 200 pairs; ~3.4 pairs/s at 24 workers. Credentials
are read from the environment (`.env`), sent term-level only, with timeouts,
bounded retries, and response caching.

### Local OMOP linking (`outputs/results/omop_linking/`)

A **new local module** (`src/scripts/vllm_termpop/omop_local.py`) + offline SQLite
index (`build_omop_index.py` → `outputs/results/omop_vocab/omop_index.sqlite`, 5.68 GB;
concept 10,167,185 / term 15,647,137 / `Maps to` 7,423,177). Exact normalized
match only, `confidence` 1.0, non-standard hits followed via `Maps to` to the
standard concept. Reported as a **separate view**, deliberately not added to
`VOCAB_PRIORITY`. Result: **9,615/71,538 typed pairs (13.44%)** with an OMOP hit,
6,713 to a standard concept, 21,881 links. A miss means "no exact OMOP
name/synonym", not "not in OMOP".

### Taxonomy classification pilot (`outputs/results/taxonomy_pilot/`)

`src/scripts/vllm_termpop/taxonomy.py` + `categorize_terms.py` classify terms against
the versioned taxonomy without inventing categories. Pilot (500 stratified terms):
493 assigned / **7 `UNCERTAIN`** / 2 invented categories flagged, 127 need review,
mean confidence 0.796. A full-table classification pass has not been run
(exported `terminology_taxonomy.json` reports `classified_terms: 0`).

## `src/cdm_pipeline/` — integrator (multi-NER + CDM build)

```bash
PYTHONPATH=src python -m cdm_pipeline.ner.runner --models all --max_files 500
PYTHONPATH=src python -m cdm_pipeline.ner.runner_sections --output_dir ...   # section mode (PubTator EXCLUDED)
PYTHONPATH=src python -m cdm_pipeline.qwen_batch                             # Qwen LLM batch (checkpoint/resume)
PYTHONPATH=src python -m cdm_pipeline.triples.runner
PYTHONPATH=src python -m cdm_pipeline.mapping.runner
PYTHONPATH=src python -m cdm_pipeline.cdm.builder                            # SQLite DB + OWL
PYTHONPATH=src python -m cdm_pipeline.evaluation.intra_nlp
PYTHONPATH=src python -m cdm_pipeline.verify_db
```

Model keys live in `src/cdm_pipeline/ner/registry.py:MODEL_REGISTRY`. The 14 CDM
entity types are in `src/cdm_pipeline/config.py:CDM_TYPES`:

`ORGANISM`, `CHEMICAL`, `DISEASE`, `PROTEIN`, `DNA_RNA`, `CELL_TYPE`,
`GENOMICS`, `PATHWAY`, `LAB_METHOD`, `DATA_ANALYSIS`, `SAMPLE_METHOD`,
`CLINICAL`, `EXPERIMENTAL_METHOD`, `STUDY_DESIGN`

## The two standalone pipelines

```bash
# pipelines/llm_terms/ (LLM via Ollama)
cd llm_terms && pip install -r requirements.txt
python main.py --input "data/paper.txt" --model "qwen3.5:9b"
python -m unittest discover tests -v

# spacy_terms/ (sciSpaCy)
cd spacy_terms && pip install -r requirements.txt
python -m spacy download en_core_sci_lg
python main.py --input_dir ./data --semantic_model nomic --output_formats json csv sqlite
pytest src/tests/
```

`pipelines/llm_terms/` uses **unittest**; `spacy_terms/` uses **pytest** — don't mix runners
within a pipeline. Each has its own venv and `requirements.txt`; a package
installed in one is not necessarily available in the other.

## Tests

Root tests are unittest, run from the repo root:

```bash
PYTHONPATH=src python -m unittest tests.test_paths -v            # path resolution + env overrides
PYTHONPATH=src python -m unittest tests.test_cdm_pipeline -v     # config, utils, dedup, mapping, evaluation
PYTHONPATH=src python -m unittest tests.test_data_catalogue -v   # needs PyYAML
PYTHONPATH=src python -m unittest tests.test_termpipeline -v     # 40 tests, mocked externals, no live creds
```

Known issues: `tests.test_integration` has a broken `project_root` (`src/tests/`
instead of repo root) in its 4 structure checks — the files exist; its
CLI/import tests pass. `tests.test_release_artifacts` expects `releases/`, which
this working tree does not contain.

## Docker

```bash
cd llm_terms && docker-compose up --build
cd spacy_terms && docker-compose up --build
```

There is **no root-level compose file** wiring the two pipelines together.

## Status & limitations (read before quoting numbers)

* **Nothing is scientifically verified.** NER, catalogue, taxonomy and mappings
  are machine output with per-row provenance; human verification is separate and
  largely `pending`.
* The 453-paper corpus has **435 `READY` / 18 `BLOCKED`** papers (abstract-only or
  partial full text) in `corpus_pipeline`, and 296/453 papers have an original
  JATS XML for cross-checking.
* CV linking is **reuse-first** and never auto-accepts; the network-sourced tier
  (UMLS/BioPortal/OLS) has now been exercised with the populated CV input
  (60,056/71,538 pairs mapped, 83.95%), but no acceptance threshold has been
  calibrated against a human-reviewed sample, so `auto_accepted` is still 0.
* OMOP coverage is honestly low (13.44%) and exact-match only.
* `llm-ner-body` (`vllm_sections_ner.csv`) is now assembled (366,123 rows); the
  terminology T1 stage consumes it as the `qwen_vllm_body` source.
* The CDM database and historical `releases/` bundles are not present in this
  working tree; rebuild via `cdm_pipeline.cdm.builder` or download.

## Code style & conventions

* Python 3.9+ floor (`requires-python = ">=3.9"`); the conda env is Python 3.9,
  though the CPU terminology/OMOP tooling runs under Python 3.12 (`venvs/vllm`).
* Lint/format: **ruff + black + isort** (root `pyproject.toml`; line-length 100,
  target py39). Pre-commit is the real local gate (`pre-commit run --all-files`).
  CI lint is non-blocking and still references old root `cdm_pipeline/` paths.
* Optional / heavy deps are wrapped in `try/except ImportError` with an
  `*_AVAILABLE` flag rather than hard requirements — follow this pattern.
* API keys are read from environment variables only — never hardcoded.

## Security

* Never commit secrets — `.env` is gitignored at the root; `.env.example` ships
  with no secrets.
* Externally sourced lookups send **minimum term-level information only**, never
  full paper text, and support local-only execution.
* Large data files, model binaries, generated databases, `data/papers_txt/`, `outputs/results/`,
  and `*.db` are gitignored — do not commit them.
* If a key is ever disclosed, **rotate it** — keys must never appear in logs,
  manifests, outputs, tests, or source.

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
