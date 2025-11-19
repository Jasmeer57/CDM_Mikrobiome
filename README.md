🧬 Microbiome CDM Entity Extraction Suite

📖 Project Overview

This repository houses a production-grade system designed to extract high-quality, standardized biomedical entities from scientific text (research papers, clinical notes) and map them to the Microbiome Common Data Model (CDM).

The suite implements two distinct, parallel pipelines:

🤖 LLM-Based Pipeline: A generative AI approach (Phi-3, Qwen via Ollama) optimized for context-aware extraction and complex entity reasoning.

⚡ spaCy-Based Pipeline: A deterministic approach utilizing 4 parallel sciSpaCy models for high-throughput, vocabulary-driven extraction.

The system is fully containerized with Docker, exposed via a FastAPI service, documents itself via MkDocs, and utilizes SQLite for persistent result storage.

⚖️ Comparative Analysis: LLM vs. spaCy

We provide both pipelines to allow for a hybrid strategy. Here is how they compare based on our internal benchmarks:

Feature

🤖 LLM-Based Pipeline

⚡ spaCy-Based Pipeline

Core Technology

Generative AI (Phi-3/Qwen via Ollama)

Multi-Model NER (en_core_sci, craft, bc5cdr, jnlpba)

Primary Strength

Reasoning & Context. Can infer entity types (e.g., knowing Butyrate is a Chemical vs. a Process based on sentence structure).

Speed & Vocabulary. Extremely fast; checks against 700k+ known biomedical terms.

Data Quality

High Precision. Best for unstructured text where disambiguation is required.

High Recall. Best for bulk processing where missing a term is unacceptable.

Deduplication

Semantic Deduplication (Nomic Embeddings).

3-Strategy: Exact + Fuzzy (85%) + Semantic (90%).

Infrastructure

Heavy. Requires GPU/VRAM for efficient inference.

Light. CPU-optimized; runs efficiently on standard hardware.

Processing Speed

~2-3 mins per 5000-char chunk (Parallel).

~1-2 mins per full document.

CDM Mapping

Adaptive type mapping via prompt engineering.

Dictionary-based mapping to OMOP/UMLS.

🏗️ System Architecture & Infrastructure

The suite is built on a modern microservices architecture:

FastAPI: Acts as the orchestration layer, exposing asynchronous endpoints (/extract/llm, /extract/spacy) to handle requests and manage pipeline execution.

Docker: Provides a unified runtime environment, managing dependencies for Python, Ollama, and system libraries.

SQLite: Provides persistent, relational storage for extraction results, ensuring data is not lost after processing batches of files.

MkDocs: Auto-generates a static documentation site for API usage, configuration guides, and architecture diagrams.

📁 Project Structure

microbiome-cdm-suite/
├── api/                        # 🚀 FastAPI Application
│   ├── main.py                 # Entry point & Routers
│   ├── database.py             # SQLite Connection & ORM
│   └── schemas.py              # Pydantic models
├── llm_pipeline/               # 🤖 Generative Pipeline
│   ├── core/                   # Chunking & Orchestration
│   ├── filters.py              # 4-Layer Filter Logic
│   └── extractors/             # Ollama Integration
├── spacy_pipeline/             # ⚡ Deterministic Pipeline
│   ├── modules/                # Multi-model NER logic
│   ├── deduplication.py        # Exact/Fuzzy/Semantic strategies
│   └── config/                 # Vocabulary settings
├── docs/                       # 📚 MkDocs Source
├── docker-compose.yml          # Service Orchestration
├── Dockerfile                  # Container Definition
└── README.md


🤖 Pipeline 1: LLM-Based Extraction (Generative)

Goal: Extract entities with high semantic understanding and map them to the CDM format.

🔄 Phase 1: Text Processing & Extraction

Analysis: Calculates character counts and reading time.

Intelligent Chunking: Splits large documents into optimal chunks (Default: 5000 characters with 150 character overlap) to ensure no entities are lost at cut-points.

Parallel Extraction: Uses worker threads to call local LLMs (Phi-3:mini, Qwen) via the Ollama API concurrently.

🧪 Phase 2: 4-Layer Enhanced Filtering

Layer 1: Basic Quality: Removes confidence scores < 0.6, short (<2 chars) or long (>100 chars) entities, and blacklisted terms (e.g., "population", "study").

Layer 2: Pattern Corrections: Applies regex rules to fix types:

.*aceae$ → ORGANISM

.*kinase$ → PROTEIN

BLAST → BIOINFO_TOOL

Layer 3: Duplicate Removal: * Exact matching.

Semantic Deduplication: Uses nomic-embed-text (0.8 threshold) to merge terms like "E. coli" and "Escherichia coli".

Layer 4: Biomedical Validation: Validates organism names against biological indicators and calculates a final quality score (0.0-1.0).

🧠 Phase 3: Semantic Processing

Uses nomic-embed-text-v1.5 with specific task prefixes (search_document:).

Groups entities by type for efficient cosine similarity calculation.

Optional: BioMistral validation for specialized medical consistency.

⚡ Pipeline 2: spaCy Scientific NER (Deterministic)

Goal: High-throughput extraction using specialized medical vocabularies.

🧠 Stage 1: Multi-Model NER

We run 4 Specialized Models in parallel for every document chunk:

en_core_sci_lg: General biomedical (700k+ terms).

en_ner_craft_md: Molecular biology (Genes, Proteins, Taxons).

en_ner_bc5cdr_md: Chemicals and Diseases.

en_ner_jnlpba_md: DNA, RNA, Cell lines.

🔍 Stage 2: Multi-Layer Quality Filtering

Layer 1 (Junk): Removes URLs, citations (Author et al), and software version numbers.

Layer 2 (Context): Validates terms against scientific context rules.

Layer 3 (Strict Bio): Checks against a list of 100+ required biomedical keywords.

Layer 4 (CDM Optimization): Classifies terms into CDM Domains: Person, Condition, Drug, Procedure, Measurement.

🔄 Stage 3: Multi-Strategy Deduplication

Exact: Case-insensitive string matching.

Fuzzy (85%): Levenshtein distance to catch typos.

Semantic (90%): Uses Nomic v1.5 or MiniLM to detect conceptual duplicates based on vector embeddings.

🏥 CDM Integration Results

Condition/Disease: 34% coverage (e.g., "bacterial infection").

Procedure/Observation: 28% coverage (e.g., "DNA extraction").

Measurement: 18% coverage (e.g., "gut microbiota diversity").

Drug/Substance: 15% coverage.

🚀 Installation & Usage

Option A: Docker (Recommended)

The easiest way to run the full suite including the API, Database, and Docs.

# 1. Clone the repo
git clone [https://github.com/your-org/microbiome-cdm-suite.git](https://github.com/your-org/microbiome-cdm-suite.git)

# 2. Start services (FastAPI, Ollama, MkDocs)
docker-compose up --build


Access Points:

API: http://localhost:8000

Swagger UI: http://localhost:8000/docs

Documentation Site: http://localhost:8001

Option B: Manual / CLI Usage

# Install dependencies
pip install -r requirements.txt

# Run LLM Pipeline (CLI)
python llm_pipeline/main.py --input "data/paper.txt" --model "phi3:mini"

# Run spaCy Pipeline (CLI) with SQLite output
python spacy_pipeline/main.py \
    --input_dir "./data" \
    --semantic_model nomic \
    --output_formats json csv sqlite


📊 Output Formats

JSON Output (Standardized)

Both pipelines produce a unified JSON structure:

{
  "metadata": {
    "timestamp": "2025-11-19T...",
    "pipeline": "LLM-Phi3",
    "version": "1.0.0"
  },
  "statistics": {
    "character_count": 55901,
    "total_entities": 85
  },
  "cdm_entities": {
    "ORGANISM": [
      { "name": "Bacteroides fragilis", "confidence": 0.92 }
    ],
    "CHEMICAL": [
      { "name": "Butyrate", "domain": "DRUG_SUBSTANCE" }
    ]
  }
}
