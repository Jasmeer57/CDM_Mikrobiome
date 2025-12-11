import json
import logging
import argparse
import sys
from pathlib import Path

# Add current directory to path
sys.path.insert(0, str(Path(__file__).parent))

from core.pipeline import CDMEntityPipeline
from config.cdm_config import PipelineConfig
from mappers.mapping import ComprehensiveMapper

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def main():
    parser = argparse.ArgumentParser(description='Process checkpoint entities with full mapping and enrichment')
    parser.add_argument('--checkpoint', default='output/checkpoint_entities.json', help='Path to checkpoint file')
    parser.add_argument('--output', default='output/full_pipeline_results_merged.json', help='Output file path')
    parser.add_argument('--bioportal-key', help='BioPortal API Key')
    parser.add_argument('--umls-key', help='UMLS API Key')
    
    args = parser.parse_args()
    
    # Load checkpoint
    logger.info(f"Loading checkpoint from {args.checkpoint}...")
    try:
        with open(args.checkpoint, 'r') as f:
            data = json.load(f)
            entities = data.get('entities', [])
            logger.info(f"Loaded {len(entities)} entities from checkpoint")
    except Exception as e:
        logger.error(f"Failed to load checkpoint: {e}")
        return

    # Configure pipeline with HIGH max_entities
    config = PipelineConfig(
        max_entities=100000,  # CRITICAL: Set high enough to hold all entities
        min_confidence=0.0    # Don't filter out existing low confidence ones if user wants them all
    )
    
    # Initialize Pipeline (we only need post-processing capabilities)
    # We cheat a bit by creating the pipeline but only using post_process components manually 
    # OR we can instantiate the components directly.
    # Actually, pipeline.post_process_entities is specifically designed for this!
    
    pipeline = CDMEntityPipeline(config=config)
    
    # Enable features based on what we want
    pipeline.enable_comprehensive_mapping = False # DISABLED per user request (API limits)
    # pipeline.enable_biomistral = True # Optional, might be slow for 21k
    pipeline.enable_correction = True # MiniLM correction (Local, fast)
    pipeline.enable_llm_correction = False # Too expensive
    
    # Initialize Mapper explicitly to pass keys
    # pipeline.comprehensive_mapper = ComprehensiveMapper(
    #     umls_api_key=args.umls_key,
    #     bioportal_api_key=args.bioportal_key,
    #     use_local_omop=True,
    #     omop_vocab_dir="vocab" # Assuming default
    # )

    # Post-process
    # Note: post_process_entities calls filter/dedup/map/score
    logger.info("Starting post-processing (Mapping, Enrichment, Deduplication)...")
    processed_entities = pipeline.post_process_entities(entities, use_semantic=True)
    
    # Save
    logger.info(f"Saving {len(processed_entities)} processed entities to {args.output}...")
    pipeline.save_results(processed_entities, args.output)
    logger.info("Done!")

if __name__ == "__main__":
    main()
