#!/usr/bin/env python3
"""Stage 55: deterministic verification of finding evidence quotes (template §4).

CPU-only, no LLM. For every finding record produced by stage 52:

1. exact substring match of evidence_text in section_text_original
   -> evidence_locator_status = verified_exact
2. normalized match (casefold, unicode NFKC, whitespace collapse, unify quotes/
   dashes, strip punctuation) with a char-offset map back to the ORIGINAL text
   -> evidence_locator_status = verified_normalized
3. no match -> unresolved_not_in_source (finding KEPT and flagged, never dropped)

On a match the record gets:
   evidence_locator = "section:<section_record_id>#chars=<start>-<end>"
   evidence_locator_chars = [start, end]  (offsets on section_text_original)
   evidence_locator_convention = "section-local chars on section_text_original"

verification_status stays "pending" everywhere - human review is the gate; this
stage only fills evidence_locator_status.

Outputs
  data/findings.jsonl                        (updated in place, atomic rewrite)
  validation/findings_report.json
"""
import json
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import pipeline.common as C

STAGE = "stage55_findings_verify"
PV = "2.1.0"

STATUS_EXACT = "verified_exact"
STATUS_NORMALIZED = "verified_normalized"
STATUS_UNRESOLVED = "unresolved_not_in_source"

REPLACEMENTS = {
    "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"',
    "\u2013": "-", "\u2014": "-", "\u2212": "-",
    "\u00a0": " ",
}


def norm_map(text: str):
    """Return (normalized_text, offsets) where offsets[i] is the index in
    `text` of the original char that produced normalized char i."""
    out_chars, offsets = [], []
    for i, ch in enumerate(text):
        for src, dst in REPLACEMENTS.items():
            if ch == src:
                ch = dst
                break
        decomposed = unicodedata.normalize("NFKC", ch)
        for dch in decomposed:
            if dch.isalnum():
                out_chars.append(dch.casefold())
                offsets.append(i)
            elif dch.isspace():
                if out_chars and out_chars[-1] == " ":
                    offsets[-1] = i      # extend previous space if contiguous
                else:
                    out_chars.append(" ")
                    offsets.append(i)
            # punctuation/diacritics dropped entirely
    if out_chars and out_chars[-1] == " ":
        out_chars.pop()
        offsets.pop()
    return "".join(out_chars), offsets


def locate_exact(quote: str, text: str):
    pos = text.find(quote)
    if pos == -1:
        # try a whitespace-collapsed exact match first: still counts as exact
        # if every non-space character is identical in order
        return None
    return pos, pos + len(quote)


def check_quote(quote: str, text: str):
    """Return (status, (start, end) or None)."""
    if not quote:
        return STATUS_UNRESOLVED, None
    span = locate_exact(quote, text)
    if span:
        return STATUS_EXACT, span
    n_text, offsets_t = norm_map(text)
    n_quote, _ = norm_map(quote)
    if not n_quote.strip():
        return STATUS_UNRESOLVED, None
    pos = n_text.find(n_quote)
    if pos == -1:
        return STATUS_UNRESOLVED, None
    start = offsets_t[pos]
    end_idx = pos + len(n_quote) - 1
    if end_idx >= len(offsets_t):
        return STATUS_UNRESOLVED, None
    end = offsets_t[end_idx] + 1
    return STATUS_NORMALIZED, (start, end)


def main():
    C.require_slurm(STAGE)
    cfg = C.load_config()
    ev = C.Events(cfg["corpus"]["corpus_id"], STAGE, PV)
    started = C.now_utc()

    findings = C.read_jsonl(C.CORPUS_DIR / "data" / "findings.jsonl")
    sections = C.read_jsonl(C.CORPUS_DIR / "data" / "sections.jsonl")
    if not findings:
        sys.exit("ERROR: data/findings.jsonl missing or empty; run stage 52 first")
    sec_text = {s["section_record_id"]: s for s in sections}

    status_counts = Counter()
    no_section = no_hash_match = 0
    prog = C.Progress(STAGE, total=len(findings), unit="finding", desc="verify")
    n_map_cache = {}

    for f in findings:
        sid = f.get("evidence_section_id")
        sec = sec_text.get(sid)
        quote = (f.get("evidence_text") or "").strip()
        status, span = STATUS_UNRESOLVED, None
        if sec is None:
            no_section += 1
        else:
            text = sec.get("section_text_original") or ""
            status, span = check_quote(quote, text)
            # verify the finding was produced against this text version
            if f.get("text_version_id") and sec.get("text_hash_sha256") and \
                    f["text_version_id"] != sec["text_hash_sha256"]:
                no_hash_match += 1
        f["evidence_locator_status"] = status
        f["verification_status"] = "pending"   # human review remains the gate
        if span and sec is not None:
            f["evidence_locator"] = f"section:{sid}#chars={span[0]}-{span[1]}"
            f["evidence_locator_convention"] = \
                "char offsets on section_text_original (section-local)"
            f["evidence_locator_chars"] = [span[0], span[1]]
        else:
            f["evidence_locator"] = f"section:{sid}" if sid else None
            f["evidence_locator_convention"] = \
                "section identifier only; quote not recoverable by offset"
            f["evidence_locator_chars"] = None
        status_counts[status] += 1
        prog.update(1)

    C.write_jsonl(C.CORPUS_DIR / "data" / "findings.jsonl", findings)

    n = len(findings)
    exact = status_counts[STATUS_EXACT]
    norm = status_counts[STATUS_NORMALIZED]
    unres = status_counts[STATUS_UNRESOLVED]
    summary = {
        "stage": STAGE, "pipeline_version": PV, "generated_at": C.now_utc(),
        "findings_total": n,
        "verified_exact": exact,
        "verified_normalized": norm,
        "unresolved_not_in_source": unres,
        "quote_resolution_rate": round((exact + norm) / n, 4) if n else 0,
        "findings_missing_section_ref": no_section,
        "findings_with_mismatched_text_version": no_hash_match,
        "evidence_locator_status_counts": dict(status_counts),
        "verification_status_note":
            "verification_status stays pending for all findings - human review "
            "is the gate; evidence_locator_status records the automated check only",
        "unresolved_policy":
            "unresolved findings are kept and flagged, never dropped",
        "direction_by_claim_type": {
            ct: {d: sum(1 for f in findings if f.get("claim_type") == ct
                       and f.get("direction") == d)
                 for d in sorted({f.get("direction") for f in findings
                                  if f.get("claim_type") == ct})}
            for ct in sorted({f.get("claim_type") for f in findings})
        },
    }
    C.atomic_write_json(C.CORPUS_DIR / "validation" / "findings_report.json", summary)
    ev.record(pipeline_stage=STAGE,
              run_status="success",
              started_at=started, completed_at=C.now_utc(),
              output_artifact_hash=C.sha256_text(json.dumps(summary, sort_keys=True)),
              note=f"findings={n} exact={exact} normalized={norm} unresolved={unres}")
    ev.close()
    prog.close(summary=f"total={n} exact={exact} normalized={norm} unresolved={unres}")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
