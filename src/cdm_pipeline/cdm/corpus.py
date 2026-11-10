"""Step 1: Build unified entity corpus from mapped entities + NER mentions."""
import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from ..config import (
    CDM_TYPES, VOCAB_PRIORITY, EXACT_MATCH_FLOOR,
    NER_OUTPUT_DIR, CDM_OUTPUT_DIR, MAPPING_DIR, PAPERS_DIR, NER_CSVS,
    REPO_ROOT,
)
from ..utils import is_junk, norm, load_csv_safe

MAPPED_PATH = MAPPING_DIR / "mapped_entities.json"

# Historical 444-paper input set, used when CDM_NER_CSVS is unset.
DEFAULT_NER_CSVS = [
    NER_OUTPUT_DIR / "gliner_ner.csv",
    NER_OUTPUT_DIR / "pubmedbert_ner.csv",
    NER_OUTPUT_DIR / "pubtator3_ner.csv",
    NER_OUTPUT_DIR / "scispacy_ner.csv",
    NER_OUTPUT_DIR / "qwen3.5_ner.csv",
]

# Per-model mention CSVs that feed the corpus.  Historically a fixed five-file
# list mirroring the 444-paper build; a re-scoped build uses different runners
# and therefore different filenames — the 452 build has seven section-level
# ensemble files plus the two Qwen artifacts, and no scispacy_ner.csv rollup.
# CDM_NER_CSVS selects them (see config._env_path_list); unset keeps the
# historical five so the 444 build is reproducible.
#
# The model label recorded downstream comes from the *filename*
# (``csv_path.stem``), not the file's ``model`` column, so these names are what
# appear in the corpus metadata and DB provenance.
ALL_NER_CSVS = NER_CSVS or DEFAULT_NER_CSVS


def _resolve_qwen_csv():
    """Locate the LLM metadata CSV (``definition``/``aliases``/``context``).

    These three columns only ever came from the whole-document Qwen batch
    (``qwen_batch.py`` -> ``qwen3.5_ner.csv``).  The section-level Qwen files
    that a re-scoped build actually ships (``qwen_sections_ner.csv``,
    ``vllm_sections_ner.csv``) carry the same nine mention columns as every
    other model and no metadata at all, so there is no automatic substitute.

    Resolution order: ``CDM_QWEN_CSV`` if set, else the historical filename,
    else the first declared input whose header actually has the columns.  A
    miss is normal for a section-level build; :func:`build_corpus` reports it
    explicitly rather than silently enriching nothing.
    """
    override = os.environ.get("CDM_QWEN_CSV", "").strip()
    if override:
        p = Path(override).expanduser()
        return p if p.is_absolute() else REPO_ROOT / p
    legacy = NER_OUTPUT_DIR / "qwen3.5_ner.csv"
    if legacy.exists():
        return legacy
    for csv_path in ALL_NER_CSVS:
        try:
            with open(csv_path, encoding="utf-8", errors="replace", newline="") as f:
                header = f.readline()
        except OSError:
            continue
        if "definition" in header or "aliases" in header:
            return csv_path
    return None


QWEN_CSV = _resolve_qwen_csv()


def _load_paper_id_map():
    """Read the corpus-id -> BioProject accession table.

    Section-level NER CSVs identify papers by their ``HMPAPER_*`` corpus id,
    while the CDM database's ``projects`` table is keyed by BioProject
    accessions (the ``PRJ*.txt`` filenames under ``data/papers_txt/``), so paper
    ids must be remapped at load time for mention rows to join ``projects``.
    Ids absent from the map (historical document-level builds already used
    accessions) pass through unchanged.
    """
    import csv as _csv

    path = REPO_ROOT / "data" / "corpus" / "id_map.csv"
    mapping = {}
    if path.exists():
        with open(path, encoding="utf-8", newline="") as f:
            for row in _csv.DictReader(f):
                cid = (row.get("corpus_id") or "").strip()
                acc = (row.get("bioproject_accession") or "").strip()
                if cid and acc:
                    mapping[cid] = acc
    return mapping


OUT = CDM_OUTPUT_DIR


def build_corpus():
    print("=" * 60)
    print("STEP 1: Building unified entity corpus")
    print("=" * 60)

    with open(MAPPED_PATH, encoding="utf-8") as f:
        mapped = json.load(f)

    id_map = _load_paper_id_map()
    print(f"  Paper id map: {len(id_map)} corpus-id -> accession entries")

    # Load per-paper mentions from ALL NER CSVs
    paper_mentions = defaultdict(lambda: defaultdict(list))  # paper -> norm -> [(term, type, start, end, model)]
    entity_papers = defaultdict(set)  # norm -> set of papers
    entity_mentions = defaultdict(list)  # norm -> [(paper, char_start, char_end, model)]
    loaded_models = []  # model labels actually read, i.e. one per CSV present

    for csv_path in ALL_NER_CSVS:
        if not csv_path.exists():
            print(f"  WARNING: {csv_path.name} not found, skipping")
            continue
        model_name = csv_path.stem.replace("_ner", "")
        loaded_models.append(model_name)
        rows = load_csv_safe(csv_path)
        for r in rows:
            t = r["term"].strip()
            if len(t) < 2:
                continue
            k = norm(t)
            if not k:
                continue
            cs = int(r.get("char_start", 0) or 0)
            ce = int(r.get("char_end", 0) or 0)
            paper = id_map.get(r["paper"], r["paper"])
            paper_mentions[paper][k].append(
                (t, r["labels"], cs, ce, model_name))
            entity_papers[k].add(paper)
            entity_mentions[k].append((paper, cs, ce, model_name))
        print(f"  {csv_path.name}: {len(rows)} rows loaded")

    # Load Qwen definitions/aliases
    qwen_meta = {}  # norm -> {"definition": ..., "aliases": ..., "context": ...}
    if QWEN_CSV is None:
        print("  Qwen metadata: NOT AVAILABLE — no CSV with definition/aliases "
              "columns in this build (section-level Qwen files carry mentions only); "
              "definitions fall back to the mapping table")
    elif not QWEN_CSV.exists():
        print(f"  Qwen metadata: NOT AVAILABLE — {QWEN_CSV} not found; "
              "definitions fall back to the mapping table")
    else:
        for r in load_csv_safe(QWEN_CSV):
            t = r["term"].strip()
            if len(t) < 2:
                continue
            k = norm(t)
            if k and k not in qwen_meta:
                qwen_meta[k] = {
                    "definition": (r.get("definition") or "").strip(),
                    "aliases": (r.get("aliases") or "").strip(),
                    "context": (r.get("context") or "").strip(),
                }
        print(f"  Qwen metadata: {len(qwen_meta)} terms from {QWEN_CSV.name}")

    # Build corpus entities with canonical mappings
    entities = []
    skipped_junk = 0
    for m in mapped:
        if is_junk(m["term"]):
            skipped_junk += 1
            continue
        k = m["norm"]
        papers = sorted(entity_papers.get(k, set()))

        # Resolve canonical + SKOS relations from all_mappings
        all_maps = m.get("all_mappings", [])
        canonical = m.get("canonical")
        related = []

        if canonical and all_maps:
            canonical_words = set(canonical.get("label", "").lower().split())
            for c in all_maps:
                if c is canonical:
                    continue
                if c.get("confidence", 0) >= EXACT_MATCH_FLOOR:
                    relation = "exactMatch"
                else:
                    c_words = set(c.get("label", "").lower().split())
                    if c_words and canonical_words and c_words < canonical_words:
                        relation = "broadMatch"
                    elif c_words and canonical_words and canonical_words < c_words:
                        relation = "narrowMatch"
                    else:
                        relation = "relatedMatch"
                related.append({**c, "relation": relation})

        # Group mappings by source
        umls_maps = [c for c in all_maps if c.get("source") == "umls"]
        bp_maps = [c for c in all_maps if c.get("source") == "bioportal"]
        ols_maps = [c for c in all_maps if c.get("source") == "ols"]
        omop_maps = [c for c in all_maps if c.get("source") == "omop"]
        ncbi_maps = [c for c in all_maps if c.get("source") == "ncbi_taxon"]

        # Qwen enrichment — prefer LLM mapping definitions, fall back to Qwen NER CSV
        qm = qwen_meta.get(k, {})
        mapping_def = m.get("definition", "").strip()
        mapping_ctx = m.get("context", "").strip()
        definition = mapping_def or qm.get("definition", "")
        context = mapping_ctx or qm.get("context", "")

        entities.append({
            "entity": m["term"],
            "norm": k,
            "entity_type": m["cdm_type"],
            "paper_count": len(papers),
            "papers": papers,  # no cap — bounded by the 452-paper analysed scope
            "total_occurrences": m.get("mention_count", 0),
            "sources": m.get("sources", []),
            "source_scores": {s: 1.0 for s in m.get("sources", [])},
            "mentions": entity_mentions.get(k, []),
            "has_any_external_mapping": canonical is not None,
            "canonical_mapping": canonical,
            "related_mappings": related,
            "umls_mappings": umls_maps,
            "bioportal_mappings": bp_maps,
            "ols_mappings": ols_maps,
            "omop_mappings": omop_maps,
            "ncbi_taxon_mappings": ncbi_maps,
            "definition": definition,
            "aliases": qm.get("aliases", ""),
            "context": context,
            "llm_verified": m.get("llm_verified", False),
            "llm_confidence": m.get("llm_confidence", 0.0),
        })

    entities.sort(key=lambda e: (-e["paper_count"], e["entity_type"], e["entity"].lower()))
    print(f"  Filtered {skipped_junk} junk entities, kept {len(entities)}")
    print(f"  Qwen context: {sum(1 for e in entities if e['context'])} entities enriched")
    print(f"  Qwen definitions: {sum(1 for e in entities if e['definition'])} entities enriched")

    corpus = {
        "metadata": {
            "name": "Microbiome Common Data Model Entity Corpus",
            "version": "2.1.0",
            "created": datetime.now(timezone.utc).isoformat(),
            "source_papers": len(paper_mentions),
            "unique_entities": len(entities),
            "entities_with_external_mapping": sum(1 for e in entities if e["has_any_external_mapping"]),
            "cdm_types": CDM_TYPES,
            "ner_models": loaded_models,
            "mapping_services": ["OLS", "UMLS", "BioPortal", "NCBI Taxonomy"],
            "vocab_priority": {k: v for k, v in VOCAB_PRIORITY.items()},
        },
        "entities": entities,
    }

    corpus_path = OUT / "unified_entity_corpus.json"
    with open(corpus_path, "w", encoding="utf-8") as f:
        json.dump(corpus, f, indent=2, ensure_ascii=False)
    print(f"  Corpus: {len(entities)} entities, {corpus['metadata']['entities_with_external_mapping']} mapped")
    print(f"  Saved to {corpus_path}")

    return corpus, entity_papers
