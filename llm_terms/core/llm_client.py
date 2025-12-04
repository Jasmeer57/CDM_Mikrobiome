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

    def __init__(self, model: str = "qwen3:8b", base_url: str = "http://localhost:11434", api_key: str = "EMPTY"):
        self.model = model
        self.base_url = base_url
        self.api_key = api_key
        self.config = CDMEntityConfig.MODEL_CONFIGS.get(model, CDMEntityConfig.MODEL_CONFIGS['qwen3:8b'])

    def call_llm(self, prompt: str, max_tokens: Optional[int] = None) -> str:
        """Call LLM with structured prompt and return response."""
        try:
            # Determine provider and endpoint
            is_ollama = "/api/generate" in self.base_url or "localhost:11434" in self.base_url
            
            if is_ollama:
                # Ollama API
                endpoint = f"{self.base_url}/api/generate"
                request_config = {
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": self.config['temperature'],
                        "top_p": 0.9,
                        "num_predict": max_tokens or self.config['max_tokens']
                    }
                }
            else:
                # OpenAI-compatible API (vLLM, ZLM, HuggingFace, OpenAI)
                endpoint = f"{self.base_url}/v1/chat/completions"
                request_config = {
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": self.config['temperature'],
                    "max_tokens": max_tokens or self.config['max_tokens'],
                    "stream": False
                }

            headers = {
                "Content-Type": "application/json"
            }
            if self.api_key and self.api_key != "EMPTY":
                headers["Authorization"] = f"Bearer {self.api_key}"

            response = requests.post(
                endpoint,
                json=request_config,
                headers=headers,
                timeout=self.config['timeout']
            )

            if response.status_code == 200:
                logger.debug(f"LLM Response Status: {response.status_code}")
                resp_json = response.json()
                
                if is_ollama:
                    content = resp_json.get('response', '').strip()
                    if not content and 'thinking' in resp_json:
                        content = resp_json['thinking'].strip()
                else:
                    # OpenAI format
                    choices = resp_json.get('choices', [])
                    if choices:
                        content = choices[0].get('message', {}).get('content', '').strip()
                    else:
                        content = ""
                        
                return content
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