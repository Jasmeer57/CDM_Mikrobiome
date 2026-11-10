#!/usr/bin/env python3
"""Generate Table 10 (top candidate associations) from the production DB.

Filters generic non-biological terms via a stoplist, sorts by cross-paper
support (co_occurrence_count), and emits LaTeX rows.

Usage: python src/scripts/gen_table10_candidates.py [--top N] [--csv PATH]
"""

import argparse
import csv
import os
import sqlite3
import sys

DB_PATH = os.path.join(
    os.path.dirname(__file__), "..", "releases", "v2.1.1-clean", "microbiome_cdm.db"
)

STOPLIST = {
    "development",
    "cells",
    "microbes",
    "microbe",
    "concentrations",
    "concentration",
    "levels",
    "level",
    "expression",
    "protein",
    "proteins",
    "metabolism",
    "treatment",
    "treatments",
    "clinical",
    "supplementation",
    "supplement",
    "human",
    "humans",
    "study",
    "studies",
    "analysis",
    "method",
    "methods",
    "associated",
    "pathway",
    "pathways",
    "disease",
    "diseases",
    "health",
    "healthy",
    "healthy controls",
    "healthy subjects",
    "patients",
    "subject",
    "subjects",
    "sample",
    "samples",
    "data",
    "results",
    "findings",
    "role",
    "function",
    "functions",
    "activity",
    "activities",
    "effect",
    "effects",
    "change",
    "changes",
    "increase",
    "increases",
    "decrease",
    "decreases",
    "gut microbes",
    "sion",
}

GENERIC_PREDICATES = {"CO_OCCURS_WITH", "ASSOCIATED_WITH"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--csv", type=str, default=None)
    ap.add_argument("--db", type=str, default=DB_PATH)
    args = ap.parse_args()

    db = sqlite3.connect(args.db)
    cur = db.cursor()

    cur.execute(
        """
        SELECT r.relationship_type,
               e1.term, e1.entity_type,
               e2.term, e2.entity_type,
               r.co_occurrence_count,
               r.confidence,
               r.source_type
        FROM relationships r
        JOIN entities e1 ON r.source_id = e1.id
        JOIN entities e2 ON r.target_id = e2.id
        WHERE r.relationship_type NOT IN ('CO_OCCURS_WITH', 'ASSOCIATED_WITH')
          AND r.confidence >= 0.5
        ORDER BY r.co_occurrence_count DESC
        """
    )

    rows = []
    for r in cur.fetchall():
        rel, s_term, s_type, o_term, o_type, n_papers, conf, src = r
        s_low = s_term.strip().lower()
        o_low = o_term.strip().lower()
        if s_low in STOPLIST or o_low in STOPLIST:
            continue
        rows.append(r)

    top = rows[: args.top]

    print(f"# Top {len(top)} candidate associations (after stoplist filter)")
    print(f"# Total candidates (non-generic, conf>=0.5): {len(rows)} (after stoplist)")
    print(f"# DB path: {args.db}")
    print()
    print(r"#\textbf & Subject & Relation & Object & n\_papers \\")
    print(r"\midrule")
    for i, r in enumerate(top, 1):
        rel, s_term, s_type, o_term, o_type, n_papers, conf, src = r
        s_disp = _ital(s_term, s_type)
        o_disp = _ital(o_term, o_type)
        print(
            f"{i} & {s_disp} & {rel.replace('_', chr(92) + '_')} & {o_disp} & {n_papers} \\\\"
        )

    if args.csv:
        with open(args.csv, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(
                ["rank", "subject", "subject_type", "relation",
                 "object", "object_type", "n_papers", "confidence", "source"]
            )
            for i, r in enumerate(top, 1):
                w.writerow([i, *r])
        print(f"\nCSV written to {args.csv}", file=sys.stderr)

    db.close()


def _ital(term, etype):
    """Italicize binomial species names (Genus species)."""
    parts = term.strip().split()
    if len(parts) >= 2 and parts[0][0].isupper() and parts[1][0].islower():
        return r"\textit{" + term + "}"
    return term


if __name__ == "__main__":
    main()
