#!/bin/bash
#SBATCH --job-name=judge-a40
#SBATCH --output=outputs/logs/llm_judge/run_judge_a40-%j.out
#SBATCH --error=outputs/logs/llm_judge/run_judge_a40-%j.err
#SBATCH --partition=mlgpu_short
#SBATCH --gres=gpu:a40:2
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --time=02:00:00

# ──────────────────────────────────────────────────────────────────────────────
# LLM-as-judge, SINGLE JOB — serves vLLM and runs the judge client in the SAME
# allocation. Mirrors src/scripts/vllm_termpop/qwen_sections_body_a40.sbatch.
#
# Judge model: Gemma 4 E4B, compressed-tensors W4A16 (auto-detected).
# The extractor under audit is Qwen 3.5:9b — a DIFFERENT model family.
# This is LLM-as-judge, NOT a human gold standard and NOT human validation.
#
# WHY SINGLE JOB: the retired two-job A100 pipeline could not attach its client
# to the server (see src/scripts/llm_judge_gemma4/deprecated/README.md). Serving and
# consuming in one allocation removes the dependency problem entirely: there is
# no second job, no --dependency, and no idle GPU.
#
#   sbatch src/scripts/llm_judge_a40/run_judge_a40.sbatch
#   LIMIT=5 sbatch src/scripts/llm_judge_a40/run_judge_a40.sbatch   # smoke test
#
# GPU count / parallelism: 2× A40 with tensor parallelism 2 by default. Override
# with TP=1 (and --gres=gpu:a40:1 on the sbatch command line) if a single GPU is
# preferred; throughput roughly halves but nothing else changes.
# ──────────────────────────────────────────────────────────────────────────────

# Repo root, found at run time: $CDM_REPO_ROOT, else walk up to .cdm_root
# from the submit dir (sbatch) or this script's dir (direct run).
CDM_ROOT="${CDM_REPO_ROOT:-$(d="${SLURM_SUBMIT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"; while [ "$d" != / ] && [ ! -f "$d/.cdm_root" ]; do d="$(dirname "$d")"; done; echo "$d")}"
[ -f "$CDM_ROOT/.cdm_root" ] || { echo "ERROR: repo root not found; set CDM_REPO_ROOT" >&2; exit 1; }
export CDM_ROOT

set -uo pipefail

export PROJECT_ROOT="$CDM_ROOT"
cd "$PROJECT_ROOT" || exit 1

OUTD="$PROJECT_ROOT/outputs/logs/llm_judge"
PIPE="$PROJECT_ROOT/src/scripts/llm_judge_a40"
RESULTS="$OUTD/results"

MODEL="${MODEL:-google/gemma-4-E4B-it-qat-w4a16-ct}"
PORT="${PORT:-8000}"
PARALLEL="${PARALLEL:-32}"
TP="${TP:-2}"
LIMIT="${LIMIT:-}"

mkdir -p "$OUTD" "$RESULTS"

echo "========================================================================"
echo "LLM-as-judge — Gemma 4 E4B W4A16 (compressed-tensors) on A40"
echo "  Job ID:    ${SLURM_JOB_ID:-<none>}"
echo "  Node:      ${SLURM_NODELIST:-<none>}"
echo "  Model:     $MODEL"
echo "  TP:        $TP   Parallel: $PARALLEL   Port: $PORT"
echo "  Limit:     ${LIMIT:-<all 500 per artifact>}"
echo "  Started:   $(date)"
echo "========================================================================"

# ── Modules (A40 / CUDA) — same env as qwen_sections_body_a40.sbatch ─────────
module use /opt/software/easybuild-AMD/modules/all
module load Python/3.12.3-GCCcore-13.3.0
module load CUDA/12.9.1
source /home/jkalra_hpc/venvs/vllm/bin/activate

export CUDA_HOME="$(dirname "$(dirname "$(command -v nvcc)")")"
# The CT checkpoint is cached in the default HF cache, NOT in
# /home/jkalra_hpc/llm/hf-cache (that path has no gemma-4 model). Overridable.
export HF_HOME="${HF_HOME:-/home/jkalra_hpc/.cache/huggingface}"
export HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}"
export PYTHONPATH="$PROJECT_ROOT/src:${PYTHONPATH:-}"
export PYTHONUNBUFFERED=1
export PYTHONIOENCODING=utf-8
export TOKENIZERS_PARALLELISM=false
export VLLM_WORKER_MULTIPROC_METHOD=spawn

echo "HF_HOME=$HF_HOME"
nvidia-smi -L || true

# ── Serve the judge model ────────────────────────────────────────────────────
echo "[$(date +%T)] starting vLLM server ..."
vllm serve "$MODEL" \
    --port "$PORT" \
    --tensor-parallel-size "$TP" \
    --gpu-memory-utilization 0.90 \
    --max-model-len 8192 \
    --trust-remote-code \
    --default-chat-template-kwargs '{"enable_thinking": false}' \
    > "$OUTD/vllm_server.log" 2>&1 &
VLLM_PID=$!

cleanup() {
    echo "[$(date +%T)] stopping vLLM server (pid $VLLM_PID)"
    kill "$VLLM_PID" 2>/dev/null || true
    wait "$VLLM_PID" 2>/dev/null || true
}
trap cleanup EXIT

# ── Readiness: poll GET /v1/models up to 180 x 5 s (mirror REF_SBATCH) ───────
ready=""
for _ in $(seq 1 180); do
    if curl -sf "http://127.0.0.1:${PORT}/v1/models" > /dev/null 2>&1; then
        ready=1; break
    fi
    if ! kill -0 "$VLLM_PID" 2>/dev/null; then
        echo "SERVER_DIED during startup — see $OUTD/vllm_server.log"
        tail -50 "$OUTD/vllm_server.log"
        exit 1
    fi
    sleep 5
done
if [ -z "$ready" ]; then
    echo "SERVER_TIMEOUT (not ready in 15 min) — see $OUTD/vllm_server.log"
    tail -50 "$OUTD/vllm_server.log"
    exit 1
fi
echo "SERVER_READY at $(date -u)"
echo "[$(date +%T)] models: $(curl -s "http://127.0.0.1:${PORT}/v1/models" | head -c 200)"

# ── Smoke test: 3 items on C1, verify JSON mode + verdict parsing ────────────
echo "[$(date +%T)] smoke test (3 items, C1) ..."
if python "$PIPE/run_judge_client_a40.py" \
        --input "$OUTD/input_C1.jsonl" \
        --output "$OUTD/smoke_C1.jsonl" \
        --model "$MODEL" --port "$PORT" --parallel 3 --limit 3 \
        --artifact C1 --prompt "$PIPE/prompts/judge_C1.txt"; then
    echo "[$(date +%T)] smoke test PASS"
    head -3 "$OUTD/smoke_C1.jsonl"
else
    echo "SMOKE_FAIL — judge client could not produce a valid verdict; aborting"
    head -3 "$OUTD/smoke_C1.jsonl" 2>/dev/null
    exit 1
fi

# ── Run the judge for all four artifacts ────────────────────────────────────
rc=0
for artifact in C1 C2 C3 C4; do
    echo "------------------------------------------------------------------------"
    echo "[$(date +%T)] judging $artifact ..."
    ARGS=(
        --input "$OUTD/input_${artifact}.jsonl"
        --output "$RESULTS/${artifact}_verdicts.jsonl"
        --model "$MODEL" --port "$PORT" --parallel "$PARALLEL"
        --artifact "$artifact"
        --prompt "$PIPE/prompts/judge_${artifact}.txt"
    )
    [ -n "$LIMIT" ] && ARGS+=(--limit "$LIMIT")
    python "$PIPE/run_judge_client_a40.py" "${ARGS[@]}" || rc=1
done

# ── Compute metrics ─────────────────────────────────────────────────────────
echo "------------------------------------------------------------------------"
echo "[$(date +%T)] computing metrics ..."
python "$PIPE/compute_judge_metrics_a40.py" \
    --results "$RESULTS" \
    --out "$OUTD/JUDGE_METRICS.md" || rc=1

echo "========================================================================"
echo "DONE at $(date -u)  rc=$rc"
echo "  results: $RESULTS"
echo "  metrics: $OUTD/JUDGE_METRICS.md"
echo "========================================================================"
exit $rc
