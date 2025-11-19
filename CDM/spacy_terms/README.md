# Advanced Scientific Term Extraction Pipeline

🔬 **Multi-sciSpaCy model term extraction with AI correction and UMLS/OMOP mapping**

## 🎯 Overview

This is a comprehensive modular pipeline for extracting scientific terms from biomedical literature. It uses multiple sciSpaCy models, advanced deduplication techniques, and optional AI correction to produce high-quality term lists suitable for research.

## ✨ Features

### 🚀 Core Extraction
- **Multi-sciSpaCy models**: en_core_sci_lg, en_ner_craft_md, en_ner_bc5cdr_md, en_ner_jnlpba_md
- **Advanced P1-P12 filtering**: Removes noise, citations, and non-scientific artifacts
- **Relevance scoring**: Science-focused term quality assessment

### 🔄 Multi-Layer Deduplication
- **Exact deduplication**: Case-insensitive exact matching
- **Fuzzy deduplication**: RapidFuzz-based similarity matching (configurable threshold)
- **Semantic deduplication**: Sentence transformer embeddings (MiniLM, Nomic, MPNet)

### 🤖 Advanced Features
- **AI Correction**: BioMistral/OpenAI integration for term validation and correction
- **UMLS Mapping**: BioPortal, OLS, NCBO Annotator integration
- **OMOP Mapping**: Clinical vocabulary mapping with fuzzy matching
- **Multi-format output**: JSON, CSV, SQLite

### 🌐 Production Ready
- **FastAPI REST API**: Background processing with job management
- **Docker Support**: Multi-stage builds with GPU support
- **Docker Compose**: Complete orchestration setup
- **Monitoring**: Prometheus + Grafana integration

## 📊 Results (PRJDB4360 Trial)

**🎉 Pipeline Performance:**
- ✅ **2915 raw entities** extracted
- ✅ **1404 filtered terms** after P1-P12 filters
- ✅ **1227 final deduplicated terms**
- ✅ **57.91% total reduction**
- ✅ **High-quality scientific terms** (relevance scores 0.8-1.0)

**🔍 Top Terms Extracted:**
- **"gut microbiota"** (frequency: 63, relevance: 1.0)
- **"composition"** (frequency: 34, relevance: 1.0)
- **"Age-related changes"** (frequency: 2, relevance: 1.0)
- **"centenarian"** (frequency: 5, relevance: 1.0)
- **"newborn"** (frequency: 2, relevance: 0.8)

## 🛠️ Installation

### Prerequisites
- Python 3.9+
- CUDA (for GPU acceleration)
- 8GB+ RAM recommended

### Option 1: Local Installation
```bash
# Clone repository
git clone <repository-url>
cd spacy_terms

# Install dependencies
pip install -r requirements.txt

# Install sciSpaCy models
pip install https://s3-us-west-2.amazonaws.com/ai2-s2-scispacy/releases/v0.5.4/en_core_sci_lg-0.5.4.tar.gz
pip install https://s3-us-west-2.amazonaws.com/ai2-s2-scispacy/releases/v0.5.4/en_ner_craft_md-0.5.4.tar.gz
pip install https://s3-us-west-2.amazonaws.com/ai2-s2-scispacy/releases/v0.5.4/en_ner_bc5cdr_md-0.5.4.tar.gz
pip install https://s3-us-west-2.amazonaws.com/ai2-s2-scispacy/releases/v0.5.4/en_ner_jnlpba_md-0.5.4.tar.gz
```

### Option 2: Docker
```bash
# Build image
docker build -t sci-term-extractor .

# Run container
docker run -p 8000:8000 sci-term-extractor
```

### Option 3: Docker Compose
```bash
docker-compose up -d
```

## 🚀 Usage

### CLI Usage
```bash
# Basic extraction
python main.py --input_dir ./data --output_formats json csv

# With all features enabled
python main.py \
  --input_dir ./data \
  --semantic_model mini-lm \
  --fuzzy_threshold 0.85 \
  --semantic_threshold 0.9 \
  --output_formats json csv sqlite \
  --enable_ai_correction \
  --enable_umls \
  --enable_omop

# Help
python main.py --help
```

### FastAPI Usage
```bash
# Start API server
python src/api/main.py

# Or using uvicorn
uvicorn src.api.main:app --host 0.0.0.0 --port 8000 --reload
```

#### API Endpoints
- `POST /extract` - Start extraction job
- `GET /jobs/{job_id}/status` - Get job status
- `GET /jobs/{job_id}/result` - Download results
- `GET /jobs` - List all jobs
- `GET /config` - Get configuration options

### Example API Call
```bash
curl -X POST "http://localhost:8000/extract" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Age-related changes in gut microbiota composition were observed in the study.",
    "config": {
      "fuzzy_threshold": 0.85,
      "semantic_threshold": 0.9,
      "semantic_model": "mini-lm",
      "enable_ai_correction": false,
      "output_formats": ["json", "csv"]
    }
  }'
```

## ⚙️ Configuration

### Environment Variables
```bash
# API Keys (optional)
export OPENAI_API_KEY="your-openai-key"
export UMLS_API_KEY="your-umls-key"
export BIOPORTAL_API_KEY="your-bioportal-key"

# Pipeline Settings
export FUZZY_THRESHOLD=0.85
export SEMANTIC_THRESHOLD=0.9
export SEMANTIC_MODEL=mini-lm
```

### Configuration File
Edit `src/config/settings.py` for detailed configuration options.

## 📁 Project Structure
```
spacy_terms/
├── main.py                           # Main CLI orchestrator
├── requirements.txt                  # Python dependencies
├── Dockerfile                        # Docker configuration
├── docker-compose.yml               # Docker Compose setup
├── README.md                         # This file
├── src/
│   ├── config/
│   │   └── settings.py             # Configuration management
│   ├── modules/
│   │   ├── terms_extractor.py      # Multi-sciSpaCy extraction
│   │   ├── deduplication.py       # Multi-layer deduplication
│   │   ├── ai_correction.py        # AI term correction
│   │   ├── umls_mapping.py        # UMLS & ontology mapping
│   │   └── omop_mapping.py        # OMOP vocabulary mapping
│   ├── utils/
│   │   └── output_writer.py        # Multi-format output
│   └── api/
│       └── main.py                # FastAPI application
├── data/                             # Input directory
├── output/                           # Output directory
└── logs/                             # Log files
```

## 🔧 Pipeline Modules

### 1. Terms Extractor (`src/modules/terms_extractor.py`)
- Loads and manages multiple sciSpaCy models
- Applies P1-P12 filters for noise removal
- Calculates science relevance scores
- Supports text and file input

### 2. Deduplication (`src/modules/deduplication.py`)
- Three-layer deduplication: Exact → Fuzzy → Semantic
- Configurable semantic models (MiniLM, Nomic, MPNet)
- Efficient batch processing with caching

### 3. AI Correction (`src/modules/ai_correction.py`)
- BioMistral/OpenAI integration
- Term validation and correction
- Batch processing with confidence scoring

### 4. UMLS Mapping (`src/modules/umls_mapping.py`)
- SciSpacy UMLS linker integration
- BioPortal, OLS, NCBO Annotator APIs
- Parallel processing for performance

### 5. OMOP Mapping (`src/modules/omop_mapping.py`)
- Clinical vocabulary mapping
- Exact and fuzzy matching
- High-performance parallel processing

## 🎛️ Available Semantic Models

- **mini-lm**: `sentence-transformers/all-MiniLM-L12-v2` (default)
- **nomic**: `nomic-ai/nomic-embed-text-v1`
- **mpnet**: `sentence-transformers/all-mpnet-base-v2`

## 📊 Output Formats

### JSON
```json
{
  "metadata": {...},
  "deduplicated_terms": [...],
  "statistics": {...}
}
```

### CSV
| term | frequency | relevance_score | models_used | labels |
|------|-----------|------------------|-------------|--------|
| gut microbiota | 63 | 1.0 | ["en_core_sci_lg"] | ["ENTITY"] |

### SQLite
- `terms` table: Extracted terms
- `statistics` table: Pipeline statistics
- `metadata` table: Configuration and metadata

## 🐳 Docker Configuration

### Multi-stage Build
- **Base stage**: System dependencies and Python setup
- **Application stage**: Dependencies and sciSpaCy models
- **Production stage**: Security hardening

### GPU Support
```bash
# With NVIDIA GPU
docker run --gpus all sci-term-extractor

# Specify GPU count
docker run --gpus 1 sci-term-extractor
```

## 🔍 API Documentation

Start the API server and visit:
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

### Authentication (Optional)
Add authentication middleware for production deployment.

## 📈 Monitoring

### Prometheus Metrics
- Term extraction count
- Processing time
- Success/failure rates
- Model performance

### Grafana Dashboards
- Pipeline performance
- Job queue status
- Resource utilization

## 🧪 Testing

```bash
# Run tests
pytest tests/

# Test CLI
python main.py --input_dir ./test_data --max_files 1

# Test API
python tests/test_api.py
```

## 🚀 Deployment

### Development
```bash
python main.py --input_dir ./data
python src/api/main.py
```

### Production
```bash
# Build and deploy
docker-compose up -d

# Scale services
docker-compose up -d --scale term-extractor=3
```

### Kubernetes
```yaml
# kubernetes/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: sci-term-extractor
spec:
  replicas: 3
  selector:
    matchLabels:
      app: sci-term-extractor
  template:
    metadata:
      labels:
        app: sci-term-extractor
    spec:
      containers:
      - name: sci-term-extractor
        image: sci-term-extractor:latest
        ports:
        - containerPort: 8000
        resources:
          limits:
            nvidia.com/gpu: 1
```

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests
5. Submit a pull request

## 📝 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🙏 Acknowledgments

- **sciSpaCy**: Biomedical NLP models
- **Sentence Transformers**: Semantic similarity models
- **BioPortal & UMLS**: Ontology resources
- **FastAPI**: Modern web framework
- **spaCy**: Core NLP library

## 📞 Support

For questions or issues:
- Create an issue on GitHub
- Check the documentation
- Review the configuration options

---

**🔬 Advanced Scientific Term Extraction Pipeline - Production-ready modular architecture for biomedical research**