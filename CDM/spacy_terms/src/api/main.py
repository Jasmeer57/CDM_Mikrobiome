"""
FastAPI application for Advanced Scientific Term Extraction Pipeline
Provides REST API endpoints for term extraction with background processing
"""

import asyncio
import logging
import uuid
from typing import List, Dict, Any, Optional
from pathlib import Path
from datetime import datetime
import tempfile
import shutil
import os

from fastapi import FastAPI, HTTPException, BackgroundTasks, UploadFile, File, Form, Query, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
import uvicorn

# Add src to path for imports
import sys
sys.path.append(str(Path(__file__).parent.parent.parent))

from src.config.settings import get_config, validate_config
from src.modules.terms_extractor import create_terms_extractor
from src.modules.deduplication import create_deduplicator
from src.modules.ai_correction import create_ai_corrector
from src.modules.umls_mapping import create_umls_mapper
from src.modules.omop_mapping import create_omop_mapper
from src.utils.output_writer import create_output_writer

logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="Advanced Scientific Term Extraction API",
    description="Multi-sciSpaCy model term extraction with AI correction and UMLS/OMOP mapping",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global pipeline components (lazy loading)
pipeline_components = None

class PipelineConfig(BaseModel):
    """Pipeline configuration model"""
    fuzzy_threshold: float = Field(0.85, ge=0.0, le=1.0, description="Fuzzy matching threshold")
    semantic_threshold: float = Field(0.9, ge=0.0, le=1.0, description="Semantic similarity threshold")
    semantic_model: str = Field("mini-lm", description="Semantic model for deduplication (mini-lm, nomic, mpnet)")
    enable_ai_correction: bool = Field(False, description="Enable AI term correction")
    enable_umls_mapping: bool = Field(False, description="Enable UMLS mapping")
    enable_omop_mapping: bool = Field(False, description="Enable OMOP mapping")
    enable_cdm_optimization: bool = Field(True, description="Enable CDM-specific optimization")
    output_formats: List[str] = Field(["json", "csv"], description="Output formats (json, csv, sqlite)")

class ExtractionRequest(BaseModel):
    """Extraction request model"""
    config: PipelineConfig = Field(default_factory=PipelineConfig)
    text: Optional[str] = Field(None, description="Text to process")
    file_url: Optional[str] = Field(None, description="URL of file to process")

class ExtractionResponse(BaseModel):
    """Extraction response model"""
    job_id: str
    status: str
    message: str
    created_at: datetime
    updated_at: datetime

class JobStatus(BaseModel):
    """Job status model"""
    job_id: str
    status: str
    progress: int
    message: str
    created_at: datetime
    updated_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None
    result_url: Optional[str] = None

# In-memory job storage (in production, use Redis/Database)
job_storage: Dict[str, Dict[str, Any]] = {}

async def get_pipeline_components():
    """Initialize pipeline components (lazy loading)"""
    global pipeline_components

    if pipeline_components is None:
        config = get_config()

        logger.info("Initializing pipeline components...")
        pipeline_components = {
            'terms_extractor': create_terms_extractor(config.scispacy),
            'deduplicator': create_deduplicator(config.deduplication),
            'ai_corrector': create_ai_corrector(config.ai_correction),
            'umls_mapper': create_umls_mapper(config.umls, config.bioportal),
            'omop_mapper': None,  # Will be initialized if needed
            'output_writer': create_output_writer('./temp_output')
        }

        logger.info("Pipeline components initialized")

    return pipeline_components

def update_job_status(job_id: str, status: str, message: str, progress: int = 0, error: str = None, result_url: str = None):
    """Update job status"""
    if job_id in job_storage:
        job = job_storage[job_id]
        job['status'] = status
        job['message'] = message
        job['progress'] = progress
        job['updated_at'] = datetime.now()

        if error:
            job['error'] = error

        if result_url:
            job['result_url'] = result_url

        if status == 'running' and job.get('started_at') is None:
            job['started_at'] = datetime.now()

        if status in ['completed', 'failed']:
            job['completed_at'] = datetime.now()

async def process_text_background(job_id: str, text: str, config: PipelineConfig):
    """Background task to process text"""
    try:
        # Update config
        pipeline_config = get_config()
        pipeline_config.deduplication.fuzzy_threshold = config.fuzzy_threshold
        pipeline_config.deduplication.semantic_threshold = config.semantic_threshold
        pipeline_config.deduplication.default_semantic_model = config.semantic_model
        pipeline_config.ai_correction.enabled = config.enable_ai_correction
        pipeline_config.umls.enabled = config.enable_umls_mapping
        # Enable CDM optimization from terms extractor
        if hasattr(pipeline_config.scispacy, 'cdm_optimization'):
            pipeline_config.scispacy.cdm_optimization = config.enable_cdm_optimization
        pipeline_config.omop.enabled = config.enable_omop_mapping
        pipeline_config.output_formats = config.output_formats

        # Get pipeline components
        components = await get_pipeline_components()

        update_job_status(job_id, 'running', 'Starting text processing...', 10)

        # Process text (simplified version of main.py logic)
        terms = components['terms_extractor'].extract_from_text(text)
        update_job_status(job_id, 'running', f'Extracted {len(terms)} terms', 30)

        # Deduplication
        dedup_result = components['deduplicator'].deduplicate_terms(terms)
        update_job_status(job_id, 'running', f'Deduplicated to {len(dedup_result.deduplicated_terms)} terms', 50)

        final_terms = dedup_result.deduplicated_terms

        # AI correction (if enabled)
        if config.enable_ai_correction:
            update_job_status(job_id, 'running', 'Applying AI correction...', 60)
            final_terms = components['ai_corrector'].correct_terms_batch(final_terms)
            update_job_status(job_id, 'running', f'AI correction complete', 70)

        # Create results
        results = {
            'metadata': {
                'timestamp': datetime.now().isoformat(),
                'job_id': job_id,
                'config': {
                    'fuzzy_threshold': config.fuzzy_threshold,
                    'semantic_threshold': config.semantic_threshold,
                    'semantic_model': config.semantic_model,
                    'ai_correction': config.enable_ai_correction,
                    'umls_mapping': config.enable_umls_mapping,
                    'omop_mapping': config.enable_omop_mapping
                }
            },
            'deduplicated_terms': final_terms,
            'statistics': {
                'extraction': {'filtered_entities': len(terms)},
                'deduplication': {
                    'original_count': len(terms),
                    'final_count': len(final_terms),
                    'exact_removed': dedup_result.exact_removed,
                    'fuzzy_removed': dedup_result.fuzzy_removed,
                    'semantic_removed': dedup_result.semantic_removed
                },
                'overall': {
                    'final_unique_terms': len(final_terms),
                    'total_reduction_percent': ((len(terms) - len(final_terms)) / len(terms) * 100) if terms else 0
                }
            }
        }

        # Save results
        update_job_status(job_id, 'running', 'Saving results...', 80)
        saved_files = components['output_writer'].save_results(results, config.output_formats)

        # Create temporary result file
        temp_dir = Path('./temp_output')
        temp_dir.mkdir(exist_ok=True)

        result_file = temp_dir / f"results_{job_id}.json"
        import json
        with open(result_file, 'w') as f:
            json.dump(results, f, indent=2)

        update_job_status(job_id, 'completed', f'Processing complete! {len(final_terms)} terms extracted', 100, result_url=str(result_file))

    except Exception as e:
        logger.error(f"Error processing job {job_id}: {e}")
        update_job_status(job_id, 'failed', f'Processing failed: {str(e)}', 0, error=str(e))

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": "Advanced Scientific Term Extraction API",
        "version": "2.0.0",
        "docs": "/docs",
        "redoc": "/redoc"
    }

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

@app.get("/config")
async def get_available_configurations():
    """Get available configuration options"""
    return {
        "semantic_models": {
            "mini-lm": "sentence-transformers/all-MiniLM-L12-v2 (default, fast)",
            "nomic": "nomic-ai/nomic-embed-text-v1.5 (upgraded, improved biomedical)",
            "mpnet": "sentence-transformers/all-mpnet-base-v2 (high accuracy)"
        },
        "cdm_domains": [
            "PERSON_SUBJECT",
            "CONDITION_DISEASE",
            "DRUG_SUBSTANCE",
            "PROCEDURE_INTERVENTION",
            "MEASUREMENT_OBSERVATION",
            "OBSERVATION"
        ],
        "output_formats": ["json", "csv", "sqlite"]
    }

@app.get("/cdm-stats")
async def get_cdm_statistics():
    """Get CDM-specific statistics"""
    # This would typically query the database for recent runs
    return {
        "total_extractions": 0,
        "cdm_ready_terms": 0,
        "cdm_domain_distribution": {},
        "latest_run": None
    }

@app.post("/extract", response_model=ExtractionResponse)
async def extract_terms(
    request: ExtractionRequest,
    background_tasks: BackgroundTasks
):
    """Start term extraction job"""
    if not request.text and not request.file_url:
        raise HTTPException(status_code=400, detail="Either text or file_url must be provided")

    # Create job
    job_id = str(uuid.uuid4())

    job = {
        'job_id': job_id,
        'status': 'queued',
        'message': 'Job queued for processing',
        'progress': 0,
        'created_at': datetime.now(),
        'updated_at': datetime.now(),
        'started_at': None,
        'completed_at': None,
        'error': None,
        'result_url': None
    }

    job_storage[job_id] = job

    # Start background processing
    if request.text:
        background_tasks.add_task(process_text_background, job_id, request.text, request.config)
    else:
        # TODO: Handle file URL download and processing
        raise HTTPException(status_code=501, detail="File URL processing not implemented yet")

    return ExtractionResponse(
        job_id=job_id,
        status="queued",
        message="Job queued for processing",
        created_at=job['created_at'],
        updated_at=job['updated_at']
    )

@app.get("/jobs/{job_id}/status", response_model=JobStatus)
async def get_job_status(job_id: str):
    """Get job status"""
    if job_id not in job_storage:
        raise HTTPException(status_code=404, detail="Job not found")

    job = job_storage[job_id]
    return JobStatus(**job)

@app.get("/jobs/{job_id}/result")
async def get_job_result(job_id: str):
    """Get job result file"""
    if job_id not in job_storage:
        raise HTTPException(status_code=404, detail="Job not found")

    job = job_storage[job_id]

    if job['status'] != 'completed':
        raise HTTPException(status_code=400, detail="Job not completed yet")

    if not job['result_url'] or not os.path.exists(job['result_url']):
        raise HTTPException(status_code=404, detail="Result file not found")

    return FileResponse(
        job['result_url'],
        media_type='application/json',
        filename=f"results_{job_id}.json"
    )

@app.get("/jobs")
async def list_jobs():
    """List all jobs"""
    return {"jobs": list(job_storage.values())}

@app.delete("/jobs/{job_id}")
async def delete_job(job_id: str):
    """Delete job and its results"""
    if job_id not in job_storage:
        raise HTTPException(status_code=404, detail="Job not found")

    job = job_storage[job_id]

    # Delete result file if exists
    if job.get('result_url') and os.path.exists(job['result_url']):
        os.remove(job['result_url'])

    # Delete job from storage
    del job_storage[job_id]

    return {"message": f"Job {job_id} deleted successfully"}

@app.get("/config")
async def get_default_config():
    """Get default configuration"""
    config = get_config()
    return {
        "fuzzy_threshold": config.deduplication.fuzzy_threshold,
        "semantic_threshold": config.deduplication.semantic_threshold,
        "semantic_model": config.deduplication.default_semantic_model,
        "available_semantic_models": list(config.deduplication.semantic_models.keys()),
        "scispacy_models": config.scispacy.models,
        "ai_correction_enabled": config.ai_correction.enabled,
        "umls_enabled": config.umls.enabled,
        "omop_enabled": config.omop.enabled
    }

if __name__ == "__main__":
    uvicorn.run(
        "src.api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )