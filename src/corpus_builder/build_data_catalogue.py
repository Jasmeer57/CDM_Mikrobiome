#!/usr/bin/env python3
"""Build a human-microbiome data catalogue seed from the 453-paper v1 corpus.

Maps every paper to the catalogue template's linked tables (
papers / datasets / data_assets / cohorts / samples / assays / findings)
using the v1 record JSONs (Pass-1 regex + qwen enrich) plus
bioproject_data_export.json for verified BioProject dataset metadata.

Conventions (see src/template/data_catalogue/README.md):
- null  = not yet extracted / unknown
- "NOT_REPORTED" = checked-and-absent
- never invent values; carry evidence through where the v1 record has it
- stable IDs: HMPAPER_/HMDATA_/... sequential over the final 453 ordering

Outputs (under --out, default outputs/results/human_microbiome_data_catalogue/):
- human_microbiome_data_catalogue.json   (validates against template schema)
- human_microbiome_data_catalogue.csv.gz (one table per line, gzipped)
- catalogue_manifest.json                (counts + provenance)
"""
import argparse
import csv
import glob
import gzip
import itertools
import json
import logging
import os
import re
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))

VERSION = "1.0.0"

ACCESSION_RE = re.compile(r"\b(PRJ[A-Z]{2}[0-9]+|E-?GA[DS][0-9]+|GSE[0-9]+|S-?RP[0-9]+"
                          r"|[A-Z]{2}PRJ[A-Z]+[0-9]+|EMP[0-9]+|MG-?RAST[0-9]+|qs[last]?\.[0-9]+)\b")
NOT_REPORTED = "NOT_REPORTED"


def now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def norm_str(v):
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


def norm_list(v, cap=30):
    if not v:
        return []
    if isinstance(v, (str, bytes)):
        v = [v]
    out = []
    for x in list(v)[:cap]:
        s = norm_str(x)
        if s:
            out.append(s)
    return out


def accession_repo(acc):
    """Map an accession prefix to repository name; None if unrecognized."""
    a = acc.upper()
    if a.startswith("PRJNA"):
        return "NCBI BioProject (PRJNA)"
    if a.startswith("PRJEB") or a.startswith("ERP"):
        return "ENA BioProject (PRJEB)"
    if a.startswith("PRJDB"):
        return "DDBJ BioProject (PRJDB)"
    if a.startswith("PRJC"):
        return "China National GeneBank (CNGB)"
    if a.startswith("PRJ"):
        return "BioProject (unspecified archive)"
    if a.startswith("GSE"):
        return "NCBI GEO"
    if a.startswith("SRP") or a.startswith("ERP") or a.startswith("DRP"):
        return "NCBI/EBI/DDBJ SRA"
    if a.startswith("MG-RAST") or a.startswith("MGRAST"):
        return "MG-RAST"
    if a.startswith("QIITA") or a.lower().startswith("emp"):
        return "Qiita / EMP"
    return None


def accession_url(acc):
    a = acc.upper()
    if a.startswith("PRJNA"):
        return "https://www.ncbi.nlm.nih.gov/bioproject/" + a
    if a.startswith("PRJEB") or a.startswith("ERP"):
        return "https://www.ebi.ac.uk/ena/browser/view/" + a
    if a.startswith("PRJDB"):
        return "https://ddbj.nig.ac.jp/search/entry/" + a
    if a.startswith("GSE"):
        return "https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=" + a
    if a.startswith("SRP"):
        return "https://trace.ncbi.nlm.nih.gov/Traces/?view=run_study&acc=" + a
    return None


def map_relevance(rec):
    """v1 corpus_classification -> template relevance enum."""
    cc = rec.get("corpus_classification") or {}
    r = (cc.get("microbiome_relevance") or "").lower()
    if r == "yes":
        return "DIRECT"
    if r == "no":
        return "EXCLUDE"
    if r == "unclear":
        return "INDIRECT"
    he = (cc.get("human_evidence") or "").lower()
    if "review" in he:
        return "REVIEW"
    return None


def map_inclusion(rec):
    cc = rec.get("corpus_classification") or {}
    d = (cc.get("inclusion_decision") or "").upper()
    if d in ("INCLUDE", "EXCLUDE", "PENDING"):
        return d
    r = (cc.get("microbiome_relevance") or "").lower()
    if r == "yes":
        return "INCLUDE"
    if r == "no":
        return "EXCLUDE"
    return "PENDING"


def map_direction(f):
    d = norm_str(f.get("direction"))
    if d is None:
        return "NOT_STATED"
    d = d.upper()
    if d in ("INCREASE", "INCREASED", "ENRICHED", "HIGHER"):
        return "INCREASE"
    if d in ("DECREASE", "DECREASED", "DEPLETED", "LOWER"):
        return "DECREASE"
    if d in ("NO_ASSOCIATION", "NONE", "NOT_ASSOCIATED"):
        return "NO_ASSOCIATION"
    if d == "MIXED":
        return "MIXED"
    return "NOT_STATED" if d else "NOT_STATED"


# Citation-boilerplate that survives Pass-1 title extraction (running heads,
# "• JID 2018:XX (XX XXXX) • 1" fragments, spaced-out "M A J O R A R T I C L E"
# banners). Stripped at catalogue-build time so registry identity checks
# compare real titles; residuals are flagged, never guessed at.
_CITE_JUNK_RE = re.compile(
    r"\s*[•▪]\s*[A-Za-z]{2,5}\s*\d{4}:?[Xx]{2}.*$"        # "• JID 2018:XX (XX XXXX) • 1"
    r"|\s*[•▪]\s*\d+\s*$"                                  # trailing "• 1"
    r"|\b(?:MAJOR|BRIEF|ORIGINAL|RESEARCH)\s*ARTICLE\b\s*[:•]?\s*",  # "MAJOR ARTICLE" banners
    )


def _clean_title(t):
    if not t:
        return t, None
    # 1) collapse spaced-out running-head banners: "M A J O R A R T I C L E" -> "MAJOR ARTICLE"
    collapsed = re.sub(r"\b((?:[A-Z]\s){2,}[A-Z])\b",
                       lambda m: re.sub(r"\s+", "", m.group(1)), t)
    # 2) glue artifacts from step 1 ("MAJORARTICLE") -> "MAJOR ARTICLE"
    collapsed = re.sub(r"\b([A-Z]{5,11})(ARTICLE)\b", r"\1 \2", collapsed)
    if collapsed != t:
        t = collapsed
    cleaned = _CITE_JUNK_RE.sub("", t).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    if cleaned and cleaned != collapsed:
        return cleaned, "title_cleaned_citation_boilerplate"
    if not cleaned:
        # title was pure junk — preserve as null, not invented
        return None, "title_was_pure_boilerplate"
    return cleaned, None


def extract_paper(rec, paper_id, src_acc, retrieved_at):
    pub = rec.get("publication") or {}
    cc = rec.get("corpus_classification") or {}
    sm = rec.get("study_metadata") or {}
    completeness = (cc.get("full_text_completeness") or "UNKNOWN").upper()
    if completeness not in ("FULL", "PARTIAL", "ABSTRACT_ONLY", "UNKNOWN"):
        completeness = "UNKNOWN"
    he = (cc.get("human_evidence") or "").lower()
    article_type = norm_str(pub.get("article_type"))
    if "review" in he and not article_type:
        article_type = "review"
    title, title_note = _clean_title(norm_str(pub.get("title")))
    notes = [
        "source_accession=" + src_acc,
        "schema=fixed-by-builder-v1-3layer",
    ]
    if title_note:
        notes.append(title_note)
    return {
        "paper_id": paper_id,
        "doi": norm_str(pub.get("doi")),
        "pmid": norm_str(pub.get("pmid")),
        "pmcid": norm_str(pub.get("pmcid")),
        "title": title,
        "authors": norm_list(pub.get("authors"), 50),
        "journal": norm_str(pub.get("journal")),
        "publication_year": pub.get("publication_year") if isinstance(pub.get("publication_year"), int) else None,
        "article_type": article_type,
        "abstract": norm_str(pub.get("abstract")),
        "keywords": norm_list(pub.get("keywords"), 40),
        "language": norm_str(pub.get("language")) or "en",
        "full_text_source": norm_str(pub.get("source_database")) or os.path.basename(rec.get("source", {}).get("source_txt") or "") or None,
        "full_text_url": norm_str(pub.get("source_url")),
        "full_text_format": "text/plain; extracted",
        "license_name": norm_str(pub.get("license")) or None,
        "license_url": None,
        "retrieved_at": norm_str(pub.get("retrieved_at")) or retrieved_at,
        "primary_research_domain": norm_str(cc.get("study_type")),
        "human_microbiome_relevance": map_relevance(rec),
        "human_study_design": norm_str(sm.get("study_design")),
        "inclusion_decision": map_inclusion(rec),
        "exclusion_reason": None if map_inclusion(rec) != "EXCLUDE" else "rule-based: microbiome_relevance=no",
        "full_text_completeness": completeness,
        "curation_status": "LLM_SEEDED" if cc.get("llm_status") == "completed" else "AUTO_SEEDED",
        "curator_notes": notes,
    }


def extract_accessions(rec, src_acc):
    """Union of LLM-extracted accessions and the known source accession.

    Returns list of dicts: {accession, source: llm|filename, evidence}
    """
    sm = rec.get("study_metadata") or {}
    llm = set()
    for a in norm_list(sm.get("data_accessions"), 20):
        m = ACCESSION_RE.search(a.upper().replace(" ", ""))
        base = (m.group(1) if m else a.upper().replace(" ", "")).strip()
        if m or base.startswith("PRJ"):
            llm.add(base)
    out = []
    if src_acc:
        out.append({"accession": src_acc, "source": "filename"})
    for a in sorted(llm):
        if a != (src_acc or ""):
            out.append({"accession": a, "source": "llm"})
    return out


def extract_datasets(rec, paper_id, src_acc, bpe, ds_counter):
    """One dataset row per BioProject accession; enriched from export when available.

    Returns (datasets, n_assets). Assets are seeded only for accessions present
    in the BioProject export (known title) — otherwise the accession row itself
    carries the available evidence.
    """
    accs = extract_accessions(rec, src_acc)
    datasets = []
    n_assets = 0

    for i, ent in enumerate(accs, 1):
        acc = ent["accession"]
        bp = bpe.get(acc)
        ds = {
            "dataset_id": f"HMDATA_{next(ds_counter):06d}",
            "paper_id": paper_id,
            "dataset_title": norm_str(bp.get("title")) if bp else None,
            "dataset_description": norm_str(bp.get("study_title")) if bp and bp.get("study_title") != bp.get("title") else None,
            "dataset_role": "primary_study_data" if ent["source"] == "filename" and i == 1 else "linked_data",
            "dataset_type": ["16S_amplicon"] if (rec.get("microbiome_metadata") or {}).get("target_gene_or_region") else [],
            "repository_name": accession_repo(acc) or "Unknown repository",
            "repository_accession": [acc],
            "accession_type": "bioproject",
            "dataset_url": accession_url(acc),
            "related_publication_dois": [d for d in [norm_str((rec.get("publication") or {}).get("doi"))] if d],
            "data_availability_status": "PUBLIC" if bp else "UNKNOWN",
            "access_conditions": None,
            "license_or_terms": None,
            "original_or_reused": "ORIGINAL" if ent["source"] == "filename" else "UNKNOWN",
            "data_dictionary_url": None,
            "study_registration": [],
            "evidence_text": None,
            "evidence_location": "full-text; data availability section" if ent["source"] == "llm" else "source file name",
            "verification_status": "VERIFIED_IMPORT" if bp else "UNVERIFIED",
            "last_verified": now_iso() if bp else None,
            "catalogue_notes": [f"accession_source={ent['source']}"],
        }
        datasets.append(ds)
        if bp:
            n_assets += 1  # registry page known — asset row will be filled below
    return datasets, n_assets


def extract_cohort(rec, paper_id, first_ds_id):
    sm = rec.get("study_metadata") or {}
    if not (isinstance(sm, dict) and sm):
        return None
    npart = sm.get("number_of_participants")
    nsamp = sm.get("number_of_samples")
    if npart is None and nsamp is None and not sm.get("population_description"):
        return None
    return {
        "cohort_id": f"HMCOHORT_{paper_id[-6:]}",
        "paper_id": paper_id,
        "dataset_id": first_ds_id,
        "cohort_label": norm_str(sm.get("population_description")) or "study population",
        "cohort_role": "cases_and_controls" if sm.get("control_group") else "single_group",
        "population_description": norm_str(sm.get("population_description")),
        "country_or_region": norm_list(sm.get("country_or_region"), 10),
        "setting": None,
        "recruitment_method": None,
        "participant_count": npart if isinstance(npart, int) else None,
        "sample_count": nsamp if isinstance(nsamp, int) else None,
        "age_group": "UNKNOWN",
        "age_summary": None,
        "sex_or_gender_reporting": None,
        "health_status": "; ".join(norm_list(sm.get("health_conditions"), 10)) or None,
        "inclusion_criteria": [],
        "exclusion_criteria": [],
        "key_covariates": norm_list(sm.get("confounders_reported"), 20),
        "longitudinal": "NOT_APPLICABLE" if "cross-sectional" in str(sm.get("study_design", "")).lower() else "UNCLEAR",
        "timepoints": [],
        "evidence_location": norm_str(sm.get("evidence_location")),
        "notes": [f"control_group={x}" for x in norm_list(sm.get("control_group"), 3)] or [],
    }


def extract_samples(rec, paper_id, first_ds_id, sample_counter):
    mm = rec.get("microbiome_metadata") or {}
    sites = norm_list(mm.get("body_sites"), 15) or ["UNKNOWN"]
    out = []
    for site in sites:
        out.append({
            "sample_group_id": f"HMSAMPLE_{next(sample_counter):06d}",
            "paper_id": paper_id,
            "dataset_id": first_ds_id,
            "cohort_id": f"HMCOHORT_{paper_id[-6:]}",
            "body_site": site.upper(),
            "body_site_original": site,
            "sample_type": (norm_list(mm.get("sample_types"), 1) or ["UNKNOWN"])[0],
            "collection_method": norm_str(mm.get("sample_collection_method") or (mm.get("sample_collection_methods") or [None])[0] if mm.get("sample_collection_methods") else mm.get("sample_collection_method")),
            "collection_timepoint": None,
            "storage_condition": None,
            "preservation_method": norm_str(mm.get("preservation_method")),
            "sample_count": (rec.get("study_metadata") or {}).get("number_of_samples"),
            "sample_processing": None,
            "notes": [],
        })
    return out


def extract_assays(rec, paper_id, first_ds_id):
    mm = rec.get("microbiome_metadata") or {}
    if not isinstance(mm, dict) or not mm:
        return []
    assay_type = (norm_list(mm.get("assay_types"), 1) or ["UNKNOWN"])[0]
    out = [{
        "assay_id": f"HMASSAY_{paper_id[-6:]}",
        "paper_id": paper_id,
        "dataset_id": first_ds_id,
        "assay_type": assay_type,
        "target_gene_or_region": "; ".join(norm_list(mm.get("target_gene_or_region") or mm.get("target_genes_or_regions"), 8)) or None,
        "sequencing_platform": "; ".join(norm_list(mm.get("sequencing_platform") or mm.get("sequencing_platforms"), 8)) or None,
        "library_preparation": norm_str(mm.get("library_preparation")),
        "dna_extraction_method": "; ".join(norm_list(mm.get("dna_extraction_method") or mm.get("dna_extraction_methods"), 8)) or None,
        "primer_or_probe": None,
        "negative_controls": "; ".join(norm_list(mm.get("negative_controls"), 8)) or None,
        "positive_controls": norm_str(mm.get("positive_controls")),
        "contamination_handling": "; ".join(norm_list(mm.get("contamination_handling"), 8)) or None,
        "quality_control": None,
        "bioinformatics_pipeline": "; ".join(norm_list(mm.get("bioinformatics_pipelines"), 8)) or None,
        "software_tools": [],
        "taxonomic_database": "; ".join(norm_list(mm.get("taxonomic_database") or mm.get("taxonomic_databases"), 8)) or None,
        "functional_database": "; ".join(norm_list(mm.get("functional_databases"), 8)) or None,
        "normalization_method": None,
        "statistical_methods": norm_list(mm.get("statistical_methods") or (rec.get("study_metadata") or {}).get("statistical_methods"), 15),
        "evidence_location": None,
        "notes": [],
    }]
    return out


def extract_findings(rec, paper_id, finding_counter):
    out = []
    for f in rec.get("findings") or []:
        q = norm_str(f.get("evidence_text"))
        out.append({
            "finding_id": f"HMFINDING_{next(finding_counter):06d}",
            "paper_id": paper_id,
            "dataset_id": None,
            "cohort_id": f"HMCOHORT_{paper_id[-6:]}",
            "assay_id": f"HMASSAY_{paper_id[-6:]}",
            "finding_domain": norm_str(f.get("finding_type")) or "microbiome_association",
            "finding_text": norm_str(f.get("finding_text")) or norm_str(f.get("taxon_or_function")),
            "taxon_or_feature": norm_str(f.get("taxon_raw") or f.get("taxon_or_function")),
            "taxonomic_rank": norm_str(f.get("taxonomic_rank")) or "UNKNOWN",
            "comparison_or_exposure": norm_str(f.get("exposure_or_comparison")),
            "outcome": norm_str(f.get("outcome")),
            "direction": map_direction(f),
            "effect_measure": norm_str(f.get("effect_measure")),
            "effect_estimate": norm_str(f.get("effect_estimate")),
            "confidence_interval": norm_str(f.get("confidence_interval")),
            "p_value": norm_str(f.get("p_value")),
            "q_value": norm_str(f.get("q_value")),
            "adjusted_covariates": norm_list(f.get("adjusted_covariates"), 15),
            "author_interpretation": None,
            "evidence_text": q,
            "evidence_location": norm_str(f.get("evidence_locator")),
            "extraction_method": norm_str(f.get("extraction_method")),
            "verification_status": "VERIFIED_INLINE" if str(f.get("extraction_method", "")).startswith("ollama") and q else "UNVERIFIED",
            "notes": [],
        })
    return out


def build_assets(datasets, bpe, asset_counter):
    """One asset row per verified dataset: the repository landing page itself.

    Raw per-file assets are NOT catalogued (per README: store URLs/accessions,
    not duplicated raw files). Files deep-listing requires per-repo API calls
    queued for later verification passes.
    """
    out = []
    for ds in datasets:
        acc = (ds["repository_accession"] or [None])[0]
        if not acc or not accession_url(acc):
            continue
        out.append({
            "asset_id": f"HMASSET_{next(asset_counter):06d}",
            "dataset_id": ds["dataset_id"],
            "asset_name": f"{acc} repository record",
            "asset_type": "repository_landing_page",
            "format": "web",
            "description": ds.get("dataset_title"),
            "repository_url": accession_url(acc),
            "accession": acc,
            "file_size_bytes": None,
            "checksum_type": None,
            "checksum": None,
            "access_status": ds.get("data_availability_status") or "UNKNOWN",
            "license_or_terms": ds.get("license_or_terms"),
            "data_dictionary_url": ds.get("data_dictionary_url"),
            "notes": [],
        })
    return out


def llm_status_done(rec):
    cc = rec.get("corpus_classification") or {}
    return cc.get("llm_status") == "completed"


# ── LLM catalogue overlay (outputs/results/human_microbiome_corpus_v1/llm_catalogue) ──
# Merge policy: fill-if-empty from per-paper qwen3.5:4b extractions
# (corpus_builder/catalogue_llm_extract.py). Never clobbers deterministic
# (v1-record) values; every overlay contribution is tagged in the row's
# catalogue_notes/notes for auditability. Overlay rows reuse the same
# counters/ID patterns as deterministic rows, so id_sequence stays gapless and
# id_uniqueness/pattern checks pass. Values needed verbatim-verified evidence
# (findings, no-accession datasets) are already gated in catalogue_llm_extract.


def load_llm_overlay(llm_cat_dir):
    """{paper_id: parsed <pid>_cat.json} for all checkpoints on disk."""
    out = {}
    d = Path(llm_cat_dir)
    if not d or not d.is_dir():
        return out
    for p in sorted(d.glob("*_cat.json")):
        try:
            c = json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
        pid = c.get("paper_id")
        if pid:
            out[pid] = c
    return out


def _evhash(s):
    """Dedup key for findings: 8-char sha of (evidence + taxon/finding text)."""
    import hashlib
    return hashlib.sha1((s or "").encode("utf-8", "replace")).hexdigest()[:8]


PROV_TAG = "llm_catalogue_overlay"

_AVAIL_ENUM = {"PUBLIC", "CONTROLLED", "EMBARGOED", "UPON_REQUEST",
               "NOT_DEPOSITED", "LINK_ONLY", "UNKNOWN"}


def _avail(v):
    """Coerce an LLM availability string to the schema enum (None if unknown)."""
    s = norm_str(v)
    if not s:
        return None
    u = s.upper().replace(" ", "_").replace("-", "_")
    return u if u in _AVAIL_ENUM else "UNKNOWN"


def _fill(target, src, key, notes, src_key=None, coerce=None):
    """Fill-if-empty one field; tag provenance in `notes` when filled.

    `src_key` maps catalogue field names to the overlay extractor's names
    (e.g. dataset_title <- title) when they differ; `coerce` canonicalizes
    enum-ish values (e.g. availability -> schema enum)."""
    cur = target.get(key)
    if cur in (None, "", []):
        v = src.get(src_key or key)
        if isinstance(v, list):
            v = norm_list(v, 20)
        else:
            v = norm_str(v)
            if coerce is not None and v is not None:
                v = coerce(v)
        if v not in (None, "", []):
            target[key] = v
            notes.append(f"{key}<-{PROV_TAG}")


def overlay_datasets(cat, paper_id, ds_counter, datasets, assets, asset_counter, bpe,
                     global_accs=None):
    """Merge overlay datasets for one paper.

    Enforces the catalogue's one-PRJ-per-paper invariant (blocking
    accession_integrity check):
    1. accession matches the paper's existing dataset -> enrich fill-if-empty.
    2. new PRJ accession AND the paper has NO dataset yet -> append one row
       (links an unlinked paper).
    3. new PRJ accession AND the paper already has >=1 dataset -> never
       append; record `additional_accession_reported<-{PROV_TAG}` on the
       paper's primary dataset row instead.
    4. accession already owned by ANOTHER paper -> skip (conflict).
    Accession-less overlay datasets never create rows; their verified evidence
    enriches the primary row (availability etc.). Returns (n_enriched, n_new).
    """
    global_accs = global_accs if global_accs is not None else {}
    n_enriched = n_new = 0
    paper_rows = [ds for ds in datasets if ds.get("paper_id") == paper_id]
    primary = paper_rows[0] if paper_rows else None
    by_acc = {}
    for ds in paper_rows:
        for a in ds.get("repository_accession") or []:
            by_acc[a.upper()] = ds
    # accession-matched entries enrich first (their titles/descriptions are
    # the trustworthy ones); accession-less entries fill remaining gaps after,
    # so a generic no-accession row can't crowd out the accession-matched value
    entries = list(cat.get("datasets") or [])
    matched = [d for d in entries
               if norm_str(d.get("accession"))
               and norm_str(d.get("accession")).upper() in by_acc]
    unmatched = [d for d in entries if d not in matched]
    for d in matched + unmatched:
        acc = norm_str(d.get("accession"))
        acc_u = acc.upper() if acc else None
        ev = norm_str(d.get("evidence_text"))
        if acc_u and acc_u in by_acc:
            target = by_acc[acc_u]
            notes = target.setdefault("catalogue_notes", [])
            _fill(target, d, "dataset_title", notes, src_key="title")
            _fill(target, d, "dataset_description", notes, src_key="description")
            _fill(target, d, "data_availability_status", notes, src_key="availability_status",
                  coerce=_avail)
            _fill(target, d, "access_conditions", notes)
            _fill(target, d, "original_or_reused", notes)
            if ev and not target.get("evidence_text"):
                target["evidence_text"] = ev
                notes.append(f"evidence_text<-{PROV_TAG}")
            n_enriched += 1
            continue
        if not acc_u or not acc_u.startswith("PRJ"):
            # accession-less overlay dataset: still let its verified evidence
            # enrich the paper's primary row fill-if-empty
            if primary is not None:
                notes = primary.setdefault("catalogue_notes", [])
                _fill(primary, d, "dataset_title", notes, src_key="title")
                _fill(primary, d, "dataset_description", notes, src_key="description")
                _fill(primary, d, "data_availability_status", notes,
                      src_key="availability_status", coerce=_avail)
                _fill(primary, d, "access_conditions", notes)
                _fill(primary, d, "original_or_reused", notes)
                if ev and not primary.get("evidence_text"):
                    primary["evidence_text"] = ev
                    notes.append(f"evidence_text<-{PROV_TAG}")
            continue
        # new PRJ accession below here
        if global_accs.get(acc_u) not in (None, paper_id):
            # accession claimed by another paper -> conflict, never write rows
            if primary is not None:
                primary.setdefault("catalogue_notes", []).append(
                    f"accession_conflict<-{PROV_TAG}: {acc}")
            continue
        if primary is not None:
            # paper already linked: note the additional accession, never append
            primary.setdefault("catalogue_notes", []).append(
                f"additional_accession_reported<-{PROV_TAG}: {acc}")
            continue
        # unlinked paper + new PRJ accession -> append the one dataset row
        repo = norm_str(d.get("repository")) or accession_repo(acc) or "Unknown repository"
        new_ds = {
            "dataset_id": f"HMDATA_{next(ds_counter):06d}",
            "paper_id": paper_id,
            "dataset_title": norm_str(d.get("title")),
            "dataset_description": norm_str(d.get("description")),
            "dataset_role": norm_str(d.get("role")) or "linked_data",
            "dataset_type": norm_list(d.get("dataset_type"), 8) or [],
            "repository_name": repo,
            "repository_accession": [acc],
            "accession_type": "bioproject",
            "dataset_url": accession_url(acc),
            "related_publication_dois": [],
            "data_availability_status": _avail(d.get("availability_status")) or "UNKNOWN",
            "access_conditions": norm_str(d.get("access_conditions")),
            "license_or_terms": None,
            "original_or_reused": norm_str(d.get("original_or_reused")) or "UNKNOWN",
            "data_dictionary_url": None,
            "study_registration": [],
            "evidence_text": ev,
            "evidence_location": "data availability statement (LLM-extracted, verbatim-verified)"
                                 if d.get("evidence_verified") else "LLM-extracted (unverified)",
            "verification_status": "VERIFIED_IMPORT" if bpe.get(acc) else "UNVERIFIED",
            "last_verified": now_iso() if bpe.get(acc) else None,
            "catalogue_notes": [f"accession_source={PROV_TAG}"],
        }
        datasets.append(new_ds)
        by_acc[acc_u] = new_ds
        global_accs[acc_u] = paper_id
        primary = new_ds
        assets.extend(build_assets([new_ds], bpe, asset_counter))
        n_new += 1
    return n_enriched, n_new


def _as_int(v):
    """Best-effort int coercion for LLM counts ('85', '85 patients', 85)."""
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, str):
        m = re.search(r"\d+", v.replace(",", ""))
        return int(m.group(0)) if m else None
    return None


def overlay_cohorts(cat, paper_id, first_ds_id, cohorts, cohort_counter):
    """First overlay cohort enriches the paper's deterministic cohort row
    fill-if-empty (or takes the tail-based ID if none exists, so sample/finding
    references resolve); further cohorts are appended with counter-based IDs
    seeded above the paper-tail range to avoid collisions (id_uniqueness)."""
    n_enriched = n_new = 0
    det = next((c for c in reversed(cohorts) if c["paper_id"] == paper_id), None)
    has_paper_cohort = det is not None
    for i, ch in enumerate(cat.get("cohorts") or []):
        if i == 0 and det is not None:
            notes = det.setdefault("notes", [])
            for k in ("population_description", "setting", "recruitment_method",
                      "age_group", "age_summary", "sex_or_gender_reporting",
                      "health_status"):
                _fill(det, ch, k, notes)
            for k in ("country_or_region", "inclusion_criteria", "exclusion_criteria",
                      "timepoints"):
                _fill(det, ch, k, notes)
            pc = _as_int(ch.get("participant_count"))
            if pc is not None and det.get("participant_count") is None:
                det["participant_count"] = pc
                notes.append(f"participant_count<-{PROV_TAG}")
            sc = _as_int(ch.get("sample_count"))
            if sc is not None and det.get("sample_count") is None:
                det["sample_count"] = sc
                notes.append(f"sample_count<-{PROV_TAG}")
            ev = norm_str(ch.get("evidence_text"))
            if ev:
                det["notes"].append(f"cohort_evidence<-{PROV_TAG}: {ev[:300]}")
            n_enriched += 1
            continue
        new_ch = {
            "cohort_id": f"HMCOHORT_{paper_id[-6:]}" if (i == 0 and not has_paper_cohort)
                         else f"HMCOHORT_{next(cohort_counter):06d}",
            "paper_id": paper_id,
            "dataset_id": first_ds_id,
            "cohort_label": norm_str(ch.get("cohort_label")) or "study population",
            "cohort_role": norm_str(ch.get("cohort_role")) or "single_group",
            "population_description": norm_str(ch.get("population_description")),
            "country_or_region": norm_list(ch.get("country_or_region"), 10),
            "setting": norm_str(ch.get("setting")),
            "recruitment_method": norm_str(ch.get("recruitment_method")),
            "participant_count": _as_int(ch.get("participant_count")),
            "sample_count": _as_int(ch.get("sample_count")),
            "age_group": norm_str(ch.get("age_group")),
            "age_summary": norm_str(ch.get("age_summary")),
            "sex_or_gender_reporting": norm_str(ch.get("sex_or_gender_reporting")),
            "health_status": norm_str(ch.get("health_status")),
            "inclusion_criteria": norm_list(ch.get("inclusion_criteria"), 20),
            "exclusion_criteria": norm_list(ch.get("exclusion_criteria"), 20),
            "key_covariates": [],
            "longitudinal": "UNCLEAR",
            "timepoints": norm_list(ch.get("timepoints"), 20),
            "evidence_location": "LLM-extracted, "
                                 + ("verbatim-verified" if ch.get("evidence_verified") else "unverified"),
            "notes": [f"from_{PROV_TAG}"],
        }
        cohorts.append(new_ch)
        n_new += 1
    return n_enriched, n_new


def overlay_samples(cat, paper_id, first_ds_id, samples, sample_counter):
    """Append overlay sample-group rows for body sites/types the deterministic
    pass missed (matched by (body_site, sample_type); existing kept)."""
    have = {((norm_str(s.get("body_site")) or "UNKNOWN").upper(),
             (norm_str(s.get("sample_type")) or "UNKNOWN").upper()) for s in samples
            if s["paper_id"] == paper_id}
    n_new = 0
    for s in cat.get("samples") or []:
        site = norm_str(s.get("body_site")) or "UNKNOWN"
        stype = norm_str(s.get("sample_type")) or "UNKNOWN"
        if (site.upper(), stype.upper()) in have:
            continue
        samples.append({
            "sample_group_id": f"HMSAMPLE_{next(sample_counter):06d}",
            "paper_id": paper_id,
            "dataset_id": first_ds_id,
            "cohort_id": f"HMCOHORT_{paper_id[-6:]}",
            "body_site": site.upper(),
            "body_site_original": site,
            "sample_type": stype,
            "collection_method": norm_str(s.get("collection_method")),
            "collection_timepoint": norm_str(s.get("collection_timepoint")),
            "storage_condition": norm_str(s.get("storage_condition")),
            "preservation_method": None,
            "sample_count": _as_int(s.get("sample_count")),
            "sample_processing": None,
            "notes": [f"from_{PROV_TAG}",
                      f"evidence_verified={bool(s.get('evidence_verified'))}"],
        })
        have.add((site.upper(), stype.upper()))
        n_new += 1
    return n_new


def overlay_assays(cat, paper_id, first_ds_id, assays, assay_counter):
    """First overlay assay enriches the paper's deterministic assay row
    fill-if-empty; overlay rows with a distinct assay_type are appended as
    new rows (matched by assay_type to avoid duplicates)."""
    det = next((a for a in reversed(assays) if a["paper_id"] == paper_id), None)
    n_enriched = n_new = 0
    enriched_det = False
    seen_types = {a.get("assay_type") for a in assays if a["paper_id"] == paper_id}
    for a in cat.get("assays") or []:
        if det is not None and not enriched_det:
            notes = det.setdefault("notes", [])
            for k in ("target_gene_or_region", "sequencing_platform", "library_preparation",
                      "dna_extraction_method", "negative_controls", "bioinformatics_pipeline",
                      "taxonomic_database"):
                _fill(det, a, k, notes)
            det["notes"].append(f"from_{PROV_TAG}")
            enriched_det = True
            n_enriched += 1
        atype = norm_str(a.get("assay_type"))
        if not atype or atype in seen_types:
            continue
        assays.append({
            "assay_id": f"HMASSAY_{next(assay_counter):06d}",
            "paper_id": paper_id,
            "dataset_id": first_ds_id,
            "assay_type": atype,
            "target_gene_or_region": norm_str(a.get("target_gene_or_region")),
            "sequencing_platform": norm_str(a.get("sequencing_platform")),
            "library_preparation": norm_str(a.get("library_preparation")),
            "dna_extraction_method": norm_str(a.get("dna_extraction_method")),
            "primer_or_probe": None,
            "negative_controls": norm_str(a.get("negative_controls")),
            "positive_controls": None,
            "contamination_handling": None,
            "quality_control": None,
            "bioinformatics_pipeline": norm_str(a.get("bioinformatics_pipeline")),
            "software_tools": [],
            "taxonomic_database": norm_str(a.get("taxonomic_database")),
            "functional_database": None,
            "normalization_method": None,
            "statistical_methods": norm_list(a.get("statistical_methods"), 15),
            "evidence_location": "LLM-extracted, "
                                 + ("verbatim-verified" if a.get("evidence_verified") else "unverified"),
            "notes": [f"from_{PROV_TAG}"],
        })
        seen_types.add(atype)
        n_new += 1
    return n_enriched, n_new


def overlay_findings(cat, paper_id, findings, finding_counter, existing_hashes, raw_norm=None):
    """Append overlay findings with verbatim-verified evidence not already
    captured (dedup by evidence+taxon hash vs the paper's existing findings).

    raw_norm: whitespace-normalized lowercased RAW source text. When given,
    evidence is re-verified against it because the extractor verified quotes
    against the *clean* text while catalogue_validation::check_evidence_
    traceability (blocking) checks the *raw* source txt — clean text may
    merge lines/hyphens, so a pass there does not imply a pass here."""
    n_new = n_raw_reject = 0
    for f in cat.get("findings") or []:
        ev = norm_str(f.get("evidence_text"))
        if not f.get("evidence_verified") or not ev:
            continue
        if raw_norm is not None:
            q = re.sub(r"\s+", " ", ev).strip().lower()
            if len(q) < 25 or q[:120] not in raw_norm:
                n_raw_reject += 1
                continue
        h = _evhash(ev + "|" + str(f.get("taxon_or_feature") or f.get("finding_text") or ""))
        if h in existing_hashes:
            continue
        existing_hashes.add(h)
        findings.append({
            "finding_id": f"HMFINDING_{next(finding_counter):06d}",
            "paper_id": paper_id,
            "dataset_id": None,
            "cohort_id": f"HMCOHORT_{paper_id[-6:]}",
            "assay_id": f"HMASSAY_{paper_id[-6:]}",
            "finding_domain": norm_str(f.get("finding_domain")) or "microbiome_association",
            "finding_text": norm_str(f.get("finding_text")),
            "taxon_or_feature": norm_str(f.get("taxon_or_feature")),
            "taxonomic_rank": norm_str(f.get("taxonomic_rank")) or "UNKNOWN",
            "comparison_or_exposure": norm_str(f.get("comparison_or_exposure")),
            "outcome": norm_str(f.get("outcome")),
            "direction": map_direction(f),
            "effect_measure": norm_str(f.get("effect_measure")),
            "effect_estimate": norm_str(f.get("effect_estimate")),
            "confidence_interval": norm_str(f.get("confidence_interval")),
            "p_value": norm_str(f.get("p_value")),
            "q_value": norm_str(f.get("q_value")),
            "adjusted_covariates": norm_list(f.get("adjusted_covariates"), 15),
            "author_interpretation": None,
            "evidence_text": ev,
            "evidence_location": norm_str(f.get("evidence_location")),
            "extraction_method": PROV_TAG,
            "verification_status": "VERIFIED_INLINE",
            "notes": [f"from_{PROV_TAG}"],
        })
        n_new += 1
    return n_new, n_raw_reject


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--v1-dir", default=str(REPO / "outputs/results/human_microbiome_corpus_v1/records"))
    ap.add_argument("--bioproject-export", default=str(REPO / "data" / "bioproject_data_export.json"))
    ap.add_argument("--out", default=str(REPO / "outputs/results/human_microbiome_data_catalogue"))
    ap.add_argument("--llm-cat-dir", default=None,
                    help="dir with LLM catalogue checkpoints (<pid>_cat.json from "
                         "catalogue_llm_extract.py); default: <v1-dir>/../llm_catalogue "
                         "when present, else disabled")
    ap.add_argument("--include-pending-llm", action="store_true",
                    help="also seed from records whose LLM pass hasn't completed (recommended: wait for job)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    v1 = Path(args.v1_dir)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    bpe_raw = json.load(open(args.bioproject_export))
    bpe_raw = bpe_raw.get("bioprojects") if isinstance(bpe_raw, dict) else bpe_raw
    bpe = {x["bioproject_id"]: x for x in bpe_raw if isinstance(x, dict) and x.get("bioproject_id")}
    logging.info("BioProject export: %d entries", len(bpe))

    if not v1.exists():
        raise SystemExit(f"v1 records dir not found: {v1}")
    record_paths = sorted(glob.glob(str(v1 / "*" / "*.json")))
    if not record_paths:
        raise SystemExit("no record json files found under " + str(v1))

    # LLM catalogue overlay: optional checkpoints from catalogue_llm_extract.py.
    # Overlay cohort/assay rows use counter IDs seeded above the paper-tail
    # numeric range (< 461 for 453 papers) to avoid id_uniqueness collisions
    # with deterministic tail-based IDs.
    llm_cat_dir = None
    if args.llm_cat_dir:
        llm_cat_dir = Path(args.llm_cat_dir)
    else:
        cand = (v1.parent / "llm_catalogue") if v1.name == "records" else (v1 / "llm_catalogue")
        if cand.is_dir() and list(cand.glob("*_cat.json")):
            llm_cat_dir = cand
    overlay = load_llm_overlay(llm_cat_dir) if llm_cat_dir else {}
    logging.info("LLM catalogue overlay: %d papers (dir=%s)", len(overlay), llm_cat_dir or "disabled")

    papers, datasets, assets, cohorts, samples, assays, findings = [], [], [], [], [], [], []
    ds_counter = itertools.count(1)
    sample_counter = itertools.count(1)
    asset_counter = itertools.count(1)
    finding_counter = itertools.count(1)
    # overlay-only counters: 6-digit IDs at 100000+, far above paper-tail range
    cohort_counter = itertools.count(100000)
    assay_counter = itertools.count(100000)
    # fill-if-empty determinism guard: overlay rows matching a deterministic
    # row's hash are skipped (also used to dedup overlay findings themselves)
    finding_hashes = set()
    ov_stats = {"ds_enriched": 0, "ds_new": 0, "ds_conflict": 0, "ds_extra_acc": 0,
                "cohort_enriched": 0, "cohort_new": 0,
                "sample_new": 0, "assay_enriched": 0, "assay_new": 0,
                "finding_new": 0, "finding_raw_reject": 0, "papers_with_overlay": 0}
    # seed with ALL deterministic accessions so overlay can never claim an
    # accession another paper already owns (blocking cross_paper_duplicate)
    global_accs = {a.upper(): ds.get("paper_id") for ds in datasets
                   for a in ds.get("repository_accession") or []}
    n_llm_done = 0
    n_unlinked = 0
    built_at = now_iso()
    skipped = 0
    for idx, p in enumerate(record_paths, 1):
        rec = json.load(open(p))
        if not args.include_pending_llm and not llm_status_done(rec):
            skipped += 1
            continue
        if llm_status_done(rec):
            n_llm_done += 1
        src_acc = os.path.basename(rec.get("source", {}).get("source_txt") or "").replace(".txt", "")
        paper_id = f"HMPAPER_{idx:06d}"
        papers.append(extract_paper(rec, paper_id, src_acc, built_at))
        dss, n_a = extract_datasets(rec, paper_id, src_acc, bpe, ds_counter)
        first_ds_id = dss[0]["dataset_id"] if dss else None
        datasets.extend(dss)
        assets.extend(build_assets(dss, bpe, asset_counter))
        if not dss:
            n_unlinked += 1
        ch = extract_cohort(rec, paper_id, first_ds_id)
        if ch:
            cohorts.append(ch)
        samples.extend(extract_samples(rec, paper_id, first_ds_id, sample_counter))
        assays.extend(extract_assays(rec, paper_id, first_ds_id))
        det_findings = extract_findings(rec, paper_id, finding_counter)
        findings.extend(det_findings)

        # LLM catalogue overlay (fill-if-empty / append-only)
        v1_pid = norm_str(rec.get("paper_id"))
        cat = overlay.get(v1_pid)
        if cat:
            raw_norm = None
            src_txt = norm_str(rec.get("source", {}).get("source_txt"))
            if src_txt and os.path.exists(src_txt):
                with open(src_txt, encoding="utf-8", errors="replace") as fh:
                    raw_norm = re.sub(r"\s+", " ", fh.read()).strip().lower()
            for f in det_findings:
                finding_hashes.add(_evhash((f.get("evidence_text") or "") + "|" +
                                            str(f.get("taxon_or_feature") or "")))
            e, n = overlay_datasets(cat, paper_id, ds_counter, datasets, assets, asset_counter,
                                    bpe, global_accs=global_accs)
            ov_stats["ds_enriched"] += e
            ov_stats["ds_new"] += n
            ds_notes = [note for row in datasets if row.get("paper_id") == paper_id
                        for note in row.get("catalogue_notes") or []]
            ov_stats["ds_conflict"] += sum(1 for x in ds_notes
                                            if x.startswith("accession_conflict"))
            ov_stats["ds_extra_acc"] += sum(1 for x in ds_notes
                                             if x.startswith("additional_accession_reported"))
            e, n = overlay_cohorts(cat, paper_id, first_ds_id, cohorts, cohort_counter)
            ov_stats["cohort_enriched"] += e
            ov_stats["cohort_new"] += n
            ov_stats["sample_new"] += overlay_samples(cat, paper_id,
                                                       first_ds_id, samples, sample_counter)
            e, n = overlay_assays(cat, paper_id, first_ds_id, assays, assay_counter)
            ov_stats["assay_enriched"] += e
            ov_stats["assay_new"] += n
            n, r = overlay_findings(cat, paper_id, findings, finding_counter,
                                    finding_hashes, raw_norm=raw_norm)
            ov_stats["finding_new"] += n
            ov_stats["finding_raw_reject"] += r
            ov_stats["papers_with_overlay"] += 1

    if not papers:
        raise SystemExit("No seeded papers — pass --include-pending-llm if the enrichment job is still running.")

    catalogue = {
        "schema_version": "1.0.0",
        "papers": papers, "datasets": datasets, "data_assets": assets,
        "cohorts": cohorts, "samples": samples, "assays": assays, "findings": findings,
    }
    cat_json = out / "human_microbiome_data_catalogue.json"
    with open(cat_json, "w", encoding="utf-8") as fh:
        json.dump(catalogue, fp=fh, indent=1, ensure_ascii=False)

    # CSV bundle: one csv per table + a findings csv for spreadsheet use
    csv_paths = []
    for table in ("papers", "datasets", "data_assets", "cohorts", "samples", "assays", "findings"):
        cf = out / f"{table}.csv"
        csv_paths.append(cf)
        rows = catalogue[table]
        if rows:
            fields = list(rows[0].keys())
            with open(cf, "w", newline="", encoding="utf-8") as fh:
                w = csv.DictWriter(fh, fieldnames=fields)
                w.writeheader()
                w.writerows(rows)
        else:
            cf.touch()

    # gzip bundle of all tables (line-delimited rows per table kept simple: single jsonl.gz)
    jsonl = out / "human_microbiome_data_catalogue.jsonl.gz"
    with gzip.open(jsonl, "wt", encoding="utf-8") as fh:
        for table, rows in catalogue.items():
            for row in rows if isinstance(rows, list) else []:
                fh.write(json.dumps({"table": table, **row}, ensure_ascii=False) + "\n")

    manifest = {
        "built_at": built_at,
        "n_papers": len(papers),
        "n_llm_completed": n_llm_done,
        "n_skipped_pending_llm": skipped,
        "n_unlinked_no_dataset": n_unlinked,
        "n_datasets": len(datasets),
        "n_datasets_verified": sum(1 for d in datasets if d["verification_status"] == "VERIFIED_IMPORT"),
        "n_assets": len(assets),
        "n_cohorts": len(cohorts),
        "n_samples": len(samples),
        "n_assays": len(assays),
        "n_findings": len(findings),
        "n_findings_llm_verified": sum(1 for f in findings if f["verification_status"] == "VERIFIED_INLINE"),
        "bioproject_export_entries": len(bpe),
        "llm_overlay": ov_stats,
        "source_v1_dir": str(v1),
        "template": "src/template/data_catalogue/schema 1.0.0",
    }

    # Reproducibility block: input content hashes + versions, so a rebuild cannot
    # silently mix fresh corpus with stale NER/catalogue artifacts and the release
    # step can cross-check hashes.
    try:
        import subprocess
        git_commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(REPO),
                                    capture_output=True, text=True).stdout.strip() or None
        git_dirty = bool(subprocess.run(["git", "status", "--porcelain"], cwd=str(REPO),
                                        capture_output=True, text=True).stdout.strip())
    except Exception:
        git_commit, git_dirty = None, None
    import catalogue_validation as cv
    manifest["reproducibility"] = {
        "input_manifest": cv.input_manifest(v1, args.bioproject_export),
        "builder_version": VERSION,
        "catalogue_validation_version": cv.__dict__.get("SCHEMA_VERSION", "unknown"),
        "python_version": sys.version.split()[0],
        "git_commit": git_commit,
        "git_dirty": git_dirty,
        "built_at": built_at,
    }
    with open(out / "catalogue_manifest.json", "w") as fh:
        json.dump(manifest, fh, indent=1)

    logging.info("Catalogue: %s", json.dumps(manifest, indent=1))
    logging.info("Wrote %s", cat_json)

    # Embedded validation: structural + traceability audit runs alongside every build.
    try:
        report = cv.run_all_checks(catalogue, v1_dir=v1, bioproject_export=args.bioproject_export)
        audit_path = cv.write_audit_report(report, out)
        blocking = report["blocking_failures"]
        logging.info("Validation: %s (blocking: %s) -> %s",
                     "PASS" if report["overall_pass"] else "FAIL", blocking or "none", audit_path)
        if blocking:
            raise SystemExit(f"catalogue built but FAILED blocking validation: {blocking}")
    except ImportError:
        logging.warning("jsonschema unavailable — skipped embedded validation")


if __name__ == "__main__":
    main()

