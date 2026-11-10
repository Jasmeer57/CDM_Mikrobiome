"""Stage E — embedding candidates for G6 (triple entities) and G7 (crosswalk), on one GPU.

all-MiniLM-L6-v2 embeds the 165,991 canonical terms once; each label to link
gets its top-5 canonical candidates by cosine similarity.

G6 (canonical triples, 32,713): every distinct subject/object label.
    exact normalised match            -> linked directly (EXACT_NORM)
    best cosine >= 0.95               -> linked directly (EMBED_HIGH)
    0.70 <= best < 0.95               -> item for Gemma adjudication (G6)
    best < 0.70                       -> UNLINKED
G7 (crosswalk inventory_to_canonical.csv, 40,141 rows):
    matched rows with type disagreement (DISJOINT / GENERIC_ONLY) -> type item
    UNMATCHED rows -> type item with top-5 canonical candidates

Writes outputs/results/gap_runs/E/{g6_candidates,g6_direct,g7_candidates}.jsonl
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import numpy as np

import gaplib as G

csv.field_size_limit(sys.maxsize)
ROOT = G.REPO_ROOT
TERMS = ROOT / "releases/frozen_output/02_data_catalogue/terminology/canonical_terms.jsonl"
TRIPLES = ROOT / "pipelines/corpus_v2/data/canonical_triples.jsonl"
CROSSWALK = ROOT / "releases/frozen_output/03_common_data_model/crosswalk/inventory_to_canonical.csv"
INVENTORY = ROOT / "pipelines/corpus_v2/releases/2.2.0/terminology_inventory.csv"
OUT = G.GAP_DIR / "E"


def main():
    import clean_catalogue as cc
    from sentence_transformers import SentenceTransformer
    OUT.mkdir(parents=True, exist_ok=True)
    log = G.log_to(OUT / "run.log")
    terms = [json.loads(l) for l in open(TERMS, encoding="utf-8")]
    norm = {}
    for t in terms:
        norm.setdefault(cc._norm_map(t["term"])[0], t)
    log(f"canonical terms {len(terms)}")
    model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2", device="cuda")
    T = model.encode([t["term"] for t in terms], batch_size=1024, normalize_embeddings=True,
                     convert_to_numpy=True, show_progress_bar=False).astype(np.float32)
    log("embedded canonical terms")

    def topk(labels, k=5):
        if not labels:
            return []
        Q = model.encode(labels, batch_size=1024, normalize_embeddings=True, convert_to_numpy=True,
                         show_progress_bar=False).astype(np.float32)
        import torch
        Tt = torch.from_numpy(T).cuda()
        out = []
        for i in range(0, len(Q), 4096):
            s = torch.from_numpy(Q[i:i + 4096]).cuda() @ Tt.T
            v, ix = s.topk(k, dim=1)
            out += list(zip(v.cpu().numpy(), ix.cpu().numpy()))
        return out

    def cands(v, ix):
        return [{"term_id": terms[j]["term_id"], "term": terms[j]["term"], "type": terms[j]["cdm_type"],
                 "score": round(float(s), 3)} for s, j in zip(v, ix)]

    # G6
    labels = set()
    for l in open(TRIPLES, encoding="utf-8"):
        t = json.loads(l)
        for side in ("subject", "object"):
            lab = (t.get(f"{side}_display_label") or "").strip()
            if lab:
                labels.add((lab, t.get(f"{side}_entity_type") or ""))
    labels = sorted(labels)
    direct, pending = [], []
    for lab, typ in labels:
        hit = norm.get(cc._norm_map(lab)[0])
        if hit:
            direct.append({"label": lab, "entity_type": typ, "term_id": hit["term_id"], "method": "EXACT_NORM"})
        else:
            pending.append((lab, typ))
    items = []
    for (lab, typ), (v, ix) in zip(pending, topk([p[0] for p in pending])):
        if v[0] >= 0.95:
            direct.append({"label": lab, "entity_type": typ, "term_id": terms[ix[0]]["term_id"],
                           "method": "EMBED_HIGH", "score": round(float(v[0]), 3)})
        elif v[0] >= 0.70:
            items.append({"id": f"L{len(items):06d}", "label": lab, "entity_type": typ, "candidates": cands(v, ix)})
        else:
            direct.append({"label": lab, "entity_type": typ, "term_id": "", "method": "UNLINKED",
                           "score": round(float(v[0]), 3)})
    G.write_jsonl(OUT / "g6_direct.jsonl", direct)
    G.write_jsonl(OUT / "g6_candidates.jsonl", items)
    log(f"G6 labels {len(labels)}: direct {sum(1 for d in direct if d['term_id'])}, "
        f"to adjudicate {len(items)}, unlinked {sum(1 for d in direct if not d['term_id'])}")

    # G7
    ctx = {}
    with open(INVENTORY, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            ctx[r["term_normalized"]] = (r.get("example_context") or "")[:300]
    rows = list(csv.DictReader(open(CROSSWALK, newline="", encoding="utf-8")))
    unmatched = [r for r in rows if r["type_relation"] == "NONE"]
    um_top = dict(zip([r["inventory_term_normalized"] for r in unmatched],
                      topk([r["inventory_term_normalized"] for r in unmatched])))
    g7 = []
    for r in rows:
        if r["type_relation"] not in ("DISJOINT", "GENERIC_ONLY", "NONE"):
            continue
        it = {"id": f"X{len(g7):06d}", "term": r["inventory_term_normalized"][:120],
              "inventory_types": r["inventory_types"], "context": ctx.get(r["inventory_term_normalized"], ""),
              "type_relation": r["type_relation"]}
        if r["type_relation"] == "NONE":
            v, ix = um_top[r["inventory_term_normalized"]]
            it["candidates"] = cands(v, ix)
        else:
            it["canonical_term_id"] = r["canonical_term_id"]
            it["canonical_type"] = r["canonical_cdm_type"]
            it["canonical_alternatives"] = r["canonical_alternative_types"]
        g7.append(it)
    G.write_jsonl(OUT / "g7_candidates.jsonl", g7)
    log(f"G7 items {len(g7)} ({len(unmatched)} unmatched with candidates)")


if __name__ == "__main__":
    main()
