#!/usr/bin/env python
"""Stage T3 — source-grounded definition extraction.

Deterministic, CPU-only, **no LLM and no network**. Definitions are *copied
verbatim* from the section text and carry the exact character coordinates they
were copied from, so every stored definition is checkable against the source.

Why not the existing script
---------------------------
``src/scripts/catalogue/llm_term_definitions.py`` asks an Ollama model to *generate*
a definition from its own world knowledge. That is not a source-derived
definition: the spec forbids conflating generated text with author text, and a
generated definition cannot be traced to the paper. It is therefore not used
here. It remains available as a separate, clearly-labelled activity if wanted.

What this stage produces
------------------------
``term_definitions.jsonl`` — one row per (canonical term, definition occurrence),
with:

  * ``definition_source`` from the spec's controlled vocabulary
    (``EXPLICIT_AUTHOR_DEFINITION``, ``ABBREVIATION_EXPANSION``,
    ``GLOSSARY_DEFINITION``, ``CONTEXTUAL_DESCRIPTION``, or
    ``NO_DEFINITION_FOUND`` for canonical terms with no source definition);
  * verbatim ``definition_text`` + ``definition_char_start/end`` (offsets into the
    section text) + ``supporting_passage``;
  * ``provenance_class`` = ``SOURCE_DERIVED``;
  * ``review_status`` = ``REVIEW_REQUIRED`` by default — nothing is asserted
    verified, and no confidence score is invented (``confidence`` is null).

Contextual descriptions are NEVER promoted to formal definitions: the pattern
class that matched is recorded, and a term that only has a contextual
description is marked ``REVIEW_REQUIRED`` with
``definition_formality = "contextual"``.

External (ontology) definitions are a *different provenance class* and are not
produced here — see docs/reports/terminology_pipeline_plan.md §2 Stage 3.

Definition-shape gates (fix-3)
------------------------------
Every emitted candidate additionally passes a set of *shape* gates that reject
spans which merely sit next to a term without describing it: figure furniture
(``bar``, ``shaded areas``), sentence fragments introduced by a preposition
(``of gut inflammation``), clause fragments whose head is a finite verb
(``current findings indicate``), page/bibliography starts
(``Supplemental figure S5``), surfaces that are themselves non-concepts
(roman numerals, figure references), and — for abbreviation expansions only —
provably circular expansions (``QIIME`` → ``MacQIIME version``). Each gate
records a named rejection counter, so the tightening is *traceable*: the summary
reports exactly how many candidates each gate removed rather than silently
shrinking the output. No gate invents, repairs, or rewrites a definition; a
rejected candidate is simply not emitted.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
sys.path.insert(0, str(REPO_ROOT / "src"))
# Sibling stage module: import by file location so this works from any CWD and
# does not require ``src/scripts/`` to be an installed package.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from assemble_mentions import (  # noqa: E402
    DEFAULT_SEG_DIR, build_text_index, load_sections, norm_term,
)
from textnorm import non_concept_reason, sanitize  # noqa: E402

TERMS_CSV = REPO_ROOT / "releases/data_catalogue/terminology/terminology_dedup.csv"

# Backmatter sections are administrative; they do not define technical terms.
BACKMATTER = ("reference", "acknowledg", "funding", "author contribution",
              "conflict", "supplementary", "data availability", "competing")

MAX_DEF_CHARS = 400
MIN_DEF_CHARS = 5
MAX_SURFACE_CHARS = 90


def _id(*parts: str) -> str:
    h = hashlib.sha1()
    for p in parts:
        h.update((p or "").encode("utf-8"))
        h.update(b"\x1f")
    return h.hexdigest()[:16]


# ── patterns ────────────────────────────────────────────────────────────────
# Each yields (defined_surface, definition_text) within ONE sentence. Ordered
# from most formal to least; the FIRST matching class wins for a given span.

# ── anchors ─────────────────────────────────────────────────────────────────
# A regex with a non-greedy "term" group picks the SHORTEST text before a comma,
# i.e. the wrong span ("particular", "Indeed"). So instead we anchor on the
# *definition cue* and then look LEFTWARD for the longest word-run that is an
# actual canonical term. This is both more precise and more honest: a definition
# is only recorded when the thing being defined is a known term, and the surface
# offsets are taken from the real source text rather than from a regex capture.

_ANCHOR_LEFT = [
    # "X is/are defined as Y"
    (re.compile(r"\s+(?:is|are)\s+defined\s+as\s+", re.I), "EXPLICIT_AUTHOR_DEFINITION"),
    # "X refers to Y"
    (re.compile(r"\s+refers?\s+to\s+", re.I), "EXPLICIT_AUTHOR_DEFINITION"),
    # "X denotes Y"
    (re.compile(r"\s+denotes?\s+", re.I), "EXPLICIT_AUTHOR_DEFINITION"),
    # "X is known as Y"
    (re.compile(r"\s+is\s+known\s+as\s+", re.I), "EXPLICIT_AUTHOR_DEFINITION"),
]

# Appositive cue: "<term>, a/an/the <description>"
_ANCHOR_APPOS = re.compile(r",\s+(?:a|an|the)\s+", re.I)

# Restrictive cue: "<term> is a/an/the <type-noun> ..."
_TYPE_NOUNS = (r"type|kind|form|class|group|member|subset|species|genus|family|"
               r"taxon|bacterium|bacteria|organism|enzyme|protein|gene|metabolite|"
               r"disease|syndrome|method|technique|assay|measure|index|score|"
               r"ratio|marker|condition|state|process|phylum|strain|isolate")
_ANCHOR_RESTR = re.compile(
    r"\s+(?:is|are)\s+(?:a|an|the)?\s*(?:%s)\b" % _TYPE_NOUNS, re.I)

# Abbreviations are handled by the Hearst-style routines below (they need
# long-form trimming + subsequence validation), not by a single regex.
_ABBREV_PAREN = re.compile(r"\((?P<acr>[A-Z][A-Za-z0-9]{1,14})s?\)")
_ABBREV_REV = re.compile(r"(?P<acr>[A-Z][A-Za-z0-9]{1,14})\s*\((?P<inner>[^()]{3,120})\)")
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9\-]*")

# Glossary lines: "TERM: description" inside glossary/definition sections.
_GLOSSARY = re.compile(r"^\s*(?P<x>[A-Za-z][^:\n]{1,60}?)\s*[:—–]\s+(?P<d>[A-Z][^\n]{5,%d})$" % MAX_DEF_CHARS, re.M)

# Definitions that are really bibliography/URLs are dropped outright.
_BAD_DEF = re.compile(r"(https?://|doi:|www\.|et al\.|\[[0-9]|^\s*see\s)", re.I)

# Definition text that is really page furniture, not a description.
_BAD_DEF_START = re.compile(
    r"^(?:section|journal|additional\s+file|table|figure|fig\.|"
    r"fig(?:ure)?s?\.?\s|table\s|supplemental|supplementary|"
    r"see\s|supplementary\s+material|et\s+al|purchased|compared\s+to|"
    r"predicted|e\.g\.|i\.e\.)", re.I)

# Surfaces that are never technical terms: discourse markers, section words,
# pronouns, generic scaffolding. They occur in the canonical table as NER noise,
# so membership in the table alone cannot filter them — this list must.
_STOPWORD_SURFACE = {
    "however", "in contrast", "in addition", "therefore", "thus", "moreover",
    "furthermore", "also", "but", "and", "or", "yet", "still", "hence",
    "consequently", "meanwhile", "nevertheless", "nonetheless", "overall",
    "similarly", "conversely", "finally", "first", "second", "third", "next",
    "results", "result", "conclusion", "conclusions", "background", "methods",
    "method", "materials", "discussion", "introduction", "abstract", "summary",
    "figure", "figures", "table", "tables", "supplementary", "appendix",
    "we", "they", "it", "this", "these", "those", "there", "here",
    "the", "a", "an", "study", "studies", "paper", "article", "data", "sample",
    "samples", "analysis", "objective", "aim", "purpose", "significance",
    "notably", "indeed", "for example", "for instance", "in particular",
    "particular", "contrast", "addition", "example", "fact", "case", "contrary",
    "general", "total", "number", "value", "values", "level", "levels",
    "increase", "decrease", "difference", "differences", "change", "changes",
    "effect", "effects", "role", "roles", "presence", "absence", "using",
    "based", "compared", "similar", "different", "higher", "lower", "greater",
    "less", "more", "most", "least", "all", "any", "some", "many", "several",
    "various", "other", "others", "same", "such", "both", "each", "either",
    "neither", "no", "not", "only", "between", "among", "within",
    "during", "after", "before", "while", "when", "where", "which", "that",
    "respectively", "including", "include", "includes", "well",
    "significantly", "relative", "associated", "observed", "found", "shown",
    "interestingly", "importantly", "additionally", "specifically",
    "particularly", "recently", "previously", "currently", "generally",
    "typically", "namely", "together", "firstly", "secondly", "thirdly",
    "notably", "ultimately", "collectively", "respectively", "approximately",
    "subsequently", "initially", "eventually", "finally", "overall",
}

# Tokens that must not START an abbreviation long form (they signal that the
# capture ran leftward past the actual noun phrase).
_BAD_LONGFORM_START = {
    "of", "in", "on", "at", "by", "for", "with", "and", "or", "to", "as",
    "from", "than", "that", "which", "whose", "including", "include", "includes",
    "included", "is", "are", "was", "were", "be", "been", "being", "has", "have",
    "had", "using", "used", "based", "shown", "observed", "indicated", "detected",
    "found", "showed", "also", "however", "where", "when", "while", "after",
    "before", "during", "between", "among", "such", "no", "not", "more", "most",
    "less", "least", "all", "any", "some", "these", "those", "this", "the",
    "denoted", "designated", "referred", "labelled", "labeled", "called",
}

MAX_LONGFORM_WORDS = 8
MAX_TERM_WORDS = 6
TERM_LOOKBEHIND = 120

# A definition is a NOUN PHRASE. These lists reject clause fragments that a
# positional anchor can otherwise produce ("...showed a trend of negative
# correlation with", "...were removed"). Recall is traded for precision
# deliberately: every stored definition must be readable as a description.
_NP_BAD_START = {
    "which", "whose", "that", "where", "when", "while", "relative", "higher",
    "lower", "greater", "less", "more", "most", "many", "several", "various",
    "all", "any", "some", "both", "each", "either", "neither", "other",
    "these", "those", "this", "the", "a", "an", "than", "as", "such", "it",
    "they", "we", "there", "here", "however", "thus", "therefore", "also",
    "showed", "observed", "found", "indicated", "detected", "compared",
    "divided", "selected", "using", "used", "based", "increased", "decreased",
}
_NP_BAD_END = {
    "of", "with", "in", "on", "at", "by", "for", "to", "from", "and", "or",
    "the", "a", "an", "that", "which", "whose", "than", "as", "were", "was",
    "is", "are", "be", "been", "being", "has", "have", "had", "not", "no",
}
_FINITE_VERBS = {
    "is", "are", "was", "were", "be", "been", "being", "has", "have", "had",
    "showed", "shows", "show", "observed", "observe", "found", "find",
    "indicated", "indicates", "detected", "detect", "compared", "compare",
    "divided", "divide", "selected", "select", "used", "use", "using",
    "based", "increased", "increase", "decreased", "decrease", "reported",
    "reports", "suggests", "suggest", "may", "might", "can", "could", "will",
    "would", "should", "does", "do", "affects", "affect", "modulate",
    "modulates", "reduce", "reduces", "cause", "causes", "induce", "induces",
    "promote", "promotes", "inhibit", "inhibits", "activate", "activates",
    "express", "expresses", "contain", "contains", "include", "includes",
    "represent", "represents", "constitute", "constitutes", "comprise",
    "comprises", "consist", "consists", "remain", "remains", "occur", "occurs",
    "exist", "exists", "differ", "differs", "vary", "varies", "arise", "arises",
}
_SURFACE_BAD_END = _NP_BAD_END | {"-", "–", "—", "/", "("}

# ── fix-3 shape gates ───────────────────────────────────────────────────────
# Leading tokens that mean the span started mid-sentence: the real description
# is the noun phrase after them, which the leftward anchor missed.
_LEADING_PREP = {
    "of", "in", "on", "at", "by", "for", "with", "and", "or", "to", "as", "from",
    "than", "that", "which", "while", "when", "where", "without", "within",
    "between", "among", "during", "after", "before", "under", "over", "into",
    "onto", "upon", "about", "against", "because", "since", "although", "though",
    "but", "nor", "yet", "so", "hence", "thus", "therefore", "also", "whereas",
    "plus", "via", "per", "versus", "vs",
}

# Words that belong to figure legends/diagram keys, never to a term description.
# Only unambiguous members are listed: ``star``, ``green``, ``polar``, ``white``,
# ``solid``, ``letter``, ``cross``, ``square``, ``diamond``, ``horizontal`` and
# ``vertical`` all begin real terms (STAR, green alga, polar regions) and are
# deliberately absent.
_FIGURE_TOKENS = {
    "color", "colors", "colour", "colours", "colored", "coloured",
    "blue", "red", "orange", "gray", "grey", "turquoise", "yellow", "purple",
    "pink", "cyan", "magenta", "violet", "maroon", "black",
    "arrow", "arrows", "asterisk", "asterisks", "circle", "circles",
    "dot", "dots", "triangle", "triangles", "box", "boxes", "bar", "bars",
    "whisker", "whiskers", "shaded", "shading", "marker", "markers",
    "symbol", "symbols", "column", "columns", "area", "areas",
    "open", "closed", "filled", "shaded", "polar", "formatting", "lightness",
    "hue", "dashed", "median", "whisker",
}

# Finite verb forms only. Gerunds/participles (``using``, ``observed``,
# ``based``) are legitimate inside a noun phrase ("variable selection using
# random forests") and must NOT reject the span.
_FINITE_VERB_HEADS = {
    "is", "are", "was", "were", "has", "have", "had", "does", "do",
    "shows", "show", "showed", "indicates", "indicate", "indicated",
    "represents", "represent", "contains", "contain", "denotes", "denote",
    "includes", "include", "accounts", "account", "reflects", "reflect",
    "suggests", "suggest", "provides", "provide", "allows", "allow",
    "causes", "cause", "induces", "induce", "promotes", "promote",
    "inhibits", "inhibit", "activates", "activate", "expresses", "express",
    "constitutes", "constitute", "comprises", "comprise", "consists", "consist",
    "remains", "remain", "occurs", "occur", "exists", "exist", "differs",
    "vary", "varies", "arises", "arise", "belongs", "belong", "carries",
    "carry", "leads", "lead", "falls", "fall", "must", "cannot", "combines",
    "combine", "corresponds", "correspond", "enables", "enable",
}
_DETERMINERS = {"a", "an", "the", "this", "these", "those", "each", "one",
                "any", "some", "all", "both", "its", "their", "our", "his", "her"}

# Word-count / shape gates. ``MIN_DEF_WORDS`` is applied to non-abbreviation
# sources only (a two-word expansion such as "Hypertrophic cardiomyopathy" is
# normal); ``HEAD_TOKENS`` bounds the finite-verb scan to the clause head.
MIN_DEF_WORDS = 3
HEAD_TOKENS = 3


def _looks_like_noun_phrase(d: str, min_words: int = 2) -> bool:
    words = _WORD.findall(d)
    if len(words) < min_words:
        return False
    lowered = [w.lower() for w in words]
    if lowered[0] in _STOPWORD_SURFACE or lowered[0] in _NP_BAD_START:
        return False
    if lowered[-1] in _NP_BAD_END:
        return False
    # A finite verb *before* the first relativiser means this clause is a
    # statement, not a description ("...were compared without").
    rel = len(lowered)
    for i, w in enumerate(lowered):
        if w in ("that", "which", "who", "whose"):
            rel = i
            break
    if any(w in _FINITE_VERBS for w in lowered[:rel]):
        return False
    return True


def _surface_ok(surf: str) -> bool:
    words = _WORD.findall(surf)
    if not words:
        return False
    lowered = [w.lower() for w in words]
    if lowered[0] in _STOPWORD_SURFACE or lowered[0] in _NP_BAD_START:
        return False
    if lowered[0].endswith("ly"):  # adverbs are never terms
        return False
    if lowered[-1] in _SURFACE_BAD_END:
        return False
    return True


def clean_surface(s: str) -> str:
    s = s.strip().strip("\"'“”‘’()[]").strip()
    s = re.sub(r"^(?:the|a|an)\s+", "", s, flags=re.I)
    s = re.sub(r"\s+", " ", s).strip().strip(",")
    return s


# ── fix-3 shape gates ───────────────────────────────────────────────────────
# Word-count tokenizer: hyphens split (``leave-one-out`` is three words), which
# is what the offline measurement used. ``_WORD`` above keeps a hyphen inside a
# token because it is also used for word-initial matching; using it for counting
# would under-count hyphenated technical phrases.
_TOKEN = re.compile(r"[A-Za-z0-9]+")


def _initials_match(acr: str, long_text: str) -> bool:
    """Classic Hearst word-initial match (used as an escape hatch only)."""
    i = 0
    for w in _WORD.findall(long_text):
        if i < len(acr) and w[0].lower() == acr[i]:
            i += 1
    return i == len(acr)


def _case_aware_match(acr: str, long_text: str) -> bool:
    """Acronym is a subsequence of the long form's upper-case initials."""
    ups = "".join(c for c in re.sub(r"[^A-Za-z0-9]", "", long_text)
                  if c.isupper()).lower()
    i = 0
    for ch in ups:
        if i < len(acr) and ch == acr[i]:
            i += 1
    return bool(ups) and i == len(acr)


def abbreviation_rejection(acr: str, long_text: str):
    """Reason when an ``ABBREVIATION_EXPANSION`` span is provably not one.

    Automatic validation of biomedical expansions has poor precision: real
    expansions routinely need non-initial letters (``HCM`` → "Hypertrophic
    cardiomyopathy", ``LEfSe`` → "Linear discriminant analysis Effect Size"),
    so a strict Hearst test rejects far more correct rows than wrong ones. This
    gate therefore rejects only the *pathologies* — degenerate acronyms, long
    forms shorter than the acronym, single-word long forms, and circular
    expansions where the acronym is repeated verbatim inside the long form
    (``CAGs`` → "elderly-associated CAGs", ``LME`` → "R package lmerTest") —
    with a case-aware or word-initial match as escape hatch. The escape hatch is
    deliberately permissive: it also rescues acronyms that are an upper-case
    subsequence of the long form (``SHAP`` → "SHapley Additive exPlanations"),
    and that same permissiveness keeps some circular cases such as ``QIIME`` →
    "MacQIIME version", which is accepted rather than risk rejecting real
    expansions. Everything else is left to the shape gates.
    """
    a = re.sub(r"[^a-z0-9]", "", acr.lower())
    letters = re.sub(r"[^a-z0-9]", "", long_text.lower())
    if len(a) < 2 or len(set(a)) == 1:
        return "ABBREV_DEGENERATE"
    if not letters or len(letters) < len(a):
        return "ABBREV_SHORTER_LONGFORM"
    words = [w.lower() for w in _TOKEN.findall(long_text)]
    if len(words) < 2:
        return "ABBREV_SINGLE_WORD_LONGFORM"
    if _initials_match(a, long_text) or _case_aware_match(a, long_text):
        return None
    if a in words or any(a in w for w in words):
        return "ABBREV_CIRCULAR_EXPANSION"
    return None


def _figure_surface(surf: str) -> bool:
    """Every word of the surface is figure-legend vocabulary."""
    words = [w.lower() for w in _TOKEN.findall(surf)]
    return bool(words) and all(w in _FIGURE_TOKENS for w in words)


def _figure_definition(d: str) -> bool:
    """The span is mostly figure-legend vocabulary."""
    words = [w.lower() for w in _TOKEN.findall(d)]
    if len(words) < 3:
        return False
    fig = sum(1 for w in words if w in _FIGURE_TOKENS)
    return fig >= 2 and fig >= len(words) / 2


def _leading_prep(d: str) -> bool:
    words = _TOKEN.findall(d)
    return bool(words) and words[0].lower() in _LEADING_PREP


def _finite_verb_head(d: str) -> bool:
    """A finite verb in the clause head means this is a statement fragment."""
    words = [w.lower() for w in _TOKEN.findall(d)]
    while words and words[0] in _DETERMINERS:
        words = words[1:]
    return any(w in _FINITE_VERB_HEADS for w in words[:HEAD_TOKENS])


def definition_rejection(surf, d, source):
    """Return a named rejection reason for a candidate, or ``None`` to keep it.

    The order is the one measured against the 1,270 pre-existing rows, so the
    recorded reason is the *most specific* one (an abbreviation pathology is
    reported as such, not as a generic shape failure).
    """
    if _BAD_DEF_START.search(d):
        return "BAD_DEFINITION_START"
    if non_concept_reason(surf):
        return "NON_CONCEPT_SURFACE"
    if _figure_surface(surf):
        return "FIGURE_SURFACE"
    if _figure_definition(d):
        return "FIGURE_DEFINITION"
    if _leading_prep(d):
        return "LEADING_PREPOSITION"
    if _finite_verb_head(d):
        return "FINITE_VERB_FRAGMENT"
    if source == "ABBREVIATION_EXPANSION":
        # A two-word expansion is perfectly normal ("Hypertrophic
        # cardiomyopathy"), so abbreviations are not held to ``MIN_DEF_WORDS``.
        return abbreviation_rejection(surf, d)
    if len(_TOKEN.findall(d)) < MIN_DEF_WORDS:
        return "TOO_FEW_WORDS"
    return None


def load_terms(path: Path, stats=None):
    """(term_norm -> (term_id, term, cdm_type)). Term ids match the dedup key.

    ``term_norm`` is sanitized on read so the join key is the *same* string T1
    writes (control bytes stripped) — otherwise the 348 control-char terms
    would never resolve. Surfaces flagged as non-concepts are recorded and
    skipped: a roman numeral or a figure reference is not a term to define.
    """
    terms = {}
    non_concept = 0
    with path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            tn = sanitize((row.get("term_norm") or "").strip())
            if not tn:
                continue
            cdm = (row.get("cdm_type") or "").strip() or "UNCERTAIN"
            raw = (row.get("term") or "").strip()
            reason = non_concept_reason(raw) or non_concept_reason(tn)
            if reason:
                non_concept += 1
                if stats is not None:
                    stats["load_terms_non_concept_by_reason"][reason] += 1
                continue
            tid = "HMCTERM_" + _id(tn, cdm)
            terms[tn] = (tid, raw, cdm)
    if stats is not None:
        stats["load_terms_non_concept"] = non_concept
    return terms


def _is_subsequence(needle: str, hay: str) -> bool:
    it = iter(hay)
    return all(ch in it for ch in needle)


def _trim_long_form(words, acronym):
    """Hearst long-form trimming: return the *shortest trailing run* of ``words``
    whose alphanumeric characters contain the acronym as a subsequence.

    This removes text captured to the left of the real expansion, e.g.
    ``"Circulating lipopolysaccharide"`` -> ``"lipopolysaccharide"`` for LPS and
    ``"indicated in simian immunodeficiency virus"`` -> ``"simian immunodeficiency
    virus"`` for SIV. Returns None when no suffix validly contains the acronym —
    in that case the candidate is REJECTED rather than stored incorrectly.
    """
    acr = re.sub(r"[^a-z0-9]", "", acronym.lower())
    if len(acr) < 3:
        return None
    for i in range(len(words)):
        cand = words[i:]
        joined = re.sub(r"[^a-z0-9]", "", "".join(cand).lower())
        if _is_subsequence(acr, joined):
            if cand[0].lower() in _BAD_LONGFORM_START:
                return None
            if len(cand) > len(acr) + 2:
                return None  # implausible expansion length
            return cand
    return None


def _long_form_before(text, pos, window=90):
    """Words immediately preceding ``pos`` (up to ``window`` chars back)."""
    seg = text[max(0, pos - window):pos]
    return _WORD.findall(seg)


def _sentence_tail(text, pos, limit=MAX_DEF_CHARS):
    """Definition text running from ``pos`` to the end of the sentence/clause.

    Returns ``(text, start, end)`` with offsets that index the original string.
    """
    m = re.search(r"[.;\n]", text[pos:pos + limit])
    end = pos + (m.start() if m else min(limit, len(text) - pos))
    raw = text[pos:end]
    lead = len(raw) - len(raw.lstrip())
    return raw.strip(), pos + lead, end


def _match_left_term(text, anchor_start, terms):
    """Longest word-run ending just before ``anchor_start`` that is a canonical
    term.

    Returns ``(term_key, surface, start, end)`` or ``None``.
    """
    lo = max(0, anchor_start - TERM_LOOKBEHIND)
    words = list(_WORD.finditer(text[lo:anchor_start]))
    for n in range(min(len(words), MAX_TERM_WORDS), 0, -1):
        w = words[-n:]
        s = lo + w[0].start()
        e = lo + w[-1].end()
        surf = text[s:e]
        key = norm_term(surf)
        if key in _STOPWORD_SURFACE:
            continue
        if key in terms:
            return key, surf, s, e
    return None


def scan_section(text: str, terms: dict, paper: str, sid: str, stats=None):
    """Yield definition candidates found in one section body.

    Every candidate is anchored on a definition cue, resolved to a canonical
    term by leftward matching, shape-gated (fix-3), and span-checked against the
    source text before it is emitted. Nothing is guessed: a candidate that
    cannot be reproduced verbatim from ``text`` at the recorded offsets is
    dropped, and every gate rejection is counted in ``stats`` so the tightening
    is traceable rather than silent.
    """
    # glossary-style extraction is only meaningful inside a glossary section
    is_glossary_sec = any(k in (sid or "").lower() for k in
                          ("glossary", "definit", "abbrev"))

    def reject(reason):
        if stats is not None and reason:
            stats["rejected"][reason] += 1
        return None

    def emit(surf, s, e, d_raw, dstart, dend, source, formality, mstart, mend):
        key = norm_term(surf)
        if not key or len(surf) > MAX_SURFACE_CHARS:
            return reject("SURFACE_TOO_LONG" if key else "EMPTY_SURFACE")
        if key in _STOPWORD_SURFACE:
            return reject("STOPWORD_SURFACE")
        hit = terms.get(key)
        if hit is None:
            return reject("TERM_NOT_CANONICAL")
        if formality == "contextual" and hit[2] == "ENTITY":
            # a contextual gloss of an *untyped* span is not worth asserting
            return reject("CONTEXTUAL_UNTYPED")
        d = d_raw.strip()
        if not (MIN_DEF_CHARS <= len(d) <= MAX_DEF_CHARS):
            return reject("DEF_LENGTH")
        if _BAD_DEF.search(d):
            return reject("BAD_DEF_TEXT")
        if _BAD_DEF_START.search(d):
            return reject("BAD_DEF_START")
        # fix-3 shape gates (figure furniture, fragments, abbreviations)
        reason = definition_rejection(surf, d, source)
        if reason:
            return reject(reason)
        # never store a span we cannot reproduce from the source
        if text[s:e] != surf or text[dstart:dend] != d_raw:
            return reject("OFFSET_MISMATCH")
        return {
            "defined_surface": surf,
            "definition_text": d,
            "definition_source": source,
            "definition_formality": formality,
            "term_id": hit[0], "term": hit[1], "term_norm": key, "cdm_type": hit[2],
            "definition_char_start": dstart, "definition_char_end": dend,
            "match_char_start": mstart, "match_char_end": mend,
            "paper_id": paper, "section_id": sid,
        }

    defs = []

    # ── 1) forward abbreviations: "<long form> (ACR)" ───────────────────────
    for m in _ABBREV_PAREN.finditer(text):
        acr = m.group("acr")
        words = _long_form_before(text, m.start())
        long_words = _trim_long_form(words, acr)
        if not long_words or len(long_words) > MAX_LONGFORM_WORDS:
            continue
        long_text = " ".join(long_words)
        # locate the long form in the source so offsets are real
        idx = text.rfind(long_text, max(0, m.start() - 120), m.start())
        if idx < 0:
            continue
        key = norm_term(acr)
        hit = terms.get(key)
        if hit is None or key in _STOPWORD_SURFACE:
            continue
        long_raw = text[idx:idx + len(long_text)]
        r = emit(acr, m.start("acr"), m.end("acr"), long_raw, idx,
                 idx + len(long_raw), "ABBREVIATION_EXPANSION", "formal",
                 idx, m.end())
        if r:
            r["term_id"], r["term"], r["term_norm"], r["cdm_type"] = (
                hit[0], hit[1], key, hit[2])
            defs.append(r)

    # ── 2) reverse abbreviations: "ACR (long form)" ─────────────────────────
    for m in _ABBREV_REV.finditer(text):
        acr = m.group("acr")
        inner = m.group("inner")
        words = _WORD.findall(inner)
        long_words = _trim_long_form(words, acr)
        if not long_words or len(long_words) > MAX_LONGFORM_WORDS:
            continue
        long_text = " ".join(long_words)
        idx = text.rfind(long_text, m.start("inner"), m.end("inner") + 1)
        if idx < 0:
            continue
        # reject circular/self-referential "definitions" (e.g. "A1c (HbA1c)")
        if (len(long_words) == 1
                and re.sub(r"[^a-z0-9]", "", acr.lower())
                in re.sub(r"[^a-z0-9]", "", long_text.lower())):
            continue
        key = norm_term(acr)
        hit = terms.get(key)
        if hit is None or key in _STOPWORD_SURFACE:
            continue
        long_raw = text[idx:idx + len(long_text)]
        r = emit(acr, m.start("acr"), m.end("acr"), long_raw, idx,
                 idx + len(long_raw), "ABBREVIATION_EXPANSION", "formal",
                 m.start(), m.end())
        if r:
            r["term_id"], r["term"], r["term_norm"], r["cdm_type"] = (
                hit[0], hit[1], key, hit[2])
            defs.append(r)

    # ── 3) explicit authorial definitions: "<term> is defined as <def>" ─────
    for pat, source in _ANCHOR_LEFT:
        for m in pat.finditer(text):
            mt = _match_left_term(text, m.start(), terms)
            if not mt:
                continue
            key, surf, s, e = mt
            if not _surface_ok(surf):
                continue
            d, ds, de = _sentence_tail(text, m.end())
            if not _looks_like_noun_phrase(d, 2):
                continue
            r = emit(surf, s, e, d, ds, de, source, "formal", s, m.end())
            if r:
                defs.append(r)

    # ── 4) appositive: "<term>, a <description>" ───────────────────────────
    for m in _ANCHOR_APPOS.finditer(text):
        mt = _match_left_term(text, m.start(), terms)
        if not mt:
            continue
        key, surf, s, e = mt
        if not _surface_ok(surf):
            continue
        d, ds, de = _sentence_tail(text, m.end())
        if not _looks_like_noun_phrase(d, 3):
            continue
        r = emit(surf, s, e, d, ds, de, "CONTEXTUAL_DESCRIPTION", "contextual",
                 s, m.end())
        if r:
            defs.append(r)

    # ── 5) restrictive: "<term> is a <type-noun> ..." ──────────────────────
    for m in _ANCHOR_RESTR.finditer(text):
        mt = _match_left_term(text, m.start(), terms)
        if not mt:
            continue
        key, surf, s, e = mt
        if not _surface_ok(surf):
            continue
        d, ds, de = _sentence_tail(text, m.end())
        if not _looks_like_noun_phrase(d, 2):
            continue
        r = emit(surf, s, e, d, ds, de, "CONTEXTUAL_DESCRIPTION", "contextual",
                 s, m.end())
        if r:
            defs.append(r)

    # ── 6) glossary lines (only inside glossary-like sections) ─────────────
    if is_glossary_sec:
        for m in _GLOSSARY.finditer(text):
            x = m.group("x").strip()
            s = m.start("x") + (len(m.group("x")) - len(m.group("x").lstrip()))
            e = s + len(x)
            r = emit(x, s, e, text[m.start("d"):m.end("d")], m.start("d"),
                     m.end("d"), "GLOSSARY_DEFINITION", "formal", s, m.end())
            if r:
                defs.append(r)

    yield from defs



def main() -> int:
    ap = argparse.ArgumentParser(description="Stage T3 source-grounded definitions")
    ap.add_argument("--out_dir", default="outputs/results/terminology_v1")
    ap.add_argument("--seg_dir", default=str(DEFAULT_SEG_DIR))
    ap.add_argument("--terms_csv", default=str(TERMS_CSV))
    ap.add_argument("--limit_papers", type=int, default=0, help="Pilot: cap papers scanned")
    ap.add_argument("--limit_terms", type=int, default=0, help="Pilot: cap canonical terms loaded")
    ap.add_argument("--emit_none_found", action="store_true",
                    help="Also emit NO_DEFINITION_FOUND rows for terms with no source definition")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "term_definitions.jsonl"

    stats = {"rejected": Counter(), "load_terms_non_concept": 0,
             "load_terms_non_concept_by_reason": Counter()}

    terms = load_terms(Path(args.terms_csv), stats=stats)
    if args.limit_terms:
        terms = dict(list(terms.items())[: args.limit_terms])
    print("canonical terms loaded: %d" % len(terms), flush=True)

    sec, _ = load_sections(Path(args.seg_dir))
    papers = sorted({k[0] for k in sec})
    if args.limit_papers:
        papers = papers[: args.limit_papers]
        sec = {k: v for k, v in sec.items() if k[0] in set(papers)}
    print("sections to scan: %d across %d papers" % (len(sec), len(papers)), flush=True)

    found_terms = set()
    by_source = Counter()
    by_formality = Counter()
    by_type = Counter()
    n_rows = 0
    seen = set()

    with out_path.open("w", encoding="utf-8") as fout:
        for (paper, sid) in sorted(sec):
            path_l = (sec[(paper, sid)][1] or "").lower()
            if any(b in path_l for b in BACKMATTER):
                continue
            text = sec[(paper, sid)][0]
            if not text:
                continue
            sents, _paras = build_text_index(text)
            for cand in scan_section(text, terms, paper, sid, stats=stats):
                ds, de = cand["definition_char_start"], cand["definition_char_end"]
                # sentence provenance for the definition span
                s_idx = None
                for i, (s, e) in enumerate(sents):
                    if s <= ds and de <= e:
                        s_idx = i
                        break
                definition_id = "HMDEF_" + _id(
                    "def", paper, sid, str(cand["term_id"]), str(ds), str(de))
                if definition_id in seen:
                    continue
                seen.add(definition_id)
                rec = {
                    "definition_id": definition_id,
                    "term_id": cand["term_id"],
                    "term": cand["term"],
                    "term_norm": cand["term_norm"],
                    "cdm_type": cand["cdm_type"],
                    "paper_id": paper,
                    "section_id": sid,
                    "sentence_id": f"{sid}:s{s_idx}" if s_idx is not None else None,
                    "definition_text": cand["definition_text"],
                    "definition_char_start": ds,
                    "definition_char_end": de,
                    "defined_surface": cand["defined_surface"],
                    "definition_source": cand["definition_source"],
                    "definition_formality": cand["definition_formality"],
                    "provenance_class": "SOURCE_DERIVED",
                    "extraction_method": "rule_pattern",
                    "extraction_run_id": "termpipeline_t3_rules_v1",
                    "confidence": None,
                    "review_status": "REVIEW_REQUIRED",
                    "unresolved_flags": [],
                }
                fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
                n_rows += 1
                found_terms.add(cand["term_id"])
                by_source[cand["definition_source"]] += 1
                by_formality[cand["definition_formality"]] += 1
                by_type[cand["cdm_type"]] += 1
            if len(found_terms) % 2000 < 50:
                print("  ... %d definitions, %d terms covered" % (n_rows, len(found_terms)), flush=True)

        if args.emit_none_found:
            for tn, (tid, term, cdm) in terms.items():
                if tid in found_terms:
                    continue
                fout.write(json.dumps({
                    "definition_id": "HMDEF_" + _id("none", tid),
                    "term_id": tid, "term": term, "term_norm": tn, "cdm_type": cdm,
                    "paper_id": None, "section_id": None, "sentence_id": None,
                    "definition_text": None, "definition_char_start": None,
                    "definition_char_end": None, "defined_surface": None,
                    "definition_source": "NO_DEFINITION_FOUND",
                    "definition_formality": None, "provenance_class": "SOURCE_DERIVED",
                    "extraction_method": "rule_pattern", "extraction_run_id": "termpipeline_t3_rules_v1",
                    "confidence": None, "review_status": "REVIEW_REQUIRED",
                    "unresolved_flags": ["NO_SOURCE_DEFINITION"],
                }, ensure_ascii=False) + "\n")
                n_rows += 1
                by_source["NO_DEFINITION_FOUND"] += 1

    summary = {
        "canonical_terms_in_scope": len(terms),
        "canonical_terms_with_source_definition": len(found_terms),
        "pct_terms_covered": round(100.0 * len(found_terms) / max(1, len(terms)), 4),
        "definition_rows": n_rows,
        "by_definition_source": dict(by_source),
        "by_formality": dict(by_formality),
        "by_cdm_type": dict(by_type),
        "papers_scanned": len(papers),
        "rejection_counts": dict(sorted(stats["rejected"].items(),
                                        key=lambda kv: -kv[1])),
        "rejected_total": sum(stats["rejected"].values()),
        "load_terms_non_concept": stats["load_terms_non_concept"],
        "load_terms_non_concept_by_reason": dict(
            sorted(stats["load_terms_non_concept_by_reason"].items(),
                   key=lambda kv: -kv[1])),
        "caveats": [
            "Rule-pattern extraction only; recall is bounded by the pattern set.",
            "CONTEXTUAL_DESCRIPTION rows are NOT formal definitions and must not be "
            "reported as such.",
            "External/ontology definitions are a separate provenance class and are not "
            "produced by this stage.",
            "review_status is REVIEW_REQUIRED for every row; no definition is verified.",
            "ABBREVIATION_EXPANSION candidates are validated by pathology checks only "
            "(degenerate/circular/single-word long forms); a non-initial expansion is "
            "kept rather than rejected, because strict Hearst matching rejects more "
            "correct rows than wrong ones.",
            "rejection_counts records every candidate removed by a shape gate, so the "
            "tightening is traceable; no gate rewrites or repairs a definition.",
        ],
    }
    (out_dir / "_definitions_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
