#!/bin/bash
#SBATCH --job-name=export-db
#SBATCH --output=outputs/logs/release/%x_%j.out
#SBATCH --error=outputs/logs/release/%x_%j.err
#SBATCH --cpus-per-task=2
#SBATCH --mem=16G
#SBATCH --time=03:00:00
# Export a CDM database to per-table CSV.  DB=<path> OUT=<folder> FLAGS=--internal
CDM_ROOT="${CDM_REPO_ROOT:-$(d="${SLURM_SUBMIT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"; while [ "$d" != / ] && [ ! -f "$d/.cdm_root" ]; do d="$(dirname "$d")"; done; echo "$d")}"
cd "$CDM_ROOT/src/scripts/release"
module use /opt/software/easybuild-AMD/modules/all; module load Python/3.12.3-GCCcore-13.3.0
export PYTHONUNBUFFERED=1
python export_db_tables.py --db "$DB" --out "$OUT" ${FLAGS:-}
