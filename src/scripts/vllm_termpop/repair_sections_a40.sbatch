#!/bin/bash
#SBATCH --job-name=llm-ner-repair
#SBATCH --output=outputs/logs/llm_ner_repair_%j.out
#SBATCH --error=outputs/logs/llm_ner_repair_%j.err
#SBATCH --partition=mlgpu_short
#SBATCH --gres=gpu:a40:1
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --time=04:00:00

# ──────────────────────────────────────────────────────────────────────────────
# TARGETED repair of the residual FAILED vLLM NER segments for the `body` run.
#
# The `llm-ner-body` run (qwen_sections_vllm.py) exhausted its retry ladder and
# left 15 errored cache keys out of 3,986. Re-running the whole corpus is NOT
# the remedy: the failures truncate at ~9.0-13.5K output chars regardless of
# input length, and `split:` retries fail at the identical char offset. So this
# job re-attempts ONLY those 15 segments (mapped back to their text by rebuilding
# the deterministic segment plan) with an escalating token budget, a corrected
# finish_reason check, truncation salvage, and deeper/finer splitting.
#
# Writes results back under the ORIGINAL cache keys, then `--assemble` regenerates
# the CSV + summary from the full cache.
#
#   sbatch src/scripts/vllm_termpop/repair_sections_a40.sbatch
#   MAX_FILES=3 sbatch ...        # (honoured via the shared segment plan)
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
PARALLEL="${PARALLEL:-16}"
SECTION_FILTER="${SECTION_FILTER:-body}"
RESULTS_DIR="${RESULTS_DIR:-results/llm_ner_body}"

echo "========================================================================"
echo "LLM section NER — TARGETED repair of residual failures (Qwen3.5-4B via vLLM)"
echo "  Job ID:      $SLURM_JOB_ID"
echo "  Node:        $SLURM_NODELIST"
echo "  Model:       $MODEL"
echo "  Filter:      $SECTION_FILTER"
echo "  Output:      $RESULTS_DIR"
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

# ── Serve the model ──────────────────────────────────────────────────────────
echo "[$(date +%T)] starting vLLM server ..."
vllm serve "$MODEL" \
    --port "$PORT" \
    --gpu-memory-utilization 0.90 \
    --max-model-len 32768 \
    > "$RESULTS_DIR/vllm_server_repair.log" 2>&1 &
SERVER_PID=$!

ready=""
for _ in $(seq 1 180); do
    if curl -sf "http://127.0.0.1:${PORT}/v1/models" > /dev/null 2>&1; then
        ready=1; break
    fi
    if ! kill -0 "$SERVER_PID" 2>/dev/null; then
        echo "vLLM server died during startup — see $RESULTS_DIR/vllm_server_repair.log"
        tail -40 "$RESULTS_DIR/vllm_server_repair.log"
        exit 1
    fi
    sleep 5
done

if [ -z "$ready" ]; then
    echo "vLLM server not ready in 15 min — see $RESULTS_DIR/vllm_server_repair.log"
    tail -40 "$RESULTS_DIR/vllm_server_repair.log"
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

# ── Repair only the errored segments, then assemble ──────────────────────────
echo "[$(date +%T)] running repair_sections_cache.py (targets only errored keys)"
python src/scripts/vllm_termpop/repair_sections_cache.py \
    --model "$MODEL" \
    --host "http://127.0.0.1:${PORT}" \
    --output_dir "$RESULTS_DIR" \
    --section_filter "$SECTION_FILTER" \
    --parallel "$PARALLEL" \
    --assemble
RC=$?

echo "[$(date +%T)] repair exit code: $RC"
echo "========================================================================"
python - "$RESULTS_DIR" <<'PYEOF'
import json, sys
from pathlib import Path
d = Path(sys.argv[1])
rp = d / "_repair_report.json"
if rp.exists():
    r = json.loads(rp.read_text())
    print("  repair report:")
    for k in ("targets", "repaired_complete", "repaired_partial", "still_failed"):
        if k in r:
            print(f"    {k}: {r[k]}")
    print("    status:", r.get("status"))
else:
    print("  (no _repair_report.json)")
s = d / "_vllm_sections_summary.json"
if s.exists():
    su = json.loads(s.read_text())
    c = su["coverage"]
    print("  sections:", su["sections"], "| segments:", su["segments_total"])
    print("  failed segments:", c["segments_failed"], "| char coverage:", c["char_coverage_pct"], "%")
    print("  coverage status:", c["coverage_status"], "| rows:", su["rows"])
print("  csv present:", (d / "vllm_sections_ner.csv").exists())
PYEOF
echo "Outputs: $RESULTS_DIR"
exit $RC
