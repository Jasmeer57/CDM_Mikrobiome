#!/usr/bin/env python3
"""
Enhance the Microbiome CDM Ontology to publication-ready standard.

Takes the unified entity corpus JSON (from build_ontology_from_corpus.py or
the multi-NER run) and produces a fully annotated OWL/TTL ontology with:

  - Full OBO Foundry / FAIR metadata (creator, license, dates, versionIRI, imports)
  - skos:definition for every entity (from canonical mapping or corpus template)
  - oboInOwl:hasDbXref cross-ontology xrefs (canonical + related mappings)
  - prov:wasDerivedFrom paper-level provenance (capped at 20 papers per entity)
  - prov:wasAttributedTo NER model attribution
  - Class hierarchy with intermediate superclasses
  - owl:disjointWith axioms between top-level groups
  - ObjectProperty domain/range constraints
  - Aggressive junk-entity filtering (NER false positives)

Usage:
    python scripts/enhance_ontology_for_publication.py \
        --input  paper_claims/_multi_ner_runs/cdm_output/unified_entity_corpus.json \
        --output_dir paper_claims/_multi_ner_runs/cdm_output/enhanced
"""
import argparse
import json
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from rdflib import Graph, Namespace, RDF, RDFS, OWL, Literal, URIRef, BNode
from rdflib.namespace import XSD, SKOS, DCTERMS, FOAF, PROV

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# ── Namespaces ────────────────────────────────────────────────────────────────

BASE = Namespace("http://microbiome-cdm.org/ontology#")
ONT_IRI = URIRef("http://microbiome-cdm.org/ontology")
VERSION_IRI = URIRef("http://microbiome-cdm.org/ontology/releases/2026-08-31")
DC = Namespace("http://purl.org/dc/elements/1.1/")
OBO = Namespace("http://purl.obolibrary.org/obo/")
OBOINOWL = Namespace("http://www.geneontology.org/formats/oboInOwl#")
VANN = Namespace("http://purl.org/vocab/vann/")
VOID = Namespace("http://rdfs.org/ns/void#")

# ── Class hierarchy ───────────────────────────────────────────────────────────

CLASS_HIERARCHY = {
    # Intermediate superclasses
    "BiologicalEntity": {
        "label": "Biological Entity",
        "comment": "Biological organisms, cells, proteins, nucleic acids, and pathways.",
        "children": ["ORGANISM", "CELL_TYPE", "PROTEIN", "DNA_RNA", "PATHWAY"],
    },
    "ChemicalEntity": {
        "label": "Chemical Entity",
        "comment": "Chemical compounds, metabolites, small molecules, and drugs.",
        "children": ["CHEMICAL"],
    },
    "ClinicalEntity": {
        "label": "Clinical Entity",
        "comment": "Diseases, clinical terms, procedures, and measurements.",
        "children": ["DISEASE", "CLINICAL"],
    },
    "MethodEntity": {
        "label": "Method Entity",
        "comment": "Laboratory, sampling, experimental, analytical, and study design methods.",
        "children": [
            "LAB_METHOD", "SAMPLE_METHOD", "EXPERIMENTAL_METHOD",
            "DATA_ANALYSIS", "STUDY_DESIGN", "GENOMICS",
        ],
    },
}

# Leaf class metadata
CLASS_META = {
    "ORGANISM":           "Biological organism including bacteria, archaea, fungi, viruses",
    "CHEMICAL":           "Chemical compounds, metabolites, small molecules",
    "DISEASE":            "Diseases, conditions, disorders",
    "PROTEIN":            "Proteins, peptides, amino acid sequences",
    "DNA_RNA":            "DNA/RNA sequences, nucleic acids, genes",
    "CELL_TYPE":          "Cell types, cellular components",
    "GENOMICS":           "Genomics related terms and concepts",
    "PATHWAY":            "Biological pathways, processes",
    "LAB_METHOD":         "Laboratory methods, assays, protocols",
    "DATA_ANALYSIS":      "Data analysis methods, statistical approaches",
    "SAMPLE_METHOD":      "Sample collection and preservation methods",
    "CLINICAL":           "Clinical terms, procedures, measurements",
    "EXPERIMENTAL_METHOD": "Experimental methods and techniques",
    "STUDY_DESIGN":       "Study design terms and frameworks",
}

# Disjointness between top-level groups
DISJOINT_GROUPS = [
    ("BiologicalEntity", "ChemicalEntity"),
    ("BiologicalEntity", "ClinicalEntity"),
    ("BiologicalEntity", "MethodEntity"),
    ("ChemicalEntity", "ClinicalEntity"),
    ("ChemicalEntity", "MethodEntity"),
    ("ClinicalEntity", "MethodEntity"),
]

# ObjectProperty domain/range
PROP_DOMAIN_RANGE = {
    "PRODUCES":        ("ORGANISM",     "CHEMICAL"),
    "METABOLIZES":     ("ORGANISM",     "CHEMICAL"),
    "ENCODES":         ("DNA_RNA",      "PROTEIN"),
    "EXPRESSES":       ("ORGANISM",     "PROTEIN"),
    "PART_OF_PATHWAY": ("BiologicalEntity", "PATHWAY"),
    "ASSOCIATED_WITH": (None, None),
    "CO_OCCURS_WITH":  (None, None),
}

# ── Junk filtering ────────────────────────────────────────────────────────────

JUNK_PATTERNS = [
    # Sentence fragments: number + common English words
    re.compile(r'^\d+\)?\.?\s*(and|were|contained|the|individuals|with|copies|intestinal|week)\b', re.I),
    re.compile(r'^(in contrast|and|or|but)\)?$', re.I),
    # Temporal microbiome references (not organisms)
    re.compile(r'^\d+(M|m)?_(month|year|week|day|hour)_?microbiome$', re.I),
    re.compile(r'^\d+M_microbiome$', re.I),
    # Pure measurements
    re.compile(r'^\d+(\.\d+)?\s*(mL|mg|kg|µL|uL|mmol|mol|copies|intake|week_intake|mL_NaOH|mM_Fuc)$', re.I),
    re.compile(r'^\d+mL$', re.I),
    # Primer/sequence probe strings (e.g. 1119r, 1492_R, 27F, 78F)
    re.compile(r'^\d+[A-Z]?[rR]?$'),
    re.compile(r'^\d+_?[A-Z]+_?\d*[rR]?$'),
    # Age/developmental stage fragments
    re.compile(r'^\d+_week_old', re.I),
    # Single character or two-char
    re.compile(r'^.{1,2}$'),
    # Pure numbers (with optional decimal)
    re.compile(r'^\d+(\.\d+)?$'),
    # Pure punctuation
    re.compile(r'^[^\w]+$'),
    # Starts with a digit+parenthesis fragment like "05)."
    re.compile(r'^\d+\)\.?\s'),
    # NER artifacts: "X_and", "X_the", "X_with" where X is alphanumeric
    re.compile(r'^[A-Za-z0-9_]+_(and|the|with|for|from|of|in|to|on|at|by)\s*$', re.I),
]

# Specific junk strings to drop (case-insensitive)
JUNK_TERMS = {
    "05_and", "05_in_contrast", "65_contained_the", "7_individuals_with",
    "7_were", "8_copies", "8_intestinal", "40_bacterial",
    "1026_and", "6_glcnac_glcnac_by_l", "16s_bacteria", "16s_bacterial",
    "10ml", "12_week_intake", "166_mm_naoh", "16_mol",
    "1_3", "1_4", "1_4_2", "1_6",
    "1_ions", "1_sabin", "22l", "aaf", "aag", "aamm",
    "act_group", "ad03", "ad05", "ad24_strain", "ad36", "ad37",
}


def is_junk(label: str) -> bool:
    """Return True if the entity label is a NER false positive."""
    clean = label.strip()
    if not clean:
        return True
    # Also test the slugified version (underscores instead of spaces/punct)
    slug = re.sub(r'[^A-Za-z0-9]', '_', clean).lower()
    slug = re.sub(r'_+', '_', slug).strip('_')
    if slug in JUNK_TERMS:
        return True
    # Test both raw and slugified forms against patterns
    for test_str in (clean, slug):
        for pat in JUNK_PATTERNS:
            if pat.search(test_str):
                return True
    return False


# ── Helpers ──────────────────────────────────────────────────────────────────

def slugify(term: str) -> str:
    keep = "".join(c if c.isalnum() else "_" for c in term.strip())
    while "__" in keep:
        keep = keep.replace("__", "_")
    return keep.strip("_") or "entity"


def paper_to_iri(paper_id: str) -> URIRef:
    """Convert a paper filename to a resolvable IRI."""
    # Strip .txt extension, use PRJ accession as identifier
    acc = paper_id.replace(".txt", "").replace(".xml", "")
    return URIRef(f"http://microbiome-cdm.org/papers/{acc}")


def concept_id_to_xref(concept_id: str) -> str:
    """Normalize a concept_id URI to a compact xref string."""
    if not concept_id:
        return ""
    # Already a URI
    if concept_id.startswith("http"):
        return concept_id
    return concept_id


# ── Build ontology ───────────────────────────────────────────────────────────

def build_enhanced_ontology(corpus_data: dict, output_dir: Path, max_provenance: int = 20):
    """Build the enhanced publication-ready ontology from corpus JSON."""
    g = Graph()

    # Bind prefixes
    g.bind("cdm", BASE)
    g.bind("owl", OWL)
    g.bind("skos", SKOS)
    g.bind("dcterms", DCTERMS)
    g.bind("foaf", FOAF)
    g.bind("prov", PROV)
    g.bind("obo", OBO)
    g.bind("oboInOwl", OBOINOWL)
    g.bind("vann", VANN)
    g.bind("void", VOID)
    g.bind("dc", DC)

    entities = corpus_data["entities"]
    metadata = corpus_data.get("metadata", {})

    # ── 1. Ontology header with full metadata ──────────────────────────────
    logger.info("Adding ontology-level metadata...")
    g.add((ONT_IRI, RDF.type, OWL.Ontology))
    g.add((ONT_IRI, RDFS.label, Literal("Microbiome Common Data Model Ontology")))
    g.add((ONT_IRI, DCTERMS.title, Literal("Microbiome Common Data Model Ontology")))
    g.add((ONT_IRI, DCTERMS.description, Literal(
        f"Comprehensive ontology of human microbiome entities derived from "
        f"{metadata.get('source_papers', 444)} research papers covering 168,000 samples. "
        f"Contains {metadata.get('unique_entities', 29954)} unique entities across "
        f"{len(CLASS_META)} categories, mapped to controlled vocabularies including "
        f"NCBITaxon, ChEBI, DOID, MONDO, SNOMED CT, and UMLS."
    )))
    g.add((ONT_IRI, RDFS.comment, Literal(
        f"Auto-generated from {metadata.get('source_papers', 444)} microbiome papers. "
        f"{metadata.get('unique_entities', 29954)} entities, "
        f"{metadata.get('entities_with_external_mapping', 22225)} mapped to controlled vocabularies. "
        f"NER models: {', '.join(metadata.get('ner_models', ['GLiNER', 'PubTator3', 'BioBERT']))}. "
        f"Mapping services: {', '.join(metadata.get('mapping_services', ['OLS', 'OMOP Athena', 'NCBI Taxonomy']))}."
    )))
    g.add((ONT_IRI, DCTERMS.creator, Literal("Jasmeer Singh Kalra")))
    g.add((ONT_IRI, DC.creator, Literal("Jasmeer Singh Kalra")))
    g.add((ONT_IRI, FOAF.maker, Literal("Jasmeer Singh Kalra")))
    now = datetime.now(timezone.utc).isoformat()
    g.add((ONT_IRI, DCTERMS.created, Literal("2026-08-31", datatype=XSD.date)))
    g.add((ONT_IRI, DCTERMS.modified, Literal(now, datatype=XSD.dateTime)))
    g.add((ONT_IRI, DCTERMS.issued, Literal("2026-08-31", datatype=XSD.date)))
    g.add((ONT_IRI, DCTERMS.publisher, Literal("Microbiome CDM Project")))
    g.add((ONT_IRI, DCTERMS.license, URIRef("https://creativecommons.org/licenses/by/4.0/")))
    g.add((ONT_IRI, DCTERMS.rights, Literal(
        "This ontology is licensed under Creative Commons Attribution 4.0 International (CC-BY 4.0). "
        "You are free to share and adapt with attribution."
    )))
    g.add((ONT_IRI, OWL.versionInfo, Literal("3.0.0")))
    g.add((ONT_IRI, OWL.versionIRI, VERSION_IRI))
    g.add((ONT_IRI, OWL.priorVersion, URIRef("http://microbiome-cdm.org/ontology/releases/2026-03-01")))
    g.add((ONT_IRI, VANN.preferredNamespacePrefix, Literal("cdm")))
    g.add((ONT_IRI, VANN.preferredNamespaceURI, Literal(str(BASE))))
    g.add((ONT_IRI, FOAF.homepage, URIRef("https://microbiome-cdm.org")))
    g.add((ONT_IRI, DCTERMS.bibliographicCitation, Literal(
        "Kalra, J.S. (2026). Microbiome Common Data Model Ontology. Version 3.0.0. "
        "https://microbiome-cdm.org/ontology"
    )))
    g.add((ONT_IRI, VOID.vocabulary, URIRef("http://microbiome-cdm.org/ontology#")))

    # Imports of standard OBO ontologies
    for import_iri in [
        "http://purl.obolibrary.org/obo/ncbitaxon.owl",
        "http://purl.obolibrary.org/obo/chebi.owl",
        "http://purl.obolibrary.org/obo/doid.owl",
        "http://purl.obolibrary.org/obo/mondo.owl",
    ]:
        g.add((ONT_IRI, OWL.imports, URIRef(import_iri)))

    # Provenance: describe the source dataset
    g.add((ONT_IRI, PROV.wasGeneratedBy, Literal("Microbiome CDM Multi-NER Pipeline v2.0")))

    # ── 2. Class hierarchy ─────────────────────────────────────────────────
    logger.info("Adding class hierarchy...")
    for parent, info in CLASS_HIERARCHY.items():
        parent_cls = BASE[parent]
        g.add((parent_cls, RDF.type, OWL.Class))
        g.add((parent_cls, RDFS.label, Literal(info["label"])))
        g.add((parent_cls, RDFS.comment, Literal(info["comment"])))
        g.add((parent_cls, RDFS.subClassOf, OWL.Thing))
        for child in info["children"]:
            child_cls = BASE[slugify(child)]
            g.add((child_cls, RDF.type, OWL.Class))
            g.add((child_cls, RDFS.label, Literal(child.replace("_", " "))))
            g.add((child_cls, RDFS.comment, Literal(CLASS_META.get(child, ""))))
            g.add((child_cls, RDFS.subClassOf, parent_cls))

    # ── 3. Disjointness axioms ─────────────────────────────────────────────
    logger.info("Adding disjointness axioms...")
    for a, b in DISJOINT_GROUPS:
        g.add((BASE[a], OWL.disjointWith, BASE[b]))

    # ── 4. Object properties with domain/range ─────────────────────────────
    logger.info("Adding object properties with domain/range...")
    prop_labels = {
        "ASSOCIATED_WITH":  "associated with",
        "CO_OCCURS_WITH":   "co-occurs with",
        "ENCODES":           "encodes",
        "EXPRESSES":         "expresses",
        "METABOLIZES":       "metabolizes",
        "PART_OF_PATHWAY":   "part of pathway",
        "PRODUCES":          "produces",
    }
    for prop_name, (domain, rng) in PROP_DOMAIN_RANGE.items():
        prop = BASE[prop_name]
        g.add((prop, RDF.type, OWL.ObjectProperty))
        g.add((prop, RDFS.label, Literal(prop_labels.get(prop_name, prop_name))))
        if domain:
            g.add((prop, RDFS.domain, BASE[slugify(domain)]))
        if rng:
            g.add((prop, RDFS.range, BASE[slugify(rng)]))

    # Data properties
    data_props = {
        "paperCount":         ("paper count",          XSD.integer),
        "totalOccurrences":   ("total occurrences",     XSD.integer),
        "averageConfidence":  ("average confidence",    XSD.float),
        "mappingConfidence":  ("mapping confidence",    XSD.float),
    }
    for prop_name, (label, datatype) in data_props.items():
        prop = BASE[prop_name]
        g.add((prop, RDF.type, OWL.DatatypeProperty))
        g.add((prop, RDFS.label, Literal(label)))
        g.add((prop, RDFS.range, datatype))

    # Annotation properties
    for prop_name in ["hasOLSMapping", "hasUMLSMapping", "hasBioPortalMapping", "hasOMOPMapping"]:
        prop = BASE[prop_name]
        g.add((prop, RDF.type, OWL.AnnotationProperty))
        g.add((prop, RDFS.label, Literal(prop_name)))

    # ── 5. NER model agents (for prov:wasAttributedTo) ──────────────────────
    ner_models = metadata.get("ner_models", ["GLiNER", "PubTator3", "BioBERT"])
    model_agents = {}
    for model_name in ner_models:
        agent_iri = URIRef(f"http://microbiome-cdm.org/agents/{model_name}")
        g.add((agent_iri, RDF.type, PROV.SoftwareAgent))
        g.add((agent_iri, RDFS.label, Literal(model_name)))
        g.add((agent_iri, FOAF.name, Literal(model_name)))
        model_agents[model_name] = agent_iri

    # ── 6. Process entities ────────────────────────────────────────────────
    logger.info(f"Processing {len(entities)} entities...")
    seen_slugs = set()
    kept = 0
    junk = 0
    provenance_count = 0

    for i, rec in enumerate(entities):
        if i > 0 and i % 5000 == 0:
            logger.info(f"  Processed {i}/{len(entities)} (kept={kept}, junk={junk})")

        label = rec.get("entity", "")
        if not label:
            continue

        # Junk filter
        if is_junk(label):
            junk += 1
            continue

        entity_type = rec.get("entity_type", "CONCEPT")
        slug = slugify(label)
        # Deduplicate slugs
        base_slug = slug
        n = 1
        while slug in seen_slugs:
            n += 1
            slug = f"{base_slug}_{n}"
        seen_slugs.add(slug)

        ind = BASE[slug]
        cls = BASE[slugify(entity_type)]

        # Type assertions
        g.add((ind, RDF.type, OWL.NamedIndividual))
        g.add((ind, RDF.type, cls))

        # Label
        g.add((ind, RDFS.label, Literal(label)))

        # Definition
        canonical = rec.get("canonical_mapping", {})
        if canonical and canonical.get("label"):
            vocab = canonical.get("ontology_name", "unknown")
            concept_id = canonical.get("concept_id", "")
            def_text = (
                f"A {entity_type.replace('_', ' ').lower()} entity referring to "
                f"'{canonical['label']}' ({vocab}). "
                f"Identified in {rec.get('paper_count', 0)} papers from the microbiome literature corpus."
            )
        else:
            def_text = (
                f"A {entity_type.replace('_', ' ').lower()} entity extracted from the "
                f"human microbiome literature corpus, occurring in "
                f"{rec.get('paper_count', 0)} papers with "
                f"{rec.get('total_occurrences', 0)} total occurrences."
            )
        g.add((ind, SKOS.definition, Literal(def_text)))
        g.add((ind, OBO.IAO0000115, Literal(def_text)))

        # Corpus statistics
        g.add((ind, BASE.paperCount, Literal(rec.get("paper_count", 0), datatype=XSD.integer)))
        g.add((ind, BASE.totalOccurrences, Literal(rec.get("total_occurrences", 0), datatype=XSD.integer)))
        if "average_confidence" in rec:
            g.add((ind, BASE.averageConfidence, Literal(rec["average_confidence"], datatype=XSD.float)))

        # Canonical mapping → xref + seeAlso
        if canonical and canonical.get("concept_id"):
            concept_id = canonical["concept_id"]
            conf = canonical.get("confidence", 0.0)
            g.add((ind, OBOINOWL.hasDbXref, Literal(concept_id_to_xref(concept_id))))
            g.add((ind, RDFS.seeAlso, URIRef(concept_id) if concept_id.startswith("http") else Literal(concept_id)))
            g.add((ind, BASE.canonicalVocabulary, Literal(canonical.get("ontology_name", ""))))
            g.add((ind, BASE.canonicalConceptId, Literal(concept_id)))
            if canonical.get("label"):
                g.add((ind, BASE.canonicalLabel, Literal(canonical["label"])))
            g.add((ind, BASE.mappingConfidence, Literal(conf, datatype=XSD.float)))
            if concept_id.startswith("http"):
                g.add((ind, BASE.hasOLSMapping, URIRef(concept_id)))

        # Related mappings → SKOS relatedMatch + xrefs
        for rm in rec.get("related_mappings", []):
            rid = rm.get("concept_id", "")
            if not rid:
                continue
            rlabel = rm.get("label", "")
            relation = rm.get("relation", "relatedMatch")
            if relation == "exactMatch":
                g.add((ind, SKOS.exactMatch, URIRef(rid) if rid.startswith("http") else Literal(rid)))
            elif relation == "closeMatch":
                g.add((ind, SKOS.closeMatch, URIRef(rid) if rid.startswith("http") else Literal(rid)))
            elif relation == "broadMatch":
                g.add((ind, SKOS.broadMatch, URIRef(rid) if rid.startswith("http") else Literal(rid)))
            elif relation == "narrowMatch":
                g.add((ind, SKOS.narrowMatch, URIRef(rid) if rid.startswith("http") else Literal(rid)))
            else:
                g.add((ind, SKOS.relatedMatch, URIRef(rid) if rid.startswith("http") else Literal(rid)))
            # Also add as xref
            g.add((ind, OBOINOWL.hasDbXref, Literal(concept_id_to_xref(rid))))
            if rlabel:
                g.add((ind, OBOINOWL.hasExactSynonym, Literal(rlabel)))

        # Provenance: paper-level links (capped)
        papers = rec.get("papers", [])
        for paper_id in papers[:max_provenance]:
            paper_iri = paper_to_iri(paper_id)
            g.add((ind, PROV.wasDerivedFrom, paper_iri))
            provenance_count += 1
        if len(papers) > max_provenance:
            g.add((ind, RDFS.comment, Literal(
                f"Entity appears in {len(papers)} papers; showing first {max_provenance}. "
                f"Full list in unified_entity_corpus.json."
            )))

        # Provenance: NER model attribution
        for source in rec.get("sources", []):
            if source in model_agents:
                g.add((ind, PROV.wasAttributedTo, model_agents[source]))

        # Mark unmapped entities
        if not rec.get("has_any_external_mapping", False):
            g.add((ind, BASE.needsCuration, Literal(True, datatype=XSD.boolean)))

        kept += 1

    logger.info(f"Entity processing complete: kept={kept}, junk_filtered={junk}")
    logger.info(f"Provenance triples added: {provenance_count}")

    # ── 7. Paper IRIs as prov:Entities ─────────────────────────────────────
    logger.info("Adding paper entities for provenance...")
    all_papers = set()
    for rec in entities:
        for p in rec.get("papers", []):
            all_papers.add(p)
    for paper_id in all_papers:
        paper_iri = paper_to_iri(paper_id)
        g.add((paper_iri, RDF.type, PROV.Entity))
        acc = paper_id.replace(".txt", "")
        g.add((paper_iri, DCTERMS.identifier, Literal(acc)))
        g.add((paper_iri, RDFS.label, Literal(acc)))
    logger.info(f"Added {len(all_papers)} paper entities.")

    # ── 8. Serialize ───────────────────────────────────────────────────────
    output_dir.mkdir(parents=True, exist_ok=True)

    ttl_path = output_dir / "microbiome_cdm_enhanced.ttl"
    owl_path = output_dir / "microbiome_cdm_enhanced.owl"

    logger.info(f"Serializing Turtle to {ttl_path}...")
    g.serialize(destination=str(ttl_path), format="turtle", encoding="utf-8")

    logger.info(f"Serializing OWL/XML to {owl_path}...")
    g.serialize(destination=str(owl_path), format="xml", encoding="utf-8")

    # Stats
    stats = {
        "total_entities_input": len(entities),
        "entities_kept": kept,
        "entities_filtered_junk": junk,
        "paper_entities": len(all_papers),
        "provenance_triples": provenance_count,
        "total_triples": len(g),
        "version": "3.0.0",
        "generated_at": now,
    }
    stats_path = output_dir / "enhanced_ontology_stats.json"
    with open(stats_path, "w") as f:
        json.dump(stats, f, indent=2)

    logger.info(f"Stats written to {stats_path}")
    logger.info(f"\n=== Enhanced Ontology Complete ===")
    logger.info(f"Entities: {kept} (filtered {junk} junk)")
    logger.info(f"Total triples: {len(g)}")
    logger.info(f"TTL: {ttl_path}")
    logger.info(f"OWL: {owl_path}")

    return stats


def main():
    parser = argparse.ArgumentParser(description="Enhance Microbiome CDM ontology to publication-ready standard.")
    parser.add_argument(
        "--input",
        default="paper_claims/_multi_ner_runs/cdm_output/unified_entity_corpus.json",
        help="Path to unified_entity_corpus.json",
    )
    parser.add_argument(
        "--output_dir",
        default="paper_claims/_multi_ner_runs/cdm_output/enhanced",
        help="Directory for enhanced ontology outputs",
    )
    parser.add_argument(
        "--max_provenance",
        type=int,
        default=20,
        help="Maximum number of paper-level provenance links per entity",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        logger.error(f"Input file not found: {input_path}")
        sys.exit(1)

    logger.info(f"Loading corpus from {input_path}...")
    with open(input_path, "r", encoding="utf-8") as f:
        corpus_data = json.load(f)
    logger.info(f"Loaded {len(corpus_data['entities'])} entities")

    build_enhanced_ontology(corpus_data, Path(args.output_dir), args.max_provenance)


if __name__ == "__main__":
    main()
