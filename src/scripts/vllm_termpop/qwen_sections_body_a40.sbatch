#!/bin/bash
#SBATCH --job-name=llm-ner-body
#SBATCH --output=outputs/logs/llm_ner_body_%j.out
#SBATCH --error=outputs/logs/llm_ner_body_%j.err
#SBATCH --partition=mlgpu_short
#SBATCH --gres=gpu:a40:1
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --time=08:00:00

# ──────────────────────────────────────────────────────────────────────────────
# LLM section-level NER at FULL 453-paper scope, matching the CPU ensemble's
# section universe exactly.
#
# WHY: the historical LLM section run (releases/zenodo_v1/qwen_sections_ner) used the
# notebook Cell-7c skip rule, which drops Introduction/Background as well as
# backmatter. The CPU ensemble (releases/zenodo_v1/ner_453_sections) skips backmatter
# ONLY. So the LLM side covered 2,601 of the CPU's 2,817 body units and emitted
# rows for 1,926 — a 438-unit / 2-paper shortfall that is a *design* gap, not a
# finding. `--section_filter body` reproduces the CPU body universe exactly
# (verified: 2,817 units, identical unit-id set), so the comparison is
# apples-to-apples instead of silently restricted to the intersection.
#
# Also upgrades transport from the Ollama run to vLLM, and from chunked to
# full-section-first extraction (whole section per request when it fits).
#
# Checkpointed/resumable: re-submit the same job; it reuses
# $RESULTS_DIR/_vllm_sections_cache.json and only runs missing segments.
#
#   sbatch src/scripts/vllm_termpop/qwen_sections_body_a40.sbatch
#   MAX_FILES=5 sbatch ...         # smoke test
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
SECTION_FILTER="${SECTION_FILTER:-body}"
FULL_SECTION_MAX_CHARS="${FULL_SECTION_MAX_CHARS:-20000}"
# Stable default (not job-id based) so the follow-up comparison job can find it
# and so a resubmit resumes the same cache.
RESULTS_DIR="${RESULTS_DIR:-results/llm_ner_body}"

echo "========================================================================"
echo "LLM section NER — FULL 453-paper scope (Qwen3.5-4B via vLLM on A40)"
echo "  Job ID:      $SLURM_JOB_ID"
echo "  Node:        $SLURM_NODELIST"
echo "  Model:       $MODEL"
echo "  Filter:      $SECTION_FILTER  (body = CPU ensemble universe)"
echo "  Parallel:    $PARALLEL"
echo "  Max files:   ${MAX_FILES:-<all>}"
echo "  Full-sec ≤:  $FULL_SECTION_MAX_CHARS chars"
echo "  Output:      $RESULTS_DIR"
echo "  Started:     $(date)"
echo "========================================================================"

# ── Modules (A40 / CUDA) — same env as catalogue_ner_a40.sbatch ──────────────
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
    echo "vLLM server not ready in 15 min — see $RESULTS_DIR/vllm_server.log"
    tail -40 "$RESULTS_DIR/vllm_server.log"
    kill "$SERVER_PID" 2>/dev/null || true
    exit 1
fi
echo "[$(date +%T)] server ready: $(curl -s "http://127.0.0.1:${PORT}/v1/models" | head -c 160)"

cleanup() {
    echo "[$(date +%T)] stopping vLLM server (pid $SERVER_PID)"
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
}
trap cleanup EXIT

# ── Run the full-scope section NER ───────────────────────────────────────────
ARGS=(
    --model "$MODEL"
    --host "http://127.0.0.1:${PORT}"
    --output_dir "$RESULTS_DIR"
    --parallel "$PARALLEL"
    --section_filter "$SECTION_FILTER"
    --full_section_max_chars "$FULL_SECTION_MAX_CHARS"
)
[ -n "$MAX_FILES" ] && ARGS+=(--max_files "$MAX_FILES")

echo "[$(date +%T)] running qwen_sections_vllm.py ${ARGS[*]}"
python src/scripts/vllm_termpop/qwen_sections_vllm.py "${ARGS[@]}"
RC=$?

echo "[$(date +%T)] extraction exit code: $RC"
echo "========================================================================"
python - "$RESULTS_DIR" <<'PYEOF'
import csv, json, sys
from pathlib import Path
d = Path(sys.argv[1])
s = json.loads((d / "_vllm_sections_summary.json").read_text())
c = s["coverage"]
print("  section_filter: ", s.get("section_filter"))
print("  papers:         ", len({r["paper"] for r in csv.DictReader((d / "_coverage.csv").open())}))
print("  sections:       ", s["sections"])
print("  segments:       ", s["segments_total"],
      f"(full={s['coverage']['segments_full_section']}, split={c['segments_split']})")
print("  failed segments:", c["segments_failed"])
print("  sections complete/empty/incomplete: %d/%d/%d" % (
    c["sections_complete"], c["sections_empty"], c["sections_incomplete"]))
print("  char coverage:  ", c["char_coverage_pct"], "%")
print("  coverage status:", c["coverage_status"])
print("  rows:           ", s["rows"])
PYEOF
echo "Outputs: $RESULTS_DIR"
exit $RC
