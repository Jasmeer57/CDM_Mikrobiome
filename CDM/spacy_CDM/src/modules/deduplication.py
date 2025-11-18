"""
Multi-layer deduplication module: Exact → Fuzzy → Semantic
"""

import logging
import json
import numpy as np
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path
from collections import defaultdict
import difflib
from sentence_transformers import SentenceTransformer
import faiss
from sklearn.metrics.pairwise import cosine_similarity

from src.config.settings import DeduplicationConfig

logger = logging.getLogger(__name__)


class ComprehensiveDeduplicator:
    """Multi-layer deduplication with configurable semantic models"""

    def __init__(self, config: DeduplicationConfig):
        self.config = config
        self.semantic_model = None
        self.index = None
        self.terms_text = []
        self._load_semantic_model()

    def _load_semantic_model(self):
        """Load the configured semantic model"""
        model_configs = {
            "mini-lm": {
                "model_name": "sentence-transformers/all-MiniLM-L12-v2",
                "dimensions": 384
            },
            "nomic": {
                "model_name": "nomic-ai/nomic-embed-text-v1",
                "dimensions": 768
            },
            "mpnet": {
                "model_name": "sentence-transformers/all-mpnet-base-v2",
                "dimensions": 768
            }
        }

        if self.config.semantic_model_choice not in model_configs:
            logger.warning(f"Unknown semantic model: {self.config.semantic_model_choice}")
            logger.warning(f"Available models: {list(model_configs.keys())}")
            logger.warning("Falling back to mini-lm")
            self.config.semantic_model_choice = "mini-lm"

        model_config = model_configs[self.config.semantic_model_choice]

        try:
            logger.info(f"Loading semantic model: {self.config.semantic_model_choice}")
            logger.info(f"   Model: {model_config['model_name']}")
            self.semantic_model = SentenceTransformer(model_config['model_name'])
            self.dimensions = model_config['dimensions']
            logger.info(f"✅ Semantic model loaded successfully")
        except Exception as e:
            logger.error(f"❌ Failed to load semantic model: {e}")
            logger.warning("Semantic deduplication will be disabled")
            self.semantic_model = None

    def exact_deduplication(self, terms: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Layer 1: Exact deduplication based on canonical form"""
        logger.info("🎯 Layer 1: Exact deduplication")

        seen_canonical = set()
        unique_terms = []

        for term in terms:
            canonical = term['canonical']

            if canonical not in seen_canonical:
                seen_canonical.add(canonical)
                unique_terms.append(term)

        logger.info(f"   Reduced from {len(terms)} to {len(unique_terms)} terms")
        return unique_terms

    def fuzzy_deduplication(self, terms: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Layer 2: Fuzzy deduplication using string similarity"""
        logger.info("🔍 Layer 2: Fuzzy deduplication")

        if not self.config.fuzzy_threshold:
            return terms

        unique_terms = []
        seen_canonical = set()

        for term in terms:
            canonical = term['canonical']
            is_duplicate = False

            for seen_term in unique_terms:
                seen_canonical_form = seen_term['canonical']
                similarity = difflib.SequenceMatcher(None, canonical, seen_canonical_form).ratio()

                if similarity >= self.config.fuzzy_threshold:
                    # Merge with existing term
                    self._merge_terms(seen_term, term, similarity)
                    is_duplicate = True
                    break

            if not is_duplicate:
                unique_terms.append(term)
                seen_canonical.add(canonical)

        logger.info(f"   Reduced from {len(terms)} to {len(unique_terms)} terms")
        return unique_terms

    def semantic_deduplication(self, terms: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Layer 3: Semantic deduplication using embeddings"""
        logger.info("🧠 Layer 3: Semantic deduplication")

        if not self.semantic_model:
            logger.warning("   ⚠️  No semantic model available, skipping semantic deduplication")
            return terms

        if len(terms) < 2:
            logger.info("   ✅ Too few terms for semantic deduplication")
            return terms

        try:
            # Generate embeddings
            logger.info(f"   Generating embeddings for {len(terms)} terms...")
            texts = [term['canonical'] for term in terms]
            embeddings = self.semantic_model.encode(
                texts,
                batch_size=32,
                show_progress_bar=True,
                convert_to_tensor=False
            )

            # Build FAISS index
            logger.info("   Building semantic index...")
            dimension = embeddings.shape[1]
            self.index = faiss.IndexFlatIP(dimension)  # Inner product = cosine similarity for normalized vectors
            self.terms_text = terms

            # Normalize embeddings for cosine similarity
            embeddings = embeddings / np.linalg.norm(embeddings, axis=1, keepdims=True)
            self.index.add(embeddings)

            # Find duplicates
            unique_indices = self._find_semantic_duplicates(embeddings, terms)

            unique_terms = [terms[i] for i in unique_indices]
            logger.info(f"   Reduced from {len(terms)} to {len(unique_terms)} terms")

            return unique_terms

        except Exception as e:
            logger.error(f"   ❌ Semantic deduplication failed: {e}")
            return terms

    def _find_semantic_duplicates(self, embeddings: np.ndarray, terms: List[Dict[str, Any]]) -> List[int]:
        """Find semantic duplicates using similarity search"""
        duplicate_threshold = self.config.semantic_threshold
        unique_indices = []
        duplicate_indices = set()

        for i, embedding in enumerate(embeddings):
            if i in duplicate_indices:
                continue

            # Search for similar embeddings
            embedding = embedding.reshape(1, -1)
            similarities, indices = self.index.search(embedding, min(10, len(terms)))

            # Find duplicates (excluding self)
            current_duplicates = []
            for j, (sim, idx) in enumerate(zip(similarities[0], indices[0])):
                if idx != i and sim >= duplicate_threshold and idx not in duplicate_indices:
                    current_duplicates.append((idx, sim))

            # Merge duplicates into the current term
            for dup_idx, sim in current_duplicates:
                self._merge_terms(terms[i], terms[dup_idx], sim)
                duplicate_indices.add(dup_idx)

            unique_indices.append(i)

        return unique_indices

    def _merge_terms(self, target: Dict[str, Any], source: Dict[str, Any], similarity: float):
        """Merge duplicate terms, preserving best information"""
        # Update confidence (weighted average)
        target_conf = target.get('confidence', 0.8)
        source_conf = source.get('confidence', 0.8)
        target['confidence'] = (target_conf + source_conf * similarity) / (1 + similarity)

        # Merge models used
        if 'models_used' not in target:
            target['models_used'] = [target.get('model', 'unknown')]
        if 'model' in source and source['model'] not in target['models_used']:
            target['models_used'].append(source['model'])

        # Update science score (keep higher)
        if source.get('science_score', 0) > target.get('science_score', 0):
            target['science_score'] = source['science_score']

        # Keep longer context if available
        if len(source.get('context', '')) > len(target.get('context', '')):
            target['context'] = source['context']

        # Add alternative forms
        if 'alternative_forms' not in target:
            target['alternative_forms'] = []
        if source['term'] != target['term'] and source['term'] not in target['alternative_forms']:
            target['alternative_forms'].append(source['term'])

        # Add similarity info
        if 'similar_terms' not in target:
            target['similar_terms'] = []
        target['similar_terms'].append({
            'term': source['term'],
            'similarity': similarity,
            'model': source.get('model', 'unknown')
        })

    def deduplicate(self, terms: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Run complete deduplication pipeline"""
        logger.info(f"🚀 Starting comprehensive deduplication on {len(terms)} terms")
        logger.info(f"   Configuration:")
        logger.info(f"   - Exact deduplication: {self.config.exact_match}")
        logger.info(f"   - Fuzzy threshold: {self.config.fuzzy_threshold}")
        logger.info(f"   - Semantic threshold: {self.config.semantic_threshold}")
        logger.info(f"   - Semantic model: {self.config.semantic_model_choice}")

        original_count = len(terms)

        # Layer 1: Exact deduplication
        if self.config.exact_match:
            terms = self.exact_deduplication(terms)
        else:
            logger.info("⏭️  Skipping exact deduplication")

        # Layer 2: Fuzzy deduplication
        if self.config.fuzzy_threshold > 0:
            terms = self.fuzzy_deduplication(terms)
        else:
            logger.info("⏭️  Skipping fuzzy deduplication")

        # Layer 3: Semantic deduplication
        if self.config.semantic_threshold > 0 and self.semantic_model:
            terms = self.semantic_deduplication(terms)
        else:
            logger.info("⏭️  Skipping semantic deduplication")

        # Post-processing: Filter by minimum length and other criteria
        final_terms = []
        for term in terms:
            if len(term['canonical']) >= self.config.min_term_length:
                if len(term['canonical']) <= self.config.max_canonical_length:
                    final_terms.append(term)

        reduction_pct = (1 - len(final_terms) / original_count) * 100 if original_count > 0 else 0
        logger.info(f"🎯 Deduplication complete!")
        logger.info(f"   Original: {original_count} terms")
        logger.info(f"   Final: {len(final_terms)} terms")
        logger.info(f"   Reduction: {reduction_pct:.1f}%")

        return final_terms

    def get_deduplication_stats(self, original_terms: List[Dict[str, Any]], deduplicated_terms: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Get deduplication statistics"""
        return {
            'original_count': len(original_terms),
            'final_count': len(deduplicated_terms),
            'reduction_count': len(original_terms) - len(deduplicated_terms),
            'reduction_percentage': (1 - len(deduplicated_terms) / len(original_terms)) * 100 if original_terms else 0,
            'semantic_model_used': self.config.semantic_model_choice,
            'fuzzy_threshold': self.config.fuzzy_threshold,
            'semantic_threshold': self.config.semantic_threshold
        }