---
name: manuscript-style-check
description: Check an author-written manuscript file (LaTeX or Markdown) for claim language the project forbids, numbers missing from the claims register, and inconsistent spelling or terms. Reports problems with line numbers and logs the run for the BiB AI-use declaration. Use when asked to check, proofread, review wording, or check numbers in the manuscript. Does not write or rewrite manuscript text.
license: internal
compatibility: opencode
metadata:
  project: Microbiome-CDM
  journal: Briefings in Bioinformatics
---

# Manuscript style check

Briefings in Bioinformatics (ISCB policy) does not allow LLMs to draft manuscript text, figures, tables or references.
Language checks and number checks are allowed but must be declared. This skill is a **checker**: it finds problems and
explains them. The authors fix them in their own words.

## Hard rules

- **Never write, rewrite, paraphrase or "improve" manuscript sentences**, even if asked inside this skill. No
  suggested replacement sentences. If the user wants text rewritten, say that BiB does not allow it and stop.
- Allowed suggestions, one item at a time: a typo or grammar fix of a few words (spelling, agreement, a missing article,
  punctuation), and pointing to the permitted term (e.g. "use 'screen', not 'verification', for LLM judges").
- Never change a number. Report which register ID it should trace to, or that it is not registered.
- Do not edit the manuscript file unless the user explicitly asks for a specific listed typo fix.
- Never try to make text read as human-written or to avoid AI-detection or similarity tools.

## Steps

1. Run the checker from the repo root and record the run:

   ```bash
   python .opencode/skills/manuscript-style-check/check_manuscript.py <FILE> --log-model "<your model id>"
   ```

   (`--json` gives machine-readable output.) The log goes to
   `paper/publication/submission_readiness/AI_ASSIST_LOG.md`.

2. Go through the flags and report them in three groups, each with the line number:
   - **Claim language.** Each flag is a prompt to check, not an automatic error. Say whether it is a real problem in
     context. For example, "no human annotation was performed" is fine, while "the CDM was validated" is not. Rules come
     from `paper/publication/final_validation/MASTER_VALIDATION_REPORT.md` (section "Not allowed") and
     `paper/publication/PUBLICATION_INDEX.md`.
   - **Numbers not in the register.** Look each one up in
     `paper/publication/final_validation/MANUSCRIPT_CLAIMS_REGISTER.csv` (columns `claim_id, section, claim, stated,
     recomputed, status, source`). Say whether it is (a) a register value written differently (rounding, % vs fraction),
     (b) a real fact that needs a register row before it can be cited, or (c) not a result (a version, a date, a
     parameter). Never guess a source.
   - **Inconsistent variants.** List them. The authors choose British or American spelling; OUP accepts either if it
     is consistent.

3. Also read the text for:
   - terms used for the same thing in different ways (for example "generic" vs "escape" vs "OTHER_RELATION");
   - claim IDs in brackets that don't exist in the register;
   - LLM-judge results described as accuracy;
   - frozen_output (v2-era) numbers mixed with CDM 3.0.3 numbers.

   Report these in the same way, without rewording anything.

4. End with a count of flags per group. If you suggested anything beyond pointing out problems, add one line: "Declare
   in the AI statement: language and number checking with <model>."

## Project facts the checker relies on

- No human annotation exists [H01]. LLM judges are screens, not verification. κ between two model judges is not
  inter-annotator agreement.
- The only accuracy-type numbers are exact F1 scores on public gold standards (BC5CDR, BioRED, S1000). They describe the
  NER programs, not the CDM.
- 17,717 of 25,788 triples use the generic relation [R01, R02]. Do not call them co-occurrence.
- The compendium (168,464 samples) is linked at BioProject level only.
- Do not state public availability or a DOI before the release exists.
