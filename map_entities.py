"""
Map deduplicated entities to controlled vocabularies:
  OLS (EBI), UMLS, BioPortal, OMOP Athena, NCBI Taxonomy

Reads:  paper_claims/_multi_ner_runs/deduplicated_entities.json
Writes: paper_claims/_multi_ner_runs/mapped_entities.json
        paper_claims/_multi_ner_runs/mapping_checkpoint.json  (resume support)

Uses the existing mappers in llm_terms/mappers/ with concurrent API calls.
"""
import sys, io, os, json, time, gc, warnings
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

warnings.filterwarnings("ignore")

sys.path.insert(0, str(Path(__file__).parent / "llm_terms"))

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

REPO = Path(__file__).parent
INPUT = REPO / "paper_claims" / "_multi_ner_runs" / "deduplicated_entities.json"
OUTPUT = REPO / "paper_claims" / "_multi_ner_runs" / "mapped_entities.json"
CHECKPOINT = REPO / "paper_claims" / "_multi_ner_runs" / "mapping_checkpoint.json"

UMLS_API_KEY = os.environ.get("UMLS_API_KEY", "")
BIOPORTAL_API_KEY = os.environ.get("BIOPORTAL_API_KEY", "")
ENTREZ_API_KEY = os.environ.get("ENTREZ_API_KEY", "")
ENTREZ_EMAIL = os.environ.get("ENTREZ_EMAIL", "microbiome.cdm@gmail.com")

MAX_WORKERS = 12
CHECKPOINT_EVERY = 500
TIMEOUT = 15

# ────────────────── HTTP session with retries ──────────────────

def make_session():
    s = requests.Session()
    retry = Retry(total=2, backoff_factor=0.5, status_forcelist=[429, 500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retry, pool_connections=20, pool_maxsize=20)
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    return s

SESSION = make_session()

# ────────────────── Individual mappers ──────────────────

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


# ────────────────── Confidence scoring (lightweight) ──────────────────

from rapidfuzz import fuzz

PREFERRED = {
    "ORGANISM": {"NCBITAXON", "SNOMEDCT", "MESH"},
    "PROTEIN": {"PR", "GO", "CHEBI", "MESH"},
    "CHEMICAL": {"CHEBI", "MESH", "RXNORM", "SNOMEDCT"},
    "DISEASE": {"DOID", "MONDO", "SNOMEDCT", "ICD9CM", "ICD10", "OMIM", "MESH"},
    "DNA_RNA": {"SO", "SEQUENCE", "GENEPIO", "MESH"},
    "CELL_TYPE": {"CL", "CLO", "MESH"},
    "SAMPLE_METHOD": {"OBI", "NCIT", "MESH"},
    "LAB_METHOD": {"OBI", "NCIT", "ERO", "MESH"},
    "DATA_ANALYSIS": {"STATO", "OBI", "EDAM", "NCIT"},
    "PATHWAY": {"GO", "WIKIPATHWAYS", "REACTOME", "CHEBI"},
    "EXPERIMENTAL_METHOD": {"OBI", "ERO", "NCIT"},
    "STUDY_DESIGN": {"OBI", "SNOMEDCT", "NCIT"},
    "GENOMICS": {"OBI", "SO", "NCIT", "MESH"},
    "CLINICAL": {"SNOMEDCT", "NCIT", "LOINC", "MESH"},
}

NOISY = {"MEDDRA", "ICD9CM", "RCD", "CPT", "LNC"}


def _confidence(entity, label, cdm_type, ontology):
    if not label:
        return 0.5
    a = " ".join(entity.lower().split())
    b = " ".join(label.lower().split())
    if a == b:
        return 1.0
    sim = fuzz.token_set_ratio(a, b) / 100.0
    score = 0.3 + 0.65 * sim
    if ontology:
        onto = ontology.upper()
        if onto in PREFERRED.get(cdm_type, set()):
            score += 0.05
        elif onto in NOISY and onto not in PREFERRED.get(cdm_type, set()):
            score -= 0.15
    return max(0.0, min(1.0, score))


# ────────────────── Vocabulary precedence ──────────────────

VOCAB_PRIORITY = {
    "ORGANISM": ["NCBITAXON", "SNOMEDCT", "MESH"],
    "PROTEIN": ["PR", "GO", "CHEBI", "MESH"],
    "CHEMICAL": ["CHEBI", "MESH", "RXNORM", "SNOMEDCT"],
    "DISEASE": ["DOID", "MONDO", "SNOMEDCT", "ICD9CM", "ICD10", "OMIM", "MESH"],
    "DNA_RNA": ["SO", "SEQUENCE", "GENEPIO", "MESH"],
    "CELL_TYPE": ["CL", "CLO", "MESH"],
    "SAMPLE_METHOD": ["OBI", "NCIT", "MESH"],
    "LAB_METHOD": ["OBI", "NCIT", "ERO", "MESH"],
    "DATA_ANALYSIS": ["STATO", "OBI", "EDAM", "NCIT"],
    "PATHWAY": ["GO", "WIKIPATHWAYS", "REACTOME", "CHEBI"],
    "EXPERIMENTAL_METHOD": ["OBI", "ERO", "NCIT"],
    "STUDY_DESIGN": ["OBI", "SNOMEDCT", "NCIT"],
    "GENOMICS": ["OBI", "SO", "NCIT", "MESH"],
    "CLINICAL": ["SNOMEDCT", "NCIT", "LOINC", "MESH"],
}


def resolve_canonical(candidates, cdm_type):
    """Pick the canonical mapping from all candidates by vocab priority + confidence."""
    if not candidates:
        return None, []
    priority = VOCAB_PRIORITY.get(cdm_type, [])

    def sort_key(c):
        try:
            rank = priority.index(c["ontology_name"])
        except ValueError:
            rank = len(priority)
        return (rank, -c["confidence"])

    ranked = sorted(candidates, key=sort_key)
    canonical = ranked[0]
    others = ranked[1:]
    return canonical, others


# ────────────────── Main mapping ──────────────────

def map_one_entity(entity):
    """Map a single entity to all available vocabularies."""
    term = entity["term"]
    cdm_type = entity["cdm_type"]

    candidates = []
    candidates.extend(map_ols(term, cdm_type))
    candidates.extend(map_umls(term, cdm_type))
    candidates.extend(map_bioportal(term, cdm_type))
    candidates.extend(map_omop(term, cdm_type))
    candidates.extend(map_ncbi_taxon(term, cdm_type))

    canonical, others = resolve_canonical(candidates, cdm_type)

    return {
        "term": term,
        "norm": entity["norm"],
        "cdm_type": cdm_type,
        "sources": entity["sources"],
        "paper_count": entity["paper_count"],
        "mention_count": entity["mention_count"],
        "canonical": canonical,
        "all_mappings": candidates,
        "has_mapping": canonical is not None,
    }


def load_checkpoint():
    if CHECKPOINT.exists():
        with open(CHECKPOINT, encoding="utf-8") as f:
            return json.load(f)
    return {"done": {}, "results": []}


def save_checkpoint(cp):
    with open(CHECKPOINT, "w", encoding="utf-8") as f:
        json.dump(cp, f, ensure_ascii=False)


def main():
    with open(INPUT, encoding="utf-8") as f:
        entities = json.load(f)
    print(f"Loaded {len(entities)} deduplicated entities")

    cp = load_checkpoint()
    done = set(cp["done"].keys())
    results = cp["results"]

    todo = [e for e in entities if e["norm"] not in done]
    print(f"Already mapped: {len(done)}, remaining: {len(todo)}")

    if not todo:
        print("Nothing to do.")
    else:
        t0 = time.time()
        mapped = 0
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = {pool.submit(map_one_entity, e): e for e in todo}
            for future in as_completed(futures):
                try:
                    result = future.result()
                    results.append(result)
                    cp["done"][result["norm"]] = True
                    mapped += 1
                except Exception as ex:
                    e = futures[future]
                    cp["done"][e["norm"]] = False
                    results.append({
                        "term": e["term"], "norm": e["norm"],
                        "cdm_type": e["cdm_type"], "sources": e["sources"],
                        "paper_count": e["paper_count"], "mention_count": e["mention_count"],
                        "canonical": None, "all_mappings": [], "has_mapping": False,
                    })
                    mapped += 1

                if mapped % CHECKPOINT_EVERY == 0:
                    save_checkpoint(cp)
                    rate = mapped / (time.time() - t0)
                    print(f"  {mapped}/{len(todo)} ({rate:.1f}/s) "
                          f"mapped={sum(1 for r in results if r['has_mapping'])}")

        save_checkpoint(cp)
        elapsed = time.time() - t0
        print(f"Done: {mapped} in {elapsed:.1f}s")

    # Final output
    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"Saved {len(results)} mapped entities to {OUTPUT}")

    # Summary
    total = len(results)
    mapped_count = sum(1 for r in results if r["has_mapping"])
    by_type = {}
    by_vocab = {}
    for r in results:
        t = r["cdm_type"]
        by_type.setdefault(t, {"total": 0, "mapped": 0})
        by_type[t]["total"] += 1
        if r["has_mapping"]:
            by_type[t]["mapped"] += 1
            v = r["canonical"]["ontology_name"]
            by_vocab[v] = by_vocab.get(v, 0) + 1

    print(f"\n=== MAPPING SUMMARY ===")
    print(f"Total entities: {total}")
    print(f"Mapped: {mapped_count} ({100*mapped_count/total:.1f}%)")
    print(f"\nBy CDM type:")
    for t in sorted(by_type, key=lambda x: -by_type[x]["total"]):
        d = by_type[t]
        print(f"  {t:20s} {d['mapped']:5d}/{d['total']:<5d} ({100*d['mapped']/d['total']:.1f}%)")
    print(f"\nTop mapped vocabularies:")
    for v, c in sorted(by_vocab.items(), key=lambda x: -x[1])[:15]:
        print(f"  {v:20s} {c}")

    # Write summary JSON
    summary = {
        "total": total, "mapped": mapped_count, "rate": 100*mapped_count/total,
        "by_type": by_type, "by_vocab": by_vocab,
        "api_keys_used": {
            "umls": bool(UMLS_API_KEY), "bioportal": bool(BIOPORTAL_API_KEY),
            "entrez": bool(ENTREZ_API_KEY),
        },
    }
    summary_path = REPO / "paper_claims" / "_multi_ner_runs" / "mapping_summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print(f"\nSummary saved to {summary_path}")


if __name__ == "__main__":
    main()
