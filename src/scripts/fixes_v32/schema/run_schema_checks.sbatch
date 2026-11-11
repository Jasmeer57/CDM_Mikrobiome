#!/bin/bash
#SBATCH --job-name=v32-schema-checks
#SBATCH --partition=intelsr_short
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=04:00:00
#SBATCH --output=outputs/logs/v32_schema_checks_%j.out
#SBATCH --error=outputs/logs/v32_schema_checks_%j.err
# Rebuild the candidate DB (3.1.0 copy + human_review), then run the data-conformance check and the FK load test.
# Submit from the repo root:  sbatch src/scripts/fixes_v32/schema/run_schema_checks.sbatch
set -euo pipefail
CDM_ROOT="$(pwd)"; while [ ! -f "$CDM_ROOT/.cdm_root" ] && [ "$CDM_ROOT" != "/" ]; do CDM_ROOT="$(dirname "$CDM_ROOT")"; done
cd "$CDM_ROOT"
module load Python/3.11.5-GCCcore-13.2.0
PY=~/venvs/fixes_2026-11-11/bin/python
$PY src/scripts/fixes_v32/human_review/import_human_review.py --force-copy
$PY src/scripts/fixes_v32/schema/validate_data.py --n 1000
$PY src/scripts/fixes_v32/schema/fk_load_test.py
