"""Deterministic quality gates and tiers for the repaired triples (no model). Reads repair output, writes a tier table.

    python3 src/scripts/triples/triple_gates_tiers.py [--repair DIR]

Gates per triple:
  specific_relation   final relation is a specific CDM label (not an exit, not UNPARSED)
  cue_found           the model's cue phrase occurs verbatim in an anchor sentence
  anchored            at least one anchor sentence is EXACT or NORMALISED
  endpoints_clean     no endpoint fix was needed (or a verbatim fix exists: endpoint_repaired)
  domain_range_ok     a biological relation does not link two non-biological endpoint types
  null_finding        the sentence states no effect/association (kept as a separate flag, not a relation)
Tiers:
  1  specific + cue_found + anchored + domain_range_ok + endpoints clean (no fix needed)
  2  specific + cue_found + domain_range_ok, but an endpoint was repaired or the anchor is not EXACT/NORMALISED
  3  everything else (no specific relation stated, not supported, null finding, cue not found, domain-range violation,
     rejected endpoint fix, unparsed)
Writes DIR/tiers.csv and DIR/TIERS_SUMMARY.json. Model-generated inputs; tiers are a filter, not accuracy.
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
EXITS = {"NO_SPECIFIC_RELATION_STATED", "NULL_FINDING", "NOT_SUPPORTED", "UNPARSED"}
METHOD_RELATIONS = {"MEASURED_BY", "DETECTED_BY", "COMPARED_WITH", "VALIDATED_BY", "HAS_P_VALUE", "HAS_TAXONOMIC_RANK",
                    "IS_A", "SAME_AS", "SUBCLASS_OF", "PART_OF", "HAS_RELATIVE_ABUNDANCE", "HAS_ABSOLUTE_ABUNDANCE",
                    "PRECEDES", "FOLLOWS", "SHARES_SOURCE_WITH", "DERIVED_FROM"}
NON_BIO = {"statistic_measure", "temporal_concept", "dataset_resource", "study_design_concept", "bioinformatics_method",
           "experimental_method", "other_unclassified"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repair", type=Path, default=ROOT / "outputs/results/triple_repair_2026-11-09")
    a = ap.parse_args()
    rows = {}
    for l in open(a.repair / "repaired.jsonl", encoding="utf-8"):
        try:
            r = json.loads(l); rows[r["canonical_triple_id"]] = r
        except ValueError:
            pass
    out, tiers = [], collections.Counter()
    for r in rows.values():
        rel = r["relation"]
        specific = rel not in EXITS
        anchored = any(s in ("EXACT", "NORMALISED") for s in r.get("anchor_status") or [])
        fix_needed = bool(r["subject_fix"] or r["object_fix"] or r["subject_fix_rejected"] or r["object_fix_rejected"])
        fix_rejected = bool(r["subject_fix_rejected"] or r["object_fix_rejected"])
        drok = not (specific and rel not in METHOD_RELATIONS and r["subject_type"] in NON_BIO and r["object_type"] in NON_BIO)
        if specific and r["cue_found"] and anchored and drok and not fix_needed:
            tier = 1
        elif specific and r["cue_found"] and drok and not fix_rejected:
            tier = 2
        else:
            tier = 3
        tiers[tier] += 1
        out.append({"canonical_triple_id": r["canonical_triple_id"], "tier": tier, "old_relation": r["old_relation"],
                    "relation": rel, "direction": r["direction"], "relation_changed": rel != r["old_relation"],
                    "specific_relation": specific, "cue_found": r["cue_found"], "anchored": anchored,
                    "endpoint_repaired": bool(r["subject_fix"] or r["object_fix"]), "endpoint_fix_rejected": fix_rejected,
                    "domain_range_ok": drok, "null_finding": rel == "NULL_FINDING",
                    "subject": r["subject_fix"] or r["subject"], "object": r["object_fix"] or r["object"]})
    with open(a.repair / "tiers.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0])); w.writeheader(); w.writerows(out)
    gen = [o for o in out if o["old_relation"] == "OTHER_RELATION"]
    spec_old = [o for o in out if o["old_relation"] != "OTHER_RELATION"]
    summ = {"triples": len(out), "tiers": {str(k): v for k, v in sorted(tiers.items())},
            "final_relations_top": collections.Counter(o["relation"] for o in out).most_common(25),
            "specific_after_repair": sum(o["specific_relation"] for o in out),
            "specific_after_repair_with_cue": sum(o["specific_relation"] and o["cue_found"] for o in out),
            "generic_input": len(gen), "generic_now_specific_with_cue": sum(o["specific_relation"] and o["cue_found"] for o in gen),
            "specific_input": len(spec_old), "specific_input_kept": sum(o["relation"] == o["old_relation"] for o in spec_old),
            "null_findings": sum(o["null_finding"] for o in out),
            "not_supported": sum(o["relation"] == "NOT_SUPPORTED" for o in out),
            "endpoint_repaired": sum(o["endpoint_repaired"] for o in out),
            "endpoint_fix_rejected": sum(o["endpoint_fix_rejected"] for o in out),
            "domain_range_violations": sum(not o["domain_range_ok"] for o in out),
            "reversed": sum(o["direction"] == "REVERSED" for o in out),
            "note": "model-generated repair + deterministic gates; tiers are a filter, not accuracy; frozen CDM unchanged"}
    json.dump(summ, open(a.repair / "TIERS_SUMMARY.json", "w"), indent=1)
    print(json.dumps({k: summ[k] for k in ("triples", "tiers", "specific_after_repair_with_cue", "generic_now_specific_with_cue",
                                           "null_findings", "not_supported", "endpoint_repaired", "domain_range_violations")}, indent=1))


if __name__ == "__main__":
    main()
