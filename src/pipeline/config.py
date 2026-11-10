"""Shared configuration: paths, CDM types, vocabulary priorities."""
import os
from pathlib import Path

from pipeline.paths import REPO_ROOT as _PATHS_REPO_ROOT
from cdm_pipeline import paths as _paths

# ── Paths ──
# Repo root and dataset locations come from cdm_pipeline.paths, which supports
# env-var overrides (CDM_PAPERS_TXT, ...). Defaults are unchanged.
REPO_ROOT = _PATHS_REPO_ROOT
PAPERS_DIR = _paths.papers_txt()


def _env_path(name, default):
    """Path from an env var, falling back to ``default``.

    Downstream stages (dedup -> mapping -> CDM build) each read their own
    directory from this module, so a re-scoped rebuild has to redirect all
    three together.  Letting them be overridden keeps the default 444-paper
    layout intact while a 452 build writes to a separate tree.
    """
    value = os.environ.get(name)
    return Path(value).expanduser() if value else default


NER_OUTPUT_DIR = _env_path(
    "CDM_NER_OUTPUT_DIR", REPO_ROOT / "paper" / "_multi_ner_runs" / "ner_output")
CDM_OUTPUT_DIR = _env_path("CDM_CDM_OUTPUT_DIR", NER_OUTPUT_DIR.parent / "cdm_output")
MAPPING_DIR = _env_path("CDM_MAPPING_DIR", NER_OUTPUT_DIR.parent / "mapping")
BENCHMARK_DIR = _env_path(
    "CDM_BENCHMARK_DIR", NER_OUTPUT_DIR.parent / "benchmarks")


def _env_path_list(name):
    """Comma- or newline-separated path list from an env var, or ``[]``.

    Relative entries resolve against :data:`REPO_ROOT` (not the CWD) so a build
    behaves the same whether it is launched from the repo root or a Slurm spool
    directory.
    """
    raw = os.environ.get(name, "").strip()
    if not raw:
        return []
    out = []
    for chunk in raw.replace("\n", ",").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        p = Path(chunk).expanduser()
        out.append(p if p.is_absolute() else REPO_ROOT / p)
    return out


def _env_csv_set(name):
    """Comma- or newline-separated string set from an env var, or ``frozenset()``."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return frozenset()
    return frozenset(c.strip() for c in raw.replace("\n", ",").split(",") if c.strip())


# The per-model mention CSVs that feed dedup (stage 2) and the CDM corpus
# (stage 5) are one contract read in two places, so they are resolved once here.
# Unset means the historical five-file 444-paper layout, keeping that build
# byte-reproducible; a re-scoped build points CDM_NER_CSVS at its own files.
NER_CSVS = _env_path_list("CDM_NER_CSVS")

# Paper IDs to drop at read time, for builds narrower than the source files.
# The 452-paper analysed scope is 453 on disk minus HMPAPER_000372 (an HTML
# redirect stub: zero catalogue records, zero body chars).  Section-level NER
# artifacts still carry its handful of stray spans, so the exclusion has to
# happen here rather than by rewriting those read-only files.  Unset = no filter,
# so the 444 build is unaffected.  A full rebuild sets
# ``CDM_EXCLUDE_PAPERS=HMPAPER_000372``.
EXCLUDE_PAPERS = _env_csv_set("CDM_EXCLUDE_PAPERS")
LLM_TERMS_DIR = REPO_ROOT / "pipelines/llm_terms"
_VENV_CANDIDATES = [
    REPO_ROOT / "pipelines/llm_terms" / "venv" / "bin" / "python",        # Linux
    REPO_ROOT / "spacy_terms" / ".venv39" / "Scripts" / "python.exe",  # Windows
]
# Preferred venv for NER model execution (tries llm_terms first, then spacy_terms).
# Named HISTORICALLY as SPACY_VENV_PYTHON but actually prefers the llm_terms venv.
NER_VENV_PYTHON = next((p for p in _VENV_CANDIDATES if p.exists()), _VENV_CANDIDATES[0])
# Backward-compatible alias
SPACY_VENV_PYTHON = NER_VENV_PYTHON
BIOPROJECT_JSON = _paths.bioproject_export()

# ── CDM entity types (14) ──
CDM_TYPES = [
    "ORGANISM", "CHEMICAL", "DISEASE", "PROTEIN", "DNA_RNA", "CELL_TYPE",
    "GENOMICS", "PATHWAY", "LAB_METHOD", "DATA_ANALYSIS", "SAMPLE_METHOD",
    "CLINICAL", "EXPERIMENTAL_METHOD", "STUDY_DESIGN",
]

# ── Vocabulary priority for canonical mapping ──
# Type-conditional: each CDM type maps to an ordered list of preferred vocabularies.
# resolve_canonical() picks the first match; mappers should reject vocabs not in this list
# for the given type to enforce type-appropriate mapping.
VOCAB_PRIORITY = {
    "ORGANISM":       ["NCBITAXON", "GTDB", "SNOMEDCT", "MESH", "NCIT", "UMLS"],
    "PROTEIN":        ["PR", "GO", "CHEBI", "MESH", "HGNC", "NCBITAXON", "UMLS"],
    "CHEMICAL":       ["CHEBI", "MESH", "RXNORM", "SNOMEDCT", "NCIT", "UMLS"],
    "DISEASE":        ["MONDO", "DOID", "SNOMEDCT", "ICD9CM", "ICD10", "OMIM", "MESH", "HP", "UMLS"],
    "DNA_RNA":        ["SO", "SEQUENCE", "GENEPIO", "MESH", "NCIT", "UMLS"],
    "CELL_TYPE":      ["CL", "CLO", "MESH", "NCIT", "UMLS"],
    "SAMPLE_METHOD":  ["OBI", "NCIT", "MESH", "UMLS"],
    "LAB_METHOD":     ["OBI", "NCIT", "ERO", "MESH", "UMLS"],
    "DATA_ANALYSIS":  ["STATO", "OBI", "EDAM", "NCIT", "UMLS"],
    "PATHWAY":        ["GO", "WIKIPATHWAYS", "REACTOME", "CHEBI", "UMLS"],
    "EXPERIMENTAL_METHOD": ["OBI", "ERO", "NCIT", "UMLS"],
    "STUDY_DESIGN":   ["OBI", "SNOMEDCT", "NCIT", "UMLS"],
    "GENOMICS":       ["OBI", "SO", "NCIT", "MESH", "UMLS"],
    "CLINICAL":       ["SNOMEDCT", "NCIT", "LOINC", "MESH", "UMLS"],
}

# ── Preferred vocabularies per CDM type (for confidence scoring) ──
PREFERRED = {
    "ORGANISM":       {"NCBITAXON", "GTDB", "SNOMEDCT", "MESH"},
    "PROTEIN":        {"PR", "GO", "CHEBI", "MESH"},
    "CHEMICAL":       {"CHEBI", "MESH", "RXNORM", "SNOMEDCT"},
    "DISEASE":        {"MONDO", "DOID", "SNOMEDCT", "ICD9CM", "ICD10", "OMIM", "MESH"},
    "DNA_RNA":        {"SO", "SEQUENCE", "GENEPIO", "MESH"},
    "CELL_TYPE":      {"CL", "CLO", "MESH"},
    "SAMPLE_METHOD":  {"OBI", "NCIT", "MESH"},
    "LAB_METHOD":     {"OBI", "NCIT", "ERO", "MESH"},
    "DATA_ANALYSIS":  {"STATO", "OBI", "EDAM", "NCIT"},
    "PATHWAY":        {"GO", "WIKIPATHWAYS", "REACTOME", "CHEBI"},
    "EXPERIMENTAL_METHOD": {"OBI", "ERO", "NCIT"},
    "STUDY_DESIGN":   {"OBI", "SNOMEDCT", "NCIT"},
    "GENOMICS":       {"OBI", "SO", "NCIT", "MESH"},
    "CLINICAL":       {"SNOMEDCT", "NCIT", "LOINC", "MESH"},
}

# ── Noisy vocabularies (penalize in confidence) ──
# NOTE: "LNC" is the Bioregistry prefix for LOINC. Both "LNC" and "LOINC" are
# accepted here so the noisy penalty fires regardless of which form a mapper returns.
NOISY = {"MEDDRA", "ICD9CM", "RCD", "CPT", "LNC", "LOINC"}

# ── Thresholds ──
EXACT_MATCH_FLOOR = 0.85

# ── API keys (from environment) ──
UMLS_API_KEY = os.environ.get("UMLS_API_KEY", "")
BIOPORTAL_API_KEY = os.environ.get("BIOPORTAL_API_KEY", "")
ENTREZ_API_KEY = os.environ.get("ENTREZ_API_KEY", "")
ENTREZ_EMAIL = os.environ.get("ENTREZ_EMAIL", "microbiome.cdm@gmail.com")
