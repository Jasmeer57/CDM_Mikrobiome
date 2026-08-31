"""
Build a small-scale "hybrid" knowledge graph from the LLM and spaCy batch runs
under paper_claims/_llm_runs/ and _spacy_runs/. The 5 sources are:

  S1. LLM entities        (CDM-typed, with confidence + paper context)
  S2. spaCy NER entities  (per-model labels, 4 models in parallel)
  S3. Cross-paper co-occurrence edges
  S4. Type-based canonical edges (ORGANISM-DISEASE, CHEMICAL-DISEASE, ...)
  S5. Cross-source co-mention (LLM term + spaCy term, same paper)

Produces JSON in paper_claims/claim_C_hybrid_fusion/mini_hybrid/ :
  - entities.json     (list of entity dicts with `source` provenance)
  - relationships.json (list of relationship dicts)
  - sources.json      (counts per source)
"""
import sys, io
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
else:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
import argparse, csv, json
from collections import defaultdict, Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_LLM = REPO_ROOT / "paper_claims" / "_llm_runs"
DEFAULT_SPACY = REPO_ROOT / "paper_claims" / "_spacy_runs"
DEFAULT_OUT = REPO_ROOT / "paper_claims" / "claim_C_hybrid_fusion" / "mini_hybrid"

# Type-pair canonical relation hints (from kg_pipeline.py VALID_TYPE_PAIRS).
CANONICAL_PAIRS = {
    ("ORGANISM", "DISEASE"): "associated_with",
    ("DISEASE", "ORGANISM"): "associated_with",
    ("ORGANISM", "CHEMICAL"): "produces",
    ("CHEMICAL", "ORGANISM"): "produced_by",
    ("CHEMICAL", "DISEASE"): "treats",
    ("DISEASE", "CHEMICAL"): "treated_by",
    ("GENE", "PROTEIN"): "encodes",
    ("PROTEIN", "GENE"): "encoded_by",
    ("PATHWAY", "CHEMICAL"): "involves",
    ("CHEMICAL", "PATHWAY"): "involved_in",
    ("PATHWAY", "DISEASE"): "implicated_in",
    ("DISEASE", "PATHWAY"): "implicates",
    ("ORGANISM", "PATHWAY"): "participates_in",
    ("PATHWAY", "ORGANISM"): "participates_in",
}


def norm(t):
    return (t or "").strip().lower()


def load_llm(llm_dir: Path):
    """Returns: list of (term, type, confidence, paper) and per-paper term sets."""
    triples, by_paper = [], defaultdict(set)
    for j in sorted(llm_dir.glob("*.cdm_entities.json")):
        try:
            d = json.loads(j.read_text(encoding="utf-8"))
        except Exception:
            continue
        paper = None
        meta = d.get("metadata", {}) or {}
        # No explicit paper field; infer from filename
        paper = j.stem.replace(".cdm_entities", "")
        inner = d.get("results", {}).get("cdm_entities", {}) or {}
        for etype, lst in inner.items():
            for e in (lst or []):
                term = e.get("entity") or e.get("term")
                if not term:
                    continue
                conf = float(e.get("confidence") or 0.0)
                triples.append((term.strip(), etype, conf, paper))
                by_paper[paper].add(norm(term))
    return triples, by_paper


def load_spacy(spacy_dir: Path):
    """Returns: list of (term, label, paper) and per-paper term sets."""
    triples, by_paper = [], defaultdict(set)
    for j in sorted(spacy_dir.glob("*.spacy_ner.csv")):
        paper = j.stem.replace(".spacy_ner", "")
        try:
            with open(j, "r", encoding="utf-8", newline="") as f:
                r = csv.DictReader(f)
                for row in r:
                    term = row.get("term", "").strip()
                    label = row.get("labels", "").strip()
                    if not term or len(term) < 2:
                        continue
                    if label == "ENTITY":  # drop the generic en_core_sci_lg label
                        continue
                    triples.append((term, label, paper))
                    by_paper[paper].add(norm(term))
        except Exception:
            continue
    return triples, by_paper


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm-dir", default=str(DEFAULT_LLM))
    ap.add_argument("--spacy-dir", default=str(DEFAULT_SPACY))
    ap.add_argument("--output", default=str(DEFAULT_OUT))
    ap.add_argument("--synonym-threshold", type=float, default=0.85)
    args = ap.parse_args()

    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)

    print(f"LLM dir:  {args.llm_dir}")
    print(f"spaCy dir: {args.spacy_dir}")
    print(f"Output:   {out}\n")

    llm_triples, llm_by_paper = load_llm(Path(args.llm_dir))
    spacy_triples, spacy_by_paper = load_spacy(Path(args.spacy_dir))

    print(f"LLM triples: {len(llm_triples)}")
    print(f"spaCy triples: {len(spacy_triples)}")

    # --- Build entity records (S1 = LLM, S2 = spaCy, S5 = co-mention) ---
    entities = []
    seen = {}  # norm -> entity dict

    def add_entity(term, etype, source, paper=None, **extra):
        k = norm(term)
        if k in seen:
            # record co-mention (S5)
            seen[k]["paper_count"] = seen[k].get("paper_count", 1) + 1
            seen[k]["sources"].add(source)
            if paper and paper not in seen[k].get("papers", []):
                seen[k].setdefault("papers", []).append(paper)
            return seen[k]
        rec = {
            "term": term,
            "term_norm": k,
            "type": (etype or "UNKNOWN").upper(),
            "source": source,
            "sources": {source},
            "paper_count": 1,
            "papers": [paper] if paper else [],
            **extra,
        }
        seen[k] = rec
        return rec

    for term, etype, conf, paper in llm_triples:
        add_entity(term, etype, "llm", paper, confidence=conf)
    for term, label, paper in spacy_triples:
        # map sciSpaCy labels to coarse CDM types
        coarse = {
            "CHEBI": "CHEMICAL", "CHEMICAL": "CHEMICAL", "DRUG": "CHEMICAL",
            "TAXON": "ORGANISM", "GGP": "PROTEIN", "SO": "DNA_RNA",
            "DNA": "DNA_RNA", "RNA": "DNA_RNA",
            "PROTEIN": "PROTEIN", "GENE": "GENE",
            "DISEASE": "DISEASE",
            "CELL_LINE": "CELL_TYPE", "CELL_TYPE": "CELL_TYPE",
        }.get(label.upper(), "UNKNOWN")
        add_entity(term, coarse, "spacy", paper, scispacy_label=label)

    # JSON can't serialize sets; convert all `sources` to sorted lists.
    for rec in seen.values():
        rec["sources"] = sorted(rec["sources"])

    entities = list(seen.values())
    print(f"Entities: {len(entities)}  (LLM-only + spaCy-only + co-mentioned)")

    # --- S3: cross-paper co-occurrence edges ---
    # Build per-paper term sets that include BOTH LLM and spaCy entities.
    by_paper = defaultdict(set)
    for paper, terms in llm_by_paper.items(): by_paper[paper].update(terms)
    for paper, terms in spacy_by_paper.items(): by_paper[paper].update(terms)
    seen_norms = set(seen.keys())

    relationships = []
    for paper, terms in by_paper.items():
        terms_in_seen = sorted(t for t in terms if t in seen_norms and seen[t]["type"] != "UNKNOWN")
        for i, a in enumerate(terms_in_seen):
            for b in terms_in_seen[i + 1: i + 6]:  # cap fan-out per paper
                ea, eb = seen[a], seen[b]
                if ea["type"] == eb["type"]:
                    continue
                rel_type = CANONICAL_PAIRS.get((ea["type"], eb["type"]), "co_occurs_with")
                relationships.append({
                    "source_entity": ea["term"],
                    "target_entity": eb["term"],
                    "relationship_type": rel_type,
                    "source_db": "co_occurrence",
                    "paper_count": 1,
                    "papers": [paper],
                    "is_cross_paper": False,
                    "confidence": 0.5,
                    "evidence": f"both mentioned in {paper}",
                })

    # --- S4: type-based canonical edges (across papers) ---
    by_type = defaultdict(list)
    for e in entities:
        if e["type"] != "UNKNOWN":
            by_type[e["type"]].append(e)
    for (ta, tb), rel in CANONICAL_PAIRS.items():
        if ta in by_type and tb in by_type:
            for ea in by_type[ta]:
                for eb in by_type[tb]:
                    if ea["term_norm"] == eb["term_norm"]:
                        continue
                    # Cap per (ta, tb) pair to keep graph tractable
                    if len([r for r in relationships if r["source_db"] == "canonical_type_pair" and r["relationship_type"] == rel]) > 200:
                        break
                    relationships.append({
                        "source_entity": ea["term"],
                        "target_entity": eb["term"],
                        "relationship_type": rel,
                        "source_db": "canonical_type_pair",
                        "paper_count": 0,
                        "papers": list(set(ea.get("papers", []) + eb.get("papers", []))),
                        "is_cross_paper": len(set(ea.get("papers", []) + eb.get("papers", []))) >= 2,
                        "confidence": 0.3,
                        "evidence": f"type-pair canonical: {ta} ↔ {tb}",
                    })
                else:
                    continue
                break

    # --- S5: cross-source co-mention (LLM + spaCy same paper) ---
    for paper, llm_terms in llm_by_paper.items():
        sp_terms = spacy_by_paper.get(paper, set())
        common = llm_terms & sp_terms
        for t in common:
            e = seen.get(t)
            if e and len(e.get("sources", set())) >= 2:
                e["cross_source"] = True

    # Collapse duplicate (source_entity, target_entity, relationship_type) edges.
    dedup = {}
    for r in relationships:
        key = (norm(r["source_entity"]), norm(r["target_entity"]), r["relationship_type"])
        if key not in dedup:
            dedup[key] = dict(r)
        else:
            d = dedup[key]
            d["paper_count"] = d.get("paper_count", 0) + r.get("paper_count", 0)
            d["is_cross_paper"] = d["is_cross_paper"] or r.get("is_cross_paper", False)
            for p in r.get("papers", []):
                if p and p not in d.get("papers", []):
                    d.setdefault("papers", []).append(p)
    relationships = list(dedup.values())
    print(f"Relationships: {len(relationships)}")

    # --- Source counts ---
    sources = {
        "S1_llm_entities":         sum(1 for e in entities if e.get("source") == "llm"),
        "S2_spacy_entities":       sum(1 for e in entities if e.get("source") == "spacy"),
        "S3_co_occurrence_edges":  sum(1 for r in relationships if r.get("source_db") == "co_occurrence"),
        "S4_type_canonical_edges": sum(1 for r in relationships if r.get("source_db") == "canonical_type_pair"),
        "S5_cross_source_ents":    sum(1 for e in entities if e.get("cross_source")),
    }
    print("Source counts:", json.dumps(sources, indent=2))

    # --- Persist ---
    (out / "entities.json").write_text(json.dumps(entities, indent=2), encoding="utf-8")
    (out / "relationships.json").write_text(json.dumps(relationships, indent=2), encoding="utf-8")
    (out / "sources.json").write_text(json.dumps(sources, indent=2), encoding="utf-8")
    print(f"\nWrote: {out}/entities.json  ({len(entities)} records)")
    print(f"Wrote: {out}/relationships.json  ({len(relationships)} records)")
    print(f"Wrote: {out}/sources.json")

    # Headline summary.
    print()
    print("=" * 70)
    print("MINI-HYBRID KG (10-paper batch)")
    print("=" * 70)
    print(f"  Entities: {len(entities)}")
    print(f"  Relationships: {len(relationships)}")
    print(f"  Sources: {len(sources)}")
    type_counts = Counter(e["type"] for e in entities)
    print(f"  Top entity types: {', '.join(f'{t}={c}' for t, c in type_counts.most_common(8))}")
    rel_counts = Counter(r["relationship_type"] for r in relationships)
    print(f"  Top rel types:    {', '.join(f'{t}={c}' for t, c in rel_counts.most_common(8))}")


if __name__ == "__main__":
    main()
