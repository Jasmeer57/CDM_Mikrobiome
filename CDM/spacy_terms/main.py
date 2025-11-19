#!/usr/bin/env python3
"""
Advanced Scientific Term Extraction Pipeline
Comprehensive modular pipeline with AI correction, UMLS/OMOP mapping, and semantic deduplication.

Features:
- Multi-sciSpaCy model NER extraction
- 3-layer deduplication (Exact → Fuzzy → Semantic)
- AI-powered term correction (BioMistral/OpenAI)
- UMLS mapping with BioPortal/OLS/NCBO integration
- OMOP vocabulary mapping
- Multi-format output (JSON, CSV, SQLite)
"""

import os
import sys
import argparse
import logging
import json
from pathlib import Path
from typing import Dict, List, Any
from datetime import datetime

# Add src to path for imports
sys.path.append(str(Path(__file__).parent / "src"))

from src.config.settings import get_config, validate_config
from src.modules.terms_extractor import TermsExtractor, create_terms_extractor
from src.modules.deduplication import Deduplicator, create_deduplicator
from src.modules.ai_correction import AITermCorrector, create_ai_corrector
from src.modules.umls_mapping import UMLSMapper, create_umls_mapper
from src.modules.omop_mapping import OMOPMapper, create_omop_mapper
from src.utils.output_writer import OutputWriter, create_output_writer


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


def load_input_files(input_dir: str, patterns: List[str], max_files: int = None) -> List[str]:
    """Load input files from directory"""
    input_files = []
    input_path = Path(input_dir)

    if not input_path.exists():
        raise FileNotFoundError(f"Input directory does not exist: {input_dir}")

    for pattern in patterns:
        files = list(input_path.glob(pattern))
        input_files.extend([str(f) for f in files if f.is_file()])

    # Remove duplicates and sort
    input_files = sorted(list(set(input_files)))

    if max_files:
        input_files = input_files[:max_files]

    return input_files


def process_documents(
    input_files: List[str],
    terms_extractor: TermsExtractor,
    deduplicator: Deduplicator,
    ai_corrector: AITermCorrector,
    umls_mapper: UMLSMapper,
    omop_mapper: OMOPMapper,
    config
) -> Dict[str, Any]:
    """Process all documents through the complete pipeline"""
    logger = logging.getLogger(__name__)

    results = {
        "metadata": {
            "timestamp": datetime.now().isoformat(),
            "input_files": input_files,
            "config": {
                "models": config.scispacy.models,
                "semantic_model": config.deduplication.default_semantic_model,
                "fuzzy_threshold": config.deduplication.fuzzy_threshold,
                "semantic_threshold": config.deduplication.semantic_threshold,
                "ai_correction_enabled": config.ai_correction.enabled,
                "umls_enabled": config.umls.enabled,
                "omop_enabled": config.omop.enabled
            }
        },
        "extraction_results": [],
        "deduplicated_terms": [],
        "ai_corrected_terms": [],
        "umls_mappings": {},
        "omop_mappings": {},
        "statistics": {}
    }

    logger.info(f"Processing {len(input_files)} files...")

    # Step 1: Extract terms using sciSpaCy models
    logger.info("=" * 50)
    logger.info("STEP 1: SCISPACY TERM EXTRACTION")
    logger.info("=" * 50)

    all_extracted_terms = []
    extraction_stats = {"raw_entities": 0, "filtered_entities": 0}

    for file_path in input_files:
        logger.info(f"Processing: {file_path}")

        try:
            file_terms = terms_extractor.extract_from_file(file_path)
            all_extracted_terms.extend(file_terms)

            extraction_stats["raw_entities"] += sum(
                len(t.get("raw_entities", [])) for t in file_terms
            )
            extraction_stats["filtered_entities"] += len(file_terms)

            results["extraction_results"].extend(file_terms)

        except Exception as e:
            logger.error(f"Error processing {file_path}: {e}")
            continue

    logger.info(f"Extraction complete: {extraction_stats['raw_entities']} raw entities → {extraction_stats['filtered_entities']} filtered terms")
    results["statistics"]["extraction"] = extraction_stats

    # Step 2: Deduplication
    logger.info("=" * 50)
    logger.info("STEP 2: MULTI-LAYER DEDUPLICATION")
    logger.info("=" * 50)

    dedup_result = deduplicator.deduplicate_terms(all_extracted_terms)
    deduplicated_terms = dedup_result.deduplicated_terms

    logger.info(f"Deduplication complete: {len(all_extracted_terms)} → {len(deduplicated_terms)} terms")
    results["deduplicated_terms"] = deduplicated_terms
    results["statistics"]["deduplication"] = {
        "original_count": len(all_extracted_terms),
        "exact_removed": dedup_result.exact_removed,
        "fuzzy_removed": dedup_result.fuzzy_removed,
        "semantic_removed": dedup_result.semantic_removed,
        "final_count": len(deduplicated_terms)
    }

    # Step 3: AI Correction (if enabled)
    if config.ai_correction.enabled:
        logger.info("=" * 50)
        logger.info("STEP 3: AI-POWERED TERM CORRECTION")
        logger.info("=" * 50)

        ai_corrected_terms = ai_corrector.correct_terms_batch(deduplicated_terms)
        results["ai_corrected_terms"] = ai_corrected_terms

        ai_stats = {
            "original_count": len(deduplicated_terms),
            "final_count": len(ai_corrected_terms),
            "corrected": sum(1 for t in ai_corrected_terms if t.get("ai_classification") == "CORRECT"),
            "removed": sum(1 for t in ai_corrected_terms if t.get("ai_classification") == "REMOVE"),
            "kept": sum(1 for t in ai_corrected_terms if t.get("ai_classification") == "KEEP")
        }
        results["statistics"]["ai_correction"] = ai_stats

        logger.info(f"AI correction complete: {ai_stats['corrected']} corrected, {ai_stats['removed']} removed, {ai_stats['kept']} kept")
    else:
        results["ai_corrected_terms"] = deduplicated_terms
        logger.info("AI correction disabled, skipping...")

    # Step 4: UMLS Mapping (if enabled)
    if config.umls.enabled:
        logger.info("=" * 50)
        logger.info("STEP 4: UMLS & ONTOLOGY MAPPING")
        logger.info("=" * 50)

        terms_to_map = [t.get("term", "") for t in results["ai_corrected_terms"]]
        umls_mappings = umls_mapper.map_terms_comprehensive(terms_to_map)
        results["umls_mappings"] = {term: mapping.to_dict() for term, mapping in umls_mappings.items()}

        umls_stats = {
            "total_terms": len(terms_to_map),
            "umls_exact_matches": sum(1 for m in umls_mappings.values() if m.umls_exact),
            "bioportal_exact_matches": sum(1 for m in umls_mappings.values() if m.bioportal_exact),
            "ols_exact_matches": sum(1 for m in umls_mappings.values() if m.ols_exact)
        }
        results["statistics"]["umls_mapping"] = umls_stats

        logger.info(f"UMLS mapping complete: {umls_stats['umls_exact_matches']} exact UMLS matches")
    else:
        logger.info("UMLS mapping disabled, skipping...")

    # Step 5: OMOP Mapping (if enabled)
    if config.omop.enabled and hasattr(config.omop, 'vocab_dir'):
        logger.info("=" * 50)
        logger.info("STEP 5: OMOP VOCABULARY MAPPING")
        logger.info("=" * 50)

        try:
            omop_mapper.initialize()
            terms_to_map = [t.get("term", "") for t in results["ai_corrected_terms"]]
            omop_results = omop_mapper.map_terms(terms_to_map)
            results["omop_mappings"] = {r.original_term: r.to_dict() for r in omop_results}

            omop_stats = {
                "total_terms": len(terms_to_map),
                "exact_matches": sum(1 for r in omop_results if r.best_match and r.best_match.match_type == "EXACT"),
                "fuzzy_matches": sum(1 for r in omop_results if r.best_match and r.best_match.match_type == "FUZZY"),
                "no_matches": sum(1 for r in omop_results if not r.matches)
            }
            results["statistics"]["omop_mapping"] = omop_stats

            logger.info(f"OMOP mapping complete: {omop_stats['exact_matches']} exact, {omop_stats['fuzzy_matches']} fuzzy matches")

        except Exception as e:
            logger.error(f"OMOP mapping failed: {e}")
            logger.info("Continuing without OMOP mapping...")
    else:
        logger.info("OMOP mapping disabled or not configured, skipping...")

    # Final statistics
    final_terms_count = len(results["ai_corrected_terms"])
    results["statistics"]["overall"] = {
        "final_unique_terms": final_terms_count,
        "total_reduction_percent": round((1 - final_terms_count / max(extraction_stats["raw_entities"], 1)) * 100, 2),
        "pipeline_stages_completed": [
            "extraction",
            "deduplication",
            "ai_correction" if config.ai_correction.enabled else None,
            "umls_mapping" if config.umls.enabled else None,
            "omop_mapping" if (config.omop.enabled and hasattr(config.omop, 'vocab_dir')) else None
        ]
    }
    results["statistics"]["overall"]["pipeline_stages_completed"] = [
        stage for stage in results["statistics"]["overall"]["pipeline_stages_completed"] if stage
    ]

    return results


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

    # Deduplication arguments
    parser.add_argument("--semantic_model", type=str, default="mini-lm", choices=["mini-lm", "nomic", "mpnet"], help="Semantic model for deduplication")
    parser.add_argument("--fuzzy_threshold", type=float, default=0.85, help="Fuzzy matching threshold")
    parser.add_argument("--semantic_threshold", type=float, default=0.9, help="Semantic similarity threshold")

    # Feature toggles
    parser.add_argument("--disable_ai_correction", action="store_true", help="Disable AI term correction")
    parser.add_argument("--disable_umls", action="store_true", help="Disable UMLS mapping")
    parser.add_argument("--disable_omop", action="store_true", help="Disable OMOP mapping")

    # OMOP specific
    parser.add_argument("--omop_vocab_dir", type=str, help="OMOP vocabulary directory")

    # Output formats
    parser.add_argument("--output_formats", nargs="+", default=["json", "csv"], choices=["json", "csv", "sqlite"], help="Output formats")

    # Logging
    parser.add_argument("--log_level", type=str, default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    parser.add_argument("--log_file", type=str, help="Log file path")

    args = parser.parse_args()

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
    config.deduplication.default_semantic_model = args.semantic_model
    config.deduplication.fuzzy_threshold = args.fuzzy_threshold
    config.deduplication.semantic_threshold = args.semantic_threshold
    config.output_formats = args.output_formats

    config.ai_correction.enabled = not args.disable_ai_correction
    config.umls.enabled = not args.disable_umls
    config.omop.enabled = not args.disable_omop

    if args.omop_vocab_dir:
        config.omop.vocab_dir = args.omop_vocab_dir

    # Validate configuration
    warnings = validate_config(config)
    if warnings:
        logger.warning("Configuration warnings:")
        for warning in warnings:
            logger.warning(f"  - {warning}")

    # Create output directory
    os.makedirs(config.output_dir, exist_ok=True)

    try:
        # Initialize pipeline components
        logger.info("Initializing pipeline components...")

        terms_extractor = create_terms_extractor(config.scispacy)
        deduplicator = create_deduplicator(config.deduplication)
        ai_corrector = create_ai_corrector(config.ai_correction)
        umls_mapper = create_umls_mapper(config.umls, config.bioportal)
        omop_mapper = create_omop_mapper(config.omop.vocab_dir, config.omop) if config.omop.enabled and config.omop.vocab_dir else None

        # Load input files
        input_files = load_input_files(config.input_dir, config.input_patterns, config.max_files)
        logger.info(f"Found {len(input_files)} files to process")

        if not input_files:
            logger.error("No input files found!")
            return 1

        # Process documents
        results = process_documents(
            input_files=input_files,
            terms_extractor=terms_extractor,
            deduplicator=deduplicator,
            ai_corrector=ai_corrector,
            umls_mapper=umls_mapper,
            omop_mapper=omop_mapper,
            config=config
        )

        # Save results
        output_writer = create_output_writer(config.output_dir)
        saved_files = output_writer.save_results(results, config.output_formats)

        logger.info("=" * 50)
        logger.info("PIPELINE COMPLETED SUCCESSFULLY")
        logger.info("=" * 50)

        # Print summary
        stats = results["statistics"]["overall"]
        logger.info(f"Final unique terms: {stats['final_unique_terms']}")
        logger.info(f"Total reduction: {stats['total_reduction_percent']}%")
        logger.info(f"Pipeline stages: {', '.join(stats['pipeline_stages_completed'])}")

        logger.info("Results saved to:")
        for format_type, file_path in saved_files.items():
            logger.info(f"  {format_type.upper()}: {file_path}")

        return 0

    except KeyboardInterrupt:
        logger.info("Pipeline interrupted by user")
        return 1
    except Exception as e:
        logger.error(f"Pipeline failed: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())