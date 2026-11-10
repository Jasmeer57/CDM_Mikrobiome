#!/bin/bash
#SBATCH --job-name=ds-review
#SBATCH --output=outputs/logs/gap/%x_%A_%a.out
#SBATCH --error=outputs/logs/gap/%x_%A_%a.err
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --time=08:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
# DeepSeek-R1-Distill-Qwen-7B (unsloth bnb 4-bit) review shard = $SLURM_ARRAY_TASK_ID of $NSHARDS.
# Partition/GPU given at submit. LIMIT=N -> smoke test. Writes only outputs/results/deepseek_review/.
CDM_ROOT="${CDM_REPO_ROOT:-$(d="${SLURM_SUBMIT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"; while [ "$d" != / ] && [ ! -f "$d/.cdm_root" ]; do d="$(dirname "$d")"; done; echo "$d")}"
[ -f "$CDM_ROOT/.cdm_root" ] || { echo "ERROR: repo root not found" >&2; exit 1; }
set -uo pipefail
cd "$CDM_ROOT"; mkdir -p outputs/logs/gap
SHARD="${SLURM_ARRAY_TASK_ID:-0}"; NSHARDS="${NSHARDS:-1}"; LIMIT="${LIMIT:-0}"
MODEL=casperhansen/deepseek-r1-distill-qwen-7b-awq  # 4-bit AWQ; vLLM 0.32 dropped bitsandbytes (unsloth bnb build)
module use /opt/software/easybuild-AMD/modules/all
module load Python/3.12.3-GCCcore-13.3.0
module load CUDA/12.9.1
source /home/jkalra_hpc/venvs/vllm/bin/activate
export CUDA_HOME="$(dirname "$(dirname "$(command -v nvcc)")")"
export HF_HOME=/home/jkalra_hpc/llm/hf-cache HF_HUB_OFFLINE=1
export PYTHONPATH="$CDM_ROOT/src:${PYTHONPATH:-}" PYTHONUNBUFFERED=1 TOKENIZERS_PARALLELISM=false
PORT=$(python3 -c "import socket;s=socket.socket();s.bind(('',0));print(s.getsockname()[1]);s.close()")
echo "== ds-review shard $SHARD/$NSHARDS on ${SLURM_NODELIST:-local} $(date)"; nvidia-smi --query-gpu=name --format=csv,noheader
LOG=outputs/logs/gap/vllm_ds_${SLURM_JOB_ID:-0}_${SHARD}.log
vllm serve "$MODEL" --port "$PORT" --quantization awq_marlin \
    --reasoning-parser deepseek_r1 --max-model-len 16384 --gpu-memory-utilization 0.92 \
    --max-num-seqs 256 --max-num-batched-tokens 16384 --enable-prefix-caching > "$LOG" 2>&1 &
SRV=$!; trap 'kill $SRV 2>/dev/null; wait $SRV 2>/dev/null' EXIT
for _ in $(seq 1 180); do curl -sf "http://127.0.0.1:$PORT/v1/models" >/dev/null 2>&1 && break
    kill -0 $SRV 2>/dev/null || { echo "vLLM died"; tail -40 "$LOG"; exit 1; }; sleep 5; done
curl -sf "http://127.0.0.1:$PORT/v1/models" >/dev/null || { echo "vLLM not ready"; tail -40 "$LOG"; exit 1; }
echo "[$(date +%T)] server ready"
python src/scripts/vllm_termpop/deepseek_review.py run --shard "$SHARD" --nshards "$NSHARDS" \
    --host "http://127.0.0.1:$PORT" --parallel "${PARALLEL:-128}" --limit "$LIMIT"
