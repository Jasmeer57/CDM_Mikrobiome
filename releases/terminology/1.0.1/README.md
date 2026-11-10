# Terminology Build 1.0.1 — frozen release

Corrections: (1) character offsets of mentions and definitions, (2) mention -> canonical term links.

Derived from `releases/terminology/1.0.0` (kept unchanged). Only the character offsets of `term_mentions.jsonl` and `term_definitions.jsonl` change: in 75 sections every row was shifted by a constant [1, 2] characters (all extraction models alike), so `section_text[start:end]` missed the term by one or two characters. The shift is found per section by majority vote and applied only where the shifted span equals the stored text. Ids, `occurrence_key` and supporting text are unchanged.

New fields: `offset_status` (EXACT / CORRECTED / UNANCHORED) and `offset_correction`.

`canonical_term_id` was null on every mention in 1.0.0; it is now set by normalized_mention == term_norm (type breaks ties; otherwise AMBIGUOUS), with `term_link_status`: AMBIGUOUS 7,072, LINKED 2,168,760, LINKED_BY_TYPE 30,049, NO_CANONICAL_TERM 299,854.

| file | EXACT | CORRECTED | UNANCHORED |
|---|---:|---:|---:|
| term_mentions.jsonl | 2,348,766 | 156,884 | 85 |
| term_definitions.jsonl | 1,087 | 63 | 0 |

All other files are hard links to the 1.0.0 files (identical bytes). Details: `OFFSET_FIX_REPORT.json`.

Verify: `sha256sum -c MANIFEST.sha256`
