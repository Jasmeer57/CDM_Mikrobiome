#!/bin/bash
#SBATCH --job-name=v32-humanreview
#SBATCH --partition=intelsr_short
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=01:00:00
#SBATCH --output=outputs/logs/v32_human_review_%j.out
#SBATCH --error=outputs/logs/v32_human_review_%j.err
# Submit from the repo root:  sbatch src/scripts/fixes_v32/human_review/run_import.sbatch [--force-copy]
set -euo pipefail
CDM_ROOT="$(pwd)"; while [ ! -f "$CDM_ROOT/.cdm_root" ] && [ "$CDM_ROOT" != "/" ]; do CDM_ROOT="$(dirname "$CDM_ROOT")"; done
cd "$CDM_ROOT"
module load Python/3.11.5-GCCcore-13.2.0
~/venvs/fixes_2026-11-11/bin/python src/scripts/fixes_v32/human_review/import_human_review.py "$@"
