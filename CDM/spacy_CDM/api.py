#!/usr/bin/env python3
"""
FastAPI REST API for the Microbiome Term Extraction Pipeline.
Provides production-ready web service with comprehensive endpoints.
"""

import os
import sys
import json
import asyncio
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional, Union
import tempfile
import shutil
from datetime import datetime

# FastAPI imports
from fastapi import FastAPI, HTTPException, BackgroundTasks, UploadFile, File, Form, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
import uvicorn

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from src.config.settings import PipelineConfig
from main import MicrobiomePipeline

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Security
security = HTTPBearer()

# Pydantic models
class PipelineRequest(BaseModel):
    """Request model for pipeline execution."""
    input_files: Optional[List[str]] = Field(None, description="List of input file paths")
    input_text: Optional[str] = Field(None, description="Input text to process")
    config: Optional[Dict[str, Any]] = Field(None, description="Pipeline configuration")
    options: Optional[Dict[str, Any]] = Field(None, description="Processing options")

class PipelineResponse(BaseModel):
    """Response model for pipeline results."""
    success: bool
    message: str
    job_id: Optional[str] = None
    results: Optional[Dict[str, Any]] = None
    status: Optional[str] = None

class JobStatus(BaseModel):
    """Job status model."""
    job_id: str
    status: str
    progress: float
    message: Optional[str] = None
    results: Optional[Dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime

class ConfigRequest(BaseModel):
    """Configuration request model."""
    config: Dict[str, Any]
    validate_only: bool = False

class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    version: str
    timestamp: datetime
    modules: Dict[str, str]
    dependencies: Dict[str, bool]
    memory_usage: Optional[Dict[str, float]] = None

# Job management
class JobManager:
    """Manages background pipeline jobs."""

    def __init__(self):
        self.jobs: Dict[str, Dict[str, Any]] = {}
        self.max_jobs = 10

    def create_job(self, config: PipelineConfig, options: Dict[str, Any]) -> str:
        """Create a new pipeline job."""
        job_id = f"job_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{len(self.jobs)}"

        job = {
            'job_id': job_id,
            'status': 'pending',
            'progress': 0.0,
            'message': 'Job created',
            'results': None,
            'config': config,
            'options': options,
            'created_at': datetime.now(),
            'updated_at': datetime.now(),
            'pipeline': None
        }

        # Limit concurrent jobs
        if len(self.jobs) >= self.max_jobs:
            oldest_job = min(self.jobs.keys(),
                           key=lambda k: self.jobs[k]['created_at'])
            del self.jobs[oldest_job]

        self.jobs[job_id] = job
        return job_id

    def update_job(self, job_id: str, status: str, progress: float,
                   message: str = None, results: Dict[str, Any] = None):
        """Update job status."""
        if job_id in self.jobs:
            self.jobs[job_id]['status'] = status
            self.jobs[job_id]['progress'] = progress
            self.jobs[job_id]['updated_at'] = datetime.now()
            if message:
                self.jobs[job_id]['message'] = message
            if results:
                self.jobs[job_id]['results'] = results

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get job by ID."""
        return self.jobs.get(job_id)

    def list_jobs(self) -> List[Dict[str, Any]]:
        """List all jobs."""
        return list(self.jobs.values())

# Global instances
job_manager = JobManager()
app = FastAPI(
    title="Microbiome Term Extraction API",
    description="Production-ready API for microbiome scientific term extraction",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1000)

# Dependency to verify API key (optional)
async def verify_api_key(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Verify API key (implement as needed)."""
    # For now, accept any token. Implement proper authentication in production.
    return credentials.credentials

# Health and info endpoints
@app.get("/", response_model=Dict[str, Any])
async def root():
    """Root endpoint with API information."""
    return {
        "name": "Microbiome Term Extraction API",
        "version": "1.0.0",
        "description": "Production-ready API for microbiome scientific term extraction",
        "endpoints": {
            "health": "/health",
            "docs": "/docs",
            "pipeline": "/pipeline",
            "jobs": "/jobs"
        }
    }

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Comprehensive health check."""
    try:
        # Check system status
        status = "healthy"
        timestamp = datetime.now()

        # Check modules
        modules = {
            "terms_extractor": "available",
            "deduplication": "available",
            "umls_mapper": "available",
            "ai_cleaner": "available",
            "omop_processor": "available"
        }

        # Check dependencies
        dependencies = {
            'spacy': False,
            'scispacy': False,
            'sentence_transformers': False,
            'transformers': False,
            'fastapi': False,
            'pandas': False
        }

        for dep in dependencies:
            try:
                __import__(dep.replace('-', '_'))
                dependencies[dep] = True
            except ImportError:
                pass

        # Memory usage (basic)
        memory_usage = None
        try:
            import psutil
            process = psutil.Process()
            memory_usage = {
                "rss_mb": process.memory_info().rss / 1024 / 1024,
                "vms_mb": process.memory_info().vms / 1024 / 1024,
                "percent": process.memory_percent()
            }
        except ImportError:
            pass

        # Check if any critical dependencies are missing
        if not dependencies['spacy'] or not dependencies['fastapi']:
            status = "unhealthy"

        return HealthResponse(
            status=status,
            version="1.0.0",
            timestamp=timestamp,
            modules=modules,
            dependencies=dependencies,
            memory_usage=memory_usage
        )

    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=503, detail=f"Service unavailable: {e}")

@app.get("/info")
async def get_info():
    """Get detailed API and pipeline information."""
    return {
        "api_version": "1.0.0",
        "pipeline_version": "1.0.0",
        "available_models": {
            "scispacy": [
                "en_ner_craft_md", "en_ner_bc5cdr_md",
                "en_core_sci_lg", "en_ner_jnlpba_md"
            ],
            "semantic": [
                "all-MiniLM-L12-v2",
                "nomic-embed-text-v1",
                "all-mpnet-base-v2"
            ],
            "ai": ["mistralai/Mistral-7B-Instruct-v0.2"]
        },
        "supported_formats": [
            "txt", "json", "csv", "tsv"
        ],
        "output_formats": [
            "json", "csv", "parquet"
        ],
        "configuration": {
            "default_config": "Available via /config/default",
            "validation": "POST /config/validate"
        }
    }

# Configuration endpoints
@app.get("/config/default")
async def get_default_config():
    """Get default pipeline configuration."""
    config = PipelineConfig()
    return config.to_dict()

@app.post("/config/validate")
async def validate_config(request: ConfigRequest):
    """Validate pipeline configuration."""
    try:
        # Create configuration from dict
        config = PipelineConfig.from_dict(request.config)

        # Basic validation
        errors = []
        warnings = []

        # Validate input directory
        if config.input_dir and not Path(config.input_dir).exists():
            errors.append(f"Input directory does not exist: {config.input_dir}")

        # Validate output directory
        if config.output_dir:
            try:
                Path(config.output_dir).mkdir(parents=True, exist_ok=True)
            except Exception as e:
                errors.append(f"Cannot create output directory: {e}")

        # Validate models
        for model in config.scispacy.models:
            try:
                import spacy
                spacy.load(model)
            except OSError:
                warnings.append(f"SciSpaCy model not available: {model}")

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "config": config.to_dict()
        }

    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Configuration validation failed: {e}")

# Pipeline endpoints
@app.post("/pipeline", response_model=PipelineResponse)
async def run_pipeline(
    request: PipelineRequest,
    background_tasks: BackgroundTasks,
    api_key: str = Depends(verify_api_key)
):
    """Execute the pipeline with provided input."""
    try:
        # Create configuration
        if request.config:
            config = PipelineConfig.from_dict(request.config)
        else:
            config = PipelineConfig()

        # Prepare options
        options = request.options or {}

        # Create job
        job_id = job_manager.create_job(config, options)

        # Add background task
        background_tasks.add_task(run_pipeline_task, job_id, request)

        return PipelineResponse(
            success=True,
            message="Pipeline job started",
            job_id=job_id,
            status="pending"
        )

    except Exception as e:
        logger.error(f"Pipeline execution failed: {e}")
        raise HTTPException(status_code=500, detail=f"Pipeline execution failed: {e}")

@app.post("/pipeline/upload")
async def run_pipeline_with_files(
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(...),
    config: str = Form(None),
    options: str = Form(None),
    api_key: str = Depends(verify_api_key)
):
    """Execute pipeline with uploaded files."""
    try:
        # Parse config and options
        config_dict = json.loads(config) if config else {}
        options_dict = json.loads(options) if options else {}

        # Create configuration
        config = PipelineConfig.from_dict(config_dict)

        # Create temporary directory for uploaded files
        temp_dir = tempfile.mkdtemp()

        # Save uploaded files
        input_files = []
        for file in files:
            file_path = Path(temp_dir) / file.filename
            with open(file_path, "wb") as f:
                content = await file.read()
                f.write(content)
            input_files.append(str(file_path))

        # Update options with file paths
        options_dict['input_files'] = input_files
        options_dict['temp_dir'] = temp_dir

        # Create job
        job_id = job_manager.create_job(config, options_dict)

        # Add background task
        background_tasks.add_task(run_pipeline_task_with_files, job_id, input_files, config, options_dict)

        return PipelineResponse(
            success=True,
            message="Pipeline job started with uploaded files",
            job_id=job_id,
            status="pending"
        )

    except Exception as e:
        logger.error(f"File upload pipeline failed: {e}")
        raise HTTPException(status_code=500, detail=f"File upload pipeline failed: {e}")

# Job management endpoints
@app.get("/jobs", response_model=List[JobStatus])
async def list_jobs():
    """List all pipeline jobs."""
    jobs = job_manager.list_jobs()
    return [
        JobStatus(**{k: v for k, v in job.items() if k != 'pipeline'})
        for job in jobs
    ]

@app.get("/jobs/{job_id}", response_model=JobStatus)
async def get_job_status(job_id: str):
    """Get status of a specific job."""
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    return JobStatus(**{k: v for k, v in job.items() if k != 'pipeline'})

@app.delete("/jobs/{job_id}")
async def delete_job(job_id: str):
    """Delete a job and its results."""
    if job_id not in job_manager.jobs:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    # Clean up temporary directory if exists
    job = job_manager.jobs[job_id]
    if 'temp_dir' in job.get('options', {}):
        temp_dir = job['options']['temp_dir']
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception as e:
            logger.warning(f"Failed to clean up temp directory {temp_dir}: {e}")

    del job_manager.jobs[job_id]
    return {"message": f"Job {job_id} deleted successfully"}

@app.get("/jobs/{job_id}/results")
async def get_job_results(job_id: str):
    """Get results of a completed job."""
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    if job['status'] != 'completed':
        raise HTTPException(status_code=400, detail=f"Job {job_id} is not completed")

    return job.get('results', {})

@app.get("/jobs/{job_id}/download")
async def download_job_results(job_id: str):
    """Download results as a file."""
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    if job['status'] != 'completed':
        raise HTTPException(status_code=400, detail=f"Job {job_id} is not completed")

    # Create temporary file with results
    temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
    json.dump(job.get('results', {}), temp_file, indent=2, default=str)
    temp_file.close()

    return FileResponse(
        temp_file.name,
        media_type='application/json',
        filename=f"pipeline_results_{job_id}.json"
    )

# Background tasks
async def run_pipeline_task(job_id: str, request: PipelineRequest):
    """Background task to run pipeline."""
    try:
        job = job_manager.get_job(job_id)
        if not job:
            return

        config = job['config']
        options = job['options']

        # Update job status
        job_manager.update_job(job_id, "running", 10.0, "Initializing pipeline")

        # Create pipeline
        pipeline = MicrobiomePipeline(config)
        job['pipeline'] = pipeline

        # Prepare input
        input_data = None
        if request.input_files:
            input_data = request.input_files
        elif request.input_text:
            # Create temporary file with text
            temp_dir = tempfile.mkdtemp()
            temp_file = Path(temp_dir) / "input.txt"
            temp_file.write_text(request.input_text, encoding='utf-8')
            input_data = str(temp_file)
            options['temp_dir'] = temp_dir

        if not input_data:
            raise ValueError("No input data provided")

        # Run pipeline
        job_manager.update_job(job_id, "running", 30.0, "Running pipeline")

        results = pipeline.run(input_data, config.output_dir)

        # Update job with results
        job_manager.update_job(
            job_id,
            "completed",
            100.0,
            "Pipeline completed successfully",
            results
        )

    except Exception as e:
        logger.error(f"Pipeline job {job_id} failed: {e}")
        job_manager.update_job(
            job_id,
            "failed",
            0.0,
            f"Pipeline failed: {str(e)}"
        )

async def run_pipeline_task_with_files(job_id: str, input_files: List[str],
                                     config: PipelineConfig, options: Dict[str, Any]):
    """Background task to run pipeline with uploaded files."""
    try:
        job = job_manager.get_job(job_id)
        if not job:
            return

        # Update job status
        job_manager.update_job(job_id, "running", 10.0, "Processing uploaded files")

        # Create pipeline
        pipeline = MicrobiomePipeline(config)
        job['pipeline'] = pipeline

        # Run pipeline
        job_manager.update_job(job_id, "running", 30.0, "Running pipeline")

        # Use the first file as input directory or create temp directory
        if len(input_files) == 1 and Path(input_files[0]).is_file():
            temp_dir = tempfile.mkdtemp()
            shutil.copy(input_files[0], temp_dir)
            input_path = temp_dir
        else:
            input_path = Path(input_files[0]).parent

        results = pipeline.run(input_path, config.output_dir)

        # Update job with results
        job_manager.update_job(
            job_id,
            "completed",
            100.0,
            "Pipeline completed successfully",
            results
        )

    except Exception as e:
        logger.error(f"Pipeline job {job_id} failed: {e}")
        job_manager.update_job(
            job_id,
            "failed",
            0.0,
            f"Pipeline failed: {str(e)}"
        )
    finally:
        # Clean up temporary directory
        if 'temp_dir' in options:
            try:
                shutil.rmtree(options['temp_dir'], ignore_errors=True)
            except Exception as e:
                logger.warning(f"Failed to clean up temp directory: {e}")

# Utility endpoints
@app.get("/models")
async def list_available_models():
    """List available models for processing."""
    models = {
        "scispacy": [],
        "semantic": [],
        "ai": []
    }

    # Check SciSpaCy models
    scispacy_models = [
        'en_ner_craft_md', 'en_ner_bc5cdr_md',
        'en_core_sci_lg', 'en_ner_jnlpba_md'
    ]

    for model in scispacy_models:
        try:
            import spacy
            spacy.load(model)
            models["scispacy"].append(model)
        except OSError:
            pass

    # Check semantic models
    semantic_models = ['all-MiniLM-L12-v2', 'nomic-embed-text-v1', 'all-mpnet-base-v2']
    for model in semantic_models:
        try:
            from sentence_transformers import SentenceTransformer
            SentenceTransformer(model)
            models["semantic"].append(model)
        except Exception:
            pass

    # Check AI model availability
    try:
        from transformers import pipeline
        models["ai"].append("mistralai/Mistral-7B-Instruct-v0.2")
    except Exception:
        pass

    return models

@app.get("/stats")
async def get_pipeline_stats():
    """Get pipeline usage statistics."""
    jobs = job_manager.list_jobs()

    total_jobs = len(jobs)
    completed_jobs = sum(1 for job in jobs if job['status'] == 'completed')
    failed_jobs = sum(1 for job in jobs if job['status'] == 'failed')
    running_jobs = sum(1 for job in jobs if job['status'] == 'running')

    return {
        "total_jobs": total_jobs,
        "completed_jobs": completed_jobs,
        "failed_jobs": failed_jobs,
        "running_jobs": running_jobs,
        "success_rate": (completed_jobs / total_jobs * 100) if total_jobs > 0 else 0,
        "active_jobs": job_manager.max_jobs - len([j for j in jobs if j['status'] in ['running', 'pending']])
    }

# Error handlers
@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    """Handle HTTP exceptions."""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": True,
            "message": exc.detail,
            "status_code": exc.status_code
        }
    )

@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    """Handle general exceptions."""
    logger.error(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=500,
        content={
            "error": True,
            "message": "Internal server error",
            "details": str(exc) if app.debug else None
        }
    )

# Run server
if __name__ == "__main__":
    uvicorn.run(
        "api:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )