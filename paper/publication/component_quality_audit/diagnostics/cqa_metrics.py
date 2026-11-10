#!/usr/bin/env python3
"""Build 16_QUALITY_METRICS.csv from the fourteen component reports.

The audit brief forbids an averaged score, so this file is deliberately
*long*: one row per (component, dimension) with the rating exactly as the
component report published it, plus the component-level issue counts.

Two normalisations are applied and recorded in separate columns rather
than silently replacing the published value:

  * ``CRITICAL`` is recorded into ``rating`` as the five-level token
    ``CRITICAL WEAKNESS`` (the brief's scale) because components F/H/M/L
    and the register both use the short form for the same level,
    while ``rating_as_published`` keeps the source wording.
  * ``MODERATE`` is **not** on the brief's five-level scale. It appears
    once, as component J's "Error introduction" rating. It is kept
    verbatim in ``rating`` (it is not our value to change), normalised
    to ``WEAK`` in ``rating_normalised`` and flagged
    ``scale_conformant = no``. See 19_AUDIT_REPRODUCIBILITY.md.

Generator-produced. Do not hand edit; rerun this script.

Usage:
    python3 diagnostics/cqa_metrics.py
"""

from __future__ import annotations

import csv
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
AUDIT = os.path.dirname(HERE)
REPO = os.path.dirname(os.path.dirname(os.path.dirname(AUDIT)))

REPORTS = [
    ("A", "Literature corpus quality", "01_CORPUS_QUALITY.md"),
    ("B", "Entity mention extraction quality", "02_ENTITY_EXTRACTION_QUALITY.md"),
    ("C", "Canonical terminology quality", "03_TERMINOLOGY_QUALITY.md"),
    ("D", "Vocabulary mapping quality", "04_MAPPING_QUALITY.md"),
    ("E", "Definition quality", "05_DEFINITION_QUALITY.md"),
    ("F", "Data catalogue quality", "06_CATALOGUE_QUALITY.md"),
    ("G", "Triple and knowledge-graph quality", "07_TRIPLE_AND_KG_QUALITY.md"),
    ("H", "CDM schema and database quality", "08_CDM_QUALITY.md"),
    ("I", "NER benchmark quality", "09_NER_BENCHMARK_QUALITY.md"),
    ("J", "Post-freeze cleaned layer", "10_CLEANED_LAYER_QUALITY.md"),
    ("K", "BugSigDB comparison quality", "11_BUGSIGDB_COMPARISON_QUALITY.md"),
    ("L", "Triple reference validation", "12_TRIPLE_REFERENCE_QUALITY.md"),
    ("M", "Interoperability and portability", "13_INTEROPERABILITY_QUALITY.md"),
    ("N", "Rights readiness and redaction integrity", "14_RIGHTS_READINESS_QUALITY.md"),
]

# The brief's ordinal scale, best to worst, plus the terminal "not measured".
SCALE = [
    "STRONG",
    "ADEQUATE",
    "WEAK",
    "CRITICAL WEAKNESS",
    "NOT EVALUATED",
]

# Tokens the reports actually use -> the brief's token.
ALIASES = {
    "CRITICAL": "CRITICAL WEAKNESS",
    "CRITICAL WEAKNESS": "CRITICAL WEAKNESS",
    "WEAK (UNINFORMATIVE)": "WEAK",
}

# Severity tokens that are not on the rating scale. Normalised for
# cross-component comparison only; the published token is preserved.
OFF_SCALE = {"MODERATE": "WEAK"}

SEV_ORDER = ["CRITICAL", "HIGH", "MODERATE", "LOW"]


def clean(cell: str) -> str:
    """Strip markdown emphasis, escaped pipes and newlines from a table cell."""
    s = cell.replace("\\|", "/").replace("|", "/")
    s = re.sub(r"\*\*(.+?)\*\*", r"\1", s)
    s = re.sub(r"\*(.+?)\*", r"\1", s)
    s = re.sub(r"`([^`]*)`", r"\1", s)
    s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def parse_dims(path: str):
    """Return [(dimension, rating_raw, evidence, indicator, limitation, confidence)].

    Reads only the table that starts with the literal header
    ``| Dimension | Rating |`` so that the many secondary tables in these
    reports (type tables, anchor tables, field-concordance tables) cannot
    leak in. A component may carry more than one such table; all are read.
    """
    out = []
    in_table = False
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if line.startswith("| Dimension | Rating |"):
                in_table = True
                continue
            if not in_table:
                continue
            if not line.startswith("|"):
                # A blank line or prose ends the contiguous table.
                if out:
                    in_table = False
                continue
            cells = [c for c in line.strip().strip("|").split("|")]
            if all(set(c.strip()) <= set("-: ") for c in cells):
                continue
            if len(cells) < 6:
                continue
            # The five right-hand columns are fixed (rating, <evidence...>,
            # indicator, limitation, confidence). Only the *evidence* cell can
            # carry a literal ``|`` in its prose -- e.g. ``KEEP|INCLUDE_TEXT``
            # or ``(null)||(null)`` -- which a naive split turns into extra
            # cells and shifts every column after it. Anchor on the tail so
            # that every row parses to exactly dimension + rating + evidence +
            # indicator + limitation + confidence.
            if len(cells) > 6:
                head = cells[:1]
                rating = cells[1:2]
                tail = cells[-3:]
                evidence = ["|".join(cells[2:-3])]
                cells = head + rating + evidence + tail
            out.append(tuple(c.strip() for c in cells[:6]))
    return out


def load_register():
    """component -> {'total', 'CRITICAL', 'HIGH', 'MODERATE', 'LOW', 'ids_by_sev'}

    Amendment rows (``*AMEND*``) are counted separately: they are audit
    corrections, not findings about the data.
    """
    path = os.path.join(AUDIT, "15_ISSUE_REGISTER.csv")
    stats = {}
    with open(path, encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            comp = row["component"]
            s = stats.setdefault(
                comp,
                {
                    "total": 0,
                    "findings": 0,
                    "amendments": 0,
                    "CRITICAL": 0,
                    "HIGH": 0,
                    "MODERATE": 0,
                    "LOW": 0,
                    "release_blocking": 0,
                },
            )
            s["total"] += 1
            if row["type_class"] == "AUDIT_CORRECTION":
                s["amendments"] += 1
            else:
                s["findings"] += 1
            sev = row["severity"]
            if sev in s:
                s[sev] += 1
            bs = (row.get("blocking_status") or "").lower()
            if "release" in bs and "not" not in bs.split("release")[0][-12:]:
                s["release_blocking"] += 1
    return stats


def main(argv=None):
    reg = load_register()
    rows = []
    problems = []

    for comp, name, fname in REPORTS:
        path = os.path.join(AUDIT, fname)
        dims = parse_dims(path)
        if not dims:
            problems.append(f"{comp}: no dimension table parsed in {fname}")
            continue
        st = reg.get(comp, {})
        for dim, raw, ev, ind, lim, conf in dims:
            published = clean(raw)
            key = published.upper().strip()
            # 09 carries an inline amendment note inside the rating cell.
            key = re.sub(r"\s*\(.*?\)\s*", " ", key).strip()

            if key in ALIASES:
                rating = ALIASES[key]
                conformant = "yes"
                normalised = rating
            elif key in OFF_SCALE:
                rating = published
                conformant = "no"
                normalised = OFF_SCALE[key]
            elif key in SCALE:
                rating = key
                conformant = "yes"
                normalised = key
            else:
                rating = published
                conformant = "no"
                normalised = "UNCLASSIFIED"
                problems.append(f"{comp}/{dim}: unrecognised rating {raw!r}")

            conf_clean = clean(conf).lower()
            if conf_clean not in ("high", "medium", "low"):
                conf_clean = clean(conf) or "unstated"

            rows.append(
                {
                    "component": comp,
                    "component_name": name,
                    "report_file": fname,
                    "dimension": clean(dim),
                    "rating": rating,
                    "rating_as_published": published,
                    "rating_normalised": normalised,
                    "rating_rank": (
                        str(SCALE.index(normalised) + 1)
                        if normalised in SCALE
                        else ""
                    ),
                    "scale_conformant": conformant,
                    "measurable_indicator": clean(ind),
                    "supporting_evidence": clean(ev),
                    "limitation": clean(lim),
                    "confidence": conf_clean,
                    "component_issues_total": st.get("total", ""),
                    "component_issues_findings": st.get("findings", ""),
                    "component_amendments": st.get("amendments", ""),
                    "component_issues_critical": st.get("CRITICAL", ""),
                    "component_issues_high": st.get("HIGH", ""),
                    "component_issues_moderate": st.get("MODERATE", ""),
                    "component_issues_low": st.get("LOW", ""),
                    "issue_register": "15_ISSUE_REGISTER.csv",
                }
            )

    out = os.path.join(AUDIT, "16_QUALITY_METRICS.csv")
    cols = [
        "component",
        "component_name",
        "report_file",
        "dimension",
        "rating",
        "rating_as_published",
        "rating_normalised",
        "rating_rank",
        "scale_conformant",
        "measurable_indicator",
        "supporting_evidence",
        "limitation",
        "confidence",
        "component_issues_total",
        "component_issues_findings",
        "component_amendments",
        "component_issues_critical",
        "component_issues_high",
        "component_issues_moderate",
        "component_issues_low",
        "issue_register",
    ]
    with open(out, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, quoting=csv.QUOTE_MINIMAL)
        w.writeheader()
        w.writerows(rows)

    # ---- summary -------------------------------------------------------
    print(f"wrote {out}")
    print(f"rows: {len(rows)} ({len(REPORTS)} components)")

    by_comp = {}
    for r in rows:
        by_comp.setdefault(r["component"], []).append(r)

    print("\nper component: dims / rating spread (normalised)")
    order = {"STRONG": 0, "ADEQUATE": 1, "WEAK": 2, "CRITICAL WEAKNESS": 3,
             "NOT EVALUATED": 4, "UNCLASSIFIED": 5}
    tally = {k: 0 for k in SCALE}
    for comp, name, _ in REPORTS:
        rs = by_comp.get(comp, [])
        if not rs:
            continue
        counts = {}
        for r in rs:
            counts[r["rating_normalised"]] = counts.get(r["rating_normalised"], 0) + 1
            if r["rating_normalised"] in tally:
                tally[r["rating_normalised"]] += 1
        spread = ", ".join(
            f"{k} {counts[k]}" for k in sorted(counts, key=lambda x: order.get(x, 9))
        )
        worst = max(rs, key=lambda r: order.get(r["rating_normalised"], 0))
        print(f"  {comp} {len(rs):2d} dims | {spread}")
        print(f"      worst: {worst['dimension']} = {worst['rating_normalised']}")

    print("\nall dimensions by rating (normalised):")
    for k in SCALE:
        print(f"  {k:20s} {tally[k]}")

    print(f"\nscale-conformant rows: "
          f"{sum(1 for r in rows if r['scale_conformant'] == 'yes')} / {len(rows)}")
    for r in rows:
        if r["scale_conformant"] != "yes":
            print(f"  NON-CONFORMANT: {r['component']} / {r['dimension']} = "
                  f"{r['rating_as_published']} -> {r['rating_normalised']}")

    if problems:
        print("\nPROBLEMS:")
        for p in problems:
            print("  ", p)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
