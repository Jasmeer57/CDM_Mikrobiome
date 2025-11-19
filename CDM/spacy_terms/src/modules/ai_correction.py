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
from ..config.settings import AIConfig

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
            self.model = pipeline(
                'text-generation',
                model=self.config.model_name,
                torch_dtype=torch.bfloat16,
                device_map='auto'
            )
            logger.info(f"Local model initialized: {self.config.model_name}")
        except Exception as e:
            logger.error(f"Failed to initialize local model: {e}")
            raise

    def _create_correction_prompt(self, term: str, examples: List[str]) -> str:
        """Create prompt for term correction"""
        examples_text = "\n".join([
            f"{i+1}. \"{example}\"" for i, example in enumerate(examples[:2])
        ])

        return f"""
**Task**: You are a biomedical data cleaning expert. Analyze the scientific term and decide whether to KEEP it, CORRECT it, or REMOVE it.

**Term**: "{term}"

**Contextual Examples**:
{examples_text}

**Decision Logic**:
1. **REMOVE**: Only if the term is clearly non-scientific (author initials, citations, figure references)
2. **CORRECT**: If the term has typos or awkward phrasing but represents a valid concept
3. **KEEP**: If the term is correct or if uncertain (default action)

**Output Format**:
Reasoning: [One sentence explanation]
```json
{{
  "classification": "KEEP_OR_CORRECT_OR_REMOVE",
  "corrected_term": "corrected version or original",
  "confidence": 0.0-1.0,
  "definition": "brief definition or empty",
  "standardized_term": "standardized terminology",
  "category": "biological/chemical/medical/technical",
  "is_valid": true/false
}}
```
"""

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