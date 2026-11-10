#!/usr/bin/env python3
"""
build_zenodo_bundle.py — Assemble a Zenodo-ready deposit folder for the
Microbiome Common Data Model (MCDM) v1.0 release.

Reads the production SQLite DB + cleanup checkpoints + corpus text files
and emits a self-contained, redistributable package.

Output: <cdm_output>/zenodo_v1/
  ├── README.md                      ← Top-level guide
  ├── zenodo_metadata.json           ← Zenodo deposition metadata
  ├── zenodo_upload_manifest.md      ← File list with SHA-256 checksums
  ├── data/
  │   ├── nodes.jsonl                ← entities (nodes)
  │   ├── edges.jsonl                ← relationships (edges/triples)
  │   ├── cdm.json                   ← Common Data Model schema
  │   ├── cdm_context.jsonld         ← JSON-LD context
  │   ├── data_catalogue.json        ← DCAT-style dataset inventory
  │   ├── cleanup_report.json        ← 5-pass entity cleanup summary
  │   └── corpus/
  │       ├── corpus_metadata.jsonl  ← 444 BioProject metadata records
  │       ├── corpus_papers.jsonl    ← Per-paper text stats
  │       ├── evidence_records.jsonl  ← Evidence records from edge_evidence
  │       ├── corpus_schema.json     ← Corpus schema
  │       ├── data_manifest.json     ← Manifest with checksums
  │       └── README_corpus.md       ← Corpus documentation
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parents[2]  # cdm_pipeline/export/ -> repo root
# Dataset path (supports CDM_PAPERS_TXT override). Imported via the repo root so
# this stays runnable as a standalone script.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
from cdm_pipeline import paths as _paths  # noqa: E402
CDM_OUTPUT = REPO_ROOT / "paper" / "_multi_ner_runs" / "cdm_output"
DB_PATH = CDM_OUTPUT / "microbiome_cdm.db"
PAPERS_DIR = _paths.papers_txt()
CHECKPOINT_DIR = CDM_OUTPUT / "checkpoints"
OUT = CDM_OUTPUT / "zenodo_v1"
OUT_DATA = OUT / "data"
OUT_CORPUS = OUT_DATA / "corpus"

# ---------------------------------------------------------------------------
# CDM constants (must match cdm_pipeline/config.py)
# ---------------------------------------------------------------------------
CDM_TYPES = [
    "ORGANISM", "CHEMICAL", "DISEASE", "PROTEIN", "DNA_RNA", "CELL_TYPE",
    "GENOMICS", "PATHWAY", "LAB_METHOD", "DATA_ANALYSIS", "SAMPLE_METHOD",
    "CLINICAL", "EXPERIMENTAL_METHOD", "STUDY_DESIGN",
]

CDM_TYPE_DESCRIPTIONS = {
    "ORGANISM": "Microorganisms, taxa, species mentioned in microbiome studies",
    "CHEMICAL": "Chemicals, metabolites, compounds, drugs",
    "DISEASE": "Diseases, conditions, disorders, syndromes",
    "PROTEIN": "Proteins, enzymes, peptides, functional gene products",
    "DNA_RNA": "DNA/RNA sequences, genes, transcripts, oligonucleotides",
    "CELL_TYPE": "Cell types, cell lines, tissue types",
    "GENOMICS": "Genomic concepts, mutations, variants, sequencing terms",
    "PATHWAY": "Metabolic pathways, signaling pathways, biological processes",
    "LAB_METHOD": "Laboratory methods, techniques, protocols",
    "DATA_ANALYSIS": "Statistical methods, bioinformatics tools, analysis approaches",
    "SAMPLE_METHOD": "Sample collection, preparation, storage methods",
    "CLINICAL": "Clinical findings, symptoms, patient characteristics",
    "EXPERIMENTAL_METHOD": "Experimental designs, interventions, procedures",
    "STUDY_DESIGN": "Study types, cohort designs, trial structures",
}

RELATIONSHIP_TYPES = [
    "CO_OCCURS_WITH", "ASSOCIATED_WITH", "ENRICHED_IN", "DEPLETED_IN",
    "PRODUCES", "TREATS", "PART_OF_PATHWAY", "PARTICIPATES_IN",
    "DISRUPTS", "EXPRESSES", "IMPLICATED_IN", "PRODUCED_BY", "ENCODES",
    "TREATED_BY",
]

# ---------------------------------------------------------------------------
# 2-char entity whitelist — well-established biomedical abbreviations
# ---------------------------------------------------------------------------

LEGITIMATE_2CHAR_TERMS = frozenset({
    # Diseases / conditions
    "AD", "AK", "AM", "AR", "AV", "BC", "BD", "CA", "CC", "CD", "CF", "CK",
    "CR", "CS", "CV",
    # Chemicals / element symbols
    "CL", "CO", "CU", "FE", "K", "LI", "MG", "MN", "MO", "NA", "NI", "NO",
    "SE", "ZN", "PH",
    # Proteins / biology
    "AP", "IG", "IL",
    # Cell types
    "DC", "NK",
    # Methods / instruments
    "CT", "DB", "GC", "KO", "LC", "MS", "PC", "WT",
    # Statistics
    "SD",
    # Other
    "OR",
})

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def is_entity_noise(term: str, conf: float) -> bool:
    """Determine if an entity should be flagged as noise beyond confidence=0.

    Additional checks:
    - 2-char terms not in the biomedical abbreviation whitelist
    - Spaced-out single-letter sequences (e.g. "O R I G I N A L A R T I C L E")
    """
    if conf == 0:
        return True
    t = term.strip()
    if len(t) <= 2 and t.upper() not in LEGITIMATE_2CHAR_TERMS:
        return True
    if len(t) > 10:
        words = t.split()
        if len(words) > 4 and all(len(w) <= 2 for w in words):
            return True
    return False

def sha256_file(filepath: Path | str) -> str:
    sha256 = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def count_lines(filepath: Path | str) -> int:
    n = 0
    with open(filepath, encoding="utf-8") as f:
        for _ in f:
            n += 1
    return n


def safe_json(text):
    """Return parsed JSON or None."""
    if not text:
        return None
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None


def normalize_paper_id(pid: str) -> str:
    """Strip .txt suffix from paper IDs for consistent referencing."""
    if pid and pid.endswith(".txt"):
        return pid[:-4]
    return pid


# ---------------------------------------------------------------------------
# Export: nodes.jsonl
# ---------------------------------------------------------------------------

def export_nodes(db: sqlite3.Connection, out_path: Path) -> int:
    """Export entities as nodes with ontology mappings and NER provenance."""
    c = db.cursor()

    # Pre-load controlled vocabulary mappings per entity
    cv_map: dict[int, list[dict]] = defaultdict(list)
    c.execute(
        "SELECT entity_id, vocabulary_name, vocabulary_id, vocabulary_uri, "
        "vocabulary_label, mapping_confidence, mapping_source, mapping_tier, "
        "is_canonical FROM controlled_vocabularies"
    )
    for row in c.fetchall():
        cv_map[row[0]].append({
            "vocabulary": row[1],
            "id": row[2],
            "uri": row[3] or "",
            "label": row[4] or "",
            "confidence": row[5],
            "source": row[6],
            "tier": row[7],
            "is_canonical": bool(row[8]),
        })

    # Determine primary grounding for each entity
    c.execute(
        "SELECT id, term, entity_type, confidence_score, paper_count, frequency, "
        "definition, contextual_definition, aliases, is_core_term, "
        "relevance_classification, is_computed_metric, "
        "UMLS_ID, OMOP, OLS, Bioportal, NCBITaxon, MeSH_UI, "
        "umls_mapped, umls_best_match, "
        "ner_gliner, ner_pubmedbert, ner_pubtator3, ner_qwen, ner_scispacy, "
        "source_scores FROM entities ORDER BY id"
    )

    n = 0
    with open(out_path, "w", encoding="utf-8") as f:
        for row in c.fetchall():
            (eid, term, etype, conf, pcount, freq, definition, ctx_def,
             aliases, is_core, rel_class, is_computed,
             umls_id, omop, ols, bioportal, ncbitaxon, mesh_ui,
             umls_mapped, umls_best,
             ner_g, ner_pb, ner_pt, ner_qw, ner_ss,
             source_scores) = row

            # Determine primary ontology source and ID
            ontology_source = None
            ontology_id = None
            if umls_id:
                ontology_source = "UMLS"
                ontology_id = umls_id
            elif ncbitaxon:
                ontology_source = "NCBITaxon"
                ontology_id = ncbitaxon
            elif mesh_ui:
                ontology_source = "MeSH"
                ontology_id = mesh_ui
            elif ols:
                ontology_source = "OLS"
                ontology_id = ols

            grounding_status = "grounded" if ontology_id else "ungrounded"

            # NER model provenance
            ner_models = []
            if ner_g:
                ner_models.append("gliner")
            if ner_pb:
                ner_models.append("pubmedbert")
            if ner_pt:
                ner_models.append("pubtator3")
            if ner_qw:
                ner_models.append("qwen")
            if ner_ss:
                ner_models.append("scispacy")

            node = {
                "id": eid,
                "name": term,
                "type": etype,
                "type_description": CDM_TYPE_DESCRIPTIONS.get(etype, ""),
                "confidence_score": conf,
                "paper_count": pcount,
                "frequency": freq,
                "definition": definition or "",
                "contextual_definition": ctx_def or "",
                "aliases": safe_json(aliases) if aliases else [],
                "is_core_term": bool(is_core) if is_core is not None else False,
                "relevance_classification": rel_class or "",
                "is_computed_metric": bool(is_computed) if is_computed is not None else False,
                "ontology_source": ontology_source,
                "ontology_id": ontology_id,
                "grounding_status": grounding_status,
                "umls_id": umls_id or "",
                "ols": ols or "",
                "ncbitaxon": ncbitaxon or "",
                "mesh_ui": mesh_ui or "",
                "umls_mapped": bool(umls_mapped) if umls_mapped is not None else False,
                "umls_best_match": umls_best or "",
                "ner_models": ner_models,
                "ner_source_scores": safe_json(source_scores) if source_scores else {},
                "ontology_mappings": cv_map.get(eid, []),
                "is_noise": is_entity_noise(term, conf),
            }
            f.write(json.dumps(node, ensure_ascii=False) + "\n")
            n += 1

    return n


# ---------------------------------------------------------------------------
# Export: edges.jsonl
# ---------------------------------------------------------------------------

def export_edges(db: sqlite3.Connection, out_path: Path) -> int:
    """Export relationships as edges with entity names and evidence."""
    c = db.cursor()

    # Pre-load evidence paper IDs per relationship
    ev_papers: dict[int, list[str]] = defaultdict(list)
    c.execute(
        "SELECT relationship_id, paper_id, source_model FROM edge_evidence"
    )
    ev_models: dict[int, list[str]] = defaultdict(list)
    for row in c.fetchall():
        rid, paper_id, source_model = row
        pid = normalize_paper_id(paper_id)
        ev_papers[rid].append(pid)
        if source_model:
            ev_models[rid].append(source_model)

    c.execute(
        "SELECT r.id, r.source_id, r.target_id, r.relationship_type, "
        "r.source_db, r.confidence, r.evidence, r.evidence_type, "
        "r.mechanism, r.ec_number, r.kegg_pathway, r.pubmed_ids, r.paper_doi, "
        "r.source_type, r.validation_status, r.npm_i, r.p_value, r.q_value, "
        "r.co_occurrence_count, r.eco_code, r.original_predicate, "
        "r.demotion_reason, r.direction_demoted_to, r.external_corroboration, "
        "r.confidence_basis, r.association_direction, r.study_type, "
        "e1.term, e1.entity_type, e2.term, e2.entity_type "
        "FROM relationships r "
        "JOIN entities e1 ON r.source_id = e1.id "
        "JOIN entities e2 ON r.target_id = e2.id "
        "ORDER BY r.id"
    )

    n = 0
    with open(out_path, "w", encoding="utf-8") as f:
        for row in c.fetchall():
            (rid, src_id, tgt_id, rel_type, src_db, conf, evidence,
             ev_type, mechanism, ec_num, kegg, pmids, doi,
             src_type, val_status, npm_i, p_val, q_val,
             co_count, eco_code, orig_pred,
             demotion_reason, dir_demoted, ext_corrob,
             conf_basis, assoc_dir, study_type,
             src_name, src_type_canon, tgt_name, tgt_type_canon) = row

            paper_ids = ev_papers.get(rid, [])
            edge = {
                "id": rid,
                "subject_id": src_id,
                "subject": src_name,
                "subject_type": src_type_canon,
                "predicate": rel_type,
                "original_predicate": orig_pred or "",
                "object_id": tgt_id,
                "object": tgt_name,
                "object_type": tgt_type_canon,
                "source_db": src_db or "",
                "source_type": src_type or "",
                "confidence": conf,
                "confidence_basis": conf_basis or "",
                "evidence": evidence or "",
                "evidence_type": ev_type or "",
                "mechanism": mechanism or "",
                "ec_number": ec_num or "",
                "kegg_pathway": kegg or "",
                "eco_code": eco_code or "",
                "study_type": study_type or "",
                "validation_status": val_status or "",
                "npm_i": npm_i,
                "p_value": p_val,
                "q_value": q_val,
                "co_occurrence_count": co_count,
                "pubmed_ids": pmids or "",
                "paper_doi": doi or "",
                "source_papers": paper_ids,
                "source_models": ev_models.get(rid, []),
                "demotion_reason": demotion_reason or "",
                "direction_demoted_to": dir_demoted or "",
                "external_corroboration": ext_corrob or "",
                "association_direction": assoc_dir or "",
            }
            f.write(json.dumps(edge, ensure_ascii=False) + "\n")
            n += 1

    return n


# ---------------------------------------------------------------------------
# Export: corpus
# ---------------------------------------------------------------------------

def export_corpus_metadata(db: sqlite3.Connection, out_path: Path) -> int:
    """Export BioProject metadata as corpus_metadata.jsonl."""
    c = db.cursor()
    c.execute(
        "SELECT project_id, title, link, amplicon, avg_length, bead_beating, "
        "kit, sample_type, condition, subjects, notes, host_organism, journal "
        "FROM projects ORDER BY project_id"
    )

    n = 0
    with open(out_path, "w", encoding="utf-8") as f:
        for row in c.fetchall():
            (pid, title, link, amplicon, avg_len, bead, kit, stype,
             condition, subjects, notes, host, journal) = row

            record = {
                "project_id": pid,
                "title": title or "",
                "link": link or "",
                "amplicon": amplicon or "",
                "avg_length": avg_len,
                "bead_beating": bool(bead) if bead is not None else None,
                "kit": kit or "",
                "sample_type": stype or "",
                "condition": condition or "",
                "subjects": subjects or "",
                "notes": notes or "",
                "host_organism": host or "",
                "journal": journal or "",
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            n += 1

    return n


def export_corpus_papers(db: sqlite3.Connection, papers_dir: Path,
                         out_path: Path) -> int:
    """Export per-paper text statistics as corpus_papers.jsonl."""
    c = db.cursor()

    # Count mentions and triples per project
    mention_counts: dict[str, int] = {}
    c.execute(
        "SELECT project_id, COUNT(*) FROM entity_project_mentions GROUP BY project_id"
    )
    for row in c.fetchall():
        mention_counts[row[0]] = row[1]

    # Count evidence per project from edge_evidence (normalize .txt suffix)
    ev_counts: dict[str, int] = {}
    c.execute(
        "SELECT paper_id, COUNT(*) FROM edge_evidence GROUP BY paper_id"
    )
    for row in c.fetchall():
        pid = normalize_paper_id(row[0])
        ev_counts[pid] = ev_counts.get(pid, 0) + row[1]

    n = 0
    with open(out_path, "w", encoding="utf-8") as f:
        for txt_file in sorted(papers_dir.glob("PRJ*.txt")):
            pid = txt_file.stem
            text = txt_file.read_text(encoding="utf-8", errors="replace")
            char_count = len(text)
            word_count = len(text.split())

            record = {
                "project_id": pid,
                "filename": txt_file.name,
                "char_count": char_count,
                "word_count": word_count,
                "mention_count": mention_counts.get(pid, 0),
                "evidence_count": ev_counts.get(pid, 0),
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            n += 1

    return n


def export_evidence_records(db: sqlite3.Connection, out_path: Path) -> int:
    """Export evidence records from edge_evidence joined with relationships.

    Each record carries an ``evidence_type`` discriminator:
    - ``verbatim_quote``  — the relationship has actual quoted text from the paper
    - ``co_occurrence_summary`` — the evidence text is a co-occurrence count string
    - ``empty`` — no evidence text
    """
    c = db.cursor()
    c.execute(
        "SELECT ee.id, ee.relationship_id, ee.paper_id, ee.char_start, "
        "ee.char_end, ee.source_model, ee.eco_code, "
        "r.evidence, r.relationship_type, r.source_id, r.target_id, "
        "e1.term, e2.term "
        "FROM edge_evidence ee "
        "JOIN relationships r ON ee.relationship_id = r.id "
        "JOIN entities e1 ON r.source_id = e1.id "
        "JOIN entities e2 ON r.target_id = e2.id "
        "ORDER BY ee.relationship_id, ee.id"
    )

    n = 0
    with open(out_path, "w", encoding="utf-8") as f:
        for row in c.fetchall():
            (eeid, rid, paper_id, char_start, char_end, source_model,
             eco_code, evidence, rel_type, src_id, tgt_id,
             src_name, tgt_name) = row

            ev_text = evidence or ""
            if ev_text and not ev_text.startswith("Co-occur"):
                ev_type = "verbatim_quote"
            elif ev_text:
                ev_type = "co_occurrence_summary"
            else:
                ev_type = "empty"

            record = {
                "evidence_id": eeid,
                "relationship_id": rid,
                "project_id": normalize_paper_id(paper_id),
                "char_start": char_start,
                "char_end": char_end,
                "source_model": source_model or "",
                "eco_code": eco_code or "",
                "evidence_text": ev_text,
                "evidence_type": ev_type,
                "predicate": rel_type,
                "subject": src_name,
                "object": tgt_name,
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            n += 1

    return n


# ---------------------------------------------------------------------------
# Export: CDM schema
# ---------------------------------------------------------------------------

def write_cdm_schema(db: sqlite3.Connection, out_path: Path,
                     n_nodes: int, n_edges: int,
                     n_mentions: int = 0, n_evidence: int = 0,
                     n_ontology_mappings: int = 0) -> None:
    """Write the CDM JSON schema document."""
    c = db.cursor()

    # Entity type distribution
    c.execute(
        "SELECT entity_type, COUNT(*) FROM entities GROUP BY entity_type ORDER BY COUNT(*) DESC"
    )
    entity_dist = {r[0]: r[1] for r in c.fetchall()}

    # Relationship type distribution
    c.execute(
        "SELECT relationship_type, COUNT(*) FROM relationships GROUP BY relationship_type ORDER BY COUNT(*) DESC"
    )
    rel_dist = {r[0]: r[1] for r in c.fetchall()}

    # Vocabulary distribution
    c.execute(
        "SELECT vocabulary_name, COUNT(*) FROM controlled_vocabularies GROUP BY vocabulary_name ORDER BY COUNT(*) DESC"
    )
    vocab_dist = {r[0]: r[1] for r in c.fetchall()}

    # ECO code distribution
    c.execute(
        "SELECT eco_code, COUNT(*) FROM relationships WHERE eco_code IS NOT NULL GROUP BY eco_code ORDER BY COUNT(*) DESC"
    )
    eco_dist = {r[0]: r[1] for r in c.fetchall()}

    # Study type distribution
    c.execute(
        "SELECT study_type, COUNT(*) FROM relationships WHERE study_type IS NOT NULL GROUP BY study_type ORDER BY COUNT(*) DESC"
    )
    study_dist = {r[0]: r[1] for r in c.fetchall()}

    # Validation status distribution
    c.execute(
        "SELECT validation_status, COUNT(*) FROM relationships GROUP BY validation_status ORDER BY COUNT(*) DESC"
    )
    val_dist = {r[0]: r[1] for r in c.fetchall()}

    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Microbiome Common Data Model (MCDM) v1.0",
        "description": (
            "Unified data model for the Microbiome Common Data Model (MCDM) "
            "knowledge graph release. Defines 14 entity types extracted from "
            "444 BioProject-associated full-text papers covering the human gut "
            "microbiome. Entities are extracted by a multi-NER pipeline "
            "(GLiNER, PubMedBERT, PubTator3, sciSpaCy, Qwen 3.5:9b LLM) and "
            "cleaned via a 5-pass quality pipeline (LLM type correction, "
            "semantic deduplication, LLM noise flagging, deterministic rule-based "
            "cleanup, heuristic ontology review). Relationships are "
            "derived from LLM-extracted triples and statistical co-occurrence, "
            "grounded to 25 biomedical ontologies."
        ),
        "version": "1.0.0",
        "created": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "statistics": {
            "total_entities": n_nodes,
            "total_relationships": n_edges,
            "total_projects": 444,
            "total_mentions": n_mentions,
            "total_evidence_rows": n_evidence,
            "total_ontology_mappings": n_ontology_mappings or sum(vocab_dist.values()),
            "entity_type_distribution": entity_dist,
            "relationship_type_distribution": rel_dist,
            "vocabulary_distribution": vocab_dist,
            "eco_code_distribution": eco_dist,
            "study_type_distribution": study_dist,
            "validation_status_distribution": val_dist,
        },
        "entity_types": {
            "Entity": {
                "description": "A unique biomedical entity (node) in the microbiome knowledge graph.",
                "primary_key": "id",
                "datasets": ["nodes.jsonl"],
                "properties": {
                    "id": {"type": "integer", "description": "Auto-increment primary key", "required": True},
                    "name": {"type": "string", "description": "Canonical entity term", "required": True},
                    "type": {"type": "string", "vocabulary": "entity_type", "description": "One of 14 CDM entity types", "required": True},
                    "type_description": {"type": "string", "description": "Human-readable type description"},
                    "confidence_score": {"type": "number", "description": "Entity confidence (0.0 = noise-flagged)"},
                    "paper_count": {"type": "integer", "description": "Number of papers mentioning this entity"},
                    "frequency": {"type": "integer", "description": "Total mention frequency"},
                    "definition": {"type": "string", "description": "Entity definition (if available)"},
                    "contextual_definition": {"type": "string", "description": "Context-specific definition"},
                    "aliases": {"type": "array", "items": {"type": "string"}, "description": "Alternative names"},
                    "is_core_term": {"type": "boolean", "description": "Whether this is a core microbiome term"},
                    "relevance_classification": {"type": "string", "description": "Relevance classification"},
                    "is_computed_metric": {"type": "boolean", "description": "Whether this is a computed metric"},
                    "ontology_source": {"type": "string", "description": "Primary ontology source (UMLS, NCBITaxon, MeSH, OLS)"},
                    "ontology_id": {"type": "string", "description": "Primary ontology identifier"},
                    "grounding_status": {"type": "string", "vocabulary": "grounding_status", "description": "grounded or ungrounded"},
                    "umls_id": {"type": "string", "description": "UMLS CUI"},
                    "ols": {"type": "string", "description": "OLS (Ontology Lookup Service) URI"},
                    "ncbitaxon": {"type": "string", "description": "NCBI Taxonomy ID"},
                    "mesh_ui": {"type": "string", "description": "MeSH UI"},
                    "umls_mapped": {"type": "boolean", "description": "Whether UMLS mapping exists"},
                    "umls_best_match": {"type": "string", "description": "Best UMLS match label"},
                    "ner_models": {"type": "array", "items": {"type": "string", "vocabulary": "ner_model"}, "description": "NER models that detected this entity"},
                    "ner_source_scores": {"type": "object", "description": "Per-model confidence scores"},
                    "ontology_mappings": {"type": "array", "items": {"type": "object"}, "description": "All controlled vocabulary mappings (UMLS, MeSH, NCIT, SNOMEDCT, etc.)"},
                    "is_noise": {"type": "boolean", "description": "True if flagged as noise (confidence_score=0, unrecognised 2-char term, or spaced-out letter sequence)"},
                },
            },
        },
        "edge_types": {
            "Relationship": {
                "description": "A knowledge graph edge (triple) connecting two entities.",
                "primary_key": "id",
                "datasets": ["edges.jsonl"],
                "properties": {
                    "id": {"type": "integer", "description": "Relationship ID", "required": True},
                    "subject_id": {"type": "integer", "description": "Foreign key to Entity.id (subject)", "required": True},
                    "subject": {"type": "string", "description": "Subject entity name", "required": True},
                    "subject_type": {"type": "string", "vocabulary": "entity_type", "description": "Subject entity type"},
                    "predicate": {"type": "string", "vocabulary": "relationship_type", "description": "Relationship type", "required": True},
                    "original_predicate": {"type": "string", "description": "Original predicate before normalization"},
                    "object_id": {"type": "integer", "description": "Foreign key to Entity.id (object)", "required": True},
                    "object": {"type": "string", "description": "Object entity name", "required": True},
                    "object_type": {"type": "string", "vocabulary": "entity_type", "description": "Object entity type"},
                    "source_db": {"type": "string", "description": "Source database (co-occurrence, llm_triple, biological_kb)"},
                    "source_type": {"type": "string", "description": "Source type classification"},
                    "confidence": {"type": "number", "description": "Confidence score (0.0-1.0)"},
                    "confidence_basis": {"type": "string", "description": "Breakdown of confidence calculation"},
                    "evidence": {"type": "string", "description": "Verbatim evidence text"},
                    "evidence_type": {"type": "string", "description": "Type of evidence"},
                    "eco_code": {"type": "string", "description": "Evidence and Conclusion Ontology (ECO) code"},
                    "study_type": {"type": "string", "vocabulary": "study_type", "description": "Study design classification"},
                    "validation_status": {"type": "string", "vocabulary": "validation_status", "description": "Validation status"},
                    "npm_i": {"type": "number", "description": "Normalized Pointwise Mutual Information (for co-occurrence edges)"},
                    "p_value": {"type": "number", "description": "Statistical p-value (for co-occurrence edges)"},
                    "q_value": {"type": "number", "description": "Adjusted q-value (FDR corrected)"},
                    "co_occurrence_count": {"type": "integer", "description": "Number of co-occurring papers"},
                    "source_papers": {"type": "array", "items": {"type": "string"}, "description": "BioProject IDs providing evidence"},
                    "source_models": {"type": "array", "items": {"type": "string"}, "description": "Models that extracted this evidence"},
                    "mechanism": {"type": "string", "description": "Mechanism description (if applicable)"},
                    "ec_number": {"type": "string", "description": "Enzyme Commission number"},
                    "kegg_pathway": {"type": "string", "description": "KEGG pathway identifier"},
                    "association_direction": {"type": "string", "description": "Direction of association"},
                    "demotion_reason": {"type": "string", "description": "Reason for confidence demotion (if any)"},
                    "external_corroboration": {"type": "string", "description": "External corroboration info"},
                },
            },
        },
        "vocabularies": {
            "entity_type": {
                "description": "14 CDM entity types",
                "values": CDM_TYPES,
            },
            "relationship_type": {
                "description": "14 relationship (predicate) types",
                "values": RELATIONSHIP_TYPES,
            },
            "grounding_status": {
                "description": "Whether an entity is grounded to an ontology ID",
                "values": ["grounded", "ungrounded"],
            },
            "ner_model": {
                "description": "NER models in the multi-extraction pipeline",
                "values": ["gliner", "pubmedbert", "pubtator3", "qwen", "scispacy"],
            },
            "study_type": {
                "description": "Study design classifications",
                "values": list(study_dist.keys()),
            },
            "validation_status": {
                "description": "Validation status of relationships",
                "values": list(val_dist.keys()),
            },
            "eco_code": {
                "description": "Evidence and Conclusion Ontology (ECO) codes",
                "values": list(eco_dist.keys()),
            },
            "ontology_vocabulary": {
                "description": "Biomedical ontology vocabularies used for entity grounding",
                "values": list(vocab_dist.keys()),
            },
        },
        "relationships": [
            {
                "name": "Entity 1—N Relationship (subject)",
                "from": "Entity",
                "to": "Relationship",
                "join": "Entity.id = Relationship.subject_id",
                "cardinality": "one-to-many",
            },
            {
                "name": "Entity 1—N Relationship (object)",
                "from": "Entity",
                "to": "Relationship",
                "join": "Entity.id = Relationship.object_id",
                "cardinality": "one-to-many",
            },
            {
                "name": "BioProject N—M Entity (via entity_project_mentions)",
                "from": "BioProject",
                "to": "Entity",
                "join": "entity_project_mentions.project_id = BioProject.project_id AND entity_project_mentions.entity_id = Entity.id",
                "cardinality": "many-to-many",
            },
            {
                "name": "BioProject N—M Relationship (via edge_evidence)",
                "from": "BioProject",
                "to": "Relationship",
                "join": "edge_evidence.paper_id = BioProject.project_id AND edge_evidence.relationship_id = Relationship.id",
                "cardinality": "many-to-many",
            },
        ],
        "reference": (
            "Abdill, R. J., Graham, S. P., Rubinetti, V., et al. (2025). "
            "Integration of 168,000 samples reveals global patterns of the "
            "human gut microbiome. Cell 188(4):1100-1118.e17. "
            "DOI: 10.1016/j.cell.2024.12.017"
        ),
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(schema, f, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Export: cleanup report
# ---------------------------------------------------------------------------

def write_cleanup_report(out_path: Path) -> None:
    """Write cleanup summary from checkpoint files."""
    report = {
        "version": "1.0.0",
        "description": (
            "Multi-stage entity cleanup pipeline applied to the MCDM knowledge "
            "graph. Pass 1: LLM-based type correction. Pass 2: bge-m3 semantic "
            "deduplication (cosine >= 0.90). Pass 3: LLM-based noise flagging. "
            "Pass 4: deterministic rule-based cleanup. Pass 5: heuristic ontology "
            "review with manual adjudication."
        ),
        "passes": {},
    }

    # Pass 1: type correction
    p1_path = CHECKPOINT_DIR / "pass1_type_correction.json"
    if p1_path.exists():
        p1 = json.loads(p1_path.read_text())
        report["passes"]["pass1_type_correction"] = {
            "total_corrections": len(p1),
            "description": "LLM-based entity type correction across 2 rounds",
            "sample": {k: p1[k] for k in list(p1.keys())[:5]},
        }

    # Pass 2: dedup
    p2_path = CHECKPOINT_DIR / "pass2_dedup.json"
    if p2_path.exists():
        p2 = json.loads(p2_path.read_text())
        report["passes"]["pass2_semantic_dedup"] = {
            "total_merges": len(p2.get("remap", {})),
            "description": "bge-m3 embedding-based semantic deduplication (cosine >= 0.90)",
            "completed_types": p2.get("completed_types", []),
            "sample_remap": {k: p2["remap"][k] for k in list(p2.get("remap", {}).keys())[:5]},
        }

    # Pass 3: noise flagging (full run — ALL entities)
    p3_path = CHECKPOINT_DIR / "pass3_noise_full.json"
    if not p3_path.exists():
        p3_path = CHECKPOINT_DIR / "pass3_noise.json"  # fallback to old
    if p3_path.exists():
        p3 = json.loads(p3_path.read_text())
        noise_count = sum(1 for v in p3.values() if isinstance(v, dict) and v.get("is_noise"))
        generic_count = sum(1 for v in p3.values() if isinstance(v, dict) and not v.get("is_real_term", True) and not v.get("is_noise"))
        real_count = sum(1 for v in p3.values() if isinstance(v, dict) and v.get("is_real_term", True) and not v.get("is_noise"))
        report["passes"]["pass3_noise_flagging"] = {
            "total_evaluated": len(p3),
            "noise_deleted": noise_count,
            "generic_deprioritized": generic_count,
            "confirmed_real": real_count,
            "description": "LLM-based noise detection on ALL entities — noise entities physically deleted, generic words de-prioritized (confidence=0)",
            "sample": {k: p3[k] for k in list(p3.keys())[:5]},
        }

    # Pass 4: deterministic rule-based cleanup
    p4_path = CHECKPOINT_DIR / "deterministic_cleanup.json"
    if p4_path.exists():
        p4 = json.loads(p4_path.read_text())
        report["passes"]["pass4_deterministic_cleanup"] = p4
    else:
        # Try to read from the ontology_review directory
        det_review_dir = CDM_OUTPUT / "ontology_review"
        det_flagged = det_review_dir / "deterministic_cleanup_stats.json"
        if det_flagged.exists():
            p4 = json.loads(det_flagged.read_text())
            report["passes"]["pass4_deterministic_cleanup"] = p4

    # Pass 5: heuristic ontology review
    p5_path = CHECKPOINT_DIR / "ontology_review_stats.json"
    if p5_path.exists():
        p5 = json.loads(p5_path.read_text())
        report["passes"]["pass5_ontology_review"] = p5
    else:
        # Fallback: try flagged_for_removal.json (may be incomplete if sanity re-scan overwrote it)
        ontology_review_dir = CDM_OUTPUT / "ontology_review"
        flagged_path = ontology_review_dir / "flagged_for_removal.json"
        if flagged_path.exists():
            flagged = json.loads(flagged_path.read_text())
            to_delete = [i for i in flagged if i.get("reason") not in ("wrong_type_fix", "adjective_review")]
            to_fix = [i for i in flagged if i.get("reason") == "wrong_type_fix"]
            to_review = [i for i in flagged if i.get("reason") == "adjective_review"]
            by_reason: dict[str, int] = {}
            for item in flagged:
                r = item.get("reason", "unknown")
                by_reason[r] = by_reason.get(r, 0) + 1
            report["passes"]["pass5_ontology_review"] = {
                "total_flagged": len(flagged),
                "deleted": len(to_delete),
                "type_fixed": len(to_fix),
                "manual_review": len(to_review),
                "reasons": by_reason,
                "description": "Heuristic-based review of all entities with ontology mappings — generic words, adjectives, verb forms, OCR fragments, time units, and wrong-type entities flagged for deletion or type correction",
            }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)


def read_cleanup_stats() -> dict:
    """Read actual cleanup stats from checkpoint files."""
    stats = {"pass1_corrections": 0, "pass2_merges": 0, "pass3_flagged": 0,
             "pass3_noise": 0, "pass4_deterministic": 0, "pass5_ontology_review": 0}

    p1_path = CHECKPOINT_DIR / "pass1_type_correction.json"
    if p1_path.exists():
        p1 = json.loads(p1_path.read_text())
        stats["pass1_corrections"] = len(p1)

    p2_path = CHECKPOINT_DIR / "pass2_dedup.json"
    if p2_path.exists():
        p2 = json.loads(p2_path.read_text())
        stats["pass2_merges"] = len(p2.get("remap", {}))

    p3_path = CHECKPOINT_DIR / "pass3_noise_full.json"
    if not p3_path.exists():
        p3_path = CHECKPOINT_DIR / "pass3_noise.json"  # fallback
    if p3_path.exists():
        p3 = json.loads(p3_path.read_text())
        stats["pass3_flagged"] = len(p3)
        stats["pass3_noise"] = sum(1 for v in p3.values() if isinstance(v, dict) and v.get("is_noise"))
        stats["pass3_generic"] = sum(1 for v in p3.values() if isinstance(v, dict) and not v.get("is_real_term", True) and not v.get("is_noise"))

    p4_path = CHECKPOINT_DIR / "deterministic_cleanup.json"
    if p4_path.exists():
        p4 = json.loads(p4_path.read_text())
        stats["pass4_deterministic"] = p4.get("noise_total", 0)

    p5_stats_path = CHECKPOINT_DIR / "ontology_review_stats.json"
    if p5_stats_path.exists():
        p5 = json.loads(p5_stats_path.read_text())
        stats["pass5_ontology_review"] = p5.get("deleted", 0)
    else:
        ontology_review_dir = CDM_OUTPUT / "ontology_review"
        flagged_path = ontology_review_dir / "flagged_for_removal.json"
        if flagged_path.exists():
            flagged = json.loads(flagged_path.read_text())
            stats["pass5_ontology_review"] = sum(1 for i in flagged if i.get("reason") not in ("wrong_type_fix", "adjective_review"))

    return stats


# ---------------------------------------------------------------------------
# Export: JSON-LD context
# ---------------------------------------------------------------------------

def write_jsonld_context(out_path: Path) -> None:
    """Write JSON-LD context for the MCDM."""
    ctx = {
        "@context": {
            "@vocab": "https://microbiome-cdm.org/vocab#",
            "mcdm": "https://microbiome-cdm.org/vocab#",
            "schema": "https://schema.org/",
            "obo": "http://purl.obolibrary.org/obo/",
            "eco": "http://purl.obolibrary.org/obo/ECO_",
            "id": "@id",
            "name": {"@id": "schema:name"},
            "type": {"@id": "@type"},
            "Entity": {"@id": "mcdm:Entity"},
            "Relationship": {"@id": "mcdm:Relationship"},
            "subject": {"@id": "mcdm:subject", "@type": "@id"},
            "object": {"@id": "mcdm:object", "@type": "@id"},
            "predicate": {"@id": "mcdm:predicate"},
            "evidence": {"@id": "mcdm:evidence"},
            "confidence": {"@id": "mcdm:confidence", "@type": "xsd:number"},
            "eco_code": {"@id": "eco:@id"},
            "study_type": {"@id": "mcdm:study_type"},
            "ontology_id": {"@id": "mcdm:ontology_id"},
            "ontology_source": {"@id": "mcdm:ontology_source"},
            "grounding_status": {"@id": "mcdm:grounding_status"},
            "paper_count": {"@id": "mcdm:paper_count", "@type": "xsd:integer"},
            "frequency": {"@id": "mcdm:frequency", "@type": "xsd:integer"},
            "ner_models": {"@id": "mcdm:ner_models", "@container": "@set"},
            "source_papers": {"@id": "mcdm:source_papers", "@container": "@set"},
            "xsd": "http://www.w3.org/2001/XMLSchema#",
        }
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(ctx, f, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Export: data catalogue (DCAT-style)
# ---------------------------------------------------------------------------

def write_data_catalogue(out_path: Path, n_nodes: int, n_edges: int,
                         n_projects: int, n_evidence: int) -> None:
    """Write DCAT-style data catalogue."""
    catalogue = {
        "@context": {
            "@vocab": "http://www.w3.org/ns/dcat#",
            "dcterms": "http://purl.org/dc/terms/",
            "foaf": "http://xmlns.com/foaf/0.1/",
        },
        "@type": "dcat:Catalog",
        "dcterms:title": "Microbiome CDM v1.0 Data Catalogue",
        "dcterms:description": (
            "Catalogue of datasets in the Microbiome Common Data Model (MCDM) "
            "v1.0 Zenodo release."
        ),
        "dcterms:issued": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "dcterms:creator": {
            "foaf:name": "Jasmeer Kalra",
            "foaf:affiliation": "University of Bonn / Fraunhofer SCAI",
        },
        "dcterms:license": "https://creativecommons.org/licenses/by/4.0/",
        "datasets": [
            {
                "@type": "dcat:Dataset",
                "dcterms:title": "Entities (Nodes)",
                "dcterms:description": f"{n_nodes:,} biomedical entities extracted by multi-NER pipeline",
                "dcat:distribution": {
                    "dcat:downloadURL": "data/nodes.jsonl",
                    "dcat:mediaType": "application/jsonl",
                },
                "dcat:keyword": ["entities", "nodes", "NER", "microbiome"],
                "records": n_nodes,
            },
            {
                "@type": "dcat:Dataset",
                "dcterms:title": "Relationships (Edges)",
                "dcterms:description": f"{n_edges:,} knowledge graph relationships (triples) with evidence",
                "dcat:distribution": {
                    "dcat:downloadURL": "data/edges.jsonl",
                    "dcat:mediaType": "application/jsonl",
                },
                "dcat:keyword": ["relationships", "edges", "triples", "co-occurrence", "LLM extraction"],
                "records": n_edges,
            },
            {
                "@type": "dcat:Dataset",
                "dcterms:title": "Corpus Metadata",
                "dcterms:description": f"{n_projects} BioProject metadata records from the 168K-sample gut microbiome compendium",
                "dcat:distribution": {
                    "dcat:downloadURL": "data/corpus/corpus_metadata.jsonl",
                    "dcat:mediaType": "application/jsonl",
                },
                "dcat:keyword": ["corpus", "BioProject", "metadata"],
                "records": n_projects,
            },
            {
                "@type": "dcat:Dataset",
                "dcterms:title": "Corpus Papers",
                "dcterms:description": "Per-paper text statistics for the 444 BioProject full-text papers",
                "dcat:distribution": {
                    "dcat:downloadURL": "data/corpus/corpus_papers.jsonl",
                    "dcat:mediaType": "application/jsonl",
                },
                "dcat:keyword": ["corpus", "papers", "text statistics"],
                "records": n_projects,
            },
            {
                "@type": "dcat:Dataset",
                "dcterms:title": "Evidence Records",
                "dcterms:description": f"{n_evidence:,} evidence records linking relationships to source papers (includes verbatim quotes and co-occurrence summaries)",
                "dcat:distribution": {
                    "dcat:downloadURL": "data/corpus/evidence_records.jsonl",
                    "dcat:mediaType": "application/jsonl",
                },
                "dcat:keyword": ["evidence", "provenance", "traceability"],
                "records": n_evidence,
            },
            {
                "@type": "dcat:Dataset",
                "dcterms:title": "CDM Schema",
                "dcterms:description": "Common Data Model schema (JSON) defining 14 entity types, 14 relationship types, and controlled vocabularies",
                "dcat:distribution": {
                    "dcat:downloadURL": "data/cdm.json",
                    "dcat:mediaType": "application/json",
                },
                "dcat:keyword": ["schema", "CDM", "data model"],
            },
            {
                "@type": "dcat:Dataset",
                "dcterms:title": "Cleanup Report",
                "dcterms:description": "5-pass entity cleanup summary (LLM type correction, semantic dedup, LLM noise flagging, deterministic cleanup, ontology review)",
                "dcat:distribution": {
                    "dcat:downloadURL": "data/cleanup_report.json",
                    "dcat:mediaType": "application/json",
                },
                "dcat:keyword": ["quality", "cleanup", "LLM", "dedup"],
            },
        ],
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(catalogue, f, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Export: corpus schema
# ---------------------------------------------------------------------------

def write_corpus_schema(out_path: Path) -> None:
    """Write corpus schema document."""
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "MCDM Corpus Schema v1.0",
        "description": "Schema for corpus files in the MCDM Zenodo release.",
        "datasets": {
            "corpus_metadata.jsonl": {
                "description": "BioProject metadata records",
                "primary_key": "project_id",
                "properties": {
                    "project_id": {"type": "string", "description": "BioProject accession (e.g., PRJEB3079)", "required": True},
                    "title": {"type": "string", "description": "Project title"},
                    "link": {"type": "string", "description": "URL to project page"},
                    "amplicon": {"type": "string", "description": "Amplicon region (e.g., V4)"},
                    "avg_length": {"type": "number", "description": "Average read length"},
                    "bead_beating": {"type": "boolean", "description": "Whether bead beating was used"},
                    "kit": {"type": "string", "description": "DNA extraction kit"},
                    "sample_type": {"type": "string", "description": "Sample type"},
                    "condition": {"type": "string", "description": "Study condition"},
                    "subjects": {"type": "string", "description": "Number of subjects"},
                    "notes": {"type": "string", "description": "Additional notes"},
                    "host_organism": {"type": "string", "description": "Host organism"},
                    "journal": {"type": "string", "description": "Journal of publication"},
                },
            },
            "corpus_papers.jsonl": {
                "description": "Per-paper text statistics",
                "primary_key": "project_id",
                "properties": {
                    "project_id": {"type": "string", "required": True},
                    "filename": {"type": "string", "description": "Text file name"},
                    "char_count": {"type": "integer", "description": "Total character count"},
                    "word_count": {"type": "integer", "description": "Total word count"},
                    "mention_count": {"type": "integer", "description": "Entity mentions in this paper"},
                    "evidence_count": {"type": "integer", "description": "Evidence rows linked to this paper"},
                },
            },
            "evidence_records.jsonl": {
                "description": "Evidence records linking relationships to source papers",
                "primary_key": "evidence_id",
                "properties": {
                    "evidence_id": {"type": "integer", "required": True},
                    "relationship_id": {"type": "integer", "description": "Foreign key to edges.jsonl:id"},
                    "project_id": {"type": "string", "description": "BioProject accession"},
                    "char_start": {"type": "integer", "nullable": True, "description": "Character offset in source text (NULL for all records in v1.0)"},
                    "char_end": {"type": "integer", "nullable": True, "description": "Character offset end in source text (NULL for all records in v1.0)"},
                    "source_model": {"type": "string", "description": "Model that extracted this evidence"},
                    "eco_code": {"type": "string", "description": "ECO code for this evidence"},
                    "evidence_text": {"type": "string", "description": "Evidence text — verbatim quote, co-occurrence summary, or empty"},
                    "evidence_type": {"type": "string", "description": "One of: verbatim_quote, co_occurrence_summary, empty"},
                    "predicate": {"type": "string", "description": "Relationship type"},
                    "subject": {"type": "string", "description": "Subject entity name"},
                    "object": {"type": "string", "description": "Object entity name"},
                },
            },
        },
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(schema, f, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Export: corpus data manifest
# ---------------------------------------------------------------------------

def write_corpus_manifest(corpus_dir: Path) -> None:
    """Write data_manifest.json for corpus directory."""
    manifest = {
        "version": "1.0.0",
        "created": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "files": {},
    }
    for f in sorted(corpus_dir.iterdir()):
        if f.is_file() and f.name != "data_manifest.json":
            manifest["files"][f.name] = {
                "size_bytes": f.stat().st_size,
                "sha256": sha256_file(f),
            }
    with open(corpus_dir / "data_manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Export: README files
# ---------------------------------------------------------------------------

def write_corpus_readme(out_path: Path, n_projects: int, n_evidence: int,
                        n_verbatim: int = 0, n_cooccur_sum: int = 0) -> None:
    """Write README_corpus.md."""
    content = f"""# MCDM Corpus v1.0

This directory contains the corpus files for the Microbiome Common Data Model (MCDM) v1.0 release.

## Files

| File | Format | Records | Description |
|------|--------|---------|-------------|
| `corpus_metadata.jsonl` | JSONL | {n_projects} | BioProject metadata (title, amplicon, kit, host, etc.) |
| `corpus_papers.jsonl` | JSONL | {n_projects} | Per-paper text statistics (char/word counts, mention/evidence counts) |
| `evidence_records.jsonl` | JSONL | {n_evidence:,} | Evidence records linking relationships to source papers |
| `corpus_schema.json` | JSON | 1 | Schema for the corpus files |
| `data_manifest.json` | JSON | 1 | Manifest with SHA-256 checksums |

## Corpus Source

The corpus consists of {n_projects} BioProject-associated full-text papers from the
168,464-sample human gut microbiome compendium (Abdill et al., 2025, *Cell*).

Each paper is a `.txt` file named by BioProject accession (e.g., `PRJEB3079.txt`).
Full text is NOT redistributed in this release — only metadata and statistics are
included here. The text files are available in the project repository under
`data/papers_txt/` (gitignored due to size).

## Evidence Records (`evidence_records.jsonl`)

Each record links a knowledge-graph edge (relationship) to the source paper that
provides evidence for it. The `evidence_type` field discriminates three kinds:

| `evidence_type` | Description | Approx. count |
|-----------------|-------------|---------------|
| `verbatim_quote` | Actual quoted text excerpted from the paper | ~{n_verbatim:,} |
| `co_occurrence_summary` | Co-occurrence count string (e.g. "Co-occur in N paper(s)") | ~{n_cooccur_sum:,} |
| `empty` | No evidence text available | ~{n_evidence - n_verbatim - n_cooccur_sum:,} |

**Note:** `char_start` and `char_end` are NULL for all records in v1.0.
Character-offset provenance will be added in a future release.

## Referencing

Papers are identified by their NCBI/ENA BioProject accession (e.g., `PRJEB3079`).
The `project_id` field is the primary key used across all corpus files and is
referenced by `source_papers[]` in `edges.jsonl` and `project_id` in
`evidence_records.jsonl`.

## Reference

> Abdill, R. J., Graham, S. P., Rubinetti, V., et al. (2025).
> *Integration of 168,000 samples reveals global patterns of the human gut microbiome.*
> **Cell** 188(4):1100-1118.e17. DOI: 10.1016/j.cell.2024.12.017
"""
    out_path.write_text(content, encoding="utf-8")


def write_readme(out_path: Path, n_nodes: int, n_edges: int, n_projects: int,
                  n_evidence: int, n_mentions: int,
                  cleanup: dict | None = None,
                  source_dist: dict | None = None,
                  n_verbatim: int = 0, n_cooccur_sum: int = 0) -> None:
    """Write top-level README.md."""
    if source_dist is None:
        source_dist = {}
    n_llm_triple = source_dist.get("llm_triple", 0)
    n_bio_kb = source_dist.get("biological_kb", 0)
    n_cooccur_kb = source_dist.get("co-occurrence+kb", 0)
    n_cooccur = source_dist.get("co-occurrence", 0)
    n_structured = n_llm_triple + n_bio_kb + n_cooccur_kb
    content = f"""# Microbiome Common Data Model (MCDM) v1.0

A knowledge graph and corpus representing biomedical entities and relationships
extracted from {n_projects} BioProject-associated full-text papers covering the
human gut microbiome.

## Contents

| Path | Format | Records | Description |
|------|--------|---------|-------------|
| `data/nodes.jsonl` | JSONL | {n_nodes:,} | Biomedical entities (nodes) with ontology mappings |
| `data/edges.jsonl` | JSONL | {n_edges:,} | Knowledge graph relationships (edges/triples) with evidence |
| `data/cdm.json` | JSON | 1 | Common Data Model schema (14 entity types, 14 relationship types) |
| `data/cdm_context.jsonld` | JSON-LD | 1 | JSON-LD context for the CDM |
| `data/data_catalogue.json` | JSON | 1 | DCAT-style dataset inventory |
| `data/cleanup_report.json` | JSON | 1 | 5-pass entity cleanup summary |
| `data/corpus/corpus_metadata.jsonl` | JSONL | {n_projects} | BioProject metadata |
| `data/corpus/corpus_papers.jsonl` | JSONL | {n_projects} | Per-paper text statistics |
| `data/corpus/evidence_records.jsonl` | JSONL | {n_evidence:,} | Evidence records linking edges to papers |
| `data/corpus/corpus_schema.json` | JSON | 1 | Corpus file schema |
| `data/corpus/data_manifest.json` | JSON | 1 | Corpus manifest with checksums |
| `data/corpus/README_corpus.md` | Markdown | 1 | Corpus documentation |
| `zenodo_metadata.json` | JSON | 1 | Zenodo deposition metadata |
| `zenodo_upload_manifest.md` | Markdown | 1 | File list with SHA-256 checksums |

## Overview

The MCDM knowledge graph contains:

- **{n_nodes:,} entities** across 14 biomedical types (ORGANISM, CHEMICAL, DISEASE,
  PROTEIN, DNA_RNA, CELL_TYPE, GENOMICS, PATHWAY, LAB_METHOD, DATA_ANALYSIS,
  SAMPLE_METHOD, CLINICAL, EXPERIMENTAL_METHOD, STUDY_DESIGN)
- **{n_edges:,} relationships** across 14 predicate types (CO_OCCURS_WITH,
  ASSOCIATED_WITH, ENRICHED_IN, DEPLETED_IN, PRODUCES, TREATS, etc.)
- **{n_mentions:,} entity mentions** with character offsets from the NER pipeline
- **{n_evidence:,} evidence records** linking relationships to source papers
- **25 biomedical ontologies** for entity grounding (UMLS, MeSH, NCIT, SNOMEDCT,
  NCBITaxon, CHEBI, MONDO, HP, GO, RXNORM, OMIM, LOINC, DOID, PR, HGNC, etc.)

### Relationship Types

| Source | Count | Description |
|--------|-------|-------------|
| `llm_triple` | {n_llm_triple:,} | LLM-extracted semantic triples (subject–predicate–object) |
| `biological_kb` | {n_bio_kb:,} | Curated biological knowledge-base edges |
| `co-occurrence+kb` | {n_cooccur_kb:,} | Co-occurrence edges enriched with KB evidence |
| `co-occurrence` | {n_cooccur:,} | Statistical co-occurrence associations (NPMI, p-value, q-value) |

The **{n_structured:,} structured edges** (`llm_triple` + `biological_kb` + `co-occurrence+kb`)
carry typed predicates (ASSOCIATED_WITH, PRODUCES, TREATS, ENRICHED_IN, etc.) and
represent the semantically meaningful core of the knowledge graph. The remaining
co-occurrence edges are statistical associations, not causally validated
relationships.

## Extraction Pipeline

Entities were extracted by a multi-NER pipeline combining 5 models:
- **GLiNER** — generalist NER model
- **PubMedBERT** — domain-specific BERT NER
- **PubTator3** — biomedical entity annotation
- **sciSpaCy** — scientific text NER
- **Qwen 3.5:9b** — LLM-based extraction via Ollama

## Entity Cleanup (5-Pass Pipeline)

1. **Type correction** (Pass 1): {cleanup['pass1_corrections']:,} LLM-based entity type corrections across 2 rounds
2. **Semantic deduplication** (Pass 2): {cleanup['pass2_merges']:,} entities merged via bge-m3 embedding similarity (cosine >= 0.90)
3. **Noise flagging** (Pass 3): {cleanup['pass3_flagged']:,} entities flagged, {cleanup['pass3_noise']:,} set to confidence_score=0
4. **Deterministic cleanup** (Pass 4): {cleanup['pass4_deterministic']:,} entities deleted via rule-based detection (author names, geographic names, journal names, company names, stopwords, OCR artifacts)
5. **Ontology review** (Pass 5): {cleanup['pass5_ontology_review']:,} entities deleted via heuristic review (generic words, adjectives, verb forms, OCR fragments, time units, wrong-type assignments)

In the exported data, `is_noise` is True for:
- Entities with `confidence_score = 0` (LLM-flagged noise)
- 2-character entity names not in the biomedical abbreviation whitelist
  (37 recognised abbreviations such as AD, CD, DC, IL, KO, CT, pH are preserved;
  273 ambiguous 2-char strings such as AA, Bv, Cβ are flagged)
- Spaced-out single-letter sequences (e.g. "O R I G I N A L A R T I C L E")

See `data/cleanup_report.json` for full details.

## Evidence and Traceability

Every relationship is anchored to at least one evidence record from the source
literature, forming a traceable chain:

BioProject → Paper text → Evidence record → Relationship → Entity

The `evidence_records.jsonl` file contains {n_evidence:,} records, each with an
`evidence_type` discriminator:

| `evidence_type` | Description | Approx. count |
|-----------------|-------------|---------------|
| `verbatim_quote` | Actual text excerpted from the source paper | ~{n_verbatim:,} |
| `co_occurrence_summary` | Co-occurrence count string (e.g. "Co-occur in N paper(s)") | ~{n_cooccur_sum:,} |
| `empty` | No evidence text available | ~{n_evidence - n_verbatim - n_cooccur_sum:,} |

**Note:** `char_start` and `char_end` are NULL for all evidence records in v1.0.

### Coverage of optional edge fields by source

| Field | `llm_triple` | `biological_kb` | `co-occurrence` | `co-occurrence+kb` |
|-------|-------------|-----------------|-----------------|---------------------|
| `eco_code` | 95.3% | 99.5% | 100% | 100% |
| `study_type` | 100% | 14.4% | 100% | 100% |
| `npm_i` | NULL | NULL | 100% | 100% |

`npm_i` (NPMI co-occurrence strength) is only populated for co-occurrence-derived
edges. `study_type` is sparse on `biological_kb` edges because those edges
originate from a curated knowledge base rather than study-classified extractions.

## Ontology Grounding

| Ontology | Mappings |
|----------|----------|
| UMLS | 34,068 |
| MeSH | 24,184 |
| NCIT | 14,496 |
| SNOMEDCT | 13,864 |
| NCBITaxon | 5,809 |
| CHEBI | 2,958 |
| MONDO | 1,396 |
| HP | 1,209 |
| GO | 895 |
| (+ 16 more) | ... |

**Grounding coverage:** {cleanup['n_grounded']:,} of {cleanup['n_total']:,} entities ({cleanup['n_grounded']/cleanup['n_total']*100:.1f}%) have at least one
ontology mapping.

## Known Limitations

- **{cleanup['db_noise']} noise-flagged entities** (confidence_score=0 or 2-char
  non-whitelisted) are retained but flagged; downstream consumers should filter
  on `is_noise: false` for production use.
- **{cleanup['n_ungrounded']:,} ungrounded entities** ({cleanup['n_ungrounded']/cleanup['n_total']*100:.1f}%) lack ontology mappings.
- **Co-occurrence edges** ({cleanup['co_occur_pct']:.1f}% of all edges) are
  statistical associations, not causally validated relationships. The {n_structured:,}
  structured edges (`llm_triple` + `biological_kb`) are the semantically typed core.
- **Evidence records** are predominantly co-occurrence summaries (~{n_cooccur_sum/n_evidence*100:.1f}%); only
  ~{n_verbatim:,} carry verbatim quoted text. `char_start`/`char_end` are NULL for all
  records in v1.0.
- **Full text is not redistributed** — only metadata and evidence excerpts.
- **Single annotator** — no inter-annotator agreement (Cohen's kappa) computed.

## Reference

> Abdill, R. J., Graham, S. P., Rubinetti, V., et al. (2025).
> *Integration of 168,000 samples reveals global patterns of the human gut microbiome.*
> **Cell** 188(4):1100-1118.e17. DOI: [10.1016/j.cell.2024.12.017](https://doi.org/10.1016/j.cell.2024.12.017)

## License

CC-BY 4.0 (https://creativecommons.org/licenses/by/4.0/)

## Citation

If you use this dataset, please cite both this Zenodo deposit and the reference
paper above.
"""
    out_path.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# Export: Zenodo metadata
# ---------------------------------------------------------------------------

def write_zenodo_metadata(out_path: Path, n_nodes: int, n_edges: int,
                          n_projects: int, n_evidence: int,
                          n_mentions: int = 0, n_ontology_mappings: int = 0,
                          n_structured: int = 0,
                          n_verbatim: int = 0, n_cooccur_sum: int = 0,
                          cleanup: dict | None = None) -> None:
    """Write Zenodo deposition metadata."""
    meta = {
        "title": "Microbiome Common Data Model (MCDM) v1.0: Knowledge Graph and Corpus from 444 Gut Microbiome BioProjects",
        "upload_type": "dataset",
        "description": (
            f"<p>The Microbiome Common Data Model (MCDM) v1.0 release is a "
            f"knowledge graph and associated corpus covering the human gut "
            f"microbiome, built from {n_projects} BioProject-associated full-text "
            f"papers from the 168,464-sample gut microbiome compendium "
            f"(Abdill et al., 2025, <i>Cell</i>).</p>"
            f"<p><strong>Contents:</strong></p><ul>"
            f"<li>Knowledge Graph: {n_edges:,} relationships (edges), {n_nodes:,} entities (nodes), 14 entity types, 14 predicate types</li>"
            f"<li>Corpus: {n_projects} BioProjects with metadata (title, amplicon, kit, host organism)</li>"
            f"<li>Evidence: {n_evidence:,} evidence records linking relationships to source papers (~{n_verbatim:,} verbatim quotes, ~{n_cooccur_sum:,} co-occurrence summaries)</li>"
            f"<li>Entity Mentions: {n_mentions:,} NER mentions with character offsets from 5 NER models</li>"
            f"<li>Ontology Grounding: {n_ontology_mappings:,} mappings across 25 biomedical vocabularies (UMLS, MeSH, NCIT, SNOMEDCT, NCBITaxon, CHEBI, etc.)</li>"
            f"<li>Quality Pipeline: 5-pass cleanup ({cleanup['pass1_corrections']:,} type corrections, {cleanup['pass2_merges']:,} merges, {cleanup['pass3_flagged']:,} LLM noise flags, {cleanup['pass4_deterministic']:,} deterministic deletions, {cleanup['pass5_ontology_review']:,} ontology review deletions)</li>"
            f"<li>Common Data Model (CDM): 14 entity types, 14 relationship types, controlled vocabularies</li>"
            f"<li>Data Catalogue: DCAT-style inventory of 7 datasets</li>"
            f"</ul>"
            f"<p><strong>Extraction:</strong> Multi-NER pipeline combining GLiNER, "
            f"PubMedBERT, PubTator3, sciSpaCy, and Qwen 3.5:9b (local Ollama LLM). "
            f"Entities are cleaned via a 5-pass quality pipeline: LLM type "
            f"correction, bge-m3 semantic deduplication (cosine >= 0.90), "
            f"LLM noise flagging, deterministic rule-based cleanup, and "
            f"heuristic ontology review.</p>"
            f"<p><strong>Evidence:</strong> Every relationship is anchored to "
            f"evidence from source literature. The {n_structured:,} structured edges "
            f"(llm_triple + biological_kb) carry typed predicates and ECO codes. "
            f"Co-occurrence edges include NPMI, p-value, and q-value statistics. "
            f"Evidence records are predominantly co-occurrence summaries (~{n_cooccur_sum/n_evidence*100:.1f}%); "
            f"~{n_verbatim:,} carry verbatim quoted text.</p>"
            f"<p><strong>Ontologies:</strong> UMLS, MeSH, NCIT, SNOMEDCT, "
            f"NCBITaxon, CHEBI, MONDO, HP, GO, RXNORM, OMIM, LOINC, DOID, PR, "
            f"HGNC, OBI, STATO, GENEPIO, CL, EDAM, SO, WIKIPATHWAYS, CLO, "
            f"ICD9CM, ICD10, ERO</p>"
            f"<p>Evidence records are short excerpts for scientific reproducibility. "
            f"No full text is redistributed.</p>"
            f"<p>See README.md in the archive for full documentation, schema, "
            f"and known limitations.</p>"
        ),
        "creators": [
            {
                "name": "Kalra, Jasmeer",
                "affiliation": "University of Bonn / Fraunhofer SCAI",
            },
        ],
        "keywords": [
            "microbiome",
            "knowledge graph",
            "common data model",
            "CDM",
            "gut microbiome",
            "human microbiome",
            "BioProject",
            "NER",
            "named entity recognition",
            "LLM extraction",
            "ontology grounding",
            "biomedical NLP",
            "relation extraction",
            "co-occurrence",
            "evidence-based",
            "GLiNER",
            "sciSpaCy",
            "PubMedBERT",
            "PubTator",
            "Qwen",
        ],
        "access_right": "open",
        "language": "eng",
        "version": "1.0.0",
        "publication_type": "dataset",
        "communities": [{"identifier": "zenodo"}],
        "related_identifiers": [
            {
                "identifier": "10.1016/j.cell.2024.12.017",
                "relation": "isDerivedFrom",
                "resource_type": "publication-article",
                "scheme": "doi",
            },
        ],
        "method": (
            "Multi-NER extraction (GLiNER, PubMedBERT, PubTator3, sciSpaCy, "
            "Qwen 3.5:9b LLM) from 444 BioProject full-text papers, followed by "
            "5-pass entity cleanup (LLM type correction, semantic dedup, LLM noise "
            "flagging, deterministic rule-based cleanup, heuristic ontology review) "
            "and ontology grounding via UMLS/OLS/MeSH/NCBITaxon"
        ),
        "notes": (
            f"{cleanup['db_noise']} noise-flagged entities (confidence_score=0 or unrecognised "
            f"2-char terms) are retained but flagged. {cleanup['n_ungrounded']:,} entities "
            f"({cleanup['n_ungrounded']/cleanup['n_total']*100:.1f}%) are ungrounded. "
            f"{cleanup['co_occur_pct']:.1f}% of edges are statistical co-occurrences, not "
            f"causally validated. The {n_structured:,} structured edges (llm_triple + biological_kb) "
            f"are the semantically typed core. See README.md Known Limitations section for details."
        ),
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Export: upload manifest
# ---------------------------------------------------------------------------

def write_upload_manifest(out_path: Path, file_records: list[dict],
                          total_size: int) -> None:
    """Write human-readable upload manifest with checksums."""
    lines = [
        "# Zenodo Upload Manifest — MCDM v1.0\n",
        f"**Total files:** {len(file_records)}\n",
        f"**Total size:** {total_size:,} bytes ({total_size / 1e6:.1f} MB)\n",
        "\n## Files\n",
        "| # | Path | Size (bytes) | SHA-256 | Records |",
        "|---|------|-------------|--------|---------|",
    ]

    for i, fr in enumerate(file_records, 1):
        sha_short = fr["sha256"][:16] + "..."
        lines.append(
            f"| {i} | `{fr['path']}` | {fr['size_bytes']:,} | `{sha_short}` | {fr['records']} |"
        )

    lines.extend([
        "\n## Upload Order\n",
        "1. Upload all files in `data/` as the deposit content",
        "2. Paste the metadata from `zenodo_metadata.json` into the Zenodo deposit form",
        "3. Set access rights to **Open** (CC-BY 4.0)",
        "4. Add the keywords from `zenodo_metadata.json` to the deposit",
        "5. Publish the deposit to get a DOI",
        "",
    ])

    out_path.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print(f"=== Building MCDM Zenodo bundle: {OUT} ===\n")

    # Verify inputs
    if not DB_PATH.exists():
        print(f"ERROR: Database not found at {DB_PATH}")
        sys.exit(1)
    if not PAPERS_DIR.exists():
        print(f"ERROR: Papers directory not found at {PAPERS_DIR}")
        sys.exit(1)

    # Create output directories
    OUT.mkdir(parents=True, exist_ok=True)
    OUT_DATA.mkdir(parents=True, exist_ok=True)
    OUT_CORPUS.mkdir(parents=True, exist_ok=True)

    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row

    # --- Export nodes ---
    print("Exporting nodes...")
    n_nodes = export_nodes(db, OUT_DATA / "nodes.jsonl")
    print(f"  {n_nodes:,} entities -> data/nodes.jsonl")

    # --- Export edges ---
    print("Exporting edges...")
    n_edges = export_edges(db, OUT_DATA / "edges.jsonl")
    print(f"  {n_edges:,} relationships -> data/edges.jsonl")

    # --- Export corpus ---
    print("Exporting corpus metadata...")
    n_projects = export_corpus_metadata(db, OUT_CORPUS / "corpus_metadata.jsonl")
    print(f"  {n_projects} projects -> data/corpus/corpus_metadata.jsonl")

    print("Exporting corpus papers...")
    n_papers = export_corpus_papers(db, PAPERS_DIR, OUT_CORPUS / "corpus_papers.jsonl")
    print(f"  {n_papers} papers -> data/corpus/corpus_papers.jsonl")

    print("Exporting evidence records...")
    n_evidence = export_evidence_records(db, OUT_CORPUS / "evidence_records.jsonl")
    print(f"  {n_evidence:,} evidence records -> data/corpus/evidence_records.jsonl")

    # Compute evidence type breakdown from DB (same logic as export function)
    ev_counts = {"verbatim_quote": 0, "co_occurrence_summary": 0, "empty": 0}
    for row in db.execute("SELECT evidence FROM relationships r JOIN edge_evidence ee ON ee.relationship_id = r.id"):
        ev_text = row[0] or ""
        if ev_text and not ev_text.startswith("Co-occur"):
            ev_counts["verbatim_quote"] += 1
        elif ev_text:
            ev_counts["co_occurrence_summary"] += 1
        else:
            ev_counts["empty"] += 1
    n_verbatim = ev_counts["verbatim_quote"]
    n_cooccur_sum = ev_counts["co_occurrence_summary"]

    # --- Compute live stats from DB + exported files ---
    n_mentions = db.execute("SELECT COUNT(*) FROM entity_project_mentions").fetchone()[0]

    # Count total ontology mappings from the just-written nodes.jsonl
    n_ontology_mappings = 0
    nodes_path = OUT_DATA / "nodes.jsonl"
    if nodes_path.exists():
        import json as _json
        with open(nodes_path, encoding="utf-8") as _f:
            for _line in _f:
                _node = _json.loads(_line)
                n_ontology_mappings += len(_node.get("ontology_mappings", []))

    # --- Write schema and metadata files ---
    print("Writing CDM schema...")
    write_cdm_schema(db, OUT_DATA / "cdm.json", n_nodes, n_edges,
                     n_mentions=n_mentions, n_evidence=n_evidence,
                     n_ontology_mappings=n_ontology_mappings)

    print("Writing JSON-LD context...")
    write_jsonld_context(OUT_DATA / "cdm_context.jsonld")

    print("Writing cleanup report...")
    write_cleanup_report(OUT_DATA / "cleanup_report.json")

    print("Writing data catalogue...")
    write_data_catalogue(OUT_DATA / "data_catalogue.json", n_nodes, n_edges,
                          n_projects, n_evidence)

    print("Writing corpus schema...")
    write_corpus_schema(OUT_CORPUS / "corpus_schema.json")

    print("Writing corpus manifest...")
    write_corpus_manifest(OUT_CORPUS)

    print("Writing corpus README...")
    write_corpus_readme(OUT_CORPUS / "README_corpus.md", n_projects, n_evidence, n_verbatim, n_cooccur_sum)

    # Query actual noise and grounding counts from DB before closing
    # Noise count uses the same logic as the export (conf=0 OR 2-char non-whitelisted OR spaced-out)
    n_noise = 0
    for row in db.execute("SELECT term, confidence_score FROM entities ORDER BY id"):
        if is_entity_noise(row[0], row[1] or 0):
            n_noise += 1
    n_total = db.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
    n_grounded = db.execute(
        "SELECT COUNT(*) FROM entities "
        "WHERE COALESCE(UMLS_ID, '') != '' "
        "OR COALESCE(NCBITaxon, '') != '' "
        "OR COALESCE(MeSH_UI, '') != '' "
        "OR COALESCE(OLS, '') != ''"
    ).fetchone()[0]
    n_ungrounded = n_total - n_grounded
    n_co_occur = db.execute("SELECT COUNT(*) FROM relationships WHERE source_db = 'co-occurrence'").fetchone()[0]
    source_dist = {r[0]: r[1] for r in db.execute(
        "SELECT source_db, COUNT(*) FROM relationships GROUP BY source_db"
    ).fetchall()}

    db.close()

    # --- Read cleanup stats from checkpoints ---
    cleanup = read_cleanup_stats()
    cleanup["db_noise"] = n_noise  # actual export noise count (conf=0 + 2-char + spaced-out)
    cleanup["n_grounded"] = n_grounded
    cleanup["n_ungrounded"] = n_ungrounded
    cleanup["n_total"] = n_total
    cleanup["co_occur_pct"] = n_co_occur / n_edges * 100 if n_edges else 0
    print(f"Cleanup stats: {cleanup['pass1_corrections']:,} corrections, "
          f"{cleanup['pass2_merges']:,} merges, {cleanup['pass3_flagged']:,} flagged "
          f"({cleanup['pass3_noise']:,} LLM noise / {n_noise:,} total noise in export)")
    print(f"Grounding: {n_grounded:,} grounded ({n_grounded/n_total*100:.1f}%), "
          f"{n_ungrounded:,} ungrounded ({n_ungrounded/n_total*100:.1f}%)")

    # --- Write Zenodo metadata ---
    n_structured = (source_dist.get("llm_triple", 0)
                    + source_dist.get("biological_kb", 0)
                    + source_dist.get("co-occurrence+kb", 0))
    print("\nWriting zenodo_metadata.json...")
    write_zenodo_metadata(OUT / "zenodo_metadata.json", n_nodes, n_edges,
                          n_projects, n_evidence,
                          n_mentions=n_mentions, n_ontology_mappings=n_ontology_mappings,
                          n_structured=n_structured,
                          n_verbatim=n_verbatim, n_cooccur_sum=n_cooccur_sum,
                          cleanup=cleanup)

    # --- Write top-level README ---
    print("Writing README.md...")
    write_readme(OUT / "README.md", n_nodes, n_edges, n_projects, n_evidence, n_mentions, cleanup, source_dist,
                 n_verbatim=n_verbatim, n_cooccur_sum=n_cooccur_sum)

    # --- Build file manifest with checksums (after all files are written) ---
    print("\nComputing checksums and building manifest...")
    file_records = []
    total_size = 0

    for root, dirs, files in os.walk(OUT):
        dirs.sort()
        files.sort()
        for fn in files:
            fp = Path(root) / fn
            if fp == OUT / "zenodo_upload_manifest.md":
                continue  # don't include manifest in itself
            if fp == OUT / "zenodo_metadata.json":
                continue  # local helper, not deposit content
            size = fp.stat().st_size
            total_size += size
            sha = sha256_file(fp)

            records = ""
            if fn.endswith(".jsonl"):
                records = f"{count_lines(fp):,} records"
            elif fn.endswith(".json"):
                records = "1 record"
            elif fn.endswith(".jsonld"):
                records = "1 record"
            elif fn.endswith(".md"):
                records = "documentation"

            rel_path = str(fp.relative_to(OUT))
            file_records.append({
                "path": rel_path,
                "size_bytes": size,
                "sha256": sha,
                "records": records,
            })
            print(f"  {rel_path:50s} {size:>12,} bytes  {records}")

    print(f"\n  Total: {len(file_records)} files, {total_size:,} bytes ({total_size / 1e6:.1f} MB)")

    # --- Write upload manifest ---
    print("Writing zenodo_upload_manifest.md...")
    write_upload_manifest(OUT / "zenodo_upload_manifest.md", file_records, total_size)

    # --- Final tree ---
    print(f"\n=== ZENODO BUNDLE FILE TREE ===")
    for root, dirs, files in os.walk(OUT):
        dirs.sort()
        files.sort()
        level = root.replace(str(OUT), "").count(os.sep)
        indent = "  " * level
        basename = os.path.basename(root) if level > 0 else "zenodo_v1"
        print(f"{indent}{basename}/")
        for fn in files:
            fp = os.path.join(root, fn)
            print(f"{indent}  {fn:45s} {os.path.getsize(fp):>12,} bytes")

    print(f"\n=== DONE ===")
    print(f"  Output: {OUT}")
    print(f"  Files:  {len(file_records)}")
    print(f"  Size:   {total_size:,} bytes ({total_size / 1e6:.1f} MB)")
    print(f"  Nodes:  {n_nodes:,}")
    print(f"  Edges:  {n_edges:,}")
    print(f"  Papers: {n_projects}")
    print(f"  Evidence: {n_evidence:,}")


if __name__ == "__main__":
    main()
