#!/bin/bash
#SBATCH --job-name=v32-type
#SBATCH --partition=mlgpu_short
#SBATCH --gres=gpu:a40:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=48G
#SBATCH --time=08:00:00
#SBATCH --output=outputs/logs/slurm/%x-%A_%a.out
# Layer 3.2.0-candidate relation typing with Qwen3.5-9B AWQ (local vLLM, one A40, thinking off). Submit from the repo root:
#   sbatch --export=ALL,TASK=check src/scripts/fixes_v32/v32.sbatch                     # constructed gold set
#   sbatch --export=ALL,TASK=smoke src/scripts/fixes_v32/v32.sbatch                     # gold set + 200 triples
#   sbatch --array=0-3 --export=ALL,TASK=all,NSHARDS=4 src/scripts/fixes_v32/v32.sbatch # full CDM scope
#   sbatch --array=0-3 --export=ALL,TASK=bench,NSHARDS=4 src/scripts/fixes_v32/v32.sbatch # DiMB-RE / MiDRED / MINERVA
# Reads CDM 3.0.3 (node-local copy, sha-checked) read-only. Outputs on Lustre, copied back at exit. Freeze exception
# PENDING lead approval (CHANGE_RECORD). Written with Claude Code (declare).
CDM_ROOT="${CDM_REPO_ROOT:-$(d="${SLURM_SUBMIT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"; while [ "$d" != / ] && [ ! -f "$d/.cdm_root" ]; do d="$(dirname "$d")"; done; echo "$d")}"
[ -f "$CDM_ROOT/.cdm_root" ] || { echo "ERROR: repo root not found" >&2; exit 1; }
set -euo pipefail
cd "$CDM_ROOT"
MODEL=${RT_MODEL:-cyankiwi/Qwen3.5-9B-AWQ-4bit}; REV=${RT_REV:-e4d2d39cede8c5d1716d824cd843e2889c648083}   # override only with a model cached in HF_HOME
SH=${SLURM_ARRAY_TASK_ID:-0}; NS=${NSHARDS:-1}
PORT=$(python3 -c "import socket;s=socket.socket();s.bind(('',0));print(s.getsockname()[1]);s.close()")
module use /opt/software/easybuild-AMD/modules/all
module load Python/3.12.3-GCCcore-13.3.0
module load CUDA/12.9.1
source /home/jkalra_hpc/venvs/vllm/bin/activate
export CUDA_HOME="$(dirname "$(dirname "$(command -v nvcc)")")"
export HF_HOME=/home/jkalra_hpc/llm/hf-cache HF_HUB_OFFLINE=1 PYTHONUNBUFFERED=1 VLLM_USE_FLASHINFER_SAMPLER=0
DB="$CDM_ROOT/releases/cdm_v3/3.0.3/microbiome_cdm_v3.db"
LOCALDB="${TMPDIR:-/tmp}/cdm303_v32_${SLURM_JOB_ID:-local}_${SH}.db"
cp "$DB" "$LOCALDB"
[[ "$(sha256sum "$LOCALDB" | cut -d' ' -f1)" == 5d23ba87d29ac7a6de831e66b35c0f42bc10312132cf20dd0191526b8b041e3e ]] || { echo "FATAL: CDM sha" >&2; exit 91; }
HOMEOUT=outputs/results/fixes_v32_2026-11-11
LOUT=/lustre/scratch/data/jkalra_hpc-deep_learning/cdm_fixes_v32_2026-11-11
SUB=${RUN_DIR:-$TASK}
mkdir -p "$LOUT/$SUB" "$LOUT/logs" "$HOMEOUT/$SUB"
for f in "$HOMEOUT/$SUB"/*.jsonl; do [ -f "$f" ] && [ ! -f "$LOUT/$SUB/$(basename "$f")" ] && timeout 120 cp "$f" "$LOUT/$SUB/" || true; done
copyback() { set +e; for f in "$LOUT/$SUB"/*; do [ -f "$f" ] && timeout 300 cp "$f" "$HOMEOUT/$SUB/"; done; true; }
LOG=$LOUT/logs/vllm-v32-${SLURM_JOB_ID:-0}_${SH}.log
vllm serve "$MODEL" --revision "$REV" --served-model-name "$MODEL" --port "$PORT" --gpu-memory-utilization 0.90 \
    --max-model-len 16384 --max-num-seqs ${RT_SEQS:-64} --enable-prefix-caching --structured-outputs-config '{"backend":"xgrammar","disable_any_whitespace":true}' > "$LOG" 2>&1 &
SRV=$!
trap 'set +e; copyback; kill $SRV 2>/dev/null; sleep 20; kill -9 $SRV 2>/dev/null; pkill -9 -P $SRV 2>/dev/null; rm -f "$LOCALDB"; true' EXIT
for _ in $(seq 1 180); do
    curl -sf "http://127.0.0.1:$PORT/v1/models" >/dev/null 2>&1 && break
    kill -0 $SRV 2>/dev/null || { echo "vLLM died"; tail -40 "$LOG"; exit 1; }
    sleep 5
done
curl -sf "http://127.0.0.1:$PORT/v1/models" | grep -q "$MODEL" || { echo "FATAL: server on $PORT is not serving $MODEL"; exit 95; }
T=src/scripts/fixes_v32/retype_triples_v32.py
case "${TASK:?}" in
  check) python $T --check --model "$MODEL" --port "$PORT" --db303 "$LOCALDB" --out "$LOUT/$SUB" ;;
  smoke) python $T --check --model "$MODEL" --port "$PORT" --db303 "$LOCALDB" --out "$LOUT/$SUB"
         python $T --model "$MODEL" --port "$PORT" --db303 "$LOCALDB" --out "$LOUT/$SUB" --sample 200 ;;
  all)   python $T --model "$MODEL" --port "$PORT" --db303 "$LOCALDB" --out "$LOUT/$SUB" --shard "$SH" --nshards "$NS" ;;
  bench) python src/scripts/fixes_v32/bench_llm_v32.py --model "$MODEL" --port "$PORT" --db303 "$LOCALDB" --outdir "$LOUT/$SUB" --shard "$SH" --nshards "$NS" ;;
esac
