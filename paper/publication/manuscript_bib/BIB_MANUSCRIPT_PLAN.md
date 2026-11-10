# Plan: Briefings in Bioinformatics submission (Problem Solving Protocol)

*Prepared 2026-11-03. Requirements: `../submission_readiness/journal_requirements_source/bib/BIB_REQUIREMENTS.md`. This plan sets the structure, word budget and content mapping. It deliberately contains no manuscript prose: BiB does not accept papers drafted by LLMs, so the authors write the text, using the facts referenced here (claim IDs from `../final_validation/MANUSCRIPT_CLAIMS_REGISTER.csv`).*

## 1. Why a Problem Solving Protocol

- **Scope:** BiB does not publish pure original research. A Problem Solving Protocol is "a protocol for solving a specific problem using different sets of programs", with a limit of 2,000–5,000 words.
- **Fit:** our work is exactly that. It combines several sets of programs:
  - trained NER, zero-shot NER, small LLMs and gazetteers;
  - ontology and vocabulary mappers;
  - an LLM extractor;
  - evaluators: structural checks, evidence anchoring, model judges, and BugSigDB comparison.
  
  Together they solve a specific problem: **building a provenance-traceable common data model from microbiome literature, and evaluating it when no human annotation is available.**
- **Not this type:** a "resource" or "data descriptor" framing (as for *Scientific Data*) does not fit BiB. The CDM and catalogue appear as the *output* of the protocol and are deposited. They are not the subject of the paper.
- **The selling point:** BiB readers expect practical guidance on which programs to use. Our most useful findings are comparative:
  - trained taggers vs small LLMs: see §12.1 (benchmark F1 and corpus judged validity L01–L04 are separate results; organisms differ);
  - public-benchmark ranking predicts corpus behaviour for diseases but not organisms (ρ 0.75 vs 0.02);
  - human-curated metadata is reproduced closely (N07–N08);
  - text-only extraction misses figure- and supplement-based findings (N06).

## 2. Working title elements (authors to phrase)

The title should cover: protocol; microbiome literature; common data model; multiple NER and LLM programs; evaluation without human annotation. Avoid "accurate" and "validated" (framing rules in `../final_validation/MASTER_VALIDATION_REPORT.md`).

## 3. Structure and word budget (5,000-word ceiling, aim for 4,700)

| § | Section | Words | Content source (working notes) | Key facts (claim IDs) |
|---|---|---:|---|---|
| — | Abstract | ~200 | | problem, protocol, 3 headline results |
| 1 | Introduction: the problem | 550 | `00_introduction.md` | why literature-derived microbiome data lacks a common model; gap left by curated databases (BugSigDB), corpora (MiDRED, DiMB-RE), KGs (MINERVA) and LLM metadata harmonisation (Higashi et al.); what the protocol adds |
| 2 | Protocol overview (Figure 1) | 350 | `01_methods…` §Corpus, FIGURE_PLAN F1+F2 | inputs, the 5 stages, outputs; corpus defined by deposited data, not by literature search (C01–C08) |
| 3 | Stage 1: Corpus and sectioning | 250 | `01_methods…` §Corpus | 453 BioProjects, 4,006 sections, rights split 274 / 179 |
| 4 | Stage 2: Entity extraction with multiple programs | 550 | `01_methods…` §Entity mention extraction, §NER benchmark | the programs (Table 1); sources kept separate; benchmark design |
| 5 | Stage 3: Normalisation and vocabulary mapping | 400 | `01_methods…` §Canonical terms | guarded mapping and two-model adjudication (T, P claims) |
| 6 | Stage 4: Catalogue and CDM (Figure 2) | 450 | `01_methods…` §Data catalogue, §Common data model | evidence-anchored catalogue; CDM modules; provenance chain (K, M claims) |
| 7 | Stage 5: Evaluation without human annotation (Figure 3) | 700 | `01_methods…` §Computational validation, `05_supplement_bugsigdb…` Method | 4 layers: structural integrity; value-in-evidence and two model judges; LLM-judged validity of all entities and triples (L); pre-registered comparison with human-curated BugSigDB (N). Rule: concordance, not accuracy |
| 8 | Results: what each program contributed (Figure 4, Table 2) | 900 | `02_results.md` §3–7, `04_supplement…`, `05_supplement…` | NER ranking (H03–H07, L01–L04); judge results (L05–L12); BugSigDB (N02–N08); evidence results (E, J) |
| 9 | Recommendations (Table 3) | 300 | new, from §8 | decision guide: which program for which entity type; when to use model judges; what to compare against curated databases |
| 10 | Limitations | 300 | `03_discussion.md` §Limitations, §Structure is not semantics | no human annotation; text-only; small extractors; overlap of 47 papers; LLM judge not independent |
| — | Key Points | 3–5 sentences | | see §5 |
| | **Total main text** | **~4,750** | | |

**Moves to the supplement:** the full resource description (Data Records), the per-model benchmark tables, the cleaned layer, the full BugSigDB field table and the "Lessons from development". The two existing supplement notes (`04_…`, `05_…`) become Supplementary Notes 1–2.

**Cut from the main text:** about 830 words of the 5,584 counted on 2026-11-03 (`00`–`03`; **5,622 by `wc -w` on 2026-11-05**, the figure to use).
- **What the 5,622 contains:** body 5,037 (including about 142 words of claim-ID and citation tags such as "[Q08]", which will not appear in the final text), headings 179, table cells 406.
- **Without the tags:** body about 4,895, headings 179, table cells 406.
- **BiB's counting rule** (whether headings and table cells count) is not stated in the saved guidelines. Confirm it in the submission system, or ask in the pre-submission enquiry.
- **Planned cut:** on any reading the text is above the ~4,700 target, so plan cuts of roughly 200 to 900 words.
- **Not included:** abstract, reference list, figure legends, Key Points.
- Compare with BiB's counting rule once it is confirmed in the submission system., mainly the resource description (`01_methods…` §Resource description) and the discussion subsections "What the resource provides" and "Reuse".

## 4. Figures and tables (no limit stated; aim for 4 + 3)

| | Content | Source |
|---|---|---|
| Figure 1 | Protocol flowchart: 5 stages, programs per stage, counts on arrows | FIGURE_PLAN F1 + F2 merged |
| Figure 2 | CDM architecture and provenance spine | FIGURE_PLAN F3 |
| Figure 3 | Evaluation layers: what each tests, and with or without humans | new (simple diagram) |
| Figure 4 | (a) public F1 vs corpus grounding per program; (b) LLM-judged validity per program; (c) BugSigDB coverage by signature source; (d) direction agreement vs chance | FIGURE_PLAN F4–F5; `llm_judge…/summary.json`; `bugsigdb…/summary.json` |
| Table 1 | Programs used: name, version, kind, stage, licence, hardware | `01_methods…`, configs |
| Table 2 | BugSigDB concordance per field with chance and chance-corrected agreement | `bugsigdb_comparison_2026-11-03/REPORT.md` |
| Table 3 | Recommendations / decision guide | from §8 |

BiB chart rules: bar charts need at least 2 categories and 5 observations. Export line art at 600 dpi.

## 5. Key Points (3–5 sentences; authors write, one fact each)

1. **The protocol:** several program types combined into an evidence-anchored, provenance-traceable CDM.
2. **Trained taggers vs small LLMs:** see §12.1. Keep judged validity on the corpus (L01–L04) separate from benchmark F1; on organisms (S1000) no difference between the best small LLM and HunFlair2 was detected.
3. **Benchmark transfer:** public benchmark rankings transferred to the microbiome corpus for diseases, but not for organisms.
4. **Agreement with human curation:** curated study metadata was reproduced with high concordance (N07–N08), while taxon findings from figures and supplements were not captured (N06).
5. **Evaluation without annotation:** evaluation without human annotation must report chance baselines and must not be called accuracy.

## 6. Positioning (references verified on Crossref, 2026-11-03)

| Work | DOI | What it is | Contrast |
|---|---|---|---|
| BugSigDB | in `VERIFIED_REFERENCES.md` | human-curated signatures | our reference standard (N01–N11) |
| MINERVA (Langarica et al., BiB 2025) | 10.1093/bib/bbaf472 | microbiome–disease KG from literature | a KG of associations; ours is a data model with provenance |
| Critique of MINERVA (Chirumbolo, BiB 2025) | 10.1093/bib/bbaf673 | concerns: open-access selection bias, sentence-level extraction ignoring negation and hedging, impact-factor weighting, 29% model error, no FDR control | use as a reviewer checklist (§7) |
| MINERVA response (Langarica et al., BiB 2025) | 10.1093/bib/bbaf671 | | |
| MiDRED (Hogan et al., BioNLP 2024) | 10.18653/v1/2024.bionlp-1.31 | annotated corpus for microbiome KB construction | human-annotated; ours is annotation-free |
| DiMB-RE (Hong et al., JAMIA 2025) | 10.1093/jamia/ocaf054 | diet–microbiome relation extraction | narrower scope; annotated |
| Higashi et al., bioRxiv 2024 | 10.1101/2024.10.26.620145 | LLM harmonisation of biomedical sample metadata | metadata harmonisation, not literature findings. **Cite by this title, not as "EMBERS"**: the earlier label could not be verified. |
| SapBERT (Liu et al., NAACL 2021) | 10.18653/v1/2021.naacl-main.334 | biomedical entity embeddings | used in the BugSigDB comparison |

## 7. Anticipated reviewer concerns

The MINERVA critique was published in this journal, so expect the same questions.

| Concern raised against MINERVA | Our position (state honestly) |
|---|---|
| Open-access selection bias | The corpus is defined by deposited sequencing data (BioProjects), not by open-access search. Text is redistributed only for the 274 CC BY / CC0 papers. Licence still limits what can be released, so state that. |
| Sentence-level extraction ignores negation and hedging | Catalogue findings are extracted per section with an anchored evidence quote. Direction includes no-association, mixed and unclear findings. The triple layer is weaker (L09–L12): say so. |
| Impact-factor weighting | Not used. |
| Model error unsuitable for clinical use | No clinical claims. Concordance is reported with CIs and chance baselines. |
| No multiple-testing control | We infer no associations. Reported p and q values are carried from the papers as given. |
| (new) No human annotation | Pre-registered comparison with human-curated BugSigDB; model judges declared as model judgements. The CDM expert review is still pending (B5). |

## 8. Endmatter and declarations checklist

- [ ] Key Points (3–5 sentences)
- [ ] Up to 6 keywords. Candidates: microbiome; common data model; named entity recognition; large language models; text mining; data provenance
- [ ] Author biographies, about 30 words each
- [ ] ORCID for the submitting author
- [ ] Data availability: Zenodo deposit `releases/zenodo_frozen` (DOI pending; licence, authors and citation still placeholders)
- [ ] Code availability: repository and licence (blocker B16)
- [ ] Funding section, before Acknowledgements
- [ ] Conflicts of interest
- [ ] **AI declaration**, in the cover letter **and** in Methods or Acknowledgements, covering:
  - LLMs as pipeline components: Qwen3.5 (extraction), Gemma, Llama, Mistral and DeepSeek-R1-Distill (benchmark, term review, judges);
  - DeepSeek-V4-Flash as validity judge and for relabelling;
  - an AI coding assistant used for analysis code and working notes.
  - the same assistant (Claude Code, Anthropic) wrote the figure scripts, including Figure 1's layout and box labels and the vector icons of its icon-style alternative (`fig_overview_illustrated`); every number in the figures is read from the claims register or a result summary;
  - Claude used as an AI-model spot check of terms and triples (2026-11-05), and local Qwen3.5-9B for the judge sanity check and, if reported, the CDM 3.1 repair runs.
  
  The submitted text must be written by the authors.
- [ ] Rights: legal / library review of the 179 withheld papers (package ready)
- [ ] Article charge: check whether a Read and Publish agreement covers it
- [ ] Re-check the abstract length and the preprint policy in the submission system (not confirmed)

## 9. What changes in the existing materials

- `manuscript_draft/00`–`05` stay as working notes. Facts are reused only through claim IDs, so the number audit still applies.
- When the authors write the BiB text, add `manuscript_bib/*.md` to `manuscript_number_audit.py:DRAFTS` so every number in it is traced.
- The *Scientific Data* items in `SUBMISSION_READINESS_CHECKLIST.md` remain valid as the fallback route.

## 10. Status of figures and tables (2026-11-03)

Generated by `src/scripts/figures/make_bib_figures.py` into `figures/` (PDF and 600 dpi PNG) and `tables/` (CSV and Markdown). Every number is read from the claims register or a result summary.

| Item | Status |
|---|---|
| Figure 1: protocol flowchart | done (`fig_overview`, from `src/scripts/figures/make_overview_figure.py`, 2026-11-06); supersedes `fig1_protocol`, which is kept but must not be used (its "pre-registered scoring" note overstates the evaluation). `fig_overview_INTERNAL_with_cdm31` adds the unreleased CDM 3.1 repair band and is not for the manuscript. Alternative in icon style: `fig_overview_illustrated` (`make_overview_illustrated.py`, same numbers; authors choose one) |
| Figure 2: CDM architecture | **open**: needs the module grouping from the entity registry |
| Figure 3: evaluation layers | turned into **Table 3**, since a table shows it more clearly |
| Figure 4: (a) NER validity per configuration; (b) BugSigDB metadata concordance vs chance; (c) taxon coverage by signature source; (d) microbe triples vs BugSigDB by cleaning stratum | done (`fig4_results`); the planned public-F1-vs-grounding panel was replaced by (d) |
| Table 1: programs, with model IDs and judged validity | done |
| Table 2: BugSigDB concordance per field | done |
| Table 3: evaluation layers | done |
| Table 4: recommendations / decision guide | authors (interpretive text) |

The triple reference check (claims X01–X06, supplement 06) adds a reference-backed result for §8 Results and answers the "triples are only model-judged" concern for microbe-centred triples.

## 11. Submission readiness plan (2026-11-05)

### 11.1 Current position

The evaluation already includes:
- BC5CDR and BioRED benchmarks with CIs (H03–H07);
- BugSigDB concordance with chance baselines (N02–N08);
- direction agreement of 77.0% against 52.0% chance (N05);
- reference support for kept vs dropped triples: 54.3% vs 44.3% (X03, Fig. 4d).

| # | Blocker | Owner | Type |
|---|---|---|---|
| B-1 | Zenodo bundle carries 1,308 strings found only in text-withheld papers | Pipeline | Technical |
| B-2 | Code licence undecided (B16) | Authors | Decision |
| B-3 | Main text (`00`–`03`) is 5,622 words; the limit is 5,000 | Authors | Writing |
| B-4 | No significance tests; no comparison table | Pipeline + authors | Analysis |
| B-5 | Admin: AI declaration, funding, COI, biographies, ORCID, legal review, APC | Authors | Admin |

### 11.2 Workstreams

**WS-1 Zenodo leak (B-1), priority 1. Status: in progress.**
- Done:
  - Release scripts gained `--match alnum`: 40-letter/digit windows after removing case, spaces and punctuation, stride 5. The deposit used whitespace-only 50-character windows.
  - Independent regression check from the source side, `src/scripts/release/check_leak_regression.py`. It reports hashes, never text.
  - New bundle README (version 1.1 candidate).
- Running: the version 1.1 candidate is being rebuilt in the Lustre workspace (home quota full); SLURM job 28715431.
- `releases/zenodo_frozen` is not modified.
- Done when:
  1. the rights scan and the regression check both report 0 on the new bundle;
  2. the regression check reproduces the 1,308 on the frozen bundle;
  3. the new bundle is sealed with SHA-256;
  4. Data Availability (§8) points to the new bundle.
- Answers: "Is the released data legally redistributable?" It supports the licence-aware design claim.

**WS-2 Multi-judge agreement, priority 2.**
- How:
  1. Compute Cohen's κ between Qwen3.5-9B (stage B validity calls, 2026-11-05) and DeepSeek-V4-Flash on all 162,409 terms.
  2. Stratify by CDM type; for triples, by relation type.
  3. Report next to it the existing **AI-model spot checks (Claude)** against DeepSeek: κ 0.55 on 3,000 terms and 0.33 on 500 triples.

  The spot checks are model judgements, not author or human checks.
- Framing: the judges are screening tools, not ground truth. Agreement between models is not accuracy, and the weak triple agreement is reported openly.
- Answers: "An LLM judge is not a gold standard."

**WS-3 Significance tests (B-4), priority 3.**
- Kept vs dropped triples:
  - BugSigDB support 54.3% vs 44.3% (X03);
  - original label supported 30.6% vs 17.2% (Q05);
  - reference hits 15.5% vs 6.4% (Q08; 72/466 = 15.45%; the register's 15.4 comes from rounding an already rounded rate, so correct it to 15.5).

  Use Fisher's exact test or a two-proportion test, with Wilson CIs and the effect size.
- NER configurations: McNemar tests on shared items (`ner_fair_bench/preds/`) or paired bootstrap, with Holm correction.
- Done when every comparative claim in the Results carries a test, and the claims register has the new entries.
- Answers: "Is the cleaning effect real?"

**WS-4 Ablation, priority 4.**
- Use the existing mentions only, with no new runs. Report coverage and judged validity for the full system and with one source removed (NER ensemble, Qwen runs, gazetteer).
- Show the unique contribution per source as an overlap table or an UpSet plot.
- Answers: "Why combine three extractors?"

**WS-5 Comparison table (B-4), priority 5.**
- Compare BugSigDB, Disbiome, GMrepo, PubTator and this CDM on:
  - scope;
  - curation method;
  - character offsets;
  - per-row provenance;
  - licence handling;
  - relation triples;
  - ontology mapping (incl. OMOP);
  - update model.
- Every cell needs a citation or a documentation link. Position the CDM as complementing curated databases, not replacing them.
- Answers: "How is this different from existing resources?"

**WS-6 Use case, priority 6.**
- One explicit IBD question, e.g. which taxa show a consistent direction across studies. Answer it from N05 and Fig. F only, with no new analysis.
- Answers: "What can a user do with this?"

**WS-7 Scope and length (B-3).**
- Mention CDM 3.1 in 2–3 sentences of future work (if the lead agrees, see §11.3).
- Apply the roughly 830 words of cuts marked in §3.
- Move per-configuration detail to the supplement.
- Done when the main text is at or below 5,000 words.

### 11.3 Decisions for the project lead (freeze in force since 2026-11-02)

| Decision | Recommendation | Reason |
|---|---|---|
| Judge sanity-check run (known-wrong items, local Qwen only) | approve | small run; the most direct answer to the LLM-judge critique |
| Species benchmark (S800 / Linnaeus) | approve together with the above | **done 2026-11-05** on S1000 (successor of S800); the sanity check is also done (§11.6) |
| CDM 3.1 in the paper | future work | the repair decisions exist (stages B, H, I, 2026-11-05), but no database is built |
| Code licence (B16) | authors (e.g. MIT or Apache-2.0) | required for the deposit |

### 11.4 Anticipated reviewer questions

| Comment | Planned response | Evidence |
|---|---|---|
| No human annotation | public gold-standard benchmarks (BC5CDR, BioRED, S1000); multi-judge κ; judge sanity checks (Qwen; DeepSeek pending §12.2) | H03–H07, WS-2, §11.6 |
| Low absolute precision | a screening layer with row-level provenance for verification, compared against chance and against curated resources; **recall on the corpus is not measured, so do not call it high-recall** | Fig. 4, N05 |
| Small validation sets | CIs throughout; the BugSigDB overlap (47 papers, 270 signatures) stated as a limitation | N01, Wilson CIs |
| Taxa missed in tables, figures and supplements | reported as a finding about where knowledge sits in papers | N06, Fig. 4c |
| Novelty | comparison table | WS-5 |
| Cleaning effect | test and effect size | WS-3, X03 |
| Data licensing | licence filter, zero-leak regression check and vocabulary-label check in the release build (B22, B23) | WS-1, §12.3 |
| Use of AI | AI declaration (§8) | — |

### 11.5 Release sequence

1. WS-1 to WS-7 are finished and the §11.3 decisions are made.
2. Internal hostile review by 1–2 colleagues outside the project.
3. Pre-submission enquiry to the BiB editor about scope (Problem Solving Protocol).
4. Zenodo DOI, then a bioRxiv preprint (only after WS-1 and the legal review of the 179 papers).
5. Submission with a cover letter and 3–5 suggested reviewers (BioNLP and microbiome curation).

### 11.6 Status, 2026-11-05 (evening)

| WS | Status | Result folder | Key facts for the authors |
|---|---|---|---|
| WS-1 leak | rebuild and scans running (SLURM 28715431) | Lustre `jkalra_hpc-cdm_repair/zenodo_r2` | done when both scans report 0 |
| WS-2 judges | done | `outputs/results/benchmark/judge_agreement_2026-11-05/` | Qwen vs DeepSeek validity κ 0.283 (156,293 terms); Qwen calls 48.5% valid, DeepSeek 18.8%; per-type κ 0.12 (ENTITY) to 0.49 (ORGANISM); type agreement among both-valid 82.8% (κ 0.81); three judges Fleiss κ 0.373 (n 2,883); triples Y/P/R/N κ 0.33, binary κ 0.36; OTHER_RELATION κ 0.18 |
| Sanity check | done (approved run) | `judge_sanity_qwen_2026-11-05/` | vocabulary-confirmed terms judged valid 96.4%; injected wrong type kept 6.2% (original restored 67.8%); random fragments rejected 90.6% |
| WS-3 tests | done | `significance_2026-11-05/` | **X03 (kept 54.3% vs dropped 44.3%) is not robust: p 0.030, Holm 0.061; with papers resampled, CI −1.2 to 21.0 pts, p 0.08**; Q05 13.5 pts, p 3e-85; Q08 9.0 pts, p 0.004 (Holm 0.011); X02, N05, Q07 above chance, all p < 1e-11; BC5CDR / BioRED best trained vs best LLM: +7.8 / +14.4 F1 pts, both p < 0.001 |
| WS-4 ablation | done | `source_ablation_2026-11-05/` | without the NER ensemble, 41.1% of terms remain; without the LLM, 90.4% (14,640 terms unique to the LLM, 2,930 judged valid); **the MeSH gazetteer adds no unique term** (its 228k mentions all fall on terms other sources also find) |
| Species benchmark | done (approved run) | `ner_species_s1000/` | S1000 test, 200 abstracts, 1,365 organism spans. PubTator3 leads with 70.5 (1,877 of 2,668 spans re-anchored to the corpus text, 37 dropped). The best small LLM (Qwen3.5-4B 3-shot, 63.2) and HunFlair2 (63.1) do not differ detectably on exact F1 (paired bootstrap difference +0.1, 95% CI −6.3 to 7.0, p 0.99); HunFlair2 leads on relaxed F1 (+10.8, p < 0.001). GLiNER v2.5 ≈ 55; scispaCy 24–27. **HunFlair2 and PubTator3 (AIONER) were trained on S800, which S1000 extends: mark both in-domain (†)** |
| WS-5 comparison | facts table done | `tables/table_resource_comparison.md` | 6 cells marked "to verify" (licences of Disbiome, GMrepo, PubTator; GMrepo / PubTator vocabularies; Disbiome update model) |
| WS-6 use case | facts done | `outputs/results/benchmark/use_case_ibd_2026-11-05/` | IBD: 22 genera reported by ≥2 papers; 16 comparable with BugSigDB signatures from outside the corpus; 12 agree (e.g. *Faecalibacterium*, *Roseburia*, *Coprococcus* decreased; *Escherichia*, *Veillonella*, *Streptococcus* increased); disagreements include *Bacteroides* and *Alistipes* |
| WS-7 length | authors | — | — |

Implications to discuss: the trained-tagger advantage over the best small LLM is shown on BC5CDR and BioRED as wholes (dataset level), and no difference was detected on organisms; the BugSigDB support gain from cleaning should be reported as a trend, the sentence-support (Q05) and reference (Q08) gains as significant.

## 12. Path to submission (2026-11-05)

Accepted by the project lead: the notes below are **notes for the authors to write from**. AI-drafted text is not
pasted into the manuscript (BiB policy).

### 12.1 Claim notes

| Claim | Basis to write from | Evidence |
|---|---|---|
| Species benchmark, overlap with training data | The S1000 test set is the 160 S800 test abstracts (standard split, Hakala et al. 2016) plus 40 new ones (S1000 paper; S800 split lists from github.com/spyysalo/s800). Neither tagger lists S1000 in its training data. **PubTator3 (AIONER):** its published training files (github.com/ncbi/AIONER, `SPECIES_Train`) contain **134 of the 200 S1000 test abstracts: seen in training**. PubTator3 scores 69.8 on those 134 and 71.9 on the other 66. On the 66 abstracts outside AIONER's training data, PubTator3 − Qwen 3-shot is +5.6 (95% CI −3.6 to 14.7, p 0.24). **HunFlair2:** trained on S800 via Flair's HUNER split. That split uses internal document numbers, and the original S800 archive needed to map them is unreachable, so its overlap is **not determined**: treat the 160 as possibly seen. On the 40 new abstracts: PubTator3 70.4, Qwen 3-shot 69.1, HunFlair2 65.8 (CIs about ±15). Wording to use: "an advantage for trained taggers on organisms was not established on abstracts outside their training data". Do not write "no advantage" | `ner_species_s1000/subset_s800_vs_new.json` (incl. `aioner_train_overlap`) |
| Trained taggers vs small LLMs | HunFlair2 vs Qwen3.5-4B 3-shot: +7.8 exact F1 on BC5CDR (chemicals and diseases together) and +14.4 on BioRED (six types); dataset level, not per entity type; HunFlair2 was trained on BC5CDR. Organisms (S1000 test): 63.2 vs 63.1 exact F1, difference +0.1 (95% CI −6.3 to 7.0, p 0.99): no difference detected, which is not the same as "on par"; HunFlair2 leads on relaxed F1 (78.3 vs 67.5, p < 0.001); PubTator3 leads both on exact F1 (70.5; +7.4 and +7.3, p ≤ 0.014). HunFlair2 and PubTator3 were trained on S800 (in-domain †). Corpus judged validity (L01–L04) is a separate result | `significance_2026-11-05` C; `ner_species_s1000/paired_tests.json` |
| X03 | Triples kept vs dropped by the cleaning (a comparison, not an effect of cleaning): 54.3% vs 44.3%, Fisher p 0.030, Holm 0.061, paper-level bootstrap p 0.08: a trend | `significance_2026-11-05` A |
| Q05, Q08 | Kept vs dropped: label supported by its sentence 30.6% vs 17.2% (p 3e-85); microbe–disease edge in a reference 15.5% vs 6.4% (Holm p 0.011; register Q08 says 15.4, correct to 15.5) | same |
| Judges | Sanity checks (96.4 / 6.2 / 90.6%) apply to the **Qwen** judge only. Do not call judged validity "conservative" or "precision". Qwen vs DeepSeek κ 0.283; Qwen 48.5% valid, DeepSeek 18.8% | `judge_sanity_qwen_2026-11-05`; `judge_agreement_2026-11-05` |
| Gazetteer | Established: no unique term; 228k mentions. No claim about a normalisation role | `source_ablation_2026-11-05` |
| Key Point on judges | Limit to the Qwen judge (or to both, if the DeepSeek sanity run in §12.2 is approved) | — |
| Data Availability | The bundle contains no code: code needs its own deposit and licence. For withheld papers the bundle also carries short extracted values. Concept labels only for allow-listed vocabularies (B23). Mention the leak checks only after all checks pass on the final bundle | §12.3 |
| IBD use case | **Exploratory (not pre-registered).** 22 genera (≥2 papers), 16 comparable, 12 agree with BugSigDB signatures from outside the corpus: 75.0% (Wilson 95% CI 50.5–89.8) vs 46.9% chance, one-sided binomial p 0.022; small n, state it. Chance method (as N05): P(same) = p_up(corpus) · p_up(BugSigDB) + p_down(corpus) · p_down(BugSigDB) over the 16 comparable genera | `use_case_ibd_2026-11-05` |

### 12.2 Decision for the project lead: DeepSeek sanity check

The manuscript uses DeepSeek-V4-Flash as the main judge, but only the Qwen judge was sanity-checked.

| Option | What it means |
|---|---|
| (a) recommended | Run the same controls (same 1,500 items, string + type, as in DeepSeek's original design) through DeepSeek. This is a new external-API run under the freeze. The items are short terms and fragments of at most 4 words, but SPAN fragments come from paper sentences, so use the CC BY / CC0 papers only, or confirm with the rights reviewer first |
| (b) | Report Qwen as the sanity-checked judge and DeepSeek as not sanity-checked |

**Status:** awaiting the answer to §12.4 item 4; if it is no, use option (b) and report DeepSeek as not sanity-checked. Awaiting the lead's choice. Prepared for (a): an identical control set built from **CC BY / CC0 papers only** (`judge_sanity_open_2026-11-05/`), so both judges are scored on the same items; **this run is the baseline for any DeepSeek comparison**. Both Qwen runs, different item sets, Wilson 95% CIs:

| Measure | All papers (28715502) | CC BY / CC0 only (28715742) |
|---|---|---|
| Vocabulary-confirmed terms judged valid | 96.4% [94.4–97.7] | 91.8% [89.1–93.9] |
| Type kept (positives) | 95.4% [93.2–96.9] | 93.8% [91.3–95.6] |
| Injected wrong type kept | 6.2% [4.4–8.7] | 3.8% [2.4–5.9] |
| Original type restored | 67.8% [63.6–71.7] | 69.2% [65.0–73.1] |
| Random fragments judged not a term | 90.6% [87.7–92.9] | 91.6% [88.8–93.7] |

The positive-control acceptance is 4.6 points lower on the CC BY / CC0 set (non-overlapping CIs); the other measures are within each other's CIs. DeepSeek has not been run. Note: the CC BY / CC0 papers were judged "candidates, not automatically authorised" for external APIs (licence scope and API terms to verify), so (a) also needs that confirmation (§12.4).

### 12.3 Release: B22 (text) and B23 (vocabulary labels)

- **B22:** rebuild `zenodo_r2` (SLURM 28715431). Rights scan with the new matching: 0 unexplained hits. The two regression checks are running.
- **B23:**
  - Builder option `--vocab-labels allowlist`, allow-list in `src/scripts/release/VOCABULARY_LABEL_ALLOWLIST.csv`. Every entry is PROPOSED with the provider's published licence; the rights reviewer confirms.
  - OMOP concepts are classified by their own `vocabulary_id`.
  - Dry run on CDM 3.0.3:
    - **kept 74,006 labels**: MeSH, NCIt, NCBI Taxonomy, ChEBI, GO, MONDO, PR, DOID;
    - **blanked 130,811**: UMLS 54,590; SNOMED CT 19,381 (+4,909 via OMOP); LOINC 7,950; MedDRA 2,374; OMIM 2,311; HPO 2,164; Read codes 1,730; RxNorm 2,085; NDDF 483; 10,027 unrecognised identifier forms; others.
  - Identifiers are always kept. Reversible: add a vocabulary to the list once confirmed.
- Final candidate: `zenodo_r3` (B22 and B23 fixes together), SLURM 28715683. It must pass:
  1. the rights scan;
  2. the source-side regression check, including the vocabulary-label check;
  3. the regression check reproducing the 1,308 on the frozen deposit.
- Then seal it with SHA-256. Do not upload before the licence decision and the legal answer.
- `zenodo_r2` validates the B22 fix only; it is **not** releasable, because concept labels were still exempt there.
- Further B23 checks (2026-11-05):
  1. **Labels outside the concept table:** none are copied from vocabularies. Values that equal a restricted label and are not in their own paper's text:
     - 69 triple labels, mostly normalised forms such as "humangut";
     - 2,305 body-site values, e.g. "feces";
     - 165 finding-domain values, e.g. "alpha diversity".

     These are the pipeline's own controlled words, not vocabulary content. Listed for the reviewer. The vocabulary-label check therefore covers the `concept` table, the only table holding vocabulary labels.
  2. **Later:** map the 451 phenomebrowser.net MeSH concepts to NLM MeSH IDs, so that they use the official (allow-listed) MeSH labels.
  3. **The 10,027 unrecognised identifiers come from about 20 other sources:** HGNC 961, ROR 712, OCHV 682, JST thesaurus 628, NCBI Gene 513, EFO 506, Orphanet 359, EDAM 339, LIPID MAPS, MIxS, WikiPathways, FMA and others. They stay blank; candidates for the reviewer. Only one group belongs to an allow-listed vocabulary: 451 labels from a MeSH copy (phenomebrowser.net). They are blanked in r3; add later if wanted.
  4. **Usability:** `rights/restore_vocab_labels.py`, shipped in the bundle and tested on synthetic data, fills empty labels from the user's own UMLS `MRCONSO.RRF` and/or OMOP `CONCEPT.csv`. The README explains it.

### 12.4 Legal / library request (one request)

1. **B1 / B22:** may we release, for the 179 withheld papers, identifiers, character offsets, normalised terms and short extracted values (no text)?
2. **B23:** which vocabularies' labels may be redistributed, under which licence? List the allow-list (8 PROPOSED) and the blanked vocabularies with counts.
3. **B2:** data licence (proposed CC BY 4.0 for the derived data), and a separate licence for the code deposit (MIT or Apache-2.0, authors to choose; B16).
4. **B24, all processing by external models (separate from redistribution).** Scope: every external run, not only withheld-paper strings.
   - **Every external run is in scope.** The CC BY / CC0 papers were judged "candidates, not automatically authorised" for external APIs (licence scope and API terms to verify).
   - **Runs:**

     | Run | What it received |
     |---|---|
     | DeepSeek-V4-Flash judge, external API, 2026-11-03 | 358,714 CDM term strings and the triple labels; no sentences |
     | DeepSeek-V4-Flash evidence check and relabelling, 2026-11-04 | sentences of CC BY / CC0 papers |
     | Claude spot checks, 2026-11-05 | 3,000 term strings; 500 triples with CC BY / CC0 sentences |
     | The AI coding assistant (Claude Code) during development | see below |

   - **Withheld papers as a sub-case:**
     - **All length bands, one method.** Counts only (`outputs/results/rights/B24_EXTERNAL_PROCESSING_INVENTORY_2026-11-05.json`). These figures are the ones to use in the legal request and the AI declaration.
     - **Method:** a string counts as withheld-only if all its 20-character windows occur in withheld text and at least one occurs in neither open text nor bibliographic metadata.
     - **Superseded figures:** the earlier 2,156 / 1,508 came from a quicker check. That check used 40-character windows and counted a string when any one window was exclusive, a different criterion, so its counts differ.

       | Run | Strings sent | Withheld-only, 20–49 chars | Withheld-only, ≥ 50 chars | Too short to attribute |
       |---|---:|---:|---:|---:|
       | DeepSeek judge, CDM term strings | 358,714 | 25,140 | 2,189 | 263,502 |
       | DeepSeek judge, triple labels | 51,576 | 5,017 | 1,460 | 28,199 |
       | Claude spot check, term strings | 3,000 | 238 | 0 | 2,195 |
       | Claude spot check, triple labels | 1,000 | 0 | 0 | 557 |

     - **Sentences sent externally:** DeepSeek evidence check (2026-11-03), 16,132; Claude triple spot check, 500; both all from CC BY / CC0 papers. **Exception, 2026-11-07:** the DeepSeek-V4.1-Flash triple screen sent 25,714 sentences via the Genie gateway, 9,629 of them from non-CC BY / CC0 papers [W01]; see CHANGE_RECORD and `B24_EXTERNAL_PROCESSING_ADDENDUM_2026-11-07.json`.
     - **Claude spot checks:**
       - The 3,000 terms included 238 withheld-only strings of 20–49 characters; strings of ≥ 50 characters were excluded by its protocol.
       - The 500 triples carried 1,000 labels (0 withheld-only in any band; 79 labels of ≥ 50 characters, none withheld-only) and 500 CC BY / CC0 sentences.
       - The project's agreed rule is that withheld-paper text of any length must not go to an external API. The 49-character limit concerns redistribution and is not a mitigation for processing.
   - **AI coding assistants:**
     - **Claude Code (Anthropic):**
       - **Confirmed:** during the 2026-11-05 leak investigation it displayed excerpts of about 20 strings found only in withheld papers (up to 110 characters each).
       - **Unknown:** what it saw in earlier sessions.
     - **OpenCode agent:**
       - Configured providers: the Fraunhofer Genie gateway (fhgenie.fraunhofer.de; OpenAI-compatible); default model `nvidia/GLM-5.2-NVFP4`, small model `deepseek-ai/DeepSeek-V4-Flash-0731`, and `Qwen/Qwen3-Coder-Next-FP8` also configured.
       - Its local session database lists 3 sessions on GLM-5.2 and 2 on DeepSeek-V4-Flash.
       - **Unknown:** whether it saw withheld text.
     - The DeepSeek-V4-Flash judge runs used the same Genie gateway. Whether an institutional gateway counts as external processing is part of the legal question.
   - **Local runs (not external):** the earlier DeepSeek mapping review (DeepSeek-R1-Distill on cluster vLLM); all Qwen runs.
   - **Questions:**
     - (i) was each external processing permitted;
     - (ii) may CC BY / CC0 text be sent to an external API (needed for §12.2 option a).
   - **To attach (the authors obtain them; not reconstructed here):** the terms that applied on the run dates, covering retention and training use, for:
     - the DeepSeek-V4-Flash access route (the institutional Genie gateway and the model provider);
     - Claude (the plan and terms under which the spot checks and the coding assistant ran).
   - Disclose all of the above in the AI declaration.

### 12.5 Critical path

1. `zenodo_r3`: all three checks at 0, then seal.
2. Legal answer (B1/B22, B23) and licences (data; separate code deposit).
3. DeepSeek sanity decision (§12.2), after the API question in §12.4 item 4.
4. Authors write and cut to ≤ 5,000 words (Key Points, the claim notes above, CDM 3.1 as future work).
5. Internal hostile review, then pre-submission enquiry, then Zenodo DOI, then preprint (after the legal answer), then submission.
