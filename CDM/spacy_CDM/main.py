#!/usr/bin/env python3
"""
Microbiome Term Extraction Pipeline - Main Orchestrator
======================================================

Comprehensive modular pipeline that integrates ALL features from the original scripts:
- terms.py: Advanced sciSpaCy term extraction with P1-P12 fixes
- do.py: AI-powered term cleaning and correction
- umls.py: Comprehensive UMLS mapping and ontology integration
- convert.py: OMOP vocabulary preprocessing and conversion
- mapping.py: OMOP concept mapping with fuzzy matching

Features:
- Multi-layer deduplication (Exact -> Fuzzy -> Semantic)
- Configurable semantic models (MiniLM, Nomic, MPNet)
- Complete modular architecture
- Production-ready error handling
- Comprehensive logging and statistics
- CLI interface with all parameters

Usage:
    python main.py --input_dir ./data/input --output_dir ./data/output
    python main.py --config config.yaml --semantic-model nomic
    python main.py --help
"""

import sys
import time
import argparse
from pathlib import Path
from typing import Dict, List, Optional, Any

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from config.settings import PipelineConfig
from modules.terms_extractor import TermsExtractor
from modules.deduplication import ComprehensiveDeduplicator
from modules.umls_mapper import UMLSMapper
from utils.data_loader import DataLoader
from utils.exporter import ResultsExporter

# Import other modules (they will be created)
try:
    from modules.ai_cleaner import AITermCleaner
    AI_CLEANING_AVAILABLE = True
except ImportError:
    AI_CLEANING_AVAILABLE = False

try:
    from modules.omop_processor import OMOPProcessor
    OMOP_AVAILABLE = True
except ImportError:
    OMOP_AVAILABLE = False

import logging

logger = logging.getLogger(__name__)


class MicrobiomePipeline:
    """
    Main pipeline orchestrator that integrates all modules.
    Executes pipeline stages in sequence with comprehensive error handling.
    """

    def __init__(self, config: PipelineConfig):
        self.config = config
        self.pipeline_stats = {
            'start_time': None,
            'end_time': None,
            'total_time': 0,
            'stage_times': {},
            'stage_results': {}
        }

        # Initialize modules
        self._initialize_modules()

    def _initialize_modules(self):
        """Initialize all pipeline modules."""
        logger.info("🔧 INITIALIZING PIPELINE MODULES")
        logger.info("=" * 80)

        # Core modules
        self.data_loader = DataLoader(self.config)
        self.results_exporter = ResultsExporter(self.config)

        # Processing modules
        self.terms_extractor = TermsExtractor(
            self.config.scispacy,
            self.config.filtering
        )
        self.deduplicator = ComprehensiveDeduplicator(self.config.deduplication)

        # Optional modules
        if self.config.enable_umls_mapping:
            self.umls_mapper = UMLSMapper(self.config.umls)
        else:
            self.umls_mapper = None

        if self.config.enable_ai_cleaning and AI_CLEANING_AVAILABLE:
            self.ai_cleaner = AITermCleaner(self.config.ai_model)
        else:
            self.ai_cleaner = None

        if self.config.enable_omop_mapping and OMOP_AVAILABLE:
            self.omop_processor = OMOPProcessor(self.config.omop)
        else:
            self.omop_processor = None

        logger.info("✅ All modules initialized successfully")
        logger.info("=" * 80)

    def run(self, input_dir: Optional[str] = None, output_dir: Optional[str] = None) -> Dict[str, Any]:
        """
        Run the complete pipeline with all stages.

        Args:
            input_dir: Override input directory
            output_dir: Override output directory

        Returns:
            Complete pipeline results
        """
        # Override config if provided
        if input_dir:
            self.config.input_dir = input_dir
        if output_dir:
            self.config.output_dir = output_dir

        self.pipeline_stats['start_time'] = time.time()

        logger.info("🚀 STARTING MICROBIOME TERM EXTRACTION PIPELINE")
        logger.info("=" * 80)
        logger.info(f"📁 Input directory: {self.config.input_dir}")
        logger.info(f"📁 Output directory: {self.config.output_dir}")
        logger.info(f"🧠 Semantic model: {self.config.deduplication.semantic_model_choice}")
        logger.info(f"🔢 Fuzzy threshold: {self.config.deduplication.fuzzy_threshold}")
        logger.info(f"🎯 Semantic threshold: {self.config.deduplication.semantic_threshold}")

        try:
            # Stage 1: Load data
            documents = self._stage_load_data()

            # Stage 2: Extract terms
            extracted_terms = self._stage_extract_terms(documents)

            # Stage 3: Deduplicate terms
            deduplicated_terms = self._stage_deduplicate_terms(extracted_terms)

            # Stage 4: UMLS mapping (optional)
            umls_results = self._stage_umls_mapping(deduplicated_terms)

            # Stage 5: AI cleaning (optional)
            cleaned_terms = self._stage_ai_cleaning(deduplicated_terms)

            # Stage 6: OMOP mapping (optional)
            omop_results = self._stage_omop_mapping(cleaned_terms)

            # Stage 7: Export results
            final_results = self._stage_export_results(
                cleaned_terms, umls_results, omop_results
            )

            # Calculate final statistics
            self.pipeline_stats['end_time'] = time.time()
            self.pipeline_stats['total_time'] = (
                self.pipeline_stats['end_time'] - self.pipeline_stats['start_time']
            )

            # Final summary
            self._print_final_summary(final_results)

            return final_results

        except Exception as e:
            logger.error(f"❌ Pipeline failed: {e}")
            if not self.config.continue_on_error:
                raise
            return {'error': str(e), 'partial_results': self.pipeline_stats['stage_results']}

    def _stage_load_data(self) -> List[Dict[str, Any]]:
        """Stage 1: Load input documents."""
        logger.info("\n📋 STAGE 1: LOADING DATA")
        logger.info("-" * 40)

        stage_start = time.time()
        documents = self.data_loader.load_documents(self.config.input_dir)

        self.pipeline_stats['stage_times']['data_loading'] = time.time() - stage_start
        self.pipeline_stats['stage_results']['documents'] = len(documents)

        logger.info(f"✅ Loaded {len(documents)} documents")
        return documents

    def _stage_extract_terms(self, documents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Stage 2: Extract terms using sciSpaCy models."""
        logger.info("\n📋 STAGE 2: TERM EXTRACTION")
        logger.info("-" * 40)

        if not self.config.enable_term_extraction:
            logger.info("⏭️  Term extraction disabled")
            return []

        stage_start = time.time()
        all_terms = {}

        for doc in documents:
            logger.info(f"🔍 Processing: {doc['file_id']}")
            extracted_terms = self.terms_extractor.process_text(
                doc['content'],
                doc['file_id']
            )
            all_terms.update(extracted_terms)

        # Convert to list and sort
        terms_list = list(all_terms.values())
        terms_list = self.terms_extractor.get_sorted_terms(
            min_frequency=self.config.filtering.min_frequency,
            top_k=self.config.filtering.top_k
        )

        self.pipeline_stats['stage_times']['term_extraction'] = time.time() - stage_start
        self.pipeline_stats['stage_results']['extracted_terms'] = len(terms_list)

        logger.info(f"✅ Extracted {len(terms_list)} unique terms")
        return terms_list

    def _stage_deduplicate_terms(self, terms: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Stage 3: Multi-layer deduplication."""
        logger.info("\n📋 STAGE 3: DEDUPLICATION")
        logger.info("-" * 40)

        if not terms:
            logger.info("⏭️  No terms to deduplicate")
            return []

        stage_start = time.time()

        # Apply comprehensive deduplication
        deduplicated_terms = self.deduplicator.deduplicate(terms)

        self.pipeline_stats['stage_times']['deduplication'] = time.time() - stage_start
        self.pipeline_stats['stage_results']['deduplicated_terms'] = len(deduplicated_terms)

        logger.info(f"✅ Deduplicated to {len(deduplicated_terms)} terms")
        return deduplicated_terms

    def _stage_umls_mapping(self, terms: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Stage 4: UMLS mapping (optional)."""
        logger.info("\n📋 STAGE 4: UMLS MAPPING")
        logger.info("-" * 40)

        if not self.config.enable_umls_mapping or not self.umls_mapper:
            logger.info("⏭️  UMLS mapping disabled")
            return {}

        stage_start = time.time()

        # Extract term texts for mapping
        term_texts = [term['term'] for term in terms]
        umls_results = self.umls_mapper.map_terms_comprehensive(term_texts)

        self.pipeline_stats['stage_times']['umls_mapping'] = time.time() - stage_start
        self.pipeline_stats['stage_results']['umls_mappings'] = len([
            r for r in umls_results.get('combined_results', {}).values()
            if r.get('has_any_match', False)
        ])

        logger.info(f"✅ Mapped {self.pipeline_stats['stage_results']['umls_mappings']} terms to UMLS")
        return umls_results

    def _stage_ai_cleaning(self, terms: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Stage 5: AI-powered term cleaning (optional)."""
        logger.info("\n📋 STAGE 5: AI CLEANING")
        logger.info("-" * 40)

        if not self.config.enable_ai_cleaning or not self.ai_cleaner:
            logger.info("⏭️  AI cleaning disabled")
            return terms

        stage_start = time.time()

        # Apply AI cleaning
        cleaned_terms = self.ai_cleaner.clean_terms(terms)

        self.pipeline_stats['stage_times']['ai_cleaning'] = time.time() - stage_start
        self.pipeline_stats['stage_results']['cleaned_terms'] = len(cleaned_terms)

        logger.info(f"✅ Cleaned {len(cleaned_terms)} terms with AI")
        return cleaned_terms

    def _stage_omop_mapping(self, terms: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Stage 6: OMOP mapping (optional)."""
        logger.info("\n📋 STAGE 6: OMOP MAPPING")
        logger.info("-" * 40)

        if not self.config.enable_omop_mapping or not self.omop_processor:
            logger.info("⏭️  OMOP mapping disabled")
            return {}

        stage_start = time.time()

        # Apply OMOP mapping
        omop_results = self.omop_processor.map_terms_to_omop(terms)

        self.pipeline_stats['stage_times']['omop_mapping'] = time.time() - stage_start
        self.pipeline_stats['stage_results']['omop_mappings'] = len([
            r for r in omop_results.values() if r.get('omop_concept_id')
        ])

        logger.info(f"✅ Mapped {self.pipeline_stats['stage_results']['omop_mappings']} terms to OMOP")
        return omop_results

    def _stage_export_results(self, terms: List[Dict[str, Any]], umls_results: Dict[str, Any],
                             omop_results: Dict[str, Any]) -> Dict[str, Any]:
        """Stage 7: Export comprehensive results."""
        logger.info("\n📋 STAGE 7: EXPORTING RESULTS")
        logger.info("-" * 40)

        stage_start = time.time()

        # Export all results
        exported_files = self.results_exporter.export_comprehensive_results(
            terms=terms,
            umls_results=umls_results,
            omop_results=omop_results,
            pipeline_stats=self.pipeline_stats,
            config=self.config
        )

        self.pipeline_stats['stage_times']['export'] = time.time() - stage_start
        self.pipeline_stats['stage_results']['exported_files'] = len(exported_files)

        logger.info(f"✅ Exported {len(exported_files)} result files")
        return {
            'terms': terms,
            'umls_results': umls_results,
            'omop_results': omop_results,
            'exported_files': exported_files,
            'pipeline_stats': self.pipeline_stats
        }

    def _print_final_summary(self, results: Dict[str, Any]):
        """Print final pipeline summary."""
        logger.info("\n" + "=" * 80)
        logger.info("🎉 PIPELINE COMPLETED SUCCESSFULLY!")
        logger.info("=" * 80)

        stats = self.pipeline_stats
        logger.info(f"⏱️  Total processing time: {stats['total_time']:.2f}s")
        logger.info(f"📊 Documents processed: {stats['stage_results'].get('documents', 0)}")
        logger.info(f"🔤 Terms extracted: {stats['stage_results'].get('extracted_terms', 0)}")
        logger.info(f"🔄 Terms deduplicated: {stats['stage_results'].get('deduplicated_terms', 0)}")
        logger.info(f"🏥 UMLS mappings: {stats['stage_results'].get('umls_mappings', 0)}")
        logger.info(f"🤖 AI cleaned terms: {stats['stage_results'].get('cleaned_terms', 0)}")
        logger.info(f"📋 OMOP mappings: {stats['stage_results'].get('omop_mappings', 0)}")
        logger.info(f"📄 Files exported: {stats['stage_results'].get('exported_files', 0)}")

        # Stage times
        logger.info("\n⏱️  Stage Processing Times:")
        for stage, stage_time in stats['stage_times'].items():
            logger.info(f"   {stage.replace('_', ' ').title()}: {stage_time:.2f}s")

        logger.info("=" * 80)


def create_argument_parser() -> argparse.ArgumentParser:
    """Create comprehensive command line argument parser."""
    parser = argparse.ArgumentParser(
        description="Microbiome Term Extraction Pipeline",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        epilog="""
Examples:
  python main.py --input_dir ./data/input --output_dir ./data/output
  python main.py --config config.yaml --semantic-model nomic --top-k 500
  python main.py --enable-umls --enable-ai-cleaning --enable-omop
  python main.py --fuzzy-threshold 85 --semantic-threshold 0.8
        """
    )

    # Input/Output arguments
    parser.add_argument("--input-dir", "-i", help="Input directory containing documents")
    parser.add_argument("--output-dir", "-o", help="Output directory for results")
    parser.add_argument("--config", "-c", help="Configuration file (JSON/YAML)")

    # Processing arguments
    parser.add_argument("--max-files", type=int, help="Maximum number of files to process")
    parser.add_argument("--min-frequency", type=int, help="Minimum term frequency")
    parser.add_argument("--top-k", type=int, help="Maximum number of terms to output")

    # Semantic model selection
    parser.add_argument(
        "--semantic-model", choices=["mini-lm", "nomic", "mpnet"],
        default="mini-lm", help="Semantic model for deduplication"
    )

    # Deduplication parameters
    parser.add_argument("--fuzzy-threshold", type=int, help="Fuzzy deduplication threshold (0-100)")
    parser.add_argument("--semantic-threshold", type=float, help="Semantic deduplication threshold (0-1)")

    # Stage enable/disable flags
    parser.add_argument("--enable-term-extraction", action="store_true", default=True, help="Enable term extraction")
    parser.add_argument("--enable-fuzzy-deduplication", action="store_true", default=True, help="Enable fuzzy deduplication")
    parser.add_argument("--enable-semantic-deduplication", action="store_true", default=True, help="Enable semantic deduplication")
    parser.add_argument("--enable-umls", action="store_true", help="Enable UMLS mapping")
    parser.add_argument("--enable-ai-cleaning", action="store_true", help="Enable AI-powered cleaning")
    parser.add_argument("--enable-omop", action="store_true", help="Enable OMOP mapping")

    # Disable flags
    parser.add_argument("--disable-term-extraction", action="store_true", help="Disable term extraction")
    parser.add_argument("--disable-fuzzy-deduplication", action="store_true", help="Disable fuzzy deduplication")
    parser.add_argument("--disable-semantic-deduplication", action="store_true", help="Disable semantic deduplication")

    # Configuration overrides
    parser.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR"], default="INFO", help="Logging level")
    parser.add_argument("--log-file", help="Log file path")
    parser.add_argument("--batch-size", type=int, help="Batch size for processing")
    parser.add_argument("--n-process", type=int, help="Number of processes for parallel processing")

    return parser


def main():
    """Main entry point."""
    parser = create_argument_parser()
    args = parser.parse_args()

    # Load configuration
    if args.config:
        config = PipelineConfig.from_file(args.config)
    else:
        config = PipelineConfig()

    # Override config with command line arguments
    config_updates = {}

    if args.input_dir:
        config_updates['input_dir'] = args.input_dir
    if args.output_dir:
        config_updates['output_dir'] = args.output_dir
    if args.max_files:
        config_updates['max_files'] = args.max_files
    if args.min_frequency:
        config_updates['filtering'] = config.filtering
        config.filtering.min_frequency = args.min_frequency
    if args.top_k:
        config_updates['filtering'] = config.filtering
        config.filtering.top_k = args.top_k
    if args.log_level:
        config_updates['log_level'] = args.log_level
    if args.log_file:
        config_updates['log_file'] = args.log_file
    if args.batch_size:
        config_updates['scispacy'] = config.scispacy
        config.scispacy.batch_size = args.batch_size
    if args.n_process:
        config_updates['scispacy'] = config.scispacy
        config.scispacy.n_process = args.n_process

    # Semantic model
    if args.semantic_model:
        config_updates['deduplication'] = config.deduplication
        config.deduplication.semantic_model_choice = args.semantic_model

    # Deduplication thresholds
    if args.fuzzy_threshold:
        config_updates['deduplication'] = config.deduplication
        config.deduplication.fuzzy_threshold = args.fuzzy_threshold
    if args.semantic_threshold:
        config_updates['deduplication'] = config.deduplication
        config.deduplication.semantic_threshold = args.semantic_threshold

    # Stage enable/disable
    config.enable_term_extraction = args.enable_term_extraction and not args.disable_term_extraction
    config.enable_fuzzy_deduplication = args.enable_fuzzy_deduplication and not args.disable_fuzzy_deduplication
    config.enable_semantic_deduplication = args.enable_semantic_deduplication and not args.disable_semantic_deduplication
    config.enable_umls_mapping = args.enable_umls
    config.enable_ai_cleaning = args.enable_ai_cleaning
    config.enable_omop_mapping = args.enable_omop

    config.update(**config_updates)

    # Validate configuration
    if not Path(config.input_dir).exists():
        logger.error(f"❌ Input directory does not exist: {config.input_dir}")
        sys.exit(1)

    # Run pipeline
    try:
        pipeline = MicrobiomePipeline(config)
        results = pipeline.run()

        # Print summary
        if 'error' in results:
            logger.error(f"❌ Pipeline completed with errors: {results['error']}")
            sys.exit(1)
        else:
            logger.info("🎉 Pipeline completed successfully!")
            sys.exit(0)

    except KeyboardInterrupt:
        logger.info("⏹️  Pipeline interrupted by user")
        sys.exit(130)
    except Exception as e:
        logger.error(f"❌ Pipeline failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()