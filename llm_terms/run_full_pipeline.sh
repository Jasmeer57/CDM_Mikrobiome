#!/bin/bash

# Full Pipeline Execution Script
# Runs modular pipeline on all files in papers_txt with all features enabled

# Configuration
INPUT_DIR="../papers_txt"
OUTPUT_FILE="output/full_pipeline_results.json"
MODEL="glm-4.6"
BASE_URL="https://api.z.ai/api/coding/paas/v4/"
API_KEY="x"
BIOPORTAL_KEY="x"

echo "🚀 Starting Full Pipeline Execution on $INPUT_DIR"
echo "Model: $MODEL"
echo "Endpoint: $BASE_URL"
echo "Output: $OUTPUT_FILE"

# Run main.py with all flags
/opt/homebrew/bin/python3.11 main.py \
    --input-file "$INPUT_DIR" \
    --output "$OUTPUT_FILE" \
    --model "$MODEL" \
    --base-url "$BASE_URL" \
    --api-key "$API_KEY" \
    --bioportal-api-key "$BIOPORTAL_KEY" \
    --enable-biomistral \
    --enable-bioportal \
    --enable-comprehensive-mapping \
    --enable-scispacy-linking \
    --enable-correction \
    --enable-llm-correction \
    --verbose

echo "✅ Pipeline execution finished."
