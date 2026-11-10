# Paper-level rights assessment (proposal, NOT a legal determination)

`PAPER_RIGHTS_MATRIX.csv` gives one row per paper (453), built by `src/scripts/publication/rights_matrix.py` from:
- the licence recorded for each paper (Europe PMC / PMC lookup, `outputs/results/catalogue_v3_licences/paper_licences.csv`);
- the CDM 3.0.3 paper table.

Each content layer is assessed separately, because full text, quotations, metadata and derived annotations do not have the same copyright status.

| Licence | Papers | Full text | Verbatim quotes | Bibliographic metadata | Derived annotations | Proposed decision |
|---|---:|---|---|---|---|---|
| CC BY | 271 | allowed with attribution | allowed with attribution | allowed | allowed with attribution | INCLUDE_TEXT |
| CC0 | 3 | allowed | allowed | allowed | allowed | INCLUDE_TEXT |
| CC BY-NC | 12 | non-commercial only | non-commercial only | allowed | non-commercial only | RESTRICTED_NC_LAYER |
| CC BY-NC-SA | 3 | non-commercial, share-alike | non-commercial, share-alike | allowed | unclear (share-alike) | RESTRICTED_NC_LAYER |
| CC BY-NC-ND | 29 | unclear (no derivatives: is re-segmented text a derivative?) | unclear | allowed | unclear | WITHHOLD_TEXT |
| no licence found | 135 | prohibited | unclear (quotation exceptions vary by jurisdiction) | allowed | likely allowed (facts), database rights unclear | WITHHOLD_TEXT |

**Totals:**
- INCLUDE_TEXT: **274**
- RESTRICTED_NC_LAYER: **15**
- WITHHOLD_TEXT: **164**
- Papers needing legal confirmation: **179**.
- 71 of the 135 no-licence papers are in PMC. They may be in the PMC author-manuscript or "free to read" set, which allows reading, **not** redistribution.

**Consistency:** the proposed text decision matches the quote policy already applied in catalogue 3.1.1 for **453 / 453** papers (KEEP ↔ INCLUDE_TEXT). The 18,502 quotes already redacted with `evidence_redacted = LICENCE` follow the same rule.

## Proposed public release architecture

| Layer | Contents | Public? |
|---|---|---|
| 1 Schema and documentation | CDM schema, data dictionary, vocabulary reference, validation reports | yes |
| 2 Structured metadata | papers (bibliographic), studies, cohorts, samples, assays, datasets, data assets, findings, **without** quote text for WITHHOLD papers | yes, pending legal confirmation for annotations |
| 3 Terminology | canonical terms, mappings with evidence, taxonomy; mention **offsets and hashes** for all papers, surface text only where the paper is INCLUDE_TEXT | yes |
| 4 Evidence quotations | quotes for INCLUDE_TEXT papers; NC layer separate | 274 papers; NC layer under an NC licence |
| 5 Full text / sections | section text for INCLUDE_TEXT papers only; for the others, `section_text_sha256` so users can re-anchor against their own copy | 274 papers |

## Required before public release

1. A rights reviewer, ideally your institution's library or legal office, fills `rights_reviewer`, `final_decision` and `decision_evidence` for the 179 flagged rows. The publisher column is empty because the corpus does not record publishers.
2. Choose the release licence. A CC BY layer and a separate CC BY-NC layer is the simplest option compatible with the matrix.
3. Build the redacted public CDM from 3.0.3 as a new release. Do not edit 3.0.3.
