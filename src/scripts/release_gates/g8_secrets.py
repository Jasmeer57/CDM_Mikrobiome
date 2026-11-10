"""G8 — secret hygiene.

Walks the release tree and every source directory declared in
``PROVENANCE.json:sources``. A file is suspicious when its *basename* matches
``secrets.env``, ``*.env``, ``*.key``, ``*.pem`` or ``secrets*``. Candidate
files are never opened: only basename, mode and size are recorded.

Also checks (existence only) whether ``pipelines/corpus_v2/config/secrets.env`` appears in
the corpus 2.2.0 or data-catalogue ``MANIFEST.sha256``. The secret file itself is
never read.
"""

from __future__ import annotations

import os
from pathlib import Path

from ._common import (
    FAIL,
    MISSING,
    PASS,
    is_secret_basename,
    load_json,
    parse_sha256sum_manifest,
    target_result,
    walk_regular_files,
)

GATE = "G8"

SECRET_REL = "pipelines/corpus_v2/config/secrets.env"
BUNDLE_MANIFESTS = (
    "pipelines/corpus_v2/releases/2.2.0/MANIFEST.sha256",
    "releases/data_catalogue/MANIFEST.sha256",
)


def _source_roots(target: Path, repo_root: Path):
    roots = [target]
    provenance = target / "PROVENANCE.json"
    if provenance.is_file():
        try:
            data = load_json(provenance)
        except Exception:
            return roots
        sources = data.get("sources") or {}
        if isinstance(sources, dict):
            for source in sources.values():
                if isinstance(source, dict):
                    rel = source.get("path")
                elif isinstance(source, str):
                    rel = source
                else:
                    rel = None
                if not rel:
                    continue
                path = Path(rel)
                if not path.is_absolute():
                    path = repo_root / path
                if path.exists():
                    roots.append(path)
    return roots


def _metadata(path: Path):
    try:
        stat = path.stat()
    except OSError as exc:
        return {"path": str(path), "basename": path.name, "error": str(exc)}
    return {
        "path": str(path),
        "basename": path.name,
        "mode": oct(stat.st_mode & 0o777),
        "size": stat.st_size,
    }


def _manifest_inclusion(repo_root: Path):
    results = []
    for rel_manifest in BUNDLE_MANIFESTS:
        manifest = repo_root / rel_manifest
        if not manifest.is_file():
            results.append(
                {
                    "manifest": str(manifest),
                    "exists": False,
                    "contains_secret": None,
                    "matches": [],
                }
            )
            continue
        matches = []
        for _digest, rel in parse_sha256sum_manifest(manifest):
            normalised = os.path.normpath(rel)
            if (
                normalised == SECRET_REL
                or normalised.endswith(os.sep + SECRET_REL)
                or Path(normalised).name == "secrets.env"
            ):
                matches.append(rel)
        results.append(
            {
                "manifest": str(manifest),
                "exists": True,
                "contains_secret": bool(matches),
                "matches": matches[:10],
            }
        )
    return results


def run(target: Path, repo_root: Path) -> dict:
    target = Path(target)
    repo_root = Path(repo_root)
    if not target.is_dir():
        return target_result(GATE, target, MISSING, {"reason": "target directory missing"})

    roots = _source_roots(target, repo_root)
    hits = []
    errors = []
    scanned = 0
    seen = set()

    for root in roots:
        if not root.exists():
            continue
        files = [root] if root.is_file() else walk_regular_files(root)
        for path in files:
            try:
                resolved = str(path.resolve())
            except OSError:
                resolved = str(path)
            if resolved in seen:
                continue
            seen.add(resolved)
            scanned += 1
            if is_secret_basename(path.name):
                meta = _metadata(path)
                if "error" in meta:
                    errors.append(meta)
                else:
                    hits.append(meta)

    secret_path = repo_root / SECRET_REL
    secret_exists = secret_path.exists()
    secret_metadata = _metadata(secret_path) if secret_exists else {"exists": False}
    if secret_exists:
        secret_metadata["exists"] = True

    inclusion = _manifest_inclusion(repo_root)

    problems = []
    if hits:
        problems.append(f"{len(hits)} secret-like basename(s) in scope")
    if any(item.get("contains_secret") for item in inclusion):
        problems.append(f"{SECRET_REL} is listed inside a bundle manifest")
    if errors:
        problems.append(f"{len(errors)} candidate(s) could not be stat'ed")

    status = PASS if not problems else FAIL
    details = {
        "roots_scanned": [str(root) for root in roots],
        "scanned_files": scanned,
        "suspicious_hits": hits,
        "stat_errors": errors,
        "secret_file": {
            "relative_path": SECRET_REL,
            "exists": secret_exists,
            "metadata": secret_metadata,
        },
        "manifest_inclusion": inclusion,
        "problems": problems,
    }
    return target_result(GATE, target, status, details)
