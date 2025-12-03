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
        text = file_path.read_text(encoding='utf-8', errors='ignore')
        terms = _worker_extractor.extract_from_text(text)
        return file_path, terms
    except Exception as e:
        logger.error(f"Worker failed on {file_path}: {e}")
        return file_path, []


class GlobalPipelineProcessor:
    """
    Manages the global 6-step pipeline:
    1. Extract all terms from all files (Parallel)
    2. Global Deduplication (Exact -> Fuzzy -> Semantic -> Biomedical)
    3. Semantic Quality Filter (Bullshit detection)
    4. Select Top N Terms (Scoring)
    5. Advanced Processing (Correction, Definitions, Validation, Mapping)
    6. Output Generation
    """
    
    def __init__(self, config: PipelineConfig):
        self.config = config
        
        # Initialize components
        self.deduplicator = Deduplicator(config.deduplication)
        
        # Advanced components (lazy loaded or initialized here)
        self.definition_generator = DefinitionGenerator(config)
        self.term_corrector = LLMTermCorrector(config)
        self.validator = BioMistralValidator(config)
        self.mapper = ComprehensiveMapper(config)
        
    def run(self):
        """Run the complete global pipeline"""
        start_time = time.time()
        logger.info("🚀 STARTING CORRECT GLOBAL PIPELINE")
        logger.info(f"   Target Final Terms: {self.config.target_final_terms}")
        logger.info(f"   Input Directory: {self.config.input_dir}")
        
        # STEP 1: Extract All Terms
        raw_terms = self.extract_all_terms_from_all_files()
        if not raw_terms:
            logger.error("No terms extracted. Exiting.")
            return
            
        # STEP 2: Global Deduplication
        deduplicated_terms = self.run_global_deduplication(raw_terms)
        
        # STEP 3: Semantic Quality Filter
        filtered_terms = self.filter_bullshit_terms(deduplicated_terms)
        
        # STEP 4: Select Final Terms
        final_selection = self.select_final_terms(filtered_terms)
        
        # STEP 5: Advanced Processing
        processed_terms = self.run_advanced_processing(final_selection)
        
        # STEP 6: Save Results
        self.save_results(processed_terms)
        
        elapsed = (time.time() - start_time) / 60
        logger.info(f"🎉 CORRECT GLOBAL PIPELINE COMPLETE!")
        logger.info(f"⏱️  Total processing time: {elapsed:.1f} minutes")
        
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
        
        # The deduplicator module handles the 4-layer deduplication
        # We just need to call it.
        result = self.deduplicator.deduplicate_terms(terms)
        
        # The result object contains the deduplicated terms list
        # Note: Deduplicator.deduplicate_terms returns a DeduplicationResult object
        # but in standalone it returned the list directly or modified it?
        # Let's check src/modules/deduplication.py
        # It returns DeduplicationResult (Step 754, line 481)
        # But wait, standalone deduplicator might have returned a list?
        # Let's adapt to the module's return type.
        
        # Actually, looking at src/modules/deduplication.py:
        # It returns a DeduplicationResult object.
        
        logger.info(f"   Exact removed: {result.exact_removed}")
        logger.info(f"   Fuzzy removed: {result.fuzzy_removed}")
        logger.info(f"   Semantic removed: {result.semantic_removed}")
        logger.info(f"   Biomedical removed: {result.biomedical_removed}")
        
        return result.deduplicated_terms

    def filter_bullshit_terms(self, terms: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Step 3: Filter out generic/noise terms"""
        logger.info("="*50)
        logger.info("STEP 3: FILTERING BULLSHIT TERMS")
        logger.info("="*50)
        
        # The deduplicator module has _semantic_quality_filter, but it's internal.
        # However, it IS called inside deduplicate_terms (Step 5 in deduplication.py).
        # So terms returned from run_global_deduplication are ALREADY filtered?
        
        # Let's check src/modules/deduplication.py again.
        # Line 461: after_semantic_filter = self._semantic_quality_filter(after_biomedical)
        # Yes, it is already done in Step 2.
        
        # But standalone pipeline had it as a separate explicit step in GlobalPipelineProcessor.
        # If I use the existing src/modules/deduplication.py, it's bundled.
        # That's fine, as long as it's done.
        
        # However, to match standalone EXACTLY, I might want to run it again or ensure it's doing the same thing.
        # Standalone `filter_bullshit_terms` in `GlobalPipelineProcessor` (Step 677 context) 
        # might have been calling `deduplicator._semantic_quality_filter` explicitly if it wasn't in the main `deduplicate_terms` flow.
        
        # In standalone `standalone_scispacy_pipeline.py`:
        # The `Deduplicator` class had `deduplicate_terms` which called `_semantic_quality_filter`.
        # So it's the same.
        
        logger.info("   (Already performed as part of Deduplication Step 5)")
        logger.info(f"   ✅ Remaining terms: {len(terms)}")
        return terms

    def select_final_terms(self, terms: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Step 4: Select top N terms based on score"""
        logger.info("="*50)
        logger.info(f"STEP 4: SELECTING FINAL {self.config.target_final_terms} TERMS")
        logger.info("="*50)
        
        # Calculate scores
        for term in terms:
            # Score = Frequency * (1 + Length_Bonus) * (1 + Source_Bonus)
            freq = term.get('frequency', 1)
            length = len(term['term'])
            
            # Length bonus: prefer 10-30 chars
            len_bonus = 0.0
            if 10 <= length <= 30:
                len_bonus = 0.5
            elif length > 30:
                len_bonus = 0.2
                
            # Source bonus (if multiple models found it)
            # 'raw_entities' might contain list of entities from different models
            # But here we might just have 'frequency'.
            # If 'sources' or 'models' is tracked, use it.
            # In standalone, we tracked 'source_models'.
            source_bonus = 0.0
            if 'source_models' in term:
                source_bonus = len(term['source_models']) * 0.2
            
            term['final_score'] = freq * (1 + len_bonus) * (1 + source_bonus)
            
        # Sort by score
        sorted_terms = sorted(terms, key=lambda x: x.get('final_score', 0), reverse=True)
        
        # Cutoff
        final_terms = sorted_terms[:self.config.target_final_terms]
        
        logger.info(f"   ✅ Selected {len(final_terms)} final terms")
        return final_terms

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

    def save_results(self, terms: List[Dict[str, Any]]):
        """Step 6: Save results"""
        logger.info("="*50)
        logger.info("STEP 6: SAVING RESULTS")
        logger.info("="*50)
        
        output_dir = Path(self.config.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Convert to DataFrame for CSV
        df = pd.DataFrame(terms)
        
        # Flatten some fields for CSV
        if not df.empty:
            # Flatten mappings
            if 'mappings' in df.columns:
                df['mappings_str'] = df['mappings'].apply(lambda x: json.dumps(x) if isinstance(x, dict) else str(x))
            
            # Flatten validation
            if 'validation' in df.columns:
                df['is_valid'] = df['validation'].apply(lambda x: x.get('is_valid') if isinstance(x, dict) else None)
                
        # Save CSV
        csv_path = output_dir / "correct_global_results.csv"
        df.to_csv(csv_path, index=False)
        logger.info(f"   💾 Saved CSV to {csv_path}")
        
        # Save JSON
        json_path = output_dir / "correct_global_results.json"
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(terms, f, indent=2, default=str)
        logger.info(f"   💾 Saved JSON to {json_path}")

