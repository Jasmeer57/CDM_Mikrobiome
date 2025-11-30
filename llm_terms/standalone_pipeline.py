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

    # Enhanced entity type definitions based on specification
    ENTITY_TYPES = {
        'ORGANISM': {
            'description': 'Bacteria, archaea, fungi, viruses, microbiota, taxa, eukaryotic organisms',
            'examples': ['Bacteroides fragilis', 'E. coli', 'Firmicutes', 'Bacteroidetes', 'Archaea', 'Methanobrevibacter', 'Lactobacillus', 'Clostridium', 'Akkermansia', 'Homo sapiens', 'Mus musculus'],
            'patterns': [r'\b([A-Z][a-z]+[a-z]*\s+[a-z]+(?:\s+[a-z]+)*)\b|\b([A-Z][a-z]+\s+sp[p]?)\b'],
            'priority': 1
        },

        'GENE': {
            'description': 'Gene names, genetic markers, gene families, transcription factors',
            'examples': ['IL6', 'TNF-alpha', 'TLR4', 'NF-kB', 'IFN-gamma', 'p53', 'BRCA1', 'STAT3', 'NOD2'],
            'patterns': [r'\b([A-Z]{2,}[0-9]*(?:-[a-z]+)?)\b'],
            'priority': 2
        },
        'PROTEIN': {
            'description': 'Proteins, enzymes, receptors, signaling molecules, antibodies',
            'examples': ['butyrate kinase', 'lipopolysaccharide', 'cytokine', 'chemokine', 'immunoglobulin', 'hemoglobin', 'collagen'],
            'patterns': [r'\b([a-z]+(?:kinase|receptor|factor|protein|enzyme|antibody))\b'],
            'priority': 3
        },
        'CHEMICAL': {
            'description': 'Metabolites, SCFAs, drugs, compounds, biochemical substances, nutrients, hormones',
            'examples': ['butyrate', 'propionate', 'acetate', 'lactate', 'lipopolysaccharide', 'glucose', 'tryptophan', 'choline', 'carnitine', 'dopamine', 'serotonin', 'cortisol'],
            'patterns': [r'\b([a-z]+(?:ate|ine|ol|one|acid|lactate|butyrate|propionate|acetate|glucose))\b'],
            'priority': 4
        },

        'DISEASE': {
            'description': 'Diseases, conditions, disorders, syndromes, clinical terms',
            'examples': ['ulcerative colitis', 'Crohn\'s disease', 'type 2 diabetes', 'inflammation', 'obesity', 'autoimmune disease', 'cancer'],
            'patterns': [r'\b([A-Z][a-z]*(?:osis|itis|emia| syndrome| disease| disorder| cancer))\b'],
            'priority': 5
        },
        'DNA_RNA': {
            'description': 'Genetic material, sequences, nucleic acids, genes',
            'examples': ['16S rRNA', 'bacterial DNA', 'microbiome sequencing', 'RNA polymerase', 'mRNA', 'tRNA', 'mitochondrial DNA', 'plasmids'],
            'patterns': [r'\b(\d+S\s+rRNA)\b|\b([a-z]+\s+(?:DNA|RNA))\b'],
            'priority': 6
        },
        'CELL_TYPE': {
            'description': 'Cell types, immune cells, tissue types, cellular components',
            'examples': ['macrophages', 'T-cells', 'dendritic cells', 'epithelial cells', 'stem cells', 'neurons', 'hepatocytes'],
            'patterns': [r'\b([a-z]+\s+cells?)\b'],
            'priority': 7
        },
        'BIOINFO_TOOL': {
            'description': 'Bioinformatics tools, software, databases, analytical methods, algorithms',
            'examples': ['BLAST', 'Qiime2', 'MetaPhlAn', 'HUMAnN', 'DADA2', 'VSEARCH', 'Picrust2', 'LEfSe', 'Phyloseq', 'UniProt', 'NCBI', 'Python', 'R'],
            'patterns': [r'\b([A-Z]{3,})\b|\b([a-z]+(?:omics|sequencing|analysis|pipeline))\b'],
            'priority': 8
        },

        'GENOMICS': {
            'description': 'Genomics, transcriptomics, proteomics, metabolomics, omics technologies, sequencing methods',
            'examples': ['genomics', 'transcriptomics', 'proteomics', 'metabolomics', '16S rRNA sequencing', 'shotgun metagenomics', 'RNA-seq', 'ChIP-seq', 'ATAC-seq'],
            'patterns': [r'\b([a-z]+(?:omics|sequencing|genome))\b'],
            'priority': 9
        },

        'CLINICAL': {
            'description': 'Clinical terms, medical procedures, treatments, healthcare',
            'examples': ['diagnosis', 'therapy', 'treatment', 'clinical trial', 'patient', 'symptoms', 'medication', 'surgery'],
            'patterns': [r'\b([a-z]+(?:therapy|treatment|clinical|medical|patient|diagnosis))\b'],
            'priority': 10
        },
        'SCIENTIFIC_TERM': {
            'description': 'General scientific terms, biological concepts, methods, statistical methods, laboratory techniques',
            'examples': ['metabolism', 'homeostasis', 'apoptosis', 'alpha diversity', 'beta diversity', 'PCR', 'ELISA', 'western blot', 'ANOVA', 'p-value', 'correlation'],
            'patterns': [r'\b([a-z]+(?:process|mechanism|pathway|response|cycle))\b'],
            'priority': 11
        }

    }

    # Chunking strategies
    CHUNK_SIZES = {
        'small': 3000,    # < 10k chars
        'medium': 6000,   # < 50k chars
        'large': 10000,   # < 100k chars
        'xlarge': 15000   # > 100k chars
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
        }
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
    default_model: str = "gemma3:12b"
    default_base_url: str = "http://localhost:11434"
    max_workers: int = 3
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
    use_json_mode: bool = True
    chunk_size_multiplier: float = 1.0
    api_type: str = "ollama"  # ollama or openai (for vLLM)
    api_key: str = "EMPTY"    # For vLLM/OpenAI


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
    def clean_text(text: str) -> str:
        """Clean and normalize text."""
        if not text:
            return ""
        text = re.sub(r'\s+', ' ', text)
        text = re.sub(r'[^\x20-\x7E\n\t\r]', '', text)
        text = re.sub(r'\r\n|\r', '\n', text)
        return text.strip()

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

    def call_llm(self, prompt: str, max_tokens: Optional[int] = None) -> str:
        """Call LLM with structured prompt and return response."""
        if self.opt_config.api_type == "openai":
            return self._call_openai_compatible(prompt, max_tokens)
        else:
            return self._call_ollama(prompt, max_tokens)

    def _call_openai_compatible(self, prompt: str, max_tokens: Optional[int] = None) -> str:
        """Call OpenAI-compatible API (e.g., vLLM)."""
        max_retries = 3
        base_delay = 1

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.opt_config.api_key}"
        }

        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self.config['temperature'],
            "max_tokens": max_tokens or self.config['max_tokens'],
        }
        
        if self.opt_config.use_json_mode:
            payload["response_format"] = {"type": "json_object"}

        for attempt in range(max_retries):
            try:
                response = requests.post(
                    f"{self.base_url}/v1/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=self.config['timeout']
                )
                
                if response.status_code == 200:
                    data = response.json()
                    return data['choices'][0]['message']['content'].strip()
                else:
                    logger.warning(f"vLLM API error: {response.status_code} - {response.text}")
            except Exception as e:
                logger.warning(f"vLLM call failed: {e}")
            
            time.sleep(base_delay * (2 ** attempt))
            
        return ""

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
                        "num_ctx": self.config.get('num_ctx', 4096)
                    }

                }
                
                if self.opt_config.use_json_mode:
                    request_config["format"] = "json"

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

    def __init__(self, llm_client: 'LLMClient'):
        self.llm_client = llm_client
        self.entity_config = CDMEntityConfig()

    def create_extraction_prompt(self, chunk_text: str) -> str:
        """Create structured prompt for CDM entity extraction."""
        return f"""
Extract EVERY SINGLE biomedical and scientific term from this text.
Focus on capturing a comprehensive list of scientific concepts, biological entities, and medical terms.
Be EXTREMELY EXHAUSTIVE. Aim to extract 100+ terms if present.
Do not filter out common terms. If it is a scientific term, EXTRACT IT.
For longer texts, do not stop until you have extracted ALL relevant entities.

TEXT:
{chunk_text}

Return ONLY a JSON array with objects containing:
{{
  "entity": "extracted term",
  "entity_type": "one of: ORGANISM|GENE|PROTEIN|CHEMICAL|DISEASE|DNA_RNA|CELL_TYPE|BIOINFO_TOOL|GENOMICS|CLINICAL|SCIENTIFIC_TERM",
  "context": "brief context or description"
}}

CDM Entity Types and Examples:
- ORGANISM: Bacteria, archaea, fungi, viruses, taxa (e.g., "Bacteroides fragilis", "E. coli", "Firmicutes")
- GENE: Gene names, genetic markers, transcription factors (e.g., "IL6", "TNF-alpha", "p53")
- PROTEIN: Proteins, enzymes, receptors, antibodies (e.g., "butyrate kinase", "cytokine", "immunoglobulin")
- CHEMICAL: Metabolites, drugs, compounds, biochemical substances (e.g., "butyrate", "glucose", "amino acids")
- DISEASE: Diseases, conditions, disorders, syndromes (e.g., "ulcerative colitis", "diabetes", "cancer")
- DNA_RNA: Genetic material, sequences, nucleic acids (e.g., "16S rRNA", "mRNA", "mitochondrial DNA")
- CELL_TYPE: Cell types, immune cells, tissue types (e.g., "macrophages", "T-cells", "epithelial cells")
- BIOINFO_TOOL: Bioinformatics tools, software, databases (e.g., "BLAST", "Qiime", "MetaPhlAn")
- GENOMICS: Genomics, omics technologies (e.g., "genomics", "transcriptomics", "metabolomics")
- CLINICAL: Clinical terms, medical procedures, treatments (e.g., "therapy", "diagnosis", "clinical trial")
- SCIENTIFIC_TERM: General scientific concepts, biological processes, mechanisms (e.g., "metabolism", "apoptosis", "immune response")

Requirements:
1. Extract ALL scientific and biomedical terms found in the text.
2. Be EXHAUSTIVE - if it looks like a scientific term, extract it. Do not filter out terms.
3. STRICTLY EXCLUDE:
   - Person names (e.g., "Smith et al.")
   - Country names or locations (e.g., "Japan", "USA", "University of X")
   - URLs, DOIs, or reference links
   - General English words that are not scientific terms
4. Use the most appropriate entity_type from the list. Use SCIENTIFIC_TERM if unsure.
"""

    def parse_llm_response(self, response: str, chunk_num: int) -> List[Dict]:
        """Parse LLM response and extract entities."""
        entities = []
        try:
            cleaned_response = response.strip()
            json_entities = self._try_json_parsing(cleaned_response)
            if json_entities:
                entities = json_entities
            else:
                entities.extend(self._extract_from_unstructured_text(cleaned_response, chunk_num))
        except Exception as e:
            logger.error(f"Error parsing LLM response for chunk {chunk_num}: {e}")
            entities.extend(self._fallback_regex_extraction(response, chunk_num))
        return entities

    def _try_json_parsing(self, response: str) -> List[Dict]:
        """Try multiple JSON parsing strategies."""
        entities = []
        # Strategy 1: Direct JSON array parsing
        try:
            if response.startswith('[') and response.endswith(']'):
                parsed = json.loads(response)
                if isinstance(parsed, list):
                    for item in parsed:
                        if self._validate_entity(item):
                            entities.append(self._format_entity(item, 0, 0.9))
                    return entities
        except json.JSONDecodeError:
            pass

        # Strategy 2: Extract JSON from text
        try:
            json_blocks = self._extract_json_blocks(response)
            for json_block in json_blocks:
                try:
                    parsed = json.loads(json_block)
                    if isinstance(parsed, list):
                        for item in parsed:
                            if self._validate_entity(item):
                                entities.append(self._format_entity(item, 0, 0.9))
                    elif isinstance(parsed, dict) and self._validate_entity(parsed):
                        entities.append(self._format_entity(parsed, 0, 0.9))
                except json.JSONDecodeError:
                    continue
            if entities:
                return entities
        except Exception:
            pass
        return []

    def _extract_json_blocks(self, text: str) -> List[str]:
        """Extract JSON blocks from mixed text."""
        json_blocks = []
        stack = []
        start_idx = None
        for i, char in enumerate(text):
            if char == '{':
                if not stack: start_idx = i
                stack.append(char)
            elif char == '}':
                if stack:
                    stack.pop()
                    if not stack and start_idx is not None:
                        json_blocks.append(text[start_idx:i+1])
                        start_idx = None
        return json_blocks

    def _validate_entity(self, entity: Dict) -> bool:
        """Validate entity structure and content."""
        if not isinstance(entity, dict): return False
        if not all(field in entity for field in ['entity', 'entity_type']): return False
        if entity['entity_type'] not in self.entity_config.ENTITY_TYPES: return False
        entity_name = entity['entity'].strip()
        if len(entity_name) < 2 or len(entity_name) > 100: return False
        return True

    def _format_entity(self, entity: Dict, chunk_num: int, confidence: float) -> Dict:
        """Format entity into standard structure."""
        return {
            'entity': entity['entity'].strip(),
            'entity_type': entity['entity_type'],
            'context': entity.get('context', '').strip()[:200],
            'source': f'chunk_{chunk_num}',
            'confidence': confidence
        }

    def _extract_from_unstructured_text(self, text: str, chunk_num: int) -> List[Dict]:
        """Extract entities from unstructured LLM response."""
        entities = []
        lines = text.split('\n')
        for line in lines:
            line = line.strip()
            if not line or line.startswith(('#', '//', '-', '*')): continue
            for entity_type in self.entity_config.ENTITY_TYPES:
                if entity_type in line.upper():
                    entity_match = re.search(r'([A-Za-z0-9\s\-_\.]+)', line)
                    if entity_match:
                        entity = entity_match.group(1).strip()
                        if len(entity) > 2 and len(entity) < 100:
                            entities.append(self._format_entity({
                                'entity': entity,
                                'entity_type': entity_type,
                                'context': line[:100]
                            }, chunk_num, 0.7))
                    break
        return entities

    def _fallback_regex_extraction(self, text: str, chunk_num: int) -> List[Dict]:
        """Fallback extraction using regex patterns."""
        entities = []
        for entity_type, config in self.entity_config.ENTITY_TYPES.items():
            if 'patterns' in config:
                for pattern in config['patterns']:
                    matches = re.findall(pattern, text, re.IGNORECASE)
                    for match in matches:
                        if isinstance(match, tuple): match = [m for m in match if m][0] if match else ""
                        if match and len(match) > 2:
                            entities.append(self._format_entity({
                                'entity': match.strip(),
                                'entity_type': entity_type,
                                'context': f"Regex extraction from chunk {chunk_num}"
                            }, chunk_num, 0.6))
        return entities

    def _get_pass_prompt(self, pass_num: int, chunk_text: str, existing_terms: List[str] = None) -> str:
        """Generate specific prompt for each extraction pass."""
        
        system_context = """You are a comprehensive biomedical terminology extractor. Extract ALL concrete scientific terms from the text including bioinformatics, molecules, chemicals, organisms, species, and technical biomedical terms.

CRITICAL RULES:
1. Extract ALL biomedical terms: bioinformatics tools, molecules, chemicals, organisms, species, technical terms
2. Include terms from ALL biomedical domains: molecular biology, biochemistry, genetics, bioinformatics, pharmacology, etc.
3. NEVER extract your own instructions, notes, or conversational phrases
4. ONLY extract terms that would be valid entries in a biomedical ontology
5. Be EXTREMELY COMPREHENSIVE - extract any term that appears biomedical or technical in nature.
6. Do not filter out terms because they seem "too common" or "generic". If it is scientific, extract it.

VALID CATEGORIES TO EXTRACT:
- ALL biological entities (organisms, species, genera, phyla)
- ALL chemical compounds, metabolites, molecules
- ALL molecular biology terms (genes, proteins, pathways, enzymes)
- ALL bioinformatics tools, methods, and pipelines
- ALL sequencing technologies and omics platforms
- ALL statistical and computational methods
- ALL medical, clinical, and pharmaceutical terms
- ALL laboratory methods and techniques
- ALL anatomical and physiological terms
- ANY technical biomedical term

OUTPUT: Return ONLY a JSON array with objects containing:
{
  "entity": "extracted term",
  "entity_type": "one of: ORGANISM|GENE|PROTEIN|CHEMICAL|DISEASE|DNA_RNA|CELL_TYPE|BIOINFO_TOOL|GENOMICS|CLINICAL|SCIENTIFIC_TERM",
  "context": "brief context or description"
}"""

        if pass_num == 1:
            return f"""{system_context}

EXTRACTION GOAL: Extract ALL biological entities, organisms, species, and taxonomic terms from the text.

FOCUS ON:
- ALL bacterial, archaeal, fungal genera and species mentioned
- ALL viral strains and types mentioned
- ALL eukaryotic organisms mentioned (human, mouse, rat, etc.)
- ALL taxonomic ranks and classifications mentioned
- ANY organism names that appear in the text
- Species names, genus names, family names, etc.

IMPORTANT: Extract ALL biological entities you find, not just microbiome-related.

TEXT:
{chunk_text}"""

        elif pass_num == 2:
            return f"""{system_context}

EXTRACTION GOAL: Extract ALL chemical compounds, metabolites, molecules, and biochemical terms from the text.

FOCUS ON:
- ALL metabolites mentioned (SCFAs, bile acids, amino acids, lipids, etc.)
- ALL drugs, pharmaceuticals, compounds mentioned
- ALL proteins, enzymes, hormones, neurotransmitters mentioned
- ALL genes, DNA, RNA molecules mentioned
- ALL metabolic pathways and processes mentioned
- ANY chemical or molecular entity that appears in the text
- Small molecules, large molecules, organic compounds, inorganic compounds

IMPORTANT: Extract ALL chemical and molecular terms you find.

TEXT:
{chunk_text}"""

        elif pass_num == 3:
            return f"""{system_context}

EXTRACTION GOAL: Extract ALL bioinformatics tools, computational methods, and technical approaches from the text.

FOCUS ON:
- ALL sequencing platforms and methods mentioned
- ALL bioinformatics tools, software, and pipelines mentioned
- ALL statistical and computational methods mentioned
- ALL machine learning and AI approaches mentioned
- ALL database and resource names mentioned
- ANY computational or technical approach that appears in the text
- Programming languages, algorithms, data structures mentioned

IMPORTANT: Extract ALL bioinformatics and computational terms you find.

TEXT:
{chunk_text}"""

        elif pass_num == 4:
            return f"""{system_context}

EXTRACTION GOAL: Extract ALL medical, clinical, pharmaceutical, and disease-related terms from the text.

FOCUS ON:
- ALL diseases, disorders, and medical conditions mentioned
- ALL drugs, pharmaceuticals, and treatments mentioned
- ALL clinical procedures and diagnostic methods mentioned
- ALL anatomical terms and body systems mentioned
- ALL physiological processes and pathways mentioned
- ANY medical or clinical term that appears in the text

IMPORTANT: Extract ALL medical and clinical terms you find.

TEXT:
{chunk_text}"""

        elif pass_num == 5:
            existing_str = ', '.join(existing_terms[:30]) if existing_terms else "None"
            return f"""{system_context}

EXTRACTION GOAL: Extract ANY remaining biomedical terms from ALL categories that haven't been captured yet.

LOOK FOR:
- ANY scientific term related to biology, medicine, chemistry, biochemistry
- ANY technical term mentioned in the text
- ANY domain-specific terminology that appears biomedical
- ANY term that could be part of a biomedical ontology
- Laboratory techniques, experimental methods, analytical approaches
- ANY term from biomedical research that you haven't extracted yet

TERMS ALREADY EXTRACTED (examples):
{existing_str}

TEXT:
{chunk_text}"""

        elif pass_num == 6:
            return f"""{system_context}

EXTRACTION GOAL: AGGRESSIVELY extract ANY biomedical terms.
BE VERY INCLUSIVE:
- Extract ANY term that sounds scientific, technical, or biomedical
- Include method names, technique names, approach names
- Include any compound, molecule, or chemical mentioned
- Include any organism, species, or biological entity
- Include any computational, statistical, or analytical method
- Include any medical, clinical, or pharmaceutical term

TEXT:
{chunk_text}"""
        
        return self.create_extraction_prompt(chunk_text)

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

    def __init__(self, vocab_dir: str = None, fuzzy_threshold: int = 95, max_matches: int = 3):
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

    def map_entity_to_omop(self, entity_name: str, entity_type: str) -> List[OMOPMapping]:
        """Map a single entity to OMOP concepts."""
        mappings = []

        try:
            # Get entity type configuration
            entity_config = self.entity_type_mappings.get(entity_type, {})

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
                target_domain = entity_config.get('domain_id')
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

    def __init__(self, api_key: str = None, cache_size: int = 1000):
        self.api_key = api_key
        self.cache = {}
        self.cache_size = cache_size
        self.semantic_type_mappings = self._initialize_semantic_mappings()

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

    def map_entity_to_umls(self, entity_name: str, entity_type: str) -> List[UMLSMapping]:
        """Map a single entity to UMLS concepts."""
        cache_key = f"{entity_name.lower()}_{entity_type}"

        if cache_key in self.cache:
            return self.cache[cache_key]

        mappings = []

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

    def _search_umls(self, entity_name: str, expected_semantic_types: List[str]) -> List[UMLSConcept]:
        """Search UMLS API for concepts."""
        if not self.api_key:
            logger.warning("No UMLS API key provided")
            return []

        concepts = []

        try:
            # UMLS REST API search
            search_url = "https://uts-ws.nlm.nih.gov/rest/search/current"
            params = {
                "string": entity_name,
                "apiKey": self.api_key,
                "pageSize": 20,
                "returnType": "object"
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
            # Get concept details
            concept_url = f"https://uts-ws.nlm.nih.gov/rest/content/current/CUI/{cui}"
            params = {"apiKey": self.api_key}

            response = requests.get(concept_url, params=params, timeout=10)

            if response.status_code == 200:
                concept_data = response.json().get('result', {})

                # Get semantic types
                semantic_types_url = f"https://uts-ws.nlm.nih.gov/rest/content/current/CUI/{cui}/semanticTypes"
                semantic_response = requests.get(semantic_types_url, params=params, timeout=5)

                semantic_types = []
                if semantic_response.status_code == 200:
                    for sem_type in semantic_response.json().get('result', []):
                        semantic_types.append(sem_type.get('name', ''))

                # Get definitions
                definitions_url = f"https://uts-ws.nlm.nih.gov/rest/content/current/CUI/{cui}/definitions"
                definitions_response = requests.get(definitions_url, params=params, timeout=5)

                definitions = []
                if definitions_response.status_code == 200:
                    for def_data in definitions_response.json().get('result', []):
                        definitions.append(def_data.get('value', ''))

                # Get synonyms
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

class ComprehensiveMapper:
    """Comprehensive mapping coordinator for all biomedical ontologies."""

    def __init__(self, umls_api_key: str = None, athena_api_url: str = None,
                 cache_mappings: bool = True, use_local_omop: bool = True,
                 omop_vocab_dir: str = None, fuzzy_threshold: int = 95, max_matches: int = 3):

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

        # UMLS mapper (can be disabled if no API key)
        self.umls_mapper = UMLSMapper(api_key=umls_api_key, cache_size=2000) if umls_api_key else None
        if self.umls_mapper:
            logger.info("🏥 UMLS mapper initialized")
        else:
            logger.info("⚠️  UMLS mapper disabled (no API key)")

    def map_entity_comprehensive(self, entity_name: str, entity_type: str) -> Dict:
        """Perform comprehensive mapping using all available sources."""
        # Get mappings from all available sources
        umls_mappings = []
        if self.umls_mapper:
            umls_mappings = self.umls_mapper.map_entity_to_umls(entity_name, entity_type)

        omop_mappings = self.omop_mapper.map_entity_to_omop(entity_name, entity_type)

        # Calculate confidences
        umls_confidences = [m.mapping_confidence for m in umls_mappings] if umls_mappings else []
        omop_confidences = [m.mapping_confidence for m in omop_mappings] if omop_mappings else []

        return {
            'entity_name': entity_name,
            'entity_type': entity_type,
            'umls_mappings': [self.umls_mapper._mapping_to_dict(m) for m in umls_mappings] if self.umls_mapper else [],
            'omop_mappings': [vars(m) for m in omop_mappings],
            'has_any_mapping': len(umls_mappings) > 0 or len(omop_mappings) > 0,
            'umls_count': len(umls_mappings),
            'omop_count': len(omop_mappings),
            'best_confidence': max(umls_confidences + omop_confidences, default=0.0)
        }

    def map_entity_list_comprehensive(self, entities: List[Dict]) -> List[Dict]:
        """Map a list of entities comprehensively."""
        mapped_entities = []

        for entity in entities:
            entity_name = entity.get('entity', '')
            entity_type = entity.get('entity_type', '')

            if not entity_name or not entity_type:
                continue

            # Get comprehensive mapping
            comprehensive_mapping = self.map_entity_comprehensive(entity_name, entity_type)

            # Enhance entity
            enhanced_entity = {
                **entity,
                'comprehensive_mapping': comprehensive_mapping
            }

            mapped_entities.append(enhanced_entity)

        logger.info(f"🌐 Comprehensive mapping: {len(entities)} entities processed")
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
        """Calculate relevance score (0.0 - 1.0)."""
        score = 0.0
        text = entity.get('entity', '').lower()
        context = entity.get('context', '').lower()
        entity_type = entity.get('entity_type', '')

        # Keyword match in entity name
        if any(kw in text for kw in self.microbiome_keywords):
            score += 0.4
        
        # Keyword match in context
        if any(kw in context for kw in self.microbiome_keywords):
            score += 0.2

        # Type relevance
        if entity_type in self.high_relevance_types:
            score += 0.2
            
        # Specific organism bonus
        if entity_type == 'ORGANISM' and ('bacter' in text or 'cocc' in text or 'bacill' in text):
            score += 0.2

        return min(score, 1.0)

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
        """Calculate a quality score for the entity (0.0-1.0)."""
        score = 0.0

        # Base score from confidence
        score += entity.get('confidence', 0.0) * 0.4

        # Context presence bonus
        if entity.get('context', '').strip():
            score += 0.2

        # Entity length score (prefer moderate length)
        entity_length = len(entity.get('entity', ''))
        if 5 <= entity_length <= 30:
            score += 0.2
        elif 3 <= entity_length <= 50:
            score += 0.1

        # Multi-word entity bonus (often more specific)
        if len(entity.get('entity', '').split()) > 1:
            score += 0.1

        # Type appropriateness bonus
        if self._is_appropriate_type(entity.get('entity', ''), entity.get('entity_type', '')):
            score += 0.1

        return min(score, 1.0)

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
class CDMEntityPipeline:
    """Main CDM entity extraction pipeline with semantic deduplication."""

    def __init__(self, model: str = None, base_url: str = None, config: PipelineConfig = None,
                 semantic_model: str = "all-MiniLM-L6-v2", semantic_threshold: float = 0.8,
                 enable_biomistral: bool = False, biomistral_model: str = "biomistral-7B",
                 enable_biomistral_deduplication: bool = False, biomistral_dedup_model: str = "biomistral:7b",
                 enable_omop_mapping: bool = False, enable_umls_mapping: bool = False,
                 umls_api_key: str = None, enable_comprehensive_mapping: bool = False,
                 mapping_confidence_threshold: float = 0.7,
                 enable_correction: bool = False, enable_llm_correction: bool = False,
                 dry_run: bool = False, fast_mode: bool = False, api_type: str = "ollama",
                 api_key: str = "EMPTY"):
        self.config = config or PipelineConfig()
        self.dry_run = dry_run
        
        # Optimization Config
        self.opt_config = OptimizationConfig(
            fast_mode=False,
            api_key=api_key,
            chunk_size_multiplier=1.0, 
            api_type=api_type
        )
        
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
            return

        self.llm_client = LLMClient(model or self.config.default_model, base_url or self.config.default_base_url, self.opt_config)
        self.extractor = CDMEntityExtractor(self.llm_client)
        self.entity_config = CDMEntityConfig()
        self.semantic_deduplicator = SemanticDeduplicator(semantic_model, semantic_threshold)
        self.entity_filter = EntityFilter(strict_mode=True)
        self.relevance_scorer = MicrobiomeRelevanceScorer()
        self.term_corrector = MiniLMTermCorrector(semantic_model, 0.9)

        # Initialize biomedical and mapping components
        self.enable_biomistral = enable_biomistral
        self.enable_biomistral_deduplication = enable_biomistral_deduplication
        self.enable_omop_mapping = enable_omop_mapping
        self.enable_umls_mapping = enable_umls_mapping
        self.enable_comprehensive_mapping = enable_comprehensive_mapping
        self.mapping_confidence_threshold = mapping_confidence_threshold
        self.enable_correction = enable_correction
        self.enable_llm_correction = enable_llm_correction
        
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
                use_local_omop=True,  # Use local mapper by default
                omop_vocab_dir=omop_vocab_dir,
                fuzzy_threshold=95,
                max_matches=3,
                cache_mappings=True
            )
            logger.info(f"🗂️  Comprehensive mapping initialized with OMOP vocab: {omop_vocab_dir}")

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
        """Split text into overlapping chunks."""
        if chunk_size is None:
            base_chunk_size = self.extractor.calculate_optimal_chunk_size(len(text))
            chunk_size = int(base_chunk_size * self.opt_config.chunk_size_multiplier)
            
            # Cap chunk size to avoid context overflow (assuming 32k context for modern models)
            # If fast mode, we push it.
            if self.opt_config.fast_mode:
                chunk_size = min(chunk_size, 12000) # Safe limit for 16k-32k context models
            else:
                chunk_size = min(chunk_size, 6000)


        overlap = self.extractor.calculate_overlap(chunk_size)

        chunks = []
        chunk_num = 1

        for i in range(0, len(text), chunk_size - overlap):
            chunk = text[i:i + chunk_size]
            if len(chunk) > 100:  # Only process substantial chunks
                chunks.append((chunk, chunk_num))
                chunk_num += 1

        logger.info(f"📊 Created {len(chunks)} chunks ({chunk_size} chars, {overlap} overlap)")
        return chunks

    def extract_entities(self, text: str, chunk_size: int = None) -> List[Dict]:
        """Extract CDM entities using Windowed Multi-Pass Strategy (Fast & Comprehensive)."""
        logger.info(f"🔍 Starting Windowed Multi-Pass Extraction on {len(text)} characters")

        if self.dry_run:
            return [
                {"entity": "Bacteroides fragilis", "entity_type": "ORGANISM", "confidence": 0.95},
                {"entity": "butyrate", "entity_type": "CHEMICAL", "confidence": 0.92}
            ]

        all_entities = []
        text_len = len(text)
        
        # Define Windows (from Reference Script)
        # Pass 1: 0-8000
        # Pass 2: 5000-13000
        # Pass 3: 10000-18000
        # Pass 4: 15000-23000
        # Pass 5: 20000-28000
        # Pass 6: 25000-35000
        
        windows = [
            (1, text[0:8000]),
            (2, text[5000:13000] if text_len > 5000 else text[0:min(text_len, 8000)]),
            (3, text[10000:18000] if text_len > 10000 else text[0:min(text_len, 8000)]),
            (4, text[15000:23000] if text_len > 15000 else text[0:min(text_len, 8000)])
        ]
        
        # Filter out empty windows or duplicates for very short text
        valid_windows = []
        seen_texts = set()
        for p_num, w_text in windows:
            if not w_text.strip(): continue
            # For short texts, windows might be identical. Skip duplicates.
            if w_text in seen_texts: continue
            seen_texts.add(w_text)
            valid_windows.append((p_num, w_text))

        # Run Passes 1-4 in Parallel
        logger.info(f"🔄 Running Passes 1-4 in parallel ({len(valid_windows)} tasks)...")
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [
                executor.submit(self.extractor.run_extraction_pass, (w_text, p_num, [])) 
                for p_num, w_text in valid_windows
            ]
            
            for future in tqdm(as_completed(futures), total=len(valid_windows), desc="Running Passes 1-4"):
                try:
                    entities = future.result()
                    all_entities.extend(entities)
                except Exception as e:
                    logger.error(f"Error in extraction pass: {e}")

        # Check count for Pass 5 & 6
        unique_terms = {e['entity'].lower() for e in all_entities}
        logger.info(f"📊 Terms after Passes 1-4: {len(unique_terms)}")
        
        # Pass 5 (Catch-all)
        if len(unique_terms) < 100: # Target min 50-100
            logger.info("⚠️  Term count low. Running Pass 5 (Catch-all)...")
            p5_text = text[20000:28000] if text_len > 20000 else text[0:min(text_len, 8000)]
            if p5_text.strip():
                p5_entities = self.extractor.run_extraction_pass((p5_text, 5, list(unique_terms)))
                all_entities.extend(p5_entities)
                unique_terms.update({e['entity'].lower() for e in p5_entities})

        # Pass 6 (Aggressive)
        if len(unique_terms) < 50:
            logger.info("⚠️  Term count still low. Running Pass 6 (Aggressive)...")
            p6_text = text[25000:35000] if text_len > 25000 else text[0:min(text_len, 8000)]
            if p6_text.strip():
                p6_entities = self.extractor.run_extraction_pass((p6_text, 6, []))
                all_entities.extend(p6_entities)

        # Post-process entities with semantic deduplication
        processed_entities = self.post_process_entities(all_entities, use_semantic=True)

        logger.info(f"✅ Extraction complete: {len(processed_entities)} unique entities")
        return processed_entities

    def post_process_entities(self, entities: List[Dict], use_semantic: bool = False) -> List[Dict]:
        if self.dry_run:
            return entities
        """Clean, deduplicate, and sort entities with optional semantic deduplication."""
        logger.info(f"🔄 Post-processing {len(entities)} entities")

        # Basic cleaning and validation
        cleaned_entities = []
        for entity_data in entities:
            # Clean entity name
            cleaned_entity = re.sub(r'[^a-zA-Z0-9\s\-\._]', '', entity_data['entity']).strip()

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
            cleaned_entities = self.comprehensive_mapper.map_entity_list_comprehensive(cleaned_entities)
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

    def save_results(self, entities: List[Dict], output_path: str, text_stats: Dict = None):
        """Save extraction results to JSON file."""
        # Group entities by type
        grouped_entities = {}
        for entity in entities:
            # Ensure entity is a dictionary
            if not isinstance(entity, dict):
                logger.warning(f"Skipping invalid entity format: {entity}")
                continue

            entity_type = entity.get('entity_type', 'UNKNOWN')
            if entity_type not in grouped_entities:
                grouped_entities[entity_type] = []

            # Basic entity data
            entity_data = {
                'term': entity.get('entity', ''), # Changed from 'term' to 'entity' to match existing structure
                'confidence': entity.get('confidence', 0.0),
                'context': entity.get('context', ''),
                'source': entity.get('source', 'LLM'),
                'microbiome_relevance_score': entity.get('microbiome_relevance_score', 0.0), # Added from original
                'source_file': entity.get('source_file', '')
            }

            omop_mappings = []
            has_omop_mapping = False
            best_omop_confidence = 0.0
            omop_domain_id = None
            omop_concept_count = 0

            # Check for direct OMOP mappings
            if 'omop_mappings' in entity:
                omop_mappings = entity['omop_mappings']
                has_omop_mapping = entity.get('has_omop_mapping', False)
                best_omop_confidence = entity.get('best_omop_confidence', 0.0)
                omop_domain_id = entity.get('omop_domain_id')
                omop_concept_count = entity.get('omop_concept_count', 0)

            # Check for OMOP mappings in comprehensive mapping
            elif 'comprehensive_mapping' in entity:
                comp_mapping = entity['comprehensive_mapping']
                if isinstance(comp_mapping, dict) and comp_mapping.get('omop_count', 0) > 0:
                    omop_mappings = comp_mapping.get('omop_mappings', [])
                    has_omop_mapping = True
                    omop_concept_count = comp_mapping.get('omop_count', 0)
                    if omop_mappings:
                        best_omop_confidence = comp_mapping.get('best_confidence', 0.0)
                        omop_domain_id = omop_mappings[0].get('domain_id') if omop_mappings else None

            # Add OMOP mapping data to entity if available
            if omop_mappings:
                entity_data['omop_mappings'] = omop_mappings
                entity_data['has_omop_mapping'] = has_omop_mapping
                entity_data['best_omop_confidence'] = best_omop_confidence
                entity_data['omop_domain_id'] = omop_domain_id
                entity_data['omop_concept_count'] = omop_concept_count

            # Add comprehensive mapping if available
            if 'comprehensive_mapping' in entity:
                entity_data['comprehensive_mapping'] = entity['comprehensive_mapping']

            grouped_entities[entity_type].append(entity_data)

        # Generate statistics
        stats = self.generate_statistics(entities)

        # Create results structure
        results = {
            'metadata': {
                'timestamp': time.time(),
                'model_used': self.llm_client.model if self.llm_client else "dry-run",
                'pipeline_version': '1.0.0',
                'extraction_config': {
                    'min_confidence': self.config.min_confidence,
                    'max_entities': self.config.max_entities,
                    'max_workers': self.config.max_workers
                }
            },
            'text_statistics': text_stats or {},
            'extraction_statistics': stats,
            'results': {
                'entity_type_counts': {k: len(v) for k, v in grouped_entities.items()},
                'cdm_entities': grouped_entities
            }
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

            # Save results
            self.save_results(entities, output_path, text_stats)

            logger.info(f"⚡ Pipeline completed in {extraction_time:.1f} seconds")
            logger.info(f"📊 Total unique entities: {len(entities)}")

            return True

        except Exception as e:
            logger.error(f"Pipeline execution failed: {e}")
            return False

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
        'BIOPORTAL_API_KEY': os.getenv('BIOPORTAL_API_KEY'),
        'HUGGINGFACE_TOKEN': os.getenv('HUGGINGFACE_TOKEN')
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
        # Initialize pipeline
        pipeline = CDMEntityPipeline(
            model=config.default_model,
            base_url=config.default_base_url,
            config=config,
            **kwargs
        )
        
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
        processed_dir = Path(output_file).parent / "processed"
        processed_dir.mkdir(parents=True, exist_ok=True)

        # Define worker function for parallel processing
        def process_file_worker(file_path):
            try:
                # Check for checkpoint
                checkpoint_file = processed_dir / f"{file_path.stem}.json"
                if checkpoint_file.exists():
                    try:
                        with open(checkpoint_file, 'r') as f:
                            return json.load(f), None
                    except json.JSONDecodeError:
                        pass # Reprocess

                with open(file_path, 'r', encoding='utf-8') as f:
                    text = f.read()
                
                # Calculate stats
                stats = {
                    "character_count": len(text),
                    "word_count": len(text.split())
                }
                
                # Extract entities
                raw_entities = pipeline.extract_entities(text, kwargs.get('chunk_size'))
                
                # Filter out invalid entities (e.g. error codes or malformed data)
                file_entities = [e for e in raw_entities if isinstance(e, dict)]
                if len(file_entities) < len(raw_entities):
                    logger.warning(f"⚠️  Filtered out {len(raw_entities) - len(file_entities)} invalid entities from {file_path.name}")

                # Add source file info
                for entity in file_entities:
                    entity['source_file'] = file_path.name
                
                # Save checkpoint
                with open(checkpoint_file, 'w') as f:
                    json.dump(file_entities, f, indent=2)
                    
                return file_entities, stats
            except Exception as e:
                logger.error(f"Error processing {file_path.name}: {e}")
                return [], None

        # Run parallel processing
        max_file_workers = config.max_file_workers
        logger.info(f"🚀 Starting parallel processing with {max_file_workers} file workers")
        
        with ThreadPoolExecutor(max_workers=max_file_workers) as executor:
            future_to_file = {executor.submit(process_file_worker, f): f for f in files}
            
            for future in tqdm(as_completed(future_to_file), total=len(files), desc=f"Processing {stage_name} files", unit="file"):
                file_path = future_to_file[future]
                try:
                    file_entities, stats = future.result()
                    if file_entities:
                        all_entities.extend(file_entities)
                    if stats:
                        text_stats_agg["character_count"] += stats["character_count"]
                        text_stats_agg["word_count"] += stats["word_count"]
                except Exception as e:
                    logger.error(f"Failed to retrieve results for {file_path.name}: {e}")

        # Final aggregation and deduplication across all files
        if len(files) > 1:
            logger.info(f"🔄 Aggregating and deduplicating {len(all_entities)} entities from {len(files)} files...")
            # Re-run post-processing on aggregated list
            # We skip extraction but run the rest of the pipeline logic
            # Use semantic deduplication again on the full set
            all_entities = pipeline.post_process_entities(all_entities, use_semantic=True)

        # Save aggregated results
        pipeline.save_results(all_entities, output_file, text_stats_agg)
        
        logger.info(f"✅ Pipeline completed. Total unique entities: {len(all_entities)}")
        return True
        
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
        with open(path, 'r') as f:
            data = json.load(f)
            
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
    parser.add_argument('--enable-biomistral', action='store_true', help='Enable BioMistral validation (requires ~14GB disk space)')
    parser.add_argument('--enable-correction', action='store_true', help='Enable MiniLM term correction')
    parser.add_argument('--enable-llm-correction', action='store_true', help='Enable LLM-based type correction')
    parser.add_argument('--enable-enhanced', action='store_true', help='Run enhanced pipeline stage')
    parser.add_argument('--semantic-model', default='all-MiniLM-L6-v2', help='Semantic model for embeddings (default: all-MiniLM-L6-v2)')
    parser.add_argument('--dry-run', action='store_true', help='Run in dry-run mode (skip heavy processing)')
    # parser.add_argument('--fast', action='store_true', help='Enable FAST mode (larger chunks, optimized settings)')
    parser.add_argument('--api-type', choices=['ollama', 'openai'], default='ollama', help='API type (ollama or openai/vllm)')
    parser.add_argument('--api-key', default='EMPTY', help='API Key for OpenAI/vLLM')

    
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
        
    # Common config
    pipeline_config = PipelineConfig(
        default_model=args.model,
        default_base_url=args.base_url,
        max_workers=args.max_workers,
        max_file_workers=args.max_file_workers
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
        fast_mode=False,
        api_type=args.api_type
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
        
        enhanced_success = run_pipeline_stage(
            "Enhanced",
            args.input,
            enhanced_output,
            pipeline_config,
            semantic_model=args.semantic_model,
            semantic_threshold=0.8,
            enable_biomistral=args.enable_biomistral,
            enable_omop_mapping=True,
            enable_umls_mapping=enable_umls,
            umls_api_key=api_keys['UMLS_API_KEY'],
            enable_comprehensive_mapping=enable_hf,
            mapping_confidence_threshold=0.7,
            enable_correction=args.enable_correction,
            enable_llm_correction=args.enable_llm_correction,

            dry_run=args.dry_run,
            fast_mode=False,
            api_type=args.api_type,
            api_key=args.api_key
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

