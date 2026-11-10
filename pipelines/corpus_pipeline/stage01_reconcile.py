"""Stage 1 - Inventory reconciliation.

Reconciles the authoritative 453-paper target set against what actually exists on
disk: raw sources, built corpus records, section inventories, and provenance.

Emits:
  manifests/target_453_papers.csv|.json
  manifests/non_target_inventory_entries.csv
  reports/target_453_reconciliation.md|.json

The stage never mutates inputs. Every target paper receives an explicit
disposition, and every gap is recorded rather than silently tolerated.
"""

from __future__ import annotations

import csv
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config as C  # noqa: E402


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def load_id_map() -> dict[str, dict[str, str]]:
    rows: dict[str, dict[str, str]] = {}
    with C.ID_MAP.open() as fh:
        for r in csv.DictReader(fh):
            rows[r["corpus_id"]] = r
    return rows


def load_exclusions() -> dict[str, str]:
    out: dict[str, str] = {}
    if not C.EXCLUSIONS_CSV.exists():
        return out
    with C.EXCLUSIONS_CSV.open() as fh:
        for r in csv.DictReader(fh):
            out[r["bioproject_accession"]] = r.get("exclusion_reason", "")
    return out


# Structural markers of a conference-abstract / supplement-only payload. These
# are deliberately specific: broad phrases such as "all rights reserved" or a
# bare "abstracts " also occur in ordinary full-text articles and must not
# trigger an exclusion.
ABSTRACT_MARKERS = (
    "oral abstracts",
    "this is a conference abstract",
    "conference abstract",
    "abstracts •",
    "suppl 2",
    "abstracts of the",
)


def source_body_stats(src: Path) -> dict:
    """Cheap structural signals used to catch abstract-only sources."""
    try:
        raw = src.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {"exists": False, "bytes": 0, "low": False, "abstract_marker": False}
    nbytes = len(raw.encode("utf-8", errors="replace"))
    head = raw[:3000].lower()
    # An abstract-supplement marker is only believed when the payload is also
    # small; the marker alone appears in the front matter of full articles.
    marker = any(m in head for m in ABSTRACT_MARKERS)
    return {
        "exists": True,
        "bytes": nbytes,
        "low": nbytes < C.ABSTRACT_ONLY_BYTES,
        "abstract_marker": marker and nbytes < C.ABSTRACT_SUPPLEMENT_BYTES,
    }


def classify(record: dict, stats: dict | None = None) -> tuple[str, list[str]]:
    """Derive a readiness state and blocking issues for one corpus record."""
    issues: list[str] = []

    ctrl = record.get("A_record_control", {}) or {}
    integ = record.get("E_full_text_integrity_checks", {}) or {}
    files = record.get("files", {}) or {}
    sections = record.get("F_full_text_section_inventory", []) or []

    completeness = ctrl.get("full_text_completeness")
    if completeness != "complete":
        issues.append(f"full_text_completeness={completeness}")

    src_rel = files.get("source_text_path")
    if not src_rel or not (C.REPO_ROOT / src_rel).exists():
        issues.append("source_text_missing")

    if not sections:
        issues.append("no_sections")
    if not files.get("text_version_path"):
        issues.append("no_text_version")

    # Integrity flags explicitly recorded as failed, not merely unchecked.
    for key in ("title_matches_source", "abstract_matches_source"):
        val = integ.get(key)
        if val in ("no", "fail", "failed", "mismatch"):
            issues.append(f"{key}={val}")

    # Content-level check: catch abstract-only payloads that the recorded
    # completeness flag missed. Both signals must agree before flagging.
    if stats and stats.get("exists"):
        if stats.get("abstract_marker"):
            issues.append("abstract_supplement_marker")
        elif stats.get("low") and len(sections) <= C.ABSTRACT_MAX_SECTIONS:
            issues.append("likely_abstract_only")

    blocking = any(
        i.startswith(("full_text_completeness", "source_text_missing", "no_sections", "no_text_version"))
        or i.endswith("=fail") or i.endswith("=failed") or i.endswith("=mismatch") or i.endswith("=no")
        or i in ("abstract_supplement_marker", "likely_abstract_only")
        for i in issues
    )
    return ("BLOCKED" if blocking else "READY"), issues


def main() -> int:
    C.ensure_dirs()

    id_map = load_id_map()
    exclusions = load_exclusions()

    records: dict[str, dict] = {}
    for p in sorted(C.RECORDS_DIR.glob("HMPAPER_*.json")):
        try:
            records[p.stem] = json.loads(p.read_text())
        except json.JSONDecodeError as exc:
            print(f"[warn] unreadable record {p.name}: {exc}", file=sys.stderr)

    expected_ids = [f"{C.ID_PREFIX}{i:0{C.ID_WIDTH}d}" for i in range(1, C.EXPECTED_TARGET_PAPERS + 1)]

    rows: list[dict] = []
    missing_records: list[str] = []

    for cid in expected_ids:
        rec = records.get(cid)
        meta = id_map.get(cid, {})
        accession = (rec or {}).get("bioproject_accession") or meta.get("bioproject_accession", "")

        if rec is None:
            missing_records.append(cid)
            rows.append({
                "corpus_id": cid,
                "bioproject_accession": accession,
                "title": meta.get("title", ""),
                "doi": meta.get("doi", ""),
                "state": "NO_RECORD",
                "blocking_issues": "record_file_missing",
                "n_sections": 0,
                "n_findings": 0,
                "source_text_present": False,
                "prior_decision": C.PRIOR_DECISIONS.get(accession, ""),
            })
            continue

        src_rel = (rec.get("files", {}) or {}).get("source_text_path", "")
        stats = source_body_stats(C.REPO_ROOT / src_rel) if src_rel else {"exists": False}
        state, issues = classify(rec, stats)
        src_ok = bool(src_rel) and (C.REPO_ROOT / src_rel).exists()

        rows.append({
            "corpus_id": cid,
            "bioproject_accession": accession,
            "title": (rec.get("B_publication_metadata", {}) or {}).get("title", ""),
            "doi": (rec.get("B_publication_metadata", {}) or {}).get("doi", ""),
            "state": state,
            "blocking_issues": ";".join(issues),
            "n_sections": len(rec.get("F_full_text_section_inventory", []) or []),
            "n_findings": len(rec.get("H_findings", []) or []),
            "source_text_present": src_ok,
            "prior_decision": C.PRIOR_DECISIONS.get(accession, ""),
        })

    # Inventory entries that are not among the 453 targets.
    target_accessions = {r["bioproject_accession"] for r in rows if r["bioproject_accession"]}
    non_target = [
        {
            "bioproject_accession": acc,
            "reason": reason,
            "in_target_453": False,
        }
        for acc, reason in sorted(exclusions.items())
        if acc not in target_accessions
    ]
    # Raw sources present on disk but not mapped into the corpus.
    for p in sorted(C.PAPERS_TXT.glob("*.txt")):
        acc = p.stem
        if acc not in target_accessions and acc not in exclusions:
            non_target.append({
                "bioproject_accession": acc,
                "reason": "source_present_but_no_corpus_record",
                "in_target_453": False,
            })

    # ------------------------------------------------------------- write ----
    out_csv = C.MANIFESTS_DIR / "target_453_papers.csv"
    if rows:
        with out_csv.open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)

    (C.MANIFESTS_DIR / "target_453_papers.json").write_text(
        json.dumps(rows, indent=2, ensure_ascii=False)
    )

    with (C.MANIFESTS_DIR / "non_target_inventory_entries.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["bioproject_accession", "reason", "in_target_453"])
        w.writeheader()
        w.writerows(non_target)

    ready = [r for r in rows if r["state"] == "READY"]
    blocked = [r for r in rows if r["state"] == "BLOCKED"]
    with_findings = [r for r in rows if r["n_findings"] > 0]

    summary = {
        "config_version": C.CONFIG_VERSION,
        "expected_targets": C.EXPECTED_TARGET_PAPERS,
        "records_found": len(records),
        "missing_records": missing_records,
        "ready": len(ready),
        "blocked": len(blocked),
        "no_record": len(missing_records),
        "total_sections": sum(r["n_sections"] for r in rows),
        "total_findings": sum(r["n_findings"] for r in rows),
        "papers_with_findings": len(with_findings),
        "papers_without_findings": len(rows) - len(with_findings),
        "non_target_inventory_entries": len(non_target),
        "blocked_detail": [
            {"corpus_id": r["corpus_id"], "accession": r["bioproject_accession"], "issues": r["blocking_issues"]}
            for r in blocked
        ],
        "prior_decision_records": [
            {"accession": k, "prior_state": v, "present_in_target_set": any(
                r["bioproject_accession"] == k for r in rows)}
            for k, v in C.PRIOR_DECISIONS.items()
        ],
    }

    (C.REPORTS_DIR / "target_453_reconciliation.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False)
    )

    lines = [
        "# Stage 1 - Target-453 Inventory Reconciliation",
        "",
        f"- Config version: `{C.CONFIG_VERSION}`",
        f"- Expected target papers: **{C.EXPECTED_TARGET_PAPERS}**",
        f"- Corpus records found: **{len(records)}**",
        f"- Records missing: **{len(missing_records)}**",
        f"- Ready for downstream stages: **{len(ready)}**",
        f"- Blocked: **{len(blocked)}**",
        f"- Total sections inventoried: **{summary['total_sections']}**",
        f"- Total findings recorded: **{summary['total_findings']}** "
        f"(in {len(with_findings)} papers; {len(rows) - len(with_findings)} papers have none)",
        f"- Non-target inventory entries tracked separately: **{len(non_target)}**",
        "",
        "## Blocking issues",
        "",
    ]
    if summary["blocked_detail"]:
        lines += ["| corpus_id | accession | issues |", "|---|---|---|"]
        for b in summary["blocked_detail"][:50]:
            lines.append(f"| {b['corpus_id']} | {b['accession']} | {b['issues']} |")
    else:
        lines.append("None — every target has a complete source, text version, and section inventory.")

    lines += [
        "",
        "## Prior documented decisions (re-verified against disk)",
        "",
        "| accession | prior state | present in target set |",
        "|---|---|---|",
    ]
    for d in summary["prior_decision_records"]:
        lines.append(f"| {d['accession']} | {d['prior_state']} | {'yes' if d['present_in_target_set'] else 'no'} |")

    (C.REPORTS_DIR / "target_453_reconciliation.md").write_text("\n".join(lines) + "\n")

    print(json.dumps({k: v for k, v in summary.items()
                      if k not in ("blocked_detail", "prior_decision_records")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())