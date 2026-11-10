#!/usr/bin/env python
"""
Fetch ALL available metadata for the 39 missing papers (not in data/papers_txt/)
from every source we have: NCBI BioProject, ENA Portal, PubMed (title search),
projects.csv, and sample_metadata.tsv.

Output:
  paper/_multi_ner_runs/cdm_output/missing_papers_metadata.json
  paper/_multi_ner_runs/cdm_output/missing_papers_metadata.tsv
"""

import csv
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Optional

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[2]
# Dataset paths (support CDM_SAMPLES_PAPER / CDM_PAPERS_TXT overrides). Imported
# via the repo root so this stays runnable as a standalone script.
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from cdm_pipeline import paths as _paths  # noqa: E402

PROJECTS_CSV = _paths.samples_paper_dir() / "projects.csv"
SAMPLE_METADATA = _paths.samples_paper_dir() / "sample_metadata.tsv"
PAPERS_DIR = _paths.papers_txt()
OUTPUT_DIR = PROJECT_ROOT / "paper" / "_multi_ner_runs" / "cdm_output"

EMAIL = os.environ.get("ENTREZ_EMAIL", "jkalra@uni-potsdam.de")


def get_missing_accessions() -> list[str]:
    """Return the 39 BioProject accessions in projects.csv but not in data/papers_txt/."""
    papers = {f.stem for f in PAPERS_DIR.glob("*.txt")}
    with open(PROJECTS_CSV, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        all_projects = {row["project"].strip() for row in reader}
    return sorted(all_projects - papers)


def load_projects_csv() -> dict[str, dict]:
    """Load projects.csv as {accession: row_dict}."""
    with open(PROJECTS_CSV, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        return {row["project"].strip(): row for row in reader}


def load_sample_metadata() -> dict[str, dict]:
    """Aggregate sample_metadata.tsv per project."""
    per_project: dict[str, dict] = {}
    with open(SAMPLE_METADATA, encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            acc = row.get("project", "").strip()
            if not acc:
                continue
            if acc not in per_project:
                per_project[acc] = {
                    "n_samples": 0,
                    "instruments": set(),
                    "geo_locs": set(),
                    "library_strategies": set(),
                    "pubdates": set(),
                    "total_bases": 0,
                }
            p = per_project[acc]
            p["n_samples"] += 1
            if row.get("instrument"):
                p["instruments"].add(row["instrument"])
            if row.get("geo_loc_name"):
                p["geo_locs"].add(row["geo_loc_name"])
            if row.get("library_strategy"):
                p["library_strategies"].add(row["library_strategy"])
            if row.get("pubdate"):
                p["pubdates"].add(row["pubdate"])
            try:
                p["total_bases"] += int(row.get("total_bases", 0))
            except ValueError:
                pass
    # Convert sets to sorted lists for JSON
    for acc, p in per_project.items():
        p["instruments"] = sorted(p["instruments"])
        p["geo_locs"] = sorted(p["geo_locs"])
        p["library_strategies"] = sorted(p["library_strategies"])
        p["pubdates"] = sorted(p["pubdates"])
    return per_project


def fetch_ncbi_bioproject(acc: str) -> dict:
    """Fetch BioProject record from NCBI E-utilities (raw XML)."""
    r = requests.get(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
        params={"db": "bioproject", "id": acc},
        timeout=30,
    )
    info = {"source": "ncbi_bioproject"}
    if r.status_code != 200 or "not public" in r.text:
        info["error"] = f"HTTP {r.status_code} or not public"
        return info
    try:
        root = ET.fromstring(r.text)
    except ET.ParseError:
        info["error"] = "XML parse error"
        return info

    for elem in root.iter():
        tag = elem.tag.split("}")[-1]
        if tag == "Title" and "title" not in info:
            info["title"] = (elem.text or "").strip()
        elif tag == "Description" and "description" not in info:
            info["description"] = (elem.text or "").strip()
        elif tag == "OrganismName" and "organism" not in info:
            info["organism"] = (elem.text or "").strip()
        elif tag == "Name" and "submitting_center" not in info:
            info["submitting_center"] = (elem.text or "").strip()
        elif tag == "DataType" and "datatype" not in info:
            info["datatype"] = (elem.text or "").strip()
        elif tag == "ProjectID" and "bioproject_uid" not in info:
            pass  # internal NCBI UID
    # Clean HTML tags from description
    if "description" in info:
        info["description"] = re.sub(r"<[^>]+>", "", info["description"]).strip()
    if "title" in info:
        info["title"] = re.sub(r"<[^>]+>", "", info["title"]).strip()
    return info


def fetch_ena(acc: str) -> dict:
    """Fetch project metadata from ENA Portal API."""
    info = {"source": "ena"}
    # XML metadata
    r = requests.get(f"https://www.ebi.ac.uk/ena/browser/api/xml/{acc}", timeout=30)
    if r.status_code == 200 and r.text.strip():
        try:
            root = ET.fromstring(r.text)
            for elem in root.iter():
                tag = elem.tag.split("}")[-1]
                if tag == "TITLE" and "title" not in info:
                    info["title"] = (elem.text or "").strip()
                elif tag == "DESCRIPTION" and "description" not in info:
                    info["description"] = re.sub(r"<[^>]+>", "", (elem.text or "")).strip()
                elif tag == "NAME" and "name" not in info:
                    info["name"] = (elem.text or "").strip()
                elif tag == "SCIENTIFIC_NAME" and "organism" not in info:
                    info["organism"] = (elem.text or "").strip()
                elif tag == "TAXON_ID" and "taxon_id" not in info:
                    info["taxon_id"] = (elem.text or "").strip()
        except ET.ParseError:
            pass

    # Run-level stats
    r2 = requests.get(
        f"https://www.ebi.ac.uk/ena/portal/api/filereport?accession={acc}&result=read_run"
        "&fields=run_accession,library_strategy,library_source,instrument_model,read_count,base_count,scientific_name"
        "&format=json",
        timeout=30,
    )
    if r2.status_code == 200 and r2.text.strip():
        try:
            runs = r2.json()
            info["n_runs"] = len(runs)
            if runs:
                first = runs[0]
                info["instrument_model"] = first.get("instrument_model", "")
                info["library_strategy"] = first.get("library_strategy", "")
                info["library_source"] = first.get("library_source", "")
                info["scientific_name"] = first.get("scientific_name", "")
                total_reads = sum(int(r.get("read_count", 0) or 0) for r in runs)
                total_bases = sum(int(r.get("base_count", 0) or 0) for r in runs)
                info["total_reads"] = total_reads
                info["total_bases"] = total_bases
        except (json.JSONDecodeError, ValueError):
            pass
    return info


def search_pubmed_by_title(title: str) -> Optional[str]:
    """Search PubMed by title, return PMID if found."""
    if not title or len(title) < 10:
        return None
    clean = re.sub(r"<[^>]+>", "", title).strip()
    if len(clean) < 10:
        return None
    try:
        r = requests.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
            params={
                "db": "pubmed",
                "term": f"{clean[:200]}[Title]",
                "retmax": 1,
                "email": EMAIL,
            },
            timeout=30,
        )
        root = ET.fromstring(r.text)
        id_elem = root.find(".//Id")
        return id_elem.text if id_elem is not None else None
    except Exception:
        return None


def fetch_pubmed_record(pmid: str) -> dict:
    """Fetch full PubMed record (raw XML)."""
    info = {"source": "pubmed", "pmid": pmid}
    r = requests.get(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
        params={"db": "pubmed", "id": pmid, "rettype": "xml"},
        timeout=30,
    )
    if r.status_code != 200:
        info["error"] = f"HTTP {r.status_code}"
        return info
    try:
        root = ET.fromstring(r.text)
    except ET.ParseError:
        info["error"] = "XML parse error"
        return info

    authors = []
    mesh_terms = []
    mesh_tree_numbers = []
    keywords = []
    pub_types = []

    for elem in root.iter():
        tag = elem.tag.split("}")[-1]
        if tag == "ArticleTitle" and "title" not in info:
            info["title"] = (elem.text or "").strip()
        elif tag == "AbstractText" and "abstract" not in info:
            info["abstract"] = (elem.text or "").strip()
        elif tag == "Title" and "journal" not in info:
            info["journal"] = (elem.text or "").strip()
        elif tag == "Year" and "pub_year" not in info:
            info["pub_year"] = (elem.text or "").strip()
        elif tag == "Language" and "language" not in info:
            info["language"] = (elem.text or "").strip()
        elif tag == "LastName":
            authors.append((elem.text or "").strip())
        elif tag == "DescriptorName":
            mesh_terms.append((elem.text or "").strip())
        elif tag == "TreeNumber":
            mesh_tree_numbers.append((elem.text or "").strip())
        elif tag == "Keyword":
            keywords.append((elem.text or "").strip())
        elif tag == "PublicationType":
            pub_types.append((elem.text or "").strip())

    info["authors"] = authors
    info["n_authors"] = len(authors)
    info["mesh_terms"] = mesh_terms
    info["n_mesh"] = len(mesh_terms)
    info["mesh_tree_numbers"] = mesh_tree_numbers
    info["keywords"] = keywords
    info["publication_types"] = pub_types
    return info


def run():
    missing = get_missing_accessions()
    print(f"Missing papers (in compendium, not in data/papers_txt/): {len(missing)}")
    print()

    projects_csv = load_projects_csv()
    sample_meta = load_sample_metadata()

    results = {}
    for i, acc in enumerate(missing):
        print(f"[{i+1}/{len(missing)}] {acc}")
        record = {"bioproject_id": acc}

        # 1. projects.csv
        pcsv = projects_csv.get(acc, {})
        record["projects_csv"] = {
            "doi_link": pcsv.get("link", "").strip(),
            "amplicon": pcsv.get("amplicon", "").strip(),
            "avg_length": pcsv.get("avg_length", "").strip(),
            "bead_beating": pcsv.get("bead_beating", "").strip(),
            "kit": pcsv.get("kit", "").strip(),
            "sample_type": pcsv.get("sample_type", "").strip(),
            "condition": pcsv.get("condition", "").strip(),
            "subjects": pcsv.get("subjects", "").strip(),
            "notes": pcsv.get("notes", "").strip(),
        }
        print(f"  projects.csv: condition={record['projects_csv']['condition'][:50]}, "
              f"sample_type={record['projects_csv']['sample_type']}")

        # 2. sample_metadata.tsv
        sm = sample_meta.get(acc, {})
        record["sample_metadata"] = sm
        if sm:
            print(f"  sample_metadata: {sm['n_samples']} samples, "
                  f"instruments={sm['instruments'][:2]}, geo={sm['geo_locs'][:2]}")

        # 3. NCBI BioProject
        ncbi = fetch_ncbi_bioproject(acc)
        record["ncbi_bioproject"] = ncbi
        if ncbi.get("title"):
            print(f"  NCBI BioProject: {ncbi.get('title', '')[:60]}")
        elif ncbi.get("error"):
            print(f"  NCBI BioProject: {ncbi['error']}")

        # 4. ENA (if NCBI returned nothing)
        if not ncbi.get("title"):
            time.sleep(0.4)
            ena = fetch_ena(acc)
            record["ena"] = ena
            if ena.get("title"):
                print(f"  ENA: {ena['title'][:60]}, {ena.get('n_runs', 0)} runs")
            else:
                print(f"  ENA: no data")
        else:
            record["ena"] = None

        # 5. PubMed (search by title)
        title = ncbi.get("title", "") or (record.get("ena", {}) or {}).get("title", "")
        pmid = search_pubmed_by_title(title)
        time.sleep(0.4)
        if pmid:
            pubmed = fetch_pubmed_record(pmid)
            record["pubmed"] = pubmed
            print(f"  PubMed: PMID {pmid}, {pubmed.get('n_mesh', 0)} MeSH, "
                  f"{pubmed.get('n_authors', 0)} authors, {pubmed.get('journal', '')[:40]}")
        else:
            record["pubmed"] = None
            print(f"  PubMed: no match")

        results[acc] = record
        print()
        time.sleep(0.5)

    # Save JSON
    json_path = OUTPUT_DIR / "missing_papers_metadata.json"
    json_path.parent.mkdir(parents=True, exist_ok=True)
    with open(json_path, "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"JSON saved: {json_path}")

    # Save TSV summary
    tsv_path = OUTPUT_DIR / "missing_papers_metadata.tsv"
    tsv_fields = [
        "bioproject_id", "title", "description", "organism", "datatype",
        "condition", "sample_type", "amplicon", "kit", "bead_beating",
        "n_samples", "instruments", "geo_locs",
        "submitting_center", "library_strategy", "n_runs", "total_reads",
        "pmid", "journal", "pub_year", "n_authors", "n_mesh", "mesh_terms",
        "abstract",
    ]
    with open(tsv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=tsv_fields, extrasaction="ignore")
        writer.writeheader()
        for acc, rec in sorted(results.items()):
            row = {"bioproject_id": acc}
            ncbi = rec.get("ncbi_bioproject", {})
            ena = rec.get("ena") or {}
            pubmed = rec.get("pubmed") or {}
            pcsv = rec.get("projects_csv", {})
            sm = rec.get("sample_metadata", {})

            row["title"] = ncbi.get("title", "") or ena.get("title", "")
            row["description"] = ncbi.get("description", "") or ena.get("description", "")
            row["organism"] = ncbi.get("organism", "") or ena.get("organism", "")
            row["datatype"] = ncbi.get("datatype", "") or ena.get("library_strategy", "")
            row["condition"] = pcsv.get("condition", "")
            row["sample_type"] = pcsv.get("sample_type", "")
            row["amplicon"] = pcsv.get("amplicon", "")
            row["kit"] = pcsv.get("kit", "")
            row["bead_beating"] = pcsv.get("bead_beating", "")
            row["n_samples"] = sm.get("n_samples", "")
            row["instruments"] = "; ".join(sm.get("instruments", []))
            row["geo_locs"] = "; ".join(sm.get("geo_locs", []))
            row["submitting_center"] = ncbi.get("submitting_center", "") or ena.get("name", "")
            row["library_strategy"] = ena.get("library_strategy", "")
            row["n_runs"] = ena.get("n_runs", "")
            row["total_reads"] = ena.get("total_reads", "")
            row["pmid"] = pubmed.get("pmid", "")
            row["journal"] = pubmed.get("journal", "")
            row["pub_year"] = pubmed.get("pub_year", "")
            row["n_authors"] = pubmed.get("n_authors", "")
            row["n_mesh"] = pubmed.get("n_mesh", "")
            row["mesh_terms"] = "; ".join(pubmed.get("mesh_terms", []))
            row["abstract"] = pubmed.get("abstract", "")[:200]
            writer.writerow(row)
    print(f"TSV saved:  {tsv_path}")

    # Summary
    n_with_title = sum(1 for r in results.values()
                       if r.get("ncbi_bioproject", {}).get("title") or (r.get("ena") or {}).get("title"))
    n_with_desc = sum(1 for r in results.values()
                      if r.get("ncbi_bioproject", {}).get("description") or (r.get("ena") or {}).get("description"))
    n_with_pmid = sum(1 for r in results.values() if r.get("pubmed"))
    n_with_mesh = sum(1 for r in results.values() if r.get("pubmed", {}) and r["pubmed"].get("n_mesh", 0) > 0)
    n_with_samples = sum(1 for r in results.values() if r.get("sample_metadata", {}).get("n_samples", 0) > 0)
    total_mesh = sum(r.get("pubmed", {}).get("n_mesh", 0) for r in results.values() if r.get("pubmed"))
    total_samples = sum(r.get("sample_metadata", {}).get("n_samples", 0) for r in results.values())

    print()
    print("=" * 60)
    print("Missing Papers Metadata Summary")
    print("=" * 60)
    print(f"Total missing papers:     {len(missing)}")
    print(f"  with title/desc:        {n_with_title} ({n_with_title/len(missing)*100:.0f}%)")
    print(f"  with description:       {n_with_desc} ({n_with_desc/len(missing)*100:.0f}%)")
    print(f"  with PMID:              {n_with_pmid} ({n_with_pmid/len(missing)*100:.0f}%)")
    print(f"  with MeSH:              {n_with_mesh}")
    print(f"  total MeSH terms:       {total_mesh}")
    print(f"  with sample metadata:   {n_with_samples}")
    print(f"  total samples:          {total_samples:,}")


if __name__ == "__main__":
    run()
