# Current frozen set (2026-11-02)

The one place to find every **current, frozen** component of the resource. Entries are symlinks to the frozen releases, not copies, so nothing is duplicated and every file stays under its original manifest.

Run `./VERIFY.sh` to check all components against their manifests.

| Link | Points to | What it is | Integrity |
|---|---|---|---|
| `01_corpus_release/` | `pipelines/corpus_v2/releases/2.2.0` | Corpus release 2.2.0: 453 papers (447 publications), studies, findings index, corpus manifest | own `MANIFEST.sha256` (42 files) |
| `02_corpus_segmented/` | `releases/frozen_output/01_corpus/data` | **Segmented corpus:** `papers.jsonl` (453 papers), `sections.jsonl` (4,006 sections, each with a SHA-256 of its text), `segments.jsonl`, plus corpus-stage entities, findings and triples | `frozen_output/MANIFEST.sha256` (18 / 18 files) |
| `03_corpus_markdown/` | `releases/frozen_output/01_corpus/segmented_sections_markdown` | **Corpus as markdown:** one `HMPAPER_*.md` per paper, with section headings (453 files + `_conversion_report.json`) | `frozen_output/MANIFEST.sha256` (454 / 454) |
| `04_ner_per_model/` | `releases/frozen_output/04_ner` | **Raw NER output, one CSV per model** (table below) | `frozen_output/MANIFEST.sha256` (42 / 42) |
| `05_terminology/` | `releases/terminology/1.0.1` | **Terminology 1.0.1:** `term_mentions.jsonl` (2,505,735 mentions from all sources, each tagged with its source run and model), `canonical_terms.jsonl` (165,991 terms), mappings, definitions, taxonomy | own `MANIFEST.sha256` (23 files) |
| `06_data_catalogue/` | `releases/data_catalogue_v3/3.1.1` | **Data catalogue 3.1.1:** 52,400 evidence-quoted records (cohorts, sample groups, assays, datasets, data assets, findings) | own `MANIFEST.sha256` (45 files) |
| `07_common_data_model/` | `releases/cdm_v3/3.0.3` | **CDM 3.0.3 (current):** `microbiome_cdm_v3.db` (SQLite, 44 tables) integrating the corpus, terminology (162,409 terms after review), catalogue, triples and run registry; data dictionary and remediation reports in `remediation/` | own `MANIFEST.sha256` (36 files) |

## Terminology by source

In the terminology and the CDM, every mention keeps its source, recorded as `extraction_run_id` and `extraction_model`. Mentions per source in CDM 3.0.3 (`term_mention`):

| Run (`extraction_run_id`) | Kind | Model (`extraction_model`) | Mentions |
|---|---|---|---:|
| `cpu_ensemble_v1` | NER models | en_core_sci_lg (scispaCy) | 960,674 |
| | | gliner_biomed | 297,113 |
| | | gliner_medium | 168,027 |
| | | en_ner_craft_md (scispaCy) | 119,092 |
| | | en_ner_bc5cdr_md (scispaCy) | 80,584 |
| | | en_ner_jnlpba_md (scispaCy) | 52,989 |
| | | biobert_diseases | 26,970 |
| `qwen35_vllm_body_v1` | **LLM** | Qwen/Qwen3.5-4B (vLLM, section bodies) | 366,123 |
| `qwen_ollama_cell7c_v1` | **LLM** | qwen3.5:4b (Ollama) | 186,024 |
| `mesh_gazetteer_2026` | dictionary | MeSH gazetteer | 248,088 |

**To get one source's terms:**
- In the CDM: `SELECT * FROM term_mention WHERE extraction_model = 'gliner_medium';`
- In the release: filter `05_terminology/term_mentions.jsonl` on the same fields.

## Raw NER output per model (`04_ner_per_model/`)

| Folder | Models (one CSV each) |
|---|---|
| `section_ner_453/` | GLiNER, GLiNER-biomed, PubMedBERT, scispaCy bc5cdr / craft / jnlpba / lg (plus a combined file) |
| `section_ner_bert_variants_452/` | BERT chemical / disease / genetic, SciBERT-JNLPBA |
| `section_ner_gliner_new_452/` | GLiNER2 base / large, GLiNER v2.5 medium / biomed |
| `section_ner_hunflair2_trim_452/` | HunFlair2 |
| `section_ner_extra_variants_452/` | scispaCy bionlp13cg |
| `section_ner_java_tools_452/` | DNorm, GNormPlus, TaggerOne (chemical, disease), tmChem |
| `qwen_sections_ner/` | **LLM:** Qwen over sections |
| `multi_ner_444/` | earlier 444-paper multi-NER run, incl. PubTator3 (historical) |

The benchmark runs (21 systems on public test sets and the 453-paper corpus) live separately in `outputs/results/benchmark/`. They are frozen by `paper/publication/final_validation/FINAL_VALIDATION_MANIFEST.sha256`.

## Not in this set, on purpose

- **Raw input text** (`data/papers_txt/`, `data/corpus/text/`) is gitignored input. The frozen text is `sections.jsonl` (hash-verified) and the CDM `section` table.
- **`releases/frozen_output/03_common_data_model/`** is an **older CDM (build 2.1.0, 2026-10-29)**, superseded by `07_common_data_model` (3.0.3). It is kept for history.
- Earlier releases (terminology 1.0.0, catalogue 3.0.0 / 3.1.0, CDM 3.0.0–3.0.2) stay in `releases/` for provenance.

The release ledger is `releases/RELEASES.md`.
