#!/bin/bash
#SBATCH --job-name=judge-full
#SBATCH --output=outputs/logs/llm_judge/run_judge_full-%j.out
#SBATCH --error=outputs/logs/llm_judge/run_judge_full-%j.err
#SBATCH --partition=mlgpu_short
#SBATCH --gres=gpu:a40:2
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --time=08:00:00

# ──────────────────────────────────────────────────────────────────────────────
# F3 — FULL-SCALE LLM-as-judge, SINGLE JOB (serve + consume in one allocation).
#
# Judge model: Gemma 4 E4B, compressed-tensors W4A16 (auto-detected), TP=2 on 2×A40.
# The extractor under audit is Qwen 3.5:9b — a DIFFERENT model family.
# This is LLM-as-judge. It is NOT a human gold standard and NOT human validation.
#
# ALL 451,799 items across the four artifacts:
#   C2  27,870  inventory -> canonical type pairs
#   C4  32,713  canonical triples
#   C1  56,985  catalogue records
#   C3 334,231  ontology mappings
#
# SIZE ORDER (smallest first). If the 8 h walltime truncates, it truncates inside
# C3, which is the largest and most expendable artifact — C2/C4/C1 are already
# complete and usable. Progress is not lost: the client writes a resume cache
# ($OUTD/_judge_full_cache.json) keyed by sha1(item_id|prompt_version), so a
# resubmission continues where this one stopped instead of re-judging.
#
# FAIL-CLOSED: the final metrics call passes --require-complete, so a partial run
# produces INCOMPLETE + exit 1 rather than numbers that look like a full run. On
# any artifact failure the script writes JUDGE_METRICS_FULL_PARTIAL.md and exits 2.
#
# No --dependency, no OpenAI SDK, no guided decoding (all proven failure modes —
# see src/scripts/llm_judge_gemma4/deprecated/README.md).
#
#   sbatch src/scripts/llm_judge_a40/run_judge_full.sbatch
#   LIMIT=200 sbatch src/scripts/llm_judge_a40/run_judge_full.sbatch   # dry run
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
CACHE="$OUTD/_judge_full_cache.json"

MODEL="${MODEL:-google/gemma-4-E4B-it-qat-w4a16-ct}"
PORT="${PORT:-8000}"
PARALLEL="${PARALLEL:-32}"
TP="${TP:-2}"
LIMIT="${LIMIT:-}"

mkdir -p "$OUTD" "$RESULTS"

echo "========================================================================"
echo "LLM-as-judge FULL-SCALE — Gemma 4 E4B W4A16 (compressed-tensors) on A40"
echo "  Job ID:    ${SLURM_JOB_ID:-<none>}"
echo "  Node:      ${SLURM_NODELIST:-<none>}"
echo "  Model:     $MODEL"
echo "  TP:        $TP   Parallel: $PARALLEL   Port: $PORT"
echo "  Items:     C2=27870 C4=32713 C1=56985 C3=334231 (total 451799)"
echo "  Order:     C2 -> C4 -> C1 -> C3 (smallest first)"
echo "  Cache:     $CACHE"
echo "  Limit:     ${LIMIT:-<all items>}"
echo "  Started:   $(date)"
echo "  NOTE: LLM-as-judge, NOT a human gold standard. Calibration still pending."
echo "========================================================================"

# ── Modules (A40 / CUDA) — same env as run_judge_a40.sbatch ──────────────────
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

# ── Partial-metrics helper: always leave a report behind on failure ──────────
partial_metrics() {
    echo "[$(date +%T)] writing partial metrics (NOT a complete run) ..."
    python "$PIPE/compute_judge_metrics_a40.py" \
        --results "$RESULTS" \
        --out "$OUTD/JUDGE_METRICS_FULL_PARTIAL.md" || true
    echo "partial metrics: $OUTD/JUDGE_METRICS_FULL_PARTIAL.md"
}

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

# ── Readiness: poll GET /v1/models up to 180 x 5 s ───────────────────────────
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

# ── Fail-fast smoke test: 3 items, C1, separate output file ──────────────────
# Cheap (~1 min) guard against an 8 h job that produces only unparseable JSON.
# Uses the resume client so JSON-mode + verdict validation are exercised exactly
# as they will be for the full run.
echo "[$(date +%T)] smoke test (3 items, C1) ..."
rm -f "$OUTD/smoke_full_C1.jsonl"
if python "$PIPE/run_judge_client_full.py" \
        --input "$OUTD/input_full_C1.jsonl" \
        --output "$OUTD/smoke_full_C1.jsonl" \
        --cache "$OUTD/_smoke_full_cache.json" \
        --model "$MODEL" --port "$PORT" --parallel 3 --limit 3 \
        --artifact C1 --prompt "$PIPE/prompts/judge_C1.txt"; then
    echo "[$(date +%T)] smoke test PASS"
    head -3 "$OUTD/smoke_full_C1.jsonl"
else
    echo "SMOKE_FAIL — judge client could not produce a valid verdict; aborting"
    head -3 "$OUTD/smoke_full_C1.jsonl" 2>/dev/null
    tail -30 "$OUTD/vllm_server.log"
    exit 1
fi

# ── Full run: smallest artifact first ───────────────────────────────────────
for artifact in C2 C4 C1 C3; do
    case $artifact in
        C2) prompt=judge_C2; n=27870  ;;
        C4) prompt=judge_C4; n=32713  ;;
        C1) prompt=judge_C1; n=56985  ;;
        C3) prompt=judge_C3; n=334231 ;;
    esac

    echo "------------------------------------------------------------------------"
    echo "=== START $artifact ($n items) at $(date -u) ==="

    ARGS=(
        --input  "$OUTD/input_full_${artifact}.jsonl"
        --output "$RESULTS/${artifact}_full_verdicts.jsonl"
        --cache  "$CACHE"
        --model  "$MODEL" --port "$PORT" --parallel "$PARALLEL"
        --artifact "$artifact"
        --prompt "$PIPE/prompts/${prompt}.txt"
        --progress-every 500
    )
    [ -n "$LIMIT" ] && ARGS+=(--limit "$LIMIT")

    python "$PIPE/run_judge_client_full.py" "${ARGS[@]}"
    rc=$?
    if [ "$rc" -ne 0 ]; then
        echo "=== FAILED $artifact at $(date -u) (rc=$rc); writing partial metrics ==="
        partial_metrics
        exit 2
    fi
    echo "=== DONE $artifact at $(date -u) ==="
done

# ── Final metrics (fail-closed) ─────────────────────────────────────────────
echo "------------------------------------------------------------------------"
echo "[$(date +%T)] computing metrics (--require-complete) ..."
python "$PIPE/compute_judge_metrics_a40.py" \
    --results "$RESULTS" \
    --out "$OUTD/JUDGE_METRICS_FULL.md" \
    --require-complete
mrc=$?
if [ "$mrc" -ne 0 ]; then
    echo "METRICS_INCOMPLETE (rc=$mrc) — some artifact is below its full-set size"
    partial_metrics
    exit 1
fi

echo "========================================================================"
echo "ALL_DONE at $(date -u)"
echo "  results: $RESULTS"
echo "  metrics: $OUTD/JUDGE_METRICS_FULL.md"
echo "  cache:   $CACHE"
echo "  REMINDER: LLM-as-judge, NOT human validation. Calibration still pending."
echo "========================================================================"
exit 0
