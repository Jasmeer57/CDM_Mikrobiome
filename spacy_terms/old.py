#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
spaCy/sciSpaCy Microbiome Biomedical Term Extraction Pipeline - GOLD STANDARD v7.0 (Patched)
==========================================================================================
Production-ready pipeline using specialized biomedical spaCy models for extracting
microbiome-related terms with deterministic, reproducible outputs.


Features:
- Multiple sciSpaCy biomedical models
- Microbiome-focused term extraction
- Advanced fuzzy deduplication
- Semantic filtering with embeddings
- Gold standard validation
- Top 2K term selection
- Robust error handling
- **NEW in 6.1**: Added a noise-term blocklist to filter irrelevant terms like placeholders.


**--- PATCH NOTES v7.0 ---**
This version includes comprehensive fixes for the 12 major problems identified during data analysis.
- P1 (Synonymy): Added a synonym map to merge terms like 'microbiome' and 'microbiota'.
- P2 (Normalization): Implemented a more robust, deterministic normalization function.
- P3 (Noise): Expanded the noise blocklist significantly.
- P4 (Gold Labels): Added fuzzy matching to the Gold Standard Scorer to increase label coverage.
- P5 (Sparsity): Introduced a '--min_frequency' filter to remove single-occurrence noise.
- P6/P11 (Generic Labels): Added a rule-based entity label refinement map to specify generic 'ENTITY' tags.
- P7 (Scoring Bias): Re-weighted the final scoring formula to better value term frequency.
- P8 (Transparency): Added detailed comments explaining the scoring methodologies.
- P9 (Contradictions): Implemented a consistency check to prevent gold flags without categories.
- P10 (Examples): Now captures the full sentence context for examples, not just the term text.
- P12 (Traceability): Added 'source_filenames' to the output to trace terms back to their origin files.
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
   from sentence_transformers import SentenceTransformer
   SENTENCE_TRANSFORMERS_AVAILABLE = True
except ImportError:
   SENTENCE_TRANSFORMERS_AVAILABLE = False


# Biomedical models and configurations
SCISPACY_MODELS = [
   "en_ner_craft_md",      # Best for genes, proteins, organisms
   "en_ner_bc5cdr_md",     # Best for diseases and chemicals
   "en_core_sci_md",       # General scientific model with vectors
   "en_ner_jnlpba_md",     # Additional biomedical entities
]


SEMANTIC_MODEL = "en_core_sci_md"


# --- FIX for P1 (Conceptual Fragmentation) ---
# This map groups common synonyms under a single canonical form.
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
# Rules to refine generic 'ENTITY' labels into more specific categories.
ENTITY_REFINEMENT_RULES = {
   'ORGANISM': [r'\b(bacter|coccus|sp\.|spp\.|phage|virus)\b', r'[A-Z][a-z]+ [a-z]+'],
   'DISEASE': [r'\b(disease|syndrome|infection|itis|osis)\b'],
   'CHEMICAL': [r'\b(acid|peptide|protein|enzyme|lipid|ol|ate)\b'],
}




# Entity types with microbiome-focused weights
ENTITY_WEIGHTS = {
   'ORGANISM': 0.35,              # Highest for microbes
   'TAXON': 0.35,                 # Taxonomic classifications
   'GENE': 0.25,                  # Genes and genetic elements
   'GENE_OR_GENE_PRODUCT': 0.25,
   'CHEMICAL': 0.20,              # Metabolites, compounds
   'DISEASE': 0.18,               # Microbiome-related diseases
   'SO': 0.15,                    # Sequence ontology
   'GO': 0.15,                    # Gene ontology
   'CL': 0.15,                    # Cell types
   'CHEBI': 0.20,                 # Chemical entities
   'OTHER': 0.10
}


# Microbiome-specific seed terms
MICROBIOME_SEEDS = [
   "microbiome", "microbiota", "gut flora", "intestinal bacteria",
   "microbial community", "bacterial diversity", "dysbiosis",
   "probiotic", "prebiotic", "synbiotic", "postbiotic",
   "short-chain fatty acids", "SCFA", "butyrate", "propionate", "acetate",
   "Firmicutes", "Bacteroidetes", "Actinobacteria", "Proteobacteria",
   "Lactobacillus", "Bifidobacterium", "Clostridium", "Bacteroides",
   "gut-brain axis", "intestinal permeability", "leaky gut"
]


# --- RECOMMENDATION 1 & FIX for P3 (Noise) ---
# Expanded blocklist to filter out more irrelevant terms and noise.
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
   """Configuration management for spaCy-based extraction."""


   def __init__(self, args):
       self.input_dir = Path(args.input_dir)
       self.output_dir = Path(args.output_dir)
       self.output_dir.mkdir(parents=True, exist_ok=True)


       self.max_docs = args.max_docs if args.max_docs > 0 else float('inf')
       self.top_k = args.top_k if args.top_k > 0 else 10000
       self.seed_terms = MICROBIOME_SEEDS
       self.similarity_threshold = getattr(args, 'similarity_threshold', 0.5)
       self.fuzzy_threshold = getattr(args, 'fuzzy_threshold', 85)
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


       # Try cached version first
       if cache_file.exists():
           try:
               with open(cache_file, 'r', encoding='utf-8') as f:
                   words = set(line.strip().lower() for line in f if line.strip())
               logging.info(f"Loaded {len(words)} stopwords from cache")
               return words
           except Exception as e:
               logging.warning(f"Failed to load cached stopwords: {e}")


       # Build comprehensive stopword list
       stopwords = self._build_stopword_list()


       # Cache the stopwords
       try:
           with open(cache_file, 'w', encoding='utf-8') as f:
               for word in sorted(stopwords):
                   f.write(f"{word}\n")
       except Exception as e:
           logging.warning(f"Failed to cache stopwords: {e}")


       return stopwords


   def _build_stopword_list(self) -> Set[str]:
       """Build comprehensive stopword list."""
       # Basic English stopwords
       basic_stopwords = {
           'a', 'an', 'the', 'and', 'or', 'but', 'in', 'on', 'at', 'to',
           'for', 'of', 'with', 'by', 'from', 'up', 'about', 'into',
           'through', 'during', 'before', 'after', 'above', 'below',
           'between', 'among', 'against', 'within', 'without', 'toward'
       }


       # Try to get spaCy stopwords
       try:
           nlp = spacy.load("en_core_web_sm")
           spacy_stopwords = set(nlp.Defaults.stop_words)
           basic_stopwords.update(spacy_stopwords)
       except:
           pass


       # Biomedical publication stopwords (keep some important terms)
       biomedical_stopwords = {
           'abstract', 'introduction', 'background', 'methods', 'results',
           'discussion', 'conclusion', 'figure', 'table', 'author',
           'doi', 'pmid', 'copyright', 'rights', 'reserved',
           'significant', 'p-value', 'statistically', 'et', 'al'
       }


       # Remove biomedically important terms that shouldn't be stopwords
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
   """Semantic filtering optimized for microbiome terms."""


   def __init__(self, nlp_model, seed_terms: List[str], similarity_threshold: float = 0.5):
       self.nlp = nlp_model
       self.similarity_threshold = similarity_threshold
       self.seed_embeddings = []


       # Pre-compute seed embeddings
       for term in seed_terms:
           try:
               doc = self.nlp(term)
               if doc.vector_norm > 0:
                   self.seed_embeddings.append(doc.vector)
           except Exception as e:
               logging.debug(f"Could not get embedding for seed '{term}': {e}")


       if not self.seed_embeddings:
           logging.warning("No valid seed embeddings - semantic filtering disabled")


       logging.info(f"Semantic filter: {len(self.seed_embeddings)} seed embeddings loaded")


       # Microbiome-specific keywords for fallback
       self.microbiome_keywords = {
           'microb', 'bacteri', 'gut', 'intestin', 'flora', 'probiotic',
           'prebiotic', 'dysbiosis', 'metabolit', 'scfa', 'butyrate',
           'lactobacillus', 'bifidobacterium', 'clostridium', 'bacteroides',
           'firmicutes', 'bacteroidetes', 'actinobacteria'
       }


   def is_microbiome_relevant(self, term_text: str) -> Tuple[bool, float]:
       """Check if term is microbiome-relevant using multiple methods."""
       if not self.seed_embeddings:
           return self._keyword_relevance(term_text)


       try:
           doc = self.nlp(term_text)
           if doc.vector_norm == 0:
               return self._keyword_relevance(term_text)


           # Calculate semantic similarity
           similarities = []
           for seed_vec in self.seed_embeddings:
               similarity = np.dot(doc.vector, seed_vec) / (
                   doc.vector_norm * np.linalg.norm(seed_vec)
               )
               similarities.append(similarity)


           max_similarity = max(similarities) if similarities else 0


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


       # Direct matches
       for keyword in self.microbiome_keywords:
           if keyword in term_lower:
               return True, 0.8


       # Pattern matching for scientific names
       if re.match(r'^[A-Z][a-z]+ [a-z]+$', term_text):  # Genus species
           return True, 0.7


       # Check for biomedical suffixes
       biomedical_suffixes = ['osis', 'itis', 'ase', 'ine', 'ate', 'ide']
       if any(term_lower.endswith(suffix) for suffix in biomedical_suffixes):
           return True, 0.6


       return False, 0.0


class MicrobiomeGoldStandardScorer:
   """Gold standard scoring for microbiome terms."""


   def __init__(self):
       self.gold_terms = self._load_gold_standard_terms()
       self.flat_terms = {
           term.lower(): (category, confidence)
           for category, terms in self.gold_terms.items()
           for term, confidence in terms.items()
       }
       # --- FIX for P4 (Gold Labels) ---
       # Create a list of just the gold terms for fuzzy matching
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


   def get_gold_score(self, term: str, frequency: int = 1) -> Tuple[bool, Optional[str], float]:
       """Get gold standard score for a term, with fuzzy matching fallback."""
       term_lower = term.lower().strip()


       # Exact match first
       if term_lower in self.flat_terms:
           category, base_confidence = self.flat_terms[term_lower]
           frequency_boost = min(0.2, log1p(frequency) / 10.0)
           final_confidence = min(1.0, base_confidence + frequency_boost)
           return True, category, final_confidence


       # --- FIX for P4 (Gold Labels) ---
       # Fuzzy matching fallback if TheFuzz is available
       if THEFUZZ_AVAILABLE and self.gold_term_keys:
           best_match, score = process.extractOne(term_lower, self.gold_term_keys, scorer=fuzz.token_sort_ratio)
           if score >= 95:  # Use a high threshold to ensure accuracy
               category, base_confidence = self.flat_terms[best_match]
               # Apply a small penalty for fuzzy matching
               adjusted_confidence = base_confidence * (score / 100.0)
               frequency_boost = min(0.2, log1p(frequency) / 10.0)
               final_confidence = min(1.0, adjusted_confidence + frequency_boost)
               logging.info(f"Fuzzy matched '{term_lower}' to gold term '{best_match}' with score {score}")
               return True, category, final_confidence


       return False, None, 0.0


class AdvancedTermFilter:
   """Advanced term filtering for microbiome context."""


   # --- RECOMMENDATION 2: Enhance the AdvancedTermFilter ---
   def __init__(self, stopword_manager: StopwordManager, noise_terms: Set[str]):
       self.stopwords = stopword_manager.stopwords
       self.noise_terms = noise_terms # Store the blocklist


       # Enhanced filtering patterns
       self.invalid_patterns = [
           re.compile(r'^\W*\d+\.\d+\W*$'),      # Version numbers
           re.compile(r'^\W*\d+\W*$'),            # Pure numbers
           re.compile(r'^[A-Z]\W*$'),              # Single letters
           re.compile(r'.*\.(png|jpg|pdf|html)$', re.I),  # File extensions
           re.compile(r'^\W*(fig|table)\W*\d*\W*$', re.I),  # Figure/table refs
           re.compile(r'^\W*p\s*[<>=]\s*0\.\d+\W*$', re.I),  # P-values
           re.compile(r'^\W*doi:.*$', re.I),        # DOI strings
       ]


       # Biomedical artifact terms to exclude
       self.biomedical_artifacts = {
           'western blot', 'pcr', 'qpcr', 'elisa', 'anova', 't-test',
           'chi-square', 'confidence interval', 'standard deviation',
           'p-value', 'statistical significance', 'correlation coefficient'
       }


   def is_valid_term(self, term_text: str, entity_label: str = "") -> bool:
       """Comprehensive term validation including a noise blocklist."""
       term_text = term_text.strip()
       term_lower = term_text.lower()


       # Length checks
       if len(term_text) < 2 or len(term_text) > 100:
           return False


       # Pattern matching for invalid formats
       for pattern in self.invalid_patterns:
           if pattern.match(term_text):
               return False


       # Must contain letters
       if not any(c.isalpha() for c in term_text):
           return False
      
       # --- NEW: Blocklist filtering ---
       if term_lower in self.noise_terms:
           return False


       tokens = [token.lower() for token in term_text.split() if token.isalpha()]
       if not tokens:
           return False
      
       # Check if any part of a multi-word term is a noise term
       if any(token in self.noise_terms for token in tokens):
           return False


       # Stopword analysis
       # Check if all tokens are stopwords (with exceptions for short terms)
       non_stopword_count = sum(1 for token in tokens if token not in self.stopwords)
       if non_stopword_count == 0 and len(tokens) > 1:
           return False


       # Exclude methodology artifacts
       if term_lower in self.biomedical_artifacts:
           return False


       # Character composition check
       alpha_count = sum(1 for c in term_text if c.isalpha())
       if alpha_count / len(term_text) < 0.5:  # At least 50% letters
           return False


       return True


class ModelManager:
   """Efficient management of multiple spaCy models."""


   def __init__(self):
       self.models = {}
       self.semantic_model = None
       self._load_models()


   def _load_models(self):
       """Load biomedical spaCy models with graceful degradation."""
       if not SPACY_AVAILABLE:
           raise ImportError("spaCy not available")


       # Load semantic model first
       semantic_loaded = False
       for model_name in [SEMANTIC_MODEL, "en_core_web_lg", "en_core_web_md"]:
           try:
               self.semantic_model = spacy.load(model_name)
               logging.info(f"✅ Loaded semantic model: {model_name}")
               semantic_loaded = True
               break
           except OSError:
               logging.warning(f"⚠️ Model {model_name} not available")
               continue


       if not semantic_loaded:
           raise RuntimeError("No suitable semantic model available")


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
                gold_scorer: MicrobiomeGoldStandardScorer, term_filter: AdvancedTermFilter):
       self.model_manager = model_manager
       self.semantic_filter = semantic_filter
       self.gold_scorer = gold_scorer
       self.term_filter = term_filter
       self.chunker = TextChunker()


       self.stats = {
           'chunks_processed': 0,
           'entities_found': 0,
           'terms_validated': 0,
           'gold_terms_found': 0,
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


                   # Basic validation with the enhanced filter
                   if not self.term_filter.is_valid_term(ent.text, ent.label_):
                       continue


                   # Semantic relevance check
                   is_relevant, relevance_score = self.semantic_filter.is_microbiome_relevant(ent.text)
                   if not is_relevant:
                       continue
                  
                   # --- FIX for P1 & P2 (Synonymy & Normalization) ---
                   # Apply synonym mapping and robust normalization
                   canonical_form = self._normalize_term(ent, use_synonym_map=True)
                   if not canonical_form:
                       continue


                   # --- FIX for P6/P11 (Generic Labels) ---
                   # Refine entity label if it's too generic
                   original_label = ent.label_
                   refined_label = self._refine_entity_label(canonical_form, original_label)
                   if refined_label != original_label:
                       self.stats['labels_refined'] += 1


                   self.stats['terms_validated'] += 1


                   # --- FIX for P8 (Scoring Transparency) ---
                   # Calculate comprehensive score using a clear, commented method
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
                           'file_ids': {file_id}, # Changed to a set for easier aggregation
                           'chunk_id': chunk_idx,
                           # --- FIX for P10 (Examples) ---
                           # Capture sentence for better context
                           'examples': [self._capture_example_context(ent)],
                           'is_gold_standard': False,
                           'gold_category': None
                       }


                       # Apply gold standard scoring
                       is_gold, category, gold_score = self.gold_scorer.get_gold_score(canonical_form, 1)
                       # --- FIX for P9 (Contradictions) ---
                       # Ensure category exists before flagging as gold
                       if is_gold and category:
                           unique_terms[term_key]['relevance_score'] += gold_score * 0.5
                           unique_terms[term_key]['is_gold_standard'] = True
                           unique_terms[term_key]['gold_category'] = category
                           self.stats['gold_terms_found'] += 1
                       elif is_gold and not category:
                            logging.warning(f"Term '{canonical_form}' was gold but had no category. Flag removed.")




                   else:
                       # Update existing term
                       existing = unique_terms[term_key]
                       existing['frequency'] += 1
                       existing['model_sources'].add(model_name)
                       existing['file_ids'].add(file_id)


                       # Update score based on frequency
                       frequency_bonus = min(0.2, log1p(existing['frequency']) / 10.0)
                       existing['relevance_score'] = min(1.0, existing['relevance_score'] + frequency_bonus)


                       # Re-check gold standard with new frequency
                       is_gold, category, gold_score = self.gold_scorer.get_gold_score(
                           canonical_form, existing['frequency']
                       )
                       # --- FIX for P9 (Contradictions) ---
                       if is_gold and category:
                           existing['relevance_score'] = min(1.0, existing['relevance_score'] + gold_score * 0.3)
                           existing['is_gold_standard'] = True
                           existing['gold_category'] = category


                       # --- FIX for P10 (Examples) ---
                       # Add new, different example sentence
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
       """
       Robustly normalize entity to a deterministic canonical form.
       - Lemmatizes tokens
       - Converts to lowercase
       - Removes punctuation and spaces
       - (Optional) Applies a synonym map
       - Sorts tokens alphabetically to handle different word orders
       """
       try:
           tokens = []
           for token in entity:
               if not token.is_punct and not token.is_space:
                   lemma = token.lemma_.lower().strip()
                   if lemma and len(lemma) > 1:
                       tokens.append(lemma)
          
           # Sort tokens to make normalization deterministic regardless of word order
           sorted_tokens = sorted(tokens)
           normalized_form = " ".join(sorted_tokens) if sorted_tokens else ""


           if use_synonym_map:
               # Check original unsorted text first for better synonym matching
               original_lemmatized = " ".join(tokens)
               if original_lemmatized in SYNONYM_MAP:
                   return SYNONYM_MAP[original_lemmatized]
               if normalized_form in SYNONYM_MAP:
                   return SYNONYM_MAP[normalized_form]


           return normalized_form


       except Exception:
           # Fallback for any processing error
           return " ".join(sorted(re.sub(r'[^\w\s-]', '', entity.text.lower()).split()))


   # --- FIX for P8 (Scoring Transparency) ---
   def _calculate_base_score(self, entity, semantic_score: float) -> float:
       """
       Calculate the base relevance score for a term before frequency adjustments.
       The score is a weighted sum of several factors:
       - Base Score (0.3): A starting value for any valid term.
       - Entity Weight: A bonus based on the entity type's relevance to the microbiome domain.
                        (e.g., 'ORGANISM' gets a higher weight than 'OTHER').
       - Semantic Score (x0.3): The cosine similarity to microbiome seed terms. This measures
                                how contextually relevant the term is.
       - Term Complexity: A small bonus for multi-word terms (2-4 words), which are often
                          more specific, and a small penalty for single-word terms.
       The final score is capped at 1.0.
       """
       score = 0.3  # Base score


       # Entity type weight
       entity_weight = ENTITY_WEIGHTS.get(entity.label_, 0.1)
       score += entity_weight


       # Semantic similarity contribution
       score += semantic_score * 0.3


       # Term complexity (prefer 2-4 word terms)
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
           # Truncate long sentences for readability
           if len(sentence) > 250:
               start = max(0, entity.start_char - entity.sent.start_char - 75)
               end = min(len(sentence), entity.end_char - entity.sent.start_char + 75)
               return f"...{sentence[start:end]}..."
           return sentence
       except Exception:
           return entity.text # Fallback to just the entity text


   # --- FIX for P6/P11 (Generic Labels) ---
   def _refine_entity_label(self, term_text: str, original_label: str) -> str:
       """Refine a generic entity label using rule-based patterns."""
       if original_label not in ['ENTITY', 'OTHER']:
           return original_label # Don't change already specific labels


       term_lower = term_text.lower()
       for specific_label, patterns in ENTITY_REFINEMENT_RULES.items():
           for pattern in patterns:
               if re.search(pattern, term_lower):
                   return specific_label
      
       return original_label # Return original if no rules match


class IterativeDeduplicator:
   """Advanced iterative deduplication pipeline."""


   def __init__(self, fuzzy_threshold: int = 85):
       self.fuzzy_threshold = fuzzy_threshold


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
       if SENTENCE_TRANSFORMERS_AVAILABLE and len(stage3) < 10000:
           stage4 = self._semantic_clustering(stage3)
           logging.info(f"📊 Stage 4 (semantic): {len(stage4)} terms remaining")
       else:
           stage4 = stage3
           logging.info("📊 Stage 4 (semantic): Skipped")


       return stage4


   def _exact_deduplication(self, terms: List[Dict]) -> List[Dict]:
       """Exact string matching deduplication."""
       groups = defaultdict(list)


       for term in terms:
           key = (term['canonical_term'], term['entity_label'])
           groups[key].append(term)


       deduplicated = []
       for group in groups.values():
           merged = self._merge_term_group(group)
           deduplicated.append(merged)


       return sorted(deduplicated, key=lambda x: x['relevance_score'], reverse=True)


   def _case_normalized_deduplication(self, terms: List[Dict]) -> List[Dict]:
       """Case-insensitive with punctuation normalization."""
       groups = defaultdict(list)


       for term in terms:
           normalized_key = self._normalize_for_comparison(term['canonical_term'])
           groups[normalized_key].append(term)


       deduplicated = []
       for group in groups.values():
           merged = self._merge_term_group(group)
           deduplicated.append(merged)


       return deduplicated


   def _iterative_fuzzy_deduplication(self, terms: List[Dict]) -> List[Dict]:
       """Iterative fuzzy matching in batches."""
       if not THEFUZZ_AVAILABLE:
           return terms


       # Process in batches to manage complexity
       batch_size = 1000
       all_deduplicated = []


       for i in range(0, len(terms), batch_size):
           batch = terms[i:i + batch_size]
           deduplicated_batch = self._fuzzy_deduplicate_batch(batch)
           all_deduplicated.extend(deduplicated_batch)


       # Final pass to merge across batches
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


           # Find similar terms within reasonable distance
           search_end = min(len(terms), i + 200)  # Limit search scope


           for j in range(i + 1, search_end):
               if j in processed_indices:
                   continue


               candidate_text = terms[j]['canonical_term']


               # Skip if very different lengths
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


   def _semantic_clustering(self, terms: List[Dict]) -> List[Dict]:
       """Semantic similarity-based clustering."""
       try:
           model = SentenceTransformer('all-MiniLM-L6-v2')


           term_texts = [term['canonical_term'] for term in terms]
           embeddings = model.encode(term_texts, batch_size=32)


           # Use clustering approach
           from sklearn.cluster import DBSCAN


           clustering = DBSCAN(eps=0.3, min_samples=2, metric='cosine')
           cluster_labels = clustering.fit_predict(embeddings)


           # Group by clusters
           clusters = defaultdict(list)
           for term, label in zip(terms, cluster_labels):
               clusters[label].append(term)


           # Merge clusters
           final_terms = []
           for cluster_terms in clusters.values():
               merged = self._merge_term_group(cluster_terms)
               final_terms.append(merged)


           return final_terms


       except Exception as e:
           logging.warning(f"Semantic clustering failed: {e}")
           return terms


   def _normalize_for_comparison(self, term: str) -> str:
       """Normalize term for comparison."""
       # Remove punctuation, normalize case and spacing
       normalized = re.sub(r'[^\w\s-]', '', term.lower())
       normalized = re.sub(r'\s+', ' ', normalized)
       return normalized.strip()


   def _merge_term_group(self, group: List[Dict]) -> Dict:
       """Merge a group of similar terms."""
       if len(group) == 1:
           return group[0]


       # Select best representative
       best_term = max(group, key=lambda x: (
           x.get('relevance_score', 0),
           x.get('frequency', 1),
           int(x.get('is_gold_standard', False))
       ))


       # Aggregate statistics
       total_frequency = sum(term.get('frequency', 1) for term in group)
       # --- FIX for P12 (Traceability) ---
       all_file_ids = set()
       all_sources = set()
       all_examples = []


       for term in group:
           all_sources.update(term.get('model_sources', set()))
           all_examples.extend(term.get('examples', []))
           # Correctly aggregate file_ids from the set
           all_file_ids.update(term.get('file_ids', set()))




       # Calculate weighted relevance score
       weighted_score = sum(
           term.get('relevance_score', 0) * term.get('frequency', 1)
           for term in group
       ) / total_frequency


       # Update merged term
       merged = best_term.copy()
       merged.update({
           'frequency': total_frequency,
           'file_count': len(all_file_ids),
           'model_sources': all_sources, # Keep as a set
           'relevance_score': weighted_score,
           'examples': list(dict.fromkeys(all_examples))[:5],  # Keep unique examples
           'merged_from_count': len(group),
           # --- FIX for P12 (Traceability) ---
           'file_ids': all_file_ids # Store the aggregated set of file IDs
       })


       return merged


# --- RECOMMENDATION 3: Add a JSON Encoder that can handle sets ---
class JSONSerializableSetEncoder(json.JSONEncoder):
   """
   A custom JSON encoder that converts sets to lists to prevent serialization errors.
   """
   def default(self, obj):
       if isinstance(obj, set):
           return list(obj)
       return json.JSONEncoder.default(self, obj)


class ResultExporter:
   """Export results with comprehensive formatting."""


   def __init__(self, output_dir: Path, file_map: Dict[str, str]):
       self.output_dir = output_dir
       # --- FIX for P12 (Traceability) ---
       self.file_id_to_name_map = file_map




   def export_results(self, terms: List[Dict], metadata: Dict):
       """Export in multiple formats."""
       timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")


       # Export JSON
       self._export_json(terms, metadata, timestamp)


       # Export CSV
       self._export_csv(terms, timestamp)


       # Export summary
       self._export_summary(terms, metadata, timestamp)


   def _export_json(self, terms: List[Dict], metadata: Dict, timestamp: str):
       """Export comprehensive JSON."""
       output_data = {
           'extraction_metadata': metadata,
           'terms': terms
       }


       json_path = self.output_dir / f"spacy_extracted_terms_{timestamp}.json"


       try:
           with open(json_path, 'w', encoding='utf-8') as f:
               # Use the custom encoder to handle sets
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
               # --- FIX for P12 (Traceability) ---
               # Map file IDs back to their original filenames
               source_filenames = sorted([self.file_id_to_name_map.get(fid, 'unknown_file') for fid in term.get('file_ids', [])])


               row = {
                   'canonical_term': self._clean_text(term.get('canonical_term', '')),
                   'primary_form': self._clean_text(term.get('primary_form', '')),
                   'entity_label': term.get('entity_label', ''),
                   'gold_category': term.get('gold_category', ''),
                   'frequency': term.get('frequency', 1),
                   'file_count': term.get('file_count', 1),
                   'relevance_score': round(term.get('relevance_score', 0), 4),
                   'semantic_score': round(term.get('semantic_score', 0), 4),
                   'is_gold_standard': term.get('is_gold_standard', False),
                   'model_sources': ';'.join(sorted(list(term.get('model_sources', [])))),
                   'examples': ' | '.join(self._clean_text(ex) for ex in term.get('examples', [])[:3]),  # First 3 examples
                   'source_filenames': ';'.join(source_filenames) # New column for traceability
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
           # Calculate comprehensive statistics
           relevance_scores = [term.get('relevance_score', 0) for term in terms]
           semantic_scores = [term.get('semantic_score', 0) for term in terms]
           entity_labels = [term.get('entity_label', 'UNKNOWN') for term in terms]
           gold_categories = [term.get('gold_category', '') for term in terms if term.get('gold_category')]


           summary = {
               'extraction_summary': {
                   'total_terms': len(terms),
                   'gold_standard_terms': sum(1 for t in terms if t.get('is_gold_standard', False)),
                   'average_relevance_score': np.mean(relevance_scores) if relevance_scores else 0,
                   'average_semantic_score': np.mean(semantic_scores) if semantic_scores else 0,
                   'score_distribution': {
                       'high_relevance (>0.7)': sum(1 for s in relevance_scores if s > 0.7),
                       'medium_relevance (0.4-0.7)': sum(1 for s in relevance_scores if 0.4 <= s <= 0.7),
                       'low_relevance (<0.4)': sum(1 for s in relevance_scores if s < 0.4)
                   },
                   'entity_label_distribution': dict(Counter(entity_labels)),
                   'gold_category_distribution': dict(Counter(gold_categories)) if gold_categories else {}
               },
               'metadata': metadata,
               'export_info': {
                   'timestamp': datetime.now().isoformat(),
                   'pipeline_version': 'spacy_v7.0_patched'
               }
           }


           with open(summary_path, 'w', encoding='utf-8') as f:
               json.dump(summary, f, indent=2, ensure_ascii=False, cls=JSONSerializableSetEncoder)


           logging.info(f"✅ Summary exported: {summary_path}")


       except Exception as e:
           logging.error(f"❌ Summary export failed: {e}")


   def _clean_text(self, text: str) -> str:
       """Clean text for export."""
       if not text:
           return ""


       text = str(text)
       text = text.replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')
       text = re.sub(r'\s+', ' ', text)
       return text.strip()


class SpaCyMicrobiomePipeline:
   """Main pipeline orchestrator for spaCy-based extraction."""


   def __init__(self, config: Config):
       self.config = config
       self.logger = setup_logging(config.output_dir)
       # --- FIX for P12 (Traceability) ---
       self.file_id_to_name_map = {}




       # Initialize components
       self.logger.info("🔬 Initializing spaCy Microbiome Pipeline...")


       self.stopword_manager = StopwordManager()
       self.model_manager = ModelManager()


       self.semantic_filter = MicrobiomeSemanticFilter(
           self.model_manager.semantic_model,
           config.seed_terms,
           config.similarity_threshold
       )


       self.gold_scorer = MicrobiomeGoldStandardScorer()
       self.term_filter = AdvancedTermFilter(self.stopword_manager, NOISE_TERMS_BLOCKLIST)


       self.extractor = MicrobiomeExtractor(
           self.model_manager,
           self.semantic_filter,
           self.gold_scorer,
           self.term_filter
       )


       self.deduplicator = IterativeDeduplicator(config.fuzzy_threshold)
       # Pass the file map to the exporter for traceability
       self.exporter = ResultExporter(config.output_dir, self.file_id_to_name_map)


       self.logger.info("✅ Pipeline initialization completed")


   def run(self):
       """Execute the complete pipeline."""
       start_time = time.time()


       self.logger.info("🚀 Starting spaCy Microbiome Extraction Pipeline v7.0 (Patched)")


       try:
           # Load documents
           documents = self._load_documents()
           if not documents:
               return


           # Extract terms
           self.logger.info("🔬 Extracting microbiome terms...")
           all_terms = self._extract_terms(documents)


           if not all_terms:
               self.logger.error("❌ No terms extracted")
               return


           # Deduplicate
           self.logger.info("🔄 Performing iterative deduplication...")
           deduplicated_terms = self.deduplicator.deduplicate(all_terms)
          
           # --- FIX for P5 (Sparsity) ---
           # Apply minimum frequency filter before selecting top terms
           pre_filter_count = len(deduplicated_terms)
           frequency_filtered_terms = [
               term for term in deduplicated_terms if term.get('frequency', 1) >= self.config.min_frequency
           ]
           self.logger.info(f"🗑️  Filtered out {pre_filter_count - len(frequency_filtered_terms)} terms with frequency < {self.config.min_frequency}")




           # Select top terms
           final_terms = self._select_top_terms(frequency_filtered_terms)


           # Export results
           metadata = self._generate_metadata(len(documents), len(all_terms), len(final_terms))
           self.exporter.export_results(final_terms, metadata)


           # Log completion
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
                   documents.append({
                       'id': file_id,
                       'filename': file_path.name,
                       'content': content
                   })
                   # --- FIX for P12 (Traceability) ---
                   # Populate the file ID to name map
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


               if i % 20 == 0:  # Progress update
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
       def composite_score(term):
           """
           This function calculates the final ranking score for a term.
           It is a weighted sum designed to balance several indicators of importance:
           - Relevance Score (x0.30): The base score combining entity type, semantic similarity, and complexity.
           - Semantic Score (x0.20): A direct measure of contextual relevance to the microbiome domain.
           - Log of Frequency (x0.25): The term's overall frequency across all documents. Using a log scale
                                      rewards high-frequency terms without letting them completely dominate.
                                      This weight has been INCREASED to address P7.
           - Log of File Count (x0.20): The number of unique documents the term appears in (breadth).
                                      Log scale prevents outliers from having too much influence.
           - Gold Standard Bonus (0.5): A significant bonus if the term is in our curated gold standard list.
           """
           relevance = term.get('relevance_score', 0)
           frequency = term.get('frequency', 1)
           file_count = term.get('file_count', 1)
           is_gold = term.get('is_gold_standard', False)
           semantic = term.get('semantic_score', 0)


           score = (
               relevance * 0.30 +
               semantic * 0.20 +
               log1p(frequency) * 0.25 +  # Increased weight for frequency
               log1p(file_count) * 0.20 +
               (0.5 if is_gold else 0.0)
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
               'version': 'spacy_v7.0_patched', # Updated version
               'type': 'microbiome_spacy_extraction',
               'timestamp': datetime.now().isoformat()
           },
           'processing_statistics': {
               'documents_processed': num_docs,
               'chunks_processed': self.extractor.stats['chunks_processed'],
               'entities_found': self.extractor.stats['entities_found'],
               'labels_refined': self.extractor.stats['labels_refined'],
               'terms_validated': self.extractor.stats['terms_validated'],
               'gold_terms_found': self.extractor.stats['gold_terms_found'],
               'raw_terms_extracted': num_raw,
               'final_terms_selected': num_final
           },
           'configuration': {
               'max_documents': self.config.max_docs,
               'top_k_terms': self.config.top_k,
               'min_frequency': self.config.min_frequency,
               'similarity_threshold': self.config.similarity_threshold,
               'fuzzy_threshold': self.config.fuzzy_threshold,
               'chunk_size': self.config.chunk_size
           },
           'models_used': {
               'semantic_model': SEMANTIC_MODEL,
               'ner_models': list(self.model_manager.models.keys()),
               'deduplication_methods': ['exact', 'fuzzy', 'semantic'] if THEFUZZ_AVAILABLE else ['exact']
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
       self.logger.info(f"🏆 Gold standard terms: {self.extractor.stats['gold_terms_found']}")
       self.logger.info(f"📊 Raw terms extracted: {num_raw}")
       self.logger.info(f"✨ Final terms selected: {num_final}")


       if num_raw > 0:
           retention_rate = (num_final / num_raw) * 100
           self.logger.info(f"📈 Quality retention rate: {retention_rate:.1f}%")


       self.logger.info("=" * 60)


def main():
   """Main entry point."""
   parser = argparse.ArgumentParser(
       description="spaCy Microbiome Biomedical Term Extraction v7.0 (Patched)",
       formatter_class=argparse.ArgumentDefaultsHelpFormatter
   )


   parser.add_argument("--input_dir", type=str, required=True,
                       help="Input directory containing .txt files")
   parser.add_argument("--output_dir", type=str, default="./spacy_microbiome_output",
                       help="Output directory for results")
   parser.add_argument("--max_docs", type=int, default=350,
                       help="Maximum documents to process (-1 for all)")
   parser.add_argument("--top_k", type=int, default=20000,
                       help="Number of top terms to select")
   # --- FIX for P5 (Sparsity) ---
   parser.add_argument("--min_frequency", type=int, default=2,
                       help="Minimum frequency for a term to be included in the final list")
   parser.add_argument("--similarity_threshold", type=float, default=0.5,
                       help="Semantic similarity threshold (0-1)")
   parser.add_argument("--fuzzy_threshold", type=int, default=91,
                       help="Fuzzy deduplication threshold (0-100)")
   parser.add_argument("--chunk_size", type=int, default=1000,
                       help="Text chunk size for processing")


   args = parser.parse_args()


   print("\n" + "=" * 70)
   print("🔬 SPACY MICROBIOME BIOMEDICAL TERM EXTRACTION v7.0 (Patched)")
   print("=" * 70)
   print("🧬 Focus: Advanced microbiome and biomedical term extraction")
   print("🤖 Method: Multiple sciSpaCy models with semantic filtering and noise reduction")
   print("🎯 Output: Top 10K validated and deduplicated terms")
   print("=" * 70)


   try:
       config = Config(args)
       pipeline = SpaCyMicrobiomePipeline(config)
       pipeline.run()


       print("\n🎉 Pipeline completed successfully!")
       print(f"📂 Results saved to: {config.output_dir}")


   except Exception as e:
       print(f"\n❌ Pipeline failed: {e}")
       sys.exit(1)


if __name__ == "__main__":
   main()




