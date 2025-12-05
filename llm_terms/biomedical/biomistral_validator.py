"""
BioMistral-based Biomedical Entity Validation
"""

import logging
import json
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from transformers import AutoTokenizer, AutoModelForCausalLM
import torch
import requests

logger = logging.getLogger(__name__)

@dataclass
class BioMistralConfig:
    """Configuration for BioMistral validation."""
    model_name: str = "biomistral-7B"
    api_url: str = "http://localhost:11434"
    temperature: float = 0.1
    max_tokens: int = 500

class BioMistralValidator:
    """Biomedical entity validation using BioMistral model."""

    def __init__(self, config: BioMistralConfig = None, llm_client=None):
        self.config = config or BioMistralConfig()
        self.validation_cache = {}
        self.model = None
        self.tokenizer = None
        self.llm_client = llm_client
        
        if not self.llm_client:
            self._load_model()
        else:
            logger.info("✅ Using LLM Client for biomedical validation (Skipping local model load)")

    def validate_biomedical_entity(self, entity_name: str, entity_type: str) -> Dict:
        """Validate entity using BioMistral biomedical knowledge."""
        cache_key = f"{entity_name.lower()}_{entity_type}"
        if cache_key in self.validation_cache:
            return self.validation_cache[cache_key]

        try:
            prompt = self._create_validation_prompt(entity_name, entity_type)
            
            if self.llm_client:
                # Use API client
                response = self.llm_client.call_llm(prompt, max_tokens=self.config.max_tokens)
            else:
                # Use local model
                response = self._call_biomistral(prompt)
                
            validation_result = self._parse_validation_response(response)

            # Cache the result
            self.validation_cache[cache_key] = validation_result
            return validation_result

        except Exception as e:
            logger.warning(f"BioMistral validation failed for {entity_name}: {e}")
            return self._default_validation(entity_name, entity_type)

    def _load_model(self):
        """Load BioMistral model from HuggingFace."""
        try:
            model_name = "BioMistral/BioMistral-7B"
            logger.info(f"Loading BioMistral model: {model_name}")

            # Load tokenizer and model
            self.tokenizer = AutoTokenizer.from_pretrained(model_name)
            self.model = AutoModelForCausalLM.from_pretrained(
                model_name,
                torch_dtype=torch.float16,
                device_map="auto",
                trust_remote_code=True
            )

            # Set padding token if not present
            if self.tokenizer.pad_token is None:
                self.tokenizer.pad_token = self.tokenizer.eos_token

            logger.info("✅ BioMistral model loaded successfully")

        except Exception as e:
            logger.error(f"Failed to load BioMistral model: {e}")
            self.model = None
            self.tokenizer = None

    def _create_validation_prompt(self, entity_name: str, entity_type: str) -> str:
        """Create validation prompt for BioMistral."""
        return f"""
As a biomedical expert, validate the following entity for a Microbiome Common Data Model:

Entity: {entity_name}
Type: {entity_type}

Please analyze and provide:
1. Is this a valid biomedical entity? (yes/no)
2. Correct entity type (from: ORGANISM, GENE, PROTEIN, CHEMICAL, DISEASE, DNA_RNA, CELL_TYPE, BIOINFO_TOOL, GENOMICS, CLINICAL)
3. Brief biomedical description
4. Common alternative names/synonyms
5. Database references (if known)

Respond in JSON format:
{{
  "is_valid": true/false,
  "corrected_type": "entity_type",
  "description": "biomedical description",
  "synonyms": ["synonym1", "synonym2"],
  "confidence": 0.0-1.0,
  "databases": {{
    "uniprot": "ID" or null,
    "ncbi": "ID" or null,
    "pubchem": "ID" or null,
    "mesh": "ID" or null
  }}
}}
"""

    def _call_biomistral(self, prompt: str) -> str:
        """Call BioMistral model using HuggingFace Transformers."""
        if self.model is None or self.tokenizer is None:
            logger.warning("BioMistral model not loaded, returning empty response")
            return ""

        try:
            # Tokenize input
            inputs = self.tokenizer.encode(
                prompt,
                return_tensors="pt",
                truncation=True,
                max_length=4096
            ).to(self.model.device)

            # Generate response
            with torch.no_grad():
                outputs = self.model.generate(
                    inputs,
                    max_new_tokens=self.config.max_tokens,
                    temperature=self.config.temperature,
                    do_sample=True,
                    pad_token_id=self.tokenizer.eos_token_id,
                    eos_token_id=self.tokenizer.eos_token_id,
                    num_return_sequences=1
                )

            # Decode response
            response = self.tokenizer.decode(
                outputs[0][inputs.shape[1]:],
                skip_special_tokens=True
            ).strip()

            return response

        except Exception as e:
            logger.error(f"Error calling BioMistral: {e}")
            return ""

    def _parse_validation_response(self, response: str) -> Dict:
        """Parse BioMistral validation response."""
        try:
            # Try to extract JSON from response
            if '{' in response and '}' in response:
                start_idx = response.find('{')
                end_idx = response.rfind('}') + 1
                json_str = response[start_idx:end_idx]
                return json.loads(json_str)
        except:
            pass

        return self._default_validation("unknown", "unknown")

    def _default_validation(self, entity_name: str, entity_type: str) -> Dict:
        """Default validation when BioMistral is unavailable."""
        return {
            "is_valid": True,  # Assume valid if can't validate
            "corrected_type": entity_type,
            "description": f"Entity: {entity_name}",
            "synonyms": [],
            "confidence": 0.5,
            "databases": {
                "uniprot": None,
                "ncbi": None,
                "pubchem": None,
                "mesh": None
            }
        }

    def validate_entity_list(self, entities: List[Dict]) -> List[Dict]:
        """Validate a list of entities using BioMistral."""
        validated_entities = []

        for entity in entities:
            entity_name = entity.get('entity', '')
            entity_type = entity.get('entity_type', '')

            if not entity_name or not entity_type:
                continue

            # Get validation from BioMistral
            validation = self.validate_biomedical_entity(entity_name, entity_type)

            # Update entity with validation results
            enhanced_entity = {
                **entity,
                'biomistral_validation': validation,
                'is_biomedically_valid': validation.get('is_valid', False),
                'biomedical_confidence': validation.get('confidence', 0.0),
                'biomedical_description': validation.get('description', ''),
                'synonyms': validation.get('synonyms', []),
                'database_references': validation.get('databases', {})
            }

            validated_entities.append(enhanced_entity)

        logger.info(f"✅ BioMistral validation: {len(entities)} → {len(validated_entities)} entities")
        return validated_entities

    def correct_entity_types(self, entities: List[Dict]) -> List[Dict]:
        """Correct entity types based on BioMistral validation."""
        corrected_entities = []
        corrections_made = 0

        for entity in entities:
            biomistral_validation = entity.get('biomistral_validation', {})
            corrected_type = biomistral_validation.get('corrected_type', entity.get('entity_type'))

            if corrected_type != entity.get('entity_type'):
                entity['original_entity_type'] = entity.get('entity_type')
                entity['entity_type'] = corrected_type
                corrections_made += 1
                logger.debug(f"Corrected type: {entity['entity']} → {corrected_type}")

            corrected_entities.append(entity)

        if corrections_made > 0:
            logger.info(f"🔧 BioMistral type corrections: {corrections_made} entities")

        return corrected_entities