"""
BioMistral-based modules for term validation, definition generation, and correction.
"""

import logging
from typing import List, Dict, Any
from src.config.settings import PipelineConfig

logger = logging.getLogger(__name__)

class DefinitionGenerator:
    """Generates definitions for terms using BioMistral or BioBERT"""
    
    def __init__(self, config: PipelineConfig):
        self.config = config
        self.pipeline = None
        self._load_model()
        
    def _load_model(self):
        """Load the model for definition generation"""
        if not self.config.generate_definitions:
            return

        try:
            from transformers import pipeline, AutoTokenizer, AutoModelForCausalLM
            import torch
            
            model_name = self.config.biomistral_model
            logger.info(f"Loading definition model: {model_name}")
            
            if self.config.load_4bit:
                from transformers import BitsAndBytesConfig
                bnb_config = BitsAndBytesConfig(
                    load_in_4bit=True,
                    bnb_4bit_compute_dtype=torch.float16,
                    bnb_4bit_quant_type="nf4"
                )
                model = AutoModelForCausalLM.from_pretrained(
                    model_name,
                    quantization_config=bnb_config,
                    device_map="auto",
                    trust_remote_code=True,
                    offload_folder="offload"
                )
            else:
                model = AutoModelForCausalLM.from_pretrained(
                    model_name,
                    device_map="auto",
                    torch_dtype=torch.float16,
                    trust_remote_code=True,
                    offload_folder="offload"
                )
                
            tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
            tokenizer.pad_token_id = model.config.eos_token_id
            tokenizer.padding_side = 'left'
            
            self.pipeline = pipeline(
                "text-generation",
                model=model,
                tokenizer=tokenizer,
                max_new_tokens=100,
                repetition_penalty=1.2
            )
            
        except Exception as e:
            logger.error(f"Failed to load definition model: {e}")
            self.pipeline = None

    def generate_definitions(self, terms: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Generate definitions for a list of terms"""
        if not self.pipeline or not terms:
            return terms
            
        logger.info(f"Generating definitions for {len(terms)} terms...")
        
        # Prepare prompts
        prompts = [
            f"Define the biomedical term '{t['term']}' concisely in one sentence:" 
            for t in terms
        ]
        
        batch_size = self.config.batch_size
        definitions = []
        
        try:
            from tqdm import tqdm
            for i in tqdm(range(0, len(prompts), batch_size), desc="Generating Definitions"):
                batch_prompts = prompts[i:i + batch_size]
                
                batch_outputs = self.pipeline(
                    batch_prompts,
                    do_sample=True,
                    temperature=0.7,
                    return_full_text=False,
                    batch_size=batch_size
                )
                
                for output in batch_outputs:
                    if isinstance(output, list):
                        output = output[0]
                    text = output['generated_text'].strip()
                    # Clean up: remove quotes, newlines
                    text = text.replace('\n', ' ').strip('"').strip("'")
                    definitions.append(text)
                    
        except Exception as e:
            logger.error(f"Definition generation failed: {e}")
            remaining = len(prompts) - len(definitions)
            definitions.extend(["Error generating definition"] * remaining)
            
        # Assign back to terms
        for term, definition in zip(terms, definitions):
            term['definition'] = definition
            
        return terms


class LLMTermCorrector:
    """Corrects terms using BioMistral/LLM"""
    
    def __init__(self, config: PipelineConfig):
        self.config = config
        self.pipeline = None
        self._load_model()
        
    def _load_model(self):
        if not self.config.correct_terms:
            return

        try:
            from transformers import pipeline, AutoTokenizer, AutoModelForCausalLM
            import torch
            
            model_name = self.config.biomistral_model
            logger.info(f"Loading correction model: {model_name}")
            
            if self.config.load_4bit:
                from transformers import BitsAndBytesConfig
                bnb_config = BitsAndBytesConfig(
                    load_in_4bit=True,
                    bnb_4bit_compute_dtype=torch.float16,
                    bnb_4bit_quant_type="nf4"
                )
                model = AutoModelForCausalLM.from_pretrained(
                    model_name,
                    quantization_config=bnb_config,
                    device_map="auto",
                    trust_remote_code=True,
                    offload_folder="offload"
                )
            else:
                model = AutoModelForCausalLM.from_pretrained(
                    model_name,
                    device_map="auto",
                    torch_dtype=torch.float16,
                    trust_remote_code=True,
                    offload_folder="offload"
                )
                
            tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
            tokenizer.pad_token_id = model.config.eos_token_id
            tokenizer.padding_side = 'left'
            
            self.pipeline = pipeline(
                "text-generation",
                model=model,
                tokenizer=tokenizer,
                max_new_tokens=50,
                repetition_penalty=1.2
            )
            
        except Exception as e:
            logger.error(f"Failed to load correction model: {e}")
            self.pipeline = None

    def correct_terms(self, terms: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not self.pipeline or not terms:
            return terms
            
        logger.info(f"Correcting {len(terms)} terms with LLM...")
        
        prompts = [
            f"Correct the following biomedical term to its standard canonical form. If it is already correct, output it as is.\nTerm: {t['term']}\nCorrected Term:"
            for t in terms
        ]
        
        batch_size = self.config.batch_size
        corrections = []
        
        try:
            from tqdm import tqdm
            for i in tqdm(range(0, len(prompts), batch_size), desc="Correcting Terms"):
                batch_prompts = prompts[i:i + batch_size]
                
                batch_outputs = self.pipeline(
                    batch_prompts,
                    do_sample=False, # Deterministic for correction
                    temperature=0.1,
                    return_full_text=False,
                    batch_size=batch_size
                )
                
                for output in batch_outputs:
                    if isinstance(output, list):
                        output = output[0]
                    text = output['generated_text'].strip().split('\n')[0] # Take first line
                    corrections.append(text)
                    
        except Exception as e:
            logger.error(f"LLM correction failed: {e}")
            remaining = len(prompts) - len(corrections)
            corrections.extend(["Error"] * remaining)
            
        # Apply corrections
        for term, correction in zip(terms, corrections):
            if correction and correction != "Error" and correction.lower() != term['term'].lower():
                term['llm_correction'] = correction
                # Optionally update the main term, but safer to keep as metadata first
                # term['term'] = correction 
            
        return terms


class BioMistralValidator:
    """Validator using BioMistral-7B"""
    def __init__(self, config: PipelineConfig):
        self.config = config
        self.pipeline = None
        self.tokenizer = None
        self.model = None

    def load_model(self):
        """Load the BioMistral model"""
        try:
            from transformers import AutoModelForCausalLM, AutoTokenizer, pipeline
            import torch
            
            model_name = self.config.biomistral_model
            logger.info(f"Loading BioMistral model: {model_name} (4-bit: {self.config.load_4bit})...")
            
            kwargs = {
                "device_map": "auto",
                "trust_remote_code": True,
                "offload_folder": "offload"
            }
            
            if self.config.load_4bit:
                try:
                    from transformers import BitsAndBytesConfig
                    kwargs["quantization_config"] = BitsAndBytesConfig(
                        load_in_4bit=True,
                        bnb_4bit_compute_dtype=torch.float16
                    )
                except ImportError:
                    logger.warning("bitsandbytes not installed. Falling back to standard loading.")
            
            self.model = AutoModelForCausalLM.from_pretrained(model_name, **kwargs)
            self.tokenizer = AutoTokenizer.from_pretrained(model_name)
            self.tokenizer.pad_token_id = self.model.config.eos_token_id
            self.tokenizer.padding_side = 'left'
            
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
        """Validate terms using BioMistral with batch processing"""
        if not self.config.validate_biomistral:
            return terms
            
        if not self.pipeline:
            if not self.load_model():
                return terms

        logger.info(f"Validating {len(terms)} terms with BioMistral (Batch Size: {self.config.batch_size})...")
        
        # Filter terms that need validation
        terms_to_validate = [t for t in terms if t.get('term')]
        if not terms_to_validate:
            return terms

        # Prepare prompts
        prompts = []
        for t in terms_to_validate:
            term = t['term']
            prompt = f"""
            Task: Verify if the following term is a valid, specific scientific concept relevant to microbiome, biomedical, or clinical research.
            Term: "{term}"
            
            Criteria:
            - Must be a specific biological entity, chemical, disease, method, or concept.
            - Reject generic words (e.g., "study", "result", "high").
            - Reject incoherent fragments.
            
            Answer (Yes/No):
            """
            prompts.append(prompt)

        # Run batch inference
        batch_size = self.config.batch_size
        results = []
        
        try:
            # Use tqdm for progress
            for i in range(0, len(prompts), batch_size):
                batch_prompts = prompts[i:i + batch_size]
                
                # Pipeline call with batch
                batch_outputs = self.pipeline(
                    batch_prompts, 
                    do_sample=False, 
                    temperature=0.1,
                    return_full_text=False,
                    batch_size=batch_size
                )
                
                for output in batch_outputs:
                    # Handle case where output might be a list (some pipeline versions)
                    if isinstance(output, list):
                        output = output[0]
                    results.append(output['generated_text'].strip().lower())
                    
        except Exception as e:
            logger.error(f"Batch validation failed: {e}")
            # Fallback to error for all remaining
            remaining = len(prompts) - len(results)
            results.extend(["error"] * remaining)

        # Assign results back to terms
        for i, t in enumerate(terms_to_validate):
            response = results[i] if i < len(results) else "error"
            is_valid = "yes" in response
            
            t['validation'] = {
                'model': self.config.biomistral_model,
                'is_valid': is_valid,
                'raw_response': response
            }
            if response == "error":
                 t['validation']['error'] = "Batch inference failed"
                
        return terms
