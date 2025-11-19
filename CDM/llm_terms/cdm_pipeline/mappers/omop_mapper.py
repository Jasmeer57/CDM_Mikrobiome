"""
OMOP CDM Mapper for Microbiome Entities
Maps extracted entities to OMOP Common Data Model standard vocabulary
"""

import logging
import json
import requests
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)

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