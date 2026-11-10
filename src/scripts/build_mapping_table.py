#!/usr/bin/env python3
"""Generate the ontology mapping table for the manuscript from a release DB.

Produces per-entity-type mapping rates for UMLS, OLS, and Bioportal,
plus a vocabulary-name breakdown and overall coverage stats.

All numbers are emitted with their SQL so every figure is reproducible.

Usage:
    python src/scripts/build_mapping_table.py \
        --db releases/v2.1.1-clean/microbiome_cdm.db \
        --out paper/manuscript/tables/mapping_table.tex
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    p.add_argument("--db", required=True, help="Path to the CDM SQLite database")
    p.add_argument("--out", required=True, help="Output .tex file path")
    args = p.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"ERROR: database not found: {db_path}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(str(db_path))
    c = conn.cursor()

    # ── Per-type mapping counts ────────────────────────────────────────────
    sql = """
        SELECT entity_type,
               COUNT(*) AS total,
               SUM(CASE WHEN UMLS_ID  IS NOT NULL AND UMLS_ID  != '' THEN 1 ELSE 0 END) AS umls,
               SUM(CASE WHEN OLS      IS NOT NULL AND OLS      != '' THEN 1 ELSE 0 END) AS ols,
               SUM(CASE WHEN Bioportal IS NOT NULL AND Bioportal != '' THEN 1 ELSE 0 END) AS bio
        FROM entities
        GROUP BY entity_type
        ORDER BY COUNT(*) DESC
    """
    c.execute(sql)
    rows = c.fetchall()

    # ── Totals ─────────────────────────────────────────────────────────────
    t_total = sum(r[1] for r in rows)
    t_umls  = sum(r[2] for r in rows)
    t_ols   = sum(r[3] for r in rows)
    t_bio   = sum(r[4] for r in rows)

    # ── Vocabulary breakdown ──────────────────────────────────────────────
    c.execute(
        "SELECT vocabulary_name, COUNT(*) FROM controlled_vocabularies "
        "GROUP BY 1 ORDER BY 2 DESC"
    )
    vocab_rows = c.fetchall()
    c.execute("SELECT COUNT(*) FROM controlled_vocabularies")
    cv_total = c.fetchone()[0]
    c.execute("SELECT COUNT(DISTINCT entity_id) FROM controlled_vocabularies")
    any_vocab = c.fetchone()[0]

    conn.close()

    # ── Write LaTeX table ─────────────────────────────────────────────────
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    lines = []
    lines.append(r"\begin{table}[h]")
    lines.append(r"\centering")
    lines.append(r"\small")
    lines.append(
        r"\caption{Ontology mapping rate by CDM entity type in the production DB "
        r"(" + f"{t_total:,}" + r" entities). "
        r"UMLS: " + f"{t_umls:,} ({100*t_umls/t_total:.1f}\%)" + r", "
        r"OLS: " + f"{t_ols:,} ({100*t_ols/t_total:.1f}\%)" + r", "
        r"BioPortal: " + f"{t_bio:,} ({100*t_bio/t_total:.1f}\%)" + r". "
        r"Any-vocabulary: " + f"{any_vocab:,} ({100*any_vocab/t_total:.1f}\%)" + r"}"
    )
    lines.append(r"\label{tab:ontology-mapping}")
    lines.append(r"\begin{tabular}{lrrrrrr}")
    lines.append(r"\toprule")
    lines.append(
        r"\textbf{Entity type} & \textbf{Entities} "
        r"& \textbf{UMLS} & \textbf{UMLS\%} "
        r"& \textbf{OLS} & \textbf{OLS\%} "
        r"& \textbf{BioP.} \\"
    )
    lines.append(r"\midrule")

    for etype, total, umls, ols, bio in rows:
        etype_latex = etype.replace("_", r"\_")
        lines.append(
            f"{etype_latex} & {total:,} & {umls:,} & {100*umls/total:.1f}\\% "
            f"& {ols:,} & {100*ols/total:.1f}\\% & {bio:,} \\\\"
        )

    lines.append(r"\midrule")
    lines.append(
        rf"\textbf{{Total}} & \textbf{{{t_total:,}}} "
        rf"& \textbf{{{t_umls:,}}} & \textbf{{{100*t_umls/t_total:.1f}\%}} "
        rf"& \textbf{{{t_ols:,}}} & \textbf{{{100*t_ols/t_total:.1f}\%}} "
        rf"& \textbf{{{t_bio:,}}} \\"
    )
    lines.append(r"\bottomrule")
    lines.append(r"\end{tabular}")
    lines.append(r"\end{table}")

    out_path.write_text("\n".join(lines) + "\n")
    print(f"Wrote {out_path}")

    # ── Also print a plain-text summary to stdout ──────────────────────────
    print()
    print(f"{'Type':<20} {'Total':>7} {'UMLS':>7} {'UMLS%':>7} {'OLS':>7} {'OLS%':>7} {'Bio':>7} {'Bio%':>7}")
    print("-" * 80)
    for etype, total, umls, ols, bio in rows:
        print(f"{etype:<20} {total:>7} {umls:>7} {100*umls/total:>6.1f}% {ols:>7} {100*ols/total:>6.1f}% {bio:>7} {100*bio/total:>6.1f}%")
    print("-" * 80)
    print(f"{'Total':<20} {t_total:>7} {t_umls:>7} {100*t_umls/t_total:>6.1f}% {t_ols:>7} {100*t_ols/t_total:>6.1f}% {t_bio:>7} {100*t_bio/t_total:>6.1f}%")
    print()
    print(f"Any-vocabulary (controlled_vocabularies): {any_vocab:,} ({100*any_vocab/t_total:.1f}%)")
    print(f"Total cv rows: {cv_total:,}")
    print(f"Distinct vocabularies: {len(vocab_rows)}")
    print()
    print("Vocabulary breakdown:")
    for name, cnt in vocab_rows:
        print(f"  {name:<30} {cnt:>8}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
