"""Where do the schema-enforced catalogue judges disagree? Agreement by field, by gap-filled status and by the
deterministic string check (deterministic; no model run).

    python src/scripts/final_validation/judge_disagreement_by_field.py

Inputs: outputs/results/benchmark/evidence_judge_constrained_2026-11-09/{llama,mistral}.shard*.jsonl and the frozen
deterministic checks (paper/publication/final_validation/evidence_judge/deterministic_value_checks.jsonl).
Verdicts collapsed to PASS / FAIL (any FAIL_*) / UNC. Output in
outputs/results/benchmark/judge_format_analysis_constrained_2026-11-09/: disagreement_by_field.csv,
disagreement_summary.json. Agreement between two models, not accuracy. Written with Claude Code (declare).
"""
from __future__ import annotations

import csv
import glob
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
sys.path.insert(0, str(ROOT / "src/scripts/final_validation"))
from judge_agreement_extended import stats  # noqa: E402

J = ROOT / "outputs/results/benchmark/evidence_judge_constrained_2026-11-09"
DET = ROOT / "paper/publication/final_validation/evidence_judge/deterministic_value_checks.jsonl"
OUT = ROOT / "outputs/results/benchmark/judge_format_analysis_constrained_2026-11-09"
L = ["PASS", "FAIL", "UNC"]


def norm(v):
    if v == "PASS":
        return "PASS"
    if isinstance(v, str) and v.startswith("FAIL"):
        return "FAIL"
    if v == "UNCERTAIN":
        return "UNC"
    return None


def load(m):
    d = {}
    for f in sorted(glob.glob(str(J / f"{m}.shard*.jsonl"))):
        for line in open(f, encoding="utf-8"):
            r = json.loads(line)
            for k, v in (r.get("fields") or {}).items():
                d[(r["table"], r["record_id"], k)] = norm(v)
    return d


def table(pairs):
    t = {a: {b: 0 for b in L} for a in L}
    for a, b in pairs:
        t[a][b] += 1
    return t


def summ(pairs):
    t = table(pairs)
    s = stats(t, L) if len(pairs) >= 30 else {"n": len(pairs)}
    if len(pairs) >= 30:
        s["disagree_pct"] = round(100 * (1 - s["observed"]), 1)
        s["pass_fail_conflicts"] = t["PASS"]["FAIL"] + t["FAIL"]["PASS"]
        s["llama_fail_mistral_pass"], s["llama_pass_mistral_fail"] = t["FAIL"]["PASS"], t["PASS"]["FAIL"]
        s["any_unc_disagreement"] = sum(t[a][b] for a in L for b in L if a != b and "UNC" in (a, b))
    return s


def main():
    la, mi = load("llama"), load("mistral")
    det = {}
    for line in open(DET, encoding="utf-8"):
        r = json.loads(line)
        det[(r["table"], r["record_id"], r["field"])] = (r.get("gap_filled"), r.get("check"), r.get("result"))
    groups = defaultdict(list)
    for k, a in la.items():
        b = mi.get(k)
        if a is None or b is None:
            continue
        gf, chk, res = det.get(k, (None, None, None))
        groups[("ALL",)].append((a, b))
        groups[("field", k[0], k[2])].append((a, b))
        groups[("gap_filled", str(gf))].append((a, b))
        groups[("det_check", f"{chk}:{res}")].append((a, b))
    rows = []
    for g, pairs in groups.items():
        s = summ(pairs)
        if "observed" not in s:
            continue
        rows.append({"group": g[0], "key": "|".join(g[1:]), "n": s["n"], "observed": s["observed"], "kappa": s["kappa"],
                     "gwet_ac1": s["gwet_ac1"], "spec_PASS": s["specific_agreement"]["PASS"],
                     "spec_FAIL": s["specific_agreement"]["FAIL"], "spec_UNC": s["specific_agreement"]["UNC"],
                     "disagree_pct": s["disagree_pct"], "pass_fail_conflicts": s["pass_fail_conflicts"],
                     "llama_fail_mistral_pass": s["llama_fail_mistral_pass"], "llama_pass_mistral_fail": s["llama_pass_mistral_fail"],
                     "any_unc_disagreement": s["any_unc_disagreement"]})
    rows.sort(key=lambda r: (r["group"], -r["n"] * (1 - r["observed"])))
    with open(OUT / "disagreement_by_field.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    fields = [r for r in rows if r["group"] == "field"]
    tot = sum(r["n"] * (1 - r["observed"]) for r in fields)
    top = sorted(fields, key=lambda r: -r["n"] * (1 - r["observed"]))
    cum, top_share = 0, []
    for r in top[:10]:
        cum += r["n"] * (1 - r["observed"])
        top_share.append({"field": r["key"], "n": r["n"], "disagree_pct": r["disagree_pct"], "kappa": r["kappa"],
                          "spec_FAIL": r["spec_FAIL"], "cum_share_of_all_disagreements": round(cum / tot, 3)})
    out = {"fields": len(fields), "top10_fields_by_disagreement_volume": top_share,
           "by_gap_filled": [r for r in rows if r["group"] == "gap_filled"],
           "by_deterministic_check": [r for r in rows if r["group"] == "det_check"]}
    (OUT / "disagreement_summary.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
