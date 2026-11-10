"""HunFlair2 NER (``hunflair/hunflair2-ner``) via the ``flair`` library.

Ports the notebook's Cell 6 reference runner to the section runner's model
interface. The notebook's ``para_chunks`` packing is preserved verbatim:
section bodies are split on paragraph boundaries and repacked into chunks of
<=3000 chars, then each chunk is fed to a ``Sentence`` built with
``use_tokenizer=False`` so flair's own tokenizer is used and offsets are
character-accurate against the chunk; the chunk offset is added back.

Label mapping (flair tag values -> CDM types) follows
:data:`common.LABEL_TO_CDM` where an entry exists; labels with no CDM type are
passed through uppercased so they are visible for downstream review rather than
silently dropped.

Requires ``flair`` (see ``src/scripts/setup_ner_variants_venv.sh``); it is not
installed in ``venvs/vllm``.
"""
from .base import BaseNERModel

# flair tag value -> emitted label
LABEL_MAP = {
    "Chemical": "CHEMICAL",
    "Gene": "PROTEIN",
    "Disease": "DISEASE",
    "Species": "ORGANISM",
    "CellLine": "CELL_TYPE",
}

DEFAULT_MODEL = "hunflair/hunflair2-ner"
MAX_CHUNK = 3000

# characters trimmed from span edges by _trim_span (superset of the set the audit measured
# as trailing-punctuation pollution, with the opening brackets added for symmetry)
_PUNCT_TRIM = ",.;:)]}\"'-([{"


def _trim_span(text, st, en):
    """Trim a whitespace-token window to its non-whitespace, non-punctuation core.

    use_tokenizer=False makes flair return the raw token window, which can carry trailing
    punctuation and embedded newlines (job 28643869: 22.5% / 12.5% of rows). Returns the
    trimmed (st, en), or (None, None) when nothing usable remains. Approved 2026-10-28
    (notebook Cell 19 proposal); changes spans, hence the full re-run and re-validation.
    """
    while st < en and (text[st].isspace() or text[st] in _PUNCT_TRIM):
        st += 1
    while en > st and (text[en - 1].isspace() or text[en - 1] in _PUNCT_TRIM):
        en -= 1
    return (st, en) if en > st else (None, None)


def para_chunks(text, maxlen=MAX_CHUNK):
    """Notebook Cell 6 verbatim: split on paragraph boundaries, pack to <= maxlen.

    Returns list of ``(offset, chunk)`` pairs.
    """
    paras = text.split("\n\n")
    chunks, cur, cur_off, pos = [], "", 0, 0
    for p in paras:
        if cur and len(cur) + len(p) + 2 > maxlen:
            chunks.append((cur_off, cur))
            cur, cur_off = p, pos
        else:
            if not cur:
                cur_off = pos
            cur = cur + "\n\n" + p if cur else p
        pos += len(p) + 2
    if cur:
        chunks.append((cur_off, cur))
    return chunks


class HunFlair2Model(BaseNERModel):
    """HunFlair2 sequence tagger over paragraph-packed chunks.

    Args:
        model_name: flair model id
        name: output model label
        output_file: output CSV filename
        max_chunk: paragraph pack size (notebook default 3000)
    """

    def __init__(self, model_name=DEFAULT_MODEL, name="hunflair2",
                 output_file="hunflair2_ner.csv", max_chunk=MAX_CHUNK, **kwargs):
        super().__init__(entity_types=None, **kwargs)
        self.model_name = model_name
        self.name = name
        self.output_file = output_file
        self.max_chunk = max_chunk

    def load(self):
        from flair.models import SequenceTagger
        print("\n[HunFlair2] Loading %s ..." % self.model_name)
        self.model = SequenceTagger.load(self.model_name)
        print("[HunFlair2] loaded (BIOES tags: Chemical, Gene, Disease, Species, CellLine)")

    def predict_text(self, text, base_offset=0):
        if self.model is None:
            self._ensure_loaded()
        from flair.data import Sentence

        preds = []
        for off, chunk in para_chunks(text, self.max_chunk):
            if not chunk.strip():
                continue
            s = Sentence(chunk, use_tokenizer=False)
            self.model.predict(s)
            for e in s.get_spans("ner"):
                st = off + e.tokens[0].start_position
                en = off + e.tokens[-1].end_position
                raw = e.get_label("ner").value
                # v2 fix (approved 2026-10-28, notebook Cell 19): use_tokenizer=False makes
                # flair return the raw whitespace-token window, which carried trailing
                # punctuation (22.5% of rows in job 28643869) and embedded newlines (12.5%).
                # Trim the window to its non-whitespace, non-punctuation core; the stored
                # term is then always exactly text[start:end] by construction.
                st, en = _trim_span(text, st, en)
                if st is None:
                    continue
                term = text[st:en]
                preds.append({
                    "start": base_offset + st,
                    "end": base_offset + en,
                    "text": term,
                    "label": LABEL_MAP.get(raw, raw.upper()),
                })
        return preds
