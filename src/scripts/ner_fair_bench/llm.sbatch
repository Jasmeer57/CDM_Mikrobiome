#!/bin/bash
#SBATCH --job-name=nerbench-llm
#SBATCH --output=outputs/logs/ner_bench/%x_%A_%a.out
#SBATCH --error=outputs/logs/ner_bench/%x_%A_%a.err
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --time=06:00:00
# BENCH=corpus_bench runs the 453-paper corpus instead of BC5CDR/BioRED.
# One LLM per array task on one GPU (vLLM), zero-shot and 3-shot, both datasets (fairbench.py).
#   sbatch -p mlgpu_medium --gres=gpu:a40:1 --array=0-5 llm.sbatch
CDM_ROOT="${CDM_REPO_ROOT:-$(d="${SLURM_SUBMIT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"; while [ "$d" != / ] && [ ! -f "$d/.cdm_root" ]; do d="$(dirname "$d")"; done; echo "$d")}"
[ -f "$CDM_ROOT/.cdm_root" ] || { echo "ERROR: repo root not found" >&2; exit 1; }
set -uo pipefail
cd "$CDM_ROOT"
KEYS=(qwen gemma llama mistral phi deepseek)
K=${KEYS[${SLURM_ARRAY_TASK_ID:-0}]}
EXTRA=()
case "$K" in
    qwen)     MODEL=Qwen/Qwen3.5-4B; HF=/home/jkalra_hpc/llm/hf-cache ;;
    gemma)    MODEL=google/gemma-4-E4B-it-qat-w4a16-ct; HF=/home/jkalra_hpc/.cache/huggingface ;;
    llama)    MODEL=hugging-quants/Meta-Llama-3.1-8B-Instruct-AWQ-INT4; HF=/home/jkalra_hpc/llm/hf-cache ;;
    mistral)  MODEL=TechxGenus/Mistral-7B-Instruct-v0.3-AWQ; HF=/home/jkalra_hpc/llm/hf-cache ;;
    phi)      MODEL=thesven/Phi-3.5-mini-instruct-awq; HF=/home/jkalra_hpc/llm/hf-cache ;;
    deepseek) MODEL=casperhansen/deepseek-r1-distill-qwen-7b-awq; HF=/home/jkalra_hpc/llm/hf-cache
              EXTRA=(--quantization awq_marlin --reasoning-parser deepseek_r1) ;;
esac
export HF_HOME=$HF HF_HUB_OFFLINE=1 PYTHONUNBUFFERED=1
module use /opt/software/easybuild-AMD/modules/all
module load Python/3.12.3-GCCcore-13.3.0
module load CUDA/12.9.1
source /home/jkalra_hpc/venvs/vllm/bin/activate
export CUDA_HOME="$(dirname "$(dirname "$(command -v nvcc)")")"
PORT=$(python3 -c "import socket;s=socket.socket();s.bind(('',0));print(s.getsockname()[1]);s.close()")
echo "== $K $MODEL on ${SLURM_NODELIST:-local} port $PORT $(date)"
nvidia-smi --query-gpu=name --format=csv,noheader
LOG=outputs/logs/ner_bench/vllm_${K}_${SLURM_JOB_ID:-0}.log
vllm serve "$MODEL" --port "$PORT" --gpu-memory-utilization 0.90 --max-model-len 16384 \
    --max-num-seqs 128 --enable-prefix-caching --trust-remote-code "${EXTRA[@]}" > "$LOG" 2>&1 &
SRV=$!
trap 'kill $SRV 2>/dev/null; wait $SRV 2>/dev/null' EXIT
for _ in $(seq 1 180); do
    curl -sf "http://127.0.0.1:$PORT/v1/models" >/dev/null 2>&1 && break
    kill -0 $SRV 2>/dev/null || { echo "vLLM died"; tail -40 "$LOG"; exit 1; }
    sleep 5
done
RC=0
for MODE in zs fs; do
    python src/scripts/ner_fair_bench/${BENCH:-fairbench}.py llm --model "$K" --mode "$MODE" \
        --host "http://127.0.0.1:$PORT" --parallel 64 || RC=1
done
echo "== done rc=$RC $(date)"
exit $RC
