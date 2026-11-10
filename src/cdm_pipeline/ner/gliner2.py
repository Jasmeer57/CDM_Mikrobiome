"""GLiNER2 NER model — schema-based entity extraction.

GLiNER2 (Fastino, 2026) is a **different package and architecture** from the
``gliner`` v1/v2.5 family in :mod:`cdm_pipeline.ner.gliner`; it shares the
zero-shot "type list -> spans" interface but nothing else:

* package   — ``pip install gliner2`` (not ``gliner``)
* API       — ``GLiNER2.from_pretrained(...).extract_entities(...)``
* output    — ``{"entities": {label: [{"text","confidence","start","end"}]}}``

**Silent truncation is the main hazard**: upstream truncates at the encoder's
512-token window without raising and without reporting what was dropped, so
chunking is mandatory rather than an optimisation. Chunks are therefore sized
against a token budget in :mod:`cdm_pipeline.ner.chunking`, which also keeps
every boundary on a word edge so spans always slice-verify.
"""

import sys

from .base import BaseNERModel
from .chunking import token_chunks


class GLiNER2Model(BaseNERModel):
    """GLiNER2 zero-shot NER model.

    Args:
        model_name: HuggingFace checkpoint (e.g. ``fastino/gliner2-base-v1``)
        name: output model label (CSV ``model`` column)
        output_file: output CSV filename
        threshold: confidence threshold passed to ``extract_entities``
        max_chars: soft upper bound on characters per chunk (word-boundary snapped)
        max_tokens: hard token budget; chunks above it are split on word edges
        entity_types: list of entity type labels to detect
        revision: optional pinned commit for reproducibility
    """

    def __init__(self, model_name="fastino/gliner2-base-v1", name="gliner2",
                 output_file="gliner2_ner.csv", threshold=0.5, chunk_size=2000,
                 entity_types=None, revision=None, max_chars=1200, max_tokens=480,
                 **kwargs):
        super().__init__(entity_types=entity_types, threshold=threshold,
                         chunk_size=chunk_size, **kwargs)
        self.model_name = model_name
        self.name = name
        self.output_file = output_file
        self.revision = revision
        self.max_chars = max_chars
        self.max_tokens = max_tokens
        self._ntokens_fn = None

    def load(self):
        import torch
        from gliner2 import GLiNER2

        print("\n[GLiNER2] Loading %s (revision=%s) ..." % (self.model_name, self.revision))
        sys.stdout.flush()
        load_kwargs = {}
        if self.revision:
            load_kwargs["revision"] = self.revision
        self.model = GLiNER2.from_pretrained(self.model_name, **load_kwargs)
        device = "cuda" if torch.cuda.is_available() else "cpu"
        if hasattr(self.model, "to"):
            self.model = self.model.to(device)
        self.device = device
        # tokenizer is used only to size chunks, never to alter spans
        tok = getattr(getattr(self.model, "processor", None), "tokenizer", None)
        if tok is not None:
            self._ntokens_fn = lambda s: len(tok(s, add_special_tokens=False)["input_ids"])
        else:
            self._ntokens_fn = lambda s: len(s) // 4
        print("[GLiNER2] Device: %s (max_chars=%d, max_tokens=%d)" % (
            device, self.max_chars, self.max_tokens))
        sys.stdout.flush()

    def predict_text(self, text, base_offset=0):
        preds = []
        for lo, hi in token_chunks(text, self._ntokens_fn, self.max_chars, self.max_tokens):
            chunk = text[lo:hi]
            if not chunk.strip():
                continue
            try:
                result = self.model.extract_entities(
                    chunk, self.entity_types, threshold=self.threshold,
                    include_spans=True, include_confidence=True)
            except Exception:
                continue
            for label, values in (result.get("entities") or {}).items():
                for ent in (values or []):
                    if not isinstance(ent, dict):
                        continue
                    start, end = ent.get("start"), ent.get("end")
                    if start is None or end is None:
                        continue
                    preds.append({
                        "start": base_offset + lo + start,
                        "end": base_offset + lo + end,
                        "text": ent.get("text", ""),
                        "label": label,
                    })
        return preds
