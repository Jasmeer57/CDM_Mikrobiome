"""Confidence scoring and canonical mapping resolution."""
from rapidfuzz import fuzz

from ..config import PREFERRED, NOISY, VOCAB_PRIORITY


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
        onto = ontology.upper()
        if onto in PREFERRED.get(cdm_type, set()):
            score += 0.05
        elif onto in NOISY and onto not in PREFERRED.get(cdm_type, set()):
            score -= 0.15
    return max(0.0, min(1.0, score))


def resolve_canonical(candidates, cdm_type):
    """Pick the canonical mapping from all candidates by vocab priority + confidence."""
    if not candidates:
        return None, []
    priority = VOCAB_PRIORITY.get(cdm_type, [])

    def sort_key(c):
        try:
            rank = priority.index(c["ontology_name"])
        except ValueError:
            rank = len(priority)
        return (rank, -c["confidence"])

    ranked = sorted(candidates, key=sort_key)
    canonical = ranked[0]
    others = ranked[1:]
    return canonical, others
