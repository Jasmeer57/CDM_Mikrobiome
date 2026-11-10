"""Shared utilities for the Microbiome-CDM project.

Single source of truth for:
  - CDM entity types (14 types + UNKNOWN)
  - sciSpaCy label → CDM type mapping
  - term normalization (norm)
  - canonical vocabulary prefixes

Import from here instead of duplicating across pipelines.
"""
import re

# ── CDM Entity Types (14) ──
# Must match cdm_pipeline/config.py:CDM_TYPES exactly.
CDM_TYPES = [
    "ORGANISM", "CHEMICAL", "DISEASE", "PROTEIN", "DNA_RNA", "CELL_TYPE",
    "GENOMICS", "PATHWAY", "LAB_METHOD", "DATA_ANALYSIS", "SAMPLE_METHOD",
    "CLINICAL", "EXPERIMENTAL_METHOD", "STUDY_DESIGN",
]
# Extended list used by paper_claims scripts (includes GENE and UNKNOWN for
# label-mapping fallback). New code should prefer CDM_TYPES (14 types).
CDM_TYPES_EXTENDED = [
    "ORGANISM", "CHEMICAL", "DISEASE", "GENE", "PROTEIN", "DNA_RNA",
    "CELL_TYPE", "PATHWAY", "LAB_METHOD", "DATA_ANALYSIS", "SAMPLE_METHOD",
    "CLINICAL", "EXPERIMENTAL_METHOD", "STUDY_DESIGN", "UNKNOWN",
]

# ── sciSpaCy fine-grained label → CDM coarse type mapping ──
# Used by spacy_terms pipeline and paper_claims/claim_C scripts.
LABEL_TO_CDM = {
    # Direct matches
    "CHEMICAL": "CHEMICAL", "DRUG": "CHEMICAL",
    "TAXON": "ORGANISM", "ORGANISM": "ORGANISM",
    "DISEASE": "DISEASE",
    "PROTEIN": "PROTEIN", "GENE": "PROTEIN",
    "CELL_TYPE": "CELL_TYPE",
    # ChEBI
    "CHEBI": "CHEMICAL",
    # Sequence ontology
    "SO": "DNA_RNA", "DNA": "DNA_RNA", "RNA": "DNA_RNA",
    # Cell lines
    "CELL_LINE": "CELL_TYPE",
    # Generic
    "ENTITY": "UNKNOWN",
    # bionlp13cg variants
    "AMINO_ACID": "CHEMICAL",
    "GENE_OR_GENE_PRODUCT": "PROTEIN",
    "ORGANISM_SUBSTANCE": "CHEMICAL",
    "OTHER_ORGANISM": "ORGANISM",
    "SIMPLE_CHEMICAL": "CHEMICAL",
    # GGP = Gene or Gene Product
    "GGP": "PROTEIN",
    # GENOMICS (config.py type, not a sciSpaCy label but included for completeness)
    "GENOMICS": "GENOMICS",
}

# ── Canonical Bioregistry prefixes used across the project ──
# Ensures consistent vocabulary naming between config, mappers, and exports.
CANONICAL_VOCAB_PREFIXES = {
    "ncbitaxon": "NCBITAXON",
    "gtdb": "GTDB",
    "silva": "SILVA",
    "chebi": "CHEBI",
    "mesh": "MESH",
    "msh": "MESH",
    "rxnorm": "RXNORM",
    "rxn": "RXNORM",
    "snomedct": "SNOMEDCT",
    "snomedct_us": "SNOMEDCT",
    "snomed": "SNOMEDCT",
    "mondo": "MONDO",
    "doid": "DOID",
    "loinc": "LOINC",
    "lnc": "LOINC",
    "pr": "PR",
    "go": "GO",
    "cl": "CL",
    "clo": "CLO",
    "obi": "OBI",
    "ero": "ERO",
    "stato": "STATO",
    "edam": "EDAM",
    "ncit": "NCIT",
    "wikipathways": "WIKIPATHWAYS",
    "reactome": "REACTOME",
    "so": "SO",
    "sequence": "SEQUENCE",
    "genepio": "GENEPIO",
    "icd9cm": "ICD9CM",
    "icd10": "ICD10",
    "omim": "OMIM",
    "hgnc": "HGNC",
    "meddra": "MEDDRA",
    "rcd": "RCD",
    "cpt": "CPT",
}


def norm(t):
    """Normalize a term for deduplication: lowercase + collapse whitespace.

    This is the canonical implementation — import from common instead of
    redefining in every module.
    """
    return re.sub(r"\s+", " ", (t or "").lower().strip())


def norm_strict(s):
    """Stricter normalization: lowercase, strip non-alphanumerics (keep spaces + hyphens),
    collapse whitespace. Used by paper_claims scripts where punctuation matters
    for matching (e.g. biological_kb, hybrid_fusion).
    """
    s = (s or "").lower().strip()
    s = re.sub(r"[^a-z0-9\s\-]", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


__all__ = [
    "CDM_TYPES",
    "CDM_TYPES_EXTENDED",
    "LABEL_TO_CDM",
    "CANONICAL_VOCAB_PREFIXES",
    "norm",
    "norm_strict",
]
