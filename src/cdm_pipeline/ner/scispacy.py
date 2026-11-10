"""sciSpaCy NER — supports 4 biomedical spaCy models.

Models:
    en_core_sci_lg     — generic ENTITY
    en_ner_bc5cdr_md   — CHEMICAL, DISEASE
    en_ner_craft_md    — PROTEIN, DNA_RNA, ORGANISM, CHEMICAL, CELL_TYPE
    en_ner_jnlpba_md   — PROTEIN, DNA_RNA, CELL_TYPE
"""
from .base import BaseNERModel

SPACY_MODELS = [
    "en_core_sci_lg",
    "en_ner_bc5cdr_md",
    "en_ner_craft_md",
    "en_ner_jnlpba_md",
]

# notebook Cell 7 also runs en_ner_bionlp13cg_md; it lives in SPACY_MODELS_EXTRA
# because it needs the isolated ner_variants venv (the vllm venv has no spacy).
SPACY_MODELS_EXTRA = ["en_ner_bionlp13cg_md"]

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
    "TISSUE_TYPE": "CELL_TYPE",
    "ORGANISM": "ORGANISM",
    "GENE": "PROTEIN",
    "GENOMICS": "GENOMICS",
}

MODEL_LABEL_MAPS = {
    "en_core_sci_lg": {"ENTITY": "ENTITY"},
    "en_ner_bc5cdr_md": {"CHEMICAL": "CHEMICAL", "DISEASE": "DISEASE"},
    "en_ner_craft_md": {
        "GGP": "PROTEIN", "SO": "DNA_RNA", "TAXON": "ORGANISM",
        "CHEBI": "CHEMICAL", "CL": "CELL_TYPE",
    },
    "en_ner_jnlpba_md": {
        "PROTEIN": "PROTEIN", "DNA": "DNA_RNA", "RNA": "DNA_RNA",
        "CELL_LINE": "CELL_TYPE", "CELL_TYPE": "CELL_TYPE",
    },
    # notebook Cell 7's 5th model; labels mirror common.LABEL_TO_CDM where an
    # entry exists, otherwise the label passes through uppercased (visible for
    # review rather than silently dropped).
    "en_ner_bionlp13cg_md": {
        "AMINO_ACID": "CHEMICAL",
        "SIMPLE_CHEMICAL": "CHEMICAL",
        "ORGANISM_SUBSTANCE": "CHEMICAL",
        "GENE_OR_GENE_PRODUCT": "PROTEIN",
        "ORGANISM": "ORGANISM",
        "ORGANISM_SUBDIVISION": "ORGANISM",
        "CANCER": "DISEASE",
        "PATHOLOGICAL_FORMATION": "DISEASE",
        "CELL": "CELL_TYPE",
        "TISSUE": "CELL_TYPE",
        "ORGAN": "CELL_TYPE",
    },
}


class SpaCyNERModel(BaseNERModel):
    """sciSpaCy NER model.

    Args:
        spacy_model: spaCy model name (e.g. ``"en_ner_bc5cdr_md"``)
        name: output model label
        output_file: output CSV filename
    """

    def __init__(self, spacy_model="en_core_sci_lg", name=None,
                 output_file="scispacy_ner.csv", **kwargs):
        super().__init__(**kwargs)
        self.spacy_model = spacy_model
        self.name = name or spacy_model
        self.output_file = output_file
        self._label_map = MODEL_LABEL_MAPS.get(spacy_model, {})

    def load(self):
        import spacy
        print("\n[sciSpaCy] Loading %s ..." % self.spacy_model)
        self.model = spacy.load(self.spacy_model,
                                disable=["tagger", "parser", "lemmatizer"])
        print("  Labels: %s" % sorted(self.model.pipe_labels.get("ner", {})))

    def map_label(self, raw_label):
        return self._label_map.get(raw_label.upper(), raw_label.upper())

    def predict_text(self, text, base_offset=0):
        doc = self.model(text)
        preds = []
        for ent in doc.ents:
            ent_text = ent.text.strip()
            if not ent_text or len(ent_text) < 2:
                continue
            preds.append({
                "start": base_offset + ent.start_char,
                "end": base_offset + ent.end_char,
                "text": ent_text,
                "label": self.map_label(ent.label_),
            })
        return preds


def run_scispacy(papers, models=None, batch_size=20):
    """Backward-compatible function: run all 4 sciSpaCy models.

    Returns:
        (results, elapsed) where results is list of tuples:
        (term, label, model_name, paper, char_start, char_end)
    """
    if models is None:
        models = SPACY_MODELS

    all_results = []
    total_elapsed = 0
    for model_name in models:
        m = SpaCyNERModel(spacy_model=model_name, name=model_name,
                          output_file="scispacy_ner_%s.csv" % model_name)
        results, elapsed = m.run(papers)
        all_results.extend(results)
        total_elapsed += elapsed
    return all_results, total_elapsed
