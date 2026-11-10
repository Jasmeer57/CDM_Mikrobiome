# Chunk Coverage Report

- Chunking config: `1.0.0`
- Target chunk size: 512 tokens, overlap 64
- Token measurement: embedding-model tokenizer
- Sections considered: **3105**
- Sections producing chunks: **2046**
- Sections excluded: **1333**
- **Chunks written: 11980**

Token counts - min 80, median 481, max 18323

## Exclusions from the primary retrieval index

| reason | sections |
|---|---|
| container section (references/funding/etc.) | 880 |
| dropped 1 sub-80-token fragment(s) | 429 |
| dropped 2 sub-80-token fragment(s) | 20 |
| dropped 3 sub-80-token fragment(s) | 3 |
| source offsets out of bounds | 1 |

No text is deleted from source. Excluded sections remain recoverable in the
section-selection manifest and can be re-chunked if rules change.
