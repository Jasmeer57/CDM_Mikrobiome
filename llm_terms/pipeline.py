#!/usr/bin/env python3
"""
Unified CDM Entity Extraction Pipeline
======================================
Orchestrates the entire extraction process, replacing the legacy shell script.
Runs basic extraction followed by enhanced extraction if resources allow.
"""

import os
import sys
import json
import time
import logging
import argparse
import subprocess
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

# Add current directory to path
sys.path.insert(0, str(Path(__file__).parent))

from core.pipeline import CDMEntityPipeline
from config.cdm_config import PipelineConfig

# Create logs directory if it doesn't exist
Path('logs').mkdir(exist_ok=True)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/pipeline.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("PipelineOrchestrator")

def setup_environment():
    """Load environment variables and setup directories."""
    load_dotenv()
    
    # Create necessary directories
    for directory in ['output', 'logs', 'checkpoints', 'data']:
        Path(directory).mkdir(exist_ok=True)
        
    # Check API keys
    api_keys = {
        'UMLS_API_KEY': os.getenv('UMLS_API_KEY'),
        'BIOPORTAL_API_KEY': os.getenv('BIOPORTAL_API_KEY'),
        'HUGGINGFACE_TOKEN': os.getenv('HUGGINGFACE_TOKEN')
    }
    
    missing_keys = [k for k, v in api_keys.items() if not v or v.startswith('your_')]
    
    if missing_keys:
        logger.warning(f"⚠️  Missing API keys: {', '.join(missing_keys)}")
        logger.warning("   Pipeline will run with limited functionality.")
    else:
        logger.info("✅ All API keys configured.")
        
    return api_keys

def run_pipeline_stage(stage_name, input_file, output_file, config, **kwargs):
    """Run a single stage of the pipeline."""
    logger.info(f"\n=== RUNNING {stage_name.upper()} PIPELINE ===")
    
    try:
        # Initialize pipeline
        pipeline = CDMEntityPipeline(
            model=config.default_model,
            base_url=config.default_base_url,
            config=config,
            **kwargs
        )
        
        # Read input
        with open(input_file, 'r', encoding='utf-8') as f:
            text = f.read()
            
        # Run pipeline
        success = pipeline.run(
            text=text,
            output_path=output_file,
            chunk_size=kwargs.get('chunk_size')
        )
        
        return success
        
    except Exception as e:
        logger.error(f"❌ {stage_name} pipeline failed: {e}")
        return False

def analyze_results(basic_output, enhanced_output):
    """Analyze and compare results from both stages."""
    report = {
        'pipeline_run': datetime.now().isoformat(),
        'basic_pipeline': _analyze_file(basic_output),
        'enhanced_pipeline': _analyze_file(enhanced_output)
    }
    
    summary_path = Path("output/pipeline_summary.json")
    with open(summary_path, 'w') as f:
        json.dump(report, f, indent=2)
        
    logger.info(f"📊 Summary report saved to: {summary_path}")
    return report

def _analyze_file(filepath):
    """Helper to analyze a single results file."""
    path = Path(filepath)
    if not path.exists():
        return None
        
    try:
        with open(path, 'r') as f:
            data = json.load(f)
            
        entities = data.get('results', {}).get('cdm_entities', {})
        total_entities = sum(len(v) for v in entities.values())
        
        # Flatten entities list for analysis
        all_entities = []
        for type_list in entities.values():
            all_entities.extend(type_list)
            
        return {
            'total_entities': total_entities,
            'entity_types': {k: len(v) for k, v in entities.items()},
            'has_mappings': any('omop_mappings' in e or 'umls_mappings' in e for e in all_entities)
        }
    except Exception as e:
        logger.error(f"Error analyzing {filepath}: {e}")
        return None

def main():
    parser = argparse.ArgumentParser(description="CDM Entity Extraction Pipeline")
    parser.add_argument('--input-file', '-i', required=True, help='Input text file')
    parser.add_argument('--output', '-o', default='output/cdm_entities.json', help='Base output file path')
    parser.add_argument('--model', '-m', default='qwen3:8b', help='LLM model to use')
    parser.add_argument('--base-url', default='http://localhost:11434', help='LLM service URL')
    parser.add_argument('--max-workers', type=int, default=3, help='Parallel workers')
    
    args = parser.parse_args()
    
    # Setup
    api_keys = setup_environment()
    input_path = Path(args.input_file)
    
    if not input_path.exists():
        logger.error(f"Input file not found: {input_path}")
        return 1
        
    # Common config
    pipeline_config = PipelineConfig(
        default_model=args.model,
        default_base_url=args.base_url,
        max_workers=args.max_workers
    )
    
    # Determine output paths
    base_output = Path(args.output)
    basic_output = str(base_output)
    
    # Create enhanced output filename (insert _enhanced before extension)
    stem = base_output.stem
    suffix = base_output.suffix
    parent = base_output.parent
    enhanced_output = str(parent / f"{stem}_enhanced{suffix}")
    basic_success = run_pipeline_stage(
        "Basic",
        args.input_file,
        basic_output,
        pipeline_config,
        semantic_model="all-MiniLM-L6-v2",
        semantic_threshold=0.8
    )
    
    if not basic_success:
        logger.error("Basic pipeline failed. Aborting.")
        return 1
        
    # --- STAGE 2: ENHANCED PIPELINE ---
    enhanced_output = "output/cdm_entities_enhanced.json"
    
    # Determine enabled features based on API keys
    enable_umls = bool(api_keys['UMLS_API_KEY'] and not api_keys['UMLS_API_KEY'].startswith('your_'))
    enable_bioportal = bool(api_keys['BIOPORTAL_API_KEY'] and not api_keys['BIOPORTAL_API_KEY'].startswith('your_'))
    enable_hf = bool(api_keys['HUGGINGFACE_TOKEN'] and not api_keys['HUGGINGFACE_TOKEN'].startswith('your_'))
    
    enhanced_success = run_pipeline_stage(
        "Enhanced",
        args.input_file,
        enhanced_output,
        pipeline_config,
        semantic_model="all-MiniLM-L6-v2",
        semantic_threshold=0.8,
        enable_biomistral=True,
        enable_omop_mapping=True,
        enable_umls_mapping=enable_umls,
        umls_api_key=api_keys['UMLS_API_KEY'],
        enable_comprehensive_mapping=enable_hf,
        mapping_confidence_threshold=0.7
    )
    
    # --- ANALYSIS ---
    analyze_results(basic_output, enhanced_output)
    
    if enhanced_success:
        logger.info("✅ Pipeline completed successfully!")
        return 0
    else:
        logger.warning("⚠️  Enhanced pipeline failed, but basic pipeline succeeded.")
        return 0

if __name__ == "__main__":
    sys.exit(main())
