#!/bin/bash
#SBATCH --job-name=scispacy_pipeline
#SBATCH --output=logs/pipeline_%j.log
#SBATCH --error=logs/pipeline_%j.err
#SBATCH --time=24:00:00
#SBATCH --mem=32G
#SBATCH --cpus-per-task=4
#SBATCH --partition=general

# Load Python module if needed (adjust based on your cluster)
# module load python/3.9

# Activate virtual environment
source venv_scispacy/bin/activate

# Create logs directory
mkdir -p logs

# Run the pipeline in ENSEMBLE mode
# This will run ALL 8 models, collect all terms, and deduplicate them into a single file
python standalone_scispacy_pipeline.py \
    --input_dir papers_txt \
    --output_dir output_ensemble_full \
    --ensemble \
    --skip_mapping  # Remove this flag if you want mapping/ranking enabled

echo "Ensemble pipeline execution completed."
