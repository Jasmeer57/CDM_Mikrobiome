"""KGX (Biolink 4.4.6) node and edge TSVs from the canonical triples of CDM 3.x (3.2.0-candidate DB, read-only).

Edges: one per canonical triple (relation), with the 3.1.0 repaired relation label (triple_tier.relation, direction
REVERSED swapped) mapped to a Biolink predicate by crosswalk/curated_mappings.BIOLINK_PRED (documented in
crosswalk_biolink_predicates.csv).  Triples whose label is NULL_FINDING or NOT_SUPPORTED have no Biolink predicate
and are not exported as edges (counted in kgx_export_stats.json).  Every edge keeps its provenance: cdm triple id,
original and repaired label, tier, cue status, extraction run, papers (publications), and its evidence anchors as
offsets + SHA-256 of the anchor sentence (edge_evidence.tsv: one row per triple mention; sentence text only for
INCLUDE_TEXT papers).
Nodes: canonical terms (MCDMT:) where the endpoint is linked to a term, otherwise the triple's endpoint entity
(MCDME:); category from the CDM type / endpoint type; xref = concepts of ACCEPTED EXACT mappings.
Outputs: exports/kgx/cdm_3.2.0-candidate_nodes.tsv, _edges.tsv, edge_evidence.tsv, kgx_export_stats.json
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from export_common import EXPORT, CurieMaker, Redactor, biolink_maps, open_db, rights, sha, text_allowed, write_tsv  # noqa

KL, AT = "knowledge_assertion", "text_mining_agent"
INFORES = "infores:microbiome-cdm"   # not (yet) registered in the infores catalogue


def main():
    out = EXPORT / "kgx"
    out.mkdir(parents=True, exist_ok=True)
    con = open_db()
    rt = rights()
    red = Redactor(con, rt)
    CM = biolink_maps()
    cm = CurieMaker()
    terms = {r["term_id"]: r for r in con.execute("SELECT term_id, term, cdm_type FROM canonical_term")}
    xref = defaultdict(set)
    for r in con.execute("SELECT term_id, concept_id FROM term_concept_map WHERE mapping_disposition_reviewed="
                         "'ACCEPTED' AND relation_llm_g9='EXACT' AND relation_deepseek='EXACT'"):
        xref[r[0]].add(cm.curie(r[1]))
    pubs = {}
    for r in con.execute("SELECT paper_id, doi, pmid FROM paper"):
        pubs[r[0]] = f"PMID:{r['pmid']}" if r["pmid"] else (f"doi:{r['doi']}" if r["doi"] else f"MCDMP:{r[0]}")
    tier = {r["canonical_triple_id"]: r for r in con.execute("SELECT * FROM triple_tier")}
    hrev = defaultdict(list)
    for r in con.execute("SELECT target_id, reviewer, decision FROM human_review WHERE target_entity='relation'"):
        hrev[r[0]].append(f"{r[1]}={r[2]}")
    ev = defaultdict(list)
    ev_rows = []
    for r in con.execute("SELECT * FROM relation_evidence WHERE relation_table='relation'"):
        allowed = text_allowed(rt, r["paper_id"])
        ev[r["canonical_triple_id"]].append(f"{r['section_record_id']}:{r['char_start']}-{r['char_end']}"
                                            f"|{r['anchor_status']}|sha256:{sha(r['source_sentence'])}")
        ev_rows.append({"triple_mention_id": r["triple_mention_id"], "edge_id": f"MCDMR:{r['canonical_triple_id']}",
                        "paper_id": r["paper_id"], "publication": pubs.get(r["paper_id"], ""),
                        "section_record_id": r["section_record_id"], "char_start": r["char_start"],
                        "char_end": r["char_end"], "anchor_status": r["anchor_status"],
                        "section_text_sha256": r["section_text_sha256"],
                        "sentence_sha256": sha(r["source_sentence"]),
                        "rights_bucket": rt.get(r["paper_id"], "UNKNOWN"),
                        "sentence": r["source_sentence"] if allowed else "",
                        "extraction_run_id": r["extraction_run_id"]})
    nodes, edges, skipped = {}, [], Counter()

    def node(side, r):
        tid = r[f"{side}_term_id"]
        pid = None
        if tid and tid in terms:
            t = terms[tid]
            nid = f"MCDMT:{tid}"
            if nid not in nodes:
                nodes[nid] = {"id": nid, "category": CM.BIOLINK_CDM_TYPE[t["cdm_type"]][0],
                              "name": red.clean(t["term"]), "xref": "|".join(sorted(xref.get(tid, ()))),
                              "provided_by": INFORES, "cdm_type": t["cdm_type"], "cdm_node_kind": "canonical_term"}
        else:
            nid = f"MCDME:{r[f'{side}_entity_id']}"
            if nid not in nodes:
                nodes[nid] = {"id": nid, "category": CM.BIOLINK_ENTITY_TYPE[r[f"{side}_entity_type"]][0],
                              "name": red.clean(r[f"{side}_normalized_label"], pid), "xref": "",
                              "provided_by": INFORES, "cdm_type": r[f"{side}_entity_type"],
                              "cdm_node_kind": "unlinked_triple_endpoint"}
        return nid

    for r in con.execute("SELECT * FROM relation ORDER BY canonical_triple_id"):
        tt = tier[r["canonical_triple_id"]]
        rel = tt["relation"]
        pred, lvl, why, extra = CM.BIOLINK_PRED[rel]
        if not pred:
            skipped[rel] += 1
            continue
        s, o = node("subject", r), node("object", r)
        if tt["direction"] == "REVERSED":
            s, o = o, s
        if extra.get("reverse"):
            s, o = o, s
        papers = json.loads(r["paper_ids"]) if (r["paper_ids"] or "").startswith("[") else \
            [p.strip() for p in (r["paper_ids"] or "").split(";") if p.strip()]
        edges.append({"id": f"MCDMR:{r['canonical_triple_id']}", "subject": s, "predicate": pred, "object": o,
                      "category": "biolink:Association", "knowledge_level": KL, "agent_type": AT,
                      "primary_knowledge_source": INFORES,
                      "publications": "|".join(sorted({pubs.get(p, f"MCDMP:{p}") for p in papers})),
                      "cdm_relation": rel, "cdm_relation_original": r["relation_normalized"],
                      "cdm_relation_tier": tt["tier"], "cdm_cue_found": tt["cue_found"],
                      "cdm_direction": extra.get("cdm_direction", ""), "cdm_direction_swapped": tt["direction"],
                      "biolink_mapping_level": lvl, "cdm_paper_ids": "|".join(papers),
                      "cdm_mention_count": r["mention_count"], "cdm_extraction_run": r["extraction_run_id"],
                      "cdm_verdict_deepseek": r["verdict_deepseek"] or "",
                      "cdm_human_review": "|".join(hrev.get(r["canonical_triple_id"], [])),
                      "cdm_evidence_anchors": "||".join(ev.get(r["canonical_triple_id"], []))})
    nf = ["id", "category", "name", "xref", "provided_by", "cdm_type", "cdm_node_kind"]
    write_tsv(out / "cdm_3.2.0-candidate_nodes.tsv", sorted(nodes.values(), key=lambda x: x["id"]), nf)
    write_tsv(out / "cdm_3.2.0-candidate_edges.tsv", edges)
    write_tsv(out / "edge_evidence.tsv", ev_rows)
    stats = {"triples": len(tier), "edges": len(edges), "triples_not_exported_no_predicate": dict(skipped),
             "nodes": len(nodes), "nodes_canonical_term": sum(n["cdm_node_kind"] == "canonical_term"
                                                              for n in nodes.values()),
             "nodes_unlinked_endpoint": sum(n["cdm_node_kind"] != "canonical_term" for n in nodes.values()),
             "edges_by_predicate": dict(Counter(e["predicate"] for e in edges).most_common()),
             "edges_related_to_only": sum(e["predicate"] == "biolink:related_to" for e in edges),
             "edges_no_specific_relation_stated": sum(e["cdm_relation"] == "NO_SPECIFIC_RELATION_STATED"
                                                      for e in edges),
             "evidence_rows": len(ev_rows), "evidence_rows_with_text": sum(bool(e["sentence"]) for e in ev_rows),
             "evidence_rows_offsets_only": sum(not e["sentence"] for e in ev_rows),
             "labels_blanked_R2_R4": red.blanked,
             "knowledge_level": KL, "agent_type": AT, "primary_knowledge_source": INFORES}
    (out / "kgx_export_stats.json").write_text(json.dumps(stats, indent=1))
    print(json.dumps(stats, indent=1))


if __name__ == "__main__":
    main()
