#!/bin/bash

#SBATCH --job-name=microbiome_spacy_terms_v6
#SBATCH --output=logs/microbiome_spacy_v6_%j.out
#SBATCH --error=logs/microbiome_spacy_v6_%j.err
#SBATCH --time=48:00:00
#SBATCH --mem=200G
#SBATCH --cpus-per-task=20
#SBATCH --nodes=1
#SBATCH --partition=gpu-amd
#SBATCH --gres=gpu:a100:1

# --- Setup ---

# Create the logs directory if it doesn't exist to store SLURM output
mkdir -p logs
mkdir -p model_cache # Create a directory for model caches

# Set environment variables for model caching to avoid filling up home directory
export HF_HOME=$(pwd)/model_cache
export TRANSFORMERS_CACHE=$(pwd)/model_cache

# --- Job Execution ---

# Define the input directory
INPUT_DIR="/home/jkalra/thesis/papers_txt"
OUTPUT_DIR="/home/jkalra/spacy_terms/output"
# Set your Hugging Face token (it's good practice to load it from a secure file if possible)

echo "Starting Python script..."

# Run the Python script using srun
# srun ensures that the job runs within the allocated resources
python terms.py \
    --input_dir "$INPUT_DIR" \
    --output_dir "$OUTPUT_DIR" 

echo "Script finished."