"""EXPLORATORY (not pre-registered) comparison of the two human annotators' labels on the pre-registered 100-triple check
with the 2026-11-10 relation layer (old) and layer 3.2.0-candidate (new). Logic of the exploratory block of
src/scripts/final_validation/human_triples_single_annotator_score.py (whose helpers are imported), applied to both layers.

    <python with openpyxl> src/scripts/fixes_v32/annotator_compare_v32.py --sheet-a A.xlsx --sheet-b B.xlsx

Annotators are referred to only as "annotator A" / "annotator B". The annotators judged the ORIGINAL triple label shown in
the sheet, so this tests the layers' flags and whether triples a layer calls specific are supported.
Flag definitions: old flag = NOT_SUPPORTED (as before); new flag = NOT_SUPPORTED or CO_OCCURRENCE_ONLY; annotator flag =
NOT_SUPPORTED or CONFLICTS. Output outputs/results/triples_final_v32_2026-11-11/annotator_comparison.{json,md}.
Written with Claude Code (declare).
"""
from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import json
import sys
from pathlib import Path

from openpyxl import load_workbook

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
sys.path.insert(0, str(ROOT / "src/scripts/final_validation"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from human_triples_single_annotator_score import compare, wilson, LABELS  # noqa: E402
from triples_final_summary_v32 import new_layer  # noqa: E402

H = ROOT / "outputs/results/benchmark/human_spotcheck_triples_2026-11-09"
OUT = ROOT / "outputs/results/triples_final_v32_2026-11-11"


def read_sheet(path, sample):
    ws = load_workbook(path, data_only=True)["annotate"]
    hdr = [c.value for c in ws[1]]
    ann = {}
    for r in ws.iter_rows(min_row=2, values_only=True):
        if r[0] is None:
            continue
        d = dict(zip(hdr, r))
        i = int(d["item"])
        s = sample[i]
        assert (d["subject"], d["relation"], d["object"], d["sentence"]) == (s["subject"], s["relation"], s["object"], s["sentence"]), i
        assert d["SUPPORT"] in LABELS, (i, d["SUPPORT"])
        ann[i] = d["SUPPORT"]
    assert sorted(ann) == sorted(sample), "sheet incomplete"
    return ann


def score(ann, layer, items, flagset):
    A = [ann[i] for i in items]
    by = collections.defaultdict(collections.Counter)
    for i in items:
        by[layer[i]][ann[i]] += 1
    fp = ["FLAGGED" if layer[i] in flagset else "KEPT" for i in items]
    fa = ["FLAGGED" if x in ("NOT_SUPPORTED", "CONFLICTS") else "KEPT" for x in A]
    tp = sum(p == q == "FLAGGED" for p, q in zip(fp, fa))
    sp = lambda b: [sum(ann[i] in ("SUPPORTED", "PARTIAL") for i in items if layer[i] == b), sum(layer[i] == b for i in items)]
    s, o = sp("SPECIFIC_CUE_VERIFIED"), sp("OPEN_CUE_VERIFIED")
    return {"annotator_support_by_bucket": {k: dict(v) for k, v in sorted(by.items())},
            "flag": {**compare(fa, fp, ["FLAGGED", "KEPT"]),
                     "layer_flag_precision": [tp, fp.count("FLAGGED"), wilson(tp, fp.count("FLAGGED"))],
                     "layer_flag_recall": [tp, fa.count("FLAGGED"), wilson(tp, fa.count("FLAGGED"))]},
            "specific_cue_verified_supported_or_partial": s + [wilson(*s)],
            "open_cue_verified_supported_or_partial": o + [wilson(*o)]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sheet-a", type=Path, required=True)
    ap.add_argument("--sheet-b", type=Path, required=True)
    a = ap.parse_args()
    sample = {int(r["item"]): r for r in csv.DictReader(open(H / "sample.csv", encoding="utf-8"))}
    items = sorted(sample)
    res, fl, v32 = new_layer()
    old = {i: res[sample[i]["triple_id"]][0] for i in items}
    new = {i: res[sample[i]["triple_id"]][1] for i in items}
    out = {"note": "EXPLORATORY, not pre-registered; annotators judged the original label; old layer = 2026-11-10 "
                   "(retype v2.5 + unsigned regate v1.1); new layer = 3.2.0-candidate",
           "n": len(items), "in_v32_scope": sum(old[i] in ("NOT_SUPPORTED", "SPECIFIC_LABEL_CUE_NOT_FOUND") for i in items),
           "transitions": dict(collections.Counter(f"{old[i]} -> {new[i]}" for i in items if old[i] != new[i]).most_common())}
    for tag, path in (("annotator_A", a.sheet_a), ("annotator_B", a.sheet_b)):
        ann = read_sheet(path, sample)
        out[tag] = {"sheet_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "old_layer": score(ann, old, items, {"NOT_SUPPORTED"}),
                    "new_layer": score(ann, new, items, {"NOT_SUPPORTED", "CO_OCCURRENCE_ONLY"})}
    out["items"] = {i: {"triple_id": sample[i]["triple_id"], "old": old[i], "new": new[i],
                        "new_relation": res[sample[i]["triple_id"]][2]} for i in items}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "annotator_comparison.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    md = ["# Exploratory: human annotators vs relation layers (old 2026-11-10 vs new 3.2.0-candidate)", "",
          f"n = {out['n']}; in v3.2 scope: {out['in_v32_scope']}; changed buckets: {out['transitions']}", ""]
    for tag in ("annotator_A", "annotator_B"):
        for lay in ("old_layer", "new_layer"):
            s = out[tag][lay]
            f = s["flag"]
            md.append(f"- {tag.replace('_', ' ')}, {lay.replace('_', ' ')}: flag agreement {f['agree']}/{f['n']} "
                      f"(kappa {f['cohen_kappa']}), flag precision {f['layer_flag_precision']}, recall {f['layer_flag_recall']}; "
                      f"specific cue-verified judged SUPPORTED/PARTIAL {s['specific_cue_verified_supported_or_partial']}; "
                      f"open cue {s['open_cue_verified_supported_or_partial']}")
            md.append(f"  - support by bucket: {s['annotator_support_by_bucket']}")
    (OUT / "annotator_comparison.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    main()
