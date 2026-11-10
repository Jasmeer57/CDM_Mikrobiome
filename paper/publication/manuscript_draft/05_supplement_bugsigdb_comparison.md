# Supplementary analysis: direct comparison with BugSigDB

*Draft 0.1, 2026-11-03. Claim IDs in brackets refer to `../final_validation/MANUSCRIPT_CLAIMS_REGISTER.csv` (N01–N10). Source: `outputs/results/benchmark/bugsigdb_comparison_2026-11-03/` (pinned by its `MANIFEST.sha256`).*

**Status:** a dated supplementary analysis added after the validation freeze of 2026-11-02. It compares the frozen releases as published (CDM 3.0.3, which contains catalogue 3.1.1) and does not modify them or the frozen validation results.

**What it is:** a comparison with an independent, human-curated reference. BugSigDB is curated by people, but it is not our annotation and not an expert review of the CDM. The numbers below measure **concordance with human curation**, not accuracy.

## Claim for the manuscript

> For the 47 corpus papers also curated in BugSigDB, an independent human-curated database of microbial signatures, the catalogue reproduced the curated study metadata closely. Agreement was 98% for 16S region, 94% for country and 93% for condition. The catalogue covered 28% of the curated taxa, against 9% expected by chance. Coverage was complete for signatures BugSigDB took from the paper text, and lowest for signatures taken from figures and supplementary tables, which the extraction does not read. Where both sources reported a taxon, the direction of change agreed in 77% of cases, against 52% expected from the base rates. All taxon identifiers in our findings are valid in the current NCBI Taxonomy. By contrast, 71 of the 8,479 identifiers in BugSigDB are no longer valid.

## Method

**Reference:** BugSigDB full export of 2026-11-03 (CC BY 4.0).
- **Papers:** matched on PMID, or on DOI when the PMID did not match.
- **Overlap:** 47 papers and 270 signatures [N01].

**Ours:** the frozen CDM 3.0.3, opened read-only, with its sha256 checked against the release manifest.
- **Taxa:** the catalogue 3.1.1 findings.
- **Study metadata:** the study, cohort, sample and assay tables.

**Pre-registration**
- **What was fixed in advance:** the scoring rules, thresholds, endpoints, chance model and uncertainty methods. They are in `src/scripts/bugsigdb_comparison/scoring_schema.json`.
- **How it is enforced:** its sha256 was written to `PREREGISTRATION.sha256` before the run, and the run refuses to start if it has changed.
- **Answer template:** every compared item is one record of a fixed template (`answer_template.schema.json`). All 2,989 records were validated against it [N11].

**Taxon matching**
- **Basis:** NCBI Taxonomy identifiers, against our snapshot of 2026-11-01.
- **Verdicts:**
  - *exact:* the same ID;
  - *same genus:* both IDs lifted to their genus;
  - *mismatch:* otherwise.
- **Two measures:**
  - *coverage:* the share of BugSigDB taxa that we also report;
  - *support:* the share of our taxa that BugSigDB also lists. This is not precision: BugSigDB curates selected signatures, so a taxon it lacks is not an error.

**Study metadata matching**

| Field | Method |
|---|---|
| Sequencing type, platform, statistical test | Fixed rule classes |
| 16S variable region | V-region sets |
| Country | Country names and aliases |
| Group sizes | Integer match |
| Condition, body site, group names | Embedding similarity (SapBERT, a biomedical concept-name model; all-MiniLM-L6-v2 as sensitivity model) |

**Embedding threshold:** the 95th percentile of the same score computed against every *other* paper. The threshold therefore follows from a null distribution, not from the observed matches. A strict lexical match is reported alongside.

**Chance baseline:** every measure was recomputed with each paper's BugSigDB values scored against every other paper's extraction. Chance-corrected agreement is (observed − chance) / (1 − chance).

**Uncertainty:** 95% Wilson intervals, plus a paper-level cluster bootstrap (2,000 replicates, fixed seed) [N11].

**Adjudication of disagreements:** for rule-based fields, both values were looked up in the paper's own text, locally. No text left the machine.

## Results

**Taxa** (1,537 BugSigDB paper–taxon items; 667 of ours):

| Measure | Value | 95% CI (paper bootstrap) | Chance |
|---|---:|---:|---:|
| BugSigDB taxa we cover (exact or same genus) | 27.7% [N02] | 21.5–35.8 | 9.0% |
| BugSigDB taxa we cover, exact ID | 23.5% [N03] | | |
| Our taxa also in BugSigDB (support) | 57.3% [N04] | 48.0–67.1 | 18.1% |
| Same direction, where determinable (n = 261) | 77.0% [N05] | 66.4–86.5 | 52.0% (base rates) |

**Coverage by where BugSigDB took the signature from** [N06]:

| Signature source | Coverage |
|---|---:|
| Paper text | 100% (18 items) |
| Tables | 51.4% |
| Figures | 27.6% |
| Supplementary material | 22.1% |

Most curated taxa come from figures and supplementary tables, which the text-based catalogue does not read. Low overall coverage is therefore mainly a scope limit of text extraction.

**Study metadata** (concordance where both sources have a value):

| Field | Concordance | Chance | Note |
|---|---:|---:|---|
| 16S variable region | 97.7% [N07] | 34.8% | |
| Country | 94.0% [N07] | 21.2% | |
| Condition (SapBERT) | 92.7% [N08] | 5% | |
| Statistical test | 85.7% [N07] | 44.0% | |
| Group size | 56.2% [N07] | 6.3% | |
| Group name (SapBERT) | 54.2% [N08] | 5% | |
| Body site (lexical) | 84.2% [N08] | | The SapBERT measure is uninformative here (see note) |
| Sequencing type, platform | 100% | 93.9–96.2% | Too uniform in this corpus to discriminate |

- **Body site:** most papers sample feces, so the cross-paper null contains exact matches and the embedding threshold becomes 1.0. The lexical match is therefore the meaningful measure.
- **Strict measure (post-hoc):** this requires our set of values to equal BugSigDB's [N09]. Agreement falls to:
  - sequencing type 50.0%;
  - platform 89.4%;
  - statistical test 3.6%.

  The catalogue usually lists every test and assay a paper reports, while BugSigDB records the one used for each signature.
- **Disagreements:** of the 11 adjudicated disagreements in country and statistical test, the value we extracted appeared in the paper text in 10 [N11]. In 2 of them (one country, one statistical test), only our value appears in the text.

**Taxonomy currency** (measured against our NCBI Taxonomy snapshot of 2026-11-01) [N10]:

| | IDs not in current NCBI Taxonomy |
|---|---:|
| Our findings | 0 of 662 |
| BugSigDB, taxa on the 47 overlap papers | 8 of 668 |
| BugSigDB, whole database | 71 of 8,479 |

- **Retired IDs:** the missing BugSigDB IDs are older identifiers that have since been retired. One example is the earlier family ID labelled Oscillospiraceae.
- **Names:** BugSigDB's taxon *names* are as current as ours (1 of 8,479 differs).
- **The supported statement:** our identifiers are all current, while the reference database carries some retired identifiers. A general claim that our ontologies are newer is **not** supported.

## Limitations (must accompany the claim)

1. **Small overlap.** 47 papers (10% of the corpus) were curated by BugSigDB, and selected for curation by BugSigDB, not at random.
2. **Not exhaustive.** BugSigDB records selected signatures per paper, so neither coverage nor support is recall or precision.
3. **Group orientation.** Direction agreement assumes that BugSigDB's group 1 corresponds to the exposed or case group in our finding. This is usual but not guaranteed.
4. **Embedding scores depend on the threshold rule.** For fields with little variation across papers, such as body site, the cross-paper null is uninformative. Lexical matches are reported alongside.
5. **Lenient "any of our values matches" rule.** The rule-based fields use it, which favours the catalogue. The post-hoc strict measure shows the other bound.
6. **Taxon findings from one source only.** Only catalogue findings carry linked taxa, so the secondary analysis on all CDM findings gives the same result.
7. **Implementation fixes.** Three fixes were made after failed runs, before any complete result: `NA` lineages are skipped, integer fields are not adjudicated, and the threshold is compared unrounded. Three post-hoc measures were added and labelled as such. Scoring rules and thresholds were not changed. See `REPORT.md`, "Deviations".

## Placement in the manuscript

- **Results:** one paragraph and the taxa table, as the external, human-curated comparison.
- **Discussion:** cite it in the paragraph on evaluation without human annotation. Use coverage by signature source to explain the extraction's scope.
- **Positioning:** BugSigDB curates signatures by hand. The catalogue extracts study metadata and text findings from the same papers automatically, and reproduces BugSigDB's metadata closely.
