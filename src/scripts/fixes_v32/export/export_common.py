"""Shared helpers for the 3.x exporters (SSSOM, KGX/Biolink, RDF/PROV-O).

Licence policy (paper/publication/rights/PAPER_RIGHTS_MATRIX.csv, proposed policy pending legal review):
  * verbatim evidence text (sentences) is exported only for papers whose proposed_release_decision is INCLUDE_TEXT;
    for every other paper only offsets, anchor status and the SHA-256 of the sentence are exported;
  * any other text value (term labels, triple endpoint labels) is checked with the public-release rules R2-R4 of
    src/scripts/release/build_zenodo_frozen.py (50-character whitespace-normalised windows of withheld text) and
    blanked if it would leak withheld text; identifiers and hashes are always kept.
"""
from __future__ import annotations

import csv
import hashlib
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "crosswalk"))
from schema_common import CANDIDATE_DB, DB_310, OUT, REPO_ROOT, RIGHTS_MATRIX, SCHEMA_ID  # noqa: E402

sys.path.insert(0, str(REPO_ROOT / "src/scripts/release"))
import build_zenodo_frozen as BZF  # noqa: E402  (Rules, key: the public-release redaction rules, ws mode)

EXPORT = OUT / "exports"
NS = SCHEMA_ID.rsplit("/", 1)[0] + "/"            # https://w3id.org/microbiome-cdm/
PREFIXES = {
    "MCDM": NS + "schema/",
    "MCDMT": NS + "term/",            # canonical terms (HMCTERM_...)
    "MCDMR": NS + "triple/",          # canonical triples (HMCV2-CT-...)
    "MCDMM": NS + "mapping/",         # mapping rows (HMMAPROW_...)
    "MCDMP": NS + "paper/",           # papers (HMPAPER_...)
    "MCDMS": NS + "section/",         # sections (HMPAPER_x:sec:n)
    "MCDMRUN": NS + "run/",           # extraction runs
    "MCDMEV": NS + "evidence/",       # triple mention evidence
    "MCDME": NS + "entity/",          # relation endpoint entities not linked to a canonical term
    "MCDMHR": NS + "review/",         # human review records
    "MCDMAG": NS + "agent/",          # agents (software models, anonymised reviewers)
}
ID_NOTE = ("w3id.org/microbiome-cdm/ is used as an identifier namespace for this candidate package; "
           "it is not (yet) registered or resolvable.")


def open_db(path: Path = CANDIDATE_DB) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def rights() -> dict[str, str]:
    return {r["paper_id"]: r["proposed_release_decision"] for r in csv.DictReader(open(RIGHTS_MATRIX))}


def text_allowed(rt: dict, pid: str | None) -> bool:
    return bool(pid) and rt.get(pid) == "INCLUDE_TEXT"


def sha(s: str | None) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest() if s else ""


class Redactor:
    """R2-R4 of the public release for label-like values (built from the frozen section text, read-only)."""

    def __init__(self, con: sqlite3.Connection, rt: dict):
        withheld = {p for p, d in rt.items() if d != "INCLUDE_TEXT"}
        text = {}
        for pid, t in con.execute("SELECT paper_id, section_text_original FROM section"):
            text[pid] = text.get(pid, "") + " " + BZF.key(t)
        self.rules = BZF.Rules(text, withheld)
        self.blanked = 0

    def clean(self, v, pid=None):
        if isinstance(v, str) and self.rules.leaks(v, pid):
            self.blanked += 1
            return ""
        return v


class CurieMaker:
    """IRI -> CURIE with a recorded prefix map.  Expansion of every CURIE returns the stored IRI exactly."""

    def __init__(self):
        import prefixmaps
        self.conv = prefixmaps.load_converter(["obo", "bioregistry.upper", "linked_data"])
        self.used: dict[str, str] = {}
        self._dyn = 0

    def _add(self, prefix, ns):
        if prefix in self.used and self.used[prefix] != ns:
            k = 2
            while f"{prefix}{k}" in self.used and self.used[f"{prefix}{k}"] != ns:
                k += 1
            prefix = f"{prefix}{k}"
        self.used[prefix] = ns
        return prefix

    def curie(self, iri: str) -> str:
        if re.fullmatch(r"C\d{7}", iri):                                    # bare UMLS CUI
            return f"{self._add('UMLS', 'https://uts.nlm.nih.gov/uts/umls/concept/')}:{iri}"
        if re.fullmatch(r"NCBITaxon:\d+", iri):
            self._add("NCBITaxon", "http://purl.obolibrary.org/obo/NCBITaxon_")
            return iri
        m0 = re.fullmatch(r"([A-Za-z][A-Za-z0-9.]*):([A-Za-z0-9._\-]+)", iri)
        if m0 and not iri.startswith(("http:", "https:", "file:")):           # already a CURIE (e.g. gpc:...)
            p = self._add(m0.group(1), NS + "external/" + m0.group(1) + "/")   # unknown namespace, recorded
            return f"{p}:{m0.group(2)}"
        m = re.match(r"^(http://purl\.bioontology\.org/ontology/([A-Za-z0-9_-]+)/)(.+)$", iri)
        if m and "/" not in m.group(3) and "#" not in m.group(3):
            p = self._add(m.group(2).upper() + "_BP", m.group(1))           # BioPortal namespace kept verbatim
            return f"{p}:{m.group(3)}"
        try:
            c = self.conv.compress(iri)
        except Exception:
            c = None
        if c:
            p, loc = c.split(":", 1)
            if re.fullmatch(r"[A-Za-z0-9._~\-]+", loc) and self.conv.expand(c) == iri:
                self._add(p, iri[: len(iri) - len(loc)])
                return c
        m = re.match(r"^(.*[/#_])([^/#_]+)$", iri)
        if not m:
            raise ValueError(f"cannot make a CURIE for {iri}")
        ns, loc = m.groups()
        for p, n in self.used.items():
            if n == ns:
                return f"{p}:{loc}"
        self._dyn += 1
        host = re.sub(r"[^A-Za-z0-9]", "", re.sub(r"^https?://(www\.)?", "", ns).split("/")[0])[:12].upper()
        return f"{self._add('X' + host, ns)}:{loc}"


def biolink_maps():
    import curated_mappings as CM
    return CM


def write_tsv(path: Path, rows: list[dict], fields: list[str] | None = None):
    fields = fields or list(dict.fromkeys(k for r in rows for k in r))
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, delimiter="\t", lineterminator="\n", extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in fields})
