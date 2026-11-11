"""GutBiomeDB platform agreement per BioProject, old vs 3.2.0-candidate sequencing_platform (protocol fixed before run).

Reuses gutbiomedb_compare.py (GutBiomeDB project_detail.jsonl already fetched; cdm_studies(); norm_platform()).
Sides compared against GutBiomeDB `instrument` (SRA-derived) for shared BioProjects:
  OLD_STUDY_LLM  study.sequencing_platform LLM-from-text value (the 86.7% row of the 2026-11-11 comparison);
  OLD_ASSAY      union of the 3.0.3 assay-record sequencing_platform values of the paper;
  NEW            union of the paper's 3.2.0-candidate keys (all confidences), and NEW_HIGH (high-confidence keys only).
Metrics (Wilson 95% CI), per paper with a value on both sides:
  script_logic   gutbiomedb_compare.norm_platform set overlap (the existing logic; instrument-line level: miseq/hiseq/...);
  family         vendor family overlap (Illumina, Roche 454, ...);
  model          exact model match, only where GutBiomeDB names a model (e.g. HiSeq 2500) and our side has a model-level value.
Agreement with GutBiomeDB, not accuracy.
    python src/scripts/fixes_v32/gbdb_compare_v32.py
Written with Claude Code (declare).
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
sys.path.insert(0, str(ROOT / "src/scripts/competitors"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import gutbiomedb_compare as GC  # noqa: E402
import gazetteer as G  # noqa: E402
from judge_fields import wilson  # noqa: E402

OUT = G.OUT
CDM303 = ROOT / "releases/cdm_v3/3.0.3/microbiome_cdm_v3.db"
MISSING = ("", "NOT_REPORTED", "CONFLICTING", None)


def gaz(s):
    """(families, models) named in a free-text platform string."""
    hs = G.match("sequencing_platform", s or "")
    if not hs and s and "illumina" in s.lower():
        hs = [{"family": "Illumina", "model": "", "level": "family"}]
    return {h["family"] for h in hs}, {h["model"] for h in hs if h["level"] == "model"}


def gbdb_side(instr):
    if not instr or instr == "unspecified":
        return None
    fams, models = gaz(instr if "454" not in instr else "Roche 454 " + instr.replace("454 GS", "pyrosequencing"))
    return {"norm": GC.norm_platform(instr), "fam": fams, "models": models}


def score(pairs):
    out = {}
    for metric in ("script_logic", "family", "model"):
        k = n = 0
        for g, o in pairs:
            if metric == "script_logic":
                if not g["norm"] or not o["norm"]:
                    continue
                n += 1
                k += bool(g["norm"] & o["norm"])
            elif metric == "family":
                if not g["fam"] or not o["fam"]:
                    continue
                n += 1
                k += bool(g["fam"] & o["fam"])
            else:
                gm = {m for m in g["models"] if any(ch.isdigit() for ch in m) or m in ("MiSeq", "MiniSeq")}
                if not gm or not o["models"]:
                    continue
                n += 1
                k += bool(gm & o["models"])
        out[metric] = wilson(k, n)
    return out


def ours(strings):
    fams, models = set(), set()
    norm = set()
    for s in strings:
        f, m = gaz(s)
        fams |= f
        models |= m
        norm |= GC.norm_platform(s) or set()
    return {"fam": fams, "models": models, "norm": frozenset(norm) or None} if (fams or norm) else None


def main():
    gb = {p["project_id"]: p for p in (json.loads(l) for l in open(GC.D / "project_detail.jsonl", encoding="utf-8"))}
    studies = GC.cdm_studies()
    c = sqlite3.connect(f"file:{CDM303}?mode=ro", uri=True)
    old_assay = defaultdict(list)
    for pid, v in c.execute("SELECT paper_id, sequencing_platform FROM assay"):
        if v not in MISSING:
            old_assay[pid].append(v)
    new, new_hi = defaultdict(list), defaultdict(list)
    for o in map(json.loads, open(OUT / "paper_values_v32.jsonl", encoding="utf-8")):
        if o["field"] != "sequencing_platform":
            continue
        for v in o["values"]:
            new[o["paper_id"]].append(v["value"])
            if v["field_confidence"] == "high":
                new_hi[o["paper_id"]].append(v["value"])
    sides = {"OLD_STUDY_LLM": lambda r: [r["platform_llm"]] if r["platform_llm"] else [],
             "OLD_ASSAY": lambda r: old_assay.get(r["paper_id"], []),
             "NEW": lambda r: new.get(r["paper_id"], []), "NEW_HIGH": lambda r: new_hi.get(r["paper_id"], [])}
    res = {"shared_bioprojects": len(set(studies) & set(gb)), "gbdb_with_instrument": 0, "sides": {}}
    rows = []
    shared = sorted(set(studies) & set(gb))
    res["gbdb_with_instrument"] = sum(1 for bp in shared if gbdb_side(gb[bp].get("instrument")))
    for name, fn in sides.items():
        pairs = []
        for bp in shared:
            g = gbdb_side(gb[bp].get("instrument"))
            if not g:
                continue
            for r in studies[bp]:
                o = ours(fn(r))
                if o:
                    pairs.append((g, o))
                    rows.append({"side": name, "bioproject": bp, "paper_id": r["paper_id"], "gbdb": gb[bp].get("instrument"),
                                 "ours": "; ".join(fn(r))[:300], "family_agree": bool(g["fam"] & o["fam"]),
                                 "script_logic_agree": bool(g["norm"] and o["norm"] and g["norm"] & o["norm"])})
        res["sides"][name] = {"n_papers_with_value": len(pairs), **score(pairs)}
    # paired: same papers on OLD_STUDY_LLM and NEW
    (OUT / "gbdb_compare_v32.json").write_text(json.dumps(res, indent=1) + "\n", encoding="utf-8")
    import csv
    with open(OUT / "gbdb_compare_v32_per_paper.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
