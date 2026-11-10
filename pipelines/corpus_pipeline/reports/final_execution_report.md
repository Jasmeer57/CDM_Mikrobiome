# Final Execution Report - CDM Human Microbiome Full-Text Corpus

## Scope actually executed

Both master prompts describe a production pipeline (harmonized Markdown,
segmented corpora, an eligibility audit, a template mapping tree, a JEV load
test) that **does not exist in this repository**. No such directories or files
were found on disk, in any git branch, in git history, or elsewhere under
`$HOME`. Per direction, those stages were not reconstructed from scratch; the
existing, verified section inventory was reused instead.

## Executed now (CPU, this node)

- **Inventory reconciliation** - 453/453 targets dispositioned, **435 ready / 18 blocked**, 0 missing records
- **Section selection** - **3105** sections classified deterministically (RELEVANT 2040, RELEVANT_CONTEXT 110, CONTAINER_ONLY 881, REVIEW_REQUIRED 74)
- **Chunking** - **11980** chunks; median 481 tokens (p25 429, p75 500)
- **BM25 index** - 11980 chunks, 134,960 terms, 7.3 MB
- **Validation** - structural and provenance checks across all artifacts

## Awaiting GPU stages (scripts written and validated, not submitted)

- `slurm/06_jev.sbatch` - provisional JEV classification
- `slurm/11_embeddings.sbatch` - BGE-M3 embeddings, FAISS dense index, hybrid RRF

## Numbers

| metric | value |
|---|---|
| Target papers | 453 |
| Ready for downstream | 435 |
| Blocked | 18 |
| Missing records | 0 |
| Sections | 3105 |
| Chunks | 11980 |
| BM25 terms | 134,960 |
| Validation failures | 2 |
| JEV predictions | **pending GPU stage** |
| Embeddings | **pending GPU stage** |
| Dense / hybrid index | **pending GPU stage** |

## Known data defects (documented, not silently repaired)

1. `PRJNA627982` was recorded `complete` but is an OFID conference-abstract
   supplement. Caught by content inspection, now blocked.
2. `PRJNA573829` and `PRJNA720325` are abstract-only despite being marked complete.
3. `HMPAPER_000425` (`PRJNA715036`) records a section spanning (42722, 47669) in a
   42,383-char source - a real segmentation defect; excluded from the index.
4. Section `char_start/char_end` offsets index `papers_txt/` (the raw source), **not**
   `data/corpus/text/`. Verified against 449/453 records.
5. A few chunks exceed 1,500 tokens: flattened table dumps with no sentence
   structure. Left intact deliberately - splitting would separate headers from rows.

## Two conflicts awaiting adjudication

- **`PRJDB11894`** - documented `EXCLUDED_WRONG_PAPER`, but the 90 KB source is
  coherent full text whose title matches its record (*Nature*, Honda et al.). Kept eligible.
- **`PRJNA721421`** - documented `HARMONIZATION_FAILED`, but the 67 KB source parses
  into 5 valid sections. Kept eligible.

## What is NOT claimed

- No retrieval-accuracy claim. There are no independently human-reviewed relevance
  labels for this corpus, so Recall@k, nDCG, MRR and precision are **not measurable yet**.
- JEV output, once generated, is `PROVISIONAL_UNVALIDATED`.
- The 1,485 existing findings cover only 31 of 453 papers; 422 have none.
  Findings extraction was not run and is not claimed complete.
- Passing structural validation does not establish scientific correctness.

## Reproduce / resume

```bash
./corpus_pipeline/run_local.sh              # CPU stages (idempotent)
./corpus_pipeline/run_local.sh --dry-run    # show plan only

sbatch corpus_pipeline/slurm/06_jev.sbatch           # GPU: JEV
sbatch corpus_pipeline/slurm/11_embeddings.sbatch    # GPU: embeddings + dense + hybrid
python corpus_pipeline/stage14_validate.py           # re-validate afterwards
```

Chunking and BM25 were confirmed byte-reproducible across reruns; model stages
cache by content checksum and resume incrementally.
