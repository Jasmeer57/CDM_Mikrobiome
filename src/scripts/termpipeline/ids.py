"""Deterministic identifier helpers shared by the terminology stages.

Every stage must derive an identifier the same way or join keys silently stop
matching. These are pure functions of the content they name — no counters, no
ordering, no timestamps — so a rerun on the same inputs yields the same ids.

The exact byte sequence each function hashes is documented, because two stages
that "look" equivalent but feed the parts in a different order produce ids that
never join. Callers should prefer these helpers over hashing inline.

Identity layers (kept deliberately distinct — see the pipeline plan):
  mention_id     one occurrence as tagged by ONE extractor
  occurrence_key one occurrence, independent of which extractor saw it
  term_id        the canonical (term_norm, cdm_type) entity
  concept_id     an external controlled-vocabulary identifier
  definition_id  one source-grounded definition span attached to a term
"""

from __future__ import annotations

import hashlib

MENTION_PREFIX = "HMTERM_"
OCCURRENCE_PREFIX = "HMOCC_"
TERM_PREFIX = "HMCTERM_"
DEFINITION_PREFIX = "HMDEF_"
MAPPING_PREFIX = "HMMAP_"


def _hashseq(*parts: str) -> str:
    """sha1 over the parts joined by 0x1f, hex, first 16 chars."""
    h = hashlib.sha1()
    for p in parts:
        h.update(str(p or "").encode("utf-8"))
        h.update(b"\x1f")
    return h.hexdigest()[:16]


def term_id(term_norm: str, cdm_type: str) -> str:
    """Canonical term id — the existing dedup key, ``(term_norm, cdm_type)``."""
    return TERM_PREFIX + _hashseq((term_norm or "").strip(),
                                  (cdm_type or "").strip())


def mention_id(run_id: str, paper_id: str, section_id: str, start, end,
               surface_norm: str) -> str:
    """One mention as recorded by one extractor (competing tags stay distinct).

    Hashes ``"mention", paper, section, start, end, surface_norm, run_id`` —
    byte-identical to ``assemble_mentions._mid("mention", ...)``. The ``run_id``
    is what keeps two models' tags for the same span as separate mentions.
    """
    return MENTION_PREFIX + _hashseq("mention", paper_id or "", section_id or "",
                                     str(start), str(end), surface_norm or "",
                                     run_id or "")


def occurrence_key(paper_id: str, section_id: str, start, end,
                   surface_norm: str) -> str:
    """Extractor-independent occurrence key — lets models disagree without merging.

    Hashes ``"occ", paper, section, start, end, surface_norm``.
    """
    return OCCURRENCE_PREFIX + _hashseq("occ", paper_id or "", section_id or "",
                                        str(start), str(end), surface_norm or "")


def definition_id(paper_id: str, section_id: str, term_id_: str,
                  char_start, char_end) -> str:
    """One source-grounded definition span for one term occurrence.

    Hashes ``"def", paper, section, term_id, char_start, char_end`` — matching
    ``extract_definitions``.
    """
    return DEFINITION_PREFIX + _hashseq("def", paper_id or "", section_id or "",
                                        str(term_id_ or ""), str(char_start),
                                        str(char_end))


def mapping_id(subject_key: str, source_tier: str, concept_id: str,
               candidate_rank=None, duplicate_index: int = 0) -> str:
    """One candidate concept for one canonical term, from one matching tier.

    Deterministic on purpose (never ``hash()``, which is salted per process):
    the same candidate must keep the same id across reruns.

    Hashes ``subject_key, source_tier, concept_id, candidate_rank,
    duplicate_index`` joined by 0x1f. ``candidate_rank`` and
    ``duplicate_index`` were added so that two rows which agree on every other
    part still receive *distinct* ids: without them a vocabulary that returned
    the same concept twice (rank churn) collapsed onto one id, which made
    ``mapping_id`` non-unique (measured: 3,556 duplicated ids over 4,150 extra
    rows before the fix). ``duplicate_index`` is a 0-based occurrence counter
    assigned deterministically in emission order, so it is stable across
    reruns on the same inputs.

    ``subject_key`` is the resolved canonical ``term_id`` when one exists, or
    ``"UNRESOLVED:<norm>|<cdm_type>"`` when no canonical term resolves — so an
    unresolved row still receives a valid, unique id instead of ``null``.
    """
    return MAPPING_PREFIX + _hashseq(
        subject_key or "", source_tier or "", concept_id or "",
        "" if candidate_rank is None else str(candidate_rank),
        str(duplicate_index))
