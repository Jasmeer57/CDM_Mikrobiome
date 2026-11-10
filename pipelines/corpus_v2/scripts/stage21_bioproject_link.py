#!/usr/bin/env python3
"""Stage 21: exact BioProject linkage to the Abdill-2025 full-text bundle.

Source: ../168000-samples-paper/fulltext/{manifest.csv, <PRJ>/meta.json}

Why this exists
---------------
Stage 20 resolves identifiers by *title search*, which is probabilistic. Every
one of our 453 papers carries a BioProject accession in its front matter, and
the compendium bundle indexes those accessions exactly. Joining on the
accession therefore replaces a fuzzy match with an exact link, and supplies an
abstract plus the path of the original JATS/PDF for the later cross-check.

Rules
-----
- identifiers (DOI/PMID/PMCID) prefer the exact-accession record; a differing
  API value is preserved in `metadata_conflicts`, never discarded
- title/journal/year/abstract are only *filled* when empty; a differing value
  is recorded as a conflict and the existing value is kept
- a paper with no manifest row is REVIEW_REQUIRED, not silently skipped
- nothing in data/ is overwritten with a value that has no recorded provenance

Outputs: data/papers.jsonl (updated), validation/bioproject_link_report.json
Resume: checkpoints/stage21_bioproject_link.jsonl keyed by paper_id.
"""
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import common as C

STAGE = "stage21_bioproject_link"
PV = "2.0.0"

BUNDLE = C.REPO_ROOT / "data/168000-samples-paper" / "fulltext"
MANIFEST = BUNDLE / "manifest.csv"
TITLE_MATCH_MIN = 0.90


def load_manifest() -> dict:
    out = {}
    if not MANIFEST.exists():
        return out
    with open(MANIFEST, encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            prj = (row.get("project") or "").strip()
            if prj:
                out[prj] = row
    return out


def load_meta(prj: str) -> dict:
    p = BUNDLE / prj / "meta.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - malformed sidecar is recorded, not fatal
        return {"_error": "unreadable meta.json"}


def clean(v) -> str | None:
    if v is None:
        return None
    v = str(v).strip()
    return v or None


def title_similarity(a: str, b: str) -> float:
    at, bt = set(C.normalize_title(a).split()), set(C.normalize_title(b).split())
    if not at or not bt:
        return 0.0
    return len(at & bt) / min(len(at), len(bt))


def main():
    C.require_slurm(STAGE)
    cfg = C.load_config()
    ev = C.Events(cfg["corpus"]["corpus_id"], STAGE, PV)
    cur = C.CurationLog()

    if not MANIFEST.exists():
        sys.exit(f"ERROR: {MANIFEST} not found; cannot link BioProjects")
    manifest = load_manifest()
    papers = C.read_jsonl(C.CORPUS_DIR / "data" / "papers.jsonl")
    if not papers:
        sys.exit("ERROR: data/papers.jsonl missing; run stages 10-20 first")

    prog = C.Progress(STAGE, total=len(papers), unit="paper", desc="bioproject link")
    ckpt = C.Checkpoint(C.CORPUS_DIR / "checkpoints" / f"{STAGE}.jsonl", key="paper_id")
    started = C.now_utc()

    # ---- apply per paper ----
    for p in papers:
        pid = p["paper_id"]
        prj = (p.get("bioproject") or "").strip()
        fp = C.sha256_text(f"{pid}|{prj}|{p.get('title')}|{p.get('DOI')}|{p.get('PMID')}|"
                           f"{p.get('publication_type')}")
        if ckpt.has(pid, fp):
            prog.update(1, detail=f"{pid} resumed")
            continue

        rec = dict(p)
        row = manifest.get(prj) if prj else None
        meta = load_meta(prj) if prj else {}
        conflicts = list(rec.get("metadata_conflicts") or [])

        def resolve(field, bundle_value, prefer_bundle=False):
            """Fill when empty; on disagreement record it and keep policy."""
            b = clean(bundle_value)
            ours = clean(rec.get(field))
            if not b:
                return
            if not ours:
                rec[field] = b
                rec.setdefault("metadata_provenance", {})[field] = {
                    "source": "internal:168000-samples-paper/fulltext",
                    "method": "exact_bioproject",
                    "bioproject": prj,
                }
                return
            if C.normalize_title(str(ours)) != C.normalize_title(str(b)):
                entry = {
                    "field": field,
                    "existing": ours,
                    "bundle": b,
                    "existing_source": (rec.get("metadata_provenance") or {}).get(
                        field, {}).get("source"),
                    "resolution": "bundle_preferred" if prefer_bundle else "existing_kept",
                }
                if entry not in conflicts:      # idempotent on re-run
                    conflicts.append(entry)
                if prefer_bundle:
                    rec[field] = b
                    rec.setdefault("metadata_provenance", {})[field] = {
                        "source": "internal:168000-samples-paper/fulltext",
                        "method": "exact_bioproject",
                        "bioproject": prj,
                        "superseded": ours,
                    }

        # identifiers: exact accession beats a fuzzy title match
        resolve("DOI", row.get("doi") if row else None, prefer_bundle=True)
        resolve("PMID", row.get("pmid") if row else None, prefer_bundle=True)
        resolve("PMCID", row.get("pmcid") if row else None, prefer_bundle=True)
        # descriptive fields: only fill gaps, keep the paper's own wording
        resolve("title", meta.get("title") or (row.get("title") if row else None))
        resolve("journal", meta.get("journal") or (row.get("journal") if row else None))
        resolve("publication_year", meta.get("year") or (row.get("year") if row else None))
        resolve("abstract", meta.get("abstract"))

        # PubMed returns a comma-joined type list; the schema wants one value
        if rec.get("publication_type"):
            raw_pt = rec["publication_type"]
            norm_pt = C.normalize_publication_type(raw_pt)
            if norm_pt != raw_pt:
                prov = rec.setdefault("metadata_provenance", {})
                prov["publication_type"] = {
                    "source": (prov.get("publication_type") or {}).get(
                        "source", "pubmed_pubtype_list"),
                    "method": "controlled_vocabulary_mapping",
                    "raw_value": raw_pt,
                }
                rec["publication_type"] = norm_pt

        if rec.get("publication_year"):
            try:
                rec["publication_year"] = int(str(rec["publication_year"])[:4])
            except ValueError:
                pass

        fmt = clean(row.get("format")) if row else None
        status = clean(row.get("status")) if row else None
        rel_path = clean(row.get("path")) if row else None
        original_path = str(BUNDLE / prj / rel_path) if (prj and rel_path) else None
        if original_path and not Path(original_path).exists():
            original_path = None
            fmt = None

        rec["bioproject_link"] = {
            "bioproject": prj or None,
            "matched": row is not None,
            "match_method": "exact_bioproject_accession",
            "bundle_status": status,
            "bundle_format": fmt,
            "bundle_original_path": original_path,
            "bundle_bytes": clean(row.get("bytes")) if row else None,
            "bundle_is_oa": clean(row.get("is_oa")) if row else None,
            "bundle_resolved_via": clean(row.get("resolved_via")) if row else None,
            "bundle_local_text": clean(row.get("local_text")) if row else None,
            "meta_json_present": bool(meta),
            "independent_fulltext_available": fmt in ("jats_xml", "pdf"),
            "linked_at": C.now_utc(),
        }
        if original_path:
            rec["original_fulltext_path"] = original_path
            rec["original_fulltext_format"] = fmt
            if fmt == "jats_xml":
                rec["original_xml_path"] = original_path
            elif fmt == "pdf":
                rec["original_pdf_path"] = original_path
        rec["metadata_conflicts"] = conflicts

        # ---- fail-closed ----
        checks = [
            ("CRIT_bioproject_present", bool(prj), "no BioProject accession in source"),
            ("PART_bundle_match", row is not None,
             f"BioProject {prj} absent from the 168000-samples-paper bundle"),
            ("PART_publication_exists",
             status not in (None, "no_publication"),
             f"bundle status={status} (unreferenced sequence deposit, no article)"),
            ("WARN_identifier", bool(rec.get("DOI") or rec.get("PMID")),
             "no DOI and no PMID after linkage"),
            ("WARN_title", bool(rec.get("title")), "no title after linkage"),
        ]
        link_status, reason = C.fail_closed(checks)
        rec["bioproject_link"]["link_status"] = link_status
        rec["bioproject_link"]["link_evidence"] = reason

        ckpt.add({"paper_id": pid, "paper": rec}, fingerprint=fp)
        ev.record(pipeline_stage=STAGE, paper_id=pid,
                  run_status="success" if link_status == "COMPLETE" else "partial",
                  input_artifact_hash=C.sha256_text(prj or pid),
                  output_artifact_hash=C.sha256_text(json.dumps(
                      rec["bioproject_link"], sort_keys=True, default=str)),
                  error_message=None if link_status == "COMPLETE" else reason)
        if link_status != "COMPLETE":
            cur.add(pid, STAGE, "stage21_bioproject_link", PV,
                    "exact BioProject join", link_status, problem=reason,
                    resolution="recorded; no value invented")
        prog.update(1, detail=f"{pid} {prj} {link_status} "
                              f"fmt={fmt or '-'} doi={bool(rec.get('DOI'))} "
                              f"pmid={bool(rec.get('PMID'))}")

    ckpt.close()
    updated = [ckpt.done[p["paper_id"]]["paper"] for p in papers]
    C.write_jsonl(C.CORPUS_DIR / "data" / "papers.jsonl", updated)
    C.write_tracking_table(updated)

    def count(pred):
        return sum(1 for r in updated if pred(r))

    summary = {
        "stage": STAGE, "pipeline_version": PV, "generated_at": C.now_utc(),
        "bundle": str(BUNDLE),
        "papers": len(updated),
        "linked_to_bioproject": count(lambda r: r["bioproject_link"]["matched"]),
        "unlinked": [r["paper_id"] for r in updated if not r["bioproject_link"]["matched"]],
        "bundle_status_counts": {},
        "bundle_format_counts": {},
        "independent_fulltext_available": count(
            lambda r: r["bioproject_link"]["independent_fulltext_available"]),
        "with_doi": count(lambda r: r.get("DOI")),
        "with_pmid": count(lambda r: r.get("PMID")),
        "with_pmcid": count(lambda r: r.get("PMCID")),
        "with_title": count(lambda r: r.get("title")),
        "with_abstract": count(lambda r: r.get("abstract")),
        "papers_with_conflicts": count(lambda r: r.get("metadata_conflicts")),
        "conflict_total": sum(len(r.get("metadata_conflicts") or []) for r in updated),
        "link_status_counts": {},
        "titles_still_missing": [r["paper_id"] for r in updated if not r.get("title")],
    }
    for r in updated:
        s = r["bioproject_link"]["bundle_status"] or "none"
        f = r["bioproject_link"]["bundle_format"] or "none"
        summary["bundle_status_counts"][s] = summary["bundle_status_counts"].get(s, 0) + 1
        summary["bundle_format_counts"][f] = summary["bundle_format_counts"].get(f, 0) + 1
        st = r["bioproject_link"]["link_status"]
        summary["link_status_counts"][st] = summary["link_status_counts"].get(st, 0) + 1

    C.atomic_write_json(C.CORPUS_DIR / "validation" / "bioproject_link_report.json", summary)
    ev.record(pipeline_stage=STAGE, run_status="success", started_at=started,
              completed_at=C.now_utc(),
              output_artifact_hash=C.sha256_text(json.dumps(summary, sort_keys=True)),
              note=f"linked={summary['linked_to_bioproject']}/{len(updated)} "
                   f"independent_fulltext={summary['independent_fulltext_available']}")
    ev.close()
    prog.close(summary=f"linked={summary['linked_to_bioproject']}/{len(updated)} "
                       f"doi={summary['with_doi']} pmid={summary['with_pmid']} "
                       f"conflicts={summary['conflict_total']}")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
