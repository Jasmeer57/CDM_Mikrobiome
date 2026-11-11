#!/bin/bash
#SBATCH --job-name=cat-v32-blocks
#SBATCH --partition=mlgpu_short
#SBATCH --gres=gpu:a40:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=48G
#SBATCH --time=06:00:00
#SBATCH --output=outputs/logs/slurm/%x-%j.out
# Catalogue 3.2.0-candidate: findings from table / caption blocks with Qwen3.5-9B (AWQ, local vLLM, one A40).
# Submit from the repo root after `python src/scripts/fixes_v32/extract_blocks.py prepare`:
#   sbatch --export=ALL,LIMIT=40 src/scripts/fixes_v32/extract_blocks.sbatch     # smoke
#   sbatch src/scripts/fixes_v32/extract_blocks.sbatch                           # all units
# Freeze exception PENDING lead approval. Reads only units.jsonl (derived from CDM 3.0.3 read-only).
CDM_ROOT="${CDM_REPO_ROOT:-$(d="${SLURM_SUBMIT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"; while [ "$d" != / ] && [ ! -f "$d/.cdm_root" ]; do d="$(dirname "$d")"; done; echo "$d")}"
[ -f "$CDM_ROOT/.cdm_root" ] || { echo "ERROR: repo root not found" >&2; exit 1; }
set -euo pipefail
cd "$CDM_ROOT"
MODEL=${RT_MODEL:-cyankiwi/Qwen3.5-9B-AWQ-4bit}; REV=${RT_REV:-e4d2d39cede8c5d1716d824cd843e2889c648083}
PORT=$(python3 -c "import socket;s=socket.socket();s.bind(('',0));print(s.getsockname()[1]);s.close()")
module use /opt/software/easybuild-AMD/modules/all
module load Python/3.12.3-GCCcore-13.3.0
module load CUDA/12.9.1
source /home/jkalra_hpc/venvs/vllm/bin/activate
export CUDA_HOME="$(dirname "$(dirname "$(command -v nvcc)")")"
export HF_HOME=/home/jkalra_hpc/llm/hf-cache HF_HUB_OFFLINE=1 PYTHONUNBUFFERED=1 VLLM_USE_FLASHINFER_SAMPLER=0
LOG=outputs/logs/slurm/vllm-catv32-${SLURM_JOB_ID:-0}.log
vllm serve "$MODEL" --revision "$REV" --served-model-name "$MODEL" --port "$PORT" --gpu-memory-utilization 0.90 \
    --max-model-len 16384 --max-num-seqs 48 --enable-prefix-caching --structured-outputs-config '{"backend":"xgrammar","disable_any_whitespace":true}' > "$LOG" 2>&1 &
SRV=$!
trap 'set +e; kill $SRV 2>/dev/null; sleep 20; kill -9 $SRV 2>/dev/null; pkill -9 -P $SRV 2>/dev/null; true' EXIT
for _ in $(seq 1 180); do
    curl -sf "http://127.0.0.1:$PORT/v1/models" >/dev/null 2>&1 && break
    kill -0 $SRV 2>/dev/null || { echo "vLLM died"; tail -40 "$LOG"; exit 1; }
    sleep 5
done
curl -sf "http://127.0.0.1:$PORT/v1/models" | grep -q "$MODEL" || { echo "FATAL: server on $PORT is not serving $MODEL"; exit 95; }
OUTDIR=outputs/results/catalogue_tables_captions_v32_2026-11-11/${RUN_DIR:-extract}
python src/scripts/fixes_v32/extract_blocks.py run --port "$PORT" --model "$MODEL" --out "$OUTDIR" --limit "${LIMIT:-0}" --parallel 48
