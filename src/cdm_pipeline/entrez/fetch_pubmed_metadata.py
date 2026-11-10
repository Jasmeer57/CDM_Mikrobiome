#!/usr/bin/env python
"""
Fetch publication metadata (PMID, MeSH terms, authors, journal, abstract, etc.)
for all papers in the compendium via DOI -> PubMed (NCBI E-utilities).

Extracts ALL available PubMed XML fields:
  - Structured abstract (with section labels)
  - MeSH descriptors (UI, MajorTopicYN, qualifiers w/ UI)
  - Chemicals (name, UI, registry number)
  - Author details (full name, ORCID, affiliations, collective names)
  - Grants (ID, agency, country, acronym)
  - Article IDs (DOI, PMC, PMID, PII, etc.)
  - Publication types, keywords (with type)
  - Journal (full title, ISO abbrev, ISSN print/electronic, NLM ID, volume, issue, pages)
  - Publication dates (received, accepted, epublish, ppublish, etc.)
  - References (citation + PMID/DOI when available)
  - Conflict of interest statement
  - Copyright information
  - Data bank accession numbers (GEO, SRA, etc.)
  - Language, publication status, citation subset

Output:
  - paper/_multi_ner_runs/cdm_output/pubmed_metadata.json   (full records)
  - paper/_multi_ner_runs/cdm_output/pubmed_metadata.tsv     (flat summary)

Usage:
  python -m cdm_pipeline.entrez.fetch_pubmed_metadata [--max N] [--delay 0.35]
"""

import argparse
import csv
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
# Dataset paths (support CDM_SAMPLES_PAPER / CDM_PAPERS_TXT overrides). Imported
# via the repo root so this stays runnable as a standalone script.
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from cdm_pipeline import paths as _paths  # noqa: E402

PROJECTS_CSV = _paths.samples_paper_dir() / "projects.csv"
PAPERS_DIR = _paths.papers_txt()
OUTPUT_DIR = PROJECT_ROOT / "paper" / "_multi_ner_runs" / "cdm_output"

ENTREZ_EMAIL = os.environ.get("ENTREZ_EMAIL", "jkalra@uni-potsdam.de")
ENTREZ_API_KEY = os.environ.get("ENTREZ_API_KEY", "")


# ---------------------------------------------------------------------------
# Input loading
# ---------------------------------------------------------------------------

def load_projects() -> List[dict]:
    with open(PROJECTS_CSV, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def get_papers_with_dois() -> Dict[str, Optional[str]]:
    papers = {txt.stem: None for txt in sorted(PAPERS_DIR.glob("*.txt"))}
    for row in load_projects():
        acc = (row.get("project") or "").strip()
        doi = (row.get("link") or "").strip()
        if doi:
            doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi)
        if acc in papers:
            papers[acc] = doi or None
    return papers


# ---------------------------------------------------------------------------
# PubMed API calls
# ---------------------------------------------------------------------------

def _eutils_params(extra: dict) -> dict:
    params = {"email": ENTREZ_EMAIL, "tool": "microbiome-cdm"}
    if ENTREZ_API_KEY:
        params["api_key"] = ENTREZ_API_KEY
    params.update(extra)
    return params


def doi_to_pmid(doi: str) -> Optional[str]:
    doi = doi.strip()
    if not doi:
        return None
    try:
        r = requests.get(f"{EUTILS}/esearch.fcgi", params=_eutils_params({
            "db": "pubmed", "term": f"{doi}[DOI]", "retmax": 1,
        }), timeout=30)
        root = ET.fromstring(r.text)
        id_elem = root.find(".//Id")
        return id_elem.text if id_elem is not None else None
    except Exception:
        return None


def fetch_pubmed_record(pmid: str) -> Optional[dict]:
    try:
        r = requests.get(f"{EUTILS}/efetch.fcgi", params=_eutils_params({
            "db": "pubmed", "id": pmid, "rettype": "xml",
        }), timeout=60)
        return parse_pubmed_xml(r.text, pmid)
    except Exception as e:
        print(f"  PubMed fetch error for PMID {pmid}: {e}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# XML parsing helpers
# ---------------------------------------------------------------------------

def _text(elem) -> str:
    """Return stripped text of an element, joining sub-elements for italic/bold."""
    if elem is None:
        return ""
    parts = []
    if elem.text:
        parts.append(elem.text)
    for child in elem:
        if child.text:
            parts.append(child.text)
        if child.tail:
            parts.append(child.tail)
    return "".join(parts).strip()


def _findtext(parent, tag, default="") -> str:
    elem = parent.find(tag) if parent is not None else None
    return _text(elem) if elem is not None else default


def _date_dict(parent: ET.Element, date_tag: str) -> dict:
    """Extract Year/Month/Day/Hour/Minute from a <PubDate> or <PubMedPubDate> element."""
    elem = parent.find(date_tag) if parent is not None else None
    if elem is None:
        return {}
    return {
        "year": _findtext(elem, "Year"),
        "month": _findtext(elem, "Month"),
        "day": _findtext(elem, "Day"),
        "hour": _findtext(elem, "Hour"),
        "minute": _findtext(elem, "Minute"),
    }


# ---------------------------------------------------------------------------
# Core parser — extracts everything PubMed gives us
# ---------------------------------------------------------------------------

def parse_pubmed_xml(xml_text: str, pmid: str) -> Optional[dict]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None

    article = root.find(".//PubmedArticle")
    if article is None:
        article = root.find(".//PubmedBookArticle")
    if article is None:
        return {"pmid": pmid}

    rec: dict = {"pmid": pmid}

    # ---- Article IDs (DOI, PMC, PMID, PII, etc.) ----
    # NOTE: only PubmedData/ArticleIdList carries the paper's own IDs —
    # a whole-document iter() would also pick up ReferenceList ArticleIds.
    article_ids = {}
    id_list = article.find(".//PubmedData/ArticleIdList")
    if id_list is not None:
        for aid in id_list.findall("ArticleId"):
            id_type = aid.attrib.get("IdType", "")
            val = (aid.text or "").strip()
            if id_type and val and id_type not in article_ids:
                article_ids[id_type] = val
    rec["article_ids"] = article_ids
    rec["doi"] = article_ids.get("doi", "")
    rec["pmc_id"] = article_ids.get("pmc", "")
    rec["pii"] = article_ids.get("pii", "")

    # ---- Article title ----
    title_elem = article.find(".//ArticleTitle")
    rec["title"] = _text(title_elem)

    # ---- Abstract (structured — preserve section labels) ----
    abstract_parts = []
    abstract_plain_parts = []
    for ab in article.iter("AbstractText"):
        label = ab.attrib.get("Label", "")
        text = _text(ab)
        if label:
            abstract_parts.append({"label": label, "text": text})
            abstract_plain_parts.append(f"{label}: {text}")
        else:
            abstract_parts.append({"label": "", "text": text})
            abstract_plain_parts.append(text)
    rec["abstract_structured"] = abstract_parts
    rec["abstract"] = "\n".join(abstract_plain_parts)
    rec["n_abstract_sections"] = len(abstract_parts)

    # ---- Language ----
    langs = [_text(e) for e in article.iter("Language")]
    rec["language"] = langs[0] if langs else ""
    rec["languages"] = langs

    # ---- Publication types ----
    pub_types = [_text(e) for e in article.iter("PublicationType")]
    rec["publication_types"] = pub_types

    # ---- Authors (full detail) ----
    authors = []
    for au in article.iter("Author"):
        author = {}
        ln = _findtext(au, "LastName")
        fn = _findtext(au, "ForeName")
        initials = _findtext(au, "Initials")
        suffix = _findtext(au, "Suffix")
        collective = _findtext(au, "CollectiveName")

        if collective:
            author["name"] = collective
            author["collective"] = True
        else:
            parts = [p for p in [fn, ln] if p]
            author["name"] = " ".join(parts) if parts else (ln or collective or "")
            author["last_name"] = ln
            author["fore_name"] = fn
            author["initials"] = initials
            author["suffix"] = suffix

        # ORCID and other identifiers
        idents = {}
        for ident in au.iter("Identifier"):
            src = ident.attrib.get("Source", "")
            idents[src] = (ident.text or "").strip()
        author["identifiers"] = idents
        author["orcid"] = idents.get("ORCID", "")

        # Affiliations
        affs = []
        for aff_info in au.iter("AffiliationInfo"):
            aff_text = _findtext(aff_info, "Affiliation")
            if aff_text:
                affs.append(aff_text)
        # Also check direct Affiliation (some records)
        for aff in au.findall("Affiliation"):
            t = _text(aff)
            if t and t not in affs:
                affs.append(t)
        author["affiliations"] = affs

        # Equal contribution flag
        eq = au.find("EqualContrib")
        author["equal_contribution"] = eq is not None

        authors.append(author)

    rec["authors"] = authors
    rec["n_authors"] = len(authors)
    rec["author_names"] = [a.get("name", "") for a in authors]
    rec["author_orcids"] = [a["orcid"] for a in authors if a.get("orcid")]
    rec["author_affiliations"] = [aff for a in authors for aff in a.get("affiliations", [])]

    # ---- MeSH headings (full detail: UI, MajorTopicYN, qualifiers) ----
    mesh_headings = []
    for mh in article.iter("MeshHeading"):
        desc = mh.find("DescriptorName")
        if desc is None:
            continue
        heading = {
            "descriptor": _text(desc),
            "ui": desc.attrib.get("UI", ""),
            "major_topic": desc.attrib.get("MajorTopicYN", "N") == "Y",
            "qualifiers": [],
        }
        for q in mh.findall("QualifierName"):
            heading["qualifiers"].append({
                "name": _text(q),
                "ui": q.attrib.get("UI", ""),
                "major_topic": q.attrib.get("MajorTopicYN", "N") == "Y",
            })
        mesh_headings.append(heading)
    rec["mesh_headings"] = mesh_headings
    rec["mesh_terms"] = [h["descriptor"] for h in mesh_headings]
    rec["n_mesh"] = len(mesh_headings)
    rec["mesh_major_topics"] = [h["descriptor"] for h in mesh_headings if h["major_topic"]]
    rec["mesh_qualifiers"] = [
        f'{h["descriptor"]}/{q["name"]}'
        for h in mesh_headings
        for q in h["qualifiers"]
    ]

    # ---- Chemicals / substances ----
    chemicals = []
    for chem in article.iter("Chemical"):
        name_elem = chem.find("NameOfSubstance")
        reg_elem = chem.find("RegistryNumber")
        chemicals.append({
            "name": _text(name_elem),
            "ui": name_elem.attrib.get("UI", "") if name_elem is not None else "",
            "registry_number": _text(reg_elem),
        })
    rec["chemicals"] = chemicals
    rec["chemical_names"] = [c["name"] for c in chemicals if c["name"]]

    # ---- Keywords (with type) ----
    keywords = []
    for kw in article.iter("Keyword"):
        keywords.append({
            "keyword": _text(kw),
            "type": kw.attrib.get("MajorTopicYN", ""),
        })
    rec["keywords"] = [k["keyword"] for k in keywords]
    rec["keyword_details"] = keywords

    # ---- Grants ----
    grants = []
    for g in article.iter("Grant"):
        grants.append({
            "id": _findtext(g, "GrantID"),
            "agency": _findtext(g, "Agency"),
            "country": _findtext(g, "Country"),
            "acronym": _findtext(g, "Acronym"),
        })
    rec["grants"] = grants
    rec["grant_ids"] = [g["id"] for g in grants if g["id"]]

    # ---- Journal info ----
    journal_elem = article.find(".//Journal")
    if journal_elem is not None:
        rec["journal"] = _findtext(journal_elem, "Title")
        rec["journal_iso_abbrev"] = _findtext(journal_elem, "ISOAbbreviation")
        rec["journal_nlm_id"] = ""
        rec["volume"] = _findtext(journal_elem, "JournalIssue/Volume")
        rec["issue"] = _findtext(journal_elem, "JournalIssue/Issue")

        # ISSN (print + electronic)
        issns = {}
        for issn in journal_elem.iter("ISSN"):
            issn_type = issn.attrib.get("IssnType", "print")
            issns[issn_type] = (issn.text or "").strip()
        rec["issn"] = issns
        rec["issn_print"] = issns.get("Print", issns.get("print", ""))
        rec["issn_electronic"] = issns.get("Electronic", issns.get("electronic", ""))

        # ISSNLinking
        rec["issn_linking"] = ""
        for il in journal_elem.iter("ISSNLinking"):
            rec["issn_linking"] = (il.text or "").strip()
            break

        # Publication date
        pub_date = journal_elem.find(".//PubDate")
        if pub_date is not None:
            rec["pub_year"] = _findtext(pub_date, "Year")
            rec["pub_month"] = _findtext(pub_date, "Month")
            rec["pub_day"] = _findtext(pub_date, "Day")
            # Some use MedlineDate for date ranges
            if not rec["pub_year"]:
                medline_date = _text(pub_date.find("MedlineDate"))
                rec["pub_year"] = medline_date[:4] if len(medline_date) >= 4 else ""

    # MedlineJournalInfo (NLM unique ID, country, medline TA)
    mji = article.find(".//MedlineJournalInfo")
    if mji is not None:
        rec["journal_nlm_id"] = _findtext(mji, "NlmUniqueID")
        rec["journal_country"] = _findtext(mji, "Country")
        rec["medline_ta"] = _findtext(mji, "MedlineTA")

    # ---- Pagination ----
    rec["pages"] = _findtext(article, ".//MedlinePgn")
    if not rec["pages"]:
        rec["pages"] = _findtext(article, ".//Pagination/StartPage")

    # ---- Copyright ----
    rec["copyright"] = _findtext(article, ".//CopyrightInformation")

    # ---- Conflict of Interest ----
    coi = article.find(".//CoiStatement")
    rec["coi_statement"] = _text(coi) if coi is not None else ""

    # ---- Publication status & history dates ----
    pubmed_data = article.find(".//PubmedData")
    if pubmed_data is not None:
        rec["publication_status"] = _findtext(pubmed_data, "PublicationStatus")

        # History dates
        history = {}
        for pd in pubmed_data.iter("PubMedPubDate"):
            status = pd.attrib.get("PubStatus", "")
            history[status] = {
                "year": _findtext(pd, "Year"),
                "month": _findtext(pd, "Month"),
                "day": _findtext(pd, "Day"),
            }
        rec["history_dates"] = history
        if "received" in history:
            rec["date_received"] = history["received"]
        if "accepted" in history:
            rec["date_accepted"] = history["accepted"]
        if "epublish" in history:
            rec["date_epublish"] = history["epublish"]
        if "ppublish" in history:
            rec["date_ppublish"] = history["ppublish"]
        if "pmc-release" in history:
            rec["date_pmc_release"] = history["pmc-release"]

    # ArticleDate (electronic publication)
    for ad in article.iter("ArticleDate"):
        date_type = ad.attrib.get("DateType", "")
        rec["article_date_type"] = date_type
        rec["article_date"] = {
            "year": _findtext(ad, "Year"),
            "month": _findtext(ad, "Month"),
            "day": _findtext(ad, "Day"),
        }

    # ---- Citation subset ----
    subsets = [_text(e) for e in article.iter("CitationSubset")]
    rec["citation_subsets"] = subsets

    # ---- ELocationID (DOI from article body, if any) ----
    for el in article.iter("ELocationID"):
        if el.attrib.get("EIdType") == "doi" and not rec.get("doi"):
            rec["doi"] = (el.text or "").strip()

    # ---- Data banks (GEO, etc.) ----
    data_banks = []
    for db in article.iter("DataBank"):
        bank = {
            "name": _findtext(db, "DataBankName"),
            "accessions": [_text(a) for a in db.iter("AccessionNumber")],
        }
        data_banks.append(bank)
    rec["data_banks"] = data_banks

    # ---- References (if present) ----
    references = []
    for ref in article.iter("Reference"):
        citation = _findtext(ref, "Citation")
        ref_ids = {}
        for aid in ref.iter("ArticleId"):
            id_type = aid.attrib.get("IdType", "")
            ref_ids[id_type] = (aid.text or "").strip()
        references.append({
            "citation": citation,
            "ids": ref_ids,
        })
    rec["references"] = references
    rec["n_references"] = len(references)
    rec["reference_pmids"] = [
        r["ids"].get("pubmed", "")
        for r in references
        if r["ids"].get("pubmed")
    ]

    return rec


# ---------------------------------------------------------------------------
# Main run loop
# ---------------------------------------------------------------------------

def run(max_papers: int = 0, delay: float = 0.35, resume: bool = True):
    papers = get_papers_with_dois()
    print(f"Total papers in data/papers_txt/: {len(papers)}")
    n_with_doi = sum(1 for v in papers.values() if v)
    n_without_doi = len(papers) - n_with_doi
    print(f"  with DOI:  {n_with_doi}")
    print(f"  no DOI:   {n_without_doi}")
    print()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = OUTPUT_DIR / "pubmed_metadata.json"
    tsv_path = OUTPUT_DIR / "pubmed_metadata.tsv"

    existing = {}
    if resume and json_path.exists():
        with open(json_path) as f:
            existing = json.load(f)
        print(f"Resuming: {len(existing)} records already fetched")

    results = dict(existing)
    to_process = [(acc, doi) for acc, doi in papers.items() if acc not in results]
    if max_papers > 0:
        to_process = to_process[:max_papers]

    print(f"To process: {len(to_process)}")
    print()

    n_found = 0
    n_not_found = 0
    n_error = 0

    for i, (acc, doi) in enumerate(to_process):
        if not doi:
            results[acc] = {"bioproject_id": acc, "pmid": None, "doi": None, "error": "no_doi"}
            n_not_found += 1
            if (i + 1) % 50 == 0:
                print(f"  [{i+1}/{len(to_process)}] {acc}: no DOI, skipping")
            continue

        pmid = doi_to_pmid(doi)
        time.sleep(delay)

        if not pmid:
            results[acc] = {"bioproject_id": acc, "pmid": None, "doi": doi, "error": "no_pmid"}
            n_not_found += 1
            if (i + 1) % 50 == 0:
                print(f"  [{i+1}/{len(to_process)}] {acc}: DOI {doi} -> no PMID")
            continue

        rec = fetch_pubmed_record(pmid)
        time.sleep(delay)

        if rec:
            rec["bioproject_id"] = acc
            if not rec.get("doi"):
                rec["doi"] = doi
            results[acc] = rec
            n_found += 1
            n_mesh = rec.get("n_mesh", 0)
            n_chem = len(rec.get("chemical_names", []))
            n_refs = rec.get("n_references", 0)
            n_orcid = len(rec.get("author_orcids", []))
            if (i + 1) % 25 == 0 or i < 5:
                print(f"  [{i+1}/{len(to_process)}] {acc}: PMID {pmid}, "
                      f"MeSH={n_mesh}, chem={n_chem}, refs={n_refs}, "
                      f"ORCIDs={n_orcid}, {rec.get('journal','')[:40]}")
        else:
            results[acc] = {"bioproject_id": acc, "pmid": pmid, "doi": doi, "error": "fetch_failed"}
            n_error += 1
            print(f"  [{i+1}/{len(to_process)}] {acc}: PMID {pmid} -> fetch error")

        if (i + 1) % 50 == 0:
            with open(json_path, "w") as f:
                json.dump(results, f, indent=2, ensure_ascii=False)
            print(f"    Checkpoint saved ({len(results)} records)")

    # Final save
    with open(json_path, "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    # TSV summary
    tsv_fields = [
        "bioproject_id", "pmid", "doi", "pmc_id", "pii",
        "title", "journal", "journal_iso_abbrev", "pub_year", "pub_month",
        "volume", "issue", "pages",
        "n_authors", "n_orcids", "n_affiliations",
        "n_mesh", "n_mesh_major", "n_chemicals", "n_keywords",
        "n_references", "n_data_banks",
        "language", "publication_status",
        "coi_statement", "copyright",
        "issn_print", "issn_electronic", "journal_nlm_id", "journal_country",
        "error",
    ]
    with open(tsv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=tsv_fields, extrasaction="ignore")
        writer.writeheader()
        for acc, rec in sorted(results.items()):
            row = {k: rec.get(k, "") for k in tsv_fields}
            row["n_orcids"] = len(rec.get("author_orcids", []))
            row["n_affiliations"] = len(rec.get("author_affiliations", []))
            row["n_mesh_major"] = len(rec.get("mesh_major_topics", []))
            row["n_chemicals"] = len(rec.get("chemical_names", []))
            row["n_keywords"] = len(rec.get("keywords", []))
            row["n_data_banks"] = len(rec.get("data_banks", []))
            writer.writerow(row)

    # Summary
    total = len(results)
    n_with_pmid = sum(1 for r in results.values() if r.get("pmid"))
    n_with_mesh = sum(1 for r in results.values() if r.get("n_mesh", 0) > 0)
    n_with_chem = sum(1 for r in results.values() if len(r.get("chemical_names", [])) > 0)
    n_with_refs = sum(1 for r in results.values() if r.get("n_references", 0) > 0)
    n_with_orcid = sum(1 for r in results.values() if len(r.get("author_orcids", [])) > 0)
    n_with_coi = sum(1 for r in results.values() if r.get("coi_statement"))
    n_with_structured = sum(1 for r in results.values() if r.get("n_abstract_sections", 0) > 1)
    total_mesh = sum(r.get("n_mesh", 0) for r in results.values())
    total_chem = sum(len(r.get("chemical_names", [])) for r in results.values())
    total_refs = sum(r.get("n_references", 0) for r in results.values())
    total_authors = sum(r.get("n_authors", 0) for r in results.values())
    total_orcids = sum(len(r.get("author_orcids", [])) for r in results.values())

    print()
    print("=" * 70)
    print("PubMed Metadata Fetch Summary (Enriched)")
    print("=" * 70)
    print(f"Total papers:              {total}")
    print(f"  with PMID:               {n_with_pmid} ({n_with_pmid/total*100:.1f}%)")
    print(f"  with MeSH:               {n_with_mesh} ({n_with_mesh/total*100:.1f}%)")
    print(f"  with chemicals:          {n_with_chem} ({n_with_chem/total*100:.1f}%)")
    print(f"  with references:         {n_with_refs} ({n_with_refs/total*100:.1f}%)")
    print(f"  with ORCID authors:      {n_with_orcid} ({n_with_orcid/total*100:.1f}%)")
    print(f"  with COI statement:      {n_with_coi} ({n_with_coi/total*100:.1f}%)")
    print(f"  structured abstract:     {n_with_structured} ({n_with_structured/total*100:.1f}%)")
    print(f"  no DOI:                  {n_not_found}")
    print(f"  errors:                  {n_error}")
    print(f"Totals:")
    print(f"  MeSH headings:           {total_mesh}")
    print(f"  Chemicals:               {total_chem}")
    print(f"  References:              {total_refs}")
    print(f"  Author mentions:         {total_authors}")
    print(f"  ORCID IDs:               {total_orcids}")
    print(f"JSON: {json_path}")
    print(f"TSV:  {tsv_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch PubMed metadata via DOI")
    parser.add_argument("--max", type=int, default=0, help="Max papers (0 = all)")
    parser.add_argument("--delay", type=float, default=0.35, help="Delay between calls")
    parser.add_argument("--no-resume", action="store_true", help="Don't resume")
    args = parser.parse_args()
    run(max_papers=args.max, delay=args.delay, resume=not args.no_resume)
