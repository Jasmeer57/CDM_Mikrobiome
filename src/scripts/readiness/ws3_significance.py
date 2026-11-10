"""WS-3: significance tests for the comparative claims (no new model runs; reads frozen result files).

Families (Holm-adjusted within each family; effect sizes and CIs reported with every p):
  A  cleaning effect (DeepSeek-cleaned layer, kept vs dropped triples):
       XR03 BugSigDB support; Q05 original label supported by its sentence; Q08 microbe-disease edges in a reference;
       chemical-disease edges in CTD. Fisher's exact test, Newcombe CI of the difference, odds ratio. For XR03 also a
       paper-cluster bootstrap (items are nested in 45 papers).
  B  above chance: XR02 taxon in the same paper's BugSigDB signatures vs cross-paper chance; N05 direction agreement
       vs base-rate chance; Q07 microbe-disease edges in a reference vs chance. Exact one-sided binomial test.
  C  NER on gold standards (BC5CDR, BioRED test splits): best trained tagger vs best small open LLM per dataset,
       paired document bootstrap of the exact-F1 difference (5,000 resamples), two-sided p.
  D  judged validity on the corpus (DeepSeek-V4-Flash, distinct strings, valid and correctly typed): each trained or
       zero-shot configuration named in L01-L02 vs the best LLM (L03). Fisher's exact test.

Writes outputs/results/benchmark/significance_2026-11-05/{summary.json,REPORT.md}.
"""
from __future__ import annotations

import json
import math
import random
import sys
from collections import defaultdict
from pathlib import Path

from scipy.stats import binomtest, fisher_exact

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
R = ROOT / "outputs/results"
OUT = R / "benchmark/significance_2026-11-05"
sys.path.insert(0, str(ROOT / "src/scripts/ner_fair_bench"))


def wilson(k, n, z=1.96):
    if not n:
        return [None, None]
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(c - h, 4), round(c + h, 4)]


def newcombe(k1, n1, k2, n2):
    l1, u1 = wilson(k1, n1)
    l2, u2 = wilson(k2, n2)
    p1, p2 = k1 / n1, k2 / n2
    d = p1 - p2
    return [round(d - math.sqrt((p1 - l1) ** 2 + (u2 - p2) ** 2), 4), round(d + math.sqrt((u1 - p1) ** 2 + (p2 - l2) ** 2), 4)]


def holm(rows):
    order = sorted(range(len(rows)), key=lambda i: rows[i]["p"])
    m, running = len(rows), 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (m - rank) * rows[i]["p"]))
        rows[i]["p_holm"] = running
    return rows


def two_prop(name, claim, k1, n1, k2, n2, label1="kept", label2="dropped"):
    odds, p = fisher_exact([[k1, n1 - k1], [k2, n2 - k2]])
    return {"test": name, "claim": claim, label1: [k1, n1, round(100 * k1 / n1, 1), wilson(k1, n1)],
            label2: [k2, n2, round(100 * k2 / n2, 1), wilson(k2, n2)],
            "difference_pts": round(100 * (k1 / n1 - k2 / n2), 1), "difference_ci95": [round(100 * x, 1) for x in newcombe(k1, n1, k2, n2)],
            "odds_ratio": round(odds, 2), "p": p, "method": "Fisher exact, two-sided"}


def x03_cluster_bootstrap(reps=5000, seed=1):
    items = [json.loads(l) for l in open(R / "benchmark/triple_reference_check_2026-11-03/items.jsonl")
             if json.loads(l)["check"] == "bugsigdb_taxon"]
    by = defaultdict(list)
    for it in items:
        by[it["paper_id"]].append((bool(it["cleaned"]["kept"]), it["verdict"] in ("MATCH", "PARTIAL")))
    papers = list(by)
    rnd, diffs = random.Random(seed), []
    for _ in range(reps):
        s = [x for p in (rnd.choice(papers) for _ in papers) for x in by[p]]
        k = [y for kept, y in s if kept]
        d = [y for kept, y in s if not kept]
        if k and d:
            diffs.append(sum(k) / len(k) - sum(d) / len(d))
    diffs.sort()
    p = 2 * min(sum(x <= 0 for x in diffs), sum(x >= 0 for x in diffs)) / len(diffs)
    allk = [y for v in by.values() for kept, y in v if kept]
    alld = [y for v in by.values() for kept, y in v if not kept]
    return {"papers": len(papers), "items": len(items), "kept": [sum(allk), len(allk)], "dropped": [sum(alld), len(alld)],
            "difference_ci95_pts": [round(100 * diffs[int(0.025 * len(diffs))], 1), round(100 * diffs[int(0.975 * len(diffs)) - 1], 1)],
            "p_two_sided": round(min(1.0, p), 4), "reps": len(diffs)}


def ner_gold(reps=5000, seed=7):
    import fairbench as F
    met = json.load(open(R / "benchmark/ner_fair_bench/fair_ner_metrics.json"))
    out = []
    for ds in ("bc5cdr", "biored"):
        docs = F.load(ds)
        types = F.TYPES[ds]
        rows = {k.split("__", 1)[1]: v for k, v in met.items() if k.startswith(ds + "__")}
        trained = max((n for n, v in rows.items() if v["meta"]["kind"] == "trained NER"),
                      key=lambda n: rows[n]["full_schema"]["exact"]["F1"])
        llm = max((n for n in rows if n.startswith("llm_")), key=lambda n: rows[n]["full_schema"]["exact"]["F1"])
        per = {}
        for n in (trained, llm):
            meta, d = F.read_preds(ROOT / "outputs/results/benchmark/ner_fair_bench/preds" / f"{ds}__{n}.jsonl")
            raw, thr = list(d.items()), meta.get("threshold")
            per[n] = F.micro(docs, F.project(raw, n, ds, thr), types, per_doc=True)
        f = {n: F.agg(per[n], types)["exact"]["F1"] for n in per}
        rnd, diffs, k = random.Random(seed), [], len(docs)
        for _ in range(reps):
            idx = [rnd.randrange(k) for _ in range(k)]
            diffs.append(F.agg([per[trained][i] for i in idx], types)["exact"]["F1"] -
                         F.agg([per[llm][i] for i in idx], types)["exact"]["F1"])
        diffs.sort()
        p = 2 * min(sum(x <= 0 for x in diffs), sum(x >= 0 for x in diffs)) / reps
        out.append({"test": f"{ds}: best trained vs best small LLM (exact F1)", "dataset": ds, "trained": trained,
                    "llm": llm, "trained_in_domain": rows[trained].get("in_domain_training"), "f1_trained": round(100 * f[trained], 1), "f1_llm": round(100 * f[llm], 1),
                    "f1_registered": [round(100 * rows[trained]["full_schema"]["exact"]["F1"], 1),
                                      round(100 * rows[llm]["full_schema"]["exact"]["F1"], 1)],
                    "difference_pts": round(100 * (f[trained] - f[llm]), 1),
                    "difference_ci95": [round(100 * diffs[int(0.025 * reps)], 1), round(100 * diffs[int(0.975 * reps) - 1], 1)],
                    "p": max(p, 1 / reps), "p_note": f"bootstrap; floor 1/{reps}", "docs": k,
                    "method": "paired document bootstrap, two-sided"})
    return out


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    tr = json.load(open(R / "benchmark/triple_reference_check_2026-11-03/summary.json"))
    ev = json.load(open(R / "kg_2026-11-04/evidence_check/summary.json"))
    gk = json.load(open(R / "kg_2026-11-04/gold_kg_check/summary.json"))
    bs = json.load(open(R / "benchmark/bugsigdb_comparison_2026-11-03/summary.json"))
    lj = json.load(open(R / "benchmark/llm_judge_deepseek_v4_flash/summary.json"))

    s = tr["bugsigdb"]["support"]
    md, cd = gk["edge_types"]["microbe_disease"], gk["edge_types"]["chemical_disease"]
    A = holm([
        two_prop("BugSigDB support, kept vs dropped", "XR03", s["kept"]["k"], s["kept"]["n"], s["dropped"]["k"], s["dropped"]["n"]),
        two_prop("label supported by sentence, kept vs dropped", "Q05", ev["kept"]["k"], ev["kept"]["n"], ev["dropped"]["k"], ev["dropped"]["n"]),
        two_prop("microbe-disease edge in reference, kept vs dropped", "Q08", md["kept"]["k"], md["kept"]["n"], md["dropped"]["k"], md["dropped"]["n"]),
        two_prop("chemical-disease edge in CTD, kept vs dropped", "(Q09 strata)", cd["kept"]["k"], cd["kept"]["n"], cd["dropped"]["k"], cd["dropped"]["n"]),
    ])
    A[0]["paper_cluster_bootstrap"] = x03_cluster_bootstrap()

    def above(name, claim, k, n, p0):
        t = binomtest(k, n, p0, alternative="greater")
        return {"test": name, "claim": claim, "k": k, "n": n, "rate_pct": round(100 * k / n, 1), "ci95": wilson(k, n),
                "chance_pct": round(100 * p0, 1), "p": t.pvalue, "method": "exact binomial, one-sided (greater than chance)"}
    dt = bs["taxa"]["catalogue"]
    Bf = holm([
        above("taxon in same paper's BugSigDB signatures vs cross-paper chance", "XR02", tr["bugsigdb"]["support"]["all"]["k"],
              tr["bugsigdb"]["support"]["all"]["n"], tr["bugsigdb"]["support_chance"]),
        above("direction agreement vs base-rate chance", "N05", dt["direction"]["SAME"], dt["direction_determinable"],
              dt["posthoc_direction_chance"]),
        above("microbe-disease edges in Disbiome/BugSigDB vs chance", "Q07", md["support"]["k"], md["support"]["n"], md["chance"]),
    ])
    C = holm(ner_gold())
    bench = lj["benchmark"]

    def vt(n):
        d = bench[n]["distinct"]
        return d["valid_type"], d["d"]
    best_llm = "llm_gemma_zs"
    D = holm([two_prop(f"judged valid+typed: {n} vs {best_llm}", c, *vt(n), *vt(best_llm), label1=n, label2=best_llm)
              for n, c in (("bert_chemical", "L01 vs L03"), ("gliner_v25_medium", "L02 vs L03"),
                           ("hunflair2", "Table 1"), ("scispacy_bc5cdr", "Table 1"))])
    res = {"note": "Tests on frozen results; no new model runs. Holm adjustment within each family.",
           "A_cleaning_effect": A, "B_above_chance": Bf, "C_ner_gold_standard": C, "D_judged_validity": D}
    (OUT / "summary.json").write_text(json.dumps(res, indent=1, default=float) + "\n")
    fmt = lambda p: "<1e-300" if p == 0 else (f"{p:.1e}" if p < 1e-3 else f"{p:.3f}")
    L = ["# Significance tests (WS-3), 2026-11-05", "", "Frozen results only; Holm-adjusted within each family.", "",
         "## A. Cleaning effect (kept vs dropped triples)", "",
         "| claim | test | kept % (k/n) | dropped % (k/n) | diff pts [95% CI] | OR | p | p Holm |", "|---|---|---|---|---|---:|---:|---:|"]
    for r in A:
        L.append(f"| {r['claim']} | {r['test']} | {r['kept'][2]} ({r['kept'][0]}/{r['kept'][1]}) | {r['dropped'][2]} "
                 f"({r['dropped'][0]}/{r['dropped'][1]}) | {r['difference_pts']} [{r['difference_ci95'][0]}, {r['difference_ci95'][1]}] | "
                 f"{r['odds_ratio']} | {fmt(r['p'])} | {fmt(r['p_holm'])} |")
    cb = A[0]["paper_cluster_bootstrap"]
    L += ["", f"XR03 with papers resampled ({cb['papers']} papers, {cb['items']} items): difference CI "
              f"[{cb['difference_ci95_pts'][0]}, {cb['difference_ci95_pts'][1]}] pts, p = {cb['p_two_sided']}.", "",
          "## B. Above chance", "", "| claim | test | rate % [95% CI] | chance % | p (one-sided) | p Holm |", "|---|---|---|---:|---:|---:|"]
    for r in Bf:
        L.append(f"| {r['claim']} | {r['test']} | {r['rate_pct']} [{round(100*r['ci95'][0],1)}, {round(100*r['ci95'][1],1)}] "
                 f"({r['k']}/{r['n']}) | {r['chance_pct']} | {fmt(r['p'])} | {fmt(r['p_holm'])} |")
    L += ["", "## C. Gold-standard NER: best trained tagger vs best small LLM", "",
          "| dataset | trained (F1) | LLM (F1) | diff pts [95% CI] | p | p Holm |", "|---|---|---|---|---:|---:|"]
    for r in C:
        L.append(f"| {r['dataset']} | {r['trained']} ({r['f1_trained']}) | {r['llm']} ({r['f1_llm']}) | {r['difference_pts']} "
                 f"[{r['difference_ci95'][0]}, {r['difference_ci95'][1]}] | {fmt(r['p'])} | {fmt(r['p_holm'])} |")
    L += ["", "## D. Judged validity on the corpus (DeepSeek-V4-Flash, distinct strings)", "",
          "| claim | comparison | A % (k/n) | B % (k/n) | diff pts [95% CI] | p | p Holm |", "|---|---|---|---|---|---:|---:|"]
    for r in D:
        a, b = [v for k, v in r.items() if isinstance(v, list) and len(v) == 4][:2]
        L.append(f"| {r['claim']} | {r['test']} | {a[2]} ({a[0]}/{a[1]}) | {b[2]} ({b[0]}/{b[1]}) | {r['difference_pts']} "
                 f"[{r['difference_ci95'][0]}, {r['difference_ci95'][1]}] | {fmt(r['p'])} | {fmt(r['p_holm'])} |")
    (OUT / "REPORT.md").write_text("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
