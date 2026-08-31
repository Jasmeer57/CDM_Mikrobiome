#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Claim C benchmark — 5-source hybrid fusion > either single method.

Compares three KG configurations (LLM-only, spaCy-only, Hybrid) on a standard
set of metrics. By default, the script derives LLM-only and spaCy-only views
from the existing hybrid output (filter by source provenance); for a clean
ground-truth comparison, run all three pipelines from scratch and point the
script at the three JSON files.

Usage (from this folder):
    python benchmark.py
    python benchmark.py --hybrid-dir /path/to/Output_final/
    python benchmark.py --output results/
"""
import argparse
import csv
import io
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

# Windows console defaults to cp1252; force UTF-8 for the ≥ / → / other Unicode.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
else:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

HERE = Path(__file__).parent
REPO_ROOT = HERE.parent.parent
DEFAULT_HYBRID_ENTITIES = str(
    REPO_ROOT / "llm_terms" / "Output_final" / "entities" / "*.json"
)
DEFAULT_HYBRID_RELATIONSHIPS = str(
    REPO_ROOT / "llm_terms" / "Output_final" / "relationships_extracted" / "*.json"
)


def load_json_any(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        return {"_error": str(exc)}


def discover(glob_pattern):
    return sorted(REPO_ROOT.glob(glob_pattern))


def normalize_entity(e):
    """Pull the canonical fields out of an entity dict (handles multiple schemas)."""
    return {
        "term": e.get("term") or e.get("entity") or e.get("name") or "",
        "type": (e.get("entity_type") or e.get("categories") or e.get("type") or "UNKNOWN").upper(),
        "source": e.get("source") or e.get("source_db") or e.get("extractor") or "unknown",
        "paper_count": e.get("paper_count") or e.get("frequency") or 0,
        "confidence": float(e.get("confidence") or e.get("average_confidence") or e.get("confidence_score") or 0.0),
        "has_umls": bool(e.get("UMLS_ID") or e.get("umls_cui") or e.get("umls_cuis")),
        "has_omop": bool(e.get("OMOP") or e.get("omop_id")),
        "has_chebi": bool(e.get("ChEBI") or e.get("chebi_id")),
        "has_ncbi": bool(e.get("NCBI") or e.get("ncbi_taxon_id") or "ncbitaxon" in str(e.get("ols_mappings", [])).lower()),
    }


def normalize_relationship(r):
    return {
        "source": r.get("source_entity") or r.get("source") or "",
        "target": r.get("target_entity") or r.get("target") or "",
        "type": (r.get("relationship_type") or r.get("relationship") or "related_to").lower(),
        "source_db": r.get("source_db") or r.get("evidence_source") or "unknown",
        "confidence": float(r.get("confidence") or 0.0),
        "paper_count": r.get("paper_count") or r.get("cross_paper_count") or 1,
        "is_cross_paper": bool(r.get("is_cross_paper") or (r.get("paper_count") or 0) >= 2),
        "has_evidence": bool(r.get("evidence") or r.get("source_context")),
    }


def derive_views_from_hybrid(entities, relationships):
    """Given the full hybrid graph, split into LLM-only / spaCy-only / hybrid
    views using simple provenance heuristics. This is a *synthetic* split for
    quick comparison; for real ground truth, re-run each pipeline independently."""
    llm_entities = [e for e in entities if e["source"] in {"llm", "llm_extractor", "qwen", "paper_llm", "scientific_llm", "paper_relationship_extractor"} or "llm" in e["source"].lower()]
    spacy_entities = [e for e in entities if e["source"] in {"spacy", "scispacy", "en_core_sci_lg", "en_ner_bc5cdr_md", "en_ner_craft_md", "en_ner_jnlpba_md"} or "spacy" in e["source"].lower() or "sci" in e["source"].lower()]
    # Anything that didn't classify cleanly is considered hybrid provenance.
    llm_set = {e["term"].lower() for e in llm_entities}
    spacy_set = {e["term"].lower() for e in spacy_entities}
    other = [
        e for e in entities
        if e["term"].lower() not in llm_set and e["term"].lower() not in spacy_set
    ]
    hybrid_entities = list({e["term"].lower(): e for e in (llm_entities + spacy_entities + other)}.values())

    # Relationships: split similarly.
    llm_rels = [r for r in relationships if "llm" in r["source_db"].lower() or r["source_db"] in {"paper_llm", "scientific_llm", "paper_relationship_extractor"}]
    spacy_rels = [r for r in relationships if "spacy" in r["source_db"].lower() or "sci" in r["source_db"].lower() or r["source_db"] in {"umls_scispacy"}]
    chebi_rels = [r for r in relationships if r["source_db"] in {"chebi", "kegg", "rhea", "metacyc"}]
    taxonomy_rels = [r for r in relationships if r["source_db"] in {"ncbi", "ncbi_taxonomy", "taxonomy"}]
    cooccur_rels = [r for r in relationships if r["source_db"] in {"co_occurrence", "co-occurrence", "papers"}]
    other_rels = [
        r for r in relationships
        if r not in llm_rels and r not in spacy_rels
        and r not in chebi_rels and r not in taxonomy_rels and r not in cooccur_rels
    ]

    return {
        "LLM-only": {"entities": llm_entities, "relationships": llm_rels},
        "spaCy-only": {"entities": spacy_entities, "relationships": spacy_rels},
        "Hybrid (5-source)": {
            "entities": hybrid_entities,
            "relationships": (llm_rels + spacy_rels + chebi_rels + taxonomy_rels + cooccur_rels + other_rels),
        },
    }


def metrics_for_view(name, view):
    """Compute the headline metrics for a view."""
    ents = view["entities"]
    rels = view["relationships"]
    type_counts = Counter(e["type"] for e in ents)
    rel_type_counts = Counter(r["type"] for r in rels)
    source_db_counts = Counter(r["source_db"] for r in rels)
    confidences = [e["confidence"] for e in ents if e["confidence"] > 0]
    rel_confidences = [r["confidence"] for r in rels if r["confidence"] > 0]
    cross_paper_rels = sum(1 for r in rels if r["is_cross_paper"])
    with_umls = sum(1 for e in ents if e["has_umls"])
    with_omop = sum(1 for e in ents if e["has_omop"])
    with_chebi = sum(1 for e in ents if e["has_chebi"])
    with_ncbi = sum(1 for e in ents if e["has_ncbi"])
    return {
        "n_entities": len(ents),
        "n_relationships": len(rels),
        "n_entity_types": len(type_counts),
        "n_rel_types": len(rel_type_counts),
        "with_umls": with_umls,
        "with_omop": with_omop,
        "with_chebi": with_chebi,
        "with_ncbi": with_ncbi,
        "umls_coverage_pct": round(100 * with_umls / max(1, len(ents)), 1),
        "chebi_coverage_pct": round(100 * with_chebi / max(1, len(ents)), 1),
        "ncbi_coverage_pct": round(100 * with_ncbi / max(1, len(ents)), 1),
        "cross_paper_rels": cross_paper_rels,
        "cross_paper_pct": round(100 * cross_paper_rels / max(1, len(rels)), 1),
        "mean_entity_confidence": round(sum(confidences) / max(1, len(confidences)), 3),
        "mean_rel_confidence": round(sum(rel_confidences) / max(1, len(rel_confidences)), 3),
        "top_5_entity_types": ", ".join(f"{t}={c}" for t, c in type_counts.most_common(5)),
        "top_3_source_dbs": ", ".join(f"{s}={c}" for s, c in source_db_counts.most_common(3)),
    }


# Case-study queries (Neo4j Cypher).
CASE_STUDY_QUERIES = """\
// Case study 1: organisms associated with IBD
// Expected: Faecalibacterium prausnitzii, Akkermansia muciniphila, etc.
MATCH (o:ORGANISM)-[r:correlates_with|treats]->(d:DISEASE)
WHERE toLower(d.term) CONTAINS 'ibd' OR toLower(d.term) CONTAINS 'inflammatory bowel'
RETURN o.term, type(r), d.term, r.confidence
ORDER BY r.confidence DESC
LIMIT 20;

// Case study 2: butyrate producers
// Expected: F. prausnitzii, Eubacterium rectale, Roseburia spp. (ChEBI-derived)
MATCH (o:ORGANISM)-[r:produces]->(c:CHEMICAL)
WHERE toLower(c.term) = 'butyrate'
   OR toLower(c.term) CONTAINS 'butyrate'
RETURN o.term, r.evidence, r.confidence
ORDER BY r.confidence DESC
LIMIT 20;

// Case study 3: antibiotics that disrupt the gut microbiome
// Expected: vancomycin, ciprofloxacin, etc.
MATCH (c:CHEMICAL)-[r:disrupts]->(m {entity_type:'MICROBIOME'})
WHERE c.subgraph = 'microbiome_metabolite'
RETURN c.term, r.evidence, r.confidence
ORDER BY r.confidence DESC
LIMIT 20;

// Case study 4: taxonomic lineage of Faecalibacterium prausnitzii
// Expected: Bacteria -> Firmicutes -> Clostridia -> ... -> F. prausnitzii
MATCH path = (root)-[:PARENT_OF*]->(s {term:'Faecalibacterium prausnitzii'})
RETURN [n IN nodes(path) | n.term] AS lineage
LIMIT 1;

// Case study 5: treatments for Crohn's disease
// Expected: infliximab, adalimumab, 5-ASA, corticosteroids
MATCH (c:CHEMICAL)-[r:treats]->(d:DISEASE)
WHERE toLower(d.term) CONTAINS 'crohn'
RETURN c.term, r.evidence, r.confidence
ORDER BY r.confidence DESC
LIMIT 20;
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--hybrid-entities", default=DEFAULT_HYBRID_ENTITIES)
    parser.add_argument("--hybrid-relationships", default=DEFAULT_HYBRID_RELATIONSHIPS)
    parser.add_argument("--output", default=str(HERE / "results"))
    parser.add_argument("--strict", action="store_true",
                        help="If set, fail (exit 1) when the hybrid view does not strictly outperform both single-method views on >=3 metrics.")
    args = parser.parse_args()

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Load hybrid output.
    ent_paths = discover(args.hybrid_entities)
    rel_paths = discover(args.hybrid_relationships)
    print(f"Discovered {len(ent_paths)} hybrid entity files, {len(rel_paths)} hybrid relationship files\n")
    if not ent_paths:
        print("No hybrid entity files found at", args.hybrid_entities)
        print("Pass --hybrid-entities explicitly, or place output under llm_terms/Output_final/entities/")
        sys.exit(1)

    entities = []
    for p in ent_paths:
        d = load_json_any(p)
        if isinstance(d, list):
            entities.extend(d)
        elif isinstance(d, dict):
            for key in ("entities", "results", "items"):
                if key in d and isinstance(d[key], list):
                    entities.extend(d[key])
                    break
    entities = [normalize_entity(e) for e in entities if e.get("term")]

    relationships = []
    for p in rel_paths:
        d = load_json_any(p)
        if isinstance(d, list):
            relationships.extend(d)
        elif isinstance(d, dict):
            for key in ("relationships", "results", "items"):
                if key in d and isinstance(d[key], list):
                    relationships.extend(d[key])
                    break
    relationships = [normalize_relationship(r) for r in relationships if r.get("source") and r.get("target")]

    print(f"Loaded {len(entities)} entities, {len(relationships)} relationships\n")

    # Derive views.
    views = derive_views_from_hybrid(entities, relationships)
    for name, view in views.items():
        print(f"  {name:25s}  entities={len(view['entities']):5d}  relationships={len(view['relationships']):5d}")

    # Metrics per view.
    metrics = {name: metrics_for_view(name, view) for name, view in views.items()}
    metric_keys = list(metrics["LLM-only"].keys())

    # Per-config comparison table.
    csv_path = out_dir / "config_comparison.csv"
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["metric"] + list(views.keys()))
        writer.writeheader()
        for key in metric_keys:
            row = {"metric": key}
            for name in views:
                row[name] = metrics[name][key]
            writer.writerow(row)
    print(f"\nWrote: {csv_path}")

    # Per-type distribution per config.
    type_path = out_dir / "entity_type_distribution.csv"
    with open(type_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["config", "type", "count"])
        for name, view in views.items():
            counts = Counter(e["type"] for e in view["entities"])
            for t, c in counts.most_common():
                writer.writerow([name, t, c])
    print(f"Wrote: {type_path}")

    # Case study queries.
    cypher_path = out_dir / "case_study_queries.cypher"
    cypher_path.write_text(CASE_STUDY_QUERIES, encoding="utf-8")
    print(f"Wrote: {cypher_path}")

    # Print the headline comparison.
    print()
    print("=" * 70)
    print("HEADLINE METRICS")
    print("=" * 70)
    for key in [
        "n_entities", "n_relationships", "n_entity_types", "n_rel_types",
        "umls_coverage_pct", "chebi_coverage_pct", "ncbi_coverage_pct",
        "cross_paper_rels", "cross_paper_pct",
        "mean_entity_confidence", "mean_rel_confidence",
    ]:
        row = f"  {key:30s}"
        for name in views:
            v = metrics[name][key]
            row += f"  {name:>15s}={str(v):>10s}"
        print(row)

    # Verdict.
    print()
    print("=" * 70)
    print("VERDICT")
    print("=" * 70)
    h = metrics["Hybrid (5-source)"]
    l = metrics["LLM-only"]
    s = metrics["spaCy-only"]
    wins = 0
    losses = 0
    for key in ["n_entities", "n_relationships", "umls_coverage_pct", "chebi_coverage_pct", "ncbi_coverage_pct", "cross_paper_rels"]:
        if h[key] > l[key]:
            wins += 0.5
        if h[key] > s[key]:
            wins += 0.5
        if h[key] < l[key]:
            losses += 0.5
        if h[key] < s[key]:
            losses += 0.5
    print(f"  Hybrid wins on {wins:.1f} / 6 metric-config pairs, loses on {losses:.1f}")
    if wins >= 3:
        print("  → Claim C is SUPPORTED (hybrid wins on ≥3 of 6 metrics)")
    elif wins >= 1.5:
        print("  → Claim C is WEAKLY supported (hybrid wins on 1.5-3 metrics; consider rephrasing)")
    else:
        print("  → Claim C is NOT supported (hybrid does not outperform single methods)")

    if args.strict and wins < 3:
        sys.exit(1)


if __name__ == "__main__":
    main()
