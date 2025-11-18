"""
AI-powered term cleaning module with ALL features from the original do.py script.
Preserves Mistral-7B-Instruct integration with comprehensive term cleaning and correction.
"""

import json
import logging
import re
import time
from typing import List, Dict, Set, Optional, Any
from pathlib import Path

# Import availability checks
try:
    import torch
    from transformers import pipeline
    TRANSFORMERS_AVAILABLE = True
except ImportError:
    TRANSFORMERS_AVAILABLE = False
    torch = None
    pipeline = None

from ..config.settings import AIModelConfig

logger = logging.getLogger(__name__)


class AITermCleaner:
    """
    AI-powered term cleaner with all features from the original do.py script.

    Features preserved from do.py:
    - Mistral-7B-Instruct model integration
    - JSON structure handling for deduplicated terms
    - Batch processing of terms
    - Comprehensive term cleaning and correction
    - Error handling and model fallbacks
    - Detailed progress reporting
    - Output file management
    """

    def __init__(self, config: AIModelConfig):
        self.config = config
        self.generator = None
        self.processing_stats = {
            'total_terms': 0,
            'cleaned_terms': 0,
            'removed_terms': 0,
            'corrected_terms': 0,
            'processing_time': 0,
            'model_loading_time': 0
        }

        # Load AI model
        self._load_ai_model()

    def _load_ai_model(self):
        """Load the Mistral-7B-Instruct model."""
        if not TRANSFORMERS_AVAILABLE:
            logger.error("❌ transformers library not available. Install with: pip install transformers torch")
            return

        logger.info("🤖 Initializing the Mistral-7B-Instruct model. This may take a few moments...")

        start_time = time.time()

        try:
            self.generator = pipeline(
                'text-generation',
                model=self.config.model_name,
                torch_dtype=getattr(torch, self.config.torch_dtype, 'float32'),
                device_map=self.config.device_map,
                token=self.config.use_gpu
            )
            self.processing_stats['model_loading_time'] = time.time() - start_time
            logger.info(f"✅ Model initialized successfully in {self.processing_stats['model_loading_time']:.2f}s")
            logger.info(f"🔧 Model: {self.config.model_name}")
            logger.info(f"🎯 Device: {self.config.device_map}")
            logger.info(f"🧠 Torch dtype: {self.config.torch_dtype}")

        except Exception as e:
            logger.error(f"❌ Error initializing model: {e}")
            logger.info("💡 Please ensure you have sufficient GPU memory and have accepted the model's license on Hugging Face")
            self.generator = None

    def clean_and_correct_deduplicated_terms(self, input_file_path: str, output_file_path: str) -> Dict[str, Any]:
        """
        Clean and correct microbiome-related deduplicated terms from a JSON file.
        Preserves the exact functionality from the original do.py script.
        """
        if not self.generator:
            logger.error("❌ AI model not available for cleaning")
            return {'error': 'AI model not available'}

        logger.info("🧹 STARTING AI-POWERED TERM CLEANING")
        logger.info("=" * 60)

        # Load input file
        input_path = Path(input_file_path)
        if not input_path.exists():
            logger.error(f"❌ Input file not found: {input_file_path}")
            return {'error': f'Input file not found: {input_file_path}'}

        try:
            with open(input_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            terms = data.get('deduplicated_terms', [])
            if not terms:
                logger.error("❌ No terms found in input file")
                return {'error': 'No terms found in input file'}
        except json.JSONDecodeError:
            logger.error(f"❌ Could not decode JSON from {input_file_path}")
            return {'error': f'Could not decode JSON from {input_file_path}'}
        except Exception as e:
            logger.error(f"❌ Error reading input file: {e}")
            return {'error': f'Error reading input file: {e}'}

        self.processing_stats['total_terms'] = len(terms)
        logger.info(f"📊 Found {len(terms)} terms to clean")

        # Create output directory
        output_path = Path(output_file_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Process terms
        start_time = time.time()
        cleaned_terms = []
        removed_count = 0
        corrected_count = 0

        logger.info("🔧 Processing terms with AI model...")

        for i, term_data in enumerate(terms):
            logger.info(f"📝 Processing term {i+1}/{len(terms)}: {term_data.get('term', 'unknown')}")

            # Prepare prompt for the AI model
            prompt = self._create_cleaning_prompt(term_data)

            try:
                # Generate response from AI model
                result = self.generator(
                    prompt,
                    max_new_tokens=self.config.max_new_tokens,
                    temperature=self.config.temperature,
                    do_sample=self.config.do_sample,
                    top_p=self.config.top_p,
                    top_k=self.config.top_k,
                    pad_token_id=50256  # EOS token
                )

                ai_response = result[0]['generated_text']
                cleaned_result = self._parse_ai_response(ai_response, term_data)

                if cleaned_result['action'] == 'keep':
                    cleaned_terms.append(cleaned_result['term_data'])
                elif cleaned_result['action'] == 'remove':
                    removed_count += 1
                    logger.info(f"   🗑️  Removed: {cleaned_result['reason']}")
                elif cleaned_result['action'] == 'correct':
                    cleaned_terms.append(cleaned_result['term_data'])
                    corrected_count += 1
                    logger.info(f"   ✏️  Corrected: {cleaned_result['original']} → {cleaned_result['term_data']['term']}")

            except Exception as e:
                logger.error(f"❌ Error processing term {term_data.get('term', 'unknown')}: {e}")
                # Keep original term if AI processing fails
                cleaned_terms.append(term_data)

            # Progress indicator
            if (i + 1) % 10 == 0:
                progress = ((i + 1) / len(terms)) * 100
                logger.info(f"   Progress: {progress:.1f}% ({i+1}/{len(terms)})")

        # Final results
        self.processing_stats['cleaned_terms'] = len(cleaned_terms)
        self.processing_stats['removed_terms'] = removed_count
        self.processing_stats['corrected_terms'] = corrected_count
        self.processing_stats['processing_time'] = time.time() - start_time

        # Prepare final output
        final_results = {
            'cleaning_metadata': {
                'pipeline_version': 'ai_term_cleaner_v1.0',
                'model_name': self.config.model_name,
                'timestamp': time.strftime("%Y%m%d_%H%M%S"),
                'total_terms_processed': self.processing_stats['total_terms'],
                'terms_cleaned': self.processing_stats['cleaned_terms'],
                'terms_removed': self.processing_stats['removed_terms'],
                'terms_corrected': self.processing_stats['corrected_terms'],
                'model_loading_time': self.processing_stats['model_loading_time'],
                'processing_time': self.processing_stats['processing_time'],
                'success_rate': (self.processing_stats['cleaned_terms'] / self.processing_stats['total_terms']) * 100
            },
            'deduplicated_terms': cleaned_terms
        }

        # Save results
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(final_results, f, indent=2, ensure_ascii=False)

        logger.info("=" * 60)
        logger.info(f"✅ AI cleaning completed in {self.processing_stats['processing_time']:.2f}s")
        logger.info(f"📊 Total terms processed: {self.processing_stats['total_terms']}")
        logger.info(f"📊 Terms kept: {self.processing_stats['cleaned_terms']}")
        logger.info(f"📊 Terms removed: {self.processing_stats['removed_terms']}")
        logger.info(f"📊 Terms corrected: {self.processing_stats['corrected_terms']}")
        logger.info(f"📊 Success rate: {(self.processing_stats['cleaned_terms'] / self.processing_stats['total_terms']) * 100:.1f}%")
        logger.info(f"💾 Results saved to: {output_path}")
        logger.info("=" * 60)

        return final_results

    def _create_cleaning_prompt(self, term_data: Dict[str, Any]) -> str:
        """Create a comprehensive prompt for the AI model."""
        term = term_data.get('term', '')
        examples = term_data.get('examples', [])
        frequency = term_data.get('frequency', 0)
        aliases = list(term_data.get('aliases', []))

        prompt = f"""You are a microbiome terminology expert. Your task is to evaluate and improve the following term extracted from scientific literature.

TERM TO EVALUATE:
Term: "{term}"
Frequency: {frequency}
Examples: {examples[:2] if examples else 'None'}
Aliases: {aliases if aliases else 'None'}

ANALYSIS CRITERIA:
1. Is this a valid microbiome/biomedical term?
2. Is the terminology scientifically accurate?
3. Is the spelling correct?
4. Should this term be kept, removed, or corrected?
5. If correction is needed, provide the improved term.

RESPONSE FORMAT:
ACTION: [keep/remove/correct]
TERM: [improved term if correction needed]
REASON: [brief explanation for decision]
CONFIDENCE: [high/medium/low]

Please analyze the term and provide your decision in the exact format above."""

        return prompt

    def _parse_ai_response(self, ai_response: str, original_term_data: Dict[str, Any]) -> Dict[str, Any]:
        """Parse the AI response and return structured result."""
        try:
            # Extract action, term, and reason using regex patterns
            action_match = re.search(r'ACTION:\s*(keep|remove|correct)', ai_response, re.IGNORECASE)
            term_match = re.search(r'TERM:\s*([^\n]+)', ai_response)
            reason_match = re.search(r'REASON:\s*([^\n]+)', ai_response)

            action = action_match.group(1).lower() if action_match else 'keep'
            improved_term = term_match.group(1).strip() if term_match else original_term_data.get('term', '')
            reason = reason_match.group(1).strip() if reason_match else 'No reason provided'

            # Clean up the improved term
            improved_term = improved_term.strip().strip('"').strip("'")

            # Update term data if corrected
            cleaned_term_data = original_term_data.copy()
            if action == 'correct' and improved_term != original_term_data.get('term', ''):
                cleaned_term_data['term'] = improved_term
                cleaned_term_data['original_term'] = original_term_data.get('term', '')
                # Add original term to aliases if different
                if 'aliases' not in cleaned_term_data:
                    cleaned_term_data['aliases'] = []
                cleaned_term_data['aliases'].append(original_term_data.get('term', ''))

            return {
                'action': action,
                'term_data': cleaned_term_data,
                'original': original_term_data.get('term', ''),
                'reason': reason,
                'ai_response': ai_response
            }

        except Exception as e:
            logger.error(f"❌ Error parsing AI response: {e}")
            return {
                'action': 'keep',
                'term_data': original_term_data,
                'original': original_term_data.get('term', ''),
                'reason': f'Parse error: {str(e)}',
                'ai_response': ai_response
            }

    def get_cleaning_statistics(self) -> Dict[str, Any]:
        """Get comprehensive cleaning statistics."""
        return self.processing_stats.copy()

    def export_cleaning_report(self, output_path: str):
        """Export detailed cleaning report."""
        import json
        from pathlib import Path

        report = {
            'cleaning_configuration': {
                'model_name': self.config.model_name,
                'torch_dtype': self.config.torch_dtype,
                'device_map': self.config.device_map,
                'max_new_tokens': self.config.max_new_tokens,
                'temperature': self.config.temperature,
                'do_sample': self.config.do_sample,
                'top_p': self.config.top_p,
                'top_k': self.config.top_k,
                'use_gpu': self.config.use_gpu
            },
            'statistics': self.get_cleaning_statistics(),
            'model_available': self.generator is not None
        }

        output_file = Path(output_path) / "ai_cleaning_report.json"
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        logger.info(f"📄 AI cleaning report exported to: {output_file}")