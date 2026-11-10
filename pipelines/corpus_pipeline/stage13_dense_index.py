"""Stage 13 - Dense vector index + hybrid retrieval.

Builds a FAISS flat inner-product index over the normalized embeddings and a
hybrid retriever that fuses BM25 and dense rankings with reciprocal rank
fusion (RRF).

Hybrid retrieval returns traceable results: every hit carries the paper,
section, chunk, source locator and heading path so a user can verify it against
the original text.

Emits:
  index/dense.faiss
  index/hybrid_config.json
  reports/rag_index_report.json
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config as C  # noqa: E402


def build_dense() -> dict:
    import numpy as np
    import faiss

    vecs = np.load(C.EMBEDDINGS_DIR / "embeddings.npy")
    manifest = json.loads((C.EMBEDDINGS_DIR / "manifest.json").read_text())
    if vecs.shape != (manifest["n"], C.EMBEDDING_DIM):
        raise SystemExit(f"shape mismatch {vecs.shape} vs manifest {manifest['n']}x{C.EMBEDDING_DIM}")

    index = faiss.IndexFlatIP(vecs.shape[1])  # vectors are L2-normalized
    index.add(vecs)
    faiss.write_index(index, str(C.INDEX_DIR / "dense.faiss"))
    return {"n": int(index.ntotal), "dim": int(vecs.shape[1])}


class HybridRetriever:
    """Reciprocal-rank fusion over a BM25 and a dense index.

    The canonical corpus is never touched: this only reads the persisted
    indexes and the chunk manifest.
    """

    def __init__(self) -> None:
        import faiss
        import gzip

        import stage12_bm25 as bm

        self.chunks = [json.loads(l) for l in (C.CHUNKS_DIR / "chunks.jsonl").open()]
        p = json.load(gzip.open(C.INDEX_DIR / "bm25_index.json.gz", "rt"))
        self.bm25 = {
            "N": p["N"], "avgdl": p["avgdl"], "idf": p["idf"], "df": p["df"],
            "k1": p["k1"], "b": p["b"], "doc_len": p["doc_len"],
            "tfs": [{k: int(v) for k, v in d.items()} for d in p["tfs"]],
        }
        self.dense = faiss.read_index(str(C.INDEX_DIR / "dense.faiss"))

    def search(self, query: str, top_k: int = 10,
               exclude_papers: set[str] | None = None) -> list[dict]:
        import numpy as np
        import stage12_bm25 as bm

        n = len(self.chunks)
        blocked = None
        if exclude_papers:
            blocked = {i for i, c in enumerate(self.chunks)
                       if c["corpus_id"] in exclude_papers}
            if len(blocked) == n:
                return []

        lex = bm.search(self.bm25, query, C.RETRIEVAL_TOP_K_LEXICAL, allowed=blocked)
        try:
            from sentence_transformers import SentenceTransformer
            model = SentenceTransformer(C.EMBEDDING_MODEL, revision=C.EMBEDDING_MODEL_REV)
            qv = model.encode([query], normalize_embeddings=True, convert_to_numpy=True)
        except Exception:
            qv = None

        dense_hits: list[tuple[int, float]] = []
        if qv is not None:
            k = C.RETRIEVAL_TOP_K_DENSE * (2 if blocked else 1)
            scores, ids = self.dense.search(qv, min(k, self.dense.ntotal))
            dense_hits = [(int(i), float(s)) for i, s in zip(ids[0], scores[0])
                          if i >= 0 and (blocked is None or i not in blocked)]

        # Reciprocal rank fusion.
        fused: dict[int, float] = {}
        for rank, (i, _) in enumerate(lex):
            fused[i] = fused.get(i, 0.0) + 1.0 / (C.RRF_K + rank + 1)
        for rank, (i, _) in enumerate(dense_hits):
            fused[i] = fused.get(i, 0.0) + 1.0 / (C.RRF_K + rank + 1)

        top = sorted(fused.items(), key=lambda kv: -kv[1])[:top_k]
        lex_rank = {i: r for r, (i, _) in enumerate(lex)}
        dense_rank = {i: r for r, (i, _) in enumerate(dense_hits)}

        out = []
        for i, score in top:
            c = self.chunks[i]
            out.append({
                "chunk_id": c["chunk_id"],
                "corpus_id": c["corpus_id"],
                "bioproject_accession": c["bioproject_accession"],
                "section_id": c["section_id"],
                "heading_path": c["heading_path"],
                "chunk_type": c["chunk_type"],
                "source_path": f"data/papers_txt/{c['bioproject_accession']}.txt",
                "source_span": [c["char_start"], c["char_end"]],
                "score": round(score, 6),
                "lexical_rank": lex_rank.get(i),
                "dense_rank": dense_rank.get(i),
                "retrieved_by": [m for m, r in
                                 (("bm25", lex_rank), ("dense", dense_rank)) if i in r],
                "text_excerpt": c["text"][:400],
            })
        return out


def main() -> int:
    C.ensure_dirs()
    t0 = time.time()

    manifest = json.loads((C.EMBEDDINGS_DIR / "manifest.json").read_text())
    stats = build_dense()

    (C.INDEX_DIR / "hybrid_config.json").write_text(json.dumps({
        "fusion": "reciprocal_rank_fusion",
        "rrf_k": C.RRF_K,
        "lexical_k": C.RETRIEVAL_TOP_K_LEXICAL,
        "dense_k": C.RETRIEVAL_TOP_K_DENSE,
        "embedding_model": C.EMBEDDING_MODEL,
        "embedding_dim": C.EMBEDDING_DIM,
        "bm25": {"k1": C.BM25_K1, "b": C.BM25_B},
        "reranking": None,
    }, indent=2))

    # Integrity probe.
    probe_query = "gut microbiome alpha diversity"
    try:
        r = HybridRetriever()
        probe = r.search(probe_query, top_k=5)
    except Exception as exc:
        probe = []
        print(f"[warn] retrieval probe failed: {exc}", file=sys.stderr)

    (C.INDEX_DIR / "index_integrity_report.json").write_text(json.dumps({
        "config_version": C.CONFIG_VERSION,
        "dense": stats,
        "bm25_chunks": len([1 for _ in (C.CHUNKS_DIR / "chunks.jsonl").open()]),
        "embedding_model": C.EMBEDDING_MODEL,
        "embedding_revision": C.EMBEDDING_MODEL_REV,
        "hybrid_probe_query": probe_query,
        "hybrid_probe_hits": len(probe),
        "hybrid_probe_top": probe[:3],
        "build_seconds": round(time.time() - t0, 2),
    }, indent=2))

    print(json.dumps({"dense": stats, "probe_hits": len(probe),
                      "seconds": round(time.time() - t0, 2)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())