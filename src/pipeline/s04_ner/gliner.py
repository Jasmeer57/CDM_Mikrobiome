"""GLiNER NER model — zero-shot span-based NER.

Supports any HuggingFace GLiNER checkpoint via ``model_name`` parameter.
The pipeline ships with two legacy configs:

* ``gliner_medium``   — ``urchade/gliner_medium``  (general purpose)
* ``gliner_biomed``    — ``Ihor/gliner-biomed-large-v1.0``  (biomedical)

and the 2026 checkpoints (``gliner-community/gliner_*-v2.5``,
``Ihor/gliner-large-v2.5-biomed``) through the same class.

**Chunking.** The model sees a ~512-token window, and upstream truncates
silently past it (no exception, no warning). Fixed character chunking therefore
loses entities: on this corpus a 2,000-character chunk overflows the window for
12.96% of chunks. Chunks are sized against a real token budget in
:mod:`cdm_pipeline.ner.chunking`.

The two legacy registry entries pin ``max_tokens=None``, which restores the
original fixed-character stride. That is deliberate: the frozen ``zenodo_v1``
baseline (``all_ner_sections_combined.csv``, 1,705,501 rows) was produced by the
fixed-stride code, and ``max_tokens=None`` keeps it byte-reproducible. New
checkpoints should leave the default in place.
"""

import sys

from pipeline.s04_ner.base import BaseNERModel
from pipeline.s04_ner.chunking import token_chunks


class GLiNERModel(BaseNERModel):
    """GLiNER zero-shot NER model.

    Args:
        model_name: HuggingFace model checkpoint
        name: output model label (CSV ``model`` column)
        output_file: output CSV filename
        threshold: confidence threshold for entity detection
        chunk_size: character chunk size for long text
        entity_types: list of entity type labels to detect
        revision: optional pinned commit for reproducibility
        max_chars: soft upper bound on characters per chunk
        max_tokens: hard token budget per chunk. ``None`` disables token-budget
            chunking and falls back to the legacy fixed ``chunk_size`` stride
            (only for reproducing the frozen baseline).
    """

    def __init__(self, model_name="urchade/gliner_medium", name="gliner_medium",
                 output_file="gliner_ner.csv", threshold=0.5, chunk_size=2000,
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
        from gliner import GLiNER

        print("\n[GLiNER] Loading %s (revision=%s) ..." % (self.model_name, self.revision))
        sys.stdout.flush()
        load_kwargs = {}
        if self.revision:
            load_kwargs["revision"] = self.revision
        self.model = GLiNER.from_pretrained(self.model_name, **load_kwargs)
        device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model = self.model.to(device)
        self.device = device
        # tokenizer is used only to size chunks, never to alter spans
        tok = None
        dp = getattr(self.model, "data_processor", None)
        if dp is not None:
            tok = getattr(dp, "transformer_tokenizer", None) or getattr(dp, "tokenizer", None)
        if tok is not None:
            self._ntokens_fn = lambda s: len(tok(s, add_special_tokens=False)["input_ids"])
        else:
            self._ntokens_fn = lambda s: len(s) // 4
        print("[GLiNER] Device: %s (max_chars=%s, max_tokens=%s)" % (
            device, self.max_chars, self.max_tokens))
        sys.stdout.flush()

    def _chunk_spans(self, text):
        if self.max_tokens is None:
            # legacy fixed-character stride (frozen-baseline reproduction only)
            for chunk_start in range(0, len(text), self.chunk_size):
                yield chunk_start, min(chunk_start + self.chunk_size, len(text))
        else:
            yield from token_chunks(text, self._ntokens_fn, self.max_chars, self.max_tokens)

    def predict_text(self, text, base_offset=0):
        preds = []
        for lo, hi in self._chunk_spans(text):
            chunk = text[lo:hi]
            if not chunk.strip():
                continue
            try:
                entities = self.model.predict_entities(
                    chunk, self.entity_types, threshold=self.threshold)
            except Exception:
                continue
            for e in entities:
                start, end = e.get("start"), e.get("end")
                if start is None or end is None:
                    continue
                preds.append({
                    "start": base_offset + lo + start,
                    "end": base_offset + lo + end,
                    "text": e["text"],
                    "label": e["label"],
                })
        return preds
