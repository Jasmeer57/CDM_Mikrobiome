#!/usr/bin/env python3
"""Classify every issue-register row into an action class and emit the ranked plan.

Purpose
-------
`15_ISSUE_REGISTER.csv` states one `recommended_action` per row but says nothing about
*what kind of work* the action is, or whether it can be done by this audit cycle or needs a
human. This script adds that triage, deterministically and from an explicit table, so the
ranked action plan in `18_RECOMMENDED_ACTIONS.md` is reproducible rather than editorial.

Two independent axes, deliberately not collapsed:

`action_class` — the nature of the *minimum* work the recommended action names
    A_APPLIED   already done by a dated amendment in this audit; no further work
    NONE        the register records that no action is required
    DOC         text only: manuscript wording, README, data dictionary, limitation statement.
                Touches no data, no code, no frozen record.
    ART         an additive artefact: a new file (DDL, manifest, cross-tab, distribution,
                list, prompt dump, filter expression) shipped read-only. Touches no frozen
                record; appends.
    BLD         requires changing a build, re-running a pipeline stage, or emitting a new
                release version. Out of scope for an audit and NOT performed here.
    HUM         requires adjudication, annotation, legal or library review, or independent
                expert judgement. Must not be simulated by this audit or by an LLM.

`human_required` — yes when the resolution path contains a step that only a person can take,
*even if* the row's action_class is DOC or ART (e.g. the artefact is shippable but the
number must not be quoted until a human has spot-checked it).

Neither axis is a severity. Severity stays in the register and is never re-derived here.

Run:  PYTHONPATH= python3 paper/publication/component_quality_audit/diagnostics/cqa_actions.py
"""
from __future__ import annotations

import csv
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
AUDIT = os.path.dirname(HERE)
RESULTS = os.path.join(HERE, "results")

sys.path.insert(0, HERE)
from common import emit  # noqa: E402

# (action_class, human_required) per issue id.
# Every one of the 154 register rows must appear here; the script fails loudly otherwise,
# so a new register row cannot silently escape triage.
PLAN = {
    # ---- A. Literature corpus -------------------------------------------------
    "CQA-A-01": ("DOC", "no"),
    "CQA-A-02": ("DOC", "no"),
    "CQA-A-03": ("DOC", "no"),
    "CQA-A-04": ("DOC", "no"),
    "CQA-A-05": ("DOC", "no"),
    "CQA-A-06": ("DOC", "no"),
    "CQA-A-AMEND-2026-11-05-1": ("A_APPLIED", "no"),
    # ---- B. Entity mention extraction -----------------------------------------
    "CQA-B-01": ("DOC", "no"),
    "CQA-B-02": ("DOC", "no"),
    "CQA-B-03": ("DOC", "no"),
    "CQA-B-04": ("DOC", "no"),
    "CQA-B-05": ("DOC", "no"),
    "CQA-B-06": ("ART", "no"),
    "CQA-B-07": ("DOC", "no"),
    "CQA-B-AMEND-2026-11-05-1": ("A_APPLIED", "no"),
    # ---- C. Canonical terminology ---------------------------------------------
    "CQA-C-01": ("DOC", "no"),
    "CQA-C-02": ("DOC", "no"),
    "CQA-C-03": ("DOC", "no"),
    "CQA-C-04": ("DOC", "no"),
    "CQA-C-05": ("DOC", "no"),
    "CQA-C-06": ("DOC", "no"),
    "CQA-C-07": ("NONE", "no"),
    "CQA-C-08": ("DOC", "no"),
    "CQA-C-09": ("DOC", "no"),
    # ---- D. Vocabulary mappings -----------------------------------------------
    "CQA-D-01": ("DOC", "no"),
    "CQA-D-02": ("DOC", "no"),
    "CQA-D-03": ("ART", "no"),
    "CQA-D-04": ("ART", "no"),
    "CQA-D-05": ("DOC", "no"),
    "CQA-D-06": ("DOC", "no"),
    "CQA-D-07": ("DOC", "no"),
    "CQA-D-08": ("DOC", "no"),
    "CQA-D-09": ("DOC", "no"),
    # ---- E. Definitions -------------------------------------------------------
    "CQA-E-01": ("DOC", "no"),
    "CQA-E-02": ("DOC", "no"),
    "CQA-E-03": ("DOC", "no"),
    "CQA-E-04": ("DOC", "no"),
    "CQA-E-05": ("DOC", "no"),
    "CQA-E-06": ("ART", "no"),
    "CQA-E-07": ("DOC", "no"),
    # ---- F. Catalogue ---------------------------------------------------------
    "CQA-F-01": ("BLD", "no"),
    "CQA-F-02": ("BLD", "no"),
    "CQA-F-03": ("DOC", "no"),
    "CQA-F-04": ("ART", "no"),
    "CQA-F-05": ("ART", "no"),
    "CQA-F-06": ("ART", "no"),
    "CQA-F-07": ("ART", "no"),
    "CQA-F-08": ("DOC", "no"),
    "CQA-F-09": ("DOC", "no"),
    "CQA-F-10": ("ART", "no"),
    "CQA-F-11": ("DOC", "no"),
    "CQA-F-12": ("ART", "no"),
    "CQA-F-13": ("ART", "no"),
    "CQA-F-14": ("DOC", "no"),
    "CQA-F-15": ("DOC", "no"),
    "CQA-F-16": ("DOC", "no"),
    "CQA-F-AMEND-2026-11-05-1": ("A_APPLIED", "no"),
    "CQA-F-AMEND-2026-11-05-2": ("A_APPLIED", "no"),
    # ---- G. Triples and KG ----------------------------------------------------
    "CQA-G-01": ("DOC", "no"),
    "CQA-G-02": ("DOC", "no"),
    "CQA-G-03": ("ART", "no"),
    "CQA-G-04": ("ART", "no"),
    "CQA-G-05": ("DOC", "no"),
    "CQA-G-06": ("DOC", "no"),
    "CQA-G-07": ("ART", "no"),
    "CQA-G-08": ("ART", "no"),
    "CQA-G-09": ("DOC", "no"),
    "CQA-G-10": ("DOC", "no"),
    "CQA-G-11": ("DOC", "no"),
    "CQA-G-12": ("DOC", "no"),
    "CQA-G-13": ("DOC", "no"),
    # ---- H. CDM schema --------------------------------------------------------
    "CQA-H-01": ("ART", "no"),
    "CQA-H-02": ("ART", "no"),
    "CQA-H-03": ("DOC", "no"),
    "CQA-H-04": ("DOC", "no"),
    "CQA-H-05": ("BLD", "no"),
    "CQA-H-06": ("DOC", "no"),
    "CQA-H-07": ("DOC", "no"),
    "CQA-H-08": ("ART", "no"),
    "CQA-H-09": ("ART", "no"),
    "CQA-H-10": ("BLD", "no"),
    # ---- I. NER benchmark -----------------------------------------------------
    "CQA-I-01": ("DOC", "no"),
    "CQA-I-02": ("DOC", "yes"),
    "CQA-I-03": ("ART", "no"),
    "CQA-I-04": ("ART", "no"),
    "CQA-I-05": ("ART", "no"),
    "CQA-I-06": ("A_APPLIED", "no"),
    "CQA-I-07": ("ART", "no"),
    "CQA-I-08": ("DOC", "no"),
    "CQA-I-09": ("BLD", "no"),
    "CQA-I-10": ("DOC", "no"),
    "CQA-I-11": ("BLD", "no"),
    "CQA-I-12": ("ART", "no"),
    "CQA-I-13": ("BLD", "no"),
    "CQA-I-14": ("ART", "no"),
    "CQA-I-15": ("BLD", "no"),
    "CQA-I-16": ("BLD", "no"),
    "CQA-I-17": ("ART", "no"),
    "CQA-I-18": ("ART", "no"),
    "CQA-I-19": ("ART", "no"),
    "CQA-I-20": ("DOC", "no"),
    "CQA-I-AMEND-2026-11-04-1": ("A_APPLIED", "no"),
    "CQA-I-AMEND-2026-11-05-1": ("A_APPLIED", "no"),
    # ---- J. Cleaned layer -----------------------------------------------------
    "CQA-J-01": ("ART", "yes"),
    "CQA-J-02": ("ART", "no"),
    "CQA-J-03": ("ART", "no"),
    "CQA-J-04": ("ART", "no"),
    "CQA-J-05": ("DOC", "no"),
    "CQA-J-06": ("DOC", "no"),
    "CQA-J-07": ("ART", "no"),
    # ---- K. BugSigDB comparison ----------------------------------------------
    "CQA-K-01": ("DOC", "no"),
    "CQA-K-02": ("HUM", "yes"),
    "CQA-K-03": ("HUM", "yes"),
    "CQA-K-04": ("ART", "no"),
    "CQA-K-05": ("ART", "no"),
    "CQA-K-06": ("NONE", "no"),
    "CQA-K-07": ("ART", "no"),
    "CQA-K-08": ("ART", "no"),
    # ---- L. Triple reference --------------------------------------------------
    "CQA-L-01": ("DOC", "no"),
    "CQA-L-02": ("DOC", "no"),
    "CQA-L-03": ("DOC", "no"),
    "CQA-L-04": ("DOC", "no"),
    "CQA-L-05": ("DOC", "no"),
    "CQA-L-06": ("DOC", "no"),
    "CQA-L-07": ("DOC", "no"),
    "CQA-L-08": ("ART", "no"),
    # ---- M. Interoperability --------------------------------------------------
    "CQA-M-01": ("ART", "no"),
    "CQA-M-02": ("ART", "no"),
    "CQA-M-03": ("DOC", "no"),
    "CQA-M-04": ("DOC", "no"),
    "CQA-M-05": ("DOC", "no"),
    "CQA-M-06": ("DOC", "no"),
    "CQA-M-07": ("ART", "no"),
    "CQA-M-08": ("DOC", "no"),
    # ---- N. Rights readiness --------------------------------------------------
    "CQA-N-01": ("HUM", "yes"),
    "CQA-N-02": ("BLD", "no"),
    "CQA-N-03": ("DOC", "no"),
    "CQA-N-04": ("BLD", "no"),
    "CQA-N-05": ("DOC", "no"),
    "CQA-N-06": ("DOC", "no"),
    "CQA-N-07": ("BLD", "no"),
    "CQA-N-08": ("BLD", "no"),
    "CQA-N-09": ("DOC", "no"),
    "CQA-N-10": ("DOC", "yes"),
    "CQA-N-11": ("DOC", "no"),
    "CQA-N-12": ("DOC", "no"),
    "CQA-N-13": ("DOC", "no"),
    "CQA-N-14": ("DOC", "no"),
    "CQA-N-AMEND-2026-11-05-1": ("A_APPLIED", "no"),
    # ---- P. Manuscript claims -------------------------------------------------
    "CQA-P-01": ("ART", "no"),
    "CQA-P-02": ("ART", "no"),
    "CQA-P-03": ("DOC", "no"),
    "CQA-P-04": ("ART", "no"),
    "CQA-P-AMEND-2026-11-05-1": ("A_APPLIED", "no"),
}

# Rows whose recommended action names no artefact but which cannot be discharged by
# wording alone: the claim is only quotable after someone looks. Recorded so the triage
# cannot be read as "everything is a text edit".
DISCLOSURE_NOTE = {
    "CQA-D-01": "disclosure suffices for the blocking claim; re-querying a stratified sample is future work",
    "CQA-F-01": "no documentation fallback resolves the deposit question; only a schema change or a stated export rule does",
    "CQA-H-05": "rename is a next-build change; documenting the population difference is sufficient today",
    "CQA-I-09": "disclosure suffices; the deleted entities are unrecoverable without a rerun",
    "CQA-I-11": "disclosure suffices; the environment is unrecoverable retroactively",
    "CQA-I-13": "disclosure suffices; the pre-fix file is overwritten",
    "CQA-I-15": "disclosure suffices; per-document records do not exist",
    "CQA-I-16": "disclosure suffices; PubTator3 is reference-only regardless",
    "CQA-N-03": "option (b) — correct the README to 59 characters — is a text edit and is sufficient",
    "CQA-N-04": "partial only: the values are unrecoverable from the public bundle",
    "CQA-J-01": "the artefact is shippable now, but 60.7% must not be quoted as fact before a human spot-check",
    "CQA-I-02": "disclosure suffices; the 200-span hand annotation is an option, not a requirement",
}

FIELDS = [
    "rank",
    "band",
    "issue_id",
    "component",
    "component_name",
    "severity",
    "type_class",
    "action_class",
    "human_required",
    "doable_without_touching_frozen_records",
    "title",
    "recommended_action",
    "blocking_status",
    "touches_publication",
    "touches_release",
    "note",
]

BAND_ORDER = {"CRITICAL": 1, "HIGH": 2, "MODERATE": 3, "LOW": 4}
CLASS_ORDER = {"HUM": 0, "BLD": 1, "ART": 2, "DOC": 3, "NONE": 4, "A_APPLIED": 5}


def main() -> int:
    with open(os.path.join(AUDIT, "15_ISSUE_REGISTER.csv"), newline="", encoding="utf-8") as fh:
        reg = list(csv.DictReader(fh))

    missing = [r["issue_id"] for r in reg if r["issue_id"] not in PLAN]
    if missing:
        print("UNCLASSIFIED register rows: %s" % missing, file=sys.stderr)
        return 2
    extra = [k for k in PLAN if k not in {r["issue_id"] for r in reg}]
    if extra:
        print("PLAN ids absent from the register: %s" % extra, file=sys.stderr)
        return 2

    rows = []
    for r in reg:
        cls, hum = PLAN[r["issue_id"]]
        rows.append(
            {
                "issue_id": r["issue_id"],
                "component": r["component"],
                "component_name": r["component_name"],
                "severity": r["severity"],
                "type_class": r["type_class"],
                "action_class": cls,
                "human_required": hum,
                "doable_without_touching_frozen_records": "no" if cls == "BLD" else "yes",
                "title": r["title"],
                "recommended_action": r["recommended_action"],
                "blocking_status": r["blocking_status"],
                "touches_publication": r["touches_publication"],
                "touches_release": r["touches_release"],
                "note": DISCLOSURE_NOTE.get(r["issue_id"], ""),
            }
        )

    # Rank: severity band, then class (human/legal first, because those gate everything a
    # machine can do), then component letter, then register order within the component.
    rows.sort(
        key=lambda r: (
            BAND_ORDER[r["severity"]],
            CLASS_ORDER[r["action_class"]],
            r["component"],
        )
    )
    for i, r in enumerate(rows, 1):
        r["rank"] = i
        r["band"] = r["severity"]

    out_csv = os.path.join(AUDIT, "18_ACTION_PLAN.csv")
    with open(out_csv, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r[k] for k in FIELDS})

    def tally(key):
        d = {}
        for r in rows:
            d.setdefault(r[key], {}).setdefault(r["severity"], 0)
            d[r[key]][r["severity"]] += 1
        return d

    by_class = tally("action_class")
    cross = {
        cls: {sev: by_class[cls].get(sev, 0) for sev in ("CRITICAL", "HIGH", "MODERATE", "LOW")}
        for cls in by_class
    }
    totals = {
        cls: sum(v.values()) for cls, v in cross.items()
    }
    summary = {
        "register_rows": len(reg),
        "plan_rows": len(rows),
        "by_class": cross,
        "totals_by_class": totals,
        "totals_by_severity": {
            sev: sum(1 for r in rows if r["severity"] == sev)
            for sev in ("CRITICAL", "HIGH", "MODERATE", "LOW")
        },
        "human_required": {
            "yes": sum(1 for r in rows if r["human_required"] == "yes"),
            "no": sum(1 for r in rows if r["human_required"] == "no"),
            "ids": [r["issue_id"] for r in rows if r["human_required"] == "yes"],
        },
        "bld_rows": [r["issue_id"] for r in rows if r["action_class"] == "BLD"],
        # Blocking is read literally, per row: the register's own prefix word "blocks".
        # The regime named in the sentence is a *second*, independent reading — most rows
        # say "blocks a <claim>" without naming a regime at all, so a regime count is a
        # lower bound on what is gated, never a total.
        "blocking": {
            "starts_with_blocks": sum(
                1 for r in rows if r["blocking_status"].strip().startswith("blocks")
            ),
            "names_public_release": sum(
                1
                for r in rows
                if r["blocking_status"].strip().startswith("blocks")
                and "release" in r["blocking_status"]
            ),
            "names_submission": sum(
                1
                for r in rows
                if r["blocking_status"].strip().startswith("blocks")
                and "submission" in r["blocking_status"]
            ),
            "names_no_regime": sum(
                1
                for r in rows
                if r["blocking_status"].strip().startswith("blocks")
                and "release" not in r["blocking_status"]
                and "submission" not in r["blocking_status"]
            ),
            "starts_with_neither": sum(
                1 for r in rows if r["blocking_status"].strip().startswith("neither")
            ),
        },
        "notes": DISCLOSURE_NOTE,
        "ranking_rule": (
            "severity band (CRITICAL>HIGH>MODERATE>LOW), then action_class "
            "(HUM>BLD>ART>DOC>NONE>A_APPLIED), then component letter, then register order"
        ),
    }
    emit("cqa_actions", summary)

    print("rows: %d -> %s" % (len(rows), out_csv))
    for cls in sorted(totals, key=lambda c: CLASS_ORDER[c]):
        print("  %-10s %4d  %s" % (cls, totals[cls], cross[cls]))
    print("human_required yes: %d" % summary["human_required"]["yes"])
    print("BLD rows: %d" % len(summary["bld_rows"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
