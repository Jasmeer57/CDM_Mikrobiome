# Fit and positioning assessment: *Microbiome*, BMC Microbiology, and *mSystems*

**Subject:** `oup-authoring-template/manuscript.tex`
*"Microbiome-CDM: An LLM-driven common data model and knowledge extraction pipeline for human microbiome literature"*

**Date:** 2026-11-10
**Manuscript status:** converted to Springer Nature `sn-jnl` v3.1 (`sn-vancouver-num`); clean `latexmk -pdf` build, **18 pages / 406,353 bytes**, 36 `\bibitem` entries, 0 undefined citations/references, 0 LaTeX errors (1 overfull hbox at 4.86 pt, 28 underfull). Re-typed results and the two factual fixes in A6.8 are committed on branch `submission-prep-2026-11-10`; nothing has been pushed.
**Scope of this document:** (A) whether the manuscript fits *Microbiome* and every way it currently falls short; (A2) whether the ASM journals — above all *mSystems* — fit it better; and (B) how it compares to the published competition and what to change so it competes. All three belong together: most of the compliance gaps are also positioning gaps, and the choice of venue changes which gaps are blocking.

**Verdict in one line:** the manuscript is *mechanically submittable* apart from 4 author-input blocks and 2 unfilled DOIs, but it is **not yet competitive at *Microbiome***, because it is framed as NLP engineering performed over a microbiome corpus rather than as a microbiome resource — and, separately, because **eight near-identical systems published in the last 18 months are uncited**, so the paper is not visibly in conversation with its own field. **It is, however, close to competitive at *mSystems* today**, because that journal has an article type — **Resource Report** — that describes this paper as written, and has published near-identical papers ([ASM2](#asm2-article-types-at-msystems--and-why-two-of-them-fit-this-paper)–[ASM3](#asm3-do-comparable-papers-actually-get-published-here)).

**Two independent rejection risks, not one:**

1. *Compliance/positioning against the journal* — wrong section architecture, future-tense data availability, no microbiome result, no standards engagement (Part A).
2. *Positioning against the literature* — the competitive claim ("none of these delivers a provenance-traceable common data model") is asserted, contestable, and made without citing most of the systems it dismisses (Part B).

Fixing only the first will not get the paper through review. Both are addressable with existing artefacts.

**A third axis, and the reason Part A2 exists:** *where* the paper is sent changes which of these are blocking. Gap 5 ("protocol") is a framing desk-reject at *Microbiome* and a perfectly valid article type at *mSystems*. Gap 4 ("no microbiome result") is disqualifying at *Microbiome* and optional for a Resource Report at *mSystems*. Gap 2 (nothing deposited) is equally fatal at every venue. Read [Part A2](#part-a2--alternative-venues-the-asm-journals) before deciding how much of Tier 0 to do.

## The ten gaps that decide the outcome

Ranked by how much each one alone can sink the submission.

| # | Gap | Where |
|---|---|---|
| 1 | No `Methods`, `Discussion` or `Conclusions` section — five unlabelled "Stage" sections sit at top level where `Methods` is indexed for | A3.1, A3.2 |
| 2 | Data and code availability is future tense with two empty DOI slots — fails the "available at submission" policy outright **at every venue** | A4.1, A4.2 |
| 3 | Eight direct competitor systems uncited; the gap over them is asserted, not demonstrated | B2.1, B3.2 |
| 4 | No microbiome result and no microbiome figure — the paper never shows what the CDM buys a microbiome scientist | A5.2, B2.4 |
| 5 | Calls itself a "protocol" **12 times in visible prose** (lines 104, 106, 132, 235, 288, 297, 331, 352, 495, 703, 832, 1,447) plus 9 times in comments — 21 total; no Protocol article type exists at *Microbiome* (but **Resource Report** and **Methods and Protocols** both exist at *mSystems*) | A5.1, B3.1, ASM2 |
| 6 | Zero engagement with FAIR, MIxS/MIMARKS, STORMS/STREAMS — the standards the paper implicitly implements | A4.4, B2.2 |
| 7 | Validation is one reviewer, n=500, no confidence intervals, second reviewer unfinished | A6.1, B2.6 |
| 8 | Relation typing is now 52.6% specific (13,564 of 25,788) — better than the previous draft, but the other 47.4% still carry no specific relation, and triples lead the abstract | A6.4, B3.4 |
| 9 | Abstract's headline F1 (90.1 / 80.6) belongs to PubTator3 and HunFlair2, not to this pipeline | A6.5, B3.3 |
| 10 | SSSOM, KGX/Biolink and RDF exports already exist in `src/cdm_pipeline/export/` and are never mentioned | B1.3 |

Items 1–2 are pure logistics. Items 3–4 and 6 need writing. Items 5 and 9–10 cost almost nothing. Items 7–8 need either new analysis or an honest reframing.

**One defect that is not a gap but was worth fixing first, because it took two minutes and it undermined everything else:** the entity-accounting sentence at **1,016–1,023** summed to 38 against a 33-entity registry ([A6.8](#a68-one-sentence-in-results-did-not-add-up-fixed-in-the-working-tree)). It was the first paragraph of Results, and the numbers are the contribution. **Now fixed** — see A6.8.

---

# Part 0 — Unresolved question that blocks further reformatting

The venue is **contested inside the repository**:

- `manuscript.tex` comments (line 88) say: *"BMC Microbiology requires a structured abstract with exactly these three headings…"*
- `manuscript.tex` comments (line 1393, plus the front-matter block at 20–21) reference BMC/Springer Nature declaration ordering.
- The current request asks about **Microbiome (2049-2618)**.
- A third option was raised while this assessment was being written: ***mSystems*** (ASM, 2379-5077).

These are **different journals with different article types, different declarations, different section order, and different framing expectations**. Nothing further should be reformatted until one is chosen — and the choice now genuinely changes the edits, because *Microbiome* requires Methods before Results while ASM requires Methods **after** Discussion.

| | *Microbiome* (2049-2618) | BMC Microbiology (1471-2180) | ***mSystems*** (2379-5077) |
|---|---|---|---|
| Publisher / model | Springer Nature (BMC), hybrid | Springer Nature (BMC), hybrid | **ASM, fully OA, CC BY 4.0** |
| Article types that fit | Research, **Methodology**, **Software**, Brief report, Review | Research, Methodology, Software, **Database**, Short report | Research, **Resource Report**, **Methods and Protocols** |
| KG/ontology-titled papers | **13** | **60** | **0** (18 in tiab) |
| Software/database/tool/pipeline-titled | **41** | **77** | **71** |
| Text-mining/NER/NLP-titled | **2** | **2** | **1** |
| LLM in abstract | **2** | **1** | **4** |
| 2026 sample (200 / 300 articles): curation | 11 | 15 | (25 tiab, all years) |
| 2026 sample: database | 10 | — | (31 resource-titled, all years) |
| 2026 sample: pipeline | 4 | — | — |
| 2026 sample: tool / platform | — | 17 / 12 | — |
| 2026 sample: text-mining/LLM methodology | 3 | **≈ 0** | (4 LLM in abstract) |
| Body word cap | none stated | none stated | **5,000** (current: 3,911 excluding back matter, 4,584 including it) |
| Abstract cap | **350** structured (current: **334 incl. the three bold labels / 331 excl.** — compliant, 16–19 to spare) | 350 structured | **250** + **150-word Importance** (current: **334/331** — **81–84 over**) |
| APC | **$5,190 / €4,290 / £3,590** | **£2,390 / $3,090 / €2,690** | **$4,500** non-member / $3,375 member |
| Initial submission format | editable TeX | editable TeX | **format-neutral — any format** |

**Read of the evidence.** *Microbiome* publishes curation/database/pipeline work at volume and has an explicit **Methodology** article type, but its bar is "a demonstrable advance" and its reviewers are the competitors. BMC Microbiology publishes the most ontology/KG work but essentially **no** text-mining or LLM methodology. ***mSystems* is the only one of the three whose article-type catalogue contains a name for what this manuscript already is** (Resource Report), and it has published near-identical papers.

**Nothing in the comparison settles it**, because fit and odds point the same way but ceiling and audience do not. That is a decision for the authors, and it is the first item in Part C. Full ASM analysis: [Part A2](#part-a2--alternative-venues-the-asm-journals). Full verdict ranking across all five venues considered: [ASM7](#asm7-five-venue-verdict-ranking).

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
| 843 | "…72.1% of **16S identifiers** natively present in the text" | 16S rRNA gene identifiers |
| 1,061 | "…its accession numbers, sequencing platforms and **16S regions** present" | 16S rRNA gene regions |
| 1,125 | "Study metadata agrees closely for **16S** region (97.7%)" | 16S rRNA gene region |

Cheap to fix, but it is an **explicitly stated criterion**, and editors do check it.

## A3. Mechanical and structural non-compliance (blocking)

### A3.1 Wrong section architecture — the most serious structural problem

Required: **Background → Methods → Results → Discussion → Conclusions**.

Actual structure:

| Actual heading | Line | Should be |
|---|---|---|
| Background | 162 | Background ✓ |
| Protocol overview | 331 | §Methods (lead-in) |
| Stage 1: Corpus and sectioning | 406 | §Methods subsection |
| Stage 2: Entity extraction with multiple programs | 460 | §Methods subsection |
| Stage 3: Normalisation and vocabulary mapping | 538 | §Methods subsection |
| Stage 4: Data catalogue and common data model | 679 | §Methods subsection |
| Stage 5: Computational evaluation and human spot check | 774 | §Methods subsection |
| Results | 920 | Results ✓ |
| Recommendations | 1166 | Discussion subsection (or drop) |
| Limitations | 1251 | **Discussion subsection** |
| Abbreviations | 1364 | ✓ (unnumbered) |
| Declarations | 1390 | ✓ (unnumbered) |

Concretely missing:

- **No `\section{Methods}`.** The five "Stage" sections *are* the methods, but they are unlabelled, sit at top level, and use internal engineering vocabulary. Reviewers, abstracting services and indexers all look for "Methods".
- **No `\section{Discussion}`.** Zero occurrences of a Discussion heading.
- **No `\section{Conclusions}`.** The only "Conclusions" is the abstract's third labelled paragraph (line 132).
- The journal states the Discussion "should discuss the implications… and **highlight limitations**". Limitations is therefore a **subsection of Discussion**, not a standalone section — and certainly not the longest section of the paper (A3.2).

### A3.2 Limitations is the paper's only interpretive section — and it carries the wrong load

**Counting convention (state it whenever you quote a number here):** comment-only lines and trailing comments removed, `figure`/`figure*`/`table`/`table*` environments removed as whole blocks, `\cite*`/`\ref`/`\label`/`\eqref` arguments removed, remaining commands and their brace arguments stripped, `$…$` math removed, then declared as the count of whitespace-separated tokens containing at least one alphanumeric character. This is the convention closest to `wc -w` and is the one used in every table below.

| Section | Words |
|---|---|
| Background | 505 |
| Protocol overview | 184 |
| Stage 1: Corpus and sectioning | 129 |
| Stage 2: Entity extraction with multiple programs | 178 |
| Stage 3: Normalisation and vocabulary mapping | 598 |
| Stage 4: Data catalogue and common data model | 168 |
| Stage 5: Computational evaluation and human spot check | 412 |
| **Results** | **1,097** |
| Recommendations | 238 |
| **Limitations** | **402** |
| *(Abbreviations)* | *58* |
| *(Declarations)* | *615* |
| **TOTAL** | **4,584** |

- **Body excluding back matter (Background → Limitations) = 3,911 words; including Abbreviations + Declarations = 4,584.** A whole-body recount between `\section{Background}` and `\bibliography`, measuring the same span contiguously instead of section-by-section, gives **4,604 plain tokens / 4,797 under hyphen-splitting tokenisation** (body only: 3,934 / 4,092). The 20-word difference from 4,584 is heading text. Quote the per-section table (4,584) as the section figure and the whole-body count only as a cross-check. Either way it sits under any cap you would face (mSystems 5,000; no stated cap at *Microbiome*).
- **Methods (five stages + overview) = 1,669 words.** For a five-stage pipeline with four mention sources, 2.5 M mentions, a catalogue and a CDM, 1,669 words of method is still **thin** — the pipeline is now described in more detail than in the previous draft (Stage 3 alone grew to 598), but a reader still cannot reproduce it from the text alone.
- **Results (1,097) is correctly the longest prose section.** An earlier draft of this document claimed "Limitations is longer than Results"; that was wrong and has been retracted. Do not repeat it — the corrected figures invert it.
- **The real defect is structural, not arithmetical.** There is no `\section{Discussion}`, so **Limitations (402) is the only section doing interpretive work**. A Discussion section normally absorbs limitations as *one subsection among several*; here self-criticism occupies the whole of the paper's one interpretive slot. To an editor that reads as a manuscript spending its scarce interpretive space arguing against itself — but the evidence for that is the missing Discussion heading and the standalone Limitations section, not a length comparison.

### A3.3 Formatting requirements not met

- **No line numbers.** `\documentclass[pdflatex,sn-vancouver-num]{sn-jnl}` (line 23); the `referee,lineno` variant exists only as a comment (line 25).
- **No double spacing.** Both are explicit requirements for the main text.
- Both are one-line preambles changes, not rewrites — but they change line/page flow, so rebuild and re-check the float placement afterwards.
- Page breaks: **0** `\newpage`/`\clearpage` — compliant ✓.

**Fix:** for the submission copy use `\documentclass[referee,lineno,pdflatex,sn-vancouver-num]{sn-jnl}`. Keep the clean build for internal reading.

### A3.4 Missing back-matter sections

The manuscript has **8 `\bmhead` blocks** (1,392 Ethics, 1,398 Consent, 1,401 Availability, 1,476 Competing interests, 1,493 Funding, 1,507 Authors' contributions, 1,526 Acknowledgements, 1,539 AI declaration) — that is the full BMC required set, so this section is **mostly compliant**. Three items are genuinely absent:

- **No "Authors' information" heading** — **0 occurrences in the file**. Caveat, stated honestly: this heading is part of the Springer Nature `sn-jnl` template and is required by some SN journals, but it is **not** in BMC's own published list of mandatory declarations (which is the seven above plus the AI declaration). Treat it as *low-risk optional*, not a blocker — but if the venue turns out to want it, the fix is one short `\bmhead{Authors' information}` block, and the authors must write its content (do not invent biographies).
- **No "Endnotes"** — fine if unused, but it is in the `sn-jnl` required list.
- **No "Additional files" list** (`0 occurrences`). For a data-deliverable paper everything is either in-text or external. Reviewers will expect at least: per-stage counts table, licence matrix, evaluation artefacts, and the full term/mapping tables as additional files.

### A3.5 Four visible author-input markers in the PDF

These are **deliberately visible** (correct practice — never invented, never hidden in comments). They still block submission:

| Line | Section | Marker |
|---|---|---|
| 1,487 | Competing interests | `[AUTHOR INPUT REQUIRED — per-author competing-interests statement missing…]` |
| 1,502 | Funding | `[AUTHOR INPUT REQUIRED — funding statement missing…]` |
| 1,517 | Authors' contributions | `[AUTHOR INPUT REQUIRED — CRediT statement missing…]` |
| 1,535 | Acknowledgements | `[AUTHOR INPUT REQUIRED — acknowledgements missing…]` |

### A3.6 Two unfilled DOI/repository slots

| Line | Slot |
|---|---|
| 1,452 | "…and the benchmark and evaluation artefacts, **DOI [to be added when the deposit is published]**." (Availability section opens at 1,447) |
| 1,454 | "The pipeline code will be released in a public repository with an archived version, **[repository and DOI to be added by the authors]**." (code-repo comment slot at 1,443) |

### A3.7 Source-file hygiene (this file would ship to the publisher)

The journal requires **editable source files**. The current `.tex`:

- **1,683 lines total; 937 comment-only (55.7%), 669 non-empty visible lines.**
- **29 mentions of "Claude"**, 28 of them inside comments (only line 1598 is visible, in the AI-use declaration), including:
  - `%% REVIEW 2026-11-09 (Claude Code fact check; prose not changed)`
  - `%% FRAMING 2026-11-09 (Claude Code; prose not changed)`
  - `%% DRAFT CAPTION, NOT SUBMISSION TEXT (plan §0)`
  - Live `%% >> AUTHOR REWRITE REQUIRED` markers: **12** — lines 101, 218, 349, 375, 756, 954, 997, 1,190, 1,195, 1,279, 1,311, 1,551. (Two further occurrences at 463 and 1,164 are prose *about* the markers, not markers.)
- Internal review notes that **admit unsettled issues**: e.g. line 783 — *"statement must change (H01). The 100-triple check is prepared, not done."* The same unfinished state is visible in the paper itself at 1330 ("the second reviewer's 100-mapping overlap is pending").

Shipping this is a professionalism problem and leaks unresolved concerns to reviewers. **Produce a comment-stripped submission build** and keep the annotated working copy separately.

### A3.8 Internal file name leaked into a published caption

*(Same defect as **B3.7**.)*

Table 1's caption (lines 969–975) names an internal audit artefact:

> "…the last column names the row in the claims register (`MANUSCRIPT_CLAIMS_REGISTER.csv`)…"

Reviewers cannot access that file. Either drop the column, drop the filename, or ship the register as an additional file.

### A3.9 Figure counts and float pressure

- **3 figures** (blocks at 336–368, 741–772, 983–1014; `\includegraphics` at 338, 759, 999) and **1 table** (`table*` at **968–980**, with `\input` of the generated body at 976 and `tablenotes` at 977–979). Counts are within limits.
- **18 pages** for a 4,584-word body including back matter ⇒ whitespace/float pressure (Underfull vbox warnings in `manuscript.log`). Consider merging Fig. 1 (`fig_overview.pdf`) and Fig. 2 (`fig3_cdm_architecture.pdf`), which are conceptually adjacent and both small (405×313 pt, 405×258 pt).
- `Fig/fig_overview_illustrated.pdf` exists but is **unused** — decide or delete before packaging.
- All figures are **vector PDFs with 0 embedded raster images** — good, no DPI problem.

### A3.10 Minor build facts (for completeness)

- 18 pages; **36 `\bibitem` entries in the compiled `.bbl`** (57 `et~al`), **36 distinct keys cited** in the comment-stripped `.tex`. `reference.bib` holds **68 entries**; the **32** that never reach the `.bbl` are precisely the uncited ones — BibTeX emits only cited keys, and the cited-vs-`.bbl` diff is empty in both directions (A7.1).
- 0 undefined citations, 0 undefined references, 0 LaTeX errors, **0 `LaTeX Warning` lines of any kind**.
- The only diagnostics are **1 overfull hbox at 4.85936 pt** and **28 underfull boxes** (3 hbox, 25 vbox) — all cosmetic, none above the 5 pt threshold.

## A4. Data and code availability — the biggest single risk

*Microbiome*'s policy is **strict** and repeated on **every** article-type page:

> "We **require that all datasets on which the conclusions of the paper rely are available to the reviewers at the time of submission** and publicly available at the time of publication."

Current text (Availability section, lines 1447–1460):

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

A grep of visible (non-comment) prose returns **zero** hits for **FAIR**, **MIxS**, **MIMARKS**, **STORMS** and **STREAMS**. Two "fair" hits exist (lines 882, 1,302) but both mean *fair/unfair rating* in the judge rubric, not the FAIR principles — do not let a naive case-insensitive grep fool you into thinking the topic is covered.

This is a serious framing gap: the journal **endorses STORMS**, **expects FAIR**, and the paper is *about* metadata standardisation for microbiome data — yet never names the standards it is implicitly trying to satisfy. An editor reads that as a blind spot. Note also that `wilkinson2016fair` and `yilmaz2011mixs` are **in the bibliography and never cited** (A7).

### A4.5 Licence/copyright statement needs one refinement

Currently: "The underlying source texts are third-party publications and are redistributed only under their own licences… the text of the 179 papers whose licence does not permit redistribution… is withheld."

Good. But it should also state: (a) the **licence of your own deposit** (CC BY 4.0 proposed, pending sign-off), and (b) that **derived annotations** over withheld text (mention offsets, spans, evidence quotes) are also restricted or redacted — the current text implies only the raw text is withheld.

## A5. Scope, article type and novelty positioning

### A5.1 Article type: neither fish nor fowl

The title promises "an LLM-driven common data model **and knowledge extraction pipeline**" — a **Software** or **Methodology** paper. But the manuscript **calls itself a protocol** in **12 occurrences on visible text lines** (21 including the 9 on comment-only lines), including the abstract ("We present a **protocol**…", line 106) and line 288 ("We built Microbiome-CDM as a **protocol** rather than a single model"). The 12 visible occurrences are at lines 104, 106, 132, 235, 288, 297, 331 (the heading `\section{Protocol overview}`), 352 (a figure caption), 495, 703, 832 and 1,447 (the Availability section, "The outputs of this protocol will be deposited").

- **There is no Protocol article type at *Microbiome*.** (There *is* a **Methods and Protocols** type at ***mSystems***, and a **Resource Report** type that fits better still — see [ASM2](#asm2-article-types-at-msystems--and-why-two-of-them-fit-this-paper). This section's verdict is venue-specific, not absolute.)
- As **Software**: criteria require "broad utility" and "direct comparison with available related software". You compare *individual NER models* on BC5CDR/BioRED, but **never compare the pipeline as a whole** to any competing literature-mining system (PubTator3-as-pipeline, SemRep, an existing microbiome KG).
- As **Methodology**: criteria require a "**demonstrable advance**". The Background (lines 228–300) dismisses related work in one paragraph and *asserts* "None of these delivers a provenance-traceable common data model over the cited literature of a compendium" — asserted, not demonstrated.

**This is the single most likely rejection reason.** The predictable editor response: *"What can I do with this that I cannot do with BugSigDB plus PubTator3?"* The manuscript does not answer that with evidence.

### A5.2 The microbiome content is nearly absent

The journal's readers are microbiome scientists. Evidence from the manuscript:

- **No figure shows microbiome data.** No taxonomic composition, no alpha/beta diversity, no differential abundance, no biological result of any kind. The three figures are: pipeline overview, CDM schema architecture, evaluation metrics.
- **No taxon is discussed.** The only organism names in the entire visible body are two incidental italics — *Lactobacillus* (line 626) and *Lactococcus* (line 627) — and they appear **only as a deduplication example** ("they denote the same taxon, so that, for example, *Lactobacillus* and *Lactococcus* remain distinct"), not as biology. Verified zero visible occurrences of Bacteroidetes, Firmicutes, *Faecalibacterium*, *Akkermansia*, *Prevotella*, *Bifidobacterium*, *Escherichia*.
- **The biological payoff is never shown.** You built a CDM over 453 papers and a 168,464-sample compendium and never demonstrate one insight it enables.

For this journal, "technical advance" means *it enables something*. An infrastructure report that never delivers a microbiome result is the archetype of what the editorial calls work that does not provide "substantial conceptual or technical advances".

**This gap is venue-dependent, and that is the single most important finding in this document.** A *mSystems* **Resource Report** explicitly asks for "proof-of-principle so that the new methodology can be replicated and/or utilized by others" — a *reuse path*, not a biological insight. Under that standard, the IBD 25/44 agreement result (Results **1,127–1,129**, currently one sentence and re-cited as a caveat at **1,327–1,330**) plus the released deposit is **sufficient**, and no microbiome figure is required. What remains mandatory at both venues is that the paper shows *someone can use it*. See [ASM2](#asm2-article-types-at-msystems--and-why-two-of-them-fit-this-paper) and [ASM4](#asm4-quantitative-topic-profile--and-the-honest-counter-signal).

### A5.3 The "cited by a compendium" framing is correct but needs an inclusion rule

You correctly separate your corpus from Abdill et al.'s compendium (lines 226–232; "the literature **cited by** a 168,464-sample gut microbiome compendium"). That distinction is essential and well handled. But:

- Your corpus is a **secondary selection** (papers cited by one synthesis). Its completeness relative to the microbiome literature is **undefined**.
- State the **inclusion logic** explicitly: how many cited works existed, how many were retrievable, how many were excluded and why.

### A5.4 No novelty statement

"novel"/"novelty" appears **zero times in visible prose**. The only two occurrences are comments — line 188 ("\"Novel LLMs\": the models are existing open-weight ones…") and line 190 ("The novelty is the protocol that…") — so the word is *deliberately* absent from the paper. That is honest and defensible (you are not claiming novel models), but it leaves a real hole: there is **no paragraph anywhere** stating what is new relative to each named prior system.

This is the one place where the manuscript's caution works against it. Withholding "novel" is correct; failing to state the *delta* is not. Methodology reviewers at this journal expect an explicit "relative to X we add Y" statement (B4.5).

## A6. Evaluation — what reviewers will attack

### A6.1 Human validation: one reviewer, no CI, second reviewer not done

- **One blinded reviewer**, 500 sampled accepted mappings → 61.8% exact, 6.2% wrong.
- **Second-reviewer 100-row overlap "prepared, not done"** (run-source comments at lines 754, 756, 1230) — tracked internally as open item **H01**.
- Limitations states outright: *"no part of this CDM was evaluated against a human-curated ground truth."*
- **No confidence intervals anywhere in the body.** No Wilson intervals, no bootstrap. For 61.8% / 6.2% on n=500, for the 82.9% judge agreement, and for the κ values (0.566, 0.471), this is a methodological hole. Telling: `wilson1927` and `efron1993bootstrap` are **in the bibliography and never cited**.

A reviewer will treat "one reviewer, n=500, no CI" as insufficient to support a claimed quality standard.

### A6.2 "Structural checks pass 118 of 121" is a test suite, not validation

Reporting 118/121 next to benchmark F1 numbers invites conflation of **engineering CI** with **scientific validity**. Keep it, but do not let it sit in the abstract as if it were accuracy.

### A6.3 LLM judges with poor agreement carry most of the quality signal

- DeepSeek-V4-Flash string screen: **730,195 judged items**.
- DeepSeek-V4.1-Flash triple evidence screen: **16,032 triples** against 25,714 licence-screened sentences.
- Two-model adjudication for vocabulary mapping (Gemma, DeepSeek-R1).
- Llama-3.1-8B + Mistral-7B as catalogue judges: **82.9% agreement on 442,772 field verdicts, Cohen's κ = 0.566, Gwet's AC1 = 0.788**; Fleiss' κ over all three judges **0.471** (line 1,049–1,053).

**Correction to earlier drafts of this report:** an older frozen run gave κ = 0.282 (0.293 after re-run, AC1 0.771). Those numbers still sit in the source at comment lines 1,297–1,299 but **do not appear in the visible paper** — the schema-enforced re-run supersedes them. Do not quote 0.282 at a reviewer; quote 0.566/0.471 and be ready to explain that the low-kappa run was the pre-fix one.

The manuscript is **honest** about this — it consistently says "concordance, never accuracy" and names the judge alongside each number. **That is a genuine strength; do not dilute it.** But the honest summary is: most quality numbers come from LLM judges whose inter-judge agreement is poor.

### A6.4 Relation typing has improved — and is still the weakest headline number

*(Framing fix: **B3.4**.)*

The re-typing pass is a real improvement and should be reported as such. Limitations (1290–1296) and Results (1088–1092) now both say the same thing:

- **13,564 of 25,788 triples (52.6%) carry a specific relation whose cue phrase is present in the source sentence** — this supersedes the older `OTHER_RELATION 17,717` figure, which no longer appears anywhere in the file.
- Of the remainder, **8,039 are flagged as not supported by their sentence** (i.e. treated as extraction errors), **1,708 state an association without direction**, and **915 report a null finding**.
- Separately, 16 collection-independent string screens judge only **39.3% of build-3.0.3 triples** to be well-formed claims (38.7% with valid subject and object, line 1087).

So the honest position is no longer "most relations are not relations" — it is **"just over half of the relation triples carry a specific, source-verified relation, and half do not."** That is a legitimate abstention-forward result, but three things follow:

1. **The 47.4% must be accounted for in the paper, not just counted.** The four named buckets — 13,564 specific + 8,039 unsupported + 1,708 undirected + 915 null = **24,226**, which leaves **1,562 triples (6.1%)** in no stated bucket. A reviewer who adds the four numbers will ask what those 1,562 are. Close the set in the text or say explicitly that the buckets overlap/are non-exhaustive.
2. **The abstract still leads with the triple count** (line 114: "an evidence-anchored catalogue and 25,788 relation triples") without carrying the 52.6%. A reader who only reads the abstract infers a relation-extraction result of unstated quality. Add the qualifier, or demote triples.
3. **The re-typing is model output, not validated.** Line 1294–1296 says so explicitly ("Re-typed relations, directions and term types are model output, checked on small constructed test sets but not against human annotation"). Keep that sentence; it is the sentence a reviewer will test you on.

Recommended framing: the contribution is *provenance-preserving extraction with principled abstention*, and the abstention rate is a finding, not a defect. That aligns with the journal's anti-overstatement editorial position and is defensible under review. It still requires the abstract's triple sentence to be rewritten.

### A6.5 Benchmark results belong to other people's systems

*(Framing fix: **B3.3**.)*

The abstract's headline numbers — "best exact F1 **90.1** on BC5CDR, **80.6** on BioRED" — are **PubTator3** and **HunFlair2**. Your best own system scores **69.5 / 66.2** (Qwen3.5-4B, 3-shot).

So the abstract's strongest quantitative claims describe *existing tools you re-measured*. A reviewer reads this as borrowed credibility. The real finding is the one you under-sell: **transfer-domain recognisers beat in-domain prestige** (lines **1,106–1,121**, and the Recommendations at **1,166+**). Lead with that.

### A6.6 Domain-transfer measurement is an under-exploited strength

You ran **27 configurations across 21 systems** on two gold standards, and found organism/disease/gene systems *not* trained on BioRED outperform trained ones. That is a reusable, quotable methodological result for the microbiome field — and it is currently buried in "Recommendations". **Promote it.**

### A6.7 No statistical analysis section

The journal's Methods requirements ask for "the type of statistical analysis used, including a power calculation if appropriate". There is no statistics subsection: no test names, no correction for multiple comparisons, no handling of the many percentages reported. Even for a mostly-descriptive paper, state the descriptive conventions: what a percentage is a percentage *of*, the denominators, and how undefined ratios are treated.

### A6.8 One sentence in Results did not add up (fixed in the working tree)

**Status: applied 2026-11-10 and verified in the rebuilt PDF.** The defect below is recorded because the same class of error — a count that does not partition — recurs elsewhere in the paper and should be re-checked whenever the numbers change.

Lines **1,016–1,023** originally read:

> *"Seventeen entity types are fully populated, fifteen partially, one is planned and five are embedded in other tables' rows"*

The registry the figure is drawn from — `releases/cdm_v3/3.0.3/remediation/UPDATED_ENTITY_REGISTRY_PROPOSAL.csv`, read by `src/scripts/figures/make_bib_extra_figures.py:47` and passed to `fig3()` — holds **33** entities across 10 modules with exactly **three** status values:

| Registry status | Count |
|---|---|
| `POPULATED_EXISTING` | **17** |
| `PARTIAL_POPULATED` | **15** |
| `PLANNED` | **1** |
| **Total** | **33** |

17 + 15 + 1 = 33. The sentence's four groups sum to **38**, because the five "embedded in other tables' rows" entities — `PARAGRAPH`, `SENTENCE`, `MODEL_RUN`, `MENTION_EVIDENCE`, `DEFINITION_EVIDENCE` — all carry `PARTIAL_POPULATED` and are therefore **already inside the fifteen**. The "five embedded" is a *sub-property* of the partial set, not a fourth category. Correct form:

> *"Seventeen entity types are fully populated, fifteen partially (five of them embedded in other tables' rows), and one is planned."*

Two adjacent risks, in opposite directions:

- **Do not "correct" Fig. 2 while fixing this.** The caption's *"33 entity types across 10 modules"* (line **760**) is **right** — it is `len()` of the same 33-row registry. It is *not* the DRAFT 0.1.0 proposal in `docs/cdm_design/cdm_schema.json` (that artefact has 22 tables and the figure never reads it).
- **Do not quote 44 tables / 866 columns at 1,017–1,018 as the 3.1.0 build.** Verified by direct count: 3.0.3 = **44 tables / 866 columns / 8,490,496 rows**; 3.1.0 = **54 tables / 985 columns / 9,084,279 rows**. The text is careful to say 3.0.3 and to add that 3.1.0 "leaves these tables unchanged" — keep that qualifier, because a reviewer who opens the shipped 3.1.0 database and counts tables will otherwise find a 10-table, 119-column, 594k-row discrepancy. **One caveat on that qualifier itself:** comparing the two frozen builds table by table, all 44 tables survive and **42 have identical row counts**, but `cdm_change_log` grows 79 → 88 and `run_metadata` 11 → 14. So the honest wording is "leaves the *entity* tables unchanged and adds ten curated tables", not "leaves these tables unchanged" — the difference is two bookkeeping tables, but it is the kind of thing a referee who downloads the database can check in thirty seconds.

It was a trivial fix with disproportionate cost: a self-inconsistent count in the first Results paragraph invites a reviewer to distrust every other number in the paper, and the numbers *are* the contribution.

## A7. References

### A7.1 32 of 68 bibliography entries are never cited (47%)

`reference.bib` has **68 entries**; **36 keys** are cited and all 36 resolve — `manuscript.bbl` contains exactly **36 `\bibitem`** entries and the pairwise diff is empty in both directions (0 cited-but-missing, 0 present-but-uncited). Measuring by hand with a regex over the raw `.bib` undercounts, so treat 36/32 as the verified pair and the earlier 34/33/35 numbers as superseded.

Uncited entries:
`abdin2024phi3`, `akbik2019flair`, `beltagy2019scibert`, `brown2015gene`, `cohen2017craft`, `collins2026biotriplex`, `cote2006ols`, `deepseek2026v4`, `deepseekv4flashcard`, `efron1993bootstrap`, `gargano2024hpo`, `karkera2023microbiomere`, `kim2004jnlpba`, `lee2019biobert`, `leinonen2011`, `li2025lore`, `liu2019sbert`, `liu2021sapbert`, `luoma2023s1000`, `medjudge2026`, `microbiorel2025`, `minilmcard`, `neumann2019scispacy`, `ollama2026`, `pyysalo2015bionlp13`, `qi2023gutmdisorder`, `vasilevsky2022mondo`, `wilkinson2016fair`, `wilson1927`, `yazdani2026glinerbiomed`, `yilmaz2011mixs`, `zaratiana2024gliner`.

### A7.2 Several of those *must* be cited

| Uncited key | Why it must be cited |
|---|---|
| `liu2021sapbert` | **SapBERT is named 4 times in visible prose** — lines 621, 1,006, 1,127, 1,594 — and **never once cited**. It drives the merge-adjudication rule, so it is load-bearing |
| `liu2019sbert` | **MiniLM is named twice** — lines 622, 1,594 — also never cited |
| `zaratiana2024gliner` | GLiNER is cited at 1,080, but only via `zaratiana2025gliner2` (the v2 checkpoint paper). The original GLiNER method is uncited |
| `lee2019biobert` | **BioBERT appears by name** at line 1,078 with no citation |
| `neumann2019scispacy`, `beltagy2019scibert`, `akbik2019flair` | The three model families behind the ensemble. Note honestly: **"sciSpaCy", "SciBERT" and "Flair" never appear in visible prose** — only the concrete checkpoints (HunFlair2, BioBERT-diseases) do. So these are *optional* citations that would strengthen Methods, not compliance failures |
| `wilkinson2016fair` | FAIR — the journal explicitly expects FAIR compliance, and the acronym appears **0 times** in the manuscript (the two "fair" hits at 882 and 1,302 mean "fair/unfair rating", not the principles). This is a *positioning* gap as much as a citation gap (A4.4) |
| `yilmaz2011mixs` | MIxS — **0 occurrences** in the manuscript. The standard metadata schema the paper is about is never named (A4.4) |
| `wilson1927`, `efron1993bootstrap` | No CIs are reported anywhere; these are the methods you should be using |

**General rule being broken:** every named tool/model/standard must be cited **at first use in the body**. This one *is* broken — SapBERT (4 mentions), MiniLM (2) and BioBERT (1) are named and uncited, and SapBERT in particular carries the merge logic.

**But do not overstate it.** A full audit of visible prose shows that the manuscript is *narrower* than the pipeline actually is: **tmChem, TaggerOne, DNorm, GNormPlus, Ab3P, SciBERT, sciSpaCy, Flair and Ollama occur zero times**. The Java tools in `src/cdm_pipeline/ner/java_tools.py` and the spaCy models are real components that the text does not name. That cuts both ways: no citation debt on those names, but also **no visible evidence of the eight-program ensemble** that the manuscript claims. If you name them (recommended — it is a real strength), you incur the citation debt at the same time.

### A7.3 Reference count is very low for this venue

**36 cited references** is low for a methodology paper at *Microbiome*; comparable accepted methodology/software papers typically cite **60–120**. The **32 uncited entries** are already sitting in the bibliography, so raising the count costs no new literature search. Wiring them in — plus the standards and the competitors in Part B — is the cheapest credibility gain available.

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
| Word count | **334 incl. the three bold labels / 331 excl.** (≤350 ✓, 16–19 to spare) |
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
7. **Build integrity.** Clean from-scratch `latexmk` build: 18 pages, 0 undefined citations, 0 undefined references, 0 errors, 0 warnings, one 4.86 pt overfull hbox and 28 underfull boxes. Nothing exceeds 5 pt.

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
- **It has no Methodology article type.** The verifiable type list is **Research article, Database article, Software article, Review, Matters Arising, Comment** (BMC Microbiology submission guidelines, checked 2026-11-10). "Methodology" is a *Microbiome* type, not a BMC one. So the paper must go as **Research**, **Database**, or **Software** — and each of those carries criteria the manuscript does not currently meet:
  - **Database article** requires a **"Utility and discussion"** section that **compares the resource against similar existing databases**, plus an optional case study. The manuscript has no such section and no such comparison (B3.2, B2.5).
  - **Software article** requires broad utility, "usually demonstrated by direct comparison with available related software", reviewer-anonymous access to the tool, and an archive copy deposited in a permanent repository.
  - **Research article** criteria do allow "a new experimental or computational method", but they explicitly **exclude non-commissioned pooled analyses and bibliometric analyses** — a risk here, since a reviewer may read the 453-paper census as bibliometric.
- APC **£2,390 / $3,090 / €2,690** — the cheapest of the three venues by a wide margin (about 47% of the *Microbiome* APC).

### Conclusion

**Neither *Microbiome* nor BMC Microbiology currently sees a paper that fits cleanly, because the manuscript is framed as NLP engineering with a microbiome corpus rather than as a microbiome resource with NLP underneath** — and because it does not cite the field it claims to advance. That is a *framing* failure and it is fixable, but it requires rewriting the Background, the title, the abstract's payoff sentence, and the related-work section — not just adding sections.

**But a third venue removes most of the framing problem without any rewriting.** *mSystems* has a **Resource Report** article type that describes this paper as it stands, a 5,000-word cap the manuscript already meets, and published precedents of exactly this shape — including a *metadata schema paper with no primary data* ([ASM3](#asm3-do-comparable-papers-actually-get-published-here)). The framing failure documented throughout this part is, in large measure, a **venue** failure. See [Part A2](#part-a2--alternative-venues-the-asm-journals).

**Recommended path, in order of preference:**

1. **If the authors will add the biological demonstration** (one reuse figure, IBD promoted, second reviewer) → **rewrite to Methodology framing** as described in Part B and submit to ***Microbiome***. Highest ceiling.
2. **If they will not** → submit the paper substantially as it stands to ***mSystems*** as a **Resource Report**, after the venue-independent fixes (deposit, availability, competitor citations, Importance paragraph, abstract trim). The biological demonstration is optional for that article type; a demonstrated reuse path is not.
3. **BMC Microbiology** remains a defensible fallback, and is the most likely of the three to accept the current framing — at the lowest signalling value.

What is *not* recommended is submitting the current manuscript to *Microbiome* unrevised. On the evidence in Parts A and B it would be rejected on framing grounds alone, before the science is reached.

---

# PART A2 — ALTERNATIVE VENUES: THE ASM JOURNALS

This part answers a different question from Part A: not "does it fit *Microbiome*" but "is there a journal where this paper's *current shape* is a recognised article type". The answer is yes — **mSystems** — and that changes the cost calculus enough to justify the extra length.

Evidence grade is stated for every claim below, because ASM's site (`journals.asm.org`) returns HTTP 403 to direct fetch and to `r.jina.ai` proxying (Cloudflare bot check). ASM facts therefore come from search-engine excerpts of ASM's own pages, not from a full page read. Where a detail could not be pinned down I say so rather than filling the gap.

## ASM1. Hard facts about *mSystems* (ISSN 2379-5077)

| Property | Value | Confidence |
|---|---|---|
| Publisher / model | ASM; fully open access | High |
| Licence | **CC BY 4.0**; authors retain copyright | High (ASM proprietary-rights page) |
| APC | **$3,375 member / $4,500 non-member** (mBio, mSphere, mSystems share this row) | High (ASM publication-fees page) |
| Short-article APC | $1,950 / $2,600 (Brief Reports, Opinions & Hypotheses) | High |
| Initial submission format | **Format-neutral** — "ASM Journals welcomes papers in any format" | High (ASM format-neutral page) |
| Peer review | Single-blind by default; **open peer review optional** (reports published with the article if the author opts in) | High |
| Corpus size (PubMed) | **3,071** papers total; **444** in 2025, **354** in 2026 | High (E-utilities, 2026-11-10) |
| Research Article word limit | **5,000 words**, excluding references, tables and figure legends | High |
| Abstract convention | **250 words**, plus a separate non-technical **Importance** paragraph of **≤150 words** | **High** — stated on the *mSystems* article-types page. **Correction:** earlier drafts of this report said 120 words; 120 is the *J. Bacteriology* limit. mSystems allows 150 |
| Title page | Title, **running title ≤ 54 characters incl. spaces**, all authors, affiliations at time of work, corresponding e-mail(s), **abstract word count** | **High** (mSystems article-types page) |
| Section order | Abstract → Importance → Introduction → Results → Discussion → **Materials and Methods** → Acknowledgments → Author Contributions → References | Medium — Methods *after* Discussion is ASM convention and appears in third-party submission checklists; not verified against a live ASM page |
| LaTeX | ASM supplies an **Overleaf template for mSystems Research Articles** | Medium-high (referenced on the mSystems article-types page) |

### ASM2. Article types at *mSystems* — and why two of them fit this paper

Article types recorded for *mSystems*: **Research Article**, **Resource Report**, **Methods and Protocols**, Observation, Minireview, Opinion/Hypothesis, Commentary, Perspective.

Two matter here.

**Resource Reports** — the journal's own description: *"Resource Reports describe major technical advances and/or major informational databases that would be of interest in microbiology or allied fields. The manuscripts should include detailed methods and illustration of proof-of-principle so that the new methodology can be replicated and/or utilized by others."*

Read that against what the manuscript actually is: a database-shaped artefact (2,505,735 mentions, 165,991 canonical terms, 334,231 mappings, a released CDM bundle) with a documented method and a released deposit. **"Proof-of-principle so that others can replicate or utilise it" is a materially lower bar than *Microbiome*'s "demonstrable advance"**, and it is the exact standard the paper can already meet. The missing element at *Microbiome* — a microbiome *insight* — is not required here; a demonstrated *reuse path* is.

**Methods and Protocols** — the paper's own preferred self-description ("we present a protocol that constructs…") turns out to name a real article type at this journal. That is worth pausing on: the single most-repeated framing defect at *Microbiome* (A5.1, B3.1 — "protocol" used 12 times in visible text with no article type behind it) **disappears entirely at mSystems**. The word does not have to be scrubbed from the manuscript; it has to be aimed at the right article type.

**Recommendation: Resource Report**, not Methods and Protocols. The contribution is an information resource with a method attached, not a bench/wet-lab protocol. Methods and Protocols would invite "this is not a protocol" from a reviewer who expects step-by-step laboratory procedures.

### ASM3. Do comparable papers actually get published here?

This is the question that decides fit, and the answer is unusually clean: yes, repeatedly, and one precedent is almost a template.

| Precedent | Year | Why it matters |
|---|---|---|
| **PaperBLAST: Text Mining Papers for Information about Homologs** | 2017 | The closest structural analogue in existence: a **literature text-mining database** published as an mSystems resource. Establishes that "we mined the literature and built a queryable resource" is inside scope, without any new microbiology |
| **A Schema for Digitized Surface Swab Site Metadata in Open-Source DNA Sequence Databases** | 2023 | **A metadata schema paper** — no experiments, no new biology, purely an argument that a free-text field should be replaced by structured, digitised metadata. This is the nearest possible neighbour to "microbiome attributes survive only in prose; here is a data model for them" |
| **Microbiome Metadata Standards: Report of the National Microbiome Data Collaborative's Workshop** | 2021 | Confirms ASM will publish microbiome-metadata-standardisation work with zero primary data |
| **E.PathDash**, pathway activation analysis of public pathogen expression data | 2024 | Reuse of public data as a first-class contribution |
| **Semantic search using protein large language models…** | 2024 | An **LLM-method** paper in mSystems — the journal is not LLM-averse |
| **NIAID systems-biology data resource / schema papers** (several) | 2020–2025 | A standing line of data-resource publishing |

The swab-metadata paper is the strongest single argument in this entire document for a venue change: it is the same paper shape, at the same journal, with no biological finding, and it was published.

### ASM4. Quantitative topic profile — and the honest counter-signal

PubMed counts, all years, journal-limited (`2379-5077[ta]`):

| Query | Papers |
|---|---|
| semantic / ontology / data model (tiab) | **18** |
| curation / harmonisation / interoperability / metadata standard (tiab) | **25** |
| metadata / schema / standard / controlled vocabulary (title) | **7** |
| resource / database / platform / toolkit / repository (title) | **31** |
| software / database / tool / pipeline (any) | **71** |
| multi-omics | **160** |
| benchmark | **8** |
| **text-mining / NER / NLP** | **1** (PaperBLAST, 2017) |
| LLM anywhere in abstract | **4** |
| "knowledge graph" / "ontology" in title | **0** |

Two readings, both true:

- **Supportive:** 71 software/database/pipeline-titled papers and 31 resource-titled papers is a real, sustained publishing line. The paper would not be a curiosity.
- **Adversarial:** the text-mining cell is **1** paper in nine years, and knowledge-graph-in-title is **0**. mSystems is a *systems biology* journal that publishes data resources; it is not a text-mining journal. A reviewer pool drawn from systems microbiologists will ask the same question *Microbiome*'s reviewers would ask — *what does this tell me about microbes?* — and will be **less** familiar with the NER/relation-extraction literature than *Microbiome*'s would be.

**Net:** mSystems lowers the *article-type* bar and does not lower the *demonstration* bar by much. It converts "you must show a biological insight" into "you must show that the resource is usable by others" — which the IBD 25/44 reuse result and the released deposit already do, once promoted out of Limitations (C2:17).

### ASM5. What the manuscript would have to change — and what it would not

| Requirement | Current manuscript | Delta |
|---|---|---|
| 5,000-word body | **3,911 words** excluding back matter, tables and figure legends (4,584 including back matter) | **Already compliant**, with ~1,100 words of headroom — enough for the capability matrix, related-work rewrite and IBD promotion, and *still* under the cap |
| Abstract ≤ 250 words | **334 incl. the three labels / 331 excl.** by a comments-stripped, LaTeX-command-stripped count | **Trim 81–84 words**, plus a new ≤150-word Importance paragraph. The trim is cheap; the Importance paragraph is the real work |
| Separate **Importance** paragraph ≤ 150 words | Does not exist | **Write ~110–140 words of plain-language significance.** New work, but it is exactly the paragraph B4.3 already asks for |
| Abstract word count on the title page | Absent | Add one number |
| Running title ≤ 54 characters | No running title | Add |
| Numbered references in citation order | `sn-vancouver-num` already does this | **Already compliant** — the reference work survives the venue change |
| Methods **after** Discussion | Materials and methods currently precede Results | Reorder (see conflict below) |
| Data deposited in a public repository, available at review | Nothing uploaded; future tense | **No improvement.** ASM is as strict as *Microbiome* here. This is venue-independent and remains Tier 0 |
| CC BY 4.0 | CC BY proposed in Declarations | Already aligned |
| Author Contributions / Acknowledgments as unnumbered end sections | Currently BMC/Springer Declarations machinery | Rework the back matter — one pass |
| No formal "Declarations / Ethics / Consent / Abbreviations" block | Present | **Delete or fold.** ASM does not use the BMC declarations apparatus |
| "16S" → "16S rRNA gene" | 3 bare occurrences | Do it anyway. *Microbiome*'s rule is explicit; ASM's is not verified, and correct usage is harmless at either venue |

**The one real structural conflict.** ASM puts Materials and Methods *after* Discussion; the Tier 0 restructure planned for *Microbiome* (C2:6–8) puts Methods before Results and adds a separate Conclusions. These are not the same edit. Deciding the venue **before** writing the restructure — which is what Part 0 already says — saves doing it twice.

**The cost that is easy to underrate.** The `sn-jnl` v3.1 conversion (preamble, structured abstract, declaration ordering, `sn-vancouver-num`, the whole `latexmk` path validated at 18 pages / 0 errors) is Springer-specific. Moving to ASM means switching to the ASM Overleaf template and re-doing front matter, back matter and declaration handling. That is a day, not a week — but it is wasted if the venue is chosen after the restructure rather than before.

### ASM6. The other ASM journals — where this paper would and would not go

| Journal | ISSN | Papers | 2026 | Best article type for this paper | Verdict |
|---|---|---|---|---|---|
| **mSystems** | 2379-5077 | 3,071 | 354 | **Resource Report** | **Best ASM fit** |
| mSphere | 2379-5042 | 3,238 | 233 | Resource Report, Observation | Same article types, **narrower scope** (host–microbe and eukaryotic microbes), no better precedent. No reason to prefer it |
| **Microbiology Spectrum** | 2165-0497 | **10,103** | **1,689** | Research Article / Resource | Highest volume of the group (≈2.8× mSystems' 2026 output) and a broader scope, but scope breadth cuts both ways: it is the group's catch-all, so per-paper visibility and selectivity signalling are lower. APC band lower than mSystems per ASM's fee table (exact figures for this row could not be resolved from the fetched table — **verify before quoting**) |
| mBio | 2150-7511 | 9,105 | — | Research Article only | **Not suitable.** No resource/protocol article type; expects mechanistic microbiology |
| ASM S2O journals (J Bacteriol, Appl Environ Microbiol, J Clin Microbiol, …) | — | — | — | Research Article | **Not suitable.** **No APC**, but subscription/S2O model means no CC BY open access by default, and all are mechanism- or method-in-laboratory oriented |

**If ASM is chosen, submit to mSystems.** Not mSphere (same types, smaller and more narrowly scoped audience), not Spectrum (volume without selectivity), not mBio (no article type for this shape).

### ASM7. Five-venue verdict ranking

Scores are comparative within this paper only, not journal quality.

| Rank | Venue | Article type | Formal fit | Precedent | Audience | Cost | Honest odds |
|---|---|---|---|---|---|---|---|
| **1** | ***mSystems*** | Resource Report | **Best** — article type describes the paper as written; 5,000-word cap already met; format-neutral first submission | **Strong** (PaperBLAST, swab schema, NMDC standards) | Systems microbiologists | APC **$4,500** non-member | **Best available.** Still needs availability + reuse promotion + Importance paragraph. Not a desk-reject risk on shape |
| **2** | ***Microbiome*** | Methodology | Good — type exists, criteria are "demonstrable advance", which the paper does not yet show | Thin (2 text-mining titles in 2,491) | Microbiome scientists, competitors as reviewers | APC **$5,190 / €4,290** | Credible **only** after the biological demonstration. Highest ceiling, highest bar |
| **3** | **BMC Microbiology** | Research / Database / Software (**no Methodology type**) | Good — widest ontology/KG precedent (**60** titles vs 13) | Strongest on topic | Mixed microbiology | APC **£2,390 / $3,090 / €2,690** | **Most likely acceptance** of the five, lowest signalling. The honest fallback |
| 4 | mSphere | Resource Report | Good | Weaker for this paper | Host–microbe focus | $4,500 | No advantage over mSystems |
| 5 | Microbiology Spectrum | Research Article | Moderate | Broad | Very broad | Lower | Volume without selectivity; no upside |

**The decision in one line:** *mSystems* is where the paper as it exists today is closest to publishable; *Microbiome* is where it would matter most if the biological demonstration is added; BMC Microbiology is where it is most likely to be accepted as-is.

### ASM8. What this changes in the rest of this document

- **C2:1 (decide the venue)** now has three real options, not two, and the choice is no longer "prestige vs fit" — it is "which bar do you intend to clear".
- **C2:2 (article type)** — "protocol" is not a defect at mSystems if the article type is **Methods and Protocols**, and not a defect at all under Resource Report. The scrub is still worth doing, because the word appears **12 times in visible text** (lines 104, 106, 132, 235, 288, 297, 331, 352, 495, 703, 832, 1,447) where "pipeline" or "resource" is meant, but it is no longer a desk-reject.
- **C2:6–9 (restructure)** — the target architecture is **venue-dependent**. Write it once, after the decision.
- **A4 / C2:4–5 (availability, deposit, DOI)** — unchanged and equally blocking at every venue considered. This is the one Tier 0 item that buys value regardless of where the paper goes.
- **A8.2 / C2:13 (abstract)** — at mSystems the abstract must come down from **331 words (excl. labels) to ≤250** *and* gain a ≤150-word Importance paragraph; at *Microbiome* the current 331-word structured abstract is already compliant (19 words to spare under the 350 cap).
- **B2.1 / B2.2 (uncited competitors, unclaimed standards)** — unchanged. mSystems reviewers will be *less* likely to know MINERVA and MicrobiomeKG, which lowers the risk of being caught but does not make the missing citations defensible. Cite them regardless.

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

**The phrase "knowledge graph" appears once in a ~4,100-word paper about building a graph.** That alone signals the paper is not in conversation with its own field.

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
- **The IBD use case is reported in one sentence and then retracted.** Results line **1,127–1,129** reads: *"An exploratory genus-by-condition consensus check agrees in 25 of 44 comparable cells."* Limitations line **1,327–1,330** then reads: *"the IBD use case (one exploratory case study; the register records only that 25 of 44 genus-by-condition cells agree with independent BugSigDB consensus) does not establish clinical validity."* So the analysis is not missing — it is present, unnamed, unillustrated and immediately disowned.

So you *ran* a genus-by-condition consensus analysis, got **25/44 cells agreeing with independent BugSigDB curation**, and reported it **only in Limitations as a thing that does not establish clinical validity.**

That is a result. It is small, but it is the *only* place in the manuscript where the CDM produces a microbiome-facing finding, and it is buried in the section that says what is wrong with the paper. **Promote it.** MicrobiomeKG published on the strength of three case studies at 1/18th your scale. MINERVA published on a KG plus a viewer.

### B2.5 Missing whole-pipeline comparison

You compare 27 NER configurations on BC5CDR/BioRED. You **never** compare Microbiome-CDM-as-a-system against MINERVA, MicrobiomeKG, PubTator3-as-pipeline, or BugSigDB as an alternative route to the same goal. The **Software** article type at *Microbiome* explicitly requires "direct comparison with available related software."

### B2.6 Missing human evaluation and statistics

- One blinded reviewer, n=500, **61.8% exact / 6.2% wrong**, **no confidence intervals**.
- Second-reviewer 100-row overlap "prepared, not done" (open item **H01**).
- LLM-judge inter-agreement: 82.9% raw agreement, but Cohen's κ = **0.566** and Fleiss' κ = **0.471** — only moderate. The raw percentage flatters the judges; the κ is the number to quote.
- No test names, no multiple-comparison policy, no bootstrap. (`wilson1927`, `efron1993bootstrap` are in the `.bib`, uncited.)

DiMB-RE reported IAA against a gold corpus. Ikeda reported against a gold standard. You report against a single reviewer with no CI. **This is the difference reviewers will name.**

### B2.7 Missing a novelty paragraph

`novel`/`novelty` appears **zero times in visible prose** across 1,683 lines; the only two occurrences (lines 188, 190) are inside a comment block that says so. There is no paragraph saying what is new relative to each named prior system. At a journal whose editorial demands a "substantial conceptual or technical advance", the absence is conspicuous.

### B2.8 Missing the community/sustainability story

MINERVA has a viewer. MicrobiomeKG is in Translator. MicrobiomeKG explicitly says it "is designed to supplement (and be integrated with) such existing knowledge bases, not to replace them." You say nothing about how yours is used, updated, or integrated. A reviewer asks: *is this a one-shot artefact that will die on the author's disk?* Nothing in the manuscript answers that.

## B3. What you are framing incorrectly

### B3.1 "Protocol" — an article type that does not exist *(at *Microbiome*)*

*(Article-type criteria: **A5.1**. Venue alternative: **[ASM2](#asm2-article-types-at-msystems--and-why-two-of-them-fit-this-paper)**.)*

The manuscript calls itself a **protocol** in **12 occurrences on visible text lines** (lines 104, 106, 132, 235, 288, 297, 331, 352, 495, 703, 832, 1,447 — 21 occurrences if the 9 comment-only lines are counted), including the abstract ("We present a protocol that constructs a…", line 106) and line 288 ("We built Microbiome-CDM as a protocol rather than a single model").

*Microbiome* has **no Protocol article type**. Its types are Research, Methodology, Software, Review, Brief report, Comment, Correspondence, Meeting Report. ***mSystems* does have a "Methods and Protocols" type — so this defect is specific to the *Microbiome* path, not intrinsic to the paper.**

You are describing a **Methodology** paper using a word that maps to no category at this journal. Every time a reviewer reads "protocol" they hear "we have not implemented this / this is a plan", which is the opposite of what a Methods paper must convey.

**If *Microbiome* or BMC: decide Methodology or Software, then replace "protocol" throughout** with "pipeline" (Software) or "method" (Methodology). Do not mix. **If *mSystems*:** submit as a **Resource Report** and still replace "protocol" — the article type is not a protocol, and the word invites the same misreading from an ASM reviewer. The fix is cheap at any venue; only its *severity* changes.

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

### B3.4 The triples are framed as a contribution while half of them carry no specific relation

*(The evaluation-side view is **A6.4**.)*

- 25,788 triples; **13,564 (52.6%) carry a specific relation with a source-verified cue phrase** (line 1,089, repeated at 1,291).
- **8,039 are flagged as unsupported by their sentence**, **1,708 are undirected** and **915 report a null finding** (1090–1092).
- A collection-independent string screen judges **39.3%** of the older build-3.0.3 triples to be well-formed claims (1087); that screen predates the re-typing.

So **47.4% of triples still state no specific relation** — better than the previous draft, but the abstract and Results still sell triples without the qualifier.

**Only one framing survives review:** make **principled abstention** the finding. "We extract 25,788 provenance-anchored candidate assertions and type just over half of them, because the source sentence often does not state a specific relation. Systems that force a label here are manufacturing signal." That is a real, defensible, and *editorially popular* position — the journal's own editorial warns against overstatement. Presenting the abstained half as relations delivered gets you rejected at review.

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

# PART C — PER-VENUE ACTION LISTS

This is the operative section. Everything above establishes *what is wrong and why*; this is *what to do, at which journal*, in the shape of **missing / rephrase / remove**. Each item carries a line number or a count from `manuscript.tex` (1,683 lines) so it can be checked and ticked off.

**Conventions used throughout this part**

- Line numbers are `manuscript.tex` line numbers for the **1,683-line / 107,887-byte** working copy on branch `submission-prep-2026-11-10` (last commit `1d2315b`, with the re-typed results and the SN-conversion still uncommitted). Re-grep before editing: the file is 57 lines longer than the `b804f97` snapshot these anchors were first taken from.
- "Visible" means a line that is not comment-only. The file has **937 comment-only lines** (55.7% of 1,683; 669 non-empty visible lines remain); those never reach the PDF and are treated separately.
- Word counts use the convention declared in A3.2 (comments stripped, floats removed as whole blocks, commands and cite/ref/label arguments stripped, whitespace tokens containing an alphanumeric character).
- Where an item appears at more than one venue, it is listed under each venue with its venue-specific wording, rather than cross-referenced — so each list can be worked top-to-bottom alone.

---

## C-1. Venue 1 — *Microbiome* (Springer Nature, ISSN 2049-2618)

**Article type to select: Methodology** (fallback: Software). This decision gates the section structure, so make it first.

### C-1.1 Missing at *Microbiome*

| # | Missing item | Evidence / where |
|---|---|---|
| M1 | `\section{Methods}` — the five stage sections are unlabelled and top-level | Stage headings at **406, 460, 538, 679, 774** are all `\section{Stage n: …}`; there is no `\section{Methods}` anywhere in the file |
| M2 | `\section{Discussion}` | Zero occurrences of a Discussion heading in the file; `\section{Results}` (**920**) is followed directly by `\section{Recommendations}` (**1166**), then `\section{Limitations}` (**1251**) |
| M3 | `\section{Conclusions}` | The only "Conclusions" is the abstract heading at line 132 |
| M4 | A **reuse demonstration that is framed and evidenced as one** | It is *present* in Results at **1,127–1,129** ("An exploratory genus-by-condition consensus check agrees in 25 of 44 comparable cells") but as a single closing sentence with no denominator beyond the 44, no figure, no table, no confidence interval, and no "IBD" label — the word IBD appears in that paragraph only as the comparison standard. It is then re-cited in Limitations at **1,327–1,330** as a reason the paper has no clinical validity. Promote it: name it as the IBD case study, show the 44 cells, and stop apologising for it |
| M5 | **Confidence intervals** on the headline proportions | 61.8% and 6.2% (both line 120), the 82.9% judge agreement and κ = 0.566/0.471 (lines **1,050–1,053**) are all point estimates with no CI |
| M6 | **Second reviewer** on the 100-mapping overlap (H01) | Abstract line 121 says "a blinded human review of 500 randomly sampled accepted vocabulary mappings" — single reviewer |
| M7 | A **capability comparison table** against competing systems | No table compares Microbiome-CDM to MINERVA, MicrobiomeKG, KG-Microbe, SemRep, PubTator3-as-pipeline |
| M8 | **SSSOM / KGX-Biolink / RDF export** statements | Body grep for `SSSOM`, `Biolink`, `KGX`, `RDF` = **0 occurrences**, though the exporters exist in `src/cdm_pipeline/export/` |
| M9 | **FAIR + MIxS/MIMARKS + STORMS/STREAMS** engagement | Body grep for all five = **0 occurrences** |
| M10 | **Novelty paragraph** naming each competitor and the added delta | No such paragraph in Background (lines 160–328) |
| M11 | The **corpus inclusion rule** (cited → retrievable → included/excluded why) | Lines 228–300 describe the 453-paper set but never state how many works the compendium cited in total or why any were excluded |
| M12 | **"Authors' information"** back-matter section (in the `sn-jnl` template; *not* in BMC's own mandatory list) | Back matter at 1,358–1,545 (`\bmhead` blocks at 1,392, 1,398, 1,401, 1,476, 1,493, 1,507, 1,526, 1,539) has Ethics, Consent, Availability, Competing interests, Funding, CRediT, Acknowledgements, AI declaration — **no Authors' information** section (0 occurrences). Low-risk omission; add only if the venue asks, and only with author-supplied content |
| M13 | **Endnotes** section (listed among mandatory Declarations) | Not present in the back matter |
| M14 | **Line numbers + double spacing** in the submission build | `\documentclass[pdflatex,sn-vancouver-num]` at line 23; the `referee,lineno` variant is described in a comment at line 25 but not enabled |
| M15 | **Emails for all authors**, not only the corresponding author | Author block at lines 66–100; affiliation street/postcode incomplete |
| M16 | An **"Additional files"** list | Not present; needed for the paper list, licence matrix and hashes |
| M17 | **A biological figure** | 3 figures total (336–368, 741–772, 983–1014); all pipeline/architecture/evaluation, none microbiome content |

### C-1.2 Rephrase at *Microbiome*

| # | Rephrase | From → to | Evidence |
|---|---|---|---|
| R1 | Self-description | "protocol" → "pipeline" (Software) or "method" (Methodology) — **pick one and use it consistently** | 12 visible occurrences: lines 104, 106, 132, 235, 288, 297, 331 (heading), 352 (caption), 495, 703, 832, 1,447 |
| R2 | Abstract opening | "We present a protocol that constructs a provenance-traceable common data model" → state the resource and the demonstrable advance | Line 106 |
| R3 | Abstract Conclusions | "A multi-program extraction protocol can turn a literature corpus…" → "A multi-program extraction **method**…" | Line 130 |
| R4 | Abstract payoff | The 90.1 / 80.6 F1 figures are PubTator3's and HunFlair2's, not this pipeline's — attribute them in-line or drop them from the headline | Lines 119–124 |
| R5 | Triple framing | 13,564 of 25,788 triples (52.6%) are specifically typed; the other 47.4% carry no specific relation. Present as **principled abstention**, not as relations delivered | Line 114 ("25,788 relation triples"); caveat at 1290–1296 |
| R6 | "16S" | **"16S" → "16S rRNA gene"** (explicit journal rule) | Lines 843, 1,061, 1,125 — three bare occurrences, all visible |
| R7 | Section heading | `\section{Protocol overview}` → `\section{Methods overview}` or fold into Methods | Line **331** |
| R8 | Figure 1 caption | "Protocol overview. Five stages build the common data model" → "Pipeline overview…" | Line 352 (the `\caption{` line; the `Protocol overview` text runs 352–357) |
| R9 | Title | Current 113-character title promises a pipeline; retarget toward the indexed concept (common data model / metadata harmonisation) | Line 66 |
| R10 | Benchmark framing | Reframe the BC5CDR/BioRED result as *transfer measurement*, which is the actual novel contribution (Spearman 0.749 diseases vs 0.023 organisms), rather than as benchmark performance | Lines 119–123 |
| R11 | Data availability | Future tense → present tense with live DOI | Lines **1,447–1,454**: "will be deposited" (1,447), "DOI [to be added when the deposit is published]" (1,452–1,453), "[repository and DOI to be added by the authors]" (1,454) |
| R12 | 453 vs 452 | State the analysis universe once and use one number | Lines 109, 352, 436, 1403 all say 453; a 452-paper body universe exists (HMPAPER_000372 excluded) and `HMPAPER_000372` never appears in the text |

### C-1.3 Remove at *Microbiome*

| # | Remove | Evidence |
|---|---|---|
| X1 | The internal claims-register filename from the published Table 1 caption | Lines **969–975**: "\dots the row in the claims register (`MANUSCRIPT\_CLAIMS\_REGISTER.csv`) that each value was verified against" |
| X2 | The same filename from the table note | Line 978: "Register: final\_validation/MANUSCRIPT\_CLAIMS\_REGISTER.csv" |
| X3 | The **4 visible** `[AUTHOR INPUT REQUIRED]` blocks once authors supply the text | Lines 1,487, 1,502, 1,517, 1,535 |
| X4 | The **2 unfilled DOI/repository slots** once deposits exist | Lines 1,452 ("DOI [to be added…]") and 1,454 ("[repository and DOI to be added by the authors]"); code repository also unset at 1,443 |
| X5 | The **937 comment-only lines** (55.7% of the file) from the submitted `.tex` | Comment-only lines pass the 937-line census; publisher receives source at submission |
| X6 | The internal engineering vocabulary in headings and prose | "Stage 1…Stage 5" (**406, 460, 538, 679, 774**) and "guarded normalisation", "evidence-anchored" read as build notes |
| X7 | The unused figure asset decision | `Fig/fig_overview_illustrated.pdf` exists and is unreferenced |
| X8 | **28 of 29 "Claude" mentions** — keep only the AI-use declaration | 29 raw occurrences in the file, **1 visible** (line **1,598**, the generative-AI declaration — keep that one); the other 28 are comment-only lines |

### C-1.4 Net position at *Microbiome*

Mechanically submittable after C-1.3 and R1/R6 alone; **competitive only after C-1.1 M4–M7 and M17**. The gate is "a demonstrable advance", and the paper's strongest demonstrable advance — the transfer-domain finding — is currently buried in Recommendations and the Limitations section. Highest ceiling of the three venues, lowest probability of acceptance on the current text.

---

## C-2. Venue 2 — *mSystems* (ASM, ISSN 2379-5077)

**Article type to select: Resource Report.** Not Methods and Protocols — the contribution is an information resource with a method attached, and "Methods and Protocols" invites "this is not a protocol" from a reviewer expecting bench procedures.

### C-2.1 Missing at *mSystems*

| # | Missing item | Evidence / where |
|---|---|---|
| A1 | A separate **Importance** paragraph, **≤150 words** (not 120 — 120 is the *J. Bacteriology* limit) | No Importance section exists anywhere in the file |
| A2 | **Abstract trimmed to ≤250 words** | Currently **334** words including the three `\textbf{Background:/Results:/Conclusions:}` labels, **331** excluding them. **Trim 81–84 words** |
| A3 | **Abstract word count** stated on the title page | Absent |
| A4 | **Running title** convention confirmed for the ASM template | A 47-character short title *does* exist (`\title[…]` at line 66: "Microbiome-CDM: an LLM-driven common data model") — within the ≤54-character limit, so **compliant but currently invisible to the reader** |
| A5 | **Author Contributions** and **Acknowledgments** as unnumbered ASM end sections | Currently BMC `\bmhead` declarations: Authors' contributions at **1,507**, Acknowledgements at **1,526**; ASM does not use the BMC declarations apparatus |
| A6 | **Methods placed after Discussion** | Stage sections (**406–919**) currently precede Results (**920**). ASM order is Introduction / Results / Discussion / Methods |
| A7 | **Table and figure legends collected after the References** | Table float at 968–980, figure floats at 336–368 / 741–772 / 983–1014 are all inline; `\bibliography{reference}` is at 1,671 |
| A8 | The **reuse demonstration** (IBD 25/44) *presented as* the Resource Report's required "proof-of-principle that others can utilise it" | The sentence exists in Results at **1,127–1,129** but is framed as "an exploratory consensus check", not as a reuse demonstration; it is then re-cited as a caveat in Limitations at **1,327–1,330**. ASM reviewers will not recognise a one-sentence exploratory check as proof-of-principle |
| A9 | **Open-data deposition at review time** (present tense, live DOI) | Lines **1,447–1,454** are future tense with two empty slots |
| A10 | The **ASM Overleaf template** adopted | Build is `sn-jnl` v3.1 (line 23) — Springer-specific |
| A11 | A sentence showing **who uses the resource and for what** | No user-facing use case in the body; the reviewer question at a systems-biology journal is exactly this |

### C-2.2 Rephrase at *mSystems*

| # | Rephrase | From → to | Evidence |
|---|---|---|---|
| B1 | Article-type framing | "protocol" → "resource" / "pipeline"; the word may stay only if pointed at Methods and Protocols, which is the wrong type here | 12 visible occurrences (104, 106, 132, 235, 288, 297, 331, 352, 495, 703, 832, 1,447) |
| B2 | Abstract structure | ASM Research format: unstructured or Background/Methods/Results/Conclusions at ≤250 words, **plus** Importance | Abstract block lines 103–136 |
| B3 | Abstract payoff | Lead with what the resource *enables* (reuse of metadata across 453 papers), not with F1 scores belonging to other systems | Lines 119–124 |
| B4 | Triple framing | Present the untyped 47.4% of triples (12,224 of 25,788) as **deliberate abstention** — a design decision a resource user needs to know | Line 114; caveat at 1290–1296 |
| B5 | "16S" | "16S" → "16S rRNA gene". Not documented as an ASM rule, but correct usage and harmless | Lines 843, 1,061, 1,125 |
| B6 | Benchmark framing | Reframe as transfer measurement (the novel part), not as competitive benchmark performance | Lines 119–123 |
| B7 | Data availability | Future → present tense with live DOI | Lines 1,447–1,460 |
| B8 | 453 vs 452 | State one analysis universe | Lines 109, 352, 436, 1403 |
| B9 | Section heading | `\section{Protocol overview}` → pipeline/resource overview | Line **331** |
| B10 | Title | Retarget toward "resource" language so the article type is obvious from the title | Line 66 |

### C-2.3 Remove at *mSystems*

| # | Remove | Evidence |
|---|---|---|
| Y1 | The BMC/Springer **Declarations apparatus**: Ethics approval, Consent for publication, Availability of data and materials, Competing interests, Funding, Authors' contributions, Acknowledgements as `\bmhead` blocks | `\bmhead` at **1,392 / 1,398 / 1,401 / 1,476 / 1,493 / 1,507 / 1,526 / 1,539** (Ethics, Consent, Availability, Competing interests, Funding, Authors' contributions, Acknowledgements, AI declaration) under `\section*{Declarations}` at **1,390** — **fold into ASM's Author Contributions / Acknowledgments / Data availability**, do not delete the content |
| Y2 | The **Abbreviations** section (not an ASM back-matter requirement) | `\section*{Abbreviations}` at line 1,364, **13 entries** (API, BC5CDR, CDM, CTD, DOI, F1, IBD, LLM, MeSH, NCBI, NER, OMOP, UMLS). Note the mirror-image problem: **SSSOM, BioLink/KGX, RDF and OWL occur zero times in visible prose** — the export formats exist in `src/cdm_pipeline/export/` but never reach the paper, so they need no abbreviation entry yet |
| Y3 | The claims-register filename from Table 1 caption and note | Caption 969–975, tablenote 978 |
| Y4 | The 4 `[AUTHOR INPUT REQUIRED]` blocks once supplied | Lines 1,487, 1,502, 1,517, 1,535 |
| Y5 | The 2 unfilled DOI slots once deposits exist | Lines 1,452, 1,454 |
| Y6 | The 937 comment-only lines | 55.7% of the file |
| Y7 | The `sn-jnl`-specific machinery (structured-abstract macros, declaration ordering) | Line **23** (`\documentclass[...]{sn-jnl}`) and the back-matter block **1,390–1,545** (`\backmatter` at 1,358) |
| Y8 | 28 of 29 "Claude" mentions | Keep line **1,598** |

### C-2.4 Net position at *mSystems*

**Best available fit.** The only venue of the three whose article-type catalogue contains a name for what this manuscript already is (Resource Report), a 5,000-word cap the body already meets with ~1,100 words to spare (**3,911** excluding back matter, **4,584** including it), and published precedents of exactly this shape — including a metadata-schema paper with no primary data. Still requires the availability fix, the reuse promotion, the Importance paragraph and the abstract trim. The honest counter-signal stands: **1** text-mining-titled paper in nine years, **0** knowledge-graph-titled, and reviewers are systems microbiologists who will ask what this tells them about microbes.

---

## C-3. Venue 3 — BMC Microbiology (Springer Nature, ISSN 1471-2180)

**Article type to select: Database** (best mapping — the paper's product is a released data resource; fallback Software, then Research). **There is no Methodology type at this journal**; the verifiable list is Research article, Database article, Software article, Review, Matters Arising, Comment.

### C-3.1 Missing at BMC Microbiology

| # | Missing item | Evidence / where |
|---|---|---|
| D1 | A **"Utility and discussion"** section — required for the Database article type | Does not exist. `\section{Results}` (**920**) and `\section{Recommendations}` (**1166**) carry the content but are not framed as utility |
| D2 | A **direct comparison against similar existing databases** — the Database type requires it; the Software type requires comparably direct comparison with related software | No comparison table or paragraph against MINERVA, MicrobiomeKG, KG-Microbe, BugSigDB as resources |
| D3 | An **optional case study** demonstrating utility (the Database type offers this; the IBD 25/44 result is exactly it) | The result is in Results at **1,127–1,129** but not written as a case study — no study design, no cell table, no IBD framing. It is re-cited in Limitations at **1,327–1,330** |
| D4 | **Reviewer-anonymous access** to the resource at review time (Software-type requirement, good practice for Database) | Availability block **1,401–1,460** gives a future-tense Zenodo deposit with no private link; the two placeholder slots are at **1,452** and **1,454** |
| D5 | **Archive copy** in a permanent repository (explicit Software-type requirement) | Zenodo deposit planned but not created; DOI slots empty at 1,452 and 1,454 |
| D6 | `\section{Methods}` as a named section | Five unlabelled `\section{Stage n}` blocks at **406, 460, 538, 679, 774** |
| D7 | `\section{Conclusions}` | BMC Research structure is Background / Methods / Results / Discussion / Conclusions / List of abbreviations / Declarations — Conclusions is a required heading and is absent (only the abstract's third labelled paragraph, line 132) |
| D8 | `\section{Discussion}` as a named heading | Absent; `\section{Recommendations}` (**1166**) and `\section{Limitations}` (**1251**) are top-level but neither is Discussion |
| D9 | A **reuse demonstration** written as one | IBD check at **1,127–1,129** (one sentence, "exploratory"), re-cited as a caveat at **1,327–1,330** |
| D10 | **Confidence intervals** on 61.8%, 6.2%, 82.9% agreement and κ = 0.566/0.471 | Lines **119–121** and **1,050–1,053** |
| D11 | **Competitor citations** | Visible-text grep: `MicrobiomeKG`, `KG-Microbe`, `SemRep`, `AIONER`, `BioREx` all **0**; `BugSigDB` **18 occurrences across 17 visible lines**, `MINERVA` **1 visible** (line 250; the other 2 of 3 raw hits are comment-only) |

### C-3.2 Rephrase at BMC Microbiology

| # | Rephrase | From → to | Evidence |
|---|---|---|---|
| E1 | Self-description | "protocol" → "resource" / "database" / "pipeline" — consistent with the Database type | 12 visible occurrences (104, 106, 132, 235, 288, 297, 331, 352, 495, 703, 832, 1,447) |
| E2 | Section heading | `\section{Protocol overview}` → `\section{Methods overview}` | Line **331** |
| E3 | Figure 1 caption | "Protocol overview" → "Pipeline overview" | Line 352 |
| E4 | **Research-type risk wording** — BMC Research criteria explicitly exclude non-commissioned pooled analyses and bibliometric analyses; if submitting as Research rather than Database, the 453-paper census must be framed as a *corpus construction method*, not as a bibliometric study | Background, lines 228–300 |
| E5 | "16S" | "16S" → "16S rRNA gene" | Lines 843, 1,061, 1,125 |
| E6 | Triple framing | `OTHER_RELATION` dominance → principled abstention | Line 108 |
| E7 | Benchmark framing | Transfer measurement, not borrowed benchmark performance | Lines 119–123 |
| E8 | Data availability | Future → present tense with live DOI | Lines 1,447–1,460 |
| E9 | 453 vs 452 | One analysis universe | Lines 109, 352, 436, 1403 |
| E10 | Title | Retarget toward database/resource language to match the article type | Line 66 |

### C-3.3 Remove at BMC Microbiology

| # | Remove | Evidence |
|---|---|---|
| Z1 | The claims-register filename from Table 1 caption and note | Caption 969–975, tablenote 978 |
| Z2 | The 4 `[AUTHOR INPUT REQUIRED]` blocks once supplied | Lines **1,487** (competing interests), **1,502** (funding), **1,517** (CRediT), **1,535** (acknowledgements) |
| Z3 | The 2 unfilled DOI slots once deposits exist | Lines 1,452, 1,454 |
| Z4 | The 937 comment-only lines | 55.7% of the file |
| Z5 | 28 of 29 "Claude" mentions | Keep line **1,598** |
| Z6 | **Nothing else** — this is the one venue where the existing back matter (Abbreviations at 1364, Declarations at 1390) is *already correct* and should be kept | Back matter built for BMC ordering |

### C-3.4 Net position at BMC Microbiology

**Most likely acceptance of the three, lowest signalling, cheapest APC (£2,390 / $3,090 / €2,690).** The back matter already conforms; the structural gap is the missing Utility-and-discussion comparison, which is also the fix that most improves the paper anywhere. If submitted here, go as **Database**, add the comparison, and promote the IBD case study.

---

## C-4. Cross-venue summary

| Item | ***Microbiome*** | ***mSystems*** | **BMC Microbiology** |
|---|---|---|---|
| Article type | Methodology (or Software) | **Resource Report** | **Database** (or Software) |
| `\section{Methods}` | Required, before Results | Required, **after** Discussion | Required, before Results |
| `\section{Discussion}` | Required | ASM "Discussion" | Required |
| `\section{Conclusions}` | Required | Not used | **Required** |
| Abstract cap | ≤350 (current 331 excl. labels ✓) | **≤250** (current 331/334 ✗) | ≤350 (current 331 excl. labels ✓) |
| Importance paragraph | Not used | **≤150 words, required** | Not used |
| Running title | Not required | ≤54 chars (current 47 ✓) | Not required |
| Line numbers / double spacing | **Required** | Optional (format-neutral) | Not required |
| Back matter | Rebuild (add Authors' information, Endnotes) | Rebuild to ASM sections | **Already correct — keep** |
| APC | €4,290 / $5,190 / £3,590 | $4,500 non-member / $3,375 member | **£2,390 / $3,090 / €2,690** |
| Blocking gap | No biological demonstration | No Importance + abstract 61 over + no live deposit | No Utility-and-discussion comparison |
| Verdict | Highest ceiling, lowest probability | **Best fit as written** | Most likely acceptance, lowest signalling |

**What is venue-independent and should be done first, whichever journal is chosen:** upload the deposit and fill the DOIs (X4/Y5/Z3), replace the 4 author-input blocks (X3/Y4/Z2), strip the 937 comment lines and 28 of the 29 "Claude" mentions (X5/Y6/Z4, X8/Y8/Z5), fix `16S` → `16S rRNA gene` at 843/1061/1125, remove the claims-register filename at 969–976 and its tablenote at 1451, and replace "protocol" in all 12 visible places (104, 106, 132, 235, 288, 297, 331, 352, 495, 703, 832, 1447). That is roughly **one day of work** and it is required at all three venues.

---

# PART C2 — MASTER FIX LIST

Items are deduplicated across both parts and grouped by how blocking they are. Numbers are stable references for tracking.

## Tier 0 — cannot submit without these

> **Item 41 (Tier 2) has already been applied to `manuscript.tex`** — the entity-accounting sentence at 1,016–1,023 summed to 38 against a 33-entity registry, and now reads *"…fifteen partially (five of them embedded in other tables' rows), and one is planned"*, plus "leaves the **entity** tables unchanged" for 3.1.0. Rebuilt clean at 18 pages with 0 errors. See [A6.8](#a68-one-sentence-in-results-did-not-add-up-fixed-in-the-working-tree).

1. **Decide the venue** (Part 0, [ASM7](#asm7-five-venue-verdict-ranking)) — *Microbiome*, BMC Microbiology, or *mSystems*. Everything downstream depends on it, including the section order.
2. **Decide the article type** — *Microbiome*: Methodology or Software. *mSystems*: **Resource Report**. BMC Microbiology: Database or Software (**no Methodology type exists there**). Then replace "protocol" with "pipeline"/"resource" where that is what is meant (**12 visible occurrences**, including the abstract at line 106, the section heading at 331 and the caption at 352). At *mSystems* this is a clarity fix, not a desk-reject.
3. Replace the **4** `[AUTHOR INPUT REQUIRED]` blocks (competing interests, funding, CRediT, acknowledgements).
4. Fill the **Zenodo DOI** and the **code repository + DOI**.
5. **Upload the deposit before submission**; convert "will be deposited" to present tense with a live DOI. **Identical requirement at all three venues** — do this regardless of the decision.
6. Add `\section{Methods}` — rename/absorb the five Stage sections as subsections. **If *mSystems*: Methods goes after Discussion, not before Results.**
7. Add `\section{Discussion}` with **Limitations and Recommendations as subsections**.
8. Add `\section{Conclusions}` (*Microbiome*/BMC only — ASM ends with Discussion).
9. Enable `referee,lineno` (double spacing + line numbers) for the submission build (*Microbiome* requires it; ASM is format-neutral, so optional).
10. Fix bare **"16S" → "16S rRNA gene"** (lines 843, 1,061, 1,125) — explicit *Microbiome* rule; correct at any venue.
11. Remove the internal `MANUSCRIPT_CLAIMS_REGISTER.csv` reference from Table 1's caption (969–975) and its tablenote (978).
12. Produce a **comment-stripped `.tex`** for submission (937 comment lines, 29 "Claude" mentions, 28 of them in comments).
13. ***If mSystems:*** cut the abstract from **331 → ≤250 words**, write a **≤150-word Importance** paragraph, add the **abstract word count** and a **≤54-character running title** to the title page, and swap `sn-jnl` for the ASM Overleaf template.

## Tier 1 — reviewer-facing, decisive

14. **Write the SSSOM / KGX-Biolink / RDF exports into the paper** — they exist in `src/cdm_pipeline/export/`. Instantly answers the FAIR question and puts you in the same interoperability conversation as MicrobiomeKG's Translator deployment. **You built it and forgot to claim it.**
15. Add the **capability matrix** (B4.1) — one table answers "how are you different" before it is asked.
16. **Rewrite the related-work paragraph** into the three-paragraph structure (B4.2) and **cite every competitor** in B1.1–B1.2.
17. **Promote the IBD 25/44 result** from Limitations into Results as "a first reuse demonstration". You already have the analysis; it is currently published as an apology.
18. Add a **FAIR + MIxS/MIMARKS + STORMS/STREAMS** paragraph to Background and Availability; cite `wilkinson2016fair`, `yilmaz2011mixs`.
19. Add **confidence intervals** (Wilson / bootstrap) to 61.8%, 6.2%, the 82.9% judge agreement and the κ values; cite `wilson1927`, `efron1993bootstrap`.
20. **Finish or remove** the second-reviewer 100-mapping overlap (H01).
21. **Reframe triples as principled abstention** in abstract + Results, or demote them.
22. **Fix the abstract's borrowed-benchmark framing** (90.1 / 80.6 are PubTator3 / HunFlair2).
23. **Promote the transfer-domain finding** (27 configs / 21 systems; Spearman 0.749; non-BioRED-trained organisms/diseases/genes win) from Recommendations to Results.
24. **Cite SapBERT (lines 621, 1,006, 1,127, 1,594), MiniLM (622, 1,594), BioBERT (1,078) and original GLiNER**; then decide whether to name the unnamed components (see A7.2).
25. **Prune or cite** the 32 uncited references; raise the cited count toward 60+.
26. **State the inclusion rule** for the 453-paper corpus (cited-works count → retrievable → included/excluded why).
27. **Resolve 453 vs 452**; name `HMPAPER_000372` or state the 452-paper analysis universe.
28. Add a **novelty paragraph** (B4.5).
29. Add an **"Additional files"** list; ship paper list + licence matrix + hashes so the corpus is verifiable-by-reconstruction.
30. Add **"Authors' information"** heading; add emails for **all** authors (currently corresponding only).
31. Complete affiliation 3 **street/postcode** and clear the `VERIFY` items in `TITLE_PAGE.md`.

## Tier 2 — quality, consistency, and defence

32. Add one **small biological figure** — e.g. a genus × condition consensus heat map with BugSigDB overlap annotated. The single change that turns this from NLP engineering into a microbiome resource.
33. **Compare the pipeline as a system** vs PubTator3-as-pipeline at equal corpus (PubTator3 coverage is already 438/453). Directly satisfies the Software criterion "direct comparison with available related software".
34. Add a short **statistics/reporting-conventions** paragraph (denominators, how ratios are defined, multiple comparisons).
35. Explain the **2,505,684 vs 2,505,735 vs 2,505,736** layer distinction and the known manifest off-by-one, in Methods.
36. Clarify that **derived annotations** over withheld text (not only raw text) are restricted/redacted.
37. Add a **PROV/PROV-O** paragraph: map per-row provenance to PROV-O, or justify why not.
38. Add a **sustainability/community** sentence: how the resource is updated, versioned and integrated.
39. Rewrite the three figure legends flagged `AUTHOR REWRITE REQUIRED` (markers at **349**, **756**, **997**).
40. Add a sentence in Declarations stating the **deposit licence** (CC BY 4.0 proposed).
41. **Fix the entity-accounting sentence at 1,016–1,023 — it does not add up.** *(Applied 2026-11-10; verified in the rebuilt PDF.)* It reads *"Seventeen entity types are fully populated, fifteen partially, one is planned and five are embedded in other tables' rows"*. That is **17 + 15 + 1 + 5 = 38** against a registry of **33** entities, because the five embedded ones (`PARAGRAPH`, `SENTENCE`, `MODEL_RUN`, `MENTION_EVIDENCE`, `DEFINITION_EVIDENCE`) are all `PARTIAL_POPULATED` and therefore already inside the fifteen. The registry (`releases/cdm_v3/3.0.3/remediation/UPDATED_ENTITY_REGISTRY_PROPOSAL.csv`) has exactly three statuses: `POPULATED_EXISTING` **17**, `PARTIAL_POPULATED` **15**, `PLANNED` **1**. Suggested rewrite: *"Seventeen entity types are fully populated, fifteen partially (five of them embedded in other tables' rows), and one is planned."* **Note on the figure:** the "33 entities in 10 modules" in Fig. 2's caption is **correct** — it is `len()` of that same 33-row registry, which `make_bib_extra_figures.py` reads at line 47. Do not "fix" it, and do not confuse it with `docs/cdm_design/cdm_schema.json` (DRAFT 0.1.0, 22 tables), which the figure does not plot.
42. **Merge Fig. 1 and Fig. 2** if page pressure allows; decide on the unused `fig_overview_illustrated.pdf`.
43. Add biology-facing **keywords**: "metadata standards", "FAIR", "data harmonisation".
44. Close the **bibliography gap that actually exists**: `reference.bib` holds **68 entries**, only **36** are cited (A7). There is no `.bbl`/cite-key discrepancy — `manuscript.bbl` has **36 `\bibitem`**, the comment-stripped `.tex` cites **36** distinct keys, and the pairwise diff is empty in both directions. An earlier draft's "33 vs 34" is superseded; do not quote it.

## Tier 3 — polish and strategy

45. Write a **cover letter** arguing field relevance with one concrete use case.
46. Consider a resource- or finding-flavoured **title** (B4.4).
47. Check every abbreviation is defined at first use in text, not only in the list.
48. Run `manuscript-style-check` and `text-overlap-check` before submission.
49. Re-run the clean `latexmk -pdf` build after all edits and re-verify 0 errors / 0 undefined / no float collisions.

## Effort ordering (value ÷ effort), if time is short

| Effort | Items |
|---|---|
| **Under an hour** | 2 (replace "protocol"), 10 (16S), 11 (claims register), 24 (SapBERT/MiniLM), 43 (keywords), 12 (strip comments), **13 (abstract trim + Importance, if mSystems)** |
| **Under a day** | 14 (exports), 15 (capability matrix), 16 (related work), 17 (IBD), 18 (standards), 19 (CIs), 23 (transfer finding), 25 (uncited refs), 27 (452), 29 (additional files), **venue template switch (if mSystems)** |
| **Days, but decisive** | 20 (second reviewer), 32 (biological figure), 33 (system comparison), 37 (PROV-O) |
| **Blocking, outside writing** | 3 (author facts), 4–5 (deposit + DOI), 30–31 (authors' information, emails, affiliation) |

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
| **36 cited total**, 32 of 68 `.bib` entries never reaching the `.bbl` | 60+ cited, standards included | Removes the "thin scholarship" rejection |
| Interop exports invisible | SSSOM/KGX/RDF claimed | Adds a genuine competitive capability |
| Borrowed benchmarks lead | Transfer-domain finding leads | Owns the contribution |
| Future-tense availability | Live DOI at submission | Removes a pre-review bounce |

That gets the manuscript **into review with a fair hearing**. Whether it is accepted still depends on the reviewer draw, on whether the authors will add the biological demonstration, and on whether the editor judges a provenance-disciplined extraction resource to be within scope that month.

**The honest risk assessment:** without Tier 2 items 32–33 (one biological figure, system-level comparison) and Tier 1 item 20 (second reviewer), the paper is very likely rejected with *"the authors present a well-engineered pipeline but do not demonstrate that it enables new microbiome insight, and the validation is a single-reviewer spot check."* With them, it is a credible Methodology paper.

**BMC Microbiology remains the honest fallback** if the authors will not invest in the biological demonstration — it publishes the KG/ontology framing at volume (60 vs 13 ontology-titled papers) and does not carry the mechanistic-insight editorial pressure.

***mSystems* changes the calculation materially, and should be read as a serious first choice rather than a fallback.** Two of the three items this part calls "decisive" — the biological demonstration and the system-level comparison — are *optional* for a **Resource Report**. The item that is not optional, the deposited resource, is the same at every venue. In practical terms: the current manuscript plus a deposit, a trimmed abstract, a 150-word Importance paragraph, a reuse demonstration promoted out of Limitations, and the competitor citations would be a **credible mSystems Resource Report** — and that is a materially shorter list than the *Microbiome* path.

The honest risk at *mSystems* is different, not smaller: a reviewer drawn from systems microbiology will ask *"who will use this, and for what?"* and will not be impressed by named-entity F1 scores. The answer has to be a use case, not a metric. The IBD 25/44 result is that use case, and it is currently buried in Limitations as a caveat.

**Three doors, honestly stated:**

| Venue | What it takes from here | What it buys | Principal way it fails |
|---|---|---|---|
| ***mSystems*** | Deposit + DOI, abstract trim, Importance, reuse promoted, competitors cited, template switch | Fastest credible route; article type matches the paper | "Who uses this?" — answered only by the reuse case |
| ***Microbiome*** | All of the above **plus** a biological figure, a system comparison, and a finished second reviewer | Highest visibility in the field | Rejection on framing before the science is assessed |
| **BMC Microbiology** | Deposit + DOI, light reframing | Highest acceptance probability | Low signalling; the paper lands quietly |

---

# PART E — SEQUENCING

1. **Answer Part 0** — which journal, and which article type. There are now three options; [ASM7](#asm7-five-venue-verdict-ranking) ranks them, and the ranking turns on whether the authors will add a biological demonstration.
2. **Tier 0 items 3–5** (author facts + DOIs + deposit upload) — these gate everything else and are **identical at every venue**. Start here regardless; none of this work is wasted whichever venue is chosen.
3. **Upload the deposit**, add the SSSOM/KGX/RDF exports to it, then rewrite Availability in present tense.
4. **Restructure** (Tier 0 items 6–9) in one pass, since Methods/Discussion/Conclusions move together — **and to the chosen venue's section order**.
5. **Rewrite Background** (B4.2) + add the capability matrix (B4.1) + novelty paragraph (B4.5); cite all competitors.
6. **Promote the IBD reuse result** and the **transfer-domain finding** into Results; reframe triples as abstention.
7. **Add the comparison table and the biological figure** — highest value per hour for reviewer confidence. At *mSystems* the comparison table still matters and the biological figure is optional.
8. **Finish the second reviewer**; add Wilson CIs.
9. **If *mSystems*:** trim the abstract to ≤250 words, write the ≤150-word Importance paragraph, add the running title and abstract word count, and switch to the ASM template.
10. Strip comments, rebuild, verify 0 errors, then run `manuscript-style-check` and `text-overlap-check`.

---

# Appendix 1 — manuscript statistics snapshot

| Metric | Value |
|---|---|
| `manuscript.tex` lines | **1,683** |
| File size | 107,887 bytes |
| Comment-only lines | **937 (55.7%)** |
| Visible non-empty lines | **669** |
| "Claude" mentions | **29** raw — 28 inside comments, **1 visible** (line 1,598, in the AI-use declaration) |
| Body words (per-section table, incl. Abbreviations + Declarations) | **4,584** (**3,911** excluding back matter) |
| Whole-body recount, same span measured contiguously | 4,604 plain / 4,797 hyphen-split (body only: 3,934 / 4,092) |
| Abstract words | **334 incl. the three bold labels / 331 excl.**; paragraphs 133 / 133 / 68 incl. labels (132 / 132 / 67 excl.); **353** under hyphen-splitting |
| Figures | 3 (vector, 0 raster) — blocks at 336–368, 741–772, 983–1014 |
| Tables | 1 (`table*`, 968–980; `\input` of the body at 976, `tablenotes` 977–979) |
| Top-level sections | 10 numbered + 2 `\section*` (1,364, 1,390) |
| Bibliography entries in `reference.bib` | 68 |
| Compiled `.bbl` entries | **36** |
| Distinct cite keys | **36** |
| Cited in text | **36 / 36 — 0 uncited** |
| Bib keys never reaching the `.bbl` | **32** — uncited (A7.1) |
| `et al.` occurrences in `.bbl` | 57 |
| `[AUTHOR INPUT REQUIRED]` markers | **4 visible** (1,487, 1,502, 1,517, 1,535) + 6 in comments = 10 total |
| Unfilled DOI/repository slots | **2** (1,452, 1,454); plus the code-repo comment slot at 1,443 |
| PDF pages | **18** (406,353 bytes) |
| LaTeX errors | 0 |
| LaTeX warnings | 0 |
| Undefined citations/references | 0 |
| Overfull hbox | **1, at 4.86 pt** (under the 5 pt threshold) |
| Underfull boxes | 28 (3 hbox / 25 vbox) |
| Unused figure file | `Fig/fig_overview_illustrated.pdf` |
| Body words vs *mSystems* 5,000-word cap | **3,911** vs 5,000 — **≈1,089 headroom** (4,584 including back matter still under) |
| Abstract vs *mSystems* 250-word cap | **331 excl. labels** vs 250 — **81 over** (**84 over** if the three labels count) |

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

**ASM journal-profile counts** (PubMed E-utilities, `db=pubmed`, 2026-11-10; full matrix saved to `/home/jkalra_hpc/jk_fig/asm_profile.json`):

- Totals: mSystems **3,071** · mSphere **3,238** · Microbiology Spectrum **10,103** · mBio **9,105**
- 2026 only: mSystems **354** · mSphere **233** · Spectrum **1,689** (2025: mSystems **444**)
- mSystems `2379-5077[ta]` topical: semantic/ontology/data model (tiab) **18** · curation/harmonisation/interoperability/metadata standard (tiab) **25** · metadata/schema/standard/controlled-vocabulary in title **7** · resource/database/platform/toolkit/repository in title **31** · software/database/tool/pipeline **71** · multi-omics **160** · benchmark **8** · **text-mining/NER/NLP 1** · LLM in abstract **4** · knowledge-graph/ontology in title **0**
- mSystems precedents confirmed by PMID/DOI: PaperBLAST (2017, `10.1128/mSystems.00039-17`) · swab-site metadata schema (2023, PMID **36847566**, `10.1128/msystems.01284-22`) · NMDC Microbiome Metadata Standards report (2021) · E.PathDash (2024) · protein-LLM semantic search (2024)

**ASM guidance** — direct fetch of `journals.asm.org` returns **HTTP 403** and the `r.jina.ai` proxy hits a Cloudflare CAPTCHA, so ASM facts are drawn from search-engine excerpts of ASM's own pages, **not** a full page read. Where a detail could not be pinned down it is marked "verify" in the tables above:

- `https://journals.asm.org/journal/msystems/article-types` (article types, 5,000-word cap, Resource Report description, format-neutral statement resolved from search snippets)
- `https://journals.asm.org/format-neutral-submissions`
- `https://journals.asm.org/publication-fees` (APC rows: mBio/mSphere/mSystems $3,375 member / $4,500 non-member; short articles $1,950 / $2,600)
- `https://journals.asm.org/proprietary-rights` (CC BY 4.0; authors retain copyright)
- `https://journals.asm.org/peer-review-process` (open peer review optional in mSystems and Microbiology Spectrum)
- `https://journals.asm.org/journal/msystems/article-types` (retrieved 2026-11-10 via search snippet: 250-word abstract, 54-character running title, ≤150-word Importance; Resource Report listed as an article type) — **supersedes** the earlier JB/CMR inference, which wrongly carried JB's 120-word Importance limit onto mSystems
- `https://journals.asm.org/journal/jb/article-types` and `.../journal/cmr/article-types` (used only to corroborate the 54-character running title and the 250-word abstract, which are ASM-wide)
- Article-type inventories corroborated at `https://scraiber.com/journals/msystems` and `https://scraiber.com/journals/msphere`

**Manuscript word counts for the mSystems comparison** (comments stripped, LaTeX commands removed):

- Body between `\section{Background}` (line 162) and `\bibliography{reference}` (line 1,671), comment lines and trailing comments stripped, float environments removed as whole blocks, `\cite*`/`\ref`/`\label`/`\eqref` arguments and remaining commands stripped: **4,584 words** including Abbreviations and Declarations, **3,911** excluding back matter (3,911 = 4,584 − 58 − 615). A whole-body recount of the same span (Background heading to `\bibliography`), measuring the text contiguously rather than section-by-section, gives **4,604 plain tokens / 4,797 under hyphen-splitting tokenisation**; the body-only span, same method, is **3,934 / 4,092**. The 20-word difference from 4,584 is the heading text, which the per-section table excludes. The earlier figures of 3,953 / 4,026 / 4,507 / 3,445 / 4,101 / 4,551 in this log came from different filters and are superseded.
- Abstract: **334 words incl. the three bold labels / 331 excl.** by the same tokeniser, paragraph split 133 / 133 / 68 including labels (132 / 132 / 67 excluding them), and **353** if hyphenated compounds are split (the manuscript's own header comment cited 282, but that figure is the count of COMPLETE papers in the catalogue manifest, not an abstract word count — corrected 2026-11-10; an intermediate 311/314 pair came from a filter that dropped the labels and one label remainder, and is superseded)
- `reference.bib`: 68 entries, **0** with more than 6 authors (so no truncation rule bites)

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
