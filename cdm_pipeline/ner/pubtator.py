"""PubTator 3 NER via NCBI E-utilities + PubTator3 API."""
import re
import json
import time as _time

from ..config import CDM_TYPES, PAPERS_DIR, BIOPROJECT_JSON


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


def _load_bioproject_titles():
    """Load clean study titles from bioproject_data_export.json."""
    titles = {}
    if BIOPROJECT_JSON.exists():
        try:
            with open(BIOPROJECT_JSON, encoding="utf-8") as f:
                data = json.load(f)
            for bp in data.get("bioprojects", []):
                pid = bp.get("bioproject_id", "")
                title = bp.get("title", "") or bp.get("study_title", "")
                if pid and title:
                    titles[pid] = title
        except Exception:
            pass
    return titles


def _extract_title_from_text(text):
    """Fallback: extract title from first lines of paper text."""
    lines = [l.strip() for l in text[:2000].split("\n") if l.strip()]
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
        return line
    return None


def run_pubtator(papers, api_key=None, batch_size=200):
    """Run PubTator 3 API on papers.

    Uses clean titles from bioproject_data_export.json when available,
    falls back to parsing paper text. Searches PubMed by title to get PMID,
    then fetches PubTator3 annotations.
    """
    import requests

    SEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"

    print("\n[PubTator] Running via NCBI E-utilities + PubTator3 API ...")

    # Load clean titles from BioProject metadata
    bp_titles = _load_bioproject_titles()
    if bp_titles:
        print("[PubTator] Loaded %d titles from BioProject metadata" % len(bp_titles))

    all_results = []
    found_count = 0
    title_source = {"bioproject": 0, "text": 0, "none": 0}
    t0 = _time.time()

    session = requests.Session()
    if api_key:
        session.params["api_key"] = api_key

    for idx, paper_file in enumerate(papers):
        pid = paper_file.replace(".txt", "")

        # Prefer clean title from BioProject metadata
        title = bp_titles.get(pid)
        if title:
            title_source["bioproject"] += 1
        else:
            path = PAPERS_DIR / paper_file
            text = path.read_text(encoding="utf-8", errors="replace")
            title = _extract_title_from_text(text)
            if title:
                title_source["text"] += 1
            else:
                title_source["none"] += 1

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
    print("[PubTator] Title sources: %s" % title_source)
    return all_results, elapsed
