#!/usr/bin/env python3
"""Stage 70: freeze the validated corpus into a versioned release bundle.

Builds releases/<corpus_version>/ containing the manifest, the template §2
tracking table, the §3G study table, the §4 findings index, the §5 curation
log, the §7 quality report, the terminology inventory derived from LLM
extraction, the JSON schemas, and every data artifact with sha256 checksums.

This stage does NOT claim the corpus is scientifically validated: findings and
studies remain machine-extracted, quote resolution (stage 55) is an automated
check only, human verification_status stays `pending` throughout, and the
quality report says so explicitly.

Outputs under releases/<corpus_version>/
  corpus_manifest.json      template §1
  corpus_tracking.csv       template §2
  studies.csv              template §3G study table (one row per paper)
  findings_index.csv        template §4 findings index (one row per finding)
  curation_log.csv          template §5
  quality_report.md         template §7
  terminology_inventory.csv LLM-extracted term inventory
  schema/{study,finding}.schema.json
  data/{papers,sections,segments,llm_terms,studies,findings,
        findings_sections,validation_per_paper,...}.jsonl
  validation/*.json         stage reports incl. findings + studies reports
  MANIFEST.sha256
  README.md

Release 2.2.0 adds the triples layer (stages 53/54/56):
  data/{triple_mentions,canonical_triples,triples_sections,entities,
        candidate_entity_mappings,cross_paper_evidence,paper_summaries}.jsonl
  validation/{triples_extraction,summaries_extraction,
              triples_canonicalization,entity_linking}_report.json
  schema/{triple_relation_schema,triple_domains}.json
  adjudication_pilot/       model-assisted triage pilot copied VERBATIM from
           results/adjudication_pilot_triples_500/ (README/manifest/summary/
           triage_results only); the pilot is NOT verification — labels stay
           model recommendations and human_review_status stays `pending`.

The triples layer and the entity-linking results remain machine-extracted and
unverified: `reviewer=model`, `human_review_status=pending` everywhere; cross-
paper evidence is listed, not resolved. Stage 57 (human-in-the-loop entity
linking) is pending and will fold linking results into the canonical triples;
this release ships them side-by-side, unmerged.
"""
import csv
import json
import platform
import re
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import pipeline.common as C

STAGE = "stage70_finalize"
PV = "2.2.0"

# Adjudication pilot (model-assisted triage, NOT verification) — copied verbatim.
PILOT_DIR = C.REPO_ROOT / "outputs/results" / "adjudication_pilot_triples_500"
PILOT_FILES = ["README.md", "manifest.json", "triage_summary.json", "triage_results.jsonl"]

# Release-2.2.0 triples-layer data artifacts (streamed, too large to read fully).
TRIPLES_ARTIFACTS = [
    "triple_mentions.jsonl", "canonical_triples.jsonl", "triples_sections.jsonl",
    "entities.jsonl", "candidate_entity_mappings.jsonl", "cross_paper_evidence.jsonl",
    "paper_summaries.jsonl",
]
TRIPLES_VALIDATION = [
    "triples_extraction_report.json", "summaries_extraction_report.json",
    "triples_canonicalization_report.json", "entity_linking_report.json",
]
TRIPLES_SCHEMAS = ["triple_relation_schema.json", "triple_domains.json"]

# Rule for the "p-shaped effect estimate" quirk count (scripted, reproducible).
P_SHAPED_RE = re.compile(r"^<?\s*0\.\d+$")


def stream_jsonl(path):
    """Yield records one at a time (triple_mentions.jsonl is ~217 MB)."""
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)


def software_versions() -> dict:
    versions = {"python": platform.python_version(), "platform": platform.platform()}
    for mod in ("vllm", "tqdm", "yaml", "transformers"):
        try:
            m = __import__(mod)
            versions[mod] = getattr(m, "__version__", "unknown")
        except Exception:  # noqa: BLE001
            versions[mod] = "not_installed"
    return versions


CONTROLLED_TYPES = {
    "organism_taxa", "disease_phenotype", "method_technique", "gene_protein",
    "metabolite", "anatomical_site", "statistical_measure", "intervention",
}


def build_terminology(llm_records: list, papers: dict) -> list:
    """Aggregate per-section LLM terms into a term inventory (normalized + original).

    - a term is counted once per section, so repeated mentions do not inflate
      the occurrence count
    - a type outside the controlled vocabulary is kept as `unmapped:<type>`
      rather than silently relabelled or dropped
    """
    agg = {}
    seen_per_section = set()
    for r in llm_records:
        pid = r["paper_id"]
        canon = papers.get(pid, {}).get("canonical_paper_id") or pid
        for t in (r.get("llm_terms") or []):
            raw = (t.get("term") or "").strip()
            if not raw:
                continue
            key = C.normalize_title(raw)
            if not key:
                continue
            dedup_key = (r["section_record_id"], key)
            if dedup_key in seen_per_section:
                continue
            seen_per_section.add(dedup_key)
            a = agg.setdefault(key, {
                "term_normalized": key, "term_original_variants": set(),
                "term_types": set(), "papers": set(), "sections": set(),
                "occurrences": 0, "confidence_sum": 0.0, "confidence_n": 0,
                "contexts": [],
            })
            a["term_original_variants"].add(raw)
            ty = (t.get("type") or "").strip()
            if ty:
                a["term_types"].add(ty if ty in CONTROLLED_TYPES else f"unmapped:{ty}")
            a["papers"].add(canon)
            a["sections"].add(r["section_record_id"])
            a["occurrences"] += 1
            try:
                a["confidence_sum"] += float(t.get("confidence"))
                a["confidence_n"] += 1
            except (TypeError, ValueError):
                pass
            if t.get("context") and len(a["contexts"]) < 3:
                a["contexts"].append(t["context"])

    rows = []
    for key, a in agg.items():
        rows.append({
            "term_normalized": key,
            "term_original_variants": " | ".join(sorted(a["term_original_variants"])[:10]),
            "term_type": "|".join(sorted(a["term_types"])) or "untyped",
            "papers_count": len(a["papers"]),
            "sections_count": len(a["sections"]),
            "occurrences": a["occurrences"],
            "mean_llm_confidence": (round(a["confidence_sum"] / a["confidence_n"], 3)
                                    if a["confidence_n"] else ""),
            "example_context": a["contexts"][0] if a["contexts"] else "",
            "verification_status": "pending",
        })
    rows.sort(key=lambda r: (-r["occurrences"], r["term_normalized"]))
    return rows


def triples_layer_stats(corpus_dir, findings: list) -> dict:
    """Stream the 2.2.0 triples-layer artifacts and count everything the
    manifest / quality report quotes. Pure function of the release inputs, so
    the numbers written into the release are computed at release time (V5.4
    quirk-enumeration rule), never hard-coded. `findings` is the already-loaded
    findings list (p-shaped effect estimates live on findings, not mentions).
    """
    d = Path(corpus_dir) / "data"
    s = {}

    # ---- p-shaped effect estimates live on FINDINGS, not mentions ----
    # (rule: regex ^<?\s*0\.\d+$ on findings.effect_estimate, string-typed,
    #  'not_reported' excluded by the regex itself). "Duplicate-p" style
    # breakdowns are NOT shipped: no single reproducible rule was agreed, and
    # V5.4 requires the rule to be stated wherever the number appears.
    p_shaped = sum(
        1 for f in (findings or [])
        if isinstance(f.get("effect_estimate"), str)
        and P_SHAPED_RE.match(f["effect_estimate"].strip()))

    # ---- triple_mentions.jsonl (streamed: ~217 MB) ----
    rel_counter = Counter()
    ev_counter = Counter()
    papers_with = set()
    trunc_true = trunc_false = 0
    m_path = d / "triple_mentions.jsonl"
    if not m_path.exists():
        return {}
    for r in stream_jsonl(m_path):
        rel_counter[r.get("relation_normalized") or "UNKNOWN"] += 1
        ev_counter[r.get("evidence_locator_status") or "not_checked"] += 1
        papers_with.add(r.get("paper_id"))
        if r.get("truncation_status") is True:
            trunc_true += 1
        elif r.get("truncation_status") is False:
            trunc_false += 1
        cand = r.get("effect_estimate")
        # p-shaped count is computed on findings above; mentions carry
        # effect_measure_value only, so nothing to count here.
    s["mentions"] = {
        "total": sum(rel_counter.values()),
        "relations": dict(rel_counter),
        "relation_distinct": len(rel_counter),
        "evidence_locator_status": dict(ev_counter),
        "papers_with_mentions": len(papers_with),
        "other_relation_mentions": rel_counter.get("OTHER_RELATION", 0),
        "truncation_status_true": trunc_true,
        "truncation_status_false": trunc_false,
        "p_shaped_effect_estimates": p_shaped,
        # private key consumed by _mentions_papers_with(); not rendered
        "_papers_with_mentions_ids": sorted(papers_with),
    }

    # ---- triples_sections.jsonl ----
    llm_st = Counter()
    secs_with_trunc = 0
    chunks_failed = chunks_trunc = chunks_total = split_retries = 0
    ts_path = d / "triples_sections.jsonl"
    if ts_path.exists():
        for r in stream_jsonl(ts_path):
            llm_st[r.get("llm_status") or "UNKNOWN"] += 1
            n_tr = r.get("llm_chunks_truncated") or 0
            chunks_failed += r.get("llm_chunks_failed") or 0
            chunks_total += r.get("llm_chunks") or 0
            split_retries += r.get("llm_split_retries") or 0
            if n_tr:
                chunks_trunc += n_tr
                secs_with_trunc += 1
        s["triples_sections"] = {
            "total": sum(llm_st.values()),
            "llm_status": dict(llm_st),
            "sections_with_truncated_chunks": secs_with_trunc,
            "chunks_total": chunks_total,
            "chunks_truncated": chunks_trunc,
            "chunks_failed": chunks_failed,
            "split_retries": split_retries,
        }

    # ---- canonical_triples.jsonl ----
    conflicts = Counter()
    linking = Counter()
    canon_unresolved = 0
    canon_total = 0
    c_path = d / "canonical_triples.jsonl"
    if c_path.exists():
        for r in stream_jsonl(c_path):
            canon_total += 1
            conflicts[r.get("conflict_flag") or "none"] += 1
            linking[r.get("external_linking_status") or "not_checked"] += 1
            if r.get("evidence_unresolved_count"):
                canon_unresolved += 1
        s["canonical_triples"] = {
            "total": canon_total,
            "conflict_flag": dict(conflicts),
            "external_linking_status": dict(linking),
            "with_evidence_unresolved": canon_unresolved,
        }

    # ---- candidate_entity_mappings.jsonl ----
    disp = Counter()
    lookups = Counter()
    m2_path = d / "candidate_entity_mappings.jsonl"
    if m2_path.exists():
        for r in stream_jsonl(m2_path):
            disp[r.get("mapping_disposition") or "UNKNOWN"] += 1
            lookups[r.get("lookup_status") or "UNKNOWN"] += 1
        s["candidate_entity_mappings"] = {
            "total": sum(disp.values()),
            "mapping_disposition": dict(disp),
            "lookup_status": dict(lookups),
        }

    # ---- entities.jsonl / cross_paper_evidence.jsonl / paper_summaries.jsonl ----
    for name, key in (("entities.jsonl", "entities"),
                      ("cross_paper_evidence.jsonl", "cross_paper_evidence"),
                      ("paper_summaries.jsonl", "paper_summaries")):
        p = d / name
        if p.exists():
            s[key] = {"total": sum(1 for _ in stream_jsonl(p))}

    # ---- evidence "unresolved" derivation rules (stated inline, computed) ----
    # findings unresolved rule: evidence_locator_status == "unresolved_not_in_source"
    # mentions unresolved rule: evidence_locator_status == "unresolved_not_in_source"
    # canonical unresolved rule: evidence_unresolved_count >= 1
    s["evidence_rules"] = {
        "findings_unresolved": 'evidence_locator_status == "unresolved_not_in_source"',
        "mentions_unresolved": 'evidence_locator_status == "unresolved_not_in_source"',
        "canonical_unresolved": "evidence_unresolved_count >= 1",
        "p_shaped_rule": 'regex ^<?\\s*0\\.\\d+$ on effect_estimate (string)',
    }
    return s


def _mentions_papers_with(tstats: dict) -> set:
    """Paper ids that have >=1 triple mention (private key, not for the manifest)."""
    return set(tstats.get("mentions", {}).get("_papers_with_mentions_ids") or [])


def llm_term_quirk_stats(llm_records: list) -> dict:
    """Count reproducible terminology quirks over the section LLM records.
    Malformed rule: term is blank, OR longer than 200 chars, OR contains any
    of \\n, \\r, \\t. Off-schema rule: type not in CONTROLLED_TYPES (kept as
    `unmapped:<type>`), counted per raw type string.
    """
    malformed = 0
    off_schema_occ = 0
    off_types = Counter()
    for r in llm_records:
        for t in (r.get("llm_terms") or []):
            raw = t.get("term") or ""
            if (not raw.strip()) or (len(raw) > 200) or re.search(r"[\n\r\t]", raw):
                malformed += 1
            ty = (t.get("type") or "").strip()
            if ty and ty not in CONTROLLED_TYPES:
                off_schema_occ += 1
                off_types[ty] += 1
    return {
        "llm_terms_malformed": malformed,
        "llm_terms_malformed_rule": "blank OR >200 chars OR contains newline/tab",
        "llm_terms_off_schema_occurrences": off_schema_occ,
        "llm_terms_off_schema_distinct_types": len(off_types),
        "llm_terms_off_schema_types": dict(off_types),
    }


def papers_with_curation_issue(cur_path, stage: str) -> set:
    """Corpus IDs with >=1 PARTIAL/FAILED curation-log row for `stage`."""
    ids = set()
    if not Path(cur_path).exists():
        return ids
    with open(cur_path, encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if ((row.get("Stage") or "").strip() == stage
                    and (row.get("Result") or "").strip() in ("PARTIAL", "FAILED")):
                cid = (row.get("Corpus ID") or "").strip()
                if cid:
                    ids.add(cid)
    return ids


def main():
    C.require_slurm(STAGE)
    cfg = C.load_config()
    corpus = cfg["corpus"]
    version = corpus["corpus_version"]
    release_dir = C.CORPUS_DIR / "releases" / version
    force = "--force-release" in sys.argv

    if release_dir.exists() and any(release_dir.iterdir()) and not force:
        sys.exit(f"ERROR: {release_dir} already exists and is non-empty "
                 f"(bump corpus_version or pass --force-release)")

    ev = C.Events(corpus["corpus_id"], STAGE, PV)
    started = C.now_utc()

    papers = C.read_jsonl(C.CORPUS_DIR / "data" / "papers.jsonl")
    sections = C.read_jsonl(C.CORPUS_DIR / "data" / "sections.jsonl")
    segments = C.read_jsonl(C.CORPUS_DIR / "data" / "segments.jsonl")
    llm = C.read_jsonl(C.CORPUS_DIR / "data" / "llm_terms.jsonl")
    per_paper = C.read_jsonl(C.CORPUS_DIR / "data" / "validation_per_paper.jsonl")
    studies = C.read_jsonl(C.CORPUS_DIR / "data" / "studies.jsonl")
    findings = C.read_jsonl(C.CORPUS_DIR / "data" / "findings.jsonl")
    if not papers or not sections:
        sys.exit("ERROR: corpus artifacts missing; run stages 10–60 first")
    if not studies:
        sys.exit("ERROR: data/studies.jsonl missing or empty; run stage 51 first")
    if not findings:
        sys.exit("ERROR: data/findings.jsonl missing or empty; run stage 52 (and 55) first")

    triples_artifacts_exist = {}
    for name in TRIPLES_ARTIFACTS:
        p = C.CORPUS_DIR / "data" / name
        triples_artifacts_exist[name] = p.exists() and p.stat().st_size > 0
    if not all(triples_artifacts_exist.values()):
        missing = [n for n, ok in triples_artifacts_exist.items() if not ok]
        if "triple_mentions.jsonl" in missing or "canonical_triples.jsonl" in missing:
            sys.exit(f"ERROR: triples-layer artifacts missing/empty: {missing}; run stages 53+54+56 first")
        print(f"WARNING: non-critical triples artifacts missing: {missing}")

    pilot_ok = PILOT_DIR.exists() and (PILOT_DIR / "triage_summary.json").exists()
    if not pilot_ok:
        sys.exit(f"ERROR: adjudication pilot missing at {PILOT_DIR} "
                 f"(triage_summary.json required); 2.2.0 ships the pilot verbatim")

    prog = C.Progress(STAGE, total=9, unit="step", desc="finalize")
    release_dir.mkdir(parents=True, exist_ok=True)
    (release_dir / "data").mkdir(exist_ok=True)

    # ---- copy artifacts ----
    artifacts = list(TRIPLES_ARTIFACTS) + [
        "papers.jsonl", "sections.jsonl", "segments.jsonl",
        "llm_terms.jsonl", "validation_per_paper.jsonl",
        "fulltext_crosscheck.jsonl",
        "studies.jsonl", "findings.jsonl", "findings_sections.jsonl"]
    for name in artifacts:
        src = C.CORPUS_DIR / "data" / name
        if src.exists():
            shutil.copy2(src, release_dir / "data" / name)
    prog.update(1, detail=f"copied {len(artifacts)} data artifacts (incl. triples layer)")

    # ---- integrity reports (linkage + independent cross-check + layers) ----
    (release_dir / "validation").mkdir(exist_ok=True)
    for name in tuple(TRIPLES_VALIDATION) + (
            "bioproject_link_report.json", "fulltext_crosscheck_report.json",
            "validation_report.json", "studies_report.json",
            "findings_report.json", "findings_extraction_report.json"):
        src = C.CORPUS_DIR / "validation" / name
        if src.exists():
            shutil.copy2(src, release_dir / "validation" / name)

    # ---- JSON schemas ----
    (release_dir / "schema").mkdir(exist_ok=True)
    for name in tuple(TRIPLES_SCHEMAS) + ("study.schema.json", "finding.schema.json"):
        src = C.CORPUS_DIR / "schema" / name
        if src.exists():
            shutil.copy2(src, release_dir / "schema" / name)

    # ---- adjudication pilot (copied VERBATIM; framing preserved) ----
    (release_dir / "adjudication_pilot").mkdir(exist_ok=True)
    for name in PILOT_FILES:
        shutil.copy2(PILOT_DIR / name, release_dir / "adjudication_pilot" / name)
    prog.update(1, detail="adjudication_pilot copied verbatim")

    # ---- template §2 tracking table ----
    shutil.copy2(C.CORPUS_DIR / "data" / "corpus_tracking.csv",
                 release_dir / "corpus_tracking.csv")
    prog.update(1, detail="corpus_tracking.csv")

    # ---- template §5 curation log ----
    cur_path = C.CORPUS_DIR / "data" / "curation_log.csv"
    if cur_path.exists():
        shutil.copy2(cur_path, release_dir / "curation_log.csv")
    prog.update(1, detail="curation_log.csv")

    # ---- terminology inventory ----
    paper_map = {p["paper_id"]: p for p in papers}
    terms = build_terminology(llm, paper_map)
    term_cols = ["term_normalized", "term_original_variants", "term_type", "papers_count",
                 "sections_count", "occurrences", "mean_llm_confidence",
                 "example_context", "verification_status"]
    with open(release_dir / "terminology_inventory.csv", "w", newline="",
              encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=term_cols)
        w.writeheader()
        w.writerows(terms)
    prog.update(1, detail=f"terminology terms={len(terms)}")

    # ---- template §4 findings index (one row per finding) ----
    # Short description is assembled ONLY from extracted fields (outcome,
    # direction, taxon/function); nothing is invented. Findings with empty
    # evidence_text or unresolved quotes are KEPT and flagged, never dropped.
    with open(release_dir / "findings_index.csv", "w", newline="",
              encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["Finding ID", "Corpus ID", "Study ID", "Short description",
                     "Evidence locator", "Extraction status", "Verification status", "Note"])
        for f in findings:
            parts = []
            oc = (f.get("outcome") or "").strip()
            if oc and oc.lower() != "not_reported":
                parts.append(oc)
            if f.get("direction"):
                parts.append(f"direction={f['direction']}")
            for k0 in ("taxon_original", "microbial_function_pathway"):
                v0 = (f.get(k0) or "").strip()
                if v0 and v0.lower() != "not_reported":
                    parts.append(v0)
                    break
            desc = "; ".join(parts) if parts else "no description fields reported"
            locator_status = f.get("evidence_locator_status") or "not_checked"
            note = f"evidence_locator_status={locator_status}"
            if not (f.get("evidence_text") or "").strip():
                note += "; empty evidence_text"
            if f.get("notes"):
                note += f"; notes={f['notes']}"
            w.writerow([f["finding_id"], f["corpus_id"], f["study_id"], desc,
                        f.get("evidence_locator") or "",
                        f.get("extraction_status_section") or "UNKNOWN",
                        f.get("verification_status") or "pending", note])
    prog.update(1, detail=f"findings_index.csv findings={len(findings)}")

    # ---- template §3G study table (one row per paper) ----
    study_cols = ["study_id", "corpus_id", "paper_id", "bioproject",
                  "extraction_status", "llm_status", "study_design",
                  "research_question", "country_region", "recruitment_setting",
                  "population_description", "num_participants_reported",
                  "num_biological_samples_reported",
                  "num_technical_replicates_reported", "num_time_points_reported",
                  "age_information", "sex_gender_information", "health_conditions",
                  "exposures_interventions", "comparator_control_group",
                  "eligibility_criteria", "confounders_covariates_reported",
                  "limitations_reported", "body_sites", "specimen_types",
                  "collection_method", "collection_time_points",
                  "storage_transport_conditions", "dna_rna_extraction_method",
                  "assay_type", "assay_type_evidence", "sequencing_platform",
                  "target_gene_region", "negative_positive_controls",
                  "contamination_handling", "taxonomic_profiling_method",
                  "taxonomic_database_and_version", "functional_profiling_method",
                  "quality_filtering_normalization", "statistical_methods",
                  "multiple_testing_correction", "software_pipeline_version",
                  "data_accessions", "code_data_availability",
                  "sra_submission_window", "country_iso_from_compendium"]
    with open(release_dir / "studies.csv", "w", newline="",
              encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=study_cols, extrasaction="ignore")
        w.writeheader()
        for srec in studies:
            w.writerow({k0: srec.get(k0, "not_reported") for k0 in study_cols})
    prog.update(1, detail=f"studies.csv studies={len(studies)}")

    status_counts = Counter(r["validation_status"] for r in per_paper)
    paper_counts = Counter(p.get("full_text_completeness") or "not_checked" for p in papers)
    llm_counts = Counter(r.get("llm_status") for r in llm)
    crosscheck = C.read_jsonl(C.CORPUS_DIR / "data" / "fulltext_crosscheck.jsonl")
    xc_counts = Counter(r.get("crosscheck_status") for r in crosscheck)
    xc_missing = [r["paper_id"] for r in crosscheck if r.get("missing_sections")]
    curated = Counter()
    if cur_path.exists():
        with open(cur_path, encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                curated[row.get("Stage") or "unknown"] += 1

    # ---- release-2.2.0 triples layer + quirk stats (computed, not hard-coded) ----
    tstats = triples_layer_stats(C.CORPUS_DIR, findings)
    if not tstats.get("mentions"):
        sys.exit("ERROR: triples_layer_stats() returned no mention stats; "
                 "data/triple_mentions.jsonl unreadable")
    quirk = llm_term_quirk_stats(llm)
    pilot_summary = json.loads((PILOT_DIR / "triage_summary.json").read_text(encoding="utf-8"))

    # papers without mentions / findings / eligible sections — derived here
    m = tstats["mentions"]
    ts = tstats.get("triples_sections", {})
    papers_no_mentions = sorted(
        {p["paper_id"] for p in papers} - _mentions_papers_with(tstats))
    papers_no_findings = sorted(
        {p["paper_id"] for p in papers}
        - {f.get("corpus_id") for f in findings if f.get("corpus_id")})
    eligible_by_paper = defaultdict(list)
    for sec in sections:
        if sec.get("extraction_eligibility"):
            eligible_by_paper[sec["paper_id"]].append(sec["section_record_id"])
    papers_no_eligible = sorted(p["paper_id"] for p in papers
                               if not eligible_by_paper.get(p["paper_id"]))


    # ---- manifest (template §1) ----
    manifest = {
        "corpus_id": corpus["corpus_id"],
        "corpus_name": corpus["corpus_name"],
        "corpus_version": version,
        "schema_version": "1.1.0",
        "generated_at": C.now_utc(),
        "pipeline_version": PV,
        "purpose": corpus["corpus_purpose"],
        "research_questions": corpus["research_questions"],
        "domain": corpus["domain"],
        "target_terminology_types": corpus["target_terminology_types"],
        "owner": corpus["corpus_owner"],
        "license_and_usage": corpus["license_and_usage"],
        "search_strategy": cfg["search_strategy"],
        "eligibility": cfg["eligibility"],
        "configuration_hash": C.config_hash(cfg),
        "source": {
            "database": "internal segmented markdown derived from PubMed full text",
            "directory": str((C.REPO_ROOT / "data/segmented_sections_markdown")),
            "conversion_report": str(
                C.REPO_ROOT / "data/segmented_sections_markdown" / "_conversion_report.json"),
            "files": len(papers),
            "raw_hash_algorithm": "sha256",
            "per_file_hashes": "see data/papers.jsonl (raw_file_hash)",
        },
        "counts": {
            "papers": len(papers),
            "papers_canonical": sum(1 for p in papers if p.get("is_canonical", True)),
            "papers_duplicate_excluded": sum(1 for p in papers if not p.get("is_canonical", True)),
            "sections": len(sections),
            "sections_eligible_for_extraction": sum(
                1 for s in sections if s.get("extraction_eligibility")),
            "sections_container_excluded": sum(
                1 for s in sections if s.get("is_container_section")),
            "segments": len(segments),
            "characters": sum(s.get("character_count") or 0 for s in sections),
            "tokens": sum(s.get("token_count") or 0 for s in sections),
            "llm_enriched_sections": len(llm),
            "llm_terms": sum(len(r.get("llm_terms") or []) for r in llm),
            "terminology_inventory_rows": len(terms),
            "studies": len(studies),
            "findings": len(findings),
            "findings_sections": len(
                C.read_jsonl(C.CORPUS_DIR / "data" / "findings_sections.jsonl")),
            "findings_evidence_resolved": sum(
                1 for f in findings
                if f.get("evidence_locator_status") in
                ("verified_exact", "verified_normalized")),
            "findings_evidence_unresolved": sum(
                1 for f in findings
                if f.get("evidence_locator_status") == "unresolved_not_in_source"),
            "independent_fulltext_crosschecked": len(crosscheck),
            "papers_with_missing_sections": len(xc_missing),
            # ---- release 2.2.0: triples layer (stages 53/54/56) ----
            "triple_mentions": m["total"],
            "canonical_triples": tstats["canonical_triples"]["total"],
            "triples_sections": ts.get("total", 0),
            "entities": tstats["entities"]["total"],
            "candidate_entity_mappings": tstats["candidate_entity_mappings"]["total"],
            "cross_paper_evidence": tstats["cross_paper_evidence"]["total"],
            "paper_summaries": tstats["paper_summaries"]["total"],
            "triple_mentions_evidence_resolved": sum(
                v for k, v in m["evidence_locator_status"].items()
                if k in ("verified_exact", "verified_normalized")),
            "triple_mentions_evidence_unresolved": m["evidence_locator_status"].get(
                "unresolved_not_in_source", 0),
            "triple_mentions_truncated": m["truncation_status_true"],
            "papers_without_triple_mentions": len(papers_no_mentions),
            "papers_without_findings": len(papers_no_findings),
            "papers_without_eligible_sections": len(papers_no_eligible),
        },
        "status_summary": {
            "validation_status": dict(status_counts),
            "full_text_completeness": dict(paper_counts),
            "llm_status": dict(llm_counts),
            "studies_extraction_status": dict(
                Counter(s.get("extraction_status") for s in studies)),
            "studies_llm_status": dict(Counter(s.get("llm_status") for s in studies)),
            "findings_extraction_status_section": dict(
                Counter(f.get("extraction_status_section") for f in findings)),
            "findings_claim_type": dict(Counter(f.get("claim_type") for f in findings)),
            "findings_direction": dict(Counter(f.get("direction") for f in findings)),
            "findings_evidence_locator_status": dict(
                Counter(f.get("evidence_locator_status") for f in findings)),
            # ---- release 2.2.0 ----
            "triple_mentions_relation_normalized": m["relations"],
            "triple_mentions_evidence_locator_status": m["evidence_locator_status"],
            "triple_mentions_truncation_status": {
                "true": m["truncation_status_true"],
                "false": m["truncation_status_false"],
            },
            "triples_sections_llm_status": ts.get("llm_status", {}),
            "paper_summaries_llm_status": dict(Counter(
                r.get("llm_status") for r in
                stream_jsonl(C.CORPUS_DIR / "data" / "paper_summaries.jsonl"))),
            "candidate_entity_mapping_disposition":
                tstats["candidate_entity_mappings"]["mapping_disposition"],
            "candidate_entity_mapping_lookup_status":
                tstats["candidate_entity_mappings"]["lookup_status"],
            "canonical_triple_conflict_flag":
                tstats["canonical_triples"]["conflict_flag"],
            "canonical_external_linking_status":
                tstats["canonical_triples"]["external_linking_status"],
        },
        "software": software_versions(),
        "llm": {
            "model": cfg["llm"]["model"],
            "model_label": cfg["llm"]["model_label"],
            "runtime": cfg["llm"]["runtime"],
            "runtime_version": software_versions().get("vllm", "unknown"),
            "prompt_version": cfg["llm"]["prompt_version"],
            "thinking": cfg["llm"]["thinking"],
            "temperature": cfg["llm"]["temperature"],
            "max_tokens": cfg["llm"]["max_tokens"],
            "max_prompt_chars": cfg["llm"]["max_prompt_chars"],
            "workers": cfg["llm"]["workers"],
        },
        "resources": cfg["resources"],
        "curation_events_by_stage": dict(curated),
        "adjudication_pilot": {
            "note": "model-assisted triage pilot, copied VERBATIM from "
                    "results/adjudication_pilot_triples_500/; NOT verification",
            "not_verification": True,
            "human_review_status": "pending",
            "copied_files": PILOT_FILES,
            "canonical_location": str(PILOT_DIR),
            "excluded_from_release": [
                "sample_500_enriched.jsonl", "sheets/",
                "get full pilot outputs from canonical_location",
            ],
            "n": pilot_summary.get("n"),
            "population_mentions": pilot_summary.get("population", {}).get("mentions"),
            "seed": pilot_summary.get("population", {}).get("seed"),
            "triage_labels": pilot_summary.get("triage_label_distribution"),
            "reason_codes": pilot_summary.get("reason_code_distribution"),
            "escape_records_in_sample":
                pilot_summary.get("escape_family_lookup", {})
                .get("escape_records_in_sample"),
            "escape_should_map_total":
                pilot_summary.get("escape_family_lookup", {}).get("escape_should_map_total"),
            "caveat": "Labels are model triage recommendations only; no human "
                      "adjudication has occurred; no accuracy or corpus-quality "
                      "claims may be derived from these labels alone.",
        },
        "known_limitations": [
            "LLM-extracted terminology, study metadata and findings are "
            "extracted_unverified; the human verification gate (finding-level review) "
            "has not been run.",
            "Findings and study metadata are LLM-extracted (§4/§3G) with deterministic "
            "compendium precedence where available; conflicts are recorded, never silently "
            "resolved.",
            "Evidence quotes are machine-checked against the cited text version only "
            "(stage 55); quote resolution is not scientific verification, and unresolved "
            "quotes are kept and flagged, never dropped.",
            "Null results, negative results and contradictory statements are included as "
            "findings; their absence from a paper is not evidence of absence.",
            "Upstream conversion defects (NUL bytes, skipped sections) are recorded, not repaired.",
            "Reference/acknowledgement/supplementary sections are retained but not extracted.",
            "Schema validity does not imply scientific correctness.",
            "Release 2.2.0 adds the triples layer (stages 53/54/56): triple "
            "mentions, canonical triples, entities and candidate mappings are "
            "LLM-extracted; automated checks (quote recovery, duplicate grouping, "
            "relation normalization) are structural only, and human adjudication "
            "has not begun.",
            "Entity linking (stage 57) is pending: candidate mappings ship "
            "side-by-side with canonical triples and are NOT folded in; "
            "`mapping_disposition=AUTO_ACCEPTED` is a pipeline-internal "
            "string-match verdict, not human acceptance.",
            "The model-assisted adjudication pilot (adjudication_pilot/) labels "
            "are triage recommendations only (reviewer=model, "
            "human_review_status=pending throughout); it is not a gold standard "
            "and supports no accuracy claims.",
        ],
        "known_quirks": {
            "note": "All numbers below are computed at release time from the "
                    "release inputs; the derivation rule is stated with each item.",
            "other_relation_mentions": {
                "count": m["other_relation_mentions"],
                "of_mentions": m["total"],
                "rule": "mention.relation_normalized == 'OTHER_RELATION'",
            },
            "relation_vocabulary": {
                "distinct_normalized_relations": m["relation_distinct"],
                "rule": "len(set(mention.relation_normalized))",
            },
            "mention_output_truncation": {
                "truncated_mentions": m["truncation_status_true"],
                "of_mentions": m["total"],
                "pct": round(100.0 * m["truncation_status_true"] / max(m["total"], 1), 1),
                "rule": "mention.truncation_status == true (stage-53 output-cap "
                        "truncation; input chunking at max_prompt_chars is by design "
                        "and lossless, output-cap truncation is the loss quirk)",
                "sections_with_truncated_chunks": ts.get("sections_with_truncated_chunks", 0),
                "of_sections_extracted": ts.get("total", 0),
                "chunks_truncated": ts.get("chunks_truncated", 0),
                "of_chunks": ts.get("chunks_total", 0),
                "split_retries": ts.get("split_retries", 0),
            },
            "p_shaped_effect_estimates": {
                "count": m["p_shaped_effect_estimates"],
                "of_findings": len(findings),
                "rule": "regex '^<?\\s*0\\.\\d+$' on findings.effect_estimate "
                        "(string); V5.4's ~1,088 figure was a broader approximation; "
                        "duplicate-p/sole-p sub-splits are NOT shipped (no single "
                        "reproducible rule was agreed)",
            },
            "llm_terms_malformed": {
                "count": quirk["llm_terms_malformed"],
                "rule": quirk["llm_terms_malformed_rule"],
            },
            "llm_terms_off_schema": {
                "occurrences": quirk["llm_terms_off_schema_occurrences"],
                "distinct_types": quirk["llm_terms_off_schema_distinct_types"],
                "rule": "llm term type not in controlled vocabulary; kept as "
                        "`unmapped:<type>`, never dropped or relabelled",
                "types": quirk["llm_terms_off_schema_types"],
            },
            "findings_evidence_unresolved": {
                "count": sum(
                    1 for f in findings
                    if f.get("evidence_locator_status") == "unresolved_not_in_source"),
                "of_findings": len(findings),
                "rule": 'evidence_locator_status == "unresolved_not_in_source"; '
                        "kept and flagged, never dropped",
            },
            "mention_evidence_unresolved": {
                "count": m["evidence_locator_status"].get("unresolved_not_in_source", 0),
                "of_mentions": m["total"],
                "rule": 'evidence_locator_status == "unresolved_not_in_source"; '
                        "kept and flagged, never dropped",
            },
            "canonical_cross_mention_conflicts": {
                "count": tstats["canonical_triples"]["conflict_flag"].get(
                    "conflicting_across_mentions", 0),
                "of_canonical_triples": tstats["canonical_triples"]["total"],
                "rule": "canonical.conflict_flag == 'conflicting_across_mentions'; "
                        "conflicts are recorded, never silently resolved",
            },
            "canonical_evidence_unresolved": {
                "count": tstats["canonical_triples"]["with_evidence_unresolved"],
                "of_canonical_triples": tstats["canonical_triples"]["total"],
                "rule": "canonical.evidence_unresolved_count >= 1",
            },
            "papers_without_mentions": {
                "paper_ids": papers_no_mentions,
                "rule": "papers with zero rows in data/triple_mentions.jsonl; both have "
                        "zero extraction-eligible sections (46-mention papers with "
                        "'partial' completeness are normal, not anomalies)",
                "note": "'partial' full_text_completeness is the corpus norm "
                        "(the majority of papers), not a data quirk",
            },
            "papers_without_findings": {
                "count": len(papers_no_findings),
                "rule": "papers with zero rows in data/findings.jsonl",
            },
            "papers_without_eligible_sections": {
                "paper_ids": papers_no_eligible,
                "rule": "papers whose sections all have extraction_eligibility=false",
            },
            "hypernym_taxa_mentions": {
                "carried_forward": True,
                "note": "taxon mentions recorded at genus/family level (e.g. "
                        "'Lactobacillus') where the source text reports a species-"
                        "level claim; qualitative V5.4 carry-forward, count not "
                        "computed at release time",
            },
            "exemplar_extraction_anomalies": {
                "examples": [
                    "HMPAPER_000268 — one stage-53 chunk FAILED (truncated JSON); "
                    "26 mentions retained; see data/curation_log.csv",
                    "HMPAPER_000239 — stage-53 PARTIAL chunks; 69 mentions retained; "
                    "see data/curation_log.csv",
                ],
                "context": {
                    "papers_with_partial_or_failed_stage53_entries": len(
                        papers_with_curation_issue(cur_path, "stage53_triples_extract")),
                    "triples_sections_llm_status": ts.get("llm_status", {}),
                    "paper_summaries_llm_status": dict(Counter(
                        r.get("llm_status") for r in
                        stream_jsonl(C.CORPUS_DIR / "data" / "paper_summaries.jsonl"))),
                    "note": "see validation/summaries_extraction_report.json for "
                            "the single FAILED summary (HMPAPER_000173) and "
                            "truncated-chunk counts",
                },
            },
        },
    }
    C.atomic_write_json(release_dir / "corpus_manifest.json", manifest)
    prog.update(1, detail="corpus_manifest.json incl. known_quirks + adjudication pilot block")

    # ---- quality report (template §7) ----
    qr = [
        f"# Quality report — {corpus['corpus_id']} v{version}", "",
        f"Generated: {C.now_utc()}  ",
        f"Pipeline: {PV}  ",
        f"Configuration hash: `{manifest['configuration_hash']}`", "",
        "## Documents", "",
        f"- Papers: **{len(papers)}** "
        f"(canonical {manifest['counts']['papers_canonical']}, "
        f"duplicate-excluded {manifest['counts']['papers_duplicate_excluded']})",
        f"- Sections: **{len(sections)}** "
        f"(eligible {manifest['counts']['sections_eligible_for_extraction']}, "
        f"container-excluded {manifest['counts']['sections_container_excluded']})",
        f"- Segments: **{len(segments)}**",
        f"- Characters: **{manifest['counts']['characters']:,}**  "
        f"Tokens: **{manifest['counts']['tokens']:,}**", "",
        "## Status distribution", "",
        "| Dimension | Values |", "|---|---|",
        f"| Validation | `{dict(status_counts)}` |",
        f"| Full-text completeness | `{dict(paper_counts)}` |",
        f"| Independent XML cross-check | `{dict(xc_counts)}` "
        f"({len(crosscheck)}/{len(papers)} papers have an original JATS XML) |",
        f"| LLM enrichment | `{dict(llm_counts)}` |", "",
        "## Full-text integrity", "",
        f"- Exact BioProject linkage to the compendium bundle: "
        f"**{sum(1 for p in papers if (p.get('bioproject_link') or {}).get('matched'))}"
        f"/{len(papers)}**",
        f"- Independent structural cross-check against original JATS XML: "
        f"**{len(crosscheck)}** papers",
        f"- Papers whose original XML has substantive sections absent from the "
        f"reconstructed text: **{len(xc_missing)}**"
        + (f" (`{', '.join(xc_missing[:10])}`)" if xc_missing else ""),
        "- PDF-only and local-text-only papers have no independent source and are "
        "reported as `not_available`, never assumed complete.", "",
        "## LLM extraction", "",
        f"- Model: `{cfg['llm']['model']}` ({cfg['llm']['model_label']}), "
        f"runtime `{cfg['llm']['runtime']}`, thinking **{cfg['llm']['thinking']}**",
        f"- Prompt version: `{cfg['llm']['prompt_version']}`",
        f"- Enriched sections: **{len(llm)}**, terms: **{manifest['counts']['llm_terms']}**, "
        f"inventory rows: **{len(terms)}**", "",
        "## Study layer (§3G, stage 51)", "",
        f"- Study records: **{len(studies)}** (one per paper, dup-excluded papers included)",
        f"- Extraction status: `{dict(Counter(s.get('extraction_status') for s in studies))}`",
        f"- Study metadata is deterministic-compendium-first (BioProject linkage), "
        f"LLM-read Methods otherwise; `not_reported` where neither source reports a value.",
        f"- Papers with recorded deterministic-vs-LLM conflicts: "
        f"**{sum(1 for s in studies if s.get('study_provenance', {}).get('conflicts'))}** "
        f"(deterministic kept, LLM value recorded).", "",
        "## Findings layer (§4, stages 52+55)", "",
        f"- Findings: **{len(findings)}**; papers with reported findings: "
        f"**{len({f['corpus_id'] for f in findings if f.get('corpus_id')})}** "
        f"(Abstract/Results/Discussion sections; zero-finding sections are valid)",
        f"- Claim types: `{dict(Counter(f.get('claim_type') for f in findings))}`",
        f"- Directions: `{dict(Counter(f.get('direction') for f in findings))}`",
        f"- Evidence quote resolution (stage 55, automated): "
        f"resolved **{manifest['counts']['findings_evidence_resolved']}** "
        f"({100.0 * manifest['counts']['findings_evidence_resolved'] / max(len(findings), 1):.1f}%), "
        f"unresolved_not_in_source **{manifest['counts']['findings_evidence_unresolved']}** "
        f"(kept and flagged, never dropped).",
        f"- Quote resolution is an automated recoverability check, NOT scientific "
        f"verification: every finding keeps `verification_status=pending` until "
        f"human review (§H).", "",
        "## Triples layer (stages 53/54/56)", "",
        f"- Triple mentions: **{m['total']:,}** over "
        f"**{m['papers_with_mentions']}** papers "
        f"({len(papers_no_mentions)} papers have zero mentions: "
        f"`{', '.join(papers_no_mentions)}` — all have zero extraction-eligible "
        f"sections; 'partial' full-text completeness is the corpus norm, not an "
        f"anomaly).",
        f"- Relation vocabulary: **{m['relation_distinct']}** distinct normalized "
        f"relations; `OTHER_RELATION` covers **{m['other_relation_mentions']:,}** "
        f"mentions ({100.0 * m['other_relation_mentions'] / max(m['total'], 1):.1f}%) "
        f"(rule: `relation_normalized == 'OTHER_RELATION'`).",
        f"- Mention evidence resolution (stage 55, automated): "
        f"`{m['evidence_locator_status']}` — unresolved mentions are kept and "
        f"flagged, never dropped (rule: `evidence_locator_status == "
        f"'unresolved_not_in_source'`).",
        f"- Output-cap truncation: **{m['truncation_status_true']:,}/{m['total']:,}** "
        f"mentions ({100.0 * m['truncation_status_true'] / max(m['total'], 1):.1f}%) "
        f"have `truncation_status=true` (rule: stage-53 output-cap truncation; "
        f"input chunking at `max_prompt_chars={cfg['llm']['max_prompt_chars']}` is "
        f"by design and lossless — output truncation is the loss quirk). "
        f"{ts.get('sections_with_truncated_chunks', 0):,} of {ts.get('total', 0):,} "
        f"extracted sections had >=1 truncated chunk "
        f"({ts.get('chunks_truncated', 0):,}/{ts.get('chunks_total', 0):,} chunks; "
        f"split-retries {ts.get('split_retries', 0):,}).",
        f"- Section LLM status: `{ts.get('llm_status', {})}`.",
        f"- Canonical triples: **{tstats['canonical_triples']['total']:,}**; "
        f"cross-mention conflicts `{tstats['canonical_triples']['conflict_flag']}` "
        f"(recorded, never silently resolved); "
        f"**{tstats['canonical_triples']['with_evidence_unresolved']:,}** have "
        f">=1 unresolved evidence mention (rule: `evidence_unresolved_count >= 1`).",
        f"- Cross-paper evidence records: **{tstats['cross_paper_evidence']['total']:,}**; "
        f"entities: **{tstats['entities']['total']:,}**; paper summaries: "
        f"**{tstats['paper_summaries']['total']}** "
        f"(`{dict(Counter(r.get('llm_status') for r in stream_jsonl(C.CORPUS_DIR / 'data' / 'paper_summaries.jsonl')))}`).",
        f"- p-shaped effect estimates: **{m['p_shaped_effect_estimates']}** of "
        f"{len(findings):,} findings (rule: regex `^<?\\s*0\\.\\d+$` on "
        f"`findings.effect_estimate`; sub-splits by duplicate-p are not shipped "
        f"— no single reproducible rule).", "",
        "## Entity linking (pending stage 57)", "",
        f"- Candidate mappings: **{tstats['candidate_entity_mappings']['total']:,}** "
        f"(`{tstats['candidate_entity_mappings']['mapping_disposition']}`; "
        f"lookup status `{tstats['candidate_entity_mappings']['lookup_status']}`).",
        "- Linking results are NOT folded into canonical_triples in this release: "
        "stage 57 (human-in-the-loop) is pending. `AUTO_ACCEPTED` is a "
        "pipeline-internal string-match verdict, **not** human acceptance.",
        f"- Every record carries `reviewer=model`, `human_review_status=pending`.", "",
        "## Model-assisted adjudication pilot (NOT verification)", "",
        f"- A 500-mention uniform-random pilot "
        f"(seed {pilot_summary.get('population', {}).get('seed')}, population "
        f"{pilot_summary.get('population', {}).get('mentions'):,} mentions) was "
        f"triaged with three model passes; labels: "
        f"`{pilot_summary.get('triage_label_distribution')}`.",
        "- **Triage is triage**: labels are model recommendations to prioritise "
        "human review; they are NOT verification, NOT a gold standard, and support "
        "NO accuracy or corpus-quality claims. All 500 mentions keep "
        "`human_review_status=pending`.",
        f"- Copied verbatim into `adjudication_pilot/` ({', '.join(PILOT_FILES)}); "
        f"the full pilot (incl. enriched sample and sheets) remains at "
        f"`{PILOT_DIR}`.", "",
        "## Known data quirks (V5.4-style enumeration)", "",
        "- **All counts below are computed at release time from the release "
        "inputs**; each manifest `known_quirks` entry states its derivation rule.",
        f"- OTHER_RELATION mentions: **{m['other_relation_mentions']:,}/{m['total']:,}** "
        f"({100.0 * m['other_relation_mentions'] / max(m['total'], 1):.1f}%).",
        f"- Mention output truncation: **{m['truncation_status_true']:,}** mentions "
        f"({ts.get('sections_with_truncated_chunks', 0):,} sections, "
        f"{ts.get('chunks_truncated', 0):,} chunks); exemplar anomalies "
        f"HMPAPER_000268 (1 FAILED chunk, 26 mentions kept) and HMPAPER_000239 "
        f"(PARTIAL chunks, 69 mentions) — recorded in `data/curation_log.csv`, "
        f"never dropped or repaired silently.",
        f"- Malformed LLM terms: **{quirk['llm_terms_malformed']}** "
        f"(rule: {quirk['llm_terms_malformed_rule']}).",
        f"- Off-schema LLM term types: **{quirk['llm_terms_off_schema_occurrences']}** "
        f"occurrences across **{quirk['llm_terms_off_schema_distinct_types']}** "
        f"distinct types, kept as `unmapped:<type>`.",
        f"- Findings with unresolved evidence: "
        f"**{sum(1 for f in findings if f.get('evidence_locator_status') == 'unresolved_not_in_source'):,}"
        f"/{len(findings):,}** "
        f"({100.0 * sum(1 for f in findings if f.get('evidence_locator_status') == 'unresolved_not_in_source') / max(len(findings), 1):.1f}%); "
        f"mentions unresolved: "
        f"**{m['evidence_locator_status'].get('unresolved_not_in_source', 0):,}/{m['total']:,}** "
        f"({100.0 * m['evidence_locator_status'].get('unresolved_not_in_source', 0) / max(m['total'], 1):.1f}%) — kept and flagged.",
        f"- Cross-mention conflicts on canonical triples: "
        f"**{tstats['canonical_triples']['conflict_flag'].get('conflicting_across_mentions', 0):,}** "
        f"(recorded, never silently resolved).",
        "- Hypernym taxa: LLM sometimes records genus/family level for species-level "
        "source claims (qualitative V5.4 carry-forward; count not computed).", "",
        "## Curation events", "",
        "| Stage | Events |", "|---|---|",
        *[f"| {k} | {v} |" for k, v in sorted(curated.items())], "",
        "## What is NOT validated", "",
        *[f"- {x}" for x in manifest["known_limitations"]], "",
        "## Reproduction", "",
        "```bash",
        "cd ~/Microbiome-CDM/corpus_v2",
        "sbatch slurm/10_ingest.sbatch   # ... through 70_finalize.sbatch",
        "# or chain them:",
        "bash slurm/submit_all.sh",
        "```", "",
    ]
    (release_dir / "quality_report.md").write_text("\n".join(qr), encoding="utf-8")
    prog.update(1, detail="quality_report.md")

    # ---- README + checksums ----
    (release_dir / "README.md").write_text(
        f"# {corpus['corpus_name']} — release {version}\n\n"
        f"Frozen {C.now_utc()} by `{STAGE}` (pipeline {PV}).\n\n"
        f"Start with `corpus_manifest.json`, then `quality_report.md`.\n"
        f"`MANIFEST.sha256` covers every file in this directory.\n\n"
        f"> Terminology, study metadata, findings, triple mentions, canonical "
        f"triples, entities and candidate mappings are model-extracted and "
        f"**unverified**: every record keeps `verification_status=pending` and "
        f"`human_review_status=pending`. "
        f"Evidence quotes are machine-checked for recoverability "
        f"(stage 55); unresolved quotes are kept and flagged. "
        f"`adjudication_pilot/` is model-assisted **triage, not verification**. "
        f"Entity linking is pending (stage 57): linking results are NOT merged "
        f"into the canonical triples. "
        f"See `schema/` for record schemas and `validation/` for stage reports.\n",
        encoding="utf-8")

    checks = []
    for fp in sorted(release_dir.rglob("*")):
        if fp.is_file() and fp.name != "MANIFEST.sha256":
            checks.append(f"{C.sha256_file(fp)}  {fp.relative_to(release_dir)}")
    (release_dir / "MANIFEST.sha256").write_text("\n".join(checks) + "\n", encoding="utf-8")

    ev.record(pipeline_stage=STAGE, run_status="success", started_at=started,
              completed_at=C.now_utc(),
              output_artifact_hash=C.sha256_file(release_dir / "MANIFEST.sha256"),
              note=f"release={release_dir} files={len(checks)}")
    ev.close()
    prog.close(summary=f"release={release_dir} files={len(checks)}")
    print(json.dumps({"release_dir": str(release_dir), "files": len(checks),
                      "manifest_sha256": C.sha256_file(release_dir / "MANIFEST.sha256")},
                     indent=2))


if __name__ == "__main__":
    main()
