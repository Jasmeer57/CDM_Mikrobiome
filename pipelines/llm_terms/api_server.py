#!/usr/bin/env python3
"""
FastAPI REST wrapper for the LLM-based CDM entity extraction pipeline.

Implements the /extract/llm and /health endpoints documented in the
repo root README.md's "Using the REST API" section, and matches the
Dockerfile's CMD/ENTRYPOINT (every stage references this file) and
.env.example's API_HOST/API_PORT/API_WORKERS settings.

This file previously didn't exist, despite being the Dockerfile's default
command in every build stage and pipelines/llm_terms/tests/test_comprehensive_llm.py's
test_api_server_import target.
"""
import argparse
import logging
import os
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from core.pipeline import CDMEntityPipeline
from config.cdm_config import PipelineConfig

logger = logging.getLogger(__name__)

app = FastAPI(
    title="CDM LLM Entity Extraction API",
    description="Extracts microbiome CDM entities from text using an LLM (via Ollama).",
    version="1.0.0",
)


class ExtractRequest(BaseModel):
    text: str
    model: str = os.environ.get("DEFAULT_MODEL", "qwen3:8b")
    chunk_size: Optional[int] = None
    base_url: Optional[str] = None
    enable_omop_mapping: bool = False
    enable_umls_mapping: bool = False


class ExtractResponse(BaseModel):
    success: bool
    entity_count: int
    entities: list


@app.get("/health")
def health():
    """Health check endpoint, polled by the Dockerfile HEALTHCHECK and
    docker-compose's cdm-api service healthcheck."""
    return {"status": "ok"}


@app.post("/extract/llm", response_model=ExtractResponse)
def extract(request: ExtractRequest):
    """Extract CDM entities from the given text."""
    if not request.text or not request.text.strip():
        raise HTTPException(status_code=400, detail="'text' must not be empty")

    config = PipelineConfig(default_model=request.model)
    pipeline = CDMEntityPipeline(
        model=request.model,
        base_url=request.base_url or os.environ.get("OLLAMA_BASE_URL"),
        config=config,
        enable_omop_mapping=request.enable_omop_mapping,
        enable_umls_mapping=request.enable_umls_mapping,
    )

    if not pipeline.validate_prerequisites():
        raise HTTPException(
            status_code=503,
            detail=f"LLM backend unavailable or model '{request.model}' not found."
        )

    entities = pipeline.extract_entities(request.text, request.chunk_size)

    return ExtractResponse(
        success=True,
        entity_count=len(entities),
        entities=entities,
    )


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the CDM LLM extraction API server.")
    parser.add_argument("--host", default=os.environ.get("API_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("API_PORT", 8000)))
    parser.add_argument("--workers", type=int, default=int(os.environ.get("API_WORKERS", 1)))
    parser.add_argument("--reload", action="store_true")
    return parser.parse_args(argv)


if __name__ == "__main__":
    import uvicorn

    args = parse_args()
    uvicorn.run(
        "api_server:app",
        host=args.host,
        port=args.port,
        workers=args.workers if not args.reload else 1,
        reload=args.reload,
    )
