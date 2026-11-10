"""Cross-benchmark analysis: does public (BioRED) per-type F1 predict corpus grounding? Plus runtime/failure inventory.

Reads the frozen outputs of fairbench.py and corpus_bench.py; writes final_validation/benchmark/benchmark_analysis.json.
Grounding is a precision proxy, not accuracy; rank correlations are descriptive (model-type pairs are not independent).

    python benchmark_analysis.py
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
FAIR = ROOT / "outputs/results/ner_fair_bench/fair_ner_metrics.json"
CORP = ROOT / "outputs/results/ner_corpus_bench/corpus_metrics.json"
OUT = ROOT / "paper/publication/final_validation/benchmark/benchmark_analysis.json"
TYPES = ("GeneOrGeneProduct", "DiseaseOrPhenotypicFeature", "ChemicalEntity", "OrganismTaxon", "SequenceVariant")


def ranks(x):
    order = sorted(range(len(x)), key=lambda i: x[i])
    r = [0.0] * len(x)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and x[order[j + 1]] == x[order[i]]:
            j += 1
        for k in range(i, j + 1):
            r[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return r


def spearman(a, b):
    if len(a) < 3:
        return None
    ra, rb = ranks(a), ranks(b)
    ma, mb = sum(ra) / len(ra), sum(rb) / len(rb)
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    va = sum((x - ma) ** 2 for x in ra) ** 0.5
    vb = sum((y - mb) ** 2 for y in rb) ** 0.5
    return round(cov / (va * vb), 3) if va and vb else None


def main():
    fair = json.load(open(FAIR))
    corp = json.load(open(CORP))["models"]
    pairs = {t: [] for t in TYPES}
    for model, c in corp.items():
        f = fair.get(f"biored__{model}")
        if not f:
            continue
        for t in TYPES:
            g = (c.get("grounding") or {}).get(t)
            p = (f.get("per_type") or {}).get(t)
            if g and p and g["unique"] >= 50:
                pairs[t].append({"model": model, "kind": c["meta"].get("kind"), "biored_exact_f1": round(100 * p["exact"]["F1"], 1),
                                 "biored_exact_p": round(100 * p["exact"]["P"], 1), "corpus_grounded_pct": g["grounded_pct"],
                                 "corpus_unique": g["unique"]})
    corr = {}
    for t, rows in pairs.items():
        corr[t] = {"n_models": len(rows),
                   "spearman_f1_vs_grounding": spearman([r["biored_exact_f1"] for r in rows], [r["corpus_grounded_pct"] for r in rows]),
                   "spearman_precision_vs_grounding": spearman([r["biored_exact_p"] for r in rows], [r["corpus_grounded_pct"] for r in rows])}
    inv = {}
    for model, c in corp.items():
        m = c["meta"]
        inv[model] = {k: m.get(k) for k in ("kind", "llm", "device", "threshold", "seconds", "seconds_this_run", "failed_chunks",
                                             "truncated_chunks", "salvaged_chunks", "strings", "strings_not_in_text", "invalid_type")
                      if m.get(k) is not None}
        inv[model]["papers_with_entities"] = c.get("papers_with_entities")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"public_vs_corpus": {"correlation": corr, "pairs": pairs}, "run_inventory": inv}, indent=1) + "\n")
    print(json.dumps(corr, indent=1))
    for model, v in inv.items():
        print(model, v)


if __name__ == "__main__":
    main()
