#!/bin/bash
#SBATCH --job-name=triple-refcheck
#SBATCH --output=outputs/logs/triple_reference_check/%x_%j.out
#SBATCH --error=outputs/logs/triple_reference_check/%x_%j.err
#SBATCH --cpus-per-task=8
#SBATCH --mem=24G
#SBATCH --time=02:00:00
# Reference check of the triple layer against BugSigDB and CTD (check.py). Run `check.py preregister` first.
#   sbatch -p intelsr_short src/scripts/triple_reference_check/check.sbatch
CDM_ROOT="${CDM_REPO_ROOT:-$(d="${SLURM_SUBMIT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"; while [ "$d" != / ] && [ ! -f "$d/.cdm_root" ]; do d="$(dirname "$d")"; done; echo "$d")}"
[ -f "$CDM_ROOT/.cdm_root" ] || { echo "ERROR: repo root not found" >&2; exit 1; }
set -euo pipefail
cd "$CDM_ROOT"
export HF_HOME=/home/jkalra_hpc/llm/hf-cache HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONUNBUFFERED=1
module use /opt/software/easybuild-AMD/modules/all
module load Python/3.12.3-GCCcore-13.3.0
source /home/jkalra_hpc/venvs/vllm/bin/activate
python src/scripts/triple_reference_check/check.py run
