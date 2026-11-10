"""Corroboration merge: merge triples across papers for the same entity pair.

When multiple papers report the same (subject, predicate, object) triple,
merge them into a single relationship with:
  - Aggregated evidence (concatenated, deduplicated)
  - Union of PubMed IDs / DOIs
  - Co-occurrence count = number of corroborating papers
  - Confidence boost: corroboration increases confidence
  - Provenance: list of source papers

This replaces the naive "first-writer-wins" approach in the current rebuild
with evidence aggregation and confidence boosting.

Adapted from EFRE's science_kg.py corroboration merge logic.
"""
from __future__ import annotations

import hashlib
from collections import defaultdict
from typing import Any


def _triple_key(subject: str, predicate: str, object: str) -> str:
    """Generate a canonical key for a triple (case-insensitive, whitespace-normalized)."""
    s = subject.strip().lower()
    p = predicate.strip().lower()
    o = object.strip().lower()
    return f"{s}||{p}||{o}"


def _entity_key(name: str, entity_type: str) -> str:
    """Generate a canonical entity key for matching."""
    return f"{name.strip().lower()}|{entity_type.strip().upper()}"


def merge_triples(triples: list[dict]) -> list[dict]:
    """Merge corroborating triples across papers.

    Each triple dict should have:
      subject, subject_type, predicate (or relationship_type), object, object_type,
      evidence, pubmed_ids (or paper_doi), confidence

    Returns a list of merged triples with:
      - evidence: aggregated (deduplicated, truncated)
      - pubmed_ids: union
      - paper_doi: union
      - co_occurrence_count: number of corroborating sources
      - confidence: boosted by corroboration
      - corroboration_count: number of sources
      - source_papers: list of source identifiers
    """
    groups: dict[str, list[dict]] = defaultdict(list)

    for t in triples:
        pred = t.get("predicate") or t.get("relationship_type") or ""
        key = _triple_key(t.get("subject", ""), pred, t.get("object", ""))
        groups[key].append(t)

    merged = []
    for key, group in groups.items():
        if len(group) == 1:
            t = dict(group[0])
            t["corroboration_count"] = 1
            t["co_occurrence_count"] = 1
            merged.append(t)
            continue

        # Sort by confidence descending — first triple is the "primary"
        group.sort(key=lambda x: x.get("confidence", 0.5), reverse=True)
        primary = dict(group[0])

        # Aggregate evidence (deduplicate by first 200 chars)
        seen_evidence: set[str] = set()
        evidence_parts: list[str] = []
        for t in group:
            ev = (t.get("evidence") or "").strip()
            if not ev:
                continue
            ev_key = ev[:200].lower()
            if ev_key not in seen_evidence:
                seen_evidence.add(ev_key)
                evidence_parts.append(ev)

        # Truncate total evidence to a reasonable length
        evidence_combined = " || ".join(evidence_parts)
        if len(evidence_combined) > 2000:
            evidence_combined = evidence_combined[:2000] + "... [truncated]"

        # Aggregate PubMed IDs
        pmids: set[str] = set()
        dois: set[str] = set()
        source_papers: list[str] = []
        for t in group:
            pmid = t.get("pubmed_ids") or ""
            if pmid:
                for p in pmid.split(","):
                    p = p.strip()
                    if p:
                        pmids.add(p)
            doi = t.get("paper_doi") or ""
            if doi:
                for d in doi.split(","):
                    d = d.strip()
                    if d:
                        dois.add(d)
            # Track source paper
            src = pmid or doi or t.get("source_paper") or ""
            if src:
                source_papers.append(src)

        # Confidence boost: corroboration increases confidence
        base_conf = primary.get("confidence", 0.5)
        n_sources = len(group)
        # Diminishing returns: boost = 0.05 * sqrt(n-1), capped at 0.15
        boost = min(0.15, 0.05 * (n_sources - 1) ** 0.5)
        boosted_conf = min(1.0, base_conf + boost)

        primary["evidence"] = evidence_combined
        primary["pubmed_ids"] = ",".join(sorted(pmids)) if pmids else ""
        primary["paper_doi"] = ",".join(sorted(dois)) if dois else ""
        primary["confidence"] = round(boosted_conf, 4)
        primary["corroboration_count"] = n_sources
        primary["co_occurrence_count"] = n_sources
        primary["source_papers"] = source_papers
        primary["source_type"] = "corroborated" if n_sources > 1 else primary.get("source_type", "extracted")

        merged.append(primary)

    return merged


def merge_db_relations(db_path, dry_run: bool = False) -> dict:
    """Merge corroborating relationships in the DB.

    Finds relationships with the same (source_id, relationship_type, target_id)
    and merges them into a single relationship, deleting duplicates.

    Returns a summary dict with counts.
    """
    import sqlite3

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    # Find duplicate groups
    rows = conn.execute("""
        SELECT r.id, r.source_id, r.target_id, r.relationship_type,
               r.confidence, r.evidence, r.pubmed_ids, r.paper_doi,
               r.co_occurrence_count, r.source_type,
               s.term as subject, s.entity_type as subject_type,
               t.term as object, t.entity_type as object_type
        FROM relationships r
        JOIN entities s ON r.source_id = s.id
        JOIN entities t ON r.target_id = t.id
        ORDER BY r.source_id, r.target_id, r.relationship_type, r.confidence DESC
    """).fetchall()

    # Group by (source_id, relationship_type, target_id)
    groups: dict[tuple, list[sqlite3.Row]] = defaultdict(list)
    for row in rows:
        key = (row["source_id"], row["relationship_type"], row["target_id"])
        groups[key].append(row)

    n_merged = 0
    n_deleted = 0
    n_kept = 0

    for key, group in groups.items():
        if len(group) == 1:
            n_kept += 1
            continue

        primary = dict(group[0])
        # Aggregate evidence
        seen_evidence: set[str] = set()
        evidence_parts: list[str] = []
        pmids: set[str] = set()
        dois: set[str] = set()
        total_co_occurrence = 0

        for row in group:
            ev = (row["evidence"] or "").strip()
            if ev:
                ev_key = ev[:200].lower()
                if ev_key not in seen_evidence:
                    seen_evidence.add(ev_key)
                    evidence_parts.append(ev)
            pmid = row["pubmed_ids"] or ""
            if pmid:
                for p in pmid.split(","):
                    p = p.strip()
                    if p:
                        pmids.add(p)
            doi = row["paper_doi"] or ""
            if doi:
                for d in doi.split(","):
                    d = d.strip()
                    if d:
                        dois.add(d)
            total_co_occurrence += row["co_occurrence_count"] or 1

        evidence_combined = " || ".join(evidence_parts)
        if len(evidence_combined) > 2000:
            evidence_combined = evidence_combined[:2000] + "... [truncated]"

        # Confidence boost
        n_sources = len(group)
        base_conf = primary.get("confidence", 0.5) or 0.5
        boost = min(0.15, 0.05 * (n_sources - 1) ** 0.5)
        boosted_conf = min(1.0, base_conf + boost)

        if not dry_run:
            # Update the primary (highest-confidence) relationship
            conn.execute("""
                UPDATE relationships SET
                    evidence = ?,
                    pubmed_ids = ?,
                    paper_doi = ?,
                    co_occurrence_count = ?,
                    confidence = ?,
                    source_type = ?
                WHERE id = ?
            """, (
                evidence_combined,
                ",".join(sorted(pmids)) if pmids else None,
                ",".join(sorted(dois)) if dois else None,
                total_co_occurrence,
                round(boosted_conf, 4),
                "corroborated",
                primary["id"],
            ))

            # Delete duplicates
            for row in group[1:]:
                conn.execute("DELETE FROM relationships WHERE id = ?", (row["id"],))
                n_deleted += 1

        n_merged += 1

    if not dry_run:
        conn.commit()
    conn.close()

    return {
        "total_groups": len(groups),
        "merged_groups": n_merged,
        "duplicates_deleted": n_deleted,
        "singletons_kept": n_kept,
        "dry_run": dry_run,
    }


def main():
    import argparse

    ap = argparse.ArgumentParser(description="Merge corroborating relationships in DB")
    ap.add_argument("--db", required=True, help="Path to microbiome_cdm.db")
    ap.add_argument("--dry-run", action="store_true", help="Show what would merge without modifying")
    args = ap.parse_args()

    result = merge_db_relations(args.db, dry_run=args.dry_run)
    mode = "DRY RUN" if result["dry_run"] else "APPLIED"
    print(f"=== CORROBORATION MERGE ({mode}) ===")
    print(f"  Total groups:        {result['total_groups']}")
    print(f"  Merged groups:       {result['merged_groups']}")
    print(f"  Duplicates deleted:  {result['duplicates_deleted']}")
    print(f"  Singletons kept:     {result['singletons_kept']}")


if __name__ == "__main__":
    main()
