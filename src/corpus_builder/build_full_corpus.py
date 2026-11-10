#!/usr/bin/env python3
"""Build the 3-layer human microbiome corpus (v2 architecture) from the
453-record working corpus into outputs/results/human_microbiome_corpus/.

Layer 1 — document/files/full_text (original paper content)
Layer 2 — structured study_metadata[] (what each paper studied)
Layer 3 — findings[] (evidence-backed scientific claims)

Design rules:
  - One JSON record per paper, template-conformant (paper_record.schema.json).
  - Keep layers separate but linked via stable identifiers
    (corpus_id + study_id + finding_id).
  - null = not yet extracted; "not_reported" only where the paper was checked.
  - Never overwrite source data; transform is read-only over v1 records.

Usage:
    python3 build_full_corpus.py [--src ...] [--out ...]
"""

import argparse
import csv
import gzip
import json
import re
import shutil
import time
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent
DEFAULT_SRC = REPO / "outputs/results" / "human_microbiome_corpus_v1"
DEFAULT_OUT = REPO / "outputs/results" / "human_microbiome_corpus"

SCHEMA_VERSION = "2.0.0"

# ─────────────────────────────────────────────────────────────────────────────

def norm_list(v, cap=40):
    """Normalize a list field: drop empties/None, dedupe, cap."""
    if not v:
        return []
    out, seen = [], set()
    for x in v:
        if x is None:
            continue
        s = str(x).strip()
        if s and s.lower() not in seen:
            seen.add(s.lower())
            out.append(s)
    return out[:cap]


def norm_str(v):
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def not_null_num(v):
    """Coerce to int-string if plausible, else pass through, else None."""
    if v is None:
        return None
    s = str(v).strip().replace(",", "")
    if s.isdigit():
        return int(s)
    return str(v).strip() or None


# ───────────────── Layer 1: document / files / full_text ─────────────────────

HEADING_CANON = {
    "introduction": "Introduction", "background": "Introduction",
    "methods": "Methods", "materials and methods": "Methods",
    "methods and materials": "Methods", "materials": "Methods",
    "results": "Results", "discussion": "Discussion",
    "conclusion": "Conclusions", "conclusions": "Conclusions",
    "abstract": "Abstract", "references": "References",
    "acknowledgements": "Other", "acknowledgments": "Other",
    "supplementary material": "Other", "supporting information": "Other",
}
SECTION_NUM = re.compile(r"sec_(\d+)", re.IGNORECASE)


def canon_section(heading):
    if not heading:
        return "Other"
    h = re.sub(r"\s+", " ", str(heading).strip().lower())
    if h in HEADING_CANON:
        return HEADING_CANON[h]
    for k, v in HEADING_CANON.items():
        if h.startswith(k) or k in h:
            return v
    return "Other"


def build_document(rec, out_name):
    pub = rec.get("publication") or {}
    src = rec.get("source") or {}
    qa = rec.get("quality_and_provenance") or {}

    license_name = (pub.get("license") or "unknown").strip() or "unknown"
    ft = rec.get("full_text") or {}
    cc = rec.get("chars", ft.get("character_count", 0))
    # Full text is genuinely available only if text was extracted AND there are
    # real content sections. From v1, sections[] is empty for thin/abstract-only
    # sources, so use section count (not the v1 status flag) as the gate.
    n_sections = len(ft.get("sections") or [])
    full_avail = bool(
        n_sections > 0
        and isinstance(cc, (int, float))
        and cc > 5000
        and qa.get("status") == "text_extracted"
        and not qa.get("needs_ocr")
    )

    return {
        "title": norm_str(pub.get("title")),
        "doi": norm_str(pub.get("doi")),
        "pmid": norm_str(pub.get("pmid")),
        "pmcid": norm_str(pub.get("pmcid")),
        "authors": norm_list(pub.get("authors"), 30),
        "journal": norm_str(pub.get("journal")),
        "publication_year": pub.get("publication_year"),
        "publication_type": norm_str(pub.get("article_type")) or "primary_research",
        "language": norm_str(pub.get("language")) or "en",
        "abstract": norm_str(pub.get("abstract")),
        "keywords": norm_list(pub.get("keywords"), 25),
        "access": {
            "source_database": norm_str(pub.get("source_database")) or "papers_txt (PRJ accession corpus)",
            "source_url": norm_str(pub.get("source_url")),
            "full_text_available": full_avail,
            "license_name": license_name,
            "license_url": None,
            "reuse_permission_verified": False,
            "retrieved_at": norm_str(pub.get("retrieved_at")) or qa.get("extraction_date"),
        },
    }


def build_files(rec, out_root):
    src = rec.get("source") or {}
    ft = rec.get("full_text") or {}
    qa = rec.get("quality_and_provenance") or {}

    def rel_to(p, default=None):
        if not p:
            return default
        try:
            return str(Path(p).resolve().relative_to(REPO))
        except Exception:
            return str(p)

    return {
        "original_xml_path": rel_to(src.get("source_pdf") if src.get("source_pdf") else None),
        "original_pdf_path": rel_to(src.get("source_pdf")),
        "clean_text_path": rel_to(src.get("source_txt") or ft.get("clean_text_path")),
        "supplementary_files": norm_list(ft.get("supplementary_materials"), 10),
        "sha256": rec.get("source_sha256") or qa.get("source_sha256"),
    }


def resolve_text(rec):
    """Load the clean text once (best available source)."""
    ft = rec.get("full_text") or {}
    for key in ("clean_text_path", "original_file"):
        p = ft.get(key)
        if p and Path(p).exists():
            try:
                return Path(p).read_text(errors="ignore")
            except OSError:
                pass
    return None


def build_full_text(rec, text):
    ft = rec.get("full_text") or {}
    qa = rec.get("quality_and_provenance") or {}
    sections = []
    base = text if text is not None else ""
    for s in ft.get("sections") or []:
        sec_text = None
        if base and s.get("start_char") is not None and s.get("end_char") is not None:
            frag = base[s["start_char"]:s["end_char"]]
            sec_text = frag if frag else None
        sections.append({
            "section_id": s.get("section_id"),
            "heading": norm_str(s.get("heading")),
            "heading_path": norm_list(s.get("heading_path"), 6),
            "order": s.get("order"),
            "section_class": canon_section(s.get("heading")),
            "start_char": s.get("start_char"),
            "end_char": s.get("end_char"),
            "text": sec_text,
        })
    tables = []
    for t in ft.get("tables") or []:
        tables.append({
            "table_id": t.get("table_id"),
            "caption": norm_str(t.get("caption")),
            "content_text": norm_str(t.get("content_text") or t.get("text")),
            "footnotes": norm_list(t.get("footnotes"), 10),
        })
    figures = []
    for f in ft.get("figures") or []:
        figures.append({
            "figure_id": f.get("figure_id"),
            "caption": norm_str(f.get("caption")),
            "asset_path": f.get("asset_path"),
        })
    return {
        "extraction_format": "plain_text" if (qa.get("extraction_tool") == "source_txt") else "pdf_text",
        "extraction_tool": norm_str(qa.get("extraction_tool")),
        "extraction_tool_version": norm_str(qa.get("extraction_version")),
        "sections": sections,
        "tables": tables,
        "figures": figures,
        "references": norm_list(ft.get("references"), 200),
    }


# ───────────────── Layer 2: study_metadata[] ─────────────────────────────────

def build_study(rec, text, paper_idx):
    sm = rec.get("study_metadata") or {}
    mm = rec.get("microbiome_metadata") or {}
    ex = rec.get("exposures_and_interventions") or {}
    cc = rec.get("corpus_classification") or {}

    exposures = []
    for key in ("antibiotics", "probiotics", "prebiotics",
                "dietary_exposures", "medications", "other_exposures"):
        exposures.extend(norm_list(ex.get(key), 12))
    fmt = ex.get("microbiota_transplantation")
    if fmt and str(fmt).strip().lower() not in ("no", "false", "none", ""):
        exposures.append(f"FMT: {fmt}")
    exposures = norm_list(exposures, 25)

    return {
        "study_id": "study_001",
        "study_design": norm_str(sm.get("study_design")),
        "research_question": norm_str(sm.get("research_question")),
        "country_or_region": norm_list(sm.get("country_or_region"), 8),
        "population_description": norm_str(sm.get("population_description")),
        "sample_size_reported": norm_str(sm.get("sample_size_reported")),
        "number_of_samples": not_null_num(sm.get("number_of_samples")),
        "number_of_participants": not_null_num(sm.get("number_of_participants")),
        "health_conditions": norm_list(sm.get("health_conditions"), 15),
        "exposures": exposures,
        "control_group": norm_str(sm.get("control_group")),
        "microbiome": {
            "body_sites": norm_list(mm.get("body_sites"), 12),
            "sample_types": norm_list(mm.get("sample_types"), 12),
            "kingdoms_or_domains": norm_list(mm.get("kingdoms_or_domains"), 5),
            "assay_type": norm_list(mm.get("assay_types"), 12),
            "sequencing_strategy": norm_str(mm.get("sequencing_strategy")),
            "sequencing_platform": "; ".join(norm_list(mm.get("sequencing_platforms"), 6)) or None,
            "target_gene_or_region": "; ".join(norm_list(mm.get("target_genes_or_regions"), 6)) or None,
            "sample_collection_method": "; ".join(norm_list(mm.get("sample_collection_methods"), 6)) or None,
            "dna_extraction_method": "; ".join(norm_list(mm.get("dna_extraction_methods"), 6)) or None,
            "bioinformatics_pipeline": "; ".join(norm_list(mm.get("bioinformatics_pipelines"), 8)) or None,
            "taxonomic_database": "; ".join(norm_list(mm.get("taxonomic_databases"), 6)) or None,
            "statistical_methods": norm_list(mm.get("statistical_methods"), 15),
        },
        "data_accessions": norm_list(sm.get("data_accessions"), 15),
        "confounders_reported": norm_list(sm.get("confounders_reported"), 15),
        "limitations_reported": norm_list(sm.get("limitations_reported"), 15),
    }


# ───────────────── Layer 3: findings[] ───────────────────────────────────────

P_VALUE = re.compile(r"\b(?:p\s*[=<]\s*([\d.]+)|p\s*=\s*NS|not\s+significant|n\.s\.?)\b", re.IGNORECASE)

def build_findings(rec, text, sections_by_id):
    out = []
    for i, f in enumerate(rec.get("findings") or [], 1):
        loc = f.get("evidence_locator")
        sec = sections_by_id.get(loc) if isinstance(loc, str) else None
        ev = f.get("evidence_text")
        pv = f.get("p_value")
        if (pv is None or str(pv).strip() == "") and ev:
            m = P_VALUE.search(str(ev))
            if m:
                pv = m.group(0).strip()
        out.append({
            "finding_id": f"{rec['paper_id']}_F{i:03d}",
            "study_id": "study_001",
            "finding_text": norm_str(f.get("finding_text")),
            "body_site": norm_str(f.get("body_site")),
            "exposure_or_comparison": norm_str(f.get("exposure_or_comparison")),
            "outcome": norm_str(f.get("outcome")),
            "taxon_name": norm_str(f.get("taxon_raw") or f.get("taxon_or_function")),
            "taxonomic_rank": norm_str(f.get("taxonomic_rank")) or (
                "species" if (f.get("taxon_raw") or "").count(" ") == 1 else
                "genus" if f.get("taxon_raw") else None),
            "microbial_function": norm_str(f.get("microbial_function")),
            "association_direction": norm_str(f.get("direction") or f.get("association_direction")),
            "effect_measure": norm_str(f.get("effect_measure")),
            "effect_estimate": norm_str(f.get("effect_estimate")),
            "p_value": norm_str(pv),
            "q_value": norm_str(f.get("q_value")),
            "confidence_interval": norm_str(f.get("confidence_interval")),
            "adjusted_covariates": norm_list(f.get("adjusted_covariates"), 10),
            "evidence_text": norm_str(ev) or "not_reported",
            "evidence_section_id": sec.get("section_id") if sec else norm_str(loc),
            "evidence_locator": (f"{sec.get('section_class', 'unknown')}"
                                 f"(chars {sec.get('start_char','?')}-{sec.get('end_char','?')})") if sec
                                else norm_str(loc),
            "evidence_source_models": norm_list(f.get("source_models"), 8),
            "extraction_method": norm_str(f.get("extraction_method")),
            "confidence": norm_str(f.get("confidence")),
            "human_verified": bool(f.get("human_verified")),
        })
    return out


# ───────────────── curation block ─────────────────────────────────────────────

def build_curation(rec):
    cc = rec.get("corpus_classification") or {}
    qa = rec.get("quality_and_provenance") or {}
    notes = []
    if cc.get("rule_based"):
        notes.append(f"rule_based classification: {json.dumps(cc['rule_based'])}")
    er = rec.get("extraction_rules")
    if er:
        filled = er.get("fields_filled") or {}
        notes.append(f"regex extractor filled {sum(v if isinstance(v,int) else 1 for v in filled.values())} fields")
    return {
        "human_microbiome_relevance": norm_str(cc.get("microbiome_relevance")) or "pending",
        "inclusion_decision": norm_str(cc.get("inclusion_decision")) or "pending",
        "inclusion_reason": norm_list(cc.get("inclusion_reason"), 5),
        "exclusion_reason": norm_list(cc.get("exclusion_reason"), 5),
        "full_text_completeness": norm_str(qa.get("full_text_completeness")) or "pending",
        "tables_checked": bool(qa.get("tables_reviewed")),
        "supplements_checked": bool(qa.get("supplements_reviewed")),
        "annotation_status": ("in_progress" if rec.get("evidence_links") else "not_started"),
        "curation_notes": notes,
    }


# ───────────────── NER evidence links (append-only view) ─────────────────────

def build_evidence_links(rec):
    out = []
    for e in rec.get("evidence_links") or []:
        out.append({
            "term": norm_str(e.get("term")),
            "entity_type": norm_str(e.get("entity_type")),
            "umls_id": norm_str(e.get("umls_id")),
            "section_id": norm_str(e.get("section_id")),
            "evidence_locator": norm_str(e.get("evidence_locator")),
            "source_model": norm_str(e.get("source_model")),
        })
    return out


# ───────────────── main ───────────────────────────────────────────────────────

def write_csv(path, rows):
    if not rows:
        path.write_text("")
        return
    keys = []
    seen = set()
    for r in rows:
        for k in r:
            if k not in seen:
                seen.add(k)
                keys.append(k)
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=str(DEFAULT_SRC))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args()
    src = Path(args.src)
    out = Path(args.out)

    recpaths = sorted(src.glob("records/*/*.json"))
    print(f"Transforming {len(recpaths)} records -> {out}")

    for sub in ("records", "schema", "annotations", "logs",
                "processed/clean_text", "processed/tables", "processed/chunks",
                "raw/jats_xml", "raw/pdf", "raw/supplementary"):
        (out / sub).mkdir(parents=True, exist_ok=True)

    # stable corpus ids: HMPAPER_000001... sorted by BioProject accession
    def acc_of(p):
        return p.parent.name + "/" + p.stem
    ordered = sorted(recpaths)
    corpus_ids = {p: f"HMPAPER_{i:06d}" for i, p in enumerate(ordered, 1)}

    t0 = time.time()
    stats = Counter()
    manifest_rows, study_rows, finding_rows, curation_rows = [], [], [], []
    retrieval_rows, extraction_rows = [], []

    for p in ordered:
        rec = json.loads(p.read_text())
        cid = corpus_ids[p]
        text = resolve_text(rec)

        doc = build_document(rec, cid)
        files = build_files(rec, out)
        full_text = build_full_text(rec, text)
        sections_by_id = {s.get("section_id"): s for s in full_text["sections"]}
        studies = [build_study(rec, text, cid)]
        findings = build_findings(rec, text, sections_by_id)
        curation = build_curation(rec)
        evidence = build_evidence_links(rec)

        record = {
            "corpus_id": cid,
            "schema_version": SCHEMA_VERSION,
            "legacy_paper_id": rec.get("paper_id"),
            "bioproject_accession": Path(rec.get("source", {}).get("relative_path") or "").stem,
            "document": doc,
            "files": files,
            "full_text": full_text,
            "study_metadata": studies,
            "findings": findings,
            "evidence_links": evidence,
            "curation": curation,
        }
        (out / "records" / f"{cid}.json").write_text(json.dumps(record, indent=2))
        stats["records"] += 1
        stats["findings"] += len(findings)
        stats["sections"] += len(full_text["sections"])
        stats["ner_links"] += len(evidence)

        pub = rec.get("publication") or {}
        sm = studies[0]
        manifest_rows.append({
            "corpus_id": cid,
            "legacy_paper_id": rec.get("paper_id"),
            "bioproject_accession": record["bioproject_accession"],
            "title": doc["title"],
            "publication_year": doc["publication_year"],
            "doi": doc["doi"],
            "pmid": doc["pmid"],
            "journal": doc["journal"],
            "full_text_available": doc["access"]["full_text_available"],
            "license_name": doc["access"]["license_name"],
            "human_microbiome_relevance": curation["human_microbiome_relevance"],
            "inclusion_decision": curation["inclusion_decision"],
            "full_text_completeness": curation["full_text_completeness"],
            "annotation_status": curation["annotation_status"],
            "n_sections": len(full_text["sections"]),
            "n_tables": len(full_text["tables"]),
            "n_figures": len(full_text["figures"]),
            "n_findings": len(findings),
            "n_ner_links": len(evidence),
            "processing_status": (rec.get("quality_and_provenance") or {}).get("status"),
        })
        study_rows.append({"corpus_id": cid, **sm, "microbiome": json.dumps(sm["microbiome"])})
        for f in findings:
            finding_rows.append({"corpus_id": cid, **f})
        curation_rows.append({
            "corpus_id": cid,
            **{k: v for k, v in curation.items() if k != "curation_notes"},
            "curation_notes": " | ".join(curation["curation_notes"]),
        })
        extraction_rows.append({
            "corpus_id": cid,
            "extraction_tool": full_text["extraction_tool"],
            "extraction_tool_version": full_text["extraction_tool_version"],
            "n_sections": len(full_text["sections"]),
            "n_findings": len(findings),
            "processed_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
        })

    # consolidated CSVs
    write_csv(out / "corpus_manifest.csv", manifest_rows)
    write_csv(out / "annotations" / "study_metadata.csv", study_rows)
    write_csv(out / "annotations" / "findings.csv", finding_rows)
    write_csv(out / "annotations" / "curation_log.csv", curation_rows)
    write_csv(out / "logs" / "extraction_log.csv", extraction_rows)

    # schema copy (paper_record.schema.json) — written separately by schema writer
    summary = {
        "schema_version": SCHEMA_VERSION,
        "total_records": stats["records"],
        "total_findings": stats["findings"],
        "total_sections": stats["sections"],
        "total_ner_links": stats["ner_links"],
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
        "source": str(src),
        "layers": {
            "layer1_documents": stats["records"],
            "layer2_studies": stats["records"],
            "layer3_findings": stats["findings"],
        },
    }
    (out / "corpus_summary.json").write_text(json.dumps(summary, indent=2))
    with gzip.open(out / "papers.jsonl.gz", "wt") as jf:
        for p in ordered:
            rec = json.loads(p.read_text())
            cid = corpus_ids[p]
            jf.write(json.dumps({
                "corpus_id": cid,
                "paper_id": rec.get("paper_id"),
                "bioproject_accession": Path(rec.get("source", {}).get("source_txt") or "x").stem,
                "title": (rec.get("publication") or {}).get("title"),
                "publication_year": (rec.get("publication") or {}).get("publication_year"),
                "abstract": (rec.get("publication") or {}).get("abstract"),
            }) + "\n")

    print(f"Done in {time.time()-t0:.0f}s")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
