#!/bin/bash
#SBATCH --job-name=judge-sanity
#SBATCH --output=outputs/logs/readiness/%x_%j.out
#SBATCH --error=outputs/logs/readiness/%x_%j.err
#SBATCH --partition=mlgpu_short,mlgpu_medium,sgpu_short,sgpu_medium
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=48G
#SBATCH --time=02:00:00
# Judge sanity check with the local Qwen3.5-9B term judge (approved 2026-11-05). Build first (CPU):
#   python src/scripts/readiness/ws_judge_sanity.py build ;  sbatch src/scripts/readiness/ws_judge_sanity.sbatch
source "${SLURM_SUBMIT_DIR:-.}/pipelines/cdm_repair/slurm/_env.sh"
source "$CDM_ROOT/pipelines/cdm_repair/slurm/_serve_qwen.sh"
python "$CDM_ROOT/src/scripts/readiness/ws_judge_sanity.py" run ${SANITY_FLAGS:-}
python "$CDM_ROOT/src/scripts/readiness/ws_judge_sanity.py" score ${SANITY_FLAGS:-}
