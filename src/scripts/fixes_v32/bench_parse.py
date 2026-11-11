"""Layer 3.2.0-candidate: apply the FROZEN Fix B syntactic filter (syntax_filter.py, sha in PREREGISTRATION.md) to every
relation-evaluation item of the competitor comparison (DiMB-RE all within-sentence gold-entity pairs, MiDRED pairs,
MINERVA labelled sentences), exactly the items of competitor_llm_runner.rel_items(). CPU, deterministic.

    PYTHONPATH=<scispacy overlay> python src/scripts/fixes_v32/bench_parse.py --out DIR [--nproc 8]

Only the marked [[ ]] sentence is parsed. Mention spans: DiMB-RE and MiDRED gold token spans converted to character spans
of the space-joined sentence; MINERVA gives mention strings only (text search, then fuzzy window, as for the corpus).
Gold labels are not used. Output DIR/bench_parse.jsonl (id, status, connected, edges, loc_a, loc_b).
Written with Claude Code (declare).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "src/scripts/competitors"))
import syntax_filter as SF  # noqa: E402
import competitor_llm_runner as CR  # noqa: E402
from corpus_parse import FROZEN_SHA  # noqa: E402


def char_spans(tokens):
    offs, k = [], 0
    for t in tokens:
        offs.append((k, k + len(t)))
        k += len(t) + 1
    return offs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--nproc", type=int, default=8)
    a = ap.parse_args()
    assert hashlib.sha256(Path(SF.__file__).read_bytes()).hexdigest() == FROZEN_SHA, "syntax_filter.py changed"
    a.out.mkdir(parents=True, exist_ok=True)
    items = CR.rel_items()
    dimb = {}
    for sp, d in CR.dimb_docs():
        _, starts = CR.doc_tokens(d)
        dimb[(sp, d["doc_key"])] = (d["sentences"], starts)
    mid = {}
    for sp in ("train", "dev", "test"):
        for n, line in enumerate(open(CR.MIDRED / f"decrypted_{sp}.json", encoding="utf-8")):
            if line.strip():
                mid[(sp, n)] = json.loads(line)
    jobs = []        # (id, sentence, a_span, b_span, a_text, b_text)
    for t in items:
        sent = re.search(r"\[\[(.*)\]\]", t["ctx"], re.S).group(1)
        if t["ds"] == "dimb":
            _, sp, doc, si, aa, bb = t["id"].split(":", 5)
            sents, starts = dimb[(sp, doc)]
            si = int(si)
            offs = char_spans(sents[si])
            assert " ".join(sents[si]) == sent
            (a0, a1), (b0, b1) = [tuple(int(x) - starts[si] for x in s.split("-")) for s in (aa, bb)]
            jobs.append((t["id"], sent, (offs[a0][0], offs[a1][1]), (offs[b0][0], offs[b1][1]), None, None))
        elif t["ds"] == "midred":
            _, sp, n, k = t["id"].split(":")
            r = mid[(sp, int(n))]
            typ = {(e[0], e[1]): e[2] for e in r["entities"]}
            rel = r["relations"][int(k)]
            h, tt = (rel[0], rel[1]), (rel[2], rel[3])
            if typ.get(h) != "Bacteria" and typ.get(tt) == "Bacteria":
                h, tt = tt, h
            offs = char_spans(r["text"])
            assert " ".join(r["text"]) == sent
            jobs.append((t["id"], sent, (offs[h[0]][0], offs[h[1]][1]), (offs[tt[0]][0], offs[tt[1]][1]), None, None))
        else:
            jobs.append((t["id"], SF.norm_text(sent), None, None, t["subject"], t["object"]))
    sents = sorted({j[1] for j in jobs})
    print(f"{len(jobs):,} items; {len(sents):,} distinct sentences", flush=True)
    nlp = SF.load()
    t0 = time.time()
    docs = dict(zip(sents, nlp.pipe(sents, n_process=a.nproc, batch_size=64)))
    print(f"parsed {time.time() - t0:.0f}s", flush=True)
    with open(a.out / "bench_parse.jsonl", "w", encoding="utf-8") as f:
        for iid, s, sa, sb, ta, tb in jobs:
            r = SF.judge(docs[s], ta, tb, sa, sb, nlp_tok=nlp.tokenizer)
            f.write(json.dumps({"id": iid, **r, "rule_version": SF.RULE_VERSION}) + "\n")
    print("done", round(time.time() - t0), flush=True)


if __name__ == "__main__":
    main()
