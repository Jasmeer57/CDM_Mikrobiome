# AGENTS.md

Biomedical entity extraction and standardization for the Microbiome Common Data
Model (CDM) over a **453-paper human-microbiome corpus**. The working tree layers
several subsystems on top of each other:

* `src/cdm_pipeline/` — modular integrator: multi-NER + triples + ontology mapping
  + CDM build (SQLite + OWL). `src/corpus_builder/` sits alongside it.
* `pipelines/llm_terms/` (LLM via Ollama) — independent pipeline with its own
  venv/`requirements.txt`. (`spacy_terms/` is still referenced by `README.md`,
  `pyproject.toml` excludes and `src/tests/test_integration.py`, but the directory is
  **absent from this working tree**.)
* `pipelines/corpus_v2/` — versioned, template-compliant LLM-ready corpus build (stages
  10–70; releases `2.0.0`, `2.1.0`, `2.2.0`; **2.2.0 is canonical**) over
  `data/segmented_sections_markdown/`.
* `pipelines/corpus_pipeline/` — older staged 453-paper build (reconcile → sections → chunk
  → BM25 → validate).
* `releases/data_catalogue/` — assembled catalogue bundle (453 papers / 56,985 records)
  plus the term inventory and taxonomy.
* `src/scripts/termpipeline/` — the 5-stage terminology pipeline (NER → canonicalize →
  definitions → classification → CV linking) producing 9 artifacts.
* `src/scripts/vllm_termpop/` + `src/scripts/slurm/` — the vLLM/Qwen runners, MeSH
  gazetteer NER, local OMOP index, CV linking, and all HPC launchers.
* `releases/frozen_output/` — **new checksummed portable bundle** (extracted 2026-10-28,
  built by `releases/frozen_output/_build/build_frozen_output.py`; `BUNDLE_INFO.json` +
  `MANIFEST.sha256`): `01_corpus` (HMCV2 2.2.0: 37,907 entities / 32,713 canonical
  triples), `02_data_catalogue`, `03_common_data_model`, `04_ner` (all NER runs,
  three different corpora — **read `04_ner/README.md` before quoting any row
  count**), `05_evidence` (manuscript, figures, LLM-judge). Read-only copy, same
  hands-off status as `releases/zenodo_v1/`.

> Repo is mid-restructure with a large working tree and **no `.git/` directory**
> (`git status` fails; treat the filesystem as the source of truth):
> `cdm_pipeline/` and `corpus_builder/` moved under `src/`; root `cdm_pipeline/`
> is absent and `spacy_terms/` is missing. `releases/` now contains only
> `releases/terminology/1.0.0/` (frozen terminology build) plus a ledger — the
> versioned DB bundles (`v2.0-qwen-publication`, `v2.1-full-multiner`, `v3.0-cdm`)
> are still absent. `paper_claims/` holds only `manuscript/` and
> `_multi_ner_runs/` — the `claim_*` dirs and `CLAIMS.md` are gone. `archive/` is
> gitignored; old doc copies live in `docs/guides/`. Trust the working tree, not
> git HEAD, for layout. Architectural detail also lives in `CLAUDE.md`
> (gitignored local config). For the 5-stage CDM flow and 14 entity types see
> `src/cdm_pipeline/README.md` and `src/cdm_pipeline/config.py:CDM_TYPES`.
>
> The empty stray root directories (`current/`, `directory/`, `new/`, …) were
> removed 2026-10-30. `.audit_tmp/` is scratch but holds the probes behind the
> terminology catalogue audit — keep it. `outputs/scratch/` is real (see below).
>
> Tooling lives **outside the repo** since 2026-10-30: `~/tools/ner_tools`
> (override `CDM_NER_TOOLS`, resolved by `cdm_pipeline.paths.ner_tools_dir`),
> `~/venvs/ner_variants` + `~/venvs/gliner_overlay`, and the HF caches
> `~/llm/hf-cache-gliner` (GLiNER models) and `~/llm/hf-cache-gemma4-w4a16`.

## Critical: `PYTHONPATH=src` required

`cdm_pipeline` and `corpus_builder` live under `src/`, so **all root-level python
invocations need `PYTHONPATH=src`**:

```bash
PYTHONPATH=src python -m unittest tests.test_paths -v      # fails without PYTHONPATH=src
PYTHONPATH=src python -m cdm_pipeline.ner.runner ...
```

SLURM wrappers already do `export PYTHONPATH="$PROJECT_ROOT/src"` (see
`src/scripts/slurm/ner_453_sections.sbatch`). Dataset paths resolve via
`src/cdm_pipeline/paths.py` (env overrides: `CDM_PAPERS_TXT`, `CDM_PDFS`,
`CDM_FULLTEXT`, `CDM_SAMPLES_PAPER`, `CDM_BIOPROJECT_EXPORT`; `REPO_ROOT` derived
from file location — CWD-independent).

## Section segmentation & markdown conversion

`src/scripts/segment_all_to_markdown.py` reads `data/corpus/records/HMPAPER_*.json`
(section inventory with char offsets) + `data/corpus/text/HMPAPER_*.txt` and
writes one `data/segmented_sections_markdown/HMPAPER_*.md` per paper. **453 papers,
4,006 section units, 26,871,587 chars**, 0 uncovered, 13 warnings / 8 papers
(`_conversion_report.json`). Marker format: `<!-- SEGMENT: ... -->`,
`<!-- SECTION_ID: ... -->`, `<!-- SECTION_PATH: ... -->`,
`<!-- SEGMENT_ORDINAL_WITHIN_SECTION: n -->`, `<!-- END_SEGMENT: ... -->`,
consumed by `src/notebooks/pipeline_standalone.ipynb` cell 2.

* **Offsets are section-body relative, never file relative.** Validate per section
  unit (reuse `cdm_pipeline.ner.runner_sections.load_sections`), never against the
  whole `.md`.
* Of 4,006 units, exactly **453 are zero-char `front/(preamble)` placeholders**
  (one per paper) — treat as `NOT_APPLICABLE`, not as failures.
* `section_path` has no reliable slash structure: bucket as
  `split("/")[0] if "/" in path else "(none)"`.
* Excluding backmatter (`body_only=True`) gives the **2,817-unit /
  20,904,249-char CPU body universe** (453 papers). The newer variant runs use a
  slightly smaller **452-paper analysis universe** — same body segmentation minus
  `HMPAPER_000372`, an HTML "Auto Article Locator" redirect stub (908 body chars,
  zero catalogue records): **2,815 units / 20,903,341 chars**, via
  `runner_sections.py --exclude_papers HMPAPER_000372`.

## Setup & run commands

### `src/cdm_pipeline/` (full multi-NER + triples + CDM build)
```bash
PYTHONPATH=src python -m cdm_pipeline.ner.runner --models all --max_files 500   # --all = DEFAULT_MODELS (gliner, pubmedbert, pubtator, 3 sciSpaCy; Qwen is separate)
PYTHONPATH=src python -m cdm_pipeline.ner.runner --models gliner                # also: gliner_biomed pubmedbert pubtator scispacy scispacy_all
PYTHONPATH=src python -m cdm_pipeline.ner.runner_sections --output_dir ...      # section-level NER (--output_dir required; PubTator EXCLUDED here: predict_text raises NotImplementedError)
PYTHONPATH=src python -m cdm_pipeline.qwen_batch                                 # Qwen LLM batch (HPC, checkpoint/resume)
PYTHONPATH=src python -m cdm_pipeline.triples.runner                             # LLM triple extraction (see triples/: biolord_matcher, eco_mapper, db_validator, cleanup_validated, biomni_*)
PYTHONPATH=src python -m cdm_pipeline.mapping.runner                             # ontology mapping
PYTHONPATH=src python -m cdm_pipeline.cdm.builder                                # SQLite DB + OWL
PYTHONPATH=src python -m cdm_pipeline.evaluation.intra_nlp                       # pairwise Jaccard + type coverage
PYTHONPATH=src python -m cdm_pipeline.verify_db                                  # quick row-count/coverage look
```
Model keys live in `src/cdm_pipeline/ner/registry.py:MODEL_REGISTRY`. Beyond
the legacy per-model keys, the registry defines **named model groups** usable as
`--models` values in `runner_sections`: `all`, `scispacy_all` (4 models),
`bert_variants` (`bert_disease bert_chemical bert_genetic scibert_jnlpba`),
`extra` (`scispacy_bionlp13cg hunflair2`), and `gliner_new` (`gliner2_base
gliner2_large gliner_v25_medium gliner_v25_biomed` — 2026 checkpoints).
Export extras: `export/` (sssom, biocypher, conformal, doc_stats,
`build_zenodo_bundle.py`) and `audit/audit_cdm.py` (CDM SQLite diagnostic).

### `pipelines/corpus_v2/` (versioned LLM-ready corpus, release 2.2.0 canonical)
```bash
bash pipelines/corpus_v2/slurm/submit_all.sh --dry-run     # 10 -> 20 -> 21 -> 30 -> 40 -> 45 -> 46 -> 50 -> 51 -> 53 -> 55 -> 56 -> 60 -> 70
bash pipelines/corpus_v2/slurm/submit_all.sh --from 40     # resume at a stage; --after <jobid> to attach
```
Every stage refuses to run outside Slurm (`common.require_slurm`; override with
`--allow-no-slurm` for debugging) and is restartable, event-logged, and
checkpointed. Stages snapshot at submit: editing a `.sbatch` needs cancel+resubmit.
Stage 53/54 requests `--partition=sgpu_short --gres=gpu:a100:2`, which exists on
the current cluster.

### `pipelines/corpus_pipeline/` (staged 453-paper corpus build)
```bash
./corpus_pipeline/run_local.sh                # stages 01 reconcile -> 04 select sections -> 08 chunk (512 tok/64 overlap) -> 12 bm25 -> 14 validate; --dry-run supported
sbatch pipelines/corpus_pipeline/slurm/06_jev.sbatch         # GPU: judgments/evidence values
sbatch pipelines/corpus_pipeline/slurm/11_embeddings.sbatch  # GPU: embeddings + dense index (same job)
```
Bump `pipelines/corpus_pipeline/config.py:CONFIG_VERSION` to invalidate caches. Artifacts:
`manifests/`, `reports/` (`final_execution_report.json` is the state summary),
`chunks/`, `index/`, `embeddings/`. **Current state: 435/453 READY, 18 BLOCKED
(abstract-only/partial); BM25 built; JEV, embeddings and dense index NOT run;
retrieval evaluation blocked on missing human-reviewed labels.** Validation
checks structure/provenance only — not scientific correctness.

### `src/scripts/termpipeline/` (5-stage terminology pipeline, CPU-only, offline)
```bash
sbatch src/scripts/slurm/termpipe_v1.sbatch        # full chain T1->T3->T2->T5->T4->registry->validation->report->manifest; SMOKE=1 to smoke-test
```
Writes a **new** `outputs/results/terminology_v1/`; `releases/data_catalogue/` and `releases/zenodo_v1/` are
read-only inputs. Stages are individually runnable (`python -m scripts.termpipeline.<stage>`)
under `/home/jkalra_hpc/venvs/vllm/bin/python` (has no pytest). Full plan:
`docs/reports/terminology_pipeline_plan.md`.

Spec §12 calibration is a **supporting** stage pair, not one of the 9 artifacts:
`T5b build_calibration_sample` draws a deterministic stratified sample of CV
candidate rows into `<out>/calibration/calibration_sample.csv` (human columns
shipped empty; skipped if the sheet already exists, so labels are never
clobbered; skipped under `SMOKE=1`), and `T5c calibrate_thresholds` derives
per-stratum Wilson lower bounds **only** when `CAL_REVIEW_SHEET=<filled sheet>`
is set. Thresholds are fail-closed (`NOT_CALIBRATED` with no verdicts,
`INSUFFICIENT_SAMPLE` below `--min_n`, `BELOW_THRESHOLD` otherwise; `UNCERTAIN`
excluded from the numerator; invalid verdict strings counted and excluded).
Consumption is opt-in: `project_mappings.py --calibration
<calibration_thresholds.json>` promotes only `auto_accept_eligible` rows in a
cleared stratum and touches **only** `mapping_disposition`. Absent the flag the
output is byte-identical to the uncalibrated build.

Full-corpus build (`outputs/results/terminology_v1/`, job **`28619916`**, all four sources
present): **2,505,735 mentions** (2,505,650 offset-verified; `cpu_ensemble`
1,705,500 / `qwen_vllm_body` 366,123 / `mesh_gazetteer` 248,088 / `qwen_ollama`
186,024, all `OK`), **165,991** canonical terms, **1,150** definition rows,
**334,231** mapping rows (`RELATED_TO` 188,313 / `AMBIGUOUS` 96,038 /
`EXACT_MATCH` 38,403 / `NO_MATCH_FOUND` 11,477), `auto_accept_eligible` **38,334**
but `auto_accepted` **0**, validation `COMPLETE` (453/453 papers, 3,553 sections,
100% mentions resolved), manifest 9/9. **Do not confuse `166,012` (L1 dedup rows in
`releases/data_catalogue/terminology/terminology_dedup.csv`) with `165,991` (L2 canonical
rows) — different tables.** T5b wrote the §12 review sample (390 rows / 14
strata) **against the superseded 334,275-row mapping table**; it is quarantined as
`releases/terminology/1.0.0/calibration_v0_pre_fix/` and must be redrawn before
use. T5c was skipped for lack of a filled sheet; thresholds are `NOT_CALIBRATED`.

Frozen as **`releases/terminology/1.0.0/`** (read-only copy, 22 files, ledger
digest `a5c1ae90…2b48`). Release gates live in `src/scripts/release_gates/`
(`python -m scripts.release_gates.check_all --release <path> [--deep] [--repo-docs]`);
the frozen release fails **G2 only** — an off-by-one: the real `2,505,736` vs
`2,505,735` in the manifest's `coverage.mention_records`. That is expected and
must not be patched. (G7 is a heuristic scan of `AGENTS.md`/`README.md` for
retired counts; it passes when those docs are clean.) See `docs/DATA_SEMANTICS.md`
before quoting any count.

### `src/scripts/vllm_termpop/` (NER + catalogue + CV linking tooling)
Qwen vLLM section NER, catalogue extraction, MeSH gazetteer NER, local OMOP index,
CV linking, taxonomy classifier, LLM-vs-NER comparison. Key modules:
`qwen_sections_vllm.py`, `catalogue_ner.py`, `mesh_gazetteer_ner.py`,
`build_omop_index.py`, `omop_local.py`, `omop_link_terms.py`, `cv_link_terms.py`,
`compare_llm_vs_ner.py`, `taxonomy.py`, `categorize_terms.py`,
`repair_sections_cache.py`. Launchers: `src/scripts/slurm/{mesh_ner,cv_link,omop_link,termpipe_v1,compare_llm_vs_ner}.sbatch`
and `src/scripts/vllm_termpop/*_a40.sbatch`.

### `pipelines/llm_terms/` (LLM pipeline, own venv)
```bash
cd llm_terms && pip install -r requirements.txt
python main.py --input "data/paper.txt" --model "qwen3.5:9b"
python api_server.py                       # Dockerfile CMD
python -m unittest discover tests -v
mkdocs serve                               # uses pipelines/llm_terms/mkdocs.yml
```

### `spacy_terms/` — absent from this working tree
`spacy_terms/` is referenced by `README.md`, `pyproject.toml` excludes and
`src/tests/test_integration.py`, but the directory does not exist locally. Its
historical commands (`pytest src/tests/`, sciSpaCy model downloads) cannot run until
it is restored.

### Docker
`cd llm_terms && docker-compose up --build` — there is **no root-level compose
file**, and the `spacy_terms` compose service cannot be used while that directory
is missing.

## NER runs — what exists, what does not

* **CPU section ensemble** — `releases/zenodo_v1/ner_453_sections/all_ner_sections_combined.csv`,
  **1,705,501 rows** over 2,817 body units, 7 models: `en_core_sci_lg` 960,719 /
  `gliner_biomed` 297,115 / `gliner_medium` 168,029 / `en_ner_craft_md` 119,092 /
  `en_ner_bc5cdr_md` 80,584 / `en_ner_jnlpba_md` 52,992 / `biobert_diseases` 26,970.
  Columns `term,labels,model,paper,section_id,section_path,char_start,char_end`.
  Launcher `src/scripts/slurm/ner_453_sections.sbatch`. **`releases/zenodo_v1/` is a frozen
  export — do not modify in place.**
* **Qwen Ollama section NER (historical)** — `releases/zenodo_v1/qwen_sections_ner/`, model
  `qwen3.5:4b`, 2,601 sections / 14,591 chunks, 0 errors, 186,024 located rows.
* **Qwen vLLM full-body run** — `src/scripts/vllm_termpop/qwen_sections_vllm.py`
  (`--section_filter {cell7c,body,all}`) → `outputs/results/llm_ner_body/`. Cache
  `_vllm_sections_cache.json` = **3,986 entries, 3,986 ok / 0 errored** after
  repair. **`vllm_sections_ner.csv` IS assembled: 366,123 rows**; summary reports
  2,817/2,817 body sections, 4,051/4,051 segments, 0 failed, **100.0% char
  coverage** (20,904,249 chars), with 453 zero-char `front/(preamble)`
  placeholders counted empty, not failed. The 15 residual failures were repaired
  (not rerun) by `repair_sections_cache.py`.
* **MeSH gazetteer NER** — `mesh_gazetteer_ner.py` + `src/scripts/slurm/mesh_ner.sbatch`,
  CPU/offline Aho–Corasick over MeSH 2026 XML. 822,910 gazetteer terms →
  **248,088 rows / 8,652 distinct terms** over 2,817 sections in 53 s; outputs
  `outputs/results/mesh_ner/mesh_ner_terms.csv` + `mesh_term_stats.csv` (typed).
* **Comparison** — `compare_llm_vs_ner.py` → `outputs/results/llm_vs_ner_comparison/`;
  reports **inter-model agreement, not accuracy** (no gold standard ⇒ no
  P/R/F1). Two views with different intersection universes: `ollama/` (historical
  `qwen3.5:4b` cell-7c, 1,926 common units) global 0.156 / pooled 0.117 / mean
  0.112, and `full_body/` (vLLM full-section body, 2,124 common units) global
  0.223 / pooled 0.176 / mean 0.175 / typed 0.158, LLM span-exact 0.700. Raw
  ensemble is reported alongside `cpu-ensemble-excl-generic` (`full_body/`
  global 0.245).

### The 2026-10 variant runs (452-paper analysis universe)

Five new section-level runs (jobs `286437…`–`28649…`, results consolidated into
`releases/frozen_output/04_ner/section_ner_*_452/`, originals in
`outputs/results/<jobid>_ner_*/`). All cover **452 papers / 2,815 body units /
20,903,341 chars** (`HMPAPER_000372` excluded) with the same
`term,labels,model,paper,section_id,section_path,char_start,char_end` schema and
**section-body-relative offsets** as the 453 ensemble:

* `section_ner_bert_variants_452/` — 4 BioBERT/SciBERT token-classifiers,
  145,342 rows (`ner_bert_variants.sbatch`).
* `section_ner_extra_variants_452/` — `en_ner_bionlp13cg_md` + HunFlair2
  (flair), 189,298 rows (`ner_extra_variants.sbatch`).
* `section_ner_gliner_new_452/` — `gliner2_{base,large}`,
  `gliner_v25_{medium,biomed}`, 1,398,962 rows (`ner_gliner_new.sbatch`).
* `section_ner_hunflair2_trim_452/` — HunFlair2 alone, 106,413 rows
  (`ner_hunflair2_trim.sbatch`).
* `section_ner_java_tools_452/` — DNorm (with Ab3P), TaggerOne (disease+chemical),
  tmChem, GNormPlus, **180,480 rows** (re-run job `28649661` via
  `ner_java_tools.sbatch`; supersedes job `28647522`'s 129,558-row run, which
  lacked tmChem and ran DNorm without Ab3P).

Gotchas for this family:

* **Do not mix corpora.** `zenodo_v1` runs are 453 papers / section; the variant
  runs are 452 / section; `multi_ner_444` (~2.1M rows, in
  `releases/frozen_output/04_ner/multi_ner_444/`) is 444 / **document** granularity, a
  different build entirely. `releases/frozen_output/04_ner/README.md` is the authority
  for which number belongs to which denominator — read it before quoting.
* **Silent 512-token truncation** in the upstream BERT/GLiNER2 APIs:
  `cdm_pipeline.ner.chunking` sizes chunks to a real token budget on word
  boundaries instead (12.96% of fixed-2000-char chunks overflow). The legacy
  `gliner_medium`/`gliner_biomed` registry entries pin `max_tokens=None` to keep
  the frozen `zenodo_v1` baseline reproducible — do not copy that setting.
* **Java NER tools** (`cdm_pipeline.ner.java_tools`) are PubTator-format CLI
  apps, not Python libs. `~/tools/ner_tools/tools/` holds the extracted sources;
  `~/tools/ner_tools/java/jdk8u504-b01` the bundled JDK; `~/tools/ner_tools/dl/`
  the archives (root overridable via `CDM_NER_TOOLS`).
  They emit title+abstract coordinates — the runner submits `section_id` as a
  sentinel title and subtracts `len(title)+1`, and replaces `\n` with a
  same-length space. Preserve these conventions (documented in
  `java_tools.py`'s docstring) if you touch the integration.
* **NUL-byte corpus artifact**: 4 `data/papers_txt/` files (`PRJNA750230` 180,
  `PRJNA413199` 23, `PRJNA307231`/`PRJNA486009` 1 each) carry U+0000 where
  ﬁ/ﬂ ligatures collapsed at PDF extraction; it survives verbatim into 4
  `data/segmented_sections_markdown/` files (205 NULs; hash-pinned by corpus_v2
  2.2.0 `source_file_hash_sha256` — do NOT rewrite the markdown) and into
  122 shipped non-java variant-CSV rows (all `HMPAPER_000446`, slice-exact,
  pass `src/scripts/verify_ner_offsets.py` as `nul_explained`). The java runner
  (`java_tools.py`) strips U+0000 from `term` at emission since job 28649661;
  pre-2026-10-29 java copies and the `outputs/results/…/_work/prenul_*.bak` backups
  still contain them. `load_csv_safe` strips NULs on read (audits via it
  under-count); audit with a raw read.
* **Environments are per-group**: `~/venvs/ner_variants` (venv built by
  `src/scripts/setup_ner_variants_venv.sh`: spacy 3.7.5 + flair 0.15.1 + numpy<2,
  for `extra` and `hunflair2_trim`), and for `gliner_new`, gliner 0.2.29 /
  gliner2 2.1.0 installed `--no-deps` into `~/venvs/gliner_overlay` and
  layered on `/home/jkalra_hpc/venvs/vllm` (torch 2.13.0, transformers 5.19.0)
  via `PYTHONPATH`. Launch through the matching `.sbatch` — each one activates
  the right interpreter itself.

## Data catalogue (`releases/data_catalogue/`)

Built by Qwen extraction over every section (`src/scripts/vllm_termpop/catalogue_ner.py`
→ `catalogue_finalize.sbatch`). **453 papers / 56,985 records**: findings 21,439,
assays 12,116, cohorts 9,575, samples 8,484, datasets 3,228, data_assets 2,143.
Coverage **3,443/4,006 sections complete, 90.857% chars, 127 failed segments,
`REVIEW_REQUIRED`**; evidence exact 11,469 / reflowed 40,807 / not located 13,199.
`terminology/terminology_dedup.csv` = 166,012 terms;
`terminology/taxonomy/term_taxonomy_v1.{yaml,csv}` = 16 upper + 66 subcategories
(+ reserved `UNCERTAIN`). Bundle is checksummed (1,003 files) — its inner
`README.md` quotes pre-finalize counts; `MANIFEST.json` / `quality/quality_report.md`
are authoritative. All rows are **machine-extracted and unverified**.

## Controlled-vocabulary linking

* **Reuse-first linking** — `src/scripts/vllm_termpop/cv_link_terms.py` +
  `src/scripts/slurm/cv_link.sbatch` → `outputs/results/cv_linking/`. 71,538 typed
  `(term, cdm_type)` pairs; 94,474 generic `ENTITY` pairs skipped on purpose;
  35,063 reused from the CPU `mapped_entities.json`; 36,475 net-new. Checkpoint
  every 200; ~8.8 pairs/s @ 24 workers (8,135 s elapsed in `cv_summary.json`).
  Does **not** touch `src/cdm_pipeline/mapping/mappers.py`.
* **Local OMOP index** — `build_omop_index.py` → `outputs/results/omop_vocab/omop_index.sqlite`
  (5.68 GB; concept 10,167,185 / term 15,647,137 / `Maps to` 7,423,177).
  `omop_local.py` + `omop_link_terms.py` + `src/scripts/slurm/omop_link.sbatch` →
  `outputs/results/omop_linking/`. Exact normalized match only, `confidence` 1.0, follows
  `Maps to` to the standard concept. **Reported as a separate view, deliberately
  NOT added to `VOCAB_PRIORITY`.** Result: 9,615/71,538 (13.44%), 6,713 standard,
  21,881 links. `map_omop` in `mappers.py` stays a dead stub.
* **Taxonomy classifier** — `taxonomy.py` + `categorize_terms.py` (LLM-assisted;
  never invents categories) → `outputs/results/taxonomy_pilot/`. Pilot: 500 terms, 493
  assigned, 7 `UNCERTAIN`, 2 invented flagged, mean confidence 0.796. Full-table
  pass not run (`classified_terms: 0` in the exported artifact).
* Local CPU env is mandatory: `module use /opt/software/easybuild-AMD/modules/all;
  module load Python/3.12.3-GCCcore-13.3.0;
  source /home/jkalra_hpc/venvs/vllm/bin/activate; export PYTHONPATH="$PROJECT_ROOT/src"`
  — the Intel easybuild Python segfaults on EPYC nodes.

### Corpus & annotation data
- `data/papers_txt/` — 453 PRJ-accession-named `.txt` files (gitignored). `others/`
  holds scratch files a recursive `.txt` scan would ingest as bogus papers; the
  corpus-builder slurm wrapper stages top-level `*.txt` symlinks into `.staging/`
  — follow that pattern for any recursive scan.
- `data/segmented_sections_markdown/` — 453 `HMPAPER_*.md` section files (input to
  section-level NER and the terminology pipeline).
- `data/corpus/` — 453-record corpus: `corpus_tracking.csv`, `id_map.csv`,
  `records/`, `text/` (453 files), `annotations/findings.csv` (1,485 findings over
  31 papers, all `verification_status=pending`).
- `pipelines/corpus_v2/releases/2.2.0/` (canonical; `2.0.0`/`2.1.0` also present) — 453
  papers (447 canonical, 6 dup-excluded), 4,006 sections, 26,874,831 chars /
  7,909,432 tokens; validation `{REVIEW_REQUIRED 392, COMPLETE 46, PARTIAL 15}`;
  provenance chain: `releases/data_catalogue/README.md` ← `releases/data_catalogue/MANIFEST.json` ←
  `outputs/results/catalogue_ner_v2/_catalogue_summary.json`.
- `releases/zenodo_v1/` — **frozen export**: section-level NER bundle (CPU ensemble + Qwen
  section NER) with sha256 `MANIFEST_v1.txt`; stage via
  `src/scripts/slurm/zenodo_v1_move.sbatch`. Don't modify in place.
- `outputs/scratch/` — one-off probe scripts and pre-fix terminology snapshots
  (`pre_fix_snapshot/`); exploratory only, not part of any pipeline.
- `outputs/results/` — gitignored run outputs: `catalogue_ner_v2/`, `mesh_ner/`,
  `omop_vocab/`, `omop_linking/`, `taxonomy_pilot/`, `cv_linking/`,
  `llm_vs_ner_comparison/`, `llm_ner_body/`, `terminology_v1/`,
  `_termpipe_chain/` (local chain validation reference), plus per-job dirs
  `<jobid>_ner_*` (the five 2026-10 variant runs, `outputs/results/28643785…28649661…`)
  and `<jobid>_pubtator3_*` / `<jobid>_ner_eval_permodel/` (see Gotchas).
- Qwen LLM runs need Ollama **0.32.9+** (`ollama-bin/0.32.9`): the default `ollama`
  on PATH (0.11.10) rejects the qwen35 GGUF architecture — hence the
  `module unload ollama` in GPU wrappers.

## Lint, format, typecheck

- **Linters/formatters: ruff + black + isort** (root `pyproject.toml`; line-length
  100, target py39). Ruff selects `E,F,W,I,B,UP,C4` with py39-compat ignores — see
  `[tool.ruff.lint]`.
- **Pre-commit is the real local gate** (`pre-commit run --all-files`): gitleaks,
  `ruff --fix --exit-non-zero-on-fix`, black, isort. Scratch scripts are excluded
  via `extend-exclude`/`exclude` (the two configs list slightly different
  `standalone_pipeline.py` paths).
- **CI (`.github/workflows/ci.yml`) is non-blocking for lint** (ruff `--exit-zero`,
  black `|| true`) and still references the **old root-level `cdm_pipeline/` paths**
  — the import smoke tests will break until CI is updated for the `src/` layout.
  Run pre-commit locally before opening a PR.

## Testing

- `pipelines/llm_terms/` uses **unittest**; `spacy_terms/` (when restored) uses **pytest** —
  don't mix runners within a pipeline.
- Root tests (all unittest, run from repo root, **with `PYTHONPATH=src`**):
  - `PYTHONPATH=src python -m unittest tests.test_paths -v` — path resolution incl. env overrides.
  - `PYTHONPATH=src python -m unittest tests.test_cdm_pipeline -v` — config, utils, dedup, mapping.confidence, evaluation.
  - `PYTHONPATH=src python -m unittest tests.test_data_catalogue -v` — needs PyYAML (skips without it).
  - `PYTHONPATH=src python -m unittest tests.test_termpipeline -v` — **97 tests**, mocked externals, no live credentials.
  - `PYTHONPATH=src python -m unittest tests.test_release_gates -v` — gate logic with temp-dir fixtures; no production artifacts read.
  - `PYTHONPATH=src python -m unittest tests.test_integration -v` — **known-broken**: its `project_root` now resolves to the real repo root (it used to be `src/tests/`), which exposes 4 genuine failures: 3 because `spacy_terms/` is absent and 1 README-section check. Its CLI/import tests pass.
  - `tests.test_release_gates.test_cli_exit_codes` — **known-broken before the 2026-10-30 restructure**: its fixture has no calibration data and the test expects an `overall_status` key the CLI does not write, so G2/G5 report FAIL.
  - `tests.test_release_artifacts` — `releases/` now exists but holds only `terminology/1.0.0`; the DB release dirs (`v2.0-qwen-publication`, `v2.1-full-multiner`) are still absent, so those tests skip per-release.

## HPC (SLURM cluster)

- **Cluster (verify with `scontrol show config`)**: the current login node is
  `login01` on cluster **`marvin`** — *not* the "Genoa" cluster most launchers in
  `src/scripts/slurm/` were written for. Real partitions now:
  CPU `intelsr_{devel,short,medium,long}` (8 h / 24 h / 7 d), `arm_short`,
  `lm_*`, `vlm_*`; GPU `mlgpu_*` (**a40:8**) and `sgpu_*` (**a100:4**).
  There is **no `short`/`medium`/`long`, no `gpu-amd`/`gpu-nv`/`gpu-nvrtx`, and no
  mi200/h100/rtx6000. Repo launchers still request those names — remap them
  (`gpu-amd`→`mlgpu_short`/`sgpu_short`, `short`→`intelsr_short`,
  `medium`/`long`→`intelsr_medium`/`intelsr_long`) and replace
  `--gres=gpu:mi200:1`/`gpu:h100:1`/`gpu:rtx6000:1` with `gpu:a40:1` or
  `gpu:a100:1` before submitting. Check the walltime fits (`intelsr_short` 8 h,
  `intelsr_medium` 24 h, `intelsr_long` 7 d).
- **Modules (current cluster)**: `Miniforge3/24.1.2-0`, `Python/3.12.3-GCCcore-13.3.0`,
  `CUDA/12.9.1`. `ollama-bin/0.32.9`, `rocm/6.3.3`, `rocm/7.2.0` and
  `Miniforge3/24.11.3-0` referenced by the wrappers are **not installed here** —
  check `module avail` before trusting a launcher. Module root is
  `/opt/software/easybuild-AMD/modules/all` (also `-INTEL`, `-ARM`).
- **Python envs**: no `microbiome-cdm-env` conda env exists here. Working CPU
  interpreter is `/home/jkalra_hpc/venvs/vllm/bin/python` (Python 3.12.3, used by
  the terminology/OMOP tooling); `pipelines/llm_terms/` has its own venv. Two more
  venvs serve the 2026-10 NER variants: `~/venvs/ner_variants` (spacy+flair, built
  by `src/scripts/setup_ner_variants_venv.sh`) and `~/venvs/gliner_overlay`
  (`--no-deps` gliner 0.2.29 + gliner2 2.1.0 layered on `venvs/vllm` via
  `PYTHONPATH`) — the section python explains which group needs which. Note
  `requirements.lock`'s torch==2.1.1+cpu / scipy==1.10.1 have **no cp312 wheels**,
  so `setup_ner_variants_venv.sh` deliberately pins nearest-compatible releases
  instead. Heavy NER jobs otherwise install from `requirements.lock` +
  `pip install gliner==0.2.26 --no-deps` (gliner's deps conflict with pinned
  transformers).
- **Launchers**: `src/scripts/slurm/` holds the real HPC entry points — 41 files
  (25 `.sbatch`, 14 `.sh`, 2 `.slurm`) after the 2026-10-30 prune (11 moved out,
  see `outputs/scratch/removed_launchers/README.md`).
  Key ones: `ner_453_sections.sbatch` (CPU ensemble over
  segmented sections), the five 2026-10 variant launchers
  (`ner_{bert_variants,extra_variants,hunflair2_trim,gliner_new,java_tools}.sbatch`,
  see the variant-runs section), `qwen_sections_ner.sbatch` (GPU + Ollama qwen
  section NER), `mesh_ner.sbatch` (CPU MeSH gazetteer), `cv_link.sbatch` (CPU CV
  linking), `omop_link.sbatch` (CPU local OMOP), `termpipe_v1.sbatch` (CPU
  terminology chain), `compare_llm_vs_ner.sbatch`, `ner_444_rerun.sbatch`,
  `findings_full_corpus.sbatch`, `triple_extraction_slurm.sh`,
  `llm_entity_cleanup_gpu.slurm`. sbatch from repo root; logs land in `outputs/logs/`,
  outputs in `outputs/results/${SLURM_JOB_ID}_*/` (gitignored, made read-only on
  completion). **26 launchers hardcode `PROJECT_ROOT="/home/jkalra/Microbiome-CDM"`**
  (nonexistent); the real repo is `/home/jkalra_hpc/Microbiome-CDM`. Patch
  `PROJECT_ROOT` or export the correct one before submitting.
- **Ollama on GPU nodes**: scripts start a node-local `ollama serve` (port 11434 or
  11444 to dodge conflicts) with `OLLAMA_MODELS="$PROJECT_ROOT/.ollama/models"`,
  wait for `/api/tags` before pulling/running, and `module unload ollama` first
  (see Qwen GGUF note above). Reuse this pattern for any new LLM-using script.
  `ollama-bin` is **not installed on `marvin`** — Qwen-Ollama jobs need it staged
  or an alternative runtime.
- **vLLM on GPU nodes**: `qwen_sections_vllm.py` and the catalogue/taxonomy
  launchers start a node-local vLLM server on an A40; `src/scripts/vllm_termpop/*_a40.sbatch`.
  The runner checkpoints per-segment results, so a timed-out job resumes.
- **GPU sharing**: run models sequentially on a single GPU. Qwen batch jobs are
  checkpoint/resume (e.g. `qwen_batch_checkpoint.json`, `_vllm_sections_cache.json`,
  `_qwen_sections_cache.json`) — a timed-out job can be resubmitted and continues.
- **`.env` is NOT auto-sourced by SBATCH** — jobs that need keys must `source .env`
  (as `cv_link.sbatch` does). `intelsr_short` = 8:00:00 walltime; the CV job ran
  ~2.3 h and resumes from `cv_checkpoint.json`.
- **SBATCH snapshots the script at submit time** — editing a `.sbatch` requires
  cancel+resubmit; editing the referenced `.py` does not affect a running process.

## Reference paper & canonical DB

> Abdill, R. J., et al. (2025). *Integration of 168,000 samples reveals global patterns of the human gut microbiome.* **Cell** 188(4):1100–1118.e17. DOI: [10.1016/j.cell.2024.12.017](https://doi.org/10.1016/j.cell.2024.12.017).

The reference paper reports 168K samples / 482 BioProjects; this repository's CDM
is built on its **cited literature** (the 453-paper corpus, expanded from 444),
not on the 168K-sample compendium. The working DB's `projects` table has 444 rows
and its `samples` table is empty — do not claim results on the compendium.

**Manuscript corpus-scope warning** (see `releases/frozen_output/05_evidence/README.md`):
the manuscript describes a **452-paper** corpus (453 on disk minus
`HMPAPER_000372`), but its entity/relationship totals come from the
**444-paper extraction build** (441 of the 452 papers + `HMPAPER_000372` + 2
accessions outside the corpus — stated explicitly in its Abstract, §3.2,
Table 8). Its 34,818 entities are **not interchangeable** with the later HMCV2
2.1.0 build's 37,907 (`releases/frozen_output/01_corpus/data/entities.jsonl`). Cite the
number for the build you mean; `docs/DATA_SEMANTICS.md` disambiguates further.

### Releases

`releases/` currently holds **only** `releases/terminology/1.0.0/` (frozen
terminology build, ledger digest `a5c1ae90…2b48`) plus `releases/RELEASES.md`
(append-only ledger). Historically it also held versioned DB bundles
(v2.0-qwen-publication frozen manuscript DB — every paper number traces there, do
not rebuild; v2.1-full-multiner parent build; v3.0-cdm OMOP-aligned); those are
**absent** from the working tree. `paper_claims/` holds only `manuscript/` +
`_multi_ner_runs/` (no `CLAIMS.md`, no `claim_*` dirs); `manuscript/PROJECT_STATUS.md`
is the old **444-paper** claim summary (2026-08-27) — historical, not the
453-paper build. The working build DB
**is present** at `paper/_multi_ner_runs/cdm_output/microbiome_cdm.db`
(360 MB; 113,517 entities / 858,145 relationships / 444 projects; no
`run_metadata` or `edge_evidence` table in this build). Corpus releases are
separate: `pipelines/corpus_v2/releases/{2.0.0,2.1.0,2.2.0}/`.

## Code style

- Python 3.9+ floor (`requires-python = ">=3.9"`); on this cluster the working
  CPU interpreter is Python 3.12 (`venvs/vllm`).
- Optional / heavy dependencies are wrapped in `try/except ImportError` with an
  `*_AVAILABLE` flag rather than hard requirements — follow this pattern for new
  optional integrations.
- API keys (UMLS, BioPortal, HuggingFace, OpenAI, Entrez) read from environment
  variables only — never hardcode.
- `src/cdm_pipeline/entrez/` is a PEP 420 namespace package (no `__init__.py`) —
  imported as `cdm_pipeline.entrez.*`; keep `namespaces = true` in `pyproject.toml`.
- `src/common/__init__.py` duplicates `CDM_TYPES` (and adds `CDM_TYPES_EXTENDED`,
  `LABEL_TO_CDM`, `norm`) — it **must stay in sync** with
  `src/cdm_pipeline/config.py:CDM_TYPES`. `corpus_builder/` has no `__init__.py`
  and is not in `[tool.setuptools.packages.find]` (only `cdm_pipeline*` + `common*`),
  so it works only via `PYTHONPATH=src`.
- `src/configs/canonical.yaml` claims to be the single source of truth for model
  selection/vocab, but it still references the old root `cdm_pipeline/` path and
  the nonexistent `microbiome-cdm-env`; verify against code before citing it.

### Hands-off files (do not modify without explicit per-file ask)
- `pipelines/llm_terms/scripts/standalone_pipeline.py` (~305 KB) — user's active dev/test scratch for the LLM pipeline.
- `spacy_terms/standalone_scispacy_pipeline.py` — user's scratch for the spaCy pipeline (directory currently absent).
- Safe-to-edit canonical production entry points: `pipelines/llm_terms/scripts/kg_pipeline.py` and `pipelines/llm_terms/Output_final/scripts/kg_pipeline.py`.
- `releases/zenodo_v1/`, `releases/data_catalogue/`, `releases/`, and `releases/frozen_output/` are frozen
  or checksummed bundles — do not modify any of them in place. New work writes
  to `outputs/results/`.

## Gotchas (learned the hard way)

- **`PYTHONPATH=src` is the #1 footgun** in the new layout — see top of file.
- **The `src/` move broke `parents[2]` in subpackages.** Modules directly under
  `src/cdm_pipeline/` (`paths.py`, `cdm_schema_alignment.py`) resolve `parents[2]`
  to the repo root correctly, but subpackage modules (`triples/eco_mapper.py`,
  `export/build_zenodo_bundle.py`, `entrez/*.py`) still assume the old root-level
  layout, so their `parents[2]` is `src/`. Default paths such as
  `paper/_multi_ner_runs/cdm_output`, `data/reference/ontologies/eco_canonical.owl`, and
  `.env` therefore point under `src/`. Patch to `parents[3]` or override before
  running those modules.
- **`vllm_sections_ner.csv` now exists** for `llm-ner-body` (366,123 rows,
  cache 0 errored) and `termpipe_v1`'s `afterany` chaining consumes it as the
  `qwen_vllm_body` source. If it ever goes missing, T1 reports that source as
  `status: MISSING` rather than substituting; regenerate with `--assemble` (or
  `repair_sections_cache.py --assemble`). Recovery is cache-only — never a rerun.
- **Truncation diagnosis for `llm-ner-body`**: failing segments emit until
  `max_tokens`, truncating at ~9.0–13.5K output chars **independent of input
  length**; `split:` retries fail at the identical char offset. vLLM is not
  bit-deterministic at `temperature=0`, so retries recovered most (160→90→68→15).
  Repair, not a full rerun, is the fix. `LLM_MAX_TOKENS` **is** in `cache_key`, so
  the main runner stays at 4096 and the repair script uses its own ladder;
  `MAX_SPLIT_DEPTH`/`SPLIT_MIN_CHARS` are **not** in the key, so retuning them is
  cache-safe. Entities are `{"text","type"}` with **no offsets** — offsets are
  recomputed later, so split-merge concatenation is offset-safe.
- **PubTator3 originally resolved only ~300 papers** — the parent run
  (`paper/_multi_ner_runs/pubtator3_ner.csv`) uses a title-only esearch
  lookup from `src/cdm_pipeline/ner/pubtator.py`. A backfill
  (`outputs/results/28608086_pubtator3_backfill/`, retry `outputs/results/28608146_.../`) raised
  coverage to **438/453 papers** (300 parent + 134 + 4) via PMID-direct → DOI →
  title esearch. The **final 15 are terminal** (9 `NO_PMID`, 6
  `ZERO_ANNOTATIONS`) after job `28621620`; its
  `outputs/results/28621620_pubtator3_final15/pubtator3_ner_all453_harmonized.csv` is the
  harmonized all-453 union (4,413 unique rows over 438 papers). It is still
  **not consolidated** into a stable dir — treat `outputs/results/<jobid>_pubtator3_*` as
  the source. PubTator3 offsets are `0,0` with **PubMed abstract/passage
  geometry**, not corpus section text, so they cannot be used for
  section-relative span work. Also excluded from section-mode NER
  (`predict_text` not implemented).
- **`docs/cdm_design/` + `src/template/cdm/` are a design-phase proposal only**
  (DRAFT 0.1.0): `cdm_schema.json`, `cdm_field_crosswalk.md`,
  `cdm_relationships.md`, `cdm_validation_specification.md`,
  `cdm_migration_risks.md`. No migration is implemented — do not treat the
  proposed 33-entity schema as built.
- **Per-model NER evaluation** exists (`outputs/results/28608*_ner_eval_permodel/`:
  `metrics_full.json`, `ner_comparison_metrics.csv`, report + permutation tests)
  but is **not consolidated** into a stable dir; it reports agreement per model,
  not accuracy, and the Qwen side is the historical Ollama run.
- **`en_core_sci_lg` returns a generic `ENTITY` label for every term** — never maps
  cleanly to CDM types; a 0% score on it is a label-mapping artifact. spaCy
  `relevance_score` is degenerate (single distinct value) — don't feed it to
  calibration metrics.
- **GLiNER + PubMedBERT want GPU.** On `marvin` use CUDA (`sgpu_*` a100 or
  `mlgpu_*` a40); the ROCm/MI200 path in old launchers is unavailable.
- **Two dirs named "fulltext"**: repo-root `data/fulltext/` (73 JATS XMLs from
  `download_corpus_pdfs.py`) vs `data/168000-samples-paper/fulltext/` (compendium
  metadata source) — `paths.py` keeps them distinct.
- **Do not trust `wc -l` on catalogue CSVs** — evidence-quote fields contain
  embedded newlines. Use `MANIFEST.json` / the summary JSONs for row counts.
- **MeSH internals**: tree numbers are `<3-char branch>.<sub>...`; MeSH 2026 XML
  has no `<EntryTerm>` — entry terms live in
  `ConceptList/Concept/TermList/Term/String`; supplementals link via
  `HeadingMappedToList`. `pyahocorasick` exposes no `__version__`.
- **`/usr/bin/time` does not exist on this cluster.** Use shell `time` or measure
  in Python. `unzip -p` (not `unzip -o -d`) is required for the OMOP zip because
  the filename contains `{}`.
- **`hive`/builtin `hash()` is salted per process** — never use it for output ids.
  `src/scripts/termpipeline/ids.py` uses sha1 over 0x1f-joined parts.
- **`archive/`, `/.ollama/`, `.staging/` are gitignored reorg artifacts** — don't
  commit relocations into them.

## PR, commit, and security conventions

- **This working tree has no `.git/`** (see top); the guidance below applies only
  if git metadata is restored or the repo is re-cloned.
- Branch from `main`; never push to `main` directly. **No `git push` without
  explicit go-ahead** — all commits stay local until the user says push.
- Commit messages: short, imperative summary. Open PRs via `gh pr create` once the
  relevant test command(s) pass.
- Never commit secrets — `.env` is gitignored at the root; `.env.example` ships
  with no secrets. Externally sourced lookups send **minimum term-level
  information only**, never full paper text, with caching keyed on
  source/query/timestamp/version; distinguish **no-match** from **failed lookup**.
- If a key is ever disclosed, **rotate it**; keys must never appear in logs,
  manifests, outputs, tests, or source.
- Large data files, model binaries, generated databases, `data/papers_txt/`, `pdfs/`,
  `outputs/results/`, and `*.db` are gitignored — do not commit them. `CLAUDE.md` is
  gitignored by design (local Claude Code config).
