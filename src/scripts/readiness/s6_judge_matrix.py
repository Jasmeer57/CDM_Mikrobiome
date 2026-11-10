"""Supplementary S6: judge-vs-judge matrix on catalogue text values (Llama vs Mistral).

This is AGREEMENT BETWEEN TWO MODEL JUDGES, not an error taxonomy, not accuracy and not inter-annotator agreement.
It reads the frozen `final_validation/evidence_judge/judge_summary.json` (written by
`src/scripts/final_validation/judge_analysis.py`, whose table keys are "<llama verdict>|<mistral verdict>"),
recomputes observed agreement and Cohen's kappa as a check, and writes the matrices, definitions and input hash
to a new dated directory. Nothing frozen is modified. Rendering a figure from `s6_matrix_*.csv` is a separate step.

    python src/scripts/readiness/s6_judge_matrix.py [--out DIR]
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import date
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
SRC = ROOT / "paper/publication/final_validation/evidence_judge/judge_summary.json"
LABELS = ["PASS", "FAIL", "UNCERTAIN", "INVALID"]
DEFS = {
    "PASS": "the judge says the stored value is supported by its evidence quote",
    "FAIL": "the judge says the value is not supported, belongs to another field, or is contradicted "
            "(FAIL_NOT_SUPPORTED, FAIL_WRONG_FIELD, FAIL_CONTRADICTED)",
    "UNCERTAIN": "the judge declined to decide",
    "INVALID": "the judge's answer is not a rubric label (e.g. it copied the field value); a rubric failure of the "
               "judge, not a verdict on the value",
}


def stats(m):
    labs = [l for l in LABELS if any(m[l].values()) or any(m[r][l] for r in LABELS)]
    n = sum(m[r][c] for r in labs for c in labs)
    po = sum(m[l][l] for l in labs) / n
    pe = sum((sum(m[l][c] for c in labs) / n) * (sum(m[r][l] for r in labs) / n) for l in labs)
    return {"pairs": n, "observed_agreement": round(po, 3), "cohen_kappa": round((po - pe) / (1 - pe), 3)}


def matrix(table, drop_invalid):
    m = {r: {c: 0 for c in LABELS} for r in LABELS}
    for k, v in table.items():
        r, c = k.split("|")
        m[r][c] += v
    if drop_invalid:
        for l in LABELS:
            m["INVALID"][l] = m[l]["INVALID"] = 0
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path,
                    default=ROOT / f"outputs/results/benchmark/s6_judge_matrix_{date.today().isoformat()}")
    a = ap.parse_args()
    js = json.load(open(SRC))
    a.out.mkdir(parents=True, exist_ok=True)
    meta = {"generated": date.today().isoformat(), "input": str(SRC.relative_to(ROOT)),
            "input_sha256": hashlib.sha256(SRC.read_bytes()).hexdigest(),
            "rows": "Llama-3.1-8B-Instruct (AWQ) verdict", "columns": "Mistral-7B-Instruct-v0.3 (AWQ) verdict",
            "unit": "one catalogue text-value field of one record, judged by both models (links and flags excluded)",
            "rubric_compliance_text_values": js["rubric_compliance_text_values"], "definitions": DEFS, "variants": {}}
    for name, key, drop in (("all_labels", "judge_agreement_text_values", False),
                            ("both_valid", "judge_agreement_text_values_both_valid", True)):
        stored = js[key]
        m = matrix(stored["table"], drop)
        s = stats(m)
        ok = s["pairs"] == stored["pairs"] and s["cohen_kappa"] == stored["cohen_kappa_between_models"] \
            and s["observed_agreement"] == stored["observed_agreement"]
        if not ok:
            raise SystemExit(f"{name}: recomputed {s} does not match stored {stored}")
        labs = [l for l in LABELS if not (drop and l == "INVALID")]
        with open(a.out / f"s6_matrix_{name}.csv", "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["llama \\ mistral"] + labs + ["row total"])
            for r in labs:
                w.writerow([r] + [m[r][c] for c in labs] + [sum(m[r][c] for c in labs)])
            w.writerow(["column total"] + [sum(m[r][c] for r in labs) for c in labs] + [s["pairs"]])
        meta["variants"][name] = s | {"matches_stored": ok, "matrix": {r: {c: m[r][c] for c in labs} for r in labs}}
    json.dump(meta, open(a.out / "s6_summary.json", "w"), indent=1)

    v, b = meta["variants"]["all_labels"], meta["variants"]["both_valid"]
    L = ["# S6: judge-vs-judge matrix on catalogue text values", "",
         "**What this is:** agreement between two model judges (Llama rows, Mistral columns) on the same text-value "
         "fields. **Not** an error taxonomy, not accuracy, not inter-annotator agreement; it cannot answer a request "
         "for per-category accuracy. Caption it as model–model agreement.", "",
         f"- All labels: {v['pairs']:,} pairs, observed agreement {v['observed_agreement']}, κ {v['cohen_kappa']} "
         "(`s6_matrix_all_labels.csv`).",
         f"- Both judges gave a valid label: {b['pairs']:,} pairs, observed agreement {b['observed_agreement']}, "
         f"κ {b['cohen_kappa']} (`s6_matrix_both_valid.csv`; registered as J04 0.85 / J05 0.282).",
         f"- Rubric compliance on text values: Llama {meta['rubric_compliance_text_values']['llama']}, Mistral "
         f"{meta['rubric_compliance_text_values']['mistral']}. Keep the INVALID row/column visible in any figure: "
         "most disagreement in the all-labels matrix is Mistral not answering in the rubric.",
         "- Llama also took part in G3 curation, so the judges are not independent of the pipeline.", "",
         "## Labels", ""] + [f"- **{k}**: {d}" for k, d in DEFS.items()] + [
         "", "## Reproducibility", "",
         f"- Input: `{meta['input']}` sha256 {meta['input_sha256']}",
         "- Recomputed pairs, observed agreement and κ match the stored values for both variants (script stops "
         "otherwise).", "- Regenerate: `python src/scripts/readiness/s6_judge_matrix.py`"]
    (a.out / "S6_JUDGE_MATRIX.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("written:", a.out, "| all labels κ", v["cohen_kappa"], "| both valid κ", b["cohen_kappa"])


if __name__ == "__main__":
    main()
