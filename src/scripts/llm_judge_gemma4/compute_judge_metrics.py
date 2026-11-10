"""P6 - aggregate LLM-as-judge results into per-artifact x metric rates.

Reads $OUTD/results/{artifact}_{metric}.jsonl produced by run_judge_client.py,
writes:
  $OUTD/JUDGE_METRICS.md   - per-artifact x metric counts, rate, Wilson 95% CI
  $OUTD/repair_queue.jsonl - one row per flagged item

Judge = Gemma 4 E4B (4-bit). Extractor = Qwen 3.5:9b. This is LLM-as-judge,
NOT a human gold standard and NOT human validation.

Usage:
  python compute_judge_metrics.py --results $OUTD/results --outdir $OUTD
"""

_CDM_ROOT = next(p for p in __import__("pathlib").Path(__file__).resolve().parents
                 if (p / ".cdm_root").is_file())  # repo root, found at run time
import argparse
import glob
import json
import math
import os
from collections import Counter, defaultdict

ROOT = str(_CDM_ROOT)
OUTD = os.path.join(ROOT, "outputs/logs", "llm_judge")

METRICS = [
    "metric_faithfulness",
    "metric_context_precision",
    "metric_context_recall",
    "metric_factual_correctness",
    "metric_instruction_following",
    "metric_completeness",
    "metric_relevance",
]

# verdict -> acceptable? (None == UNCERTAIN / excluded from numerator+denominator)
ACCEPT = {
    "FAITHFUL": True, "PARTIALLY_FAITHFUL": True, "UNFAITHFUL": False, "UNCERTAIN": None,
    "HIGH": True, "MEDIUM": True, "LOW": False,
    "COMPLETE": True, "PARTIAL": True, "MISSING": False, "INCOMPLETE": False,
    "CORRECT": True, "INCORRECT": False,
    "YES": True, "NO": False,
}

# which verdict value flags an item for repair, per metric
FLAG = {
    "metric_faithfulness": {"UNFAITHFUL"},
    "metric_factual_correctness": {"INCORRECT"},
}

SUGGESTED_ACTION = {
    "metric_faithfulness": "re-extract",
    "metric_factual_correctness": "re-extract",
}

# RAGAS-style / task-excellence mapping for the README/table
METRIC_KIND = {
    "metric_faithfulness": "RAGAS",
    "metric_context_precision": "RAGAS",
    "metric_context_recall": "RAGAS",
    "metric_factual_correctness": "task",
    "metric_instruction_following": "task",
    "metric_completeness": "task",
    "metric_relevance": "task",
}


def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - m) / d, (c + m) / d)


def primary_verdict(rec):
    """Extract the metric's verdict string from a result record."""
    vj = rec.get("verdict_json")
    if not isinstance(vj, dict):
        return None
    if "verdict" in vj:
        return vj.get("verdict")
    # C2-style multi-field verdicts: use the canonical-side type as primary
    for key in ("verdict_canonical_type", "verdict_inventory_type", "verdict_agreement"):
        if key in vj:
            return vj.get(key)
    return None


def load_results(results_dir):
    """Return {artifact: {metric: [records]}} and the judge model seen."""
    data = defaultdict(lambda: defaultdict(list))
    model = None
    for path in sorted(glob.glob(os.path.join(results_dir, "*_metric_*.jsonl"))):
        base = os.path.basename(path)[:-6]  # strip .jsonl
        if "_metric_" not in base:
            continue
        artifact, metric = base.split("_metric_", 1)
        metric = "metric_" + metric
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                d = json.loads(line)
                model = model or d.get("model")
                data[artifact][metric].append(d)
    return data, model


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default=os.path.join(OUTD, "results"))
    ap.add_argument("--outdir", default=OUTD)
    ap.add_argument("--judge-model", default=os.environ.get("JUDGE_MODEL", ""))
    args = ap.parse_args()

    data, model = load_results(args.results)
    judge = args.judge_model or model or "(unknown)"
    os.makedirs(args.outdir, exist_ok=True)

    lines = []
    lines.append("# LLM-as-judge evaluation (Gemma 4 E4B, 4-bit, thinking=false)")
    lines.append("")
    lines.append("- Judge: Gemma 4 E4B (4-bit GPTQ, vLLM, thinking disabled) — `%s`" % judge)
    lines.append("- Extractor under audit: Qwen 3.5:9b")
    lines.append("- Prompt version: judge-gemma4-v1")
    lines.append("")
    lines.append("**NOT a human gold standard.** Human calibration: pending "
                 "(see `HUMAN_CALIBRATION_SHEET.csv`). UNCERTAIN is excluded from the "
                 "numerator and denominator; N and the 95% Wilson CI are reported for "
                 "every rate.")
    lines.append("")

    repair = []
    flagged_total = 0
    summary = {}  # artifact -> {metric: rate%}

    if not data:
        lines.append("_No judge results found in `%s`._" % args.results)
    for artifact in ["C1", "C2", "C3", "C4"]:
        per_metric = data.get(artifact, {})
        if not per_metric:
            continue
        lines.append("## %s" % artifact)
        lines.append("")
        lines.append("| metric | kind | n | decided | rate | 95% CI | UNCERTAIN | flagged |")
        lines.append("|---|---|---:|---:|---:|---|---:|---:|")
        summary[artifact] = {}
        for metric in METRICS:
            rows = per_metric.get(metric, [])
            if not rows:
                continue
            dist = Counter(primary_verdict(r) for r in rows)
            dist.pop(None, 0)
            n = sum(dist.values())
            acc_k = sum(c for k, c in dist.items() if ACCEPT.get(k) is True)
            acc_n = sum(c for k, c in dist.items() if ACCEPT.get(k) is not None)
            unc = dist.get("UNCERTAIN", 0)
            rate = 100.0 * acc_k / acc_n if acc_n else float("nan")
            lo, hi = wilson(acc_k, acc_n)
            flagset = FLAG.get(metric, set())
            flagged = sum(c for k, c in dist.items() if k in flagset)
            flagged_total += flagged
            summary[artifact][metric] = rate
            lines.append("| %s | %s | %d | %d | %s | %s | %d | %d |" % (
                metric, METRIC_KIND[metric], n, acc_n,
                ("%.1f%%" % rate) if acc_n else "n/a",
                ("%.1f-%.1f%%" % (100 * lo, 100 * hi)) if acc_n else "n/a",
                unc, flagged))
            for r in rows:
                v = primary_verdict(r)
                if v in flagset:
                    repair.append({
                        "item_id": r.get("item_id"),
                        "artifact": artifact,
                        "metric": metric,
                        "verdict": v,
                        "suggested_action": SUGGESTED_ACTION.get(metric, "flag-for-human"),
                    })
        lines.append("")

    lines.append("## Flagged items")
    lines.append("")
    lines.append("Flag rules: `metric_faithfulness == UNFAITHFUL`, "
                 "`metric_factual_correctness == INCORRECT`. **%d** item(s) flagged; "
                 "see `repair_queue.jsonl`." % flagged_total)
    lines.append("")

    out_md = os.path.join(args.outdir, "JUDGE_METRICS.md")
    with open(out_md, "w") as fh:
        fh.write("\n".join(lines) + "\n")

    with open(os.path.join(args.outdir, "repair_queue.jsonl"), "w") as fh:
        for r in repair:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    with open(os.path.join(args.outdir, "_judge_summary.json"), "w") as fh:
        json.dump({"judge": judge, "summary": summary, "flagged": flagged_total}, fh, indent=1)

    print("wrote %s (flagged=%d)" % (out_md, flagged_total))
    for art, m in summary.items():
        parts = " ".join("%s=%.1f%%" % (k.replace("metric_", ""), v)
                         for k, v in m.items() if v == v)
        print("  %s: %s" % (art, parts))


if __name__ == "__main__":
    main()
