#!/bin/bash
#SBATCH --job-name=v32-exports
#SBATCH --partition=intelsr_short
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=48G
#SBATCH --time=04:00:00
#SBATCH --output=outputs/logs/v32_exports_%j.out
#SBATCH --error=outputs/logs/v32_exports_%j.err
# SSSOM, KGX and RDF exports of the 3.2.0-candidate DB + validation.
# Submit from the repo root:  sbatch src/scripts/fixes_v32/export/run_exports.sbatch
set -euo pipefail
CDM_ROOT="$(pwd)"; while [ ! -f "$CDM_ROOT/.cdm_root" ] && [ "$CDM_ROOT" != "/" ]; do CDM_ROOT="$(dirname "$CDM_ROOT")"; done
cd "$CDM_ROOT"
module load Python/3.11.5-GCCcore-13.2.0
PY=~/venvs/fixes_2026-11-11/bin/python
$PY src/scripts/fixes_v32/export/export_sssom.py
$PY src/scripts/fixes_v32/export/export_kgx.py
$PY src/scripts/fixes_v32/export/export_rdf.py
$PY src/scripts/fixes_v32/export/validate_exports.py
