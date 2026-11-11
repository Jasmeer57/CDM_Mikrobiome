"""Combined counts after the 2026-11-10 re-typing layers (deterministic; reads CDM 3.1.0 read-only plus the layer files).

    python src/scripts/terms/retype_merge_summary.py

Triples: CDM 3.1.0 triple_tier, with each NO_SPECIFIC_RELATION_STATED triple replaced by its retype-v2.5 result
(the two sets are disjoint). A triple counts as specific when it has a specific relation and a cue phrase found in its
source sentence (3.1.0: specific_relation and cue_found; v2.5: specific_verified).
Terms: CDM 3.1.0 term_curation kept terms, with each generic ENTITY term replaced by its entity-retype-v1.1 type.
Output: outputs/results/retype_merged_2026-11-10/SUMMARY.json. Model-generated layers; frozen releases unchanged; not
human-validated; PENDING lead approval. Written with Claude Code (declare).
"""
from __future__ import annotations

import glob
import json
import sqlite3
from collections import Counter
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
DB310 = ROOT / "releases/cdm_v3/3.1.0/microbiome_cdm_v3.1.0.db"
TRI = ROOT / "outputs/results/triple_retype_v2_2026-11-10/all_v25"
ENT = ROOT / "outputs/results/entity_retype_2026-11-10/all"
OUT = ROOT / "outputs/results/retype_merged_2026-11-10"
EXT = {"ANATOMY_OR_BODY_SITE", "POPULATION_OR_HOST_GROUP", "MEASURE_OR_UNIT", "GEOGRAPHY"}


def rows(d):
    return [json.loads(line) for f in sorted(glob.glob(str(d / "*.jsonl"))) for line in open(f, encoding="utf-8")]


def main():
    c = sqlite3.connect(f"file:{DB310}?mode=ro", uri=True)
    tiers = c.execute("SELECT canonical_triple_id, relation, specific_relation, cue_found FROM triple_tier").fetchall()
    new = {r["canonical_triple_id"]: r for r in rows(TRI)}
    before = sum(s == "True" and cf == "True" for _, _, s, cf in tiers)
    out = Counter()
    for tid, rel, s, cf in tiers:
        if tid in new:
            r = new[tid]
            assert not (s == "True" and cf == "True")               # disjoint by construction
            out["SPECIFIC_CUE_VERIFIED" if r["specific_verified"] else r["relation"]] += 1
        else:
            out["SPECIFIC_CUE_VERIFIED" if (s == "True" and cf == "True") else rel] += 1
    n = len(tiers)
    terms = c.execute("SELECT term_id, cdm_type FROM term_curation WHERE kept='True'").fetchall()
    ent = {r["term_id"]: r["type"] for r in rows(ENT)}
    types = Counter(ent.get(t, ty) if ty == "ENTITY" else ty for t, ty in terms)
    generic_before = sum(ty == "ENTITY" for _, ty in terms)
    core = sum(v for k, v in types.items() if k not in EXT | {"NOT_A_CONCEPT", "ENTITY"})
    res = {"triples": {"total": n, "specific_cue_verified_3_1_0": before,
                       "specific_cue_verified_after_retype": out["SPECIFIC_CUE_VERIFIED"],
                       "specific_cue_verified_after_retype_pct": round(100 * out["SPECIFIC_CUE_VERIFIED"] / n, 1),
                       "not_supported": out["NOT_SUPPORTED"], "association_unsigned": out["ASSOCIATION_UNSIGNED"],
                       "null_finding": out["NULL_FINDING"], "no_specific_relation_stated": out["NO_SPECIFIC_RELATION_STATED"],
                       "all": dict(out.most_common())},
           "terms": {"kept": len(terms), "generic_entity_before": generic_before,
                     "generic_entity_after": types.get("ENTITY", 0), "in_14_cdm_types_after": core,
                     "in_14_cdm_types_after_pct": round(100 * core / len(terms), 1),
                     "proposed_extension_types": sum(types[k] for k in EXT), "not_a_concept": types["NOT_A_CONCEPT"],
                     "types": dict(types.most_common())},
           "status": "model-generated layers over CDM 3.1.0; frozen releases unchanged; not human-validated; PENDING lead approval"}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "SUMMARY.json").write_text(json.dumps(res, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: {kk: vv for kk, vv in v.items() if kk not in ("all", "types")} for k, v in res.items() if k != "status"}, indent=1))


if __name__ == "__main__":
    main()
