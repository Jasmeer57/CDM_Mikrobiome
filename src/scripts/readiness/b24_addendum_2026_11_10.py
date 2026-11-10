"""B24 addendum (2026-11-10) and rights check of the CDM 3.1.0 definitions layer. Counts and ids only; no text printed.

    python src/scripts/readiness/b24_addendum_2026_11_10.py          # ~30 GB RAM; run as a CPU SLURM job

Part A - what the FhGenie runs received, by the 2026-11-05 window method (b24_external_processing_inventory.py):
  * DeepSeek-V4.1 triple-label judge (2026-11-07): subject / object strings (was "NOT YET ASSESSED").
  * Term relevance screen (2026-11-09, concept_relevance_fhgenie.py --terms): 157,990 term labels.
  * Concept relevance screen (2026-11-09): ontology labels only (not paper text): counted, not attributed.
Part B - rights check of the model-generated definitions layer (CDM 3.1.0 term_enrichment), local Qwen3.5-4B, never
  sent outside. A MODEL_definition / MODEL_full_form / MODEL_synonyms value is flagged when it contains a 40-character
  normalised window (lower case, letters and digits) that occurs in text-withheld papers and in neither text-included
  papers nor bibliographic metadata (a verbatim span of withheld text). SOURCE_extracted_definitions are paper quotes:
  flagged when any contributing term_definition row comes from a paper whose decision is not INCLUDE_TEXT.
Outputs (outputs/results/rights/): B24_EXTERNAL_PROCESSING_ADDENDUM_2026-11-10.json (counts);
  DEFINITIONS_RIGHTS_FLAGS_2026-11-10.csv (term_id + flags; no text) for the release filter.
Written with Claude Code (declare).
"""
from __future__ import annotations

import csv
import json
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
sys.path.insert(0, str(ROOT / "src/scripts/readiness"))
import b24_external_processing_inventory as B  # noqa: E402  (sq, windows, K)

DB303 = ROOT / "releases/cdm_v3/3.0.3/microbiome_cdm_v3.db"
DB310 = ROOT / "releases/cdm_v3/3.1.0/microbiome_cdm_v3.1.0.db"
R = ROOT / "outputs/results"
OUT = R / "rights"
K2 = 40


def main():
    rights = {r["paper_id"]: r["proposed_release_decision"]
              for r in csv.DictReader(open(ROOT / "paper/publication/rights/PAPER_RIGHTS_MATRIX.csv", encoding="utf-8"))}
    c = sqlite3.connect(f"file:{DB303}?mode=ro", uri=True)
    wh, inc, wh2, inc2 = set(), set(), set(), set()
    for pid, t in c.execute("SELECT paper_id, section_text_original FROM section"):
        q = B.sq(t)
        a, b = (inc, inc2) if rights.get(pid) == "INCLUDE_TEXT" else (wh, wh2)
        a.update(hash(q[i:i + B.K]) for i in range(len(q) - B.K + 1))
        b.update(hash(q[i:i + K2]) for i in range(len(q) - K2 + 1))
    for row in c.execute("SELECT title, journal, authors, keywords FROM paper"):
        for x in row:
            q = B.sq(x)
            inc.update(hash(q[i:i + B.K]) for i in range(len(q) - B.K + 1))
            inc2.update(hash(q[i:i + K2]) for i in range(len(q) - K2 + 1))
    print(f"windows k20 withheld {len(wh):,} included {len(inc):,}; k40 withheld {len(wh2):,}", flush=True)

    def classify(s):
        band = "<20" if len(s) < 20 else ("20-49" if len(s) < 50 else ">=50")
        q = B.sq(s)
        if len(q) < B.K:
            return band, "too_short_to_attribute"
        ws = [hash(w) for w in B.windows(q)]
        return band, ("withheld_only" if all(h in wh for h in ws) and any(h not in inc for h in ws) else "not_withheld_only")

    def tally(strings):
        cnt = Counter("|".join(classify(s)) for s in strings)
        return {"strings": sum(cnt.values()), "withheld_only": sum(v for k, v in cnt.items() if k.endswith("|withheld_only")),
                "by_band": dict(sorted(cnt.items()))}

    res = {"addendum_to": "outputs/results/rights/B24_EXTERNAL_PROCESSING_ADDENDUM_2026-11-07.json", "generated": "2026-11-10",
           "method": "2026-11-05 window method (k=20, stride 5); counts only"}
    tri = [json.loads(l) for l in open(R / "benchmark/llm_judge_deepseek_v41_triples/items.jsonl", encoding="utf-8")]
    res["deepseek_v41_judge_triple_labels"] = {"gateway": "FhGenie", "date": "2026-11-07", "items": len(tri),
                                               "labels": tally([x for d in tri for x in (d["subject"], d["object"])])}
    terms = [json.loads(l) for l in open(R / "term_relevance_2026-11-09/judgements.jsonl", encoding="utf-8")]
    res["term_relevance_screen"] = {"gateway": "FhGenie", "model": "deepseek-ai/DeepSeek-V4.1-Flash", "date": "2026-11-09",
                                    "sent": "term label + CDM type (no paper text, no definitions)",
                                    "labels": tally([d["label"] for d in terms])}
    nconc = sum(1 for _ in open(R / "concept_relevance_2026-11-09/judgements.jsonl", encoding="utf-8"))
    res["concept_relevance_screen"] = {"gateway": "FhGenie", "date": "2026-11-09", "labels": nconc,
                                       "sent": "ontology concept label + prefix + CDM type; labels come from ontologies, "
                                               "not from papers (licensed-vocabulary labels: see B23)"}
    print(json.dumps(res, indent=1), flush=True)

    # ---- Part B: definitions layer
    def withheld_span(s):
        q = B.sq(s)
        return any(hash(q[i:i + K2]) in wh2 and hash(q[i:i + K2]) not in inc2 for i in range(len(q) - K2 + 1))

    srcbad = Counter()
    for tid, pid in c.execute("SELECT term_id, paper_id FROM term_definition"):
        if rights.get(pid) != "INCLUDE_TEXT":
            srcbad[tid] += 1
    c3 = sqlite3.connect(f"file:{DB310}?mode=ro", uri=True)
    flags = Counter()
    with open(OUT / "DEFINITIONS_RIGHTS_FLAGS_2026-11-10.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["term_id", "model_definition_withheld_span", "model_full_form_withheld_span", "model_synonyms_withheld_span",
                    "source_definitions_from_non_open_paper"])
        for tid, d, ff, syn, sd in c3.execute("SELECT term_id, MODEL_definition, MODEL_full_form, MODEL_synonyms, "
                                              "SOURCE_extracted_definitions FROM term_enrichment"):
            f = [withheld_span(d or ""), withheld_span(ff or ""), withheld_span(syn or ""), bool(sd) and srcbad[tid] > 0]
            for k, v in zip(("model_definition", "model_full_form", "model_synonyms", "source_definitions"), f):
                flags[k] += v
            flags["any_model_field"] += any(f[:3])
            flags["terms"] += 1
            if any(f):
                w.writerow([tid] + [int(x) for x in f])
    res["definitions_layer_rights_check"] = {
        "table": "CDM 3.1.0 term_enrichment", "generated_by": "local Qwen3.5-4B (not sent outside)",
        "rule": f"model field flagged if it contains a {K2}-char normalised window found only in text-withheld papers; "
                "SOURCE_extracted_definitions flagged if any contributing quote is from a paper not INCLUDE_TEXT",
        "counts": dict(flags), "flags_file": "outputs/results/rights/DEFINITIONS_RIGHTS_FLAGS_2026-11-10.csv",
        "release_rule": "public release: blank every flagged field (model fields with a withheld span; source definitions from "
                        "non-open papers); the frozen 3.1.0 database is not changed"}
    (OUT / "B24_EXTERNAL_PROCESSING_ADDENDUM_2026-11-10.json").write_text(json.dumps(res, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(res["definitions_layer_rights_check"], indent=1))


if __name__ == "__main__":
    main()
