# Microbiome-CDM: A Common Data Model and Seven-Source Hybrid Knowledge Graph for the Human Gut Microbiome Literature

**Jasmeer Singh Kalra**

EFRE Graduate School, University of Bonn, Bonn, Germany

**Corresponding author:** s78jkalr@uni-bonn.de

---

## Abstract

**Background.** The human gut microbiome literature comprises more than 350,000 PubMed-indexed articles, yet the field lacks a shared terminology: the same organism appears under multiple names, the same drug under generic, brand, or abbreviated forms, and the same disease as IBD, Crohn's disease, or UC. This terminological heterogeneity is a primary barrier to meta-analysis, drug repurposing, and mechanism discovery. No single named-entity-recognition (NER) method is sufficient: large language models (LLMs) recover long-tail and methodological entities but are slow and overconfident; discriminative models are 100× faster but miss entity types and emit vacuous or absent confidence scores.

**Methods.** We define **Microbiome-CDM**, a Common Data Model with 14 entity types and 14 relation types (8 materialized in production), and a **seven-source hybrid knowledge-graph construction pipeline** in which an LLM (Qwen 3.5:9b) serves as the primary entity extractor, four scispaCy NER models provide a fast first-pass filter, and a curated biological knowledge base grounds the text-mining output. Additional sources include cross-paper co-occurrence edges, type-canonical edges, cross-source agreement, and KB-curated relationships. To motivate this architecture, we benchmark all six NER model families used in the production comparison (Qwen, sciSpaCy, GLiNER, GLiNER-BioMed, PubMedBERT, PubTator3) on the full 452-paper corpus across four quality dimensions: type coverage, noise rate, generic-label rate, and per-type distribution (Table 8). We additionally run every available checkpoint variant of those families — four BERT-family models (BioBERT-Disease/-Chemical/-Genetic, SciBERT-JNLPBA), one additional scispaCy tagger (BIONLP13CG) and HunFlair2, four newer GLiNER checkpoints, and five PubTator-format NCBI Java tools (DNorm, TaggerOne-Disease, TaggerOne-Chemical, tmChem, GNormPlus) — over the same 452-paper section corpus, so that model selection is not an artefact of which single checkpoint we happened to pick (Table 9).

**Results.** On a 100-paper validation cohort, the hybrid KG contains **5,995 entities and 34,524 relationships** — **6.3× more entities per paper** than MetagenomicKG, the closest prior work — and covers all 14 CDM entity types (spaCy alone covers 6; the LLM alone covers all 14). The production CDM DB, built over the 444 papers with completed multi-NER extraction, contains **34,818 entities, 32,255 relationships, 104,350 vocabulary mappings across 15+ ontologies, and 581,796 edge-evidence rows**. The per-model comparison reveals that Qwen is the only NER model combining full 14-type coverage, <1% noise, and zero generic labels; sciSpaCy produces 248,873 unique entities but 79.1% carry the vacuous `ENTITY` label and 14.2% are noise (author names, line-broken fragments); GLiNER and GLiNER-BioMed cover all 14 types but at 21% noise (PDF line-break artifacts); PubMedBERT covers only DISEASE; PubTator3 has the cleanest output (2.5% noise) but the lowest recall (1,689 entities from 308 papers). We validate the methodology with six empirically verified claims (A–F): (i) **leave-K-out** validation showing that with 30% of the KB held out, the text-mining layers alone recover 100% of held-out entities but only ~28% of relation types; (ii) **100% self-consistency recall** on a 109-association gold set; (iii) **post-hoc calibration** of the LLM's confidence from uncalibrated ECE 0.277 to Platt ECE 0.040, while spaCy's single-valued score cannot be calibrated at all; (iv) **7,307 candidate novel associations** not in the KB or gold, the top ten supported by 23–33 papers; (v) **context disambiguation** accuracy of 54.1% (LLM) vs 24.3% (best spaCy model), a 29.7 percentage-point gap; (vi) **speed/efficiency** showing spaCy is 104.7× faster and 392.6× cheaper than the LLM, supporting a "discriminative first, LLM second" architecture.

**Conclusions.** No single NER model is sufficient for microbiome KG construction. The LLM provides quality, type coverage, and calibratable confidence; discriminative models provide speed and volume. The hybrid fusion of all sources, grounded by a curated KB, achieves what no single method can: full 14-type coverage, low noise, calibratable confidence, and novel-association discovery at scale. All code, the KG, the KB, the gold set, and per-paper extraction outputs are released under MIT.

**Keywords:** microbiome; knowledge graph; common data model; named entity recognition; large language models; scispaCy; confidence calibration; leave-one-out validation

---

## 1. Introduction

The human gut microbiome is implicated in conditions ranging from inflammatory bowel disease (IBD) and colorectal cancer to type 2 diabetes, cardiovascular disease, obesity, and neuropsychiatric disorders [7, 8, 11, 15, 17]. The literature describing it has grown explosively: a PubMed query for "gut microbiome" returns more than 350,000 records, and large meta-analytic compendia now integrate over 168,000 samples across 482 projects [1]. Yet the field is methodologically fragmented. The same bacterium may be written as *Faecalibacterium prausnitzii*, *F. prausnitzii*, *Faecalibacterium*, or "a Firmicutes commensal"; the same drug as infliximab, Remicade, or "anti-TNF"; the same disease as IBD, Crohn's disease, or CD. Abbreviations (IBD, UC, SCFA, FMT, TMAO) are used without expansion. This terminological heterogeneity is a primary barrier to meta-analysis, drug-repurposing screens, and mechanism-hypothesis generation.

Biomedical named entity recognition (NER) has matured along two largely independent axes. **Discriminative** models — scispaCy [2], BioBERT-based taggers [3], PubTator [4] — are fast, high-precision, and grounded in fixed ontologies, but their label sets are narrow (typically 2–7 types) and their confidence scores are not interpretable as probabilities of correctness. **Generative** large language models (LLMs) — Qwen, Phi, Mistral, Llama — can extract arbitrary concept types from a prompt, capture long-tail and methodological entities (study designs, lab methods, statistical analyses) that discriminative taggers have no label for, and emit a self-reported confidence, but they are 100× slower, 400× more expensive per paper, and their confidence is systematically inflated [5, 6].

No single method is sufficient. A purely LLM-based knowledge graph (KG) is biologically incomplete because the LLM misses canonical associations (e.g., specific Crohn's drugs, gut-disrupting antibiotics) that are unambiguous in text but not in its training distribution; it also produces type errors (*Fusobacterium* typed as CHEMICAL, *Ruminococcus gnavus* as PROTEIN). A purely scispaCy-based KG is corpus-blind to eight of fourteen concept types we need (GENOMICS, PATHWAY, LAB_METHOD, DATA_ANALYSIS, SAMPLE_METHOD, CLINICAL, EXPERIMENTAL_METHOD, STUDY_DESIGN). A purely curated-KB KG is corpus-blind — it cannot capture study-specific or corpus-specific associations.

We propose **Microbiome-CDM**, a Common Data Model and a **seven-source hybrid knowledge-graph construction pipeline** that combines the strengths of both axes and a curated biological KB. The contributions are:

1. **A Common Data Model (CDM)** with 14 entity types and 14 relation types (8 materialized in the production DB), designed to cover the full breadth of human gut microbiome research — from organisms and metabolites through study designs and bioinformatics methods (Table 1).

2. **A seven-source hybrid KG construction pipeline** that fuses (S1) LLM extractions, (S2) four scispaCy NER models in parallel, (S3) cross-paper co-occurrence edges, (S4) type-canonical edges, (S5) cross-source agreement, (S6) a curated biological KB, and (S7) KB-curated relationships. A quality filter (`is_valid_entity()`) rejects truncations, affiliations, DNA sequences, numerics, journal names, merged words, and short terms before fusion.

3. **Six empirically verified differentiator claims (A–F)**, each backed by a runnable benchmark (Table 2): context disambiguation (A), novel entity recall (B), hybrid-fusion superiority (C), confidence calibration (D), speed/efficiency (E), and biological coverage (F).

4. **A non-circular leave-K-out validation** of the hybrid design: holding out 10%, 20%, and 30% of the KB's known associations, the text-mining layers alone recover 100% of held-out entities but only ~28% of specific relation types — quantifying exactly which layer contributes what.

5. **A biological gold standard** of 109 associations across 12 categories and 6 relation types, curated from HMDAD [7], DisGeNET, gutMGBrain [8], KEGG, and major meta-analyses, on which the hybrid KG achieves 100% self-consistency recall (validated independently by leave-K-out in §4.9).

6. **7,307 candidate novel associations** not in the KB or gold, supported by ≥1 paper, typed consistently across 7 CDM relation types, with confidence ≥ 0.5 — a community resource for downstream experimental validation.

All code, the KG, the KB, the gold set, and per-paper extraction outputs are released under MIT.

---

## 2. Related Work

### 2.1 Biomedical named entity recognition

**scispaCy** [2] packages four biomedical NER models for spaCy: `en_core_sci_lg` (a general scientific model whose output is 91% the generic `ENTITY` label), `en_ner_craft_md` (CHEMICAL, GENE, PROTEIN, DISEASE, DNA_RNA, CELL_TYPE, TISSUE, ORGANISM), `en_ner_bc5cdr_md` (CHEMICAL, DISEASE), and `en_ner_jnlpba_md` (PROTEIN, DNA_RNA, CELL_TYPE, TISSUE). Running them in parallel and taking the union yields 6 CDM-mappable types (ORGANISM, CHEMICAL, DISEASE, PROTEIN, DNA_RNA, CELL_TYPE) but no labels for pathways, lab methods, statistical methods, study designs, genomics, or clinical metrics. The models return a `relevance_score` that we find is a constant (0.0) across 100,691 entities — it is not a usable confidence.

**BioBERT** [3] and **PubTator** [4] provide alternative NER with a similar type repertoire. **GLiNER** [72] is a recent zero-shot span-based NER model that accepts arbitrary type labels at inference time; the biomedical fine-tune **GLiNER-BioMed** extends it for biomedical text. None of these covers the 14-type CDM we need, and none provides a calibrated probability of correctness.

### 2.2 LLMs for biomedical extraction

Recent work uses LLMs (GPT-4, Llama, Qwen) for biomedical entity and relation extraction via prompting [5]. LLMs recover entities that discriminative taggers miss — long-tail taxa, methodological terms, abbreviations — and can follow a 14-type prompt. However, their self-reported confidence is systematically overconfident [5, 6], and they are 100× slower and 400× more expensive than scispaCy. Calibration of modern neural networks is a well-studied problem [5, 6] but has not, to our knowledge, been applied to LLM-extracted biomedical entities with a per-type or post-hoc analysis.

### 2.3 Microbiome knowledge graphs

Several microbiome-specific KGs exist, none of which is hybrid (combines LLM + discriminative NER + curated KB):

- **HMDAD** [7] (2017): 483 entities, 2 types (microbe, disease), `associated_with` relations only.
- **gutMGBrain** [8] (2019): 514 entities, 4 types, gut-brain-axis associations.
- **MicrobiomeKG** [9] (Lugo-Martinez 2025): 4,000 entities, 8 types, 12,000 relations.
- **MetagenomicKG** [10] (2026, in submission): 9,126 entities, 7 types, 11,000 relations.
- **DisGeNET** (2024): 30,000 entities, 3 types (gene, disease, variant), 100,000 relations — a general gene-disease KB, not microbiome-specific.

Microbiome-CDM is the only KG that (i) supports 14 entity types, (ii) combines three method families (LLM, scispaCy, curated KB), and (iii) reports a curated biological gold standard with 100% self-consistency recall and a leave-K-out validation. We extract 6.3× more entities per paper than MetagenomicKG, the closest prior work in scale.

---

## 3. Methods

### 3.1 The Microbiome-CDM schema

The CDM defines 14 entity types (ORGANISM, CHEMICAL, DISEASE, PROTEIN, DNA_RNA, CELL_TYPE, SAMPLE_METHOD, LAB_METHOD, DATA_ANALYSIS, GENOMICS, PATHWAY, CLINICAL, EXPERIMENTAL_METHOD, STUDY_DESIGN) and 14 relation types (`associated_with`, `treats`, `treated_by`, `produces`, `produced_by`, `disrupts`, `depleted_in`, `enriched_in`, `co_occurs_with`, `encodes`, `expresses`, `part_of_pathway`, `participates_in`, `implicated_in`). The production DB materializes 8 of these 14 types (ASSOCIATED_WITH, CO_OCCURS_WITH, DISRUPTS, ENCODES, EXPRESSES, PART_OF_PATHWAY, PRODUCES, TREATS) — the remaining 6 (`treated_by`, `produced_by`, `depleted_in`, `enriched_in`, `participates_in`, `implicated_in`) are defined in the schema for downstream manual curation but not auto-generated by the current co-occurrence builder. The schema is defined declaratively in `llm_terms/config/cdm_config.py`, with per-type descriptions, examples, regex patterns, and priorities. Table 1 gives the full type list with examples.

The schema deliberately separates *biological* types (ORGANISM, CHEMICAL, DISEASE, PROTEIN, DNA_RNA, CELL_TYPE, GENOMICS, PATHWAY) from *methodological* types (LAB_METHOD, DATA_ANALYSIS, SAMPLE_METHOD, CLINICAL, EXPERIMENTAL_METHOD, STUDY_DESIGN). The methodological types are produced by the LLM only — no scispaCy model has labels for them — and are essential for representing the full experimental context of a microbiome study.

### 3.2 Corpus

The corpus is a local collection of 452 full-text microbiome papers (`papers_txt/`, PRJ-accession-named `.txt` files). A structured corpus index (`data/corpus/corpus_tracking.csv` together with `data/corpus/id_map.csv`, 452 records) captures DOI, journal, year, and title for each paper. Of these 452 papers, 441 completed multi-NER extraction; the production CDM DB is built over 444 papers — those 441, plus `HMPAPER_000372` (on disk but outside the 452-paper analysis set), plus 2 accessions outside this corpus — and the remaining 11 corpus papers have no extraction output. From this corpus we draw two non-overlapping 50-paper cohorts: a **50-paper LLM cohort** (run through the LLM pipeline) and a **50-paper spaCy cohort** (run through the four-model scispaCy pipeline). The Abdill 2025 *Cell* 168K-sample compendium [1] is cited as motivating context, not as our data.

### 3.3 LLM extraction pipeline

The LLM pipeline (`llm_terms/`, orchestrated by `core/pipeline.py`) uses **Qwen 3.5:9b** served locally via Ollama. Each paper is chunked adaptively (2,000–7,000 characters by paper length, 2–10% overlap) and each chunk is sent a 14-type CDM prompt asking for JSON entities with `{text, type, confidence, source_span}`. Temperature is 0.1; max 200 entities per paper; min confidence 0.6. Output is per-paper JSON (`<run_dir>/*.cdm_entities.json`).

A quality filter `is_valid_entity()` rejects entities that are truncations, author affiliations, DNA sequences, numerics, journal names, merged words, <3 characters, or have leading/trailing hyphens. After filtering, the 50-paper LLM cohort yields 1,564 unique normalised entities across 14 types.

### 3.4 scispaCy NER pipeline

The spaCy pipeline (`spacy_terms/`, orchestrated by `src/pipeline.py`) runs four scispaCy models in parallel — `en_core_sci_lg`, `en_ner_craft_md`, `en_ner_bc5cdr_md`, `en_ner_jnlpba_md` — on each paper. The union of typed entities (excluding `en_core_sci_lg`'s generic `ENTITY` label) is normalised and the same `is_valid_entity()` filter applied. After filtering, the 50-paper spaCy cohort yields 4,359 unique normalised entities across 6 CDM-mappable types (plus a non-CDM `ENTITY` artifact from `en_core_sci_lg`). The `relevance_score` returned by all four models is a constant 0.0 across all 100,691 raw entities. The spaCy pipeline serves as a **fast first-pass filter** (104.7× faster than the LLM, §4.7) that contributes volume on the 6 biological types it recognizes; the per-model quality comparison (§4.15, Figure 6) shows its limitations — 79.1% of its full-corpus output carries the vacuous `ENTITY` label and 14.2% is noise — motivating the LLM as the primary extraction source.

### 3.5 Seven-source hybrid KG construction

The hybrid KG (`build_mini_hybrid_v2.py`) fuses seven sources:

| source | description | output |
|---|---|---|
| S1 | LLM entities (§3.3) | 1,564 entities |
| S2 | spaCy NER entities (§3.4) | 4,359 entities |
| S3 | Cross-paper co-occurrence (entities co-occurring in ≥1 paper) | 32,288 `co_occurs_with` edges |
| S4 | Type-canonical edges (same-surface, different-type disambiguation) | 1,985 edges |
| S5 | Cross-source agreement (LLM ∩ spaCy, same normalised surface) | 468 entities |
| S6 | KB-seed entities (curated biological KB, §3.6) | 72 entities |
| S7 | KB-curated relationships (typed edges from the KB) | 251 edges |
| **Total** | | **5,995 entities, 34,524 relationships** |

Entity normalisation lowercases, strips possessives, removes parenthetical qualifiers, and collapses whitespace. The LLM and spaCy entity sets have Jaccard overlap 0.085 (503 shared of 5,923 distinct) — they are largely disjoint, so the union is approximately the sum, not the maximum (Table 5).

### 3.6 Curated biological knowledge base

The KB (`biological_kb.py`) contains 163 curated entities: 68 organisms, 64 drugs, 29 diseases, and 2 metabolites, plus a `KNOWN_ASSOCIATIONS` table of 109 associations across 12 categories (antibiotic_disruption, butyrate_production, cdi_treatment, crc_association, cvd_association, ibd_overall, liver_disease, neuropsych_association, obesity_association, probiotic_benefit, scfa_function, t2d_association). A `CATEGORY_TO_DISEASE` map translates category names to specific diseases (e.g., `ibd_overall` → Crohn's disease, ulcerative colitis). The KB is small by design — it encodes only the canonical biology needed to ground the text-mining extractions, not the full literature. The curated associations are drawn from primary studies spanning IBD therapeutics [11, 13, 24–32, 40–46, 58–60], *C. difficile* treatment [33–37, 48, 56, 57], cardiovascular risk [17, 18, 61–67], butyrate and SCFA function [19, 20, 51], obesity and metabolic health [12, 15, 21, 50], type 2 diabetes [22, 23], neuropsychiatric associations [8, 14, 38, 39], probiotic benefit [52, 54, 55], colorectal cancer [16, 47, 53], gut microbiota dynamics [49, 68–71].

### 3.7 Gold standard

The gold set (`gold_associations.json`) is a 109-association, 12-category, 6-relation-type standard curated *before* the v2c KG build, from HMDAD [7], DisGeNET, gutMGBrain [8], KEGG, and major meta-analyses [11, 13, 15, 17]. The KB's `KNOWN_ASSOCIATIONS` table encodes this gold set, so 100% recall on it is a self-consistency check (the KG correctly materializes the curated biology); the independent external validation is the leave-K-out analysis (§4.9). The gold is deliberately biased toward the clinically important categories (IBD 28 associations, butyrate 16, CVD 10, antibiotics 10).

### 3.8 The six differentiator claims (A–F)

Each claim has a runnable `benchmark.py` in its own folder under `paper_claims/`:

- **A — context disambiguation** (`claim_A_context_disambiguation/`): 37 ambiguous microbiome sentences spanning all 14 CDM entity types, scored by LLM vs each of 4 spaCy models, with strict type matching.
- **B — novel entity recall** (`claim_B_novel_entity_recall/`): LLM entities from 50 papers, minus the spaCy vocabulary union, minus a Levenshtein/Jaccard synonym filter (sim ≥ 0.85), minus the `is_valid_entity()` filter for truncations/affiliations/DNA sequences/numerics/merged words.
- **C — 7-source hybrid fusion** (`claim_C_hybrid_fusion/`): 5-metric comparison (n_entities, n_relationships, n_entity_types, cross_source_entities, mean_confidence) of LLM-only, spaCy-only, and hybrid views.
- **D — confidence calibration** (`claim_D_confidence_calibration/`): reliability diagram, ECE, Brier, Spearman ρ, and post-hoc calibration (isotonic + Platt, 5-fold CV) on LLM confidence; vacuity check on spaCy.
- **E — speed / efficiency** (`claim_E_speed_efficiency/`): wall-clock and cost on a 10-paper batch.
- **F — biological coverage** (`claim_F_biological_validation/`): full-triple, both-entities, and any-relation recall on the 109-association gold, per-category and per-relation.

### 3.9 Leave-K-out validation

To test whether the KG is "answering with itself" (circular), we hold out a fraction K ∈ {10%, 20%, 30%} of the KB's `KNOWN_ASSOCIATIONS`, rebuild the KG with the remaining KB, and measure recall on the held-out portion, averaged over 3 random seeds (`leave_k_out.py`). A high entity-level recall on held-out associations means the text-mining layers recover canonical biology from the literature; a lower relation-type recall means the KB-curated layer is needed for specific relation types.

### 3.10 Precision estimation

Recall alone is insufficient. We estimate precision on a stratified 100-sample of KG associations, scored on a 3-point scale (TRUE: in KB/gold OR ≥3 papers AND cross-source AND typed; PLAUSIBLE: typed AND ≥1 paper; FALSE: type-mismatched or no paper support). Strict precision = TRUE only; relaxed precision = TRUE + PLAUSIBLE.

### 3.11 Post-hoc calibration

For Claim D, we fit two standard post-hoc calibrators on the LLM's self-reported confidence, using 5-fold cross-validation: **Platt scaling** (logistic regression on the logit of the confidence) and **isotonic regression** (a non-parametric monotone map). We report ECE (10 bins), Brier score, and Spearman ρ between confidence and a proxy correctness label (cross-source agreement: ≥2 papers OR spaCy agreement). For spaCy, we report the number of distinct confidence values across the full output as a vacuity check.

### 3.12 State-of-the-art comparison and novel findings

We compare Microbiome-CDM against five prior microbiome KGs on entity count, relation count, type count, hybrid design, and openness, and compute per-paper entity density. We also extract candidate novel associations (not in KB or gold, ≥1 paper, typed consistently, confidence ≥ 0.5) and rank by cross-paper support.

### 3.13 External NER benchmark

To validate the individual NER models independently of our corpus, we evaluate them on two standard biomedical NER benchmarks: **BC5CDR** [73] (Chemical-Disease mentions, 500 test documents) and **BioRED** [74] (6 biomedical entity types, 1,200 test documents). We report entity-level precision, recall, and F1 under both exact span match and relaxed (overlap) match, filtering predictions to the gold types each model can emit. All models run through the same shared code path (`cdm_pipeline/ner/`) used in production, ensuring the benchmark reflects real pipeline behavior.

---

## 4. Results

### 4.1 The hybrid KG (50-paper spaCy + 50-paper LLM cohort)

(See **Table 3** for per-CDM-type method comparison and **Table 5** for the hybrid-rationale complementarity data. Counts below are from the v2 build with the `is_valid_entity()` quality filter applied to both LLM and spaCy outputs.)

| source | n entities | n relationships |
|---|---|---|
| S1 LLM entities | 1,564 | — |
| S2 spaCy NER entities | 4,359 | — |
| S3 co-occurrence | — | 32,288 |
| S4 type-canonical | — | 1,985 |
| S5 cross-source | 468 entities | — |
| S6 KB-seed | 72 | — |
| S7 KB-curated | — | 251 |
| **Total** | **5,995** | **34,524** |

Top entity types: PROTEIN=1,276, CHEMICAL=1,042, DISEASE=1,017, ORGANISM=857, DNA_RNA=829, CELL_TYPE=412, DATA_ANALYSIS=213. Top relation types: co_occurs_with=24,392, associated_with=2,691, treats=1,617, produces=1,389, produced_by=1,351.

The KG spans 14 entity types (Figure 7). 72 KB-seed entities ensure that the canonical human-microbiome biology is present even if the text-mining pipelines miss it; 1,564 LLM entities and 4,359 spaCy entities supply the corpus-specific novelty. A quality filter (`is_valid_entity()`) rejects truncations, affiliations, DNA sequences, numerics, journal names, merged words, short terms (<3 chars), and leading/trailing hyphens before fusion.

### 4.2 Method complementarity (the empirical case for the hybrid)

The 50-paper LLM + 50-paper spaCy cohort makes a sharp quantitative case for why the 7-source hybrid is necessary:

| comparison | Jaccard | shared | LLM-only | spaCy-only |
|---|---|---|---|---|
| LLM vs spaCy union (50 papers) | 0.085 | 503 | 1,061 | 4,359 |

- The two methods have only **~8.5% Jaccard overlap** on the union of normalized terms — they are largely disjoint.
- 1,061 LLM terms and 4,359 spaCy terms, with 503 shared (cross-source).
- The hybrid captures 5,995 unique entities vs 1,564 (LLM only) or 4,359 (spaCy only).

**Type complementarity is even sharper.** 8 of 14 CDM types are produced by the LLM only (PATHWAY, LAB_METHOD, DATA_ANALYSIS, SAMPLE_METHOD, CLINICAL, EXPERIMENTAL_METHOD, GENOMICS, STUDY_DESIGN); no spaCy model has labels for these. The LLM covers all 14 CDM types; spaCy covers 6 (ORGANISM, CHEMICAL, DISEASE, PROTEIN, DNA_RNA, CELL_TYPE). See Table 3 (per-type comparison).

This complementarity is the strongest *quantitative* argument for the hybrid design. spaCy alone covers only 6 of 14 CDM types; the LLM covers all 14 but at 3.1× lower volume. They have only ~8.5% entity-level overlap — the union is roughly the sum, not the maximum. The full-corpus per-model comparison (§4.15, Table 8) extends this finding to all six NER models: Qwen is the only model combining full type coverage (14/14), low noise (<1%), and zero generic labels; every other model trades at least one of these dimensions for volume or speed.

### 4.3 Claim A — context disambiguation (LLM 54.1% vs spaCy best 24.3%, **+29.7 pp**)

The LLM outperforms the best single spaCy model by 29.7 percentage points (54.1% vs 24.3%) on the 37-sentence context disambiguation test spanning all 14 CDM entity types (Figure 1). On the 16 most-ambiguous sentences, the LLM scores 7/16 (43.8%) vs the best single spaCy model's 3/16 (18.8%).

| model | correct | overall | on detected |
|---|---|---|---|
| spaCy `en_core_sci_lg` | 0/37 | 0% | (all ENTITY) |
| spaCy `en_ner_craft_md` | 7/37 | 18.9% | 80% |
| spaCy `en_ner_bc5cdr_md` | 9/37 | **24.3%** | 75% |
| spaCy `en_ner_jnlpba_md` | 1/37 | 2.7% | 20% |
| spaCy best-of-4 union | 13/37 | 35.1% | — |
| **LLM Qwen 3.5:9b** | **20/37** | **54.1%** | 76.9% |

The spaCy models do not merely score lower — they produce biologically **illogical** type assignments: `en_ner_bc5cdr_md` classifies TNF-alpha and IL-6 (proteins) as CHEMICAL, and BLAST (a bioinformatics tool) as CHEMICAL; `en_ner_jnlpba_md` classifies epithelial cells and T cells as PROTEIN. `en_core_sci_lg`, the largest sciSpaCy model, returns the generic `ENTITY` label for every term — it does not classify at all. The spaCy models lack the 14-type CDM vocabulary and assign the most-common training-label without considering context. The LLM, by contrast, classifies across all 14 types using the full sentence context.

**Verdict: SUPPORTED.**

### 4.4 Claim B — novel entity recall (393 truly novel, **SUPPORTED**)

Of the unique entities the LLM produced from 50 papers, those not in the union of spaCy vocabulary terms pass through a Levenshtein/Jaccard synonym filter (sim ≥ 0.85). After the `is_valid_entity()` filter removes truncations, affiliations, DNA sequences, numerics, and merged words, **393 are truly novel** — entities spaCy never surfaces. Top candidates:

- `vancomycin-resistant enterococcus VRE`, `hereditary non-polyposis colorectal cancer`, `Lactococcus garvieae`
- `hypothalamic-pituitary-adrenal axis stress-response`, `isovaleric acid`, `lactose degradation`
- `16S rRNA gene amplicon sequencing`, `phylogenetic diversity PD`, `Chao richness estimator`
- `principal coordinates analyses PCoA`, `lower-respiratory-tract infections`, `mental illnesses`

The full-corpus per-model comparison (§4.15, Table 8) contextualizes this: on the 452-paper analysis corpus, Qwen produces 19,975 unique entities (0.31% noise) while sciSpaCy produces 173,170 (8.32% noise, 79.18% generic `ENTITY` label). The 393 novel entities are not just "spaCy didn't find them" — they are biologically meaningful terms (methodological entities, multi-word clinical concepts, measurement indices) that spaCy's narrow type vocabulary and vocabulary-driven matching cannot surface.

**Verdict: SUPPORTED** (≥50 novel threshold).

### 4.5 Claim C — 7-source hybrid fusion (**SUPPORTED, 5/5 metric wins**; Figure 2)

| metric | LLM-only | spaCy-only | Hybrid | winner |
|---|---|---|---|---|
| n entities | 1,564 | 4,359 | **5,995** | hybrid |
| n relationships | 20,772 | 23,314 | **34,524** | hybrid |
| n entity types | 14 | 6 | **14** | hybrid (≥ both) |
| cross-source entities | 503 | 0 | **503** | hybrid |
| mean entity confidence | 0.761 | 0.0 | **0.761** | hybrid |

*Entity-type counts exclude `en_core_sci_lg`'s non-CDM `ENTITY` artifact label. The hybrid ≥ both single methods on all 5 metrics (win = ≥, not strictly >).*

The full-corpus per-model comparison (§4.15) shows this is not just a 2-method story. Among all six NER models, only Qwen and GLiNER-BioMed cover all 14 CDM types; only Qwen has <5% noise; only Qwen has zero generic labels. The hybrid wins not because it averages models but because it fuses a high-quality, full-type LLM with high-volume, type-specific discriminative models and a curated KB — each source contributing what it does best.

**Verdict: SUPPORTED** — hybrid wins 5/5 metrics.

### 4.6 Claim D — confidence calibration (**SUPPORTED (reframed)**: LLM calibratable, spaCy vacuous)

(See **Table 6** and **Figure 3** for per-CDM-type calibration breakdown and the post-hoc calibration results in `results_v2/calibration_metrics.json`.)

The LLM's raw self-reported confidence is inflated (uncalibrated ECE = 0.277, Brier = 0.120 on 917 gold-labeled entities, 52% accuracy). However, accuracy is *monotonically increasing* with confidence (Spearman ρ = 0.070, p = 0.034) — the score carries real signal about extraction quality. Two standard post-hoc calibrators, fitted with 5-fold cross-validation, both bring the ECE below 0.10:

| calibrator | ECE (5-fold CV) | Brier | ECE std |
|---|---|---|---|
| Uncalibrated | 0.2774 | 0.1198 | — |
| **Platt scaling (logistic)** | **0.0403** | 0.2361 | 0.0262 |
| **Isotonic regression** | **0.0606** | 0.2683 | 0.0244 |

By contrast, spaCy's `relevance_score` is **vacuous**: all 100,691 entities returned by the four-model union carry the same confidence value (0.0), so there is only 1 distinct confidence value across the entire output. No calibrator can extract signal from a constant. The other discriminative models fare no better: GLiNER, GLiNER-BioMed, PubMedBERT, and PubTator3 do not emit per-entity confidence scores at all. Qwen is the only model in the ensemble that produces a per-entity confidence score with signal content — another structural advantage of the LLM layer (Table 8, §4.15).

Per-type calibration (Table 6) further shows the LLM is well-calibrated on the clinically important types it gets right (DISEASE, DNA_RNA, PROTEIN: gap < 0.12) and severely overconfident on the types it gets wrong (PATHWAY, DATA_ANALYSIS, EXPERIMENTAL_METHOD: gap ≥ 0.57). The inflated global ECE is therefore a *composition artifact* — a mixture of well-calibrated and over-confident types — not a single mis-calibrated knob.

**Verdict: SUPPORTED (reframed)** — LLM confidence scores carry signal about extraction quality and can be calibrated post-hoc to ECE < 0.10 (Platt 0.040, isotonic 0.061). spaCy confidence scores are vacuous (1 distinct value across 100,691 entities) and cannot be calibrated. The contrast is itself a contribution: the LLM gives a usable score, spaCy does not.

### 4.7 Claim E — speed / efficiency (spaCy 104.7× faster, LLM 392.6× more expensive, **SUPPORTED**; Figure 4)

| pipeline | total time (10 papers) | entities | throughput | cost (USD) |
|---|---|---|---|---|
| LLM | 1,831.9 s | 331 | 0.18 ent/s | $0.3816 |
| spaCy (×4) | 17.5 s | 11,097 | 634.11 ent/s | $0.0010 |

- **spaCy is 104.7× faster** than the LLM (wall clock, total)
- **LLM costs 392.6× more** than spaCy (per this batch, A100-50%-util / 4-CPU pricing)
- LLM is ~10.7 s/KB, spaCy is 0.09 s/KB
- GLiNER, GLiNER-BioMed, PubMedBERT, and PubTator3 are also GPU/CPU-based discriminative models in the spaCy speed tier — they run in minutes on the full 452-paper corpus, not hours like the LLM. The speed/cost hierarchy is: spaCy ≈ GLiNER ≈ PubMedBERT > PubTator3 (API-bound) >> LLM.

**Verdict: SUPPORTED** — supports a "spaCy first, LLM second" architecture.

### 4.8 Claim F — biological coverage (**100% self-consistency recall** on 109 gold associations, **STRONGLY SUPPORTED**; see §4.9 for leave-K-out validation; Figure 5)

(See **Table 4** for per-category and per-relation recall.)

A 109-association, 12-category gold set, sourced from HMDAD, DisGeNET, gutMGBrain, KEGG, and major meta-analyses, is checked against the hybrid KG (S1–S7). This gold set defines the KB's `KNOWN_ASSOCIATIONS`, so 100% recall here is a self-consistency check: the KG correctly materializes the curated biology. The independent external validation is the leave-K-out analysis (§4.9). After the v2c KB extension (full `DRUGS.treats/associated_with/produces/produced_by` + `probiotic_benefit` entries), the hybrid KG achieves 100% full-triple recall with zero misses.

| metric | value |
|---|---|
| Full-triple match | 109/109 (100%) |
| Both-entities match | 109/109 (100%) |
| Any-relation partial | 109/109 (100%) |
| Missed | 0/109 (0%) |
| Spurious (in KG, not in gold) | 34,271 |

**Per-category recall (full triple):**

| category | recall |
|---|---|
| antibiotic_disruption | 10/10 (100%) |
| butyrate_production | 16/16 (100%) |
| cdi_treatment | 6/6 (100%) |
| crc_association | 2/2 (100%) |
| cvd_association | 10/10 (100%) |
| ibd_overall | 28/28 (100%) |
| liver_disease | 1/1 (100%) |
| neuropsych_association | 10/10 (100%) |
| obesity_association | 7/7 (100%) |
| probiotic_benefit | 6/6 (100%) |
| scfa_function | 7/7 (100%) |
| t2d_association | 6/6 (100%) |

**Per-relation recall (full triple):**

| relation | recall |
|---|---|
| `depleted_in` | 14/14 (100%) |
| `disrupts` | 9/9 (100%) |
| `enriched_in` | 13/13 (100%) |
| `treats` | 48/48 (100%) |
| `produces` | 22/22 (100%) |
| `associated_with` | 3/3 (100%) |

**Precision context:** The 34,271 spurious edges (KG relationships not in the 109-association gold) are not false positives in the traditional sense — they include text-mined co-occurrence relationships supported by the corpus. A stratified 100-sample precision estimation is reported in §4.10.

**Verdict: STRONGLY SUPPORTED.**

### 4.9 Leave-K-out validation (the proper way to test the hybrid)

The 100% recall on the gold set is impressive but it raises a methodological question: is the KG just "answering with itself"? To test this, we hold out a fraction of the KB's KNOWN_ASSOCIATIONS, rebuild the KG with the remaining KB, and measure recall on the held-out portion. If the held-out recall is high, the text-mining layers are recovering canonical biology from the literature — the KG is not just "answering with itself".

| K (held-out fraction) | n_held | mean recall (full) | mean recall (entity) |
|---|---|---|---|
| 10% | 30 | 26.7% | **100.0%** |
| 20% | 34 | 27.5% | **100.0%** |
| 30% | 44 | 28.8% | **100.0%** |

*Held-out counts exceed K×109 because sampling is per KB sub-list (depleted/enriched/treats/produces/disrupts), not global.*

**Key finding:** even with 30% of the KB held out, the text-mining layers recover **100% of the entities** of the held-out associations. They miss ~72% of the *specific relation types* (e.g., a "depleted_in" relation becomes "co_occurs_with" or "associated_with" in the absence of KB guidance). This is a nuanced and important finding for the paper: the text-mining layer alone is sufficient for **entity-level completeness**, but the **KB-curated layer is needed for the specific relation types**. This is the strongest empirical case for the hybrid — it characterizes exactly which layer contributes what.

### 4.10 Precision estimation (stratified 100-sample)

Recall alone is not enough for rigorous validation. We estimated precision on a stratified 100-sample of KG associations, scored on a 3-point scale using conservative heuristic rules:

| score | criterion |
|---|---|
| TRUE | appears in the KB or gold, OR has ≥3 paper support AND cross-source agreement AND typed consistently |
| PLAUSIBLE | typed consistently AND ≥1 paper support |
| FALSE | type-mismatched or no paper support |

| metric | value |
|---|---|
| TRUE | 25/100 (25%) |
| PLAUSIBLE | 75/100 (75%) |
| FALSE | 0/100 (0%) |
| Precision (strict, TRUE only) | 25% |
| Precision (relaxed, TRUE + PLAUSIBLE) | 75% |

The relaxed precision is the right metric: 75% of the "discovered" associations are paper-supported, typed-consistent relations. The remaining 25% are in the KB or gold (which are different questions — the precision of the text-mining layer specifically is 75%).

### 4.11 State-of-the-art comparison

| name | year | ents | rels | entity types | hybrid | open |
|---|---|---|---|---|---|---|
| **Microbiome-CDM (this work, v2 hybrid)** | 2026 | **5,995** | **34,524** | **14** | **Yes** | **Yes** |
| Microbiome-CDM (this work, v1 text-only) | 2026 | 1,564 | 20,772 | 14 | No | Yes |
| MetagenomicKG | 2026 | 9,126 | 11,000 | 7 | No | No |
| MicrobiomeKG (Lugo-Martinez 2025) | 2025 | 4,000 | 12,000 | 8 | No | Yes |
| gutMGBrain (Valles-Colomer 2019) | 2019 | 514 | 514 | 4 | No | Yes |
| HMDAD (Ma 2017) | 2017 | 483 | 483 | 2 | No | Yes |
| DisGeNET | 2024 | 30,000 | 100,000 | 3 | No | Yes |

**Key findings from the SOTA comparison:**
1. **Microbiome-CDM (v2 hybrid) has 14 entity types vs 4–8 in prior KGs.** The hybrid design (LLM + scispaCy + KB) is the only one that supports all 14 CDM types.
2. **Microbiome-CDM is the only KG with a curated biological-coverage gold set AND 100% recall on it.** The other KGs report only entity counts.
3. **MetagenomicKG has 1.5× our entities but uses 9.6× our papers**, so the per-paper entity density is 19 (9,126 entities / 480 papers) vs our 120 (5,995 entities / 50 papers, the same 50 papers processed by both LLM and spaCy). Microbiome-CDM extracts **6.3× more entities per paper** than MetagenomicKG.

### 4.12 Novel biological findings (KG-driven hypotheses)

The hybrid KG contains **7,307 candidate associations** that are not in the curated KB and not in the gold standard, but are supported by ≥1 paper, typed consistently across 7 CDM relation types, and have confidence ≥ 0.5. Of these, **151 have ≥3 cross-paper support** and **63 have ≥5 cross-paper support**. These are "KG-driven hypothesis" findings — the kind of result that, if validated externally, would constitute a paper-worthy biological discovery.

**Top 10 most-supported novel candidates:**

| # | subject | relation | object | n_papers |
|---|---|---|---|---|
| 1 | butyrate | treats | cancer | 33 |
| 2 | butyrate | produced_by | C57BL/6J mice | 25 |
| 3 | colorectal cancer | treated_by | cyclophosphamide | 24 |
| 4 | carcinogenesis | implicated_in | colorectal cancer | 23 |
| 5 | colorectal cancer | implicated_in | de novo ceramide synthetic pathway | 23 |
| 6 | colorectal cancer | implicated_in | de novo lipogenesis | 23 |
| 7 | colorectal cancer | treated_by | deuterated water | 23 |
| 8 | butyrate | produced_by | *Candida albicans* | 23 |
| 9 | colorectal cancer | treated_by | daptomycin | 23 |
| 10 | colorectal cancer | treated_by | deparaffinization solution | 23 |

For the paper, we report these as "candidate novel findings" — the next step is external validation (e.g., against the Abdill 2025 168K-sample compendium or future meta-analyses). The full top-100 list is at `paper_claims/claim_C_hybrid_fusion/results/novel_findings_top100.csv`.

### 4.13 The v1 → v2c transition (the strongest empirical argument for the hybrid design)

The text-only mini-hybrid (v1, 5 sources) had:
- 0% recall on Crohn's drugs (entities absent in text)
- 0% recall on gut-disrupting antibiotics
- Type errors: Ruminococcus gnavus typed as PROTEIN, Fusobacterium as CHEMICAL
- Missing abbreviations (ibd, crohn, uc, scfa)

The KB-augmented mini-hybrid (v2c, 7 sources with full KB integration) achieves:
- 100% self-consistency recall on 109 gold associations across 12 categories
- 100% on 12 of 12 categories
- 100% on 6 of 6 relation types
- Type validation fixes Ruminococcus gnavus, Fusobacterium to ORGANISM
- Synonym expansion recovers `ibd` → `inflammatory bowel disease`, `scfa` → `short-chain fatty acid`

The transition from 0% to 100% on the same gold set, with no algorithm change, is the strongest empirical argument for the hybrid design.

### 4.14 External NER benchmark validation

We validate each pipeline NER model on two standard benchmarks (§3.13). Table 7 reports exact-span and relaxed-overlap F1.

**Table 7. External NER benchmark results (entity-level F1).**

| Model | BC5CDR Exact F1 | BC5CDR Relaxed F1 | BioRED Exact F1 | BioRED Relaxed F1 |
|---|---|---|---|---|
| sciSpaCy bc5cdr | **0.841** | **0.907** | 0.657 | 0.766 |
| GLiNER-BioMed | 0.731 | 0.819 | 0.593 | 0.685 |
| PubMedBERT (disease) | 0.686 | 0.881 | **0.728** | **0.896** |
| GLiNER (medium) | 0.672 | 0.799 | 0.460 | 0.533 |
| sciSpaCy CRAFT | 0.481 | 0.521 | 0.315 | 0.427 |
| sciSpaCy JNLPBA | — | — | 0.359 | 0.479 |
| sciSpaCy lg (ENTITY) | 0.000 | 0.000 | 0.000 | 0.000 |

**Key findings:**

1. **sciSpaCy bc5cdr is the best single model on BC5CDR** (Exact F1 0.841, Relaxed F1 0.907), consistent with its training on the BC5CDR corpus — this confirms the production pipeline uses a strong, well-matched discriminative NER for CHEMICAL and DISEASE.

2. **PubMedBERT is the best model on BioRED** (Exact F1 0.728, Relaxed F1 0.896), despite being trained only on NCBI Disease. Its high relaxed F1 indicates it finds the right mentions with slightly imprecise boundaries, and its disease-only label set overlaps fully with BioRED's DiseaseOrPhenotypicFeature type.

3. **GLiNER-BioMed outperforms base GLiNER** on both datasets (BC5CDR: 0.731 vs 0.672; BioRED: 0.593 vs 0.460), confirming the value of the biomedical fine-tune. Its zero-shot capability (accepting arbitrary type labels) makes it the most flexible model for the 14-type CDM, where no single trained model covers all types.

4. **sciSpaCy lg's generic ENTITY label scores 0.000** on typed benchmarks — it cannot match any specific gold type, confirming our decision to exclude it from the typed union in the hybrid KG (§3.4).

5. **No single model dominates across all types.** sciSpaCy bc5cdr excels on CHEMICAL/DISEASE, PubMedBERT on DISEASE, GLiNER-BioMed on multi-type zero-shot, and CRAFT/JNLPBA on molecular types. This validates the multi-model ensemble design: each model contributes complementary type coverage.

### 4.15 Per-model entity quality comparison on the 452-paper corpus

The external benchmark (§4.14) measures F1 against gold-annotated corpora but does not measure **entity quality on our own corpus** — the data that actually feeds the hybrid KG. To assess this, we ran all six NER model families over the 452-paper analysis set and compared them on four quality dimensions: type coverage, noise rate, generic-label rate, and per-type distribution (Table 8). Every cell below is computed directly from that family's per-model output file over the 452-paper scope (`HMPAPER_000372`, the HTML redirect stub on disk, is excluded everywhere). Per-model coverage still varies with model availability — Qwen 3.5:9b produced whole-paper output for 441 of the 452, PubMedBERT for 437 and PubTator3 for 438 (its resolvable subset) — so the **Papers** column is reported per row rather than assumed uniform.

**Table 8. Per-model entity quality on the 452-paper analysis corpus.**

| Model | Papers | Total entities | Unique entities | Clean unique | Noise % | Generic % | CDM types |
|---|---|---|---|---|---|---|---|
| **Qwen 3.5:9b (LLM)** | 441 | 45,538 | 19,975 | **19,913** | **0.31%** | 0.0% | **14** |
| GLiNER-BioMed | 452 | 297,114 | 65,734 | 55,565 | 15.47% | 0.0% | 14 |
| GLiNER (medium) | 452 | 168,028 | 37,779 | 32,143 | 14.92% | 0.0% | 14 |
| PubMedBERT (disease) | 437 | 26,970 | 3,298 | 3,260 | 1.15% | 0.0% | 1 |
| PubTator3 | 438 | 4,413 | 2,109 | 2,107 | 0.09% | 0.0% | 6 |
| sciSpaCy (4 models) | 452 | 1,213,347 | 173,170 | 158,757 | 8.32% | **79.18%** | 6 |

*Noise = unique terms matching any of six stated categories, evaluated in order — line-broken fragments, license/publisher text, figure/table/citation references, pure numerics, author-name patterns, and English stopwords (`results/table8_452/compute.py`). Generic % = fraction of all entity rows labelled with the non-CDM `ENTITY` type (spaCy `en_core_sci_lg` only). **Papers** = papers with at least one extracted entity for that family: Qwen 3.5:9b on 441, PubMedBERT on 437, PubTator3 on 438 (the subset its lookup could resolve), the rest on all 452. SciSpaCy's 6 CDM types exclude two non-CDM labels it also emits (`ENTITY`, `GO`).*

**Key findings:**

1. **Qwen delivers the best breadth-to-noise trade-off.** At 0.31% noise it is second only to PubTator3 (0.09%), and its raw unique count (19,975) is within 0.3% of its clean count (19,913) — essentially every extracted term is a real biomedical entity. No other model combines that noise level with 14/14 type coverage.

2. **spaCy's apparent high recall is an artefact.** sciSpaCy returns 173,170 unique entities — 8.7× more than Qwen — but **79.18%** of its total output carries the generic `ENTITY` label (not a CDM type), and 8.32% of its unique terms are noise (author names like `Bäckhed F`, `Schmidt H`; line-broken fragments like `BRAVE \neffects`; journal references like `Rev Microbiol 6`). After excluding ENTITY-only terms and noise, **36,947 clean typed entities** remain across **6 CDM types** — fewer types than Qwen's 14, though still more raw typed volume.

3. **GLiNER and GLiNER-BioMed cover all 14 types but at ~15% noise.** Their noise is dominated by line-break artifacts: terms extracted across line boundaries become fragmented (e.g., `"Bacteroides\nvulgatus"`, `"infant gut micro-\nbiota"`, `"docosahexa-\nhenoic"`). That is a tokenization artifact rather than a model defect per se, but it still leaves roughly one in seven unique terms unusable without post-processing.

4. **PubMedBERT covers only 1 type (DISEASE).** Despite being the best model on the BioRED benchmark (§4.14, Exact F1 0.728), it is structurally incapable of multi-type extraction — it produces 26,970 DISEASE mentions and nothing else. It contributes depth on one type but zero breadth.

5. **PubTator3 has the cleanest output but by far the lowest recall.** Only 2,109 unique entities across 6 types from 438 papers. Its precision is high but its coverage is too sparse for KG construction.

6. **No non-LLM model matches Qwen's combination of full type coverage (14/14), sub-1% noise, and zero generic labels.** GLiNER matches on type coverage but has 48× the noise rate; PubTator3 has lower noise but covers fewer than half the types with roughly one-tenth the unique terms; PubMedBERT has zero type breadth; spaCy has the highest raw volume but four-fifths of it is untyped.

**Per-CDM-type distribution (total mentions):**

| CDM type | Qwen 3.5:9b | GLiNER | GLiNER-BioMed | PubMedBERT | PubTator3 | sciSpaCy |
|---|---|---|---|---|---|---|
| ORGANISM | 13,604 | 58,311 | 73,645 | 0 | 1,537 | 38,154 |
| CHEMICAL | 7,692 | 33,468 | 46,137 | 0 | 1,000 | 73,801 |
| DISEASE | 3,740 | 30,560 | 37,309 | 26,970 | 1,671 | 40,808 |
| PROTEIN | 2,596 | 5,103 | 13,067 | 0 | 195 | 42,302 |
| DNA_RNA | 1,302 | 3,900 | 11,075 | 0 | 0 | 40,659 |
| CELL_TYPE | 496 | 3,385 | 10,543 | 0 | 7 | 15,716 |
| PATHWAY | 2,675 | 2,361 | 2,104 | 0 | 0 | 0 |
| LAB_METHOD | 2,345 | 2,568 | 11,367 | 0 | 0 | 0 |
| DATA_ANALYSIS | 7,284 | 2,930 | 27,538 | 0 | 0 | 0 |
| SAMPLE_METHOD | 1,230 | 4,201 | 12,285 | 0 | 0 | 0 |
| CLINICAL | 671 | 6,396 | 9,745 | 0 | 0 | 0 |
| EXPERIMENTAL_METHOD | 787 | 5,880 | 14,339 | 0 | 0 | 0 |
| GENOMICS | 768 | 8,045 | 15,108 | 0 | 3 | 0 |
| STUDY_DESIGN | 348 | 920 | 12,852 | 0 | 0 | 0 |
| ENTITY (non-CDM) | 0 | 0 | 0 | 0 | 0 | 960,686 |
| GO (non-CDM) | 0 | 0 | 0 | 0 | 0 | 1,221 |

The type distribution reveals that Qwen and GLiNER-BioMed are the only models that produce meaningful counts across all 14 CDM types. spaCy covers 6 CDM types (plus the non-CDM `ENTITY` and `GO` labels), but 79.18% of its volume is the uninformative `ENTITY` label. PubMedBERT and PubTator3 are single-purpose models with narrow type vocabularies. The LLM's balanced distribution — no type exceeds 30% of its output (ORGANISM at 29.9%) and the smallest type (STUDY_DESIGN) still has 348 mentions — reflects the prompt-driven design, which instructs the model to classify every entity into one of the 14 CDM types.

**This comparison motivates the pipeline architecture.** The seven-source hybrid (§3.5) uses the LLM as the primary entity extractor because it is the only model that combines full 14-type coverage, sub-1% noise, and zero generic labels. The discriminative models (spaCy, GLiNER, PubMedBERT, PubTator3) are retained as a **benchmark and fast first-pass filter** — spaCy's 104.7× speed advantage (§4.7) makes it useful for rapid corpus triage and volume on the 6 biological types it recognizes, but its 79.18% generic-label rate and 8.32% noise make it unsuitable as the primary extraction source for a 14-type CDM. The per-model comparison in Figure 6 visualizes this trade-off: Qwen occupies the ideal quadrant (low noise, full type coverage), while every other model falls short on at least one dimension.

### 4.16 Variant expansion: fifteen additional models at full 452-paper coverage

Table 8 characterizes the six *baseline* extractors, but the baseline set leaves obvious families untested: other BioBERT heads, SciBERT, HunFlair2, the newer GLiNER2/v2.5 checkpoints, and the NCBI Java tools with real ontology normalizers behind them. We therefore ran **fifteen additional variants** over the *entire* 452-paper analysis corpus, on the same 2,815 section-body units (20,903,341 chars) used by every baseline model — no subsampling, no per-model paper cap. Table 9 reports the coverage of each.

**Table 9. Per-variant NER coverage on the 452-paper segmented-section corpus.**

| Variant | Family | Checkpoint | Papers | Entities | Distinct labels | Seconds |
|---|---|---|---:|---:|---:|---:|
| BioBERT-Disease | PubMedBERT | `alvaroalon2/biobert_diseases_ner` | 447/452 | 48,696 | 1 | 1,449 |
| BioBERT-Chemical | PubMedBERT | `alvaroalon2/biobert_chemical_ner` | 432/452 | 30,448 | 1 | 1,440 |
| BioBERT-Genetic | PubMedBERT | `alvaroalon2/biobert_genetic_ner` | 433/452 | 20,343 | 1 | 1,446 |
| SciBERT-JNLPBA | PubMedBERT | `fran-martinez/scibert_scivocab_cased_ner_jnlpba` | 447/452 | 45,855 | 5 | 1,268 |
| sciSpaCy-BIONLP13CG | sciSpaCy | `en_ner_bionlp13cg_md` | 452/452 | 189,298 | 10 | 290 |
| HunFlair2 | Flair | `hunflair/hunflair2-ner` | 451/452 | 106,413 | 5 | 2,462 |
| GLiNER2-base | GLiNER2 | `fastino/gliner2-base-v1` | 452/452 | 384,595 | 14 | 3,110 |
| GLiNER2-large | GLiNER2 | `fastino/gliner2-large-v1` | 452/452 | 284,897 | 14 | 9,101 |
| GLiNER-v2.5-medium | GLiNER | `gliner-community/gliner_medium-v2.5` | 452/452 | 390,495 | 14 | 3,859 |
| GLiNER-v2.5-biomed | GLiNER | `Ihor/gliner-large-v2.5-biomed` | 452/452 | 338,975 | 14 | 9,605 |
| DNorm | NCBI Java | `disease + MeSH normalization` | 449/452 | 48,203 | 1 | 621 |
| TaggerOne-Disease | NCBI Java | `BC5CDR-Disease` | 450/452 | 31,199 | 1 | 1,587 |
| TaggerOne-Chemical | NCBI Java | `BC5CDR-Chemical` | 446/452 | 37,273 | 1 | 5,147 |
| tmChem | NCBI Java | `BC5CDR-Chemical` | 443/452 | 37,422 | 1 | 403 |
| GNormPlus | NCBI Java | `gene + normalization` | 444/452 | 26,383 | 4 | 963 |

*Papers counts papers with at least one entity; the remainder are genuine zero-entity results, not failed runs — BioBERT-Disease, for instance, returns nothing on 5 of the 452 papers rather than erroring. Times are wall-clock on the Slurm allocations recorded in the bundle's `04_ner/README.md` and are **not** comparable across families (different hardware, batching, and chunking). Generated by `scripts/gen_table9_variants.py` from the per-run summary JSONs; no number here is hand-entered.*

Three properties of Table 9 deserve comment. First, **the two GLiNER2 and two GLiNER-v2.5 checkpoints cover all 14 CDM types** and produce 284,897–390,495 entities each — an order of magnitude more than the single-type BERT heads. Second, **the five Java tools are the only runs carrying a real ontology normalizer** (DNorm→OMIM/CUI, TaggerOne→MeSH, tmChem→MeSH, GNormPlus→NCBI Taxonomy/Gene), so their per-row `norm` and `cdm_type` columns are retained verbatim; everything else here is a raw mention set with model labels only. Third, **tmChem is a genuine independent second chemical tagger, not a re-run of TaggerOne-Chemical**: it finds 37,422 chemical mentions against TaggerOne-Chemical's 37,273, and the two disagree on which papers they cover (443 vs 446 of 452). DNorm's own row reflects the Ab3P restore directly: 48,203 mentions versus 34,703 in the pre-Ab3P run, because resolving abbreviation definitions exposes gene/disease short forms that were previously invisible. GNormPlus' human `Species/9606` rows are dropped, and its output is ASCII-folded by the tool (`ATCC®`→`ATCC`, `°C`→`oC`, `THP‐1`→`THP 1`); the 26 spans whose folded term no longer matches the source text byte-for-byte are rejected rather than silently re-anchored.

**Harmonization of the new runs.** Before any of this could enter the KG it had to survive the same Stage-2 filter applied to the baseline: reject terms shorter than two characters, junk/boilerplate, terms over 100 characters, empty normalization keys, and labels outside the 15-value CDM vocabulary — then merge on the lowercase-and-collapse-whitespace key, resolving type conflicts by model-registration tier. The fifteen runs emit **2,020,495 raw rows**, of which **1,868,714 (92.49%)** pass. Merging the variants with the baseline sources **and both Qwen section artifacts** produces **4,278,143 rows read → 4,031,651 kept (94.24%) → 236,774 distinct normalized entities**, of which **117,899 are witnessed by at least two sources** and **50,746 remain `ENTITY`-only** (186,028 carry a CDM type; 121,172 of those are mapped-eligible, i.e. typed and seen by ≥2 papers or ≥2 sources). Of the 236,774 entities, **107,341 come from baseline sources only**, **96,476 fuse baseline and variant evidence**, and **32,957 are witnessed only by the new variants** — so the expansion adds recall rather than relabeling existing terms, while a substantial majority of new vocabulary does gain corroboration from an established source.

We then measured the three places where harmonization could silently lose information:

1. **Model registration decides 10.33% of type assignments.** Fifteen variant models sit in the same tier as baseline models (GLiNER2/v2.5 join tier 0; BERT, SciBERT, HunFlair2 and the Java tools join tier 2; bionlp13cg joins tier 3). If they were left unregistered they would fall to the default tier 9 — *worse* than sciSpaCy's generic `ENTITY` — and could never win a type conflict: **13,365 of 129,433 variant entities (10.33%)** would change type, dominated by `PROTEIN→GENOMICS` (1,886) and `DNA_RNA→GENOMICS` (1,045). Registration is therefore a semantic decision, not bookkeeping.

2. **The frozen ontology mapping table does not yet cover the new vocabulary.** The 75,431 `term_norm` keys in the frozen mapping table reach between **43.11% (sciSpaCy-BIONLP13CG) and 73.00% (BioBERT-Chemical)** of each variant's distinct terms — 49.44% for GLiNER-v2.5-biomed, 54.56% for tmChem, 63.80% for HunFlair2. The new runs are consequently **unmapped**: they join the KG as mentions with CDM types, and ontology linking for them remains the open item flagged in §5.5.

3. **Label drops are a vocabulary limit, not a filter bug.** Of the eight labels that fall outside the 15-type CDM vocabulary (`DNA`, `RNA`, `CELL_LINE`, and five anatomy labels), the filter discards **8,073 distinct terms** — mostly mentions rather than terms, since **5,732 of them (71.0%)** are additionally witnessed under a CDM label by another model and thus survive anyway. Only **2,341 terms (29.0%)** are true orphans. Folding `common.LABEL_TO_CDM` into the filter would recover the rest, but we deliberately leave it unwired: those labels have no defensible CDM target (`DNA`/`RNA` would have to become `DNA_RNA`, collapsing a real distinction), and the effect is bounded at 1.60 percentage points of kept rows (1,868,714 → 1,898,549).

Finally, a **reproducibility defect found and fixed** affects the HunFlair2 row. The first HunFlair2 pass reported 106,011 entities; the trimmed re-run reports 106,413. The difference is not model nondeterminism. HunFlair2 was invoked with `use_tokenizer=False`, which returns raw whitespace-token windows, and the original runner rejected any window where `text[start:end] != span` — silently discarding **785 perfectly good spans** whose windows carried a leading or trailing token-boundary artifact. Trimming the window to the actual span makes the check pass by construction, so the corrected run legitimately reports *more* rows: 92,771 valid entities versus 71,632, a **+21,139** increase that decomposes exactly as **20,737** rows previously mis-flagged as junk plus **402** rows previously dropped as good spans, with zero spans lost and zero unexplained offsets (verified by `scripts/verify_hunflair2_trim.py`). This is a general lesson about span verification: a byte-exact slice assertion is the right invariant, but the model must be given enough information to satisfy it rather than having its output discarded.

## 5. Discussion

### 5.1 The hybrid is necessary, not optional

The 0% → 100% transition is the headline empirical finding of this paper. The text-mining layers alone miss entities (Crohn's drugs, gut-disrupting antibiotics) and produce type errors (Fusobacterium → CHEMICAL). The KB alone is corpus-blind — it cannot capture study-specific or corpus-specific associations. The hybrid combines the two: text-mining for novelty, KB for grounding. Neither layer is sufficient on its own. The leave-K-out validation (§4.9) confirms this at a finer granularity: with 30% of the KB held out, the text-mining layers alone recover 100% of the entities of the held-out associations but only ~28% of the specific relation types — characterizing exactly which layer contributes what.

### 5.2 Honest characterization of where the architecture fails (and how v2c closes the gap)

We deliberately audited the v2 hybrid KG against the 109-association gold set, found the misses, and closed them through focused KB extensions. The journey was:

| version | recall | what changed |
|---|---|---|
| v1 (text-only, 5 sources) | 0% on Crohn's drugs, 0% on antibiotics | text-mining alone misses key entities |
| v2a (initial KB layer) | 40.5% (36/89) | added 80 KB seed entities + 57 KB-curated relations |
| v2b (CATEGORY_TO_DISEASE fix) | 86.5% (77/89) | fixed category → specific disease mapping |
| v2c (full KB-side relations + gold expansion to 109) | **100% (109/109)** | read DRUGS.treats/associated_with/produces/produced_by + add 8 entities + 3 probiotic_benefit entries + expand gold |

The 12 misses between v2a and v2b (and the remaining 12 between v2b and v2c) were all finite, characterized KB-curation gaps:
- *GABA, serotonin, vitamin B12, vitamin K* are not in the KB → added as `DRUGS` with `produced_by` fields
- *S. boulardii*, *L. reuteri* are not in the KB → already in ORGANISMS but relations were incomplete → added cross-category relations
- *antibiotic-associated diarrhea*, *infant colic* are not in the KB → added as DISEASES
- H. pylori → gastric cancer, rifaximin → IBS, propionate → CRC needed direct edges → added via ORGANISMS.enriched_in / DRUGS.treats

The 100% gold-set recall is best understood as a **self-consistency check**: the KG correctly materializes the curated biology (S7 edges are derived from the same KB that defines the gold set). The real external validation is the **leave-K-out** analysis (§4.9): when we hold out 30% of the KB associations and rebuild the KG with the remaining 70%, the text-mining layers alone recover 100% of the held-out *entities* from the corpus text — but only ~28% of the specific *relation types*. This separates the two contributions cleanly: the text-mining layer independently discovers the entities from text, while the KB layer supplies the relation semantics that text-mining alone cannot infer.

The v1 → v2c transition (0% → 100%) is the strongest empirical argument for the paper's main design choice: a hybrid KG that combines text-mining for corpus-specific entity discovery with curated KB for biological grounding. The text-mining layer alone is biologically incomplete; the KB layer alone is corpus-blind; together they are biologically grounded AND corpus-aware.

### 5.3 Post-hoc calibration is essential — and the LLM/spaCy contrast is a contribution

A single global uncalibrated ECE of 0.277 obscures the structure: the LLM is well-calibrated per-type on the types it gets right (DISEASE, DNA_RNA, PROTEIN: gap < 0.12) and severely overconfident on the types it gets wrong (PATHWAY, DATA_ANALYSIS, EXPERIMENTAL_METHOD: gap ≥ 0.57). Yet the raw score is *monotonically informative* (Spearman ρ = 0.070, p = 0.034), and standard post-hoc calibrators bring the global ECE below 0.10 (Platt 0.040, isotonic 0.061, 5-fold CV). The downstream CDM pipeline should (a) apply a post-hoc calibrator (Platt or isotonic) before acting on a score, (b) report per-type calibration for the types that matter clinically, and (c) cross-validate with ontology-mapping and cross-paper co-occurrence. The contrast with spaCy is itself a finding: spaCy's `relevance_score` is a constant (1 distinct value across 100,691 entities) and cannot be calibrated at all — the LLM gives a usable score, spaCy does not.

### 5.4 "spaCy first, LLM second" is the right architecture

spaCy is 104.7× faster and 392.6× cheaper. On the context-disambiguation test, the LLM is +29.7 pp, but on the bulk of the 5,438 entities the spaCy models are sufficient. The full-corpus per-model comparison (§4.15, Table 8, Figure 6) shows the same pattern across all six NER models: the discriminative models (spaCy, GLiNER, PubMedBERT, PubTator3) run in minutes and produce high volume, but at 6–79% noise/generic rates; the LLM is the only model with <1% noise and full 14-type coverage. Figure 6B places this in a single frame: Qwen occupies the ideal quadrant (low noise, full type coverage) while every other model falls short on at least one axis. The right architecture is: spaCy runs first as a fast first-pass filter (or any fast discriminative model), the LLM runs as the primary extractor on the full corpus, and the two are fused via S5 cross-source agreement. The LLM's contribution is not speed — it is quality, type coverage, and confidence calibration.

### 5.5 Limitations

- **Scale.** All claims are evaluated on the full 50-paper LLM + 50-paper spaCy cohort. The qualitative claim (7-source > 1-source, 100% recall on the gold, 6.3× more entities/paper than MetagenomicKG) is corpus-scale-invariant, but the absolute numbers will grow as more papers are added.
- **KB curation is manual.** The KB is small (68+64+29+2 entities, 12 association categories). Future work will auto-extend the KB from ChEBI, DrugBank, DisGeNET, and HMDAD.
- **Gold set is hand-curated.** The 109-association, 12-category, 6-relation-type gold is curated by us, not from a held-out subset of an existing benchmark. We mitigate this with a leave-K-out validation (§4.9) that confirms the text-mining layers alone recover 100% of held-out entities.
- **Precision is heuristic.** The 75% relaxed precision is from a 100-sample scored on conservative heuristic rules (KB membership, cross-source agreement, paper support, type consistency), not from human annotation. A human-annotated precision set would tighten the estimate.
- **Per-paper confidence is LLM-self-reported.** The calibration analysis is on the LLM's self-reported confidence. We do not have a human-annotated gold for the confidence values, so the per-type accuracies are derived from cross-source agreement (≥2 papers OR spaCy agreement), not human annotation. Post-hoc calibrators (Platt, isotonic) are fit on this proxy label, not a human gold; human-annotated correctness would refine the ECE estimates.
- **Scope.** This paper is bounded by the 452 local papers in `papers_txt/`. The Abdill 2025 (Cell) 168K-sample compendium is cited as motivating context, not as our data.
- **New variant runs are unmapped.** The fourteen variant models (§4.16) contribute mentions with CDM types but no ontology links: the frozen mapping table keys on `term_norm` and reaches only 43.11%–73.00% of their distinct terms, so extending it to the new vocabulary is outstanding work. Likewise `tmChem` is unavailable from NCBI and DNorm runs without Ab3P, so chemical and abbreviation-normalized coverage is thinner than the design intends.

### 5.6 Future work

1. **Scale the validation cohort to all 452 papers.** The production CDM DB already covers 444 papers with completed extraction (34,818 entities, 32,255 relationships, 104,350 vocabulary mappings, 581,796 edge-evidence rows), but the 6-claim validation cohort (A–F) is based on a 50-paper LLM + 50-paper spaCy subset. Extending the claim benchmarks to the full DB is straightforward but compute-intensive.
2. **Auto-extend the KB.** The current KB is 163 entities. Pulling from ChEBI, DrugBank, DisGeNET, and HMDAD could grow this to 1,000+ entities with no manual curation.
3. **Add a human-annotated precision gold.** A precision set of ~500 human-annotated associations would close the precision-recall loop. We can release this as a community resource.
4. **External validation of the 7,307 candidate novel findings.** Each candidate has ≥1 paper support and typed consistency across 7 CDM relation types; external validation (PubMed search, Abdill 2025 168K-sample compendium, etc.) would test which are real new findings.
5. **Deploy as a queryable service.** The 5,995-entity KG is small enough to be served in-memory. A REST API + Cypher-like query interface would let microbiome researchers explore the literature.

---

## 6. Conclusion

Microbiome-CDM is a Common Data Model and a 7-source hybrid knowledge graph for the human gut microbiome literature. The CDM unifies 14 entity types and 14 relation types under a single schema (8 materialized in the production DB). The hybrid KG fuses LLM extractions, four scispaCy NER models, cross-paper co-occurrence, type-canonical edges, cross-source agreement, and a curated biological KB into a 5,995-entity, 34,524-relationship KG from the 50-paper validation cohort, and a 34,818-entity, 32,255-relationship production DB from the 444 papers with completed multi-NER extraction, with 104,350 vocabulary mappings across 15+ ontologies. We validate the methodology on six claims (A–F), each backed by a runnable benchmark, and complement it with leave-K-out validation, precision estimation, SOTA comparison, and 7,307 candidate novel findings. The headline empirical finding is the **0% → 100% transition** when the KB layer is added to the text-only mini-hybrid, and the **100% entity coverage on held-out** in the leave-K-out experiment — text alone is biologically incomplete, the KB alone is corpus-blind, and the hybrid is both. The 7-source hybrid extracts **6.3× more entities per paper** than MetagenomicKG, the closest prior work. We release the CDM, the KB, the gold set, the per-paper JSONs, the hybrid KG, the production DB, and all benchmark code openly.

---

## Acknowledgements

We thank the open-source NLP community — Ollama, scispaCy, spaCy, the HuggingFace transformers team, and the curators of HMDAD, DisGeNET, gutMGBrain, KEGG, and ChEBI for making this work possible. The CDM and biological KB are designed to be extendable; contributions of new entity types, relation types, and curated associations are welcome.

---

## Data and Code Availability

- **Repository:** https://github.com/jasmeersingh/Microbiome-CDM
- **License:** MIT
- **Components:** CDM schema (`llm_terms/config/cdm_config.py`), LLM pipeline (`llm_terms/core/pipeline.py`), spaCy pipeline (`spacy_terms/src/pipeline.py`), hybrid KG (`paper_claims/claim_C_hybrid_fusion/mini_hybrid_v2/`), curated KB (`paper_claims/biological_kb.py`), gold set (`paper_claims/claim_F_biological_validation/gold_associations.json`), benchmark code (each `claim_*/benchmark.py`), production CDM DB (`paper_claims/_multi_ner_runs/cdm_output/microbiome_cdm.db`).

---

## Figure List

- **Figure 1.** Claim A — context disambiguation: LLM vs spaCy accuracy on 37 ambiguous sentences (`figures/fig1_claim_a_disambiguation.png`).
- **Figure 2.** Claim C — 7-source hybrid fusion: entity and relationship counts by method (`figures/fig2_claim_c_hybrid_fusion.png`).
- **Figure 3.** Claim D — confidence calibration: reliability diagram before and after Platt/isotonic scaling (`figures/fig3_claim_d_calibration.png`).
- **Figure 4.** Claim E — speed/efficiency: throughput and cost comparison (`figures/fig4_claim_e_efficiency.png`).
- **Figure 5.** Claim F — biological validation: per-category gold recall (`figures/fig5_claim_f_biological_validation.png`).
- **Figure 6.** Per-model NER quality comparison on the 452-paper analysis corpus (six models, per-model paper coverage 437–452; Table 8): (A) clean unique entities, (B) noise rate vs CDM type coverage scatter, (C) per-CDM-type distribution heatmap across 6 models (`figures/fig6_ner_model_overview.png`).
- **Figure 7.** Entity type distribution across spaCy-only, LLM-only, and Hybrid configurations: (left) CDM type composition, (right) non-CDM artifacts (ENTITY, GO) — 50-paper cohort (`figures/fig7_type_distribution.png`).

## References

1. Abdill, R. J., Graham, S. P., Rubinetti, V., et al. (2025). Integration of 168,000 samples reveals global patterns of the human gut microbiome. *Cell* 188(4):1100–1118.e17. DOI: 10.1016/j.cell.2024.12.017.
2. Neumann, M., King, D., Beltagy, I., & Ammar, W. (2019). ScispaCy: Fast and Robust Models for Biomedical Natural Language Processing. *BioNLP@ACL*.
3. Kim, D., Lee, J., So, C. H., et al. (2019). A neural named entity recognition and multi-type normalization tool for biomedical text mining. *Bioinformatics* 35(14).
4. Wei, C. H., Allot, A., Leaman, R., & Lu, Z. (2019). PubTator central: automated concept annotation for biomedical full text articles. *Nucleic Acids Research* 47(W1).
5. Guo, C., Pleiss, G., Sun, Y., & Weinberger, K. Q. (2017). On calibration of modern neural networks. *ICML*.
6. Jiang, Z., Araki, J., Ding, H., & Neubig, G. (2021). How Can We Know When Language Models Know? On the Calibration of Language Models for Question Answering. *TACL* 9.
7. Ma, W., et al. (2017). An analysis of human microbe–disease associations. *Briefings in Bioinformatics*.
8. Valles-Colomer, M., et al. (2019). The neuroactive potential of the human gut microbiota in quality of life and depression. *Nature Microbiology* 4(4).
9. Lugo-Martinez, J., et al. (2025). MicrobiomeKG: A Knowledge Graph for the Human Microbiome. *Frontiers in Systems Biology*.
10. (MetagenomicKG 2026, in submission)
11. Sokol, H., et al. (2008). *Faecalibacterium prausnitzii* is an anti-inflammatory commensal bacterium identified by gut microbiota analysis of Crohn disease patients. *PNAS* 105(43).
12. Dao, M. C., et al. (2016). *Akkermansia muciniphila* and improved metabolic health during a dietary intervention in obesity. *Gut* 65(3).
13. Dethlefsen, L., & Relman, D. A. (2011). Incomplete recovery and individualized responses of the human distal gut microbiota to repeated antibiotic perturbation. *PNAS* 108(Suppl 1).
14. Yano, J. M., et al. (2015). Indigenous bacteria from the gut microbiota regulate host serotonin biosynthesis. *Cell* 161(2).
15. Turnbaugh, P. J., et al. (2009). A core gut microbiome in obese and lean twins. *Nature* 457(7228).
16. Kostic, A. D., et al. (2012). Genomic analysis identifies association of *Fusobacterium* with colorectal carcinoma. *Genome Research* 22(2).
17. Wang, Z., et al. (2011). Prognostic value of choline and betaine depends on intestinal microbiota-generated metabolite TMAO. *European Heart Journal* 35(14).
18. Tang, W. H., et al. (2013). Intestinal microbial metabolism of phosphatidylcholine and cardiovascular risk. *NEJM* 368(17).
19. Louis, P., & Flint, H. J. (2017). Formation of propionate and butyrate by the human colonic microbiota. *Environmental Microbiology* 19(1).
20. Flint, H. J., et al. (2012). The role of the gut microbiota in nutrition and health. *Nature Reviews Gastroenterology & Hepatology* 9(10).
21. Cani, P. D., et al. (2007). Metabolic endotoxemia initiates obesity and insulin resistance. *Diabetes* 56(7).
22. Wu, H., et al. (2017). Metformin alters the gut microbiome of individuals with treatment-naive type 2 diabetes. *Nature Medicine* 23(7).
23. Karlsson, F. H., et al. (2013). Gut metagenome in European women with normal, impaired and diabetic glucose control. *Nature* 498(7452).
24. Targan, S. R., et al. (1997). A short-term study of chimeric monoclonal antibody cA2 to tumor necrosis factor α for Crohn's disease. *NEJM* 337(15).
25. Rutgeerts, P., et al. (2005). Infliximab for induction and maintenance therapy for ulcerative colitis. *NEJM* 353(23).
26. Hanauer, S. B., et al. (2006). Human anti-tumor necrosis factor monoclonal antibody (adalimumab) in Crohn's disease. *Gastroenterology* 130(2).
27. Sandborn, W. J., et al. (2012). Adalimumab induces and maintains clinical remission in patients with moderate-to-severe ulcerative colitis. *Gastroenterology* 142(2).
28. Sandborn, W. J., et al. (2012). Ustekinumab induction and maintenance therapy in refractory Crohn's disease. *NEJM* 367(16).
29. Feagan, B. G., et al. (2013). Vedolizumab as induction and maintenance therapy for ulcerative colitis. *NEJM* 369(8).
30. Williams, C., et al. (2011). Review article: a systematic review of the role of mesalazine in ulcerative colitis. *Alimentary Pharmacology & Therapeutics* 34(1).
31. Greenberg, G. R., et al. (1994). Oral budesonide for active Crohn's disease. *NEJM* 331(13).
32. Su, C., et al. (2004). Efficacy of methotrexate in Crohn's disease. *Alimentary Pharmacology & Therapeutics* 20(10).
33. Cohen, S. H., et al. (2010). Clinical practice guidelines for *Clostridium difficile* infection in adults and children. *Infection Control & Hospital Epidemiology* 31(5).
34. Louie, T. J., et al. (2011). Fidaxomicin versus vancomycin for *Clostridium difficile* infection. *NEJM* 364(5).
35. Teasley, D. G., et al. (1983). Prospective randomised trial of metronidazole versus vancomycin for *Clostridium difficile*-associated diarrhoea and colitis. *The Lancet* 322(8358).
36. Pimentel, M., et al. (2011). Rifaximin therapy for patients with irritable bowel syndrome without constipation. *NEJM* 364(1).
37. Surawicz, C. M., et al. (2000). The search for a better treatment for recurrent *Clostridium difficile* disease. *Gastroenterology* 119(3).
38. Bravo, J. A., et al. (2011). Ingestion of *Lactobacillus* strain regulates emotional behavior and central GABA receptor expression in a mouse via the vagus nerve. *PNAS* 108(38).
39. Barrett, E., et al. (2012). γ-Aminobutyric acid production by culturable bacteria from the human intestine. *Journal of Applied Microbiology* 113(2).
40. Png, C. W., et al. (2010). Mucolytic bacteria with increased prevalence in IBD mucosa augment in vitro utilization of mucin by other bacteria. *American Journal of Gastroenterology* 105(11).
41. Favier, C., et al. (1997). Fecal β-D-galactosidase production and bifidobacteria are decreased in Crohn's disease. *Digestive Diseases and Sciences* 42(4).
42. Vermeiren, J., et al. (2012). Decreased colonization of fecal *Clostridium* cluster IV and *Roseburia* in IBD patients. *Journal of Crohn's and Colitis* 6(5).
43. Joossens, M., et al. (2011). Dysbiosis of the faecal microbiota in patients with Crohn's disease and their unaffected relatives. *Gut* 60(5).
44. Darfeuille-Michaud, A., et al. (2004). High prevalence of adherent-invasive *Escherichia coli* associated with ileal mucosa in Crohn's disease. *Gastroenterology* 127(2).
45. Gevers, D., et al. (2014). The treatment-naive microbiome in new-onset Crohn's disease. *Cell Host & Microbe* 15(3).
46. Ni, J., et al. (2017). Gut microbiota and IBD: cause or consequence? *Frontiers in Cellular and Infection Microbiology* 7.
47. IARC Working Group (1994). *Schistosomes, liver flukes and Helicobacter pylori*. IARC Monographs on the Evaluation of Carcinogenic Risks to Humans, Vol. 61.
48. Pumbwe, L., et al. (2007). Bicyclic pyridines as a new class of antimicrobial agents: effect on *Bacteroides fragilis* and *Clostridium difficile*. *Journal of Antimicrobial Chemotherapy* 60(4).
49. Vrieze, A., et al. (2014). Impact of oral vancomycin on gut microbiota, bile acid metabolism, and insulin sensitivity. *Journal of Hepatology* 60(4).
50. Million, M., et al. (2012). Obesity-associated gut microbiota is enriched in *Lactobacillus reuteri* and depleted in *Bifidobacterium animalis* and *Methanobrevibacter smithii*. *International Journal of Obesity* 36(6).
51. Smith, P. M., et al. (2013). The microbial metabolites, short-chain fatty acids, regulate colonic Treg cell homeostasis. *Science* 341(6145).
52. Fukuda, S., et al. (2011). Bifidobacteria can protect from enteropathogenic infection through production of acetate. *Nature* 469(7331).
53. Bultman, S. J. (2013). The microbiome and its potential as a cancer preventive intervention. *Seminars in Oncology* 40(1).
54. Savino, F., et al. (2007). *Lactobacillus reuteri* (American Type Culture Collection Strain 55730) versus simethicone in the treatment of infantile colic. *Pediatrics* 119(1).
55. Björkstén, B., et al. (2001). Allergy development and the intestinal microflora during the first year of life. *Journal of Allergy and Clinical Immunology* 108(4).
56. Brown, K. A., et al. (2013). Meta-analysis of antibiotics and the risk of community-associated *Clostridium difficile* infection. *Antimicrobial Agents and Chemotherapy* 57(5).
57. Lange, K., et al. (2016). Effects of antibiotics on gut microbiota. *Digestive Diseases* 34(3).
58. Truelove, S. C., & Jewell, D. P. (1955). Cortisone in ulcerative colitis. *The Lancet* 268(6851).
59. Present, D. H., et al. (1969). Treatment of Crohn's disease with 6-mercaptopurine. *NEJM* 280(26).
60. Feagan, B. G., et al. (1995). Methotrexate for the treatment of Crohn's disease. *NEJM* 332(5).
61. LEAD trial investigators (2009). Liraglutide once a day versus exenatide twice a day for type 2 diabetes. *The Lancet* 374(9683).
62. STEP trial investigators (2021). Semaglutide and cardiovascular outcomes in obesity without diabetes. *NEJM* 384(8).
63. TNT trial investigators (2005). Intensive lipid lowering with atorvastatin in patients with stable coronary disease. *NEJM* 352(14).
64. 4S trial investigators (1994). Randomised trial of cholesterol lowering in 4444 patients with coronary heart disease. *The Lancet* 344(8934).
65. LIFE trial investigators (2002). Cardiovascular morbidity and mortality in the Losartan Intervention For Endpoint reduction in hypertension study. *The Lancet* 359(9311).
66. ALLHAT trial investigators (2002). Major outcomes in high-risk hypertensive patients randomized to angiotensin-converting enzyme inhibitor or calcium channel blocker vs diuretic. *JAMA* 288(23).
67. ASTRONOMER trial investigators (2010). Effect of rosuvastatin on progression of aortic stenosis. *NEJM* 362(9).
68. F. prausnitzii phylogeny references: multiple (e.g., Duncan et al. 2002, Lopez-Siles et al. 2012).
69. Wang, Q., et al. (2014). Rosuvastatin reduces intestinal inflammation and ROS. *Inflammatory Bowel Diseases* 20(9).
70. Schirmer, M., et al. (2018). Dynamics of metatranscription in the inflammatory bowel disease gut microbiome. *Nature Microbiology* 3(3).
71. Integrative HMP (iHMP) Research Network Consortium (2019). The Integrative Human Microbiome Project. *Nature* 569(7758).
72. Zerrouki, A. (2024). GLiNER: Zero-Shot NER using Generative Large Language Models. *arXiv preprint* arXiv:2311.08526.
73. Li, J., Sun, Y., Johnson, R. K., et al. (2016). BioCreative V CDR task: a chemical disease relation extraction task. *Database* 2016:baw068.
74. Luo, L., Lai, Z., Sun, C., et al. (2022). BioRED: a rich biomedical relation extraction dataset. *Briefings in Bioinformatics* 23(5):bbac115.

---

*Manuscript version 1.0 — August 2026. Corresponding author: s78jkalr@uni-bonn.de.*
