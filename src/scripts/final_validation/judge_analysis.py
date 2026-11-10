"""Summarise the model-based evidence assessment (evidence_judge.py outputs) — model judgements, not accuracy.

Pipeline flags and classifications (is_primary_finding, cites_other_work, finding_domain, intervention_category)
are reported separately: a passage cannot state them, so the rubric does not apply. Invalid or missing verdict
labels are counted as INVALID, never mapped to a class.

    python judge_analysis.py
"""
from __future__ import annotations

import csv
import glob
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
D = ROOT / "paper/publication/final_validation/evidence_judge"
NOT_TEXT = {"is_primary_finding", "cites_other_work", "finding_domain", "intervention_category"}
LINKS = {"cohort_id", "assay_id", "dataset_id"}
VALID = {"PASS", "FAIL_NOT_SUPPORTED", "FAIL_WRONG_FIELD", "FAIL_CONTRADICTED", "UNCERTAIN"}


def link_verdict(v):
    """A per-id verdict dict counts as PASS only if every linked id is PASS (strict rule, as in the guidelines)."""
    if isinstance(v, dict) and v and all(isinstance(x, str) for x in v.values()):
        ks = {cls(x) for x in v.values()}
        return "PASS" if ks == {"PASS"} else ("FAIL_NOT_SUPPORTED" if "FAIL" in ks else "UNCERTAIN")
    return v


def cls(v):
    if not isinstance(v, str) or v not in VALID:
        return "INVALID"
    return "PASS" if v == "PASS" else ("UNCERTAIN" if v == "UNCERTAIN" else "FAIL")


def main():
    det = {(r["table"], r["record_id"], r["field"]): r for r in map(json.loads, open(D / "deterministic_value_checks.jsonl"))}
    anchor = {(r["table"], r["record_id"]): r["anchor"] for r in det.values()}
    J = {}
    meta = {}
    for model in ("llama", "mistral"):
        rows = [json.loads(l) for f in sorted(glob.glob(str(D / f"{model}.shard*.jsonl"))) for l in open(f)]
        J[model] = {(r["table"], r["record_id"]): r for r in rows}
        meta[model] = {"records": len(rows), "errors": sum("error" in r for r in rows),
                       "truncated": sum(r.get("finish") == "length" for r in rows)}
    out = {"judges": meta}
    fld_all = {}
    for model, recs in J.items():
        rec_v = defaultdict(Counter)
        fld = defaultdict(Counter)
        fail_kind = Counter()
        by_anchor = defaultdict(Counter)
        by_source = defaultdict(Counter)
        by_det = defaultdict(Counter)
        for (t, rid), r in recs.items():
            if "error" in r:
                continue
            rec_v[t][r.get("record") if r.get("record") in ("PASS", "FAIL", "UNCERTAIN") else "INVALID"] += 1
            for f, v in (r.get("fields") or {}).items():
                if f in LINKS:
                    v = link_verdict(v)
                k = cls(v)
                grp = "flag_or_classification" if f in NOT_TEXT else ("link" if f in LINKS else "text_value")
                fld[(t, grp)][k] += 1
                if grp != "text_value":
                    continue
                if k == "FAIL":
                    fail_kind[v] += 1
                by_anchor[anchor.get((t, rid), "?")][k] += 1
                d = det.get((t, rid, f))
                if d:
                    by_source["gap_filled" if d["gap_filled"] else "original_extraction"][k] += 1
                    by_det[d["result"]][k] += 1
        fld_all[model] = fld
        out[model] = {"record_level": {t: dict(v) for t, v in rec_v.items()},
                      "fields": {f"{t}|{g}": dict(v) for (t, g), v in sorted(fld.items())},
                      "text_value_fail_kinds": dict(fail_kind),
                      "text_value_by_anchor": {k: dict(v) for k, v in by_anchor.items()},
                      "text_value_by_source": {k: dict(v) for k, v in by_source.items()},
                      "text_value_by_deterministic_check": {k: dict(v) for k, v in by_det.items()}}
    # agreement between judges on text values and records
    agree = Counter()
    rec_agree = Counter()
    both_fail = []
    for key, a in J["llama"].items():
        b = J["mistral"].get(key)
        if not b or "error" in a or "error" in b:
            continue
        rec_agree[(a.get("record"), b.get("record"))] += 1
        for f, va in (a.get("fields") or {}).items():
            if f in NOT_TEXT or f in LINKS:
                continue
            vb = (b.get("fields") or {}).get(f)
            agree[(cls(va), cls(vb))] += 1
            if cls(va) == cls(vb) == "FAIL":
                d = det.get((key[0], key[1], f), {})
                both_fail.append((key[0], key[1], f, va, vb, d.get("result", ""), d.get("gap_filled", "")))
    with open(D / "BOTH_JUDGES_FAIL.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["table", "record_id", "field", "llama_verdict", "mistral_verdict", "deterministic_check", "gap_filled"])
        w.writerows(sorted(both_fail))
    def kappa(tab):
        n = sum(tab.values())
        if not n:
            return {"pairs": 0}
        po = sum(v for (x, y), v in tab.items() if x == y) / n
        labels = {x for k in tab for x in k}
        pa = {l: sum(v for (x, _), v in tab.items() if x == l) / n for l in labels}
        pb = {l: sum(v for (_, y), v in tab.items() if y == l) / n for l in labels}
        pe = sum(pa[l] * pb[l] for l in labels)
        return {"pairs": n, "observed_agreement": round(po, 3),
                "cohen_kappa_between_models": round((po - pe) / (1 - pe), 3) if pe < 1 else None,
                "both_pass": tab[("PASS", "PASS")], "both_fail": tab[("FAIL", "FAIL")],
                "table": {f"{x}|{y}": v for (x, y), v in sorted(tab.items())}}

    # rubric compliance: share of text-value fields given a valid label (a copied field value is not a verdict)
    out["rubric_compliance_text_values"] = {
        m: round(1 - sum(c.get("INVALID", 0) for (t, g), c in fld_all[m].items() if g == "text_value")
                 / max(1, sum(sum(c.values()) for (t, g), c in fld_all[m].items() if g == "text_value")), 3)
        for m in fld_all}
    out["judge_agreement_text_values"] = kappa(agree)
    out["judge_agreement_text_values_both_valid"] = kappa(Counter({k: v for k, v in agree.items() if "INVALID" not in k}))
    out["judge_agreement_records"] = {f"{x}|{y}": v for (x, y), v in sorted(rec_agree.items(), key=lambda kv: -kv[1])}
    (D / "judge_summary.json").write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps(out, indent=1)[:6000])


if __name__ == "__main__":
    main()
