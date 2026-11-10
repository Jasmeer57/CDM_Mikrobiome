# Rights and public-release readiness

**No legal determination has been made**, by a person or by a model. Everything below is a proposed policy derived from each paper's recorded licence. A human rights review must confirm it. Detail is in `../rights/RIGHTS_ASSESSMENT.md` and `../rights/PAPER_RIGHTS_MATRIX.csv`.

## Status

| Item | Status |
|---|---|
| Per-paper licence recorded | 318 / 453 with a CC licence; 135 none found |
| Proposed text treatment | include 274 (CC BY, CC0) · NC layer 15 · withhold 164 |
| Papers needing confirmation | **179**: 135 without licence, 29 CC BY-NC-ND, 12 CC BY-NC, 3 CC BY-NC-SA |
| Consistency with quotes already redacted in catalogue 3.1.1 | 453 / 453 |
| NC layer | **not cleared**: requires the release licence to be NC-compatible, and confirmation |
| Confirmed permissions | **none yet** |

## Proposed release policies (for the rights reviewer to confirm or amend)

| Content | Proposed policy |
|---|---|
| **Bibliographic metadata** (IDs, title, journal, DOI, BioProject) | release for all 453 papers (facts) |
| **Derived structured annotations** (catalogue values, terms, mappings, triples, offsets, hashes) | release for all papers, **subject to confirmation** for the 164 withheld papers (database rights; values that are verbatim text) |
| **Verbatim quotations** | release only for the 274 CC BY / CC0 papers with attribution; NC papers in a separate NC-licensed layer if cleared; withhold otherwise |
| **Full text / section text** | release only for the 274 CC BY / CC0 papers; others: `section_text_sha256` + offsets only |
| **Restricted content** | the 164 withheld papers' text and quotes never enter a public build |
| **Redacted build** | a new release derived from CDM 3.0.3 that drops `section_text_original` and evidence text for non-cleared papers, keeps hashes and offsets, and ships the rights matrix; 3.0.3 itself stays internal |

## Blocking public release

1. Human or legal review of the 179 flagged papers.
2. A decision on the release licence or licences.
3. The redacted build and its verification.
4. Zenodo deposit and DOI.

None of these can be completed computationally.
