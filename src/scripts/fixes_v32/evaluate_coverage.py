"""BugSigDB taxon coverage by signature source: catalogue_v3_1 vs catalogue_v3_1 + 3.2.0-candidate block tier.

Re-uses src/scripts/bugsigdb_comparison/compare.py (inputs, hash checks, paper matching, taxonomy lift, verdicts,
Wilson / paper-bootstrap intervals, cross-paper chance baseline, direction map, source classes) unchanged; the only
difference is the set of "our" findings. The old arm must reproduce the frozen summary.json exactly (asserted).

    python src/scripts/fixes_v32/evaluate_coverage.py
"""
from __future__ import annotations

import csv
import json
import random
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
sys.path.insert(0, str(ROOT / "src/scripts/bugsigdb_comparison"))
import compare as C  # noqa: E402

OUT = ROOT / "outputs/results/catalogue_tables_captions_v32_2026-11-11"
FROZEN = ROOT / "outputs/results/benchmark/bugsigdb_comparison_2026-11-03/summary.json"
HIT = ("MATCH", "PARTIAL")


def main():
    for key in ("cdm", "bugsigdb", "ncbi_taxonomy_nodes", "ncbi_taxonomy_names"):
        assert C.sha256(ROOT / C.SCHEMA["inputs"][key]["path"]) == C.SCHEMA["inputs"][key]["sha256"], key
    c = sqlite3.connect(f"file:{ROOT / C.SCHEMA['inputs']['cdm']['path']}?mode=ro", uri=True)
    q = lambda sql, *a: c.execute(sql, a).fetchall()
    export, rows = C.load_bugsigdb()
    parent, rank, tname, genus = C.load_taxonomy()
    by_pmid = {str(p): i for i, p in q("SELECT paper_id, pmid FROM paper WHERE pmid IS NOT NULL AND pmid != ''")}
    by_doi = {d.lower().strip(): i for i, d in q("SELECT paper_id, doi FROM paper WHERE doi IS NOT NULL AND doi != ''")}
    sig = defaultdict(list)
    for r in rows:
        pm = (r.get("PMID") or "").split(".")[0]
        pid = (by_pmid.get(pm) if pm else None) or by_doi.get((r.get("DOI") or "").lower().strip())
        if pid:
            sig[pid].append(r)
    papers = sorted(sig)
    dmap = C.SCHEMA["our_findings"]["direction_map"]

    def add(store, pid, ids, d):
        for t in C.taxa_ids(ids):
            store[pid][t]
            if d in dmap:
                store[pid][t].add(dmap[d])

    old = defaultdict(lambda: defaultdict(set))
    for pid, ids, d in q("SELECT paper_id, taxon_ncbi_ids, direction FROM claim WHERE claim_source = 'catalogue_v3_1' "
                         "AND taxon_ncbi_ids IS NOT NULL AND taxon_ncbi_ids != ''"):
        add(old, pid, ids, d)
    tier = [json.loads(l) for l in open(OUT / "findings_v32_candidate.jsonl", encoding="utf-8")]
    blocks_only = defaultdict(lambda: defaultdict(set))
    new = defaultdict(lambda: defaultdict(set))
    for pid, m in old.items():
        for t, ds in m.items():
            new[pid][t] |= ds
    for f in tier:
        if f["taxon_ncbi_ids"]:
            add(new, f["paper_id"], f["taxon_ncbi_ids"], f["direction"])
            add(blocks_only, f["paper_id"], f["taxon_ncbi_ids"], f["direction"])

    ref, bsdb_dir, sig_source = defaultdict(lambda: defaultdict(list)), defaultdict(lambda: defaultdict(set)), {}
    for pid in papers:
        for r in sig[pid]:
            sid = r["BSDB ID"]
            sig_source[sid] = r.get("Source") or ""
            d = {"increased": "up", "decreased": "down"}.get(r["Abundance in Group 1"])
            if d:
                for lin in [x for x in (r["NCBI Taxonomy IDs"] or "").split(";") if x.strip()]:
                    if lin.split("|")[-1].strip().isdigit():
                        leaf = int(lin.split("|")[-1])
                        ref[pid][str(leaf)].append(sid)
                        bsdb_dir[pid][leaf].add(d)

    def tax_verdict(leaf, mine):
        if not mine:
            return "OURS_MISSING", []
        if leaf in mine:
            return "MATCH", [leaf]
        g = genus(leaf)
        hit = [t for t in mine if genus(t) == g]
        return ("PARTIAL", hit) if hit else ("MISMATCH", [])

    def evaluate(ours):
        rng = random.Random(C.SCHEMA["uncertainty"]["bootstrap"]["seed"])
        items = []
        for pid in papers:
            mine = ours.get(pid, {})
            for leaf_s, sids in ref[pid].items():
                leaf = int(leaf_s)
                v, hit = tax_verdict(leaf, mine)
                agr = None
                dirs = None
                if v in HIT:
                    od = set().union(*(mine[h] for h in hit))
                    bd = bsdb_dir[pid][leaf]
                    agr = ("SAME" if bd == od else "OPPOSITE") if len(bd) == 1 and len(od) == 1 else "UNDETERMINED"
                    dirs = (sorted(bd), sorted(od))
                items.append({"paper_id": pid, "leaf": leaf, "verdict": v, "agr": agr, "dirs": dirs,
                              "src": C.source_class(sig_source.get(sorted(set(sids))[0], "")),
                              "sids": sorted(set(sids))})
        ck = cn = 0
        for p in papers:
            for o in papers:
                if o == p or not ours.get(o):
                    continue
                for leaf_s in ref[p]:
                    cn += 1
                    ck += tax_verdict(int(leaf_s), ours[o])[0] in HIT
        n, k = len(items), sum(i["verdict"] in HIT for i in items)
        det = [i for i in items if i["agr"] in ("SAME", "OPPOSITE")]
        kd = sum(i["agr"] == "SAME" for i in det)
        ch = ck / cn if cn else None
        boot_cov = C.boot(items, lambda i: i["verdict"] in HIT, papers, rng)
        return items, {
            "bsdb_items": n, "verdicts": dict(Counter(i["verdict"] for i in items)),
            "coverage": round(k / n, 4), "coverage_wilson": C.wilson(k, n), "coverage_bootstrap": boot_cov,
            "coverage_chance": round(ch, 4) if ch is not None else None,
            "coverage_chance_corrected": round((k / n - ch) / (1 - ch), 4) if ch is not None and ch < 1 else None,
            "exact_coverage": round(sum(i["verdict"] == "MATCH" for i in items) / n, 4),
            "direction": dict(Counter(i["agr"] for i in items if i["agr"])), "direction_determinable": len(det),
            "direction_same": round(kd / len(det), 4) if det else None, "direction_same_wilson": C.wilson(kd, len(det)),
            "posthoc_direction_chance": C.direction_chance(det),
            "coverage_by_source": {s: {"items": len(g), "covered": sum(i["verdict"] in HIT for i in g),
                                       "coverage": round(sum(i["verdict"] in HIT for i in g) / len(g), 4),
                                       "wilson": C.wilson(sum(i["verdict"] in HIT for i in g), len(g))}
                                   for s, g in sorted(C.group_by(items, "src").items())}}

    old_items, s_old = evaluate(old)
    frozen = json.loads(FROZEN.read_text())["taxa"]["catalogue"]
    assert s_old["coverage"] == frozen["coverage"] and s_old["coverage_wilson"] == frozen["coverage_wilson"], "old arm"
    assert s_old["coverage_chance"] == frozen["coverage_chance"] and s_old["direction_same"] == frozen["direction_same"]
    assert s_old["coverage_bootstrap"] == frozen["coverage_bootstrap"], "bootstrap"
    for s, v in frozen["posthoc_coverage_by_source"].items():
        assert s_old["coverage_by_source"][s]["coverage"] == v["coverage"], s
    new_items, s_new = evaluate(new)
    _, s_blk = evaluate(blocks_only)

    newly = [(o, n) for o, n in zip(old_items, new_items) if o["verdict"] not in HIT and n["verdict"] in HIT]
    det = [n for _, n in newly if n["agr"] in ("SAME", "OPPOSITE")]
    kd = sum(n["agr"] == "SAME" for n in det)
    upgraded = [(o, n) for o, n in zip(old_items, new_items) if o["verdict"] == "PARTIAL" and n["verdict"] == "MATCH"]
    res = {"protocol": "compare.py functions, scoring_schema.json v" + C.SCHEMA["version"] + " (unchanged); old arm "
                       "asserted equal to the frozen summary.json",
           "papers": len(papers), "tier_findings_with_ncbi_taxon": sum(bool(f["taxon_ncbi_ids"]) for f in tier),
           "tier_findings_on_bugsigdb_papers": sum(f["paper_id"] in sig for f in tier),
           "tier_findings_with_taxon_on_bugsigdb_papers": sum(f["paper_id"] in sig and bool(f["taxon_ncbi_ids"]) for f in tier),
           "old_catalogue_v3_1": s_old, "old_plus_blocks": s_new, "blocks_tier_alone": s_blk,
           "newly_covered_items": len(newly),
           "newly_covered_by_source": dict(Counter(n["src"] for _, n in newly)),
           "newly_covered_direction": dict(Counter(n["agr"] for _, n in newly)),
           "newly_covered_direction_same": round(kd / len(det), 4) if det else None,
           "newly_covered_direction_same_wilson": C.wilson(kd, len(det)),
           "newly_covered_direction_chance": C.direction_chance(det),
           "partial_upgraded_to_exact": len(upgraded)}
    (OUT / "coverage_eval.json").write_text(json.dumps(res, indent=2) + "\n")
    with open(OUT / "newly_covered_items.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["paper_id", "bsdb_taxon", "bsdb_name", "bsdb_source", "old_verdict", "new_verdict", "bsdb_dir",
                    "our_dir", "agreement", "bsdb_signatures"])
        for o, n in newly:
            w.writerow([n["paper_id"], n["leaf"], tname.get(n["leaf"], ""), n["src"], o["verdict"], n["verdict"],
                        "/".join(n["dirs"][0]), "/".join(n["dirs"][1]), n["agr"], "; ".join(n["sids"])])
    print(json.dumps({k: v for k, v in res.items() if k not in ("old_catalogue_v3_1", "old_plus_blocks", "blocks_tier_alone")}, indent=2))
    for k in ("old_catalogue_v3_1", "old_plus_blocks", "blocks_tier_alone"):
        s = res[k]
        print(k, s["coverage"], s["coverage_wilson"], "chance", s["coverage_chance"], "dir", s["direction_same"],
              json.dumps({x: (v["covered"], v["items"], v["coverage"], v["wilson"]) for x, v in s["coverage_by_source"].items()}))


if __name__ == "__main__":
    main()
