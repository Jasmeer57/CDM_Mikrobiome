#!/usr/bin/env python3
"""Stage 53: LLM extraction of knowledge-graph TRIPLE MENTIONS (template §2/§3)
from all non-boilerplate sections (excludes References/Acknowledgements and
container sections; Methods included for MEASURED_BY/DETECTED_BY coverage).

Runs INSIDE the A100 Slurm job that also serves the model (localhost). The job
may shard work across 2 GPUs: SHARD_COUNT/SHARD_INDEX env vars split sections
by stable sha256(section_record_id) % SHARD_COUNT; each shard gets its own
checkpoint and section-output file, then `--merge` (still inside the job,
CPU-only) reassembles, verifies quotes and assigns mention IDs.

LLM emits a COMPACT content record (subject/predicate/object mentions, domains,
enums, context, verbatim source sentence, verbatim statistics). Everything
else in the master triple record (§A ids, §F provenance, §I extraction
metadata, §J automated checks) is stamped deterministically by this code.
Canonical/§K aggregation is a separate later stage (56).

Null vocabulary (never blank, never invented):
- not_reported : the source text does not state a value
- unavailable   : not derivable in this build (segmented-markdown source has
                  no character offsets; sentence/paragraph ids)
- unresolved    : entity linking is string-normalization only in v1
- pending       : human review is the verification gate (like stage 52)

Outputs (final, after --merge)
  data/triples_sections.jsonl   one record per processed section
  data/triple_mentions.jsonl    flat records, one per triple mention
  validation/triples_extraction_report.json
"""
import json
import os
import re
import sys
import threading
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import pipeline.common as C
import pipeline.llmio

STAGE = "stage53_triples_extract"
PV = "2.1.0"
NR = "not_reported"
UNAVAIL = "unavailable"
UNRES = "unresolved"
PENDING = "pending"

SCHEMA_DIR = C.CORPUS_DIR / "schema"

EXCLUDED_TYPES = {"References", "Acknowledgements"}

POLARITIES = {"POSITIVE", "NEGATIVE", "UNKNOWN"}
ASSERTIONS = {"ASSERTED", "NEGATED", "UNCERTAIN"}
CAUSALS = {"CAUSAL", "ASSOCIATIONAL", "NOT_ESTABLISHED"}
CLAIM_BASIS = {"reported_result", "author_interpretation",
               "hypothesis", "speculation", "unclear"}

DOMAIN_RE = re.compile(r"^D(0[1-9]|1[0-9]|2[0-5])$")

# predicates that imply a direction of change (for the §H effect_direction)
DIRECTION_BY_PREDICATE = {
    "INCREASED_IN": "increased", "MORE_ABUNDANT_THAN": "increased",
    "INCREASES_RISK_OF": "increased", "INCREASES_OVER_TIME": "increased",
    "UPREGULATES": "increased", "EXACERBATES": "increased",
    "DECREASED_IN": "decreased", "LESS_ABUNDANT_THAN": "decreased",
    "DECREASES_OVER_TIME": "decreased", "DOWNREGULATES": "decreased",
    "ALLEVIATES": "decreased", "PROTECTIVE_AGAINST": "decreased",
}


def load_vocab():
    """Load the FROZEN relation schema + domain taxonomy. Returns
    (predicates, predicate_meta, domains_dict, entity_types_list)."""
    rel = json.loads((SCHEMA_DIR / "triple_relation_schema.json").read_text())
    dom = json.loads((SCHEMA_DIR / "triple_domains.json").read_text())
    return (set(rel["predicate_index"]), rel["predicate_index"],
            dom["domains"], dom["entity_types"])


def build_prompt_template(vocab):
    """Generate the prompt base with the EXACT frozen predicate list (grouped
    by family), domain list and entity-type enum substituted straight from the
    schema files, so the prompt can never drift from the frozen vocabularies.
    Uses token replacement (no .format) so the JSON skeleton braces stay
    literal for the second .format at chunk time."""
    _, pmeta, domains, etypes = vocab
    by_fam = defaultdict(list)
    for p, m in pmeta.items():          # dict order preserved: schema order
        by_fam[m["family"]].append(p)
    fam_lines = []
    for fam, plist in by_fam.items():
        fam_lines.append(f"- {fam}: " + " ".join(plist))
    dom_lines = "\n".join(f"  {d} {domains[d]['label']},"
                          for d in sorted(domains))
    type_line = " | ".join(etypes)
    out = PROMPT_TEMPLATE
    out = out.replace("@@PREDICATES@@", "\n".join(fam_lines))
    out = out.replace("@@DOMAINS@@", dom_lines)
    out = out.replace("@@ENTITY_TYPES@@", type_line)
    return out


PROMPT_TEMPLATE = """You extract knowledge-graph TRIPLES from one section of a human-microbiome paper.
Extract every explicitly supported, scientifically meaningful subject-predicate-object relationship. Include NEGATED, UNCERTAIN, null and contradictory relationships - do not keep only positive findings.
If the section states no relationships, return an empty list.

CANONICAL PREDICATES (copy exactly; use ONLY these; if none fits, use OTHER_RELATION):
@@PREDICATES@@

ENTITY DOMAINS for subject_domain/object_domain:
@@DOMAINS@@

entity_type enum (subject_entity_type / object_entity_type):
@@ENTITY_TYPES@@

For each triple return STRICT JSON (no markdown, no commentary) with exactly these keys:
{{
  "triples": [
    {{
      "subject_mention": "entity EXACTLY as worded in the text",
      "subject_entity_type": "from the entity_type enum",
      "subject_domain": "D01-D25",
      "predicate": "one CANONICAL PREDICATE above",
      "relation_mention": "how the relationship is worded in the text (short phrase), or the predicate name",
      "object_mention": "entity EXACTLY as worded in the text",
      "object_entity_type": "from the entity_type enum",
      "object_domain": "D01-D25",
      "body_site": "body site as worded, or not_reported",
      "population_subgroup": "population/subgroup, or not_reported",
      "study_design": "study design mentioned here, or not_reported",
      "intervention_or_exposure": "exposure/intervention, or not_reported",
      "comparator": "comparison group/baseline, or not_reported",
      "timepoint": "timepoint/period, or not_reported",
      "polarity": "POSITIVE|NEGATIVE|UNKNOWN",
      "assertion_status": "ASSERTED|NEGATED|UNCERTAIN",
      "causal_status": "CAUSAL|ASSOCIATIONAL|NOT_ESTABLISHED",
      "claim_basis": "reported_result|author_interpretation|hypothesis|speculation",
      "effect_measure_type": "measure as stated (odds ratio, log2foldchange...), or not_reported",
      "effect_measure_value": "numeric value VERBATIM from text, or not_reported",
      "confidence_interval": "verbatim, or not_reported",
      "p_value": "verbatim, or not_reported",
      "adjusted_p_value": "verbatim, or not_reported",
      "sample_size": "n as stated for this analysis, or not_reported",
      "source_sentence": "short VERBATIM quote from the text supporting this triple (at most 50 words, exact wording, no paraphrase)"
    }}
  ]
}}

Rules:
- subject -> predicate -> object order is canonical; NEVER reverse a causal or regulatory relationship.
- Do not convert observational associations into causal predicates; use ASSOCIATED_WITH unless the text explicitly states causation.
- INCREASED_IN / DECREASED_IN / MORE_ABUNDANT_THAN / LESS_ABUNDANT_THAN need a comparator: put it in "comparator".
- source_sentence MUST be copied word-for-word from the text provided below; the corpus verifies it and drops nothing silently.
- NEVER invent or compute a statistic; unreported numeric fields are not_reported.
- Only use the text provided. If a relationship is not explicitly supported, do not emit it.

Section "{section_name}" ({section_type}) of "{title}":
{chunk}"""


def sanitize_triple(fd, vocab):
    """Coerce one LLM triple dict into the corpus vocabulary; unknown enums and
    predicates are kept visible (relation_mention preserved, normalized to
    OTHER_RELATION), never silently dropped."""
    preds, pmeta, domains, etypes = vocab
    issues = []

    def ent(kind):
        v = " ".join(str(fd.get(f"{kind}_mention") or "").split())
        t = " ".join(str(fd.get(f"{kind}_entity_type") or "").split())
        if t and t not in etypes:
            issues.append(f"{kind}_entity_type:{t}")
            t = "other_unclassified"
        d = " ".join(str(fd.get(f"{kind}_domain") or "").split()).upper()
        if not DOMAIN_RE.match(d or ""):
            issues.append(f"{kind}_domain:{d}")
            d = "D25"
        return v, t or "other_unclassified", d

    s_mention, s_type, s_dom = ent("subject")
    o_mention, o_type, o_dom = ent("object")
    if not s_mention:
        issues.append("subject_mention_missing")
    if not o_mention:
        issues.append("object_mention_missing")

    rel_raw = " ".join(str(fd.get("predicate") or "").split()).upper()
    if rel_raw in preds:
        rel_norm = rel_raw
    else:
        issues.append(f"predicate:{rel_raw}")
        rel_norm = "OTHER_RELATION"
        if not rel_raw:
            rel_raw = NR
    rel_mention = " ".join(str(fd.get("relation_mention") or "").split())
    if not rel_mention or rel_mention.lower() == "not_reported":
        rel_mention = rel_norm

    def enum(key, valid, fallback):
        v = " ".join(str(fd.get(key) or "").split()).upper()
        if v not in valid:
            if v:
                issues.append(f"{key}:{v}")
            return fallback
        return v

    polarity = enum("polarity", POLARITIES, "UNKNOWN")
    assertion = enum("assertion_status", ASSERTIONS, "UNCERTAIN")
    causal = enum("causal_status", CAUSALS, "NOT_ESTABLISHED")
    cb = " ".join(str(fd.get("claim_basis") or "").split())
    if cb not in CLAIM_BASIS:
        issues.append(f"claim_basis:{cb}")
        cb = "unclear"

    out = {
        "subject_mention": s_mention or NR,
        "subject_entity_type": s_type,
        "subject_domain": s_dom,
        "relation_mention": rel_mention,
        "relation_normalized": rel_norm,
        "object_mention": o_mention or NR,
        "object_entity_type": o_type,
        "object_domain": o_dom,
        "polarity": polarity, "assertion_status": assertion,
        "causal_status": causal, "claim_basis": cb,
    }
    for k in ("body_site", "population_subgroup", "study_design",
              "intervention_or_exposure", "comparator", "timepoint",
              "effect_measure_type", "effect_measure_value",
              "confidence_interval", "p_value", "adjusted_p_value",
              "sample_size"):
        v = " ".join(str(fd.get(k) or "").split())
        out[k] = v if v else NR
    ev = " ".join(str(fd.get("source_sentence") or "").split())
    out["source_sentence"] = ev
    out["_invalid_source_sentence"] = not ev or ev.lower() == NR
    out["_enum_issues"] = issues
    return out


def enrich_section(sec, cfg, port, vocab, prompt_tpl):
    """Extract triples from one section; return the section-level record
    (same envelope semantics as stage 52: llm_status, chunks, split retries)."""
    out = {
        "paper_id": sec["paper_id"],
        "section_record_id": sec["section_record_id"],
        "section_type": sec.get("section_type"),
        "section_order": sec.get("section_order"),
        "llm_model": cfg["llm"]["model_label"],
        "llm_model_version": f"vllm:{cfg['llm']['runtime']}",
        "llm_prompt_version": cfg["llm"]["triples_prompt_version"],
        "llm_source_text_hash": sec.get("text_hash_sha256"),
        "llm_status": "FAILED", "triples_raw": [], "llm_error": None,
        "llm_chunks": 0, "llm_chunks_failed": 0, "llm_chunks_truncated": 0,
        "llm_split_retries": 0, "llm_input_chars": 0, "llm_degrees": [],
    }
    text = sec.get("section_text_original") or ""
    if not text.strip():
        out["llm_status"] = "COMPLETE"   # empty section: vacuously no triples
        return out
    chunks = C.chunk_text(text, cfg["llm"]["max_prompt_chars"])

    def build_prompt(chunk):
        return prompt_tpl.format(
            section_name=sec.get("section_name_original") or "section",
            section_type=sec.get("section_type") or "",
            title=sec.get("paper_title") or "untitled",
            chunk=chunk)

    extract = llmio.make_extractor(cfg, port, out, build_prompt)

    statuses, all_tris = [], []
    for ci, chunk in enumerate(chunks):
        out["llm_input_chars"] += len(chunk)
        try:
            data, status, err = extract(chunk, ci, 0)
            tris = None
            if status != "FAILED" and isinstance(data, dict):
                raw = data.get("triples")
                tris = raw if isinstance(raw, list) else []
            if status == "COMPLETE" and tris is None:
                status, err = "FAILED", "triples key missing from response"
            if tris is not None:
                for td in tris:
                    if isinstance(td, dict):
                        t = sanitize_triple(td, vocab)
                        t["chunk"] = ci
                        all_tris.append(t)
            statuses.append(status)
            if status != "COMPLETE":
                out["llm_error"] = ((out["llm_error"] + "; ") if out["llm_error"]
                                    else "") + f"chunk{ci}:{err}"
                if status == "PARTIAL":
                    out["llm_chunks_truncated"] += 1
                else:
                    out["llm_chunks_failed"] += 1
            out["llm_chunks"] += 1
        except Exception as e:  # noqa: BLE001
            statuses.append("FAILED")
            out["llm_chunks_failed"] += 1
            out["llm_chunks"] += 1
            out["llm_error"] = ((out["llm_error"] + "; ") if out["llm_error"]
                                else "") + f"chunk{ci}:{e}"

    if all(s == "COMPLETE" for s in statuses):
        out["llm_status"] = "COMPLETE"
    elif any(s == "COMPLETE" for s in statuses) or all_tris:
        out["llm_status"] = "PARTIAL"
    else:
        out["llm_status"] = "FAILED"
    out["triples_raw"] = all_tris
    return out


def select_sections(sections):
    """Stage-53 eligibility: every non-boilerplate, non-container section.
    Container sections are excluded because their text duplicates their
    children (deterministic double-extraction guard)."""
    eligible = []
    excluded = Counter()
    for s in sections:
        st = s.get("section_type")
        if not (s.get("section_text_original") or "").strip():
            excluded["empty_text"] += 1
        elif st in EXCLUDED_TYPES:
            excluded[st] += 1
        elif s.get("is_container_section"):
            excluded["container_section"] += 1
        else:
            eligible.append(s)
    return eligible, excluded


def shard_of(sid, n):
    return int(C.sha256_text(sid)[:8], 16) % n


# ---------------- merge (CPU, deterministic, fail-closed) ----------------

def _collapse(s):
    return re.sub(r"\s+", " ", s or "")


def _alnum_norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def verify_quote(quote, section_text):
    """Fail-closed quote verification against the section text. The
    segmented-markdown source has no character offsets, so this build never
    claims them: verified via whitespace-collapsed substring (exact) or
    alphanumeric-collapsed substring (normalized), else unresolved."""
    q = _collapse(quote)
    ct = _collapse(section_text)
    if not q:
        return "unavailable_empty_quote", False, False
    if q in ct:
        return "verified_exact", False, False
    qa, ta = _alnum_norm(q), _alnum_norm(ct)
    if qa and qa in ta:
        return "verified_normalized", False, False
    return "unresolved_not_in_source", False, False


def merge_only(cfg, vocab):
    """Reassemble shard outputs, verify quotes, assign IDs, write final
    artifacts. Fails closed on missing shard files, coverage gaps or
    fingerprint drift."""
    preds, pmeta, _, _ = vocab
    sections = C.read_jsonl(C.CORPUS_DIR / "data" / "sections.jsonl")
    papers = {p["paper_id"]: p for p in
              C.read_jsonl(C.CORPUS_DIR / "data" / "papers.jsonl")}
    eligible, excluded = select_sections(sections)
    n_shards = int(os.environ.get("SHARD_COUNT", "1"))
    expected_shard = {s["section_record_id"]:
                      shard_of(s["section_record_id"], n_shards)
                      for s in eligible}

    section_recs = []
    for i in range(n_shards):
        p = (C.CORPUS_DIR / "data" /
             ("triples_sections.jsonl" if n_shards == 1
              else f"triples_sections.shard{i}.jsonl"))
        if not p.exists():
            sys.exit(f"ERROR: missing shard output {p}")
        recs = C.read_jsonl(p)
        for r in recs:
            if expected_shard.get(r["section_record_id"]) != i:
                sys.exit(f"ERROR: section {r['section_record_id']} found in "
                         f"shard {i} but belongs to shard "
                         f"{expected_shard.get(r['section_record_id'])} "
                         f"(sharding drift)")
        section_recs.extend(recs)
    if len({r["section_record_id"] for r in section_recs}) != len(section_recs):
        sys.exit("ERROR: duplicate section records across shards")

    by_sid = {r["section_record_id"]: r for r in section_recs}
    missing = [s["section_record_id"] for s in eligible
               if s["section_record_id"] not in by_sid]
    if missing:
        sys.exit(f"ERROR: {len(missing)} eligible sections not covered by "
                 f"shard outputs, e.g. {missing[:5]}")

    covered_sorted = sorted(
        eligible, key=lambda s: (s["paper_id"], s.get("section_order") or 0))

    # ---- assemble flat mentions -------------------------------
    mentions = []
    per_paper = defaultdict(int)
    quote_status_count = Counter()
    mentions_by_section = Counter()
    for s in covered_sorted:
        r = by_sid[s["section_record_id"]]
        p = papers.get(s["paper_id"], {})
        collapsed = _collapse(s.get("section_text_original") or "")
        mentions_by_section[s["section_record_id"]] = 0
        for td in r.get("triples_raw") or []:
            pid = s["paper_id"]
            per_paper[pid] += 1
            mentions_by_section[s["section_record_id"]] += 1
            sent = _collapse(td.get("source_sentence") or "")
            loc_status = verify_quote(td.get("source_sentence"), collapsed)[0]
            quote_status_count[loc_status] += 1
            sub_g = ("mentioned_in_source_sentence"
                     if _collapse(td["subject_mention"]).lower()
                     in collapsed.lower()
                     else "not_found_in_sentence_flagged")
            obj_g = ("mentioned_in_source_sentence"
                     if _collapse(td["object_mention"]).lower()
                     in collapsed.lower()
                     else "not_found_in_sentence_flagged")
            issues = list(td.get("_enum_issues") or [])
            if loc_status == "unresolved_not_in_source":
                issues.append("source_sentence_not_found_in_section")
            if td.get("_invalid_source_sentence"):
                issues.append("source_sentence_missing")
            meta = pmeta.get(td["relation_normalized"], {})
            has_stats = any(td.get(k) != NR for k in
                            ("effect_measure_value", "confidence_interval",
                             "p_value", "adjusted_p_value", "sample_size"))
            rec = {
                # A. identification
                "triple_mention_id": f"{pid}_TRI_{per_paper[pid]:04d}",
                "canonical_triple_id": "pending_stage56",
                "graph_id": cfg["corpus"]["corpus_id"],
                "graph_version": PV,
                "extraction_run_id": f"{STAGE}@{PV}",
                "record_status": "active",
                "duplicate_group_id": "pending_stage56",
                # B. subject
                "subject_mention": td["subject_mention"],
                "subject_normalized_label":
                    _collapse(td["subject_mention"]).lower(),
                "subject_entity_id": UNRES,
                "subject_entity_type": td["subject_entity_type"],
                "subject_domain": td["subject_domain"],
                "subject_taxonomy_id": NR,
                "subject_ontology_id": UNRES,
                "subject_semantic_type": None,
                "subject_organism": NR, "subject_strain": NR,
                "subject_gene_or_protein_id": NR, "subject_abbreviation": NR,
                "subject_entity_resolution_status":
                    "unresolved_string_match_v1",
                # C. predicate
                "relation_mention": td["relation_mention"],
                "relation_normalized": td["relation_normalized"],
                "relation_id":
                    f"HMCV2-REL-v1:{td['relation_normalized']}",
                "relation_family": meta.get("family", "escape"),
                "relation_direction": "subject_to_object",
                "relation_evidence_type": "textual_mention",
                "relation_is_symmetric": bool(meta.get("is_symmetric")),
                "relation_is_causal": bool(meta.get("is_causal")),
                "relation_is_negatable": bool(meta.get("is_negatable")),
                "relation_schema_version": "v2-triple-relations-1",
                # D. object
                "object_mention": td["object_mention"],
                "object_normalized_label":
                    _collapse(td["object_mention"]).lower(),
                "object_entity_id": UNRES,
                "object_entity_type": td["object_entity_type"],
                "object_domain": td["object_domain"],
                "object_taxonomy_id": NR,
                "object_ontology_id": UNRES,
                "object_semantic_type": None,
                "object_organism": NR, "object_strain": NR,
                "object_gene_or_protein_id": NR, "object_abbreviation": NR,
                "object_entity_resolution_status":
                    "unresolved_string_match_v1",
                # E. context
                "body_site": td["body_site"], "anatomical_detail": NR,
                "host_species": NR,
                "host_population": td["population_subgroup"],
                "host_age_group": NR, "host_sex_as_reported": NR,
                "disease_or_health_status": NR,
                "sample_type": NR, "microbiome_compartment": NR,
                "study_design": td["study_design"],
                "intervention_or_exposure": td["intervention_or_exposure"],
                "comparator": td["comparator"],
                "experimental_condition": NR,
                "timepoint": td["timepoint"],
                "geography_if_relevant": NR,
                "context_scope": "as_extracted_from_single_section",
                "context_source_status": "llm_extracted_unverified",
                # F. evidence + provenance
                "paper_id": pid,
                "PMID": p.get("PMID") or NR,
                "PMCID": p.get("PMCID") or NR,
                "DOI": p.get("DOI") or NR,
                "paper_title": p.get("title") or "untitled",
                "section_id": s["section_record_id"],
                "section_name": s.get("section_name_original") or NR,
                "subsection_name": NR,
                "paragraph_id": UNAVAIL, "sentence_id": UNAVAIL,
                "source_sentence": td["source_sentence"],
                "source_character_start": UNAVAIL,
                "source_character_end": UNAVAIL,
                "source_chunk_index": td.get("chunk", 0),
                "source_file_id": s.get("source_location") or NR,
                "source_text_hash": s.get("text_hash_sha256"),
                "segment_ids": s.get("segment_ids") or [],
                "evidence_locator_type": "section",
                "evidence_locator":
                    f"section:{s['section_record_id']}",
                "evidence_locator_status": loc_status,
                "evidence_type": "textual_mention",
                "evidence_completeness_status": (
                    "complete_section_processed"
                    if r.get("llm_status") == "COMPLETE"
                    else "partial_section"),
                # G. polarity/modality/interpretation
                "polarity": td["polarity"],
                "assertion_status": td["assertion_status"],
                "epistemic_modality": td["claim_basis"],
                "causal_status": td["causal_status"],
                "temporality": NR,
                "directionality": "subject_to_object",
                "hypothetical_status": (
                    "hypothetical"
                    if td["claim_basis"] in ("hypothesis", "speculation")
                    else "not_hypothetical"),
                "conditional_status": "not_reported_in_sentence",
                "speculation_status": td["claim_basis"],
                "author_hedging": "not_captured_v1",
                "reported_or_observed": td["claim_basis"],
                "finding_status": "extracted_mention",
                "interpretation_notes": NR,
                # H. quantitative
                "effect_measure_type": td["effect_measure_type"],
                "effect_measure_value": td["effect_measure_value"],
                "effect_measure_unit": NR,
                "confidence_interval": td["confidence_interval"],
                "p_value": td["p_value"],
                "adjusted_p_value": td["adjusted_p_value"],
                "sample_size": td["sample_size"],
                "group_sizes": NR, "relative_abundance": NR,
                "absolute_abundance": NR, "fold_change": NR,
                "effect_direction": DIRECTION_BY_PREDICATE.get(
                    td["relation_normalized"], "not_applicable"),
                "statistical_significance_as_reported": NR,
                "quantitative_evidence_source": "verbatim_from_source_sentence",
                "quantitative_extraction_status": (
                    "verbatim_only" if has_stats
                    else "no_statistics_reported"),
                # I. extraction provenance
                "extraction_model_provider": "vllm-local",
                "extraction_model_name": cfg["llm"]["model_label"],
                "extraction_model_version":
                    f"vllm:{cfg['llm']['runtime']}",
                "prompt_id": "HMCV2-TRIPLES-PROMPT",
                "prompt_version": cfg["llm"]["triples_prompt_version"],
                "input_section_id": s["section_record_id"],
                "input_text_hash": s.get("text_hash_sha256"),
                "expected_input_length": s.get("character_count"),
                "processed_input_length": r.get("llm_input_chars")
                                          or 0,
                "coverage_status": {"COMPLETE": "complete",
                                    "PARTIAL": "partial",
                                    "FAILED": "incomplete"}[
                                        r.get("llm_status")],
                "truncation_status": bool(r.get("llm_chunks_truncated")),
                "extraction_timestamp": C.now_utc(),
                "extraction_method": "automated",
                "entity_linking_method": "string_normalization_v1",
                "relation_normalization_method": "vocabulary_lookup_v1",
                # J. confidence + validation
                "model_reported_confidence": NR,
                "entity_linking_confidence": NR,
                "relation_classification_confidence": NR,
                "evidence_support_status": loc_status,
                "subject_grounding_status": sub_g,
                "predicate_grounding_status": (
                    "canonical_vocabulary"
                    if td["relation_normalized"] in preds
                    else "normalized_to_escape"),
                "object_grounding_status": obj_g,
                "directionality_validation_status": "not_auto_validated",
                "polarity_validation_status": "not_auto_validated",
                "duplicate_validation_status": "pending_stage56",
                "ontology_validation_status": "skipped_v1",
                "automated_validation_status": (
                    "checks_passed" if not issues
                    else "flagged_needs_review"),
                "human_review_status": PENDING,
                "verification_status": PENDING,
                "reviewer": None, "review_timestamp": None,
                "error_category": issues or None,
                "correction_or_rejection_reason": None,
                "reviewer_notes": None,
                # L. disposition
                "triple_quality_status": (
                    "automated_checks_passed" if not issues
                    else "flagged_needs_review"),
                "inclusion_status": "included_v1",
                "exclusion_reason": None,
                "publication_readiness": "pending_human_review",
                "unresolved_issues": issues or None,
            }
            mentions.append(rec)

    C.write_jsonl(C.CORPUS_DIR / "data" / "triples_sections.jsonl",
                  [by_sid[s["section_record_id"]] for s in covered_sorted])
    C.write_jsonl(C.CORPUS_DIR / "data" / "triple_mentions.jsonl", mentions)

    st = Counter(r.get("llm_status") for r in section_recs)
    report = {
        "stage": STAGE, "pipeline_version": PV, "generated_at": C.now_utc(),
        "shards": n_shards,
        "sections_total": len(sections),
        "sections_eligible_for_triples": len(eligible),
        "sections_processed": len(section_recs),
        "sections_not_covered": len(missing),
        "exclusion_counts": dict(excluded),
        "section_status_counts": dict(st),
        "sections_with_zero_triples": sum(
            1 for r in section_recs if not r.get("triples_raw")),
        "mentions_total": len(mentions),
        "papers_with_mentions": len({m["paper_id"] for m in mentions}),
        "mentions_per_section_dist": dict(mentions_by_section and
                                          Counter(mentions_by_section.values())),
        "quote_verification_counts": dict(quote_status_count),
        "predicate_counts": dict(Counter(
            m["relation_normalized"] for m in mentions)),
        "relation_family_counts": dict(Counter(
            m["relation_family"] for m in mentions)),
        "subject_domain_counts": dict(Counter(
            m["subject_domain"] for m in mentions)),
        "object_domain_counts": dict(Counter(
            m["object_domain"] for m in mentions)),
        "polarity_counts": dict(Counter(
            m["polarity"] for m in mentions)),
        "assertion_status_counts": dict(Counter(
            m["assertion_status"] for m in mentions)),
        "causal_status_counts": dict(Counter(
            m["causal_status"] for m in mentions)),
        "mentions_with_flags": sum(
            1 for m in mentions if m.get("unresolved_issues")),
        "model": cfg["llm"]["model"], "model_label": cfg["llm"]["model_label"],
        "prompt_version": cfg["llm"]["triples_prompt_version"],
        "thinking": cfg["llm"]["thinking"],
        "relation_schema": "v2-triple-relations-1",
        "domain_taxonomy": "v2-triple-domains-1",
        "reconciliation": {
            "eligible_equals_processed":
                len(eligible) == len(section_recs),
            "mentions_sum_matches": len(mentions) == sum(
                len(r.get("triples_raw") or []) for r in section_recs),
            "ids_unique": len({m["triple_mention_id"]
                               for m in mentions}) == len(mentions),
        },
    }
    C.atomic_write_json(
        C.CORPUS_DIR / "validation" / "triples_extraction_report.json",
        report)
    return report


def main():
    C.require_slurm(STAGE)
    if "--merge" in sys.argv:
        cfg = C.load_config()
        report = merge_only(cfg, load_vocab())
        ev = C.Events(cfg["corpus"]["corpus_id"], f"{STAGE}-merge", PV)
        ev.record(pipeline_stage=f"{STAGE}-merge",
                  run_status="success" if report["reconciliation"][
                      "eligible_equals_processed"] else "partial",
                  note=f"mentions={report['mentions_total']} "
                       f"sections={report['sections_processed']}")
        ev.close()
        print(json.dumps(report, indent=2))
        return

    cfg = C.load_config()
    if cfg["llm"].get("thinking") is not False:
        sys.exit("ERROR: llm.thinking must be false for this corpus build")
    port = int(os.environ.get("VLLM_PORT", "8000"))
    shard_n = int(os.environ.get("SHARD_COUNT", "1"))
    shard_i = int(os.environ.get("SHARD_INDEX", "0"))
    if not (0 <= shard_i < max(shard_n, 1)):
        sys.exit(f"ERROR: SHARD_INDEX {shard_i} out of range")

    vocab = load_vocab()
    prompt_tpl = build_prompt_template(vocab)
    sections = C.read_jsonl(C.CORPUS_DIR / "data" / "sections.jsonl")
    if not sections:
        sys.exit("ERROR: data/sections.jsonl missing")
    titles = {p["paper_id"]: p.get("title") for p in
              C.read_jsonl(C.CORPUS_DIR / "data" / "papers.jsonl")}
    eligible, excluded = select_sections(sections)
    mine = [s for s in eligible
            if shard_of(s["section_record_id"], shard_n) == shard_i]

    suffix = "" if shard_n == 1 else f".shard{shard_i}"
    ckpt = C.Checkpoint(
        C.CORPUS_DIR / "checkpoints" / f"{STAGE}{suffix}.jsonl",
        key="section_record_id")

    def llm_fingerprint(s: dict) -> str:
        return C.sha256_text("|".join([
            str(s.get("text_hash_sha256")),
            cfg["llm"]["model"],
            cfg["llm"]["triples_prompt_version"],
            str(cfg["llm"]["max_prompt_chars"]),
            str(cfg["llm"]["max_tokens"]),
        ]))

    fp_by_sid = {s["section_record_id"]: llm_fingerprint(s) for s in eligible}

    def usable(sid):
        if not ckpt.has(sid, fp_by_sid[sid]):
            return False
        return ckpt.done[sid].get("llm_status") == "COMPLETE"

    pending = [s for s in mine if not usable(s["section_record_id"])]
    workers = int(os.environ.get(
        "WORKERS", str(cfg["llm"].get("workers_a100",
                                      cfg["llm"]["workers"]))))
    prog = C.Progress(STAGE, total=len(mine), unit="section", desc="triples")
    prog.count = len(mine) - len(pending)
    if prog.bar is not None:
        prog.bar.update(prog.count)
        prog.bar.refresh()
    prog.log(f"shard {shard_i}/{shard_n} eligible={len(eligible)} "
             f"mine={len(mine)} resumed={prog.count} pending={len(pending)} "
             f"model={cfg['llm']['model']} workers={workers}")

    if not llmio.wait_for_server(port, prog):
        prog.close(summary="FAILED: server not ready")
        sys.exit(1)

    ev = C.Events(cfg["corpus"]["corpus_id"],
                  STAGE if shard_n == 1 else f"{STAGE}-s{shard_i}", PV)
    cur = C.CurationLog()
    lock = threading.Lock()
    started = C.now_utc()

    def work(sec):
        sec = dict(sec)
        sec["paper_title"] = titles.get(sec["paper_id"])
        try:
            return enrich_section(sec, cfg, port, vocab, prompt_tpl)
        except Exception as e:  # noqa: BLE001
            return {"paper_id": sec["paper_id"],
                    "section_record_id": sec["section_record_id"],
                    "llm_status": "FAILED", "llm_error": f"worker: {e!r}",
                    "triples_raw": [], "llm_chunks": 0,
                    "llm_chunks_failed": 1, "llm_chunks_truncated": 0,
                    "llm_input_chars": 0,
                    "llm_model": cfg["llm"]["model_label"],
                    "llm_model_version": "vllm",
                    "llm_prompt_version":
                        cfg["llm"]["triples_prompt_version"]}

    if pending:
        with ThreadPoolExecutor(workers) as ex:
            futs = {ex.submit(work, s): s for s in pending}
            for fut in as_completed(futs):
                r = fut.result()
                ckpt.add(r, fingerprint=fp_by_sid[r["section_record_id"]])
                with lock:
                    prog.update(1, detail=(
                        f"{r['section_record_id']} {r['llm_status']} "
                        f"tris={len(r.get('triples_raw') or [])}"))
                    if r["llm_status"] != "COMPLETE":
                        cur.add(r["paper_id"], STAGE,
                                cfg["llm"]["model_label"], PV,
                                "triple extraction", r["llm_status"],
                                problem=str(r.get("llm_error"))[:300],
                                resolution="section kept with status; "
                                           "resumable via checkpoint")
    ckpt.close()

    results = [ckpt.done[s["section_record_id"]] for s in mine
               if s["section_record_id"] in ckpt.done]
    C.write_jsonl(C.CORPUS_DIR / "data" / f"triples_sections{suffix}.jsonl",
                  results)
    n_com = sum(1 for r in results if r.get("llm_status") == "COMPLETE")
    n_par = sum(1 for r in results if r.get("llm_status") == "PARTIAL")
    n_fail = sum(1 for r in results if r.get("llm_status") == "FAILED")
    n_tri = sum(len(r.get("triples_raw") or []) for r in results)
    ev.record(pipeline_stage=STAGE,
              run_status="success" if not n_fail else "partial",
              model_name_version=cfg["llm"]["model_label"],
              prompt_version=cfg["llm"]["triples_prompt_version"],
              started_at=started, completed_at=C.now_utc(),
              note=f"shard {shard_i}/{shard_n} triples={n_tri} "
                   f"sections={len(results)} complete={n_com} "
                   f"partial={n_par} failed={n_fail}")
    ev.close()
    prog.close(summary=f"shard{shard_i} triples={n_tri} complete={n_com} "
                       f"partial={n_par} failed={n_fail}")
    print(json.dumps({"shard": shard_i, "sections": len(results),
                      "complete": n_com, "partial": n_par, "failed": n_fail,
                      "triples": n_tri}, indent=2))


if __name__ == "__main__":
    main()
