"""
Comprehensive deduplication module with fuzzy and semantic deduplication.
Implements multi-layer deduplication strategy as requested.
"""

import logging
import time
from typing import List, Dict, Set, Optional, Tuple, Any
from difflib import SequenceMatcher
from collections import defaultdict

# Import availability checks
try:
    from thefuzz import fuzz, process
    THEFUZZ_AVAILABLE = True
except ImportError:
    THEFUZZ_AVAILABLE = False
    fuzz = None
    process = None

try:
    from sentence_transformers import SentenceTransformer, util
    import numpy as np
    SENTENCE_TRANSFORMERS_AVAILABLE = True
except ImportError:
    SENTENCE_TRANSFORMERS_AVAILABLE = False
    SentenceTransformer = None
    util = None
    np = None

from ..config.settings import DeduplicationConfig

logger = logging.getLogger(__name__)


class ExactDeduplicator:
    """Exact deduplication with case normalization."""

    def __init__(self, config: DeduplicationConfig):
        self.config = config

    def deduplicate(self, terms: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Remove exact duplicates."""
        if not terms:
            return terms

        logger.info(f"🔄 Performing exact deduplication on {len(terms)} terms...")

        seen_terms = set()
        deduplicated = []

        for term_data in terms:
            term_key = term_data['term']

            if not self.config.case_sensitive:
                term_key = term_key.lower()

            if term_key not in seen_terms:
                seen_terms.add(term_key)
                deduplicated.append(term_data)

        removed_count = len(terms) - len(deduplicated)
        logger.info(f"✅ Exact deduplication: removed {removed_count} exact duplicates")

        return deduplicated


class FuzzyDeduplicator:
    """Advanced fuzzy deduplication using multiple similarity metrics."""

    def __init__(self, config: DeduplicationConfig):
        self.config = config
        if not THEFUZZ_AVAILABLE:
            logger.warning("⚠️ thefuzz not available. Fuzzy deduplication disabled.")

    def deduplicate(self, terms: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Perform fuzzy deduplication."""
        if not THEFUZZ_AVAILABLE or not terms:
            return terms

        logger.info(f"🔄 Performing fuzzy deduplication on {len(terms)} terms...")
        logger.info(f"📊 Fuzzy threshold: {self.config.fuzzy_threshold}%")

        start_time = time.time()
        deduplicated = []
        seen_terms = set()

        for term_data in terms:
            term = term_data['term']
            term_lower = term.lower()

            # Check for fuzzy matches with existing terms
            best_match = None
            best_score = 0

            for existing_term in seen_terms:
                similarity = self._calculate_fuzzy_similarity(term, existing_term)
                if similarity > best_score:
                    best_score = similarity
                    best_match = existing_term

            # If no good match found, keep the term
            if best_score < self.config.fuzzy_threshold:
                seen_terms.add(term_lower)
                deduplicated.append(term_data)
                term_data['fuzzy_matches'] = []
            else:
                # Add to best match's fuzzy matches
                for existing_data in deduplicated:
                    if existing_data['term'].lower() == best_match:
                        if 'fuzzy_matches' not in existing_data:
                            existing_data['fuzzy_matches'] = []
                        existing_data['fuzzy_matches'].append({
                            'term': term,
                            'similarity': best_score,
                            'frequency': term_data['frequency']
                        })
                        # Merge metadata
                        self._merge_term_metadata(existing_data, term_data, best_score)
                        break

        removed_count = len(terms) - len(deduplicated)
        processing_time = time.time() - start_time

        logger.info(f"✅ Fuzzy deduplication completed in {processing_time:.2f}s")
        logger.info(f"📊 Removed {removed_count} fuzzy duplicates")
        logger.info(f"📊 Retained {len(deduplicated)} unique terms")

        return deduplicated

    def _calculate_fuzzy_similarity(self, term1: str, term2: str) -> int:
        """Calculate fuzzy similarity using the configured scorer."""
        if not fuzz:
            return 0

        scorers = {
            'ratio': fuzz.ratio,
            'partial_ratio': fuzz.partial_ratio,
            'token_sort_ratio': fuzz.token_sort_ratio,
            'token_set_ratio': fuzz.token_set_ratio
        }

        scorer_func = scorers.get(self.config.fuzzy_scorer, fuzz.ratio)
        return scorer_func(term1.lower(), term2.lower())

    def _merge_term_metadata(self, base_term: Dict[str, Any], duplicate_term: Dict[str, Any], similarity: int):
        """Merge metadata from duplicate term into base term."""
        # Merge frequencies
        base_term['frequency'] += duplicate_term['frequency']

        # Merge models found
        for model in duplicate_term.get('models_found', []):
            if model not in base_term.get('models_found', []):
                base_term['models_found'].append(model)

        # Merge file IDs
        for file_id in duplicate_term.get('file_ids', []):
            if file_id not in base_term.get('file_ids', []):
                base_term['file_ids'].append(file_id)

        # Merge examples
        existing_examples = [ex.lower() for ex in base_term.get('examples', [])]
        for example in duplicate_term.get('examples', []):
            if example.lower() not in existing_examples:
                base_term['examples'].append(example)

        # Merge synonyms
        if 'synonyms' in base_term and 'synonyms' in duplicate_term:
            base_term['synonyms'].update(duplicate_term['synonyms'])

        # Add similarity score
        if 'fuzzy_matches' not in base_term:
            base_term['fuzzy_matches'] = []
        base_term['fuzzy_matches'].append({
            'term': duplicate_term['term'],
            'similarity': similarity,
            'frequency': duplicate_term['frequency']
        })


class SemanticDeduplicator:
    """Advanced semantic deduplication using sentence transformer embeddings."""

    def __init__(self, config: DeduplicationConfig):
        self.config = config
        self.semantic_model = None
        self._load_semantic_model()

    def _load_semantic_model(self):
        """Load the semantic model based on user choice."""
        if not SENTENCE_TRANSFORMERS_AVAILABLE:
            logger.warning("⚠️ sentence-transformers not available. Semantic deduplication disabled.")
            return

        try:
            model_name = self.config.semantic_models[self.config.semantic_model_choice]
            logger.info(f"🧠 Loading semantic model: {model_name}")
            self.semantic_model = SentenceTransformer(model_name)
            logger.info(f"✅ Loaded semantic model: {self.config.semantic_model_choice}")
        except Exception as e:
            logger.error(f"❌ Error loading semantic model: {e}")
            self.semantic_model = None

    def deduplicate(self, terms: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Perform semantic deduplication."""
        if not self.semantic_model or not terms:
            return terms

        logger.info(f"🔄 Performing semantic deduplication on {len(terms)} terms...")
        logger.info(f"📊 Semantic threshold: {self.config.semantic_threshold}")
        logger.info(f"🧠 Using model: {self.config.semantic_model_choice}")

        start_time = time.time()

        # Create embeddings for all terms
        term_texts = [term_data['term'] for term_data in terms]
        logger.info("🔢 Computing embeddings...")

        # Process in batches to avoid memory issues
        batch_size = self.config.batch_size_semantic
        all_embeddings = []

        for i in range(0, len(term_texts), batch_size):
            batch_texts = term_texts[i:i + batch_size]
            batch_embeddings = self.semantic_model.encode(
                batch_texts,
                convert_to_tensor=True,
                show_progress_bar=False
            )
            all_embeddings.append(batch_embeddings)

        # Concatenate all embeddings
        if len(all_embeddings) > 1:
            embeddings = np.concatenate(all_embeddings, axis=0)
        else:
            embeddings = all_embeddings[0]

        logger.info(f"✅ Computed {len(embeddings)} embeddings")

        # Calculate similarity matrix
        logger.info("🔍 Computing similarity matrix...")
        similarity_matrix = util.cos_sim(embeddings, embeddings).numpy()

        # Apply semantic deduplication
        deduplicated = self._apply_semantic_deduplication(terms, similarity_matrix)

        processing_time = time.time() - start_time
        removed_count = len(terms) - len(deduplicated)

        logger.info(f"✅ Semantic deduplication completed in {processing_time:.2f}s")
        logger.info(f"📊 Removed {removed_count} semantic duplicates")
        logger.info(f"📊 Retained {len(deduplicated)} unique terms")

        return deduplicated

    def _apply_semantic_deduplication(self, terms: List[Dict[str, Any]],
                                   similarity_matrix: np.ndarray) -> List[Dict[str, Any]]:
        """Apply semantic deduplication using similarity matrix."""
        n_terms = len(terms)
        processed = set()
        deduplicated = []

        for i in range(n_terms):
            if i in processed:
                continue

            current_term = terms[i].copy()
            current_term['semantic_matches'] = []

            # Find all semantically similar terms
            for j in range(i + 1, n_terms):
                if j in processed:
                    continue

                similarity = similarity_matrix[i][j]
                if similarity >= self.config.semantic_threshold:
                    processed.add(j)

                    # Merge metadata
                    self._merge_semantic_metadata(current_term, terms[j], similarity)

                    current_term['semantic_matches'].append({
                        'term': terms[j]['term'],
                        'similarity': float(similarity),
                        'frequency': terms[j]['frequency']
                    })

            processed.add(i)
            deduplicated.append(current_term)

        return deduplicated

    def _merge_semantic_metadata(self, base_term: Dict[str, Any], duplicate_term: Dict[str, Any],
                               similarity: float):
        """Merge metadata from semantically duplicate term."""
        # Merge frequencies with semantic weight
        semantic_weight = similarity
        base_term['frequency'] += int(duplicate_term['frequency'] * semantic_weight)

        # Merge models found
        for model in duplicate_term.get('models_found', []):
            if model not in base_term.get('models_found', []):
                base_term['models_found'].append(model)

        # Merge file IDs
        for file_id in duplicate_term.get('file_ids', []):
            if file_id not in base_term.get('file_ids', []):
                base_term['file_ids'].append(file_id)

        # Merge examples (keep highest quality examples)
        existing_examples = [ex.lower() for ex in base_term.get('examples', [])]
        for example in duplicate_term.get('examples', []):
            if example.lower() not in existing_examples:
                base_term['examples'].append(example)

        # Merge synonyms
        if 'synonyms' in base_term and 'synonyms' in duplicate_term:
            base_term['synonyms'].update(duplicate_term['synonyms'])

        # Update semantic score
        base_term['max_semantic_similarity'] = max(
            base_term.get('max_semantic_similarity', 0),
            similarity
        )


class ComprehensiveDeduplicator:
    """
    Comprehensive deduplication orchestrator that applies all deduplication methods.
    Implements the multi-layer strategy: Exact -> Fuzzy -> Semantic
    """

    def __init__(self, config: DeduplicationConfig):
        self.config = config

        # Initialize deduplicators
        self.exact_deduplicator = ExactDeduplicator(config)
        self.fuzzy_deduplicator = FuzzyDeduplicator(config)
        self.semantic_deduplicator = SemanticDeduplicator(config)

        # Statistics
        self.deduplication_stats = {
            'original_count': 0,
            'after_exact': 0,
            'after_fuzzy': 0,
            'after_semantic': 0,
            'total_removed': 0,
            'processing_time': 0
        }

    def deduplicate(self, terms: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Apply comprehensive deduplication pipeline.

        Args:
            terms: List of term dictionaries to deduplicate

        Returns:
            Deduplicated list of terms
        """
        if not terms:
            return terms

        logger.info("=" * 80)
        logger.info("🚀 STARTING COMPREHENSIVE DEDUPLICATION PIPELINE")
        logger.info("=" * 80)

        start_time = time.time()
        self.deduplication_stats['original_count'] = len(terms)

        # Step 1: Exact deduplication
        if self.config.normalize_terms:
            logger.info("\n📋 STEP 1: EXACT DEDUPLICATION")
            terms = self.exact_deduplicator.deduplicate(terms)
            self.deduplication_stats['after_exact'] = len(terms)

        # Step 2: Fuzzy deduplication
        logger.info("\n📋 STEP 2: FUZZY DEDUPLICATION")
        terms = self.fuzzy_deduplicator.deduplicate(terms)
        self.deduplication_stats['after_fuzzy'] = len(terms)

        # Step 3: Semantic deduplication
        logger.info("\n📋 STEP 3: SEMANTIC DEDUPLICATION")
        terms = self.semantic_deduplicator.deduplicate(terms)
        self.deduplication_stats['after_semantic'] = len(terms)

        # Calculate final statistics
        self.deduplication_stats['total_removed'] = (
            self.deduplication_stats['original_count'] - self.deduplication_stats['after_semantic']
        )
        self.deduplication_stats['processing_time'] = time.time() - start_time

        logger.info("\n" + "=" * 80)
        logger.info("✅ COMPREHENSIVE DEDUPLICATION COMPLETED")
        logger.info("=" * 80)
        logger.info(f"📊 Original terms: {self.deduplication_stats['original_count']:,}")
        logger.info(f"📊 After exact deduplication: {self.deduplication_stats['after_exact']:,}")
        logger.info(f"📊 After fuzzy deduplication: {self.deduplication_stats['after_fuzzy']:,}")
        logger.info(f"📊 After semantic deduplication: {self.deduplication_stats['after_semantic']:,}")
        logger.info(f"📊 Total removed: {self.deduplication_stats['total_removed']:,}")
        logger.info(f"⏱️  Processing time: {self.deduplication_stats['processing_time']:.2f}s")
        logger.info("=" * 80)

        return terms

    def get_deduplication_stats(self) -> Dict[str, Any]:
        """Get comprehensive deduplication statistics."""
        return self.deduplication_stats.copy()

    def export_deduplication_report(self, output_path: str):
        """Export detailed deduplication report."""
        import json
        from pathlib import Path

        report = {
            'deduplication_config': {
                'fuzzy_threshold': self.config.fuzzy_threshold,
                'fuzzy_scorer': self.config.fuzzy_scorer,
                'semantic_threshold': self.config.semantic_threshold,
                'semantic_model': self.config.semantic_model_choice,
                'case_sensitive': self.config.case_sensitive,
                'normalize_terms': self.config.normalize_terms
            },
            'statistics': self.get_deduplication_stats(),
            'methods_applied': [
                'exact_deduplication' if self.config.normalize_terms else 'skipped',
                'fuzzy_deduplication' if THEFUZZ_AVAILABLE else 'unavailable',
                'semantic_deduplication' if SENTENCE_TRANSFORMERS_AVAILABLE and self.semantic_deduplicator.semantic_model else 'unavailable'
            ]
        }

        output_file = Path(output_path) / "deduplication_report.json"
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        logger.info(f"📄 Deduplication report exported to: {output_file}")