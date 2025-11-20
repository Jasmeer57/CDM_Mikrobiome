#!/bin/bash
#SBATCH --job-name=cdm_pipeline
#SBATCH --output=logs/cdm_pipeline_%j.out
#SBATCH --error=logs/cdm_pipeline_%j.err
#SBATCH --time=24:00:00
#SBATCH --mem=120G
#SBATCH --cpus-per-task=16
#SBATCH --nodes=1
#SBATCH --partition=gpu-amd
#SBATCH --gres=gpu:a100:1

# === CDM PIPELINE METADATA EXTRACTION ===
export SLURM_JOB_START_TIME="$(date)"
echo "=== CDM PIPELINE - MICROBIOME ENTITY EXTRACTION ==="
echo "Job started at: $(date)"
echo "Node: $HOSTNAME"
echo "Job ID: $SLURM_JOB_ID"
echo "GPU assigned: $CUDA_VISIBLE_DEVICES"
echo ""

# === ENVIRONMENT SETUP ===
module purge
module load Miniforge3/24.1.2-0
source "$EBROOTMINIFORGE3/etc/profile.d/conda.sh"
module load CUDA/12.3.0

# Create logs directory
mkdir -p logs

# Activate or create conda environment
if conda env list | grep -q "cdm_pipeline"; then
    echo "✅ Activating existing cdm_pipeline environment..."
    conda activate cdm_pipeline
else
    echo "🔧 Creating cdm_pipeline environment..."
    conda create -y -n cdm_pipeline python=3.10
    conda activate cdm_pipeline

    echo "📦 Installing dependencies..."
    pip install --no-cache-dir \
        fastapi==0.104.1 \
        uvicorn[standard]==0.24.0 \
        python-multipart==0.0.6 \
        sentence-transformers==2.2.2 \
        torch==2.1.1 \
        transformers==4.35.2 \
        scikit-learn==1.3.2 \
        einops==0.7.0 \
        numpy==1.24.4 \
        pandas==2.0.3 \
        scipy==1.11.4 \
        requests==2.31.0 \
        urllib3==2.1.0 \
        httpx==0.25.2 \
        jsonschema==4.20.0 \
        pydantic==2.5.0 \
        structlog==23.2.0 \
        pytest==7.4.3 \
        pytest-asyncio==0.21.1 \
        spacy==3.7.2 \
        scispacy==0.5.1 \
        nltk==3.8.1 \
        sqlalchemy==2.0.23 \
        redis==5.0.1 \
        elasticsearch==8.11.0 \
        python-dotenv==1.0.0 \
        mkdocs==1.5.3 \
        mkdocs-material==9.4.8 \
        mkdocs-git-revision-date-localized-plugin==1.2.6 \
        mkdocs-minify-plugin==0.7.1 \
        mkdocs-awesome-pages-plugin==2.9.2 \
        pymdown-extensions==10.7 \
        mkdocstrings==0.24.0
fi

# Check GPU availability
echo "🔍 Checking GPU availability..."
nvidia-smi

# Set environment variables for optimal performance
export CUDA_VISIBLE_DEVICES=0
export OMP_NUM_THREADS=$SLURM_CPUS_PER_TASK
export PYTHONPATH="${PYTHONPATH}:$(pwd)"
export TOKENIZERS_PARALLELISM=false

# Navigate to project directory
cd cdm_pipeline || {
    echo "❌ Error: cdm_pipeline directory not found!"
    echo "Current directory: $(pwd)"
    exit 1
}

echo "📂 Working directory: $(pwd)"
echo ""

# === OLLAMA SETUP ===
echo "🚀 Starting Ollama service..."
ollama serve &
OLLAMA_PID=$!
sleep 30  # Give Ollama time to start

# Check if Ollama is running
if ! curl -s http://localhost:11434/api/tags > /dev/null; then
    echo "❌ Error: Ollama service failed to start!"
    kill $OLLAMA_PID 2>/dev/null
    exit 1
fi

echo "✅ Ollama service started successfully!"

# Download required models if not already available
echo "📥 Checking required models..."

MODELS=("phi3:mini" "qwen3:8b" "biomistral:7b" "nomic-embed-text:latest")
for model in "${MODELS[@]}"; do
    if ! ollama list | grep -q "$model"; then
        echo "📥 Downloading model: $model..."
        ollama pull "$model" || {
            echo "⚠️ Warning: Failed to download model $model"
        }
    else
        echo "✅ Model $model already available"
    fi
done

# === PIPELINE CONFIGURATION ===
echo ""
echo "⚙️ Pipeline Configuration:"
echo "   - Input file: ${1:-/path/to/your/input.txt}"
echo "   - Max entities: ${2:-100}"
echo "   - Semantic model: nomic-embed-text"
echo "   - Semantic threshold: 0.8"
echo "   - Max workers: $SLURM_CPUS_PER_TASK"
echo ""

# Check if input file exists
INPUT_FILE="${1:-/path/to/your/input.txt}"
if [[ "$INPUT_FILE" == "/path/to/your/input.txt" ]]; then
    echo "❌ Error: Please provide input file path as first argument!"
    echo "Usage: sbatch run_cdm_pipeline.sh <input_file.txt> [max_entities]"
    kill $OLLAMA_PID 2>/dev/null
    exit 1
fi

if [[ ! -f "$INPUT_FILE" ]]; then
    echo "❌ Error: Input file not found: $INPUT_FILE"
    kill $OLLAMA_PID 2>/dev/null
    exit 1
fi

echo "📄 Input file: $INPUT_FILE"
MAX_ENTITIES="${2:-100}"

# === RUN CDM PIPELINE ===
echo ""
echo "🚀 Starting CDM Entity Extraction Pipeline..."
echo "Started at: $(date)"

# Choose model based on available resources
MODEL_TO_USE="phi3:mini"
if [[ "$CUDA_VISIBLE_DEVICES" != "" ]]; then
    # Check GPU memory and choose appropriate model
    GPU_MEMORY=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits | head -1)
    if [[ $GPU_MEMORY -gt 32000 ]]; then
        MODEL_TO_USE="qwen3:8b"
        echo "🎯 Using qwen3:8b model (GPU memory: ${GPU_MEMORY}MB)"
    else
        echo "🎯 Using phi3:mini model (GPU memory: ${GPU_MEMORY}MB)"
    fi
fi

# Run the pipeline with BioMistral deduplication
python main.py \
    --input-file "$INPUT_FILE" \
    --model "$MODEL_TO_USE" \
    --max-entities "$MAX_ENTITIES" \
    --semantic-model nomic-embed-text \
    --semantic-threshold 0.8 \
    --enable-biomistral-deduplication \
    --biomistral-dedup-model biomistral:7b \
    --max-workers "$SLURM_CPUS_PER_TASK" \
    --verbose

PIPELINE_EXIT_CODE=$?

echo ""
echo "Pipeline completed at: $(date)"

# === OUTPUT PROCESSING ===
if [[ $PIPELINE_EXIT_CODE -eq 0 ]]; then
    echo "✅ Pipeline completed successfully!"

    # Check if output files were created
    if [[ -f "cdm_entities.json" ]]; then
        echo "📊 Output summary:"
        echo "   - Entities saved to: cdm_entities.json"

        # Extract basic statistics
        ENTITY_COUNT=$(jq -r '.extraction_statistics.total_entities // 0' cdm_entities.json 2>/dev/null || echo "N/A")
        AVG_CONFIDENCE=$(jq -r '.extraction_statistics.average_confidence // 0' cdm_entities.json 2>/dev/null || echo "N/A")

        echo "   - Total entities extracted: $ENTITY_COUNT"
        echo "   - Average confidence: $AVG_CONFIDENCE"

        # Show entity type distribution
        echo "   - Entity type distribution:"
        jq -r '.extraction_statistics.entity_type_distribution // {} | to_entries[] | "     \(.key): \(.value)"' cdm_entities.json 2>/dev/null || echo "     Not available"
    fi

    if [[ -f "cdm_pipeline.db" ]]; then
        echo "   - Database created: cdm_pipeline.db"
    fi
else
    echo "❌ Pipeline failed with exit code: $PIPELINE_EXIT_CODE"
fi

# === CLEANUP ===
echo ""
echo "🧹 Cleaning up..."
kill $OLLAMA_PID 2>/dev/null
wait $OLLAMA_PID 2>/dev/null

# Job completion summary
echo ""
echo "=== JOB COMPLETION SUMMARY ==="
echo "Job started at: $SLURM_JOB_START_TIME"
echo "Job completed at: $(date)"
echo "Total runtime: $(date -ud "@$(($(date +%s) - $(date -d "$SLURM_JOB_START_TIME" +%s)))" | cut -d' ' -f4-5)"
echo "Node used: $HOSTNAME"
echo "Exit status: $PIPELINE_EXIT_CODE"

if [[ $PIPELINE_EXIT_CODE -eq 0 ]]; then
    echo "✅ CDM Pipeline job completed successfully!"
else
    echo "❌ CDM Pipeline job failed!"
fi

exit $PIPELINE_EXIT_CODE