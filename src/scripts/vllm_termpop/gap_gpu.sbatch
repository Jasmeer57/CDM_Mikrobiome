#!/bin/bash
#SBATCH --job-name=gap-gpu
#SBATCH --output=outputs/logs/gap/%x_%A_%a.out
#SBATCH --error=outputs/logs/gap/%x_%A_%a.err
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --time=08:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1

# ──────────────────────────────────────────────────────────────────────────────
# One GPU task of a gap stage (docs/gpu_gap_plan.md). Partition/GPU type, the
# array range and dependencies are given at submit time (submit_gap_chain.sh).
#
#   STAGE=G1 NSHARDS=8 sbatch -p mlgpu_medium --gres=gpu:a40:1 --array=0-7 gap_gpu.sbatch
#   KIND=embed  -> gap_embed.py (no vLLM)
#   KIND=link   -> link_catalogue.py --only_flagged --prompt_version v3 (G4)
#   KIND=judge  -> run_judge_client_full.py on G10 part $SLURM_ARRAY_TASK_ID
#   LIMIT_PAPERS=3 -> smoke test
#
# vLLM is tuned for throughput: continuous batching with up to 256 concurrent
# sequences, prefix caching (prompts send the shared passage first), chunked
# prefill, 92% GPU memory for the KV cache.
# ──────────────────────────────────────────────────────────────────────────────
CDM_ROOT="${CDM_REPO_ROOT:-$(d="${SLURM_SUBMIT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"; while [ "$d" != / ] && [ ! -f "$d/.cdm_root" ]; do d="$(dirname "$d")"; done; echo "$d")}"
[ -f "$CDM_ROOT/.cdm_root" ] || { echo "ERROR: repo root not found; set CDM_REPO_ROOT" >&2; exit 1; }
set -uo pipefail
cd "$CDM_ROOT"
mkdir -p outputs/logs/gap

KIND="${KIND:-gap}"
STAGE="${STAGE:-}"
NSHARDS="${NSHARDS:-1}"
SHARD="${SLURM_ARRAY_TASK_ID:-0}"
LIMIT_PAPERS="${LIMIT_PAPERS:-}"
PARALLEL="${PARALLEL:-128}"
PORT=$(python3 -c "import socket;s=socket.socket();s.bind(('',0));print(s.getsockname()[1]);s.close()")
S=src/scripts/vllm_termpop

case "$STAGE" in
    G1|G2|G5|G8|G4|G11) MKEY=qwen ;;
    G3B) MKEY=llama ;;
    *) MKEY=gemma ;;
esac
[ "$KIND" = link ] && MKEY=qwen
case "$MKEY" in
    qwen)  MODEL=Qwen/Qwen3.5-4B; export HF_HOME=/home/jkalra_hpc/llm/hf-cache; MAXLEN=32768 ;;
    gemma) MODEL=google/gemma-4-E4B-it-qat-w4a16-ct; export HF_HOME=/home/jkalra_hpc/.cache/huggingface; MAXLEN=16384 ;;
    llama) MODEL=hugging-quants/Meta-Llama-3.1-8B-Instruct-AWQ-INT4; export HF_HOME=/home/jkalra_hpc/llm/hf-cache; MAXLEN=16384 ;;
esac

echo "== gap task: KIND=$KIND STAGE=$STAGE shard=$SHARD/$NSHARDS model=$MODEL node=${SLURM_NODELIST:-local} $(date)"
module use /opt/software/easybuild-AMD/modules/all
module load Python/3.12.3-GCCcore-13.3.0
module load CUDA/12.9.1
source /home/jkalra_hpc/venvs/vllm/bin/activate
export CUDA_HOME="$(dirname "$(dirname "$(command -v nvcc)")")"
export PYTHONPATH="$CDM_ROOT/src:${PYTHONPATH:-}"
export PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8 TOKENIZERS_PARALLELISM=false
export HF_HUB_OFFLINE=1
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader || true

if [ "$KIND" = embed ]; then
    exec python $S/gap_embed.py
fi

SRV_LOG="outputs/logs/gap/vllm_${STAGE:-$KIND}_${SLURM_JOB_ID:-0}_${SHARD}.log"
vllm serve "$MODEL" --port "$PORT" \
    --gpu-memory-utilization 0.92 --max-model-len "$MAXLEN" \
    --max-num-seqs 256 --max-num-batched-tokens 16384 \
    --enable-prefix-caching --enable-chunked-prefill \
    --trust-remote-code \
    > "$SRV_LOG" 2>&1 &
SRV=$!
trap 'kill $SRV 2>/dev/null; wait $SRV 2>/dev/null' EXIT
for _ in $(seq 1 180); do
    curl -sf "http://127.0.0.1:$PORT/v1/models" >/dev/null 2>&1 && break
    kill -0 $SRV 2>/dev/null || { echo "vLLM died"; tail -40 "$SRV_LOG"; exit 1; }
    sleep 5
done
curl -sf "http://127.0.0.1:$PORT/v1/models" >/dev/null || { echo "vLLM not ready"; tail -40 "$SRV_LOG"; exit 1; }
echo "[$(date +%T)] server ready on :$PORT"

case "$KIND" in
    gap)
        ARGS=(run --stage "$STAGE" --shard "$SHARD" --nshards "$NSHARDS" --host "http://127.0.0.1:$PORT" --parallel "$PARALLEL")
        [ -n "$LIMIT_PAPERS" ] && ARGS+=(--limit_papers "$LIMIT_PAPERS")
        python $S/gap_stages.py "${ARGS[@]}" ;;
    link)
        python $S/link_catalogue.py --input_dir outputs/results/gap_runs/G3/catalogue \
            --output_dir outputs/results/gap_runs/G4/catalogue --only_flagged --prompt_version v3 \
            --host "http://127.0.0.1:$PORT" --parallel "$PARALLEL" ;;
    judge)
        P=src/scripts/llm_judge_a40
        python $P/run_judge_client_full.py \
            --input outputs/results/gap_runs/G10/input_full_C1.part$SHARD.jsonl \
            --output outputs/results/gap_runs/G10/C1_part${SHARD}_verdicts.jsonl \
            --cache outputs/results/gap_runs/G10/_cache_part$SHARD.json \
            --model "$MODEL" --port "$PORT" --parallel "$PARALLEL" --artifact C1 \
            --prompt $P/prompts/judge_C1.txt --progress-every 1000 ;;
esac
RC=$?
echo "[$(date +%T)] exit $RC"
exit $RC
