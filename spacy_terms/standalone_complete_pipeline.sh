#!/bin/bash
#SBATCH --job-name=sci_term_extraction_mistral
#SBATCH --output=logs/sci_term_complete_%j.out
#SBATCH --error=logs/sci_term_complete_%j.err
#SBATCH --partition=gpu-mix
#SBATCH --gres=gpu:a100:1
#SBATCH --cpus-per-task=16
#SBATCH --mem=150G
#SBATCH --time=24:00:00
#SBATCH --nodes=1

# === METADATA ===
export SLURM_JOB_START_TIME="$(date)"
echo "=== COMPLETE SCIENTIFIC TERM EXTRACTION PIPELINE WITH MISTRAL ==="
echo "Job started at: $(date)"
echo "Node: $HOSTNAME"
echo "Job ID: $SLURM_JOB_ID"
echo "GPU: $CUDA_VISIBLE_DEVICES"
echo "CPUs: $SLURM_CPUS_PER_TASK"
echo "Memory: ${SLURM_MEM_PER_NODE}GB"
echo ""

# === ENVIRONMENT SETUP ===
module purge
module load Miniforge3/24.1.2-0
source "$EBROOTMINIFORGE3/etc/profile.d/conda.sh"
module load CUDA/12.3.0
module load ollama/0.7.0

# Set CUDA library paths
export LD_LIBRARY_PATH="/opt/software/easybuild/software/CUDA/12.3.0/targets/x86_64-linux/lib:$LD_LIBRARY_PATH"
export CUDA_HOME="/opt/software/easybuild/software/CUDA/12.3.0"

# Memory management to reduce fragmentation
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True,max_split_size_mb:128

# Create logs directory
mkdir -p logs

# === CONDA ENVIRONMENT ===
echo "Setting up conda environment..."
conda activate spacy_scispacy_env

# Verify correct Python is being used
echo "Python path: $(which python)"
echo "Python version: $(python --version)"

# === INSTALL OLLAMA IF NEEDED ===
echo "Checking Ollama availability..."
if ! command -v ollama &> /dev/null; then
    echo "Installing Ollama..."
    curl -fsSL https://ollama.ai/install.sh | sh
    export PATH="$PATH:/usr/local/bin"
else
    echo "✅ Ollama is already installed"
fi

# Start Ollama server if not running
if ! pgrep -x "ollama" > /dev/null; then
    echo "Starting Ollama server..."
    ollama serve &
    sleep 10  # Give server time to start
fi

# Pull Mistral model if not available
if ! ollama list | grep -q "mistral"; then
    echo "Pulling Mistral model..."
    ollama pull mistral:latest
else
    echo "✅ Mistral model is already available"
fi

# === PIPELINE CONFIGURATION ===
echo "=== PIPELINE CONFIGURATION ==="
echo "Input Directory: papers_txt"
echo "Output Directory: output_full"
echo "Ensemble Mode: Enabled (all models)"
echo "Workers: 8 (reduced from 16 for memory efficiency)"
echo "Batch Size: 8 (reduced from 16 for GPU memory)"
echo "Target Terms: 10,000"
echo "Max Files: 50 (limiting for testing)"
echo "Fuzzy Threshold: 0.85"
echo "Semantic Threshold: 0.90"
echo "Features: Definitions, Correction, UMLS/OMOP/BioPortal Mapping"
echo "LLM Model: Ollama Mistral (LOCAL - much faster!)"
echo "GPU Memory Management: Enabled"
echo ""

# OPTIMIZED: Run pipeline with optimized settings for better performance
echo "Starting OPTIMIZED pipeline execution on CLUSTER with Ollama Mistral..."
/home/jkalra/.conda/envs/spacy_scispacy_env/bin/python standalone_scispacy_pipeline.py \
    --input_dir "/home/jkalra/my_node_tools/Microbiome-CDM/papers_txt" \
    --output_dir "output_optimized" \
    --ensemble \
    --workers 2 \
    --use_ollama \
    --ollama_model "mistral:latest" \
    --ollama_base_url "http://localhost:11434" \
    --generate_definitions \
    --correct_terms \
    --map_umls \
    --map_omop \
    --map_bioportal \
    --batch_size 16 \
    --target_terms 15000 \
    --fuzzy_threshold 0.85 \
    --semantic_threshold 0.90 

echo "=== PIPELINE EXECUTION COMPLETE ==="
echo "Job completed at: $(date)"