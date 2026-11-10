"""Fetch each mapped concept's own definition from its ontology (sourced text, not model-generated).

    ~/venvs/parquet_export/bin/python src/scripts/definitions/fetch_ontology_definitions.py [--scope sample500|accepted]

Concepts: those of the 18,272 ACCEPTED mappings of CDM 3.0.3 (13,330 concepts); the 500 review concepts first.
Sources, in order: BioPortal (purl.bioontology.org, SNOMED CT, MeSH), OLS4 (OBO IRIs; NCIt Thesaurus IRIs translated),
UMLS (CUIs), NCBI Taxonomy (rank and lineage only; taxa have no textual definition); if the primary source has no
definition, UMLS is asked for the same code (SNOMEDCT_US, LNC, MSH, OMIM, MDR, ICD10CM) and its definitions are used.
Only concept identifiers are sent; no paper text. Resumable cache:
outputs/results/ontology_definitions_2026-11-09/concept_definitions.jsonl (one row per concept).
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
sys.path.insert(0, str(ROOT / "src/scripts/final_validation"))
import human_spotcheck_mappings_revise as R  # noqa: E402  (reuses get(), clean(), ont_definition(), API keys)

DB = ROOT / "releases/cdm_v3/3.0.3/microbiome_cdm_v3.db"
SAMPLE_KEY = ROOT / "outputs/results/benchmark/human_spotcheck_mappings_2026-11-09/KEY_model_verdicts.csv"
OUT = ROOT / "outputs/results/ontology_definitions_2026-11-09"
CACHE = OUT / "concept_definitions.jsonl"
UMLS_SAB = [(r"purl\.bioontology\.org/ontology/SNOMEDCT/(\d+)$", "SNOMEDCT_US"), (r"snomed\.info/id/(\d+)$", "SNOMEDCT_US"),
            (r"purl\.bioontology\.org/ontology/LNC/([\w-]+)$", "LNC"), (r"purl\.bioontology\.org/ontology/MESH/(\w+)$", "MSH"),
            (r"id\.nlm\.nih\.gov/mesh/(\w+)$", "MSH"), (r"purl\.bioontology\.org/ontology/OMIM/([\w.]+)$", "OMIM"),
            (r"purl\.bioontology\.org/ontology/MEDDRA/(\d+)$", "MDR"), (r"purl\.bioontology\.org/ontology/ICD10CM/([\w.]+)$", "ICD10CM")]
PREF = ("MSH", "NCI", "CSP", "MEDLINEPLUS", "HPO", "NCI_NCI-GLOSS", "MDR", "SNOMEDCT_US")


def umls_by_code(cid):
    if not R.UM:
        return "", ""
    for pat, sab in UMLS_SAB:
        m = re.search(pat, cid)
        if not m:
            continue
        q = urllib.parse.urlencode({"string": m.group(1), "sabs": sab, "searchType": "exact", "inputType": "sourceUi",
                                    "returnIdType": "concept", "apiKey": R.UM})
        res = R.get(f"https://uts-ws.nlm.nih.gov/rest/search/current?{q}")["result"]["results"]
        cui = next((x["ui"] for x in res if x.get("ui", "NONE") != "NONE"), None)
        if not cui:
            return "", f"UMLS {sab} (code not found)"
        try:
            defs = R.get(f"https://uts-ws.nlm.nih.gov/rest/content/current/CUI/{cui}/definitions?apiKey={R.UM}").get("result") or []
        except urllib.error.HTTPError:
            return "", f"UMLS {cui} (no definition)"
        defs.sort(key=lambda d: PREF.index(d.get("rootSource")) if d.get("rootSource") in PREF else 99)
        return (R.clean(defs[0]["value"]), f"UMLS {cui} via {sab} ({defs[0].get('rootSource', '')})") if defs else ("", f"UMLS {cui} (no definition)")
    return "", ""


def concepts(scope):
    first = list(dict.fromkeys(r["concept_id"] for r in csv.DictReader(open(SAMPLE_KEY, encoding="utf-8"))))
    if scope == "sample500":
        return first
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    rest = [c for (c,) in con.execute("SELECT DISTINCT concept_id FROM term_concept_map "
                                      "WHERE mapping_disposition_reviewed='ACCEPTED' ORDER BY concept_id")]
    return first + [c for c in rest if c not in set(first)]


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
            d, src = R.ont_definition(cid)
            if not d:
                d2, src2 = umls_by_code(cid)
                if d2:
                    d, src = d2, src2
                elif src2:
                    src = f"{src}; {src2}"
            f.write(json.dumps({"concept_id": cid, "definition": d, "source": src, "provenance": "ONTOLOGY_SOURCE",
                                "fetched": time.strftime("%Y-%m-%d")}, ensure_ascii=False) + "\n")
            f.flush()
            time.sleep(0.1)
            if k % 250 == 0:
                print(f"{k:,}/{len(todo):,}", flush=True)
    rows = {}
    for l in open(CACHE, encoding="utf-8"):
        r = json.loads(l); rows[r["concept_id"]] = r
    filled = sum(1 for r in rows.values() if r["definition"])
    json.dump({"concepts": len(rows), "with_definition": filled, "provenance": "ONTOLOGY_SOURCE (sourced, not generated)"},
              open(OUT / "summary.json", "w"), indent=1)
    print(f"{filled:,}/{len(rows):,} concepts with a definition")


if __name__ == "__main__":
    main()
