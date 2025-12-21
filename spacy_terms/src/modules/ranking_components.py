#!/usr/bin/env python3
"""
Term ranking and semantic modeling components for advanced term scoring.

This module contains specialized components for ranking terms based on gold standard
scoring, semantic relevance, frequency, and other metrics, plus TF-IDF fallback
semantic modeling.
"""

import logging
import math
from typing import List, Dict, Any, Optional
import numpy as np

try:
    from sklearn.feature_extraction.text import TfidfVectorizer
except ImportError:
    TfidfVectorizer = None

from .microbiome_components import (
    MicrobiomeGoldStandardScorer,
    MicrobiomeSemanticFilter
)

logger = logging.getLogger(__name__)


class TfidfSemanticModel:
    """Fallback semantic model using TF-IDF."""

    def __init__(self):
        if TfidfVectorizer is None:
            logger.warning("scikit-learn not available, TF-IDF fallback disabled")
            self.vectorizer = None
        else:
            self.vectorizer = TfidfVectorizer(
                stop_words='english',
                analyzer='char_wb',
                ngram_range=(2, 4)
            )
        self.is_fitted = False

    def encode(self, sentences: List[str], convert_to_tensor: bool = False):
        """
        Encode sentences using TF-IDF.
        Note: This fits the vectorizer on the provided sentences every time if not fitted,
        which is a simplification for this fallback.
        """
        if not sentences or self.vectorizer is None:
            return np.array([])

        # For deduplication of a single batch, we fit on that batch.
        # This is sufficient for finding internal duplicates.
        try:
            embeddings = self.vectorizer.fit_transform(sentences)
            self.is_fitted = True
            return embeddings
        except ValueError:
            # Handle empty vocabulary or other issues
            return np.zeros((len(sentences), 1))


class TermRanker:
    """Ranks terms using Gold Standard, Semantic Similarity, and Frequency"""

    def __init__(self, config, semantic_model=None):
        self.config = config
        self.gold_scorer = MicrobiomeGoldStandardScorer()
        self.semantic_filter = MicrobiomeSemanticFilter(semantic_model)

    def rank_terms(self, terms: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Rank terms using comprehensive scoring algorithm"""
        logger.info(f"Ranking {len(terms)} terms using gold standard and semantic scoring")

        for term in terms:
            t_text = term['term']

            # 1. Gold Standard Score
            is_gold, category, gold_conf = self.gold_scorer.get_gold_score(t_text)
            term['is_gold_standard'] = is_gold
            term['gold_category'] = category if category else ""
            term['gold_confidence'] = gold_conf

            # 2. Semantic Score
            semantic_score = self.semantic_filter.get_relevance_score(t_text)
            term['semantic_score'] = round(semantic_score, 4)

            # --- NOVELTY DETECTION ---
            # A term is "Novel" if it is High Semantic Relevance BUT Not Gold Standard.
            # We also ensure it's not just a generic word (length check or keyword check processed earlier).
            term['is_novel'] = False
            if (not is_gold) and (semantic_score >= 0.7):
                 term['is_novel'] = True
                 term['novelty_status'] = "HighRelevance-NonGold"

            # 3. Calculate Composite Score (Logic from standalone pipeline)
            # Relevance (Base)
            relevance = 0.3  # Base relevance

            # Label-based relevance bonuses
            label = term.get('label', '').upper()
            if label in ['ORGANISM', 'TAXON']:
                relevance += 0.2
            elif label in ['CHEMICAL', 'DISEASE', 'DISORDER']:
                relevance += 0.1

            # Domain-specific bonuses
            if term.get('cdm_domain'):
                relevance += 0.15

            # Mapped Bonus
            if term.get('mappings'):
                relevance += 0.2

            # Validation Bonus
            validation = term.get('validation', {})
            if isinstance(validation, dict) and validation.get('is_valid'):
                relevance += 0.2

            # Correction Bonus
            if term.get('ai_correction'):
                relevance += 0.1

            # Definition Bonus
            if term.get('definition'):
                relevance += 0.1

            relevance = min(1.0, relevance)

            # Frequency metrics
            frequency = term.get('frequency', 1)
            file_count = len(term.get('source_files', [])) if isinstance(term.get('source_files'), list) else 1

            # Source model diversity bonus
            source_models = term.get('source_models', [])
            model_diversity = len(set(source_models)) if isinstance(source_models, list) else 1

            # Length bonus (prefer terms of reasonable length)
            term_length = len(t_text)
            length_bonus = 0.0
            if 10 <= term_length <= 30:
                length_bonus = 0.2
            elif 30 < term_length <= 50:
                length_bonus = 0.1
            elif term_length > 50:
                length_bonus = -0.1  # Penalize very long terms

            # Composite Score Formula (adapted from standalone with improvements)
            # Score = (Relevance * 0.3) + (Semantic * 0.2) + (log(Freq) * 0.2) +
            #         (log(FileCount) * 0.15) + (ModelDiversity * 0.1) + (LengthBonus * 0.05) + GoldBonus

            score = (
                relevance * 0.25 +                    # Reduced from 0.30 to balance other factors
                semantic_score * 0.20 +               # Semantic relevance
                math.log1p(frequency) * 0.20 +        # Logarithmic frequency
                math.log1p(file_count) * 0.15 +       # File distribution
                math.log1p(model_diversity) * 0.10 +   # Model diversity
                length_bonus * 0.05 +                 # Length preference
                (0.5 if is_gold else 0.0) +           # Gold standard bonus
                (0.4 if term.get('is_novel') else 0.0) # Novelty bonus (Increased)
            )

            # Apply gold confidence multiplier
            if is_gold and gold_conf > 0:
                score *= (0.8 + 0.2 * gold_conf)  # Boost score based on gold confidence

            term['relevance_score'] = round(relevance, 4)
            term['score'] = round(score, 4)
            term['ranking_factors'] = {
                'relevance': relevance,
                'semantic': semantic_score,
                'frequency': frequency,
                'file_count': file_count,
                'model_diversity': model_diversity,
                'length_bonus': length_bonus,
                'gold_bonus': 0.5 if is_gold else 0.0,
                'novelty_bonus': 0.4 if term.get('is_novel') else 0.0
            }

        # Sort by composite score
        ranked_terms = sorted(terms, key=lambda x: x['score'], reverse=True)

        logger.info(f"Top 5 ranked terms:")
        for i, term in enumerate(ranked_terms[:5]):
            logger.info(f"  {i+1}. '{term['term']}' (score: {term['score']:.4f}, "
                       f"gold: {term.get('is_gold_standard', False)}, "
                       f"semantic: {term.get('semantic_score', 0):.3f})")

        return ranked_terms


def create_term_ranker(config, semantic_model=None) -> TermRanker:
    """Factory function to create TermRanker instance"""
    return TermRanker(config, semantic_model)


def create_tfidf_semantic_model() -> Optional[TfidfSemanticModel]:
    """Factory function to create TfidfSemanticModel instance"""
    try:
        return TfidfSemanticModel()
    except Exception as e:
        logger.warning(f"Failed to create TF-IDF semantic model: {e}")
        return None


def rank_terms_with_gold_standard(
    terms: List[Dict[str, Any]],
    config,
    semantic_model=None,
    max_terms: Optional[int] = None
) -> List[Dict[str, Any]]:
    """
    Convenience function to rank terms using gold standard scoring

    Args:
        terms: List of term dictionaries
        config: Pipeline configuration
        semantic_model: Optional semantic model for scoring
        max_terms: Maximum number of terms to return

    Returns:
        Ranked list of terms
    """
    ranker = create_term_ranker(config, semantic_model)
    ranked_terms = ranker.rank_terms(terms)

    if max_terms:
        ranked_terms = ranked_terms[:max_terms]

    return ranked_terms