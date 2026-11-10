#!/usr/bin/env python3
"""Evidence grounding analysis for v2.1 typed edges (v2 — paper lookup via mentions).

For each typed (non-co-occurrence) edge with evidence text, we:
  1. Find papers where BOTH subject and object entities are mentioned
     (intersection of entity_project_mentions.project_id).
  2. Load each such paper's text from data/papers_txt/.
  3. Check at THREE levels:
     Tier 1 (SENTENCE): The evidence text appears verbatim as a substring
             in at least one common paper.
     Tier 2 (PAPER):    Both entity terms appear (case-insensitive substring)
             in the same paper, but the evidence text does NOT appear verbatim.
     Tier 3 (NONE):     Neither condition met — at least one entity term is
             not found in any common paper via substring.

This replaces the ad-hoc analysis. Results are reproducible from this script.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

REPO = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
DB_PATH = REPO / "releases" / "v2.1-full-multiner" / "microbiome_cdm.db"
PAPERS_DIR = REPO / "data/papers_txt"


def load_paper_text(project_id: str, cache: dict[str, str]) -> str:
    if project_id in cache:
        return cache[project_id]
    p = PAPERS_DIR / f"{project_id}.txt"
    if p.exists():
        text = p.read_text(encoding="utf-8", errors="replace")
        cache[project_id] = text
        return text
    cache[project_id] = ""
    return ""


def main():
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row

    edges = db.execute("""
        SELECT r.id, r.source_type, r.evidence, r.relationship_type,
               r.source_id, r.target_id,
               s.term as subject_term, o.term as object_term
        FROM relationships r
        JOIN entities s ON r.source_id = s.id
        JOIN entities o ON r.target_id = o.id
        WHERE r.source_type != 'co_occurrence'
          AND r.evidence IS NOT NULL AND r.evidence != ''
    """).fetchall()

    total_typed = db.execute(
        "SELECT COUNT(*) FROM relationships WHERE source_type != 'co_occurrence'"
    ).fetchone()[0]
    total_with_ev = len(edges)
    total_without_ev = total_typed - total_with_ev

    print(f"Total typed edges: {total_typed}")
    print(f"  With evidence text: {total_with_ev}")
    print(f"  Without evidence text: {total_without_ev}")
    print()

    paper_cache: dict[str, str] = {}
    tier1_examples: list[dict] = []
    tier2_examples: list[dict] = []
    tier3_examples: list[dict] = []

    tier1_count = 0
    tier2_count = 0
    tier3_count = 0
    no_common_papers = 0

    for i, edge in enumerate(edges):
        if i % 2000 == 0:
            print(f"  Processing edge {i}/{total_with_ev}...", file=sys.stderr)

        evidence = edge["evidence"]
        subj = edge["subject_term"]
        obj = edge["object_term"]

        # Find common papers via entity_project_mentions
        subj_papers = set(
            row[0] for row in db.execute(
                "SELECT DISTINCT project_id FROM entity_project_mentions WHERE entity_id = ?",
                (edge["source_id"],)
            )
        )
        obj_papers = set(
            row[0] for row in db.execute(
                "SELECT DISTINCT project_id FROM entity_project_mentions WHERE entity_id = ?",
                (edge["target_id"],)
            )
        )
        common = subj_papers & obj_papers

        if not common:
            no_common_papers += 1
            tier3_count += 1
            if len(tier3_examples) < 20:
                tier3_examples.append({
                    "subject": subj, "object": obj,
                    "relation": edge["relationship_type"],
                    "source_type": edge["source_type"],
                    "evidence": evidence[:200],
                    "reason": "no common papers",
                    "subj_papers": len(subj_papers),
                    "obj_papers": len(obj_papers),
                })
            continue

        found_verbatim = False
        found_terms = False
        paper_hit = ""

        for pid in common:
            text = load_paper_text(pid, paper_cache)
            if not text:
                continue

            if not found_verbatim and evidence in text:
                found_verbatim = True
                paper_hit = pid
                break

            if not found_terms:
                text_lower = text.lower()
                if subj.lower() in text_lower and obj.lower() in text_lower:
                    found_terms = True

        if found_verbatim:
            tier1_count += 1
            if len(tier1_examples) < 15:
                tier1_examples.append({
                    "subject": subj, "object": obj,
                    "relation": edge["relationship_type"],
                    "source_type": edge["source_type"],
                    "evidence": evidence[:200],
                    "paper": paper_hit,
                    "n_common_papers": len(common),
                })
        elif found_terms:
            tier2_count += 1
            if len(tier2_examples) < 15:
                tier2_examples.append({
                    "subject": subj, "object": obj,
                    "relation": edge["relationship_type"],
                    "source_type": edge["source_type"],
                    "evidence": evidence[:200],
                    "n_common_papers": len(common),
                })
        else:
            tier3_count += 1
            if len(tier3_examples) < 20:
                tier3_examples.append({
                    "subject": subj, "object": obj,
                    "relation": edge["relationship_type"],
                    "source_type": edge["source_type"],
                    "evidence": evidence[:200],
                    "n_common_papers": len(common),
                    "common_papers": list(common)[:3],
                })

    print("=" * 60)
    print("RESULTS")
    print("=" * 60)
    print(f"Total typed edges with evidence: {total_with_ev}")
    print(f"  Tier 1 (verbatim sentence match):  {tier1_count:6d} ({tier1_count/total_with_ev*100:.1f}%)")
    print(f"  Tier 2 (both terms in same paper): {tier2_count:6d} ({tier2_count/total_with_ev*100:.1f}%)")
    print(f"  Tier 3 (no term match found):      {tier3_count:6d} ({tier3_count/total_with_ev*100:.1f}%)")
    print(f"    (of which no common papers:      {no_common_papers:6d})")
    print(f"  Grounded (Tier 1+2):               {tier1_count + tier2_count:6d} ({(tier1_count+tier2_count)/total_with_ev*100:.1f}%)")
    print()

    # Breakdown by source_type
    print("By source_type:")
    for st in ["llm_extracted", "llm_triple", "kb"]:
        st_total = db.execute(
            "SELECT COUNT(*) FROM relationships WHERE source_type = ? AND evidence IS NOT NULL AND evidence != ''", (st,)
        ).fetchone()[0]
        print(f"  {st:20s} total_with_ev={st_total}")

    print()
    print("TIER 1 EXAMPLES (verbatim match):")
    for ex in tier1_examples:
        print(f"  [{ex['source_type']}] {ex['subject']} {ex['relation']} {ex['object']}")
        print(f"    paper={ex['paper']}  n_common={ex['n_common_papers']}")
        print(f"    evidence: {ex['evidence'][:120]}")
        print()

    print("TIER 2 EXAMPLES (terms co-occur, no verbatim):")
    for ex in tier2_examples:
        print(f"  [{ex['source_type']}] {ex['subject']} {ex['relation']} {ex['object']}")
        print(f"    n_common={ex['n_common_papers']}")
        print(f"    evidence: {ex['evidence'][:120]}")
        print()

    print("TIER 3 EXAMPLES (no term match):")
    for ex in tier3_examples:
        print(f"  [{ex['source_type']}] {ex['subject']} {ex['relation']} {ex['object']}")
        reason = ex.get("reason", "terms not found in common papers")
        print(f"    n_common={ex.get('n_common_papers', 0)}  reason={reason}")
        print(f"    evidence: {ex['evidence'][:120]}")
        if "subj_papers" in ex:
            print(f"    subj_papers={ex['subj_papers']}  obj_papers={ex['obj_papers']}")
        if "common_papers" in ex:
            print(f"    common_papers={ex['common_papers']}")
        print()

    db.close()


if __name__ == "__main__":
    main()
