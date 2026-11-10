#!/bin/bash
#SBATCH --job-name=cat-trunc-probe
#SBATCH --partition=mlgpu_short
#SBATCH --gres=gpu:a40:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=02:00:00
#SBATCH --output=outputs/logs/catalogue_trunc_probe_%j.out
#SBATCH --error=outputs/logs/catalogue_trunc_probe_%j.err
# ──────────────────────────────────────────────────────────────────────────────
# Read-only diagnostic for the 32 residual catalogue truncations (job 28663289).
#
# Pass 1 cut 127 -> 32. Every residual failure reports the SAME truncation
# ValueError and NONE exhausted the 32-call budget, so the `min_chars=600` floor
# is the binding limit: a 2,092-char leaf halves into ~1,046-char pieces that
# cannot split again. But successful repairs emit up to 115 findings from 19,961
# chars, so a ~1,000-char leaf overflowing 4,096 output tokens is anomalous.
#
# This job distinguishes the two candidate causes before pass 2 commits to a
# policy:
#   (a) dense enumeration (taxon lists)  -> lower the floor, records faithful
#   (b) repetition loop                  -> lower the floor, but the records are
#                                           worthless and must not be trusted
#
# It NEVER writes the cache: probe_call() returns diagnostics instead of
# recording, and the only output is `_truncation_probe.json`.
#
#   sbatch src/scripts/vllm_termpop/diagnose_truncation_a40.sbatch
#   LADDER=1,2,4,8,16 sbatch ...    # widen the halving ladder
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
PARALLEL="${PARALLEL:-8}"
LADDER="${LADDER:-1,2,4,8}"

echo "========================================================================"
echo "Catalogue truncation probe — 32 residual leaves — Qwen3.5-4B on A40"
echo "  Job ID:      ${SLURM_JOB_ID:-<none>}"
echo "  Node:        ${SLURM_NODELIST:-<none>}"
echo "  Model:       $MODEL"
echo "  Output dir:  $OUT_DIR"
echo "  Ladder:      $LADDER   (divisors of the leaf, 1 = whole leaf)"
echo "  Writes:      $OUT_DIR/_truncation_probe.json  (cache untouched)"
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
    > "$OUT_DIR/vllm_server_probe_${SLURM_JOB_ID:-local}.log" 2>&1 &
SERVER_PID=$!

ready=""
for _ in $(seq 1 180); do
    if curl -sf "http://127.0.0.1:${PORT}/v1/models" > /dev/null 2>&1; then
        ready=1; break
    fi
    if ! kill -0 "$SERVER_PID" 2>/dev/null; then
        echo "vLLM server died during startup — see the server log"
        tail -40 "$OUT_DIR/vllm_server_probe_${SLURM_JOB_ID:-local}.log"
        exit 1
    fi
    sleep 5
done

if [ -z "$ready" ]; then
    echo "vLLM server not ready in 15 min — see server log"
    tail -40 "$OUT_DIR/vllm_server_probe_${SLURM_JOB_ID:-local}.log"
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

echo "[$(date +%T)] running diagnose_catalogue_truncation.py ..."
python outputs/scratch/diagnose_catalogue_truncation.py \
    --model "$MODEL" \
    --host "http://127.0.0.1:${PORT}" \
    --output_dir "$OUT_DIR" \
    --parallel "$PARALLEL" \
    --ladder "$LADDER"
RC=$?

echo "[$(date +%T)] probe exit code: $RC"
echo "========================================================================"
python - "$OUT_DIR" <<'PYEOF'
import json, sys
from pathlib import Path
p = Path(sys.argv[1]) / "_truncation_probe.json"
if not p.exists():
    print("_truncation_probe.json: MISSING")
else:
    s = json.loads(p.read_text())
    print("\n== _truncation_probe.json ==")
    for k in ("targets", "resolved_within_ladder", "still_failing"):
        print("  %-24s %s" % (k + ":", s.get(k)))
    print("  %-24s %s" % ("min_divisor_needed:",
                          json.dumps(s.get("min_divisor_needed"))))
    c = s.get("classification") or {}
    print("  %-24s %d keys" % ("repetition_loop:", len(c.get("repetition_loop") or [])))
    print("  %-24s %d keys" % ("dense_enumeration:", len(c.get("dense_enumeration") or [])))
    print("\n  per-target finest outcome:")
    for r in s.get("rows") or []:
        last = r["ladder"][-1]
        print("    %-16s %-10s %6d ch  -> %-10s div=%s  %s"
              % (r["paper"], r["section"], r["leaf_chars"], last["status"],
                 last["divisor"], last.get("finish_reason") or ""))
PYEOF
echo "Output: $OUT_DIR/_truncation_probe.json"
exit $RC
