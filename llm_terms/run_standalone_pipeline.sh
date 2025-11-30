#!/bin/bash
#SBATCH --job-name=llm_terms_cdm_pipeline
#SBATCH --output=logs/llm_terms_%j.out
#SBATCH --error=logs/llm_terms_%j.err
#SBATCH --partition=gpu-mix
#SBATCH --gres=gpu:a100:1
#SBATCH --cpus-per-task=16
#SBATCH --mem=120G
#SBATCH --time=12:00:00
#SBATCH --nodes=1

# === METADATA ===
export SLURM_JOB_START_TIME="$(date)"
echo "=== LLM TERMS CDM ENTITY EXTRACTION PIPELINE ==="
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

# Prevent user's local packages from interfering with the conda environment
export PYTHONPATH=""
export PYTHONNOUSERSITE=1

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

# Install core requirements
echo "Installing core ML/NLP dependencies..."
pip install sentence-transformers==2.2.2
pip install torch==2.1.1
pip install transformers==4.35.2
pip install scikit-learn==1.3.2
pip install einops==0.7.0

# Install scientific computing
echo "Installing scientific computing dependencies..."
pip install numpy==1.24.4
pip install pandas==2.0.3
pip install scipy==1.11.4

# Install web framework
echo "Installing web framework dependencies..."
pip install fastapi==0.104.1
pip install "uvicorn[standard]==0.24.0"
pip install python-multipart==0.0.6

# Install HTTP and networking
echo "Installing HTTP dependencies..."
pip install requests==2.31.0
pip install urllib3==2.1.0
pip install httpx==0.25.2

# Install data processing
echo "Installing data processing dependencies..."
pip install jsonschema==4.20.0
pip install pydantic==2.5.0

# Install biomedical NLP
echo "Installing biomedical NLP dependencies..."
pip install spacy==3.7.2
pip install scispacy>=0.5.4

# Install additional text processing
pip install nltk==3.8.1

# Install database support
pip install sqlalchemy==2.0.23

# Install monitoring and safety
pip install structlog==23.2.0
pip install psutil==5.9.6
pip install python-dotenv==1.0.0

# Install testing dependencies
pip install pytest==7.4.3
pip install pytest-asyncio==0.21.1

# === INSTALL SCIPACY MODELS ===
echo "Installing sciSpaCy models..."
pip install https://github.com/allenai/scispacy/releases/download/v0.5.1/en_core_sci_lg-0.5.1.tar.gz
pip install https://github.com/allenai/scispacy/releases/download/v0.5.1/en_ner_craft_md-0.5.1.tar.gz
pip install https://github.com/allenai/scispacy/releases/download/v0.5.1/en_ner_bc5cdr_md-0.5.1.tar.gz
pip install https://github.com/allenai/scispacy/releases/download/v0.5.1/en_ner_jnlpba_md-0.5.1.tar.gz

# === OPTIONAL: REDIS AND ELASTICSEARCH ===
echo "Installing optional caching and search dependencies..."
pip install redis==5.0.1
pip install elasticsearch==8.11.0

# === DOWNLOAD SPACY MODELS ===
echo "Downloading spaCy models..."
python -m spacy download en_core_web_sm
python -m spacy download en_core_web_md

# === DOWNLOAD NLTK DATA ===
echo "Downloading NLTK data..."
python -c "
import nltk
nltk.download('punkt')
nltk.download('stopwords')
nltk.download('wordnet')
print('NLTK data downloaded successfully')
"

# === API KEYS CONFIGURATION ===
echo "Setting up API keys configuration..."
cat > .env << 'EOF'
# === API KEYS AND CONFIGURATION ===
# Please replace the placeholder values with your actual API keys

# UMLS (Unified Medical Language System) API Key
# Optional: Only needed for direct UMLS API calls
# Not required when using entity linker approach
# Get from: https://uts.nlm.nih.gov/uts/signup-login (if needed)
# UMLS_API_KEY=your_umls_api_key_here

# BioPortal API Key
# Required for BioPortal ontology search
# Get from: https://bioportal.bioontology.org/accounts
BIOPORTAL_API_KEY=your_bioportal_api_key_here

# Hugging Face Token (Optional)
# Required for accessing certain biomedical models
# Get from: https://huggingface.co/settings/tokens
HUGGINGFACE_TOKEN=your_huggingface_token_here

# OpenAI API Key (Optional)
# Required if using OpenAI models instead of local Ollama
# Get from: https://platform.openai.com/api-keys
OPENAI_API_KEY=your_openai_api_key_here

# Anthropic API Key (Optional)
# Required if using Claude models
# Get from: https://console.anthropic.com/
ANTHROPIC_API_KEY=your_anthropic_api_key_here

# Google API Key (Optional)
# Required for Google models or services
# Get from: https://console.cloud.google.com/
GOOGLE_API_KEY=your_google_api_key_here

# === DATABASE CONFIGURATION ===
# Optional: For external database connections

# Redis Configuration (Optional)
# Required if using external Redis for caching
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=your_redis_password_here

# Elasticsearch Configuration (Optional)
# Required if using external Elasticsearch for search
ELASTICSEARCH_HOST=localhost
ELASTICSEARCH_PORT=9200
ELASTICSEARCH_USERNAME=your_elasticsearch_username
ELASTICSEARCH_PASSWORD=your_elasticsearch_password_here

# === ENDPOINT CONFIGURATION ===
# Custom endpoints for various services

# Ollama Endpoint (Local LLM Service)
OLLAMA_BASE_URL=http://localhost:11434

# Custom LLM Endpoint (Optional)
# If using a different LLM service
CUSTOM_LLM_BASE_URL=https://your-llm-service.com/v1
CUSTOM_LLM_API_KEY=your_custom_llm_api_key_here
EOF

echo "✅ .env file created with API key placeholders"
echo ""
echo "⚠️  IMPORTANT: Please update the .env file with your actual API keys before running the pipeline!"
echo "   - UMLS API key: Optional (only needed for direct API calls, not entity linker)"
echo "   - BioPortal API key: Required for ontology search"
echo "   - Hugging Face token: Required for accessing certain biomedical models"
echo ""

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

# === VALIDATE API KEYS ===
echo ""
echo "=== VALIDATING API KEYS ==="
API_KEY_WARNINGS=0

if [ "$UMLS_API_KEY" = "your_umls_api_key_here" ] || [ -z "$UMLS_API_KEY" ]; then
    echo "ℹ️  Info: UMLS API key not configured"
    echo "   - Using entity linker approach instead"
    echo "   - UMLS API key only needed for direct API calls"
fi

if [ "$BIOPORTAL_API_KEY" = "your_bioportal_api_key_here" ] || [ -z "$BIOPORTAL_API_KEY" ]; then
    echo "⚠️  Warning: BioPortal API key not configured"
    echo "   - BioPortal ontology search will be limited"
    echo "   - Get API key from: https://bioportal.bioontology.org/accounts"
    API_KEY_WARNINGS=$((API_KEY_WARNINGS + 1))
fi

if [ "$HUGGINGFACE_TOKEN" = "your_huggingface_token_here" ] || [ -z "$HUGGINGFACE_TOKEN" ]; then
    echo "⚠️  Warning: Hugging Face token not configured"
    echo "   - Some biomedical models may not be accessible"
    echo "   - Get token from: https://huggingface.co/settings/tokens"
    API_KEY_WARNINGS=$((API_KEY_WARNINGS + 1))
fi

if [ $API_KEY_WARNINGS -gt 0 ]; then
    echo ""
    echo "📝 Found $API_KEY_WARNINGS missing API key(s)"
    echo "   Pipeline will run with limited functionality"
    echo "   Update .env file with actual API keys for full features"
else
    echo "✅ All relevant API keys appear to be configured"
fi

# Set flags based on available API keys
ENABLE_UMLS_FLAG=""
ENABLE_BIOPORTAL_FLAG=""
ENABLE_HF_FLAG=""

if [ "$UMLS_API_KEY" != "your_umls_api_key_here" ] && [ -n "$UMLS_API_KEY" ]; then
    ENABLE_UMLS_FLAG="--enable-umls-mapping --umls-api-key $UMLS_API_KEY"
fi

if [ "$BIOPORTAL_API_KEY" != "your_bioportal_api_key_here" ] && [ -n "$BIOPORTAL_API_KEY" ]; then
    ENABLE_BIOPORTAL_FLAG="--enable-bioportal"
fi

if [ "$HUGGINGFACE_TOKEN" != "your_huggingface_token_here" ] && [ -n "$HUGGINGFACE_TOKEN" ]; then
    ENABLE_HF_FLAG="--enable-comprehensive-mapping"
    export HUGGINGFACE_TOKEN="$HUGGINGFACE_TOKEN"
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
echo "  - Semantic threshold: 0.8"
echo "  - Max entities: 200"
echo "  - Min confidence: 0.6"
echo "  - Max workers: 3"
echo "  - BioMistral validation: ENABLED (--enable-biomistral)"
echo "  - Term Correction: ENABLED (--enable-correction)"
echo "  - OMOP mapping: DISABLED (enable with --enable-omop-mapping)"
echo "  - UMLS mapping: DISABLED (enable with --enable-umls-mapping)"
echo ""

# Check if input file exists
INPUT_FILE="./data/input_text.txt"
if [ ! -f "$INPUT_FILE" ]; then
    echo "WARNING: Input file $INPUT_FILE not found!"
    echo "Please place your input text file in the data/ directory or modify the INPUT_FILE variable"
    echo "Available files in data directory:"
    ls -la data/ 2>/dev/null || echo "data directory not found"
    echo ""
    echo "Creating a sample input file for demonstration..."
    mkdir -p data
    cat > "$INPUT_FILE" << 'EOF'
The human gut microbiome plays a crucial role in maintaining overall health.
Recent studies have identified various bacterial species such as Bacteroides fragilis,
Faecalibacterium prausnitzii, and Akkermansia muciniphila as key players in
intestinal homeostasis. These microorganisms produce short-chain fatty acids (SCFAs)
including acetate, propionate, and butyrate, which have anti-inflammatory properties.
Dysbiosis of the gut microbiota has been associated with inflammatory bowel disease (IBD),
Crohn's disease, and ulcerative colitis. Metagenomic sequencing studies have revealed
significant changes in microbial diversity in patients with metabolic syndrome,
type 2 diabetes, and obesity. The gut-brain axis involves complex interactions
between the microbiome and the central nervous system, influencing conditions like
depression and anxiety through the production of neurotransmitters and modulation
of the immune response.
EOF
    echo "Sample input file created at: $INPUT_FILE"
fi

echo ""
echo "Input file: $INPUT_FILE"
echo "File size: $(wc -c < "$INPUT_FILE") characters"
echo "File lines: $(wc -l < "$INPUT_FILE") lines"
echo ""

# === RUN CDM ENTITY EXTRACTION PIPELINE ===
echo "=== STARTING CDM ENTITY EXTRACTION PIPELINE ==="
echo ""

# Basic pipeline run
echo "Running basic CDM entity extraction pipeline..."
python standalone_pipeline.py \
    --input "$INPUT_FILE" \
    --output "../output/cdm_entities.json" \
    --model qwen3:14b \
    --base-url http://localhost:11434 \
    --semantic-model all-MiniLM-L6-v2 \
    --max-workers 3

BASIC_EXIT_CODE=$?

# === ENHANCED PIPELINE RUN (if basic succeeds) ===
if [ $BASIC_EXIT_CODE -eq 0 ]; then
    echo ""
    echo "=== RUNNING ENHANCED PIPELINE WITH BIOMEDICAL FEATURES ==="

    # Enhanced pipeline with biomedical features (adaptive based on available API keys)
    echo "Running enhanced pipeline with available features..."

    # Build command dynamically based on available API keys
    ENHANCED_CMD="python standalone_pipeline.py \
        --input \"$INPUT_FILE\" \
        --output \"../output/cdm_entities_enhanced.json\" \
        --model qwen3:14b \
        --base-url ${OLLAMA_BASE_URL:-http://localhost:11434} \
        --semantic-model all-MiniLM-L6-v2 \
        --max-workers 3 \
        --enable-enhanced \
        --enable-biomistral \
        --enable-correction \
        --enable-omop-mapping"

    # Add UMLS mapping if API key is available
    if [ -n "$ENABLE_UMLS_FLAG" ]; then
        ENHANCED_CMD="$ENHANCED_CMD $ENABLE_UMLS_FLAG"
        echo "✅ Enabling UMLS mapping"
    else
        echo "⚠️  Skipping UMLS mapping (no API key)"
    fi

    # Add BioPortal mapping if API key is available
    if [ -n "$ENABLE_BIOPORTAL_FLAG" ]; then
        ENHANCED_CMD="$ENHANCED_CMD $ENABLE_BIOPORTAL_FLAG"
        echo "✅ Enabling BioPortal mapping"
    else
        echo "⚠️  Skipping BioPortal mapping (no API key)"
    fi

    # Add comprehensive mapping if Hugging Face token is available
    if [ -n "$ENABLE_HF_FLAG" ]; then
        ENHANCED_CMD="$ENHANCED_CMD $ENABLE_HF_FLAG"
        echo "✅ Enabling comprehensive mapping"
    else
        echo "⚠️  Skipping comprehensive mapping (no HF token)"
    fi

    ENHANCED_CMD="$ENHANCED_CMD"

    echo "Executing: $ENHANCED_CMD"
    eval "$ENHANCED_CMD"

    ENHANCED_EXIT_CODE=$?
else
    ENHANCED_EXIT_CODE=$BASIC_EXIT_CODE
fi

# === PIPELINE COMPLETION ANALYSIS ===
echo ""
echo "=== PIPELINE COMPLETION ANALYSIS ==="
echo "Basic pipeline exit code: $BASIC_EXIT_CODE"
echo "Enhanced pipeline exit code: $ENHANCED_EXIT_CODE"

if [ $BASIC_EXIT_CODE -eq 0 ]; then
    echo "✅ SUCCESS: Basic pipeline completed successfully!"

    # Analyze basic results
    echo ""
    echo "=== BASIC RESULTS ANALYSIS ==="

    if [ -f "../output/cdm_entities.json" ]; then
        echo "📄 Basic Output: ../output/cdm_entities.json"
        ENTITY_COUNT=$(grep -c '"entity":' "../output/cdm_entities.json" 2>/dev/null || echo "N/A")
        echo "   - Total entities extracted: $ENTITY_COUNT"

        # Show entity types distribution
        echo "   - Entity type distribution:"
        grep -o '"type": "[^"]*"' "../output/cdm_entities.json" 2>/dev/null | \
            sed 's/"type": "//; s/"//' | sort | uniq -c | sort -nr | head -10 | \
            while read count type; do
                echo "     * $type: $count"
            done
    fi

    if [ $ENHANCED_EXIT_CODE -eq 0 ]; then
        echo ""
        echo "✅ SUCCESS: Enhanced pipeline completed successfully!"

        if [ -f "../output/cdm_entities_enhanced.json" ]; then
            echo "📄 Enhanced Output: ../output/cdm_entities_enhanced.json"
            ENHANCED_ENTITY_COUNT=$(grep -c '"entity":' "../output/cdm_entities_enhanced.json" 2>/dev/null || echo "N/A")
            echo "   - Total entities extracted: $ENHANCED_ENTITY_COUNT"

            # Show mappings count
            OMOP_COUNT=$(grep -c '"omop_concept_id":' "../output/cdm_entities_enhanced.json" 2>/dev/null || echo "0")
            UMLS_COUNT=$(grep -c '"umls_cui":' "../output/cdm_entities_enhanced.json" 2>/dev/null || echo "0")
            echo "   - OMOP mappings: $OMOP_COUNT"
            echo "   - UMLS mappings: $UMLS_COUNT"

            # Show confidence distribution
            echo "   - High confidence entities (>0.8):"
            grep -o '"confidence": [0-9.]*' "../output/cdm_entities_enhanced.json" 2>/dev/null | \
                awk '{if ($2 > 0.8) count++} END {print count " entities"}'
        fi
    fi

    # Generate summary report
    echo ""
    echo "=== GENERATING SUMMARY REPORT ==="
    python << 'EOF'
import json
import sys
from datetime import datetime
from pathlib import Path

def analyze_output(filepath):
    try:
        with open(filepath, 'r') as f:
            data = json.load(f)

        if isinstance(data, list):
            entities = data
        elif isinstance(data, dict) and 'entities' in data:
            entities = data['entities']
        else:
            return None

        analysis = {
            'total_entities': len(entities),
            'entity_types': {},
            'confidence_scores': [],
            'has_mappings': False,
            'omop_mappings': 0,
            'umls_mappings': 0
        }

        for entity in entities:
            # Count entity types
            entity_type = entity.get('type', 'UNKNOWN')
            analysis['entity_types'][entity_type] = analysis['entity_types'].get(entity_type, 0) + 1

            # Collect confidence scores
            if 'confidence' in entity:
                analysis['confidence_scores'].append(entity['confidence'])

            # Count mappings
            if 'omop_concept_id' in entity:
                analysis['omop_mappings'] += 1
                analysis['has_mappings'] = True
            if 'umls_cui' in entity:
                analysis['umls_mappings'] += 1
                analysis['has_mappings'] = True

        # Calculate average confidence
        if analysis['confidence_scores']:
            analysis['avg_confidence'] = sum(analysis['confidence_scores']) / len(analysis['confidence_scores'])

        return analysis

    except Exception as e:
        print(f"Error analyzing {filepath}: {e}")
        return None

# Analyze basic output
basic_analysis = analyze_output("../output/cdm_entities.json")
enhanced_analysis = analyze_output("../output/cdm_entities_enhanced.json")

report = {
    'pipeline_run': datetime.now().isoformat(),
    'basic_pipeline': basic_analysis,
    'enhanced_pipeline': enhanced_analysis
}

with open("../output/pipeline_summary.json", 'w') as f:
    json.dump(report, f, indent=2)

print("📊 Summary report saved to: ../output/pipeline_summary.json")
EOF

else
    echo "❌ FAILED: Pipeline failed with exit code $BASIC_EXIT_CODE"
    echo "Check error log: logs/llm_terms_${SLURM_JOB_ID}.err"
fi

# === PERFORMANCE METRICS ===
echo ""
echo "=== PERFORMANCE METRICS ==="
echo "Job started at: $SLURM_JOB_START_TIME"
echo "Job completed at: $(date)"
if command -v sstat &> /dev/null; then
    echo "Memory usage: $(sstat -j $SLURM_JOB_ID --format=MaxRSS -P -n 2>/dev/null || echo "N/A")"
fi
echo "Node used: $HOSTNAME"
echo "Job ID: $SLURM_JOB_ID"

# === OUTPUT FILES SUMMARY ===
echo ""
echo "=== OUTPUT FILES SUMMARY ==="
echo "Generated files:"
ls -la ../output/ 2>/dev/null | grep -E "\.(json|csv|db|log)$" || echo "No output files found"

# === CLEANUP ===
echo ""
echo "Cleaning up..."
conda deactivate

echo ""
echo "=== LLM TERMS CDM PIPELINE EXECUTION COMPLETE ==="
if [ $BASIC_EXIT_CODE -eq 0 ]; then
    echo "✅ Pipeline completed successfully!"
    exit 0
else
    echo "❌ Pipeline failed!"
    exit $BASIC_EXIT_CODE
fi