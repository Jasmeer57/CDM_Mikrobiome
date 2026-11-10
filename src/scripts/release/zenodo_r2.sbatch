#!/bin/bash
#SBATCH --job-name=zenodo-r2
#SBATCH --output=outputs/logs/release/%x_%j.out
#SBATCH --error=outputs/logs/release/%x_%j.err
#SBATCH --cpus-per-task=4
#SBATCH --mem=64G
#SBATCH --time=08:00:00
# Rebuild the public bundle with letter/digit matching (version 1.1 candidate). releases/zenodo_frozen is not touched.
# VOCAB_LABELS=allowlist also blanks labels of non-allow-listed vocabularies (B23) and checks for them.
# Output goes to OUT (default: the Lustre workspace, because the home quota is full).
#   sbatch -p intelsr_short src/scripts/release/zenodo_r2.sbatch
CDM_ROOT="${CDM_REPO_ROOT:-$(d="${SLURM_SUBMIT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"; while [ "$d" != / ] && [ ! -f "$d/.cdm_root" ]; do d="$(dirname "$d")"; done; echo "$d")}"
[ -f "$CDM_ROOT/.cdm_root" ] || { echo "ERROR: repo root not found" >&2; exit 1; }
set -euo pipefail
OUT="${OUT:-/lustre/scratch/data/jkalra_hpc-cdm_repair/zenodo_r2}"
cd "$CDM_ROOT/src/scripts/release"
export PYTHONUNBUFFERED=1
module use /opt/software/easybuild-AMD/modules/all
module load Python/3.12.3-GCCcore-13.3.0
source /home/jkalra_hpc/venvs/vllm/bin/activate
python build_zenodo_frozen.py --out "$OUT" --match alnum --vocab-labels "${VOCAB_LABELS:-all}"
python finalize_zenodo_frozen.py --out "$OUT"
set +e
python verify_zenodo_frozen.py --out "$OUT" --match alnum; V=$?
python check_leak_regression.py --out "$OUT" $([ "${VOCAB_LABELS:-all}" = allowlist ] && echo --vocab-labels); R=$?
python check_leak_regression.py --out releases/zenodo_frozen \
    --report outputs/results/release/leak_regression_zenodo_frozen_2026-11-05.json; F=$?
echo "verify_alnum_exit=$V regression_r2_exit=$R regression_frozen_exit=$F (frozen is expected to fail)"
