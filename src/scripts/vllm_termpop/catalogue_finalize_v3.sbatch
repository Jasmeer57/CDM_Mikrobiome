#!/bin/bash
#SBATCH --job-name=cat-final-v3
#SBATCH --output=outputs/logs/catalogue_finalize_v3_%j.out
#SBATCH --error=outputs/logs/catalogue_finalize_v3_%j.err
#SBATCH --partition=intelsr_short
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=02:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1

# ──────────────────────────────────────────────────────────────────────────────
# CPU follow-up to the Phase B linking job (docs/catalogue_cleanup_plan.md):
#   C  controlled vocabularies on the linked catalogue (offline: NCBI cache)
#   D3 fail-closed QA
#   E  human-validation sample + reviewer guide
#   D  freeze releases/data_catalogue_v3/<VERSION> (refuses if it exists)
#
# Needs, prepared beforehand on a login node (network):
#   outputs/results/catalogue_v3_licences/paper_licences.csv  (fetch_paper_licences.py)
#   src/configs/catalogue_vocab/ncbi_taxon_cache.json         (normalize_catalogue_vocab.py)
#
# Chain after the linking job:
#   sbatch --dependency=afterok:<link_jobid> src/scripts/vllm_termpop/catalogue_finalize_v3.sbatch
# Submit from the repo root (log paths above are root-relative).
# ──────────────────────────────────────────────────────────────────────────────

CDM_ROOT="${CDM_REPO_ROOT:-$(d="${SLURM_SUBMIT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"; while [ "$d" != / ] && [ ! -f "$d/.cdm_root" ]; do d="$(dirname "$d")"; done; echo "$d")}"
[ -f "$CDM_ROOT/.cdm_root" ] || { echo "ERROR: repo root not found; set CDM_REPO_ROOT" >&2; exit 1; }
export CDM_ROOT

set -euo pipefail
cd "$CDM_ROOT"
mkdir -p outputs/logs

VERSION="${VERSION:-3.0.0}"
LINKED=outputs/results/catalogue_v3_linked
FINAL=outputs/results/catalogue_v3_vocab
RELEASE=releases/data_catalogue_v3/$VERSION
S=src/scripts/vllm_termpop

module use /opt/software/easybuild-AMD/modules/all
module load Python/3.12.3-GCCcore-13.3.0
source /home/jkalra_hpc/venvs/vllm/bin/activate
export PYTHONPATH="$CDM_ROOT/src:${PYTHONPATH:-}"
export PYTHONUNBUFFERED=1

echo "========================================================================"
echo "Catalogue v3 finalize — job ${SLURM_JOB_ID:-<local>} on ${SLURM_NODELIST:-$(hostname)}"
echo "  linked input: $LINKED   final: $FINAL   release: $RELEASE"
echo "  started: $(date)"
echo "========================================================================"

[ -f "$LINKED/_link_report.json" ] || { echo "no linked catalogue at $LINKED"; exit 1; }
python - "$LINKED/_link_report.json" <<'PYEOF'
import json, sys
r = json.load(open(sys.argv[1]))
print("linking:", r["papers_run"], "of", r["papers_total"], "papers;", json.dumps(r["stats"].get("batches_failed", 0)), "failed batches")
if r["papers_run"] != r["papers_total"] or r["stats"].get("batches_failed", 0):
    sys.exit("linking incomplete — not finalizing")
PYEOF

echo "[$(date +%T)] C  vocabularies (offline)"
python $S/normalize_catalogue_vocab.py --offline --input_dir "$LINKED" --output_dir "$FINAL"

echo "[$(date +%T)] D3 QA"
python $S/qa_catalogue_v3.py --catalogue_dir "$FINAL"

echo "[$(date +%T)] E  validation sample"
python $S/make_validation_sample.py make --catalogue_dir "$FINAL"

echo "[$(date +%T)] D  release $VERSION"
python $S/build_catalogue_release.py --catalogue_dir "$FINAL" --version "$VERSION"
(cd "$RELEASE" && sha256sum -c MANIFEST.sha256 --quiet && echo "manifest verified: $(wc -l < MANIFEST.sha256) files")

echo "[$(date +%T)] done — $RELEASE"
