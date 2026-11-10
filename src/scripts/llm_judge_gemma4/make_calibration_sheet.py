"""P8 - build the 10-item human calibration sheet.

Deterministic selection: 2-3 items per artifact (>=2 drawn from the flagged
repair queue), so a human can spot-check whether the Gemma 4 E4B judge agrees
with them. This is the ONLY place human judgment enters; it calibrates the judge,
it does not turn the pipeline into a human gold standard.

Writes:
  $OUTD/HUMAN_CALIBRATION_SHEET.csv   (human_verdict / human_notes left empty)
  $OUTD/HUMAN_CALIBRATION_INSTRUCTIONS.md

Usage:
  python make_calibration_sheet.py
"""

_CDM_ROOT = next(p for p in __import__("pathlib").Path(__file__).resolve().parents
                 if (p / ".cdm_root").is_file())  # repo root, found at run time
import argparse
import csv
import hashlib
import json
import os

ROOT = str(_CDM_ROOT)
OUTD = os.path.join(ROOT, "outputs/logs", "llm_judge")
SAMPLE_PREFIX = "judge-gemma4-v1|calib|"
TARGET = 10

# per-artifact calibration question + the judge metric we are checking
QUESTION = {
    "C1": "Is the extracted catalogue record faithful to the evidence text "
          "(metric_faithfulness)?",
    "C2": "Is the canonical CDM type correct for this inventory term "
          "(metric_factual_correctness)?",
    "C3": "Is the ontology mapping correct for this term "
          "(metric_factual_correctness)?",
    "C4": "Is the extracted triple faithful to the evidence text "
          "(metric_faithfulness)?",
}
METRIC = {
    "C1": "metric_faithfulness", "C4": "metric_faithfulness",
    "C2": "metric_factual_correctness", "C3": "metric_factual_correctness",
}


def rank(sid):
    return hashlib.sha1((SAMPLE_PREFIX + str(sid)).encode()).hexdigest()


def load_inputs(outdir):
    by_art = {}
    for art in ("C1", "C2", "C3", "C4"):
        p = os.path.join(outdir, "input_%s.jsonl" % art)
        if not os.path.exists(p):
            continue
        rows = [json.loads(l) for l in open(p) if l.strip()]
        by_art[art] = {r["item_id"]: r for r in rows}
    return by_art


def load_queue(outdir):
    p = os.path.join(outdir, "repair_queue.jsonl")
    if not os.path.exists(p):
        return []
    return [json.loads(l) for l in open(p) if l.strip()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", default=OUTD)
    args = ap.parse_args()

    items = load_inputs(args.outdir)
    queue = load_queue(args.outdir)
    flagged_by_art = {}
    for q in queue:
        flagged_by_art.setdefault(q["artifact"], []).append(q["item_id"])

    picked = []  # (item_id, artifact, source)
    # 1) take flagged items first (>=2 overall, spread across artifacts)
    for art in ("C1", "C2", "C3", "C4"):
        for iid in sorted(set(flagged_by_art.get(art, [])), key=rank)[:1]:
            picked.append((iid, art, "flagged"))
    # 2) top up to TARGET with a deterministic mix (2-3 per artifact)
    per_art_target = {"C1": 3, "C2": 3, "C3": 2, "C4": 2}
    for art in ("C1", "C2", "C3", "C4"):
        want = per_art_target[art]
        have = sum(1 for _, a, _ in picked if a == art)
        if have >= want:
            continue
        pool = [i for i in items.get(art, {}) if i not in {p[0] for p in picked}]
        for iid in sorted(pool, key=rank)[:want - have]:
            picked.append((iid, art, "random"))
    picked = picked[:TARGET]

    rows = []
    for iid, art, source in picked:
        item = items.get(art, {}).get(iid, {})
        q = next((x for x in queue if x["item_id"] == iid), None)
        rows.append({
            "item_id": iid,
            "artifact": art,
            "question": QUESTION.get(art, "Is this extraction correct?"),
            "source_data_json": json.dumps(item, ensure_ascii=False),
            "selection": source,
            "judge_metric": METRIC.get(art, ""),
            "judge_verdict": (q or {}).get("verdict", ""),
            "human_verdict": "",
            "human_notes": "",
        })

    sheet = os.path.join(args.outdir, "HUMAN_CALIBRATION_SHEET.csv")
    cols = ["item_id", "artifact", "question", "source_data_json", "selection",
            "judge_metric", "judge_verdict", "human_verdict", "human_notes"]
    with open(sheet, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow(r)

    n_flagged = sum(1 for r in rows if r["selection"] == "flagged")
    instr = os.path.join(args.outdir, "HUMAN_CALIBRATION_INSTRUCTIONS.md")
    with open(instr, "w") as fh:
        fh.write(INSTRUCTIONS.format(n=len(rows), flagged=n_flagged))
    print("wrote %s (%d items, %d flagged) and %s" % (sheet, len(rows), n_flagged, instr))


INSTRUCTIONS = """# Human calibration instructions

This sheet calibrates the **LLM-as-judge** (Gemma 4 E4B, 4-bit). It is **not** a
human gold standard and does not replace one; it only checks whether the judge
agrees with a human on a small spot-check.

## What to do
1. Open `HUMAN_CALIBRATION_SHEET.csv` ({n} rows; {flagged} were flagged by the judge).
2. For each row, read `source_data_json` (the extracted item and its evidence) and
   answer the `question` in `human_verdict` using the metric's verdict vocabulary:
   - `metric_faithfulness` (C1, C4): `FAITHFUL | PARTIALLY_FAITHFUL | UNFAITHFUL | UNCERTAIN`
   - `metric_factual_correctness` (C2, C3): `CORRECT | INCORRECT | UNCERTAIN`
3. Optionally add one line of justification in `human_notes`.
4. Save the CSV in place (do not rename).

## How the result is used
Compare `human_verdict` against `judge_verdict`:
- **>= 8/10 agree** -> run the full-corpus judge evaluation as planned.
- **6-7/10 agree** -> report full results **with a calibration caveat**.
- **< 6/10 agree** -> **drop the judge-based claim**; the judge is not reliable enough.

No pipeline item is auto-fixed from this sheet.
"""


if __name__ == "__main__":
    main()
