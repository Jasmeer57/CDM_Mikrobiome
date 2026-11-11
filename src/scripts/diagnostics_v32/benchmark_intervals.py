"""Missing intervals and n's (diagnostics 2026-11-11, item 4).

  a. BugSigDB cross-paper comparison (register N02-N05): recomputes counts, denominators and 95% Wilson intervals from
     the frozen item file outputs/results/benchmark/bugsigdb_comparison_2026-11-03/items.jsonl, checks them against the
     frozen summary.json (src/scripts/bugsigdb_comparison/compare.py), reports the paper-cluster bootstrap intervals
     stored there, and exact binomial tests against the stated chance levels.
  b. Spearman correlation of BioRED exact F1 with corpus grounding per entity type (register H04/H05; computed by
     src/scripts/final_validation/benchmark_analysis.py from the frozen pairs in benchmark_analysis.json): n
     configurations, distinct systems, rho, asymptotic and permutation p-values, percentile bootstrap 95% CI, and a
     one-point-per-system sensitivity (zero-shot / few-shot LLM configurations averaged).
Reads only; writes outputs/results/diagnostics_2026-11-11/missing_intervals/{SUMMARY.json, REPORT.md}.

    python src/scripts/diagnostics_v32/benchmark_intervals.py
Written with Claude Code (declare)."""
from __future__ import annotations

import json
import random
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy import stats

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
sys.path.insert(0, str(ROOT / "src/scripts/diagnostics_v32"))
from stats_util import prop  # noqa: E402

BSD = ROOT / "outputs/results/benchmark/bugsigdb_comparison_2026-11-03"
BA = ROOT / "paper/publication/final_validation/benchmark/benchmark_analysis.json"
OUT = ROOT / "outputs/results/diagnostics_2026-11-11/missing_intervals"
SEED = 20261111


def bugsigdb():
    S = json.load(open(BSD / "summary.json"))
    t = S["taxa"]["catalogue"]
    items = [json.loads(l) for l in open(BSD / "items.jsonl", encoding="utf-8")]
    tax = [i for i in items if i["field"] == "taxon"]
    our = [i for i in items if i["field"] == "our_taxon"]
    cov_k = sum(i["verdict"] in ("MATCH", "PARTIAL") for i in tax)
    ex_k = sum(i["verdict"] == "MATCH" for i in tax)
    sup_k = sum(i["verdict"] in ("MATCH", "PARTIAL") for i in our)
    det = [i for i in tax if (i.get("direction") or {}).get("agreement") in ("SAME", "OPPOSITE")]
    dir_k = sum(i["direction"]["agreement"] == "SAME" for i in det)
    def test(k, n, p0):
        return float(f"{stats.binomtest(k, n, p0, alternative='greater').pvalue:.3g}")
    res = {
        "source": "outputs/results/benchmark/bugsigdb_comparison_2026-11-03 (items.jsonl recomputed; summary.json from compare.py)",
        "papers": S["papers"], "signatures": S["signatures"],
        "N02_coverage_exact_or_same_genus": {**prop(cov_k, len(tax)), "paper_cluster_bootstrap95": [round(100 * x, 1) for x in t["coverage_bootstrap"]],
                                             "chance_pct": round(100 * t["coverage_chance"], 1), "binomial_p_vs_chance": test(cov_k, len(tax), t["coverage_chance"]),
                                             "matches_summary": round(cov_k / len(tax), 4) == t["coverage"]},
        "N03_coverage_exact_id": {**prop(ex_k, len(tax)), "matches_summary": round(ex_k / len(tax), 4) == t["exact_coverage"]},
        "N04_our_taxa_in_bugsigdb": {**prop(sup_k, len(our)), "paper_cluster_bootstrap95": [round(100 * x, 1) for x in t["support_bootstrap"]],
                                     "chance_pct": round(100 * t["support_chance"], 1), "binomial_p_vs_chance": test(sup_k, len(our), t["support_chance"]),
                                     "matches_summary": round(sup_k / len(our), 4) == t["support_rate"]},
        "N05_direction_same": {**prop(dir_k, len(det)), "paper_cluster_bootstrap95": [round(100 * x, 1) for x in t["direction_same_bootstrap"]],
                               "base_rate_chance_pct": round(100 * t["posthoc_direction_chance"], 1),
                               "binomial_p_vs_base_rate": test(dir_k, len(det), t["posthoc_direction_chance"]),
                               "undetermined_pairs": t["direction"].get("UNDETERMINED"), "opposite": len(det) - dir_k,
                               "papers_with_determinable_pairs": len({i["paper_id"] for i in det}),
                               "matches_summary": round(dir_k / len(det), 4) == t["direction_same"]},
        "unit_note": "N02/N03/N05 units are (paper, BugSigDB leaf taxon) items pooled over the paper's signatures; N04 units are "
                     "(paper, catalogue taxon) items. Items cluster in 47 papers, so the paper-cluster bootstrap interval is the "
                     "honest one; Wilson intervals assume independent items and are too narrow.",
    }
    return res


def spearman_block(x, y, rng, reps=10000):
    x, y = np.asarray(x, float), np.asarray(y, float)
    r = stats.spearmanr(x, y)
    perm = np.array([stats.spearmanr(x, rng.permutation(y)).statistic for _ in range(reps)])
    p_perm = float((np.sum(np.abs(perm) >= abs(r.statistic) - 1e-12) + 1) / (reps + 1))
    bs = []
    n = len(x)
    for _ in range(reps):
        i = rng.integers(0, n, n)
        if len(set(x[i])) > 1 and len(set(y[i])) > 1:
            bs.append(stats.spearmanr(x[i], y[i]).statistic)
    lo, hi = np.percentile(bs, [2.5, 97.5])
    return {"rho": round(float(r.statistic), 3), "p_asymptotic": float(f"{r.pvalue:.3g}"), "p_permutation": float(f"{p_perm:.3g}"),
            "bootstrap95": [round(float(lo), 3), round(float(hi), 3)]}


def system_of(model):
    return model.rsplit("_", 1)[0] if model.startswith("llm_") and model.rsplit("_", 1)[1] in ("zs", "fs") else model


def spearman():
    B = json.load(open(BA))["public_vs_corpus"]
    rng = np.random.default_rng(SEED)
    res = {"source": "paper/publication/final_validation/benchmark/benchmark_analysis.json (pairs), recomputed with scipy",
           "inclusion": "configurations with BioRED per-type F1 and >= 50 unique corpus strings of that type",
           "definition_corpus_grounding": (
               "src/scripts/ner_fair_bench/corpus_bench.py score: share (%) of a configuration's UNIQUE entity strings of the "
               "predicted BioRED type that resolve by dictionary lookup (normalised string variants) in a reference vocabulary "
               "of that type -- NCBI Gene (short symbols case-sensitive), CTD-MEDIC/MeSH diseases + Mondo + HPO, CTD/MeSH "
               "chemicals, NCBI Taxonomy names; SequenceVariant = regular-expression pattern match; CellLine not grounded. "
               "No LLM judge, no human check; a vocabulary hit is a precision proxy (junk can match a synonym, real entities can "
               "be missing)."),
           "per_type": {}}
    for t, rows in B["pairs"].items():
        x = [r["biored_exact_f1"] for r in rows]
        y = [r["corpus_grounded_pct"] for r in rows]
        d = {"n_configurations": len(rows), "n_systems": len({system_of(r["model"]) for r in rows}),
             "configurations": [r["model"] for r in rows],
             "frozen_rho": B["correlation"][t]["spearman_f1_vs_grounding"], **spearman_block(x, y, rng)}
        g = defaultdict(list)
        for r in rows:
            g[system_of(r["model"])].append((r["biored_exact_f1"], r["corpus_grounded_pct"]))
        xs = [np.mean([a for a, _ in v]) for v in g.values()]
        ys = [np.mean([b for _, b in v]) for v in g.values()]
        d["one_point_per_system"] = {"n": len(g), **spearman_block(xs, ys, rng)}
        res["per_type"][t] = d
    return res


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    s = {"date": "2026-11-11", "bugsigdb": bugsigdb(), "spearman_biored_vs_grounding": spearman(),
         "status": "diagnostic recomputation from frozen outputs; PENDING lead approval"}
    (OUT / "SUMMARY.json").write_text(json.dumps(s, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(s, indent=1)[:8000])


if __name__ == "__main__":
    main()
