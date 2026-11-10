"""Usability check: the 8 research queries on CDM 3.0.3 vs paper sets found independently by text search.

The expected sets come from fixed keyword rules over the section text (no model, no catalogue field), so the
comparison is between two computational processes, not against human ground truth. Both sides are paper sets.

    python query_check.py
"""
from __future__ import annotations

import csv
import json
import re
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
CDM = ROOT / "releases/cdm_v3/3.0.3/microbiome_cdm_v3.db"
QUERIES = ROOT / "outputs/human_validation/gate4_2026-11-02/CDM_VALIDATION/RESEARCH_QUERY_VALIDATION.csv"
OUT = ROOT / "paper/publication/final_validation/queries"
csv.field_size_limit(sys.maxsize)
CORE = ("Abstract", "Methods", "Results")


def sentences(t):
    return re.split(r"(?<=[.!?])\s+", t)


def any_sent(texts, *pats):
    """True if one sentence matches every pattern."""
    rx = [re.compile(p, re.I) for p in pats]
    return any(all(r.search(s) for r in rx) for t in texts for s in sentences(t))


RULES = {  # query id -> (sections searched, predicate over {section_type: [texts]}, description)
    "Q1": ("Abstract/Methods/Results", lambda S: any_sent(S["core"], r"inflammatory bowel disease|\bIBD\b|crohn|ulcerative colitis")
           and any_sent(S["Methods"] + S["Abstract"], r"16S"), "IBD in a core-section sentence AND 16S in Methods/Abstract"),
    "Q2": ("Abstract/Methods", lambda S: any_sent(S["Abstract"] + S["Methods"], r"type 2 diabetes|\bT2D\b|type II diabetes"),
           "type 2 diabetes in Abstract/Methods"),
    "Q3": ("Abstract/Results", lambda S: any_sent(S["Abstract"] + S["Results"], r"prausnitzii|faecalibacterium",
                                                  r"decreas|lower|reduc|deplet|less abundant"),
           "Faecalibacterium + decrease word in one Abstract/Results sentence"),
    "Q4": ("all but References", lambda S: bool(re.search(r"\b(PRJ(NA|EB|DB|DA)\d{3,}|[SED]RP\d{5,}|EGA[SD]\d{8,})\b", " ".join(S["all"]))),
           "public project/study accession anywhere except References"),
    "Q6": ("Abstract/Methods", lambda S: any_sent(S["Abstract"] + S["Methods"], r"probiotic"), "probiotic in Abstract/Methods"),
    "Q7": ("Methods", lambda S: any_sent(S["Methods"], r"stool|f(a)?ecal|f(a)?eces", r"[-−–]\s?80\s?°?\s?C|minus 80"),
           "stool/fecal + -80 °C in one Methods sentence"),
    "Q8": ("Methods/Abstract", lambda S: any_sent(S["Methods"] + S["Abstract"], r"shotgun|whole[- ]genome metagenom|metagenomic sequencing"),
           "shotgun/metagenomic sequencing in Methods/Abstract"),
}


def main():
    c = sqlite3.connect(f"file:{CDM}?mode=ro", uri=True)
    S = defaultdict(lambda: defaultdict(list))
    for pid, st, t in c.execute("SELECT paper_id, section_type, section_text_original FROM section"):
        if st == "References":
            continue
        S[pid][st].append(t or "")
        S[pid]["all"].append(t or "")
        if st in CORE:
            S[pid]["core"].append(t or "")
    qs = list(csv.DictReader(open(QUERIES, encoding="utf-8")))
    rows = []
    for q in qs:
        res = c.execute(q["sql"]).fetchall()
        got = {next(x for x in r if str(x).startswith("HMPAPER")) for r in res if any(str(x).startswith("HMPAPER") for x in r)}
        if q["query_id"] not in RULES:
            # Q5: provenance completeness of every catalogue finding
            full = sum(1 for r in res if r[2] and r[4] is not None and r[6] in ("EXACT", "WHITESPACE", "RELOCATED", "NORMALISED"))
            rows.append({"query_id": q["query_id"], "question": q["research_question"], "cdm_rows": len(res), "cdm_papers": len(got),
                         "text_rule": "provenance: DOI + section + located verbatim quote", "text_papers": "", "both": "",
                         "cdm_only": "", "text_only": "", "jaccard": "", "text_set_covered_pct": "",
                         "provenance_complete_pct": round(100 * full / len(res), 1)})
            continue
        sec, pred, desc = RULES[q["query_id"]]
        exp = {p for p in S if pred(S[p])}
        both = got & exp
        rows.append({"query_id": q["query_id"], "question": q["research_question"], "cdm_rows": len(res), "cdm_papers": len(got),
                     "text_rule": desc, "text_papers": len(exp), "both": len(both), "cdm_only": len(got - exp),
                     "text_only": len(exp - got), "jaccard": round(len(both) / len(got | exp), 3) if got | exp else "",
                     "text_set_covered_pct": round(100 * len(both) / len(exp), 1) if exp else "",
                     "provenance_complete_pct": "", "cdm_only_ids": ";".join(sorted(got - exp)[:30]),
                     "text_only_ids": ";".join(sorted(exp - got)[:30])})
    OUT.mkdir(parents=True, exist_ok=True)
    keys = list(dict.fromkeys(k for r in rows for k in r))
    with open(OUT / "QUERY_COMPARISON.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)
    for r in rows:
        print({k: r.get(k) for k in ("query_id", "cdm_papers", "text_papers", "both", "cdm_only", "text_only", "jaccard",
                                     "text_set_covered_pct", "provenance_complete_pct")})


if __name__ == "__main__":
    main()
