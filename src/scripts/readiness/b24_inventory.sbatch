#!/bin/bash
#SBATCH --job-name=b24-inventory
#SBATCH --output=outputs/logs/readiness/%x_%j.out
#SBATCH --error=outputs/logs/readiness/%x_%j.err
#SBATCH --cpus-per-task=2
#SBATCH --mem=96G
#SBATCH --time=03:00:00
# Counts-only inventory of strings sent to external models (B24).  sbatch -p intelsr_short src/scripts/readiness/b24_inventory.sbatch
source "${SLURM_SUBMIT_DIR:-.}/pipelines/cdm_repair/slurm/_env.sh"
python "$CDM_ROOT/src/scripts/readiness/b24_external_processing_inventory.py"
