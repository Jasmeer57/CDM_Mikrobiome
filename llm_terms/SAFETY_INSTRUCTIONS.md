# Safety Instructions & Environment Setup

This document provides detailed instructions on how to safely set up the environment for the CDM Pipeline, ensuring all dependencies are installed correctly and securely.

## 🛡️ Virtual Environment Setup

Using a virtual environment is critical to prevent conflicts with system packages and ensure reproducibility.

### 1. Prerequisites
- **Python 3.10+**: Ensure Python 3.10 or higher is installed.
  ```bash
  python3 --version
  ```
- **Pip**: Ensure pip is up to date.
  ```bash
  python3 -m pip install --upgrade pip
  ```

### 2. Creating a Virtual Environment
We recommend using `venv` (built-in) or `conda`.

#### Option A: Using `venv` (Recommended for standard servers)
```bash
# Create the virtual environment named '.venv'
python3 -m venv .venv

# Activate the environment
# On Linux/MacOS:
source .venv/bin/activate
# On Windows:
.venv\Scripts\activate
```

#### Option B: Using `conda` (Recommended for HPC/Data Science)
```bash
# Create a new conda environment
conda create -n cdm_pipeline python=3.10

# Activate the environment
conda activate cdm_pipeline
```

### 3. Installing Dependencies
Once the environment is active, install the required packages safely.

```bash
# Install core dependencies
pip install -r requirements.txt

# Install additional NLP models (if not automatically handled)
python -m spacy download en_core_web_sm
```

## 📦 Dependency List & Safety Notes

The pipeline relies on several key libraries. Here's what they do and why they are needed:

- **`torch`**: PyTorch deep learning framework. *Note: Large installation (~2GB).*
- **`transformers`**: Hugging Face transformers for running LLMs and embeddings.
- **`sentence-transformers`**: For semantic deduplication (MiniLM).
- **`ollama`**: Client library to communicate with the Ollama server.
- **`fastapi` & `uvicorn`**: For the API server.
- **`pandas` & `numpy`**: Data manipulation.
- **`scikit-learn`**: For cosine similarity calculations.

### 🔒 Security Best Practices
- **API Keys**: Never commit API keys (UMLS, OpenAI, etc.) to version control. Use `.env` files.
- **Model Sources**: Only download models from trusted sources (e.g., official Hugging Face repositories, Ollama library).
- **Input Validation**: The pipeline includes input validation to prevent injection attacks, but always sanitize inputs if exposing the API publicly.

## 🚀 Verifying Installation

Run the following command to verify that the environment is set up correctly:

```bash
python -c "import torch; import transformers; import sentence_transformers; print('✅ Environment verified successfully!')"
```

## 🆘 Troubleshooting

**Issue: `ModuleNotFoundError`**
- Ensure your virtual environment is activated (`source .venv/bin/activate`).
- Re-run `pip install -r requirements.txt`.

**Issue: CUDA/GPU not found**
- If using GPU, ensure you installed the CUDA-compatible version of PyTorch.
- Check with: `python -c "import torch; print(torch.cuda.is_available())"`
