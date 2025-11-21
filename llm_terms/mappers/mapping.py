"""
Comprehensive Mapping Module
Integrates OMOP, UMLS, and BioPortal mappings for complete biomedical entity mapping
"""

import logging
from typing import Dict, List, Optional
from .omop_mapper import OMOPMapper
from .omop_local_mapper import OMOPLocalMapper
from .umls import UMLSMapper

logger = logging.getLogger(__name__)

class ComprehensiveMapper:
    """Comprehensive mapping coordinator for all biomedical ontologies."""

    def __init__(self, umls_api_key: str = None, athena_api_url: str = None,
                 cache_mappings: bool = True, use_local_omop: bool = True,
                 omop_vocab_dir: str = None, fuzzy_threshold: int = 95, max_matches: int = 3):

        # Use local OMOP mapper by default, fallback to API mapper
        if use_local_omop:
            self.omop_mapper = OMOPLocalMapper(
                vocab_dir=omop_vocab_dir,
                fuzzy_threshold=fuzzy_threshold,
                max_matches=max_matches
            )
            logger.info("📁 Using local OMOP mapper")
        else:
            self.omop_mapper = OMOPMapper(athena_api_url=athena_api_url, cache_mappings=cache_mappings)
            logger.info("🌐 Using API-based OMOP mapper")

        # UMLS mapper (can be disabled if no API key)
        self.umls_mapper = UMLSMapper(api_key=umls_api_key, cache_size=2000) if umls_api_key else None
        if self.umls_mapper:
            logger.info("🏥 UMLS mapper initialized")
        else:
            logger.info("⚠️  UMLS mapper disabled (no API key)")

    def map_entity_comprehensive(self, entity_name: str, entity_type: str) -> Dict:
        """Perform comprehensive mapping using all available sources."""
        # Get mappings from all available sources
        umls_mappings = []
        if self.umls_mapper:
            umls_mappings = self.umls_mapper.map_entity_to_umls(entity_name, entity_type)

        omop_mappings = self.omop_mapper.map_entity_to_omop(entity_name, entity_type)

        # Calculate confidences
        umls_confidences = [m.mapping_confidence for m in umls_mappings] if umls_mappings else []
        omop_confidences = [m.mapping_confidence for m in omop_mappings] if omop_mappings else []

        return {
            'entity_name': entity_name,
            'entity_type': entity_type,
            'umls_mappings': [self.umls_mapper._mapping_to_dict(m) for m in umls_mappings] if self.umls_mapper else [],
            'omop_mappings': [vars(m) for m in omop_mappings],
            'has_any_mapping': len(umls_mappings) > 0 or len(omop_mappings) > 0,
            'umls_count': len(umls_mappings),
            'omop_count': len(omop_mappings),
            'best_confidence': max(umls_confidences + omop_confidences, default=0.0)
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
        umls_summary = self.umls_mapper.generate_umls_summary(entities) if self.umls_mapper else {"enabled": False}
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
            'omop_summary': omop_summary,
            'mappers_enabled': {
                'omop_local': isinstance(self.omop_mapper, OMOPLocalMapper),
                'umls': self.umls_mapper is not None
            }
        }
