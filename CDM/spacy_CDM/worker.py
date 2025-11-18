#!/usr/bin/env python3
"""
Background worker for the Microbiome Term Extraction Pipeline.
Handles long-running tasks and background processing.
"""

import os
import sys
import json
import logging
import asyncio
import redis
import signal
from typing import Dict, Any, Optional
from datetime import datetime
import time

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from src.config.settings import PipelineConfig
from main import MicrobiomePipeline

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('worker.log')
    ]
)
logger = logging.getLogger(__name__)

class PipelineWorker:
    """Background worker for pipeline tasks."""

    def __init__(self):
        self.redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
        self.redis = redis.from_url(self.redis_url)
        self.pipeline = None
        self.running = False
        self.worker_id = f"worker_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        # Setup signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        logger.info(f"Worker {self.worker_id} initialized")

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals."""
        logger.info(f"Received signal {signum}, shutting down worker {self.worker_id}")
        self.running = False

    def _create_pipeline(self, config_dict: Dict[str, Any]) -> MicrobiomePipeline:
        """Create pipeline instance from configuration."""
        config = PipelineConfig.from_dict(config_dict)
        return MicrobiomePipeline(config)

    def _update_job_status(self, job_id: str, status: str, progress: float,
                          message: str = None, results: Dict[str, Any] = None):
        """Update job status in Redis."""
        job_data = {
            'job_id': job_id,
            'worker_id': self.worker_id,
            'status': status,
            'progress': progress,
            'updated_at': datetime.now().isoformat()
        }

        if message:
            job_data['message'] = message
        if results:
            job_data['results'] = json.dumps(results, default=str)

        # Store job data in Redis
        job_key = f"job:{job_id}"
        self.redis.hset(job_key, mapping=job_data)
        self.redis.expire(job_key, 3600)  # Expire after 1 hour

        # Publish update
        self.redis.publish(f"job_updates:{job_id}", json.dumps(job_data))

        logger.info(f"Updated job {job_id}: {status} ({progress}%) - {message}")

    def _get_job_config(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get job configuration from Redis."""
        job_key = f"job:{job_id}"
        job_data = self.redis.hgetall(job_key)

        if not job_data:
            logger.error(f"Job {job_id} not found")
            return None

        # Parse configuration
        config_str = job_data.get(b'config', b'{}').decode('utf-8')
        try:
            return json.loads(config_str)
        except json.JSONDecodeError as e:
            logger.error(f"Invalid configuration for job {job_id}: {e}")
            return None

    async def process_job(self, job_id: str):
        """Process a single pipeline job."""
        try:
            logger.info(f"Starting job {job_id}")

            # Get job configuration
            config_dict = self._get_job_config(job_id)
            if not config_dict:
                self._update_job_status(job_id, 'failed', 0, 'Invalid job configuration')
                return

            # Update status to running
            self._update_job_status(job_id, 'running', 10, 'Initializing pipeline')

            # Create pipeline
            self.pipeline = self._create_pipeline(config_dict)

            # Get input data from job
            job_key = f"job:{job_id}"
            input_files = self.redis.hget(job_key, 'input_files')
            input_text = self.redis.hget(job_key, 'input_text')

            # Process input
            input_path = None
            if input_files:
                input_path = input_files.decode('utf-8')
            elif input_text:
                # Create temporary file with text
                import tempfile
                with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
                    f.write(input_text.decode('utf-8'))
                    input_path = f.name

            if not input_path:
                raise ValueError("No input data provided")

            self._update_job_status(job_id, 'running', 30, 'Running pipeline')

            # Run pipeline
            results = self.pipeline.run(input_path, config_dict.get('output_dir', './output'))

            # Update job with results
            self._update_job_status(
                job_id,
                'completed',
                100,
                'Pipeline completed successfully',
                results
            )

            logger.info(f"Job {job_id} completed successfully")

        except Exception as e:
            logger.error(f"Job {job_id} failed: {e}")
            self._update_job_status(
                job_id,
                'failed',
                0,
                f'Pipeline failed: {str(e)}'
            )

    async def run(self):
        """Main worker loop."""
        self.running = True
        logger.info(f"Worker {self.worker_id} started")

        # Subscribe to job queue
        pubsub = self.redis.pubsub()
        pubsub.subscribe('pipeline_jobs')

        while self.running:
            try:
                # Check for new jobs
                message = pubsub.get_message(timeout=1.0)
                if message and message['type'] == 'message':
                    job_data = json.loads(message['data'])
                    job_id = job_data.get('job_id')

                    if job_id:
                        logger.info(f"Received job {job_id}")
                        await self.process_job(job_id)

                # Small delay to prevent busy waiting
                await asyncio.sleep(0.1)

            except redis.ConnectionError:
                logger.error("Redis connection lost, attempting to reconnect...")
                try:
                    self.redis = redis.from_url(self.redis_url)
                    pubsub = self.redis.pubsub()
                    pubsub.subscribe('pipeline_jobs')
                except Exception as e:
                    logger.error(f"Failed to reconnect to Redis: {e}")
                    await asyncio.sleep(5.0)

            except Exception as e:
                logger.error(f"Worker error: {e}")
                await asyncio.sleep(1.0)

        logger.info(f"Worker {self.worker_id} stopped")

    def start(self):
        """Start the worker."""
        asyncio.run(self.run())

class SimpleWorker:
    """Simple worker without Redis for basic background processing."""

    def __init__(self):
        self.queue = []
        self.running = False
        logger.info("Simple worker initialized")

    def add_job(self, job_id: str, config: Dict[str, Any], input_data: str):
        """Add a job to the queue."""
        job = {
            'job_id': job_id,
            'config': config,
            'input_data': input_data,
            'status': 'queued',
            'created_at': datetime.now()
        }
        self.queue.append(job)
        logger.info(f"Added job {job_id} to queue")

    def process_queue(self):
        """Process all jobs in the queue."""
        self.running = True

        for i, job in enumerate(self.queue):
            try:
                job_id = job['job_id']
                config = job['config']
                input_data = job['input_data']

                logger.info(f"Processing job {job_id} ({i+1}/{len(self.queue)})")

                # Create pipeline
                pipeline_config = PipelineConfig.from_dict(config)
                pipeline = MicrobiomePipeline(pipeline_config)

                # Run pipeline
                results = pipeline.run(input_data, config.get('output_dir', './output'))

                # Update job status
                job['status'] = 'completed'
                job['results'] = results
                job['completed_at'] = datetime.now()

                logger.info(f"Job {job_id} completed")

            except Exception as e:
                logger.error(f"Job {job['job_id']} failed: {e}")
                job['status'] = 'failed'
                job['error'] = str(e)
                job['failed_at'] = datetime.now()

        self.running = False

    def get_job_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get status of a specific job."""
        for job in self.queue:
            if job['job_id'] == job_id:
                return job
        return None

    def stop(self):
        """Stop the worker."""
        self.running = False

def main():
    """Main entry point."""
    use_redis = os.getenv('USE_REDIS', 'true').lower() == 'true'

    if use_redis:
        worker = PipelineWorker()
    else:
        worker = SimpleWorker()

    try:
        worker.start()
    except KeyboardInterrupt:
        logger.info("Worker stopped by user")
    except Exception as e:
        logger.error(f"Worker crashed: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()