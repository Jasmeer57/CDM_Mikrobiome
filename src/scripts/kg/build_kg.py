"""Knowledge graph from the CDM 3.0.3 relation triples (frozen, read-only), in two variants:

  full     all 25,788 triples as released (relation_normalized)
  cleaned  the triples kept by the DeepSeek cleaning, with the cleaned relation and orientation

Nodes are canonical terms (term_id); an unlinked triple end becomes a label node (LABEL:<normalised label>).
Each node carries its CDM type, the cleaned type, and one ontology identifier when the CDM holds an accepted or
canonical, non-rejected mapping. Outputs go to outputs/results/kg_2026-11-04/ with a MANIFEST.

    python build_kg.py        # normally: sbatch build_kg.sbatch
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import json
import re
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

import networkx as nx

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
CDM = ROOT / "releases/cdm_v3/3.0.3/microbiome_cdm_v3.db"
CLEAN = ROOT / "outputs/results/cleaned_layer_deepseek"
OUT = ROOT / "outputs/results/kg_2026-11-04"


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def norm(s):
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def main():
    c = sqlite3.connect(f"file:{CDM}?mode=ro", uri=True)
    terms = {tid: (t, typ) for tid, t, typ in c.execute("SELECT term_id, term, cdm_type FROM canonical_term")}
    with gzip.open(CLEAN / "cleaned_terms.csv.gz", "rt", encoding="utf-8") as fh:
        ctype = {r["term_id"]: r["type_cleaned"] for r in csv.DictReader(fh)}
    onto = {}
    for tid, cid, disp, rev, canon in c.execute("SELECT term_id, concept_id, mapping_disposition, mapping_disposition_reviewed, "
                                                "is_canonical_candidate FROM term_concept_map ORDER BY candidate_rank"):
        ok = rev == "ACCEPTED" or (canon == 1 and disp != "REJECTED" and rev not in ("REJECTED", "REMOVED"))
        if ok and (tid not in onto or rev == "ACCEPTED" and onto[tid][1] != "ACCEPTED"):
            onto[tid] = (cid, rev or "")
    with gzip.open(CLEAN / "cleaned_triples.csv.gz", "rt", encoding="utf-8") as fh:
        cl = {r["canonical_triple_id"]: r for r in csv.DictReader(fh)}
    edges = []
    for row in c.execute("SELECT canonical_triple_id, subject_term_id, subject_display_label, relation_normalized, relation_family, "
                         "object_term_id, object_display_label, paper_count, mention_count, paper_ids FROM relation"):
        tid, st, sl, rel, fam, ot, ol, pc, mc, pids = row
        s_node = st if st in terms else f"LABEL:{norm(sl)}"
        o_node = ot if ot in terms else f"LABEL:{norm(ol)}"
        r = cl.get(tid, {})
        kept = r.get("kept") == "1"
        swapped = r.get("direction_swapped") == "1"
        edges.append({"triple_id": tid, "subject": s_node, "subject_label": sl, "relation": rel, "relation_family": fam,
                      "object": o_node, "object_label": ol, "paper_count": pc, "mention_count": mc,
                      "papers": "|".join(json.loads(pids or "[]")), "kept_by_cleaning": int(kept),
                      "relation_cleaned": r.get("relation_cleaned", "") if kept else "", "swapped_by_cleaning": int(swapped),
                      "drop_reason": r.get("drop_reason", "")})
    nodes = {}
    for e in edges:
        for side in ("subject", "object"):
            n = e[side]
            if n in nodes:
                continue
            if n.startswith("LABEL:"):
                nodes[n] = {"node_id": n, "label": e[f"{side}_label"], "cdm_type": "", "type_cleaned": "", "ontology_id": "", "linked": 0}
            else:
                t, typ = terms[n]
                nodes[n] = {"node_id": n, "label": t, "cdm_type": typ, "type_cleaned": ctype.get(n, typ),
                            "ontology_id": onto.get(n, ("", ""))[0], "linked": 1}

    def graph(variant):
        g = nx.MultiDiGraph()
        for e in edges:
            if variant == "cleaned" and not e["kept_by_cleaning"]:
                continue
            s, o = (e["object"], e["subject"]) if variant == "cleaned" and e["swapped_by_cleaning"] else (e["subject"], e["object"])
            rel = e["relation_cleaned"] if variant == "cleaned" else e["relation"]
            g.add_edge(s, o, key=e["triple_id"], relation=rel, papers=e["papers"], paper_count=int(e["paper_count"] or 0))
        for n in g.nodes:
            g.nodes[n].update({k: v for k, v in nodes[n].items() if k != "node_id"})
        return g

    stats = {}
    OUT.mkdir(parents=True, exist_ok=True)
    for variant in ("full", "cleaned"):
        g = graph(variant)
        und = g.to_undirected(as_view=True)
        comps = sorted((len(x) for x in nx.connected_components(nx.Graph(und))), reverse=True)
        deg = Counter(dict(g.degree()))
        type_of = lambda n: g.nodes[n]["type_cleaned" if variant == "cleaned" else "cdm_type"] or "UNLINKED"
        pairs = Counter((type_of(u), type_of(v)) for u, v in g.edges())
        papers = {p for _, _, d in g.edges(data=True) for p in d["papers"].split("|") if p}
        both_onto = sum(1 for u, v in g.edges() if g.nodes[u]["ontology_id"] and g.nodes[v]["ontology_id"])
        stats[variant] = {
            "nodes": g.number_of_nodes(), "edges": g.number_of_edges(),
            "distinct_node_pairs": len({(u, v) for u, v in g.edges()}),
            "linked_nodes": sum(1 for n in g if g.nodes[n]["linked"]),
            "edges_with_ontology_ids_both_ends": both_onto,
            "components": len(comps), "largest_component_nodes": comps[0] if comps else 0,
            "largest_component_share": round(comps[0] / g.number_of_nodes(), 4) if comps else 0,
            "mean_degree": round(2 * g.number_of_edges() / max(1, g.number_of_nodes()), 2),
            "papers_covered": len(papers),
            "relations": dict(Counter(d["relation"] for _, _, d in g.edges(data=True)).most_common()),
            "top_type_pairs": [[a, b, n] for (a, b), n in pairs.most_common(15)],
            "top_hubs": [[g.nodes[n]["label"], type_of(n), d] for n, d in deg.most_common(20)],
        }
        if variant == "cleaned":
            nx.write_graphml(g, OUT / "kg_cleaned.graphml")
    with gzip.open(OUT / "nodes.csv.gz", "wt", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(next(iter(nodes.values()))))
        w.writeheader()
        w.writerows(nodes.values())
    with gzip.open(OUT / "edges.csv.gz", "wt", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(edges[0]))
        w.writeheader()
        w.writerows(edges)
    (OUT / "kg_stats.json").write_text(json.dumps(stats, indent=1))
    f, k = stats["full"], stats["cleaned"]
    L = ["# Knowledge graph from the CDM 3.0.3 triples", "",
         "*Built by `src/scripts/kg/build_kg.py` from the frozen CDM (read-only) and the DeepSeek-cleaned layer. Nodes are "
         "canonical terms; unlinked triple ends are label nodes. `edges.csv.gz` holds every triple with its original and cleaned "
         "relation; `kg_cleaned.graphml` is the cleaned graph.*", "",
         "| | Full (as released) | Cleaned (DeepSeek) |", "|---|---:|---:|",
         *[f"| {lab} | {f[key]:,} | {k[key]:,} |" for key, lab in [
             ("nodes", "Nodes"), ("edges", "Edges (triples)"), ("distinct_node_pairs", "Distinct node pairs"),
             ("linked_nodes", "Nodes linked to a canonical term"), ("edges_with_ontology_ids_both_ends", "Edges with ontology IDs on both ends"),
             ("components", "Connected components"), ("largest_component_nodes", "Largest component (nodes)"),
             ("papers_covered", "Papers contributing edges")]],
         f"| Largest component share | {100 * f['largest_component_share']:.1f}% | {100 * k['largest_component_share']:.1f}% |",
         f"| Mean degree | {f['mean_degree']} | {k['mean_degree']} |", "",
         "## Most connected nodes (cleaned)", "", "| Node | Type | Degree |", "|---|---|---:|",
         *[f"| {a} | {b} | {d} |" for a, b, d in k["top_hubs"][:15]], "",
         "## Most frequent type pairs (cleaned)", "", "| Subject type | Object type | Edges |", "|---|---|---:|",
         *[f"| {a} | {b} | {n} |" for a, b, n in k["top_type_pairs"][:12]]]
    (OUT / "REPORT.md").write_text("\n".join(L) + "\n")
    files = sorted(p for p in OUT.iterdir() if p.is_file() and p.name != "MANIFEST.sha256")
    (OUT / "MANIFEST.sha256").write_text("".join(f"{sha256(p)}  {p.name}\n" for p in files))
    print("\n".join(L))


if __name__ == "__main__":
    main()
