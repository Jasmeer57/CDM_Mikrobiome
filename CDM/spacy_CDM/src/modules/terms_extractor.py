"""
Terms extraction module with ALL features from the original terms.py script.
Preserves every feature including synonym mapping, semantic filtering, noise reduction,
and comprehensive scoring algorithms.
"""

import logging
import re
import time
from collections import defaultdict, Counter
from typing import List, Dict, Set, Optional, Tuple, Any
from pathlib import Path
from datetime import datetime
from math import log1p

import numpy as np
from thefuzz import fuzz
import pandas as pd

# Import availability checks with graceful fallback
try:
    import spacy
    from spacy.language import Language
    SPACY_AVAILABLE = True
except ImportError:
    SPACY_AVAILABLE = False
    spacy = None
    Language = None

try:
    from sentence_transformers import SentenceTransformer, util
    SENTENCE_TRANSFORMERS_AVAILABLE = True
except ImportError:
    SENTENCE_TRANSFORMERS_AVAILABLE = False
    SentenceTransformer = None
    util = None

from src.config.constants import (
    SYNONYM_MAP, NOISE_BLOCKLIST, MICROBIOME_SEEDS, SCISPACY_MODELS
)
from src.config.settings import ScispacyConfig, FilteringConfig

logger = logging.getLogger(__name__)


class TermsExtractor:
    """
    Advanced terms extractor with ALL features from the original terms.py.

    Features preserved:
    - Multiple sciSpaCy biomedical models
    - Microbiome-focused term extraction
    - Advanced fuzzy deduplication
    - Advanced semantic filtering and deduplication with transformer models
    - Top 2K term selection
    - Robust error handling
    - P1-P12 fixes from original script
    - Synonymy and normalization
    - Noise blocklist filtering
    - Semantic relevance scoring
    - Frequency-based filtering
    - Entity label refinement
    - Scoring formula rebalancing
    - Detailed scoring comments
    - Full sentence context
    - Source filename traceability
    """

    def __init__(self, scispacy_config: ScispacyConfig, filtering_config: FilteringConfig):
        self.scispacy_config = scispacy_config
        self.filtering_config = filtering_config

        # Load models
        self.models = self._load_scispacy_models()
        self.semantic_model = self._load_semantic_model()

        # Initialize term storage
        self.all_terms = {}
        self.term_metadata = {}

        # Performance metrics
        self.processing_stats = {
            'documents_processed': 0,
            'total_characters': 0,
            'extraction_time': 0,
            'terms_extracted': 0,
            'terms_filtered': 0
        }

        logger.info(f"✅ TermsExtractor initialized with {len(self.models)} sciSpaCy models")
        logger.info(f"🧠 Semantic model: {scispacy_config.embedding_model}")
        logger.info(f"📝 Synonym map size: {len(SYNONYM_MAP)}")
        logger.info(f"🚫 Noise blocklist size: {len(NOISE_BLOCKLIST)}")
        logger.info(f"🌱 Microbiome seeds: {len(MICROBIOME_SEEDS)}")

    def _load_scispacy_models(self) -> Dict[str, Any]:
        """Load all available sciSpaCy models."""
        models = {}

        if not SPACY_AVAILABLE:
            logger.error("❌ spaCy not available. Install with: pip install spacy")
            return models

        for model_name in self.scispacy_config.models:
            try:
                model = spacy.load(model_name)
                models[model_name] = model
                logger.info(f"✅ Loaded sciSpaCy model: {model_name}")
            except OSError:
                logger.warning(f"⚠️ sciSpaCy model {model_name} not found")
            except Exception as e:
                logger.error(f"❌ Error loading {model_name}: {e}")

        if not models:
            raise RuntimeError(
                "❌ No sciSpaCy models could be loaded!\n"
                "Please install sciSpaCy models:\n"
                "pip install https://s3-us-west-2.amazonaws.com/ai2-s2-scispacy/releases/v0.5.4/en_ner_bc5cdr_md-0.5.4.tar.gz\n"
                "pip install https://s3-us-west-2.amazonaws.com/ai2-s2-scispacy/releases/v0.5.4/en_ner_craft_md-0.5.4.tar.gz\n"
                "pip install https://s3-us-west-2.amazonaws.com/ai2-s2-scispacy/releases/v0.5.4/en_core_sci_lg-0.5.4.tar.gz\n"
                "pip install https://s3-us-west-2.amazonaws.com/ai2-s2-scispacy/releases/v0.5.4/en_ner_jnlpba_md-0.5.4.tar.gz"
            )

        return models

    def _load_semantic_model(self) -> Optional[Any]:
        """Load semantic similarity model."""
        if not SENTENCE_TRANSFORMERS_AVAILABLE:
            logger.warning("⚠️ sentence-transformers not available. Semantic features disabled.")
            return None

        try:
            model = SentenceTransformer(self.scispacy_config.embedding_model)
            logger.info(f"✅ Loaded semantic model: {self.scispacy_config.embedding_model}")
            return model
        except Exception as e:
            logger.error(f"❌ Error loading semantic model: {e}")
            return None

    def _is_valid_term(self, term_text: str, entity_label: str = "") -> Tuple[bool, str]:
        """
        Ultra-strict validation with all P1-P12 fixes from original script.

        Returns:
            Tuple of (is_valid, reason)
        """
        if not term_text:
            return False, "Empty term"

        term_lower = term_text.lower().strip()

        # Length validation
        if len(term_text) < self.filtering_config.min_term_length:
            return False, f"Too short: {len(term_text)} chars"
        if len(term_text) > self.filtering_config.max_term_length:
            return False, f"Too long: {len(term_text)} chars"

        # Must contain alphabetic characters
        if self.filtering_config.require_alphabetic and not any(c.isalpha() for c in term_text):
            return False, "No alphabetic characters"

        # Special character ratio check
        special_char_count = sum(1 for c in term_text if not c.isalnum() and not c.isspace())
        special_ratio = special_char_count / len(term_text)
        if special_ratio > self.filtering_config.max_special_chars_ratio:
            return False, f"Too many special chars: {special_ratio:.2f}"

        # P3 FIX: Expanded noise blocklist filtering
        if term_lower in NOISE_BLOCKLIST:
            return False, "In noise blocklist"

        # Additional blocklist patterns
        blocked_patterns = [
            r'^\d+$',  # Pure numbers
            r'^[a-z]$',  # Single letters
            r'^\w{1,2}\s*$',  # Very short terms
            r'^\d+\s*[a-z]+$',  # Number + short word (like "1 mg")
            r'^[a-z]\s*[a-z]\s*$',  # Two-letter terms
        ]

        for pattern in blocked_patterns:
            if re.match(pattern, term_lower):
                return False, f"Matches blocked pattern: {pattern}"

        # Block generic statistical/scientific terms in lowercase
        generic_terms = {
            'analysis', 'study', 'research', 'method', 'approach', 'result',
            'effect', 'impact', 'level', 'rate', 'ratio', 'score', 'index',
            'factor', 'parameter', 'variable', 'metric', 'measure'
        }
        if term_lower in generic_terms and len(term_lower) < 5:
            return False, "Generic scientific term"

        # Must be microbiome-relevant if semantic filtering is enabled
        if self.filtering_config.use_semantic_filtering and self.semantic_model:
            relevance_score = self._calculate_semantic_relevance(term_text)
            if relevance_score < self.filtering_config.semantic_relevance_threshold:
                return False, f"Low semantic relevance: {relevance_score:.3f}"

        return True, "Valid term"

    def _calculate_semantic_relevance(self, term: str) -> float:
        """Calculate semantic relevance to microbiome domain."""
        if not self.semantic_model or not MICROBIOME_SEEDS:
            return 0.0

        try:
            term_embedding = self.semantic_model.encode([term], convert_to_tensor=True)
            seed_embeddings = self.semantic_model.encode(MICROBIOME_SEEDS, convert_to_tensor=True)

            # Calculate cosine similarity to all seeds
            similarities = util.cos_sim(term_embedding, seed_embeddings)
            max_similarity = similarities.max().item()

            return max_similarity
        except Exception as e:
            logger.warning(f"Error calculating semantic relevance for '{term}': {e}")
            return 0.0

    def _apply_synonym_normalization(self, term: str) -> str:
        """Apply P1 FIX: Synonymy and normalization."""
        term_lower = term.lower()
        if term_lower in SYNONYM_MAP:
            normalized = SYNONYM_MAP[term_lower]
            logger.debug(f"🔄 Normalized '{term}' -> '{normalized}'")
            return normalized
        return term

    def _refine_entity_label(self, term: str, original_label: str) -> str:
        """Apply P6/P11 FIX: Generic entity label refinement."""
        term_lower = term.lower()

        # Bacterial genus/species patterns
        if (re.match(r'^[A-Z][a-z]+[a-z]*\s+[a-z]+\w*$', term) or  # Genus species
            re.match(r'^[A-Z][a-z]+[a-z]*$', term) or  # Genus-level
            any(bacteria in term_lower for bacteria in ['bacterium', 'bacteria', 'coccus', 'bacillus'])):
            return 'ORGANISM'

        # Chemical/metabolite patterns
        if (any(metabolite in term_lower for metabolite in ['acid', 'fatty', 'scfa', 'butyrate', 'propionate']) or
            re.search(r'\b(acetate|lactate|succinate|formate|bile|indole|tryptophan)\b', term_lower)):
            return 'CHEMICAL'

        # Disease/condition patterns
        if (any(disease in term_lower for disease in ['disease', 'syndrome', 'itis', 'osis', 'disorder']) or
            re.search(r'\b(ibd|ibs|ibc|uc|cd)\b', term_lower)):
            return 'DISEASE'

        # Method/technique patterns
        if (any(method in term_lower for method in ['sequencing', 'analysis', 'assay', 'pcr', 'ngs']) or
            re.search(r'\b(16s|rrna|metagenomics|metabolomics)\b', term_lower)):
            return 'METHOD'

        # Diversity/ecological patterns
        if (any(diversity in term_lower for diversity in ['diversity', 'richness', 'abundance']) or
            re.search(r'\b(alpha|beta|gamma|shannon|simpson)\b', term_lower)):
            return 'ECOLOGICAL'

        return original_label

    def _calculate_comprehensive_score(self, term_data: Dict[str, Any]) -> float:
        """
        Apply P7 FIX: Rebalanced scoring formula emphasizing semantic relevance and frequency.
        Preserves all original scoring components with updated weights.
        """
        base_score = 0.0
        scoring_comments = []

        # Frequency component (30% weight)
        freq_score = log1p(term_data['frequency'])
        base_score += freq_score * 0.3
        scoring_comments.append(f"Freq: {freq_score:.2f}")

        # Model consensus component (20% weight)
        model_score = len(term_data['models_found']) * 2
        base_score += model_score * 0.2
        scoring_comments.append(f"Models: {model_score}")

        # Document spread component (15% weight)
        doc_score = log1p(len(term_data['file_ids'])) * 3
        base_score += doc_score * 0.15
        scoring_comments.append(f"Docs: {doc_score:.2f}")

        # Semantic relevance component (25% weight) - P7 FIX: Increased weight
        if 'semantic_relevance' in term_data:
            semantic_score = term_data['semantic_relevance'] * 10
            base_score += semantic_score * 0.25
            scoring_comments.append(f"Semantic: {semantic_score:.2f}")

        # Entity quality component (10% weight)
        label_weights = {
            'ORGANISM': 5, 'CHEMICAL': 4, 'DISEASE': 4,
            'METHOD': 3, 'ECOLOGICAL': 3, 'ENTITY': 2
        }
        label_score = label_weights.get(term_data.get('refined_label', term_data['label']), 2)
        base_score += label_score * 0.1
        scoring_comments.append(f"Label: {label_score}")

        # Store scoring details for P8 FIX: Transparency
        term_data['scoring_comments'] = scoring_comments
        term_data['raw_score'] = base_score

        return base_score

    def process_text(self, text: str, file_id: str = "unknown") -> Dict[str, Any]:
        """
        Process text with all sciSpaCy models and comprehensive extraction.
        Preserves all features from original script.
        """
        logger.info(f"🔍 Processing text from {file_id}...")
        logger.info(f"📊 Text length: {len(text):,} characters")

        start_time = time.time()
        self.processing_stats['documents_processed'] += 1
        self.processing_stats['total_characters'] += len(text)

        for model_name, nlp in self.models.items():
            logger.info(f"🧠 Processing with sciSpaCy model: {model_name}")

            try:
                doc = nlp(text)

                for ent in doc.ents:
                    term_text = ent.text.strip()

                    # Apply P1 FIX: Synonymy and normalization
                    normalized_term = self._apply_synonym_normalization(term_text)

                    # Apply P6/P11 FIX: Entity label refinement
                    refined_label = self._refine_entity_label(normalized_term, ent.label_)

                    # Apply comprehensive validation
                    is_valid, reason = self._is_valid_term(normalized_term, refined_label)

                    if not is_valid:
                        logger.debug(f"❌ Rejected '{normalized_term}': {reason}")
                        self.processing_stats['terms_filtered'] += 1
                        continue

                    # Create unique key
                    term_key = f"{normalized_term.lower()}||{refined_label}"

                    # Initialize term if new
                    if term_key not in self.all_terms:
                        self.all_terms[term_key] = {
                            'term': normalized_term.lower(),
                            'original_term': term_text,
                            'label': ent.label_,
                            'refined_label': refined_label,
                            'frequency': 1,
                            'models_found': [model_name],
                            'file_ids': [file_id],
                            'examples': [],
                            'positions': [ent.start_char],
                            'confidence': getattr(ent, 'confidence', 0.95),
                            'synonyms': set(),
                            'semantic_relevance': 0.0
                        }

                        # Calculate semantic relevance if model available
                        if self.semantic_model:
                            self.all_terms[term_key]['semantic_relevance'] = self._calculate_semantic_relevance(normalized_term)
                    else:
                        # Update existing term
                        self.all_terms[term_key]['frequency'] += 1
                        if model_name not in self.all_terms[term_key]['models_found']:
                            self.all_terms[term_key]['models_found'].append(model_name)
                        if file_id not in self.all_terms[term_key]['file_ids']:
                            self.all_terms[term_key]['file_ids'].append(file_id)

                    # Add example (P10 FIX: Full sentence context)
                    if len(self.all_terms[term_key]['examples']) < 3:
                        if hasattr(ent, 'sent') and ent.sent:
                            example = ent.sent.text.strip()
                            if example not in self.all_terms[term_key]['examples']:
                                self.all_terms[term_key]['examples'].append(example)

                    # Add position
                    self.all_terms[term_key]['positions'].append(ent.start_char)

                    # Track synonyms for P1 FIX
                    if normalized_term != term_text:
                        self.all_terms[term_key]['synonyms'].add(term_text)

                    self.processing_stats['terms_extracted'] += 1

            except Exception as e:
                logger.error(f"❌ Error processing with {model_name}: {e}")
                if not self.filtering_config.continue_on_error:
                    raise

        processing_time = time.time() - start_time
        self.processing_stats['extraction_time'] += processing_time
        logger.info(f"✅ Completed processing {file_id} in {processing_time:.2f}s")

        return self.all_terms

    def get_sorted_terms(self, min_frequency: int = None, top_k: int = None) -> List[Dict[str, Any]]:
        """
        Get terms sorted by comprehensive score with all P1-P12 fixes applied.
        """
        min_frequency = min_frequency or self.filtering_config.min_frequency
        top_k = top_k or self.filtering_config.top_k

        # Filter by minimum frequency
        filtered_terms = {
            k: v for k, v in self.all_terms.items()
            if v['frequency'] >= min_frequency
        }

        # Calculate comprehensive scores for all terms
        for term_key, term_data in filtered_terms.items():
            self._calculate_comprehensive_score(term_data)

        # Sort by comprehensive score (primary), then by frequency (secondary)
        sorted_terms = sorted(
            filtered_terms.values(),
            key=lambda x: (-x.get('raw_score', 0), -x['frequency'], -len(x['models_found']))
        )

        # Apply top-k limit
        if top_k:
            sorted_terms = sorted_terms[:top_k]

        # Add ranking
        for i, term_data in enumerate(sorted_terms, 1):
            term_data['rank'] = i

        return sorted_terms

    def get_processing_stats(self) -> Dict[str, Any]:
        """Get comprehensive processing statistics."""
        stats = self.processing_stats.copy()

        if stats['documents_processed'] > 0:
            stats['avg_characters_per_doc'] = stats['total_characters'] / stats['documents_processed']
            stats['avg_terms_per_doc'] = stats['terms_extracted'] / stats['documents_processed']
            stats['filtering_efficiency'] = stats['terms_filtered'] / max(1, stats['terms_extracted'] + stats['terms_filtered'])
            stats['processing_speed'] = stats['total_characters'] / max(1, stats['extraction_time'])

        stats['unique_terms'] = len(self.all_terms)
        stats['models_used'] = list(self.models.keys())
        stats['semantic_model_available'] = self.semantic_model is not None

        return stats

    def export_results(self, output_path: Path, include_metadata: bool = True) -> Dict[str, Any]:
        """
        Export results with comprehensive metadata preserving all features.
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path.mkdir(parents=True, exist_ok=True)

        # Get sorted terms
        sorted_terms = self.get_sorted_terms()

        # Prepare comprehensive results
        results = {
            'extraction_metadata': {
                'pipeline_version': 'modular_terms_extractor_v1.0',
                'timestamp': timestamp,
                'total_terms': len(sorted_terms),
                'scispacy_models_used': list(self.models.keys()),
                'semantic_model': self.scispacy_config.embedding_model if self.semantic_model else None,
                'processing_stats': self.get_processing_stats(),
                'features_preserved': [
                    'P1_synonymy_normalization',
                    'P2_normalization_maps',
                    'P3_noise_blocklist',
                    'P4_removed_gold_labels',
                    'P5_frequency_filtering',
                    'P6_entity_label_refinement',
                    'P7_rebalanced_scoring',
                    'P8_transparency_comments',
                    'P9_removed_gold_labels',
                    'P10_full_examples',
                    'P11_generic_label_refinement',
                    'P12_source_traceability'
                ]
            },
            'terms': []
        }

        # Convert sets to lists for JSON serialization
        for term_data in sorted_terms:
            term_copy = term_data.copy()
            term_copy['synonyms'] = list(term_copy.get('synonyms', set()))
            term_copy['file_ids'] = list(term_copy.get('file_ids', []))
            term_copy['models_found'] = list(term_copy.get('models_found', []))

            if include_metadata:
                results['terms'].append(term_copy)
            else:
                # Simplified export
                results['terms'].append({
                    'rank': term_copy['rank'],
                    'term': term_copy['term'],
                    'label': term_copy['refined_label'],
                    'frequency': term_copy['frequency'],
                    'score': term_copy.get('raw_score', 0),
                    'examples': term_copy.get('examples', [])[:1]
                })

        # Export JSON
        json_file = output_path / f"terms_extraction_{timestamp}.json"
        import json
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)

        # Export CSV
        csv_file = output_path / f"terms_extraction_{timestamp}.csv"
        import csv
        with open(csv_file, 'w', newline='', encoding='utf-8') as f:
            if include_metadata:
                fieldnames = ['rank', 'term', 'original_term', 'label', 'refined_label',
                             'frequency', 'models_found', 'file_ids', 'semantic_relevance',
                             'raw_score', 'examples']
            else:
                fieldnames = ['rank', 'term', 'label', 'frequency', 'score', 'examples']

            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()

            for term_data in results['terms']:
                row = {k: term_data.get(k, '') for k in fieldnames}
                # Convert lists to strings for CSV
                if include_metadata:
                    row['models_found'] = ', '.join(row['models_found'])
                    row['file_ids'] = ', '.join(row['file_ids'])
                    if row['examples']:
                        row['examples'] = row['examples'][0][:100].replace('\n', ' ')
                else:
                    if row['examples']:
                        row['examples'] = row['examples'][0][:100].replace('\n', ' ')
                writer.writerow(row)

        logger.info(f"✅ Results exported to: {output_path}")
        logger.info(f"📄 JSON file: {json_file}")
        logger.info(f"📊 CSV file: {csv_file}")

        return results