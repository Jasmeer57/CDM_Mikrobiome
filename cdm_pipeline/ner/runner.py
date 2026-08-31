"""Multi-NER runner CLI — orchestrates GLiNER + PubMedBERT + PubTator3."""
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
else:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

warnings.filterwarnings("ignore")
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
os.environ["TRANSFORMERS_VERBOSITY"] = "error"

import argparse
from collections import Counter

from ..config import PAPERS_DIR, NER_OUTPUT_DIR
from .gliner import run_gliner
from .pubmedbert import run_pubmedbert
from .pubtator import run_pubtator


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
    parser = argparse.ArgumentParser(description="Run multi-NER on corpus")
    parser.add_argument("--models", nargs="+", default=["gliner", "pubmedbert", "pubtator"],
                        choices=["gliner", "pubmedbert", "pubtator", "all"],
                        help="Which NER models to run")
    parser.add_argument("--max_files", type=int, default=500, help="Max papers to process")
    parser.add_argument("--incremental", action="store_true",
                        help="Skip papers already in the output CSV (append mode)")
    parser.add_argument("--threshold", type=float, default=0.5, help="GLiNER threshold")
    parser.add_argument("--api_key", default=os.environ.get("ENTREZ_API_KEY", ""),
                        help="NCBI Entrez API key for PubTator")
    args = parser.parse_args()

    if "all" in args.models:
        args.models = ["gliner", "pubmedbert", "pubtator"]

    # Get paper list
    all_papers = sorted([f.name for f in PAPERS_DIR.glob("*.txt")])[:args.max_files]
    print("Found %d papers in %s" % (len(all_papers), PAPERS_DIR))

    # Incremental mode: skip papers already in existing output CSVs
    if args.incremental:
        model_csv_map = {"gliner": "gliner_ner.csv", "pubmedbert": "pubmedbert_ner.csv", "pubtator": "pubtator3_ner.csv"}
        done = set()
        for model_name in args.models:
            csv_name = model_csv_map.get(model_name, "")
            if not csv_name:
                continue
            csv_path = NER_OUTPUT_DIR / csv_name
            if csv_path.exists():
                with open(csv_path, encoding="utf-8", errors="replace") as f:
                    content = f.read().replace("\x00", "")
                    done.update(r["paper"] for r in csv.DictReader(io.StringIO(content)))
        papers = [p for p in all_papers if p not in done]
        print("Incremental: %d already done across selected models, %d remaining" % (len(done), len(papers)))
    else:
        papers = all_papers

    if not papers:
        print("Nothing to do — all papers already processed.")
        return

    print("Running models:", args.models, "on %d papers" % len(papers))

    NER_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    all_results = []
    elapsed_times = {}

    # Load existing results for merge when incremental
    existing_results = {"gliner": [], "pubmedbert": [], "pubtator": []}
    if args.incremental:
        for model_key, csv_name in [("gliner", "gliner_ner.csv"),
                                     ("pubmedbert", "pubmedbert_ner.csv"),
                                     ("pubtator", "pubtator3_ner.csv")]:
            csv_path = NER_OUTPUT_DIR / csv_name
            if csv_path.exists():
                with open(csv_path, encoding="utf-8", errors="replace") as f:
                    content = f.read().replace("\x00", "")
                    existing_results[model_key] = list(csv.DictReader(io.StringIO(content)))
                print("  Loaded %d existing rows from %s" % (len(existing_results[model_key]), csv_name))

    if "gliner" in args.models:
        results, elapsed = run_gliner(papers, threshold=args.threshold)
        merged = existing_results["gliner"] + [dict(zip(["term","labels","model","paper","char_start","char_end"], r)) for r in results]
        save_csv_dict(merged, NER_OUTPUT_DIR / "gliner_ner.csv")
        all_results.extend(results)
        elapsed_times["gliner_medium"] = elapsed
        del results; gc.collect()

    if "pubmedbert" in args.models:
        results, elapsed = run_pubmedbert(papers)
        merged = existing_results["pubmedbert"] + [dict(zip(["term","labels","model","paper","char_start","char_end"], r)) for r in results]
        save_csv_dict(merged, NER_OUTPUT_DIR / "pubmedbert_ner.csv")
        all_results.extend(results)
        elapsed_times["biobert_diseases"] = elapsed
        del results; gc.collect()

    if "pubtator" in args.models:
        results, elapsed = run_pubtator(papers, api_key=args.api_key)
        merged = existing_results["pubtator"] + [dict(zip(["term","labels","model","paper","char_start","char_end"], r)) for r in results]
        save_csv_dict(merged, NER_OUTPUT_DIR / "pubtator3_ner.csv")
        all_results.extend(results)
        elapsed_times["pubtator3"] = elapsed
        del results; gc.collect()

    # Combined CSV (all models, all papers)
    combined = []
    for csv_name in ["gliner_ner.csv", "pubmedbert_ner.csv", "pubtator3_ner.csv"]:
        csv_path = NER_OUTPUT_DIR / csv_name
        if csv_path.exists():
            with open(csv_path, encoding="utf-8", errors="replace") as f:
                content = f.read().replace("\x00", "")
                combined.extend(csv.DictReader(io.StringIO(content)))
    save_csv_dict(combined, NER_OUTPUT_DIR / "all_ner_combined.csv")
    save_summary_rows(combined, elapsed_times, NER_OUTPUT_DIR)


if __name__ == "__main__":
    main()
