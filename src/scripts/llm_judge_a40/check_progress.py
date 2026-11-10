"""Progress checker for the full-scale LLM-as-judge run.

Reads the resume cache and the per-artifact result files (read-only) and prints
per-artifact progress, throughput and ETA. Safe to run while the job is going —
the cache is rewritten atomically, so a concurrent read sees either the old or
the new complete file, never a torn one.

  python src/scripts/llm_judge_a40/check_progress.py
  python src/scripts/llm_judge_a40/check_progress.py --cache outputs/logs/llm_judge/_judge_full_cache.json
"""

_CDM_ROOT = next(p for p in __import__("pathlib").Path(__file__).resolve().parents
                 if (p / ".cdm_root").is_file())  # repo root, found at run time
import argparse
import json
import os
import time

ROOT = str(_CDM_ROOT)
OUTD = os.path.join(ROOT, "outputs/logs", "llm_judge")
RESULTS = os.path.join(OUTD, "results")

# Smallest-first runtime order, with full-set sizes.
ORDER = [("C2", 27870), ("C4", 32713), ("C1", 56985), ("C3", 334231)]


def count_rows(path):
    if not os.path.exists(path):
        return 0
    n = 0
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                n += 1
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=os.path.join(OUTD, "_judge_full_cache.json"))
    args = ap.parse_args()

    cache = {}
    if os.path.exists(args.cache):
        try:
            with open(args.cache, encoding="utf-8") as fh:
                cache = json.load(fh)
        except (json.JSONDecodeError, OSError):
            print("cache unreadable (job may be mid-write; retry in a moment)")

    # Cache entries carry their artifact tag.
    by_art = {}
    for entry in cache.values():
        a = entry.get("artifact")
        if a:
            by_art[a] = by_art.get(a, 0) + 1

    print(f"cache: {args.cache}")
    print(f"cache entries: {len(cache):,}")
    print()
    print(f"{'artifact':8} {'judged':>9} {'expected':>9} {'pct':>7} {'rows':>9}  status")
    print("-" * 62)
    total_j = total_e = 0
    for a, expected in ORDER:
        judged = by_art.get(a, 0)
        rows = count_rows(os.path.join(RESULTS, f"{a}_full_verdicts.jsonl"))
        pct = 100.0 * judged / expected if expected else 0.0
        if judged >= expected:
            status = "COMPLETE"
        elif judged or rows:
            status = "IN PROGRESS"
        else:
            status = "pending"
        total_j += judged
        total_e += expected
        print(f"{a:8} {judged:9,} {expected:9,} {pct:6.1f}% {rows:9,}  {status}")
    print("-" * 62)
    print(f"{'TOTAL':8} {total_j:9,} {total_e:9,} "
          f"{100.0 * total_j / total_e:6.1f}%")
    print()

    # Throughput from the newest cache timestamps.
    stamps = []
    for entry in cache.values():
        ts = entry.get("timestamp")
        if ts:
            try:
                stamps.append(time.mktime(time.strptime(ts, "%Y-%m-%dT%H:%M:%S")))
            except ValueError:
                pass
    if len(stamps) >= 10:
        stamps.sort()
        window = stamps[-1] - stamps[max(0, len(stamps) - 2000)]
        if window > 0:
            rate = min(2000, len(stamps)) / window
            remain = total_e - total_j
            print(f"recent rate: ~{rate:.1f} items/s over the last {window / 60:.0f} min")
            if rate > 0 and remain > 0:
                hrs = remain / rate / 3600.0
                print(f"remaining:   {remain:,} items -> ~{hrs:.2f} h")
    print()
    print("NOTE: LLM-as-judge, NOT human validation. Calibration still pending.")
    print("If the job hits walltime, resubmit the same sbatch — the cache resumes it.")


if __name__ == "__main__":
    main()
