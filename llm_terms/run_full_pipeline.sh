#!/bin/bash

# Full Pipeline Execution Script
# Runs modular pipeline on all files in papers_txt with all features enabled

# Configuration
INPUT_DIR="../papers_txt"
OUTPUT_FILE="output/full_pipeline_results.json"
MODEL="glm-4.6"
BASE_URL="https://api.z.ai/api/coding/paas/v4/"
API_KEY="REDACTED_API_KEY.XUKb58aJoZho9YlH"
BIOPORTAL_KEY="BIOPORTAL_API_KEY_PLACEHOLDER"
UMLS_KEY="0408aade-b2d9-47ad-a8dc-24f185d4e767"

echo "🚀 Starting Full Pipeline Execution on $INPUT_DIR"
echo "Model: $MODEL"
echo "Output: $OUTPUT_FILE"

# Run the pipeline
# Added --enable-umls-mapping and --enable-scispacy-linking for full coverage
python3 main.py \
    --input-file "$INPUT_DIR" \
    --output "$OUTPUT_FILE" \
    --model "$MODEL" \
    --base-url "$BASE_URL" \
    --api-key "$API_KEY" \
    --bioportal-api-key "$BIOPORTAL_KEY" \
    --umls-api-key "$UMLS_KEY" \
    # --enable-scispacy-linking \
    --enable-umls-mapping \
    --enable-bioportal \
    --enable-comprehensive-mapping \
    --map \
    --enrich \
    --enable-correction \
    --enable-llm-correction \
    --verbose

echo "✅ Pipeline execution finished."
