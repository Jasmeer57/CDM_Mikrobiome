"""Layer 3.2.0-candidate, step 1 (CPU, deterministic): parse the evidence sentences of every CDM triple with scispaCy,
apply the FROZEN Fix B syntactic filter (syntax_filter.py, sha in PREREGISTRATION.md) and extract the connecting phrase
between subject and object (input for the corpus-derived vocabulary of Fix A).

    PYTHONPATH=<scispacy overlay> python src/scripts/fixes_v32/corpus_parse.py --out DIR [--nproc 8]

Population / buckets exactly as triples_final_summary.py (CDM 3.1.0 triple_tier overridden by retype-v2.5 all_v25/ and
unsigned_resolve all/final.jsonl). Evidence rows per triple exactly as retype_triples_v3.py (relation_evidence of CDM
3.0.3, source_sentence not null, EXACT first, then WHITESPACE, LIMIT 2) -- the rows the typer would see.
Output DIR/corpus_parse.jsonl (one row per triple). Read-only on releases/. Written with Claude Code (declare).
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import sqlite3
import sys
import time
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
sys.path.insert(0, str(Path(__file__).resolve().parent))
import syntax_filter as SF  # noqa: E402

DB303 = ROOT / "releases/cdm_v3/3.0.3/microbiome_cdm_v3.db"
DB310 = ROOT / "releases/cdm_v3/3.1.0/microbiome_cdm_v3.1.0.db"
FROZEN_SHA = "e6a9bb8d4600955d59d661d6f4914b0393a17077aa4641009bf2d2c2d6c4a920"
SCOPE_BUCKETS = ("NOT_SUPPORTED", "SPECIFIC_LABEL_CUE_NOT_FOUND")


def check_frozen():
    got = hashlib.sha256((Path(SF.__file__)).read_bytes()).hexdigest()
    assert got == FROZEN_SHA, f"syntax_filter.py changed after pre-registration: {got}"


def rows(pattern):
    return [json.loads(l) for f in sorted(glob.glob(str(ROOT / pattern))) for l in open(f, encoding="utf-8") if l.strip()]


def bucket(rel, ok):
    if ok:
        return "SPECIFIC_CUE_VERIFIED"
    if rel in ("NOT_SUPPORTED", "ASSOCIATION_UNSIGNED", "NULL_FINDING", "BAD_ENDPOINT"):
        return rel
    return "SPECIFIC_LABEL_CUE_NOT_FOUND"


def final_layer():
    """{triple_id: (bucket, relation, subject, object)} as in triples_final_summary.py."""
    c = sqlite3.connect(f"file:{DB310}?mode=ro", uri=True)
    base = {k: (rel, s == "True" and cf == "True", su, ob) for k, rel, s, cf, su, ob in
            c.execute("SELECT canonical_triple_id, relation, specific_relation, cue_found, subject, object FROM triple_tier")}
    v25 = {r["canonical_triple_id"]: r for r in rows("outputs/results/triple_retype_v2_2026-11-10/all_v25/*.jsonl")}
    uns = {r["canonical_triple_id"]: r for r in rows("outputs/results/unsigned_resolve_2026-11-10/all/final.jsonl")}
    out = {}
    for k, (rel, ok, su, ob) in base.items():
        r = uns.get(k) or v25.get(k)
        if r:
            out[k] = (bucket(r["relation"], r["specific_verified"]), r["relation"], su, ob, "unsigned_resolve" if k in uns else "retype_v25")
        else:
            out[k] = (bucket(rel, ok), rel, su, ob, "cdm310_triple_tier")
    return out


def phrase(sa, sb):
    """Connecting phrase between two located spans: tokens on the dependency path (minus the two heads) with their
    negation / passive / preposition children, in sentence order, plus the surface tokens between the spans."""
    p = SF._path(sa.root, sb.root)
    if p is None:
        return None
    edges, lca, nodes = p
    inner = {t.i: t for t in nodes + [lca]}
    for h in (sa.root, sb.root):
        inner.pop(h.i, None)
    span_ids = set(range(sa.start, sa.end)) | set(range(sb.start, sb.end))
    toks = []
    for t in sorted(inner.values(), key=lambda x: x.i):
        if t.i in span_ids or t.is_punct:
            continue
        kids = {SF.base(c.dep_): c for c in t.children}
        toks.append({"lemma": t.lemma_.lower(), "pos": t.pos_, "dep": SF.base(t.dep_),
                     "neg": any(SF.base(c.dep_) == "neg" for c in t.children),
                     "passive": "auxpass" in kids or "nsubjpass" in kids,
                     "prt": [c.lemma_.lower() for c in t.children if SF.base(c.dep_) == "prt"]})
    path_toks = list(inner.values()) + [sa.root, sb.root]
    preps = sorted({(c.i, c.lemma_.lower()) for t in path_toks for c in t.children
                    if SF.base(c.dep_) in ("case", "prep", "agent") and c.i not in span_ids})
    lo, hi = (sa.end, sb.start) if sa.start < sb.start else (sb.end, sa.start)
    between = [[t.lemma_.lower(), t.pos_, t.text] for t in sa.doc[lo:hi] if not t.is_punct] if 0 <= hi - lo <= 12 else None
    return {"path": toks, "preps": [w for _, w in preps], "edges": edges, "between": between,
            "subject_first": sa.start < sb.start}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--nproc", type=int, default=8)
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    check_frozen()
    a.out.mkdir(parents=True, exist_ok=True)
    fl = final_layer()
    c = sqlite3.connect(f"file:{DB303}?mode=ro", uri=True)
    tids = sorted(fl)
    if a.limit:
        tids = tids[:a.limit]
    ev = {}
    for tid in tids:
        ev[tid] = c.execute("""SELECT e.source_sentence, e.triple_mention_id, e.paper_id, e.anchor_status
                               FROM relation_evidence e WHERE e.canonical_triple_id=? AND e.source_sentence IS NOT NULL
                               ORDER BY (e.anchor_status='EXACT') DESC, (e.anchor_status='WHITESPACE') DESC LIMIT 2""",
                            (tid,)).fetchall()
    sents = sorted({SF.norm_text(s) for v in ev.values() for s, *_ in v})
    print(f"{len(tids):,} triples; {len(sents):,} distinct evidence sentences", flush=True)
    nlp = SF.load()
    t0 = time.time()
    docs = {}
    for s, d in zip(sents, nlp.pipe(sents, n_process=a.nproc, batch_size=64)):
        docs[s] = d
        if len(docs) % 5000 == 0:
            print(f"  parsed {len(docs):,} {time.time() - t0:.0f}s", flush=True)
    order = SF.ORDER + ["UNLOCATED"]
    with open(a.out / "corpus_parse.jsonl", "w", encoding="utf-8") as f:
        for tid in tids:
            bk, rel, su, ob, src = fl[tid]
            out_ev = []
            for s, mid, pid, anch in ev[tid]:
                d = docs[SF.norm_text(s)]
                r = SF.judge(d, su, ob, nlp_tok=nlp.tokenizer)
                ph = None
                A, _ = SF.locate(d, su, None, nlp.tokenizer)
                B, _ = SF.locate(d, ob, None, nlp.tokenizer)
                if A and B:
                    best = min(((SF.judge_spans(x, y)[0], x, y) for x in A[:5] for y in B[:5]), key=lambda z: SF.ORDER.index(z[0]))
                    ph = phrase(best[1], best[2])
                out_ev.append({"mention_id": mid, "paper_id": pid, "anchor": anch, "sentence": SF.norm_text(s), **r, "phrase": ph})
            sts = [e["status"] for e in out_ev] or ["NO_EVIDENCE"]
            best = min(sts, key=lambda x: order.index(x) if x in order else 99)
            conn = True if any(e["connected"] for e in out_ev) else (None if all(e["connected"] is None for e in out_ev) else False)
            f.write(json.dumps({"canonical_triple_id": tid, "bucket_v31": bk, "relation_v31": rel, "layer_source": src,
                                "subject": su, "object": ob, "in_v32_scope": bk in SCOPE_BUCKETS,
                                "syntax_status": best, "syntax_connected": conn, "rule_version": SF.RULE_VERSION,
                                "evidence": out_ev}, ensure_ascii=False) + "\n")
    print("done", round(time.time() - t0), flush=True)


if __name__ == "__main__":
    main()
