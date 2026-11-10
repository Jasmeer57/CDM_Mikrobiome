"""Shared utility functions."""
import csv
import io
import re


def is_junk(term):
    """Return True if a term is likely an extraction artifact (punctuation/noise)."""
    t = term.strip()
    if len(t) < 2:
        return True
    if len(t) < 3 and not t.isalpha():
        return True
    if re.sub(r"^[\W\d_]+|[\W_]+$", "", t, flags=re.UNICODE) == "":
        return True
    if t.startswith((",", ".", ")", "(", "[", "]", "'", '"', ";", ":", "-")):
        return True
    if t.endswith((",", ".", ")", "(", "[", "]", "'", '"', ";", ":", "-")):
        return True
    if "\n" in t or "\t" in t:
        return True
    if re.fullmatch(r"[\d\s\W]+", t):
        return True
    if re.search(r"[a-z]\)", t) and len(t) < 30:
        return True
    return False


def norm(t):
    """Normalize a term for deduplication: lowercase + collapse whitespace.

    Canonical version lives in the root-level ``common`` package; this is kept
    for backward-compatible ``from cdm_pipeline.utils import norm`` imports.
    """
    return re.sub(r"\s+", " ", t.lower().strip())


def load_csv_safe(path):
    """Load a CSV file, tolerating null bytes and encoding issues."""
    with open(path, encoding="utf-8", errors="replace") as f:
        content = f.read().replace("\x00", "")
        return list(csv.DictReader(io.StringIO(content)))
