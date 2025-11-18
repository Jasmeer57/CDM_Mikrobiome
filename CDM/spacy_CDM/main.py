#!/usr/bin/env python3
"""
Main orchestrator for the Scientific Terms Extraction Pipeline
Uses modular architecture with configurable semantic deduplication
"""

import sys
import logging
import argparse
import time
from pathlib import Path
from typing import Dict, Any, List

# Add src to Python path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from src.config.settings import PipelineConfig
from src.modules.terms_extractor import TermsExtractor
from src.modules.deduplication import ComprehensiveDeduplicator
from src.utils.data_loader import DataLoader
from src.utils.output_writer import OutputWriter


def setup_logging(log_dir: str = "logs") -> None:
    """Setup logging configuration"""
    Path(log_dir).mkdir(exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(f"{log_dir}/pipeline_{time.strftime('%Y%m%d_%H%M%S')}.log"),
            logging.StreamHandler(sys.stdout)
        ]
    )


def parse_arguments() -> Dict[str, Any]:
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description="Scientific Terms Extraction Pipeline with Multi-layer Deduplication",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic usage with default settings
  python main.py --input_dir ./data

  # Specify semantic model and thresholds
  python main.py --input_dir ./data --semantic_model nomic --fuzzy_threshold 0.9 --semantic_threshold 0.85

  # Use specific sciSpaCy models
  python main.py --input_dir ./data --scispacy_models en_core_sci_lg en_ner_bc5cdr_md

  # Limit processing
  python main.py --input_dir ./data --max_files 5 --max_docs 10

  # Parallel processing
  python main.py --input_dir ./data --parallel --workers 8
        """
    )

    # Input/Output
    parser.add_argument("--input_dir", type=str, default="data",
                       help="Input directory containing documents (default: data)")
    parser.add_argument("--output_dir", type=str, default="output",
                       help="Output directory for results (default: output)")

    # Deduplication settings
    parser.add_argument("--semantic_model", type=str, default="mini-lm",
                       choices=["mini-lm", "nomic", "mpnet"],
                       help="Semantic model for deduplication (default: mini-lm)")
    parser.add_argument("--fuzzy_threshold", type=float, default=0.85,
                       help="Fuzzy matching threshold (0.0-1.0, default: 0.85)")
    parser.add_argument("--semantic_threshold", type=float, default=0.9,
                       help="Semantic similarity threshold (0.0-1.0, default: 0.9)")

    # sciSpaCy models
    parser.add_argument("--scispacy_models", nargs="+",
                       default=["en_core_sci_lg", "en_ner_craft_md", "en_ner_bc5cdr_md", "en_ner_jnlpba_md"],
                       help="List of sciSpaCy models to use (default: all 4 models)")

    # Processing limits
    parser.add_argument("--max_files", type=int, default=-1,
                       help="Maximum number of files to process (-1 for unlimited, default: -1)")
    parser.add_argument("--max_docs", type=int, default=-1,
                       help="Maximum number of documents per file (-1 for unlimited, default: -1)")

    # Performance
    parser.add_argument("--parallel", action="store_true",
                       help="Enable parallel processing")
    parser.add_argument("--workers", type=int, default=4,
                       help="Number of worker processes for parallel processing (default: 4)")

    # Quality filters
    parser.add_argument("--min_confidence", type=float, default=0.1,
                       help="Minimum confidence score (0.0-1.0, default: 0.1)")
    parser.add_argument("--min_science_score", type=float, default=0.5,
                       help="Minimum science relevance score (0.0-1.0, default: 0.5)")

    # Output
    parser.add_argument("--output_formats", nargs="+",
                       default=["json", "csv", "sqlite"],
                       choices=["json", "csv", "sqlite"],
                       help="Output formats to generate (default: json csv sqlite)")
    parser.add_argument("--no_timestamp", action="store_true",
                       help="Don't add timestamp to output filenames")

    return vars(parser.parse_args())


def print_banner():
    """Print pipeline banner"""
    banner = """
╔══════════════════════════════════════════════════════════════╗
║         Scientific Terms Extraction Pipeline v1.0.0         ║
║     Multi-layer Deduplication with Semantic Analysis        ║
╚══════════════════════════════════════════════════════════════╝
    """
    print(banner)


def print_configuration(config: PipelineConfig, args: Dict[str, Any]):
    """Print pipeline configuration"""
    print("\n🔧 PIPELINE CONFIGURATION")
    print("=" * 50)
    print(f"Input directory: {config.input_dir}")
    print(f"Output directory: {config.output_dir}")
    print(f"sciSpaCy models: {', '.join(config.scispacy.models)}")
    print(f"Semantic model: {config.deduplication.semantic_model_choice}")
    print(f"Fuzzy threshold: {config.deduplication.fuzzy_threshold}")
    print(f"Semantic threshold: {config.deduplication.semantic_threshold}")
    print(f"Max files: {config.max_files}")
    print(f"Max docs per file: {config.max_docs_per_file}")
    print(f"Parallel processing: {config.parallel_processing}")
    if config.parallel_processing:
        print(f"Workers: {config.num_workers}")
    print()


def validate_configuration(config: PipelineConfig) -> bool:
    """Validate pipeline configuration"""
    # Check input directory
    if not Path(config.input_dir).exists():
        print(f"❌ Input directory does not exist: {config.input_dir}")
        return False

    # Check thresholds
    if not 0 <= config.deduplication.fuzzy_threshold <= 1:
        print("❌ Fuzzy threshold must be between 0.0 and 1.0")
        return False

    if not 0 <= config.deduplication.semantic_threshold <= 1:
        print("❌ Semantic threshold must be between 0.0 and 1.0")
        return False

    if not 0 <= config.processing.min_confidence <= 1:
        print("❌ Minimum confidence must be between 0.0 and 1.0")
        return False

    if not 0 <= config.processing.min_science_score <= 1:
        print("❌ Minimum science score must be between 0.0 and 1.0")
        return False

    return True


def process_document(doc: Dict[str, Any], extractor: TermsExtractor, config: PipelineConfig, logger: logging.Logger) -> List[Dict[str, Any]]:
    """Process a single document"""
    logger.info(f"📄 Processing document: {doc['file_id']}")
    logger.info(f"   Content length: {len(doc['content'])} characters")

    # Extract terms using all configured models
    terms = extractor.extract_terms(doc['content'])
    logger.info(f"   Raw terms extracted: {len(terms)}")

    # Filter by confidence and science score
    filtered_terms = []
    for term in terms:
        if (term.get('confidence', 0) >= config.processing.min_confidence and
            term.get('science_score', 0) >= config.processing.min_science_score):
            filtered_terms.append(term)

    logger.info(f"   Terms after filtering: {len(filtered_terms)}")
    return filtered_terms


def main():
    """Main pipeline execution"""
    print_banner()

    # Parse arguments
    args = parse_arguments()

    # Setup logging
    setup_logging(args.get('output_dir', 'logs'))
    logger = logging.getLogger(__name__)

    # Create configuration
    config = PipelineConfig.from_args(args)
    print_configuration(config, args)

    # Validate configuration
    if not validate_configuration(config):
        sys.exit(1)

    logger.info("🚀 Starting Scientific Terms Extraction Pipeline")
    start_time = time.time()

    try:
        # Initialize components
        logger.info("📦 Initializing pipeline components...")

        # Data loader
        data_loader = DataLoader(config)
        logger.info("✅ Data loader initialized")

        # Terms extractor
        extractor = TermsExtractor(config.scispacy)
        model_summary = extractor.get_model_summary()
        logger.info(f"✅ Terms extractor initialized with {model_summary['models_count']} models")

        # Deduplicator
        deduplicator = ComprehensiveDeduplicator(config.deduplication)
        logger.info("✅ Deduplicator initialized")

        # Output writer
        output_writer = OutputWriter(config)
        logger.info("✅ Output writer initialized")

        # Load documents
        logger.info(f"📂 Loading documents from {config.input_dir}")
        documents = list(data_loader.load_documents(config.input_dir, config.max_files))

        if not documents:
            logger.error("❌ No documents found to process")
            sys.exit(1)

        logger.info(f"✅ Loaded {len(documents)} documents")

        # Process documents
        all_terms = []
        total_docs_processed = 0

        for doc in documents:
            try:
                terms = process_document(doc, extractor, config, logger)
                all_terms.extend(terms)
                total_docs_processed += 1

                # Check if we've hit the max documents limit
                if config.max_docs_per_file > 0 and total_docs_processed >= config.max_docs_per_file:
                    logger.info(f"Reached maximum documents limit: {config.max_docs_per_file}")
                    break

            except Exception as e:
                logger.error(f"❌ Error processing document {doc['file_id']}: {e}")
                continue

        logger.info(f"📊 Total terms extracted from all documents: {len(all_terms)}")

        # Deduplication
        logger.info("🔄 Running multi-layer deduplication...")
        deduplicated_terms = deduplicator.deduplicate(all_terms)

        # Get deduplication statistics
        dedup_stats = deduplicator.get_deduplication_stats(all_terms, deduplicated_terms)
        logger.info(f"✅ Deduplication complete: {dedup_stats['reduction_count']} duplicates removed")

        # Generate outputs
        logger.info("💾 Generating output files...")
        outputs = output_writer.write_all_formats(
            deduplicated_terms,
            {'deduplication_stats': dedup_stats},
            base_filename=f"scispacy_comprehensive_{time.strftime('%Y%m%d_%H%M%S')}" if not args.get('no_timestamp') else "scispacy_comprehensive"
        )

        # Summary
        elapsed_time = time.time() - start_time
        logger.info("🎉 PIPELINE COMPLETED SUCCESSFULLY!")
        logger.info(f"   Total processing time: {elapsed_time:.2f} seconds")
        logger.info(f"   Documents processed: {total_docs_processed}")
        logger.info(f"   Final terms: {len(deduplicated_terms)}")
        logger.info(f"   Output files:")
        for format_name, file_path in outputs.items():
            logger.info(f"      {format_name.upper()}: {file_path}")

        # Print final summary
        print("\n🎯 PIPELINE RESULTS")
        print("=" * 50)
        print(f"✅ Processing completed in {elapsed_time:.2f} seconds")
        print(f"✅ {total_docs_processed} documents processed")
        print(f"✅ {len(deduplicated_terms)} unique scientific terms extracted")
        print(f"✅ {dedup_stats['reduction_percentage']:.1f}% reduction through deduplication")
        print(f"✅ Results saved to: {config.output_dir}")

        # Show sample terms
        if deduplicated_terms:
            print(f"\n🏆 TOP 10 EXTRACTED TERMS:")
            print("-" * 50)
            top_terms = sorted(deduplicated_terms, key=lambda x: x.get('confidence', 0), reverse=True)[:10]
            for i, term in enumerate(top_terms, 1):
                confidence = term.get('confidence', 0)
                science_score = term.get('science_score', 0)
                models = term.get('models_used', [term.get('model', 'unknown')])
                print(f"{i:2d}. {term['term']}")
                print(f"     Confidence: {confidence:.3f} | Science: {science_score:.3f}")
                print(f"     Models: {', '.join(models)}")
                print()

    except Exception as e:
        logger.error(f"❌ Pipeline failed: {e}")
        raise


if __name__ == "__main__":
    main()