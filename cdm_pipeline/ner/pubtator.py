"""PubTator 3 NER via NCBI E-utilities + PubTator3 API."""
import re
import time as _time

from ..config import CDM_TYPES, PAPERS_DIR


def map_pubtator_label(raw_type):
    """Map PubTator type to CDM type."""
    rt = raw_type.upper()
    mapping = {
        "DISEASE": "DISEASE",
        "CHEMICAL": "CHEMICAL",
        "GENE": "PROTEIN",
        "GENE_GENE": "PROTEIN",
        "PROTEIN": "PROTEIN",
        "SPECIES": "ORGANISM",
        "TAXON": "ORGANISM",
        "ORGANISM": "ORGANISM",
        "CELLLINE": "CELL_TYPE",
        "CELL_LINE": "CELL_TYPE",
        "CELL_TYPE": "CELL_TYPE",
        "DNA": "DNA_RNA",
        "RNA": "DNA_RNA",
        "MUTATION": "GENOMICS",
        "VARIANT": "GENOMICS",
    }
    return mapping.get(rt, rt if rt in CDM_TYPES else "ENTITY")


def run_pubtator(papers, api_key=None, batch_size=200):
    """Run PubTator 3 API on papers.

    PubTator annotates PubMed abstracts/full text by PMID.
    Since our papers are PRJ-accession-named txt files (not PMIDs),
    we need to extract the PMID from the text or use the title-based search.

    Strategy: Extract title from first line of each paper, search PubTator
    by title to get PMID, then fetch annotations.
    """
    import requests

    SEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"

    print("\n[PubTator] Running via NCBI E-utilities + PubTator3 API ...")

    all_results = []
    found_count = 0
    t0 = _time.time()

    session = requests.Session()
    if api_key:
        session.params["api_key"] = api_key

    for idx, paper_file in enumerate(papers):
        path = PAPERS_DIR / paper_file
        text = path.read_text(encoding="utf-8", errors="replace")

        # Extract title from first ~2000 chars
        lines = [l.strip() for l in text[:2000].split("\n") if l.strip()]
        title = None
        junk_titles = {
            "research article", "nature communications", "science",
            "plos one", "frontiers", "frontiers in", "pnas",
            "proceedings of the national academy of sciences",
        }
        for line in lines:
            if line.startswith("PRJ") or len(line) < 10:
                continue
            low = line.lower().strip()
            if low in junk_titles:
                continue
            if re.search(r'\d{4}\s*\(\d{4}\)\s*\d', line):
                continue
            if re.match(r'^\d{4}$', line.strip()):
                continue
            title = line
            break

        if not title:
            continue

        # Search for PMID by title
        try:
            params = {
                "db": "pubmed",
                "term": title[:200],
                "retmode": "json",
                "retmax": 1,
            }
            resp = session.get(SEARCH_URL, params=params, timeout=15)
            data = resp.json()
            id_list = data.get("esearchresult", {}).get("idlist", [])
            if not id_list:
                continue
            pmid = id_list[0]
        except Exception:
            continue

        # Fetch PubTator annotations (biocjson format)
        try:
            pubtator_url = "https://www.ncbi.nlm.nih.gov/research/pubtator3-api/publications/export/biocjson"
            resp = session.post(pubtator_url, json={"pmids": [pmid]}, timeout=30)
            if resp.status_code != 200:
                continue
            data = resp.json()
            docs = data.get("PubTator3", [])
            for doc in docs:
                for passage in doc.get("passages", []):
                    for ent in passage.get("annotations", []):
                        infons = ent.get("infons", {})
                        raw_type = infons.get("type", "").upper()
                        cdm_label = map_pubtator_label(raw_type)
                        ent_text = ent.get("text", "").strip()
                        if not ent_text:
                            continue
                        all_results.append((
                            ent_text,
                            cdm_label,
                            "pubtator3",
                            paper_file,
                            0, 0,
                        ))
                        found_count += 1
        except Exception:
            pass

        if (idx + 1) % 25 == 0 or idx == len(papers) - 1:
            elapsed = _time.time() - t0
            print("  [PubTator] %d/%d papers (%d found, %.1fs)" % (
                idx + 1, len(papers), found_count, elapsed))
        # Rate limit: 10 req/s with API key, 3/s without
        _time.sleep(0.12)

    elapsed = _time.time() - t0
    print("[PubTator] Done: %d entities from %d papers in %.1fs" % (
        len(all_results), len(papers), elapsed))
    return all_results, elapsed
