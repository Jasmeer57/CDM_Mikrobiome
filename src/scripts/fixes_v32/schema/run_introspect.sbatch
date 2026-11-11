#!/bin/bash
#SBATCH --job-name=v32-introspect
#SBATCH --partition=intelsr_short
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=48G
#SBATCH --time=03:00:00
#SBATCH --output=outputs/logs/v32_introspect_%j.out
#SBATCH --error=outputs/logs/v32_introspect_%j.err
# Submit from the repo root:  sbatch src/scripts/fixes_v32/schema/run_introspect.sbatch
set -euo pipefail
CDM_ROOT="$(pwd)"; while [ ! -f "$CDM_ROOT/.cdm_root" ] && [ "$CDM_ROOT" != "/" ]; do CDM_ROOT="$(dirname "$CDM_ROOT")"; done
cd "$CDM_ROOT"
module load Python/3.11.5-GCCcore-13.2.0
export SQLITE_TMPDIR="${TMPDIR:-/tmp}"
~/venvs/fixes_2026-11-11/bin/python src/scripts/fixes_v32/schema/introspect.py "$@"
