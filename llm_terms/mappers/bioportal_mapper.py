import logging
import requests
from typing import List, Dict, Optional
from dataclasses import dataclass

from .confidence_scoring import score_match

logger = logging.getLogger(__name__)

@dataclass
class BioPortalMapping:
    """Mapping result from BioPortal."""
    entity_name: str
    entity_type: str
    concept_id: str
    ontology_name: str
    mapping_confidence: float
    mapping_method: str = "BioPortal_API"
    label: str = ""

    def to_dict(self) -> Dict:
        return {
            "entity_name": self.entity_name,
            "entity_type": self.entity_type,
            "concept_id": self.concept_id,
            "ontology_name": self.ontology_name,
            "mapping_confidence": self.mapping_confidence,
            "mapping_method": self.mapping_method,
            "label": self.label,
        }

class BioPortalMapper:
    """Maps entities to BioPortal ontologies."""

    def __init__(self, api_key: str = None, cache_size: int = 1000):
        self.api_key = api_key
        self.cache = {}
        self.cache_size = cache_size
        self.base_url = "http://data.bioontology.org/search"

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
            
            response = requests.get(self.base_url, params=params, timeout=10)
            if response.status_code == 200:
                results = response.json().get('collection', [])
                for result in results:
                    ontology_name = result.get('links', {}).get('ontology', '').split('/')[-1]
                    confidence = score_match(
                        entity_name, entity_type,
                        candidate_label=result.get('prefLabel'),
                        ontology_name=ontology_name,
                    )
                    if confidence > 0.4:
                        mappings.append(BioPortalMapping(
                            entity_name=entity_name,
                            entity_type=entity_type,
                            concept_id=result.get('@id', ''),
                            ontology_name=ontology_name,
                            mapping_confidence=confidence,
                            mapping_method="BioPortal_API",
                            label=result.get('prefLabel', ''),
                        ))
            else:
                 logger.warning(f"BioPortal API error: {response.status_code} - {response.text[:100]}")
            
            mappings.sort(key=lambda x: x.mapping_confidence, reverse=True)
            
        except Exception as e:
            logger.debug(f"BioPortal mapping failed for {entity_name}: {e}")

        if len(self.cache) < self.cache_size:
            self.cache[cache_key] = mappings
            
        return mappings
