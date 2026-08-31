#!/usr/bin/env python3
"""
Claim E benchmark — speed / efficiency / cost per document.

Measures wall clock, peak memory, throughput, and cost on a sample of papers
from `papers_txt/`. Compares the LLM and spaCy pipelines head-to-head.

Usage (from this folder):
    python benchmark.py
    python benchmark.py --n-papers 10
    python benchmark.py --papers-dir /path/to/papers_txt/
    python benchmark.py --output results/
    python benchmark.py --gpu-cost-usd 1.50    # $/hr for an A100 (default 1.50)
    python benchmark.py --cpu-cost-usd 0.05    # $/hr per core (default 0.05)

If the pipelines can't be loaded (e.g., no Ollama running, no scispaCy models
installed), the script still records the wall clock for whichever subset
*can* run, and reports the missing one as N/A.
"""
import argparse
import csv
import json
import os
import resource
import sys
import time
import tracemalloc
from pathlib import Path

HERE = Path(__file__).parent
REPO_ROOT = HERE.parent.parent
DEFAULT_PAPERS_DIR = REPO_ROOT / "papers_txt"


def get_rss_mb():
    """Peak resident-set-size in MB (POSIX). On Windows, use working-set."""
    try:
        rusage = resource.getrusage(resource.RUSAGE_SELF)
        return rusage.ru_maxrss / 1024  # Linux: KB; macOS: bytes — heuristic
    except Exception:
        try:
            import psutil
            return psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024)
        except Exception:
            return -1


def _try_load_llm():
    try:
        llm_root = REPO_ROOT / "llm_terms"
        sys.path.insert(0, str(llm_root))
        from core.pipeline import CDMEntityPipeline
        from config.cdm_config import PipelineConfig
        return CDMEntityPipeline(
            model="qwen3:8b",
            config=PipelineConfig(default_model="qwen3:8b"),
        )
    except Exception as exc:
        print(f"  [warn] LLM pipeline not available: {type(exc).__name__}: {str(exc)[:120]}")
        return None


def _try_load_spacy():
    try:
        spacy_root = REPO_ROOT / "spacy_terms"
        sys.path.insert(0, str(spacy_root))
        from src.config.settings import get_config
        from src.modules.terms_extractor import create_terms_extractor
        cfg = get_config()
        return create_terms_extractor(cfg)
    except Exception as exc:
        print(f"  [warn] spaCy pipeline not available: {type(exc).__name__}: {str(exc)[:120]}")
        return None


def time_pipeline(run_fn, text, label):
    """Time a single pipeline run. Returns dict of metrics."""
    tracemalloc.start()
    t0 = time.time()
    n_entities = 0
    err = None
    try:
        ents = run_fn(text)
        n_entities = len(ents) if ents else 0
    except Exception as exc:
        err = f"{type(exc).__name__}: {str(exc)[:80]}"
    elapsed = time.time() - t0
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    rss_mb = get_rss_mb()
    return {
        "wall_clock_s": round(elapsed, 3),
        "peak_tracemalloc_mb": round(peak / (1024 * 1024), 1),
        "rss_mb": round(rss_mb, 1) if rss_mb > 0 else None,
        "n_entities": n_entities,
        "throughput_entities_per_s": round(n_entities / elapsed, 2) if elapsed > 0 else 0,
        "error": err,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--papers-dir", default=str(DEFAULT_PAPERS_DIR))
    parser.add_argument("--n-papers", type=int, default=10)
    parser.add_argument("--gpu-cost-usd", type=float, default=1.50, help="USD per GPU-hour")
    parser.add_argument("--cpu-cost-usd", type=float, default=0.05, help="USD per CPU-hour")
    parser.add_argument("--output", default=str(HERE / "results"))
    parser.add_argument("--llm-only", action="store_true")
    parser.add_argument("--spacy-only", action="store_true")
    args = parser.parse_args()

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    papers_dir = Path(args.papers_dir)
    if not papers_dir.exists():
        print(f"Papers dir not found: {papers_dir}")
        sys.exit(1)
    paper_paths = sorted([p for p in papers_dir.glob("*.txt") if p.is_file()])[: args.n_papers]
    if not paper_paths:
        print(f"No .txt files in {papers_dir}")
        sys.exit(1)

    print(f"Will benchmark on {len(paper_paths)} papers from {papers_dir}\n")

    llm = None if args.spacy_only else _try_load_llm()
    spacy_ex = None if args.llm_only else _try_load_spacy()
    if llm:
        print("LLM pipeline: loaded")
    if spacy_ex:
        print("spaCy pipeline: loaded")

    rows = []
    for paper in paper_paths:
        text = paper.read_text(encoding="utf-8", errors="ignore")
        size_kb = len(text.encode("utf-8")) / 1024
        print(f"\n--- {paper.name}  ({size_kb:.1f} KB) ---")

        row = {
            "paper": paper.name,
            "size_kb": round(size_kb, 1),
        }

        if llm:
            print("  running LLM... ", end="", flush=True)
            m = time_pipeline(lambda t=text: llm.extract_entities(t), text, "LLM")
            print(f"{m['wall_clock_s']}s, {m['n_entities']} entities")
            for k, v in m.items():
                row[f"llm_{k}"] = v
            # Rough cost: assume one A100 used at 50% util → effective $/hr
            row["llm_cost_usd"] = round(m["wall_clock_s"] / 3600 * args.gpu_cost_usd * 0.5, 6)
        else:
            for k in ["wall_clock_s", "peak_tracemalloc_mb", "rss_mb", "n_entities", "throughput_entities_per_s", "error"]:
                row[f"llm_{k}"] = None
            row["llm_cost_usd"] = None

        if spacy_ex:
            print("  running spaCy... ", end="", flush=True)
            m = time_pipeline(lambda t=text: spacy_ex.extract_from_text(t), text, "spaCy")
            print(f"{m['wall_clock_s']}s, {m['n_entities']} entities")
            for k, v in m.items():
                row[f"spacy_{k}"] = v
            # Cost: assume 4 CPU cores at the per-core $/hr
            row["spacy_cost_usd"] = round(m["wall_clock_s"] / 3600 * args.cpu_cost_usd * 4, 6)
        else:
            for k in ["wall_clock_s", "peak_tracemalloc_mb", "rss_mb", "n_entities", "throughput_entities_per_s", "error"]:
                row[f"spacy_{k}"] = None
            row["spacy_cost_usd"] = None

        rows.append(row)

    # Persist CSV.
    fieldnames = list(rows[0].keys()) if rows else []
    csv_path = out_dir / "timings.csv"
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)
    print(f"\nWrote: {csv_path}")

    # Summary.
    print()
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    if rows and rows[0].get("llm_wall_clock_s") is not None:
        llm_total_s = sum(r["llm_wall_clock_s"] for r in rows if r["llm_wall_clock_s"] is not None)
        llm_total_ents = sum(r["llm_n_entities"] for r in rows if r["llm_n_entities"] is not None)
        llm_total_cost = sum(r["llm_cost_usd"] for r in rows if r["llm_cost_usd"] is not None)
        print(f"  LLM total:  {llm_total_s:6.1f} s, {llm_total_ents:5d} entities, ${llm_total_cost:.4f}")
        if llm_total_s > 0:
            print(f"  LLM throughput:  {llm_total_ents/llm_total_s:.1f} entities/s overall")
            print(f"  LLM avg cost:    ${(llm_total_cost/len(rows)):.6f} / paper")
    if rows and rows[0].get("spacy_wall_clock_s") is not None:
        sp_total_s = sum(r["spacy_wall_clock_s"] for r in rows if r["spacy_wall_clock_s"] is not None)
        sp_total_ents = sum(r["spacy_n_entities"] for r in rows if r["spacy_n_entities"] is not None)
        sp_total_cost = sum(r["spacy_cost_usd"] for r in rows if r["spacy_cost_usd"] is not None)
        print(f"  spaCy total: {sp_total_s:6.1f} s, {sp_total_ents:5d} entities, ${sp_total_cost:.4f}")
        if sp_total_s > 0:
            print(f"  spaCy throughput: {sp_total_ents/sp_total_s:.1f} entities/s overall")
            print(f"  spaCy avg cost:   ${(sp_total_cost/len(rows)):.6f} / paper")

    if llm and spacy_ex:
        # Headline.
        if llm_total_s > 0 and sp_total_s > 0:
            speedup = llm_total_s / sp_total_s
            print(f"\n  spaCy is {speedup:.1f}x faster than LLM (wall clock, total)")
        if sp_total_cost > 0:
            cost_ratio = llm_total_cost / sp_total_cost if sp_total_cost > 0 else float("inf")
            print(f"  LLM costs {cost_ratio:.1f}x more than spaCy (per this batch)")

    # Scalability linear fit (size_kb vs wall clock).
    print()
    print("=" * 70)
    print("SCALABILITY (s/KB)")
    print("=" * 70)
    if rows and rows[0].get("llm_wall_clock_s") is not None:
        valid = [(r["size_kb"], r["llm_wall_clock_s"]) for r in rows if r["llm_wall_clock_s"] is not None and r["size_kb"] > 0]
        if len(valid) >= 2:
            try:
                from statistics import linear_regression
                xs, ys = zip(*valid)
                slope, intercept = linear_regression(xs, ys)
                print(f"  LLM:   wall_clock = {slope:.4f} * size_kb + {intercept:.2f}  ({slope*1024:.2f} s/MB)")
            except Exception:
                pass
    if rows and rows[0].get("spacy_wall_clock_s") is not None:
        valid = [(r["size_kb"], r["spacy_wall_clock_s"]) for r in rows if r["spacy_wall_clock_s"] is not None and r["size_kb"] > 0]
        if len(valid) >= 2:
            try:
                from statistics import linear_regression
                xs, ys = zip(*valid)
                slope, intercept = linear_regression(xs, ys)
                print(f"  spaCy: wall_clock = {slope:.4f} * size_kb + {intercept:.2f}  ({slope*1024:.2f} s/MB)")
            except Exception:
                pass


if __name__ == "__main__":
    main()
