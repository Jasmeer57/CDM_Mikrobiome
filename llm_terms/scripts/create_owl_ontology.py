#!/usr/bin/env python3
"""
Create comprehensive OWL ontology from microbiome knowledge graph.
Uses lxml for proper XML serialization and escaping.
"""
import pandas as pd
import json
from pathlib import Path
from typing import Dict, List
import logging
from datetime import datetime
from lxml import etree

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# OWL ontology IRIs
BASE_IRI = "http://microbiome-cdm.org/ontology/"
OWL = "http://www.w3.org/2002/07/owl#"
RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
RDFS = "http://www.w3.org/2000/01/rdf-schema#"
XSD = "http://www.w3.org/2001/XMLSchema#"
OBO = "http://purl.obolibrary.org/obo/"
OBO_IN_OWL = "http://www.geneontology.org/formats/oboInOwl#"
DC = "http://purl.org/dc/elements/1.1/"

# Namespace map
NS_MAP = {
    None: BASE_IRI,
    'owl': OWL,
    'rdf': RDF,
    'rdfs': RDFS,
    'xsd': XSD,
    'obo': OBO,
    'oboInOwl': OBO_IN_OWL,
    'mb': BASE_IRI,
    'dc': DC
}


def sanitize_id(term: str) -> str:
    """Convert term to valid ontology ID."""
    clean = term.strip().replace(' ', '_').replace('-', '_').replace('/', '_')
    while '__' in clean:
        clean = clean.replace('__', '_')
    clean = clean.strip('_')
    return clean if clean else "Unknown"


def create_owl_header(root):
    """Create OWL ontology header with metadata."""
    timestamp = datetime.now().isoformat()

    ontology = etree.SubElement(root, f"{{{OWL}}}Ontology",
                                attrib={f"{{{RDF}}}about": BASE_IRI})

    # Version
    etree.SubElement(ontology, f"{{{OWL}}}versionIRI",
                     attrib={f"{{{RDF}}}resource": f"{BASE_IRI}releases/2026-03-01"})

    # Label
    label = etree.SubElement(ontology, f"{{{RDFS}}}label")
    label.text = "Microbiome Common Data Model Ontology"

    # Creator
    creator = etree.SubElement(ontology, f"{{{DC}}}creator")
    creator.text = "Microbiome CDM Project"

    # Date
    date = etree.SubElement(ontology, f"{{{DC}}}date")
    date.text = timestamp

    # Description
    desc = etree.SubElement(ontology, f"{{{DC}}}description")
    desc.text = "Comprehensive ontology of microbiome entities, relationships, and metadata derived from 168,000 samples across 481 studies."

    # Comment
    comment = etree.SubElement(ontology, f"{{{RDFS}}}comment")
    comment.text = "Generated from 8,657 entities with UMLS, OMOP, OLS, and BioPortal mappings"

    # Version info
    version = etree.SubElement(ontology, f"{{{OWL}}}versionInfo")
    version.text = "1.0.0"


def create_object_properties(root):
    """Create OWL object properties for relationship types."""
    properties = {
        'PARENT_OF': 'Taxonomic parent-child relationship',
        'PRODUCES': 'Organism produces chemical/metabolite',
        'ASSOCIATED_WITH': 'General association between entities',
        'PROTECTS_AGAINST': 'Negative association with disease',
        'EXACERBATES': 'Positive association with disease',
        'CAUSES': 'Causal relationship',
        'INHIBITS': 'Inhibition relationship',
        'METABOLIZES': 'Metabolic transformation',
        'DETECTS': 'Method detects entity',
        'MEASURES': 'Method quantifies entity',
        'PART_OF_PATHWAY': 'Entity participates in pathway',
        'REGULATES': 'Regulatory relationship',
        'INTERACTS_WITH': 'Molecular interaction'
    }

    for prop_id, label in properties.items():
        prop = etree.SubElement(root, f"{{{OWL}}}ObjectProperty",
                               attrib={f"{{{RDF}}}about": f"{BASE_IRI}{prop_id}"})

        label_elem = etree.SubElement(prop, f"{{{RDFS}}}label")
        label_elem.text = label

        comment = etree.SubElement(prop, f"{{{RDFS}}}comment")
        comment.text = label


def create_data_properties(root):
    """Create OWL data properties for entity attributes."""
    properties = {
        'confidence_score': 'Confidence score for entity or relationship',
        'paper_count': 'Number of papers mentioning entity',
        'frequency': 'Frequency of occurrence in corpus',
        'definition': 'Definition of the entity',
        'aliases': 'Alternative names for entity',
        'examples': 'Examples of entity',
        'evidence': 'Evidence for relationship',
        'mechanism': 'Mechanism of action',
        'ec_number': 'Enzyme Commission number',
        'pubmed_ids': 'PubMed IDs supporting relationship'
    }

    for prop_id, label in properties.items():
        prop = etree.SubElement(root, f"{{{OWL}}}DatatypeProperty",
                               attrib={f"{{{RDF}}}about": f"{BASE_IRI}{prop_id}"})

        label_elem = etree.SubElement(prop, f"{{{RDFS}}}label")
        label_elem.text = label

        range_elem = etree.SubElement(prop, f"{{{RDFS}}}range")
        range_elem.set(f"{{{RDF}}}resource", f"{XSD}string")


def create_entity_classes(root, entities: List[Dict]):
    """Create OWL classes for entities."""
    entity_types = {
        'ORGANISM': 'Biological organism including bacteria, archaea, fungi',
        'CHEMICAL': 'Chemical compounds, metabolites, small molecules',
        'DISEASE': 'Diseases, conditions, disorders',
        'LAB_METHOD': 'Laboratory methods, assays, protocols',
        'PATHWAY': 'Biological pathways, processes',
        'GENE': 'Genes, genetic elements',
        'PROTEIN': 'Proteins, peptides, amino acid sequences',
        'BIOMARKER': 'Biomarkers, indicators, measurements',
        'PHENOTYPE': 'Phenotypic traits, characteristics',
        'CONCEPT': 'General concepts, categories',
        'DATA_ANALYSIS': 'Data analysis methods, statistics',
        'CLINICAL': 'Clinical terms, procedures',
        'GENOMICS': 'Genomics related terms',
        'SAMPLE_METHOD': 'Sample collection methods',
        'CELL_TYPE': 'Cell types, cellular components',
        'DNA_RNA': 'DNA/RNA sequences, nucleic acids',
        'ANATOMICAL': 'Anatomical locations, body sites',
        'EXPERIMENTAL_METHOD': 'Experimental methods',
        'STUDY_DESIGN': 'Study design terms'
    }

    for entity_type, description in entity_types.items():
        class_id = sanitize_id(entity_type)
        cls = etree.SubElement(root, f"{{{OWL}}}Class",
                              attrib={f"{{{RDF}}}about": f"{BASE_IRI}{class_id}"})

        label = etree.SubElement(cls, f"{{{RDFS}}}label")
        label.text = entity_type

        comment = etree.SubElement(cls, f"{{{RDFS}}}comment")
        comment.text = description


def create_entity_individuals(root, entities: List[Dict], umls_mappings: List[Dict]):
    """Create OWL individuals for entities with metadata."""
    # Create map from term to UMLS data
    umls_map = {}
    for m in umls_mappings:
        if isinstance(m, dict) and 'term' in m:
            umls_map[m['term']] = m

    total = len(entities)
    for i, entity in enumerate(entities):
        if i > 0 and i % 1000 == 0:
            logger.info(f"  Processed {i}/{total} entities ({100*i/total:.1f}%)")

        term = entity.get('term', '')
        if not term:
            continue

        entity_id = sanitize_id(term)

        individual = etree.SubElement(root, f"{{{OWL}}}NamedIndividual",
                                     attrib={f"{{{RDF}}}about": f"{BASE_IRI}{entity_id}"})

        # Type
        entity_type = entity.get('entity_type', 'CONCEPT')
        class_id = sanitize_id(entity_type)
        type_elem = etree.SubElement(individual, f"{{{RDF}}}type")
        type_elem.set(f"{{{RDF}}}resource", f"{BASE_IRI}{class_id}")

        # Label
        label = etree.SubElement(individual, f"{{{RDFS}}}label")
        label.text = term

        # Definition
        definition = entity.get('definition', '')[:500]
        if definition:
            def_elem = etree.SubElement(individual, f"{{{OBO}}}IAO_0000115")
            def_elem.text = definition

        # Confidence score
        confidence = entity.get('confidence_score', 0.0)
        conf_elem = etree.SubElement(individual, f"{{{BASE_IRI}}}confidence_score")
        conf_elem.set(f"{{{RDF}}}datatype", f"{XSD}float")
        conf_elem.text = str(confidence)

        # Paper count
        paper_count = entity.get('paper_count', 0)
        paper_elem = etree.SubElement(individual, f"{{{BASE_IRI}}}paper_count")
        paper_elem.set(f"{{{RDF}}}datatype", f"{XSD}integer")
        paper_elem.text = str(paper_count)

        # UMLS ID
        umls_id = entity.get('UMLS_ID', '')
        if umls_id:
            xref = etree.SubElement(individual, f"{{{OBO_IN_OWL}}}hasDbXref")
            xref.set(f"{{{RDF}}}resource", f"http://identifiers.org/umls/{umls_id}")

        # OMOP ID
        omop_id = entity.get('OMOP', '')
        if omop_id:
            xref = etree.SubElement(individual, f"{{{OBO_IN_OWL}}}hasDbXref")
            xref.set(f"{{{RDF}}}resource", f"http://identifiers.org/omop/{omop_id}")

        # OLS ID
        ols_id = entity.get('OLS', '')
        if ols_id:
            xref = etree.SubElement(individual, f"{{{OBO_IN_OWL}}}hasDbXref")
            xref.set(f"{{{RDF}}}resource", ols_id)

        # Bioportal ID
        bioportal_id = entity.get('Bioportal', '')
        if bioportal_id:
            xref = etree.SubElement(individual, f"{{{OBO_IN_OWL}}}hasDbXref")
            xref.set(f"{{{RDF}}}resource", bioportal_id)

        # UMLS mappings
        if term in umls_map:
            umls_data = umls_map[term]
            concepts = umls_data.get('umls_concepts', [])[:3]
            for concept in concepts:
                cui = concept.get('cui', '')
                if cui:
                    xref = etree.SubElement(individual, f"{{{OBO_IN_OWL}}}hasDbXref")
                    xref.set(f"{{{RDF}}}resource", f"http://identifiers.org/umls/{cui}")


def create_relationship_assertions(root, relationships: pd.DataFrame):
    """Create OWL relationship assertions."""
    total = len(relationships)

    for i, (_, row) in enumerate(relationships.iterrows()):
        if i > 0 and i % 100 == 0:
            logger.info(f"  Processed {i}/{total} relationships ({100*i/total:.1f}%)")

        source = row.get('source', '')
        target = row.get('target', '')
        rel_type = row.get('relationship_type', 'ASSOCIATED_WITH')
        confidence = row.get('confidence', 1.0)
        evidence = row.get('evidence', '')[:500]
        source_db = row.get('source_db', '')

        if not source or not target:
            continue

        source_id = sanitize_id(source)
        target_id = sanitize_id(target)

        source_iri = f"{BASE_IRI}{source_id}"
        target_iri = f"{BASE_IRI}{target_id}"

        # Create assertion
        assertion_id = f"{source_id}_{rel_type}_{target_id}"
        assertion_iri = f"{BASE_IRI}{assertion_id}"

        axiom = etree.SubElement(root, f"{{{OWL}}}Axiom",
                                attrib={f"{{{RDF}}}about": assertion_iri})

        # Annotated source
        elem = etree.SubElement(axiom, f"{{{OWL}}}annotatedSource")
        elem.set(f"{{{RDF}}}resource", source_iri)

        # Annotated property
        elem = etree.SubElement(axiom, f"{{{OWL}}}annotatedProperty")
        elem.set(f"{{{RDF}}}resource", f"{BASE_IRI}{rel_type}")

        # Annotated target
        elem = etree.SubElement(axiom, f"{{{OWL}}}annotatedTarget")
        elem.set(f"{{{RDF}}}resource", target_iri)

        # Confidence
        conf = etree.SubElement(axiom, f"{{{BASE_IRI}}}confidence")
        conf.set(f"{{{RDF}}}datatype", f"{XSD}float")
        conf.text = str(confidence)

        # Source DB
        db = etree.SubElement(axiom, f"{{{BASE_IRI}}}source_db")
        db.text = str(source_db)

        # Evidence
        if evidence:
            ev = etree.SubElement(axiom, f"{{{BASE_IRI}}}evidence")
            ev.text = evidence

        # Create relationship assertion
        desc = etree.SubElement(root, f"{{{RDF}}}Description",
                               attrib={f"{{{RDF}}}about": source_iri})

        rel = etree.SubElement(desc, f"{{{BASE_IRI}}}{rel_type}")
        rel.set(f"{{{RDF}}}resource", target_iri)


def load_data():
    """Load all data files."""
    logger.info("Loading data files...")

    # Load entities
    entities_file = Path("/home/jkalra/Microbiome-CDM/llm_terms/knowledge_graph/cdm_entities_final_v3_embeddings.json")
    with open(entities_file) as f:
        entities_data = json.load(f)
    entities = entities_data['results']
    logger.info(f"Loaded {len(entities)} entities")

    # Load relationships
    relationships_file = Path("/home/jkalra/Microbiome-CDM/llm_terms/knowledge_graph/relationships_merged.csv")
    relationships = pd.read_csv(relationships_file)
    logger.info(f"Loaded {len(relationships)} relationships")

    # Load UMLS mappings
    mappings_file = Path("/home/jkalra/Microbiome-CDM/llm_terms/knowledge_graph/relationships/umls_entity_mappings.json")
    try:
        with open(mappings_file) as f:
            umls_data = json.load(f)
        if isinstance(umls_data, dict):
            if 'results' in umls_data:
                umls_mappings = umls_data['results']
            else:
                umls_mappings = [{'term': k, **v} if isinstance(v, dict) else {'term': k, 'umls_concepts': v}
                                 for k, v in umls_data.items()]
        else:
            umls_mappings = umls_data if isinstance(umls_data, list) else []
        logger.info(f"Loaded {len(umls_mappings)} UMLS mappings")
    except Exception as e:
        umls_mappings = []
        logger.warning(f"Could not load UMLS mappings: {e}")

    return entities, relationships, umls_mappings


def main():
    output_dir = Path("/home/jkalra/Microbiome-CDM/llm_terms/knowledge_graph")
    owl_dir = output_dir / "owl"
    owl_dir.mkdir(exist_ok=True)

    logger.info("Creating OWL ontology...")

    # Load data
    entities, relationships, umls_mappings = load_data()

    # Create root element
    root = etree.Element(f"{{{RDF}}}RDF", nsmap=NS_MAP)

    # Build OWL document
    logger.info("Building OWL document...")
    create_owl_header(root)
    create_object_properties(root)
    create_data_properties(root)
    create_entity_classes(root, entities)
    create_entity_individuals(root, entities, umls_mappings)
    create_relationship_assertions(root, relationships)

    # Save OWL file
    owl_file = owl_dir / "microbiome_cdm.owl"
    tree = etree.ElementTree(root)
    tree.write(owl_file, encoding='utf-8', xml_declaration=True, pretty_print=True)
    logger.info(f"Saved OWL ontology to {owl_file}")

    # Create statistics
    stats = {
        'total_entities': len(entities),
        'total_relationships': len(relationships),
        'entity_types_in_owl': len(set(e.get('entity_type', '') for e in entities)),
        'umls_mappings': len(umls_mappings),
        'owl_file_size_mb': round(owl_file.stat().st_size / (1024 * 1024), 2),
        'generated_at': datetime.now().isoformat()
    }

    stats_file = owl_dir / "owl_stats.json"
    with open(stats_file, 'w') as f:
        json.dump(stats, f, indent=2)

    logger.info(f"Saved statistics to {stats_file}")
    logger.info("\n=== OWL Ontology Generation Complete ===")
    logger.info(f"Total entities: {stats['total_entities']}")
    logger.info(f"Total relationships: {stats['total_relationships']}")
    logger.info(f"OWL file size: {stats['owl_file_size_mb']} MB")
    logger.info(f"\nFiles created in {owl_dir}:")
    logger.info(f"  - microbiome_cdm.owl")
    logger.info(f"  - owl_stats.json")


if __name__ == "__main__":
    main()
