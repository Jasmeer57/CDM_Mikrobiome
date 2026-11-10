#!/usr/bin/env python3
"""Regenerate Fig 4 (leave-K-out) from leave_k_out_results.json.

Reads:  paper_claims/claim_C_hybrid_fusion/results_v2/leave_k_out_results.json
Writes: paper/manuscript/figures/fig5_leave_k_out.png
"""
import json
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pathlib import Path

REPO = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
DATA = REPO / "paper_claims" / "claim_C_hybrid_fusion" / "results_v2" / "leave_k_out_results.json"
OUT = REPO / "paper" / "manuscript" / "figures" / "fig5_leave_k_out.png"

with open(DATA) as f:
    data = json.load(f)

ks = sorted(data.keys(), key=float)
k_labels = [f"{int(float(k)*100)}%" for k in ks]
full_recalls = [data[k]["mean_recall_full"] * 100 for k in ks]
entity_recalls = [data[k]["mean_recall_entity"] * 100 for k in ks]

# Per-seed full recalls for error bars
full_stds = []
for k in ks:
    seed_recalls = [s["recall_full"] * 100 for s in data[k]["seed_recalls"]]
    import statistics
    full_stds.append(statistics.stdev(seed_recalls) if len(seed_recalls) > 1 else 0)

fig, ax = plt.subplots(figsize=(7, 5))

x = range(len(ks))
width = 0.35

bars1 = ax.bar([i - width/2 for i in x], full_recalls, width, yerr=full_stds,
               label="Relation recall (full triple)", color="#4C72B0",
               capsize=5, edgecolor="white", linewidth=0.8)
bars2 = ax.bar([i + width/2 for i in x], entity_recalls, width,
               label="Entity recall", color="#55A868",
               edgecolor="white", linewidth=0.8)

# Value labels
for bar, val in zip(bars1, full_recalls):
    ax.text(bar.get_x() + bar.get_width()/2, val + 1, f"{val:.1f}%",
            ha="center", va="bottom", fontsize=10, fontweight="bold")
for bar, val in zip(bars2, entity_recalls):
    ax.text(bar.get_x() + bar.get_width()/2, val + 1, f"{val:.1f}%",
            ha="center", va="bottom", fontsize=10, fontweight="bold")

ax.set_xlabel("Held-out fraction $K$", fontsize=12)
ax.set_ylabel("Recall (%)", fontsize=12)
ax.set_title("Leave-K-out Validation (mean of 3 seeds)", fontsize=13)
ax.set_xticks(x)
ax.set_xticklabels(k_labels)
ax.set_ylim(0, 115)
ax.legend(loc="upper center", fontsize=11)
ax.spines["top"].set_visible(False)
ax.spines["right"].set_visible(False)

plt.tight_layout()
fig.savefig(OUT, dpi=300, bbox_inches="tight")
print(f"Saved: {OUT}")
print(f"Full recalls: {dict(zip(k_labels, [f'{r:.1f}%' for r in full_recalls]))}")
print(f"Entity recalls: {dict(zip(k_labels, [f'{r:.1f}%' for r in entity_recalls]))}")
