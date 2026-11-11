"""MicrobiomeKG (Goetz et al., Front Syst Biol 2025, doi 10.3389/fsysb.2025.1544432) vs Microbiome-CDM.

MicrobiomeKG has no bulk KGX download linked from the paper (Data Availability: "included in the article/Supplementary
Material"); its graph is served as a TRAPI (Plover) API at https://multiomics.transltr.io/mbkp. Its supplementary
Table 1 (INDEX_OF_TABLES; Europe PMC supplementaryFiles of PMC12425944) lists the source publications.
This script:
  1. paper overlap: source publications (DOI / PMCID / PMID, PMCIDs resolved through the Europe PMC REST API) vs our
     453 papers (CDM 3.1.0 paper.doi / pmid / pmcid);
  2. for shared papers: TRAPI one-hop queries pinned on the NCBI taxa of our catalogue findings for that paper (plus their
     genera), edges kept when biolink:publications names the shared paper; taxa / object / sign compared with our
     findings and triples for that paper;
  3. taxon coverage: TRAPI one-hop queries pinned on every genus in our catalogue (batches of 100) -> share of our
     genera present in MicrobiomeKG and the predicates/categories they connect to.
All requests use a generic User-Agent and are cached under outputs/scratch/competitors/microbiomekg/.
Outputs: outputs/results/competitor_compare_2026-11-11/microbiomekg/{SUMMARY.json, REPORT.md, shared_paper_edges.csv}
Written with Claude Code (declare).
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from _cstats import RESULTS, ROOT, SCRATCH, dump, wilson, write_manifest  # noqa: E402

sys.path.insert(0, str(ROOT / "src/scripts/bugsigdb_comparison"))
import compare as BC  # noqa: E402

D = SCRATCH / "microbiomekg"
OUT = RESULTS / "microbiomekg"
DB310 = ROOT / "releases/cdm_v3/3.1.0/microbiome_cdm_v3.1.0.db"
TRAPI = "https://multiomics.transltr.io/mbkp/query"
UA = {"User-Agent": "cdm-compare/1.0", "Content-Type": "application/json"}


def cached(key, fn):
    p = D / "cache" / (hashlib.sha1(key.encode()).hexdigest() + ".json")
    if p.exists():
        return json.loads(p.read_text())
    v = fn()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(v))
    time.sleep(0.5)
    return v


def trapi(ids, reverse=False):
    q = {"message": {"query_graph": {"nodes": {"n0": {"ids": ids}, "n1": {}},
                                     "edges": {"e0": {"subject": "n1", "object": "n0"} if reverse else {"subject": "n0", "object": "n1"}}}}}

    def go():
        for k in range(4):
            try:
                r = urllib.request.Request(TRAPI, data=json.dumps(q).encode(), headers=UA)
                return json.load(urllib.request.urlopen(r, timeout=300))["message"]["knowledge_graph"]
            except Exception as e:  # noqa: BLE001
                print("retry", repr(e)[:100], flush=True)
                time.sleep(10 * (k + 1))
        raise RuntimeError("TRAPI failed")
    return cached(json.dumps(q, sort_keys=True), go)


def attrs(e):
    return {a["attribute_type_id"]: a.get("value") for a in e.get("attributes", [])}


def source_pubs():
    import openpyxl
    wb = openpyxl.load_workbook(D / "supp/Table1.xlsx", read_only=True)
    rows = [r for r in wb.worksheets[0].iter_rows(values_only=True)][1:]
    pubs = sorted({r[0].strip() for r in rows if r and r[0]})
    pmcs = [p.split(":", 1)[1] for p in pubs if p.upper().startswith("PMC:")]

    def epmc(q):
        u = "https://www.ebi.ac.uk/europepmc/webservices/rest/search?" + urllib.parse.urlencode({"query": q, "format": "json", "pageSize": 100})
        return json.load(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "cdm-compare/1.0"}), timeout=120))
    res = {}
    for i in range(0, len(pmcs), 12):
        q = " OR ".join(f"PMCID:{x}" for x in pmcs[i:i + 12])
        for r in cached("epmc:" + q, lambda q=q: epmc(q))["resultList"]["result"]:
            res[r.get("pmcid")] = {"pmid": r.get("pmid"), "doi": (r.get("doi") or "").lower()}
    out = []
    for p in pubs:
        k, _, v = p.partition(":")
        rec = {"curie": p, "pmid": None, "doi": None, "pmcid": None}
        if k.upper() == "PMC":
            rec.update(pmcid=v.upper(), **res.get(v.upper(), {}))
        elif k.upper() == "PMID":
            rec["pmid"] = v
        else:
            rec["doi"] = v.lower()
        out.append(rec)
    return out, len(rows)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(f"file:{DB310}?mode=ro", uri=True)
    P = c.execute("SELECT paper_id, lower(doi), pmid, upper(pmcid) FROM paper").fetchall()
    by_doi = {(d or "").replace("https://doi.org/", ""): p for p, d, _, _ in P if d}
    by_pm = {str(m): p for p, _, m, _ in P if m}
    by_pmc = {x: p for p, _, _, x in P if x}
    pubs, n_tables = source_pubs()
    shared = {}
    for r in pubs:
        h = by_doi.get(r["doi"] or "-") or by_pm.get(str(r["pmid"] or "-")) or by_pmc.get(r["pmcid"] or "-")
        if h:
            shared[h] = r
    parent, rank, sci, genus = BC.load_taxonomy()
    summ = {"source": "MicrobiomeKG TRAPI https://multiomics.transltr.io/mbkp (queried " + time.strftime("%Y-%m-%d") +
                      "); supplementary Table 1 via Europe PMC PMC12425944/supplementaryFiles",
            "licence": "article CC BY 4.0; no data licence stated for the API",
            "microbiomekg_source_publications": len(pubs), "microbiomekg_table_rows": n_tables,
            "shared_papers": wilson(len(shared), len(pubs)), "shared_paper_ids": {k: v["curie"] for k, v in shared.items()}}
    # 2. shared-paper edges
    edges_out = []
    per_paper = {}
    for pid, r in shared.items():
        ids = set()
        for (x,) in c.execute("SELECT taxon_ncbi_ids FROM claim WHERE paper_id=? AND claim_source='catalogue_v3_1'", (pid,)):
            for t in BC.taxa_ids(x):
                ids.add(t)
                g = genus(t)
                if g in rank and rank[g] == "genus":
                    ids.add(g)
        curies = [f"NCBITaxon:{t}" for t in sorted(ids)]
        keys = {r["curie"].upper(), f"PMC:{r['pmcid']}".upper() if r["pmcid"] else "-", f"PMID:{r['pmid']}".upper() if r["pmid"] else "-"}
        theirs = []
        for i in range(0, len(curies), 100):
            for rev in (False, True):
                kg = trapi(curies[i:i + 100], rev)
                for e in kg["edges"].values():
                    a = attrs(e)
                    pubv = a.get("biolink:publications")
                    pubv = pubv if isinstance(pubv, list) else [pubv]
                    if any(str(x).upper() in keys for x in pubv if x):
                        theirs.append((e, a, kg["nodes"]))
        mk_taxa = set()
        for e, a, nodes in theirs:
            for side in ("subject", "object"):
                if e[side].startswith("NCBITaxon:"):
                    mk_taxa.add(int(e[side].split(":")[1]))
            edges_out.append({"paper_id": pid, "subject": e["subject"], "subject_name": nodes.get(e["subject"], {}).get("name"),
                              "predicate": e["predicate"], "object": e["object"], "object_name": nodes.get(e["object"], {}).get("name"),
                              "strength": a.get("STATO:0000085"), "p": a.get("biolink:adjusted_p_value"), "test": a.get("AFR_0000895")})
        ours_taxa = {t for (x,) in c.execute("SELECT taxon_ncbi_ids FROM claim WHERE paper_id=? AND claim_source='catalogue_v3_1'", (pid,))
                     for t in BC.taxa_ids(x)}
        g_ours = {genus(t) for t in ours_taxa}
        g_mk = {genus(t) for t in mk_taxa}
        n_find = c.execute("SELECT count(*) FROM claim WHERE paper_id=? AND claim_source='catalogue_v3_1'", (pid,)).fetchone()[0]
        n_trip = c.execute("SELECT count(DISTINCT canonical_triple_id) FROM relation_evidence WHERE paper_id=?", (pid,)).fetchone()[0]
        per_paper[pid] = {"microbiomekg_edges_for_paper": len(theirs), "cdm_catalogue_findings": n_find, "cdm_triples_with_evidence": n_trip,
                          "microbiomekg_predicates": dict(Counter(e["predicate"] for e, _, _ in theirs)),
                          "taxa_cdm": len(ours_taxa), "taxa_microbiomekg_pinned_hits": len(mk_taxa),
                          "genera_shared": len(g_ours & g_mk), "genera_cdm_only": len(g_ours - g_mk), "genera_microbiomekg_only": len(g_mk - g_ours),
                          "note": "MicrobiomeKG edges were retrieved only for taxa that occur in our findings for this paper, so taxa"
                                  " that MicrobiomeKG has and we lack are not visible here"}
    summ["shared_paper_comparison"] = per_paper
    if edges_out:
        with open(OUT / "shared_paper_edges.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(edges_out[0]))
            w.writeheader()
            w.writerows(edges_out)
    # 3. genus coverage
    gen = set()
    for (x,) in c.execute("SELECT taxon_ncbi_ids FROM claim WHERE claim_source='catalogue_v3_1' AND taxon_ncbi_ids LIKE 'NCBITaxon:%'"):
        for t in BC.taxa_ids(x):
            g = genus(t)
            if g in rank and rank[g] == "genus":
                gen.add(g)
    gen = sorted(gen)
    hit, preds, cats = set(), Counter(), Counter()
    for i in range(0, len(gen), 100):
        kg = trapi([f"NCBITaxon:{g}" for g in gen[i:i + 100]])
        for e in kg["edges"].values():
            if e["subject"].startswith("NCBITaxon:"):
                hit.add(int(e["subject"].split(":")[1]))
            preds[e["predicate"]] += 1
            cats[(kg["nodes"].get(e["object"], {}).get("categories") or ["?"])[0]] += 1
    summ["genus_coverage"] = {"cdm_catalogue_genera": len(gen), "present_as_subject_in_microbiomekg": wilson(len(hit & set(gen)), len(gen)),
                              "edge_predicates": dict(preds.most_common(10)), "object_categories": dict(cats.most_common(10)),
                              "note": "one-hop, taxon as subject only; MicrobiomeKG normalises taxa to NCBITaxon via Babel"}
    dump(summ, OUT / "SUMMARY.json")
    write_manifest(D, "Europe PMC supplementaryFiles PMC12425944 + MicrobiomeKG TRAPI responses (cache/)", "article CC BY 4.0",
                   time.strftime("%Y-%m-%d"))
    print(json.dumps(summ, indent=1)[:3000])


if __name__ == "__main__":
    main()
