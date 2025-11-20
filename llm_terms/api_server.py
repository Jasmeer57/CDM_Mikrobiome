#!/usr/bin/env python3
"""
CDM Entity Extraction FastAPI Server
RESTful API for biomedical entity extraction and CDM mapping
"""

import asyncio
import logging
import os
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Union

import uvicorn
from fastapi import FastAPI, HTTPException, UploadFile, File, BackgroundTasks, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
import yaml

# Import CDM Pipeline components
from core.pipeline import CDMEntityPipeline
from config.cdm_config import PipelineConfig, CDMEntityConfig

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="CDM Entity Extraction API",
    description="RESTful API for extracting structured biomedical entities from text using AI",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global pipeline instance
pipeline: Optional[CDMEntityPipeline] = None

# Task storage for background processing
running_tasks: Dict[str, Dict] = {}

# Pydantic models
class ExtractionRequest(BaseModel):
    """Request model for text extraction"""
    text: str = Field(..., description="Text to extract entities from", min_length=50, max_length=1000000)
    model: str = Field(default="phi3:mini", description="LLM model to use")
    base_url: str = Field(default="http://localhost:11434", description="LLM service URL")
    chunk_size: Optional[int] = Field(default=None, description="Chunk size in characters")
    max_entities: int = Field(default=200, description="Maximum entities to extract", ge=1, le=1000)
    min_confidence: float = Field(default=0.6, description="Minimum confidence threshold", ge=0.0, le=1.0)
    semantic_threshold: float = Field(default=0.8, description="Semantic similarity threshold", ge=0.0, le=1.0)
    enable_biomistral: bool = Field(default=False, description="Enable BioMistral validation")
    enable_omop_mapping: bool = Field(default=False, description="Enable OMOP CDM mapping")
    enable_umls_mapping: bool = Field(default=False, description="Enable UMLS mapping")
    enable_comprehensive_mapping: bool = Field(default=False, description="Enable comprehensive mapping")
    max_workers: int = Field(default=3, description="Maximum parallel workers", ge=1, le=10)

class ExtractionResponse(BaseModel):
    """Response model for extraction results"""
    task_id: str
    status: str
    message: str
    entities: Optional[List[Dict]] = None
    metadata: Optional[Dict] = None
    statistics: Optional[Dict] = None

class TaskStatus(BaseModel):
    """Task status model"""
    task_id: str
    status: str
    message: str
    progress: Optional[float] = None
    result: Optional[Dict] = None
    error: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None

class HealthResponse(BaseModel):
    """Health check response"""
    status: str
    message: str
    pipeline_ready: bool
    available_models: List[str]
    version: str

class ConfigResponse(BaseModel):
    """Configuration response"""
    entity_types: Dict
    default_config: Dict
    supported_features: List[str]

@app.on_event("startup")
async def startup_event():
    """Initialize the pipeline on startup"""
    global pipeline
    try:
        # Initialize with default configuration
        config = PipelineConfig()
        pipeline = CDMEntityPipeline(config=config)

        # Validate prerequisites
        if pipeline.validate_prerequisites():
            logger.info("✅ CDM Pipeline API server started successfully")
        else:
            logger.warning("⚠️ Pipeline started but LLM service not available")

    except Exception as e:
        logger.error(f"❌ Failed to initialize pipeline: {e}")
        pipeline = None

@app.get("/", response_model=Dict)
async def root():
    """Root endpoint"""
    return {
        "message": "CDM Entity Extraction API",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health",
        "status": "Ready" if pipeline else "Not Ready"
    }

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint"""
    if not pipeline:
        return HealthResponse(
            status="unhealthy",
            message="Pipeline not initialized",
            pipeline_ready=False,
            available_models=[],
            version="1.0.0"
        )

    try:
        # Check if LLM service is available
        llm_available = pipeline.validate_prerequisites()
        models = pipeline.llm_client.get_available_models() if llm_available else []

        return HealthResponse(
            status="healthy" if llm_available else "degraded",
            message="LLM service available" if llm_available else "LLM service unavailable",
            pipeline_ready=llm_available,
            available_models=models,
            version="1.0.0"
        )
    except Exception as e:
        return HealthResponse(
            status="unhealthy",
            message=f"Health check failed: {str(e)}",
            pipeline_ready=False,
            available_models=[],
            version="1.0.0"
        )

@app.get("/config", response_model=ConfigResponse)
async def get_config():
    """Get pipeline configuration"""
    try:
        entity_config = CDMEntityConfig()
        pipeline_config = PipelineConfig()

        return ConfigResponse(
            entity_types=entity_config.ENTITY_TYPES,
            default_config={
                "model": pipeline_config.default_model,
                "base_url": pipeline_config.default_base_url,
                "max_workers": pipeline_config.max_workers,
                "max_entities": pipeline_config.max_entities,
                "min_confidence": pipeline_config.min_confidence,
            },
            supported_features=[
                "semantic_deduplication",
                "biomistral_validation",
                "omop_mapping",
                "umls_mapping",
                "comprehensive_mapping",
                "parallel_processing",
                "adaptive_chunking"
            ]
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get config: {str(e)}")

@app.post("/extract", response_model=ExtractionResponse)
async def extract_entities(request: ExtractionRequest):
    """Extract entities from text"""
    if not pipeline:
        raise HTTPException(status_code=503, detail="Pipeline not initialized")

    try:
        # Validate text length
        if len(request.text) < 50:
            raise HTTPException(status_code=400, detail="Text too short (minimum 50 characters)")

        if len(request.text) > 1000000:
            raise HTTPException(status_code=400, detail="Text too long (maximum 1,000,000 characters)")

        # Configure pipeline
        config = PipelineConfig(
            default_model=request.model,
            default_base_url=request.base_url,
            max_workers=request.max_workers,
            max_entities=request.max_entities,
            min_confidence=request.min_confidence
        )

        # Initialize pipeline with request configuration
        extract_pipeline = CDMEntityPipeline(
            model=request.model,
            base_url=request.base_url,
            config=config,
            enable_biomistral=request.enable_biomistral,
            enable_omop_mapping=request.enable_omop_mapping,
            enable_umls_mapping=request.enable_umls_mapping,
            enable_comprehensive_mapping=request.enable_comprehensive_mapping,
            semantic_threshold=request.semantic_threshold
        )

        # Validate prerequisites
        if not extract_pipeline.validate_prerequisites():
            raise HTTPException(status_code=503, detail="LLM service not available")

        # Extract entities
        logger.info(f"🚀 Starting entity extraction for {len(request.text)} characters")
        start_time = datetime.now()

        entities = extract_pipeline.extract_entities(
            text=request.text,
            chunk_size=request.chunk_size
        )

        processing_time = (datetime.now() - start_time).total_seconds()

        # Generate statistics
        statistics = extract_pipeline.generate_statistics(entities)

        logger.info(f"✅ Extraction completed: {len(entities)} entities in {processing_time:.2f}s")

        return ExtractionResponse(
            task_id=str(uuid.uuid4()),
            status="completed",
            message=f"Successfully extracted {len(entities)} entities",
            entities=entities,
            metadata={
                "processing_time": processing_time,
                "text_length": len(request.text),
                "model_used": request.model,
                "features_enabled": {
                    "biomistral": request.enable_biomistral,
                    "omop_mapping": request.enable_omop_mapping,
                    "umls_mapping": request.enable_umls_mapping,
                    "comprehensive_mapping": request.enable_comprehensive_mapping,
                    "semantic_deduplication": True
                }
            },
            statistics=statistics
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Extraction failed: {e}")
        raise HTTPException(status_code=500, detail=f"Extraction failed: {str(e)}")

@app.post("/extract/async")
async def extract_entities_async(
    background_tasks: BackgroundTasks,
    request: ExtractionRequest
):
    """Extract entities asynchronously"""
    if not pipeline:
        raise HTTPException(status_code=503, detail="Pipeline not initialized")

    task_id = str(uuid.uuid4())

    # Store task information
    running_tasks[task_id] = {
        "status": "pending",
        "message": "Task queued",
        "progress": 0.0,
        "result": None,
        "error": None,
        "created_at": datetime.now(),
        "completed_at": None
    }

    # Add background task
    background_tasks.add_task(
        process_extraction_task,
        task_id,
        request.dict()
    )

    return ExtractionResponse(
        task_id=task_id,
        status="pending",
        message="Task started. Check status with /task/{task_id}",
        entities=None,
        metadata=None,
        statistics=None
    )

@app.get("/task/{task_id}", response_model=TaskStatus)
async def get_task_status(task_id: str):
    """Get task status"""
    if task_id not in running_tasks:
        raise HTTPException(status_code=404, detail="Task not found")

    task = running_tasks[task_id]
    return TaskStatus(
        task_id=task_id,
        status=task["status"],
        message=task["message"],
        progress=task.get("progress"),
        result=task.get("result"),
        error=task.get("error"),
        created_at=task["created_at"],
        completed_at=task.get("completed_at")
    )

@app.delete("/task/{task_id}")
async def delete_task(task_id: str):
    """Delete completed task"""
    if task_id not in running_tasks:
        raise HTTPException(status_code=404, detail="Task not found")

    task = running_tasks[task_id]
    if task["status"] == "running":
        raise HTTPException(status_code=400, detail="Cannot delete running task")

    del running_tasks[task_id]
    return {"message": "Task deleted successfully"}

@app.get("/tasks")
async def list_tasks():
    """List all tasks"""
    tasks = []
    for task_id, task in running_tasks.items():
        tasks.append({
            "task_id": task_id,
            "status": task["status"],
            "message": task["message"],
            "created_at": task["created_at"],
            "completed_at": task.get("completed_at")
        })

    # Sort by creation time (newest first)
    tasks.sort(key=lambda x: x["created_at"], reverse=True)

    return {"tasks": tasks, "total": len(tasks)}

@app.post("/upload")
async def upload_and_extract(
    file: UploadFile = File(...),
    model: str = Query(default="phi3:mini"),
    enable_biomistral: bool = Query(default=False),
    enable_comprehensive_mapping: bool = Query(default=False)
):
    """Upload file and extract entities"""
    if not pipeline:
        raise HTTPException(status_code=503, detail="Pipeline not initialized")

    # Validate file type
    if not file.filename or not file.filename.endswith(('.txt', '.md')):
        raise HTTPException(
            status_code=400,
            detail="Only .txt and .md files are supported"
        )

    try:
        # Read file content
        content = await file.read()
        text = content.decode('utf-8')

        # Validate content
        if len(text) < 50:
            raise HTTPException(status_code=400, detail="File content too short")

        if len(text) > 1000000:
            raise HTTPException(status_code=400, detail="File content too long")

        # Create extraction request
        request = ExtractionRequest(
            text=text,
            model=model,
            enable_biomistral=enable_biomistral,
            enable_comprehensive_mapping=enable_comprehensive_mapping
        )

        # Process extraction
        return await extract_entities(request)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"File processing failed: {e}")
        raise HTTPException(status_code=500, detail=f"File processing failed: {str(e)}")

@app.get("/models")
async def list_models():
    """List available LLM models"""
    if not pipeline:
        raise HTTPException(status_code=503, detail="Pipeline not initialized")

    try:
        models = pipeline.llm_client.get_available_models()
        return {
            "available_models": models,
            "default_model": pipeline.config.default_model,
            "total_models": len(models)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list models: {str(e)}")

async def process_extraction_task(task_id: str, request_data: Dict):
    """Process extraction task in background"""
    try:
        # Update task status
        running_tasks[task_id]["status"] = "running"
        running_tasks[task_id]["message"] = "Processing extraction"
        running_tasks[task_id]["progress"] = 0.1

        # Create extraction request
        request = ExtractionRequest(**request_data)

        # Configure pipeline
        config = PipelineConfig(
            default_model=request.model,
            default_base_url=request.base_url,
            max_workers=request.max_workers,
            max_entities=request.max_entities,
            min_confidence=request.min_confidence
        )

        extract_pipeline = CDMEntityPipeline(
            model=request.model,
            base_url=request.base_url,
            config=config,
            enable_biomistral=request.enable_biomistral,
            enable_omop_mapping=request.enable_omop_mapping,
            enable_umls_mapping=request.enable_umls_mapping,
            enable_comprehensive_mapping=request.enable_comprehensive_mapping,
            semantic_threshold=request.semantic_threshold
        )

        running_tasks[task_id]["progress"] = 0.3
        running_tasks[task_id]["message"] = "Validating prerequisites"

        if not extract_pipeline.validate_prerequisites():
            raise Exception("LLM service not available")

        running_tasks[task_id]["progress"] = 0.5
        running_tasks[task_id]["message"] = "Extracting entities"

        # Extract entities
        start_time = datetime.now()
        entities = extract_pipeline.extract_entities(
            text=request.text,
            chunk_size=request.chunk_size
        )

        processing_time = (datetime.now() - start_time).total_seconds()
        statistics = extract_pipeline.generate_statistics(entities)

        running_tasks[task_id]["progress"] = 0.9
        running_tasks[task_id]["message"] = "Finalizing results"

        # Update task with results
        running_tasks[task_id].update({
            "status": "completed",
            "message": f"Successfully extracted {len(entities)} entities",
            "progress": 1.0,
            "result": {
                "entities": entities,
                "metadata": {
                    "processing_time": processing_time,
                    "text_length": len(request.text),
                    "model_used": request.model,
                    "features_enabled": {
                        "biomistral": request.enable_biomistral,
                        "omop_mapping": request.enable_omop_mapping,
                        "umls_mapping": request.enable_umls_mapping,
                        "comprehensive_mapping": request.enable_comprehensive_mapping,
                        "semantic_deduplication": True
                    }
                },
                "statistics": statistics
            },
            "completed_at": datetime.now()
        })

        logger.info(f"✅ Async extraction completed: task {task_id}")

    except Exception as e:
        logger.error(f"❌ Async extraction failed: task {task_id}, error: {e}")
        running_tasks[task_id].update({
            "status": "failed",
            "message": f"Extraction failed: {str(e)}",
            "error": str(e),
            "completed_at": datetime.now()
        })

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="CDM Entity Extraction API Server")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind to")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload")
    parser.add_argument("--workers", type=int, default=1, help="Number of worker processes")

    args = parser.parse_args()

    uvicorn.run(
        "api_server:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        workers=args.workers
    )