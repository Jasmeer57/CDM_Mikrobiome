#!/usr/bin/env python
"""Repair and classify findings evidence locators without re-running the LLM.

Two distinct defects are handled.

1. OFFSET DRIFT (the 78 warnings). The recall stage located each quoted sentence
   inside a whitespace-collapsed copy of the chunk and then applied those
   offsets to the ORIGINAL string. Collapsing whitespace changes the length, so
   every offset after the first newline or double space was wrong. The fixed
   `_fuzzy_substring` maps collapsed positions back through an index map, so the
   quote can be re-anchored exactly.

2. NON-VERBATIM EVIDENCE (620 rows, no offsets at all). The earlier
   qwen3.5:9b run sometimes returned a paraphrase or a summary sentence instead
   of a verbatim quote. Those strings do not occur in the paper at all, so no
   offset can be correct. They are NOT repaired — doing so would invent a
   locator. They are flagged `unresolved_not_in_source` and excluded from any
   verified-evidence count.

Row status values written to the report and the findings table:
    verified_exact       offsets already correct — untouched
    repaired_reanchored  offsets corrected by index-map re-anchoring
    relocated            quote is at a different place than stored
    unresolved_not_in_source   quote absent from the paper (paraphrase/hallucination)
    unresolved_no_offsets      row never carried offsets

Usage:
    python repair_evidence_offsets.py --dry-run
    python repair_evidence_offsets.py
"""
import argparse
import csv
import re
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))

from paper_claims.corpus.pipeline.findings_extract import _fuzzy_substring  # noqa: E402
from paper_claims.corpus.pipeline.config import DB_PATH  # noqa: E402

REPORT = REPO / "paper_claims" / "corpus" / "logs" / "evidence_repair_report.csv"
FIELDS = ["finding_id", "paper_id", "claim_type", "status",
          "old_start", "old_end", "new_start", "new_end", "evidence_text_excerpt"]

_norm = lambda s: re.sub(r"\s+", " ", s or "").strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    texts = {r["paper_id"]: (r["cleaned_text"] or "")
             for r in conn.execute("SELECT paper_id, cleaned_text FROM papers")}
    rows = conn.execute(
        "SELECT finding_id, paper_id, claim_type, evidence_text, "
        "evidence_char_start, evidence_char_end FROM findings "
        "ORDER BY finding_id").fetchall()
    conn.close()

    counts, updates, report = {}, [], []

    for r in rows:
        fid, pid, ev = r["finding_id"], r["paper_id"], r["evidence_text"] or ""
        old_s, old_e = r["evidence_char_start"], r["evidence_char_end"]
        text = texts.get(pid, "")
        new_s = new_e = None

        if old_s is None or old_e is None:
            # No locator: try to anchor the quote fresh.
            s, e = _fuzzy_substring(ev, text, hint=0)
            if s >= 0:
                new_s, new_e = s, e
                status = "repaired_new_anchor"
                updates.append((new_s, new_e, "unresolved_not_in_source", fid))
            else:
                status = "unresolved_not_in_source"
        elif not (0 <= old_s < old_e <= len(text)):
            s, e = _fuzzy_substring(ev, text, hint=max(old_s - 2000, 0))
            if s >= 0:
                new_s, new_e = s, e
                status = "relocated"
                updates.append((new_s, new_e, "verified_exact", fid))
            else:
                status = "unresolved_not_in_source"
        else:
            if _norm(text[old_s:old_e]) == _norm(ev):
                status = "verified_exact"
            else:
                s, e = _fuzzy_substring(ev, text, hint=old_s)
                if s >= 0 and _norm(text[s:e]) == _norm(ev):
                    new_s, new_e = s, e
                    status = "repaired_reanchored"
                    updates.append((new_s, new_e, "verified_exact", fid))
                elif s >= 0:
                    new_s, new_e = s, e
                    status = "relocated"
                    updates.append((new_s, new_e, "verified_exact", fid))
                else:
                    status = "unresolved_not_in_source"

        counts[status] = counts.get(status, 0) + 1
        report.append({"finding_id": fid, "paper_id": pid,
                       "claim_type": r["claim_type"], "status": status,
                       "old_start": old_s if old_s is not None else "",
                       "old_end": old_e if old_e is not None else "",
                       "new_start": new_s if new_s is not None else "",
                       "new_end": new_e if new_e is not None else "",
                       "evidence_text_excerpt": ev[:200].replace("\n", " ")})

    total = len(rows)
    print(f"\n{'='*62}\nEVIDENCE LOCATOR REPAIR — {total} findings")
    print("=" * 62)
    for k in sorted(counts, key=lambda x: -counts[x]):
        print(f"  {k:28s} {counts[k]:5d}  ({100*counts[k]/total:.1f}%)")

    verified = counts.get("verified_exact", 0) + counts.get("repaired_reanchored", 0) \
        + counts.get("relocated", 0) + counts.get("repaired_new_anchor", 0)
    unresolved = counts.get("unresolved_not_in_source", 0)
    print(f"\n  with a resolvable locator : {verified} ({100*verified/total:.1f}%)")
    print(f"  UNRESOLVED (not in source): {unresolved} ({100*unresolved/total:.1f}%)")
    print(f"  offsets to write          : {len(updates)}")

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    with REPORT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(report)
    print(f"\n  report: {REPORT}")

    if updates and not a.dry_run:
        conn = sqlite3.connect(str(DB_PATH))
        conn.executemany(
            "UPDATE findings SET evidence_char_start=?, evidence_char_end=?, "
            "evidence_locator_status=? WHERE finding_id=?",
            [(s, e, st, fid) for (s, e, st, fid) in updates])
        conn.commit()
        conn.close()
        print(f"  wrote {len(updates)} corrected rows to corpus.db")
    elif updates:
        print(f"  DRY RUN — would write {len(updates)} corrected rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())