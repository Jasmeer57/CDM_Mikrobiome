"""BioBERT + SciBERT token-classification NER (4 variants).

Implements the four HuggingFace token-classification checkpoints that the
Windows notebook ran in ``Cell 6b`` — but here over the **full 452-paper
segmented-section corpus** instead of 5 demo papers:

======================  ===========================================================
registry key            checkpoint
======================  ===========================================================
``bert_disease``        ``alvaroalon2/biobert_diseases_ner``
``bert_chemical``       ``alvaroalon2/biobert_chemical_ner``
``bert_genetic``        ``alvaroalon2/biobert_genetic_ner``
``scibert_jnlpba``      ``fran-martinez/scibert_scivocab_cased_ner_jnlpba``
======================  ===========================================================

Decoding is the notebook's **v2 word-level** rule (``BERT_AGG_SRC``), ported
verbatim so the section runner is byte-comparable to the notebook reference:

* input is chunked into **word windows** of <=2600 chars / <=450 sub-tokens /
  <=220 words with **no overlap** (a word never appears in two windows);
* each word takes the label of its **first** sub-token;
* word spans are the union of their sub-token pieces;
* BIO decode over words, where ``I-X`` continues **only** an already-open ``X``.

The notebook's legacy sub-token decode is deliberately *not* reproduced: it was
kept only as a before/after trace for the partial-word fix and is superseded.

Labels emitted are the models' own, uppercased (``DISEASE``, ``CHEMICAL``,
``GENETIC``, ``PROTEIN``, ``RNA``, ``DNA``, ``CELL_TYPE``, ``CELL_LINE``);
:data:`common.LABEL_TO_CDM` maps them to CDM types downstream.

Pass ``label_map`` to fold a checkpoint's vocabulary to CDM types at the
source (e.g. JNLPBA ``DNA``/``RNA`` -> ``DNA_RNA``). The map is applied to the
decoded entity type *after* BIO decoding, so it can never merge or split
spans — only relabel them. A map is **opt-in per registry entry**: the
2026-10-27 452-paper runs were produced with ``label_map=None`` (raw labels),
so leaving the default alone keeps those artifacts reproducible.
"""
import re

from .base import BaseNERModel

# ── notebook Cell 1b: BERT_AGG_SRC, verbatim ──────────────────────────────────


def word_level(word_ids, labels, offsets):
    """Collapse sub-tokens to words: label = first sub-token's label; span = union of pieces."""
    words, prev = [], None
    for wid, lab, (s, e) in zip(word_ids, labels, offsets):
        if wid is None or s == e:
            continue
        if wid != prev:
            words.append([s, e, lab])
            prev = wid
        else:
            words[-1][1] = max(words[-1][1], e)
    return words


def words_to_spans(words):
    """BIO decode over words -> [(type, start, end)]. I-X continues only an open X entity."""
    ents, cur = [], None
    for s, e, lab in words:
        if lab == "O":
            if cur:
                ents.append(cur)
                cur = None
            continue
        b, t = lab.split("-", 1)
        if b == "I" and cur and cur[0] == t:
            cur[2] = e
        else:
            if cur:
                ents.append(cur)
            cur = [t, s, e]
    if cur:
        ents.append(cur)
    return [tuple(x) for x in ents]


def norm_label(raw):
    """Normalize a model label to ``X`` / ``B-X`` / ``I-X`` / ``O`` (notebook Cell 6b)."""
    s = (raw or "").strip().upper()
    if s in ("O", "0", ""):
        return "O"
    if "-" in s:
        b, t = s.split("-", 1)
        if b in ("B", "I") and t:
            return s
    return "O"


class BertVariantModel(BaseNERModel):
    """One HuggingFace token-classification checkpoint, notebook v2 decoding.

    Args:
        model_name: HuggingFace checkpoint id
        name: output model label (goes into the CSV ``model`` column)
        output_file: output CSV filename
        revision: optional pinned revision for reproducibility
        label_map: optional {RAW_LABEL: CDM_TYPE} fold applied after BIO decoding
        max_chars / max_words / max_tokens: word-window limits (notebook defaults)
    """

    def __init__(self, model_name, name, output_file, revision=None, label_map=None,
                 max_chars=2600, max_words=220, max_tokens=450, threads=8, **kwargs):
        super().__init__(entity_types=None, **kwargs)
        self.model_name = model_name
        self.name = name
        self.output_file = output_file
        self.revision = revision
        self.label_map = {k.upper(): v for k, v in (label_map or {}).items()}
        self.max_chars = max_chars
        self.max_words = max_words
        self.max_tokens = max_tokens
        self.threads = threads
        self._tok = None
        self._mdl = None
        self._id2 = None
        self.device = "cpu"

    # ── load ──

    def load(self):
        import torch
        from transformers import AutoTokenizer, AutoModelForTokenClassification

        print("\n[BERT] Loading %s (revision=%s) ..." % (self.model_name, self.revision))
        load_kwargs = {}
        if self.revision:
            load_kwargs["revision"] = self.revision
        tok = AutoTokenizer.from_pretrained(self.model_name, **load_kwargs)
        if not tok.is_fast:
            raise RuntimeError("%s: word_ids() needs a fast tokenizer" % self.model_name)
        mdl = AutoModelForTokenClassification.from_pretrained(self.model_name, **load_kwargs)
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        if self.device == "cpu":
            torch.set_num_threads(self.threads)
        mdl = mdl.to(self.device).eval()
        self._tok, self._mdl = tok, mdl
        self._id2 = {int(k): norm_label(v) for k, v in mdl.config.id2label.items()}
        print("[BERT] %s on %s | labels: %s" % (
            self.name, self.device, sorted(set(self._id2.values()))))

    # ── inference ──

    def predict_text(self, text, base_offset=0):
        """Word-window inference -> list of {start, end, text, label} (section-relative)."""
        if self._tok is None:
            self._ensure_loaded()
        import torch

        tok, mdl = self._tok, self._mdl
        out = []
        words = [(m.start(), m.end()) for m in re.finditer(r"\S+", text)]
        n, i = len(words), 0
        while i < n:
            j = min(i + self.max_words, n)
            while j - i > 1 and words[j - 1][1] - words[i][0] > self.max_chars:
                j -= 1
            while j - i > 1 and len(tok(text[words[i][0]:words[j - 1][1]])["input_ids"]) > self.max_tokens:
                j = max(i + 1, j - max(1, (j - i) // 2))
            base = words[i][0]
            chunk = text[base:words[j - 1][1]]
            enc = tok(chunk, return_tensors="pt", return_offsets_mapping=True,
                      truncation=True, max_length=512)
            wids = enc.word_ids(0)
            off = enc.pop("offset_mapping")[0].tolist()
            enc = {k: v.to(self.device) for k, v in enc.items()}
            with torch.no_grad():
                logits = mdl(**enc).logits[0]
            labels = [self._id2[li] for li in logits.argmax(-1).tolist()]
            for ty, s, e in words_to_spans(word_level(wids, labels, off)):
                term = text[base + s:base + e]
                if not term.strip():
                    continue
                out.append({
                    "start": base + s,
                    "end": base + e,
                    "text": term,
                    "label": self.label_map.get(ty, ty),
                })
            i = j
        return out
