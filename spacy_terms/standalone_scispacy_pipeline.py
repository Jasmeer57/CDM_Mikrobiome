#!/usr/bin/env python3
"""
Standalone Scientific Term Extraction Pipeline (SciSpaCy Version)
=================================================================

A single-file, portable implementation of the advanced scientific term extraction pipeline.
Combines extraction, deduplication, and mapping into one robust script.

Features:
- **Extraction**: Uses sciSpaCy models (default: en_core_sci_lg)
- **Filtering**: Strict noise filtering (no names, URLs, generic terms)
- **Deduplication**: Exact + Fuzzy (Rapidfuzz) + Semantic (SentenceTransformers)
- **Mapping**: UMLS/BioPortal API integration (graceful fallback)
- **Robustness**: Handles missing keys/models without crashing

Usage:
    python standalone_scispacy_pipeline.py --input_dir data --output_dir output
"""

import os
import sys
import re
import json
import time
import logging
import argparse
import signal
from pathlib import Path
from typing import List, Dict, Any, Optional, Set, Tuple
from dataclasses import dataclass, field, asdict
from datetime import datetime
from collections import Counter
import concurrent.futures
import multiprocessing
from functools import partial

try:
    import torch
except ImportError:
    torch = None

try:
    import numpy as np
except ImportError:
    np = None

try:
    from sklearn.feature_extraction.text import TfidfVectorizer
except ImportError:
    TfidfVectorizer = None

# --- Configuration ---

@dataclass
class PipelineConfig:
    """Global configuration"""
    input_dir: str = "./data"
    output_dir: str = "./output"
    max_files: int = 100
    
    # Global Pipeline Settings - OPTIMIZED: Use 3 best models
    models_to_use: List[str] = field(default_factory=lambda: ["en_core_sci_md", "en_ner_bc5cdr_md", "en_core_sci_lg"])
    target_final_terms: int = 6000  # Smart target based on 100k raw terms
    max_raw_terms_limit: int = 100000  # Maximum raw terms for efficient processing (1 lakh)

    # Extraction
    spacy_model: str = "en_core_sci_md"  # Faster default model
    
    # Deduplication
    fuzzy_threshold: float = 0.85
    semantic_threshold: float = 0.90
    semantic_model: str = "all-MiniLM-L6-v2"  # Lightweight default
    
    # API Keys (loaded from env)
    bioportal_api_key: Optional[str] = os.getenv("BIOPORTAL_API_KEY")
    umls_api_key: Optional[str] = os.getenv("UMLS_API_KEY")

    # Advanced Features
    generate_definitions: bool = False
    correct_terms: bool = False
    map_umls: bool = False
    map_omop: bool = False
    map_bioportal: bool = False
    
    # Models
    definition_model: str = "BioMistral/BioMistral-7B" # Can be BioBERT if user insists (but won't work well for gen)
    correction_model: str = "BioMistral/BioMistral-7B"

    # Ollama Settings
    use_ollama: bool = False  # Use Ollama instead of HuggingFace models
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "mistral:latest"  # Default Mistral model in Ollama

    # Validation
    validate_biomistral: bool = False
    biomistral_model: str = "BioMistral/BioMistral-7B"
    load_4bit: bool = False
    batch_size: int = 32  # Batch size for GPU inference

    # Execution - OPTIMIZED: Better memory management
    workers: int = 2  # Increased to 2 for better parallelism
    checkpoint_file: str = "processed_files_checkpoint.json"
    memory_cleanup_interval: int = 5  # Cleanup every 5 files
    max_memory_gb: int = 10  # Memory limit

# --- Logging Setup ---

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("SciTermPipeline")

# --- Ollama Client ---

class OllamaClient:
    """Simple Ollama client for LLM inference"""

    def __init__(self, base_url: str = "http://localhost:11434", model: str = "mistral:latest"):
        self.base_url = base_url.rstrip('/')
        self.model = model

    def _call_ollama(self, prompt: str, temperature: float = 0.1, max_tokens: int = 512) -> Optional[str]:
        """Call Ollama API"""
        try:
            import requests

            url = f"{self.base_url}/api/generate"
            payload = {
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": temperature,
                    "num_predict": max_tokens
                }
            }

            response = requests.post(url, json=payload, timeout=60)
            if response.status_code == 200:
                result = response.json()
                return result.get('response', '')
            else:
                logger.error(f"Ollama API error: {response.status_code} - {response.text}")
                return None

        except Exception as e:
            logger.error(f"Ollama call failed: {e}")
            return None

    def generate_text(self, prompt: str, temperature: float = 0.1, max_tokens: int = 512) -> Optional[str]:
        """Generate text using Ollama"""
        return self._call_ollama(prompt, temperature, max_tokens)

    def check_connection(self) -> bool:
        """Check if Ollama is accessible"""
        try:
            import requests
            response = requests.get(f"{self.base_url}/api/tags", timeout=5)
            return response.status_code == 200
        except:
            return False

# --- Constants & Filters ---

# Available Models - OPTIMIZED: Use only 3 most effective models for speed
SCISPACY_MODELS = [
    "en_core_sci_md",        # Best general scientific terms
    "en_ner_bc5cdr_md",      # Best biomedical entities
    "en_core_sci_lg"         # High accuracy for verification
]

# Safe synonyms that don't lose clinical specificity
SAFE_SYNONYM_MAP = {
    "gut flora": "gut microbiota",
    "intestinal flora": "intestinal microbiota",
    "microbial flora": "microbiota",
    "16s ribosomal rna": "16s rrna",
    "16s rrna gene": "16s rrna",
    "e. coli": "escherichia coli",
    "c. difficile": "clostridioides difficile",
}

# --- Robust Filtering Constants (Ported from terms_extractor.py) ---

# P1-P28 Filters
FILTER_PATTERNS = {
    'P1': r'\b[A-Z]\.?\b',  # Single letters
    'P2': r'\b(etal|fig|figure|table|tab)\b\.?',  # Citations/refs
    'P3': r'^\d+$',  # Pure numbers
    'P4': r'^[a-zA-Z]$',  # Single chars
    'P5': r'^[^a-zA-Z]+$',  # No alphabetic
    'P6': r'^.{1,2}$',  # Very short
    'P7': r'^\W+$',  # Non-word
    'P8': r'^[0-9\W]+$',  # Numbers/symbols
    'P9': r'\b(and|or|the|of|in|on|at|to|for|with|by|as)\b',  # Stop words
    'P10': r'^[a-z]{1,3}$',  # Short lowercase
    'P11': r'^\W*\d+\W*$',  # Numbers with symbols
    'P12': r'^[^a-zA-Z]*[a-z][^a-zA-Z]*$',  # Single lowercase with symbols
    'P13': r'^[A-Z][a-z]+[0-9]+(?:\*|†)?$',  # Author names with numbers
    'P14': r'^[A-Z][a-z]+ [A-Z][a-z]+[0-9]+(?:\*|†)?$',  # Two author names with numbers
    'P15': r'^[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?\s+[0-9]+,\s*[0-9]+',  # Multiple authors
    'P16': r'https?://[^\s]+',  # URLs
    'P17': r'\b(?:university|department|institute|college|hospital|center|centre)\b',  # Institutions
    'P18': r'\b(?:abstract|introduction|methods|results|discussion|conclusion|references)\b',  # Sections
    'P19': r'\b(?:doi|isbn|issn|pmid|pmcid)\b',  # IDs
    'P20': r'\b(?:email|phone|fax|address|correspondence)\b',  # Contact
    'P21': r'\b(?:study|research|paper|article|report|manuscript)\b',  # Generic
    'P22': r'\b(?:cross-?sectional|prospective|retrospective|observational)\b\s+study',  # Study design
    'P23': r'^[A-Z][a-z]+,\s*[A-Z]\.?\s*[A-Z][a-z]+$',  # Author: Smith, J. John
    'P24': r'^[A-Z][a-z]+(?:-[A-Z][a-z]+)?\s+[A-Z]\.\s*[A-Z][a-z]+$',  # Author: Smith-Jones J. John
    'P25': r'\b(?:professor|dr|md|phd)\b',  # Titles
    'P26': r'^[A-Z][a-z]+(?:\s+[A-Z][a-z]+){2,}\s*[0-9]*\*?$',  # 3+ names with numbers
    'P27': r'/[A-Za-z0-9_\-./]+',  # File paths
    'P28': r'^[A-Z][a-z]+\s+et\s+al\.?$',  # et al
    'P29': r'\d{4};\d+:\d+(?:-\d+)?',  # Journal Citation
    'P30': r'^\b(?:J|Am|Nat|Sci|Cell|Mol|Biol|Med|Res|Rev|Ann|Arch|Clin|Eur|Int|Proc|Trans|Front|BMC|PLoS)\.?\s',  # Journal Abbrev
    'P31': r'\b[A-Z][a-z]+ [A-Z]{1,2}\b',  # Author Initials (e.g., Brown PO) - Reverted to simpler
    'P32': r'\bet al\.?',  # Any et al
    'P33': r'\b(?:vol|no|pp)\.\s*\d+',  # Volume/Page info
    'P34': r'^[A-Z]+\s+[A-Z]+$',  # All caps names
    'P35': r'\b(?:eds|ed)\.\b'  # Editors
}

# Enhanced Noise Blocklist
NOISE_TERMS = {
    "lorem", "ipsum", "introduction", "methods", "results", "discussion",
    "conclusion", "references", "acknowledgments", "author", "figure", "table", 
    "et al", "copyright", "rights", "reserved", "doi", "http", "www", "com", 
    "org", "edu", "journal", "press", "volume", "issue", "page", "editor",
    "publisher", "received", "accepted", "published", "supplementary", "data",
    "material", "appendix", "correspondence", "address", "email", "tel", "fax",
    "abstract", "background", "objective", "design", "setting", "participants",
    "interventions", "measurements", "limitations", "conclusions", "funding",
    "competing", "interests", "disclosure", "keywords", "abbreviations",
    "study", "analysis", "bacterial", "microbial", "result", "results",
    "significant", "high", "low", "increase", "decrease", "effect", "effects",
    "shown", "see", "view", "large", "small", "new", "old", "different",
    "similar", "observed", "detected", "measured", "calculated",
    "et", "al", "fig", "figs", "table", "tables", "ref", "refs",
    "journal", "doi", "pmid", "pmcid", "volume", "issue", "pages", "pp",
    "editor", "publisher", "received", "accepted", "revised", "published",
    "copyright", "license", "open", "access", "creative", "commons",
    "department", "university", "institute", "center", "centre", "hospital",
    "school", "college", "division", "laboratory", "group", "association",
    "society", "foundation", "committee", "council", "board", "ministry",
    "introduction", "methods", "results", "discussion", "conclusion",
    "references", "acknowledgments", "supporting", "information", "supplementary",
    "background", "objectives", "conclusions", "author", "authors", "contributions",
    "competing", "interests", "funding", "grant", "support", "correspondence",
    "available", "online", "download", "file", "click", "here", "visit", "website",
    "http", "https", "www", "com", "org", "net", "gov", "edu"
}

# Geographic Blocklist
GEO_BLOCKLIST = {
    "usa", "uk", "united states", "united kingdom", "china", "japan", "germany",
    "france", "italy", "spain", "canada", "australia", "brazil", "india",
    "russia", "korea", "netherlands", "sweden", "switzerland", "belgium",
    "london", "paris", "tokyo", "beijing", "new york", "boston", "cambridge",
    "oxford", "harvard", "stanford", "yale", "mit", "hospital", "center",
    "centre", "university", "institute", "school", "college", "department",
    "division", "laboratory", "foundation", "association", "society"
}

# High-value biomedical keywords (must contain at least one)
BIOMEDICAL_KEYWORDS = {
    'microbi', 'bacteri', 'gene', 'dna', 'rna', 'protein', 'enzyme', 'cell',
    'disease', 'infect', 'immun', 'metabol', 'pathogen', 'clinic', 'medic',
    'therap', 'antibiot', 'resistan', 'sequenc', 
    'acid', 'fatty', 'chain', 'synthesis', 'receptor', 'pathway',
    'genome', 'genom', 'transcript', 'express', 'mutat', 'amplif',
    'phylum', 'class', 'order', 'family', 'genus', 'species', 'strain',
    'diversity', 'abundance', 'community', 'population', 'phylogen',
    '16s', 'rrna', 'otu', 'asv', 'pcr'
}

# CDM Essential Domains
CDM_KEYWORDS = {
    'patient', 'subject', 'disease', 'disorder', 'drug', 'medication',
    'procedure', 'measurement', 'analysis', 'bacteria', 'virus', 'gene',
    'clinical', 'medical', 'health', 'study', 'research'
}

# Entity Refinement Rules
ENTITY_REFINEMENT_RULES = {
    'ORGANISM': [r'\b(bacter|coccus|sp\.|spp\.|phage|virus)\b', r'[A-Z][a-z]+ [a-z]+'],
    'DISEASE': [r'\b(disease|syndrome|infection|itis|osis)\b'],
    'CHEMICAL': [r'\b(acid|peptide|protein|enzyme|lipid|ol|ate)\b'],
}

# Invalid Regex Patterns (Advanced)
INVALID_PATTERNS = [
    re.compile(r'^\W*\d+\.\d+\W*$'),
    re.compile(r'^\W*\d+\W*$'),
    re.compile(r'^[A-Z]\W*$'),
    re.compile(r'.*\.(png|jpg|pdf|html)$', re.I),
    re.compile(r'^\W*(fig|table)\W*\d*\W*$', re.I),
    re.compile(r'^\W*p\s*[<>=]\s*0\.\d+\W*$', re.I),
    re.compile(r'^\W*doi:.*$', re.I),
    re.compile(r'^\W*https?://.*$', re.I),
    re.compile(r'^\W*www\..*$', re.I),
    re.compile(r'.*Co\.\W*$|.*Inc\.\W*$|.*Ltd\.\W*$', re.I),
    re.compile(r'.*University\W*$|.*Institute\W*$', re.I),
    re.compile(r'.*et\s+al\.\W*$', re.I),
    re.compile(r'^[A-Z][a-z]+,\s*[A-Z]\.\W*'),
    re.compile(r'.*[,:;]\W*$'),
    re.compile(r'^\W*(and|or|the|but|for|with|from)\W*$', re.I)
]

class ContextualCleaner:
    """Cleans terms based on context (Fixing OCR errors like newlines/hyphens)"""
    
    @staticmethod
    def clean_terms(terms: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        cleaned = []
        for t in terms:
            term = t['term']
            context = t.get('context', '')
            
            # 1. Fix broken newlines/hyphens
            # If term has \n or - inside, check if removing it makes sense in context
            # Actually, spacy might have already split it.
            # But if we have "bac\nteria", let's fix it.
            
            # 1. Unicode Normalization (Fix curly quotes, dashes, etc.)
            term = term.replace('\u2019', "'").replace('\u2018', "'").replace('\u2013', "-").replace('\u2014', "-")
            
            if '\n' in term or '- ' in term:
                # 2. Handle Hyphenation (word-\nword -> wordword)
                fixed = term.replace('-\n', '').replace('- ', '')
                
                # 3. Handle Line Breaks (word\nword -> word word)
                fixed = fixed.replace('\n', ' ')
                
                # 4. Collapse multiple spaces
                fixed = re.sub(r'\s+', ' ', fixed).strip()
                
                t['term'] = fixed
                t['original'] = term
            else:
                # Update term if only unicode changed
                t['term'] = term
            
            cleaned.append(t)
        return cleaned

# --- Domain Logic (Ported from old.py) ---

class MicrobiomeGoldStandardScorer:
    """Gold standard scoring for microbiome terms (Ported from old.py)"""

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

        # Fuzzy matching fallback
        try:
            from rapidfuzz import process, fuzz
            if self.gold_term_keys:
                match = process.extractOne(term_lower, self.gold_term_keys, scorer=fuzz.token_sort_ratio)
                if match:
                    best_match, score, _ = match
                    if score >= 95:  # High threshold
                        category, base_confidence = self.flat_terms[best_match]
                        adjusted_confidence = base_confidence * (score / 100.0)
                        return True, category, adjusted_confidence
        except ImportError:
            pass

        return False, None, 0.0

class MicrobiomeSemanticFilter:
    """Semantic filtering optimized for microbiome terms (Better Implementation using SentenceTransformer)"""

    def __init__(self, semantic_model=None, seed_terms: List[str] = None):
        self.model = semantic_model
        # Use default seeds if none provided
        self.seed_terms = seed_terms or [
           "microbiome", "microbiota", "gut flora", "intestinal bacteria",
           "microbial community", "bacterial diversity", "dysbiosis",
           "probiotic", "prebiotic", "synbiotic", "postbiotic",
           "short-chain fatty acids", "SCFA", "butyrate", "propionate", "acetate",
           "Firmicutes", "Bacteroidetes", "Actinobacteria", "Proteobacteria",
           "Lactobacillus", "Bifidobacterium", "Clostridium", "Bacteroides",
           "gut-brain axis", "intestinal permeability", "leaky gut"
        ]
        self.seed_embeddings = None
        self._precompute_embeddings()

        self.microbiome_keywords = {
            'microb', 'bacteri', 'gut', 'intestin', 'flora', 'probiotic',
            'prebiotic', 'dysbiosis', 'metabolit', 'scfa', 'butyrate',
            'lactobacillus', 'bifidobacterium', 'clostridium', 'bacteroides',
            'firmicutes', 'bacteroidetes', 'actinobacteria'
        }

    def _precompute_embeddings(self):
        if not self.model: return
        try:
            # Check if model is SentenceTransformer or TF-IDF
            if hasattr(self.model, 'encode'):
                self.seed_embeddings = self.model.encode(self.seed_terms)
        except Exception as e:
            logger.warning(f"Failed to precompute seed embeddings: {e}")

    def get_relevance_score(self, term_text: str) -> float:
        """Calculate relevance score using embeddings or keywords."""
        keyword_score = self._keyword_score(term_text)
        
        if self.seed_embeddings is None or not hasattr(self.model, 'encode'):
            return keyword_score

        try:
            # Encode term
            term_vec = self.model.encode([term_text])[0]
            
            # Calculate max similarity to seeds (Cosine Similarity)
            # Manual cosine sim for speed/independence from heavy libs if needed, 
            # but we likely have sklearn or torch if we have the model.
            # Let's use numpy for portability.
            
            norm_term = np.linalg.norm(term_vec)
            if norm_term == 0: return keyword_score
            
            # Vectorized cosine similarity
            # seed_embeddings is (N, D), term_vec is (D,)
            # dot product -> (N,)
            dots = np.dot(self.seed_embeddings, term_vec)
            norms = np.linalg.norm(self.seed_embeddings, axis=1) * norm_term
            
            # Avoid divide by zero
            sims = np.divide(dots, norms, out=np.zeros_like(dots), where=norms!=0)
            max_sim = np.max(sims) if len(sims) > 0 else 0.0
            
            return max(float(max_sim), keyword_score * 0.7)
            
        except Exception:
            return keyword_score

    def _keyword_score(self, term_text: str) -> float:
        term_lower = term_text.lower()
        for keyword in self.microbiome_keywords:
            if keyword in term_lower:
                return 0.8
        return 0.0

class TermRanker:
    """Ranks terms using Gold Standard, Semantic Similarity, and Frequency"""
    
    def __init__(self, config: PipelineConfig, semantic_model=None):
        self.config = config
        self.gold_scorer = MicrobiomeGoldStandardScorer()
        self.semantic_filter = MicrobiomeSemanticFilter(semantic_model)
        
    def rank_terms(self, terms: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        import math
        
        for term in terms:
            t_text = term['term']
            
            # 1. Gold Standard Score
            is_gold, category, gold_conf = self.gold_scorer.get_gold_score(t_text)
            term['is_gold_standard'] = is_gold
            term['gold_category'] = category if category else ""
            
            # 2. Semantic Score
            semantic_score = self.semantic_filter.get_relevance_score(t_text)
            term['semantic_score'] = round(semantic_score, 4)
            
            # 3. Calculate Composite Score (Logic from old.py)
            # Relevance (Base)
            relevance = 0.3 # Base
            if term.get('label') in ['ORGANISM', 'TAXON']: relevance += 0.2
            if term.get('label') in ['CHEMICAL', 'DISEASE']: relevance += 0.1
            
            # Mapped Bonus (Standalone feature)
            if term.get('mappings'): relevance += 0.2
            
            # Validation Bonus (Standalone feature)
            if term.get('validation', {}).get('is_valid'): relevance += 0.2
            
            relevance = min(1.0, relevance)
            
            frequency = term.get('frequency', 1)
            file_count = len(term.get('source_file', [])) if isinstance(term.get('source_file'), list) else 1
            
            # Formula:
            # Score = (Relevance * 0.3) + (Semantic * 0.2) + (log(Freq) * 0.25) + (log(FileCount) * 0.2) + (GoldBonus)
            
            score = (
                relevance * 0.30 +
                semantic_score * 0.20 +
                math.log1p(frequency) * 0.25 +
                math.log1p(file_count) * 0.20 +
                (0.5 if is_gold else 0.0)
            )
            
            term['score'] = round(score, 4)
            
        return sorted(terms, key=lambda x: x['score'], reverse=True)

# --- Components ---

class TermsExtractor:
    """Extracts terms using sciSpaCy with strict filtering"""
    
    def __init__(self, config: PipelineConfig):
        self.config = config
        self.nlp = self._load_model()
        
    def _load_model(self):
        """Load spaCy model with graceful fallback"""
        import spacy
        try:
            logger.info(f"Loading model: {self.config.spacy_model}")
            nlp = spacy.load(self.config.spacy_model)
            # Add sentencizer if missing
            if "sentencizer" not in nlp.pipe_names:
                nlp.add_pipe("sentencizer")
            return nlp
        except OSError:
            logger.warning(f"Model '{self.config.spacy_model}' not found.")
            logger.warning(f"⚠️  PLEASE INSTALL SCISPACY MODELS: python -m spacy download {self.config.spacy_model}")
            logger.warning("Attempting to use fallback 'en_core_web_sm' (Results will be suboptimal)...")
            try:
                nlp = spacy.load("en_core_web_sm")
                if "sentencizer" not in nlp.pipe_names:
                    nlp.add_pipe("sentencizer")
                return nlp
            except OSError:
                logger.error("Fallback model 'en_core_web_sm' also not found. Please install a spacy model.")
                sys.exit(1)

    def extract(self, text: str) -> List[Dict[str, Any]]:
        """Extract terms from text"""
        # Chunking Strategy (User Request: 4 chunks)
        # We split text into 4 overlapping chunks to improve recall
        
        chunk_size = len(text) // 4
        if chunk_size < 1000: # Don't chunk small files
            chunks = [text]
        else:
            # Create 4 chunks with overlap
            overlap = 200 # characters
            chunks = []
            for i in range(4):
                start = i * chunk_size
                # Adjust start to avoid breaking words (simple heuristic: find space)
                if i > 0:
                    start = max(0, start - overlap)
                    while start < len(text) and text[start] not in ' \n':
                        start -= 1
                
                end = (i + 1) * chunk_size
                if i < 3:
                    end = min(len(text), end + overlap)
                    while end < len(text) and text[end] not in ' \n':
                        end += 1
                else:
                    end = len(text)
                    
                chunks.append(text[start:end])
        
        all_terms = []
        seen_terms = set()
        
        for i, chunk in enumerate(chunks):
            logger.info(f"Processing chunk {i+1}/{len(chunks)} ({len(chunk)} chars)...")
            try:
                doc = self.nlp(chunk)
            except Exception as e:
                logger.warning(f"Spacy failed on chunk {i+1}: {e}")
                continue
                
            for ent in doc.ents:
                term = ent.text.strip()
                if not term: continue
                
                # Basic filtering
                if len(term) < 3: continue
                
                # Clean and normalize
                normalized = term.lower()
                
                # Check filters
                if not self._apply_filters(term):
                    continue
                    
                # Deduplicate within file (simple set check)
                if normalized in seen_terms:
                    continue
                seen_terms.add(normalized)
                
                label = ent.label_
                
                all_terms.append({
                    "term": normalized,
                    "original": term,
                    "label": label,
                    "source": "scispacy",
                    "context": ent.sent.text.strip().replace("\n", " ") if ent.sent else ""
                })
                
        # Apply Contextual Cleaning (OCR fix)
        all_terms = ContextualCleaner.clean_terms(all_terms)
                
        return all_terms

    def _apply_filters(self, term: str) -> bool:
        """Apply comprehensive P1-P28 filters and advanced checks"""
        term_lower = term.lower().strip()

        # 1. P1-P28 Pattern Filters
        for pattern in FILTER_PATTERNS.values():
            if re.search(pattern, term):
                return False

        # 2. Noise Blocklist
        if term_lower in NOISE_TERMS:
            return False
            
        # 3. Geo Blocklist
        if any(geo in term_lower for geo in GEO_BLOCKLIST):
            return False

        # 4. Advanced Invalid Patterns
        for pattern in INVALID_PATTERNS:
            if pattern.match(term):
                return False

        # 5. Length & Content
        if len(term) < 3 or len(term) > 100:
            return False
        if not any(c.isalpha() for c in term):
            return False

        # 6. Advanced Quality Check
        if not self._advanced_quality_check(term):
            return False

        # 7. Strict Biomedical Filter (Disabled for higher recall)
        # if not self._is_biomedical_term(term):
        #     return False

        # 8. CDM Relevance (Disabled for higher recall)
        # if not self._is_cdm_relevant(term):
        #     return False

        return True

    def _advanced_quality_check(self, term: str) -> bool:
        """Advanced quality checks for sophisticated filtering"""
        term_lower = term.lower()

        # Skip terms with few unique chars (e.g., "aaaa")
        if len(set(term_lower)) <= 2 and len(term) > 3:
            return False

        # Skip terms with no vowels (random strings)
        vowel_count = sum(1 for c in term_lower if c in 'aeiou')
        if len(term) > 5 and vowel_count == 0:
            return False

        # Skip product names/manufacturers
        if any(x in term_lower for x in ['kit', 'reagent', 'system', 'technology', 'solution']):
            return False

        # --- NEW: Author/Citation Filters ---
        
        # 1. Check for citation numbers attached to words (e.g., "Konishi3,7")
        # Regex: Word ending with digit(s) or digit-comma-digit
        if re.search(r'[a-zA-Z]+\d+(,\d+)*$', term):
            return False
            
        # 2. Check for "Surname, Name" pattern (common in author lists)
        # But be careful not to kill "Disease, Parkinson's" (though usually "Parkinson's Disease")
        # Author lists often have multiple commas: "Smith J, Doe A, ..."
        if term.count(',') >= 1:
            # If it looks like a list of names (Capitalized words separated by commas)
            parts = [p.strip() for p in term.split(',')]
            if all(p[0].isupper() for p in parts if p):
                # Likely a name list
                return False
                
        # 3. Check for common author/affiliation keywords
        author_keywords = ['et al', 'university', 'department', 'correspondence', 'received', 'accepted', 'published']
        if any(kw in term_lower for kw in author_keywords):
            return False

        # 9. Generic/Non-Scientific Term Filter
        if self._is_generic_term(term):
            return False

        return True

    def _is_generic_term(self, term: str) -> bool:
        """Filter out generic academic and non-scientific terms"""
        term_lower = term.lower()
        
        # 1. Blocked Generics (Expanded)
        blocked_generics = {
            'new', 'old', 'big', 'small', 'high', 'low', 'used', 'found',
            'study', 'analysis', 'experiment', 'result', 'data', 'method',
            'conclusion', 'discussion', 'background', 'introduction',
            'figure', 'table', 'fig', 'tab', 'section', 'chapter',
            'page', 'volume', 'issue', 'doi', 'url', 'http', 'https',
            'copyright', 'license', 'waiver', 'rights', 'reserved',
            'creative commons', 'public domain', 'dedication',
            'publisher', 'note', 'editor', 'author', 'contribution',
            'conflict of interest', 'funding', 'acknowledgement',
            'supplementary', 'material', 'file', 'available',
            'significant', 'difference', 'increase', 'decrease',
            'effect', 'role', 'impact', 'association', 'correlation',
            'group', 'population', 'cohort', 'sample', 'patient',
            'subject', 'participant', 'individual', 'human', 'people',
            'year', 'month', 'day', 'time', 'period', 'duration'
        }
        
        # Exact match check
        if term_lower in blocked_generics:
            return False
            
        # Check if term ends with a generic word (e.g. "this study")
        # But be careful: "gut microbiome study" -> maybe keep "gut microbiome"? 
        # The extractor usually grabs the whole noun phrase.
        # If the term is JUST "study" or "the study", it's blocked above or by stopword regex.
        
        # 2. License/Legal/Meta Text (Phrase matching)
        meta_phrases = [
            'creative commons', 'public domain', 'rights reserved', 'open access',
            'supplementary material', 'supplementary information', 'online version',
            'additional file', 'table s', 'figure s', 'fig s', 'available at',
            'http', 'doi.org', 'www.', 'et al', 'primer sequence'
        ]
        
        for phrase in meta_phrases:
            if phrase in term_lower:
                return True
                
        # 3. Primer sequences (long strings of ACTG)
        if re.search(r'^[actg\-\s]{10,}$', term_lower):
            return True
            
        return False

    def _is_biomedical_term(self, term: str) -> bool:
        """Strict filtering to keep only high-value biomedical terms"""
        term_lower = term.lower()
        
        # Must contain at least one biomedical keyword
        if not any(kw in term_lower for kw in BIOMEDICAL_KEYWORDS):
            return False
            
        # Block generic terms even if they have keywords
        blocked_generics = {
            'new', 'old', 'big', 'small', 'high', 'low', 'used', 'found',
            'study', 'analysis', 'experiment', 'result', 'data'
        }
        if term_lower in blocked_generics:
            return False
            
        return True

    def _is_cdm_relevant(self, term: str) -> bool:
        """CDM-specific filtering"""
        term_lower = term.lower()
        
        # Must contain at least one CDM keyword
        if not any(kw in term_lower for kw in CDM_KEYWORDS):
            return False
            
        # Block non-CDM academic terms
        blocked_cdm = {
            'university', 'department', 'funding', 'grant', 'publication',
            'version', 'software', 'p value', 'confidence interval'
        }
        if any(blocked in term_lower for blocked in blocked_cdm):
            return False
            
        return True

    def _normalize(self, term: str) -> str:
        """Normalize term (lowercase, synonym map)"""
        term_lower = term.lower()
        if term_lower in SAFE_SYNONYM_MAP:
            return SAFE_SYNONYM_MAP[term_lower]
        return term_lower

    def rank_terms(self, terms: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Rank terms using a weighted scoring system:
        - Microbiome Core: +5.0
        - CDM Core: +3.0
        - Biomedical: +1.0
        - Mapped: +2.0
        - Validated: +2.0
        - Frequency: + log(freq) * 0.5
        """
        import math
        
        for term in terms:
            score = 1.0
            t_lower = term['term'].lower()
            
            # 1. Microbiome Core (Highest Priority)
            microbiome_core = ['microbi', 'bacter', 'gut', 'flora', 'pathogen', 'dysbiosis', 'probiotic', 'antibiotic', 'resistome']
            if any(x in t_lower for x in microbiome_core):
                score += 5.0
                
            # 2. CDM Core (Study Design & Clinical)
            # Ensure CDM_KEYWORDS are used effectively
            if any(kw in t_lower for kw in CDM_KEYWORDS):
                score += 3.0
                
            # 3. Biomedical Keywords (General)
            if any(kw in t_lower for kw in BIOMEDICAL_KEYWORDS):
                score += 1.0
                
            # 4. Mapped Boost (High Confidence)
            if term.get('mappings'):
                score += 2.0
                
            # 5. Validation Boost
            if term.get('validation', {}).get('is_valid') == 'Yes':
                score += 2.0
                
            # 6. Frequency Boost (Logarithmic)
            freq = term.get('frequency', 1)
            if freq > 1:
                score += math.log(freq) * 0.5
                
            # 7. Length Penalty/Boost
            if len(t_lower) < 5:
                score -= 0.5
            elif len(t_lower) > 10:
                score += 0.5
                
            term['score'] = round(score, 2)
            
        # Sort by score descending
        return sorted(terms, key=lambda x: x['score'], reverse=True)


class TfidfSemanticModel:
    """Fallback semantic model using TF-IDF."""

    def __init__(self):
        if TfidfVectorizer is None:
            raise ImportError("scikit-learn is required for TF-IDF fallback semantic model")
        self.vectorizer = TfidfVectorizer(stop_words='english', analyzer='char_wb', ngram_range=(2, 4))
        self.is_fitted = False
        
    def encode(self, sentences: List[str], convert_to_tensor: bool = False):
        """
        Encode sentences using TF-IDF. 
        Note: This fits the vectorizer on the provided sentences every time if not fitted, 
        which is a simplification for this fallback.
        """
        if not sentences:
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

class SemanticCorrector:
    """Corrects and canonicalizes terms using Semantic Embeddings (MiniLM)"""
    
    def __init__(self, model):
        self.model = model
        
    def correct_terms(self, terms: List[Dict[str, Any]], threshold: float = 0.90) -> List[Dict[str, Any]]:
        """Cluster terms by semantic similarity and pick a canonical representative"""
        if not self.model or not terms:
            return terms
            
        logger.info(f"Running semantic correction on {len(terms)} terms...")
        
        # 1. Get embeddings
        term_texts = [t['term'] for t in terms]
        try:
            embeddings = self.model.encode(term_texts)
        except Exception as e:
            logger.warning(f"Semantic encoding failed: {e}")
            return terms
            
        # 2. Cluster (Greedy clustering)
        # Sort by length (prefer shorter as canonical? or frequency?)
        # Let's prefer higher frequency, then shorter length
        # But we don't have global frequency here easily unless we aggregated.
        # Let's just use the order provided, assuming sorted by quality/freq if possible.
        # Actually, let's sort indices by length for stability
        
        indices = sorted(range(len(terms)), key=lambda i: len(terms[i]['term']))
        
        clusters = []
        visited = set()
        
        import numpy as np
        
        # Normalize embeddings
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        embeddings = embeddings / (norms + 1e-9)
        
        for i in indices:
            if i in visited: continue
            
            cluster = [i]
            visited.add(i)
            
            # Find neighbors
            # Dot product with all others
            # Optimization: only check unvisited? No, check all to find best match?
            # Greedy: check unvisited.
            
            # Vectorized check against all unvisited is faster but complex to index.
            # Simple loop implementation (sufficient for typical file sizes < 1000 terms)
            
            vec_i = embeddings[i]
            
            # Calculate sims for all
            sims = np.dot(embeddings, vec_i)
            
            # Find matches > threshold
            matches = np.where(sims > threshold)[0]
            
            for match_idx in matches:
                if match_idx not in visited:
                    cluster.append(match_idx)
                    visited.add(match_idx)
            
            clusters.append(cluster)
            
        # 3. Canonicalize
        corrected_terms = []
        for cluster in clusters:
            # Pick representative term: Choose most frequent term, fallback to shortest
            cluster_terms = [terms[i] for i in cluster]
            # First try to find the term with highest frequency
            canonical = max(cluster_terms, key=lambda t: (t.get('frequency', 0), -len(t['term'])))
            # If all have same frequency (0), fallback to shortest term
            if canonical.get('frequency', 0) == 0:
                canonical = min(cluster_terms, key=lambda t: len(t['term']))
            
            # Merge metadata
            merged_examples = set()
            merged_files = set()
            total_freq = 0
            
            for t in cluster_terms:
                if t.get('examples'):
                    if isinstance(t['examples'], list): merged_examples.update(t['examples'])
                    elif isinstance(t['examples'], set): merged_examples.update(t['examples'])
                
                if t.get('source_file'):
                    if isinstance(t['source_file'], list): merged_files.update(t['source_file'])
                    else: merged_files.add(t['source_file'])
                    
                total_freq += t.get('frequency', 1)
                
            canonical['examples'] = list(merged_examples)[:5]
            canonical['source_file'] = list(merged_files)
            canonical['frequency'] = total_freq
            
            corrected_terms.append(canonical)
            
        logger.info(f"Semantic correction: {len(terms)} -> {len(corrected_terms)}")
        return corrected_terms

class Deduplicator:
    """Multi-layer deduplication"""
    
    def __init__(self, config: PipelineConfig):
        self.config = config
        self.semantic_model = self._load_semantic_model()
        self.corrector = SemanticCorrector(self.semantic_model)
        
    def _load_semantic_model(self):
        """Load sentence-transformers model or fallback to TF-IDF"""
        try:
            from sentence_transformers import SentenceTransformer
            logger.info(f"Loading semantic model: {self.config.semantic_model}")
            return SentenceTransformer(self.config.semantic_model)
        except ImportError:
            logger.warning("sentence-transformers not installed. Using TF-IDF fallback.")
            return TfidfSemanticModel()
        except Exception as e:
            logger.warning(f"Failed to load semantic model: {e}. Using TF-IDF fallback.")
            return TfidfSemanticModel()

    def deduplicate(self, terms: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """CONSERVATIVE deduplication - preserve maximum terms"""
        initial_count = len(terms)

        # STEP 1: ONLY Exact Deduplication - PRESERVE ALL VARIANTS
        logger.info("🔄 CONSERVATIVE DEDUPLICATION - PRESERVING MAXIMUM TERMS")

        unique_terms = {}
        for t in terms:
            # More conservative exact matching - case sensitive
            term_key = t['term'].strip()
            if term_key not in unique_terms:
                unique_terms[term_key] = t.copy()
                unique_terms[term_key]['frequency'] = 1
                unique_terms[term_key]['sources'] = [t.get('source_model', 'unknown')]
                unique_terms[term_key]['contexts'] = [t.get('context', '')] if t.get('context') else []
            else:
                # Merge metadata but keep original term
                existing = unique_terms[term_key]
                existing['frequency'] += 1
                if t.get('source_model') and t['source_model'] not in existing.get('sources', []):
                    existing.setdefault('sources', []).append(t['source_model'])
                if t.get('context') and t['context'] not in existing.get('contexts', []):
                    existing.setdefault('contexts', []).append(t['context'])

        terms = list(unique_terms.values())
        logger.info(f"Exact deduplication: {initial_count} -> {len(terms)} terms ({len(terms)/initial_count*100:.1f}% preserved)")

        # STEP 2: ONLY VERY CONSERVATIVE FUZZY DEDUPLICATION (high threshold)
        if self.config.fuzzy_threshold and len(terms) > 1:
            logger.info("Running very conservative fuzzy deduplication...")
            terms = self._conservative_fuzzy_dedup(terms)

        # STEP 3: OPTIONAL SEMANTIC PROCESSING (only if explicitly enabled)
        # Skip aggressive semantic deduplication to preserve more terms
        if self.semantic_model and self.config.semantic_threshold >= 0.95:  # Only if very high threshold
            logger.info("Running conservative semantic correction (high threshold)...")
            terms = self.corrector.correct_terms(terms, threshold=self.config.semantic_threshold)
        else:
            logger.info("Skipping semantic deduplication to preserve maximum terms")

        logger.info(f"🎯 FINAL: {len(terms)} terms preserved ({len(terms)/initial_count*100:.1f}% of original)")
        return terms

    def _conservative_fuzzy_dedup(self, terms: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Very conservative fuzzy deduplication with high threshold"""
        try:
            from rapidfuzz import fuzz
        except ImportError:
            logger.warning("rapidfuzz not installed, skipping fuzzy deduplication")
            return terms

        if len(terms) < 2:
            return terms

        # Use very high threshold - only merge near-identical terms
        threshold = max(0.90, self.config.fuzzy_threshold)  # Never below 0.90
        keep_indices = set(range(len(terms)))
        term_texts = [t['term'] for t in terms]

        logger.info(f"   Using fuzzy threshold: {threshold}")

        for i in range(len(terms)):
            if i not in keep_indices:
                continue

            for j in range(i + 1, len(terms)):
                if j not in keep_indices:
                    continue

                # Check fuzzy similarity - only for very similar terms
                similarity = fuzz.ratio(term_texts[i], term_texts[j]) / 100

                if similarity >= threshold:
                    # Very conservative merging logic
                    term_i_freq = terms[i].get('frequency', 1)
                    term_j_freq = terms[j].get('frequency', 1)

                    # Only merge if they're nearly identical and one has much higher frequency
                    if similarity >= 0.95 and max(term_i_freq, term_j_freq) > min(term_i_freq, term_j_freq) * 3:
                        if term_j_freq > term_i_freq:
                            keep_indices.discard(i)
                        else:
                            keep_indices.discard(j)

        preserved = [terms[i] for i in sorted(keep_indices)]
        logger.info(f"   Conservative fuzzy deduplication: {len(terms)} → {len(preserved)} terms")
        return preserved

    def _semantic_quality_filter(self, terms: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Filter out terms that are semantically similar to generic research concepts or non-scientific noise.
        Uses MiniLM embeddings in a contrastive manner (Scientific vs Noise).
        """
        if not self.semantic_model or not terms:
            return terms
            
        logger.info("Running Semantic Quality Filter (Contrastive)...")
        
        # Prototypes
        SCIENTIFIC_PROTOTYPES = [
            "bacterium", "microbiome", "gene expression", "protein", "enzyme", 
            "disease", "pathogen", "metabolite", "chemical compound", "clinical symptom", 
            "anatomy", "physiology", "molecular biology", "genetics", "pharmacology"
        ]
        
        NOISE_PROTOTYPES = [
            "scientific study", "research analysis", "statistical method", "data collection",
            "experimental result", "clinical trial", "literature review", "author contribution",
            "funding source", "conflict of interest", "copyright statement", "figure legend",
            "table caption", "supplementary material", "university department", "correspondence address",
            "p-value", "confidence interval", "standard deviation", "sample size",
            "significant difference", "observed effect", "increased level", "decreased value",
            "et al", "published by", "received on", "available online", "http url", "doi link",
            "primer sequence", "dna sequence string", "nucleotide sequence", "gene amplification method"
        ]
        
        term_strings = [t['term'] for t in terms]
        
        # Encode everything
        if isinstance(self.semantic_model, TfidfSemanticModel):
             # Fallback: Simple noise check if no embeddings
             combined = term_strings + NOISE_PROTOTYPES
             embeddings = self.semantic_model.encode(combined)
             term_embeddings = embeddings[:len(term_strings)]
             noise_embeddings = embeddings[len(term_strings):]
             scores = cosine_similarity(term_embeddings, noise_embeddings)
             
             keep_indices = []
             for i in range(len(terms)):
                 if scores[i].max() < 0.7: # Stricter fallback
                     keep_indices.append(i)
        else:
            # Encode terms, scientific, and noise
            term_embeddings = self.semantic_model.encode(term_strings, convert_to_tensor=True)
            sci_embeddings = self.semantic_model.encode(SCIENTIFIC_PROTOTYPES, convert_to_tensor=True)
            noise_embeddings = self.semantic_model.encode(NOISE_PROTOTYPES, convert_to_tensor=True)
            
            from sentence_transformers.util import cos_sim
            
            # Sim to Scientific
            sci_scores = cos_sim(term_embeddings, sci_embeddings) # (N_terms, N_sci)
            max_sci_score, _ = sci_scores.max(dim=1)
            
            # Sim to Noise
            noise_scores = cos_sim(term_embeddings, noise_embeddings) # (N_terms, N_noise)
            max_noise_score, _ = noise_scores.max(dim=1)
            
            keep_indices = []
            for i in range(len(terms)):
                # Logic: 
                # 1. Must have some scientific relevance (max_sci > 0.25)
                # 2. Must be more scientific than noise (max_sci > max_noise)
                # 3. Or if it's very close to noise (max_noise > 0.8), discard regardless
                
                s_score = max_sci_score[i].item()
                n_score = max_noise_score[i].item()
                
                if n_score > 0.8:
                    logger.info(f"   Dropping '{term_strings[i]}' (Noise Score: {n_score:.4f})")
                    continue # Definitely noise
                    
                if s_score > n_score:
                    keep_indices.append(i)
                elif s_score > 0.4: 
                    if s_score > n_score - 0.05:
                        keep_indices.append(i)
                else:
                    logger.info(f"   Dropping '{term_strings[i]}' (Sci: {s_score:.4f}, Noise: {n_score:.4f})")
        
        logger.info(f"Semantic Filter: {len(terms)} -> {len(keep_indices)} terms")
        return [terms[i] for i in keep_indices]

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
        terms.sort(key=lambda x: (x.get('frequency', 0), len(x.get('term', ''))), reverse=True)
        
        keep_indices = set(range(len(terms)))
        term_strings = [t.get('term', '') for t in terms]
        
        # Pre-compute embeddings if semantic model is available
        embeddings = None
        cosine_scores = None
        
        if self.semantic_model:
            if isinstance(self.semantic_model, TfidfSemanticModel):
                embeddings = self.semantic_model.encode(term_strings)
                cosine_scores = cosine_similarity(embeddings, embeddings)
            else:
                embeddings = self.semantic_model.encode(term_strings, convert_to_tensor=True)
                from sentence_transformers.util import cos_sim
                cosine_scores = cos_sim(embeddings, embeddings)

        for i in range(len(terms)):

            if i not in keep_indices: continue
            
            for j in range(i + 1, len(terms)):
                if j not in keep_indices: continue
                
                s1 = term_strings[i]
                s2 = term_strings[j]
                
                # 1. Lexical Check (High Fuzzy Ratio)
                lexical_score = fuzz.ratio(s1, s2)
                if lexical_score < 90: 
                    continue
                    
                # 2. Semantic Confirmation (if model available)
            # Semantic check
            if cosine_scores is not None:
                if isinstance(cosine_scores, np.ndarray):
                    semantic_score = cosine_scores[i][j]
                else:
                    semantic_score = cosine_scores[i][j].item()
                    
                if semantic_score < 0.85: 
                    continue
                
                # Merge s2 into s1
                terms[i]['frequency'] = terms[i].get('frequency', 1) + terms[j].get('frequency', 1)
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
        # But wait, user wants 'microbiome' terms ranked higher. 
        # We should respect the ranking if it was already done, but here we are in dedup.
        # Let's just remove clear substrings or high fuzzy matches.
        
        terms.sort(key=lambda x: len(x['term']), reverse=True)
        keep_indices = set(range(len(terms)))
        term_strings = [t['term'] for t in terms]
        
        for i in range(len(terms)):
            if i not in keep_indices: continue
            
            for j in range(i + 1, len(terms)):
                if j not in keep_indices: continue
                
                s1 = term_strings[i]
                s2 = term_strings[j]
                
                # Substring check
                if s2 in s1: # s2 is shorter and inside s1
                    # e.g. "gut microbiome" (s1) vs "microbiome" (s2) -> Keep s1
                    keep_indices.discard(j)
                    continue
                    
                # High fuzzy match
                if fuzz.ratio(s1, s2) > 92:
                    keep_indices.discard(j)
                    
        return [terms[i] for i in sorted(keep_indices)]

    def _fuzzy_dedup(self, terms: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Fuzzy deduplication using Rapidfuzz"""
        try:
            from rapidfuzz import process, fuzz
        except ImportError:
            logger.warning("rapidfuzz not installed. Fuzzy deduplication disabled.")
            return terms

        logger.info("Running fuzzy deduplication...")
        term_strings = [t['term'] for t in terms]
        keep_indices = set(range(len(terms)))
        
        # Simple O(N^2) approach - optimized for smaller batches (<5000 terms)
        # For larger batches, we'd need blocking/clustering
        for i in range(len(terms)):
            if i not in keep_indices: continue
            
            for j in range(i + 1, len(terms)):
                if j not in keep_indices: continue
                
                # Length check optimization
                if abs(len(term_strings[i]) - len(term_strings[j])) > 3:
                    continue
                    
                ratio = fuzz.ratio(term_strings[i], term_strings[j])
                if ratio >= self.config.fuzzy_threshold * 100:
                    # Keep the one that looks "better" (e.g., longer or more frequent)
                    # Here we just keep the first one for simplicity
                    keep_indices.discard(j)
                    
        return [terms[i] for i in sorted(keep_indices)]

    def _semantic_dedup(self, terms: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not terms or not self.semantic_model:
            return terms

        # Get embeddings for all terms
        term_strings = [t['term'] for t in terms]
        embeddings = self.semantic_model.encode(term_strings, convert_to_tensor=True)

        # Compute cosine similarity matrix
        cosine_scores = torch.nn.functional.normalize(embeddings, dim=1).mm(torch.nn.functional.normalize(embeddings, dim=1).T)

        keep_indices = set(range(len(terms)))

        # Iterate through upper triangle
        for i in range(len(terms)):
            if i not in keep_indices: continue

            for j in range(i + 1, len(terms)):
                if j not in keep_indices: continue

                if cosine_scores[i][j] >= self.config.semantic_threshold:
                    keep_indices.discard(j)

        return [terms[i] for i in sorted(keep_indices)]

    # def _biomedical_dedup(self, terms: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    #     """Biomedical context-aware deduplication (Cross-Encoder)"""
    #     try:
    #         from sentence_transformers import CrossEncoder
    #     except ImportError:
    #         logger.warning("sentence-transformers not installed. Biomedical deduplication disabled.")
    #         return terms

    #     if len(terms) < 2:
    #         return terms

    #     logger.info("Running biomedical deduplication (Cross-Encoder)...")

    #     # Load Cross-Encoder model
    #     try:
    #         model_name = "cross-encoder/stsb-roberta-base"
    #         logger.info(f"Loading Cross-Encoder: {model_name}")
    #         model = CrossEncoder(model_name)
    #     except Exception as e:
    #         logger.warning(f"Failed to load Cross-Encoder model: {e}")
    #         return terms

    #     keep_indices = set(range(len(terms)))
    #     term_strings = [t['term'] for t in terms]

    #     # 1. Identify candidate pairs to check
    #     potential_pairs = []

    #     if self.semantic_model:
    #         # Use embeddings to find candidates efficiently
    #         embeddings = self.semantic_model.encode(term_strings, convert_to_tensor=True)
    #         from sentence_transformers.util import cos_sim
    #         scores = cos_sim(embeddings, embeddings)

    #         for i in range(len(terms)):
    #             if i not in keep_indices: continue
    #             for j in range(i + 1, len(terms)):
    #                 if j not in keep_indices: continue
    #                 # Check if semantically somewhat close (e.g. > 0.75)
    #                 if scores[i][j] > 0.75:
    #                     potential_pairs.append((i, j))
    #     else:
    #         # Fallback: Check for word overlap
    #         for i in range(len(terms)):
    #             if i not in keep_indices: continue
    #             for j in range(i + 1, len(terms)):
    #                 if j not in keep_indices: continue
    #                 words_i = set(term_strings[i].split())
    #                 words_j = set(term_strings[j].split())
    #                 if words_i.intersection(words_j):
    #                     potential_pairs.append((i, j))

    #     if not potential_pairs:
    #         return terms

    #     # 2. Score pairs with Cross-Encoder
    #     logger.info(f"Checking {len(potential_pairs)} candidate pairs with Cross-Encoder...")

    #     # Prepare pairs for batch processing
    #     sentence_pairs = [[term_strings[i], term_strings[j]] for i, j in potential_pairs]

    #     try:
    #         similarity_scores = model.predict(sentence_pairs)

    #         for k, score in enumerate(similarity_scores):
    #             i, j = potential_pairs[k]

    #             # Threshold for "Duplicate" in biomedical context
    #             if score > 0.85:
    #                 # Keep the one that looks "better" (longer or more frequent)
    #                 if len(term_strings[i]) < len(term_strings[j]):
    #                     keep_indices.discard(j)
    #                 else:
    #                     keep_indices.discard(i)

    #     except Exception as e:
    #         logger.warning(f"Cross-Encoder check failed: {e}")

    #     return [terms[i] for i in sorted(keep_indices)]

    # Temporary replacement to skip biomedical deduplication
    def _biomedical_dedup(self, terms: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Biomedical deduplication disabled"""
        return terms


class DefinitionGenerator:
    """Generates definitions for terms using BioMistral or BioBERT"""
    
    def __init__(self, config: PipelineConfig):
        self.config = config
        self.pipeline = None
        self._load_model()
        
    def _load_model(self):
        """Load the model for definition generation"""
        if not self.config.generate_definitions:
            return

        try:
            if self.config.use_ollama:
                # Use Ollama
                self.ollama_client = OllamaClient(
                    base_url=self.config.ollama_base_url,
                    model=self.config.ollama_model
                )
                if self.ollama_client.check_connection():
                    logger.info(f"✅ Connected to Ollama using model: {self.config.ollama_model}")
                else:
                    logger.warning(f"⚠️ Could not connect to Ollama at {self.config.ollama_base_url}")
                    self.ollama_client = None
                return

            # Use HuggingFace transformers
            from transformers import pipeline, AutoTokenizer, AutoModelForCausalLM
            import torch

            model_name = self.config.biomistral_model
            logger.info(f"Loading definition model: {model_name}")

            if self.config.load_4bit:
                from transformers import BitsAndBytesConfig
                bnb_config = BitsAndBytesConfig(
                    load_in_4bit=True,
                    bnb_4bit_compute_dtype=torch.float16,
                    bnb_4bit_quant_type="nf4"
                )
                model = AutoModelForCausalLM.from_pretrained(
                    model_name,
                    quantization_config=bnb_config,
                    device_map="auto",
                    trust_remote_code=True
                )
            else:
                model = AutoModelForCausalLM.from_pretrained(
                    model_name,
                    device_map="auto",
                    torch_dtype=torch.float16,
                    trust_remote_code=True
                )

            tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
            tokenizer.pad_token = tokenizer.eos_token

            self.pipeline = pipeline(
                "text-generation",
                model=model,
                tokenizer=tokenizer,
                max_new_tokens=100,
                repetition_penalty=1.2
            )

        except Exception as e:
            logger.error(f"Failed to load definition model: {e}")
            self.pipeline = None

    def generate_definitions(self, terms: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Generate definitions for a list of terms"""
        # Check if we have a valid model (either Ollama or HuggingFace)
        if not terms:
            return terms

        if self.config.use_ollama and not hasattr(self, 'ollama_client'):
            logger.warning("Ollama configured but client not available")
            return terms
        elif not self.config.use_ollama and not self.pipeline:
            return terms

        logger.info(f"Generating definitions for {len(terms)} terms...")

        # Prepare prompts
        prompts = [
            f"""You are a specialized biomedical scientist and microbiome expert. Provide a precise, scientific definition for the following term.

TERM TO DEFINE: "{t['term']}"

DEFINITION REQUIREMENTS:
- Use proper biomedical terminology
- Be concise but comprehensive (15-30 words)
- Include the biological/medical context
- Focus on microbiome/biomedical relevance when applicable
- Use formal scientific language
- Specify if it's a gene, protein, metabolite, organism, etc.

Definition:"""
            for t in terms
        ]

        definitions = []

        try:
            from tqdm import tqdm

            if self.config.use_ollama and hasattr(self, 'ollama_client'):
                # Use Ollama for generation
                for i, prompt in enumerate(tqdm(prompts, desc="Generating Definitions (Ollama)")):
                    response = self.ollama_client.generate_text(
                        prompt,
                        temperature=0.7,
                        max_tokens=100
                    )
                    if response:
                        text = response.strip().replace('\n', ' ').strip('"').strip("'")
                        definitions.append(text)
                    else:
                        definitions.append("")  # Empty definition on failure
            else:
                # Use HuggingFace pipeline
                batch_size = self.config.batch_size
                for i in tqdm(range(0, len(prompts), batch_size), desc="Generating Definitions (HF)"):
                    batch_prompts = prompts[i:i + batch_size]

                    batch_outputs = self.pipeline(
                        batch_prompts,
                        do_sample=True,
                        temperature=0.7,
                        return_full_text=False,
                        batch_size=batch_size
                    )

                    for output in batch_outputs:
                        if isinstance(output, list):
                            output = output[0]
                        text = output['generated_text'].strip()
                        # Clean up: remove quotes, newlines
                        text = text.replace('\n', ' ').strip('"').strip("'")
                        definitions.append(text)

        except Exception as e:
            logger.error(f"Definition generation failed: {e}")
            remaining = len(prompts) - len(definitions)
            definitions.extend(["Error generating definition"] * remaining)
            
        # Assign back to terms
        for term, definition in zip(terms, definitions):
            term['definition'] = definition
            
        return terms


class LLMTermCorrector:
    """Corrects terms using BioMistral/LLM"""
    
    def __init__(self, config: PipelineConfig):
        self.config = config
        self.pipeline = None
        self._load_model()
        
    def _load_model(self):
        if not self.config.correct_terms:
            return

        try:
            if self.config.use_ollama:
                # Use Ollama
                self.ollama_client = OllamaClient(
                    base_url=self.config.ollama_base_url,
                    model=self.config.ollama_model
                )
                if self.ollama_client.check_connection():
                    logger.info(f"✅ Connected to Ollama using model: {self.config.ollama_model}")
                else:
                    logger.warning(f"⚠️ Could not connect to Ollama at {self.config.ollama_base_url}")
                    self.ollama_client = None
                return

            # Use HuggingFace transformers
            from transformers import pipeline, AutoTokenizer, AutoModelForCausalLM
            import torch

            model_name = self.config.biomistral_model
            logger.info(f"Loading correction model: {model_name}")

            if self.config.load_4bit:
                from transformers import BitsAndBytesConfig
                bnb_config = BitsAndBytesConfig(
                    load_in_4bit=True,
                    bnb_4bit_compute_dtype=torch.float16,
                    bnb_4bit_quant_type="nf4"
                )
                model = AutoModelForCausalLM.from_pretrained(
                    model_name,
                    quantization_config=bnb_config,
                    device_map="auto",
                    trust_remote_code=True
                )
            else:
                model = AutoModelForCausalLM.from_pretrained(
                    model_name,
                    device_map="auto",
                    torch_dtype=torch.float16,
                    trust_remote_code=True
                )

            tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
            tokenizer.pad_token = tokenizer.eos_token

            self.pipeline = pipeline(
                "text-generation",
                model=model,
                tokenizer=tokenizer,
                max_new_tokens=50,
                repetition_penalty=1.2
            )

        except Exception as e:
            logger.error(f"Failed to load correction model: {e}")
            self.pipeline = None

    def correct_terms(self, terms: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        # Check if we have a valid model (either Ollama or HuggingFace)
        if not terms:
            return terms

        if self.config.use_ollama and not hasattr(self, 'ollama_client'):
            logger.warning("Ollama configured but client not available")
            return terms
        elif not self.config.use_ollama and not self.pipeline:
            return terms

        logger.info(f"Correcting {len(terms)} terms with LLM...")

        prompts = [
            f"""You are a specialized biomedical terminology expert. Your goal is to extract and correct ONLY high-value, specific terms relevant to a Microbiome Common Data Model (CDM).

TERM TO CORRECT: "{t['term']}"

CORRECTION RULES:
1. Extract ONLY specific biomedical terms: specific organisms (species/genus), specific metabolites/chemicals, specific genes/proteins
2. Fix typos, spacing, and formatting issues
3. Standardize medical/biological terminology
4. Expand abbreviations to full form when appropriate
5. Remove junk text, numbers, symbols that aren't part of the term
6. Separate multiple distinct terms with semicolons if they're incorrectly combined
7. IGNORE generic scientific terms (e.g., "study", "analysis", "data", "results", "significant", "correlation")

Valid Categories: ORGANISM, GENE, PROTEIN, CHEMICAL, DISEASE, DNA_RNA, CELL_TYPE, BIOINFO_TOOL, GENOMICS, CLINICAL, SCIENTIFIC_TERM

Corrected Term:"""
            for t in terms
        ]

        corrections = []

        try:
            from tqdm import tqdm

            if self.config.use_ollama and hasattr(self, 'ollama_client'):
                # Use Ollama for correction
                for prompt in tqdm(prompts, desc="Correcting Terms (Ollama)"):
                    response = self.ollama_client.generate_text(
                        prompt,
                        temperature=0.1,
                        max_tokens=50
                    )
                    if response:
                        text = response.strip().split('\n')[0]  # Take first line
                        corrections.append(text)
                    else:
                        corrections.append("")  # Empty correction on failure
            else:
                # Use HuggingFace pipeline
                batch_size = self.config.batch_size
                for i in tqdm(range(0, len(prompts), batch_size), desc="Correcting Terms (HF)"):
                    batch_prompts = prompts[i:i + batch_size]

                    batch_outputs = self.pipeline(
                        batch_prompts,
                        do_sample=False,  # Deterministic for correction
                        temperature=0.1,
                        return_full_text=False,
                        batch_size=batch_size
                    )

                    for output in batch_outputs:
                        if isinstance(output, list):
                            output = output[0]
                        text = output['generated_text'].strip().split('\n')[0]  # Take first line
                        corrections.append(text)

        except Exception as e:
            logger.error(f"LLM correction failed: {e}")
            remaining = len(prompts) - len(corrections)
            corrections.extend(["Error"] * remaining)
            
        # Apply corrections
        for term, correction in zip(terms, corrections):
            if correction and correction != "Error" and correction.lower() != term['term'].lower():
                term['llm_correction'] = correction
                # Optionally update the main term, but safer to keep as metadata first
                # term['term'] = correction 
            
        return terms

    def correct_entity_types(self, terms: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Correct entity types using Mistral 7B with specialized microbiome prompts"""
        if not terms:
            return terms

        # Prepare batch of items for entity type correction
        items = [t['term'] for t in terms]

        prompt = f"""You are a specialized biomedical terminology expert for a Microbiome Common Data Model (CDM).

Correct the entity types for these terms according to microbiome/biomedical standards.

Valid Types: ORGANISM, GENE, PROTEIN, CHEMICAL, DISEASE, DNA_RNA, CELL_TYPE, BIOINFO_TOOL, GENOMICS, CLINICAL, SCIENTIFIC_TERM

Items to classify:
{chr(10).join(f"{i+1}. {item}" for i, item in enumerate(items))}

Return a JSON array of strings ["TYPE1", "TYPE2", ...] corresponding to each item.
Return ONLY the JSON array."""

        try:
            if self.config.use_ollama and hasattr(self, 'ollama_client'):
                response = self.ollama_client.generate_text(
                    prompt,
                    temperature=0.1,
                    max_tokens=200
                )

                if response:
                    import json
                    try:
                        # Parse JSON response
                        types_array = json.loads(response.strip())
                        if isinstance(types_array, list) and len(types_array) == len(terms):
                            # Update entity types
                            for term, new_type in zip(terms, types_array):
                                if new_type in ['ORGANISM', 'GENE', 'PROTEIN', 'CHEMICAL', 'DISEASE', 'DNA_RNA', 'CELL_TYPE', 'BIOINFO_TOOL', 'GENOMICS', 'CLINICAL', 'SCIENTIFIC_TERM']:
                                    term['corrected_label'] = new_type
                                else:
                                    term['corrected_label'] = term.get('label', 'ENTITY')
                        else:
                            logger.warning(f"Invalid response format for entity types: {response}")
                    except json.JSONDecodeError:
                        logger.warning(f"Failed to parse entity types JSON: {response}")
                else:
                    logger.warning("No response for entity type correction")

        except Exception as e:
            logger.error(f"Entity type correction failed: {e}")

        return terms

class UMLSMapper:
    """Maps terms to UMLS using SciSpaCy Linker"""
    
    def __init__(self, config: PipelineConfig):
        self.config = config
        self.linker = None
        self._load_linker()
        
    def _load_linker(self):
        if not self.config.map_umls:
            return
            
        try:
            import spacy
            from scispacy.linking import EntityLinker
            
            logger.info("Loading SciSpaCy UMLS Linker...")
            # We need a base model to add the linker to, or just use the linker class directly
            # But EntityLinker is a pipe. 
            # Let's load a small model just for linking context if needed, 
            # or use the CandidateGenerator directly if we want speed.
            # Using the pipe is easier.
            
            self.nlp = spacy.load("en_core_sci_sm")
            self.nlp.add_pipe("scispacy_linker", config={"resolve_abbreviations": True, "linker_name": "umls"})
            self.linker = self.nlp.get_pipe("scispacy_linker")
            
        except Exception as e:
            logger.error(f"Failed to load UMLS Linker: {e}")
            self.linker = None

    def map_terms(self, terms: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not self.linker or not terms:
            return terms
            
        logger.info(f"Mapping {len(terms)} terms to UMLS...")
        
        # Batch processing with nlp.pipe
        term_texts = [t['term'] for t in terms]
        
        try:
            docs = list(self.nlp.pipe(term_texts, batch_size=50))
            
            for term, doc in zip(terms, docs):
                # The doc contains the term as text. 
                # The linker links entities found in the doc.
                # Since the doc IS the term, we look at doc.ents
                
                mappings = []
                if doc.ents:
                    # Usually just one entity if the term is short
                    ent = doc.ents[0]
                    for umls_ent in ent._.kb_ents:
                        cui = umls_ent[0]
                        score = umls_ent[1]
                        # Get details from KB
                        entity_details = self.linker.kb.cui_to_entity[cui]
                        
                        mappings.append({
                            "cui": cui,
                            "name": entity_details.canonical_name,
                            "score": score,
                            "types": entity_details.types,
                            "source": "UMLS"
                        })
                        
                if mappings:
                    term['mappings'] = term.get('mappings', {})
                    term['mappings']['umls'] = mappings[:3] # Top 3
                    
        except Exception as e:
            logger.error(f"UMLS mapping failed: {e}")
            
        return terms

class OMOPMapper:
    """High-performance OMOP vocabulary mapper"""

    def __init__(self, config: PipelineConfig):
        self.config = config
        # Assume vocab is in a 'vocab' sibling directory to input or data/vocab
        self.vocab_dir = Path(config.input_dir).parent / "vocab"
        if not self.vocab_dir.exists():
             self.vocab_dir = Path("data/vocab")

        self.concepts_df = None
        self.synonyms_df = None
        self.lookup_df = None
        self.concept_cache = {}
        self.lookup_dict = {}  # Use dict for faster lookup

    def load_vocab(self):
        """Load OMOP vocabulary files and build optimized lookup table"""
        from pathlib import Path
        concept_file = Path("/home/jkalra/thesis/omop_vocab/CONCEPT.csv")
        synonym_file = Path("/home/jkalra/thesis/omop_vocab/CONCEPT_SYNONYM.csv")

        if not concept_file.exists():
            logger.warning(f"OMOP CONCEPT.csv not found at {concept_file}. OMOP mapping disabled.")
            return

        logger.info("Loading OMOP vocabulary (optimized)...")
        try:
            import pandas as pd

            # Load and filter concepts in chunks to avoid memory issues
            logger.info("Loading standard concepts...")
            chunks = []
            chunk_size = 50000
            for chunk in pd.read_csv(
                concept_file, sep='\t',
                usecols=['concept_id', 'concept_name', 'domain_id', 'vocabulary_id', 'standard_concept', 'concept_code'],
                dtype=str, na_filter=False, chunksize=chunk_size
            ):
                # Filter for standard concepts only
                standard_chunk = chunk[chunk['standard_concept'] == 'S']
                if not standard_chunk.empty:
                    chunks.append(standard_chunk)

            self.concepts_df = pd.concat(chunks, ignore_index=True)
            logger.info(f"Loaded {len(self.concepts_df)} standard concepts")

            # Load synonyms in chunks and filter efficiently
            if synonym_file.exists():
                logger.info("Loading synonyms...")
                valid_concept_ids = set(self.concepts_df['concept_id'])
                synonym_chunks = []

                for chunk in pd.read_csv(
                    synonym_file, sep='\t',
                    usecols=['concept_id', 'concept_synonym_name'],
                    dtype=str, na_filter=False, chunksize=chunk_size
                ):
                    # Filter for valid concept IDs only
                    valid_chunk = chunk[chunk['concept_id'].isin(valid_concept_ids)]
                    if not valid_chunk.empty:
                        synonym_chunks.append(valid_chunk)

                if synonym_chunks:
                    self.synonyms_df = pd.concat(synonym_chunks, ignore_index=True)
                    logger.info(f"Loaded {len(self.synonyms_df)} valid synonyms")
                else:
                    self.synonyms_df = pd.DataFrame(columns=['concept_id', 'concept_synonym_name'])
            else:
                self.synonyms_df = pd.DataFrame(columns=['concept_id', 'concept_synonym_name'])

            # Build optimized lookup
            self._build_optimized_lookup()

        except ImportError:
            logger.warning("pandas not installed. OMOP mapping disabled.")
        except Exception as e:
            logger.error(f"Failed to load OMOP vocab: {e}")

    def _preprocess_term(self, term: str) -> str:
        """Preprocess term for matching"""
        if not term: return ""
        term = term.lower()
        term = re.sub(r'[^a-z0-9\s]', ' ', term)
        term = re.sub(r'\s+', ' ', term).strip()
        return term

    def _build_optimized_lookup(self):
        """Build optimized lookup dictionary for fast matching"""
        import pandas as pd
        logger.info("Building optimized OMOP lookup dictionary...")

        # Clear existing lookup
        self.lookup_dict = {}

        # Process concepts
        logger.info("Processing concept names...")
        for idx, row in self.concepts_df.iterrows():
            concept_id = row['concept_id']
            concept_name = row['concept_name']

            # Add original concept name
            clean_name = self._preprocess_term(concept_name)
            if clean_name and len(clean_name) > 2:  # Skip very short terms
                if clean_name not in self.lookup_dict:
                    self.lookup_dict[clean_name] = []
                self.lookup_dict[clean_name].append({
                    'concept_id': concept_id,
                    'concept_name': concept_name,
                    'domain_id': row.get('domain_id', ''),
                    'vocabulary_id': row.get('vocabulary_id', ''),
                    'concept_code': row.get('concept_code', ''),
                    'match_type': 'exact'
                })

        # Process synonyms efficiently
        if not self.synonyms_df.empty:
            logger.info("Processing synonyms...")
            valid_concept_ids = set(self.concepts_df['concept_id'])

            for idx, row in self.synonyms_df.iterrows():
                concept_id = row['concept_id']
                synonym_name = row['concept_synonym_name']

                if concept_id in valid_concept_ids:
                    clean_synonym = self._preprocess_term(synonym_name)
                    if clean_synonym and len(clean_synonym) > 2:
                        if clean_synonym not in self.lookup_dict:
                            self.lookup_dict[clean_synonym] = []

                        # Get concept details from concepts_df
                        concept_info = self.concepts_df[self.concepts_df['concept_id'] == concept_id].iloc[0]
                        self.lookup_dict[clean_synonym].append({
                            'concept_id': concept_id,
                            'concept_name': concept_info['concept_name'],
                            'domain_id': concept_info.get('domain_id', ''),
                            'vocabulary_id': concept_info.get('vocabulary_id', ''),
                            'concept_code': concept_info.get('concept_code', ''),
                            'match_type': 'synonym'
                        })

        logger.info(f"Optimized lookup built with {len(self.lookup_dict)} terms")

    def _build_lookup_table(self):
        """Legacy method - redirect to optimized version"""
        self._build_optimized_lookup()

    def _build_concept_cache(self):
        """Cache concept details for quick access"""
        for _, row in self.concepts_df.iterrows():
            self.concept_cache[row['concept_id']] = row.to_dict()

    def map_terms(self, terms: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Map terms using optimized exact and fuzzy matching"""
        if not self.lookup_dict:
            logger.warning("OMOP lookup not loaded. Skipping OMOP mapping.")
            return terms

        logger.info(f"Mapping {len(terms)} terms to OMOP (optimized)...")

        try:
            from rapidfuzz import process, fuzz
            HAS_RAPIDFUZZ = True
        except ImportError:
            HAS_RAPIDFUZZ = False
            logger.warning("rapidfuzz not installed. Fuzzy OMOP matching disabled.")

        # Prepare terms for batch processing
        term_map = {t['term']: t for t in terms}
        unique_terms = list(term_map.keys())
        mapped_count = 0

        # Create lookup keys list for fuzzy matching
        lookup_keys = list(self.lookup_dict.keys())

        for i, term_str in enumerate(unique_terms):
            if i % 100 == 0:
                logger.info(f"  Progress: {i}/{len(unique_terms)} terms processed ({mapped_count} mapped)")

            clean_term = self._preprocess_term(term_str)
            if not clean_term or len(clean_term) < 3:
                continue

            matches = []

            # 1. Exact Match (optimized dictionary lookup)
            if clean_term in self.lookup_dict:
                for match_info in self.lookup_dict[clean_term]:
                    matches.append({
                        'concept_id': match_info['concept_id'],
                        'name': match_info['concept_name'],
                        'domain': match_info.get('domain_id', ''),
                        'vocabulary_id': match_info.get('vocabulary_id', ''),
                        'concept_code': match_info.get('concept_code', ''),
                        'score': 100.0,
                        'type': 'EXACT',
                        'match_type': match_info.get('match_type', 'exact')
                    })

            # 2. Fuzzy Match (if no exact match and rapidfuzz available)
            if not matches and HAS_RAPIDFUZZ and len(clean_term) >= 4:
                # Use rapidfuzz for efficient fuzzy matching
                result = process.extractOne(
                    clean_term,
                    lookup_keys,
                    scorer=fuzz.WRatio,
                    score_cutoff=85  # High threshold for quality
                )

                if result:
                    match_term, score, _ = result
                    if score >= 85 and match_term in self.lookup_dict:
                        # Take the first (best) match from fuzzy search
                        match_info = self.lookup_dict[match_term][0]
                        matches.append({
                            'concept_id': match_info['concept_id'],
                            'name': match_info['concept_name'],
                            'domain': match_info.get('domain_id', ''),
                            'vocabulary_id': match_info.get('vocabulary_id', ''),
                            'concept_code': match_info.get('concept_code', ''),
                            'score': score,
                            'type': 'FUZZY',
                            'match_type': match_info.get('match_type', 'fuzzy')
                        })

            # Update term with matches
            if matches:
                term_obj = term_map[term_str]
                term_obj['omop_mappings'] = matches[:3]  # Keep top 3 matches
                mapped_count += 1

        logger.info(f"OMOP mapping complete: {mapped_count}/{len(unique_terms)} terms mapped")
        return terms


class ComprehensiveMapper:
    """Unified Mapper for UMLS, BioPortal, and OMOP (optional)"""

    # API Endpoints
    BIOPORTAL_API = "https://data.bioontology.org/search"
    OLS_API = "https://www.ebi.ac.uk/ols/api/search"

    def __init__(self, config: PipelineConfig):
        self.config = config
        self.omop_mapper = None
        self.umls_mapper = None

        # Only load OMOP if explicitly requested and not problematic
        if config.map_omop:
            try:
                self.omop_mapper = OMOPMapper(config)
                self.omop_mapper.load_vocab()
                logger.info("OMOP mapper loaded successfully")
            except Exception as e:
                logger.warning(f"Failed to load OMOP mapper (skipping): {e}")
                self.omop_mapper = None

        # Load UMLS mapper
        if config.map_umls:
            try:
                self.umls_mapper = UMLSMapper(config)
                logger.info("UMLS mapper loaded successfully")
            except Exception as e:
                logger.warning(f"Failed to load UMLS mapper (skipping): {e}")
                self.umls_mapper = None
        
    def map_terms(self, terms: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Run all mapping strategies (excluding OMOP by default)"""

        logger.info("Starting comprehensive mapping (UMLS + BioPortal/OLS)...")

        # 1. OMOP Mapping (only if successfully loaded)
        if self.omop_mapper:
            try:
                terms = self.omop_mapper.map_terms(terms)
            except Exception as e:
                logger.warning(f"OMOP mapping failed (skipping): {e}")
        else:
            logger.info("Skipping OMOP mapping (disabled or failed to load)")

        # 2. UMLS Mapping (use UMLSMapper)
        if self.umls_mapper:
            try:
                terms = self.umls_mapper.map_terms(terms)
                # Convert UMLS mappings to expected format
                for term in terms:
                    if 'mappings' in term and 'umls' in term['mappings']:
                        term['umls_mappings'] = term['mappings']['umls']
                        # Convert to expected format
                        for umls_map in term['umls_mappings']:
                            umls_map['concept_id'] = umls_map.pop('cui', '')
                            umls_map['concept_name'] = umls_map.pop('name', '')
                            umls_map['semantic_types'] = umls_map.pop('types', [])
                            umls_map['score'] = float(umls_map.get('score', 0)) * 100  # Convert to percentage
            except Exception as e:
                logger.warning(f"UMLS mapping failed: {e}")
        else:
            logger.info("Skipping UMLS mapping (disabled or failed to load)")

        # 3. BioPortal/OLS API Mapping
        if self.config.bioportal_api_key:
            try:
                terms = self._map_bioportal(terms)
            except Exception as e:
                logger.warning(f"BioPortal mapping failed: {e}")
        else:
            # Fallback to OLS if no BioPortal key
            try:
                terms = self._map_ols(terms)
            except Exception as e:
                logger.warning(f"OLS mapping failed: {e}")

        return terms
        
    def _map_bioportal(self, terms: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Map to BioPortal using real API"""
        import requests
        
        logger.info(f"Mapping {len(terms)} terms to BioPortal...")
        
        # Use session for connection pooling
        session = requests.Session()
        headers = {"Authorization": f"apikey token={self.config.bioportal_api_key}"}
        
        for term_data in terms:
            term = term_data['term']
            try:
                params = {
                    "q": term,
                    "ontologies": "SNOMEDCT,LOINC,RXNORM,MESH,ICD10",
                    "require_exact_match": "true",
                    "pagesize": 3,
                    "apikey": self.config.bioportal_api_key
                }
                
                response = session.get(self.BIOPORTAL_API, params=params, timeout=5)
                if response.status_code == 200:
                    data = response.json()
                    matches = []
                    for item in data.get("collection", []):
                        matches.append({
                            "id": item.get("@id"),
                            "label": item.get("prefLabel"),
                            "ontology": item.get("links", {}).get("ontology", "").split("/")[-1],
                            "source": "BioPortal"
                        })
                    
                    if matches:
                        term_data['mappings'] = term_data.get('mappings', {})
                        term_data['mappings']['bioportal'] = matches
                
                # Rate limiting niceness
                time.sleep(0.1)
                
            except Exception as e:
                logger.warning(f"BioPortal error for {term}: {e}")
                
        return terms

    def _map_ols(self, terms: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Map to OLS (Free, no key required)"""
        import requests
        
        logger.info(f"Mapping {len(terms)} terms to OLS...")
        session = requests.Session()
        
        for term_data in terms:
            term = term_data['term']
            try:
                params = {
                    "q": term,
                    "ontology": "ncit,mondo,doid,hp,go",
                    "rows": 3
                }
                
                response = session.get(self.OLS_API, params=params, timeout=5)
                if response.status_code == 200:
                    data = response.json()
                    matches = []
                    for doc in data.get("response", {}).get("docs", []):
                        matches.append({
                            "id": doc.get("obo_id") or doc.get("iri"),
                            "label": doc.get("label"),
                            "ontology": doc.get("ontology_name"),
                            "source": "OLS"
                        })
                        
                    if matches:
                        term_data['mappings'] = term_data.get('mappings', {})
                        term_data['mappings']['ols'] = matches
                        
                time.sleep(0.05)
                
            except Exception as e:
                logger.warning(f"OLS error for {term}: {e}")
                
        return terms

    def _map_ncbo(self, terms: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Map using NCBO Annotator"""
        if not self.config.bioportal_api_key:
            return terms
            
        import requests
        logger.info(f"Mapping {len(terms)} terms using NCBO Annotator...")
        session = requests.Session()
        headers = {"Authorization": f"apikey token={self.config.bioportal_api_key}"}
        
        for term_data in terms:
            term = term_data['term']
            try:
                params = {
                    "text": term,
                    "longest_only": "true",
                    "ontologies": "SNOMEDCT,LOINC,RXNORM,MESH,ICD10",
                    "apikey": self.config.bioportal_api_key
                }
                
                response = session.get("https://data.bioontology.org/annotator", params=params, timeout=5)
                if response.status_code == 200:
                    data = response.json()
                    matches = []
                    for annotation in data[:3]:
                        annotated_class = annotation.get("annotatedClass", {})
                        matches.append({
                            "id": annotated_class.get("@id"),
                            "label": annotated_class.get("prefLabel"),
                            "ontology": annotated_class.get("links", {}).get("ontology", "").split("/")[-1],
                            "source": "NCBO"
                        })
                        
                    if matches:
                        term_data['mappings'] = term_data.get('mappings', {})
                        term_data['mappings']['ncbo'] = matches
                        
                time.sleep(0.1)
                
            except Exception as e:
                logger.warning(f"NCBO error for {term}: {e}")
                
        return terms


class BioMistralValidator:
    """Validator using BioMistral-7B"""
    def __init__(self, config: PipelineConfig):
        self.config = config
        self.pipeline = None
        self.tokenizer = None
        self.model = None

    def load_model(self):
        """Load the BioMistral model"""
        try:
            from transformers import AutoModelForCausalLM, AutoTokenizer, pipeline
            import torch
            
            model_name = self.config.biomistral_model
            logger.info(f"Loading BioMistral model: {model_name} (4-bit: {self.config.load_4bit})...")
            
            kwargs = {
                "device_map": "auto",
                "trust_remote_code": True,
                "offload_folder": "offload"
            }
            
            if self.config.load_4bit:
                try:
                    from transformers import BitsAndBytesConfig
                    kwargs["quantization_config"] = BitsAndBytesConfig(
                        load_in_4bit=True,
                        bnb_4bit_compute_dtype=torch.float16
                    )
                except ImportError:
                    logger.warning("bitsandbytes not installed. Falling back to standard loading.")
            
            self.model = AutoModelForCausalLM.from_pretrained(model_name, **kwargs)
            self.tokenizer = AutoTokenizer.from_pretrained(model_name)
            self.tokenizer.pad_token_id = self.model.config.eos_token_id
            self.tokenizer.padding_side = 'left'
            
            # Create generation pipeline
            self.pipeline = pipeline(
                "text-generation",
                model=self.model,
                tokenizer=self.tokenizer,
                max_new_tokens=10
            )
            logger.info("BioMistral model loaded successfully.")
            return True
            
        except Exception as e:
            logger.error(f"Failed to load BioMistral model: {e}")
            return False

    def validate_terms(self, terms: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Validate terms using BioMistral with batch processing"""
        if not self.config.validate_biomistral:
            return terms
            
        if not self.pipeline:
            if not self.load_model():
                return terms

        logger.info(f"Validating {len(terms)} terms with BioMistral (Batch Size: {self.config.batch_size})...")
        
        # Filter terms that need validation
        terms_to_validate = [t for t in terms if t.get('term')]
        if not terms_to_validate:
            return terms

        # Prepare prompts
        prompts = []
        for t in terms_to_validate:
            term = t['term']
            prompt = f"""You are a specialized biomedical research curator. Evaluate if this term should be kept in a high-quality microbiome/biomedical dataset for a Microbiome Common Data Model (CDM).

TERM TO EVALUATE: "{term}"

EVALUATION CRITERIA:
✅ KEEP: Valid biological entities (genes, proteins, bacteria, metabolites, diseases)
✅ KEEP: Medical procedures, tests, treatments, methodologies
✅ KEEP: Anatomical terms, biological processes, pathways
✅ KEEP: Chemical compounds, drugs, supplements
✅ KEEP: Specific organisms (species/genus level), taxonomic groups

❌ REJECT: Author names, citations, references (e.g., "Smith J", "et al 2015")
❌ REJECT: University names, departments, institutions, locations
❌ REJECT: Generic scientific words (e.g., "study", "result", "significant", "control", "correlation")
❌ REJECT: File names, sequences, random characters, measurement units alone
❌ REJECT: Incomplete phrases, sentence fragments, formatting artifacts

CRITICAL: Aim for HIGH PRECISION. Target only the most valuable, specific entities.

DECISION (Yes/No):
REASON (brief):"""
            prompts.append(prompt)

        # Run batch inference
        batch_size = self.config.batch_size
        results = []
        
        try:
            # Use tqdm for progress
            for i in range(0, len(prompts), batch_size):
                batch_prompts = prompts[i:i + batch_size]
                
                # Pipeline call with batch
                batch_outputs = self.pipeline(
                    batch_prompts, 
                    do_sample=False, 
                    temperature=0.1,
                    return_full_text=False,
                    batch_size=batch_size
                )
                
                for output in batch_outputs:
                    # Handle case where output might be a list (some pipeline versions)
                    if isinstance(output, list):
                        output = output[0]
                    results.append(output['generated_text'].strip().lower())
                    
        except Exception as e:
            logger.error(f"Batch validation failed: {e}")
            # Fallback to error for all remaining
            remaining = len(prompts) - len(results)
            results.extend(["error"] * remaining)

        # Assign results back to terms
        for i, t in enumerate(terms_to_validate):
            response = results[i] if i < len(results) else "error"
            is_valid = "yes" in response
            
            t['validation'] = {
                'model': self.config.biomistral_model,
                'is_valid': is_valid,
                'raw_response': response
            }
            if response == "error":
                 t['validation']['error'] = "Batch inference failed"
                
        return terms


class Mapper:
    """Maps terms to ontologies using APIs"""
    
    def __init__(self, config: PipelineConfig):
        self.config = config
        
    def map_terms(self, terms: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Map terms to BioPortal/UMLS"""
        if not self.config.bioportal_api_key:
            logger.warning("No BioPortal API key. Skipping mapping.")
            return terms
            
        logger.info("Mapping terms (mock/limited for standalone demo)...")
        # In a full standalone script, we'd implement the requests logic here.
        # For this implementation, we'll do a lightweight check or skip to avoid
        # hitting API limits during testing.
        
        # We'll just mark them as "mapped" if we have a key, to show logic flow
        for term in terms:
            term['mappings'] = {
                "bioportal": "skipped_in_standalone_demo"
            }
        return terms


# --- Global Pipeline Logic ---

class GlobalPipelineProcessor:
    """
    Correct Global Scientific Term Extraction Pipeline Processor
    
    FIXED WORKFLOW:
    1. Extract ALL terms from ALL models across ALL files
    2. Gather ALL terms into single collection
    3. Global deduplication (exact + fuzzy + semantic)
    4. Filter noise terms
    5. Final selection to 5-10k high-quality terms
    6. Then apply mapping, definitions, validation
    """

    def __init__(self, config: PipelineConfig):
        self.config = config

        # Create output directory
        self.output_path = Path(config.output_dir)
        self.output_path.mkdir(parents=True, exist_ok=True)

        # OPTIMIZED: Lazy loading + memory management
        logger.info("🚀 Setting up optimized pipeline with lazy model loading...")
        self.model_cache = {}
        self.files_processed = 0

        # Import for memory management
        try:
            import gc
            import psutil
            self.gc = gc
            self.psutil = psutil
        except ImportError:
            logger.warning("⚠️ Memory management modules not available")
            self.gc = None
            self.psutil = None

        # Initialize components once (no models loaded yet)
        self.deduplicator = None
        self.term_corrector = None
        self.mapper = None
        self.umls_mapper = None
        self.def_generator = None
        self.validator = None
        self.term_ranker = None

    def _cleanup_memory(self):
        """OPTIMIZED: Aggressive memory cleanup"""
        if self.gc:
            self.gc.collect()

        # Clear GPU cache if available
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except:
            pass

    def _check_memory_usage(self):
        """OPTIMIZED: Check memory and cleanup if needed"""
        if self.psutil:
            memory_gb = self.psutil.Process().memory_info().rss / 1024 / 1024 / 1024
            if memory_gb > self.config.max_memory_gb:
                logger.warning(f"⚠️ High memory usage: {memory_gb:.1f}GB - Running cleanup")
                self._cleanup_memory()

    def _load_model_lazy(self, model_name: str):
        """OPTIMIZED: Load model only when needed"""
        if model_name not in self.model_cache:
            logger.info(f"   Loading {model_name} (lazy)...")
            try:
                model_config = PipelineConfig(
                    input_dir=self.config.input_dir,
                    output_dir=self.config.output_dir,
                    spacy_model=model_name
                )
                extractor = TermsExtractor(model_config)
                self.model_cache[model_name] = extractor
                logger.info(f"   ✅ {model_name} loaded")
            except Exception as e:
                logger.error(f"   ❌ Failed to load {model_name}: {e}")
                self.model_cache[model_name] = None
        return self.model_cache.get(model_name)

    def _initialize_components(self):
        """OPTIMIZED: Initialize components only when needed"""
        if self.deduplicator is None:
            self.deduplicator = Deduplicator(self.config)
            self.term_corrector = LLMTermCorrector(self.config) if self.config.correct_terms else None
            self.mapper = ComprehensiveMapper(self.config) if (self.config.map_omop or self.config.map_bioportal) else None
            self.umls_mapper = UMLSMapper(self.config) if self.config.map_umls else None
            self.def_generator = DefinitionGenerator(self.config) if self.config.generate_definitions else None
            self.validator = BioMistralValidator(self.config) if self.config.validate_biomistral else None
            self.term_ranker = TermRanker(self.config, self.deduplicator.semantic_model)

    def extract_all_terms_from_all_files(self) -> List[Dict[str, Any]]:
        """STEP 1: Extract ALL terms from ALL models across ALL files"""
        logger.info("🔥 STEP 1: Extracting ALL terms from ALL models across ALL files...")

        input_path = Path(self.config.input_dir)
        files = list(input_path.glob("*.txt"))

        if self.config.max_files:
            files = files[:self.config.max_files]

        logger.info(f"Found {len(files)} files to process")
        logger.info(f"Using models: {self.config.models_to_use}")

        all_raw_terms = []

        # We can parallelize this if needed, but let's stick to the logic from correct_global_pipeline.py
        # which iterates files and models.
        
        for file_idx, file_path in enumerate(files, 1):
            logger.info(f"📄 Processing file {file_idx}/{len(files)}: {file_path.name}")

            try:
                text = file_path.read_text(encoding='utf-8')
                logger.info(f"   📖 File size: {len(text):,} characters")
            except Exception as e:
                logger.error(f"❌ Error reading {file_path}: {e}")
                continue

            # OPTIMIZED: Extract with lazy loading and memory management
            file_terms = []
            for model_name in self.config.models_to_use:
                logger.info(f"   🤖 Extracting with {model_name}...")
                try:
                    # OPTIMIZED: Lazy load model only when needed
                    extractor = self._load_model_lazy(model_name)
                    if extractor is None:
                        logger.warning(f"   ⚠️ Model {model_name} not available, skipping")
                        continue

                    terms = extractor.extract(text)

                    logger.info(f"      ✅ Found {len(terms)} terms")

                    # Tag terms with their source model and file for traceability
                    for t in terms:
                        t['source_model'] = model_name
                        t['source_file'] = file_path.name

                    file_terms.extend(terms)

                except Exception as e:
                    logger.error(f"      ❌ Failed to run {model_name}: {e}")

            logger.info(f"   📊 Total terms from {file_path.name}: {len(file_terms):,}")
            all_raw_terms.extend(file_terms)

            # OPTIMIZED: Memory cleanup and monitoring
            self.files_processed += 1
            if self.files_processed % self.config.memory_cleanup_interval == 0:
                logger.info(f"   🧹 Running memory cleanup (file {self.files_processed})")
                self._cleanup_memory()
                self._check_memory_usage()

            # OPTIMIZED: Smart raw terms limit for efficient processing
            if len(all_raw_terms) >= self.config.max_raw_terms_limit:
                logger.info(f"🎯 Smart limit reached! {len(all_raw_terms):,} raw terms - time for deduplication")
                break

        logger.info(f"🎯 STEP 1 COMPLETE: Total raw terms from ALL files: {len(all_raw_terms):,}")
        return all_raw_terms

    def filter_noise_terms(self, terms: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """STEP 4: Filter out noise terms"""
        logger.info("🧹 STEP 4: Filtering noise terms...")

        # Common noise patterns
        noise_patterns = [
            r'^[a-z]$',  # Single letters
            r'^[0-9]+$',  # Just numbers
            r'^[^a-zA-Z0-9]+$',  # Just special chars
            r'^\w+$',  # Single word only
            r'.{1,2}$',  # Very short terms
            r'(fig|figure|table|tab)\.? ?\d+$',  # Figure/table references
            r'^https?://',  # URLs
            r'^www\.',  # URLs
            r'@\w+',  # Emails/mentions
            r'^\d+%$',  # Percentages
            r'^\d+/\d+$',  # Fractions
            r'^[ivxlm]+\.$',  # Roman numerals with period
        ]

        # Common noise words
        noise_words = {
            'et', 'al', 'and', 'or', 'the', 'in', 'on', 'at', 'to', 'for', 'of', 'with',
            'by', 'from', 'as', 'is', 'are', 'was', 'were', 'be', 'been', 'have', 'has',
            'had', 'do', 'does', 'did', 'will', 'would', 'could', 'should', 'may', 'might',
            'can', 'must', 'shall', 'fig', 'figure', 'table', 'ref', 'reference',
            'see', 'also', 'note', 'notes', 'above', 'below', 'previous', 'following',
            'respectively', 'respectively,', 'respectively.', 'ie', 'eg', 'id', 'ids',
            'mm', 'cm', 'nm', 'μm', '°c', '°f', 'mg', 'g', 'kg', 'ml', 'l', 'ul'
        }

        original_count = len(terms)
        filtered_terms = []

        for term in terms:
            term_text = term.get('term', '').lower().strip()

            # Skip empty terms
            if not term_text or len(term_text) < 3:
                continue

            # Check noise patterns
            is_noise = False
            for pattern in noise_patterns:
                if re.match(pattern, term_text):
                    is_noise = True
                    break

            # Check noise words
            if term_text in noise_words:
                is_noise = True

            # Check if it's all lowercase (likely not a scientific term)
            if term_text.islower() and len(term_text.split()) == 1:
                is_noise = True

            if not is_noise:
                filtered_terms.append(term)

        filtered_count = len(filtered_terms)
        logger.info(f"   🗑️  Filtered {original_count - filtered_count:,} noise terms")
        logger.info(f"   ✅ Remaining terms: {filtered_count:,}")

        return filtered_terms

    def select_final_terms(self, terms: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """STEP 5: Select final terms to reach target count"""
        logger.info(f"🎯 STEP 5: Selecting final {self.config.target_final_terms:,} terms...")

        current_count = len(terms)
        target_count = self.config.target_final_terms

        if current_count <= target_count:
            logger.info(f"   ✅ Already have {current_count:,} terms (≤ target {target_count:,})")
            return terms

        # Advanced Ranking using TermRanker (Gold Standard + Semantic + Frequency)
        logger.info("   🌟 Applying Advanced Term Ranking...")
        ranked_terms = self.term_ranker.rank_terms(terms)
        
        # Select top N
        final_terms = ranked_terms[:target_count]

        logger.info(f"   ✅ Selected {len(final_terms):,} final terms")
        return final_terms

    def run_advanced_processing(self, terms: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Apply correction, mapping, definitions, validation"""
        logger.info("🔬 STEP 6: Advanced processing (correction, mapping, definitions, validation)...")

        # Correction
        if self.term_corrector:
            logger.info("   🔧 Running term correction...")
            terms = self.term_corrector.correct_terms(terms)
            logger.info(f"      ✅ Correction complete: {len(terms)} terms")
            self.save_terms_to_files(terms, "step6_corrected")

        # Mapping
        if self.mapper:
            logger.info("   🗺️  Running OMOP/BioPortal mapping...")
            terms = self.mapper.map_terms(terms)
            logger.info(f"      ✅ OMOP/BioPortal mapping complete")
            self.save_terms_to_files(terms, "step6_mapped_omop_bioportal")

        if self.umls_mapper:
            logger.info("   🏥 Running UMLS mapping...")
            terms = self.umls_mapper.map_terms(terms)
            logger.info(f"      ✅ UMLS mapping complete")
            self.save_terms_to_files(terms, "step6_mapped_umls")

        # Definitions
        if self.def_generator:
            logger.info("   📚 Generating definitions...")
            terms = self.def_generator.generate_definitions(terms)
            logger.info(f"      ✅ Definitions generated")
            self.save_terms_to_files(terms, "step6_definitions")

        # Validation
        if self.validator:
            logger.info("   ✅ Running validation...")
            terms = self.validator.validate_terms(terms)
            logger.info(f"      ✅ Validation complete")
            self.save_terms_to_files(terms, "step6_validated")

        return terms

    def save_terms_to_files(self, terms: List[Dict[str, Any]], step_name: str) -> None:
        """Save terms to both JSON and CSV files with step-specific naming"""
        logger.info(f"💾 Saving {len(terms)} terms for step: {step_name}")

        # Save JSON
        json_file = self.output_path / f"{step_name}_terms.json"
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(terms, f, indent=2, ensure_ascii=False)
        logger.info(f"   ✅ Saved JSON to {json_file}")

        # Save CSV
        try:
            import pandas as pd
            csv_data = []
            for term in terms:
                row = {
                    "term": term.get('term', ''),
                    "label": term.get('label', 'ENTITY'),
                    "score": term.get('score', 0.0),
                    "source_model": term.get('source_model', ''),
                    "source_file": term.get('source_file', ''),
                    "examples": " | ".join(term.get('examples', [])[:3])
                }
                # Add mappings if available
                if "mappings" in term:
                    for source, matches in term["mappings"].items():
                        if matches:
                            row[f"mapping_{source}_id"] = matches[0].get("id")
                            row[f"mapping_{source}_label"] = matches[0].get("label")
                # Add definition if available
                if "definition" in term:
                    row["definition"] = term["definition"]
                # Add validation if available
                if "validation" in term:
                    row["validation_valid"] = term["validation"].get("is_valid")
                    row["validation_response"] = term["validation"].get("raw_response")

                csv_data.append(row)

            df = pd.DataFrame(csv_data)
            csv_file = self.output_path / f"{step_name}_terms.csv"
            df.to_csv(csv_file, index=False, encoding='utf-8')
            logger.info(f"   ✅ Saved CSV to {csv_file}")

        except Exception as e:
            logger.warning(f"Failed to save CSV for {step_name}: {e}")

    def run_global_pipeline(self) -> Dict[str, Any]:
        """Run the complete correct global pipeline"""
        logger.info("🚀 Starting CORRECT GLOBAL Scientific Term Extraction Pipeline")

        start_time = time.time()

        # STEP 1: Extract ALL terms from ALL models across ALL files
        all_raw_terms = self.extract_all_terms_from_all_files()

        # Save raw terms after extraction
        self.save_terms_to_files(all_raw_terms, "step1_raw_extraction")

        # STEP 2: Gather ALL terms into single collection (already done in step 1)
        logger.info(f"📦 STEP 2: Gathered ALL {len(all_raw_terms):,} terms into single collection")

        # STEP 3: Global deduplication (exact + fuzzy + semantic)
        logger.info("🔄 STEP 3: Global deduplication (exact + fuzzy + semantic)...")

        # OPTIMIZED: Initialize deduplicator only when needed
        self._initialize_components()

        dedup_terms = self.deduplicator.deduplicate(all_raw_terms)
        logger.info(f"   ✅ Global deduplication: {len(all_raw_terms):,} → {len(dedup_terms):,} terms")

        # OPTIMIZED: Cleanup after deduplication (memory intensive)
        self._cleanup_memory()

        # Save deduplicated terms
        self.save_terms_to_files(dedup_terms, "step3_deduplicated")

        # STEP 4: Filter noise terms
        filtered_terms = self.filter_noise_terms(dedup_terms)

        # Save filtered terms
        self.save_terms_to_files(filtered_terms, "step4_filtered")

        # STEP 5: Final selection to target count
        final_terms = self.select_final_terms(filtered_terms)

        # Save final selection before advanced processing
        self.save_terms_to_files(final_terms, "step5_final_selection")

        # STEP 6: Advanced processing (optional)
        if any([self.term_corrector, self.mapper, self.umls_mapper, self.def_generator, self.validator]):
            final_terms = self.run_advanced_processing(final_terms)

        # Calculate stats
        end_time = time.time()
        processing_time = end_time - start_time

        result = {
            "pipeline_metadata": {
                "pipeline_type": "correct_global",
                "processing_time_seconds": processing_time,
                "processing_time_hours": processing_time / 3600,
                "timestamp": datetime.now().isoformat(),
                "models_used": self.config.models_to_use,
                "input_files_processed": len(list(Path(self.config.input_dir).glob("*.txt"))),
                "target_final_terms": self.config.target_final_terms
            },
            "workflow_steps": {
                "step1_raw_extraction": len(all_raw_terms),
                "step2_collection": len(all_raw_terms),
                "step3_deduplication": len(dedup_terms),
                "step4_noise_filtering": len(filtered_terms),
                "step5_final_selection": len(final_terms),
                "step6_advanced_processing": len(final_terms)
            },
            "terms": final_terms
        }

        # Save final results with our helper method
        self.save_terms_to_files(final_terms, "step7_final_results")

        # Save results in the original format for compatibility
        output_file = self.output_path / "correct_global_results.json"
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2, ensure_ascii=False)

        # Save CSV
        try:
            import pandas as pd
            csv_data = []
            for term in final_terms:
                row = {
                    "term": term.get('term', ''),
                    "label": term.get('label', 'ENTITY'),
                    "score": term.get('score', 0.0),
                    "source_model": term.get('source_model', ''),
                    "source_file": term.get('source_file', ''),
                    "examples": " | ".join(term.get('examples', [])[:3])
                }
                # Add mappings if available
                if "mappings" in term:
                    for source, matches in term["mappings"].items():
                        if matches:
                            row[f"mapping_{source}_id"] = matches[0].get("id")
                            row[f"mapping_{source}_label"] = matches[0].get("label")
                # Add definition if available
                if "definition" in term:
                    row["definition"] = term["definition"]
                # Add validation if available
                if "validation" in term:
                    row["validation_valid"] = term["validation"].get("is_valid")
                    row["validation_response"] = term["validation"].get("raw_response")

                csv_data.append(row)

            df = pd.DataFrame(csv_data)
            csv_file = self.output_path / "correct_global_results.csv"
            df.to_csv(csv_file, index=False, encoding='utf-8')
            logger.info(f"💾 Saved CSV results to {csv_file}")

        except Exception as e:
            logger.warning(f"Failed to save CSV: {e}")

        # Final summary
        logger.info("🎉 CORRECT GLOBAL PIPELINE COMPLETE!")
        logger.info(f"⏱️  Total processing time: {processing_time/60:.1f} minutes")
        logger.info(f"📊 Final results: {len(final_terms):,} high-quality terms")
        logger.info(f"💾 Results saved to: {output_file}")

        return result

# --- Main Execution ---

def process_file(file_path: Path, extractor: TermsExtractor, deduplicator: Deduplicator, mapper: ComprehensiveMapper) -> Dict[str, Any]:
    """Process a single file"""
    logger.info(f"Processing {file_path.name}...")
    
    try:
        text = file_path.read_text(encoding='utf-8')
    except Exception as e:
        logger.error(f"Error reading {file_path}: {e}")
        return None
        
    # 1. Extraction
    raw_terms = extractor.extract(text)
    logger.info(f"  Extracted {len(raw_terms)} raw terms")
    
    # 2. Deduplication
    dedup_terms = deduplicator.deduplicate(raw_terms)
    logger.info(f"  Deduplicated to {len(dedup_terms)} terms")
    
    # 3. Mapping
    mapped_terms = mapper.map_terms(dedup_terms)
    logger.info(f"  Mapped {len(mapped_terms)} terms")

    # 4. Ranking
    final_terms = extractor.rank_terms(mapped_terms)
    logger.info(f"  Ranked {len(final_terms)} terms")
    
    return {
        "file": file_path.name,
        "timestamp": datetime.now().isoformat(),
        "stats": {
            "raw_count": len(raw_terms),
            "final_count": len(final_terms)
        },
        "terms": final_terms
    }

# --- Global Worker State ---
_worker_extractor = None

def init_worker(config: PipelineConfig):
    """Initialize worker process with its own extractor"""
    global _worker_extractor
    try:
        _worker_extractor = TermsExtractor(config)
        logger.info(f"Worker initialized with model {config.spacy_model}")
    except Exception as e:
        logger.error(f"Worker initialization failed: {e}")

def process_file_worker(file_path: Path) -> Tuple[Path, List[Dict[str, Any]]]:
    """Worker function to extract terms from a file"""
    global _worker_extractor
    if _worker_extractor is None:
        return file_path, []
    
    try:
        text = file_path.read_text(encoding='utf-8')
        terms = _worker_extractor.extract(text)
        return file_path, terms
    except Exception as e:
        logger.error(f"Worker failed on {file_path}: {e}")
        return file_path, []

# --- Checkpointing ---

def load_checkpoint(checkpoint_path: Path) -> Set[str]:
    """Load set of processed filenames from checkpoint"""
    if not checkpoint_path.exists():
        return set()
    try:
        with open(checkpoint_path, 'r') as f:
            data = json.load(f)
            return set(data.get("processed_files", []))
    except Exception as e:
        logger.warning(f"Failed to load checkpoint: {e}")
        return set()

def update_checkpoint(checkpoint_path: Path, filename: str):
    """Append a filename to the checkpoint"""
    try:
        current = load_checkpoint(checkpoint_path)
        current.add(filename)
        
        # Atomic write
        temp_path = checkpoint_path.with_suffix(".tmp")
        with open(temp_path, 'w') as f:
            json.dump({"processed_files": list(current), "last_updated": datetime.now().isoformat()}, f)
        temp_path.replace(checkpoint_path)
    except Exception as e:
        logger.warning(f"Failed to update checkpoint: {e}")

SCISPACY_MODELS = [
    "en_core_sci_sm",
    "en_core_sci_md",
    "en_core_sci_lg",
    "en_core_sci_scibert",
    "en_ner_craft_md",
    "en_ner_jnlpba_md",
    "en_ner_bc5cdr_md",
    "en_ner_bionlp13cg_md"
]

SPACY_MODELS = [
    "en_core_web_sm",
    "en_core_web_md",
    "en_core_web_lg",
    "en_core_web_trf"
]

def run_pipeline(config: PipelineConfig, skip_mapping: bool = False):
    """Run the pipeline with the given configuration"""
    # Ensure directories exist
    input_path = Path(config.input_dir)
    output_path = Path(config.output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    checkpoint_path = output_path / config.checkpoint_file
    
    if not input_path.exists():
        logger.error(f"Input directory {input_path} does not exist!")
        return
        
    # Load Checkpoint
    processed_files = load_checkpoint(checkpoint_path)
    logger.info(f"Loaded checkpoint: {len(processed_files)} files already processed.")

    # Identify files to process
    all_files = list(input_path.glob("*.txt"))
    files_to_process = [f for f in all_files if f.name not in processed_files]
    
    if config.max_files:
        files_to_process = files_to_process[:config.max_files]
        
    logger.info(f"Found {len(all_files)} files. Processing {len(files_to_process)} new files.")
    
    if not files_to_process:
        logger.info("No new files to process. Exiting.")
        return

    # Initialize Central Components
    logger.info("Initializing central components...")
    try:
        deduplicator = Deduplicator(config)
        mapper = ComprehensiveMapper(config) if not skip_mapping else None
        validator = BioMistralValidator(config) if config.validate_biomistral else None
        
        # Initialize Ranker with the semantic model from deduplicator
        ranker = TermRanker(config, deduplicator.semantic_model)
        
    except Exception as e:
        logger.error(f"Failed to initialize central components: {e}")
        return

    # Process Loop
    # Phase 1: Parallel Extraction (CPU Bound)
    # Phase 2: Sequential/Batched Processing (GPU/Memory Bound)
    
    batch_size_files = 5 # OPTIMIZED: Smaller chunks for better memory management
    
    total_processed = 0
    
    # We will use a ProcessPoolExecutor for extraction
    # We process in chunks of files to avoid loading ALL terms into memory at once
    
    for i in range(0, len(files_to_process), batch_size_files):
        chunk_files = files_to_process[i : i + batch_size_files]
        logger.info(f"--- Processing Batch {i//batch_size_files + 1} ({len(chunk_files)} files) ---")
        
        # 1. Parallel Extraction
        chunk_results = []
        if config.workers > 1:
            logger.info(f"Starting parallel extraction with {config.workers} workers...")
            with concurrent.futures.ProcessPoolExecutor(
                max_workers=config.workers, 
                initializer=init_worker, 
                initargs=(config,)
            ) as executor:
                results = list(executor.map(process_file_worker, chunk_files))
                chunk_results = results
        else:
            # Sequential fallback
            logger.info("Running sequential extraction...")
            # We need a local extractor if not using workers
            local_extractor = TermsExtractor(config)
            for f in chunk_files:
                try:
                    text = f.read_text(encoding='utf-8')
                    chunk_results.append((f, local_extractor.extract(text)))
                except Exception as e:
                    logger.error(f"Error reading {f}: {e}")
            del local_extractor

        # 2. Post-Processing (Deduplication, Mapping, Validation)
        for file_path, raw_terms in chunk_results:
            if not raw_terms:
                logger.warning(f"No terms extracted for {file_path.name}")
                continue
                
            logger.info(f"Post-processing {file_path.name} ({len(raw_terms)} raw terms)...")
            
            # Deduplication
            dedup_terms = deduplicator.deduplicate(raw_terms)
            
            final_terms = dedup_terms
            
            # Mapping & Ranking
            if not skip_mapping and mapper:
                mapped_terms = mapper.map_terms(dedup_terms)
                final_terms = ranker.rank_terms(mapped_terms)
            else:
                final_terms = ranker.rank_terms(final_terms) 

            # Validation (Batched per file, or we could batch across files but that's complex for tracking)
            if validator:
                final_terms = validator.validate_terms(final_terms)

            # Save Result
            result = {
                "file": file_path.name,
                "model": config.spacy_model,
                "timestamp": datetime.now().isoformat(),
                "stats": {
                    "raw_count": len(raw_terms),
                    "final_count": len(final_terms)
                },
                "terms": final_terms
            }
            
            out_file = output_path / f"{file_path.stem}_{config.spacy_model}_results.json"
            with open(out_file, 'w') as f:
                json.dump(result, f, indent=2)
                
            # Update Checkpoint
            update_checkpoint(checkpoint_path, file_path.name)
            logger.info(f"Completed {file_path.name}")
            
        # Explicit GC
        import gc
        gc.collect()


    # After processing all files, create consolidated results
    logger.info("All files processed. Creating consolidated results...")
    try:
        create_final_consolidated_results(output_path, config)
    except Exception as e:
        logger.error(f"Failed to create final consolidated results: {e}")

# Removed rank_terms_static as it is replaced by TermRanker

def create_final_consolidated_results(output_path: Path, config: PipelineConfig):
    """Create final consolidated results from all processed files with top 5K-10K terms"""
    import pandas as pd

    logger.info("Creating final consolidated results from all processed files...")

    # Find all result files
    result_files = list(output_path.glob(f"*_{config.spacy_model}_results.json"))

    if not result_files:
        logger.warning("No result files found for consolidation")
        return

    logger.info(f"Found {len(result_files)} result files to consolidate")

    all_terms = []
    consolidation_metadata = {
        "pipeline_config": {
            "model": config.spacy_model,
            "fuzzy_threshold": config.fuzzy_threshold,
            "semantic_threshold": config.semantic_threshold,
        },
        "consolidation_timestamp": datetime.now().isoformat(),
        "total_files_processed": len(result_files),
        "files_consolidated": []
    }

    # Process each result file
    for result_file in result_files:
        logger.info(f"Processing {result_file.name}")
        try:
            with open(result_file, 'r') as f:
                data = json.load(f)

            # Add file metadata
            consolidation_metadata["files_consolidated"].append({
                "filename": data.get("file"),
                "timestamp": data.get("timestamp"),
                "raw_count": data.get("stats", {}).get("raw_count", 0),
                "final_count": data.get("stats", {}).get("final_count", 0)
            })

            # Add terms with file source
            for term in data.get("terms", []):
                term["source_file"] = data.get("file")
                term["source_model"] = config.spacy_model
                all_terms.append(term)

        except Exception as e:
            logger.error(f"Error processing {result_file}: {e}")
            continue

    logger.info(f"Collected {len(all_terms)} total terms from all files")

    # Global deduplication across all files
    unique_terms = {}

    for term in all_terms:
        term_key = term["term"].lower().strip()
        if term_key not in unique_terms:
            unique_terms[term_key] = term.copy()
        else:
            # Merge information from duplicates
            existing = unique_terms[term_key]

            # Combine source files
            if "source_file" not in existing:
                existing["source_file"] = []
            elif isinstance(existing["source_file"], str):
                existing["source_file"] = [existing["source_file"]]

            if term["source_file"] not in existing["source_file"]:
                existing["source_file"].append(term["source_file"])

            # Update frequency
            existing["frequency"] = existing.get("frequency", 1) + term.get("frequency", 1)

            # Keep highest score
            if term.get("score", 0) > existing.get("score", 0):
                existing["score"] = term["score"]

            # Merge other fields if needed
            if term.get("examples") and existing.get("examples"):
                existing["examples"] = list(set(existing["examples"] + term["examples"]))

    consolidated_terms = list(unique_terms.values())

    # Sort by score descending and limit to top 5K-10K
    consolidated_terms.sort(key=lambda x: (x.get("score", 0), x.get("frequency", 0)), reverse=True)

    MAX_TERMS = 10000  # Configurable limit for top terms
    MIN_TERMS = 5000   # Minimum terms to keep
    target_terms = min(max(len(consolidated_terms), MIN_TERMS), MAX_TERMS)
    top_terms = consolidated_terms[:target_terms]

    # Create final consolidated data structure
    final_consolidated_data = {
        "metadata": {
            **consolidation_metadata,
            "total_raw_terms": len(all_terms),
            "total_unique_terms": len(consolidated_terms),
            "final_top_terms": len(top_terms),
            "deduplication_stats": {
                "removed_duplicates": len(all_terms) - len(consolidated_terms),
                "duplicate_ratio": (len(all_terms) - len(consolidated_terms)) / len(all_terms) if all_terms else 0
            }
        },
        "terms": top_terms
    }

    # Save consolidated JSON
    json_output = output_path / f"final_consolidated_{config.spacy_model}_results.json"
    with open(json_output, 'w') as f:
        json.dump(final_consolidated_data, f, indent=2)

    logger.info(f"Saved final consolidated JSON with {len(top_terms)} top terms to {json_output}")

    # Create CSV with top terms
    csv_output = output_path / f"final_consolidated_{config.spacy_model}_results.csv"
    try:
        flat_terms = []
        for term in top_terms:
            # Calculate file frequency
            file_count = 1
            if isinstance(term.get("source_file"), list):
                file_count = len(term["source_file"])

            row = {
                "term": term["term"],
                "canonical_term": term.get("canonical_form", term["term"]),
                "primary_form": term.get("primary_form", term["term"]),
                "label": term.get("label", "ENTITY"),
                "category": term.get("category", ""),
                "score": term.get("score", 0.0),
                "frequency": term.get("frequency", 1),
                "file_count": file_count,
                "semantic_score": term.get("semantic_score", 0.0),
                "source_files": ";".join(term.get("source_file", [])) if isinstance(term.get("source_file"), list) else term.get("source_file", ""),
                "examples": " | ".join(term.get("examples", [])[:3])
            }

            # Add mappings if available
            if "mappings" in term:
                for source, matches in term["mappings"].items():
                    if matches and isinstance(matches, list) and len(matches) > 0:
                        row[f"mapping_{source}_id"] = matches[0].get("id", "")
                        row[f"mapping_{source}_label"] = matches[0].get("label", "")
                        row[f"mapping_{source}_score"] = matches[0].get("score", 0)

            # Add validation if available
            if "validation" in term:
                validation = term["validation"]
                row["validation_valid"] = validation.get("is_valid")
                row["validation_response"] = validation.get("raw_response")

            flat_terms.append(row)

        df = pd.DataFrame(flat_terms)
        df.to_csv(csv_output, index=False)
        logger.info(f"Saved final consolidated CSV with {len(flat_terms)} rows to {csv_output}")

    except Exception as e:
        logger.error(f"Failed to create CSV: {e}")

    # Save summary statistics
    stats_output = output_path / f"final_consolidation_{config.spacy_model}_stats.json"
    stats = {
        "consolidation_summary": final_consolidated_data["metadata"],
        "output_files": {
            "consolidated_json": str(json_output),
            "consolidated_csv": str(csv_output),
            "per_paper_files": [str(f) for f in result_files]
        }
    }
    with open(stats_output, 'w') as f:
        json.dump(stats, f, indent=2)

    logger.info(f"Final consolidation completed. Processed {len(result_files)} files, generated {len(top_terms)} top terms")

def consolidate_results(input_dir: str, output_dir: str):
    """Consolidate all ensemble results into a single comprehensive output"""
    import pandas as pd
    from pathlib import Path

    logger.info(f"Consolidating results from {input_dir} to {output_dir}")

    input_path = Path(input_dir)
    output_path = Path(output_dir)

    # Ensure output directory exists
    output_path.mkdir(parents=True, exist_ok=True)

    # Find all ensemble result files
    ensemble_files = list(input_path.glob("*_ensemble_results.json"))

    if not ensemble_files:
        logger.warning("No ensemble result files found to consolidate")
        return

    logger.info(f"Found {len(ensemble_files)} ensemble files")

    all_terms = []
    consolidated_data = {
        "metadata": {
            "consolidation_timestamp": datetime.now().isoformat(),
            "total_files": len(ensemble_files),
            "files_processed": []
        },
        "terms": []
    }

    # Process each ensemble file
    for file_path in ensemble_files:
        logger.info(f"Processing {file_path.name}")
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)

            # Add file metadata
            consolidated_data["metadata"]["files_processed"].append({
                "filename": file_path.name,
                "timestamp": data.get("timestamp"),
                "models_used": data.get("models_used", []),
                "raw_count": data.get("stats", {}).get("raw_count", 0),
                "final_count": data.get("stats", {}).get("final_count", 0)
            })

            # Add terms with file source
            for term in data.get("terms", []):
                term["source_file"] = file_path.name
                all_terms.append(term)

        except Exception as e:
            logger.error(f"Error processing {file_path}: {e}")
            continue

    # Global deduplication across all files
    logger.info(f"Performing global deduplication on {len(all_terms)} terms")
    unique_terms = {}

    for term in all_terms:
        term_key = term["term"].lower().strip()
        if term_key not in unique_terms:
            unique_terms[term_key] = term
        else:
            # Merge metadata if duplicate
            existing = unique_terms[term_key]
            if "source_file" not in existing:
                existing["source_file"] = []
            elif isinstance(existing["source_file"], str):
                existing["source_file"] = [existing["source_file"]]

            if isinstance(term["source_file"], str):
                if term["source_file"] not in existing["source_file"]:
                    existing["source_file"].append(term["source_file"])
            elif isinstance(term["source_file"], list):
                for sf in term["source_file"]:
                    if sf not in existing["source_file"]:
                        existing["source_file"].append(sf)

            # Keep highest score
            if term.get("score", 0) > existing.get("score", 0):
                existing["score"] = term["score"]

    consolidated_terms = list(unique_terms.values())

    # Sort by score descending
    consolidated_terms.sort(key=lambda x: x.get("score", 0), reverse=True)
    
    # Limit to top 5K-10K terms as requested
    MAX_CONSOLIDATED_TERMS = 10000  # Configurable limit
    consolidated_terms = consolidated_terms[:MAX_CONSOLIDATED_TERMS]

    consolidated_data["terms"] = consolidated_terms
    consolidated_data["metadata"]["total_unique_terms"] = len(consolidated_terms)
    consolidated_data["metadata"]["total_raw_terms"] = len(all_terms)

    # Save consolidated JSON
    json_output = output_path / "consolidated_ensemble_results.json"
    with open(json_output, 'w') as f:
        json.dump(consolidated_data, f, indent=2)

    logger.info(f"Saved consolidated JSON with {len(consolidated_terms)} unique terms")

    # Create flattened DataFrame for CSV export
    flat_terms = []
    for term in consolidated_terms:
        # Calculate file count and frequency
        file_count = len(term.get("source_file", [])) if isinstance(term.get("source_file"), list) else 1
        
        row = {
            "canonical_term": term["term"],
            "primary_form": term.get("original", term["term"]),
            "entity_label": term.get("label", "ENTITY"),
            "gold_category": term.get("gold_category", ""),
            "frequency": term.get("frequency", 1),
            "file_count": file_count,
            "relevance_score": term.get("score", 0.0),
            "semantic_score": term.get("semantic_score", 0.0),
            "is_gold_standard": term.get("is_gold_standard", False),
            "model_sources": term.get("source", "ensemble"),
            "examples": " | ".join(term.get("examples", [])[:3]),
            "source_filenames": ";".join(term.get("source_file", [])) if isinstance(term.get("source_file"), list) else term.get("source_file", "")
        }

        # Add validation info if available
        if "validation" in term:
            validation = term["validation"]
            row["validation_valid"] = validation.get("is_valid")
            row["validation_response"] = validation.get("raw_response")
            row["validation_model"] = validation.get("model")

        # Add mappings if available
        if "mappings" in term:
            for source, matches in term["mappings"].items():
                if matches and isinstance(matches, list) and len(matches) > 0:
                    row[f"mapping_{source}_id"] = matches[0].get("id", "")
                    row[f"mapping_{source}_label"] = matches[0].get("label", "")
                    row[f"mapping_{source}_score"] = matches[0].get("score", 0)

        flat_terms.append(row)

    # Save consolidated CSV
    csv_output = output_path / "consolidated_ensemble_results.csv"
    if flat_terms:
        df = pd.DataFrame(flat_terms)
        df.to_csv(csv_output, index=False)
        logger.info(f"Saved consolidated CSV with {len(flat_terms)} rows")
    else:
        logger.warning("No terms to save to CSV")

    # Generate summary statistics
    stats = {
        "total_ensemble_files": len(ensemble_files),
        "total_raw_terms": len(all_terms),
        "total_unique_terms": len(consolidated_terms),
        "consolidation_timestamp": datetime.now().isoformat(),
        "output_files": {
            "json": str(json_output),
            "csv": str(csv_output)
        }
    }

    # Save summary stats
    stats_output = output_path / "consolidation_stats.json"
    with open(stats_output, 'w') as f:
        json.dump(stats, f, indent=2)

    logger.info(f"Consolidation complete. Processed {len(all_terms)} raw terms into {len(consolidated_terms)} unique terms")
    logger.info(f"Results saved to {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Standalone SciSpaCy Pipeline")

    parser.add_argument("--input_dir", default="./data", help="Input directory")
    parser.add_argument("--output_dir", default="./output", help="Output directory")
    parser.add_argument("--model", default="en_core_sci_lg", help="Spacy model name")
    parser.add_argument("--skip_mapping", action="store_true", help="Skip mapping and ranking phases")
    parser.add_argument("--run_all_models", action="store_true", help="Run pipeline with ALL available scispacy models")
    parser.add_argument("--ensemble", action="store_true", help="Run ALL models and combine/deduplicate results into one file")

    # Validation arguments
    parser.add_argument("--validate_biomistral", action="store_true", help="Enable BioMistral-7B validation")
    parser.add_argument("--biomistral_model", default="BioMistral/BioMistral-7B", help="BioMistral model name")
    parser.add_argument("--load_4bit", action="store_true", help="Load BioMistral in 4-bit quantization")

    # Ollama arguments
    parser.add_argument("--use_ollama", action="store_true", help="Use Ollama instead of HuggingFace models")
    parser.add_argument("--ollama_base_url", default="http://localhost:11434", help="Ollama base URL")
    parser.add_argument("--ollama_model", default="mistral:latest", help="Ollama model to use (e.g., mistral:latest, llama2:7b)")

    # Advanced Features
    parser.add_argument("--generate_definitions", action="store_true", help="Generate definitions using LLM")
    parser.add_argument("--correct_terms", action="store_true", help="Correct terms using LLM")
    parser.add_argument("--map_umls", action="store_true", help="Map terms to UMLS")
    parser.add_argument("--map_omop", action="store_true", help="Map terms to OMOP")
    parser.add_argument("--map_bioportal", action="store_true", help="Map terms to BioPortal/OLS")
    parser.add_argument("--definition_model", default="BioMistral/BioMistral-7B", help="Model for definitions/correction (e.g. BioMistral, BioBERT)")
    parser.add_argument("--bioportal_api_key", default=os.getenv("BIOPORTAL_API_KEY"), help="BioPortal API Key")

    # ⭐ NEW arguments you requested ⭐
    parser.add_argument("--max_files", type=int, default=None, help="Maximum number of files to process")
    parser.add_argument("--target_terms", type=int, default=10000, help="Target final number of terms")
    parser.add_argument("--fuzzy_threshold", type=float, default=0.85, help="Fuzzy matching threshold")
    parser.add_argument("--semantic_threshold", type=float, default=0.90, help="Semantic similarity threshold")
    parser.add_argument("--workers", type=int, default=1, help="Number of parallel workers for extraction")
    parser.add_argument("--batch_size", type=int, default=32, help="Batch size for GPU inference")

    args = parser.parse_args()


    # Select models
    # Start with optimized models from config
    models_to_use = ["en_core_sci_md", "en_ner_bc5cdr_md", "en_core_sci_lg"]  # Optimized 3 models

    if args.model and not args.run_all_models and not args.ensemble:
        # If specific model requested, just use that one
        models_to_use = [args.model]

    # OPTIMIZED: --ensemble now uses optimized 3 models instead of all 8
    # Only use ALL 8 models if specifically requested with --run_all_models
    if args.run_all_models:
        models_to_use = SCISPACY_MODELS
    # --ensemble will use the optimized 3 models by default

    logger.info(f"🚀 Starting Standalone Pipeline with Global Workflow")
    logger.info(f"Models: {models_to_use}")

    # Create config
    config = PipelineConfig(
        input_dir=args.input_dir,
        output_dir=args.output_dir,
        models_to_use=models_to_use,
        max_files=args.max_files,
        target_final_terms=args.target_terms,
        fuzzy_threshold=args.fuzzy_threshold,
        semantic_threshold=args.semantic_threshold,
        workers=args.workers,
        batch_size=args.batch_size,
        generate_definitions=args.generate_definitions,
        correct_terms=args.correct_terms,
        map_omop=args.map_omop,
        map_umls=args.map_umls,
        map_bioportal=args.map_bioportal,
        validate_biomistral=args.validate_biomistral,
        definition_model=args.definition_model,
        correction_model=args.definition_model,
        bioportal_api_key=args.bioportal_api_key,
        load_4bit=args.load_4bit,
        spacy_model=models_to_use[0], # Default for base components

        # Ollama configuration
        use_ollama=args.use_ollama,
        ollama_base_url=args.ollama_base_url,
        ollama_model=args.ollama_model,
        biomistral_model=args.biomistral_model
    )
    # Run Global Pipeline
    processor = GlobalPipelineProcessor(config)
    processor.run_global_pipeline()

    logger.info("✅ Pipeline execution completed!")

if __name__ == "__main__":
    main()


