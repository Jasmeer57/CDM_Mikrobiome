#!/bin/bash
# Repo root, found at run time: $CDM_REPO_ROOT, else walk up to .cdm_root
# from the submit dir (sbatch) or this script's dir (direct run).
CDM_ROOT="${CDM_REPO_ROOT:-$(d="${SLURM_SUBMIT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"; while [ "$d" != / ] && [ ! -f "$d/.cdm_root" ]; do d="$(dirname "$d")"; done; echo "$d")}"
[ -f "$CDM_ROOT/.cdm_root" ] || { echo "ERROR: repo root not found; set CDM_REPO_ROOT" >&2; exit 1; }
export CDM_ROOT

set -e

eval "$(/opt/software/easybuild/genoa/software/Miniforge3/24.11.3-0/bin/conda shell.bash hook)"
conda activate microbiome-cdm-env

cd $CDM_ROOT

echo "=== MeSH Cross-Reference ==="
echo "Started: $(date)"
echo ""

python -m cdm_pipeline.entrez.mesh_crossref \
    --workers 5 \
    --max-cui-api 12000 \
    --max-label-api 2000 \
    "$@"

echo ""
echo "Finished: $(date)"
