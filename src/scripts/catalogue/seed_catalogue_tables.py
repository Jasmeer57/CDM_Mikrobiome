#!/usr/bin/env python
"""Stage 4: seed the data-catalogue Papers table (453 papers).

Reads:   data/corpus/records/HMPAPER_*.json          (A–I record schema)
         data/corpus/corpus_tracking.csv             (state machine, post-backfill)
Writes:  data/catalogue/tables/papers.csv            (template column set)
         data/catalogue/tables/datasets.csv          (seeded 1 row/paper from BioProject accession)
         data/catalogue/tables/dataassets.csv         (landing-page asset per dataset)

Papers get every template column; blanks follow template missing-data
conventions (blank = not yet extracted). Datasets are AUTO_SEEDED: one row per
paper carrying a BioProject accession, repository assumed NCBI, access status
left for verification, verification_status=UNVERIFIED.
"""

from __future__ import annotations

import csv
import json
import time
from pathlib import Path

PROJECT_ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
REPO_ROOT = PROJECT_ROOT
while not (REPO_ROOT / "data" / "corpus").exists() and REPO_ROOT != REPO_ROOT.parent:
    REPO_ROOT = REPO_ROOT.parent
PROJECT_ROOT = REPO_ROOT

RECORDS = PROJECT_ROOT / "data" / "corpus" / "records"
TRACKING = PROJECT_ROOT / "data" / "corpus" / "corpus_tracking.csv"
OUT = PROJECT_ROOT / "data" / "catalogue" / "tables"
PAPERS_CSV = OUT / "papers.csv"
DATASETS_CSV = OUT / "datasets.csv"
ASSETS_CSV = OUT / "dataassets.csv"

PAPER_FIELDS = [
    "paper_id", "doi", "pmid", "pmcid", "title", "authors", "journal",
    "publication_year", "article_type", "abstract", "keywords", "language",
    "full_text_source", "full_text_url", "full_text_format", "license_name",
    "license_url", "retrieved_at", "primary_research_domain",
    "human_microbiome_relevance", "human_study_design", "inclusion_decision",
    "exclusion_reason", "full_text_completeness", "curation_status",
    "curator_notes",
]
DATASET_FIELDS = [
    "dataset_id", "paper_id", "dataset_title", "dataset_description",
    "dataset_role", "dataset_type", "repository_name", "repository_accession",
    "accession_type", "dataset_url", "related_publication_dois",
    "data_availability_status", "access_conditions", "license_or_terms",
    "original_or_reused", "data_dictionary_url", "study_registration",
    "evidence_text", "evidence_location", "verification_status",
    "last_verified", "catalogue_notes",
]
ASSET_FIELDS = [
    "asset_id", "dataset_id", "asset_name", "asset_type", "format",
    "description", "repository_url", "accession", "file_size_bytes",
    "checksum_type", "checksum", "access_status", "license_or_terms",
    "data_dictionary_url", "notes",
]


def s(v) -> str:
    if isinstance(v, list):
        return "|".join(str(x) for x in v if x)
    return str(v or "").strip()


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    tracking = {}
    with TRACKING.open(encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            tracking[r["corpus_id"]] = r

    papers, datasets, assets = [], [], []
    ds_n = as_n = 0
    for i in range(1, 454):
        cid = f"HMPAPER_{i:06d}"
        rec = json.loads((RECORDS / f"{cid}.json").read_text())
        b = rec.get("B_publication_metadata") or {}
        a = rec.get("A_record_control", {})
        files = rec.get("files") or {}
        tr = tracking.get(cid, {})

        fts_map = {
            "complete": "FULL", "partial": "PARTIAL", "abstract_only": "ABSTRACT_ONLY",
        }
        inc_map = {"included": "INCLUDE", "excluded": "EXCLUDE", "pending": "PENDING"}

        papers.append({
            "paper_id": cid,
            "doi": s(b.get("doi")),
            "pmid": s(b.get("pmid")),
            "pmcid": s(b.get("pmcid")),
            "title": s(b.get("title")),
            "authors": s(b.get("authors")),
            "journal": s(b.get("journal")),
            "publication_year": s(b.get("publication_year")),
            "article_type": s(b.get("publication_type")),
            "abstract": s(b.get("abstract")),
            "keywords": s(b.get("keywords")),
            "language": s(b.get("language")) or "eng",
            "full_text_source": "corpus_builder/papers_txt",
            "full_text_url": "",
            "full_text_format": "text",
            "license_name": "",
            "license_url": "",
            "retrieved_at": s(files.get("retrieved_at")),
            "primary_research_domain": s(b.get("study_type_reported")),
            "human_microbiome_relevance": "DIRECT",
            "human_study_design": "",
            "inclusion_decision": inc_map.get(s(tr.get("inclusion_decision")).lower(),
                                              s(tr.get("inclusion_decision")) or None),
            "exclusion_reason": "",
            "full_text_completeness": fts_map.get(s(tr.get("full_text_status")).lower(),
                                                 "UNKNOWN"),
            "curation_status": "AUTO_SEEDED",
            "curator_notes": s(a.get("notes")),
        })

        # dataset seed rows: one BioProject per paper carrying one
        accs = []
        acc = s(rec.get("bioproject_accession"))
        if acc.startswith("PRJ"):
            accs = [acc]
        d = rec.get("D_data_availability") or {}
        if not accs:
            declared = d.get("declared_accessions") or d.get("accessions") or []
            accs = [x for x in (declared if isinstance(declared, list) else [declared])
                    if s(x).startswith("PRJ")]
        for acc in accs:
            ds_n += 1
            did = f"HMDATA_{ds_n:06d}"
            datasets.append({
                "dataset_id": did,
                "paper_id": cid,
                "dataset_title": f"Primary sequencing data for {cid} ({acc})",
                "dataset_description": s(d.get("availability_statement")) or
                "Auto-seeded from corpus record bioproject_accession; verify repository and access.",
                "dataset_role": "primary_study_data",
                "dataset_type": "",
                "repository_name": ("NCBI BioProject" if acc.startswith("PRJNA")
                                    else "DDBJ BioProject" if acc.startswith("PRJD")
                                    else "EBI/ENA BioProject" if acc.startswith("PRJE")
                                    else "Unknown repository"),
                "repository_accession": acc,
                "accession_type": "bioproject",
                "dataset_url": f"https://www.ncbi.nlm.nih.gov/bioproject/{acc}",
                "related_publication_dois": s(b.get("doi")),
                "data_availability_status": "",
                "access_conditions": "",
                "license_or_terms": "",
                "original_or_reused": "ORIGINAL",
                "data_dictionary_url": "",
                "study_registration": "",
                "evidence_text": "",
                "evidence_location": "",
                "verification_status": "UNVERIFIED",
                "last_verified": "",
                "catalogue_notes": ["AUTO_SEEDED"],
            })
            as_n += 1
            assets.append({
                "asset_id": f"HMASSET_{as_n:06d}",
                "dataset_id": did,
                "asset_name": f"{acc} repository landing page",
                "asset_type": "repository_landing_page",
                "format": "html",
                "description": "",
                "repository_url": f"https://www.ncbi.nlm.nih.gov/bioproject/{acc}",
                "accession": acc,
                "file_size_bytes": "",
                "checksum_type": "",
                "checksum": "",
                "access_status": "UNKNOWN",
                "license_or_terms": "",
                "data_dictionary_url": "",
                "notes": ["AUTO_SEEDED"],
            })

    for path, fields, rows in ((PAPERS_CSV, PAPER_FIELDS, papers),
                               (DATASETS_CSV, DATASET_FIELDS, datasets),
                               (ASSETS_CSV, ASSET_FIELDS, assets)):
        with path.open("w", newline="", encoding="utf-8-sig") as fh:
            w = csv.DictWriter(fh, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)
        print(f"wrote {len(rows):4d} rows -> {path.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
