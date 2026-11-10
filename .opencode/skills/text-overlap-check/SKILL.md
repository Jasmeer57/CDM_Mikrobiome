---
name: text-overlap-check
description: Find sentences in a manuscript draft that share long word sequences with AI-assisted notes, the corpus papers, or other given texts, and say for each whether to quote and cite, cite, or have the authors rewrite it themselves. Use before submission or when asked about plagiarism, similarity, text reuse or iThenticate. Reports only. It never paraphrases text to lower similarity.
license: internal
compatibility: opencode
metadata:
  project: Microbiome-CDM
  journal: Briefings in Bioinformatics
---

# Text overlap check

This skill makes overlap **visible** so the authors can handle it honestly before the journal's similarity check
(iThenticate) does. It is not a paraphraser.

## Hard rules

- **Never paraphrase, reword, or "make original" any flagged sentence**, and never suggest synonym swaps or
  restructuring to lower a similarity score. Rewording a source to hide where it came from is plagiarism. If asked, say
  so and stop.
- Never try to make text read as human-written or to avoid AI-detection tools.
- Report and advise only. Do not edit the draft.

## Steps

1. Run from the repo root:

   ```bash
   # against the AI-assisted notes (manuscript_draft, submission_readiness, manuscript_bib, docs/reports)
   python .opencode/skills/text-overlap-check/overlap_check.py <DRAFT> --log-model "<your model id>"
   # also against the 453 corpus papers (~10 s)
   python .opencode/skills/text-overlap-check/overlap_check.py <DRAFT> --corpus --log-model "<your model id>"
   # other texts, labelled: e.g. a preprint or thesis chapter by the authors
   python .opencode/skills/text-overlap-check/overlap_check.py <DRAFT> --sources own_prior=paper/preprint/*.txt
   ```

   Options: `--n` sets the sequence length in words (default 8), `--min-share` sets the reporting threshold (default
   0.3), `--json` gives JSON, and `--no-default` skips the notes.

2. For each flagged sentence, give its line number, the source and the longest shared run. Then give the action
   matching the kind of source:

   | Source kind | What it means | Action for the authors |
   |---|---|---|
   | `ai_notes` | The sentence matches notes written with AI tools (Claude Code, OpenCode). BiB does not allow LLM-drafted manuscript text. | The authors write the sentence themselves from the facts, or declare the AI drafting. Keeping only the register IDs and numbers is fine. |
   | `corpus_papers` / published source | The wording comes from a published paper. | Put it in quotation marks and cite it, or the authors restate it in their own words **and** cite it. A standard method phrase can stay if cited. |
   | `own_prior` (authors' own preprint or thesis) | Text recycling. | Cite the earlier work. Tell the editor in the cover letter if the overlap is large (COPE text-recycling guidance). |
   | `other` | Unknown. | Ask the user what the source is before advising. |

3. Short shared runs made only of numbers, claim IDs or fixed names (e.g. "Comparative Toxicogenomics Database") are
   expected. Mention them in one line and don't treat them as problems.

4. End with counts per source kind and a reminder that the run is in
   `paper/publication/submission_readiness/AI_ASSIST_LOG.md` for the AI-use declaration.
