"""Triples figure for the BiB submission: what happened to the 25,788 CDM triples, how the cleaning changed their labels,
whether their source sentence supports them, and whether curated knowledge graphs know the pairs.
Reads only result files (cleaned layer, evidence check, reference-KG check); nothing is typed in.

    python make_triples_figure.py
"""
from __future__ import annotations

import csv
import gzip
import json
from collections import Counter

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

import make_bib_figures as M  # noqa: E402

ROOT = M.ROOT
KG = ROOT / "outputs/results/kg_2026-11-04"
EV = json.load(open(KG / "evidence_check/summary.json"))
GK = json.load(open(KG / "gold_kg_check/summary.json"))
S1, S2, S3 = M.SERIES
NEUTRAL, DARK = "#c9c8c3", "#8a8985"


def title(ax, s):
    ax.set_title(s, loc="left", fontsize=7, fontweight="bold", color=M.INK)


def main():
    with gzip.open(ROOT / "outputs/results/cleaned_layer_deepseek/cleaned_triples.csv.gz", "rt", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    with gzip.open(KG / "evidence_check/evidence_verdicts.csv.gz", "rt", encoding="utf-8") as fh:
        ev = list(csv.DictReader(fh))
    fig = plt.figure(figsize=(7.0, 6.2))
    gs = fig.add_gridspec(2, 2, hspace=0.6, wspace=0.75)

    # a: fate of all triples
    ax = fig.add_subplot(gs[0, 0])
    fate = Counter("kept" if r["kept"] == "1" else r["drop_reason"] for r in rows)
    order = [("kept", "Kept by cleaning", S1), ("invalid_entities", "Dropped: invalid entity", S2), ("not_well_formed", "Dropped: not a well-formed claim", NEUTRAL)]
    y = np.arange(len(order))[::-1]
    vals = [fate[k] for k, _, _ in order]
    ax.barh(y, vals, color=[c for _, _, c in order], height=0.6, edgecolor="white")
    for yy, v in zip(y, vals):
        ax.text(v + 300, yy, f"{v:,} ({100 * v / len(rows):.0f}%)", va="center", fontsize=5.8, color=M.INK)
    ax.set_yticks(y, [lab for _, lab, _ in order], fontsize=6)
    M.style(ax, f"Triples (n = {len(rows):,})", max(vals) * 1.45)
    title(ax, "a  Fate of every triple")

    # b: labels before / after cleaning (kept triples)
    ax = fig.add_subplot(gs[0, 1])
    kept = [r for r in rows if r["kept"] == "1"]
    before, after = Counter(r["relation_original"] for r in kept), Counter(r["relation_cleaned"] for r in kept)
    labs = [k for k, _ in (before + after).most_common(9)]
    y = np.arange(len(labs))[::-1]
    h = 0.38
    ax.barh(y + h / 2, [before[k] for k in labs], height=h, color=NEUTRAL, edgecolor="white", label="Before cleaning")
    ax.barh(y - h / 2, [after[k] for k in labs], height=h, color=S1, edgecolor="white", label="After cleaning")
    ax.set_yticks(y, labs, fontsize=5.6)
    M.style(ax, f"Kept triples (n = {len(kept):,})", max(max(before.values()), max(after.values())) * 1.12)
    ax.legend(fontsize=5.6, frameon=False, loc="lower right")
    title(ax, "b  Relation labels")

    # c: sentence support
    ax = fig.add_subplot(gs[1, 0])
    codes = [("Y", "Supported as written", S1), ("P", "Related, label generic", NEUTRAL), ("R", "Reversed", S2), ("N", "Not supported", DARK)]
    groups = [("Kept, original label", [r["A"] for r in ev if r["kept_by_cleaning"] == "1"]),
              ("Dropped, original label", [r["A"] for r in ev if r["kept_by_cleaning"] != "1"]),
              ("Relabelled, original", [r["A"] for r in ev if r["relation_cleaned"]]),
              ("Relabelled, cleaned", [r["B"] for r in ev if r["relation_cleaned"]])]
    y = np.arange(len(groups))[::-1]
    left = np.zeros(len(groups))
    for code, lab, col in codes:
        v = np.array([100 * Counter(g)[code] / max(1, len(g)) for _, g in groups])
        ax.barh(y, v, left=left, height=0.6, color=col, edgecolor="white", linewidth=0.6, label=lab)
        for yy, vv, ll in zip(y, v, left):
            if code == "Y" and vv > 8:
                ax.text(ll + 1.5, yy, f"{vv:.0f}%", va="center", fontsize=5.6, color="white", fontweight="bold")
        left += v
    ax.set_yticks(y, [f"{g} (n={len(x):,})" for g, x in groups], fontsize=5.6)
    M.style(ax, "Triples with a CC BY/CC0 sentence (%)", 100)
    ax.legend(fontsize=5.4, frameon=False, ncol=2, loc="lower center", bbox_to_anchor=(0.4, 1.0))
    ax.text(0, 1.2, "c  Does the source sentence state it? (DeepSeek)", transform=ax.transAxes, fontsize=7, fontweight="bold", color=M.INK)

    # d: reference-KG support
    ax = fig.add_subplot(gs[1, 1])
    ets = [et for et, r in GK["edge_types"].items() if r["resolved_edges"] >= 20]
    lab = {"microbe_disease": "Microbe–disease", "chemical_disease": "Chemical–disease", "gene_disease": "Gene–disease", "chemical_gene": "Chemical–gene"}
    y = np.arange(len(ets))[::-1]
    h = 0.27
    for i, (key, name, col) in enumerate([("kept", "Kept", S1), ("dropped", "Dropped", S2)]):
        vals = [100 * (GK["edge_types"][et][key]["rate"] or 0) for et in ets]
        ax.barh(y + (0.5 - i) * h, vals, height=h * 0.92, color=col, edgecolor="white", label=name)
        for yy, v, et in zip(y + (0.5 - i) * h, vals, ets):
            x0 = max(v, 100 * (GK["edge_types"][et]["chance"] or 0)) + 1.5
            ax.text(x0, yy, f"{v:.0f}% (n={GK['edge_types'][et][key]['n']})", va="center", fontsize=5.2, color=M.INK)
    for yy, et in zip(y, ets):
        c = GK["edge_types"][et]["chance"]
        if c is not None:
            ax.plot([100 * c] * 2, [yy - 0.42, yy + 0.42], color=M.INK2, lw=1.4)
    ax.set_yticks(y, [lab[et] for et in ets], fontsize=6)
    M.style(ax, "Edges whose pair is in a curated KG (%); tick = chance", 100)
    ax.legend(fontsize=5.6, frameon=False, loc="lower right")
    title(ax, "d  Known in Disbiome, BugSigDB or CTD")
    M.save(fig, "fig_triples")


if __name__ == "__main__":
    main()
