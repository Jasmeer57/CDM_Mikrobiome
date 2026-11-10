"""LLM-based triple extraction for the Microbiome-CDM pipeline (EFRE-parity).

Upgraded from the original 560-line version to port EFRE's methodology
(src/efre/stages/extract_triples.py) for broad microbiome scope (not
IBD-specific). Key additions over the original:

  - 26 canonical predicates (was 14) via cdm_pipeline.quality.predicate_synonyms
  - Type-pair constraint matrix via cdm_pipeline.quality.type_constraints
    (102 valid (subject_type, object_type) pairs across 14 CDM entity types)
  - Per-paper entity ontology block injected into the prompt (top 40 per
    type) loaded from the production DB (entity_project_mentions table)
  - Section-aware chunking: paper text split into sections (ALL-CAPS
    headers), dropped sections (references/acknowledgments/...), each
    chunk ≤ 12k chars split at sentence boundaries so the LLM sees one
    contiguous section at a time with section_id stamped for provenance
  - 12+ per-triple quality checks (hard reject / soft penalty split):
    vague subject/object, garbled text, self-loop, list-dump entities,
    evidence mentions subj/obj, spliced evidence, evidence negates
    predicate, direction inversion (via type_constraints), differential
    diagnosis lists, bare noun phrases, predicate downgrade (hedge
    detection), knowledge override, merged taxa, intervention-treats-
    biomarker
  - Three independent confidence dimensions: confidence, clarity,
    relevance (EFRE ports all three; the original only had confidence)
  - Soft-issue penalty: 0.92 per credibility-affecting issue (was 0.85
    flat in the original — too aggressive, collapsed 6-issue triples
    below the 0.3 publishability floor)
  - Study metadata extraction (one LLM call per paper) — general
    population characteristics only (continent, country, sample_size,
    age_group, sex, study_type, ethnicity); IBD-specific fields from
    EFRE dropped per the broad-microbiome scope
  - Provenance stamps on every triple: extraction_run_id, prompt_version,
    model_version, section_id, chunk_index — so re-extractions are
    traceable and comparable across runs

Design decisions kept from the original extractor:
  - `think: false` — Qwen3 family burns generation budget on CoT otherwise
  - No `format: "json"` — Ollama JSON mode returns single object, not array
  - Multi-tier JSON parser (array → bracket-extract → stream-of-objects)
  - Verbatim evidence quotes (8-12 words) for source linking
  - `rationale` field forces LLM to state causal direction before JSON
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Set, Tuple

import requests

from pipeline.config import CDM_TYPES, CDM_OUTPUT_DIR
from pipeline.s08_kg_triples.predicate_synonyms import CANONICAL_PREDICATES, DIRECTIONAL_PREDICATES, HEDGE_WORDS, PREDICATE_SYNONYM_MAP, STRONG_EVIDENCE_WORDS, SYMMETRIC_PREDICATES, normalize_predicate
from pipeline.s08_kg_triples.type_constraints import ALL_PREDICATES, TYPE_PAIR_CONSTRAINTS, check_inverted, get_valid_predicates, is_valid_triple, validate_and_fix

logger = logging.getLogger(__name__)

# ── CDM entity types (14) ──
CDM_ENTITY_TYPES: List[str] = list(CDM_TYPES)
CDM_ENTITY_TYPE_SET: Set[str] = set(CDM_TYPES)

# ── Canonical predicates (26) — imported from type_constraints ──
CDM_RELATION_TYPES: List[str] = sorted(ALL_PREDICATES)

# ── Ollama defaults ──
DEFAULT_MODEL = "qwen3.5:9b"
_raw_ollama_host = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
if not _raw_ollama_host.startswith("http://") and not _raw_ollama_host.startswith("https://"):
    _raw_ollama_host = f"http://{_raw_ollama_host}"
DEFAULT_BASE_URL = _raw_ollama_host
NO_THINKING = (
    "You are a knowledge graph constructor. Do not show your reasoning. "
    "Return ONLY the JSON array requested."
)
MAX_CHARS = 28000  # legacy cap kept for the no-sections fallback path
NUM_CTX = int(os.environ.get("OLLAMA_NUM_CTX", "16384"))
NUM_PREDICT = int(os.environ.get("OLLAMA_NUM_PREDICT", "8192"))
TIMEOUT = 600
MAX_RETRIES = 5
CHUNK_MAX_CHARS = 12000  # per-chunk cap for section-aware extraction

# ── Provenance ──
PROMPT_VERSION = "mcdm-extractor-v2-efre-parity"
DEFAULT_DB_PATH = CDM_OUTPUT_DIR / "microbiome_cdm.db"

# ── Sections to drop from extraction (lower-cased labels) ──
DROP_SECTION_LABELS: Set[str] = {
    "references", "bibliography",
    "acknowledgments", "acknowledgement", "acknowledgments",
    "conflict of interest", "conflicts of interest", "disclosure",
    "conflict of interest statement", "conflicts of interest statement",
    "supplementary", "supplementary material", "supplementary data",
    "supplementary information", "supporting information",
    "figure legends", "table legends",
    "author contributions", "contributions",
    "data availability", "availability", "data availability statement",
    "abbreviations", "keywords",
    "copyright", "license", "footnote", "notes",
    "correspondence", "ethics statement", "ethical considerations",
    "ethical statement", "funding", "author information",
}

# ── Vague entity terms (reject as subject/object) ──
VAGUE_TERMS: Set[str] = {
    "protein", "proteins", "gene", "genes", "cell", "cells",
    "tissue", "tissues", "organism", "microbe", "microbes",
    "bacteria", "bacterium", "pathogen", "pathogens",
    "harmful bacteria", "beneficial bacteria", "good bacteria", "bad bacteria",
    "the microbiome", "the gut microbiome", "human gut microbiome",
    "unidentified host", "host cells", "unknown",
    "metabolite", "metabolites", "nutrient", "nutrients",
    "inflammatory response", "immune response",
    "disease activity", "clinical outcome", "outcome",
    "cancer", "cancer risk", "tumor", "tumour",
    "the disease", "the condition", "the patient", "the study",
    "the result", "the finding", "the effect", "the treatment",
}

# ── Negation detection for raw predicates ──
_NEGATION_PATTERN = re.compile(
    r"\b(not|never|without|non-?significant(ly)?|"
    r"fails?\s+to|failed\s+to|lack(s|ing)?\s+of|absence\s+of|"
    r"does\s*n[o']?t|did\s*n[o']?t|do\s*n[o']?t|"
    r"no\s+(significant\s+)?(effect|association|difference|change|relation(ship)?)s?\b)",
    re.IGNORECASE,
)


def _has_negation(raw: str) -> bool:
    """Detect negation cues in a raw predicate string (e.g. 'does_not_reduce')."""
    return bool(_NEGATION_PATTERN.search(raw.replace("_", " ")))


# ── Type fuzzy map: LLM-emitted types → 14 canonical CDM types ──
TYPE_FUZZY_MAP: Dict[str, str] = {
    # ORGANISM synonyms
    "MICROBE": "ORGANISM", "MICROBES": "ORGANISM", "MICROBIAL_TAXON": "ORGANISM",
    "BACTERIUM": "ORGANISM", "BACTERIA": "ORGANISM", "TAXON": "ORGANISM",
    "MICROBIOME": "ORGANISM", "MICROBIOTA": "ORGANISM",
    "ARCHAEON": "ORGANISM", "ARCHAEA": "ORGANISM",
    "FUNGI": "ORGANISM", "FUNGUS": "ORGANISM", "YEAST": "ORGANISM",
    "VIRUS": "ORGANISM", "VIROME": "ORGANISM", "PHAGE": "ORGANISM",
    "PATHOGEN": "ORGANISM", "PATHOGENS": "ORGANISM",
    "SPECIES": "ORGANISM", "STRAIN": "ORGANISM",
    # CHEMICAL synonyms
    "METABOLITE": "CHEMICAL", "METABOLITES": "CHEMICAL",
    "COMPOUND": "CHEMICAL", "MOLECULE": "CHEMICAL",
    "SCFA": "CHEMICAL", "SHORT_CHAIN_FATTY_ACID": "CHEMICAL",
    "SHORTCHAINFATTYACID": "CHEMICAL", "FATTY_ACID": "CHEMICAL",
    "LIPID": "CHEMICAL", "AMINO_ACID": "CHEMICAL", "AMINOACID": "CHEMICAL",
    "NUTRIENT": "CHEMICAL", "FOOD": "CHEMICAL", "FOOD_COMPONENT": "CHEMICAL",
    "DIETARY_PATTERN": "CHEMICAL", "DRUG": "CHEMICAL",
    "ANTIBIOTIC": "CHEMICAL", "PROBIOTIC": "CHEMICAL", "PREBIOTIC": "CHEMICAL",
    "SYNBIOTIC": "CHEMICAL", "SUPPLEMENT": "CHEMICAL",
    # DISEASE synonyms
    "CONDITION": "DISEASE", "DISORDER": "DISEASE", "ILLNESS": "DISEASE",
    "SYNDROME": "DISEASE", "INFECTION": "DISEASE",
    "PHENOTYPE": "DISEASE", "SYMPTOM": "DISEASE",
    # PROTEIN synonyms
    "ENZYME": "PROTEIN", "RECEPTOR": "PROTEIN", "CYTOKINE": "PROTEIN",
    "CHEMOKINE": "PROTEIN", "ANTIBODY": "PROTEIN",
    "IMMUNOGLOBULIN": "PROTEIN", "SIGNALING_MOLECULE": "PROTEIN",
    "TRANSCRIPTION_FACTOR": "PROTEIN", "KINASE": "PROTEIN",
    # DNA_RNA synonyms
    "GENE": "DNA_RNA", "GENES": "DNA_RNA",
    "RNA": "DNA_RNA", "MRNA": "DNA_RNA", "TRNA": "DNA_RNA",
    "RRNA": "DNA_RNA", "SEQUENCE": "DNA_RNA", "OLIGONUCLEOTIDE": "DNA_RNA",
    "GENETIC_VARIANT": "DNA_RNA", "ALLELE": "DNA_RNA",
    # CELL_TYPE synonyms
    "CELL": "CELL_TYPE", "CELLS": "CELL_TYPE",
    "IMMUNE_CELL": "CELL_TYPE", "T_CELL": "CELL_TYPE", "B_CELL": "CELL_TYPE",
    "EPITHELIAL_CELL": "CELL_TYPE", "TISSUE": "CELL_TYPE",
    # GENOMICS synonyms
    "GENOMICS_ENTITY": "GENOMICS", "GENOMIC_FEATURE": "GENOMICS",
    "MICROBIOME_FEATURE": "GENOMICS", "DIVERSITY": "GENOMICS",
    "ALPHA_DIVERSITY": "GENOMICS", "BETA_DIVERSITY": "GENOMICS",
    "ABUNDANCE": "GENOMICS", "COMPOSITION": "GENOMICS",
    # PATHWAY synonyms
    "SIGNALING_PATHWAY": "PATHWAY", "METABOLIC_PATHWAY": "PATHWAY",
    "BIOLOGICAL_PROCESS": "PATHWAY", "PROCESS": "PATHWAY",
    # LAB_METHOD synonyms
    "ASSAY": "LAB_METHOD", "TECHNIQUE": "LAB_METHOD",
    "MEASUREMENT": "LAB_METHOD", "TEST": "LAB_METHOD",
    # DATA_ANALYSIS synonyms
    "STATISTICAL_METHOD": "DATA_ANALYSIS", "STATISTICAL_TEST": "DATA_ANALYSIS",
    "ANALYSIS": "DATA_ANALYSIS", "ANALYTICAL_METHOD": "DATA_ANALYSIS",
    "METRIC": "DATA_ANALYSIS", "INDEX": "DATA_ANALYSIS", "SCORE": "DATA_ANALYSIS",
    # SAMPLE_METHOD synonyms
    "SAMPLING": "SAMPLE_METHOD", "SAMPLE_COLLECTION": "SAMPLE_METHOD",
    "SAMPLE_TYPE": "SAMPLE_METHOD", "SPECIMEN": "SAMPLE_METHOD",
    # CLINICAL synonyms
    "CLINICAL_OUTCOME": "CLINICAL", "OUTCOME": "CLINICAL",
    "BIOMARKER": "CLINICAL", "CLINICAL_MEASUREMENT": "CLINICAL",
    "CLINICAL_VARIABLE": "CLINICAL",
    # EXPERIMENTAL_METHOD synonyms
    "EXPERIMENT": "EXPERIMENTAL_METHOD", "EXPERIMENTAL_DESIGN": "EXPERIMENTAL_METHOD",
    # STUDY_DESIGN synonyms
    "STUDY": "STUDY_DESIGN", "STUDY_TYPE": "STUDY_DESIGN",
    "COHORT": "STUDY_DESIGN", "INTERVENTION": "STUDY_DESIGN",
    "HOST_FACTOR": "STUDY_DESIGN", "LOCATION": "STUDY_DESIGN",
}

# ── Type inference keywords (fallback when LLM omits/garbles type) ──
_TYPE_KW: List[Tuple[List[str], str]] = [
    (["disease", "syndrome", "colitis", "crohn", "ibd", "inflammation",
      "cancer", "tumor", "carcinoma", "infection", "diabetes", "obesity",
      "hypertension", "atherosclerosis", "asthma", "allergy", "celiac",
      "disorder", "condition"], "DISEASE"),
    (["lactobacillus", "bifidobacterium", "clostridium", "escherichia",
      "salmonella", "streptococcus", "staphylococcus", "pseudomonas",
      "helicobacter", "enterococcus", "bacteroides", "faecalibacterium",
      "akkermansia", "roseburia", "prevotella", "ruminococcus",
      "veillonella", "parabacteroides", "parasutterella",
      "eubacterium", "fusobacterium", "actinobacteria", "firmicutes",
      "bacteroidetes", "proteobacteria", "verrucomicrobia", "mycobacterium",
      "candida", "saccharomyces", "cryptococcus", "bacillus",
      "bacterium", "bacteria", "microbe", "microbial", "microbiota",
      "microbiome"], "ORGANISM"),
    (["metabolite", "acid", "bile", "scfa", "short-chain", "butyrate",
      "acetate", "propionate", "lactate", "succinate", "polyphenol",
      "flavonoid", "phenolic", "lipid", "fatty acid", "amino acid",
      "sugar", "carbohydrate", "glucose", "tryptophan", "drug",
      "antibiotic", "probiotic", "prebiotic", "supplement",
      "compound", "molecule"], "CHEMICAL"),
    (["gene", "protein", "receptor", "enzyme", "transcription",
      "tlr", "nrf2", "nf-kb", "tnf", "il-", "interleukin",
      "cytokine", "chemokine", "growth factor", "kinase",
      "phosphatase", "caspase", "mucin", "antibody"], "PROTEIN"),
    (["16s", "rrna", "amplicon", "gene variant", "allele",
      "mutation", "snp", "sequence"], "DNA_RNA"),
    (["t cell", "b cell", "macrophage", "dendritic", "neutrophil",
      "epithelial", "colonocyte", "enterocyte", "regulatory t",
      "cd4", "cd8", "th17", "treg"], "CELL_TYPE"),
    (["alpha diversity", "beta diversity", "diversity", "abundance",
      "composition", "richness", "evenness", "microbiome feature"], "GENOMICS"),
    (["pathway", "signaling", "cascade"], "PATHWAY"),
    (["assay", "pcr", "sequencing", "extraction", "chromatography",
      "mass spectrometry", "elisa", "western blot", "flow cytometry",
      "culture", "pcr"], "LAB_METHOD"),
    (["ancom", "lefse", "wilcoxon", "pca", "pcoa", "permanova",
      "linear discriminant", "machine learning", "regression",
      "correlation", "statistical", "analysis", "metric",
      "index", "score", "aitchison", "bray-curtis", "unifrac"], "DATA_ANALYSIS"),
    (["stool", "fecal", "biopsy", "sample collection", "specimen"], "SAMPLE_METHOD"),
    (["clinical outcome", "biomarker", "remission", "response",
      "viral load", "cd4 count", "calprotectin"], "CLINICAL"),
    (["rct", "cohort", "case-control", "cross-sectional", "case-report",
      "animal-model", "in-vitro", "review", "meta-analysis"], "STUDY_DESIGN"),
]

# Microbial genera for binomial detection
_BINOMIAL_GENUS: Set[str] = {
    "lactobacillus", "bifidobacterium", "clostridium", "escherichia",
    "salmonella", "streptococcus", "staphylococcus", "pseudomonas",
    "helicobacter", "enterococcus", "bacteroides", "faecalibacterium",
    "akkermansia", "roseburia", "prevotella", "ruminococcus",
    "veillonella", "parabacteroides", "parasutterella",
    "eubacterium", "fusobacterium", "mycobacterium",
    "candida", "saccharomyces", "cryptococcus", "bacillus",
}

# ── Differential-diagnosis patterns (correlational, not causal) ──
DIFFERENTIAL_DIAGNOSIS_PATTERNS = [
    r"\bdifferential\s+diagnos",
    r"\brul(e|ing)\s+out\b",
    r"\bconsider\s+exclud",
    r"\bmay\s+be\b.{0,40}\b(due to|caused by|diagnos)",
    r"\bshould\s+be\s+considered\b",
    r"\bmimic\b.{0,30}\b(disease|condition|infection)",
]

# ── Strong-predicate set for hedge-downgrade ──
_STRONG_PREDICATES: Set[str] = DIRECTIONAL_PREDICATES - {"encodes", "expresses"}

# ── Perception / qualified-language words for hedge-downgrade ──
_PERCEPTION_WORDS: Set[str] = {
    "perceived", "perceive", "perception", "thought to", "reported to",
    "reportedly", "hypothesized", "hypothesis", "presumably", "presumed",
    "believed", "alleged", "claimed to", "considered to", "assumed",
    "assumption", "according to", "described as", "viewed as", "seen as",
    "appears to", "seems to", "supposedly", "purportedly", "reputedly",
    "ostensibly", "would be", "might be", "could be", "may be",
    "were thought", "was thought", "is thought", "are thought",
    "patients reported", "self-reported", "subjective",
}

_QUALIFIED_WORDS: Set[str] = {
    "negative role", "positive role", "beneficial role", "protective role",
    "potential", "possible", "putative", "candidate",
    "partially", "somewhat", "marginally", "weakly",
    "not significantly", "not clearly", "not directly",
    "in some", "in certain", "in most", "in many",
    "depending on", "varies", "variable", "unclear", "uncertain",
    "remains to", "further studies", "needs further",
}

# ── Verb roots by canonical predicate (for evidence-negation check) ──
_VERB_ROOTS_BY_CANONICAL: Dict[str, List[str]] = defaultdict(list)
for _raw_pred, _canon_pred in PREDICATE_SYNONYM_MAP.items():
    if "_" not in _raw_pred and " " not in _raw_pred:
        _VERB_ROOTS_BY_CANONICAL[_canon_pred].append(_raw_pred)
# Also include the canonical predicates themselves as roots
for _p in ALL_PREDICATES:
    if _p not in _VERB_ROOTS_BY_CANONICAL:
        _VERB_ROOTS_BY_CANONICAL[_p].append(_p)


# ════════════════════════════════════════════════════════════════════
# Section parsing
# ════════════════════════════════════════════════════════════════════

# Section-header pattern: a line of 4+ uppercase letters/spaces/&/, alone
_SECTION_HEADER_RE = re.compile(r"^([A-Z][A-Z/&\s]{3,})\s*$")


def parse_sections(text: str) -> List[Dict]:
    """Split a paper's plain text into sections keyed by ALL-CAPS headers.

    Returns a list of dicts: {section_id, label, text, start_char, end_char}.
    Section headers are lines of 4+ uppercase letters (e.g. "INTRODUCTION",
    "MATERIALS AND METHODS"). Text before the first header is "ABSTRACT".
    """
    lines = text.splitlines()
    sections: List[Dict] = []
    current_label = "ABSTRACT"
    current_buf: List[str] = []
    current_start = 0
    char_pos = 0
    sid = 0

    def _flush(end_char: int) -> None:
        nonlocal current_buf, current_label, current_start, sid
        body = "\n".join(current_buf).strip()
        if body:
            sections.append({
                "section_id": f"s{sid}",
                "label": current_label,
                "text": body,
                "start_char": current_start,
                "end_char": end_char,
            })
            sid += 1
        current_buf = []

    for line in lines:
        line_stripped = line.strip()
        m = _SECTION_HEADER_RE.match(line_stripped) if line_stripped else None
        # Heuristic: header must be reasonably short and not contain lowercase
        is_header = (
            m is not None
            and len(line_stripped) <= 60
            and not any(c.islower() for c in line_stripped)
        )
        if is_header:
            _flush(char_pos)
            current_label = line_stripped.title()
            current_start = char_pos
            current_buf = []
        else:
            current_buf.append(line)
        char_pos += len(line) + 1  # +1 for the newline

    _flush(char_pos)
    return sections


@dataclass
class SectionChunk:
    """A contiguous chunk of paper text plus provenance metadata.

    Produced by iter_section_chunks so downstream callers can attribute
    evidence back to a specific section. section_id is the same across
    every chunk from a single section.
    """
    text: str
    section_id: str
    section_label: str
    char_start: int


def iter_section_chunks(
    sections: List[Dict],
    max_chars_per_chunk: int = CHUNK_MAX_CHARS,
) -> Iterator[SectionChunk]:
    """Yield one SectionChunk per surviving section, splitting long sections
    at sentence boundaries so no chunk contains a half-sentence.
    """
    for sec in sections:
        label = (sec.get("label") or "").lower().strip()
        if label in DROP_SECTION_LABELS:
            continue
        text = sec.get("text", "")
        if not text:
            continue
        sec_id = sec.get("section_id", "")
        base_char = sec.get("start_char", 0)
        if len(text) <= max_chars_per_chunk:
            yield SectionChunk(
                text=text, section_id=sec_id,
                section_label=sec.get("label", ""), char_start=base_char,
            )
            continue
        start = 0
        n = len(text)
        while start < n:
            end = min(n, start + max_chars_per_chunk)
            boundary = end
            for cand in range(end, max(start + max_chars_per_chunk // 2, start + 1), -1):
                if cand < n and text[cand - 1] in ".!?":
                    boundary = cand
                    break
            yield SectionChunk(
                text=text[start:boundary], section_id=sec_id,
                section_label=sec.get("label", ""),
                char_start=base_char + start,
            )
            start = boundary


# ════════════════════════════════════════════════════════════════════
# Type normalization
# ════════════════════════════════════════════════════════════════════

def normalize_type(raw: Optional[str]) -> Optional[str]:
    """Normalize a raw type string to one of the 14 canonical CDM types.

    Returns None if the type can't be mapped.
    """
    if not raw:
        return None
    t = raw.strip().upper().replace(" ", "_")
    if t in CDM_ENTITY_TYPE_SET:
        return t
    if t in TYPE_FUZZY_MAP:
        return TYPE_FUZZY_MAP[t]
    # Strip _ENTITY / _TYPE / _CLASS suffix and retry
    t_stripped = re.sub(r"_(ENTITY|TYPE|CLASS|SUBCLASS|SUBTYPE)$", "", t)
    if t_stripped in CDM_ENTITY_TYPE_SET:
        return t_stripped
    if t_stripped in TYPE_FUZZY_MAP:
        return TYPE_FUZZY_MAP[t_stripped]
    # Keyword containment (last-resort fallback)
    for keyword, mapped in [
        ("GENE", "DNA_RNA"), ("PROTEIN", "PROTEIN"), ("ENZYME", "PROTEIN"),
        ("RECEPTOR", "PROTEIN"), ("DISEASE", "DISEASE"), ("METABOLITE", "CHEMICAL"),
        ("IMMUNE", "CELL_TYPE"), ("TAXON", "ORGANISM"), ("BACTERIA", "ORGANISM"),
        ("MICROBIAL", "ORGANISM"), ("MICROBE", "ORGANISM"), ("PATHWAY", "PATHWAY"),
        ("NUTRIENT", "CHEMICAL"), ("INTERVENTION", "STUDY_DESIGN"),
        ("TREATMENT", "CLINICAL"), ("PHENOTYPE", "DISEASE"),
        ("BIOMARKER", "CLINICAL"), ("OUTCOME", "CLINICAL"),
        ("TISSUE", "CELL_TYPE"), ("FUNGI", "ORGANISM"), ("FUNGI", "ORGANISM"),
        ("VIROME", "ORGANISM"), ("PHAGE", "ORGANISM"),
        ("FATTY_ACID", "CHEMICAL"), ("LIPID", "CHEMICAL"),
        ("AMINO_ACID", "CHEMICAL"), ("ANTIBODY", "PROTEIN"),
        ("IMMUNOGLOBULIN", "PROTEIN"), ("ASSAY", "LAB_METHOD"),
        ("ANALYSIS", "DATA_ANALYSIS"), ("SAMPLE", "SAMPLE_METHOD"),
        ("EXPERIMENT", "EXPERIMENTAL_METHOD"), ("STUDY", "STUDY_DESIGN"),
        ("COHORT", "STUDY_DESIGN"),
    ]:
        if keyword in t:
            return mapped
    return None


def _infer_type_from_entity(entity_text: str) -> Optional[str]:
    """Infer a CDM type from entity text using keyword + binomial heuristics.

    Used when the LLM omits or garbles subject_type/object_type. Falls back
    to None if no signal fires — caller then leaves the type empty and the
    type-constraint validator will reject the triple.
    """
    if not entity_text:
        return None
    lc = entity_text.lower().strip()

    # Disease keywords (checked first to avoid "Crohn disease" → organism)
    for kw, mapped in _TYPE_KW:
        if any(k in lc for k in kw):
            return mapped

    # Genus/species binomial (e.g. "E. coli", "Lactobacillus rhamnosus")
    m = re.search(r"\b([A-Z][a-z]{2,})\s+([a-z]{2,})", entity_text)
    if m and (m.group(1).lower() in _BINOMIAL_GENUS or m.group(2).lower() in _BINOMIAL_GENUS):
        return "ORGANISM"
    if re.search(r"\b[A-Z]\.\s*[a-z]{3,}", entity_text):
        return "ORGANISM"

    return None


# ════════════════════════════════════════════════════════════════════
# Ontology block (per-paper entity injection)
# ════════════════════════════════════════════════════════════════════

def load_paper_entities_from_db(
    paper_id: str,
    db_path: Path = DEFAULT_DB_PATH,
) -> Dict[str, List[str]]:
    """Load the entities detected in a single paper from the production DB.

    Returns {entity_type: [term, term, ...]} with terms de-duplicated and
    truncated to a per-type cap by the caller (build_ontology_block).
    Returns {} if the DB or paper isn't found — extraction still works,
    just without the ontology-block context.
    """
    if not Path(db_path).exists():
        return {}
    try:
        con = sqlite3.connect(str(db_path))
        cur = con.cursor()
        cur.execute(
            """
            SELECT e.term, e.entity_type
            FROM entity_project_mentions m
            JOIN entities e ON e.id = m.entity_id
            WHERE m.project_id = ?
              AND e.term IS NOT NULL
              AND length(e.term) >= 2
            GROUP BY e.term, e.entity_type
            ORDER BY e.entity_type, COUNT(*) DESC
            """,
            (paper_id,),
        )
        rows = cur.fetchall()
        con.close()
    except sqlite3.Error as exc:
        logger.warning(f"[{paper_id}] DB entity load failed: {exc}")
        return {}

    by_type: Dict[str, List[str]] = defaultdict(list)
    seen_per_type: Dict[str, set] = defaultdict(set)
    for term, etype in rows:
        etype = (etype or "").upper().strip()
        if etype not in CDM_ENTITY_TYPE_SET:
            continue
        key = term.lower().strip()
        if not key or key in seen_per_type[etype]:
            continue
        seen_per_type[etype].add(key)
        by_type[etype].append(term.strip())
    return dict(by_type)


def build_ontology_block(
    entities_by_type: Dict[str, List[str]],
    max_per_type: int = 40,
) -> str:
    """Format the per-paper ontology block for the LLM prompt."""
    if not entities_by_type:
        return ""
    lines = ["## Paper Ontology (entities detected in this paper)\n"]
    for etype in sorted(entities_by_type.keys()):
        sample = entities_by_type[etype][:max_per_type]
        lines.append(f"  {etype}: {', '.join(sample)}")
    return "\n".join(lines)


# ════════════════════════════════════════════════════════════════════
# Prompt construction
# ════════════════════════════════════════════════════════════════════

def build_system_prompt(entities_by_type: Optional[Dict[str, List[str]]] = None) -> str:
    types_str = "\n".join(f"- {t}" for t in CDM_ENTITY_TYPES)
    ontology_block = build_ontology_block(entities_by_type or {})
    preds_str = ", ".join(CDM_RELATION_TYPES)

    return f"""You are a knowledge graph constructor for biomedical microbiome research.
Extract factual BIOLOGICAL and BIOMEDICAL (subject, predicate, object) triples from the text.

IMPORTANT: Only extract relations between BIOLOGICAL/MEDICAL entities.
DO NOT extract metadata relations about the study itself (e.g. "researchers conducted", "study published", "authors found").
DO NOT use entity types outside the valid list below — especially never "PERSON", "RESEARCHER", "AUTHOR", "INSTITUTION", "JOURNAL".

{ontology_block}

Valid entity types:
{types_str}

Valid predicates (use the MOST SPECIFIC one the evidence supports):
{preds_str}

CRITICAL PREDICATE CHOICE GUIDANCE (direction matters — subject is the AGENT, object is the TARGET):
- "X causes Y" / "X leads to Y" / "X triggers Y" / "X induces Y" / "X promotes Y" → causes (X=agent, Y=outcome)
- "X increases Y" / "X raises Y" / "X upregulates Y" / "X enhances Y" → increases
- "X decreases Y" / "X reduces Y" / "X lowers Y" / "X downregulates Y" → decreases
- "X activates Y" / "X stimulates Y" → activates
- "X inhibits Y" / "X blocks Y" / "X suppresses Y" / "X represses Y" → inhibits
- "X regulates Y" (mechanistic) → regulates
- "X modulates Y" / "X alters Y" / "X changes Y" / "X modifies Y" → modulates
- "X prevents Y" / "X protects against Y" / "X is prophylaxis for Y" → prevents
- "X improves Y" / "X ameliorates Y" / "X alleviates Y" / "X mitigates Y" → improves
- "X treats Y" / "X is used to treat Y" → treats (X=drug/therapy, Y=disease)
- "X is treated by Y" / "Y treats X" → treated_by (X=disease, Y=drug/therapy)
- "X metabolizes Y" / "X transforms Y" / "X degrades Y" → metabolizes
- "X binds Y" (physical interaction: protein-protein, receptor-ligand) → binds
- "X predicts Y" (biomarker / risk factor) → predicts
- "X produces Y" / "X synthesizes Y" → produces (X=organism, Y=metabolite)
- "Y is produced by X" → produced_by (Y=metabolite, X=organism)
- "X disrupts Y" (antibiotic disrupting microbiome) → disrupts (X=agent, Y=system affected)
- "X is depleted in Y" (organism reduced in disease/condition) → depleted_in
  (X=ORGANISM depleted, Y=DISEASE/CONDITION where depletion occurs)
- "X is enriched in Y" (organism increased in disease/condition) → enriched_in
  (X=ORGANISM enriched, Y=DISEASE/CONDITION where enrichment occurs)
- "X encodes Y" (gene encodes protein) → encodes (X=DNA_RNA, Y=PROTEIN)
- "X expresses Y" (organism expresses gene/protein) → expresses (X=organism, Y=gene/protein)
- "X is part of pathway Y" → part_of_pathway
- "X participates in Y" (process/study) → participates_in
- "X is implicated in Y" (factor implicated in disease) → implicated_in
- "X is associated with Y" (general, no direction, no mechanism) → associated_with — LAST RESORT
- "X co-occurs with Y" (statistical co-occurrence only) → co_occurs_with

DIRECTION RULES (CRITICAL — getting direction wrong makes the triple worthless):
- depleted_in: subject MUST be the ORGANISM that is reduced, object MUST be the DISEASE/CONDITION.
  "Faecalibacterium is depleted in Crohn's disease" → (Faecalibacterium, depleted_in, Crohn's disease)
  "PBC patients have decreased Clostridiales" → (Clostridiales, depleted_in, primary biliary cholangitis)
- enriched_in: subject MUST be the ORGANISM that is increased, object MUST be the DISEASE/CONDITION.
  "Proteobacteria is enriched in HIV-1 infection" → (Proteobacteria, enriched_in, HIV-1 infection)
- treats: subject MUST be the DRUG/THERAPY/AGENT, object MUST be the DISEASE.
- treated_by: subject MUST be the DISEASE, object MUST be the DRUG/THERAPY/AGENT.
- produces: subject MUST be the PRODUCER (organism), object MUST be what is PRODUCED (metabolite/chemical).
- encodes: subject MUST be the GENE, object MUST be the PROTEIN.
- The object of depleted_in/enriched_in MUST be a DISEASE, CLINICAL condition, or patient group.
  NEVER use ORGANISM, GENOMICS, or CELL_TYPE as the object.

HEDGED LANGUAGE IS STILL DIRECTIONAL. Do NOT default to associated_with just because the
sentence is hedged. "Butyrate may reduce inflammation" → decreases (NOT associated_with).
"Vitamin D is associated with a reduced risk of C. diff" → prevents (NOT associated_with).
Use associated_with ONLY for pure co-occurrence with no implied direction or mechanism.

Rules:
1. EVERY triple MUST include subject_type and object_type from the valid entity types listed above.
2. predicate MUST be one of the valid predicates above. If none fit, do NOT create a new predicate — skip.
3. evidence must be a DIRECT QUOTE copied word-for-word from the text (at least 8-12 consecutive words).
   No paraphrasing, no rewording. If the exact words don't appear, pick a different sentence.
4. confidence: 0.0-1.0 — how sure the paper is of the statement (explicitness).
5. clarity: 0.0-1.0 — how unambiguously the evidence states THIS specific relationship.
   1.0 = states it directly and completely; 0.3-0.5 = partly inferred from context.
6. relevance: 0.0-1.0 — how central this finding is to the paper's own main topic.
   1.0 = one of the paper's primary findings; 0.3 = mentioned in passing.
7. Extract EVERY biological relationship you can find — aim for 15-25 triples per section.
8. subject and object must each be a single specific entity — never a list. If the text
   describes multiple related entities ("X increases Y, Z, and W"), emit ONE triple per entity.
9. rationale: one short sentence explaining why THIS predicate and THIS direction (subject→object)
   was chosen. State the causal direction explicitly to catch cause/effect reversal.

Return ONLY a JSON array — no markdown, no extra text.
Examples:
[
  {{"subject": "butyrate", "predicate": "decreases", "object": "intestinal inflammation",
    "subject_type": "CHEMICAL", "object_type": "DISEASE",
    "evidence": "butyrate decreases intestinal inflammation by inhibiting HDAC activity in colonocytes",
    "confidence": 0.8, "clarity": 0.9, "relevance": 0.7,
    "rationale": "text states butyrate decreases inflammation via HDAC inhibition, direction is butyrate→inflammation"}},
  {{"subject": "Faecalibacterium prausnitzii", "predicate": "depleted_in", "object": "Crohn's disease",
    "subject_type": "ORGANISM", "object_type": "DISEASE",
    "evidence": "F. prausnitzii is significantly depleted in Crohn's disease patients compared to healthy controls",
    "confidence": 0.9, "clarity": 1.0, "relevance": 0.9,
    "rationale": "text explicitly states organism is reduced in disease, direction is organism→disease"}},
  {{"subject": "metformin", "predicate": "disrupts", "object": "gut microbiota",
    "subject_type": "CHEMICAL", "object_type": "ORGANISM",
    "evidence": "metformin treatment alters the gut microbiota composition in patients with type 2 diabetes",
    "confidence": 0.75, "clarity": 0.85, "relevance": 0.8,
    "rationale": "text states drug changes/disrupts microbiome composition, direction is drug→microbiota"}},
  {{"subject": "Proteobacteria", "predicate": "enriched_in", "object": "HIV-1 infection",
    "subject_type": "ORGANISM", "object_type": "DISEASE",
    "evidence": "more abundant Proteobacteria were observed in HIV+ individuals",
    "confidence": 0.9, "clarity": 0.9, "relevance": 0.85,
    "rationale": "text states organism is increased (enriched) in disease, direction is organism→disease"}},
  {{"subject": "NOD2", "predicate": "activates", "object": "NF-kB pathway",
    "subject_type": "DNA_RNA", "object_type": "PATHWAY",
    "evidence": "NOD2 activation triggers the NF-kB signaling pathway",
    "confidence": 0.85, "clarity": 1.0, "relevance": 0.75,
    "rationale": "text explicitly states NOD2 triggers (activates) the pathway, not the reverse"}}
]
"""


def build_user_prompt(chunk_text: str, section_label: str = "") -> str:
    label_hint = f" (section: {section_label})" if section_label else ""
    return f"""Extract factual triples from the paper text below{label_hint}.

PAPER TEXT:
{chunk_text}

Return ONLY a JSON array of triple objects:"""


# ════════════════════════════════════════════════════════════════════
# Ollama call + JSON parsing
# ════════════════════════════════════════════════════════════════════

def call_ollama(
    paper_text: str,
    model: str = DEFAULT_MODEL,
    base_url: str = DEFAULT_BASE_URL,
    temperature: float = 0,
    paper_id: str = "",
    system_prompt: Optional[str] = None,
) -> List[Dict]:
    """Call Ollama and return parsed list of triple dicts.

    Uses /api/chat endpoint which properly supports `think: false` for Qwen3 models.
    """
    if system_prompt is None:
        system_prompt = build_system_prompt()
    user = build_user_prompt(paper_text)

    endpoint = f"{base_url.rstrip('/')}/api/chat"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": f"{NO_THINKING}\n\n{system_prompt}"},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "think": False,
        "format": None,
        "options": {
            "temperature": temperature,
            "top_p": 0.9,
            "seed": 42,
            "num_ctx": NUM_CTX,
            "num_predict": NUM_PREDICT,
        },
    }

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.post(endpoint, json=payload, timeout=TIMEOUT)
            if resp.status_code == 200:
                data = resp.json()
                msg = data.get("message", {})
                raw = msg.get("content", "").strip()
                if not raw:
                    logger.warning(f"[{paper_id}] Empty response (attempt {attempt})")
                    time.sleep(5 * attempt)
                    continue
                return parse_json_response(raw, paper_id)
            logger.error(f"[{paper_id}] Ollama HTTP {resp.status_code}: {resp.text[:200]}")
            time.sleep(10 * attempt)
        except requests.exceptions.Timeout:
            logger.warning(f"[{paper_id}] Timeout (attempt {attempt}/{MAX_RETRIES})")
            time.sleep(10)
        except requests.exceptions.ConnectionError as e:
            logger.warning(f"[{paper_id}] Connection error (attempt {attempt}/{MAX_RETRIES}): {e}")
            time.sleep(10 * attempt)
        except Exception as e:
            logger.error(f"[{paper_id}] Unexpected error (attempt {attempt}): {e}")
            time.sleep(5 * attempt)

    logger.error(f"[{paper_id}] All {MAX_RETRIES} attempts failed")
    return []


def parse_json_response(raw: str, paper_id: str = "") -> List[Dict]:
    """Multi-tier JSON parser (array → bracket-extract → stream-of-objects)."""
    if not raw:
        return []
    raw = raw.strip()

    # Tier 1: direct parse
    try:
        result = json.loads(raw)
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            triples = result.get("triples") or result.get("results") or result.get("data")
            if isinstance(triples, list):
                return triples
            return [result]
    except json.JSONDecodeError:
        pass

    # Tier 2: extract first [...] block
    match = re.search(r"\[", raw)
    if match:
        start = match.start()
        depth = 0
        end = -1
        in_string = False
        escape = False
        for i in range(start, len(raw)):
            c = raw[i]
            if escape:
                escape = False
                continue
            if c == "\\":
                escape = True
                continue
            if c == '"' and not escape:
                in_string = not in_string
                continue
            if in_string:
                continue
            if c == "[":
                depth += 1
            elif c == "]":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break

        if end > start:
            fragment = repair_json(raw[start:end])
            try:
                result = json.loads(fragment)
                if isinstance(result, list):
                    return result
            except json.JSONDecodeError:
                pass

    # Tier 3: stream-of-objects
    objects: List[Dict] = []
    decoder = json.JSONDecoder()
    idx = 0
    while idx < len(raw):
        if raw[idx] == "{":
            try:
                obj, consumed = decoder.raw_decode(raw, idx)
                if isinstance(obj, dict):
                    objects.append(obj)
                idx += consumed
                continue
            except json.JSONDecodeError:
                pass
        idx += 1

    if objects:
        return objects

    logger.warning(f"[{paper_id}] Failed to parse any JSON from LLM response ({len(raw)} chars)")
    return []


def repair_json(s: str) -> str:
    """Best-effort repair of common LLM JSON issues."""
    s = re.sub(r"```json\s*", "", s)
    s = re.sub(r"```\s*$", "", s)
    s = re.sub(r",\s*]", "]", s)
    s = re.sub(r",\s*}", "}", s)
    return s


# ════════════════════════════════════════════════════════════════════
# Per-triple quality checks (hard reject / soft penalty)
# ════════════════════════════════════════════════════════════════════

def _is_vague(text: str) -> bool:
    return text.lower().strip() in VAGUE_TERMS


def _is_garbled(text: str) -> bool:
    """Detect truly garbled text, not just long biomedical names."""
    if not text or not text.strip():
        return True
    t = text.strip()
    if any(c in t for c in ["▪", "□", "■", "★", "\x00", "\ufffd"]):
        return True
    special = re.findall(r"[^a-zA-Z0-9\s\-\(\)\[\]\.,;:/αβγδεζηθ°%μ]", t)
    if special and len(special) / max(len(t), 1) > 0.4:
        return True
    if len(t) > 200 and "." in t and len(t.split(".")) > 2:
        return True
    return False


def _evidence_mentions_subj_obj(subj: str, obj: str, evidence: str) -> bool:
    """Check whether the evidence quote mentions the subject and/or object."""
    ev = (evidence or "").lower()
    if len(ev) < 10:
        return False
    s = (subj or "").lower().strip()
    o = (obj or "").lower().strip()

    if s[:60] in ev or o[:60] in ev:
        return True

    def _content_overlap(entity: str, evidence_lc: str) -> bool:
        words = [w for w in entity.split() if len(w) > 3]
        if len(words) < 2:
            return False
        matches = sum(1 for w in words if w in evidence_lc)
        return matches >= min(2, len(words))

    if _content_overlap(s, ev) or _content_overlap(o, ev):
        return True

    # Prefix match for single-word entities (butyrate in butyric, IL6 in interleukin-6)
    if len(s.split()) == 1 and len(s) > 5 and s[:5] in ev:
        return True
    if len(o.split()) == 1 and len(o) > 5 and o[:5] in ev:
        return True

    # Acronym match
    s_acr = "".join(c for c in s if c.isupper() and c.isalpha())
    if len(s_acr) >= 2 and s_acr.lower() in ev:
        return True
    o_acr = "".join(c for c in o if c.isupper() and c.isalpha())
    if len(o_acr) >= 2 and o_acr.lower() in ev:
        return True
    return False


def _is_differential_diagnosis(evidence: str, predicate: str) -> bool:
    ev_lower = evidence.lower()
    if any(re.search(pat, ev_lower) for pat in DIFFERENTIAL_DIAGNOSIS_PATTERNS):
        return True
    causal_preds = {"causes", "induces", "drives", "triggers", "produces"}
    if predicate in causal_preds and len(evidence.split(",")) > 3:
        return True
    return False


def _is_bare_noun_phrase(evidence: str) -> bool:
    ev = evidence.strip()
    words = ev.split()
    if len(words) > 6:
        return False
    has_verb = bool(re.search(
        r"\b(is|are|was|were|has|have|had|shows?|showed|increases?|decreases?|"
        r"regulates?|produces?|inhibits?|activates?|reduces?|induces?|associated|"
        r"found|observed|detected|measured|treated|caused|resulted|mediated|"
        r"promotes?|suppresses?|expressed|plays?|leads?)\b",
        ev, re.I,
    ))
    return not has_verb


def _is_spliced_evidence(evidence: str) -> bool:
    """Detect evidence that splices non-adjacent fragments with a mid-string ellipsis."""
    ev = (evidence or "").strip()
    if "..." not in ev and "[...]" not in ev:
        return False
    stripped = re.sub(r"^[\[\s]*(\.\.\.|\[\.\.\.\])\s*", "", ev)
    stripped = re.sub(r"\s*(\.\.\.|\[\.\.\.\])\s*[\]\s]*$", "", stripped)
    return "..." in stripped or "[...]" in stripped


def _check_evidence_negates_predicate(predicate: str, evidence: str) -> Optional[str]:
    """Detect when the quoted evidence negates the very verb the predicate asserts."""
    pred = (predicate or "").lower().strip()
    ev = (evidence or "").lower()
    if not ev or not pred:
        return None
    for root in _VERB_ROOTS_BY_CANONICAL.get(pred, []):
        pattern = (
            rf"\b(?:not|never|without|fails?\s+to|failed\s+to|"
            rf"does\s*n[o']?t|did\s*n[o']?t|do\s*n[o']?t)\b(?:\s+\w+){{0,3}}\s+{re.escape(root)}\b"
        )
        if re.search(pattern, ev):
            return (f"evidence negates the predicate's own verb ('{root}'): "
                    f"asserts '{pred}' but quotes a negated claim")
    return None


def _downgrade_predicate(predicate: str, evidence: str) -> Optional[Tuple[str, str]]:
    """Detect an assertive predicate backed only by hedged/perception evidence.

    Returns (new_predicate, reason) if a downgrade is warranted, else None.
    The caller is responsible for actually mutating the triple — this
    function is pure so it can be tested in isolation.
    """
    pred = (predicate or "").lower().strip()
    ev = (evidence or "").lower()
    if pred not in _STRONG_PREDICATES:
        return None
    all_weak = HEDGE_WORDS | _PERCEPTION_WORDS | _QUALIFIED_WORDS
    if not any(w in ev for w in all_weak):
        return None
    # Only downgrade if there's no strong-evidence signal in the text
    if any(s in ev for s in STRONG_EVIDENCE_WORDS):
        return None
    return ("associated_with", "hedged_or_perception_evidence")


def _check_merged_taxon(subject: str) -> Optional[str]:
    """Detect merged non-existent entities like 'Bacteroides Geobacillus'."""
    words = subject.split()
    if len(words) >= 2:
        caps = [w for w in words if w and w[0].isupper()]
        if len(caps) >= 2 and all(len(w) > 3 for w in caps):
            # Only flag if at least one is a known genus (avoid false positives
            # on legitimate compound names like "Crohn's disease")
            known = [w for w in caps if w.lower() in _BINOMIAL_GENUS]
            if len(known) >= 2:
                return f"merged taxa: '{subject}' looks like two genera concatenated"
    return None


def _check_intervention_treats_biomarker(
    subject_type: str, predicate: str, object_type: str,
) -> Optional[str]:
    """CHEMICAL/drug → treats → CLINICAL/BIOMARKER is almost always wrong."""
    st = (subject_type or "").upper()
    ot = (object_type or "").upper()
    pred = (predicate or "").lower().strip()
    intervention_types = {"CHEMICAL"}
    nonsense_types = {"CLINICAL", "CELL_TYPE", "GENOMICS"}
    if st in intervention_types and ot in nonsense_types and pred == "treats":
        return f"{st} → treats → {ot} — interventions treat diseases, not {ot.lower()}"
    return None


# ════════════════════════════════════════════════════════════════════
# Main validation + normalization
# ════════════════════════════════════════════════════════════════════

def _quality_check(
    subject: str, predicate: str, object_: str,
    subject_type: str, object_type: str, evidence: str,
) -> Tuple[List[str], List[str]]:
    """Run every per-triple quality heuristic; return (hard_issues, soft_issues)."""
    hard: List[str] = []
    soft: List[str] = []

    if _is_vague(subject):
        hard.append(f"vague subject: '{subject}'")
    if _is_vague(object_):
        hard.append(f"vague object: '{object_}'")

    if subject and object_ and subject.lower().strip() == object_.lower().strip():
        hard.append("self-loop: subject equals object")

    if _is_garbled(subject):
        hard.append(f"garbled subject: '{subject[:60]}'")
    if _is_garbled(object_):
        hard.append(f"garbled object: '{object_[:60]}'")

    if not _evidence_mentions_subj_obj(subject, object_, evidence):
        soft.append("evidence does not mention subject or object")

    if _is_differential_diagnosis(evidence, predicate):
        soft.append("evidence appears to be from differential diagnosis list, not causal claim")

    if _is_bare_noun_phrase(evidence):
        soft.append("evidence is a bare noun phrase, not a full sentence")

    if _is_spliced_evidence(evidence):
        hard.append("evidence splices non-adjacent text fragments (mid-quote ellipsis)")

    ev_neg = _check_evidence_negates_predicate(predicate, evidence)
    if ev_neg:
        hard.append(ev_neg)

    downgrade = _downgrade_predicate(predicate, evidence)
    if downgrade:
        soft.append(f"predicate downgraded to associated_with: {downgrade[1]}")

    ib_treats_bm = _check_intervention_treats_biomarker(subject_type, predicate, object_type)
    if ib_treats_bm:
        hard.append(ib_treats_bm)

    merged = _check_merged_taxon(subject)
    if merged:
        hard.append(merged)
    merged = _check_merged_taxon(object_)
    if merged:
        hard.append(merged)

    # Improvement-predicate vs decline evidence
    ev_lower = evidence.lower()
    improvement_preds = {"treats", "improves", "prevents"}
    if predicate in improvement_preds:
        decline_words = {"decreased", "reduced", "lower", "worsened", "declined"}
        pred_root = predicate.rstrip("es")
        for dw in decline_words:
            if dw in ev_lower and not dw.startswith(pred_root):
                hard.append("evidence suggests decrease/worsening but predicate claims improvement — may be inverted")
                break

    return hard, soft


def validate_and_normalize(
    triples: List[Dict],
    min_confidence: float = 0.3,
    min_clarity: float = 0.3,
    min_relevance: float = 0.3,
) -> Tuple[List[Dict], List[Dict]]:
    """Validate triples and map to canonical forms. Returns (valid, flagged).

    Uses two-tier validation:
    - HARD issues → triple goes to flagged (rejected)
    - SOFT issues → triple passes with confidence penalty and annotation

    Pulls the type-pair constraint matrix from cdm_pipeline.quality.type_constraints
    (auto-swap inverted triples, demote invalid predicates to associated_with).
    """
    valid: List[Dict] = []
    flagged: List[Dict] = []

    CORE_FIELDS = {"subject", "predicate", "object"}
    META_FIELDS = {"evidence", "confidence", "clarity", "relevance"}

    for t in triples:
        hard_issues: List[str] = []
        soft_issues: List[str] = []

        if not isinstance(t, dict):
            flagged.append({"raw": str(t)[:200], "issues": ["not a dict"]})
            continue

        # 1. Core fields required
        missing_core = CORE_FIELDS - set(t.keys())
        if missing_core:
            hard_issues.append(f"missing core fields: {missing_core}")
            t["validation_issues"] = hard_issues
            flagged.append(t)
            continue

        # 1b. Metadata fields default rather than reject
        missing_meta = META_FIELDS - set(t.keys())
        if missing_meta:
            if "evidence" in missing_meta:
                t["evidence"] = ""
                soft_issues.append("evidence_missing")
            if "confidence" in missing_meta:
                t["confidence"] = 0.5
                soft_issues.append("confidence_defaulted_to_0.5")
            if "clarity" in missing_meta:
                t["clarity"] = 0.5
                soft_issues.append("clarity_defaulted_to_0.5")
            if "relevance" in missing_meta:
                t["relevance"] = 0.5
                soft_issues.append("relevance_defaulted_to_0.5")

        subject = str(t.get("subject", "")).strip()
        predicate_raw = str(t.get("predicate", "")).strip()
        obj = str(t.get("object", "")).strip()
        evidence = str(t.get("evidence", "")).strip()

        # 2. Non-empty subject/object
        if not subject or not obj:
            hard_issues.append("empty subject or object")
            t["validation_issues"] = hard_issues
            flagged.append(t)
            continue

        # 2b. Reject list-dump entities
        MAX_COMMAS = 4
        MAX_CHARS_ENT = 120
        for field in ("subject", "object"):
            val = str(t.get(field, ""))
            if val.count(",") > MAX_COMMAS or len(val) > MAX_CHARS_ENT:
                hard_issues.append(f"{field}_looks_like_list_dump: {len(val)} chars, {val.count(',')} commas")
        if hard_issues:
            t["validation_issues"] = hard_issues
            flagged.append(t)
            continue

        if len(subject) < 2 or len(obj) < 2:
            hard_issues.append("subject or object too short")
            t["validation_issues"] = hard_issues
            flagged.append(t)
            continue

        # 3. Normalize predicate (HARD if negated, SOFT default to associated_with if unmappable)
        if _has_negation(predicate_raw):
            hard_issues.append(f"negated predicate would invert polarity: '{predicate_raw[:60]}'")
            t["predicate_canonical"] = None
            t["predicate_raw"] = predicate_raw
            t["validation_issues"] = hard_issues
            flagged.append(t)
            continue

        canonical_pred = normalize_predicate(predicate_raw)
        if canonical_pred not in ALL_PREDICATES:
            # normalize_predicate returned an unmappable string — default to associated_with
            t["predicate_raw"] = predicate_raw
            canonical_pred = "associated_with"
            soft_issues.append(f"predicate_unmappable_to_associated_with: '{predicate_raw[:60]}'")
        else:
            # Check if it was remapped from a synonym (not already canonical)
            if predicate_raw.lower().strip() != canonical_pred:
                t["predicate_raw"] = predicate_raw
        t["predicate_canonical"] = canonical_pred

        # 4. Normalize types
        raw_st = str(t.get("subject_type", "")).strip()
        raw_ot = str(t.get("object_type", "")).strip()
        canonical_st = normalize_type(raw_st) if raw_st else None
        canonical_ot = normalize_type(raw_ot) if raw_ot else None

        if canonical_st is None:
            inferred = _infer_type_from_entity(subject)
            if inferred:
                canonical_st = inferred
                soft_issues.append(f"inferred subject_type: '{raw_st}' -> '{canonical_st}'")
            else:
                soft_issues.append("unable to infer subject_type from entity text")
        if canonical_ot is None:
            inferred = _infer_type_from_entity(obj)
            if inferred:
                canonical_ot = inferred
                soft_issues.append(f"inferred object_type: '{raw_ot}' -> '{canonical_ot}'")
            else:
                soft_issues.append("unable to infer object_type from entity text")

        t["subject_type_canonical"] = canonical_st or ""
        t["object_type_canonical"] = canonical_ot or ""

        # Hard reject if either type is still missing/invalid
        if canonical_st is None or canonical_st not in CDM_ENTITY_TYPE_SET:
            hard_issues.append(f"invalid subject_type: '{raw_st}'")
        if canonical_ot is None or canonical_ot not in CDM_ENTITY_TYPE_SET:
            hard_issues.append(f"invalid object_type: '{raw_ot}'")
        if hard_issues:
            t["validation_issues"] = hard_issues
            flagged.append(t)
            continue

        # 5. Validate evidence (SOFT)
        if not evidence:
            soft_issues.append("evidence_empty")
        elif len(evidence) < 10:
            soft_issues.append(f"evidence_short:{len(evidence)}_chars")

        # 6. Validate confidence/clarity/relevance (SOFT)
        try:
            conf = float(t.get("confidence", 0))
            if conf < min_confidence:
                soft_issues.append(f"low confidence: {conf}")
        except (ValueError, TypeError):
            soft_issues.append(f"invalid confidence: {t.get('confidence')}")
        try:
            clar = float(t.get("clarity", 0))
            if clar < min_clarity:
                soft_issues.append(f"low clarity: {clar}")
        except (ValueError, TypeError):
            soft_issues.append(f"invalid clarity: {t.get('clarity')}")
        try:
            rel = float(t.get("relevance", 0))
            if rel < min_relevance:
                soft_issues.append(f"low relevance: {rel}")
        except (ValueError, TypeError):
            soft_issues.append(f"invalid relevance: {t.get('relevance')}")

        # 7. Quality checks (hard/soft split)
        qc_hard, qc_soft = _quality_check(
            subject=subject, predicate=canonical_pred, object_=obj,
            subject_type=canonical_st, object_type=canonical_ot, evidence=evidence,
        )
        hard_issues.extend(qc_hard)
        soft_issues.extend(qc_soft)

        # 8. Type-pair constraint validation (auto-fix: swap / demote / flag)
        fix = validate_and_fix(
            subject=subject, subject_type=canonical_st,
            predicate=canonical_pred,
            object=obj, object_type=canonical_ot,
            evidence=evidence,
        )
        if not fix["valid"]:
            hard_issues.append(fix["fix_reason"] or "type-pair constraint violated")
        else:
            if fix["fix_action"] == "swapped":
                subject, obj = fix["subject"], fix["object"]
                canonical_st, canonical_ot = fix["subject_type"], fix["object_type"]
                t["subject"], t["object"] = subject, obj
                t["subject_type_canonical"], t["object_type_canonical"] = canonical_st, canonical_ot
                soft_issues.append(f"auto-swapped: {fix['fix_reason']}")
            elif fix["fix_action"] == "demoted":
                if not t.get("predicate_original"):
                    t["predicate_original"] = canonical_pred
                canonical_pred = fix["predicate"]
                t["predicate_canonical"] = canonical_pred
                soft_issues.append(f"predicate demoted: {fix['fix_reason']}")
            elif fix["fix_action"] == "flagged":
                soft_issues.append(f"type-pair flagged: {fix['fix_reason']}")

        # HARD issues → reject
        if hard_issues:
            t["validation_issues"] = hard_issues
            if soft_issues:
                t["warnings"] = soft_issues
            flagged.append(t)
            continue

        # SOFT issues only → annotate + penalize confidence
        if soft_issues:
            t["warnings"] = soft_issues
            penalty_issues = sum(
                1 for s in soft_issues
                if any(kw in s for kw in [
                    "evidence_empty", "evidence_missing", "evidence_short",
                    "confidence_defaulted", "predicate_unmappable",
                    "type_unmappable", "type_inferred", "inferred",
                    "unable to infer",
                    "low clarity", "low relevance",
                    "predicate downgraded",
                ])
            )
            penalty = 0.92 ** penalty_issues
            t["confidence"] = float(t.get("confidence", 0.5)) * penalty

        valid.append(t)

    # Deduplicate by (subject, predicate_canonical, object)
    seen: Set[Tuple[str, str, str]] = set()
    deduped: List[Dict] = []
    for t in valid:
        s = str(t.get("subject", "")).lower().strip()
        p = str(t.get("predicate_canonical", "")).lower().strip()
        o = str(t.get("object", "")).lower().strip()
        key = (s, p, o)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(t)

    return deduped, flagged


# ════════════════════════════════════════════════════════════════════
# Sentence segmentation + evidence linking
# ════════════════════════════════════════════════════════════════════

def segment_sentences(text: str) -> List[Dict]:
    """Simple regex sentence segmentation for evidence linking."""
    sentences: List[Dict] = []
    sid = 0
    pattern = re.compile(r"([.!?]+)(?:\s+|\n)")
    pos = 0
    for m in pattern.finditer(text):
        end = m.end()
        sentence_text = text[pos:end].strip()
        if len(sentence_text) > 15:
            sentences.append({
                "sentence_id": f"sent{sid}",
                "text": sentence_text,
                "char_start": pos,
                "char_end": end,
            })
            sid += 1
        pos = end
    if pos < len(text):
        remainder = text[pos:].strip()
        if len(remainder) > 15:
            sentences.append({
                "sentence_id": f"sent{sid}",
                "text": remainder,
                "char_start": pos,
                "char_end": len(text),
            })
    return sentences


def locate_evidence(
    evidence: str, sentences: List[Dict],
) -> Optional[Dict]:
    """Link an evidence quote back to a source sentence."""
    if not evidence or not sentences:
        return None
    ev_lower = evidence.lower().strip()

    # Tier 1: exact substring
    for s in sentences:
        if ev_lower in s["text"].lower():
            return {
                "sentence_id": s["sentence_id"],
                "char_start": s["char_start"],
                "char_end": s["char_end"],
            }

    # Tier 2: fuzzy match (SequenceMatcher ≥ 0.85)
    best_ratio = 0.0
    best_sentence: Optional[Dict] = None
    for s in sentences:
        ratio = SequenceMatcher(None, ev_lower, s["text"].lower()).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_sentence = s
    if best_ratio >= 0.85 and best_sentence is not None:
        return {
            "sentence_id": best_sentence["sentence_id"],
            "char_start": best_sentence["char_start"],
            "char_end": best_sentence["char_end"],
        }
    return None


# ════════════════════════════════════════════════════════════════════
# Study metadata (one LLM call per paper)
# ════════════════════════════════════════════════════════════════════

STUDY_METADATA_PROMPT = """Extract the study population characteristics from this
paper's text, if stated. This is asked ONCE per paper (not per finding) — these
are facts about who/where the study was conducted, not about any specific
relationship. Every triple extracted from this paper will inherit these values,
so be precise.

Return ONLY a JSON array with exactly one object:
[{"continent": "continent the study population was recruited from, e.g. "
   "'Europe', 'Asia', 'North America' — empty string if not stated",
  "country": "country the study population was recruited from, e.g. 'United States', "
   "'Italy', 'multi-center European' — empty string if not stated",
  "sample_size": integer number of study participants/subjects, or null if not stated,
  "age_group": "life-stage group as stated, one of: pediatric, adolescent, adult, "
   "elderly, mixed, all — or the specific age range in the paper if it doesn't map "
   "to a life-stage, e.g. '18-65 years', 'mean 34.2±12.1'; empty string if not stated",
  "sex": "one of: male, female, mixed, not_stated — as stated for the study population",
  "study_type": "one of: RCT, cohort, case-control, cross-sectional, case-report, "
   "animal-model, in-vitro, review, meta-analysis, other — use 'not_stated' if unclear",
  "ethnicity": "the ethnicity/race of the study population as stated in the paper, e.g. "
   "'Caucasian', 'Asian', 'Black/African American', 'Hispanic', 'multi-ethnic', "
   "'Ashkenazi Jewish' — single combined string if multiple groups are named, "
   "e.g. 'Caucasian, African American'; empty string if not stated"}]

Only extract what is explicitly stated in the text — do not guess or infer
population characteristics that aren't written down. Empty string / null /
"not_stated" are all valid, correct answers when the paper doesn't say.

CRITICAL: NEVER return an empty array. ALWAYS return exactly one object with
all 7 keys present, even if most values are empty/null/"not_stated". Look
carefully at the Methods, Results, and Abstract sections for sample size,
country, sex, age, and ethnicity information.

PAPER TEXT (first section, usually contains methods/population details):
{text}

Return ONLY the JSON array with exactly one object:"""


def extract_study_metadata(
    paper_text: str,
    paper_id: str,
    model: str = DEFAULT_MODEL,
    base_url: str = DEFAULT_BASE_URL,
) -> Dict:
    """One LLM call per paper for study-level population characteristics.

    Returns a dict with keys: continent, country, sample_size, age_group,
    sex, study_type, ethnicity. Values are empty/null/'not_stated' when the
    paper doesn't say. This is broad-microbiome scope (no IBD-specific fields).
    """
    # Use the first 25k chars to reach Methods in primary research papers
    text_window = paper_text[:25000] if len(paper_text) > 25000 else paper_text
    prompt = STUDY_METADATA_PROMPT.replace("{text}", text_window)

    endpoint = f"{base_url.rstrip('/')}/api/chat"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": NO_THINKING},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "think": False,
        "format": None,
        "options": {
            "temperature": 0, "seed": 42, "top_p": 0.9,
            "num_ctx": NUM_CTX, "num_predict": 4096,
        },
    }

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.post(endpoint, json=payload, timeout=TIMEOUT)
            if resp.status_code == 200:
                data = resp.json()
                raw = (data.get("message", {}) or {}).get("content", "").strip()
                if not raw:
                    time.sleep(3 * attempt)
                    continue
                parsed = parse_json_response(raw, paper_id)
                if parsed and isinstance(parsed[0], dict):
                    return parsed[0]
                # Single dict fallback
                try:
                    obj = json.loads(raw)
                    if isinstance(obj, dict):
                        return obj
                except json.JSONDecodeError:
                    pass
            time.sleep(5 * attempt)
        except Exception as exc:
            logger.warning(f"[{paper_id}] study metadata attempt {attempt} failed: {exc}")
            time.sleep(5 * attempt)

    logger.warning(f"[{paper_id}] study metadata extraction failed — using defaults")
    return {
        "continent": "", "country": "", "sample_size": None,
        "age_group": "", "sex": "not_stated",
        "study_type": "not_stated", "ethnicity": "",
    }


# ════════════════════════════════════════════════════════════════════
# Main entry point
# ════════════════════════════════════════════════════════════════════

def extract_triples_from_paper(
    paper_text: str,
    paper_id: str,
    model: str = DEFAULT_MODEL,
    base_url: str = DEFAULT_BASE_URL,
    db_path: Optional[Path] = None,
    entities_by_type: Optional[Dict[str, List[str]]] = None,
    extract_metadata: bool = True,
) -> Dict:
    """Extract triples from a single paper using EFRE-parity extraction.

    Pipeline:
      1. Parse paper text into sections, drop irrelevant ones (references, ...)
      2. Load per-paper entity ontology from DB (if not passed in)
      3. Build system prompt with ontology block + 26-predicate vocabulary
      4. For each chunk (≤ 12k chars, sentence-bounded):
         - Build user prompt with chunk text + section label
         - Call Ollama, parse JSON triples
      5. Validate all raw triples: hard/soft checks + type-pair constraints
      6. Stamp provenance (extraction_run_id, prompt_version, model_version,
         section_id, chunk_index) + study metadata on each surviving triple
      7. Link evidence to sentences (best-effort)
      8. Deduplicate by (subject, predicate_canonical, object)

    Args:
      paper_text: full text of the paper
      paper_id: project accession (e.g. PRJDB10485)
      model: Ollama model name
      base_url: Ollama base URL
      db_path: path to microbiome_cdm.db (defaults to CDM_OUTPUT_DIR)
      entities_by_type: pre-loaded {type: [terms]} (skips DB load if provided)
      extract_metadata: if True, run the extra study-metadata LLM call

    Returns:
      {
        "paper_id": str,
        "model": str,
        "extraction_run_id": str,
        "prompt_version": str,
        "n_chunks": int,
        "n_triples_raw": int,
        "n_triples_valid": int,
        "n_triples_flagged": int,
        "triples": List[Dict],
        "flagged": List[Dict],
        "study_metadata": Dict,
        "elapsed_s": float,
        "timestamp": str,
      }
    """
    t0 = time.time()
    extraction_run_id = str(uuid.uuid4())
    db_path = db_path or DEFAULT_DB_PATH

    # 1. Sections
    sections = parse_sections(paper_text)
    if not sections:
        # Fallback: treat whole text as one ABSTRACT section
        sections = [{
            "section_id": "s0", "label": "ABSTRACT",
            "text": paper_text, "start_char": 0, "end_char": len(paper_text),
        }]

    # 2. Per-paper entity ontology
    if entities_by_type is None:
        entities_by_type = load_paper_entities_from_db(paper_id, db_path)

    # 3. System prompt (built once, reused across chunks)
    system_prompt = build_system_prompt(entities_by_type)

    # 4. Extract per-chunk
    all_raw: List[Dict] = []
    chunks = list(iter_section_chunks(sections))
    n_chunks = len(chunks)
    for chunk_idx, chunk in enumerate(chunks):
        chunk_triples = call_ollama(
            paper_text=chunk.text,
            model=model, base_url=base_url,
            paper_id=f"{paper_id}[chunk {chunk_idx + 1}/{n_chunks}]",
            system_prompt=system_prompt,
        )
        for t in chunk_triples:
            if isinstance(t, dict):
                t["_chunk_index"] = chunk_idx
                t["_section_id"] = chunk.section_id
                t["_section_label"] = chunk.section_label
        all_raw.extend(chunk_triples)

    # 5. Validate
    valid_triples, flagged = validate_and_normalize(all_raw)

    # 6. Study metadata (one extra LLM call)
    study_metadata: Dict = {}
    if extract_metadata:
        study_metadata = extract_study_metadata(
            paper_text, paper_id, model=model, base_url=base_url,
        )

    # 7. Stamp provenance + link evidence + finalize triples
    finalized: List[Dict] = []
    for t in valid_triples:
        subject = str(t.get("subject", "")).strip()
        predicate = str(t.get("predicate_canonical", "")).strip().lower()
        obj = str(t.get("object", "")).strip()
        subject_type = str(t.get("subject_type_canonical", "")).strip().upper()
        object_type = str(t.get("object_type_canonical", "")).strip().upper()
        evidence = str(t.get("evidence", "")).strip()
        confidence = float(t.get("confidence", 0.5))
        try:
            confidence = max(0.0, min(1.0, confidence))
        except (ValueError, TypeError):
            confidence = 0.5
        try:
            clarity = float(t.get("clarity", 0.5))
        except (ValueError, TypeError):
            clarity = 0.5
        try:
            relevance = float(t.get("relevance", 0.5))
        except (ValueError, TypeError):
            relevance = 0.5

        record = {
            "subject": subject,
            "predicate": predicate,
            "object": obj,
            "subject_type": subject_type,
            "object_type": object_type,
            "evidence": evidence,
            "confidence": round(confidence, 4),
            "clarity": round(clarity, 4),
            "relevance": round(relevance, 4),
            "rationale": str(t.get("rationale", "")).strip(),
            "paper_id": paper_id,
            "model": model,
            "extraction_run_id": extraction_run_id,
            "prompt_version": PROMPT_VERSION,
            "model_version": model,
            "section_id": t.get("_section_id"),
            "section_label": t.get("_section_label"),
            "chunk_index": t.get("_chunk_index"),
            "predicate_raw": t.get("predicate_raw"),
            "predicate_original": t.get("predicate_original"),
            "warnings": t.get("warnings", []),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        # Attach study metadata (paper-level)
        for k, v in (study_metadata or {}).items():
            record[f"study_{k}"] = v

        # Best-effort sentence linking
        chunk_text = ""
        for c in chunks:
            if c.section_id == t.get("_section_id"):
                chunk_text = c.text
                break
        if chunk_text:
            sentences = segment_sentences(chunk_text)
            ev_loc = locate_evidence(evidence, sentences)
            if ev_loc:
                record["sentence_id"] = ev_loc["sentence_id"]
                record["evidence_start_offset"] = ev_loc["char_start"]
                record["evidence_end_offset"] = ev_loc["char_end"]
            else:
                record["sentence_id"] = None
                record["evidence_start_offset"] = None
                record["evidence_end_offset"] = None
        else:
            record["sentence_id"] = None
            record["evidence_start_offset"] = None
            record["evidence_end_offset"] = None

        finalized.append(record)

    elapsed = time.time() - t0

    return {
        "paper_id": paper_id,
        "model": model,
        "extraction_run_id": extraction_run_id,
        "prompt_version": PROMPT_VERSION,
        "n_chunks": n_chunks,
        "n_triples_raw": len(all_raw),
        "n_triples_valid": len(finalized),
        "n_triples_flagged": len(flagged),
        "triples": finalized,
        "flagged": flagged,
        "study_metadata": study_metadata,
        "elapsed_s": round(elapsed, 1),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
