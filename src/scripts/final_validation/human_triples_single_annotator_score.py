"""Score ONE completed annotator sheet of the pre-registered 100-triple manual check (deterministic; no model).

    ~/path/to/python-with-openpyxl src/scripts/final_validation/human_triples_single_annotator_score.py \
        --sheet <annotator A sheet>.xlsx --name annotator_A

The pre-registered analysis (human_spotcheck_score.py, PROTOCOL.md of 2026-11-09) needs both sheets A and B plus an
agreed column. Until sheet B exists, this script reports what the protocol allows for one annotator:
  1. pre-registered: the annotator's SUPPORT distribution with 95% Wilson intervals; agreement of the
     DeepSeek-V4.1-Flash screen (KEY file, opened only now) with this annotator (confusion, observed agreement,
     Cohen's kappa; 4 labels and two binary cuts);
  2. EXPLORATORY (not pre-registered): agreement of this annotator with the pipeline's final relation layer for the
     same triples (triples_final_summary.py buckets: retype v2.5 + unsigned regate v1.1 over CDM 3.1.0 triple_tier).
     The annotator judged the ORIGINAL triple label shown in the sheet, so this tests the pipeline's flags
     (NOT_SUPPORTED vs kept) and whether triples the pipeline calls specific and cue-verified are supported.
Checks the pre-registered files against PREREGISTRATION.sha256 and the sheet against sample.csv.
Output: outputs/results/benchmark/human_spotcheck_triples_2026-11-09/<name>/{results.json,RESULTS.md}.
Written with Claude Code (declare).
"""
from __future__ import annotations

import argparse
import collections
import csv
import glob
import hashlib
import json
import math
import sqlite3
from pathlib import Path

from openpyxl import load_workbook

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
D = ROOT / "outputs/results/benchmark/human_spotcheck_triples_2026-11-09"
DB310 = ROOT / "releases/cdm_v3/3.1.0/microbiome_cdm_v3.1.0.db"
LABELS = ["SUPPORTED", "PARTIAL", "NOT_SUPPORTED", "CONFLICTS"]


def wilson(k, n, z=1.96):
    if not n:
        return [None, None]
    p = k / n; d = 1 + z * z / n; c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(100 * (c - h), 1), round(100 * (c + h), 1)]


def kappa(a, b):
    n = len(a)
    po = sum(x == y for x, y in zip(a, b)) / n
    ca, cb = collections.Counter(a), collections.Counter(b)
    pe = sum(ca[l] * cb[l] for l in set(a) | set(b)) / (n * n)
    return round(po, 3), (round((po - pe) / (1 - pe), 3) if pe < 1 else None)


def compare(a, b, labels):
    po, k = kappa(a, b)
    conf = {x: {y: sum(1 for p, q in zip(a, b) if p == x and q == y) for y in labels} for x in labels}
    agree = sum(p == q for p, q in zip(a, b))
    return {"n": len(a), "agree": agree, "observed_agreement": po, "agreement_ci95": wilson(agree, len(a)),
            "cohen_kappa": k, "confusion_rows_first_cols_second": conf}


def rows(pattern):
    return [json.loads(l) for f in sorted(glob.glob(str(ROOT / pattern))) for l in open(f, encoding="utf-8") if l.strip()]


def bucket(rel, ok):
    if ok:
        return "SPECIFIC_CUE_VERIFIED"
    if rel in ("NOT_SUPPORTED", "ASSOCIATION_UNSIGNED", "NULL_FINDING", "BAD_ENDPOINT"):
        return rel
    return "SPECIFIC_LABEL_CUE_NOT_FOUND"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sheet", type=Path, required=True)
    ap.add_argument("--name", required=True)
    a = ap.parse_args()
    pre = dict(reversed(l.split("  ", 1)) for l in (D / "PREREGISTRATION.sha256").read_text().split("\n") if l)
    changed = [f for f in ("KEY_deepseek_verdicts.csv", "sample.csv", "PROTOCOL.md", "GUIDE.txt")
               if hashlib.sha256((D / f).read_bytes()).hexdigest() != pre.get(f)]
    assert not changed, f"pre-registered files changed: {changed}"
    sample = {int(r["item"]): r for r in csv.DictReader(open(D / "sample.csv", encoding="utf-8"))}
    ws = load_workbook(a.sheet, data_only=True)["annotate"]
    hdr = [c.value for c in ws[1]]
    ann = {}
    for r in ws.iter_rows(min_row=2, values_only=True):
        if r[0] is None:
            continue
        d = dict(zip(hdr, r)); i = int(d["item"]); s = sample[i]
        assert (d["subject"], d["relation"], d["object"], d["sentence"]) == (s["subject"], s["relation"], s["object"], s["sentence"]), i
        assert d["SUPPORT"] in LABELS, (i, d["SUPPORT"])
        ann[i] = d
    assert sorted(ann) == sorted(sample), "sheet incomplete"
    key = {int(r["item"]): r for r in csv.DictReader(open(D / "KEY_deepseek_verdicts.csv", encoding="utf-8"))}
    items = sorted(ann); n = len(items)
    A = [ann[i]["SUPPORT"] for i in items]; K = [key[i]["ds_support"] for i in items]
    cA = collections.Counter(A)
    dist = {l: {"n": cA[l], "pct": round(100 * cA[l] / n, 1), "ci95": wilson(cA[l], n)} for l in LABELS}
    sp = cA["SUPPORTED"] + cA["PARTIAL"]
    cut1 = lambda x: "SUPPORTED" if x == "SUPPORTED" else "OTHER"
    cut2 = lambda x: "SUPPORTED_OR_PARTIAL" if x in ("SUPPORTED", "PARTIAL") else "NOT_OR_CONFLICT"
    res = {"annotator": a.name, "sheet": a.sheet.name,
           "sheet_sha256": hashlib.sha256(a.sheet.read_bytes()).hexdigest(), "n": n,
           "status": "ONE annotator of the two pre-registered; adjudicated (AGREED) labels pending",
           "preregistered": {
               "support_distribution": dist,
               "supported_or_partial": {"n": sp, "pct": round(100 * sp / n, 1), "ci95": wilson(sp, n)},
               "polarity": dict(collections.Counter(ann[i]["POLARITY"] for i in items)),
               "relation_justified": dict(collections.Counter(ann[i]["RELATION_JUSTIFIED"] for i in items)),
               "deepseek_on_sample": dict(collections.Counter(K)),
               "deepseek_vs_annotator_4label": compare(A, K, LABELS),
               "deepseek_vs_annotator_supported_vs_other": compare([cut1(x) for x in A], [cut1(x) for x in K], ["SUPPORTED", "OTHER"]),
               "deepseek_vs_annotator_supported_or_partial": compare([cut2(x) for x in A], [cut2(x) for x in K],
                                                                     ["SUPPORTED_OR_PARTIAL", "NOT_OR_CONFLICT"])}}
    # exploratory: pipeline final layer
    c = sqlite3.connect(f"file:{DB310}?mode=ro", uri=True)
    base = {k: (rel, s == "True" and cf == "True") for k, rel, s, cf in
            c.execute("SELECT canonical_triple_id, relation, specific_relation, cue_found FROM triple_tier")}
    v25 = {r["canonical_triple_id"]: r for r in rows("outputs/results/triple_retype_v2_2026-11-10/all_v25/*.jsonl")}
    uns = {r["canonical_triple_id"]: r for r in rows("outputs/results/unsigned_resolve_2026-11-10/all/final.jsonl")}
    pipe = {}
    for i in items:
        t = sample[i]["triple_id"]; r = uns.get(t) or v25.get(t)
        pipe[i] = {"bucket": bucket(r["relation"], r["specific_verified"]) if r else bucket(*base[t]),
                   "final_relation": r["relation"] if r else base[t][0]}
    by = collections.defaultdict(collections.Counter)
    for i in items:
        by[pipe[i]["bucket"]][ann[i]["SUPPORT"]] += 1
    flag_pipe = ["FLAGGED" if pipe[i]["bucket"] == "NOT_SUPPORTED" else "KEPT" for i in items]
    flag_ann = ["FLAGGED" if x in ("NOT_SUPPORTED", "CONFLICTS") else "KEPT" for x in A]
    tp = sum(p == q == "FLAGGED" for p, q in zip(flag_pipe, flag_ann))
    spec = [i for i in items if pipe[i]["bucket"] == "SPECIFIC_CUE_VERIFIED"]
    spec_ok = sum(ann[i]["SUPPORT"] in ("SUPPORTED", "PARTIAL") for i in spec)
    res["exploratory_pipeline"] = {
        "note": "not pre-registered; annotator judged the original label; pipeline layer = retype v2.5 + unsigned regate v1.1",
        "annotator_support_by_pipeline_bucket": {k: dict(v) for k, v in by.items()},
        "not_supported_flag": {**compare(flag_ann, flag_pipe, ["FLAGGED", "KEPT"]),
                               "pipeline_flag_precision": [tp, flag_pipe.count("FLAGGED"), wilson(tp, flag_pipe.count("FLAGGED"))],
                               "pipeline_flag_recall": [tp, flag_ann.count("FLAGGED"), wilson(tp, flag_ann.count("FLAGGED"))]},
        "specific_cue_verified_supported_or_partial": [spec_ok, len(spec), wilson(spec_ok, len(spec))],
        "items": {i: {"triple_id": sample[i]["triple_id"], "annotator": ann[i]["SUPPORT"], "deepseek": key[i]["ds_support"],
                      **pipe[i]} for i in items}}
    out = D / a.name
    out.mkdir(exist_ok=True)
    (out / "results.json").write_text(json.dumps(res, indent=1) + "\n", encoding="utf-8")
    p = res["preregistered"]; e = res["exploratory_pipeline"]
    md = [f"# 100-triple manual check: {a.name} (one of two annotators; adjudicated labels pending)", "",
          "| SUPPORT | n | % (95% CI) |", "|---|---|---|"]
    md += [f"| {l} | {dist[l]['n']} | {dist[l]['pct']} ({dist[l]['ci95'][0]}–{dist[l]['ci95'][1]}) |" for l in LABELS]
    for k in ("deepseek_vs_annotator_4label", "deepseek_vs_annotator_supported_vs_other", "deepseek_vs_annotator_supported_or_partial"):
        v = p[k]; md.append(f"\n{k}: agreement {v['agree']}/{v['n']} ({v['agreement_ci95']}), kappa {v['cohen_kappa']}")
    f = e["not_supported_flag"]
    md += ["", "## Exploratory (not pre-registered): pipeline final layer",
           f"annotator SUPPORT by pipeline bucket: {e['annotator_support_by_pipeline_bucket']}",
           f"NOT_SUPPORTED flag vs annotator NOT_SUPPORTED/CONFLICTS: agreement {f['agree']}/{f['n']}, kappa {f['cohen_kappa']}, "
           f"precision {f['pipeline_flag_precision']}, recall {f['pipeline_flag_recall']}",
           f"specific cue-verified triples judged SUPPORTED or PARTIAL: {e['specific_cue_verified_supported_or_partial']}"]
    (out / "RESULTS.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    main()
