#!/bin/bash
#SBATCH --job-name=modular_cdm_pipeline
#SBATCH --output=logs/modular_pipeline_%j.out
#SBATCH --error=logs/modular_pipeline_%j.err
#SBATCH --partition=gpu-mix
#SBATCH --gres=gpu:a100:1
#SBATCH --cpus-per-task=16
#SBATCH --mem=120G
#SBATCH --time=12:00:00
#SBATCH --nodes=1

# === METADATA ===
export SLURM_JOB_START_TIME="$(date)"
echo "=== MODULAR CDM ENTITY EXTRACTION PIPELINE ==="
echo "Job started at: $(date)"
echo "Node: $HOSTNAME"
echo "Job ID: $SLURM_JOB_ID"
echo "GPU: $CUDA_VISIBLE_DEVICES"
echo "CPUs: $SLURM_CPUS_PER_TASK"
echo "Memory: ${SLURM_MEM_PER_NODE}GB"
echo ""

# === ENVIRONMENT SETUP ===
module purge
module load Miniforge3/24.1.2-0
source "$EBROOTMINIFORGE3/etc/profile.d/conda.sh"
module load CUDA/12.3.0

# Create logs directory
mkdir -p logs

# === CONDA ENVIRONMENT ===
# === CONDA ENVIRONMENT ===
echo "Setting up conda environment..."
if conda info --envs | grep -q "llm-terms-cdm"; then
    echo "Environment llm-terms-cdm already exists. Activating..."
    conda activate llm-terms-cdm
else
    echo "Creating new environment llm-terms-cdm..."
    conda create -n llm-terms-cdm python=3.9 -y
    conda activate llm-terms-cdm
fi

# === INSTALL DEPENDENCIES ===
echo "Installing dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

# === API KEYS CONFIGURATION ===
# Load environment variables from .env file
if [ -f .env ]; then
    echo "Loading environment variables from .env..."
    set -a
    source .env
    set +a
    echo "✅ Environment variables loaded"
else
    echo "⚠️  Warning: .env file not found"
fi

# === SETUP DIRECTORIES ===
echo "Setting up directories..."
mkdir -p output
mkdir -p logs
mkdir -p checkpoints
mkdir -p data

# === PIPELINE CONFIGURATION ===
echo ""
echo "=== PIPELINE CONFIGURATION ==="
echo "Pipeline configuration:"
echo "  - Input file: ./data/input_text.txt (update as needed)"
echo "  - Model: qwen3:14b"
echo "  - Base URL: http://localhost:11434"
echo "  - Semantic model: all-MiniLM-L6-v2"
echo "  - Max workers: 3"
echo "  - BioMistral validation: ENABLED"
echo "  - Term Correction: ENABLED"
echo ""

# Check if input file exists
INPUT_FILE="./data/input_text.txt"
if [ ! -f "$INPUT_FILE" ]; then
    echo "WARNING: Input file $INPUT_FILE not found!"
    echo "Please place your input text file in the data/ directory or modify the INPUT_FILE variable"
    mkdir -p data
    cat > "$INPUT_FILE" << 'EOF'
The human gut microbiome plays a crucial role in maintaining overall health.
Recent studies have identified various bacterial species such as Bacteroides fragilis,
Faecalibacterium prausnitzii, and Akkermansia muciniphila as key players in
intestinal homeostasis.
EOF
    echo "Sample input file created at: $INPUT_FILE"
fi

# === RUN MODULAR PIPELINE ===
echo "=== STARTING MODULAR PIPELINE ==="
echo ""

# Run modular pipeline using main.py
python main.py \
    --input-file "$INPUT_FILE" \
    --output "output/modular_cdm_entities.json" \
    --model qwen3:14b \
    --base-url http://localhost:11434 \
    --semantic-model all-MiniLM-L6-v2 \
    --max-workers 3 \
    --enable-biomistral \
    --enable-correction \
    --enable-omop-mapping \
    --log-format json \
    --verbose

EXIT_CODE=$?

# === PIPELINE COMPLETION ANALYSIS ===
echo ""
echo "=== PIPELINE COMPLETION ANALYSIS ==="
echo "Pipeline exit code: $EXIT_CODE"

if [ $EXIT_CODE -eq 0 ]; then
    echo "✅ SUCCESS: Modular pipeline completed successfully!"
    
    if [ -f "output/modular_cdm_entities.json" ]; then
        echo "📄 Output: output/modular_cdm_entities.json"
        ENTITY_COUNT=$(grep -c '"entity":' "output/modular_cdm_entities.json" 2>/dev/null || echo "N/A")
        echo "   - Total entities extracted: $ENTITY_COUNT"
    fi
else
    echo "❌ FAILED: Pipeline failed with exit code $EXIT_CODE"
    echo "Check error log: logs/modular_pipeline_${SLURM_JOB_ID}.err"
fi

# === CLEANUP ===
echo ""
echo "Cleaning up..."
conda deactivate

echo ""
echo "=== MODULAR PIPELINE EXECUTION COMPLETE ==="
exit $EXIT_CODE
