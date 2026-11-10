"""Ask DeepSeek-V4.1-Flash (Fraunhofer Genie) whether each non-English ontology label matches its English name.

    python src/scripts/final_validation/check_label_translations.py

Input: outputs/results/non_english_scan_2026-11-08/omop_chinese_to_english.tsv (OMOP concept id, Chinese label,
official English concept_name from the local OMOP CONCEPT.csv) plus the one Japanese NANDO label in CDM 3.0.3.
Only vocabulary labels are sent: no paper text, quote or section (rights rule, B24). Model judgement of a
translation, not a curated mapping. Writes label_check.jsonl and label_check_summary.json next to the input.
"""
from __future__ import annotations

import collections
import csv
import json
import sys
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
sys.path.insert(0, str(ROOT / "src/scripts/ner_llm_judge"))
from judge import Client, load_cfg, parse  # noqa: E402

OUT = ROOT / "outputs/results/non_english_scan_2026-11-08"
MODEL = "deepseek-ai/DeepSeek-V4.1-Flash"
BATCH = 30
TASK = """Each item is [n, "foreign-language ontology label", "proposed English name", "vocabulary"].
The foreign label is a Chinese or Japanese synonym of a concept in a standard vocabulary (LOINC, NANDO).
Decide whether the proposed English name names the same concept as the foreign label.
Answer JSON {"r": [[n, verdict, "your literal English translation of the foreign label", "short note"], ...]}
verdict: MATCH (same concept), PARTIAL (same concept but a detail differs, e.g. specimen or method), MISMATCH.
One row per item, same n. No other text."""


def main():
    items = []
    with open(OUT / "omop_chinese_to_english.tsv", encoding="utf-8") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            items.append({"id": r["omop_concept_id"], "foreign": r["chinese_label_in_corpus_2.2.0"],
                          "english": r["english_concept_name"], "vocab": r["vocabulary"]})
    items.append({"id": "NANDO:1200027", "foreign": "視神経脊髄炎", "english": "neuromyelitis optica",
                  "vocab": "NANDO (via BioPortal; English name proposed, not from a local vocabulary file)"})
    cfg = load_cfg(str(ROOT / "src/scripts/ner_llm_judge/config.yml"))
    cfg["api"]["model"] = MODEL
    cl = Client(cfg["api"])
    res = []
    for k in range(0, len(items), BATCH):
        batch = items[k:k + BATCH]
        rows = [[n, it["foreign"], it["english"], it["vocab"]] for n, it in enumerate(batch)]
        content, finish, usage = cl.chat(TASK + "\n\nItems:\n" + json.dumps(rows, ensure_ascii=False))
        got = {r[0]: r for r in (parse(content) or {}).get("r", []) if isinstance(r, list) and len(r) == 4}
        for n, it in enumerate(batch):
            g = got.get(n)
            res.append({**it, "model": MODEL, "verdict": g[1] if g else "UNPARSED",
                        "model_translation": g[2] if g else "", "note": g[3] if g else ""})
        print(f"{min(k + BATCH, len(items))}/{len(items)}", flush=True)
    with open(OUT / "label_check.jsonl", "w", encoding="utf-8") as f:
        for r in res:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    summ = {"model": MODEL, "what": "model judgement of label translations; vocabulary labels only, no paper text",
            "items": len(res), "verdicts": dict(collections.Counter(r["verdict"] for r in res))}
    json.dump(summ, open(OUT / "label_check_summary.json", "w"), indent=1)
    print(json.dumps(summ))


if __name__ == "__main__":
    main()
