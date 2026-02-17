"""
UMLS (Unified Medical Language System) Mapper
Maps entities to UMLS concepts and identifiers
"""

import logging
import requests
import json
from typing import Dict, List, Optional, Set
from dataclasses import dataclass

logger = logging.getLogger(__name__)

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