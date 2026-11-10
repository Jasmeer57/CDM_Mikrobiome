#!/usr/bin/env python3
"""
Loads the full 352-paper graph into Neo4j: unified corpus entities as nodes
(same as load_neo4j.py) PLUS real extracted relationships from kg_pipeline.py
(kg_relationships_validated.json) as typed edges, alongside CO_OCCURS_WITH
edges for pairs that co-occur but have no extracted relationship.

Usage:
    python scripts/load_neo4j_full.py \
        --corpus <unified_entity_corpus.json> \
        --mapped_dir <dir of *.mapped.json> \
        --relationships <kg_relationships_validated.json> \
        --uri bolt://localhost:7688 --user neo4j --password ...
"""
import argparse
import itertools
import json
import logging
import re
from collections import Counter
from pathlib import Path

from neo4j import GraphDatabase

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--corpus", required=True)
    p.add_argument("--mapped_dir", required=True)
    p.add_argument("--relationships", required=True)
    p.add_argument("--uri", default="bolt://localhost:7688")
    p.add_argument("--user", default="neo4j")
    p.add_argument("--password", required=True)
    p.add_argument("--min_edge_weight", type=int, default=2)
    return p.parse_args()


def rel_type_to_label(rel_type: str) -> str:
    """Turn a relationship_type string into a safe Neo4j relationship type name."""
    safe = re.sub(r"[^A-Za-z0-9_]", "_", rel_type.upper())
    return safe or "RELATED_TO"


def main():
    args = parse_args()

    with open(args.corpus, "r", encoding="utf-8") as f:
        entities = json.load(f)["entities"]

    relationships = json.load(open(args.relationships, "r", encoding="utf-8"))
    logger.info(f"{len(relationships)} extracted relationships to load.")

    pair_counts = Counter()
    files = sorted(Path(args.mapped_dir).glob("*.json"))
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
                "name": rec["entity"], "name_lower": rec["entity"].lower(),
                "entity_type": rec["entity_type"], "paper_count": rec["paper_count"],
                "total_occurrences": rec["total_occurrences"], "average_confidence": rec["average_confidence"],
                "umls_cuis": umls_cuis, "bioportal_iris": bioportal_iris, "ols_iris": ols_iris,
            })
        session.run(
            """UNWIND $rows AS row
               CREATE (e:Entity {name: row.name, name_lower: row.name_lower, entity_type: row.entity_type,
                   paper_count: row.paper_count, total_occurrences: row.total_occurrences,
                   average_confidence: row.average_confidence, umls_cuis: row.umls_cuis,
                   bioportal_iris: row.bioportal_iris, ols_iris: row.ols_iris})""",
            rows=batch,
        )
        for etype in sorted(set(r["entity_type"] for r in entities)):
            safe_label = "".join(c for c in etype if c.isalnum() or c == "_")
            session.run(f"MATCH (e:Entity {{entity_type: $etype}}) SET e:`{safe_label}`", etype=etype)

        # Real extracted relationships, grouped by type so each gets its own Neo4j rel type.
        by_type = {}
        skipped_no_node = 0
        for r in relationships:
            by_type.setdefault(r["relationship_type"], []).append(r)

        for rel_type, rels in by_type.items():
            label = rel_type_to_label(rel_type)
            rows = [{
                "source": r["source_entity"], "source_type": r["source_type"],
                "target": r["target_entity"], "target_type": r["target_type"],
                "confidence": r.get("confidence", 0.0), "evidence": r.get("evidence", ""),
            } for r in rels]
            result = session.run(
                f"""UNWIND $rows AS row
                    MATCH (a:Entity {{name_lower: toLower(row.source), entity_type: row.source_type}})
                    MATCH (b:Entity {{name_lower: toLower(row.target), entity_type: row.target_type}})
                    CREATE (a)-[r:`{label}` {{confidence: row.confidence, evidence: row.evidence}}]->(b)
                    RETURN count(r) AS c""",
                rows=rows,
            )
            created = result.single()["c"]
            logger.info(f"  {rel_type} ({label}): {created}/{len(rels)} edges created")

        # Co-occurrence edges for pairs without an extracted relationship (weight >= threshold).
        edges = [
            {"a_name": a[0], "a_type": a[1], "b_name": b[0], "b_type": b[1], "weight": w}
            for (a, b), w in pair_counts.items() if w >= args.min_edge_weight
        ]
        logger.info(f"Loading {len(edges)} CO_OCCURS_WITH edges (weight >= {args.min_edge_weight})...")
        session.run(
            """UNWIND $rows AS row
               MATCH (a:Entity {name_lower: row.a_name, entity_type: row.a_type})
               MATCH (b:Entity {name_lower: row.b_name, entity_type: row.b_type})
               CREATE (a)-[:CO_OCCURS_WITH {weight: row.weight}]->(b)""",
            rows=edges,
        )

        node_count = session.run("MATCH (n) RETURN count(n) AS c").single()["c"]
        edge_count = session.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]
        logger.info(f"DONE. Graph now has {node_count} nodes and {edge_count} relationships "
                    f"({len(relationships)} extracted + co-occurrence edges).")

    driver.close()


if __name__ == "__main__":
    main()
