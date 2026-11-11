#!/bin/bash
#SBATCH --job-name=fields-v32
#SBATCH --partition=mlgpu_short
#SBATCH --gres=gpu:a40:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=48G
#SBATCH --time=04:00:00
#SBATCH --output=outputs/logs/slurm/%x-%A_%a.out
# CDM 3.2.0-candidate catalogue-field fix (DNA extraction method, sequencing platform). One A40, local vLLM. From repo root:
#   sbatch --export=ALL,TASK=extract,LIMIT=20 src/scripts/fixes_v32/fields_v32.sbatch          # smoke
#   sbatch --export=ALL,TASK=extract src/scripts/fixes_v32/fields_v32.sbatch                   # Qwen3.5-9B extractor
#   sbatch --array=0-2 --export=ALL,TASK=judge src/scripts/fixes_v32/fields_v32.sbatch          # judges 0=qwen9 1=llama 2=mistral
# Part files go to Lustre scratch (home is NFS); collected into outputs/results/catalogue_fields_v32_2026-11-11 after.
# Freeze exception (new model run) PENDING project-lead approval; logged in CHANGE_RECORD.md.
CDM_ROOT="${CDM_REPO_ROOT:-$(d="${SLURM_SUBMIT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"; while [ "$d" != / ] && [ ! -f "$d/.cdm_root" ]; do d="$(dirname "$d")"; done; echo "$d")}"
[ -f "$CDM_ROOT/.cdm_root" ] || { echo "ERROR: repo root not found" >&2; exit 1; }
set -uo pipefail
cd "$CDM_ROOT"
LOUT=${V32_LUSTRE_OUT:-/lustre/scratch/data/jkalra_hpc-deep_learning/catalogue_fields_v32_2026-11-11}
mkdir -p "$LOUT" outputs/logs/slurm
EXTRA=""
JUDGES=(qwen9 llama mistral)
if [ "${TASK:?}" = judge ]; then JUDGE=${JUDGE:-${JUDGES[${SLURM_ARRAY_TASK_ID:-0}]}}; else JUDGE=qwen9; fi
case "$JUDGE" in
    qwen9)   MODEL=cyankiwi/Qwen3.5-9B-AWQ-4bit; EXTRA="--revision e4d2d39cede8c5d1716d824cd843e2889c648083"; MAXLEN=16384 ;;
    llama)   MODEL=hugging-quants/Meta-Llama-3.1-8B-Instruct-AWQ-INT4; MAXLEN=8192 ;;
    mistral) MODEL=TechxGenus/Mistral-7B-Instruct-v0.3-AWQ; MAXLEN=8192 ;;
esac
export HF_HOME=/home/jkalra_hpc/llm/hf-cache HF_HUB_OFFLINE=1 PYTHONUNBUFFERED=1 VLLM_USE_FLASHINFER_SAMPLER=0
module use /opt/software/easybuild-AMD/modules/all
module load Python/3.12.3-GCCcore-13.3.0
module load CUDA/12.9.1
source /home/jkalra_hpc/venvs/vllm/bin/activate
export CUDA_HOME="$(dirname "$(dirname "$(command -v nvcc)")")"
PORT=$(python3 -c "import socket;s=socket.socket();s.bind(('',0));print(s.getsockname()[1]);s.close()")   # free port
LOG=$LOUT/vllm_${TASK}_${JUDGE}_${SLURM_JOB_ID:-0}.log
vllm serve "$MODEL" $EXTRA --served-model-name "$MODEL" --port "$PORT" --gpu-memory-utilization 0.90 \
    --max-model-len "$MAXLEN" --max-num-seqs 64 --enable-prefix-caching --structured-outputs-config '{"backend":"xgrammar","disable_any_whitespace":true}' > "$LOG" 2>&1 &
SRV=$!
trap 'set +e; kill $SRV 2>/dev/null; sleep 20; kill -9 $SRV 2>/dev/null; pkill -9 -P $SRV 2>/dev/null; true' EXIT
for _ in $(seq 1 180); do
    curl -sf "http://127.0.0.1:$PORT/v1/models" >/dev/null 2>&1 && break
    kill -0 $SRV 2>/dev/null || { echo "vLLM died"; tail -40 "$LOG"; exit 1; }
    sleep 5
done
curl -sf "http://127.0.0.1:$PORT/v1/models" | grep -q "$MODEL" || { echo "FATAL: server on $PORT is not serving $MODEL"; exit 95; }
case "$TASK" in
  extract) python src/scripts/fixes_v32/llm_extract.py --host "http://127.0.0.1:$PORT" --out "$LOUT/${RUN_DIR:-extract}" \
               --limit "${LIMIT:-0}" --parallel 32 ;;
  judge)   python src/scripts/fixes_v32/judge_fields.py judge --model "$JUDGE" --host "http://127.0.0.1:$PORT" \
               --out "$LOUT/${RUN_DIR:-judge}" --parallel 48 ;;
esac
RC=$?
echo "task exit $RC"
exit $RC
