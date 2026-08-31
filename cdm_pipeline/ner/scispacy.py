"""sciSpaCy NER — 4 models in parallel on full corpus."""
import sys
import csv
import time as _time
from collections import Counter

from ..config import PAPERS_DIR

SPACY_MODELS = [
    "en_core_sci_lg",
    "en_ner_bc5cdr_md",
    "en_ner_craft_md",
    "en_ner_jnlpba_md",
]

LABEL_MAP = {
    "ENTITY": "ENTITY",
    "DISEASE": "DISEASE",
    "CHEMICAL": "CHEMICAL",
    "GGP": "PROTEIN",
    "SO": "DNA_RNA",
    "TAXON": "ORGANISM",
    "CHEBI": "CHEMICAL",
    "CL": "CELL_TYPE",
    "CL TYPE": "CELL_TYPE",
    "CELL_TYPE": "CELL_TYPE",
    "CELLLINE": "CELL_TYPE",
    "CELL_LINE": "CELL_TYPE",
    "PROTEIN": "PROTEIN",
    "DNA": "DNA_RNA",
    "RNA": "DNA_RNA",
    "TAXON": "ORGANISM",
    "TISSUE_TYPE": "CELL_TYPE",
    "ORGANISM": "ORGANISM",
    "GENE": "PROTEIN",
    "GENOMICS": "GENOMICS",
}


def map_spacy_label(raw_label, model_name):
    """Map sciSpaCy label to CDM type."""
    lab = raw_label.upper()
    if model_name == "en_core_sci_lg":
        return "ENTITY"
    mapped = LABEL_MAP.get(lab, lab)
    return mapped


def run_scispacy(papers, models=None, batch_size=20):
    """Run sciSpaCy NER models on papers.

    Args:
        papers: list of paper filenames (e.g. "PRJNA12345.txt")
        models: list of model names to run (default: all 4)
        batch_size: spaCy pipe batch size

    Returns:
        (results, elapsed) where results is list of tuples:
        (term, label, model_name, paper, char_start, char_end)
    """
    import spacy

    if models is None:
        models = SPACY_MODELS

    print("\n[sciSpaCy] Loading models: %s" % ", ".join(models))
    nlp_pipes = {}
    for model_name in models:
        try:
            nlp = spacy.load(model_name, disable=["tagger", "parser", "lemmatizer"])
            nlp_pipes[model_name] = nlp
            print("  Loaded %s (%d labels: %s)" % (
                model_name, len(nlp.pipe_labels.get("ner", {})),
                ", ".join(sorted(nlp.pipe_labels.get("ner", {})))))
        except Exception as e:
            print("  FAILED to load %s: %s" % (model_name, e))

    if not nlp_pipes:
        print("[sciSpaCy] No models loaded, aborting")
        return [], 0

    all_results = []
    t0 = _time.time()
    total_ents = Counter()

    for idx, paper_file in enumerate(papers):
        path = PAPERS_DIR / paper_file
        text = path.read_text(encoding="utf-8", errors="replace")

        for model_name, nlp in nlp_pipes.items():
            doc = nlp(text)
            for ent in doc.ents:
                cdm_label = map_spacy_label(ent.label_, model_name)
                ent_text = ent.text.strip()
                if not ent_text or len(ent_text) < 2:
                    continue
                all_results.append((
                    ent_text,
                    cdm_label,
                    model_name,
                    paper_file,
                    ent.start_char,
                    ent.end_char,
                ))
                total_ents[model_name] += 1

        if (idx + 1) % 10 == 0 or idx == len(papers) - 1:
            elapsed = _time.time() - t0
            rate = (idx + 1) / elapsed if elapsed > 0 else 0
            remaining = (len(papers) - idx - 1) / rate if rate > 0 else 0
            print("  [sciSpaCy] %d/%d papers (%d ents, %.1fs, ETA %.0fs)" % (
                idx + 1, len(papers), len(all_results), elapsed, remaining))

    elapsed = _time.time() - t0
    print("[sciSpaCy] Done: %d entities from %d papers in %.1fs" % (
        len(all_results), len(papers), elapsed))
    print("[sciSpaCy] Per model: %s" % dict(total_ents))
    return all_results, elapsed
