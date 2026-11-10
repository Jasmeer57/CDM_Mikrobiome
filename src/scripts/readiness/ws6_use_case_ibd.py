"""WS-6: IBD use case, read from the Figure F data (no new analysis: the same cells figF() draws, for one condition).

Question: which genera do papers in the corpus report as consistently increased or decreased in IBD, and does the
direction agree with BugSigDB signatures from papers outside the corpus?  Cells, thresholds and the BugSigDB
consensus rule (>= 3 signatures, >= 2/3 one direction) are exactly those of make_bib_extra_figures.figF; the script
first re-computes all cells and checks the figure's totals (44 compared, 25 same) before reporting.
Reported findings, not a meta-analysis. Writes outputs/results/benchmark/use_case_ibd_2026-11-05/.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
sys.path.insert(0, str(ROOT / "src/scripts/figures"))
import make_bib_extra_figures as X  # noqa: E402

OUT = ROOT / "outputs/results/benchmark/use_case_ibd_2026-11-05"
COND = "IBD"


def cells():
    c = X.db()
    parent, rank, tname, genus = X.BC.load_taxonomy()
    pcond = X.paper_conditions(c)
    dmap = {"INCREASE": 1, "increased": 1, "DECREASE": -1, "decreased": -1}
    ours = defaultdict(lambda: defaultdict(set))
    for pid, ids, d in c.execute("SELECT paper_id, taxon_ncbi_ids, direction FROM claim WHERE claim_source = 'catalogue_v3_1' "
                                 "AND taxon_ncbi_ids LIKE 'NCBITaxon:%'"):
        if d not in dmap:
            continue
        for t in {int(x) for x in re.findall(r"NCBITaxon:(\d+)", ids)}:
            g = genus(t)
            if g not in rank or rank[g] != "genus":
                continue
            for cond in pcond.get(pid, ()):
                ours[(g, cond)][dmap[d]].add(pid)
    pm = {str(x) for (x,) in c.execute("SELECT pmid FROM paper WHERE pmid != ''")}
    dois = {x.lower() for (x,) in c.execute("SELECT doi FROM paper WHERE doi != ''")}
    _, rows = X.BC.load_bugsigdb()
    bs = defaultdict(Counter)
    for r in rows:
        if (r.get("PMID") or "").split(".")[0] in pm or (r.get("DOI") or "").lower() in dois:
            continue
        d = {"increased": 1, "decreased": -1}.get(r["Abundance in Group 1"])
        if not d:
            continue
        for lin in (r["NCBI Taxonomy IDs"] or "").split(";"):
            leaf = lin.split("|")[-1].strip()
            if leaf.isdigit():
                g = genus(int(leaf))
                if g in rank and rank[g] == "genus":
                    for cond in X.conditions(r.get("Condition") or ""):
                        bs[(g, cond)][d] += 1
    cl = {k: v for k, v in ours.items() if len(v[1] | v[-1]) >= 2}
    return cl, bs, tname


def main():
    cl, bs, tname = cells()
    # reproduce the figure's grid and totals
    conds = [k for k, _ in Counter(k[1] for k in cl).most_common(10)]
    gens = [g for g, _ in Counter(k[0] for k in cl).most_common(60) if sum((g, cc) in cl for cc in conds) >= 2][:22]
    agree = Counter()
    for g in gens:
        for cc in conds:
            v = cl.get((g, cc))
            if not v:
                continue
            up, dn = len(v[1]), len(v[-1])
            b = bs.get((g, cc), Counter())
            nb = b[1] + b[-1]
            if nb >= 3 and max(b[1], b[-1]) / nb >= 2 / 3 and up != dn:
                agree["same" if (b[1] > b[-1]) == (up > dn) else "opposite"] += 1
    check = {"cells_compared": sum(agree.values()), "same": agree["same"], "figure_values": {"cells_compared": 44, "same": 25}}
    assert check["cells_compared"] == 44 and check["same"] == 25, check
    rows = []
    for (g, cc), v in cl.items():
        if cc != COND:
            continue
        up, dn = len(v[1]), len(v[-1])
        b = bs.get((g, cc), Counter())
        nb = b[1] + b[-1]
        cons = None
        if nb >= 3 and max(b[1], b[-1]) / nb >= 2 / 3:
            cons = "increased" if b[1] > b[-1] else "decreased"
        ours_dir = "increased" if up > dn else "decreased" if dn > up else "mixed"
        rows.append({"genus": tname.get(g, str(g)), "ncbi_taxon": g, "papers_increased": up, "papers_decreased": dn,
                     "corpus_direction": ours_dir, "consistency_pct": round(100 * max(up, dn) / (up + dn), 1),
                     "bugsigdb_outside_increased": b[1], "bugsigdb_outside_decreased": b[-1], "bugsigdb_consensus": cons,
                     "agrees": None if cons is None or ours_dir == "mixed" else cons == ours_dir, "in_figure": g in gens})
    rows.sort(key=lambda r: -(r["papers_increased"] + r["papers_decreased"]))
    OUT.mkdir(parents=True, exist_ok=True)
    comp = [r for r in rows if r["agrees"] is not None]
    res = {"condition": COND, "figure_check": check, "genera_with_2plus_papers": len(rows),
           "comparable_with_bugsigdb": len(comp), "agree": sum(r["agrees"] for r in comp), "rows": rows,
           "note": "Reported findings in the corpus vs BugSigDB signatures from papers outside it; not a meta-analysis."}
    (OUT / "summary.json").write_text(json.dumps(res, indent=1) + "\n")
    L = [f"# Use case: genera reported in IBD (WS-6), from the Figure F data", "",
         f"{len(rows)} genera reported in IBD by at least 2 corpus papers; {len(comp)} comparable with an independent "
         f"BugSigDB consensus; {res['agree']} agree in direction. Reported findings, not a meta-analysis.", "",
         "| genus | papers up / down | corpus direction (consistency %) | BugSigDB outside corpus up / down | consensus | agrees |",
         "|---|---|---|---|---|---|"]
    for r in rows:
        L.append(f"| *{r['genus']}* | {r['papers_increased']} / {r['papers_decreased']} | {r['corpus_direction']} ({r['consistency_pct']}) | "
                 f"{r['bugsigdb_outside_increased']} / {r['bugsigdb_outside_decreased']} | {r['bugsigdb_consensus'] or '—'} | "
                 f"{'' if r['agrees'] is None else ('yes' if r['agrees'] else 'no')} |")
    (OUT / "REPORT.md").write_text("\n".join(L) + "\n")
    print("\n".join(L[:40]))


if __name__ == "__main__":
    main()
