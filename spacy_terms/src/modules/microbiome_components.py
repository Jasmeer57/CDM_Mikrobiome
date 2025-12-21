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
                "Proteobacteria": 0.75,
                "Verrucomicrobia": 0.85,
                "Fusobacterium nucleatum": 0.85,
                "Ruminococcus gnavus": 0.85,
                "Roseburia intestinalis": 0.90,
                "Eubacterium rectale": 0.90,
                "Prevotella copri": 0.85,
                "Helicobacter pylori": 0.80,
                "Lactobacillus rhamnosus": 0.85,
                "Bifidobacterium animalis": 0.85
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
                "indole": 0.75,
                "trimethylamine N-oxide": 0.85,
                "TMAO": 0.85,
                "lipopolysaccharide": 0.90,
                "LPS": 0.90,
                "secondary bile acids": 0.85,
                "polyphenols": 0.80,
                "vitamins": 0.75
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
                "postbiotic": 0.80,
                "fecal microbiota transplantation": 0.90,
                "FMT": 0.90,
                "colonization resistance": 0.85,
                "metabolic capacity": 0.80
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
                "antibiotic-associated diarrhea": 0.80,
                "obesity": 0.75,
                "diabetes": 0.75,
                "colorectal cancer": 0.80,
                "autism spectrum disorder": 0.70,
                "depression": 0.70
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
                "flow cytometry": 0.70,
                "shotgun sequencing": 0.85,
                "alpha diversity": 0.80,
                "beta diversity": 0.80,
                "PCoA": 0.75,
                "rarefaction": 0.75
            },
            "Bioinformatics_Tools": {
                "QIIME2": 0.90,
                "QIIME 2": 0.90,
                "DADA2": 0.90,
                "Mothur": 0.85,
                "Phyloseq": 0.85,
                "MicrobiomeAnalyst": 0.85,
                "UniFrac": 0.85,
                "SILVA": 0.80,
                "Greengenes": 0.80,
                "MetaPhlAn": 0.85,
                "HUMAnN": 0.85,
                "PICRUSt": 0.85
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
                "large intestine": 0.75,
                "epithelium": 0.75,
                "lumen": 0.70
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
        self.common_words = set() # Initialize here to avoid AttributeError

        if self.semantic_model and self.seed_terms:
            self._precompute_embeddings()
        
        # Load 20k common words filter (Moved from precompute to ensure it runs)
        try:
            from pathlib import Path
            common_words_path = Path("data/20k.txt")
            if common_words_path.exists():
                with open(common_words_path, 'r') as f:
                    self.common_words = {w.strip().lower() for w in f if len(w.strip()) > 3}
                logger.info(f"Loaded {len(self.common_words)} common words for filtering")
            else:
                 logger.warning(f"20k common words file not found at {common_words_path}")
        except Exception as e:
            logger.warning(f"Failed to load common words: {e}")

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

        # Load 20k common words filter
        self.common_words = set()
        try:
            common_words_path = Path("data/20k.txt")
            if common_words_path.exists():
                with open(common_words_path, 'r') as f:
                    self.common_words = {w.strip().lower() for w in f if len(w.strip()) > 3} # Ignore short words, handled elsewhere
                logger.info(f"Loaded {len(self.common_words)} common words for filtering")
            else:
                 logger.warning(f"20k common words file not found at {common_words_path}")
        except Exception as e:
            logger.warning(f"Failed to load common words: {e}")

    def get_relevance_score(self, term_text: str) -> float:
        """Get microbiome relevance score for a term"""
        term_lower = term_text.lower()

        # Keyword-based scoring (faster, primary method)
        keyword_score = self._keyword_score(term_lower)
        if keyword_score >= 0.8:  # High confidence keyword match
            return keyword_score
            
        # Common Word Filter (New Feature)
        # If term is in 20k common list and NOT a keyword match, kill it.
        # This keeps "novel" terms that are scientific, but removes "novel" terms that are just basic English.
        if term_lower in self.common_words:
            # We already checked keywords (which return early above), so if we are here, it's NOT a keyword.
            # So it's a common English word that is not a known microbiome/seed term.
            # Return low score to filter it out.
            return 0.0

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

        return score

    def _keyword_score(self, term_text: str) -> float:
        """Calculate keyword-based relevance score with context awareness"""
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
            r'16s', r'rrna', r'metagenom', r'metabolom',
            r'gut', r'intestin', r'colorectal', r'gastric'  # Added context terms
        ]

        # Check for microbiome context
        has_microbiome_context = False
        for pattern in microbiome_patterns:
            if re.search(pattern, term_lower):
                score = max(score, 0.8)
                has_microbiome_context = True
                break

        # Penalty for clearly non-microbiome terms
        # Removed 'cancer', 'tumor' from blanket ban.
        # Only penalize if NO microbiome context is present.
        non_microbiome_patterns = [
             r'cardiovascular', r'pulmonary',
            r'dermatology', r'ophthalmology', r'orthopedic', r'neurology',
            r'traffic', r'vehicle', r'finance', r'political' # Added obvious noise
        ]
        
        # Penalize unrelated medical fields
        for pattern in non_microbiome_patterns:
            if re.search(pattern, term_lower):
                score = score * 0.3  # Heavy penalty
                break
                
        # Context-dependent penalties (e.g. generic cancer without gut context)
        # But we want to be high-recall for novel terms, so be careful.
        # If it's just "cancer" (generic), maybe low score. 
        # But "colorectal cancer" has "colorectal" (context) -> has_microbiome_context=True -> saved.
        
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

        if re.match(r'^[0-9]+$', term):
            return False

        # Reject "word + number" patterns like "microbiome13", "protein53"
        # Exception: Short prefixes like "IL6", "CD4", "p53", "T2" are valid.
        # Rule: If term ends in a number, the alpha prefix must be <= 3 chars OR it must include a hyphen/space.
        if re.search(r'[a-zA-Z]{4,}[0-9]+$', term):
            # Check if it has a separator
            if not re.search(r'[- ]', term):
                 # "microbiome13" -> matches (len 10 > 3, no sep) -> REJECT
                 # "COVID-19" -> matches (has sep) -> KEEP
                 return False
        
        # Reject terms with underscores (variable names)
        if '_' in term:
            return False

        return True


def create_microbiome_scorer() -> MicrobiomeGoldStandardScorer:
    """Factory function to create MicrobiomeGoldStandardScorer instance"""
    return MicrobiomeGoldStandardScorer()


def create_microbiome_filter(semantic_model=None, seed_terms: List[str] = None) -> MicrobiomeSemanticFilter:
    """Factory function to create MicrobiomeSemanticFilter instance"""
    return MicrobiomeSemanticFilter(semantic_model, seed_terms)


class NoveltyDetector:
    """
    Detects novel biomedical terms using semantic distance from known concepts.
    Ported from standalone pipeline to enhance modular pipeline capabilities.
    """

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self.model = None
        self.model_name = model_name
        self.known_biomedical_terms = set()
        self._initialize()

    def _initialize(self):
        """Initialize the semantic model and known terms"""
        try:
            from sentence_transformers import SentenceTransformer
            self.model = SentenceTransformer(self.model_name)
            logger.info(f"✓ Loaded semantic model for novelty detection: {self.model_name}")
        except ImportError:
            logger.warning("sentence-transformers not available, novelty detection disabled")
            self.model = None
        except Exception as e:
            logger.warning(f"Could not load semantic model: {e}")
            self.model = None

        # Initialize with common biomedical terms (enhanced from standalone)
        self.known_biomedical_terms.update({
            # Core microbiome terms
            'gut microbiota', 'microbiome', 'microbiota', 'bacteria', 'bacteroides',
            'firmicutes', 'proteobacteria', 'actinobacteria', 'verrucomicrobia',
            'clostridia', 'bacteroidia', 'eubacterium', 'faecalibacterium',
            'roseburia', 'prevotella', 'ruminococcus', 'akkermansia', 'lactobacillus',
            'bifidobacterium', 'streptococcus', 'enterococcus', 'staphylococcus',
            'escherichia coli', 'e. coli', 'salmonella', 'campylobacter',

            # Health and disease terms
            'inflammation', 'immune', 'antibiotic', 'probiotic', 'prebiotic',
            'infection', 'disease', 'syndrome', 'disorder', 'condition',
            'crohn disease', 'ulcerative colitis', 'irritable bowel syndrome',
            'inflammatory bowel disease', 'ibd', 'ibs', 'sibo',

            # Metabolism and metabolites
            'metabolism', 'metabolic', 'fermentation', 'short-chain fatty acids',
            'butyrate', 'propionate', 'acetate', 'bile acids', 'cholesterol',
            'lipopolysaccharide', 'lps', 'cytokine', 'interleukin', 'tnf-alpha',
            'trimethylamine', 'tmao', 'indole', 'succinate', 'lactate',

            # Methods and techniques
            'diversity', 'richness', 'evenness', 'shannon', 'simpson', 'alpha',
            'beta', 'ordination', 'pcoa', 'pca', 'nmds', 'cluster', 'dendrogram',
            'phylogeny', '16s', '16s rrna', 'metagenomics', 'metabarcoding',
            'amplicon', 'shotgun', 'assembly', 'annotation', 'taxonomy',
            'classification', 'otu', 'asv', 'operational taxonomic unit',
            'amplicon sequence variant', 'pcr', 'qpcr', 'sequencing',

            # Clinical terms
            'clinical', 'patient', 'treatment', 'therapy', 'diagnosis',
            'hospital', 'medical', 'health', 'drug', 'medication',
            'resistance', 'susceptibility', 'pathogen', 'commensal', 'symbiotic'
        })

    def add_known_terms(self, terms: List[str]):
        """Add new known biomedical terms to the reference set"""
        self.known_biomedical_terms.update(term.lower().strip() for term in terms)
        logger.debug(f"Added {len(terms)} new known terms to novelty detector")

    def is_novel(self, term: str) -> tuple[bool, float]:
        """
        Check if a term is novel relative to known biomedical concepts.

        Returns:
            tuple: (is_novel, novelty_score)
                   novelty_score: 0.0 (very familiar) to 1.0 (very novel)
        """
        if not self.model:
            return False, 0.0

        term_lower = term.lower().strip()

        # If it's a known term, it's not novel
        if term_lower in self.known_biomedical_terms:
            return False, 0.0

        try:
            # Generate embedding for the term
            term_embedding = self.model.encode([term], convert_to_numpy=True)

            # Generate embeddings for known terms (sample for efficiency)
            known_terms_sample = list(self.known_biomedical_terms)[:100]  # Limit for performance
            known_embeddings = self.model.encode(known_terms_sample, convert_to_numpy=True)

            # Calculate cosine similarities
            from sklearn.metrics.pairwise import cosine_similarity
            similarities = cosine_similarity(term_embedding, known_embeddings)[0]

            # Get maximum similarity (closest known term)
            max_similarity = float(similarities.max()) if len(similarities) > 0 else 0.0

            # Calculate novelty score (inverse of similarity)
            novelty_score = 1.0 - max_similarity

            # Consider novel if similarity is below threshold (e.g., 0.5)
            is_novel = novelty_score > 0.5

            return is_novel, novelty_score

        except Exception as e:
            logger.warning(f"Error in novelty detection for '{term}': {e}")
            return False, 0.0

    def filter_novel_terms(self, terms: List[str], novelty_threshold: float = 0.5) -> List[str]:
        """
        Filter terms based on novelty threshold.

        Args:
            terms: List of terms to filter
            novelty_threshold: Minimum novelty score to keep term (0.0 to 1.0)

        Returns:
            List of novel terms above threshold
        """
        novel_terms = []
        for term in terms:
            is_novel, novelty_score = self.is_novel(term)
            if is_novel and novelty_score >= novelty_threshold:
                novel_terms.append(term)

        logger.info(f"Identified {len(novel_terms)} novel terms from {len(terms)} candidates")
        return novel_terms

    def get_novelty_stats(self, terms: List[str]) -> dict:
        """
        Get novelty statistics for a list of terms.

        Returns:
            Dictionary with novelty statistics
        """
        if not self.model:
            return {"error": "Novelty detector not initialized"}

        novelty_scores = []
        novel_count = 0
        for term in terms:
            is_novel, score = self.is_novel(term)
            novelty_scores.append(score)
            if is_novel:
                novel_count += 1

        return {
            "total_terms": len(terms),
            "novel_terms": novel_count,
            "known_terms": len(terms) - novel_count,
            "average_novelty": sum(novelty_scores) / len(novelty_scores) if novelty_scores else 0.0,
            "max_novelty": max(novelty_scores) if novelty_scores else 0.0,
            "min_novelty": min(novelty_scores) if novelty_scores else 0.0
        }


def create_contextual_cleaner() -> ContextualCleaner:
    """Factory function to create ContextualCleaner instance"""
    return ContextualCleaner()


def create_novelty_detector(model_name: str = "all-MiniLM-L6-v2") -> NoveltyDetector:
    """Factory function to create NoveltyDetector instance"""
    return NoveltyDetector(model_name)