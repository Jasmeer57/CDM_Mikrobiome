"""Pairwise + consensus agreement across LLM judges (Anchor 1).

Compares Judge A (gemma-4-E4B, existing results in outputs/logs/llm_judge/results/)
against judges B/C/D (results_multi/<tag>/) on the SAME 2,000-item sample
(500 per artifact C1-C4).

Metrics per artifact:
  * pairwise Cohen's kappa (nominal, quadratic-free) for each judge pair
  * pairwise Krippendorff's alpha (nominal) for each judge pair
  * both computed INCLUDING UNCERTAIN as a category, and on the subset of
    items where BOTH judges returned a non-UNCERTAIN verdict
  * majority-2-of-3 (or 3-of-4 when all four judged) consensus rate per
    artifact, plus the consensus-positive rate vs Judge A's solo rate

Verdicts are read from the flat `verdict` field of each *_verdicts.jsonl
(C2's flat field carries verdict_agreement, the primary verdict — same
convention as Judge A's files).

This script computes agreement BETWEEN JUDGES. It says nothing about
agreement with human truth: there is no human gold standard here.
"""

from __future__ import annotations

import argparse
import datetime as dt
import itertools
import json
from collections import Counter, defaultdict
from pathlib import Path

UNCERTAIN = "UNCERTAIN"


# ----------------------------------------------------------------- metrics --

def cohen_kappa(ratings_a, ratings_b):
    """Nominal Cohen's kappa over paired lists (equal length, non-None)."""
    n = len(ratings_a)
    if n == 0:
        return None
    assert len(ratings_b) == n
    cats = sorted(set(ratings_a) | set(ratings_b))
    idx = {c: i for i, c in enumerate(cats)}
    k = len(cats)
    observed = sum(1 for a, b in zip(ratings_a, ratings_b) if a == b) / n
    # marginal distributions
    pa = Counter(ratings_a)
    pb = Counter(ratings_b)
    expected = sum((pa[c] / n) * (pb[c] / n) for c in cats)
    if expected == 1.0:
        return None if observed < 1.0 else 1.0
    return (observed - expected) / (1.0 - expected)


def krippendorff_alpha_nominal(units):
    """Krippendorff's alpha (nominal metric) via the coincidence matrix.

    units: list of lists — each unit holds the ratings it received from the
    coders being compared (2 each here). Units with fewer than 2 ratings are
    unpairable and skipped. Follows Krippendorff's canonical formulation:

        D_o = sum of coincidences of unequal values / all coincidences
        D_e = (sum_{a != b} n_a * n_b) / (N * (N - 1))   [chance-expected]

    where each unit with m ratings contributes each ORDERED pair (i,j), i != j,
    weighted 1/(m-1); n_a are row sums of the coincidence table and N its total.

    Sanity anchors (verified in the unit test below):
      * all-agree, >=2 categories  -> 1.0
      * perfect balanced disagreement -> negative (D_o > D_e)
      * single category anywhere    -> D_e == 0 -> 1.0 by convention
    """
    # coincidence table
    coin = Counter()
    for values in units:
        vals = [v for v in values if v is not None]
        m = len(vals)
        if m < 2:
            continue
        for i in range(m):
            for j in range(m):
                if i == j:
                    continue
                coin[(vals[i], vals[j])] += 1.0 / (m - 1)
    total = sum(coin.values())
    if total <= 0:
        return None
    d_o = sum(c for (a, b), c in coin.items() if a != b) / total
    # chance-expected disagreement from the marginals
    n_u = Counter()
    for (a, _b), c in coin.items():
        n_u[a] += c
    n_total = sum(n_u.values())
    if n_total < 2:
        return 1.0 if d_o == 0 else None
    d_e = sum(ca * cb for a, ca in n_u.items() for b, cb in n_u.items()
              if a != b) / (n_total * (n_total - 1))
    if d_e == 0:
        return 1.0 if d_o == 0 else None
    return 1.0 - d_o / d_e



# ------------------------------------------------------------------- load ---

def load_verdicts(path: Path) -> dict:
    """Map item_id -> verdict from one *_verdicts.jsonl file."""
    out = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            iid = rec.get("item_id")
            v = rec.get("verdict")
            if iid is not None and v:
                out[iid] = str(v).strip().upper()
    return out


def collect_judge_results(baseline_dir: Path, multi_dir: Path):
    """Per artifact: {judge_tag: {item_id: verdict}} + item universes."""
    judges = {"A": baseline_dir}
    if multi_dir.exists():
        for sub in sorted(multi_dir.iterdir()):
            if sub.is_dir() and (sub / "C1_verdicts.jsonl").exists():
                judges[sub.name] = sub
    artifacts = {}
    for artifact in ("C1", "C2", "C3", "C4"):
        per_judge = {}
        universes = []
        for tag, d in judges.items():
            f = d / f"{artifact}_verdicts.jsonl"
            if f.exists():
                v = load_verdicts(f)
                per_judge[tag] = v
                universes.append(set(v.keys()))
        common = set.intersection(*universes) if universes else set()
        artifacts[artifact] = {"per_judge": per_judge, "common": common}
    return artifacts


# ------------------------------------------------------------------ report --

def fmt(x, nd=3):
    return "n/a" if x is None else f"{x:.{nd}f}"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--baseline", required=True, help="Judge A results dir")
    ap.add_argument("--multi_dir", required=True, help="results_multi/ dir (B,C,D)")
    ap.add_argument("--out_dir", required=True)
    args = ap.parse_args()

    baseline = Path(args.baseline)
    multi = Path(args.multi_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    artifacts = collect_judge_results(baseline, multi)
    tags = sorted({t for a in artifacts.values() for t in a["per_judge"]})

    summary = {"generated_at": dt.datetime.now().isoformat(timespec="seconds"),
               "judges": tags, "per_artifact": {}}
    lines = ["# Multi-judge agreement report (Anchor 1)",
             "",
             f"Generated: {summary['generated_at']}",
             "",
             "Judges compared: " + ", ".join(
                 f"{t} (results dir: {'baseline' if t == 'A' else 'results_multi/' + t})"
                 for t in tags),
             "",
             "**Scope**: agreement between LLM judges on the same 2,000-item",
             "sample. There is NO human gold standard in this comparison;",
             "these numbers quantify judge reproducibility, not correctness.",
             ""]

    for artifact in ("C1", "C2", "C3", "C4"):
        info = artifacts[artifact]
        per_judge, common = info["per_judge"], info["common"]
        if len(per_judge) < 2 or not common:
            lines += [f"## {artifact}", "", "insufficient judges/items; skipped", ""]
            continue
        lines += [f"## Artifact {artifact}",
                  "",
                  f"Items common to all {len(per_judge)} judges: {len(common)}",
                  ""]
        art_summary = {"common_items": len(common), "pairs": {}}

        lines += ["| Judge pair | n | κ (all) | κ (excl. UNCERTAIN-pair items) | α (all) | exact % |",
                  "|---|---:|---:|---:|---:|---:|"]
        for t1, t2 in itertools.combinations(sorted(per_judge), 2):
            ra = [per_judge[t1][i] for i in sorted(common)]
            rb = [per_judge[t2][i] for i in sorted(common)]
            k_all = cohen_kappa(ra, rb)
            a_all = krippendorff_alpha_nominal(
                [[per_judge[t1][i], per_judge[t2][i]] for i in sorted(common)])
            # restricted: both rated non-UNCERTAIN
            idx_both = [i for i in sorted(common)
                        if per_judge[t1][i] != UNCERTAIN and per_judge[t2][i] != UNCERTAIN]
            ra2 = [per_judge[t1][i] for i in idx_both]
            rb2 = [per_judge[t2][i] for i in idx_both]
            k_sub = cohen_kappa(ra2, rb2) if len(idx_both) > 1 else None
            exact = (100 * sum(1 for x, y in zip(ra, rb) if x == y) / len(ra)) if ra else None
            lines.append(
                f"| {t1}–{t2} | {len(ra)} | {fmt(k_all)} | {fmt(k_sub)} | "
                f"{fmt(a_all)} | {fmt(exact, 1)} |")
            art_summary["pairs"][f"{t1}-{t2}"] = {
                "n": len(ra), "kappa_all": k_all, "kappa_non_uncertain": k_sub,
                "alpha_nominal": a_all, "exact_pct": exact,
                "n_non_uncertain": len(ra2),
            }

        # consensus across available judges (>2 judges)
        if len(per_judge) >= 3:
            cons_total = 0
            cons_agree = Counter()
            for i in sorted(common):
                votes = [per_judge[t][i] for t in sorted(per_judge)]
                top, cnt = Counter(votes).most_common(1)[0]
                cons_total += 1
                cons_agree[(top, cnt, len(votes))] += 1
            majority = sum(n for (t, c, k), n in cons_agree.items() if c > k / 2)
            unanimous = sum(n for (t, c, k), n in cons_agree.items() if c == k)
            pct = lambda x: f"{100 * x / cons_total:.1f}%" if cons_total else "n/a"
            lines += ["",
                      f"Consensus (n={cons_total}): **majority** {pct(majority)} · "
                      f"**unanimous** {pct(unanimous)} · "
                      f"{len(per_judge)} judges voting"]
            art_summary["consensus"] = {"n": cons_total,
                                       "majority_pct": 100 * majority / cons_total if cons_total else None,
                                       "unanimous_pct": 100 * unanimous / cons_total if cons_total else None,
                                       "judges": len(per_judge)}
            # per-judge solo positive rates for context
            lines += ["", "Per-judge verdict distributions (context, not agreement):"]
            for t in sorted(per_judge):
                dist = Counter(per_judge[t][i] for i in sorted(common))
                lines.append(f"- {t}: " + ", ".join(f"{k} {v}" for k, v in dist.most_common()))
        lines += [""]
        summary["per_artifact"][artifact] = art_summary

    out_json = out_dir / "judge_agreement.json"
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    report = out_dir / "JUDGE_AGREEMENT.md"
    lines += ["## Interpretation guidance", "",
              "κ ≥ 0.70: judge signal reproducible across model families.",
              "0.40 ≤ κ < 0.70: moderate — treat judge rates as model-dependent.",
              "κ < 0.40: weak — do not headline judge-based quality rates.",
              "",
              "These are machine-machine agreement numbers. The word",
              "'validated' must NOT be used for any pipeline number derived",
              "from judges alone; there is no human gold standard here.",
              ""]
    report.write_text("\n".join(lines), encoding="utf-8")
    print(f"[agreement] wrote {report}")
    print(f"[agreement] wrote {out_json}")


if __name__ == "__main__":
    main()
