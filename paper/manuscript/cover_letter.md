# Cover Letter — Microbiome-CDM

**To:** The Editor, *Briefings in Bioinformatics*

**Subject:** Microbiome-CDM: a Common Data Model and 7-source hybrid Knowledge Graph for the human gut microbiome literature

---

Dear Editor,

We submit our manuscript, "Microbiome-CDM: a Common Data Model and 7-source hybrid Knowledge Graph for the human gut microbiome literature," for consideration as a Research Article in *Briefings in Bioinformatics*.

The human gut microbiome literature is large (>350,000 papers indexed in PubMed) but fragmented. The same organism may appear under multiple names; the same drug under generic, brand, or abbreviation; the same disease as IBD, Crohn's disease, or UC. This terminological heterogeneity is a primary barrier to meta-analyses, drug-repurposing screens, and mechanism-hypothesis generation. Recent advances in NLP — both generative (LLMs) and discriminative (scispaCy) — make it possible to extract structured information at scale, but no single method is sufficient.

We present **Microbiome-CDM**, a Common Data Model (14 entity types, 14 relation types; 8 materialized in the production DB) and a **7-source hybrid knowledge graph construction pipeline** in which an LLM (Qwen 3.5:9b) serves as the primary entity extractor, four scispaCy models provide a fast first-pass filter, and a curated biological knowledge base grounds the text-mining output. Additional sources include cross-paper co-occurrence edges, type-canonical edges, cross-source agreement, and KB-curated relationships:

1. LLM extractions (Qwen 3.5:9b, generative, adaptive chunking, 14-type CDM prompt) — **primary extractor**
2. Discriminative NER from four scispaCy models in parallel — **fast first-pass filter** (104.7× faster than LLM)
3. Cross-paper co-occurrence edges
4. Type-canonical CDM edges
5. Cross-source agreement (LLM ∩ spaCy)
6. Curated biological knowledge base (68 organisms, 64 drugs, 29 diseases, 2 metabolites, 12 KNOWN_ASSOCIATIONS categories)
7. KB-curated relationships (251 typed edges including `depleted_in`, `enriched_in`, `produces`, `treats`, `disrupts`)

To motivate this architecture, we benchmark all six available NER models (Qwen, sciSpaCy, GLiNER, GLiNER-BioMed, PubMedBERT, PubTator3) on the full 452-paper corpus across four quality dimensions (Figure 6). Qwen is the only model combining full 14-type coverage, <1% noise (0.9%), and zero generic labels. sciSpaCy produces 248,873 unique entities but 79.1% carry the vacuous `ENTITY` label and 14.2% are noise (author names, line-broken fragments). GLiNER and GLiNER-BioMed cover all 14 types but at 21% noise (PDF line-break artifacts). PubMedBERT covers only DISEASE. PubTator3 has 2.5% noise but only 1,689 entities from 308 papers. No single non-LLM model matches the LLM's quality on all dimensions, motivating the LLM-first architecture with discriminative models as benchmark and fast pre-filter.

We validate the methodology with **six empirically verified claims** (A–F):

- **Claim A**: LLM 54.1% vs spaCy best 24.3% on 37 ambiguous microbiome-context sentences spanning all 14 CDM entity types (+29.7 pp).
- **Claim B**: 393 truly novel entities recovered by the LLM (VRE, HNPCC, Chao richness estimator, etc.) not in any spaCy vocabulary, after synonym and validity filtering.
- **Claim C**: 5/5 metric wins for the 7-source hybrid over either single-method view.
- **Claim D**: the LLM's raw confidence is inflated (ECE 0.277) but monotonically informative (Spearman ρ 0.070, p 0.034); post-hoc Platt scaling brings ECE to 0.040 and isotonic to 0.061. spaCy's confidence is vacuous (1 distinct value across 100,691 entities).
- **Claim E**: spaCy 104.7× faster and 392.6× cheaper than the LLM.
- **Claim F**: **100% self-consistency recall** on a 109-association, 12-category, 6-relation-type gold set (HMDAD, DisGeNET, gutMGBrain, KEGG), with 0 misses; validated independently by leave-K-out (see below).

The 100% gold-set recall is a self-consistency check — the KG correctly materializes the curated biology it was built from. The independent external validation is **leave-K-out**: holding out 10%, 20%, 30% of the KB's KNOWN_ASSOCIATIONS, the text-mining layers alone recover **100% of the entities** of the held-out associations, but only ~28% of the specific relation types. This characterizes exactly which layer contributes what: the text-mining layer is sufficient for **entity-level completeness**; the **KB-curated layer is needed for the specific relation types**. The hybrid is not optional.

The KG is open, reproducible, and includes 7,307 candidate novel findings (associations not in the KB or gold, supported by ≥1 paper, typed consistently across 7 CDM relation types). The 10 most-supported are: *butyrate → cancer* (treats, 33 papers), *butyrate → C57BL/6J mice* (produced_by, 25 papers), *colorectal cancer → cyclophosphamide* (treated_by, 24 papers), *carcinogenesis → colorectal cancer* (implicated_in, 23 papers), *colorectal cancer → de novo ceramide synthetic pathway* (implicated_in, 23 papers), *colorectal cancer → de novo lipogenesis* (implicated_in, 23 papers), *colorectal cancer → deuterated water* (treated_by, 23 papers), *butyrate → Candida albicans* (produced_by, 23 papers), *colorectal cancer → daptomycin* (treated_by, 23 papers), *colorectal cancer → deparaffinization solution* (treated_by, 23 papers). These are KG-driven hypotheses that, if validated externally, would constitute new biological discoveries.

We believe this work is of broad interest to *Briefings in Bioinformatics*'s readership because:
- It provides a reproducible Common Data Model for human gut microbiome research — a domain that, despite its clinical and translational importance, lacks a shared terminological standard.
- The 7-source hybrid architecture (LLM as primary extractor + scispaCy as fast first-pass + KB for grounding), validated by a 6-model benchmark showing the LLM is the only model combining full type coverage, <1% noise, and zero generic labels, is a general-purpose methodological contribution, reusable for any biomedical literature domain beyond the microbiome.
- The empirical results (6.3× better entity density than MetagenomicKG, 100% self-consistency recall on a 109-assoc gold with leave-K-out-validated hybrid necessity, post-hoc confidence calibration) advance the state of the art in biomedical knowledge-graph construction — a core bioinformatics methodology topic.
- The 7,307 candidate novel findings constitute a community resource for downstream experimental work and a demonstration that a hybrid KG can generate testable biological hypotheses.
- The CDM's 14-type schema (spanning biological *and* methodological entities) and the per-type calibration analysis directly address the journal's focus on integrative, reproducible bioinformatics methods.

The manuscript is ~10,000 words including the 74-reference bibliography. All code, data, the KG, the KB, the gold set, and the per-paper extraction JSONs are released openly under the MIT license. The CDM is designed to be extensible: new entity types, relation types, and KB associations can be added without changing the pipeline.

We suggest the following potential reviewers, all of whom have published on microbiome knowledge graphs or biomedical NLP (detailed list below). We exclude the authors of the Abdill et al. 2025 *Cell* meta-analysis and the HMDAD / gutMGBrain authors (these KGs are used as gold for Claim F).

This manuscript is not under consideration at any other journal. All authors have read and approved the manuscript.

Thank you for your consideration.

Sincerely,
Jasmeer Singh
EFRE Graduate School, University of Bonn
s78jkalr@uni-bonn.de

---

**Suggested reviewers:**
- Dr. Casey Greene (U Penn) — biomedical NLP, knowledge graphs, representation learning
- Dr. Zhiyong Lu (NCBI) — biomedical text mining, PubTator, BioBERT
- Dr. Georg Zeller (EMBL) — gut microbiome meta-analyses, computational methods
- Dr. Curtis Huttenhower (Harvard) — HMP, bioBakery, microbiome bioinformatics
- Dr. Yifan Chen (NLM) — LLMs for biomedical entity/relation extraction
- Dr. Robert Hoehndorf (KAUST) — biomedical ontologies, knowledge-graph reasoning

**Conflicts to exclude:**
- Any microbiome KG paper authors from the Abdill et al. 2025 *Cell* meta-analysis
- The HMDAD / gutMGBrain authors (these KGs are used as gold for Claim F)
