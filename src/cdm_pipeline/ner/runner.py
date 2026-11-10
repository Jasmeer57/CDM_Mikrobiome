"""Multi-NER runner CLI — orchestrates NER models from the registry.

Usage:
    # Run all models (default ensemble)
    python -m cdm_pipeline.ner.runner --models all --max_files 500

    # Run specific models
    python -m cdm_pipeline.ner.runner --models gliner pubmedbert

    # Run GLiNER-BioMed instead of base GLiNER
    python -m cdm_pipeline.ner.runner --models gliner_biomed pubmedbert scispacy_bc5cdr

    # Incremental mode (skip papers already in output CSVs)
    python -m cdm_pipeline.ner.runner --models all --incremental

    # Custom entity types (domain-agnostic)
    python -m cdm_pipeline.ner.runner --models gliner --entity_types DISEASE CHEMICAL PROTEIN

Domain-agnostic: pass ``--entity_types`` to override the default CDM_TYPES for
GLiNER-based models. Token-classification models (PubMedBERT, spaCy) have
fixed label sets determined by their training data.
"""
import sys
import io
import os
import csv
import json
import gc
import warnings

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

warnings.filterwarnings("ignore")
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
os.environ["TRANSFORMERS_VERBOSITY"] = "error"

import argparse
from collections import Counter
from pathlib import Path

from ..config import PAPERS_DIR, NER_OUTPUT_DIR, CDM_TYPES
from .registry import MODEL_REGISTRY, DEFAULT_MODELS, SCISPACY_ALL, get_model


def save_csv_dict(rows, output_path):
    """Save list-of-dicts to CSV, preserving column order."""
    if not rows:
        print("No rows to save for", output_path)
        return
    fields = ["term", "labels", "model", "paper", "char_start", "char_end"]
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print("Saved %d rows to %s" % (len(rows), output_path))


def save_summary_rows(all_rows, elapsed_times, output_dir):
    """Save summary JSON from list-of-dicts (merged combined CSV rows)."""
    summary = {
        "total_papers": len(set(r["paper"] for r in all_rows)),
        "total_entities": len(all_rows),
        "models": {},
    }
    for model_name in set(r["model"] for r in all_rows):
        model_rows = [r for r in all_rows if r["model"] == model_name]
        labels = Counter(r["labels"] for r in model_rows)
        unique = set(r["term"].lower() for r in model_rows)
        summary["models"][model_name] = {
            "total_entities": len(model_rows),
            "unique_entities": len(unique),
            "types_covered": len(labels),
            "types": dict(labels.most_common()),
            "elapsed_seconds": elapsed_times.get(model_name, 0),
        }

    summary_path = output_dir / "_multi_ner_summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print("\nSummary saved to", summary_path)
    print(json.dumps(summary, indent=2))


def main():
    available = sorted(MODEL_REGISTRY.keys()) + ["all", "scispacy_all"]
    parser = argparse.ArgumentParser(description="Run multi-NER on corpus")
    parser.add_argument("--models", nargs="+", default=["all"],
                        choices=available,
                        help="Which NER models to run")
    parser.add_argument("--max_files", type=int, default=500, help="Max papers to process")
    parser.add_argument("--incremental", action="store_true",
                        help="Skip papers already in the output CSV (append mode)")
    parser.add_argument("--threshold", type=float, default=0.5, help="GLiNER threshold")
    parser.add_argument("--entity_types", nargs="+", default=None,
                        help="Override entity types (for GLiNER-based models)")
    parser.add_argument("--api_key", default=os.environ.get("ENTREZ_API_KEY", ""),
                        help="NCBI Entrez API key for PubTator")
    parser.add_argument("--output_dir", default=None,
                        help="Output directory for NER CSVs (default: %s). "
                             "Use a versioned dir like outputs/results/<job_id>/ for isolation."
                             % NER_OUTPUT_DIR)
    args = parser.parse_args()

    # Resolve output directory
    output_dir = Path(args.output_dir) if args.output_dir else NER_OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    print("Output directory: %s" % output_dir)

    # Expand shortcuts
    models = list(args.models)
    if "all" in models:
        models = list(DEFAULT_MODELS)
    elif "scispacy_all" in models:
        models = [m for m in models if m != "scispacy_all"] + SCISPACY_ALL

    # Get paper list
    all_papers = sorted([f.name for f in PAPERS_DIR.glob("*.txt")])[:args.max_files]
    print("Found %d papers in %s" % (len(all_papers), PAPERS_DIR))

    # Incremental: skip papers already done across ALL selected models
    if args.incremental:
        done = set()
        for model_key in models:
            entry = MODEL_REGISTRY[model_key]
            csv_name = entry["kwargs"].get("output_file", "")
            if not csv_name:
                continue
            csv_path = output_dir / csv_name
            if csv_path.exists():
                with open(csv_path, encoding="utf-8", errors="replace") as f:
                    content = f.read().replace("\x00", "")
                    done.update(r["paper"] for r in csv.DictReader(io.StringIO(content)))
        papers = [p for p in all_papers if p not in done]
        print("Incremental: %d already done, %d remaining" % (len(done), len(papers)))
    else:
        papers = all_papers

    if not papers:
        print("Nothing to do — all papers already processed.")
        return

    print("Running models:", models, "on %d papers" % len(papers))

    # Entity type override for GLiNER-based models
    entity_types = args.entity_types or CDM_TYPES

    all_results = []
    elapsed_times = {}

    for model_key in models:
        print("\n" + "=" * 60)
        print("Running: %s" % model_key)
        print("=" * 60)

        override = {"threshold": args.threshold}
        # Apply entity_types override only to GLiNER models
        if model_key.startswith("gliner"):
            override["entity_types"] = entity_types
        if model_key == "pubtator":
            override["api_key"] = args.api_key

        model = get_model(model_key, **override)
        # Pass output_path so each model writes to the isolated output_dir
        model_output_path = output_dir / model.output_file
        results, elapsed = model.run(papers, incremental=args.incremental,
                                     output_path=model_output_path)
        all_results.extend(results)
        elapsed_times[model.name] = elapsed
        del model
        gc.collect()

    # Combined CSV (all models, all papers)
    print("\n" + "=" * 60)
    print("Building combined CSV")
    print("=" * 60)
    combined = []
    for model_key in models:
        entry = MODEL_REGISTRY[model_key]
        csv_name = entry["kwargs"].get("output_file", "")
        csv_path = output_dir / csv_name
        if csv_path.exists():
            with open(csv_path, encoding="utf-8", errors="replace") as f:
                content = f.read().replace("\x00", "")
                combined.extend(csv.DictReader(io.StringIO(content)))
    save_csv_dict(combined, output_dir / "all_ner_combined.csv")
    save_summary_rows(combined, elapsed_times, output_dir)


if __name__ == "__main__":
    main()
