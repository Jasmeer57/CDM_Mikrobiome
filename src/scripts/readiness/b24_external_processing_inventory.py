"""B24: inventory of what external model runs received (counts only; no text is written or printed).

Runs covered:
  * DeepSeek-V4-Flash judge (external API, 2026-11-03): CDM term strings (scheme "cdm") and triple subject/object labels;
    no sentences.
  * DeepSeek-V4-Flash evidence check and relabelling (2026-11-04): sentences of CC BY / CC0 papers (counts from their
    item files).
  * Claude AI-model spot checks (2026-11-05): 3,000 term strings; 500 triples with their CC BY / CC0 sentence.
For every string the question is: does it occur only in text-withheld papers? Normalisation: lower case, letters and
digits only. A string (normalised length >= 20) counts as "withheld-only" if every 20-character window of it (stride 5,
plus the last window) occurs in withheld text and at least one window occurs in neither text-included paper text nor
bibliographic metadata. Strings with normalised length < 20 are counted separately (too short to attribute).
Length bands use raw characters: < 20, 20-49, >= 50.
Writes outputs/results/rights/B24_EXTERNAL_PROCESSING_INVENTORY_2026-11-05.json.
"""
from __future__ import annotations

import csv
import json
import re
import sqlite3
from collections import Counter
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
B = ROOT / "outputs/results/benchmark"
OUT = ROOT / "outputs/results/rights/B24_EXTERNAL_PROCESSING_INVENTORY_2026-11-05.json"
K, STRIDE = 20, 5


def sq(s):
    return re.sub(r"[^0-9a-z]", "", (s or "").lower())


def windows(q):
    idx = list(range(0, len(q) - K + 1, STRIDE))
    if idx and idx[-1] != len(q) - K:
        idx.append(len(q) - K)
    return [q[i:i + K] for i in idx]


def main():
    rights = {r["paper_id"]: r["proposed_release_decision"] for r in csv.DictReader(open(ROOT / "paper/publication/rights/PAPER_RIGHTS_MATRIX.csv"))}
    c = sqlite3.connect(f"file:{ROOT / 'releases/cdm_v3/3.0.3/microbiome_cdm_v3.db'}?mode=ro", uri=True)
    wh, inc = set(), set()
    for pid, t in c.execute("SELECT paper_id, section_text_original FROM section"):
        q = sq(t)
        tgt = inc if rights.get(pid) == "INCLUDE_TEXT" else wh
        tgt.update(hash(q[i:i + K]) for i in range(len(q) - K + 1))
    for row in c.execute("SELECT title, journal, authors, keywords FROM paper"):
        for x in row:
            q = sq(x)
            inc.update(hash(q[i:i + K]) for i in range(len(q) - K + 1))
    print(f"windows: withheld {len(wh):,}, included+bib {len(inc):,}", flush=True)

    def classify(s):
        band = "<20" if len(s) < 20 else ("20-49" if len(s) < 50 else ">=50")
        q = sq(s)
        if len(q) < K:
            return band, "too_short_to_attribute"
        ws = [hash(w) for w in windows(q)]
        if all(h in wh for h in ws) and any(h not in inc for h in ws):
            return band, "withheld_only"
        return band, "not_withheld_only"

    res = {}

    def tally(name, strings):
        cnt = Counter()
        for s in strings:
            b, k = classify(s)
            cnt[f"{b}|{k}"] += 1
        res[name] = {"strings": sum(cnt.values()), "by_band": dict(sorted(cnt.items()))}
        print(name, res[name], flush=True)

    ent, tri = [], []
    for l in open(B / "llm_judge_deepseek_v4_flash/items.jsonl", encoding="utf-8"):
        d = json.loads(l)
        if d["task"] == "entity" and d.get("scheme") == "cdm":
            ent.append(d["string"])
        elif d["task"] == "triple":
            tri += [d["subject"], d["object"]]
    tally("deepseek_v4_judge_cdm_term_strings", ent)
    tally("deepseek_v4_judge_triple_labels", tri)
    tsc = [json.loads(l)["term"] for l in open(B / "term_spotcheck_claude_2026-11-05/sample.jsonl", encoding="utf-8")]
    tally("claude_spotcheck_terms", tsc)
    trc = [json.loads(l) for l in open(B / "triple_spotcheck_claude_2026-11-05/sample.jsonl", encoding="utf-8")]
    tally("claude_spotcheck_triple_labels", [x for d in trc for x in (d["subject"], d["object"])])
    res["claude_spotcheck_triple_sentences"] = {
        "sentences": len(trc), "papers_not_cc_by_cc0": sum(rights.get(d["paper_id"]) != "INCLUDE_TEXT" for d in trc)}
    ev = ROOT / "outputs/results/kg_2026-11-04/evidence_check"
    import gzip
    with gzip.open(ev / "evidence_verdicts.csv.gz", "rt", encoding="utf-8") as fh:
        evr = list(csv.DictReader(fh))
    res["deepseek_v4_evidence_check_sentences"] = {"items": len(evr),
                                                   "papers_not_cc_by_cc0": sum(rights.get(r["paper_id"]) != "INCLUDE_TEXT" for r in evr)}
    res["note"] = ("Counts only. 'withheld_only' = string attested only in text-withheld papers (window method above). "
                   "All DeepSeek-V4 and Claude runs also processed CC BY / CC0 material; whether external processing of "
                   "that material was permitted is part of the legal question.")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(res, indent=1) + "\n")
    print("written", OUT)


if __name__ == "__main__":
    main()
