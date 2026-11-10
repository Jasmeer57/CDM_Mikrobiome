"""Token-budgeted, word-aligned chunking for span models.

Zero-shot span models (GLiNER v1/v2.x, GLiNER2) are trained on ~512-token
windows. Both upstream APIs **truncate silently** when a chunk is longer: no
exception, no truncated-count, no warning — the tail of the input is simply
never scored. Measured on this corpus with the checkpoints' own DeBERTa-v3
tokenizer, a fixed 2,000-character chunk exceeds a 512-token window for
**12.96%** of chunks (worst case 1,977 tokens), and even 1,500 chars does so for
2.82%. Fixed character chunking therefore silently drops entities.

This module sizes chunks against an actual **token budget** instead:

* candidates are grown to ``max_chars`` and snap forward to their last whole
  word, so chunks tile the text with no overlap and no dropped words;
* any candidate still above ``max_tokens`` is recursively halved on word
  boundaries, so the budget holds even for dense text (long chemical names,
  tables) where characters-per-token is unusually low.

Because every boundary falls on a word edge, a chunk never splits an entity
mid-word and returned spans always slice-verify against the source text.
Offsets are absolute within the input string.
"""

import re

_WORD_RE = re.compile(r"\S+")


def split_words(text, start, end, ntokens, max_tokens):
    """Split ``text[start:end]`` into word-aligned spans under ``max_tokens``.

    Args:
        text: the full string; offsets are absolute within it.
        start, end: region to split.
        ntokens: callable mapping a string to its token count.
        max_tokens: hard upper bound on tokens per returned span.

    Returns:
        list of ``(start, end)`` spans covering every non-whitespace character
        in the region, in order.
    """
    # NOTE: finditer(text, pos, endpos) yields ABSOLUTE offsets; do not add start.
    spans = [(m.start(), m.end()) for m in _WORD_RE.finditer(text, start, end)]
    if not spans:
        return []
    if ntokens(text[spans[0][0]:spans[-1][1]]) <= max_tokens or len(spans) == 1:
        return [(spans[0][0], spans[-1][1])]
    mid = len(spans) // 2
    return (split_words(text, spans[0][0], spans[mid - 1][1], ntokens, max_tokens) +
            split_words(text, spans[mid][0], spans[-1][1], ntokens, max_tokens))


def token_chunks(text, ntokens, max_chars=1200, max_tokens=480):
    """Yield word-aligned ``(start, end)`` chunks that respect a token budget.

    The cursor advances to the snapped right edge (never by a fixed stride), so
    chunks tile the text exactly: consecutive chunks skip only whitespace.
    """
    n = len(text)
    pos = 0
    while pos < n:
        hi = min(pos + max_chars, n)
        if hi < n:
            m = _WORD_RE.search(text, hi)
            hi = m.end() if m else n
        if text[pos:hi].strip():
            yield from split_words(text, pos, hi, ntokens, max_tokens)
        pos = hi
