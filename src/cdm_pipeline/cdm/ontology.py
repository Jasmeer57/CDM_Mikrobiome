"""Step 3: Create OWL/RDF ontology from the entity corpus."""
import re

from ..config import CDM_TYPES, CDM_OUTPUT_DIR

OUT = CDM_OUTPUT_DIR


def create_owl(corpus):
    print("\n" + "=" * 60)
    print("STEP 3: Creating OWL ontology")
    print("=" * 60)

    try:
        from rdflib import Graph, Namespace, URIRef, Literal, RDF, RDFS, OWL, XSD
    except ImportError:
        print("  rdflib not installed, skipping OWL")
        return None

    BASE = Namespace("http://microbiome-cdm.org/ontology#")
    g = Graph()
    ont_iri = URIRef("http://microbiome-cdm.org/ontology")
    g.add((ont_iri, RDF.type, OWL.Ontology))
    g.add((ont_iri, RDFS.label, Literal("Microbiome Common Data Model Ontology")))
    g.add((ont_iri, RDFS.comment, Literal(
        f"Entity ontology auto-generated from {corpus['metadata']['source_papers']} microbiome papers. "
        f"{len(corpus['entities'])} entities, "
        f"{corpus['metadata']['entities_with_external_mapping']} mapped to controlled vocabularies.")))
    g.add((ont_iri, OWL.versionInfo, Literal("2.0.0")))

    # One owl:Class per CDM type
    for t in CDM_TYPES:
        cls = URIRef(f"http://microbiome-cdm.org/ontology#{t}")
        g.add((cls, RDF.type, OWL.Class))
        g.add((cls, RDFS.subClassOf, OWL.Thing))
        g.add((cls, RDFS.label, Literal(t.replace("_", " "))))

    # Object properties
    for prop_name in ["ASSOCIATED_WITH", "PRODUCES", "EXPRESSES", "ENCODES",
                      "PART_OF_PATHWAY", "CO_OCCURS_WITH", "METABOLIZES"]:
        prop = URIRef(f"http://microbiome-cdm.org/ontology#{prop_name}")
        g.add((prop, RDF.type, OWL.ObjectProperty))
        g.add((prop, RDFS.label, Literal(prop_name.replace("_", " ").lower())))

    # NamedIndividual per entity
    slug_seen = set()

    def slug(term):
        s = re.sub(r"[^A-Za-z0-9]+", "_", term).strip("_")
        if not s:
            s = "entity"
        base = s
        idx = 2
        while s.lower() in slug_seen:
            s = f"{base}_{idx}"
            idx += 1
        slug_seen.add(s.lower())
        return s

    for e in corpus["entities"]:
        s = slug(e["entity"])
        ind = URIRef(f"http://microbiome-cdm.org/ontology#{s}")
        cls = URIRef(f"http://microbiome-cdm.org/ontology#{e['entity_type']}")
        g.add((ind, RDF.type, cls))
        g.add((ind, RDFS.label, Literal(e["entity"])))
        g.add((ind, BASE.paperCount, Literal(e["paper_count"], datatype=XSD.integer)))
        g.add((ind, BASE.totalOccurrences, Literal(e["total_occurrences"], datatype=XSD.integer)))

        if e.get("definition"):
            g.add((ind, RDFS.comment, Literal(e["definition"])))
        if e.get("context"):
            g.add((ind, BASE.microbiomeContext, Literal(e["context"])))
        if e.get("llm_verified"):
            g.add((ind, BASE.llmVerified, Literal(True, datatype=XSD.boolean)))
        if e.get("llm_confidence"):
            g.add((ind, BASE.llmConfidence, Literal(e["llm_confidence"], datatype=XSD.float)))

        canon = e.get("canonical_mapping")
        if canon:
            g.add((ind, BASE.canonicalVocabulary, Literal(canon.get("ontology_name", ""))))
            g.add((ind, BASE.canonicalConceptId, Literal(canon.get("concept_id", ""))))
            g.add((ind, BASE.canonicalLabel, Literal(canon.get("label", ""))))
            g.add((ind, BASE.mappingConfidence, Literal(canon.get("confidence", 0.0), datatype=XSD.float)))

        for m in e.get("umls_mappings", []):
            g.add((ind, BASE.hasUMLSMapping, Literal(m.get("concept_id", ""))))
        for m in e.get("ols_mappings", []):
            cid = m.get("concept_id", "")
            if cid.startswith("http"):
                g.add((ind, BASE.hasOLSMapping, URIRef(cid)))
            else:
                g.add((ind, BASE.hasOLSMapping, Literal(cid)))
        for m in e.get("bioportal_mappings", []):
            cid = m.get("concept_id", "")
            if cid.startswith("http"):
                g.add((ind, BASE.hasBioPortalMapping, URIRef(cid)))
            else:
                g.add((ind, BASE.hasBioPortalMapping, Literal(cid)))
        for m in e.get("omop_mappings", []):
            g.add((ind, BASE.hasOMOPMapping, Literal(m.get("concept_id", ""))))
        for m in e.get("ncbi_taxon_mappings", []):
            g.add((ind, BASE.hasNCBITaxonMapping, Literal(m.get("concept_id", ""))))

    owl_path = OUT / "microbiome_cdm.owl"
    g.serialize(destination=str(owl_path), format="xml")
    ttl_path = OUT / "microbiome_cdm.ttl"
    g.serialize(destination=str(ttl_path), format="turtle")
    print(f"  OWL: {len(g)} triples, saved to {owl_path}")
    print(f"  TTL: saved to {ttl_path}")
    return owl_path
