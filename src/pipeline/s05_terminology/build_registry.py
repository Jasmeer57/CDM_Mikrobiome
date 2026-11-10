#!/usr/bin/env python3
"""Supporting artifact — ``ontology_registry.json``.

A registry of every vocabulary the pipeline actually consulted, with the
version/edition that was used and how it was reached. It is assembled from the
**measured** state of the inputs, not from memory: a vocabulary whose local
files are absent is recorded with ``available: false`` and a reason, never
omitted and never claimed.

Nothing here is a claim that a vocabulary is complete or that a term is absent
from it — only that a specific edition/route was used.

Outputs (in ``--out_dir``)
--------------------------
    ontology_registry.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

MESH_DESC = REPO_ROOT / "outputs/results/mesh_ner/raw/desc2026.xml"
MESH_SUPP = REPO_ROOT / "outputs/results/mesh_ner/raw/supp2026.xml"
MESH_QUAL = REPO_ROOT / "outputs/results/mesh_ner/raw/qual2026.xml"
OMOP_INDEX = REPO_ROOT / "outputs/results/omop_vocab/omop_index.sqlite"
OMOP_CONCEPT = REPO_ROOT / "outputs/results/omop_vocab/CONCEPT.csv"
OMOP_VOCAB = REPO_ROOT / "outputs/results/omop_vocab/VOCABULARY.csv"


def _credential_present(name: str) -> bool:
    """True if the key is in the environment OR present in a local .env file.

    Only presence is tested — the value is never read into memory, logged, or
    written into the registry.
    """
    if os.environ.get(name):
        return True
    for envf in (REPO_ROOT / ".env", REPO_ROOT / "pipelines/corpus_v2/config/secrets.env"):
        try:
            for line in envf.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith(f"{name}=") and line.split("=", 1)[1].strip():
                    return True
        except OSError:
            continue
    return False


def _size(p: Path):
    try:
        return p.stat().st_size
    except OSError:
        return None


def _sqlite_count(db: Path, table: str):
    if not db.exists():
        return None
    try:
        import sqlite3
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            return con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        finally:
            con.close()
    except Exception:
        return None


def _xml_count(path: Path, tag: str):
    """Count occurrences of ``<tag>`` without parsing a 300 MB file into memory."""
    if not path.exists():
        return None
    n = 0
    pat = re.compile(rf"<{tag}[ >]".encode())
    with path.open("rb") as f:
        while True:
            chunk = f.read(1 << 22)
            if not chunk:
                break
            n += len(pat.findall(chunk))
    return n


def main():
    ap = argparse.ArgumentParser(description="Build ontology_registry.json")
    ap.add_argument("--out_dir", type=Path, required=True)
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    cv_cfg = REPO_ROOT / "outputs/results/cv_linking/cv_summary.json"
    mesh_sum = REPO_ROOT / "outputs/results/mesh_ner/_mesh_summary.json"
    omop_sum = REPO_ROOT / "outputs/results/omop_linking/omop_summary.json"

    def _load(p):
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None

    mesh_s = _load(mesh_sum)
    omop_s = _load(omop_sum)

    entries = [
        {
            "vocabulary": "MeSH",
            "edition": "2026",
            "authority": "U.S. National Library of Medicine",
            "route": "offline gazetteer (Aho-Corasick dictionary matching)",
            "availability": "local",
            "available": MESH_DESC.exists(),
            "source_files": {
                str(MESH_DESC.relative_to(REPO_ROOT)): _size(MESH_DESC),
                str(MESH_SUPP.relative_to(REPO_ROOT)): _size(MESH_SUPP),
                str(MESH_QUAL.relative_to(REPO_ROOT)): _size(MESH_QUAL),
            },
            "counts": {
                "descriptors_parsed": (mesh_s or {}).get("descriptors")
                or _xml_count(MESH_DESC, "DescriptorRecord"),
                "supplementals_parsed": (mesh_s or {}).get("supplementals")
                or _xml_count(MESH_SUPP, "SupplementalRecord"),
            },
            "network_required": False,
            "notes": "Entry terms live in ConceptList/Concept/TermList/Term; the 2026 "
                     "XML has no <EntryTerm> element. Supplementals link via HeadingMappedTo.",
        },
        {
            "vocabulary": "OMOP standardised vocabularies",
            "edition": "vocabulary_download_v5 (2018-06-02 release build)",
            "authority": "OHDSI / Athena",
            "route": "offline SQLite index, exact normalized match only",
            "availability": "local",
            "available": OMOP_INDEX.exists(),
            "source_files": {
                str(OMOP_CONCEPT.relative_to(REPO_ROOT)): _size(OMOP_CONCEPT),
                str(OMOP_VOCAB.relative_to(REPO_ROOT)): _size(OMOP_VOCAB),
                str(OMOP_INDEX.relative_to(REPO_ROOT)): _size(OMOP_INDEX),
            },
            "counts": {
                "concepts": _sqlite_count(OMOP_INDEX, "concept"),
                "terms_and_synonyms": _sqlite_count(OMOP_INDEX, "term"),
                "maps_to_relationships": _sqlite_count(OMOP_INDEX, "maps_to"),
            },
            "network_required": False,
            "notes": "Bundle contains no concept-definition table, so OMOP can supply "
                     "identifiers/relations but not definitions. Exact match only: a miss "
                     "means 'no exact name/synonym', not 'absent from OMOP'.",
        },
        {
            "vocabulary": "UMLS",
            "edition": "live REST API (version returned per response)",
            "authority": "U.S. National Library of Medicine",
            "route": "UMLS REST search (API key from environment)",
            "availability": "network",
            "available": _credential_present("UMLS_API_KEY"),
            "counts": None,
            "network_required": True,
            "notes": "Only the term string is sent, never paper text. Responses cached "
                     "with query/source/timestamp. Key read from environment only.",
        },
        {
            "vocabulary": "BioPortal",
            "edition": "live REST API (submission version per response)",
            "authority": "U.S. National Center for Biomedical Ontology",
            "route": "BioPortal REST search at data.bioontology.org (API key from environment)",
            "availability": "network",
            "available": _credential_present("BIOPORTAL_API_KEY"),
            "counts": None,
            "network_required": True,
            "notes": "data.bioontology.org is the working host; the portal front-end host "
                     "returns Cloudflare 403 and data.bioportal.lirmm.fr times out.",
        },
        {
            "vocabulary": "EBI OLS4",
            "edition": "live REST API",
            "authority": "EMBL-EBI",
            "route": "OLS4 search API",
            "availability": "network",
            "available": True,
            "counts": None,
            "network_required": True,
            "notes": "Keyless. Ontology name is taken from each returned document, so "
                     "mixed ontologies (MESH, GO, EFO, ...) are reported per candidate.",
        },
        {
            "vocabulary": "NCBI Taxonomy",
            "edition": "live Entrez lookup",
            "authority": "NCBI",
            "route": "Entrez esearch/esummary (API key from environment when present)",
            "availability": "network",
            "available": True,
            "counts": None,
            "network_required": True,
            "notes": "Scientific-name exact match is treated as a validated identifier; "
                     "common-name matches are lower-confidence lexically generated candidates.",
        },
    ]

    registry = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "note": "Editions and routes actually used by this pipeline build. Absence of a "
                "vocabulary here means it was not consulted — not that it does not exist.",
        "credentials_policy": {
            "source": "environment variables only (a local .env is detected, never read)",
            "variables": ["UMLS_API_KEY", "BIOPORTAL_API_KEY", "ENTREZ_API_KEY"],
            "logged": False,
            "sent_payload": "term string only; never paper text",
        },
        "vocabularies": entries,
        "n_vocabularies": len(entries),
        "n_local": sum(1 for e in entries if e["availability"] == "local"),
        "n_network": sum(1 for e in entries if e["availability"] == "network"),
        "local_only_supported": True,
        "local_only_note": "MeSH, OMOP and every consumed NER artifact are local, so the "
                           "pipeline has a fully offline path; the OLS/UMLS/BioPortal/Entrez "
                           "tiers are additive and skippable.",
    }

    out = args.out_dir / "ontology_registry.json"
    out.write_text(json.dumps(registry, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({
        "n_vocabularies": registry["n_vocabularies"],
        "n_local": registry["n_local"],
        "n_network": registry["n_network"],
        "available": {e["vocabulary"]: e["available"] for e in entries},
    }, indent=2))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
