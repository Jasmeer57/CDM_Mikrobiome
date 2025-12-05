#!/usr/bin/env python3
"""
CDM Entity Extraction Pipeline CLI
=================================
Extract structured biomedical entities for Microbiome Common Data Model
"""

import argparse
import logging
import sys
from pathlib import Path

# Add current directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from core.pipeline import CDMEntityPipeline
from core.config_manager import ConfigManager
from config.cdm_config import PipelineConfig
import json

class JsonFormatter(logging.Formatter):
    def format(self, record):
        log_record = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name
        }
        if record.exc_info:
            log_record["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_record)

# Configure logging
def setup_logging(verbose=False, log_format='text', log_file='cdm_pipeline.log'):
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO if not verbose else logging.DEBUG)
    
    # Clear existing handlers
    root_logger.handlers = []
    
    # Create handlers
    file_handler = logging.FileHandler(log_file)
    stream_handler = logging.StreamHandler()
    
    if log_format == 'json':
        formatter = JsonFormatter()
    else:
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        
    file_handler.setFormatter(formatter)
    stream_handler.setFormatter(formatter)
    
    root_logger.addHandler(file_handler)
    root_logger.addHandler(stream_handler)

logger = logging.getLogger(__name__)

def main():
    parser = argparse.ArgumentParser(
        description='Extract CDM-structured biomedical entities from text',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
CDM Entity Types:
  GENE      - Gene names, genetic markers, gene families
  PROTEIN   - Proteins, enzymes, receptors, signaling molecules
  ORGANISM  - Bacteria, archaea, fungi, viruses, taxa
  DISEASE   - Diseases, conditions, disorders
  CHEMICAL  - Metabolites, SCFAs, drugs, compounds
  DNA_RNA   - Genetic material, sequences, genes
  CELL_TYPE - Cell types, immune cells

Examples:
  %(prog)s --input-file research_paper.txt
  %(prog)s --input-file data.txt --model qwen3:8b --output results.json
  %(prog)s --input-file text.txt --chunk-size 3000 --verbose
        """
    )

    parser.add_argument(
        '--config',
        help='Path to JSON configuration file'
    )

    parser.add_argument(
        '--log-format',
        choices=['text', 'json'],
        default='text',
        help='Log output format (default: text)'
    )

    parser.add_argument(
        '--input-file', '-i',
        required=False, # Changed to False because it might be in config
        help='Input text file or directory to process'
    )

    parser.add_argument(
        '--output', '-o',
        default='./cdm_entities.json',
        help='Output JSON file path (default: ./cdm_entities.json)'
    )

    parser.add_argument(
        '--model', '-m',
        default='qwen3:8b',
        help='LLM model to use (default: qwen3:8b)'
    )

    parser.add_argument(
        '--base-url',
        default='http://localhost:11434',
        help='LLM service base URL (default: http://localhost:11434)'
    )

    parser.add_argument(
        '--api-key',
        default='EMPTY',
        help='API Key for OpenAI/vLLM (default: EMPTY)'
    )

    parser.add_argument(
        '--chunk-size', '-c',
        type=int,
        default=None,
        help='Chunk size in characters (default: auto-adaptive based on file size)'
    )

    parser.add_argument(
        '--max-entities', '--max-terms',
        type=int,
        default=200,
        help='Maximum number of entities to extract (default: 200)'
    )

    parser.add_argument(
        '--semantic-model',
        default='all-MiniLM-L6-v2',
        help='Sentence transformer model for semantic deduplication (default: all-MiniLM-L6-v2)'
    )

    parser.add_argument(
        '--semantic-threshold',
        type=float,
        default=0.8,
        help='Semantic similarity threshold for deduplication (default: 0.8)'
    )

    parser.add_argument(
        '--enable-biomistral',
        action='store_true',
        help='Enable BioMistral biomedical validation and correction'
    )

    parser.add_argument(
        '--enable-correction',
        action='store_true',
        help='Enable MiniLM term correction'
    )

    parser.add_argument(
        '--enable-llm-correction',
        action='store_true',
        help='Enable LLM-based type correction'
    )

    parser.add_argument(
        '--biomistral-model',
        default='biomistral-7B',
        help='BioMistral model for biomedical validation (default: biomistral-7B)'
    )

    parser.add_argument(
        '--enable-biomistral-deduplication',
        action='store_true',
        help='Enable BioMistral biomedical deduplication for contextual duplicates'
    )

    parser.add_argument(
        '--biomistral-dedup-model',
        default='biomistral:7b',
        help='BioMistral model for deduplication (default: biomistral:7b)'
    )

    parser.add_argument(
        '--enable-omop-mapping',
        action='store_true',
        help='Enable OMOP CDM standard vocabulary mapping'
    )

    parser.add_argument(
        '--enable-umls-mapping',
        action='store_true',
        help='Enable UMLS biomedical concept mapping'
    )

    parser.add_argument(
        '--umls-api-key',
        help='UMLS API key for biomedical concept mapping'
    )

    parser.add_argument(
        '--enable-bioportal',
        action='store_true',
        help='Enable BioPortal ontology search'
    )

    parser.add_argument(
        '--enable-ols',
        action='store_true',
        help='Enable OLS (Ontology Lookup Service) mapping'
    )

    parser.add_argument(
        '--enable-comprehensive-mapping',
        action='store_true',
        help='Enable comprehensive mapping (OMOP + UMLS + BioPortal + OLS)'
    )

    parser.add_argument(
        '--mapping-confidence-threshold',
        type=float,
        default=0.7,
        help='Minimum confidence threshold for mappings (default: 0.7)'
    )

    parser.add_argument(
        '--min-confidence',
        type=float,
        default=0.6,
        help='Minimum confidence threshold (default: 0.6)'
    )

    parser.add_argument(
        '--max-workers',
        type=int,
        default=3,
        help='Maximum parallel workers (default: 3)'
    )

    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Enable verbose logging'
    )

    parser.add_argument(
        '--list-models',
        action='store_true',
        help='List available models and exit'
    )

    parser.add_argument(
        '--bioportal-api-key',
        help='BioPortal API key for ontology search'
    )

    parser.add_argument(
        '--provider',
        choices=['ollama', 'openai', 'huggingface', 'zlm'],
        default='ollama',
        help='LLM provider type (default: ollama)'
    )

    parser.add_argument(
        '--enable-scispacy-linking',
        action='store_true',
        help='Enable SciSpaCy for UMLS linking (requires scispacy installed)'
    )

    parser.add_argument(
        '--consolidate',
        action='store_true',
        help='Consolidate processed files from input directory to output file'
    )

    parser.add_argument(
        '--map',
        action='store_true',
        help='Apply mappings to input file'
    )

    parser.add_argument(
        '--enrich',
        action='store_true',
        help='Enrich definitions for input file'
    )

    # Parse args with config support
    args = ConfigManager.setup_parser_with_config(parser)

    # Setup logging
    setup_logging(args.verbose, args.log_format)

    # Handle list models
    if args.list_models:
        try:
            from core.llm_client import LLMClient
            client = LLMClient(base_url=args.base_url)
            models = client.get_available_models()
            print("Available models:")
            for model in models:
                print(f"  - {model}")
            return 0
        except Exception as e:
            logger.error(f"Failed to list models: {e}")
            return 1

    # Validate input file (must be checked after config merge)
    if not args.input_file:
        parser.error("the following arguments are required: --input-file/-i (or in config file)")

    # Configure pipeline
    config = PipelineConfig(
        default_model=args.model,
        default_base_url=args.base_url,
        max_workers=args.max_workers,
        max_entities=args.max_entities,
        min_confidence=args.min_confidence
    )

    # Initialize pipeline with comprehensive features
    try:
        pipeline = CDMEntityPipeline(
            model=args.model,
            base_url=args.base_url,
            config=config,
            semantic_model=args.semantic_model,
            semantic_threshold=args.semantic_threshold,
            enable_biomistral=args.enable_biomistral,
            biomistral_model=args.biomistral_model,
            enable_omop_mapping=args.enable_omop_mapping,
            enable_umls_mapping=args.enable_umls_mapping,
            umls_api_key=args.umls_api_key,
            bioportal_api_key=args.bioportal_api_key,
            enable_comprehensive_mapping=args.enable_comprehensive_mapping,
            enable_scispacy_linking=args.enable_scispacy_linking,
            mapping_confidence_threshold=args.mapping_confidence_threshold,
            enable_correction=args.enable_correction,
            enable_llm_correction=args.enable_llm_correction,
            api_key=args.api_key
        )
    except Exception as e:
        logger.error(f"Failed to initialize pipeline: {e}")
        return 1

    # Handle Modes
    if args.consolidate:
        pipeline.consolidate_results(args.input_file, args.output)
        return 0

    if args.map:
        pipeline.apply_mappings_to_file(args.input_file)
        return 0

    if args.enrich:
        pipeline.enrich_definitions(args.input_file)
        return 0

    # Default: Run Extraction
    # Validate input file
    input_path = Path(args.input_file)
    if not input_path.exists():
        logger.error(f"Input path not found: {input_path}")
        return 1

    # Determine input files
    input_files = []
    if input_path.is_file():
        input_files = [input_path]
    elif input_path.is_dir():
        input_files = list(input_path.glob("*.txt"))
        logger.info(f"📂 Found {len(input_files)} text files in {input_path}")
        if not input_files:
            logger.error(f"No .txt files found in directory: {input_path}")
            return 1
    else:
        logger.error(f"Invalid input path: {input_path}")
        return 1

    # Create output directory if needed
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Process files
    all_entities = []
    text_stats_agg = {"character_count": 0, "word_count": 0}

    # Check for checkpoint
    checkpoint_file = output_path.parent / "checkpoint_entities.json"
    processed_files_set = set()
    
    if checkpoint_file.exists():
        try:
            import json
            with open(checkpoint_file, 'r') as f:
                checkpoint_data = json.load(f)
                all_entities = checkpoint_data.get('entities', [])
                processed_files_set = set(checkpoint_data.get('processed_files', []))
                text_stats_agg = checkpoint_data.get('stats', text_stats_agg)
                logger.info(f"🔄 Resuming from checkpoint: {len(processed_files_set)} files processed, {len(all_entities)} entities loaded.")
        except Exception as e:
            logger.error(f"Failed to load checkpoint: {e}")

    for i, file_path in enumerate(input_files):
        if file_path.name in processed_files_set:
            logger.info(f"⏭️ Skipping already processed file {i+1}/{len(input_files)}: {file_path.name}")
            continue

        logger.info(f"📄 Processing file {i+1}/{len(input_files)}: {file_path.name}")
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                text = f.read()
            
            # Update stats
            text_stats_agg["character_count"] += len(text)
            text_stats_agg["word_count"] += len(text.split())
            
            # Extract entities
            file_entities = pipeline.extract_entities(text, args.chunk_size)
            
            # Add source file info
            for entity in file_entities:
                entity['source_file'] = file_path.name
                
            all_entities.extend(file_entities)
            processed_files_set.add(file_path.name)
            
            # Save checkpoint every 5 files
            if len(processed_files_set) % 5 == 0:
                try:
                    import json
                    checkpoint_data = {
                        'entities': all_entities,
                        'processed_files': list(processed_files_set),
                        'stats': text_stats_agg
                    }
                    with open(checkpoint_file, 'w') as f:
                        json.dump(checkpoint_data, f, indent=2)
                    logger.info(f"💾 Checkpoint saved: {len(processed_files_set)} files processed.")
                except Exception as e:
                    logger.error(f"Failed to save checkpoint: {e}")
            
        except Exception as e:
            logger.error(f"Error processing file {file_path}: {e}")
            continue

    # Final aggregation and deduplication across all files
    if len(input_files) > 1:
        logger.info(f"🔄 Aggregating and deduplicating {len(all_entities)} entities from {len(input_files)} files...")
        # Re-run post-processing on aggregated list
        all_entities = pipeline.post_process_entities(all_entities, use_semantic=True)

    # Save aggregated results
    pipeline.save_results(all_entities, args.output, text_stats_agg)
    
    logger.info(f"✅ Pipeline completed. Total unique entities: {len(all_entities)}")
    return 0

if __name__ == "__main__":
    sys.exit(main())