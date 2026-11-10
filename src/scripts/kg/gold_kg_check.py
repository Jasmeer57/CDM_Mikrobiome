"""Reference-KG check of the CDM triple KG (rules: gold_kg_schema.json, pre-registered).

    python gold_kg_check.py preregister
    python gold_kg_check.py run          # normally: sbatch gold_kg_check.sbatch (after the evidence check)
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = next(p for p in HERE.parents if (p / ".cdm_root").is_file())
sys.path.insert(0, str(ROOT / "src/scripts/bugsigdb_comparison"))
import compare as BC  # noqa: E402  (taxonomy, BugSigDB loader, wilson, sha256)

SCHEMA = json.loads((HERE / "gold_kg_schema.json").read_text())
KG = ROOT / "outputs/results/kg_2026-11-04"
OUT = KG / "gold_kg_check"
GENE_T = {"PROTEIN", "DNA_RNA", "GENOMICS"}
EDGE_TYPES = {"microbe_disease": ({"ORGANISM"}, {"DISEASE"}), "chemical_disease": ({"CHEMICAL"}, {"DISEASE"}),
              "gene_disease": (GENE_T, {"DISEASE"}), "chemical_gene": ({"CHEMICAL"}, GENE_T)}


def low(s):
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def ctd_vocab(path, id_col, name_cols, keep=None):
    out = defaultdict(set)
    header = None
    with gzip.open(ROOT / path, "rt", encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("# Fields"):
                continue
            if line.startswith("#"):
                if header is None and "\t" in line:
                    header = line[2:].rstrip("\n").split("\t")
                continue
            r = dict(zip(header, line.rstrip("\n").split("\t")))
            for col in name_cols:
                for n in (r.get(col) or "").split("|"):
                    n = low(n)
                    if n and (keep is None or n in keep):
                        out[n].add(r[id_col].replace("MESH:", ""))
    return out


def rate(xs, ok):
    n, k = len(xs), sum(1 for x in xs if ok(x))
    return {"n": n, "k": k, "rate": round(k / n, 4) if n else None, "wilson": BC.wilson(k, n)}


def newcombe(a, b):
    if not a["n"] or not b["n"]:
        return None
    p1, p2 = a["rate"], b["rate"]
    (l1, u1), (l2, u2) = a["wilson"], b["wilson"]
    d = p1 - p2
    return [round(d - ((p1 - l1) ** 2 + (u2 - p2) ** 2) ** 0.5, 4), round(d + ((u1 - p1) ** 2 + (p2 - l2) ** 2) ** 0.5, 4)]


def cmd_preregister():
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "PREREGISTRATION.sha256").write_text(f"{BC.sha256(HERE / 'gold_kg_schema.json')}  gold_kg_schema.json\n")
    print((OUT / "PREREGISTRATION.sha256").read_text())


def cmd_run():
    h, f = (OUT / "PREREGISTRATION.sha256").read_text().split()
    if BC.sha256(HERE / f) != h:
        sys.exit("gold_kg_schema.json changed after pre-registration")
    with gzip.open(KG / "nodes.csv.gz", "rt", encoding="utf-8") as fh:
        nodes = {r["node_id"]: r for r in csv.DictReader(fh)}
    with gzip.open(KG / "edges.csv.gz", "rt", encoding="utf-8") as fh:
        edges = list(csv.DictReader(fh))
    ev = {}
    evp = KG / "evidence_check/evidence_verdicts.csv.gz"
    if evp.exists():
        with gzip.open(evp, "rt", encoding="utf-8") as fh:
            ev = {r["canonical_triple_id"]: r["A"] for r in csv.DictReader(fh)}
    ntype = lambda n: (nodes[n]["type_cleaned"] or nodes[n]["cdm_type"]) if n in nodes else ""

    # reference vocabularies
    parent, rank, tname, genus = BC.load_taxonomy()
    labels = {low(n["label"]) for n in nodes.values()}
    tax_by_name = defaultdict(set)
    with open(ROOT / "data/reference_kg/raw/names.dmp", encoding="utf-8") as fh:
        for line in fh:
            x = line.split("\t|\t")
            if low(x[1]) in labels:
                tax_by_name[low(x[1])].add(int(x[0]))
    dis_by_name = ctd_vocab("data/reference_kg/raw/CTD_diseases.tsv.gz", "DiseaseID", ["DiseaseName", "Synonyms"])
    chem_by_name = ctd_vocab("data/reference_kg/raw/CTD_chemicals.tsv.gz", "ChemicalID", ["ChemicalName", "MESHSynonyms", "CTDCuratedSynonyms"], labels)
    gene_by_sym = defaultdict(set)
    with gzip.open(ROOT / "data/reference_kg/raw/Homo_sapiens.gene_info.gz", "rt", encoding="utf-8") as fh:
        for line in fh:
            if not line.startswith("#"):
                x = line.split("\t")
                for sym in [x[2]] + (x[4].split("|") if x[4] != "-" else []):
                    if len(sym) >= 3:
                        gene_by_sym[sym.upper()].add(x[1])
    print("vocabularies loaded", flush=True)

    def disease_keys(name, onto=""):
        keys = {"N:" + low(name)}
        m = re.search(r"(?:MESH/|^)([CD]\d{6,9})$", onto or "")
        if m:
            keys.add(m.group(1))
        ids = dis_by_name.get(low(name), set())
        if len(ids) == 1:
            keys |= ids
        return keys

    def resolve(n, kind):
        node = nodes.get(n)
        if not node:
            return None, None
        lab, onto = node["label"], node["ontology_id"] or ""
        if kind == "taxon":
            if onto.startswith("NCBITaxon:"):
                return int(onto.split(":")[1]), "cdm_mapping"
            ids = tax_by_name.get(low(lab), set())
            return (next(iter(ids)), "name_match") if len(ids) == 1 else (None, None)
        if kind == "disease":
            k = disease_keys(lab, onto)
            return (frozenset(k), "cdm_mapping" if any(not x.startswith("N:") for x in k) else "name_only")
        if kind == "chemical":
            m = re.search(r"(?:MESH/|^)([CD]\d{6,9})$", onto)
            if m:
                return m.group(1), "cdm_mapping"
            ids = chem_by_name.get(low(lab), set())
            return (next(iter(ids)), "name_match") if len(ids) == 1 else (None, None)
        ids = gene_by_sym.get((lab or "").strip().upper(), set())
        return (next(iter(ids)), "name_match") if len(ids) == 1 else (None, None)

    # reference pairs
    md = defaultdict(set)   # source -> {(genus or taxon, disease key)}
    for r in json.load(open(ROOT / SCHEMA["references"]["disbiome"]["path"])):
        if (r.get("host_type") or "Human") != "Human" or not r.get("organism_ncbi_id"):
            continue
        t = int(r["organism_ncbi_id"])
        for k in disease_keys(r.get("disease_name") or ""):
            md["disbiome"].add((t, k))
            md["disbiome"].add((genus(t), k))
    _, rows = BC.load_bugsigdb()
    for r in rows:
        if r["Abundance in Group 1"] not in ("increased", "decreased"):
            continue
        dk = disease_keys(r.get("Condition") or "")
        for lin in (r["NCBI Taxonomy IDs"] or "").split(";"):
            leaf = lin.split("|")[-1].strip()
            if leaf.isdigit():
                t = int(leaf)
                for k in dk:
                    md["bugsigdb"].add((t, k))
                    md["bugsigdb"].add((genus(t), k))
    cd_any, cd_cur = set(), set()
    with gzip.open(ROOT / SCHEMA["references"]["ctd_chemical_disease"]["path"], "rt", encoding="utf-8") as fh:
        for line in fh:
            if not line.startswith("#"):
                x = line.split("\t", 6)
                p = (x[1], x[4].replace("MESH:", ""))
                cd_any.add(p)
                if x[5].strip():
                    cd_cur.add(p)
    gd = set()
    with gzip.open(ROOT / SCHEMA["references"]["ctd_gene_disease"]["path"], "rt", encoding="utf-8") as fh:
        for line in fh:
            if not line.startswith("#"):
                x = line.split("\t")
                gd.add((x[1], x[3].replace("MESH:", "")))
    cg = set()
    with gzip.open(ROOT / SCHEMA["references"]["ctd_chemical_gene"]["path"], "rt", encoding="utf-8") as fh:
        for line in fh:
            if not line.startswith("#"):
                x = line.split("\t", 6)
                cg.add((x[1], x[4]))
    print("references loaded", {k: len(v) for k, v in md.items()}, len(cd_any), len(gd), len(cg), flush=True)

    def support(et, a, b):
        """Return set of references supporting the pair (a, b); a/b already resolved for edge type et."""
        hits = set()
        if et == "microbe_disease":
            for src, pairs in md.items():
                if any((a, k) in pairs or (genus(a), k) in pairs for k in b):
                    hits.add(src)
        elif et == "chemical_disease":
            ks = [k for k in b if not k.startswith("N:")]
            if any((a, k) in cd_cur for k in ks):
                hits.add("ctd_curated")
            if any((a, k) in cd_any for k in ks):
                hits.add("ctd_any")
        elif et == "gene_disease":
            if any((a, k) in gd for k in b if not k.startswith("N:")):
                hits.add("ctd_curated")
        elif et == "chemical_gene":
            if (a, b) in cg:
                hits.add("ctd_chem_gene")
        return hits

    kinds = {"microbe_disease": ("taxon", "disease"), "chemical_disease": ("chemical", "disease"),
             "gene_disease": ("gene", "disease"), "chemical_gene": ("chemical", "gene")}
    items, sides = [], defaultdict(lambda: (set(), set()))
    for e in edges:
        ts, to = ntype(e["subject"]), ntype(e["object"])
        for et, (A, Bt) in EDGE_TYPES.items():
            if ts in A and to in Bt:
                na, nb = e["subject"], e["object"]
            elif to in A and ts in Bt:
                na, nb = e["object"], e["subject"]
            else:
                continue
            ka, kb = kinds[et]
            a, ma = resolve(na, ka)
            b, mb = resolve(nb, kb)
            if a is None or b is None:
                break
            hits = support(et, a, b)
            items.append({"triple_id": e["triple_id"], "edge_type": et, "kept": e["kept_by_cleaning"] == "1",
                          "evidence_A": ev.get(e["triple_id"], ""), "support": sorted(hits), "methods": f"{ma}+{mb}",
                          "subject": e["subject_label"], "relation": e["relation"], "object": e["object_label"]})
            sides[et][0].add(a)
            sides[et][1].add(b)
            break
    # chance: all cross pairs within each edge type
    chance = {}
    for et, (sa, sb) in sides.items():
        sa, sb = list(sa), list(sb)
        n = k = 0
        for a in sa:
            for b in sb:
                n += 1
                k += bool(support(et, a, b))
        chance[et] = round(k / n, 4) if n else None
    sup = lambda x: bool(x["support"])
    res = {}
    for et in EDGE_TYPES:
        xs = [x for x in items if x["edge_type"] == et]
        kept, dropped = [x for x in xs if x["kept"]], [x for x in xs if not x["kept"]]
        evy = [x for x in xs if x["evidence_A"] == "Y"]
        evn = [x for x in xs if x["evidence_A"] in ("N", "P", "R")]
        r = {"resolved_edges": len(xs), "support": rate(xs, sup), "chance": chance.get(et),
             "kept": rate(kept, sup), "dropped": rate(dropped, sup), "kept_vs_dropped": newcombe(rate(kept, sup), rate(dropped, sup)),
             "evidence_supported": rate(evy, sup), "evidence_not_supported": rate(evn, sup),
             "evidence_diff": newcombe(rate(evy, sup), rate(evn, sup)),
             "by_reference": dict(Counter(s for x in xs for s in x["support"])),
             "methods": dict(Counter(x["methods"] for x in xs))}
        res[et] = r
        print(et, json.dumps(r)[:400], flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    with gzip.open(OUT / "edge_support.csv.gz", "wt", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(items[0]))
        w.writeheader()
        for x in items:
            w.writerow({**x, "support": "|".join(x["support"])})
    (OUT / "summary.json").write_text(json.dumps({"edge_types": res, "evidence_check_available": bool(ev),
                                                  "code_sha256": BC.sha256(Path(__file__).resolve())}, indent=1))
    chance_txt = lambda c: "–" if c is None else f"{100 * c:.1f}%"
    pct = lambda d: "–" if not d or not d["n"] else f"{100 * d['rate']:.1f}% ({d['k']}/{d['n']})"
    ci = lambda x: "–" if not x else f"{100 * x[0]:+.1f} to {100 * x[1]:+.1f}"
    L = ["# KG edges against curated knowledge graphs", "",
         "*Pre-registered in `src/scripts/kg/gold_kg_schema.json`. Support = the pair is known in a reference (Disbiome, BugSigDB, CTD), "
         "independent of the source paper. Absence is not error.*", "",
         "| Edge type | Resolved edges | In a reference | Chance | Kept by cleaning | Dropped | Kept − dropped (95% CI, points) | Sentence supports label | Sentence does not | Difference (95% CI) |",
         "|---|---:|---:|---:|---:|---:|---|---:|---:|---|"]
    for et, r in res.items():
        L.append(f"| {et.replace('_', '–')} | {r['resolved_edges']} | {pct(r['support'])} | "
                 f"{chance_txt(r['chance'])} | {pct(r['kept'])} | {pct(r['dropped'])} | "
                 f"{ci(r['kept_vs_dropped'])} | {pct(r['evidence_supported'])} | {pct(r['evidence_not_supported'])} | {ci(r['evidence_diff'])} |")
    L += ["", "Support by reference: " + "; ".join(f"{et}: {r['by_reference']}" for et, r in res.items()), "",
          "Resolution methods: " + "; ".join(f"{et}: {r['methods']}" for et, r in res.items())]
    (OUT / "REPORT.md").write_text("\n".join(L) + "\n")
    files = sorted(p for p in OUT.iterdir() if p.is_file() and p.name != "MANIFEST.sha256")
    (OUT / "MANIFEST.sha256").write_text("".join(f"{BC.sha256(p)}  {p.name}\n" for p in files))
    print("\n".join(L))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["preregister", "run"])
    cmd_preregister() if ap.parse_args().cmd == "preregister" else cmd_run()
