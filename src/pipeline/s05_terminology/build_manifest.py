#!/usr/bin/env python3
"""Supporting artifact — ``terminology_extraction_manifest.json``.

The provenance record for one terminology-extraction build. It answers, for
each artifact: where it came from, how it was produced, whether it is complete,
and what is explicitly NOT covered.

Every count is read from the artifact's own summary file or recomputed from the
artifact itself. Nothing is estimated, and a missing input is recorded as
missing rather than assumed present.

Outputs (in ``--out_dir``)
--------------------------
    terminology_extraction_manifest.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

ARTIFACTS = {
    "term_mentions.jsonl": "Stage 1 — mention-level records",
    "canonical_terms.jsonl": "Stage 2 — canonical terms",
    "term_definitions.jsonl": "Stage 3 — source-grounded definitions",
    "term_ontology_mappings.jsonl": "Stage 5 — candidate CV mappings",
    "terminology_taxonomy.json": "Stage 4 — exported taxonomy",
    "ontology_registry.json": "supporting — vocabularies consulted",
    "terminology_validation.jsonl": "supporting — per-section validation",
    "terminology_extraction_report.md": "supporting — human-readable report",
    "terminology_extraction_manifest.json": "supporting — this manifest",
}

SUMMARIES = [
    "_mentions_summary.json",
    "canonical_terms_summary.json",
    "_definitions_summary.json",
    "mapping_projection_summary.json",
    "taxonomy_summary.json",
    "validation_summary.json",
    "terminology_pipeline_summary.json",
]


def _sha256_file(path: Path, chunk=1 << 20):
    h = hashlib.sha256()
    try:
        with path.open("rb") as f:
            while True:
                b = f.read(chunk)
                if not b:
                    break
                h.update(b)
    except OSError:
        return None
    return h.hexdigest()


def _jsonl_count(path: Path):
    if not path.exists():
        return None
    n = 0
    with path.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.strip():
                n += 1
    return n


def _load(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser(description="Build terminology_extraction_manifest.json")
    ap.add_argument("--out_dir", type=Path, required=True)
    ap.add_argument("--version", default="v1")
    args = ap.parse_args()
    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    artifacts = []
    for name, desc in ARTIFACTS.items():
        p = out_dir / name
        if name == "terminology_extraction_manifest.json":
            # A file cannot contain its own correct sha256. Recorded as SELF so
            # the entry is explicit rather than a hash that will never verify.
            # Treated as present unconditionally: this manifest is being written.
            artifacts.append({
                "name": name, "description": desc, "status": "PRESENT",
                "path": str(p), "sha256": None,
                "sha256_note": "SELF — a file cannot carry its own digest; every "
                               "other artifact is hashed normally.",
            })
            continue
        if not p.exists():
            artifacts.append({"name": name, "description": desc,
                              "status": "MISSING", "path": str(p)})
            continue
        entry = {
            "name": name,
            "description": desc,
            "status": "PRESENT",
            "path": str(p),
            "bytes": p.stat().st_size,
            "sha256": _sha256_file(p),
        }
        if p.suffix == ".jsonl":
            entry["records"] = _jsonl_count(p)
        artifacts.append(entry)

    summaries = {}
    for s in SUMMARIES:
        p = out_dir / s
        if p.exists():
            summaries[s] = _load(p)

    validation = summaries.get("validation_summary.json") or {}
    coverage = validation.get("coverage") or {}
    mentions = summaries.get("_mentions_summary.json") or {}
    canon = summaries.get("canonical_terms_summary.json") or {}
    defs = summaries.get("_definitions_summary.json") or {}
    mapsum = summaries.get("mapping_projection_summary.json") or {}
    tax = summaries.get("taxonomy_summary.json") or {}

    present = [a for a in artifacts if a["status"] == "PRESENT"]
    missing = [a["name"] for a in artifacts if a["status"] == "MISSING"]

    manifest = {
        "manifest_version": "1.1.0",
        "pipeline_version": args.version,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "repository": {
            "root": str(REPO_ROOT),
            "entry_package": "src/scripts/termpipeline/",
            "note": "Outputs are written to a NEW directory; releases/data_catalogue/ and "
                    "releases/zenodo_v1/ are read-only inputs and are not modified.",
        },
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "note": "Stages 1/2/4/5 and the supporting artifacts are CPU-only and "
                    "deterministic. Stage 3 is CPU-only, deterministic, and makes no "
                    "LLM or network call.",
        },
        "artifacts": artifacts,
        "artifact_status": {
            "n_expected": len(ARTIFACTS),
            "n_present": len(present),
            "n_missing": len(missing),
            "missing": missing,
        },
        "sources": {
            "sections": "data/segmented_sections_markdown/ (453 HMPAPER_*.md)",
            "cpu_ensemble_ner": "releases/zenodo_v1/ner_453_sections/all_ner_sections_combined.csv",
            "qwen_ollama_ner": "releases/zenodo_v1/qwen_sections_ner/qwen_sections_ner.csv",
            "qwen_vllm_body_ner": "outputs/results/llm_ner_body/vllm_sections_ner.csv",
            "mesh_gazetteer": "outputs/results/mesh_ner/mesh_ner_terms.csv",
            "canonical_input_table": "releases/data_catalogue/terminology/terminology_dedup.csv",
            "cv_linking": "outputs/results/cv_linking/cv_mapped_entities.jsonl",
            "omop_linking": "outputs/results/omop_linking/omop_links.csv",
            "taxonomy": "releases/data_catalogue/terminology/taxonomy/term_taxonomy_v1.yaml",
        },
        "coverage": {
            "papers_in_corpus_membership": coverage.get("papers_in_corpus_membership"),
            "papers_processed": coverage.get("papers_processed"),
            "papers_not_processed": coverage.get("papers_not_processed"),
            "sections_validated": coverage.get("sections_validated"),
            "sections_flagged": coverage.get("sections_flagged"),
            "sections_not_applicable": coverage.get("sections_not_applicable"),
            "mentions_excluded_non_integer_offsets": (
                (validation.get("mention_offset_verification") or {})
                .get("mentions_excluded_non_integer_offsets")),
            "mention_rows_by_link_status": (
                (validation.get("mention_link_status") or {}).get("by_link_status")),
            "corpus_build_ready_papers": coverage.get("corpus_report_ready"),
            "corpus_build_blocked_papers": coverage.get("corpus_report_blocked"),
            "canonical_terms": (canon.get("counts") or {}).get("canonical_terms"),
            "mention_records": mentions.get("rows_written"),
            "mention_rows_read": mentions.get("rows_read"),
            "mention_rows_skipped_empty_surface": mentions.get("rows_skipped_empty_surface"),
            "sources_with_mentions": (sorted((mentions.get("sources") or {}).keys())
                                      or None),
            "mention_rows_linked": (canon.get("counts") or {}).get("mention_rows_linked"),
            "mention_rows_unresolved": (canon.get("counts") or {}).get("mention_rows_unresolved"),
            "terms_with_mention_rollup": (canon.get("counts") or {})
            .get("terms_with_mention_rollup"),
            "terms_with_source_definition": defs.get("canonical_terms_with_source_definition"),
            "definition_rows": defs.get("definition_rows"),
            "mapping_rows": (mapsum.get("counts") or {}).get("rows"),
            "terms_with_any_mapping_candidate": (mapsum.get("counts") or {})
            .get("terms_with_any_candidate"),
            "terms_with_any_mapping_candidate_including_unresolved": (mapsum.get("counts") or {})
            .get("terms_with_any_candidate_including_unresolved"),
            "mapping_rows_unresolved_no_canonical_term": (mapsum.get("counts") or {})
            .get("rows_unresolved_no_canonical_term"),
            "mapping_ids_unique": (mapsum.get("counts") or {}).get("mapping_id_unique"),
            "duplicate_mapping_ids": (mapsum.get("counts") or {}).get("duplicate_mapping_ids"),
            "auto_accepted_mappings": (mapsum.get("counts") or {}).get("auto_accepted"),
            "taxonomy_upper_categories": (tax.get("taxonomy") or {}).get("n_upper_categories"),
            "taxonomy_subcategories": (tax.get("taxonomy") or {}).get("n_subcategories"),
            "classified_terms": (tax.get("classification") or {}).get("n_classified_terms"),
        },
        "completeness": {
            "overall_status": validation.get("overall_status", "UNKNOWN"),
            "basis": "fail-closed: COMPLETE requires all corpus papers present, every "
                     "section integrity check passing, and a mention for every paper "
                     "with content.",
            "retrieval_evaluation": "BLOCKED_NO_HUMAN_REVIEWED_LABELS",
            "corpus_stages_not_run": {
                "jev": False,
                "embeddings": False,
                "dense_index": False,
                "note": "corpus_pipeline stages 06/11 have not been run for this build; "
                        "they are not assumed complete.",
            },
        },
        "not_covered": [
            "No canonical term, definition or mapping is human-verified in this build.",
            "External ontology definitions (UMLS/OMOP/BioPortal descriptions) are NOT "
            "produced: they are a different provenance class from source definitions.",
            "No acceptance threshold has been calibrated, so nothing is AUTO_ACCEPTED.",
            "OMOP linking is exact-normalized only; a miss is not evidence of absence.",
            "MeSH/OMOP cover only their own vocabularies; specialist strain/gene names "
            "may legitimately have no candidate.",
            "Definition extraction is limited to the sections scanned; a term with no "
            "definition found is scoped to this pass, not to the literature.",
            "`mention_count` is a count of DISTINCT occurrences (`occurrence_key`), not "
            "of mention rows; summing rows across extractors would count one occurrence "
            "up to four times.",
            "The mention -> canonical-term link is an exact normalized-surface match "
            "with recorded type agreement; unmatched mentions are archived as "
            "`UNRESOLVED_*`, never deleted or force-linked.",
            "A mapping row whose subject has no canonical term is retained as "
            "`UNRESOLVED_NO_CANONICAL_TERM`; such rows can never be auto-accept-eligible.",
        ],
        "caveats": [
            "Counts are read from the artifacts' own summaries or recomputed from the "
            "artifacts; none are estimated.",
            "A MISSING artifact is reported as MISSING, never as zero or complete.",
            "Model confidence is not correctness and is not treated as such.",
            "`mapping_id` is unique by construction over the rows (a trailing "
            "occurrence index disambiguates repeated candidates); no candidate is "
            "collapsed to make ids unique.",
        ],
        "elapsed_seconds": round(time.time() - t0, 1),
    }

    out = out_dir / "terminology_extraction_manifest.json"
    out.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"artifact_status": manifest["artifact_status"],
                      "completeness": manifest["completeness"]["overall_status"]}, indent=2))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
