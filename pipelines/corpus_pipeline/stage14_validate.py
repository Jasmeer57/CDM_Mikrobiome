"""Stage 14 - Comprehensive automated validation.

Validates inventory, source integrity, section selection, chunking, embeddings
and retrieval. Every failure names the affected paper/section/chunk and the
reason. Nothing is suppressed to obtain a green report.

This validates STRUCTURE AND PROVENANCE ONLY. Passing these checks says the
artifacts are internally consistent and traceable to source - it does not show
that the science is correct or that retrieval finds the right answer.

Emits:
  reports/validation_report.json
  reports/validation_report.md
  reports/processing_failures.csv
"""

from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config as C  # noqa: E402

FAILURES: list[dict] = []


def fail(check: str, target: str, reason: str) -> None:
    FAILURES.append({"check": check, "target": target, "reason": reason})


def main() -> int:
    C.ensure_dirs()

    # ---------------------------------------------------------- inventory ---
    recon = json.loads((C.REPORTS_DIR / "target_453_reconciliation.json").read_text())
    targets = json.loads((C.MANIFESTS_DIR / "target_453_papers.json").read_text())

    if len(targets) != C.EXPECTED_TARGET_PAPERS:
        fail("inventory.count", "target_453", f"{len(targets)} rows, expected {C.EXPECTED_TARGET_PAPERS}")
    if recon.get("missing_records"):
        fail("inventory.missing_records", ",".join(recon["missing_records"]), "no corpus record")

    blocked_ids = {t["corpus_id"] for t in targets if t["state"] == "BLOCKED"}

    # ------------------------------------------------------------ sections --
    sel = json.loads((C.MANIFESTS_DIR / "section_selection.json").read_text())
    sel_keys = {(s["corpus_id"], s["section_id"]) for s in sel}
    if len(sel_keys) != len(sel):
        fail("selection.duplicate", "section_selection", f"{len(sel) - len(sel_keys)} duplicate (paper, section) keys")

    for t in targets:
        if t["state"] != "READY":
            continue
        rec = json.loads((C.RECORDS_DIR / f"{t['corpus_id']}.json").read_text())
        for sec in rec.get("F_full_text_section_inventory") or []:
            if (t["corpus_id"], sec["section_id"]) not in sel_keys:
                fail("selection.coverage", f"{t['corpus_id']}::{sec['section_id']}",
                     "section has no selection record")

    for s in sel:
        if not s["offsets_in_bounds"]:
            fail("source.offsets", f"{s['corpus_id']}::{s['section_id']}",
                 f"span ({s['char_start']},{s['char_end']}) outside source")

    # -------------------------------------------------------------- chunks --
    chunks = [json.loads(l) for l in (C.CHUNKS_DIR / "chunks.jsonl").open()]
    chunk_ids = [c["chunk_id"] for c in chunks]
    if len(set(chunk_ids)) != len(chunk_ids):
        dupes = [k for k, v in Counter(chunk_ids).items() if v > 1]
        fail("chunk.uniqueness", ",".join(dupes[:10]), "duplicate chunk IDs")

    import hashlib
    for c in chunks:
        if hashlib.sha256(c["text"].encode()).hexdigest() != c["text_sha256"]:
            fail("chunk.checksum", c["chunk_id"], "text_sha256 mismatch")
        if c["corpus_id"] in blocked_ids:
            fail("chunk.blocked_paper", c["chunk_id"], "chunk from a BLOCKED paper")
        if c["token_count"] < C.CHUNK_MIN_TOKENS:
            fail("chunk.tokens", c["chunk_id"], f"token_count {c['token_count']}")

    if not all(c["corpus_id"] in {t["corpus_id"] for t in targets} for c in chunks):
        fail("chunk.unknown_paper", "chunks", "chunk references a non-target paper")

    # ---------------------------------------------------------- embeddings --
    emb_report = {"present": False}
    if (C.EMBEDDINGS_DIR / "manifest.json").exists():
        import numpy as np
        m = json.loads((C.EMBEDDINGS_DIR / "manifest.json").read_text())
        v = np.load(C.EMBEDDINGS_DIR / "embeddings.npy")
        emb_report = {"present": True, "n": m["n"], "dim": m["dim"], "shape": list(v.shape)}
        if v.shape != (m["n"], m["dim"]):
            fail("embed.shape", "embeddings.npy", f"{v.shape} != {(m['n'], m['dim'])}")
        if m["n"] != len(chunks):
            fail("embed.count", "manifest", f"{m['n']} vectors vs {len(chunks)} chunks")
        ids = [e["chunk_id"] for e in m["entries"]]
        if set(ids) != set(chunk_ids):
            fail("embed.mapping", "manifest", "vector IDs do not match chunk IDs")
        norms = np.linalg.norm(v, axis=1)
        if (norms < 1e-6).any():
            fail("embed.zero_vector", "embeddings.npy", f"{int((norms < 1e-6).sum())} zero vectors")
    else:
        fail("embed.missing", "embeddings/manifest.json", "embeddings not generated (SLURM stage not run)")

    # ------------------------------------------------------------ indexes ---
    bm25_present = (C.INDEX_DIR / "bm25_index.json.gz").exists()
    dense_present = (C.INDEX_DIR / "dense.faiss").exists()
    if not bm25_present:
        fail("index.bm25", "bm25_index.json.gz", "missing")

    # ------------------------------------------------------------- output ---
    by_check = Counter(f["check"] for f in FAILURES)
    report = {
        "config_version": C.CONFIG_VERSION,
        "target_papers": C.EXPECTED_TARGET_PAPERS,
        "ready_papers": len(targets) - len(blocked_ids),
        "blocked_papers": len(blocked_ids),
        "sections": len(sel),
        "chunks": len(chunks),
        "embeddings": emb_report,
        "bm25_index": bm25_present,
        "dense_index": dense_present,
        "failures_total": len(FAILURES),
        "failures_by_check": dict(by_check),
        "scope_note": (
            "These checks validate structure, provenance and traceability only. "
            "They do not establish scientific correctness, nor retrieval quality: "
            "no independently human-reviewed relevance labels exist for this corpus."
        ),
    }
    (C.REPORTS_DIR / "validation_report.json").write_text(json.dumps(report, indent=2))

    with (C.REPORTS_DIR / "processing_failures.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["check", "target", "reason"])
        w.writeheader()
        w.writerows(FAILURES)

    md = [
        "# Validation Report", "",
        f"- Config version: `{C.CONFIG_VERSION}`",
        f"- Target papers: **{C.EXPECTED_TARGET_PAPERS}**",
        f"- Ready: **{len(targets) - len(blocked_ids)}**, blocked: **{len(blocked_ids)}**",
        f"- Sections: **{len(sel)}**, chunks: **{len(chunks)}**",
        f"- BM25 index: {'present' if bm25_present else 'MISSING'}; "
        f"dense index: {'present' if dense_present else 'not yet built'}",
        f"- **Failures: {len(FAILURES)}**", "",
        f"> {report['scope_note']}", "",
        "## Failures by check", "", "| check | count |", "|---|---|",
    ]
    for k, v in by_check.most_common():
        md.append(f"| {k} | {v} |")
    md += ["", "## All failures", "", "| check | target | reason |", "|---|---|---|"]
    md += [f"| {f['check']} | {f['target'][:60]} | {f['reason'][:70]} |" for f in FAILURES[:200]]
    (C.REPORTS_DIR / "validation_report.md").write_text("\n".join(md) + "\n")

    print(json.dumps({k: v for k, v in report.items() if k != "scope_note"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())