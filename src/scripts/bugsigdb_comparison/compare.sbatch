#!/bin/bash
#SBATCH --job-name=bugsigdb-cmp
#SBATCH --output=outputs/logs/bugsigdb_comparison/%x_%j.out
#SBATCH --error=outputs/logs/bugsigdb_comparison/%x_%j.err
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=02:00:00
# Direct comparison of the frozen CDM 3.0.3 with BugSigDB (compare.py). Run `compare.py preregister` first.
#   sbatch -p mlgpu_short --gres=gpu:1 src/scripts/bugsigdb_comparison/compare.sbatch
CDM_ROOT="${CDM_REPO_ROOT:-$(d="${SLURM_SUBMIT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"; while [ "$d" != / ] && [ ! -f "$d/.cdm_root" ]; do d="$(dirname "$d")"; done; echo "$d")}"
[ -f "$CDM_ROOT/.cdm_root" ] || { echo "ERROR: repo root not found" >&2; exit 1; }
set -euo pipefail
cd "$CDM_ROOT"
export HF_HOME=/home/jkalra_hpc/llm/hf-cache HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONUNBUFFERED=1
module use /opt/software/easybuild-AMD/modules/all
module load Python/3.12.3-GCCcore-13.3.0
source /home/jkalra_hpc/venvs/vllm/bin/activate
python src/scripts/bugsigdb_comparison/compare.py run "$@"
