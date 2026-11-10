"""BioCypher/KGX export: Biolink-conformant node and edge TSVs.

Generates node and edge files in the Biolink Model format compatible with
the KGX (Knowledge Graph Exchange) standard, suitable for ingestion by
BioCypher or the NCATS Translator ecosystem.

Usage:
    python -m cdm_pipeline.export.biocypher --db cdm_output/microbiome_cdm.db --out cdm_output/kgx/
"""
import argparse
import sqlite3
from pathlib import Path

from ..config import CDM_OUTPUT_DIR

# CDM type → Biolink category mapping
CDM_TO_BIOLINK = {
    "ORGANISM":   "biolink:OrganismTaxon",
    "CHEMICAL":   "biolink:ChemicalEntity",
    "DISEASE":    "biolink:Disease",
    "PROTEIN":    "biolink:Protein",
    "DNA_RNA":    "biolink:Gene",
    "CELL_TYPE":  "biolink:Cell",
    "PATHWAY":    "biolink:Pathway",
    "LAB_METHOD": "biolink:Procedure",
    "DATA_ANALYSIS": "biolink:Procedure",
    "SAMPLE_METHOD": "biolink:Procedure",
    "CLINICAL":   "biolink:ClinicalIntervention",
    "EXPERIMENTAL_METHOD": "biolink:Procedure",
    "STUDY_DESIGN": "biolink:Procedure",
    "GENOMICS":   "biolink:GenomicEntity",
}

# Relationship type → Biolink predicate mapping
REL_TO_BIOLINK = {
    "ASSOCIATED_WITH":  "biolink:associated_with",
    "CO_OCCURS_WITH":   "biolink:co_occurs_with",
    "PRODUCES":         "biolink:produces",
    "EXPRESSES":        "biolink:expresses",
    "TREATS":           "biolink:treats",
    "DISRUPTS":         "biolink:disrupts",
    "PART_OF_PATHWAY":  "biolink:part_of",
    "ENCODES":          "biolink:encodes",
}

NODE_HEADER = [
    "id", "category", "name", "description", "synonym",
    "xref", "provided_by", "in_taxon",
]

EDGE_HEADER = [
    "id", "subject", "predicate", "object",
    "relation", "confidence", "provided_by",
    "publications", "evidence_type",
]


def export_biocypher(db_path: Path, out_dir: Path):
    """Export CDM entities and relationships as KGX-compliant TSV files.

    Outputs:
      nodes.tsv  — one row per entity with Biolink category
      edges.tsv  — one row per relationship with Biolink predicate
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    c = conn.cursor()

    # Export nodes
    node_path = out_dir / "nodes.tsv"
    entities = c.execute("""
        SELECT id, term, entity_type, confidence_score, paper_count
        FROM entities
    """).fetchall()

    # Gather xrefs (vocabulary mappings) per entity
    xref_map = {}
    xref_rows = c.execute("""
        SELECT entity_id, vocabulary_name, vocabulary_id
        FROM controlled_vocabularies
        WHERE is_canonical = 1
    """).fetchall()
    for eid, vname, vid in xref_rows:
        xref_map.setdefault(eid, []).append(f"{vname}:{vid}" if vid else vname)

    with open(node_path, "w", encoding="utf-8") as f:
        f.write("\t".join(NODE_HEADER) + "\n")
        for eid, term, etype, conf, pcount in entities:
            category = CDM_TO_BIOLINK.get(etype, "biolink:NamedThing")
            xrefs = "|".join(xref_map.get(eid, []))
            f.write("\t".join([
                f"MicrobiomeCDM:{eid}",
                category,
                term or "",
                "",  # description
                "",  # synonym
                xrefs,
                "Microbiome-CDM",
                "",  # in_taxon (could be populated from NCBITaxon xref)
            ]) + "\n")

    # Export edges
    edge_path = out_dir / "edges.tsv"
    rels = c.execute("""
        SELECT r.id, r.source_id, r.target_id, r.relationship_type,
               r.confidence, r.evidence_type, r.validation_status
        FROM relationships r
    """).fetchall()

    with open(edge_path, "w", encoding="utf-8") as f:
        f.write("\t".join(EDGE_HEADER) + "\n")
        for rid, src, tgt, rtype, conf, ev_type, val_status in rels:
            predicate = REL_TO_BIOLINK.get(rtype, "biolink:related_to")
            f.write("\t".join([
                f"MicrobiomeCDM-REL:{rid}",
                f"MicrobiomeCDM:{src}",
                predicate,
                f"MicrobiomeCDM:{tgt}",
                rtype,
                f"{conf:.3f}" if conf else "",
                "Microbiome-CDM",
                "",  # publications (could be populated from pubmed_ids)
                ev_type or "",
            ]) + "\n")

    conn.close()
    print(f"BioCypher/KGX export: {len(entities)} nodes → {node_path}")
    print(f"BioCypher/KGX export: {len(rels)} edges → {edge_path}")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Export CDM to BioCypher/KGX TSV")
    p.add_argument("--db", type=Path, default=CDM_OUTPUT_DIR / "microbiome_cdm.db")
    p.add_argument("--out", type=Path, default=CDM_OUTPUT_DIR / "kgx")
    args = p.parse_args()
    export_biocypher(args.db, args.out)
