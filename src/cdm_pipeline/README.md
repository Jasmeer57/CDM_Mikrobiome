# Microbiome CDM Pipeline (`cdm_pipeline/`)

Modular Python package for biomedical entity extraction, ontology mapping, and Common Data Model (CDM) construction from a 444-paper microbiome research corpus. Compares four NLP-based Named Entity Recognition (NER) models against an LLM-based extractor (Qwen 3.5:9b via Ollama) for both **intra-NLP** (model-to-model) and **inter-NLP-vs-LLM** (ensemble vs. generative) evaluation.

---

## Architecture

```
                    papers_txt/ (444 .txt files)
                           |
                           v
              +-------------------------+
              |   Stage 1: Multi-NER    |  cdm_pipeline/ner/
              +-------------------------+
              |  GLiNER  (zero-shot)    |  -> gliner_ner.csv
              |  PubMedBERT (fine-tuned)|  -> pubmedbert_ner.csv
              |  PubTator3 (NCBI API)   |  -> pubtator3_ner.csv
              |  sciSpaCy (4 models)    |  -> scispacy_ner.csv
              +-------------------------+
                           |
                           v
              +-------------------------+
              | Stage 2: Deduplication  |  -> deduplicated_entities.json
              +-------------------------+
                           |
                           v
              +-------------------------+
              | Stage 3: Ontology Map   |  cdm_pipeline/mapping/
              +-------------------------+
              | OLS, UMLS, BioPortal,   |  -> mapped_entities.json
              | OMOP, NCBI Taxonomy     |  -> mapping_summary.json
              +-------------------------+
                           |
                           v
              +-------------------------+
              | Stage 4: CDM Build      |  cdm_pipeline/cdm/
              +-------------------------+
              | Corpus + Database + OWL |  -> microbiome_cdm.db
              | Catalogue + Provenance  |  -> microbiome_cdm.owl
              +-------------------------+
                           |
                           v
              +-------------------------+
              | Stage 5: LLM NER (HPC)  |  cdm_pipeline/qwen_batch.py
              +-------------------------+
              | Qwen 3.5:9b via Ollama  |  -> llm_terms/output/*.json
              +-------------------------+
                           |
                           v
              +-------------------------+
              | Stage 6: Evaluation     |  (intra-NLP + inter-NLP/LLM)
              +-------------------------+
              | Gold standard, P/R/F1,  |  -> evaluation results
              | overlap, type coverage  |
              +-------------------------+
```

---

## Package Structure

```
cdm_pipeline/
├── __init__.py
├── config.py                  # Shared config: paths, CDM types, vocab priority, API keys
├── utils.py                    # Shared utilities: junk detection, normalization, CSV I/O
├── qwen_batch.py              # LLM batch runner (Qwen 3.5:9b, checkpoint/resume)
│
├── ner/                        # Stage 1: Named Entity Recognition
│   ├── __init__.py
│   ├── gliner.py               # GLiNER zero-shot NER
│   ├── pubmedbert.py           # BioBERT/PubMedBERT fine-tuned NER
│   ├── pubtator.py             # PubTator3 via NCBI E-utilities + PubTator3 API
│   ├── scispacy.py             # sciSpaCy 4-model NER
│   └── runner.py               # CLI orchestrator for all NER models
│
├── mapping/                    # Stage 3: Ontology mapping
│   ├── __init__.py
│   ├── mappers.py              # OLS, UMLS, BioPortal, OMOP, NCBI Taxonomy mappers
│   ├── confidence.py           # Canonical resolution + confidence scoring
│   └── runner.py               # CLI orchestrator for mapping
│
└── cdm/                        # Stage 4: CDM construction
    ├── __init__.py
    ├── corpus.py               # Unified entity corpus builder
    ├── database.py             # SQLite CDM database (8 tables, 24 indexes, 8 views)
    ├── ontology.py             # OWL ontology (RDFLib)
    ├── catalogue.py            # Data catalogue (per-paper metadata)
    ├── provenance.py           # Provenance tracking
    └── builder.py              # Orchestrator — runs all 5 CDM steps
```

---

## CDM Entity Types (14)

The pipeline extracts and classifies entities into 14 microbiome-relevant types:

| Type | Description | Example |
|------|-------------|---------|
| `ORGANISM` | Bacteria, viruses, archaea, fungi | *Bacteroides fragilis* |
| `CHEMICAL` | Metabolites, drugs, compounds | butyrate, metformin |
| `DISEASE` | Diseases, conditions | inflammatory bowel disease |
| `PROTEIN` | Genes, proteins, enzymes | butyryl-CoA transferase |
| `DNA_RNA` | DNA/RNA sequences, genes | 16S rRNA, *fliC* gene |
| `CELL_TYPE` | Cell types, cell lines | T-helper cells, Caco-2 |
| `GENOMICS` | Genomic features, variants | SNPs, gene clusters |
| `PATHWAY` | Biological pathways | TCA cycle, glycolysis |
| `LAB_METHOD` | Laboratory methods | DNA extraction, PCR |
| `DATA_ANALYSIS` | Computational methods | Shannon index, PCoA |
| `SAMPLE_METHOD` | Sample collection methods | fecal sampling |
| `CLINICAL` | Clinical concepts | dosage, treatment duration |
| `EXPERIMENTAL_METHOD` | Experimental designs | gnotobiotic mice |
| `STUDY_DESIGN` | Study design concepts | cohort, case-control |

---

## Controlled Vocabularies (15+)

Entities are mapped to canonical concepts across 15+ biomedical ontologies:

| Vocabulary | Coverage | CDM Types |
|-----------|----------|-----------|
| **UMLS** | General biomedical (43,708 mappings) | All types |
| **MeSH** | Medical subject headings | All types |
| **NCBI Taxonomy** | Organism names | ORGANISM |
| **CheBI** | Chemical entities | CHEMICAL, PROTEIN |
| **DOID** | Disease ontology | DISEASE |
| **MONDO** | Monarch disease ontology | DISEASE |
| **SNOMED CT** | Clinical terminology | DISEASE, CLINICAL, ORGANISM |
| **Gene Ontology (GO)** | Biological processes, functions | PROTEIN, PATHWAY |
| **PR** | Protein ontology | PROTEIN |
| **Sequence Ontology (SO)** | DNA/RNA features | DNA_RNA, GENOMICS |
| **Cell Ontology (CL)** | Cell types | CELL_TYPE |
| **OBI** | Biomedical investigations | LAB_METHOD, SAMPLE_METHOD |
| **STATO** | Statistics ontology | DATA_ANALYSIS |
| **EDAM** | Bioinformatics operations | DATA_ANALYSIS |
| **Reactome/WikiPathways** | Biological pathways | PATHWAY |
| **OMOP** | OMOP vocabulary | Multiple |
| **RxNorm** | Clinical drugs | CHEMICAL |
| **ICD-9/10** | Disease classification | DISEASE |

---

## Running the Pipeline

### Prerequisites

- Python 3.9+ (tested with 3.9 venv at `spacy_terms/.venv39/`)
- GPU recommended for GLiNER and PubMedBERT (NVIDIA RTX 5080, 16GB VRAM)
- Ollama server (for LLM NER) at `http://localhost:11434` with `qwen3.5:9b` model
- API keys as environment variables:
  - `UMLS_API_KEY` — UMLS Terminology Services
  - `BIOPORTAL_API_KEY` — BioPortal REST API
  - `ENTREZ_API_KEY` — NCBI Entrez (optional, raises rate limit)

```bash
export UMLS_API_KEY="your-key"
export BIOPORTAL_API_KEY="your-key"
export ENTREZ_API_KEY="your-key"
```

### Stage 1: Multi-NER Extraction

Run all four NER models on the 444-paper corpus:

```bash
python -m cdm_pipeline.ner.runner --models all --max_files 500
```

Run individual models:

```bash
python -m cdm_pipeline.ner.runner --models gliner
python -m cdm_pipeline.ner.runner --models pubmedbert
python -m cdm_pipeline.ner.runner --models pubtator
python -m cdm_pipeline.ner.runner --models scispacy
```

Incremental mode (skip already-processed papers, append to existing CSV):

```bash
python -m cdm_pipeline.ner.runner --models scispacy --incremental
```

CLI options:

| Flag | Default | Description |
|------|---------|-------------|
| `--models` | gliner pubmedbert pubtator | Which models to run (`all` = all 4) |
| `--max_files` | 500 | Maximum papers to process |
| `--incremental` | off | Skip papers already in output CSV |
| `--threshold` | 0.5 | GLiNER confidence threshold |
| `--api_key` | `$ENTREZ_API_KEY` | NCBI Entrez API key for PubTator3 |

**Output** (in `paper_claims/_multi_ner_runs/`):

| File | Models | Rows | Description |
|------|--------|------|-------------|
| `gliner_ner.csv` | GLiNER | ~186K | Zero-shot NER, 14 CDM types |
| `pubmedbert_ner.csv` | BioBERT/PubMedBERT | ~321K | Fine-tuned disease/chemical/gene NER |
| `pubtator3_ner.csv` | PubTator3 API | ~2.3K | NCBI-curated annotations (DISEASE, CHEMICAL, GENE, ORGANISM) |
| `scispacy_ner.csv` | 4 sciSpaCy models | TBD | Domain-specific NER |
| `all_ner_combined.csv` | All | ~510K+ | Merged output |
| `_multi_ner_summary.json` | — | — | Per-model statistics |

#### NER Model Details

**GLiNER** (`ner/gliner.py`) — Zero-shot NER with 14 CDM type labels. Threshold-tunable. GPU-accelerated.

**PubMedBERT** (`ner/pubmedbert.py`) — Microsoft BiomedNLP-PubMedBERT-MNLI-MedNLI fine-tuned for biomedical NER. Detects DISEASE, CHEMICAL, ORGANISM, PROTEIN, DNA_RNA, CELL_TYPE, GENOMICS.

**PubTator3** (`ner/pubtator.py`) — NCBI's PubTator3 API. Searches PubMed by paper title (using clean titles from `bioproject_data_export.json` when available, falls back to text extraction) to retrieve PMID, then fetches curated annotations. Covers DISEASE, CHEMICAL, GENE/PROTEIN, ORGANISM, CELL_TYPE, DNA/RNA, VARIANT.

**sciSpaCy** (`ner/scispacy.py`) — Four specialized models run per document:

| Model | Corpus | Labels | CDM Mapping |
|-------|--------|--------|-------------|
| `en_core_sci_lg` | General biomedical | ENTITY | ENTITY (broad) |
| `en_ner_bc5cdr_md` | BC5CDR | DISEASE, CHEMICAL | DISEASE, CHEMICAL |
| `en_ner_craft_md` | CRAFT | GGP, SO, TAXON, CHEBI, CL | PROTEIN, DNA_RNA, ORGANISM, CHEMICAL, CELL_TYPE |
| `en_ner_jnlpba_md` | JNLPBA | DNA, RNA, PROTEIN, CELL_TYPE | DNA_RNA, PROTEIN, CELL_TYPE |

### Stage 2: Deduplication

Deduplicates raw NER output across all models to produce a unified entity registry:

```bash
python -m cdm_pipeline.dedup  # (or use the standalone dedup script)
```

**Output**: `paper_claims/_multi_ner_runs/deduplicated_entities.json` (36,481 unique entities)

### Stage 3: Ontology Mapping

Maps each deduplicated entity to controlled vocabulary concepts:

```bash
python -m cdm_pipeline.mapping.runner
```

Queries (in parallel, 12 workers):
- **OLS** (Ontology Lookup Service) — EBI REST API
- **UMLS** — UMLS Terminology Services (REST API)
- **BioPortal** — NCBO BioPortal REST API
- **OMOP** — OMOP vocabulary (local)
- **NCBI Taxonomy** — Entrez E-utilities

Checkpoint/resume support — saves every 500 entities to `mapping_checkpoint.json`.

**Output**:

| File | Description |
|------|-------------|
| `mapped_entities.json` | 34,767 mapped entities with canonical concepts + all mappings |
| `mapping_summary.json` | Summary: 95.3% mapping rate, by-type, by-vocab breakdown |
| `mapping_checkpoint.json` | Resume checkpoint |

### Stage 4: CDM Construction

Builds the complete Common Data Model:

```bash
python -m cdm_pipeline.cdm.builder
```

Runs all 5 steps:
1. **Corpus** (`corpus.py`) — Unified entity corpus from mapped entities
2. **Database** (`database.py`) — SQLite CDM database
3. **Ontology** (`ontology.py`) — OWL ontology (RDFLib)
4. **Catalogue** (`catalogue.py`) — Data catalogue (per-paper metadata)
5. **Provenance** (`provenance.py`) — Provenance tracking

**Output** (in `paper_claims/_multi_ner_runs/cdm_output/`):

| File | Size | Description |
|------|------|-------------|
| `microbiome_cdm.db` | 247 MB | SQLite database (8 tables, 24 indexes, 8 views) |
| `microbiome_cdm.owl` | ~420K triples | OWL ontology |
| `unified_entity_corpus.json` | — | Unified entity corpus |
| `db_statistics.json` | — | Database statistics |

**CDM Database schema** (8 tables):
- `entities` — 29,954 unique entities
- `cv_mappings` — 189,250 controlled vocabulary mappings
- `relationships` — 914,413 co-occurrence relationships
- `projects` — 444 BioProject entries
- `entity_project_mentions` — 68,950 entity-paper mentions
- `provenance` — Pipeline execution provenance
- `db_stats` — Database statistics
- `catalogue` — Data catalogue

### Stage 5: LLM NER (Qwen 3.5:9b)

Batch LLM-based entity extraction using Qwen 3.5:9b via Ollama. Designed for HPC execution:

```bash
# Ensure Ollama is running with qwen3.5:9b model
ollama pull qwen3.5:9b

# Run on all 444 papers (sequential, checkpoint/resume)
python -m cdm_pipeline.qwen_batch
```

Features:
- Sequential execution (GPU memory constraint)
- Checkpoint/resume (`llm_terms/output/qwen_batch_checkpoint.json`)
- Per-paper timeout (900s)
- Error handling per-paper
- Thinking mode disabled (`"think": False` in `llm_terms/core/llm_client.py`)

**Output** (in `llm_terms/output/`):
- `{PRJ_ID}.cdm_entities.json` — Per-paper LLM extracted entities
- `qwen_batch_checkpoint.json` — Resume checkpoint
- `qwen_batch_summary.json` — Batch run summary

---

## Running on HPC

### 1. Clone and set up environment

```bash
git clone https://github.com/SCAI-BIO/Microbiome-CDM.git
cd Microbiome-CDM

# Create venv (Python 3.9+)
python3.9 -m venv .venv
source .venv/bin/activate
pip install -r spacy_terms/requirements.txt
python -m spacy download en_core_sci_lg
python -m spacy download en_ner_bc5cdr_md
python -m spacy download en_ner_craft_md
python -m spacy download en_ner_jnlpba_md
```

### 2. Set API keys

```bash
export UMLS_API_KEY="your-key"
export BIOPORTAL_API_KEY="your-key"
export ENTREZ_API_KEY="your-key"
export ENTREZ_EMAIL="microbiome.cdm@gmail.com"
```

### 3. Run NLP NER (if not already done)

```bash
# Run all 4 NER models on 444 papers
python -m cdm_pipeline.ner.runner --models all

# Or incremental (skip already processed)
python -m cdm_pipeline.ner.runner --models scispacy --incremental
```

### 4. Run LLM NER (Qwen 3.5:9b)

```bash
# Install Ollama on HPC node
curl -fsSL https://ollama.com/install.sh | sh

# Start Ollama server (background)
ollama serve &
sleep 5

# Pull model
ollama pull qwen3.5:9b

# Run batch LLM NER on all 444 papers
python -m cdm_pipeline.qwen_batch

# Resume if interrupted (checkpoint auto-loads)
python -m cdm_pipeline.qwen_batch
```

### 5. Run ontology mapping + CDM build

```bash
python -m cdm_pipeline.mapping.runner
python -m cdm_pipeline.cdm.builder
```

### 6. SLURM script (optional)

```bash
#!/bin/bash
#SBATCH --job-name=microbiome-cdm
#SBATCH --partition=gpu
#SBATCH --gres=gpu:1
#SBATCH --mem=32G
#SBATCH --time=24:00:00

source .venv/bin/activate
export UMLS_API_KEY=$1
export BIOPORTAL_API_KEY=$2

# Stage 1: NLP NER
python -m cdm_pipeline.ner.runner --models all

# Stage 5: LLM NER
ollama serve &
sleep 10
python -m cdm_pipeline.qwen_batch

# Stage 3: Mapping
python -m cdm_pipeline.mapping.runner

# Stage 4: CDM build
python -m cdm_pipeline.cdm.builder
```

---

## Evaluation Framework

### Intra-NLP Comparison

Pairwise comparison of the four NLP NER models:

- **Entity overlap** — Jaccard similarity per paper and per type
- **Unique entity contribution** — Entities found by only one model
- **Per-type precision/recall** — Against gold standard (when available)
- **Type coverage** — Which CDM types each model detects
- **Speed/efficiency** — Entities/second, GPU vs CPU

```bash
# (Evaluation scripts to be added: cdm_pipeline/evaluation/intra_nlp.py)
```

### Inter-NLP vs LLM Comparison

Aggregate NLP ensemble (union of 4 models) vs. LLM (Qwen 3.5:9b):

- **Aggregate recall** — NLP ensemble recall vs. LLM recall
- **Entity quality** — Precision of LLM vs. NLP (LLM expected higher precision)
- **Type coverage** — LLM reasoning for type assignment vs. NLP label mapping
- **Context disambiguation** — LLM ability to resolve ambiguous terms (e.g., "butyrate" as chemical vs. process)
- **Novel entity recall** — Entities found by LLM but missed by all NLP models
- **Cost/efficiency** — LLM inference time vs. NLP processing time

```bash
# (Evaluation scripts to be added: cdm_pipeline/evaluation/inter_nlp_llm.py)
```

### Gold Standard Evaluation

Create a manually annotated subset for ground truth:

- **Sample size** — 20-50 papers, stratified by BioProject, journal, and entity density
- **Annotation schema** — 14 CDM types, span-level annotations
- **Metrics** — Precision, Recall, F1 (micro and macro), per-type breakdown
- **Inter-annotator agreement** — Cohen's kappa (if multiple annotators)

```bash
# (Evaluation scripts to be added: cdm_pipeline/evaluation/gold_standard.py)
```

---

## Current Status

### Completed

- All 4 NLP NER models run on corpus:
  - GLiNER: 186K entities (444 papers)
  - PubMedBERT: 321K entities (444 papers)
  - PubTator3: 2,308 entities (126/444 papers — title lookup being improved)
  - sciSpaCy: 50 papers (re-run on all 444 pending)
- Deduplicated entity registry: 36,481 unique entities
- Ontology mapping: 34,767/36,481 (95.3%) mapped across 15+ vocabularies
- CDM v2.0 built: 29,954 entities, 189,250 CV mappings, 914,413 relationships
- SQLite database: 247.1 MB (8 tables, 24 indexes, 8 views)
- OWL ontology: 420,825 triples
- Modular pipeline package (`cdm_pipeline/`) complete and committed

### In Progress

- sciSpaCy re-run on all 444 papers (4 models)
- PubTator3 coverage fix (use BioProject metadata titles for PMID lookup)
- LLM NER (Qwen 3.5:9b) — user to run on HPC

### Planned

- Semantic relationship extraction (dependency-parse-based, beyond co-occurrence)
- Gold standard evaluation (20-50 paper annotated subset)
- Intra-NLP comparison framework
- Inter-NLP vs LLM comparison framework

---

## Reference

> Abdill, R. J., Graham, S. P., Rubinetti, V., et al. (2025). *Integration of 168,000 samples reveals global patterns of the human gut microbiome.* **Cell** 188(4):1100-1118.e17. DOI: [10.1016/j.cell.2024.12.017](https://doi.org/10.1016/j.cell.2024.12.017)

The 168,464 samples and 482 projects in the CDM database match this paper. The CDM is built on the cited literature of that compendium.

---

## Citation

```bibtex
@software{microbiome_cdm_pipeline_2025,
  title={Microbiome CDM Pipeline: Multi-NER Entity Extraction and Common Data Model Construction},
  author={Kalra, Jasmeer Singh},
  year={2025},
  url={https://github.com/SCAI-BIO/Microbiome-CDM}
}
```
