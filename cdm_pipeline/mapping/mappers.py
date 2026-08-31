"""Individual ontology/vocabulary mappers (OLS, UMLS, BioPortal, OMOP, NCBI Taxonomy)."""
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ..config import (
    UMLS_API_KEY, BIOPORTAL_API_KEY, ENTREZ_API_KEY, ENTREZ_EMAIL,
)
from .confidence import _confidence

TIMEOUT = 15


def make_session():
    """HTTP session with retry strategy."""
    s = requests.Session()
    retry = Retry(total=2, backoff_factor=0.5, status_forcelist=[429, 500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retry, pool_connections=20, pool_maxsize=20)
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    return s


SESSION = make_session()


def map_ols(term, cdm_type):
    """EBI OLS - free, no key needed."""
    try:
        r = SESSION.get("https://www.ebi.ac.uk/ols/api/search",
                         params={"q": term, "rows": 3, "exact": "false"},
                         timeout=TIMEOUT)
        if r.status_code != 200:
            return []
        docs = r.json().get("response", {}).get("docs", [])
        results = []
        for d in docs:
            label = d.get("label", "")
            iri = d.get("iri", "")
            onto = d.get("ontology_name", "").upper()
            if not label:
                continue
            results.append({
                "source": "ols",
                "ontology_name": onto,
                "concept_id": iri,
                "label": label,
                "confidence": _confidence(term, label, cdm_type, onto),
            })
        return results[:3]
    except Exception:
        return []


def map_umls(term, cdm_type):
    """UMLS REST API - needs UMLS_API_KEY."""
    if not UMLS_API_KEY:
        return []
    try:
        r = SESSION.get(
            f"https://uts-ws.nlm.nih.gov/rest/search/current",
            params={"string": term, "apiKey": UMLS_API_KEY, "ticket": "1",
                    "pageSize": 3, "returnIdType": "concept"},
            timeout=TIMEOUT)
        if r.status_code != 200:
            return []
        data = r.json()
        results = []
        for item in data.get("result", {}).get("results", []):
            cui = item.get("ui", "")
            name = item.get("name", "")
            if not cui or cui == "NONE":
                continue
            results.append({
                "source": "umls",
                "ontology_name": "UMLS",
                "concept_id": cui,
                "label": name,
                "confidence": _confidence(term, name, cdm_type, "UMLS"),
            })
        return results[:3]
    except Exception:
        return []


def map_bioportal(term, cdm_type):
    """BioPortal search - needs BIOPORTAL_API_KEY."""
    if not BIOPORTAL_API_KEY:
        return []
    try:
        r = SESSION.get("https://data.bioontology.org/search",
                         params={"q": term, "apikey": BIOPORTAL_API_KEY,
                                  "pagesize": 3, "include": "prefLabel"},
                         timeout=TIMEOUT)
        if r.status_code != 200:
            return []
        results = []
        for item in r.json().get("collection", []):
            label = item.get("prefLabel", "")
            onto = item.get("links", {}).get("ontology", "").split("/")[-1].upper()
            concept_id = item.get("@id", "")
            if not label:
                continue
            results.append({
                "source": "bioportal",
                "ontology_name": onto,
                "concept_id": concept_id,
                "label": label,
                "confidence": _confidence(term, label, cdm_type, onto),
            })
        return results[:3]
    except Exception:
        return []


def map_omop(term, cdm_type):
    """OMOP Athena API - free."""
    try:
        r = SESSION.post("https://api.ohdsi.org/WebAPI/vocabulary/search",
                          json=[{"STRING": term, "DOMAIN_ID": None,
                                "VOCABULARY_ID": [], "CONCEPT_CLASS_ID": []}],
                          timeout=TIMEOUT)
        if r.status_code != 200:
            return []
        results = []
        for c in r.json()[:3]:
            name = c.get("CONCEPT_NAME", "")
            concept_id = c.get("CONCEPT_ID", "")
            vocab = c.get("VOCABULARY_ID", "")
            if not concept_id:
                continue
            results.append({
                "source": "omop",
                "ontology_name": vocab,
                "concept_id": str(concept_id),
                "label": name,
                "confidence": _confidence(term, name, cdm_type, vocab),
            })
        return results[:3]
    except Exception:
        return []


def map_ncbi_taxon(term, cdm_type):
    """NCBI Taxonomy via E-utilities - for ORGANISM only."""
    if cdm_type != "ORGANISM":
        return []
    try:
        params = {
            "db": "taxonomy", "term": term + "[Scientific Name]",
            "retmode": "json", "retmax": 3,
        }
        if ENTREZ_API_KEY:
            params["api_key"] = ENTREZ_API_KEY
        if ENTREZ_EMAIL:
            params["email"] = ENTREZ_EMAIL

        r = SESSION.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
                        params=params, timeout=TIMEOUT)
        if r.status_code != 200:
            return []
        ids = r.json().get("esearchresult", {}).get("idlist", [])
        if not ids:
            return []
        taxon_id = ids[0]
        return [{
            "source": "ncbi_taxon",
            "ontology_name": "NCBITAXON",
            "concept_id": f"NCBITaxon:{taxon_id}",
            "label": term,
            "confidence": 1.0,
        }]
    except Exception:
        return []
