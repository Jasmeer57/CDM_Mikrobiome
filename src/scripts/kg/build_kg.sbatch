#!/bin/bash
#SBATCH --job-name=build-kg
#SBATCH --output=outputs/logs/kg/%x_%j.out
#SBATCH --error=outputs/logs/kg/%x_%j.err
#SBATCH --cpus-per-task=4
#SBATCH --mem=24G
#SBATCH --time=01:00:00
# Knowledge graph from the CDM 3.0.3 triples (build_kg.py); reads the frozen CDM read-only.
#   sbatch -p intelsr_short src/scripts/kg/build_kg.sbatch
CDM_ROOT="${CDM_REPO_ROOT:-$(d="${SLURM_SUBMIT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"; while [ "$d" != / ] && [ ! -f "$d/.cdm_root" ]; do d="$(dirname "$d")"; done; echo "$d")}"
[ -f "$CDM_ROOT/.cdm_root" ] || { echo "ERROR: repo root not found" >&2; exit 1; }
set -euo pipefail
cd "$CDM_ROOT/src/scripts/kg"
export PYTHONUNBUFFERED=1
module use /opt/software/easybuild-AMD/modules/all
module load Python/3.12.3-GCCcore-13.3.0
source /home/jkalra_hpc/venvs/vllm/bin/activate
python build_kg.py
