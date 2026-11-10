"""Individual ontology/vocabulary mappers (OLS, UMLS, BioPortal, OMOP, NCBI Taxonomy)."""
import time
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ..config import (
    UMLS_API_KEY, BIOPORTAL_API_KEY, ENTREZ_API_KEY, ENTREZ_EMAIL,
    VOCAB_PRIORITY,
)
from .confidence import _confidence, _normalize_vocab

TIMEOUT = 30

# NCBI rate limiting: 3 req/s without API key, 10 req/s with
_NCBI_MIN_INTERVAL = 0.35 if not ENTREZ_API_KEY else 0.1
_NCBI_LAST_CALL = 0.0


def make_session():
    """HTTP session with retry strategy."""
    s = requests.Session()
    retry = Retry(total=3, backoff_factor=1.0, status_forcelist=[429, 500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retry, pool_connections=20, pool_maxsize=20)
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    return s


SESSION = make_session()


def _is_type_appropriate(ontology_name, cdm_type):
    """Check whether a vocabulary is appropriate for the given CDM type.

    Returns True if the vocabulary is in the type's VOCAB_PRIORITY list,
    or if no priority list is defined for the type (permissive fallback).
    """
    priority = VOCAB_PRIORITY.get(cdm_type, [])
    if not priority:
        return True
    norm_onto = _normalize_vocab(ontology_name)
    norm_priority = {_normalize_vocab(v) for v in priority}
    return norm_onto in norm_priority


def map_ols(term, cdm_type):
    """EBI OLS - free, no key needed."""
    try:
        r = SESSION.get("https://www.ebi.ac.uk/ols4/api/search",
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
            if not _is_type_appropriate(onto, cdm_type):
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
    """UMLS REST API - needs UMLS_API_KEY.

    UMLS is a meta-vocabulary covering all semantic types. We accept all UMLS
    results (type filtering is handled by VOCAB_PRIORITY ranking, not rejection,
    since UMLS CUIs span every domain and the concept itself may be valid even
    if the vocabulary name is generic).
    """
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
            if not _is_type_appropriate(onto, cdm_type):
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
    """OMOP Athena API - free (currently disabled: server returns 500 NPE)."""
    return []
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


def _entrez_esearch(db, term, retmax=3):
    """Helper: NCBI ESearch with API key + email if available."""
    global _NCBI_LAST_CALL
    # Rate limit: enforce minimum interval between NCBI calls
    elapsed = time.time() - _NCBI_LAST_CALL
    if elapsed < _NCBI_MIN_INTERVAL:
        time.sleep(_NCBI_MIN_INTERVAL - elapsed)
    _NCBI_LAST_CALL = time.time()

    params = {"db": db, "term": term, "retmode": "json", "retmax": retmax}
    if ENTREZ_API_KEY:
        params["api_key"] = ENTREZ_API_KEY
    if ENTREZ_EMAIL:
        params["email"] = ENTREZ_EMAIL
    try:
        r = SESSION.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
                        params=params, timeout=TIMEOUT)
        if r.status_code != 200:
            return []
        return r.json().get("esearchresult", {}).get("idlist", [])
    except Exception:
        return []


def map_ncbi_taxon(term, cdm_type):
    """NCBI Taxonomy via E-utilities - for ORGANISM only.

    Tries, in order:
      1. Exact scientific name match (term[Scientific Name])
      2. All-names match (term[All Names]) — catches synonyms, common names
      3. Broad search (no field qualifier) — catches partial / genus-level
    Returns the first hit with appropriate confidence.
    """
    if cdm_type != "ORGANISM":
        return []

    # 1. Exact scientific name
    ids = _entrez_esearch("taxonomy", term + "[Scientific Name]")
    if ids:
        return [{
            "source": "ncbi_taxon",
            "ontology_name": "NCBITAXON",
            "concept_id": f"NCBITaxon:{ids[0]}",
            "label": term,
            "confidence": 1.0,
            "mapping_tier": 1,
        }]

    # 2. All names (synonyms, common names, genbank synonyms)
    ids = _entrez_esearch("taxonomy", term + "[All Names]")
    if ids:
        return [{
            "source": "ncbi_taxon",
            "ontology_name": "NCBITAXON",
            "concept_id": f"NCBITaxon:{ids[0]}",
            "label": term,
            "confidence": 0.85,
            "mapping_tier": 2,
        }]

    # 3. Broad unqualified search — last resort for genus/phylum-level mentions
    ids = _entrez_esearch("taxonomy", term)
    if ids:
        return [{
            "source": "ncbi_taxon",
            "ontology_name": "NCBITAXON",
            "concept_id": f"NCBITaxon:{ids[0]}",
            "label": term,
            "confidence": 0.7,
            "mapping_tier": 3,
        }]

    return []
