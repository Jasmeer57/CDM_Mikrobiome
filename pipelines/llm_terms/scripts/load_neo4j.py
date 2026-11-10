#!/usr/bin/env python3
"""
Loads the unified entity corpus (scripts/build_ontology_from_corpus.py output)
into a running Neo4j instance as a real graph:

  (:Entity {name, entity_type, paper_count, total_occurrences, average_confidence,
            umls_cuis, bioportal_iris, ols_iris})
  (:Entity)-[:CO_OCCURS_WITH {weight}]-(:Entity)

Nodes = unique corpus entities (from unified_entity_corpus.json).
Edges = co-occurrence: two entities get an edge, weighted by how many papers
they were BOTH extracted from (computed straight from the per-paper
*.mapped.json files, not fabricated - this is the only relationship signal
this corpus actually has, since no relation-extraction step was run).

Usage:
    python scripts/load_neo4j.py \
        --corpus <unified_entity_corpus.json> \
        --mapped_dir <dir of *.mapped.json> \
        --uri bolt://localhost:7688 --user neo4j --password ...
"""
import argparse
import itertools
import json
import logging
from collections import Counter
from pathlib import Path

from neo4j import GraphDatabase

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def parse_args():
    p = argparse.ArgumentParser(description="Load the unified entity corpus into Neo4j as a co-occurrence graph.")
    p.add_argument("--corpus", required=True, help="Path to unified_entity_corpus.json")
    p.add_argument("--mapped_dir", required=True, help="Directory of *.mapped.json (for co-occurrence edges)")
    p.add_argument("--uri", default="bolt://localhost:7688")
    p.add_argument("--user", default="neo4j")
    p.add_argument("--password", required=True)
    p.add_argument("--min_edge_weight", type=int, default=2,
                    help="Only create an edge if entities co-occur in at least this many papers "
                         "(cuts noise from one-off pairings, keeps the graph readable).")
    return p.parse_args()


def load_corpus(corpus_path):
    with open(corpus_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data["entities"]


def compute_cooccurrence(mapped_dir):
    """For each paper, get its set of unique entities, then count how many
    papers each unordered pair of entities co-occurs in."""
    pair_counts = Counter()
    files = sorted(Path(mapped_dir).glob("*.json"))
    for fp in files:
        with open(fp, "r", encoding="utf-8") as f:
            data = json.load(f)
        cdm_entities = data.get("results", {}).get("cdm_entities", {})
        entities_in_paper = set()
        for entity_type, ents in cdm_entities.items():
            for e in ents:
                term = e.get("entity")
                if term:
                    entities_in_paper.add((term.lower(), entity_type))
        for a, b in itertools.combinations(sorted(entities_in_paper), 2):
            pair_counts[(a, b)] += 1
    logger.info(f"Computed co-occurrence over {len(files)} papers: {len(pair_counts)} unique pairs.")
    return pair_counts


def main():
    args = parse_args()
    entities = load_corpus(args.corpus)
    pair_counts = compute_cooccurrence(args.mapped_dir)

    driver = GraphDatabase.driver(args.uri, auth=(args.user, args.password))
    with driver.session() as session:
        logger.info("Clearing existing graph (fresh load)...")
        session.run("MATCH (n) DETACH DELETE n")

        session.run("CREATE CONSTRAINT entity_key IF NOT EXISTS "
                     "FOR (e:Entity) REQUIRE (e.name_lower, e.entity_type) IS UNIQUE")

        logger.info(f"Loading {len(entities)} entity nodes...")
        batch = []
        for rec in entities:
            umls_cuis = [m.get("umls_cui") for m in rec.get("umls_mappings", []) if m.get("umls_cui")]
            bioportal_iris = [m.get("concept_id") for m in rec.get("bioportal_mappings", []) if m.get("concept_id")]
            ols_iris = [m.get("iri") for m in rec.get("ols_mappings", []) if m.get("iri")]
            batch.append({
                "name": rec["entity"],
                "name_lower": rec["entity"].lower(),
                "entity_type": rec["entity_type"],
                "paper_count": rec["paper_count"],
                "total_occurrences": rec["total_occurrences"],
                "average_confidence": rec["average_confidence"],
                "umls_cuis": umls_cuis,
                "bioportal_iris": bioportal_iris,
                "ols_iris": ols_iris,
            })

        session.run(
            """
            UNWIND $rows AS row
            CREATE (e:Entity {
                name: row.name, name_lower: row.name_lower, entity_type: row.entity_type,
                paper_count: row.paper_count, total_occurrences: row.total_occurrences,
                average_confidence: row.average_confidence,
                umls_cuis: row.umls_cuis, bioportal_iris: row.bioportal_iris, ols_iris: row.ols_iris
            })
            """,
            rows=batch,
        )

        logger.info("Tagging each Entity with its type as an extra label (for Neo4j Browser coloring)...")
        for etype in sorted(set(r["entity_type"] for r in entities)):
            safe_label = "".join(c for c in etype if c.isalnum() or c == "_")
            session.run(f"MATCH (e:Entity {{entity_type: $etype}}) SET e:`{safe_label}`", etype=etype)

        edges = [
            {"a_name": a[0], "a_type": a[1], "b_name": b[0], "b_type": b[1], "weight": w}
            for (a, b), w in pair_counts.items()
            if w >= args.min_edge_weight
        ]
        logger.info(f"Loading {len(edges)} CO_OCCURS_WITH edges (weight >= {args.min_edge_weight}, "
                    f"out of {len(pair_counts)} total pairs)...")

        session.run(
            """
            UNWIND $rows AS row
            MATCH (a:Entity {name_lower: row.a_name, entity_type: row.a_type})
            MATCH (b:Entity {name_lower: row.b_name, entity_type: row.b_type})
            CREATE (a)-[:CO_OCCURS_WITH {weight: row.weight}]->(b)
            """,
            rows=edges,
        )

        node_count = session.run("MATCH (n) RETURN count(n) AS c").single()["c"]
        edge_count = session.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]
        logger.info(f"DONE. Graph now has {node_count} nodes and {edge_count} relationships.")

    driver.close()


if __name__ == "__main__":
    main()
