#!/bin/bash
#SBATCH --job-name=kg-umls-map
#SBATCH --output=logs/umls_mapping_%j.out
#SBATCH --error=logs/umls_mapping_%j.err
#SBATCH --time=04:00:00
#SBATCH --partition=gpu-nv
#SBATCH --gres=gpu:h100:1
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --nodes=1
#SBATCH --ntasks=1

# =============================================================================
# UMLS Entity Mapping - Map ALL entities to UMLS concepts
# =============================================================================
# This script maps ALL 8,657 entities to UMLS concepts using scispaCy entity linker
# Generates comprehensive umls_entity_mappings.csv and umls_entity_mappings.json
# =============================================================================

echo "========================================================================"
echo "UMLS Entity Mapping for ALL Entities"
echo "========================================================================"
echo "Job ID: $SLURM_JOB_ID"
echo "Node: $SLURM_NODELIST"
echo "========================================================================"

# Load environment
export PROJECT_ROOT="/home/jkalra/Microbiome-CDM/llm_terms"
cd "$PROJECT_ROOT"

# Activate conda environment with scispaCy
echo "Activating llm_terms_env with scispaCy..."
eval "$(conda shell.bash hook)"
conda activate llm_terms_env

# Run UMLS mapping
echo "Starting UMLS entity mapping..."
python scripts/extract_umls_scispacy.py

echo ""
echo "========================================================================"
echo "UMLS Mapping Complete!"
echo "========================================================================"
echo ""
echo "Output files:"
ls -lh knowledge_graph/relationships/umls_entity_mappings.*
echo ""
echo "Next: Check the mappings and use them for relationship extraction"
