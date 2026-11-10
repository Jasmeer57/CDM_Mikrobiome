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


    def __init__(self, umls_api_key: str = None, bioportal_api_key: str = None,
                 use_local_omop: bool = True, omop_vocab_dir: str = None,
                 fuzzy_threshold: int = 90, max_matches: int = 5,
                 cache_mappings: bool = True, use_scispacy: bool = False):
        logger.info("🔧 Initializing ComprehensiveMapper (FIXED VERSION)")
        self.umls_mapper = UMLSMapper(api_key=umls_api_key) if umls_api_key else None
        if use_local_omop and omop_vocab_dir:
            self.omop_mapper = OMOPLocalMapper(vocab_dir=omop_vocab_dir)
        else:
            self.omop_mapper = OMOPMapper()
        
        # Initialize BioPortal Mapper
        self.bioportal_mapper = None
        if bioportal_api_key:
            from .bioportal_mapper import BioPortalMapper
            self.bioportal_mapper = BioPortalMapper(api_key=bioportal_api_key)
            
        # Initialize OLS Mapper (No API key needed usually)
        from .ols_mapper import OLSMapper
        self.ols_mapper = OLSMapper()

        self.fuzzy_threshold = fuzzy_threshold
        self.max_matches = max_matches
        self.cache_mappings = cache_mappings
        self.mapping_cache = {}
        
        # SciSpaCy (Optional)
        self.nlp = None
        if use_scispacy:
            try:
                import spacy
                import scispacy
                from scispacy.linking import EntityLinker
                self.nlp = spacy.load("en_core_sci_sm")
                self.nlp.add_pipe("scispacy_linker", config={"resolve_abbreviations": True, "linker_name": "umls"})
                logger.info("✅ SciSpaCy initialized for UMLS linking")
            except Exception as e:
                logger.warning(f"⚠️ Failed to initialize SciSpaCy: {e}")

    def map_entity_comprehensive(self, term: str, entity_type: str) -> Dict:
        """Map a single entity using all available mappers."""
        results = {
            'term': term,
            'entity_type': entity_type,
            'bioportal_mappings': [],
            'ols_mappings': [],
            'umls_mappings': [],
            'omop_mappings': [],
            'has_any_mapping': False
        }
        
        # 1. BioPortal Mapping
        if self.bioportal_mapper:
            try:
                bp_results = self.bioportal_mapper.map_entity(term, entity_type)
                if bp_results:
                    results['bioportal_mappings'] = [r.to_dict() for r in bp_results[:self.max_matches]]
                    results['has_any_mapping'] = True
            except Exception as e:
                logger.warning(f"BioPortal mapping failed for {term}: {e}")
                
        # 2. OLS Mapping
        if self.ols_mapper:
            try:
                ols_results = self.ols_mapper.map_entity(term, entity_type)
                if ols_results:
                    results['ols_mappings'] = [r.to_dict() for r in ols_results[:self.max_matches]]
                    results['has_any_mapping'] = True
            except Exception as e:
                logger.warning(f"OLS mapping failed for {term}: {e}")
                
        # 3. UMLS Mapping
        if self.umls_mapper:
            try:
                umls_results = self.umls_mapper.map_entity_to_umls(term, entity_type)
                if umls_results:
                    results['umls_mappings'] = [self.umls_mapper._mapping_to_dict(r) for r in umls_results[:self.max_matches]]
                    results['has_any_mapping'] = True
            except Exception as e:
                logger.warning(f"UMLS mapping failed for {term}: {e}")

        # 4. OMOP Mapping
        if self.omop_mapper:
            try:
                omop_result = self.omop_mapper.map_entity_to_omop(term, entity_type)
                if omop_result:
                     # OMOP mapper returns a list of OMOPMapping objects
                     if isinstance(omop_result, list):
                         results['omop_mappings'] = [vars(r) for r in omop_result]
                     else:
                         # Should not happen based on signature, but just in case
                         results['omop_mappings'] = [vars(omop_result)]
                     results['has_any_mapping'] = True
            except Exception as e:
                logger.warning(f"OMOP mapping failed for {term}: {e}")
                
        return results

    def map_entity_list_comprehensive(self, entities: List[Dict]) -> List[Dict]:
        """Map a list of entities using all available mappers."""
        mapped_entities = []

        for entity in entities:
            term = entity.get('entity') or entity.get('term')
            entity_type = entity.get('entity_type') or entity.get('categories')
            
            if not term:
                mapped_entities.append(entity)
                continue
                
            # Perform mapping
            comprehensive_mapping = self.map_entity_comprehensive(term, entity_type)

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
