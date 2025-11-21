"""
OMOP (Observational Medical Outcomes Partnership) vocabulary mapping module.
Based on reference mapping.py functionality with parallel processing support.
"""

import os
import re
import logging
import json
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, asdict
import pandas as pd
import numpy as np
from rapidfuzz import process, fuzz
from concurrent.futures import ProcessPoolExecutor, as_completed
from tqdm import tqdm
import pickle
from pathlib import Path
from src.config.settings import OMOPConfig

logger = logging.getLogger(__name__)


@dataclass
class OMOPConcept:
    """OMOP concept representation"""
    concept_id: str
    concept_name: str
    domain_id: str
    vocabulary_id: str
    concept_class_id: str
    standard_concept: str
    invalid_reason: str
    concept_code: str = ""
    domain_name: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class OMOPMatch:
    """OMOP mapping match result"""
    concept_id: str
    concept_name: str
    domain_id: str
    vocabulary_id: str
    score: float
    match_type: str  # EXACT, FUZZY
    concept_code: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class OMOPMappingResult:
    """Complete OMOP mapping result for a term"""
    original_term: str
    cleaned_term: str
    matches: List[OMOPMatch]
    best_match: Optional[OMOPMatch] = None

    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        result['matches'] = [match.to_dict() for match in self.matches]
        if self.best_match:
            result['best_match'] = self.best_match.to_dict()
        return result


class OMOPMapper:
    """High-performance OMOP vocabulary mapper with parallel processing"""

    # Default clinically relevant domains
    DEFAULT_DOMAINS = [
        'Condition', 'Drug', 'Procedure', 'Measurement',
        'Observation', 'Device', 'Spec Anatomic Site', 'Drug Class'
    ]

    def __init__(self, vocab_dir: str, config: OMOPConfig):
        self.vocab_dir = vocab_dir
        self.config = config
        self.concepts_df: Optional[pd.DataFrame] = None
        self.synonyms_df: Optional[pd.DataFrame] = None
        self.lookup_df: Optional[pd.DataFrame] = None
        self.standard_concepts: Optional[pd.DataFrame] = None
        self._concept_cache: Dict[str, OMOPConcept] = {}

    def preprocess_term(self, term: str) -> str:
        """Preprocess term for matching"""
        if not isinstance(term, str) or not term.strip():
            return ""

        term = term.lower()
        # Remove special characters but keep spaces
        term = re.sub(r'[^a-z0-9\s]', ' ', term)
        # Remove common stop words
        term = re.sub(r'\b(and|or|of|the|a|an|with|for|in|on|to|at|by|as)\b', ' ', term)
        # Normalize whitespace
        term = re.sub(r'\s+', ' ', term).strip()
        return term

    def _load_concepts(self) -> pd.DataFrame:
        """Load CONCEPT.csv from OMOP vocabulary"""
        logger.info("Loading OMOP CONCEPT.csv...")
        concept_path = os.path.join(self.vocab_dir, 'CONCEPT.csv')

        if not os.path.exists(concept_path):
            raise FileNotFoundError(f"CONCEPT.csv not found at {concept_path}")

        df = pd.read_csv(
            concept_path, sep='\t',
            usecols=[
                'concept_id', 'concept_name', 'concept_code',
                'domain_id', 'vocabulary_id', 'concept_class_id',
                'standard_concept', 'invalid_reason'
            ],
            dtype=str, na_filter=False
        )

        # Filter valid concepts
        df = df[df['invalid_reason'] == '']

        # Filter by domains if specified
        if self.config.vocabularies and 'Condition' in self.config.vocabularies:
            # Use domain filtering logic
            df = df[df['domain_id'].isin(self.DEFAULT_DOMAINS)]
            logger.info(f"Filtered to {len(self.DEFAULT_DOMAINS)} domains")

        logger.info(f"Loaded {len(df):,} valid OMOP concepts")
        return df

    def _load_synonyms(self) -> pd.DataFrame:
        """Load CONCEPT_SYNONYM.csv from OMOP vocabulary"""
        logger.info("Loading OMOP CONCEPT_SYNONYM.csv...")
        synonym_path = os.path.join(self.vocab_dir, 'CONCEPT_SYNONYM.csv')

        if not os.path.exists(synonym_path):
            logger.warning("CONCEPT_SYNONYM.csv not found, using only concept names")
            return pd.DataFrame(columns=['concept_id', 'concept_synonym_name'])

        df = pd.read_csv(
            synonym_path, sep='\t',
            usecols=['concept_id', 'concept_synonym_name'],
            dtype=str, na_filter=False
        )

        df = df[df['concept_synonym_name'] != '']
        logger.info(f"Loaded {len(df):,} concept synonyms")
        return df

    def _build_lookup_table(self):
        """Build lookup table for fast term matching"""
        logger.info("Building OMOP lookup table...")

        # Get standard concepts only
        self.standard_concepts = self.concepts_df[
            self.concepts_df['standard_concept'] == 'S'
        ].copy()

        standard_ids = set(self.standard_concepts['concept_id'])

        # Filter synonyms for standard concepts only
        synonym_standard = self.synonyms_df[
            self.synonyms_df['concept_id'].isin(standard_ids)
        ].copy()

        # Create lookup entries
        concept_entries = self.standard_concepts[['concept_id', 'concept_name']].copy()
        concept_entries['term_clean'] = concept_entries['concept_name'].apply(self.preprocess_term)

        synonym_standard['term_clean'] = synonym_standard['concept_synonym_name'].apply(self.preprocess_term)

        # Combine concept names and synonyms
        lookup_entries = pd.concat([
            concept_entries[['concept_id', 'term_clean']],
            synonym_standard[['concept_id', 'term_clean']]
        ], ignore_index=True)

        # Clean and optimize lookup
        lookup_entries = lookup_entries[lookup_entries['term_clean'] != '']
        lookup_entries.drop_duplicates(['term_clean', 'concept_id'], inplace=True)
        lookup_entries['term_len'] = lookup_entries['term_clean'].str.len()

        self.lookup_df = lookup_entries
        logger.info(f"Built lookup table with {len(self.lookup_df):,} entries")

    def _build_concept_cache(self):
        """Build concept cache for fast metadata retrieval"""
        logger.info("Building concept metadata cache...")

        for _, row in tqdm(self.standard_concepts.iterrows(), total=len(self.standard_concepts), desc="Building cache"):
            concept = OMOPConcept(
                concept_id=row['concept_id'],
                concept_name=row['concept_name'],
                domain_id=row['domain_id'],
                vocabulary_id=row['vocabulary_id'],
                concept_class_id=row['concept_class_id'],
                standard_concept=row['standard_concept'],
                invalid_reason=row['invalid_reason'],
                concept_code=row.get('concept_code', '')
            )
            self._concept_cache[row['concept_id']] = concept

        logger.info(f"Cached {len(self._concept_cache):,} concepts")

    def initialize(self):
        """Initialize the mapper with vocabulary data"""
        try:
            self.concepts_df = self._load_concepts()
            self.synonyms_df = self._load_synonyms()
            self._build_lookup_table()
            self._build_concept_cache()

            # Save cache if configured
            if self.config.concept_cache_file:
                self._save_cache()

        except Exception as e:
            logger.error(f"Failed to initialize OMOP mapper: {e}")
            raise

    def _save_cache(self):
        """Save concept cache to file"""
        try:
            cache_path = Path(self.config.concept_cache_file)
            with open(cache_path, 'wb') as f:
                pickle.dump(self._concept_cache, f)
            logger.info(f"Saved concept cache to {cache_path}")
        except Exception as e:
            logger.warning(f"Failed to save cache: {e}")

    def _load_cache(self) -> bool:
        """Load concept cache from file"""
        try:
            cache_path = Path(self.config.concept_cache_file)
            if cache_path.exists():
                with open(cache_path, 'rb') as f:
                    self._concept_cache = pickle.load(f)
                logger.info(f"Loaded concept cache from {cache_path}")
                return True
        except Exception as e:
            logger.warning(f"Failed to load cache: {e}")
        return False

    def _find_exact_matches(self, terms: List[str]) -> Dict[str, List[OMOPMatch]]:
        """Find exact matches for terms"""
        logger.info("Finding exact OMOP matches...")

        matches = {}
        term_series = pd.Series(terms)
        cleaned_terms = term_series.apply(self.preprocess_term)

        # Merge with lookup table
        merged = pd.DataFrame({
            'original_term': terms,
            'term_clean': cleaned_terms
        }).reset_index().merge(
            self.lookup_df,
            on='term_clean',
            how='left'
        )

        # Group by original term
        for term in terms:
            term_matches = merged[merged['original_term'] == term]
            concept_ids = term_matches['concept_id'].dropna().unique()

            term_matches_list = []
            for concept_id in concept_ids:
                concept = self._concept_cache.get(concept_id)
                if concept:
                    match = OMOPMatch(
                        concept_id=concept.concept_id,
                        concept_name=concept.concept_name,
                        domain_id=concept.domain_id,
                        vocabulary_id=concept.vocabulary_id,
                        score=100.0,
                        match_type="EXACT",
                        concept_code=concept.concept_code
                    )
                    term_matches_list.append(match)

            matches[term] = term_matches_list

        exact_count = sum(1 for term_matches in matches.values() if term_matches)
        logger.info(f"Found exact matches for {exact_count}/{len(terms)} terms")

        return matches

    def _find_fuzzy_matches(self, terms: List[str], threshold: float = 95.0) -> Dict[str, List[OMOPMatch]]:
        """Find fuzzy matches for terms using parallel processing"""
        logger.info(f"Finding fuzzy OMOP matches (threshold: {threshold})...")

        # Prepare data for parallel processing
        terms_to_process = [(term, self.preprocess_term(term)) for term in terms]
        lookup_data = self.lookup_df[['term_clean', 'concept_id']].values.tolist()

        # Split into batches for parallel processing
        batch_size = 100
        batches = [terms_to_process[i:i + batch_size] for i in range(0, len(terms_to_process), batch_size)]

        all_matches = {}

        # Process batches in parallel
        with ProcessPoolExecutor(max_workers=4) as executor:
            future_to_batch = {
                executor.submit(self._process_fuzzy_batch, batch, lookup_data, threshold): batch
                for batch in batches
            }

            for future in tqdm(as_completed(future_to_batch), total=len(batches), desc="Fuzzy Matching"):
                batch = future_to_batch[future]
                try:
                    batch_matches = future.result()
                    all_matches.update(batch_matches)
                except Exception as e:
                    logger.error(f"Error processing batch: {e}")
                    # Add empty matches for failed batch
                    for term, _ in batch:
                        all_matches[term] = []

        fuzzy_count = sum(1 for term_matches in all_matches.values() if term_matches)
        logger.info(f"Found fuzzy matches for {fuzzy_count}/{len(terms)} terms")

        return all_matches

    @staticmethod
    def _process_fuzzy_batch(batch: List[Tuple[str, str]], lookup_data: List[Tuple[str, str]], threshold: float) -> Dict[str, List[OMOPMatch]]:
        """Process a batch of terms for fuzzy matching (static method for parallel processing)"""
        batch_matches = {}

        for original_term, cleaned_term in batch:
            if not cleaned_term:
                batch_matches[original_term] = []
                continue

            # Find candidates with similar length
            tlen = len(cleaned_term)
            candidates = [
                (term_clean, concept_id)
                for term_clean, concept_id in lookup_data
                if abs(len(term_clean) - tlen) <= 3
            ]

            if not candidates:
                candidates = lookup_data

            # Extract just the terms for fuzzy matching
            candidate_terms = [term for term, _ in candidates]

            # Perform fuzzy matching
            results = process.extract(
                cleaned_term,
                candidate_terms,
                scorer=fuzz.ratio,
                limit=10
            )

            # Convert to OMOPMatch objects
            term_matches = []
            for matched_term, score, _ in results:
                if score >= threshold:
                    # Find concept_id for matched term
                    concept_id = next(
                        (cid for term, cid in candidates if term == matched_term),
                        None
                    )
                    if concept_id:
                        # Note: We can't access concept cache here, so we'll fill in details later
                        match = OMOPMatch(
                            concept_id=concept_id,
                            concept_name="",  # Will be filled later
                            domain_id="",     # Will be filled later
                            vocabulary_id="",  # Will be filled later
                            score=float(score),
                            match_type="FUZZY"
                        )
                        term_matches.append(match)

            batch_matches[original_term] = term_matches

        return batch_matches

    def map_terms(self, terms: List[str], max_matches: int = 5) -> List[OMOPMappingResult]:
        """Map terms to OMOP concepts"""
        if not self.lookup_df:
            raise RuntimeError("OMOP mapper not initialized. Call initialize() first.")

        logger.info(f"Mapping {len(terms)} terms to OMOP vocabulary...")

        # Find exact matches
        exact_matches = self._find_exact_matches(terms)

        # Find terms that need fuzzy matching
        terms_for_fuzzy = [term for term in terms if not exact_matches.get(term)]

        fuzzy_matches = {}
        if terms_for_fuzzy and self.config.use_fuzzy_matching:
            fuzzy_matches = self._find_fuzzy_matches(
                terms_for_fuzzy,
                threshold=self.config.fuzzy_threshold
            )

        # Combine results
        results = []
        for term in terms:
            term_matches = exact_matches.get(term, []) + fuzzy_matches.get(term, [])

            # Fill in concept details for fuzzy matches
            for match in term_matches:
                if not match.concept_name:  # Fuzzy match missing details
                    concept = self._concept_cache.get(match.concept_id)
                    if concept:
                        match.concept_name = concept.concept_name
                        match.domain_id = concept.domain_id
                        match.vocabulary_id = concept.vocabulary_id
                        match.concept_code = concept.concept_code

            # Sort by score and limit matches
            term_matches.sort(key=lambda x: (x.score, x.match_type == "EXACT"), reverse=True)
            term_matches = term_matches[:max_matches]

            # Determine best match
            best_match = term_matches[0] if term_matches else None

            result = OMOPMappingResult(
                original_term=term,
                cleaned_term=self.preprocess_term(term),
                matches=term_matches,
                best_match=best_match
            )
            results.append(result)

        # Calculate coverage statistics
        matched_count = sum(1 for r in results if r.matches)
        coverage = matched_count / len(terms) * 100 if terms else 0

        logger.info(f"OMOP mapping complete: {matched_count}/{len(terms)} ({coverage:.1f}% coverage)")

        return results

    def get_concept_by_id(self, concept_id: str) -> Optional[OMOPConcept]:
        """Get concept details by ID"""
        return self._concept_cache.get(concept_id)

    def save_results(self, results: List[OMOPMappingResult], output_file: str):
        """Save mapping results to file"""
        # Convert to DataFrame for easy saving
        rows = []
        for result in results:
            base_row = {
                'original_term': result.original_term,
                'cleaned_term': result.cleaned_term,
                'match_count': len(result.matches),
                'best_match_concept_id': result.best_match.concept_id if result.best_match else None,
                'best_match_score': result.best_match.score if result.best_match else None,
                'best_match_domain': result.best_match.domain_id if result.best_match else None
            }

            # Add match details as columns
            for i, match in enumerate(result.matches[:5]):  # Top 5 matches
                base_row.update({
                    f'match_{i+1}_concept_id': match.concept_id,
                    f'match_{i+1}_concept_name': match.concept_name,
                    f'match_{i+1}_domain_id': match.domain_id,
                    f'match_{i+1}_vocabulary_id': match.vocabulary_id,
                    f'match_{i+1}_score': match.score,
                    f'match_{i+1}_match_type': match.match_type
                })

            rows.append(base_row)

        df = pd.DataFrame(rows)
        df.to_csv(output_file, sep='\t', index=False)
        logger.info(f"Saved OMOP mapping results to {output_file}")


def create_omop_mapper(vocab_dir: str, config: OMOPConfig) -> OMOPMapper:
    """Factory function to create OMOP mapper"""
    return OMOPMapper(vocab_dir, config)