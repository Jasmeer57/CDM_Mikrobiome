#!/usr/bin/env python3
"""Verify the hunflair2 span-trim re-run before it replaces the shipped CSV.

Background
----------
The shipped run (job 28643869) called flair with ``use_tokenizer=False``, so the
tagger returned the raw whitespace-token *window* of each span.  Those windows
routinely carry trailing punctuation (22.5% of rows) and embedded newlines
(12.5%).  The old runner compared ``text[start:end] != p["text"]`` before
writing, so any window whose surface did not match byte-for-byte was silently
discarded -- which meant the *good* spans were the ones being dropped.

The fix (approved 2026-10-28, notebook Cell 19) trims each window to its
non-whitespace, non-punctuation core in ``hunflair2._trim_span``, so the stored
term is ``text[start:end]`` by construction and the slice check passes.

Consequence: the re-run legitimately has *more* rows than the shipped CSV.
Trimming does not only shorten spans, it also recovers the spans the old slice
check rejected.  A "row count must not increase" assertion is therefore wrong,
and this script does not make it.  What it does assert is the mechanism:

  1. No surviving term may have leading/trailing whitespace or edge punctuation
     (that is the entire point of the trim).
  2. Every new span that is not contained in some old span must be explained by
     trimming -- i.e. its untrimmed window must have had edge junk.  A span with
     no edge junk and no old counterpart would mean the model itself changed.
  3. The trimmed vocabulary must not lose anything: after applying the same edge
     trim to both sides, the kept-term sets must agree.
  4. Offsets slice-verify against the segmented-section text (NUL bytes are a
     known corpus artifact, counted separately from failures).
  5. No internal duplicate spans.

Exit code is non-zero on any failed invariant (fail-closed).

Usage
-----
    PYTHONPATH=src python src/scripts/verify_hunflair2_trim.py \
        --new outputs/results/28649224_ner_hunflair2_trim \
        --old outputs/results/28643869_ner_extra_variants
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import re
import sys

REPO = str(next(p for p in __import__("pathlib").Path(__file__).resolve().parents if (p / ".cdm_root").is_file()))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, REPO)

from cdm_pipeline import dedup as dd  # noqa: E402
from cdm_pipeline.ner.runner_sections import load_sections  # noqa: E402

DEFAULT_NEW = os.path.join(REPO, "outputs/results", "28649224_ner_hunflair2_trim")
DEFAULT_OLD = os.path.join(REPO, "outputs/results", "28643869_ner_extra_variants")
CSV_NAME = "hunflair2_ner.csv"

# Same edge set the trimmer uses (src/cdm_pipeline/ner/hunflair2.py:_PUNCT_TRIM),
# applied after normalization so the vocabulary comparison ignores exactly the
# punctuation the trim was designed to remove.
_EDGE = ",.;:)]}\"'-([{"


def _edge_trim(s):
    return s.strip().strip(_EDGE).strip()


def build_text_index(seg_dir=None):
    """(paper, section_id, path) -> text, plus a paper-level fallback map.

    Section-level NER stores `section_id` as a section *type* and `path` as the
    heading, and `(paper, section_id)` is not unique, so the key has to carry
    all three fields.  Anything that still misses falls back to a paper-level
    concatenation, mirroring what the offset verifier does.
    """
    units, _stats = load_sections(seg_dir or os.path.join(REPO, "data/segmented_sections_markdown"))
    by_key = {}
    by_paper = collections.defaultdict(list)
    for u in units:
        text = u.get("text") or ""
        by_key[(u.get("cid"), u.get("section_id"), u.get("path"))] = text
        by_paper[u.get("cid")].append(text)
    return by_key, {k: "\n".join(v) for k, v in by_paper.items()}


def check_offsets(rows, by_key, by_paper):
    """Slice-verify every span.  NUL bytes are a known corpus artifact."""
    ok = nul_explained = unexplained = 0
    samples = []
    for r in rows:
        term = (r.get("term") or "").strip()
        try:
            start = int(r.get("char_start") or -1)
        except (TypeError, ValueError):
            unexplained += 1
            continue
        try:
            end = int(r.get("char_end") or -1)
        except (TypeError, ValueError):
            unexplained += 1
            continue
        key = (r.get("paper"), r.get("section_id"), r.get("section_path"))
        text = by_key.get(key)
        if text is None:
            text = by_paper.get(r.get("paper"), "")
        if start < 0 or end > len(text) or start >= end:
            unexplained += 1
            if len(samples) < 5:
                samples.append((r.get("paper"), term[:40], start, end, "out_of_range"))
            continue
        sliced = text[start:end]
        if sliced.strip() == term:
            ok += 1
        elif sliced.replace("\x00", "").strip() == term.replace("\x00", "").strip():
            nul_explained += 1
        else:
            unexplained += 1
            if len(samples) < 5:
                samples.append((r.get("paper"), term[:40], sliced[:60], start, "slice_mismatch"))
    return {"ok": ok, "nul_explained": nul_explained,
            "unexplained": unexplained, "samples": samples}


def check_no_edge_junk(rows):
    """Invariant 1: the trim must leave no edge whitespace or edge punctuation."""
    bad_ws = [r for r in rows if (r.get("term") or "") != (r.get("term") or "").strip()]
    bad_p = [r for r in rows
             if (r.get("term") or "").strip()
             and (r.get("term") or "").strip()[-1] in _EDGE]
    return bad_ws, bad_p


def check_span_provenance(new_rows, old_rows, text_index):
    """Invariant 2: every unexplained new span must have had edge junk to trim.

    A new span is 'explained' when some old span on the same section contains it
    (the normal trim case: the window shrank).  When no old span contains it, the
    old runner must have *rejected* it, which can only happen if its untrimmed
    window carried edge whitespace or punctuation -- the old slice check compared
    the raw window against the emitted surface and dropped mismatches.
    """
    old_idx = collections.defaultdict(list)
    for r in old_rows:
        try:
            old_idx[(r.get("paper"), r.get("section_id"))].append(
                (int(r.get("char_start")), int(r.get("char_end"))))
        except (TypeError, ValueError):
            continue

    recovered_trailing = recovered_leading = contained = 0
    inexplicable = []
    for r in new_rows:
        key = (r.get("paper"), r.get("section_id"))
        try:
            s, e = int(r.get("char_start")), int(r.get("char_end"))
        except (TypeError, ValueError):
            continue
        if any(a <= s and e <= b for a, b in old_idx.get(key, [])):
            contained += 1
            continue
        text = text_index.get(key)
        if text is None:
            inexplicable.append((key, s, e, "no_text"))
            continue
        s2, e2 = s, e
        while s2 > 0 and (text[s2 - 1].isspace() or text[s2 - 1] in _EDGE):
            s2 -= 1
        while e2 < len(text) and (text[e2].isspace() or text[e2] in _EDGE):
            e2 += 1
        if e2 > e:
            recovered_trailing += 1
        if s2 < s:
            recovered_leading += 1
        if s2 == s and e2 == e:
            inexplicable.append((key, s, e, (r.get("term") or "")[:50]))

    return {
        "contained_in_old": contained,
        "recovered_by_trailing_trim": recovered_trailing,
        "recovered_by_leading_trim": recovered_leading,
        "inexplicable": inexplicable,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--new", default=DEFAULT_NEW, help="trim re-run directory")
    ap.add_argument("--old", default=DEFAULT_OLD, help="directory with the shipped CSV")
    ap.add_argument("--output", default=None, help="write the report JSON here")
    args = ap.parse_args()

    new_csv = os.path.join(args.new, CSV_NAME)
    old_csv = os.path.join(args.old, CSV_NAME)
    if not os.path.exists(new_csv):
        print(f"FAIL: trim re-run not found: {new_csv}")
        return 1
    if not os.path.exists(old_csv):
        print(f"FAIL: shipped CSV not found: {old_csv}")
        return 1

    new_rows = dd.load_csv_safe(new_csv)
    old_rows = dd.load_csv_safe(old_csv)
    failures = []

    print(f"shipped : {len(old_rows):,} rows  {old_csv}")
    print(f"trimmed : {len(new_rows):,} rows  {new_csv}")
    if not new_rows:
        print("FAIL: trim re-run is empty")
        return 1

    # ── Junk accounting (same filter the registry uses) ──────────────────────
    old_reasons = collections.Counter(dd.classify_row(r)[0] for r in old_rows)
    new_reasons = collections.Counter(dd.classify_row(r)[0] for r in new_rows)
    old_junk = old_reasons["junk_or_short"]
    new_junk = new_reasons["junk_or_short"]
    print(f"junk rows: {old_junk:,} -> {new_junk:,}")
    print(f"valid rows: {old_reasons[None]:,} -> {new_reasons[None]:,} "
          f"({new_reasons[None] - old_reasons[None]:+,})")

    # Residual junk is classified by the *reason* the shared filter rejects it,
    # not by our assumption.  None of it may be edge noise -- removing edge
    # whitespace/punctuation is exactly what the trim is for, so any surviving
    # edge-noise row means the trim is incomplete.  Multi-line spans and
    # short/numeric surfaces (`2890`, `N2`, `O2` -- strain accessions and
    # chemical formulae) are legitimate tagger output that `is_junk` rejects by
    # design; they are recorded, not treated as trim failures.
    residual = collections.Counter()
    edge_noise = []
    for r in new_rows:
        if dd.classify_row(r)[0] != "junk_or_short":
            continue
        raw = r.get("term") or ""
        t = raw.strip()
        if raw != t or (t and t[-1] in _EDGE):
            residual["edge_noise"] += 1
            if len(edge_noise) < 10:
                edge_noise.append(raw[:60])
        elif "\n" in t or "\t" in t:
            residual["embedded_newline"] += 1
        elif len(t) < 3:
            residual["short_or_numeric"] += 1
        elif not any(c.isalpha() for c in t):
            residual["short_or_numeric"] += 1
        elif re.search(r"[a-z]\)", t) and len(t) < 30:
            # `is_junk`'s reference-marker heuristic (catches `disease)47`) also
            # rejects legitimate parenthetical terms such as
            # `immunoglobulin (Ig) A` / `neuro(auto)immune diseases`.  This is a
            # pre-existing filter property, unrelated to the span trim.
            residual["paren_heuristic_false_positive"] += 1
        else:
            residual["other"] += 1
    print(f"residual junk composition: {dict(sorted(residual.items()))}")
    if residual.get("edge_noise"):
        failures.append(f"{residual['edge_noise']:,} junk rows still carry edge noise -- "
                        "the trim did not run on them")
        for s in edge_noise:
            print(f"  edge noise: {s!r}")
    if residual.get("other"):
        failures.append(f"{residual['other']:,} junk rows fall outside every known class")

    # ── Invariant 1: no edge junk survives ───────────────────────────────────
    bad_ws, bad_p = check_no_edge_junk(new_rows)
    print(f"edge whitespace in term: {len(bad_ws):,}   edge punctuation: {len(bad_p):,}")
    if bad_ws:
        failures.append(f"{len(bad_ws):,} terms still carry leading/trailing whitespace")
    if bad_p:
        failures.append(f"{len(bad_p):,} terms still end in edge punctuation")

    # ── Invariant 3: vocabulary is not lost ──────────────────────────────────
    def kept_terms(rows, edge_trim):
        out = set()
        for r in rows:
            reason, parsed = dd.classify_row(r)
            if reason is None:
                out.add(edge_trim(parsed[0]))
        return out

    old_core = kept_terms(old_rows, _edge_trim)
    new_core = kept_terms(new_rows, _edge_trim)
    lost = old_core - new_core
    gained = new_core - old_core
    print(f"kept terms (core): {len(old_core):,} -> {len(new_core):,} "
          f"(lost {len(lost):,}, gained {len(gained):,})")
    if lost:
        failures.append(f"trim lost {len(lost):,} distinct vocabularies")
        for t in sorted(lost)[:10]:
            print(f"  lost: {t!r}")

    # ── Invariant 4: offsets slice-verify ────────────────────────────────────
    by_key, by_paper = build_text_index()
    offs = check_offsets(new_rows, by_key, by_paper)
    print(f"offsets: ok={offs['ok']:,} nul_explained={offs['nul_explained']:,} "
          f"unexplained={offs['unexplained']:,}")
    if offs["unexplained"]:
        failures.append(f"{offs['unexplained']:,} offset mismatches")
        for s in offs["samples"]:
            print(f"  {s}")

    # ── Invariant 2: span provenance ─────────────────────────────────────────
    text_index = {(u["cid"], u["section_id"]): (u.get("text") or "")
                  for u in load_sections(os.path.join(REPO, "data/segmented_sections_markdown"))[0]}
    prov = check_span_provenance(new_rows, old_rows, text_index)
    print(f"new spans contained in an old span: {prov['contained_in_old']:,}")
    print(f"  recovered by trailing-edge trim : {prov['recovered_by_trailing_trim']:,}")
    print(f"  recovered by leading-edge trim  : {prov['recovered_by_leading_trim']:,}")
    print(f"  inexplicable                    : {len(prov['inexplicable']):,}")
    if prov["inexplicable"]:
        failures.append(f"{len(prov['inexplicable']):,} new spans have no old counterpart "
                        "and no edge junk -- the model behaviour changed, not just the trim")
        for x in prov["inexplicable"][:10]:
            print(f"  {x}")

    # ── Invariant 5: no internal duplicates ──────────────────────────────────
    seen = collections.Counter(
        (r.get("paper"), r.get("section_id"), r.get("char_start"),
         r.get("char_end"), (r.get("term") or "").strip()) for r in new_rows)
    dupes = sum(v - 1 for v in seen.values() if v > 1)
    print(f"internal duplicate rows: {dupes:,}")
    if dupes:
        failures.append(f"{dupes:,} duplicate spans")

    papers = {r.get("paper") for r in new_rows if (r.get("term") or "").strip()}
    print(f"papers with entities: {len(papers):,}")

    verdict = "PASS" if not failures else "FAIL"
    report = {
        "verdict": verdict,
        "shipped_csv": old_csv,
        "trimmed_csv": new_csv,
        "rows_shipped": len(old_rows),
        "rows_trimmed": len(new_rows),
        "rows_delta": len(new_rows) - len(old_rows),
        "valid_rows_shipped": old_reasons[None],
        "valid_rows_trimmed": new_reasons[None],
        "junk_rows_shipped": old_junk,
        "junk_rows_trimmed": new_junk,
        "residual_junk_composition": dict(residual),
        "edge_whitespace_terms": len(bad_ws),
        "edge_punctuation_terms": len(bad_p),
        "kept_terms_shipped": len(old_core),
        "kept_terms_trimmed": len(new_core),
        "terms_lost": len(lost),
        "terms_gained": len(gained),
        "offsets": {k: v for k, v in offs.items() if k != "samples"},
        "span_provenance": {
            "contained_in_old": prov["contained_in_old"],
            "recovered_by_trailing_trim": prov["recovered_by_trailing_trim"],
            "recovered_by_leading_trim": prov["recovered_by_leading_trim"],
            "inexplicable": len(prov["inexplicable"]),
        },
        "papers_with_entities": len(papers),
        "internal_duplicates": dupes,
        "failures": failures,
    }
    out = args.output or os.path.join(args.new, "_trim_verification.json")
    try:
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2, sort_keys=True)
            fh.write("\n")
        print(f"wrote {out}")
    except OSError:
        alt = os.path.join("/tmp", "hunflair2_trim_verification.json")
        with open(alt, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2, sort_keys=True)
            fh.write("\n")
        print(f"results dir read-only; wrote {alt}")

    if failures:
        print("\nFAIL:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nPASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
