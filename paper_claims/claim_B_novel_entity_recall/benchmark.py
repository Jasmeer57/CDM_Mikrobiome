#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Claim B benchmark — novel entity recall (LLM vs. union of spaCy vocabularies).

Compares the set of entities extracted by the LLM pipeline against the union of
all 4 sciSpaCy NER vocabularies across the same corpus. Classifies LLM-only
entities as either (a) synonyms / surface variants of a spaCy term, or
(b) truly novel. Reports counts + top novel candidates for manual review.

Usage (from this folder):
    python benchmark.py
    python benchmark.py --llm-file path/to/cdm_entities.json
    python benchmark.py --spacy-dir path/to/spacy/output/
    python benchmark.py --output results/

Inputs (defaults look in the standard repo locations):
    --llm-file   JSON file with `{"results": [{"entity": ..., "entity_type": ...}, ...]}`
                 or just a list of entity dicts.
    --spacy-dir  Directory of CSV files from spacy_terms/output/step3*.csv
                 (each row has a `term` column).
"""
import argparse
import csv
import io
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

# Windows console defaults to cp1252; force UTF-8 for the ≥ character.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
else:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

HERE = Path(__file__).parent
REPO_ROOT = HERE.parent.parent
DEFAULT_LLM_GLOB = str(REPO_ROOT / "llm_terms" / "Output_final" / "**" / "*.cdm_entities.json")
DEFAULT_SPACY_GLOB = str(REPO_ROOT / "spacy_terms" / "output" / "step3_*.csv")

# ----------------------------------------------------------------------------
# Entity validation filter (rejects garbage entities at source)
# ----------------------------------------------------------------------------

_GARBAGE_AFFILIATIONS = re.compile(
    r"\b(department|division|institute|laboratory|school|college|"
    r"faculty|center|centre|university|hospital|clinic|genomic service|"
    r"hudson alpha|sequencing facility|core facility)\b",
    re.IGNORECASE,
)
_GARBAGE_JOURNALS = {
    "nucleic acids res", "nucleic acids research",
    "nature", "science", "cell", "pnas", "plos one",
    "front microbiol", "appl environ microbiol",
}
_GARBAGE_EXACT = {
    "ated", "ples", "demon-", "bi dobacterium", "mmol l",
    "rev", "f d", "l k", "c l", "base-",
    "bezoarsintestinal obstruction",
    "medium-chain fatty acidsscfas",
    "warty microora",
}
_GARBAGE_AUTHOR = re.compile(r"^\d+,\s+[A-Z][a-z]")
_GARBAGE_NUMERIC = re.compile(r"^[\d≤≥<>=+\-\.,\s]+$")
_GARBAGE_DNA_SEQ = re.compile(r"^[ACGT]{10,}$", re.IGNORECASE)
_GARBAGE_PRIMER = re.compile(r"[ACGT]{20,}", re.IGNORECASE)


def is_valid_entity(term: str) -> bool:
    """Return False if the term is a garbage entity."""
    t = (term or "").strip()
    if len(t) < 3:
        return False
    if t.startswith("-") or t.endswith("-"):
        return False
    if _GARBAGE_AUTHOR.match(t):
        return False
    if _GARBAGE_NUMERIC.match(t):
        return False
    if _GARBAGE_DNA_SEQ.match(t):
        return False
    if _GARBAGE_PRIMER.search(t):
        return False
    if _GARBAGE_AFFILIATIONS.search(t):
        return False
    if t.lower() in _GARBAGE_JOURNALS or t.lower() in _GARBAGE_EXACT:
        return False
    # Reject merged words (camelCase junction of two terms, e.g. "bezoarsintestinal")
    if re.search(r"[a-z][A-Z][a-z]", t) and not re.match(r"^[A-Z][a-z]+[A-Z]", t):
        # looks like two words merged — "bezoarsintestinal", "acidsscfas"
        # but keep legitimate camelCase like "Bifidobacterium", "Bacteroides"
        # Only reject if there's a lowercase->uppercase->lowercase transition
        # in the middle of the word (not at start)
        if re.search(r"[a-z][A-Z][a-z]", t[2:]):
            return False
    return True


def _normalize(s):
    """Lowercase, strip non-alphanum, collapse spaces."""
    if not s:
        return ""
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return s.strip()


def _token_set(s):
    return set(_normalize(s).split())


def _levenshtein(a, b):
    """Tiny Levenshtein for similarity scoring."""
    if a == b:
        return 1.0
    if not a or not b:
        return 0.0
    if len(a) > len(b):
        a, b = b, a
    prev = list(range(len(a) + 1))
    for i, ch_b in enumerate(b):
        cur = [i + 1]
        for j, ch_a in enumerate(a):
            cost = 0 if ch_a == ch_b else 1
            cur.append(min(cur[-1] + 1, prev[j + 1] + 1, prev[j] + cost))
        prev = cur
    dist = prev[-1]
    return 1.0 - dist / max(len(a), len(b))


def _ngram_set(s, n=3):
    """Return set of character n-grams (with padding)."""
    if not s:
        return set()
    s = f"^{s}$"
    return {s[i:i+n] for i in range(len(s) - n + 1)}


def _nearest_similarity(query, vocab_set):
    """Highest similarity to any vocab term, using n-gram Jaccard + token overlap.

    Replaces the O(len_a*len_b) Levenshtein with fast set-based n-gram Jaccard,
    which is O(|ngrams|) per comparison and avoids the quadratic blowup.
    """
    if not vocab_set:
        return (0.0, "")
    q_norm = _normalize(query)
    q_tokens = _token_set(query)
    q_ngrams = _ngram_set(q_norm)
    best = (0.0, "")
    for v in vocab_set:
        v_norm = _normalize(v)
        if not v_norm or not q_norm:
            continue
        # Fast n-gram Jaccard
        v_ngrams = _ngram_set(v_norm)
        if q_ngrams and v_ngrams:
            j_gram = len(q_ngrams & v_ngrams) / len(q_ngrams | v_ngrams)
        else:
            j_gram = 0.0
        # Token Jaccard for multi-word terms
        v_tokens = _token_set(v)
        if v_tokens and q_tokens:
            j_tok = len(v_tokens & q_tokens) / max(1, len(v_tokens | q_tokens))
        else:
            j_tok = 0.0
        sim = max(j_gram, j_tok)
        if sim > best[0]:
            best = (sim, v)
            if sim > 0.99:
                return best
    return best


def _flatten_llm(data):
    """Flatten various LLM JSON shapes into list of (term, type) tuples.

    The llm_terms/main.py pipeline writes:
        {"results": {"cdm_entities": {"CHEMICAL": [{"entity":..., ...}, ...], ...}, ...}, ...}
    We accept:
      - that nested form (results.cdm_entities.<TYPE>)
      - the simpler {"results": [<entity_dict>, ...]}  (older / other pipelines)
      - a top-level list
    """
    ents_holder = None
    if isinstance(data, dict):
        if "results" in data and isinstance(data["results"], dict):
            # nested cdm_entities form
            inner = data["results"].get("cdm_entities")
            if isinstance(inner, dict):
                # inner is {TYPE: [entity_dict, ...]}
                flat = []
                for etype, lst in inner.items():
                    for e in (lst or []):
                        if isinstance(e, dict):
                            flat.append({**e, "entity_type": etype})
                return flat
            # else: results is itself the entity list
            ents_holder = data["results"]
        elif "results" in data and isinstance(data["results"], list):
            ents_holder = data["results"]
        elif "entities" in data:
            ents_holder = data["entities"]
    elif isinstance(data, list):
        ents_holder = data
    return ents_holder or []


def load_llm_entities(llm_paths):
    """Return list of (raw_term, type) from one or more JSON files."""
    out = []
    n_rejected = 0
    for path in llm_paths:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as exc:
            print(f"  [skip] {path}: {exc}")
            continue
        for e in _flatten_llm(data):
            term = e.get("entity") or e.get("term") or ""
            etype = e.get("entity_type") or e.get("categories") or "UNKNOWN"
            if term:
                term = term.strip()
                if not is_valid_entity(term):
                    n_rejected += 1
                    continue
                out.append((term, str(etype).strip()))
    if n_rejected:
        print(f"  [filter] LLM: rejected {n_rejected} garbage entities")
    return out


def load_spacy_entities(spacy_paths):
    """Return list of (raw_term, label) from spacy CSV outputs."""
    out = []
    n_rejected = 0
    for path in spacy_paths:
        try:
            with open(path, "r", encoding="utf-8-sig", newline="") as f:
                content = f.read().replace("\x00", "")
            reader = csv.DictReader(io.StringIO(content))
            for row in reader:
                    term = row.get("term") or row.get("display_form") or ""
                    label = row.get("labels") or row.get("primary_label") or "ENTITY"
                    if term:
                        term = term.strip()
                        if not is_valid_entity(term):
                            n_rejected += 1
                            continue
                        out.append((term, label.strip()))
        except FileNotFoundError:
            continue
    if n_rejected:
        print(f"  [filter] spaCy: rejected {n_rejected} garbage entities")
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--llm-file", action="append", help="path to LLM entity JSON; can be repeated")
    parser.add_argument("--spacy-file", action="append", help="path to spaCy entity CSV; can be repeated")
    parser.add_argument("--llm-glob", default=DEFAULT_LLM_GLOB)
    parser.add_argument("--spacy-glob", default=DEFAULT_SPACY_GLOB)
    parser.add_argument("--output", default=str(HERE / "results"))
    parser.add_argument("--synonym-threshold", type=float, default=0.85,
                        help="Levenshtein/Jaccard similarity above which an LLM entity is classified as a synonym of a spaCy term")
    args = parser.parse_args()

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Discover files if not given explicitly.
    if args.llm_file:
        llm_paths = [Path(p) for p in args.llm_file]
    else:
        llm_paths = sorted(REPO_ROOT.glob(args.llm_glob))

    if args.spacy_file:
        spacy_paths = [Path(p) for p in args.spacy_file]
    else:
        spacy_paths = sorted(REPO_ROOT.glob(args.spacy_glob))

    print(f"LLM input files ({len(llm_paths)}):")
    for p in llm_paths:
        print(f"  {p}")
    print(f"spaCy input files ({len(spacy_paths)}):")
    for p in spacy_paths:
        print(f"  {p}")
    print()

    llm_ents = load_llm_entities(llm_paths)
    spacy_ents = load_spacy_entities(spacy_paths)

    print(f"Loaded {len(llm_ents)} LLM entities")
    print(f"Loaded {len(spacy_ents)} spaCy entities\n")

    # Build vocab sets (case-insensitive).
    llm_set = {_normalize(t) for t, _ in llm_ents if _normalize(t)}
    spacy_set = {_normalize(t) for t, _ in spacy_ents if _normalize(t)}
    spacy_lookup = {n: t for t, _ in spacy_ents for n in [_normalize(t)] if n}

    # Novel = in LLM, not in spaCy vocab.
    novel_norms = llm_set - spacy_set
    print(f"LLM entities (unique, normalized): {len(llm_set)}")
    print(f"spaCy entities (unique, normalized): {len(spacy_set)}")
    print(f"LLM-only (novel, before synonym filter): {len(novel_norms)}")
    print()

    # Classify each novel as synonym or truly-novel.
    novel_records = []
    for norm in novel_norms:
        # Find the original (raw) form for this norm.
        raw_form = next(
            (t for t, _ in llm_ents if _normalize(t) == norm), norm
        )
        sim, nearest = _nearest_similarity(norm, spacy_set)
        is_synonym = sim >= args.synonym_threshold
        novel_records.append({
            "term": raw_form,
            "norm": norm,
            "nearest_spacy": nearest,
            "similarity": round(sim, 3),
            "classification": "synonym" if is_synonym else "novel",
        })

    counts = Counter(r["classification"] for r in novel_records)
    print(f"After synonym filter (sim ≥ {args.synonym_threshold}):")
    print(f"  Synonym/variant of spaCy term:   {counts['synonym']:4d}")
    print(f"  Truly novel:                     {counts['novel']:4d}")
    print()

    # Top truly-novel candidates.
    truly_novel = [r for r in novel_records if r["classification"] == "novel"]
    truly_novel.sort(key=lambda r: (-r["similarity"], r["term"]))

    print("Top 20 truly-novel candidates (review these for the paper):")
    for r in truly_novel[:20]:
        print(f"  {r['term']:40s}  (nearest spaCy: {r['nearest_spacy'] or '(none)':30s}  sim={r['similarity']})")
    print()

    # Persist outputs.
    (out_dir / "llm_entity_set.txt").write_text(
        "\n".join(sorted(llm_set)) + "\n", encoding="utf-8"
    )
    (out_dir / "spacy_vocab_union.txt").write_text(
        "\n".join(sorted(spacy_set)) + "\n", encoding="utf-8"
    )

    csv_path = out_dir / "novel_entities.csv"
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=["term", "norm", "nearest_spacy", "similarity", "classification"]
        )
        writer.writeheader()
        for r in sorted(novel_records, key=lambda r: (r["classification"], r["term"].lower())):
            writer.writerow(r)
    print(f"Wrote: {csv_path}")

    summary = {
        "n_llm_unique": len(llm_set),
        "n_spacy_unique": len(spacy_set),
        "n_novel_raw": len(novel_norms),
        "n_synonym_classified": counts["synonym"],
        "n_truly_novel": counts["novel"],
        "synonym_threshold": args.synonym_threshold,
        "top_novel_candidates": [r["term"] for r in truly_novel[:20]],
        "verdict": (
            "supported" if counts["novel"] >= 50
            else ("weak" if counts["novel"] >= 10 else "falsified")
        ),
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"Wrote: {out_dir / 'summary.json'}")

    print()
    print("=" * 70)
    print(f"VERDICT: {summary['verdict']}  ({counts['novel']} truly novel entities)")
    print("=" * 70)


if __name__ == "__main__":
    main()
