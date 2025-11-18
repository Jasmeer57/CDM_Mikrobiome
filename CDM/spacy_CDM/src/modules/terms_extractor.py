"""
Module for extracting scientific terms using sciSpaCy models
Preserves all P1-P12 fixes from original terms.py
"""

import spacy
import logging
import re
from typing import List, Dict, Any, Tuple, Optional
from collections import defaultdict
import string
from urllib.parse import urlparse
from pathlib import Path

from src.config.settings import SciSpaCyConfig, ProcessingConfig

logger = logging.getLogger(__name__)


class TermsExtractor:
    """Extract scientific terms using multiple sciSpaCy models with comprehensive scoring"""

    def __init__(self, config: SciSpaCyConfig):
        self.config = config
        self.models = {}
        self.processing_config = ProcessingConfig()
        self._load_models()
        self._setup_stopwords()

    def _load_models(self):
        """Load all configured sciSpaCy models"""
        logger.info(f"Loading {len(self.config.models)} sciSpaCy models...")

        for model_name in self.config.models:
            try:
                nlp = spacy.load(model_name, disable=self.config.disabled_components)
                self.models[model_name] = nlp
                logger.info(f"✅ Loaded model: {model_name}")
            except Exception as e:
                logger.error(f"❌ Failed to load model {model_name}: {e}")
                logger.warning(f"   Install with: pip install https://s3-us-west-2.amazonaws.com/ai2-s2-scispacy/releases/v0.5.4/{model_name}-0.5.4.tar.gz")

    def _setup_stopwords(self):
        """Setup stopwords for P7 filter"""
        self.stopwords = {
            'a', 'an', 'and', 'are', 'as', 'at', 'be', 'by', 'for', 'from',
            'has', 'he', 'in', 'is', 'it', 'its', 'of', 'on', 'that', 'the',
            'to', 'was', 'will', 'with', 'we', 'can', 'or', 'but', 'not',
            'this', 'have', 'had', 'his', 'her', 'she', 'they', 'were',
            'been', 'have', 'having', 'do', 'does', 'did', 'than', 'there',
            'their', 'what', 'when', 'where', 'who', 'whom', 'why', 'how',
            'i', 'you', 'your', 'yours', 'our', 'ours', 'us', 'them', 'their',
            'my', 'me', 'mine', 'him', 'himself', 'herself', 'itself',
            'myself', 'yourself', 'yourselves', 'ourselves', 'themselves',
            'am', 'is', 'are', 'was', 'were', 'be', 'been', 'being'
        }

    def _extract_entities_from_model(self, nlp, text: str, model_name: str) -> List[Dict[str, Any]]:
        """Extract entities from a single model"""
        entities = []

        # Process text in chunks
        for i in range(0, len(text), self.config.batch_size):
            chunk = text[i:i + self.config.batch_size]
            doc = nlp(chunk)

            for ent in doc.ents:
                # Apply P1-P12 filters
                if self._apply_all_filters(ent.text):
                    entities.append({
                        'text': ent.text,
                        'label': ent.label_,
                        'start_char': ent.start_char + i,
                        'end_char': ent.end_char + i,
                        'model': model_name,
                        'confidence': getattr(ent, 'confidence', 0.8)  # Default confidence if not available
                    })

        return entities

    def _apply_all_filters(self, term: str) -> bool:
        """Apply all P1-P12 filters from original terms.py"""

        # P1: Minimum length
        if len(term) < self.processing_config.p1_min_length:
            return False

        # P2: Maximum canonical length
        canonical = self._canonicalize_term(term)
        if len(canonical) > self.processing_config.p2_max_length:
            return False

        # P3: No websites
        if self.processing_config.p3_no_websites and self._contains_website(term):
            return False

        # P4: Require at least one alphabetic character
        if self.processing_config.p4_require_alpha and not any(c.isalpha() for c in term):
            return False

        # P5: Remove leading non-alphabetic characters
        if self.processing_config.p5_remove_leading_non_alpha:
            term = re.sub(r'^[^a-zA-Z]+', '', term)
            if not term:
                return False

        # P6: Remove duplicates (handled at pipeline level)

        # P7: Exclude stopwords
        if self.processing_config.p7_exclude_stopwords:
            cleaned = re.sub(r'[^\w\s]', ' ', term.lower())
            words = [w for w in cleaned.split() if w not in self.stopwords]
            if not words:
                return False

        # P8: Minimum confidence (handled at pipeline level)

        # P9: Minimum science score (handled at pipeline level)

        # P10: Not all uppercase
        if self.processing_config.p10_no_all_caps and term.isupper():
            return False

        # P11: Not starting with capital letter
        if self.processing_config.p11_no_start_with_cap and term[0].isupper():
            return False

        # P12: Minimum character variety
        if self.processing_config.p12_min_char_variety > 0:
            unique_chars = set(c.lower() for c in term if c.isalpha())
            if len(unique_chars) < self.processing_config.p12_min_char_variety:
                return False

        return True

    def _canonicalize_term(self, term: str) -> str:
        """Canonicalize term for consistency"""
        # Remove extra whitespace
        term = re.sub(r'\s+', ' ', term.strip())
        # Remove leading/trailing punctuation
        term = term.strip(string.punctuation)
        # Convert to lowercase for comparison
        return term.lower()

    def _contains_website(self, term: str) -> bool:
        """Check if term contains website URL"""
        url_pattern = r'https?://[^\s]+|www\.[^\s]+|[^\s]+\.[a-zA-Z]{2,}(?:/[^\s]*)?'
        return bool(re.search(url_pattern, term, re.IGNORECASE))

    def _calculate_science_score(self, term: str, label: str) -> float:
        """Calculate science relevance score"""
        term_lower = term.lower()

        # High-scoring scientific indicators
        high_sci_indicators = [
            'enzyme', 'protein', 'gene', 'dna', 'rna', 'cell', 'bacteri', 'microbi',
            'virus', 'pathogen', 'mutation', 'sequence', 'genome', 'chromosome',
            'metabol', 'receptor', 'antibod', 'vaccine', 'drug', 'compound',
            'molecule', 'chemical', 'reaction', 'synthesis', 'analysis',
            'method', 'technique', 'assay', 'measurement', 'experiment'
        ]

        # Medium-scoring indicators
        med_sci_indicators = [
            'sample', 'patient', 'subject', 'group', 'control', 'treatment',
            'therapy', 'diagnosis', 'symptom', 'disease', 'condition',
            'factor', 'level', 'concentration', 'dose', 'response'
        ]

        score = 0.1  # Base score

        # Check for high-scoring indicators
        for indicator in high_sci_indicators:
            if indicator in term_lower:
                score += 0.4
                break

        # Check for medium-scoring indicators
        for indicator in med_sci_indicators:
            if indicator in term_lower:
                score += 0.2
                break

        # Bonus for certain entity types
        if label in ['DNA', 'RNA', 'PROTEIN', 'CELL', 'CHEMICAL', 'ORGANISM']:
            score += 0.3
        elif label in ['CANCER', 'DISEASE', 'DISORDER']:
            score += 0.2

        # Penalty for common words
        common_words = ['study', 'research', 'paper', 'article', 'result', 'finding']
        if term_lower in common_words:
            score -= 0.2

        return min(max(score, 0.0), 1.0)

    def extract_terms(self, text: str) -> List[Dict[str, Any]]:
        """Extract terms from text using all loaded models"""
        all_entities = []

        logger.info(f"Extracting terms from {len(text)} characters using {len(self.models)} models")

        for model_name, nlp in self.models.items():
            try:
                entities = self._extract_entities_from_model(nlp, text, model_name)
                all_entities.extend(entities)
                logger.info(f"   {model_name}: extracted {len(entities)} entities")
            except Exception as e:
                logger.error(f"Error processing with {model_name}: {e}")

        # Calculate scores and canonical forms
        processed_terms = []
        for entity in all_entities:
            canonical = self._canonicalize_term(entity['text'])
            science_score = self._calculate_science_score(entity['text'], entity['label'])

            processed_terms.append({
                'term': entity['text'],
                'canonical': canonical,
                'label': entity['label'],
                'start_char': entity['start_char'],
                'end_char': entity['end_char'],
                'model': entity['model'],
                'confidence': entity['confidence'],
                'science_score': science_score,
                'context': text[max(0, entity['start_char']-50):entity['end_char']+50]
            })

        logger.info(f"Total raw terms extracted: {len(processed_terms)}")
        return processed_terms

    def get_model_summary(self) -> Dict[str, Any]:
        """Get summary of loaded models"""
        return {
            'models_loaded': list(self.models.keys()),
            'models_count': len(self.models),
            'disabled_components': self.config.disabled_components,
            'batch_size': self.config.batch_size
        }