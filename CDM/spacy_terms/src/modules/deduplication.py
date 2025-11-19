"""
Multi-layer deduplication module: Exact → Fuzzy → Semantic.
Configurable semantic models with CLI support.
"""

import logging
import numpy as np
from typing import List, Dict, Any, Optional, Set
from dataclasses import dataclass
from collections import defaultdict
from tqdm import tqdm
import re
from rapidfuzz import process, fuzz
from ..config.settings import DeduplicationConfig

logger = logging.getLogger(__name__)


@dataclass
class DeduplicationResult:
    """Result of deduplication process"""
    original_count: int
    final_count: int
    exact_removed: int
    fuzzy_removed: int
    semantic_removed: int
    deduplicated_terms: List[Dict[str, Any]]


class Deduplicator:
    """Multi-layer deduplication with configurable semantic models"""

    def __init__(self, config: DeduplicationConfig):
        self.config = config
        self.semantic_model = None
        self.embeddings_cache = {}
        self._initialize_semantic_model()

    def _initialize_semantic_model(self):
        """Initialize semantic model based on configuration"""
        if not self.config.semantic_enabled:
            logger.info("Semantic deduplication disabled")
            return

        try:
            model_name = self.config.semantic_models[self.config.default_semantic_model]
            logger.info(f"Loading semantic model: {model_name}")

            from sentence_transformers import SentenceTransformer
            self.semantic_model = SentenceTransformer(model_name)
            logger.info(f"✓ Semantic model loaded: {self.config.default_semantic_model}")

        except ImportError:
            logger.error("sentence-transformers not installed. Semantic deduplication disabled.")
            self.config.semantic_enabled = False
        except Exception as e:
            logger.error(f"Failed to load semantic model: {e}")
            self.config.semantic_enabled = False

    def _normalize_term(self, term: str) -> str:
        """Normalize term for comparison"""
        if not term:
            return ""

        term = term.lower().strip()
        # Remove extra whitespace
        term = re.sub(r'\s+', ' ', term)
        # Remove common punctuation at start/end
        term = term.strip('.,;:!?()[]{}"\'')
        return term

    def _exact_deduplication(self, terms: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Perform exact deduplication"""
        if not self.config.exact_enabled:
            return terms

        logger.info("Starting exact deduplication...")
        seen_terms = set()
        deduplicated = []

        for term_data in terms:
            term = term_data.get('term', '')
            normalized = self._normalize_term(term)

            if normalized and normalized not in seen_terms:
                seen_terms.add(normalized)
                deduplicated.append(term_data)

        removed = len(terms) - len(deduplicated)
        logger.info(f"Exact deduplication: {len(terms)} → {len(deduplicated)} (removed {removed})")

        return deduplicated

    def _fuzzy_deduplication(self, terms: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Perform fuzzy deduplication using rapidfuzz"""
        if not self.config.fuzzy_enabled or len(terms) <= 1:
            return terms

        logger.info(f"Starting fuzzy deduplication (threshold: {self.config.fuzzy_threshold})...")

        deduplicated = []
        term_list = [term_data.get('term', '') for term_data in terms]
        normalized_terms = [self._normalize_term(term) for term in term_list]

        # Track which indices to keep
        keep_indices = set(range(len(terms)))

        for i in tqdm(range(len(terms)), desc="Fuzzy deduplication"):
            if i not in keep_indices:
                continue

            current_term = normalized_terms[i]
            if not current_term:
                continue

            # Find similar terms after current position
            search_start = i + 1
            if search_start >= len(terms):
                continue

            # Get candidates within reasonable length range
            candidates = []
            candidate_indices = []

            for j in range(search_start, len(terms)):
                if j not in keep_indices:
                    continue

                candidate_term = normalized_terms[j]
                if not candidate_term:
                    continue

                # Only consider terms with similar length
                len_diff = abs(len(current_term) - len(candidate_term))
                if len_diff <= max(3, len(current_term) // 3):
                    candidates.append(candidate_term)
                    candidate_indices.append(j)

            if not candidates:
                continue

            # Find fuzzy matches
            matches = process.extract(
                current_term,
                candidates,
                scorer=fuzz.ratio,
                limit=len(candidates)
            )

            # Remove terms above threshold
            for match_term, score, _ in matches:
                if score >= self.config.fuzzy_threshold * 100:  # rapidfuzz uses 0-100 scale
                    # Find the index of this match
                    match_idx = candidates.index(match_term)
                    original_idx = candidate_indices[match_idx]
                    keep_indices.discard(original_idx)

        # Build deduplicated list
        for idx in sorted(keep_indices):
            deduplicated.append(terms[idx])

        removed = len(terms) - len(deduplicated)
        logger.info(f"Fuzzy deduplication: {len(terms)} → {len(deduplicated)} (removed {removed})")

        return deduplicated

    def _get_embeddings(self, terms: List[str]) -> np.ndarray:
        """Get embeddings for terms, using cache when possible"""
        terms_to_embed = []
        indices = []
        embeddings = []

        # Check cache first
        for i, term in enumerate(terms):
            if term in self.embeddings_cache:
                embeddings.append(self.embeddings_cache[term])
            else:
                terms_to_embed.append(term)
                indices.append(i)

        # Get new embeddings
        if terms_to_embed:
            logger.info(f"Computing embeddings for {len(terms_to_embed)} terms...")
            new_embeddings = self.semantic_model.encode(
                terms_to_embed,
                batch_size=32,
                show_progress_bar=True,
                normalize_embeddings=True
            )

            # Cache new embeddings
            for term, embedding in zip(terms_to_embed, new_embeddings):
                self.embeddings_cache[term] = embedding

            # Insert embeddings in correct positions
            for idx, embedding in zip(indices, new_embeddings):
                embeddings.insert(idx, embedding)

        return np.array(embeddings)

    def _semantic_deduplication(self, terms: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Perform semantic deduplication using embeddings"""
        if not self.config.semantic_enabled or not self.semantic_model or len(terms) <= 1:
            return terms

        logger.info(f"Starting semantic deduplication (threshold: {self.config.semantic_threshold})...")

        # Extract terms for embedding
        term_list = [term_data.get('term', '') for term_data in terms]
        normalized_terms = [self._normalize_term(term) for term in term_list]

        # Get embeddings
        embeddings = self._get_embeddings(normalized_terms)

        # Perform semantic clustering
        keep_indices = set(range(len(terms)))

        for i in tqdm(range(len(terms)), desc="Semantic deduplication"):
            if i not in keep_indices:
                continue

            # Calculate similarity with remaining terms
            similarities = np.dot(embeddings[i:i+1], embeddings.T).flatten()

            # Find similar terms (excluding self)
            similar_indices = np.where((similarities >= self.config.semantic_threshold) &
                                     (np.arange(len(terms)) > i))[0]

            # Remove similar terms
            for j in similar_indices:
                if j in keep_indices:
                    # Keep the one with higher relevance score or frequency
                    current_score = terms[i].get('relevance_score', 0) + terms[i].get('frequency', 0) * 0.1
                    other_score = terms[j].get('relevance_score', 0) + terms[j].get('frequency', 0) * 0.1

                    if current_score >= other_score:
                        keep_indices.discard(j)
                    else:
                        keep_indices.discard(i)
                        break

        # Build deduplicated list
        deduplicated = [terms[i] for i in sorted(keep_indices)]

        removed = len(terms) - len(deduplicated)
        logger.info(f"Semantic deduplication: {len(terms)} → {len(deduplicated)} (removed {removed})")

        return deduplicated

    def deduplicate_terms(self, terms: List[Dict[str, Any]]) -> DeduplicationResult:
        """Perform complete multi-layer deduplication"""
        logger.info(f"Starting multi-layer deduplication for {len(terms)} terms...")

        original_count = len(terms)

        # Step 1: Exact deduplication
        after_exact = self._exact_deduplication(terms)
        exact_removed = original_count - len(after_exact)

        # Step 2: Fuzzy deduplication
        after_fuzzy = self._fuzzy_deduplication(after_exact)
        fuzzy_removed = len(after_exact) - len(after_fuzzy)

        # Step 3: Semantic deduplication
        after_semantic = self._semantic_deduplication(after_fuzzy)
        semantic_removed = len(after_fuzzy) - len(after_semantic)

        result = DeduplicationResult(
            original_count=original_count,
            final_count=len(after_semantic),
            exact_removed=exact_removed,
            fuzzy_removed=fuzzy_removed,
            semantic_removed=semantic_removed,
            deduplicated_terms=after_semantic
        )

        total_reduction = (original_count - len(after_semantic)) / original_count * 100 if original_count > 0 else 0
        logger.info(f"Deduplication complete: {original_count} → {len(after_semantic)} ({total_reduction:.1f}% reduction)")

        return result


def create_deduplicator(config: DeduplicationConfig) -> Deduplicator:
    """Factory function to create deduplicator"""
    return Deduplicator(config)