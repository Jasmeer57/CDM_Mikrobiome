#!/usr/bin/env python
"""Build the HMPAPER human-microbiome full-text corpus per
src/template/human_microbiome_corpus_building_template.md.

Merges five already-existing sources into one traceable corpus:

  1. data/papers_txt/<PRJ>.txt              cleaned full text (the 453-paper corpus set)
  2. paper_claims/corpus/corpus.db      sections, captions, study metadata,
                                        accessions, findings, STORMS
  3. data/168000-samples-paper/projects.csv     study-level: condition, sample type,
                                           subjects, kit, amplicon
  4. data/168000-samples-paper/sample_metadata.tsv  per-project sample counts,
                                           instruments, geography, library strategy
  5. data/168000-samples-paper/fulltext/          retrieved DOI/PMID/PMCID, license,
                                           retrieval date + manifest status

Output (hm_corpus/):
  corpus_tracking.csv            §2  one row per paper, HMPAPER_000001..000453
  records/HMPAPER_000001.json    §3  per-paper record, sections A-I
  annotations/findings.csv       §H  one row per finding
  outputs/logs/curation_log.csv          §5  one row per processing event
  provenance/exclusions.csv      §6  compendium entries not in the corpus, with reasons
  schema/paper_record.schema.json      JSON Schema for the record format
  README.md                      build summary + status distribution

The corpus set is the 453 accessions that have a cleaned text file. Anything in
projects.csv that lacks one is written to provenance/exclusions.csv rather than
silently dropped.

Usage:
    python build_hm_corpus.py
    python build_hm_corpus.py --out hm_corpus
"""
import argparse
import csv
import hashlib
import json
import os
import re
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent
PAPERS_TXT = REPO / "data/papers_txt"
CORPUS_DB = REPO / "paper_claims" / "corpus" / "corpus.db"
ABDILL = REPO / "data/168000-samples-paper"
PROJECTS_CSV = ABDILL / "projects.csv"
SAMPLE_META = ABDILL / "sample_metadata.tsv"
BIOPROJECT_JSON = REPO / "data" / "bioproject_data_export.json"
FULLTEXT_MANIFEST = ABDILL / "fulltext" / "manifest.csv"
FULLTEXT_DIR = ABDILL / "fulltext"
PROTOCOL_VERSION = "1.0.0"
SCHEMA_VERSION = "1.0.0"
CORPUS_VERSION = "1.0.0"
EXTRACTION_TOOL = "Microbiome-CDM corpus pipeline"
EXTRACTION_TOOL_VERSION = "1.0.0"


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


# ── Source loaders ────────────────────────────────────────────────────────

def load_paper_set():
    """The corpus set: accessions with a cleaned text file, sorted for stable IDs."""
    return sorted(p.stem for p in PAPERS_TXT.glob("*.txt"))


def load_projects():
    with PROJECTS_CSV.open(encoding="utf-8-sig") as f:
        return {r["project"].strip(): r for r in csv.DictReader(f) if r.get("project")}


def load_sample_metadata():
    """Aggregate sample_metadata.tsv per project."""
    per = defaultdict(lambda: {"n": 0, "instruments": set(), "geo": set(),
                               "strategy": set(), "pubdates": set(), "sources": set()})
    if not SAMPLE_META.exists():
        return {}
    with SAMPLE_META.open(encoding="utf-8") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            acc = (row.get("project") or "").strip()
            if not acc:
                continue
            p = per[acc]
            p["n"] += 1
            for col, key in (("instrument", "instruments"), ("geo_loc_name", "geo"),
                             ("library_strategy", "strategy"), ("pubdate", "pubdates"),
                             ("library_source", "sources")):
                v = (row.get(col) or "").strip()
                if v:
                    p[key].add(v)
    return {k: {"n_samples": v["n"],
                "instruments": sorted(v["instruments"]),
                "geo_locations": sorted(v["geo"]),
                "library_strategies": sorted(v["strategy"]),
                "publication_dates": sorted(v["pubdates"]),
                "library_sources": sorted(v["sources"])}
            for k, v in per.items()}


def load_bioproject_titles():
    if not BIOPROJECT_JSON.exists():
        return {}
    data = json.loads(BIOPROJECT_JSON.read_text(encoding="utf-8"))
    return {b["bioproject_id"]: b.get("title") or b.get("study_title")
            for b in data.get("bioprojects", [])}


def load_fulltext_manifest():
    if not FULLTEXT_MANIFEST.exists():
        return {}
    with FULLTEXT_MANIFEST.open(encoding="utf-8") as f:
        return {r["project"]: r for r in csv.DictReader(f)}


def load_fulltext_meta(acc):
    p = FULLTEXT_DIR / acc / "meta.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            return {}
    return {}


def parse_jats(acc):
    """Pull abstract and licence out of a retrieved JATS XML file.

    Returns (abstract, license_name, license_url). Any element may be None.
    """
    p = FULLTEXT_DIR / acc / "article.xml"
    if not p.exists():
        return None, None, None
    try:
        import xml.etree.ElementTree as ET
        root = ET.parse(p).getroot()
    except Exception:
        return None, None, None

    def _txt(el):
        return re.sub(r"\s+", " ", "".join(el.itertext())).strip() if el is not None else None

    # abstract — JATS puts it under front/article-meta/abstract
    abstract = None
    for ab in root.iter("abstract"):
        t = _txt(ab)
        if t:
            abstract = t
            break

    # licence — front/article-meta/permissions/license
    lic_name = lic_url = None
    for lic in root.iter("license"):
        t = _txt(lic)
        if t and not lic_name:
            lic_name = t[:200]
        href = lic.get("{http://www.w3.org/1999/xlink}href")
        if href and not lic_url:
            lic_url = href
    return abstract, lic_name, lic_url


# ── DB access ─────────────────────────────────────────────────────────────

class CorpusDB:
    def __init__(self, path):
        self.c = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        self.c.row_factory = sqlite3.Row

    def q(self, sql, *args):
        return [dict(r) for r in self.c.execute(sql, args).fetchall()]

    def one(self, sql, *args):
        r = self.c.execute(sql, args).fetchone()
        return dict(r) if r else {}

    def group(self, sql, *args):
        out = defaultdict(list)
        for r in self.c.execute(sql, args).fetchall():
            out[r[0]].append(dict(r))
        return out


# ── Record assembly ───────────────────────────────────────────────────────

PUB_TYPE_MAP = {
    "primary_research": "primary_research", "primary research": "primary_research",
    "research article": "primary_research", "review": "review",
    "meta-analysis": "meta_analysis", "meta analysis": "meta_analysis",
    "systematic review": "review", "protocol": "protocol",
    "methods": "method", "method": "method", "editorial": "other",
    "letter": "other", "case report": "other",
}


def normalise_pub_type(study_type):
    if not study_type:
        return None
    return PUB_TYPE_MAP.get(study_type.strip().lower(), "other")


def build_record(acc, corpus_id, db, projects, samples, biotitles, ftman, ftmeta):
    """Assemble one §3 paper record."""
    paper = db.one("SELECT * FROM papers WHERE paper_id=?", acc)
    txt_path = PAPERS_TXT / f"{acc}.txt"
    text = txt_path.read_text(encoding="utf-8", errors="replace") if txt_path.exists() else ""
    digest = sha256_of(txt_path) if txt_path.exists() else None

    # Evidence offsets index into the pipeline's cleaned_text, which is NOT the
    # same string as the papers_txt file (that one holds raw_text). The template's
    # evidence-locator rule requires offsets be recoverable from the named text
    # version, so the exact versioned text is written to corpus_build/text/.
    cleaned = paper.get("cleaned_text") or text
    version_rel = f"text/{corpus_id}.txt"
    (OUT_TEXT_DIR / f"{corpus_id}.txt").write_text(cleaned, encoding="utf-8")
    version_sha = hashlib.sha256(cleaned.encode("utf-8")).hexdigest()

    prow = projects.get(acc, {})
    srow = samples.get(acc, {})
    frow = ftman.get(acc, {})
    meta = ftmeta.get(acc, {})
    biotitle = biotitles.get(acc)
    jats_abstract, jats_license, jats_license_url = parse_jats(acc)

    # ── B. Publication metadata ──
    abstract = jats_abstract or meta.get("abstract")
    kw = db.q("SELECT keyword FROM paper_keywords WHERE paper_id=? ORDER BY keyword_order", acc)
    authors = paper.get("authors")

    document = {
        "title": paper.get("title") or meta.get("title") or prow.get("study_title"),
        "doi": paper.get("doi") or frow.get("doi") or meta.get("doi"),
        "pmid": paper.get("pmid") or frow.get("pmid") or meta.get("pmid"),
        "pmcid": paper.get("pmcid") or frow.get("pmcid") or meta.get("pmcid"),
        "authors": authors,
        "journal": paper.get("journal") or meta.get("journal"),
        "publication_year": paper.get("year") or meta.get("year"),
        "publication_type": normalise_pub_type(paper.get("study_type")),
        "language": paper.get("language") or "en",
        "abstract": abstract,
        "keywords": [k["keyword"] for k in kw if k["keyword"]],
        "study_type_reported": paper.get("study_type"),
    }

    # ── C. Source and file provenance ──
    files = {
        "source_text_path": str(txt_path.relative_to(REPO)),
        "source_text_sha256": digest,
        "source_text_bytes": len(text.encode("utf-8")),
        "source_text_words": len(text.split()),
        "text_version_path": version_rel,
        "text_version_sha256": version_sha,
        "text_version_bytes": len(cleaned.encode("utf-8")),
        "original_pdf_path": (str((FULLTEXT_DIR / acc / "article.pdf").relative_to(REPO))
                              if (FULLTEXT_DIR / acc / "article.pdf").exists() else None),
        "original_xml_path": (str((FULLTEXT_DIR / acc / "article.xml").relative_to(REPO))
                              if (FULLTEXT_DIR / acc / "article.xml").exists() else None),
        "supplementary_files": [],
    }

    provenance = {
        "source_database": "PubMed Central / Europe PMC (open access subset)"
                           if frow.get("status") == "fulltext" else "local corpus (papers_txt)",
        "source_url": f"https://doi.org/{document['doi']}" if document["doi"] else None,
        "bioproject_accession": acc,
        "bioproject_title": biotitle,
        "retrieval_date": frow.get("retrieved_at") or None,
        "license_name": paper.get("license_name") or jats_license or meta.get("license") or None,
        "license_url": paper.get("license_url") or jats_license_url or None,
        "reuse_permission_checked": ("yes" if frow.get("is_oa") == "yes"
                                     else ("no" if frow.get("is_oa") == "no" else "unclear")),
        "extraction_tool": EXTRACTION_TOOL,
        "extraction_tool_version": EXTRACTION_TOOL_VERSION,
        "extraction_date": (paper.get("updated_at") or paper.get("created_at")),
        "text_version_id": version_sha[:16],
        "retrieval_status": frow.get("status") or "local_text_only",
        "retrieved_format": frow.get("format") or None,
        "resolved_via": frow.get("resolved_via") or None,
    }

    # ── F. Section inventory ──
    sections = db.q(
        "SELECT id, section_type, heading, char_start, char_end, section_order, "
        "       detection_method FROM sections WHERE paper_id=? ORDER BY section_order",
        acc)
    for i, s in enumerate(sections, 1):
        s["section_id"] = f"sec_{i:03d}"
        s["heading_path"] = s["heading"] or s["section_type"]
        s["checked"] = False
    section_rows = [
        {"section_id": s["section_id"], "heading": s["heading"],
         "heading_path": s["heading_path"], "order": s["section_order"],
         "section_type": s["section_type"],
         "char_start": s["char_start"], "char_end": s["char_end"],
         "detection_method": s["detection_method"]}
        for s in sections
    ]

    captions = db.q(
        "SELECT caption_type, caption_number, caption_text, char_start, char_end "
        "FROM figure_table_captions WHERE paper_id=? ORDER BY id", acc)
    tables = db.q("SELECT table_number, caption, extraction_status FROM tables WHERE paper_id=?",
                  acc)
    refs = db.q("SELECT COUNT(*) AS n FROM paper_references WHERE paper_id=?", acc)[0]["n"]

    full_text = {
        "extraction_format": "plain text (sectioned)",
        "extraction_tool": EXTRACTION_TOOL,
        "extraction_tool_version": EXTRACTION_TOOL_VERSION,
        "char_count": len(cleaned),
        "word_count": len(cleaned.split()),
        "sections": [{"section_id": s["section_id"], "heading": s["heading"],
                      "heading_path": s["heading_path"], "order": s["section_order"],
                      "section_type": s["section_type"],
                      "char_start": s["char_start"], "char_end": s["char_end"],
                      "checked": False}
                     for s in sections],
        "section_inventory": section_rows,
        "tables": [{"table_number": t["table_number"], "caption": t["caption"],
                    "extraction_status": t["extraction_status"]} for t in tables],
        "figures": [{"caption_number": c["caption_number"], "caption": c["caption_text"],
                     "caption_type": c["caption_type"],
                     "char_start": c["char_start"], "char_end": c["char_end"]}
                    for c in captions if c["caption_type"] != "table"],
        "table_captions": [c["caption_text"] for c in captions if c["caption_type"] == "table"],
        "references_retained": refs > 0,
        "reference_count": refs,
    }

    # ── G. Study metadata ──
    conds = db.q("SELECT * FROM study_conditions WHERE paper_id=?", acc)
    orgs = db.q("SELECT * FROM study_organisms WHERE paper_id=?", acc)
    meths = db.q("SELECT * FROM study_methods WHERE paper_id=?", acc)
    accs = db.q("SELECT accession, accession_type, repository FROM data_accessions "
                "WHERE paper_id=?", acc)
    geo = db.q("SELECT * FROM geographic_populations WHERE paper_id=?", acc)
    avail = db.q("SELECT * FROM data_availability WHERE paper_id=?", acc)
    storms = db.one("SELECT * FROM paper_storms WHERE paper_id=?", acc)

    condition_names = sorted({c["condition_name"] for c in conds if c.get("condition_name")})
    organism_names = sorted({o["organism_name"] for o in orgs if o.get("organism_name")})
    method_names = sorted({m["method_name"] for m in meths if m.get("method_name")})
    method_categories = sorted({m["method_category"] for m in meths
                                if m.get("method_category")})

    study_id = f"{corpus_id}_STUDY_001"
    study = {
        "study_id": study_id,
        "study_design": paper.get("study_design") or prow.get("condition"),
        "research_question": None,
        "country_or_region": sorted({g["location"] for g in geo if g["location"]})
                              or srow.get("geo_locations", []),
        "recruitment_setting": None,
        "population_description": paper.get("population") or prow.get("subjects"),
        "number_of_participants_reported": paper.get("sample_size"),
        "number_of_biological_samples_reported": srow.get("n_samples"),
        "number_of_technical_replicates_reported": None,
        "number_of_time_points_reported": None,
        "age_information": None,
        "sex_gender_information_as_reported": None,
        "health_conditions": condition_names
                             or ([prow["condition"]] if prow.get("condition") else []),
        "exposures": condition_names,
        "comparator_control_group": None,
        "eligibility_criteria": None,
        "confounders_reported": None,
        "limitations_reported_by_authors": None,
        "microbiome": {
            "body_sites": sorted({prow["sample_type"]} if prow.get("sample_type") else []),
            "specimen_types": sorted({prow["sample_type"]} if prow.get("sample_type") else []),
            "kingdoms_or_domains": organism_names,
            "assay_type": sorted({prow["amplicon"]} if prow.get("amplicon") else [])
                           or srow.get("library_strategies", []),
            "sequencing_strategy": paper.get("sequencing_strategy")
                                   or (srow.get("library_strategies") or [None])[0],
            "sequencing_platform": srow.get("instruments", [None])[0]
                                   if srow.get("instruments") else None,
            "target_gene_or_region": prow.get("amplicon"),
            "sample_collection_method": None,
            "dna_extraction_method": prow.get("kit") or None,
            "bioinformatics_pipeline": None,
            "taxonomic_database": storms.get("taxonomic_db_version"),
            "statistical_methods": method_names,
            "method_categories": method_categories,
        },
        "laboratory": {
            "bead_beating": prow.get("bead_beating") or None,
            "kit": prow.get("kit") or None,
            "avg_length": prow.get("avg_length") or None,
        },
        "storms": ({k: storms.get(k) for k in (
            "negative_controls", "contamination_handling", "chimera_checking",
            "rarefaction_depth", "multiple_testing_correction", "taxonomic_db_version",
            "qc_filtering_threshold", "alpha_diversity_indices",
            "beta_diversity_indices", "differential_abundance_method")} if storms else {}),
        "data_accessions": [{"accession": a["accession"], "type": a["accession_type"],
                             "repository": a["repository"]} for a in accs],
        "code_data_availability": [{"type": a["availability_type"], "statement": a["statement_text"],
                                    "repository": a["repository_name"],
                                    "url": a["repository_url"]} for a in avail],
        "source_row_notes": prow.get("notes") or None,
    }

    # ── H. Findings ──
    findings = db.q(
        "SELECT * FROM findings WHERE paper_id=? ORDER BY finding_id", acc)
    finding_records = []
    for f in findings:
        fid = f"{corpus_id}_FIND_{f['finding_id']:04d}"
        finding_records.append({
            "finding_id": fid,
            "corpus_id": corpus_id,
            "study_id": study_id,
            "claim_type": f.get("claim_type"),
            "body_site_original_wording": f.get("body_site"),
            "body_site_normalized": f.get("body_site"),
            "population_subgroup": None,
            "exposure_or_comparison": f.get("exposure_or_comparison"),
            "outcome": f.get("outcome"),
            "taxon_original_wording": f.get("taxon_name"),
            "taxon_normalized": f.get("taxon_name"),
            "taxonomic_rank": f.get("taxon_rank"),
            "microbial_function_pathway": f.get("microbial_function"),
            "association_direction": f.get("association_direction"),
            "direction_refers_to": f.get("taxon_name"),
            "effect_measure": f.get("effect_measure"),
            "effect_estimate": f.get("effect_estimate"),
            "p_value": f.get("p_value"),
            "q_value": f.get("q_value"),
            "confidence_interval": f.get("confidence_interval"),
            "adjusted_covariates": json.loads(f["adjusted_covariates"])
                                   if f.get("adjusted_covariates") else [],
            "sample_size": f.get("sample_size"),
            "evidence_text": f.get("evidence_text"),
            "evidence_section_id": f.get("evidence_section_id"),
            "evidence_locator_type": "section" if f.get("evidence_section_id") else None,
            "evidence_char_start": f.get("evidence_char_start"),
            "evidence_char_end": f.get("evidence_char_end"),
            "offset_basis": "absolute character offset into the versioned text "
                            "named in files.text_version_path",
            "evidence_locator_status": f.get("evidence_locator_status"),
            "text_version_path": version_rel,
            "text_version_id": version_sha[:16],
            "extraction_method": "automated",
            "extractor_model_and_version": f.get("extraction_method"),
            "confidence": f.get("confidence"),
            "verification_status": "pending" if not f.get("human_verified") else "verified",
            "reviewer": None,
            "review_date": None,
            "notes": None,
        })

    # ── E. Full-text integrity checks ──
    integrity = {
        "title_matches_source": "not_checked",
        "abstract_matches_source": "not_available" if not abstract else "not_checked",
        "body_text_completeness": "complete" if len(cleaned) > 5000 else (
            "partial" if cleaned else "failed"),
        "section_hierarchy_preserved": "yes" if sections else "no",
        "tables_checked": "no",
        "figure_captions_checked": "no",
        "supplementary_materials_checked": "unavailable",
        "references_retained": "yes" if refs > 0 else "no",
        "known_extraction_problems": None,
    }

    # ── D. Eligibility ──
    eligibility = {
        "human_microbiome_relevance": "yes",
        "inclusion_decision": "include",
        "inclusion_reasons": [
            "human microbiome full-text paper in the Abdill-2025 cited corpus",
            "cleaned full text available",
        ],
        "exclusion_reasons": [],
        "protocol_version_applied": PROTOCOL_VERSION,
        "canonical_record_id": corpus_id,
    }

    # ── A. Record control ──
    control = {
        "corpus_id": corpus_id,
        "bioproject_accession": acc,
        "schema_version": SCHEMA_VERSION,
        "processing_status": paper.get("processing_status") or "text_extracted",
        "full_text_completeness": integrity["body_text_completeness"],
        "annotation_status": ("extracted_unverified" if findings else "not_started"),
        "reviewer": None,
        "review_date": None,
        "curation_notes": None,
    }

    # ── I. Final review checklist ──
    checklist = {
        "bibliographic_identifiers_checked": False,
        "duplicate_status_resolved": False,
        "source_and_license_recorded": bool(provenance["license_name"]),
        "full_text_checked_against_source": False,
        "sections_and_captions_checked": False,
        "participants_distinguished_from_samples": False,
        "reported_vs_missing_distinguished": False,
        "every_finding_has_stable_id_and_study_link": bool(finding_records),
        "evidence_text_and_locator_verified": False,
        "reviewer_and_date_recorded": False,
    }

    return {
        "corpus_id": corpus_id,
        "corpus_version": CORPUS_VERSION,
        "bioproject_accession": acc,
        "A_record_control": control,
        "B_publication_metadata": document,
        "C_source_and_file_provenance": provenance,
        "D_eligibility_and_relevance": eligibility,
        "E_full_text_integrity_checks": integrity,
        "F_full_text_section_inventory": section_rows,
        "G_study_metadata": [study],
        "H_findings": finding_records,
        "I_final_review_checklist": checklist,
        "files": files,
        "full_text_summary": {k: full_text[k] for k in
                              ("char_count", "word_count", "extraction_format")},
        "built_at": now_iso(),
    }


# ── Emit ──────────────────────────────────────────────────────────────────

TRACKING_FIELDS = [
    "corpus_id", "title", "doi", "pmid", "pmcid", "year", "journal",
    "source_file_path", "inclusion_decision", "processing_status",
    "full_text_status", "annotation_status", "retrieval_status",
    "sha256", "n_sections", "n_findings", "n_storms_fields", "reviewer", "notes",
]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="hm_corpus", help="Output directory")
    args = ap.parse_args()
    out = (REPO / args.out).resolve() if not Path(args.out).is_absolute() else Path(args.out)
    (out / "records").mkdir(parents=True, exist_ok=True)
    (out / "annotations").mkdir(parents=True, exist_ok=True)
    (out / "logs").mkdir(parents=True, exist_ok=True)
    (out / "provenance").mkdir(parents=True, exist_ok=True)
    (out / "schema").mkdir(parents=True, exist_ok=True)
    global OUT_TEXT_DIR
    OUT_TEXT_DIR = out / "text"
    OUT_TEXT_DIR.mkdir(parents=True, exist_ok=True)

    accs = load_paper_set()
    print(f"corpus set: {len(accs)} papers")
    id_map = {acc: f"HMPAPER_{i:06d}" for i, acc in enumerate(accs, 1)}

    db = CorpusDB(CORPUS_DB)
    projects = load_projects()
    samples = load_sample_metadata()
    biotitles = load_bioproject_titles()
    ftman = load_fulltext_manifest()

    tracking, curation_log, findings_rows = [], [], []
    for i, acc in enumerate(accs, 1):
        cid = id_map[acc]
        meta = load_fulltext_meta(acc)
        rec = build_record(acc, cid, db, projects, samples, biotitles, ftman, meta)

        (out / "records" / f"{cid}.json").write_text(
            json.dumps(rec, indent=2, ensure_ascii=False), encoding="utf-8")

        frow = ftman.get(acc, {})
        doc = rec["B_publication_metadata"]
        sec = rec["F_full_text_section_inventory"]
        fnd = rec["H_findings"]
        storms = rec["G_study_metadata"][0].get("storms") or {}
        tracking.append({
            "corpus_id": cid,
            "title": (doc["title"] or "")[:300],
            "doi": doc["doi"] or "", "pmid": doc["pmid"] or "", "pmcid": doc["pmcid"] or "",
            "year": doc["publication_year"] or "", "journal": doc["journal"] or "",
            "source_file_path": rec["files"]["source_text_path"],
            "inclusion_decision": "include",
            "processing_status": rec["A_record_control"]["processing_status"],
            "full_text_status": rec["E_full_text_integrity_checks"]["body_text_completeness"],
            "annotation_status": rec["A_record_control"]["annotation_status"],
            "retrieval_status": rec["C_source_and_file_provenance"]["retrieval_status"],
            "sha256": rec["files"]["source_text_sha256"] or "",
            "n_sections": len(sec), "n_findings": len(fnd),
            "n_storms_fields": sum(1 for v in storms.values() if v),
            "reviewer": "", "notes": "",
        })

        for f in fnd:
            findings_rows.append({
                "corpus_id": cid, "bioproject_accession": acc,
                "finding_id": f["finding_id"], "study_id": f["study_id"],
                "claim_type": f["claim_type"],
                "body_site": f["body_site_normalized"] or "",
                "condition_or_exposure": f["exposure_or_comparison"] or "",
                "taxon": f["taxon_original_wording"] or "",
                "taxonomic_rank": f["taxonomic_rank"] or "",
                "association": f["association_direction"] or "",
                "outcome": f["outcome"] or "",
                "effect_measure": f["effect_measure"] or "",
                "effect_estimate": f["effect_estimate"] or "",
                "p_value": f["p_value"] or "", "q_value": f["q_value"] or "",
                "confidence_interval": f["confidence_interval"] or "",
                "sample_size": f["sample_size"] or "",
                "evidence_text": f["evidence_text"] or "",
                "evidence_locator": (f"sec[{f['evidence_char_start']}:{f['evidence_char_end']}]"
                                     if f["evidence_char_start"] is not None else ""),
                "verification_status": f["verification_status"],
                "evidence_locator_status": f.get("evidence_locator_status"),
            })

        curation_log.append({
            "corpus_id": cid, "bioproject_accession": acc,
            "date": rec["built_at"][:10], "stage": "corpus_build",
            "tool_or_person": EXTRACTION_TOOL, "tool_version": EXTRACTION_TOOL_VERSION,
            "action_or_check": "merge_text_metadata_provenance_and_export_record",
            "result": "ok",
            "problem_found": "", "resolution": "",
        })
        if i % 50 == 0 or i == len(accs):
            print(f"  [{i}/{len(accs)}] records written")

    # ── tracking table (§2) ──
    with (out / "corpus_tracking.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=TRACKING_FIELDS)
        w.writeheader()
        w.writerows(tracking)

    # ── findings (§H) ──
    ff = list(findings_rows[0].keys()) if findings_rows else []
    with (out / "annotations" / "findings.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=ff)
        w.writeheader()
        w.writerows(findings_rows)

    # ── curation log (§5) ──
    with (out / "logs" / "curation_log.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(curation_log[0].keys()))
        w.writeheader()
        w.writerows(curation_log)

    # ── ID map ──
    with (out / "id_map.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["corpus_id", "bioproject_accession", "doi", "title"])
        for t in tracking:
            w.writerow([t["corpus_id"], accs[int(t["corpus_id"][8:]) - 1],
                        t["doi"], t["title"]])

    # ── exclusions (§6) ──
    corpus_set = set(accs)
    excl = []
    for acc, prow in sorted(projects.items()):
        if acc in corpus_set:
            continue
        f = ftman.get(acc, {})
        if not (PAPERS_TXT / f"{acc}.txt").exists():
            reason = ("no publication linked to this BioProject "
                      "(unreferenced sequence deposit)" if f.get("status") == "no_publication"
                      else "no full text retrieved")
        else:
            reason = "in corpus"
        excl.append({"bioproject_accession": acc, "inclusion_decision": "exclude",
                     "exclusion_reason": reason, "doi": prow.get("link", ""),
                     "retrieval_status": f.get("status", "not_attempted")})
    # DB papers with no text file at all
    for p in db.q("SELECT paper_id FROM papers"):
        acc = p["paper_id"]
        if acc not in corpus_set and acc not in {e["bioproject_accession"] for e in excl}:
            excl.append({"bioproject_accession": acc, "inclusion_decision": "exclude",
                         "exclusion_reason": "no cleaned text file in papers_txt",
                         "doi": "", "retrieval_status": "not_attempted"})
    with (out / "provenance" / "exclusions.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["bioproject_accession", "inclusion_decision",
                                          "exclusion_reason", "doi", "retrieval_status"])
        w.writeheader()
        w.writerows(excl)

    print(f"\nrecords        : {len(list((out/'records').glob('*.json')))}")
    print(f"tracking rows  : {len(tracking)}")
    print(f"findings rows  : {len(findings_rows)}")
    print(f"exclusions     : {len(excl)}")
    print(f"output         : {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())