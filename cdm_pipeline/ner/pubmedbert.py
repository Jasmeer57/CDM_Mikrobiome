"""PubMedBERT / BioBERT NER runner (disease-focused)."""
import re
import time

from ..config import PAPERS_DIR


def map_pubmedbert_label(raw_label):
    """Map BioBERT disease NER label to CDM type."""
    rl = raw_label.upper()
    rl = re.sub(r'^[BI]-', '', rl)
    mapping = {
        "DISEASE": "DISEASE",
        "DISEASE_DISORDER": "DISEASE",
        "DISEASES_DISORDERS": "DISEASE",
    }
    return mapping.get(rl, "DISEASE")


def _run_pubmedbert_sent(nlp_pipe, sent, paper_file, all_results):
    """Run BioBERT NER on a single sentence and append results."""
    try:
        ner_results = nlp_pipe(sent)
        for ent in ner_results:
            term = ent["word"].strip()
            if term.startswith("##") or len(term) < 2:
                continue
            cdm_label = map_pubmedbert_label(ent["entity_group"])
            all_results.append((
                term,
                cdm_label,
                "biobert_diseases",
                paper_file,
                ent["start"],
                ent["end"],
            ))
    except Exception:
        pass


def run_pubmedbert(papers, chunk_size=1500):
    """Run biomedical NER via HuggingFace token classification pipeline.

    Uses alvaroalon2/biobert_diseases_ner (BioBERT fine-tuned on NCBI Disease).
    Disease-only, high precision. Uses spaCy sentencizer for proper splitting.
    """
    from transformers import AutoTokenizer, AutoModelForTokenClassification, pipeline
    import torch

    model_name = "alvaroalon2/biobert_diseases_ner"
    print("\n[PubMedBERT] Loading %s ..." % model_name)
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    model = AutoModelForTokenClassification.from_pretrained(model_name)
    device_num = 0 if torch.cuda.is_available() else -1

    nlp_pipe = pipeline("ner", model=model, tokenizer=tokenizer,
                   aggregation_strategy="simple", device=device_num)

    # Use spacy for sentence splitting (already installed)
    import spacy
    try:
        nlp_spacy = spacy.load("en_core_sci_sm", disable=["ner", "tagger", "lemmatizer"])
    except Exception:
        nlp_spacy = spacy.blank("en")
        nlp_spacy.add_pipe("sentencizer")

    all_results = []
    t0 = time.time()

    for idx, paper_file in enumerate(papers):
        path = PAPERS_DIR / paper_file
        text = path.read_text(encoding="utf-8", errors="replace")

        # Sentence splitting via spaCy
        doc = nlp_spacy(text[:100000])  # cap at 100k chars
        sentences = [sent.text.strip() for sent in doc.sents if len(sent.text.strip()) > 5]

        for sent_idx, sent in enumerate(sentences):
            # Skip overly long sentences (model has 512 token limit)
            if len(sent) > 400:
                # Split further on semicolons/commas
                parts = re.split(r'[;]', sent)
                for p in parts:
                    p = p.strip()
                    if len(p) > 200:
                        # Force split
                        for i in range(0, len(p), 200):
                            s = p[i:i+200].strip()
                            if len(s) > 5:
                                _run_pubmedbert_sent(nlp_pipe, s, paper_file, all_results)
                    elif len(p) > 5:
                        _run_pubmedbert_sent(nlp_pipe, p, paper_file, all_results)
            else:
                _run_pubmedbert_sent(nlp_pipe, sent, paper_file, all_results)

        if (idx + 1) % 25 == 0 or idx == len(papers) - 1:
            print("  [PubMedBERT] %d/%d papers done (%.1fs)" % (idx + 1, len(papers), time.time() - t0))

    elapsed = time.time() - t0
    print("[PubMedBERT] Done: %d entities from %d papers in %.1fs" % (
        len(all_results), len(papers), elapsed))
    return all_results, elapsed
