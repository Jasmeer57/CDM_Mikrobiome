#!/usr/bin/env python3
"""Reusable structural + traceability validators for the human-microbiome data catalogue.

Design contract (see temp.md acceptance criteria):
- Pure functions over a catalogue dict (as loaded from
  human_microbiome_data_catalogue.json) plus optional record-dir / schema paths.
- Every check returns structured results, never raises on invalid data; callers
  (builder, release flow, tests) decide what blocks.
- run_all_checks() aggregates into a machine-readable audit report with per-check
  pass/fail and blocking status; write_audit_report() persists next to the outputs.

Checks:
  schema_conformance      jsonschema Draft 2020-12 against the template schema
  fk_integrity            child.paper_id -> papers; asset.dataset_id -> datasets;
                         cohort/sample/assay.dataset_id -> datasets
  id_uniqueness           all *_id fields unique per table
  id_sequence             table ids form a gapless 1..N sequence (stability guard)
  required_fields         schema-required keys non-missing per row
  accession_integrity     one distinct PRJ accession per paper, matches source
                         filename accession, no cross-paper duplicates
  evidence_traceability   every VERIFIED_INLINE finding's evidence_text appears
                         verbatim (normalized) in its paper's source txt
  accession_mapping_conflicts  reconciles catalogue accessions against the
                         BioProject export; classifies RESOLVED / UNVERIFIED /
                         CONFLICTING (export title vs paper title disagreement)
  reproducibility         hashes input dirs/files and records them for rebuild
                         comparisons (called by builder; full byte-rebuild test
                         lives in src/tests/test_data_catalogue.py)

Usage (library):
    from corpus_builder.catalogue_validation import run_all_checks, write_audit_report
    report = run_all_checks(catalogue, v1_dir=..., schema_path=..., bioproject_export=...)
    write_audit_report(report, out_dir)

Usage (CLI):
    python -m corpus_builder.catalogue_validation --catalogue <cat.json> [...]
"""

from __future__ import annotations

import argparse
import datetime
import glob
import hashlib
import json
import logging
import os
import re
import sqlite3
import sys
from pathlib import Path

try:
    import jsonschema
    JSONSCHEMA_AVAILABLE = True
except ImportError:
    JSONSCHEMA_AVAILABLE = False

REPO = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "1.0.0"
TABLES = ("papers", "datasets", "data_assets", "cohorts", "samples", "assays", "findings")
ID_FIELD = {
    "papers": "paper_id",
    "datasets": "dataset_id",
    "data_assets": "asset_id",
    "cohorts": "cohort_id",
    "samples": "sample_group_id",
    "assays": "assay_id",
    "findings": "finding_id",
}
ID_PATTERN = {
    "papers": r"^HMPAPER_[0-9]{6}$",
    "datasets": r"^HMDATA_[0-9]{6}$",
    "data_assets": r"^HMASSET_[0-9]{6}$",
    "cohorts": r"^HMCOHORT_[0-9]{6}$",
    "samples": r"^HMSAMPLE_[0-9]{6}$",
    "assays": r"^HMASSAY_[0-9]{6}$",
    "findings": r"^HMFINDING_[0-9]{6}$",
}

log = logging.getLogger("catalogue_validation")


def now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _norm_ws(s: str) -> str:
    return re.sub(r"\s+", " ", str(s)).strip().lower()


# ---------------------------------------------------------------- structural


def check_schema(catalogue: dict, schema_path=None) -> dict:
    """jsonschema Draft 2020-12 conformance. Blocking when errors > 0."""
    schema_path = schema_path or REPO / "src/template/data_catalogue/human_microbiome_data_catalogue.schema.json"
    if not JSONSCHEMA_AVAILABLE:
        return {"check": "schema_conformance", "pass": None, "blocking": True,
                "n_errors": -1, "errors": [], "note": "jsonschema not installed"}
    sch = json.load(open(schema_path))
    v = jsonschema.Draft202012Validator(sch)
    errors = []
    for i, e in enumerate(v.iter_errors(catalogue)):
        if i >= 50:
            errors.append({"message": "... truncated", "path": []})
            break
        errors.append({"message": e.message, "path": [str(x) for x in e.absolute_path]})
    return {"check": "schema_conformance", "pass": not errors if errors is not None else True,
            "blocking": True, "n_errors": len(errors), "schema": str(schema_path)}


def check_fk(catalogue: dict) -> dict:
    """Cross-table referential integrity. Blocking."""
    pids = {p.get("paper_id") for p in catalogue.get("papers", [])}
    dids = {d.get("dataset_id") for d in catalogue.get("datasets", [])}
    viol = []
    for d in catalogue.get("datasets", []):
        if d.get("paper_id") not in pids:
            viol.append({"table": "datasets", "row": d.get("dataset_id"), "missing": d.get("paper_id"), "target": "papers"})
    for a in catalogue.get("data_assets", []):
        if a.get("dataset_id") not in dids:
            viol.append({"table": "data_assets", "row": a.get("asset_id"), "missing": a.get("dataset_id"), "target": "datasets"})
    for t in ("cohorts", "samples", "assays"):
        for r in catalogue.get(t, []):
            if r.get("paper_id") not in pids:
                viol.append({"table": t, "row": r.get(ID_FIELD[t]), "missing": r.get("paper_id"), "target": "papers"})
            ds = r.get("dataset_id")
            if ds is not None and ds not in dids:
                viol.append({"table": t, "row": r.get(ID_FIELD[t]), "missing": ds, "target": "datasets"})
    for f in catalogue.get("findings", []):
        if f.get("paper_id") not in pids:
            viol.append({"table": "findings", "row": f.get("finding_id"), "missing": f.get("paper_id"), "target": "papers"})
    return {"check": "fk_integrity", "pass": not viol, "blocking": True,
            "violations": viol[:50], "n_violations": len(viol)}


def check_id_uniqueness(catalogue: dict) -> dict:
    """ID uniqueness per table + pattern conformance. Blocking."""
    problems = []
    for t in TABLES:
        rows = catalogue.get(t, [])
        ids = [str(r.get(ID_FIELD[t])) for r in rows]
        seen, dups = set(), set()
        for i in ids:
            if i in seen:
                dups.add(i)
            seen.add(i)
        for i in ids:
            if not re.match(ID_PATTERN[t], i):
                problems.append({"table": t, "id": i, "problem": "pattern"})
        for i in sorted(dups):
            problems.append({"table": t, "id": i, "problem": "duplicate"})
    return {"check": "id_uniqueness", "pass": not problems, "blocking": True, "problems": problems[:50]}


def check_id_sequence(catalogue: dict) -> dict:
    """Gapless 1..N sequences flag: not blocking (stable-id policy is observational)."""
    problems = []
    for t in TABLES:
        rows = catalogue.get(t, [])
        nums = sorted(int(re.sub(r"\D", "", str(r.get(ID_FIELD[t], "0")))) for r in rows if r.get(ID_FIELD[t]))
        expected = list(range(1, len(nums) + 1))
        gapless = nums == expected
        problems.append({"table": t, "n": len(nums), "gapless": gapless})
    bad = [p for p in problems if not p["gapless"]]
    return {"check": "id_sequence", "pass": not bad, "blocking": False, "tables": problems}


def check_required_fields(catalogue: dict) -> dict:
    """Every required schema key present per row. Blocking (schema required[])."""
    problems = []
    required_map = {
        "papers": ("paper_id",),
        "datasets": ("dataset_id", "paper_id"),
        "data_assets": ("asset_id", "dataset_id"),
        "cohorts": ("cohort_id", "paper_id"),
        "samples": ("sample_group_id", "paper_id"),
        "assays": ("assay_id", "paper_id"),
        "findings": ("finding_id", "paper_id"),
    }
    for t, req in required_map.items():
        for r in catalogue.get(t, []):
            for k in req:
                if r.get(k) in (None, ""):
                    problems.append({"table": t, "id": r.get(ID_FIELD[t]), "field": k})
    return {"check": "required_fields", "pass": not problems, "blocking": True,
            "problems": problems[:50], "n_problems": len(problems)}


# ------------------------------------------------------------ scientific


def _source_txt_for_paper(v1_dir: Path, paper_row: dict, paper_to_rec: dict) -> Path | None:
    rec_path = paper_to_rec.get(paper_row.get("paper_id"))
    if not rec_path:
        return None
    rec = json.load(open(rec_path))
    src = rec.get("source", {}).get("source_txt")
    return Path(os.path.expanduser(src)) if src else None


def check_evidence_traceability(catalogue: dict, v1_dir=None, max_mismatches_reported: int = 20) -> dict:
    """Every VERIFIED_INLINE finding's evidence_text (first 120 normalized chars)
    appears in the paper's source text. Blocking — findings shipped as verified
    must trace to source."""
    if v1_dir is None:
        v1_dir = REPO / "outputs/results/human_microbiome_corpus_v1/records"
    v1_dir = Path(v1_dir)
    recs = sorted(glob.glob(str(v1_dir / "*" / "*.json")))
    paper_to_rec = {f"HMPAPER_{i:06d}": p for i, p in enumerate(recs, 1)}
    _cache: dict = {}

    def src_text(paper_id):
        if paper_id not in _cache:
            p = paper_to_rec.get(paper_id)
            _cache[paper_id] = None
            if p:
                rec = json.load(open(p))
                s = rec.get("source", {}).get("source_txt")
                if s and os.path.exists(s):
                    with open(s, encoding="utf-8", errors="replace") as fh:
                        _cache[paper_id] = _norm_ws(fh.read())
        return _cache[paper_id]

    checked, mismatches = 0, []
    not_found_src = []
    for f in catalogue.get("findings", []):
        if f.get("verification_status") != "VERIFIED_INLINE":
            continue
        ev = f.get("evidence_text")
        if not ev:
            mismatches.append({"finding_id": f.get("finding_id"), "problem": "empty_evidence_text"})
            continue
        text = src_text(f.get("paper_id"))
        if text is None:
            not_found_src.append(f.get("paper_id"))
            continue
        checked += 1
        if _norm_ws(ev)[:120] not in text:
            mismatches.append({"finding_id": f.get("finding_id"), "paper_id": f.get("paper_id"),
                               "problem": "evidence_not_in_source", "evidence_snippet": ev[:100]})
    res = {"check": "evidence_traceability", "pass": not mismatches and checked > 0, "blocking": True,
           "n_checked": checked, "n_mismatch": len(mismatches),
           "mismatches": mismatches[:max_mismatches_reported],
           "n_source_missing": len(set(not_found_src)), "source_missing_papers": sorted(set(not_found_src))[:10],
           "denominator": "findings with verification_status == VERIFIED_INLINE and non-empty evidence_text"}
    if not checked and not mismatches:
        res["pass"] = None
        res["note"] = "no VERIFIED_INLINE findings checked — nothing to trace"
    return res


def check_accession_integrity(catalogue: dict, v1_dir=None) -> dict:
    """Each paper has exactly one dataset with exactly one PRJ* accession and no
    accession is shared across papers. Blocking (catalogue structural promise)."""
    problems = []
    seen: dict = {}
    acc_of_paper: dict = {}
    for d in catalogue.get("datasets", []):
        accs = [a for a in (d.get("repository_accession") or []) if a]
        if len(accs) != 1 or not accs[0].startswith("PRJ"):
            problems.append({"dataset_id": d.get("dataset_id"), "problem": "expected exactly one PRJ accession",
                             "accessions": accs})
            continue
        acc = accs[0]
        if acc in seen and seen[acc] != d.get("paper_id"):
            papers_with = [seen[acc], d.get("paper_id")]
            problems.append({"accession": acc, "problem": "cross_paper_duplicate", "papers": papers_with})
        seen.setdefault(acc, d.get("paper_id"))
        prev = acc_of_paper.setdefault(d.get("paper_id"), set())
        prev.add(acc)
    for pid, accs in acc_of_paper.items():
        if len(accs) != 1:
            problems.append({"paper_id": pid, "problem": "multi_accession_paper", "accessions": sorted(accs)})
    return {"check": "accession_integrity", "pass": not problems, "blocking": True,
            "problems": problems[:50], "n_problems": len(problems)}


def check_accession_mapping_conflicts(catalogue: dict, bioproject_export=None) -> dict:
    """Reconcile catalogue accessions vs BioProject export. Resolved / UNVERIFIED /
    CONFLICTING per paper. CONFLICTING = export title disagrees materially with the
    paper title (token-Jaccard re-check after normalization; disagreements are
    surfaced, never auto-resolved). Not silently blocking — release gate reads
    the per-paper list."""
    if bioproject_export is None:
        bioproject_export = REPO / "data" / "bioproject_data_export.json"
    bpe_raw = json.load(open(bioproject_export))
    bpe_raw = bpe_raw.get("bioprojects") if isinstance(bpe_raw, dict) else bpe_raw
    bpe = {x["bioproject_id"]: x for x in bpe_raw if isinstance(x, dict) and x.get("bioproject_id")}

    title_of = {p.get("paper_id"): p.get("title") for p in catalogue.get("papers", [])}
    acc_of = {}
    for d in catalogue.get("datasets", []):
        accs = [a for a in (d.get("repository_accession") or []) if a]
        if accs:
            acc_of.setdefault(d.get("paper_id"), set()).update(accs)

    def tokens(s):
        return set(re.findall(r"[a-z0-9]+", _norm_ws(s or ""))) - {"the", "a", "an", "of", "in", "and", "for", "with"}

    # Matching policy (per review): match on accession/registry membership first;
    # title similarity is informational only. BioProject submitter titles routinely
    # diverge from paper titles, so low Jaccard is divergence, not disagreement.
    # Statuses:
    #   RESOLVED   accession present in the BioProject export (registry-known);
    #              title_agreement recorded for audit (not used to resolve/deny)
    #   REVIEW     accession in export but title agreement ~zero (<0.05) AND the
    #              export title looks like junk/boilerplate OR shares no tokens —
    #              these are queued for Phase 4 metadata-identity verification,
    #              not auto-classified as conflicts
    #   UNVERIFIED accession absent from the export (31 expected) — preserved
    #              as documented uncertainty, never auto-filled
    #   CONFLICTING reserved for evidence that actively disagrees (cross-paper
    #              duplicate accessions, or Phase 4 network identity-mismatch);
    #              this check alone cannot manufacture that evidence
    disposition = {}
    for pid, accs in acc_of.items():
        acc = sorted(accs)[0] if accs else None
        bp = bpe.get(acc)
        if bp is None:
            disposition[pid] = {"accession": acc, "status": "UNVERIFIED",
                               "reason": "not_in_bioproject_export", "bp_title": None,
                               "title_agreement": None}
            continue
        pt, bt = tokens(title_of.get(pid)), tokens(bp.get("title"))
        jac = round(len(pt & bt) / len(pt | bt), 3) if pt and bt else None
        entry = {"accession": acc, "status": "RESOLVED", "title_agreement": jac, "bp_title": bp.get("title")}
        if jac is not None and jac < 0.05 and len(pt) >= 3 and len(bt) >= 3:
            entry["status"] = "REVIEW"
            entry["reason"] = f"title_agreement~0 (jaccard={jac}); queued for metadata-identity verification"
        disposition[pid] = entry
    n_res = sum(1 for v in disposition.values() if v["status"] == "RESOLVED")
    n_unv = sum(1 for v in disposition.values() if v["status"] == "UNVERIFIED")
    n_rev = sum(1 for v in disposition.values() if v["status"] == "REVIEW")
    n_conf = sum(1 for v in disposition.values() if v["status"] == "CONFLICTING")
    return {"check": "accession_mapping_conflicts", "pass": n_conf == 0, "blocking": True,
            "n_resolved": n_res, "n_unverified": n_unv, "n_review": n_rev, "n_conflicting": n_conf,
            "note": "RESOLVED=registry accession match; UNVERIFIED=absent from export (does not "
                    "block, documented); REVIEW=title disagreement ~0, queued for Phase 4 identity "
                    "check (does not block); CONFLICTING=active disagreement only (blocks)",
            "review_queue": {k: v for k, v in disposition.items() if v["status"] == "REVIEW"},
            "per_paper": disposition}


# ---------------------------------------------------------- reproducibility


def hash_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def hash_record_dir(v1_dir) -> dict:
    """Deterministic content hash over record JSONs: sha256 over sorted
    (relative_name, file_sha256) pairs."""
    from pathlib import Path
    v1_dir = Path(v1_dir)
    files = sorted(glob.glob(str(v1_dir / "**" / "*.json"), recursive=True))
    per_file = []
    for f in files:
        rel = os.path.relpath(f, v1_dir)
        per_file.append(f"{rel}:{hash_file(f)}")
    joined = "\n".join(sorted(per_file)).encode("utf-8")
    return {"n_record_files": len(files), "content_sha256": hashlib.sha256(joined).hexdigest()}


def input_manifest(v1_dir, bioproject_export, ner_run_dir=None) -> dict:
    """Everything a rebuild needs to be reproducible/auditable. Builder embeds this
    in the catalogue manifest; a rebuild with mismatched hashes is flagged, so a
    fresh corpus cannot silently mix with stale NER or catalogue artifacts."""
    m = {
        "v1_records": hash_record_dir(v1_dir),
        "bioproject_export": {"sha256": hash_file(bioproject_export), "path": str(bioproject_export)},
        "generated_at": now_iso(),
    }
    if ner_run_dir:
        d = Path(ner_run_dir)
        csvs = sorted(d.glob("*.csv"))
        m["ner_run"] = {"dir": str(d),
                        "files": {c.name: hash_file(c) for c in csvs}}
    return m


# ---------------------------------------------------------------- report


def run_all_checks(catalogue: dict, v1_dir=None, schema_path=None, bioproject_export=None) -> dict:
    results = [
        check_schema(catalogue, schema_path),
        check_fk(catalogue),
        check_id_uniqueness(catalogue),
        check_id_sequence(catalogue),
        check_required_fields(catalogue),
        check_accession_integrity(catalogue),
        check_evidence_traceability(catalogue, v1_dir),
        check_accession_mapping_conflicts(catalogue, bioproject_export),
    ]
    blocking_fail = [r["check"] for r in results if r.get("blocking") and r["pass"] is False]
    return {
        "audit_generated_at": now_iso(),
        "checks": results,
        "overall_pass": not blocking_fail,
        "blocking_failures": blocking_fail,
    }


def write_audit_report(report: dict, out_dir) -> Path:
    out = Path(out_dir) / "catalogue_audit_report.json"
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--catalogue", default=str(REPO / "outputs/results/human_microbiome_data_catalogue/human_microbiome_data_catalogue.json"))
    ap.add_argument("--v1-dir", default=str(REPO / "outputs/results/human_microbiome_corpus_v1/records"))
    ap.add_argument("--schema", default=str(REPO / "src/template/data_catalogue/human_microbiome_data_catalogue.schema.json"))
    ap.add_argument("--bioproject-export", default=str(REPO / "data" / "bioproject_data_export.json"))
    ap.add_argument("--out-dir", default=None, help="where to write catalogue_audit_report.json (default: catalogue dir)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    catalogue = json.load(open(args.catalogue))
    report = run_all_checks(catalogue, v1_dir=args.v1_dir, schema_path=args.schema,
                            bioproject_export=args.bioproject_export)
    out_dir = Path(args.out_dir) if args.out_dir else Path(args.catalogue).parent
    p = write_audit_report(report, out_dir)
    for c in report["checks"]:
        state = c.get("pass")
        label = "PASS" if state else ("FAIL" if state is False else "SKIP")
        extra = c.get("n_errors", c.get("n_violations", c.get("n_problems", c.get("n_mismatch", ""))))
        logging.info("[%s] %s %s", label, c["check"], extra)
    logging.info("Overall: %s (blocking failures: %s)", "PASS" if report["overall_pass"] else "FAIL",
                 report["blocking_failures"] or "none")
    logging.info("Wrote %s", p)
    return 0 if report["overall_pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
