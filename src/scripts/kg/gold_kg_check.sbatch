#!/bin/bash
#SBATCH --job-name=gold-kg
#SBATCH --output=outputs/logs/kg/%x_%j.out
#SBATCH --error=outputs/logs/kg/%x_%j.err
#SBATCH --cpus-per-task=4
#SBATCH --mem=48G
#SBATCH --time=01:00:00
# Reference-KG check of the triple KG (gold_kg_check.py); run after the evidence check.
#   sbatch -p intelsr_short src/scripts/kg/gold_kg_check.sbatch
CDM_ROOT="${CDM_REPO_ROOT:-$(d="${SLURM_SUBMIT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"; while [ "$d" != / ] && [ ! -f "$d/.cdm_root" ]; do d="$(dirname "$d")"; done; echo "$d")}"
[ -f "$CDM_ROOT/.cdm_root" ] || { echo "ERROR: repo root not found" >&2; exit 1; }
set -euo pipefail
cd "$CDM_ROOT/src/scripts/kg"
export PYTHONUNBUFFERED=1
module use /opt/software/easybuild-AMD/modules/all
module load Python/3.12.3-GCCcore-13.3.0
source /home/jkalra_hpc/venvs/vllm/bin/activate
python gold_kg_check.py run
