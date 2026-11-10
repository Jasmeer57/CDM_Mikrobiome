#!/bin/bash
#SBATCH --job-name=termdef
#SBATCH --partition=mlgpu_medium
#SBATCH --gres=gpu:a40:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=48G
#SBATCH --time=24:00:00
#SBATCH --output=outputs/logs/slurm/%x-%j.out
#SBATCH --error=outputs/logs/slurm/%x-%j.err
#
# Contextual definitions + full forms + synonyms (Qwen3.5-4B, local vLLM on one A40; reads corpus sentences). Submit from the repo root:
#   sbatch --job-name=termdef-500 src/scripts/definitions/term_definitions.sbatch sample500
#   sbatch --job-name=termdef-all src/scripts/definitions/term_definitions.sbatch all
# Writes only to outputs/results/term_definitions_llm_2026-11-09/<scope>/ ; reads CDM 3.0.3 read-only.
# Freeze exception (new model run), pending project-lead approval: see final_validation/CHANGE_RECORD.md.
CDM_ROOT="${CDM_REPO_ROOT:-$(d="${SLURM_SUBMIT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"; while [ "$d" != / ] && [ ! -f "$d/.cdm_root" ]; do d="$(dirname "$d")"; done; echo "$d")}"
[ -f "$CDM_ROOT/.cdm_root" ] || { echo "ERROR: repo root not found; set CDM_REPO_ROOT" >&2; exit 1; }
set -euo pipefail
SCOPE="${1:?usage: sbatch term_definitions.sbatch sample500|all}"
OUT="$CDM_ROOT/outputs/results/term_definitions_llm_2026-11-09/$SCOPE"
PORT=$((8017 + (${SLURM_JOB_ID:-0} % 200)))
MODEL="Qwen/Qwen3.5-4B"
mkdir -p "$OUT" "$CDM_ROOT/outputs/logs/slurm"

module use /opt/software/easybuild-AMD/modules/all
module load Python/3.12.3-GCCcore-13.3.0
module load CUDA/12.9.1
source /home/jkalra_hpc/venvs/vllm/bin/activate
export CUDA_HOME="$(dirname "$(dirname "$(command -v nvcc)")")"
export VLLM_USE_FLASHINFER_SAMPLER=0 PYTHONUNBUFFERED=1 TOKENIZERS_PARALLELISM=false
export HF_HOME=/home/jkalra_hpc/llm/hf-cache HF_HUB_OFFLINE=1

DB="$CDM_ROOT/releases/cdm_v3/3.0.3/microbiome_cdm_v3.db"
DB_SHA=$(sha256sum "$DB" | cut -d' ' -f1)
[[ "$DB_SHA" == 5d23ba87d29ac7a6de831e66b35c0f42bc10312132cf20dd0191526b8b041e3e ]] || { echo "FATAL: CDM sha $DB_SHA" >&2; exit 91; }

LOCALDB="${TMPDIR:-/tmp}/cdm303_${SLURM_JOB_ID:-local}.db"
cp "$DB" "$LOCALDB"
[[ "$(sha256sum "$LOCALDB" | cut -d' ' -f1)" == "$DB_SHA" ]] || { echo "FATAL: local copy sha mismatch" >&2; exit 94; }
trap 'rm -f "$LOCALDB"' EXIT
echo "[$(date -u +%FT%TZ)] node=$(hostname) job=${SLURM_JOB_ID:-local} scope=$SCOPE port=$PORT"
nvidia-smi -L || true
CUDA_VISIBLE_DEVICES=0 vllm serve "$MODEL" --port "$PORT" --gpu-memory-utilization 0.90 \
    --max-model-len 16384 --max-num-seqs 64 --served-model-name "$MODEL" > "$OUT/vllm-${SLURM_JOB_ID:-local}.log" 2>&1 &
SERVER_PID=$!
trap 'kill "$SERVER_PID" 2>/dev/null || true; wait "$SERVER_PID" 2>/dev/null || true; rm -f "$LOCALDB"' EXIT
for i in $(seq 1 120); do
    curl -sf "http://127.0.0.1:${PORT}/v1/models" >/dev/null 2>&1 && break
    kill -0 "$SERVER_PID" 2>/dev/null || { echo "FATAL: vLLM died"; tail -50 "$OUT/vllm-${SLURM_JOB_ID:-local}.log"; exit 92; }
    sleep 10
done
curl -sf "http://127.0.0.1:${PORT}/v1/models" >/dev/null || { echo "FATAL: vLLM not ready"; exit 93; }
echo "vLLM ready"
# Optional hand-over: REPLACE_JOB=<jobid> cancels an earlier job on the same scope only once this server is ready;
# the generator then resumes from the rows that job wrote.
if [[ -n "${REPLACE_JOB:-}" ]]; then
    echo "taking over from job $REPLACE_JOB"
    scancel "$REPLACE_JOB" || true
    while squeue -h -j "$REPLACE_JOB" 2>/dev/null | grep -q .; do sleep 5; done
fi

if [[ "${TASK:-definitions}" == "repair" ]]; then
    OUT="$CDM_ROOT/outputs/results/${REPAIR_DIR:-triple_repair_2026-11-09}"; mkdir -p "$OUT"
    python "$CDM_ROOT/src/scripts/triples/repair_triples.py" --out "$OUT" --port "$PORT" --workers 48 --db "$LOCALDB" ${REPAIR_LIMIT:+--limit $REPAIR_LIMIT} ${REPAIR_SAMPLE:+--sample $REPAIR_SAMPLE}
    python3 "$CDM_ROOT/src/scripts/triples/triple_gates_tiers.py" --repair "$OUT"
elif [[ "${TASK:-definitions}" == "retype" ]]; then
    OUT="$CDM_ROOT/outputs/results/triple_retyping_2026-11-09"; mkdir -p "$OUT"
    python "$CDM_ROOT/src/scripts/triples/retype_generic_triples.py" --out "$OUT" --port "$PORT" --workers 48 --db "$LOCALDB" ${RETYPE_LIMIT:+--limit $RETYPE_LIMIT}
elif [[ "${TASK:-definitions}" == "complete" ]]; then
    python "$CDM_ROOT/src/scripts/definitions/generate_completion.py" --scope "$SCOPE" --out "$OUT/completion" --port "$PORT" --workers 48 --db "$LOCALDB"
else
    python "$CDM_ROOT/src/scripts/definitions/generate_term_definitions.py" --scope "$SCOPE" --out "$OUT" --port "$PORT" --workers 48 --db "$LOCALDB"
fi
echo "[$(date -u +%FT%TZ)] done"
