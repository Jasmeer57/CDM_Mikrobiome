"""Shared text hygiene for the terminology stages.

Two concerns live here so that every stage applies them *identically* — a
divergence in either would silently break the joins between stages:

``sanitize``
    Strip C0/C1 control characters (and DEL) and collapse runs of whitespace.
    The corpus markdown contains raw control bytes where PDF conversion lost a
    glyph (77 of 453 source ``.md`` files, e.g. ``P \\x02 0.0001`` for
    ``P < 0.0001``). Those bytes survive ``norm_term``'s ``ascii`` encode
    because they *are* ASCII, so they ended up inside ``term_norm`` and inside
    every id derived from it (348 canonical terms, e.g. ``p \\x04``,
    ``\\x04-diversity``, ``fut8\\x02/\\x02``). ``sanitize`` is applied to the
    normalized identity layer only — never to ``surface_form`` / ``defined_surface``
    / ``definition_text``, which stay verbatim so that offset and reproduction
    checks keep passing byte-for-byte.

    ``sanitize`` removes *only* control bytes and whitespace runs. It is
    deliberately NOT the full normalizer: applying the full normalization a
    second time to an already-normalized ``term_norm`` is not idempotent (it
    would fold ``−80°C`` into ``80c`` and, worse, merge genuinely distinct
    terms such as ``Proteobacteria`` with ``ε-proteobacteria``). Control-byte
    removal, by contrast, only ever merges rows that differ *solely* by an
    invisible byte — 19 ``(term_norm, cdm_type)`` collisions across the whole
    166,012-row table, all of them true duplicates.

``non_concept_reason``
    A conservative, pattern-based flag for canonical surfaces that are not
    technical terms at all: URLs/licences, figure/table references, roman
    numerals, citation fragments, significance markers. The canonical table is
    NER output and therefore contains such noise; membership in the table alone
    cannot exclude it. Flagged terms are *marked, not deleted* — the mention
    stream and its provenance stay intact — and downstream stages (T3
    definitions, T5 auto-accept eligibility) skip them so the noise does not
    propagate. ``UNCERTAIN`` is never forced: a surface is either flagged with
    a named reason or left alone.
"""
from __future__ import annotations

import re

# C0 controls except \t \n \r (whitespace, handled by the collapse), plus DEL
# and the C1 block. Kept as one character class so both stages strip the exact
# same set.
CONTROL_RE = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")

_WS_RE = re.compile(r"\s+")


def sanitize(s: str) -> str:
    """Strip control characters and collapse whitespace. Idempotent."""
    if not s:
        return ""
    return _WS_RE.sub(" ", CONTROL_RE.sub(" ", s)).strip()


def has_control(s: str) -> bool:
    """True when ``s`` still contains a control byte (pre-sanitize check)."""
    return bool(s) and bool(CONTROL_RE.search(s))


# ── non-concept surface detection ───────────────────────────────────────────

_URL_OR_LICENSE = re.compile(r"://|\bdoi\s*:|\bcreativecommons\b|\bwww\.", re.I)
_FIGURE_TABLE_REF = re.compile(
    r"^(?:fig(?:ures?|s)?\.?\s*\d*|tab(?:le|les)?\s*\d*|panel\s*\d*|"
    r"eq(?:uation)?s?\s*\d*|supplementary\s+(?:fig|table|material)s?)$", re.I)
_ROMAN_NUMERAL = re.compile(
    r"^(?:II|III|IV|VI|VII|VIII|IX|XI|XII|XIII|XIV|XV|XVI|XVII|XVIII|XIX|XX)$")
_CITATION_FRAGMENT = re.compile(r"^et\.?\s+al\.?$|^et$", re.I)
_SIGNIFICANCE_MARKER = re.compile(r"^\*+\s*[A-Za-z]?\b")

_REASONS = (
    ("EMPTY", lambda t: not t),
    ("CONTROL_CHAR", has_control),
    ("URL_OR_LICENSE", lambda t: bool(_URL_OR_LICENSE.search(t))),
    ("FIGURE_TABLE_REF", lambda t: bool(_FIGURE_TABLE_REF.match(t))),
    ("ROMAN_NUMERAL", lambda t: bool(_ROMAN_NUMERAL.match(t))),
    ("CITATION_FRAGMENT", lambda t: bool(_CITATION_FRAGMENT.match(t))),
    ("SIGNIFICANCE_MARKER", lambda t: bool(_SIGNIFICANCE_MARKER.match(t))),
)


def non_concept_reason(surface: str):
    """Return a reason name when ``surface`` is not a technical term, else None.

    Conservative on purpose: every pattern here was checked against the full
    166,012-term table, and none of them fires on a plausible technical term
    (``PC1``, ``CO2``, ``IL-6``, ``806R`` are all left alone — an earlier
    "short word + digit" rule flagged 1,676 terms and was rejected).
    """
    t = (surface or "").strip()
    for name, test in _REASONS:
        try:
            if test(t):
                return name
        except Exception:  # pragma: no cover - defensive
            continue
    return None


def is_non_concept(surface: str) -> bool:
    return non_concept_reason(surface) is not None
