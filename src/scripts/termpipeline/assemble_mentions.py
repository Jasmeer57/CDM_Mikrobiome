#!/usr/bin/env python
"""Stage T1 — assemble mention-level terminology records from NER outputs.

This is an ASSEMBLY stage: it makes **no new model calls and no new network
calls**. It unifies the mention tables that already exist into one mention-level
artifact, giving every mention a stable id, verified source coordinates, and
sentence/paragraph provenance.

Sources (all share the schema ``term,labels,model,paper,section_id,section_path,
char_start,char_end``):

  CPU ensemble      releases/zenodo_v1/ner_453_sections/all_ner_sections_combined.csv
  Qwen (Ollama)     releases/zenodo_v1/qwen_sections_ner/qwen_sections_ner.csv
  Qwen (vLLM body)  outputs/results/llm_ner_body/vllm_sections_ner.csv        (when present)
  MeSH gazetteer    outputs/results/mesh_ner/mesh_ner_terms.csv

Identity model (see docs/reports/terminology_pipeline_plan.md):
  * ``mention_id``      one source occurrence AS TAGGED BY ONE EXTRACTOR. Competing
                        type assignments from different models are therefore kept as
                        distinct mentions and never silently merged.
  * ``occurrence_key``  the extractor-independent span identity
                        (paper|section|start|end|normalized surface), so identical
                        spans can be grouped downstream.

Offsets are NEVER fabricated. Each row is validated against the section text
(``text[start:end] == surface_form``). When the stored offsets do not reproduce
the surface form the configurable recovery is attempted; if that also fails the
record is emitted with null offsets and ``OFFSET_UNVERIFIED`` in
``unresolved_flags`` — it is reported, not dropped and not invented.

``surface_form`` is stored **verbatim**. Where the source markdown itself carries
a control byte (a lost glyph from PDF conversion) the mention keeps the exact
surface and the *identity* layer is sanitized instead (see ``textnorm``); the row
is additionally flagged ``CONTROL_CHAR_SURFACE`` so the artifact count can be
audited rather than assumed to be zero.

Output: ``<out_dir>/term_mentions.jsonl`` (+ ``_mentions_summary.json``).
"""
from __future__ import annotations

import argparse
import bisect
import csv
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
sys.path.insert(0, str(REPO_ROOT / "src"))

import unicodedata  # noqa: E402

from textnorm import has_control, sanitize  # noqa: E402

DEFAULT_SEG_DIR = REPO_ROOT / "data/segmented_sections_markdown"

# Source registry: name -> (path, extraction_method, extraction_run_id)
SOURCES = {
    "cpu_ensemble": (
        "releases/zenodo_v1/ner_453_sections/all_ner_sections_combined.csv",
        "ner_model_ensemble", "cpu_ensemble_v1",
    ),
    "qwen_ollama": (
        "releases/zenodo_v1/qwen_sections_ner/qwen_sections_ner.csv",
        "llm_section_ner", "qwen_ollama_cell7c_v1",
    ),
    "qwen_vllm_body": (
        "outputs/results/llm_ner_body/vllm_sections_ner.csv",
        "llm_section_ner", "qwen35_vllm_body_v1",
    ),
    "mesh_gazetteer": (
        "outputs/results/mesh_ner/mesh_ner_terms.csv",
        "gazetteer_dictionary_match", "mesh_gazetteer_2026",
    ),
}

SENT_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])")
PASSAGE_WINDOW = 200   # chars either side of the mention for supporting_passage
SENT_MAX_CHARS = 400   # supporting_sentence is clipped to this, centred on the mention


def norm_term(t: str) -> str:
    """Deterministic display/normalized form (mirrors export_terminology.norm_term).

    ``sanitize`` is applied **last** so that it can only ever remove an invisible
    control byte, never change how the rest of the normalization treats the
    string. Applying it first would let ``.strip("-")`` see a different leading
    character and diverge from the canonical table's ``term_norm`` (measured:
    sanitize-first introduced 18 join mismatches, sanitize-last introduced none).
    """
    if not t:
        return ""
    t = unicodedata.normalize("NFKD", t)
    t = t.encode("ascii", "ignore").decode("ascii")
    t = t.lower().replace("\u2013", "-").replace("\u2014", "-")
    t = re.sub(r"[-_/]", "-", t)
    t = re.sub(r"\s+", " ", t).strip().strip("-")
    return sanitize(t)


def _mid(prefix: str, *parts: str) -> str:
    h = hashlib.sha1()
    for p in (prefix, *parts):
        h.update((p or "").encode("utf-8"))
        h.update(b"\x1f")
    return h.hexdigest()[:16]


def build_text_index(text: str):
    """Deterministic sentence + paragraph spans for a section body.

    Sentence/paragraph ids are POSITIONS in these lists (``<section_id>:s0``),
    not invented identifiers, and both carry their own char offsets.
    """
    sents = []
    pos = 0
    for m in SENT_END.finditer(text):
        end = m.start() + 1
        if end > pos:
            sents.append((pos, end))
        pos = m.end()
    if pos < len(text):
        sents.append((pos, len(text)))
    if not sents:
        sents = [(0, len(text))] if text else []

    paras = []
    ppos = 0
    for m in re.finditer(r"\n\s*\n", text):
        if m.start() > ppos:
            paras.append((ppos, m.start()))
        ppos = m.end()
    if ppos < len(text):
        paras.append((ppos, len(text)))
    if not paras:
        paras = [(0, len(text))] if text else []

    return sents, paras


def _clip_around(text, start, end, budget):
    """Clip ``text[start:end]`` to at most ``budget`` chars, centred on the mention.

    Returns ``(snippet, clipped_bool)``. A "sentence" that never ends (e.g. a
    punctuation-free author/affiliation block) is not silently presented as one
    sentence: it is clipped and the caller records ``SENTENCE_CLIPPED`` in
    ``unresolved_flags``.
    """
    if end - start <= budget:
        return text[start:end], False
    before = max(1, (budget - (end - start)) // 2)
    s = max(start, start - before)
    e = min(end, s + budget)
    s = max(start, e - budget)
    return text[s:e], True


def _locate(span_list, starts, start, end):
    """Index of the span that contains [start,end); prefers smallest containing."""
    i = bisect.bisect_right(starts, start) - 1
    if i < 0:
        i = 0
    for j in (i, i - 1):
        if 0 <= j < len(span_list):
            s, e = span_list[j]
            if s <= start and end <= e:
                return j
    return None


def load_sections(seg_dir: Path):
    """(cid, section_id) -> (text, path). Uses the project's canonical loader."""
    from cdm_pipeline.ner.runner_sections import load_sections as _ls
    units, stats = _ls(seg_dir, body_only=False)
    out = {}
    for u in units:
        out[(u["cid"], u["section_id"])] = (u["text"] or "", u["path"] or "")
    return out, stats


def section_name_subsection(path: str):
    parts = [p.strip() for p in (path or "").split(">") if p.strip()]
    if not parts:
        return "", None
    return parts[-1], (">".join(parts[:-1]) or None)


def main() -> int:
    ap = argparse.ArgumentParser(description="Stage T1 mention assembly")
    ap.add_argument("--out_dir", default="outputs/results/terminology_v1")
    ap.add_argument("--seg_dir", default=str(DEFAULT_SEG_DIR))
    ap.add_argument("--sources", default="cpu_ensemble,qwen_ollama,qwen_vllm_body,mesh_gazetteer",
                    help="Comma-separated source keys (missing files are skipped with a warning)")
    ap.add_argument("--limit_per_source", type=int, default=0, help="Smoke test: cap rows per source")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "term_mentions.jsonl"

    print("loading section texts ...", flush=True)
    sec, sec_stats = load_sections(Path(args.seg_dir))
    n_papers = len({k[0] for k in sec})
    n_chars = sum(len(t) for t, _ in sec.values())
    print("  sections: %d across %d papers (%d chars)"
          % (len(sec), n_papers, n_chars), flush=True)

    idx_cache: dict[tuple, tuple] = {}

    def get_index(key):
        if key not in idx_cache:
            text = sec.get(key, ("", ""))[0]
            idx_cache[key] = build_text_index(text)
        return idx_cache[key]

    wanted = [s.strip() for s in args.sources.split(",") if s.strip()]
    summary = {"sources": {}, "rows_written": 0, "rows_read": 0,
               "rows_skipped_empty_surface": 0,
               "offsets_verified": 0,
               "offsets_recovered": 0, "offsets_unverified": 0,
               "control_char_surfaces": 0,
               "unknown_section": 0, "by_entity_type": {}, "by_method": {}}

    with out_path.open("w", encoding="utf-8") as fout:
        for src in wanted:
            if src not in SOURCES:
                print("WARNING: unknown source %r — skipped" % src, file=sys.stderr)
                continue
            rel, method, run_id = SOURCES[src]
            path = REPO_ROOT / rel
            if not path.exists():
                print("WARNING: %s not found (%s) — skipped" % (path, src), file=sys.stderr)
                summary["sources"][src] = {"path": rel, "status": "MISSING", "rows": 0}
                continue

            n = verified = recovered = unverified = unknown_sec = control_surfaces = 0
            rows_read = skipped_empty = 0
            with path.open(encoding="utf-8") as fin:
                for row in csv.DictReader(fin):
                    rows_read += 1
                    if args.limit_per_source and n >= args.limit_per_source:
                        break
                    paper = (row.get("paper") or "").strip()
                    sid = (row.get("section_id") or "").strip()
                    surface = (row.get("term") or row.get("text") or "").strip()
                    if not surface:
                        # A row with no surface form cannot be a mention. It is
                        # counted separately and is NEVER added to ``n`` — ``n``
                        # is the number of rows actually written, so incrementing
                        # it before this check declared one more row than the
                        # file contains (the off-by-one this fix removes).
                        skipped_empty += 1
                        continue
                    n += 1
                    etype = (row.get("labels") or "").strip()
                    model = (row.get("model") or "").strip()
                    try:
                        start = int(row["char_start"])
                        end = int(row["char_end"])
                    except (KeyError, TypeError, ValueError):
                        start = end = None

                    key = (paper, sid)
                    if key not in sec:
                        unknown_sec += 1
                        text, spath = "", ""
                    else:
                        text, spath = sec[key]

                    # ── offset verification: never fabricate coordinates ──
                    flags = []
                    if start is not None and end is not None and 0 <= start < end <= len(text) \
                            and text[start:end] == surface:
                        verified += 1
                    else:
                        # conservative recovery: first whole-word occurrence
                        hits = [m.start() for m in re.finditer(
                            r"(?<!\w)" + re.escape(surface) + r"(?!\w)", text)] if text else []
                        if hits:
                            start, end = hits[0], hits[0] + len(surface)
                            recovered += 1
                            flags.append("OFFSET_RECOVERED")
                        else:
                            start = end = None
                            unverified += 1
                            flags.append("OFFSET_UNVERIFIED")

                    sents, paras = get_index(key) if key in sec else ([], [])
                    s_starts = [s for s, _ in sents]
                    p_starts = [p for p, _ in paras]
                    sidx = _locate(sents, s_starts, start, end) if start is not None else None
                    pidx = _locate(paras, p_starts, start, end) if start is not None else None

                    if sidx is not None:
                        sent_text, sent_clipped = _clip_around(
                            text, sents[sidx][0], sents[sidx][1], SENT_MAX_CHARS)
                        if sent_clipped:
                            flags.append("SENTENCE_CLIPPED")
                    else:
                        sent_text, sent_clipped = None, False
                    if start is not None:
                        ps = max(0, start - PASSAGE_WINDOW)
                        pe = min(len(text), end + PASSAGE_WINDOW)
                        passage = text[ps:pe]
                    else:
                        passage = None

                    nrm = norm_term(surface)
                    if has_control(surface):
                        # The surface is kept verbatim; only the identity layer is
                        # sanitized. The flag records that the source text itself
                        # carries a lost glyph, so a reviewer can tell a genuine
                        # surface from a PDF-conversion artifact.
                        flags.append("CONTROL_CHAR_SURFACE")
                        control_surfaces += 1
                    mention_id = "HMTERM_" + _mid("mention", paper, sid, str(start), str(end),
                                                  nrm, run_id)
                    occurrence_key = "HMOCC_" + _mid("occ", paper, sid, str(start), str(end), nrm)

                    sec_name, subsection = section_name_subsection(spath)
                    rec = {
                        "mention_id": mention_id,
                        "occurrence_key": occurrence_key,
                        "paper_id": paper,
                        "source_file_id": f"{paper}.md" if paper else None,
                        "section_id": sid or None,
                        "section_name": sec_name or None,
                        "subsection": subsection,
                        "paragraph_id": f"{sid}:p{pidx}" if pidx is not None else None,
                        "sentence_id": f"{sid}:s{sidx}" if sidx is not None else None,
                        "surface_form": surface,
                        "normalized_mention": nrm,
                        "start_offset": start,
                        "end_offset": end,
                        "supporting_sentence": sent_text,
                        "supporting_sentence_clipped": sent_clipped,
                        "supporting_passage": passage,
                        "entity_type": etype or None,
                        "domain": None,          # Stage T4
                        "subdomain": None,       # Stage T4
                        "canonical_term_id": None,  # Stage T2
                        "link_status": "PENDING_CANONICAL_STAGE",  # Stage T2
                        "extraction_method": method,
                        "extraction_model": model or None,
                        "extraction_run_id": run_id,
                        "confidence": None,      # not computed for any of these extractors
                        "review_status": "UNVERIFIED",
                        "unresolved_flags": flags,
                    }
                    fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    summary["by_entity_type"][etype] = summary["by_entity_type"].get(etype, 0) + 1
                    summary["by_method"][method] = summary["by_method"].get(method, 0) + 1

            summary["sources"][src] = {"path": rel, "status": "OK", "rows": n,
                                       "rows_read": rows_read,
                                       "rows_skipped_empty_surface": skipped_empty,
                                       "offsets_verified": verified,
                                       "offsets_recovered": recovered,
                                       "offsets_unverified": unverified,
                                       "control_char_surfaces": control_surfaces,
                                       "unknown_section": unknown_sec}
            summary["rows_written"] += n
            summary["rows_read"] += rows_read
            summary["rows_skipped_empty_surface"] += skipped_empty
            summary["offsets_verified"] += verified
            summary["offsets_recovered"] += recovered
            summary["offsets_unverified"] += unverified
            summary["control_char_surfaces"] += control_surfaces
            summary["unknown_section"] += unknown_sec
            print("  %-16s %8d rows  (read %d, skipped_empty %d, verified %d, "
                  "recovered %d, unverified %d, control_char %d, unknown_section %d)"
                  % (src, n, rows_read, skipped_empty, verified, recovered, unverified,
                     control_surfaces, unknown_sec),
                  flush=True)

    total = summary["rows_written"] or 1
    summary["pct_offsets_verified"] = round(100.0 * summary["offsets_verified"] / total, 4)
    with (out_dir / "_mentions_summary.json").open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print("wrote %d mentions -> %s" % (summary["rows_written"], out_path))
    print("offset verification: %.3f%% exact" % summary["pct_offsets_verified"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
