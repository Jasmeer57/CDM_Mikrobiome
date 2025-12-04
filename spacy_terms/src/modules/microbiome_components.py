#!/usr/bin/env python3
"""
Microbiome-specific term processing components for advanced scoring and filtering.

This module contains specialized components for microbiome domain-specific processing
including gold standard scoring, semantic filtering, and contextual cleaning.
"""

import logging
import re
from typing import List, Dict, Any, Optional, Tuple, Set
from pathlib import Path
import json
from dataclasses import dataclass
from collections import Counter

logger = logging.getLogger(__name__)


class MicrobiomeGoldStandardScorer:
    """Gold standard scoring for microbiome terms (Ported from standalone pipeline)"""

    def __init__(self):
        self.gold_terms = self._load_gold_standard_terms()
        self.flat_terms = {
            term.lower(): (category, confidence)
            for category, terms in self.gold_terms.items()
            for term, confidence in terms.items()
        }
        self.gold_term_keys = list(self.flat_terms.keys())

    def _load_gold_standard_terms(self) -> Dict[str, Dict[str, float]]:
        """Load curated microbiome terms with confidence scores."""
        return {
            "Key_Organisms": {
                "Akkermansia muciniphila": 0.95,
                "Faecalibacterium prausnitzii": 0.95,
                "Bacteroides fragilis": 0.90,
                "Lactobacillus acidophilus": 0.90,
                "Bifidobacterium longum": 0.90,
                "Clostridium butyricum": 0.85,
                "Enterococcus faecium": 0.80,
                "Escherichia coli": 0.75,
                "Firmicutes": 0.85,
                "Bacteroidetes": 0.85,
                "Actinobacteria": 0.80,
                "Proteobacteria": 0.75
            },
            "Metabolites": {
                "short-chain fatty acids": 0.95,
                "SCFA": 0.95,
                "butyrate": 0.90,
                "propionate": 0.90,
                "acetate": 0.90,
                "lactate": 0.85,
                "succinate": 0.80,
                "bile acids": 0.85,
                "tryptophan": 0.80,
                "indole": 0.75
            },
            "Functional_Terms": {
                "microbiome": 0.95,
                "microbiota": 0.95,
                "gut flora": 0.90,
                "intestinal bacteria": 0.90,
                "microbial community": 0.90,
                "bacterial diversity": 0.85,
                "dysbiosis": 0.90,
                "eubiosis": 0.85,
                "probiotic": 0.90,
                "prebiotic": 0.90,
                "synbiotic": 0.85,
                "postbiotic": 0.80
            },
            "Diseases_Conditions": {
                "inflammatory bowel disease": 0.85,
                "IBD": 0.85,
                "Crohn's disease": 0.85,
                "ulcerative colitis": 0.85,
                "irritable bowel syndrome": 0.80,
                "IBS": 0.80,
                "small intestinal bacterial overgrowth": 0.80,
                "SIBO": 0.80,
                "C. difficile infection": 0.85,
                "antibiotic-associated diarrhea": 0.80
            },
            "Methods_Techniques": {
                "16S rRNA sequencing": 0.85,
                "16S rRNA": 0.85,
                "metagenomics": 0.85,
                "metagenomic sequencing": 0.85,
                "metabolomics": 0.80,
                "metatranscriptomics": 0.80,
                "qPCR": 0.75,
                "FISH": 0.70,
                "flow cytometry": 0.70
            },
            "Anatomical_Terms": {
                "gut-brain axis": 0.85,
                "intestinal permeability": 0.85,
                "leaky gut": 0.80,
                "mucus layer": 0.80,
                "intestinal barrier": 0.85,
                "cecum": 0.75,
                "colon": 0.75,
                "small intestine": 0.75,
                "large intestine": 0.75
            }
        }

    def get_gold_score(self, term: str) -> Tuple[bool, Optional[str], float]:
        """Get gold standard score for a term, with fuzzy matching fallback."""
        term_lower = term.lower().strip()

        # Exact match first
        if term_lower in self.flat_terms:
            category, base_confidence = self.flat_terms[term_lower]
            return True, category, base_confidence

        # Fuzzy matching for single word terms
        if len(term_lower.split()) == 1:
            for gold_term, (category, confidence) in self.flat_terms.items():
                gold_words = gold_term.split()
                if len(gold_words) > 1 and term_lower in gold_words:
                    # Penalize for partial match
                    return True, category, confidence * 0.7

        # Partial string matching for multi-word terms
        for gold_term, (category, confidence) in self.flat_terms.items():
            if len(gold_term.split()) > 1:
                if term_lower in gold_term or gold_term in term_lower:
                    # Penalize for partial match
                    return True, category, confidence * 0.8

        return False, None, 0.0


class MicrobiomeSemanticFilter:
    """Semantic filter with microbiome-specific seed terms and relevance scoring"""

    def __init__(self, semantic_model=None, seed_terms: List[str] = None):
        self.semantic_model = semantic_model
        self.seed_terms = seed_terms or self._get_default_seed_terms()
        self.seed_embeddings = None

        if self.semantic_model and self.seed_terms:
            self._precompute_embeddings()

    def _get_default_seed_terms(self) -> List[str]:
        """Get default microbiome seed terms for semantic filtering"""
        return [
            "microbiome", "microbiota", "gut", "intestinal", "bacterial",
            "microbial", "probiotic", "prebiotic", "dysbiosis", "antibiotic",
            "fermentation", "metabolite", "short-chain fatty acids", "SCFA",
            "butyrate", "propionate", "acetate", "bile acids", "inflammation",
            "immune", "barrier", "permeability", "commensal", "pathogen",
            "symbiosis", "metabolism", "digestion", "colon", "fecal"
        ]

    def _precompute_embeddings(self):
        """Precompute embeddings for seed terms"""
        if self.semantic_model:
            try:
                self.seed_embeddings = self.semantic_model.encode(
                    self.seed_terms,
                    convert_to_tensor=True
                )
                logger.info(f"Precomputed embeddings for {len(self.seed_terms)} seed terms")
            except Exception as e:
                logger.warning(f"Failed to precompute seed embeddings: {e}")

    def get_relevance_score(self, term_text: str) -> float:
        """Get microbiome relevance score for a term"""
        term_lower = term_text.lower()

        # Keyword-based scoring (faster, primary method)
        keyword_score = self._keyword_score(term_lower)
        if keyword_score >= 0.8:  # High confidence keyword match
            return keyword_score

        # Semantic similarity scoring (slower, secondary method)
        if self.semantic_model and self.seed_embeddings is not None:
            try:
                term_embedding = self.semantic_model.encode(
                    [term_text],
                    convert_to_tensor=True
                )

                # Calculate similarity with seed terms
                from sentence_transformers import util
                similarities = util.cos_sim(term_embedding, self.seed_embeddings)
                max_similarity = similarities.max().item()

                # Combine keyword and semantic scores
                combined_score = 0.6 * keyword_score + 0.4 * max_similarity
                return min(combined_score, 1.0)

            except Exception as e:
                logger.warning(f"Semantic scoring failed for '{term_text}': {e}")

        return keyword_score

    def _keyword_score(self, term_text: str) -> float:
        """Calculate keyword-based relevance score"""
        score = 0.0
        term_lower = term_text.lower()

        # Direct keyword matches
        for seed in self.seed_terms:
            if seed in term_lower:
                if seed == term_lower:  # Exact match
                    score = max(score, 1.0)
                elif term_lower.startswith(seed):  # Starts with keyword
                    score = max(score, 0.9)
                else:  # Contains keyword
                    score = max(score, 0.7)

        # Bonus for microbiome-specific patterns
        microbiome_patterns = [
            r'bacteroides', r'firmicutes', r'proteobacteria', r'actinobacteria',
            r'lactobacillus', r'bifidobacterium', r'clostridium', r'enterococcus',
            r'akkermania', r'faecalibacterium',
            r'scfa', r'butyrate', r'propionate', r'acetate',
            r'16s', r'rrna', r'metagenom', r'metabolom'
        ]

        for pattern in microbiome_patterns:
            if re.search(pattern, term_lower):
                score = max(score, 0.8)
                break

        # Penalty for clearly non-microbiome terms
        non_microbiome_patterns = [
            r'cancer', r'tumor', r'cardiovascular', r'renal', r'pulmonary',
            r'dermatology', r'ophthalmology', r'orthopedic', r'neurology'
        ]

        for pattern in non_microbiome_patterns:
            if re.search(pattern, term_lower):
                score = score * 0.3  # Heavy penalty
                break

        return score


class ContextualCleaner:
    """Advanced term cleaning with contextual rules"""

    @staticmethod
    def clean_terms(terms: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Apply contextual cleaning rules to extracted terms"""
        cleaned_terms = []

        for term_data in terms:
            term = term_data.get('term', '').strip()

            # Skip empty terms
            if not term:
                continue

            # Apply cleaning rules
            cleaned_term = ContextualCleaner._clean_term_text(term)

            if cleaned_term and ContextualCleaner._is_valid_term(cleaned_term):
                # Update term data with cleaned term
                cleaned_data = term_data.copy()
                cleaned_data['term'] = cleaned_term
                cleaned_data['original_term'] = term  # Keep original for reference

                cleaned_terms.append(cleaned_data)

        logger.info(f"Contextual cleaning: {len(terms)} → {len(cleaned_terms)} terms")
        return cleaned_terms

    @staticmethod
    def _clean_term_text(term: str) -> str:
        """Clean individual term text"""
        # Remove leading/trailing punctuation
        term = re.sub(r'^[^\w]+|[^\w]+$', '', term)

        # Remove excess whitespace
        term = re.sub(r'\s+', ' ', term).strip()

        # Fix common OCR/extraction errors
        term = term.replace('·', '.')
        term = term.replace('"', '')
        term = term.replace("'", "")
        term = term.replace('(', ' ').replace(')', ' ')
        term = term.replace('[', ' ').replace(']', ' ')
        term = term.replace('{', ' ').replace('}', ' ')

        # Remove extra spaces created by punctuation removal
        term = re.sub(r'\s+', ' ', term).strip()

        return term

    @staticmethod
    def _is_valid_term(term: str) -> bool:
        """Check if term is valid after cleaning"""
        # Skip very short terms
        if len(term) < 2:
            return False

        # Skip single characters (unless meaningful)
        if len(term) == 1 and term.lower() not in ['a', 'i', 'x', 'y', 'z']:
            return False

        # Skip pure numbers or single characters with numbers
        if re.match(r'^[0-9]+$', term) or re.match(r'^[a-z][0-9]+$', term):
            return False

        # Skip meaningless patterns
        meaningless_patterns = [
            r'^[.,;:!?]+$',  # Pure punctuation
            r'^[=-]+$',      # Pure symbols
            r'^\s+$',        # Pure whitespace
        ]

        for pattern in meaningless_patterns:
            if re.match(pattern, term):
                return False

        return True


def create_microbiome_scorer() -> MicrobiomeGoldStandardScorer:
    """Factory function to create MicrobiomeGoldStandardScorer instance"""
    return MicrobiomeGoldStandardScorer()


def create_microbiome_filter(semantic_model=None, seed_terms: List[str] = None) -> MicrobiomeSemanticFilter:
    """Factory function to create MicrobiomeSemanticFilter instance"""
    return MicrobiomeSemanticFilter(semantic_model, seed_terms)


def create_contextual_cleaner() -> ContextualCleaner:
    """Factory function to create ContextualCleaner instance"""
    return ContextualCleaner()