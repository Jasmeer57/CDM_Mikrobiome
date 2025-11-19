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
from config.cdm_config import PipelineConfig

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('cdm_pipeline.log'),
        logging.StreamHandler()
    ]
)
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
        '--input-file', '-i',
        required=True,
        help='Input text file to process'
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
        '--biomistral-model',
        default='biomistral-7B',
        help='BioMistral model for biomedical validation (default: biomistral-7B)'
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

    args = parser.parse_args()

    # Set logging level
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

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

    # Validate input file
    input_path = Path(args.input_file)
    if not input_path.exists():
        logger.error(f"Input file not found: {input_path}")
        return 1

    if not input_path.is_file():
        logger.error(f"Input path is not a file: {input_path}")
        return 1

    # Create output directory if needed
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

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
            enable_comprehensive_mapping=args.enable_comprehensive_mapping,
            mapping_confidence_threshold=args.mapping_confidence_threshold
        )
    except Exception as e:
        logger.error(f"Failed to initialize pipeline: {e}")
        return 1

    # Read input file
    try:
        with open(input_path, 'r', encoding='utf-8') as f:
            text = f.read()
        logger.info(f"📄 Loaded file: {input_path} ({len(text)} characters)")
    except Exception as e:
        logger.error(f"Error reading input file: {e}")
        return 1

    # Show configuration
    logger.info(f"🎯 Pipeline Configuration:")
    logger.info(f"   Model: {args.model}")
    logger.info(f"   Base URL: {args.base_url}")
    logger.info(f"   Chunk size: {'auto-adaptive' if args.chunk_size is None else args.chunk_size}")
    logger.info(f"   Max entities: {args.max_entities}")
    logger.info(f"   Min confidence: {args.min_confidence}")
    logger.info(f"   Max workers: {args.max_workers}")
    logger.info(f"   Semantic model: {args.semantic_model}")
    logger.info(f"   Semantic threshold: {args.semantic_threshold}")

    # Run pipeline
    logger.info(f"🚀 Starting CDM entity extraction...")
    success = pipeline.run(
        text=text,
        output_path=args.output,
        chunk_size=args.chunk_size
    )

    if success:
        logger.info(f"✅ Pipeline completed successfully!")
        logger.info(f"💾 Results saved to: {args.output}")
        return 0
    else:
        logger.error(f"❌ Pipeline failed!")
        return 1

if __name__ == "__main__":
    sys.exit(main())