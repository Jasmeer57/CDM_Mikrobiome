"""
Claim E analyzer — derive timing comparison from the LLM and spaCy batch runs
already produced under paper_claims/_llm_runs/ and _spacy_runs/.

This avoids re-running the pipelines (which are slow) and reads the timing
summaries emitted by the batch runners.

Inputs (auto-discovered, but can be overridden):
    --llm-dir   : paper_claims/_llm_runs/   (has _batch_summary.csv)
    --spacy-dir : paper_claims/_spacy_runs/ (has _batch_summary.json)
"""
import sys, io
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
else:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
import argparse, csv, json
from pathlib import Path


def linear_regression(xs, ys):
    """Tiny least-squares helper (statistics.linear_regression is 3.10+)."""
    n = len(xs)
    if n < 2:
        return (0.0, 0.0)
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den = sum((x - mx) ** 2 for x in xs)
    slope = num / den if den else 0.0
    intercept = my - slope * mx
    return (slope, intercept)

HERE = Path(__file__).parent
REPO_ROOT = HERE.parent.parent
DEFAULT_LLM = REPO_ROOT / "paper_claims" / "_llm_runs"
DEFAULT_SPACY = REPO_ROOT / "paper_claims" / "_spacy_runs"


def load_llm_timings(llm_dir: Path, papers_dir: Path):
    """Read _batch_summary.csv and merge with per-paper entity counts (from
    the saved .cdm_entities.json). Returns list of dicts."""
    csv_path = llm_dir / "_batch_summary.csv"
    if not csv_path.exists():
        return []
    rows = list(csv.DictReader(csv_path.open(encoding="utf-8")))
    out = []
    for r in rows:
        paper = r["paper"]
        seconds = float(r["seconds"])
        j = llm_dir / paper.replace(".txt", ".cdm_entities.json")
        n_ents = 0
        if j.exists():
            try:
                d = json.loads(j.read_text(encoding="utf-8"))
                inner = d.get("results", {}).get("cdm_entities", {})
                n_ents = sum(len(v) for v in inner.values() if isinstance(v, list))
            except Exception:
                pass
        # size_kb
        p_path = papers_dir / paper
        size_kb = p_path.stat().st_size / 1024 if p_path.exists() else 0
        out.append({
            "paper": paper, "size_kb": round(size_kb, 1),
            "wall_clock_s": seconds, "n_entities": n_ents,
            "throughput": round(n_ents / seconds, 2) if seconds > 0 else 0,
        })
    return out


def load_spacy_timings(spacy_dir: Path, papers_dir: Path):
    """Read _batch_summary.json (saved by run_spacy_batch.py)."""
    p = spacy_dir / "_batch_summary.json"
    if not p.exists():
        return []
    data = json.loads(p.read_text(encoding="utf-8"))
    out = []
    for r in data:
        paper = r["paper"]
        path = papers_dir / paper
        size_kb = path.stat().st_size / 1024 if path.exists() else 0
        out.append({
            "paper": paper, "size_kb": round(size_kb, 1),
            "wall_clock_s": r["seconds"], "n_entities": r["ents"],
            "throughput": round(r["ents"] / r["seconds"], 2) if r["seconds"] > 0 else 0,
        })
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--llm-dir", default=str(DEFAULT_LLM))
    p.add_argument("--spacy-dir", default=str(DEFAULT_SPACY))
    p.add_argument("--papers-dir", default=str(REPO_ROOT / "papers_txt"))
    p.add_argument("--output", default=str(HERE / "results"))
    p.add_argument("--gpu-cost-usd", type=float, default=1.50)
    p.add_argument("--cpu-cost-usd", type=float, default=0.05)
    args = p.parse_args()

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    llm = load_llm_timings(Path(args.llm_dir), Path(args.papers_dir))
    spacy = load_spacy_timings(Path(args.spacy_dir), Path(args.papers_dir))

    print(f"LLM papers: {len(llm)}, spaCy papers: {len(spacy)}\n")
    if not llm or not spacy:
        print("Need both LLM and spaCy batch summaries to compare.")

    # Write per-paper comparison.
    keys = ["paper", "size_kb", "wall_clock_s", "n_entities", "throughput"]
    cmp_rows = []
    spacy_by_paper = {r["paper"]: r for r in spacy}
    for lr in llm:
        sr = spacy_by_paper.get(lr["paper"])
        cmp_rows.append({
            "paper": lr["paper"],
            "size_kb": lr["size_kb"],
            "llm_wall_clock_s": lr["wall_clock_s"],
            "llm_n_entities": lr["n_entities"],
            "llm_throughput": lr["throughput"],
            "spacy_wall_clock_s": sr["wall_clock_s"] if sr else None,
            "spacy_n_entities": sr["n_entities"] if sr else None,
            "spacy_throughput": sr["throughput"] if sr else None,
        })
    if cmp_rows:
        cmp_csv = out_dir / "timings.csv"
        with open(cmp_csv, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(cmp_rows[0].keys()))
            w.writeheader(); w.writerows(cmp_rows)
        print(f"Wrote: {cmp_csv}")
    else:
        print("No papers to compare (no LLM data yet).")

    # Summary.
    if llm and spacy:
        llm_total_s = sum(r["wall_clock_s"] for r in llm)
        llm_total_ents = sum(r["n_entities"] for r in llm)
        sp_total_s = sum(r["wall_clock_s"] for r in spacy)
        sp_total_ents = sum(r["n_entities"] for r in spacy)
        llm_total_cost = llm_total_s / 3600 * args.gpu_cost_usd * 0.5
        sp_total_cost = sp_total_s / 3600 * args.cpu_cost_usd * 4
        print()
        print("=" * 70)
        print("SUMMARY (Claim E — speed / efficiency)")
        print("=" * 70)
        print(f"  LLM  total:  {llm_total_s:7.1f} s  {llm_total_ents:6d} ents  ${llm_total_cost:.4f}")
        print(f"  spaCy total: {sp_total_s:7.1f} s  {sp_total_ents:6d} ents  ${sp_total_cost:.4f}")
        if sp_total_s > 0:
            print(f"\n  spaCy is {llm_total_s/sp_total_s:6.1f}x faster than LLM (wall clock)")
        if sp_total_cost > 0:
            print(f"  LLM costs {llm_total_cost/sp_total_cost:6.1f}x more than spaCy (per this batch)")
        print(f"  LLM throughput:  {llm_total_ents/llm_total_s:6.1f} ents/s overall")
        print(f"  spaCy throughput: {sp_total_ents/sp_total_s:6.1f} ents/s overall")

        # Scalability: s per KB.
        print()
        print("=" * 70)
        print("SCALABILITY (s / KB)")
        print("=" * 70)
        for name, data in [("LLM", llm), ("spaCy", spacy)]:
            valid = [(r["size_kb"], r["wall_clock_s"]) for r in data if r["wall_clock_s"] and r["size_kb"]]
            if len(valid) >= 2:
                xs, ys = zip(*valid)
                slope, intercept = linear_regression(xs, ys)
                print(f"  {name:5s}: wall_clock = {slope:.4f} * size_kb + {intercept:.2f}  ({slope*1024:.2f} s/MB)")

        # Persist a summary JSON.
        summary = {
            "n_papers": len(llm),
            "llm_total_s": round(llm_total_s, 1),
            "spacy_total_s": round(sp_total_s, 1),
            "llm_total_entities": llm_total_ents,
            "spacy_total_entities": sp_total_ents,
            "llm_throughput": round(llm_total_ents / llm_total_s, 2),
            "spacy_throughput": round(sp_total_ents / sp_total_s, 2),
            "spacy_speedup": round(llm_total_s / sp_total_s, 1),
            "llm_total_cost_usd": round(llm_total_cost, 4),
            "spacy_total_cost_usd": round(sp_total_cost, 6),
            "llm_cost_ratio_vs_spacy": round(llm_total_cost / sp_total_cost, 1) if sp_total_cost else None,
            "verdict": "supported" if sp_total_s * 5 < llm_total_s else "weak",
        }
        (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(f"\nWrote: {out_dir / 'summary.json'}")
        print()
        print("=" * 70)
        print(f"VERDICT: {summary['verdict']}  (spaCy {summary['spacy_speedup']}x faster than LLM)")
        print("=" * 70)


if __name__ == "__main__":
    main()
