"""D01 - Independent re-verification of mention offsets against section text.

Re-derives every mention's surface form from the frozen section text and compares
it with the stored `surface_form`. This independently tests the offset claim
rather than inheriting it from `offset_status`.

Reference text is taken from the frozen CDM `section.section_text_original`
column, which is then itself verified two ways:
  1. its sha256 must equal the stored `text_hash_sha256`
  2. it must equal the independent reconstruction from
     `data/segmented_sections_markdown/<paper>.md`
Keying is (paper_id, section_id) because `section_id_original` (e.g. `sec_001`)
is only unique within a paper.

Read-only. Writes no release artifact.
"""

from __future__ import annotations

import hashlib
import re
import sys
from collections import Counter, defaultdict

sys.path.insert(0, str(__file__.rsplit("/", 1)[0]))
from common import DB, SECTIONS, connect, emit

SEG_RE = re.compile(
    r"<!-- SEGMENT: (.*?) -->\n"
    r"<!-- SECTION_ID: (.*?) -->\n"
    r"<!-- SECTION_PATH: (.*?) -->\n"
    r"<!-- SEGMENT_ORDINAL_WITHIN_SECTION: (\d+) -->\n"
)
END_RE = re.compile(r"<!-- END_SEGMENT: .*? -->\n?")


def load_markdown_sections():
    """(paper_id, section_id) -> body text, concatenating that section's segments."""
    sec = defaultdict(list)
    if not SECTIONS.exists():
        return None
    for md in sorted(SECTIONS.glob("*.md")):
        paper = md.stem
        raw = md.read_text(encoding="utf-8", errors="surrogateescape")
        parts = SEG_RE.split(raw)
        for i in range(1, len(parts), 5):
            sid = parts[i + 1]
            body = END_RE.sub("", parts[i + 4])
            # The marker regex consumes the newline ending the ordinal line; the
            # remaining body therefore starts with the blank line that followed
            # the marker. section_text_original does not keep it.
            if body.startswith("\n"):
                body = body[1:]
            sec[(paper, sid)].append(body)
    return {k: "".join(v) for k, v in sec.items()}


def main():
    con = connect()

    db_text = {}
    hash_ok = hash_bad = 0
    for r in con.execute(
        "select paper_id, section_id_original, section_text_original, text_hash_sha256, "
        "character_count from section"
    ):
        t = r[2] or ""
        key = (r[0], r[1])
        db_text[key] = t
        h = hashlib.sha256(t.encode("utf-8", errors="surrogateescape")).hexdigest()
        if h == r[3]:
            hash_ok += 1
        else:
            hash_bad += 1

    md = load_markdown_sections()
    md_status = "SKIPPED"
    md_equal = md_diff = md_missing = 0
    md_examples = []
    if md is not None:
        md_status = "OK"
        for key, t in db_text.items():
            if key not in md:
                md_missing += 1
                continue
            if md[key] == t:
                md_equal += 1
            else:
                md_diff += 1
                if len(md_examples) < 10:
                    a, b = t, md[key]
                    i = next((k for k, (x, y) in enumerate(zip(a, b)) if x != y), min(len(a), len(b)))
                    md_examples.append(
                        {
                            "key": list(key),
                            "db_len": len(a),
                            "md_len": len(b),
                            "first_diff_at": i,
                            "db_ctx": a[max(0, i - 30): i + 20],
                            "md_ctx": b[max(0, i - 30): i + 20],
                        }
                    )

    total = checked = exact = mismatch = oor = missing = nul = no_off = 0
    by_source = Counter()
    by_source_mismatch = Counter()
    mismatch_by_type = Counter()
    examples = []

    for r in con.execute(
        "select m.mention_id, m.paper_id, m.section_id, m.surface_form, m.start_offset, "
        "m.end_offset, m.extraction_model, m.extraction_method, m.entity_type "
        "from term_mention m"
    ):
        total += 1
        s, e = r[4], r[5]
        if s is None or e is None:
            no_off += 1
            continue
        key = (r[1], r[2])
        if key not in db_text:
            missing += 1
            continue
        t = db_text[key]
        if s < 0 or e > len(t) or s > e:
            oor += 1
            continue
        checked += 1
        prov = r[6] or r[7] or "unknown"
        by_source[prov] += 1
        got = t[s:e]
        want = r[3] or ""
        if got == want:
            exact += 1
        elif got.replace("\x00", "") == want.replace("\x00", ""):
            nul += 1
            exact += 1
        else:
            mismatch += 1
            by_source_mismatch[prov] += 1
            mismatch_by_type[r[8] or "(none)"] += 1
            if len(examples) < 25:
                examples.append(
                    {
                        "mention_id": r[0],
                        "paper_id": r[1],
                        "section_id": r[2],
                        "stored": want[:80],
                        "recovered": got[:80],
                        "offsets": [s, e],
                        "source": prov,
                        "type": r[8],
                    }
                )

    payload = {
        "status": "OK",
        "reference_text": "CDM section.section_text_original (hash-verified)",
        "section_rows": len(db_text),
        "section_hash_match": hash_ok,
        "section_hash_mismatch": hash_bad,
        "markdown_crosscheck_status": md_status,
        "markdown_equal": md_equal,
        "markdown_differ": md_diff,
        "markdown_missing": md_missing,
        "markdown_examples": md_examples,
        "mentions_total": total,
        "mentions_without_offsets": no_off,
        "mentions_checked": checked,
        "exact_reproduce": exact,
        "mismatch": mismatch,
        "pct_exact_of_checked": round(100.0 * exact / checked, 4) if checked else None,
        "out_of_range": oor,
        "missing_section": missing,
        "explained_by_nul": nul,
        "checked_by_source": dict(by_source),
        "mismatch_by_source": dict(by_source_mismatch),
        "mismatch_by_type": dict(mismatch_by_type),
        "examples": examples,
    }
    emit("d01_offset_integrity", payload)
    print(
        f"section_hash {hash_ok}/{hash_ok + hash_bad}  markdown eq={md_equal} diff={md_diff}\n"
        f"mentions={total:,} checked={checked:,} exact={exact:,} mismatch={mismatch} "
        f"oor={oor} missing={missing} no_off={no_off} pct={payload['pct_exact_of_checked']}"
    )


if __name__ == "__main__":
    main()
