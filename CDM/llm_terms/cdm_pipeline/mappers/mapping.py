"""
Comprehensive Mapping Module
Integrates OMOP, UMLS, and BioPortal mappings for complete biomedical entity mapping
"""

import logging
from typing import Dict, List, Optional
from .omop_mapper import OMOPMapper
from .umls import UMLSMapper

logger = logging.getLogger(__name__)

class ComprehensiveMapper:
    """Comprehensive mapping coordinator for all biomedical ontologies."""

    def __init__(self, umls_api_key: str = None, athena_api_url: str = None,
                 cache_mappings: bool = True):
        self.umls_mapper = UMLSMapper(api_key=umls_api_key, cache_size=2000)
        self.omop_mapper = OMOPMapper(athena_api_url=athena_api_url, cache_mappings=cache_mappings)

    def map_entity_comprehensive(self, entity_name: str, entity_type: str) -> Dict:
        """Perform comprehensive mapping using all available sources."""
        # Get mappings from all sources
        umls_mappings = self.umls_mapper.map_entity_to_umls(entity_name, entity_type)
        omop_mappings = self.omop_mapper.map_entity_to_omop(entity_name, entity_type)

        return {
            'entity_name': entity_name,
            'entity_type': entity_type,
            'umls_mappings': [self.umls_mapper._mapping_to_dict(m) for m in umls_mappings],
            'omop_mappings': [vars(m) for m in omop_mappings],
            'has_any_mapping': len(umls_mappings) > 0 or len(omop_mappings) > 0,
            'umls_count': len(umls_mappings),
            'omop_count': len(omop_mappings),
            'best_confidence': max(
                [m.mapping_confidence for m in umls_mappings] + [m.mapping_confidence for m in omop_mappings],
                default=0.0
            )
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
        umls_summary = self.umls_mapper.generate_umls_summary(entities)
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
            'omop_summary': omop_summary
        }