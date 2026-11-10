"""P7 - build a 10-item human calibration sheet from judge outputs.

Purpose: a small human spot-check to decide whether the LLM judge is trustworthy
enough to run at full scale. This is a CALIBRATION check on the judge, not a
human gold standard over the corpus.

Selection (10 items):
  - 3 triples
  - 3 mappings
  - 2 records
  - 2 "worst cases" (lowest judge confidence, any artifact)

If judge outputs are absent, falls back to a deterministic sample of the
stratified sample so the sheet can still be produced (human columns empty).

Writes $OUTD/labeled/HUMAN_CALIBRATION_SHEET.csv and
$OUTD/labeled/HUMAN_CALIBRATION_INSTRUCTIONS.md.
"""

_CDM_ROOT = next(p for p in __import__("pathlib").Path(__file__).resolve().parents
                 if (p / ".cdm_root").is_file())  # repo root, found at run time
import argparse
import csv
import hashlib
import json
import os

ROOT = str(_CDM_ROOT)
OUTD = os.path.join(ROOT, "outputs/logs", "gold_standard")
LAB = os.path.join(OUTD, "labeled")

VERDICT_FIELD = {
    "triples": "verdict", "mappings": "verdict", "records": "verdict",
    "types": "verdict_inventory_type",
}
JUDGE_FILES = {
    "records": "judge_records.jsonl", "triples": "judge_triples.jsonl",
    "mappings": "judge_mappings.jsonl", "types": "judge_types.jsonl",
}
ALLOWED = {
    "triples": "SENSIBLE|PLAUSIBLE_BUT_WEAK|NONSENSE|UNCERTAIN",
    "mappings": "VALID|INVALID|TOO_BROAD|TOO_NARROW|UNCERTAIN",
    "records": "SUPPORTED|PARTIALLY_SUPPORTED|NOT_SUPPORTED|UNCERTAIN",
    "types": "CORRECT|INCORRECT|UNCERTAIN",
}


def rank(item_id):
    return hashlib.sha1(("cal-v1|" + str(item_id)).encode()).hexdigest()


def load_jsonl(p):
    rows = []
    if os.path.exists(p):
        with open(p) as fh:
            for line in fh:
                rows.append(json.loads(line))
    return rows


def pick(items, k):
    return sorted(items, key=lambda r: rank(r["item_id"]))[:k]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--indir", default=LAB)
    args = ap.parse_args()

    sample = load_jsonl(os.path.join(args.indir, "sample_input.jsonl"))
    by_art = {}
    for r in sample:
        by_art.setdefault(r["artifact"], []).append(r)

    # judge verdicts keyed by item_id
    verdicts = {}
    conf = {}
    for art, fname in JUDGE_FILES.items():
        for r in load_jsonl(os.path.join(args.indir, fname)):
            verdicts[r["item_id"]] = (art, r.get(VERDICT_FIELD[art]))
            conf[r["item_id"]] = r.get("confidence")

    chosen = []
    for art, k in [("triples", 3), ("mappings", 3), ("records", 2)]:
        chosen.append((art, pick(by_art.get(art, []), k)))

    # worst cases: lowest numeric confidence across all judged items. When no
    # judge confidences exist yet, fall back to a deterministic pick so the sheet
    # is always 10 items (re-run after run_judge.py to get true worst cases).
    judged = [r for r in sample if isinstance(conf.get(r["item_id"]), (int, float))]
    if judged:
        worst = sorted(judged, key=lambda r: (conf[r["item_id"]], rank(r["item_id"])))[:2]
    else:
        worst = pick(sample, 2)
    chosen.append(("worst_case", worst))

    fieldnames = ["n", "artifact", "item_id", "judge_verdict", "judge_confidence",
                  "prompt_version", "question", "item_summary",
                  "human_verdict", "human_confidence", "human_notes"]
    out_csv = os.path.join(args.indir, "HUMAN_CALIBRATION_SHEET.csv")
    n = 0
    with open(out_csv, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        for art, rows in chosen:
            for r in rows:
                n += 1
                real_art = r["artifact"]
                jv = verdicts.get(r["item_id"], (real_art, None))[1]
                summary = summarize(r)
                w.writerow({
                    "n": n,
                    "artifact": art if art != "worst_case" else "worst_case:" + real_art,
                    "item_id": r["item_id"],
                    "judge_verdict": jv if jv is not None else "(no judge output)",
                    "judge_confidence": conf.get(r["item_id"], ""),
                    "prompt_version": "judge-v1",
                    "question": "Is the judge's verdict correct for this item? "
                                "Allowed: " + ALLOWED.get(real_art, "?"),
                    "item_summary": summary,
                    "human_verdict": "",
                    "human_confidence": "",
                    "human_notes": "",
                })

    instructions = os.path.join(args.indir, "HUMAN_CALIBRATION_INSTRUCTIONS.md")
    with open(instructions, "w") as fh:
        fh.write(INSTRUCTIONS)

    print("wrote %s (%d items)" % (out_csv, n))
    print("wrote %s" % instructions)
    if not verdicts:
        print("NOTE: no judge outputs found; judge_verdict column is a placeholder.")
        print("      Re-run this script after run_judge.py to populate it.")


def summarize(r):
    a = r["artifact"]
    if a == "triples":
        return "%s --%s--> %s | ev: %s" % (
            r.get("subject_surface", ""), r.get("relation", ""), r.get("object_surface", ""),
            (r.get("evidence_text", "") or "")[:160])
    if a == "mappings":
        return "term=%s -> %s:%s (%s) | def: %s" % (
            r.get("term", ""), r.get("ontology_name", ""), r.get("concept_id", ""),
            r.get("concept_label", ""), (r.get("term_definition", "") or "")[:160])
    if a == "records":
        return "claim: %s | ev: %s" % (
            (r.get("claim_text", "") or "")[:160], (r.get("evidence_text", "") or "")[:160])
    if a == "types":
        return "term=%s inv=%s canon=%s" % (
            r.get("inventory_term", ""), r.get("inventory_types", ""),
            r.get("canonical_cdm_type", ""))
    return ""


INSTRUCTIONS = """# Human Calibration of the LLM Judge

This is a short (~15 min) human spot-check used **only** to decide whether the
automated LLM judge is trustworthy enough to run at full scale. It is **not** a
human gold standard over the corpus and **not** human validation of the
extraction pipeline.

## Steps
1. Open `HUMAN_CALIBRATION_SHEET.csv`.
2. For each of the 10 rows, read `item_summary` and the `question`.
3. Fill `human_verdict` with one allowed value (listed in `question`).
   Optionally fill `human_confidence` (0.0-1.0) and `human_notes`.
4. Compare your `human_verdict` with the `judge_verdict` column.

## Decision rule
- If **>= 8 / 10** human verdicts agree with the judge verdicts, the judge is
  considered calibrated enough to run at full scale.
- If **< 8 / 10**, do **not** run the full-scale judge; the corresponding claim
  is dropped and the judge prompts/model must be revised first.

## Scope reminder
Agreement here measures whether the judge reproduces a human's judgment on 10
spot items. It does not validate the underlying extraction pipeline, and it must
never be reported as "human validation" or a "gold standard".
"""


if __name__ == "__main__":
    main()
