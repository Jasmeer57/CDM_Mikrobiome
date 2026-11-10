"""P6 - judge metrics: verdict distributions, rates, Wilson 95% CIs, and a
chi-square test that the sample's stratum mix matches the full population.

LLM-as-judge evaluation, NOT human validation and NOT a gold standard.

Reads judge output JSONL (run_judge.py) plus sample_strata.json, writes
$OUTD/labeled/JUDGE_METRICS.md.
"""

_CDM_ROOT = next(p for p in __import__("pathlib").Path(__file__).resolve().parents
                 if (p / ".cdm_root").is_file())  # repo root, found at run time
import argparse
import json
import math
import os
from collections import Counter, defaultdict

ROOT = str(_CDM_ROOT)
OUTD = os.path.join(ROOT, "outputs/logs", "gold_standard")
LAB = os.path.join(OUTD, "labeled")

VERDICT_FIELDS = {
    "triples": ["verdict"],
    "mappings": ["verdict"],
    "records": ["verdict"],
    "types": ["verdict_inventory_type", "verdict_canonical_type", "verdict_agreement"],
}

# "positive"/acceptable verdict sets, for rate reporting
ACCEPT = {
    "SUPPORTED": True, "PARTIALLY_SUPPORTED": True, "NOT_SUPPORTED": False, "UNCERTAIN": None,
    "CORRECT": True, "INCORRECT": False,
    "AGREE": True, "DISAGREE": False,
    "VALID": True, "INVALID": False, "TOO_BROAD": False, "TOO_NARROW": False,
    "SENSIBLE": True, "PLAUSIBLE_BUT_WEAK": True, "NONSENSE": False,
}


def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - m) / d, (c + m) / d)


def chi2_uniform(observed, expected_frac):
    """Chi-square of observed counts vs expected fractions (goodness of fit)."""
    n = sum(observed.values())
    if n == 0:
        return 0.0, 0.0, 0
    stat = 0.0
    for k, exp_f in expected_frac.items():
        exp = exp_f * n
        obs = observed.get(k, 0)
        if exp > 0:
            stat += (obs - exp) ** 2 / exp
    df = len(expected_frac) - 1
    return stat, df, n


def chi2_sf(stat, df):
    """Survival function of chi-square via a simple series/gamma approach."""
    if df <= 0:
        return 1.0
    # regularized upper incomplete gamma Q(df/2, stat/2)
    a = df / 2.0
    x = stat / 2.0
    if x <= 0:
        return 1.0
    if x < a + 1:
        # lower series for P
        term = 1.0 / a
        s = term
        n = 1
        while n < 200:
            term *= x / (a + n)
            s += term
            if abs(term) < 1e-12 * abs(s):
                break
            n += 1
        p = s * math.exp(-x + a * math.log(x) - math.lgamma(a))
        return max(0.0, min(1.0, 1.0 - p))
    # continued fraction for Q
    tiny = 1e-300
    b = x + 1 - a
    c = 1 / tiny
    d = 1 / b
    h = d
    for i in range(1, 200):
        an = -i * (i - a)
        b += 2
        d = an * d + b
        if abs(d) < tiny:
            d = tiny
        c = b + an / c
        if abs(c) < tiny:
            c = tiny
        d = 1 / d
        delta = d * c
        h *= delta
        if abs(delta - 1) < 1e-12:
            break
    q = math.exp(-x + a * math.log(x) - math.lgamma(a)) * h
    return max(0.0, min(1.0, q))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--indir", default=LAB)
    ap.add_argument("--output", default=os.path.join(LAB, "JUDGE_METRICS.md"))
    ap.add_argument("--judge-model", default=os.environ.get("JUDGE_MODEL", "(from results)"))
    args = ap.parse_args()

    strata = {}
    sp = os.path.join(args.indir, "sample_strata.json")
    if os.path.exists(sp):
        strata = json.load(open(sp))

    # map item_id -> artifact using the sample
    item_art = {}
    samp = os.path.join(args.indir, "sample_input.jsonl")
    if os.path.exists(samp):
        with open(samp) as fh:
            for line in fh:
                d = json.loads(line)
                item_art[d["item_id"]] = d["artifact"]

    # collect judge results (default expected filenames)
    results = defaultdict(list)
    default_files = {
        "records": "judge_records.jsonl",
        "triples": "judge_triples.jsonl",
        "mappings": "judge_mappings.jsonl",
        "types": "judge_types.jsonl",
    }
    for art, fname in default_files.items():
        p = os.path.join(args.indir, fname)
        if os.path.exists(p):
            with open(p) as fh:
                for line in fh:
                    results[art].append(json.loads(line))

    lines = []
    lines.append("# LLM-as-Judge Metrics")
    lines.append("")
    lines.append("> Framing: this is an **LLM-as-judge** evaluation of an automated")
    lines.append("> extraction pipeline (extractor: Qwen 3.5:9b). It is **not** a human")
    lines.append("> gold standard and **not** human validation.")
    lines.append("")
    lines.append("- Judge model: `%s`" % args.judge_model)
    lines.append("- Prompt version: judge-v1")
    lines.append("")

    any_results = False
    for art in ["triples", "mappings", "records", "types"]:
        rows = results.get(art, [])
        if not rows:
            lines.append("## %s" % art)
            lines.append("")
            lines.append("_No judge output found (expected `%s`)._ Run `run_judge.py` first."
                         % default_files[art])
            lines.append("")
            continue
        any_results = True
        lines.append("## %s (n=%d)" % (art, len(rows)))
        lines.append("")
        for vf in VERDICT_FIELDS[art]:
            dist = Counter(r.get(vf) for r in rows)
            n = sum(v for k, v in dist.items() if k is not None)
            if n == 0:
                continue
            lines.append("### %s" % vf)
            lines.append("")
            lines.append("| verdict | count | share |")
            lines.append("|---|---:|---:|")
            for k in sorted(dist, key=lambda x: (x is None, x)):
                if k is None:
                    continue
                lines.append("| %s | %d | %.1f%% |" % (k, dist[k], 100 * dist[k] / n))
            lines.append("")
            # acceptable rate with Wilson CI (UNCERTAIN excluded)
            acc_k = sum(c for k, c in dist.items() if ACCEPT.get(k) is True)
            acc_n = sum(c for k, c in dist.items() if ACCEPT.get(k) is not None)
            if acc_n:
                lo, hi = wilson(acc_k, acc_n)
                lines.append("Acceptable rate (UNCERTAIN excluded): **%.1f%%** (%.1f-%.1f%%, Wilson 95%% CI; %d/%d)"
                             % (100 * acc_k / acc_n, 100 * lo, 100 * hi, acc_k, acc_n))
                lines.append("")
            unc = dist.get("UNCERTAIN", 0)
            lines.append("Uncertain share: %.1f%% (%d/%d)" % (100 * unc / n, unc, n))
            lines.append("")

    # chi-square: sample stratum mix vs full population
    lines.append("## Sample-vs-full chi-square (stratum mix)")
    lines.append("")
    for art, info in (strata.get("artifacts", {}) or {}).items():
        st = info.get("strata", {})
        if not st:
            continue
        total_pop = sum(v["population"] for v in st.values())
        expected = {k: v["population"] / total_pop for k, v in st.items()}
        observed = {k: v["selected"] for k, v in st.items()}
        stat, df, n = chi2_uniform(observed, expected)
        p = chi2_sf(stat, df)
        lines.append("- **%s**: chi2=%.3f, df=%d, p=%.3f (%s)"
                     % (art, stat, df, p,
                        "sample mix matches full" if p > 0.05 else "SAMPLE MIX DIVERGES"))
    lines.append("")
    if not any_results:
        lines.append("_No judge results yet; metrics tables will populate after a run._")
        lines.append("")

    with open(args.output, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    print("wrote", args.output)


if __name__ == "__main__":
    main()
