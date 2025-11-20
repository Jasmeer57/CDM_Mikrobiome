"""
Safety Enhancements Module for Clinical-Grade CDM Pipeline
Provides comprehensive error handling, timeouts, and safety mechanisms
"""

import asyncio
import logging
import signal
import threading
import time
import traceback
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from typing import Dict, List, Optional, Any, Callable
from enum import Enum
import psutil
import os
import json

logger = logging.getLogger(__name__)

class SafetyLevel(Enum):
    """Safety levels for different operation modes"""
    RESEARCH = "research"      # Standard research mode
    CLINICAL = "clinical"      # High-safety clinical mode
    DEVELOPMENT = "development"  # Development mode with detailed logging

@dataclass
class SafetyConfig:
    """Configuration for safety mechanisms"""
    timeout_seconds: int = 300
    max_memory_mb: int = 8192  # 8GB max memory
    max_cpu_percent: float = 80.0
    enable_circuit_breaker: bool = True
    max_retries: int = 3
    retry_delay: float = 1.0
    safety_level: SafetyLevel = SafetyLevel.RESEARCH
    enable_fallback_results: bool = True
    preserve_min_entities: int = 10

class CircuitBreaker:
    """Circuit breaker pattern for preventing cascade failures"""

    def __init__(self, failure_threshold: int = 5, timeout: int = 60):
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.failure_count = 0
        self.last_failure_time = 0
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN

    def call(self, func: Callable, *args, **kwargs):
        """Execute function with circuit breaker protection"""
        if self.state == "OPEN":
            if time.time() - self.last_failure_time > self.timeout:
                self.state = "HALF_OPEN"
            else:
                raise Exception("Circuit breaker is OPEN - call blocked")

        try:
            result = func(*args, **kwargs)
            if self.state == "HALF_OPEN":
                self.state = "CLOSED"
                self.failure_count = 0
            return result
        except Exception as e:
            self.failure_count += 1
            self.last_failure_time = time.time()

            if self.failure_count >= self.failure_threshold:
                self.state = "OPEN"

            raise e

class ResourceManager:
    """Monitors and manages system resources"""

    def __init__(self, config: SafetyConfig):
        self.config = config
        self.process = psutil.Process()

    def check_resources(self) -> Dict[str, Any]:
        """Check current resource usage"""
        try:
            memory_info = self.process.memory_info()
            memory_mb = memory_info.rss / 1024 / 1024
            cpu_percent = self.process.cpu_percent()

            return {
                'memory_mb': memory_mb,
                'memory_percent': (memory_mb / self.config.max_memory_mb) * 100,
                'cpu_percent': cpu_percent,
                'status': 'ok'
            }
        except Exception as e:
            logger.error(f"Resource check failed: {e}")
            return {'status': 'error', 'error': str(e)}

    def is_safe_to_proceed(self) -> bool:
        """Check if it's safe to continue processing"""
        resources = self.check_resources()

        if resources['status'] == 'error':
            return False

        if resources['memory_mb'] > self.config.max_memory_mb:
            logger.warning(f"Memory limit exceeded: {resources['memory_mb']:.1f}MB > {self.config.max_memory_mb}MB")
            return False

        if resources['cpu_percent'] > self.config.max_cpu_percent:
            logger.warning(f"CPU usage high: {resources['cpu_percent']:.1f}% > {self.config.max_cpu_percent}%")
            return False

        return True

class TimeoutManager:
    """Manages operation timeouts with graceful degradation"""

    def __init__(self, config: SafetyConfig):
        self.config = config
        self.active_operations = {}

    @contextmanager
    def timeout_context(self, operation_id: str = None):
        """Context manager for timeout handling"""
        if operation_id is None:
            operation_id = str(id(threading.current_thread()))

        start_time = time.time()
        timeout_occurred = False

        def timeout_handler():
            nonlocal timeout_occurred
            timeout_occurred = True
            logger.warning(f"Operation {operation_id} timed out after {self.config.timeout_seconds}s")

        timer = threading.Timer(self.config.timeout_seconds, timeout_handler)
        timer.start()

        try:
            self.active_operations[operation_id] = {
                'start_time': start_time,
                'timeout': self.config.timeout_seconds
            }
            yield
        except asyncio.TimeoutError:
            logger.error(f"Async timeout for operation {operation_id}")
            raise
        except Exception as e:
            if timeout_occurred:
                raise TimeoutError(f"Operation {operation_id} timed out") from e
            raise
        finally:
            timer.cancel()
            self.active_operations.pop(operation_id, None)

    def get_active_operations(self) -> Dict[str, Any]:
        """Get information about active operations"""
        current_time = time.time()
        active = {}

        for op_id, info in self.active_operations.items():
            elapsed = current_time - info['start_time']
            remaining = info['timeout'] - elapsed
            active[op_id] = {
                'elapsed': elapsed,
                'remaining': max(0, remaining),
                'status': 'running' if remaining > 0 else 'timeout'
            }

        return active

class SafetyErrorHandler:
    """Enhanced error handling with safety mechanisms"""

    def __init__(self, config: SafetyConfig):
        self.config = config
        self.error_history = []
        self.circuit_breaker = CircuitBreaker() if config.enable_circuit_breaker else None
        self.resource_manager = ResourceManager(config)
        self.timeout_manager = TimeoutManager(config)

    def safe_execute(self, func: Callable, *args, **kwargs) -> Dict[str, Any]:
        """Safely execute a function with comprehensive error handling"""
        operation_id = kwargs.pop('operation_id', None)
        fallback_result = kwargs.pop('fallback_result', None)

        # Pre-execution safety checks
        if not self.resource_manager.is_safe_to_proceed():
            error_msg = "Resource limits exceeded - cannot proceed safely"
            logger.error(error_msg)
            return self._create_safe_error_result(error_msg, func.__name__, fallback_result)

        # Execute with circuit breaker if enabled
        if self.circuit_breaker:
            try:
                result = self.circuit_breaker.call(self._execute_with_timeout, func, *args, **kwargs)
                return result
            except Exception as e:
                return self._create_safe_error_result(f"Circuit breaker blocked: {str(e)}", func.__name__, fallback_result)
        else:
            return self._execute_with_timeout(func, *args, **kwargs)

    def _execute_with_timeout(self, func: Callable, *args, **kwargs) -> Dict[str, Any]:
        """Execute function with timeout handling"""
        operation_id = kwargs.pop('operation_id', None)
        fallback_result = kwargs.pop('fallback_result', None)

        try:
            with self.timeout_manager.timeout_context(operation_id):
                start_time = time.time()
                result = func(*args, **kwargs)
                execution_time = time.time() - start_time

                return {
                    'success': True,
                    'result': result,
                    'execution_time': execution_time,
                    'operation_id': operation_id,
                    'error': None,
                    'fallback_used': False
                }

        except FutureTimeoutError as e:
            error_msg = f"Future timeout: {str(e)}"
            logger.error(error_msg)
            return self._create_safe_error_result(error_msg, func.__name__, fallback_result)

        except TimeoutError as e:
            error_msg = f"Operation timeout: {str(e)}"
            logger.error(error_msg)
            return self._create_safe_error_result(error_msg, func.__name__, fallback_result)

        except Exception as e:
            error_msg = f"Execution error: {str(e)}"
            logger.error(f"{error_msg}\n{traceback.format_exc()}")

            # Add to error history for pattern analysis
            self.error_history.append({
                'timestamp': time.time(),
                'function': func.__name__,
                'error': str(e),
                'traceback': traceback.format_exc()
            })

            return self._create_safe_error_result(error_msg, func.__name__, fallback_result)

    def _create_safe_error_result(self, error_msg: str, function_name: str, fallback_result: Any = None) -> Dict[str, Any]:
        """Create a safe error result with fallback if available"""
        result = {
            'success': False,
            'result': None,
            'execution_time': 0,
            'operation_id': None,
            'error': error_msg,
            'fallback_used': False
        }

        # Use fallback result if available and enabled
        if fallback_result is not None and self.config.enable_fallback_results:
            result['result'] = fallback_result
            result['fallback_used'] = True
            logger.info(f"Using fallback result for {function_name}: {error_msg}")

        return result

    def get_error_summary(self) -> Dict[str, Any]:
        """Get summary of recent errors for analysis"""
        recent_errors = [e for e in self.error_history if time.time() - e['timestamp'] < 3600]  # Last hour

        error_counts = {}
        for error in recent_errors:
            func_name = error['function']
            error_counts[func_name] = error_counts.get(func_name, 0) + 1

        return {
            'total_errors': len(recent_errors),
            'error_by_function': error_counts,
            'circuit_breaker_state': self.circuit_breaker.state if self.circuit_breaker else 'disabled',
            'resource_status': self.resource_manager.check_resources(),
            'active_operations': self.timeout_manager.get_active_operations()
        }

class SafeEntityExtractor:
    """Wrapper for entity extraction with safety mechanisms"""

    def __init__(self, original_extractor, safety_config: SafetyConfig):
        self.original_extractor = original_extractor
        self.safety_handler = SafetyErrorHandler(safety_config)
        self.config = safety_config

    def extract_entities_safe(self, text: str, extraction_params: Dict[str, Any]) -> Dict[str, Any]:
        """Extract entities with comprehensive safety measures"""

        # Create fallback result for minimal functionality
        fallback_result = self._create_minimal_fallback(text)

        # Safe execution with all safety mechanisms
        result = self.safety_handler.safe_execute(
            self.original_extractor.extract_entities,
            text,
            operation_id="entity_extraction",
            fallback_result=fallback_result,
            **extraction_params
        )

        # Post-processing safety checks
        if result['success'] and result['result']:
            result['result'] = self._validate_extraction_result(result['result'], text)

        return result

    def _create_minimal_fallback(self, text: str) -> Dict[str, Any]:
        """Create minimal fallback result when extraction fails"""
        # Simple word-based extraction as absolute fallback
        words = text.split()
        potential_entities = [
            word for word in words
            if len(word) > 3 and word.isalpha()
        ][:self.config.preserve_min_entities]

        return {
            'entities': [
                {
                    'entity': entity,
                    'type': 'UNKNOWN',
                    'confidence': 0.5,
                    'source': 'fallback_extraction',
                    'context': 'Fallback extraction due to system limitations'
                }
                for entity in potential_entities
            ],
            'metadata': {
                'extraction_method': 'fallback',
                'warning': 'Primary extraction failed - using fallback method',
                'safety_mode': True
            }
        }

    def _validate_extraction_result(self, result: Dict[str, Any], original_text: str) -> Dict[str, Any]:
        """Validate and sanitize extraction results"""
        if not isinstance(result, dict) or 'entities' not in result:
            logger.warning("Invalid extraction result format, using fallback")
            return self._create_minimal_fallback(original_text)

        entities = result.get('entities', [])

        # Validate each entity
        validated_entities = []
        for entity in entities:
            if self._is_valid_entity(entity):
                # Sanitize entity fields
                validated_entity = {
                    'entity': str(entity.get('entity', ''))[:500],  # Limit length
                    'type': str(entity.get('type', 'UNKNOWN'))[:50],
                    'confidence': min(1.0, max(0.0, float(entity.get('confidence', 0.5)))),
                    'source': str(entity.get('source', 'unknown'))[:100],
                    'context': str(entity.get('context', ''))[:1000]
                }
                validated_entities.append(validated_entity)

        result['entities'] = validated_entities
        result['metadata'] = result.get('metadata', {})
        result['metadata']['safety_validated'] = True
        result['metadata']['original_entity_count'] = len(entities)
        result['metadata']['validated_entity_count'] = len(validated_entities)

        return result

    def _is_valid_entity(self, entity: Any) -> bool:
        """Check if an entity is valid"""
        if not isinstance(entity, dict):
            return False

        required_fields = ['entity']
        for field in required_fields:
            if field not in entity or not entity[field]:
                return False

        entity_str = str(entity.get('entity', ''))
        if len(entity_str.strip()) < 2:
            return False

        return True

# Utility functions for integration
def create_safety_config(safety_level: SafetyLevel = SafetyLevel.RESEARCH) -> SafetyConfig:
    """Create safety configuration based on safety level"""
    configs = {
        SafetyLevel.RESEARCH: SafetyConfig(
            timeout_seconds=300,
            max_memory_mb=8192,
            max_cpu_percent=80.0,
            enable_circuit_breaker=True,
            safety_level=SafetyLevel.RESEARCH
        ),
        SafetyLevel.CLINICAL: SafetyConfig(
            timeout_seconds=120,
            max_memory_mb=4096,
            max_cpu_percent=60.0,
            enable_circuit_breaker=True,
            safety_level=SafetyLevel.CLINICAL,
            preserve_min_entities=20
        ),
        SafetyLevel.DEVELOPMENT: SafetyConfig(
            timeout_seconds=600,
            max_memory_mb=16384,
            max_cpu_percent=90.0,
            enable_circuit_breaker=False,
            safety_level=SafetyLevel.DEVELOPMENT
        )
    }

    return configs.get(safety_level, configs[SafetyLevel.RESEARCH])

def log_safety_metrics(safety_handler: SafetyErrorHandler, output_file: str = None):
    """Log safety metrics for monitoring and compliance"""
    summary = safety_handler.get_error_summary()

    log_entry = {
        'timestamp': time.time(),
        'safety_metrics': summary,
        'system_info': {
            'memory_mb': psutil.virtual_memory().used / 1024 / 1024,
            'cpu_percent': psutil.cpu_percent(),
            'process_count': len(psutil.pids())
        }
    }

    logger.info(f"🛡️ Safety Metrics: {json.dumps(log_entry, indent=2)}")

    if output_file:
        try:
            with open(output_file, 'a') as f:
                f.write(json.dumps(log_entry) + '\n')
        except Exception as e:
            logger.error(f"Failed to write safety metrics to {output_file}: {e}")