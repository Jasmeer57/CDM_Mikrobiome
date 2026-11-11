"""Score the Microbiome-CDM relation-typing step (retype-v3.1, Qwen3.5-9B AWQ, zero-shot) against MiDRED (Hogan et al.,
BioNLP 2024; huggingface.co/datasets/shangdatalab-ucsd/midred @20c3228b, CC BY 4.0): 3,116 human-annotated
microbe-disease relation instances (double annotation + adjudication, Fleiss kappa 0.710), 4 classes
(connecting / contrasting / pathogen / no relation).

Our 89 labels are mapped to the 4 MiDRED classes (MD_MAP below; class definitions from the MiDRED paper, Table 6/7):
  pathogen     <- CAUSES, TRIGGERS_INFLAMMATION, INDUCES_IMMUNE_RESPONSE (microbe is the causative agent)
  contrasting  <- protective / lower-in-disease / inhibiting labels (CONTRASTING set)
  no relation  <- NULL_FINDING with a negation cue, and every non-verified answer (NOT_SUPPORTED, BAD_ENDPOINT, unverified)
  connecting   <- ASSOCIATION_UNSIGNED with its cue found, and every other verified specific label (association, risk
                  factor, higher in disease, colonises ...)
Metrics: 4-class micro-F1 (= accuracy, Wilson CI) and macro-F1 (bootstrap CI), per-class P/R/F1, and a collapsed
3-class view (positive = connecting+pathogen / contrasting / no relation). Test split (n=500) reported next to the
published baselines (BioLinkBERT-large fine-tuned 0.905, GPT-4 in-context 0.721 micro-F1); all splits (n=3,116) as the
zero-shot estimate.

Inputs : outputs/results/competitor_compare_2026-11-11/llm_runs/rel/*.jsonl (rows with ds == "midred")
Outputs: outputs/results/competitor_compare_2026-11-11/midred/{SUMMARY.json, REPORT.md}
Written with Claude Code (declare).
"""
from __future__ import annotations

import glob
import json
import os
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _cstats import RESULTS, confusion, dump, macro_f1_boot, wilson  # noqa: E402

RUNS = Path(os.environ.get("CMP_RUNS", RESULTS / "llm_runs"))
OUT = Path(os.environ.get("CMP_OUT", RESULTS / "midred"))
PATHOGEN = {"CAUSES", "TRIGGERS_INFLAMMATION", "INDUCES_IMMUNE_RESPONSE"}
CONTRASTING = {"PREVENTS", "PROTECTIVE_AGAINST", "NEGATIVELY_ASSOCIATED_WITH", "DECREASED_IN", "SUPPRESSES", "INHIBITS",
               "ALLEVIATES", "TREATS", "IMPROVES", "DOWNREGULATES", "NEGATIVELY_REGULATES", "ENHANCES_BARRIER",
               "LESS_ABUNDANT_THAN", "DECREASES_OVER_TIME"}
# polarity sets shared with minerva_compare.py (microbe -> disease)
POSITIVE = PATHOGEN | {"INCREASED_IN", "POSITIVELY_ASSOCIATED_WITH", "PROMOTES", "EXACERBATES", "INCREASES_RISK_OF", "IMPAIRS",
                       "CONTRIBUTES_TO", "UPREGULATES", "MORE_ABUNDANT_THAN", "INCREASES_OVER_TIME", "ACTIVATES",
                       "POSITIVELY_REGULATES"}


def md_class(r):
    if r["relation"] == "NULL_FINDING" and r.get("cue_found"):
        return "no relation"
    if r["relation"] == "ASSOCIATION_UNSIGNED" and r.get("cue_found"):
        return "connecting"                  # stated link without sign = MiDRED "associated with"
    if not r.get("specific_verified"):
        return "no relation"
    if r["relation"] in PATHOGEN:
        return "pathogen"
    if r["relation"] in CONTRASTING:
        return "contrasting"
    return "connecting"


def load(ds):
    """Prediction rows of one dataset, one per item id: the last parsed answer wins (resumed runs may repeat UNPARSED
    items); truncated lines are skipped."""
    best = {}
    for f in sorted(glob.glob(str(RUNS / "rel/*.jsonl"))):
        for line in open(f, encoding="utf-8"):
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r["ds"] == ds and (r["id"] not in best or r["relation"] != "UNPARSED"):
                best[r["id"]] = r
    return list(best.values())


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    rows = load("midred")
    L4 = ["connecting", "contrasting", "pathogen", "no relation"]
    col = {"connecting": "positive", "pathogen": "positive", "contrasting": "contrasting", "no relation": "no relation"}
    summ = {"source": "huggingface.co/datasets/shangdatalab-ucsd/midred revision 20c3228b (2024-07-02), CC BY 4.0",
            "reference_type": "human-annotated gold standard (double annotation, adjudicated; Fleiss kappa 0.710)",
            "n_rows": len(rows), "unparsed": sum(1 for r in rows if r["relation"] == "UNPARSED"),
            "mapping": {"pathogen": sorted(PATHOGEN), "contrasting": sorted(CONTRASTING),
                        "no relation": "NULL_FINDING(cue found) + any non-verified answer",
                        "connecting": "ASSOCIATION_UNSIGNED(cue found) + all other verified labels"}}
    for split in ("all", "test"):
        R = [r for r in rows if split == "all" or r["split"] == split]
        pairs = [(r["gold"][0]["label"], md_class(r)) for r in R]
        summ[split] = {"four_class": macro_f1_boot(pairs, L4),
                       "collapsed_three_class": macro_f1_boot([(col[g], col[p]) for g, p in pairs], ["positive", "contrasting", "no relation"]),
                       "confusion_gold_vs_pred": confusion(pairs),
                       "sign_agreement_when_both_signed": wilson(
                           sum(1 for g, p in pairs if g != "no relation" and p != "no relation" and col[g] == col[p]),
                           sum(1 for g, p in pairs if g != "no relation" and p != "no relation")),
                       "abstained_on_gold_relation": wilson(sum(1 for g, p in pairs if g != "no relation" and p == "no relation"),
                                                            sum(1 for g, p in pairs if g != "no relation")),
                       "our_raw_label_distribution": dict(Counter(r["relation"] for r in R).most_common(25))}
    summ["published_baselines_test_micro_f1"] = {"BioLinkBERT-large (fine-tuned)": 0.905, "PubMedBERT-base (fine-tuned)": 0.861,
                                                 "GPT-4 (in-context)": 0.721, "GPT-3.5 (in-context)": 0.552,
                                                 "source": "Hogan et al. 2024, Table 4"}
    dump(summ, OUT / "SUMMARY.json")
    for s in ("all", "test"):
        print(s, summ[s]["four_class"]["accuracy_micro_f1"], summ[s]["four_class"]["macro_f1"], summ[s]["collapsed_three_class"]["accuracy_micro_f1"])


if __name__ == "__main__":
    main()
