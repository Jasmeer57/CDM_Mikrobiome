import logging
from typing import List, Dict
from .llm_client import LLMClient
from config.cdm_config import BioMistralConfig, CDMEntityConfig

logger = logging.getLogger(__name__)

class BioMistralValidator:
    """Advanced biomedical validation using BioMistral model."""

    def __init__(self, config: BioMistralConfig):
        self.config = config
        self.llm_client = LLMClient(model=config.model_name, base_url=config.api_url)

    def validate_entity_list(self, entities: List[Dict]) -> List[Dict]:
        """Validate a list of entities using BioMistral."""
        # For standalone, we'll implement a simplified version or a pass-through
        # if the model isn't actually available/heavy to run in loop.
        # But assuming we want to try:
        validated_entities = []
        for entity in entities:
            if self._validate_single_entity(entity):
                validated_entities.append(entity)
        return validated_entities

    def _validate_single_entity(self, entity: Dict) -> bool:
        """Validate a single entity."""
        # Simplified validation logic
        prompt = f"""
        Is "{entity['entity']}" a valid {entity['entity_type']} in the context of microbiome research?
        Reply with YES or NO only.
        """
        try:
            response = self.llm_client.call_llm(prompt, max_tokens=10)
            return "YES" in response.upper()
        except Exception as e:
            logger.warning(f"BioMistral validation failed for {entity['entity']}: {e}")
            return True # Fallback to keep entity

    def correct_entity_types(self, entities: List[Dict]) -> List[Dict]:
        """Correct entity types using BioMistral."""
        logger.info(f"🧬 Correcting entity types for {len(entities)} entities using LLM...")
        
        corrected_count = 0
        for entity in entities:
            if entity.get('confidence', 1.0) < 0.8: # Only check low confidence ones
                prompt = f"""
                Given the text "{entity['entity']}" and context "{entity.get('context', '')[:100]}", what is the most appropriate entity type?
                Options: ORGANISM, GENE, PROTEIN, CHEMICAL, DISEASE, DNA_RNA, CELL_TYPE, BIOINFO_TOOL, GENOMICS, CLINICAL, SCIENTIFIC_TERM.
                Reply with ONLY the entity type.
                """
                try:
                    response = self.llm_client.call_llm(prompt, max_tokens=10).strip().upper()
                    
                    # Extract type from response
                    found_type = None
                    for valid_type in CDMEntityConfig.ENTITY_TYPES.keys():
                        if valid_type in response:
                            found_type = valid_type
                            break
                    
                    if found_type and found_type != entity['entity_type']:
                        entity['original_type'] = entity['entity_type']
                        entity['entity_type'] = found_type
                        entity['type_correction_method'] = 'LLM_Validation'
                        corrected_count += 1
                except Exception as e:
                    logger.warning(f"BioMistral type correction failed for {entity['entity']}: {e}")

        logger.info(f"✅ LLM type correction: Updated {corrected_count} entities")
        return entities
