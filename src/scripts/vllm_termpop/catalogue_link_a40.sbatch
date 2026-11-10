#!/bin/bash
#SBATCH --job-name=cat-link
#SBATCH --output=outputs/logs/catalogue_link_%j.out
#SBATCH --error=outputs/logs/catalogue_link_%j.err
#SBATCH --partition=mlgpu_medium
#SBATCH --gres=gpu:a40:1
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --time=12:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1

# ──────────────────────────────────────────────────────────────────────────────
# Phase B of docs/catalogue_cleanup_plan.md — within-paper linking of catalogue
# records (cohort/assay/dataset ids) over the 453-paper corpus.
#
# Serves Qwen3.5-4B with vLLM on one A40 and runs
# src/scripts/vllm_termpop/link_catalogue.py on the Phase A output.
#
# Checkpointed: re-submit and it resumes from <RESULTS_DIR>/_link_cache.json.
#
# Smoke test (3 papers):  MAX_PAPERS=3 RESULTS_DIR=outputs/results/catalogue_v3_link_smoke \
#                             sbatch src/scripts/vllm_termpop/catalogue_link_a40.sbatch
# Full corpus:            sbatch src/scripts/vllm_termpop/catalogue_link_a40.sbatch
# Submit from the repo root (log paths above are root-relative).
# ──────────────────────────────────────────────────────────────────────────────

# Repo root, found at run time: $CDM_REPO_ROOT, else walk up to .cdm_root
# from the submit dir (sbatch) or this script's dir (direct run).
CDM_ROOT="${CDM_REPO_ROOT:-$(d="${SLURM_SUBMIT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"; while [ "$d" != / ] && [ ! -f "$d/.cdm_root" ]; do d="$(dirname "$d")"; done; echo "$d")}"
[ -f "$CDM_ROOT/.cdm_root" ] || { echo "ERROR: repo root not found; set CDM_REPO_ROOT" >&2; exit 1; }
export CDM_ROOT

set -uo pipefail
cd "$CDM_ROOT"
mkdir -p outputs/logs

MODEL="${MODEL:-Qwen/Qwen3.5-4B}"
PORT="${PORT:-8000}"
PARALLEL="${PARALLEL:-32}"
MAX_PAPERS="${MAX_PAPERS:-}"
INPUT_DIR="${INPUT_DIR:-outputs/results/catalogue_v3_clean}"
RESULTS_DIR="${RESULTS_DIR:-outputs/results/catalogue_v3_linked}"
REQUEST_TIMEOUT="${REQUEST_TIMEOUT:-600}"

echo "========================================================================"
echo "Catalogue linking (Phase B) — Qwen3.5-4B via vLLM on A40"
echo "  Job ID:     ${SLURM_JOB_ID:-<none>}   Node: ${SLURM_NODELIST:-<local>}"
echo "  Input:      $INPUT_DIR"
echo "  Output:     $RESULTS_DIR"
echo "  Max papers: ${MAX_PAPERS:-<all 453>}"
echo "  Started:    $(date)"
echo "========================================================================"

module use /opt/software/easybuild-AMD/modules/all
module load Python/3.12.3-GCCcore-13.3.0
module load CUDA/12.9.1
source /home/jkalra_hpc/venvs/vllm/bin/activate

export CUDA_HOME="$(dirname "$(dirname "$(command -v nvcc)")")"
export HF_HOME=/home/jkalra_hpc/llm/hf-cache
export PYTHONPATH="$CDM_ROOT/src:${PYTHONPATH:-}"
export PYTHONUNBUFFERED=1
export PYTHONIOENCODING=utf-8
export TOKENIZERS_PARALLELISM=false

mkdir -p "$RESULTS_DIR"
nvidia-smi -L || true

echo "[$(date +%T)] starting vLLM server ..."
vllm serve "$MODEL" \
    --port "$PORT" \
    --gpu-memory-utilization 0.90 \
    --max-model-len 32768 \
    > "$RESULTS_DIR/vllm_server.log" 2>&1 &
SERVER_PID=$!

cleanup() {
    echo "[$(date +%T)] stopping vLLM server (pid $SERVER_PID)"
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
}
trap cleanup EXIT

ready=""
for _ in $(seq 1 180); do
    if curl -sf "http://127.0.0.1:${PORT}/v1/models" > /dev/null 2>&1; then ready=1; break; fi
    if ! kill -0 "$SERVER_PID" 2>/dev/null; then
        echo "vLLM server died during startup — see $RESULTS_DIR/vllm_server.log"
        tail -40 "$RESULTS_DIR/vllm_server.log"; exit 1
    fi
    sleep 5
done
[ -n "$ready" ] || { echo "vLLM server not ready in 15 min"; tail -40 "$RESULTS_DIR/vllm_server.log"; exit 1; }
echo "[$(date +%T)] server ready"

ARGS=(--input_dir "$INPUT_DIR" --output_dir "$RESULTS_DIR" --model "$MODEL"
      --host "http://127.0.0.1:${PORT}" --parallel "$PARALLEL" --request_timeout "$REQUEST_TIMEOUT")
[ -n "$MAX_PAPERS" ] && ARGS+=(--max_papers "$MAX_PAPERS")

echo "[$(date +%T)] running link_catalogue.py ${ARGS[*]}"
python src/scripts/vllm_termpop/link_catalogue.py "${ARGS[@]}"
RC=$?
echo "[$(date +%T)] linking exit code: $RC"
echo "Outputs: $RESULTS_DIR"
exit $RC
