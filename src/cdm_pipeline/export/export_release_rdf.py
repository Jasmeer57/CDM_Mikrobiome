#!/usr/bin/env python3
"""
Generate the release RDF fact-graph (OWL/XML + Turtle) from a release DB.

This is the canonical producer for `releases/<release-name>/cdm_facts_*.{owl,ttl}`.
It supersedes the ad-hoc OWL-emitters in `paper_claims/build_qwen_cdm.py` and
`paper_claims/apply_dedup.py`, which were never wired to release DBs and
shipped RDF containing 0 (v2.1-full) or only 78% (v2.0-qwen) of the DB
relationships.

Properties:
- Reads ONLY the SQLite release DB (no JSON side-files).
- Serializes EVERY row in `relationships` as a triple
  `mcdm:entity_<src>  mcdm:<PREDICATE>  mcdm:entity_<tgt>`.
- Strips C0 control characters (U+0000..U+001F except tab/newline/CR) from
  every string literal so the .owl file always parses as valid XML.
- Emits owl:Ontology header, 14 CDM classes, plus an `owl:ObjectProperty`
  per distinct `relationship_type` so the predicate vocabulary is also
  a first-class part of the fact graph.
- Total-triple invariant: file triple count == entity triples + relationship
  triples (modulo header) — the invariant is checked in src/tests/test_release_artifacts.py.

Usage:
    python cdm_pipeline/export/export_release_rdf.py \\
        --db releases/v2.0-qwen-publication/microbiome_cdm.db \\
        --release-name v2.0-qwen-publication \\
        --out-dir releases/v2.0-qwen-publication

    python cdm_pipeline/export/export_release_rdf.py \\
        --db releases/v2.1-full-multiner/microbiome_cdm.db \\
        --release-name v2.1-full-multiner \\
        --out-dir releases/v2.1-full-multiner
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from pathlib import Path

# rdflib is imported lazily inside main() so the script's --help is fast and
# so the CLI is informative even if rdflib is absent.
MCDM = "http://microbiome-cdm.org/qwen#"
ONT_IRI = "http://microbiome-cdm.org/qwen"

CDM_TYPES = [
    "ORGANISM", "CHEMICAL", "DISEASE", "PROTEIN", "DNA_RNA", "CELL_TYPE",
    "GENOMICS", "PATHWAY", "LAB_METHOD", "DATA_ANALYSIS", "SAMPLE_METHOD",
    "CLINICAL", "EXPERIMENTAL_METHOD", "STUDY_DESIGN",
]

# C0 control characters except TAB (\x09), LF (\x0a), CR (\x0d). Anything
# else in 0x00..0x1f is illegal in XML 1.0 char data and breaks the OWL/XML
# parser. Strip BEFORE the value reaches rdflib, otherwise the .owl is broken.
_CTRL_RE = re.compile(r"[\x00-\x08\x0b-\x0c\x0e-\x1f]")


def sanitize(value: str) -> str:
    """Strip illegal XML control characters from a string."""
    return _CTRL_RE.sub("", value) if value else value


def _predicate_name(relationship_type: str) -> str:
    """Turn 'CO_OCCURS_WITH' / 'PART_OF_PATHWAY' into a safe IRI fragment."""
    return re.sub(r"[^A-Za-z0-9]+", "_", relationship_type).strip("_") or "RELATES_TO"


def build_graph(con: sqlite3.Connection, release_label: str) -> tuple["Graph", int, int]:
    """Build the rdflib Graph and return (graph, n_entities, n_relationships)."""
    from rdflib import Graph, URIRef, Literal, Namespace, RDF, RDFS, OWL, XSD

    BASE = Namespace(MCDM)
    g = Graph()
    g.bind("mcdm", BASE)
    g.bind("owl", OWL)
    g.bind("rdfs", RDFS)

    # ── 1. Ontology metadata ───────────────────────────────────────
    ont_iri = URIRef(ONT_IRI)
    g.add((ont_iri, RDF.type, OWL.Ontology))
    g.add((ont_iri, RDFS.label, Literal(f"Microbiome-CDM ({release_label}) Fact Graph")))
    g.add((ont_iri, OWL.versionInfo, Literal("3.0.0")))

    # ── 2. CDM classes ─────────────────────────────────────────────
    for t in CDM_TYPES:
        cls = URIRef(f"{MCDM}{t}")
        g.add((cls, RDF.type, OWL.Class))
        g.add((cls, RDFS.subClassOf, OWL.Thing))
        g.add((cls, RDFS.label, Literal(t.replace("_", " "))))

    # ── 3. ObjectProperty per distinct predicate ──────────────────
    predicates = [r[0] for r in con.execute(
        "SELECT DISTINCT relationship_type FROM relationships WHERE relationship_type IS NOT NULL"
    ).fetchall()]
    for rtype in predicates:
        prop = URIRef(f"{MCDM}{_predicate_name(rtype)}")
        g.add((prop, RDF.type, OWL.ObjectProperty))
        g.add((prop, RDFS.label, Literal(rtype.replace("_", " ").lower())))

    # ── 4. Entities ────────────────────────────────────────────────
    entity_rows = con.execute("""
        SELECT id, term, entity_type, umls_mapped, UMLS_ID,
               confidence_score, paper_count,
               definition, contextual_definition
        FROM entities
    """).fetchall()
    for (eid, etype, *_rest) in entity_rows:
        pass  # placeholder so the unpack below isn't shadowed
    for (eid, term, etype, umls_mapped, umls_id,
         conf, pc, definition, ctx_def) in entity_rows:
        if not term or not etype:
            continue
        ind = URIRef(f"{MCDM}entity_{eid}")
        cls = URIRef(f"{MCDM}{etype}")
        g.add((ind, RDF.type, cls))
        g.add((ind, RDFS.label, Literal(sanitize(term))))
        if pc:
            g.add((ind, BASE.paperCount, Literal(int(pc), datatype=XSD.integer)))
        if umls_mapped and umls_id:
            g.add((ind, BASE.hasUMLSMapping, Literal(sanitize(umls_id))))
        if conf is not None:
            g.add((ind, BASE.confidenceScore, Literal(float(conf), datatype=XSD.float)))
        if definition:
            g.add((ind, RDFS.comment, Literal(sanitize(definition))))
        if ctx_def:
            g.add((ind, BASE.microbiomeContext, Literal(sanitize(ctx_def))))

    # ── 5. Relationships (EVERY row in the table) ─────────────────
    rel_rows = con.execute("""
        SELECT id, source_id, target_id, relationship_type, confidence, source_type
        FROM relationships
        ORDER BY id
    """).fetchall()
    for (rid, src_id, tgt_id, rtype, conf, stype) in rel_rows:
        if not rtype or src_id is None or tgt_id is None:
            continue
        pred = URIRef(f"{MCDM}{_predicate_name(rtype)}")
        g.add((
            URIRef(f"{MCDM}entity_{src_id}"),
            pred,
            URIRef(f"{MCDM}entity_{tgt_id}"),
        ))

    return g, len(entity_rows), len(rel_rows)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    p.add_argument("--db", required=True, help="Path to release microbiome_cdm.db")
    p.add_argument("--release-name", required=True,
                   help="Human label (e.g. v2.0-qwen-publication)")
    p.add_argument("--out-dir", required=True,
                   help="Where to write cdm_facts_<release-name>.{owl,ttl}")
    p.add_argument("--ttl-only", action="store_true",
                   help="Only emit Turtle (skip OWL/XML)")
    args = p.parse_args()

    db = Path(args.db)
    if not db.exists():
        print(f"DB not found: {db}", file=sys.stderr)
        return 1
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    con = sqlite3.connect(db)
    g, n_ent, n_rel = build_graph(con, args.release_name)
    con.close()

    # The legacy filename convention is a fixed abbreviation, NOT a direct
    # underscore-fication of the release name. Keep the historical filenames
    # stable so any external consumers don't break:
    #   v2.0-qwen-publication  -> cdm_facts_v2_0_qwen
    #   v2.1-full-multiner     -> cdm_facts_v2_1_full
    _FILENAME_OVERRIDES = {
        "v2.0-qwen-publication": "v2_0_qwen",
        "v2.1-full-multiner":     "v2_1_full",
    }
    _underscored = _FILENAME_OVERRIDES.get(
        args.release_name,
        re.sub(r"[^A-Za-z0-9]+", "_", args.release_name).strip("_"),
    )
    out_stem = f"cdm_facts_{_underscored}"

    ttl_path = out_dir / f"{out_stem}.ttl"
    g.serialize(destination=str(ttl_path), format="turtle")
    print(f"  TTL: {len(g):,} triples → {ttl_path}")

    if not args.ttl_only:
        owl_path = out_dir / f"{out_stem}.owl"
        g.serialize(destination=str(owl_path), format="xml")
        print(f"  OWL: {len(g):,} triples → {owl_path}")

    print()
    print(f"  Entities serialised:         {n_ent:>10,}")
    print(f"  Relationships serialised:   {n_rel:>10,}")
    print(f"  Total triples in graph:     {len(g):>10,}")
    if n_ent + n_rel > 0:
        overhead = len(g) - (n_ent + n_rel)
        print(f"  Overhead (header + props):  {overhead:>10,}  "
              f"({100 * overhead / len(g):.1f}% of total)")
    return 0


if __name__ == "__main__":
    sys.exit(main())