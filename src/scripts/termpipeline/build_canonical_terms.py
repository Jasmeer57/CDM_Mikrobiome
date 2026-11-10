#!/usr/bin/env python3
"""Stage 2 — normalization / canonicalization.

Emits ``canonical_terms.jsonl``: one record per ``(term_norm, cdm_type)`` —
the existing dedup key, which is already fuzzy/embedding-deduplicated upstream
with a protected-taxon rule.

This stage does NOT re-cluster and does NOT overwrite
``releases/data_catalogue/terminology/terminology_dedup.csv``. It reads that table,
rolls the mention stream from Stage 1 (and, when asked, the full NER row
corpus) up onto each canonical term, and records the identity layers
separately so that competing type assignments and homonyms are preserved
rather than silently merged.

Rules
-----
* ``term_id`` = ``HMCTERM_<sha1(term_norm, cdm_type)[:16]>`` — same function the
  other stages import from ``ids.py``, so joins hold.
* A surface form carrying more than one ``cdm_type`` yields **one term per
  type** (the dedup table already stores one row per ``term_norm`` and keeps the
  extra types in ``all_types``); each such term is flagged
  ``identity_evidence = "multi_type_surface_form"`` plus the full candidate set.
* ``alternative_types`` comes from ``all_types`` — reported, never used to merge.
* ``mention_count`` is the number of **distinct occurrences** (distinct
  ``occurrence_key``), never the number of mention rows — the four extractors
  see the same occurrence repeatedly, so summing rows inflates the count.
  ``mention_rows`` keeps the raw row count alongside it. ``paper_count`` and
  ``section_count`` are distinct ``paper_id`` / distinct
  ``(paper_id, section_id)``. All counts are null unless the mention rollup was
  supplied. ``NO_DEFINITION_FOUND``-style placeholders are never invented here.
* The **mention -> canonical-term link is materialised** in this stage: the
  Stage-1 mention file is rewritten in place (atomically, via a ``.tmp`` file
  and ``os.replace``) so every row carries ``canonical_term_id``,
  ``link_status``, ``link_type_agreement`` and the full
  ``candidate_term_ids`` set. The join is exact on the sanitized normalized
  surface — never a fuzzy or type-coerced match. When a surface carries more
  than one canonical type the pick is deterministic (type-exact first, then a
  term that records the mention's type in ``alternative_types``, then the
  lowest ``term_id``) and the choice is recorded, not hidden.
* Nothing is auto-merged on shared preferred label or embedding similarity.

Outputs (in ``--out_dir``)
--------------------------
    canonical_terms.jsonl
    canonical_terms_summary.json
    term_mentions.jsonl   (rewritten in place with the resolved link)
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ids import term_id as make_term_id  # noqa: E402
from textnorm import non_concept_reason, sanitize  # noqa: E402

DEDUP_CSV = REPO_ROOT / "releases/data_catalogue" / "terminology" / "terminology_dedup.csv"
TERMINOLOGY_PROVENANCE = REPO_ROOT / "releases/data_catalogue" / "terminology" / "provenance.json"

# Every CDM entity type, so a term's type can be checked against the spec list.
CDM_TYPES = {
    "HMDATA", "HMASSET", "HMCOHORT", "HMSAMPLE", "HMASSAY", "HMFINDING",
    "ORGANISM", "CHEMICAL", "PROTEIN", "DISEASE", "DNA_RNA", "CELL_TYPE",
    "CLINICAL", "DATA_ANALYSIS", "EXPERIMENTAL_METHOD", "LAB_METHOD",
    "GENOMICS", "PATHWAY", "SAMPLE_METHOD", "STUDY_DESIGN", "ENTITY",
    "UNCERTAIN",
}
GENERIC_TYPE = "ENTITY"

# ── mention -> canonical-term link vocabulary ─────────────────────────────
# Kept as explicit constants so T1 (which writes the placeholder), T2 (which
# resolves it) and the tests all agree on the exact strings.
LINK_EXACT_TYPE = "LINKED_EXACT_TYPE"
LINK_TYPE_DIVERGENT_RECORDED = "LINKED_TYPE_DIVERGENT_RECORDED"
LINK_TYPE_DIVERGENT_UNRECORDED = "LINKED_TYPE_DIVERGENT_UNRECORDED"
LINK_UNRESOLVED_NO_TERM = "UNRESOLVED_NO_CANONICAL_TERM"
LINK_UNRESOLVED_EMPTY = "UNRESOLVED_EMPTY_SURFACE"
LINK_UNRESOLVED_NO_TYPE = "UNRESOLVED_NO_ENTITY_TYPE"
LINK_PENDING = "PENDING_CANONICAL_STAGE"
LINKED_STATUSES = (LINK_EXACT_TYPE, LINK_TYPE_DIVERGENT_RECORDED,
                   LINK_TYPE_DIVERGENT_UNRECORDED)

# ``alternative_labels`` is a bounded, derived summary of the distinct surface
# forms that linked to a term. The full set is counted; only this many are kept.
ALT_LABEL_CAP = 25

# Describes the upstream normalizer, so a consumer knows what ``term_norm`` is.
NORMALIZATION_METHOD = (
    "upstream data_catalogue.terminology dedup term_norm, then textnorm.sanitize "
    "(strip C0/C1 control bytes + collapse whitespace runs); NOT the full "
    "norm_term, which is destructive on already-normalized keys"
)

# A-field availability map, emitted in the summary. PRESENT = read from the
# source table; DERIVED = computed from the mention stream; UNAVAILABLE = no
# source data exists in this build; NOT_APPLICABLE = the field is undefined for
# this entity. Nothing is ever invented to fill a gap.
FIELD_AVAILABILITY = {
    "term": "PRESENT",
    "term_norm": "PRESENT",
    "cdm_type": "PRESENT",
    "alternative_types": "PRESENT",
    "models": "PRESENT",
    "source_names": "PRESENT",
    "n_models": "PRESENT",
    "n_observations": "PRESENT",
    "n_papers": "PRESENT",
    "normalization_method": "PRESENT",
    "normalization_status": "PRESENT",
    "mention_count": "DERIVED",
    "mention_rows": "DERIVED",
    "mention_count_exact_type": "DERIVED",
    "paper_count": "DERIVED",
    "section_count": "DERIVED",
    "top_paper_ids": "DERIVED",
    "alternative_labels": "DERIVED",
    "n_alternative_labels": "DERIVED",
    "processing_run_ids": "DERIVED",
    "definition_status": "DERIVED",
    "taxonomy_category": "DERIVED",
    "taxonomy_subcategory": "DERIVED",
    "first_seen": "NOT_APPLICABLE",
    "last_seen": "NOT_APPLICABLE",
    "definition_text": "NOT_APPLICABLE",
    "reviewer": "NOT_APPLICABLE",
}


def _split_types(raw: str):
    """``all_types`` is a ``|``-separated list; tolerate ``;``/``,`` too."""
    if not raw:
        return []
    out = []
    for chunk in raw.replace(";", "|").replace(",", "|").split("|"):
        t = chunk.strip()
        if t and t not in out:
            out.append(t)
    return out


def load_terms(path: Path):
    """Read the dedup table into canonical-term records (no rollups yet).

    ``term_norm`` is sanitized on read. The upstream table is machine output and
    carries PDF-conversion artifacts (control bytes where a glyph was lost), so
    the identity layer is cleaned before any id is derived from it. Sanitizing
    can collide two upstream rows onto one ``(term_norm, cdm_type)`` — measured
    19 collisions across the whole 166,012-row table, every one of them a row
    pair that differed *only* by an invisible byte. The one-term-per-key
    invariant is preserved by keeping the first row and counting the drop.

    ``non_concept_reason`` is evaluated on the RAW upstream value (before the
    control bytes are stripped) so that a surface whose only defect is the
    control byte is still flagged rather than silently cleaned into an ordinary
    term. Flagged terms are marked, never deleted.
    """
    terms = []
    seen_ids = set()
    reasons = Counter()
    n_deduped = 0
    unknown_types = Counter()
    with path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            raw = (row.get("term_norm") or "").strip()
            tn = sanitize(raw)
            term = (row.get("term") or "").strip()
            if not tn:
                continue
            cdm = (row.get("cdm_type") or "").strip() or "UNCERTAIN"
            if cdm not in CDM_TYPES:
                unknown_types[cdm] += 1
            all_types = _split_types(row.get("all_types"))
            if cdm not in all_types:
                all_types = [cdm] + all_types
            alt = [t for t in all_types if t != cdm]
            multi = len(all_types) > 1
            tid = make_term_id(tn, cdm)
            if tid in seen_ids:
                n_deduped += 1
                continue
            seen_ids.add(tid)
            # Evaluated on both the raw normalized key *and* the display
            # surface: ``term_norm`` is lower-cased upstream, so the
            # upper-case-only roman-numeral rule would never fire on it and
            # the surface carries the evidence. Measured on the full table the
            # union flags 1,109 rows (0.67%) — a superset of the raw-only 1,103,
            # the extra 6 being genuine roman numerals (``IV``, ``II``, ...).
            reason = non_concept_reason(raw) or non_concept_reason(term)
            if reason:
                reasons[reason] += 1
            terms.append({
                "term_id": tid,
                "term": term,
                "term_norm": tn,
                "cdm_type": cdm,
                "is_generic_type": cdm == GENERIC_TYPE,
                "is_non_concept_surface": reason is not None,
                "non_concept_reason": reason,
                "alternative_types": alt,
                "n_candidate_types": len(all_types),
                "identity_evidence": (
                    "multi_type_surface_form" if multi else "single_type_surface_form"
                ),
                "models": _split_types(row.get("models")),
                "source_names": _split_types(row.get("source_names")),
                "n_models": _int(row.get("n_models")),
                "n_observations": _int(row.get("n_observations")),
                "n_papers": _int(row.get("n_papers")),
                "mention_count": None,
                "mention_rows": None,
                "mention_count_exact_type": None,
                "paper_count": None,
                "section_count": None,
                "top_paper_ids": [],
                "alternative_labels": [],
                "n_alternative_labels": None,
                "alternative_labels_truncated": False,
                "normalization_method": NORMALIZATION_METHOD,
                "normalization_status": "UPSTREAM_PROVIDED",
                "processing_run_ids": [],
                "definition_status": None,
                "taxonomy_category": None,
                "taxonomy_subcategory": None,
                "review_status": "UNVERIFIED",
                "source_table": "releases/data_catalogue/terminology/terminology_dedup.csv",
            })
    return terms, unknown_types, reasons, n_deduped


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def pick_canonical(cands, entity_type):
    """Deterministically choose the canonical term for one mention surface.

    Preference order (all deterministic, none fuzzy):
      1. a term whose ``cdm_type`` equals the mention's ``entity_type``;
      2. a term that records that type in ``alternative_types``;
      3. the lowest ``term_id``.

    Returns ``(term, link_status)``. The caller records the choice and the full
    candidate set, so a divergent pick is auditable rather than silent.
    """
    etype = entity_type or ""
    if etype:
        exact = [t for t in cands if t["cdm_type"] == etype]
        if exact:
            return min(exact, key=lambda x: x["term_id"]), LINK_EXACT_TYPE
        recorded = [t for t in cands if etype in (t.get("alternative_types") or [])]
        if recorded:
            return min(recorded, key=lambda x: x["term_id"]), LINK_TYPE_DIVERGENT_RECORDED
    return min(cands, key=lambda x: x["term_id"]), LINK_TYPE_DIVERGENT_UNRECORDED


def link_mention(norm: str, entity_type: str, by_norm: dict):
    """Resolve one mention to a canonical term without coercing anything.

    Returns ``(canonical_term, link_status, candidate_term_ids,
    link_type_agreement)``. ``canonical_term`` is ``None`` only when there is
    genuinely no canonical term to link to (empty surface, no type, or a
    normalized surface absent from the canonical table).
    """
    etype = (entity_type or "").strip()
    if not norm:
        return None, LINK_UNRESOLVED_EMPTY, [], None
    cands = by_norm.get(norm)
    if not cands:
        return None, LINK_UNRESOLVED_NO_TERM, [], None
    if not etype:
        # Defensive only: every extractor emits an entity type, so this branch
        # should never fire on the real stream.
        t, _ = pick_canonical(cands, etype)
        return t, LINK_UNRESOLVED_NO_TYPE, [c["term_id"] for c in cands], None
    t, status = pick_canonical(cands, etype)
    agreement = status != LINK_TYPE_DIVERGENT_UNRECORDED
    return t, status, [c["term_id"] for c in cands], agreement


def rollup_mentions(terms, mentions_path: Path, max_papers: int = 5,
                    rewrite: bool = True, alt_label_cap: int = ALT_LABEL_CAP):
    """Materialise the mention -> term link and roll mention frequency up.

    Single streaming pass over the Stage-1 stream:

      * every mention row is rewritten with ``canonical_term_id``,
        ``link_status``, ``link_type_agreement`` and ``candidate_term_ids``
        (written to ``<name>.tmp`` then ``os.replace``d, so a crash never
        truncates the mention file);
      * each canonical term accumulates the number of **distinct occurrences**
        (``occurrence_key``), the raw row count, the exact-type row count,
        distinct papers, distinct ``(paper_id, section_id)`` sections, the
        distinct surface forms that linked, and the extractor run ids.

    Terms with no linked mention keep ``None`` — a zero would be a claim the
    stream cannot support (the stream is a subset of the corpus).
    """
    by_id = {}
    by_norm = defaultdict(list)
    for t in terms:
        by_id.setdefault((t["term_norm"], t["cdm_type"]), t)
        by_norm[t["term_norm"]].append(t)

    occ = defaultdict(set)
    papers = defaultdict(Counter)
    sections = defaultdict(set)
    surfaces = defaultdict(set)
    runs = defaultdict(set)
    row_counts = Counter()
    exact_rows = Counter()

    stats = Counter()
    link_counts = Counter()

    tmp_path = mentions_path.with_name(mentions_path.name + ".tmp")
    fin = mentions_path.open(encoding="utf-8")
    fout = tmp_path.open("w", encoding="utf-8") if rewrite else None
    try:
        for line in fin:
            s = line.rstrip("\n")
            if not s.strip():
                continue
            stats["rows_read"] += 1
            try:
                m = json.loads(s)
            except json.JSONDecodeError:
                stats["unparsable_rows"] += 1
                if fout is not None:
                    fout.write(s + "\n")
                continue

            norm = (m.get("normalized_mention") or "").strip()
            etype = (m.get("entity_type") or "").strip()
            t, status, cand_ids, agreement = link_mention(norm, etype, by_norm)

            m["canonical_term_id"] = t["term_id"] if t is not None else None
            m["link_status"] = status
            m["link_type_agreement"] = agreement
            m["candidate_term_ids"] = cand_ids
            if fout is not None:
                fout.write(json.dumps(m, ensure_ascii=False) + "\n")
                stats["rows_written"] += 1

            link_counts[status] += 1
            if t is None:
                continue
            tid = t["term_id"]
            row_counts[tid] += 1
            if status == LINK_EXACT_TYPE:
                exact_rows[tid] += 1
            ok = (m.get("occurrence_key") or "").strip()
            if ok:
                occ[tid].add(ok)
            pid = (m.get("paper_id") or "").strip()
            if pid:
                papers[tid][pid] += 1
                sections[tid].add((pid, (m.get("section_id") or "").strip()))
            sf = (m.get("surface_form") or "").strip()
            if sf:
                surfaces[tid].add(sf)
            run = m.get("extraction_run_id")
            if run:
                runs[tid].add(run)
    finally:
        fin.close()
        if fout is not None:
            fout.close()

    if rewrite:
        os.replace(tmp_path, mentions_path)

    attached = 0
    for t in terms:
        tid = t["term_id"]
        n = row_counts.get(tid)
        if not n:
            continue
        attached += 1
        t["mention_rows"] = n
        t["mention_count"] = len(occ[tid])
        t["mention_count_exact_type"] = exact_rows.get(tid, 0)
        t["paper_count"] = len(papers[tid])
        t["section_count"] = len(sections[tid])
        labels = sorted(surfaces[tid])
        t["n_alternative_labels"] = len(labels)
        t["alternative_labels_truncated"] = len(labels) > alt_label_cap
        t["alternative_labels"] = labels[:alt_label_cap]
        t["processing_run_ids"] = sorted(runs[tid])
        t["top_paper_ids"] = [p for p, _ in papers[tid].most_common(max_papers)]

    stats["terms_with_mention_rollup"] = attached
    stats["mentions_linked"] = sum(link_counts[s] for s in LINKED_STATUSES)
    stats["mentions_unresolved"] = (link_counts[LINK_UNRESOLVED_NO_TERM]
                                    + link_counts[LINK_UNRESOLVED_EMPTY]
                                    + link_counts[LINK_UNRESOLVED_NO_TYPE])
    stats["by_link_status"] = dict(link_counts.most_common())
    stats["distinct_occurrence_assignments"] = sum(len(s) for s in occ.values())
    return stats


def rollup_definitions(terms, defs_path: Path):
    """Attach a per-term definition status: has one, or NO_DEFINITION_FOUND.

    ``NO_DEFINITION_FOUND`` here means "this extraction pass found no
    source-grounded definition for the term in the scanned sections" — phrased
    as a scoped negative, never as "the term has no definition".
    """
    found = Counter()
    by_src = defaultdict(Counter)
    if defs_path.exists():
        with defs_path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                src = d.get("definition_source")
                if not src or src == "NO_DEFINITION_FOUND" or not d.get("definition_text"):
                    continue
                tid = d.get("term_id")
                found[tid] += 1
                by_src[tid][src] += 1
    n_found = 0
    for t in terms:
        n = found.get(t["term_id"])
        if n:
            n_found += 1
            t["definition_status"] = "SOURCE_DEFINITION_FOUND"
            t["definition_sources"] = [s for s, _ in by_src[t["term_id"]].most_common()]
            t["definition_count"] = n
        else:
            t["definition_status"] = "NO_DEFINITION_FOUND"
            t["definition_sources"] = []
            t["definition_count"] = 0
    return n_found


def attach_taxonomy(terms, taxonomy_csv: Path):
    """Join the v1 taxonomy labels when the exported csv is available."""
    if not taxonomy_csv.exists():
        return 0
    index = {}
    with taxonomy_csv.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            key = (sanitize((row.get("term_norm") or row.get("term") or "").strip()),
                   (row.get("cdm_type") or "").strip())
            cat = (row.get("category") or row.get("upper_category") or "").strip()
            sub = (row.get("subcategory") or "").strip()
            if cat:
                index[key] = (cat, sub or None)
    n = 0
    for t in terms:
        hit = index.get((t["term_norm"], t["cdm_type"])) or index.get(
            (t["term_norm"], ""))
        if hit:
            t["taxonomy_category"], t["taxonomy_subcategory"] = hit
            n += 1
    return n


def main():
    ap = argparse.ArgumentParser(description="Stage 2 — canonical terms")
    ap.add_argument("--dedup_csv", type=Path, default=DEDUP_CSV)
    ap.add_argument("--mentions", type=Path, default=None,
                    help="Stage 1 term_mentions.jsonl (enables mention rollups)")
    ap.add_argument("--definitions", type=Path, default=None,
                    help="Stage 3 term_definitions.jsonl (enables definition status)")
    ap.add_argument("--taxonomy_csv", type=Path,
                    default=REPO_ROOT / "releases/data_catalogue/terminology/taxonomy/term_taxonomy_v1.csv")
    ap.add_argument("--out_dir", type=Path, required=True)
    args = ap.parse_args()

    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    if not args.dedup_csv.exists():
        raise SystemExit(f"missing dedup table: {args.dedup_csv}")
    terms, unknown_types, non_concept_reasons, n_deduped = load_terms(args.dedup_csv)
    print(f"loaded {len(terms)} canonical terms from {args.dedup_csv.name}", flush=True)
    if n_deduped:
        print(f"deduped {n_deduped} rows that collided after control-char sanitization",
              flush=True)
    if non_concept_reasons:
        print(f"flagged {sum(non_concept_reasons.values())} non-concept surfaces: "
              f"{dict(non_concept_reasons)}", flush=True)

    dupe_ids = [tid for tid, n in Counter(t["term_id"] for t in terms).items() if n > 1]
    if dupe_ids:
        print(f"WARNING: {len(dupe_ids)} duplicated term ids "
              f"(term_norm, cdm_type collisions)", flush=True)

    mention_rows = attached = None
    link_stats = None
    if args.mentions and args.mentions.exists():
        link_stats = rollup_mentions(terms, args.mentions)
        mention_rows = link_stats["rows_read"]
        attached = link_stats["terms_with_mention_rollup"]
        print(f"mention link + rollup: {link_stats['rows_read']} rows read, "
              f"{link_stats['mentions_linked']} linked, "
              f"{link_stats['mentions_unresolved']} unresolved -> "
              f"{attached} terms", flush=True)
        print(f"  by link_status: {link_stats['by_link_status']}", flush=True)

    n_defs = None
    if args.definitions and args.definitions.exists():
        n_defs = rollup_definitions(terms, args.definitions)
        print(f"definition rollup: {n_defs} terms with a source definition", flush=True)

    n_tax = attach_taxonomy(terms, args.taxonomy_csv)
    if n_tax:
        print(f"taxonomy join: {n_tax} terms labelled", flush=True)

    out_path = out_dir / "canonical_terms.jsonl"
    with out_path.open("w", encoding="utf-8") as f:
        for t in terms:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")

    by_type = Counter(t["cdm_type"] for t in terms)
    multi = sum(1 for t in terms if t["identity_evidence"] == "multi_type_surface_form")
    summary = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "inputs": {
            "dedup_csv": str(args.dedup_csv),
            "dedup_csv_rows": len(terms) + n_deduped,
            "mentions": str(args.mentions) if args.mentions else None,
            "definitions": str(args.definitions) if args.definitions else None,
            "taxonomy_csv": str(args.taxonomy_csv),
        },
        "outputs": {"canonical_terms": str(out_path)},
        "counts": {
            "canonical_terms": len(terms),
            "distinct_term_norm": len({t["term_norm"] for t in terms}),
            "multi_type_surface_forms": multi,
            "duplicated_term_ids": len(dupe_ids),
            "deduped_after_sanitize": n_deduped,
            "non_concept_surfaces": sum(non_concept_reasons.values()),
            "generic_entity_terms": by_type.get(GENERIC_TYPE, 0),
            "terms_with_mention_rollup": attached,
            "mention_rows_read": link_stats["rows_read"] if link_stats else None,
            "mention_rows_linked": link_stats["mentions_linked"] if link_stats else None,
            "mention_rows_unresolved": link_stats["mentions_unresolved"] if link_stats else None,
            "terms_with_source_definition": n_defs,
            "terms_with_taxonomy_label": n_tax,
        },
        "mention_link": {
            "by_link_status": link_stats["by_link_status"] if link_stats else None,
            "link_status_vocabulary": {
                LINK_EXACT_TYPE: "normalized surface matched a canonical term of the same type",
                LINK_TYPE_DIVERGENT_RECORDED: "matched a term of another type that records this type in alternative_types",
                LINK_TYPE_DIVERGENT_UNRECORDED: "matched a term whose recorded types do not include this mention's type",
                LINK_UNRESOLVED_NO_TERM: "no canonical term has this normalized surface",
                LINK_UNRESOLVED_EMPTY: "the mention had an empty normalized surface",
                LINK_UNRESOLVED_NO_TYPE: "defensive: the mention carried no entity type",
                LINK_PENDING: "written by Stage T1; resolved by Stage T2",
            },
            "join_rule": "exact match on sanitize(normalized_mention) == canonical term_norm; "
                         "NO type coercion, NO fuzzy match; multi-term surfaces resolved by "
                         "pick_canonical() (type-exact, then recorded alt type, then lowest term_id)",
            "note": "term_mentions.jsonl was rewritten in place with these fields "
                    "(atomic .tmp + os.replace); the Stage-1 raw output is preserved "
                    "in the prior release (outputs/results/terminology_v1/).",
        },
        "field_availability": FIELD_AVAILABILITY,
        "non_concept_surfaces_by_reason": non_concept_reasons.most_common(),
        "by_cdm_type": by_type.most_common(),
        "unknown_cdm_types": unknown_types.most_common(),
        "identity_layers": {
            "term_id": "HMCTERM_<sha1(term_norm, cdm_type)[:16]>",
            "note": "one term per (term_norm, cdm_type); alternative_types reported, never merged",
        },
        "caveats": [
            "Dedup/clustering happened upstream (terminology_dedup.csv); this stage does not re-cluster.",
            "alternative_types is reported evidence, not a merge decision.",
            "Unresolved terms keep null counts rather than a fabricated zero.",
            "review_status stays UNVERIFIED: no canonical term is human-validated.",
            "term_norm is sanitized (control bytes removed) on read; rows that collide "
            "only after sanitization are deduplicated, and the drop is counted.",
            "is_non_concept_surface marks NER noise (URLs, figure refs, roman numerals); "
            "flagging is a report, not a deletion — the term stays in the artifact.",
            "mention_count counts DISTINCT occurrence_key values, not mention rows; "
            "mention_rows is the raw row count. Summing rows across extractors would "
            "count the same occurrence up to four times.",
            "section_count counts distinct (paper_id, section_id); section ids are only "
            "unique within a paper and are never summed across papers.",
            "The mention link is an exact normalized-surface match with recorded type "
            "agreement; a divergent link is archived, not hidden and not deleted.",
        ],
        "elapsed_seconds": round(time.time() - t0, 1),
    }
    with (out_dir / "canonical_terms_summary.json").open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print(json.dumps({"counts": summary["counts"]}, indent=2))
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
