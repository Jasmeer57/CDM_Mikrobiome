"""
Confidence Scorer Module
========================
Calculates confidence scores for extracted entities using a hybrid approach:
1. Ontology Validation (High Trust)
2. Heuristic Analysis (Medium Trust)
3. Frequency/Consensus (Medium Trust)
4. LLM Verification (High Cost, High Accuracy - Optional)
"""

import re
import logging
from typing import Dict, List, Optional, Any
from config.cdm_config import CDMEntityConfig

logger = logging.getLogger(__name__)

class ConfidenceScorer:
    """Calculates confidence scores for extracted entities."""

    def __init__(self, entity_config: Optional[CDMEntityConfig] = None):
        self.entity_config = entity_config or CDMEntityConfig()
        
        # Microbiome-specific keywords for relevance boosting
        self.microbiome_keywords = {
            'gut', 'microbiome', 'microbiota', 'bacteria', 'bacterial', 'intestinal',
            'colon', 'fecal', 'faecal', 'stool', 'dysbiosis', 'probiotic', 'prebiotic',
            'fermentation', 'scfa', 'short-chain fatty acid', 'mucosa', 'lumen',
            'commensal', 'pathogen', 'axis', 'metabolite', 'butyrate', 'propionate', 'acetate',
            'firmicutes', 'bacteroidetes', 'proteobacteria', 'actinobacteria', 
            'enterobacteriaceae', 'lactobacillus', 'bifidobacterium'
        }

        # Confidence Constants
        self.BASE_SCORE = 0.5
        self.VALIDATED_SCORE = 0.9
        self.MAPPED_SCORE = 0.95
        self.FREQ_BOOST_LOW = 0.05
        self.FREQ_BOOST_HIGH = 0.10
        self.HEURISTIC_HIGH = 0.15
        self.HEURISTIC_MED = 0.10
        self.HEURISTIC_LOW = 0.05
        self.FORMAT_BOOST_HIGH = 0.10
        self.FORMAT_BOOST_LOW = 0.05
        self.CONTEXT_BOOST_HIGH = 0.10
        self.CONTEXT_BOOST_LOW = 0.05

    def calculate_score(self, entity: Dict, frequency_count: int = 1) -> float:
        """
        Calculate a comprehensive confidence score (0.0 - 1.0).
        
        Args:
            entity: The entity dictionary (must contain 'entity' and 'entity_type')
            frequency_count: How many times this entity has been seen in the text
        """
        term = entity.get('entity', '').strip()
        entity_type = entity.get('entity_type', '').upper()
        context = entity.get('context', '')
        
        if not term:
            return 0.0

        # Base Score (Start conservative)
        score = self.BASE_SCORE 

        # --- 1. Ontology / Knowledge Base Validation (Strongest Signal) ---
        # If the pipeline has already mapped this, or if ANY ontology ID is present, trust it high.
        
        has_ontology_match = False
        
        # Check standard known keys
        if entity.get('is_biomedically_valid') or \
           entity.get('UMLS_ID') or \
           entity.get('OMOP_ID') or \
           entity.get('Bioportal') or \
           entity.get('OLS') or \
           entity.get('has_omop_mapping'):
            has_ontology_match = True

        # Check for any key looking like an ID (e.g. MESH_ID, NCBI_ID)
        if not has_ontology_match:
            for key, value in entity.items():
                if (key.endswith('_ID') or 'mapping' in key.lower()) and value:
                    has_ontology_match = True
                    break

        if has_ontology_match:
            score = max(score, self.MAPPED_SCORE) # High confidence for ANY ontology match

        # --- 2. Heuristic Analysis (Pattern Matching) ---
        score += self._calculate_heuristic_score(term, entity_type, context)

        # --- 3. Frequency Boost (Consensus) ---
        if frequency_count > 1:
            score += self.FREQ_BOOST_HIGH
        if frequency_count > 3:
            score += self.FREQ_BOOST_LOW
            
        # --- 4. Penalties (Quality Control) ---
        score = self._apply_penalties(score, term)

        # Clamp between 0.1 and 1.0
        return round(min(max(score, 0.1), 1.0), 3)

    def _calculate_heuristic_score(self, term: str, entity_type: str, context: str) -> float:
        """Calculate score adjustment based on heuristics."""
        adjustment = 0.0
        
        # A. Type Priority (from Config)
        type_info = self.entity_config.ENTITY_TYPES.get(entity_type, {})
        priority = type_info.get('priority', 10)
        
        # Lower priority number = Core entity type = Higher confidence
        if priority <= 3: adjustment += self.HEURISTIC_HIGH
        elif priority <= 5: adjustment += self.HEURISTIC_MED
        elif priority <= 8: adjustment += self.HEURISTIC_LOW

        # B. Regex Pattern Matching
        patterns = type_info.get('patterns', [])
        if patterns:
             if any(re.search(pattern, term, re.IGNORECASE) for pattern in patterns):
                 adjustment += self.HEURISTIC_HIGH
        
        # Specific formatting bonuses
        if entity_type == 'ORGANISM' and re.search(r'^[A-Z][a-z]+\s+[a-z]+', term):
            adjustment += self.FORMAT_BOOST_HIGH # Linnaean binomial (e.g. "E. coli")
        if entity_type in ['GENE', 'PROTEIN'] and re.search(r'^[A-Z0-9\-]{2,}$', term):
            adjustment += self.FORMAT_BOOST_LOW # Gene symbol format

        # C. Context Relevance
        term_lower = term.lower()
        context_lower = context.lower()
        
        if term_lower in context_lower:
            adjustment += self.CONTEXT_BOOST_LOW
            
        # Check for microbiome keywords in context or term
        relevance_text = term_lower + ' ' + context_lower
        if any(kw in relevance_text for kw in self.microbiome_keywords):
            adjustment += self.CONTEXT_BOOST_HIGH

        return adjustment

    def _apply_penalties(self, score: float, term: str) -> float:
        """Apply penalties for suspicious terms."""
        
        # Very short terms (unless they look like genes/chemicals e.g. "pH", "O2")
        if len(term) < 3 and not re.search(r'^[A-Za-z0-9]{1,2}$', term): 
             score -= 0.2
        elif len(term) < 4:
             score -= 0.1

        # Single word terms often less confident than multi-word for some types
        if ' ' not in term:
            # But okay for genes/chemicals
            pass 

        # Excessive special characters
        special_char_ratio = sum(1 for c in term if not c.isalnum() and c != ' ') / len(term)
        if special_char_ratio > 0.3:
            score -= 0.15

        # Check for common "junk" or "stopwords" that might have slipped through
        blocklist = {'result', 'study', 'data', 'table', 'figure', 'analysis', 'using', 'used'}
        if term.lower() in blocklist:
            score -= 0.4

        return score
