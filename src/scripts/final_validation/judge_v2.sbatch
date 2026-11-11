#!/bin/bash
#SBATCH --job-name=judge-v2
#SBATCH --partition=mlgpu_short
#SBATCH --gres=gpu:a40:1
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --time=08:00:00
#SBATCH --output=outputs/logs/final_validation/%x_%A_%a.out
# Catalogue judge rubric v2 (evidence_judge_v2.py), one shard per array task, one A40 each. Submit from the repo root:
#   sbatch --array=0 --export=ALL,JUDGE=qwen9,SPLIT=dev,NSHARDS=1 src/scripts/final_validation/judge_v2.sbatch
#   sbatch --array=0-2 --export=ALL,JUDGE=llama,SPLIT=test,NSHARDS=3 src/scripts/final_validation/judge_v2.sbatch
# Freeze exception (new model run) PENDING project-lead approval; logged in CHANGE_RECORD.md.
CDM_ROOT="${CDM_REPO_ROOT:-$(d="${SLURM_SUBMIT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"; while [ "$d" != / ] && [ ! -f "$d/.cdm_root" ]; do d="$(dirname "$d")"; done; echo "$d")}"
[ -f "$CDM_ROOT/.cdm_root" ] || { echo "ERROR: repo root not found" >&2; exit 1; }
set -uo pipefail
cd "$CDM_ROOT"
EXTRA=""
case "${JUDGE:?}" in
    qwen9)   MODEL=cyankiwi/Qwen3.5-9B-AWQ-4bit; EXTRA="--revision e4d2d39cede8c5d1716d824cd843e2889c648083"; MAXLEN=16384 ;;
    llama)   MODEL=hugging-quants/Meta-Llama-3.1-8B-Instruct-AWQ-INT4; MAXLEN=8192 ;;
    mistral) MODEL=TechxGenus/Mistral-7B-Instruct-v0.3-AWQ; MAXLEN=8192 ;;
esac
export HF_HOME=/home/jkalra_hpc/llm/hf-cache HF_HUB_OFFLINE=1 PYTHONUNBUFFERED=1
module use /opt/software/easybuild-AMD/modules/all
module load Python/3.12.3-GCCcore-13.3.0
module load CUDA/12.9.1
source /home/jkalra_hpc/venvs/vllm/bin/activate
export CUDA_HOME="$(dirname "$(dirname "$(command -v nvcc)")")"
PORT=$(python3 -c "import socket;s=socket.socket();s.bind(('',0));print(s.getsockname()[1]);s.close()")   # free port: fixed ports collided on shared nodes (2026-11-10)
LOG=outputs/logs/final_validation/vllm_v2_${JUDGE}_${SLURM_JOB_ID:-0}.log
vllm serve "$MODEL" $EXTRA --served-model-name "$MODEL" --port "$PORT" --gpu-memory-utilization 0.90 \
    --max-model-len "$MAXLEN" --max-num-seqs 64 --enable-prefix-caching --structured-outputs-config '{"backend":"xgrammar","disable_any_whitespace":true}' > "$LOG" 2>&1 &
SRV=$!
trap 'set +e; kill $SRV 2>/dev/null; sleep 20; kill -9 $SRV 2>/dev/null; pkill -9 -P $SRV 2>/dev/null; true' EXIT   # set +e: under set -e a failed kill aborted the trap with exit 1 (2026-11-10)
for _ in $(seq 1 180); do
    curl -sf "http://127.0.0.1:$PORT/v1/models" >/dev/null 2>&1 && break
    kill -0 $SRV 2>/dev/null || { echo "vLLM died"; tail -40 "$LOG"; exit 1; }
    sleep 5
done
curl -sf "http://127.0.0.1:$PORT/v1/models" | grep -q "$MODEL" || { echo "FATAL: server on $PORT is not serving $MODEL"; exit 95; }
python src/scripts/final_validation/evidence_judge_v2.py judge --model "$JUDGE" --host "http://127.0.0.1:$PORT" \
    --split "${SPLIT:-dev}" --shard "${SLURM_ARRAY_TASK_ID:-0}" --nshards "${NSHARDS:-1}" --parallel 48 --seed "${SEED:-0}"
