"""Score the Microbiome-CDM LLM steps against the DiMB-RE human-annotated corpus (Hong et al., JAMIA 2025,
doi 10.1093/jamia/ocaf054; data github.com/ScienceNLP-Lab/DiMB-RE @03012c9, ner_reduced_v6.1_trg_abs; 165 papers).

DiMB-RE is a human gold standard (double annotation, adjudicated). Our steps are zero-shot (no DiMB data used for prompt
design), so all splits are evaluation data; the test split (37 docs) is also reported for orientation next to the
published fine-tuned baselines (NER F1 0.800, end-to-end RE F1 0.445 on test; those are NOT directly comparable:
different task set-up, see REPORT.md).

A. Relations (task rel of competitor_llm_runner.py, CDM retype-v3.1 pipeline unchanged, gold entities given):
   A1 typing of gold related pairs: our label mapped to the 13 DiMB labels (MAP below); exact label (+ direction for
      directional labels) accuracy, polarity agreement, and detection (did we assert any relation).
   A2 relation extraction over ALL within-sentence gold-entity pairs (negatives included): detection P/R/F1 and typed
      P/R/F1; strict variant also counts the 320 cross-sentence gold relations as misses.
   CIs: cluster bootstrap over documents (2,000 resamples) for P/R/F1; Wilson for proportions.
B. Entities (task ner): CDM 14-type prompt; gold types mapped to CDM types where a mapping exists
   (Microorganism->ORGANISM, Disease->DISEASE, Chemical/Nutrient/Metabolite->CHEMICAL, Enzyme->PROTEIN,
   Gene->PROTEIN|DNA_RNA). Food, DietPattern, Physiology, Measurement, DiversityMetric have no CDM counterpart and are
   reported as span recall only.

Inputs : outputs/scratch/competitors/dimb_re/raw/*.json; outputs/results/competitor_compare_2026-11-11/llm_runs/{rel,ner}/
Outputs: outputs/results/competitor_compare_2026-11-11/dimb_re/{SUMMARY.json, REPORT.md, rel_predictions.csv}
Written with Claude Code (declare).
"""
from __future__ import annotations

import csv
import os
import glob
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _cstats import RESULTS, SCRATCH, confusion, dump, macro_f1_boot, prf_boot, wilson  # noqa: E402

RAW = SCRATCH / "dimb_re/raw"
OUT = Path(os.environ.get("CMP_OUT", RESULTS / "dimb_re"))
RUNS = Path(os.environ.get("CMP_RUNS", RESULTS / "llm_runs"))
SYM = {"INTERACTS_WITH", "ASSOCIATED_WITH", "POS_ASSOCIATED_WITH", "NEG_ASSOCIATED_WITH"}
# our label -> (DiMB label, flip direction?)   flip: our "A INCREASED_IN B" (A higher in B) = "B INCREASES A"
MAP = {
    **{k: ("INCREASES", False) for k in ("PROMOTES", "UPREGULATES", "ACTIVATES", "POSITIVELY_REGULATES", "ENHANCES_BARRIER")},
    **{k: ("INCREASES", True) for k in ("INCREASED_IN", "INCREASES_OVER_TIME")},
    **{k: ("DECREASES", False) for k in ("SUPPRESSES", "DOWNREGULATES", "INHIBITS", "NEGATIVELY_REGULATES", "DEGRADES")},
    **{k: ("DECREASES", True) for k in ("DECREASED_IN", "DECREASES_OVER_TIME")},
    **{k: ("AFFECTS", False) for k in ("MODULATES", "ALTERS_MICROBIOME", "REGULATES", "CONTRIBUTES_TO", "MEDIATES", "TARGETS")},
    **{k: ("AFFECTS", True) for k in ("RESPONDS_TO", "DIFFERENTIALLY_ABUNDANT_IN", "STABLE_UNDER")},
    **{k: ("IMPROVES", False) for k in ("IMPROVES", "ALLEVIATES", "TREATS")},
    **{k: ("WORSENS", False) for k in ("EXACERBATES", "IMPAIRS")},
    **{k: ("PREVENTS", False) for k in ("PREVENTS", "PROTECTIVE_AGAINST")},
    **{k: ("CAUSES", False) for k in ("CAUSES", "TRIGGERS_INFLAMMATION", "INDUCES_IMMUNE_RESPONSE")},
    "INCREASES_RISK_OF": ("PREDISPOSES", False),
    "POSITIVELY_ASSOCIATED_WITH": ("POS_ASSOCIATED_WITH", False),
    "NEGATIVELY_ASSOCIATED_WITH": ("NEG_ASSOCIATED_WITH", False),
    **{k: ("ASSOCIATED_WITH", False) for k in ("ASSOCIATION_UNSIGNED", "INVOLVED_IN", "BIOMARKER_OF", "PREDICTS")},
    **{k: ("INTERACTS_WITH", False) for k in ("BINDS_TO", "COOPERATES_WITH", "COMPETES_WITH", "CROSS_FEEDS", "ENCODES", "EXPRESSES",
                                               "METABOLIZES", "CONSUMES", "PRODUCES", "SYNTHESIZES", "FACILITATES")},
    **{k: ("HAS_COMPONENT", True) for k in ("PART_OF", "DERIVED_FROM")},
}
POL = {"INCREASES": "+", "POS_ASSOCIATED_WITH": "+", "DECREASES": "-", "NEG_ASSOCIATED_WITH": "-", "AFFECTS": "0", "ASSOCIATED_WITH": "0"}
NER_MAP = {"Microorganism": {"ORGANISM"}, "Disease": {"DISEASE"}, "Chemical": {"CHEMICAL"}, "Nutrient": {"CHEMICAL"},
           "Metabolite": {"CHEMICAL"}, "Enzyme": {"PROTEIN"}, "Gene": {"PROTEIN", "DNA_RNA"}}
SCORED_CDM = {"ORGANISM", "DISEASE", "CHEMICAL", "PROTEIN", "DNA_RNA"}


def docs():
    for sp in ("train", "dev", "test"):
        for line in open(RAW / f"data_DiMB-RE_ner_reduced_v6.1_trg_abs_{sp}.json", encoding="utf-8"):
            yield sp, json.loads(line)


def mapped(r):
    """Prediction row -> (DiMB label | 'NEGATED' | None, direction)."""
    rel = r["relation"]
    if rel == "NULL_FINDING" and r.get("cue_found"):
        return "NEGATED", "SAME"
    if rel == "ASSOCIATION_UNSIGNED" and r.get("cue_found"):
        return "ASSOCIATED_WITH", "SAME"     # an exit label in the CDM (unsigned layer), but a relation in DiMB-RE terms
    if not r.get("specific_verified"):
        return None, None
    if rel not in MAP:
        return "OTHER", r["direction"]
    lab, flip = MAP[rel]
    d = r["direction"] or "SAME"
    if flip:
        d = "REVERSED" if d == "SAME" else "SAME"
    return lab, d


def correct(lab, d, gold):
    for g in gold:
        if lab == "NEGATED" and g.get("fact") == "Negated":
            return True
        if lab == g["label"] and (lab in SYM or d == g["dir"]):
            return True
    return False


def score_rel(rows, cross, split):
    R = [r for r in rows if r["ds"] == "dimb" and (split == "all" or r["split"] == split)]
    out = {"n_pairs": len(R), "n_gold_pairs": sum(1 for r in R if r["gold"])}
    # A1 typing on gold pairs
    G = [r for r in R if r["gold"]]
    det = sum(1 for r in G if mapped(r)[0] is not None)
    exact = sum(1 for r in G if correct(*mapped(r), r["gold"]))
    label_only = sum(1 for r in G if mapped(r)[0] in {g["label"] for g in r["gold"]} or
                     (mapped(r)[0] == "NEGATED" and any(g.get("fact") == "Negated" for g in r["gold"])))
    pol = [(POL[r["gold"][0]["label"]], POL.get(mapped(r)[0], "x")) for r in G if r["gold"][0]["label"] in POL and mapped(r)[0] is not None]
    out["A1_typing_on_gold_pairs"] = {
        "detected_any_relation": wilson(det, len(G)),
        "detected_relation_in_dimb_scheme": wilson(sum(1 for r in G if mapped(r)[0] not in (None, "OTHER")), len(G)),
        "exact_label_and_direction": wilson(exact, len(G)),
        "exact_label_and_direction_given_detected": wilson(exact, det),
        "label_ignoring_direction": wilson(label_only, len(G)),
        "polarity_agreement_given_detected": wilson(sum(1 for g, p in pol if g == p), len(pol)),
        "polarity_note": "gold INCREASES/POS_ASSOC = +, DECREASES/NEG_ASSOC = -, AFFECTS/ASSOCIATED_WITH = 0; pairs with another gold label excluded",
        "confusion_gold_vs_pred": confusion([(r["gold"][0]["label"], str(mapped(r)[0])) for r in G]),
    }
    # A2 extraction over all pairs (detection and typed), per-document units. "schema_filtered": answers whose label has
    # no DiMB-RE counterpart (USED_FOR, DIFFERS_FROM, IS_A, ...; mapped "OTHER") are dropped, as a user mapping our
    # output to the DiMB-RE scheme would do; "all_answers": they count as (false) predictions.
    a2 = {}
    for variant in ("schema_filtered", "all_answers"):
        det_u, typ_u = defaultdict(lambda: [0, 0, 0]), defaultdict(lambda: [0, 0, 0])
        for r in R:
            lab, d = mapped(r)
            if variant == "schema_filtered" and lab == "OTHER":
                lab = None
            key = (r["split"], r["doc"])
            g = bool(r["gold"])
            u, t = det_u[key], typ_u[key]
            if lab is not None and g:
                u[0] += 1
            elif lab is not None:
                u[1] += 1
            elif g:
                u[2] += 1
            if lab is not None and g and correct(lab, d, r["gold"]):
                t[0] += 1
            else:
                if lab is not None:
                    t[1] += 1
                if g:
                    t[2] += 1
        a2[variant] = {"detection": prf_boot([tuple(v) for v in det_u.values()]), "typed": prf_boot([tuple(v) for v in typ_u.values()])}
        if variant == "schema_filtered":
            keep = typ_u
    out["A2_extraction_within_sentence"] = a2
    typ_u = keep
    strict = {k: list(v) for k, v in typ_u.items()}
    for (sp, doc), n in cross.items():
        if split == "all" or sp == split:
            strict.setdefault((sp, doc), [0, 0, 0])[2] += n
    out["A2_typed_schema_filtered_incl_cross_sentence_as_missed"] = prf_boot([tuple(v) for v in strict.values()])
    out["n_cross_sentence_gold_relations"] = sum(n for (sp, _), n in cross.items() if split == "all" or sp == split)
    out["predicted_label_distribution"] = dict(Counter(str(mapped(r)[0]) for r in R).most_common())
    return out


def score_ner(split):
    pred = defaultdict(list)
    for f in glob.glob(str(RUNS / "ner/*.jsonl")):
        for line in open(f, encoding="utf-8"):
            try:
                c = json.loads(line)
            except json.JSONDecodeError:
                continue
            pred[(c["split"], c["doc"], c["sent0"])] = c
    units, units_l, recall_by_type, n_err = [], [], defaultdict(lambda: [0, 0]), 0
    typed_rec = defaultdict(lambda: [0, 0])
    for sp, d in docs():
        if split != "all" and sp != split:
            continue
        toks = [t for s in d["sentences"] for t in s]
        sstart = [0]
        for s in d["sentences"]:
            sstart.append(sstart[-1] + len(s))
        gold = [(e[0], e[1], e[2]) for s in d["ner"] for e in s]
        P = set()
        for c in [v for k, v in pred.items() if k[0] == sp and k[1] == d["doc_key"]]:
            n_err += bool(c.get("error"))
            t0 = sstart[c["sent0"]]
            ctoks = c["text"].split(" ")
            offs, k = [], 0
            for t in ctoks:
                offs.append(k)
                k += len(t) + 1
            o2t = {o: i for i, o in enumerate(offs)}
            for e in c["entities"]:
                txt = " ".join((e.get("text") or "").split())
                if not txt:
                    continue
                for m in re.finditer(r"(?<!\S)" + re.escape(txt) + r"(?!\S)", c["text"]):
                    if m.start() in o2t:
                        a = o2t[m.start()]
                        b = a + len(txt.split(" ")) - 1
                        P.add((t0 + a, t0 + b, e.get("type")))
        # untyped span recall per gold type (any predicted span overlapping)
        for gs, ge, gt in gold:
            recall_by_type[gt][1] += 1
            recall_by_type[gt][0] += any(ps <= ge and gs <= pe for ps, pe, _ in P)
        for gs, ge, gt in gold:
            if gt in NER_MAP:
                typed_rec[gt][1] += 1
                typed_rec[gt][0] += any(ps <= ge and gs <= pe and pt in NER_MAP[gt] for ps, pe, pt in P)
        Gs = [(gs, ge, gt) for gs, ge, gt in gold if gt in NER_MAP]
        Ps = [(ps, pe, pt) for ps, pe, pt in P if pt in SCORED_CDM]
        # strict
        tp = sum(1 for gs, ge, gt in Gs if any(ps == gs and pe == ge and pt in NER_MAP[gt] for ps, pe, pt in Ps))
        tpp = sum(1 for ps, pe, pt in Ps if any(ps == gs and pe == ge and pt in NER_MAP[gt] for gs, ge, gt in Gs))
        units.append((tpp, len(Ps) - tpp, len(Gs) - tp))
        # lenient overlap; predictions overlapping only unmapped gold types are not counted as FP
        tpl = sum(1 for gs, ge, gt in Gs if any(ps <= ge and gs <= pe and pt in NER_MAP[gt] for ps, pe, pt in Ps))
        okp = fp = 0
        for ps, pe, pt in Ps:
            if any(ps <= ge and gs <= pe and pt in NER_MAP[gt] for gs, ge, gt in Gs):
                okp += 1
            elif not any(ps <= ge and gs <= pe for gs, ge, gt in gold if gt not in NER_MAP):
                fp += 1
        units_l.append((okp, fp, len(Gs) - tpl))
    return {"strict_typed_mapped_types": prf_boot(units), "lenient_overlap_typed_mapped_types": prf_boot(units_l),
            "lenient_note": "TP if spans overlap and type compatible; predicted spans overlapping only Food/DietPattern/Physiology/"
                            "Measurement/DiversityMetric gold are excluded from FP; recall counts each gold mention",
            "untyped_span_recall_by_gold_type": {k: wilson(*v) for k, v in sorted(recall_by_type.items())},
            "typed_overlap_recall_by_gold_type": {k: wilson(*v) for k, v in sorted(typed_rec.items())},
            "chunks_with_llm_error": n_err}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    from midred_compare import load
    rows = load("dimb")
    cross = Counter()
    for sp, d in docs():
        for ents, rels in zip(d["ner"], d["relations"]):
            es = {(e[0], e[1]) for e in ents}
            cross[(sp, d["doc_key"])] += sum(1 for r in rels if (r[0], r[1]) not in es or (r[2], r[3]) not in es)
    summ = {"source": "github.com/ScienceNLP-Lab/DiMB-RE commit 03012c98 (2025-02-17), data/DiMB-RE/ner_reduced_v6.1_trg_abs",
            "reference_type": "human-annotated gold standard",
            "n_prediction_rows": len(rows), "unparsed": sum(1 for r in rows if r["relation"] == "UNPARSED" and r["ds"] == "dimb"),
            "label_mapping": {k: list(v) for k, v in MAP.items()},
            "relations": {sp: score_rel(rows, cross, sp) for sp in ("all", "test")}}
    try:
        summ["entities"] = {sp: score_ner(sp) for sp in ("all", "test")}
    except FileNotFoundError:
        summ["entities"] = None
    summ["published_baselines_test"] = {"NER_F1_finetuned": 0.800, "end_to_end_RE_F1_finetuned": 0.445,
                                        "note": "Hong et al. 2025 (JAMIA) abstract; fine-tuned on DiMB-RE train; end-to-end incl. NER"}
    dump(summ, OUT / "SUMMARY.json")
    with open(OUT / "rel_predictions.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "split", "subject", "stype", "object", "otype", "gold", "relation", "direction", "cue", "mapped", "mapped_dir", "correct"])
        for r in rows:
            if r["ds"] != "dimb":
                continue
            lab, d = mapped(r)
            w.writerow([r["id"], r["split"], r["subject"], r["stype"], r["object"], r["otype"],
                        ";".join(f"{g['label']}/{g['dir']}/{g.get('fact', '')}" for g in r["gold"]), r["relation"], r["direction"],
                        r.get("cue", ""), lab, d, correct(lab, d, r["gold"]) if r["gold"] and lab else ""])
    print(json.dumps(summ["relations"]["all"]["A1_typing_on_gold_pairs"], indent=1)[:2500])


if __name__ == "__main__":
    main()
