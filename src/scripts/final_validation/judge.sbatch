#!/bin/bash
#SBATCH --job-name=evid-judge
#SBATCH --output=outputs/logs/final_validation/%x_%A_%a.out
#SBATCH --error=outputs/logs/final_validation/%x_%A_%a.err
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --time=12:00:00
# Model-based evidence assessment of the catalogue (evidence_judge.py), one shard per array task.
# Constrained re-run (2026-11-09): JUDGE_SCRIPT=src/scripts/final_validation/evidence_judge_constrained.py JUDGE_EXTRA="--constrained --out DIR"
#   sbatch -p mlgpu_medium --gres=gpu:a40:1 --array=0-2 --export=ALL,JUDGE=llama,NSHARDS=3 judge.sbatch
CDM_ROOT="${CDM_REPO_ROOT:-$(d="${SLURM_SUBMIT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"; while [ "$d" != / ] && [ ! -f "$d/.cdm_root" ]; do d="$(dirname "$d")"; done; echo "$d")}"
[ -f "$CDM_ROOT/.cdm_root" ] || { echo "ERROR: repo root not found" >&2; exit 1; }
set -uo pipefail
cd "$CDM_ROOT"
case "${JUDGE:?}" in
    llama)   MODEL=hugging-quants/Meta-Llama-3.1-8B-Instruct-AWQ-INT4 ;;
    mistral) MODEL=TechxGenus/Mistral-7B-Instruct-v0.3-AWQ ;;
esac
export HF_HOME=/home/jkalra_hpc/llm/hf-cache HF_HUB_OFFLINE=1 PYTHONUNBUFFERED=1
module use /opt/software/easybuild-AMD/modules/all
module load Python/3.12.3-GCCcore-13.3.0
module load CUDA/12.9.1
source /home/jkalra_hpc/venvs/vllm/bin/activate
export CUDA_HOME="$(dirname "$(dirname "$(command -v nvcc)")")"
PORT=$(python3 -c "import socket;s=socket.socket();s.bind(('',0));print(s.getsockname()[1]);s.close()")
LOG=outputs/logs/final_validation/vllm_${JUDGE}_${SLURM_JOB_ID:-0}.log
vllm serve "$MODEL" --port "$PORT" --gpu-memory-utilization 0.90 --max-model-len 8192 \
    --max-num-seqs 128 --enable-prefix-caching > "$LOG" 2>&1 &
SRV=$!
trap 'kill $SRV 2>/dev/null; wait $SRV 2>/dev/null' EXIT
for _ in $(seq 1 180); do
    curl -sf "http://127.0.0.1:$PORT/v1/models" >/dev/null 2>&1 && break
    kill -0 $SRV 2>/dev/null || { echo "vLLM died"; tail -40 "$LOG"; exit 1; }
    sleep 5
done
python "${JUDGE_SCRIPT:-src/scripts/final_validation/evidence_judge.py}" judge --model "$JUDGE" --host "http://127.0.0.1:$PORT" \
    --shard "${SLURM_ARRAY_TASK_ID:-0}" --nshards "${NSHARDS:-1}" --parallel 64 ${JUDGE_EXTRA:-}
