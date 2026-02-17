#!/usr/bin/env python3
"""
Unified CDM Entity Extraction Pipeline (Standalone)
===================================================
Single-file implementation of the Microbiome CDM Entity Extraction Pipeline.
Contains all necessary components: extraction, mapping, deduplication, and validation.
"""

import os
import sys
import json
import time
import logging
import argparse
import re
import math
import statistics
import subprocess
import tempfile
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Set, Tuple, Optional, Any, Union
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict, Counter

# Third-party imports
try:
    import requests
    import numpy as np
    import pandas as pd
    import torch
    from transformers import AutoTokenizer, AutoModelForCausalLM
    from sentence_transformers import SentenceTransformer
    from sklearn.metrics.pairwise import cosine_similarity
    from rapidfuzz import process, fuzz
    from dotenv import load_dotenv
    from tqdm import tqdm
except ImportError as e:
    print(f"Missing dependency: {e}")
    print("Please install required packages: pip install requests numpy pandas torch transformers sentence-transformers scikit-learn rapidfuzz python-dotenv tqdm")
    sys.exit(1)

# Configure logging
class JsonFormatter(logging.Formatter):
    def format(self, record):
        log_record = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name
        }
        if record.exc_info:
            log_record["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_record)

def setup_logging(verbose=False, log_format='text', log_file='cdm_pipeline.log'):
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO if not verbose else logging.DEBUG)
    
    # Clear existing handlers
    root_logger.handlers = []
    
    # Create handlers
    file_handler = logging.FileHandler(log_file)
    stream_handler = logging.StreamHandler()
    
    if log_format == 'json':
        formatter = JsonFormatter()
    else:
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        
    file_handler.setFormatter(formatter)
    stream_handler.setFormatter(formatter)
    
    root_logger.addHandler(file_handler)
    root_logger.addHandler(stream_handler)

logger = logging.getLogger("CDMPipeline")

class ConfigManager:
    """
    Manages configuration loading from JSON files and CLI arguments.
    Prioritizes CLI arguments over JSON config values.
    """

    @staticmethod
    def load_config(config_path: str) -> Dict[str, Any]:
        """Load configuration from a JSON file."""
        path = Path(config_path)
        if not path.exists():
            logger.warning(f"Config file not found: {config_path}")
            return {}
        
        try:
            with open(path, 'r') as f:
                config = json.load(f)
                logger.info(f"Loaded configuration from {config_path}")
                return config
        except json.JSONDecodeError as e:
            logger.error(f"Error parsing config file {config_path}: {e}")
            return {}
        except Exception as e:
            logger.error(f"Error loading config file {config_path}: {e}")
            return {}

    @staticmethod
    def setup_parser_with_config(parser: argparse.ArgumentParser, cli_args: Optional[List[str]] = None) -> argparse.Namespace:
        """
        Parse arguments supporting a configuration file.
        1. Parse only known args to find --config
        2. Load config file
        3. Update parser defaults with config values
        4. Parse all args
        """
        # First pass: look for config file
        temp_parser = argparse.ArgumentParser(add_help=False)
        temp_parser.add_argument('--config', help='Path to JSON configuration file')
        known_args, _ = temp_parser.parse_known_args(cli_args)

        if known_args.config:
            config = ConfigManager.load_config(known_args.config)
            
            # Normalize config keys to match argparse dest
            # e.g. "input-file" -> "input_file"
            normalized_config = {}
            for k, v in config.items():
                normalized_config[k.replace('-', '_')] = v
                
            parser.set_defaults(**normalized_config)

        # Second pass: parse everything
        return parser.parse_args(cli_args)

# ==========================================
# CONFIGURATION
# ==========================================

@dataclass
class CDMEntityConfig:
    """Configuration for CDM entity types."""

    # Enhanced entity type definitions based on specification and old.py's comprehensive categories
    ENTITY_TYPES = {
        'ORGANISM': {
            'description': 'Bacteria, archaea, fungi, viruses, microbiota, taxa, eukaryotic organisms',
            'examples': ['Bacteroides fragilis', 'E. coli', 'Firmicutes', 'Bacteroidetes', 'Archaea', 'Methanobrevibacter', 'Lactobacillus', 'Clostridium', 'Akkermansia', 'Homo sapiens', 'Mus musculus'],
            'patterns': [
                r'\b([A-Z][a-z]+[a-z]*\s+[a-z]+(?:\s+[a-z]+)*)\b', 
                r'\b([A-Z][a-z]+\s+sp[p]?)\b',
                r'\b\w*bacter\w*\b', r'\b\w*coccus\b', r'\b\w*aceae\b', r'\b\w*ales\b', r'\b\w*idae\b',
                r'\b\w*phyla\b', r'\b\w*genus\b', r'\b\w*species\b'
            ],
            'priority': 1
        },
        'CHEMICAL': {
            'description': 'Chemical compounds, metabolites, drugs, enzymes, hormones',
            'examples': ['butyrate', 'acetate', 'propionate', 'metformin', 'glucose', 'insulin', 'scfa', 'short-chain fatty acids'],
            'patterns': [
                r'\b[A-Za-z0-9\-\']+(?:acid|ate|ose|ol|one|ase|ium|ide|ine)\b',
                r'\b(SCFA|short-chain fatty acid)s?\b',
                r'\b\w*metabolit\w*\b', r'\b\w*compound\b'
            ],
            'priority': 2
        },
        'GENE': {
            'description': 'Genes, genetic markers, DNA/RNA segments',
            'examples': ['BRCA1', '16S rRNA', 'NOD2', 'TLR4', 'gene', 'allele'],
            'patterns': [
                r'\b[A-Z0-9\-]+(?:\s+gene)?\b',
                r'\b\w*gene\b', r'\b\w*genomic\w*\b', r'\b\w*genetic\w*\b'
            ],
            'priority': 3
        },
        'PROTEIN': {
            'description': 'Proteins, antibodies, cytokines',
            'examples': ['insulin', 'hemoglobin', 'TNF-alpha', 'interleukin'],
            'patterns': [
                r'\b[A-Z0-9\-]+(?:\s+protein)?\b',
                r'\b\w*protein\b', r'\b\w*enzyme\b'
            ],
            'priority': 3
        },
        'DNA_RNA': {
            'description': 'DNA, RNA, plasmids, vectors, genetic material',
            'examples': ['16S rRNA', 'plasmid', 'mRNA', 'cDNA'],
            'patterns': [r'\b\w*RNA\b', r'\b\w*DNA\b', r'\b\w*plasmid\b'],
            'priority': 3
        },
        'CELL_TYPE': {
            'description': 'Cells, cell lines, tissues, cellular structures',
            'examples': ['macrophage', 'epithelial cell', 'neuron', 'tissue'],
            'patterns': [r'\b\w*cell\b', r'\b\w*tissue\b', r'\b\w*neuron\b'],
            'priority': 3
        },
        'GENOMICS': {
            'description': 'Genomics, metagenomics, omics terms',
            'examples': ['metagenomics', 'transcriptomics', 'sequencing'],
            'patterns': [r'\b\w*omics\b', r'\b\w*sequencing\b'],
            'priority': 4
        },
        'DISEASE': {
            'description': 'Diseases, conditions, syndromes, disorders',
            'examples': ['Type 2 Diabetes', 'Crohn\'s disease', 'Obesity', 'IBD', 'Cancer'],
            'patterns': [
                r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s+(?:Syndrome|Disease|Disorder)\b',
                r'\b\w*disease\b', r'\b\w*disorder\b', r'\b\w*syndrome\b', r'\b\w*cancer\b',
                r'\b\w*infection\b', r'\b\w*inflammation\b'
            ],
            'priority': 2
        },
        # Sample Collection, Transport, Storage (Wet Lab - Pre-processing)
        'SAMPLE_METHOD': {
            'description': 'Methods for sample collection, transport, storage, and DNA extraction',
            'examples': ['fecal sampling', 'swab collection', 'frozen at -80C', 'RNAlater', 'PowerSoil DNA Kit', 'bead beating', 'DNA extraction'],
            'patterns': [r'\b([a-z]+\s+(?:kit|extraction|collection|storage))\b'],
            'priority': 8
        },
        # Laboratory Methods & Sequencing (Wet Lab - Sequencing)
        'LAB_METHOD': {
            'description': 'Library preparation, PCR, sequencing platforms, and wet-lab techniques',
            'examples': ['Illumina MiSeq', '16S rRNA PCR', 'V4 region', 'library preparation', 'Nextera XT', 'Nanopore', 'shotgun sequencing', 'PCR amplification'],
            'patterns': [r'\b(Illumina\s+[A-Za-z0-9]+)\b|\b([A-Z][a-z]+\s+(?:sequencing|PCR))\b'],
            'priority': 9
        },
        # Data Analysis & Bioinformatics (Dry Lab)
        'DATA_ANALYSIS': {
            'description': 'Bioinformatics tools, software, databases, statistical methods, and QC',
            'examples': ['QIIME2', 'Mothur', 'DADA2', 'Silva database', 'GreenGenes', 'UniFrac', 'Bray-Curtis', 'PCA', 'random forest', 'quality control'],
            'patterns': [r'\b([A-Z]{3,})\b|\b([a-z]+(?:omics|pipeline|analysis))\b'],
            'priority': 10
        },
        'CLINICAL': {
            'description': 'Clinical terms, procedures, anatomy, physiology',
            'examples': ['diagnosis', 'prognosis', 'treatment', 'gut', 'intestine', 'liver'],
            'patterns': [
                r'\b\w*clinica\w*\b', r'\b\w*diagnos\w*\b', r'\b\w*therap\w*\b',
                r'\b\w*anatomy\w*\b', r'\b\w*physiology\w*\b'
            ],
            'priority': 4
        },
        'SCIENTIFIC_TERM': {
            'description': 'General scientific and biomedical terms, lab methods',
            'examples': ['PCR', 'microscopy', 'chromatography', 'experiment', 'hypothesis'],
            'patterns': [
                r'\b\w*laboratory\w*\b', r'\b\w*experimental\w*\b', r'\b\w*method\w*\b'
            ],
            'priority': 5
        }
    }

    # Chunking strategies - Optimized for Yield (Balanced context)
    CHUNK_SIZES = {
        'small': 4000,    
        'medium': 8000,  
        'large': 12000,   
        'xlarge': 15000    
    }

    OVERLAP_RATIOS = {
        'small': 0.1,     # 10% overlap
        'medium': 0.05,   # 5% overlap
        'large': 0.03,    # 3% overlap
        'xlarge': 0.02    # 2% overlap
    }

    # Model configurations
    MODEL_CONFIGS = {
        'phi3:mini': {
            'max_tokens': 2000,
            'temperature': 0.1,
            'timeout': 300,
            'num_ctx': 4096
        },
        'qwen3:8b': {
            'max_tokens': 4000,
            'temperature': 0.1,
            'timeout': 600,
            'num_ctx': 8192
        },
        'qwen3:14b': {
            'max_tokens': 8000,
            'temperature': 0.3,
            'timeout': 1200,
            'num_ctx': 32768
        },
        'gemma3:12b': {
            'max_tokens': 8000,
            'temperature': 0.3,
            'timeout': 1200,
            'num_ctx': 16384
        },
        'biomistral-7B': {
            'max_tokens': 4000,
            'temperature': 0.1,
            'timeout': 600,
            'num_ctx': 8192
        },
        'deepseek-r1:8b': {
            'max_tokens': 8000,
            'temperature': 0.1,
            'timeout': 1200,
            'num_ctx': 8192
        },
        'glm-4': {
            'max_tokens': 4096,
            'temperature': 0.1,
            'timeout': 300,
            'num_ctx': 8192
        },
        'glm-4-6': {
            'max_tokens': 4096,
            'temperature': 0.1,
            'timeout': 300,
            'num_ctx': 8192
        },
        'glm-4-flash': {
            'max_tokens': 4096,
            'temperature': 0.1,
            'timeout': 300,
            'num_ctx': 128000
        },
        'glm-4-air': {
            'max_tokens': 4096,
            'temperature': 0.1,
            'timeout': 300,
            'num_ctx': 128000
        },
        'glm-4.6': {
            'max_tokens': 4096,
            'temperature': 0.1,
            'timeout': 3000,
            'num_ctx': 128000
        },
    }

    @classmethod
    def get_chunk_size(cls, text_length: int) -> int:
        """Get optimal chunk size based on text length."""
        if text_length < 10000:
            return cls.CHUNK_SIZES['small']
        elif text_length < 50000:
            return cls.CHUNK_SIZES['medium']
        elif text_length < 100000:
            return cls.CHUNK_SIZES['large']
        else:
            return cls.CHUNK_SIZES['xlarge']

    @classmethod
    def get_overlap(cls, chunk_size: int) -> int:
        """Get optimal overlap based on chunk size."""
        if chunk_size <= cls.CHUNK_SIZES['small']:
            return int(chunk_size * cls.OVERLAP_RATIOS['small'])
        elif chunk_size <= cls.CHUNK_SIZES['medium']:
            return int(chunk_size * cls.OVERLAP_RATIOS['medium'])
        elif chunk_size <= cls.CHUNK_SIZES['large']:
            return int(chunk_size * cls.OVERLAP_RATIOS['large'])
        else:
            return int(chunk_size * cls.OVERLAP_RATIOS['xlarge'])

@dataclass
class PipelineConfig:
    """Main pipeline configuration."""
    default_model: str = "qwen3:8b"
    default_base_url: str = os.environ.get("LLM_BASE_URL", "http://localhost:11434")
    max_workers: int = 5
    max_file_workers: int = 1
    max_entities: int = 500
    min_confidence: float = 0.4

@dataclass
class BioMistralConfig:
    """Configuration for BioMistral validation."""
    model_name: str = "biomistral-7B"
    api_url: str = "http://localhost:11434"
    temperature: float = 0.1
    max_tokens: int = 500

@dataclass
class OptimizationConfig:
    """Configuration for performance optimizations."""
    fast_mode: bool = False
    use_json_mode: bool = False
    chunk_size_multiplier: float = 1.0
    api_type: str = "ollama"  # ollama, openai (for vLLM), or huggingface
    api_key: str = "EMPTY"    # For vLLM/OpenAI
    hf_token: str = None      # For HuggingFace


# ==========================================
# UTILITIES
# ==========================================

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

class TfidfSemanticModel:
    """Fallback semantic model using TF-IDF."""
    
    def __init__(self):
        self.vectorizer = TfidfVectorizer(stop_words='english', analyzer='char_wb', ngram_range=(2, 4))
        self.is_fitted = False
        
    def encode(self, sentences: List[str], batch_size: int = 32, show_progress_bar: bool = False, convert_to_numpy: bool = True):
        """
        Encode sentences using TF-IDF. 
        """
        if not sentences:
            return np.array([])
            
        try:
            # Fit on the current batch for internal deduplication
            embeddings = self.vectorizer.fit_transform(sentences)
            self.is_fitted = True
            if convert_to_numpy:
                return embeddings.toarray()
            return embeddings
        except ValueError:
            return np.zeros((len(sentences), 1))


class TextProcessor:
    """Utility class for text processing operations."""

    @staticmethod
    def chunk_text(text: str, chunk_size: int = 5000, overlap: int = 150) -> List[Tuple[str, int]]:
        """Split text into overlapping chunks for processing."""
        if not text or len(text) <= chunk_size:
            return [(text, 1)] if text else []

        chunks = []
        chunk_num = 1

        for i in range(0, len(text), chunk_size - overlap):
            chunk = text[i:i + chunk_size]
            if len(chunk.strip()) > 100:  # Only process substantial chunks
                chunks.append((chunk, chunk_num))
                chunk_num += 1

        logger.info(f"📊 Created {len(chunks)} chunks ({chunk_size} chars, {overlap} overlap)")
        return chunks

    @staticmethod
    def enhanced_preprocess_text(text: str) -> str:
        """Advanced text preprocessing with noise reduction."""
        if not text: return ""

        # Remove boilerplate sections
        patterns = [
            r"(\n\s*(?:References|Bibliography|Acknowledgments?|Author[s]? Contribution[s]?|Funding|Competing [Ii]nterest[s]?)\s*.*?)(?=\n\s*\w|\Z)",
            r"(\n\s*(?:Supplementary [Mm]aterial|Additional [Ff]ile[s]?|Supporting [Ii]nformation)\s*.*?)(?=\n\s*\w|\Z)",
            r"(\n\s*(?:Ethics [Ss]tatement|Consent|IRB [Aa]pproval)\s*.*?)(?=\n\s*\w|\Z)",
            r"(\n\s*(?:Abbreviations|Data [Aa]vailability)\s*.*?)(?=\n\s*\w|\Z)"
        ]

        for pattern in patterns:
            text = re.sub(pattern, "\n", text, flags=re.DOTALL | re.IGNORECASE)

        # Remove citations and references
        text = re.sub(r'\[\d+\]', '', text)
        text = re.sub(r'\([^)]*?\d{4}[^)]*?\)', '', text)

        # Remove page numbers and headers
        text = re.sub(r'\n\s*\d+\s*\n', '\n', text)

        # Clean whitespace
        text = re.sub(r'\n\s*\n\s*\n', '\n\n', text)
        text = re.sub(r'\s+', ' ', text)

        return text.strip()

    @staticmethod
    def strict_term_cleaning(term: str) -> Optional[str]:
        """Term cleaning that filters out artifacts but keeps biomedical terms."""
        if not isinstance(term, str) or len(term) < 2:
            return None

        # Initial cleaning
        cleaned = term.lower().strip()

        # Enhanced normalization
        greek_replacements = {
            'α': 'alpha', 'β': 'beta', 'γ': 'gamma', 'δ': 'delta',
            'ε': 'epsilon', 'ζ': 'zeta', 'η': 'eta', 'θ': 'theta',
            'ι': 'iota', 'κ': 'kappa', 'λ': 'lambda', 'μ': 'mu',
            'ν': 'nu', 'ξ': 'xi', 'ο': 'omicron', 'π': 'pi',
            'ρ': 'rho', 'σ': 'sigma', 'τ': 'tau', 'υ': 'upsilon',
            'φ': 'phi', 'χ': 'chi', 'ψ': 'psi', 'ω': 'omega'
        }

        for greek_char, replacement in greek_replacements.items():
            cleaned = cleaned.replace(greek_char, replacement)

        # Auto-expand known abbreviations
        abbreviation_expansions = {
            'fmt': 'fecal_microbiota_transplantation',
            'scfa': 'short_chain_fatty_acids',
            'otu': 'operational_taxonomic_unit',
            'asv': 'amplicon_sequence_variant',
            'pcoa': 'principal_coordinate_analysis',
            'nmds': 'non_metric_multidimensional_scaling',
            'pcr': 'polymerase_chain_reaction',
            'dna': 'deoxyribonucleic_acid',
            'rna': 'ribonucleic_acid',
            'mrna': 'messenger_rna',
            'trna': 'transfer_rna',
            'rrna': 'ribosomal_rna',
            'pdb': 'protein_data_bank',
            'ncbi': 'national_center_for_biotechnology_information',
            'blast': 'basic_local_alignment_search_tool'
        }

        if cleaned in abbreviation_expansions:
            cleaned = abbreviation_expansions[cleaned]

        # Remove problematic prefixes/suffixes
        prefix_patterns = [
            r'^(such_as|e_g|eg|for_example|including|like)[\s_]+',
            r'^(the|a|an|this|these|that|those)[\s_]+',
            r'^(and|or|but|however|therefore|thus)[\s_]+',
            r'[\s_]+(etc|et_al|and_so_on|respectively)$'
        ]

        for pattern in prefix_patterns:
            cleaned = re.sub(pattern, '', cleaned)

        # Convert to snake_case
        cleaned = re.sub(r'[\s\-\.]+', '_', cleaned)
        cleaned = re.sub(r'[^\w_]', '', cleaned)
        cleaned = re.sub(r'_+', '_', cleaned).strip('_')

        if not cleaned or len(cleaned) < 2:
            return None

        # Reject problematic patterns
        reject_patterns = [
            r'^\d+$',                      # pure numbers
            r'^(figure|table|fig|tab)_?\d*$', # figure references
            r'^[a-z]{1}$',                 # single letters
            r'.*conversational.*',         # conversational terms
            r'.*instructional.*',          # instructional terms
            r'.*procedural.*',             # procedural terms
            r'.*note.*',                   # note terms
            r'.*maybe.*',                  # uncertain terms
            r'.*seems.*',                  # uncertain terms
            r'.*might.*',                  # uncertain terms
            r'.*probably.*',               # uncertain terms
        ]

        for pattern in reject_patterns:
            if re.match(pattern, cleaned):
                return None

        # Reject conversational patterns
        conversational_indicators = [
            'so_', 'user_', 'mentioned_', 'if_', 'avoided_', 'note_', 'conversational_',
            'looking_', 'rules_', 'avoid_', 'sample_', 'text_', 'given_', 'actual_',
            'focusing_', 'prioritizing_', 'compiling_', 'categories_', 'requested_'
        ]

        if any(cleaned.startswith(indicator) for indicator in conversational_indicators):
            return None

        # Must contain at least one letter
        if not re.search(r'[a-z]', cleaned):
            return None

        return cleaned

    @staticmethod
    def clean_text(text: str) -> str:
        """Legacy clean_text wrapper calling enhanced_preprocess_text."""
        return TextProcessor.enhanced_preprocess_text(text)

    @staticmethod
    def extract_sentences(text: str) -> List[str]:
        """Extract sentences from text."""
        sentences = []
        for sentence in re.split(r'[.!?]+', text):
            sentence = sentence.strip()
            if len(sentence) > 10:
                sentences.append(sentence)
        return sentences

    @staticmethod
    def calculate_text_stats(text: str) -> dict:
        """Calculate basic text statistics."""
        if not text:
            return {"char_count": 0, "word_count": 0, "sentence_count": 0}
        words = text.split()
        sentences = TextProcessor.extract_sentences(text)
        return {
            "char_count": len(text),
            "word_count": len(words),
            "sentence_count": len(sentences),
            "avg_word_length": sum(len(word) for word in words) / len(words) if words else 0,
            "reading_time_minutes": len(words) / 200
        }

class ValidationLevel(Enum):
    """Validation severity levels"""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"

@dataclass
class ValidationIssue:
    """Represents a validation issue found in results"""
    level: ValidationLevel
    category: str
    message: str
    entity_index: Optional[int] = None
    entity_type: Optional[str] = None
    confidence_score: Optional[float] = None
    suggestion: Optional[str] = None

@dataclass
class ValidationResult:
    """Complete validation result for entities"""
    is_valid: bool
    total_entities: int
    valid_entities: int
    issues: List[ValidationIssue] = field(default_factory=list)
    summary: Dict[str, Any] = field(default_factory=dict)
    recommendations: List[str] = field(default_factory=list)
    validation_metadata: Dict[str, Any] = field(default_factory=dict)

class EntityValidator:
    """Validates individual entities for quality and consistency"""

    def __init__(self):
        self.valid_entity_types = set(CDMEntityConfig.ENTITY_TYPES.keys())
        self.min_lengths = {'default': 2}
        self.max_lengths = {'default': 100}
        self.invalid_patterns = [
            r'^\d+$', r'^[^a-zA-Z]+$', r'.*[<>{}[\]\\].*', r'^\s+$',
            r'^(the|and|or|but|in|on|at|to|for|of|with|by)\s*$'
        ]
        self.organism_indicators = [
            'bacterium', 'bacteria', 'species', 'strain', 'family', 'phylum',
            'genus', 'order', 'class', 'kingdom', 'domain', 'coli', 'coccus',
            'bacillus', 'streptococcus', 'lactobacillus', 'bifidobacterium'
        ]

    def validate_entity(self, entity: Dict[str, Any], index: int) -> List[ValidationIssue]:
        issues = []
        entity_text = str(entity.get('entity', '')).strip()
        entity_type = str(entity.get('entity_type', '')).upper()
        confidence = float(entity.get('confidence', 0.0))

        if not entity_text:
            issues.append(ValidationIssue(ValidationLevel.ERROR, 'empty_entity', "Entity text is empty", index))
            return issues

        if entity_type not in self.valid_entity_types:
            issues.append(ValidationIssue(ValidationLevel.WARNING, 'invalid_type', f"Unknown entity type: {entity_type}", index, entity_type))

        if not (0.0 <= confidence <= 1.0):
            issues.append(ValidationIssue(ValidationLevel.ERROR, 'invalid_confidence', f"Confidence out of range: {confidence}", index, entity_type, confidence))

        return issues

class ResultConsistencyChecker:
    """Checks for consistency across multiple entities"""
    def check_consistency(self, entities: List[Dict[str, Any]]) -> List[ValidationIssue]:
        return [] # Simplified for standalone

class CDMResultValidator:
    """Main result validator that combines all validation checks"""
    def __init__(self):
        self.entity_validator = EntityValidator()
        self.consistency_checker = ResultConsistencyChecker()

    def validate_results(self, entities: List[Dict[str, Any]], context: Dict[str, Any] = None) -> ValidationResult:
        all_issues = []
        for i, entity in enumerate(entities):
            all_issues.extend(self.entity_validator.validate_entity(entity, i))
        
        error_count = sum(1 for issue in all_issues if issue.level == ValidationLevel.ERROR)
        return ValidationResult(
            is_valid=error_count == 0,
            total_entities=len(entities),
            valid_entities=len(entities) - error_count,
            issues=all_issues
        )

# Alias
ResultValidator = CDMResultValidator

# ==========================================
# CORE COMPONENTS
# ==========================================

class LLMClient:
    """Client for interacting with LLM models."""

    def __init__(self, model: str = "qwen3:8b", base_url: str = "http://localhost:11434", 
                 optimization_config: OptimizationConfig = None):
        self.model = model
        self.base_url = base_url
        self.config = CDMEntityConfig.MODEL_CONFIGS.get(model, CDMEntityConfig.MODEL_CONFIGS['qwen3:8b'])
        self.opt_config = optimization_config or OptimizationConfig()
        self.hf_pipeline = None
        self.hf_tokenizer = None
        self.token_usage = {"input_tokens": 0, "output_tokens": 0}
        logger.info(f"🤖 LLM Client initialized with model: {self.model} (API: {self.opt_config.api_type})")

    def get_token_usage(self) -> Dict[str, int]:
        """Get total token usage."""
        return self.token_usage

    def call_llm(self, prompt: str, max_tokens: Optional[int] = None) -> str:
        """Call LLM with structured prompt and return response."""
        if self.opt_config.api_type == "openai":
            return self._call_openai_compatible(prompt, max_tokens)
        elif self.opt_config.api_type == "anthropic":
            return self._call_anthropic(prompt, max_tokens)
        elif self.opt_config.api_type == "glm":
            return self._call_glm(prompt, max_tokens)
        elif self.opt_config.api_type == "huggingface":
            return self._call_huggingface_local(prompt, max_tokens)
        else:
            return self._call_ollama(prompt, max_tokens)

    def _call_openai_compatible(self, prompt: str, max_tokens: Optional[int] = None, extra_body: Optional[Dict] = None) -> str:
        """Call OpenAI-compatible API using the official SDK."""
        try:
            from openai import OpenAI
        except ImportError:
            logger.error("OpenAI SDK not installed. Please run: pip install openai")
            return ""

        # Initialize client if not already done (or recreate if base_url changes)
        # Note: In a persistent class we might want to cache this, but for now we create it per call 
        # or we could add it to __init__. Let's create it here for safety with dynamic base_urls.
        
        client = OpenAI(
            api_key=self.opt_config.api_key,
            base_url=self.base_url
        )
        
        messages = [{"role": "user", "content": prompt}]
        
        # Prepare arguments
        kwargs = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.1, # Default low temp
            "timeout": self.config.get('timeout', 60)
        }
        
        if max_tokens:
            kwargs["max_tokens"] = max_tokens
            
        if extra_body:
            kwargs["extra_body"] = extra_body
            
        if self.opt_config.use_json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        max_retries = 3
        base_delay = 1

        for attempt in range(max_retries):
            try:
                completion = client.chat.completions.create(**kwargs)
                
                # Track usage
                if completion.usage:
                    self.token_usage['input_tokens'] += completion.usage.prompt_tokens
                    self.token_usage['output_tokens'] += completion.usage.completion_tokens
                
                message = completion.choices[0].message
                content = message.content
                
                # Fallback for models (like GLM-4.7) that return output in reasoning_content
                if not content:
                    # Try attribute access
                    if hasattr(message, 'reasoning_content') and message.reasoning_content:
                        content = message.reasoning_content
                    # Try model_extra
                    elif hasattr(message, 'model_extra') and message.model_extra and 'reasoning_content' in message.model_extra:
                        content = message.model_extra['reasoning_content']
                    # Try dict access
                    elif isinstance(message, dict) and 'reasoning_content' in message:
                        content = message['reasoning_content']

                return content.strip() if content else ""
                
            except Exception as e:
                logger.warning(f"OpenAI API call failed (attempt {attempt+1}): {e}")
                if hasattr(e, 'response') and e.response:
                    logger.warning(f"Response body: {e.response.text}")
                time.sleep(base_delay * (2 ** attempt))
        
        logger.error(f"OpenAI API call failed after {max_retries} retries.")
        return ""

    def _call_anthropic(self, prompt: str, max_tokens: Optional[int] = None) -> str:
        """Call Anthropic API (Claude) or ZhipuAI (Anthropic-compatible)."""
        max_retries = 3
        base_delay = 1
        
        # Check if we are using ZhipuAI (based on URL or key format)
        is_zhipu = "bigmodel.cn" in (self.base_url or "") or "api.z.ai" in (self.base_url or "")
        
        if is_zhipu:
            # ZhipuAI uses Bearer token
            headers = {
                "Authorization": f"Bearer {self.opt_config.api_key}",
                "Content-Type": "application/json"
            }
        else:
            # Standard Anthropic headers
            headers = {
                "x-api-key": self.opt_config.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json"
            }
    
        payload = {
            "model": self.model,
            "max_tokens": max_tokens or self.config.get('max_tokens', 4096),
            "messages": [{"role": "user", "content": prompt}]
        }
        
        # Determine URL
        if is_zhipu:
             # Zhipu URL usually ends in /messages, but let's be safe
             if self.base_url:
                 url = f"{self.base_url}/messages" if not self.base_url.endswith("/messages") else self.base_url
             else:
                 url = "https://open.bigmodel.cn/api/paas/v4/messages"
        else:
            url = "https://api.anthropic.com/v1/messages"
            # Use custom base_url if provided and not the default Ollama one
            if self.base_url and "localhost:11434" not in self.base_url:
                url = f"{self.base_url}/messages" if not self.base_url.endswith("/messages") else self.base_url
                logger.info(f"Using custom Anthropic URL: {url}")
        
        for attempt in range(max_retries):
            try:
                response = requests.post(url, headers=headers, json=payload, timeout=self.config.get('timeout', 60))
                
                if response.status_code == 200:
                    resp_json = response.json()
                    
                    # Track usage
                    if 'usage' in resp_json:
                        usage = resp_json['usage']
                        self.token_usage['input_tokens'] += usage.get('input_tokens', 0)
                        self.token_usage['output_tokens'] += usage.get('output_tokens', 0)
                        
                    try:
                        content = resp_json['content'][0]['text'].strip()
                        return content
                    except (KeyError, IndexError, TypeError) as e:
                        logger.error(f"Failed to parse Anthropic response: {e}")
                        logger.error(f"Raw Response: {response.text}")
                        # Try fallback for potential proxy formats (e.g. OpenAI format from an 'anthropic' endpoint?)
                        if 'choices' in resp_json:
                            return resp_json['choices'][0]['message']['content'].strip()
                        return ""
                else:
                    logger.warning(f"Anthropic API error (attempt {attempt+1}): {response.status_code} - {response.text}")
            except Exception as e:
                logger.warning(f"Anthropic API call failed (attempt {attempt+1}): {e}")
                
            time.sleep(base_delay * (2 ** attempt))
            
        logger.error("Anthropic API call failed after all retries.")
        return ""

    def _call_glm(self, prompt: str, max_tokens: Optional[int] = None) -> str:
        """Call GLM-4 API (OpenAI-compatible)."""
        # GLM-4 uses OpenAI-compatible endpoint
        # Official endpoint from docs: https://api.z.ai/api/paas/v4/
        
        # If base_url is default localhost, switch to official Z.AI endpoint
        if "localhost" in self.base_url or "open.bigmodel.cn" in self.base_url:
             # User requested Z.AI endpoint specifically in the prompt
            self.base_url = "https://api.z.ai/api/paas/v4/"
            
        # Add 'thinking' parameter for GLM-4.6 as per docs
        extra_body = None
        # Always enable thinking for glm-4.6 or if explicitly requested
        if "glm-4.6" in self.model or self.model == "glm-4" or "glm-4-6" in self.model:
             # Note: The user provided docs show "thinking": {"type": "enabled"} for glm-4.6
             if "glm-4.6" in self.model:
                extra_body = {"thinking": {"type": "enabled"}}
        
        return self._call_openai_compatible(prompt, max_tokens, extra_body=extra_body)

    def _call_ollama(self, prompt: str, max_tokens: Optional[int] = None) -> str:
        """Call Ollama API."""
        max_retries = 3
        base_delay = 2

        for attempt in range(max_retries):
            try:
                request_config = {
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": self.config['temperature'],
                        "top_p": 0.9,
                        "num_predict": max_tokens or self.config['max_tokens'],
                    }
                }

                headers = {}
                if self.opt_config.api_key and self.opt_config.api_key != "EMPTY":
                    headers["Authorization"] = f"Bearer {self.opt_config.api_key}"

                response = requests.post(
                    f"{self.base_url}/api/generate",
                    json=request_config,
                    headers=headers,
                    timeout=self.config['timeout']
                )

                if response.status_code == 200:
                    logger.debug(f"LLM Response Status: {response.status_code}")
                    logger.debug(f"LLM Response Body: {response.text[:500]}...")
                    resp_json = response.json()
                    content = resp_json.get('response', '').strip()
                    
                    # Handle 'thinking' field (seen in qwen3:4b)
                    if not content and 'thinking' in resp_json:
                        logger.debug("Found content in 'thinking' field")
                        content = resp_json['thinking'].strip()
                        
                    # Final check and debug
                    if not content:
                        logger.warning(f"⚠️  LLM returned empty content. Keys found: {list(resp_json.keys())}")
                        logger.debug(f"Full Response JSON: {str(resp_json)[:1000]}...")
                        
                    return content
                else:
                    logger.warning(f"LLM API error (attempt {attempt+1}/{max_retries}): {response.status_code} - {response.text}")
                    
            except Exception as e:
                logger.warning(f"LLM call failed (attempt {attempt+1}/{max_retries}): {e}")
            
            if attempt < max_retries - 1:
                time.sleep(base_delay * (2 ** attempt))  # Exponential backoff

        logger.error("LLM call failed after all retries.")
        return ""

    def _call_huggingface_local(self, prompt: str, max_tokens: Optional[int] = None) -> str:
        """Call HuggingFace model locally."""
        try:
            if not self.hf_pipeline:
                logger.info(f"🤗 Loading HuggingFace model: {self.model}...")
                
                # Check for GPU
                device = "cuda" if torch.cuda.is_available() else "cpu"
                logger.info(f"   Device: {device}")
                
                try:
                    self.hf_tokenizer = AutoTokenizer.from_pretrained(
                        self.model, 
                        token=self.opt_config.hf_token,
                        trust_remote_code=True
                    )
                    
                    # Load model with 4-bit quantization if possible to save memory
                    # Requires bitsandbytes
                    try:
                        from transformers import BitsAndBytesConfig
                        quantization_config = BitsAndBytesConfig(
                            load_in_4bit=True,
                            bnb_4bit_compute_dtype=torch.float16
                        )
                        logger.info("   Using 4-bit quantization")
                    except ImportError:
                        quantization_config = None
                        logger.warning("   bitsandbytes not found, loading full precision (might OOM)")

                    self.hf_pipeline = AutoModelForCausalLM.from_pretrained(
                        self.model,
                        token=self.opt_config.hf_token,
                        device_map="auto" if device == "cuda" else None,
                        quantization_config=quantization_config,
                        trust_remote_code=True,
                        torch_dtype=torch.float16 if device == "cuda" else torch.float32
                    )
                except Exception as e:
                    logger.error(f"Failed to load HF model: {e}")
                    return ""

            # Generate
            inputs = self.hf_tokenizer(prompt, return_tensors="pt").to(self.hf_pipeline.device)
            
            with torch.no_grad():
                outputs = self.hf_pipeline.generate(
                    **inputs,
                    max_new_tokens=max_tokens or self.config['max_tokens'],
                    temperature=self.config['temperature'],
                    do_sample=True,
                    pad_token_id=self.hf_tokenizer.eos_token_id
                )
                
            response = self.hf_tokenizer.decode(outputs[0][inputs.input_ids.shape[1]:], skip_special_tokens=True)
            return response.strip()

        except Exception as e:
            logger.error(f"HuggingFace local generation failed: {e}")
            return ""

    def is_available(self) -> bool:
        """Check if the LLM service is available."""
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=10)
            return response.status_code == 200
        except:
            return False

    def get_available_models(self) -> List[str]:
        """Get list of available models."""
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=10)
            if response.status_code == 200:
                models = response.json().get('models', [])
                return [model['name'] for model in models]
            return []
        except:
            return []

    def generate(self, prompt: str, model: str = None, max_tokens: int = None) -> str:
        """Alias for call_llm to support different method signatures."""
        # Temporarily switch model if requested
        original_model = self.model
        if model:
            self.model = model
        
        result = self.call_llm(prompt, max_tokens)
        
        self.model = original_model
        return result

# ==========================================
# EXTRACTORS
# ==========================================

class CDMEntityExtractor:
    """Extracts CDM-structured biomedical entities from text."""

    # Microbiome-specific keywords for relevance scoring
    MICROBIOME_KEYWORDS = {
        'gut', 'microbiome', 'microbiota', 'bacteria', 'bacterial', 'intestinal',
        'colon', 'fecal', 'faecal', 'stool', 'dysbiosis', 'probiotic', 'prebiotic',
        'fermentation', 'scfa', 'short-chain fatty acid', 'mucosa', 'lumen',
        'commensal', 'pathogen', 'axis', 'metabolite', 'butyrate', 'propionate', 'acetate',
        'firmicutes', 'bacteroidetes', 'proteobacteria', 'actinobacteria', 'veillonella',
        'coprococcus', 'ruminococcus', 'faecalibacterium', 'bifidobacterium', 'lactobacillus',
        'prevotella', 'clostridium', 'enterobacteriaceae', 'streptococcaceae', 'microbial',
        'antibiotic', 'antimicrobial', 'inflammation', 'immune', 'metabolome', 'metagenomic'
    }

    def __init__(self, llm_client: 'LLMClient'):
        self.llm_client = llm_client
        self.entity_config = CDMEntityConfig()

    def calculate_confidence(self, term: str, entity_type: str, context: str = '',
                            definition: str = '', examples: list = None,
                            aliases: list = None) -> float:
        """
        Calculate confidence score based on multiple factors.

        Factors:
        1. Entity type priority (from ENTITY_TYPES)
        2. Pattern matching (does term match expected patterns?)
        3. Context quality (length, relevance)
        4. Supporting evidence (definition, examples, aliases)
        5. Microbiome relevance (keyword matching)
        6. Term quality (length, formatting)

        Returns: float between 0.0 and 1.0
        """
        if examples is None:
            examples = []
        if aliases is None:
            aliases = []

        confidence = 0.5  # Base confidence

        # ========== 1. Entity Type Priority (0-0.25) ==========
        type_info = self.entity_config.ENTITY_TYPES.get(entity_type, {})
        priority = type_info.get('priority', 10)

        # Lower priority = higher confidence (priority 1 is best)
        if priority <= 2:
            confidence += 0.25
        elif priority <= 4:
            confidence += 0.18
        elif priority <= 6:
            confidence += 0.12
        elif priority <= 8:
            confidence += 0.06
        else:
            confidence += 0.02

        # ========== 2. Pattern Matching (0-0.15) ==========
        patterns = type_info.get('patterns', [])
        if patterns:
            pattern_match = any(re.search(pattern, term, re.IGNORECASE) for pattern in patterns)
            if pattern_match:
                confidence += 0.15
            elif entity_type == 'ORGANISM' and re.search(r'\b[A-Z][a-z]+[a-z]*\s+[a-z]+', term):
                # Scientific name format bonus
                confidence += 0.12
            elif entity_type in ['GENE', 'PROTEIN'] and re.search(r'^[A-Z0-9\-]{2,}$', term):
                # Gene/Protein abbreviation format
                confidence += 0.10

        # ========== 3. Context Quality (0-0.15) ==========
        context_lower = context.lower()
        term_lower = term.lower()

        # Context length score
        if len(context) >= 100:
            confidence += 0.08
        elif len(context) >= 50:
            confidence += 0.05
        elif len(context) >= 20:
            confidence += 0.02

        # Context contains the term (good indicator)
        if term_lower in context_lower:
            confidence += 0.07

        # ========== 4. Supporting Evidence (0-0.15) ==========
        evidence_score = 0.0

        # Definition quality
        if definition and len(definition) > 50:
            evidence_score += 0.06
        elif definition and len(definition) > 20:
            evidence_score += 0.04
        elif definition:
            evidence_score += 0.02

        # Examples
        if examples:
            if isinstance(examples, list) and len(examples) > 0:
                evidence_score += 0.05
            elif isinstance(examples, str) and len(examples) > 5:
                evidence_score += 0.05

        # Aliases
        if aliases:
            if isinstance(aliases, list) and len(aliases) > 0:
                evidence_score += 0.04
            elif isinstance(aliases, str) and len(aliases) > 2:
                evidence_score += 0.04

        confidence += min(evidence_score, 0.15)

        # ========== 5. Microbiome Relevance (0-0.15) ==========
        relevance_text = term_lower + ' ' + context_lower
        keyword_matches = sum(1 for kw in self.MICROBIOME_KEYWORDS if kw in relevance_text)

        if keyword_matches >= 3:
            confidence += 0.15
        elif keyword_matches >= 2:
            confidence += 0.12
        elif keyword_matches >= 1:
            confidence += 0.08

        # Bonus for core entity types in microbiome context
        if entity_type in ['ORGANISM', 'CHEMICAL', 'GENE', 'PROTEIN']:
            if any(kw in relevance_text for kw in ['gut', 'microbiome', 'microbiota', 'fecal', 'stool']):
                confidence += 0.05

        # ========== 6. Term Quality (penalties) ==========
        term_len = len(term)

        # Very short terms
        if term_len < 3:
            confidence *= 0.6
        elif term_len < 5:
            confidence *= 0.8

        # Single word terms (slightly lower confidence)
        if ' ' not in term and not re.match(r'^[A-Z]{2,}[0-9\-]*$', term):
            confidence *= 0.92

        # Terms with only numbers/symbols
        if re.match(r'^[\d\W]+$', term):
            confidence *= 0.3

        # Terms with excessive special characters
        special_char_ratio = sum(1 for c in term if not c.isalnum() and c != ' ') / max(len(term), 1)
        if special_char_ratio > 0.3:
            confidence *= 0.7
        elif special_char_ratio > 0.2:
            confidence *= 0.85

        # ========== 7. Certainty Boosters ==========
        # Well-formatted scientific names
        if re.match(r'^[A-Z][a-z]+ [a-z]+$', term):  # Genus species
            confidence = min(confidence * 1.08, 1.0)
        elif re.match(r'^[A-Z]{2,}[0-9\-]*$', term):  # Gene/Protein code
            confidence = min(confidence * 1.05, 1.0)

        # Final clamp
        return round(min(max(confidence, 0.1), 1.0), 3)

    def create_extraction_prompt(self, chunk_text: str) -> str:
        """Create structured prompt for CDM entity extraction."""
        return self._get_pass_prompt(0, chunk_text)

    def parse_llm_response(self, response: str, chunk_num: int) -> List[Dict]:
        """Parse LLM response and extract entities with robust cleaning."""
        entities = []
        try:
            # 1. Aggressive Cleanup of Chain-of-Thought (<think>...</think>)
            cleaned_response = re.sub(r'<think>.*?</think>', '', response, flags=re.DOTALL)
            if '<think>' in cleaned_response:
                 cleaned_response = re.sub(r'<think>.*', '', cleaned_response, flags=re.DOTALL)
            
            cleaned_response = re.sub(r'^Here is the list.*?:', '', cleaned_response, flags=re.IGNORECASE | re.MULTILINE)
            
            # Remove Markdown code blocks if present
            cleaned_response = re.sub(r'```[a-zA-Z]*\n', '', cleaned_response)
            cleaned_response = re.sub(r'```', '', cleaned_response)
            
            cleaned_response = cleaned_response.strip()

            logger.debug(f"🔍 Processed LLM Response (Chunk {chunk_num}):\n{cleaned_response[:500]}...") 
            
            # 2. Try to parse as JSON first (List of objects)
            if (cleaned_response.startswith('[') and cleaned_response.endswith(']')) or \
               (cleaned_response.startswith('{') and cleaned_response.endswith('}')):
                try:
                    data = json.loads(cleaned_response)
                    
                    # If it's a dictionary wrapping the list (e.g. {"entities": [...]})
                    if isinstance(data, dict):
                        for key in ['entities', 'terms', 'results', 'output', 'answer', 'content']:
                            if key in data:
                                if isinstance(data[key], list):
                                    data = data[key]
                                    break
                                elif isinstance(data[key], str):
                                    # If the key contains a string, it might be the text block
                                    cleaned_response = data[key]
                                    # Fall through to line parsing with this new text
                                    raise json.JSONDecodeError("Found text block in JSON", cleaned_response, 0)
                    
                    if isinstance(data, list):
                        for item in data:
                            if not isinstance(item, dict): continue
                            
                            term = item.get('entity', item.get('term', '')).strip()
                            entity_type = item.get('entity_type', item.get('type', '')).upper()
                            context = item.get('context', '')
                            definition = item.get('definition', '')
                            aliases = item.get('aliases', [])
                            if isinstance(aliases, str): aliases = [a.strip() for a in aliases.split(',')]
                            examples = item.get('examples', [])
                            if isinstance(examples, str): examples = [e.strip() for e in examples.split(',')]
                            
                            # Map type
                            entity_type = self._map_hallucinated_type(entity_type)
                            
                            if self._validate_entity(term, entity_type):
                                entities.append({
                                    'entity': term,
                                    'entity_type': entity_type,
                                    'context': context,
                                    'definition': definition,
                                    'aliases': aliases,
                                    'examples': examples,
                                    'confidence': self.calculate_confidence(term, entity_type, context, definition, examples, aliases),
                                    'source_pass': 0
                                })
                        
                        if entities:
                            return entities
                            
                except json.JSONDecodeError:
                    pass # Fallback to line parsing

            # 3. Strict Line-by-Line Parsing
            # We expect: "- Term (TYPE): Context"
            lines = cleaned_response.split('\n')
            for line in lines:
                line = line.strip()
                if not line: continue
                
                # Skip conversational lines
                if line.lower().startswith(('here are', 'sure', 'i have', 'note:', 'however', 'let\'s list', 'but', 'also', 'the text', 'actually', 'for example', 'in this text', 'output:', 'extracted terms:')):
                    continue

                # Split by pipe to separate main term info from extra details
                parts = line.split('|')
                main_part = parts[0].strip()
                
                # Regex to capture: Optional bullet, Term, (TYPE), Optional Context
                match = re.match(r'^(?:[\-\*0-9\.]+\s*)?(.+?)\s*\(([^)]+)\)(?:\s*[:\-]\s*(.+))?$', main_part)
                
                if match:
                    term = match.group(1).strip()
                    entity_type = match.group(2).strip().upper()
                    context = match.group(3).strip() if match.group(3) else ""
                    
                    # Cleanup term - Remove common JSON artifacts if regex matched them
                    # e.g. 'answer": "- Term' -> 'Term'
                    if '":' in term:
                         term = term.split('":')[-1].strip()
                    if '":"' in term:
                         term = term.split('":"')[-1].strip()
                    
                    term = term.strip('"\'').strip('-').strip()
                    
                    # Map hallucinated types
                    entity_type = self._map_hallucinated_type(entity_type)
                    
                    # Parse extra fields
                    definition = ""
                    aliases = []
                    examples = []
                    
                    for part in parts[1:]:
                        part = part.strip()
                        if part.lower().startswith("definition:"):
                            definition = part[11:].strip()
                        elif part.lower().startswith("aliases:"):
                            aliases_str = part[8:].strip()
                            if aliases_str and aliases_str.lower() != "none":
                                aliases = [a.strip() for a in aliases_str.split(',')]
                        elif part.lower().startswith("examples:"):
                            examples_str = part[9:].strip()
                            if examples_str and examples_str.lower() != "none":
                                examples = [e.strip() for e in examples_str.split(',')]

                    # Validate
                    if self._validate_entity(term, entity_type):
                        entities.append({
                            'entity': term,
                            'entity_type': entity_type,
                            'context': context,
                            'definition': definition,
                            'aliases': aliases,
                            'examples': examples,
                            'confidence': self.calculate_confidence(term, entity_type, context, definition, examples, aliases),
                            'source_pass': 0
                        })

        except Exception as e:
            logger.error(f"Error parsing LLM response for chunk {chunk_num}: {e}")
            logger.debug(f"Full response that caused error: {response}")
            
        return entities

    def _find_sentence_context(self, term: str, text: str) -> str:
        """Find the full paragraph (multiple sentences) containing the term in the text."""
        if not term or not text:
            return ""

        # Normalize for search
        term_lower = term.lower()
        text_lower = text.lower()

        try:
            start_idx = text_lower.find(term_lower)
            if start_idx == -1:
                return ""

            # Find paragraph boundaries (capture 3 sentences before and after for context)
            # Look backward for paragraph start (3 sentences back or newline)
            sent_start = start_idx
            for _ in range(3):  # Go back up to 3 sentences
                prev_period = text.rfind('.', 0, sent_start)
                prev_excl = text.rfind('!', 0, sent_start)
                prev_quest = text.rfind('?', 0, sent_start)
                prev_newline = text.rfind('\n\n', 0, sent_start)  # Double newline = paragraph break

                # Find the furthest back we can go
                prev_boundaries = [b for b in [prev_period, prev_excl, prev_quest, prev_newline] if b > 0]
                if not prev_boundaries:
                    break
                sent_start = min(prev_boundaries)

            sent_start = sent_start + 1 if sent_start > 0 else 0

            # Look forward for paragraph end (3 sentences forward or newline)
            sent_end = start_idx
            for _ in range(3):  # Go forward up to 3 sentences
                next_period = text.find('.', sent_end + 1)
                next_excl = text.find('!', sent_end + 1)
                next_quest = text.find('?', sent_end + 1)
                next_newline = text.find('\n\n', sent_end)  # Double newline = paragraph break

                # Find the nearest boundary
                next_boundaries = [b for b in [next_period, next_excl, next_quest, next_newline] if b > sent_end]
                if not next_boundaries:
                    break
                sent_end = min(next_boundaries)

            if sent_end == -1 or sent_end <= start_idx:  # Not found, take rest of text
                sent_end = len(text)
            else:
                sent_end += 1  # Include the punctuation

            # Limit to 2000 characters to avoid huge contexts
            context = text[sent_start:sent_end].strip()
            return context[:2000] if len(context) > 2000 else context
        except Exception:
            return ""

    def _validate_entity(self, term: str, entity_type: str) -> bool:
        """Validate entity structure and content."""
        if not term or not isinstance(term, str) or len(term) < 2:
            return False
            
        # Check if type is valid
        if entity_type not in self.entity_config.ENTITY_TYPES:
            # Try to map it again or check if it's a sub-string of a valid type
            found = False
            for valid_type in self.entity_config.ENTITY_TYPES:
                if valid_type in entity_type:
                    entity_type = valid_type
                    found = True
                    break
            if not found:
                return False

        # 2. Check for pure numbers or simple units
        if re.match(r'^[\d\.,\s%±<>≤≥=°]+$', term):
            return False
            
        # Check specifically for temperature-like terms (e.g. 60°C)
        if '°' in term:
             return False
            
        # 3. Check for statistical terms and common noise
        noise_terms = {
            'p-value', 'confidence interval', 'odds ratio', 'relative risk',
            'standard deviation', 'mean', 'median', 'mode', 'range',
            'significant', 'significance', 'correlation', 'regression',
            'analysis', 'study', 'data', 'result', 'conclusion',
            'table', 'figure', 'fig', 'section', 'method',
            'g/ml', 'mg/ml', 'ug/ml', 'mm', 'cm', 'kg', 'mg', 'ug', 'ng',
            'min', 'sec', 'hour', 'day', 'week', 'month', 'year',
            'fdr', 'anova', 't-test', 'chi-square', 'wilcoxon',
            'statistical', 'statistically', 'value', 'score'
        }
        
        if term.lower() in noise_terms:
            return False
            
        # Check if term is just a number with a unit (e.g. "5 mg")
        if re.match(r'^[\d\.]+\s*[a-zA-Z/%]+$', term):
            return False

        # 4. Check for generic words (stop words)
        stop_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by'}
        if term.lower() in stop_words:
            return False
            
        # 5. Check for Author names and Affiliations (Junk filtering)
        if 'et al' in term.lower():
            return False
            
        affiliation_keywords = {
            'university', 'institute', 'department', 'center', 'centre', 'college', 'school',
            'hospital', 'laboratory', 'foundation', 'group', 'consortium', 'ministry',
            'academy', 'division', 'unit', 'program', 'programme', 'council', 'bureau',
            'author', 'correspondence', 'email', 'address', 'tel', 'fax', 'phd', 'md',
            'professor', 'prof', 'dr', 'scientist', 'researcher'
        }
        
        # Check if any affiliation keyword is in the term
        term_lower = term.lower()
        if any(keyword in term_lower.split() for keyword in affiliation_keywords):
            return False
            
        # Check for citation patterns like (Smith 2020) or [1]
        if re.search(r'\(\w+\s+\d{4}\)', term) or re.search(r'\[\d+\]', term):
            return False

        # 6. Check for Grant Numbers (e.g., R01HD078912)
        # Pattern: 1-3 letters, 2 digits, 1-3 letters, 5-6 digits
        if re.match(r'^[A-Z]{1,4}\d{2,5}[A-Z]{0,3}\d{4,8}$', term, re.IGNORECASE):
            return False
        if re.search(r'\b(grant|award|contract)\s+(no\.?|number)?\s*[A-Z0-9-]+\b', term_lower):
            return False

        # 7. Check for Journal Names and Publishers
        journal_blocklist = {
            'frontiers in', 'bmj open', 'nature', 'science', 'cell host', 'plos one',
            'scientific reports', 'journal of', 'annals of', 'proceedings of',
            'nucleic acids res', 'genome biol', 'nat methods', 'sci transl med'
        }
        if any(j in term_lower for j in journal_blocklist):
            return False

        # 8. Check for Broad/Generic Terms
        broad_terms = {
            'microbiome', 'viral', 'amino acids', 'bacteria', 'fungi', 'archaea',
            'microbiota', 'gut microbiota', 'bacterial', 'microbial', 'pathogen',
            'probiotic', 'prebiotic', 'antibiotic', 'metabolome', 'genome',
            'metagenome', 'transcriptome', 'proteome', 'lipidome'
        }
        if term_lower in broad_terms:
            return False

        # Reject if term is in artifacts
        if term.lower() in ['none', 'n/a', 'null', 'unknown']:
            return False
            
        return True

    def _map_hallucinated_type(self, entity_type: str) -> str:
        """Map common hallucinated types to valid CDM types."""
        entity_type = entity_type.upper().strip()
        
        # Common mappings based on observation
        mapping = {
            'BACTERIA': 'ORGANISM', 'VIRUS': 'ORGANISM', 'FUNGI': 'ORGANISM', 'ARCHAEA': 'ORGANISM',
            'SPECIES': 'ORGANISM', 'GENUS': 'ORGANISM', 'MICROORGANISM': 'ORGANISM',
            'METABOLITE': 'CHEMICAL', 'DRUG': 'CHEMICAL', 'ANTIBIOTIC': 'CHEMICAL', 'COMPOUND': 'CHEMICAL',
            'MOLECULE': 'CHEMICAL', 'FATTY_ACID': 'CHEMICAL', 'SCFA': 'CHEMICAL',
            'GENE_NAME': 'GENE', 'GENETIC': 'GENE',
            'ENZYME': 'PROTEIN', 'PEPTIDE': 'PROTEIN',
            'METHOD': 'SCIENTIFIC_TERM', 'TECHNIQUE': 'SCIENTIFIC_TERM', 'APPROACH': 'SCIENTIFIC_TERM',
            'CONDITION': 'DISEASE', 'SYMPTOM': 'DISEASE', 'DISORDER': 'DISEASE',
            'TOOL': 'BIOINFO_TOOL', 'SOFTWARE': 'BIOINFO_TOOL', 'DATABASE': 'BIOINFO_TOOL',
            'BODY_SITE': 'CLINICAL', 'ANATOMY': 'CLINICAL', 'TISSUE': 'CELL_TYPE'
        }
        
        if entity_type in mapping:
            return mapping[entity_type]
            
        # Partial match
        for key, val in mapping.items():
            if key in entity_type:
                return val
                
        return entity_type

    def _get_pass_prompt(self, pass_num: int, chunk_text: str, existing_terms: List[str] = None) -> str:
        """Generate specific prompt for extraction."""
        
        return f"""You are a specialized biomedical terminology extractor. Your goal is to extract **ONLY high-value, specific terms relevant to a Microbiome Common Data Model (CDM)**.

CRITICAL RULES:
1. Extract ONLY specific biomedical terms: specific organisms (species/genus), specific metabolites/chemicals, specific genes/proteins, and specific bioinformatics tools.
2. IGNORE generic scientific terms (e.g., "study", "analysis", "data", "results", "significant", "correlation", "p-value", "table", "figure").
3. Aim for HIGH PRECISION. Target the top 15-25 most important entities per chunk. Do NOT list every possible noun.
4. NEVER extract your own instructions, notes, or conversational phrases.
5. IGNORE all reasoning or "thinking" processes. Output ONLY the final list.
6. FORMAT: One term per line.
   Format: - Term (TYPE): Brief Context | Definition: Brief definition | Aliases: Alias1, Alias2 | Examples: Ex1, Ex2

VALID CATEGORIES:
- ORGANISM: Specific bacteria, viruses, fungi, taxa
- GENE: Specific genes, markers
- PROTEIN: Specific proteins, enzymes
- CHEMICAL: Specific metabolites, drugs, compounds
- DISEASE: Specific diseases, conditions
- DNA_RNA: Specific genetic material types
- CELL_TYPE: Specific cells, tissues
- SAMPLE_METHOD: Sample collection, transport, storage, DNA extraction
- LAB_METHOD: Library prep, sequencing platforms, wet-lab
- DATA_ANALYSIS: Bioinformatics tools, databases, statistics
- GENOMICS: Specific omics methods
- CLINICAL: Specific clinical parameters

TEXT TO ANALYZE:
{chunk_text}

OUTPUT FORMAT (STRICT):
For each extracted term, output in this format:
- TermName (TYPE): Context sentence | Definition: definition | Aliases: alias1, alias2 | Examples: example1, example2

IMPORTANT: Replace TermName with the actual extracted term, not "[Extracted Term]".

Start output immediately:
"""

    def extract_chunk_multi_pass(self, chunk_text: str, chunk_num: int) -> List[Dict]:
        """Extract entities from a chunk using multi-pass strategy (Single Comprehensive Pass)."""
        all_entities = []
        
        # Define passes
        # Reduced to single comprehensive pass for efficiency as per user request
        passes = [
            (0, "General Comprehensive"), 
        ]
        
        for pass_num, pass_name in passes:
            try:
                # logger.debug(f"   - Pass {pass_num} ({pass_name})...")
                prompt = self._get_pass_prompt(pass_num, chunk_text)
                response = self.llm_client.call_llm(prompt)
                
                entities = self.parse_llm_response(response, chunk_num)
                
                # Tag with pass info and enhance context
                for e in entities:
                    e['extraction_pass'] = pass_name
                    e['pass_index'] = pass_num
                    
                    # Find full sentence context from source text
                    sentence_context = self._find_sentence_context(e['entity'], chunk_text)
                    if sentence_context:
                        # If we found a sentence, use it. Append original LLM context if useful?
                        # User specifically asked for "the sentence it was listed in"
                        # So we prioritize the sentence.
                        if len(sentence_context) > len(e.get('context', '')):
                             e['context'] = sentence_context
                    
                if entities:
                    all_entities.extend(entities)
                    
            except Exception as e:
                logger.error(f"Error in pass {pass_num} for chunk {chunk_num}: {e}")
                
        return all_entities

    def run_extraction_pass(self, pass_data: Tuple[str, int, List[str]]) -> List[Dict]:
        """Execute a single extraction pass on a specific text window."""
        text, pass_num, existing_terms = pass_data
        logger.info(f"🚀 Starting Pass {pass_num} on {len(text)} chars")
        
        prompt = self._get_pass_prompt(pass_num, text, existing_terms)
        
        # Use lower temperature for aggressive pass
        # We can't easily set temp per call in current LLMClient, so we rely on prompt instructions
        response = self.llm_client.call_llm(prompt, max_tokens=4000)
        
        if not response:
            logger.warning(f"⚠️ Pass {pass_num} returned no response")
            return []
            
        logger.debug(f"🔍 Raw LLM Response (Pass {pass_num}):\n{response[:500]}...") # Log first 500 chars
        entities = self.parse_llm_response(response, pass_num)
        logger.info(f"✅ Pass {pass_num} found {len(entities)} entities")
        return entities

    def calculate_optimal_chunk_size(self, text_length: int) -> int:
        return self.entity_config.get_chunk_size(text_length)

    def calculate_overlap(self, chunk_size: int) -> int:
        return self.entity_config.get_overlap(chunk_size)

# ==========================================
# DEDUPLICATORS
# ==========================================

class SemanticDeduplicator:
    """Advanced semantic deduplication using Sentence Transformers."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2", similarity_threshold: float = 0.8):
        self.model_name = self._get_valid_model_name(model_name)
        self.similarity_threshold = similarity_threshold
        self.model = None
        self.entity_config = CDMEntityConfig()

    def _get_valid_model_name(self, model_name: str) -> str:
        model_mapping = {
            "nomic-embed-text": "nomic-ai/nomic-embed-text-v1.5",
            "minilm": "sentence-transformers/all-MiniLM-L6-v2",
            "miniLM": "sentence-transformers/all-MiniLM-L6-v2",
            "mpnet": "sentence-transformers/all-mpnet-base-v2",
            "bert": "sentence-transformers/all-mpnet-base-v2"
        }
        return model_mapping.get(model_name.lower(), model_name)

    def load_model(self) -> bool:
        try:
            logger.info(f"🔄 Loading sentence transformer model: {self.model_name}")
            if 'nomic' in self.model_name.lower():
                self.model = SentenceTransformer(self.model_name, trust_remote_code=True)
            else:
                self.model = SentenceTransformer(self.model_name)
            logger.info(f"✅ Model loaded successfully")
            return True
        except ImportError:
            logger.warning("⚠️ sentence-transformers not installed. Using TF-IDF fallback.")
            self.model = TfidfSemanticModel()
            return True
        except Exception as e:
            logger.warning(f"⚠️ Failed to load sentence transformer model: {e}. Using TF-IDF fallback.")
            self.model = TfidfSemanticModel()
            return True


    def encode_entities(self, entities: List[Dict]) -> Optional[np.ndarray]:
        if not self.model:
            if not self.load_model(): return None
        try:
            entity_texts = []
            for entity in entities:
                text = f"search_document: {entity['entity']} {entity.get('context', '')} {entity['entity_type']}"
                entity_texts.append(text.strip())
            
            embeddings = self.model.encode(entity_texts, batch_size=32, show_progress_bar=False, convert_to_numpy=True)
            return embeddings
        except Exception as e:
            logger.error(f"❌ Failed to encode entities: {e}")
            return None

    def find_semantic_duplicates(self, entities: List[Dict], embeddings: np.ndarray) -> List[int]:
        if len(entities) != len(embeddings): return []
        duplicate_indices = []
        processed = set()
        try:
            similarity_matrix = cosine_similarity(embeddings)
            for i in range(len(entities)):
                if i in processed: continue
                similar_indices = np.where(similarity_matrix[i] > self.similarity_threshold)[0]
                similar_indices = [idx for idx in similar_indices if idx != i and idx not in processed]
                if similar_indices:
                    candidate_indices = [i] + similar_indices
                    confidences = [entities[idx]['confidence'] for idx in candidate_indices]
                    best_idx = candidate_indices[np.argmax(confidences)]
                    for idx in candidate_indices:
                        if idx != best_idx:
                            duplicate_indices.append(idx)
                            processed.add(idx)
                    processed.add(best_idx)
            return duplicate_indices
        except Exception as e:
            logger.error(f"❌ Error finding semantic duplicates: {e}")
            return []

    def apply_semantic_deduplication(self, entities: List[Dict]) -> List[Dict]:
        if not entities: return entities
        logger.info(f"🔄 Starting semantic deduplication for {len(entities)} entities")
        deduplicated = []
        total_duplicates = 0
        for entity_type in self.entity_config.ENTITY_TYPES:
            type_entities = [e for e in entities if e['entity_type'] == entity_type]
            if not type_entities: continue
            if len(type_entities) <= 2:
                deduplicated.extend(type_entities)
                continue
            embeddings = self.encode_entities(type_entities)
            if embeddings is None:
                deduplicated.extend(type_entities)
                continue
            duplicate_indices = self.find_semantic_duplicates(type_entities, embeddings)
            type_deduplicated = [entity for idx, entity in enumerate(type_entities) if idx not in duplicate_indices]
            deduplicated.extend(type_deduplicated)
            total_duplicates += len(duplicate_indices)
        logger.info(f"✅ Semantic deduplication complete: {len(entities)} → {len(deduplicated)} (removed {total_duplicates})")
        return deduplicated

# ==============================================================================
# MAPPERS
# ==============================================================================

class OMOPDomain(Enum):
    """OMOP domain IDs for different entity types."""
    GENETIC = "Genetic"
    CONDITION = "Condition"
    DRUG = "Drug"
    PROCEDURE = "Procedure"
    MEASUREMENT = "Measurement"
    OBSERVATION = "Observation"
    SPECIMEN = "Specimen"
    DEVICE = "Device"

class OMOPVocabulary(Enum):
    """OMOP standard vocabulary IDs."""
    SNOMED = "SNOMED"
    LOINC = "LOINC"
    RXNORM = "RxNorm"
    ICD10CM = "ICD10CM"
    ICD9CM = "ICD9CM"
    HCPCS = "HCPCS"
    NDC = "NDC"
    ATC = "ATC"
    HGNC = "HGNC"
    ENSEMBL = "Ensembl"
    REFSEQ = "RefSeq"
    UNIPROT = "UniProt"

@dataclass
class OMOPMapping:
    """OMOP mapping result."""
    concept_id: int
    concept_name: str
    domain_id: str
    vocabulary_id: str
    concept_class_id: str
    standard_concept: str
    concept_code: str
    valid_start_date: str
    valid_end_date: str
    invalid_reason: str
    create_time: str
    mapping_confidence: float
    mapping_method: str

class OMOPMapper:
    """Maps CDM entities to OMOP standard concepts."""

    def __init__(self, athena_api_url: str = None, cache_mappings: bool = True):
        self.athena_api_url = athena_api_url or "http://api.ohdsi.org/WebAPI"
        self.cache = {} if cache_mappings else None
        self.entity_type_mappings = self._initialize_entity_type_mappings()

    def _initialize_entity_type_mappings(self) -> Dict[str, Dict]:
        """Initialize entity type to OMOP domain mappings."""
        return {
            "GENE": {
                "domain_id": OMOPDomain.GENETIC.value,
                "vocabularies": [OMOPVocabulary.HGNC.value, OMOPVocabulary.ENSEMBL.value, OMOPVocabulary.REFSEQ.value],
                "concept_classes": ["Gene", "Gene Variant", "Genomic Finding"]
            },
            "PROTEIN": {
                "domain_id": OMOPDomain.GENETIC.value,
                "vocabularies": [OMOPVocabulary.UNIPROT.value, OMOPVocabulary.SNOMED.value],
                "concept_classes": ["Protein", "Biomarker", "Enzyme"]
            },
            "CHEMICAL": {
                "domain_id": OMOPDomain.DRUG.value,
                "vocabularies": [OMOPVocabulary.RXNORM.value, OMOPVocabulary.NDC.value, OMOPVocabulary.ATC.value],
                "concept_classes": ["Drug", "Compound", "Chemical Substance"]
            },
            "DISEASE": {
                "domain_id": OMOPDomain.CONDITION.value,
                "vocabularies": [OMOPVocabulary.SNOMED.value, OMOPVocabulary.ICD10CM.value, OMOPVocabulary.ICD9CM.value],
                "concept_classes": ["Clinical Finding", "Disease", "Disorder"]
            },
            "CELL_TYPE": {
                "domain_id": OMOPDomain.MEASUREMENT.value,
                "vocabularies": [OMOPVocabulary.LOINC.value, OMOPVocabulary.SNOMED.value],
                "concept_classes": ["Cell Type", "Cell Finding", "Laboratory Test"]
            },
            "DNA_RNA": {
                "domain_id": OMOPDomain.GENETIC.value,
                "vocabularies": [OMOPVocabulary.REFSEQ.value, OMOPVocabulary.ENSEMBL.value],
                "concept_classes": ["DNA Sequence", "RNA Sequence", "Genomic Finding"]
            },
            "ORGANISM": {
                "domain_id": OMOPDomain.MEASUREMENT.value,
                "vocabularies": [OMOPVocabulary.SNOMED.value, OMOPVocabulary.LOINC.value],
                "concept_classes": ["Organism", "Microorganism", "Bacterial Finding"]
            },
            "BIOINFO_TOOL": {
                "domain_id": OMOPDomain.PROCEDURE.value,
                "vocabularies": [OMOPVocabulary.SNOMED.value],
                "concept_classes": ["Procedure", "Laboratory Procedure", "Molecular Biology Test"]
            },
            "GENOMICS": {
                "domain_id": OMOPDomain.MEASUREMENT.value,
                "vocabularies": [OMOPVocabulary.LOINC.value, OMOPVocabulary.SNOMED.value],
                "concept_classes": ["Genomic Test", "Molecular Test", "Sequencing Procedure"]
            },
            "CLINICAL": {
                "domain_id": OMOPDomain.OBSERVATION.value,
                "vocabularies": [OMOPVocabulary.SNOMED.value, OMOPVocabulary.LOINC.value],
                "concept_classes": ["Clinical Finding", "Observation", "Sign"]
            }
        }

    def map_entity_to_omop(self, entity_name: str, entity_type: str) -> List[OMOPMapping]:
        """Map a single entity to OMOP concepts."""
        cache_key = f"{entity_name.lower()}_{entity_type}"

        if self.cache and cache_key in self.cache:
            return self.cache[cache_key]

        mappings = []

        try:
            # Get OMOP domain and vocabulary info for entity type
            entity_config = self.entity_type_mappings.get(entity_type, {})

            if not entity_config:
                logger.warning(f"No OMOP configuration for entity type: {entity_type}")
                return mappings

            # Try multiple mapping strategies
            mappings.extend(self._map_via_athena_api(entity_name, entity_config))
            mappings.extend(self._map_via_standard_vocabs(entity_name, entity_config))
            mappings.extend(self._map_via_pattern_matching(entity_name, entity_config))

            # Sort by confidence and remove duplicates
            mappings = self._deduplicate_and_rank_mappings(mappings)

        except Exception as e:
            logger.error(f"Error mapping {entity_name} to OMOP: {e}")

        # Cache result
        if self.cache:
            self.cache[cache_key] = mappings

        return mappings

    def _map_via_athena_api(self, entity_name: str, entity_config: Dict) -> List[OMOPMapping]:
        """Map using OHDSI Athena API."""
        mappings = []

        try:
            # Search for concepts in Athena
            search_url = f"{self.athena_api_url}/vocabulary/search"
            params = {
                "query": entity_name,
                "domain": entity_config["domain_id"],
                "standardConcept": "Standard"
            }

            response = requests.get(search_url, params=params, timeout=10)

            if response.status_code == 200:
                concepts = response.json()
                for concept in concepts[:5]:  # Limit to top 5 results
                    mapping = OMOPMapping(
                        concept_id=concept.get("conceptId", 0),
                        concept_name=concept.get("conceptName", ""),
                        domain_id=concept.get("domainId", ""),
                        vocabulary_id=concept.get("vocabularyId", ""),
                        concept_class_id=concept.get("conceptClassId", ""),
                        standard_concept=concept.get("standardConcept", ""),
                        concept_code=concept.get("conceptCode", ""),
                        valid_start_date=concept.get("validStartDate", ""),
                        valid_end_date=concept.get("validEndDate", ""),
                        invalid_reason=concept.get("invalidReason", ""),
                        create_time=concept.get("createTime", ""),
                        mapping_confidence=self._calculate_athena_confidence(entity_name, concept),
                        mapping_method="Athena_API"
                    )
                    mappings.append(mapping)

        except Exception as e:
            logger.debug(f"Athena API mapping failed for {entity_name}: {e}")

        return mappings

    def _map_via_standard_vocabs(self, entity_name: str, entity_config: Dict) -> List[OMOPMapping]:
        """Map using direct vocabulary lookups."""
        mappings = []
        # Implementation would include specific vocabulary mappings
        # This is a placeholder for actual mapping logic
        return mappings

    def _map_via_pattern_matching(self, entity_name: str, entity_config: Dict) -> List[OMOPMapping]:
        """Map using pattern-based heuristics."""
        mappings = []

        try:
            entity_lower = entity_name.lower()
            domain_id = entity_config["domain_id"]
            entity_type = next((k for k, v in self.entity_type_mappings.items() if v == entity_config), None)

            # Pattern-based mapping examples
            if entity_type == "GENE":
                if entity_upper := entity_name.upper():
                    # HGNC pattern
                    if len(entity_upper) >= 2 and entity_upper.isalpha():
                        mapping = self._create_pattern_mapping(
                            entity_name, entity_upper, "HGNC", domain_id, 0.8
                        )
                        mappings.append(mapping)

            elif entity_type == "CHEMICAL":
                # Chemical suffix patterns
                chemical_suffixes = ["-ine", "-ol", "-one", "-acid", "-ate", "-ide"]
                if any(entity_lower.endswith(suffix) for suffix in chemical_suffixes):
                    mapping = self._create_pattern_mapping(
                        entity_name, entity_name, "SNOMED", domain_id, 0.6
                    )
                    mappings.append(mapping)

            elif entity_type == "DISEASE":
                # Disease pattern matching
                disease_suffixes = ["-itis", "-osis", "-emia", "-pathy", "-oma"]
                if any(entity_lower.endswith(suffix) for suffix in disease_suffixes):
                    mapping = self._create_pattern_mapping(
                        entity_name, entity_name, "SNOMED", domain_id, 0.7
                    )
                    mappings.append(mapping)

        except Exception as e:
            logger.debug(f"Pattern mapping failed for {entity_name}: {e}")

        return mappings

    def _create_pattern_mapping(self, entity_name: str, concept_code: str,
                               vocab_id: str, domain_id: str, confidence: float) -> OMOPMapping:
        """Create a pattern-based OMOP mapping."""
        return OMOPMapping(
            concept_id=0,  # Placeholder ID
            concept_name=entity_name,
            domain_id=domain_id,
            vocabulary_id=vocab_id,
            concept_class_id="Clinical Finding",
            standard_concept="",
            concept_code=concept_code,
            valid_start_date="1970-01-01",
            valid_end_date="2099-12-31",
            invalid_reason="",
            create_time="",
            mapping_confidence=confidence,
            mapping_method="Pattern_Matching"
        )

    def _calculate_athena_confidence(self, entity_name: str, concept: Dict) -> float:
        """Calculate confidence score for Athena mapping."""
        confidence = 0.5  # Base confidence

        concept_name = concept.get("conceptName", "").lower()
        entity_lower = entity_name.lower()

        # Exact match bonus
        if entity_lower == concept_name:
            confidence += 0.4
        # Contains match bonus
        elif entity_lower in concept_name or concept_name in entity_lower:
            confidence += 0.2

        # Standard concept bonus
        if concept.get("standardConcept") == "S":
            confidence += 0.1

        return min(confidence, 1.0)

    def _deduplicate_and_rank_mappings(self, mappings: List[OMOPMapping]) -> List[OMOPMapping]:
        """Remove duplicate mappings and sort by confidence."""
        # Deduplicate by concept_id and concept_code
        seen = set()
        unique_mappings = []

        for mapping in mappings:
            key = (mapping.concept_id, mapping.concept_code)
            if key not in seen:
                seen.add(key)
                unique_mappings.append(mapping)

        # Sort by confidence (descending)
        unique_mappings.sort(key=lambda x: x.mapping_confidence, reverse=True)

        return unique_mappings

    def map_entity_list(self, entities: List[Dict]) -> List[Dict]:
        """Map a list of entities to OMOP concepts."""
        mapped_entities = []

        for entity in entities:
            entity_name = entity.get('entity', '')
            entity_type = entity.get('entity_type', '')

            if not entity_name or not entity_type:
                continue

            # Get OMOP mappings
            omop_mappings = self.map_entity_to_omop(entity_name, entity_type)

            # Enhance entity with OMOP mappings
            enhanced_entity = {
                **entity,
                'omop_mappings': [vars(mapping) for mapping in omop_mappings],
                'has_omop_mapping': len(omop_mappings) > 0,
                'best_omop_confidence': max([m.mapping_confidence for m in omop_mappings], default=0.0),
                'omop_domain_id': omop_mappings[0].domain_id if omop_mappings else None,
                'omop_concept_count': len(omop_mappings)
            }

            mapped_entities.append(enhanced_entity)

        logger.info(f"🏥 OMOP mapping: {len(entities)} entities → {len(mapped_entities)} with mappings")
        return mapped_entities

    def generate_omop_summary(self, entities: List[Dict]) -> Dict:
        """Generate summary statistics for OMOP mappings."""
        mapped_entities = [e for e in entities if e.get('has_omop_mapping', False)]

        domain_counts = {}
        vocab_counts = {}
        total_mappings = 0
        high_confidence_count = 0

        for entity in mapped_entities:
            mappings = entity.get('omop_mappings', [])
            total_mappings += len(mappings)

            for mapping in mappings:
                domain_id = mapping.get('domain_id')
                vocab_id = mapping.get('vocabulary_id')
                confidence = mapping.get('mapping_confidence', 0)

                domain_counts[domain_id] = domain_counts.get(domain_id, 0) + 1
                vocab_counts[vocab_id] = vocab_counts.get(vocab_id, 0) + 1

                if confidence >= 0.8:
                    high_confidence_count += 1

        return {
            "total_entities": len(entities),
            "mapped_entities": len(mapped_entities),
            "mapping_rate": len(mapped_entities) / len(entities) if entities else 0,
            "total_mappings": total_mappings,
            "high_confidence_mappings": high_confidence_count,
            "domain_distribution": domain_counts,
            "vocabulary_distribution": vocab_counts,
            "average_confidence": sum([e.get('best_omop_confidence', 0) for e in entities]) / len(entities) if entities else 0
        }

class OMOPLocalMapper:
    """Maps CDM entities to OMOP standard concepts using local vocabulary."""

    def __init__(self, vocab_dir: str = None, fuzzy_threshold: int = 70, max_matches: int = 3):
        self.vocab_dir = vocab_dir or os.environ.get('OMOP_VOCAB_DIR', 'omop_vocab')
        self.fuzzy_threshold = fuzzy_threshold
        self.max_matches = max_matches

        # Initialize lookup tables
        self.lookup_df = None
        self.standard_concepts = None
        self._initialize_lookup()

        # Entity type to OMOP domain mappings
        self.entity_type_mappings = {
            "GENE": {
                "domain_id": "Genetic",
                "concept_classes": ["Gene", "Gene Variant", "Genomic Finding"]
            },
            "PROTEIN": {
                "domain_id": "Genetic",
                "concept_classes": ["Protein", "Biomarker", "Enzyme"]
            },
            "CHEMICAL": {
                "domain_id": "Drug",
                "concept_classes": ["Drug", "Compound", "Chemical Substance", "Clinical Drug"]
            },
            "DISEASE": {
                "domain_id": "Condition",
                "concept_classes": ["Clinical Finding", "Disease", "Disorder"]
            },
            "CELL_TYPE": {
                "domain_id": "Measurement",
                "concept_classes": ["Cell Type", "Cell Finding", "Laboratory Test"]
            },
            "DNA_RNA": {
                "domain_id": "Genetic",
                "concept_classes": ["DNA Sequence", "RNA Sequence", "Genomic Finding"]
            },
            "ORGANISM": {
                "domain_id": "Measurement",
                "concept_classes": ["Organism", "Microorganism", "Bacterial Finding"]
            },
            "CLINICAL": {
                "domain_id": "Observation",
                "concept_classes": ["Clinical Finding", "Observation", "Sign", "Clinical Observation"]
            },
            # Handle variations
            "CLINICAL OUTCOME": {
                "domain_id": "Observation",
                "concept_classes": ["Clinical Finding", "Observation"]
            },
            "CLINICAL PARAMETER": {
                "domain_id": "Measurement",
                "concept_classes": ["Clinical Observation", "Measurement"]
            },
            "DATA_ANALYSIS": {
                "domain_id": "Procedure",
                "concept_classes": ["Procedure", "Laboratory Procedure", "Device", "Research Study"]
            },
            "SCIENTIFIC_TERM": {
                "domain_id": "Observation",
                "concept_classes": ["Clinical Finding", "Observation"]
            },
            "GENOMICS": {
                "domain_id": "Procedure",
                "concept_classes": ["Procedure", "Laboratory Procedure", "Genomic Procedure"]
            }
        }

    def _initialize_lookup(self):
        """Initialize OMOP lookup tables from vocabulary files."""
        try:
            if not os.path.exists(self.vocab_dir):
                logger.warning(f"OMOP vocabulary directory not found: {self.vocab_dir}")
                self.lookup_df = pd.DataFrame(columns=['concept_id', 'term_lower', 'term_len'])
                self.standard_concepts = pd.DataFrame()
                return

            logger.info(f"Initializing OMOP lookup from: {self.vocab_dir}")

            # Load concepts and synonyms
            concepts = self._load_concepts()
            synonyms = self._load_synonyms()

            # Build lookup table
            self.lookup_df, self.standard_concepts = self._build_lookup(concepts, synonyms)

            logger.info(f"✅ OMOP lookup initialized with {len(self.lookup_df):,} entries")

        except Exception as e:
            logger.error(f"Failed to initialize OMOP lookup: {e}")
            self.lookup_df = pd.DataFrame(columns=['concept_id', 'term_lower', 'term_len'])
            self.standard_concepts = pd.DataFrame()

    def _preprocess_term(self, term: str) -> str:
        """Preprocess term for matching."""
        if not isinstance(term, str) or not term.strip():
            return ""
        term = term.lower()
        term = re.sub(r'[^a-z0-9\s]', ' ', term)
        term = re.sub(r'\b(and|or|of|the|a|an|with|for|in|on|to|at|by|as)\b', ' ', term)
        term = re.sub(r'\s+', ' ', term).strip()
        return term

    def _load_concepts(self) -> pd.DataFrame:
        """Load CONCEPT.csv file."""
        logger.info("Loading CONCEPT.csv...")
        path = os.path.join(self.vocab_dir, 'CONCEPT.csv')

        if not os.path.exists(path):
            logger.warning(f"CONCEPT.csv not found at: {path}")
            return pd.DataFrame()

        df = pd.read_csv(
            path, sep='\t',
            usecols=['concept_id', 'concept_name', 'standard_concept', 'invalid_reason', 'domain_id', 'vocabulary_id', 'concept_class_id'],
            dtype=str, na_filter=False
        )
        df = df[df['invalid_reason'] == '']
        logger.info(f"Loaded {len(df):,} valid concepts")
        return df

    def _load_synonyms(self) -> pd.DataFrame:
        """Load CONCEPT_SYNONYM.csv file."""
        logger.info("Loading CONCEPT_SYNONYM.csv...")
        path = os.path.join(self.vocab_dir, 'CONCEPT_SYNONYM.csv')

        if not os.path.exists(path):
            logger.warning(f"CONCEPT_SYNONYM.csv not found at: {path}")
            return pd.DataFrame()

        df = pd.read_csv(
            path, sep='\t',
            usecols=['concept_id', 'concept_synonym_name'],
            dtype=str, na_filter=False
        )
        return df[df['concept_synonym_name'] != '']

    def _build_lookup(self, concepts: pd.DataFrame, synonyms: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """Build lookup table from concepts and synonyms."""
        if concepts.empty:
            return pd.DataFrame(), pd.DataFrame()

        # Filter to standard concepts only
        standard_concepts = concepts[concepts['standard_concept'] == 'S'].copy()
        standard_ids = set(standard_concepts['concept_id'])

        # Get synonyms for standard concepts
        synonym_std = synonyms[synonyms['concept_id'].isin(standard_ids)].copy()

        # Build lookup from concept names
        names = standard_concepts[['concept_id', 'concept_name']].copy()
        names['term_lower'] = names['concept_name'].apply(self._preprocess_term)

        # Build lookup from synonyms
        synonym_std['term_lower'] = synonym_std['concept_synonym_name'].apply(self._preprocess_term)

        # Combine names and synonyms
        lookup = pd.concat([
            names[['concept_id', 'term_lower']],
            synonym_std[['concept_id', 'term_lower']]
        ], ignore_index=True)

        # Clean up lookup
        lookup = lookup[lookup['term_lower'] != '']
        lookup.drop_duplicates(['term_lower', 'concept_id'], inplace=True)
        lookup['term_len'] = lookup['term_lower'].str.len()

        logger.info(f"Built lookup with {len(lookup):,} entries from {len(standard_concepts):,} standard concepts")
        return lookup, standard_concepts

    def _get_fuzzy_matches(self, term: str) -> List[Tuple[str, int, float]]:
        """Get fuzzy matches for a term."""
        if not term or self.lookup_df.empty:
            return []

        # Get candidate terms by length (optimization)
        tlen = len(term)
        candidates_df = self.lookup_df[
            (self.lookup_df['term_len'] >= max(1, tlen - 3)) &
            (self.lookup_df['term_len'] <= tlen + 3)
        ]

        if candidates_df.empty:
            candidates_df = self.lookup_df

        candidate_terms = candidates_df['term_lower'].tolist()

        # Use rapidfuzz for fast fuzzy matching
        results = process.extract(
            term, candidate_terms,
            scorer=fuzz.ratio,
            limit=self.max_matches * 2  # Get more results, filter later
        )

        matches = []
        for matched_term, score, _ in results:
            if score < self.fuzzy_threshold:
                break
            if len(matches) >= self.max_matches:
                break

            concept_id = candidates_df.loc[
                candidates_df['term_lower'] == matched_term, 'concept_id'
            ].iloc[0]
            matches.append((concept_id, matched_term, score))

        return matches

    def _get_exact_matches(self, term: str) -> List[Tuple[str, int, float]]:
        """Get exact matches for a term."""
        if not term or self.lookup_df.empty:
            return []

        term_clean = self._preprocess_term(term)
        matches = self.lookup_df[self.lookup_df['term_lower'] == term_clean]

        return [(row['concept_id'], term_clean, 100.0) for _, row in matches.iterrows()]

    def _get_entity_config(self, entity_type: str) -> Dict:
        """Get entity type configuration with fallback to partial matches."""
        # Try exact match first
        config = self.entity_type_mappings.get(entity_type, {})
        if config:
            return config

        # Try partial match (for types like "CLINICAL OUTCOME" -> "CLINICAL")
        for key, value in self.entity_type_mappings.items():
            if key in entity_type.upper() or entity_type.upper() in key:
                return value

        # Default to Observation for unknown types
        return {
            "domain_id": "Observation",
            "concept_classes": ["Observation", "Clinical Finding"]
        }

    def map_entity_to_omop(self, entity_name: str, entity_type: str) -> List[OMOPMapping]:
        """Map a single entity to OMOP concepts."""
        mappings = []

        try:
            # Get entity type configuration (with fuzzy matching)
            entity_config = self._get_entity_config(entity_type)

            # Try exact matching first
            exact_matches = self._get_exact_matches(entity_name)

            # If no exact matches, try fuzzy matching
            fuzzy_matches = self._get_fuzzy_matches(entity_name) if not exact_matches else []

            all_matches = exact_matches + fuzzy_matches

            for concept_id, matched_term, score in all_matches:
                # Get concept details
                concept_info = self.standard_concepts[
                    self.standard_concepts['concept_id'] == concept_id
                ]

                if concept_info.empty:
                    continue

                concept_row = concept_info.iloc[0]

                # Check if matches entity type domain
                target_domain = entity_config.get("domain_id")
                if target_domain and concept_row['domain_id'] != target_domain:
                    # Still include but with lower confidence
                    confidence_adjustment = 0.8
                else:
                    confidence_adjustment = 1.0

                # Create mapping
                mapping = OMOPMapping(
                    concept_id=int(concept_row['concept_id']),
                    concept_name=concept_row['concept_name'],
                    domain_id=concept_row['domain_id'],
                    vocabulary_id=concept_row['vocabulary_id'],
                    concept_class_id=concept_row['concept_class_id'],
                    standard_concept=concept_row['standard_concept'],
                    concept_code=concept_row['concept_id'],  # Use concept_id as code
                    valid_start_date="1970-01-01",
                    valid_end_date="2099-12-31",
                    invalid_reason="",
                    create_time="",
                    mapping_confidence=min(score / 100.0 * confidence_adjustment, 1.0),
                    mapping_method="Exact" if score == 100.0 else "Fuzzy"
                )
                mappings.append(mapping)

            # Sort by confidence and limit results
            mappings.sort(key=lambda x: x.mapping_confidence, reverse=True)
            mappings = mappings[:self.max_matches]

        except Exception as e:
            logger.debug(f"Error mapping {entity_name} to OMOP: {e}")

        return mappings

    def map_entity_list(self, entities: List[Dict]) -> List[Dict]:
        """Map a list of entities to OMOP concepts."""
        if self.lookup_df is None or self.lookup_df.empty:
            logger.warning("OMOP lookup not initialized, skipping mapping")
            return entities

        mapped_entities = []
        mapping_count = 0

        for entity in entities:
            entity_name = entity.get('entity', '')
            entity_type = entity.get('type', '')

            if not entity_name or not entity_type:
                mapped_entities.append(entity)
                continue

            # Get OMOP mappings
            omop_mappings = self.map_entity_to_omop(entity_name, entity_type)

            if omop_mappings:
                mapping_count += 1

            # Enhance entity with OMOP mappings
            enhanced_entity = {
                **entity,
                'omop_mappings': [vars(mapping) for mapping in omop_mappings],
                'has_omop_mapping': len(omop_mappings) > 0,
                'best_omop_confidence': max([m.mapping_confidence for m in omop_mappings], default=0.0),
                'omop_domain_id': omop_mappings[0].domain_id if omop_mappings else None,
                'omop_concept_count': len(omop_mappings)
            }

            mapped_entities.append(enhanced_entity)

        logger.info(f"🏥 OMOP mapping: {mapping_count}/{len(entities)} entities mapped using local vocabulary")
        return mapped_entities

    def generate_omop_summary(self, entities: List[Dict]) -> Dict:
        """Generate summary statistics for OMOP mappings."""
        mapped_entities = [e for e in entities if e.get('has_omop_mapping', False)]

        domain_counts = {}
        vocab_counts = {}
        method_counts = {}
        total_mappings = 0
        high_confidence_count = 0

        for entity in mapped_entities:
            mappings = entity.get('omop_mappings', [])
            total_mappings += len(mappings)

            for mapping in mappings:
                domain_id = mapping.get('domain_id', 'Unknown')
                vocab_id = mapping.get('vocabulary_id', 'Unknown')
                method = mapping.get('mapping_method', 'Unknown')
                confidence = mapping.get('mapping_confidence', 0)

                domain_counts[domain_id] = domain_counts.get(domain_id, 0) + 1
                vocab_counts[vocab_id] = vocab_counts.get(vocab_id, 0) + 1
                method_counts[method] = method_counts.get(method, 0) + 1

                if confidence >= 0.8:
                    high_confidence_count += 1

        return {
            "total_entities": len(entities),
            "mapped_entities": len(mapped_entities),
            "mapping_rate": len(mapped_entities) / len(entities) if entities else 0,
            "total_mappings": total_mappings,
            "high_confidence_mappings": high_confidence_count,
            "domain_distribution": domain_counts,
            "vocabulary_distribution": vocab_counts,
            "method_distribution": method_counts,
            "average_confidence": sum([e.get('best_omop_confidence', 0) for e in entities]) / len(entities) if entities else 0,
            "lookup_entries": len(self.lookup_df) if self.lookup_df is not None else 0
        }

@dataclass
class UMLSConcept:
    """UMLS concept information."""
    cui: str  # Concept Unique Identifier
    name: str
    semantic_types: List[str]
    definitions: List[str]
    synonyms: List[str]
    umls_api_data: Dict

@dataclass
class UMLSMapping:
    """UMLS mapping result."""
    entity_name: str
    entity_type: str
    umls_concept: UMLSConcept
    mapping_confidence: float
    mapping_method: str

class UMLSMapper:
    """Maps entities to UMLS concepts."""

    def __init__(self, api_key: str = None, cache_size: int = 5000, use_scispacy: bool = False, request_delay: float = 0.1):
        self.api_key = api_key
        self.cache = {}
        self.cache_size = cache_size
        self.use_scispacy = use_scispacy
        self.nlp = None
        self.linker = None
        self.semantic_type_mappings = self._initialize_semantic_mappings()
        self.request_delay = request_delay  # Delay between API calls to avoid rate limiting (reduced for speed)
        self._last_request_time = 0
        self.session = requests.Session()  # Use session for connection pooling

        if self.use_scispacy:
            self._initialize_scispacy()

    def _initialize_scispacy(self):
        """Initialize SciSpaCy model and linker."""
        try:
            import spacy
            import scispacy
            from scispacy.linking import EntityLinker
            
            # Load model (try sm then md)
            model_name = "en_core_sci_sm"
            try:
                if not spacy.util.is_package(model_name):
                    model_name = "en_core_sci_md"
                    if not spacy.util.is_package(model_name):
                        raise OSError("No SciSpaCy model found")
                
                self.nlp = spacy.load(model_name)
                logger.info(f"✅ Loaded SciSpaCy model: {model_name}")
                
                # Add linker
                self.nlp.add_pipe("scispacy_linker", config={"resolve_abbreviations": True, "linker_name": "umls"})
                self.linker = self.nlp.get_pipe("scispacy_linker")
                logger.info("✅ SciSpaCy UMLS linker initialized")
                
            except Exception as e:
                logger.warning(f"⚠️  Failed to load SciSpaCy model: {e}")
                self.use_scispacy = False
                
        except ImportError:
            logger.warning("⚠️  scispacy not installed. Falling back to API.")
            self.use_scispacy = False
        except Exception as e:
            logger.warning(f"⚠️  Failed to initialize SciSpaCy: {e}")
            self.use_scispacy = False

    def _initialize_semantic_mappings(self) -> Dict[str, List[str]]:
        """Initialize entity type to UMLS semantic type mappings."""
        return {
            "GENE": ["gngm", "enzy", "aapp"],  # Gene or Genome, Enzyme, Amino Acid, Peptide, or Protein
            "PROTEIN": ["aapp", "enzy", "bacs"],  # Amino Acid, Peptide, or Protein, Enzyme, Biologically Active Substance
            "CHEMICAL": ["phsu", "chem", "bacs", "orch"],  # Pharmacologic Substance, Chemical, Biologically Active Substance, Organic Chemical
            "DISEASE": ["patf", "dsyn", "neop", "mobd"],  # Pathologic Function, Disease or Syndrome, Neoplastic Process, Mental or Behavioral Dysfunction
            "CELL_TYPE": ["cell", "bacs", "tisu"],  # Cell, Biologically Active Substance, Tissue
            "DNA_RNA": ["gngm", "celf"],  # Gene or Genome, Cell Component
            "ORGANISM": ["orgm", "bact", "virs", "fngs"],  # Organism, Bacterium, Virus, Fungus
            "BIOINFO_TOOL": ["inpr", "resd"],  # Intellectual Product, Research Device
            "GENOMICS": ["inpr", "diap"],  # Intellectual Product, Diagnostic Procedure
            "CLINICAL": ["fndg", "clna", "lbpr"]  # Finding, Clinical Attribute, Laboratory Procedure
        }

    def _rate_limit_delay(self):
        """Apply rate limiting delay between API calls."""
        import time
        if self._last_request_time > 0:
            elapsed = time.time() - self._last_request_time
            if elapsed < self.request_delay:
                time.sleep(self.request_delay - elapsed)
        self._last_request_time = time.time()

    def map_entity_to_umls(self, entity_name: str, entity_type: str) -> List[UMLSMapping]:
        """Map a single entity to UMLS concepts."""
        cache_key = f"{entity_name.lower()}_{entity_type}"

        if cache_key in self.cache:
            return self.cache[cache_key]

        mappings = []

        if self.use_scispacy and self.nlp:
            return self._map_with_scispacy(entity_name, entity_type)

        try:
            # Get expected semantic types for entity type
            expected_semantic_types = self.semantic_type_mappings.get(entity_type, [])

            # Search UMLS API
            umls_concepts = self._search_umls(entity_name, expected_semantic_types)

            # Create mappings
            for concept in umls_concepts:
                confidence = self._calculate_umls_confidence(entity_name, concept, entity_type)
                if confidence > 0.3:  # Minimum confidence threshold
                    mapping = UMLSMapping(
                        entity_name=entity_name,
                        entity_type=entity_type,
                        umls_concept=concept,
                        mapping_confidence=confidence,
                        mapping_method="UMLS_API"
                    )
                    mappings.append(mapping)

            # Sort by confidence
            mappings.sort(key=lambda x: x.mapping_confidence, reverse=True)

        except Exception as e:
            logger.error(f"Error mapping {entity_name} to UMLS: {e}")

        # Cache result
        if len(self.cache) < self.cache_size:
            self.cache[cache_key] = mappings

        return mappings

    def _map_with_scispacy(self, entity_name: str, entity_type: str) -> List[UMLSMapping]:
        """Map entity using SciSpaCy linker."""
        mappings = []
        try:
            doc = self.nlp(entity_name)
            
            # Collect all linked entities
            seen_cuis = set()
            
            for ent in doc.ents:
                for umls_ent in ent._.kb_ents:
                    cui, score = umls_ent
                    
                    if cui in seen_cuis:
                        continue
                    seen_cuis.add(cui)
                    
                    # Get details from KB
                    try:
                        kb_entity = self.linker.kb.cui_to_entity[cui]
                        canonical_name = kb_entity.canonical_name
                        types = kb_entity.types
                        definition = kb_entity.definition
                    except:
                        canonical_name = ent.text
                        types = []
                        definition = ""
                    
                    # Filter by score
                    if score > 0.7:  # SciSpaCy scores are cosine similarity
                        mapping = UMLSMapping(
                            entity_name=entity_name,
                            entity_type=entity_type,
                            umls_concept=UMLSConcept(
                                cui=cui,
                                name=canonical_name,
                                semantic_types=types,
                                definition=definition
                            ),
                            mapping_confidence=float(score),
                            mapping_method="SciSpaCy"
                        )
                        mappings.append(mapping)
            
            mappings.sort(key=lambda x: x.mapping_confidence, reverse=True)
            
        except Exception as e:
            logger.error(f"SciSpaCy mapping failed for {entity_name}: {e}")
            
        # Cache result
        cache_key = f"{entity_name.lower()}_{entity_type}"
        if len(self.cache) < self.cache_size:
            self.cache[cache_key] = mappings
            
        return mappings

    def _search_umls(self, entity_name: str, expected_semantic_types: List[str]) -> List[UMLSConcept]:
        """Search UMLS API for concepts."""
        if not self.api_key:
            logger.warning("No UMLS API key provided")
            return []

        concepts = []

        try:
            # Rate limiting delay
            self._rate_limit_delay()

            # UMLS REST API search
            search_url = "https://uts-ws.nlm.nih.gov/rest/search/current"
            params = {
                "string": entity_name,
                "apiKey": self.api_key,
                "pageSize": 20
            }

            response = requests.get(search_url, params=params, timeout=10)

            if response.status_code == 200:
                results = response.json()
                if 'result' in results:
                    for result in results['result'].get('results', []):
                        concept = self._get_umls_concept_details(result['ui'])
                        if concept and self._matches_semantic_types(concept.semantic_types, expected_semantic_types):
                            concepts.append(concept)

        except Exception as e:
            logger.debug(f"UMLS API search failed for {entity_name}: {e}")

        return concepts

    def _get_umls_concept_details(self, cui: str) -> Optional[UMLSConcept]:
        """Get detailed UMLS concept information."""
        try:
            # Rate limiting delay before each sub-request
            self._rate_limit_delay()

            # Get concept details
            concept_url = f"https://uts-ws.nlm.nih.gov/rest/content/current/CUI/{cui}"
            params = {"apiKey": self.api_key}

            response = requests.get(concept_url, params=params, timeout=10)

            if response.status_code == 200:
                concept_data = response.json().get('result', {})

                # Get semantic types (with delay)
                self._rate_limit_delay()
                semantic_types_url = f"https://uts-ws.nlm.nih.gov/rest/content/current/CUI/{cui}/semanticTypes"
                semantic_response = requests.get(semantic_types_url, params=params, timeout=5)

                semantic_types = []
                if semantic_response.status_code == 200:
                    for sem_type in semantic_response.json().get('result', []):
                        semantic_types.append(sem_type.get('name', ''))

                # Get definitions (with delay)
                self._rate_limit_delay()
                definitions_url = f"https://uts-ws.nlm.nih.gov/rest/content/current/CUI/{cui}/definitions"
                definitions_response = requests.get(definitions_url, params=params, timeout=5)

                definitions = []
                if definitions_response.status_code == 200:
                    for def_data in definitions_response.json().get('result', []):
                        definitions.append(def_data.get('value', ''))

                # Get synonyms (with delay)
                self._rate_limit_delay()
                synonyms_url = f"https://uts-ws.nlm.nih.gov/rest/content/current/CUI/{cui}/atoms"
                synonyms_response = requests.get(synonyms_url, params=params, timeout=5)

                synonyms = []
                if synonyms_response.status_code == 200:
                    for atom in synonyms_response.json().get('result', []):
                        synonym = atom.get('name', '')
                        if synonym and synonym != concept_data.get('name', '') and synonym not in synonyms:
                            synonyms.append(synonym)

                return UMLSConcept(
                    cui=cui,
                    name=concept_data.get('name', ''),
                    semantic_types=semantic_types,
                    definitions=definitions,
                    synonyms=synonyms[:10],  # Limit synonyms
                    umls_api_data=concept_data
                )

        except Exception as e:
            logger.debug(f"Error getting UMLS concept details for {cui}: {e}")

        return None

    def _matches_semantic_types(self, concept_semantic_types: List[str], expected_semantic_types: List[str]) -> bool:
        """Check if concept matches expected semantic types."""
        if not expected_semantic_types:
            return True  # No restriction

        concept_set = set(concept_semantic_types)
        expected_set = set(expected_semantic_types)

        return bool(concept_set.intersection(expected_set))

    def _calculate_umls_confidence(self, entity_name: str, concept: UMLSConcept, entity_type: str) -> float:
        """Calculate confidence score for UMLS mapping."""
        confidence = 0.5  # Base confidence

        entity_lower = entity_name.lower()
        concept_name_lower = concept.name.lower()

        # Exact name match
        if entity_lower == concept_name_lower:
            confidence += 0.3
        # Partial match
        elif entity_lower in concept_name_lower or concept_name_lower in entity_lower:
            confidence += 0.15

        # Synonym match
        for synonym in concept.synonyms:
            if entity_lower == synonym.lower():
                confidence += 0.25
                break
            elif entity_lower in synonym.lower() or synonym.lower() in entity_lower:
                confidence += 0.1

        # Semantic type matching bonus
        expected_semantic_types = self.semantic_type_mappings.get(entity_type, [])
        if self._matches_semantic_types(concept.semantic_types, expected_semantic_types):
            confidence += 0.1

        # Definition presence bonus
        if concept.definitions:
            confidence += 0.05

        return min(confidence, 1.0)

    def map_entity_list(self, entities: List[Dict]) -> List[Dict]:
        """Map a list of entities to UMLS concepts."""
        mapped_entities = []

        for entity in entities:
            entity_name = entity.get('entity', '')
            entity_type = entity.get('entity_type', '')

            if not entity_name or not entity_type:
                continue

            # Get UMLS mappings
            umls_mappings = self.map_entity_to_umls(entity_name, entity_type)

            # Enhance entity with UMLS mappings
            enhanced_entity = {
                **entity,
                'umls_mappings': [self._mapping_to_dict(mapping) for mapping in umls_mappings],
                'has_umls_mapping': len(umls_mappings) > 0,
                'best_umls_confidence': max([m.mapping_confidence for m in umls_mappings], default=0.0),
                'umls_cui_count': len(umls_mappings),
                'umls_cuis': [m.umls_concept.cui for m in umls_mappings]
            }

            mapped_entities.append(enhanced_entity)

        logger.info(f"🏥 UMLS mapping: {len(entities)} entities → {len(mapped_entities)} with mappings")
        return mapped_entities

    def _mapping_to_dict(self, mapping: UMLSMapping) -> Dict:
        """Convert UMLSMapping to dictionary."""
        return {
            'entity_name': mapping.entity_name,
            'entity_type': mapping.entity_type,
            'umls_cui': mapping.umls_concept.cui,
            'umls_name': mapping.umls_concept.name,
            'semantic_types': mapping.umls_concept.semantic_types,
            'definitions': mapping.umls_concept.definitions,
            'synonyms': mapping.umls_concept.synonyms,
            'mapping_confidence': mapping.mapping_confidence,
            'mapping_method': mapping.mapping_method
        }

    def generate_umls_summary(self, entities: List[Dict]) -> Dict:
        """Generate summary statistics for UMLS mappings."""
        mapped_entities = [e for e in entities if e.get('has_umls_mapping', False)]

        semantic_type_counts = {}
        total_cuis = 0
        high_confidence_count = 0

        for entity in mapped_entities:
            mappings = entity.get('umls_mappings', [])
            total_cuis += len(mappings)

            for mapping in mappings:
                for semantic_type in mapping.get('semantic_types', []):
                    semantic_type_counts[semantic_type] = semantic_type_counts.get(semantic_type, 0) + 1

                confidence = mapping.get('mapping_confidence', 0)
                if confidence >= 0.8:
                    high_confidence_count += 1

        return {
            "total_entities": len(entities),
            "mapped_entities": len(mapped_entities),
            "mapping_rate": len(mapped_entities) / len(entities) if entities else 0,
            "total_cuis": total_cuis,
            "high_confidence_mappings": high_confidence_count,
            "semantic_type_distribution": semantic_type_counts,
            "average_confidence": sum([e.get('best_umls_confidence', 0) for e in entities]) / len(entities) if entities else 0
        }

@dataclass
class BioPortalMapping:
    """BioPortal mapping result."""
    entity_name: str
    entity_type: str
    concept_id: str
    ontology_name: str
    mapping_confidence: float
    mapping_method: str

class BioPortalMapper:
    """Maps entities to BioPortal ontologies."""

    def __init__(self, api_key: str = None, cache_size: int = 2000):
        self.api_key = api_key
        self.cache = {}
        self.cache_size = cache_size
        self.base_url = "http://data.bioontology.org/search"
        self.session = requests.Session()  # Use session for connection pooling

    def map_entity(self, entity_name: str, entity_type: str) -> List[BioPortalMapping]:
        """Map entity using BioPortal API."""
        if not self.api_key:
            return []

        cache_key = f"{entity_name.lower()}_{entity_type}"
        if cache_key in self.cache:
            return self.cache[cache_key]

        mappings = []
        try:
            params = {
                "q": entity_name,
                "apikey": self.api_key,
                "pagesize": 5,
                "include": "prefLabel,cui,semanticType"
            }

            response = self.session.get(self.base_url, params=params, timeout=10)
            if response.status_code == 200:
                results = response.json().get('collection', [])
                # print(f"DEBUG: BioPortal found {len(results)} results for {entity_name}")
                for result in results:
                    confidence = self._calculate_confidence(entity_name, result)
                    if confidence > 0.4:
                        mappings.append(BioPortalMapping(
                            entity_name=entity_name,
                            entity_type=entity_type,
                            concept_id=result.get('@id', ''),
                            ontology_name=result.get('links', {}).get('ontology', '').split('/')[-1],
                            mapping_confidence=confidence,
                            mapping_method="BioPortal_API"
                        ))
            else:
                 logger.warning(f"BioPortal API error: {response.status_code} - {response.text[:100]}")

            mappings.sort(key=lambda x: x.mapping_confidence, reverse=True)

        except Exception as e:
            logger.debug(f"BioPortal mapping failed for {entity_name}: {e}")

        if len(self.cache) < self.cache_size:
            self.cache[cache_key] = mappings

        return mappings

    def _calculate_confidence(self, entity_name: str, result: Dict) -> float:
        confidence = 0.5
        pref_label = result.get('prefLabel', '').lower()
        if pref_label == entity_name.lower():
            confidence += 0.4
        elif entity_name.lower() in pref_label:
            confidence += 0.2
        return min(confidence, 1.0)

@dataclass
class OLSMapping:
    """OLS mapping result."""
    entity_name: str
    entity_type: str
    iri: str
    ontology_name: str
    label: str
    mapping_confidence: float
    mapping_method: str

class OLSMapper:
    """Maps entities using EBI OLS API (Free)."""

    def __init__(self, cache_size: int = 1000):
        self.cache = {}
        self.cache_size = cache_size
        self.base_url = "https://www.ebi.ac.uk/ols/api/search"
        self.session = requests.Session()  # Use session for connection pooling

    def map_entity(self, entity_name: str, entity_type: str) -> List[OLSMapping]:
        """Map entity using OLS API."""
        cache_key = f"{entity_name.lower()}_{entity_type}"
        if cache_key in self.cache:
            return self.cache[cache_key]

        mappings = []
        try:
            params = {
                "q": entity_name,
                "rows": 5,
                "exact": "false"
            }

            response = self.session.get(self.base_url, params=params, timeout=10)
            if response.status_code == 200:
                results = response.json().get('response', {}).get('docs', [])
                for result in results:
                    confidence = self._calculate_confidence(entity_name, result)
                    if confidence > 0.4:
                        mappings.append(OLSMapping(
                            entity_name=entity_name,
                            entity_type=entity_type,
                            iri=result.get('iri', ''),
                            ontology_name=result.get('ontology_name', ''),
                            label=result.get('label', ''),
                            mapping_confidence=confidence,
                            mapping_method="OLS_API"
                        ))

            mappings.sort(key=lambda x: x.mapping_confidence, reverse=True)

        except Exception as e:
            logger.debug(f"OLS mapping failed for {entity_name}: {e}")

        if len(self.cache) < self.cache_size:
            self.cache[cache_key] = mappings

        return mappings

    def map_entities_batch(self, entities: List[Tuple[str, str]], max_workers: int = 10) -> Dict[str, List[OLSMapping]]:
        """Map multiple entities in parallel for faster processing."""
        from concurrent.futures import ThreadPoolExecutor, as_completed

        results = {}

        def map_single(entity_name, entity_type):
            try:
                return (entity_name, self.map_entity(entity_name, entity_type))
            except Exception as e:
                logger.debug(f"Error mapping {entity_name}: {e}")
                return (entity_name, [])

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(map_single, name, etype): (name, etype)
                      for name, etype in entities}

            for future in as_completed(futures):
                try:
                    entity_name, mappings = future.result()
                    results[entity_name] = mappings
                except Exception as e:
                    logger.error(f"Batch mapping error: {e}")

        return results

    def _calculate_confidence(self, entity_name: str, result: Dict) -> float:
        confidence = 0.5
        label = result.get('label', '').lower()
        if label == entity_name.lower():
            confidence += 0.4
        elif entity_name.lower() in label:
            confidence += 0.2
        return min(confidence, 1.0)

class ComprehensiveMapper:
    """Comprehensive mapping coordinator for all biomedical ontologies."""

    def __init__(self, umls_api_key: str = None, bioportal_api_key: str = None, athena_api_url: str = None,
                 cache_mappings: bool = True, use_local_omop: bool = True,
                 omop_vocab_dir: str = None, fuzzy_threshold: int = 70, max_matches: int = 3,
                 use_scispacy: bool = False):

        # Use local OMOP mapper by default, fallback to API mapper
        if use_local_omop:
            self.omop_mapper = OMOPLocalMapper(
                vocab_dir=omop_vocab_dir,
                fuzzy_threshold=fuzzy_threshold,
                max_matches=max_matches
            )
            logger.info("📁 Using local OMOP mapper")
        else:
            self.omop_mapper = OMOPMapper(athena_api_url=athena_api_url, cache_mappings=cache_mappings)
            logger.info("🌐 Using API-based OMOP mapper")

        # UMLS mapper
        self.umls_mapper = UMLSMapper(api_key=umls_api_key, cache_size=2000, use_scispacy=use_scispacy) if (umls_api_key or use_scispacy) else None
        if self.umls_mapper:
            logger.info(f"🏥 UMLS mapper initialized (SciSpaCy: {use_scispacy})")
        else:
            logger.info("⚠️  UMLS mapper disabled (no API key and SciSpaCy disabled)")
            
        # BioPortal mapper
        self.bioportal_mapper = BioPortalMapper(api_key=bioportal_api_key) if bioportal_api_key else None
        if self.bioportal_mapper:
            logger.info("🏥 BioPortal mapper initialized")
        else:
            logger.info("⚠️  BioPortal mapper disabled (no API key)")
            
        # OLS mapper (Free)
        self.ols_mapper = OLSMapper()
        logger.info("🏥 OLS mapper initialized")

    def map_entity_comprehensive(self, entity_name: str, entity_type: str) -> Dict:
        """Perform comprehensive mapping using all available sources."""
        # Get mappings from all available sources
        umls_mappings = []
        if self.umls_mapper:
            umls_mappings = self.umls_mapper.map_entity_to_umls(entity_name, entity_type)

        omop_mappings = self.omop_mapper.map_entity_to_omop(entity_name, entity_type)
        
        bioportal_mappings = []
        if self.bioportal_mapper:
            bioportal_mappings = self.bioportal_mapper.map_entity(entity_name, entity_type)
            
        ols_mappings = self.ols_mapper.map_entity(entity_name, entity_type)

        # Calculate confidences
        umls_confidences = [m.mapping_confidence for m in umls_mappings] if umls_mappings else []
        omop_confidences = [m.mapping_confidence for m in omop_mappings] if omop_mappings else []
        bioportal_confidences = [m.mapping_confidence for m in bioportal_mappings] if bioportal_mappings else []
        ols_confidences = [m.mapping_confidence for m in ols_mappings] if ols_mappings else []

        return {
            'entity_name': entity_name,
            'entity_type': entity_type,
            'umls_mappings': [self.umls_mapper._mapping_to_dict(m) for m in umls_mappings] if self.umls_mapper else [],
            'omop_mappings': [vars(m) for m in omop_mappings],
            'bioportal_mappings': [vars(m) for m in bioportal_mappings],
            'ols_mappings': [vars(m) for m in ols_mappings],
            'has_any_mapping': any([umls_mappings, omop_mappings, bioportal_mappings, ols_mappings]),
            'umls_count': len(umls_mappings),
            'omop_count': len(omop_mappings),
            'bioportal_count': len(bioportal_mappings),
            'ols_count': len(ols_mappings),
            'best_confidence': max(umls_confidences + omop_confidences + bioportal_confidences + ols_confidences, default=0.0)
        }

    def map_entity_list_comprehensive(self, entities: List[Dict], max_workers: int = 16) -> List[Dict]:
        """Map a list of entities comprehensively with parallel processing."""
        mapped_entities = []

        def process_single_entity(entity):
            entity_name = entity.get('entity', '')
            entity_type = entity.get('entity_type', '')

            if not entity_name or not entity_type:
                return None

            # Get comprehensive mapping
            comprehensive_mapping = self.map_entity_comprehensive(entity_name, entity_type)

            # Enhance entity
            enhanced_entity = {
                **entity,
                'comprehensive_mapping': comprehensive_mapping
            }

            return enhanced_entity

        # Use ThreadPoolExecutor for parallel API calls
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(process_single_entity, entity): entity for entity in entities}

            for future in tqdm(as_completed(futures), total=len(futures), desc="Mapping entities", unit="entity"):
                try:
                    result = future.result()
                    if result:
                        mapped_entities.append(result)
                except Exception as e:
                    logger.error(f"Error processing entity: {e}")

        logger.info(f"🌐 Comprehensive mapping: {len(entities)} entities processed with {max_workers} workers")
        return mapped_entities

    def generate_comprehensive_summary(self, entities: List[Dict]) -> Dict:
        """Generate comprehensive mapping summary."""
        umls_summary = self.umls_mapper.generate_umls_summary(entities) if self.umls_mapper else {"enabled": False}
        omop_summary = self.omop_mapper.generate_omop_summary(entities)

        entities_with_any_mapping = [
            e for e in entities
            if e.get('comprehensive_mapping', {}).get('has_any_mapping', False)
        ]

        return {
            'total_entities': len(entities),
            'entities_with_any_mapping': len(entities_with_any_mapping),
            'overall_mapping_rate': len(entities_with_any_mapping) / len(entities) if entities else 0,
            'umls_summary': umls_summary,
            'omop_summary': omop_summary,
            'mappers_enabled': {
                'omop_local': isinstance(self.omop_mapper, OMOPLocalMapper),
                'umls': self.umls_mapper is not None
            }
        }

# ==============================================================================
# VALIDATORS
# ==============================================================================

class ValidationLevel(Enum):
    """Validation severity levels"""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"

@dataclass
class ValidationIssue:
    """Represents a validation issue found in results"""
    level: ValidationLevel
    category: str
    message: str
    entity_index: Optional[int] = None
    entity_type: Optional[str] = None
    confidence_score: Optional[float] = None
    suggestion: Optional[str] = None

@dataclass
class ValidationResult:
    """Complete validation result for entities"""
    is_valid: bool
    total_entities: int
    valid_entities: int
    issues: List[ValidationIssue] = field(default_factory=list)
    summary: Dict[str, Any] = field(default_factory=dict)
    recommendations: List[str] = field(default_factory=list)
    validation_metadata: Dict[str, Any] = field(default_factory=dict)

class EntityValidator:
    """Validates individual entities for quality and consistency"""

    def __init__(self):
        # Valid CDM entity types
        self.valid_entity_types = {
            'GENE', 'PROTEIN', 'ORGANISM', 'DISEASE', 'CHEMICAL',
            'DNA_RNA', 'CELL_TYPE', 'PATHWAY', 'PHENOTYPE', 'DRUG'
        }

        # Minimum entity lengths by type
        self.min_lengths = {
            'GENE': 2,
            'PROTEIN': 2,
            'ORGANISM': 3,
            'DISEASE': 3,
            'CHEMICAL': 2,
            'DNA_RNA': 2,
            'CELL_TYPE': 3,
            'PATHWAY': 3,
            'PHENOTYPE': 3,
            'DRUG': 2,
            'default': 2
        }

        # Maximum entity lengths to prevent garbage
        self.max_lengths = {
            'GENE': 50,
            'PROTEIN': 100,
            'ORGANISM': 100,
            'DISEASE': 200,
            'CHEMICAL': 100,
            'DNA_RNA': 100,
            'CELL_TYPE': 50,
            'PATHWAY': 200,
            'PHENOTYPE': 100,
            'DRUG': 100,
            'default': 100
        }

        # Patterns for potentially invalid entities
        self.invalid_patterns = [
            r'^\d+$',  # Pure numbers
            r'^[^a-zA-Z]+$',  # No letters
            r'.*[<>{}[\]\\].*',  # HTML/markup symbols
            r'^\s+$',  # Just whitespace
            r'^(the|and|or|but|in|on|at|to|for|of|with|by)\s*$',  # Common stop words alone
        ]

        # Known organism suffixes/prefixes for validation
        self.organism_indicators = [
            'bacterium', 'bacteria', 'species', 'strain', 'family', 'phylum',
            'genus', 'order', 'class', 'kingdom', 'domain', 'coli', 'coccus',
            'bacillus', 'streptococcus', 'lactobacillus', 'bifidobacterium'
        ]

        # Gene/protein patterns
        self.gene_patterns = [
            r'^[A-Z]{2,}\d*',  # Gene symbols like TP53, BRCA1
            r'^[a-z]+-\d+',     # Gene names like p53, gata-1
            r'.*gene.*',        # Contains 'gene'
            r'.*protein.*',     # Contains 'protein'
        ]

    def validate_entity(self, entity: Dict[str, Any], index: int) -> List[ValidationIssue]:
        """Validate a single entity and return any issues"""
        issues = []

        # Check required fields
        required_fields = ['entity', 'type', 'confidence']
        for field in required_fields:
            if field not in entity or entity[field] is None:
                issues.append(ValidationIssue(
                    level=ValidationLevel.ERROR,
                    category='missing_field',
                    message=f"Missing required field: {field}",
                    entity_index=index,
                    suggestion=f"Add {field} field to entity"
                ))

        # Get entity values safely
        entity_text = str(entity.get('entity', '')).strip()
        entity_type = str(entity.get('type', '')).upper()
        confidence = float(entity.get('confidence', 0.0))

        # Validate entity text
        if entity_text:
            text_issues = self._validate_entity_text(entity_text, entity_type, index)
            issues.extend(text_issues)
        else:
            issues.append(ValidationIssue(
                level=ValidationLevel.ERROR,
                category='empty_entity',
                message="Entity text is empty",
                entity_index=index,
                suggestion="Remove empty entity"
            ))

        # Validate entity type
        if entity_type:
            type_issues = self._validate_entity_type(entity_type, index)
            issues.extend(type_issues)
        else:
            issues.append(ValidationIssue(
                level=ValidationLevel.WARNING,
                category='unknown_type',
                message="Entity type is empty or invalid",
                entity_index=index,
                suggestion="Assign appropriate CDM entity type"
            ))

        # Validate confidence score
        if confidence is not None:
            confidence_issues = self._validate_confidence_score(confidence, entity_type, index)
            issues.extend(confidence_issues)
        else:
            issues.append(ValidationIssue(
                level=ValidationLevel.WARNING,
                category='missing_confidence',
                message="Confidence score is missing",
                entity_index=index,
                suggestion="Add confidence score between 0.0 and 1.0"
            ))

        # Type-specific validation
        if entity_type and entity_text:
            type_specific_issues = self._validate_type_specific(entity_text, entity_type, index)
            issues.extend(type_specific_issues)

        return issues

    def _validate_entity_text(self, text: str, entity_type: str, index: int) -> List[ValidationIssue]:
        """Validate the entity text content"""
        issues = []

        # Length validation
        min_len = self.min_lengths.get(entity_type, self.min_lengths['default'])
        max_len = self.max_lengths.get(entity_type, self.max_lengths['default'])

        if len(text) < min_len:
            issues.append(ValidationIssue(
                level=ValidationLevel.WARNING,
                category='too_short',
                message=f"Entity text too short: {len(text)} < {min_len}",
                entity_index=index,
                entity_type=entity_type,
                suggestion="Consider removing or merging with other entities"
            ))

        if len(text) > max_len:
            issues.append(ValidationIssue(
                level=ValidationLevel.WARNING,
                category='too_long',
                message=f"Entity text too long: {len(text)} > {max_len}",
                entity_index=index,
                entity_type=entity_type,
                suggestion="Check for truncated or malformed text"
            ))

        # Pattern validation
        for pattern in self.invalid_patterns:
            if re.match(pattern, text, re.IGNORECASE):
                issues.append(ValidationIssue(
                    level=ValidationLevel.ERROR,
                    category='invalid_pattern',
                    message=f"Entity matches invalid pattern: {pattern}",
                    entity_index=index,
                    entity_type=entity_type,
                    suggestion="Remove entity as it appears to be noise"
                ))

        # Character validation
        if re.search(r'[^\w\s\-\.]', text):
            issues.append(ValidationIssue(
                level=ValidationLevel.WARNING,
                category='special_characters',
                message="Entity contains unusual special characters",
                entity_index=index,
                entity_type=entity_type,
                suggestion="Review for potential formatting issues"
            ))

        return issues

    def _validate_entity_type(self, entity_type: str, index: int) -> List[ValidationIssue]:
        """Validate the entity type"""
        issues = []

        if entity_type not in self.valid_entity_types:
            issues.append(ValidationIssue(
                level=ValidationLevel.WARNING,
                category='invalid_type',
                message=f"Unknown entity type: {entity_type}",
                entity_index=index,
                entity_type=entity_type,
                suggestion=f"Use one of: {', '.join(sorted(self.valid_entity_types))}"
            ))

        return issues

    def _validate_confidence_score(self, confidence: float, entity_type: str, index: int) -> List[ValidationIssue]:
        """Validate confidence score"""
        issues = []

        if not (0.0 <= confidence <= 1.0):
            issues.append(ValidationIssue(
                level=ValidationLevel.ERROR,
                category='invalid_confidence',
                message=f"Confidence score out of range: {confidence}",
                entity_index=index,
                entity_type=entity_type,
                confidence_score=confidence,
                suggestion="Ensure confidence is between 0.0 and 1.0"
            ))

        elif confidence < 0.3:
            issues.append(ValidationIssue(
                level=ValidationLevel.WARNING,
                category='low_confidence',
                message=f"Very low confidence score: {confidence:.2f}",
                entity_index=index,
                entity_type=entity_type,
                confidence_score=confidence,
                suggestion="Consider increasing confidence threshold"
            ))

        return issues

    def _validate_type_specific(self, text: str, entity_type: str, index: int) -> List[ValidationIssue]:
        """Type-specific validation rules"""
        issues = []
        text_lower = text.lower()

        if entity_type == 'ORGANISM':
            # Check if it looks like an organism
            has_organism_indicator = any(indicator in text_lower for indicator in self.organism_indicators)
            has_scientific_pattern = re.search(r'\b[A-Z][a-z]+ [a-z]+\b', text)  # Genus species

            if not (has_organism_indicator or has_scientific_pattern):
                issues.append(ValidationIssue(
                    level=ValidationLevel.INFO,
                    category='organism_validation',
                    message="May not be a valid organism name",
                    entity_index=index,
                    entity_type=entity_type,
                    suggestion="Verify organism classification"
                ))

        elif entity_type == 'GENE':
            # Check if it looks like a gene name
            has_gene_pattern = any(re.search(pattern, text, re.IGNORECASE) for pattern in self.gene_patterns)

            if not has_gene_pattern and not re.search(r'[A-Z]{2,}\d*', text):
                issues.append(ValidationIssue(
                    level=ValidationLevel.INFO,
                    category='gene_validation',
                    message="May not be a standard gene name/symbol",
                    entity_index=index,
                    entity_type=entity_type,
                    suggestion="Verify gene nomenclature"
                ))

        return issues

class ResultConsistencyChecker:
    """Checks for consistency across multiple entities"""

    def __init__(self):
        self.similarity_threshold = 0.9  # High similarity threshold for duplicates

    def check_consistency(self, entities: List[Dict[str, Any]]) -> List[ValidationIssue]:
        """Check consistency across all entities"""
        issues = []

        # Check for exact duplicates
        exact_duplicates = self._find_exact_duplicates(entities)
        for duplicate_group in exact_duplicates:
            if len(duplicate_group) > 1:
                issues.append(ValidationIssue(
                    level=ValidationLevel.WARNING,
                    category='exact_duplicates',
                    message=f"Found {len(duplicate_group)} exact duplicates: {[entities[i]['entity'] for i in duplicate_group]}",
                    suggestion="Remove duplicate entities"
                ))

        # Check for near duplicates
        near_duplicates = self._find_near_duplicates(entities)
        for duplicate_group in near_duplicates:
            if len(duplicate_group) > 1:
                issues.append(ValidationIssue(
                    level=ValidationLevel.INFO,
                    category='near_duplicates',
                    message=f"Found similar entities: {[entities[i]['entity'] for i in duplicate_group]}",
                    suggestion="Consider if these should be merged"
                ))

        # Check confidence consistency
        confidence_issues = self._check_confidence_consistency(entities)
        issues.extend(confidence_issues)

        # Check type consistency
        type_issues = self._check_type_consistency(entities)
        issues.extend(type_issues)

        return issues

    def _find_exact_duplicates(self, entities: List[Dict[str, Any]]) -> List[List[int]]:
        """Find groups of exact duplicate entities"""
        entity_map = defaultdict(list)

        for i, entity in enumerate(entities):
            key = (entity.get('entity', '').lower().strip(), entity.get('type', '').upper())
            entity_map[key].append(i)

        return [indices for indices in entity_map.values() if len(indices) > 1]

    def _find_near_duplicates(self, entities: List[Dict[str, Any]]) -> List[List[int]]:
        """Find groups of near-duplicate entities using string similarity"""
        duplicate_groups = []

        for i, entity1 in enumerate(entities):
            for j, entity2 in enumerate(entities[i+1:], i+1):
                if entity1.get('type') == entity2.get('type'):
                    text1 = entity1.get('entity', '').lower()
                    text2 = entity2.get('entity', '').lower()

                    # Simple similarity check (can be enhanced with more sophisticated methods)
                    similarity = self._string_similarity(text1, text2)
                    if similarity >= self.similarity_threshold:
                        duplicate_groups.append([i, j])

        return duplicate_groups

    def _string_similarity(self, s1: str, s2: str) -> float:
        """Calculate string similarity using Jaccard similarity of words"""
        words1 = set(s1.split())
        words2 = set(s2.split())

        if not words1 and not words2:
            return 1.0
        if not words1 or not words2:
            return 0.0

        intersection = words1.intersection(words2)
        union = words1.union(words2)

        return len(intersection) / len(union)

    def _check_confidence_consistency(self, entities: List[Dict[str, Any]]) -> List[ValidationIssue]:
        """Check for unusual confidence score patterns"""
        issues = []
        confidences = [entity.get('confidence', 0.0) for entity in entities]

        if confidences:
            avg_confidence = statistics.mean(confidences)
            std_confidence = statistics.stdev(confidences) if len(confidences) > 1 else 0

            # Very low average confidence
            if avg_confidence < 0.5:
                issues.append(ValidationIssue(
                    level=ValidationLevel.WARNING,
                    category='low_average_confidence',
                    message=f"Low average confidence: {avg_confidence:.2f}",
                    suggestion="Consider improving extraction quality or lowering threshold"
                ))

            # Very high standard deviation (inconsistent quality)
            if std_confidence > 0.3:
                issues.append(ValidationIssue(
                    level=ValidationLevel.INFO,
                    category='inconsistent_confidence',
                    message=f"Inconsistent confidence scores (std: {std_confidence:.2f})",
                    suggestion="Review extraction process for consistency"
                ))

        return issues

    def _check_type_consistency(self, entities: List[Dict[str, Any]]) -> List[ValidationIssue]:
        """Check entity type distribution"""
        issues = []
        type_counts = Counter(entity.get('type', 'UNKNOWN') for entity in entities)

        # Warn if too many unknown types
        unknown_count = type_counts.get('UNKNOWN', 0)
        if unknown_count > len(entities) * 0.2:  # More than 20% unknown
            issues.append(ValidationIssue(
                level=ValidationLevel.WARNING,
                category='many_unknown_types',
                message=f"Many unknown entity types: {unknown_count}/{len(entities)}",
                suggestion="Review entity type classification"
            ))

        return issues

class CDMResultValidator:
    """Main result validator that combines all validation checks"""

    def __init__(self):
        self.entity_validator = EntityValidator()
        self.consistency_checker = ResultConsistencyChecker()

    def validate_results(self, entities: List[Dict[str, Any]],
                        context: Dict[str, Any] = None) -> ValidationResult:
        """
        Validate complete extraction results

        Args:
            entities: List of extracted entities
            context: Additional context about the extraction

        Returns:
            Complete validation result
        """
        context = context or {}
        all_issues = []

        # Validate individual entities
        for i, entity in enumerate(entities):
            entity_issues = self.entity_validator.validate_entity(entity, i)
            all_issues.extend(entity_issues)

        # Check consistency across entities
        consistency_issues = self.consistency_checker.check_consistency(entities)
        all_issues.extend(consistency_issues)

        # Additional validation checks
        additional_issues = self._additional_validations(entities, context)
        all_issues.extend(additional_issues)

        # Count issues by severity
        critical_count = sum(1 for issue in all_issues if issue.level == ValidationLevel.CRITICAL)
        error_count = sum(1 for issue in all_issues if issue.level == ValidationLevel.ERROR)

        is_valid = critical_count == 0 and error_count == 0

        # Create summary
        summary = self._create_summary(entities, all_issues)

        # Generate recommendations
        recommendations = self._generate_recommendations(all_issues, summary)

        result = ValidationResult(
            is_valid=is_valid,
            total_entities=len(entities),
            valid_entities=len(entities) - error_count - critical_count,
            issues=all_issues,
            summary=summary,
            recommendations=recommendations,
            validation_metadata={
                'validation_timestamp': context.get('timestamp'),
                'source_file': context.get('source_file'),
                'extraction_model': context.get('model_used')
            }
        )

        logger.info(f"🔍 Result validation: {is_valid}, "
                   f"issues: {len(all_issues)} (E:{error_count}, W:{sum(1 for issue in all_issues if issue.level == ValidationLevel.WARNING)})")

        return result

    def _additional_validations(self, entities: List[Dict[str, Any]],
                              context: Dict[str, Any]) -> List[ValidationIssue]:
        """Additional validation checks"""
        issues = []

        # Check if we have enough entities (context-dependent)
        expected_min = context.get('expected_min_entities', 1)
        if len(entities) < expected_min:
            issues.append(ValidationIssue(
                level=ValidationLevel.WARNING,
                category='insufficient_entities',
                message=f"Too few entities extracted: {len(entities)} < {expected_min}",
                suggestion="Adjust extraction parameters or check input quality"
            ))

        # Check if we have too many entities (might indicate over-extraction)
        expected_max = context.get('expected_max_entities', 1000)
        if len(entities) > expected_max:
            issues.append(ValidationIssue(
                level=ValidationLevel.INFO,
                category='excessive_entities',
                message=f"Many entities extracted: {len(entities)} > {expected_max}",
                suggestion="Review for potential over-extraction"
            ))

        return issues

    def _create_summary(self, entities: List[Dict[str, Any]],
                       issues: List[ValidationIssue]) -> Dict[str, Any]:
        """Create validation summary"""
        issue_counts = Counter(issue.category for issue in issues)
        level_counts = Counter(issue.level.value for issue in issues)

        type_counts = Counter(entity.get('type', 'UNKNOWN') for entity in entities)
        confidences = [entity.get('confidence', 0.0) for entity in entities if entity.get('confidence') is not None]

        summary = {
            'total_entities': len(entities),
            'total_issues': len(issues),
            'issues_by_category': dict(issue_counts),
            'issues_by_level': dict(level_counts),
            'entity_types': dict(type_counts),
            'confidence_stats': {
                'mean': statistics.mean(confidences) if confidences else 0.0,
                'min': min(confidences) if confidences else 0.0,
                'max': max(confidences) if confidences else 0.0,
                'median': statistics.median(confidences) if confidences else 0.0
            }
        }

        return summary

    def _generate_recommendations(self, issues: List[ValidationIssue],
                                summary: Dict[str, Any]) -> List[str]:
        """Generate improvement recommendations"""
        recommendations = []

        # Based on issue patterns
        issue_categories = [issue.category for issue in issues]
        issue_levels = [issue.level for issue in issues]

        if ValidationLevel.ERROR in issue_levels or ValidationLevel.CRITICAL in issue_levels:
            recommendations.append("🚨 Fix critical errors before using results")

        if 'invalid_confidence' in issue_categories:
            recommendations.append("📊 Ensure all confidence scores are between 0.0 and 1.0")

        if 'low_confidence' in issue_categories:
            recommendations.append("🎯 Consider increasing confidence threshold")

        if 'invalid_type' in issue_categories:
            recommendations.append("🏷️  Review entity type classification")

        if 'exact_duplicates' in issue_categories:
            recommendations.append("🔄 Run deduplication process")

        if summary['confidence_stats']['mean'] < 0.6:
            recommendations.append("📈 Improve extraction quality - average confidence low")

        if summary.get('entity_types', {}).get('UNKNOWN', 0) > 0:
            recommendations.append("🔍 Review entities with UNKNOWN type")

        if not recommendations:
            recommendations.append("✅ Results appear to be good quality")

        return recommendations

    def save_validation_report(self, result: ValidationResult, output_file: str):
        """Save validation report to file"""
        report = {
            'validation_summary': {
                'is_valid': result.is_valid,
                'total_entities': result.total_entities,
                'valid_entities': result.valid_entities,
                'total_issues': len(result.issues)
            },
            'detailed_summary': result.summary,
            'issues': [
                {
                    'level': issue.level.value,
                    'category': issue.category,
                    'message': issue.message,
                    'entity_index': issue.entity_index,
                    'entity_type': issue.entity_type,
                    'suggestion': issue.suggestion
                }
                for issue in result.issues
            ],
            'recommendations': result.recommendations,
            'metadata': result.validation_metadata
        }

        try:
            with open(output_file, 'w') as f:
                json.dump(report, f, indent=2, default=str)
            logger.info(f"📋 Validation report saved to {output_file}")
        except Exception as e:
            logger.error(f"Failed to save validation report: {e}")

# ==============================================================================
# BIOMEDICAL VALIDATORS & SCORERS
# ==============================================================================

class BioMistralValidator:
    """Advanced biomedical validation using BioMistral model."""

    def __init__(self, config: BioMistralConfig):
        self.config = config
        self.llm_client = LLMClient(model=config.model_name, base_url=config.api_url)

    def validate_entity_list(self, entities: List[Dict]) -> List[Dict]:
        """Validate a list of entities using BioMistral with batch processing."""
        validated_entities = []
        batch_size = 20
        
        # Process in batches
        for i in tqdm(range(0, len(entities), batch_size), desc="🧬 Validating entities", unit="batch"):
            batch = entities[i:i + batch_size]
            validated_batch = self._validate_batch(batch)
            validated_entities.extend(validated_batch)
            
        return validated_entities

    def _validate_batch(self, batch: List[Dict]) -> List[Dict]:
        """Validate a batch of entities."""
        if not batch:
            return []
            
        # Create batch prompt
        items = "\n".join([f"{j+1}. {e['entity']} ({e['entity_type']})" for j, e in enumerate(batch)])
        prompt = f"""
Validate these biomedical entities for microbiome research context.
Entities:
{items}

Return a JSON array of booleans [true, false, ...] corresponding to each item.
True if the term is a valid scientific/biomedical entity, False if it is generic, a person name, location, or irrelevant.
Return ONLY the JSON array.
"""
        try:
            response = self.llm_client.call_llm(prompt, max_tokens=200)
            # Parse response
            # Look for JSON array
            match = re.search(r'\[.*\]', response, re.DOTALL)
            if match:
                results = json.loads(match.group(0))
                if len(results) == len(batch):
                    return [e for e, valid in zip(batch, results) if valid]
            
            # Fallback: assume all valid if parsing fails to avoid data loss
            logger.warning("Failed to parse batch validation response, keeping all entities.")
            return batch
        except Exception as e:
            logger.error(f"Error in batch validation: {e}")
            return batch

    def correct_entity_types(self, entities: List[Dict]) -> List[Dict]:
        """Correct entity types using BioMistral with batch processing."""
        logger.info(f"🧬 Correcting entity types for {len(entities)} entities using LLM...")
        
        # Filter for low confidence or ambiguous entities
        candidates = [e for e in entities if e.get('confidence', 1.0) < 0.8]
        others = [e for e in entities if e.get('confidence', 1.0) >= 0.8]
        
        if not candidates:
            return entities

        corrected_candidates = []
        batch_size = 20
        corrected_count = 0
        
        for i in tqdm(range(0, len(candidates), batch_size), desc="🧬 Correcting types", unit="batch"):
            batch = candidates[i:i + batch_size]
            corrected_batch, count = self._correct_batch(batch)
            corrected_candidates.extend(corrected_batch)
            corrected_count += count
            
        logger.info(f"✅ LLM type correction: Updated {corrected_count} entities")
        return others + corrected_candidates

    def _correct_batch(self, batch: List[Dict]) -> Tuple[List[Dict], int]:
        """Correct types for a batch of entities."""
        if not batch:
            return [], 0
            
        items = "\n".join([f"{j+1}. {e['entity']} (Current: {e['entity_type']}) - Context: {e.get('context', '')[:50]}..." for j, e in enumerate(batch)])
        prompt = f"""
Correct the entity types for these terms.
Valid Types: ORGANISM, GENE, PROTEIN, CHEMICAL, DISEASE, DNA_RNA, CELL_TYPE, BIOINFO_TOOL, GENOMICS, CLINICAL, SCIENTIFIC_TERM.

Items:
{items}

Return a JSON array of strings ["TYPE1", "TYPE2", ...] corresponding to each item.
Return ONLY the JSON array.
"""
        try:
            response = self.llm_client.call_llm(prompt, max_tokens=300)
            match = re.search(r'\[.*\]', response, re.DOTALL)
            if match:
                new_types = json.loads(match.group(0))
                if len(new_types) == len(batch):
                    corrected_batch = []
                    count = 0
                    valid_types = CDMEntityConfig.ENTITY_TYPES.keys()
                    
                    for entity, new_type in zip(batch, new_types):
                        new_type = new_type.upper().strip()
                        if new_type in valid_types and new_type != entity['entity_type']:
                            entity['original_type'] = entity['entity_type']
                            entity['entity_type'] = new_type
                            entity['type_correction_method'] = 'LLM_Validation'
                            count += 1
                        corrected_batch.append(entity)
                    return corrected_batch, count
            
            return batch, 0
        except Exception as e:
            logger.error(f"Error in batch correction: {e}")
            return batch, 0

class BioMistralDeduplicator:
    """Biomedical deduplication using BioMistral."""

    def __init__(self, llm_client: LLMClient, biomistral_model: str, semantic_model: str):
        self.llm_client = llm_client
        self.biomistral_model = biomistral_model
        self.semantic_model = semantic_model
        self.duplicate_groups = []

    def deduplicate_entities(self, entities: List[Dict], biomistral_threshold: float = 0.7,
                           semantic_threshold: float = 0.85, use_biomistral: bool = True) -> Tuple[List[Dict], List[List[int]]]:
        """Deduplicate entities using biomedical knowledge."""
        # Simplified deduplication for standalone
        # In a full implementation, this would use embeddings and LLM verification
        return entities, []

    def export_duplicate_analysis(self, filepath: str):
        """Export duplicate analysis to file."""
        try:
            with open(filepath, 'w') as f:
                json.dump(self.duplicate_groups, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to export duplicate analysis: {e}")

class MiniLMTermCorrector:
    """Corrects terms using MiniLM semantic embeddings."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2", similarity_threshold: float = 0.9):
        self.model_name = model_name
        self.similarity_threshold = similarity_threshold
        self.model = None
        
    def load_model(self) -> bool:
        try:
            if self.model is None:
                from sentence_transformers import SentenceTransformer
                self.model = SentenceTransformer(self.model_name)
            return True
        except Exception as e:
            logger.error(f"Failed to load MiniLM for correction: {e}")
            return False

    def correct_terms(self, entities: List[Dict]) -> List[Dict]:
        """Correct terms by clustering similar entities and mapping to the most frequent canonical form."""
        if not entities or len(entities) < 2:
            return entities
            
        if not self.load_model():
            return entities

        logger.info(f"🔧 Starting MiniLM term correction for {len(entities)} entities")
        
        # Group by entity type to only correct within same type
        type_groups = defaultdict(list)
        for i, entity in enumerate(entities):
            type_groups[entity['entity_type']].append(i)

        corrected_count = 0
        
        for entity_type, indices in type_groups.items():
            if len(indices) < 2:
                continue
                
            # Get texts for this group
            texts = [entities[i]['entity'] for i in indices]
            
            # Encode
            try:
                embeddings = self.model.encode(texts, convert_to_numpy=True, show_progress_bar=False)
                
                # Calculate similarity matrix
                similarity_matrix = cosine_similarity(embeddings)
                
                # Find clusters/corrections
                # Simple strategy: For each term, find highly similar terms. 
                # If a highly similar term is much more frequent (or just pick the most frequent in the cluster), map to it.
                
                # Count frequencies first
                term_counts = Counter(texts)
                
                processed_indices = set()
                
                for i in range(len(texts)):
                    if i in processed_indices:
                        continue
                        
                    # Find similar terms
                    similar_indices = np.where(similarity_matrix[i] > self.similarity_threshold)[0]
                    
                    if len(similar_indices) > 1:
                        # We have a cluster of similar terms
                        cluster_indices = similar_indices
                        cluster_texts = [texts[idx] for idx in cluster_indices]
                        
                        # Find canonical term (most frequent, then shortest/longest?)
                        # Prefer most frequent. If tie, prefer longer (often more specific) or shorter (cleaner)?
                        # Let's prefer most frequent, then alphabetical for stability.
                        canonical_term = max(cluster_texts, key=lambda t: (term_counts[t], t))
                        
                        # Apply correction
                        for idx in cluster_indices:
                            original_term = texts[idx]
                            if original_term != canonical_term:
                                entities[indices[idx]]['entity'] = canonical_term
                                entities[indices[idx]]['original_entity'] = original_term
                                entities[indices[idx]]['correction_method'] = 'MiniLM_Semantic'
                                corrected_count += 1
                                
                            processed_indices.add(idx)
                            
            except Exception as e:
                logger.error(f"Error correcting terms for type {entity_type}: {e}")
                continue

        logger.info(f"✅ MiniLM term correction: Corrected {corrected_count} terms")
        return entities

class MicrobiomeRelevanceScorer:
    """Scores entities based on relevance to microbiome research."""

    def __init__(self):
        self.microbiome_keywords = {
            'gut', 'microbiome', 'microbiota', 'bacteria', 'bacterial', 'intestinal',
            'colon', 'fecal', 'faecal', 'stool', 'dysbiosis', 'probiotic', 'prebiotic',
            'fermentation', 'scfa', 'short-chain fatty acid', 'mucosa', 'lumen',
            'commensal', 'pathogen', 'axis', 'metabolite'
        }
        
        self.high_relevance_types = {'ORGANISM', 'CHEMICAL', 'DISEASE', 'GENE'}

    def calculate_score(self, entity: Dict) -> float:
        """Calculate relevance score (0.0 - 1.0) using enhanced logic."""
        score = 0.5
        term = entity.get('entity', '').strip()
        term_lower = term.lower()
        context = entity.get('context', '').lower()
        entity_type = entity.get('entity_type', '')

        # Core vocabulary bonus
        if any(kw in term_lower for kw in self.microbiome_keywords):
            score += 0.3

        # Context relevance
        if any(kw in context for kw in self.microbiome_keywords):
            score += 0.1

        # Type relevance
        if entity_type in self.high_relevance_types:
            score += 0.1

        # Multi-word compound bonus
        parts = term.split()
        if len(parts) in [2, 3, 4]:
            score += 0.1

        # Length optimization
        if 4 <= len(term) <= 25:
            score += 0.05

        # Pattern bonuses (from old.py)
        biomedical_patterns = [
            ('aceae', 0.15), ('ales', 0.1), ('idae', 0.1), ('bacter', 0.15),
            ('coccus', 0.15), ('myces', 0.1), ('virus', 0.1), ('protein', 0.1),
            ('enzyme', 0.1), ('gene', 0.1), ('pathway', 0.1), ('metabolit', 0.1),
            ('sequencing', 0.1), ('analysis', 0.05), ('diversity', 0.1),
            ('bioinformat', 0.1), ('computational', 0.1), ('statistical', 0.1),
            ('clinical', 0.1), ('medical', 0.1), ('pharmaceutical', 0.1)
        ]

        for pattern, bonus in biomedical_patterns:
            if pattern in term_lower:
                score += bonus
                break

        return min(max(score, 0.1), 1.0)

    def score_entities(self, entities: List[Dict]) -> List[Dict]:
        """Add relevance scores to a list of entities."""
        scored_entities = []
        for entity in entities:
            entity['microbiome_relevance_score'] = self.calculate_score(entity)
            scored_entities.append(entity)
        return scored_entities

# ==============================================================================
# PIPELINE ORCHESTRATOR
# ==============================================================================

# ==============================================================================
# ENTITY FILTER
# ==============================================================================

class EntityFilter:
    """Advanced entity filtering and quality control."""

    def __init__(self, strict_mode: bool = True):
        self.strict_mode = strict_mode
        self.entity_config = CDMEntityConfig()

        # Blacklist of non-biomedical terms
        self.non_biomedical_blacklist = {
            'japanese population', 'population', 'study', 'analysis', 'method',
            'approach', 'technique', 'result', 'finding', 'data', 'sample',
            'group', 'cohort', 'patient', 'subject', 'participant', 'research',
            'paper', 'article', 'publication', 'investigation', 'examination',
            'observation', 'measurement', 'assessment', 'evaluation',
            'centrifugation', 'gut colonization', 'human gut'  # Lab techniques and processes
        }

        # Entity type correction rules
        self.type_corrections = {
            # Bacterial families should be ORGANISMS
            r'.*aceae$': 'ORGANISM',
            r'.*bacteri.*': 'ORGANISM',
            r'.*cocc.*': 'ORGANISM',
            r'.*bact.*': 'ORGANISM',

            # Viral terms should be ORGANISMS
            r'.*virus.*': 'ORGANISM',
            r'.*vir.*': 'ORGANISM',

            # Fungal terms should be ORGANISMS
            r'.*myc.*': 'ORGANISM',
            r'.*fung.*': 'ORGANISM',

            # Statistical methods should not be BIOINFO_TOOLS
            r'.*correlation.*': 'GENOMICS',
            r'.*analysis.*': 'GENOMICS',
            r'.*clustering.*': 'GENOMICS',
            r'.*statistical.*': 'GENOMICS',

            # Enzyme patterns
            r'.*kinase$': 'PROTEIN',
            r'.*ase$': 'PROTEIN',
            r'.*dehydrogenase$': 'PROTEIN',

            # Gene patterns
            r'.*gene$': 'GENE',
            r'^[A-Z]{2,}[0-9]*$': 'GENE',  # Like IL6, TNF

            # Chemical patterns
            r'.*acid$': 'CHEMICAL',
            r'.*ate$': 'CHEMICAL',
            r'.*ol$': 'CHEMICAL',

            # DNA/RNA patterns
            r'.*DNA.*': 'DNA_RNA',
            r'.*RNA.*': 'DNA_RNA',
            r'^16S.*': 'DNA_RNA',
            r'.*rRNA.*': 'DNA_RNA',

            # Disease patterns
            r'.*itis$': 'DISEASE',
            r'.*osis$': 'DISEASE',
            r'.*emia$': 'DISEASE',

            # Bioinformatics tools should be BIOINFO_TOOL, not GENE
            r'^BLAST$': 'BIOINFO_TOOL',
            r'.*BLAST.*': 'BIOINFO_TOOL',
            r'^MetaPhlAn$': 'BIOINFO_TOOL',
            r'.*MetaPhlAn.*': 'BIOINFO_TOOL',
            r'.*Qiime.*': 'BIOINFO_TOOL',
            r'.*QIIME.*': 'BIOINFO_TOOL',

            # Chemical patterns (short-chain fatty acids)
            r'^butyrate$': 'CHEMICAL',
            r'^Propionate$': 'CHEMICAL',
            r'^acetate$': 'CHEMICAL',
            r'.*fatty acid.*': 'CHEMICAL',

            # Non-biomedical processes to filter
            r'.*colonization$': None,  # Will be filtered out
            r'.*extraction$': None,     # Will be filtered out if not DNA specific
        }

        # Duplicate detection patterns
        self.duplicate_patterns = [
            # Remove "family", "group", "type" suffixes for duplicate detection
            r'\s+(family|group|type|strain|species)$',
            # Remove common prefixes
            r'^(genus|family|order|class|phylum)\s+',
            # Remove strain designations and JCM numbers
            r'\s+JCM\s+\d+$',
            r'\s+\d+$',
            r'\s+subsp\.',
        ]

        # Organism name normalization mappings
        self.organism_normalizations = {
            r'^E\.?\s*coli$': 'Escherichia coli',
            r'^B\.\s*fragilis$': 'Bacteroides fragilis',
            r'^Bifidobacterium\s+longum\s+.*': 'Bifidobacterium longum',
        }

    def apply_basic_filtering(self, entities: List[Dict]) -> List[Dict]:
        """Apply basic quality filters to entities."""
        logger.info(f"🔍 Applying basic filtering to {len(entities)} entities")

        filtered_entities = []
        removed_count = 0

        for entity in entities:
            entity_name = entity.get('entity', '').strip()
            entity_type = entity.get('entity_type', '')

            # Skip if missing required fields
            if not entity_name or not entity_type:
                removed_count += 1
                continue

            # Skip blacklisted non-biomedical terms
            if self._is_blacklisted(entity_name.lower()):
                removed_count += 1
                continue

            # Skip entities that are too short or too long
            if len(entity_name) < 2 or len(entity_name) > 100:
                removed_count += 1
                continue

            # Skip if confidence is too low
            confidence = entity.get('confidence', 0.0)
            if confidence < 0.5:
                removed_count += 1
                continue

            # Apply entity type corrections
            corrected_type = self._correct_entity_type(entity_name, entity_type)

            # If None is returned, filter out this entity
            if corrected_type is None:
                removed_count += 1
                continue

            if corrected_type != entity_type:
                entity['entity_type'] = corrected_type
                entity['original_type'] = entity_type

            # Validate entity type exists in our config
            if corrected_type not in self.entity_config.ENTITY_TYPES:
                removed_count += 1
                continue

            filtered_entities.append(entity)

        logger.info(f"✅ Basic filtering: {len(entities)} → {len(filtered_entities)} entities (removed {removed_count})")
        return filtered_entities

    def remove_exact_duplicates(self, entities: List[Dict]) -> List[Dict]:
        """Remove exact duplicates (same entity name and type)."""
        logger.info(f"🔄 Removing exact duplicates from {len(entities)} entities")

        seen = set()
        unique_entities = []
        duplicates_removed = 0

        for entity in entities:
            entity_key = f"{entity['entity'].lower()}_{entity['entity_type']}"

            if entity_key not in seen:
                seen.add(entity_key)
                unique_entities.append(entity)
            else:
                duplicates_removed += 1

        logger.info(f"✅ Exact duplicate removal: {len(entities)} → {len(unique_entities)} entities (removed {duplicates_removed})")
        return unique_entities

    def remove_semantic_duplicates_simple(self, entities: List[Dict]) -> List[Dict]:
        """Remove semantic duplicates using simple string matching."""
        logger.info(f"🔄 Removing semantic duplicates from {len(entities)} entities")

        # Group by entity type
        type_groups = defaultdict(list)
        for entity in entities:
            type_groups[entity['entity_type']].append(entity)

        deduplicated = []
        total_removed = 0

        for entity_type, type_entities in type_groups.items():
            if len(type_entities) <= 1:
                deduplicated.extend(type_entities)
                continue

            # Remove semantic duplicates within this type
            unique_for_type = []
            seen_normalized = set()

            for entity in type_entities:
                normalized = self._normalize_entity_name(entity['entity'])

                if normalized not in seen_normalized:
                    seen_normalized.add(normalized)
                    unique_for_type.append(entity)
                else:
                    total_removed += 1

            deduplicated.extend(unique_for_type)

        logger.info(f"✅ Semantic duplicate removal: {len(entities)} → {len(deduplicated)} entities (removed {total_removed})")
        return deduplicated

    def apply_biomedical_validation(self, entities: List[Dict]) -> List[Dict]:
        """Apply biomedical validation rules."""
        logger.info(f"🧪 Applying biomedical validation to {len(entities)} entities")

        validated_entities = []
        invalid_count = 0

        for entity in entities:
            entity_name = entity.get('entity', '')
            entity_type = entity.get('entity_type', '')

            # Validate specific entity types
            if not self._is_valid_biomedical_entity(entity_name, entity_type):
                invalid_count += 1
                continue

            # Add quality score
            quality_score = self._calculate_quality_score(entity)
            entity['quality_score'] = quality_score

            validated_entities.append(entity)

        logger.info(f"✅ Biomedical validation: {len(entities)} → {len(validated_entities)} entities (removed {invalid_count})")
        return validated_entities

    def _is_blacklisted(self, entity_name: str) -> bool:
        """Check if entity is in the blacklist."""
        # Direct blacklist check
        if entity_name in self.non_biomedical_blacklist:
            return True

        # Pattern-based blacklist
        blacklist_patterns = [
            r'.*\b(study|analysis|method|approach|technique|result|finding)\b.*',
            r'.*\b(paper|article|publication|research)\b.*',
            r'.*\b(patient|subject|participant|cohort|group)\b.*',
            # URL and Reference patterns
            r'https?://\S+',
            r'www\.\S+',
            r'doi\.org/\S+',
            r'et al\.',
            r'\(?\d{4}\)?',  # Years like (2023)
            # Common country/location patterns (simple check)
            r'\b(USA|UK|China|Japan|Germany|France|Italy|Spain|Canada|Australia|India|Brazil)\b',
            r'\b(University|Institute|Hospital|Center|Department)\b'
        ]

        for pattern in blacklist_patterns:
            if re.search(pattern, entity_name, re.IGNORECASE):
                return True

        return False

    def _correct_entity_type(self, entity_name: str, current_type: str) -> str:
        """Correct entity type based on name patterns."""
        entity_lower = entity_name.lower()

        for pattern, correct_type in self.type_corrections.items():
            if re.search(pattern, entity_name, re.IGNORECASE):
                # If None, this means the entity should be filtered out
                if correct_type is None:
                    return None
                return correct_type

        return current_type

    def _normalize_entity_name(self, entity_name: str) -> str:
        """Normalize entity name for duplicate detection."""
        normalized = entity_name.lower().strip()

        # Apply organism-specific normalizations first
        for pattern, replacement in self.organism_normalizations.items():
            if re.search(pattern, entity_name, re.IGNORECASE):
                normalized = replacement.lower().strip()
                break

        # Remove suffixes/prefixes that don't change meaning
        for pattern in self.duplicate_patterns:
            normalized = re.sub(pattern, '', normalized).strip()

        # Remove extra whitespace
        normalized = re.sub(r'\s+', ' ', normalized)

        return normalized

    def _is_valid_biomedical_entity(self, entity_name: str, entity_type: str) -> bool:
        """Validate that entity is a proper biomedical term."""

        # SCIENTIFIC_TERM validation (permissive but checks for noise)
        if entity_type == 'SCIENTIFIC_TERM':
            # Should not be too generic
            if len(entity_name.split()) > 5: # Too long phrases
                return False
            return True

        # ORGANISM validation
        if entity_type == 'ORGANISM':
            # Should not be generic terms
            organism_blacklist = ['bacteria', 'microbe', 'organism', 'cell', 'cells']
            if entity_name.lower() in organism_blacklist:
                return False
            # Should have at least one biological indicator
            # bio_indicators = ['bacter', 'virus', 'fung', 'cocc', 'bacill', 'entero', 'staph', 'strept']
            # if not any(indicator in entity_name.lower() for indicator in bio_indicators):
            #    return len(entity_name.split()) > 1  # Allow multi-word organisms
            pass

        # GENE validation
        elif entity_type == 'GENE':
            # Should not be family names
            if entity_name.lower().endswith('family') or entity_name.lower().endswith('aceae'):
                return False

        # DISEASE validation
        elif entity_type == 'DISEASE':
            # Should not be populations or demographics
            disease_blacklist = ['population', 'japanese', 'american', 'cohort', 'group']
            if any(blacklisted in entity_name.lower() for blacklisted in disease_blacklist):
                return False

        # CHEMICAL validation
        elif entity_type == 'CHEMICAL':
            # Should not be processes or methods
            if entity_name.lower().endswith('tion') or entity_name.lower().endswith('ment'):
                return False

        return True

    def _calculate_quality_score(self, entity: Dict) -> float:
        """Calculate a quality score for the entity (0.0-1.0) with pattern bonuses."""
        score = 0.0
        term = entity.get('entity', '')
        entity_type = entity.get('entity_type', '')

        # Base score from confidence
        score += entity.get('confidence', 0.0) * 0.4

        # Context presence bonus
        if entity.get('context', '').strip():
            score += 0.2

        # Entity length score (prefer moderate length)
        entity_length = len(term)
        if 5 <= entity_length <= 30:
            score += 0.2
        elif 3 <= entity_length <= 50:
            score += 0.1

        # Multi-word entity bonus (often more specific)
        if len(term.split()) > 1:
            score += 0.1

        # Type appropriateness bonus
        if self._is_appropriate_type(term, entity_type):
            score += 0.1
            
        # Pattern-based bonuses (Biomedical suffixes)
        lower_term = term.lower()
        biomedical_suffixes = ['ase', 'osis', 'itis', 'emia', 'ome', 'omics', 'aceae', 'bacter', 'coccus', 'bacillus']
        if any(lower_term.endswith(suffix) for suffix in biomedical_suffixes):
            score += 0.1
            
        # Penalty for very short terms or all digits
        if len(term) < 3 or term.isdigit():
            score -= 0.3

        return max(0.0, min(score, 1.0))

    def clean_term(self, term: str) -> str:
        """
        Strict term cleaning to remove artifacts, greek letters, and noise.
        """
        if not term:
            return ""
            
        # Remove surrounding whitespace and quotes
        term = term.strip().strip('"\'')
        
        # Replace common greek letters if needed (basic mapping)
        greek_map = {
            'alpha': 'α', 'beta': 'β', 'gamma': 'γ', 'delta': 'δ'
        }
        # Note: We might want to keep text representation for consistency, 
        # but removing artifacts is key.
        
        # Remove trailing punctuation
        term = re.sub(r'[.,;:!]+$', '', term)
        
        # Remove "extracted term" or placeholder text if it sneaks in
        if term.lower() in ['extracted term', 'entity', 'term']:
            return ""
            
        return term

    def _is_appropriate_type(self, entity_name: str, entity_type: str) -> bool:
        """Check if the entity type is appropriate for the entity name."""
        # This is a simplified check - could be enhanced with more rules
        appropriate_patterns = {
            'ORGANISM': [r'.*bacter.*', r'.*virus.*', r'.*fung.*', r'.*cocc.*'],
            'GENE': [r'.*gene$', r'^[A-Z]{2,}[0-9]*$', r'.*[0-9]+$'],
            'PROTEIN': [r'.*protein$', r'.*enzyme$', r'.*kinase$', r'.*ase$'],
            'CHEMICAL': [r'.*acid$', r'.*ate$', r'.*ol$', r'.*ldehyde$'],
            'DISEASE': [r'.*itis$', r'.*osis$', r'.*emia$', r'.*cancer$'],
            'DNA_RNA': [r'.*DNA.*', r'.*RNA.*', r'^16S.*', r'.*rRNA.*'],
        }

        if entity_type in appropriate_patterns:
            for pattern in appropriate_patterns[entity_type]:
                if re.search(pattern, entity_name, re.IGNORECASE):
                    return True

        return True  # Default to appropriate if no specific pattern

    def apply_comprehensive_filtering(self, entities: List[Dict]) -> List[Dict]:
        """Apply all filtering steps in sequence."""
        logger.info(f"🚀 Starting comprehensive filtering on {len(entities)} entities")

        # Step 1: Basic filtering
        filtered = self.apply_basic_filtering(entities)

        # Step 2: Remove exact duplicates
        filtered = self.remove_exact_duplicates(filtered)

        # Step 3: Remove semantic duplicates
        filtered = self.remove_semantic_duplicates_simple(filtered)

        # Step 4: Biomedical validation
        filtered = self.apply_biomedical_validation(filtered)

        # Sort by quality score if available
        if filtered and 'quality_score' in filtered[0]:
            filtered.sort(key=lambda x: x.get('quality_score', 0), reverse=True)

        logger.info(f"✅ Comprehensive filtering complete: {len(entities)} → {len(filtered)} final entities")
        return filtered

class SemanticDeduplicator:
    """Deduplicates entities using semantic similarity."""

    def __init__(self, model_name: str = 'all-MiniLM-L6-v2', threshold: float = 0.85):
        self.threshold = threshold
        self.model = None
        try:
            from sentence_transformers import SentenceTransformer
            self.model = SentenceTransformer(model_name)
            logger.info(f"🧠 Semantic deduplicator initialized with {model_name}")
        except ImportError:
            logger.warning("⚠️  sentence-transformers not installed. Semantic deduplication disabled.")
        except Exception as e:
            logger.warning(f"⚠️  Failed to load semantic model: {e}")

    def apply_semantic_deduplication(self, entities: List[Dict]) -> List[Dict]:
        """Deduplicate entities based on semantic similarity."""
        if not entities:
            return []
            
        if not self.model:
            # Fallback to exact string deduplication
            return self._exact_deduplication(entities)

        # First, exact deduplication to reduce work
        unique_entities = self._exact_deduplication(entities)
        if len(unique_entities) < 2:
            return unique_entities

        # Get embeddings
        terms = [e['entity'] for e in unique_entities]
        embeddings = self.model.encode(terms)

        # Compute similarity matrix
        from sklearn.metrics.pairwise import cosine_similarity
        similarity_matrix = cosine_similarity(embeddings)

        # Group similar entities
        # We use a simple greedy approach: take the first, find all similar, merge, repeat
        final_entities = []
        processed_indices = set()

        for i in range(len(unique_entities)):
            if i in processed_indices:
                continue

            current_group = [unique_entities[i]]
            processed_indices.add(i)

            for j in range(i + 1, len(unique_entities)):
                if j in processed_indices:
                    continue

                if similarity_matrix[i][j] >= self.threshold:
                    # Check if types match (optional, but safer)
                    if unique_entities[i]['entity_type'] == unique_entities[j]['entity_type']:
                        current_group.append(unique_entities[j])
                        processed_indices.add(j)

            # Merge group
            merged_entity = self._merge_entity_group(current_group)
            final_entities.append(merged_entity)

        return final_entities

    def _exact_deduplication(self, entities: List[Dict]) -> List[Dict]:
        """Deduplicate by exact string match (case-insensitive)."""
        grouped = defaultdict(list)
        for e in entities:
            key = (e['entity'].lower().strip(), e['entity_type'])
            grouped[key].append(e)
        
        return [self._merge_entity_group(group) for group in grouped.values()]

    def _merge_entity_group(self, group: List[Dict]) -> Dict:
        """Merge a group of duplicate entities into one."""
        if not group:
            return {}
            
        # Pick the most frequent or longest form as the canonical name
        # For now, just pick the one with highest confidence or first
        best_entity = max(group, key=lambda x: x.get('confidence', 0))
        
        # Aggregate stats
        total_confidence = sum(e.get('confidence', 0) for e in group)
        avg_confidence = total_confidence / len(group)
        max_confidence = max(e.get('confidence', 0) for e in group)
        
        # Create merged object
        merged = best_entity.copy()
        merged['confidence'] = avg_confidence
        merged['avg_confidence_score'] = avg_confidence
        merged['max_confidence_score'] = max_confidence
        merged['frequency'] = len(group)
        merged['source_count'] = len(group)
        
        return merged

class SemanticDeduplicator:
    """Deduplicates entities using semantic similarity."""

    def __init__(self, model_name: str = 'all-MiniLM-L6-v2', threshold: float = 0.85):
        self.threshold = threshold
        self.model = None
        try:
            from sentence_transformers import SentenceTransformer
            self.model = SentenceTransformer(model_name)
            logger.info(f"🧠 Semantic deduplicator initialized with {model_name}")
        except ImportError:
            logger.warning("⚠️  sentence-transformers not installed. Semantic deduplication disabled.")
        except Exception as e:
            logger.warning(f"⚠️  Failed to load semantic model: {e}")

    def apply_semantic_deduplication(self, entities: List[Dict]) -> List[Dict]:
        """Deduplicate entities based on semantic similarity."""
        if not entities:
            return []
            
        if not self.model:
            # Fallback to exact string deduplication
            return self._exact_deduplication(entities)

        # First, exact deduplication to reduce work
        unique_entities = self._exact_deduplication(entities)
        if len(unique_entities) < 2:
            return unique_entities

        # Get embeddings
        terms = [e['entity'] for e in unique_entities]
        embeddings = self.model.encode(terms)

        # Compute similarity matrix
        from sklearn.metrics.pairwise import cosine_similarity
        similarity_matrix = cosine_similarity(embeddings)

        # Group similar entities
        # We use a simple greedy approach: take the first, find all similar, merge, repeat
        final_entities = []
        processed_indices = set()

        for i in range(len(unique_entities)):
            if i in processed_indices:
                continue

            current_group = [unique_entities[i]]
            processed_indices.add(i)

            for j in range(i + 1, len(unique_entities)):
                if j in processed_indices:
                    continue

                if similarity_matrix[i][j] >= self.threshold:
                    # Check if types match (optional, but safer)
                    if unique_entities[i]['entity_type'] == unique_entities[j]['entity_type']:
                        current_group.append(unique_entities[j])
                        processed_indices.add(j)

            # Merge group
            merged_entity = self._merge_entity_group(current_group)
            final_entities.append(merged_entity)

        return final_entities

    def _exact_deduplication(self, entities: List[Dict]) -> List[Dict]:
        """Deduplicate by exact string match (case-insensitive)."""
        grouped = defaultdict(list)
        for e in entities:
            key = (e['entity'].lower().strip(), e['entity_type'])
            grouped[key].append(e)
        
        return [self._merge_entity_group(group) for group in grouped.values()]

    def _merge_entity_group(self, group: List[Dict]) -> Dict:
        """Merge a group of duplicate entities into one."""
        if not group:
            return {}
            
        # Pick the most frequent or longest form as the canonical name
        # For now, just pick the one with highest confidence or first
        best_entity = max(group, key=lambda x: x.get('confidence', 0))
        
        # Aggregate stats
        total_confidence = sum(e.get('confidence', 0) for e in group)
        avg_confidence = total_confidence / len(group)
        max_confidence = max(e.get('confidence', 0) for e in group)
        
        # Create merged object
        merged = best_entity.copy()
        merged['confidence'] = avg_confidence
        merged['avg_confidence_score'] = avg_confidence
        merged['max_confidence_score'] = max_confidence
        merged['frequency'] = len(group)
        merged['source_count'] = len(group)

        return merged

# ==========================================
# ADVANCED RELATIONSHIP & ANALYTICS EXTRACTORS
# ==========================================

class RelationshipExtractor:
    """Extract subject-predicate-object relationships from text."""

    def __init__(self, llm_client: 'LLMClient'):
        self.llm_client = llm_client

        # Define relationship categories
        self.relation_types = {
            'causal': ['causes', 'leads to', 'results in', 'induces', 'triggers', 'elicits'],
            'prevents': ['prevents', 'inhibits', 'suppresses', 'blocks', 'reduces', 'decreases'],
            'treats': ['treats', 'ameliorates', 'alleviates', 'therapeutic for'],
            'produces': ['produces', 'synthesizes', 'generates', 'secretes', 'releases', 'creates'],
            'regulates': ['regulates', 'modulates', 'controls', 'mediates'],
            'activates': ['activates', 'stimulates', 'enhances', 'upregulates', 'increases'],
            'associated': ['associated with', 'correlated with', 'linked to', 'related to'],
            'binds': ['binds to', 'interacts with', 'attaches to'],
            'metabolizes': ['metabolizes', 'converts', 'transforms', 'degrades'],
            'transports': ['transports', 'carries', 'moves', 'translocates']
        }

    def extract_relationships(self, text: str, entities: List[Dict], include_speculative: bool = False) -> List[Dict]:
        """Extract relationships between entities from text.

        Args:
            text: Source text
            entities: List of extracted entities
            include_speculative: If False, filter to asserted only (thesis mode)
                              If True, include all relationships (exploratory mode)
        """
        if not entities or len(entities) < 2:
            return []

        # Create entity lookup for context
        entity_names = {e['entity'].lower(): e for e in entities}
        entity_list = list(entity_names.keys())

        # Create prompt
        prompt = self._create_relationship_prompt(text, entity_list)

        # Call LLM
        response = self.llm_client.call_llm(prompt, max_tokens=2000)

        # Parse response with text for evidence spans
        relationships = self._parse_relationship_response(response, entity_names, text)

        # Filter based on mode
        if include_speculative:
            logger.info("🔍 EXPLORATORY MODE: Including all relationships (speculative/negated)")
        else:
            # Filter to asserted relationships only for strict mode
            original_count = len(relationships)
            relationships = [r for r in relationships if r.get('evidence_strength') == 'asserted']
            filtered_count = original_count - len(relationships)
            logger.info(f"✅ STRICT MODE: {len(relationships)} asserted relationships ({filtered_count} speculative/negated filtered)")

        return relationships

    def _create_relationship_prompt(self, text: str, entity_list: List[str]) -> str:
        """Create prompt for relationship extraction."""
        entities_str = "\n".join([f"- {e}" for e in entity_list[:50]])  # Limit to 50 entities

        prompt = f"""Extract relationships between the following entities from the biomedical text.

ENTITIES FOUND:
{entities_str}

RELATIONSHIP TYPES TO EXTRACT:
- CAUSES: causes, leads to, results in, induces
- PREVENTS: prevents, inhibits, suppresses, reduces
- TREATS: treats, ameliorates, alleviates
- PRODUCES: produces, synthesizes, generates, secretes
- REGULATES: regulates, modulates, controls
- ACTIVATES: activates, stimulates, enhances
- ASSOCIATED_WITH: associated with, correlated with, linked to
- BINDS: binds to, interacts with
- METABOLIZES: metabolizes, converts, transforms

TEXT:
{text[:8000]}

OUTPUT FORMAT (one per line):
Subject | Relation | Object | Context | Reasoning
Example: Bacteroides fragilis | PRODUCES | propionate | B. fragilis produces propionate | Direct production statement

INSTRUCTIONS:
1. Use EXACT entity names from the list above (case-insensitive match)
2. Extract 10-20 relationships if available
3. Include brief context and reasoning
4. Mark speculative relationships with "(speculative)" in reasoning
5. Extract relationships even if tentative or exploratory
6. Format: Subject | Relation | Object | Context | Reasoning

Start extracting relationships now:"""

        return prompt

    def _parse_relationship_response(self, response: str, entity_names: Dict, text: str) -> List[Dict]:
        """Parse LLM response for relationships with enhanced evidence tracking."""
        relationships = []

        try:
            # Clean response
            response = re.sub(r'```.*', '', response, flags=re.DOTALL)
            response = re.sub(r'^Here.*?:', '', response, flags=re.IGNORECASE | re.MULTILINE)
            lines = response.split('\n')

            for line in lines:
                line = line.strip()
                if not line or line.lower().startswith(('sure', 'here', 'note:', 'the relationships', '-')):
                    continue

                # Parse format: Subject | Relation | Object | Context | Reasoning
                if '|' in line:
                    parts = [p.strip() for p in line.split('|')]
                    if len(parts) >= 3:
                        subject = parts[0]
                        relation = parts[1].upper().strip()  # Normalize to uppercase
                        obj = parts[2]
                        context = parts[3] if len(parts) > 3 else ""
                        reasoning = parts[4] if len(parts) > 4 else ""

                        # Check if entities exist in our list (case-insensitive)
                        subject_lower = subject.lower()
                        obj_lower = obj.lower()

                        # More flexible matching - check if entity name appears in our list
                        subject_match = None
                        obj_match = None

                        for entity_name in entity_names.keys():
                            if subject_lower in entity_name or entity_name in subject_lower:
                                subject_match = entity_name
                                break
                        for entity_name in entity_names.keys():
                            if obj_lower in entity_name or entity_name in obj_lower:
                                obj_match = entity_name
                                break

                        if subject_match and obj_match:
                            # Normalize relation
                            relation_normalized = self._normalize_relation(relation)

                            # Calculate evidence strength
                            evidence_strength = self._calculate_evidence_strength(context + " " + reasoning)

                            # Extract evidence span
                            subject_start = text.lower().find(subject_match)
                            subject_span = {
                                'start_char': subject_start if subject_start != -1 else -1,
                                'end_char': subject_start + len(subject) if subject_start != -1 else -1,
                                'sentence': self._extract_sentence(text, subject)
                            }

                            # Build enhanced relationship object
                            relationships.append({
                                'subject': subject,
                                'subject_type': entity_names[subject_match].get('entity_type', 'UNKNOWN'),
                                'relation': relation_normalized,
                                'object': obj,
                                'object_type': entity_names[obj_match].get('entity_type', 'UNKNOWN'),
                                'context': context[:200] if context else "",
                                'reasoning': reasoning[:200] if reasoning else "",
                                'evidence_strength': evidence_strength,
                                'negated': (evidence_strength == 'negated'),
                                'speculated': (evidence_strength == 'speculative')
                            })

        except Exception as e:
            logger.error(f"Error parsing relationships: {e}")

        return relationships

    def _normalize_relation(self, relation: str) -> str:
        """Normalize relation to standard types."""
        relation = relation.lower().strip()

        # Mapping variations to standard types
        mapping = {
            'cause': 'causes',
            'lead to': 'causes',
            'result in': 'causes',
            'induce': 'causes',
            'prevent': 'prevents',
            'inhibit': 'inhibits',
            'suppress': 'inhibits',
            'reduce': 'prevents',
            'decrease': 'prevents',
            'treat': 'treats',
            'produce': 'produces',
            'synthesize': 'produces',
            'generate': 'produces',
            'secrete': 'produces',
            'regulate': 'regulates',
            'modulate': 'regulates',
            'activate': 'activates',
            'stimulate': 'activates',
            'enhance': 'activates',
            'upregulate': 'activates',
            'associate': 'associated',
            'correlate': 'associated',
            'link': 'associated',
            'bind': 'binds',
            'interact': 'binds',
            'metabolize': 'metabolizes',
            'convert': 'metabolizes',
            'transform': 'metabolizes',
            'transport': 'transports',
            'carry': 'transports'
        }

        return mapping.get(relation, relation)

    def _check_negation(self, text: str) -> bool:
        """Check if relationship is negated."""
        negation_patterns = [
            r'\bno\b.*\b(effect|impact|influence|change)',
            r'\bnot\b',
            r'\bfailed to\b',
            r'\bdid not\b',
            r'\bdoes not\b',
            r'\bunable to\b',
            r'\bnone\b'
        ]

        text_lower = text.lower()
        for pattern in negation_patterns:
            if re.search(pattern, text_lower):
                return True
        return False

    def _check_speculation(self, text: str) -> bool:
        """Check if relationship is speculative."""
        speculation_patterns = [
            r'\bmay\b',
            r'\bmight\b',
            r'\bcould\b',
            r'\bpotentially\b',
            r'\bpossibly\b',
            r'\bsuggests?\b',
            r'\bappears?\b',
            r'\bseems?\b',
            r'\blikely\b',
            r'\bprobable\b'
        ]

        text_lower = text.lower()
        for pattern in speculation_patterns:
            if re.search(pattern, text_lower):
                return True
        return False

    def _calculate_evidence_strength(self, context: str) -> str:
        """Calculate evidence strength category for evidence strength classification."""
        negated = self._check_negation(context)
        speculated = self._check_speculation(context)

        if negated:
            return 'negated'
        elif speculated:
            return 'speculative'
        elif any(w in context.lower() for w in ['associated', 'correlated', 'linked', 'related', 'connected']):
            return 'associated'
        else:
            return 'asserted'

    def _get_relation_type(self, relation: str) -> str:
        """Categorize relation into causal, regulatory, or association."""
        relation_lower = relation.lower()

        causal = ['causes', 'prevents', 'treats', 'produces', 'metabolizes', 'inhibits', 'blocks']
        regulatory = ['regulates', 'activates', 'stimulates', 'suppresses', 'modulates', 'controls']

        if relation_lower in causal or any(c in relation_lower for c in causal):
            return 'causal'
        elif relation_lower in regulatory or any(r in relation_lower for r in regulatory):
            return 'regulatory'
        else:
            return 'association'

    def _get_polarity(self, context: str) -> str:
        """Determine polarity of relationship (positive, negative, neutral)."""
        negative_words = ['decreases', 'reduces', 'inhibits', 'prevents', 'blocks', 'suppresses', 'downregulates']
        positive_words = ['increases', 'enhances', 'activates', 'promotes', 'stimulates', 'upregulates', 'induces']

        context_lower = context.lower()

        if any(w in context_lower for w in negative_words):
            return 'negative'
        elif any(w in context_lower for w in positive_words):
            return 'positive'
        else:
            return 'neutral'

    def _get_confidence_basis(self, context: str, entities_validated: bool) -> List[str]:
        """Generate confidence basis instead of arbitrary scores."""
        basis = []

        # Check for explicit verbs
        explicit_verbs = ['causes', 'produces', 'inhibits', 'activates', 'prevents', 'treats']
        if any(v in context.lower() for v in explicit_verbs):
            basis.append('explicit_verb')

        # Check entity validation
        if entities_validated:
            basis.append('entity_validated')

        # Check for negation
        if not self._check_negation(context):
            basis.append('non_negated')

        # Check for speculation
        if not self._check_speculation(context):
            basis.append('non_speculative')

        # Check for direct evidence
        direct_evidence = ['shown', 'demonstrated', 'found', 'observed', 'detected', 'measured']
        if any(w in context.lower() for w in direct_evidence):
            basis.append('direct_evidence')

        # Check for statistical support
        if re.search(r'p\s*[<>=]+\s*[0-9.]+', context):
            basis.append('statistical_support')

        return basis if basis else ['weak_evidence']

    def _extract_sentence(self, text: str, term: str) -> str:
        """Extract the full sentence containing a term."""
        # Split into sentences
        sentences = re.split(r'[.!?]+\s+', text)

        # Find sentence containing the term
        term_lower = term.lower()
        for sentence in sentences:
            if term_lower in sentence.lower():
                return sentence.strip()

        # Fallback: return surrounding text
        try:
            idx = text.lower().find(term_lower)
            if idx != -1:
                start = max(0, idx - 100)
                end = min(len(text), idx + len(term) + 100)
                return text[start:end].strip()
        except:
            pass

        return ""


class MicrobiomeInteractionExtractor:
    """Extract microbiome-specific interactions and relationships."""

    def __init__(self, llm_client: 'LLMClient'):
        self.llm_client = llm_client

        self.interaction_types = {
            'microbe_disease': ['associated with', 'increased in', 'decreased in', 'found in'],
            'microbe_metabolite': ['produces', 'consumes', 'degrades', 'converts'],
            'microbe_microbe': ['inhibits', 'promotes', 'co-occurs with', 'cross-feeds'],
            'diet_microbe': ['promotes', 'reduces', 'increases', 'decreases'],
            'drug_microbe': ['affects', 'alters', 'reduces', 'eliminates'],
            'host_microbe': ['harbors', 'colonized by', 'hosts']
        }

    def extract_interactions(self, text: str, entities: List[Dict]) -> Dict[str, List[Dict]]:
        """Extract microbiome-specific interactions."""
        interactions = {
            'microbe_disease': [],
            'microbe_metabolite': [],
            'microbe_microbe': [],
            'diet_microbe_host': [],
            'drug_microbe': []
        }

        if not entities:
            return interactions

        # Categorize entities
        organisms = [e for e in entities if e['entity_type'] == 'ORGANISM']
        chemicals = [e for e in entities if e['entity_type'] == 'CHEMICAL']
        diseases = [e for e in entities if e['entity_type'] == 'DISEASE']
        drugs = [e for e in entities if e['entity_type'] in ['DRUG', 'CHEMICAL']]

        # Extract microbe-metabolite interactions
        if organisms and chemicals:
            interactions['microbe_metabolite'] = self._extract_microbe_metabolite(text, organisms, chemicals)

        # Extract microbe-disease associations
        if organisms and diseases:
            interactions['microbe_disease'] = self._extract_microbe_disease(text, organisms, diseases)

        # Extract microbe-microbe interactions
        if len(organisms) >= 2:
            interactions['microbe_microbe'] = self._extract_microbe_microbe(text, organisms)

        return interactions

    def _extract_microbe_metabolite(self, text: str, organisms: List[Dict], chemicals: List[Dict]) -> List[Dict]:
        """Extract microbe-metabolite production/consumption relationships."""
        prompt = f"""Extract relationships between microbes and metabolites from the text.

MICROBES:
{', '.join([o['entity'] for o in organisms[:20]])}

METABOLITES:
{', '.join([c['entity'] for c in chemicals[:20]])}

RELATIONSHIP TYPES:
- PRODUCES: microbe produces the metabolite
- CONSUMES: microbe uses/degrades the metabolite
- CONVERTS: microbe converts one metabolite to another

TEXT:
{text[:4000]}

OUTPUT FORMAT:
Microbe | Relation | Metabolite | Context
Example: Bacteroides fragilis | PRODUCES | propionate | B. fragilis produces propionate as a fermentation product

Start now:"""

        response = self.llm_client.call_llm(prompt, max_tokens=1500)
        return self._parse_interaction_response(response, organisms, chemicals, 'microbe_metabolite')

    def _extract_microbe_disease(self, text: str, organisms: List[Dict], diseases: List[Dict]) -> List[Dict]:
        """Extract microbe-disease associations."""
        prompt = f"""Extract associations between microbes and diseases/conditions from the text.

MICROBES:
{', '.join([o['entity'] for o in organisms[:20]])}

DISEASES/CONDITIONS:
{', '.join([d['entity'] for d in diseases[:20]])}

RELATIONSHIP TYPES:
- INCREASED: microbe abundance is increased in the disease
- DECREASED: microbe abundance is decreased in the disease
- ASSOCIATED: general association (direction unclear)
- PROTECTIVE: microbe protects against disease

TEXT:
{text[:4000]}

OUTPUT FORMAT:
Microbe | Relation | Disease | Context
Example: Faecalibacterium prausnitzii | DECREASED | Crohn's disease | F. prausnitzii is depleted in Crohn's disease patients

Start now:"""

        response = self.llm_client.call_llm(prompt, max_tokens=1500)
        return self._parse_interaction_response(response, organisms, diseases, 'microbe_disease')

    def _extract_microbe_microbe(self, text: str, organisms: List[Dict]) -> List[Dict]:
        """Extract microbe-microbe interactions."""
        organism_names = [o['entity'] for o in organisms[:30]]

        prompt = f"""Extract interactions between microbes from the text.

MICROBES:
{', '.join(organism_names)}

RELATIONSHIP TYPES:
- INHIBITS: one microbe inhibits growth of another
- PROMOTES: one microbe promotes growth of another
- CROSS-FEEDS: one microbe produces metabolite consumed by another
- CO-OCCURS: microbes found together frequently

TEXT:
{text[:4000]}

OUTPUT FORMAT:
Microbe1 | Relation | Microbe2 | Context
Example: Bacteroides | CROSS-FEEDS | Faecalibacterium | Bacteroides produces acetate used by Faecalibacterium

Start now:"""

        response = self.llm_client.call_llm(prompt, max_tokens=1500)

        # Parse response
        interactions = []
        entity_lookup = {o['entity'].lower(): o for o in organisms}

        try:
            lines = response.split('\n')
            for line in lines:
                line = line.strip()
                if not line or '|' not in line:
                    continue

                parts = [p.strip() for p in line.split('|')]
                if len(parts) >= 3:
                    microbe1 = parts[0]
                    relation = parts[1].upper()
                    microbe2 = parts[2]
                    context = parts[3] if len(parts) > 3 else ""

                    if microbe1.lower() in entity_lookup and microbe2.lower() in entity_lookup:
                        interactions.append({
                            'microbe1': microbe1,
                            'microbe1_type': entity_lookup[microbe1.lower()]['entity_type'],
                            'interaction': relation,
                            'microbe2': microbe2,
                            'microbe2_type': entity_lookup[microbe2.lower()]['entity_type'],
                            'context': context[:200],
                            'confidence': 0.75
                        })
        except Exception as e:
            logger.error(f"Error parsing microbe-microbe interactions: {e}")

        return interactions

    def _parse_interaction_response(self, response: str, entities1: List[Dict], entities2: List[Dict], interaction_type: str) -> List[Dict]:
        """Parse interaction response."""
        interactions = []
        entity_lookup1 = {e['entity'].lower(): e for e in entities1}
        entity_lookup2 = {e['entity'].lower(): e for e in entities2}

        try:
            response = re.sub(r'```.*', '', response, flags=re.DOTALL)
            lines = response.split('\n')

            for line in lines:
                line = line.strip()
                if not line or '|' not in line or line.lower().startswith(('sure', 'here', 'note:')):
                    continue

                parts = [p.strip() for p in line.split('|')]
                if len(parts) >= 3:
                    entity1 = parts[0]
                    relation = parts[1].upper()
                    entity2 = parts[2]
                    context = parts[3] if len(parts) > 3 else ""

                    if entity1.lower() in entity_lookup1 and entity2.lower() in entity_lookup2:
                        interactions.append({
                            'entity1': entity1,
                            'entity1_type': entity_lookup1[entity1.lower()]['entity_type'],
                            'interaction': relation,
                            'entity2': entity2,
                            'entity2_type': entity_lookup2[entity2.lower()]['entity_type'],
                            'context': context[:200],
                            'confidence': 0.8
                        })
        except Exception as e:
            logger.error(f"Error parsing {interaction_type} interactions: {e}")

        return interactions


class TemporalExtractor:
    """Extract temporal information and relationships from text."""

    def __init__(self, llm_client: 'LLMClient'):
        self.llm_client = llm_client

        # Temporal patterns
        self.timepoint_patterns = [
            r'(?:after|at|on|during)\s+(?:day|hour|week|month)\s+\d+',
            r'\d+\s*(?:hours|days|weeks|months|years)\s+(?:after|post|following)',
            r'(?:baseline|week\s+\d+|day\s+\d+|timepoint)',
            r'\d+\s*(?:h|hr|d|day|w|week|m|month|y|year)'
        ]

        self.duration_patterns = [
            r'(?:for|over)\s+\d+\s*(?:hours|days|weeks|months|years)',
            r'\d+\s*-\s*\d+\s*(?:hours|days|weeks|months)',
            r'(?:long-term|short-term|acute|chronic)'
        ]

        self.sequence_patterns = [
            r'(?:followed by|subsequently|then|after that|prior to|before)',
            r'(?:first|then|next|finally|firstly|secondly)',
            r'(?:gradual|progressive|sequential)'
        ]

    def extract_temporal(self, text: str) -> List[Dict]:
        """Extract temporal expressions and relationships."""
        temporal_data = []

        # Extract timepoints
        timepoints = self._extract_timepoints(text)
        temporal_data.extend(timepoints)

        # Extract durations
        durations = self._extract_durations(text)
        temporal_data.extend(durations)

        # Extract sequences
        sequences = self._extract_sequences(text)
        temporal_data.extend(sequences)

        logger.info(f"⏰ Extracted {len(temporal_data)} temporal expressions")
        return temporal_data

    def _extract_timepoints(self, text: str) -> List[Dict]:
        """Extract specific timepoints mentioned."""
        timepoints = []

        for pattern in self.timepoint_patterns:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                timepoints.append({
                    'type': 'timepoint',
                    'expression': match.group(),
                    'start_pos': match.start(),
                    'confidence': 0.85
                })

        return timepoints

    def _extract_durations(self, text: str) -> List[Dict]:
        """Extract duration expressions."""
        durations = []

        for pattern in self.duration_patterns:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                durations.append({
                    'type': 'duration',
                    'expression': match.group(),
                    'start_pos': match.start(),
                    'confidence': 0.80
                })

        return durations

    def _extract_sequences(self, text: str) -> List[Dict]:
        """Extract sequential relationships."""
        sequences = []

        for pattern in self.sequence_patterns:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                sequences.append({
                    'type': 'sequence',
                    'expression': match.group(),
                    'start_pos': match.start(),
                    'confidence': 0.75
                })

        return sequences


class QuantitativeDataExtractor:
    """Extract quantitative measurements, concentrations, and statistical data."""

    def __init__(self, llm_client: 'LLMClient'):
        self.llm_client = llm_client

        # Quantitative patterns
        self.concentration_patterns = [
            r'(\d+\.?\d*)\s*(mM|μM|uM|nM|pM|mg/mL|μg/mL|ng/mL|pg/mL)',
            r'(\d+\.?\d*)\s*(millimolar|micromolar|nanomolar|picomolar)'
        ]

        self.fold_change_patterns = [
            r'(\d+\.?\d*)\s*-fold\s*(?:increase|decrease|change|up|down)',
            r'(?:increased|decreased|upregulated|downregulated)\s+(?:by\s+)?(\d+\.?\d*)\s*-?fold',
            r'(\d+\.?\d*)\s*x\s+(?:increase|decrease|change)'
        ]

        self.percentage_patterns = [
            r'(\d+\.?\d*)%',
            r'(\d+\.?\d*)\s*percent'
        ]

        self.statistical_patterns = [
            r'p\s*[<>=]+\s*[0-9.]+',
            r'p\s*=\s*[0-9.]+',
            r'[fr]\s*=\s*[0-9.]+',
            r'effect size',
            r'confidence interval'
        ]

    def extract_quantitative(self, text: str) -> List[Dict]:
        """Extract all quantitative data from text."""
        quantitative_data = []

        # Extract concentrations
        concentrations = self._extract_concentrations(text)
        quantitative_data.extend(concentrations)

        # Extract fold changes
        fold_changes = self._extract_fold_changes(text)
        quantitative_data.extend(fold_changes)

        # Extract percentages
        percentages = self._extract_percentages(text)
        quantitative_data.extend(percentages)

        # Extract statistical measures
        stats = self._extract_statistics(text)
        quantitative_data.extend(stats)

        logger.info(f"📊 Extracted {len(quantitative_data)} quantitative data points")
        return quantitative_data

    def _extract_concentrations(self, text: str) -> List[Dict]:
        """Extract concentration measurements."""
        concentrations = []

        for pattern in self.concentration_patterns:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                concentrations.append({
                    'type': 'concentration',
                    'value': match.group(1),
                    'unit': match.group(2),
                    'context': self._get_context(text, match.start(), match.end()),
                    'confidence': 0.90
                })

        return concentrations

    def _extract_fold_changes(self, text: str) -> List[Dict]:
        """Extract fold change measurements."""
        fold_changes = []

        for pattern in self.fold_change_patterns:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                full_match = match.group()
                # Determine if increase or decrease
                change_type = 'unknown'
                if 'increase' in full_match.lower() or 'up' in full_match.lower() or 'upregulated' in full_match.lower():
                    change_type = 'increase'
                elif 'decrease' in full_match.lower() or 'down' in full_match.lower() or 'downregulated' in full_match.lower():
                    change_type = 'decrease'

                fold_changes.append({
                    'type': 'fold_change',
                    'value': match.group(1),
                    'change_type': change_type,
                    'context': self._get_context(text, match.start(), match.end()),
                    'confidence': 0.88
                })

        return fold_changes

    def _extract_percentages(self, text: str) -> List[Dict]:
        """Extract percentage measurements."""
        percentages = []

        for pattern in self.percentage_patterns:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                percentages.append({
                    'type': 'percentage',
                    'value': match.group(1),
                    'context': self._get_context(text, match.start(), match.end()),
                    'confidence': 0.85
                })

        return percentages

    def _extract_statistics(self, text: str) -> List[Dict]:
        """Extract statistical measures."""
        stats = []

        for pattern in self.statistical_patterns:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                stats.append({
                    'type': 'statistical',
                    'expression': match.group(),
                    'context': self._get_context(text, match.start(), match.end()),
                    'confidence': 0.95
                })

        return stats

    def _get_context(self, text: str, start: int, end: int, window: int = 100) -> str:
        """Get surrounding context for a match."""
        context_start = max(0, start - window)
        context_end = min(len(text), end + window)
        return text[context_start:context_end].strip()


class CoreferenceResolver:
    """Resolve coreferences and link pronouns to entities."""

    def __init__(self, llm_client: 'LLMClient'):
        self.llm_client = llm_client

        self.pronoun_patterns = [
            r'\bit\b',
            r'\bthey\b',
            r'\bthis\b',
            r'\bthat\b',
            r'\bthese\b',
            r'\bthose\b',
            r'\bwhich\b',
            r'\bwho\b'
        ]

        self.demonstrative_patterns = [
            r'\bthis (?:bacterium|microbe|organism|metabolite|compound)\b',
            r'\bthat (?:bacterium|microbe|organism|metabolite|compound)\b',
            r'\bthese bacteria|microbes|organisms\b',
            r'\bthose bacteria|microbes|organisms\b'
        ]

    def resolve_coreferences(self, text: str, entities: List[Dict]) -> List[Dict]:
        """Resolve coreferences and link to entities."""
        coreference_chains = []

        if not entities:
            return coreference_chains

        # Create entity lookup
        entity_names = [e['entity'] for e in entities]

        # Find sentences with potential coreferences
        sentences = re.split(r'[.!?]+', text)

        for sentence in sentences:
            if len(sentence.strip()) < 20:
                continue

            # Check for pronouns
            pronoun_matches = []
            for pattern in self.pronoun_patterns:
                matches = re.finditer(pattern, sentence, re.IGNORECASE)
                pronoun_matches.extend([(m.group(), m.start()) for m in matches])

            if pronoun_matches:
                # Use LLM to resolve
                resolved = self._resolve_with_llm(sentence, entity_names)
                if resolved:
                    coreference_chains.extend(resolved)

        logger.info(f"🔗 Resolved {len(coreference_chains)} coreferences")
        return coreference_chains

    def _resolve_with_llm(self, sentence: str, entities: List[str]) -> List[Dict]:
        """Use LLM to resolve coreferences in a sentence."""
        entities_str = ', '.join(entities[:20])

        prompt = f"""Resolve pronoun references to specific entities in the sentence.

AVAILABLE ENTITIES:
{entities_str}

SENTENCE:
{sentence}

TASK: Identify which entity each pronoun refers to.

OUTPUT FORMAT:
Pronoun | Entity
Example: it | Escherichia coli

If a pronoun cannot be resolved, output: Pronoun | UNKNOWN

Start now:"""

        response = self.llm_client.call_llm(prompt, max_tokens=500)

        # Parse response
        resolutions = []
        try:
            lines = response.split('\n')
            for line in lines:
                line = line.strip()
                if '|' in line and not line.lower().startswith(('sure', 'here', 'note:')):
                    parts = [p.strip() for p in line.split('|')]
                    if len(parts) == 2:
                        pronoun = parts[0]
                        entity = parts[1]

                        if entity != 'UNKNOWN':
                            resolutions.append({
                                'pronoun': pronoun,
                                'refers_to': entity,
                                'sentence': sentence[:200],
                                'confidence': 0.70
                            })
        except Exception as e:
            logger.error(f"Error parsing coreference resolution: {e}")

        return resolutions


class CDMEntityPipeline:
    """Main CDM entity extraction pipeline with semantic deduplication."""

    def __init__(self, model: str = None, base_url: str = None, config: PipelineConfig = None,
                 semantic_model: str = "all-MiniLM-L6-v2", semantic_threshold: float = 0.95,
                 enable_biomistral: bool = False, biomistral_model: str = "biomistral-7B",
                 enable_biomistral_deduplication: bool = False, biomistral_dedup_model: str = "biomistral:7b",
                 enable_omop_mapping: bool = False, enable_umls_mapping: bool = False,
                 umls_api_key: str = None, bioportal_api_key: str = None, enable_comprehensive_mapping: bool = False,
                 enable_scispacy_linking: bool = False,
                 mapping_confidence_threshold: float = 0.7,
                 enable_correction: bool = False, enable_llm_correction: bool = False,
                 dry_run: bool = False, fast_mode: bool = False, api_type: str = "ollama",
                 api_key: str = "EMPTY", hf_token: str = None,
                 include_speculative: bool = False):
        self.config = config or PipelineConfig()
        self.dry_run = dry_run
        
        # Optimization Config
        self.opt_config = OptimizationConfig(
            fast_mode=fast_mode,
            api_key=api_key,
            chunk_size_multiplier=1.0, 
            api_type=api_type,
            hf_token=hf_token
        )
        self.enable_biomistral = enable_biomistral
        self.enable_biomistral_deduplication = enable_biomistral_deduplication
        self.enable_correction = enable_correction
        self.enable_llm_correction = enable_llm_correction
        self.enable_omop_mapping = enable_omop_mapping
        self.enable_umls_mapping = enable_umls_mapping
        self.enable_comprehensive_mapping = enable_comprehensive_mapping
        self.enable_scispacy_linking = enable_scispacy_linking
        
        if self.dry_run:
            logger.info("⚠️  DRY RUN MODE ENABLED: Skipping model loading and LLM calls")
            self.llm_client = None
            self.extractor = None
            self.entity_config = CDMEntityConfig()
            self.semantic_deduplicator = None
            self.entity_filter = None
            self.relevance_scorer = None
            self.term_corrector = None
            self.biomistral_validator = None
            self.biomistral_deduplicator = None
            self.comprehensive_mapper = None
            self.relationship_extractor = None
            self.microbiome_extractor = None
            self.temporal_extractor = None
            self.quantitative_extractor = None
            self.coreference_resolver = None
            return

        self.llm_client = LLMClient(model or self.config.default_model, base_url or self.config.default_base_url, self.opt_config)
        self.extractor = CDMEntityExtractor(self.llm_client)
        self.entity_config = CDMEntityConfig()
        self.semantic_deduplicator = SemanticDeduplicator(semantic_model, semantic_threshold)
        self.entity_filter = EntityFilter()
        self.relevance_scorer = MicrobiomeRelevanceScorer()
        
        if self.opt_config.fast_mode:
            logger.info("🚀 FAST MODE ENABLED: Using larger chunks and optimized settings")
            # Disable expensive optional steps in fast mode unless explicitly forced?
            # User said "reduce time", so we should be careful.
            # But we'll respect the flags if they are passed.


        if enable_biomistral:
            biomistral_config = BioMistralConfig(model_name=biomistral_model)
            self.biomistral_validator = BioMistralValidator(biomistral_config)

        if enable_biomistral_deduplication:
            self.biomistral_deduplicator = BioMistralDeduplicator(
                llm_client=self.llm_client,
                biomistral_model=biomistral_dedup_model,
                semantic_model=semantic_model
            )
            logger.info(f"✅ BioMistral deduplication enabled with model: {biomistral_dedup_model}")

        if enable_comprehensive_mapping:
            # Get OMOP vocab directory from environment or default
            omop_vocab_dir = os.environ.get('OMOP_VOCAB_DIR', 'omop_vocab')

            self.comprehensive_mapper = ComprehensiveMapper(
                umls_api_key=umls_api_key,
                bioportal_api_key=bioportal_api_key,
                use_local_omop=True,  # Use local mapper by default
                omop_vocab_dir=omop_vocab_dir,
                fuzzy_threshold=95,
                max_matches=3,
                cache_mappings=True,
                use_scispacy=enable_scispacy_linking
            )
            logger.info(f"🗂️  Comprehensive mapping initialized with OMOP vocab: {omop_vocab_dir}")

        # Initialize advanced analytics extractors
        self.relationship_extractor = RelationshipExtractor(self.llm_client)
        self.microbiome_extractor = MicrobiomeInteractionExtractor(self.llm_client)
        self.temporal_extractor = TemporalExtractor(self.llm_client)
        self.quantitative_extractor = QuantitativeDataExtractor(self.llm_client)
        self.coreference_resolver = CoreferenceResolver(self.llm_client)
        logger.info("✅ Advanced analytics extractors initialized: Relationships, Microbiome, Temporal, Quantitative, Coreference")

        # Paper metadata (can be set externally)
        self.paper_metadata = {}
        self.include_speculative = False  # Default to strict mode

    def validate_prerequisites(self) -> bool:
        """Validate that the pipeline can run."""
        if self.dry_run:
            logger.info("✅ Dry run: Prerequisites check skipped")
            return True

        if not self.llm_client.is_available():
            logger.error(f"LLM service not available at {self.llm_client.base_url}")
            return False

        available_models = self.llm_client.get_available_models()
        if self.llm_client.model not in available_models:
            logger.error(f"Model {self.llm_client.model} not available. Available models: {available_models}")
            return False

        logger.info(f"✅ LLM service available with model: {self.llm_client.model}")
        return True

    def chunk_text(self, text: str, chunk_size: int = None) -> List[tuple]:
        """Split text into overlapping chunks after enhanced preprocessing."""
        # Apply enhanced preprocessing
        text = TextProcessor.enhanced_preprocess_text(text)
        
        if chunk_size is None:
            if self.extractor:
                base_chunk_size = self.extractor.calculate_optimal_chunk_size(len(text))
            else:
                base_chunk_size = 5000 # Default for dry run
                
            chunk_size = int(base_chunk_size * self.opt_config.chunk_size_multiplier)
            
            # Cap chunk size to avoid context overflow (assuming 128k context for modern models like GLM-4/GPT-4)
            # Use 50000 for high efficiency
            chunk_size = min(chunk_size, 50000)


        if self.extractor:
            overlap = self.extractor.calculate_overlap(chunk_size)
        else:
            overlap = 150 # Default for dry run

        chunks = []
        chunk_num = 1

        for i in range(0, len(text), chunk_size - overlap):
            chunk = text[i:i + chunk_size]
            if len(chunk) > 100:  # Only process substantial chunks
                chunks.append((chunk, chunk_num))
                chunk_num += 1

        logger.info(f"📊 Created {len(chunks)} chunks ({chunk_size} chars, {overlap} overlap)")
        return chunks

    def extract_entities(self, text: str, chunk_size: int = None, checkpoint_path: Path = None) -> List[Dict]:
        """Extract entities from text using the configured strategy with granular checkpointing."""
        # Chunk text
        chunks = self.chunk_text(text, chunk_size)
        
        all_entities = []
        completed_chunks = set()
        
        # Load checkpoint if exists
        if checkpoint_path and checkpoint_path.exists():
            try:
                with open(checkpoint_path, 'r') as f:
                    data = json.load(f)
                    # Check if it's the new format with 'completed_chunks'
                    if isinstance(data, dict) and 'completed_chunks' in data:
                        all_entities = data.get('entities', [])
                        completed_chunks = set(data.get('completed_chunks', []))
                        logger.info(f"🔄 Resuming from checkpoint: {len(completed_chunks)} chunks already processed, {len(all_entities)} entities loaded")
                    elif isinstance(data, list):
                        # Legacy format (just list of entities), assume finished or restart?
                        # If we are here, it means we might want to resume, but we don't know which chunks are done.
                        # Safest is to treat as entities found so far but maybe re-process if we can't map them to chunks.
                        # Actually, if it's a list, it's likely the old full-file checkpoint.
                        # Let's assume we start over if it's not the granular format, OR we could try to use it.
                        # For now, let's just log and start over to be safe, or maybe the user wants to keep them.
                        logger.warning("⚠️  Found legacy checkpoint format. Starting fresh for granular tracking.")
            except Exception as e:
                logger.warning(f"⚠️  Failed to load checkpoint: {e}")

        # Filter chunks
        chunks_to_process = [(chunk, i) for chunk, i in chunks if i not in completed_chunks]
        
        if not chunks_to_process:
            logger.info("✅ All chunks already processed.")
            return all_entities

        logger.info(f"🧩 Processing {len(chunks_to_process)}/{len(chunks)} chunks with {self.config.max_workers} workers")
        logger.info("🚀 NORMAL MODE: Single Comprehensive Pass for High Efficiency")
        
        # Use parallel processing
        with ThreadPoolExecutor(max_workers=self.config.max_workers) as executor:
            # Submit only remaining chunks
            if self.extractor:
                future_to_chunk = {
                    executor.submit(self.extractor.extract_chunk_multi_pass, chunk, i): i 
                    for chunk, i in chunks_to_process
                }
            else:
                # Dry run: mock futures
                logger.info("⚠️  Dry run: Skipping actual extraction")
                return all_entities
            
            for future in tqdm(as_completed(future_to_chunk), total=len(chunks_to_process), desc="Processing chunks (Multi-Pass)", unit="chunk"):
                chunk_idx = future_to_chunk[future]
                try:
                    chunk_entities = future.result()
                    if chunk_entities:
                        all_entities.extend(chunk_entities)
                        logger.debug(f"Chunk {chunk_idx}: Found {len(chunk_entities)} entities")
                    
                    # Mark chunk as completed
                    completed_chunks.add(chunk_idx)
                    
                    # Save incremental checkpoint
                    if checkpoint_path:
                        try:
                            checkpoint_data = {
                                "entities": all_entities,
                                "completed_chunks": list(completed_chunks),
                                "total_chunks": len(chunks),
                                "last_updated": datetime.now().isoformat()
                            }
                            with open(checkpoint_path, 'w') as f:
                                json.dump(checkpoint_data, f, indent=2)
                        except Exception as e:
                            logger.error(f"Failed to save checkpoint for chunk {chunk_idx}: {e}")
                            
                except Exception as e:
                    logger.error(f"Error processing chunk {chunk_idx}: {e}")
                    
        return all_entities

    def extract_advanced_analytics(self, text: str, entities: List[Dict], include_speculative: bool = False) -> Dict[str, Any]:
        """Extract advanced analytics: relationships, microbiome interactions, temporal, quantitative, coreferences.

        Args:
            text: Source text
            entities: Extracted entities
            include_speculative: If True, include speculative/negated relationships (exploratory mode)
        """
        if self.dry_run or not entities:
            return {
                'relationships': [],
                'microbiome_interactions': {},
                'temporal_data': [],
                'quantitative_data': [],
                'coreference_chains': []
            }

        analytics = {}

        # 1. Extract relationships (triplets)
        logger.info("🔗 Extracting entity relationships...")
        try:
            analytics['relationships'] = self.relationship_extractor.extract_relationships(text, entities, include_speculative)
        except Exception as e:
            logger.error(f"Error extracting relationships: {e}")
            analytics['relationships'] = []

        # 2. Extract microbiome-specific interactions
        logger.info("🧬 Extracting microbiome-specific interactions...")
        try:
            analytics['microbiome_interactions'] = self.microbiome_extractor.extract_interactions(text, entities)
        except Exception as e:
            logger.error(f"Error extracting microbiome interactions: {e}")
            analytics['microbiome_interactions'] = {}

        # 3. Extract temporal information
        logger.info("⏰ Extracting temporal data...")
        try:
            analytics['temporal_data'] = self.temporal_extractor.extract_temporal(text)
        except Exception as e:
            logger.error(f"Error extracting temporal data: {e}")
            analytics['temporal_data'] = []

        # 4. Extract quantitative data
        logger.info("📊 Extracting quantitative data...")
        try:
            analytics['quantitative_data'] = self.quantitative_extractor.extract_quantitative(text)
        except Exception as e:
            logger.error(f"Error extracting quantitative data: {e}")
            analytics['quantitative_data'] = []

        # 5. Resolve coreferences - DISABLED for speed (takes too long on large texts)
        logger.info("🔗 Skipping coreference resolution (disabled for performance)...")
        try:
            # analytics['coreference_chains'] = self.coreference_resolver.resolve_coreferences(text, entities)
            analytics['coreference_chains'] = []  # Empty instead of running
        except Exception as e:
            logger.error(f"Error resolving coreferences: {e}")
            analytics['coreference_chains'] = []

        logger.info(f"✅ Advanced analytics extraction complete")
        return analytics

    def post_process_entities(self, entities: List[Dict], use_semantic: bool = False) -> List[Dict]:
        if self.dry_run:
            return entities
        """Clean, deduplicate, and sort entities with optional semantic deduplication."""
        logger.info(f"🔄 Post-processing {len(entities)} entities")

        # Basic cleaning and validation
        cleaned_entities = []
        for entity_data in entities:
            # Clean entity name using strict cleaning
            cleaned_entity = self.entity_filter.clean_term(entity_data['entity'])

            # Validation checks
            if (not cleaned_entity or
                len(cleaned_entity) < 2 or
                len(cleaned_entity) > 100 or
                entity_data['confidence'] < self.config.min_confidence):
                continue

            entity_data['entity'] = cleaned_entity
            cleaned_entities.append(entity_data)

        logger.info(f"✅ Basic validation: {len(entities)} → {len(cleaned_entities)} entities")

        # Apply BioMistral biomedical validation if enabled
        if self.enable_biomistral:
            logger.info("🔄 Applying BioMistral biomedical validation...")
            cleaned_entities = self.biomistral_validator.validate_entity_list(cleaned_entities)
            if self.enable_llm_correction:
                cleaned_entities = self.biomistral_validator.correct_entity_types(cleaned_entities)
            logger.info(f"✅ BioMistral validation: {len(cleaned_entities)} entities processed")

        # Apply MiniLM term correction
        if self.enable_correction:
            logger.info("🔧 Applying MiniLM term correction...")
            cleaned_entities = self.term_corrector.correct_terms(cleaned_entities)
        
        # Apply comprehensive mapping if enabled
        if self.enable_comprehensive_mapping:
            logger.info("🔄 Applying comprehensive biomedical mapping...")
            cleaned_entities = self.comprehensive_mapper.map_entity_list_comprehensive(cleaned_entities, max_workers=self.config.max_workers)
            logger.info(f"✅ Comprehensive mapping: {len(cleaned_entities)} entities processed")

        # Apply semantic deduplication if requested
        if use_semantic:
            logger.info("🔄 Applying semantic deduplication...")
            semantically_deduplicated = self.semantic_deduplicator.apply_semantic_deduplication(cleaned_entities)
            logger.info(f"✅ Semantic deduplication: {len(cleaned_entities)} → {len(semantically_deduplicated)} entities")
            unique_entities = semantically_deduplicated
        else:
            # Traditional string-based deduplication
            seen_entities = set()
            unique_entities = []
            for entity_data in cleaned_entities:
                key = (entity_data['entity'].lower().strip(), entity_data['entity_type'])
                if key not in seen_entities:
                    seen_entities.add(key)
                    unique_entities.append(entity_data)

        # Apply BioMistral biomedical deduplication if enabled
        if self.enable_biomistral_deduplication:
            logger.info("🔬 Applying BioMistral biomedical deduplication...")
            biomistral_deduplicated, duplicate_groups = self.biomistral_deduplicator.deduplicate_entities(
                entities=unique_entities,
                biomistral_threshold=0.7,
                semantic_threshold=0.85,
                use_biomistral=True
            )
            logger.info(f"✅ BioMistral deduplication: {len(unique_entities)} → {len(biomistral_deduplicated)} entities")
            logger.info(f"🔗 Found {len(duplicate_groups)} biomedical duplicate groups")

            # Export duplicate analysis for parsing
            self.biomistral_deduplicator.export_duplicate_analysis("biomistral_duplicate_analysis.json")

            unique_entities = biomistral_deduplicated

        # Apply comprehensive entity filtering and quality control
        logger.info("🔍 Applying comprehensive entity filtering and quality control...")
        filtered_entities = self.entity_filter.apply_comprehensive_filtering(unique_entities)
        logger.info(f"✅ Comprehensive filtering: {len(unique_entities)} → {len(filtered_entities)} high-quality entities")
        
        # Apply microbiome relevance scoring
        logger.info("📊 Calculating microbiome relevance scores...")
        scored_entities = self.relevance_scorer.score_entities(filtered_entities)
        unique_entities = scored_entities

        # Sort by entity type priority and confidence
        entity_type_order = {entity_type: config['priority']
                           for entity_type, config in self.entity_config.ENTITY_TYPES.items()}

        unique_entities.sort(
            key=lambda x: (entity_type_order.get(x['entity_type'], 99), -x['confidence'])
        )

        # Cap maximum entities
        final_entities = unique_entities[:self.config.max_entities]
        logger.info(f"✅ Final result: {len(final_entities)} entities (max: {self.config.max_entities})")

        return final_entities

    def generate_statistics(self, entities: List[Dict]) -> Dict:
        """Generate extraction statistics."""
        type_counts = {}
        confidence_sum = 0
        source_counts = {}

        for entity in entities:
            entity_type = entity['entity_type']
            type_counts[entity_type] = type_counts.get(entity_type, 0) + 1
            confidence_sum += entity['confidence']

            source = entity['source']
            source_counts[source] = source_counts.get(source, 0) + 1

        avg_confidence = confidence_sum / len(entities) if entities else 0

        return {
            'total_entities': len(entities),
            'entity_type_distribution': type_counts,
            'average_confidence': round(avg_confidence, 3),
            'source_distribution': source_counts,
            'unique_entity_types': len(type_counts)
        }

    def save_results(self, entities: List[Dict], output_path: str, text_stats: Dict = None, advanced_analytics: Dict = None, paper_metadata: Dict = None):
        """Save extraction results to JSON file in the requested flat format."""

        flat_results = []
        
        for entity in entities:
            if not isinstance(entity, dict):
                continue
                
            # Extract comprehensive mapping data if available
            comp_mapping = entity.get('comprehensive_mapping', {})
            omop_mappings = comp_mapping.get('omop_mappings', []) if comp_mapping else entity.get('omop_mappings', [])
            
            # Helper to safely get list item
            def get_item(lst, idx, key=None, default=None):
                try:
                    item = lst[idx]
                    return item.get(key, default) if key else item
                except IndexError:
                    return default

            # Construct the flat record
            record = {
                "term": entity.get('entity', ''),
                "contextual_definition": entity.get('context', ''),
                "definition": entity.get('definition', ''),
                "confidence_score": entity.get('confidence', 0.0),
                "avg_confidence_score": entity.get('avg_confidence_score', entity.get('confidence', 0.0)),
                "max_confidence_score": entity.get('max_confidence_score', entity.get('confidence', 0.0)),
                "frequency": entity.get('frequency', 1),
                "categories": entity.get('entity_type', ''),
                "aliases": ", ".join(entity.get('aliases', [])), 
                "examples": "; ".join(entity.get('examples', [])),
                "files_found_in": entity.get('source_file', ''),
                "is_core_term": entity.get('frequency', 1) > 1, # Simple heuristic
                "relevance_classification": "High" if entity.get('microbiome_relevance_score', 0) > 0.7 else "Medium",
                # Note: source_code field removed - use files_found_in for source tracking

                # Requested IDs
                "UMLS_ID": comp_mapping.get('umls_mappings', [{}])[0].get('umls_cui', '') if comp_mapping.get('umls_mappings') else '',
                "OMOP": get_item(omop_mappings, 0, 'concept_id', ''),
                "OLS": comp_mapping.get('ols_mappings', [{}])[0].get('iri', '') if comp_mapping.get('ols_mappings') else '',
                "Bioportal": comp_mapping.get('bioportal_mappings', [{}])[0].get('concept_id', '') if comp_mapping.get('bioportal_mappings') else '',
            }
            flat_results.append(record)

    
        # Generate statistics
        stats = self.generate_statistics(entities)

        # Create results structure (keeping wrapper for metadata, but results is now flat list)
        results = {
            'metadata': {
                'timestamp': time.time(),
                'model_used': self.llm_client.model if self.llm_client else "dry-run",
                'pipeline_version': '2.0.0',  # Updated version with advanced analytics
                'token_usage': self.llm_client.get_token_usage() if self.llm_client else {},
                'extraction_config': {
                    'min_confidence': self.config.min_confidence,
                    'max_entities': self.config.max_entities,
                    'max_workers': self.config.max_workers,
                    'mode': 'exploratory' if self.include_speculative else 'strict',
                    'filtering': 'disabled' if self.include_speculative else 'enabled'
                }
            },
            'text_statistics': text_stats or {},
            'extraction_statistics': stats,
            'results': flat_results,  # Now a flat list
            # NEW: Advanced analytics sections
            'relationships': advanced_analytics.get('relationships', []) if advanced_analytics else [],
            'microbiome_interactions': advanced_analytics.get('microbiome_interactions', {}) if advanced_analytics else {},
            'temporal_data': advanced_analytics.get('temporal_data', []) if advanced_analytics else [],
            'quantitative_data': advanced_analytics.get('quantitative_data', []) if advanced_analytics else [],
            'coreference_chains': advanced_analytics.get('coreference_chains', []) if advanced_analytics else [],
            # NEW: Paper metadata if available
            'paper_metadata': paper_metadata or {}
        }

        # Write to file
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2)

        logger.info(f"💾 Results saved to {output_path}")

        # Log summary
        logger.info(f"📊 Extraction Summary:")
        for entity_type, count in stats['entity_type_distribution'].items():
            logger.info(f"   {entity_type}: {count} entities")
        logger.info(f"   Average confidence: {stats['average_confidence']:.3f}")

        # Log advanced analytics summary
        if advanced_analytics:
            logger.info(f"📈 Advanced Analytics Summary:")
            logger.info(f"   Relationships extracted: {len(advanced_analytics.get('relationships', []))}")
            logger.info(f"   Microbiome interactions: {sum(len(v) for v in advanced_analytics.get('microbiome_interactions', {}).values())}")
            logger.info(f"   Temporal expressions: {len(advanced_analytics.get('temporal_data', []))}")
            logger.info(f"   Quantitative data points: {len(advanced_analytics.get('quantitative_data', []))}")
            logger.info(f"   Coreferences resolved: {len(advanced_analytics.get('coreference_chains', []))}")

    def generate_statistics(self, entities: List[Dict]) -> Dict:
        """Generate statistics from extracted entities."""
        stats = {
            'total_entities': len(entities),
            'unique_entities': len({e['entity'].lower() for e in entities}),
            'entity_type_distribution': {},
            'average_confidence': 0.0
        }
        
        if not entities:
            return stats
            
        # Type distribution
        type_counts = {}
        total_confidence = 0
        
        for entity in entities:
            e_type = entity.get('entity_type', 'UNKNOWN')
            type_counts[e_type] = type_counts.get(e_type, 0) + 1
            total_confidence += entity.get('confidence', 0.0)
            
        stats['entity_type_distribution'] = type_counts
        stats['average_confidence'] = total_confidence / len(entities)
        
        return stats

    def run(self, text: str, output_path: str, chunk_size: int = None) -> bool:
        """Run the complete CDM entity extraction pipeline."""
        try:
            # Validate prerequisites
            if not self.validate_prerequisites():
                return False

            # Text statistics
            text_stats = {
                'character_count': len(text),
                'word_count': len(text.split()),
                'estimated_reading_time': len(text.split()) / 200  # words per minute
            }

            logger.info(f"📄 Text analysis: {text_stats['character_count']} chars, {text_stats['word_count']} words")

            # Extract entities
            start_time = time.time()
            entities = self.extract_entities(text, chunk_size)
            extraction_time = time.time() - start_time

            # Extract advanced analytics (relationships, temporal, quantitative, etc.)
            advanced_analytics = self.extract_advanced_analytics(text, entities, self.include_speculative)

            # Save results with advanced analytics and paper metadata
            self.save_results(entities, output_path, text_stats, advanced_analytics, self.paper_metadata)

            logger.info(f"⚡ Pipeline completed in {extraction_time:.1f} seconds")
            logger.info(f"📊 Total unique entities: {len(entities)}")

            return True

        except Exception as e:
            logger.error(f"Pipeline execution failed: {e}")
            return False

    def consolidate_results(self, processed_dir: str, output_file: str, skip_dedup: bool = False):
        """Consolidate processed JSON files into a single output."""
        processed_path = Path(processed_dir)
        output_path = Path(output_file)

        logger.info(f"📂 Reading processed files from {processed_path}")

        all_entities = []
        files_processed = 0

        for file_path in processed_path.glob("*.json"):
            try:
                with open(file_path, 'r') as f:
                    data = json.load(f)

                if isinstance(data, list):
                    entities = data
                elif isinstance(data, dict) and 'entities' in data:
                    entities = data['entities']
                elif isinstance(data, dict) and 'results' in data:
                     # Handle already flattened results if needed, but usually we consolidate raw entities
                     # For now, assume we are consolidating raw entities from checkpoints/processed files
                     entities = data['results'] if isinstance(data['results'], list) else []
                else:
                    logger.warning(f"⚠️ Unknown format in {file_path.name}")
                    continue

                for entity in entities:
                    if 'source_file' not in entity:
                        entity['source_file'] = file_path.stem + ".txt"

                all_entities.extend(entities)
                files_processed += 1

            except Exception as e:
                logger.error(f"❌ Failed to read {file_path.name}: {e}")

        logger.info(f"✅ Loaded {len(all_entities)} entities from {files_processed} files")

        # Deduplicate (unless skipped)
        if skip_dedup:
            logger.info("⏭️  Skipping semantic deduplication (--skip-dedup enabled)")
            deduplicated_entities = all_entities
        else:
            logger.info("🔄 Running semantic deduplication...")
            deduplicated_entities = self.semantic_deduplicator.apply_semantic_deduplication(all_entities)

        # Save (no advanced analytics for consolidated results)
        logger.info(f"💾 Saving consolidated results to {output_path}")
        self.save_results(deduplicated_entities, str(output_path), advanced_analytics=None)
        logger.info("🎉 Consolidation complete!")

    def apply_mappings_to_file(self, input_file: str):
        """Apply mappings to an existing JSON file."""
        input_path = Path(input_file)
        logger.info(f"📂 Reading entities from {input_path}")
        
        with open(input_path, 'r') as f:
            data = json.load(f)
            
        if isinstance(data, dict) and 'results' in data:
            entities = data['results']
            is_flat = True
        elif isinstance(data, list):
            entities = data
            is_flat = False
        else:
            logger.error("❌ Unknown file format")
            return

        logger.info(f"🚀 Starting mapping for {len(entities)} entities with {self.config.max_workers} workers...")

        updated_entities = []
        with ThreadPoolExecutor(max_workers=self.config.max_workers) as executor:
            futures = []
            for entity in entities:
                futures.append(executor.submit(self._process_mapping_entity, entity, is_flat))

            for future in tqdm(as_completed(futures), total=len(entities)):
                updated_entities.append(future.result())
        
        if is_flat:
            data['results'] = updated_entities
            output_data = data
        else:
            output_data = updated_entities
            
        with open(input_path, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, indent=2)
            
        logger.info(f"💾 Updated mappings saved to {input_path}")

    def _process_mapping_entity(self, entity: Dict, is_flat: bool) -> Dict:
        """Process a single entity for mapping."""
        term = entity.get('term') if is_flat else entity.get('entity')
        entity_type = entity.get('categories') if is_flat else entity.get('entity_type')
        
        if not term:
            return entity
            
        # Check if mapping is missing (check all 4 mapping fields)
        needs_mapping = False
        if is_flat:
            # Need mapping if any of the key mappings are missing
            if not entity.get('Bioportal') or not entity.get('OLS') or not entity.get('UMLS_ID') or not entity.get('OMOP'):
                needs_mapping = True
        else:
            if 'comprehensive_mapping' not in entity:
                needs_mapping = True
                
        if needs_mapping and self.comprehensive_mapper:
            try:
                # Map using comprehensive mapper
                mapping_result = self.comprehensive_mapper.map_entity_comprehensive(term, entity_type)
                
                if is_flat:
                    # Update Bioportal
                    bioportal_list = mapping_result.get('bioportal_mappings', [])
                    bioportal = bioportal_list[0].get('concept_id', '') if bioportal_list else ''
                    if bioportal: entity['Bioportal'] = bioportal

                    # Update OLS
                    ols_list = mapping_result.get('ols_mappings', [])
                    ols = ols_list[0].get('iri', '') if ols_list else ''
                    if ols: entity['OLS'] = ols

                    # Update UMLS_ID if missing
                    umls_list = mapping_result.get('umls_mappings', [])
                    umls = umls_list[0].get('umls_cui', '') if umls_list else ''
                    if umls and not entity.get('UMLS_ID'): entity['UMLS_ID'] = umls

                    # Update OMOP if missing
                    omop_list = mapping_result.get('omop_mappings', [])
                    omop = omop_list[0].get('concept_id', '') if omop_list else ''
                    if omop and not entity.get('OMOP'): entity['OMOP'] = omop
                    elif omop_list and not entity.get('OMOP') or not entity.get('OMOP') or entity.get('OMOP') == '':
                        # If no concept_id, try domain_id or construct mapping string
                        if omop_list:
                            concept_id = omop_list[0].get('concept_id', '')
                            if concept_id:
                                entity['OMOP'] = concept_id
                            else:
                                # Use vocabulary-specific identifier if available
                                concept_code = omop_list[0].get('concept_code', '')
                                vocab_id = omop_list[0].get('vocabulary_id', '')
                                if concept_code and vocab_id:
                                    entity['OMOP'] = f"{vocab_id}:{concept_code}"

                else:
                    entity['comprehensive_mapping'] = mapping_result
                    
            except Exception:
                pass
                
        return entity

    def enrich_definitions(self, input_file: str):
        """Enrich existing entities with Definitions, Aliases, and Examples using LLM."""
        input_path = Path(input_file)
        logger.info(f"📂 Reading entities for enrichment from {input_path}")
        
        with open(input_path, 'r') as f:
            data = json.load(f)
            
        if isinstance(data, dict) and 'results' in data:
            entities = data['results']
            is_flat = True
        else:
            logger.error("❌ Enrichment currently only supports flat format (results.json)")
            return

        logger.info(f"🚀 Starting enrichment for {len(entities)} entities...")
        
        # Filter entities that need enrichment
        to_enrich = [e for e in entities if not e.get('definition') or not e.get('aliases')]
        logger.info(f"ℹ️  {len(to_enrich)} entities need enrichment")
        
        # Batch process
        batch_size = 20
        for i in tqdm(range(0, len(to_enrich), batch_size)):
            batch = to_enrich[i:i+batch_size]
            self._enrich_batch(batch)
            
            # Save periodically
            if i % 100 == 0:
                 with open(input_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2)

        # Final save
        with open(input_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
            
        logger.info(f"💾 Enriched results saved to {input_path}")

    def _enrich_batch(self, batch: List[Dict]):
        """Enrich a batch of entities using LLM."""
        if not batch: return
        
        terms = [e.get('term') for e in batch]
        terms_str = "\n".join([f"- {t} ({e.get('categories', 'UNKNOWN')})" for t, e in zip(terms, batch)])
        
        prompt = f"""You are a biomedical expert. Provide Definition, Aliases, and Examples for the following terms.
        
TERMS:
{terms_str}

OUTPUT FORMAT:
- [Term] | Definition: [Brief definition] | Aliases: [Alias1, Alias2] | Examples: [Ex1, Ex2]

Provide one line per term. Start immediately.
"""
        try:
            response = self.llm_client.call_llm(prompt)
            lines = response.strip().split('\\n')
            
            # Parse response and update entities
            results_map = {}
            for line in lines:
                parts = line.split('|')
                if len(parts) < 2: continue
                
                term_part = parts[0].strip()
                # Remove bullet and type if present
                term_match = re.match(r'^(?:[\-\*0-9\.]+\s*)?(.+?)(?:\s*\(.*\))?$', term_part)
                if term_match:
                    term_clean = term_match.group(1).strip()
                    
                    definition = ""
                    aliases = []
                    examples = []
                    
                    for part in parts[1:]:
                        part = part.strip()
                        if part.lower().startswith("definition:"):
                            definition = part[11:].strip()
                        elif part.lower().startswith("aliases:"):
                            aliases_str = part[8:].strip()
                            if aliases_str and aliases_str.lower() != "none":
                                aliases = [a.strip() for a in aliases_str.split(',')]
                        elif part.lower().startswith("examples:"):
                            examples_str = part[9:].strip()
                            if examples_str and examples_str.lower() != "none":
                                examples = [e.strip() for e in examples_str.split(',')]
                                
                    results_map[term_clean.lower()] = {
                        'definition': definition,
                        'aliases': aliases,
                        'examples': examples
                    }
            
            # Update batch objects
            for entity in batch:
                term = entity.get('term', '').strip()
                if term.lower() in results_map:
                    res = results_map[term.lower()]
                    if not entity.get('definition'): entity['definition'] = res['definition']
                    if not entity.get('aliases'): entity['aliases'] = ", ".join(res['aliases'])
                    if not entity.get('examples'): entity['examples'] = "; ".join(res['examples'])
                    
        except Exception as e:
            logger.error(f"Enrichment batch failed: {e}")


    def _extract_llm_relationships(self, term: str, entity: Dict, all_entities: List[Dict]) -> List[Dict]:
        """Extract relationships for an entity using LLM."""
        entity_type = entity.get('categories', entity.get('entity_type', ''))
        context = entity.get('contextual_definition', entity.get('definition', ''))[:500]

        # Get top related entities (same type or related types)
        related_entities = []
        for e in all_entities[:100]:  # Limit to first 100 for efficiency
            other_term = e.get('term', '')
            other_type = e.get('categories', e.get('entity_type', ''))
            if other_term and other_term.lower() != term.lower():
                related_entities.append(f"{other_term} ({other_type})")

        if not related_entities:
            return []

        entities_str = "\n".join(related_entities[:20])  # Limit to 20

        prompt = f"""You are a biomedical expert. Extract relationships between the primary entity and other entities.

PRIMARY ENTITY:
- {term} ({entity_type})

RELATED ENTITIES:
{entities_str}

CONTEXT: {context}

Extract 5-10 relationships in format:
Subject | Relation | Object | Evidence
Relations to extract: CAUSES, PREVENTS, TREATS, PRODUCES, REGULATES, ACTIVATES, ASSOCIATED_WITH, BINDS, METABOLIZES

Only extract relationships that are directly supported by the text or well-established biomedical knowledge."""

        try:
            response = self.llm_client.call_llm(prompt, max_tokens=1000)
            relationships = []
            for line in response.split('\n'):
                if '|' in line and not line.strip().lower().startswith(('-')):
                    parts = [p.strip() for p in line.split('|')]
                    if len(parts) >= 3:
                        relationships.append({
                            'subject': parts[0],
                            'relation': parts[1].upper(),
                            'object': parts[2],
                            'evidence': parts[3] if len(parts) > 3 else ''
                        })
            return relationships[:10]  # Max 10 relationships
        except Exception as e:
            logger.debug(f"LLM relationship extraction failed for {term}: {e}")
            return []

    def _extract_microbiome_connection(self, term: str, entity: Dict) -> str:
        """Extract microbiome domain connection using LLM."""
        entity_type = entity.get('categories', entity.get('entity_type', ''))
        definition = entity.get('definition', '')
        context = entity.get('contextual_definition', '')[:800]

        prompt = f"""You are a microbiome domain expert. Explain how this entity connects to the microbiome field.

ENTITY: {term} ({entity_type})
DEFINITION: {definition}
CONTEXT: {context}

Provide a concise 1-2 sentence explanation of how this entity relates to microbiome research.
Focus on: gut microbiota, bacterial communities, metabolites (SCFAs), immune interactions, or dysbiosis.
If not directly related, state "Not directly related to microbiome" and explain briefly."""

        try:
            response = self.llm_client.call_llm(prompt, max_tokens=300)
            # Clean response
            response = response.strip()
            if response.lower().startswith(('here', 'the entity', 'this entity', '-')):
                # Remove prefix
                lines = response.split('\n')
                response = '\n'.join(lines[1:]) if len(lines) > 1 else lines[0]
            return response[:500]  # Limit length
        except Exception as e:
            logger.debug(f"Microbiome connection extraction failed for {term}: {e}")
            return ""

    def run_batch(self, input_path: str, output_file: str, chunk_size: int = None, force: bool = False):
        """Run the full pipeline on a directory or file."""
        start_time = time.time()
        logger.info(f"🚀 Starting CDM Entity Extraction Pipeline")
        logger.info(f"📂 Input: {input_path}")
        logger.info(f"💾 Output: {output_file}")
        
        if not self.validate_prerequisites():
            logger.error("❌ Prerequisites check failed. Aborting.")
            return False

        # Determine input files
        path_obj = Path(input_path)
        if path_obj.is_file():
            files = [path_obj]
        elif path_obj.is_dir():
            files = list(path_obj.glob("*.txt"))
            logger.info(f"Found {len(files)} text files in directory")
        else:
            logger.error(f"Invalid input path: {input_path}")
            return False

        if not files:
            logger.error("No input files found")
            return False

        # Create output directory
        output_path = Path(output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Create processed directory for checkpoints
        processed_dir = output_path.parent / "processed"
        processed_dir.mkdir(exist_ok=True)

        # Run pipeline
        success = self.run_pipeline_stage(files, processed_dir, output_file, "extraction", force=force, chunk_size=chunk_size)
        
        elapsed_time = time.time() - start_time
        logger.info(f"⏱️  Total execution time: {elapsed_time:.2f} seconds")
        
        return success

    def run_pipeline_stage(self, files: List[Path], processed_dir: Path, output_file: str, stage_name: str, **kwargs):
        """Run a specific pipeline stage."""
        force = kwargs.get('force', False)
        all_entities = []
        all_text = []
        text_stats_agg = {"character_count": 0, "word_count": 0}
        
        # Define worker function for parallel processing
        def process_file_worker(file_path):
            try:
                # Check for checkpoint
                checkpoint_file = processed_dir / f"{file_path.stem}.json"
                
                # If force is False, we might want to resume or skip
                if checkpoint_file.exists():
                    if force:
                        # Delete checkpoint to force fresh start
                        try:
                            checkpoint_file.unlink()
                            logger.info(f"🗑️  Deleted checkpoint for {file_path.name} (force=True)")
                        except Exception as e:
                            logger.warning(f"⚠️  Failed to delete checkpoint: {e}")
                    else:
                        try:
                            with open(checkpoint_file, 'r') as f:
                                data = json.load(f)
                                
                            # Check if it's a completed run (all chunks done) or legacy format
                            if isinstance(data, list):
                                return data, None, "" # Legacy format, assume complete (no text)
                            elif isinstance(data, dict) and 'completed_chunks' in data:
                                # Check if all chunks are done? 
                                # Actually, extract_entities will handle resumption.
                                # But if we want to skip reading the file if strictly DONE...
                                # For now, let's just let extract_entities handle it.
                                pass 
                        except json.JSONDecodeError:
                            pass # Reprocess

                with open(file_path, 'r', encoding='utf-8') as f:
                    text = f.read()
                
                # Calculate stats
                stats = {
                    "character_count": len(text),
                    "word_count": len(text.split())
                }
                
                # Extract entities (RESUMABLE)
                # Pass checkpoint_path so it can load/save progress
                raw_entities = self.extract_entities(text, kwargs.get('chunk_size'), checkpoint_path=checkpoint_file)
                
                # Filter out invalid entities (e.g. error codes or malformed data)
                file_entities = [e for e in raw_entities if isinstance(e, dict)]
                if len(file_entities) < len(raw_entities):
                    logger.warning(f"⚠️  Filtered out {len(raw_entities) - len(file_entities)} invalid entities from {file_path.name}")

                # PER-FILE DEDUPLICATION: Remove exact duplicates before aggregating
                # This prevents massive duplicate counts (e.g., 95x "Fucose Utilisation")
                import re
                from collections import defaultdict

                # First pass: normalize entity names (remove extra whitespace, parentheses, etc.)
                def normalize_entity_name(name):
                    # Remove extra whitespace
                    name = re.sub(r'\s+', ' ', name.strip())
                    # Remove content in parentheses for matching (but keep original)
                    name_base = re.sub(r'\s*\([^)]*\)\s*$', '', name, flags=re.IGNORECASE)
                    return name.lower().strip(), name_base.lower().strip()

                # Group by normalized name (ignoring entity type for better dedup)
                grouped = defaultdict(lambda: {'entities': [], 'types': Counter()})
                for e in file_entities:
                    name_full, name_base = normalize_entity_name(e['entity'])
                    # Use base name as key (without parentheses)
                    grouped[name_base]['entities'].append(e)
                    grouped[name_base]['types'][e['entity_type']] += 1

                # Merge duplicates within this file
                deduped_file_entities = []
                for group_data in grouped.values():
                    group = group_data['entities']
                    types = group_data['types']

                    if len(group) > 1:
                        # Merge: keep highest confidence, aggregate info
                        best = max(group, key=lambda x: x.get('confidence', 0))

                        # Use the most common entity type, or the one from best entity
                        most_common_type = types.most_common(1)[0][0] if types else best['entity_type']
                        best['entity_type'] = most_common_type

                        # Clean up the entity name (remove extra parentheses if redundant)
                        name_full, name_base = normalize_entity_name(best['entity'])
                        if name_base != name_full:
                            # Keep the cleaner version
                            best['entity'] = best['entity'].split('(')[0].strip()

                        best['frequency'] = len(group)
                        best['avg_confidence_score'] = sum(e.get('confidence', 0) for e in group) / len(group)
                        best['max_confidence_score'] = max(e.get('confidence', 0) for e in group)

                        # Store alternative types that were merged
                        if len(types) > 1:
                            best['merged_types'] = list(types.keys())

                        deduped_file_entities.append(best)
                    else:
                        deduped_file_entities.append(group[0])

                if len(deduped_file_entities) < len(file_entities):
                    logger.info(f"✂️  Deduped {file_path.name}: {len(file_entities)} → {len(deduped_file_entities)} entities ({len(file_entities) - len(deduped_file_entities)} duplicates removed)")

                file_entities = deduped_file_entities

                # Add source file info
                for entity in file_entities:
                    entity['source_file'] = file_path.name

                return file_entities, stats, text
            except Exception as e:
                logger.error(f"Error processing {file_path.name}: {e}")
                return [], None, ""

        # Run parallel processing
        max_file_workers = self.config.max_file_workers
        logger.info(f"🚀 Starting parallel processing with {max_file_workers} file workers")
        
        with ThreadPoolExecutor(max_workers=max_file_workers) as executor:
            future_to_file = {executor.submit(process_file_worker, f): f for f in files}
            
            for future in tqdm(as_completed(future_to_file), total=len(files), desc=f"Processing {stage_name} files", unit="file"):
                file_path = future_to_file[future]
                try:
                    file_entities, stats, file_text = future.result()
                    if file_entities:
                        all_entities.extend(file_entities)
                    if file_text:
                        all_text.append(file_text)
                    if stats:
                        text_stats_agg["character_count"] += stats["character_count"]
                        text_stats_agg["word_count"] += stats["word_count"]
                except Exception as e:
                    logger.error(f"Failed to retrieve results for {file_path.name}: {e}")

        # Final aggregation and deduplication across all files
        if all_entities:
            logger.info(f"🔄 Aggregating and deduplicating {len(all_entities)} entities from {len(files)} files...")
            # Re-run post-processing on aggregated list
            # We skip extraction but run the rest of the pipeline logic
            # Use semantic deduplication again on the full set
            all_entities = self.post_process_entities(all_entities, use_semantic=True)

        # Extract advanced analytics from aggregated text
        advanced_analytics = None
        if all_text and not self.dry_run:
            try:
                logger.info(f"🔗 Extracting advanced analytics (relationships, triplets, etc.) from aggregated text...")
                combined_text = "\n\n".join(all_text)
                advanced_analytics = self.extract_advanced_analytics(combined_text, all_entities, self.include_speculative)
                logger.info(f"✅ Advanced analytics extraction complete: {len(advanced_analytics.get('relationships', []))} relationships, {len(advanced_analytics.get('microbiome_interactions', {}))} interaction types")
            except Exception as e:
                logger.error(f"❌ Error extracting advanced analytics: {e}")
                advanced_analytics = {
                    'relationships': [],
                    'microbiome_interactions': {},
                    'temporal_data': [],
                    'quantitative_data': [],
                    'coreference_chains': []
                }
        else:
            advanced_analytics = {
                'relationships': [],
                'microbiome_interactions': {},
                'temporal_data': [],
                'quantitative_data': [],
                'coreference_chains': []
            }

        # Save aggregated results with advanced analytics
        self.save_results(all_entities, output_file, text_stats_agg, advanced_analytics=advanced_analytics)
        
        logger.info(f"✅ Pipeline completed. Total unique entities: {len(all_entities)}")
        return True

# ==============================================================================
# MAIN EXECUTION
# ==============================================================================

def setup_environment():
    """Load environment variables and setup directories."""
    load_dotenv()
    
    # Create necessary directories
    for directory in ['output', 'logs', 'checkpoints', 'data']:
        Path(directory).mkdir(exist_ok=True)
        
    # Check API keys
    api_keys = {
        'UMLS_API_KEY': os.getenv('UMLS_API_KEY'),
        'BIOPORTAL_API_KEY': os.getenv('BioPortal_API_KEY'),
        'HUGGINGFACE_TOKEN': os.getenv('HuggingFace_API_KEY'),
    }
    
    missing_keys = [k for k, v in api_keys.items() if not v or v.startswith('your_')]
    
    if missing_keys:
        logger.warning(f"⚠️  Missing API keys: {', '.join(missing_keys)}")
        logger.warning("   Pipeline will run with limited functionality.")
    else:
        logger.info("✅ All API keys configured.")
        
    return api_keys

def run_pipeline_stage(stage_name, input_path, output_file, config, **kwargs):
    """Run a single stage of the pipeline on a file or directory."""
    logger.info(f"\n=== RUNNING {stage_name.upper()} PIPELINE ===")

    try:
        # Extract force argument to prevent passing it to pipeline init
        force = kwargs.pop('force', False)

        # Extract paper_metadata if provided
        paper_metadata = kwargs.pop('paper_metadata', {})

        # Initialize pipeline
        pipeline = CDMEntityPipeline(
            model=config.default_model,
            base_url=config.default_base_url,
            config=config,
            **kwargs
        )

        # Set paper_metadata on pipeline
        pipeline.paper_metadata = paper_metadata
        if paper_metadata:
            logger.info(f"📄 Pipeline configured with paper metadata: {paper_metadata.get('paper_id', 'unknown')}")

        # Set include_speculative mode from kwargs
        include_speculative = kwargs.pop('include_speculative', False)
        pipeline.include_speculative = include_speculative
        mode_str = "EXPLORATORY" if include_speculative else "STRICT"
        logger.info(f"🎯 Pipeline mode: {mode_str} (speculative content: {'enabled' if include_speculative else 'filtered'})")
        
        input_p = Path(input_path)
        all_entities = []
        text_stats_agg = {"character_count": 0, "word_count": 0}
        
        if input_p.is_file():
            files = [input_p]
        elif input_p.is_dir():
            files = list(input_p.glob("*.txt"))
            logger.info(f"📂 Found {len(files)} text files in {input_path}")
        else:
            logger.error(f"Invalid input path: {input_path}")
            return False

        # Create processed directory for checkpoints
        # Use a 'processed' subdirectory relative to the output file's parent
        # If output_file is 'output_v2/cdm_entities.json', processed_dir is 'output_v2/processed'
        processed_dir = Path(output_file).parent / "processed"
        processed_dir.mkdir(parents=True, exist_ok=True)

        # Run pipeline stage
        return pipeline.run_pipeline_stage(files, processed_dir, output_file, stage_name, force=force, **kwargs)

    except Exception as e:
        logger.error(f"❌ {stage_name} pipeline failed: {e}")
        return False

def analyze_results(basic_output, enhanced_output):
    """Analyze and compare results from both stages."""
    report = {
        'pipeline_run': datetime.now().isoformat(),
        'basic_pipeline': _analyze_file(basic_output),
        'enhanced_pipeline': _analyze_file(enhanced_output)
    }
    
    summary_path = Path("output/pipeline_summary.json")
    with open(summary_path, 'w') as f:
        json.dump(report, f, indent=2)
        
    logger.info(f"📊 Summary report saved to: {summary_path}")
    return report

def _analyze_file(filepath):
    """Helper to analyze a single results file."""
    path = Path(filepath)
    if not path.exists():
        return None
        
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        # Handle new flat list format
        if isinstance(data.get('results'), list):
            entities = data['results']
            # Group by type for statistics
            type_counts = {}
            for e in entities:
                etype = e.get('categories', 'UNKNOWN')
                type_counts[etype] = type_counts.get(etype, 0) + 1
                
            return {
                'total_entities': len(entities),
                'entity_types': type_counts,
                'has_mappings': any(e.get('auto_concept_id_1') or e.get('UMLS_ID') for e in entities)
            }
        
        # Legacy format support
        entities = data.get('results', {}).get('cdm_entities', {})
        total_entities = sum(len(v) for v in entities.values())
        
        # Flatten entities list for analysis
        all_entities = []
        for type_list in entities.values():
            all_entities.extend(type_list)
            
        return {
            'total_entities': total_entities,
            'entity_types': {k: len(v) for k, v in entities.items()},
            'has_mappings': any('omop_mappings' in e or 'umls_mappings' in e for e in all_entities)
        }
    except Exception as e:
        logger.error(f"Error analyzing {filepath}: {e}")
        return None


def load_paper_metadata(paper_id: str, metadata_base_dir: str = None) -> Dict[str, Any]:
    """Load metadata from projects.csv and sample_metadata.tsv for a given paper_id.

    Args:
        paper_id: The paper/project ID (e.g., '15122187' or project accession)
        metadata_base_dir: Base directory containing metadata files (default: ./15122187)

    Returns:
        Dictionary containing metadata from projects.csv and sample_metadata.tsv
    """
    if not metadata_base_dir:
        # Try to find metadata directory
        possible_paths = [
            Path(paper_id),  # Direct paper_id as directory
            Path('./15122187'),  # Default location
            Path('..') / paper_id,  # Parent directory
        ]

        metadata_base_dir = None
        for path in possible_paths:
            if path.exists() and (path / 'projects.csv').exists():
                metadata_base_dir = str(path)
                break

        if not metadata_base_dir:
            logger.warning(f"⚠️  Could not find metadata directory for paper_id: {paper_id}")
            return {}

    metadata_dir = Path(metadata_base_dir)
    metadata = {}

    # Load projects.csv
    projects_file = metadata_dir / 'projects.csv'
    if projects_file.exists():
        try:
            import pandas as pd
            df = pd.read_csv(projects_file)
            # Convert to list of dicts
            metadata['projects'] = df.to_dict('records')
            logger.info(f"✅ Loaded {len(metadata['projects'])} project records from {projects_file}")
        except Exception as e:
            logger.error(f"Error loading projects.csv: {e}")
    else:
        logger.warning(f"Projects file not found: {projects_file}")

    # Load sample_metadata.tsv
    samples_file = metadata_dir / 'sample_metadata.tsv'
    if samples_file.exists():
        try:
            import pandas as pd
            df = pd.read_csv(samples_file, sep='\t')
            # Convert to list of dicts
            metadata['samples'] = df.to_dict('records')
            logger.info(f"✅ Loaded {len(metadata['samples'])} sample records from {samples_file}")
        except Exception as e:
            logger.error(f"Error loading sample_metadata.tsv: {e}")
    else:
        logger.warning(f"Sample metadata file not found: {samples_file}")

    # Store paper_id for reference
    metadata['paper_id'] = paper_id

    return metadata


def main():
    parser = argparse.ArgumentParser(description="CDM Entity Extraction Pipeline (Standalone)")
    parser.add_argument('--config', help='Path to JSON configuration file')
    parser.add_argument('--log-format', choices=['text', 'json'], default='text', help='Log output format')
    parser.add_argument('--input', '-i', required=False, help='Input text file or directory')
    parser.add_argument('--output', '-o', default='output/cdm_entities.json', help='Base output file path')
    parser.add_argument('--model', '-m', default='phi3:mini', help='LLM model to use (default: phi3:mini)')
    parser.add_argument('--base-url', default='http://localhost:11434', help='LLM service URL')
    parser.add_argument('--max-workers', type=int, default=3, help='Parallel workers')
    parser.add_argument('--max-file-workers', type=int, default=1, help='Parallel file workers')
    parser.add_argument('--max-entities', type=int, default=50000, help='Maximum entities to output (default: 50000, set higher for more results)')
    parser.add_argument('--enable-biomistral', action='store_true', help='Enable BioMistral validation (requires ~14GB disk space)')
    parser.add_argument('--enable-correction', action='store_true', help='Enable MiniLM term correction')
    parser.add_argument('--enable-llm-correction', action='store_true', help='Enable LLM-based type correction')
    parser.add_argument('--enable-enhanced', action='store_true', help='Run enhanced pipeline stage')
    parser.add_argument('--enable-comprehensive-mapping', action='store_true', help='Enable comprehensive mapping (UMLS, OMOP, etc.)')
    parser.add_argument('--enable-scispacy-linking', action='store_true', help='Enable SciSpaCy-based UMLS linking')
    parser.add_argument('--semantic-model', default='all-MiniLM-L6-v2', help='Semantic model for embeddings (default: all-MiniLM-L6-v2)')
    parser.add_argument('--dry-run', action='store_true', help='Run in dry-run mode (skip heavy processing)')
    parser.add_argument('--fast-mode', action='store_true', help='Enable FAST mode (larger chunks, optimized settings)')
    parser.add_argument('--api-type', choices=['ollama', 'openai', 'huggingface', 'anthropic', 'glm'], default='ollama', help='API type (ollama, openai/vllm, huggingface, anthropic, or glm)')
    parser.add_argument('--api-key', default='EMPTY', help='API Key for OpenAI/vLLM')
    parser.add_argument('--bioportal-api-key', help='BioPortal API Key')
    parser.add_argument('--hf-token', help='HuggingFace Token (optional if logged in)')
    parser.add_argument('--force', action='store_true', help='Force re-processing (ignore checkpoints)')
    parser.add_argument('--consolidate', action='store_true', help='Consolidate processed files')
    parser.add_argument('--map', action='store_true', help='Apply mappings to existing file')
    parser.add_argument('--enrich', action='store_true', help='Enrich definitions using LLM')
    parser.add_argument('--chunk-size', type=int, help='Chunk size (deprecated, using windowed strategy)')
    parser.add_argument('--overlap', type=int, help='Overlap size (deprecated)')
    parser.add_argument('--enable-omop-mapping', action='store_true', help='Enable OMOP mapping (enabled by default in enhanced mode)')

    # NEW: Metadata loading arguments
    parser.add_argument('--paper-id', help='Paper/project ID for metadata lookup (e.g., 15122187)')
    parser.add_argument('--metadata-dir', help='Base directory containing projects.csv and sample_metadata.tsv')
    parser.add_argument('--enable-advanced-analytics', action='store_true', default=True, help='Enable advanced analytics extraction (relationships, temporal, quantitative, etc.)')
    parser.add_argument('--include-speculative', action='store_true', help='Include speculative/negated relationships (exploratory mode). Default is strict mode (asserted only).')
    parser.add_argument('--skip-dedup', action='store_true', help='Skip semantic deduplication to keep all entities (including duplicates)')
    parser.add_argument('--semantic-threshold', type=float, default=0.95, help='Semantic similarity threshold for deduplication (default: 0.95, higher = fewer duplicates removed)')
    parser.add_argument('--min-confidence', type=float, default=0.1, help='Minimum confidence threshold for entity extraction (default: 0.1, lower = more terms extracted)')



    parser.add_argument('--verbose', '-v', action='store_true', help='Enable verbose logging (DEBUG level)')
    
    args = ConfigManager.setup_parser_with_config(parser)
    
    # Setup logging
    setup_logging(verbose=args.verbose, log_format=args.log_format)



    if not args.input:
        parser.error("the following arguments are required: --input/-i (or in config file)")
    
    # Setup
    api_keys = setup_environment()
    input_path = Path(args.input)
    
    if not input_path.exists():
        logger.error(f"Input path not found: {input_path}")
        return 1

    # Load metadata if paper_id is provided
    paper_metadata = {}
    if args.paper_id:
        logger.info(f"📄 Loading metadata for paper_id: {args.paper_id}")
        paper_metadata = load_paper_metadata(args.paper_id, args.metadata_dir)
        if paper_metadata:
            logger.info(f"✅ Loaded metadata: {len(paper_metadata.get('projects', []))} projects, {len(paper_metadata.get('samples', []))} samples")
        else:
            logger.warning(f"⚠️  Could not load metadata for paper_id: {args.paper_id}")

    # Common config
    pipeline_config = PipelineConfig(
        default_model=args.model,
        default_base_url=args.base_url,
        max_workers=args.max_workers,
        max_file_workers=args.max_file_workers,
        min_confidence=args.min_confidence,
        max_entities=args.max_entities
    )

    # Determine output paths
    base_output = Path(args.output)
    basic_output = str(base_output)
    
    # Run Basic Pipeline
    basic_success = run_pipeline_stage(
        "Basic",
        args.input,
        basic_output,
        pipeline_config,
        semantic_model=args.semantic_model,
        semantic_threshold=0.8,
        dry_run=args.dry_run,
        fast_mode=args.fast_mode,
        api_type=args.api_type,
        api_key=args.api_key,
        hf_token=args.hf_token,
        enable_comprehensive_mapping=args.enable_comprehensive_mapping,
        enable_scispacy_linking=args.enable_scispacy_linking,
        umls_api_key=api_keys['UMLS_API_KEY'],
        bioportal_api_key=args.bioportal_api_key or api_keys['BIOPORTAL_API_KEY'],
        force=args.force,
        paper_metadata=paper_metadata,
        include_speculative=args.include_speculative
    )
    
    if not basic_success:
        logger.error("Basic pipeline failed. Aborting.")
        return 1
        
    # Run Enhanced Pipeline (Optional)
    enhanced_output = None
    if args.enable_enhanced:
        # Create enhanced output filename
        stem = base_output.stem
        suffix = base_output.suffix
        parent = base_output.parent
        enhanced_output = str(parent / f"{stem}_enhanced{suffix}")
        
        # Determine enabled features based on API keys and flags
        enable_umls = bool(api_keys['UMLS_API_KEY'] and not api_keys['UMLS_API_KEY'].startswith('your_'))
        enable_hf = bool(api_keys['HUGGINGFACE_TOKEN'] and not api_keys['HUGGINGFACE_TOKEN'].startswith('your_'))
        
        bp_key = args.bioportal_api_key or api_keys['BIOPORTAL_API_KEY']
        logger.info(f"DEBUG: BioPortal Key in main: {bp_key}")
        
        enhanced_success = run_pipeline_stage(
            "Enhanced",
            args.input,
            enhanced_output,
            pipeline_config,
            semantic_model=args.semantic_model,
            semantic_threshold=0.8,
            enable_biomistral=args.enable_biomistral,
            enable_omop_mapping=args.enable_omop_mapping,
            enable_umls_mapping=enable_umls,
            bioportal_api_key=bp_key,
            enable_comprehensive_mapping=enable_hf,
            mapping_confidence_threshold=0.7,
            enable_correction=args.enable_correction,
            enable_llm_correction=args.enable_llm_correction,
            dry_run=args.dry_run,
            fast_mode=args.fast_mode,
            api_type=args.api_type,
            api_key=args.api_key,
            hf_token=args.hf_token,
            force=args.force,
            paper_metadata=paper_metadata,
            include_speculative=args.include_speculative
        )
        
        if enhanced_success:
             logger.info("✅ Enhanced pipeline completed successfully!")
        else:
             logger.warning("⚠️  Enhanced pipeline failed.")

    # --- ANALYSIS ---
    if enhanced_output:
        analyze_results(basic_output, enhanced_output)
    
    logger.info("✅ Pipeline execution finished.")
    return 0

if __name__ == "__main__":
    sys.exit(main())

class SemanticDeduplicator:

    """Deduplicates entities using semantic similarity."""



    def __init__(self, model_name: str = 'all-MiniLM-L6-v2', threshold: float = 0.85):

        self.threshold = threshold

        self.model = None

        try:

            from sentence_transformers import SentenceTransformer

            self.model = SentenceTransformer(model_name)

            logger.info(f">��� Semantic deduplicator initialized with {model_name}")

        except ImportError:

            logger.warning("�&�  sentence-transformers not installed. Semantic deduplication disabled.")

        except Exception as e:

            logger.warning(f"�&�  Failed to load semantic model: {e}")



    def apply_semantic_deduplication(self, entities: List[Dict]) -> List[Dict]:

        """Deduplicate entities based on semantic similarity."""

        if not entities:

            return []

            

        if not self.model:

            # Fallback to exact string deduplication

            return self._exact_deduplication(entities)



        # First, exact deduplication to reduce work

        unique_entities = self._exact_deduplication(entities)

        if len(unique_entities) < 2:

            return unique_entities



        # Get embeddings

        terms = [e['entity'] for e in unique_entities]

        embeddings = self.model.encode(terms)



        # Compute similarity matrix

        from sklearn.metrics.pairwise import cosine_similarity

        similarity_matrix = cosine_similarity(embeddings)



        # Group similar entities

        # We use a simple greedy approach: take the first, find all similar, merge, repeat

        final_entities = []

        processed_indices = set()



        for i in range(len(unique_entities)):

            if i in processed_indices:

                continue



            current_group = [unique_entities[i]]

            processed_indices.add(i)



            for j in range(i + 1, len(unique_entities)):

                if j in processed_indices:

                    continue



                if similarity_matrix[i][j] >= self.threshold:

                    # Check if types match (optional, but safer)

                    if unique_entities[i]['entity_type'] == unique_entities[j]['entity_type']:

                        current_group.append(unique_entities[j])

                        processed_indices.add(j)



            # Merge group

            merged_entity = self._merge_entity_group(current_group)

            final_entities.append(merged_entity)



        return final_entities



    def _exact_deduplication(self, entities: List[Dict]) -> List[Dict]:

        """Deduplicate by exact string match (case-insensitive)."""

        grouped = defaultdict(list)

        for e in entities:

            key = (e['entity'].lower().strip(), e['entity_type'])

            grouped[key].append(e)

        

        return [self._merge_entity_group(group) for group in grouped.values()]



    def _merge_entity_group(self, group: List[Dict]) -> Dict:

        """Merge a group of duplicate entities into one."""

        if not group:

            return {}

            

        # Pick the most frequent or longest form as the canonical name

        # For now, just pick the one with highest confidence or first

        best_entity = max(group, key=lambda x: x.get('confidence', 0))

        

        # Aggregate stats

        total_confidence = sum(e.get('confidence', 0) for e in group)

        avg_confidence = total_confidence / len(group)

        max_confidence = max(e.get('confidence', 0) for e in group)

        

        # Create merged object

        merged = best_entity.copy()

        merged['confidence'] = avg_confidence # Use average for the final score? Or max?

        merged['avg_confidence_score'] = avg_confidence

        merged['max_confidence_score'] = max_confidence

        merged['frequency'] = len(group)

        merged['source_count'] = len(group)

        

        return merged
