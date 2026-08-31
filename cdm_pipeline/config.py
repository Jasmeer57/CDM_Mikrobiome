"""Shared configuration: paths, CDM types, vocabulary priorities."""
import os
from pathlib import Path

# ── Paths ──
REPO_ROOT = Path(__file__).resolve().parent.parent
PAPERS_DIR = REPO_ROOT / "papers_txt"
NER_OUTPUT_DIR = REPO_ROOT / "paper_claims" / "_multi_ner_runs"
CDM_OUTPUT_DIR = NER_OUTPUT_DIR / "cdm_output"
LLM_TERMS_DIR = REPO_ROOT / "llm_terms"
SPACY_VENV_PYTHON = REPO_ROOT / "spacy_terms" / ".venv39" / "Scripts" / "python.exe"
BIOPROJECT_JSON = REPO_ROOT / "bioproject_data_export.json"

# ── CDM entity types (14) ──
CDM_TYPES = [
    "ORGANISM", "CHEMICAL", "DISEASE", "PROTEIN", "DNA_RNA", "CELL_TYPE",
    "GENOMICS", "PATHWAY", "LAB_METHOD", "DATA_ANALYSIS", "SAMPLE_METHOD",
    "CLINICAL", "EXPERIMENTAL_METHOD", "STUDY_DESIGN",
]

# ── Vocabulary priority for canonical mapping ──
VOCAB_PRIORITY = {
    "ORGANISM": ["NCBITAXON", "SNOMEDCT", "MESH", "NCIT"],
    "PROTEIN": ["PR", "GO", "CHEBI", "MESH", "HGNC", "NCBITAXON"],
    "CHEMICAL": ["CHEBI", "MESH", "RXNORM", "SNOMEDCT", "NCIT"],
    "DISEASE": ["DOID", "MONDO", "SNOMEDCT", "ICD9CM", "ICD10", "OMIM", "MESH"],
    "DNA_RNA": ["SO", "SEQUENCE", "GENEPIO", "MESH", "NCIT"],
    "CELL_TYPE": ["CL", "CLO", "MESH", "NCIT"],
    "SAMPLE_METHOD": ["OBI", "NCIT", "MESH"],
    "LAB_METHOD": ["OBI", "NCIT", "ERO", "MESH"],
    "DATA_ANALYSIS": ["STATO", "OBI", "EDAM", "NCIT"],
    "PATHWAY": ["GO", "WIKIPATHWAYS", "REACTOME", "CHEBI"],
    "EXPERIMENTAL_METHOD": ["OBI", "ERO", "NCIT"],
    "STUDY_DESIGN": ["OBI", "SNOMEDCT", "NCIT"],
    "GENOMICS": ["OBI", "SO", "NCIT", "MESH"],
    "CLINICAL": ["SNOMEDCT", "NCIT", "LOINC", "MESH"],
}

# ── Preferred vocabularies per CDM type (for confidence scoring) ──
PREFERRED = {
    "ORGANISM": {"NCBITAXON", "SNOMEDCT", "MESH"},
    "PROTEIN": {"PR", "GO", "CHEBI", "MESH"},
    "CHEMICAL": {"CHEBI", "MESH", "RXNORM", "SNOMEDCT"},
    "DISEASE": {"DOID", "MONDO", "SNOMEDCT", "ICD9CM", "ICD10", "OMIM", "MESH"},
    "DNA_RNA": {"SO", "SEQUENCE", "GENEPIO", "MESH"},
    "CELL_TYPE": {"CL", "CLO", "MESH"},
    "SAMPLE_METHOD": {"OBI", "NCIT", "MESH"},
    "LAB_METHOD": {"OBI", "NCIT", "ERO", "MESH"},
    "DATA_ANALYSIS": {"STATO", "OBI", "EDAM", "NCIT"},
    "PATHWAY": {"GO", "WIKIPATHWAYS", "REACTOME", "CHEBI"},
    "EXPERIMENTAL_METHOD": {"OBI", "ERO", "NCIT"},
    "STUDY_DESIGN": {"OBI", "SNOMEDCT", "NCIT"},
    "GENOMICS": {"OBI", "SO", "NCIT", "MESH"},
    "CLINICAL": {"SNOMEDCT", "NCIT", "LOINC", "MESH"},
}

# ── Noisy vocabularies (penalize in confidence) ──
NOISY = {"MEDDRA", "ICD9CM", "RCD", "CPT", "LNC"}

# ── Thresholds ──
EXACT_MATCH_FLOOR = 0.85

# ── API keys (from environment) ──
UMLS_API_KEY = os.environ.get("UMLS_API_KEY", "")
BIOPORTAL_API_KEY = os.environ.get("BIOPORTAL_API_KEY", "")
ENTREZ_API_KEY = os.environ.get("ENTREZ_API_KEY", "")
ENTREZ_EMAIL = os.environ.get("ENTREZ_EMAIL", "microbiome.cdm@gmail.com")
