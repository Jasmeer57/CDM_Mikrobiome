"""Species benchmark (S1000, test split): the fair-benchmark models on organism names. Approved 2026-11-05.

Same models, label handling, GLiNER threshold selection on dev, LLM prompts (zero-shot and 3-shot from train) and
scoring as fairbench.py; only the dataset differs. fairbench.py and its frozen BC5CDR/BioRED predictions are not
modified: this module patches the dataset tables at import and writes to outputs/results/benchmark/ner_species_s1000/.

Data: S1000 corpus v1.1 (Luoma et al., Bioinformatics 2023, doi:10.1093/bioinformatics/btad369; Zenodo 10285825,
CC BY 4.0), the re-annotated and extended successor of S800, official train/dev/test split (700/100/200 abstracts),
data/benchmarks_ner/raw/s1000/. Gold = every Species, Genus and Strain span, scored as one type "Organism" (the CDM
ORGANISM type); discontinuous spans are skipped. Trained models are scored through their organism label only
(HunFlair2 ORGANISM, scispaCy CRAFT TAXON, scispaCy BioNLP13CG ORGANISM, PubTator3 Species); models without an
organism label are not run. In-domain training on S800/S1000 is not asserted for any model here; check model cards
before claiming an in-domain advantage.

    BENCH=species_bench GROUP=cpu sbatch -p intelsr_short src/scripts/ner_fair_bench/classic.sbatch
    BENCH=species_bench GROUP=gpu sbatch -p mlgpu_short --gres=gpu:a40:1 src/scripts/ner_fair_bench/classic.sbatch
    BENCH=species_bench sbatch -p mlgpu_short --gres=gpu:a40:1 --array=0-5 src/scripts/ner_fair_bench/llm.sbatch
    python species_bench.py pubtator ; python species_bench.py score
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import fairbench as F

DS = "s1000"
DATA = F.ROOT / "data/benchmarks_ner/raw/s1000/S1000-corpus/entire-corpus"
F.OUT = F.ROOT / "outputs/results/benchmark/ner_species_s1000"
F.PRED = F.OUT / "preds"
F.TYPES[DS] = ["Organism"]
F.TYPE_DEFS["Organism"] = ("organisms: names of species, genera and strains, including common names such as human, "
                           "mouse or rat")
F.GLINER_LABEL["Organism"] = "organism"
ORG = {"hunflair2": {"ORGANISM": "Organism"}, "scispacy_craft": {"TAXON": "Organism"},
       "scispacy_bionlp13cg": {"ORGANISM": "Organism"}, "pubtator3": {"Species": "Organism"}}
for name, m in F.RAW_MAP.items():
    m[DS] = ORG.get(name, {})
GOLD_TYPES = {"Species", "Genus", "Strain"}
_load = F.load


def load(ds, split="test"):
    if ds != DS:
        return _load(ds, split)
    docs, bad = [], 0
    for txt in sorted((DATA / split).glob("*.txt")):
        text = txt.read_text(encoding="utf-8").replace("\n", " ")
        gold = []
        ann = txt.with_suffix(".ann")
        for line in (ann.read_text(encoding="utf-8").splitlines() if ann.exists() else []):
            if not line.startswith("T"):
                continue
            _, spec, mention = line.split("\t")
            typ, *offs = spec.split(" ")
            if typ not in GOLD_TYPES or ";" in spec:
                continue
            s, e = int(offs[0]), int(offs[-1])
            # 10 test spans carry a mojibake copy of a no-break space ("H.\u00c2\u00a0lepturus") in the .ann text only;
            # the offsets are right, so the text span is used as the mention
            bad += text[s:e] != mention.replace("\n", " ").replace("\u00c2\u00a0", "\u00a0")
            gold.append((s, e, "Organism", text[s:e]))
        docs.append((txt.stem, text, gold))
    if bad:
        raise SystemExit(f"{DS}/{split}: {bad} gold offsets do not match the text")
    return docs


F.load = load


def realign(d, text, window=300):
    """PubTator3 offsets refer to the current PubMed text, which differs slightly from the corpus copy for some
    abstracts: each span is moved to the nearest exact occurrence of its own string (within +-window characters),
    and dropped if there is none. Counts are reported."""
    out, kept, moved, dropped = {}, 0, 0, 0
    for pm, ps in d.items():
        t, new = text.get(pm, ""), []
        for x in ps:
            s, e, s_txt = x["start"], x["end"], x.get("text") or ""
            if t[s:e] == s_txt:
                new.append(x)
                kept += 1
                continue
            best, i = None, t.find(s_txt, max(0, s - window))
            while s_txt and i != -1 and i <= s + window:
                if best is None or abs(i - s) < abs(best - s):
                    best = i
                i = t.find(s_txt, i + 1)
            if best is None:
                dropped += 1
            else:
                new.append({**x, "start": best, "end": best + len(s_txt)})
                moved += 1
        out[pm] = new
    return out, {"exact": kept, "moved_to_nearest_occurrence": moved, "dropped": dropped}


def score():
    docs = load(DS)
    types = F.TYPES[DS]
    res, rows = {}, {}
    for p in sorted(F.PRED.glob(f"{DS}__*.jsonl")):
        name = p.stem.split("__", 1)[1]
        if not (name in F.ZERO_SHOT or name.startswith("llm_") or ORG.get(name)):
            continue                                   # no organism label: not scored
        meta, d = F.read_preds(p)
        if name == "pubtator3":
            d, meta["realigned"] = realign(d, {pm: tx for pm, tx, _ in docs})
        pred = F.project(list(d.items()), name, DS, meta.get("threshold"))
        rows[name] = F.micro(docs, pred, types, per_doc=True)
        m = F.agg(rows[name], types)
        res[name] = {"meta": meta, "exact": m["exact"], "relaxed": m["relaxed"], "exact_ci": F.boot(rows[name], types)}
    best = max(res, key=lambda n: res[n]["exact"]["F1"])
    for n in res:
        res[n]["p_vs_best"] = None if n == best else F.paired_p(rows[best], rows[n], types)
    F.OUT.mkdir(parents=True, exist_ok=True)
    (F.OUT / "species_metrics.json").write_text(json.dumps(res, indent=1, default=float) + "\n")
    ng = sum(len(g) for _, _, g in docs)
    L = ["# Species benchmark: S1000 test split (organism names)", "",
         f"S1000 v1.1 test split: {len(docs)} abstracts, {ng:,} organism spans (Species, Genus, Strain). Exact = same span; "
         "relaxed = overlapping span. 95% CI by document bootstrap; one-sided paired bootstrap p against the best model.", "",
         "| model | kind | exact F1 [95% CI] | relaxed F1 | P | R | p vs best | s/doc |", "|---|---|---|---:|---:|---:|---:|---:|"]
    f = lambda x: f"{100 * x:.1f}"
    for n, v in sorted(res.items(), key=lambda kv: -kv[1]["exact"]["F1"]):
        lo, hi = v["exact_ci"]
        pv = "best" if v["p_vs_best"] is None else f"{v['p_vs_best']:.3f}"
        L.append(f"| {n} | {v['meta'].get('kind', '')} | {f(v['exact']['F1'])} [{f(lo)}–{f(hi)}] | {f(v['relaxed']['F1'])} | "
                 f"{f(v['exact']['P'])} | {f(v['exact']['R'])} | {pv} | {v['meta'].get('sec_per_doc', '')} |")
    (F.OUT / "SPECIES_BENCHMARK.md").write_text("\n".join(L) + "\n")
    print("\n".join(L))


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "score":
        return score()
    if argv and argv[0] == "check":
        for split in ("train", "dev", "test"):
            d = load(DS, split)
            print(split, len(d), "docs", sum(len(g) for _, _, g in d), "organism spans")
        return
    if "--datasets" not in argv:
        argv += ["--datasets", DS]
    return F.main(argv)


if __name__ == "__main__":
    main()
