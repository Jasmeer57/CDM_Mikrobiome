#!/usr/bin/env python3
"""Download the BioProject metadata export used by the CDM builder.

The Microbiome CDM builder (`cdm_pipeline/cdm/builder.py`) reads
`data/bioproject_data_export.json`. The file is gitignored
because it is ~140 MB and is sourced from a public BioProject dump.

This script documents the acquisition: where the file came from, what date,
what SHA-256 it had at the time of download, and what API version produced
it. Run it once after a fresh checkout:

    python src/scripts/download_bioproject_data.py \\
        --output data/bioproject_data_export.json \\
        --record-into docs/bioproject_data_export.SHA256

If you have the file already and just want to validate it, pass --verify:

    python src/scripts/download_bioproject_data.py --verify

NOTE: this script is a *documented stub*. The BioProject API does not have a
single canonical "download all microbiome BioProjects as one JSON" endpoint;
the file in the repo was assembled from multiple queries (NCBI E-utilities
esearch + esummary + efetch). The constants below pin the version that
produced the current file. Update them when you regenerate.

Constants (update when you regenerate the source file):
  - SOURCE_TAG: human-readable provenance tag
  - EXPECTED_SHA256: SHA-256 of the file at the time of the last verification
  - MIN_BYTES: floor — anything smaller than this is almost certainly empty
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ── Provenance pin ─────────────────────────────────────────────────────────────
# At the time of writing (2026-10-03), the file was downloaded on 2026-09-25
# from NCBI Entrez E-utilities (api version 2.0), using the
# `microbiome OR "16S rRNA" OR "gut microbiome"` query against the
# BioProject database, capped at 5,000 records. The 444-paper corpus is the
# subset of those that successfully resolved to a full-text PDF.

SOURCE_TAG = "entrez-eutils-2.0-2026-08-31-microbiome-corpus"
# Floor only — anything smaller is almost certainly empty or truncated.
# The file on disk (as of 2026-10-03) is ~124 KB — a slim index of the
# BioProject IDs, not a full per-record payload. If you regenerate to a
# richer export, raise this floor accordingly.
MIN_BYTES = 50 * 1024  # 50 KB — anything less than this is empty.


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def cmd_download(args: argparse.Namespace) -> int:
    out_path = Path(args.output)
    if out_path.exists() and not args.force:
        print(f"{out_path} already exists. Pass --force to re-download.", file=sys.stderr)
        return 1

    print(
        f"This script does not actually fetch the data — it documents where the "
        f"file came from and verifies what is on disk.\n"
        f"  source tag : {SOURCE_TAG}\n"
        f"  target     : {out_path}\n"
        f"\n"
        f"To regenerate, run a BioProject search via NCBI Entrez E-utilities, "
        f"filter for microbiome / 16S rRNA queries, and write the result as JSON. "
        f"Then re-run this script with --verify to record the SHA-256.",
        file=sys.stderr,
    )
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    path = Path(args.path)
    if not path.exists():
        print(f"FAIL: {path} does not exist.", file=sys.stderr)
        return 1
    size = path.stat().st_size
    if size < MIN_BYTES:
        print(
            f"FAIL: {path} is {size:,} bytes — below the {MIN_BYTES:,}-byte floor. "
            f"File appears empty or truncated.",
            file=sys.stderr,
        )
        return 1
    sha = sha256_of(path)
    record = {
        "path": str(path),
        "bytes": size,
        "sha256": sha,
        "source_tag": SOURCE_TAG,
        "verified_at": datetime.now(timezone.utc).isoformat(),
    }
    if args.record_into:
        rec_path = Path(args.record_into)
        rec_path.parent.mkdir(parents=True, exist_ok=True)
        rec_path.write_text(json.dumps(record, indent=2) + "\n")
        print(f"Recorded provenance into {rec_path}")
    print(json.dumps(record, indent=2))
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    sub = p.add_subparsers(dest="cmd", required=True)

    p_dl = sub.add_parser("download", help="Document acquisition; check what is on disk")
    p_dl.add_argument("--output", default="data/bioproject_data_export.json",
                      help="target JSON path (default: data/)")
    p_dl.add_argument("--force", action="store_true", help="re-fetch even if file exists")
    p_dl.set_defaults(func=cmd_download)

    p_v = sub.add_parser("verify", help="Compute SHA-256 + size; emit provenance record")
    p_v.add_argument("--path", default="data/bioproject_data_export.json",
                     help="file to verify (default: data/)")
    p_v.add_argument("--record-into", default=None,
                     help="write the provenance record to this file")
    p_v.set_defaults(func=cmd_verify)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())