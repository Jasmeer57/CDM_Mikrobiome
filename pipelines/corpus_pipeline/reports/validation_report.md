# Validation Report

- Config version: `1.0.0`
- Target papers: **453**
- Ready: **435**, blocked: **18**
- Sections: **3105**, chunks: **11980**
- BM25 index: present; dense index: not yet built
- **Failures: 2**

> These checks validate structure, provenance and traceability only. They do not establish scientific correctness, nor retrieval quality: no independently human-reviewed relevance labels exist for this corpus.

## Failures by check

| check | count |
|---|---|
| source.offsets | 1 |
| embed.missing | 1 |

## All failures

| check | target | reason |
|---|---|---|
| source.offsets | HMPAPER_000425::sec_002 | span (42722,47669) outside source |
| embed.missing | embeddings/manifest.json | embeddings not generated (SLURM stage not run) |
