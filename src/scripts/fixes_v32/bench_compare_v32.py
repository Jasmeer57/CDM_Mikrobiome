"""Score layer 3.2.0-candidate on DiMB-RE, MiDRED and MINERVA labelled sentences with the UNCHANGED comparison code
(src/scripts/competitors/{dimb_re,midred,minerva}_compare.py, _cstats.py), side by side with the v3.1 run.

    python src/scripts/fixes_v32/bench_compare_v32.py

Run sets (PREREGISTRATION.md section 3):
  v31          original llm_runs of competitor_compare_2026-11-11 (re-scored: reproducibility check vs its SUMMARY.json)
  v31_filter   v31 answers, replaced by CO_OCCURRENCE_ONLY where the frozen syntactic filter fails (post hoc, Fix B only)
  v32          new run (fixes_v32_2026-11-11/bench/rel): Fix A labels + open cue + Fix B filter
The only code change is the pre-registered in-place mapping of the new labels (NEWMAP below). Open-cue and
CO_OCCURRENCE_ONLY answers are abstentions (specific_verified false) everywhere.
Outputs: outputs/results/fixes_v32_2026-11-11/bench_scored/<run>/{dimb_re,midred,minerva}/SUMMARY.json and
COMPARISON.{json,md}. Written with Claude Code (declare).
"""
from __future__ import annotations

import glob
import importlib
import json
import os
import sys
from collections import Counter
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
COMP = ROOT / "src/scripts/competitors"
sys.path.insert(0, str(COMP))
D = ROOT / "outputs/results/fixes_v32_2026-11-11"
OLD = ROOT / "outputs/results/competitor_compare_2026-11-11"
S = D / "bench_scored"
RUNS = {"v31": OLD / "llm_runs", "v31_filter": S / "v31_filter_runs", "v32": D / "bench"}


def make_v31_filter():
    syn = {j["id"]: j for j in (json.loads(l) for l in open(D / "parse/bench_parse.jsonl", encoding="utf-8"))}
    out = RUNS["v31_filter"] / "rel"
    out.mkdir(parents=True, exist_ok=True)
    for f in sorted(glob.glob(str(RUNS["v31"] / "rel/*.jsonl"))):
        with open(out / Path(f).name, "w", encoding="utf-8") as g:
            for line in open(f, encoding="utf-8"):
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                s = syn[r["id"]]
                r["syntax_status"], r["syntax_connected"] = s["status"], s["connected"]
                if s["connected"] is False:
                    r.update(relation="CO_OCCURRENCE_ONLY", cue="", cue_found=False, specific_verified=False, direction="SAME")
                g.write(json.dumps(r, ensure_ascii=False) + "\n")


def score(run):
    """Import the comparison modules fresh with CMP_RUNS set, apply NEWMAP in place, run the scoring."""
    os.environ["CMP_RUNS"] = str(RUNS[run])
    for m in ("_cstats", "midred_compare", "dimb_re_compare", "minerva_compare"):
        sys.modules.pop(m, None)
    mid = importlib.import_module("midred_compare")
    dimb = importlib.import_module("dimb_re_compare")
    minv = importlib.import_module("minerva_compare")
    # --- pre-registered mapping of the corpus-derived labels (PREREGISTRATION.md section 3) ---
    dimb.MAP.update({"INCLUDES": ("HAS_COMPONENT", False), "RESULTS_IN": ("CAUSES", False),
                     "ATTRIBUTED_TO": ("CAUSES", True), "CHARACTERIZED_BY": ("ASSOCIATED_WITH", False)})
    for lab in ("RESULTS_IN", "ATTRIBUTED_TO"):
        mid.PATHOGEN.add(lab)
        mid.POSITIVE.add(lab)          # same set object as minerva_compare.POSITIVE
    assert minv.POSITIVE is mid.POSITIVE
    out = S / run
    dimb.OUT = out / "dimb_re"
    dimb.RUNS = RUNS[run]
    dimb.score_ner = lambda split: (_ for _ in ()).throw(FileNotFoundError())   # entities unchanged; not re-scored
    dimb.main()
    mid.OUT = out / "midred"
    mid.main()
    minv.OUT = out / "minerva"
    minv.OUT.mkdir(parents=True, exist_ok=True)
    from _cstats import dump
    dump({"gold_sentences": minv.gold_part()}, minv.OUT / "SUMMARY.json")
    rows = {ds: mid.load(ds) for ds in ("dimb", "midred", "minerva")}
    extra = {}
    for ds, R in rows.items():
        gold_rel = (lambda r: bool(r["gold"])) if ds == "dimb" else (
            (lambda r: r["gold"][0]["label"] != "no relation") if ds == "midred" else
            (lambda r: r["gold"][0]["label"] in ("positive", "negative")))
        c = Counter((r["relation"] if r["relation"] in ("CO_OCCURRENCE_ONLY", "OTHER_STATED_RELATION") else "other",
                     "gold_relation" if gold_rel(r) else "gold_none") for r in R)
        extra[ds] = {"n": len(R), "co_occurrence_only": {"on_gold_relation": c[("CO_OCCURRENCE_ONLY", "gold_relation")],
                                                         "on_gold_none": c[("CO_OCCURRENCE_ONLY", "gold_none")]},
                     "open_cue_verified": sum(1 for r in R if r.get("open_cue_verified")),
                     "open_cue_verified_on_gold_relation": sum(1 for r in R if r.get("open_cue_verified") and gold_rel(r)),
                     "new_label_specific": dict(Counter(r["relation"] for r in R if r.get("specific_verified") and r["relation"] in NEW)),
                     "unparsed": sum(1 for r in R if r["relation"] == "UNPARSED")}
    return extra


NEW = {l["label"] for l in json.load(open(D / "labels_v32.json"))["labels"]}


def pick(run):
    j = lambda p: json.load(open(p))
    dm = j(S / run / "dimb_re/SUMMARY.json")["relations"]
    md = j(S / run / "midred/SUMMARY.json")
    mv = j(S / run / "minerva/SUMMARY.json")["gold_sentences"]
    out = {}
    for sp in ("all", "test"):
        a1 = dm[sp]["A1_typing_on_gold_pairs"]
        a2 = dm[sp]["A2_extraction_within_sentence"]["schema_filtered"]
        out[f"dimb_{sp}"] = {"typed_P": a2["typed"]["precision"], "typed_R": a2["typed"]["recall"], "typed_F1": a2["typed"]["f1"],
                             "detect_P": a2["detection"]["precision"], "detect_R": a2["detection"]["recall"], "detect_F1": a2["detection"]["f1"],
                             "typed_all_answers_F1": dm[sp]["A2_extraction_within_sentence"]["all_answers"]["typed"]["f1"],
                             "typed_strict_incl_cross_sentence_F1": dm[sp]["A2_typed_schema_filtered_incl_cross_sentence_as_missed"]["f1"],
                             "exact_label_dir_on_gold_pairs": a1["exact_label_and_direction"],
                             "exact_given_detected": a1["exact_label_and_direction_given_detected"],
                             "polarity_agreement_given_detected": a1["polarity_agreement_given_detected"],
                             "detected_any_on_gold_pairs": a1["detected_any_relation"],
                             "detected_in_dimb_scheme_on_gold_pairs": a1["detected_relation_in_dimb_scheme"]}
        out[f"midred_{sp}"] = {"micro_f1": md[sp]["four_class"]["accuracy_micro_f1"], "macro_f1": md[sp]["four_class"]["macro_f1"],
                               "three_class_micro_f1": md[sp]["collapsed_three_class"]["accuracy_micro_f1"],
                               "sign_agreement_when_both_signed": md[sp]["sign_agreement_when_both_signed"],
                               "abstained_on_gold_relation": md[sp]["abstained_on_gold_relation"],
                               "per_class": {k: {x: v[x] for x in ("precision", "recall", "f1")} for k, v in md[sp]["four_class"]["per_class"].items()}}
    out["minerva"] = {"accuracy": mv["three_class"]["accuracy_micro_f1"], "macro_f1": mv["three_class"]["macro_f1"],
                      "sign_agreement_when_both_signed": mv["sign_agreement_when_both_signed"],
                      "abstained_on_signed_gold": mv["abstained_on_signed_gold"],
                      "per_class": {k: {x: v[x] for x in ("precision", "recall", "f1")} for k, v in mv["three_class"]["per_class"].items()}}
    return out


def fmt(v):
    if isinstance(v, dict) and "value" in v:
        return f"{v['value']:.3f} [{v['boot_lo']:.3f}-{v['boot_hi']:.3f}]"
    if isinstance(v, dict) and "p" in v:
        return f"{v['p']:.3f} ({v['k']}/{v['n']}) [{v['lo']:.3f}-{v['hi']:.3f}]" if v["n"] else "n/a"
    return str(v)


def main():
    make_v31_filter()
    extra = {run: score(run) for run in RUNS}
    res = {run: pick(run) for run in RUNS}
    old = json.load(open(OLD / "dimb_re/SUMMARY.json"))["relations"]["all"]["A2_extraction_within_sentence"]["schema_filtered"]["typed"]["f1"]["value"]
    oldm = json.load(open(OLD / "midred/SUMMARY.json"))["all"]["four_class"]["accuracy_micro_f1"]["p"]
    repro = {"dimb_typed_f1_published_vs_rescored": [old, res["v31"]["dimb_all"]["typed_F1"]["value"]],
             "midred_micro_f1_published_vs_rescored": [oldm, res["v31"]["midred_all"]["micro_f1"]["p"]]}
    comp = {"reproducibility": repro, "metrics": res, "abstention_and_new_labels": extra}
    (S / "COMPARISON.json").write_text(json.dumps(comp, indent=1) + "\n", encoding="utf-8")
    md = ["# Relation evaluation: v3.1 vs v3.1 + filter vs v3.2 (95% CIs: bootstrap over documents for P/R/F1, Wilson for proportions)", "",
          f"Reproducibility (published vs re-scored v3.1): {repro}", ""]
    for blk in ("dimb_all", "dimb_test", "midred_all", "midred_test", "minerva"):
        md += [f"## {blk}", "", "| metric | v3.1 | v3.1 + filter | v3.2 |", "|---|---|---|---|"]
        for k in res["v31"][blk]:
            if k == "per_class":
                continue
            md.append(f"| {k} | " + " | ".join(fmt(res[r][blk][k]) for r in RUNS) + " |")
        md.append("")
    md += ["## Abstentions and new labels", "", "```", json.dumps(extra, indent=1), "```"]
    (S / "COMPARISON.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    main()
