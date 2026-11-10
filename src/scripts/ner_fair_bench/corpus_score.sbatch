#!/bin/bash
#SBATCH --job-name=corpus-score
#SBATCH --output=outputs/logs/ner_bench/%x_%j.out
#SBATCH --partition=intelsr_short
#SBATCH --cpus-per-task=4
#SBATCH --mem=120G
#SBATCH --time=06:00:00
CDM_ROOT="${CDM_REPO_ROOT:-$(d="${SLURM_SUBMIT_DIR:-$PWD}"; while [ "$d" != / ] && [ ! -f "$d/.cdm_root" ]; do d="$(dirname "$d")"; done; echo "$d")}"
cd "$CDM_ROOT"
module use /opt/software/easybuild-AMD/modules/all; module load Python/3.12.3-GCCcore-13.3.0
python3 src/scripts/ner_fair_bench/corpus_bench.py score
