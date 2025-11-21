"""
AI-powered term correction and validation module using BioMistral.
Incorporates functionality from reference do.py script.
"""

import json
import logging
import re
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from tqdm import tqdm
import requests
from src.config.settings import AIConfig

logger = logging.getLogger(__name__)


@dataclass
class CorrectionResult:
    """Result of AI correction for a term"""
    original_term: str
    corrected_term: str
    is_valid: bool
    confidence: float
    definition: str
    standardized_term: str
    category: str
    classification: str  # KEEP, CORRECT, REMOVE
    reasoning: str


class AITermCorrector:
    """AI-powered term correction using BioMistral or similar models"""

    def __init__(self, config: AIConfig):
        self.config = config
        self.model = None
        self.client = None

    def _initialize_model(self):
        """Initialize the AI model based on configuration"""
        if not self.config.enabled:
            logger.info("AI correction disabled")
            return

        try:
            if self.config.api_key:
                # Use OpenAI API or similar
                self.client = self._init_openai_client()
            else:
                # Use local model (requires transformers)
                self._init_local_model()

        except Exception as e:
            logger.error(f"Failed to initialize AI model: {e}")
            self.config.enabled = False

    def _init_openai_client(self):
        """Initialize OpenAI-compatible API client"""
        try:
            import openai
            client = openai.OpenAI(api_key=self.config.api_key)
            logger.info(f"Initialized OpenAI client with model: {self.config.model_name}")
            return client
        except ImportError:
            logger.error("OpenAI package not installed")
            return None

    def _init_local_model(self):
        """Initialize local model using transformers"""
        try:
            import torch
            from transformers import pipeline

            logger.info("Initializing local model (this may take a few moments)...")

            # Determine device without using device_map='auto' to avoid accelerate dependency
            device = "cuda" if torch.cuda.is_available() else "cpu"
            if device == "cuda":
                logger.info("Using CUDA GPU for inference")
            else:
                logger.info("Using CPU for inference")

            # Initialize pipeline with explicit device instead of device_map
            self.model = pipeline(
                'text-generation',
                model=self.config.model_name,
                torch_dtype=torch.float16 if device == "cuda" else torch.float32,
                device=0 if device == "cuda" else -1
            )
            logger.info(f"Local model initialized: {self.config.model_name} on {device}")
        except Exception as e:
            logger.error(f"Failed to initialize local model: {e}")
            # Fallback to CPU without torch_dtype specification
            try:
                self.model = pipeline(
                    'text-generation',
                    model=self.config.model_name,
                    device=-1
                )
                logger.info(f"Local model initialized on CPU fallback: {self.config.model_name}")
            except Exception as fallback_e:
                logger.error(f"Completely failed to initialize local model: {fallback_e}")
                raise

    def _create_correction_prompt(self, term: str, examples: List[str]) -> str:
        """
        ENHANCED: Advanced prompt engineering from reference do.py
        Comprehensive biomedical term validation and correction with context-aware decision logic
        """
        examples_text = "\n".join([
            f"{i+1}. \"{example}\"" for i, example in enumerate(examples[:2])
        ])

        # Enhanced prompt based on reference do.py with sophisticated biomedical validation
        return f"""
        **Task**: You are a data cleaning expert specializing in biomedical literature. Your job is to analyze a term and, based on its context, decide whether to KEEP it, CORRECT it, or REMOVE it.

        **Term**: "{term}"

        **Contextual Examples**:
        1. "{examples[0] if len(examples) > 0 else 'N/A'}"
        2. "{examples[1] if len(examples) > 1 else 'N/A'}"

        **Decision Logic**:
        1.  **REMOVE**: ONLY if the term is a clear non-scientific artifact like author initials ('YY'), citation markers ('et al'), or figure references ('Fig.').
        2.  **CORRECT**: If the term is a plausible scientific concept but seems to have a typo or awkward phrasing, suggest a corrected version. For example, 'acid fatty middle-chain' could be corrected to 'medium-chain fatty acid'.
        3.  **KEEP**: If the term is correct as-is or if you are in any doubt. This is the default action.

        **Biomedical Validation Criteria**:
        - Is this a legitimate biomedical/biological/chemical term?
        - Does it represent a specific concept, entity, or measurement?
        - Would this term appear in a scientific database or ontology?
        - Is it relevant to microbiome, biomedical, or clinical research?

        **Instructions**:
        First, provide your reasoning. Then, provide your final decision in a strict JSON format.

        **Output Format**:
        Reasoning: [Your one-sentence reasoning here.]
        ```json
        {{
          "classification": "KEEP_OR_CORRECT_OR_REMOVE",
          "corrected_term": "The corrected term here, or the original term if keeping.",
          "definition": "Your one-sentence definition here, or an empty string for REMOVE.",
          "confidence": 0.0-1.0,
          "is_valid": true/false,
          "standardized_term": "Standardized terminology if applicable",
          "category": "biological/chemical/medical/technical"
        }}
        """
        # Enhanced prompt from reference do.py with better structure and biomedical focus

    def _call_openai_api(self, prompt: str) -> Optional[Dict[str, Any]]:
        """Call OpenAI-compatible API"""
        try:
            response = self.client.chat.completions.create(
                model=self.config.model_name,
                messages=[
                    {"role": "system", "content": self.config.system_prompt},
                    {"role": "user", "content": prompt}
                ],
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens
            )

            content = response.choices[0].message.content
            return self._parse_json_response(content)

        except Exception as e:
            logger.error(f"OpenAI API call failed: {e}")
            return None

    def _call_local_model(self, prompt: str) -> Optional[Dict[str, Any]]:
        """Call local model pipeline"""
        try:
            messages = [{"role": "user", "content": prompt}]
            response = self.model(
                messages,
                max_new_tokens=self.config.max_tokens,
                do_sample=False,
                pad_token_id=self.model.tokenizer.eos_token_id
            )

            content = response[0]['generated_text'][-1]['content']
            return self._parse_json_response(content)

        except Exception as e:
            logger.error(f"Local model call failed: {e}")
            return None

    def _parse_json_response(self, content: str) -> Optional[Dict[str, Any]]:
        """Parse JSON response from model output"""
        try:
            # Extract JSON block from response
            match = re.search(r'```json\s*(\{.*?\})\s*```', content, re.DOTALL)
            if match:
                json_str = match.group(1)
                return json.loads(json_str)
            else:
                # Try to parse entire response as JSON
                return json.loads(content)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response: {e}")
            return None

    def correct_term(self, term: str, examples: List[str] = None) -> CorrectionResult:
        """Correct a single term using AI"""
        if not self.config.enabled or not term.strip():
            return CorrectionResult(
                original_term=term,
                corrected_term=term,
                is_valid=True,
                confidence=0.5,
                definition="",
                standardized_term=term,
                category="unknown",
                classification="KEEP",
                reasoning="AI correction disabled"
            )

        examples = examples or []

        # Initialize model if not done yet
        if not self.model and not self.client:
            self._initialize_model()

        # Create prompt
        prompt = self._create_correction_prompt(term, examples)

        # Call appropriate model
        try:
            if self.client:
                result_data = self._call_openai_api(prompt)
            else:
                result_data = self._call_local_model(prompt)

            if result_data:
                return CorrectionResult(
                    original_term=term,
                    corrected_term=result_data.get('corrected_term', term),
                    is_valid=result_data.get('is_valid', True),
                    confidence=result_data.get('confidence', 0.5),
                    definition=result_data.get('definition', ''),
                    standardized_term=result_data.get('standardized_term', term),
                    category=result_data.get('category', 'unknown'),
                    classification=result_data.get('classification', 'KEEP'),
                    reasoning="AI-based correction"
                )
            else:
                logger.warning(f"AI correction failed for term: {term}")
                return self._fallback_result(term)

        except Exception as e:
            logger.error(f"Error correcting term '{term}': {e}")
            return self._fallback_result(term)

    def _fallback_result(self, term: str) -> CorrectionResult:
        """Fallback result when AI correction fails"""
        return CorrectionResult(
            original_term=term,
            corrected_term=term,
            is_valid=True,
            confidence=0.3,
            definition="",
            standardized_term=term,
            category="unknown",
            classification="KEEP",
            reasoning="AI correction failed, kept by default"
        )

    def correct_terms_batch(self, terms_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Correct multiple terms in batch"""
        if not self.config.enabled:
            logger.info("AI correction disabled, returning original terms")
            return terms_data

        logger.info(f"Starting AI correction for {len(terms_data)} terms...")
        corrected_terms = []
        removed_count = 0
        corrected_count = 0

        for term_data in tqdm(terms_data, desc="AI Correction"):
            original_term = term_data.get('term', '')
            examples = term_data.get('examples', [])

            result = self.correct_term(original_term, examples)

            if result.classification == 'REMOVE':
                removed_count += 1
                tqdm.write(f"Term '{original_term}' removed by AI")
                continue
            elif result.classification == 'CORRECT' and result.corrected_term != original_term:
                corrected_count += 1
                tqdm.write(f"Term '{original_term}' corrected to '{result.corrected_term}'")
                term_data['term'] = result.corrected_term
                term_data['original_term_before_correction'] = original_term

            # Add AI correction metadata
            term_data.update({
                'ai_classification': result.classification,
                'ai_confidence': result.confidence,
                'ai_definition': result.definition,
                'ai_standardized_term': result.standardized_term,
                'ai_category': result.category,
                'ai_reasoning': result.reasoning
            })

            corrected_terms.append(term_data)

        logger.info(f"AI correction complete: {len(corrected_terms)} kept, {corrected_count} corrected, {removed_count} removed")
        return corrected_terms


def create_ai_corrector(config: AIConfig) -> AITermCorrector:
    """Factory function to create AI corrector"""
    return AITermCorrector(config)