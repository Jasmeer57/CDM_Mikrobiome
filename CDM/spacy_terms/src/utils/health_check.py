"""
Health check and system validation module for pipeline reliability.
Implements comprehensive model validation and system health monitoring.
"""

import logging
import psutil
import gc
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from pathlib import Path
import json
import time
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


@dataclass
class HealthStatus:
    """Health status for a component"""
    name: str
    status: str  # "healthy", "degraded", "unhealthy"
    message: str
    last_check: datetime
    response_time: float = 0.0
    metrics: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SystemHealth:
    """Overall system health status"""
    status: str
    components: List[HealthStatus]
    timestamp: datetime
    system_metrics: Dict[str, Any] = field(default_factory=dict)

    def is_healthy(self) -> bool:
        """Check if all components are healthy"""
        return all(comp.status == "healthy" for comp in self.components)


class HealthChecker:
    """Comprehensive health checking for pipeline components"""

    def __init__(self):
        self.component_checks = {}
        self.last_system_check = None

    def register_component(self, name: str, check_function):
        """Register a component health check"""
        self.component_checks[name] = check_function

    def check_system_health(self) -> SystemHealth:
        """Perform comprehensive system health check"""
        components = []
        system_start = time.time()

        # Check all registered components
        for name, check_func in self.component_checks.items():
            try:
                start_time = time.time()
                status, message, metrics = check_func()
                response_time = time.time() - start_time

                health_status = HealthStatus(
                    name=name,
                    status=status,
                    message=message,
                    last_check=datetime.now(),
                    response_time=response_time,
                    metrics=metrics
                )
                components.append(health_status)

            except Exception as e:
                logger.error(f"Health check failed for {name}: {e}")
                components.append(HealthStatus(
                    name=name,
                    status="unhealthy",
                    message=f"Health check exception: {str(e)}",
                    last_check=datetime.now(),
                    response_time=0.0
                ))

        # System metrics
        system_metrics = self._get_system_metrics()
        system_time = time.time() - system_start

        # Determine overall status
        if any(comp.status == "unhealthy" for comp in components):
            overall_status = "unhealthy"
        elif any(comp.status == "degraded" for comp in components):
            overall_status = "degraded"
        else:
            overall_status = "healthy"

        self.last_system_check = SystemHealth(
            status=overall_status,
            components=components,
            timestamp=datetime.now(),
            system_metrics=system_metrics
        )

        return self.last_system_check

    def _get_system_metrics(self) -> Dict[str, Any]:
        """Get system performance metrics"""
        try:
            return {
                "cpu_percent": psutil.cpu_percent(interval=1),
                "memory_percent": psutil.virtual_memory().percent,
                "memory_available_gb": psutil.virtual_memory().available / (1024**3),
                "disk_usage_percent": psutil.disk_usage('/').percent,
                "process_count": len(psutil.pids()),
                "python_memory_mb": psutil.Process().memory_info().rss / (1024**2),
                "gc_stats": gc.get_stats()[:2]  # First 2 generations
            }
        except Exception as e:
            logger.warning(f"Failed to get system metrics: {e}")
            return {"error": str(e)}


class ModelValidator:
    """Validation for ML models and NLP components"""

    def __init__(self):
        self.validation_cache = {}
        self.cache_timeout = timedelta(minutes=5)

    def validate_spacy_model(self, model_name: str) -> Tuple[str, str, Dict[str, Any]]:
        """Validate a spaCy model"""
        cache_key = f"spacy_{model_name}"

        if self._is_cached(cache_key):
            return self._get_cached_result(cache_key)

        try:
            import spacy

            start_time = time.time()
            nlp = spacy.load(model_name, disable=["parser"])
            load_time = time.time() - start_time

            # Test basic functionality
            test_text = "This is a test sentence with biological terms like DNA and protein."
            doc = nlp(test_text)

            metrics = {
                "load_time_seconds": load_time,
                "vocab_size": len(nlp.vocab),
                "pipe_names": list(nlp.pipe_names),
                "test_entities": len(doc.ents),
                "model_path": str(spacy.util.find_package(model_name)) if hasattr(spacy.util, 'find_package') else None
            }

            # Check for required components
            has_ner = "ner" in nlp.pipe_names
            has_sentencizer = any(comp in nlp.pipe_names for comp in ["sentencizer", "senter"])

            if not has_ner:
                return "degraded", "Model loaded but missing NER component", metrics
            if not has_sentencizer:
                return "degraded", "Model loaded but missing sentence boundary detection", metrics

            return "healthy", "Model fully functional", metrics

        except ImportError:
            return "unhealthy", "spaCy not installed", {}
        except OSError as e:
            return "unhealthy", f"Model '{model_name}' not found or corrupted", {"error": str(e)}
        except Exception as e:
            return "unhealthy", f"Model validation failed: {str(e)}", {"error": str(e)}
        finally:
            self._cache_result(cache_key, (status, message, metrics))

    def validate_transformer_model(self, model_name: str) -> Tuple[str, str, Dict[str, Any]]:
        """Validate a sentence transformer model"""
        cache_key = f"transformer_{model_name}"

        if self._is_cached(cache_key):
            return self._get_cached_result(cache_key)

        try:
            from sentence_transformers import SentenceTransformer
            import torch

            start_time = time.time()
            model = SentenceTransformer(model_name, trust_remote_code=True)
            load_time = time.time() - start_time

            # Test basic functionality
            test_sentences = [
                "This is a test sentence.",
                "This is another test sentence."
            ]

            with torch.no_grad():
                embeddings = model.encode(test_sentences, show_progress_bar=False)

            metrics = {
                "load_time_seconds": load_time,
                "embedding_dim": embeddings.shape[1],
                "model_max_seq_length": getattr(model, 'max_seq_length', 'unknown'),
                "device": str(model.device) if hasattr(model, 'device') else 'unknown',
                "test_embedding_shape": embeddings.shape,
                "model_config": model.get_config_dict() if hasattr(model, 'get_config_dict') else {}
            }

            # Basic sanity checks
            if embeddings.shape[0] != len(test_sentences):
                return "unhealthy", "Embedding output shape mismatch", metrics
            if embeddings.shape[1] == 0:
                return "unhealthy", "Zero-dimensional embeddings", metrics

            return "healthy", "Transformer model fully functional", metrics

        except ImportError:
            return "unhealthy", "sentence-transformers not installed", {}
        except Exception as e:
            return "unhealthy", f"Transformer validation failed: {str(e)}", {"error": str(e)}
        finally:
            self._cache_result(cache_key, (status, message, metrics))

    def validate_api_access(self, url: str, api_key: str = None) -> Tuple[str, str, Dict[str, Any]]:
        """Validate API connectivity"""
        cache_key = f"api_{url}"

        if self._is_cached(cache_key):
            return self._get_cached_result(cache_key)

        try:
            import requests

            headers = {}
            if api_key:
                headers['Authorization'] = f'Bearer {api_key}'

            start_time = time.time()
            response = requests.get(url, headers=headers, timeout=10)
            response_time = time.time() - start_time

            metrics = {
                "response_time_seconds": response_time,
                "status_code": response.status_code,
                "response_headers": dict(response.headers),
                "url": url
            }

            if response.status_code == 200:
                return "healthy", "API accessible", metrics
            elif response.status_code in [401, 403]:
                return "unhealthy", "API authentication failed", metrics
            elif response.status_code >= 500:
                return "degraded", "API server error", metrics
            else:
                return "degraded", f"API returned unexpected status: {response.status_code}", metrics

        except requests.exceptions.Timeout:
            return "unhealthy", "API request timeout", {"timeout": 10}
        except requests.exceptions.ConnectionError:
            return "unhealthy", "API connection failed", {"connection_error": True}
        except Exception as e:
            return "unhealthy", f"API validation failed: {str(e)}", {"error": str(e)}
        finally:
            self._cache_result(cache_key, (status, message, metrics))

    def _is_cached(self, cache_key: str) -> bool:
        """Check if cached result is still valid"""
        if cache_key not in self.validation_cache:
            return False

        cached_time, _ = self.validation_cache[cache_key]
        return datetime.now() - cached_time < self.cache_timeout

    def _get_cached_result(self, cache_key: str) -> Tuple[str, str, Dict[str, Any]]:
        """Get cached validation result"""
        _, result = self.validation_cache[cache_key]
        return result

    def _cache_result(self, cache_key: str, result: Tuple[str, str, Dict[str, Any]]):
        """Cache validation result"""
        self.validation_cache[cache_key] = (datetime.now(), result)

    def clear_cache(self):
        """Clear validation cache"""
        self.validation_cache.clear()


class DataValidator:
    """Validation for data quality and pipeline outputs"""

    @staticmethod
    def validate_term_data(terms: List[Dict[str, Any]]) -> Tuple[str, str, Dict[str, Any]]:
        """Validate extracted term data quality"""
        if not terms:
            return "degraded", "No terms to validate", {"term_count": 0}

        issues = []
        metrics = {
            "total_terms": len(terms),
            "invalid_terms": 0,
            "missing_fields": 0,
            "duplicate_terms": 0,
            "empty_examples": 0,
            "avg_confidence": 0.0,
            "quality_score": 0.0
        }

        # Check required fields
        required_fields = ['term', 'models_used', 'relevance_score', 'frequency']
        term_texts = set()

        confidences = []
        quality_issues = 0

        for i, term_data in enumerate(terms):
            # Check required fields
            missing_fields = [field for field in required_fields if field not in term_data]
            if missing_fields:
                issues.append(f"Term {i}: Missing fields {missing_fields}")
                metrics["missing_fields"] += len(missing_fields)

            # Check term validity
            term = term_data.get('term', '')
            if not term or len(term.strip()) < 2:
                metrics["invalid_terms"] += 1
                continue

            # Check for duplicates
            term_lower = term.lower()
            if term_lower in term_texts:
                metrics["duplicate_terms"] += 1
            term_texts.add(term_lower)

            # Check examples
            examples = term_data.get('examples', [])
            if not examples or all(not ex.strip() for ex in examples):
                metrics["empty_examples"] += 1

            # Collect confidence scores
            confidence = term_data.get('relevance_score', 0.0)
            confidences.append(confidence)

            if confidence < 0.3:  # Low quality threshold
                quality_issues += 1

        # Calculate metrics
        if confidences:
            metrics["avg_confidence"] = sum(confidences) / len(confidences)

        metrics["quality_score"] = max(0, 100 - (quality_issues / len(terms) * 100))
        metrics["unique_terms"] = len(term_texts)

        # Determine status
        if metrics["invalid_terms"] > len(terms) * 0.1:  # >10% invalid
            return "unhealthy", f"High number of invalid terms: {metrics['invalid_terms']}", metrics
        elif metrics["missing_fields"] > 0:
            return "degraded", f"Missing fields in {metrics['missing_fields']} terms", metrics
        elif metrics["quality_score"] < 50:
            return "degraded", f"Low data quality score: {metrics['quality_score']:.1f}", metrics
        else:
            return "healthy", "Data validation passed", metrics

    @staticmethod
    def validate_deduplication_quality(original_count: int, final_count: int,
                                      reduction_rate: float) -> Tuple[str, str, Dict[str, Any]]:
        """Validate deduplication quality"""
        metrics = {
            "original_count": original_count,
            "final_count": final_count,
            "reduction_rate": reduction_rate,
            "reduction_absolute": original_count - final_count
        }

        if reduction_rate > 0.95:  # >95% reduction
            return "unhealthy", "Excessive deduplication - possible data loss", metrics
        elif reduction_rate < 0.1:  # <10% reduction
            return "degraded", "Insufficient deduplication", metrics
        elif reduction_rate > 0.8:  # >80% reduction
            return "degraded", "High deduplication rate - review needed", metrics
        else:
            return "healthy", "Deduplication quality acceptable", metrics


# Global health checker instance
_health_checker = HealthChecker()
_model_validator = ModelValidator()

def get_health_checker() -> HealthChecker:
    """Get global health checker instance"""
    return _health_checker

def get_model_validator() -> ModelValidator:
    """Get global model validator instance"""
    return _model_validator

def create_default_health_checks(config) -> HealthChecker:
    """Create and configure default health checks"""
    health_checker = HealthChecker()

    # Register spaCy model checks
    def check_scispacy_models():
        failed_models = []
        total_models = len(config.scispacy.models)

        for model_name in config.scispacy.models:
            status, message, _ = _model_validator.validate_spacy_model(model_name)
            if status != "healthy":
                failed_models.append(f"{model_name}: {message}")

        if not failed_models:
            return "healthy", f"All {total_models} spaCy models healthy", {"models_checked": total_models}
        elif len(failed_models) == total_models:
            return "unhealthy", f"All spaCy models failed: {'; '.join(failed_models[:3])}", {"failed_models": failed_models}
        else:
            return "degraded", f"{len(failed_models)}/{total_models} spaCy models have issues", {"failed_models": failed_models}

    # Register semantic model check
    def check_semantic_model():
        model_name = config.deduplication.semantic_models[config.deduplication.default_semantic_model]
        return _model_validator.validate_transformer_model(model_name)

    # Register AI model check
    def check_ai_model():
        if not config.ai_correction.enabled:
            return "healthy", "AI correction disabled", {"status": "disabled"}

        model_name = config.ai_correction.model_name
        return _model_validator.validate_transformer_model(model_name)

    # Register UMLS model check
    def check_umls_model():
        if not config.umls.enabled:
            return "healthy", "UMLS mapping disabled", {"status": "disabled"}

        return _model_validator.validate_spacy_model("en_core_sci_lg")

    # Register system resource check
    def check_system_resources():
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')

        if memory.percent > 90:
            return "unhealthy", f"High memory usage: {memory.percent:.1f}%", {
                "memory_percent": memory.percent,
                "memory_available_gb": memory.available / (1024**3)
            }
        elif disk.percent > 90:
            return "unhealthy", f"High disk usage: {disk.percent:.1f}%", {
                "disk_percent": disk.percent,
                "disk_free_gb": disk.free / (1024**3)
            }
        elif memory.percent > 80:
            return "degraded", f"Moderate memory usage: {memory.percent:.1f}%", {
                "memory_percent": memory.percent
            }
        else:
            return "healthy", "System resources acceptable", {
                "memory_percent": memory.percent,
                "disk_percent": disk.percent
            }

    # Register all checks
    health_checker.register_component("scispacy_models", check_scispacy_models)
    health_checker.register_component("semantic_model", check_semantic_model)
    health_checker.register_component("ai_model", check_ai_model)
    health_checker.register_component("umls_model", check_umls_model)
    health_checker.register_component("system_resources", check_system_resources)

    return health_checker