"""Confidence scoring and canonical mapping resolution."""
from rapidfuzz import fuzz

from ..config import PREFERRED, NOISY, VOCAB_PRIORITY

# Vocab alias normalization: map common alternate names to a single canonical form
# so that NOISY and PREFERRED checks fire regardless of which alias a mapper returns.
_VOCAB_ALIASES = {
    # Clinical / general
    "LNC": "LOINC",
    "SNOMEDCT_US": "SNOMEDCT",
    "SNOMED": "SNOMEDCT",
    "MSH": "MESH",
    "RXN": "RXNORM",
    # Taxonomy
    "NCBI_TAXON": "NCBITAXON",
    # BioPortal ontology name variants (hyphen vs. no-hyphen, abbreviations)
    "FBBT": "FB-BT",
    "FBCV": "FB-CV",
    "WBBT": "WB-BT",
    "BPT": "BP",
    "REPRODUCEME": "REPRODUCE-ME",
    "BCIO": "BCI-O",
    "CCONT": "CCON",
    "APOLLO_SV": "APOLLO-SV",
    "SCHEMAORG_HTTPS": "SCHEMAORG_HTTP",
}


def _normalize_vocab(vocab_name: str) -> str:
    """Normalize a vocabulary name to a canonical form."""
    return _VOCAB_ALIASES.get(vocab_name.upper(), vocab_name.upper())


def _confidence(entity, label, cdm_type, ontology):
    """Compute a confidence score [0,1] for an entity-label mapping."""
    if not label:
        return 0.5
    a = " ".join(entity.lower().split())
    b = " ".join(label.lower().split())
    if a == b:
        return 1.0
    sim = fuzz.token_set_ratio(a, b) / 100.0
    score = 0.3 + 0.65 * sim
    if ontology:
        onto = _normalize_vocab(ontology)
        preferred = {_normalize_vocab(v) for v in PREFERRED.get(cdm_type, set())}
        noisy = {_normalize_vocab(v) for v in NOISY}
        if onto in preferred:
            score += 0.05
        elif onto in noisy:
            score -= 0.15
    return max(0.0, min(1.0, score))


def resolve_canonical(candidates, cdm_type):
    """Pick the canonical mapping from all candidates by vocab priority + confidence.

    Candidates whose vocabulary is not in VOCAB_PRIORITY for the given type
    are deprioritized (sorted to the end) but not discarded, to preserve coverage
    when no type-appropriate mapping exists.
    """
    if not candidates:
        return None, []
    priority = [_normalize_vocab(v) for v in VOCAB_PRIORITY.get(cdm_type, [])]

    def sort_key(c):
        onto = _normalize_vocab(c["ontology_name"])
        try:
            rank = priority.index(onto)
        except ValueError:
            rank = len(priority)
        return (rank, -c["confidence"])

    ranked = sorted(candidates, key=sort_key)
    canonical = ranked[0]
    others = ranked[1:]
    return canonical, others
