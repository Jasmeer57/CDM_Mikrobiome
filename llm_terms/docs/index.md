# CDM Entity Extraction Pipeline

![CDM Pipeline](https://img.shields.io/badge/CDM-Pipeline-blue)
![Python](https://img.shields.io/badge/Python-3.8%2B-green)
![License](https://img.shields.io/badge/License-MIT-yellow)
![Docker](https://img.shields.io/badge/Docker-Ready-blue)

A comprehensive, modular pipeline for extracting structured biomedical entities from text for the Microbiome Common Data Model (CDM). Powered by Large Language Models and advanced biomedical validation.

## 🚀 Key Features

### 🧠 Advanced AI Processing
- **LLM-Powered Extraction**: Support for multiple LLM models (Phi3, Qwen, Llama, etc.)
- **Semantic Deduplication**: Sentence Transformers for intelligent duplicate removal
- **BioMistral Validation**: Biomedical entity validation and correction
- **Confidence Scoring**: Quality assessment for all extracted entities

### 🏥 Biomedical Integration
- **OMOP CDM Mapping**: Standardized clinical vocabulary mapping
- **UMLS Integration**: Unified Medical Language System concept mapping
- **BioPortal/OLS**: Ontology lookup services integration
- **10 Entity Types**: Comprehensive biomedical entity classification

### ⚡ Performance & Scalability
- **Parallel Processing**: Multi-threaded chunk processing
- **Adaptive Chunking**: Intelligent text segmentation
- **Memory Efficient**: Streaming processing for large files
- **Configurable Resources**: Adjustable worker counts and memory usage

### 🐳 Deployment Ready
- **Docker Support**: Complete containerization
- **FastAPI Server**: RESTful API endpoints
- **CLI Interface**: Comprehensive command-line tool
- **Cloud Ready**: Kubernetes deployment manifests

## 📊 Supported Entity Types

| Entity Type | Description | Examples |
|------------|-------------|----------|
| **GENE** | Genes, genetic markers, gene families | `Bacteroides`, `Firmicutes`, `Lactobacillus` |
| **PROTEIN** | Proteins, enzymes, receptors | `Butyrate kinase`, `Beta-lactamase` |
| **ORGANISM** | Bacteria, archaea, fungi, viruses | `E. coli`, `Bifidobacterium` |
| **DISEASE** | Diseases, conditions, disorders | `Inflammatory bowel disease` |
| **CHEMICAL** | Metabolites, SCFAs, drugs | `Butyrate`, `Propionate`, `Acetate` |
| **DNA_RNA** | Genetic material, sequences | `16S rRNA`, `PCR primers` |
| **CELL_TYPE** | Cell types, immune cells | `T-cells`, `B-cells`, `Macrophages` |
| **BIOINFO_TOOL** | Bioinformatics tools, databases | `BLAST`, `Qiime`, `MetaPhlAn` |
| **GENOMICS** | Omics technologies, methods | `Metagenomics`, `Transcriptomics` |
| **CLINICAL** | Clinical terms, procedures | `Gut microbiota analysis` |

## 🏁 Quick Start

### Installation

```bash
# Clone the repository
git clone https://github.com/your-org/cdm-pipeline
cd cdm-pipeline

# Install dependencies
pip install -r requirements.txt

# Or install in development mode
pip install -e .
```

### Basic Usage

```bash
# Simple extraction
python main.py \
  --input-file research_paper.txt \
  --model phi3:mini \
  --output results.json

# Advanced with all features
python main.py \
  --input-file research_paper.txt \
  --model qwen3:8b \
  --enable-biomistral \
  --enable-omop-mapping \
  --enable-umls-mapping \
  --enable-comprehensive-mapping \
  --semantic-threshold 0.8 \
  --output comprehensive_results.json
```

### Python API

```python
import main  # Import main module from current directory
from main import CDMEntityPipeline

# Initialize pipeline
pipeline = CDMEntityPipeline(
    model="phi3:mini",
    enable_biomistral=True,
    enable_comprehensive_mapping=True
)

# Extract entities
entities = pipeline.extract_entities(text)
print(f"Found {len(entities)} entities")
```

## 📈 Performance

| File Size | Processing Time | Memory Usage | Entities Found |
|-----------|----------------|--------------|----------------|
| 1 MB | ~30 seconds | ~500 MB | 50-100 |
| 10 MB | ~3 minutes | ~1 GB | 500-1000 |
| 100 MB | ~25 minutes | ~2 GB | 5000-10000 |

*Benchmarks performed with Phi3:mini model on standard hardware*

## 🏗️ Architecture

```
llm_terms/
├── main.py                    # CLI interface
├── config/                    # Configuration modules
│   ├── cdm_config.py         # CDM entity types & pipeline config
│   └── __init__.py
├── core/                      # Core pipeline components
│   ├── pipeline.py           # Main orchestrator
│   ├── llm_client.py         # LLM interface
│   └── semantic_deduplicator.py
├── extractors/               # Entity extraction engine
│   ├── entity_extractor.py
│   └── __init__.py
├── biomedical/               # Biomedical validation
│   ├── biomistral_validator.py
│   └── __init__.py
├── mappers/                  # Ontology mapping
│   ├── omop_mapper.py       # OMOP CDM mapping
│   ├── umls.py              # UMLS mapping
│   ├── mapping.py           # Comprehensive mapping
│   └── __init__.py
└── utils/                    # Utilities
    ├── text_processor.py
    └── __init__.py
```

## 🔧 Configuration

The pipeline supports extensive configuration via CLI arguments:

```bash
python main.py --help
```

Key configuration options:
- **Model Selection**: `--model phi3:mini|qwen3:8b|llama2:7b`
- **Performance**: `--max-workers`, `--chunk-size`, `--max-entities`
- **Quality**: `--min-confidence`, `--semantic-threshold`
- **Features**: `--enable-biomistral`, `--enable-comprehensive-mapping`
- **Output**: `--output`, `--verbose`

## 🐳 Docker Deployment

```bash
# Build Docker image
docker build -t cdm-pipeline .

# Run with Docker
docker run -v $(pwd)/data:/data \
  cdm-pipeline \
  --input-file /data/research.txt \
  --output /data/results.json
```

## 📚 Documentation

- [Getting Started](getting-started/introduction.md)
- [User Guide](user-guide/cli.md)
- [API Reference](api/rest-api.md)
- [Architecture](architecture/overview.md)
- [Deployment](deployment/docker.md)

## 🤝 Contributing

We welcome contributions! Please see our [Contributing Guide](development/contributing.md) for details.

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- **Ollama Project** - LLM serving infrastructure
- **BioMistral** - Biomedical language model
- **OMOP CDM** - Standardized clinical data model
- **UMLS** - Unified Medical Language System
- **Sentence Transformers** - Semantic similarity models

---

## 📞 Support

- 📧 Email: support@cdm-pipeline.org
- 💬 Discord: [Join our community](https://discord.gg/cdm-pipeline)
- 🐛 Issues: [GitHub Issues](https://github.com/your-org/cdm-pipeline/issues)
- 📖 Documentation: [Full Docs](https://cdm-pipeline.readthedocs.io)

---

<div align="center">
  <strong>Transforming biomedical text into structured knowledge</strong> 🧬✨
</div>