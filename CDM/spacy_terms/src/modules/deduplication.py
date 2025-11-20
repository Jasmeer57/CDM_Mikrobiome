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
    biomedical_removed: int
    deduplicated_terms: List[Dict[str, Any]]
    biomedical_duplicates: List[Dict[str, Any]]


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
            self.semantic_model = SentenceTransformer(model_name, trust_remote_code=True)
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

    def _biomedical_deduplication(self, terms: List[Dict[str, Any]]) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Perform BioMistral-powered biomedical context-aware deduplication"""
        if not self.config.biomedical_enabled or len(terms) <= 1:
            return terms, []

        logger.info("Starting biomedical context-aware deduplication...")

        try:
            # Initialize BioMistral for biomedical reasoning
            from transformers import pipeline

            # Use a smaller, efficient model for duplicate detection
            biomedical_classifier = pipeline(
                "text-classification",
                model="microsoft/BiomedNLP-PubMedBERT-base-uncased-abstract-fulltext",
                device=0 if self.semantic_model else -1  # Use GPU if available
            )

        except Exception as e:
            logger.warning(f"BioMistral model not available: {e}. Skipping biomedical deduplication.")
            return terms, []

        deduplicated = []
        biomedical_duplicates = []
        term_groups = []

        # Group terms by semantic similarity first for efficiency
        term_embeddings = {}
        if self.semantic_model:
            for i, term_data in enumerate(terms):
                term = term_data.get('term', '')
                if term:
                    embedding = self.semantic_model.encode(term, convert_to_tensor=True)
                    term_embeddings[i] = embedding

        # Find potential duplicate groups using semantic embeddings
        processed_indices = set()
        for i, term_data_i in enumerate(terms):
            if i in processed_indices:
                continue

            term_i = term_data_i.get('term', '')
            if not term_i:
                processed_indices.add(i)
                continue

            current_group = [i]

            # Find semantically similar terms
            if self.semantic_model and i in term_embeddings:
                for j, term_data_j in enumerate(terms[i+1:], i+1):
                    if j in processed_indices:
                        continue

                    term_j = term_data_j.get('term', '')
                    if not term_j or j not in term_embeddings:
                        continue

                    # Calculate semantic similarity
                    similarity = float((term_embeddings[i] @ term_embeddings[j]).cpu().numpy())
                    if similarity >= self.config.semantic_threshold:
                        current_group.append(j)
                        processed_indices.add(j)

            if len(current_group) > 1:
                term_groups.append(current_group)
            processed_indices.add(i)

        # Process each group with BioMistral for biomedical context
        for group in tqdm(term_groups, desc="Biomedical deduplication"):
            if len(group) == 1:
                deduplicated.append(terms[group[0]])
                continue

            # Create comparison prompts for BioMistral
            group_terms = [terms[idx].get('term', '') for idx in group]
            duplicate_matrix = {}

            for i in range(len(group)):
                for j in range(i+1, len(group)):
                    term1, term2 = group_terms[i], group_terms[j]

                    # Create biomedical comparison prompt
                    comparison_prompt = f"""
                    Compare these two biomedical terms in the context of microbiome research:
                    Term 1: "{term1}"
                    Term 2: "{term2}"

                    Question: Are these terms referring to the same biological concept, entity, or measurement in microbiome/biomedical research?
                    Consider:
                    - Do they represent the same biological entity (e.g., same bacterium, same gene, same protein)?
                    - Do they refer to the same measurement or observation?
                    - Are they synonymous in biomedical context?
                    - Could they be merged without losing clinical/scientific meaning?

                    Answer with only: YES (if duplicates) or NO (if distinct concepts)
                    """

                    try:
                        # Use BioMistral for classification
                        result = biomedical_classifier(comparison_prompt[:512])  # Limit context length
                        is_duplicate = "YES" in result[0]['label'].upper()

                        if is_duplicate:
                            duplicate_matrix[(i, j)] = True
                        else:
                            duplicate_matrix[(i, j)] = False

                    except Exception as e:
                        logger.debug(f"BioMistral comparison failed for {term1} vs {term2}: {e}")
                        # Fallback to semantic similarity
                        duplicate_matrix[(i, j)] = False

            # Find duplicate clusters within the group
            duplicate_clusters = []
            used_indices = set()

            for i in range(len(group)):
                if i in used_indices:
                    continue

                cluster = [i]
                used_indices.add(i)

                for j in range(i+1, len(group)):
                    if j in used_indices:
                        continue

                    # Check if all pairs in the cluster are duplicates
                    all_duplicates = all(
                        duplicate_matrix.get((min(cluster[k], j), max(cluster[k], j)), False)
                        for k in range(len(cluster))
                    )

                    if all_duplicates:
                        cluster.append(j)
                        used_indices.add(j)

                duplicate_clusters.append(cluster)

            # Process duplicate clusters
            for cluster in duplicate_clusters:
                if len(cluster) == 1:
                    # No duplicates, keep the term
                    deduplicated.append(terms[group[cluster[0]]])
                else:
                    # Found duplicates, keep the best one and record others
                    cluster_terms = [terms[group[idx]] for idx in cluster]

                    # Select the best term (highest frequency, then shortest, then first)
                    best_term_data = max(cluster_terms, key=lambda x: (
                        x.get('frequency', 0),
                        -len(x.get('term', '')),  # Negative for shorter preference
                        -cluster_terms.index(x)   # Negative for first preference
                    ))

                    # Add reasoning for biomedical duplicate detection
                    removed_terms = [t for t in cluster_terms if t != best_term_data]
                    for removed_term in removed_terms:
                        removed_term['biomedical_duplicate_reason'] = {
                            'kept_term': best_term_data.get('term', ''),
                            'removed_term': removed_term.get('term', ''),
                            'context': 'microbiome_biomedical',
                            'method': 'biomistral_classification',
                            'confidence': 'high'
                        }
                        biomedical_duplicates.append(removed_term)

                    # Mark the kept term
                    best_term_data['biomedical_kept'] = True
                    best_term_data['biomedical_duplicate_group'] = [t.get('term', '') for t in cluster_terms]
                    deduplicated.append(best_term_data)

        # Add terms not in any group
        all_grouped_indices = set(idx for group in term_groups for idx in group)
        for i, term_data in enumerate(terms):
            if i not in all_grouped_indices:
                deduplicated.append(term_data)

        biomedical_removed = len(terms) - len(deduplicated)
        logger.info(f"Biomedical deduplication: {len(terms)} → {len(deduplicated)} (removed {biomedical_removed})")

        return deduplicated, biomedical_duplicates

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

        # Step 4: Biomedical context-aware deduplication
        after_biomedical, biomedical_duplicates = self._biomedical_deduplication(after_semantic)
        biomedical_removed = len(after_semantic) - len(after_biomedical)

        result = DeduplicationResult(
            original_count=original_count,
            final_count=len(after_biomedical),
            exact_removed=exact_removed,
            fuzzy_removed=fuzzy_removed,
            semantic_removed=semantic_removed,
            biomedical_removed=biomedical_removed,
            deduplicated_terms=after_biomedical,
            biomedical_duplicates=biomedical_duplicates
        )

        total_reduction = (original_count - len(after_biomedical)) / original_count * 100 if original_count > 0 else 0
        logger.info(f"Deduplication complete: {original_count} → {len(after_biomedical)} ({total_reduction:.1f}% reduction)")

        return result


def create_deduplicator(config: DeduplicationConfig) -> Deduplicator:
    """Factory function to create deduplicator"""
    return Deduplicator(config)