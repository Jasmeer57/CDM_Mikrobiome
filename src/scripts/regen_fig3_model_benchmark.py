#!/usr/bin/env python3
"""Regenerate fig3_model_benchmark.png (Fig 5 / fig:ner-overview) for the manuscript.

Four panels from the caption (manuscript.tex ~line 772):
  (A) CDM type coverage: Qwen and GLiNER variants cover all 14; PubMedBERT 1; spaCy & PubTator3 6.
  (B) Artifact rate: pending rerun (placeholder).
  (C) Generic ENTITY label rate: only spaCy produces generic labels (79.1%).
  (D) Unique entity counts (log scale): spaCy highest, PubTator3 lowest.

Data source: paper/manuscript/numbers.json (per_model_quality key, single source of truth)
Run from repo root: python src/scripts/regen_fig3_model_benchmark.py
"""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import seaborn as sns

sns.set_theme(style="whitegrid", font_scale=1.1)

REPO = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
FIG_DIR = REPO / "paper" / "manuscript" / "figures"
NUMBERS_FILE = REPO / "paper" / "manuscript" / "numbers.json"

# ── Color palette (matches generate_figures.py) ──
C_LLM = "#2563eb"
C_SPACY = "#64748b"
C_NLP = "#d97706"
C_BIOMED = "#f59e0b"
C_PUBMED = "#ef4444"
C_PUBTATOR = "#8b5cf6"

# Model order + display labels + keys in numbers.json per_model_quality.models
MODELS = [
    ("Qwen 3.5:9b", "Qwen", C_LLM, 14),
    ("sciSpaCy (4 combined)", "sciSpaCy", C_SPACY, 6),
    ("GLiNER (medium)", "GLiNER", C_NLP, 14),
    ("GLiNER-BioMed", "GLiNER-BioMed", C_BIOMED, 14),
    ("PubMedBERT", "PubMedBERT", C_PUBMED, 1),
    ("PubTator3", "PubTator3", C_PUBTATOR, 6),
]


def main():
    nb = json.loads(NUMBERS_FILE.read_text())
    d = nb["per_model_quality"]["models"]
    labels = [m[1] for m in MODELS]
    colors = [m[2] for m in MODELS]
    keys = [m[0] for m in MODELS]
    type_cov = [m[3] for m in MODELS]
    unique = [d[k]["unique"] for k in keys]
    generic = [d[k].get("generic_pct", 0.0) for k in keys]

    fig = plt.figure(figsize=(16, 6))
    gs = fig.add_gridspec(1, 3, hspace=0.35, wspace=0.3)

    # ── Panel A: CDM type coverage ──
    ax1 = fig.add_subplot(gs[0, 0])
    bars = ax1.barh(np.arange(len(labels)), type_cov, color=colors, edgecolor="white", height=0.6)
    for bar, v in zip(bars, type_cov):
        ax1.text(bar.get_width() + 0.2, bar.get_y() + bar.get_height() / 2,
                 f"{v}/14", va="center", fontsize=11, fontweight="bold")
    ax1.set_yticks(np.arange(len(labels)))
    ax1.set_yticklabels(labels, fontsize=11)
    ax1.set_xlabel("CDM types covered (out of 14)")
    ax1.set_title("(A) CDM type coverage", fontsize=13, fontweight="bold")
    ax1.invert_yaxis()
    ax1.set_xlim(0, 16)
    ax1.axvline(x=14, color="#dc2626", linestyle="--", alpha=0.4, linewidth=1)

    # ── Panel B: Generic ENTITY label rate ──
    ax3 = fig.add_subplot(gs[0, 1])
    bars = ax3.bar(np.arange(len(labels)), generic, color=colors, edgecolor="white", width=0.6)
    for bar, v in zip(bars, generic):
        if v > 0:
            ax3.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1.5,
                     f"{v:.1f}%", ha="center", va="bottom", fontsize=11, fontweight="bold")
        else:
            ax3.text(bar.get_x() + bar.get_width() / 2, 1.0,
                     "0%", ha="center", va="bottom", fontsize=10, color="#9ca3af")
    ax3.set_xticks(np.arange(len(labels)))
    ax3.set_xticklabels(labels, rotation=30, ha="right", fontsize=10)
    ax3.set_ylabel("% entities with generic ENTITY label")
    ax3.set_title("(B) Generic ENTITY label rate", fontsize=13, fontweight="bold")
    ax3.set_ylim(0, max(generic) * 1.2 if max(generic) > 0 else 1)

    # ── Panel C: Unique entity counts (log scale) ──
    ax4 = fig.add_subplot(gs[0, 2])
    bars = ax4.bar(np.arange(len(labels)), unique, color=colors, edgecolor="white", width=0.6)
    for bar, v in zip(bars, unique):
        ax4.text(bar.get_x() + bar.get_width() / 2, v * 1.05,
                 f"{v:,}", ha="center", va="bottom", fontsize=10, fontweight="bold", rotation=0)
    ax4.set_xticks(np.arange(len(labels)))
    ax4.set_xticklabels(labels, rotation=30, ha="right", fontsize=10)
    ax4.set_yscale("log")
    ax4.set_ylabel("Unique entities (log scale)")
    ax4.set_title("(C) Unique entity counts (log scale)", fontsize=13, fontweight="bold")
    ax4.set_ylim(min(unique) * 0.3, max(unique) * 3)

    fig.suptitle("Per-model NER quality benchmark on the full 444-paper corpus",
                 fontsize=15, fontweight="bold", y=0.98)
    fig.savefig(FIG_DIR / "fig3_model_benchmark.png", dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"  wrote {FIG_DIR / 'fig3_model_benchmark.png'}")


if __name__ == "__main__":
    main()
