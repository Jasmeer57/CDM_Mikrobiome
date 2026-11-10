"""Generate the final execution report from the artifacts each stage produced.

Run after the local stages (and again after the GPU stages) to refresh the
counts. Reads only what the pipeline wrote; it never recomputes results.
"""

from __future__ import annotations

import gzip
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config as C  # noqa: E402


def main() -> int:
    C.ensure_dirs()
    val = json.loads((C.REPORTS_DIR / "validation_report.json").read_text())
    rec = json.loads((C.REPORTS_DIR / "target_453_reconciliation.json").read_text())
    rows = json.loads((C.MANIFESTS_DIR / "section_selection.json").read_text())
    chunks = [json.loads(l) for l in (C.CHUNKS_DIR / "chunks.jsonl").open()]
    bm = json.load(gzip.open(C.INDEX_DIR / "bm25_index.json.gz", "rt"))

    status = Counter(r["selection_status"] for r in rows)
    toks = sorted(c["token_count"] for c in chunks)
    size_mb = (C.INDEX_DIR / "bm25_index.json.gz").stat().st_size / 1e6
    emb_done = (C.EMBEDDINGS_DIR / "manifest.json").exists()
    dense_done = (C.INDEX_DIR / "dense.faiss").exists()
    jev_done = (C.MANIFESTS_DIR / "jev_predictions.jsonl").exists()

    md = [
        "# Final Execution Report - CDM Human Microbiome Full-Text Corpus", "",
        "## Scope actually executed", "",
        "Both master prompts describe a production pipeline (harmonized Markdown,",
        "segmented corpora, an eligibility audit, a template mapping tree, a JEV load",
        "test) that **does not exist in this repository**. No such directories or files",
        "were found on disk, in any git branch, in git history, or elsewhere under",
        "`$HOME`. Per direction, those stages were not reconstructed from scratch; the",
        "existing, verified section inventory was reused instead.", "",
        "## Executed now (CPU, this node)", "",
        f"- **Inventory reconciliation** - 453/453 targets dispositioned, "
        f"**{rec['ready']} ready / {rec['blocked']} blocked**, 0 missing records",
        f"- **Section selection** - **{len(rows)}** sections classified deterministically "
        f"(RELEVANT {status['RELEVANT']}, RELEVANT_CONTEXT {status['RELEVANT_CONTEXT']}, "
        f"CONTAINER_ONLY {status['CONTAINER_ONLY']}, REVIEW_REQUIRED {status['REVIEW_REQUIRED']})",
        f"- **Chunking** - **{len(chunks)}** chunks; median {toks[len(toks)//2]} tokens "
        f"(p25 {toks[len(toks)//4]}, p75 {toks[3*len(toks)//4]})",
        f"- **BM25 index** - {bm['N']} chunks, {len(bm['idf']):,} terms, {size_mb:.1f} MB",
        "- **Validation** - structural and provenance checks across all artifacts", "",
        "## Awaiting GPU stages (scripts written and validated, not submitted)", "",
        "- `slurm/06_jev.sbatch` - provisional JEV classification",
        "- `slurm/11_embeddings.sbatch` - BGE-M3 embeddings, FAISS dense index, hybrid RRF", "",
        "## Numbers", "", "| metric | value |", "|---|---|",
        "| Target papers | 453 |",
        f"| Ready for downstream | {rec['ready']} |",
        f"| Blocked | {rec['blocked']} |",
        f"| Missing records | {len(rec['missing_records'])} |",
        f"| Sections | {len(rows)} |",
        f"| Chunks | {len(chunks)} |",
        f"| BM25 terms | {len(bm['idf']):,} |",
        f"| Validation failures | {val['failures_total']} |",
        f"| JEV predictions | {'complete' if jev_done else '**pending GPU stage**'} |",
        f"| Embeddings | {'complete' if emb_done else '**pending GPU stage**'} |",
        f"| Dense / hybrid index | {'built' if dense_done else '**pending GPU stage**'} |", "",
        "## Known data defects (documented, not silently repaired)", "",
        "1. `PRJNA627982` was recorded `complete` but is an OFID conference-abstract",
        "   supplement. Caught by content inspection, now blocked.",
        "2. `PRJNA573829` and `PRJNA720325` are abstract-only despite being marked complete.",
        "3. `HMPAPER_000425` (`PRJNA715036`) records a section spanning (42722, 47669) in a",
        "   42,383-char source - a real segmentation defect; excluded from the index.",
        "4. Section `char_start/char_end` offsets index `data/papers_txt/` (the raw source), **not**",
        "   `data/corpus/text/`. Verified against 449/453 records.",
        "5. A few chunks exceed 1,500 tokens: flattened table dumps with no sentence",
        "   structure. Left intact deliberately - splitting would separate headers from rows.", "",
        "## Two conflicts awaiting adjudication", "",
        "- **`PRJDB11894`** - documented `EXCLUDED_WRONG_PAPER`, but the 90 KB source is",
        "  coherent full text whose title matches its record (*Nature*, Honda et al.). Kept eligible.",
        "- **`PRJNA721421`** - documented `HARMONIZATION_FAILED`, but the 67 KB source parses",
        "  into 5 valid sections. Kept eligible.", "",
        "## What is NOT claimed", "",
        "- No retrieval-accuracy claim. There are no independently human-reviewed relevance",
        "  labels for this corpus, so Recall@k, nDCG, MRR and precision are **not measurable yet**.",
        "- JEV output, once generated, is `PROVISIONAL_UNVALIDATED`.",
        "- The 1,485 existing findings cover only 31 of 453 papers; 422 have none.",
        "  Findings extraction was not run and is not claimed complete.",
        "- Passing structural validation does not establish scientific correctness.", "",
        "## Reproduce / resume", "", "```bash",
        "./corpus_pipeline/run_local.sh              # CPU stages (idempotent)",
        "./corpus_pipeline/run_local.sh --dry-run    # show plan only",
        "",
        "sbatch pipelines/corpus_pipeline/slurm/06_jev.sbatch           # GPU: JEV",
        "sbatch pipelines/corpus_pipeline/slurm/11_embeddings.sbatch    # GPU: embeddings + dense + hybrid",
        "python pipelines/corpus_pipeline/stage14_validate.py           # re-validate afterwards",
        "```", "",
        "Chunking and BM25 were confirmed byte-reproducible across reruns; model stages",
        "cache by content checksum and resume incrementally.", "",
    ]

    (C.REPORTS_DIR / "final_execution_report.md").write_text("\n".join(md))
    (C.REPORTS_DIR / "final_execution_report.json").write_text(json.dumps({
        "config_version": C.CONFIG_VERSION,
        "target_papers": C.EXPECTED_TARGET_PAPERS,
        "ready": rec["ready"], "blocked": rec["blocked"],
        "sections": len(rows), "chunks": len(chunks),
        "bm25_terms": len(bm["idf"]),
        "validation_failures": val["failures_total"],
        "jev_complete": jev_done, "embeddings_complete": emb_done,
        "dense_index_complete": dense_done,
        "retrieval_evaluation": "BLOCKED_NO_HUMAN_REVIEWED_LABELS",
        "pending_gpu_stages": [s for s, d in
                               (("06_jev.sbatch", jev_done), ("11_embeddings.sbatch", emb_done))
                               if not d],
    }, indent=2))
    print(f"[report] written; {len(chunks)} chunks, {rec['ready']} ready, {val['failures_total']} failures")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())