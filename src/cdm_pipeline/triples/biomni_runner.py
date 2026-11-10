"""Batch runner for Biomni-powered triple validation (Phase 2).

Reads per-paper triple JSONs from Phase 1 (extractor.py output),
passes them through the Biomni A1 agent (Ollama backend) for
validation and enrichment, and writes validated triples.

Outputs (in cdm_output/triples/validated/):
  - Per-paper JSON: <paper_id>.validated.json
  - Aggregated CSV: all_validated_triples.csv
  - Checkpoint: checkpoint.json
  - Summary: validation_summary.json

Usage:
  python -m cdm_pipeline.triples.biomni_runner [--model qwen3.5:9b] [--limit N]
"""

import csv
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

from ..config import CDM_OUTPUT_DIR
from .biomni_validator import BiomniValidator, DEFAULT_MODEL

TRIPLES_DIR = CDM_OUTPUT_DIR / "triples"
VALIDATED_DIR = TRIPLES_DIR / "validated"
VALIDATED_DIR.mkdir(parents=True, exist_ok=True)

CHECKPOINT = VALIDATED_DIR / "checkpoint.json"
CSV_PATH = VALIDATED_DIR / "all_validated_triples.csv"
CSV_FIELDS = [
    "paper_id", "subject", "predicate", "object",
    "subject_type", "object_type", "confidence",
    "action", "correction_note", "original_subject", "original_object",
    "original_subject_type", "original_object_type",
    "validated_timestamp",
]


def load_phase1_triples() -> dict:
    """Load all Phase 1 triple JSONs. Returns {paper_id: [triple, ...]}."""
    papers = {}
    for json_path in sorted(TRIPLES_DIR.glob("*.triples.json")):
        pid = json_path.stem.replace(".triples", "")
        with open(json_path, encoding="utf-8") as f:
            data = json.load(f)
        triples = data.get("triples", [])
        if triples:
            papers[pid] = triples
    return papers


def rebuild_csv():
    """Rebuild the aggregated CSV from all validated JSONs."""
    rows = []
    for json_path in sorted(VALIDATED_DIR.glob("*.validated.json")):
        with open(json_path, encoding="utf-8") as f:
            data = json.load(f)
        pid = data.get("paper_id", json_path.stem.replace(".validated", ""))
        for t in data.get("validated_triples", []):
            rows.append({
                "paper_id": pid,
                "subject": t.get("subject", ""),
                "predicate": t.get("predicate", ""),
                "object": t.get("object", ""),
                "subject_type": t.get("subject_type", ""),
                "object_type": t.get("object_type", ""),
                "confidence": t.get("confidence", 0),
                "action": t.get("action", ""),
                "correction_note": t.get("correction_note", ""),
                "original_subject": t.get("original_subject", ""),
                "original_object": t.get("original_object", ""),
                "original_subject_type": t.get("original_subject_type", ""),
                "original_object_type": t.get("original_object_type", ""),
                "validated_timestamp": data.get("timestamp", ""),
            })
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    logger.info(f"CSV rebuilt: {len(rows)} rows -> {CSV_PATH}")
    return len(rows)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Biomni triple validation runner")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Ollama model name")
    parser.add_argument("--limit", type=int, default=None, help="Max papers to process")
    parser.add_argument("--datalake", action="store_true", help="Enable Biomni datalake (11GB download)")
    parser.add_argument("--data-path", default="/tmp/biomni_data", help="Biomni data directory")
    args = parser.parse_args()

    # Load Phase 1 triples
    all_triples = load_phase1_triples()
    logger.info(f"Loaded {len(all_triples)} papers with triples from Phase 1")

    total_triples = sum(len(t) for t in all_triples.values())
    logger.info(f"Total triples to validate: {total_triples}")

    if args.limit:
        items = list(all_triples.items())[:args.limit]
        all_triples = dict(items)
        logger.info(f"Limited to {len(all_triples)} papers")

    if not all_triples:
        logger.info("No triples to validate. Exiting.")
        return

    # Create validator
    validator = BiomniValidator(
        model=args.model,
        data_path=args.data_path,
        use_datalake=args.datalake,
    )

    # Run batch validation
    logger.info(f"Starting Biomni validation (model={args.model})")
    logger.info(f"Output dir: {VALIDATED_DIR}")

    summary = validator.validate_batch(
        papers_triples=all_triples,
        output_dir=VALIDATED_DIR,
        checkpoint_path=CHECKPOINT,
    )

    # Rebuild CSV
    n_rows = rebuild_csv()

    logger.info(f"\n{'=' * 60}")
    logger.info("BIOMNI VALIDATION COMPLETE")
    logger.info(f"{'=' * 60}")
    logger.info(f"Papers:    {summary['successful']}/{summary['total_papers']}")
    logger.info(f"Kept:      {summary['total_kept']}")
    logger.info(f"Corrected: {summary['total_corrected']}")
    logger.info(f"Rejected:  {summary['total_rejected']}")
    logger.info(f"CSV rows:  {n_rows}")
    logger.info(f"Elapsed:   {summary['elapsed_min']} min")


if __name__ == "__main__":
    main()
