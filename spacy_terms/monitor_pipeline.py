#!/usr/bin/env python3
"""
Real-time Pipeline Progress Monitor
================================
Watches the consolidated_all_models_results.json file and shows live updates as the pipeline processes each file.
Provides real-time statistics and term updates.

Usage:
    python monitor_pipeline.py --input_dir path/to/input --output_dir path/to/output
"""

import json
import time
import argparse
import logging
from datetime import datetime
from pathlib import Path

def setup_logging(level=logging.INFO):
    """Setup logging with specified level"""
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        force=True
    )
    return logging.getLogger(__name__)

def tail_file(file_path: str, lines=10):
    """Tail last N lines from a file"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()[-lines:]
            return lines[-lines:]
    except Exception as e:
        print(f"Error reading file: {e}")
        return []

def monitor_pipeline(input_dir: str, output_dir: str, update_interval: int = 5):
    """Monitor pipeline progress and output updates"""
    logger = setup_logging()
    logger.info(f"Starting pipeline monitor...")

    input_path = Path(input_dir)
    output_path = Path(output_dir)
    consolidated_file = output_path / "consolidated_all_models_results.json"

    if not input_path.exists():
        logger.error(f"Input directory does not exist: {input_path}")
        return False

    if not output_path.exists():
        output_path.mkdir(parents=True, exist_ok=True)
        logger.info(f"Created output directory: {output_path}")

    last_lines = []
    last_stats = {
        "files_processed": 0,
        "all_terms": 0,
        "model_contributions": {},
        "statistics": {
            "total_terms_extracted": 0,
            "total_terms_final": 0,
            "model_contributions": {},
            "label_distribution": {},
            "score_distribution": {"high": 0, "medium": 0, "load": 0},
            "domain_distribution": {"biomedical": 0, "general": 0}
        },
        "timestamp": datetime.now().isoformat(),
        "average_score": 0.0
        }
    }
    }

    logger.info(f"Monitoring pipeline output: {consolidated_file}")
    logger.info("Press Ctrl+C to stop monitoring")

    try:
        while True:
            # Load current state
            if consolidated_file.exists():
                with open(consolidated_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    all_terms = data.get("all_terms", [])
                    stats = data.get("metadata", {}).get("statistics", {})

                    # Calculate changes since last check
                    if stats["total_terms_extracted"] != last_stats["total_terms_extracted"]:
                        new_terms = len(all_terms) - last_stats["total_terms_extracted"]
                        new_unique = len(all_terms) - last_stats["total_terms_final"]

                        logger.info(f"\n🔄 PIPELINE UPDATE")
                        logger.info(f"   Files processed: {stats['total_files_processed']}")
                        logger.info(f"   Total terms extracted: {stats['total_terms_extracted']}")
                        logger.info(f"   Total terms after deduplication: {new_unique}")
                        logger.info(f"   Change since last check: +{new_terms - last_stats['total_terms_extracted']} terms")
                        logger.info(f"   Current unique terms: {len(all_terms)}")
                        logger.info(f"   Domain distribution: {stats['domain_distribution']['biomedical']} biomedical, {stats['domain_distribution']['general']} general")

                        if args.update_interval > 0:
                            time.sleep(update_interval)
                            continue
                    else:
                        break
            except Exception as e:
                logger.error(f"Error monitoring pipeline: {e}")
                break

    return True

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Real-time pipeline progress monitor")
    parser.add_argument("--input_dir", required=True, help="Directory containing research papers")
    parser.add_argument("--output_dir", required=True, help="Directory for output files")
    parser.add_argument("--update_interval", type=int, default=5, help="Update interval in seconds (default: 5)")

    args = parser.parse_args()
    monitor_pipeline(args.input_dir, args.output_dir, args.update_interval)