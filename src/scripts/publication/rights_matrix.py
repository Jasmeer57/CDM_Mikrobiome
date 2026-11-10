"""Paper-level rights matrix (read-only): proposed release treatment per paper and per content layer.

Inputs: CDM 3.0.3 paper table (DOI, journal, licence) and outputs/results/catalogue_v3_licences/paper_licences.csv
(licence, OA flag, PMC flag, the quote policy already applied in catalogue 3.1.1). The decisions are a
RULE-BASED PROPOSAL from the stated licence only; they are not a legal determination. Every row carries
`needs_legal_confirmation`.

    python rights_matrix.py [--out paper/publication/rights]
"""
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from collections import Counter
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
CDM = ROOT / "releases/cdm_v3/3.0.3/microbiome_cdm_v3.db"
LIC = ROOT / "outputs/results/catalogue_v3_licences/paper_licences.csv"

# licence -> (full text, verbatim quotations, bibliographic metadata, derived annotations, release decision, legal check)
RULES = {
    "cc by": ("ALLOWED_WITH_ATTRIBUTION", "ALLOWED_WITH_ATTRIBUTION", "ALLOWED", "ALLOWED_WITH_ATTRIBUTION",
              "INCLUDE_TEXT", "no"),
    "cc0": ("ALLOWED", "ALLOWED", "ALLOWED", "ALLOWED", "INCLUDE_TEXT", "no"),
    "cc by-nc": ("ALLOWED_NONCOMMERCIAL_ONLY", "ALLOWED_NONCOMMERCIAL_ONLY", "ALLOWED", "ALLOWED_NONCOMMERCIAL_ONLY",
                 "RESTRICTED_NC_LAYER", "yes: release licence must be NC-compatible"),
    "cc by-nc-sa": ("ALLOWED_NONCOMMERCIAL_SHAREALIKE", "ALLOWED_NONCOMMERCIAL_SHAREALIKE", "ALLOWED",
                    "UNCLEAR_SHAREALIKE", "RESTRICTED_NC_LAYER", "yes: share-alike may bind derived layers"),
    "cc by-nc-nd": ("UNCLEAR_NO_DERIVATIVES", "UNCLEAR", "ALLOWED", "UNCLEAR_NO_DERIVATIVES",
                    "WITHHOLD_TEXT", "yes: is sectioned/re-segmented text a derivative?"),
    "": ("PROHIBITED", "UNCLEAR", "ALLOWED", "LIKELY_ALLOWED", "WITHHOLD_TEXT",
         "yes: quotation exceptions and database rights depend on jurisdiction"),
}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "paper/publication/rights"))
    a = ap.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    lic = {r["paper_id"]: r for r in csv.DictReader(open(LIC, encoding="utf-8"))}
    c = sqlite3.connect(f"file:{CDM}?mode=ro", uri=True)
    rows = []
    for pid, doi, journal, lname, lurl, bp in c.execute(
            "SELECT paper_id, doi, journal, license_name, license_url, bioproject FROM paper ORDER BY paper_id"):
        l = lic.get(pid, {})
        key = (l.get("license") or lname or "").strip().lower()
        ft, q, md, der, dec, legal = RULES.get(key, RULES[""])
        rows.append({
            "paper_id": pid, "bioproject": bp, "doi": doi, "journal": journal or "",
            "publisher": "", "publisher_note": "to confirm (not recorded in the corpus)",
            "doi_prefix": (doi or "").split("/")[0],
            "licence": key or "NONE_FOUND", "licence_url": l.get("license_url") or lurl or "",
            "is_open_access": l.get("is_open_access", ""), "in_pmc": l.get("in_pmc", ""),
            "licence_evidence": (f"Europe PMC / PMC record ({l.get('matched_by')})" if l.get("matched_by") else "no licence found"),
            "full_text_redistribution": ft, "verbatim_quotations": q, "bibliographic_metadata": md,
            "derived_annotations": der,
            "quote_policy_applied_in_catalogue_3_1_1": l.get("quote_policy", ""),
            "proposed_release_decision": dec, "needs_legal_confirmation": legal,
            "rights_reviewer": "", "final_decision": "", "decision_evidence": ""})
    with open(out / "PAPER_RIGHTS_MATRIX.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    s = {"papers": len(rows), "by_licence": dict(Counter(r["licence"] for r in rows).most_common()),
         "by_proposed_decision": dict(Counter(r["proposed_release_decision"] for r in rows).most_common()),
         "needs_legal_confirmation": sum(r["needs_legal_confirmation"] != "no" for r in rows),
         "no_licence_but_in_pmc": sum(r["licence"] == "NONE_FOUND" and r["in_pmc"] == "Y" for r in rows),
         "consistent_with_3_1_1_quote_policy": sum(
             (r["proposed_release_decision"] == "INCLUDE_TEXT") == (r["quote_policy_applied_in_catalogue_3_1_1"] == "KEEP")
             for r in rows)}
    (out / "rights_summary.json").write_text(json.dumps(s, indent=1) + "\n")
    print(json.dumps(s, indent=1))


if __name__ == "__main__":
    raise SystemExit(main())
