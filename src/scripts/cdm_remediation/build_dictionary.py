"""Column-level data dictionary for a CDM build, generated from the actual database (read-only).

Every column of every table gets: observed SQLite storage types, documented type and allowed values (catalogue
JSON schema), observed values (when few), null share, key role, source stage, provenance requirement, an
example, and a definition WITH ITS SOURCE. A definition is only given when a source states it:
  SCHEMA_DESCRIPTION   description in a JSON schema (catalogue schema, corpus_v2 schemas)
  CROSSWALK            docs/cdm_design/cdm_field_crosswalk.md row for the field
  CODE                 the code that creates the column states its meaning (file cited); curated below for the
                       columns created by the CDM builder, the gap stages, the review and the 3.0.3 migration
Otherwise the definition is empty and definition_status = NEEDS_EXPERT_REVIEW. Meanings are never inferred from
column names.

    python build_dictionary.py --db <cdm.db> --out <folder>
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import re
import sqlite3
from collections import defaultdict
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
CAT_SCHEMA = ROOT / "src/template/data_catalogue/human_microbiome_data_catalogue.schema.json"
CROSSWALK = ROOT / "docs/cdm_design/cdm_field_crosswalk.md"
SOURCE_TEXT = {"section_text_original", "evidence_text", "evidence_span", "supporting_sentence", "supporting_passage",
               "finding_text", "source_sentence", "definition_text", "abstract", "author_interpretation", "title",
               "population_description", "inclusion_criteria", "exclusion_criteria", "stored_quote", "gap_evidence",
               "notes", "description", "dataset_description", "evidence_location", "merged_evidence"}
CAT_DEF = {"cohort": "cohort", "sample": "sample", "assay": "assay", "dataset": "dataset", "data_asset": "asset",
           "claim": "finding", "paper": "paper"}
B = "src/scripts/vllm_termpop/build_cdm_v3.py"
G = "src/scripts/vllm_termpop/gap_stages.py"
MIG = "src/scripts/cdm_remediation/migrate_303.py"
ANCHOR = ("how the record's quote was located in its section: EXACT (quote == section_text[start:end]), WHITESPACE "
          "(offsets right, spacing differs), RELOCATED (same text elsewhere in the section), NORMALISED (matches ignoring "
          "punctuation/Unicode), FUZZY (>= 90% of characters align within 1.5x the quote length; approximate span), "
          "UNANCHORED (not found), NO_EVIDENCE (no quote), NO_SECTION")
CODE = {  # (table or '*', column) -> (definition, code reference)
    ("*", "evidence_anchor_status"): (ANCHOR, f"{B} anchor_span()"),
    ("*", "evidence_span_start"): ("start offset of the located quote in section_text_original (null if not located)", f"{B} anchored()"),
    ("*", "evidence_span_end"): ("end offset of the located quote in section_text_original (null if not located)", f"{B} anchored()"),
    ("*", "evidence_span"): ("exact source text section_text_original[evidence_span_start:evidence_span_end]; the stored quote is kept unchanged in evidence_text", f"{B} anchored()"),
    ("*", "section_text_sha256"): ("sha256 of section.section_text_original — the text version that this row's offsets index (3.0.3)", MIG),
    ("*", "study_id"): ("study of the row's paper, derived through PAPER (exactly one STUDY per PAPER in this release; 3.0.3). For corpus claims the original stage-51/52 value", MIG),
    ("*", "review_status"): ("review state; UNVERIFIED / REVIEW_REQUIRED unless a human review exists (none does: human_review is empty). Never ACCEPTED/REJECTED from a model", f"{B}; template §5"),
    ("*", "field_sources"): ("JSON object field -> stage that set or changed the value (e.g. G1_qwen, G1_checked_all_passages, G3_gemma+llama, finalize_*, compendium_projects_csv)", f"{G} apply_G1/apply_G3/finalize"),
    ("*", "gap_evidence"): ("JSON object field -> {section_id, char_start, char_end, quote} supporting a gap-filled value, or {conflict: competing values} for CONFLICTING", f"{G} apply_G1"),
    ("*", "gap_changes"): ("JSON list of changes made by the gap stages to this record (field, old, new, stage)", f"{G} apply_G1/apply_G3"),
    ("*", "extraction_run_id"): ("run that produced the row; resolves in EXTRACTION_RUN (all runs registered in 3.0.3)", f"{B}; {MIG} R1/R2"),
    ("*", "term_status"): ("'' if term_id is a live canonical term; REMOVED if the DeepSeek review removed it; NOT_IN_TERMINOLOGY if unknown", f"{B} term_status()"),
    ("term_mention", "mention_row_id"): ("row key = mention_id|extraction_model (mention_id is shared by models tagging the same span)", B),
    ("term_mention", "canonical_term_status"): ("'' | REMOVED | NOT_IN_TERMINOLOGY for canonical_term_id (see term_status)", B),
    ("term_mention", "term_link_status"): ("how canonical_term_id was set: LINKED (unique term_norm match), LINKED_BY_TYPE (type broke a tie), AMBIGUOUS (no unique term; id null), NO_CANONICAL_TERM", "src/scripts/vllm_termpop/fix_terminology_offsets.py"),
    ("term_mention", "offset_status"): ("EXACT (offsets as extracted), CORRECTED (section-level shift corrected in terminology 1.0.1), UNANCHORED", "src/scripts/vllm_termpop/fix_terminology_offsets.py"),
    ("term_mention", "offset_correction"): ("characters added to both offsets by the 1.0.1 correction (0 if none)", "src/scripts/vllm_termpop/fix_terminology_offsets.py"),
    ("term_mention", "extraction_run_id"): ("terminology source run: cpu_ensemble_v1, qwen_ollama_cell7c_v1, qwen35_vllm_body_v1, mesh_gazetteer_2026 (registered with source file sha256 in 3.0.3)", "src/scripts/termpipeline/assemble_mentions.py SOURCES"),
    ("term_concept_map", "mapping_row_id"): ("row key HMMAPROW_<n>, n = row order in mapping_remapped.jsonl then mapping_rejected.jsonl (mapping_id is not unique)", B),
    ("term_concept_map", "mapping_id_status"): ("'' | MISSING (no mapping_id upstream) | SHARED (mapping_id used by several rows)", B),
    ("term_concept_map", "guard_status"): ("kept (in mapping_remapped.jsonl) | rejected_guard (in mapping_rejected.jsonl)", B),
    ("term_concept_map", "relation_llm_g9"): ("relation EXACT/BROADER/NARROWER/RELATED/REJECTED proposed by Gemma in G9 (model judgement)", f"{G} apply_G9"),
    ("term_concept_map", "relation_deepseek"): ("relation proposed by DeepSeek-R1-Distill-Qwen-7B in the review (model judgement)", "src/scripts/vllm_termpop/deepseek_review.py"),
    ("term_concept_map", "mapping_disposition_reviewed"): ("ACCEPTED (Gemma and DeepSeek both EXACT) | REMOVED (both WRONG, or term removed) | REVIEW_REQUIRED (disagree); null = not reviewed. Model agreement, not human acceptance", "src/scripts/vllm_termpop/deepseek_review.py apply"),
    ("term_concept_map", "g9_run_id"): ("run that produced relation_llm_g9", MIG),
    ("term_concept_map", "deepseek_run_id"): ("run that produced relation_deepseek / mapping_disposition_reviewed", MIG),
    ("term_concept_map", "matched_via"): ("how the candidate was found, copied from the frozen guard file (3.0.3)", MIG),
    ("term_concept_map", "match_scores"): ("candidate scores (JSON) copied from the frozen guard file (3.0.3)", MIG),
    ("term_concept_map", "mapping_provenance"): ("JSON {query, services_queried, error} copied from the frozen guard file (3.0.3)", MIG),
    ("term_concept_map", "source_service_mapping"): ("service that returned the candidate, copied from the frozen guard file (3.0.3)", MIG),
    ("term_concept_map", "guard_rejection_reason"): ("reason the mapping guard rejected the candidate (rejected_guard rows)", MIG),
    ("term_concept_map", "mapping_evidence_status"): ("RESTORED (evidence copied; row verified on mapping_id+term_id+concept_id) | MISMATCH", MIG),
    ("term_definition", "verdict_deepseek"): ("DeepSeek review verdict on the definition (model judgement)", "src/scripts/vllm_termpop/deepseek_review.py"),
    ("relation", "subject_term_id"): ("canonical term linked to subject_display_label (G6 / embedding link); '' if none or the term was removed", f"{B} rel()"),
    ("relation", "object_term_id"): ("canonical term linked to object_display_label; '' if none or removed", f"{B} rel()"),
    ("relation", "entity_link_method"): ("method of the subject/object term link (embedding direct match or G6 Gemma)", f"{B} rel()"),
    ("relation", "subject_link_status"): ("LINKED | UNLINKED | REMOVED | NOT_IN_TERMINOLOGY", f"{B} rel()"),
    ("relation", "object_link_status"): ("LINKED | UNLINKED | REMOVED | NOT_IN_TERMINOLOGY", f"{B} rel()"),
    ("relation", "verdict_deepseek"): ("DeepSeek review verdict on the triple (model judgement)", "src/scripts/vllm_termpop/deepseek_review.py"),
    ("relation", "verdict_gemma_c4"): ("Gemma C4 judge verdict on the triple (model judgement)", "src/scripts/vllm_termpop/deepseek_review.py"),
    ("taxonomy_annotation", "agreement_status"): ("AGREED (both models same subcategory) | PARENT_AGREED (same category) | UNCERTAIN (both) | CONFLICTING | SINGLE_MODEL", f"{G} apply_G11"),
    ("taxonomy_annotation", "category"): ("upper taxonomy category, set only where the two models agree", f"{G} apply_G11"),
    ("taxonomy_annotation", "subcategory"): ("taxonomy subcategory, set only where both models chose it", f"{G} apply_G11"),
    ("taxonomy_annotation", "sub_qwen"): ("subcategory chosen by Qwen3.5-4B (G11)", f"{G} apply_G11"),
    ("taxonomy_annotation", "sub_gemma"): ("subcategory chosen by Gemma-4-E4B (G11B)", f"{G} apply_G11"),
    ("taxonomy_annotation", "taxonomy_version"): ("taxonomy id and version (terminology_taxonomy.json)", f"{G} apply_G11"),
    ("taxonomy_annotation", "classification_method"): ("models used", f"{G} apply_G11"),
    ("claim", "claim_source"): ("which extraction the row comes from: catalogue_v3_1 (catalogue finding) | corpus_stage52 (corpus stage-52 finding)", B),
    ("claim", "extraction_run_id_recovered"): ("run recovered for corpus claims that had no run id: the single stage-52 run whose checkpoint covers the claim's evidence section (3.0.3)", MIG),
    ("claim", "run_provenance_status"): ("ORIGINAL | RECOVERED_UNIQUE_STAGE_RUN | UNAVAILABLE", MIG),
    ("claim", "study_id_derived"): ("study of the claim's paper derived through PAPER (3.0.3); study_id is the original corpus value", MIG),
    ("canonical_term", "has_linked_mention"): ("1 if at least one term_mention links to this term, else 0 (3.0.3)", MIG),
    ("canonical_term", "ds_reviewed"): ("true if the DeepSeek review saw the term", "src/scripts/vllm_termpop/deepseek_review.py"),
    ("extraction_run", "verification"): ("VERIFIED_LOG | VERIFIED_CODE_AND_HASH | VERIFIED_RUN_EVENT | RECORDED_IN_DATA | AS_IN_3.0.2_UNVERIFIED", MIG),
    ("load_audit", "rows_offered"): ("rows handed to the table loader", B), ("load_audit", "rows_kept"): ("rows in the table", B),
    ("load_audit", "rows_dropped"): ("rows rejected by the primary key at load", B),
    ("cdm_entity_status", "status"): ("POPULATED | EMBEDDED (carried as columns) | EMPTY | EMPTY_NO_HUMAN_REVIEW_YET | NOT_A_TABLE", B),
    ("publication", "duplicate_status"): ("CONFLICTING when several BioProjects share the publication (not merged)", B),
}
MIG_TABLE_COLS = {"extraction_run": {"run_kind", "source_artifact", "source_artifact_sha256", "job_ids", "completed_at",
                                     "model_name_version", "prompt_version", "provenance_evidence", "stage_corrected"}}
TABLE_SOURCE = {  # table -> (generation stage, source)
    "paper": ("catalogue 3.1.1 papers + licences + corpus duplicates", B), "publication": ("CDM build", B),
    "paper_publication": ("CDM build", B), "source_asset": ("corpus_v2 sections (section_order 0)", B),
    "section": ("corpus_v2 sections.jsonl", B), "extraction_run": ("CDM build + 3.0.3 run registration", MIG),
    "processing_event": ("corpus_v2 processing_events.jsonl", B), "processing_lineage": ("CDM build", B),
    "canonical_term": ("terminology 1.0.1 canonical terms after DeepSeek review", "deepseek_review/corrected"),
    "removed_canonical_term": ("DeepSeek review removals", "deepseek_review/corrected"),
    "term_mention": ("terminology 1.0.1 term_mentions.jsonl", "releases/terminology/1.0.1"),
    "term_occurrence": ("CDM build (aggregate of term_mention)", B),
    "term_definition": ("terminology definitions + G8, after DeepSeek review", B),
    "removed_term_definition": ("DeepSeek review removals", "deepseek_review/corrected"),
    "term_concept_map": ("mapping guards v2 + G9 + DeepSeek review", B), "concept": ("mapping guards v2", B),
    "taxonomy_annotation": ("G11 two-model taxonomy", G), "type_harmonization": ("G7", G),
    "study": ("corpus_v2 studies.jsonl (stage 51)", B), "cohort": ("catalogue 3.1.1", B), "sample": ("catalogue 3.1.1", B),
    "assay": ("catalogue 3.1.1", B), "dataset": ("catalogue 3.1.1", B), "data_asset": ("catalogue 3.1.1", B),
    "body_site": ("CDM build (aggregate)", B), "intervention": ("CDM build (aggregate of G5 categories)", B),
    "claim": ("corpus_v2 findings (stage 52) + catalogue 3.1.1 findings", B), "quantitative_result": ("CDM build (projection of claim)", B),
    "claim_evidence": ("CDM build (projection of claim)", B), "relation": ("corpus_v2 canonical triples after DeepSeek review", B),
    "removed_relation": ("DeepSeek review removals", "deepseek_review/corrected"), "validation_result": ("catalogue QA + corpus validation", B),
    "evaluation_run": ("CDM build", B), "human_review": ("CDM build (empty)", B), "dataset_release": ("release manifests", B),
    "compendium_sample": ("Abdill et al. 2025 sample_metadata.tsv (corpus BioProjects)", B),
    "compendium_sample_tag": ("Abdill et al. 2025 tags.tsv.gz", B), "compendium_project": ("Abdill et al. 2025 projects.csv", B),
    "cdm_entity_status": ("CDM build", B), "load_audit": ("CDM build", B), "run_metadata": ("CDM build / migration", B),
    "cdm_change_log": ("3.0.3 migration", MIG), "identifier_crosswalk": ("3.0.3 migration", MIG), "relation_evidence": ("3.0.3 migration", MIG),
}
PK = {"paper": "paper_id", "section": "section_record_id", "extraction_run": "extraction_run_id", "term_mention": "mention_row_id",
      "canonical_term": "term_id", "concept": "concept_id", "term_concept_map": "mapping_row_id", "study": "study_id",
      "cohort": "cohort_id", "sample": "sample_group_id", "assay": "assay_id", "dataset": "dataset_id", "data_asset": "asset_id",
      "relation": "canonical_triple_id", "intervention": "intervention_id", "publication": "publication_id",
      "validation_result": "validation_result_id", "evaluation_run": "evaluation_run_id", "dataset_release": "release_id",
      "compendium_sample": "srs", "compendium_project": "project", "term_occurrence": "occurrence_key"}
PK_MULTI = {"claim": ("finding_id", "claim_source"), "term_definition": ("definition_id", "term_id"),
            "taxonomy_annotation": ("term_id", "taxonomy_version"), "quantitative_result": ("finding_id", "claim_source"),
            "claim_evidence": ("finding_id", "claim_source")}
FK = {"paper_id": "PAPER.paper_id", "study_id": "STUDY.study_id", "cohort_id": "COHORT.cohort_id (';'-list in catalogue)",
      "assay_id": "ASSAY.assay_id (';'-list in catalogue)", "dataset_id": "DATASET.dataset_id (';'-list in catalogue)",
      "canonical_term_id": "CANONICAL_TERM.term_id", "term_id": "CANONICAL_TERM.term_id", "concept_id": "CONCEPT.concept_id",
      "subject_term_id": "CANONICAL_TERM.term_id", "object_term_id": "CANONICAL_TERM.term_id", "extraction_run_id": "EXTRACTION_RUN.extraction_run_id",
      "extraction_run_id_recovered": "EXTRACTION_RUN.extraction_run_id", "g9_run_id": "EXTRACTION_RUN.extraction_run_id",
      "deepseek_run_id": "EXTRACTION_RUN.extraction_run_id", "publication_id": "PUBLICATION.publication_id",
      "section_record_id": "SECTION.section_record_id", "evidence_section_id": "SECTION.section_record_id",
      "canonical_triple_id": "RELATION.canonical_triple_id", "occurrence_key": "TERM_OCCURRENCE.occurrence_key",
      "study_id_derived": "STUDY.study_id", "project": "PAPER.bioproject", "srs": "COMPENDIUM_SAMPLE.srs"}
MISSING = ("NOT_REPORTED", "NOT_APPLICABLE", "NOT_ACCESSIBLE", "CONFLICTING")
PROMPT_SRC = "src/scripts/vllm_termpop/catalogue_ner.py (prompt cdm-catalogue-ner-v2-noplaceholder)"
PROMPT_VOCAB = {"dataset_role": "primary_study_data | linked_data",
                "data_availability_status": "PUBLIC | CONTROLLED | EMBARGOED | UPON_REQUEST | NOT_DEPOSITED | LINK_ONLY | UNKNOWN",
                "access_status": "PUBLIC | CONTROLLED | EMBARGOED | UPON_REQUEST | NOT_DEPOSITED | LINK_ONLY | UNKNOWN",
                "original_or_reused": "ORIGINAL | REUSED | UNKNOWN", "cohort_role": "cases_and_controls | single_group",
                "longitudinal": "YES | NO | UNCLEAR | NOT_APPLICABLE", "direction": "INCREASE | DECREASE | NO_ASSOCIATION | MIXED | NOT_STATED"}
PROMPT_RULE = {"participant_count": "integer stated in the passage; never computed or estimated",
               "sample_count": "integer stated in the passage; never computed or estimated",
               "file_size_bytes": "integer stated in the passage; never computed or estimated",
               "direction": "NOT_STATED unless the passage states the direction; 'detected'/'associated' never upgraded",
               "evidence_text": "verbatim quote from the passage, <= 300 characters"}


def prompt_fields():
    import ast
    src = (ROOT / "src/scripts/vllm_termpop/catalogue_ner.py").read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "ENTITY_SPECS" for t in node.targets):
            spec = ast.literal_eval(node.value)
            return {ent: set(v[3]) for ent, v in spec.items()}
    return {}


def schema_props():
    s = json.loads(CAT_SCHEMA.read_text())
    out = {}
    for ent, d in (s.get("$defs") or {}).items():
        for k, v in (d.get("properties") or {}).items():
            out[(ent, k)] = v
    for f in glob.glob(str(ROOT / "pipelines/corpus_v2/schema/*.json")):
        ent = Path(f).stem.split(".")[0]
        def walk(o):
            if isinstance(o, dict):
                for k, v in (o.get("properties") or {}).items():
                    if isinstance(v, dict):
                        out.setdefault((ent, k), v)
                        walk(v)
                for k, v in o.items():
                    if k != "properties":
                        walk(v)
            elif isinstance(o, list):
                for x in o:
                    walk(x)
        walk(json.loads(open(f).read()))
    return out


def crosswalk():
    """CDM field (lower-case table.column) -> crosswalk row text."""
    out = defaultdict(list)
    for line in CROSSWALK.read_text().splitlines():
        if not line.startswith("|") or "---" in line:
            continue
        cells = [x.strip() for x in line.strip("|").split("|")]
        if len(cells) < 3:
            continue
        for m in re.finditer(r"([A-Z_]{3,})\.([a-z0-9_*]+(?:/[a-z0-9_]+)*)", cells[1]):
            ent = m.group(1).lower()
            for col in m.group(2).split("/"):
                out[(ent, col)].append(f"{cells[0]} → {cells[1]}: {cells[2]}")
    return out


def run(db, out):
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    props, cw = schema_props(), crosswalk()
    pf = prompt_fields()
    cat_ent = {"cohort": "cohorts", "sample": "samples", "assay": "assays", "dataset": "datasets",
               "data_asset": "data_assets", "claim": "findings"}
    rows = []
    for (t,) in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
        info = c.execute(f'PRAGMA table_info("{t}")').fetchall()
        n = c.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
        big = n > 300000
        samp = f'(SELECT * FROM "{t}" WHERE rowid % {max(1, n // 200000)} = 0)' if big else f'"{t}"'
        ent_s = CAT_DEF.get(t)
        for cid, col, decl, notnull, dflt, pk in info:
            ty = dict(c.execute(f'SELECT typeof("{col}"), COUNT(*) FROM {samp} GROUP BY 1').fetchall())
            tot = sum(ty.values()) or 1
            nulls = ty.pop("null", 0)
            obs_types = "/".join(sorted(ty)) or "null only"
            vals = c.execute(f'SELECT "{col}", COUNT(*) FROM {samp} WHERE "{col}" IS NOT NULL GROUP BY 1 ORDER BY 2 DESC LIMIT 21').fetchall()
            jsonish = c.execute(f'SELECT COUNT(*) FROM {samp} WHERE "{col}" LIKE \'[%\' OR "{col}" LIKE \'{{%\'').fetchone()[0]
            multi = c.execute(f'SELECT COUNT(*) FROM {samp} WHERE typeof("{col}")=\'text\' AND "{col}" LIKE \'%; %\' AND "{col}" LIKE \'HM%\'').fetchone()[0]
            codes = sorted({v for v, _ in vals if v in MISSING})
            sp = props.get((ent_s, col)) if ent_s else None
            sp = sp or props.get(({"section": "section", "study": "study", "paper": "paper"}.get(t, ""), col))
            doc_type = (json.dumps(sp.get("type")) if sp and sp.get("type") else ("$ref " + sp["$ref"].split("/")[-1] if sp and sp.get("$ref") else ""))
            enum = sp.get("enum") or ((sp.get("items") or {}).get("enum") if sp else None) if sp else None
            definition, dsrc, status = "", "", "NEEDS_EXPERT_REVIEW"
            code = CODE.get((t, col)) or CODE.get(("*", col))
            if code and not (code is CODE.get(("*", col)) and t in ("study",) and col == "study_id"):
                definition, dsrc, status = code[0], f"CODE: {code[1]}", "DEFINED_IN_CODE"
            elif t in MIG_TABLE_COLS and col in MIG_TABLE_COLS[t]:
                definition, dsrc, status = c.execute("SELECT description FROM cdm_change_log WHERE target=?", (f"{t}.{col}",)).fetchone()[0] \
                    if c.execute("SELECT 1 FROM sqlite_master WHERE name='cdm_change_log'").fetchone() else ("", "", "NEEDS_EXPERT_REVIEW"), f"CODE: {MIG}", "DEFINED_IN_CODE"
            elif sp and sp.get("description"):
                definition, dsrc, status = sp["description"], "SCHEMA_DESCRIPTION", "DOCUMENTED"
            elif cw.get((t, col)) or cw.get((t.rstrip("s"), col)):
                txt = (cw.get((t, col)) or cw.get((t.rstrip("s"), col)))[0]
                definition, dsrc, status = "", "CROSSWALK: " + txt[:300], "SOURCE_DOCUMENTED_MEANING_NEEDS_REVIEW"
            elif t in ("compendium_sample", "compendium_sample_tag", "compendium_project"):
                dsrc, status = "column of the Abdill et al. 2025 compendium file (definition in that dataset's documentation)", "EXTERNAL_SOURCE_DEFINITION"
            if col in SOURCE_TEXT:
                ex = "<source text>"
            else:
                ex = next((str(v) for v, _ in vals), "")
                ex = ex[:80] + ("…" if len(ex) > 80 else "")
            key = ("PK" if PK.get(t) == col or pk else ("PK part" if col in PK_MULTI.get(t, ()) else ""))
            fkr = FK.get(col, "") if key != "PK" else ""
            observed = "" if len(vals) > 20 or col in SOURCE_TEXT else "; ".join(f"{v}" for v, _ in vals)[:400]
            rows.append({
                "table": t, "column": col, "position": cid, "sqlite_declared_type": decl or "(none: dynamic typing)",
                "observed_storage_types": obs_types, "documented_type": doc_type,
                "logical_type": ("JSON-encoded" if jsonish and jsonish >= 0.5 * (tot - nulls) else
                                 "';'-separated id list or id" if multi else
                                 ("integer or missing-data code" if set(ty) == {"integer", "text"} and codes else
                                  {"integer": "integer", "real": "number", "text": "text"}.get(obs_types, obs_types))),
                "key_role": key, "references": fkr,
                "null_share": round(nulls / tot, 4), "documented_allowed_values": "; ".join(map(str, enum)) if enum else "",
                "observed_values_if_few": observed, "missing_data_codes_present": "; ".join(codes),
                "missing_data_behaviour": ("null = not extracted; missing-data codes = checked (template §4)" if t in CAT_DEF and t != "paper"
                                           else "null = not available"),
                "source_stage": TABLE_SOURCE.get(t, ("", ""))[0],
                "provenance_requirement": ("extraction_run_id + section + offsets + section_text_sha256" if col in ("char_start", "start_offset", "evidence_span_start", "definition_char_start") else ""),
                "extraction_rule": (f"LLM-extracted field '{col}' ({PROMPT_SRC}): only values the passage states explicitly"
                                    + (f"; {PROMPT_RULE[col]}" if col in PROMPT_RULE else "")
                                    if col in pf.get(cat_ent.get(t, ""), set()) else ""),
                "prompt_controlled_vocabulary": PROMPT_VOCAB.get(col, "") if col in pf.get(cat_ent.get(t, ""), set()) else "",
                "example_value": ex, "definition": definition, "definition_source": dsrc, "definition_status": status,
                "rows_in_table": n, "sampled_for_profile": "yes (every k-th row)" if big else "no (all rows)"})
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "CDM_COLUMN_DICTIONARY.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    from collections import Counter
    st = Counter(r["definition_status"] for r in rows)
    by_t = defaultdict(list)
    for r in rows:
        by_t[r["table"]].append(r)
    L = [f"# CDM column dictionary — {Path(db).parent.name}", "",
         f"Generated from the database by `src/scripts/cdm_remediation/build_dictionary.py`: **{len(by_t)} tables, {len(rows)} columns**. "
         "Definitions are given only where a source states them; `NEEDS_EXPERT_REVIEW` marks the rest (meanings are never inferred "
         "from column names). Full detail (types, allowed values, null share, keys, examples) in `CDM_COLUMN_DICTIONARY.csv`.", "",
         "| definition status | columns |", "|---|---:|"] + [f"| {k} | {v} |" for k, v in st.most_common()] + [""]
    for t, cols in by_t.items():
        src = TABLE_SOURCE.get(t, ("", ""))
        L += [f"## `{t}` — {cols[0]['rows_in_table']:,} rows", "", f"Source: {src[0]} (`{src[1]}`)" if src[0] else "", "",
              "| column | type | key / reference | null % | definition | status |", "|---|---|---|---:|---|---|"]
        for r in cols:
            d = (r["definition"] or ("source: " + r["definition_source"] if r["definition_source"] else "")).replace("|", "/")
            L.append(f"| `{r['column']}` | {r['logical_type']} | {(r['key_role'] + ' ' + r['references']).strip()} | "
                     f"{100 * r['null_share']:.1f} | {d[:220]} | {r['definition_status']} |")
        L.append("")
    (out / "COMPLETE_CDM_DATA_DICTIONARY.md").write_text("\n".join(L))
    print(len(by_t), "tables", len(rows), "columns", dict(st))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    run(Path(a.db), Path(a.out))


if __name__ == "__main__":
    raise SystemExit(main())
