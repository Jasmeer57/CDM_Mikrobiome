import logging
import torch
from typing import List, Dict, Any
from tqdm import tqdm

logger = logging.getLogger(__name__)

class BioMistralValidator:
    """
    Validator using BioMistral-7B to verify scientific terms.
    """
    def __init__(self, model_name: str = "BioMistral/BioMistral-7B", load_in_4bit: bool = False):
        self.model_name = model_name
        self.load_in_4bit = load_in_4bit
        self.pipeline = None
        self.tokenizer = None
        self.model = None

    def load_model(self):
        """Load the BioMistral model"""
        try:
            from transformers import AutoModelForCausalLM, AutoTokenizer, pipeline
            
            logger.info(f"Loading BioMistral model: {self.model_name} (4-bit: {self.load_in_4bit})...")
            
            kwargs = {
                "device_map": "auto",
                "trust_remote_code": True
            }
            
            if self.load_in_4bit:
                try:
                    from transformers import BitsAndBytesConfig
                    kwargs["quantization_config"] = BitsAndBytesConfig(
                        load_in_4bit=True,
                        bnb_4bit_compute_dtype=torch.float16
                    )
                except ImportError:
                    logger.warning("bitsandbytes not installed. Falling back to standard loading.")
            
            self.tokenizer = AutoTokenizer.from_pretrained(self.model_name)
            self.model = AutoModelForCausalLM.from_pretrained(self.model_name, **kwargs)
            
            # Create generation pipeline
            self.pipeline = pipeline(
                "text-generation",
                model=self.model,
                tokenizer=self.tokenizer,
                max_new_tokens=10
            )
            logger.info("BioMistral model loaded successfully.")
            return True
            
        except Exception as e:
            logger.error(f"Failed to load BioMistral model: {e}")
            return False

    def validate_terms(self, terms: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Validate terms using BioMistral.
        Adds 'validation' field to terms: {'valid': bool, 'confidence': float, 'reason': str}
        """
        if not self.pipeline:
            if not self.load_model():
                return terms

        logger.info(f"Validating {len(terms)} terms with BioMistral...")
        
        for term_data in tqdm(terms, desc="BioMistral Validation"):
            term = term_data.get('term', '')
            if not term: continue
            
            prompt = f"""
            Task: Verify if the following term is a valid, specific scientific concept relevant to microbiome, biomedical, or clinical research.
            Term: "{term}"
            
            Criteria:
            - Must be a specific biological entity, chemical, disease, method, or concept.
            - Reject generic words (e.g., "study", "result", "high").
            - Reject incoherent fragments.
            
            Answer (Yes/No):
            """
            
            try:
                # Generate response
                outputs = self.pipeline(
                    prompt, 
                    do_sample=False, 
                    temperature=0.1,
                    return_full_text=False
                )
                response = outputs[0]['generated_text'].strip().lower()
                
                is_valid = "yes" in response
                
                term_data['validation'] = {
                    'model': self.model_name,
                    'is_valid': is_valid,
                    'raw_response': response
                }
                
            except Exception as e:
                logger.warning(f"Validation failed for '{term}': {e}")
                term_data['validation'] = {'error': str(e)}
                
        return terms
