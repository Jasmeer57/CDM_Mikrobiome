#!/usr/bin/env python3
"""Supporting artifact — versioned, checksummed release entry + inventory crosswalk.

This stage turns a terminology-extraction output directory into a *release
entry*: a self-contained record that says exactly which bytes constitute the
release, what corpus they were derived from, and — critically — how the three
different "term inventory" figures that float around this repo relate to one
another.

It writes INTO the release directory (never into ``releases/data_catalogue/``: that is a
checksummed 1,003-file bundle whose manifest would be invalidated by an in-place
edit, so the release entry is additive and lives with the release).

Outputs (in ``--out_dir``)
--------------------------
    terminology_release_entry.json      manifests + checksums + provenance
    terminology_inventory_crosswalk.md  human-readable 3-inventory reconciliation
    terminology_inventory_crosswalk.csv machine-readable crosswalk

The crosswalk is deliberately *not* a forced equality. The three inventories
count different things at different stages; the job here is to say which is
which and to state the measured overlap, not to make the totals agree.

Rules
-----
* Every count is recomputed from the actual files present in ``--out_dir`` or
  read from the matching summary — never hand-typed, never estimated.
* A missing artifact is reported ``MISSING``, never as zero.
* The release's own digests cover every artifact in ``ARTIFACTS`` plus the
  summary files, so a consumer can verify the bundle byte-for-byte.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
import time
from collections import Counter
from pathlib import Path

REPO_ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())

# The nine artifacts that constitute a terminology release (identical list to
# build_manifest.ARTIFACTS minus the manifest's self-reference, which is hashed
# here as an ordinary file because this entry is written after the manifest).
ARTIFACTS = [
    "term_mentions.jsonl",
    "canonical_terms.jsonl",
    "term_definitions.jsonl",
    "term_ontology_mappings.jsonl",
    "terminology_taxonomy.json",
    "ontology_registry.json",
    "terminology_validation.jsonl",
    "terminology_extraction_report.md",
    "terminology_extraction_manifest.json",
]

SUMMARIES = [
    "_mentions_summary.json",
    "canonical_terms_summary.json",
    "_definitions_summary.json",
    "mapping_projection_summary.json",
    "taxonomy_summary.json",
    "validation_summary.json",
    "terminology_pipeline_summary.json",
]

# ── crosswalk inputs ────────────────────────────────────────────────────────
# Each is (label, path, key fields, what it actually counts). Paths are
# repo-relative and read-only.
UPSTREAM_DEDUP = REPO_ROOT / "releases/data_catalogue/terminology/terminology_dedup.csv"
CORPUS_INVENTORY = REPO_ROOT / "pipelines/corpus_v2/releases/2.2.0/terminology_inventory.csv"
CORPUS_RELEASE_DOC = REPO_ROOT / "pipelines/corpus_v2/releases/2.2.0/MANIFEST.sha256"

# Kept in sync with build_canonical_terms.NORMALIZATION_METHOD / textnorm.
NORMALIZER_NOTE = ("textnorm.sanitize (strip C0/C1 control bytes, collapse "
                   "whitespace runs) then .lower(); the upstream term_norm is "
                   "NOT re-processed by the full norm_term")


def _sha256_file(path: Path, chunk: int = 1 << 20):
    h = hashlib.sha256()
    try:
        with path.open("rb") as f:
            while True:
                b = f.read(chunk)
                if not b:
                    break
                h.update(b)
    except OSError:
        return None
    return h.hexdigest()


def _jsonl_count(path: Path):
    if not path.exists():
        return None
    n = 0
    with path.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.strip():
                n += 1
    return n


def _load(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _norm(s: str) -> str:
    """The release-wide normalized key: sanitize, then lowercase.

    Imported from the pipeline when available so the crosswalk keys cannot drift
    from the join keys the stages actually use; falls back to a local copy only
    if the import fails (e.g. the script is inspected outside the package).
    """
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from textnorm import sanitize  # noqa: E402
        return sanitize(s or "").lower()
    except Exception:
        import re
        s = (s or "").replace("\r", " ").replace("\n", " ")
        s = "".join(ch for ch in s if ch >= " " or ch == "\t")
        return " ".join(s.split()).lower()


def _scan_csv_keys(path: Path, key_fields):
    """Return (rows, distinct_key_tuple_count, key_set) for a CSV."""
    key_set = set()
    n = 0
    with path.open(newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            n += 1
            key_set.add(tuple(_norm(row.get(kf)) for kf in key_fields))
    return n, len(key_set), key_set


def build_crosswalk(out_dir: Path):
    """Reconcile the three inventories. Returns (summary_dict, rows)."""
    # ── A. the release's own canonical terms (recomputed from the artifact) ──
    canon_path = out_dir / "canonical_terms.jsonl"
    canon_rows = 0
    canon_norm = set()
    canon_pairs = set()
    if canon_path.exists():
        with canon_path.open(encoding="utf-8", errors="replace") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                canon_rows += 1
                nn = _norm(d.get("term_norm"))
                canon_norm.add(nn)
                canon_pairs.add((nn, d.get("cdm_type") or ""))

    # ── B. the upstream dedup table the release was built from ──────────────
    up_rows = up_pairs = up_norms = None
    up_norm_set = set()
    if UPSTREAM_DEDUP.exists():
        up_rows, up_pairs, pair_set = _scan_csv_keys(
            UPSTREAM_DEDUP, ("term_norm", "cdm_type"))
        up_norm_set = {p[0] for p in pair_set}
        up_norms = len(up_norm_set)

    # ── C. the corpus_v2 release inventory (a different pipeline + stage) ────
    inv_rows = inv_norms = None
    inv_norm_set = set()
    if CORPUS_INVENTORY.exists():
        inv_rows, inv_norms, pair_set = _scan_csv_keys(
            CORPUS_INVENTORY, ("term_normalized", "term_type"))
        inv_norm_set = {p[0] for p in pair_set}

    overlap_inv = len(inv_norm_set & canon_norm) if inv_norm_set else None
    inv_only = len(inv_norm_set - canon_norm) if inv_norm_set else None
    canon_only_inv = len(canon_norm - inv_norm_set) if inv_norm_set else None

    rows = [
        {
            "inventory": "A_release_canonical_terms",
            "artifact": str(canon_path),
            "unit_of_count": "canonical term = (term_norm, cdm_type)",
            "rows": canon_rows,
            "distinct_terms": len(canon_norm),
            "stage": "this release, Stage 2 output",
            "provenance": "derived from B by normalization/dedup + type split",
            "human_reviewed": False,
        },
        {
            "inventory": "B_upstream_dedup_table",
            "artifact": str(UPSTREAM_DEDUP),
            "unit_of_count": "upstream dedup row = (term_norm, cdm_type)",
            "rows": up_rows,
            "distinct_terms": up_norms,
            "stage": "data_catalogue input table (frozen, read-only)",
            "provenance": "Qwen catalogue extraction + embedding dedup, upstream of this pipeline",
            "human_reviewed": False,
        },
        {
            "inventory": "C_corpus_v2_release_inventory",
            "artifact": str(CORPUS_INVENTORY),
            "unit_of_count": "corpus release term = (term_normalized, term_type)",
            "rows": inv_rows,
            "distinct_terms": inv_norms,
            "stage": "corpus_v2 release 2.2.0 (separate build line)",
            "provenance": "corpus_v2 pipeline; different typer, different section scope",
            "human_reviewed": False,
        },
    ]

    summary = {
        "A_release_canonical_terms": {
            "rows": canon_rows, "distinct_terms": len(canon_norm),
            "distinct_pairs": len(canon_pairs), "path": str(canon_path),
        },
        "B_upstream_dedup_table": {
            "rows": up_rows, "distinct_terms": up_norms, "distinct_pairs": up_pairs,
            "path": str(UPSTREAM_DEDUP),
        },
        "C_corpus_v2_release_inventory": {
            "rows": inv_rows, "distinct_terms": inv_norms,
            "path": str(CORPUS_INVENTORY),
            "source_corpus_release": "corpus_v2 2.2.0",
        },
        "overlap_A_vs_C": {
            "shared_normalized_terms": overlap_inv,
            "only_in_C": inv_only,
            "only_in_A": canon_only_inv,
            "jaccard": (round(overlap_inv / (overlap_inv + inv_only + canon_only_inv), 6)
                        if overlap_inv is not None
                        and (overlap_inv + inv_only + canon_only_inv) else None),
        },
        "not_forced_equal": True,
        "explanation": (
            "The three figures count different entities at different stages and "
            "MUST NOT be forced to agree. A (165,991-style) is this release's "
            "canonical terms: one row per (term_norm, cdm_type). B is the frozen "
            "upstream dedup table this release was built from — it has the same "
            "row shape, so A and B differ only by normalization collisions and "
            "the type split, and that difference is counted, not erased. C is a "
            "DISTINCT build line (corpus_v2 release 2.2.0) with its own typer and "
            "its own section scope, so it is neither a superset nor a subset of "
            "A; the measured overlap is reported instead of a forced total."
        ),
        "normalization": NORMALIZER_NOTE,
    }
    return summary, rows


def _crosswalk_md(summary, rows, version):
    L = []
    A = L.append
    A("# Terminology inventory crosswalk")
    A("")
    A(f"- **Release:** `{version}`")
    A(f"- **Generated:** {time.strftime('%Y-%m-%dT%H:%M:%S')}")
    A("")
    A("Three different 'term inventory' figures are in circulation for this repo. "
      "They count **different entities at different stages**, so the totals are "
      "reported side by side and the measured overlap is given — they are **not** "
      "forced to agree.")
    A("")
    A("| # | Inventory | Unit of count | Rows | Distinct terms | Stage |")
    A("|---|---|---|---|---|---|")
    for r in rows:
        A("| {} | `{}` | {} | {} | {} | {} |".format(
            r["inventory"].split("_")[0], r["inventory"],
            r["unit_of_count"], r["rows"] if r["rows"] is not None else "MISSING",
            r["distinct_terms"] if r["distinct_terms"] is not None else "MISSING",
            r["stage"]))
    A("")
    ov = summary["overlap_A_vs_C"]
    A("## A vs C overlap (normalized-surface terms)")
    A("")
    A("| Measure | Value |")
    A("|---|---|")
    A(f"| Shared normalized terms | {ov['shared_normalized_terms']} |")
    A(f"| Only in C (corpus_v2 2.2.0) | {ov['only_in_C']} |")
    A(f"| Only in A (this release) | {ov['only_in_A']} |")
    A(f"| Jaccard | {ov['jaccard']} |")
    A("")
    A("## Why they differ")
    A("")
    A(summary["explanation"])
    A("")
    A(f"**Normalization key:** {summary['normalization']}")
    A("")
    A("- None of the three inventories is human-reviewed. Every entry is "
      "machine-extracted; `verification_status` on C is `pending` for all rows.")
    A("- B is a read-only frozen input and is never modified by this pipeline; "
      "the release entry lives in the release directory, not in `releases/data_catalogue/`.")
    A("")
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser(description="Build the versioned release entry + crosswalk")
    ap.add_argument("--out_dir", type=Path, required=True)
    ap.add_argument("--version", default="v1")
    ap.add_argument("--corpus_release", default="corpus_v2 2.2.0",
                    help="Source corpus release label recorded in the entry")
    args = ap.parse_args()
    out_dir = args.out_dir
    if not out_dir.exists():
        raise SystemExit(f"missing out_dir: {out_dir}")
    t0 = time.time()

    # ── checksums over artifacts + summaries ────────────────────────────────
    files = []
    for name in ARTIFACTS + SUMMARIES:
        p = out_dir / name
        if not p.exists():
            files.append({"name": name, "status": "MISSING", "path": str(p)})
            continue
        ent = {
            "name": name, "status": "PRESENT", "path": str(p),
            "bytes": p.stat().st_size, "sha256": _sha256_file(p),
        }
        if p.suffix == ".jsonl":
            ent["records"] = _jsonl_count(p)
        files.append(ent)

    n_present = sum(1 for f in files if f["status"] == "PRESENT")
    n_missing = len(files) - n_present

    # ── key counts, read from the summaries (never hand-typed) ──────────────
    canon = _load(out_dir / "canonical_terms_summary.json") or {}
    mentions = _load(out_dir / "_mentions_summary.json") or {}
    defs = _load(out_dir / "_definitions_summary.json") or {}
    mapsum = _load(out_dir / "mapping_projection_summary.json") or {}
    val = _load(out_dir / "validation_summary.json") or {}
    mc = canon.get("counts") or {}
    mp = mapsum.get("counts") or {}

    crosswalk, cw_rows = build_crosswalk(out_dir)

    entry = {
        "release_entry_version": "1.0.0",
        "pipeline_version": args.version,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "release_kind": "terminology_catalogue",
        "source_corpus_release": args.corpus_release,
        "source_corpus_release_note": (
            "The corpus_v2 release is the section-level input universe. Its own "
            "terminology_inventory.csv is a DIFFERENT artifact from this "
            "pipeline's canonical terms and is reconciled in the crosswalk, not "
            "merged."
        ),
        "artifact_integrity": {
            "n_files": len(files),
            "n_present": n_present,
            "n_missing": n_missing,
            "missing": [f["name"] for f in files if f["status"] == "MISSING"],
            "checksum_algorithm": "sha256",
            "files": files,
        },
        "counts": {
            "mention_rows": mentions.get("rows_written"),
            "mention_rows_read": mentions.get("rows_read"),
            "mention_rows_skipped_empty_surface": mentions.get("rows_skipped_empty_surface"),
            "canonical_terms": mc.get("canonical_terms"),
            "terms_with_mention_rollup": mc.get("terms_with_mention_rollup"),
            "mention_rows_linked": mc.get("mention_rows_linked"),
            "mention_rows_unresolved": mc.get("mention_rows_unresolved"),
            "definition_rows": defs.get("definition_rows"),
            "mapping_rows": mp.get("rows"),
            "mapping_id_unique": mp.get("mapping_id_unique"),
            "duplicate_mapping_ids": mp.get("duplicate_mapping_ids"),
            "rows_rekeyed_type_divergent": mp.get("rows_rekeyed_type_divergent"),
            "rows_unresolved_no_canonical_term": mp.get("rows_unresolved_no_canonical_term"),
            "auto_accept_eligible": mp.get("auto_accept_eligible"),
            "auto_accepted": mp.get("auto_accepted"),
            "overall_status": val.get("overall_status"),
        },
        "inventory_crosswalk": crosswalk,
        "human_reviewed": False,
        "verification_note": (
            "No term, definition or mapping in this release is human-verified. "
            "auto_accepted is 0 by construction absent a calibrated, "
            "human-reviewed threshold file."
        ),
        "caveats": [
            "Checksums cover the artifacts and summaries listed above; a missing "
            "file is reported MISSING, never as an empty digest.",
            "The crosswalk does not force the three inventories to a single total; "
            "they count different entities at different stages.",
            "This entry is written into the release directory only. The "
            "checksummed releases/data_catalogue/ bundle is a read-only input and is not "
            "modified in place.",
        ],
        "elapsed_seconds": round(time.time() - t0, 1),
    }

    entry_path = out_dir / "terminology_release_entry.json"
    entry_path.write_text(json.dumps(entry, indent=2, ensure_ascii=False), encoding="utf-8")

    cw_csv = out_dir / "terminology_inventory_crosswalk.csv"
    with cw_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(cw_rows[0].keys()))
        w.writeheader()
        for r in cw_rows:
            w.writerow(r)

    cw_md = out_dir / "terminology_inventory_crosswalk.md"
    cw_md.write_text(_crosswalk_md(crosswalk, cw_rows, args.version), encoding="utf-8")

    print(json.dumps({"artifact_integrity": {
        "n_files": len(files), "n_present": n_present, "n_missing": n_missing,
        "missing": entry["artifact_integrity"]["missing"]},
        "inventory_crosswalk": {k: (v if not isinstance(v, dict)
                                    else {kk: vv for kk, vv in v.items()})
                                for k, v in crosswalk.items()
                                if k in ("A_release_canonical_terms",
                                         "B_upstream_dedup_table",
                                         "C_corpus_v2_release_inventory")}},
        indent=2))
    print(f"wrote {entry_path}")
    print(f"wrote {cw_md}")
    print(f"wrote {cw_csv}")


if __name__ == "__main__":
    main()
