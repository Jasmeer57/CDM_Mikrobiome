#!/bin/bash
#SBATCH --job-name=kg-builder-llama-cpp
#SBATCH --output=logs/kg_builder_llama_cpp_%j.out
#SBATCH --error=logs/kg_builder_llama_cpp_%j.err
#SBATCH --time=24:00:00
#SBATCH --nodes=1
#SBATCH --partition=gpu-nvrtx
#SBATCH --gres=gpu:rtx6000
#SBATCH --cpus-per-task=32
#SBATCH --mem=200G

# =============================================================================
# Knowledge Graph Builder - llama.cpp with Phi Model
# ==============================================================================

# Repo root, found at run time: $CDM_REPO_ROOT, else walk up to .cdm_root
# from the submit dir (sbatch) or this script's dir (direct run).
CDM_ROOT="${CDM_REPO_ROOT:-$(d="${SLURM_SUBMIT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"; while [ "$d" != / ] && [ ! -f "$d/.cdm_root" ]; do d="$(dirname "$d")"; done; echo "$d")}"
[ -f "$CDM_ROOT/.cdm_root" ] || { echo "ERROR: repo root not found; set CDM_REPO_ROOT" >&2; exit 1; }
export CDM_ROOT

echo "================================================================"
echo "Knowledge Graph Builder - llama.cpp Phi Model"
echo "================================================================"
echo "Job ID  : $SLURM_JOB_ID"
echo "Node    : $HOSTNAME"
echo "Started : $(date)"
echo "================================================================"

# =============================================================================
# ENVIRONMENT
# =============================================================================
module purge
module load CUDA/12.8.0
module load Miniforge3/24.11.3-0

cd $CDM_ROOT/pipelines/llm_terms/kg_builder

source /opt/software/easybuild/genoa/software/Miniforge3/24.11.3-0/etc/profile.d/conda.sh
conda activate metadata-compliance

mkdir -p logs new_output

# =============================================================================
# CONFIGURATION
# =============================================================================
PORT=$((8000 + RANDOM % 1000))
ENTITIES_FILE="../../archive/legacy_kg_extraction/extraction/entities_raw.jsonl"

echo "Using port: $PORT"
echo "Entities file: $ENTITIES_FILE"

# =============================================================================
# START llama.cpp SERVER with Phi Model
# =============================================================================
echo "Downloading Phi-4 model..."

MODEL_PATH=$(python -c "from huggingface_hub import hf_hub_download; print(hf_hub_download(repo_id='microsoft/phi-4-gguf', filename='phi-4-Q8_0.gguf'))")

LOG_FILE="logs/llama_server_${SLURM_JOB_ID}.log"
echo "Model path: $MODEL_PATH"
echo "Log file: $LOG_FILE"

echo "Starting llama.cpp server..."

python -m llama_cpp.server \
  --model "$MODEL_PATH" \
  --host 127.0.0.1 \
  --port "$PORT" \
  --n_gpu_layers -1 \
  --n_ctx 32768 \
  --n_batch 4096 \
  --n_threads 16 \
  --use_mmap false \
  --use_mlock true \
  > "$LOG_FILE" 2>&1 &

SERVER_PID=$!
echo "LLM server PID: $SERVER_PID"
sleep 5

# =============================================================================
# WAIT FOR SERVER READINESS
# =============================================================================
echo "Waiting for LLM server..."
SERVER_READY=false
for i in {1..60}; do
    if curl -s "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
        if curl -s "http://127.0.0.1:$PORT/v1/models" 2>/dev/null | grep -qi "phi\|model"; then
            echo "LLM server ready after ${i} checks."
            SERVER_READY=true
            break
        fi
    fi
    sleep 2
done

if [ "$SERVER_READY" = false ]; then
    echo "ERROR: LLM server failed to start"
    cat "$LOG_FILE"
    kill "$SERVER_PID" 2>/dev/null
    exit 1
fi

echo "================================================================"
echo "Starting Knowledge Graph Builder"
echo "================================================================"

# Run the kg_builder with llama_cpp
python kg_builder_llama_cpp.py --entities "$ENTITIES_FILE" --llama-url "http://127.0.0.1:$PORT/v1"

BUILD_EXIT=$?

# =============================================================================
# CLEANUP
# =============================================================================
echo "Cleaning up..."
kill "$SERVER_PID" 2>/dev/null || true
wait "$SERVER_PID" 2>/dev/null || true

if [ $BUILD_EXIT -eq 0 ]; then
    echo "================================================================"
    echo "Knowledge Graph Built Successfully!"
    echo "================================================================"
else
    echo "================================================================"
    echo "Build Failed (exit code: $BUILD_EXIT)"
    echo "================================================================"
    exit $BUILD_EXIT
fi

echo "Done."
exit 0
