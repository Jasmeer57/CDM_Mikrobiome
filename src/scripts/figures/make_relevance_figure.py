"""Figure on the relevance of the CDM triples to human microbiome research (DeepSeek relevance verdict, existing files only).

Panels: a) relevance by relation family; b) what the irrelevant triples are (subject type);
c) sentence support for relevant vs irrelevant triples; d) relevance of kept vs dropped triples.

    python make_relevance_figure.py
"""
from __future__ import annotations

import csv
import gzip
import sqlite3
from collections import Counter, defaultdict

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

import make_bib_figures as M  # noqa: E402

ROOT = M.ROOT
S1, S2, S3 = M.SERIES
NEUTRAL, DARK = "#c9c8c3", "#8a8985"
VER = ROOT / "outputs/results/benchmark/llm_judge_deepseek_v4_flash/triple_verdicts.csv.gz"
CLEAN = ROOT / "outputs/results/cleaned_layer_deepseek/cleaned_triples.csv.gz"
EVID = ROOT / "outputs/results/kg_2026-11-04/evidence_check/evidence_verdicts.csv.gz"
CDM = ROOT / "releases/cdm_v3/3.0.3/microbiome_cdm_v3.db"


def title(ax, s):
    ax.set_title(s, loc="left", fontsize=7, fontweight="bold", color=M.INK)


def main():
    rel = {}
    with gzip.open(VER, "rt", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            rel[r["triple_id"]] = r["microbiome_relevant"] == "Y"
    cl = {}
    with gzip.open(CLEAN, "rt", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            cl[r["canonical_triple_id"]] = r
    ev = {}
    with gzip.open(EVID, "rt", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            ev[r["canonical_triple_id"]] = r
    c = sqlite3.connect(f"file:{CDM}?mode=ro", uri=True)
    fam, subj = {}, {}
    for tid, f, st in c.execute("SELECT canonical_triple_id, relation_family, subject_entity_type FROM relation"):
        fam[tid], subj[tid] = f, st

    fig = plt.figure(figsize=(7.0, 6.0))
    gs = fig.add_gridspec(2, 2, hspace=0.55, wspace=0.8)

    # a: relevance by relation family
    ax = fig.add_subplot(gs[0, 0])
    tot, yes = Counter(), Counter()
    for t, ok in rel.items():
        f = fam.get(t, "?")
        tot[f] += 1
        yes[f] += ok
    fams = [f for f, _ in tot.most_common(9)]
    pct = [100 * yes[f] / tot[f] for f in fams]
    y = np.arange(len(fams))[::-1]
    ax.barh(y, pct, height=0.62, color=[S2 if f == "escape" else S1 for f in fams], edgecolor="white")
    for yy, p, f in zip(y, pct, fams):
        ax.text(p + 1.5, yy, f"{p:.0f}% (n={tot[f]:,})", va="center", fontsize=5.4, color=M.INK)
    ax.set_yticks(y, [("catch-all (OTHER_RELATION)" if f == "escape" else f.replace("_", " ")) for f in fams], fontsize=5.6)
    M.style(ax, "Triples judged relevant to human microbiome research (%)", 125)
    title(ax, "a  Relevance by relation family")

    # b: what the irrelevant triples are (subject type)
    ax = fig.add_subplot(gs[0, 1])
    irr = Counter(subj.get(t, "?") for t, ok in rel.items() if not ok)
    top = irr.most_common(7)
    y = np.arange(len(top))[::-1]
    ax.barh(y, [n for _, n in top], height=0.62, color=DARK, edgecolor="white")
    for yy, (_, n) in zip(y, top):
        ax.text(n + 40, yy, f"{n:,}", va="center", fontsize=5.6, color=M.INK)
    ax.set_yticks(y, [k.replace("_", " ") for k, _ in top], fontsize=5.6)
    M.style(ax, f"Irrelevant triples by subject type (n = {sum(irr.values()):,})", max(n for _, n in top) * 1.2)
    title(ax, "b  What the irrelevant triples are")

    # c: sentence support by relevance (triples with a CC BY sentence)
    ax = fig.add_subplot(gs[1, 0])
    groups = {"Relevant": [e for t, e in ev.items() if rel.get(t)], "Irrelevant": [e for t, e in ev.items() if rel.get(t) is False]}
    codes = [("Y", "Supported as written", S1), ("P", "Related, generic label", NEUTRAL), ("R", "Reversed", S2), ("N", "Not supported", DARK)]
    names = list(groups)
    y = np.arange(len(names))[::-1]
    left = np.zeros(len(names))
    for code, lab, col in codes:
        v = np.array([100 * Counter(e["A"] for e in groups[g])[code] / max(1, len(groups[g])) for g in names])
        ax.barh(y, v, left=left, height=0.55, color=col, edgecolor="white", linewidth=0.6, label=lab)
        for yy, vv, ll in zip(y, v, left):
            if code == "Y" and vv > 8:
                ax.text(ll + 1.5, yy, f"{vv:.0f}%", va="center", fontsize=5.8, color="white", fontweight="bold")
        left += v
    ax.set_yticks(y, [f"{n} (n={len(groups[n]):,})" for n in names], fontsize=5.8)
    M.style(ax, "Original label judged against the source sentence (%)", 100)
    ax.legend(fontsize=5.2, frameon=False, ncol=2, loc="lower center", bbox_to_anchor=(0.4, 1.0))
    ax.text(0, 1.22, "c  Sentence support, by relevance", transform=ax.transAxes, fontsize=7, fontweight="bold", color=M.INK)

    # d: relevance of kept vs dropped triples
    ax = fig.add_subplot(gs[1, 1])
    kept = [t for t, r in cl.items() if r["kept"] == "1"]
    dropped = [t for t, r in cl.items() if r["kept"] != "1"]
    cats = [("Kept by cleaning", kept, S1), ("Dropped by cleaning", dropped, S2)]
    for i, (lab, ts, col) in enumerate(cats):
        n = len([t for t in ts if t in rel])
        p = 100 * sum(rel[t] for t in ts if t in rel) / max(1, n)
        ax.barh(i, p, height=0.55, color=col, edgecolor="white")
        ax.text(p + 1.5, i, f"{p:.0f}% (n={n:,})", va="center", fontsize=5.8, color=M.INK)
    ax.set_yticks([0, 1], [c_[0] for c_ in cats][::-1][::-1], fontsize=5.8)
    ax.set_ylim(-0.6, 1.6)
    M.style(ax, "Triples judged relevant (%)", 125)
    title(ax, "d  Relevance of kept and dropped triples")

    M.save(fig, "fig_relevance")


if __name__ == "__main__":
    main()
