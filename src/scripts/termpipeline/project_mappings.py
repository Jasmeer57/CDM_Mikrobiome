#!/usr/bin/env python3
"""Stage 5 — controlled-vocabulary linking (projection only).

Emits ``term_ontology_mappings.jsonl``: one row per **candidate** concept for a
canonical term, with the staged-match provenance, a ``mapping_relation`` and a
``mapping_disposition``.

This stage makes **no network calls**. It projects what already exists:

  * ``outputs/results/cv_linking/cv_mapped_entities.jsonl``  (OLS / UMLS / BioPortal / NCBITaxon)
  * ``outputs/results/omop_linking/omop_links.csv``          (local OMOP vocabulary, exact match only)
  * ``outputs/results/mesh_ner/mesh_term_stats.csv``         (MeSH gazetteer dictionary hits)

Relation + disposition are assigned by the documented rules in ``classify()``.
**Nothing is auto-accepted**: with no human-reviewed gold sample the
calibration required by the spec does not exist yet, so every row is
``REVIEW_REQUIRED`` or ``UNRESOLVED`` while ``auto_accept_eligible`` records
what *would* qualify once thresholds are calibrated.

A "no mapping" and a "lookup that failed" are different facts and are recorded
differently (``UNRESOLVED``/``NO_MATCH_FOUND`` vs ``LOOKUP_FAILED``).

Terms flagged as *non-concept surfaces* by the canonicalisation stage (roman
numerals, figure references, URLs, citation fragments, ...) are emitted like any
other row but are never ``auto_accept_eligible``: the reason is carried in
``auto_accept_ineligible_reason`` so the exclusion is auditable rather than
silent.

Outputs (in ``--out_dir``)
--------------------------
    term_ontology_mappings.jsonl
    mapping_projection_summary.json
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ids import mapping_id as make_mapping_id, term_id as make_term_id  # noqa: E402
from textnorm import non_concept_reason, sanitize  # noqa: E402

CV_JSONL = REPO_ROOT / "outputs/results/cv_linking/cv_mapped_entities.jsonl"
CV_LINKS = REPO_ROOT / "outputs/results/cv_linking/cv_links.csv"
OMOP_CSV = REPO_ROOT / "outputs/results/omop_linking/omop_links.csv"
MESH_STATS = REPO_ROOT / "outputs/results/mesh_ner/mesh_term_stats.csv"

# Sources that return a *validated identifier* rather than a text search hit.
# These are the only tiers eligible for EXACT_MATCH without a label comparison
# against the vocabulary's own preferred label.
VALIDATED_ID_SOURCES = {"ncbitaxon_exact", "omop_exact", "mesh_gazetteer"}

# Text-search services: an exact match needs the returned label to equal the term.
TEXT_SEARCH_SOURCES = {"ols", "umls", "bioportal"}


def norm(s: str) -> str:
    """Join key: control chars stripped, case-folded, whitespace collapsed.

    The control-byte strip matters for the *join*: 348 canonical terms contain
    raw control bytes (see ``textnorm.sanitize``) and the upstream linking runs
    keyed on the unsanitized string, so without it those terms would never
    resolve to a canonical row. It is applied to both sides (term and returned
    label) so the comparison stays symmetric.
    """
    return sanitize(s).lower()


def classify(term_norm, cdm_type, source_tier, label, concept_id,
             has_error=False, tied_competing=False):
    """Assign (mapping_relation, mapping_disposition, auto_accept_eligible).

    Rules, in order:

    1. a lookup that errored is LOOKUP_FAILED — *not* a no-match;
    2. a validated-identifier source is EXACT_MATCH (identifier already
       validated against source in the producing stage);
    3. a text-search source whose returned label normalizes to the term is
       EXACT_MATCH; a differing label is RELATED_TO (candidate generation);
    4. two-or-more tied candidates for different concepts is AMBIGUOUS;
    5. nothing at all is NO_MATCH_FOUND / UNRESOLVED.

    Nothing is AUTO_ACCEPTED: the calibrated acceptance threshold does not exist.
    """
    if has_error:
        return "UNVERIFIED", "LOOKUP_FAILED", False
    if source_tier in VALIDATED_ID_SOURCES:
        return "EXACT_MATCH", "REVIEW_REQUIRED", True
    if source_tier in TEXT_SEARCH_SOURCES:
        if label and norm(label) == norm(term_norm):
            return "EXACT_MATCH", "REVIEW_REQUIRED", True
        return "RELATED_TO", "REVIEW_REQUIRED", False
    if tied_competing:
        return "AMBIGUOUS", "REVIEW_REQUIRED", False
    return "RELATED_TO", "REVIEW_REQUIRED", False


def apply_calibration(rel, disp, elig, calibrated_accept):
    """Promote a candidate to ``AUTO_ACCEPTED`` only on a calibrated stratum.

    ``calibrated_accept`` is true only when the caller matched this candidate's
    ``(source_service, mapping_relation)`` against a threshold file whose status
    enables auto-accept *and* whose Wilson lower bound cleared the threshold at
    the required sample size. Anything else — no file, a missing stratum, an
    ``auto_accept_eligible`` that is false — leaves the disposition untouched,
    so the default projection is unchanged and nothing is auto-accepted without
    a human-reviewed sample behind it.
    """
    if calibrated_accept and elig:
        return rel, "AUTO_ACCEPTED", elig
    return rel, disp, elig


def load_calibration(path):
    """Read ``calibration_thresholds.json``; fail closed on anything unproven.

    Returns ``(accept_pairs, meta)``. ``accept_pairs`` is a set of
    ``"<source_service>|<mapping_relation>"`` keys that may be auto-accepted; it
    is empty unless the file reports ``auto_accept_enabled`` true.
    """
    if path is None:
        return set(), {"status": "NOT_CALIBRATED",
                       "reason": "no calibration file supplied"}
    path = Path(path)
    if not path.exists():
        return set(), {"status": "NOT_CALIBRATED",
                       "reason": "calibration file not found: %s" % path}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as ex:
        return set(), {"status": "NOT_CALIBRATED",
                       "reason": "calibration file unreadable: %s" % ex}
    if not data.get("auto_accept_enabled"):
        return set(), {"status": data.get("status", "NOT_CALIBRATED"),
                       "reason": "auto_accept_enabled is false: %s"
                                 % data.get("reason", ""),
                       "file": str(path)}
    pairs = set()
    for s in data.get("accept_strata") or []:
        svc = s.get("source_service") or "none"
        rel = s.get("mapping_relation") or "none"
        pairs.add("%s|%s" % (svc, rel))
    return pairs, {"status": data.get("status"), "reason": data.get("reason"),
                   "file": str(path), "n_accept_strata": len(pairs)}


def load_cv(path: Path):
    """(term_norm, cdm_type) -> record from the CV-linking stage."""
    out = {}
    if not path.exists():
        return out
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            key = (norm(r.get("term_norm")), (r.get("cdm_type") or "").strip())
            out[key] = r
    return out


def load_omop(path: Path):
    """(term_norm, cdm_type) -> list of OMOP candidate dicts."""
    out = defaultdict(list)
    if not path.exists():
        return out
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            key = (norm(row.get("term_norm")), (row.get("cdm_type") or "").strip())
            out[key].append(row)
    return out


def load_mesh(path: Path):
    """(term_norm, cdm_type) -> list of MeSH candidates.

    A MeSH descriptor/supplemental that matches a gazetteer heading *is* an exact
    dictionary match, so these rows carry no candidate-generation uncertainty.
    """
    out = defaultdict(list)
    if not path.exists():
        return out
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            key = (norm(row.get("term")), (row.get("cdm_type") or "").strip())
            out[key].append(row)
    return out


def cv_candidates(rec):
    """Yield (source_tier, concept_id, label, confidence, is_canonical) for a CV record."""
    if not rec:
        return
    canon = rec.get("canonical") or {}
    canon_id = canon.get("concept_id")
    for c in rec.get("all_mappings") or []:
        if not isinstance(c, dict):
            continue
        yield (c.get("source") or "unknown", c.get("concept_id"), c.get("label"),
               c.get("confidence"),
               bool(canon_id and c.get("concept_id") == canon_id
                    and c.get("ontology_name") == canon.get("ontology_name")))


def build_rows(cv, omop, mesh, terms_index, accept_pairs=None):
    accept_pairs = accept_pairs or set()
    rows = []
    all_keys = set(cv) | set(omop) | set(mesh)
    n_lookup_failed = 0
    n_no_match = 0

    # A normalized-surface index, used to re-key rows whose exact
    # (term_norm, cdm_type) key is absent but whose term exists under other
    # types. Derived from ``terms_index`` so the two never drift.
    terms_by_norm = defaultdict(list)
    for (_tn, _ct), _t in terms_index.items():
        if isinstance(_t, dict):
            terms_by_norm[_tn].append(_t)

    for key in sorted(all_keys):
        term_norm, cdm_type = key
        if not term_norm:
            continue
        rec = cv.get(key)
        omop_hits = omop.get(key, [])
        mesh_hits = mesh.get(key, [])

        # ── resolve the mapping subject to a canonical term ────────────────
        # A row's own (term_norm, cdm_type) key may be absent from the canonical
        # table even though the normalized term is present — the MeSH gazetteer
        # types a heading by its MeSH tree while the canonical table types it by
        # CDM entity type, so 3,268 dictionary hits were orphaned by an exact-key
        # join. Those are re-keyed to the canonical term and the divergence is
        # recorded (``type_agreement``); the 1,969 rows whose normalized term is
        # genuinely absent from the canonical table are marked
        # UNRESOLVED_NO_CANONICAL_TERM — kept, never dropped, never force-linked.
        hit = terms_index.get((term_norm, cdm_type))
        key_resolution = "EXACT_KEY"
        type_agreement = "TYPE_EXACT"
        canonical_cdm_type = cdm_type
        if hit is None:
            alts = terms_by_norm.get(term_norm) or []
            if alts:
                hit = min(alts, key=lambda x: x.get("term_id") or "")
                canonical_cdm_type = (hit.get("cdm_type") or "").strip() or None
                key_resolution = "REKEYED_TYPE_DIVERGENT"
                if canonical_cdm_type == cdm_type:
                    type_agreement = "TYPE_EXACT"
                elif cdm_type in (hit.get("alternative_types") or []):
                    type_agreement = "TYPE_DIVERGENT_RECORDED"
                else:
                    type_agreement = "TYPE_DIVERGENT_UNRECORDED"
            else:
                key_resolution = "UNRESOLVED_NO_CANONICAL_TERM"
                type_agreement = None
                canonical_cdm_type = None
        hit = hit or {}
        resolved_tid = hit.get("term_id") or make_term_id(term_norm, cdm_type)
        unresolved = key_resolution == "UNRESOLVED_NO_CANONICAL_TERM"
        subject_key = (("UNRESOLVED:%s|%s" % (term_norm, cdm_type))
                       if unresolved else resolved_tid)

        cands = []
        for src, cid, label, conf, is_canon in cv_candidates(rec):
            cands.append({
                "ontology_source": "cv_linking",
                "source_service": src,
                "source_tier": src,
                "concept_id": cid,
                "concept_label": label,
                "confidence": conf,
                "is_canonical_candidate": is_canon,
            })
        for r in omop_hits:
            cands.append({
                "ontology_source": "omop_local",
                "source_service": "omop",
                "source_tier": "omop_exact",
                "concept_id": r.get("concept_id"),
                "concept_label": r.get("label"),
                "ontology_name": r.get("ontology_name"),
                "omop_domain": r.get("omop_domain"),
                "omop_concept_class": r.get("omop_concept_class"),
                "omop_standard": r.get("omop_standard"),
                "matched_via": r.get("omop_matched_via"),
                "standard_concept_id": r.get("omop_standard_concept_id"),
                "standard_concept_label": r.get("omop_standard_concept_name"),
                "confidence": 1.0,  # exact normalized dictionary match
                "is_canonical_candidate": False,
            })
        for r in mesh_hits:
            cands.append({
                "ontology_source": "mesh_gazetteer",
                "source_service": "mesh",
                "source_tier": "mesh_gazetteer",
                "concept_id": r.get("mesh_ui"),
                "concept_label": r.get("term"),
                "mesh_tree": r.get("mesh_tree"),
                "mesh_kind": r.get("kind"),
                "n_hits": r.get("n_hits"),
                "confidence": 1.0,  # exact dictionary heading match
                "is_canonical_candidate": False,
            })

        has_error = bool(rec and rec.get("error"))

        # rank: canonical first, then confidence desc, then concept id
        cands.sort(key=lambda c: (not c["is_canonical_candidate"],
                                  -(c["confidence"] or 0.0),
                                  str(c.get("concept_id"))))
        for i, c in enumerate(cands, 1):
            c["candidate_rank"] = i

        # AMBIGUOUS means the SAME vocabulary offers competing concepts for this
        # term (tied top confidence, different ids). Two different vocabularies
        # both matching (e.g. MeSH and OMOP/SNOMED) is corroboration, not
        # ambiguity, and is ranked normally.
        tied_groups = set()
        by_vocab = defaultdict(list)
        for c in cands:
            vocab = c.get("ontology_name") or c["source_service"] or "unknown"
            by_vocab[(vocab, c["source_tier"] in VALIDATED_ID_SOURCES)].append(c)
        for group in by_vocab.values():
            top = group[0]["confidence"] or 0.0
            tied = [c for c in group if (c["confidence"] or 0.0) == top]
            ids = {c.get("concept_id") for c in tied}
            if len(ids) > 1:
                for c in tied:
                    if c.get("concept_id") is not None:
                        tied_groups.add(id(c))

        # Non-concept surfaces (roman numerals, figure references, URLs, ...) can
        # never be promoted: they are ineligible for auto-accept regardless of how
        # clean the matched concept is. The reason is recorded on the row so the
        # exclusion is auditable, and the candidate itself is still emitted —
        # nothing is dropped, only marked.
        nc_reason = (hit.get("non_concept_reason")
                     or non_concept_reason(hit.get("term") or term_norm))

        if not cands:
            if unresolved:
                rel, disp, elig = "NO_MATCH_FOUND", "UNRESOLVED_NO_CANONICAL_TERM", False
            elif has_error:
                rel, disp, elig = "UNVERIFIED", "LOOKUP_FAILED", False
            else:
                rel, disp, elig = "NO_MATCH_FOUND", "UNRESOLVED", False
            if has_error:
                n_lookup_failed += 1
            else:
                n_no_match += 1
            rows.append({
                "mapping_id": None,  # assigned uniquely in the post-pass below
                "term_id": resolved_tid, "term": hit.get("term") or term_norm,
                "term_norm": term_norm, "cdm_type": cdm_type,
                "subject_key": subject_key,
                "canonical_cdm_type": canonical_cdm_type,
                "key_resolution": key_resolution,
                "type_agreement": type_agreement,
                "source_tier": None,
                "candidate_rank": None,
                "duplicate_index": 0,
                "is_canonical_candidate": False,
                "ontology_source": None, "source_service": None, "concept_id": None,
                "concept_label": None, "mapping_relation": rel,
                "mapping_disposition": disp, "auto_accept_eligible": False,
                "auto_accept_ineligible_reason": nc_reason,
                "scores": {"confidence": None, "lexical_score": None, "semantic_score": None},
                "staged_match": {"stage": "lookup", "matched_label": False,
                                 "matched_synonym": None},
                "competing_candidates": 0,
                "review_status": "REVIEW_REQUIRED" if has_error else "UNRESOLVED",
                "provenance": {"query": term_norm, "services_queried": ["ols", "umls",
                              "bioportal", "ncbitaxon"] + (["omop"] if omop_hits else []),
                              "error": (rec or {}).get("error") if has_error else None},
            })
            continue

        for c in cands:
            tier = c["source_tier"]
            label_norm = norm(c.get("concept_label"))
            rel, disp, elig = classify(term_norm, cdm_type, tier,
                                       c.get("concept_label"), c.get("concept_id"),
                                       has_error=False,
                                       tied_competing=id(c) in tied_groups)
            if id(c) in tied_groups:
                # an unresolvable within-vocabulary tie is flagged, not hidden
                rel, disp, elig = "AMBIGUOUS", "REVIEW_REQUIRED", False
            if nc_reason:
                # a non-concept term is never eligible, whatever the candidate is
                elig = False
            if unresolved:
                # A candidate exists but there is no canonical term to attach it
                # to. The relation is kept as evidence; the disposition records
                # that the subject itself is unresolved, and nothing is eligible.
                disp, elig = "UNRESOLVED_NO_CANONICAL_TERM", False
            # Opt-in promotion, driven only by a human-calibrated threshold file.
            rel, disp, elig = apply_calibration(
                rel, disp, elig,
                ("%s|%s" % (c.get("source_service") or "none", rel)) in accept_pairs)
            matched_label = bool(label_norm and label_norm == norm(term_norm))
            rows.append({
                "mapping_id": None,  # assigned uniquely in the post-pass below
                "term_id": resolved_tid, "term": hit.get("term") or term_norm,
                "term_norm": term_norm, "cdm_type": cdm_type,
                "subject_key": subject_key,
                "canonical_cdm_type": canonical_cdm_type,
                "key_resolution": key_resolution,
                "type_agreement": type_agreement,
                "source_tier": tier,
                "candidate_rank": c["candidate_rank"],
                "duplicate_index": 0,
                "is_canonical_candidate": c["is_canonical_candidate"],
                "ontology_source": c["ontology_source"],
                "source_service": c["source_service"],
                "ontology_name": c.get("ontology_name"),
                "concept_id": c.get("concept_id"),
                "concept_label": c.get("concept_label"),
                "mesh_tree": c.get("mesh_tree"),
                "mesh_kind": c.get("mesh_kind"),
                "omop_domain": c.get("omop_domain"),
                "omop_concept_class": c.get("omop_concept_class"),
                "omop_standard": c.get("omop_standard"),
                "matched_via": c.get("matched_via"),
                "standard_concept_id": c.get("standard_concept_id"),
                "standard_concept_label": c.get("standard_concept_label"),
                "mapping_relation": rel,
                "mapping_disposition": disp,
                "auto_accept_eligible": elig,
                "auto_accept_ineligible_reason": nc_reason,
                "scores": {
                    "confidence": c.get("confidence"),
                    "lexical_score": None,   # not computed at projection time
                    "semantic_score": None,  # not computed at projection time
                },
                "staged_match": {
                    "stage": _stage_for(tier, matched_label),
                    "matched_label": matched_label,
                    "matched_synonym": None if matched_label else False,
                },
                "competing_candidates": len(cands),
                "review_status": "REVIEW_REQUIRED",
                "provenance": {
                    "query": term_norm,
                    "service": c["source_service"],
                    "produced_by": c["ontology_source"],
                    "note": "projected from an existing linking run; not re-queried",
                },
            })

    # ── assign a unique, deterministic mapping_id to every row ─────────────
    # Rows can agree on (subject_key, source_tier, concept_id, candidate_rank)
    # when a vocabulary returned the same concept more than once (rank churn).
    # A 0-based occurrence counter in emission order disambiguates them without
    # dropping anything, so ``mapping_id`` is unique by construction and stable
    # across reruns on the same inputs.
    seen = {}
    for r in rows:
        base = (r["subject_key"], r.get("source_tier") or "",
                str(r.get("concept_id") or ""), str(r.get("candidate_rank") or ""))
        k = seen.get(base, 0)
        r["duplicate_index"] = k
        r["mapping_id"] = make_mapping_id(
            r["subject_key"], r.get("source_tier") or "",
            str(r.get("concept_id") or ""), r.get("candidate_rank"), k)
        seen[base] = k + 1
    return rows, n_lookup_failed, n_no_match


def _stage_for(tier, matched_label):
    """Which matching stage produced this candidate (spec: staged matching)."""
    if tier in ("omop_exact", "mesh_gazetteer"):
        return "validated_identifier"
    if tier == "ncbitaxon_exact":
        return "identifier_validation"
    if matched_label:
        return "exact_label"
    return "lexical_candidate_generation"


def main():
    ap = argparse.ArgumentParser(description="Stage 5 — project CV/OMOP/MeSH links")
    ap.add_argument("--cv_jsonl", type=Path, default=CV_JSONL)
    ap.add_argument("--omop_csv", type=Path, default=OMOP_CSV)
    ap.add_argument("--mesh_stats", type=Path, default=MESH_STATS)
    ap.add_argument("--canonical_terms", type=Path, default=None,
                    help="Stage 2 canonical_terms.jsonl for term display names")
    ap.add_argument("--out_dir", type=Path, required=True)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--calibration", type=Path, default=None,
                    help="calibration_thresholds.json from calibrate_thresholds.py; "
                         "when absent or not enabled nothing is auto-accepted")
    args = ap.parse_args()

    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    cv = load_cv(args.cv_jsonl)
    omop = load_omop(args.omop_csv)
    mesh = load_mesh(args.mesh_stats)
    accept_pairs, cal_meta = load_calibration(args.calibration)
    print(f"inputs: cv={len(cv)}  omop_keys={len(omop)}  mesh_terms={len(mesh)}", flush=True)
    print(f"calibration: {cal_meta.get('status')} "
          f"(auto-accept strata: {len(accept_pairs)})", flush=True)

    terms_index = {}
    if args.canonical_terms and args.canonical_terms.exists():
        with args.canonical_terms.open(encoding="utf-8") as f:
            for line in f:
                try:
                    t = json.loads(line)
                except json.JSONDecodeError:
                    continue
                terms_index[(norm(t.get("term_norm")), (t.get("cdm_type") or "").strip())] = t

    rows, n_failed, n_nomatch = build_rows(cv, omop, mesh, terms_index,
                                          accept_pairs=accept_pairs)
    if args.limit:
        rows = rows[:args.limit]

    out_path = out_dir / "term_ontology_mappings.jsonl"
    with out_path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    by_rel = Counter(r["mapping_relation"] for r in rows)
    by_disp = Counter(r["mapping_disposition"] for r in rows)
    by_source = Counter(r["ontology_source"] or "none" for r in rows)
    by_vocab = Counter(r.get("ontology_name") or r["source_service"] or "none"
                       for r in rows if r.get("concept_id"))
    by_resolution = Counter(r["key_resolution"] for r in rows)
    by_type_agreement = Counter(r.get("type_agreement") or "none" for r in rows)
    # "terms with any candidate" is corrected to mean terms that resolved to a
    # canonical term_id AND carry at least one concept id. The old figure
    # (65,293) also counted the 5,237 orphan rows, so it over-counted subjects;
    # the including-unresolved figure is reported separately, never merged in.
    n_terms_resolved = len({r["subject_key"] for r in rows
                            if r.get("concept_id")
                            and r["key_resolution"] != "UNRESOLVED_NO_CANONICAL_TERM"})
    n_terms_resolved_or_unresolved = len({r["subject_key"] for r in rows
                                          if r.get("concept_id")})
    n_ids = len({r["mapping_id"] for r in rows})
    n_null_ids = sum(1 for r in rows if not r.get("mapping_id"))
    summary = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "inputs": {
            "cv_jsonl": str(args.cv_jsonl), "cv_jsonl_exists": args.cv_jsonl.exists(),
            "omop_csv": str(args.omop_csv), "omop_csv_exists": args.omop_csv.exists(),
            "mesh_stats": str(args.mesh_stats), "mesh_stats_exists": args.mesh_stats.exists(),
        },
        "outputs": {"term_ontology_mappings": str(out_path)},
        "counts": {
            "rows": len(rows),
            "rows_with_concept_id": sum(1 for r in rows if r.get("concept_id")),
            "terms_with_any_candidate": n_terms_resolved,
            "terms_with_any_candidate_including_unresolved": n_terms_resolved_or_unresolved,
            "terms_no_match_found": n_nomatch,
            "terms_lookup_failed": n_failed,
            "auto_accept_eligible": sum(1 for r in rows if r.get("auto_accept_eligible")),
            "auto_accepted": sum(1 for r in rows
                                 if r.get("mapping_disposition") == "AUTO_ACCEPTED"),
            "auto_accept_ineligible_non_concept": sum(
                1 for r in rows if r.get("auto_accept_ineligible_reason")),
            "rows_rekeyed_type_divergent": by_resolution.get("REKEYED_TYPE_DIVERGENT", 0),
            "rows_unresolved_no_canonical_term": by_resolution.get(
                "UNRESOLVED_NO_CANONICAL_TERM", 0),
            "distinct_mapping_ids": n_ids,
            "duplicate_mapping_ids": len(rows) - n_ids,
            "null_mapping_ids": n_null_ids,
            "mapping_id_unique": (n_ids == len(rows) and n_null_ids == 0),
        },
        "calibration": {
            **cal_meta,
            "accept_pairs": sorted(accept_pairs),
        },
        "by_mapping_relation": by_rel.most_common(),
        "by_mapping_disposition": by_disp.most_common(),
        "by_key_resolution": by_resolution.most_common(),
        "by_type_agreement": by_type_agreement.most_common(),
        "auto_accept_ineligible_by_reason": Counter(
            r["auto_accept_ineligible_reason"] for r in rows
            if r.get("auto_accept_ineligible_reason")).most_common(),
        "by_ontology_source": by_source.most_common(),
        "by_vocabulary": by_vocab.most_common(40),
        "rules": {
            "EXACT_MATCH": "validated identifier (ncbitaxon/omop/mesh) or text-search label equal to term_norm",
            "RELATED_TO": "text-search candidate with a differing label (candidate generation only)",
            "AMBIGUOUS": "two or more tied top candidates for different concepts",
            "NO_MATCH_FOUND": "no candidate returned; NOT the same as a failed lookup",
            "LOOKUP_FAILED": "the producing stage recorded an error for this term",
        },
        "subject_resolution": {
            "EXACT_KEY": "row's (term_norm, cdm_type) is a canonical term key",
            "REKEYED_TYPE_DIVERGENT": "key absent, but the normalized term exists "
                                      "under another canonical type; re-keyed to the "
                                      "lowest term_id and the divergence recorded",
            "UNRESOLVED_NO_CANONICAL_TERM": "the normalized term has no canonical "
                                            "term; row kept with a deterministic "
                                            "UNRESOLVED subject_key",
            "note": "term_norm and cdm_type on the row stay the mapping's OWN query "
                    "key (evidence); canonical_cdm_type records the resolved term's type.",
        },
        "caveats": [
            "Projection only: nothing is re-queried and no network call is made.",
            "auto_accepted is 0 unless a human-reviewed calibration file is supplied "
            "and reports auto_accept_enabled; the default has no calibration at all.",
            "auto_accept_eligible marks what WOULD qualify once thresholds are calibrated; it is not an acceptance.",
            "auto_accept_ineligible_reason is set for terms flagged as non-concept surfaces "
            "(roman numerals, figure references, URLs, ...); those can never be auto-accepted "
            "even in a calibrated stratum.",
            "lexical_score/semantic_score are null because they were not computed at projection time.",
            "OMOP matching is exact-normalized only, so a miss means 'no exact OMOP name/synonym', not 'absent from OMOP'.",
            "A row whose subject did not resolve to a canonical term (key_resolution = "
            "UNRESOLVED_NO_CANONICAL_TERM) is retained with its candidate evidence but can "
            "never be auto_accept_eligible; it is a broken link to surface, not a deleted row.",
            "mapping_id is unique over the rows (verified: duplicate_mapping_ids = 0) and stable "
            "across reruns; it no longer collapses rank-churn duplicates.",
        ],
        "elapsed_seconds": round(time.time() - t0, 1),
    }
    with (out_dir / "mapping_projection_summary.json").open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print(json.dumps({"counts": summary["counts"],
                      "by_mapping_relation": summary["by_mapping_relation"][:8]}, indent=2))
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
