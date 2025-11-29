#!/bin/bash

# === METADATA ===
START_TIME="$(date)"
echo "=== STANDALONE SCIENTIFIC TERM EXTRACTION PIPELINE ==="
echo "Job started at: $START_TIME"
echo "Host: $HOSTNAME"
echo "User: $USER"
echo ""

# === ENVIRONMENT SETUP ===
# Try to find conda
if command -v conda &> /dev/null; then
    CONDA_EXE=$(command -v conda)
    CONDA_BASE=$(dirname $(dirname "$CONDA_EXE"))
    source "$CONDA_BASE/etc/profile.d/conda.sh"
elif [ -f "$HOME/miniforge3/etc/profile.d/conda.sh" ]; then
    source "$HOME/miniforge3/etc/profile.d/conda.sh"
elif [ -f "$HOME/anaconda3/etc/profile.d/conda.sh" ]; then
    source "$HOME/anaconda3/etc/profile.d/conda.sh"
elif [ -f "$HOME/miniconda3/etc/profile.d/conda.sh" ]; then
    source "$HOME/miniconda3/etc/profile.d/conda.sh"
else
    echo "WARNING: Conda not found in standard locations. Assuming 'conda' is in PATH or environment is already active."
fi

# Create logs directory
mkdir -p logs

# === CONDA ENVIRONMENT ===
ENV_NAME="sci-term-standalone"
echo "Setting up conda environment '$ENV_NAME'..."

if conda info --envs | grep -q "$ENV_NAME"; then
    echo "Environment '$ENV_NAME' already exists. Activating..."
    conda activate "$ENV_NAME"
else
    echo "Creating environment '$ENV_NAME'..."
    conda create -n "$ENV_NAME" python=3.9 -y
    conda activate "$ENV_NAME"
fi

# === INSTALL DEPENDENCIES ===
echo "Installing dependencies..."
pip install --upgrade pip
pip install spacy==3.7.2
pip install scispacy==0.5.1
pip install sentence-transformers==2.2.2
pip install pandas==2.1.3
pip install numpy==1.24.3
pip install tqdm==4.66.1
pip install python-Levenshtein==0.23.0
pip install rapidfuzz==3.5.2
pip install prettytable

# === INSTALL SCIPACY MODELS ===
echo "Installing sciSpaCy models..."
# Check if model is installed to avoid re-downloading every time
if ! python -c "import spacy; spacy.load('en_core_sci_lg')" &> /dev/null; then
    pip install https://github.com/allenai/scispacy/releases/download/v0.5.1/en_core_sci_lg-0.5.1.tar.gz
else
    echo "en_core_sci_lg already installed."
fi

# === CREATE OUTPUT DIRECTORIES ===
echo "Setting up output directories..."
mkdir -p output
mkdir -p logs

# === PIPELINE EXECUTION ===
echo ""
echo "=== STARTING PIPELINE EXECUTION ==="
echo "Pipeline configuration:"
echo "  - Script: standalone_scispacy_pipeline.py"
echo "  - Input directory: ./data"
echo "  - Output directory: ./output"
echo "  - Semantic model: all-MiniLM-L6-v2"
echo "  - Fuzzy threshold: 0.85"
echo "  - Semantic threshold: 0.90"
echo ""

# Check input data
if [ ! -d "data" ]; then
    echo "ERROR: data directory not found! Please create 'data' directory and put .txt files in it."
    exit 1
fi

echo "Available files in data directory:"
ls -la data/ | head -n 10
echo ""

# === RUN PIPELINE ===
echo "Starting scientific term extraction pipeline..."
python standalone_scispacy_pipeline.py \
    --input_dir ./data \
    --output_dir ./output \
    --max_files 100 \
    --fuzzy_threshold 0.85 \
    --semantic_threshold 0.90

PIPELINE_EXIT_CODE=$?

# === PIPELINE COMPLETION ANALYSIS ===
echo ""
echo "=== PIPELINE COMPLETION ANALYSIS ==="
echo "Pipeline completed with exit code: $PIPELINE_EXIT_CODE"

if [ $PIPELINE_EXIT_CODE -eq 0 ]; then
    echo "✅ SUCCESS: Pipeline completed successfully!"

    # Analyze results
    echo ""
    echo "=== RESULTS ANALYSIS ==="

    # Find latest output files (assuming naming convention from script)
    # The script outputs {filename}_scispacy_results.json
    
    count_files=$(ls output/*_scispacy_results.json 2>/dev/null | wc -l)
    echo "Generated $count_files JSON result files."

    if [ $count_files -gt 0 ]; then
        echo "Sample results:"
        ls -lh output/*_scispacy_results.json | head -n 5
    fi

else
    echo "❌ FAILED: Pipeline failed with exit code $PIPELINE_EXIT_CODE"
fi

# === FINAL METADATA ===
echo ""
echo "=== JOB COMPLETION METADATA ==="
echo "Job started at: $START_TIME"
echo "Job completed at: $(date)"
echo "Total runtime: $(($(date +%s) - $(date -d "$START_TIME" +%s))) seconds"
echo ""

# === CLEANUP ===
# echo "Deactivating conda environment..."
# conda deactivate

echo "=== PIPELINE EXECUTION COMPLETE ==="
exit $PIPELINE_EXIT_CODE
