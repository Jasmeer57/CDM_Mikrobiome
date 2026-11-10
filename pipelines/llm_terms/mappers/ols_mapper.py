"""
OLS Mapper Module
Maps entities using EBI OLS API
"""

import logging
import requests
from typing import List, Dict, Optional
from dataclasses import dataclass, asdict

from .confidence_scoring import score_match

logger = logging.getLogger(__name__)

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

    def to_dict(self) -> Dict:
        return asdict(self)

class OLSMapper:
    """Maps entities using EBI OLS API (Free)."""

    def __init__(self, cache_size: int = 1000):
        self.cache = {}
        self.cache_size = cache_size
        self.base_url = "https://www.ebi.ac.uk/ols/api/search"

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
            
            response = requests.get(self.base_url, params=params, timeout=10)
            if response.status_code == 200:
                results = response.json().get('response', {}).get('docs', [])
                for result in results:
                    confidence = score_match(
                        entity_name, entity_type,
                        candidate_label=result.get('label'),
                        ontology_name=result.get('ontology_name'),
                    )
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
