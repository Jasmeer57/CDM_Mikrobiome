#!/usr/bin/env python3
"""
CLI entry point for the LLM-based CDM entity extraction pipeline.

Wires up core.pipeline.CDMEntityPipeline (the modular, unit-tested pipeline
in core/, mappers/, extractors/) into a runnable command, as documented in
README.md's Quick Start:

    python main.py --input "data/paper.txt" --model "phi3:mini"

This file previously didn't exist, despite being referenced by README.md,
Dockerfile (every stage's CMD/ENTRYPOINT), and pipelines/llm_terms/tests/test_comprehensive_llm.py's
test_main_script_import.
"""
import argparse
import logging
import os
import sys

from core.pipeline import CDMEntityPipeline
from config.cdm_config import PipelineConfig

logger = logging.getLogger(__name__)


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract CDM entities from a scientific paper using an LLM (via Ollama)."
    )
    parser.add_argument("--input", required=True, help="Path to the input text file.")
    parser.add_argument("--output", default=None,
                         help="Path to write the extraction results JSON. "
                              "Defaults to <input>.cdm_entities.json next to the input file.")
    parser.add_argument("--model", default=os.environ.get("DEFAULT_MODEL", "qwen3:8b"),
                         help="Ollama (or OpenAI-compatible) model name.")
    parser.add_argument("--base_url", default=os.environ.get("OLLAMA_BASE_URL"),
                         help="LLM API base URL. Defaults to http://localhost:11434 (Ollama).")
    parser.add_argument("--api_key", default=os.environ.get("LLM_API_KEY", "EMPTY"),
                         help="API key, for OpenAI-compatible / cloud endpoints. Not needed for Ollama.")
    parser.add_argument("--chunk_size", type=int, default=None,
                         help="Override the pipeline's automatic chunk sizing.")
    parser.add_argument("--semantic_model", default="all-MiniLM-L6-v2",
                         help="Embedding model for semantic deduplication.")
    parser.add_argument("--semantic_threshold", type=float, default=0.8,
                         help="Cosine similarity threshold for semantic deduplication.")
    parser.add_argument("--enable_omop_mapping", action="store_true",
                         help="Map extracted entities to OMOP concepts.")
    parser.add_argument("--enable_umls_mapping", action="store_true",
                         help="Map extracted entities to UMLS concepts (requires --umls_api_key).")
    parser.add_argument("--umls_api_key", default=os.environ.get("UMLS_API_KEY"),
                         help="UMLS API key, required if --enable_umls_mapping is set.")
    parser.add_argument("--enable_comprehensive_mapping", action="store_true",
                         help="Enable OMOP + UMLS + OLS + BioPortal mapping together.")
    parser.add_argument("--log_level", default="INFO",
                         choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=getattr(logging, args.log_level), format="%(levelname)s: %(message)s")

    input_path = args.input
    if not os.path.exists(input_path):
        logger.error(f"Input file not found: {input_path}")
        return 1

    with open(input_path, "r", encoding="utf-8") as f:
        text = f.read()

    output_path = args.output or f"{input_path}.cdm_entities.json"

    config = PipelineConfig(default_model=args.model)
    pipeline = CDMEntityPipeline(
        model=args.model,
        base_url=args.base_url,
        config=config,
        semantic_model=args.semantic_model,
        semantic_threshold=args.semantic_threshold,
        enable_omop_mapping=args.enable_omop_mapping,
        enable_umls_mapping=args.enable_umls_mapping,
        umls_api_key=args.umls_api_key,
        enable_comprehensive_mapping=args.enable_comprehensive_mapping,
        api_key=args.api_key,
    )

    ok = pipeline.run(text, output_path, chunk_size=args.chunk_size)

    if ok:
        logger.info(f"Done. Results written to {output_path}")
        return 0
    else:
        logger.error("Pipeline run failed - see log above for details.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
