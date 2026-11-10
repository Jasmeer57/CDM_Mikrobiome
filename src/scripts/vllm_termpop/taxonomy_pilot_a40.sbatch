#!/bin/bash
#SBATCH --job-name=cat-taxpilot
#SBATCH --output=outputs/logs/taxonomy_pilot_%j.out
#SBATCH --error=outputs/logs/taxonomy_pilot_%j.err
#SBATCH --partition=mlgpu_medium
#SBATCH --gres=gpu:a40:1
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --nodes=1
#SBATCH --time=08:00:00

# ──────────────────────────────────────────────────────────────────────────────
# STAGE 2 pilot: classify a sample of the 166k-term inventory against the fixed
# taxonomy (taxonomy/term_taxonomy_v1.yaml, 16 upper + 66 subcategories).
#
# Extraction (stage 1, catalogue_ner.py) and classification (stage 2) are
# deliberately separate stages with separate evaluation. This job only answers
# "does the taxonomy cover what the corpus actually contains, and where does it
# fail?" — it is a coverage probe, not the full classification run.
#
# Terms that do not fit are emitted as UNCERTAIN/needs_review, never forced into
# a category, so the output doubles as the taxonomy-gap list.
#
# Requires the extraction recovery job to have released the GPU (same node class).
#
#   sbatch --dependency=afterany:<recovery_jobid> src/scripts/vllm_termpop/taxonomy_pilot_a40.sbatch
#   LIMIT=2000 sbatch ...                     # bigger pilot
#   SAMPLE=head sbatch ...                    # most-frequent terms instead
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
PARALLEL="${PARALLEL:-32}"
INPUT="${INPUT:-data/catalogue/terminology_dedup.csv}"
TAXONOMY="${TAXONOMY:-data/reference/taxonomy/term_taxonomy_v1.yaml}"
LIMIT="${LIMIT:-500}"
SAMPLE="${SAMPLE:-stratified}"
SEED="${SEED:-17}"
BATCH_SIZE="${BATCH_SIZE:-20}"
RESULTS_DIR="${RESULTS_DIR:-results/taxonomy_pilot}"
OUT_PREFIX="${OUT_PREFIX:-$RESULTS_DIR/term_categories_pilot}"

mkdir -p "$RESULTS_DIR"

echo "========================================================================"
echo "Taxonomy classification PILOT — Qwen3.5-4B via vLLM on A40"
echo "  Job ID:    $SLURM_JOB_ID"
echo "  Node:      $SLURM_NODELIST"
echo "  Input:     $INPUT"
echo "  Taxonomy:  $TAXONOMY"
echo "  Sample:    $SAMPLE  limit=$LIMIT  seed=$SEED"
echo "  Output:    $OUT_PREFIX{,.csv,_cache.json}"
echo "  Started:   $(date)"
echo "========================================================================"

# ── Modules (A40 / CUDA, same as catalogue_ner_a40.sbatch) ────────────────────
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

# ── Serve the model (identical config to the extraction run) ──────────────────
echo "[$(date +%T)] starting vLLM server ..."
vllm serve "$MODEL" \
    --port "$PORT" \
    --gpu-memory-utilization 0.90 \
    --max-model-len 32768 \
    > "$RESULTS_DIR/vllm_server.log" 2>&1 &
SERVER_PID=$!

ready=""
for _ in $(seq 1 180); do
    if curl -sf "http://127.0.0.1:${PORT}/v1/models" > /dev/null 2>&1; then
        ready=1; break
    fi
    if ! kill -0 "$SERVER_PID" 2>/dev/null; then
        echo "vLLM server died during startup — see $RESULTS_DIR/vllm_server.log"
        tail -40 "$RESULTS_DIR/vllm_server.log"
        exit 1
    fi
    sleep 5
done

if [ -z "$ready" ]; then
    echo "vLLM server did not become ready in 15 min — see $RESULTS_DIR/vllm_server.log"
    tail -40 "$RESULTS_DIR/vllm_server.log"
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

# ── Run the classifier ────────────────────────────────────────────────────────
echo "[$(date +%T)] classifying $LIMIT terms ($SAMPLE) ..."
python src/scripts/vllm_termpop/categorize_terms.py \
    --input "$INPUT" \
    --taxonomy "$TAXONOMY" \
    --output "$OUT_PREFIX" \
    --host "http://127.0.0.1:${PORT}" \
    --model "$MODEL" \
    --parallel "$PARALLEL" \
    --batch_size "$BATCH_SIZE" \
    --limit "$LIMIT" \
    --sample "$SAMPLE" \
    --seed "$SEED"
RC=$?

echo "[$(date +%T)] classification exit code: $RC"
echo "========================================================================"
echo "Pilot output: $OUT_PREFIX.csv (+ _cache.json)"
if [ -f "${OUT_PREFIX}.csv" ]; then
    echo "First rows:"
    head -3 "${OUT_PREFIX}.csv"
fi
exit $RC
