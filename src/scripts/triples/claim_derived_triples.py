"""Derive directional triples from catalogue findings (deterministic; no model; frozen CDM 3.0.3 read-only).

    python src/scripts/triples/claim_derived_triples.py

Source: CDM 3.0.3 claim rows from the evidence-quoted catalogue (claim_source = catalogue_v3_1) whose quote is anchored
in the paper (evidence_verified = 1, anchor status not UNANCHORED / NO_EVIDENCE) and that name a taxon or feature, a
comparison or exposure and a direction (INCREASE / DECREASE / NO_ASSOCIATION).
Triple: subject = taxon_or_feature, object = comparison_or_exposure, relation INCREASED_IN / DECREASED_IN / NULL_FINDING.
Kept only if the evidence quote itself supports it:
  - the subject occurs in the quote (whole string, or its first content word of >= 4 letters);
  - at least one content word of the object occurs in the quote;
  - the quote has wording for the claimed direction (increase / decrease words; for NULL_FINDING negation wording) and,
    for INCREASED_IN / DECREASED_IN, no wording for the opposite direction unless the claimed one is also present
    (both present -> kept, flagged direction_cue_mixed).
Rows that duplicate an existing CDM triple (same paper, same normalised subject and object, either order) are marked
duplicate_of_existing and not counted as new. Output: outputs/results/claim_triples_2026-11-10/{claim_triples.jsonl,
SUMMARY.json}. New derived layer; frozen releases unchanged; PENDING lead approval. Written with Claude Code (declare).
"""
from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
DB303 = ROOT / "releases/cdm_v3/3.0.3/microbiome_cdm_v3.db"
OUT = ROOT / "outputs/results/claim_triples_2026-11-10"
REL = {"INCREASE": "INCREASED_IN", "DECREASE": "DECREASED_IN", "NO_ASSOCIATION": "NULL_FINDING"}
INC = re.compile(r"(increas|higher|elevat|enrich|more abundant|greater|raised|up-?regulat|over-?represent|expan|bloom|\brise|\brose|↑)")
DEC = re.compile(r"(decreas|lower|reduc|deplet|less abundant|diminish|down-?regulat|under-?represent|declin|\bdrop|fewer|\bloss|↓)")
NEG = re.compile(r"\b(no|not|none|neither|nor|without|unchanged|similar|comparable|n\.s\.|non-?significant|insignificant|unaltered|unaffected)\b")
STOP = {"with", "from", "between", "versus", "group", "groups", "patients", "subjects", "samples", "compared", "than",
        "that", "this", "those", "these", "after", "before", "during", "control", "controls"}


def norm(s):
    return re.sub(r"[^a-z0-9]+", " ", str(s or "").lower()).strip()


def words(s):
    return [w for w in norm(s).split() if len(w) >= 4 and w not in STOP]


def main():
    c = sqlite3.connect(f"file:{DB303}?mode=ro", uri=True)
    rows = c.execute("""SELECT finding_id, paper_id, taxon_or_feature, comparison_or_exposure, upper(direction), evidence_text,
                               body_site, evidence_anchor_status, char_start, char_end, section_id
                        FROM claim WHERE claim_source='catalogue_v3_1' AND evidence_verified IN (1,'1')
                          AND evidence_anchor_status NOT IN ('UNANCHORED','NO_EVIDENCE')
                          AND taxon_or_feature<>'' AND comparison_or_exposure<>''
                          AND upper(direction) IN ('INCREASE','DECREASE','NO_ASSOCIATION')""").fetchall()
    existing = set()
    for paper, s, o in c.execute("""SELECT e.paper_id, t.subject_display_label, t.object_display_label FROM relation_evidence e
                                    JOIN relation t USING(canonical_triple_id)"""):
        existing.add((paper, norm(s), norm(o)))
        existing.add((paper, norm(o), norm(s)))
    why, out = Counter(), []
    for fid, paper, subj, obj, d, ev, site, anchor, cs, ce, sec in rows:
        e = norm(ev)
        el = (ev or "").lower()
        sw = words(subj)
        if not (norm(subj) in e or (sw and sw[0] in e.split())):
            why["subject_not_in_quote"] += 1
            continue
        ow = words(obj)
        if ow and not any(w in e.split() for w in ow):
            why["object_not_in_quote"] += 1
            continue
        rel = REL[d]
        inc, dec, neg = bool(INC.search(el)), bool(DEC.search(el)), bool(NEG.search(el))
        if rel == "NULL_FINDING":
            if not neg:
                why["null_without_negation"] += 1
                continue
            mixed = False
        else:
            want, other = (inc, dec) if rel == "INCREASED_IN" else (dec, inc)
            if not want:
                why["no_direction_wording"] += 1
                continue
            mixed = other
        dup = (paper, norm(subj), norm(obj)) in existing
        why["duplicate_of_existing" if dup else "kept_new"] += 1
        out.append({"finding_id": fid, "paper_id": paper, "subject": subj, "relation": rel, "object": obj,
                    "body_site": site, "evidence_text": ev, "evidence_anchor_status": anchor, "char_start": cs,
                    "char_end": ce, "section_id": sec, "direction_cue_mixed": mixed, "duplicate_of_existing": dup,
                    "provenance": "DERIVED_FROM_CATALOGUE_FINDING", "derivation": "claim_derived_triples.py 2026-11-10"})
    new = [r for r in out if not r["duplicate_of_existing"]]
    summ = {"source_claims": len(rows), "kept": len(out), "new_not_in_cdm": len(new), "rejected": {k: v for k, v in why.items()
            if k not in ("kept_new", "duplicate_of_existing")}, "duplicate_of_existing": why["duplicate_of_existing"],
            "new_by_relation": dict(Counter(r["relation"] for r in new)),
            "new_direction_cue_mixed": sum(r["direction_cue_mixed"] for r in new),
            "new_papers": len({r["paper_id"] for r in new}),
            "status": "derived from frozen CDM 3.0.3 catalogue findings; no model; frozen releases unchanged; PENDING lead approval"}
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "claim_triples.jsonl", "w", encoding="utf-8") as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    (OUT / "SUMMARY.json").write_text(json.dumps(summ, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(summ, indent=1))


if __name__ == "__main__":
    main()
