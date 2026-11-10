"""
Cross-vocabulary precedence rules for entities with mappings to more than one
ontology (UMLS, OLS, BioPortal, OMOP). Picks one canonical vocabulary/concept
per entity_type and records the rest as SKOS-typed relations, rather than
shipping an unordered pile of candidate mappings per entity.

Design (matches the priority order already used for the ontology-domain bonus
in confidence_scoring.py, reused here rather than re-specified):
  - Biological process / molecular function -> GO
  - Organism / taxon -> NCBITAXON
  - Phenotype / clinical sign -> HP-style clinical vocabularies (SNOMEDCT/MESH,
    since HP itself isn't one of the ontologies this pipeline queries)
  - Clinical/EHR-facing concept (drug, condition, procedure) -> OMOP-style
    (SNOMEDCT/RXNORM/LOINC as OMOP's own source vocabularies, since we have no
    local OMOP vocabulary files loaded this run - see omop_local_mapper.py)
  - Anything else -> whichever candidate has the highest confidence

SKOS relation assigned to every non-canonical mapping:
  - exactMatch: candidate confidence >= EXACT_MATCH_FLOOR (same concept, just
    a different vocabulary's identifier for it)
  - broadMatch: candidate's label is a token-subset of the canonical label
    (candidate is the more general concept)
  - narrowMatch: canonical's label is a token-subset of the candidate label
    (candidate is the more specific concept)
  - relatedMatch: none of the above - kept as evidence but flagged uncertain,
    matching the "flag for manual review" step in the spec this implements
"""
from typing import Dict, List, Optional

EXACT_MATCH_FLOOR = 0.85

VOCAB_PRIORITY_BY_TYPE = {
    "ORGANISM": ["NCBITAXON", "SNOMEDCT", "MESH"],
    "GENE": ["HGNC", "NCBIGENE", "GENE", "SO"],
    "PROTEIN": ["PR", "GO", "CHEBI", "MESH"],
    "CHEMICAL": ["CHEBI", "MESH", "RXNORM", "SNOMEDCT"],
    "DISEASE": ["DOID", "MONDO", "SNOMEDCT", "ICD9CM", "ICD10", "OMIM", "MESH"],
    "DNA_RNA": ["SO", "SEQUENCE", "GENEPIO", "MESH"],
    "CELL_TYPE": ["CL", "CLO", "MESH"],
    "SAMPLE_METHOD": ["OBI", "NCIT", "MESH"],
    "LAB_METHOD": ["OBI", "NCIT", "ERO", "MESH"],
    "DATA_ANALYSIS": ["STATO", "OBI", "EDAM", "NCIT"],
    "PATHWAY": ["GO", "WIKIPATHWAYS", "REACTOME", "CHEBI"],
    "EXPERIMENTAL_METHOD": ["OBI", "ERO", "NCIT"],
    "STUDY_DESIGN": ["OBI", "SNOMEDCT", "NCIT"],
    "GENOMICS": ["OBI", "SO", "NCIT", "MESH"],
    "CLINICAL": ["SNOMEDCT", "RXNORM", "LOINC", "NCIT", "MESH"],
}


def _label_words(label: str) -> set:
    return set(label.lower().split()) if label else set()


def _candidates_from_entity(entity: Dict) -> List[Dict]:
    """Flatten an entity's per-vocab mapping lists into one candidate list,
    tagging each with which vocab source it came from."""
    candidates = []
    for field, source in [("bioportal_mappings", "bioportal"), ("ols_mappings", "ols"),
                           ("umls_mappings", "umls"), ("omop_mappings", "omop")]:
        for m in entity.get(field, []):
            if source == "umls":
                candidates.append({
                    "source": source, "ontology_name": "UMLS",
                    "concept_id": m.get("umls_cui", ""), "label": m.get("preferred_name", ""),
                    "confidence": m.get("mapping_confidence", 0.0),
                })
            elif source == "omop":
                candidates.append({
                    "source": source, "ontology_name": "OMOP",
                    "concept_id": str(m.get("concept_id", "")), "label": m.get("concept_name", ""),
                    "confidence": 1.0,  # omop_local_mapper matches are exact-string by construction
                })
            else:
                candidates.append({
                    "source": source, "ontology_name": m.get("ontology_name", "").upper(),
                    "concept_id": m.get("concept_id") or m.get("iri", ""),
                    "label": m.get("label", ""), "confidence": m.get("mapping_confidence", 0.0),
                })
    # Dedupe by (ontology_name, concept_id) - the same concept can legitimately
    # come back from more than one API call (e.g. OLS and BioPortal both indexing
    # the same GENEPIO term), which otherwise shows up as redundant self-relations.
    seen = set()
    deduped = []
    for c in candidates:
        key = (c["ontology_name"], c["concept_id"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(c)
    return deduped


def resolve_precedence(entity: Dict) -> Optional[Dict]:
    """Given an entity dict (as produced by build_ontology_from_corpus.py),
    return {"canonical": {...}, "mappings": [{..., "relation": "exactMatch"|...}]}
    or None if the entity has no external mappings at all.
    """
    candidates = _candidates_from_entity(entity)
    if not candidates:
        return None

    priority = VOCAB_PRIORITY_BY_TYPE.get(entity["entity_type"], [])

    def sort_key(c):
        try:
            rank = priority.index(c["ontology_name"])
        except ValueError:
            rank = len(priority)  # not in the priority list - ranks after all preferred vocabs
        return (rank, -c["confidence"])

    ranked = sorted(candidates, key=sort_key)
    canonical = ranked[0]
    canonical_words = _label_words(canonical["label"])

    mappings = []
    for c in ranked[1:]:
        if c["confidence"] >= EXACT_MATCH_FLOOR:
            relation = "exactMatch"
        else:
            c_words = _label_words(c["label"])
            if c_words and canonical_words and c_words < canonical_words:
                relation = "broadMatch"
            elif c_words and canonical_words and canonical_words < c_words:
                relation = "narrowMatch"
            else:
                relation = "relatedMatch"
        mappings.append({**c, "relation": relation})

    return {"canonical": canonical, "mappings": mappings}
