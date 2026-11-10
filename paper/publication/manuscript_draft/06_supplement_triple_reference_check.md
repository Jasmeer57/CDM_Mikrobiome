# Supplementary analysis: reference check of the triple layer

*Working notes, 2026-11-03. Claim IDs refer to `../final_validation/MANUSCRIPT_CLAIMS_REGISTER.csv` (X01–X06). Source: `outputs/results/benchmark/triple_reference_check_2026-11-03/` (pinned by its `MANIFEST.sha256`).*

**Status:** a dated supplementary analysis after the validation freeze. It does not change the frozen releases or the frozen validation results.

**What it measures:** support by a reference, not accuracy. A triple that is absent from BugSigDB or CTD is not counted as wrong.

## Method

**Triples checked:** all 25,788 CDM 3.0.3 triples, both as frozen and as kept or dropped by the DeepSeek cleaning (supplement 04).

**Pre-registration:** the rules are fixed in `src/scripts/triple_reference_check/scoring_schema.json`. Its hash was written before the run, and every item is a validated answer-template record. The run was SLURM job `28691847`.

**Identifier resolution:** each entity was resolved first by its CDM mapping. Otherwise, it was resolved by an exact name match in the reference vocabulary, and only when the match was unambiguous.

| Check | Triples included | What counts as support |
|---|---|---|
| BugSigDB | Triples with a microbial taxon, on the 47 papers curated in both | The taxon, at the same ID or genus, appears in BugSigDB's signatures for the same paper |
| CTD | Chemical–disease and gene–disease triples | The pair is listed in CTD |

**Chance:** the same entities scored against other papers, or against all cross pairs.

## Results

**Microbial taxa against BugSigDB**
- **Coverage:** 518 (triple, paper) items on 45 papers [X01].
- **Support:** in 50.4% of items, the triple's taxon is listed by BugSigDB for the same paper, against 16.1% by chance [X02].
- **Cleaning:** triples the DeepSeek cleaning kept had more support than those it dropped: 54.3% vs 44.3%, a difference of +10.0 points (95% CI 1.1–18.6) [X03]. The cleaning is therefore modestly aligned with human curation.
- **Direction:** agreement could be assessed for only 12 items, and 11 agreed [X04]. This is too few to support a claim.

**CTD**
- **Chemical–disease triples:** only 49 could be resolved on both sides. Their support (22.4%) is no higher than chance (24.2%) [X05].
- **Gene–disease triples:** only 7 could be resolved, and none was curated in CTD [X06].
- **Interpretation:** the triple layer rarely links chemicals or genes directly to diseases. A CTD comparison is therefore uninformative for this corpus.

## Limitations

1. **Paper-level matching.** The BugSigDB check tests whether the triple's taxon is curated for the same paper. It does not test whether the relation itself is correct.
2. **Name matching.** 401 of the 518 taxon items were resolved by an exact name match, not by a CDM mapping.
3. **Small CTD sample.** The CTD samples are too small to estimate support.
4. **Partial picture.** Together with supplement 04, this gives a reference-backed signal for microbe-centred triples only. Other triple types remain checked by model judgement alone.
