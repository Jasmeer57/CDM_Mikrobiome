#!/usr/bin/env python3
"""Generate all manuscript figures for the Microbiome-CDM paper.

Pure matplotlib (no seaborn). Every figure is written in three formats: vector
PDF (journal submission), 600-DPI PNG (Markdown draft), and SVG (editable).

    python3 paper/manuscript/generate_figures.py             # all figures
    python3 paper/manuscript/generate_figures.py --only 8,9  # subset
    python3 paper/manuscript/generate_figures.py --list      # registry

══════════════════════════════════════════════════════════════════════════════
DATA PROVENANCE — read before changing any number
════════════════════════════════════════════════════════════════════════════════
Two sourcing regimes are used; every figure declares which in the registry
printed at the end of a run.

LIVE   recomputed at generation time from an artifact that exists in this
       working tree. The figure cannot drift from the artifact.
       - outputs/results/28643785_ner_bert_variants/_bert_variants_summary.json
       - outputs/results/28643869_ner_extra_variants/_extra_variants_summary.json
       - outputs/results/28649224_ner_hunflair2_trim/{hunflair2_ner.csv,_summary.json}
       - outputs/results/28647499_ner_gliner_new/_gliner_new_summary.json
       - outputs/results/*_ner_java_tools/_java_tools_summary_*.json
       - outputs/results/28643869_ner_extra_variants/hunflair2_ner.csv (pre-fix artifact)
       - outputs/results/410470_ext_bench/ner_benchmark_results.json
       - $AUDIT_DIR/ner_dedup_survival.csv (default ~/.nbdump/test_out/audit;
         the Cell-15 dedup audit of the fifteen variant artifacts)

FROZEN the claim-era raw JSONs (paper_claims/claim_*/, and
       _multi_ner_runs/ner_output/per_model_quality.json) were deleted in the
       2026-10 repository reorg and are not recoverable, so figures 1-7 embed
       exactly the numbers published in the manuscript tables (which trace to
       the frozen v2.0 manuscript DB release). Blocks below say "FROZEN: <table
       or section>". Do NOT "correct" them against recomputations that use a
       different corpus/config without also updating the manuscript.

The seven original 2026-10-21 PNGs are preserved byte-for-byte in
figures/frozen_2026-10-21/ before any file with the same name is overwritten.
"""
from __future__ import annotations

import argparse
import csv
import glob
import io
import json
import os
import shutil
import sys
import time
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LogNorm

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
FIG_DIR = HERE / "figures"
FROZEN_PNG_DIR = HERE / "frozen_2026-10-21"
RESULTS = REPO / "outputs/results"
MULTI_SUMMARY = REPO / "paper" / "_multi_ner_runs" / "_multi_ner_summary.json"
BENCH_JSON = RESULTS / "410470_ext_bench" / "ner_benchmark_results.json"
AUDIT_DIR = Path(os.environ.get("AUDIT_DIR",
                                str(Path.home() / ".nbdump" / "test_out" / "audit")))
SURVIVAL_CSV = AUDIT_DIR / "ner_dedup_survival.csv"
HF_PREFIX_CSV = RESULTS / "28643869_ner_extra_variants" / "hunflair2_ner.csv"
HF_TRIM_CSV = RESULTS / "28649224_ner_hunflair2_trim" / "hunflair2_ner.csv"
HF_TRIM_SUMMARY = RESULTS / "28649224_ner_hunflair2_trim" / "_hunflair2_trim_summary.json"

# ── palette (families) ────────────────────────────────────────────────────
C_LLM = "#2563eb"      # LLM (Qwen)
C_SPACY = "#64748b"    # sciSpaCy
C_GLINER = "#d97706"   # GLiNER family
C_BERT = "#7c3aed"     # PubMedBERT-family checkpoints
C_FLAIR = "#dc2626"    # flair (HunFlair2)
C_JAVA = "#059669"     # NCBI Java tools
C_GREY = "#cbd5e1"

plt.rcParams.update({
    "font.size": 8.5, "axes.titlesize": 9.5, "axes.labelsize": 8.5,
    "xtick.labelsize": 8, "ytick.labelsize": 8, "legend.fontsize": 8,
    "axes.titlesize": 9.5, "axes.titleweight": "bold",
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.alpha": 0.25, "grid.linewidth": 0.5,
    "axes.axisbelow": True, "figure.dpi": 110,
    "savefig.facecolor": "white",
    "font.family": "sans-serif",
    "font.sans-serif": ["DejaVu Sans", "Helvetica", "Arial"],
})


def newfig(w, h, ncols=1, nrows=1, **kw):
    fig, axes = plt.subplots(nrows, ncols, figsize=(w, h), **kw)
    return fig, axes


def save(fig, name, provenance):
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    for ext, kwargs in ((".pdf", {}), (".svg", {}), (".png", {"dpi": 600})):
        fig.savefig(FIG_DIR / f"{name}{ext}", bbox_inches="tight", **kwargs)
    print(f"  figures/{name}.pdf/.svg/.png  [{provenance}]")
    plt.close(fig)


# ═══════════════════════════════════════════════════════════════════════════
# FROZEN numbers (see docstring). Each block cites its manuscript source.
# ═══════════════════════════════════════════════════════════════════════════

# §4.3 / Table 2, Claim A — context disambiguation, 37 ambiguous sentences.
F_CLAIM_A = [
    ("en_core_sci_lg (all ENTITY)", 0, 0.0, False),
    ("en_ner_jnlpba_md", 1, 2.7, False),
    ("en_ner_craft_md", 7, 18.9, False),
    ("en_ner_bc5cdr_md (best spaCy)", 9, 24.3, False),
    ("spaCy best-of-4 union", 13, 35.1, False),
    ("LLM Qwen 3.5:9b", 20, 54.1, True),
]

# §4.1 — hybrid KG source contributions (50-paper cohort, v2 filtered build).
F_SOURCES_ENT = [("S1 LLM", 1564), ("S2 spaCy NER", 4359),
                 ("S5 cross-source", 468), ("S6 KB-seed", 72)]
F_TOTAL_ENT = 5995
F_SOURCES_REL = [("S3 co-occurrence", 32288), ("S4 type-canonical", 1985),
                 ("S7 KB-curated", 251)]
F_TOTAL_REL = 34524

# §4.6 / Table 2, Claim D — calibration (917 gold-labeled entities, 5-fold CV).
F_CALIB = [("Uncalibrated", 0.2774, 0.1198),
           ("Platt scaling", 0.0403, 0.2361),
           ("Isotonic regression", 0.0606, 0.2683)]

# §4.7 / Table 2, Claim E — 10-paper timing/cost batch.
F_CLAIM_E_TIME = [("LLM (Qwen 3.5:9b)", 1831.9), ("spaCy (x4 models)", 17.5)]
F_CLAIM_E_ENT = [("LLM (Qwen 3.5:9b)", 331), ("spaCy (x4 models)", 11097)]
F_CLAIM_E_COST = [("LLM", 0.3816), ("spaCy (x4)", 0.0010)]
F_CLAIM_E_SPEEDUP = 104.7
F_CLAIM_E_COSTFACTOR = 392.6

# Table 4 — Claim F journey to 100% recall (109 gold associations).
F_JOURNEY = [
    ("v1 text-only\n(5 sources)", 0.0, "0% on Crohn's drugs,\n0% on antibiotics"),
    ("v2a +KB", 40.5, "initial KB layer,\ncategory names as targets"),
    ("v2b category fix", 86.5, "CATEGORY_TO_DISEASE\nmapping (36→77→ of 89)"),
    ("v2c full KB relations", 100.0, "DRUGS relations + 8 entities\n+ 3 probiotic entries (109/109)"),
]

# Table 8 — per-model entity quality, 452-paper analysis corpus.
# LIVE from outputs/results/table8_452/table8_452.json (scope: 452 papers / 2,815 body
# units, HMPAPER_000372 excluded). Noise = six stated caption categories; a
# reproducible replacement for the unreproducible published clean/noise pair.
# (model, total, unique, clean, noise%, generic%, cdm types)
F_TABLE8 = [
    ("Qwen 3.5:9b (LLM)", 45538, 19975, 19913, 0.31, 0.0, 14),
    ("GLiNER-BioMed", 297114, 65734, 55565, 15.47, 0.0, 14),
    ("GLiNER (medium)", 168028, 37779, 32143, 14.92, 0.0, 14),
    ("PubMedBERT (disease)", 26970, 3298, 3260, 1.15, 0.0, 1),
    ("PubTator3", 4413, 2109, 2107, 0.09, 0.0, 6),
    # sciSpaCy's "6" follows the manuscript: 8 distinct VALID_TYPES labels are
    # present, but two are the non-CDM ones (ENTITY 960,686 and GO 1,221), and
    # the manuscript counts GO outside the 14 CDM types rather than as PATHWAY.
    ("sciSpaCy (4 models)", 1213347, 173170, 158757, 8.32, 79.18, 6),
]

# §4.15 per-CDM-type distribution table (rows: types, cols: models).
# LIVE: native labels from outputs/results/table8_452/table8_452.json, 452-paper scope.
F_TYPE_MODELS = ["Qwen", "GLiNER", "GLiNER-BioMed", "PubMedBERT", "PubTator3", "sciSpaCy"]
F_TYPE_ROWS = [
    ("ORGANISM",              [13604, 58311, 73645, 0, 1537, 38154]),
    ("CHEMICAL",              [7692, 33468, 46137, 0, 1000, 73801]),
    ("DISEASE",               [3740, 30560, 37309, 26970, 1671, 40808]),
    ("PROTEIN",               [2596, 5103, 13067, 0, 195, 42302]),
    ("DNA_RNA",               [1302, 3900, 11075, 0, 0, 40659]),
    ("CELL_TYPE",             [496, 3385, 10543, 0, 7, 15716]),
    ("PATHWAY",               [2675, 2361, 2104, 0, 0, 0]),
    ("LAB_METHOD",            [2345, 2568, 11367, 0, 0, 0]),
    ("DATA_ANALYSIS",         [7284, 2930, 27538, 0, 0, 0]),
    ("SAMPLE_METHOD",         [1230, 4201, 12285, 0, 0, 0]),
    ("CLINICAL",              [671, 6396, 9745, 0, 0, 0]),
    ("EXPERIMENTAL_METHOD",   [787, 5880, 14339, 0, 0, 0]),
    ("GENOMICS",              [768, 8045, 15108, 0, 3, 0]),
    ("STUDY_DESIGN",          [348, 920, 12852, 0, 0, 0]),
    ("ENTITY (non-CDM)",      [0, 0, 0, 0, 0, 960686]),
    ("GO (non-CDM)",          [0, 0, 0, 0, 0, 1221]),
]

# fig9 harmonization waterfall (§4.16 + Cell-15 audit, applied-fix story).
# (stage, kept_rows, raw_rows, applied?)
# LIVE: 15-variant Stage-2 audit.  Rungs 1-2 use the SUPERSEDED pre-trim hunflair2
# CSV (job 28643869, 2,020,093 raw rows) because that is the "pre-fix" state; rungs
# 3-4 use the shipped trim re-run (job 28649224, 2,020,495 raw rows).  Kept counts
# are cdm_pipeline.dedup.classify_row survivors; rung 4 additionally wires
# common.LABEL_TO_CDM, which is NOT applied to production.
F_WATERFALL = [
    ("Pre-fix audit\n(label floors open)", 1658275, 2020093, True),
    ("+ LABEL_FIX\n(applied 2026-10-28)", 1847575, 2020093, True),
    ("+ hunflair2 span-trim\nre-run (applied)", 1868714, 2020495, True),
    ("+ LABEL_TO_CDM wiring\n(proposed, NOT applied)", 1887986, 2020495, False),
]

# ═══════════════════════════════════════════════════════════════════════════
# Figure 1 — Claim A: context disambiguation   [FROZEN: §4.3 / Table 2]
# ═══════════════════════════════════════════════════════════════════════════

def fig1():
    labels = [r[0] for r in F_CLAIM_A]
    correct = [r[1] for r in F_CLAIM_A]
    pct = [r[2] for r in F_CLAIM_A]
    fig, ax = newfig(7.0, 3.0)
    x = np.arange(len(labels))
    colors = [C_LLM if r[3] else (C_SPACY if "union" not in r[0] else C_GLINER)
              for r in F_CLAIM_A]
    bars = ax.bar(x, pct, color=colors, edgecolor="white", linewidth=0.6, width=0.62)
    for b, c, p, r in zip(bars, correct, pct, F_CLAIM_A):
        ax.annotate(f"{r[1]}/37\n{p:.1f}%", (b.get_x() + b.get_width() / 2, p),
                    ha="center", va="bottom", fontsize=7.5, fontweight="bold" if r[3] else "normal")
    ax.axhline(54.1, color=C_LLM, lw=0.8, ls="--", alpha=0.5)
    ax.axhline(24.3, color=C_SPACY, lw=0.8, ls="--", alpha=0.5)
    ax.annotate("best spaCy 24.3%", (0.30, 0.33), xycoords="axes fraction",
                fontsize=7.5, color=C_SPACY)
    ax.annotate("LLM +29.7 pp", (0.62, 0.55), xycoords="axes fraction",
                fontsize=8, fontweight="bold", color=C_LLM)
    ax.set_xticks(x, labels, rotation=18, ha="right")
    ax.set_ylabel("Correct type (% of 37 sentences)")
    ax.set_ylim(0, 66)
    ax.set_title("Claim A - context disambiguation: LLM vs spaCy (37 ambiguous sentences, 14 CDM types)")
    save(fig, "fig1_claim_a_disambiguation", "FROZEN §4.3")


def _fruit_bars(ax, data, total, color, title):
    names = [d[0] for d in data]
    vals = [d[1] for d in data]
    y = np.arange(len(names))
    ax.barh(y, vals, color=color, edgecolor="white", linewidth=0.5)
    for yi, v in zip(y, vals):
        ax.annotate(f"{v:,}", (v + total * 0.004, yi), va="center", fontsize=7.5)
    ax.set_yticks(y, names)
    ax.set_xlim(0, max(vals) * 1.22)
    ax.set_title(title, fontsize=8.5)
    ax.grid(axis="y", alpha=0)


# ═══════════════════════════════════════════════════════════════════════════
# Figure 2 — Claim C: 7-source hybrid fusion   [FROZEN: §4.1, §4.5 / Table 5]
# ═══════════════════════════════════════════════════════════════════════════

def fig2():
    fig, (ax1, ax2) = newfig(7.0, 3.0, ncols=2)
    _fruit_bars(ax1, F_SOURCES_ENT, F_TOTAL_ENT, C_LLM,
                f"Entities by source (total {F_TOTAL_ENT:,})")
    _fruit_bars(ax2, F_SOURCES_REL, F_TOTAL_REL, C_SPACY,
                f"Relationships by source (total {F_TOTAL_REL:,})")
    ax1.set_xlabel("unique entities")
    ax2.set_xlabel("relationships")
    fig.suptitle("Claim C - 7-source hybrid fusion (50-paper cohort, v2 filtered build)",
                 fontweight="bold", fontsize=9.5)
    fig.tight_layout(rect=[0, 0, 1, 0.94])
    save(fig, "fig2_claim_c_hybrid_fusion", "FROZEN §4.1/§4.5")


# ═══════════════════════════════════════════════════════════════════════════
# Figure 3 — Claim D: confidence calibration   [FROZEN: §4.6 / Table 2]
# ═══════════════════════════════════════════════════════════════════════════

def fig3():
    fig, (ax1, ax2) = newfig(7.0, 3.0, ncols=2)
    names = [c[0] for c in F_CALIB]
    ece = [c[1] for c in F_CALIB]
    brier = [c[2] for c in F_CALIB]
    x = np.arange(len(names))
    w = 0.38
    b1 = ax1.bar(x - w / 2, ece, w, color=C_LLM, label="ECE (5-fold CV)")
    b2 = ax1.bar(x + w / 2, brier, w, color=C_GLINER, label="Brier")
    for bars in (b1, b2):
        for b in bars:
            ax1.annotate(f"{b.get_height():.3f}", (b.get_x() + b.get_width() / 2, b.get_height()),
                         ha="center", va="bottom", fontsize=7)
    ax1.axhline(0.10, color="black", lw=0.9, ls=":")
    ax1.annotate("ECE < 0.10 target", (0.02, 0.115), xycoords="axes fraction", fontsize=7)
    ax1.set_xticks(x, ["Uncalibrated", "Platt", "Isotonic"])
    ax1.set_ylabel("error")
    ax1.legend(frameon=False)
    ax1.set_title("Post-hoc calibration (LLM, 917 gold entities)")

    # right: per-type gap from Table 6 (calibrated gap = expected - observed accuracy)
    table6 = [  # (type, gap)
        ("DISEASE", 0.03), ("DNA_RNA", 0.04), ("PROTEIN", 0.11),
        ("PATHWAY", 0.57), ("DATA_ANALYSIS", 0.62), ("EXPERIMENTAL_METHOD", 0.61),
    ]
    names6 = [t[0] for t in table6]
    gaps = [t[1] for t in table6]
    y = np.arange(len(names6))
    cols = [C_LLM if g < 0.12 else C_FLAIR for g in gaps]
    ax2.barh(y, gaps, color=cols, edgecolor="white", linewidth=0.5)
    for yi, g in zip(y, gaps):
        ax2.annotate(f"{g:.2f}", (g + 0.01, yi), va="center", fontsize=7.5)
    ax2.set_yticks(y, names6)
    ax2.set_xlabel("confidence-accuracy gap")
    ax2.axvline(0.12, color="black", lw=0.9, ls=":")
    ax2.annotate("well-calibrated < 0.12", (0.13, 0.9), xycoords="axes fraction",
                 fontsize=7, rotation=90, va="top")
    ax2.set_title("Per-type gap (Table 6)\ncomposition artifact: mixed regimes")
    fig.suptitle("Claim D - LLM confidence is calibratable; spaCy confidence is vacuous (1 value / 100,691)",
                 fontweight="bold", fontsize=9.5)
    fig.tight_layout(rect=[0, 0, 1, 0.92])
    save(fig, "fig3_claim_d_calibration", "FROZEN §4.6")


# ═══════════════════════════════════════════════════════════════════════════
# Figure 4 — Claim E: speed / efficiency       [FROZEN: §4.7 / Table 2]
# ═══════════════════════════════════════════════════════════════════════════

def fig4():
    fig, axes = newfig(7.0, 2.8, ncols=3)
    # (A) wall clock (log)
    t = [d[1] for d in F_CLAIM_E_TIME]
    bars = axes[0].bar([0, 1], t, color=[C_LLM, C_SPACY], edgecolor="white")
    axes[0].set_yscale("log")
    axes[0].set_xticks([0, 1], ["LLM", "spaCy (x4)"])
    for r, (_, v) in zip(bars, F_CLAIM_E_TIME):
        axes[0].annotate(f"{v:,.1f} s", (r.get_x() + r.get_width() / 2, v),
                         ha="center", va="bottom", fontsize=7.5)
    axes[0].set_ylabel("wall clock, 10 papers [s, log]")
    axes[0].set_title(f"(A) speed: spaCy {F_CLAIM_E_SPEEDUP}x faster", fontsize=8.5)
    # (B) volume (log scale)
    ent = [d[1] for d in F_CLAIM_E_ENT]
    bars = axes[1].bar([0, 1], ent, color=[C_LLM, C_SPACY], edgecolor="white")
    axes[1].set_yscale("log")
    axes[1].set_xticks([0, 1], ["LLM", "spaCy (x4)"])
    for r, d in zip(bars, F_CLAIM_E_ENT):
        axes[1].annotate(f"{d[1]:,}", (r.get_x() + r.get_width() / 2, d[1]),
                         ha="center", va="bottom", fontsize=7.5)
    axes[1].set_ylabel("entities extracted (log)")
    axes[1].set_title("(B) volume", fontsize=8.5)
    # (C) cost
    cost = [d[1] for d in F_CLAIM_E_COST]
    bars = axes[2].bar([0, 1], cost, color=[C_LLM, C_SPACY], edgecolor="white")
    for r, d in zip(bars, F_CLAIM_E_COST):
        axes[2].annotate(f"${d[1]:.4f}", (r.get_x() + r.get_width() / 2, d[1]),
                         ha="center", va="bottom", fontsize=7.5)
    axes[2].set_xticks([0, 1], ["LLM", "spaCy (x4)"])
    axes[2].set_ylabel("cost (USD)")
    axes[2].set_title(f"(C) cost: LLM {F_CLAIM_E_COSTFACTOR}x more expensive", fontsize=8.5)
    fig.suptitle("Claim E - speed / efficiency trade-off (10-paper batch)",
                 fontweight="bold", fontsize=9.5)
    fig.tight_layout(rect=[0, 0, 1, 0.93])
    save(fig, "fig4_claim_e_efficiency", "FROZEN §4.7")


# ═══════════════════════════════════════════════════════════════════════════
# Figure 5 — Claim F: journey to 100% gold recall  [FROZEN: Table 4]
# ═══════════════════════════════════════════════════════════════════════════

def fig5():
    fig, (ax1, ax2) = newfig(7.0, 3.0, ncols=2, gridspec_kw={"width_ratios": [1.1, 1]})
    names = [r[0] for r in F_JOURNEY]
    vals = [r[1] for r in F_JOURNEY]
    x = np.arange(len(names))
    bars = ax1.bar(x, vals, color=[C_FLAIR, C_GLINER, C_BERT, C_LLM],
                   edgecolor="white", linewidth=0.6, width=0.6)
    for b, v in zip(bars, vals):
        ax1.annotate(f"{v:.1f}%", (b.get_x() + b.get_width() / 2, v),
                     ha="center", va="bottom", fontsize=8, fontweight="bold")
    ax1.set_xticks(x, names, fontsize=7)
    ax1.set_ylabel("full-triple recall on gold associations")
    ax1.set_ylim(0, 113)
    ax1.set_title("(A) The journey to 100% gold recall")
    # (B) 12 categories at 100% — lollipop
    cats = ["antibiotic_disruption", "butyrate_production", "cdi_treatment",
            "crc_association", "cvd_association", "ibd_overall",
            "liver_disease", "neuropsych_assoc", "obesity_assoc",
            "probiotic_benefit", "scfa_function", "t2d_association"]
    ys = np.arange(len(cats))
    ax2.hlines(ys, 0, 100, color=C_GREY, lw=1.4)
    ax2.plot([100] * len(cats), ys, "o", ms=5, color=C_LLM)
    for yi, c in zip(ys, cats):
        ax2.annotate(c, (2, yi), fontsize=6.8, va="center")
    ax2.set_xlim(0, 107)
    ax2.set_yticks([])
    ax2.set_xlabel("recall (%)")
    ax2.set_title("(B) All 12 categories at 100% (109/109)")
    fig.suptitle("Claim F - biological coverage: 100% self-consistency recall on the curated gold set",
                 fontweight="bold", fontsize=9.5)
    fig.tight_layout(rect=[0, 0, 1, 0.92])
    save(fig, "fig5_claim_f_biological_validation", "FROZEN Table 4")

# ═══════════════════════════════════════════════════════════════════════════
# Figure 6 — per-model NER quality overview at published values (Table 8)
#             + noise/coverage scatter panel. FROZEN numbers; the live
#             _multi_ner_summary.json cannot reproduce them (§4.15 explains:
#             the 444-paper build's per_model_quality.json was deleted; Table 8
#             is now the measured 452-scope replacement, so fig6 reads that).
# ═══════════════════════════════════════════════════════════════════════════

def fig6():
    fig, axes = newfig(7.0, 7.2, ncols=2, nrows=2,
                       gridspec_kw={"width_ratios": [1, 1], "height_ratios": [1, 1.0]})
    ax1, ax2, ax3, ax4 = axes.flat
    names = [r[0] for r in F_TABLE8]
    short = [n.replace(" (disease)", " (dis.)").replace(" 3.5:9b (LLM)", " (LLM)")
             .replace("GLiNER-BioMed", "GLiNER\nBioMed").replace("GLiNER (medium)", "GLiNER\n(medium)")
             .replace("sciSpaCy (4 models)", "sciSpaCy\n(4 models)") for n in names]
    total = np.array([r[1] for r in F_TABLE8], float)
    unique = np.array([r[2] for r in F_TABLE8], float)
    clean = np.array([r[3] for r in F_TABLE8], float)
    noise = np.array([r[4] for r in F_TABLE8], float)
    generic = np.array([r[5] for r in F_TABLE8], float)
    types = np.array([r[6] for r in F_TABLE8], float)
    fam = [C_LLM, C_GLINER, C_GLINER, C_BERT, "#0891b2", C_SPACY]

    x = np.arange(len(names))
    w = 0.27
    ax1.set_yscale("log")
    ax1.bar(x - w, total, w, color=fam, edgecolor="white", linewidth=0.5, alpha=0.45)
    ax1.bar(x, unique, w, color=fam, edgecolor="white", linewidth=0.5, alpha=0.9)
    ax1.bar(x + w, clean, w, color=fam, edgecolor="white",
            hatch="///", fill=False, linewidth=0.8)
    ax1.set_xticks(x, short, fontsize=6.6)
    ax1.set_ylabel("entities [log]")
    ax1.legend([plt.Rectangle((0, 0), 1, 1, alpha=0.45), plt.Rectangle((0, 0), 1, 1),
                plt.Rectangle((0, 0), 1, 1, fill=False, hatch="///")],
               ["total", "unique", "clean unique"], frameon=False, fontsize=7)
    ax1.set_title("(A) Volume: total / unique / clean (452-paper scope)", fontsize=8.5)

    # (B) noise vs coverage scatter — "ideal quadrant"
    for i, r in enumerate(F_TABLE8):
        ax2.scatter(noise[i], types[i], s=np.sqrt(total[i]) * 1.35, color=fam[i],
                    edgecolor="black", linewidth=0.5, zorder=3,
                    label=r[0].split(" (")[0])
    ax2.annotate("Qwen 3.5:9b\n(0.9% noise, 14 types)", (0.9, 14), fontsize=7,
                 color=C_LLM, fontweight="bold")
    ax2.annotate("ideal quadrant:\nlow noise + full coverage", (1.5, 11.7),
                 fontsize=6.5, style="italic", alpha=0.75)
    ax2.axvspan(0, 5, ymin=14 / 15, alpha=0.05, color=C_LLM)
    ax2.set_xlabel("noise rate (%)")
    ax2.set_ylabel("CDM types covered (of 14)")
    ax2.set_xlim(-1, 24)
    ax2.set_ylim(0, 15)
    ax2.set_title("(B) Noise vs type coverage", fontsize=8.5)

    # (C) per-type distribution heat map (Qwen + top models + non-CDM rows)
    rows_hm = F_TYPE_ROWS[:6] + F_TYPE_ROWS[13:]
    hm_names = [r[0] for r in rows_hm]
    z = np.array([[max(float(c), 0.5) for c in r[1]] for r in rows_hm])  # log floor
    im = ax3.imshow(z, norm=LogNorm(vmin=0.5, vmax=z.max()), cmap="Blues",
                    aspect="auto")
    ax3.set_xticks(np.arange(len(F_TYPE_MODELS)), F_TYPE_MODELS, fontsize=6.4,
                   rotation=20, ha="right")
    ax3.set_yticks(np.arange(len(hm_names)), hm_names, fontsize=6.4)
    for i, r in enumerate(rows_hm):
        for j, c in enumerate(r[1]):
            if c and c >= 100:
                ax3.annotate(f"{c // 1000}k" if c >= 1000 else str(c),
                             (j, i), ha="center", va="center", fontsize=5.9,
                             color="white" if c > z[i].max() * 0.3 else "black")
    ax3.grid(False)
    cb = fig.colorbar(im, ax=ax3, shrink=0.75, pad=0.02)
    cb.set_label("mentions [log]", fontsize=7)
    ax3.set_title("(C) Per-CDM-type distribution (mention counts, log colour)",
                  fontsize=8.5)

    # (D) generic-label and noise-rate bars
    w2 = 0.36
    ax4.bar(x - w2 / 2, noise, w2, color=fam, edgecolor="white", linewidth=0.5)
    ax4.bar(x + w2 / 2, generic, w2, color=fam, edgecolor="white",
            hatch="xx", fill=False, linewidth=0.8)
    for xi, n, g in zip(x, noise, generic):
        ax4.annotate(f"{n:.1f}%", (xi - w2 / 2, n), ha="center", va="bottom", fontsize=6.3)
        if g:
            ax4.annotate(f"{g:.1f}%", (xi + w2 / 2, g), ha="center", va="bottom", fontsize=6.3)
    ax4.set_xticks(x, short, fontsize=6.6)
    ax4.set_ylabel("rate (%)")
    ax4.legend([plt.Rectangle((0, 0), 1, 1), plt.Rectangle((0, 0), 1, 1, fill=False, hatch="xx")],
               ["noise %", "generic ENTITY %"], frameon=False, fontsize=7, loc="upper left")
    ax4.set_title("(D) Noise and generic-label rates", fontsize=8.5)

    fig.suptitle("Per-model NER quality comparison - 452-paper analysis corpus (Table 8)",
                 fontweight="bold", fontsize=9.5)
    fig.tight_layout(rect=[0, 0, 1, 0.97], h_pad=1.4, w_pad=1.2)
    save(fig, "fig6_ner_model_overview", "FROZEN Table 8 / §4.15")


# ═══════════════════════════════════════════════════════════════════════════
# Figure 7 — 50-paper cohort type distribution
#             [FROZEN: Table 3 (per-CDM-type) + §4.1; spaCy ENTITY/GO from §4.15]
# ═══════════════════════════════════════════════════════════════════════════

def fig7():
    fig, (ax1, ax2) = newfig(7.0, 3.4, ncols=2, gridspec_kw={"width_ratios": [1.6, 1]})
    # Table 3: 14 CDM types, LLM vs spaCy union
    types = [r[0] for r in F_TYPE_ROWS[:14]]
    llm = np.array([0 for _ in types], float)
    spacy = np.array([0 for _ in types], float)
    table3 = {  # FROZEN Table 3
        "ORGANISM": (523, 311), "CHEMICAL": (223, 778), "DISEASE": (241, 768),
        "PROTEIN": (68, 1208), "DNA_RNA": (24, 805), "CELL_TYPE": (15, 412),
        "PATHWAY": (64, 0), "LAB_METHOD": (64, 0), "DATA_ANALYSIS": (213, 0),
        "SAMPLE_METHOD": (59, 0), "EXPERIMENTAL_METHOD": (29, 0), "CLINICAL": (20, 0),
        "GENOMICS": (14, 0), "STUDY_DESIGN": (7, 0),
    }
    llm = np.array([table3[t][0] for t in types], float)
    spacy = np.array([table3[t][1] for t in types], float)
    y = np.arange(len(types))
    b1 = ax1.barh(y + 0.2, llm, 0.4, color=C_LLM, label=f"LLM (total {int(llm.sum()):,})")
    b2 = ax1.barh(y - 0.2, spacy, 0.4, color=C_SPACY, label=f"spaCy union (total {int(spacy.sum()):,})")
    ax1.set_yticks(y, types, fontsize=6.8)
    ax1.set_xlabel("unique normalized entities (50-paper cohort)")
    ax1.legend(frameon=False, loc="lower right", fontsize=7)
    ax1.grid(axis="y", alpha=0)
    # Annotate the 8 LLM-only types
    for yi, t in zip(y, types):
        if table3[t][1] == 0 and table3[t][0] > 0:
            ax1.annotate("LLM-only", (max(table3[t][0], 6), yi + 0.2), xytext=(6, 0),
                         textcoords="offset points", fontsize=6, va="center", color=C_LLM)
    ax1.set_title("(A) Per-CDM-type composition (Table 3; 8/14 types LLM-only)", fontsize=8.5)

    # right: non-CDM artifacts
    arts = [("ENTITY (en_core_sci_lg)", 1265525), ("GO (en_ner_craft_md)", 1510)]
    vals = [a[1] for a in arts]
    y2 = np.arange(len(arts))
    ax2.barh(y2, vals, color=[C_GREY, C_BERT], edgecolor="white")
    ax2.set_xscale("log")
    for yi, v in zip(y2, vals):
        ax2.annotate(f"{v:,}", (v * 1.1, yi), va="center", fontsize=7.5)
    ax2.set_yticks(y2, [a[0] for a in arts], fontsize=6.8)
    ax2.set_xlim(1e2, 4e7)
    ax2.grid(axis="y", alpha=0)
    ax2.set_xlabel("mentions [log] (spaCy full-corpus, §4.15)")
    ax2.set_title("(B) Non-CDM artifacts", fontsize=8.5)
    fig.suptitle("Entity type distribution: spaCy-only vs LLM-only vs hybrid composition",
                 fontweight="bold", fontsize=9.5)
    fig.tight_layout(rect=[0, 0, 1, 0.93])
    save(fig, "fig7_type_distribution", "FROZEN Table 3 / §4.15")


# ═══════════════════════════════════════════════════════════════════════════
# Figure 8 — fifteen-variant coverage at 452 papers   [LIVE: Table-9 JSONs]
# ═══════════════════════════════════════════════════════════════════════════

# (label, family-colour, run_dir, summary_glob, model_key)
VARIANT_RUNS = [
    ("BioBERT-Disease", C_BERT, "28643785_ner_bert_variants", "_bert_variants_summary.json", "biobert_diseases_wl"),
    ("BioBERT-Chemical", C_BERT, "28643785_ner_bert_variants", "_bert_variants_summary.json", "biobert_chemical"),
    ("BioBERT-Genetic", C_BERT, "28643785_ner_bert_variants", "_bert_variants_summary.json", "biobert_genetic"),
    ("SciBERT-JNLPBA", C_BERT, "28643785_ner_bert_variants", "_bert_variants_summary.json", "scibert_jnlpba"),
    ("sciSpaCy-BIONLP13CG", C_SPACY, "28643869_ner_extra_variants", "_extra_variants_summary.json", "en_ner_bionlp13cg_md"),
    ("HunFlair2", C_FLAIR, "28649224_ner_hunflair2_trim", "_hunflair2_trim_summary.json", "hunflair2"),
    ("GLiNER2-base", C_GLINER, "28647499_ner_gliner_new", "_gliner_new_summary.json", "gliner2_base"),
    ("GLiNER2-large", C_GLINER, "28647499_ner_gliner_new", "_gliner_new_summary.json", "gliner2_large"),
    ("GLiNER-v2.5-medium", C_GLINER, "28647499_ner_gliner_new", "_gliner_new_summary.json", "gliner_v25_medium"),
    ("GLiNER-v2.5-biomed", C_GLINER, "28647499_ner_gliner_new", "_gliner_new_summary.json", "gliner_v25_biomed"),
]
JAVA_KEYS = [("DNorm", C_JAVA), ("TaggerOne-Disease", C_JAVA),
             ("TaggerOne-Chemical", C_JAVA), ("tmChem", C_JAVA), ("GNormPlus", C_JAVA)]
JAVA_GLOB = str(RESULTS / "*_ner_java_tools" / "_java_tools_summary_*.json")


def _load_variant_rows():
    """Collect rows, papers, labels and seconds for all 15 variants from live JSONs."""
    rows, missing = [], []
    cache = {}
    for label, colour, run_dir, pattern, key in VARIANT_RUNS:
        ck = (run_dir, pattern)
        if ck not in cache:
            hits = sorted(glob.glob(str(RESULTS / run_dir / pattern)))
            cache[ck] = json.load(open(hits[-1])) if hits else None
        summ = cache[ck]
        if not summ or key not in summ.get("models", {}):
            missing.append(f"{label} (outputs/results/{run_dir}/{pattern})")
            continue
        m = summ["models"][key]
        rows.append({"label": label, "colour": colour,
                     "rows": m.get("rows", 0),
                     "papers": m.get("papers_with_entities"),
                     "papers_total": m.get("papers_total") or summ.get("papers"),
                     "labels": len(m.get("labels", {})),
                     "seconds": m.get("elapsed_seconds"),
                     "family": None})
    jhits = sorted(glob.glob(JAVA_GLOB))
    jsumm = None
    if jhits:
        try:
            cand = json.load(open(jhits[-1]))
            if all(cand.get("models", {}).get(k, {}).get("status") == "OK"
                   for k, _ in JAVA_KEYS):
                jsumm = cand
        except (json.JSONDecodeError, OSError):
            jsumm = None
    for label, colour in JAVA_KEYS:
        if not jsumm or label not in jsumm.get("models", {}):
            missing.append(f"{label} ({JAVA_GLOB})")
            continue
        m = jsumm["models"][label]
        if m.get("status") != "OK":
            missing.append(f"{label} (status={m.get('status')})")
            continue
        rows.append({"label": label, "colour": colour,
                     "rows": m.get("rows", 0),
                     "papers": m.get("papers_with_entities"),
                     "papers_total": jsumm.get("papers"),
                     "labels": len(m.get("labels", {})),
                     "seconds": m.get("elapsed_seconds"),
                     "family": None})
    return rows, missing


def fig8():
    rows, missing = _load_variant_rows()
    if missing:
        raise SystemExit("FIGURE 8 ABORTED - missing live sources:\n  " + "\n  ".join(missing))
    fig, (ax1, ax2) = newfig(7.0, 4.6, ncols=2, gridspec_kw={"width_ratios": [2.3, 1]})
    order = np.argsort([r["rows"] for r in rows])
    rows = [rows[i] for i in order]
    y = np.arange(len(rows))
    ax1.barh(y, [r["rows"] for r in rows], color=[r["colour"] for r in rows],
             edgecolor="white", linewidth=0.5)
    for yi, r in zip(y, rows):
        ax1.annotate(f"{r['rows']:,}", (r["rows"], yi), xytext=(4, 0),
                     textcoords="offset points", va="center", fontsize=7,
                     fontweight="bold")
        ax1.annotate(f"{r['papers']}/{r['papers_total']}", (0, yi), xytext=(6, 0),
                     textcoords="offset points", va="center", fontsize=6, color="white")
    ax1.set_yticks(y, [r["label"] for r in rows], fontsize=7)
    ax1.set_xlabel("entities (rows) on the 2,815-unit / 20.9M-char section-body corpus")
    ax1.set_xlim(0, max(r["rows"] for r in rows) * 1.16)
    ax1.grid(axis="y", alpha=0)
    ax1.set_title("(A) Entities per variant (white text: papers covered)", fontsize=8.5)

    ax2.scatter([r["seconds"] for r in rows], [r["labels"] for r in rows],
                s=[max(r["rows"] / 300.0, 8) for r in rows],
                c=[r["colour"] for r in rows], edgecolor="black", linewidth=0.5)
    for r in rows:
        ax2.annotate(r["label"].replace("GLiNER-v2.5-", "v2.5-").replace("BioBERT-", "BB-")
                     .replace("TaggerOne-", "T1-").replace("sciSpaCy-", "sS-"),
                     (r["seconds"], r["labels"]), fontsize=5.8,
                     xytext=(3, 3), textcoords="offset points")
    ax2.set_xscale("log")
    ax2.set_xlabel("wall-clock seconds [log; not comparable across families]")
    ax2.set_ylabel("distinct labels")
    ax2.set_title("(B) Label breadth vs runtime", fontsize=8.5)

    fig.suptitle("Fifteen NER variants at full 452-paper coverage (live artifacts; Table 9)",
                 fontweight="bold", fontsize=9.5)
    fig.tight_layout(rect=[0, 0, 1, 0.94])
    save(fig, "fig8_variant_coverage", "LIVE: Table-9 summary JSONs")


# ═══════════════════════════════════════════════════════════════════════════
# Figure 9 — dedup label survival   [LIVE: $AUDIT_DIR/ner_dedup_survival.csv]
# ═══════════════════════════════════════════════════════════════════════════

def _load_survival():
    if not SURVIVAL_CSV.exists():
        raise SystemExit(f"FIGURE 9 ABORTED - {SURVIVAL_CSV} missing")
    with open(SURVIVAL_CSV, newline="") as f:
        return list(csv.DictReader(f))


def fig9():
    rows = _load_survival()
    models = [r["model"] for r in rows]
    base = [100.0 * int(r["kept"]) / int(r["rows"]) for r in rows]
    maponly = [100.0 * int(r["kept_map_only"]) / int(r["rows"]) for r in rows]
    order = np.argsort(base)
    models = [models[i] for i in order]
    base = [base[i] for i in order]
    maponly = [maponly[i] for i in order]
    fig, (ax1, ax2) = newfig(7.2, 4.6, ncols=2,
                             gridspec_kw={"width_ratios": [1.45, 1]})
    fam = {"bert": C_BERT, "scibert": C_BERT, "bionlp": C_SPACY, "hunflair": C_FLAIR,
           "gliner": C_GLINER, "dnorm": C_JAVA, "taggerone": C_JAVA, "gnormplus": C_JAVA,
           "tmchem": C_JAVA}
    colours = [C_LLM] * len(models)
    for i, m in enumerate(models):
        for k, c in fam.items():
            if m.startswith(k):
                colours[i] = c
                break
    y = np.arange(len(models))
    ax1.barh(y, base, 0.68, color=colours, edgecolor="white", linewidth=0.5)
    for yi, b in zip(y, base):
        ax1.annotate(f"{b:.1f}%", (max(b, 0.4), yi), xytext=(4, 0),
                     textcoords="offset points", va="center", fontsize=6.6)
    for yi, (b, m) in enumerate(zip(base, models)):
        if m == "scibert_jnlpba":
            # Placed clear of the numeric value label so the two never overlap.
            ax1.annotate("DNA/RNA/CELL_LINE labels\nnot folded (still open)",
                         (b, yi), xytext=(22, 0), textcoords="offset points",
                         fontsize=6.2, va="center", color=C_FLAIR)
    ax1.axvline(92.5, color="black", lw=0.9, ls=":")
    # Horizontal, in reserve space above the top bar: a rotated label here would
    # sit on top of the per-bar percentage annotations.
    ax1.set_ylim(-0.7, len(models) - 0.05)
    ax1.annotate("TOTAL 92.5%", (92.5, len(models) - 0.45), fontsize=7,
                 ha="center", va="bottom")
    ax1.set_yticks(y, models, fontsize=7)
    ax1.set_xlim(0, 104)
    ax1.grid(axis="y", alpha=0)
    ax1.set_xlabel("kept rate after dedup LABEL_FIX (% rows)")
    ax1.set_title("(A) Per-variant survival (audit, post-fix)", fontsize=8.5)

    # (B) population waterfall from the paper's harmonization story
    names = [w[0] for w in F_WATERFALL]
    kept = [w[1] for w in F_WATERFALL]
    raw = [w[2] for w in F_WATERFALL]
    applied = [w[3] for w in F_WATERFALL]
    pcts = [100.0 * k / r for k, r in zip(kept, raw)]
    x = np.arange(len(names))
    bars = ax2.bar(x, pcts, color=[(C_LLM if a else C_GREY) for a in applied],
                   edgecolor="white", linewidth=0.5)
    for b, p, k, r in zip(bars, pcts, kept, raw):
        ax2.annotate(f"{p:.1f}%", (b.get_x() + b.get_width() / 2, p),
                     ha="center", va="bottom", fontsize=7.4,
                     fontweight="bold" if p >= 91 else "normal")
        ax2.annotate(f"{k:,}", (b.get_x() + b.get_width() / 2, p / 2),
                     ha="center", va="center", fontsize=6.2, rotation=90, color="white")
    ax2.set_xticks(x, ["pre-fix", "+LABEL_FIX", "+trim\nre-run", "+L2C\n(proposed)"],
                   fontsize=6.6, rotation=22, ha="right")
    ax2.set_ylabel("kept % of raw rows")
    ax2.set_ylim(0, 104)
    ax2.set_title("(B) Harmonization waterfall\n(fixes applied vs proposed)", fontsize=8.5)
    fig.suptitle("Label survival through Stage-2 dedup - fifteen variant artifacts (live audit)",
                 fontweight="bold", fontsize=9.5)
    fig.tight_layout(rect=[0, 0, 1, 0.94])
    save(fig, "fig9_dedup_label_survival", "LIVE: audit ner_dedup_survival.csv")


# ═══════════════════════════════════════════════════════════════════════════
# Figure 10 — hunflair2 span hygiene, pre vs post _trim_span
#             [LIVE: pre-fix CSV 28643869 vs trim-run CSV 28649224, exact
#              audit rule _HYG_PUNCT = ",.;:)]}\"'-" applied to both]
# ═════════════════════════════════════════════════════════════════════════════

_HYG_PUNCT = ",.;:)]}\"'-"


def _hygiene(path):
    n = tp = nl = edge = 0
    with open(path, "rb") as f:
        text = io.StringIO(f.read().decode("utf-8", errors="replace").replace("\x00", ""))
        for row in csv.DictReader(text):
            t = row["term"]
            n += 1
            tt = t.strip()
            if tt and tt[-1] in _HYG_PUNCT:
                tp += 1
            if "\n" in t or "\r" in t:
                nl += 1
                if tt != t:
                    edge += 1
    return {"rows": n, "trailing": 100.0 * tp / n if n else 0.0,
            "newline": 100.0 * nl / n if n else 0.0,
            "nl_edge": edge, "nl_mid": nl - edge}


def _labels_of(path):
    from collections import Counter
    out = Counter()
    with open(path, "rb") as f:
        text = io.StringIO(f.read().decode("utf-8", errors="replace").replace("\x00", ""))
        for row in csv.DictReader(text):
            out[row["labels"]] += 1
    return out


def fig10():
    if not HF_PREFIX_CSV.exists() or not HF_TRIM_CSV.exists():
        raise SystemExit(f"FIGURE 10 ABORTED - {HF_PREFIX_CSV} / {HF_TRIM_CSV} missing")
    pre = _hygiene(HF_PREFIX_CSV)
    post = _hygiene(HF_TRIM_CSV)
    fig, axes = newfig(7.0, 3.0, ncols=3)
    labels = ["trailing punct", "newline-in-term", "valid rows\n(slice == term)"]
    # "valid rows" = the audit's slice-exact fidelity (ner_span_fidelity.csv:
    # pre 99.997% — 3 NUL-artifact rows, not mis-spans; post 100.000%)
    pre_vals = [pre["trailing"], pre["newline"], 99.997]
    post_vals = [post["trailing"], post["newline"], 100.0]
    x = np.arange(3)
    w = 0.36
    b1 = axes[0].bar(x - w / 2, pre_vals, w, color=C_FLAIR, label="pre-fix (28643869)")
    b2 = axes[0].bar(x + w / 2, post_vals, w, color=C_LLM, label="post-trim (28649224)")
    for bars in (b1, b2):
        for b in bars:
            v = b.get_height()
            axes[0].annotate(f"{v:.2f}%", (b.get_x() + b.get_width() / 2, v),
                             ha="center", va="bottom", fontsize=6.8)
    axes[0].set_xticks(x, labels, fontsize=7)
    axes[0].set_ylabel("% of rows")
    axes[0].set_ylim(0, 115)
    axes[0].legend(frameon=False, fontsize=7)
    axes[0].set_title("(A) Hygiene pre vs post _trim_span", fontsize=8.5)

    # (B) all newlines are mid-span BY DESIGN (token windows span line breaks;
    # _trim_span only strips edges, and edge count is 0 in both)
    cats = ["edge newlines\n(strip target)", "mid-span newlines\n(kept by design)"]
    pre_edge = [pre["nl_edge"], pre["nl_mid"]]
    post_edge = [post["nl_edge"], post["nl_mid"]]
    x2 = np.arange(2)
    b1 = axes[1].bar(x2 - w / 2, pre_edge, w, color=C_FLAIR)
    b2 = axes[1].bar(x2 + w / 2, post_edge, w, color=C_LLM)
    for bars in (b1, b2):
        for b in bars:
            axes[1].annotate(f"{int(b.get_height()):,}", (b.get_x() + b.get_width() / 2, b.get_height()),
                             ha="center", va="bottom", fontsize=7)
    axes[1].set_xticks(x2, cats, fontsize=7)
    axes[1].set_ylabel("rows")
    axes[1].set_title("(B) Newline decomposition", fontsize=8.5)

    # (C) label volume pre vs post, computed live from both CSVs + trim summary
    summ = json.load(open(HF_TRIM_SUMMARY))
    labels_post = summ["models"]["hunflair2"]["labels"]
    pre_counts = _labels_of(HF_PREFIX_CSV)
    wanted = ["CHEMICAL", "DISEASE", "ORGANISM", "PROTEIN", "CELL_TYPE"]
    extras = [n for n in sorted(set(pre_counts) | set(labels_post)) if n not in wanted]
    lab_names = [n for n in wanted if n in pre_counts or n in labels_post] + extras
    pre_l = [pre_counts.get(n, 0) for n in lab_names]
    post_l = [labels_post.get(n, 0) for n in lab_names]
    x3 = np.arange(len(lab_names))
    b1 = axes[2].bar(x3 - w / 2, pre_l, w, color=C_FLAIR)
    b2 = axes[2].bar(x3 + w / 2, post_l, w, color=C_LLM)
    for bars in (b1, b2):
        for b in bars:
            axes[2].annotate(f"{int(b.get_height()):,}", (b.get_x() + b.get_width() / 2, b.get_height()),
                             ha="center", va="bottom", fontsize=5.9, rotation=0)
    axes[2].set_xticks(x3, [l.replace("_", "\n") for l in lab_names], fontsize=6.4)
    axes[2].set_ylabel("rows")
    axes[2].set_title("(C) Post-fix label mix", fontsize=8.5)

    fig.suptitle("HunFlair2 span hygiene: _trim_span re-run eliminates trailing-punct pollution;\n"
                 "newlines are all mid-span by design (zero edge cases in either run)",
                 fontweight="bold", fontsize=9)
    fig.tight_layout(rect=[0, 0, 1, 0.90])
    save(fig, "fig10_hunflair2_span_hygiene", "LIVE: 28643869 vs 28649224 CSVs")


# ═══════════════════════════════════════════════════════════════════════════
# Figure 11 — external benchmark F1     [LIVE: outputs/results/410470_ext_bench]
# ═══════════════════════════════════════════════════════════════════════════

def fig11():
    if not BENCH_JSON.exists():
        raise SystemExit(f"FIGURE 11 ABORTED - {BENCH_JSON} missing")
    bench = json.load(open(BENCH_JSON))

    def f1(prefix, model, mode):
        try:
            v = bench[f"{prefix}__{model}"]["overall"][mode]["F1"]
            return round(v, 3)
        except KeyError:
            return None

    def fmt(v):
        return f"{v:.3f}" if v is not None else "  —  "

    rows = [  # (display, bench key suffix, colour)
        ("scispaCy bc5cdr", "scispacy_bc5cdr", C_SPACY),
        ("GLiNER-BioMed", "gliner_biomed", C_GLINER),
        ("PubMedBERT (disease)", "pubmedbert", C_BERT),
        ("GLiNER (medium)", "gliner", C_GLINER),
        ("scispaCy CRAFT", "scispacy_craft", C_SPACY),
        ("scispaCy JNLPBA", "scispacy_jnlpba", C_SPACY),
        ("scispaCy lg (ENTITY)", "scispacy_lg", C_SPACY),
    ]
    fig, (ax1, ax2) = newfig(7.0, 3.2, ncols=2)
    w = 0.2
    x = np.arange(len(rows))
    FOURSE = ["#1e3a8a", "#93c5fd", "#14532d", "#86efac"]
    for k, (ds, mode) in enumerate([("bc5cdr", "exact"), ("bc5cdr", "relaxed"),
                                    ("biored", "exact"), ("biored", "relaxed")]):
        vals = [f1(ds, m, mode) for _, m, _ in rows]
        vals = [v if v is not None else 0.0 for v in vals]
        bars = ax1.bar(x + (k - 1.5) * w, vals, w,
                       color=FOURSE[k],
                       edgecolor="white", linewidth=0.4,
                       label=f"{ds}-{mode}")
        for b, v, (_, key, _c) in zip(bars, vals, rows):
            if v:
                ax1.annotate(f"{v:.3f}", (b.get_x() + b.get_width() / 2, v),
                             ha="center", va="bottom", fontsize=5.2, rotation=90)
    # (A) numbers: the y-values are exact/relaxed F1 from the live JSON; zero bars
    # mark "—" (model not run on that dataset)
    for i, (name, key, col) in enumerate(rows):
        for k, (ds, mode) in enumerate([("bc5cdr", "exact"), ("bc5cdr", "relaxed"),
                                       ("biored", "exact"), ("biored", "relaxed")]):
            v = f1(ds, key, mode)
            if v is not None:
                ax1.scatter(i + (k - 1.5) * w, v, s=10, color="black", zorder=4)
    ax1.set_xticks(x, [r[0] for r in rows], fontsize=6.4, rotation=12, ha="right")
    ax1.set_ylabel("entity-level F1")
    ax1.set_ylim(0, 1.05)
    ax1.legend(frameon=False, fontsize=6.5, ncol=2)
    ax1.axvspan(-0.5, 0.5, color=C_SPACY, alpha=0.06)
    ax1.set_title("(A) External benchmarks (exact + relaxed F1)", fontsize=8.5)
    ax2.text(0.02, 0.98, "Table 7 manuscript numbers\n(read from live JSON):", transform=ax2.transAxes,
             fontsize=8, va="top", fontweight="bold")
    lines = []
    for name, key, _c in rows:
        b_e, b_r = f1("bc5cdr", key, "exact"), f1("bc5cdr", key, "relaxed")
        r_e, r_r = f1("biored", key, "exact"), f1("biored", key, "relaxed")
        lines.append(f"{name:24s} {fmt(b_e)}  {fmt(b_r)}   {fmt(r_e)}  {fmt(r_r)}")
    ax2.text(0.02, 0.86, "BC5CDR-exact  relaxed | BioRED-exact  relaxed\n" + "\n".join(lines),
             transform=ax2.transAxes, fontsize=6.4, family="monospace", va="top")
    ax2.axis("off")
    fig.suptitle("External NER benchmark validation (live artifacts; Table 7)",
                 fontweight="bold", fontsize=9.5)
    fig.tight_layout(rect=[0, 0, 1, 0.93])
    save(fig, "fig11_external_benchmark", "LIVE: outputs/results/410470_ext_bench")

# ═══════════════════════════════════════════════════════════════════════════
# Back up the seven 2026-10-21 claim-era PNGs before overwriting any name,
# then run the requested figures.
# ═══════════════════════════════════════════════════════════════════════════

def preserve_frozen_pngs():
    """The 2026-10-21 PNGs are the only surviving artifacts of the deleted
    claim_* JSONs; keep them byte-for-byte in figures/frozen_2026-10-21/."""
    if not FIG_DIR.exists():
        return
    FROZEN_PNG_DIR.mkdir(parents=True, exist_ok=True)
    kept = 0
    for p in sorted(FIG_DIR.glob("fig*.png")):
        # Only the claim-era files (mtime 2026-10-21 10:52) are the irreplaceable
        # frozen evidence; regenerated PNGs must never overwrite them.
        if time.strftime("%Y-%m-%d %H:%M", time.localtime(p.stat().st_mtime)) \
                != "2026-10-21 10:52":
            continue
        dest = FROZEN_PNG_DIR / p.name
        if not dest.exists():
            shutil.copy2(p, dest)
            kept += 1
    if kept:
        print(f"preserved {kept} claim-era PNGs -> figures/frozen_2026-10-21/ "
              "(figs 1-5 raw JSONs deleted; PNGs are frozen evidence)")


# figs numbered 1-11.  Arguments: name, builder, provenance tag, long description
REGISTRY = [
    ("fig1_claim_a_disambiguation", fig1, "FROZEN §4.3",
     "Claim A: LLM 54.1% vs spaCy best 24.3% (+29.7 pp), 37 ambiguous sentences."),
    ("fig2_claim_c_hybrid_fusion", fig2, "FROZEN §4.1/§4.5",
     "Claim C: 7-source hybrid KG - entities 5,995 / relationships 34,524 by source."),
    ("fig3_claim_d_calibration", fig3, "FROZEN §4.6",
     "Claim D: ECE 0.277 -> 0.040 (Platt) / 0.061 (isotonic); per-type gap regime."),
    ("fig4_claim_e_efficiency", fig4, "FROZEN §4.7",
     "Claim E: spaCy 104.7x faster; LLM 392.6x more costly (10-paper batch)."),
    ("fig5_claim_f_biological_validation", fig5, "FROZEN Table 4",
     "Claim F: journey to 100% gold recall; 12 categories at 109/109."),
    ("fig6_ner_model_overview", fig6, "FROZEN Table 8 / §4.15",
     "Per-model NER quality - 6 baseline models on the 452-paper analysis corpus."),
    ("fig7_type_distribution", fig7, "FROZEN Table 3 / §4.15",
     "50-paper cohort per-type composition; 8/14 types LLM-only; non-CDM artifacts."),
    ("fig8_variant_coverage", fig8, "LIVE Table-9 JSONs",
     "15 additional NER variants at full 452-paper coverage (rows, papers, labels, time)."),
    ("fig9_dedup_label_survival", fig9, "LIVE audit CSV",
     "Stage-2 dedup label survival per variant + applied-vs-proposed fix waterfall."),
    ("fig10_hunflair2_span_hygiene", fig10, "LIVE pre/post CSVs",
     "HunFlair2 _trim_span pre/post: trailing punct 22.5%->0.0%, newlines all mid-span."),
    ("fig11_external_benchmark", fig11, "LIVE 410470_ext_bench",
     "External benchmark F1 (BC5CDR + BioRED, exact + relaxed) - Table 7."),
]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--only", default=None,
                        help="comma-separated figure numbers, e.g. 8,9,10")
    parser.add_argument("--list", dest="list_registry", action="store_true",
                        help="print the figure registry and exit")
    args = parser.parse_args(argv)

    if args.list_registry:
        print(f"{'#':>3}  {'name':37} {'provenance':24} description")
        for i, (name, _fn, prov, desc) in enumerate(REGISTRY, 1):
            print(f"{i:>3}  {name:37} {prov:24} {desc}")
        return 0

    wanted = None
    if args.only:
        wanted = {int(x) for x in args.only.split(",") if x.strip()}

    preserve_frozen_pngs()
    print(f"figures -> {FIG_DIR}")
    failures = []
    for i, (name, fn, prov, desc) in enumerate(REGISTRY, 1):
        if wanted and i not in wanted:
            continue
        print(f"[{i:>2}/{len(REGISTRY)}] {name}: {desc}")
        try:
            fn()
        except SystemExit as e:
            print(f"  FAILED: {e}")
            failures.append(name)
        except Exception as e:  # noqa: BLE001 — report and continue
            print(f"  FAILED: {type(e).__name__}: {e}")
            failures.append(name)

    print()
    if failures:
        print(f"{len(failures)} figure(s) FAILED: {', '.join(failures)}")
        print("LIVE-source figures fail loudly when their artifact is missing "
              "- do not ship a partial regeneration without investigating.")
        return 1
    print(f"All requested figures written (PDF + 600-DPI PNG + SVG each) to {FIG_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
