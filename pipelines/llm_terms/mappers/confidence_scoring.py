"""
Shared confidence scoring for entity->ontology mapping candidates.

Replaces the old per-mapper logic (bare 0.5 floor + `entity_name in label`
naive substring check) which produced false positives like:
    "intestinal pH"  in  "Intestinal phase of gastric secretory response"
        -> True (literal chars "intestinal ph" line up as a prefix), scored 0.7
This uses token-set fuzzy matching (order/duplicate-insensitive word overlap)
instead of raw substring containment, so partial-word coincidences like the
one above score low instead of being credited as a "partial match".

A small ontology-domain bonus/penalty is layered on top: CDM entity types
have known-good and known-noisy ontology sources (e.g. an ORGANISM term
landing in FlyBase-derived gene-symbol entries, or a DATA_ANALYSIS term
landing in a clinical-coding ontology like MEDDRA/ICD9CM/RCD, is usually a
false positive even when the string similarity looks plausible).
"""
from typing import Optional

from rapidfuzz import fuzz

_embedder = None
_embed_cache = {}


def _get_embedder():
    """Lazy-load the sentence embedder (only paid for if embedding scoring is actually used)."""
    global _embedder
    if _embedder is None:
        from sentence_transformers import SentenceTransformer
        _embedder = SentenceTransformer("all-MiniLM-L6-v2")
    return _embedder


def _cosine(u, v) -> float:
    import numpy as np
    num = float(np.dot(u, v))
    denom = float(np.linalg.norm(u) * np.linalg.norm(v))
    return num / denom if denom else 0.0


def embedding_similarity(a: str, b: str) -> float:
    """Cosine similarity between two strings' sentence embeddings, 0.0-1.0 (clamped).

    Catches semantic equivalences token overlap misses entirely (synonyms,
    abbreviation expansions with no shared substring) - e.g. "gut microbiota"
    vs "intestinal microbiome" share zero tokens but are the same concept.
    Cached per string since the same entity/label pairs repeat heavily
    across a corpus this size.
    """
    model = _get_embedder()
    key_a, key_b = a.strip().lower(), b.strip().lower()
    if key_a not in _embed_cache:
        _embed_cache[key_a] = model.encode(key_a, normalize_embeddings=True)
    if key_b not in _embed_cache:
        _embed_cache[key_b] = model.encode(key_b, normalize_embeddings=True)
    sim = _cosine(_embed_cache[key_a], _embed_cache[key_b])
    return max(0.0, min(1.0, sim))

# Ontologies that tend to produce true positives for a given CDM entity type.
PREFERRED_ONTOLOGIES = {
    "ORGANISM": {"NCBITAXON", "SNOMEDCT", "MESH"},
    "GENE": {"HGNC", "NCBIGENE", "GENE", "SO"},
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

# Ontologies that are frequently wrong for entity types outside their home
# domain (drug/procedure billing codes, gene-symbol collision sources).
NOISY_FOR_NON_MATCHING_TYPES = {"MEDDRA", "ICD9CM", "RCD", "CPT", "LNC", "LOINC"}


def _normalize(s: str) -> str:
    return " ".join(s.strip().lower().split())


DISEASE_CLASS_MARKERS = {"disorder", "disease", "syndrome", "deficiency", "-associated", "associated"}


WORD_MATCH_THRESHOLD = 72  # rapidfuzz.fuzz.ratio, per individual word pair
# Tuned against real cases: catches morphological variants (propionate/propionic=73.7,
# glycolysis/glycolytic=80.0, bacterial/bacteria=94.1, resistant/resistance=84.2)
# while rejecting coincidental-prefix false positives (ph/phase=57.1) AND
# same-root-different-entity collisions (kendall/astley-kendall=66.7 - the
# "Kendall correlations" -> "Astley-Kendall syndrome" false match).


def _fuzzy_word_jaccard(a_words: set, b_words: set) -> float:
    """Jaccard-like overlap, but a word in `a` counts as "shared" if it has a
    close per-word character match in `b` (ratio >= WORD_MATCH_THRESHOLD), not
    just an exact match.

    This is what makes "propionate" match "propionic" (ratio ~84, same root,
    -ate/-ic suffix variant - a real match) while still keeping "ph" from
    matching "phase" (ratio ~57, different words that happen to share a
    prefix - the exact false-positive pattern that broke the naive substring
    check in the first place). Whole-string fuzzy ratio can't tell these
    apart; per-word ratio can, because it only ever compares word to word,
    never lets one short word "absorb" credit from an entire unrelated label.
    """
    if not a_words or not b_words:
        return 0.0
    matched = 0
    b_remaining = set(b_words)
    for wa in a_words:
        if wa in b_remaining:
            matched += 1
            b_remaining.discard(wa)
            continue
        best = None
        for wb in b_remaining:
            r = fuzz.ratio(wa, wb)
            if r >= WORD_MATCH_THRESHOLD and (best is None or r > best[1]):
                best = (wb, r)
        if best:
            matched += 1
            b_remaining.discard(best[0])
    return matched / len(a_words | b_words)


def score_match(entity_name: str, entity_type: str, candidate_label: Optional[str],
                 ontology_name: Optional[str] = None, use_embeddings: bool = False) -> float:
    """Score a candidate ontology match for an extracted entity, 0.0-1.0.

    entity_name: the extracted term (e.g. "intestinal pH")
    entity_type: CDM type (e.g. "CLINICAL")
    candidate_label: the ontology concept's preferred label, if known.
        If the caller doesn't have the label yet (some APIs only give a
        relevance-ranked ID without the label at scoring time), pass None -
        this falls back to a flat 0.5 "unverified" score, same as before,
        so callers that can't provide a label don't regress.
    ontology_name: source ontology acronym, for the domain bonus/penalty.
    use_embeddings: OFF by default. Tried blending in general-purpose
        (MiniLM) sentence-embedding cosine similarity as a synonym-catcher,
        but it measured *topical* similarity, not entity identity, and
        made known false positives score HIGHER (e.g. "intestinal pH" vs
        "Intestinal phase of gastric secretory response" went from 0.79
        token-only to 0.87 blended) - a domain-specific biomedical embedding
        model (SapBERT etc.) might do better, generic MiniLM does not.
        Left here disabled rather than deleted in case that's revisited.
    """
    if not candidate_label:
        return 0.5

    a = _normalize(entity_name)
    b = _normalize(candidate_label)

    if a == b:
        return 1.0

    # Strict WORD-level Jaccard, not rapidfuzz's token_set_ratio - token_set_ratio
    # still does character-level fuzzy reconstruction under the hood, so it was
    # fooled the same way the old substring check was (e.g. "ph" character-overlaps
    # with "phase", inflating "intestinal pH" vs "Intestinal phase..." to 0.92).
    # A real word-set Jaccard treats "ph" and "phase" as the distinct tokens they are.
    a_words = set(a.replace("-", " ").split())
    b_words = set(b.replace("-", " ").split())
    similarity = _fuzzy_word_jaccard(a_words, b_words)

    if use_embeddings:
        try:
            similarity = 0.5 * similarity + 0.5 * embedding_similarity(a, b)
        except Exception:
            pass

    score = 0.3 + 0.65 * similarity  # floor 0.3 (weakest real overlap), cap ~0.95 before bonuses

    # "X" fully contained in "X disorder" / "X-associated virus" etc. is a
    # common false-positive shape: every one of the entity's words is present,
    # but a class-shifting qualifier changes what the concept actually IS
    # (a process vs a disease of that process, a sample type vs an organism
    # found in it). Penalize when the label adds a disease/associated marker
    # word the entity itself doesn't have and entity_type isn't DISEASE-like.
    if entity_type not in ("DISEASE", "CLINICAL"):
        added_words = b_words - a_words
        if added_words & DISEASE_CLASS_MARKERS:
            score -= 0.35

    # Same shape, general case: candidate label is much longer than the
    # entity (lots of extra unrelated tokens) - even with decent Jaccard,
    # a huge length gap means the entity is a small fragment of a much more
    # specific concept, not equivalent to it.
    if len(b_words) >= 2 * max(len(a_words), 1) and similarity < 0.9:
        score -= 0.1

    if ontology_name:
        onto = ontology_name.upper()
        preferred = PREFERRED_ONTOLOGIES.get(entity_type, set())
        if onto in preferred:
            score += 0.05
        elif onto in NOISY_FOR_NON_MATCHING_TYPES and onto not in preferred:
            score -= 0.15

    return max(0.0, min(1.0, score))
