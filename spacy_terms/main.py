#!/usr/bin/env python3
"""
Advanced Scientific Term Extraction Pipeline
Comprehensive modular pipeline with AI correction, UMLS/OMOP mapping, and semantic deduplication.
"""

import os
import sys
import argparse
import logging
from pathlib import Path

# This pipeline logs/prints Unicode (checkmarks, emoji) throughout. Windows
# consoles default stdout/stderr to the system codepage (e.g. cp1252), which
# raises UnicodeEncodeError on that output - reconfigure to UTF-8 up front
# rather than special-casing every print/log call.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

# Add src to path for imports
sys.path.append(str(Path(__file__).parent / "src"))

from src.config.settings import get_config, validate_config
from src.pipeline import GlobalPipelineProcessor
from src.utils.model_detector import get_available_model_info

def setup_logging(log_level: str = "INFO", log_file: str = None):
    """Setup logging configuration"""
    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    handlers = [logging.StreamHandler()]
    if log_file:
        handlers.append(logging.FileHandler(log_file))

    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format=log_format,
        handlers=handlers
    )

def main():
    """Main pipeline execution"""
    parser = argparse.ArgumentParser(
        description="Advanced Scientific Term Extraction Pipeline with AI Correction & UMLS/OMOP Mapping"
    )

    # Input/Output arguments
    parser.add_argument("--input_dir", type=str, default="./data", help="Input directory containing documents")
    parser.add_argument("--output_dir", type=str, default="./output", help="Output directory for results")
    parser.add_argument("--max_files", type=int, default=100, help="Maximum number of files to process")
    parser.add_argument("--file_patterns", nargs="+", default=["*.txt", "*.md", "*.csv"], help="File patterns to process")

    # Global Pipeline Settings
    parser.add_argument("--target_terms", type=int, default=2000, help="Target number of final terms")
    parser.add_argument("--run_all_models", action="store_true", help="Run all available sciSpaCy models")

    # Deduplication arguments
    parser.add_argument("--semantic_model", type=str, default="mini-lm", choices=["mini-lm", "nomic", "mpnet"], help="Semantic model for deduplication")
    parser.add_argument("--fuzzy_threshold", type=float, default=0.85, help="Fuzzy matching threshold")
    parser.add_argument("--semantic_threshold", type=float, default=0.9, help="Semantic similarity threshold")

    # Biomedical deduplication arguments
    parser.add_argument("--disable_biomedical_dedup", action="store_true", help="Disable BioMistral biomedical deduplication")
    parser.add_argument("--biomedical_context", type=str, default="microbiome", choices=["microbiome", "biomedical", "clinical", "genomics"], help="Biomedical context for deduplication")

    # Advanced Features
    parser.add_argument("--validate_biomistral", action="store_true", help="Validate terms with BioMistral")
    parser.add_argument("--generate_definitions", action="store_true", help="Generate definitions")
    parser.add_argument("--correct_terms", action="store_true", help="Correct terms with LLM")
    
    # Mapping Features
    parser.add_argument("--map_umls", action="store_true", help="Map to UMLS")
    parser.add_argument("--map_omop", action="store_true", help="Map to OMOP")
    parser.add_argument("--map_bioportal", action="store_true", help="Map to BioPortal")
    
    # BioMistral Settings
    parser.add_argument("--biomistral_model", type=str, default="BioMistral/BioMistral-7B", help="BioMistral model path")
    parser.add_argument("--load_4bit", action="store_true", help="Load BioMistral in 4-bit mode")
    parser.add_argument("--batch_size", type=int, default=32, help="Batch size for inference")

    # Logging
    parser.add_argument("--log_level", type=str, default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    parser.add_argument("--log_file", type=str, help="Log file path")
    
    # Model Listing
    parser.add_argument("--list_available_models", action="store_true", help="List all available scientific spaCy models and exit")
    parser.add_argument("--models", nargs="+", help="Specific spaCy models to use (e.g., en_core_sci_lg en_ner_bc5cdr_md)")
    parser.add_argument("--use_all_available_models", action="store_true", help="Use all available scientific models")
    parser.add_argument("--disable_auto_detect_models", action="store_true", help="Disable automatic model detection")
    
    # Output formats
    parser.add_argument("--output_formats", nargs="+", default=["json", "csv"], choices=["json", "csv", "sqlite"], help="Output formats")

    args = parser.parse_args()

    # Handle listing available models
    if args.list_available_models:
        print("Available Scientific spaCy Models:")
        print("=" * 50)
        model_info = get_available_model_info()
        if model_info:
            for model_name, info in sorted(model_info.items(), key=lambda x: x[1]["priority"]):
                status = "✓" if info["compatible"] else "✗"
                priority = info["priority"]
                model_type = info["type"]
                print(f"{status} [{priority:3d}] {model_name} ({model_type})")
        else:
            print("No scientific models found. Please install sciSpaCy models:")
            print("  pip install https://s3-us-west-2.amazonaws.com/ai2-s2-scispacy/releases/v0.5.1/en_core_sci_lg-0.5.1.tar.gz")
            print("  pip install https://s3-us-west-2.amazonaws.com/ai2-s2-scispacy/releases/v0.5.1/en_ner_bc5cdr_md-0.5.1.tar.gz")
        return 0

    # Setup logging
    setup_logging(args.log_level, args.log_file)
    logger = logging.getLogger(__name__)

    # Load configuration
    config = get_config()

    # Override config with command line arguments
    config.input_dir = args.input_dir
    config.output_dir = args.output_dir
    config.max_files = args.max_files
    config.input_patterns = args.file_patterns
    config.target_final_terms = args.target_terms
    
    # Deduplication
    config.deduplication.default_semantic_model = args.semantic_model
    config.deduplication.fuzzy_threshold = args.fuzzy_threshold
    config.deduplication.semantic_threshold = args.semantic_threshold
    config.deduplication.biomedical_enabled = not args.disable_biomedical_dedup
    config.deduplication.biomedical_context = args.biomedical_context
    
    # Advanced Features
    config.validate_biomistral = args.validate_biomistral
    config.generate_definitions = args.generate_definitions
    config.correct_terms = args.correct_terms
    config.map_umls = args.map_umls
    config.map_omop = args.map_omop
    config.map_bioportal = args.map_bioportal
    
    # BioMistral
    config.biomistral_model = args.biomistral_model
    config.load_4bit = args.load_4bit
    config.batch_size = args.batch_size
    
    # Output formats
    config.output_formats = args.output_formats

    # SpaCy model configuration
    if args.models:
        config.scispacy.preferred_models = args.models
        logger.info(f"Using user-specified models: {args.models}")
        
    if args.run_all_models or args.use_all_available_models:
        config.scispacy.use_all_available = True
        logger.info("Will use all available scientific models")

    config.scispacy.auto_detect_models = not args.disable_auto_detect_models

    # Create output directory
    os.makedirs(config.output_dir, exist_ok=True)

    try:
        # Initialize and run Global Pipeline
        pipeline = GlobalPipelineProcessor(config)
        pipeline.run()
        return 0

    except KeyboardInterrupt:
        logger.info("Pipeline interrupted by user")
        return 1
    except Exception as e:
        logger.error(f"Pipeline failed: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())