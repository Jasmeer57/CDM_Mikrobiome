#!/bin/bash
#SBATCH --job-name=sci_term_extraction_complete
#SBATCH --output=logs/sci_term_complete_%j.out
#SBATCH --error=logs/sci_term_complete_%j.err
#SBATCH --partition=gpu-mix
#SBATCH --gres=gpu:a100:1
#SBATCH --cpus-per-task=16
#SBATCH --mem=120G
#SBATCH --time=12:00:00
#SBATCH --nodes=1

# === METADATA ===
export SLURM_JOB_START_TIME="$(date)"
echo "=== COMPLETE SCIENTIFIC TERM EXTRACTION PIPELINE ==="
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

# Create logs directory
mkdir -p logs

# === CONDA ENVIRONMENT ===
echo "Setting up conda environment..."
conda activate sci-term-extraction

# === INSTALL DEPENDENCIES ===
echo "Installing dependencies..."
pip install --upgrade pip
pip install spacy==3.7.2 scispacy==0.5.1 sentence-transformers==2.2.2 pandas==2.1.3 rapidfuzz==3.5.2 transformers==4.35.0 accelerate==0.24.1 bitsandbytes==0.41.2

# === INSTALL SCIPACY MODELS ===
echo "Installing sciSpaCy models..."
pip install https://github.com/allenai/scispacy/releases/download/v0.5.1/en_core_sci_lg-0.5.1.tar.gz
pip install https://github.com/allenai/scispacy/releases/download/v0.5.1/en_ner_craft_md-0.5.1.tar.gz
pip install https://github.com/allenai/scispacy/releases/download/v0.5.1/en_ner_bc5cdr_md-0.5.1.tar.gz
pip install https://github.com/allenai/scispacy/releases/download/v0.5.1/en_ner_jnlpba_md-0.5.1.tar.gz
pip install https://github.com/allenai/scispacy/releases/download/v0.5.1/en_ner_bionlp13cg_md-0.5.1.tar.gz

# === RUN PIPELINE ===
echo "Starting pipeline execution on CLUSTER with BioMistral..."
python standalone_scispacy_pipeline.py \
    --input_dir "data" \
    --output_dir "output_cluster" \
    --ensemble \
    --workers 16 \
    --generate_definitions \
    --correct_terms \
    --definition_model "BioMistral/BioMistral-7B" \
    --map_umls \
    --map_omop \
    --map_bioportal \
    --batch_size 32 \
    --load_4bit

echo "=== PIPELINE EXECUTION COMPLETE ==="
