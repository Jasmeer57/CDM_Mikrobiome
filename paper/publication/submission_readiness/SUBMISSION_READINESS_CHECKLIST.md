# Submission readiness checklist

*2026-11-02. ✅ done and verified · ⏳ needs people outside the project · ❗ authors' decision · ⬜ not started. Blocker IDs refer to `final_validation/REMAINING_PUBLICATION_BLOCKERS.csv`.*

## A. Frozen science (no further development)

| | Item | Evidence |
|---|---|---|
| ✅ | Releases frozen and verified: corpus, terminology 1.0.1, catalogue 3.1.1, CDM 3.0.3 | every cited release manifest verifies (`sha256sum -c`) |
| ✅ | Validation results frozen, read-only | `final_validation/FINAL_VALIDATION_MANIFEST.sha256` (119 files) |
| ✅ | B15 legacy bundles: closed as a false positive; nothing restored or modified | `B15_LEGACY_BUNDLE_DECISION.md` |
| ✅ | No human annotation, by decision; stated in every section | `FINAL_MANUSCRIPT_QA.md` §5 |

## B. Manuscript

| | Item | Evidence / next step |
|---|---|---|
| ✅ | Every number traceable (278 numbers, 0 untraced); register 88 / 88 MATCH | `MANUSCRIPT_NUMBER_AUDIT.csv`, `MANUSCRIPT_CLAIMS_REGISTER.csv` |
| ✅ | References verified from registries (41 / 41); citation keys in drafts | `VERIFIED_REFERENCES.md` |
| ✅ | Each reference checked against its claim; 5 sentences revised | `REFERENCE_TO_CLAIM_MAPPING.csv`, QA §3 |
| ✅ | Prohibited-claim scan; 3 fixes | QA §4 |
| ❗ | Journal and article type (B17). **Target since 2026-11-03: *Briefings in Bioinformatics*, Problem Solving Protocol (2,000–5,000 words)**. Plan: `../manuscript_bib/BIB_MANUSCRIPT_PLAN.md`; requirements: `journal_requirements_source/bib/BIB_REQUIREMENTS.md`. BiB does not accept LLM-drafted papers, so the authors write the text and declare AI use. Fallback: *Scientific Data* Data Descriptor (restructure; move or condense the benchmark; title of 110 characters or fewer) | QA §6 |
| ⬜ | Abstract (at most 170 words), Data Records, Usage Notes | B9 |
| ⬜ | Code Availability: choose a licence, publish a versioned repository / Zenodo snapshot (B16) | no LICENSE file; repository not under version control |
| ⏳ | Data Availability: depends on B1–B4 | Methods `[PENDING]` |
| ⬜ | Three reference open items (GLiNER v2.5 biomed paper; Qwen3.5; Mondo peer-reviewed version) | `VERIFIED_REFERENCES.md` "Unresolved" |
| ⬜ | Cite S4–S6 in text or drop them; produce figures | `FIGURE_PLAN.md` |
| ❗ | Recommended: pre-submission enquiry on acceptability without human accuracy evaluation (B20) | QA §6 |

## C. External reviews (run in parallel)

| | Item | Who | Package |
|---|---|---|---|
| ⏳ | Independent CDM expert review (B5): six questions; findings classified critical / major / minor | external biomedical-informatics expert, not involved in the pipeline | `CDM_EXPERT_REVIEW_PACKAGE.md`, `cdm_review/EXAMPLE_RECORDS_HMPAPER_000258.json` |
| ⏳ | Legal / library review of 179 papers (B1), plus licence advice (B2) | institutional library / legal office | `LEGAL_LIBRARY_REVIEW_PACKAGE.csv`, `LEGAL_LIBRARY_REVIEW_README.md` |
| ⬜ | Six papers missing DOI and title (B19) | authors | listed in the legal README |

## D. Release (after B1–B2)

| | Step |
|---|---|
| ⬜ | 1. Apply the legal decisions: final release layers and licence(s) |
| ⬜ | 2. Generate the redacted public release from CDM 3.0.3 (a new release; 3.0.3 unchanged) |
| ⬜ | 3. Verify the manifest, integrity and that no withheld text is present |
| ⬜ | 4. Deposit in a formal repository with a DOI (B4) |
| ⬜ | 5. Update Data Availability and data citation |

## E. Data for first-round review (B18)

*Scientific Data* requires reviewers to be able to download the data anonymously at first-round review. A temporary location is allowed; a DOI is not required until later rounds.

- **Before the legal review completes,** only a **conservative build** is safe to share: all derived annotations, offsets and hashes, with text and quotations **only** for the 274 CC BY / CC0 papers.
- **Even that build** includes derived annotations for the 135 papers without a licence. The legal reviewer should confirm that this is acceptable before anything is shared.
- **Authors' decision:** build this interim package, or wait for B1.

## Who must act

| Who | Action |
|---|---|
| **Authors** | journal and article type (B17); pre-submission enquiry (B20); code licence and repository (B16); Abstract, Data Records and Usage Notes; reference open items; six missing identifiers (B19); recruit the CDM reviewer; send the legal package |
| **External CDM expert** | written review per `CDM_EXPERT_REVIEW_PACKAGE.md` |
| **Library / legal office** | decisions for 179 papers and licence advice |
| **Pipeline (after decisions)** | redacted release, verification, DOI deposit; no new extraction or modelling |

## Required before journal submission

Minimum, assuming *Scientific Data*:
1. Article type chosen and manuscript restructured.
2. Code Availability with a public repository.
3. Reviewer-accessible data download: conservative build or legal-cleared build.
4. Abstract, Data Records, Usage Notes.
5. Reference open items resolved.

**Not strictly required at initial submission, but needed before acceptance:**
- the legal review and redacted DOI release;
- the CDM expert review, if the paper is to claim anything about semantic suitability. The current drafts make no such claim.
