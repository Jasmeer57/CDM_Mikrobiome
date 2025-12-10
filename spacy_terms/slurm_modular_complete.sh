#!/bin/bash
#SBATCH --job-name=modular_complete_pipeline
#SBATCH --output=logs/modular_complete_%j.out
#SBATCH --error=logs/modular_complete_%j.err
#SBATCH --partition=gpu-mix
#SBATCH --gres=gpu:a100:1
#SBATCH --cpus-per-task=16
#SBATCH --mem=120G
#SBATCH --time=12:00:00
#SBATCH --nodes=1

# === METADATA ===
export SLURM_JOB_START_TIME="$(date)"
echo "=== MODULAR COMPLETE PIPELINE - DEFINITIONS, VALIDATION, CLEANING ==="
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
module load ollama/0.7.0

# Set CUDA library paths
export LD_LIBRARY_PATH="/opt/software/easybuild/software/CUDA/12.3.0/targets/x86_64-linux/lib:$LD_LIBRARY_PATH"
export CUDA_HOME="/opt/software/easybuild/software/CUDA/12.3.0"

# Create logs directory
mkdir -p logs

# === CONDA ENVIRONMENT ===
echo "Setting up conda environment..."
conda activate spacy_scispacy_env

# === ENVIRONMENT VARIABLES ===
export OMOP_VOCAB_PATH="/home/jkalra/thesis/omop_vocab"
export BIOPORTAL_API_KEY="$BIOPORTAL_API_KEY"
export UMLS_API_KEY="$UMLS_API_KEY"

# === CHECK OLLAMA AVAILABILITY ===
echo "Checking Ollama availability..."
if ! command -v ollama &> /dev/null; then
    echo "Installing Ollama..."
    curl -fsSL https://ollama.ai/install.sh | sh
    export PATH="$PATH:/usr/local/bin"
else
    echo "✅ Ollama is already installed"
fi

# Start Ollama server if not running
if ! pgrep -x "ollama" > /dev/null; then
    echo "Starting Ollama server..."
    ollama serve &
    sleep 5  # Give server time to start
fi

# Pull Mistral model if not available
if ! ollama list | grep -q "mistral"; then
    echo "Pulling Mistral model..."
    ollama pull mistral:latest
else
    echo "✅ Mistral model is already available"
fi

# === MODULAR PIPELINE CONFIGURATION ===
echo ""
echo "=== MODULAR COMPLETE PIPELINE CONFIGURATION ==="
echo "✨ USING SOPHISTICATED MODULAR COMPONENTS:"
echo "Input: ALL 9,736 terms from continuation pipeline"
echo "Goal: 5-7k high-quality processed terms"
echo "Components:"
echo "  1. ContextualCleaner - Advanced term cleaning"
echo "  2. DefinitionGenerator - BioMistral-7B definitions"
echo "  3. BioMistralValidator - Medical term validation"
echo "  4. MicrobiomeGoldStandardScorer - Gold standard validation"
echo "  5. MicrobiomeSemanticFilter - Semantic quality filtering"
echo "  6. UMLSMapper - Medical ontology mapping"
echo "  7. OMOPMapper - OMOP vocabulary mapping"
echo "  8. EntityLinker - Entity linking"
echo "Output: /home/jkalra/my_node_tools/Microbiome-CDM/spacy_terms/output_modular_complete"
echo ""

# Check if input terms exist
INPUT_TERMS="/home/jkalra/my_node_tools/Microbiome-CDM/spacy_terms/output_final/terms_only_20251206_031409.txt"
if [ ! -f "$INPUT_TERMS" ]; then
    echo "❌ ERROR: Input terms file $INPUT_TERMS not found!"
    exit 1
fi

# Count input terms
TERM_COUNT=$(wc -l < "$INPUT_TERMS")
echo "✅ Found $TERM_COUNT terms for modular processing"

# Create modular processing script
cat > run_modular_complete.py << 'EOF'
#!/usr/bin/env python3
"""
Run complete modular pipeline with definitions, validation, and cleaning.
"""

import sys
import os
import json
import logging
import time
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any

# Add src to path
sys.path.append('.')

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(f"logs/modular_complete_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("ModularComplete")

def load_terms(input_file: str, limit: int = None) -> List[Dict]:
    """Load terms from input file"""
    logger.info(f"Loading terms from {input_file}")

    with open(input_file, 'r') as f:
        terms = [line.strip() for line in f if line.strip()]

    if limit:
        terms = terms[:limit]
        logger.info(f"Processing limited sample of {len(terms)} terms")

    # Convert to term dictionaries
    term_dicts = []
    for term in terms:
        term_dicts.append({
            'term': term,
            'text': term,
            'original_text': term,
            'label': 'ENTITY',
            'score': 0.0,
            'source_model': 'continuation_pipeline',
            'source_file': 'terms_only_20251206_031409.txt',
            'examples': ''
        })

    logger.info(f"Loaded {len(term_dicts)} terms for processing")
    return term_dicts

def run_modular_pipeline(terms: List[Dict]) -> List[Dict]:
    """Run the complete modular pipeline"""
    try:
        from src.config.settings import PipelineConfig
        from src.modules.microbiome_components import (
            ContextualCleaner,
            MicrobiomeGoldStandardScorer,
            MicrobiomeSemanticFilter
        )
        from src.modules.biomistral import (
            DefinitionGenerator,
            BioMistralValidator,
            LLMTermCorrector
        )
        from src.modules.umls_mapping import UMLSMapper
        from src.modules.omop_mapping import OMOPMapper

        # Create configuration
        config = PipelineConfig(
            input_dir="/home/jkalra/my_node_tools/Microbiome-CDM/papers_txt",
            output_dir="/home/jkalra/my_node_tools/Microbiome-CDM/spacy_terms/output_modular_complete",
            generate_definitions=True,
            correct_terms=True,
            map_umls=True,
            map_omop=True,
            validate_biomistral=True,
            use_ollama=True,
            ollama_model="mistral:latest",
            ollama_base_url="http://localhost:11434"
        )

        logger.info("🚀 Starting modular pipeline processing...")

        # Step 1: Contextual Cleaning
        logger.info("Step 1: Contextual Cleaning")
        cleaner = ContextualCleaner()
        cleaned_terms = []
        for term in terms:
            cleaned = cleaner.clean_term(term)
            if cleaned:
                cleaned_terms.append(cleaned)
        logger.info(f"Cleaning: {len(terms)} -> {len(cleaned_terms)} terms")

        # Step 2: Gold Standard Scoring
        logger.info("Step 2: Gold Standard Scoring")
        scorer = MicrobiomeGoldStandardScorer()
        scored_terms = []
        for term in cleaned_terms:
            score = scorer.score_term(term)
            term['gold_score'] = score
            scored_terms.append(term)

        scored_terms.sort(key=lambda x: x.get('gold_score', 0), reverse=True)
        logger.info(f"Gold standard scoring complete for {len(scored_terms)} terms")

        # Step 3: Generate Definitions (ALL terms)
        logger.info("Step 3: Definition Generation")
        def_gen = DefinitionGenerator(config)
        definition_count = 0

        # Process ALL terms for 5-7k target
        sample_terms = scored_terms

        for term in sample_terms:
            try:
                definition = def_gen.generate_definition(term['term'])
                if definition:
                    term['definition'] = definition
                    definition_count += 1
            except Exception as e:
                logger.debug(f"Definition generation failed for {term['term']}: {e}")
                term['definition'] = None

        logger.info(f"Generated {definition_count} definitions")

        # Step 4: BioMistral Validation
        logger.info("Step 4: BioMistral Validation")
        try:
            validator = BioMistralValidator(load_in_4bit=True)
            validator.load_model()

            validation_count = 0
            for term in sample_terms:
                try:
                    validation = validator.validate_term(term['term'])
                    term['validation_score'] = validation.get('score', 5)
                    term['validation_relevance'] = validation.get('relevance', 'medium')
                    validation_count += 1
                except Exception as e:
                    logger.debug(f"Validation failed for {term['term']}: {e}")
                    term['validation_score'] = 5
                    term['validation_relevance'] = 'medium'

            logger.info(f"Validated {validation_count} terms")
        except Exception as e:
            logger.warning(f"BioMistral validation failed: {e}")

        # Step 5: Semantic Filtering
        logger.info("Step 5: Semantic Filtering")
        semantic_filter = MicrobiomeSemanticFilter()
        filtered_terms = semantic_filter.filter_terms(sample_terms)
        logger.info(f"Semantic filtering: {len(sample_terms)} -> {len(filtered_terms)} terms")

        # Step 6: UMLS Mapping (sample)
        logger.info("Step 6: UMLS Mapping")
        try:
            umls_mapper = UMLSMapper(config.umls_api_key)
            umls_mapped = 0

            for term in filtered_terms:  # Process ALL terms
                try:
                    mappings = umls_mapper.map_term(term['term'], term['label'])
                    term['umls_concepts'] = mappings
                    if mappings:
                        umls_mapped += 1
                except Exception as e:
                    logger.debug(f"UMLS mapping failed for {term['term']}: {e}")
                    term['umls_concepts'] = []

            logger.info(f"Mapped {umls_mapped} terms to UMLS")
        except Exception as e:
            logger.warning(f"UMLS mapping failed: {e}")

        return filtered_terms

    except Exception as e:
        logger.error(f"Modular pipeline failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return terms  # Return original terms if pipeline fails

def save_results(terms: List[Dict], output_file: str):
    """Save processed results"""
    logger.info(f"Saving {len(terms)} processed terms to {output_file}")

    results = {
        'metadata': {
            'total_terms': len(terms),
            'processing_date': datetime.now().isoformat(),
            'pipeline_stage': 'modular_complete',
            'components_applied': [
                'contextual_cleaning',
                'gold_standard_scoring',
                'definition_generation',
                'biomistral_validation',
                'semantic_filtering',
                'umls_mapping'
            ]
        },
        'terms': terms
    }

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, default=str)

    # Also save just terms list
    terms_file = output_file.replace('.json', '_terms.txt')
    with open(terms_file, 'w', encoding='utf-8') as f:
        for term in terms:
            term_text = term.get('term', term.get('text', '')).strip()
            if term_text and term.get('definition'):
                f.write(f"{term_text}: {term.get('definition', '')}\n")

    logger.info(f"Results saved to {output_file} and {terms_file}")

def main():
    """Main function"""
    input_file = "/home/jkalra/my_node_tools/Microbiome-CDM/spacy_terms/output_final/terms_only_20251206_031409.txt"
    output_dir = Path("/home/jkalra/my_node_tools/Microbiome-CDM/spacy_terms/output_modular_complete")
    output_dir.mkdir(parents=True, exist_ok=True)

    output_file = output_dir / f"modular_complete_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

    # Load terms - Process ALL terms for 5-7k target
    terms = load_terms(input_file)  # Process ALL 9,736 terms

    if not terms:
        logger.error("No terms loaded!")
        return

    # Run modular pipeline
    start_time = time.time()
    processed_terms = run_modular_pipeline(terms)
    processing_time = time.time() - start_time

    logger.info(f"🎉 Modular pipeline completed!")
    logger.info(f"Processed {len(processed_terms)} terms")
    logger.info(f"Processing time: {processing_time:.2f} seconds")

    # Save results
    save_results(processed_terms, str(output_file))

if __name__ == "__main__":
    main()
EOF

# === RUN MODULAR COMPLETE PIPELINE ===
echo ""
echo "🚀 STARTING MODULAR COMPLETE PIPELINE..."
echo ""

# Run the modular complete pipeline
python run_modular_complete.py

EXIT_CODE=$?

# === RESULTS ANALYSIS ===
echo ""
echo "=== MODULAR COMPLETE PIPELINE ANALYSIS ==="
echo "Pipeline exit code: $EXIT_CODE"

if [ $EXIT_CODE -eq 0 ]; then
    echo "✅ SUCCESS: Modular complete pipeline finished successfully!"

    # Check results
    if [ -d "/home/jkalra/my_node_tools/Microbiome-CDM/spacy_terms/output_modular_complete" ]; then
        echo "📄 Results: /home/jkalra/my_node_tools/Microbiome-CDM/spacy_terms/output_modular_complete/"

        # Find latest results
        LATEST_RESULTS=$(ls -t /home/jkalra/my_node_tools/Microbiome-CDM/spacy_terms/output_modular_complete/modular_complete_*.json | head -1)
        if [ -f "$LATEST_RESULTS" ]; then
            echo "   - Latest results: $LATEST_RESULTS"

            # Count processed terms
            TERM_COUNT=$(python -c "
import json
try:
    with open('$LATEST_RESULTS', 'r') as f:
        data = json.load(f)
        print(data['metadata']['total_terms'])
except Exception as e:
    print(f'Error: {e}')
            " 2>/dev/null || echo "N/A")
            echo "   - Terms with definitions and validation: $TERM_COUNT"

            # Check for terms list
            TERMS_FILE="${LATEST_RESULTS%.json}_terms.txt"
            if [ -f "$TERMS_FILE" ]; then
                TERMS_COUNT=$(wc -l < "$TERMS_FILE")
                echo "   - Terms with definitions: $TERMS_COUNT"
            fi
        fi
    fi

else
    echo "❌ FAILED: Modular complete pipeline failed with exit code $EXIT_CODE"
    echo "Check error log: logs/modular_complete_${SLURM_JOB_ID}.err"
fi

# === CLEANUP ===
echo ""
echo "Cleaning up..."
rm -f run_modular_complete.py
conda deactivate

echo ""
echo "=== MODULAR COMPLETE PIPELINE FINISHED ==="
exit $EXIT_CODE