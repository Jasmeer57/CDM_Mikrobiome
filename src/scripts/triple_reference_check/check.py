"""Reference check of the CDM 3.0.3 triple layer, as frozen and as cleaned by DeepSeek, against BugSigDB and CTD.

Rules are pre-registered in scoring_schema.json; one record per checked item (answer_template.schema.json) in
items.jsonl. The CDM is opened read-only; absence from a reference is NOT_IN_REFERENCE, never an error.

    python check.py preregister    # before the run
    python check.py run            # normally: sbatch src/scripts/triple_reference_check/check.sbatch
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import random
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "bugsigdb_comparison"))
import compare as B  # noqa: E402  (shared loaders: BugSigDB, taxonomy, wilson, bootstrap, sha256)

SCHEMA = json.loads((HERE / "scoring_schema.json").read_text())
TEMPLATE = json.loads((HERE / "answer_template.schema.json").read_text())
OUT = ROOT / "outputs/results/benchmark/triple_reference_check_2026-11-03"
CHK = SCHEMA["checks"]
UP, DOWN = set(CHK["bugsigdb_direction"]["up"]), set(CHK["bugsigdb_direction"]["down"])
GENE_TYPES = {"PROTEIN", "DNA_RNA", "GENOMICS"}


def low(s):
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def newcombe(k1, n1, k2, n2):
    """95% hybrid-score interval for p1 - p2 (Newcombe 1998, method 10)."""
    if not n1 or not n2:
        return None
    p1, p2 = k1 / n1, k2 / n2
    l1, u1 = B.wilson(k1, n1)
    l2, u2 = B.wilson(k2, n2)
    d = p1 - p2
    return [round(d - ((p1 - l1) ** 2 + (u2 - p2) ** 2) ** 0.5, 4), round(d + ((u1 - p1) ** 2 + (p2 - l2) ** 2) ** 0.5, 4)]


def rate(items, ok):
    n = len(items)
    k = sum(1 for i in items if ok(i))
    return {"n": n, "k": k, "rate": round(k / n, 4) if n else None, "wilson": B.wilson(k, n)}


def cmd_preregister():
    OUT.mkdir(parents=True, exist_ok=True)
    lines = [f"{B.sha256(HERE / f)}  {f}" for f in ("scoring_schema.json", "answer_template.schema.json")]
    (OUT / "PREREGISTRATION.sha256").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


def cmd_run():
    for line in (OUT / "PREREGISTRATION.sha256").read_text().splitlines():
        h, f = line.split()
        if B.sha256(HERE / f) != h:
            sys.exit(f"{f} changed after pre-registration")
    for k, v in SCHEMA["inputs"].items():
        if B.sha256(ROOT / v["path"]) != v["sha256"]:
            sys.exit(f"input {k} does not match the registered sha256")
    print("pre-registration and input hashes verified", flush=True)
    rng = random.Random(SCHEMA["uncertainty"]["bootstrap"]["seed"])
    c = sqlite3.connect(f"file:{ROOT / SCHEMA['inputs']['cdm']['path']}?mode=ro", uri=True)
    q = lambda sql, *a: c.execute(sql, a).fetchall()

    # ---------------- triples, types, cleaning
    ctype = dict(q("SELECT term_id, cdm_type FROM canonical_term"))
    triples = []
    for tid, s, rel, o, st, ot, pids in q("SELECT canonical_triple_id, subject_display_label, relation_normalized, "
                                          "object_display_label, subject_term_id, object_term_id, paper_ids FROM relation"):
        triples.append({"id": tid, "s": s or "", "rel": rel, "o": o or "", "st": st, "ot": ot,
                        "stype": ctype.get(st), "otype": ctype.get(ot), "papers": json.loads(pids or "[]")})
    with gzip.open(ROOT / SCHEMA["inputs"]["cleaned_triples"]["path"], "rt", encoding="utf-8") as fh:
        cleaned = {r["canonical_triple_id"]: {"kept": r["kept"] == "1", "relation": r["relation_cleaned"] if r["kept"] == "1" else None,
                                               "swapped": r["direction_swapped"] == "1"} for r in csv.DictReader(fh)}
    print(len(triples), "triples;", sum(v["kept"] for v in cleaned.values()), "kept by cleaning", flush=True)

    # ---------------- CDM mappings per term
    mapped = defaultdict(lambda: defaultdict(set))  # term -> kind -> ids
    for term, cid, disp, rev, canon in q("SELECT term_id, concept_id, mapping_disposition, mapping_disposition_reviewed, "
                                         "is_canonical_candidate FROM term_concept_map"):
        if not (rev == "ACCEPTED" or (canon == 1 and disp != "REJECTED" and rev not in ("REJECTED", "REMOVED"))):
            continue
        cid = cid or ""
        if cid.startswith("NCBITaxon:"):
            mapped[term]["taxon"].add(int(cid.split(":")[1]))
        m = re.search(r"(?:MESH/|^)([CD]\d{6,9})$", cid)
        if m:
            mapped[term]["mesh"].add(m.group(1))

    # ---------------- reference vocabularies (only names we need)
    names_needed = {low(t["s"]) for t in triples} | {low(t["o"]) for t in triples}
    parent, rank, tname, genus = B.load_taxonomy()
    tax_by_name = defaultdict(set)
    with open(ROOT / SCHEMA["inputs"]["ncbi_taxonomy_names"]["path"], encoding="utf-8") as fh:
        for line in fh:
            f = line.split("\t|\t")
            n = low(f[1])
            if n in names_needed:
                tax_by_name[n].add(int(f[0]))

    def vocab(path, id_col, name_cols, prefix=""):
        out = defaultdict(set)
        with gzip.open(ROOT / path, "rt", encoding="utf-8") as fh:
            header = None
            for line in fh:
                if line.startswith("# Fields"):
                    continue
                if line.startswith("#"):
                    if header is None and "\t" in line:
                        header = line[2:].rstrip("\n").split("\t")
                    continue
                r = dict(zip(header, line.rstrip("\n").split("\t")))
                ident = r[id_col]
                for col in name_cols:
                    for n in (r.get(col) or "").split("|"):
                        n = low(n)
                        if n in names_needed:
                            out[n].add(ident.replace("MESH:", ""))
        return out
    chem_by_name = vocab(SCHEMA["inputs"]["ctd_chemicals"]["path"], "ChemicalID", ["ChemicalName", "MESHSynonyms", "CTDCuratedSynonyms"])
    dis_by_name = vocab(SCHEMA["inputs"]["ctd_diseases"]["path"], "DiseaseID", ["DiseaseName", "Synonyms"])
    gene_by_sym = defaultdict(set)
    with gzip.open(ROOT / SCHEMA["inputs"]["human_gene_info"]["path"], "rt", encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("#"):
                continue
            f = line.split("\t")
            for sym in [f[2]] + (f[4].split("|") if f[4] != "-" else []):
                if len(sym) >= 3:
                    gene_by_sym[sym.upper()].add(f[1])
    print("vocabularies loaded", flush=True)

    def resolve(term, label, kind):
        if kind == "taxon" and mapped[term]["taxon"]:
            ids = mapped[term]["taxon"]
            return (str(next(iter(ids))), "cdm_mapping") if len(ids) == 1 else (None, None)
        if kind in ("chemical", "disease") and mapped[term]["mesh"]:
            ids = mapped[term]["mesh"]
            return (next(iter(ids)), "cdm_mapping") if len(ids) == 1 else (None, None)
        pool = {"taxon": tax_by_name, "chemical": chem_by_name, "disease": dis_by_name}.get(kind)
        ids = pool.get(low(label), set()) if pool is not None else gene_by_sym.get((label or "").strip().upper(), set())
        return (str(next(iter(ids))), "name_match") if len(ids) == 1 else (None, None)

    items = []

    def rec(check, t, pid, ids, methods, verdict, direction=None):
        cl = cleaned.get(t["id"], {"kept": False, "relation": None, "swapped": False})
        items.append({"item_id": f"{check}:{len(items):06d}", "check": check, "triple_id": t["id"], "paper_id": pid,
                      "subject": t["s"][:300], "relation": t["rel"], "object": t["o"][:300], "ids": ids, "link_methods": methods,
                      "verdict": verdict, "direction": direction, "cleaned": cl})

    # ---------------- BugSigDB
    _, rows = B.load_bugsigdb()
    by_pmid = {str(p): i for i, p in q("SELECT paper_id, pmid FROM paper WHERE pmid IS NOT NULL AND pmid != ''")}
    by_doi = {d.lower().strip(): i for i, d in q("SELECT paper_id, doi FROM paper WHERE doi IS NOT NULL AND doi != ''")}
    bdir = defaultdict(lambda: defaultdict(set))
    for r in rows:
        pm = (r.get("PMID") or "").split(".")[0]
        pid = (by_pmid.get(pm) if pm else None) or by_doi.get((r.get("DOI") or "").lower().strip())
        d = {"increased": "up", "decreased": "down"}.get(r["Abundance in Group 1"])
        if not pid or not d:
            continue
        for lin in (r["NCBI Taxonomy IDs"] or "").split(";"):
            leaf = lin.split("|")[-1].strip()
            if leaf.isdigit():
                bdir[pid][int(leaf)].add(d)
    overlap = sorted(bdir)
    bgen = {p: defaultdict(set) for p in overlap}
    for p in overlap:
        for t, ds in bdir[p].items():
            bgen[p][genus(t)] |= ds

    def bverdict(tax, pid):
        if tax in bdir[pid]:
            return "MATCH", bdir[pid][tax]
        g = genus(tax)
        return ("PARTIAL", bgen[pid][g]) if g in bgen[pid] else ("NOT_IN_REFERENCE", set())

    def dir_of(rel):
        return "up" if rel in UP else "down" if rel in DOWN else None

    def agree(rel, ds):
        d = dir_of(rel)
        if d is None or len(ds) != 1:
            return "UNDETERMINED"
        return "SAME" if d in ds else "OPPOSITE"

    bs_items, chance_k, chance_n = [], 0, 0
    for t in triples:
        side = "s" if t["stype"] == "ORGANISM" else "o" if t["otype"] == "ORGANISM" else None
        if not side:
            continue
        tax, how = resolve(t["st" if side == "s" else "ot"], t[side], "taxon")
        if tax is None:
            continue
        tax = int(tax)
        for pid in t["papers"]:
            if pid not in bdir:
                continue
            v, ds = bverdict(tax, pid)
            direction = None
            if v != "NOT_IN_REFERENCE" and side == "s" and dir_of(t["rel"]):
                cl = cleaned.get(t["id"], {})
                dc = None
                if cl.get("kept"):
                    dc = "UNDETERMINED" if cl["swapped"] else agree(cl["relation"], ds)
                direction = {"original": agree(t["rel"], ds), "cleaned": dc}
            rec("bugsigdb_taxon", t, pid, [f"NCBITaxon:{tax}"], [how], v, direction)
            bs_items.append(items[-1])
            for o in overlap:
                if o != pid:
                    chance_n += 1
                    chance_k += bverdict(tax, o)[0] != "NOT_IN_REFERENCE"

    # ---------------- CTD
    chem_dis, gene_dis = [], []
    for t in triples:
        types = (t["stype"], t["otype"])
        if "CHEMICAL" in types and "DISEASE" in types and types[0] != types[1]:
            ci, di = (0, 1) if types[0] == "CHEMICAL" else (1, 0)
            sides = [("st", "s"), ("ot", "o")]
            chem = resolve(t[sides[ci][0]], t[sides[ci][1]], "chemical")
            dis = resolve(t[sides[di][0]], t[sides[di][1]], "disease")
            if chem[0] and dis[0]:
                chem_dis.append((t, chem, dis))
        elif "DISEASE" in types and (types[0] in GENE_TYPES or types[1] in GENE_TYPES):
            gi, di = (0, 1) if types[0] in GENE_TYPES else (1, 0)
            sides = [("st", "s"), ("ot", "o")]
            gene = resolve(None, t[sides[gi][1]], "gene")
            dis = resolve(t[sides[di][0]], t[sides[di][1]], "disease")
            if gene[0] and dis[0]:
                gene_dis.append((t, gene, dis))
    chems = {x[1][0] for x in chem_dis}
    diss = {x[2][0] for x in chem_dis} | {x[2][0] for x in gene_dis}
    genes = {x[1][0] for x in gene_dis}
    ctd_cd = {}
    with gzip.open(ROOT / SCHEMA["inputs"]["ctd_chemicals_diseases"]["path"], "rt", encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("#"):
                continue
            f = line.split("\t", 6)
            if f[1] in chems:
                d = f[4].replace("MESH:", "")
                if d in diss:
                    ctd_cd[(f[1], d)] = ctd_cd.get((f[1], d), False) or bool(f[5].strip())
    ctd_cd = {k: ("CURATED" if v is True else "INFERRED_ONLY") for k, v in ctd_cd.items()}
    ctd_gd = set()
    with gzip.open(ROOT / SCHEMA["inputs"]["ctd_genes_diseases"]["path"], "rt", encoding="utf-8") as fh:
        for line in fh:
            if not line.startswith("#"):
                f = line.split("\t")
                ctd_gd.add((f[1], f[3].replace("MESH:", "")))
    for t, chem, dis in chem_dis:
        rec("ctd_chemical_disease", t, None, [chem[0], dis[0]], [chem[1], dis[1]], ctd_cd.get((chem[0], dis[0]), "NOT_IN_REFERENCE"))
    for t, gene, dis in gene_dis:
        rec("ctd_gene_disease", t, None, [gene[0], dis[0]], [gene[1], dis[1]],
            "CURATED" if (gene[0], dis[0]) in ctd_gd else "NOT_IN_REFERENCE")
    cd_cross = [(a, b) for a in chems for b in {x[2][0] for x in chem_dis}]
    gd_cross = [(a, b) for a in genes for b in {x[2][0] for x in gene_dis}]

    # ---------------- validate and summarise
    import jsonschema
    val = jsonschema.Draft202012Validator(TEMPLATE)
    bad = [(i["item_id"], e.message) for i in items for e in val.iter_errors(i)]
    if bad:
        sys.exit(f"{len(bad)} records violate the answer template, e.g. {bad[:3]}")

    def strata(its, ok):
        return {"all": rate(its, ok), "kept": rate([i for i in its if i["cleaned"]["kept"]], ok),
                "dropped": rate([i for i in its if not i["cleaned"]["kept"]], ok)}

    def effect(st):
        k, d = st["kept"], st["dropped"]
        return {"kept_minus_dropped": round(k["rate"] - d["rate"], 4) if k["n"] and d["n"] else None,
                "newcombe": newcombe(k["k"], k["n"], d["k"], d["n"])}

    sup = lambda i: i["verdict"] != "NOT_IN_REFERENCE"
    bs = strata(bs_items, sup)
    det_o = [i for i in bs_items if i["direction"] and i["direction"]["original"] != "UNDETERMINED"]
    det_pair = [i for i in bs_items if i["direction"] and i["cleaned"]["kept"]
                and i["direction"]["original"] != "UNDETERMINED" and i["direction"]["cleaned"] not in (None, "UNDETERMINED")]
    overlap_with_items = sorted({i["paper_id"] for i in bs_items})
    cd_items = [i for i in items if i["check"] == "ctd_chemical_disease"]
    gd_items = [i for i in items if i["check"] == "ctd_gene_disease"]
    summary = {
        "protocol": "scoring_schema.json v" + SCHEMA["version"], "triples": len(triples),
        "kept_by_cleaning": sum(v["kept"] for v in cleaned.values()),
        "bugsigdb": {
            "overlap_papers": len(overlap), "papers_with_items": len(overlap_with_items),
            "items": len(bs_items), "verdicts": dict(Counter(i["verdict"] for i in bs_items)),
            "link_methods": dict(Counter(i["link_methods"][0] for i in bs_items)),
            "support": bs, "support_effect": effect(bs),
            "support_bootstrap": B.boot(bs_items, sup, overlap_with_items, rng),
            "support_chance": round(chance_k / chance_n, 4) if chance_n else None,
            "direction_original": rate(det_o, lambda i: i["direction"]["original"] == "SAME"),
            "direction_original_chance": None,
            "direction_pairs_original_vs_cleaned": {
                "n": len(det_pair),
                "original_same": rate(det_pair, lambda i: i["direction"]["original"] == "SAME"),
                "cleaned_same": rate(det_pair, lambda i: i["direction"]["cleaned"] == "SAME")},
        },
        "ctd_chemical_disease": {
            "items": len(cd_items), "verdicts": dict(Counter(i["verdict"] for i in cd_items)),
            "link_methods": dict(Counter("+".join(i["link_methods"]) for i in cd_items)),
            "any_support": strata(cd_items, sup), "any_support_effect": effect(strata(cd_items, sup)),
            "curated": strata(cd_items, lambda i: i["verdict"] == "CURATED"),
            "chance_any": round(sum(1 for p in cd_cross if p in ctd_cd) / len(cd_cross), 4) if cd_cross else None,
            "chance_curated": round(sum(1 for p in cd_cross if ctd_cd.get(p) == "CURATED") / len(cd_cross), 4) if cd_cross else None},
        "ctd_gene_disease": {
            "items": len(gd_items), "verdicts": dict(Counter(i["verdict"] for i in gd_items)),
            "curated": strata(gd_items, sup), "curated_effect": effect(strata(gd_items, sup)),
            "chance": round(sum(1 for p in gd_cross if p in ctd_gd) / len(gd_cross), 4) if gd_cross else None},
        "code_sha256": B.sha256(Path(__file__).resolve()),
    }
    # base-rate chance for direction agreement (BugSigDB direction vs our relation direction)
    if det_o:
        ours = Counter(dir_of(i["relation"]) for i in det_o)
        same = sum(i["direction"]["original"] == "SAME" for i in det_o)
        refs = Counter()
        for i in det_o:
            od = dir_of(i["relation"])
            refs[od if i["direction"]["original"] == "SAME" else ("down" if od == "up" else "up")] += 1
        n = len(det_o)
        summary["bugsigdb"]["direction_original_chance"] = round(sum(ours[d] * refs[d] for d in ("up", "down")) / (n * n), 4)
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "items.jsonl", "w", encoding="utf-8") as fh:
        for i in items:
            fh.write(json.dumps(i, ensure_ascii=False) + "\n")
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2))
    write_report(summary)
    files = sorted(p for p in OUT.iterdir() if p.is_file() and p.name != "MANIFEST.sha256")
    (OUT / "MANIFEST.sha256").write_text("".join(f"{B.sha256(p)}  {p.name}\n" for p in files))
    print(json.dumps(summary, indent=1)[:4000])


def write_report(s):
    pct = lambda x: "–" if x is None else f"{100 * x:.1f}%"
    ci = lambda x: "–" if not x else f"{100 * x[0]:.1f}–{100 * x[1]:.1f}"
    r = lambda d: f"{pct(d['rate'])} ({d['k']}/{d['n']}; {ci(d['wilson'])})"
    b, cd, gd = s["bugsigdb"], s["ctd_chemical_disease"], s["ctd_gene_disease"]
    def eff(e):
        d = "–" if e["kept_minus_dropped"] is None else f"{100 * e['kept_minus_dropped']:+.1f} points"
        return f"{d} (95% CI {ci(e['newcombe'])})"
    L = ["# Reference check of the triple layer (BugSigDB, CTD)", "",
         "*CDM 3.0.3 triples (frozen) and the DeepSeek-cleaned layer, against BugSigDB (human-curated) and CTD. Protocol "
         "pre-registered in `src/scripts/triple_reference_check/scoring_schema.json` (hash in `PREREGISTRATION.sha256`); "
         "one record per item in `items.jsonl`, validated against `answer_template.schema.json`.*", "",
         "Support by a reference, not accuracy: a triple absent from BugSigDB or CTD is not counted as wrong, and CTD support "
         "shows that an association is known, not that the paper stated it.", "",
         f"Triples: {s['triples']:,}; kept by the DeepSeek cleaning: {s['kept_by_cleaning']:,}.", "",
         "## Microbial taxa against BugSigDB (same paper)", "",
         f"(triple, paper) items: {b['items']} on {b['papers_with_items']} of {b['overlap_papers']} overlap papers; "
         f"taxon resolved via {b['link_methods']}.", "",
         "| Stratum | Taxon in BugSigDB signatures of the same paper (exact or genus) |", "|---|---:|",
         f"| All triples | {r(b['support']['all'])} |", f"| Kept by cleaning | {r(b['support']['kept'])} |",
         f"| Dropped by cleaning | {r(b['support']['dropped'])} |", "",
         f"Paper bootstrap (all): {ci(b['support_bootstrap'])}. Chance (other papers' signatures): {pct(b['support_chance'])}. "
         f"Kept minus dropped: {eff(b['support_effect'])}.", "",
         f"Direction (taxon as subject, directional relation, determinable): same direction {r(b['direction_original'])}; "
         f"base-rate chance {pct(b['direction_original_chance'])}.", "",
         f"Same kept pairs, original vs cleaned relation (n={b['direction_pairs_original_vs_cleaned']['n']}): original "
         f"{r(b['direction_pairs_original_vs_cleaned']['original_same'])}, cleaned {r(b['direction_pairs_original_vs_cleaned']['cleaned_same'])}.", "",
         "## Chemical–disease triples against CTD", "",
         f"Items: {cd['items']}; verdicts {cd['verdicts']}; identifiers via {cd['link_methods']}.", "",
         "| Stratum | Any CTD support | Curated (direct evidence) |", "|---|---:|---:|",
         *[f"| {k} | {r(cd['any_support'][k])} | {r(cd['curated'][k])} |" for k in ("all", "kept", "dropped")], "",
         f"Chance (all cross pairs): any {pct(cd['chance_any'])}, curated {pct(cd['chance_curated'])}. "
         f"Kept minus dropped (any support): {eff(cd['any_support_effect'])}.", "",
         "## Gene–disease triples against CTD (curated)", "",
         f"Items: {gd['items']}; verdicts {gd['verdicts']}.", "",
         "| Stratum | Curated in CTD |", "|---|---:|",
         *[f"| {k} | {r(gd['curated'][k])} |" for k in ("all", "kept", "dropped")], "",
         f"Chance (all cross pairs): {pct(gd['chance'])}. Kept minus dropped: {eff(gd['curated_effect'])}."]
    (OUT / "REPORT.md").write_text("\n".join(L) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["preregister", "run"])
    a = ap.parse_args()
    cmd_preregister() if a.cmd == "preregister" else cmd_run()


if __name__ == "__main__":
    main()
