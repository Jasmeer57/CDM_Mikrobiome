"""Restore concept labels left empty in the public CDM, from your own licensed vocabulary files.

The public release ships labels only for vocabularies on rights/VOCABULARY_LABEL_ALLOWLIST.csv; for the others
(UMLS, SNOMED CT, MedDRA, LOINC, ...) the concept identifiers are kept and the label is empty. If you hold a licence,
fill them in locally from your own copy. Writes into a copy of the database; the original is not changed.

  UMLS:  --mrconso path/to/MRCONSO.RRF      fills UMLS CUIs (C0000000) with the preferred English name
         (TS=P, STT=PF, ISPREF=Y, LAT=ENG), and source-vocabulary codes (SNOMED CT, MedDRA, LOINC, OMIM, RxNorm, Read,
         NDDF, ...) from their own rows in MRCONSO (SAB + CODE)
  OMOP:  --omop-concept path/to/CONCEPT.csv  fills numeric OMOP concept ids from an Athena download (tab-separated)

    python restore_vocab_labels.py --db microbiome_cdm_v3.0.3_public.db --out restored.db --mrconso MRCONSO.RRF
"""
from __future__ import annotations

import argparse
import csv
import re
import shutil
import sqlite3
import sys

SAB = {"SNOMEDCT": "SNOMEDCT_US", "MEDDRA": "MDR", "LNC": "LNC", "OMIM": "OMIM", "RXNORM": "RXNORM", "RCD": "RCD",
       "NDDF": "NDDF", "NDFRT": "NDFRT", "HP": "HPO", "CSP": "CSP", "SNMI": "SNMI"}


def code_of(cid: str):
    m = re.search(r"purl\.bioontology\.org/ontology/([A-Za-z0-9_\-]+)/([^/#]+)$", cid)
    if m:
        return m.group(1).upper(), m.group(2)
    m = re.search(r"snomed\.info/id/(\d+)$", cid)
    if m:
        return "SNOMEDCT", m.group(1)
    return None, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--mrconso")
    ap.add_argument("--omop-concept")
    a = ap.parse_args()
    shutil.copyfile(a.db, a.out)
    c = sqlite3.connect(a.out)
    empty = c.execute("SELECT rowid, concept_id FROM concept WHERE concept_label IS NULL OR concept_label = ''").fetchall()
    cuis = {cid for _, cid in empty if re.fullmatch(r"C\d{7}", cid)}
    codes = {code_of(cid) for _, cid in empty} - {(None, None)}
    want_sab = {(SAB.get(v, v), k) for v, k in codes}
    names = {}
    if a.mrconso:
        with open(a.mrconso, encoding="utf-8") as fh:
            for line in fh:
                f = line.split("|")
                cui, lat, ts, stt, ispref, sab, code, s = f[0], f[1], f[2], f[4], f[6], f[11], f[13], f[14]
                if lat != "ENG":
                    continue
                if cui in cuis and ts == "P" and stt == "PF" and ispref == "Y":
                    names[cui] = s
                if (sab, code) in want_sab:
                    names.setdefault((sab, code), s)
    omop = {}
    if a.omop_concept:
        csv.field_size_limit(sys.maxsize)
        with open(a.omop_concept, encoding="utf-8") as fh:
            for r in csv.DictReader(fh, delimiter="\t"):
                omop[r["concept_id"]] = r["concept_name"]
    filled = 0
    for rid, cid in empty:
        v, k = code_of(cid)
        lab = names.get(cid) or (names.get((SAB.get(v, v), k)) if v else None) or omop.get(cid)
        if lab:
            c.execute("UPDATE concept SET concept_label = ? WHERE rowid = ?", (lab, rid))
            filled += 1
    c.commit()
    c.close()
    print(f"empty labels {len(empty):,}; filled {filled:,} -> {a.out}")


if __name__ == "__main__":
    main()
