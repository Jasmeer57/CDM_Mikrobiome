#!/bin/bash
# Standalone Pipeline Script for Cluster Execution (BioMistral)
# This script runs the python pipeline with all advanced features enabled.

# Ensure strictly configured environment
set -e

# Activate Virtual Environment (Adjust path if needed for your cluster)
source venv_scispacy/bin/activate

# Run the pipeline
echo "Starting pipeline execution on CLUSTER with BioMistral..."
python standalone_scispacy_pipeline.py \
    --input_dir "papers_txt" \
    --output_dir "output_full" \
    --ensemble \
    --workers 16 \
    --generate_definitions \
    --correct_terms \
    --definition_model "BioMistral/BioMistral-7B" \
    --map_umls \
    --map_omop \
    --map_bioportal \
    --batch_size 32 \
    --load_4bit
