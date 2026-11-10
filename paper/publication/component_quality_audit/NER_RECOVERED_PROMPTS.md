# Recovered LLM prompts and few-shot examples (component I correction)

*Recovered 2026-11-04T16:32:23 from `src/scripts/ner_fair_bench/fairbench.py` (`llm_system()`, `fewshot()`, `run_llm()`). Machine-readable copy: `diagnostics/results/ner_recovered_prompts.json`.*

Recovery is **by reconstruction from the scoring code plus verification against the run metadata**, not by re-running any model. The few-shot document ids recovered here are compared against `fewshot_train_pmids` recorded in each prediction file's `_meta`; all twelve 3-shot runs agree, so the examples are confirmed rather than merely plausible.

## BC5CDR — system prompt (verbatim)

```text
You are an expert biomedical named-entity annotator. Find every entity of the types below in the text. Copy each entity string EXACTLY as it appears (same spelling, case and spacing); do not expand abbreviations - an abbreviation is its own entity. List each distinct string once per type.
Types:
- Chemical: chemicals and drugs, including abbreviations and specific chemical classes
- Disease: diseases, disorders, syndromes, signs and symptoms, including abbreviations
Return ONLY JSON: {"entities": [{"text": "...", "type": "<one of the types>"}]}
```

## BC5CDR — 3-shot examples (seed 0, train split only)

Train PMIDs used as shots (identical for all six LLMs): `12523465, 7053303, 12695819`

**shot message 1 — `user`**

```text
Text:
Visual hallucinations associated with zonisamide. Zonisamide is a broad-spectrum antiepileptic drug used to treat various types of seizures. Although visual hallucinations have not been reported as an adverse effect of this agent, we describe three patients who experienced complex visual hallucinations and altered mental status after zonisamide treatment was begun or its dosage increased. All three had been diagnosed earlier with epilepsy, and their electroencephalogram (EEG) findings were abnormal. During monitoring, visual hallucinations did not correlate with EEG readings, nor did video recording capture any of the described events. None of the patients had experienced visual hallucinations before this event. The only recent change in their treatment was the introduction or increased dosage of zonisamide. With either discontinuation or decreased dosage of the drug the symptoms disappeared and did not recur. Further observations and reports will help clarify this adverse effect. Until then, clinicians need to be aware of this possible complication associated with zonisamide.
```

**shot message 2 — `assistant`**

```text
{"entities": [{"text": "Visual hallucinations", "type": "Disease"}, {"text": "zonisamide", "type": "Chemical"}, {"text": "Zonisamide", "type": "Chemical"}, {"text": "seizures", "type": "Disease"}, {"text": "visual hallucinations", "type": "Disease"}, {"text": "epilepsy", "type": "Disease"}]}
```

**shot message 3 — `user`**

```text
Text:
Age and renal clearance of cimetidine. In 35 patients (ages 20 to 86 yr) receiving cimetidine therapeutically two serum samples and all urine formed in the interim were collected for analysis of cimetidine by high-pressure liquid chromatography and for creatinine. Cimetidine clearance decreased with age. The extrapolated 6-hr serum concentration of cimetidine per unit dose, after intravenous cimetidine, increased with age of the patients. The ratio of cimetidine clearance to creatinine clearance (Rc) averaged 4.8 +/- 2.0, indicating net tubular secretion for cimetidine. Rc seemed to be independent of age and decreased with increasing serum concentration of cimetidine, suggesting that secretion of cimetidine is a saturable process. There was only one case of dementia possibly due to cimetidine (with a drug level of 1.9 microgram/ml 6 hr after a dose) in a group of 13 patients without liver or kidney disease who had cimetidine levels above 1.25 microgram/ml. Thus, high cimetidine levels alone do not always induce dementia.
```

**shot message 4 — `assistant`**

```text
{"entities": [{"text": "cimetidine", "type": "Chemical"}, {"text": "creatinine", "type": "Chemical"}, {"text": "Cimetidine", "type": "Chemical"}, {"text": "dementia", "type": "Disease"}, {"text": "liver or kidney disease", "type": "Disease"}]}
```

**shot message 5 — `user`**

```text
Text:
MR imaging with quantitative diffusion mapping of tacrolimus-induced neurotoxicity in organ transplant patients. Our objective was to investigate brain MR imaging findings and the utility of diffusion-weighted (DW) imaging in organ transplant patients who developed neurologic symptoms during tacrolimus therapy. Brain MR studies, including DW imaging, were prospectively performed in 14 organ transplant patients receiving tacrolimus who developed neurologic complications. In each patient who had abnormalities on the initial MR study, a follow-up MR study was performed 1 month later. Apparent diffusion coefficient (ADC) values on the initial MR study were correlated with reversibility of the lesions. Of the 14 patients, 5 (35.7%) had white matter abnormalities, 1 (7.1%) had putaminal hemorrhage, and 8 (57.1%) had normal findings on initial MR images. Among the 5 patients with white matter abnormalities, 4 patients (80.0%) showed higher than normal ADC values on initial MR images, and all showed complete resolution on follow-up images. The remaining 1 patient (20.0%) showed lower than normal ADC value and showed incomplete resolution with cortical laminar necrosis. Diffusion-weighted imaging may be useful in predicting the outcomes of the lesions of tacrolimus-induced neurotoxicity.
```

**shot message 6 — `assistant`**

```text
{"entities": [{"text": "tacrolimus", "type": "Chemical"}, {"text": "neurotoxicity", "type": "Disease"}, {"text": "neurologic complications", "type": "Disease"}, {"text": "white matter abnormalities", "type": "Disease"}, {"text": "putaminal hemorrhage", "type": "Disease"}, {"text": "cortical laminar necrosis", "type": "Disease"}]}
```

## BioRED — system prompt (verbatim)

```text
You are an expert biomedical named-entity annotator. Find every entity of the types below in the text. Copy each entity string EXACTLY as it appears (same spelling, case and spacing); do not expand abbreviations - an abbreviation is its own entity. List each distinct string once per type.
Types:
- GeneOrGeneProduct: genes, proteins, mRNAs and other gene products, including families and complexes
- DiseaseOrPhenotypicFeature: diseases, disorders, signs, symptoms and phenotypic features
- ChemicalEntity: chemicals and drugs, including abbreviations
- OrganismTaxon: organisms and species, including common names such as human, mouse or patients
- SequenceVariant: genomic or protein sequence variants such as mutations, SNPs and rs identifiers
- CellLine: named cell lines such as HeLa or HEK293
Return ONLY JSON: {"entities": [{"text": "...", "type": "<one of the types>"}]}
```

## BioRED — 3-shot examples (seed 0, train split only)

Train PMIDs used as shots (identical for all six LLMs): `19918264, 20533999, 20722491`

**shot message 1 — `user`**

```text
Text:
FGFR4 Gly388Arg polymorphism and prostate cancer risk in Scottish men. Fibroblast growth factor receptor 4 (FGFR4), a member of the fibroblast growth receptor family, was recently reported to be more abundantly expressed in malignant than benign prostate cells. A single nucleotide polymorphism at position 388 of the FGFR4 amino-acid sequence results in the substitution of glycine (Gly) with arginine (Arg) and higher frequency of the ArgArg genotype was previously found in prostate cancer patients. DNA was extracted from the blood drawn from 399 prostate cancer patients, 150 BPH patients and 294 healthy community controls. Polymerase chain reaction was carried out and single nucleotide polymorphisms of FGFR4 were identified by restriction enzyme digestion. No overall association is detectable between the Arg allele and increased prostate cancer risk. Subgroup analysis shows a higher incidence of the heterozygous ArgGly genotype in cancer cases than in the combined group of BPH and controls (P<0.05); this difference is statistically significant between cancer and BPH patients but not between cancer cases and community controls. The single nucleotide polymorphism Gly(388)Arg in FGFR4 is not associated with increased risk of prostate cancer in Scottish men. This observation is in contrast with results from two previous studies conducted in the USA and Japan.
```

**shot message 2 — `assistant`**

```text
{"entities": [{"text": "FGFR4", "type": "GeneOrGeneProduct"}, {"text": "Gly388Arg", "type": "SequenceVariant"}, {"text": "prostate cancer", "type": "DiseaseOrPhenotypicFeature"}, {"text": "cancer", "type": "DiseaseOrPhenotypicFeature"}, {"text": "men", "type": "OrganismTaxon"}, {"text": "Fibroblast growth factor receptor 4", "type": "GeneOrGeneProduct"}, {"text": "fibroblast growth receptor", "type": "GeneOrGeneProduct"}, {"text": "glycine (Gly) with arginine (Arg)", "type": "SequenceVariant"}, {"text": "patients", "type": "OrganismTaxon"}, {"text": "BPH", "type": "DiseaseOrPhenotypicFeature"}, {"text": "Gly(388)Arg", "type": "SequenceVariant"}]}
```

**shot message 3 — `user`**

```text
Text:
Dopamine is not essential for the development of methamphetamine-induced neurotoxicity. It is widely believed that dopamine (DA) mediates methamphetamine (METH)-induced toxicity to brain dopaminergic neurons, because drugs that interfere with DA neurotransmission decrease toxicity, whereas drugs that increase DA neurotransmission enhance toxicity. However, temperature effects of drugs that have been used to manipulate brain DA neurotransmission confound interpretation of the data. Here we show that the recently reported ability of L-dihydroxyphenylalanine to reverse the protective effect of alpha-methyl-para-tyrosine on METH-induced DA neurotoxicity is also confounded by drug effects on body temperature. Further, we show that mice genetically engineered to be deficient in brain DA develop METH neurotoxicity, as long as the thermic effects of METH are preserved. In addition, we demonstrate that mice genetically engineered to have unilateral brain DA deficits develop METH-induced dopaminergic deficits that are of comparable magnitude on both sides of the brain. Taken together, these findings demonstrate that DA is not essential for the development of METH-induced dopaminergic neurotoxicity and suggest that mechanisms independent of DA warrant more intense investigation.
```

**shot message 4 — `assistant`**

```text
{"entities": [{"text": "Dopamine", "type": "ChemicalEntity"}, {"text": "methamphetamine", "type": "ChemicalEntity"}, {"text": "neurotoxicity", "type": "DiseaseOrPhenotypicFeature"}, {"text": "toxicity", "type": "DiseaseOrPhenotypicFeature"}, {"text": "dopamine", "type": "ChemicalEntity"}, {"text": "DA", "type": "ChemicalEntity"}, {"text": "METH", "type": "ChemicalEntity"}, {"text": "L-dihydroxyphenylalanine", "type": "ChemicalEntity"}, {"text": "alpha-methyl-para-tyrosine", "type": "ChemicalEntity"}, {"text": "mice", "type": "OrganismTaxon"}, {"text": "dopaminergic deficits", "type": "DiseaseOrPhenotypicFeature"}]}
```

**shot message 5 — `user`**

```text
Text:
Safety of capecitabine: a review. IMPORTANCE OF THE FIELD: Fluoropyrimidines, in particular 5-fluorouracil (5-FU), have been the mainstay of treatment for several solid tumors, including colorectal, breast and head and neck cancers, for > 40 years. AREAS COVERED IN THIS REVIEW: This article reviews the pharmacology and efficacy of capecitabine with a special emphasis on its safety. WHAT THE READER WILL GAIN: The reader will gain better insight into the safety of capecitabine in special populations such as patients with advanced age, renal and kidney disease. We also explore different dosing and schedules of capecitabine administration. TAKE HOME MESSAGE: Capecitabine is an oral prodrug of 5-FU and was developed to fulfill the need for a more convenient therapy and provide an improved safety/efficacy profile. It has shown promising results alone or in combination with other chemotherapeutic agents in colorectal, breast, pancreaticobiliary, gastric, renal cell and head and neck cancers. The most commonly reported toxic effects of capecitabine are diarrhea, nausea, vomiting, stomatitis and hand-foot syndrome. Capecitabine has a well-established safety profile and can be given safely to patients with advanced age, hepatic and renal dysfunctions.
```

**shot message 6 — `assistant`**

```text
{"entities": [{"text": "capecitabine", "type": "ChemicalEntity"}, {"text": "Fluoropyrimidines", "type": "ChemicalEntity"}, {"text": "5-fluorouracil", "type": "ChemicalEntity"}, {"text": "5-FU", "type": "ChemicalEntity"}, {"text": "tumors", "type": "DiseaseOrPhenotypicFeature"}, {"text": "colorectal, breast and head and neck cancers", "type": "DiseaseOrPhenotypicFeature"}, {"text": "patients", "type": "OrganismTaxon"}, {"text": "renal and kidney disease", "type": "DiseaseOrPhenotypicFeature"}, {"text": "Capecitabine", "type": "ChemicalEntity"}, {"text": "colorectal, breast, pancreaticobiliary, gastric, renal cell and head and neck cancers", "type": "DiseaseOrPhenotypicFeature"}, {"text": "diarrhea", "type": "DiseaseOrPhenotypicFeature"}, {"text": "nausea", "type": "DiseaseOrPhenotypicFeature"}, {"text": "vomiting", "type": "DiseaseOrPhenotypicFeature"}, {"text": "stomatitis", "type": "DiseaseOrPhenotypicFeature"}, {"text": "hand-foot syndrome", "type": "DiseaseOrPhenotypicFeature"}, {"text": "hepatic and renal dysfunctions", "type": "DiseaseOrPhenotypicFeature"}]}
```

## Decoding parameters (per model family)

| setting | deepseek (R1-distill) | all other LLMs |
|---|---|---|
| temperature | 0.6 | 0 |
| seed | 0 | 0 |
| max_tokens | 10000 | 8000 |
| response_format | *(none — reasoner)* | `{"type": "json_object"}` |
| chat_template_kwargs | *(none)* | `enable_thinking: false` for qwen and gemma |
| retries on exception | 3 | 3 |
| system message | normal `system` role | normal `system` role, **except mistral** |

**Mistral special case.** `NO_SYSTEM_ROLE = {"mistral"}`: the chat template rejects a system message, so the system text is concatenated as `<system>\n\n<first message content>` into the first message. In 3-shot mode the first message is the first few-shot *user* turn, so Mistral's first user message contains the system prompt *and* the first example text; in zero-shot mode it contains the system prompt and the document. This is a genuine prompt difference between models and must be stated wherever `_fs`/`_zs` results are compared across models.

**What is *not* recoverable from the artefacts.** The vLLM server version, the exact serving flags, the tokenizer revision, and the GPU/library stack are recorded only as `device: 1x A40 (vLLM)` in `_meta`. Sampling is nominally greedy (`temperature=0`, `seed=0`) except for DeepSeek, but vLLM is not bit-deterministic across builds, so the *responses* are not exactly reproducible even with the prompts in hand. See `NER_REPRODUCIBILITY_GAPS.md`.
