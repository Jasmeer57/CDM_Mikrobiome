import logging
from typing import List, Dict

logger = logging.getLogger(__name__)

class MicrobiomeRelevanceScorer:
    """Scores entities based on relevance to microbiome research."""

    def __init__(self):
        self.microbiome_keywords = {
            'gut', 'microbiome', 'microbiota', 'bacteria', 'bacterial', 'intestinal',
            'colon', 'fecal', 'faecal', 'stool', 'dysbiosis', 'probiotic', 'prebiotic',
            'fermentation', 'scfa', 'short-chain fatty acid', 'mucosa', 'lumen',
            'commensal', 'pathogen', 'axis', 'metabolite', 'butyrate', 'propionate', 'acetate'
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
