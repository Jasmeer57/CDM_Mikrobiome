"""
LLM Client Module for CDM Pipeline
"""

import logging
import requests
import json
import os
from typing import Dict, List, Optional, Any
from config.cdm_config import CDMEntityConfig

logger = logging.getLogger(__name__)

# Try to import openai SDK
try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    logger.warning("⚠️ openai package not installed. Some features may be limited.")

class LLMClient:
    """Client for interacting with LLM models."""

    def __init__(self, model: str = "qwen3:8b", base_url: str = None, api_key: str = "EMPTY"):
        self.model = model
        self.base_url = base_url or os.environ.get("LLM_BASE_URL", "http://localhost:11434")
        self.api_key = api_key
        self.config = CDMEntityConfig.MODEL_CONFIGS.get(model, CDMEntityConfig.MODEL_CONFIGS['qwen3:8b'])
        
        logger.info(f"🔌 LLMClient initialized with model: {model}, base_url: {base_url}")

        # Initialize OpenAI client if applicable
        self.client = None
        if OPENAI_AVAILABLE:
            # Initialize OpenAI client for /v1 endpoints (including local llama.cpp)
            has_v1_endpoint = "/v1/" in self.base_url or self.base_url.endswith("/v1")
            is_zhipu_or_bigmodel = "api.z.ai" in self.base_url or "bigmodel.cn" in self.base_url
            if has_v1_endpoint or is_zhipu_or_bigmodel:
                 logger.info(f"🚀 Initializing OpenAI client for endpoint: {self.base_url}")
                 self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)

    def call_llm(self, prompt: str, max_tokens: Optional[int] = None, **kwargs) -> str:
        """Call LLM with structured prompt and return response."""

        # Determine provider based on model name and URL
        is_ollama = "/api/generate" in self.base_url or ":11434" in self.base_url or "ollama" in self.base_url
        is_zhipu = "glm" in self.model.lower() or "api.z.ai" in self.base_url
        is_anthropic = "claude" in self.model.lower()
        # Check for /v1 or /v1/ to detect llama.cpp OpenAI-compatible endpoints
        is_llama_cpp = ("/v1/" in self.base_url or self.base_url.endswith("/v1")) and ("localhost" in self.base_url or "127.0.0.1" in self.base_url)

        if is_llama_cpp:
            return self._call_llama_cpp(prompt, max_tokens, **kwargs)
        elif is_zhipu:
            return self._call_glm(prompt, max_tokens, **kwargs)
        elif is_anthropic:
            return self._call_anthropic(prompt, max_tokens, **kwargs)
        elif is_ollama:
            return self._call_ollama(prompt, max_tokens, **kwargs)
        else:
            return self._call_openai_compatible(prompt, max_tokens, **kwargs)

    def _call_ollama(self, prompt: str, max_tokens: Optional[int] = None, **kwargs) -> str:
        """Call Ollama API."""
        try:
            # Fix double /api path issue
            base_url = self.base_url.rstrip('/')
            if base_url.endswith('/api'):
                endpoint = f"{base_url}/generate"
            else:
                endpoint = f"{base_url}/api/generate"

            request_config = {
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": kwargs.get('temperature', self.config['temperature']),
                    "top_p": 0.9,
                    "num_predict": max_tokens or self.config['max_tokens']
                }
            }

            response = requests.post(
                endpoint,
                json=request_config,
                timeout=kwargs.get('timeout', self.config['timeout'])
            )
            
            if response.status_code == 200:
                resp_json = response.json()
                content = resp_json.get('response', '').strip()
                if not content and 'thinking' in resp_json:
                    content = resp_json['thinking'].strip()
                return content
            else:
                logger.error(f"Ollama API error: {response.status_code} - {response.text}")
                return ""

        except Exception as e:
            logger.error(f"Ollama call failed: {e}")
            return ""

    def _call_llama_cpp(self, prompt: str, max_tokens: Optional[int] = None, **kwargs) -> str:
        """Call llama.cpp server using raw requests (avoids OpenAI SDK httpx issues)."""
        try:
            # Ensure URL has correct endpoint
            url = self.base_url
            if not url.endswith("/chat/completions"):
                url = url.rstrip("/") + "/chat/completions"

            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}" if self.api_key else ""
            }

            prompt_preview = prompt[:100] + "..." if len(prompt) > 100 else prompt
            logger.info(f"Calling llama.cpp (prompt: {prompt_preview}, max_tokens: {max_tokens or self.config['max_tokens']})")

            payload = {
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": kwargs.get('temperature', self.config['temperature']),
                "max_tokens": max_tokens or self.config['max_tokens'],
                "top_p": 0.9
            }

            timeout = kwargs.get('timeout', self.config['timeout'])
            logger.debug(f"Sending request to {url} with timeout {timeout}s")

            response = requests.post(
                url,
                headers=headers,
                json=payload,
                timeout=timeout
            )
            response.raise_for_status()
            data = response.json()

            content = data["choices"][0]["message"]["content"].strip()
            logger.info(f"Received response ({len(content)} chars)")
            return content

        except requests.exceptions.Timeout as e:
            logger.error(f"llama.cpp call timed out after {timeout}s: {e}")
            return ""
        except Exception as e:
            logger.error(f"llama.cpp call failed: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"API Response: {e.response.text}")
            return ""

    def _call_openai_compatible(self, prompt: str, max_tokens: Optional[int] = None, **kwargs) -> str:
        """Call OpenAI-compatible API (vLLM, ZLM, llama.cpp, etc)."""
        if not OPENAI_AVAILABLE:
            logger.error("OpenAI SDK not installed. Cannot make OpenAI-compatible calls.")
            return ""

        # Ensure we have a client
        if not self.client:
            logger.error("OpenAI client not initialized. Cannot make call.")
            return ""

        try:
            logger.info(f"📞 Calling OpenAI-compatible API. Model: {self.model}")

            messages = [{"role": "user", "content": prompt}]

            # Handle extra_body (for thinking or other custom params)
            extra_body = kwargs.get('extra_body', {})

            # Legacy boolean thinking support (if passed directly)
            if kwargs.get('thinking', False):
                 # Default to old behavior if boolean passed, but prefer object if in extra_body
                 if 'thinking' not in extra_body:
                     extra_body['thinking'] = True

            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=kwargs.get('temperature', self.config['temperature']),
                max_tokens=max_tokens or self.config['max_tokens'],
                timeout=kwargs.get('timeout', self.config['timeout']),
                extra_body=extra_body if extra_body else None
            )

            message = response.choices[0].message
            content = message.content

            # Fallback for models (like GLM-4.7/Deepseek) that return output in reasoning_content
            if not content:
                # Try attribute access (standard in some SDKs)
                if hasattr(message, 'reasoning_content') and message.reasoning_content:
                    content = message.reasoning_content
                # Try model_extra (Pydantic models in newer OpenAI SDK)
                elif hasattr(message, 'model_extra') and message.model_extra and 'reasoning_content' in message.model_extra:
                    content = message.model_extra['reasoning_content']
                # Try dict access if it's a dict
                elif isinstance(message, dict) and 'reasoning_content' in message:
                    content = message['reasoning_content']

            return content.strip() if content else ""

        except Exception as e:
            logger.error(f"OpenAI-compatible call failed: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            return ""

    def _call_glm(self, prompt: str, max_tokens: Optional[int] = None, **kwargs) -> str:
        """Call ZhipuAI GLM models."""
        logger.info(f"🤖 _call_glm invoked. Current self.base_url: {self.base_url}")
        
        # Use OpenAI compatible method but ensure correct base_url if not set
        if "api.z.ai" not in self.base_url and "bigmodel.cn" not in self.base_url:
             logger.info("⚠️ ZhipuAI URL not detected. Defaulting to open.bigmodel.cn")
             # Default to open platform if base_url is generic
             self.base_url = "https://open.bigmodel.cn/api/paas/v4/"
             if self.client:
                 self.client.base_url = self.base_url
        
        # Enable thinking for supported models
        if self.model in ['glm-4-flash', 'glm-4-6', 'glm-4.6']:
             # Use the object format required by ZhipuAI coding endpoint
             # kwargs['extra_body'] = {"thinking": {"type": "enabled"}} # DISABLED to save time/tokens
             pass
             
        return self._call_openai_compatible(prompt, max_tokens, **kwargs)

    def _call_anthropic(self, prompt: str, max_tokens: Optional[int] = None, **kwargs) -> str:
        """Call Anthropic API (or ZhipuAI Anthropic compatible)."""
        # Check if using ZhipuAI's Anthropic endpoint
        is_zhipu_anthropic = "api.z.ai" in self.base_url or "bigmodel.cn" in self.base_url
        
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }
        
        if is_zhipu_anthropic:
             # ZhipuAI uses Bearer token for Anthropic endpoint? 
             # Actually documentation says standard Anthropic headers usually.
             # But let's stick to what worked in standalone:
             # If it's Zhipu, we might need different auth or just use the OpenAI endpoint for GLM models.
             # Assuming this is for actual Claude models via some proxy.
             pass

        data = {
            "model": self.model,
            "max_tokens": max_tokens or self.config['max_tokens'],
            "messages": [{"role": "user", "content": prompt}],
            "temperature": kwargs.get('temperature', self.config['temperature'])
        }

        try:
            response = requests.post(
                f"{self.base_url}/messages",
                headers=headers,
                json=data,
                timeout=kwargs.get('timeout', self.config['timeout'])
            )
            
            if response.status_code == 200:
                return response.json()['content'][0]['text']
            else:
                logger.error(f"Anthropic API error: {response.status_code} - {response.text}")
                return ""
        except Exception as e:
            logger.error(f"Anthropic call failed: {e}")
            return ""

    def is_available(self) -> bool:
        """Check if LLM service is available."""
        base_url = self.base_url.rstrip('/')

        # For llama.cpp / OpenAI-compatible endpoints on localhost
        if ("localhost" in base_url or "127.0.0.1" in base_url) and '/v1/' in base_url:
            try:
                # For llama.cpp, just check if port is open
                import socket
                from urllib.parse import urlparse

                parsed = urlparse(base_url)
                host = parsed.hostname or '127.0.0.1'
                port = parsed.port or (443 if parsed.scheme == 'https' else 80)

                logger.info(f"Checking connection to {host}:{port}...")
                sock = socket.create_connection((host, port), timeout=5)
                sock.close()
                logger.info(f"✓ Port {port} is open for {base_url}")
                return True
            except Exception as e:
                logger.error(f"Port check failed for {base_url}: {e}")
                return False

        # Check for Ollama API
        elif '/api/' in base_url or base_url.endswith('/api'):
            try:
                tags_url = f"{base_url}/tags"
                response = requests.get(tags_url, timeout=5)
                return response.status_code == 200
            except Exception as e:
                logger.error(f"Ollama check failed: {e}")
                return False

        # For remote endpoints, try available models
        else:
            try:
                return len(self.get_available_models()) > 0
            except Exception as e:
                logger.error(f"Remote endpoint check failed: {e}")
                return False

    def get_available_models(self) -> List[str]:
        """Get list of available models."""
        try:
            if "localhost" in self.base_url:
                response = requests.get(f"{self.base_url}/api/tags", timeout=10)
                if response.status_code == 200:
                    models = response.json().get('models', [])
                    return [model['name'] for model in models]
            return list(CDMEntityConfig.MODEL_CONFIGS.keys())
        except:
            return []