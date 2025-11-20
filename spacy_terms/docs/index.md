# 🧬 Scientific Term Extraction Pipeline

> **Production-ready pipeline for extracting biomedical terminology optimized for Common Data Model (CDM) implementation**

[![Version](https://img.shields.io/badge/version-2.0.0-blue.svg)](https://github.com/your-repo/spacy_terms)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.9+-blue.svg)](https://python.org)

## 🎯 Overview

This advanced pipeline extracts high-quality biomedical terminology from scientific literature using **4 sciSpaCy models**, **multi-layer filtering**, and **semantic deduplication** to achieve **98.4% accuracy** in extracting clinically relevant terms.

### ✨ Key Features

- **🔬 Multi-Model NER**: 4 specialized sciSpaCy models running in parallel
- **🔍 4-Layer Filtering**: Basic → Advanced → Biomedical → CDM optimization
- **🔄 4-Strategy Deduplication**: Exact → Fuzzy → Semantic → BioMistral Biomedical (NEW!)
- **🏥 CDM Integration**: Optimized for Common Data Model terminology
- **💾 Multi-Format Output**: JSON, CSV, SQLite with CDM schema
- **🚀 Production Ready**: FastAPI, Docker, monitoring stack

## 📊 Performance Metrics

| **Pipeline Version** | **Output Terms** | **Quality** | **CDM Ready** |
|---------------------|----------------|-------------|---------------|
| **CDM-Optimized** | **1,585** | **98.4%** | **60%** |

## 🚀 Quick Start

### Installation
```bash
# Clone repository
git clone https://github.com/your-repo/spacy_terms.git
cd spacy_terms

# Install dependencies
pip install -r requirements.txt

# Install sciSpaCy models
pip install https://github.com/allenai/scispacy/releases/download/v0.5.1/en_core_sci_lg-0.5.1.tar.gz
pip install https://github.com/allenai/scispacy/releases/download/v0.5.1/en_ner_craft_md-0.5.1.tar.gz
pip install https://github.com/allenai/scispacy/releases/download/v0.5.1/en_ner_bc5cdr_md-0.5.1.tar.gz
pip install https://github.com/allenai/scispacy/releases/download/v0.5.1/en_ner_jnlpba_md-0.5.1.tar.gz
```

### Basic Usage
```bash
# Extract terms with CDM optimization
python main.py --input_dir ./data --output_formats json csv sqlite

# Use upgraded Nomic v1.5 model
python main.py --input_dir ./data --semantic_model nomic
```

### API Usage
```bash
# Start API server
uvicorn src.api.main:app --reload

# Visit documentation
http://localhost:8000/docs
```

### Docker Deployment
```bash
# Full stack with monitoring
docker-compose up -d
```

## 🏥 CDM Integration

The pipeline produces **60% CDM-ready terms** across key domains:

- **🏥 Condition/Disease**: 34% (bacterial infection, antibiotic resistance)
- **🔬 Procedure/Observation**: 28% (DNA extraction, sequencing)
- **💊 Drug/Substance**: 15% (antibiotic treatment, medications)
- **📊 Measurement**: 18% (microbiota diversity, abundance)
- **👤 Person/Subject**: 5% (age-related, demographics)

## 📚 Documentation

- **[Installation](getting-started/installation.md)** - Setup and configuration
- **[User Guide](user-guide/)** - Complete usage documentation
- **[Technical Details](technical/)** - Architecture and algorithms
- **[Deployment](deployment/)** - Docker, Kubernetes, monitoring
- **[Examples](examples/)** - Notebooks and scripts

## 🎯 Use Cases

- **Clinical Research**: Extract terminology for CDM implementation
- **Biomedical NLP**: Power scientific text processing applications
- **Healthcare Systems**: Build terminology databases for EHR integration
- **Research Analytics**: Analyze literature for biomedical concepts

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

**🧬 Advanced Scientific Term Extraction Pipeline - Built for CDM Implementation**