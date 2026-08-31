#!/usr/bin/env python3
"""
Builds a unified entity corpus + a base OWL ontology from a directory of
*.mapped.json files produced by scripts/map_existing_corpus.py.

Two outputs:
  1. Unified corpus (JSON): every unique (entity, entity_type) across the
     whole run, with which papers it appeared in, how often, average
     confidence, and its best external mappings (UMLS CUI, BioPortal IRI,
     OLS IRI, OMOP concept if present).
  2. Base OWL ontology (.owl, RDF/XML via rdflib): one owl:Class per CDM
     entity_type, one NamedIndividual per unique entity typed to its class,
     annotated with corpus stats and cross-references to UMLS/BioPortal/OLS.

Scope note: this is an entity-level ontology base (classes + annotated
individuals), not a relational knowledge graph - no object-property
assertions between individuals, because this corpus only ran entity
extraction, not relationship extraction (that's a separate step -
llm_terms/scripts/kg_pipeline.py builds relationships; not run here).

Usage:
    python scripts/build_ontology_from_corpus.py --input_dir <dir of *.mapped.json> --output_dir <dir>
"""
import argparse
import json
import logging
import sys
from collections import defaultdict
from pathlib import Path

from rdflib import Graph, Namespace, RDF, RDFS, OWL, Literal, URIRef
from rdflib.namespace import XSD

sys.path.insert(0, str(Path(__file__).parent.parent))
from mappers.vocabulary_precedence import resolve_precedence

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

BASE = Namespace("http://microbiome-cdm.org/ontology#")


def parse_args():
    p = argparse.ArgumentParser(description="Build unified corpus + base OWL ontology from mapped entity JSON files.")
    p.add_argument("--input_dir", required=True, help="Directory of *.mapped.json files.")
    p.add_argument("--output_dir", required=True, help="Directory to write corpus + ontology outputs.")
    p.add_argument("--min_mapping_confidence", type=float, default=0.0,
                   help="Drop individual UMLS/BioPortal/OLS/OMOP mapping candidates below this "
                        "confidence before aggregating (0.0 = keep everything, i.e. old behavior). "
                        "Manual verification found the 0.4-0.55 band is ~68%% wrong; 0.55 keeps "
                        "~90%% of mapping volume at ~80%% precision - see verify100 sample in "
                        "run100/ontology_v2/.")
    return p.parse_args()


def slugify(term: str) -> str:
    """Turn an entity string into a safe URI local-name fragment."""
    keep = "".join(c if c.isalnum() else "_" for c in term.strip())
    while "__" in keep:
        keep = keep.replace("__", "_")
    return keep.strip("_") or "entity"


def main():
    args = parse_args()
    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    files = sorted(input_dir.glob("*.json"))
    logger.info(f"Found {len(files)} mapped corpus files.")

    # entity_key -> aggregated record
    unified = {}

    for fp in files:
        with open(fp, "r", encoding="utf-8") as f:
            data = json.load(f)
        paper_id = fp.stem.replace(".mapped", "")
        cdm_entities = data.get("results", {}).get("cdm_entities", {})

        for entity_type, entities in cdm_entities.items():
            for ent in entities:
                term = ent.get("entity")
                if not term:
                    continue
                key = (term.lower(), entity_type)
                rec = unified.setdefault(key, {
                    "entity": term,
                    "entity_type": entity_type,
                    "papers": set(),
                    "occurrences": 0,
                    "confidence_sum": 0.0,
                    "contexts": [],
                    "umls_mappings": [],
                    "bioportal_mappings": [],
                    "ols_mappings": [],
                    "omop_mappings": [],
                })
                rec["papers"].add(paper_id)
                rec["occurrences"] += 1
                rec["confidence_sum"] += ent.get("confidence", 0.0)
                if ent.get("context") and len(rec["contexts"]) < 3:
                    rec["contexts"].append(ent["context"])

                mapping = ent.get("comprehensive_mapping", {})
                for field in ("umls_mappings", "bioportal_mappings", "ols_mappings", "omop_mappings"):
                    for m in mapping.get(field, []):
                        if m.get("mapping_confidence", 1.0) < args.min_mapping_confidence:
                            continue  # below the verified-precision floor, drop the candidate entirely
                        if m not in rec[field]:
                            rec[field].append(m)

    logger.info(f"{len(unified)} unique (entity, type) pairs across {len(files)} papers.")

    # --- Output 1: unified corpus JSON ---
    corpus_out = []
    for (term_lc, entity_type), rec in unified.items():
        entity_record = {
            "entity": rec["entity"],
            "entity_type": rec["entity_type"],
            "paper_count": len(rec["papers"]),
            "papers": sorted(rec["papers"]),
            "total_occurrences": rec["occurrences"],
            "average_confidence": round(rec["confidence_sum"] / rec["occurrences"], 3) if rec["occurrences"] else 0.0,
            "example_contexts": rec["contexts"],
            "umls_mappings": rec["umls_mappings"],
            "bioportal_mappings": rec["bioportal_mappings"],
            "ols_mappings": rec["ols_mappings"],
            "omop_mappings": rec["omop_mappings"],
            "has_any_external_mapping": bool(
                rec["umls_mappings"] or rec["bioportal_mappings"] or rec["ols_mappings"] or rec["omop_mappings"]
            ),
        }
        # Cross-vocabulary precedence: pick one canonical concept per entity_type's
        # priority order, tag the rest with SKOS relations instead of leaving every
        # entity with an unordered pile of UMLS/OLS/BioPortal/OMOP candidates.
        precedence = resolve_precedence(entity_record)
        if precedence:
            entity_record["canonical_mapping"] = precedence["canonical"]
            entity_record["related_mappings"] = precedence["mappings"]
        corpus_out.append(entity_record)
    corpus_out.sort(key=lambda r: (-r["paper_count"], r["entity_type"], r["entity"]))

    corpus_fp = output_dir / "unified_entity_corpus.json"
    with open(corpus_fp, "w", encoding="utf-8") as f:
        json.dump({
            "metadata": {
                "source_papers": len(files),
                "unique_entities": len(corpus_out),
                "entities_with_external_mapping": sum(1 for r in corpus_out if r["has_any_external_mapping"]),
            },
            "entities": corpus_out,
        }, f, indent=2, ensure_ascii=False)
    logger.info(f"Wrote unified corpus: {corpus_fp}")

    # --- Output 2: base OWL ontology ---
    g = Graph()
    g.bind("cdm", BASE)
    g.bind("owl", OWL)

    ontology_iri = URIRef("http://microbiome-cdm.org/ontology")
    g.add((ontology_iri, RDF.type, OWL.Ontology))
    g.add((ontology_iri, RDFS.comment, Literal(
        "Base entity ontology auto-generated from a 100-paper microbiome-literature extraction run "
        "(llm_terms pipeline). Classes = CDM entity types. Individuals = unique extracted entities, "
        "annotated with corpus frequency and cross-references to UMLS/BioPortal/OLS where mapped. "
        "No relationship assertions between individuals - entity extraction only, no relation extraction step run."
    )))

    entity_types = sorted(set(r["entity_type"] for r in corpus_out))
    for etype in entity_types:
        cls = BASE[slugify(etype)]
        g.add((cls, RDF.type, OWL.Class))
        g.add((cls, RDFS.label, Literal(etype)))
        g.add((cls, RDFS.subClassOf, OWL.Thing))

    seen_slugs = set()
    for rec in corpus_out:
        base_slug = slugify(rec["entity"])
        slug = base_slug
        n = 1
        while slug in seen_slugs:
            n += 1
            slug = f"{base_slug}_{n}"
        seen_slugs.add(slug)

        ind = BASE[slug]
        cls = BASE[slugify(rec["entity_type"])]
        g.add((ind, RDF.type, OWL.NamedIndividual))
        g.add((ind, RDF.type, cls))
        g.add((ind, RDFS.label, Literal(rec["entity"])))
        g.add((ind, BASE.paperCount, Literal(rec["paper_count"], datatype=XSD.integer)))
        g.add((ind, BASE.totalOccurrences, Literal(rec["total_occurrences"], datatype=XSD.integer)))
        g.add((ind, BASE.averageConfidence, Literal(rec["average_confidence"], datatype=XSD.float)))

        for m in rec["umls_mappings"]:
            cui = m.get("umls_cui")
            if cui:
                g.add((ind, BASE.hasUMLSMapping, Literal(cui)))
        for m in rec["bioportal_mappings"]:
            if m.get("concept_id"):
                try:
                    g.add((ind, BASE.hasBioPortalMapping, URIRef(m["concept_id"])))
                except Exception:
                    g.add((ind, BASE.hasBioPortalMapping, Literal(m["concept_id"])))
        for m in rec["ols_mappings"]:
            if m.get("iri"):
                try:
                    g.add((ind, BASE.hasOLSMapping, URIRef(m["iri"])))
                except Exception:
                    g.add((ind, BASE.hasOLSMapping, Literal(m["iri"])))
        for m in rec["omop_mappings"]:
            concept_id = m.get("concept_id") or m.get("concept_name")
            if concept_id:
                g.add((ind, BASE.hasOMOPMapping, Literal(str(concept_id))))

    owl_fp = output_dir / "microbiome_cdm_base.owl"
    g.serialize(destination=str(owl_fp), format="xml")
    ttl_fp = output_dir / "microbiome_cdm_base.ttl"
    g.serialize(destination=str(ttl_fp), format="turtle")

    logger.info(f"Wrote OWL ontology: {owl_fp} ({len(g)} triples)")
    logger.info(f"Wrote Turtle ontology: {ttl_fp}")
    logger.info(f"Classes: {len(entity_types)}, Individuals: {len(seen_slugs)}")


if __name__ == "__main__":
    main()
