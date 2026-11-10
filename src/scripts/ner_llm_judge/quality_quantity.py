"""Quality and quantity of every NER configuration on the 453-paper corpus, per entity type, from the existing
DeepSeek verdicts (no new API calls).

quantity = distinct strings judged valid and correctly typed (and those also judged microbiome-relevant);
quality  = that count / distinct strings judged (95% Wilson); coverage = papers with at least one such mention.
Model judgements, not accuracy.

    python quality_quantity.py        # normally: sbatch quality_quantity.sbatch
"""
from __future__ import annotations

import csv
import gzip
import json
import re
import sys
from collections import defaultdict

import judge as J

sys.path.insert(0, str(J.ROOT / "src/scripts/ner_fair_bench"))
OUT = J.ROOT / "outputs/results/benchmark/ner_quality_quantity_2026-11-03"
TYPES = ["OrganismTaxon", "DiseaseOrPhenotypicFeature", "ChemicalEntity", "GeneOrGeneProduct", "SequenceVariant", "CellLine"]


def wilson(k, n, z=1.959964):
    if not n:
        return None
    p, d = k / n, 1 + z * z / n
    c, h = (p + z * z / (2 * n)) / d, z * (p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5 / d
    return [round(100 * (c - h), 1), round(100 * (c + h), 1)]


def main():
    verdict = {}
    with gzip.open(J.ROOT / "outputs/results/benchmark/llm_judge_deepseek_v4_flash/entity_verdicts.csv.gz", "rt", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["scheme"] == "biored" and r["valid"] in ("Y", "N"):
                verdict[(r["string"], r["proposed_type"])] = (r["valid"] == "Y", r["microbiome_relevant"] == "Y",
                                                               r["valid"] == "Y" and r["type_correct"] == "Y")
    seen = defaultdict(set)                      # (config, type) -> distinct strings judged
    good = defaultdict(set)                      # ... valid + correctly typed
    good_micro = defaultdict(set)                # ... and microbiome-relevant
    mentions = defaultdict(lambda: [0, 0])       # (config, type) -> [judged mentions, valid+typed mentions]
    papers = defaultdict(set)                    # (config, type) -> papers with a valid+typed mention
    all_papers = set()
    for cfg, s, t in J.bench_mentions():
        v = verdict.get((s, t))
        if v is None:
            continue
        k = (cfg, t)
        seen[k].add(s)
        mentions[k][0] += 1
        if v[2]:
            good[k].add(s)
            mentions[k][1] += 1
        if v[2] and v[1]:
            good_micro[k].add(s)
    # papers: re-read predictions with chunk ids
    import fairbench as FB
    text = {json.loads(l)["chunk_id"]: json.loads(l)["text"] for l in open(J.BENCH / "chunks.jsonl", encoding="utf-8")}
    for p in sorted((J.BENCH / "preds").glob("*.jsonl")):
        if p.name.endswith(".partial.jsonl"):
            continue
        raw = {}
        for l in open(p, encoding="utf-8"):
            r = json.loads(l)
            if "chunk_id" in r:
                raw[r["chunk_id"]] = r["preds"]
        for cid, ps in FB.project(list(raw.items()), p.stem, "biored"):
            m = re.search(r"HMPAPER_\d{6}", cid)
            pid = m.group(0) if m else cid.split(":")[0]
            all_papers.add(pid)
            for s, e, t in ps:
                v = verdict.get((J.norm(text[cid][s:e]), t))
                if v and v[2]:
                    papers[(p.stem, t)].add(pid)
    rows = []
    for (cfg, t) in sorted(seen):
        n, g = len(seen[(cfg, t)]), len(good[(cfg, t)])
        rows.append({"config": cfg, "type": t, "distinct_judged": n, "valid_typed_distinct": g,
                     "valid_typed_microbiome_distinct": len(good_micro[(cfg, t)]),
                     "quality_pct": round(100 * g / n, 1) if n else None,
                     "quality_wilson": wilson(g, n),
                     "mentions_judged": mentions[(cfg, t)][0], "valid_typed_mentions": mentions[(cfg, t)][1],
                     "papers_with_valid_typed": len(papers[(cfg, t)])})
    tot = defaultdict(lambda: defaultdict(int))
    for r in rows:
        for k in ("distinct_judged", "valid_typed_distinct", "valid_typed_microbiome_distinct", "mentions_judged", "valid_typed_mentions"):
            tot[r["config"]][k] += r[k]
    for cfg, d in tot.items():
        d["quality_pct"] = round(100 * d["valid_typed_distinct"] / d["distinct_judged"], 1) if d["distinct_judged"] else None
        d["types"] = sum(1 for r in rows if r["config"] == cfg and r["valid_typed_distinct"] > 0)
        d["papers_with_valid_typed"] = len(set().union(*(papers[(cfg, t)] for t in TYPES)))
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "per_config_type.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    summary = {"papers": len(all_papers), "per_config": tot, "per_config_type": rows}
    (OUT / "summary.json").write_text(json.dumps(summary, indent=1))
    L = ["# NER quality and quantity on all papers (DeepSeek-judged)", "",
         f"*{len(all_papers)} papers. Quantity = distinct strings judged valid and correctly typed; quality = that share of the "
         "distinct strings judged; papers = papers with at least one such mention. Model judgements, not accuracy.*", "",
         "## Overall (all types)", "", "| Configuration | Types | Valid + typed (distinct) | of which microbiome-relevant | Quality | Valid + typed mentions | Papers |",
         "|---|---:|---:|---:|---:|---:|---:|"]
    for cfg, d in sorted(tot.items(), key=lambda kv: -kv[1]["valid_typed_distinct"]):
        L.append(f"| {cfg} | {d['types']} | {d['valid_typed_distinct']:,} | {d['valid_typed_microbiome_distinct']:,} | "
                 f"{d['quality_pct']}% | {d['valid_typed_mentions']:,} | {d['papers_with_valid_typed']} |")
    for t in TYPES:
        sub = sorted((r for r in rows if r["type"] == t and r["distinct_judged"] >= 20), key=lambda r: -r["valid_typed_distinct"])
        if not sub:
            continue
        L += ["", f"## {t}", "", "| Configuration | Valid + typed (distinct) | Quality [95% CI] | Papers |", "|---|---:|---:|---:|"]
        L += [f"| {r['config']} | {r['valid_typed_distinct']:,} | {r['quality_pct']}% [{r['quality_wilson'][0]}–{r['quality_wilson'][1]}] | "
              f"{r['papers_with_valid_typed']} |" for r in sub[:12]]
    (OUT / "REPORT.md").write_text("\n".join(L) + "\n")
    print("\n".join(L[:40]))


if __name__ == "__main__":
    main()
