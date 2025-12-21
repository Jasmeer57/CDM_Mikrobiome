"""
Global Pipeline Processor
Orchestrates the complete scientific term extraction workflow:
1. Parallel Extraction (Multi-model)
2. Global Deduplication (Exact -> Fuzzy -> Semantic -> Biomedical)
3. Semantic Quality Filtering
4. Term Selection (Scoring & Ranking)
5. Advanced Processing (Correction, Definitions, Validation, Mapping)
"""

import logging
import time
import json
import multiprocessing
from pathlib import Path
from typing import List, Dict, Any, Set, Tuple
from datetime import datetime
from collections import Counter
import pandas as pd
import numpy as np

from src.config.settings import PipelineConfig
from src.modules.terms_extractor import TermsExtractor
from src.modules.deduplication import Deduplicator
from src.modules.ai_correction import AITermCorrector
from src.modules.biomistral import BioMistralValidator, DefinitionGenerator, LLMTermCorrector
from src.modules.umls_mapping import UMLSMapper
from src.modules.omop_mapping import OMOPMapper, ComprehensiveMapper
from src.modules.microbiome_components import (
    MicrobiomeGoldStandardScorer,
    MicrobiomeSemanticFilter,
    ContextualCleaner
)
from src.modules.label_corrector import LabelCorrector
from src.modules.ranking_components import (
    TermRanker,
    TfidfSemanticModel
)

logger = logging.getLogger(__name__)

# --- Global Worker State for Parallel Processing ---
_worker_extractor = None

def init_worker(config: PipelineConfig):
    """Initialize worker process with its own extractor"""
    global _worker_extractor
    try:
        # Create a fresh extractor for each worker
        # We need to ensure the config passed here is picklable and correct
        from src.modules.terms_extractor import TermsExtractor
        _worker_extractor = TermsExtractor(config.scispacy)
        logger.info(f"Worker initialized")
    except Exception as e:
        logger.error(f"Worker initialization failed: {e}")

def process_file_worker(file_path: Path) -> Tuple[Path, List[Dict[str, Any]]]:
    """Worker function to extract terms from a file"""
    global _worker_extractor
    if _worker_extractor is None:
        return file_path, []

    try:
        # Security: Validate file path to prevent path traversal attacks
        resolved_path = file_path.resolve()

        # Check if file exists and is actually a file
        if not resolved_path.exists() or not resolved_path.is_file():
            logger.warning(f"File does not exist or is not a regular file: {file_path}")
            return file_path, []

        # Additional file validation for security
        if resolved_path.suffix.lower() not in {'.txt', '.md', '.csv', '.json'}:
            logger.warning(f"Unauthorized file type: {resolved_path.suffix}")
            return file_path, []

        # Check file size to prevent processing extremely large files
        file_size = resolved_path.stat().st_size
        max_file_size = 50 * 1024 * 1024  # 50MB limit
        if file_size > max_file_size:
            logger.warning(f"File too large ({file_size} bytes): {file_path}")
            return file_path, []

        # Secure file reading with path validation
        text = resolved_path.read_text(encoding='utf-8', errors='ignore')
        terms = _worker_extractor.extract_from_text(text)
        return file_path, terms
    except (PermissionError, OSError) as e:
        logger.error(f"Permission or OS error accessing {file_path}: {e}")
        return file_path, []
    except UnicodeDecodeError as e:
        logger.error(f"Text encoding error in {file_path}: {e}")
        return file_path, []
    except Exception as e:
        logger.error(f"Worker failed on {file_path}: {e}")
        return file_path, []


class GlobalPipelineProcessor:
    """
    Enhanced Global Pipeline Processor with microbiome-specific components
    Manages the global 6-step pipeline:
    1. Extract all terms from all files (Parallel)
    2. Contextual Cleaning & Global Deduplication (Exact -> Fuzzy -> Semantic -> Biomedical)
    3. Microbiome Semantic Filtering
    4. Advanced Term Ranking (Gold Standard + Scoring)
    5. Advanced Processing (Correction, Definitions, Validation, Mapping)
    6. Output Generation with Step-by-Step Saving
    """

    def __init__(self, config: PipelineConfig):
        self.config = config

        # Initialize core components
        self.deduplicator = Deduplicator(config.deduplication)

        # Microbiome-specific components
        self.contextual_cleaner = ContextualCleaner()
        self.gold_scorer = MicrobiomeGoldStandardScorer()
        self.semantic_filter = MicrobiomeSemanticFilter()
        self.term_ranker = TermRanker(config)
        self.label_corrector = LabelCorrector(
            bioportal_api_key=config.bioportal.api_key,
            umls_api_key=config.umls.api_key
        )

        # Fallback semantic model
        try:
            self.tfidf_model = TfidfSemanticModel()
        except Exception as e:
            logger.warning(f"TF-IDF model not available: {e}")
            self.tfidf_model = None

        # Advanced components (lazy loaded or initialized here)
        self.definition_generator = DefinitionGenerator(config)
        self.term_corrector = LLMTermCorrector(config)
        self.validator = BioMistralValidator(config)
        self.mapper = ComprehensiveMapper(config)
        
    def run(self):
        """Run the complete enhanced global pipeline with microbiome-specific components"""
        start_time = time.time()
        logger.info("🚀 STARTING ENHANCED GLOBAL PIPELINE WITH MICROBIOME COMPONENTS")
        logger.info(f"   Target Final Terms: {self.config.target_final_terms}")
        logger.info(f"   Input Directory: {self.config.input_dir}")
        logger.info("   Features: Gold Standard Scoring, Contextual Cleaning, Advanced Ranking")

        # STEP 1: Extract All Terms
        raw_terms = self.extract_all_terms_from_all_files()
        if not raw_terms:
            logger.error("No terms extracted. Exiting.")
            return

        # Save raw terms after extraction
        self.save_terms_to_files(raw_terms, "step1_raw_extraction")

        # STEP 2: Contextual Cleaning & Global Deduplication
        cleaned_terms = self.apply_contextual_cleaning(raw_terms)
        self.save_terms_to_files(cleaned_terms, "step2_cleaned_terms")

        deduplicated_terms = self.run_global_deduplication(cleaned_terms)
        self.save_terms_to_files(deduplicated_terms, "step3_deduplicated_terms")
        
        # STEP 2B: Label Correction  
        deduplicated_terms = self.apply_label_correction(deduplicated_terms)

        # STEP 3: Microbiome Semantic Filtering
        filtered_terms = self.apply_microbiome_semantic_filtering(deduplicated_terms)
        self.save_terms_to_files(filtered_terms, "step4_semantic_filtered_terms")

        # STEP 4: Advanced Term Ranking (Gold Standard + Comprehensive Scoring)
        ranked_terms = self.apply_advanced_term_ranking(filtered_terms)
        final_selection = ranked_terms[:self.config.target_final_terms]
        self.save_terms_to_files(final_selection, "step5_final_selection")

        # STEP 5: Advanced Processing
        processed_terms = self.run_advanced_processing(final_selection)

        # STEP 6: Save Results
        self.save_results(processed_terms)

        elapsed = (time.time() - start_time) / 60
        logger.info(f"🎉 ENHANCED GLOBAL PIPELINE COMPLETE!")
        logger.info(f"⏱️  Total processing time: {elapsed:.1f} minutes")
        logger.info(f"📊 Final term count: {len(processed_terms)}")
        
    def extract_all_terms_from_all_files(self) -> List[Dict[str, Any]]:
        """Step 1: Parallel extraction from all files"""
        logger.info("="*50)
        logger.info("STEP 1: EXTRACTING TERMS FROM ALL FILES")
        logger.info("="*50)
        
        input_path = Path(self.config.input_dir)
        files = []
        for pattern in self.config.input_patterns:
            files.extend(list(input_path.glob(pattern)))
            
        files = sorted(list(set(files)))[:self.config.max_files]
        
        if not files:
            logger.error(f"No files found in {input_path}")
            return []
            
        logger.info(f"Found {len(files)} files to process.")
        
        all_terms = []
        
        # Use ProcessPoolExecutor for parallel extraction
        # We need to pass the config to the worker init
        # Note: Config must be picklable. Dataclasses usually are.
        
        # Use config.scispacy.num_workers if available (for crash-proof execution on low RAM)
        if hasattr(self.config, 'scispacy') and hasattr(self.config.scispacy, 'num_workers'):
            max_workers = self.config.scispacy.num_workers
        else:
            max_workers = min(multiprocessing.cpu_count(), len(files))
            # Cap workers to avoid OOM with large models
            max_workers = min(max_workers, 4) 
        
        logger.info(f"Starting parallel extraction with {max_workers} workers...")
        
        from concurrent.futures import ProcessPoolExecutor
        
        with ProcessPoolExecutor(max_workers=max_workers, initializer=init_worker, initargs=(self.config,)) as executor:
            results = list(executor.map(process_file_worker, files))
            
        for file_path, terms in results:
            all_terms.extend(terms)
            
        logger.info(f"✅ Extraction complete. Total raw terms: {len(all_terms)}")
        return all_terms

    def run_global_deduplication(self, terms: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Step 2: Global Deduplication"""
        logger.info("="*50)
        logger.info("STEP 2: GLOBAL DEDUPLICATION")
        logger.info("="*50)
        
        # Apply 4-layer deduplication (Exact, Fuzzy, Semantic, Biomedical)
        result = self.deduplicator.deduplicate_terms(terms)
        
        logger.info(f"   Exact removed: {result.exact_removed}")
        logger.info(f"   Fuzzy removed: {result.fuzzy_removed}")
        logger.info(f"   Semantic removed: {result.semantic_removed}")
        logger.info(f"   Biomedical removed: {result.biomedical_removed}")
        
        return result.deduplicated_terms

    def filter_noise_terms(self, terms: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Step 3: Filter out generic/noise terms"""
        logger.info("="*50)
        logger.info("STEP 3: FILTERING NOISE TERMS")
        logger.info("="*50)
        
        # Semantic quality filtering is integrated into the deduplication system
        logger.info(f"   ✅ Remaining terms: {len(terms)}")
        return terms
    
    def apply_label_correction(self, terms: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Correct generic ENTITY labels using enhanced pattern matching"""
        logger.info("="*50)
        logger.info("STEP 2B: LABEL CORRECTION")
        logger.info("="*50)
        
        from src.modules.terms_extractor import ENTITY_REFINEMENT_RULES
        import re
        
        corrected_count = 0
        label_changes = {}
        
        for term_data in terms:
            current_labels = term_data.get('labels', [])
            
            # Only correct generic ENTITY labels
            if 'ENTITY' in current_labels and len(current_labels) == 1:
                term_text = term_data['term']
                term_lower = term_text.lower()
                
                # Try pattern-based correction
                for label, patterns in ENTITY_REFINEMENT_RULES.items():
                    matched = False
                    for pattern in patterns:
                        if re.search(pattern, term_lower):
                            term_data['labels'] = [label]
                            term_data['original_label'] = 'ENTITY'
                            corrected_count += 1
                            label_changes[label] = label_changes.get(label, 0) + 1
                            matched = True
                            break
                    if matched:
                        break
                
                # If still ENTITY, try API-based correction if enabled
                if term_data['labels'] == ['ENTITY']:
                    api_result = self.label_corrector.correct_label(term_text, 'ENTITY')
                    if api_result and api_result['label'] != 'ENTITY':
                        term_data['labels'] = [api_result['label']]
                        term_data['original_label'] = 'ENTITY'
                        term_data['label_source'] = api_result['source']
                        corrected_count += 1
                        label_changes[api_result['label']] = label_changes.get(api_result['label'], 0) + 1
        
        logger.info(f"   ✓ Corrected {corrected_count}/{len(terms)} generic ENTITY labels")
        for label, count in sorted(label_changes.items(), key=lambda x: x[1], reverse=True):
            logger.info(f"      ENTITY → {label}: {count}")
        logger.info("")
        
        return terms

  
    def run_advanced_processing(self, terms: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Step 5: Correction, Definitions, Validation, Mapping"""
        logger.info("="*50)
        logger.info("STEP 5: ADVANCED PROCESSING")
        logger.info("="*50)
        
        # 1. Correction
        if self.config.correct_terms:
            logger.info("   Running term correction...")
            terms = self.term_corrector.correct_terms(terms)
            
        # 2. Definitions
        if self.config.generate_definitions:
            logger.info("   Generating definitions...")
            terms = self.definition_generator.generate_definitions(terms)
            
        # 3. Validation
        if self.config.validate_biomistral:
            logger.info("   Running BioMistral validation...")
            terms = self.validator.validate_terms(terms)
            
        # 4. Mapping
        if self.config.map_umls or self.config.map_omop or self.config.map_bioportal:
            logger.info("   Running Ontology Mapping...")
            terms = self.mapper.map_terms(terms)
            
        return terms

    def apply_contextual_cleaning(self, terms: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Apply contextual cleaning to extracted terms"""
        logger.info("="*50)
        logger.info("STEP 2A: CONTEXTUAL CLEANING")
        logger.info("="*50)

        cleaned_terms = self.contextual_cleaner.clean_terms(terms)
        logger.info(f"✅ Contextual cleaning: {len(terms)} → {len(cleaned_terms)} terms")
        return cleaned_terms

    def apply_microbiome_semantic_filtering(self, terms: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Apply microbiome-specific semantic filtering"""
        logger.info("="*50)
        logger.info("STEP 4: MICROBIOME SEMANTIC FILTERING")
        logger.info("="*50)

        filtered_terms = []
        rejected_count = 0

        for term in terms:
            term_text = term.get('term', '')
            relevance_score = self.semantic_filter.get_relevance_score(term_text)

            # Add relevance score to term data
            term['microbiome_relevance'] = relevance_score

            # Keep terms with reasonable relevance score
            if relevance_score >= 0.3:  # Threshold can be adjusted
                filtered_terms.append(term)
            else:
                rejected_count += 1

        logger.info(f"   🧬 Semantic filtering: {len(terms)} → {len(filtered_terms)} terms")
        logger.info(f"   ❌ Rejected {rejected_count} terms with low microbiome relevance")

        return filtered_terms

    def apply_advanced_term_ranking(self, terms: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Apply advanced term ranking with gold standard scoring"""
        logger.info("="*50)
        logger.info("STEP 5: ADVANCED TERM RANKING (GOLD STANDARD + COMPREHENSIVE SCORING)")
        logger.info("="*50)

        ranked_terms = self.term_ranker.rank_terms(terms)

        # Log statistics about gold standard terms
        gold_standard_count = sum(1 for term in ranked_terms if term.get('is_gold_standard', False))
        high_relevance_count = sum(1 for term in ranked_terms if term.get('microbiome_relevance', 0) >= 0.8)

        logger.info(f"   🏆 Gold standard terms: {gold_standard_count}")
        logger.info(f"   🎯 High relevance terms: {high_relevance_count}")

        return ranked_terms

    def save_terms_to_files(self, terms: List[Dict[str, Any]], step_name: str) -> None:
        """Save intermediate results to files (matching standalone pipeline behavior)"""
        try:
            output_dir = Path(self.config.output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

            # Save CSV
            csv_file = output_dir / f"{step_name}_{timestamp}.csv"
            if terms:
                df = pd.DataFrame(terms)
                df.to_csv(csv_file, index=False)
                logger.info(f"   💾 Saved {len(terms)} terms to {csv_file}")
            else:
                # Create empty CSV with headers
                empty_df = pd.DataFrame(columns=['term', 'score', 'frequency', 'label'])
                empty_df.to_csv(csv_file, index=False)
                logger.info(f"   💾 Created empty file {csv_file}")

        except Exception as e:
            logger.warning(f"Failed to save intermediate files for {step_name}: {e}")

    def save_results(self, terms: List[Dict[str, Any]]):
        """Step 6: Save final results with enhanced metadata"""
        logger.info("="*50)
        logger.info("STEP 6: SAVING FINAL RESULTS")
        logger.info("="*50)

        output_dir = Path(self.config.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Create summary statistics
        gold_standard_count = sum(1 for term in terms if term.get('is_gold_standard', False))
        avg_score = sum(term.get('score', 0) for term in terms) / len(terms) if terms else 0
        avg_relevance = sum(term.get('microbiome_relevance', 0) for term in terms) / len(terms) if terms else 0

        # Enhanced metadata
        metadata = {
            'pipeline_version': '7.0-enhanced',
            'processing_date': datetime.now().isoformat(),
            'total_terms': len(terms),
            'gold_standard_terms': gold_standard_count,
            'target_final_terms': self.config.target_final_terms,
            'average_score': round(avg_score, 4),
            'average_microbiome_relevance': round(avg_relevance, 4),
            'features_enabled': {
                'contextual_cleaning': True,
                'gold_standard_scoring': True,
                'microbiome_semantic_filtering': True,
                'advanced_ranking': True,
                'ai_correction': self.config.correct_terms,
                'generate_definitions': self.config.generate_definitions,
                'biomistral_validation': self.config.validate_biomistral,
                'umls_mapping': self.config.map_umls,
                'omop_mapping': self.config.map_omop,
                'bioportal_mapping': self.config.map_bioportal
            }
        }

        # Convert to DataFrame for CSV
        df = pd.DataFrame(terms)

        # Flatten fields for CSV
        if not df.empty:
            # Flatten mappings
            if 'mappings' in df.columns:
                df['mappings_str'] = df['mappings'].apply(
                    lambda x: json.dumps(x) if isinstance(x, dict) else str(x)
                )

            # Flatten validation
            if 'validation' in df.columns:
                df['is_valid'] = df['validation'].apply(
                    lambda x: x.get('is_valid') if isinstance(x, dict) else None
                )

            # Flatten ranking factors
            if 'ranking_factors' in df.columns:
                df['ranking_factors_str'] = df['ranking_factors'].apply(
                    lambda x: json.dumps(x) if isinstance(x, dict) else str(x)
                )

        # Save enhanced CSV
        csv_path = output_dir / "enhanced_pipeline_results.csv"
        df.to_csv(csv_path, index=False)
        logger.info(f"   💾 Saved enhanced CSV to {csv_path}")

        # Save enhanced JSON with metadata
        results = {
            'metadata': metadata,
            'terms': terms
        }

        json_path = output_dir / "enhanced_pipeline_results.json"
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, default=str)
        logger.info(f"   💾 Saved enhanced JSON to {json_path}")

        # Save metadata separately
        metadata_path = output_dir / "pipeline_metadata.json"
        with open(metadata_path, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=2, default=str)
        logger.info(f"   💾 Saved metadata to {metadata_path}")

        # Log summary statistics
        logger.info(f"📊 FINAL RESULTS SUMMARY:")
        logger.info(f"   Total terms processed: {len(terms)}")
        logger.info(f"   Gold standard terms: {gold_standard_count}")
        logger.info(f"   Average score: {avg_score:.4f}")
        logger.info(f"   Average microbiome relevance: {avg_relevance:.4f}")

