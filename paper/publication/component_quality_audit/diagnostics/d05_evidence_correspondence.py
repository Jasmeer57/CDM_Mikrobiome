"""D05 - Evidence-to-value correspondence for catalogue and triple records.

This is the audit's central "is the quoted evidence really there" test. It is
deliberately NOT an accuracy measure: it asks only whether the text the CDM
points at can be located at the stated coordinates in the frozen section text.

Four outcomes are reported separately and never collapsed:
  LOCATED_EXACT              evidence == section_text[start:end] byte for byte
  LOCATED_NORMALISED         equal after whitespace/case/dash/quote folding
  LOCATED_FUZZY              high similarity at offsets, or exact containment
  LOCATED_UNVERIFIED_OFFSET  no offsets stored; text found by containment only
  UNABLE_TO_VERIFY           section unresolvable, empty evidence, or not found

Both section-id formats are resolved: `HMPAPER_x:sec:NNN` (section_record_id)
and bare `sec_NNN` (section_id_original, unique only within a paper).

Every (table, column) pair is checked against PRAGMA table_info first: SQLite
silently treats a double-quoted unknown identifier as a string literal, which
would turn a typo into a fabricated 100% failure rate.

Read-only. Writes no release artifact.
"""

from __future__ import annotations

import difflib
import re
import sys
from collections import Counter, defaultdict

sys.path.insert(0, str(__file__.rsplit("/", 1)[0]))
from common import connect, emit

WS_RE = re.compile(r"\s+")
FOLD = (("\u2019", "'"), ("\u2018", "'"), ("\u201c", '"'), ("\u201d", '"'),
        ("\u2013", "-"), ("\u2014", "-"), ("\u2212", "-"), ("\u00a0", " "))


def norm(s):
    return WS_RE.sub(" ", (s or "")).strip().lower()


def norm_loose(s):
    s = norm(s)
    for a, b in FOLD:
        s = s.replace(a, b)
    return s


def require_columns(con, table, wanted):
    have = {r[1] for r in con.execute(f'PRAGMA table_info("{table}")')}
    missing = [c for c in wanted if c and c not in have]
    if missing:
        raise SystemExit(f"FATAL {table}: missing columns {missing} (have {sorted(have)})")


def load_sections(con):
    by_record = {}
    by_bare = defaultdict(list)
    for rec, paper, bare, text in con.execute(
        "select section_record_id, paper_id, section_id_original, "
        "section_text_original from section"
    ):
        by_record[rec] = (paper, bare, text or "")
        by_bare[(paper, bare)].append(rec)
    return by_record, by_bare


BRACKET_RE = re.compile(r"\[([^\]]+)\]")


def section_ref(raw):
    """Catalogue evidence_location is a display string, not a key.

    Examples: 'RESULTS [sec_003] chars 40-174',
              'external: corpus papers.csv bioproject (exact_bioproject_accession)'
    The bracketed token is the section_id_original; anything else is unparseable.
    """
    if not raw:
        return None
    m = BRACKET_RE.search(raw)
    if m:
        return m.group(1).strip()
    return None


def resolve(section_id, paper_id, by_record, by_bare):
    if not section_id:
        return None, None
    if section_id in by_record:
        return section_id, by_record[section_id][2]
    cands = by_bare.get((paper_id, section_id))
    if cands and len(cands) == 1:
        return cands[0], by_record[cands[0]][2]
    return None, None


def classify(evidence, text, start, end):
    if not evidence or not evidence.strip():
        return "UNABLE_TO_VERIFY", "no_evidence_text"
    if start is None or end is None:
        if norm_loose(evidence) in norm_loose(text):
            return "LOCATED_UNVERIFIED_OFFSET", "containment_only"
        return "UNABLE_TO_VERIFY", "no_offsets_no_containment"
    if start < 0 or end > len(text) or end <= start:
        return "UNABLE_TO_VERIFY", "offset_out_of_range"
    sl = text[start:end]
    if sl == evidence:
        return "LOCATED_EXACT", ""
    if norm_loose(sl) == norm_loose(evidence):
        return "LOCATED_NORMALISED", ""
    if len(evidence) > 20:
        ratio = difflib.SequenceMatcher(None, norm_loose(sl), norm_loose(evidence)).ratio()
        if ratio >= 0.85:
            return "LOCATED_FUZZY", f"similarity={ratio:.3f}"
    if norm_loose(evidence) in norm_loose(text):
        return "LOCATED_FUZZY", "contained_elsewhere"
    return "UNABLE_TO_VERIFY", "text_not_at_offsets"


def run_table(con, table, id_col, paper_col, section_col, evidence_col,
              start_col, end_col, by_record, by_bare, group_cols=None,
              section_is_display=False):
    """group_cols: list of columns to cross-tabulate outcomes by (may be empty)."""
    group_cols = [c for c in (group_cols or []) if c]
    require_columns(con, table, [id_col, paper_col, section_col, evidence_col,
                                 start_col, end_col] + group_cols)
    res = Counter()
    reasons = Counter()
    by_group = defaultdict(Counter)
    examples = []
    n = 0
    cols = [id_col, paper_col, section_col, evidence_col, start_col, end_col] + group_cols
    sel = ", ".join(f'"{c}"' for c in cols)
    for row in con.execute(f'select {sel} from "{table}"'):
        n += 1
        v = dict(zip(cols, row))
        keys = [str(v[c]) for c in group_cols]
        sid = section_ref(v[section_col]) if section_is_display else v[section_col]
        if sid is None and section_is_display:
            # e.g. 'external: corpus papers.csv ...' - declared non-corpus provenance
            outcome, reason = ("UNABLE_TO_VERIFY",
                               "no_section_ref"
                               if not (v[evidence_col] or "").strip()
                               else "no_section_ref")
            res[outcome] += 1
            reasons[reason] += 1
            for k in keys:
                by_group[k][outcome] += 1
            continue
        rid, text = resolve(sid, v[paper_col], by_record, by_bare)
        if rid is None:
            outcome, reason = "UNABLE_TO_VERIFY", "section_unresolvable"
        else:
            outcome, reason = classify(v[evidence_col], text, v[start_col], v[end_col])
        res[outcome] += 1
        if reason:
            reasons[reason] += 1
        if outcome == "UNABLE_TO_VERIFY" and len(examples) < 6:
            examples.append({"id": v[id_col], "paper": v[paper_col],
                             "section": str(v[section_col])[:60], "reason": reason,
                             "evidence": (v[evidence_col] or "")[:120]})
        for k in keys:
            by_group[k][outcome] += 1
    tot = n or 1
    payload = {
        "table": table,
        "records": n,
        "outcomes": dict(res),
        "pct": {k: round(100.0 * c / tot, 3) for k, c in res.items()},
        "failure_reasons": dict(reasons.most_common(10)),
        "examples_unable": examples,
        "group_cols": group_cols,
        "by_group": {k: dict(c) for k, c in by_group.items()},
    }
    print(f"\n[{table}] {n:,} records")
    for k in ("LOCATED_EXACT", "LOCATED_NORMALISED", "LOCATED_FUZZY",
              "LOCATED_UNVERIFIED_OFFSET", "UNABLE_TO_VERIFY"):
        if res.get(k):
            print(f"   {k:26s} {res[k]:>8,}  {100.0*res[k]/tot:6.2f}%")
    if reasons:
        print("   reasons:", dict(reasons.most_common(6)))
    for g, c in sorted(by_group.items(), key=lambda kv: -sum(kv[1].values()))[:14]:
        t = sum(c.values())
        print(f"   {g:26s} n={t:>7,} "
              f"exact={c.get('LOCATED_EXACT',0):>7,} ({100.0*c.get('LOCATED_EXACT',0)/t:5.1f}%) "
              f"unable={c.get('UNABLE_TO_VERIFY',0):>7,}")
    return payload


def main():
    con = connect()
    by_record, by_bare = load_sections(con)
    print(f"sections loaded: {len(by_record):,}")
    out = {"status": "OK", "sections": len(by_record), "tables": []}

    out["tables"].append(run_table(
        con, "claim_evidence", "finding_id", "paper_id", "section_id",
        "evidence_text", "char_start", "char_end", by_record, by_bare,
        group_cols=["claim_source", "evidence_anchor_status"]))

    out["tables"].append(run_table(
        con, "relation_evidence", "triple_mention_id", "paper_id",
        "section_record_id", "source_sentence", "char_start", "char_end",
        by_record, by_bare, group_cols=["relation_table", "anchor_status"]))

    for t, icol in (("dataset", "dataset_id"), ("sample", "sample_group_id"),
                    ("assay", "assay_id"), ("cohort", "cohort_id"),
                    ("data_asset", "asset_id")):
        out["tables"].append(run_table(
            con, t, icol, "paper_id", "evidence_location", "evidence_text",
            "evidence_span_start", "evidence_span_end", by_record, by_bare,
            group_cols=["evidence_anchor_status"], section_is_display=True))

    emit("d05_evidence_correspondence", out)


if __name__ == "__main__":
    main()
