#!/bin/bash
#SBATCH --job-name=cat-deep-probe
#SBATCH --partition=mlgpu_short
#SBATCH --gres=gpu:a40:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=02:00:00
#SBATCH --output=outputs/logs/catalogue_deep_probe_%j.out
#SBATCH --error=outputs/logs/catalogue_deep_probe_%j.err
# ──────────────────────────────────────────────────────────────────────────────
# Read-only probe: characterize the 9 catalogue segments that pass 2 left
# truncated (job 28663900), using GENUINE recursive bisection.
#
# Why a second probe. The first probe (job 28663870) reported "30 of 32 resolve
# by halving" and pass 2 delivered 23 of 32. The probe was wrong, and the defect
# is in the probe:
#
#     piece = text[: max(1, len(text) // d)]          # prefix truncation
#
# It tested only the FIRST 1/d of each passage, never the later halves. A real
# halving repair needs BOTH halves of every split to fit, and the dense content
# of a results section sits in the middle and at the end. So the probe measured
# "the opening text is fine", which was never in doubt.
#
# This probe bisects properly and records EVERY node of the descent, attempting
# both halves at each level, so the smallest piece that still overflows the
# 4,096-token output budget is measured rather than predicted.
#
# It decides between two policies:
#   H1 SIZE-DRIVEN  - halving eventually fits; the fix is a lower split floor.
#   H2 VOLUME-FLOOR - a small input still emits ~4,096 tokens, exactly the
#                     failure mode documented for llm-ner-body (truncation at a
#                     near-constant output length independent of input). No
#                     depth of halving fits; the honest outcome is a reported
#                     residual with the measured reason attached.
#
# It NEVER writes the cache and never touches any pipeline artifact. The only
# output is outputs/results/catalogue_ner_v2/_deep_split_probe.json.
#
#   sbatch src/scripts/vllm_termpop/probe_deep_split_a40.sbatch
#   FLOOR=100 sbatch ...            # bisect deeper before giving up
#   MAX_NODES=60 sbatch ...         # allow a larger per-target tree
# ──────────────────────────────────────────────────────────────────────────────

# Repo root, found at run time: $CDM_REPO_ROOT, else walk up to .cdm_root
# from the submit dir (sbatch) or this script's dir (direct run).
CDM_ROOT="${CDM_REPO_ROOT:-$(d="${SLURM_SUBMIT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"; while [ "$d" != / ] && [ ! -f "$d/.cdm_root" ]; do d="$(dirname "$d")"; done; echo "$d")}"
[ -f "$CDM_ROOT/.cdm_root" ] || { echo "ERROR: repo root not found; set CDM_REPO_ROOT" >&2; exit 1; }
export CDM_ROOT

set -uo pipefail

export PROJECT_ROOT="$CDM_ROOT"
cd "$PROJECT_ROOT"
mkdir -p logs

MODEL="${MODEL:-Qwen/Qwen3.5-4B}"
PORT="${PORT:-8000}"
OUT_DIR="${OUT_DIR:-results/catalogue_ner_v2}"
PARALLEL="${PARALLEL:-9}"
FLOOR="${FLOOR:-200}"
MAX_NODES="${MAX_NODES:-40}"
KEYS_FILE="${KEYS_FILE:-$OUT_DIR/_residual_keys_pass2.txt}"

if [ ! -f "$KEYS_FILE" ]; then
    echo "keys file not found: $KEYS_FILE"
    exit 1
fi

echo "========================================================================"
echo "Catalogue deep-split probe — residual leaves — Qwen3.5-4B on A40"
echo "  Job ID:      ${SLURM_JOB_ID:-<none>}"
echo "  Node:        ${SLURM_NODELIST:-<none>}"
echo "  Model:       $MODEL"
echo "  Output dir:  $OUT_DIR"
echo "  Keys file:   $KEYS_FILE  ($(wc -l < "$KEYS_FILE") keys)"
echo "  Floor:       $FLOOR chars   Max nodes/target: $MAX_NODES"
echo "  Method:      GENUINE bisection, both halves attempted"
echo "  Writes:      $OUT_DIR/_deep_split_probe.json  (cache untouched)"
echo "  Started:     $(date)"
echo "========================================================================"

module use /opt/software/easybuild-AMD/modules/all
module load Python/3.12.3-GCCcore-13.3.0
module load CUDA/12.9.1
source /home/jkalra_hpc/venvs/vllm/bin/activate

export CUDA_HOME="$(dirname "$(dirname "$(command -v nvcc)")")"
export HF_HOME=/home/jkalra_hpc/llm/hf-cache
export HF_HUB_OFFLINE=0
export PYTHONPATH="$PROJECT_ROOT/src:${PYTHONPATH:-}"
export PYTHONUNBUFFERED=1
export PYTHONIOENCODING=utf-8
export TOKENIZERS_PARALLELISM=false

nvidia-smi -L || true

echo "[$(date +%T)] starting vLLM server ..."
vllm serve "$MODEL" \
    --port "$PORT" \
    --gpu-memory-utilization 0.90 \
    --max-model-len 32768 \
    > "$OUT_DIR/vllm_server_deepprobe_${SLURM_JOB_ID:-local}.log" 2>&1 &
SERVER_PID=$!

ready=""
for _ in $(seq 1 180); do
    if curl -sf "http://127.0.0.1:${PORT}/v1/models" > /dev/null 2>&1; then
        ready=1; break
    fi
    if ! kill -0 "$SERVER_PID" 2>/dev/null; then
        echo "vLLM server died during startup — see the server log"
        tail -40 "$OUT_DIR/vllm_server_deepprobe_${SLURM_JOB_ID:-local}.log"
        exit 1
    fi
    sleep 5
done

if [ -z "$ready" ]; then
    echo "vLLM server not ready in 15 min — see server log"
    tail -40 "$OUT_DIR/vllm_server_deepprobe_${SLURM_JOB_ID:-local}.log"
    kill "$SERVER_PID" 2>/dev/null || true
    exit 1
fi
echo "[$(date +%T)] server ready"

cleanup() {
    echo "[$(date +%T)] stopping vLLM server (pid $SERVER_PID)"
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
}
trap cleanup EXIT

echo "[$(date +%T)] running probe_deep_split.py ..."
python outputs/scratch/probe_deep_split.py \
    --model "$MODEL" \
    --host "http://127.0.0.1:${PORT}" \
    --keys_file "$KEYS_FILE" \
    --floor "$FLOOR" \
    --max_nodes "$MAX_NODES" \
    --parallel "$PARALLEL"
RC=$?

echo "[$(date +%T)] probe exit code: $RC"
echo "Output: $OUT_DIR/_deep_split_probe.json"
exit $RC
