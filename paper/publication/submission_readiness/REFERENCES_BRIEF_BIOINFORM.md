# Must-cite list — *Briefings in Bioinformatics* format

**Manuscript:** *Microbiome-CDM: An LLM-driven common data model and knowledge extraction pipeline for human microbiome literature*

*2026-11-07 render. Every entry is registry-verified (Crossref / PubMed / arXiv API / Hugging Face API / GitHub API, today) and recorded in `references_source/bibliography.json` (regenerate with `references_source/fetch_bibliography.py`; 56 records, 0 errors). Numbering below is provisional pipeline-phase order — BiB numbers by first appearance in the text, so RENUMBER at submission and cite [n–m] before punctuation.*

## Reference list

### Argument (Introduction) (provisional [1–10])

1. Abdill R, Graham S, Rubinetti V et al. Integration of 168,000 samples reveals global patterns of the human gut microbiome. *Cell* 2025;188:1100–1118.e17.
2. Gonçalves R, Musen M. The variable quality of metadata about biological samples used in biomedical experiments. *Sci Data* 2019;6:190021.
3. Geistlinger L, Mirzayi C, Zohra F et al. BugSigDB captures patterns of differential abundance across a broad range of host-associated microbial signatures. *Nat Biotechnol* 2023;42:790–802.
4. Langarica S, Kim Y, Alkhadrawi A et al. MINERVA—microbiome network research and visualization atlas: a scalable knowledge graph for mapping microbiome-disease associations. *Brief Bioinform* 2025;26:bbaf472.
5. Chirumbolo S. Methodological and statistical concerns in MINERVA microbiome-disease knowledge graph. *Brief Bioinform* 2025;26:bbaf673.
6. Langarica S, Kim Y, Alkhadrawi A et al. Response to ‘Methodological and statistical concerns in MINERVA microbiome–disease knowledge graph’ by Salvatore Chirumbolo. *Brief Bioinform* 2025;26:bbaf671.
7. Hogan W, Bartko A, Shang J et al. MiDRED: An Annotated Corpus for Microbiome Knowledge Base Construction. In: *Proceedings of the 23rd Workshop on Biomedical Natural Language Processing*, 2024, 398–408.
8. Hong G, Hindle V, Veasley N et al. DiMB-RE: mining the scientific literature for diet-microbiome associations. *J Am Med Inform Assoc* 2025;32:998–1006.
9. Higashi K, Nakagawa Z, Yamada T et al. Automated Harmonization and Large-Scale Integration of Heterogeneous Biomedical Sample Metadata Using Large Language Models. *medRxiv* 2024;2024.10.26.620145 (preprint).
10. Chen Q, Hu Y, Peng X et al. Benchmarking large language models for biomedical natural language processing applications and recommendations. *Nat Commun* 2025;16:3280.

### Annotated relation corpora used for audit (provisional [11–12])

11. Li J, Sun Y, Johnson R et al. BioCreative V CDR task corpus: a resource for chemical disease relation extraction. *Database (Oxford)* 2016;2016:baw068.
12. Luo L, Lai P, Wei C et al. BioRED: a rich biomedical relation extraction dataset. *Brief Bioinform* 2022;23:bbac282.

### NER programs, corpora and base models (provisional [13–23])

13. Wei C, Allot A, Lai P et al. PubTator 3.0: an AI-powered literature resource for unlocking biomedical knowledge. *Nucleic Acids Res* 2024;52:W540–W546.
14. Sänger M, Garda S, Wang X et al. HunFlair2 in a cross-corpus evaluation of biomedical named entity recognition and normalization tools. *Bioinformatics* 2024;40:btae564.
15. Akbik A, Bergmann T, Blythe D et al. FLAIR: An Easy-to-Use Framework for State-of-the-Art NLP. In: *Proceedings of the 2019 Conference of the North American Chapter of the Association for Computational Linguistics (Demonstrations)*, 2019, 54–59.
16. Neumann M, King D, Beltagy I et al. ScispaCy: Fast and Robust Models for Biomedical Natural Language Processing. In: *Proceedings of the 18th BioNLP Workshop and Shared Task*, 2019, 319–327.
17. Cohen K, Verspoor K, Fort K et al. The Colorado Richly Annotated Full Text (CRAFT) Corpus: Multi-Model Annotation in the Biomedical Domain. In: *Handbook of Linguistic Annotation*. Dordrecht: Springer, 2017, 1379–1394.
18. Kim J, Ohta T, Tsuruoka Y et al. Introduction to the bio-entity recognition task at JNLPBA. In: *Proceedings of the International Joint Workshop on Natural Language Processing in Biomedicine and its Applications - JNLPBA '04*, 2004, 70.
19. Pyysalo S, Ohta T, Rak R et al. Overview of the Cancer Genetics and Pathway Curation tasks of BioNLP Shared Task 2013. *BMC Bioinformatics* 2015;16:S2.
20. Lee J, Yoon W, Kim S et al. BioBERT: a pre-trained biomedical language representation model for biomedical text mining. *Bioinformatics* 2019;36:1234–1240.
21. Beltagy I, Lo K, Cohan A. SciBERT: A Pretrained Language Model for Scientific Text. In: *Proceedings of the 2019 Conference on Empirical Methods in Natural Language Processing and the 9th International Joint Conference on Natural Language Processing (EMNLP-IJCNLP)*, 2019, 3613–3618.
22. Zaratiana U, Tomeh N, Holat P et al. GLiNER: Generalist Model for Named Entity Recognition using Bidirectional Transformer. In: *Proceedings of the 2024 Conference of the North American Chapter of the Association for Computational Linguistics: Human Language Technologies (Volume 1: Long Papers)*, 2024, 5364–5376.
23. Zaratiana U, Pasternak G, Boyd O et al. GLiNER2: Schema-Driven Multi-Task Learning for Structured Information Extraction. In: *Proceedings of the 2025 Conference on Empirical Methods in Natural Language Processing: System Demonstrations*, 2025, 130–140.

### LLMs, embedding, inference and judging (provisional [24–38])

24. Grattafiori A, Dubey A, Jauhri A et al. The Llama 3 Herd of Models. *arXiv* 2024;arXiv:2407.21783.
25. Jiang AQ, Sablayrolles A, Mensch A et al. Mistral 7B. *arXiv* 2023;arXiv:2310.06825.
26. Abdin M, Aneja J, Awadalla H et al. Phi-3 Technical Report: A Highly Capable Language Model Locally on Your Phone. *arXiv* 2024;arXiv:2404.14219.
27. Guo D, Yang D, Zhang H et al. DeepSeek-R1 incentivizes reasoning in LLMs through reinforcement learning. *Nature* 2025;645:633–638.
28. Gemma Team, El Abd S, Aggarwal V et al. Gemma 4 Technical Report. *arXiv* 2026;arXiv:2607.02770.
29. Qwen, 2026-03-02 (accessed 2026-11-07): Qwen/Qwen3.5-4B model card, Hugging Face (repository), https://huggingface.co/Qwen/Qwen3.5-4B.
30. DeepSeek-AI, Xu A, Lin B et al. DeepSeek-V4: Towards Highly Efficient Million-Token Context Intelligence. *arXiv* 2026;arXiv:2606.19348.
31. DeepSeek-AI, 2026-08-01 (accessed 2026-11-07): deepseek-ai/DeepSeek-V4-Flash-0731 model card, Hugging Face (repository), https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash-0731.
32. DeepSeek-AI, 2026-10-16 (accessed 2026-11-07): deepseek-ai/DeepSeek-V4.1-Flash model card, Hugging Face (repository), https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash.
33. Zheng L, Chiang W, Sheng Y et al. Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena. *arXiv* 2023;arXiv:2306.05685.
34. Reimers N, Gurevych I. Sentence-BERT: Sentence Embeddings using Siamese BERT-Networks. In: *Proceedings of the 2019 Conference on Empirical Methods in Natural Language Processing and the 9th International Joint Conference on Natural Language Processing (EMNLP-IJCNLP)*, 2019, 3980–3990.
35. Sentence-Transformers, 2026-06-01 (accessed 2026-11-07): sentence-transformers/all-MiniLM-L6-v2 model card, Hugging Face (repository), https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2.
36. Kwon W, Li Z, Zhuang S et al. Efficient Memory Management for Large Language Model Serving with PagedAttention. In: *Proceedings of the 29th Symposium on Operating Systems Principles*, 2023, 611–626.
37. Ollama, Release 0.32.9 (cluster version; accessed 2026-11-07): Ollama local large-language-model runtime, GitHub (repository), https://github.com/ollama/ollama (MIT license).
38. Lin J, Tang J, Tang H et al. AWQ: Activation-aware Weight Quantization for LLM Compression and Acceleration. *arXiv* 2023;arXiv:2306.00978.

### Vocabularies, services, archives and standards (provisional [39–52])

39. Schoch C, Ciufo S, Domrachev M et al. NCBI Taxonomy: a comprehensive update on curation, resources and tools. *Database (Oxford)* 2020;2020:baaa062.
40. Brown G, Hem V, Katz K et al. Gene: a gene-centered information resource at NCBI. *Nucleic Acids Res* 2015;43:D36–D42.
41. Lipscomb CE. Medical Subject Headings (MeSH). *Bull Med Libr Assoc* 2000;88:265–6.
42. Davis A, Wiegers T, Sciaky D et al. Comparative Toxicogenomics Database: update 2027. *Nucleic Acids Res* 2026;gkag1041.
43. Barrett T, Clark K, Gevorgyan R et al. BioProject and BioSample databases at NCBI: facilitating capture and organization of metadata. *Nucleic Acids Res* 2012;40:D57–D63.
44. Leinonen R, Sugawara H, Shumway M et al. The Sequence Read Archive. *Nucleic Acids Res* 2011;39:D19–D21.
45. Vasilevsky N, Matentzoglu N, Toro S et al. Mondo: Unifying diseases for the world, by the world. *medRxiv* 2022;2022.04.13.22273750 (preprint).
46. Gargano M, Matentzoglu N, Coleman B et al. The Human Phenotype Ontology in 2024: phenotypes around the world. *Nucleic Acids Res* 2024;52:D1333–D1346.
47. Bodenreider O. The Unified Medical Language System (UMLS): integrating biomedical terminology. *Nucleic Acids Res* 2004;32:267D–270.
48. Whetzel P, Noy N, Shah N et al. BioPortal: enhanced functionality via new Web services from the National Center for Biomedical Ontology to access and use ontologies in software applications. *Nucleic Acids Res* 2011;39:W541–W545.
49. Côté R, Jones P, Apweiler R et al. The Ontology Lookup Service, a lightweight cross-platform tool for controlled vocabulary queries. *BMC Bioinformatics* 2006;7:97.
50. Hripcsak G, Duke JD, Shah NH et al. Observational Health Data Sciences and Informatics (OHDSI): Opportunities for Observational Researchers. In: *MEDINFO 2015: eHealth-enabled Health*. Amsterdam: IOS Press, 2015, 574–79 (see note).
51. Yilmaz P, Kottmann R, Field D et al. Minimum information about a marker gene sequence (MIMARKS) and minimum information about any (x) sequence (MIxS) specifications. *Nat Biotechnol* 2011;29:415–420.
52. Janssens Y, Nielandt J, Bronselaer A et al. Disbiome database: linking the microbiome to disease. *BMC Microbiol* 2018;18:50.

### Statistics (provisional [53–55])

53. Wilson E. Probable Inference, the Law of Succession, and Statistical Inference. *J Am Stat Assoc* 1927;22:209–212.
54. Efron B, Tibshirani R. An Introduction to the Bootstrap. Boston: Springer, 1993.
55. Cohen J. A Coefficient of Agreement for Nominal Scales. *Educ Psychol Meas* 1960;20:37–46.

## In-text style (apply at submission)

Numbers enclosed in square brackets, before the punctuation: e.g. *'…curated differential-abundance evidence [3, 11, 12]…'*. 1–3 authors listed in full; 4+ → first three + et al. Do not include papers in preparation/submitted (a registered preprint is fine, labelled as such).

## Notes and open decisions (do not silently resolve)

- **OHDSI/Hripcsak [50]**: MEDINFO-2015 book chapter; Crossref registers only the start page 574 — the end page 579 comes from IOS chapter pagination, confirm against the PDF if exact ranges are required.
- **Barrett [43], Leinonen [44], Brown [40], Gargano [46]**: Crossref 'issued' = online year; the shown year is the volume's print year (per the earlier verification notes in VERIFIED_REFERENCES.md).
- **Davis/CTD [42]**: advance access; volume pages must be updated when the 2027-update issue is assigned.
- **DeepSeek-V4.1-Flash [32]**: no arXiv report; the model repo ships its own tech-report PDF — cite the model card with an access date.
- **DeepSeek-V4 [30]**: arXiv:2606.19348 verified (register says DeepSeek-AI as first author); the checkpoint actually run was deepseek-ai/DeepSeek-V4-Flash-0731 [31].
- **Qwen3.5-4B [29]**: no technical report exists — model card only (do not substitute the Qwen3 report).
- **Gemma [28]**: arXiv:2607.02770 verified via the HF model card of the checkpoint run (google/gemma-4-E4B-it-qat-w4a16-ct).
- **Mondo [45]**: medRxiv preprint; check for a peer-reviewed version before typesetting.
- **GLiNER-BioMed**: the Bioinformatics 2026 paper needs author confirmation that it describes the `gliner-large-v2.5-biomed` checkpoint actually run; else cite that model card as well.
- **OMOP vocabularies**: record the Athena/vocabulary release version + access date in Methods; the OHDSI paper covers the initiative, not the vocabulary snapshot.
- **FhGenie (Fraunhofer on-prem gateway)**: infrastructure, not cited — describe in Methods.
- **S1000 species corpus**: NOT included — the comparison is not registered yet; register it first, then cite what was actually used.
- **Not essential here** (kept in the wider verified list): SapBERT (`liu2021sapbert`, NAACL 2021) if entity-linking baselines are discussed; the spaCy framework itself is covered by the scispaCy paper [16].
