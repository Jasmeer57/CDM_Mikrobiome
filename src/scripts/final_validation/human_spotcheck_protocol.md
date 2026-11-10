# Manual check of 100 triples: protocol (fixed 2026-11-09, before annotation)

**Status:** an exception to the 2026-11-02 development freeze ("no human annotation"). It needs the project lead's
approval, recorded in `paper/publication/final_validation/CHANGE_RECORD.md`. Once done, every "no human annotation"
statement in the manuscript must be updated.

## Question
How often do two people, reading only the anchor sentence, judge a triple to be supported by it? How well does the
DeepSeek-V4.1-Flash screen (W03: 56.0 / 22.6 / 18.2 / 3.3%) agree with them?

## Population and sample
- Population: the 16,032 canonical triples that DeepSeek-V4.1-Flash judged on 2026-11-07 against a sentence from a
  CC BY or CC0 paper (register W02). Only openly licensed text is shown to annotators.
- Sample: simple random sample, n = 100, `random.Random(20261109)`, drawn once by
  `src/scripts/final_validation/human_spotcheck_sample.py`; presentation order shuffled.
- With n = 100 a proportion near 50% has a 95% Wilson interval of about ±10 points. This is a spot check, not a
  precise estimate.

## Procedure
1. Two annotators (A and B) with microbiome knowledge, each with their own copy of the sheet
   (`ANNOTATION_SHEET_A.xlsx`, `ANNOTATION_SHEET_B.xlsx`).
2. Blinding: the sheets contain no model output. `KEY_deepseek_verdicts.csv` is not opened until both sheets are
   complete. Annotators do not discuss items before both are finished.
3. Each item is judged from the sentence only, using the definitions in the sheet's `guide` tab (the same definitions
   the model judge received).
4. After both sheets are complete, A and B resolve disagreements together and record the agreed SUPPORT label in a
   column `AGREED` added to sheet A.

## Analysis (fixed in advance; `src/scripts/final_validation/human_spotcheck_score.py`)
- Per annotator and for the agreed labels: share SUPPORTED / PARTIAL / NOT_SUPPORTED / CONFLICTS, with 95% Wilson
  intervals; also SUPPORTED or PARTIAL.
- Agreement between A and B on SUPPORT: observed agreement and Cohen's kappa (4 labels, and 2 labels:
  SUPPORTED vs not).
- Agreement of DeepSeek with the agreed labels: confusion matrix, observed agreement, Cohen's kappa.
- Reported as a small two-person spot check of one LLM screen. It is not an accuracy estimate for the CDM, the
  extraction, or other layers.

## Files and integrity
`PREREGISTRATION.sha256` holds the SHA-256 of this protocol, the guide, `sample.csv`, both blank sheets and the key,
written when the sample was drawn and before any annotation.
