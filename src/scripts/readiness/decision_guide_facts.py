"""Decision-guide fact sheet (entity type x program) for the BiB manuscript's Table 3 / Recommendations.

Facts only, for the authors to write from (BiB forbids LLM-drafted text and tables). Reads frozen outputs, writes a new
dated directory; nothing frozen is modified. Every value is copied or derived arithmetically from:

  outputs/results/ner_fair_bench/fair_ner_metrics.json          public gold-standard F1 (BioRED, BC5CDR) + bootstrap CI
  outputs/results/benchmark/ner_species_s1000/species_metrics.json  S1000 organism F1 + CI (contamination caveats below)
  outputs/results/ner_corpus_bench/corpus_metrics.json          corpus grounding (precision proxy, no gold standard)
  paper/publication/final_validation/benchmark/benchmark_analysis.json  Spearman rho, BioRED F1 vs corpus grounding
  outputs/results/benchmark/llm_judge_deepseek_v4_flash/summary.json   model-judged validity (screen, not accuracy)
  paper/publication/final_validation/MANUSCRIPT_CLAIMS_REGISTER.csv     which numbers are already registered

    python src/scripts/readiness/decision_guide_facts.py [--out DIR]
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import date
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
SRC = {
    "fair": ROOT / "outputs/results/ner_fair_bench/fair_ner_metrics.json",
    "s1000": ROOT / "outputs/results/benchmark/ner_species_s1000/species_metrics.json",
    "corpus": ROOT / "outputs/results/ner_corpus_bench/corpus_metrics.json",
    "analysis": ROOT / "paper/publication/final_validation/benchmark/benchmark_analysis.json",
    "judge": ROOT / "outputs/results/benchmark/llm_judge_deepseek_v4_flash/summary.json",
    "register": ROOT / "paper/publication/final_validation/MANUSCRIPT_CLAIMS_REGISTER.csv",
}
# BioRED type -> (short label, BC5CDR per-type key or None, S1000 applies?)
TYPES = {
    "DiseaseOrPhenotypicFeature": ("Disease", "Disease", False),
    "ChemicalEntity": ("Chemical", "Chemical", False),
    "GeneOrGeneProduct": ("Gene/protein", None, False),
    "OrganismTaxon": ("Organism", None, True),
    "SequenceVariant": ("Variant", None, False),
    "CellLine": ("Cell line", None, False),
}


def pct(x):
    return None if x is None else round(100 * x, 1)


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path,
                    default=ROOT / f"outputs/results/benchmark/decision_guide_facts_{date.today().isoformat()}")
    a = ap.parse_args()
    fair, s1000, corpus, analysis, judge = (json.load(open(SRC[k])) for k in ("fair", "s1000", "corpus", "analysis",
                                                                              "judge"))
    corpus = corpus["models"]
    reg = list(csv.DictReader(open(SRC["register"], encoding="utf-8")))

    programs = sorted({k.split("__", 1)[1] for k in fair})
    rows = []
    for prog in programs:
        bi, bc = fair.get(f"biored__{prog}"), fair.get(f"bc5cdr__{prog}")
        cm = corpus.get(prog, {})
        jd = judge["benchmark"].get(prog, {}).get("distinct")
        for t, (lab, bc_key, s_app) in TYPES.items():
            r = {"program": prog, "kind": (bi or bc or {}).get("meta", {}).get("kind"), "entity_type": lab}
            pt = (bi or {}).get("per_type", {}).get(t)
            if pt:
                r |= {"biored_exact_f1": pct(pt["exact"]["F1"]), "biored_ci_lo": pct(pt["ci"][0]),
                      "biored_ci_hi": pct(pt["ci"][1]), "biored_exact_p": pct(pt["exact"]["P"]),
                      "biored_in_domain_training": bi.get("in_domain_training")}
            if bc_key and bc and bc_key in bc.get("per_type", {}):
                q = bc["per_type"][bc_key]
                r |= {"bc5cdr_exact_f1": pct(q["exact"]["F1"]), "bc5cdr_ci_lo": pct(q["ci"][0]),
                      "bc5cdr_ci_hi": pct(q["ci"][1]), "bc5cdr_in_domain_training": bc.get("in_domain_training")}
            if s_app and prog in s1000:
                s = s1000[prog]
                r |= {"s1000_exact_f1": pct(s["exact"]["F1"]), "s1000_ci_lo": pct(s["exact_ci"][0]),
                      "s1000_ci_hi": pct(s["exact_ci"][1]), "s1000_p_vs_best": s.get("p_vs_best")}
            g = cm.get("grounding", {}).get(t)
            if g:
                r |= {"corpus_grounded_pct": g["grounded_pct"], "corpus_unique_strings": g["unique"]}
            if len(r) > 3:
                if jd:  # program-level, all types together: repeated per row, flagged as such
                    r["judge_valid_and_typed_pct_program_level"] = round(100 * jd["valid_type"] / jd["d"], 1)
                r["biored_sec_per_doc"] = (bi or {}).get("meta", {}).get("sec_per_doc")
                rows.append(r)

    best = {}
    for t, (lab, _, _) in TYPES.items():
        cand = [r for r in rows if r["entity_type"] == lab and r.get("biored_exact_f1") is not None]
        if cand:
            b = max(cand, key=lambda r: r["biored_exact_f1"])
            # configurations whose 95% CI upper bound reaches the best point estimate (descriptive, not a test)
            near = sorted({r["program"] for r in cand if r["biored_ci_hi"] >= b["biored_exact_f1"]} - {b["program"]})
            best[lab] = {"best": b["program"], "f1": b["biored_exact_f1"], "ci": [b["biored_ci_lo"], b["biored_ci_hi"]],
                         "in_domain": b.get("biored_in_domain_training"), "ci_reaches_best": near, "n": len(cand)}

    rho = analysis["public_vs_corpus"]["correlation"]
    reg_ids = {"DiseaseOrPhenotypicFeature": "H04", "OrganismTaxon": "H05"}

    a.out.mkdir(parents=True, exist_ok=True)
    cols = ["program", "kind", "entity_type", "biored_exact_f1", "biored_ci_lo", "biored_ci_hi", "biored_exact_p",
            "biored_in_domain_training", "bc5cdr_exact_f1", "bc5cdr_ci_lo", "bc5cdr_ci_hi",
            "bc5cdr_in_domain_training", "s1000_exact_f1", "s1000_ci_lo", "s1000_ci_hi", "s1000_p_vs_best",
            "corpus_grounded_pct", "corpus_unique_strings", "judge_valid_and_typed_pct_program_level",
            "biored_sec_per_doc"]
    with open(a.out / "decision_guide_matrix.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)

    L = [f"# Decision-guide facts (entity type x program), {date.today().isoformat()}", "",
         "Facts only, for the authors to write Table 3 and the Recommendations from. Not manuscript text. "
         "Generated by `src/scripts/readiness/decision_guide_facts.py` from frozen outputs (hashes at the end); "
         "full matrix in `decision_guide_matrix.csv`.", "",
         "## Rules the guide must follow (from the publication rules and the 2026-11-06 review)", "",
         "- Recommend programs **only from public gold-standard F1** (BioRED, BC5CDR; S1000 with its caveats). "
         "These are the only columns with a gold standard.",
         "- Corpus grounding is a **precision proxy** on the 453-paper corpus, not accuracy: share of a program's "
         "unique strings of a type found in that type's reference vocabulary (NCBI Gene; CTD-MEDIC/MeSH, Mondo, HPO; "
         "CTD/MeSH chemicals; NCBI Taxonomy; variant syntax). Real entities can be missing; junk can match.",
         "- The judge column is a **model-judged screen** (DeepSeek-V4-Flash, valid and correctly typed, distinct "
         "strings, all types of that program together), never accuracy. It is program-level and repeated on each row.",
         "- Nothing here supports \"LLMs beat NLP methods\" (prohibited claim).",
         "- Public F1 is not corpus accuracy. Any number used in the text must first be added to the claims register "
         "(only the IDs listed below are registered).", "",
         "## Best configuration per entity type on BioRED (exact F1, %, 95% bootstrap CI)", "",
         "`CI reaches best` = configurations whose CI upper bound reaches the best point estimate. Descriptive only; "
         "it is not a significance test (paired tests exist only at full-schema level, `p_vs_best`).", "",
         "| Type | n configs | Best | F1 [CI] | Best trained in-domain? | CI reaches best |", "|---|---|---|---|---|---|"]
    for lab, b in best.items():
        L.append(f"| {lab} | {b['n']} | {b['best']} | {b['f1']} [{b['ci'][0]}–{b['ci'][1]}] | {b['in_domain']} | "
                 f"{', '.join(b['ci_reaches_best']) or '—'} |")
    L += ["", "## What rho correlates (Spearman, across configurations)", "",
          "For each type: across the configurations that emit it, the rank correlation between **BioRED exact F1 "
          "for that type** and **corpus grounding % for that type**. High rho = public benchmark rank predicts which "
          "programs produce vocabulary-resolvable strings on this corpus; low rho = it does not. It is not a "
          "correlation with corpus accuracy (none exists).", "",
          "| Type | n configs | rho (F1 vs grounding) | rho (precision vs grounding) | Register |", "|---|---|---|---|---|"]
    for t, v in rho.items():
        L.append(f"| {TYPES.get(t, (t,))[0]} | {v['n_models']} | {v['spearman_f1_vs_grounding']} | "
                 f"{v['spearman_precision_vs_grounding']} | {reg_ids.get(t, 'not registered')} |")
    L += ["", "## Caveats that must travel with the numbers", "",
          "- **In-domain training:** `*_in_domain_training = True` means the program was trained on that benchmark "
          "(or its source corpus); its F1 is not a transfer estimate. Flag these in any table.",
          "- **S1000 contamination:** AIONER (PubTator3's tagger) training data contain 134 of the 200 S1000 test "
          "abstracts; HunFlair2's overlap cannot be determined; the S1000 test set is 160 S800 test abstracts + 40 new. "
          "On the 40 unseen abstracts no difference between PubTator3, Qwen 3-shot and HunFlair2 is detected "
          "(`ner_species_s1000/subset_s800_vs_new.json`). Do not rank organism taggers on S1000 alone.",
          "- **Organism:** rho = 0.023 (H05): public F1 rank says nothing about corpus grounding for organisms, the "
          "type that matters most for a microbiome corpus. Grounding misses abbreviated binomials, strain suffixes and "
          "rank prefixes for every program equally (`ner_corpus_bench/MEASUREMENT_NOTES.md`).",
          "- **MeSH dictionary:** adds no unique term (source ablation, 2026-11-05); not in this matrix.",
          "- **Coverage:** 9 of the 14 CDM types have no public benchmark (component audit); the guide can only speak "
          "for disease, chemical, gene, organism, variant, cell line.",
          "- **Judge:** κ between model judges is low (J05 0.282 on catalogue values; 0.283 Qwen vs DeepSeek on terms, "
          "unregistered); one judge's verdicts are a screen, not ground truth.", "",
          "## Already registered numbers relevant to the guide", "", "| ID | Claim | Value | Source |", "|---|---|---|---|"]
    for r in reg:
        if r["claim_id"] in ("H03", "H04", "H05", "H06", "H07") or r["claim_id"].startswith("L0"):
            L.append(f"| {r['claim_id']} | {r['claim']} | {r['stated']} | {r['source']} |")
    L += ["", "## Inputs (SHA-256)", ""] + [f"- `{p.relative_to(ROOT)}` {sha(p)[:16]}…" for p in SRC.values()]
    (a.out / "DECISION_GUIDE_FACTS.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    json.dump({"generated": date.today().isoformat(), "rows": len(rows), "best_biored": best, "rho": rho,
               "inputs": {k: sha(p) for k, p in SRC.items()}}, open(a.out / "summary.json", "w"), indent=1)
    print("written:", a.out, len(rows), "rows")


if __name__ == "__main__":
    main()
