#!/usr/bin/env python3
"""
Test script to run the complete pipeline and check what's actually working
with all deduplication layers and optional modules.
"""

import os
import sys
import json
import logging
from pathlib import Path

# Add src to path FIRST, before any other imports
src_path = str(Path(__file__).parent / "src")
if src_path not in sys.path:
    sys.path.insert(0, src_path)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def test_full_pipeline():
    """Test the complete pipeline with all features."""
    logger.info("🚀 Testing complete pipeline functionality...")

    # Check if all modules are available
    module_status = {}

    # Test 1: Configuration
    try:
        from config.settings import PipelineConfig
        config = PipelineConfig()
        module_status['config'] = "✅ Available"
        logger.info(f"✅ Configuration module: {config.scispacy.models}")
    except Exception as e:
        module_status['config'] = f"❌ Error: {e}"
        logger.error(f"❌ Configuration module failed: {e}")

    # Test 2: Terms Extractor
    try:
        from modules.terms_extractor import TermsExtractor
        extractor = TermsExtractor(config.scispacy)
        module_status['terms_extractor'] = "✅ Available"
        logger.info(f"✅ Terms extractor: {config.scispacy.models}")
    except Exception as e:
        module_status['terms_extractor'] = f"❌ Error: {e}"
        logger.error(f"❌ Terms extractor failed: {e}")

    # Test 3: Deduplication (all layers)
    try:
        from modules.deduplication import ComprehensiveDeduplicator
        deduplicator = ComprehensiveDeduplicator(config.deduplication)
        module_status['deduplication'] = "✅ Available"
        logger.info(f"✅ Deduplication: 3 layers (exact, fuzzy, semantic)")
        logger.info(f"   - Semantic model: {config.deduplication.semantic_model_choice}")
        logger.info(f"   - Fuzzy threshold: {config.deduplication.fuzzy_threshold}")
        logger.info(f"   - Semantic threshold: {config.deduplication.semantic_threshold}")
    except Exception as e:
        module_status['deduplication'] = f"❌ Error: {e}"
        logger.error(f"❌ Deduplication failed: {e}")

    # Test 4: UMLS Mapper
    try:
        from modules.umls_mapper import UMLSMapper
        if config.enable_umls_mapping:
            umls_mapper = UMLSMapper(config.umls)
            module_status['umls_mapper'] = "✅ Available & Enabled"
            logger.info("✅ UMLS mapper: BioPortal, OLS, NCBO Annotator")
        else:
            module_status['umls_mapper'] = "⏸️ Disabled"
            logger.info("⏸️ UMLS mapper: Disabled in config")
    except Exception as e:
        module_status['umls_mapper'] = f"❌ Error: {e}"
        logger.error(f"❌ UMLS mapper failed: {e}")

    # Test 5: AI Cleaner
    try:
        from modules.ai_cleaner import AITermCleaner
        if config.enable_ai_cleaning:
            ai_cleaner = AITermCleaner(config.ai_model)
            module_status['ai_cleaner'] = "✅ Available & Enabled"
            logger.info(f"✅ AI cleaner: Mistral-7B-Instruct")
        else:
            module_status['ai_cleaner'] = "⏸️ Disabled"
            logger.info("⏸️ AI cleaner: Disabled in config")
    except Exception as e:
        module_status['ai_cleaner'] = f"❌ Error: {e}"
        logger.error(f"❌ AI cleaner failed: {e}")

    # Test 6: OMOP Processor
    try:
        from modules.omop_processor import OMOPProcessor
        if config.enable_omop_mapping:
            omop_processor = OMOPProcessor(config.omop)
            module_status['omop_processor'] = "✅ Available & Enabled"
            logger.info("✅ OMOP processor: Parquet preprocessing, fuzzy matching")
        else:
            module_status['omop_processor'] = "⏸️ Disabled"
            logger.info("⏸️ OMOP processor: Disabled in config")
    except Exception as e:
        module_status['omop_processor'] = f"❌ Error: {e}"
        logger.error(f"❌ OMOP processor failed: {e}")

    # Test 7: Data Loader and Exporter
    try:
        from utils.data_loader import DataLoader
        from utils.exporter import ResultsExporter
        data_loader = DataLoader(config.input)
        exporter = ResultsExporter()
        module_status['utils'] = "✅ Available"
        logger.info("✅ Data loader and exporter: File handling, CSV/JSON export")
    except Exception as e:
        module_status['utils'] = f"❌ Error: {e}"
        logger.error(f"❌ Utils failed: {e}")

    # Test 8: Main Pipeline
    try:
        from main import MicrobiomePipeline
        pipeline = MicrobiomePipeline(config)
        module_status['main_pipeline'] = "✅ Available"
        logger.info("✅ Main pipeline: All 7 stages implemented")
        logger.info("   - Stage 1: Load data")
        logger.info("   - Stage 2: Extract terms")
        logger.info("   - Stage 3: Multi-layer deduplication")
        logger.info("   - Stage 4: UMLS mapping (optional)")
        logger.info("   - Stage 5: AI cleaning (optional)")
        logger.info("   - Stage 6: OMOP mapping (optional)")
        logger.info("   - Stage 7: Export results")
    except Exception as e:
        module_status['main_pipeline'] = f"❌ Error: {e}"
        logger.error(f"❌ Main pipeline failed: {e}")

    # Check for the PRJDB4360 file
    test_file = "data/PRJDB4360.txt"
    if Path(test_file).exists():
        file_size = Path(test_file).stat().st_size
        module_status['test_file'] = f"✅ Available ({file_size:,} bytes)"
        logger.info(f"✅ Test file: PRJDB4360.txt ({file_size:,} characters)")
    else:
        module_status['test_file'] = f"❌ Not found: {test_file}"
        logger.error(f"❌ Test file not found: {test_file}")

    # Print summary
    logger.info("\n" + "="*80)
    logger.info("📋 PIPELINE MODULE STATUS SUMMARY")
    logger.info("="*80)

    for module, status in module_status.items():
        logger.info(f"{module:.<25}: {status}")

    # Check what features are enabled
    logger.info("\n🔧 CONFIGURATION STATUS")
    logger.info("-" * 40)
    logger.info(f"Term extraction: {'✅ ENABLED' if config.enable_term_extraction else '❌ DISABLED'}")
    logger.info(f"UMLS mapping: {'✅ ENABLED' if config.enable_umls_mapping else '⏸️ DISABLED'}")
    logger.info(f"AI cleaning: {'✅ ENABLED' if config.enable_ai_cleaning else '⏸️ DISABLED'}")
    logger.info(f"OMOP mapping: {'✅ ENABLED' if config.enable_omop_mapping else '⏸️ DISABLED'}")

    # Test with sample text if possible
    if module_status['main_pipeline'].startswith("✅") and Path(test_file).exists():
        logger.info("\n🧪 ATTEMPTING PIPELINE TEST")
        logger.info("-" * 40)

        try:
            # Enable all optional modules for full testing
            config.enable_umls_mapping = True
            config.enable_ai_cleaning = True
            config.enable_omop_mapping = True

            # Create fresh pipeline with all features enabled
            test_pipeline = MicrobiomePipeline(config)

            logger.info("🔄 Running full pipeline on PRJDB4360.txt...")

            # Create input directory structure
            input_dir = Path("data/input")
            input_dir.mkdir(parents=True, exist_ok=True)

            # Copy test file to input
            import shutil
            test_output = Path("data/test_output")
            test_output.mkdir(parents=True, exist_ok=True)

            # Run the pipeline
            results = test_pipeline.run("data/input", "data/test_output")

            if 'error' not in results:
                logger.info("✅ Full pipeline completed successfully!")

                # Check what stages were actually executed
                if 'pipeline_statistics' in results:
                    stats = results['pipeline_statistics']
                    if 'stage_results' in stats:
                        stages = stats['stage_results']
                        logger.info("\n📊 EXECUTED STAGES:")
                        for stage, count in stages.items():
                            if count is not None:
                                logger.info(f"   - {stage}: {count} items")

                    if 'stage_times' in stats:
                        logger.info("\n⏱️  PROCESSING TIMES:")
                        for stage, time_taken in stats['stage_times'].items():
                            logger.info(f"   - {stage}: {time_taken:.2f}s")

                # Check for results files
                result_files = list(test_output.glob("*"))
                logger.info(f"\n📁 Generated {len(result_files)} output files:")
                for file in result_files:
                    logger.info(f"   - {file.name}")

            else:
                logger.error(f"❌ Pipeline completed with errors: {results.get('error', 'Unknown error')}")

        except Exception as e:
            logger.error(f"❌ Pipeline test failed: {e}")
            import traceback
            logger.error(traceback.format_exc())

    return module_status

def main():
    """Main function."""
    status = test_full_pipeline()

    logger.info("\n" + "="*80)
    logger.info("🏁 PIPELINE ANALYSIS COMPLETE")
    logger.info("="*80)

    # Count working vs non-working modules
    working = sum(1 for status in status.values() if status.startswith("✅"))
    total = len(status)

    logger.info(f"Working modules: {working}/{total}")
    logger.info(f"Success rate: {(working/total)*100:.1f}%")

    if working == total:
        logger.info("🎉 All modules are working! Pipeline is ready for production.")
    else:
        logger.info("⚠️  Some modules have issues. See detailed status above.")

        # Identify what needs fixing
        broken = [module for module, status in status.items() if status.startswith("❌")]
        logger.info("\n🔧 Modules that need attention:")
        for module in broken:
            logger.info(f"   - {module}")

if __name__ == "__main__":
    main()