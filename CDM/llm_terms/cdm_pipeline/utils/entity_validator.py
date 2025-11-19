"""
Entity Validation Utilities for CDM Pipeline
"""

import logging
import re
from typing import Dict, List, Set
from config.cdm_config import CDMEntityConfig

logger = logging.getLogger(__name__)

class EntityValidator:
    """Specialized validator for CDM entities."""

    def __init__(self):
        self.entity_config = CDMEntityConfig()
        self.stopwords = self._load_stopwords()
        self.blacklisted_terms = self._load_blacklisted_terms()

    def _load_stopwords(self) -> Set[str]:
        """Load common stopwords to filter out."""
        return {
            'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
            'of', 'with', 'by', 'from', 'up', 'about', 'into', 'through', 'during',
            'before', 'after', 'above', 'below', 'between', 'among', 'this', 'that',
            'these', 'those', 'we', 'you', 'they', 'them', 'their', 'our', 'us',
            'also', 'may', 'can', 'could', 'would', 'should', 'might', 'must',
            'however', 'therefore', 'moreover', 'furthermore', 'nevertheless',
            'although', 'because', 'since', 'while', 'whereas', 'whether'
        }

    def _load_blacklisted_terms(self) -> Set[str]:
        """Load terms that should be filtered out."""
        return {
            'data', 'analysis', 'method', 'methods', 'approach', 'approaches',
            'result', 'results', 'conclusion', 'conclusions', 'figure', 'figures',
            'table', 'tables', 'study', 'studies', 'research', 'investigation',
            'paper', 'article', 'abstract', 'introduction', 'discussion',
            'background', 'objective', 'objectives', 'aim', 'aims', 'purpose',
            'significant', 'statistical', 'statistically', 'p-value', 'p_value',
            'confidence interval', 'ci', 'sample', 'samples', 'population',
            'group', 'groups', 'control', 'experimental', 'treatment',
            'intervention', 'placebo', 'randomized', 'randomisation', 'clinical trial'
        }

    def validate_entity(self, entity_data: Dict) -> bool:
        """Validate a single entity."""
        entity_name = entity_data.get('entity', '').strip()
        entity_type = entity_data.get('entity_type', '')
        confidence = entity_data.get('confidence', 0.0)

        # Basic checks
        if not entity_name or not entity_type:
            return False

        # Length checks
        if len(entity_name) < 2 or len(entity_name) > 100:
            return False

        # Confidence check
        if confidence < 0.6:  # Minimum confidence threshold
            return False

        # Entity type check
        if entity_type not in self.entity_config.ENTITY_TYPES:
            return False

        # Content checks
        if self._is_blacklisted(entity_name):
            return False

        if self._is_stopword_only(entity_name):
            return False

        if not self._has_valid_pattern(entity_name, entity_type):
            return False

        return True

    def _is_blacklisted(self, entity_name: str) -> bool:
        """Check if entity is blacklisted."""
        entity_lower = entity_name.lower()
        return entity_lower in self.blacklisted_terms

    def _is_stopword_only(self, entity_name: str) -> bool:
        """Check if entity consists only of stopwords."""
        words = entity_name.lower().split()
        return all(word in self.stopwords for word in words)

    def _has_valid_pattern(self, entity_name: str, entity_type: str) -> bool:
        """Check if entity matches expected patterns for its type."""
        if entity_type not in self.entity_config.ENTITY_TYPES:
            return False

        type_config = self.entity_config.ENTITY_TYPES[entity_type]
        if 'patterns' not in type_config:
            return True  # No pattern restrictions

        for pattern in type_config['patterns']:
            if re.search(pattern, entity_name, re.IGNORECASE):
                return True

        return False

    def clean_entity_name(self, entity_name: str) -> str:
        """Clean and normalize entity name."""
        if not entity_name:
            return ""

        # Remove extra whitespace
        entity_name = re.sub(r'\s+', ' ', entity_name.strip())

        # Remove special characters except hyphens, periods, and common scientific symbols
        entity_name = re.sub(r'[^\w\s\-\.\(\)\[\]/]', '', entity_name)

        # Remove leading/trailing punctuation
        entity_name = entity_name.strip('.,;:!()[]{}"\'')

        return entity_name

    def filter_entities(self, entities: List[Dict]) -> List[Dict]:
        """Filter and clean a list of entities."""
        filtered_entities = []

        for entity_data in entities:
            # Clean entity name
            cleaned_name = self.clean_entity_name(entity_data.get('entity', ''))
            entity_data['entity'] = cleaned_name

            # Validate entity
            if self.validate_entity(entity_data):
                filtered_entities.append(entity_data)
            else:
                logger.debug(f"Filtered out entity: {cleaned_name} ({entity_data.get('entity_type', 'unknown')})")

        logger.info(f"🔍 Entity validation: {len(entities)} → {len(filtered_entities)} entities")
        return filtered_entities

    def calculate_confidence_boost(self, entity_data: Dict) -> float:
        """Calculate confidence boost based on entity characteristics."""
        entity_name = entity_data.get('entity', '').lower()
        entity_type = entity_data.get('entity_type', '')
        base_confidence = entity_data.get('confidence', 0.6)

        boost = 0.0

        # Boost for capitalization patterns
        if entity_type == 'GENE' and entity_name.isupper():
            boost += 0.1
        elif entity_type == 'ORGANISM' and entity_name.istitle():
            boost += 0.1

        # Boost for length
        if 5 <= len(entity_name) <= 25:
            boost += 0.05

        # Boost for scientific terms (contains numbers, specific suffixes)
        if any(char.isdigit() for char in entity_name):
            boost += 0.05
        if any(suffix in entity_name for suffix in ['ase', 'ine', 'ol', 'one', 'acid']):
            boost += 0.05

        # Cap the confidence
        return min(base_confidence + boost, 1.0)