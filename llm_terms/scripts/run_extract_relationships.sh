#!/bin/bash
#SBATCH --job-name=extract-rels
#SBATCH --output=logs/extract_rels_%j.out
#SBATCH --error=logs/extract_rels_%j.err
#SBATCH --time=12:00:00
#SBATCH --partition=gpu-nvrtx
#SBATCH --gres=gpu:rtx6000:1
#SBATCH --cpus-per-task=16
#SBATCH --mem=128G
#SBATCH --nodes=1
#SBATCH --ntasks=1

set -euo pipefail

echo "========================================================================"
echo "Extract Scientific Relationships using Qwen3.5-9B (HuggingFace)"
echo "========================================================================"
echo "Job ID: $SLURM_JOB_ID"
echo "Node: $SLURM_NODELIST"

export PROJECT_ROOT="/home/jkalra/Microbiome-CDM/llm_terms"
cd "$PROJECT_ROOT"

mkdir -p logs

# Activate environment
echo "Activating environment..."
eval "$(conda shell.bash hook)"
conda activate qwen-coder

echo "GPU:"
nvidia-smi --query-gpu=name,memory.free --format=csv,noheader

# Input/Output - use corrected entities
INPUT_FILE="outputs/enhanced/cdm_entities_clean_step4_v2.json"
OUTPUT_DIR="outputs/relationships"

mkdir -p "$OUTPUT_DIR"

echo ""
echo "Input: $INPUT_FILE"
echo "Output: $OUTPUT_DIR"
echo ""

# Run relationship extraction using build_knowledge_graph.py
echo "Starting relationship extraction..."
python scripts/build_knowledge_graph.py \
    --entities "$INPUT_FILE" \
    --output-dir "$OUTPUT_DIR" \
    --skip-umls \
    --skip-taxonomy \
    --skip-chebi

echo "Done!"
ls -lh "$OUTPUT_DIR/"
