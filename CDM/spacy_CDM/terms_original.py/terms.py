#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
spaCy/Transformer Microbiome Biomedical Term Extraction Pipeline - v8.0 (Refactored)
=====================================================================================
Production-ready pipeline using specialized biomedical spaCy models and a 
SentenceTransformer model for extracting microbiome-related terms.

Features:
- Multiple sciSpaCy biomedical models
- Microbiome-focused term extraction
- Advanced fuzzy deduplication
- **NEW**: Advanced semantic filtering and deduplication with transformer models
- Top 2K term selection
- Robust error handling
- **NEW in 8.0**: Removed all "gold standard" hardcoding in favor of a unified
                 semantic relevance system driven by a comprehensive seed list.

**--- PATCH NOTES v8.0 ---**
This version represents a major refactor based on user feedback to improve semantic
accuracy and remove hardcoded logic.

- **P1/P2 (Synonymy/Normalization)**: Kept robust normalization and synonym maps.
- **P3 (Noise)**: Kept expanded noise blocklist.
- **P4/P9 (Gold Labels Removed)**: All "Gold Standard" logic, scoring, and classes 
  have been removed. All "gold" terms were moved into the `MICROBIOME_SEEDS` list.
  This creates a single, data-driven source for semantic relevance.
- **P5 (Sparsity)**: Kept the '--min_frequency' filter.
- **P6/P11 (Generic Labels)**: Kept rule-based entity label refinement.
- **P7 (Scoring Bias)**: Final scoring formula re-balanced to emphasize the new
  transformer-based semantic score and term frequency.
- **P8 (Transparency)**: Kept detailed scoring comments.
- **P10 (Examples)**: Kept full sentence context for examples.
- **P12 (Traceability)**: Kept 'source_filenames' for traceability.
- **NEW (Semantic Engine)**: Replaced spaCy vectors with a 'sentence-transformers'
  model ('all-MiniLM-L12-v2') for both semantic filtering and deduplication,
  dramatically improving semantic understanding.
"""

import os
import re
import json
import time
import logging
import argparse
import sys
import csv
import requests
from collections import defaultdict, Counter
from typing import List, Dict, Set, Optional, Tuple, Any
from pathlib import Path
from datetime import datetime
import pandas as pd
import numpy as np
from math import log1p

# Import availability checks
try:
    import spacy
    from spacy.language import Language
    SPACY_AVAILABLE = True
except ImportError:
    SPACY_AVAILABLE = False

try:
    from thefuzz import fuzz, process
    THEFUZZ_AVAILABLE = True
except ImportError:
    THEFUZZ_AVAILABLE = False

try:
    from sentence_transformers import SentenceTransformer, util
    SENTENCE_TRANSFORMERS_AVAILABLE = True
except ImportError:
    SENTENCE_TRANSFORMERS_AVAILABLE = False

# Biomedical models and configurations
SCISPACY_MODELS = [
    "en_ner_craft_md",      # Best for genes, proteins, organisms
    "en_ner_bc5cdr_md",     # Best for diseases and chemicals
    "en_core_sci_md",       # General scientific model
    "en_ner_jnlpba_md",     # Additional biomedical entities
]

# Use a specific, high-quality embedding model for all semantic tasks
# You can swap this with 'nomic-embed-text-v1' for (slower) state-of-the-art results
EMBEDDING_MODEL = 'all-MiniLM-L12-v2'


# --- FIX for P1 (Conceptual Fragmentation) ---
SYNONYM_MAP = {
    "microbiota": "microbiome",
    "gut flora": "microbiome",
    "intestinal bacteria": "microbiome",
    "microbial community": "microbiome",
    "short-chain fatty acids": "scfa",
    "inflammatory bowel disease": "ibd",
    "crohn's disease": "ibd",
    "ulcerative colitis": "ibd",
    "irritable bowel syndrome": "ibs",
    "small intestinal bacterial overgrowth": "sibo",
    "c. difficile infection": "clostridioides difficile"
}

# --- FIX for P6/P11 (Generic Entity Labels) ---
ENTITY_REFINEMENT_RULES = {
    'ORGANISM': [r'\b(bacter|coccus|sp\.|spp\.|phage|virus)\b', r'[A-Z][a-z]+ [a-z]+'],
    'DISEASE': [r'\b(disease|syndrome|infection|itis|osis)\b'],
    'CHEMICAL': [r'\b(acid|peptide|protein|enzyme|lipid|ol|ate)\b'],
}


# Entity types with microbiome-focused weights
ENTITY_WEIGHTS = {
    'ORGANISM': 0.35,
    'TAXON': 0.35,
    'GENE': 0.25,
    'GENE_OR_GENE_PRODUCT': 0.25,
    'CHEMICAL': 0.20,
    'DISEASE': 0.18,
    'SO': 0.15,
    'GO': 0.15,
    'CL': 0.15,
    'CHEBI': 0.20,
    'OTHER': 0.10
}

# --- NEW in v8.0: Unified & Expanded Microbiome Seed List ---
# This list now includes all former "gold standard" terms and drives
# the transformer-based semantic relevance filter.
MICROBIOME_SEEDS = [
    # Core Concepts
    "microbiome", "microbiota", "gut flora", "intestinal bacteria",
    "microbial community", "bacterial diversity", "dysbiosis", "eubiosis",
    "probiotic", "prebiotic", "synbiotic", "postbiotic",
    
    # Key Metabolites
    "short-chain fatty acids", "SCFA", "butyrate", "propionate", "acetate",
    "lactate", "succinate", "bile acids", "tryptophan", "indole",
    
    # Key Phyla/Organisms
    "Firmicutes", "Bacteroidetes", "Actinobacteria", "Proteobacteria",
    "Akkermansia muciniphila", "Faecalibacterium prausnitzii",
    "Bacteroides fragilis", "Lactobacillus acidophilus", "Lactobacillus",
    "Bifidobacterium longum", "Bifidobacterium", "Clostridium",
    "Clostridium butyricum", "Enterococcus faecium", "Escherichia coli",
    "Bacteroides", "Clostridioides difficile",

    # Diseases & Conditions
    "inflammatory bowel disease", "IBD", "Crohn's disease",
    "ulcerative colitis", "irritable bowel syndrome", "IBS",
    "small intestinal bacterial overgrowth", "SIBO",
    "antibiotic-associated diarrhea",

    # Methods
    "16S rRNA sequencing", "16S rRNA", "metagenomics", 
    "metagenomic sequencing", "metabolomics", "metatranscriptomics",
    "qPCR", "FISH", "flow cytometry",

    # Anatomical/Functional
    "gut-brain axis", "intestinal permeability", "leaky gut",
    "mucus layer", "intestinal barrier", "cecum", "colon",
    "small intestine", "large intestine"
]

# --- FIX for P3 (Noise) ---
NOISE_TERMS_BLOCKLIST = {
    # Latin placeholder text
    "lorem", "ipsum", "dolor", "sit", "amet", "consectetur", "adipiscing", "elit",
    "proin", "ornare", "etiam", "condimentum", "mauris", "consequat", "fermentum",
    "phasellus", "elementum", "habitant", "morbi", "tristique", "senectus",
    # Common English stopwords
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has", "he",
    "in", "is", "it", "its", "of", "on", "that", "the", "to", "was", "were", "will", "with",
    # Generic verbs and adjectives found in publications
    "see", "show", "shown", "study", "studies", "result", "results", "figure", "table",
    "introduction", "methods", "conclusion", "abstract", "background", "discussion",
    "significant", "high", "low", "increase", "decrease", "effect", "effects", "author",
    "copyright", "reserved", "rights", "publication", "published", "journal", "university",
    "et", "al", "fig", "supplementary", "data", "information", "available", "online",
    "author contributions", "funding", "acknowledgments", "competing interests"
}

class Config:
    """Configuration management for the extraction pipeline."""

    def __init__(self, args):
        self.input_dir = Path(args.input_dir)
        self.output_dir = Path(args.output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.max_docs = args.max_docs if args.max_docs > 0 else float('inf')
        self.top_k = args.top_k if args.top_k > 0 else 10000
        self.seed_terms = MICROBIOME_SEEDS
        self.similarity_threshold = getattr(args, 'similarity_threshold', 0.5)
        self.fuzzy_threshold = getattr(args, 'fuzzy_threshold', 85)
        # Semantic threshold for merging duplicates (1.0 = perfect match)
        self.semantic_dedup_threshold = getattr(args, 'semantic_dedup_threshold', 0.9)
        self.chunk_size = getattr(args, 'chunk_size', 2000)
        # --- FIX for P5 (Sparsity) ---
        self.min_frequency = getattr(args, 'min_frequency', 2)

        self._validate()

    def _validate(self):
        """Validate configuration parameters."""
        if not self.input_dir.exists():
            raise ValueError(f"Input directory does not exist: {self.input_dir}")
        if not SPACY_AVAILABLE:
            raise ImportError("spaCy is not available. Install with: pip install spacy")
        if not SENTENCE_TRANSFORMERS_AVAILABLE:
            raise ImportError("sentence-transformers is not available. Install with: pip install sentence-transformers")

def setup_logging(output_dir: Path) -> logging.Logger:
    """Initialize comprehensive logging."""
    log_file = output_dir / f"spacy_extraction_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

    logger = logging.getLogger('spacy_microbiome_extractor')
    logger.setLevel(logging.INFO)

    if logger.handlers:
        logger.handlers.clear()

    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # File handler
    fh = logging.FileHandler(log_file, mode='w', encoding='utf-8')
    fh.setFormatter(formatter)
    logger.addHandler(fh)

    # Console handler
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(formatter)
    logger.addHandler(ch)

    return logger

class StopwordManager:
    """Advanced stopword management with biomedical context."""

    def __init__(self, cache_dir: Path = Path(".cache")):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(exist_ok=True)
        self.stopwords = self._load_stopwords()

    def _load_stopwords(self) -> Set[str]:
        """Load stopwords with multiple fallback strategies."""
        cache_file = self.cache_dir / "biomedical_stopwords.txt"

        if cache_file.exists():
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    words = set(line.strip().lower() for line in f if line.strip())
                logging.info(f"Loaded {len(words)} stopwords from cache")
                return words
            except Exception as e:
                logging.warning(f"Failed to load cached stopwords: {e}")

        stopwords = self._build_stopword_list()

        try:
            with open(cache_file, 'w', encoding='utf-8') as f:
                for word in sorted(stopwords):
                    f.write(f"{word}\n")
        except Exception as e:
            logging.warning(f"Failed to cache stopwords: {e}")

        return stopwords

    def _build_stopword_list(self) -> Set[str]:
        """Build comprehensive stopword list."""
        basic_stopwords = {
            'a', 'an', 'the', 'and', 'or', 'but', 'in', 'on', 'at', 'to',
            'for', 'of', 'with', 'by', 'from', 'up', 'about', 'into',
            'through', 'during', 'before', 'after', 'above', 'below',
            'between', 'among', 'against', 'within', 'without', 'toward'
        }

        try:
            nlp = spacy.load("en_core_web_sm")
            spacy_stopwords = set(nlp.Defaults.stop_words)
            basic_stopwords.update(spacy_stopwords)
        except:
            pass

        biomedical_stopwords = {
            'abstract', 'introduction', 'background', 'methods', 'results',
            'discussion', 'conclusion', 'figure', 'table', 'author',
            'doi', 'pmid', 'copyright', 'rights', 'reserved',
            'significant', 'p-value', 'statistically', 'et', 'al'
        }

        important_biomedical_terms = {
            'cell', 'cells', 'gene', 'genes', 'protein', 'proteins',
            'bacteria', 'bacterial', 'microbe', 'microbial',
            'gut', 'intestinal', 'disease', 'treatment', 'therapy',
            'patient', 'study', 'analysis', 'group', 'effect'
        }

        final_stopwords = basic_stopwords.union(biomedical_stopwords)
        final_stopwords = final_stopwords - important_biomedical_terms

        logging.info(f"Built stopword list with {len(final_stopwords)} words")
        return final_stopwords

class MicrobiomeSemanticFilter:
    """Semantic filtering using a SentenceTransformer model."""

    def __init__(self, embedding_model, seed_terms: List[str], similarity_threshold: float = 0.5):
        if not embedding_model or not SENTENCE_TRANSFORMERS_AVAILABLE:
            logging.error("SentenceTransformer model not available. Semantic filtering will be disabled.")
            self.model = None
            self.seed_embeddings = None
            self.similarity_threshold = 0
            return

        self.model = embedding_model
        self.similarity_threshold = similarity_threshold
        
        logging.info("Encoding semantic seed terms...")
        # Pre-compute seed embeddings
        try:
            # Using convert_to_tensor=True for faster cosine similarity calculations
            self.seed_embeddings = self.model.encode(
                seed_terms, 
                convert_to_tensor=True,
                show_progress_bar=True
            )
            logging.info(f"Semantic filter: {len(self.seed_embeddings)} seed embeddings loaded")
        except Exception as e:
            logging.error(f"Failed to encode seed terms: {e}")
            self.seed_embeddings = None

        # Microbiome-specific keywords for fallback
        self.microbiome_keywords = {
            'microb', 'bacteri', 'gut', 'intestin', 'flora', 'probiotic',
            'prebiotic', 'dysbiosis', 'metabolit', 'scfa', 'butyrate',
            'lactobacillus', 'bifidobacterium', 'clostridium', 'bacteroides',
            'firmicutes', 'bacteroidetes', 'actinobacteria'
        }

    def is_microbiome_relevant(self, term_text: str) -> Tuple[bool, float]:
        """Check if term is microbiome-relevant using transformer embeddings."""
        if not self.model or self.seed_embeddings is None:
            return self._keyword_relevance(term_text)

        try:
            # Encode the new term
            term_embedding = self.model.encode(term_text, convert_to_tensor=True)

            # Calculate cosine similarities
            # This computes similarity between the term_embedding and all seed_embeddings
            similarities = util.cos_sim(term_embedding, self.seed_embeddings)
            
            # Get the highest similarity score
            max_similarity = similarities[0].max().item()

            # Combine with keyword matching for better coverage
            is_keyword_relevant, keyword_score = self._keyword_relevance(term_text)

            final_score = max(max_similarity, keyword_score * 0.7)  # Weighted combination
            is_relevant = final_score >= self.similarity_threshold

            return is_relevant, final_score

        except Exception as e:
            logging.debug(f"Semantic check failed for '{term_text}': {e}")
            return self._keyword_relevance(term_text)

    def _keyword_relevance(self, term_text: str) -> Tuple[bool, float]:
        """Fallback keyword-based relevance check."""
        term_lower = term_text.lower()

        for keyword in self.microbiome_keywords:
            if keyword in term_lower:
                return True, 0.8

        if re.match(r'^[A-Z][a-z]+ [a-z]+$', term_text):  # Genus species
            return True, 0.7

        biomedical_suffixes = ['osis', 'itis', 'ase', 'ine', 'ate', 'ide']
        if any(term_lower.endswith(suffix) for suffix in biomedical_suffixes):
            return True, 0.6

        return False, 0.0

class AdvancedTermFilter:
    """Advanced term filtering for microbiome context."""

    def __init__(self, stopword_manager: StopwordManager, noise_terms: Set[str]):
        self.stopwords = stopword_manager.stopwords
        self.noise_terms = noise_terms

        self.invalid_patterns = [
            re.compile(r'^\W*\d+\.\d+\W*$'),
            re.compile(r'^\W*\d+\W*$'),
            re.compile(r'^[A-Z]\W*$'),
            re.compile(r'.*\.(png|jpg|pdf|html)$', re.I),
            re.compile(r'^\W*(fig|table)\W*\d*\W*$', re.I),
            re.compile(r'^\W*p\s*[<>=]\s*0\.\d+\W*$', re.I),
            re.compile(r'^\W*doi:.*$', re.I),
        ]

        self.biomedical_artifacts = {
            'western blot', 'pcr', 'qpcr', 'elisa', 'anova', 't-test',
            'chi-square', 'confidence interval', 'standard deviation',
            'p-value', 'statistical significance', 'correlation coefficient'
        }

    def is_valid_term(self, term_text: str, entity_label: str = "") -> bool:
        """Comprehensive term validation including a noise blocklist."""
        term_text = term_text.strip()
        term_lower = term_text.lower()

        if len(term_text) < 2 or len(term_text) > 100:
            return False

        for pattern in self.invalid_patterns:
            if pattern.match(term_text):
                return False

        if not any(c.isalpha() for c in term_text):
            return False
        
        if term_lower in self.noise_terms:
            return False

        tokens = [token.lower() for token in term_text.split() if token.isalpha()]
        if not tokens:
            return False
        
        if any(token in self.noise_terms for token in tokens):
            return False

        non_stopword_count = sum(1 for token in tokens if token not in self.stopwords)
        if non_stopword_count == 0 and len(tokens) > 1:
            return False

        if term_lower in self.biomedical_artifacts:
            return False

        alpha_count = sum(1 for c in term_text if c.isalpha())
        if alpha_count / len(term_text) < 0.5:
            return False

        return True

class ModelManager:
    """Efficient management of multiple spaCy and transformer models."""

    def __init__(self):
        self.models = {}
        self.semantic_model = None # spaCy model with vectors
        self.embedding_model = None # SentenceTransformer model
        self._load_models()

    def _load_models(self):
        """Load biomedical spaCy and transformer models."""
        if not SPACY_AVAILABLE:
            raise ImportError("spaCy not available")

        # Load spaCy semantic model first (for fallback/other tasks)
        semantic_loaded = False
        for model_name in ["en_core_sci_md", "en_core_web_lg", "en_core_web_md"]:
            try:
                self.semantic_model = spacy.load(model_name)
                logging.info(f"✅ Loaded spaCy semantic model: {model_name}")
                semantic_loaded = True
                break
            except OSError:
                logging.warning(f"⚠️ spaCy model {model_name} not available")
                continue

        if not semantic_loaded:
            raise RuntimeError("No suitable spaCy model available")

        # Load NER models
        successful_models = 0
        for model_name in SCISPACY_MODELS:
            try:
                model = spacy.load(model_name)
                self.models[model_name] = model
                successful_models += 1
                logging.info(f"✅ Loaded NER model: {model_name}")
            except OSError:
                logging.warning(f"⚠️ NER model {model_name} not available")
            except Exception as e:
                logging.error(f"❌ Error loading {model_name}: {e}")

        if successful_models == 0:
            raise RuntimeError("No NER models could be loaded")

        logging.info(f"Successfully loaded {successful_models} NER models")
        
        # Load SentenceTransformer model
        if SENTENCE_TRANSFORMERS_AVAILABLE:
            try:
                logging.info(f"🤖 Loading SentenceTransformer model: {EMBEDDING_MODEL}...")
                self.embedding_model = SentenceTransformer(EMBEDDING_MODEL)
                logging.info(f"✅ Loaded SentenceTransformer model: {EMBEDDING_MODEL}")
            except Exception as e:
                logging.error(f"❌ Failed to load SentenceTransformer model {EMBEDDING_MODEL}: {e}")
                raise
        else:
            raise ImportError("SentenceTransformers not installed, cannot proceed with v8.0 logic.")

class TextChunker:
    """Efficient text chunking for large documents."""

    def __init__(self, chunk_size: int = 2000):
        self.chunk_size = chunk_size

    def chunk_text(self, text: str) -> List[str]:
        """Split text into overlapping chunks."""
        if len(text) <= self.chunk_size:
            return [text]

        chunks = []
        sentences = re.split(r'[.!?]+', text)
        current_chunk = ""

        for sentence in sentences:
            if len(current_chunk) + len(sentence) <= self.chunk_size:
                current_chunk += sentence + ". "
            else:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                current_chunk = sentence + ". "

        if current_chunk:
            chunks.append(current_chunk.strip())

        return chunks

class MicrobiomeExtractor:
    """Main extraction engine optimized for microbiome terms."""

    def __init__(self, model_manager: ModelManager, semantic_filter: MicrobiomeSemanticFilter,
                 term_filter: AdvancedTermFilter):
        self.model_manager = model_manager
        self.semantic_filter = semantic_filter
        self.term_filter = term_filter
        self.chunker = TextChunker()

        self.stats = {
            'chunks_processed': 0,
            'entities_found': 0,
            'terms_validated': 0,
            'labels_refined': 0
        }

    def extract_from_text(self, text: str, file_id: str) -> List[Dict]:
        """Extract microbiome terms from text."""
        chunks = self.chunker.chunk_text(text)
        all_terms = []

        for chunk_idx, chunk in enumerate(chunks):
            chunk_terms = self._process_chunk(chunk, file_id, chunk_idx)
            all_terms.extend(chunk_terms)
            self.stats['chunks_processed'] += 1

        return all_terms

    def _process_chunk(self, chunk: str, file_id: str, chunk_idx: int) -> List[Dict]:
        """Process a single text chunk with all models."""
        unique_terms = {}

        for model_name, nlp in self.model_manager.models.items():
            try:
                doc = nlp(chunk)

                for ent in doc.ents:
                    self.stats['entities_found'] += 1

                    if not self.term_filter.is_valid_term(ent.text, ent.label_):
                        continue

                    # Semantic relevance check
                    is_relevant, relevance_score = self.semantic_filter.is_microbiome_relevant(ent.text)
                    if not is_relevant:
                        continue
                    
                    # --- FIX for P1 & P2 (Synonymy & Normalization) ---
                    canonical_form = self._normalize_term(ent, use_synonym_map=True)
                    if not canonical_form:
                        continue

                    # --- FIX for P6/P11 (Generic Labels) ---
                    original_label = ent.label_
                    refined_label = self._refine_entity_label(canonical_form, original_label)
                    if refined_label != original_label:
                        self.stats['labels_refined'] += 1

                    self.stats['terms_validated'] += 1

                    # --- FIX for P8 (Scoring Transparency) ---
                    base_score = self._calculate_base_score(ent, relevance_score)

                    term_key = f"{canonical_form}||{refined_label}"

                    if term_key not in unique_terms:
                        unique_terms[term_key] = {
                            'canonical_term': canonical_form,
                            'primary_form': ent.text,
                            'entity_label': refined_label,
                            'frequency': 1,
                            'relevance_score': base_score,
                            'semantic_score': relevance_score,
                            'model_sources': {model_name},
                            'file_ids': {file_id},
                            'chunk_id': chunk_idx,
                            # --- FIX for P10 (Examples) ---
                            'examples': [self._capture_example_context(ent)],
                        }
                    else:
                        # Update existing term
                        existing = unique_terms[term_key]
                        existing['frequency'] += 1
                        existing['model_sources'].add(model_name)
                        existing['file_ids'].add(file_id)

                        # Update score based on frequency
                        frequency_bonus = min(0.2, log1p(existing['frequency']) / 10.0)
                        existing['relevance_score'] = min(1.0, existing['relevance_score'] + frequency_bonus)

                        # --- FIX for P10 (Examples) ---
                        new_example = self._capture_example_context(ent)
                        if (len(existing['examples']) < 3 and
                            new_example.lower() not in (ex.lower() for ex in existing['examples'])):
                            existing['examples'].append(new_example)

            except Exception as e:
                logging.error(f"Error processing chunk with {model_name}: {e}")
                continue

        return list(unique_terms.values())

    # --- FIX for P2 (Normalization Inconsistency) ---
    def _normalize_term(self, entity, use_synonym_map: bool = False) -> str:
        """Robustly normalize entity to a deterministic canonical form."""
        try:
            tokens = []
            for token in entity:
                if not token.is_punct and not token.is_space:
                    lemma = token.lemma_.lower().strip()
                    if lemma and len(lemma) > 1:
                        tokens.append(lemma)
            
            sorted_tokens = sorted(tokens)
            normalized_form = " ".join(sorted_tokens) if sorted_tokens else ""

            if use_synonym_map:
                original_lemmatized = " ".join(tokens)
                if original_lemmatized in SYNONYM_MAP:
                    return SYNONYM_MAP[original_lemmatized]
                if normalized_form in SYNONYM_MAP:
                    return SYNONYM_MAP[normalized_form]

            return normalized_form

        except Exception:
            return " ".join(sorted(re.sub(r'[^\w\s-]', '', entity.text.lower()).split()))

    # --- FIX for P8 (Scoring Transparency) ---
    def _calculate_base_score(self, entity, semantic_score: float) -> float:
        """
        Calculate the base relevance score for a term before frequency adjustments.
        The score is a weighted sum of several factors:
        - Base Score (0.3): A starting value for any valid term.
        - Entity Weight: A bonus based on the entity type's relevance.
        - Semantic Score (x0.3): The transformer-based similarity to seed terms.
        - Term Complexity: A small bonus for multi-word terms.
        """
        score = 0.3
        entity_weight = ENTITY_WEIGHTS.get(entity.label_, 0.1)
        score += entity_weight
        score += semantic_score * 0.3
        word_count = len(entity.text.split())
        if 2 <= word_count <= 4:
            score += 0.1
        elif word_count == 1:
            score -= 0.05
        return min(1.0, score)
    
    # --- FIX for P10 (Unhelpful Examples) ---
    def _capture_example_context(self, entity) -> str:
        """Capture the full sentence containing the entity as an example."""
        try:
            sentence = entity.sent.text.strip().replace("\n", " ")
            if len(sentence) > 250:
                start = max(0, entity.start_char - entity.sent.start_char - 75)
                end = min(len(sentence), entity.end_char - entity.sent.start_char + 75)
                return f"...{sentence[start:end]}..."
            return sentence
        except Exception:
            return entity.text

    # --- FIX for P6/P11 (Generic Labels) ---
    def _refine_entity_label(self, term_text: str, original_label: str) -> str:
        """Refine a generic entity label using rule-based patterns."""
        if original_label not in ['ENTITY', 'OTHER']:
            return original_label

        term_lower = term_text.lower()
        for specific_label, patterns in ENTITY_REFINEMENT_RULES.items():
            for pattern in patterns:
                if re.search(pattern, term_lower):
                    return specific_label
        
        return original_label

class IterativeDeduplicator:
    """Advanced iterative deduplication pipeline with semantic clustering."""

    def __init__(self, embedding_model, fuzzy_threshold: int = 85, semantic_threshold: float = 0.9):
        self.fuzzy_threshold = fuzzy_threshold
        self.semantic_threshold = semantic_threshold
        self.model = embedding_model # SentenceTransformer model

    def deduplicate(self, terms: List[Dict]) -> List[Dict]:
        """Perform multi-stage iterative deduplication."""
        if not terms:
            return []

        logging.info(f"🔄 Starting deduplication pipeline with {len(terms)} terms")

        # Stage 1: Exact deduplication
        stage1 = self._exact_deduplication(terms)
        logging.info(f"📊 Stage 1 (exact): {len(stage1)} terms remaining")

        # Stage 2: Case-normalized deduplication
        stage2 = self._case_normalized_deduplication(stage1)
        logging.info(f"📊 Stage 2 (case-normalized): {len(stage2)} terms remaining")

        # Stage 3: Fuzzy deduplication (if available)
        if THEFUZZ_AVAILABLE:
            stage3 = self._iterative_fuzzy_deduplication(stage2)
            logging.info(f"📊 Stage 3 (fuzzy): {len(stage3)} terms remaining")
        else:
            stage3 = stage2
            logging.info("📊 Stage 3 (fuzzy): Skipped - thefuzz not available")

        # Stage 4: Semantic clustering (if available)
        if self.model and SENTENCE_TRANSFORMERS_AVAILABLE:
            stage4 = self._semantic_deduplication(stage3)
            logging.info(f"📊 Stage 4 (semantic): {len(stage4)} terms remaining")
        else:
            stage4 = stage3
            logging.info("📊 Stage 4 (semantic): Skipped - model not available")

        return stage4

    def _exact_deduplication(self, terms: List[Dict]) -> List[Dict]:
        """Exact string matching deduplication."""
        groups = defaultdict(list)
        for term in terms:
            key = (term['canonical_term'], term['entity_label'])
            groups[key].append(term)
        
        deduplicated = [self._merge_term_group(group) for group in groups.values()]
        return sorted(deduplicated, key=lambda x: x['relevance_score'], reverse=True)

    def _case_normalized_deduplication(self, terms: List[Dict]) -> List[Dict]:
        """Case-insensitive with punctuation normalization."""
        groups = defaultdict(list)
        for term in terms:
            normalized_key = self._normalize_for_comparison(term['canonical_term'])
            groups[normalized_key].append(term)
        
        deduplicated = [self._merge_term_group(group) for group in groups.values()]
        return deduplicated

    def _iterative_fuzzy_deduplication(self, terms: List[Dict]) -> List[Dict]:
        """Iterative fuzzy matching in batches."""
        batch_size = 1000
        all_deduplicated = []

        for i in range(0, len(terms), batch_size):
            batch = terms[i:i + batch_size]
            deduplicated_batch = self._fuzzy_deduplicate_batch(batch)
            all_deduplicated.extend(deduplicated_batch)

        if len(all_deduplicated) > batch_size:
            final_dedup = self._fuzzy_deduplicate_batch(all_deduplicated)
            return final_dedup
        return all_deduplicated

    def _fuzzy_deduplicate_batch(self, terms: List[Dict]) -> List[Dict]:
        """Fuzzy deduplication within a batch."""
        processed_indices = set()
        final_terms = []

        for i, term in enumerate(terms):
            if i in processed_indices:
                continue

            cluster = [term]
            term_text = term['canonical_term']
            search_end = min(len(terms), i + 200)

            for j in range(i + 1, search_end):
                if j in processed_indices:
                    continue
                candidate_text = terms[j]['canonical_term']
                if abs(len(term_text) - len(candidate_text)) > max(len(term_text), len(candidate_text)) * 0.5:
                    continue

                similarity = fuzz.token_set_ratio(term_text, candidate_text)
                if similarity >= self.fuzzy_threshold:
                    cluster.append(terms[j])
                    processed_indices.add(j)

            merged = self._merge_term_group(cluster)
            final_terms.append(merged)
            processed_indices.add(i)

        return final_terms

    def _semantic_deduplication(self, terms: List[Dict]) -> List[Dict]:
        """
        Deduplicate based on semantic similarity using hierarchical clustering.
        This uses `util.community_detection` which is fast and effective.
        """
        if not terms:
            return []
        
        logging.info("🤖 Starting semantic deduplication...")
        try:
            term_texts = [term['canonical_term'] for term in terms]
            
            logging.info(f"Embedding {len(term_texts)} terms for semantic clustering...")
            embeddings = self.model.encode(
                term_texts, 
                batch_size=32, 
                show_progress_bar=True
            )

            logging.info("Clustering terms...")
            # Perform hierarchical clustering
            clusters = util.community_detection(
                embeddings, 
                min_community_size=2, 
                threshold=self.semantic_threshold
            )

            final_terms = []
            processed_indices = set()

            # Merge terms within each cluster
            for cluster in clusters:
                cluster_terms = [terms[i] for i in cluster]
                merged = self._merge_term_group(cluster_terms)
                final_terms.append(merged)
                processed_indices.update(cluster)

            # Add back all terms that were not part of any cluster
            for i in range(len(terms)):
                if i not in processed_indices:
                    final_terms.append(terms[i])

            logging.info(f"Semantic deduplication complete. {len(clusters)} clusters merged.")
            return final_terms

        except Exception as e:
            logging.warning(f"Semantic deduplication failed: {e}. Returning fuzzy-deduped list.")
            return terms

    def _normalize_for_comparison(self, term: str) -> str:
        """Normalize term for comparison."""
        normalized = re.sub(r'[^\w\s-]', '', term.lower())
        normalized = re.sub(r'\s+', ' ', normalized)
        return normalized.strip()

    def _merge_term_group(self, group: List[Dict]) -> Dict:
        """Merge a group of similar terms."""
        if len(group) == 1:
            return group[0]

        # Select best representative based on score, frequency
        best_term = max(group, key=lambda x: (
            x.get('relevance_score', 0),
            x.get('frequency', 1)
        ))

        total_frequency = sum(term.get('frequency', 1) for term in group)
        all_file_ids = set()
        all_sources = set()
        all_examples = []

        for term in group:
            all_sources.update(term.get('model_sources', set()))
            all_examples.extend(term.get('examples', []))
            all_file_ids.update(term.get('file_ids', set()))

        weighted_score = sum(
            term.get('relevance_score', 0) * term.get('frequency', 1)
            for term in group
        ) / total_frequency

        merged = best_term.copy()
        merged.update({
            'frequency': total_frequency,
            'file_count': len(all_file_ids),
            'model_sources': all_sources,
            'relevance_score': weighted_score,
            'examples': list(dict.fromkeys(all_examples))[:5],
            'merged_from_count': len(group),
            'file_ids': all_file_ids
        })

        return merged

class JSONSerializableSetEncoder(json.JSONEncoder):
    """A custom JSON encoder that converts sets to lists."""
    def default(self, obj):
        if isinstance(obj, set):
            return list(obj)
        return json.JSONEncoder.default(self, obj)

class ResultExporter:
    """Export results with comprehensive formatting."""

    def __init__(self, output_dir: Path, file_map: Dict[str, str]):
        self.output_dir = output_dir
        self.file_id_to_name_map = file_map


    def export_results(self, terms: List[Dict], metadata: Dict):
        """Export in multiple formats."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._export_json(terms, metadata, timestamp)
        self._export_csv(terms, timestamp)
        self._export_summary(terms, metadata, timestamp)

    def _export_json(self, terms: List[Dict], metadata: Dict, timestamp: str):
        """Export comprehensive JSON."""
        output_data = {'extraction_metadata': metadata, 'terms': terms}
        json_path = self.output_dir / f"spacy_extracted_terms_{timestamp}.json"
        try:
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(output_data, f, indent=2, ensure_ascii=False, cls=JSONSerializableSetEncoder)
            logging.info(f"✅ JSON exported: {json_path}")
        except Exception as e:
            logging.error(f"❌ JSON export failed: {e}")

    def _export_csv(self, terms: List[Dict], timestamp: str):
        """Export CSV with proper formatting."""
        csv_path = self.output_dir / f"spacy_extracted_terms_{timestamp}.csv"
        if not terms:
            return

        try:
            csv_data = []
            for term in terms:
                source_filenames = sorted([self.file_id_to_name_map.get(fid, 'unknown_file') for fid in term.get('file_ids', [])])
                row = {
                    'canonical_term': self._clean_text(term.get('canonical_term', '')),
                    'primary_form': self._clean_text(term.get('primary_form', '')),
                    'entity_label': term.get('entity_label', ''),
                    'frequency': term.get('frequency', 1),
                    'file_count': term.get('file_count', 1),
                    'relevance_score': round(term.get('relevance_score', 0), 4),
                    'semantic_score': round(term.get('semantic_score', 0), 4),
                    'model_sources': ';'.join(sorted(list(term.get('model_sources', [])))),
                    'examples': ' | '.join(self._clean_text(ex) for ex in term.get('examples', [])[:3]),
                    'source_filenames': ';'.join(source_filenames)
                }
                csv_data.append(row)

            df = pd.DataFrame(csv_data)
            df.to_csv(csv_path, index=False, encoding='utf-8', escapechar='\\')
            logging.info(f"✅ CSV exported: {csv_path}")
        except Exception as e:
            logging.error(f"❌ CSV export failed: {e}")

    def _export_summary(self, terms: List[Dict], metadata: Dict, timestamp: str):
        """Export detailed summary statistics."""
        summary_path = self.output_dir / f"spacy_extraction_summary_{timestamp}.json"
        try:
            relevance_scores = [term.get('relevance_score', 0) for term in terms]
            semantic_scores = [term.get('semantic_score', 0) for term in terms]
            entity_labels = [term.get('entity_label', 'UNKNOWN') for term in terms]

            summary = {
                'extraction_summary': {
                    'total_terms': len(terms),
                    'average_relevance_score': np.mean(relevance_scores) if relevance_scores else 0,
                    'average_semantic_score': np.mean(semantic_scores) if semantic_scores else 0,
                    'score_distribution': {
                        'high_relevance (>0.7)': sum(1 for s in relevance_scores if s > 0.7),
                        'medium_relevance (0.4-0.7)': sum(1 for s in relevance_scores if 0.4 <= s <= 0.7),
                        'low_relevance (<0.4)': sum(1 for s in relevance_scores if s < 0.4)
                    },
                    'entity_label_distribution': dict(Counter(entity_labels)),
                },
                'metadata': metadata,
                'export_info': {
                    'timestamp': datetime.now().isoformat(),
                    'pipeline_version': 'spacy_v8.0_refactored'
                }
            }
            with open(summary_path, 'w', encoding='utf-8') as f:
                json.dump(summary, f, indent=2, ensure_ascii=False, cls=JSONSerializableSetEncoder)
            logging.info(f"✅ Summary exported: {summary_path}")
        except Exception as e:
            logging.error(f"❌ Summary export failed: {e}")

    def _clean_text(self, text: str) -> str:
        """Clean text for export."""
        if not text: return ""
        text = str(text).replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')
        text = re.sub(r'\s+', ' ', text)
        return text.strip()

class SpaCyMicrobiomePipeline:
    """Main pipeline orchestrator for spaCy-based extraction."""

    def __init__(self, config: Config):
        self.config = config
        self.logger = setup_logging(config.output_dir)
        self.file_id_to_name_map = {}

        self.logger.info("🔬 Initializing spaCy Microbiome Pipeline v8.0...")

        self.stopword_manager = StopwordManager()
        
        # ModelManager now loads both spaCy and Transformer models
        self.model_manager = ModelManager()

        self.semantic_filter = MicrobiomeSemanticFilter(
            self.model_manager.embedding_model, # Use the transformer model
            config.seed_terms,
            config.similarity_threshold
        )

        self.term_filter = AdvancedTermFilter(self.stopword_manager, NOISE_TERMS_BLOCKLIST)

        self.extractor = MicrobiomeExtractor(
            self.model_manager,
            self.semantic_filter,
            self.term_filter
            # No more gold_scorer
        )

        self.deduplicator = IterativeDeduplicator(
            self.model_manager.embedding_model, # Pass model to deduplicator
            config.fuzzy_threshold,
            config.semantic_dedup_threshold
        )
        
        self.exporter = ResultExporter(config.output_dir, self.file_id_to_name_map)
        self.logger.info("✅ Pipeline initialization completed")

    def run(self):
        """Execute the complete pipeline."""
        start_time = time.time()
        self.logger.info("🚀 Starting spaCy Microbiome Extraction Pipeline v8.0 (Refactored)")

        try:
            documents = self._load_documents()
            if not documents: return

            self.logger.info("🔬 Extracting microbiome terms...")
            all_terms = self._extract_terms(documents)
            if not all_terms:
                self.logger.error("❌ No terms extracted")
                return

            self.logger.info("🔄 Performing iterative deduplication (Fuzzy + Semantic)...")
            deduplicated_terms = self.deduplicator.deduplicate(all_terms)
            
            # --- FIX for P5 (Sparsity) ---
            pre_filter_count = len(deduplicated_terms)
            frequency_filtered_terms = [
                term for term in deduplicated_terms if term.get('frequency', 1) >= self.config.min_frequency
            ]
            self.logger.info(f"🗑️  Filtered out {pre_filter_count - len(frequency_filtered_terms)} terms with frequency < {self.config.min_frequency}")

            final_terms = self._select_top_terms(frequency_filtered_terms)

            metadata = self._generate_metadata(len(documents), len(all_terms), len(final_terms))
            self.exporter.export_results(final_terms, metadata)

            self._log_completion(start_time, len(documents), len(all_terms), len(final_terms))

        except Exception as e:
            self.logger.error(f"❌ Pipeline failed: {e}", exc_info=True)
            raise

    def _load_documents(self) -> List[Dict]:
        """Load text documents."""
        txt_files = list(self.config.input_dir.glob("*.txt"))
        if not txt_files:
            self.logger.error(f"No .txt files found in {self.config.input_dir}")
            return []

        documents = []
        for file_path in txt_files:
            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read().strip()
                if content and len(content) > 50:
                    file_id = file_path.stem
                    documents.append({'id': file_id, 'filename': file_path.name, 'content': content})
                    self.file_id_to_name_map[file_id] = file_path.name
            except Exception as e:
                self.logger.warning(f"Failed to read {file_path}: {e}")

        if len(documents) > self.config.max_docs:
            documents = documents[:int(self.config.max_docs)]

        self.logger.info(f"📚 Loaded {len(documents)} documents")
        return documents

    def _extract_terms(self, documents: List[Dict]) -> List[Dict]:
        """Extract terms from all documents."""
        all_terms = []
        for i, doc in enumerate(documents, 1):
            self.logger.info(f"Processing document {i}/{len(documents)}: {doc['filename']}")
            try:
                doc_terms = self.extractor.extract_from_text(doc['content'], doc['id'])
                all_terms.extend(doc_terms)
                if i % 20 == 0:
                    self.logger.info(f"Progress: {len(all_terms)} terms extracted so far")
            except Exception as e:
                self.logger.error(f"Failed to process {doc['filename']}: {e}")
                continue
        self.logger.info(f"📊 Extracted {len(all_terms)} raw terms")
        return all_terms

    def _select_top_terms(self, terms: List[Dict]) -> List[Dict]:
        """Select top K terms based on comprehensive scoring."""
        if len(terms) <= self.config.top_k:
            return terms

        # --- FIX for P7 (Scoring Bias) & P8 (Transparency) ---
        # --- NEW v8.0: Re-balanced composite score ---
        def composite_score(term):
            """
            This function calculates the final ranking score for a term.
            It is a weighted sum designed to balance several indicators of importance:
            - Relevance Score (x0.25): The base score (entity type, complexity).
            - Semantic Score (x0.35): **[WEIGHT INCREASED]** The transformer-based 
                                     similarity to our comprehensive seed list.
            - Log of Frequency (x0.25): The term's overall frequency.
            - Log of File Count (x0.15): The number of unique documents (breadth).
            - (Gold Standard Bonus Removed)
            """
            relevance = term.get('relevance_score', 0)
            frequency = term.get('frequency', 1)
            file_count = term.get('file_count', 1)
            semantic = term.get('semantic_score', 0)

            score = (
                relevance * 0.25 +
                semantic * 0.35 +
                log1p(frequency) * 0.25 +
                log1p(file_count) * 0.15
            )
            return score

        sorted_terms = sorted(terms, key=composite_score, reverse=True)
        selected = sorted_terms[:self.config.top_k]

        self.logger.info(f"📈 Selected top {len(selected)} terms from {len(terms)} candidates")
        return selected

    def _generate_metadata(self, num_docs: int, num_raw: int, num_final: int) -> Dict:
        """Generate comprehensive metadata."""
        return {
            'pipeline_info': {
                'version': 'spacy_v8.0_refactored',
                'type': 'microbiome_spacy_transformer_extraction',
                'timestamp': datetime.now().isoformat()
            },
            'processing_statistics': {
                'documents_processed': num_docs,
                'chunks_processed': self.extractor.stats['chunks_processed'],
                'entities_found': self.extractor.stats['entities_found'],
                'labels_refined': self.extractor.stats['labels_refined'],
                'terms_validated': self.extractor.stats['terms_validated'],
                'raw_terms_extracted': num_raw,
                'final_terms_selected': num_final
            },
            'configuration': {
                'max_documents': self.config.max_docs,
                'top_k_terms': self.config.top_k,
                'min_frequency': self.config.min_frequency,
                'similarity_threshold': self.config.similarity_threshold,
                'fuzzy_threshold': self.config.fuzzy_threshold,
                'semantic_dedup_threshold': self.config.semantic_dedup_threshold,
                'chunk_size': self.config.chunk_size
            },
            'models_used': {
                'embedding_model': EMBEDDING_MODEL,
                'ner_models': list(self.model_manager.models.keys()),
                'deduplication_methods': ['exact', 'fuzzy', 'semantic']
            }
        }

    def _log_completion(self, start_time: float, num_docs: int, num_raw: int, num_final: int):
        """Log detailed completion statistics."""
        duration = time.time() - start_time
        self.logger.info("=" * 60)
        self.logger.info("🎉 SPACY MICROBIOME EXTRACTION COMPLETED")
        self.logger.info("=" * 60)
        self.logger.info(f"⏱️  Total runtime: {duration:.2f} seconds")
        self.logger.info(f"📚 Documents processed: {num_docs}")
        self.logger.info(f"🧩 Text chunks processed: {self.extractor.stats['chunks_processed']}")
        self.logger.info(f"🔍 Raw entities found: {self.extractor.stats['entities_found']}")
        self.logger.info(f"🏷️  Generic labels refined: {self.extractor.stats['labels_refined']}")
        self.logger.info(f"✅ Terms validated: {self.extractor.stats['terms_validated']}")
        self.logger.info(f"📊 Raw terms extracted: {num_raw}")
        self.logger.info(f"✨ Final terms selected: {num_final}")
        if num_raw > 0:
            retention_rate = (num_final / num_raw) * 100
            self.logger.info(f"📈 Quality retention rate: {retention_rate:.1f}%")
        self.logger.info("=" * 60)

def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="spaCy/Transformer Microbiome Term Extraction v8.0 (Refactored)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )

    parser.add_argument("--input_dir", type=str, required=True,
                        help="Input directory containing .txt files")
    parser.add_argument("--output_dir", type=str, default="./spacy_microbiome_output_v8",
                        help="Output directory for results")
    parser.add_argument("--max_docs", type=int, default=350,
                        help="Maximum documents to process (-1 for all)")
    parser.add_argument("--top_k", type=int, default=10000, # Reduced default
                        help="Number of top terms to select")
    parser.add_argument("--min_frequency", type=int, default=2,
                        help="Minimum frequency for a term to be included")
    parser.add_argument("--similarity_threshold", type=float, default=0.5,
                        help="Semantic similarity threshold for filtering (0-1)")
    parser.add_argument("--fuzzy_threshold", type=int, default=91,
                        help="Fuzzy deduplication threshold (0-100)")
    parser.add_argument("--semantic_dedup_threshold", type=float, default=0.9,
                        help="Semantic deduplication similarity threshold (0-1)")
    parser.add_argument("--chunk_size", type=int, default=1000,
                        help="Text chunk size for processing")

    args = parser.parse_args()

    print("\n" + "=" * 70)
    print("🔬 SPACY/TRANSFORMER MICROBIOME TERM EXTRACTION v8.0 (Refactored)")
    print("=" * 70)
    print("🧬 Focus: Advanced microbiome and biomedical term extraction")
    print(f"🤖 Method: sciSpaCy NER + '{EMBEDDING_MODEL}' for semantic processing")
    print(f"🎯 Output: Top {args.top_k} validated and deduplicated terms")
    print("=" * 70)

    try:
        config = Config(args)
        pipeline = SpaCyMicrobiomePipeline(config)
        pipeline.run()

        print("\n🎉 Pipeline completed successfully!")
        print(f"📂 Results saved to: {config.output_dir}")

    except Exception as e:
        print(f"\n❌ Pipeline failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()