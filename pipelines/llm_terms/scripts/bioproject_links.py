"""Try NCBI BioProject database for linked publications for the last 2."""
import time
from pathlib import Path
import requests
import xml.etree.ElementTree as ET

UA = "Mozilla/5.0"
OUT = Path(r"C:\Users\jkalra\Documents\Microbiome-CDM\pdfs")

def is_xml(b):
    return b[:5] == b"<?xml" or b[:1] == b"<"

def save(path, content):
    with open(path, "wb") as f:
        f.write(content)

def get_bioproject_links(accession):
    """Get publication links from NCBI BioProject database."""
    try:
        # Search BioProject DB
        r = requests.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
                         params={"db": "bioproject", "term": accession, "retmode": "json"},
                         timeout=30, headers={"User-Agent": UA})
        if r.status_code != 200:
            return []
        ids = r.json().get("esearchresult", {}).get("idlist", [])
        if not ids:
            return []
        bioproject_id = ids[0]

        # Fetch BioProject details
        r2 = requests.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
                          params={"db": "bioproject", "id": bioproject_id, "retmode": "xml"},
                          timeout=30, headers={"User-Agent": UA})
        if r2.status_code != 200:
            return []

        root = ET.fromstring(r2.content)
        publications = []

        # Look for Publication elements
        for pub in root.iter("Publication"):
            pub_info = {}
            for child in pub:
                if child.tag == "title":
                    pub_info["title"] = child.text or ""
                elif child.tag == "journal":
                    pub_info["journal"] = child.text or ""
                elif child.tag == "date":
                    pub_info["date"] = child.text or ""
                elif child.tag == "pmid":
                    pub_info["pmid"] = child.text or ""
                elif child.tag == "doi":
                    pub_info["doi"] = child.text or ""
            if pub_info:
                publications.append(pub_info)

        # Also look for Project/ProjectDesc/Publication
        for pub_ref in root.iter("PublicationRef"):
            pub_info = {}
            for child in pub_ref:
                tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                if child.text:
                    pub_info[tag] = child.text
            if pub_info:
                publications.append(pub_info)

        return publications
    except Exception as e:
        print(f"  Error: {e}")
        return []

def fetch_pmc_by_pmid(pmid, bid):
    out_path = OUT / f"{bid}.xml"
    try:
        # Get PMC ID
        r = requests.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/elink.fcgi",
                         params={"dbfrom": "pubmed", "db": "pmc", "id": pmid, "retmode": "json"},
                         timeout=30, headers={"User-Agent": UA})
        if r.status_code != 200:
            return False
        pmcid = None
        for ls in r.json().get("linksets", []):
            for lb in ls.get("linksetdbs", []):
                if lb.get("dbto") == "pmc":
                    links = lb.get("links", [])
                    if links:
                        pmcid = links[0]; break
            if pmcid: break
        if not pmcid:
            return False
        xml_r = requests.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
                              params={"db": "pmc", "id": pmcid, "rettype": "xml", "retmode": "xml"},
                              timeout=60, headers={"User-Agent": UA})
        if xml_r.status_code == 200 and is_xml(xml_r.content):
            save(out_path, xml_r.content)
            return True
    except:
        pass
    return False

for accession in ["PRJNA275256", "PRJEB32547"]:
    print(f"\n=== {accession} ===")
    pubs = get_bioproject_links(accession)
    print(f"  Found {len(pubs)} publications")
    for pub in pubs[:5]:
        print(f"    Title: {pub.get('title', 'N/A')[:80]}")
        print(f"    Journal: {pub.get('journal', 'N/A')}")
        print(f"    PMID: {pub.get('pmid', 'N/A')}, DOI: {pub.get('doi', 'N/A')}")
        pmid = pub.get("pmid")
        if pmid and pmid.isdigit():
            if fetch_pmc_by_pmid(pmid, accession):
                size = (OUT / f"{accession}.xml").stat().st_size
                print(f"    OK: PMC XML ({size:,} bytes)")
                break
            else:
                print(f"    No PMC full text")
    time.sleep(1)

total = len(list(OUT.glob("*.pdf"))) + len(list(OUT.glob("*.xml")))
print(f"\nTotal: {total}/351")
