#!/bin/bash
#SBATCH --job-name=v32-parse
#SBATCH --partition=intelsr_short
#SBATCH --cpus-per-task=16
#SBATCH --mem=48G
#SBATCH --time=04:00:00
#SBATCH --output=outputs/logs/slurm/%x-%j.out
# Layer 3.2.0-candidate: scispaCy parse + FROZEN syntactic filter (CPU). Submit from the repo root:
#   sbatch --export=ALL,TASK=corpus src/scripts/fixes_v32/parse.sbatch
#   sbatch --export=ALL,TASK=bench  src/scripts/fixes_v32/parse.sbatch
# Read-only on releases/. Outputs written on Lustre and copied back. PENDING lead approval. Written with Claude Code (declare).
CDM_ROOT="${CDM_REPO_ROOT:-$(d="${SLURM_SUBMIT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"; while [ "$d" != / ] && [ ! -f "$d/.cdm_root" ]; do d="$(dirname "$d")"; done; echo "$d")}"
[ -f "$CDM_ROOT/.cdm_root" ] || { echo "ERROR: repo root not found" >&2; exit 1; }
set -euo pipefail
cd "$CDM_ROOT"
module use /opt/software/easybuild-AMD/modules/all
module load Python/3.12.3-GCCcore-13.3.0
source /home/jkalra_hpc/venvs/ner_variants/bin/activate
export PYTHONPATH="/home/jkalra_hpc/venvs/scispacy_models_overlay:${PYTHONPATH:-}" PYTHONUNBUFFERED=1 PYTHONWARNINGS=ignore
HOMEOUT=outputs/results/fixes_v32_2026-11-11/parse
LOUT=/lustre/scratch/data/jkalra_hpc-deep_learning/cdm_fixes_v32_2026-11-11/parse
mkdir -p "$LOUT" "$HOMEOUT"
trap 'set +e; for f in "$LOUT"/*.jsonl; do [ -f "$f" ] && timeout 300 cp "$f" "$HOMEOUT/"; done; true' EXIT
case "${TASK:?}" in
  corpus) python src/scripts/fixes_v32/corpus_parse.py --out "$LOUT" --nproc 14 ;;
  bench)  python src/scripts/fixes_v32/bench_parse.py --out "$LOUT" --nproc 14 ;;
esac
