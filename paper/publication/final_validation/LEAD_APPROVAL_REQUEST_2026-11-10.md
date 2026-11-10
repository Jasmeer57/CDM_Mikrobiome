# Decisions needed from the project lead (2026-11-10)

The development freeze of 2026-11-02 requires your approval for every new model run and for human annotation. Since then, the layers below were built. **None of them is approved yet.** Each one is logged in `CHANGE_RECORD.md`, and its numbers are in the claims register (ID in brackets). Frozen CDM 3.0.3 is unchanged. CDM 3.1.0 = 3.0.3 plus these layers as new tables.

Please mark each row **Approve** / **Reject** / **Discuss**. Rejected layers stay out of the manuscript and the deposit.

## A. Layers in CDM 3.1.0

| # | Layer | What it does | Key numbers | Risk | Decision |
|---|---|---|---|---|---|
| A1 | Term and concept dedup | Merges duplicates in three passes: exact, fuzzy, embedding (SapBERT/MiniLM, offline) | terms 162,409 → 157,815; concepts 13,330 → 12,182 [CL01, CL02] | low; no human check of merges | |
| A2 | Relevance screens | FhGenie (DeepSeek-V4.1-Flash) labels each term/concept KEEP, NOT_A_CONCEPT, IRRELEVANT or UNSURE; only labels are sent | 116,755 terms and 11,912 concepts kept [CL01, CL02] | external service; 13,138 sent labels occur only in text-withheld papers [RT05] | |
| A3 | Clean mappings | Accepted mappings restricted to the kept terms and concepts | 15,769 rows; 13,540 EXACT [CL03, CL04] | low | |
| A4 | Definitions, full forms, synonyms | Local Qwen3.5-4B (nothing sent out), labelled MODEL_ | 120,091 contextual definitions [CL08]; 2,061 terms flagged for rights and emptied in the public build [RT06] | model-generated; not curated | |
| A5 | Triple repair and tiers | Re-types relations using a closed list with abstain options; checks the cue text | 9,621 specific, 8,307 with a verified cue; tiers 1,794 / 6,263 / 17,731 [CL05, CL06, CL12] | 14,867 triples have no specific relation [CL07] | |
| A6 | Schema-enforced catalogue judges | Re-runs the frozen judge prompt with the output format enforced | invalid output (Mistral) 53.5% → 0.1%; κ 0.293; AC1 0.771 [CL11, CL15] | none new | |

## B. Outside 3.1.0

| # | Item | Key numbers | Decision |
|---|---|---|---|
| B1 | Triple dedup (post-3.1.0) | 23,339 clean triples; 61.6% have no specific relation [CL13, CL14] | |
| B2 | **Human spot checks (item 7)**: 100 triples with 2 annotators; 500 mappings with a second reviewer on 100 of them | Reviewer A has finished the 500 mappings: 61.8% EXACT, 6.2% WRONG. If reported, every "no human annotation" statement must change (H01) | |
| B3 | **W01 disclosure**: 9,629 sentences from non-CC-BY/CC0 papers went to FhGenie in the 2026-11-07 triple screen. Results are reported on CC BY/CC0 sentences only | Choose one: (a) disclose as is; (b) also re-run CC BY/CC0-only (new FhGenie run, sentences of open papers only) | |
| B4 | **Deposit**: upload `releases/zenodo_r2_310` (built locally, rights scan included) | Also needs the legal review of 179 papers (B1) and the licence choice (B2) | |
| B5 | Make the 3.1.0 tables the cited resource (the manuscript currently cites 3.0.3 in 9 places) | — | |

Contact: Jasmeer Singh Kalra. Sources: `CHANGE_RECORD.md` (2026-11-09 and 2026-11-10 entries) and `MANUSCRIPT_CLAIMS_REGISTER.csv`.
