#!/bin/bash
#SBATCH --job-name=dedup3
#SBATCH --partition=mlgpu_short
#SBATCH --gres=gpu:a40:1
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --time=02:00:00
#SBATCH --output=outputs/logs/slurm/%x-%j.out
#SBATCH --error=outputs/logs/slurm/%x-%j.err
#
# Exact -> fuzzy -> embedding deduplication of CDM terms and accepted ontology concepts.
# Embeddings: SapBERT (names) + MiniLM (contextual / ontology definitions), already in the HF cache (offline).
# Submit from the repo root:   sbatch src/scripts/concept_dedup/dedup.sbatch
# Writes only to outputs/results/concept_dedup_2026-11-09/{terms,concepts}/ ; reads CDM 3.0.3 read-only.
# Freeze exception (new derived layer), pending project-lead approval: see final_validation/CHANGE_RECORD.md.
CDM_ROOT="${CDM_REPO_ROOT:-$(d="${SLURM_SUBMIT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"; while [ "$d" != / ] && [ ! -f "$d/.cdm_root" ]; do d="$(dirname "$d")"; done; echo "$d")}"
[ -f "$CDM_ROOT/.cdm_root" ] || { echo "ERROR: repo root not found; set CDM_REPO_ROOT" >&2; exit 1; }
set -euo pipefail
cd "$CDM_ROOT"
echo "[$(date -u +%FT%TZ)] node=$(hostname) job=${SLURM_JOB_ID:-local}"
nvidia-smi -L || true
source "$HOME/venvs/vllm/bin/activate"
export HF_HOME=/lustre/scratch/data/jkalra_hpc-deep_learning/hf-cache HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
python src/scripts/concept_dedup/stage_a_iri_normalise.py > /dev/null
for E in concepts terms; do
  echo "=== $E"
  python src/scripts/concept_dedup/dedup_three_pass.py --entity "$E" --stages exact,fuzzy,embed
done
echo "[$(date -u +%FT%TZ)] done"
