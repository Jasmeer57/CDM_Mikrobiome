"""Fix B (layer 3.2.0-candidate): syntactic-connection pre-filter for relation typing. RULE FIXED IN ADVANCE.

The sha256 of this file is recorded in outputs/results/fixes_v32_2026-11-11/PREREGISTRATION.md BEFORE the filter is run on
any benchmark (DiMB-RE, MiDRED, MINERVA). No rule or threshold here may be changed after that; a changed sha means the
pre-registration is void. Motivation (to be disclosed in the manuscript): the filter was added after a first DiMB-RE run
showed that the relation typer asserts relations between entity pairs that merely co-occur in a sentence.

Rule. Two entity mentions in one sentence are SYNTACTICALLY CONNECTED (the pair may be relation-typed) if one of:
  (a) NESTED      the two mention spans overlap (one noun phrase holds both);
  (b) PATH        the dependency path between the two span heads (span roots) uses only clause-internal relations
                  ALLOWED below, and is not a bare coordination;
  (c) CLAUSE      the two heads belong to the same clause and that clause has a predicate (a verb / auxiliary head, or a
                  head with a copula child), and the path is not a bare coordination.
  A conj edge between two predicates is clause-internal only when the conjoined predicate has no subject of its own
  (shared-subject coordination, "A increased B and decreased C"); with its own subject it joins two clauses ("A was
  collected, and B was measured by C") and counts as a relation outside ALLOWED.
  Bare coordination = every edge on the path is conj or appos, with at least one conj, or an appos chain of length >= 2
  (lists such as "A, B and C" or "A, B, C"). A bare coordination still passes (COORD_EXCEPTION) when
    (i)  the coordination is the subject of a predicate that has no other argument or oblique ("A and B were
         correlated", "A and B co-occurred"; "each other" / "one another" are ignored), or
    (ii) the coordination is governed by "between" or "among" ("correlation between A and B").
  Pairs whose heads lie in different sentences of the parse, or whose path needs a relation outside ALLOWED (parataxis,
  dep, advmod, mark, ...) without meeting (c), FAIL -> abstention class CO_OCCURRENCE_ONLY.
  Implementation notes, also fixed: "compound", "poss", "nummod" (noun-phrase-internal modifiers, like amod/nmod) and the
  ClearNLP variants used by scispaCy ("csubj", "agent", "acomp", "dative", "oprd", "nmod:*", "obl:*", "acl:relcl") are
  treated as clause-internal; "case" (the preposition itself) is never an edge between two content heads.
Mention location: a given character span is used as is (alignment "expand"); otherwise the mention text is searched
case-insensitively (every occurrence; the pair passes if any occurrence pair passes); failing that, a fuzzy window of at
least half of the mention's content tokens (lower-cased form or lemma; window <= mention length + 3 tokens). A mention that
cannot be located gives UNLOCATED: the filter cannot be assessed, the pair is NOT filtered and is counted separately.
Parser: scispaCy en_core_sci_lg 0.5.4 (spaCy 3.7.5), NER disabled. Deterministic.
Written with Claude Code (declare).
"""
from __future__ import annotations

import math
import re

RULE_VERSION = "syntax-filter-v1.0-2026-11-11"
ALLOWED = {"nsubj", "nsubjpass", "csubj", "csubjpass", "obj", "dobj", "iobj", "nmod", "obl", "amod", "prep", "pobj", "conj",
           "appos", "acl", "relcl", "ccomp", "xcomp", "advcl", "attr", "cop", "agent", "acomp", "dative", "oprd",
           "compound", "poss", "nummod"}
COORD = {"conj", "appos"}
ARGS = {"dobj", "obj", "iobj", "nmod", "obl", "pobj", "prep", "attr", "acomp", "ccomp", "xcomp", "oprd", "dative", "agent"}
SUBJ = {"nsubj", "nsubjpass", "csubj", "csubjpass"}
CLAUSE_DEPS = {"ccomp", "xcomp", "advcl", "acl", "relcl", "parataxis", "csubj", "csubjpass"}
PASS = {"PASS_NESTED", "PASS_PATH", "PASS_COORD_EXCEPTION", "PASS_CLAUSE"}
FAIL = {"FAIL_BARE_COORDINATION", "FAIL_NO_PATH", "FAIL_DISALLOWED_EDGE"}
STOP = {"the", "a", "an", "of", "in", "and", "or", "with", "to", "for", "on", "by", "at", "from", "as", "its", "their", "this",
        "these", "that", "those", "is", "are", "was", "were", "be"}


def base(dep):
    d = dep.split(":")[0] if dep not in ("acl:relcl", "nmod:poss") else ("relcl" if dep == "acl:relcl" else "poss")
    return d


def load(model="en_core_sci_lg"):
    import spacy
    return spacy.load(model, disable=["ner"])


def norm_text(s):
    return " ".join((s or "").split())


def _content(tokens):
    return [t for t in tokens if not t.is_punct and t.lower_ not in STOP and t.text.strip()]


def locate(doc, text=None, char_span=None, nlp_tok=None):
    """List of spaCy Spans for one mention (empty -> UNLOCATED). Returns (spans, method)."""
    if char_span is not None:
        sp = doc.char_span(char_span[0], char_span[1], alignment_mode="expand")
        return ([sp] if sp is not None and len(sp) else []), "CHAR_SPAN"
    m = norm_text(text)
    if not m:
        return [], "EMPTY"
    low, ml = doc.text.lower(), m.lower()
    spans, k = [], low.find(ml)
    while k >= 0:
        sp = doc.char_span(k, k + len(ml), alignment_mode="expand")
        if sp is not None and len(sp):
            spans.append(sp)
        k = low.find(ml, k + 1)
    if spans:
        return spans, "EXACT"
    mt = _content(nlp_tok(m)) if nlp_tok else [w for w in re.findall(r"\w+", ml) if w not in STOP]
    keys = {(t.lower_ if hasattr(t, "lower_") else t) for t in mt}
    if not keys:
        return [], "NO_CONTENT"
    need = max(1, math.ceil(0.5 * len(keys)))
    width = len(mt) + 3
    hits = [t.i for t in doc if (t.lower_ in keys or t.lemma_.lower() in keys) and not t.is_punct]
    best = None
    for i in hits:
        win = [j for j in hits if i <= j < i + width]
        got = {doc[j].lower_ if doc[j].lower_ in keys else doc[j].lemma_.lower() for j in win}
        if len(got) >= need and (best is None or len(got) > best[0]):
            best = (len(got), win[0], win[-1])
    if best:
        return [doc[best[1]:best[2] + 1]], "FUZZY"
    return [], "NOT_FOUND"


def _edge(x):
    """Dependency label of x -> head; a conj between predicates where x has its own subject is a clause join."""
    d = base(x.dep_)
    if d == "conj" and _predicate(x) and any(base(c.dep_) in SUBJ for c in x.children):
        return "conj_clause"
    return d


def _path(ha, hb):
    """Edges (dep labels) on the tree path between two tokens, plus the lowest common ancestor; None if no common
    ancestor (different sentences)."""
    up_a = [ha] + list(ha.ancestors)
    up_b = [hb] + list(hb.ancestors)
    ids_b = {t.i: n for n, t in enumerate(up_b)}
    for n, t in enumerate(up_a):
        if t.i in ids_b:
            lca = t
            nodes = up_a[:n] + up_b[:ids_b[t.i]]
            return [_edge(x) for x in nodes], lca, nodes
    return None


def _clause_head(t):
    x = t
    while x.head.i != x.i:
        d = base(x.dep_)
        if d in CLAUSE_DEPS or (d == "conj" and x.pos_ in ("VERB", "AUX")):
            break
        x = x.head
    return x


def _predicate(h):
    return h.pos_ in ("VERB", "AUX") or any(base(c.dep_) == "cop" for c in h.children)


def _bare_coordination(edges):
    if not edges or not set(edges) <= COORD:
        return False
    return "conj" in edges or len(edges) >= 2


def _coord_exception(lca):
    """(i) coordination = subject of an argument-less predicate; (ii) coordination governed by between / among."""
    for c in lca.children:
        if base(c.dep_) in ("case", "prep") and c.lemma_.lower() in ("between", "among"):
            return True
    if base(lca.dep_) == "pobj" and lca.head.lemma_.lower() in ("between", "among"):
        return True
    if base(lca.dep_) in SUBJ:
        p = lca.head
        others = [c for c in p.children if base(c.dep_) in ARGS and c.lemma_.lower() not in ("other", "another", "one")]
        return not others
    return False


def judge_spans(sa, sb):
    """Status for one pair of located spans."""
    if sa.start < sb.end and sb.start < sa.end:
        return "PASS_NESTED", []
    ha, hb = sa.root, sb.root
    p = _path(ha, hb)
    if p is None:
        return "FAIL_NO_PATH", []
    edges, lca, _ = p
    bare = _bare_coordination(edges)
    if bare:
        return ("PASS_COORD_EXCEPTION" if _coord_exception(lca) else "FAIL_BARE_COORDINATION"), edges
    if all(e in ALLOWED for e in edges):
        return "PASS_PATH", edges
    ca, cb = _clause_head(ha), _clause_head(hb)
    if ca.i == cb.i and _predicate(ca):
        return "PASS_CLAUSE", edges
    return "FAIL_DISALLOWED_EDGE", edges


ORDER = ["PASS_PATH", "PASS_NESTED", "PASS_COORD_EXCEPTION", "PASS_CLAUSE",
         "FAIL_BARE_COORDINATION", "FAIL_DISALLOWED_EDGE", "FAIL_NO_PATH"]


def judge(doc, a_text=None, b_text=None, a_span=None, b_span=None, nlp_tok=None):
    """dict(status, connected, edges, loc_a, loc_b). status in PASS | FAIL | {"UNLOCATED"}; connected is True / False /
    None (UNLOCATED: not assessable, not filtered)."""
    A, la = locate(doc, a_text, a_span, nlp_tok)
    B, lb = locate(doc, b_text, b_span, nlp_tok)
    if not A or not B:
        return {"status": "UNLOCATED", "connected": None, "edges": [], "loc_a": la, "loc_b": lb}
    best = None
    for sa in A[:5]:
        for sb in B[:5]:
            st, e = judge_spans(sa, sb)
            if best is None or ORDER.index(st) < ORDER.index(best[0]):
                best = (st, e)
    return {"status": best[0], "connected": best[0] in PASS, "edges": best[1], "loc_a": la, "loc_b": lb}
