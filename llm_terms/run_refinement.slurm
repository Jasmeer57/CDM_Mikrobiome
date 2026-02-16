#!/bin/bash
#SBATCH --job-name=kg-refine
#SBATCH --output=logs/kg_refine_%j.out
#SBATCH --error=logs/kg_refine_%j.err
#SBATCH --time=00:30:00
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --partition=short

# =============================================================================
# Knowledge Graph Refinement SLURM Script
# =============================================================================
# This script refines an existing knowledge graph by:
# 1. Canonicalizing entities (merging duplicates, normalizing types)
# 2. Validating relationships (type constraints, evidence typing)
# 3. Filtering noise nodes (instruments, software versions, etc.)
# 4. Adding subgraph labels (mechanism/microbiome_metabolite/methods_provenance)
# 5. Adding formal scope statement
#
# Usage:
#   sbatch run_refinement.slurm
#
# Or with custom parameters:
#   sbatch --export=KG_FILE="custom_kg.json",RELS_FILE="custom_rels.json" run_refinement.slurm
# =============================================================================

set -euo pipefail  # Exit on error

# Configuration (can be overridden via SLURM --export)
KG_FILE="${KG_FILE:-knowledge_graph/cdm_kg.json}"
RELS_FILE="${RELS_FILE:-relationships/cdm_relationships.json}"
OUTPUT_FILE="${OUTPUT_FILE:-knowledge_graph/cdm_kg_refined.json}"
MIN_ENTITY_CONF="${MIN_ENTITY_CONF:-0.4}"
MIN_REL_CONF="${MIN_REL_CONF:-0.5}"
KEEP_BIOLOGICAL_ONLY="${KEEP_BIOLOGICAL_ONLY:-false}"

# Create logs directory
mkdir -p logs

echo "=========================================="
echo "Knowledge Graph Refinement Job"
echo "=========================================="
echo "Job ID: $SLURM_JOB_ID"
echo "Node: $SLURM_NODELIST"
echo "Start time: $(date)"
echo ""
echo "Input KG: $KG_FILE"
echo "Input Relationships: $RELS_FILE"
echo "Output: $OUTPUT_FILE"
echo "Min Entity Confidence: $MIN_ENTITY_CONF"
echo "Min Relationship Confidence: $MIN_REL_CONF"
echo "Keep Biological Only: $KEEP_BIOLOGICAL_ONLY"
echo "=========================================="
echo ""

# Change to script directory
cd "$SLURM_SUBMIT_DIR"

# Load conda if available
if [ -f "$(conda info --base 2>/dev/null)/etc/profile.d/conda.sh" ]; then
    echo "Activating conda environment..."
    source "$(conda info --base)/etc/profile.d/conda.sh"
    conda activate llm-terms || echo "Warning: conda environment not found, using system Python"
fi

# Run refinement
echo "Running KG refinement..."
python refine_kg.py \
    --kg "$KG_FILE" \
    --relationships "$RELS_FILE" \
    --output "$OUTPUT_FILE" \
    --min-entity-confidence "$MIN_ENTITY_CONF" \
    --min-rel-confidence "$MIN_REL_CONF" \
    ${KEEP_BIOLOGICAL_ONLY:+--keep-biological-only}

# Check exit code
EXIT_CODE=$?
if [ $EXIT_CODE -eq 0 ]; then
    echo ""
    echo "=========================================="
    echo "Job completed successfully!"
    echo "Output: $OUTPUT_FILE"
    echo "End time: $(date)"
    echo "=========================================="
else
    echo ""
    echo "=========================================="
    echo "Job FAILED with exit code $EXIT_CODE"
    echo "End time: $(date)"
    echo "=========================================="
fi

exit $EXIT_CODE
