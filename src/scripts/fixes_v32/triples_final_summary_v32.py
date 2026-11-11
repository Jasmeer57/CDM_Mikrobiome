"""Final relation buckets for the CDM triples with layer 3.2.0-candidate (deterministic; reads layer files and CDM 3.1.0).

    python src/scripts/fixes_v32/triples_final_summary_v32.py

Old layer (= triples_final_summary.py, 2026-11-10): CDM 3.1.0 triple_tier, overridden by retype-v2.5 (all_v25/) and by
the unsigned-association resolution (unsigned_resolve_2026-11-10/all/final.jsonl). New layer: the old layer, with the
9,672 triples of buckets NOT_SUPPORTED / SPECIFIC_LABEL_CUE_NOT_FOUND overridden by retype-v3.2
(fixes_v32_2026-11-11/all/triples_v32.shard*.jsonl: Fix A labels + open cue, Fix B syntactic filter).
New buckets (exhaustive): SPECIFIC_CUE_VERIFIED (closed vocabulary, incl. the 11 corpus-derived labels; reported
separately), OPEN_CUE_VERIFIED (OTHER_STATED_RELATION with verbatim, verified cue; NOT counted as typed),
CO_OCCURRENCE_ONLY (Fix B), ASSOCIATION_UNSIGNED, NULL_FINDING, NOT_SUPPORTED, BAD_ENDPOINT, SPECIFIC_LABEL_CUE_NOT_FOUND,
OPEN_CUE_NOT_FOUND. Also: the Fix B filter applied (diagnostic only, no change) to the triples the old layer already
calls specific. Writes outputs/results/triples_final_v32_2026-11-11/{SUMMARY.json, SUMMARY.md, triples_v32_final.jsonl};
does not touch triples_final_2026-11-10. Model-generated layer; PENDING lead approval. Written with Claude Code (declare).
"""
from __future__ import annotations

import glob
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
sys.path.insert(0, str(Path(__file__).resolve().parent))
from corpus_parse import final_layer  # noqa: E402  (old-layer logic, identical to triples_final_summary.py)

D = ROOT / "outputs/results/fixes_v32_2026-11-11"
OUT = ROOT / "outputs/results/triples_final_v32_2026-11-11"
NEW = [l["label"] for l in json.load(open(D / "labels_v32.json"))["labels"]]
ORDER = ["SPECIFIC_CUE_VERIFIED", "OPEN_CUE_VERIFIED", "CO_OCCURRENCE_ONLY", "ASSOCIATION_UNSIGNED", "NULL_FINDING",
         "NOT_SUPPORTED", "BAD_ENDPOINT", "SPECIFIC_LABEL_CUE_NOT_FOUND", "OPEN_CUE_NOT_FOUND"]


def v32_bucket(r):
    rel = r["relation"]
    if r["specific_verified"]:
        return "SPECIFIC_CUE_VERIFIED"
    if r.get("open_cue_verified"):
        return "OPEN_CUE_VERIFIED"
    if rel == "OTHER_STATED_RELATION":
        return "OPEN_CUE_NOT_FOUND"
    if rel in ("CO_OCCURRENCE_ONLY", "NOT_SUPPORTED", "ASSOCIATION_UNSIGNED", "NULL_FINDING", "BAD_ENDPOINT"):
        return rel
    if rel == "UNPARSED":
        return "NOT_SUPPORTED"
    return "SPECIFIC_LABEL_CUE_NOT_FOUND"


def load_v32(run="all"):
    out = {}
    for f in sorted(glob.glob(str(D / run / "triples_v32*.jsonl"))):
        for line in open(f, encoding="utf-8"):
            try:
                j = json.loads(line)
            except json.JSONDecodeError:
                continue
            if j["relation"] != "UNPARSED" or j["canonical_triple_id"] not in out:
                out[j["canonical_triple_id"]] = j
    return out


def new_layer():
    """{tid: (old_bucket, new_bucket, new_relation, v32 row or None)}"""
    fl = final_layer()
    v32 = load_v32()
    res = {}
    for k, (bk, rel, *_r) in fl.items():
        r = v32.get(k)
        res[k] = (bk, v32_bucket(r) if r else bk, r["relation"] if r else rel, r)
    return res, fl, v32


def main():
    res, fl, v32 = new_layer()
    scope = [k for k, v in fl.items() if v[0] in ("NOT_SUPPORTED", "SPECIFIC_LABEL_CUE_NOT_FOUND")]
    missing = [k for k in scope if k not in v32]
    old = Counter(v[0] for v in res.values())
    new = Counter(v[1] for v in res.values())
    n = len(res)
    trans = defaultdict(Counter)
    for k in scope:
        trans[res[k][0]][res[k][1]] += 1
    spec_rows = [v[3] for v in res.values() if v[3] and v[1] == "SPECIFIC_CUE_VERIFIED"]
    new_lab = Counter(r["relation"] for r in spec_rows if r["relation"] in NEW)
    all_lab = Counter(r["relation"] for r in spec_rows)
    syn = Counter(v[3]["syntax_status"] for v in res.values() if v[3])
    parse = [json.loads(l) for l in open(D / "parse/corpus_parse.jsonl", encoding="utf-8")]
    diag = Counter((p["bucket_v31"], p["syntax_connected"]) for p in parse if p["bucket_v31"] == "SPECIFIC_CUE_VERIFIED")
    out = {"cdm_triples_total": n, "scope_v32": len(scope), "scope_missing_v32_rows": len(missing),
           "old_buckets_2026_11_10": {b: old.get(b, 0) for b in ORDER if old.get(b, 0)},
           "new_buckets_v32": {b: new.get(b, 0) for b in ORDER},
           "specific_pct_old": round(100 * old["SPECIFIC_CUE_VERIFIED"] / n, 1),
           "specific_pct_new": round(100 * new["SPECIFIC_CUE_VERIFIED"] / n, 1),
           "specific_plus_open_pct_new": round(100 * (new["SPECIFIC_CUE_VERIFIED"] + new["OPEN_CUE_VERIFIED"]) / n, 1),
           "scope_transitions_old_to_new": {k: dict(v.most_common()) for k, v in trans.items()},
           "v32_specific_by_label": dict(all_lab.most_common()),
           "v32_specific_via_new_labels": {"total": sum(new_lab.values()), **dict(new_lab.most_common())},
           "v32_syntax_status_in_scope": dict(syn.most_common()),
           "diagnostic_filter_on_old_specific": {"note": "Fix B applied to triples the old layer already calls specific; NOT used to change them",
                                                 "connected": diag[("SPECIFIC_CUE_VERIFIED", True)],
                                                 "fails_filter": diag[("SPECIFIC_CUE_VERIFIED", False)],
                                                 "unlocated": diag[("SPECIFIC_CUE_VERIFIED", None)]},
           "labels_sha256": hashlib.sha256((D / "labels_v32.json").read_bytes()).hexdigest(),
           "status": "model-generated layer 3.2.0-candidate; frozen releases unchanged; not human-validated; PENDING lead approval"}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "SUMMARY.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    with open(OUT / "triples_v32_final.jsonl", "w", encoding="utf-8") as f:
        for k in sorted(res):
            ob, nb, rel, r = res[k]
            f.write(json.dumps({"canonical_triple_id": k, "old_bucket": ob, "new_bucket": nb, "relation": rel,
                                "direction": (r or {}).get("direction"), "cue": (r or {}).get("cue"),
                                "syntax_status": (r or {}).get("syntax_status"), "layer": "v3.2" if r else "2026-11-10"},
                               ensure_ascii=False) + "\n")
    md = ["# CDM triple relation buckets: 2026-11-10 layer vs 3.2.0-candidate", "",
          "| bucket | old (2026-11-10) | new (v3.2) |", "|---|---|---|"]
    md += [f"| {b} | {old.get(b, 0):,} | {new.get(b, 0):,} |" for b in ORDER]
    md += [f"| total | {n:,} | {n:,} |", "",
           f"Specific cue-verified: {out['specific_pct_old']}% -> {out['specific_pct_new']}% "
           f"(+ open cue: {out['specific_plus_open_pct_new']}%). New-label share of specific: {out['v32_specific_via_new_labels']}.",
           f"Scope transitions: {out['scope_transitions_old_to_new']}", f"Diagnostic: {out['diagnostic_filter_on_old_specific']}"]
    (OUT / "SUMMARY.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    main()
