"""Final relation-quality counts over all triple layers of 2026-11-10 (deterministic; reads layer files and CDM 3.1.0).

    python src/scripts/triples/triples_final_summary.py

CDM triples (25,788): CDM 3.1.0 triple_tier, overridden by retype-v2.5 (all_v25/) for the 14,867 unspecific triples and
by the unsigned-association resolution (unsigned_resolve_2026-11-10/all/final.jsonl, regate v1.1) for its 1,708.
Buckets (exhaustive): SPECIFIC_CUE_VERIFIED, NOT_SUPPORTED, SPECIFIC_LABEL_CUE_NOT_FOUND, ASSOCIATION_UNSIGNED,
NULL_FINDING, BAD_ENDPOINT. Catalogue-derived triples: triple_retype_v3_2026-11-10/claims/.
Output: outputs/results/triples_final_2026-11-10/SUMMARY.json. Model-generated layers; frozen releases unchanged;
PENDING lead approval. Written with Claude Code (declare).
"""
from __future__ import annotations

import glob
import json
import sqlite3
from collections import Counter
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
DB310 = ROOT / "releases/cdm_v3/3.1.0/microbiome_cdm_v3.1.0.db"
OUT = ROOT / "outputs/results/triples_final_2026-11-10"


def rows(pattern):
    return [json.loads(l) for f in sorted(glob.glob(str(ROOT / pattern))) for l in open(f, encoding="utf-8") if l.strip()]


def bucket(rel, ok):
    if ok:
        return "SPECIFIC_CUE_VERIFIED"
    if rel in ("NOT_SUPPORTED", "ASSOCIATION_UNSIGNED", "NULL_FINDING", "BAD_ENDPOINT"):
        return rel
    return "SPECIFIC_LABEL_CUE_NOT_FOUND"


def main():
    c = sqlite3.connect(f"file:{DB310}?mode=ro", uri=True)
    base = {k: (rel, s == "True" and cf == "True") for k, rel, s, cf in
            c.execute("SELECT canonical_triple_id, relation, specific_relation, cue_found FROM triple_tier")}
    v25 = {r["canonical_triple_id"]: r for r in rows("outputs/results/triple_retype_v2_2026-11-10/all_v25/*.jsonl")}
    uns = {r["canonical_triple_id"]: r for r in rows("outputs/results/unsigned_resolve_2026-11-10/all/final.jsonl")}
    b = Counter()
    for k, (rel, ok) in base.items():
        r = uns.get(k) or v25.get(k)
        b[bucket(r["relation"], r["specific_verified"]) if r else bucket(rel, ok)] += 1
    cat = rows("outputs/results/triple_retype_v3_2026-11-10/claims/*.jsonl")
    cb = Counter(bucket(r["relation"], r["specific_verified"]) for r in cat)
    n, m = sum(b.values()), len(cat)
    us = [r for r in uns.values() if r["specific_verified"]]
    res = {"cdm_triples": {"total": n, "buckets": dict(b.most_common()),
                           "specific_pct": round(100 * b["SPECIFIC_CUE_VERIFIED"] / n, 1)},
           "unsigned_resolution": {"scope": len(uns), "resolved_specific": len(us),
                                   "resolved_via_section": sum(r["step"] == "SECTION" for r in us),
                                   "deepseek_cc_by_cc0": sum(r["backend"] == "genie" for r in uns.values()),
                                   "local_qwen": sum(r["backend"] == "local" for r in uns.values())},
           "catalogue_derived": {"total": m, "buckets": dict(cb.most_common()),
                                 "papers_with_specific": len({r["paper_id"] for r in cat if r["specific_verified"]})},
           "all": {"total": n + m, "specific_cue_verified": b["SPECIFIC_CUE_VERIFIED"] + cb["SPECIFIC_CUE_VERIFIED"]},
           "status": "model-generated layers; frozen releases unchanged; not human-validated; PENDING lead approval"}
    res["all"]["specific_pct"] = round(100 * res["all"]["specific_cue_verified"] / res["all"]["total"], 1)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "SUMMARY.json").write_text(json.dumps(res, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
