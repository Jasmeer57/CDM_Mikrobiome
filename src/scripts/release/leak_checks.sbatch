#!/bin/bash
#SBATCH --job-name=leak-checks
#SBATCH --output=outputs/logs/release/%x_%j.out
#SBATCH --error=outputs/logs/release/%x_%j.err
#SBATCH --cpus-per-task=4
#SBATCH --mem=96G
#SBATCH --time=08:00:00
# Per-value regression check on a bundle (and optionally the frozen deposit). BUNDLE=<folder> FLAGS=--vocab-labels FROZEN=1
#   sbatch -p intelsr_short --export=ALL,BUNDLE=/lustre/.../zenodo_r3,FLAGS=--vocab-labels,FROZEN=1 src/scripts/release/leak_checks.sbatch
CDM_ROOT="${CDM_REPO_ROOT:-$(d="${SLURM_SUBMIT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"; while [ "$d" != / ] && [ ! -f "$d/.cdm_root" ]; do d="$(dirname "$d")"; done; echo "$d")}"
[ -f "$CDM_ROOT/.cdm_root" ] || { echo "ERROR: repo root not found" >&2; exit 1; }
cd "$CDM_ROOT/src/scripts/release"
export PYTHONUNBUFFERED=1
module use /opt/software/easybuild-AMD/modules/all
module load Python/3.12.3-GCCcore-13.3.0
source /home/jkalra_hpc/venvs/vllm/bin/activate
python check_leak_regression.py --out "$BUNDLE" ${FLAGS:-}; echo "regression_exit=$?"
if [ "${FROZEN:-0}" = 1 ]; then
  python check_leak_regression.py --out releases/zenodo_frozen \
      --report outputs/results/release/leak_regression_zenodo_frozen_2026-11-05.json; echo "frozen_exit=$? (expected 1)"
fi
