#!/usr/bin/env python
"""Offline OMOP concept lookup against a locally built Athena index.

``map_omop`` in ``src/cdm_pipeline/mapping/mappers.py`` is a dead stub: the
public Athena API (``api.ohdsi.org``) returns HTTP 500, so OMOP has never
contributed a single mapping. With a full Athena vocabulary download that is
no longer necessary — this module resolves concepts from a local SQLite index
(``src/scripts/vllm_termpop/build_omop_index.py``) with no network at all.

Design constraints, agreed with the user:

* **separate view** — OMOP results are returned in their own channel and are
  deliberately *not* injected into ``config.VOCAB_PRIORITY``, so adding OMOP
  can never silently displace an existing UMLS/MESH/NCBITaxon canonical.
* **non-standard aware** — when a term matches a non-standard concept, the
  ``Maps to`` relationship is followed so the standard concept is reported too
  (that is the whole point of having the vocabulary locally).

The lookup is exact-match on a normalized string, which is deterministic and
cheap; fuzzy matching is intentionally left to the caller's ``_confidence``
scoring rather than being hidden in here.
"""
import sqlite3
import threading
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INDEX = REPO_ROOT / "outputs/results" / "omop_vocab" / "omop_index.sqlite"

# Vocabulary ids in the Athena bundle that are *not* useful as a mapping target
# for a microbiome CDM: they are administrative, pricing, or drug-code bundles
# with no concept-level semantics (e.g. NDC package codes, SPL labels).
EXCLUDE_VOCABS = {
    "NDC", "SPL", "EDI", "GCN_SEQNO", "OSM", "DPD", "AMT", "BDPM", "VANDF",
    "GGR", "dm+d", "NDFRT", "PACK", "CPT4", "HCPCS", "JMDC", "KDC", "NCCD",
    "OPS", "OPCS4", "CCAM", "ICD10PCS", "CIM10", "KCD7", "ICD10CN", "ICD10GM",
    "ICD10", "ICD9ProcCN", "Read", "NAACCR", "CDISC", "CIEL",
}

_local = threading.local()


def _conn(index_path):
    c = getattr(_local, "conn", None)
    if c is None or getattr(_local, "path", None) != str(index_path):
        c = sqlite3.connect(f"file:{index_path}?mode=ro", uri=True)
        c.row_factory = sqlite3.Row
        _local.conn = c
        _local.path = str(index_path)
    return c


def _norm(s):
    return " ".join((s or "").lower().split())


def available(index_path=DEFAULT_INDEX):
    return Path(index_path).exists()


def lookup(term, cdm_type=None, index_path=DEFAULT_INDEX, limit=5,
           include_non_standard=True):
    """Resolve ``term`` to OMOP concepts from the local index.

    Returns a list of candidate dicts shaped like the other mappers' output
    (``source``, ``ontology_name``, ``concept_id``, ``label``, ``confidence``)
    so callers can treat it uniformly. ``confidence`` is a fixed exact-match
    score (1.0) because the lookup *is* an exact normalized match; any fuzzy
    re-scoring is the caller's business.

    ``cdm_type`` is accepted for interface symmetry but is deliberately unused:
    OMOP concepts are typed by ``domain_id`` already, and filtering by CDM type
    here would need a domain->CDM map that the user asked us not to invent.
    """
    if not available(index_path):
        return []
    nm = _norm(term)
    if not nm:
        return []

    con = _conn(index_path)
    rows = []
    # preferred names first, then synonyms
    for r in con.execute(
        "SELECT c.concept_id, c.name, c.domain_id, c.vocabulary_id, "
        "       c.concept_class_id, c.standard_concept, t.is_preferred "
        "FROM term t JOIN concept c ON c.concept_id = t.concept_id "
        "WHERE t.norm = ? "
        "ORDER BY t.is_preferred DESC, c.standard_concept DESC, c.concept_id "
        "LIMIT ?", (nm, limit)):
        rows.append(r)

    out = []
    for r in rows:
        if r["vocabulary_id"] in EXCLUDE_VOCABS:
            continue
        out.append({
            "source": "omop_local",
            "ontology_name": (r["vocabulary_id"] or "").upper(),
            "concept_id": str(r["concept_id"]),
            "label": r["name"],
            "confidence": 1.0,
            "omop_domain": r["domain_id"],
            "omop_vocab": r["vocabulary_id"],
            "omop_concept_class": r["concept_class_id"],
            "omop_standard": r["standard_concept"] == "S",
            "omop_matched_via": "preferred" if r["is_preferred"] else "synonym",
        })
        if r["standard_concept"] == "S":
            out[-1]["omop_standard_concept_id"] = str(r["concept_id"])
            out[-1]["omop_standard_concept_name"] = r["name"]
        elif include_non_standard:
            # follow `Maps to` so the standard target is reported too
            std = con.execute(
                "SELECT concept_id, name, vocabulary_id, domain_id "
                "FROM maps_to WHERE src_concept_id = ? "
                "ORDER BY concept_id LIMIT 1", (r["concept_id"],)).fetchone()
            if std:
                out[-1]["omop_standard_concept_id"] = str(std["concept_id"])
                out[-1]["omop_standard_concept_name"] = std["name"]
                out[-1]["omop_standard_vocab"] = std["vocabulary_id"]
                out[-1]["omop_standard_domain"] = std["domain_id"]
    return out


def stats(index_path=DEFAULT_INDEX):
    if not available(index_path):
        return {}
    con = _conn(index_path)
    d = {}
    for t in ("concept", "term", "maps_to"):
        try:
            d[t] = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        except sqlite3.Error:
            d[t] = None
    return d


if __name__ == "__main__":
    import argparse
    import json
    import sys

    ap = argparse.ArgumentParser(description="Offline OMOP concept lookup")
    ap.add_argument("terms", nargs="+")
    ap.add_argument("--index", default=str(DEFAULT_INDEX))
    args = ap.parse_args()
    print(json.dumps(stats(args.index), indent=2))
    for t in args.terms:
        print(f"\n{t!r}")
        for c in lookup(t, index_path=args.index):
            print("   ", json.dumps(c, ensure_ascii=False))
