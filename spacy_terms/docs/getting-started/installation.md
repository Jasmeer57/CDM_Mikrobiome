# Installation

## 🔧 Prerequisites

- **Python**: 3.8+ (3.9+ recommended)
- **Memory**: 4GB+ RAM for semantic models
- **Storage**: 2GB+ for spaCy models
- **OS**: Linux, macOS, Windows (WSL2)

## 📦 Quick Installation

### 1. Clone Repository
```bash
git clone https://github.com/SCAI-BIO/Microbiome-CDM.git
cd Microbiome-CDM/spacy_terms
```

### 2. Create Virtual Environment
```bash
# Using conda (recommended)
conda create -n sci-term-extraction python=3.9
conda activate sci-term-extraction

# Or using venv
python -m venv sci-term-extraction
source sci-term-extraction/bin/activate  # Linux/macOS
# sci-term-extraction\Scripts\activate  # Windows
```

### 3. Install Dependencies
```bash
# Core dependencies
pip install -r requirements.txt

# Install sciSpaCy models
pip install https://github.com/allenai/scispacy/releases/download/v0.5.1/en_core_sci_lg-0.5.1.tar.gz
pip install https://github.com/allenai/scispacy/releases/download/v0.5.1/en_ner_craft_md-0.5.1.tar.gz
pip install https://github.com/allenai/scispacy/releases/download/v0.5.1/en_ner_bc5cdr_md-0.5.1.tar.gz
pip install https://github.com/allenai/scispacy/releases/download/v0.5.1/en_ner_jnlpba_md-0.5.1.tar.gz
```

## 🐳 Docker Installation

### Using Docker Hub (Recommended)
```bash
# Pull pre-built image
docker pull your-registry/sci-term-extractor:latest

# Run container
docker run -p 8000:8000 -v $(pwd)/data:/app/data your-registry/sci-term-extractor
```

### Build from Source
```bash
# Build image
docker build -t sci-term-extractor .

# Run container
docker run -p 8000:8000 -v $(pwd)/data:/app/data sci-term-extractor
```

### Docker Compose
```bash
# Full stack with monitoring
docker-compose up -d

# API only
docker-compose up -d term-extractor
```

## 🔍 Verification

### Test CLI Installation
```bash
# Test basic extraction
python main.py --input_dir ./data --max_files 1

# Should see output like:
# "✅ Pipeline completed: 1585 terms extracted (98.4% quality)"
```

### Test API Installation
```bash
# Start API server
uvicorn src.api.main:app --reload

# Test endpoint
curl http://localhost:8000/health

# Should return: {"status": "healthy", "timestamp": "..."}
```

## 📚 Optional Dependencies

### Documentation (MkDocs)
```bash
pip install mkdocs mkdocs-material mkdocstrings
mkdocs serve  # Local documentation server
```

### Development Tools
```bash
pip install pytest black flake8 jupyter
pytest  # Run tests
black .  # Code formatting
```

### GPU Support (CUDA)
```bash
# Install PyTorch with CUDA support
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118

# Verify GPU support
python -c "import torch; print('CUDA available:', torch.cuda.is_available())"
```

## ⚙️ Configuration

### Environment Variables
```bash
# API Keys (optional)
export OPENAI_API_KEY="your-openai-key"
export UMLS_API_KEY="your-umls-key"

# Pipeline Settings
export FUZZY_THRESHOLD=0.85
export SEMANTIC_THRESHOLD=0.9
export SEMANTIC_MODEL=mini-lm
```

### Configuration File
Edit `src/config/settings.py` for detailed configuration options.

## 🐛 Troubleshooting

### Common Issues

#### **Memory Issues**
```bash
# Reduce batch size or disable semantic deduplication
python main.py --disable_semantic --max_files 1
```

#### **Model Loading Errors**
```bash
# Reinstall sciSpaCy models
pip uninstall en_core_sci_lg en_ner_craft_md en_ner_bc5cdr_md en_ner_jnlpba_md
pip install https://github.com/allenai/scispacy/releases/download/v0.5.1/en_core_sci_lg-0.5.1.tar.gz
# ... repeat for other models
```

#### **Import Errors**
```bash
# Ensure Python path includes src
export PYTHONPATH="${PYTHONPATH}:$(pwd)"
```

#### **Docker Issues**
```bash
# Clean up Docker cache
docker system prune -a
docker build --no-cache -t sci-term-extractor .
```

### Performance Tips

1. **Use SSD**: Faster model loading and file processing
2. **Increase Memory**: Add RAM for better semantic model performance
3. **GPU Acceleration**: Use CUDA for semantic embedding computations
4. **Batch Processing**: Process multiple files simultaneously

### Getting Help

- **Issues**: [GitHub Issues](https://github.com/SCAI-BIO/Microbiome-CDM/issues)
- **Documentation**: [Full Documentation](https://your-docs-site.com)
- **API Reference**: [API Docs](http://localhost:8000/docs)

## ✅ Installation Complete

Your pipeline is now ready! See [Quick Start](quickstart.md) for your first extraction.