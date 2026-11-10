"""Fetch each mapped concept's own definition AND synonyms from its ontology (sourced text, not model-generated).

    ~/venvs/parquet_export/bin/python src/scripts/definitions/fetch_ontology_info.py [--scope sample500|accepted]

Concepts: those of the 18,272 ACCEPTED mappings of CDM 3.0.3 (13,330); the 500 review concepts first.
Sources: BioPortal (purl.bioontology.org incl. MeSH, SNOMED CT, LOINC, OMIM; definition + synonym), OLS4 (OBO IRIs,
NCIt Thesaurus IRIs translated; description + synonyms), UMLS (CUIs; definitions + English atom names), NCBI Taxonomy
(rank, lineage, other names). If the primary source has no definition, UMLS is asked for the same source code and its
definition is used. Only concept identifiers are sent; no paper text. Resumable cache (one row per concept):
outputs/results/ontology_definitions_2026-11-09/concept_ontology_info.jsonl
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
sys.path.insert(0, str(ROOT / "src/scripts/final_validation"))
sys.path.insert(0, str(ROOT / "src/scripts/definitions"))
import human_spotcheck_mappings_revise as R  # noqa: E402  (get(), clean(), API keys)
from fetch_ontology_definitions import PREF, UMLS_SAB, concepts  # noqa: E402

OUT = ROOT / "outputs/results/ontology_definitions_2026-11-09"
CACHE = OUT / "concept_ontology_info.jsonl"
BPH = {"Authorization": f"apikey token={R.BP}"} if R.BP else {}


def syn_list(xs, label=""):
    seen, out = {label.lower().strip()}, []
    for x in xs or []:
        x = R.clean(str(x))[:120]
        if x and x.lower() not in seen:
            seen.add(x.lower()); out.append(x)
    return out[:10]


def bioportal(acr, iri):
    d = R.get(f"https://data.bioontology.org/ontologies/{acr}/classes/{urllib.parse.quote(iri, safe='')}", BPH)
    return R.clean("; ".join(d.get("definition") or [])), syn_list(d.get("synonym"), d.get("prefLabel", "")), f"BioPortal {acr}"


def umls_cui(cui):
    try:
        defs = R.get(f"https://uts-ws.nlm.nih.gov/rest/content/current/CUI/{cui}/definitions?apiKey={R.UM}").get("result") or []
    except urllib.error.HTTPError:
        defs = []
    defs.sort(key=lambda d: PREF.index(d.get("rootSource")) if d.get("rootSource") in PREF else 99)
    try:
        atoms = R.get(f"https://uts-ws.nlm.nih.gov/rest/content/current/CUI/{cui}/atoms?language=ENG&pageSize=40&apiKey={R.UM}").get("result") or []
    except urllib.error.HTTPError:
        atoms = []
    return (R.clean(defs[0]["value"]) if defs else ""), syn_list(a.get("name") for a in atoms), f"UMLS {cui}"


def umls_code(cid):
    for pat, sab in UMLS_SAB:
        m = re.search(pat, cid)
        if m:
            q = urllib.parse.urlencode({"string": m.group(1), "sabs": sab, "searchType": "exact", "inputType": "sourceUi",
                                        "returnIdType": "concept", "apiKey": R.UM})
            res = R.get(f"https://uts-ws.nlm.nih.gov/rest/search/current?{q}")["result"]["results"]
            cui = next((x["ui"] for x in res if x.get("ui", "NONE") != "NONE"), None)
            return umls_cui(cui) if cui else ("", [], f"UMLS {sab} (code not found)")
    return "", [], ""


def info(cid):
    try:
        m = re.search(r"bioontology\.org/ontology/([^/]+)/(.+)$", cid)
        if m and R.BP:
            return bioportal(m.group(1), cid)
        m = re.match(r"https?://snomed\.info/id/(\d+)$", cid)
        if m and R.BP:
            return bioportal("SNOMEDCT", f"http://purl.bioontology.org/ontology/SNOMEDCT/{m.group(1)}")
        m = re.match(r"https?://id\.nlm\.nih\.gov/mesh/(\w+)$", cid)
        if m and R.BP:
            return bioportal("MESH", f"http://purl.bioontology.org/ontology/MESH/{m.group(1)}")
        m = re.search(r"NCBITaxon[:_](\d+)$", cid) or re.search(r"taxonomy/(\d+)$", cid)
        if m:
            x = ET.fromstring(urllib.request.urlopen(f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=taxonomy&id={m.group(1)}", timeout=30).read())
            t = x.find("Taxon")
            name, rank = t.findtext("ScientificName", ""), t.findtext("Rank", "")
            lin = t.findtext("Lineage", "")
            others = [e.text for e in t.iter() if e.tag in ("Synonym", "GenbankCommonName", "CommonName", "EquivalentName") and e.text]
            return (f"NCBI Taxonomy {rank} {name}; lineage: {lin[-160:]} (taxa carry no textual definition)",
                    syn_list(others, name), "NCBI Taxonomy")
        m = re.match(r"(?:UMLS:)?(C\d{7})$", cid)
        if m and R.UM:
            return umls_cui(m.group(1))
        m = re.search(r"Thesaurus\.owl#(C\d+)$", cid)
        if m:
            cid = f"http://purl.obolibrary.org/obo/NCIT_{m.group(1)}"
        if cid.startswith("http"):
            d = R.get(f"https://www.ebi.ac.uk/ols4/api/terms?iri={urllib.parse.quote(cid, safe='')}")
            for t in (d.get("_embedded") or {}).get("terms") or []:
                return (R.clean((t.get("description") or [""])[0]), syn_list(t.get("synonyms"), t.get("label", "")),
                        f"OLS {t.get('ontology_prefix', '')}")
            return "", [], "OLS (not found)"
    except urllib.error.HTTPError as e:
        return "", [], f"lookup failed: HTTP {e.code}"
    except Exception as e:  # noqa: BLE001
        return "", [], f"lookup failed: {type(e).__name__}"
    return "", [], "no source"


import urllib.request  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scope", choices=["sample500", "accepted"], default="accepted")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    done = set()
    if CACHE.exists():
        for l in open(CACHE, encoding="utf-8"):
            try:
                r = json.loads(l)
                if not r["source"].startswith("lookup failed"):
                    done.add(r["concept_id"])
            except (ValueError, KeyError):
                pass
    todo = [c for c in concepts(a.scope) if c not in done]
    print(f"{len(done):,} cached; {len(todo):,} to fetch", flush=True)
    with open(CACHE, "a", encoding="utf-8") as f:
        for k, cid in enumerate(todo, 1):
            d, syn, src = info(cid)
            if not d and R.UM:
                try:
                    d2, syn2, src2 = umls_code(cid)
                except Exception:  # noqa: BLE001
                    d2, syn2, src2 = "", [], ""
                if d2:
                    d, src = d2, f"{src}; definition via {src2}"
                if not syn and syn2:
                    syn = syn2
            f.write(json.dumps({"concept_id": cid, "definition": d, "synonyms": syn, "source": src,
                                "provenance": "ONTOLOGY_SOURCE", "fetched": time.strftime("%Y-%m-%d")},
                               ensure_ascii=False) + "\n")
            f.flush(); time.sleep(0.1)
            if k % 250 == 0:
                print(f"{k:,}/{len(todo):,}", flush=True)
    rows = {}
    for l in open(CACHE, encoding="utf-8"):
        r = json.loads(l); rows[r["concept_id"]] = r
    print(f"{sum(1 for r in rows.values() if r['definition']):,} with definition, "
          f"{sum(1 for r in rows.values() if r['synonyms']):,} with synonyms, of {len(rows):,} concepts")


if __name__ == "__main__":
    main()
