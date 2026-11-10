#!/bin/bash
#SBATCH --job-name=hmcv2-fix-000427
#SBATCH --partition=mlgpu_short
#SBATCH --gres=gpu:a40:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=48G
#SBATCH --time=0:30:00
#SBATCH --output=outputs/logs/slurm/%x-%j.out
#SBATCH --error=outputs/logs/slurm/%x-%j.err

# Isolated recovery of the single FAILED section HMPAPER_000427:sec:001.
#
# Deliberately NOT stage 53: stage 53 has no paper filter and writes
# pipelines/corpus_v2/data/triples_sections.jsonl + triple_mentions.jsonl, which are
# byte-identical mirrors of pipelines/corpus_v2/releases/2.2.0/data/. A single-section
# run through stage 53 would replace the full frozen artifacts with one row.
# This job imports stage 53's own helpers unchanged and writes only to
# outputs/scratch/fix_000427/.
#
# max_tokens is raised 4500 -> 8000 in memory only (corpus.yaml untouched).
# The llmio.py split ladder (depth<2, chunk>=2000) is left UNCHANGED.
# Repo root, found at run time: $CDM_REPO_ROOT, else walk up to .cdm_root
# from the submit dir (sbatch) or this script's dir (direct run).
CDM_ROOT="${CDM_REPO_ROOT:-$(d="${SLURM_SUBMIT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"; while [ "$d" != / ] && [ ! -f "$d/.cdm_root" ]; do d="$(dirname "$d")"; done; echo "$d")}"
[ -f "$CDM_ROOT/.cdm_root" ] || { echo "ERROR: repo root not found; set CDM_REPO_ROOT" >&2; exit 1; }
export CDM_ROOT

set -euo pipefail

REPO="$CDM_ROOT"
CORPUS_DIR="$REPO/pipelines/corpus_v2"
OUTDIR="$REPO/outputs/scratch/fix_000427"
MAX_TOKENS=8000

source "$CORPUS_DIR/slurm/_env.sh" fix_000427
module load CUDA/12.9.1
export CUDA_HOME="$(dirname "$(dirname "$(command -v nvcc)")")"
export VLLM_USE_FLASHINFER_SAMPLER=0

mkdir -p "$OUTDIR" "$REPO/outputs/logs/slurm"

JID="${SLURM_JOB_ID:-local}"
PORT=8010
MODEL="Qwen/Qwen3.5-4B"

echo "[$(date -u +%FT%TZ)] node=$(hostname) job=$JID"
nvidia-smi -L || true

# ---- guarded files: md5 BEFORE ---------------------------------------------
GUARDED=(
  "$CORPUS_DIR/data/triples_sections.jsonl"
  "$CORPUS_DIR/data/triple_mentions.jsonl"
  "$CORPUS_DIR/data/canonical_triples.jsonl"
  "$CORPUS_DIR/releases/2.2.0/data/triples_sections.jsonl"
  "$CORPUS_DIR/releases/2.2.0/data/triple_mentions.jsonl"
  "$CORPUS_DIR/releases/2.2.0/data/canonical_triples.jsonl"
)
echo "[$(date -u +%FT%TZ)] hashing ${#GUARDED[@]} guarded files (before)"
md5sum "${GUARDED[@]}" > "$OUTDIR/.md5_before.txt"
cat "$OUTDIR/.md5_before.txt"

# ---- vLLM: single A40 -------------------------------------------------------
echo "[$(date -u +%FT%TZ)] starting vLLM (port $PORT)"
CUDA_VISIBLE_DEVICES=0 vllm serve "$MODEL" \
    --port "$PORT" \
    --gpu-memory-utilization 0.90 \
    --max-model-len 32768 \
    --max-num-seqs 8 \
    --served-model-name "$MODEL" \
    > "$OUTDIR/vllm-${JID}.log" 2>&1 &
SERVER_PID=$!

cleanup() {
    echo "[$(date -u +%FT%TZ)] stopping vLLM pid=$SERVER_PID"
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
}
trap cleanup EXIT

ready=""
for _ in $(seq 1 120); do
    if curl -sf "http://127.0.0.1:${PORT}/v1/models" >/dev/null 2>&1; then
        ready=1; break
    fi
    if ! kill -0 "$SERVER_PID" 2>/dev/null; then
        echo "ERROR: vLLM exited during startup; last 50 lines:" >&2
        tail -50 "$OUTDIR/vllm-${JID}.log" >&2 || true
        exit 1
    fi
    sleep 5
done
if [[ -z "$ready" ]]; then
    echo "ERROR: vLLM not ready after 600s; last 50 lines:" >&2
    tail -50 "$OUTDIR/vllm-${JID}.log" >&2 || true
    exit 1
fi
echo "[$(date -u +%FT%TZ)] vLLM ready"

# ---- the fix ---------------------------------------------------------------
echo "[$(date -u +%FT%TZ)] running isolated recovery (max_tokens=$MAX_TOKENS)"
set +e
python "$OUTDIR/run_fix.py" --max-tokens "$MAX_TOKENS" --port "$PORT" \
    2>&1 | tee "$OUTDIR/run_fix.${JID}.log"
RC=${PIPESTATUS[0]}
set -e
echo "[$(date -u +%FT%TZ)] run_fix exit code: $RC"

# ---- guarded files: md5 AFTER + hard assertion ------------------------------
echo "[$(date -u +%FT%TZ)] hashing ${#GUARDED[@]} guarded files (after)"
md5sum "${GUARDED[@]}" > "$OUTDIR/.md5_after.txt"
if ! diff -u "$OUTDIR/.md5_before.txt" "$OUTDIR/.md5_after.txt"; then
    echo "FATAL: guarded corpus files CHANGED during the run" >&2
    exit 90
fi
echo "PASS: guarded corpus files unchanged"

# ---- read-only baseline re-verification ------------------------------------
fail=0
check_baseline() {  # $1=dir  $2=expected-ok  $3=label
    local dir="$1" expect="$2" label="$3" ok
    ok=$(cd "$dir" && sha256sum -c MANIFEST.sha256 2>/dev/null | grep -c ': OK$' || true)
    if [[ "$ok" == "$expect" ]]; then
        echo "PASS: $label $ok/$expect"
    else
        echo "FAIL: $label $ok/$expect" >&2
        fail=1
    fi
}
check_baseline "$CORPUS_DIR/releases/2.2.0" 42  "pipelines/corpus_v2/releases/2.2.0"
check_baseline "$REPO/releases/data_catalogue"     1003 "data_catalogue"
check_baseline "$REPO/releases/terminology/1.0.0" 22 "releases/terminology/1.0.0"
if [[ "$fail" -ne 0 ]]; then
    echo "FATAL: a read-only baseline failed; stopping" >&2
    exit 91
fi

# ---- outcome ---------------------------------------------------------------
echo "[$(date -u +%FT%TZ)] artifacts:"
ls -la "$OUTDIR" || true
if [[ "$RC" -ne 0 ]]; then
    echo "INCOMPLETE: run_fix exited $RC (see FIX_REPORT.md)" >&2
    exit "$RC"
fi
echo "[$(date -u +%FT%TZ)] DONE"
