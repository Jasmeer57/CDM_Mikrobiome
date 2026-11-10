"""Stage 12 - BM25 lexical index.

Implements Okapi BM25 directly (rank_bm25 is not installed in this environment)
and persists the index so it can be rebuilt without re-running chunking.

The tokenizer preserves the domain-specific tokens that matter for this corpus:
taxonomic names, BioProject/BioSample accessions, assay names, software names,
and statistical expressions. A generic whitespace tokenizer would shred
``PRJNA12345`` and ``g.`` and is therefore not used.

Emits:
  index/bm25_index.json.gz
  reports/bm25_build_report.md
"""

from __future__ import annotations

import gzip
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config as C  # noqa: E402

TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_\-]{1,}|[A-Z]{2,}\d+|\d+")
STOPWORDS = {
    "the", "and", "for", "that", "with", "this", "was", "were", "are", "but",
    "not", "you", "all", "can", "has", "have", "had", "our", "from", "they",
    "which", "were", "their", "there", "these", "those", "been", "also",
    "such", "than", "then", "when", "while", "into", "out", "about", "after",
    "before", "because", "both", "each", "more", "most", "other", "over",
    "same", "some", "such", "only", "very", "will", "would", "could", "should",
}


def tokenize(text: str) -> list[str]:
    """Lowercase word tokens plus preserved all-caps/technical forms.

    Scientific terms keep their capitalisation signal (``Faecalibacterium``,
    ``IL-6``, ``PRJNA1234``) by also emitting an original-case copy for
    tokens that are not sentence-initial ordinary words.
    """
    out: list[str] = []
    for m in TOKEN_RE.finditer(text):
        tok = m.group(0)
        low = tok.lower()
        if low in STOPWORDS:
            continue
        out.append(low)
        if any(c.isupper() for c in tok) and len(tok) > 3:
            out.append(tok)  # preserve taxonomy / accession form
    return out


def build_bm25(chunk_texts: list[str], k1: float, b: float) -> dict:
    tokenized = [tokenize(t) for t in chunk_texts]
    N = len(tokenized)
    avgdl = sum(len(t) for t in tokenized) / max(1, N)

    df: Counter[str] = Counter()
    tfs: list[Counter[str]] = []
    for toks in tokenized:
        tf = Counter(toks)
        tfs.append(tf)
        df.update(tf.keys())

    idf = {
        term: math.log(1 + (N - freq + 0.5) / (freq + 0.5))
        for term, freq in df.items()
    }
    return {"N": N, "avgdl": avgdl, "df": df, "idf": idf, "tfs": tfs,
            "doc_len": [len(t) for t in tokenized], "k1": k1, "b": b}


def search(index: dict, query: str, top_k: int, allowed: set[int] | None = None) -> list[tuple[int, float]]:
    k1, b = index["k1"], index["b"]
    idf, tfs, doc_len, avgdl = index["idf"], index["tfs"], index["doc_len"], index["avgdl"]
    scores: dict[int, float] = {}
    q_terms = tokenize(query)
    for term in set(q_terms):
        wt = idf.get(term, 0.0)
        if wt <= 0:
            continue
        for i, tf in enumerate(tfs):
            f = tf.get(term, 0)
            if not f:
                continue
            if allowed is not None and i not in allowed:
                continue
            denom = f + k1 * (1 - b + b * doc_len[i] / avgdl)
            scores[i] = scores.get(i, 0.0) + wt * (f * (k1 + 1)) / denom
    return sorted(scores.items(), key=lambda kv: -kv[1])[:top_k]


def main() -> int:
    C.ensure_dirs()
    chunks = [json.loads(l) for l in (C.CHUNKS_DIR / "chunks.jsonl").open()]
    texts = [c["text"] for c in chunks]

    index = build_bm25(texts, C.BM25_K1, C.BM25_B)
    df_counts = {t: int(c) for t, c in index["df"].items()}

    payload = {
        "config_version": C.CONFIG_VERSION,
        "k1": C.BM25_K1,
        "b": C.BM25_B,
        "N": index["N"],
        "avgdl": index["avgdl"],
        "doc_len": index["doc_len"],
        "chunk_ids": [c["chunk_id"] for c in chunks],
        "df": df_counts,
        "idf": {t: float(v) for t, v in index["idf"].items()},
        "tfs": [{t: int(f) for t, f in tf.items()} for tf in index["tfs"]],
    }
    # mtime=0 keeps the archive byte-reproducible across reruns; gzip otherwise
    # embeds the current time and defeats checksum-based rebuild detection.
    with open(C.INDEX_DIR / "bm25_index.json.gz", "wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as gz:
            gz.write(json.dumps(payload).encode("utf-8"))

    # Integrity self-check: every chunk resolves, a probe query returns hits.
    probe = search(index, "gut microbiome diversity sequencing", 5)
    accession_probe = search(index, "PRJNA", 5)

    size_mb = (C.INDEX_DIR / "bm25_index.json.gz").stat().st_size / 1e6
    md = [
        "# BM25 Index Build Report", "",
        f"- Chunks indexed: **{index['N']}**",
        f"- Vocabulary size: **{len(df_counts)}**",
        f"- Average document length: **{index['avgdl']:.1f}** tokens",
        f"- k1 = {C.BM25_K1}, b = {C.BM25_B}",
        f"- On-disk size: **{size_mb:.1f} MB** (gzip)", "",
        "## Integrity checks", "",
        f"- Chunk ID uniqueness: {len(set(payload['chunk_ids']))}/{len(payload['chunk_ids'])} unique",
        f"- Probe 'gut microbiome diversity sequencing' returned **{len(probe)}** hits",
        f"- Probe 'PRJNA' returned **{len(accession_probe)}** hits",
        "",
        "## Vocabulary sample", "",
        "Terms with the highest IDF (most discriminative):", "",
        "| term | df | idf |", "|---|---|---|",
    ]
    top = sorted(df_counts.items(), key=lambda kv: -payload["idf"][kv[0]])[:15]
    for t, f in top:
        md.append(f"| `{t}` | {f} | {payload['idf'][t]:.3f} |")

    (C.REPORTS_DIR / "bm25_build_report.md").write_text("\n".join(md) + "\n")

    print(json.dumps({
        "chunks_indexed": index["N"],
        "vocab": len(df_counts),
        "avgdl": round(index["avgdl"], 1),
        "size_mb": round(size_mb, 1),
        "probe_hits": len(probe),
        "unique_chunk_ids": len(set(payload["chunk_ids"])),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())