"""
LLM Client Module for CDM Pipeline
"""

import logging
import requests
import json
from typing import Dict, List, Optional
from config.cdm_config import CDMEntityConfig

logger = logging.getLogger(__name__)

class LLMClient:
    """Client for interacting with LLM models."""

    def __init__(self, model: str = "qwen3:8b", base_url: str = "http://localhost:11434"):
        self.model = model
        self.base_url = base_url
        self.config = CDMEntityConfig.MODEL_CONFIGS.get(model, CDMEntityConfig.MODEL_CONFIGS['qwen3:8b'])

    def call_llm(self, prompt: str, max_tokens: Optional[int] = None) -> str:
        """Call LLM with structured prompt and return response."""
        try:
            request_config = {
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": self.config['temperature'],
                    "top_p": 0.9,
                    "max_tokens": max_tokens or self.config['max_tokens']
                }
            }

            response = requests.post(
                f"{self.base_url}/api/generate",
                json=request_config,
                timeout=self.config['timeout']
            )

            if response.status_code == 200:
                return response.json().get('response', '').strip()
            else:
                logger.error(f"LLM API error: {response.status_code} - {response.text}")
                return ""

        except requests.exceptions.Timeout:
            logger.error(f"LLM call timeout after {self.config['timeout']} seconds")
            return ""
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            return ""

    def is_available(self) -> bool:
        """Check if the LLM service is available."""
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=10)
            return response.status_code == 200
        except:
            return False

    def get_available_models(self) -> List[str]:
        """Get list of available models."""
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=10)
            if response.status_code == 200:
                models = response.json().get('models', [])
                return [model['name'] for model in models]
            return []
        except:
            return []