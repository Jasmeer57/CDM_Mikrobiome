#!/bin/bash
#SBATCH --job-name=ner-qq
#SBATCH --output=outputs/logs/ner_llm_judge/%x_%j.out
#SBATCH --error=outputs/logs/ner_llm_judge/%x_%j.err
#SBATCH --cpus-per-task=4
#SBATCH --mem=24G
#SBATCH --time=01:00:00
# Quality and quantity per NER configuration and type from the DeepSeek verdicts (quality_quantity.py; no API calls).
#   sbatch -p intelsr_short src/scripts/ner_llm_judge/quality_quantity.sbatch
CDM_ROOT="${CDM_REPO_ROOT:-$(d="${SLURM_SUBMIT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"; while [ "$d" != / ] && [ ! -f "$d/.cdm_root" ]; do d="$(dirname "$d")"; done; echo "$d")}"
[ -f "$CDM_ROOT/.cdm_root" ] || { echo "ERROR: repo root not found" >&2; exit 1; }
set -euo pipefail
cd "$CDM_ROOT/src/scripts/ner_llm_judge"
export PYTHONUNBUFFERED=1
module use /opt/software/easybuild-AMD/modules/all
module load Python/3.12.3-GCCcore-13.3.0
source /home/jkalra_hpc/venvs/vllm/bin/activate
python quality_quantity.py
