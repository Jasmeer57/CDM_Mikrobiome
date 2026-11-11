#!/bin/bash
#SBATCH --job-name=cmp-llm
#SBATCH --partition=mlgpu_short
#SBATCH --gres=gpu:a40:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=48G
#SBATCH --time=08:00:00
#SBATCH --output=outputs/logs/slurm/%x-%A_%a.out
# Competitor comparisons (2026-11-11): Qwen3.5-9B AWQ on a local vLLM server (one A40), thinking off.
# Submit from the repo root:
#   sbatch --export=ALL,TASK=smoke src/scripts/competitors/competitor_llm.sbatch
#   sbatch --array=0-3 --export=ALL,TASK=rel,NSHARDS=4 src/scripts/competitors/competitor_llm.sbatch
#   sbatch --export=ALL,TASK=ner src/scripts/competitors/competitor_llm.sbatch
#   sbatch --export=ALL,TASK=gbdb src/scripts/competitors/competitor_llm.sbatch
# Reads CDM 3.0.3 / 3.1.0 read-only. New analysis under the development freeze: PENDING lead approval (CHANGE_RECORD).
# Written with Claude Code (declare).
CDM_ROOT="${CDM_REPO_ROOT:-$(d="${SLURM_SUBMIT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"; while [ "$d" != / ] && [ ! -f "$d/.cdm_root" ]; do d="$(dirname "$d")"; done; echo "$d")}"
[ -f "$CDM_ROOT/.cdm_root" ] || { echo "ERROR: repo root not found" >&2; exit 1; }
set -euo pipefail
cd "$CDM_ROOT"
MODEL=${RT_MODEL:-cyankiwi/Qwen3.5-9B-AWQ-4bit}; REV=${RT_REV:-e4d2d39cede8c5d1716d824cd843e2889c648083}
SH=${SLURM_ARRAY_TASK_ID:-0}; NS=${NSHARDS:-1}
PORT=$(python3 -c "import socket;s=socket.socket();s.bind(('',0));print(s.getsockname()[1]);s.close()")
module use /opt/software/easybuild-AMD/modules/all
module load Python/3.12.3-GCCcore-13.3.0
module load CUDA/12.9.1
source /home/jkalra_hpc/venvs/vllm/bin/activate
export CUDA_HOME="$(dirname "$(dirname "$(command -v nvcc)")")"
export HF_HOME=/home/jkalra_hpc/llm/hf-cache HF_HUB_OFFLINE=1 PYTHONUNBUFFERED=1 VLLM_USE_FLASHINFER_SAMPLER=0
# Outputs go to Lustre while the job runs (home NFS appends hung on compute nodes on 2026-11-11, job 28788876) and are
# copied back to the repo at the end; a later run resumes from the Lustre copy.
HOMEOUT=outputs/results/competitor_compare_2026-11-11/llm_runs
LOUT=${CMP_LUSTRE_OUT:-/lustre/scratch/data/jkalra_hpc-deep_learning/cdm_competitor_compare_2026-11-11/llm_runs}
mkdir -p "$LOUT"
for t in rel ner gbdb; do
    mkdir -p "$LOUT/$t"
    for f in "$HOMEOUT/$t"/*.jsonl; do [ -f "$f" ] && [ ! -f "$LOUT/$t/$(basename "$f")" ] && timeout 120 cp "$f" "$LOUT/$t/" || true; done
done
copyback() { set +e; for t in rel ner gbdb; do mkdir -p "$HOMEOUT/$t"; for f in "$LOUT/$t"/*.jsonl; do [ -f "$f" ] && timeout 300 cp "$f" "$HOMEOUT/$t/" ; done; done; true; }
mkdir -p "$LOUT/../logs"
LOG=$LOUT/../logs/vllm-cmp-${SLURM_JOB_ID:-0}_${SH}.log
vllm serve "$MODEL" --revision "$REV" --served-model-name "$MODEL" --port "$PORT" --gpu-memory-utilization 0.90 \
    --max-model-len 16384 --max-num-seqs ${RT_SEQS:-64} --enable-prefix-caching --structured-outputs-config '{"backend":"xgrammar","disable_any_whitespace":true}' > "$LOG" 2>&1 &
SRV=$!
trap 'set +e; copyback; kill $SRV 2>/dev/null; sleep 20; kill -9 $SRV 2>/dev/null; pkill -9 -P $SRV 2>/dev/null; true' EXIT
for _ in $(seq 1 180); do
    curl -sf "http://127.0.0.1:$PORT/v1/models" >/dev/null 2>&1 && break
    kill -0 $SRV 2>/dev/null || { echo "vLLM died"; tail -40 "$LOG"; exit 1; }
    sleep 5
done
curl -sf "http://127.0.0.1:$PORT/v1/models" | grep -q "$MODEL" || { echo "FATAL: server on $PORT is not serving $MODEL"; exit 95; }
R=src/scripts/competitors/competitor_llm_runner.py
case "${TASK:?}" in
  smoke) python $R --task rel --sample 60 --outdir outputs/results/competitor_compare_2026-11-11/llm_runs/smoke --port "$PORT" --model "$MODEL" --shard 0 --nshards 1 ;;
  rel)   python $R --task rel --outdir "$LOUT" --port "$PORT" --model "$MODEL" --shard "$SH" --nshards "$NS" ;;
  ner)   python $R --task ner --outdir "$LOUT" --port "$PORT" --model "$MODEL" --shard "$SH" --nshards "$NS" ;;
  gbdb)  python $R --task gbdb --outdir "$LOUT" --port "$PORT" --model "$MODEL" --shard "$SH" --nshards "$NS" ;;
esac
