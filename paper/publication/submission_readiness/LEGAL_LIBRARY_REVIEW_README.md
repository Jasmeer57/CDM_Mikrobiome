# Legal / library review: cover note

*Prepared 2026-11-02. **No legal determination has been made by anyone, and none by a model.** Every decision column in the CSV is blank.*

**What we ask:** for each of the **179** papers in `LEGAL_LIBRARY_REVIEW_PACKAGE.csv`, decide which layers of a public data release may include material from that paper.

| Layer | Content |
|---|---|
| Bibliographic metadata | IDs, title, journal, DOI, BioProject. Proposed: release for all papers as facts |
| Derived annotations | catalogue values, terms, mappings, triples, character offsets, text hashes |
| Verbatim quotations | evidence quotes of 300 characters or fewer |
| Full section text | the papers' text, split into sections |

**The 179 papers by recorded licence:**
- **135 with no licence found:** the question is whether quotation exceptions or database rights apply in our jurisdiction.
- **29 CC BY-NC-ND:** is re-segmented text, quotation or annotation "adapted material"?
- **12 CC BY-NC:** the release licence must be NC-compatible.
- **3 CC BY-NC-SA:** does share-alike bind the derived layers?

The other 274 papers are CC BY or CC0 and are proposed for full inclusion with attribution. They are not part of this review unless the reviewer wishes to check them.

**Columns to fill:** `reviewer_name`, `review_date`, `decision` (from `decision_options`), `decision_basis_or_evidence`, `conditions_or_notes`.

**Supporting material:**
- `paper/publication/rights/RIGHTS_ASSESSMENT.md`
- `PAPER_RIGHTS_MATRIX.csv`
- `paper/publication/final_validation/RIGHTS_READINESS_REPORT.md`

**Known gap:** six papers (HMPAPER_000063, 073, 117, 170, 249, 419) have no DOI or title recorded. Their BioProject accession is given; the authors will supply the bibliographic details.

**Also needed from the reviewer:** advice on the release licence(s): CC BY for the open layer, and whether a separate NC layer is advisable. The journal policy (*Scientific Data*) expects open licences (CC BY / CC0) for openly shared data.

**What happens next:** the authors apply the decisions to a new, redacted release derived from CDM 3.0.3 (3.0.3 itself stays unchanged), verify its manifest and deposit it with a DOI.
