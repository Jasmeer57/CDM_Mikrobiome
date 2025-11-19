#!/bin/bash
#SBATCH --job-name=sci_term_extraction_complete
#SBATCH --output=logs/sci_term_complete_%j.out
#SBATCH --error=logs/sci_term_complete_%j.err
#SBATCH --partition=gpu-mix
#SBATCH --gres=gpu:a100:1
#SBATCH --cpus-per-task=16
#SBATCH --mem=120G
#SBATCH --time=12:00:00
#SBATCH --nodes=1

# === METADATA ===
export SLURM_JOB_START_TIME="$(date)"
echo "=== COMPLETE SCIENTIFIC TERM EXTRACTION PIPELINE ==="
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
echo "Setting up conda environment..."
conda create -n sci-term-extraction python=3.9 -y
conda activate sci-term-extraction

# === INSTALL DEPENDENCIES ===
echo "Installing dependencies..."
pip install --upgrade pip
pip install spacy==3.7.2
pip install scispacy==0.5.1
pip install sentence-transformers==2.2.2
pip install pandas==2.1.3
pip install numpy==1.24.3
pip install tqdm==4.66.1
pip install python-Levenshtein==0.23.0
pip install fastapi==0.104.1
pip install uvicorn==0.24.0
pip install python-multipart==0.0.6
pip install pydantic==2.5.0
pip install rapidfuzz==3.5.2
pip install python-docx==0.8.11
pip install PyPDF2==3.0.1
pip install Pillow==10.1.0

# === INSTALL SCIPACY MODELS ===
echo "Installing sciSpaCy models..."
pip install https://github.com/allenai/scispacy/releases/download/v0.5.1/en_core_sci_lg-0.5.1.tar.gz
pip install https://github.com/allenai/scispacy/releases/download/v0.5.1/en_ner_craft_md-0.5.1.tar.gz
pip install https://github.com/allenai/scispacy/releases/download/v0.5.1/en_ner_bc5cdr_md-0.5.1.tar.gz
pip install https://github.com/allenai/scispacy/releases/download/v0.5.1/en_ner_jnlpba_md-0.5.1.tar.gz

# === HUGGING FACE SETUP (if needed) ===
echo "Setting up Hugging Face..."
# Uncomment and add your token if needed
# huggingface-cli login --token YOUR_HF_TOKEN

# === CREATE OUTPUT DIRECTORIES ===
echo "Setting up output directories..."
mkdir -p output
mkdir -p logs
mkdir -p checkpoints

# === COMPLETE PIPELINE EXECUTION ===
echo ""
echo "=== STARTING COMPLETE PIPELINE EXECUTION ==="
echo "Pipeline configuration:"
echo "  - Input directory: ./data"
echo "  - Semantic model: nomic (upgraded v1.5)"
echo "  - Fuzzy threshold: 0.85"
echo "  - Semantic threshold: 0.90"
echo "  - BioMistral Biomedical Deduplication: ENABLED"
echo "  - Biomedical Context: microbiome"
echo "  - AI Correction: ENABLED"
echo "  - UMLS Mapping: ENABLED"
echo "  - OMOP Mapping: ENABLED"
echo "  - Output formats: json csv sqlite"
echo "  - Max files: 1 (trial run)"
echo ""

# Check input data
if [ ! -d "data" ]; then
    echo "ERROR: data directory not found!"
    exit 1
fi

echo "Available files in data directory:"
ls -la data/
echo ""

# === RUN COMPLETE PIPELINE ===
echo "Starting complete scientific term extraction pipeline..."
python main.py \
    --input_dir ./data \
    --semantic_model nomic \
    --fuzzy_threshold 0.85 \
    --semantic_threshold 0.90 \
    --biomedical_context microbiome \
    --max_files 1 \
    --output_formats json csv sqlite

PIPELINE_EXIT_CODE=$?

# === PIPELINE COMPLETION ANALYSIS ===
echo ""
echo "=== PIPELINE COMPLETION ANALYSIS ==="
echo "Pipeline completed with exit code: $PIPELINE_EXIT_CODE"

if [ $PIPELINE_EXIT_CODE -eq 0 ]; then
    echo "✅ SUCCESS: Pipeline completed successfully!"

    # Analyze results
    echo ""
    echo "=== RESULTS ANALYSIS ==="

    # Find latest output files
    LATEST_JSON=$(ls -t output/pipeline_results_*.json 2>/dev/null | head -1)
    LATEST_CSV=$(ls -t output/pipeline_results_*.csv 2>/dev/null | head -1)
    LATEST_DB=$(ls -t output/pipeline_results_*.db 2>/dev/null | head -1)

    if [ -n "$LATEST_JSON" ]; then
        echo "📄 JSON Output: $LATEST_JSON"
        TERM_COUNT=$(grep -c '"term":' "$LATEST_JSON" 2>/dev/null || echo "N/A")
        echo "   - Total terms extracted: $TERM_COUNT"
    fi

    if [ -n "$LATEST_CSV" ]; then
        echo "📊 CSV Output: $LATEST_CSV"
        LINE_COUNT=$(tail -n +2 "$LATEST_CSV" | wc -l 2>/dev/null || echo "N/A")
        echo "   - Total rows: $LINE_COUNT"
    fi

    if [ -n "$LATEST_DB" ]; then
        echo "💾 SQLite Database: $LATEST_DB"

        # Quick SQLite analysis if available
        if command -v sqlite3 &> /dev/null; then
            echo "   - Database tables:"
            sqlite3 "$LATEST_DB" ".tables" 2>/dev/null | head -10
            echo ""
            echo "   - Total terms in database:"
            sqlite3 "$LATEST_DB" "SELECT COUNT(*) FROM terms;" 2>/dev/null || echo "N/A"
            echo "   - CDM-ready terms:"
            sqlite3 "$LATEST_DB" "SELECT COUNT(*) FROM terms WHERE cdm_relevance IN ('HIGH', 'MEDIUM');" 2>/dev/null || echo "N/A"
        fi
    fi

else
    echo "❌ FAILED: Pipeline failed with exit code $PIPELINE_EXIT_CODE"
    echo "Check error log: logs/sci_term_complete_${SLURM_JOB_ID}.err"
fi

# === FINAL METADATA ===
echo ""
echo "=== JOB COMPLETION METADATA ==="
echo "Job started at: $SLURM_JOB_START_TIME"
echo "Job completed at: $(date)"
echo "Total runtime: $(date -d "$SLURM_JOB_START_TIME" +%s 2>/dev/null)"
echo "Node used: $HOSTNAME"
echo "Job ID: $SLURM_JOB_ID"
echo ""

# === CLEANUP ===
echo "Cleaning up temporary files..."
conda deactivate

echo "=== PIPELINE EXECUTION COMPLETE ==="
exit $PIPELINE_EXIT_CODE