"""Stage 9 - Embedding generation (GPU/SLURM stage).

Embeds the chunk corpus with the configured sentence-transformers model and
writes a cached float32 matrix plus a manifest mapping every vector back to its
chunk ID and text checksum.

Caching is keyed on (text_sha256, model, revision, dim) so reruns are
incremental and a changed chunk regenerates only its own vector.

Emits:
  embeddings/embeddings.npy
  embeddings/manifest.json
  reports/embedding_manifest.csv
"""

from __future__ import annotations

import csv
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config as C  # noqa: E402


def main() -> int:
    C.ensure_dirs()
    import numpy as np
    from sentence_transformers import SentenceTransformer

    chunks = [json.loads(l) for l in (C.CHUNKS_DIR / "chunks.jsonl").open()]
    n = len(chunks)

    manifest_path = C.EMBEDDINGS_DIR / "manifest.json"
    cache_path = C.EMBEDDINGS_DIR / "embeddings.npy"

    # ---------------------------------------------------------- load cache --
    vectors = np.zeros((n, C.EMBEDDING_DIM), dtype=np.float32)
    prev_hashes: dict[str, str] = {}

    if manifest_path.exists() and cache_path.exists():
        prev = json.loads(manifest_path.read_text())
        if (prev.get("model") == C.EMBEDDING_MODEL
                and prev.get("revision") == C.EMBEDDING_MODEL_REV
                and prev.get("dim") == C.EMBEDDING_DIM):
            mat = np.load(cache_path)
            prev_hashes = {e["chunk_id"]: e["text_sha256"] for e in prev["entries"]}
            prev_rows = {e["chunk_id"]: e["row"] for e in prev["entries"]}
            for i, c in enumerate(chunks):
                row = prev_rows.get(c["chunk_id"])
                if (row is not None and row < mat.shape[0]
                        and prev_hashes.get(c["chunk_id"]) == c["text_sha256"]):
                    vectors[i] = mat[row]

    fresh = [i for i, c in enumerate(chunks) if prev_hashes.get(c["chunk_id"]) != c["text_sha256"]]
    print(f"[embed] {n - len(fresh)} cached, {len(fresh)} to compute")

    todo = fresh

    if todo:
        model = SentenceTransformer(C.EMBEDDING_MODEL, revision=C.EMBEDDING_MODEL_REV)
        dim = model.get_sentence_embedding_dimension()
        if dim != C.EMBEDDING_DIM:
            raise SystemExit(f"model dim {dim} != configured {C.EMBEDDING_DIM}")
        t0 = time.time()
        texts = [chunks[i]["text"] for i in todo]
        vecs = model.encode(texts, batch_size=C.EMBED_BATCH_SIZE, show_progress_bar=True,
                            normalize_embeddings=True, convert_to_numpy=True)
        for j, i in enumerate(todo):
            vectors[i] = vecs[j]
        print(f"[embed] encoded {len(todo)} in {time.time() - t0:.1f}s")

    np.save(cache_path, vectors)

    entries = [{"chunk_id": c["chunk_id"], "row": i, "text_sha256": c["text_sha256"]}
               for i, c in enumerate(chunks)]
    manifest_path.write_text(json.dumps({
        "model": C.EMBEDDING_MODEL,
        "revision": C.EMBEDDING_MODEL_REV,
        "dim": C.EMBEDDING_DIM,
        "n": n,
        "normalized": True,
        "entries": entries,
    }))

    with (C.REPORTS_DIR / "embedding_manifest.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["row", "chunk_id", "corpus_id", "text_sha256"])
        for e in entries:
            w.writerow([e["row"], e["chunk_id"],
                        chunks[e["row"]]["corpus_id"], e["text_sha256"]])

    norms = np.linalg.norm(vectors, axis=1)
    print(json.dumps({
        "chunks": n, "dim": C.EMBEDDING_DIM,
        "zero_vectors": int((norms < 1e-6).sum()),
        "mean_norm": round(float(norms.mean()), 4),
        "index_mb": round(cache_path.stat().st_size / 1e6, 1),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())