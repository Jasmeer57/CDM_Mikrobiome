#!/usr/bin/env python3
"""Stage 51: build one fully populated Study record (template §3G) per paper.

Every §3G field is always present in the output. Values come from three
sources, applied with deterministic precedence (conflicts recorded, never
silently discarded):

1. DETERMINISTIC facts from the compendium bundle `168000-samples-paper/`
   (joined by exact BioProject accession via the stage-21 link):
   projects.csv (sample_type, condition, subjects, kit, bead_beating),
   sample_metadata.tsv (n_samples, instruments, library strategy, geo loc,
   ISO country, pubdate range) and fulltext/<PRJ>/meta.json.
2. LLM READING of the paper's own Methods/Abstract text for the narrative
   fields (design, population, criteria, statistics, ...).
3. Stage-50 terminology as a secondary cross-source (body sites, platforms,
   statistics methods) - used only to fill fields still empty after 1-2;
   disagreements are recorded in study_provenance.conflicts.

A field no source reports becomes the literal "not_reported" - never blank.
Fail-closed per paper: extraction_status COMPLETE/PARTIAL/FAILED.

Outputs
  data/studies.jsonl                  one study record per paper
  validation/studies_report.json
"""
import csv
import json
import os
import sys
import threading
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import pipeline.common as C
import pipeline.llmio

STAGE = "stage51_studies_extract"
PV = "2.1.0"
NOT_REPORTED = "not_reported"

# Template §3G: 17 study-metadata fields + 20 sampling/lab fields (37 total).
STUDY_FIELDS = [
    "study_design", "research_question", "country_region", "recruitment_setting",
    "population_description", "num_participants_reported",
    "num_biological_samples_reported", "num_technical_replicates_reported",
    "num_time_points_reported", "age_information", "sex_gender_information",
    "health_conditions", "exposures_interventions", "comparator_control_group",
    "eligibility_criteria", "confounders_covariates_reported",
    "limitations_reported",
]
LAB_FIELDS = [
    "body_sites", "specimen_types", "collection_method", "collection_time_points",
    "storage_transport_conditions", "dna_rna_extraction_method", "assay_type",
    "assay_type_evidence", "sequencing_platform", "target_gene_region",
    "negative_positive_controls", "contamination_handling",
    "taxonomic_profiling_method", "taxonomic_database_and_version",
    "functional_profiling_method", "quality_filtering_normalization",
    "statistical_methods", "multiple_testing_correction",
    "software_pipeline_version", "data_accessions", "code_data_availability",
]

ASSAY_TYPES = {"16S": "16S", "shotgun_metagenomics": "shotgun_metagenomics",
              "metatranscriptomics": "metatranscriptomics", "metabolomics": "metabolomics",
              "culture": "culture", "other": "other"}
# SRA library strategy -> template assay type
LIBSTRATEGY_TO_ASSAY = {"AMPLICON": "16S", "WGS": "shotgun_metagenomics",
                       "RNA-SEQ": "metatranscriptomics", "METATRANSCRIPTOME": "metatranscriptomics",
                       "METAGENOME": "shotgun_metagenomics", "OTHER": "other"}

STUDY_PROMPT = """You extract structured STUDY metadata from a scientific paper for a human-microbiome corpus.
Fill every field. If the text does not state a field, use exactly the string "not_reported" - never guess, never leave blank, never infer from outside knowledge. Copy exact wording from the text where possible (short phrases, do not paraphrase numbers).
Only use the text provided.

Return STRICT JSON (no markdown, no commentary) with exactly these keys:
{{
  "study_design": "study types, e.g. cross-sectional / longitudinal / case-control / RCT / animal model",
  "research_question": "main question or objective in one sentence",
  "country_region": "country/region participants or samples come from",
  "recruitment_setting": "where participants were recruited or samples sourced",
  "population_description": "cohort description: healthy/disease, age, sex, group sizes",
  "num_participants_reported": "participants/subjects as stated (a number plus wording, or not_reported)",
  "num_technical_replicates_reported": "technical replicates as stated",
  "num_time_points_reported": "time points as stated",
  "age_information": "age of participants as reported",
  "sex_gender_information": "sex/gender distribution as reported",
  "health_conditions": "health conditions/diseases studied",
  "exposures_interventions": "exposures or interventions studied (diet, drugs, FMT...)",
  "comparator_control_group": "control/comparison group description",
  "eligibility_criteria": "inclusion/exclusion criteria as stated",
  "confounders_covariates_reported": "covariates adjusted for, as stated",
  "limitations_reported": "limitations the authors state",
  "body_sites": "body site(s) sampled (gut, oral, skin, vaginal...)",
  "specimen_types": "specimen type(s): stool/feces, saliva, swab, biopsy...",
  "collection_method": "how samples were collected",
  "collection_time_points": "when samples were collected",
  "storage_transport_conditions": "storage/transport conditions as stated",
  "dna_rna_extraction_method": "DNA/RNA extraction kit or protocol",
  "assay_type": "exactly one of: 16S | shotgun_metagenomics | metatranscriptomics | metabolomics | culture | other",
  "assay_type_evidence": "short quote supporting assay_type",
  "sequencing_platform": "sequencing instrument(s)",
  "target_gene_region": "targeted 16S region, or not_reported for shotgun",
  "negative_positive_controls": "negative/positive controls mentioned",
  "contamination_handling": "contamination detection/removal methods",
  "taxonomic_profiling_method": "taxonomic profiling method e.g. QIIME2, MetaPhlAn",
  "taxonomic_database_and_version": "database as stated e.g. SILVA 138, Greengenes 2022.10",
  "functional_profiling_method": "functional profiling e.g. PICRUSt2, HUMAnN",
  "quality_filtering_normalization": "QC filtering/normalization steps",
  "statistical_methods": "statistical tests and models used",
  "multiple_testing_correction": "multiple-testing correction as stated",
  "software_pipeline_version": "software/pipelines and versions",
  "code_data_availability": "where data/code are available as stated"
}}

Text from the paper "{title}":
{chunk}"""


def load_projects_csv(prjs):
    path = C.REPO_ROOT / "data/168000-samples-paper" / "projects.csv"
    facts = {}
    if not path.exists():
        return facts
    with open(path, encoding="utf-8-sig", errors="replace") as fh:
        for row in csv.DictReader(fh):
            prj = (row.get("project") or "").strip()
            if prj in prjs:
                facts[prj] = row
    return facts


def load_sample_stats(prjs):
    path = C.REPO_ROOT / "data/168000-samples-paper" / "sample_metadata.tsv"
    stats = {p: {"n_samples": 0, "instruments": set(), "geo": set(),
                 "library_strategy": set(), "country_iso": set(),
                 "pubdate_min": None, "pubdate_max": None} for p in prjs}
    if not path.exists():
        return stats
    with open(path, encoding="utf-8", errors="replace") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            prj = (row.get("project") or "").strip()
            if prj not in stats:
                continue
            st = stats[prj]
            st["n_samples"] += 1
            for src, dst in (("instrument", "instruments"), ("geo_loc_name", "geo"),
                             ("library_strategy", "library_strategy")):
                v = (row.get(src) or "").strip()
                if v:
                    st[dst].add(v)
            v = (row.get("iso") or "").strip()
            if v:
                st["country_iso"].add(v)
            pd = (row.get("pubdate") or "")[:10]
            if pd and pd >= "1990-01-01":
                st["pubdate_min"] = pd if st["pubdate_min"] is None or pd < st["pubdate_min"] else st["pubdate_min"]
                st["pubdate_max"] = pd if st["pubdate_max"] is None or pd > st["pubdate_max"] else st["pubdate_max"]
    return stats


def load_bundle_meta(prjs):
    out = {}
    base = C.REPO_ROOT / "data/168000-samples-paper" / "fulltext"
    for prj in prjs:
        p = base / prj / "meta.json"
        if p.exists():
            try:
                out[prj] = json.loads(p.read_text(encoding="utf-8", errors="replace"))
            except Exception:
                pass
    return out


def load_terms_by_paper():
    terms = defaultdict(lambda: defaultdict(set))
    fp = C.CORPUS_DIR / "data" / "llm_terms.jsonl"
    if not fp.exists():
        return terms
    for r in C.read_jsonl(fp):
        for t in (r.get("llm_terms") or []):
            ty = (t.get("type") or "").strip()
            raw = (t.get("term") or "").strip()
            if ty and raw:
                terms[r["paper_id"]][ty].add(raw)
    return terms


def norm(t):
    return C.normalize_title(str(t or ""))


def clean_str(v):
    """None-safe string trim; collapses whitespace."""
    if v is None:
        return ""
    return " ".join(str(v).split())


def set_field(rec, prov, conflicts, field, llm_val, det_val=None, det_source=None,
              det_method="deterministic"):
    """Precedence: deterministic > LLM. Value never blank (not_reported fallback).
    Both present and different -> keep deterministic, record the conflict."""
    lv = clean_str(llm_val)
    dv = clean_str(det_val) if det_val is not None else ""
    lv_ok = bool(lv) and lv.lower() != NOT_REPORTED
    dv_ok = bool(dv) and dv.lower() != NOT_REPORTED
    if dv_ok and lv_ok and norm(dv) != norm(lv):
        rec[field] = dv
        prov[field] = {"source": det_source, "method": det_method,
                       "llm_value_rejected": lv[:280]}
        conflicts.append({"field": field, "deterministic": dv[:280], "llm": lv[:280],
                           "kept": "deterministic", "llm_source": "llm_section_text"})
    elif dv_ok:
        rec[field] = dv
        prov[field] = {"source": det_source, "method": det_method}
    elif lv_ok:
        rec[field] = lv
        prov[field] = {"source": "llm_section_text", "method": "llm_extraction"}
    else:
        rec[field] = NOT_REPORTED
        prov[field] = {"source": "none", "method": "no_evidence"}


def study_input_text(p, sec_by_paper, max_chars):
    secs = sec_by_paper.get(p["paper_id"], [])
    chosen = [s for s in secs if s.get("section_type") in ("Methods", "Abstract")]
    chosen.sort(key=lambda s: (0 if s.get("section_type") == "Abstract" else 1,
                               s.get("section_order") or 0))
    if not chosen and secs:
        chosen = sorted(secs, key=lambda s: s.get("section_order") or 0)[:3]
    parts, total = [], 0
    for s in chosen:
        txt = s.get("section_text_cleaned") or s.get("section_text_original") or ""
        label = s.get("section_name_original") or s.get("section_type") or "section"
        piece = f"## {label}\n{txt}"
        if total + len(piece) > max_chars:
            piece = piece[: max(0, max_chars - total)]
        parts.append(piece)
        total += len(piece)
        if total >= max_chars:
            break
    return "\n\n".join(parts)


def main():
    C.require_slurm(STAGE)
    cfg = C.load_config()
    if cfg["llm"].get("thinking") is not False:
        sys.exit("ERROR: llm.thinking must be false for this corpus build")
    port = int(os.environ.get("VLLM_PORT", "8000"))
    ev = C.Events(cfg["corpus"]["corpus_id"], STAGE, PV)
    cur = C.CurationLog()

    papers = C.read_jsonl(C.CORPUS_DIR / "data" / "papers.jsonl")
    sections = C.read_jsonl(C.CORPUS_DIR / "data" / "sections.jsonl")
    if not papers or not sections:
        sys.exit("ERROR: papers/sections missing; run stages 10-46 first")

    prjs = {(p.get("bioproject") or "").strip() for p in papers if p.get("bioproject")}
    proj_facts = load_projects_csv(prjs)
    sample_stats = load_sample_stats(prjs)
    bundle_meta = load_bundle_meta(prjs)
    term_map = load_terms_by_paper()

    sec_by_paper = defaultdict(list)
    for s in sections:
        if s.get("extraction_eligibility"):
            sec_by_paper[s["paper_id"]].append(s)

    max_chars = min(cfg["llm"]["max_prompt_chars"] * 3, 36000)

    ckpt = C.Checkpoint(C.CORPUS_DIR / "checkpoints" / f"{STAGE}.jsonl", key="paper_id")

    def fingerprint(p):
        secs = sec_by_paper.get(p["paper_id"], [])
        src_hash = C.sha256_text("\n".join(s.get("text_hash_sha256") or "" for s in secs))
        return C.sha256_text("|".join([p["paper_id"], p.get("bioproject") or "",
                                       src_hash, cfg["llm"]["model"],
                                       cfg["llm"]["studies_prompt_version"], PV]))

    fp_map = {p["paper_id"]: fingerprint(p) for p in papers}

    def usable(pid):
        if not ckpt.has(pid, fp_map[pid]):
            return False
        return ckpt.done[pid].get("extraction_status") == "COMPLETE"

    pending = [p for p in papers if not usable(p["paper_id"])]
    prog = C.Progress(STAGE, total=len(papers), unit="paper", desc="studies")
    prog.count = len(papers) - len(pending)
    if prog.bar is not None:
        prog.bar.update(prog.count)
        prog.bar.refresh()
    prog.log(f"papers={len(papers)} resumed={prog.count} pending={len(pending)}")

    if not llmio.wait_for_server(port, prog):
        ev.record(pipeline_stage=STAGE, run_status="failed",
                  error_message=f"vLLM server not ready on port {port}")
        ev.close()
        sys.exit(1)

    lock = threading.Lock()
    counts = {"COMPLETE": 0, "PARTIAL": 0, "FAILED": 0}
    started = C.now_utc()
    out_degrees = {}

    def work(p):
        """Extract one study record (LLM + deterministic merge)."""
        pid = p["paper_id"]
        prj = (p.get("bioproject") or "").strip()
        link = p.get("bioproject_link") or {}
        stats = sample_stats.get(prj)
        proj_row = proj_facts.get(prj) or {}
        bmeta = bundle_meta.get(prj) or {}
        terms = term_map.get(pid) or {}
        text = study_input_text(p, sec_by_paper, max_chars)

        rec = {
            "study_id": f"{pid}_STUDY_001",
            "corpus_id": pid,
            "paper_id": pid,
            "bioproject": prj or None,
            "extraction_status": "FAILED",
            "llm_error": None,
            "llm_model": cfg["llm"]["model_label"],
            "llm_model_version": f"vllm:{cfg['llm']['runtime']}",
            "llm_prompt_version": cfg["llm"]["studies_prompt_version"],
            "llm_input_chars": len(text),
            "llm_source_section_ids": [s["section_record_id"] for s in
                                       sec_by_paper.get(pid, [])
                                       if s.get("section_type") in ("Methods", "Abstract")],
            "llm_source_text_hash": C.sha256_text(text),
            "llm_degrees": [],
            "llm_split_retries": 0,
            "study_provenance": {},
        }
        llm_data, status, err = {}, "FAILED", "no eligible section text"
        if text:
            out_meta = {"llm_degrees": [], "llm_split_retries": 0}

            def build_prompt(chunk):
                return STUDY_PROMPT.format(title=p.get("title") or "untitled", chunk=chunk)

            extract = llmio.make_extractor(cfg, port, out_meta, build_prompt)
            try:
                chunks = C.chunk_text(text, cfg["llm"]["max_prompt_chars"])
                merged, statuses = {}, []
                for ci, chunk in enumerate(chunks):
                    data, st, e = extract(chunk, ci, 0)
                    if data:
                        merged = llmio.merge_data(merged, data)
                    statuses.append(st)
                    if st != "COMPLETE":
                        err = f"chunk{ci}:{e}"
                merged_status = ("COMPLETE" if all(s == "COMPLETE" for s in statuses)
                                 else "PARTIAL" if merged else "FAILED")
                llm_data, status, err = merged, merged_status, err
                rec["llm_degrees"] = out_meta["llm_degrees"]
                rec["llm_split_retries"] = out_meta["llm_split_retries"]
                out_degrees[pid] = {"chunks": len(chunks),
                                    "last_finish": (out_meta["llm_degrees"] or [{}])[-1].get("finish_reason")}
            except Exception as e:
                status, err = "FAILED", f"worker: {e!r}"
        rec["llm_status"] = status
        rec["llm_error"] = None if status == "COMPLETE" else err

        # ---- deterministic facts ----
        both = clean_str(proj_row.get("condition"))
        d_country = ", ".join(sorted(stats["geo"])) if stats else ""
        d_sample_type = clean_str(proj_row.get("sample_type"))
        d_n = (f"{stats['n_samples']} sequencing samples (compendium count)" if stats and stats["n_samples"] else "")
        d_instruments = ", ".join(sorted(stats["instruments"])) if stats else ""
        d_libstrat = ", ".join(sorted(stats["library_strategy"])) if stats else ""
        d_kit = clean_str(proj_row.get("kit"))
        d_bead = clean_str(proj_row.get("bead_beating"))
        d_subjects = clean_str(proj_row.get("subjects"))
        # assay from SRA library strategy is the strongest deterministic signal
        d_assay = ""
        if d_libstrat:
            mapped = sorted({LIBSTRATEGY_TO_ASSAY.get(x, "other") for x in d_libstrat.split(", ")})
            d_assay = "|".join(mapped)

        prov, conflicts = {}, []
        F = rec  # target record; fields written via set_field

        set_field(F, prov, conflicts, "study_design", llm_data.get("study_design"))
        set_field(F, prov, conflicts, "research_question", llm_data.get("research_question"))
        set_field(F, prov, conflicts, "country_region", llm_data.get("country_region"),
                  det_val=d_country, det_source="internal:168000-samples-paper/sample_metadata.tsv:geo_loc_name")
        set_field(F, prov, conflicts, "recruitment_setting", llm_data.get("recruitment_setting"))
        set_field(F, prov, conflicts, "population_description", llm_data.get("population_description"),
                  det_val=d_subjects or "", det_source="internal:168000-samples-paper/projects.csv:subjects")
        set_field(F, prov, conflicts, "num_biological_samples_reported", None,
                  det_val=d_n, det_source="internal:168000-samples-paper/sample_metadata.tsv:project_sample_count")
        set_field(F, prov, conflicts, "num_participants_reported",
                  llm_data.get("num_participants_reported"),
                  det_val=d_subjects or "",
                  det_source="internal:168000-samples-paper/projects.csv:subjects")
        set_field(F, prov, conflicts, "num_technical_replicates_reported",
                  llm_data.get("num_technical_replicates_reported"))
        set_field(F, prov, conflicts, "num_time_points_reported",
                  llm_data.get("num_time_points_reported"))
        set_field(F, prov, conflicts, "age_information", llm_data.get("age_information"))
        set_field(F, prov, conflicts, "sex_gender_information", llm_data.get("sex_gender_information"))
        set_field(F, prov, conflicts, "health_conditions", llm_data.get("health_conditions"),
                  det_val=both, det_source="internal:168000-samples-paper/projects.csv:condition")
        set_field(F, prov, conflicts, "exposures_interventions", llm_data.get("exposures_interventions"))
        set_field(F, prov, conflicts, "comparator_control_group", llm_data.get("comparator_control_group"))
        set_field(F, prov, conflicts, "eligibility_criteria", llm_data.get("eligibility_criteria"))
        set_field(F, prov, conflicts, "confounders_covariates_reported",
                  llm_data.get("confounders_covariates_reported"))
        set_field(F, prov, conflicts, "limitations_reported", llm_data.get("limitations_reported"))
        set_field(F, prov, conflicts, "body_sites", llm_data.get("body_sites"),
                  det_val=d_sample_type, det_source="internal:168000-samples-paper/projects.csv:sample_type")
        set_field(F, prov, conflicts, "specimen_types", llm_data.get("specimen_types"))
        # stage-50 term cross-source fills fields still not_reported (never overrides)
        if F["body_sites"] == NOT_REPORTED and terms.get("anatomical_site"):
            F["body_sites"] = ", ".join(sorted(terms["anatomical_site"])[:8])
            prov["body_sites"] = {"source": "stage50_llm_terms", "method": "terminology_cross_source"}
        set_field(F, prov, conflicts, "collection_method", llm_data.get("collection_method"))
        set_field(F, prov, conflicts, "collection_time_points", llm_data.get("collection_time_points"))
        set_field(F, prov, conflicts, "storage_transport_conditions",
                  llm_data.get("storage_transport_conditions"))
        set_field(F, prov, conflicts, "dna_rna_extraction_method",
                  llm_data.get("dna_rna_extraction_method"),
                  det_val=(f"{d_kit} (bead beating: {d_bead})" if d_kit and d_bead else d_kit),
                  det_source="internal:168000-samples-paper/projects.csv:kit/bead_beating")
        # assay: SRA library strategy outranks the LLM reading
        assay_det = {"source": "internal:168000-samples-paper/sample_metadata.tsv:library_strategy",
                    "det_val": d_assay}
        set_field(F, prov, conflicts, "assay_type", llm_data.get("assay_type"),
                  det_val=d_assay or None,
                  det_source=assay_det["source"])
        if F["assay_type"] != NOT_REPORTED and F["assay_type"] not in ASSAY_TYPES.values():
            F["assay_type"] = "other"
        if F["assay_type"] == NOT_REPORTED and d_libstrat:
            F["assay_type"] = "other"
            prov["assay_type"] = {"source": assay_det["source"],
                                   "method": "library_strategy_unmappable"}
        if not d_assay and F["assay_type"] == NOT_REPORTED and llm_data.get("assay_type_evidence"):
            pass  # LLM already had its chance; evidence kept below regardless
        F["assay_type_evidence"] = clean_str(llm_data.get("assay_type_evidence")) or NOT_REPORTED
        set_field(F, prov, conflicts, "sequencing_platform", llm_data.get("sequencing_platform"),
                  det_val=d_instruments, det_source="internal:168000-samples-paper/sample_metadata.tsv:instrument")
        if F["sequencing_platform"] == NOT_REPORTED and terms.get("method_technique"):
            plat = sorted({t for t in terms["method_technique"]
                           if norm(t) in {"illumina miseq", "illumina hiseq", "illumina novaseq",
                                          "ion torrent", "nanopore", "pacbio"}})
            if plat:
                F["sequencing_platform"] = ", ".join(plat)
                prov["sequencing_platform"] = {"source": "stage50_llm_terms",
                                              "method": "terminology_cross_source"}
        set_field(F, prov, conflicts, "target_gene_region", llm_data.get("target_gene_region"))
        if F["target_gene_region"] == NOT_REPORTED and proj_row.get("amplicon"):
            F["target_gene_region"] = clean_str(proj_row["amplicon"])
            prov["target_gene_region"] = {"source": "internal:168000-samples-paper/projects.csv:amplicon",
                                          "method": "deterministic"}
        set_field(F, prov, conflicts, "negative_positive_controls",
                  llm_data.get("negative_positive_controls"))
        set_field(F, prov, conflicts, "contamination_handling", llm_data.get("contamination_handling"))
        set_field(F, prov, conflicts, "taxonomic_profiling_method",
                  llm_data.get("taxonomic_profiling_method"))
        set_field(F, prov, conflicts, "taxonomic_database_and_version",
                  llm_data.get("taxonomic_database_and_version"))
        set_field(F, prov, conflicts, "functional_profiling_method",
                  llm_data.get("functional_profiling_method"))
        set_field(F, prov, conflicts, "quality_filtering_normalization",
                  llm_data.get("quality_filtering_normalization"))
        set_field(F, prov, conflicts, "statistical_methods", llm_data.get("statistical_methods"))
        if F["statistical_methods"] == NOT_REPORTED and terms.get("statistical_measure"):
            F["statistical_methods"] = ", ".join(sorted(terms["statistical_measure"])[:12])
            prov["statistical_methods"] = {"source": "stage50_llm_terms",
                                            "method": "terminology_cross_source"}
        set_field(F, prov, conflicts, "multiple_testing_correction",
                  llm_data.get("multiple_testing_correction"))
        set_field(F, prov, conflicts, "software_pipeline_version",
                  llm_data.get("software_pipeline_version"))
        set_field(F, prov, conflicts, "data_accessions",
                  None,
                  det_val=(f"BioProject:{prj}" if prj else ""), det_source="stage21_bioproject_link")
        set_field(F, prov, conflicts, "code_data_availability",
                  llm_data.get("code_data_availability"))

        # identify the study time window from SRA submission dates (evidence only)
        if stats and stats.get("pubdate_min"):
            F["sra_submission_window"] = f"{stats['pubdate_min']}..{stats['pubdate_max']}"
            prov["sra_submission_window"] = {"source": "internal:168000-samples-paper/sample_metadata.tsv:pubdate",
                                              "method": "deterministic"}
        else:
            F["sra_submission_window"] = NOT_REPORTED
            prov["sra_submission_window"] = {"source": "none", "method": "no_evidence"}

        prov["conflicts"] = conflicts
        F["study_provenance"] = prov

        # examination of source-country ISO codes as region hint (non §3G, evidence)
        if stats and stats["country_iso"]:
            F["country_iso_from_compendium"] = ", ".join(sorted(stats["country_iso"]))
        else:
            F["country_iso_from_compendium"] = NOT_REPORTED

        if status == "FAILED":
            F["extraction_status"] = "FAILED" if not text else "PARTIAL"
        elif status == "PARTIAL":
            F["extraction_status"] = "PARTIAL"
        else:
            F["extraction_status"] = "COMPLETE"
        # a paper that had no eligible text keeps its deterministic fields: PARTIAL
        if not text and F["extraction_status"] == "FAILED":
            F["extraction_status"] = "PARTIAL"
            F["llm_error"] = "no eligible section text; deterministic fields only"
        if not conflicts:
            prov["conflicts"] = []
        return F

    if pending:
        with ThreadPoolExecutor(cfg["llm"]["workers"]) as ex:
            futs = {ex.submit(work, p): p for p in pending}
            for fut in as_completed(futs):
                p = futs[fut]
                try:
                    rec = fut.result()
                except Exception as e:
                    rec = {"study_id": f"{p['paper_id']}_STUDY_001",
                           "corpus_id": p["paper_id"], "paper_id": p["paper_id"],
                           "extraction_status": "FAILED", "llm_status": "FAILED",
                           "llm_error": f"worker crash: {e!r}",
                           "study_provenance": {"conflicts": []}}
                ckpt.add(rec, fingerprint=fp_map[rec["paper_id"]])
                with lock:
                    counts[rec["extraction_status"]] = counts.get(rec["extraction_status"], 0) + 1
                    prog.update(1, detail=f"{rec['paper_id']} {rec['extraction_status']}")
                    if rec["extraction_status"] != "COMPLETE":
                        cur.add(rec["paper_id"], STAGE, cfg["llm"]["model_label"], PV,
                                "study extraction", rec["extraction_status"],
                                problem=str(rec.get("llm_error"))[:300],
                                resolution="fields kept; flagged unverified")
    ckpt.close()

    records = [ckpt.done[p["paper_id"]] for p in papers if p["paper_id"] in ckpt.done]
    C.write_jsonl(C.CORPUS_DIR / "data" / "studies.jsonl", records)

    n_conflict_fields = sum(len(r.get("study_provenance", {}).get("conflicts", []))
                            for r in records)
    conflicts_dist = {}
    for r in records:
        for c in r.get("study_provenance", {}).get("conflicts", []):
            conflicts_dist[c["field"]] = conflicts_dist.get(c.get("field"), 0) + 1
    tracked_fields = STUDY_FIELDS + LAB_FIELDS
    filled = sum(1 for r in records for k in tracked_fields
                 if r.get(k) not in (None, "", NOT_REPORTED))
    total_fields = len(records) * len(tracked_fields)
    summary = {
        "stage": STAGE, "pipeline_version": PV, "generated_at": C.now_utc(),
        "papers": len(papers), "study_records": len(records),
        "extraction_status_counts": dict(Counter(r["extraction_status"] for r in records)),
        "llm_status_counts": dict(Counter(r.get("llm_status") for r in records)),
        "conflict_fields_total": n_conflict_fields,
        "conflict_distribution": conflicts_dist,
        "papers_with_conflicts": sum(
            1 for r in records if r.get("study_provenance", {}).get("conflicts")),
        "field_fill_rate": round(filled / total_fields, 4) if total_fields else 0,
        "fields_per_study": len(tracked_fields),
        "model": cfg["llm"]["model"],
        "model_label": cfg["llm"]["model_label"],
        "prompt_version": cfg["llm"]["studies_prompt_version"],
        "thinking": cfg["llm"]["thinking"],
        "note": "every §3G field present per record; not_reported means no source "
                "states it; conflicts deterministic>llm are recorded not discarded",
    }
    C.atomic_write_json(C.CORPUS_DIR / "validation" / "studies_report.json", summary)
    ev.record(pipeline_stage=STAGE,
              run_status="success" if counts.get("FAILED", 0) == 0 else "partial",
              model_name_version=cfg["llm"]["model_label"],
              prompt_version=cfg["llm"]["studies_prompt_version"],
              started_at=started, completed_at=C.now_utc(),
              output_artifact_hash=C.sha256_text(json.dumps(summary, sort_keys=True)),
              note=f"records={len(records)} {summary['extraction_status_counts']}")
    ev.close()
    prog.close(summary=f"records={len(records)} {summary['extraction_status_counts']} "
                       f"conflicts={n_conflict_fields}")
    print(json.dumps(summary, indent=2))
    sys.exit(0)


if __name__ == "__main__":
    main()
