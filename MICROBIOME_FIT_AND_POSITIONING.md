# Fit and positioning assessment: *Microbiome* (BMC, ISSN 2049-2618)

**Subject:** `oup-authoring-template/manuscript.tex`
*"Microbiome-CDM: An LLM-driven common data model and knowledge extraction pipeline for human microbiome literature"*

**Date:** 2026-11-10
**Manuscript status:** converted to Springer Nature `sn-jnl` v3.1 (`sn-vancouver-num`); clean from-scratch `latexmk -pdf` build, 17 pages, 0 undefined citations/references, 0 LaTeX errors. Committed as `b804f97` on branch `submission-prep-2026-11-10` (not pushed).
**Scope of this document:** (A) whether the manuscript fits this journal and every way it currently falls short, and (B) how it compares to the published competition and what to change so it competes. Both parts are needed together — most of the compliance gaps are also positioning gaps.

**Verdict in one line:** the manuscript is *mechanically submittable* apart from 4 author-input blocks and 2 unfilled DOIs, but it is **not yet competitive** at this journal, because it is framed as NLP engineering performed over a microbiome corpus rather than as a microbiome resource — and, separately, because **eight near-identical systems published in the last 18 months are uncited**, so the paper is not visibly in conversation with its own field.

**Two independent rejection risks, not one:**

1. *Compliance/positioning against the journal* — wrong section architecture, future-tense data availability, no microbiome result, no standards engagement (Part A).
2. *Positioning against the literature* — the competitive claim ("none of these delivers a provenance-traceable common data model") is asserted, contestable, and made without citing most of the systems it dismisses (Part B).

Fixing only the first will not get the paper through review. Both are addressable with existing artefacts.

## The ten gaps that decide the outcome

Ranked by how much each one alone can sink the submission.

| # | Gap | Where |
|---|---|---|
| 1 | No `Methods`, `Discussion` or `Conclusions` section; Limitations (1,089 words) is longer than Results (900) | A3.1, A3.2 |
| 2 | Data and code availability is future tense with two empty DOI slots — fails the "available at submission" policy outright | A4.1, A4.2 |
| 3 | Eight direct competitor systems uncited; the gap over them is asserted, not demonstrated | B2.1, B3.2 |
| 4 | No microbiome result and no microbiome figure — the paper never shows what the CDM buys a microbiome scientist | A5.2, B2.4 |
| 5 | Calls itself a "protocol" 17 times; no Protocol article type exists at this journal | A5.1, B3.1 |
| 6 | Zero engagement with FAIR, MIxS/MIMARKS, STORMS/STREAMS — the standards the paper implicitly implements | A4.4, B2.2 |
| 7 | Validation is one reviewer, n=500, no confidence intervals, second reviewer unfinished | A6.1, B2.6 |
| 8 | Relations: 17,717 of 25,788 triples carry only a generic `OTHER_RELATION`, yet triples lead the abstract | A6.4, B3.4 |
| 9 | Abstract's headline F1 (90.1 / 80.6) belongs to PubTator3 and HunFlair2, not to this pipeline | A6.5, B3.3 |
| 10 | SSSOM, KGX/Biolink and RDF exports already exist in `src/cdm_pipeline/export/` and are never mentioned | B1.3 |

Items 1–2 are pure logistics. Items 3–4 and 6 need writing. Items 5 and 9–10 cost almost nothing. Items 7–8 need either new analysis or an honest reframing.

---

# Part 0 — Unresolved question that blocks further reformatting

The venue is **contested inside the repository**:

- `manuscript.tex` comments (line 90) say: *"BMC Microbiology requires a structured abstract with exactly these three headings…"*
- `manuscript.tex` comments (lines 1336, 1405) reference BMC/Springer Nature declaration ordering.
- The current request asks about **Microbiome (2049-2618)**.

These are **different journals with different article types, different declarations, and different framing expectations**. Nothing further should be reformatted until one is chosen.

| | *Microbiome* (2049-2618) | BMC Microbiology (1471-2180) |
|---|---|---|
| Article types | Research, **Methodology**, **Software**, Review, Brief report, Comment, Correspondence, Meeting Report | Research article, Methodology article, Software, Database, Short report, Review, … |
| KG/ontology-titled papers | **13** | **60** |
| Software/database/tool/pipeline-titled | **41** | **77** |
| Text-mining/NER/NLP-titled | **2** | **2** |
| LLM in abstract | **2** | **1** |
| 2026 sample (200 / 300 articles): curation | 11 | 15 |
| 2026 sample: database | 10 | — |
| 2026 sample: pipeline | 4 | — |
| 2026 sample: tool / platform | — | 17 / 12 |
| 2026 sample: text-mining/LLM methodology | 3 | **≈ 0** |

**Read of the evidence:** *Microbiome* demonstrably publishes curation/database/pipeline work and has an explicit **Methodology** article type. BMC Microbiology publishes more ontology/KG work but essentially **no** text-mining or LLM methodology. So *Microbiome* is the better *thematic* home for this paper and the worse *competitive* one (higher bar, mechanistic bias). See **A10** for the full venue verdict.

---

# PART A — FIT AGAINST THE JOURNAL

## A1. Hard facts about *Microbiome* (verified from journal guidelines, 2026-11-10)

| Property | Value |
|---|---|
| Publisher | BMC (Springer Nature) |
| APC | **€4,290 / $5,190 / £3,590** |
| Licence | CC BY, or CC BY-NC-ND |
| Waivers | Yes (lowest-income countries; discretionary case-by-case, requested **at submission only**) |
| Other charges | None |
| Abstract | Structured, **≤350 words**, **Background / Results / Conclusions**, **no citations**, minimise abbreviations |
| Keywords | **3–10** |
| Mandatory Declarations | Ethics approval and consent to participate; Consent for publication; Availability of data and materials; Competing interests; Funding; Acknowledgements; Authors' information; Endnotes; References |
| Main text formatting | **double line spacing**, **line and page numbering**, SI units, **no page breaks** |
| Editable source | **required at submission**; DOC/DOCX/RTF/**TeX** accepted |
| Reference style | Vancouver (numeric) — `sn-vancouver-num` provides this |
| Figures/tables | per general formatting guidelines; Additional files supported |

**Article types:** Research, Comment, Correspondence, **Methodology**, Review, Brief report (short report), **Software**, Meeting Report.

**There is no "Protocol" article type.** This matters — see A5.1.

**Criteria the manuscript will be judged against:**

> **Methodology:** "should present a new experimental or computational method, test or procedure… The article **must describe a demonstrable advance** on what is currently available. The method needs to have been **well tested**."

> **Software:** "a tool likely to be of **broad utility** that represents a **significant advance** over previously published software (usually demonstrated by **direct comparison with available related software**)."

> **Editorial `s40168-025-02091-0` (senior editors):** "we are seeking studies that provide either new mechanistic insights… or **substantial conceptual or technical advances**… Manuscripts need to meet high standards of language accuracy, quality of microbiome analyses, and data and protocol availability."

> **Same editorial, on associations:** "Associative studies… often lead to overstatement… should therefore be self-critically and conservatively interpreted."

The editorial is *directly* relevant: the manuscript is associative by construction (text co-occurrence → triples) and must be positioned so it is not read as making association claims.

## A2. Journal rule the manuscript violates verbatim: the "16S" terminology rule

*Microbiome*'s Research guidelines state, word for word:

> "A common example is the use of the term **16S**, 16S rDNA, 16S rDNA gene, 16S gene which are not appropriate. These should be replaced with **16S rRNA gene**. Please make sure that you comply with all these criteria."

Bare "16S" appears **three times** in the body:

| Line | Text | Fix |
|---|---|---|
| 816 | "…72.1% of **16S identifiers** natively present in the text" | 16S rRNA gene identifiers |
| 1010 | "…its accession numbers, sequencing platforms and **16S regions** present" | 16S rRNA gene regions |
| 1071 | "Study metadata agrees closely for **16S** region (97.7%)" | 16S rRNA gene region |

Cheap to fix, but it is an **explicitly stated criterion**, and editors do check it.

## A3. Mechanical and structural non-compliance (blocking)

### A3.1 Wrong section architecture — the most serious structural problem

Required: **Background → Methods → Results → Discussion → Conclusions**.

Actual structure:

| Actual heading | Line | Should be |
|---|---|---|
| Background | 160 | Background ✓ |
| Protocol overview | 329 | §Methods (lead-in) |
| Stage 1: Corpus and sectioning | 404 | §Methods subsection |
| Stage 2: Entity extraction with multiple programs | 458 | §Methods subsection |
| Stage 3: Normalisation and vocabulary mapping | 536 | §Methods subsection |
| Stage 4: Data catalogue and common data model | 652 | §Methods subsection |
| Stage 5: Computational evaluation and human spot check | 747 | §Methods subsection |
| Results | 876 | Results ✓ |
| Recommendations | 1112 | Discussion subsection (or drop) |
| Limitations | 1197 | **Discussion subsection** |
| Abbreviations | 1310 | ✓ (unnumbered) |
| Declarations | 1336 | ✓ (unnumbered) |

Concretely missing:

- **No `\section{Methods}`.** The five "Stage" sections *are* the methods, but they are unlabelled, sit at top level, and use internal engineering vocabulary. Reviewers, abstracting services and indexers all look for "Methods".
- **No `\section{Discussion}`.** Zero occurrences of a Discussion heading.
- **No `\section{Conclusions}`.** The only "Conclusions" is the abstract's third paragraph (line 130).
- The journal states the Discussion "should discuss the implications… and **highlight limitations**". Limitations is therefore a **subsection of Discussion**, not a standalone section — and certainly not the longest section of the paper (A3.2).

### A3.2 The limitations section outweighs the results

Body word counts (comments stripped, tables/figures removed):

| Section | Words |
|---|---|
| Background | 506 |
| Protocol overview | 192 |
| Stage 1: Corpus and sectioning | 129 |
| Stage 2: Entity extraction | 192 |
| Stage 3: Normalisation and mapping | 343 |
| Stage 4: Catalogue and CDM | 161 |
| Stage 5: Evaluation and human spot check | 294 |
| **Results** | **900** |
| Recommendations | 234 |
| **Limitations** | **1,089** |

- **Total body ≈ 4,507 words.**
- **Methods (all five stages + overview) = 1,311 words.** For a five-stage pipeline with four mention sources, 2.5 M mentions, a catalogue and a CDM, 1,311 words of method is **thin**. A reader cannot reproduce the pipeline from it.
- **Limitations (1,089) > Results (900).** The paper's most developed argument is self-criticism. To an editor that reads as a manuscript that already knows it has not cleared the bar.

### A3.3 Formatting requirements not met

- **No line numbers.** `\documentclass[pdflatex,sn-vancouver-num]{sn-jnl}` (line 23); the `lineno`/`referee` variant exists only as a comment (line 25).
- **No double spacing.** Both are explicit requirements for the main text.
- Page breaks: **0** `\newpage`/`\clearpage` — compliant ✓.

**Fix:** for the submission copy use `\documentclass[referee,lineno,pdflatex,sn-vancouver-num]{sn-jnl}`. Keep the clean build for internal reading.

### A3.4 Missing back-matter sections

- **No "Authors' information"** heading (listed in the required Declarations set).
- **No "Endnotes"** — fine if unused, but it is in the required list.
- **No "Additional files" list.** For a data-deliverable paper everything is either in-text or external. Reviewers will expect at least: per-stage counts table, licence matrix, evaluation artefacts, and the full term/mapping tables as additional files.

### A3.5 Four visible author-input markers in the PDF

These are **deliberately visible** (correct practice — never invented, never hidden in comments). They still block submission:

| Line | Section | Marker |
|---|---|---|
| 1433 | Competing interests | `[AUTHOR INPUT REQUIRED — per-author competing-interests statement missing…]` |
| 1448 | Funding | `[AUTHOR INPUT REQUIRED — funding statement missing…]` |
| 1463 | Authors' contributions | `[AUTHOR INPUT REQUIRED — CRediT statement missing…]` |
| 1481 | Acknowledgements | `[AUTHOR INPUT REQUIRED — acknowledgements missing…]` |

### A3.6 Two unfilled DOI/repository slots

| Line | Slot |
|---|---|
| ~1399 | "…and the benchmark and evaluation artefacts, **DOI [to be added when the deposit is published]**." |
| ~1401 | "The pipeline code will be released in a public repository with an archived version, **[repository and DOI to be added by the authors]**." |

### A3.7 Source-file hygiene (this file would ship to the publisher)

The journal requires **editable source files**. The current `.tex`:

- **1,626 lines total; 931 are comment lines (57%).**
- **29 mentions of "Claude"**, including:
  - `%% REVIEW 2026-11-09 (Claude Code fact check; prose not changed)`
  - `%% FRAMING 2026-11-09 (Claude Code; prose not changed)`
  - `%% DRAFT CAPTION, NOT SUBMISSION TEXT (plan §0)`
  - `%% >> AUTHOR REWRITE REQUIRED: rewrite the legend in your own words` (lines 347, 729, 952)
- Internal review notes that **admit unsettled issues**: e.g. line 756 — *"statement must change (H01). The 100-triple check is prepared, not done."*

Shipping this is a professionalism problem and leaks unresolved concerns to reviewers. **Produce a comment-stripped submission build** and keep the annotated working copy separately.

### A3.8 Internal file name leaked into a published caption

*(Same defect as **B3.7**.)*

Table 1's caption (line 927) names an internal audit artefact:

> "…the last column names the row in the claims register (`MANUSCRIPT_CLAIMS_REGISTER.csv`)…"

Reviewers cannot access that file. Either drop the column, drop the filename, or ship the register as an additional file.

### A3.9 Figure counts and float pressure

- **3 figures** (lines 334, 714, 938), **1 table** (`table*`, line 924). Counts are within limits.
- **17 pages** for a 4,507-word body ⇒ whitespace/float pressure (Underfull vbox warnings in `manuscript.log`). Consider merging Fig. 1 (`fig_overview.pdf`) and Fig. 2 (`fig3_cdm_architecture.pdf`), which are conceptually adjacent and both small (405×313 pt, 405×258 pt).
- `Fig/fig_overview_illustrated.pdf` exists but is **unused** — decide or delete before packaging.
- All figures are **vector PDFs with 0 embedded raster images** — good, no DPI problem.

### A3.10 Minor build facts (for completeness)

- 17 pages; **33 `\bibitem` entries in the compiled `.bbl`** (34 distinct cite keys; `key` appears as a stray match only inside a comment at line 1584, which is *not* a real citation).
- 0 undefined citations, 0 undefined references, 0 LaTeX errors.
- 3 warnings in the log, all "Underfull \vbox" (cosmetic).

## A4. Data and code availability — the biggest single risk

*Microbiome*'s policy is **strict** and repeated on **every** article-type page:

> "We **require that all datasets on which the conclusions of the paper rely are available to the reviewers at the time of submission** and publicly available at the time of publication."

Current text (lines 1392–1401):

> "The outputs of this protocol **will be** deposited on Zenodo **before publication**… DOI [to be added]… The pipeline code **will be** released… [repository and DOI to be added by the authors]."

### A4.1 Nothing is uploaded — future tense fails the policy

"Will be deposited before publication" is **not** "available at submission". This alone can trigger desk rejection or a "revise before review" bounce. The project rule already in place is correct: *no public-availability statement until the deposit exists.*

### A4.2 No DOI, no URL

Even if uploaded, there is no identifier for a reviewer to follow. **Blocking.**

### A4.3 60% of the source corpus is withheld

*(Positioning consequences of this are in **B3.9**.)*

| Rights bucket | Papers |
|---|---|
| INCLUDE_TEXT | 274 |
| RESTRICTED_NC_LAYER | 15 |
| WITHHOLD_TEXT | 164 |

**179 of 453 papers** cannot be redistributed (135 with no licence + 44 non-commercial or no-derivatives). This is legally correct and honestly stated — but the consequence must be made explicit:

- **The corpus is not reproducible from the deposit.** No reviewer can rebuild the 2,505,684 mentions from scratch.
- The deposit must therefore ship the **paper list**, the **per-paper licence decision**, **source-file SHA-256 hashes**, and the **`PAPER_RIGHTS_MATRIX.csv`** — so the build is *verifiable-by-reconstruction* even where text is withheld.
- State plainly which downstream numbers depend on withheld text (everything derived from those 179 papers) and whether any headline figure is affected.

### A4.4 No engagement with the field's metadata standards

*(Competitive framing consequences are in **B2.2**.)*

Grep of non-comment body text returns **zero** hits for **FAIR**, **MIxS / MIMARKS**, **STORMS**, **STREAMS**.

This is a serious framing gap: the journal **endorses STORMS**, **expects FAIR**, and the paper is *about* metadata standardisation for microbiome data — yet never names the standards it is implicitly trying to satisfy. An editor reads that as a blind spot. Note also that `wilkinson2016fair` and `yilmaz2011mixs` are **in the bibliography and never cited** (A7).

### A4.5 Licence/copyright statement needs one refinement

Currently: "The underlying source texts are third-party publications and are redistributed only under their own licences… the text of the 179 papers whose licence does not permit redistribution… is withheld."

Good. But it should also state: (a) the **licence of your own deposit** (CC BY 4.0 proposed, pending sign-off), and (b) that **derived annotations** over withheld text (mention offsets, spans, evidence quotes) are also restricted or redacted — the current text implies only the raw text is withheld.

## A5. Scope, article type and novelty positioning

### A5.1 Article type: neither fish nor fowl

The title promises "an LLM-driven common data model **and knowledge extraction pipeline**" — a **Software** or **Methodology** paper. But the manuscript **calls itself a protocol** in 17 places, including the abstract ("We present a **protocol**…") and line 286 ("We built Microbiome-CDM as a **protocol** rather than a single model").

- **There is no Protocol article type at *Microbiome*.**
- As **Software**: criteria require "broad utility" and "direct comparison with available related software". You compare *individual NER models* on BC5CDR/BioRED, but **never compare the pipeline as a whole** to any competing literature-mining system (PubTator3-as-pipeline, SemRep, an existing microbiome KG).
- As **Methodology**: criteria require a "**demonstrable advance**". The Background (lines 228–300) dismisses related work in one paragraph and *asserts* "None of these delivers a provenance-traceable common data model over the cited literature of a compendium" — asserted, not demonstrated.

**This is the single most likely rejection reason.** The predictable editor response: *"What can I do with this that I cannot do with BugSigDB plus PubTator3?"* The manuscript does not answer that with evidence.

### A5.2 The microbiome content is nearly absent

The journal's readers are microbiome scientists. Evidence from the manuscript:

- **No figure shows microbiome data.** No taxonomic composition, no alpha/beta diversity, no differential abundance, no biological result of any kind. The three figures are: pipeline overview, CDM schema architecture, evaluation metrics.
- **No taxon is discussed.** The only organism names in the body are two incidental italics — *Lactobacillus* and *Lactococcus* (lines 624–625). Zero mentions of Bacteroidetes, Firmicutes, *Faecalibacterium*, *Akkermansia*, *Prevotella*, *Bifidobacterium*, *Escherichia*.
- **The biological payoff is never shown.** You built a CDM over 453 papers and a 168,464-sample compendium and never demonstrate one insight it enables.

For this journal, "technical advance" means *it enables something*. An infrastructure report that never delivers a microbiome result is the archetype of what the editorial calls work that does not provide "substantial conceptual or technical advances".

### A5.3 The "cited by a compendium" framing is correct but needs an inclusion rule

You correctly separate your corpus from Abdill et al.'s compendium (lines 226–232; "the literature **cited by** a 168,464-sample gut microbiome compendium"). That distinction is essential and well handled. But:

- Your corpus is a **secondary selection** (papers cited by one synthesis). Its completeness relative to the microbiome literature is **undefined**.
- State the **inclusion logic** explicitly: how many cited works existed, how many were retrievable, how many were excluded and why.

### A5.4 No novelty statement

"novel/novelty" appears **twice** in the whole file, neither time as a claim. There is no paragraph stating what is new relative to each named prior system. Methodology reviewers at this journal expect one.

## A6. Evaluation — what reviewers will attack

### A6.1 Human validation: one reviewer, no CI, second reviewer not done

- **One blinded reviewer**, 500 sampled accepted mappings → 61.8% exact, 6.2% wrong.
- **Second-reviewer 100-row overlap "prepared, not done"** (run-source comments at lines 754, 756, 1230) — tracked internally as open item **H01**.
- Limitations states outright: *"no part of this CDM was evaluated against a human-curated ground truth."*
- **No confidence intervals anywhere in the body.** No Wilson intervals, no bootstrap. For 61.8% / 6.2% on n=500, and for κ = 0.282, this is a methodological hole. Telling: `wilson1927` and `efron1993bootstrap` are **in the bibliography and never cited**.

A reviewer will treat "one reviewer, n=500, no CI" as insufficient to support a claimed quality standard.

### A6.2 "Structural checks pass 118 of 121" is a test suite, not validation

Reporting 118/121 next to benchmark F1 numbers invites conflation of **engineering CI** with **scientific validity**. Keep it, but do not let it sit in the abstract as if it were accuracy.

### A6.3 LLM judges with poor agreement carry most of the quality signal

- DeepSeek-V4-Flash string screen: **730,195 judged items**.
- DeepSeek-V4.1-Flash triple evidence screen: **16,032 triples** against 25,714 licence-screened sentences.
- Two-model adjudication for vocabulary mapping (Gemma, DeepSeek-R1).
- Llama-3.1-8B + Mistral-7B as catalogue judges: **85.0% agreement but Cohen's κ = 0.282** (0.293 after re-running).

The manuscript is **honest** about this — it consistently says "concordance, never accuracy" and names the judge alongside each number. **That is a genuine strength; do not dilute it.** But the honest summary is: most quality numbers come from LLM judges whose inter-judge agreement is poor.

### A6.4 The relation-quality admission undermines a headline claim

*(Framing fix: **B3.4**.)*

Limitations concedes:

- Only **8,071 of 25,788** triples carry a typed relation; **17,717 are generic "escape" relations**.
- A string screen judges **just 12.5%** of triples to carry a specific relation label.
- After repair (build 3.1.0): 9,621 triples with a specific relation, 8,307 with a verified cue phrase.
- **After dedup, 61.6% of 23,339 clean triples still state no specific relation.**

You are publishing a relation-extraction contribution in which **most relations are not relations**. Either:

1. **Demote triples** out of the abstract/Results headline (recommended), or
2. **Reframe explicitly**: the contribution is *provenance-preserving extraction with principled abstention*, and the abstention rate is the finding — which is defensible and aligns with the editorial's anti-overstatement position.

Option 2 is the only one that survives review, and it requires rewriting the abstract's triple sentence.

### A6.5 Benchmark results belong to other people's systems

*(Framing fix: **B3.3**.)*

The abstract's headline numbers — "best exact F1 **90.1** on BC5CDR, **80.6** on BioRED" — are **PubTator3** and **HunFlair2**. Your best own system scores **69.5 / 66.2** (Qwen3.5-4B, 3-shot).

So the abstract's strongest quantitative claims describe *existing tools you re-measured*. A reviewer reads this as borrowed credibility. The real finding is the one you under-sell: **transfer-domain recognisers beat in-domain prestige** (lines 1048–1050, and the Recommendations at 1112+). Lead with that.

### A6.6 Domain-transfer measurement is an under-exploited strength

You ran **27 configurations across 21 systems** on two gold standards, and found organism/disease/gene systems *not* trained on BioRED outperform trained ones. That is a reusable, quotable methodological result for the microbiome field — and it is currently buried in "Recommendations". **Promote it.**

### A6.7 No statistical analysis section

The journal's Methods requirements ask for "the type of statistical analysis used, including a power calculation if appropriate". There is no statistics subsection: no test names, no correction for multiple comparisons, no handling of the many percentages reported. Even for a mostly-descriptive paper, state the descriptive conventions: what a percentage is a percentage *of*, the denominators, and how undefined ratios are treated.

## A7. References

### A7.1 35 of 68 bibliography entries are never cited (51%)

`reference.bib` has **68 entries**; **34 keys** are cited (33 resolve in the `.bbl`; `key` is only a comment match).

Uncited entries:
`abdin2024phi3`, `akbik2019flair`, `beltagy2019scibert`, `brown2015gene`, `cohen2017craft`, `collins2026biotriplex`, `cote2006ols`, `deepseek2026v4`, `deepseekv4flashcard`, `efron1993bootstrap`, `gargano2024hpo`, `grattafiori2024llama3`, `jiang2023mistral`, `karkera2023microbiomere`, `kim2004jnlpba`, `lee2019biobert`, `leinonen2011`, `li2025lore`, `lin2023awq`, `liu2019sbert`, `liu2021sapbert`, `luoma2023s1000`, `medjudge2026`, `microbiorel2025`, `minilmcard`, `neumann2019scispacy`, `ollama2026`, `pyysalo2015bionlp13`, `qi2023gutmdisorder`, `vasilevsky2022mondo`, `wilkinson2016fair`, `wilson1927`, `yazdani2026glinerbiomed`, `yilmaz2011mixs`, `zaratiana2024gliner`.

### A7.2 Several of those *must* be cited

| Uncited key | Why it must be cited |
|---|---|
| `liu2021sapbert` | You use **SapBERT by name** in the body (lines 619, 961, 1073) with **no citation** |
| `liu2019sbert` | You use **MiniLM by name** (lines 619–620, 1538) with **no citation** |
| `wilkinson2016fair` | FAIR — the journal explicitly expects FAIR compliance |
| `yilmaz2011mixs` | MIxS — the standard metadata schema the paper is about |
| `wilson1927` | No CIs are reported; this is the method you should be using |
| `efron1993bootstrap` | same |

**General rule being broken:** every named tool/model/standard must be cited **at first use in the body**. Audit all of: GLiNER, BioBERT, SciBERT, spaCy/sciSpaCy, Flair/HunFlair2, tmChem, TaggerOne, DNorm, GNormPlus, PubTator3, MeSH, SapBERT, MiniLM, Qwen, Gemma, Llama, Mistral, vLLM, Ollama.

### A7.3 Reference count is very low for this venue

**34 cited references** is low for a methodology paper at *Microbiome*; comparable accepted methodology/software papers typically cite **60–120**. The 35 uncited entries are already sitting in the bibliography. Wiring them in — plus the standards and the competitors in Part B — is the cheapest credibility gain available.

### A7.4 Bibliography is generated — do not hand-edit

`reference.bib` is generated from `paper/publication/submission_readiness/references_source/bibliography.json`. Fixes go **upstream in the generator**, not in the `.bib`.

## A8. Title, abstract, keywords, front matter

### A8.1 Title

> "Microbiome-CDM: An LLM-driven common data model and knowledge extraction pipeline for human microbiome literature"

- 15 words, acceptable length.
- Promises a **pipeline** (Software framing) while the body claims to be a **protocol** (non-existent article type). **Title, abstract, article type and declared framing must agree.**
- Does not signal "resource" or "reusable metadata", which is what the target audience searches for. Candidate alternative framings in **B4.4** (authors own the title).

### A8.2 Abstract — genuinely in good shape

| Check | Result |
|---|---|
| Word count | **282** (≤350 ✓) |
| Structure | Background / Results / Conclusions ✓ |
| Citations | **0** ✓ (verified: no `\cite` in the abstract block) |
| Abbreviations | Reasonably minimised ✓ |

**Weaknesses:**

- Leads with intermediate-artefact counts — "2,505,684 character-offset mentions", "334,231 candidate vocabulary mappings". A microbiome reader cannot tell what those *buy* them.
- **No reuse or biological payoff sentence.** Nothing says "with this, X becomes possible".
- The highest-visibility numbers (F1 90.1 / 80.6) belong to **other systems** (A6.5).
- The triples claim survives in the abstract despite A6.4.

### A8.3 Keywords

Six supplied — within 3–10 ✓:
`microbiome, common data model, named entity recognition, large language models, text mining, data provenance`

**Add** terms the journal and its search traffic actually use: **metadata standards**, **FAIR**, **data harmonisation**. Currently absent.

### A8.4 Author block

- 3 authors, 3 affiliations, 1 corresponding (starred) ✓
- **Only one email address** (the corresponding author's). The guidelines ask for "email addresses for **all** authors". Likely tolerated but technically non-compliant.
- ORCIDs present for all three ✓
- **Affiliation 3 has no street/postcode** (line 87) while 1 and 2 do. Internal note (lines 78–85) says street/postcode values "confirm against the official imprint pages before submission" — **still open**.
- Internal note also flags remaining `VERIFY` items in `TITLE_PAGE.md`.

### A8.5 Declarations — content check

| Declaration | Status |
|---|---|
| Ethics approval and consent to participate | ✓ "Not applicable. This study analysed only previously published literature and public data; no human participants, human tissue or animal subjects were involved." |
| Consent for publication | ✓ "Not applicable." |
| Availability of data and materials | ⚠ present but future-tense, no DOI (A4) |
| Competing interests | ✗ `[AUTHOR INPUT REQUIRED]` |
| Funding | ✗ `[AUTHOR INPUT REQUIRED]` |
| Authors' contributions | ✗ `[AUTHOR INPUT REQUIRED]` |
| Acknowledgements | ✗ `[AUTHOR INPUT REQUIRED]` |
| AI declaration | ✓ unusually thorough (see A9, strength 1) |

### A8.6 Abbreviations list

13 entries, `list`-based (correct — `sn-jnl`'s `description` env collapses `\labelwidth`). Ensure every abbreviation used in the body is defined **at first use in text** as well as in the list (journal requirement).

## A9. Strengths to protect

Do not lose these while fixing everything else:

1. **The AI-use declaration is excellent.** It separates two distinct roles — (a) LLMs as *pipeline components and evaluation instruments*, naming each model and the item counts (DeepSeek-V4-Flash 730,195 items; DeepSeek-V4.1-Flash 16,032 triples over 25,714 sentences; Gemma + DeepSeek-R1 adjudication; Llama-3.1-8B + Mistral-7B judging) — and (b) AI writing assistance. This exceeds Springer Nature policy and will be noticed favourably.
2. **Honest metric framing.** "Concordance, never accuracy" is applied consistently, and Figure 4's caption explicitly refuses the "accuracy" reading. Keep.
3. **Layer-labelled numbers.** Distinguishing CDM 3.0.3 (2,505,684) from terminology 1.0.1 (2,505,735) is exactly right and rare.
4. **The claims register.** Every table value traceable to a register row is a reproducibility practice most submissions lack — just don't cite the internal filename in the caption (A3.8).
5. **Domain-transfer finding.** 27 configurations / 21 systems; organism, disease and gene recognisers *not* trained on BioRED outperforming trained ones. The best available novel contribution — promote it from "Recommendations" to Results.
6. **Licence discipline.** All 453 papers rights-checked with an explicit matrix. Most corpora papers do not do this.
7. **Build integrity.** Clean from-scratch `latexmk` build: 17 pages, 0 undefined citations, 0 undefined references, 0 errors, no overfull hbox > 5 pt, no float/page-number collisions.

## A10. Venue verdict, in evidence

### For *Microbiome*

- It publishes curation/database/pipeline/methodology work at real volume. 2026 sample of 200 articles: **curation 11, database 10, pipeline 4, metadata 4, benchmark 3, LLM 3**.
- It has an **explicit Methodology article type** whose criteria a provenance-tracked CDM *could* satisfy.
- Text-mining/NER/NLP-titled papers exist (2 of 2,491 total) — precedent exists, but it is thin.

### Against *Microbiome*

- The 2026 editorial pushes hard toward **mechanistic insight** and **substantial technical advance**, and explicitly warns against descriptive/associative work.
- **Strict data release** at reviewer time, plus FAIR and STORMS. You currently fail the first, ignore the second and third.
- **The paper delivers no microbiome result** (A5.2).
- APC **$5,190 / €4,290** — confirm funding exists (currently `[AUTHOR INPUT REQUIRED]`). Waiver requests are only considered **at submission**.

### Against BMC Microbiology

- It publishes far more ontology/KG work (60 vs 13) — a better thematic match for the KG/CDM framing.
- But its 2026 sample (n=300) shows **essentially no text-mining or LLM methodology** (tool 17, curation 15, platform 12). So it is not a better fit for the *method*.

### Conclusion

**Neither journal currently sees a paper that fits cleanly, because the manuscript is framed as NLP engineering with a microbiome corpus rather than as a microbiome resource with NLP underneath** — and because it does not cite the field it claims to advance. That is a *framing* failure and it is fixable, but it requires rewriting the Background, the title, the abstract's payoff sentence, and the related-work section — not just adding sections.

**Recommended path:** rewrite to Methodology framing (provenance + principled abstention + transfer-domain finding, with one demonstrated reuse case), fix everything in Part C, then submit to ***Microbiome***. If the authors will not add a microbiome-facing demonstration, **BMC Microbiology** is the honest fallback.

---

# PART B — POSITIONING AGAINST THE LITERATURE

**One-paragraph verdict.** The honest problem is not that the work is too small. It is that **eight near-identical systems have been published in the last 18 months and the manuscript cites almost none of them.** MicrobiomeKG (2025), MINERVA (2025), MiKG (2024), DiMB-RE (2025), GutBiomeDB (2025), MiDRED (2024), plus the LLM-metadata-extraction line (Ikeda 2025, Turner 2025). The Background lists four of them in one dismissive sentence and then asserts, without evidence, "None of these delivers a provenance-traceable common data model." A reviewer who has read MINERVA or MicrobiomeKG — and at this journal, that is most reviewers — will read that sentence as either uninformed or evasive. **Fixing related work and adding one reuse demonstration is the difference between desk-reject and review.**

## B1. The comparable literature, and what each one proves is publishable

### B1.1 Direct competitors (microbiome + literature extraction)

| System | Venue / year | Scale | What they did that you did not |
|---|---|---|---|
| **MINERVA** (Langarica et al.) | *Briefings in Bioinformatics* 26(5), 2025 | ~130,000 microbiome papers analysed; ontology-driven KG | Explicitly prioritises **accuracy and transparency**; ships a **visual interface**; already drew a methodological critique (Chirumbolo 2025) plus a published author response — i.e. it is *established* enough to be attacked |
| **MicrobiomeKG** (Goetz, Glen, Glusman) | *Frontiers in Systems Biology* 5, 2025 | 27,772 nodes / 112,118 edges from **40 papers** | Three explicit **case studies**; deployed into **NCATS Translator**; novel source (*supplementary tables*, not prose); explicitly positions against KG-Microbe, MicroPhenoDB, MetagenomicsKG |
| **MiKG** (Liu et al.) | *Bioinformatics* 40(1), 2024 | Gut microbiota ↔ neurotransmitter relations | Manuscript-curated relations + **pathway data** fused; relations *typed by biology*, not by generic predicate |
| **DiMB-RE** (Hong et al.) | *JAMIA* 2025 | 14,450 entities / 4,206 relations from **165 publications**; 15 entity types, 13 relation types | A **gold-standard annotated corpus** released for others to train on; reported inter-annotator agreement |
| **MiDRED** (Hogan et al.) | BioNLP 2024 | annotated corpus for microbiome KB construction | Releases **annotation guidelines** as a citable artefact |
| **GutBiomeDB** | *Nucleic Acids Research* 2025 | 168,464 samples / 482 BioProjects / 72 countries / 224 conditions | Same source compendium as you, converted into a **queryable database with an analysis platform** |
| **MetagenomicsKG** (Ma et al.) 2024, **KG-Microbe** (Santangelo 2025), **MicroPhenoDB** (Yao 2020) | various | integrative microbiome KGs | Each is a named, citable prior system the paper never mentions |

### B1.2 The adjacent line you must cite: LLM metadata extraction from papers

| Paper | Venue | Relevant finding |
|---|---|---|
| **Ikeda et al. 2025** — "Extraction of biological terms using LLMs enhances the usability of metadata in the BioSample database" | *GigaScience* 2025, 26 citations | **The closest analogue to this paper's premise.** They evaluated LLMs on a **gold-standard dataset** and reported extraction quality against it — exactly the experiment you did *not* run (you have no human gold standard) |
| **Turner et al. 2025** — "LLMs can extract metadata for annotation of human neuroimaging publications" | *Frontiers in Neuroinformatics* 2025, 14 citations | Same pattern: LLMs + metadata schema + **human-verified subset**. Demonstrates the field accepts a *single-domain metadata extraction* paper if the validation is human |
| **Giuliani et al. 2025** — "Identifying biomedical entities for datasets in scientific articles" | *JMIR Formative Research* 2025 | Dataset-entity recognition, directly comparable to your DATA_ASSET type |

**Why this matters:** Ikeda and Turner both got into good journals doing *less* than you — smaller corpora (one domain, no 453-paper build, no CDM, no triples), but with **human gold-standard evaluation**. Your weakness is precisely their strength. Conversely your scale is far beyond theirs. That asymmetry is the whole framing problem in one sentence.

### B1.3 Infrastructure you already have and never mention

`src/cdm_pipeline/export/` in your own repository contains:

- `sssom.py` — **SSSOM 1.0** mapping export
- `biocypher.py` — **BioCypher / KGX / Biolink Model** node-edge export, "suitable for ingestion by BioCypher or the **NCATS Translator ecosystem**"
- `export_release_rdf.py` — RDF export
- `build_zenodo_bundle.py` — deposit builder

**Grep of the manuscript body for `SSSOM`, `BioLink`, `Biolink`, `KGX`, `Translator`, `RO-Crate`, `PROV-O`, `W3C PROV`: all zero.**

You have Biolink- and Translator-compatible exports sitting in the repo, and MicrobiomeKG's *entire competitive claim* is "we are in Translator." You are not claiming a capability you already built. This is the single cheapest, highest-leverage fix in this document.

## B2. What you are missing — by category

### B2.1 Missing related work (the fatal one)

Zero mentions in the body of: `MicrobiomeKG`, `MetagenomicsKG`, `KG-Microbe`, `MicroPhenoDB`, `MiKG`, `GutBiomeDB`, `Medaka`, `SemRep`, `DeepKE`, `AIONER`, `BioREx`, `SSSOM`, `Biolink`, `KGX`, `RO-Crate`, `PROV-O`.

Present but thin: `BugSigDB` (17), `MINERVA` (3), `DiMB-RE` (1), `knowledge graph` (**1**), `ontology` (**1**).

**The phrase "knowledge graph" appears once in a 4,507-word paper about building a graph.** That alone signals the paper is not in conversation with its own field.

### B2.2 Missing the standards you are implicitly implementing

*(Policy reason this matters at this journal: **A4.4**.)*

Body grep returns **zero** for `FAIR`, `MIxS`, `MIMARKS`, `STORMS`, `STREAMS`.

You are building a common data model for microbiome study metadata. STORMS *is* the reporting standard for exactly that metadata (host species, body site, condition, assay). MIxS/MIMARKS *is* the minimum-information schema for the sequencing metadata. The journal's own editorial (`s40168-025-02091-0`) names STORMS and FAIR explicitly. Not mentioning them makes the paper look built by people who have not read the field's standards — while claiming to standardise the field.

Note: `wilkinson2016fair` and `yilmaz2011mixs` are **already in `reference.bib` and never cited**. The citations are sitting there waiting.

### B2.3 Missing the provenance standard

You claim "provenance-traceable" as your central differentiator. You implement it ad hoc (program identity per row, verbatim evidence sentence, source offsets). You never reference **W3C PROV / PROV-O**, the standard for exactly this. A reviewer from the semantic-web side will ask "why not PROV-O?" and you have no answer in the text. Either map to PROV-O, or state in one sentence why per-row program identity is sufficient.

### B2.4 Missing a reuse demonstration

This is the second fatal gap. Confirmed by direct inspection:

- **Figures:** 3 total — pipeline overview, CDM architecture, evaluation metrics. **None shows microbiome data.**
- **Taxon names in the entire body:** `Lactobacillus` ×1, `Lactococcus` ×1. Nothing else. No *Faecalibacterium*, *Akkermansia*, *Prevotella*, *Bacteroidetes*, *Firmicutes*.
- **The IBD use case is cited as a caveat, not reported as a result.** Line 1274 reads: *"the IBD use case (one exploratory case study; the register records only that 25 of 44 genus-by-condition cells agree with independent BugSigDB consensus) does not establish clinical validity."*

So you *ran* a genus-by-condition consensus analysis, got **25/44 cells agreeing with independent BugSigDB curation**, and reported it **only in Limitations as a thing that does not establish clinical validity.**

That is a result. It is small, but it is the *only* place in the manuscript where the CDM produces a microbiome-facing finding, and it is buried in the section that says what is wrong with the paper. **Promote it.** MicrobiomeKG published on the strength of three case studies at 1/18th your scale. MINERVA published on a KG plus a viewer.

### B2.5 Missing whole-pipeline comparison

You compare 27 NER configurations on BC5CDR/BioRED. You **never** compare Microbiome-CDM-as-a-system against MINERVA, MicrobiomeKG, PubTator3-as-pipeline, or BugSigDB as an alternative route to the same goal. The **Software** article type at *Microbiome* explicitly requires "direct comparison with available related software."

### B2.6 Missing human evaluation and statistics

- One blinded reviewer, n=500, **61.8% exact / 6.2% wrong**, **no confidence intervals**.
- Second-reviewer 100-row overlap "prepared, not done" (open item **H01**).
- LLM-judge inter-agreement κ = **0.282** — poor.
- No test names, no multiple-comparison policy, no bootstrap. (`wilson1927`, `efron1993bootstrap` are in the `.bib`, uncited.)

DiMB-RE reported IAA against a gold corpus. Ikeda reported against a gold standard. You report against a single reviewer with no CI. **This is the difference reviewers will name.**

### B2.7 Missing a novelty paragraph

`novel`/`novelty` appears **twice** in 1,626 lines, neither time as a claim. There is no paragraph saying what is new relative to each named prior system. At a journal whose editorial demands a "substantial conceptual or technical advance", the absence is conspicuous.

### B2.8 Missing the community/sustainability story

MINERVA has a viewer. MicrobiomeKG is in Translator. MicrobiomeKG explicitly says it "is designed to supplement (and be integrated with) such existing knowledge bases, not to replace them." You say nothing about how yours is used, updated, or integrated. A reviewer asks: *is this a one-shot artefact that will die on the author's disk?* Nothing in the manuscript answers that.

## B3. What you are framing incorrectly

### B3.1 "Protocol" — an article type that does not exist

*(Article-type criteria: **A5.1**.)*

The manuscript calls itself a **protocol** in 17 places, including the abstract ("We present a protocol that constructs a…") and line 286 ("We built Microbiome-CDM as a protocol rather than a single model").

*Microbiome* has **no Protocol article type**. Its types are Research, Methodology, Software, Review, Brief report, Comment, Correspondence, Meeting Report.

You are describing a **Methodology** paper using a word that maps to no category. Every time a reviewer reads "protocol" they hear "we have not implemented this / this is a plan", which is the opposite of what a Methods paper must convey.

**Decide: Methodology or Software. Then delete the word "protocol" from the entire vocabulary of the paper.** Replace with "pipeline" (Software) or "method" (Methodology). Do not mix.

### B3.2 "Provenance-traceable common data model" is asserted, not shown

The Background's closing rhetorical move is:

> "None of these delivers a provenance-traceable common data model over the cited literature of a compendium."

Two problems:

1. **It is factually contestable.** MicrobiomeKG traces every edge to a supplementary table cell. MINERVA traces to paper. DiMB-RE traces to annotation. "None of these delivers provenance-traceable" is not a defensible claim about that literature.
2. **It is a claim about others used as a substitute for a claim about yourself.** The correct form is: *"X, Y and Z each deliver [capability]. None provides [specific capability C]. We provide C, and here is the demonstration."*

Rewrite as an explicit capability matrix (B4.1 below).

### B3.3 The NER benchmark framing makes you look derivative

*(The evaluation-side view is **A6.5**.)*

Abstract headline numbers: **F1 90.1 on BC5CDR, 80.6 on BioRED**. These are **PubTator3** and **HunFlair2**. Your own best system is **69.5 / 66.2** (Qwen3.5-4B, 3-shot).

So the abstract's two strongest numbers describe **other people's tools, which you re-measured.** A reviewer reads: *"the best results in this paper are not the authors'."*

The genuinely interesting finding is the one currently buried on line 1048 and in Recommendations:

> **Organism, disease and gene recognisers not trained on BioRED outperform those trained on it. Spearman correlation between BioRED F1 and corpus grounding is 0.749 — high, but not sufficient to select models by leaderboard.**

That is a reusable, quotable, transferable methodological result that matters to anyone building a microbiome extraction pipeline. **Lead with it. Move the borrowed benchmarks to a supporting position.**

### B3.4 The triples are framed as a contribution while being mostly not relations

*(The evaluation-side view is **A6.4**.)*

- 25,788 triples; only **8,071** typed; **17,717** are `OTHER_RELATION`.
- After dedup, **61.6% of 23,339 clean triples state no specific relation.**
- String screen judges only **12.5%** to carry a specific relation.

You are presenting relation extraction in which most relations are placeholders. The Limitations admit this; the abstract and Results still sell triples.

**Only one framing survives review:** make **principled abstention** the finding. "We extract 25,788 provenance-anchored candidate assertions and deliberately abstain from typing 69% of them, because the source sentence does not state a specific relation. Systems that force a label here are manufacturing signal." That is a real, defensible, and *editorially popular* position — the journal's own editorial warns against overstatement. The alternative (pretending 17,717 generic relations are relations) gets you rejected at review.

### B3.5 453 vs 452 vs 444 is never resolved for the reader

Manuscript says **453** papers / 4,006 sections. The analysis universe is **452** (`HMPAPER_000372` excluded — an HTML redirect stub, 908 body chars, zero catalogue records). The entity totals quoted elsewhere come from a **444-paper** build.

`HMPAPER_000372` appears **nowhere** in the manuscript. A reviewer who downloads the deposit and counts will find the discrepancy. State the 452-paper analysis universe explicitly in Methods and name the exclusion.

### B3.6 Layer ambiguity in the headline counts

`2,505,684` (CDM 3.0.3) vs `2,505,735` (terminology 1.0.1) vs `2,505,736` (manifest). You do label them, which is better than most. But the three numbers are not explained *relationally* — a reader cannot tell which one to quote. One sentence in Methods: "these differ by N because [X]; quote the build-specific number."

### B3.7 Internal artefacts named in published text

*(Same defect as **A3.8**.)*

Table 1's caption says the last column "names the row in the claims register (`MANUSCRIPT_CLAIMS_REGISTER.csv`)." Reviewers cannot open that. Either ship it as an additional file or drop the filename.

### B3.8 The corpus looks arbitrary because the inclusion rule is unstated

"453 papers cited by a 168,464-sample compendium" is a defensible, *interesting* sampling frame — a citation-closed set around a landmark synthesis. But the manuscript never states:

- how many works the compendium cited in total,
- how many were retrievable,
- how many failed and why (paywall? no full text? not microbiome?),
- what fraction of the microbiome literature this represents.

Without that, "453" reads as "however many we could download." With it, "453" reads as "the complete citable literature behind the field's largest synthesis." Same number, completely different paper.

### B3.9 179/453 papers withheld — stated, but the consequence is not

*(The policy reason this is blocking is in **A4.3**.)*

274 INCLUDE_TEXT / 15 RESTRICTED_NC_LAYER / 164 WITHHOLD_TEXT ⇒ **179 of 453 papers cannot be redistributed.** Legally correct and honestly stated.

But you never state the consequence: **no reviewer can rebuild your corpus.** So the deposit must contain the paper list, the per-paper licence decision, and source hashes, so the build is *verifiable-by-reconstruction*. And you must say whether any headline number depends on withheld text.

Same issue for derived annotations: the text implies only raw text is withheld. Mention offsets, spans and evidence quotes over withheld papers too.

### B3.10 Data availability is future tense

*(Full policy analysis and fixes: **A4**.)*

> "The outputs of this protocol **will be** deposited on Zenodo **before publication**… DOI [to be added]… The pipeline code **will be** released… [repository and DOI to be added]."

The journal requires data **available to reviewers at submission**. "Will be" is not available. This alone can trigger a pre-review bounce. Two empty DOI slots remain.

## B4. How to frame it better — concrete rewrites

### B4.1 Add the capability matrix (highest-value single addition)

A table reviewers can read in 20 seconds. Fill it honestly — including where you *lose*.

| | BugSigDB | MINERVA | MicrobiomeKG | MiKG | DiMB-RE | PubTator3 | **Microbiome-CDM** |
|---|---|---|---|---|---|---|---|
| Unit | curated signature | microbe–disease edge | assertion from suppl. table | curated relation | annotated corpus | entity annotation + relation | provenance-anchored mention/triple |
| Source | manual curation | 130k papers | 40 papers | manual + pathway | 165 papers | all PubMed/PMC | 453 papers (full text) |
| Scale | 2,500+ signatures | large KG | 112k edges | small, deep | 14,450 ent / 4,206 rel | ~1B annotations | 2.5M mentions / 25,788 triples |
| Entity types | taxa, signature | taxa, disease | taxa, pathway, phenotype | taxa, neurotransmitter | 15 types | 6 types | 14 CDM types |
| Provenance | paper + curator | paper | table cell | annotation | annotation | offset | **program identity + offset + verbatim sentence** |
| Abstention | n/a | not stated | not stated | n/a | n/a | n/a | **explicit, 69% typed-as-generic** |
| Interop export | web | viewer | Translator | — | HF dataset | API/FTP | **SSSOM, KGX/Biolink, RDF (built, unreported)** |
| Gold standard | curator consensus | — | — | annotation | **IAA reported** | benchmark | **single reviewer, no CI** ← your loss |
| Licence discipline | n/a | — | — | — | — | — | **453/453 rights-checked** ← your win |

Two rows you win outright (provenance granularity, licence discipline), one you lose outright (gold standard). Showing the loss buys credibility for the wins.

### B4.2 Rewrite the Background's dismissal sentence

**Current:**
> "Adjacent computational efforts do not close the gap either: MiDRED…; DiMB-RE…; MINERVA…, whose methodology has been questioned…; LLM-based metadata harmonisation has been explored… None of these delivers a provenance-traceable common data model over the cited literature of a compendium."

**Problems:** lumps six systems into one sentence, names a published dispute as if it were a point in your favour (**do not attack MINERVA's methods — cite the exchange neutrally or omit it entirely; using a critique of a competitor as your competitive advantage reads as bad faith to the reviewer who wrote the response**), and ends on an unsupported universal negative.

**Replace with three short paragraphs:**

1. *Curation-based resources* (BugSigDB, DiMB-RE, MiDRED) — what they achieve, why capacity-bound.
2. *Aggregation-based resources* (MINERVA, MicrobiomeKG, MiKG, MetagenomicsKG, KG-Microbe, MicroPhenoDB, GutBiomeDB) — what they achieve, and the specific gap: none exposes per-row **program identity** across a heterogeneous multi-NER ensemble, and none reports **abstention** as a first-class output.
3. *LLM metadata extraction* (Ikeda, Turner, Higashi) — established for narrow schemas in single domains; not established at corpus scale with auditable provenance.

Then one sentence: *"We address (2)+(3) by …, and we make abstention explicit rather than forced."*

### B4.3 Rewrite the abstract's payoff

The abstract currently leads with intermediate artefact counts (2,505,684 mentions; 334,231 mappings). A microbiome reader cannot tell what those buy.

Add one sentence in Results, structured like this (the authors must supply the actual finding):

> "As a first use, the model reproduces [N of M] genus-by-condition associations independently curated in BugSigDB, and surfaces [K] candidate associations with no BugSigDB entry and verbatim textual support."

And one in Conclusions:

> "[Concrete capability]. The resource and all per-row provenance are deposited at [DOI] under [licence], with [SSSOM/KGX] exports for integration into existing microbiome knowledge graphs."

**Only write the second sentence if the deposit and exports actually exist.** Do not promise.

### B4.4 Reframe the title toward what the journal indexes

Current: *"Microbiome-CDM: An LLM-driven common data model and knowledge extraction pipeline for human microbiome literature"* — promises a pipeline; body says protocol; no reader-facing benefit.

Options (authors decide):

- Resource flavour: *"…: a provenance-traceable common data model for reusing microbiome study metadata at literature scale"*
- Method flavour: *"…: quantifying what multi-program extraction can and cannot recover from the human microbiome literature"*
- Finding flavour: *"Transfer-domain recognisers outperform in-domain benchmarks for microbiome literature extraction, and most extracted relations should not be typed"*

The third is the most competitive and the most honest to the actual results.

### B4.5 Add a novelty paragraph

One paragraph, explicitly structured: *"Relative to MINERVA we add X. Relative to MicrobiomeKG we add Y. Relative to DiMB-RE we add Z. Relative to PubTator3 we add W."* Place at the end of Background. This is standard at this journal and its absence is noticed.

---

# PART C — MASTER FIX LIST

Items are deduplicated across both parts and grouped by how blocking they are. Numbers are stable references for tracking.

## Tier 0 — cannot submit without these

1. **Decide the venue** (Part 0) — *Microbiome* vs BMC Microbiology. Everything downstream depends on it.
2. **Decide the article type** — Methodology or Software. Then delete "protocol" from the paper's vocabulary (17 occurrences, including the abstract).
3. Replace the **4** `[AUTHOR INPUT REQUIRED]` blocks (competing interests, funding, CRediT, acknowledgements).
4. Fill the **Zenodo DOI** and the **code repository + DOI**.
5. **Upload the deposit before submission**; convert "will be deposited" to present tense with a live DOI.
6. Add `\section{Methods}` — rename/absorb the five Stage sections as subsections.
7. Add `\section{Discussion}` with **Limitations and Recommendations as subsections**.
8. Add `\section{Conclusions}`.
9. Enable `referee,lineno` (double spacing + line numbers) for the submission build.
10. Fix bare **"16S" → "16S rRNA gene"** (lines 816, 1010, 1071) — explicit journal rule.
11. Remove the internal `MANUSCRIPT_CLAIMS_REGISTER.csv` reference from Table 1's caption (line 927).
12. Produce a **comment-stripped `.tex`** for submission (931 comment lines, 29 "Claude" mentions).

## Tier 1 — reviewer-facing, decisive

13. **Write the SSSOM / KGX-Biolink / RDF exports into the paper** — they exist in `src/cdm_pipeline/export/`. Instantly answers the FAIR question and puts you in the same interoperability conversation as MicrobiomeKG's Translator deployment. **You built it and forgot to claim it.**
14. Add the **capability matrix** (B4.1) — one table answers "how are you different" before it is asked.
15. **Rewrite the related-work paragraph** into the three-paragraph structure (B4.2) and **cite every competitor** in B1.1–B1.2.
16. **Promote the IBD 25/44 result** from Limitations into Results as "a first reuse demonstration". You already have the analysis; it is currently published as an apology.
17. Add a **FAIR + MIxS/MIMARKS + STORMS/STREAMS** paragraph to Background and Availability; cite `wilkinson2016fair`, `yilmaz2011mixs`.
18. Add **confidence intervals** (Wilson / bootstrap) to 61.8%, 6.2% and κ = 0.282; cite `wilson1927`, `efron1993bootstrap`.
19. **Finish or remove** the second-reviewer 100-mapping overlap (H01).
20. **Reframe triples as principled abstention** in abstract + Results, or demote them.
21. **Fix the abstract's borrowed-benchmark framing** (90.1 / 80.6 are PubTator3 / HunFlair2).
22. **Promote the transfer-domain finding** (27 configs / 21 systems; Spearman 0.749; non-BioRED-trained organisms/diseases/genes win) from Recommendations to Results.
23. **Cite SapBERT and MiniLM** at first use; audit every named tool/model at first use.
24. **Prune or cite** the 35 uncited references; raise the cited count toward 60+.
25. **State the inclusion rule** for the 453-paper corpus (cited-works count → retrievable → included/excluded why).
26. **Resolve 453 vs 452**; name `HMPAPER_000372` or state the 452-paper analysis universe.
27. Add a **novelty paragraph** (B4.5).
28. Add an **"Additional files"** list; ship paper list + licence matrix + hashes so the corpus is verifiable-by-reconstruction.
29. Add **"Authors' information"** heading; add emails for **all** authors (currently corresponding only).
30. Complete affiliation 3 **street/postcode** and clear the `VERIFY` items in `TITLE_PAGE.md`.

## Tier 2 — quality, consistency, and defence

31. Add one **small biological figure** — e.g. a genus × condition consensus heat map with BugSigDB overlap annotated. The single change that turns this from NLP engineering into a microbiome resource.
32. **Compare the pipeline as a system** vs PubTator3-as-pipeline at equal corpus (PubTator3 coverage is already 438/453). Directly satisfies the Software criterion "direct comparison with available related software".
33. Add a short **statistics/reporting-conventions** paragraph (denominators, how ratios are defined, multiple comparisons).
34. Explain the **2,505,684 vs 2,505,735 vs 2,505,736** layer distinction and the known manifest off-by-one, in Methods.
35. Clarify that **derived annotations** over withheld text (not only raw text) are restricted/redacted.
36. Add a **PROV/PROV-O** paragraph: map per-row provenance to PROV-O, or justify why not.
37. Add a **sustainability/community** sentence: how the resource is updated, versioned and integrated.
38. Rewrite the three figure legends flagged `AUTHOR REWRITE REQUIRED` (lines 347, 729, 952).
39. Add a sentence in Declarations stating the **deposit licence** (CC BY 4.0 proposed).
40. Verify Fig. 2's "**33 entity types**" against the actual 3.0.3 build — the 33-entity schema is a *design-phase proposal* and was never migrated.
41. **Merge Fig. 1 and Fig. 2** if page pressure allows; decide on the unused `fig_overview_illustrated.pdf`.
42. Add biology-facing **keywords**: "metadata standards", "FAIR", "data harmonisation".
43. Reconcile **33 `.bbl` entries vs 34 cite keys**.

## Tier 3 — polish and strategy

44. Write a **cover letter** arguing field relevance with one concrete use case.
45. Consider a resource- or finding-flavoured **title** (B4.4).
46. Check every abbreviation is defined at first use in text, not only in the list.
47. Run `manuscript-style-check` and `text-overlap-check` before submission.
48. Re-run the clean `latexmk -pdf` build after all edits and re-verify 0 errors / 0 undefined / no float collisions.

## Effort ordering (value ÷ effort), if time is short

| Effort | Items |
|---|---|
| **Under an hour** | 2 (delete "protocol"), 10 (16S), 11 (claims register), 23 (SapBERT/MiniLM), 24 (cite uncited), 42 (keywords), 12 (strip comments) |
| **Under a day** | 13 (exports), 14 (capability matrix), 15 (related work), 16 (IBD), 17 (standards), 18 (CIs), 22 (transfer finding), 26 (452), 28 (additional files) |
| **Days, but decisive** | 19 (second reviewer), 31 (biological figure), 32 (system comparison), 36 (PROV-O) |
| **Blocking, outside writing** | 3 (author facts), 4–5 (deposit + DOI), 30 (affiliations) |

---

# PART D — HONEST ACCEPTANCE ASSESSMENT

No honest analysis can promise "100% acceptance", and this document does not. *Microbiome* has a low acceptance rate, an editorial policy pushing for mechanistic insight or substantial technical advance, and reviewers drawn from the very groups that built MINERVA, MicrobiomeKG and BugSigDB — who will be asked to assess a paper that currently does not cite them.

What can be said precisely is the difference in outcome between the current manuscript and a competitive one:

| Current state | After Tier 0–2 | Effect |
|---|---|---|
| Cites 4 of 11 direct competitors | Cites all; capability matrix | Removes the "not in conversation with the field" rejection |
| Calls itself a protocol (no such type) | Methodology or Software, consistently | Removes a framing desk-reject |
| No reuse demonstration | IBD reuse promoted + one biological figure | Removes the "no microbiome content" rejection |
| No human gold standard, no CI, one reviewer | Two reviewers + Wilson CIs | Removes the "insufficient validation" rejection |
| 35 uncited refs, 34 cited total | 60+ cited, standards included | Removes the "thin scholarship" rejection |
| Interop exports invisible | SSSOM/KGX/RDF claimed | Adds a genuine competitive capability |
| Borrowed benchmarks lead | Transfer-domain finding leads | Owns the contribution |
| Future-tense availability | Live DOI at submission | Removes a pre-review bounce |

That gets the manuscript **into review with a fair hearing**. Whether it is accepted still depends on the reviewer draw, on whether the authors will add the biological demonstration, and on whether the editor judges a provenance-disciplined extraction resource to be within scope that month.

**The honest risk assessment:** without Tier 2 items 31–32 (one biological figure, system-level comparison) and Tier 1 item 19 (second reviewer), the paper is very likely rejected with *"the authors present a well-engineered pipeline but do not demonstrate that it enables new microbiome insight, and the validation is a single-reviewer spot check."* With them, it is a credible Methodology paper.

**BMC Microbiology remains the honest fallback** if the authors will not invest in the biological demonstration — it publishes the KG/ontology framing at volume (60 vs 13 ontology-titled papers) and does not carry the mechanistic-insight editorial pressure.

---

# PART E — SEQUENCING

1. **Answer Part 0** — which journal, and Methodology or Software.
2. **Tier 0 items 3–5** (author facts + DOIs + deposit upload) — these gate everything else.
3. **Upload the deposit**, add the SSSOM/KGX/RDF exports to it, then rewrite Availability in present tense.
4. **Restructure** (Tier 0 items 6–9) in one pass, since Methods/Discussion/Conclusions move together.
5. **Rewrite Background** (B4.2) + add the capability matrix (B4.1) + novelty paragraph (B4.5); cite all competitors.
6. **Promote the IBD reuse result** and the **transfer-domain finding** into Results; reframe triples as abstention.
7. **Add the comparison table and the biological figure** — highest value per hour for reviewer confidence.
8. **Finish the second reviewer**; add Wilson CIs.
9. Strip comments, rebuild, verify 0 errors, then run `manuscript-style-check` and `text-overlap-check`.

---

# Appendix 1 — manuscript statistics snapshot

| Metric | Value |
|---|---|
| `manuscript.tex` lines | 1,626 |
| Comment lines | 931 (57%) |
| "Claude" mentions | 29 |
| Body words (excl. tables/figures/comments) | 4,507 |
| Abstract words | 282 |
| Figures | 3 (vector, 0 raster) |
| Tables | 1 (`table*`) |
| Top-level sections | 10 + 2 unnumbered |
| Bibliography entries | 68 |
| Distinct cite keys | 34 |
| Compiled `.bbl` entries | 33 |
| Uncited bib entries | 35 (51%) |
| `[AUTHOR INPUT REQUIRED]` markers | 4 visible (+ 6 in comments = 10 total) |
| Unfilled DOI/repository slots | 2 |
| PDF pages | 17 |
| LaTeX errors | 0 |
| Undefined citations/references | 0 |
| Overfull hbox > 5 pt | 0 |
| Unused figure file | `Fig/fig_overview_illustrated.pdf` |

# Appendix 2 — evidence log

**Journal guidance** (retrieved 2026-11-10 via the `r.jina.ai` proxy; the BMC domain itself serves a JS "Client Challenge" page and cannot be fetched directly):

- `https://link.springer.com/journal/40168/submission-guidelines`
- `.../submission-guidelines/research-article`
- `.../submission-guidelines/methodology`
- `.../submission-guidelines/software-article`
- `https://link.springer.com/article/10.1186/s40168-025-02091-0` (senior-editor editorial: scope, STORMS, FAIR, anti-overstatement)
- `https://doaj.org/api/search/journals/issn%3A2049-2618` (APC, licence, waiver)

**Journal-profile counts** from PubMed E-utilities (`esearch`/`efetch`, `db=pubmed`):

- *Microbiome* total 2,491; BMC Microbiology total 7,641
- software/database/tool/pipeline/platform/web-server/resource/benchmark titles: 41 vs 77
- knowledge-graph/ontology: 13 vs 60
- text-mining/NER/NLP: 2 vs 2
- LLM in abstract: 2 vs 1
- "common data model"/harmonisation/metadata: 21
- 2026 samples parsed to `/home/jkalra_hpc/jk_fig/microbiome_2026.xml` (200 records) and `/home/jkalra_hpc/jk_fig/bmcmicro_2026.xml` (300 records)

**Competitor systems located (2026-11-10):**

- MINERVA — Langarica et al., *Brief Bioinform* 26(5):bbaf472, 2025 (PMID 40984703); critique Chirumbolo 2025 (PMC12780759)
- MicrobiomeKG — Goetz, Glen, Glusman, *Front Syst Biol* 5:1544432, 2025 (PMID 40951793; PMC12425944)
- MiKG — Liu T. et al., *Bioinformatics* 40(1):btad771, 2024
- DiMB-RE — Hong G. et al., *JAMIA* 2025 (arXiv 2409.19581); 14,450 entities / 4,206 relations / 165 publications
- MiDRED — Hogan W. et al., BioNLP 2024 (aclanthology 2024.bionlp-1.31)
- GutBiomeDB — *NAR* 2025 (doi 10.1093/nar/gkag1125); 168,464 samples / 482 BioProjects / 72 countries
- PubTator 3.0 — Wei C.-H. et al., *NAR* 52(W1):W540, 2024 (AIONER annotation, BioREx relations)
- Ikeda S. et al., *GigaScience* 2025, giaf070 (PMID 40549542) — LLM BioSample metadata, gold-standard evaluation
- Turner M.D. et al., *Front Neuroinform* 2025 (PMC12405296) — LLM neuroimaging metadata
- Giuliani C. et al., *JMIR Form Res* 2025;9:e73822 — dataset entity recognition
- STORMS — Mirzayi C. et al., *Nat Med* 2021 (PMC9105086); STREAMS — *Nat Microbiol* 2025 (s41564-025-02186-2)

**Manuscript greps (body text, comments excluded):**
`MicrobiomeKG` 0 · `MetagenomicsKG` 0 · `KG-Microbe` 0 · `MicroPhenoDB` 0 · `MiKG` 0 · `GutBiomeDB` 0 · `Medaka` 0 · `SemRep` 0 · `DeepKE` 0 · `AIONER` 0 · `BioREx` 0 · `SSSOM` 0 · `Biolink` 0 · `MIxS` 0 · `MIMARKS` 0 · `STORMS` 0 · `STREAMS` 0 · `FAIR` 0 · `RO-Crate` 0 · `PROV-O` 0 · `W3C PROV` 0 · `knowledge graph` 1 · `ontology` 1 · `MINERVA` 3 · `DiMB-RE` 1 · `BugSigDB` 17

Taxa in body: `Lactobacillus` 1, `Lactococcus` 1, all others 0. Figures: 3, none showing microbiome data.

**Repo assets unreported in the manuscript:** `src/cdm_pipeline/export/sssom.py`, `biocypher.py` (Biolink/KGX/Translator), `export_release_rdf.py`, `build_zenodo_bundle.py`.

**Manuscript internals** read from `oup-authoring-template/manuscript.tex`, `reference.bib`, `manuscript.bbl`, `manuscript.log`, `tables/table_pipeline_summary.tex`, `paper/publication/final_validation/PAPER_NUMBERS_2026-11-09.md`, `paper/publication/manuscript_bib/TITLE_PAGE.md`.
