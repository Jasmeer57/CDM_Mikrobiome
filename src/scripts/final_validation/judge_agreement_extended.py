"""Agreement statistics beyond Cohen's kappa for the schema-enforced catalogue judges (deterministic, no model run).

    python src/scripts/final_validation/judge_agreement_extended.py

Input: outputs/results/benchmark/judge_format_analysis_constrained_2026-11-09/summary.json (the both-valid
Llama x Mistral crosstab of field verdicts PASS / FAIL / UNC). Output: agreement_extended.json in the same folder:
observed agreement, Cohen's kappa, PABAK, Gwet's AC1, and per-label specific agreement 2*n_ii / (row_i + col_i),
for the 3-label table and for PASS vs FAIL (both decided). Kappa is low while observed agreement is high because
PASS dominates (kappa paradox); AC1 and per-label agreement show where the judges agree and where they do not.
These are agreement between two models, not accuracy. Written with Claude Code (declare).
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
D = ROOT / "outputs/results/benchmark/judge_format_analysis_constrained_2026-11-09"


def stats(t, labels):
    n = sum(t[a][b] for a in labels for b in labels)
    po = sum(t[a][a] for a in labels) / n
    row = {a: sum(t[a][b] for b in labels) / n for a in labels}
    col = {b: sum(t[a][b] for a in labels) / n for b in labels}
    pe = sum(row[a] * col[a] for a in labels)
    q = len(labels)
    pi = {a: (row[a] + col[a]) / 2 for a in labels}
    pe_ac1 = sum(p * (1 - p) for p in pi.values()) / (q - 1)
    spec = {a: round(2 * t[a][a] / (sum(t[a][b] for b in labels) + sum(t[b][a] for b in labels)), 3) for a in labels}
    return {"n": n, "observed": round(po, 3), "kappa": round((po - pe) / (1 - pe), 3),
            "pabak": round((q * po - 1) / (q - 1), 3), "gwet_ac1": round((po - pe_ac1) / (1 - pe_ac1), 3),
            "specific_agreement": spec, "label_share_mean_of_judges": {a: round(v, 3) for a, v in pi.items()}}


def main():
    s = json.load(open(D / "summary.json", encoding="utf-8"))
    t = s["both_valid_crosstab_llama_rows_mistral_cols"]
    out = {"what": "catalogue judges (Llama-3.1-8B, Mistral-7B), schema-enforced, both-valid field verdicts; "
                   "agreement between two models, not accuracy",
           "three_label": stats(t, ["PASS", "FAIL", "UNC"]),
           "pass_vs_fail_both_decided": stats(t, ["PASS", "FAIL"])}
    (D / "agreement_extended.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
