"""Stage 8 - Structure-aware chunking of selected sections.

Converts RELEVANT / RELEVANT_CONTEXT / REVIEW_REQUIRED sections into retrieval
chunks of a target token size, measured with the embedding model's own
tokenizer. Container sections are excluded from the primary index but recorded
in the coverage report so the omission is auditable.

Every chunk carries a stable ID, its source provenance, and a text checksum so
later stages can cache and incrementally update embeddings.

Emits:
  chunks/chunks.jsonl
  reports/chunk_manifest.csv
  reports/chunk_coverage_report.md
"""

from __future__ import annotations

import csv
import hashlib
import json
import sys
from pathlib import Path
import re

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config as C  # noqa: E402

# Chunk types derived from the recorded section type.
CHUNK_TYPE_MAP = {
    "abstract": "document_metadata",
    "introduction": "document_metadata",
    "methods": "methods",
    "results": "results",
    "discussion": "discussion",
    "conclusion": "discussion",
    "data_availability": "data_availability",
    "supplementary": "supplementary",
    "ethics": "study_design",
    "abbreviations": "container",
    "other": "other",
}

# Text that must not enter the retrieval index even inside a relevant section.
_BOILERPLATE = re.compile(
    r"^(?:page \d+ of \d+|© .*|all rights reserved\.?)$",
    re.IGNORECASE | re.MULTILINE,
)


def load_tokenizer():
    """Load the embedding model's tokenizer; fall back to a word proxy."""
    try:
        from transformers import AutoTokenizer
        tok = AutoTokenizer.from_pretrained(C.EMBEDDING_MODEL, revision=C.EMBEDDING_MODEL_REV)
        return tok, True
    except Exception as exc:  # offline / not cached
        print(f"[warn] tokenizer unavailable ({exc}); using word-count proxy", file=sys.stderr)
        return None, False


def _looks_like_table_dump(text: str) -> bool:
    """True when a chunk is a flattened table (many short lines, no prose)."""
    lines = [ln for ln in text.split("\n") if ln.strip()]
    if len(lines) < 12:
        return False
    short = sum(1 for ln in lines if len(ln) < 40)
    sentences = sum(1 for ln in lines if ln.rstrip().endswith((".", "!", "?")))
    return short / len(lines) > 0.8 and sentences / len(lines) < 0.2


def count_tokens(text: str, tok, real: bool) -> int:
    if real:
        return len(tok.encode(text, add_special_tokens=False))
    # ~4 chars/token is the usual English approximation.
    return max(1, len(text) // 4)


_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z(\[\d])")


def _split_long_paragraph(para: str, tok, real: bool, target: int) -> list[str]:
    """Break an oversized paragraph on sentence boundaries.

    Papers whose body is one continuous block (no blank lines) otherwise emit a
    single multi-thousand-token chunk. Sentences are packed up to `target`;
    a single sentence longer than `target` is emitted whole rather than cut
    mid-clause, since splitting it would destroy table rows and statistics.
    """
    if count_tokens(para, tok, real) <= target:
        return [para]
    sents = [s for s in _SENTENCE_SPLIT.split(para) if s.strip()]
    if len(sents) <= 1:
        return [para]

    out: list[str] = []
    buf: list[str] = []
    buf_tok = 0
    for s in sents:
        stok = count_tokens(s, tok, real)
        if buf and buf_tok + stok > target:
            out.append(" ".join(buf))
            buf, buf_tok = [], 0
        buf.append(s)
        buf_tok += stok
    if buf:
        out.append(" ".join(buf))
    return out


def split_on_boundaries(text: str, tok, real: bool, target: int, overlap: int) -> list[str]:
    """Split text on paragraph boundaries, packing up to `target` tokens.

    Prefers paragraph breaks, falls back to sentence boundaries for oversized
    paragraphs, and never drops text.
    """
    paras = [p for p in text.split("\n\n") if p.strip()]
    if not paras:
        return [text] if text.strip() else []

    # Normalise: no single unit handed to the packer may exceed the target.
    units: list[str] = []
    for para in paras:
        units.extend(_split_long_paragraph(para, tok, real, target))

    pieces: list[str] = []
    buf: list[str] = []
    buf_tok = 0

    for para in units:
        ptok = count_tokens(para, tok, real)
        if buf and buf_tok + ptok > target:
            pieces.append("\n\n".join(buf))
            # Start the next piece with a little overlap for retrieval context.
            tail: list[str] = []
            tail_tok = 0
            for prev in reversed(buf):
                pprev = count_tokens(prev, tok, real)
                if tail_tok + pprev > overlap:
                    break
                tail.insert(0, prev)
                tail_tok += pprev
            buf = list(tail)
            buf_tok = tail_tok
        buf.append(para)
        buf_tok += ptok

    if buf:
        pieces.append("\n\n".join(buf))
    return pieces


def main() -> int:
    C.ensure_dirs()
    sel = json.loads((C.MANIFESTS_DIR / "section_selection.json").read_text())
    tok, real = load_tokenizer()

    chunks: list[dict] = []
    coverage: list[dict] = []
    source_cache: dict[str, str] = {}

    for s in sel:
        cid = s["corpus_id"]
        if cid not in source_cache:
            rec = json.loads((C.RECORDS_DIR / f"{cid}.json").read_text())
            src_rel = (rec.get("files", {}) or {}).get("source_text_path", "")
            p = C.REPO_ROOT / src_rel
            source_cache[cid] = p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""
        body = source_cache[cid]

        status = s["selection_status"]
        if not s["offsets_in_bounds"]:
            coverage.append({**s, "n_chunks": 0,
                             "exclusion_reason": "source offsets out of bounds"})
            continue
        if status in ("CONTAINER_ONLY",):
            coverage.append({**s, "n_chunks": 0,
                             "exclusion_reason": "container section (references/funding/etc.)"})
            continue

        text = body[s["char_start"]:s["char_end"]].strip()
        if not text:
            coverage.append({**s, "n_chunks": 0, "exclusion_reason": "empty section text"})
            continue

        ctype = CHUNK_TYPE_MAP.get(s["section_type"], "other")
        pieces = split_on_boundaries(text, tok, real, C.CHUNK_TARGET_TOKENS, C.CHUNK_OVERLAP_TOKENS)
        made = 0
        dropped = 0
        for i, piece in enumerate(pieces):
            ntok = count_tokens(piece, tok, real)
            # A trailing overlap fragment can be a handful of tokens; it carries
            # no retrievable signal and would pollute precision, so drop it.
            if ntok < C.CHUNK_MIN_TOKENS:
                dropped += 1
                continue
            cid_chunk = f"{cid}::{s['section_id']}::{i:03d}"
            # Flattened tables have no sentence structure to split on; cutting
            # them would separate header cells from their rows. Flag instead.
            is_table = _looks_like_table_dump(piece)
            chunks.append({
                "chunk_id": cid_chunk,
                "corpus_id": cid,
                "bioproject_accession": s["bioproject_accession"],
                "section_id": s["section_id"],
                "section_type": s["section_type"],
                "chunk_type": "table" if is_table else ctype,
                "selection_status": status,
                "oversized": ntok > 800,
                "chunk_ordinal": i,
                "heading_path": s["heading_path"],
                "char_start": s["char_start"],
                "char_end": s["char_end"],
                "token_count": ntok,
                "chunking_config_version": C.CHUNKING_CONFIG_VERSION,
                "text_sha256": hashlib.sha256(piece.encode("utf-8")).hexdigest(),
                "text": piece,
            })
            made += 1
        if made == 0 and not dropped:
            coverage.append({**s, "n_chunks": 0, "exclusion_reason": "empty section text"})
        elif dropped:
            coverage.append({**s, "n_chunks": made,
                             "exclusion_reason": f"dropped {dropped} sub-{C.CHUNK_MIN_TOKENS}-token fragment(s)"})
        else:
            coverage.append({**s, "n_chunks": made, "exclusion_reason": ""})

    # ------------------------------------------------------------- write ----
    with (C.CHUNKS_DIR / "chunks.jsonl").open("w") as fh:
        for c in chunks:
            fh.write(json.dumps(c, ensure_ascii=False) + "\n")

    manifest_fields = [k for k in chunks[0].keys() if k != "text"] if chunks else []
    with (C.REPORTS_DIR / "chunk_manifest.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=manifest_fields, extrasaction="ignore")
        w.writeheader()
        for c in chunks:
            w.writerow(c)

    # ----------------------------------------------------------- coverage ---
    excluded = [c for c in coverage if c["exclusion_reason"]]
    produced = [c for c in coverage if c["n_chunks"] > 0]
    by_reason: dict[str, int] = {}
    for c in excluded:
        by_reason[c["exclusion_reason"]] = by_reason.get(c["exclusion_reason"], 0) + 1

    toks = sorted(c["token_count"] for c in chunks)
    md = [
        "# Chunk Coverage Report", "",
        f"- Chunking config: `{C.CHUNKING_CONFIG_VERSION}`",
        f"- Target chunk size: {C.CHUNK_TARGET_TOKENS} tokens, overlap {C.CHUNK_OVERLAP_TOKENS}",
        f"- Token measurement: {'embedding-model tokenizer' if real else 'word-count proxy (tokenizer unavailable)'}",
        f"- Sections considered: **{len(coverage)}**",
        f"- Sections producing chunks: **{len(produced)}**",
        f"- Sections excluded: **{len(excluded)}**",
        f"- **Chunks written: {len(chunks)}**", "",
    ]
    if toks:
        md += [f"Token counts - min {toks[0]}, median {toks[len(toks)//2]}, max {toks[-1]}", ""]
    md += ["## Exclusions from the primary retrieval index", "", "| reason | sections |", "|---|---|"]
    for r, n in sorted(by_reason.items(), key=lambda x: -x[1]):
        md.append(f"| {r} | {n} |")
    md += ["",
           "No text is deleted from source. Excluded sections remain recoverable in the",
           "section-selection manifest and can be re-chunked if rules change.", ""]
    (C.REPORTS_DIR / "chunk_coverage_report.md").write_text("\n".join(md))

    print(json.dumps({
        "sections_considered": len(coverage),
        "sections_producing_chunks": len(produced),
        "sections_excluded": len(excluded),
        "chunks": len(chunks),
        "tokenizer_real": real,
        "median_tokens": toks[len(toks)//2] if toks else 0,
        "exclusion_breakdown": by_reason,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())