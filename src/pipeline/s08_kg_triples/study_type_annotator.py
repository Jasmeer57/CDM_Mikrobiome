"""Study-type annotation from PubMed MeSH metadata.

Maps PubMed ``publication_types`` and ``mesh_terms`` to a canonical study
type (RCT, cohort, case-control, etc.) and writes a ``study_type`` column to
the relationships table.  The confidence-scoring formula (Gate 6) then uses
this paper-level metadata instead of relying solely on regex scanning of
evidence text.

MeSH publication types and MeSH descriptor terms are complementary:
  - ``publication_types`` (e.g. "Randomized Controlled Trial") come from the
    PubMed <PublicationTypeList> element — set by the indexer.
  - ``mesh_terms`` (e.g. "Cohort Studies", "Case-Control Studies") are MeSH
    descriptors assigned to the article.

Both are authoritative; when they disagree the more specific / higher-ranking
type wins (see ``_STUDY_TYPE_RANK``).

Usage (standalone):
    python -m cdm_pipeline.quality.study_type_annotator \
        --db path/to/microbiome_cdm.db \
        --pubmed-meta path/to/pubmed_metadata.json

Usage (imported from rebuild_relations.py):
    from cdm_pipeline.quality.study_type_annotator import annotate_study_types
    annotate_study_types(db_path, pubmed_meta_path)
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from pipeline.config import CDM_OUTPUT_DIR

DB_PATH = CDM_OUTPUT_DIR / "microbiome_cdm.db"
PUBMED_META_PATH = CDM_OUTPUT_DIR / "pubmed_metadata.json"

# ── Canonical study types (shared with confidence_scoring.py) ──
STUDY_TYPE_SCORES = {
    "systematic_review_meta_analysis": 1.0,
    "randomized_controlled_trial": 0.95,
    "prospective_cohort": 0.85,
    "cohort": 0.8,
    "retrospective_cohort": 0.7,
    "case_control": 0.6,
    "cross_sectional": 0.5,
    "case_series": 0.4,
    "case_report": 0.3,
    "in_vivo_animal": 0.55,
    "in_vitro": 0.45,
    "in_silico": 0.4,
    "review": 0.35,
    "guideline": 0.3,
    "consensus_statement": 0.3,
    "letter": 0.2,
    "editorial": 0.2,
    "conference_abstract": 0.3,
    "unknown": 0.25,
}

# Higher rank = higher priority when multiple types are detected.
_STUDY_TYPE_RANK = {
    "systematic_review_meta_analysis": 100,
    "randomized_controlled_trial": 95,
    "prospective_cohort": 85,
    "cohort": 80,
    "retrospective_cohort": 70,
    "case_control": 60,
    "cross_sectional": 50,
    "case_series": 40,
    "case_report": 30,
    "in_vivo_animal": 55,
    "in_vitro": 45,
    "in_silico": 40,
    "review": 35,
    "guideline": 30,
    "consensus_statement": 30,
    "conference_abstract": 30,
    "letter": 20,
    "editorial": 20,
    "unknown": 0,
}

# ── PubMed PublicationType → canonical study type ──
_PUB_TYPE_MAP: dict[str, str] = {
    "randomized controlled trial": "randomized_controlled_trial",
    "clinical trial, phase iii": "randomized_controlled_trial",
    "clinical trial, phase ii": "randomized_controlled_trial",
    "clinical trial, phase i": "randomized_controlled_trial",
    "clinical trial": "randomized_controlled_trial",
    "multicenter study": "prospective_cohort",
    "observational study": "cross_sectional",
    "twin study": "cross_sectional",
    "comparative study": "cross_sectional",
    "validation study": "cross_sectional",
    "meta-analysis": "systematic_review_meta_analysis",
    "review": "review",
    "case reports": "case_report",
    "editorial": "editorial",
    "letter": "letter",
}

# ── MeSH descriptor → canonical study type ──
_MESH_TERM_MAP: dict[str, str] = {
    "randomized controlled trials as topic": "randomized_controlled_trial",
    "clinical trials as topic": "randomized_controlled_trial",
    "meta-analysis as topic": "systematic_review_meta_analysis",
    "systematic reviews as topic": "systematic_review_meta_analysis",
    "cohort studies": "cohort",
    "prospective studies": "prospective_cohort",
    "retrospective studies": "retrospective_cohort",
    "longitudinal studies": "prospective_cohort",
    "follow-up studies": "prospective_cohort",
    "case-control studies": "case_control",
    "cross-sectional studies": "cross_sectional",
    "pilot projects": "cross_sectional",
    "proof of concept study": "case_series",
}

# ── MeSH terms that indicate animal / in-vitro ──
_ANIMAL_MESH = {"animals", "mice", "rats", "rodentia", "animal experimentation"}
_INVITRO_MESH = {"cells, cultured", "cell line", "cell line, tumor"}


def classify_paper(pub_types: list[str], mesh_terms: list[str]) -> str:
    """Classify a single paper into a canonical study type.

    Args:
        pub_types: PubMed PublicationType list (e.g. ["Journal Article", "Randomized Controlled Trial"])
        mesh_terms: MeSH descriptor list (e.g. ["Cohort Studies", "Prospective Studies"])

    Returns:
        Canonical study type key from STUDY_TYPE_SCORES, or "unknown".
    """
    candidates: list[tuple[int, str]] = []

    # From publication types
    for pt in pub_types:
        key = pt.lower().strip()
        mapped = _PUB_TYPE_MAP.get(key)
        if mapped:
            candidates.append((_STUDY_TYPE_RANK[mapped], mapped))

    # From MeSH terms
    mesh_lower = {m.lower().strip() for m in mesh_terms}
    for mt, mapped in _MESH_TERM_MAP.items():
        if mt in mesh_lower:
            candidates.append((_STUDY_TYPE_RANK[mapped], mapped))

    # Animal / in-vitro detection from MeSH
    if mesh_lower & _ANIMAL_MESH:
        # Only downgrade to animal if no stronger human study type found
        candidates.append((_STUDY_TYPE_RANK["in_vivo_animal"], "in_vivo_animal"))
    if mesh_lower & _INVITRO_MESH:
        candidates.append((_STUDY_TYPE_RANK["in_vitro"], "in_vitro"))

    if not candidates:
        return "unknown"

    # Pick the highest-ranking candidate
    candidates.sort(key=lambda x: -x[0])
    return candidates[0][1]


def build_paper_study_types(
    pubmed_meta: dict[str, Any],
) -> dict[str, str]:
    """Build {bioproject_id: study_type} from PubMed metadata.

    Args:
        pubmed_meta: Parsed pubmed_metadata.json — keys are bioproject IDs
                     (e.g. "PRJDB10485"), values are dicts with
                     ``publication_types`` and ``mesh_terms`` fields.

    Returns:
        {bioproject_id: canonical study type}
    """
    result: dict[str, str] = {}
    for bp_id, meta in pubmed_meta.items():
        pub_types = meta.get("publication_types", [])
        mesh_terms = meta.get("mesh_terms", [])
        result[bp_id] = classify_paper(pub_types, mesh_terms)
    return result


def _resolve_paper_id(raw: str) -> str:
    """Strip .txt suffix and normalize a paper_id from edge_evidence."""
    pid = raw.strip()
    if pid.endswith(".txt"):
        pid = pid[:-4]
    return pid


def annotate_study_types(
    db_path: Path | str = DB_PATH,
    pubmed_meta_path: Path | str = PUBMED_META_PATH,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Annotate relationships with study_type from PubMed metadata.

    For each relationship, looks up the study types of all papers that
    contribute evidence (via edge_evidence.paper_id → pubmed_metadata.json)
    and picks the highest-ranking study type among them.

    Writes a ``study_type`` column to the relationships table.

    Args:
        db_path: Path to microbiome_cdm.db
        pubmed_meta_path: Path to pubmed_metadata.json
        dry_run: If True, don't modify the DB

    Returns:
        Summary dict with distribution and coverage stats.
    """
    db_path = Path(db_path)
    pubmed_meta_path = Path(pubmed_meta_path)

    # Load PubMed metadata
    with open(pubmed_meta_path, encoding="utf-8") as f:
        pubmed_meta = json.load(f)
    print(f"Loaded PubMed metadata for {len(pubmed_meta):,} papers")

    # Classify each paper
    paper_study_types = build_paper_study_types(pubmed_meta)
    type_dist = Counter(paper_study_types.values())
    print(f"Paper study type distribution:")
    for st, n in type_dist.most_common():
        print(f"  {st:35s}: {n:4d}")

    conn = sqlite3.connect(str(db_path))

    # Add study_type column if not exists
    if not dry_run:
        try:
            conn.execute("ALTER TABLE relationships ADD COLUMN study_type TEXT")
        except sqlite3.OperationalError:
            pass

    # Build {relationship_id: set of paper_ids}
    rel_to_papers: dict[int, set[str]] = defaultdict(set)
    for row in conn.execute(
        "SELECT relationship_id, paper_id FROM edge_evidence"
    ).fetchall():
        rel_id, paper_id = row
        rel_to_papers[rel_id].add(_resolve_paper_id(paper_id))

    # For each relationship, pick the highest-ranking study type among its papers
    updates: list[tuple[str, int]] = []
    unmatched_count = 0
    for rel_id, papers in rel_to_papers.items():
        best_rank = -1
        best_type = "unknown"
        any_matched = False
        for paper_id in papers:
            st = paper_study_types.get(paper_id)
            if st is None:
                continue
            any_matched = True
            rank = _STUDY_TYPE_RANK.get(st, 0)
            if rank > best_rank:
                best_rank = rank
                best_type = st
        if not any_matched:
            unmatched_count += 1
        updates.append((best_type, rel_id))

    # Apply updates
    if not dry_run:
        conn.executemany(
            "UPDATE relationships SET study_type = ? WHERE id = ?",
            updates,
        )
        conn.commit()
        print(f"\nAnnotated {len(updates):,} relationships with study_type")

    # Stats
    rel_type_dist = Counter(u[0] for u in updates)
    n_with_type = sum(
        n for st, n in rel_type_dist.items() if st != "unknown"
    )

    conn.close()

    return {
        "n_papers_classified": len(paper_study_types),
        "n_paper_types": len([s for s in paper_study_types.values() if s != "unknown"]),
        "n_relationships": len(updates),
        "n_with_study_type": n_with_type,
        "n_unknown": rel_type_dist.get("unknown", 0),
        "n_unmatched_papers": unmatched_count,
        "paper_type_distribution": dict(type_dist.most_common()),
        "relationship_type_distribution": dict(rel_type_dist.most_common()),
        "dry_run": dry_run,
    }


def main():
    ap = argparse.ArgumentParser(
        description="Annotate relationships with study_type from PubMed MeSH metadata"
    )
    ap.add_argument("--db", required=True, help="Path to microbiome_cdm.db")
    ap.add_argument(
        "--pubmed-meta",
        default=str(PUBMED_META_PATH),
        help="Path to pubmed_metadata.json",
    )
    ap.add_argument("--dry-run", action="store_true", help="Don't modify DB")
    args = ap.parse_args()

    result = annotate_study_types(
        db_path=args.db,
        pubmed_meta_path=args.pubmed_meta_path,
        dry_run=args.dry_run,
    )

    print(f"\n{'='*60}")
    print(f"STUDY TYPE ANNOTATION ({'DRY RUN' if result['dry_run'] else 'APPLIED'})")
    print(f"{'='*60}")
    print(f"Papers classified:     {result['n_papers_classified']:,}")
    print(f"  With study type:      {result['n_paper_types']:,}")
    print(f"Relationships:         {result['n_relationships']:,}")
    print(f"  With study type:      {result['n_with_study_type']:,}")
    print(f"  Unknown:              {result['n_unknown']:,}")
    print(f"  Unmatched papers:     {result['n_unmatched_papers']:,}")
    print(f"\nPaper study type distribution:")
    for st, n in result["paper_type_distribution"].items():
        print(f"  {st:35s}: {n:4d}")
    print(f"\nRelationship study type distribution:")
    for st, n in result["relationship_type_distribution"].items():
        print(f"  {st:35s}: {n:4d}")


if __name__ == "__main__":
    main()
