"""Shared helpers for the release-gate framework.

Design rules
------------
* Fail closed.  A missing file is reported as ``MISSING`` and is never
  silently converted to ``0`` or ``PASS``.
* Gates never write inside a release directory.  Reports are written by
  ``check_all.py`` to a caller-supplied path.
* Everything is read-only with respect to the checked artifacts.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

# The 14 CDM entity types plus the generic ``ENTITY`` label produced by
# ``en_core_sci_lg``.  ``ENTITY`` is never evidence of type correctness.
CDM_TYPES = {
    "PROTEIN",
    "ORGANISM",
    "CHEMICAL",
    "DISEASE",
    "DNA_RNA",
    "LAB_METHOD",
    "SAMPLE_METHOD",
    "EXPERIMENTAL_METHOD",
    "CELL_TYPE",
    "CLINICAL",
    "STUDY_DESIGN",
    "DATA_ANALYSIS",
    "GENOMICS",
    "PATHWAY",
    "ENTITY",
}

MAPPING_RELATIONS = {
    "EXACT_MATCH",
    "RELATED_TO",
    "AMBIGUOUS",
    "NO_MATCH_FOUND",
    "EQUIVALENT_TO",
    "NARROWER_THAN",
    "BROADER_THAN",
    "SOURCE_CONCEPT_OF",
    "CONFLICTING_MAPPINGS",
    "INVALID_OR_OBSOLETE",
    "UNVERIFIED",
}

MAPPING_DISPOSITIONS = {"REVIEW_REQUIRED", "UNRESOLVED", "AUTO_ACCEPTED"}

# Files that legitimately exist but are not listed in a sibling manifest.
MANIFEST_BASENAMES = {"MANIFEST.sha256", "MANIFEST.json", "MANIFEST_v1.txt"}

SECRET_RE = re.compile(
    r"(^secrets.*\.env$|^secrets$|.*\.env$|.*\.key$|.*\.pem$)", re.IGNORECASE
)

PASS = "PASS"
FAIL = "FAIL"
SKIP = "SKIP"
NA = "NOT_APPLICABLE"
MISSING = "MISSING"


@dataclass
class GateResult:
    gate: str
    title: str
    status: str
    detail: str = ""
    metrics: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "gate": self.gate,
            "title": self.title,
            "status": self.status,
            "detail": self.detail,
            "metrics": self.metrics,
        }


def sha256_file(path: Path, chunk: int = 1 << 22) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def count_lines(path: Path) -> int:
    """Physical line count; a final line without a newline still counts."""
    n = 0
    with open(path, "rb") as fh:
        for _ in fh:
            n += 1
    return n


def iter_jsonl(path: Path):
    """Yield ``(line_number, obj)``; blank lines are skipped, not counted."""
    with open(path, encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            yield lineno, json.loads(line)


def parse_sha256sum_manifest(path: Path):
    """Parse ``sha256sum`` output (``<digest>  <path>``), tolerating ``*`` mode."""
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


def walk_files(root: Path):
    """Relative POSIX-ish paths of every regular file under ``root``."""
    out = set()
    for base, _dirs, files in os.walk(root):
        for name in files:
            p = Path(base) / name
            out.add(str(p.relative_to(root)))
    return out


def detect_kind(root: Path) -> str:
    if (root / "terminology_extraction_manifest.json").is_file():
        return "TERMINOLOGY"
    if (root / "corpus_manifest.json").is_file():
        return "CORPUS"
    if (root / "MANIFEST.json").is_file():
        return "CATALOGUE"
    return "UNKNOWN"


@dataclass
class Ctx:
    root: Path
    corpus_data: Path | None = None  # .../corpus_v2/releases/2.2.0/data
    repo_root: Path | None = None

    def __post_init__(self):
        self.root = Path(self.root).resolve()
        self.kind = detect_kind(self.root)
        if self.repo_root is None:
            # src/scripts/release_gates/core.py -> repo root
            self.repo_root = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
        else:
            self.repo_root = Path(self.repo_root).resolve()

    def path(self, *parts: str) -> Path:
        return self.root.joinpath(*parts)
