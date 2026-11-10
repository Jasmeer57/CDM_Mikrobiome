#!/usr/bin/env python
"""MeSH gazetteer NER over the segmented corpus — CPU only, no GPU, no LLM.

Approach: dictionary matching against the local MeSH 2026 XML dumps
(``outputs/results/mesh_ner/raw/{desc,supp}2026.xml``) with an Aho-Corasick automaton
(``pyahocorasick``), matching the *exact* section/offset semantics used by the
CPU ensemble and the LLM runner (``cdm_pipeline.ner.runner_sections``), so the
output rows are directly comparable and join cleanly on
``(paper, section_id, char_start, char_end)``.

This is a gazetteer, not a model: it has no notion of context. That is a real
limitation and is reported as such — see the ``caveats`` block in the summary.
To keep the noise bounded it applies four filters that are all recorded in the
output summary:

1. **branch filter** — descriptors are kept only if they carry a tree number in
   a CDM-relevant MeSH branch; non-relevant branches (K humanities,
   V publication characteristics, Z geography) are dropped by default.
2. **term quality** — terms shorter than ``--min_chars`` or made only of
   punctuation/digits are dropped, as are pure ``CODE`` tokens (all-uppercase
   alphanumeric strings ≤ 8 chars, which are overwhelmingly drug/registry codes
   such as ``SAMP`` or ``MLN02``).
3. **word boundaries** — a match must not be flanked by an alphanumeric
   character, so ``men`` no longer fires inside ``women`` and ``art`` no longer
   fires inside ``start``.
4. **ambiguous-word deny-list** — a small curated list of high-frequency
   English words that are legitimate MeSH headings but hopeless as a
   context-free gazetteer (``art``, ``men``, ``table``, ``wit``, ...).

Matching is longest-match-first with no nesting: among overlapping candidates
the longest wins, ties broken left-most.

Outputs (under ``--out_dir``, default ``outputs/results/mesh_ner``):

    mesh_ner_terms.csv         CPU-schema rows: term,labels,model,paper,
                               section_id,section_path,char_start,char_end
                               (``model`` is fixed to ``mesh-gazetteer``)
    mesh_term_stats.csv        per distinct term: mesh_ui, mesh_tree, cdm_type,
                               kind (descriptor/supplemental), n_hits, papers
    mesh_gazetteer.jsonl       the gazetteer itself, one record per term
    _mesh_summary.json         counts, filters applied, caveats, coverage

Usage:
    python src/scripts/vllm_termpop/mesh_gazetteer_ner.py --out_dir outputs/results/mesh_ner
    python src/scripts/vllm_termpop/mesh_gazetteer_ner.py --max_files 5   # smoke test
"""
import argparse
import csv
import json
import os
import re
import sys
import time
import warnings
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

warnings.filterwarnings("ignore")

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from pipeline.s04_ner.runner_sections import load_sections  # noqa: E402

SEG_DIR_DEFAULT = REPO_ROOT / "data/segmented_sections_markdown"
RAW_DIR = REPO_ROOT / "outputs/results" / "mesh_ner" / "raw"
MODEL_NAME = "mesh-gazetteer"

# ── MeSH tree branch -> CDM type ──
# Two-letter rules win over the one-letter default. Branches absent from both
# maps are dropped (that is the branch filter).
_TWO_LETTER = {
    "G02": "CHEMICAL",           # Chemical phenomena
    "G03": "PATHWAY",            # Metabolism / metabolic phenomena
    "G04": "CELL_TYPE",          # Cell physiological phenomena
    "G05": "GENOMICS",           # Genetic phenomena
    "G06": "ORGANISM",           # Microbiological phenomena
    "G12": "PROTEIN",            # Amino acids / peptides / proteins
    "E01": "CLINICAL",           # Diagnosis
    "E02": "CLINICAL",           # Therapeutics
    "E03": "CLINICAL",           # Anesthesia / analgesia
    "E06": "CLINICAL",           # Dentistry
    "E04": "EXPERIMENTAL_METHOD",  # Surgical procedures
    "E05": "LAB_METHOD",         # Investigative techniques
    "E07": "LAB_METHOD",         # Equipment and supplies
    "L01": "DATA_ANALYSIS",      # Information science
}
_ONE_LETTER = {
    "A": "CELL_TYPE",   # Anatomy
    "B": "ORGANISM",    # Organisms
    "C": "DISEASE",     # Diseases
    "D": "CHEMICAL",    # Chemicals and Drugs
    "E": "LAB_METHOD",  # Analytical/Diagnostic/Therapeutic Techniques
    "F": "CLINICAL",    # Psychiatry and Psychology
    "G": "PATHWAY",     # Phenomena and Processes
    "H": "STUDY_DESIGN",  # Disciplines and Occupations
    "I": "CLINICAL",    # Anthropology/Education/Sociology
    "J": "CHEMICAL",    # Technology, Industry, Agriculture
    "L": "DATA_ANALYSIS",  # Information Science
    "M": "CLINICAL",    # Named Groups
    "N": "CLINICAL",    # Health Care
}
DEFAULT_BRANCHES = "ABCDEFGHIJLMN"

# Curated deny-list: valid MeSH headings that are unusable in a context-free
# gazetteer because they are ordinary high-frequency English words.
AMBIGUOUS = {
    "a", "art", "arts", "men", "man", "woman", "women", "table", "tables",
    "wit", "sir", "may", "june", "march", "cell", "cells", "acid", "acids",
    "air", "animal", "animals", "back", "bit", "blood", "body", "bone", "care",
    "case", "cases", "cat", "cats", "child", "children", "class", "clear",
    "cold", "com", "core", "data", "day", "days", "death", "dog", "dogs",
    "dose", "drug", "drugs", "end", "eye", "eyes", "face", "fact", "family",
    "fat", "fever", "fire", "fish", "food", "force", "form", "free", "gas",
    "gene", "germ", "gland", "grow", "hand", "hands", "head", "health",
    "heart", "heat", "high", "home", "host", "human", "humans", "ice",
    "image", "iron", "job", "key", "knee", "lab", "land", "lead", "life",
    "light", "line", "liver", "loss", "lot", "low", "male", "map", "mass",
    "men", "mind", "moon", "mouse", "mice", "mouth", "music", "nation",
    "neck", "need", "nerve", "new", "nose", "nurse", "oil", "old", "order",
    "organ", "pain", "paper", "past", "person", "pig", "pigs", "plant",
    "point", "police", "pool", "poor", "power", "press", "protein", "race",
    "rain", "rat", "rats", "rate", "red", "rest", "rice", "ring", "risk",
    "rock", "room", "root", "row", "rule", "run", "salt", "scale", "sea",
    "seat", "set", "sex", "shape", "ship", "shock", "shot", "sign", "size",
    "skin", "sky", "sleep", "small", "smoke", "snow", "soft", "soil", "solid",
    "son", "sport", "staff", "stage", "star", "state", "steel", "stock",
    "stone", "store", "stress", "sun", "sweet", "table", "taste", "team",
    "test", "tests", "thick", "thin", "time", "times", "tissue", "toe",
    "tone", "tool", "top", "town", "toy", "tree", "type", "types", "unit",
    "units", "war", "warm", "water", "wave", "way", "week", "weight", "well",
    "wind", "wing", "wire", "wood", "work", "year", "years", "young", "zone",
}
CODE_RE = re.compile(r"^[A-Z0-9][A-Z0-9\-]{1,7}$")
NONALNUM_RE = re.compile(r"[^a-z0-9]+")
HAS_ALNUM_RE = re.compile(r"[a-z0-9]")


def cdm_from_tree(trees):
    """First (most specific) tree number -> CDM type via the branch maps.

    MeSH tree numbers are ``<branch>.<sub>...`` where the branch is one letter
    or one letter + two digits (``G06.591``), so the specific rule keys are
    three characters long, not two.
    """
    for t in trees:
        three = t[:3]
        if three in _TWO_LETTER:
            return _TWO_LETTER[three]
        one = t[:1]
        if one in _ONE_LETTER:
            return _ONE_LETTER[one]
    return ""


def branch_of(trees):
    return trees[0][:1] if trees else ""


class Gazetteer:
    """term(lower) -> {term, uis, kinds, trees, cdm, pref}."""

    def __init__(self):
        self.recs = {}
        self.dropped = Counter()

    def add(self, term, ui, kind, trees, cdm, pref, min_chars):
        s = (term or "").strip()
        low = s.lower()
        if len(s) < min_chars:
            self.dropped["too_short"] += 1
            return
        if not HAS_ALNUM_RE.search(low) or NONALNUM_RE.sub("", low) == "":
            self.dropped["no_alnum"] += 1
            return
        if CODE_RE.match(s) and s.upper() == s and not any(c.islower() for c in s):
            self.dropped["code_token"] += 1
            return
        if low in AMBIGUOUS:
            self.dropped["ambiguous"] += 1
            return
        r = self.recs.get(low)
        if r is None:
            self.recs[low] = {"term": s, "uis": [ui], "kinds": [kind],
                              "trees": list(trees), "cdm": cdm, "pref": pref}
        else:
            if ui not in r["uis"]:
                r["uis"].append(ui)
            if kind not in r["kinds"]:
                r["kinds"].append(kind)
            if not r["cdm"] and cdm:
                r["cdm"] = cdm
            r["pref"] = r["pref"] or pref
            for t in trees:
                if t not in r["trees"]:
                    r["trees"].append(t)


def iter_descriptors(path):
    for _ev, el in ET.iterparse(path, events=("end",)):
        if el.tag == "DescriptorRecord":
            yield el
            el.clear()


def iter_supplementals(path):
    for _ev, el in ET.iterparse(path, events=("end",)):
        if el.tag == "SupplementalRecord":
            yield el
            el.clear()


def build_gazetteer(desc_path, supp_path, branches, min_chars, include_supp):
    gz = Gazetteer()
    ui2cdm, ui2branch = {}, {}

    n_desc = n_desc_kept = 0
    t0 = time.time()
    for el in iter_descriptors(desc_path):
        n_desc += 1
        ui = (el.findtext("DescriptorUI") or "").strip()
        trees = [(t.text or "").strip() for t in el.iter("TreeNumber")]
        trees = [t for t in trees if t]
        br = branch_of(trees)
        cdm = cdm_from_tree(trees)
        ui2cdm[ui] = cdm
        ui2branch[ui] = br
        # branch filter applies to descriptors only; supplementals inherit
        if branches and (not br or br not in branches):
            continue
        n_desc_kept += 1
        gz.add(el.findtext("DescriptorName/String") or "", ui, "descriptor",
               trees, cdm, True, min_chars)
        for c in el.iter("Concept"):
            for t in c.iter("Term"):
                if t.get("IsPermutedTermYN") == "Y":
                    continue
                gz.add(t.findtext("String") or "", ui, "descriptor",
                       trees, cdm, False, min_chars)
    print(f"  descriptors: {n_desc} parsed, {n_desc_kept} kept after branch filter "
          f"({time.time()-t0:.1f}s)")

    n_supp = 0
    if include_supp:
        for el in iter_supplementals(supp_path):
            n_supp += 1
            ui = (el.findtext("SupplementalRecordUI") or "").strip()
            ds = [(d.text or "").strip().lstrip("*")
                  for d in el.findall("HeadingMappedToList/HeadingMappedTo/"
                                      "DescriptorReferredTo/DescriptorUI")]
            cdm, br, trees = "", "", []
            for d in ds:
                if ui2cdm.get(d):
                    cdm, br = ui2cdm[d], ui2branch.get(d, "")
                    break
            if branches and (not br or br not in branches):
                gz.dropped["supp_branch"] += 1
                continue
            for d in ds:
                if ui2cdm.get(d):
                    cdm = cdm or ui2cdm[d]
            gz.add(el.findtext("SupplementalRecordName/String") or "", ui,
                   "supplemental", trees, cdm, True, min_chars)
            for c in el.iter("Concept"):
                for t in c.iter("Term"):
                    if t.get("IsPermutedTermYN") == "Y":
                        continue
                    gz.add(t.findtext("String") or "", ui, "supplemental",
                           trees, cdm, False, min_chars)
        print(f"  supplementals: {n_supp} parsed ({time.time()-t0:.1f}s)")

    return gz, n_desc, n_desc_kept, n_supp


def build_automaton(recs):
    import ahocorasick
    A = ahocorasick.Automaton()
    for k in recs:
        A.add_word(k, k)
    A.make_automaton()
    return A


def match_text(text, A, recs):
    """Longest-match, non-nesting, boundary-respecting matches.

    Returns list of (start, end, term_lower, rec).
    """
    low = text.lower()
    n = len(low)
    raw = []
    for end, k in A.iter(low):
        s = end + 1 - len(k)
        # word boundaries: no alnum immediately outside the span
        if s > 0 and low[s - 1].isalnum():
            continue
        if end + 1 < n and low[end + 1].isalnum():
            continue
        raw.append((s, end + 1, k))
    if not raw:
        return []
    # longest first, then left-most
    raw.sort(key=lambda x: (x[0], -(x[1] - x[0])))
    out, last_end = [], -1
    for s, e, k in raw:
        if s >= last_end:
            out.append((s, e, k, recs[k]))
            last_end = e
    return out


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seg_dir", default=str(SEG_DIR_DEFAULT))
    ap.add_argument("--raw_dir", default=str(RAW_DIR))
    ap.add_argument("--out_dir", default=str(REPO_ROOT / "outputs/results" / "mesh_ner"))
    ap.add_argument("--branches", default=DEFAULT_BRANCHES,
                    help="MeSH tree branches to keep (default %(default)s); '' = all")
    ap.add_argument("--min_chars", type=int, default=4)
    ap.add_argument("--no_supplemental", action="store_true",
                    help="Descriptors only (smaller, curated gazetteer)")
    ap.add_argument("--max_files", type=int, default=None)
    ap.add_argument("--include_backmatter", action="store_true")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = Path(args.raw_dir)
    desc_path = raw_dir / "desc2026.xml"
    supp_path = raw_dir / "supp2026.xml"
    for p in (desc_path, supp_path):
        if not p.exists():
            print(f"ERROR: missing MeSH dump {p}", file=sys.stderr)
            return 2

    t_start = time.time()
    branches = set(args.branches) if args.branches else set()
    print("=" * 72)
    print("MeSH gazetteer NER (CPU, no GPU, no LLM)")
    print(f"  seg_dir      : {args.seg_dir}")
    print(f"  raw_dir      : {raw_dir}")
    print(f"  out_dir      : {out_dir}")
    print(f"  branches     : {args.branches or 'ALL'}")
    print(f"  min_chars    : {args.min_chars}")
    print(f"  supplemental : {not args.no_supplemental}")
    print("=" * 72)

    print("\n[1/5] building gazetteer")
    gz, n_desc, n_desc_kept, n_supp = build_gazetteer(
        desc_path, supp_path, branches, args.min_chars, not args.no_supplemental)
    recs = gz.recs
    print(f"  gazetteer terms: {len(recs)}")
    print(f"  dropped: {dict(gz.dropped)}")
    print(f"  cdm_type coverage: {Counter(r['cdm'] or 'UNMAPPED' for r in recs.values()).most_common()}")

    print("\n[2/5] building automaton")
    t0 = time.time()
    A = build_automaton(recs)
    print(f"  {len(A)} patterns ({time.time()-t0:.1f}s)")

    print("\n[3/5] loading sections")
    units, stats = load_sections(Path(args.seg_dir), max_files=args.max_files,
                                body_only=not args.include_backmatter)
    body_chars = sum(len(u["text"]) for u in units)
    print(f"  {len(stats)} papers, {len(units)} sections, {body_chars:,} chars")

    print("\n[4/5] matching")
    t0 = time.time()
    rows = []
    term_hits = Counter()
    term_papers = defaultdict(set)
    per_paper_hits = Counter()
    for i, u in enumerate(units, 1):
        for s, e, k, rec in match_text(u["text"], A, recs):
            rows.append({
                "term": u["text"][s:e],
                "labels": rec["cdm"] or "MESH",
                "model": MODEL_NAME,
                "paper": u["cid"],
                "section_id": u["section_id"],
                "section_path": u["path"],
                "char_start": s,
                "char_end": e,
            })
            term_hits[k] += 1
            term_papers[k].add(u["cid"])
        per_paper_hits[u["cid"]] += 1
        if i % 200 == 0 or i == len(units):
            print(f"  {i}/{len(units)} sections, {len(rows):,} rows "
                  f"({time.time()-t0:.0f}s)", flush=True)
    print(f"  matched {len(rows):,} spans over {len(units)} sections"
          f" ({time.time()-t0:.1f}s)")

    print("\n[5/5] writing outputs")
    FIELDS = ["term", "labels", "model", "paper", "section_id", "section_path",
              "char_start", "char_end"]
    terms_csv = out_dir / "mesh_ner_terms.csv"
    with open(terms_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    stats_csv = out_dir / "mesh_term_stats.csv"
    with open(stats_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["term", "mesh_ui", "mesh_tree", "cdm_type", "kind",
                    "n_hits", "n_papers"])
        for k, n in term_hits.most_common():
            r = recs[k]
            w.writerow([r["term"], ";".join(r["uis"]),
                        ";".join(r["trees"][:4]), r["cdm"] or "UNMAPPED",
                        ";".join(r["kinds"]), n, len(term_papers[k])])

    gz_jsonl = out_dir / "mesh_gazetteer.jsonl"
    with open(gz_jsonl, "w", encoding="utf-8") as f:
        for k, r in recs.items():
            f.write(json.dumps({
                "term_lower": k, "term": r["term"], "mesh_ui": r["uis"],
                "mesh_tree": r["trees"], "cdm_type": r["cdm"],
                "kind": r["kinds"], "preferred": r["pref"],
            }, ensure_ascii=False) + "\n")

    lab_counts = Counter(r["labels"] for r in rows)
    summary = {
        "model": MODEL_NAME,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "approach": "Aho-Corasick gazetteer match against local MeSH 2026 XML dumps",
        "mesh_dumps": {
            "desc2026.xml": str(desc_path),
            "supp2026.xml": str(supp_path),
            "descriptors_parsed": n_desc,
            "descriptors_kept": n_desc_kept,
            "supplementals_parsed": n_supp,
        },
        "gazetteer": {
            "n_terms": len(recs),
            "branches": args.branches or "ALL",
            "min_chars": args.min_chars,
            "include_supplemental": not args.no_supplemental,
            "dropped": dict(gz.dropped),
        },
        "corpus": {
            "seg_dir": str(args.seg_dir),
            "papers": len(stats),
            "sections": len(units),
            "body_chars": body_chars,
            "include_backmatter": args.include_backmatter,
        },
        "output": {
            "rows": len(rows),
            "distinct_terms_matched": len(term_hits),
            "distinct_terms_in_gazetteer": len(recs),
            "gazetteer_yield_pct": round(100.0 * len(term_hits) / len(recs), 3),
            "labels": lab_counts.most_common(),
            "papers_with_hits": len(per_paper_hits),
            "top_terms": [{"term": recs[k]["term"], "n_hits": n,
                           "cdm_type": recs[k]["cdm"]}
                          for k, n in term_hits.most_common(30)],
        },
        "caveats": [
            "Gazetteer matching has no context model: every literal string "
            "match is emitted regardless of whether the passage is actually "
            "about that concept. Expect false positives on ambiguous strings "
            "that survive the deny-list.",
            "This output is machine extraction, not human-verified annotation. "
            "It carries no verification_status and must not be treated as gold.",
            "CDM types are derived from the MeSH tree branch of the mapped "
            "descriptor; supplemental records inherit the type of their "
            "HeadingMappedTo descriptor and are UNMAPPED if untyped.",
            "Longest-match-only means nested shorter MeSH terms inside a longer "
            "match are not emitted (e.g. 'gut' inside 'gut microbiota').",
        ],
        "elapsed_seconds": round(time.time() - t_start, 1),
    }
    with open(out_dir / "_mesh_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print(f"  {terms_csv}  ({len(rows):,} rows)")
    print(f"  {stats_csv}  ({len(term_hits):,} distinct terms)")
    print(f"  {gz_jsonl}")
    print(f"  {out_dir / '_mesh_summary.json'}")
    print(f"\n  labels: {lab_counts.most_common()}")
    print(f"  top terms: {[t['term'] for t in summary['output']['top_terms'][:15]]}")
    print(f"\nDone in {summary['elapsed_seconds']}s -> {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
