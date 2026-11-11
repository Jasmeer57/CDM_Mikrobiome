#!/bin/bash
#SBATCH --job-name=diag-v32
#SBATCH --partition=mlgpu_short
#SBATCH --gres=gpu:a40:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=48G
#SBATCH --time=08:00:00
#SBATCH --output=outputs/logs/slurm/%x-%j.out
# Reviewer diagnostics 2026-11-11 (items 1-2), local models only, one A40. Submit from the repo root:
#   sbatch --export=ALL,TASK=unsigned_open src/scripts/diagnostics_v32/diag.sbatch            # Qwen3.5-9B on the 959 CC BY/CC0 triples
#   sbatch --export=ALL,TASK=retype_reps src/scripts/diagnostics_v32/diag.sbatch              # 500 triples x (3 x T0 + 1 x T0.7)
#   sbatch --export=ALL,TASK=judge_reps,JUDGE=qwen9 src/scripts/diagnostics_v32/diag.sbatch   # 500 records x (3 x T0 + 1 x T0.7)
# Server pattern of src/scripts/terms/retype_v2.sbatch (free port, model-name check, trap with set +e). Reads CDM 3.0.3
# read-only (node-local sha-checked copy). Writes only under outputs/results/diagnostics_2026-11-11/. Thinking disabled.
CDM_ROOT="${CDM_REPO_ROOT:-$(d="${SLURM_SUBMIT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"; while [ "$d" != / ] && [ ! -f "$d/.cdm_root" ]; do d="$(dirname "$d")"; done; echo "$d")}"
[ -f "$CDM_ROOT/.cdm_root" ] || { echo "ERROR: repo root not found" >&2; exit 1; }
set -euo pipefail
cd "$CDM_ROOT"
EXTRA=""; MAXLEN=16384
case "${JUDGE:-qwen9}" in
    qwen9)   MODEL=cyankiwi/Qwen3.5-9B-AWQ-4bit; EXTRA="--revision e4d2d39cede8c5d1716d824cd843e2889c648083" ;;
    llama)   MODEL=hugging-quants/Meta-Llama-3.1-8B-Instruct-AWQ-INT4; MAXLEN=8192 ;;
    mistral) MODEL=TechxGenus/Mistral-7B-Instruct-v0.3-AWQ; MAXLEN=8192 ;;
esac
PORT=$(python3 -c "import socket;s=socket.socket();s.bind(('',0));print(s.getsockname()[1]);s.close()")
module use /opt/software/easybuild-AMD/modules/all
module load Python/3.12.3-GCCcore-13.3.0
module load CUDA/12.9.1
source /home/jkalra_hpc/venvs/vllm/bin/activate
export CUDA_HOME="$(dirname "$(dirname "$(command -v nvcc)")")"
export HF_HOME=/home/jkalra_hpc/llm/hf-cache HF_HUB_OFFLINE=1 PYTHONUNBUFFERED=1 VLLM_USE_FLASHINFER_SAMPLER=0
DB="$CDM_ROOT/releases/cdm_v3/3.0.3/microbiome_cdm_v3.db"
LOCALDB="${TMPDIR:-/tmp}/cdm303_diag_${SLURM_JOB_ID:-local}.db"
cp "$DB" "$LOCALDB"
[[ "$(sha256sum "$LOCALDB" | cut -d' ' -f1)" == 5d23ba87d29ac7a6de831e66b35c0f42bc10312132cf20dd0191526b8b041e3e ]] || { echo "FATAL: CDM sha" >&2; exit 91; }
LOG=outputs/logs/slurm/vllm-diag-${SLURM_JOB_ID:-0}.log
vllm serve "$MODEL" $EXTRA --served-model-name "$MODEL" --port "$PORT" --gpu-memory-utilization 0.90 \
    --max-model-len "$MAXLEN" --max-num-seqs 64 --enable-prefix-caching --structured-outputs-config '{"backend":"xgrammar","disable_any_whitespace":true}' > "$LOG" 2>&1 &
SRV=$!
trap 'set +e; kill $SRV 2>/dev/null; sleep 20; kill -9 $SRV 2>/dev/null; pkill -9 -P $SRV 2>/dev/null; rm -f "$LOCALDB"; true' EXIT
for _ in $(seq 1 180); do
    curl -sf "http://127.0.0.1:$PORT/v1/models" >/dev/null 2>&1 && break
    kill -0 $SRV 2>/dev/null || { echo "vLLM died"; tail -40 "$LOG"; exit 1; }
    sleep 5
done
curl -sf "http://127.0.0.1:$PORT/v1/models" | grep -q "$MODEL" || { echo "FATAL: server on $PORT is not serving $MODEL"; exit 95; }
# results are written to Lustre (home NFS append hangs seen on compute nodes, 2026-11-10/11) and copied back at the end
D=${DIAG_LUSTRE:-/lustre/scratch/data/jkalra_hpc-deep_learning/cdm_diagnostics_2026-11-11}
R=outputs/results/diagnostics_2026-11-11
SAMPLE="$R/run_variance/judge_sample.json"
mkdir -p "$D"
S=src/scripts/diagnostics_v32
case "${TASK:?}" in
  unsigned_open)
    python $S/unsigned_local_open.py --port "$PORT" --model "$MODEL" --db303 "$LOCALDB" --out "$D/licence_comparability/local_on_open" --workers 16 ;;
  retype_reps)
    for r in rep1 rep2 rep3; do
      echo "== retype $r T=0"; python $S/retype_rerun.py --out "$D/run_variance/retype/$r" --port "$PORT" --db303 "$LOCALDB" --sample 500
    done
    echo "== retype t07"; DIAG_TEMPERATURE=0.7 DIAG_SEED=20261111 python $S/retype_rerun.py --out "$D/run_variance/retype/t07" --port "$PORT" --db303 "$LOCALDB" --sample 500 ;;
  judge_reps)
    for r in rep1 rep2 rep3; do
      echo "== judge ${JUDGE} $r T=0"; python $S/judge_rerun.py --sample "$SAMPLE" --model "$JUDGE" --host "http://127.0.0.1:$PORT" --out "$D/run_variance/judge/$r"
    done
    echo "== judge ${JUDGE} t07"; DIAG_TEMPERATURE=0.7 DIAG_SEED=20261111 python $S/judge_rerun.py --sample "$SAMPLE" --model "$JUDGE" --host "http://127.0.0.1:$PORT" --out "$D/run_variance/judge/t07" ;;
esac
case "$TASK" in
  unsigned_open) SUB=licence_comparability/local_on_open ;;
  retype_reps)   SUB=run_variance/retype ;;
  judge_reps)    SUB=run_variance/judge ;;
esac
mkdir -p "$R/$SUB"
timeout 600 cp -r "$D/$SUB/." "$R/$SUB/"
echo "TASK ${TASK} finished; copied $D/$SUB -> $R/$SUB"
