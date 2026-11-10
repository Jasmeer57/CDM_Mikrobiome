"""PubMedBERT / BioBERT NER — disease-focused token classification.

Uses ``alvaroalon2/biobert_diseases_ner`` (BioBERT fine-tuned on NCBI Disease).

Label mapping: the model emits BIO tags (``B-DISEASE``, ``I-DISEASE``, ``0``).
The HuggingFace ``pipeline`` with ``aggregation_strategy="simple"`` merges
B/I tokens into span groups with ``entity_group="DISEASE"`` or ``"0"``.
We filter out ``"0"`` (non-entity) groups.
"""
import re

from .base import BaseNERModel


class PubMedBERTModel(BaseNERModel):
    """BioBERT disease NER model.

    Args:
        model_name: HuggingFace model checkpoint
        name: output model label
        output_file: output CSV filename
        entity_types: CDM types this model can emit (default: ["DISEASE"])
    """

    def __init__(self, model_name="alvaroalon2/biobert_diseases_ner",
                 name="biobert_diseases", output_file="pubmedbert_ner.csv",
                 entity_types=None, revision=None, **kwargs):
        if entity_types is None:
            entity_types = ["DISEASE"]
        super().__init__(entity_types=entity_types, **kwargs)
        self.model_name = model_name
        self.name = name
        self.output_file = output_file
        self.revision = revision

    def load(self):
        from transformers import AutoTokenizer, AutoModelForTokenClassification, pipeline
        import torch

        print("\n[PubMedBERT] Loading %s (revision=%s) ..." % (self.model_name, self.revision))
        load_kwargs = {}
        if self.revision:
            load_kwargs["revision"] = self.revision
        tokenizer = AutoTokenizer.from_pretrained(self.model_name, **load_kwargs)
        model = AutoModelForTokenClassification.from_pretrained(self.model_name, **load_kwargs)
        device_num = 0 if torch.cuda.is_available() else -1
        self._nlp = pipeline("ner", model=model, tokenizer=tokenizer,
                             aggregation_strategy="simple", device=device_num)

        import spacy
        try:
            self._nlp_spacy = spacy.load("en_core_sci_sm",
                                         disable=["ner", "tagger", "lemmatizer"])
        except Exception:
            self._nlp_spacy = spacy.blank("en")
            self._nlp_spacy.add_pipe("sentencizer")

    def predict_text(self, text, base_offset=0):
        text_capped = text[:100000]
        doc = self._nlp_spacy(text_capped)
        sentences = [(sent.start_char, sent.text.strip())
                     for sent in doc.sents if len(sent.text.strip()) > 5]

        preds = []
        for sent_offset, sent in sentences:
            abs_offset = base_offset + sent_offset
            if len(sent) > 400:
                parts = re.split(r'[;]', sent)
                part_base = 0
                for p in parts:
                    p = p.strip()
                    if len(p) > 200:
                        for i in range(0, len(p), 200):
                            s = p[i:i+200].strip()
                            if len(s) > 5:
                                self._predict_sent(s, abs_offset + part_base + i, preds)
                    elif len(p) > 5:
                        self._predict_sent(p, abs_offset + part_base, preds)
                    part_base += len(p) + 1
            else:
                self._predict_sent(sent, abs_offset, preds)
        return preds

    def _predict_sent(self, sent, base_offset, preds):
        """Run NER on a single sentence and append results to preds."""
        try:
            ner_results = self._nlp(sent)
            for ent in ner_results:
                group = ent.get("entity_group", ent.get("entity", ""))
                if group.upper() in ("0", "O", ""):
                    continue
                term = ent["word"].strip()
                if term.startswith("##") or len(term) < 2:
                    continue
                preds.append({
                    "start": base_offset + ent["start"],
                    "end": base_offset + ent["end"],
                    "text": term,
                    "label": "DISEASE",
                })
        except Exception:
            pass
