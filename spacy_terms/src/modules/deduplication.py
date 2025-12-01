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
from src.config.settings import DeduplicationConfig

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
            logger.info(f"Loading semantic model: {self.config.default_semantic_model}")

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
        """Biomedical context-aware deduplication (Cross-Encoder)"""
        if not self.config.biomedical_enabled or len(terms) < 2:
            return terms, []

        try:
            from sentence_transformers import CrossEncoder
        except ImportError:
            logger.warning("sentence-transformers not installed. Biomedical deduplication disabled.")
            return terms, []

        logger.info("Running biomedical deduplication (Cross-Encoder)...")
        
        # Load Cross-Encoder model
        try:
            model_name = "cross-encoder/stsb-roberta-base"
            logger.info(f"Loading Cross-Encoder: {model_name}")
            model = CrossEncoder(model_name)
        except Exception as e:
            logger.warning(f"Failed to load Cross-Encoder model: {e}")
            return terms, []

        keep_indices = set(range(len(terms)))
        term_strings = [t.get('term', '') for t in terms]
        
        # 1. Identify candidate pairs to check
        potential_pairs = []
        
        if self.semantic_model:
            # Use embeddings to find candidates efficiently
            embeddings = self._get_embeddings(term_strings)
            from sentence_transformers.util import cos_sim
            scores = cos_sim(embeddings, embeddings)
            
            for i in range(len(terms)):
                if i not in keep_indices: continue
                for j in range(i + 1, len(terms)):
                    if j not in keep_indices: continue
                    # Check if semantically somewhat close (e.g. > 0.75)
                    if scores[i][j] > 0.75: 
                        potential_pairs.append((i, j))
        else:
            # Fallback: Check for word overlap
            for i in range(len(terms)):
                if i not in keep_indices: continue
                for j in range(i + 1, len(terms)):
                    if j not in keep_indices: continue
                    words_i = set(term_strings[i].split())
                    words_j = set(term_strings[j].split())
                    if words_i.intersection(words_j):
                        potential_pairs.append((i, j))

        if not potential_pairs:
            return terms, []

        # 2. Score pairs with Cross-Encoder
        logger.info(f"Checking {len(potential_pairs)} candidate pairs with Cross-Encoder...")
        
        biomedical_duplicates = []
        
        # Prepare pairs for batch processing
        sentence_pairs = [[term_strings[i], term_strings[j]] for i, j in potential_pairs]
        
        try:
            similarity_scores = model.predict(sentence_pairs)
            
            for k, score in enumerate(similarity_scores):
                i, j = potential_pairs[k]
                
                # Threshold for "Duplicate" in biomedical context
                if score > 0.85:
                    # Keep the one that looks "better" (longer or more frequent)
                    if len(term_strings[i]) < len(term_strings[j]):
                        if j in keep_indices: # Ensure not already removed
                            keep_indices.discard(i)
                            biomedical_duplicates.append(terms[i])
                    else:
                        if i in keep_indices:
                            keep_indices.discard(j)
                            biomedical_duplicates.append(terms[j])
                        
        except Exception as e:
            logger.warning(f"Cross-Encoder check failed: {e}")

        return [terms[i] for i in sorted(keep_indices)], biomedical_duplicates

    def _correct_typos(self, terms: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Correct typos by merging terms that are lexically and semantically very similar.
        Uses MiniLM for semantic confirmation if available.
        """
        if len(terms) < 2: return terms
        
        logger.info("Running typo correction...")
        try:
            from rapidfuzz import fuzz
        except ImportError:
            return terms

        # Sort by frequency (descending) then length (descending)
        # We assume higher frequency terms are more likely to be "correct"
        terms.sort(key=lambda x: (x.get('frequency', 0), len(x.get('term', ''))), reverse=True)
        
        keep_indices = set(range(len(terms)))
        term_strings = [t.get('term', '') for t in terms]
        
        # Pre-compute embeddings if semantic model is available
        embeddings = None
        if self.semantic_model:
            embeddings = self._get_embeddings(term_strings)
            from sentence_transformers.util import cos_sim
            cosine_scores = cos_sim(embeddings, embeddings)

        for i in range(len(terms)):
            if i not in keep_indices: continue
            
            for j in range(i + 1, len(terms)):
                if j not in keep_indices: continue
                
                s1 = term_strings[i]
                s2 = term_strings[j]
                
                # 1. Lexical Check (High Fuzzy Ratio)
                # Ratio > 95 means very few character differences (likely typo)
                lexical_score = fuzz.ratio(s1, s2)
                if lexical_score < 90: 
                    continue
                    
                # 2. Semantic Confirmation (if model available)
                # If lexically similar but semantically different (rare, but possible), don't merge
                if self.semantic_model:
                    semantic_score = cosine_scores[i][j]
                    if semantic_score < 0.85: # Should be very high for typos
                        continue
                
                # If we reach here, s2 is likely a typo of s1 (since s1 is more frequent/longer)
                # Merge s2 into s1
                # Update s1's frequency
                terms[i]['frequency'] = terms[i].get('frequency', 1) + terms[j].get('frequency', 1)
                
                # Record the correction
                terms[i]['typo_corrections'] = terms[i].get('typo_corrections', [])
                terms[i]['typo_corrections'].append(s2)
                
                keep_indices.discard(j)
                    
        return [terms[i] for i in sorted(keep_indices)]

    def _aggressive_dedup(self, terms: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Final aggressive pass to remove any remaining near-duplicates"""
        if len(terms) < 2: return terms
        
        logger.info("Running aggressive final deduplication...")
        try:
            from rapidfuzz import fuzz
        except ImportError:
            return terms
            
        # Sort by length descending (keep longer/more specific terms usually)
        terms.sort(key=lambda x: len(x.get('term', '')), reverse=True)
        keep_indices = set(range(len(terms)))
        term_strings = [t.get('term', '') for t in terms]
        
        for i in range(len(terms)):
            if i not in keep_indices: continue
            
            for j in range(i + 1, len(terms)):
                if j not in keep_indices: continue
                
                s1 = term_strings[i]
                s2 = term_strings[j]
                
                if not s1 or not s2: continue
                
                # Substring check
                if s2 in s1: # s2 is shorter and inside s1
                    # e.g. "gut microbiome" (s1) vs "microbiome" (s2) -> Keep s1
                    keep_indices.discard(j)
                    continue
                    
                # High fuzzy match
                if fuzz.ratio(s1, s2) > 92:
                    keep_indices.discard(j)
                    
        return [terms[i] for i in sorted(keep_indices)]

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

        # Step 5: Semantic Quality Filter (New)
        after_semantic_filter = self._semantic_quality_filter(after_biomedical)
        semantic_filter_removed = len(after_biomedical) - len(after_semantic_filter)

        # Step 6: Typo Correction
        after_typo = self._correct_typos(after_semantic_filter)
        typo_removed = len(after_semantic_filter) - len(after_typo)

        # Step 7: Aggressive Final Pass
        after_aggressive = self._aggressive_dedup(after_typo)
        aggressive_removed = len(after_typo) - len(after_aggressive)

        result = DeduplicationResult(
            original_count=original_count,
            final_count=len(after_aggressive),
            exact_removed=exact_removed,
            fuzzy_removed=fuzzy_removed,
            semantic_removed=semantic_removed,
            biomedical_removed=biomedical_removed + semantic_filter_removed + typo_removed + aggressive_removed, 
            deduplicated_terms=after_aggressive,
            biomedical_duplicates=biomedical_duplicates
        )

        total_reduction = (original_count - len(after_aggressive)) / original_count * 100 if original_count > 0 else 0
        logger.info(f"Deduplication complete: {original_count} → {len(after_aggressive)} ({total_reduction:.1f}% reduction)")

    def _semantic_quality_filter(self, terms: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Filter out terms that are semantically similar to generic research concepts.
        Uses MiniLM embeddings.
        """
        if not self.semantic_model or not terms:
            return terms
            
        logger.info("Running Semantic Quality Filter...")
        
        # Prototypes of generic/noise concepts
        NOISE_PROTOTYPES = [
            "scientific study", "research analysis", "statistical method", "data collection",
            "experimental result", "clinical trial", "literature review", "author contribution",
            "funding source", "conflict of interest", "copyright statement", "figure legend",
            "table caption", "supplementary material", "university department", "correspondence address",
            "p-value", "confidence interval", "standard deviation", "sample size"
        ]
        
        term_strings = [t.get('term', '') for t in terms]
        
        # Encode terms and noise prototypes
        embeddings = self._get_embeddings(term_strings)
        noise_embeddings = self._get_embeddings(NOISE_PROTOTYPES)
        
        from sentence_transformers.util import cos_sim
        # Shape: [num_terms, num_noise]
        scores = cos_sim(embeddings, noise_embeddings)
        
        keep_indices = []
        for i in range(len(terms)):
            # Check max similarity to ANY noise prototype
            max_noise_score = scores[i].max().item()
            
            # If too close to noise (e.g. > 0.75), discard
            if max_noise_score < 0.75:
                keep_indices.append(i)
                
        logger.info(f"Semantic Filter: {len(terms)} -> {len(keep_indices)} terms")
        return [terms[i] for i in keep_indices]

        return result


def create_deduplicator(config: DeduplicationConfig) -> Deduplicator:
    """Factory function to create deduplicator"""
    return Deduplicator(config)