"""MINERVA (Langarica et al., Brief Bioinform 2025, doi 10.1093/bib/bbaf472; github.com/MGH-LMIC/MINERVA @4a6210e):
two comparisons.

1. Gold sentences: MINERVA's LLM_evaluation/initial_db/gold_data_corrected.csv -- 1,100 manually labelled
   microbe-disease sentences (Karkera et al., corrected by the MINERVA authors; labels positive = microbe promotes the
   disease, negative = microbe inhibits it, relate / na = unclear or unrelated, merged to "unrelated" as MINERVA does).
   Our retype-v3.1 answers (task rel of competitor_llm_runner.py) mapped to positive / negative / unrelated (POSITIVE and
   CONTRASTING sets of midred_compare.py; NULL_FINDING, unsigned and non-verified answers -> unrelated). Human labels, but
   annotation protocol / agreement are not reported in the MINERVA paper: we call it "manually labelled reference".
2. KG concordance (not accuracy): MINERVA Data/strengths_neg_pos.csv (66,444 microbe-disease pairs with counts of
   positive / negative paper-level relations; no PMIDs, so no paper-level matching is possible) vs our catalogue
   findings (claim_source catalogue_v3_1, direction INCREASE/DECREASE) at genus x condition level. MINERVA microbes are
   mapped to NCBI taxa by exact name (names.dmp scientific names + synonyms) and lifted to genus; conditions use the 26
   regex classes of the BugSigDB/figF comparison (make_bib_extra_figures.CONDITIONS) on MINERVA disease names and on
   our finding comparison text. A cell is comparable when our papers give a net direction and MINERVA has >= 3
   relations with >= 2/3 in one sign. Our INCREASE in a condition is compared with MINERVA "positive".

Inputs : outputs/scratch/competitors/minerva/raw/*; CDM 3.1.0 (read-only); data/reference_kg/raw/{nodes,names}.dmp;
         llm_runs/rel/*.jsonl
Outputs: outputs/results/competitor_compare_2026-11-11/minerva/{SUMMARY.json, REPORT.md, kg_cells.csv}
Written with Claude Code (declare).
"""
from __future__ import annotations

import ast
import csv
import json
import os
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from _cstats import RESULTS, ROOT, SCRATCH, confusion, dump, macro_f1_boot, wilson  # noqa: E402
from midred_compare import CONTRASTING, POSITIVE, load  # noqa: E402

sys.path.insert(0, str(ROOT / "src/scripts/bugsigdb_comparison"))
import compare as BC  # noqa: E402

RAW = SCRATCH / "minerva/raw"
OUT = Path(os.environ.get("CMP_OUT", RESULTS / "minerva"))
DB310 = ROOT / "releases/cdm_v3/3.1.0/microbiome_cdm_v3.1.0.db"
HEALTHY_FIRST = re.compile(r"^\s*(healthy|control|controls|hc\b|non-?\w+|normal|lean)\b", re.I)


def conditions_rules():
    """CONDITIONS list literal from make_bib_extra_figures.py (single source, parsed without importing matplotlib)."""
    src = (ROOT / "src/scripts/figures/make_bib_extra_figures.py").read_text()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "CONDITIONS" for t in node.targets):
            return ast.literal_eval(node.value)
    raise RuntimeError("CONDITIONS not found")


RULES = conditions_rules()


def conditions(text):
    t = (text or "").lower()
    hits = {name for name, rx in RULES if re.search(rx, t)}
    if "Colorectal cancer" in hits:
        hits.discard("Cancer (other)")
    return hits


def pol(r):
    if not r.get("specific_verified"):
        return "unrelated"
    if r["relation"] in POSITIVE:
        return "positive"
    if r["relation"] in CONTRASTING:
        return "negative"
    return "unrelated"


def gold_part():
    rows = load("minerva")
    gmap = {"positive": "positive", "negative": "negative", "relate": "unrelated", "na": "unrelated"}
    pairs = [(gmap[r["gold"][0]["label"]], pol(r)) for r in rows]
    four = [(r["gold"][0]["label"], pol(r)) for r in rows]
    signed = [(g, p) for g, p in pairs if g != "unrelated" and p != "unrelated"]
    return {"source": "github.com/MGH-LMIC/MINERVA LLM_evaluation/initial_db/gold_data_corrected.csv (commit 4a6210ee)",
            "reference_type": "manually labelled sentences (Karkera et al.; corrected by MINERVA authors); annotation protocol/IAA not reported",
            "n": len(rows), "unparsed": sum(1 for r in rows if r["relation"] == "UNPARSED"),
            "three_class": macro_f1_boot(pairs, ["positive", "negative", "unrelated"]),
            "sign_agreement_when_both_signed": wilson(sum(1 for g, p in signed if g == p), len(signed)),
            "abstained_on_signed_gold": wilson(sum(1 for g, p in pairs if g != "unrelated" and p == "unrelated"),
                                               sum(1 for g, p in pairs if g != "unrelated")),
            "confusion_gold4_vs_pred3": confusion(four),
            "published_reference": "MINERVA fine-tuned LLM reported F1 about 0.71 on its evaluation (authors' response, PMC12704414); not the same protocol"}


def kg_part():
    parent, rank, sci, genus = BC.load_taxonomy()
    name2tax = defaultdict(set)
    for t, n in sci.items():
        name2tax[n.lower()].add(t)
    with open(ROOT / "data/reference_kg/raw/names.dmp", encoding="utf-8") as fh:
        for line in fh:
            f = line.split("\t|\t")
            if len(f) > 3 and ("synonym" in f[3] or "equivalent name" in f[3]):
                name2tax[f[1].lower()].add(int(f[0]))
    mic = {}
    for r in csv.DictReader(open(RAW / "microbes.csv", encoding="utf-8")):
        ts = name2tax.get((r["official_name"] or "").lower()) or name2tax.get((r["name"] or "").lower()) or set()
        gs = {genus(t) for t in ts if genus(t) in rank and rank[genus(t)] == "genus"}
        if len(gs) == 1:
            mic[r["id"]] = gs.pop()
    dis = {}
    for r in csv.DictReader(open(RAW / "diseases.csv", encoding="utf-8")):
        cs = conditions(f"{r['official_name']} ; {r['name']}")
        if cs:
            dis[r["id"]] = cs
    mv = defaultdict(lambda: [0, 0])     # (genus, cond) -> [pos, neg]
    n_rows = n_used = 0
    for r in csv.DictReader(open(RAW / "strengths_neg_pos.csv", encoding="utf-8")):
        n_rows += 1
        g, cs = mic.get(r["id_microbe"]), dis.get(r["id_disease"])
        if g is None or not cs:
            continue
        n_used += 1
        for cc in cs:
            mv[(g, cc)][0] += int(float(r["pos_relations"]))
            mv[(g, cc)][1] += int(float(r["neg_relations"]))
    c = sqlite3.connect(f"file:{DB310}?mode=ro", uri=True)
    pcond = {pid: conditions(f"{t} {hc}") for pid, t, hc in
             c.execute("SELECT p.paper_id, p.title, s.health_conditions FROM paper p LEFT JOIN study s USING (paper_id)")}
    base = {"source": "github.com/MGH-LMIC/MINERVA Data/strengths_neg_pos.csv + microbes.csv + diseases.csv (commit 4a6210ee)",
            "reference_type": "automatically extracted KG (fine-tuned LLM); concordance only",
            "minerva_pairs_total": n_rows, "minerva_pairs_mapped_to_genus_and_condition": n_used,
            "minerva_microbes_mapped_to_unique_genus": len(mic), "minerva_cells": len(mv),
            "rule": "comparable = CDM net direction (up papers != down papers) and MINERVA >= 3 relations with >= 2/3 one sign"}
    for level in ("finding_level", "paper_level"):
        base[level] = cells(c, level, pcond, mv, rank, sci, genus)
    return base


def cells(c, level, pcond, mv, rank, sci, genus):
    """finding_level: condition from the finding's comparison text (orientation checked); paper_level: condition from
    paper title + study health conditions (as figF of make_bib_extra_figures.py)."""
    ours = defaultdict(lambda: {1: set(), -1: set()})
    excl = Counter()
    for pid, ids, d, comp in c.execute("SELECT paper_id, taxon_ncbi_ids, direction, comparison_or_exposure FROM claim "
                                       "WHERE claim_source='catalogue_v3_1' AND taxon_ncbi_ids LIKE 'NCBITaxon:%'"):
        s = {"INCREASE": 1, "DECREASE": -1}.get(d)
        if not s:
            excl["direction_not_up_down"] += 1
            continue
        if level == "finding_level":
            cs = conditions(comp)
            if not cs:
                excl["no_condition_in_comparison"] += 1
                continue
            if HEALTHY_FIRST.search(comp or ""):
                excl["comparison_starts_with_control_group"] += 1
                continue
        else:
            cs = pcond.get(pid, set())
            if not cs:
                excl["no_condition_for_paper"] += 1
                continue
        for t in BC.taxa_ids(ids):
            g = genus(t)
            if g in rank and rank[g] == "genus":
                for cc in cs:
                    ours[(g, cc)][s].add(pid)
    rows, agree, comp_n, ours_up, mv_pos = [], 0, 0, 0, 0
    for k, v in ours.items():
        up, dn = len(v[1]), len(v[-1])
        m = mv.get(k)
        rec = {"level": level, "genus": sci.get(k[0], k[0]), "condition": k[1], "cdm_up_papers": up, "cdm_down_papers": dn,
               "ref_pos": m[0] if m else 0, "ref_neg": m[1] if m else 0, "comparable": False, "agree": ""}
        if m and up != dn and sum(m) >= 3 and max(m) / sum(m) >= 2 / 3:
            same = (up > dn) == (m[0] > m[1])
            rec.update(comparable=True, agree=same)
            comp_n += 1
            agree += same
            ours_up += up > dn
            mv_pos += m[0] > m[1]
        rows.append(rec)
    q, p = (ours_up / comp_n if comp_n else 0), (mv_pos / comp_n if comp_n else 0)
    mode = "w" if level == "finding_level" else "a"
    with open(OUT / "kg_cells.csv", mode, newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        if mode == "w":
            w.writeheader()
        w.writerows(sorted(rows, key=lambda r: (-r["cdm_up_papers"] - r["cdm_down_papers"], str(r["genus"]))))
    in_mv = sum(1 for k in ours if k in mv and sum(mv[k]) > 0)
    return {"cdm_genus_condition_cells": len(ours), "cdm_cells_present_in_reference": wilson(in_mv, len(ours)),
            "cdm_findings_excluded": dict(excl), "comparable_cells": comp_n, "direction_agreement": wilson(agree, comp_n),
            "chance_agreement_from_marginals": round(q * p + (1 - q) * (1 - p), 4),
            "marginals_comparable_cells": {"cdm_share_up": round(q, 4), "reference_share_positive": round(p, 4)}}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    summ = {"kg_concordance": kg_part()}
    try:
        summ["gold_sentences"] = gold_part()
    except Exception as e:  # noqa: BLE001  (LLM run not finished yet)
        summ["gold_sentences"] = {"error": repr(e)}
    dump(summ, OUT / "SUMMARY.json")
    print(json.dumps(summ, indent=1)[:3000])


if __name__ == "__main__":
    main()
