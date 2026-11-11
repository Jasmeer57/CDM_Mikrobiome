"""KG-Microbe (Santangelo et al., GigaScience 2026; github.com/Knowledge-Graph-Hub/kg-microbe release 2025-03-07,
BSD-3-Clause) vs Microbiome-CDM -- light checks only (KG-Microbe is about organism traits, not study findings).

1. Trait coverage: which genera / species of our catalogue findings carry at least one non-taxonomic edge in the
   KG-Microbe core merged graph (kg-microbe-core.tar.gz -> merged-kg_edges.tsv, streamed; subclass_of edges ignored).
2. Disbiome subset (disbiome.tar.gz; Disbiome = manually curated microbe-disease associations, elevated/reduced in
   disease): genus x condition direction concordance with our catalogue findings, with exactly the rules and code of
   minerva_compare.cells (associated_with_increased_likelihood_of = "positive"). Disbiome curation is human but its
   source papers may overlap ours (no PMIDs in the KG-Microbe edges), so this is concordance, not independent validation.
Inputs : outputs/scratch/competitors/kg_microbe/{raw,x_disbiome,x_ont}; CDM 3.1.0 read-only; NCBI taxonomy dumps.
Outputs: outputs/results/competitor_compare_2026-11-11/kg_microbe/{SUMMARY.json, REPORT.md, kg_cells.csv}
Written with Claude Code (declare).
"""
from __future__ import annotations

import csv
import sqlite3
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from _cstats import RESULTS, ROOT, SCRATCH, dump, wilson, write_manifest  # noqa: E402
import minerva_compare as MC  # noqa: E402

D = SCRATCH / "kg_microbe"
OUT = RESULTS / "kg_microbe"
DB310 = ROOT / "releases/cdm_v3/3.1.0/microbiome_cdm_v3.1.0.db"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    MC.OUT = OUT
    parent, rank, sci, genus = MC.BC.load_taxonomy()
    c = sqlite3.connect(f"file:{DB310}?mode=ro", uri=True)
    ours_taxa = set()
    for (x,) in c.execute("SELECT taxon_ncbi_ids FROM claim WHERE claim_source='catalogue_v3_1' AND taxon_ncbi_ids LIKE 'NCBITaxon:%'"):
        ours_taxa |= MC.BC.taxa_ids(x)
    our_gen = {genus(t) for t in ours_taxa if genus(t) in rank and rank[genus(t)] == "genus"}
    our_sp = {t for t in ours_taxa if rank.get(t) == "species"}
    # 1. trait coverage (stream edges from the nested tarball; nothing large is kept on disk)
    cmd = f"tar -xzOf '{D}/raw/kg-microbe-core.tar.gz' ./merged-kg.tar.gz | tar -xzO --wildcards '*merged-kg_edges.tsv'"
    with_trait = set()
    preds = defaultdict(int)
    p = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, text=True, bufsize=1 << 20)
    n = 0
    for line in p.stdout:
        n += 1
        f = line.split("\t", 5)          # id, subject, predicate, object, ...
        if len(f) < 4 or "subclass_of" in f[2] or f[0] == "id":
            continue
        for side in (f[1], f[3]):
            if side.startswith("NCBITaxon:"):
                try:
                    with_trait.add(int(side[10:]))
                except ValueError:
                    pass
        preds[f[2]] += 1
    p.wait()
    gen_trait = {genus(t) for t in with_trait if t in rank}

    def species_of(t):
        x, k = t, 0
        while x in parent and k < 40:
            if rank.get(x) == "species":
                return x
            if parent[x] == x:
                return None
            x, k = parent[x], k + 1
        return None
    sp_trait = {species_of(t) for t in with_trait if t in rank}
    summ = {"source": "github.com/Knowledge-Graph-Hub/kg-microbe releases/2025-03-07 (kg-microbe-core.tar.gz, disbiome.tar.gz, ontologies.tar.gz)",
            "licence": "BSD-3-Clause (repository); Disbiome content per Disbiome terms",
            "core_edges_streamed": n, "core_top_predicates": dict(sorted(preds.items(), key=lambda kv: -kv[1])[:10]),
            "trait_coverage": {"cdm_catalogue_genera": len(our_gen), "genera_with_kgmicrobe_trait_edges": wilson(len(our_gen & gen_trait), len(our_gen)),
                               "cdm_catalogue_species": len(our_sp), "species_with_kgmicrobe_trait_edges": wilson(len(our_sp & sp_trait), len(our_sp))}}
    # 2. Disbiome direction concordance
    mondo = {}
    with open(D / "x_ont/mondo_nodes.tsv", encoding="utf-8") as fh:
        for r in csv.DictReader(fh, delimiter="\t"):
            if r["id"].startswith("MONDO:"):
                mondo[r["id"]] = f"{r['name']} ; {r.get('synonym') or ''}"
    mv = defaultdict(lambda: [0, 0])
    n_e = n_used = 0
    with open(D / "x_disbiome/edges.tsv", encoding="utf-8") as fh:
        for r in csv.DictReader(fh, delimiter="\t"):
            n_e += 1
            if not r["subject"].startswith("NCBITaxon:"):
                continue
            t = int(r["subject"].split(":")[1])
            g = genus(t) if t in rank else None
            cs = MC.conditions(mondo.get(r["object"], ""))
            if g is None or rank.get(g) != "genus" or not cs:
                continue
            n_used += 1
            k = 0 if "increased" in r["predicate"] else 1
            for cc in cs:
                mv[(g, cc)][k] += 1
    pcond = {pid: MC.conditions(f"{t} {hc}") for pid, t, hc in
             c.execute("SELECT p.paper_id, p.title, s.health_conditions FROM paper p LEFT JOIN study s USING (paper_id)")}
    summ["disbiome_concordance"] = {"disbiome_edges": n_e, "edges_mapped_to_genus_and_condition": n_used, "disbiome_cells": len(mv),
                                    "rule": "same as minerva_compare: CDM net direction; Disbiome >= 3 edges with >= 2/3 one direction",
                                    **{lvl: MC.cells(c, lvl, pcond, mv, rank, sci, genus) for lvl in ("finding_level", "paper_level")}}
    dump(summ, OUT / "SUMMARY.json")
    write_manifest(D / "raw", "https://github.com/Knowledge-Graph-Hub/kg-microbe/releases/tag/2025-03-07", "BSD-3-Clause", "2025-03-07")
    import json
    print(json.dumps(summ, indent=1)[:3500])


if __name__ == "__main__":
    main()
