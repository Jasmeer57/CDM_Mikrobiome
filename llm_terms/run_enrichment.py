import json
import logging
import sys
from pathlib import Path
import time

# Add current directory to path
sys.path.insert(0, str(Path(__file__).parent))

from core.pipeline import CDMEntityPipeline
from config.cdm_config import PipelineConfig

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('enrichment.log')
    ]
)
logger = logging.getLogger(__name__)

def main():
    # Configuration
    INPUT_FILE = "output/Common_Data_Model_LLMs.json"
    OUTPUT_FILE = "output/Common_Data_Model_LLMs_Enriched.json"
    
    API_KEY = "REDACTED_API_KEY.XUKb58aJoZho9YlH"
    BASE_URL = "https://api.z.ai/api/coding/paas/v4/"
    MODEL = "glm-4.6"
    
    logger.info(f"🚀 Starting LLM Enrichment with {MODEL}")
    
    # Initialize Pipeline
    # We enable biomistral (for type correction) but pass our LLM client
    config = PipelineConfig(
        max_entities=100000,
        min_confidence=0.0
    )
    
    pipeline = CDMEntityPipeline(
        model=MODEL,
        base_url=BASE_URL,
        api_key=API_KEY,
        config=config,
        enable_biomistral=True, # For type correction
        enable_llm_correction=True
    )
    
    # 1. Load Data
    logger.info(f"📂 Loading data from {INPUT_FILE}")
    with open(INPUT_FILE, 'r') as f:
        data = json.load(f)
        
    # Flatten entities if structured
    if isinstance(data, dict) and 'results' in data and 'cdm_entities' in data['results']:
        entities_map = data['results']['cdm_entities']
        all_entities = []
        for etype, elist in entities_map.items():
            for e in elist:
                e['entity_type'] = etype
                all_entities.append(e)
        entities = all_entities
    else:
        logger.error("❌ Unexpected file format")
        return

    logger.info(f"Loaded {len(entities)} entities for enhancement")

    # 2. Correct Labels (Entity Types)
    # This uses the LLM to fix misclassified entities
    logger.info("🧬 Correcting Entity Labels (Types)...")
    # pipeline.biomistral_validator is initialized because we passed enable_biomistral=True
    # correct_entity_types batches requests to the LLM
    entities = pipeline.biomistral_validator.correct_entity_types(entities)
    
    # 3. Enrich Definitions, Aliases, Examples
    # This function is on the pipeline class and handles its own batching/saving
    # But it takes a file path. We can modify it or just save our current progress and call it.
    # To be safe and reuse the logic, let's save intermediate and call it.
    INTERMEDIATE_FILE = "output/temp_enrichment_input.json"
    
    # We need to save in the format enrich_definitions expects (a list or the structured dict)
    # Based on core/pipeline.py line 576, it handles structured.
    # So let's construct a temporary structured object
    temp_results = {
        'metadata': data.get('metadata', {}),
        'results': {
            'cdm_entities': {} # We'll fill this later or just pass list if it supports list
        }
    }
    # Actually enrich_definitions supports list (line 586)
    with open(INTERMEDIATE_FILE, 'w') as f:
        json.dump(entities, f)
        
    logger.info("📚 Enriching Definitions, Aliases, and Examples...")
    # We call the method, passing the file path
    # It will update the file in-place
    pipeline.enrich_definitions(INTERMEDIATE_FILE)
    
    # Reload enriched entities
    with open(INTERMEDIATE_FILE, 'r') as f:
        entities = json.load(f)

    # 4. Score Better
    logger.info("📊 Calculating Microbiome Relevance Scores...")
    entities = pipeline.relevance_scorer.score_entities(entities)
    
    # 5. Save Final
    logger.info(f"💾 Saving final results to {OUTPUT_FILE}")
    pipeline.save_results(entities, OUTPUT_FILE)
    logger.info("✅ Enrichment Complete!")

if __name__ == "__main__":
    main()
