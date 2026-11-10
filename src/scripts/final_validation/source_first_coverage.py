"""Source-first computational coverage: an independent deterministic extractor vs the catalogue (CDM 3.0.3).

The extractor shares nothing with the model pipelines: fixed regular expressions over every section except
References (cited studies), for three fact types that can be matched without interpretation:
  accessions  project / study level identifiers (BioProject, SRA/ENA/DDBJ study, EGA, MG-RAST, Qiita)
  platforms   sequencing platform families
  regions     16S rRNA variable regions
Per paper the two sets are compared: MATCHED, SOURCE_ONLY (potential catalogue omission), CATALOGUE_ONLY
(catalogue value not found in the text: possibly from the compendium metadata or a normalisation).
This is cross-method agreement on a narrow, regex-matchable subset, not recall.

    python source_first_coverage.py
"""
from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
CDM = ROOT / "releases/cdm_v3/3.0.3/microbiome_cdm_v3.db"
OUT = ROOT / "paper/publication/final_validation/source_first"
SKIP = ("References",)   # Acknowledgements kept: data-availability statements are often parsed into it
ACC = re.compile(r"\b(PRJ(?:NA|EB|DB|DA)\d{3,}|[SED]RP\d{5,}|EGA[SD]\d{8,}|mgp\d{3,})\b")
PLATFORMS = {"MiSeq": r"\bmiseq\b", "HiSeq": r"\bhiseq\b", "NovaSeq": r"\bnovaseq\b", "NextSeq": r"\bnextseq\b",
             "iSeq": r"\biseq\b", "Ion Torrent": r"\bion (torrent|pgm|s5|proton)\b", "PacBio": r"\bpacbio\b|\bpacific biosciences\b",
             "Nanopore": r"\bnanopore\b|\bminion\b|\bpromethion\b|\bgridion\b", "454": r"\b454\b|\bgs flx\b",
             "BGISEQ/DNBSEQ": r"\bbgiseq\b|\bdnbseq\b|\bmgiseq\b"}
REGION = re.compile(r"\bV([1-9])(?:\s*(?:-|–|—|to|and|/)\s*V?([1-9]))?\b")


def regions(text):
    out = set()
    for m in REGION.finditer(text):
        a, b = m.group(1), m.group(2)
        out.add(f"V{a}" if not b else f"V{a}-V{b}")
    return out


def platforms(text):
    t = text.lower()
    return {k for k, p in PLATFORMS.items() if re.search(p, t)}


def main():
    c = sqlite3.connect(f"file:{CDM}?mode=ro", uri=True)
    src = defaultdict(lambda: {"acc": set(), "plat": set(), "reg": set(), "acc_in_refs": set()})
    for pid, stype, txt in c.execute("SELECT paper_id, section_type, section_text_original FROM section"):
        txt = txt or ""
        if stype in SKIP:
            src[pid]["acc_in_refs"] |= set(ACC.findall(txt))
            continue
        src[pid]["acc"] |= set(ACC.findall(txt))
        src[pid]["plat"] |= platforms(txt)
        src[pid]["reg"] |= regions(txt)
    cat = defaultdict(lambda: {"acc": set(), "plat": set(), "reg": set(), "acc_bp_derived": set()})
    for pid, acc, ids, rid, srcs in c.execute("SELECT paper_id, repository_accession, accession_ids, dataset_id, field_sources FROM dataset"):
        found = set(ACC.findall(f"{acc or ''} {ids or ''}"))
        if str(rid).startswith("HMDATA_BP_") or "compendium_projects_csv" in str(srcs):
            cat[pid]["acc_bp_derived"] |= found
        else:
            cat[pid]["acc"] |= found
    for pid, acc, ids in c.execute("SELECT paper_id, accession, accession_ids FROM data_asset"):
        cat[pid]["acc"] |= set(ACC.findall(f"{acc or ''} {ids or ''}"))
    for pid, plat, reg, typ in c.execute("SELECT paper_id, sequencing_platform, target_gene_or_region, assay_type FROM assay"):
        cat[pid]["plat"] |= platforms(f"{plat or ''}")
        cat[pid]["reg"] |= regions(f"{reg or ''}")
    papers = [p for (p,) in c.execute("SELECT paper_id FROM paper ORDER BY paper_id")]
    bp = dict(c.execute("SELECT paper_id, bioproject FROM paper"))
    tot = {k: Counter() for k in ("acc", "plat", "reg")}
    per = []
    for p in papers:
        row = {"paper_id": p}
        for k in tot:
            s, cset = src[p][k], cat[p][k]
            m, so, co = s & cset, s - cset, cset - s
            tot[k]["MATCHED"] += len(m)
            tot[k]["SOURCE_ONLY"] += len(so)
            tot[k]["CATALOGUE_ONLY"] += len(co)
            tot[k]["papers_with_source_facts"] += bool(s)
            tot[k]["papers_source_fully_covered"] += bool(s) and not so
            row[k] = {"matched": sorted(m), "source_only": sorted(so), "catalogue_only": sorted(co)}
        row["own_bioproject_in_text"] = bp.get(p) in src[p]["acc"]
        row["own_bioproject_in_catalogue_extraction"] = bp.get(p) in cat[p]["acc"]
        row["own_bioproject_only_bp_derived"] = bp.get(p) in cat[p]["acc_bp_derived"] and bp.get(p) not in cat[p]["acc"]
        per.append(row)
    s = {"papers": len(papers),
         "accessions": dict(tot["acc"]), "platforms": dict(tot["plat"]), "regions_16S": dict(tot["reg"]),
         "own_bioproject_stated_in_text": sum(r["own_bioproject_in_text"] for r in per),
         "own_bioproject_extracted_from_text_by_catalogue": sum(r["own_bioproject_in_catalogue_extraction"] for r in per),
         "own_bioproject_in_text_but_missed_by_extraction": sum(r["own_bioproject_in_text"] and not r["own_bioproject_in_catalogue_extraction"] for r in per),
         "accessions_only_in_reference_sections": sum(len(src[p]["acc_in_refs"] - src[p]["acc"]) for p in papers)}
    for k, v in (("accessions", tot["acc"]), ("platforms", tot["plat"]), ("regions_16S", tot["reg"])):
        n = v["MATCHED"] + v["SOURCE_ONLY"]
        s[k]["share_of_source_facts_in_catalogue_pct"] = round(100 * v["MATCHED"] / n, 1) if n else None
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "coverage_summary.json").write_text(json.dumps(s, indent=1) + "\n")
    with open(OUT / "coverage_per_paper.jsonl", "w") as fh:
        for r in per:
            fh.write(json.dumps(r) + "\n")
    print(json.dumps(s, indent=1))


if __name__ == "__main__":
    main()
