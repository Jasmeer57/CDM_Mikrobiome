# Verified references

*2026-11-02. Every entry was resolved from its registry (Crossref, arXiv API, PubMed, Hugging Face API), never written from memory. Machine-readable record with full author lists: `references_source/bibliography.json` (regenerate with `references_source/fetch_bibliography.py`). Citation keys `[@key]` are the ones now used in the drafts.*

**41 / 41 references verified.** Unresolved points are listed at the end.

## Argument citations (Introduction R1–R6)

- **[@abdill2025]** Abdill R, Graham S, Rubinetti V et al. (2025). Integration of 168,000 samples reveals global patterns of the human gut microbiome. *Cell 188 (4):1100-1118.e17*. doi:10.1016/j.cell.2024.12.017. — R1; verified via Crossref, 2026-11-02.
- **[@leinonen2011]** Leinonen R, Sugawara H, Shumway M et al. (2010). The Sequence Read Archive. *Nucleic Acids Research 39 (Database):D19-D21*. doi:10.1093/nar/gkq1019. — R2; verified via Crossref, 2026-11-02.
  - Note: Crossref 'issued' = online date (2010); print issue Nucleic Acids Res 39 (2011).
- **[@goncalves2019]** Gonçalves R, Musen M (2019). The variable quality of metadata about biological samples used in biomedical experiments. *Scientific Data 6 (1):190021*. doi:10.1038/sdata.2019.21. — R3; verified via Crossref, 2026-11-02.
- **[@geistlinger2023]** Geistlinger L, Mirzayi C, Zohra F et al. (2023). BugSigDB captures patterns of differential abundance across a broad range of host-associated microbial signatures. *Nature Biotechnology 42 (5):790-802*. doi:10.1038/s41587-023-01872-y. — R4; verified via Crossref, 2026-11-02.
- **[@li2016bc5cdr]** Li J, Sun Y, Johnson R et al. (2016). BioCreative V CDR task corpus: a resource for chemical disease relation extraction. *Database 2016:baw068*. doi:10.1093/database/baw068. — R5; corpus; verified via Crossref, 2026-11-02.
- **[@luo2022biored]** Luo L, Lai P, Wei C et al. (2022). BioRED: a rich biomedical relation extraction dataset. *Briefings in Bioinformatics 23 (5):bbac282*. doi:10.1093/bib/bbac282. — R5; corpus; verified via Crossref, 2026-11-02.
- **[@sanger2024hunflair2]** Sänger M, Garda S, Wang X et al. (2024). HunFlair2 in a cross-corpus evaluation of biomedical named entity recognition and normalization tools. *Bioinformatics 40 (10):btae564*. doi:10.1093/bioinformatics/btae564. — R5; tool; verified via Crossref, 2026-11-02.
- **[@chen2025llmbench]** Chen Q, Hu Y, Peng X et al. (2025). Benchmarking large language models for biomedical natural language processing applications and recommendations. *Nature Communications 16 (1):3280*. doi:10.1038/s41467-025-56989-2. — R6; verified via Crossref, 2026-11-02.

## NER tools, corpora and base models

- **[@wei2024pubtator3]** Wei C, Allot A, Lai P et al. (2024). PubTator 3.0: an AI-powered literature resource for unlocking biomedical knowledge. *Nucleic Acids Research 52 (W1):W540-W546*. doi:10.1093/nar/gkae235. — tool; verified via Crossref, 2026-11-02.
- **[@akbik2019flair]** Akbik A, Bergmann T, Blythe D et al. (2019). FLAIR: An Easy-to-Use Framework for State-of-the-Art NLP. *Proceedings of the 2019 Conference of the North American Chapter of the Association for Computational Linguistics (Demonstrations):54-59*. doi:10.18653/v1/n19-4010. — tool; verified via Crossref, 2026-11-02.
- **[@neumann2019scispacy]** Neumann M, King D, Beltagy I et al. (2019). ScispaCy: Fast and Robust Models for Biomedical Natural Language Processing. *Proceedings of the 18th BioNLP Workshop and Shared Task:319-327*. doi:10.18653/v1/w19-5034. — tool; verified via Crossref, 2026-11-02.
- **[@cohen2017craft]** Cohen K, Verspoor K, Fort K et al. (2017). The Colorado Richly Annotated Full Text (CRAFT) Corpus: Multi-Model Annotation in the Biomedical Domain. *Handbook of Linguistic Annotation:1379-1394*. doi:10.1007/978-94-024-0881-2_53. — model training corpus; verified via Crossref, 2026-11-02.
  - Note: Training corpus of scispaCy en_ner_craft_md.
- **[@kim2004jnlpba]** Kim J, Ohta T, Tsuruoka Y et al. (2004). Introduction to the bio-entity recognition task at JNLPBA. *Proceedings of the International Joint Workshop on Natural Language Processing in Biomedicine and its Applications - JNLPBA '04:70*. doi:10.3115/1567594.1567610. — model training corpus; verified via Crossref, 2026-11-02.
- **[@pyysalo2015bionlp13]** Pyysalo S, Ohta T, Rak R et al. (2015). Overview of the Cancer Genetics and Pathway Curation tasks of BioNLP Shared Task 2013. *BMC Bioinformatics 16 (S10):S2*. doi:10.1186/1471-2105-16-s10-s2. — model training corpus; verified via Crossref, 2026-11-02.
- **[@lee2019biobert]** Lee J, Yoon W, Kim S et al. (2019). BioBERT: a pre-trained biomedical language representation model for biomedical text mining. *Bioinformatics 36 (4):1234-1240*. doi:10.1093/bioinformatics/btz682. — base model; verified via Crossref, 2026-11-02.
  - Note: Base of alvaroalon2/biobert_{diseases,chemical,genetic}_ner; also cite those model cards.
- **[@beltagy2019scibert]** Beltagy I, Lo K, Cohan A (2019). SciBERT: A Pretrained Language Model for Scientific Text. *Proceedings of the 2019 Conference on Empirical Methods in Natural Language Processing and the 9th International Joint Conference on Natural Language Processing (EMNLP-IJCNLP):3613-3618*. doi:10.18653/v1/d19-1371. — base model; verified via Crossref, 2026-11-02.
  - Note: Base of fran-martinez/scibert_scivocab_cased_ner_jnlpba (model card cites arXiv 1903.10676).
- **[@zaratiana2024gliner]** Zaratiana U, Tomeh N, Holat P et al. (2024). GLiNER: Generalist Model for Named Entity Recognition using Bidirectional Transformer. *Proceedings of the 2024 Conference of the North American Chapter of the Association for Computational Linguistics: Human Language Technologies (Volume 1: Long Papers):5364-5376*. doi:10.18653/v1/2024.naacl-long.300. — tool; verified via Crossref, 2026-11-02.
- **[@zaratiana2025gliner2]** Zaratiana U, Pasternak G, Boyd O et al. (2025). GLiNER2: Schema-Driven Multi-Task Learning for Structured Information Extraction. *Proceedings of the 2025 Conference on Empirical Methods in Natural Language Processing: System Demonstrations:130-140*. doi:10.18653/v1/2025.emnlp-demos.10. — tool; verified via Crossref, 2026-11-02.
- **[@yazdani2026glinerbiomed]** Yazdani A, Stepanov I, Teodoro D (2026). GLiNER-BioMed: a suite of efficient models for open biomedical named entity recognition. *Bioinformatics 42 (6):btag322*. doi:10.1093/bioinformatics/btag322. — tool (see note); verified via Crossref, 2026-11-02.
  - Note: **Unresolved:** the checkpoint used (`Ihor/gliner-large-v2.5-biomed`) has no model-card citation; whether this paper describes it must be confirmed by the authors. Otherwise cite the model card URL plus GLiNER.

## LLMs, inference and quantisation

- **[@kwon2023vllm]** Kwon W, Li Z, Zhuang S et al. (2023). Efficient Memory Management for Large Language Model Serving with PagedAttention. *Proceedings of the 29th Symposium on Operating Systems Principles:611-626*. doi:10.1145/3600006.3613165. — inference; verified via Crossref, 2026-11-02.
- **[@lin2023awq]** Ji Lin, Jiaming Tang, Haotian Tang et al. (2023). AWQ: Activation-aware Weight Quantization for LLM Compression and Acceleration. *arXiv*. doi:10.48550/arXiv.2306.00978. — quantisation; verified via arXiv API, 2026-11-02.
  - Note: AWQ quantisation used for 4 of 6 LLM checkpoints.
- **[@grattafiori2024llama3]** Aaron Grattafiori, Abhimanyu Dubey, Abhinav Jauhri et al. (2024). The Llama 3 Herd of Models. *arXiv*. doi:10.48550/arXiv.2407.21783. — LLM; verified via arXiv API, 2026-11-02.
  - Note: Official reference for Llama 3.1 (the herd paper covers the 3.1 models); the arXiv abstract does not name '3.1'. Checkpoint used: hugging-quants/Meta-Llama-3.1-8B-Instruct-AWQ-INT4.
- **[@jiang2023mistral]** Albert Q. Jiang, Alexandre Sablayrolles, Arthur Mensch et al. (2023). Mistral 7B. *arXiv*. doi:10.48550/arXiv.2310.06825. — LLM; verified via arXiv API, 2026-11-02.
  - Note: Mistral 7B base paper; the model used is v0.3 Instruct (TechxGenus AWQ). No separate v0.3 paper.
- **[@abdin2024phi3]** Marah Abdin, Jyoti Aneja, Hany Awadalla et al. (2024). Phi-3 Technical Report: A Highly Capable Language Model Locally on Your Phone. *arXiv*. doi:10.48550/arXiv.2404.14219. — LLM; verified via arXiv API, 2026-11-02.
  - Note: v4 abstract covers phi-3.5. Checkpoint used: thesven/Phi-3.5-mini-instruct-awq.
- **[@guo2025deepseekr1]** Guo D, Yang D, Zhang H et al. (2025). DeepSeek-R1 incentivizes reasoning in LLMs through reinforcement learning. *Nature 645 (8081):633-638*. doi:10.1038/s41586-025-09422-z. — LLM; verified via Crossref, 2026-11-02.
  - Note: Peer-reviewed version of arXiv 2501.12948. Checkpoint used: casperhansen/deepseek-r1-distill-qwen-7b-awq.
- **[@gemma2026gemma4]** Gemma Team, Sherif El Abd, Vaibhav Aggarwal et al. (2026). Gemma 4 Technical Report. *arXiv*. doi:10.48550/arXiv.2607.02770. — LLM; verified via arXiv API, 2026-11-02.
  - Note: Cited by the model card of google/gemma-4-E4B-it-qat-w4a16-ct.
- **[@qwen35card]** Qwen (n.d.). Qwen/Qwen3.5-4B (model card). *Hugging Face*. https://huggingface.co/Qwen/Qwen3.5-4B. — LLM (model card); verified via Hugging Face API, 2026-11-02.
  - Note: **No verified technical report for Qwen3.5.** The Qwen3 report (arXiv 2505.09388) describes an earlier generation and is not substituted. Cite the model card with access date.

## Vocabularies, knowledge graphs, mapping services and standards

- **[@schoch2020taxonomy]** Schoch C, Ciufo S, Domrachev M et al. (2020). NCBI Taxonomy: a comprehensive update on curation, resources and tools. *Database 2020:baaa062*. doi:10.1093/database/baaa062. — vocabulary; verified via Crossref, 2026-11-02.
- **[@brown2015gene]** Brown G, Hem V, Katz K et al. (2014). Gene: a gene-centered information resource at NCBI. *Nucleic Acids Research 43 (D1):D36-D42*. doi:10.1093/nar/gku1055. — vocabulary; verified via Crossref, 2026-11-02.
  - Note: Online 2014; print issue 2015 (vol 43).
- **[@davis2026ctd]** Davis A, Wiegers T, Sciaky D et al. (2026). Comparative Toxicogenomics Database: update 2027. *Nucleic Acids Research:gkag1041*. doi:10.1093/nar/gkag1041. — vocabulary + KG; verified via Crossref, 2026-11-02.
  - Note: Current CTD update; reference data downloaded 2026-11-02 (`data/reference_kg/raw/DOWNLOADED_AT`). Cite with access date.
- **[@lipscomb2000mesh]** Lipscomb CE (2000). Medical Subject Headings (MeSH). *Bulletin of the Medical Library Association 88 (3):265-6*. PMID 10928714 · PMC35238. — vocabulary; verified via PubMed, 2026-11-02.
  - Note: No DOI exists; verified via PubMed/PMC.
- **[@vasilevsky2022mondo]** Vasilevsky N, Matentzoglu N, Toro S et al. (2022). Mondo: Unifying diseases for the world, by the world. *medRxiv*. doi:10.1101/2022.04.13.22273750. — vocabulary; verified via Crossref (posted-content; venue from `institution[0].name`), 2026-11-08. No peer-reviewed version exists (Europe PMC: preprint only).
  - Note: medRxiv preprint (Crossref `publisher` field: openRxiv; venue taken from `institution`). Europe PMC search (2026-11-08): preprint only, no journal version exists.
- **[@gargano2024hpo]** Gargano M, Matentzoglu N, Coleman B et al. (2023). The Human Phenotype Ontology in 2024: phenotypes around the world. *Nucleic Acids Research 52 (D1):D1333-D1346*. doi:10.1093/nar/gkad1005. — vocabulary; verified via Crossref, 2026-11-02.
  - Note: Online 2023; print issue 2024 (vol 52).
- **[@janssens2018disbiome]** Janssens Y, Nielandt J, Bronselaer A et al. (2018). Disbiome database: linking the microbiome to disease. *BMC Microbiology 18 (1):50*. doi:10.1186/s12866-018-1197-5. — KG; verified via Crossref, 2026-11-02.
- **[@bodenreider2004umls]** Bodenreider O (2004). The Unified Medical Language System (UMLS): integrating biomedical terminology. *Nucleic Acids Research 32 (90001):267D-270*. doi:10.1093/nar/gkh061. — mapping service; verified via Crossref, 2026-11-02.
- **[@whetzel2011bioportal]** Whetzel P, Noy N, Shah N et al. (2011). BioPortal: enhanced functionality via new Web services from the National Center for Biomedical Ontology to access and use ontologies in software applications. *Nucleic Acids Research 39 (suppl):W541-W545*. doi:10.1093/nar/gkr469. — mapping service; verified via Crossref, 2026-11-02.
- **[@cote2006ols]** Côté R, Jones P, Apweiler R et al. (2006). The Ontology Lookup Service, a lightweight cross-platform tool for controlled vocabulary queries. *BMC Bioinformatics 7 (1):97*. doi:10.1186/1471-2105-7-97. — mapping service; verified via Crossref, 2026-11-02.
- **[@hripcsak2015ohdsi]** Hripcsak G, Duke J D, Shah N H et al. (2015). Observational Health Data Sciences and Informatics (OHDSI): Opportunities for Observational Researchers. *Studies in Health Technology and Informatics 216:574-578*. doi:10.3233/978-1-61499-564-7-574. — standard (OMOP); verified via PubMed (PMID 26262116) + Europe PMC (volume/pages), 2026-11-08. The Crossref book-chapter record packs the whole name into `family` ("Hripcsak George") and carries no volume/pages, so the record is routed via PMID.
- **[@yilmaz2011mixs]** Yilmaz P, Kottmann R, Field D et al. (2011). Minimum information about a marker gene sequence (MIMARKS) and minimum information about any (x) sequence (MIxS) specifications. *Nature Biotechnology 29 (5):415-420*. doi:10.1038/nbt.1823. — standard (MIxS); verified via Crossref, 2026-11-02.

## Statistics

- **[@efron1993bootstrap]** Efron B, Tibshirani R (1993). An Introduction to the Bootstrap. *Springer US*. doi:10.1007/978-1-4899-4541-9. — statistics; verified via Crossref, 2026-11-02.
  - Note: Springer reprint DOI of the 1993 Chapman & Hall monograph.
- **[@cohen1960kappa]** Cohen J (1960). A Coefficient of Agreement for Nominal Scales. *Educational and Psychological Measurement 20 (1):37-46*. doi:10.1177/001316446002000104. — statistics; verified via Crossref, 2026-11-02.
  - Note: Used only for agreement between two model judges, never as inter-annotator agreement.

## Documentation without a paper (cite as web resources with access date)

- Hugging Face model cards for every checkpoint actually run (exact IDs in `outputs/results/ner_fair_bench/fair_ner_metrics.json` → `meta.hf_id`, and `src/cdm_pipeline/ner/registry.py`).
- scispaCy model packages: en_ner_bc5cdr_md, en_ner_craft_md, en_ner_jnlpba_md, en_ner_bionlp13cg_md, en_core_sci_lg (cite with the scispaCy paper).
- Creative Commons licence deeds (CC BY 4.0, CC0, CC BY-NC, CC BY-NC-SA, CC BY-NC-ND), for the rights layers.
- OMOP standardised vocabularies (Athena) release used for the Mondo/HPO lookups: version and date to be read from the vocabulary files.

## Resolved 2026-11-08 (registry-verified; nothing was guessed)

1. **GLiNER v2.5 biomed checkpoint — resolved:** the GLiNER-BioMed paper (doi:10.1093/bioinformatics/btag322, arXiv 2504.00676; Yazdani, Stepanov, Teodoro) released exactly six v1.0 models (`Ihor/gliner-biomed-{small,base,large}-v1.0` + bi-encoder variants, HF updated 2025-07). The run checkpoint `Ihor/gliner-large-v2.5-biomed` (HF created 2026-02-18, no model card) is a later release by co-author Stepanov and is **not** described in the paper. The manuscript never cites btag322 for the v2.5 checkpoint — the text cites `zaratiana2025gliner2` (GLiNER2, EMNLP demos 2025) for the v2.5-medium result (H06-scale usage of v2.5-biomed carries no paper attribution in the text). No in-text change needed; `yazdani2026glinerbiomed` remains in the bibliography uncited.
2. **Qwen3.5-4B — resolved (status confirmed):** no technical report exists; the Hugging Face model card (last modified 2026-03-02) is the canonical citation, recorded via the HF API. Do not substitute the Qwen3 report (arXiv 2505.09388), which describes an earlier generation.
3. **Mondo — resolved:** preprint only; Europe PMC title search (2026-11-08) found no journal-published version. Cite as medRxiv preprint.
4. **Journal style:** print-year vs online-year conventions (SRA, HPO, NCBI Gene) — still open (cosmetic; author choice).
5. **OMOP vocabulary version — resolved:** recorded from the local OMOP CDM v5 bundle (`outputs/results/omop_vocab/VOCABULARY.csv`, Athena download 2026-10-23): **Mondo v2026-07-06, HPO v2026-06-23**. To be stated in the manuscript’s vocabulary-grounding sentence or Methods note if the authors want version pinning in text.

## Added 2026-11-03 (BiB positioning; verified on Crossref by DOI)

| Key | Reference | DOI |
|---|---|---|
| langarica2025minerva | Langarica S, Kim YT, Alkhadrawi A, et al. MINERVA—microbiome network research and visualization atlas: a scalable knowledge graph for mapping microbiome-disease associations. *Briefings in Bioinformatics* 2025 | 10.1093/bib/bbaf472 |
| chirumbolo2025minerva | Chirumbolo S. Methodological and statistical concerns in MINERVA microbiome-disease knowledge graph. *Briefings in Bioinformatics* 2025 | 10.1093/bib/bbaf673 |
| langarica2025response | Langarica S, Kim YT, Alkhadrawi A, et al. Response to 'Methodological and statistical concerns in MINERVA microbiome–disease knowledge graph' by Salvatore Chirumbolo. *Briefings in Bioinformatics* 2025 | 10.1093/bib/bbaf671 |
| hogan2024midred | Hogan W, Bartko A, Shang J, et al. MiDRED: An Annotated Corpus for Microbiome Knowledge Base Construction. *Proceedings of the 23rd Workshop on Biomedical Natural Language Processing (BioNLP)* 2024 | 10.18653/v1/2024.bionlp-1.31 |
| hong2025dimbre | Hong G, Hindle V, Veasley NM, et al. DiMB-RE: mining the scientific literature for diet-microbiome associations. *JAMIA* 2025 | 10.1093/jamia/ocaf054 |
| higashi2024harmonization | Higashi, Nakagawa, Yamada, et al. Automated Harmonization and Large-Scale Integration of Heterogeneous Biomedical Sample Metadata Using Large Language Models. *bioRxiv* 2024 (preprint) | 10.1101/2024.10.26.620145 |
| liu2021sapbert | Liu F, Shareghi E, Meng Z, et al. Self-Alignment Pretraining for Biomedical Entity Representations. *Proceedings of NAACL-HLT* 2021 | 10.18653/v1/2021.naacl-main.334 |

## Added 2026-11-07 (registry re-verified full list; BiB render)

All 56 records were re-fetched from their registries (Crossref, PubMed, arXiv API, Hugging Face API,
GitHub API) on 2026-11-07 — zero failures; `bibliography_2026-11-02.json.bak` holds the previous
snapshot. New records (none previously in the list):

- **[@barrett2012bioproject]** Barrett T, Clark K, Gevorgyan R et al. (2012). BioProject and BioSample databases at NCBI: facilitating capture and organization of metadata. *Nucleic Acids Research 40 (D1):D57-D63*. doi:10.1093/nar/gkr1163. — C05 paper↔BioProject linking; Crossref 'issued' 2011 (online), print vol 40 = 2012.
- **[@wilson1927]** Wilson EB (1927). Probable Inference, the Law of Succession, and Statistical Inference. *Journal of the American Statistical Association 22 (158):209-212*. doi:10.1080/01621459.1927.10502953. — Wilson 95% intervals used throughout the audits.
- **[@zheng2023mtbench]** Zheng L, Chiang W-L, Sheng Y et al. (2023). Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena. *arXiv*. doi:10.48550/arXiv.2306.05685. — method reference for the LLM-judge tiers (NeurIPS 2023 Datasets & Benchmarks track).
- **[@deepseek2026v4]** DeepSeek-AI, Xu A, Lin B et al. (2026). DeepSeek-V4: Towards Highly Efficient Million-Token Context Intelligence. *arXiv*. doi:10.48550/arXiv.2606.19348. — tech report of the checkpoint used by the 2026-11-03 string-level judge: `deepseek-ai/DeepSeek-V4-Flash-0731`.
- **[@deepseekv4flashcard]** DeepSeek-AI (n.d.). deepseek-ai/DeepSeek-V4-Flash-0731 (model card). *Hugging Face*. https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash-0731 — checkpoint card; arXiv tag on the card.
- **[@deepseekv41card]** DeepSeek-AI (n.d.). deepseek-ai/DeepSeek-V4.1-Flash (model card). *Hugging Face*. https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash — the 2026-11-07 evidence-anchored judge; **no arXiv report exists** (the repo ships its own `DeepSeek_V41_Tech_Report.pdf`); cite card with access date.
- **[@liu2019sbert]** Reimers N, Gurevych I (2019). Sentence-BERT: Sentence Embeddings using Siamese BERT-Networks. *Proceedings of the 2019 Conference on Empirical Methods in Natural Language Processing and the 9th International Joint Conference on Natural Language Processing (EMNLP-IJCNLP)*:3980-3990. doi:10.18653/v1/d19-1410. — method behind the G6/G7 embedding stage.
- **[@minilmcard]** Sentence-Transformers (n.d.). sentence-transformers/all-MiniLM-L6-v2 (model card). *Hugging Face*. https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2 — checkpoint actually loaded in `gap_embed.py` (G6 triple↔term + G7 crosswalk); base model `nreimers/MiniLM-L6-H384-uncased`.
- **[@ollama2026]** Ollama (n.d.). Ollama (software repository). *GitHub*. https://github.com/ollama/ollama — runtime for the historical Qwen-Ollama section-NER run (186,024 rows); cite Release 0.32.9 + access date. MIT.

The 2026-11-03 positioning-table entries (MINERVA + comment + reply, MiDRED, DiMB-RE, the
metadata-harmonisation preprint) are now registry records too (`langarica2025_*`,
`hogan2024midred` now pages 398–408, `hong2025dimbre` now 32:998–1006,
`higashi2024harmonization`). The BiB-formatted must-cite render is
`REFERENCES_BRIEF_BIOINFORM.md` (55 numbered entries; regenerate with
`references_source/fetch_bibliography.py` + `references_source/render_bib_style.py`).

Author initials beyond the first author come from registry given names and should be checked against the article. Do not cite 10.1101/2024.10.26.620145 as "EMBERS": that name did not match the registered title.
