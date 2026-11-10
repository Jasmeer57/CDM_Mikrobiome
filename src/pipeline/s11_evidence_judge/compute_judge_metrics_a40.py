"""Aggregate LLM-as-judge verdicts into a metrics report (Wilson 95% CI).

Reads <results>/<ARTIFACT>_full_verdicts.jsonl (full-scale) or
<results>/<ARTIFACT>_verdicts.jsonl (sample), and for each artifact reports:
  * judged / expected counts and the missing count,
  * the full verdict distribution,
  * the artifact's headline rate over DECIDED items (UNCERTAIN excluded from both
    numerator and denominator),
  * a 95% Wilson score interval for that rate,
  * the UNCERTAIN count and rate, reported separately,
  * judge-confidence statistics (mean, median, quartiles, 0.1-bin histogram).

With --require-complete the report is FAIL-CLOSED: any artifact whose judged
count is below its known full-set size is marked INCOMPLETE and the process
exits 1, so a truncated run can never be mistaken for a complete one.

Rate definitions follow outputs/logs/gold_standard/REVIEW_GUIDELINES.md:
  C1  correctness   = SUPPORTED / (SUPPORTED + PARTIALLY_SUPPORTED + NOT_SUPPORTED)
  C2  inventory     = CORRECT / (CORRECT + INCORRECT)
      canonical     = CORRECT / (CORRECT + INCORRECT)
      agreement     = AGREE / (AGREE + DISAGREE)
  C3  mapping valid = VALID / (VALID + INVALID + TOO_BROAD + TOO_NARROW)
  C4  sensibility   = SENSIBLE / (SENSIBLE + PLAUSIBLE_BUT_WEAK + NONSENSE)

This is an LLM-as-judge measurement. It is NOT a human gold standard and NOT
human validation.

Usage:
  python compute_judge_metrics_a40.py --results outputs/logs/llm_judge/results \
      --out outputs/logs/llm_judge/JUDGE_METRICS_FULL.md --require-complete
"""
import argparse
import json
import math
import os
from pathlib import Path

ARTIFACTS = ["C1", "C2", "C3", "C4"]

# Known full-set sizes (source artifact row counts).
EXPECTED = {"C1": 56985, "C2": 27870, "C3": 334231, "C4": 32713}

SPEC = {
    "C1": [("correctness", "verdict", "SUPPORTED",
            ["SUPPORTED", "PARTIALLY_SUPPORTED", "NOT_SUPPORTED"])],
    "C2": [("inventory type correctness", "verdict_inventory_type", "CORRECT",
            ["CORRECT", "INCORRECT"]),
           ("canonical type correctness", "verdict_canonical_type", "CORRECT",
            ["CORRECT", "INCORRECT"]),
           ("pipeline agreement", "verdict_agreement", "AGREE",
            ["AGREE", "DISAGREE"])],
    "C3": [("mapping validity", "verdict", "VALID",
            ["VALID", "INVALID", "TOO_BROAD", "TOO_NARROW"])],
    "C4": [("claim sensibility", "verdict", "SENSIBLE",
            ["SENSIBLE", "PLAUSIBLE_BUT_WEAK", "NONSENSE"])],
}

HEADLINE = {"C1": "correctness", "C2": "canonical type correctness",
            "C3": "mapping validity", "C4": "claim sensibility"}

# 500-item sample baseline (run on 2026-10-27, job 28642401).
SAMPLE_MEAN_CONF = 0.914
CONF_SHIFT_FLAG = 0.05


def wilson(k, n, z=1.959963984540054):
    if n <= 0:
        return (0.0, 0.0, 0.0)
    p = k / n
    denom = 1.0 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (100.0 * p, 100.0 * max(0.0, centre - half), 100.0 * min(1.0, centre + half))


def load(path):
    recs = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    recs.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return recs


def pct(x):
    return f"{x:.1f}%"


def quantile(sorted_vals, q):
    if not sorted_vals:
        return 0.0
    idx = (len(sorted_vals) - 1) * q
    lo, hi = int(math.floor(idx)), int(math.ceil(idx))
    if lo == hi:
        return sorted_vals[lo]
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (idx - lo)


def conf_stats(recs):
    vals = sorted(r["confidence"] for r in recs
                  if isinstance(r.get("confidence"), (int, float)))
    if not vals:
        return None
    n = len(vals)
    hist = {f"{i/10:.1f}-{(i+1)/10:.1f}": 0 for i in range(10)}
    for v in vals:
        b = min(9, int(v * 10))
        hist[f"{b/10:.1f}-{(b+1)/10:.1f}"] += 1
    mean = sum(vals) / n
    return {"n": n, "mean": mean, "median": quantile(vals, 0.5),
            "q1": quantile(vals, 0.25), "q3": quantile(vals, 0.75),
            "min": vals[0], "max": vals[-1], "hist": hist,
            "shift": mean - SAMPLE_MEAN_CONF}


def analyze(artifact, recs):
    out = {"n": len(recs), "errors": 0, "metrics": {}, "distributions": {},
           "confidence": conf_stats(recs)}
    for r in recs:
        if r.get("verdict") is None and not any(r.get(f) for _, f, _, _ in SPEC[artifact]):
            out["errors"] += 1
    for label, field, positive, decided in SPEC[artifact]:
        dist = {}
        for r in recs:
            v = r.get(field)
            if v is None:
                continue
            dist[v] = dist.get(v, 0) + 1
        out["distributions"][label] = dist
        n_decided = sum(dist.get(v, 0) for v in decided)
        k = dist.get(positive, 0)
        rate, lo, hi = wilson(k, n_decided)
        out["metrics"][label] = {
            "positive": positive, "k": k, "n_decided": n_decided,
            "rate": rate, "lo": lo, "hi": hi,
            "uncertain": dist.get("UNCERTAIN", 0),
            "uncertain_pct": (100.0 * dist.get("UNCERTAIN", 0) / len(recs)) if recs else 0.0,
        }
    return out


def resolve(results, artifact, require_complete):
    full = results / f"{artifact}_full_verdicts.jsonl"
    sample = results / f"{artifact}_verdicts.jsonl"
    if require_complete:
        return full if full.exists() else None
    if full.exists():
        return full
    return sample if sample.exists() else None


def main():
    ap = argparse.ArgumentParser(description="Aggregate LLM-as-judge verdicts")
    ap.add_argument("--results", default="outputs/logs/llm_judge/results")
    ap.add_argument("--out", default="outputs/logs/llm_judge/JUDGE_METRICS.md")
    ap.add_argument("--require-complete", action="store_true",
                    help="fail closed if any artifact is below its full-set size")
    args = ap.parse_args()

    results = Path(args.results)
    stats, missing, incomplete = {}, [], []
    for a in ARTIFACTS:
        p = resolve(results, a, args.require_complete)
        if p is None:
            missing.append(str(results / f"{a}_full_verdicts.jsonl"))
            continue
        stats[a] = analyze(a, load(p))
        if args.require_complete and stats[a]["n"] < EXPECTED[a]:
            incomplete.append(a)

    L = []
    L.append("# LLM-as-judge metrics — FULL-SCALE\n")
    L.append("> **LLM-as-judge (Gemma 4 E4B W4A16, thinking disabled). FULL-SCALE.**")
    L.append("> **NOT a human gold standard. Human calibration: STILL PENDING.**")
    L.append("> **C1/C2 numbers are upper bounds until 10-item calibration lands.**\n")
    L.append("The judge is a different model family from the extractor under audit "
             "(Qwen 3.5:9b). These are model-judged agreement rates — not human "
             "validation and not accuracy against a gold standard.\n")
    L.append("Rates are computed over **decided** items only; `UNCERTAIN` is excluded "
             "from both numerator and denominator and reported separately. Intervals "
             "are 95% Wilson score intervals.\n")

    if args.require_complete:
        status = "COMPLETE" if not incomplete and not missing else "INCOMPLETE"
        L.append(f"**Completion status: {status}**\n")
        L.append("| Artifact | Judged | Expected | Missing | Status |")
        L.append("|---|---|---|---|---|")
        for a in ARTIFACTS:
            got = stats[a]["n"] if a in stats else 0
            miss = max(0, EXPECTED[a] - got)
            st = "COMPLETE" if (a in stats and miss == 0) else "INCOMPLETE"
            L.append(f"| {a} | {got:,} | {EXPECTED[a]:,} | {miss:,} | {st} |")
        L.append("")

    if missing:
        L.append("## Missing result files\n")
        for m in missing:
            L.append(f"- `{m}` — not found")
        L.append("")

    L.append("## Headline\n")
    L.append("| Artifact | Metric | Rate (decided) | 95% CI | decided / total | UNCERTAIN |")
    L.append("|---|---|---|---|---|---|")
    for a in ARTIFACTS:
        if a not in stats:
            L.append(f"| {a} | {HEADLINE[a]} | _n/a_ | _n/a_ | _n/a_ | _n/a_ |")
            continue
        s = stats[a]
        m = s["metrics"][HEADLINE[a]]
        L.append(f"| {a} | {HEADLINE[a]} | **{pct(m['rate'])}** | "
                 f"{pct(m['lo'])}–{pct(m['hi'])} | {m['n_decided']:,} / {s['n']:,} | "
                 f"{m['uncertain']:,} ({pct(m['uncertain_pct'])}) |")
    L.append("")

    L.append("## Per-artifact detail\n")
    for a in ARTIFACTS:
        if a not in stats:
            continue
        s = stats[a]
        L.append(f"### {a} — {s['n']:,} judged, {s['errors']:,} failed all retries\n")
        for label, field, positive, decided in SPEC[a]:
            m = s["metrics"][label]
            dist = s["distributions"][label]
            ds = ", ".join(f"{k}={v:,}" for k, v in sorted(dist.items(), key=lambda kv: -kv[1]))
            L.append(f"**{label}** — `{positive} / ({' + '.join(decided)})`\n")
            L.append(f"- rate: **{pct(m['rate'])}** (95% CI {pct(m['lo'])}–{pct(m['hi'])}), "
                     f"{m['k']:,}/{m['n_decided']:,} decided")
            L.append(f"- UNCERTAIN: {m['uncertain']:,} ({pct(m['uncertain_pct'])}) — excluded")
            L.append(f"- distribution: {ds or '(none)'}")
            L.append("")
        c = s["confidence"]
        if c:
            flag = ""
            if abs(c["shift"]) > CONF_SHIFT_FLAG:
                flag = f" ⚠️ **shift {c['shift']:+.3f} vs sample {SAMPLE_MEAN_CONF:.3f} — judge-instability signal**"
            L.append(f"**judge confidence** — n={c['n']:,}, mean={c['mean']:.3f}, "
                     f"median={c['median']:.3f}, Q1={c['q1']:.3f}, Q3={c['q3']:.3f}, "
                     f"range {c['min']:.2f}–{c['max']:.2f}{flag}")
            L.append("")
            L.append("| confidence bin | count |")
            L.append("|---|---|")
            for b, n in c["hist"].items():
                L.append(f"| {b} | {n:,} |")
            L.append("")

    if stats:
        L.append("## Totals\n")
        L.append(f"- items judged: **{sum(s['n'] for s in stats.values()):,}**")
        L.append(f"- failed all retries: **{sum(s['errors'] for s in stats.values()):,}**")
        if args.require_complete:
            L.append(f"- expected total: **{sum(EXPECTED.values()):,}**")
        L.append("")
        L.append("## Interpretation guardrails\n")
        L.append("- A rate means *the judge accepted the artifact*, not that the artifact "
                 "is correct.")
        L.append("- C1 `PARTIALLY_SUPPORTED` is **not** counted as correct; only "
                 "`SUPPORTED` is.")
        L.append("- C4 judges coherence, not biological truth.")
        L.append("- Human calibration is still pending: fill the 10-item sheet before "
                 "quoting any number. ≥8/10 agreement is required to report judge-based "
                 "claims at full weight.")
        L.append("")

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(L), encoding="utf-8")
    print(f"wrote {out_path}")

    summary = {a: {"judged": s["n"],
                   "expected": EXPECTED[a],
                   "complete": s["n"] >= EXPECTED[a],
                   "confidence_mean": (s["confidence"] or {}).get("mean"),
                   "metrics": {k: {"rate": round(v["rate"], 2),
                                   "ci": [round(v["lo"], 2), round(v["hi"], 2)],
                                   "k": v["k"], "n": v["n_decided"],
                                   "uncertain": v["uncertain"]}
                               for k, v in s["metrics"].items()}}
               for a, s in stats.items()}
    (out_path.parent / "_judge_summary_full.json").write_text(
        json.dumps({"artifacts": summary,
                    "totals": {"judged": sum(s["n"] for s in stats.values()),
                               "errors": sum(s["errors"] for s in stats.values()),
                               "expected": sum(EXPECTED.values())},
                    "require_complete": args.require_complete,
                    "incomplete": incomplete}, indent=2), encoding="utf-8")

    if args.require_complete and (incomplete or missing):
        print(f"INCOMPLETE: {incomplete or 'missing files: ' + ', '.join(missing)}",
              file=os.sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
