# References needed

No reference has been chosen yet. Bibliographic details were deliberately **not** written from memory: each entry must be taken from the source itself (publisher page, PubMed, or the tool's documented "how to cite"). A placeholder is better than a wrong citation.

## A. Argument citations (Introduction; `[CITE: Rn]` in the text)

| ID | Claim the reference must support | Notes |
|---|---|---|
| R1 | The Abdill et al. (2025) human microbiome compendium; 168,464 samples | Primary citation for the compendium; numbers must match our recomputation [C06] |
| R2 | Sequence Read Archive / INSDC as the source archive | NCBI SRA database paper or NAR database-issue update |
| R3 | Public-archive sample metadata are sparse and inconsistent | Prefer a study that quantifies this for microbiome / SRA metadata |
| R4 | Manual literature curation of study metadata does not scale | A curation-effort or curated-database paper |
| R5 | Trained biomedical NER is fast and well characterised on benchmark corpora | Ideally a survey plus the BC5CDR / BioRED papers (see B) |
| R6 | LLMs for biomedical information extraction without task-specific training | Prefer an evaluation study, including evidence of the limitations |

## B. Resources and tools used (Methods; each must be cited)

| Group | Items |
|---|---|
| Gold-standard corpora | BC5CDR; BioRED |
| Trained / reference NER | PubTator3; HunFlair2 (Flair); scispaCy (and its model corpora: BC5CDR, BioNLP13CG, CRAFT, JNLPBA); the BERT / SciBERT checkpoints used (cite model cards and base models) |
| Zero-shot NER | GLiNER; GLiNER2; GLiNER-BioMed (v2.5 checkpoints) |
| LLMs | Qwen3.5-4B; Gemma-4-E4B; Llama-3.1-8B-Instruct; Mistral-7B-Instruct-v0.3; Phi-3.5-mini-instruct; DeepSeek-R1-Distill-Qwen-7B; plus quantisation methods (AWQ) where required |
| Inference | vLLM |
| Vocabularies and services | NCBI Taxonomy; NCBI Gene; MeSH; CTD (incl. MEDIC); Mondo; HPO; UMLS; BioPortal; OLS; OMOP vocabularies |
| Knowledge graphs | CTD curated associations; Disbiome |
| Standards discussed | OMOP CDM; MIxS (if alignment is discussed) |
| Statistics | document bootstrap / paired bootstrap; Cohen's κ (reported only as agreement between two models) |
| Data / licences | Creative Commons licence definitions (rights layers) |

## C. Checks before submission

- Every `[CITE: …]` resolved; no citation added for a claim the paper no longer makes.
- Model versions and checkpoint identifiers match `run_registry` / benchmark metadata exactly.
- Target journal's data-availability and software-citation requirements confirmed.
