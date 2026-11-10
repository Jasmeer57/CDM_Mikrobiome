#!/bin/bash
#SBATCH --job-name=cat-ner
#SBATCH --output=outputs/logs/catalogue_ner_%j.out
#SBATCH --error=outputs/logs/catalogue_ner_%j.err
#SBATCH --partition=mlgpu_medium
#SBATCH --gres=gpu:a40:1
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --time=24:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1

# ──────────────────────────────────────────────────────────────────────────────
# Catalogue-entity NER over the 453-paper segmented corpus.
#
# Serves Qwen3.5-4B with vLLM (OpenAI-compatible API) on one A40 and runs
# src/scripts/vllm_termpop/catalogue_ner.py, which extracts data-catalogue records
# (datasets, data_assets, cohorts, samples, assays, findings) from EVERY section
# of EVERY paper in data/segmented_sections_markdown/ — full sections, coverage-
# preserving segmentation for over-long ones, fail-closed coverage reporting.
#
# Checkpointed: re-submit the same job and it resumes from
# outputs/results/<jobid>_catalogue_ner/_catalogue_cache.json.
#
# Smoke test (2 papers):   MAX_FILES=2 sbatch src/scripts/vllm_termpop/catalogue_ner_a40.sbatch
# Full corpus:             sbatch src/scripts/vllm_termpop/catalogue_ner_a40.sbatch
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
MAX_FILES="${MAX_FILES:-}"
ENTITY_TYPES="${ENTITY_TYPES:-}"
RESULTS_DIR="${RESULTS_DIR:-results/${SLURM_JOB_ID}_catalogue_ner}"
REQUEST_TIMEOUT="${REQUEST_TIMEOUT:-600}"

echo "========================================================================"
echo "Catalogue NER (full-section) — Qwen3.5-4B via vLLM on A40"
echo "  Job ID:   $SLURM_JOB_ID"
echo "  Node:     $SLURM_NODELIST"
echo "  Model:    $MODEL"
echo "  Parallel: $PARALLEL"
echo "  Max files: ${MAX_FILES:-<all>}"
echo "  Output:   $RESULTS_DIR"
echo "  Req tmout: ${REQUEST_TIMEOUT}s"
echo "  Started:  $(date)"
echo "========================================================================"

# ── Modules (A40 / CUDA, same as ~/llm/serve-a40-Qwen3.5-4B.sbatch) ───────────
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

mkdir -p "$RESULTS_DIR"
nvidia-smi -L || true

# ── Serve the model ──────────────────────────────────────────────────────────
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
echo "[$(date +%T)] server ready: $(curl -s "http://127.0.0.1:${PORT}/v1/models" | head -c 200)"

cleanup() {
    echo "[$(date +%T)] stopping vLLM server (pid $SERVER_PID)"
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
}
trap cleanup EXIT

# ── Run the catalogue extraction ─────────────────────────────────────────────
ARGS=(
    --model "$MODEL"
    --host "http://127.0.0.1:${PORT}"
    --output_dir "$RESULTS_DIR"
    --parallel "$PARALLEL"
    --request_timeout "$REQUEST_TIMEOUT"
)
[ -n "$MAX_FILES" ] && ARGS+=(--max_files "$MAX_FILES")
[ -n "$ENTITY_TYPES" ] && ARGS+=(--entity_types $ENTITY_TYPES)

echo "[$(date +%T)] running catalogue_ner.py ${ARGS[*]}"
python src/scripts/vllm_termpop/catalogue_ner.py "${ARGS[@]}"
RC=$?

echo "[$(date +%T)] extraction exit code: $RC"
echo "========================================================================"
echo "Coverage:"
python - "$RESULTS_DIR" <<'PYEOF'
import json, sys
from pathlib import Path
d = Path(sys.argv[1])
s = json.loads((d / "_catalogue_summary.json").read_text())
cov = s["coverage"]
print("  papers:      ", s["papers"])
print("  sections:    ", s["sections"])
print("  segments:    ", s["segments_total"], f"(full={s['segments_full_section']}, split={s['segments_split']})")
print("  failed segs: ", s["segments_failed"])
print("  char cover:  ", cov["char_coverage_pct"], "%")
print("  status:      ", cov["coverage_status"])
print("  records:     ", json.dumps(s["records_per_entity"]))
print("  evidence:    ", s["stats"]["evidence_located"], "located /",
      s["stats"]["evidence_not_located"], "unlocated")
PYEOF
echo "Outputs: $RESULTS_DIR"
exit $RC
