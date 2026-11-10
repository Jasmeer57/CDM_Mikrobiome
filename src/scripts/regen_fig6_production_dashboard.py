#!/usr/bin/env python3
"""Regenerate Fig 6 (production dashboard) from v2.1.1-clean DB.

Reads:  releases/v2.1.1-clean/microbiome_cdm.db
Writes: paper/manuscript/figures/fig6_production_dashboard.png
"""
import sqlite3
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import numpy as np
from pathlib import Path

REPO = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
DB = REPO / "releases" / "v2.1.1-clean" / "microbiome_cdm.db"
OUT = REPO / "paper" / "manuscript" / "figures" / "fig6_production_dashboard.png"

conn = sqlite3.connect(str(DB))
cur = conn.cursor()

# Entity counts by type
cur.execute("SELECT entity_type, COUNT(*) FROM entities WHERE entity_type IS NOT NULL GROUP BY entity_type ORDER BY COUNT(*) DESC")
type_counts = cur.fetchall()

# UMLS mapping rate
cur.execute("SELECT COUNT(*) FROM entities")
total_entities = cur.fetchone()[0]
cur.execute("""SELECT COUNT(DISTINCT e.id) FROM entities e 
               WHERE EXISTS (SELECT 1 FROM controlled_vocabularies cv 
               WHERE cv.entity_id = e.id AND cv.vocabulary_name = 'UMLS')""")
umls_mapped = cur.fetchone()[0]
umls_pct = umls_mapped / total_entities * 100

# Relationship breakdown (by source_type, matching manuscript numbers.json:
# typed-core = 21,514 = llm_extracted 20,827 + llm_triple 488 + kb 199;
# co-occurrence = 33,274 = source_type='co_occurrence')
cur.execute("SELECT COUNT(*) FROM relationships WHERE source_type != 'co_occurrence'")
typed_core = cur.fetchone()[0]
cur.execute("SELECT COUNT(*) FROM relationships WHERE source_type = 'co_occurrence'")
co_occurrence = cur.fetchone()[0]
total_rels = typed_core + co_occurrence

# Vocabulary mappings by ontology (top 10)
cur.execute("SELECT vocabulary_name, COUNT(*) FROM controlled_vocabularies GROUP BY vocabulary_name ORDER BY COUNT(*) DESC LIMIT 10")
vocab_counts = cur.fetchall()

# Top relationship types (excluding CO_OCCURS_WITH)
cur.execute("""SELECT relationship_type, COUNT(*) FROM relationships 
               WHERE relationship_type != 'CO_OCCURS_WITH' 
               GROUP BY relationship_type ORDER BY COUNT(*) DESC LIMIT 10""")
rel_counts = cur.fetchall()

# Projects and mentions
cur.execute("SELECT COUNT(DISTINCT project_id) FROM entity_project_mentions")
n_projects = cur.fetchone()[0]
cur.execute("SELECT COUNT(*) FROM entity_project_mentions")
n_mentions = cur.fetchone()[0]

conn.close()

# --- Build figure ---
fig = plt.figure(figsize=(14, 10))
gs = gridspec.GridSpec(2, 3, hspace=0.35, wspace=0.4)

# Panel A: Entity counts by type (horizontal bar)
ax1 = fig.add_subplot(gs[0, :2])
types = [t[0] for t in type_counts]
counts = [t[1] for t in type_counts]
colors = plt.cm.Set3(np.linspace(0, 1, len(types)))
bars = ax1.barh(types, counts, color=colors, edgecolor="white", linewidth=0.5)
ax1.set_xlabel("Entity count", fontsize=11)
ax1.set_title(f"A. Entities by CDM type (n={total_entities:,})", fontsize=12, fontweight="bold")
ax1.invert_yaxis()
for bar, cnt in zip(bars, counts):
    ax1.text(bar.get_width() + 50, bar.get_y() + bar.get_height()/2, f"{cnt:,}",
             va="center", fontsize=9)
ax1.spines["top"].set_visible(False)
ax1.spines["right"].set_visible(False)

# Panel B: UMLS mapping donut (show mapped% and unmapped% on the two wedges)
ax2 = fig.add_subplot(gs[0, 2])
mapped = umls_mapped
unmapped = total_entities - umls_mapped
unmapped_pct = 100.0 - umls_pct


def _b_autopct(pct):
    # pct is the wedge fraction; return the right label for each segment
    return f"{umls_pct:.1f}%" if pct >= 50 else f"{unmapped_pct:.1f}%"


ax2.pie([mapped, unmapped], labels=["UMLS-mapped", "Unmapped"],
        colors=["#55A868", "#E0E0E0"], autopct=_b_autopct,
        startangle=90, wedgeprops=dict(width=0.4), textprops=dict(fontsize=10))
ax2.set_title(f"B. UMLS mapping (n={total_entities:,})", fontsize=12, fontweight="bold")

# Panel C: Relationship breakdown
ax3 = fig.add_subplot(gs[1, 0])
ax3.bar(["Typed core", "Co-occurrence"], [typed_core, co_occurrence],
        color=["#4C72B0", "#DD8452"], edgecolor="white", linewidth=0.8)
ax3.set_ylabel("Edge count", fontsize=11)
ax3.set_title(f"C. Relationships (n={total_rels:,})", fontsize=12, fontweight="bold")
for i, v in enumerate([typed_core, co_occurrence]):
    ax3.text(i, v + 500, f"{v:,}", ha="center", fontsize=10, fontweight="bold")
ax3.spines["top"].set_visible(False)
ax3.spines["right"].set_visible(False)

# Panel D: Vocabulary mappings by ontology (top 10)
ax4 = fig.add_subplot(gs[1, 1])
vocabs = [v[0] for v in vocab_counts]
vcounts = [v[1] for v in vocab_counts]
ax4.barh(vocabs, vcounts, color=plt.cm.Pastel1(np.linspace(0, 1, len(vocabs))), edgecolor="white")
ax4.set_xlabel("Mapping count", fontsize=11)
ax4.set_title("D. Vocab. mappings (top 10)", fontsize=12, fontweight="bold")
ax4.invert_yaxis()
ax4.spines["top"].set_visible(False)
ax4.spines["right"].set_visible(False)

# Panel E: Top typed relationship types
ax5 = fig.add_subplot(gs[1, 2])
rtypes = [r[0] for r in rel_counts]
rcounts = [r[1] for r in rel_counts]
ax5.barh(rtypes, rcounts, color=plt.cm.Set2(np.linspace(0, 1, len(rtypes))), edgecolor="white")
ax5.set_xlabel("Edge count", fontsize=11)
ax5.set_title("E. Top typed relations", fontsize=12, fontweight="bold")
ax5.invert_yaxis()
ax5.spines["top"].set_visible(False)
ax5.spines["right"].set_visible(False)

fig.suptitle(f"Production CDM DB — v2.1.1-clean ({n_projects} papers, {total_entities:,} entities, {total_rels:,} relationships)",
             fontsize=14, fontweight="bold", y=0.98)

fig.savefig(OUT, dpi=300, bbox_inches="tight")
print(f"Saved: {OUT}")
print(f"Total entities: {total_entities:,}")
print(f"UMLS mapped: {umls_mapped:,} ({umls_pct:.1f}%)")
print(f"Typed core edges: {typed_core:,}, Co-occurrence: {co_occurrence:,}")
print(f"Projects: {n_projects}, EPM rows: {n_mentions:,}")
