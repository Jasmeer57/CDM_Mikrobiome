#!/bin/bash
#SBATCH --job-name=spacy_ensemble
#SBATCH --output=spacy_ensemble_%j.log
#SBATCH --error=spacy_ensemble_%j.err
#SBATCH --time=24:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --partition=cpu

# Activate Python 3.9 venv with standard SpaCy models
source venv_spacy_39/bin/activate

# Run the pipeline in Ensemble Mode using standard SpaCy models
# - input_dir: papers_txt (your dataset)
# - output_dir: output_spacy_ensemble (separate output folder)
# - ensemble: Run all available models (sm, md, lg, trf)
# - use_spacy_models: Switch to standard SpaCy models
# - skip_mapping: Optional, remove if you want OMOP/OLS mapping
# - validate_biomistral: Optional, add if you want LLM validation (requires GPU partition)

python standalone_scispacy_pipeline.py \
    --input_dir papers_txt \
    --output_dir output_spacy_ensemble \
    --ensemble \
    --use_spacy_models \
    --skip_mapping

echo "Spacy Ensemble Run Complete. Results in output_spacy_ensemble/"
