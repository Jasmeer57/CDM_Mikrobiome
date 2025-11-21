"""
Resource management and memory optimization for pipeline stability.
Implements proper cleanup, pooling, and resource monitoring.
"""

import logging
import gc
import threading
import time
import psutil
import weakref
from typing import Dict, List, Optional, Any, Union, Callable
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import queue

logger = logging.getLogger(__name__)


@dataclass
class ResourceStats:
    """Resource utilization statistics"""
    memory_mb: float
    memory_percent: float
    cpu_percent: float
    open_files: int
    threads: int
    timestamp: float


class ModelPool:
    """Pool for managing spaCy models to prevent memory leaks"""

    def __init__(self, max_models: int = 3, timeout: float = 300.0):
        self.max_models = max_models
        self.timeout = timeout
        self.pool = weakref.WeakValueDictionary()
        self.last_used = {}
        self.lock = threading.Lock()
        self.cleanup_thread = None
        self._start_cleanup_thread()

    def _start_cleanup_thread(self):
        """Start background cleanup thread"""
        if self.cleanup_thread is None or not self.cleanup_thread.is_alive():
            self.cleanup_thread = threading.Thread(target=self._cleanup_worker, daemon=True)
            self.cleanup_thread.start()

    def _cleanup_worker(self):
        """Background cleanup worker"""
        while True:
            try:
                time.sleep(60)  # Check every minute
                self._cleanup_expired_models()
            except Exception as e:
                logger.error(f"Cleanup worker error: {e}")

    def _cleanup_expired_models(self):
        """Remove expired models from pool"""
        current_time = time.time()
        with self.lock:
            expired_keys = []
            for key, last_used in self.last_used.items():
                if current_time - last_used > self.timeout:
                    expired_keys.append(key)

            for key in expired_keys:
                if key in self.pool:
                    model = self.pool.get(key)
                    if model:
                        try:
                            # Try to clean up spaCy model
                            if hasattr(model, 'disable'):
                                model.disable_pipes()
                            del model
                        except Exception as e:
                            logger.warning(f"Error cleaning up model {key}: {e}")
                    del self.pool[key]
                    del self.last_used[key]
                    logger.debug(f"Cleaned up expired model: {key}")

    @contextmanager
    def get_model(self, model_name: str, load_func: Callable):
        """Get a model from the pool or load it"""
        with self.lock:
            if model_name in self.pool:
                model = self.pool.get(model_name)
                if model is not None:
                    self.last_used[model_name] = time.time()
                    yield model
                    return

        # Model not in pool, load it
        try:
            logger.debug(f"Loading model {model_name}")
            model = load_func(model_name)

            with self.lock:
                # Check pool capacity
                if len(self.pool) >= self.max_models:
                    # Remove oldest model
                    oldest_key = min(self.last_used.keys(), key=lambda k: self.last_used[k])
                    if oldest_key in self.pool:
                        del self.pool[oldest_key]
                    del self.last_used[oldest_key]

                self.pool[model_name] = model
                self.last_used[model_name] = time.time()

            yield model

        except Exception as e:
            logger.error(f"Failed to load model {model_name}: {e}")
            raise

    def clear_pool(self):
        """Clear all models from pool"""
        with self.lock:
            for key in list(self.pool.keys()):
                model = self.pool.get(key)
                if model:
                    try:
                        if hasattr(model, 'disable'):
                            model.disable_pipes()
                        del model
                    except Exception as e:
                        logger.warning(f"Error cleaning up model {key}: {e}")

            self.pool.clear()
            self.last_used.clear()
            gc.collect()
            logger.info("Model pool cleared")


class ResourceManager:
    """Centralized resource management for the pipeline"""

    def __init__(self):
        self.model_pools = {}
        self.thread_pools = {}
        self.resource_stats = []
        self.monitoring = False
        self.monitor_thread = None
        self.lock = threading.Lock()

        # Resource thresholds
        self.memory_threshold_mb = 4096  # 4GB
        self.cpu_threshold_percent = 90.0
        self.max_threads = 50

    def get_model_pool(self, pool_name: str = "default", max_models: int = 3) -> ModelPool:
        """Get or create a model pool"""
        if pool_name not in self.model_pools:
            self.model_pools[pool_name] = ModelPool(max_models=max_models)
        return self.model_pools[pool_name]

    def get_thread_pool(self, pool_name: str = "default", max_workers: int = 4) -> ThreadPoolExecutor:
        """Get or create a thread pool"""
        if pool_name not in self.thread_pools:
            self.thread_pools[pool_name] = ThreadPoolExecutor(
                max_workers=max_workers,
                thread_name_prefix=f"pipeline-{pool_name}"
            )
        return self.thread_pools[pool_name]

    @contextmanager
    def managed_spacy_model(self, model_name: str, model_pool: str = "scispacy"):
        """Context manager for spaCy models with automatic cleanup"""
        pool = self.get_model_pool(model_pool, max_models=3)

        def load_model(name):
            import spacy
            # Load with minimal components to save memory
            nlp = spacy.load(name, disable=["parser"])
            if "sentencizer" not in nlp.pipe_names:
                nlp.add_pipe("sentencizer")
            return nlp

        with pool.get_model(model_name, load_model) as model:
            yield model

    @contextmanager
    def managed_transformer_model(self, model_name: str, model_pool: str = "transformers"):
        """Context manager for transformer models with automatic cleanup"""
        pool = self.get_model_pool(model_pool, max_models=2)

        def load_model(name):
            from sentence_transformers import SentenceTransformer
            return SentenceTransformer(name, trust_remote_code=True)

        with pool.get_model(model_name, load_model) as model:
            yield model

    def start_monitoring(self, interval: float = 30.0):
        """Start resource monitoring"""
        if self.monitoring:
            return

        self.monitoring = True
        self.monitor_thread = threading.Thread(
            target=self._monitor_resources,
            args=(interval,),
            daemon=True
        )
        self.monitor_thread.start()
        logger.info("Resource monitoring started")

    def stop_monitoring(self):
        """Stop resource monitoring"""
        self.monitoring = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=5.0)
        logger.info("Resource monitoring stopped")

    def _monitor_resources(self, interval: float):
        """Resource monitoring worker"""
        while self.monitoring:
            try:
                stats = self.get_current_stats()

                with self.lock:
                    self.resource_stats.append(stats)
                    # Keep only last 100 stats
                    if len(self.resource_stats) > 100:
                        self.resource_stats = self.resource_stats[-100:]

                # Check thresholds
                if stats.memory_mb > self.memory_threshold_mb:
                    logger.warning(f"High memory usage: {stats.memory_mb:.1f} MB")
                    self._trigger_memory_cleanup()

                if stats.cpu_percent > self.cpu_threshold_percent:
                    logger.warning(f"High CPU usage: {stats.cpu_percent:.1f}%")

                time.sleep(interval)

            except Exception as e:
                logger.error(f"Resource monitoring error: {e}")
                time.sleep(interval)

    def get_current_stats(self) -> ResourceStats:
        """Get current resource statistics"""
        try:
            process = psutil.Process()
            memory_info = process.memory_info()

            return ResourceStats(
                memory_mb=memory_info.rss / (1024 * 1024),
                memory_percent=process.memory_percent(),
                cpu_percent=process.cpu_percent(),
                open_files=len(process.open_files()),
                threads=process.num_threads(),
                timestamp=time.time()
            )
        except Exception as e:
            logger.error(f"Failed to get resource stats: {e}")
            return ResourceStats(0, 0, 0, 0, 0, time.time())

    def _trigger_memory_cleanup(self):
        """Trigger aggressive memory cleanup"""
        logger.info("Triggering memory cleanup")

        # Clear model pools
        for pool in self.model_pools.values():
            pool.clear_pool()

        # Force garbage collection
        for _ in range(3):
            gc.collect()

        logger.info("Memory cleanup completed")

    def get_resource_summary(self) -> Dict[str, Any]:
        """Get summary of resource usage"""
        if not self.resource_stats:
            return {"error": "No resource statistics available"}

        latest = self.resource_stats[-1]

        if len(self.resource_stats) > 1:
            # Calculate averages over recent stats
            recent_stats = self.resource_stats[-10:]  # Last 10 measurements
            avg_memory = sum(s.memory_mb for s in recent_stats) / len(recent_stats)
            avg_cpu = sum(s.cpu_percent for s in recent_stats) / len(recent_stats)
        else:
            avg_memory = latest.memory_mb
            avg_cpu = latest.cpu_percent

        return {
            "current": {
                "memory_mb": latest.memory_mb,
                "memory_percent": latest.memory_percent,
                "cpu_percent": latest.cpu_percent,
                "open_files": latest.open_files,
                "threads": latest.threads
            },
            "averages": {
                "memory_mb": avg_memory,
                "cpu_percent": avg_cpu
            },
            "active_pools": len(self.model_pools),
            "active_thread_pools": len(self.thread_pools),
            "total_stats_collected": len(self.resource_stats)
        }

    def cleanup_all(self):
        """Clean up all resources"""
        logger.info("Cleaning up all resources")

        # Clear model pools
        for name, pool in self.model_pools.items():
            pool.clear_pool()
            logger.debug(f"Cleared model pool: {name}")

        # Shutdown thread pools
        for name, pool in self.thread_pools.items():
            pool.shutdown(wait=True)
            logger.debug(f"Shutdown thread pool: {name}")

        # Clear references
        self.model_pools.clear()
        self.thread_pools.clear()

        # Force garbage collection
        for _ in range(3):
            gc.collect()

        # Stop monitoring
        self.stop_monitoring()

        logger.info("Resource cleanup completed")

    def __del__(self):
        """Cleanup on deletion"""
        try:
            self.cleanup_all()
        except Exception:
            pass  # Ignore errors during deletion


class RateLimiter:
    """Rate limiting for API calls"""

    def __init__(self, max_calls: int, time_window: float):
        self.max_calls = max_calls
        self.time_window = time_window
        self.calls = []
        self.lock = threading.Lock()

    def acquire(self) -> bool:
        """Acquire a call slot"""
        with self.lock:
            now = time.time()

            # Remove old calls outside time window
            self.calls = [call_time for call_time in self.calls if now - call_time < self.time_window]

            if len(self.calls) < self.max_calls:
                self.calls.append(now)
                return True

            return False

    def wait_for_slot(self, timeout: float = 60.0) -> bool:
        """Wait for an available call slot"""
        start_time = time.time()

        while time.time() - start_time < timeout:
            if self.acquire():
                return True
            time.sleep(0.1)

        return False

    def get_status(self) -> Dict[str, Any]:
        """Get current rate limiter status"""
        with self.lock:
            now = time.time()
            recent_calls = [call_time for call_time in self.calls if now - call_time < self.time_window]

            return {
                "calls_in_window": len(recent_calls),
                "max_calls": self.max_calls,
                "time_window": self.time_window,
                "available_slots": max(0, self.max_calls - len(recent_calls)),
                "reset_time": max(recent_calls) + self.time_window if recent_calls else now
            }


# Global resource manager instance
_resource_manager = None

def get_resource_manager() -> ResourceManager:
    """Get global resource manager instance"""
    global _resource_manager
    if _resource_manager is None:
        _resource_manager = ResourceManager()
    return _resource_manager

def cleanup_resources():
    """Cleanup global resource manager"""
    global _resource_manager
    if _resource_manager:
        _resource_manager.cleanup_all()
        _resource_manager = None