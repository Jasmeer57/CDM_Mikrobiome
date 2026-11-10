#!/bin/bash
# 453-scope CDM rebuild: dedup -> ontology mapping -> 5-step CDM builder.
#
# Scope: ALL 453 papers (CDM_EXCLUDE_PAPERS deliberately unset — this is the
# full-corpus counterpart of the retired 452 staging build, which excluded
# HMPAPER_000372).
#
# Inputs: 24 section-level CSVs listed in outputs/results/cdm_453/ner_inputs.txt
# (copied from the 452 build): 7-model section ensemble + both Qwen
# artifacts + 15 variant CSVs incl. the 5 Java tool CSVs.
#
# Mapping resumes from outputs/results/cdm_453/mapping/mapping_checkpoint.json (first
# seeded from the 452 checkpoint), so only new terms hit the online APIs.
#
# Outputs (outputs/results/cdm_453/):
#   ner/deduplicated_entities.json          registry from dedup
#   mapping/mapped_entities.json            + checkpoint + summary
#   cdm_output/microbiome_cdm.db  .owl .ttl  data_catalogue.*  cdm_provenance.json
#
# Logs: outputs/logs/cdm_453_build.log (nohup, launched from repo root like:
#   nohup bash src/scripts/run_cdm_453.sh > outputs/logs/cdm_453_build.log 2>&1 & )
# Repo root, found at run time: $CDM_REPO_ROOT, else walk up to .cdm_root
# from the submit dir (sbatch) or this script's dir (direct run).
CDM_ROOT="${CDM_REPO_ROOT:-$(d="${SLURM_SUBMIT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"; while [ "$d" != / ] && [ ! -f "$d/.cdm_root" ]; do d="$(dirname "$d")"; done; echo "$d")}"
[ -f "$CDM_ROOT/.cdm_root" ] || { echo "ERROR: repo root not found; set CDM_REPO_ROOT" >&2; exit 1; }
export CDM_ROOT

set -euo pipefail
cd $CDM_ROOT

# Work interpreter + API keys for the mapping stage (keys are never printed).
source /home/jkalra_hpc/venvs/vllm/bin/activate
set -a; source .env; set +a

export PYTHONPATH="$PWD/src"
export CDM_NER_OUTPUT_DIR="$PWD/outputs/results/cdm_453/ner"
export CDM_NER_CSVS="$(tr '\n' ',' < outputs/results/cdm_453/ner_inputs.txt | sed 's/,$//')"
# CDM_EXCLUDE_PAPERS deliberately unset: 453-paper scope.

echo "=== [1/3] dedup: 453 scope, ${CDM_NER_CSVS} ===" | tr ',' ' ' | head -c 300; echo
python -m cdm_pipeline.dedup --output "$CDM_NER_OUTPUT_DIR/deduplicated_entities.json"

echo "=== [2/3] ontology mapping (checkpoint-seeded from 452) ==="
python -m cdm_pipeline.mapping.runner

echo "=== [3/3] CDM builder: corpus -> db -> owl -> catalogue -> provenance ==="
python -m cdm_pipeline.cdm.builder

echo "=== 453 CDM rebuild chain DONE ==="
