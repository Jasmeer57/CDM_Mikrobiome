# Catalogue evidence assessment (Workstream B)

*Data catalogue 3.1.1 as loaded in CDM 3.0.3. Generated 2026-11-02 from `evidence_judge/` by `src/scripts/final_validation/evidence_judge.py` and `judge_analysis.py`.*

**No human annotation was performed.** Nothing in this report is an accuracy estimate. The deterministic checks measure whether a value's text occurs in its evidence. The model-based results are **model judgements**: they show where two language models consider a value unsupported by its passage, not whether the value is true.

## 1. What was assessed

| Item | Count |
|---|---:|
| Catalogue records (6 tables) | 52,400 |
| Records with at least one assessable value | 52,397 (3 assay records have no populated field) |
| Populated text values (excluding links and flags) | 447,380 checked deterministically, about 352,000 sent to each judge |
| Values filled by the gap pipeline (G1/G2/G5) | 14,845 |

Each judge saw the record's evidence passage (the located quote plus 300 characters either side, or the quote alone if it was never located), field names with their extraction rules, and the values. Judges did not see earlier verdicts or each other's output. Each value was labelled PASS, FAIL_NOT_SUPPORTED, FAIL_WRONG_FIELD, FAIL_CONTRADICTED or UNCERTAIN.

**Judges and their independence:**

| Judge | Role in building the catalogue | Independence |
|---|---|---|
| Mistral-7B-Instruct-v0.3 (AWQ) | none | independent of every catalogue stage |
| Llama-3.1-8B-Instruct (AWQ) | second model in the G3 verify-and-repair stage (with Gemma), which removed 2,586 records | **not independent**: it is re-judging records it helped retain |

Extraction itself was done by Qwen3.5-4B, and G3 used Gemma. Neither was used as a judge.

## 2. Deterministic value-in-evidence checks (no model)

| Check | Values | Found in evidence |
|---|---:|---:|
| Text value occurs in its evidence (after normalising case and punctuation) | 392,587 | 70.5% |
| Stated count occurs in its evidence | 12,114 | 75.4% |
| Coded values (vocabulary terms such as `NOT_STATED`, `INCREASE`) | 42,679 | not assessable by string match |

"Not found" does not mean wrong. Normalised values ("16S rRNA V4" from "the V4 region of the 16S gene"), paraphrased findings and unit conversions all fail a string match. The check is a conservative floor on literal support.

By table, text values found in evidence: cohort 74.6%, sample 76.2%, assay 64.5%, dataset 66.5%, data asset 79.2%, finding (claim) 70.0%. Counts: cohort 79.3%, sample 73.7%. Data-asset file sizes are almost never stated in the text (4 of 222).

## 3. Model-based assessment

### 3.1 Compliance with the rubric

A label is valid only if it is one of the five rubric labels. Copied field values ("NO", "INCREASE", "gut"), free text ("FAIL: cited prior work") and malformed labels count as INVALID and are excluded from the percentages below, never mapped to a class.

| | Llama | Mistral |
|---|---:|---:|
| Records judged | 52,397 | 52,397 |
| Records with an unparseable response | 120 | 6 |
| Responses truncated | 13 | 5 |
| Text values with a valid label | **99.2%** | **55.4%** |

Mistral often returned the field's value in place of a verdict, especially for findings (38.2% valid) and cohorts (64.7%). Its percentages therefore rest on fewer values and may not represent the fields it failed to label.

### 3.2 Text values, by table (share of validly labelled values)

| table | values | deterministic: found in evidence % | Llama valid % | Llama PASS / FAIL / UNCERTAIN % | Mistral valid % | Mistral PASS / FAIL / UNCERTAIN % |
|---|---:|---:|---:|---|---:|---|
| cohort | 56,000 | 74.6 | 97.6 | 91.5 / 4.4 / 4.1 | 64.7 | 81.7 / 9.2 / 9.1 |
| sample | 30,653 | 76.2 | 100.0 | 89.3 / 6.3 / 4.4 | 93.6 | 82.2 / 8.2 / 9.6 |
| assay | 27,019 | 64.5 | 99.7 | 80.0 / 4.4 / 15.7 | 94.6 | 78.3 / 10.0 / 11.8 |
| dataset | 20,218 | 66.5 | 99.9 | 95.6 / 1.9 / 2.5 | 81.0 | 88.6 / 4.7 / 6.7 |
| data_asset | 9,064 | 79.2 | 99.7 | 90.9 / 2.0 / 7.1 | 91.0 | 91.7 / 3.2 / 5.1 |
| claim (finding) | 208,870 | 70.0 | 99.3 | 88.0 / 1.9 / 10.2 | 38.2 | 92.4 / 4.5 / 3.2 |
| **all** | 351,824 | 70.5 | 99.2 | **88.5 / 2.9 / 8.6** | 55.4 | **86.7 / 6.6 / 6.7** |

FAIL types (Llama / Mistral): not supported 6,127 / 6,550; wrong field 3,561 / 6,006; contradicted 285 / 283.

### 3.3 Within-paper links (cohort, assay, dataset)

Llama: 88.8% PASS, 7.2% FAIL, 4.0% UNCERTAIN of 97,266 valid labels. Mistral: 60.1% / 6.6% / 33.3% of 51,895. A link is PASS only if every linked ID passes. The judges see the linked record's label but not its evidence, so many links cannot be confirmed from the passage. Mistral's high UNCERTAIN rate is the more defensible reading.

### 3.4 Flags and classifications

`is_primary_finding`, `cites_other_work`, `finding_domain` and `intervention_category` are pipeline judgements, not statements in the text. The rubric does not fit them, so they are excluded from all figures above (Llama labelled 93,501 of them, mostly PASS, with 16.7% FAIL. Mistral produced a valid label for only 14%).

### 3.5 Record level

Record-level verdicts are uninformative: Llama passes 98.3% of the 52,397 records, and Mistral never returned a valid FAIL label at record level (447 records got free-text "FAIL: …", mostly "cited prior work"). Field-level results are the unit of analysis.

## 4. Where the signals converge

**Deterministic and model checks agree.** Values whose text is not in the evidence are judged FAIL several times as often:

| Deterministic result | Llama FAIL % (n) | Mistral FAIL % (n) |
|---|---:|---:|
| found in evidence | 1.4 (246,944) | 4.8 (149,024) |
| not found | 6.8 (61,691) | 12.5 (38,323) |
| coded value (not string-checkable) | 5.7 (40,312) | 12.3 (7,770) |

**Gap-filled values are weaker.** Values added by the gap pipeline fail 3–3.5 times as often as original extractions:

| Source | Llama FAIL % | Mistral FAIL % |
|---|---:|---:|
| original extraction | 2.6 | 5.6 |
| gap-filled (G1/G2/G5) | 9.0 | 19.1 |

**Anchor status makes no difference.** Values whose quote was never located in the paper (UNANCHORED, 13,460 values) pass as often as EXACT ones (89.2% vs 86.9% under Llama). For those records the judge sees only the quote, which naturally agrees with the value. The judges therefore test **value–quote consistency, not whether the quote is genuine**. Only offset anchoring tests the latter (88.2% of quotes verbatim; see `EXHAUSTIVE_INTEGRITY_REPORT.md`).

## 5. Agreement between the two judges

Across text values both judges labelled validly (194,479 pairs):

| | value |
|---|---:|
| Observed agreement | 85.0% |
| Cohen's κ between the two **models** | 0.28 |
| Both PASS | 159,680 |
| Both FAIL | 2,023 |

κ is low because nearly everything passes: when one judge fails a value, the other usually does not (Llama FAIL → Mistral FAIL in 34% of valid pairs; Mistral FAIL → Llama FAIL in 16%). This κ measures agreement between two language models. It is not inter-annotator agreement and says nothing about correctness.

**Both-fail worklist:** `evidence_judge/BOTH_JUDGES_FAIL.csv` (2,023 values) lists every value both models failed, with the deterministic result and gap-fill flag:
- 58% are not found in their evidence by the deterministic check;
- 28% are gap-filled, although gap-filled values are only about 4% of the values judged;
- the fields most often listed are `dna_extraction_method` (214), `storage_condition` (203), `longitudinal` (109), `preservation_method` (105), `sample_count` (95), `collection_timepoint` (91).

This is the most useful output of the assessment: a ranked list for curation in the next catalogue release. The frozen 3.1.1 release is unchanged.

## 6. Limitations

- Both judges are small (7–8B), quantised models. They are lenient and share the general failure modes of language models.
- Llama is not independent of the G3 curation stage.
- Mistral's 55% rubric compliance leaves the findings table largely assessed by Llama alone.
- A judge sees one passage. A value correctly supported elsewhere in the paper can be failed, and an unsupported value can be passed if the passage is ambiguous.
- Earlier model-based figures from development (92.2% Gemma census, 59%) are not reused here and are not accuracy.

## 7. Decision

**Interpretation for the manuscript:** computational assessment identified substantial literal correspondence between catalogue values and their associated evidence, alongside a subset of potentially unsupported values. Model-based assessments by two judges, one of them not independent of curation, provided additional but limited evidence of support. These evaluations do not establish scientific accuracy. Do not write that independent judges confirmed the catalogue's reliability.

| Property | Status |
|---|---|
| Structural evidence linkage | PASS (`EXHAUSTIVE_INTEGRITY_REPORT.md`) |
| Literal value-in-evidence (deterministic) | CONDITIONAL: 70.5% of text values and 75.4% of counts found verbatim in their evidence |
| Computational evidence support (model judgements) | CONDITIONAL: 2.9% (Llama) and 6.6% (Mistral) of validly labelled values judged unsupported; gap-filled values markedly weaker |
| Cross-model agreement | CONDITIONAL: 85.0% observed agreement, κ 0.28, low because near-all-PASS |
| Scientific accuracy | **NOT EVALUATED** (no human annotation) |
