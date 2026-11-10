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

# Repo root, found at run time: $CDM_REPO_ROOT, else walk up to .cdm_root
# from the submit dir (sbatch) or this script's dir (direct run).
CDM_ROOT="${CDM_REPO_ROOT:-$(d="${SLURM_SUBMIT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"; while [ "$d" != / ] && [ ! -f "$d/.cdm_root" ]; do d="$(dirname "$d")"; done; echo "$d")}"
[ -f "$CDM_ROOT/.cdm_root" ] || { echo "ERROR: repo root not found; set CDM_REPO_ROOT" >&2; exit 1; }
export CDM_ROOT

set -euo pipefail

echo "========================================================================"
echo "Extract Scientific Relationships using Qwen3.5-9B (HuggingFace)"
echo "========================================================================"
echo "Job ID: $SLURM_JOB_ID"
echo "Node: $SLURM_NODELIST"

export PROJECT_ROOT="$CDM_ROOT/pipelines/llm_terms"
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
