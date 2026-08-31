"""
Claim C runner for the mini-hybrid built by build_mini_hybrid.py.

Splits the hybrid into LLM-only, spaCy-only, and Hybrid (all-sources) views
by entity/relationship provenance, then computes the same comparison metrics
as paper_claims/claim_C_hybrid_fusion/benchmark.py but adapted to the data
shape produced locally (no Google Drive hybrid KG required).
"""
import sys, io
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
else:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
import argparse, csv, json
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_HYBRID = REPO_ROOT / "paper_claims" / "claim_C_hybrid_fusion" / "mini_hybrid"


def load_hybrid(hybrid_dir: Path):
    ents = json.loads((hybrid_dir / "entities.json").read_text(encoding="utf-8"))
    rels = json.loads((hybrid_dir / "relationships.json").read_text(encoding="utf-8"))
    sources = json.loads((hybrid_dir / "sources.json").read_text(encoding="utf-8"))
    return ents, rels, sources


def split_views(entities, relationships):
    """Split by entity provenance.

    - LLM-only entities: `source == 'llm'`
    - spaCy-only entities: `source == 'spacy'`
    - Hybrid: union of all entities.
    Relationships follow their participating entity sources:
    - A relationship whose source OR target is LLM-extracted belongs to LLM-edges.
    - Same for spaCy-edges.
    - Hybrid-edges = everything (union of all 3 source layers).
    """
    by_norm = {e["term_norm"]: e for e in entities}
    llm_set = {n for n, e in by_norm.items() if e.get("source") == "llm"}
    spc_set = {n for n, e in by_norm.items() if e.get("source") == "spacy"}

    def belongs(rel, sset):
        return rel.get("source_entity", "").lower() in sset or rel.get("target_entity", "").lower() in sset

    llm_rels = [r for r in relationships if belongs(r, llm_set)]
    spc_rels = [r for r in relationships if belongs(r, spc_set)]
    return {
        "LLM-only":       {"entities": [e for e in entities if e.get("source") == "llm"],         "relationships": llm_rels},
        "spaCy-only":     {"entities": [e for e in entities if e.get("source") == "spacy"],       "relationships": spc_rels},
        "Hybrid (5-source)": {"entities": entities,                                                "relationships": relationships},
    }


def metrics(name, view):
    ents = view["entities"]; rels = view["relationships"]
    type_counts = Counter(e["type"] for e in ents)
    rel_type_counts = Counter(r["relationship_type"] for r in rels)
    confidences = [e.get("confidence", 0) for e in ents if e.get("confidence")]
    cross_paper = sum(1 for r in rels if r.get("is_cross_paper"))
    co_mentioned = sum(1 for e in ents if len(e.get("sources", [])) >= 2)
    return {
        "n_entities": len(ents),
        "n_relationships": len(rels),
        "n_entity_types": len(type_counts),
        "n_rel_types": len(rel_type_counts),
        "mean_entity_confidence": round(sum(confidences) / max(1, len(confidences)), 3),
        "cross_paper_rels": cross_paper,
        "cross_paper_pct": round(100 * cross_paper / max(1, len(rels)), 1),
        "cross_source_entities": co_mentioned,
        "top_entity_types": ", ".join(f"{t}={c}" for t, c in type_counts.most_common(5)),
        "top_rel_types": ", ".join(f"{t}={c}" for t, c in rel_type_counts.most_common(5)),
    }


CASE_STUDIES = """\
// Case study 1: organisms associated with IBD
MATCH (o:ORGANISM)-[r:associated_with|co_occurs_with]->(d:DISEASE)
WHERE toLower(d.term) CONTAINS 'ibd' OR toLower(d.term) CONTAINS 'inflammatory bowel'
RETURN o.term, type(r), d.term, r.confidence
ORDER BY r.confidence DESC LIMIT 20;

// Case study 2: butyrate producers
MATCH (o:ORGANISM)-[r:produces|co_occurs_with]->(c:CHEMICAL)
WHERE toLower(c.term) CONTAINS 'butyrate'
RETURN o.term, r.evidence, r.confidence ORDER BY r.confidence DESC LIMIT 20;

// Case study 3: antibiotics that disrupt microbiome
MATCH (c:CHEMICAL)-[r:co_occurs_with|treated_by]->(d:DISEASE)
WHERE c.term IN ['vancomycin', 'ciprofloxacin', 'metronidazole', 'rifaximin']
RETURN c.term, type(r), d.term, r.confidence LIMIT 20;

// Case study 4: taxonomic lineage (simplified; requires NCBI taxonomy)
MATCH (e:ORGANISM {term:'Faecalibacterium prausnitzii'})-[r]-(ne:ENTITY)
WHERE ne.type IN ['ORGANISM', 'GENOMICS']
RETURN e.term, ne.term LIMIT 20;

// Case study 5: treatments for Crohn's disease
MATCH (c:CHEMICAL)-[r:treats|co_occurs_with]->(d:DISEASE)
WHERE toLower(d.term) CONTAINS 'crohn'
RETURN c.term, type(r), d.term, r.confidence
ORDER BY r.confidence DESC LIMIT 20;
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hybrid-dir", default=str(DEFAULT_HYBRID))
    ap.add_argument("--output", default=str(Path(__file__).parent / "results"))
    args = ap.parse_args()

    out = Path(args.output); out.mkdir(parents=True, exist_ok=True)
    hdir = Path(args.hybrid_dir)
    print(f"Loading hybrid from: {hdir}")
    entities, rels, sources = load_hybrid(hdir)
    print(f"  {len(entities)} entities, {len(rels)} relationships")
    print(f"  Source counts: {json.dumps(sources, indent=2)}\n")

    views = split_views(entities, rels)
    for name, view in views.items():
        print(f"  {name:25s}  entities={len(view['entities']):5d}  relationships={len(view['relationships']):5d}")
    print()

    # Metrics.
    m = {name: metrics(name, view) for name, view in views.items()}
    keys = list(m["LLM-only"].keys())

    # Per-config comparison CSV.
    cmp_csv = out / "config_comparison.csv"
    with open(cmp_csv, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["metric"] + list(views.keys()))
        w.writeheader()
        for k in keys:
            row = {"metric": k}
            for n in views: row[n] = m[n][k]
            w.writerow(row)
    print(f"Wrote: {cmp_csv}")

    # Per-type distribution.
    td_csv = out / "entity_type_distribution.csv"
    with open(td_csv, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f); w.writerow(["config", "type", "count"])
        for n, view in views.items():
            for t, c in Counter(e["type"] for e in view["entities"]).most_common():
                w.writerow([n, t, c])
    print(f"Wrote: {td_csv}")

    # Per-relationship-type distribution.
    rd_csv = out / "relationship_type_distribution.csv"
    with open(rd_csv, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f); w.writerow(["config", "type", "count"])
        for n, view in views.items():
            for t, c in Counter(r["relationship_type"] for r in view["relationships"]).most_common():
                w.writerow([n, t, c])
    print(f"Wrote: {rd_csv}")

    # Cypher case studies.
    cq_path = out / "case_study_queries.cypher"
    cq_path.write_text(CASE_STUDIES, encoding="utf-8")
    print(f"Wrote: {cq_path}")

    # Headline.
    print()
    print("=" * 70)
    print("HEADLINE METRICS")
    print("=" * 70)
    for key in ["n_entities", "n_relationships", "n_entity_types", "n_rel_types",
                "cross_paper_rels", "cross_paper_pct", "cross_source_entities",
                "mean_entity_confidence"]:
        row = f"  {key:30s}"
        for n in views:
            row += f"  {n:>18s}={str(m[n][key]):>10s}"
        print(row)

    # Verdict: hybrid wins if (n_entities ≥ both), (n_relationships ≥ both), (n_entity_types ≥ both),
    # (n_rel_types ≥ both), (cross_source_entities > 0 in hybrid only).
    h = m["Hybrid (5-source)"]; l = m["LLM-only"]; s = m["spaCy-only"]
    wins = losses = 0
    for key in ["n_entities", "n_relationships", "n_entity_types", "n_rel_types", "cross_paper_rels"]:
        if h[key] >= l[key]: wins += 0.5
        if h[key] >= s[key]: wins += 0.5
        if h[key] <  l[key]: losses += 0.5
        if h[key] <  s[key]: losses += 0.5
    print()
    print("=" * 70)
    print("VERDICT")
    print("=" * 70)
    print(f"  Hybrid wins on {wins:.1f} / 5 metric-config pairs (losses {losses:.1f})")
    if wins >= 3:
        verdict = "SUPPORTED (hybrid ≥ both single-method views on ≥3 metrics)"
    elif wins >= 1.5:
        verdict = "WEAKLY supported"
    else:
        verdict = "NOT supported"
    print(f"  → Claim C is {verdict}")

    summary = {
        "n_entities": len(entities),
        "n_relationships": len(rels),
        "source_counts": sources,
        "headline_metrics": m,
        "wins": wins, "losses": losses,
        "verdict": verdict,
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\nWrote: {out / 'summary.json'}")


if __name__ == "__main__":
    main()
