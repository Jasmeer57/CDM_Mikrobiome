"""Shared paths and reference specification for the 3.2.0-candidate schema / interoperability package.

Never hard-codes the repo root: walks up to the nearest ``.cdm_root`` (override with CDM_REPO_ROOT).
The frozen releases are only ever opened read-only (``file:...?mode=ro``).
"""
from __future__ import annotations

import hashlib
import os
import sqlite3
from pathlib import Path


def _repo_root() -> Path:
    env = os.environ.get("CDM_REPO_ROOT")
    if env:
        return Path(env).resolve()
    return next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())


REPO_ROOT = _repo_root()
DB_303 = REPO_ROOT / "releases/cdm_v3/3.0.3/microbiome_cdm_v3.db"
DB_310 = REPO_ROOT / "releases/cdm_v3/3.1.0/microbiome_cdm_v3.1.0.db"
DICTIONARY_303 = REPO_ROOT / "releases/cdm_v3/3.0.3/remediation/CDM_COLUMN_DICTIONARY.csv"
REGISTRY_303 = REPO_ROOT / "releases/cdm_v3/3.0.3/remediation/UPDATED_ENTITY_REGISTRY_PROPOSAL.csv"
RIGHTS_MATRIX = REPO_ROOT / "paper/publication/rights/PAPER_RIGHTS_MATRIX.csv"
OUT = REPO_ROOT / "outputs/results/schema_exports_v32_2026-11-11"
SCRATCH = REPO_ROOT / "outputs/scratch/cdm_v32_candidate"
STANDARDS = REPO_ROOT / "outputs/scratch/standards_fetch_2026-11-11"
CANDIDATE_DB = SCRATCH / "microbiome_cdm_v3.2.0-candidate_schema_hr.db"  # 3.1.0 copy + human_review
CDM_VERSION = "3.2.0-candidate"
SCHEMA_ID = "https://w3id.org/microbiome-cdm/schema"  # identifier namespace only; not a resolvable claim


def ro_connect(path: Path = DB_310) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


# ---------------------------------------------------------------------------------------------------------------
# Primary / unique keys.  "declared" = SQLite PRIMARY KEY in the 3.1.0 DDL; "documented" = PK in the 3.0.3
# column dictionary; "inferred" = chosen here and verified unique + non-null by introspect.py.
# ---------------------------------------------------------------------------------------------------------------
KEYS: dict[str, tuple[list[str], str]] = {
    "paper": (["paper_id"], "declared"),
    "publication": (["publication_id"], "declared"),
    "section": (["section_record_id"], "declared"),
    "study": (["study_id"], "declared"),
    "dataset": (["dataset_id"], "declared"),
    "data_asset": (["asset_id"], "declared"),
    "dataset_release": (["release_id"], "declared"),
    "evaluation_run": (["evaluation_run_id"], "declared"),
    "extraction_run": (["extraction_run_id"], "declared"),
    "intervention": (["intervention_id"], "declared"),
    "canonical_term": (["term_id"], "declared"),
    "concept": (["concept_id"], "declared"),
    "term_concept_map": (["mapping_row_id"], "declared"),
    "term_mention": (["mention_row_id"], "declared"),
    "relation": (["canonical_triple_id"], "declared"),
    "compendium_project": (["project"], "declared"),
    "compendium_sample": (["srs"], "declared"),
    "assay": (["assay_id"], "documented"),
    "cohort": (["cohort_id"], "documented"),
    "sample": (["sample_group_id"], "documented"),
    "claim": (["finding_id", "claim_source"], "documented"),
    "claim_evidence": (["finding_id", "claim_source"], "documented"),
    "quantitative_result": (["finding_id", "claim_source"], "documented"),
    "term_occurrence": (["occurrence_key"], "documented"),
    "taxonomy_annotation": (["term_id", "taxonomy_version"], "documented"),
    "term_definition": (["definition_id", "term_id"], "documented"),
    "validation_result": (["validation_result_id"], "documented"),
    "relation_evidence": (["triple_mention_id"], "inferred"),
    "source_asset": (["paper_id"], "inferred"),
    "paper_publication": (["paper_id"], "inferred"),
    "body_site": (["body_site_label"], "inferred"),
    "term_dedup_map": (["term_id"], "inferred"),
    "term_curation": (["term_id"], "inferred"),
    "term_enrichment": (["term_id"], "inferred"),
    "triple_repair": (["canonical_triple_id"], "inferred"),
    "triple_tier": (["canonical_triple_id"], "inferred"),
    "concept_curation": (["concept_id"], "inferred"),
    "concept_curie_map": (["concept_iri"], "inferred"),
    "type_harmonization": (["id"], "inferred"),
    "removed_canonical_term": (["term_id"], "inferred"),
    "removed_relation": (["canonical_triple_id"], "inferred"),
    "removed_term_definition": (["_id"], "inferred"),
    "run_metadata": (["key"], "inferred"),
    "human_review": (["review_id"], "documented"),
    "mapping_enrichment": ([], "no natural key: 18,272 rows, 16,750 distinct (term_id, concept_id); one row per accepted mapping row, mapping_row_id not carried"),
    "term_concept_map_clean": (["term_id", "concept_id"], "inferred"),
}

# ---------------------------------------------------------------------------------------------------------------
# References (foreign-key-style).  (child_table, [child_cols], parent_table, [parent_cols], multivalued, source)
# multivalued=True: the child cell may hold a ';'-separated id list (documented in the 3.0.3 dictionary); such
# links are declared as multivalued ranges in LinkML and are NOT emitted as SQL FOREIGN KEY constraints.
# source: DOCUMENTED (3.0.3 column dictionary `references`) or INFERRED (name/value match, checked by SQL).
# ---------------------------------------------------------------------------------------------------------------
_D, _I = "DOCUMENTED_3.0.3_DICTIONARY", "INFERRED_NAME_AND_VALUE_MATCH"
REFS: list[tuple[str, list[str], str, list[str], bool, str]] = []


def _r(ct, cc, pt, pc, mv=False, src=_I):
    REFS.append((ct, cc if isinstance(cc, list) else [cc], pt, pc if isinstance(pc, list) else [pc], mv, src))


for _t in ("assay", "cohort", "sample", "dataset", "data_asset", "claim"):
    _r(_t, "paper_id", "paper", "paper_id", src=_D)
    _r(_t, "study_id", "study", "study_id", src=_D)
    _r(_t, "extraction_run_id", "extraction_run", "extraction_run_id", src=_D)
for _t in ("assay", "cohort", "sample", "data_asset", "claim"):
    _r(_t, "dataset_id", "dataset", "dataset_id", mv=True, src=_D)
_r("sample", "cohort_id", "cohort", "cohort_id", mv=True, src=_D)
_r("claim", "cohort_id", "cohort", "cohort_id", mv=True, src=_D)
_r("claim", "assay_id", "assay", "assay_id", mv=True, src=_D)
_r("claim", "evidence_section_id", "section", "section_record_id", src=_D)
for _t in ("assay", "cohort", "sample", "dataset", "data_asset", "claim"):
    _r(_t, ["paper_id", "section_id"], "section", ["paper_id", "section_id_original"])
_r("claim_evidence", ["finding_id", "claim_source"], "claim", ["finding_id", "claim_source"])
_r("claim_evidence", "paper_id", "paper", "paper_id", src=_D)
_r("quantitative_result", ["finding_id", "claim_source"], "claim", ["finding_id", "claim_source"])
_r("quantitative_result", "paper_id", "paper", "paper_id", src=_D)
_r("compendium_sample", "project", "compendium_project", "project")
_r("compendium_sample_tag", "srs", "compendium_sample", "srs", src=_D)
_r("compendium_sample_tag", "project", "compendium_project", "project")
_r("compendium_project", "project", "paper", "bioproject")  # parent col not a key -> logical only
_r("paper", "canonical_paper_id", "paper", "paper_id")
_r("paper_publication", "paper_id", "paper", "paper_id", src=_D)
_r("paper_publication", "publication_id", "publication", "publication_id", src=_D)
_r("processing_event", "paper_id", "paper", "paper_id", src=_D)
_r("section", "paper_id", "paper", "paper_id", src=_D)
_r("source_asset", "paper_id", "paper", "paper_id", src=_D)
_r("study", "paper_id", "paper", "paper_id", src=_D)
_r("relation", "subject_term_id", "canonical_term", "term_id", src=_D)
_r("relation", "object_term_id", "canonical_term", "term_id", src=_D)
_r("relation", "extraction_run_id", "extraction_run", "extraction_run_id", src=_D)
_r("relation_evidence", "canonical_triple_id", "relation", "canonical_triple_id", src=_D)
_r("relation_evidence", "paper_id", "paper", "paper_id", src=_D)
_r("relation_evidence", "section_record_id", "section", "section_record_id", src=_D)
_r("relation_evidence", "extraction_run_id", "extraction_run", "extraction_run_id", src=_D)
_r("taxonomy_annotation", "term_id", "canonical_term", "term_id", src=_D)
_r("taxonomy_annotation", "extraction_run_id", "extraction_run", "extraction_run_id", src=_D)
_r("term_concept_map", "term_id", "canonical_term", "term_id", src=_D)
_r("term_concept_map", "concept_id", "concept", "concept_id", src=_D)
_r("term_concept_map", "extraction_run_id", "extraction_run", "extraction_run_id", src=_D)
_r("term_concept_map", "g9_run_id", "extraction_run", "extraction_run_id", src=_D)
_r("term_concept_map", "deepseek_run_id", "extraction_run", "extraction_run_id", src=_D)
_r("term_definition", "term_id", "canonical_term", "term_id", src=_D)
_r("term_definition", "paper_id", "paper", "paper_id", src=_D)
_r("term_definition", "extraction_run_id", "extraction_run", "extraction_run_id", src=_D)
_r("term_definition", ["paper_id", "section_id"], "section", ["paper_id", "section_id_original"])
_r("term_mention", "occurrence_key", "term_occurrence", "occurrence_key", src=_D)
_r("term_mention", "paper_id", "paper", "paper_id", src=_D)
_r("term_mention", "canonical_term_id", "canonical_term", "term_id", src=_D)
_r("term_mention", "extraction_run_id", "extraction_run", "extraction_run_id", src=_D)
_r("term_mention", ["paper_id", "section_id"], "section", ["paper_id", "section_id_original"])
_r("term_occurrence", "paper_id", "paper", "paper_id", src=_D)
_r("type_harmonization", "canonical_term_id", "canonical_term", "term_id", src=_D)
_r("type_harmonization", "extraction_run_id", "extraction_run", "extraction_run_id", src=_D)
_r("removed_term_definition", "paper_id", "paper", "paper_id", src=_D)
_r("removed_term_definition", "term_id", "canonical_term", "term_id", src=_D)
_r("removed_term_definition", "extraction_run_id", "extraction_run", "extraction_run_id", src=_D)
# 3.1.0 curated layers (not in the 3.0.3 dictionary)
for _t in ("term_dedup_map", "term_curation", "term_enrichment", "term_concept_map_clean", "mapping_enrichment"):
    _r(_t, "term_id", "canonical_term", "term_id")
_r("term_dedup_map", "canonical_term_id", "canonical_term", "term_id")
_r("mapping_enrichment", "concept_id", "concept", "concept_id")
# curated (3.1.0) concept ids are canonical CURIEs; concept_curation is their key table, concept_curie_map bridges
# each curated CURIE to the concept IRIs of the live concept table
_r("term_concept_map_clean", "concept_id", "concept_curation", "concept_id")
_r("concept_curie_map", "canonical_concept_id", "concept_curation", "concept_id")
_r("concept_curie_map", "concept_iri", "concept", "concept_id")
_r("triple_repair", "canonical_triple_id", "relation", "canonical_triple_id")
_r("triple_tier", "canonical_triple_id", "relation", "canonical_triple_id")
_r("human_review", "target_id", "*", "*")  # polymorphic: resolved per target_entity in the candidate DB

# The 3.0.3 dictionary documents removed_* -> live tables; they are archives of rows REMOVED from the live table,
# so by construction they do not resolve.  Recorded as documented-but-not-a-FK (see build_linkml.py).
ARCHIVE_REFS = [
    ("removed_canonical_term", "term_id", "canonical_term", "term_id"),
    ("removed_relation", "canonical_triple_id", "relation", "canonical_triple_id"),
]

# Live tables whose deleted rows are kept in an archive table: an orphan that resolves in the archive is a
# tombstoned reference (the child row carries a REMOVED / NOT_IN_TERMINOLOGY status), not a broken link.
ARCHIVE_OF = {"canonical_term": ("removed_canonical_term", "term_id"),
              "relation": ("removed_relation", "canonical_triple_id")}
