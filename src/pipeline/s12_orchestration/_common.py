"""Shared, read-only helpers for the minimal P0.3 release gates.

Design rules
------------
* Read-only: no helper writes to a gate input.
* Fail-closed: missing inputs are reported as ``MISSING``, never as ``0``.
* Deterministic: sampling ranks by ``sha1("qc-v1|" + stable_id)``; there is no
  ``random()``, no builtin ``hash()`` and no ``os.urandom()``.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

PASS = "PASS"
FAIL = "FAIL"
SKIPPED = "SKIPPED"
MISSING = "MISSING"

SECRET_PATTERNS = ("secrets.env", "*.env", "*.key", "*.pem", "secrets*")


def utc_now() -> str:
    """Current UTC time in the repository's report format."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha1_hex(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def stable_key(value: object, prefix: str = "qc-v1|") -> str:
    """Deterministic ranking key (never builtin ``hash()``)."""
    return sha1_hex(prefix + str(value))


def deterministic_sample(items, k: int, id_getter=lambda item: item, prefix: str = "qc-v1|"):
    """Return the ``k`` items with the smallest ``sha1(prefix + id)``."""
    ranked = sorted(items, key=lambda item: (stable_key(id_getter(item), prefix), str(id_getter(item))))
    return ranked[:k]


def count_physical_lines(path: Path) -> int:
    """Physical line count via streaming read; a final line without newline counts."""
    n = 0
    with open(path, "rb") as fh:
        for _ in fh:
            n += 1
    return n


def iter_jsonl(path: Path):
    """Yield parsed JSON objects; blank lines are skipped."""
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)


def load_json(path: Path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def parse_sha256sum_manifest(path: Path):
    """Parse ``sha256sum`` output into ``[(digest, relative_path), ...]``."""
    entries = []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line.strip():
                continue
            parts = line.split(None, 1)
            if len(parts) != 2 or len(parts[0]) != 64:
                continue
            digest, rel = parts
            entries.append((digest.lower(), rel.lstrip("*").lstrip("./")))
    return entries


def walk_regular_files(root: Path):
    """Yield regular files under ``root`` without following directory symlinks."""
    for base, _dirs, names in os.walk(root):
        for name in names:
            p = Path(base) / name
            if p.is_file():
                yield p


def is_terminology_release(root: Path) -> bool:
    return (root / "terminology_extraction_manifest.json").is_file()


def is_secret_basename(name: str) -> bool:
    low = name.lower()
    return any(fnmatch.fnmatch(low, pattern) for pattern in SECRET_PATTERNS)


def gate_status(statuses) -> str:
    """Aggregate target statuses into a gate status.

    ``MISSING`` is a failure. ``SKIPPED`` only wins when every target skipped.
    """
    statuses = list(statuses)
    if any(s in (FAIL, MISSING) for s in statuses):
        return FAIL
    if any(s == PASS for s in statuses):
        return PASS
    return SKIPPED


def target_result(gate: str, target: Path, status: str, details=None) -> dict:
    return {
        "gate": gate,
        "target": str(Path(target)),
        "status": status,
        "details": details or {},
    }
