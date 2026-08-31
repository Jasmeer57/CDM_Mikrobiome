"""
Build a publishable Microbiome Common Data Model (CDM) from mapped NER entities.

Produces:
  1. unified_entity_corpus.json  — corpus with canonical mappings + SKOS relations
  2. microbiome_cdm.db           — SQLite database (8 tables, 24 indexes, 9 views)
  3. microbiome_cdm.owl           — OWL/RDF ontology
  4. data_catalogue.json          — browsable data catalogue
  5. data_catalogue.csv           — flat CSV export
  6. cdm_provenance.json          — provenance trace

Input:
  - paper_claims/_multi_ner_runs/mapped_entities.json   (36K mapped entities)
  - paper_claims/_multi_ner_runs/gliner_ner.csv          (per-paper entity mentions)
  - bioproject_data_export.json                          (BioProject metadata)
  - papers_txt/*.txt                                      (444 source papers)
"""
import sys, io, os, json, csv, sqlite3, re, time
from pathlib import Path
from collections import Counter, defaultdict
from datetime import datetime, timezone

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

REPO = Path(__file__).parent
OUT = REPO / "paper_claims" / "_multi_ner_runs" / "cdm_output"
OUT.mkdir(parents=True, exist_ok=True)

MAPPED_PATH = REPO / "paper_claims" / "_multi_ner_runs" / "mapped_entities.json"
GLINER_CSV = REPO / "paper_claims" / "_multi_ner_runs" / "gliner_ner.csv"
PUBTATOR_CSV = REPO / "paper_claims" / "_multi_ner_runs" / "pubtator3_ner.csv"
BIOPROJECT_JSON = REPO / "bioproject_data_export.json"
PAPERS_DIR = REPO / "papers_txt"

CDM_TYPES = [
    "ORGANISM", "CHEMICAL", "DISEASE", "PROTEIN", "DNA_RNA", "CELL_TYPE",
    "GENOMICS", "PATHWAY", "LAB_METHOD", "DATA_ANALYSIS", "SAMPLE_METHOD",
    "CLINICAL", "EXPERIMENTAL_METHOD", "STUDY_DESIGN",
]

VOCAB_PRIORITY = {
    "ORGANISM": ["NCBITAXON", "SNOMEDCT", "MESH", "NCIT"],
    "PROTEIN": ["PR", "GO", "CHEBI", "MESH", "HGNC", "NCBITAXON"],
    "CHEMICAL": ["CHEBI", "MESH", "RXNORM", "SNOMEDCT", "NCIT"],
    "DISEASE": ["DOID", "MONDO", "SNOMEDCT", "ICD9CM", "ICD10", "OMIM", "MESH"],
    "DNA_RNA": ["SO", "SEQUENCE", "GENEPIO", "MESH", "NCIT"],
    "CELL_TYPE": ["CL", "CLO", "MESH", "NCIT"],
    "SAMPLE_METHOD": ["OBI", "NCIT", "MESH"],
    "LAB_METHOD": ["OBI", "NCIT", "ERO", "MESH"],
    "DATA_ANALYSIS": ["STATO", "OBI", "EDAM", "NCIT"],
    "PATHWAY": ["GO", "WIKIPATHWAYS", "REACTOME", "CHEBI"],
    "EXPERIMENTAL_METHOD": ["OBI", "ERO", "NCIT"],
    "STUDY_DESIGN": ["OBI", "SNOMEDCT", "NCIT"],
    "GENOMICS": ["OBI", "SO", "NCIT", "MESH"],
    "CLINICAL": ["SNOMEDCT", "NCIT", "LOINC", "MESH"],
}

EXACT_MATCH_FLOOR = 0.85

JUNK_RE = re.compile(r"^[\W\d_]+|[\W_]+$", re.UNICODE)


def is_junk(term):
    """Return True if a term is likely an extraction artifact (punctuation/noise)."""
    t = term.strip()
    if len(t) < 2:
        return True
    if len(t) < 3 and not t.isalpha():
        return True
    if JUNK_RE.sub("", t) == "":
        return True
    if t.startswith((",", ".", ")", "(", "[", "]", "'", '"', ";", ":", "-")):
        return True
    if t.endswith((",", ".", ")", "(", "[", "]", "'", '"', ";", ":", "-")):
        return True
    if "\n" in t or "\t" in t:
        return True
    # Pure numbers or punctuation
    if re.fullmatch(r"[\d\s\W]+", t):
        return True
    # Contains "respectively)" or other trailing fragments
    if re.search(r"[a-z]\)", t) and len(t) < 30:
        return True
    return False


def norm(t):
    return re.sub(r"\s+", " ", t.lower().strip())


def load_csv_safe(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        content = f.read().replace("\x00", "")
        return list(csv.DictReader(io.StringIO(content)))


# ────────────────── Step 1: Build unified corpus ──────────────────

def build_corpus():
    print("=" * 60)
    print("STEP 1: Building unified entity corpus")
    print("=" * 60)

    with open(MAPPED_PATH, encoding="utf-8") as f:
        mapped = json.load(f)

    # Load per-paper mentions from GLiNER CSV
    paper_mentions = defaultdict(lambda: defaultdict(list))  # paper -> norm -> [(term, type, pos)]
    gliner_rows = load_csv_safe(GLINER_CSV)
    for r in gliner_rows:
        t = r["term"].strip()
        if len(t) < 2:
            continue
        k = norm(t)
        paper_mentions[r["paper"]][k].append((t, r["labels"], int(r.get("char_start", 0))))

    # Build paper -> entity mapping
    entity_papers = defaultdict(set)  # norm -> set of papers
    for paper, mentions in paper_mentions.items():
        for k in mentions:
            entity_papers[k].add(paper)

    # Add PubTator3 paper associations
    pubtator_rows = load_csv_safe(PUBTATOR_CSV)
    for r in pubtator_rows:
        t = r["term"].strip()
        if len(t) < 2:
            continue
        k = norm(t)
        entity_papers[k].add(r["paper"])

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

        entities.append({
            "entity": m["term"],
            "norm": k,
            "entity_type": m["cdm_type"],
            "paper_count": len(papers),
            "papers": papers[:100],  # cap for file size
            "total_occurrences": m.get("mention_count", 0),
            "sources": m.get("sources", []),
            "has_any_external_mapping": canonical is not None,
            "canonical_mapping": canonical,
            "related_mappings": related,
            "umls_mappings": umls_maps,
            "bioportal_mappings": bp_maps,
            "ols_mappings": ols_maps,
            "omop_mappings": omop_maps,
            "ncbi_taxon_mappings": ncbi_maps,
        })

    entities.sort(key=lambda e: (-e["paper_count"], e["entity_type"], e["entity"].lower()))
    print(f"  Filtered {skipped_junk} junk entities, kept {len(entities)}")

    corpus = {
        "metadata": {
            "name": "Microbiome Common Data Model Entity Corpus",
            "version": "2.0.0",
            "created": datetime.now(timezone.utc).isoformat(),
            "source_papers": len(paper_mentions),
            "unique_entities": len(entities),
            "entities_with_external_mapping": sum(1 for e in entities if e["has_any_external_mapping"]),
            "cdm_types": CDM_TYPES,
            "ner_models": ["GLiNER", "PubTator3", "BioBERT"],
            "mapping_services": ["OLS", "OMOP Athena", "NCBI Taxonomy"],
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


# ────────────────── Step 2: Create SQLite CDM database ──────────────────

def create_db(corpus, entity_papers):
    print("\n" + "=" * 60)
    print("STEP 2: Creating SQLite CDM database")
    print("=" * 60)

    db_path = OUT / "microbiome_cdm.db"
    if db_path.exists():
        db_path.unlink()

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    c = conn.cursor()

    # ── Tables ──
    c.executescript("""
    CREATE TABLE entity_types (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        type_name TEXT UNIQUE NOT NULL,
        description TEXT,
        parent_type TEXT
    );
    CREATE INDEX idx_entity_types_name ON entity_types(type_name);

    CREATE TABLE entities (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        term TEXT UNIQUE NOT NULL,
        entity_type TEXT,
        categories TEXT,
        confidence_score REAL,
        paper_count INTEGER,
        frequency INTEGER,
        definition TEXT,
        contextual_definition TEXT,
        aliases TEXT,
        examples TEXT,
        is_core_term BOOLEAN,
        relevance_classification TEXT,
        is_computed_metric BOOLEAN,
        files_found_in TEXT,
        paper_location TEXT,
        paper_context TEXT,
        UMLS_ID TEXT,
        OMOP TEXT,
        OLS TEXT,
        Bioportal TEXT,
        NCBITaxon TEXT,
        umls_mapped BOOLEAN,
        umls_concepts TEXT,
        umls_best_match TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX idx_entities_term ON entities(term);
    CREATE INDEX idx_entities_type ON entities(entity_type);
    CREATE INDEX idx_entities_umls ON entities(UMLS_ID);
    CREATE INDEX idx_entities_omop ON entities(OMOP);
    CREATE INDEX idx_entities_confidence ON entities(confidence_score);

    CREATE TABLE relationships (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_id INTEGER NOT NULL,
        target_id INTEGER NOT NULL,
        relationship_type TEXT NOT NULL,
        source_db TEXT,
        confidence REAL,
        evidence TEXT,
        evidence_type TEXT,
        mechanism TEXT,
        ec_number TEXT,
        kegg_pathway TEXT,
        pubmed_ids TEXT,
        paper_doi TEXT,
        validation_status TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (source_id) REFERENCES entities(id),
        FOREIGN KEY (target_id) REFERENCES entities(id)
    );
    CREATE INDEX idx_relationships_source ON relationships(source_id);
    CREATE INDEX idx_relationships_target ON relationships(target_id);
    CREATE INDEX idx_relationships_type ON relationships(relationship_type);
    CREATE INDEX idx_relationships_confidence ON relationships(confidence);

    CREATE TABLE projects (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id TEXT UNIQUE NOT NULL,
        title TEXT,
        link TEXT,
        amplicon TEXT,
        avg_length REAL,
        bead_beating BOOLEAN,
        kit TEXT,
        sample_type TEXT,
        condition TEXT,
        subjects TEXT,
        notes TEXT,
        host_organism TEXT,
        journal TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX idx_projects_project_id ON projects(project_id);
    CREATE INDEX idx_projects_condition ON projects(condition);

    CREATE TABLE samples (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        srs TEXT UNIQUE NOT NULL,
        project_id TEXT NOT NULL,
        srr TEXT,
        library_strategy TEXT,
        library_source TEXT,
        pubdate TEXT,
        total_bases INTEGER,
        instrument TEXT,
        geo_loc_name TEXT,
        iso TEXT,
        region TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (project_id) REFERENCES projects(project_id)
    );
    CREATE INDEX idx_samples_srs ON samples(srs);
    CREATE INDEX idx_samples_project ON samples(project_id);
    CREATE INDEX idx_samples_instrument ON samples(instrument);
    CREATE INDEX idx_samples_geo ON samples(geo_loc_name);

    CREATE TABLE sample_tags (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sample_id INTEGER NOT NULL,
        tag TEXT NOT NULL,
        value TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (sample_id) REFERENCES samples(id)
    );
    CREATE INDEX idx_sample_tags_sample ON sample_tags(sample_id);
    CREATE INDEX idx_sample_tags_tag ON sample_tags(tag);

    CREATE TABLE entity_project_mentions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        entity_id INTEGER NOT NULL,
        project_id TEXT NOT NULL,
        mention_type TEXT,
        paper_context TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (entity_id) REFERENCES entities(id),
        UNIQUE(entity_id, project_id, mention_type)
    );
    CREATE INDEX idx_entity_project_entity ON entity_project_mentions(entity_id);
    CREATE INDEX idx_entity_project_project ON entity_project_mentions(project_id);
    CREATE INDEX idx_entity_project_type ON entity_project_mentions(mention_type);

    CREATE TABLE controlled_vocabularies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        entity_id INTEGER NOT NULL,
        vocabulary_name TEXT NOT NULL,
        vocabulary_id TEXT,
        vocabulary_uri TEXT,
        vocabulary_label TEXT,
        mapping_confidence REAL,
        mapping_source TEXT,
        is_canonical BOOLEAN DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (entity_id) REFERENCES entities(id)
    );
    CREATE INDEX idx_cv_entity ON controlled_vocabularies(entity_id);
    CREATE INDEX idx_cv_vocabulary ON controlled_vocabularies(vocabulary_name);
    CREATE INDEX idx_cv_vocab_id ON controlled_vocabularies(vocabulary_id);
    """)

    # ── Populate entity_types ──
    type_descs = {
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
    for t in CDM_TYPES:
        c.execute("INSERT INTO entity_types (type_name, description) VALUES (?, ?)",
                  (t, type_descs.get(t, "")))

    # ── Populate projects from BioProject metadata ──
    bp_data = {}
    if BIOPROJECT_JSON.exists():
        with open(BIOPROJECT_JSON, encoding="utf-8") as f:
            bp_data = json.load(f)

    proj_count = 0
    for bp in bp_data.get("bioprojects", []):
        pid = bp.get("bioproject_id", "")
        if not pid:
            continue
        c.execute("""INSERT OR IGNORE INTO projects
            (project_id, title, amplicon, kit, sample_type, condition,
             subjects, notes, host_organism, journal)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (pid,
             bp.get("title", "") or bp.get("study_title", ""),
             bp.get("amplicon_region", ""),
             bp.get("library_prep_kit", ""),
             bp.get("sample_type", ""),
             bp.get("health_status", ""),
             str(bp.get("sample_size", "")),
             (bp.get("summary", "") or "")[:500],
             bp.get("host_organism", ""),
             bp.get("journal", "")))
        proj_count += 1

    # Add papers without BioProject metadata as stub projects
    all_papers = set(f.name for f in PAPERS_DIR.glob("*.txt"))
    for paper in all_papers:
        pid = paper.replace(".txt", "")
        c.execute("INSERT OR IGNORE INTO projects (project_id) VALUES (?)", (pid,))
    print(f"  Projects: {proj_count} from BioProject metadata, {len(all_papers)} total papers")

    # ── Populate entities ──
    entity_id_map = {}  # norm -> entity_id
    for e in corpus["entities"]:
        canon = e.get("canonical_mapping") or {}
        umls_id = ""
        omop_id = ""
        ols_id = ""
        bp_id = ""
        ncbi_id = ""

        for m in e.get("umls_mappings", []):
            if m.get("concept_id"):
                umls_id = m["concept_id"]
                break
        for m in e.get("omop_mappings", []):
            if m.get("concept_id"):
                omop_id = m["concept_id"]
                break
        for m in e.get("ols_mappings", []):
            if m.get("concept_id"):
                ols_id = m["concept_id"]
                break
        for m in e.get("bioportal_mappings", []):
            if m.get("concept_id"):
                bp_id = m["concept_id"]
                break
        for m in e.get("ncbi_taxon_mappings", []):
            if m.get("concept_id"):
                ncbi_id = m["concept_id"]
                break

        # Also check canonical for IDs
        if not umls_id and canon.get("source") == "umls":
            umls_id = canon.get("concept_id", "")
        if not omop_id and canon.get("source") == "omop":
            omop_id = canon.get("concept_id", "")
        if not ols_id and canon.get("source") == "ols":
            ols_id = canon.get("concept_id", "")
        if not bp_id and canon.get("source") == "bioportal":
            bp_id = canon.get("concept_id", "")
        if not ncbi_id and canon.get("source") == "ncbi_taxon":
            ncbi_id = canon.get("concept_id", "")

        is_core = e["paper_count"] >= 10
        confidence = canon.get("confidence", 0.5) if canon else 0.5

        c.execute("""INSERT INTO entities
            (term, entity_type, confidence_score, paper_count, frequency,
             is_core_term, UMLS_ID, OMOP, OLS, Bioportal, NCBITaxon, umls_mapped)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (e["entity"], e["entity_type"], confidence,
             e["paper_count"], e["total_occurrences"],
             is_core, umls_id, omop_id, ols_id, bp_id, ncbi_id,
             bool(umls_id)))
        entity_id_map[e["norm"]] = c.lastrowid

    print(f"  Entities: {len(corpus['entities'])} inserted")

    # ── Populate controlled_vocabularies ──
    cv_count = 0
    for e in corpus["entities"]:
        eid = entity_id_map[e["norm"]]
        canon = e.get("canonical_mapping")
        all_maps = (e.get("umls_mappings", []) + e.get("bioportal_mappings", []) +
                    e.get("ols_mappings", []) + e.get("omop_mappings", []) +
                    e.get("ncbi_taxon_mappings", []))

        seen = set()
        for m in all_maps:
            key = (m.get("ontology_name", ""), m.get("concept_id", ""))
            if key in seen:
                continue
            seen.add(key)
            is_canon = (canon and m.get("source") == canon.get("source") and
                        m.get("concept_id") == canon.get("concept_id"))
            c.execute("""INSERT INTO controlled_vocabularies
                (entity_id, vocabulary_name, vocabulary_id, vocabulary_uri,
                 vocabulary_label, mapping_confidence, mapping_source, is_canonical)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (eid, m.get("ontology_name", ""), m.get("concept_id", ""),
                 m.get("concept_id", "") if m.get("concept_id", "").startswith("http") else "",
                 m.get("label", ""), m.get("confidence", 0.0),
                 m.get("source", ""), is_canon))
            cv_count += 1
    print(f"  Controlled vocabulary mappings: {cv_count}")

    # ── Populate entity_project_mentions ──
    mention_count = 0
    for e in corpus["entities"]:
        eid = entity_id_map[e["norm"]]
        for paper in e.get("papers", []):
            pid = paper.replace(".txt", "")
            try:
                c.execute("""INSERT OR IGNORE INTO entity_project_mentions
                    (entity_id, project_id, mention_type)
                    VALUES (?, ?, ?)""",
                    (eid, pid, e["entity_type"]))
                mention_count += 1
            except sqlite3.IntegrityError:
                pass
    print(f"  Entity-project mentions: {mention_count}")

    # ── Generate co-occurrence relationships ──
    print("  Generating co-occurrence relationships...")
    paper_entities = defaultdict(list)
    for e in corpus["entities"]:
        eid = entity_id_map[e["norm"]]
        for paper in e.get("papers", []):
            paper_entities[paper].append((eid, e["entity_type"], e["entity"]))

    rel_count = 0
    rel_inserted = 0
    # Type pairs that make biological sense as relationships
    meaningful_pairs = {
        frozenset(("ORGANISM", "DISEASE")), frozenset(("ORGANISM", "CHEMICAL")),
        frozenset(("ORGANISM", "PROTEIN")), frozenset(("ORGANISM", "PATHWAY")),
        frozenset(("ORGANISM", "CLINICAL")), frozenset(("CHEMICAL", "DISEASE")),
        frozenset(("CHEMICAL", "PROTEIN")), frozenset(("CHEMICAL", "PATHWAY")),
        frozenset(("DISEASE", "PROTEIN")), frozenset(("DISEASE", "CLINICAL")),
        frozenset(("DISEASE", "CELL_TYPE")), frozenset(("PROTEIN", "PATHWAY")),
        frozenset(("DNA_RNA", "PROTEIN")), frozenset(("CELL_TYPE", "ORGANISM")),
        frozenset(("CELL_TYPE", "DISEASE")),
    }

    seen_pairs = set()
    for paper, ents in paper_entities.items():
        if len(ents) > 200:  # skip papers with too many entities (noise)
            continue
        for i in range(len(ents)):
            for j in range(i + 1, len(ents)):
                eid1, t1, term1 = ents[i]
                eid2, t2, term2 = ents[j]
                if eid1 == eid2:
                    continue
                pair_key = (min(eid1, eid2), max(eid1, eid2))
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)

                if frozenset((t1, t2)) not in meaningful_pairs:
                    continue

                # Determine relationship type from type pair
                rel_type = "CO_OCCURS_WITH"
                s_id, t_id = eid1, eid2
                if {t1, t2} == {"ORGANISM", "DISEASE"}:
                    rel_type = "ASSOCIATED_WITH"
                    s_id = eid1 if t1 == "ORGANISM" else eid2
                    t_id = eid2 if t1 == "ORGANISM" else eid1
                elif {t1, t2} == {"ORGANISM", "CHEMICAL"}:
                    rel_type = "PRODUCES"
                    s_id = eid1 if t1 == "ORGANISM" else eid2
                    t_id = eid2 if t1 == "ORGANISM" else eid1
                elif {t1, t2} == {"CHEMICAL", "DISEASE"}:
                    rel_type = "ASSOCIATED_WITH"
                    s_id = eid1 if t1 == "CHEMICAL" else eid2
                    t_id = eid2 if t1 == "CHEMICAL" else eid1
                elif {t1, t2} == {"ORGANISM", "PROTEIN"}:
                    rel_type = "EXPRESSES"
                    s_id = eid1 if t1 == "ORGANISM" else eid2
                    t_id = eid2 if t1 == "ORGANISM" else eid1
                elif {t1, t2} == {"PROTEIN", "PATHWAY"}:
                    rel_type = "PART_OF_PATHWAY"
                    s_id = eid1 if t1 == "PROTEIN" else eid2
                    t_id = eid2 if t1 == "PROTEIN" else eid1
                elif {t1, t2} == {"ORGANISM", "PATHWAY"}:
                    rel_type = "PART_OF_PATHWAY"
                    s_id = eid1 if t1 == "ORGANISM" else eid2
                    t_id = eid2 if t1 == "ORGANISM" else eid1
                elif {t1, t2} == {"DISEASE", "CLINICAL"}:
                    rel_type = "ASSOCIATED_WITH"
                elif {t1, t2} == {"DNA_RNA", "PROTEIN"}:
                    rel_type = "ENCODES"
                    s_id = eid1 if t1 == "DNA_RNA" else eid2
                    t_id = eid2 if t1 == "DNA_RNA" else eid1

                c.execute("""INSERT INTO relationships
                    (source_id, target_id, relationship_type, source_db,
                     confidence, evidence, evidence_type, validation_status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (s_id, t_id, rel_type, "co-occurrence",
                     0.5, f"Co-occur in {paper}",
                     "literature_co_occurrence", "unvalidated"))
                rel_inserted += 1
                rel_count += 1
                if rel_count % 100000 == 0:
                    print(f"    {rel_count} relationships generated...")
                    conn.commit()

    print(f"  Relationships: {rel_inserted} co-occurrence pairs (meaningful type pairs only)")

    # ── Create views ──
    c.executescript("""
    DROP VIEW IF EXISTS v_entity_relationships;
    CREATE VIEW v_entity_relationships AS
    SELECT r.id as relationship_id, e1.term as source_term, e1.entity_type as source_type,
           e2.term as target_term, e2.entity_type as target_type,
           r.relationship_type, r.source_db, r.confidence, r.evidence,
           r.evidence_type, r.validation_status
    FROM relationships r
    JOIN entities e1 ON r.source_id = e1.id
    JOIN entities e2 ON r.target_id = e2.id;

    DROP VIEW IF EXISTS v_project_entities;
    CREATE VIEW v_project_entities AS
    SELECT epm.project_id, p.title, p.condition, e.term, e.entity_type,
           e.confidence_score, epm.mention_type
    FROM entity_project_mentions epm
    LEFT JOIN projects p ON epm.project_id = p.project_id
    JOIN entities e ON epm.entity_id = e.id
    ORDER BY epm.project_id, e.entity_type, e.term;

    DROP VIEW IF EXISTS v_project_entity_counts;
    CREATE VIEW v_project_entity_counts AS
    SELECT p.project_id, p.title, p.condition,
           COUNT(DISTINCT e.id) as entity_count,
           COUNT(DISTINCT CASE WHEN e.entity_type='ORGANISM' THEN e.id END) as organism_count,
           COUNT(DISTINCT CASE WHEN e.entity_type='CHEMICAL' THEN e.id END) as chemical_count,
           COUNT(DISTINCT CASE WHEN e.entity_type='DISEASE' THEN e.id END) as disease_count,
           COUNT(DISTINCT CASE WHEN e.entity_type='PROTEIN' THEN e.id END) as protein_count
    FROM projects p
    LEFT JOIN entity_project_mentions epm ON p.project_id = epm.project_id
    LEFT JOIN entities e ON epm.entity_id = e.id
    GROUP BY p.project_id
    ORDER BY entity_count DESC;

    DROP VIEW IF EXISTS v_disease_organisms;
    CREATE VIEW v_disease_organisms AS
    SELECT e1.term as organism, e2.term as disease,
           r.relationship_type, r.confidence, r.evidence, r.source_db
    FROM relationships r
    JOIN entities e1 ON r.source_id = e1.id AND e1.entity_type = 'ORGANISM'
    JOIN entities e2 ON r.target_id = e2.id AND e2.entity_type = 'DISEASE'
    ORDER BY r.confidence DESC;

    DROP VIEW IF EXISTS v_metabolite_producers;
    CREATE VIEW v_metabolite_producers AS
    SELECT e1.term as organism, e2.term as metabolite,
           r.confidence, r.evidence
    FROM relationships r
    JOIN entities e1 ON r.source_id = e1.id AND e1.entity_type = 'ORGANISM'
    JOIN entities e2 ON r.target_id = e2.id AND e2.entity_type = 'CHEMICAL'
    WHERE r.relationship_type = 'PRODUCES'
    ORDER BY r.confidence DESC;

    DROP VIEW IF EXISTS v_entity_summary;
    CREATE VIEW v_entity_summary AS
    SELECT e.id, e.term, e.entity_type, e.confidence_score,
           e.paper_count, e.frequency,
           COUNT(DISTINCT r.id) as relationship_count,
           COUNT(DISTINCT epm.project_id) as project_mention_count,
           (SELECT GROUP_CONCAT(DISTINCT cv.vocabulary_name || ':' || cv.vocabulary_id)
            FROM controlled_vocabularies cv WHERE cv.entity_id = e.id) as vocab_mappings
    FROM entities e
    LEFT JOIN relationships r ON e.id = r.source_id OR e.id = r.target_id
    LEFT JOIN entity_project_mentions epm ON e.id = epm.entity_id
    GROUP BY e.id
    ORDER BY relationship_count DESC, e.term;

    DROP VIEW IF EXISTS v_entity_vocabularies;
    CREATE VIEW v_entity_vocabularies AS
    SELECT e.term, e.entity_type, cv.vocabulary_name, cv.vocabulary_id,
           cv.vocabulary_uri, cv.vocabulary_label, cv.mapping_confidence,
           cv.is_canonical
    FROM entities e
    JOIN controlled_vocabularies cv ON e.id = cv.entity_id
    ORDER BY e.entity_type, e.term, cv.is_canonical DESC, cv.mapping_confidence DESC;

    DROP VIEW IF EXISTS v_high_confidence_relationships;
    CREATE VIEW v_high_confidence_relationships AS
    SELECT r.id, e1.term as source_term, e1.entity_type as source_type,
           e2.term as target_term, e2.entity_type as target_type,
           r.relationship_type, r.confidence, r.evidence
    FROM relationships r
    JOIN entities e1 ON r.source_id = e1.id
    JOIN entities e2 ON r.target_id = e2.id
    WHERE r.confidence >= 0.7
    ORDER BY r.confidence DESC;
    """)

    conn.commit()

    # ── Stats ──
    for table in ["entity_types", "entities", "relationships", "projects",
                   "entity_project_mentions", "controlled_vocabularies"]:
        c.execute(f"SELECT COUNT(*) FROM {table}")
        print(f"    {table}: {c.fetchone()[0]} rows")

    conn.close()
    print(f"  Database saved to {db_path}")
    print(f"  DB size: {db_path.stat().st_size / 1024 / 1024:.1f} MB")

    return db_path


# ────────────────── Step 3: Create OWL ontology ──────────────────

def create_owl(corpus):
    print("\n" + "=" * 60)
    print("STEP 3: Creating OWL ontology")
    print("=" * 60)

    try:
        from rdflib import Graph, Namespace, URIRef, Literal, RDF, RDFS, OWL, XSD
    except ImportError:
        print("  rdflib not installed, skipping OWL")
        return None

    BASE = Namespace("http://microbiome-cdm.org/ontology#")
    g = Graph()
    ont_iri = URIRef("http://microbiome-cdm.org/ontology")
    g.add((ont_iri, RDF.type, OWL.Ontology))
    g.add((ont_iri, RDFS.label, Literal("Microbiome Common Data Model Ontology")))
    g.add((ont_iri, RDFS.comment, Literal(
        f"Entity ontology auto-generated from 444 microbiome papers. "
        f"{len(corpus['entities'])} entities, "
        f"{corpus['metadata']['entities_with_external_mapping']} mapped to controlled vocabularies.")))
    g.add((ont_iri, OWL.versionInfo, Literal("2.0.0")))

    # One owl:Class per CDM type
    for t in CDM_TYPES:
        cls = URIRef(f"http://microbiome-cdm.org/ontology#{t}")
        g.add((cls, RDF.type, OWL.Class))
        g.add((cls, RDFS.subClassOf, OWL.Thing))
        g.add((cls, RDFS.label, Literal(t.replace("_", " "))))

    # Object properties
    for prop_name in ["ASSOCIATED_WITH", "PRODUCES", "EXPRESSES", "ENCODES",
                      "PART_OF_PATHWAY", "CO_OCCURS_WITH", "METABOLIZES"]:
        prop = URIRef(f"http://microbiome-cdm.org/ontology#{prop_name}")
        g.add((prop, RDF.type, OWL.ObjectProperty))
        g.add((prop, RDFS.label, Literal(prop_name.replace("_", " ").lower())))

    # NamedIndividual per entity
    slug_seen = set()

    def slug(term):
        s = re.sub(r"[^A-Za-z0-9]+", "_", term).strip("_")
        if not s:
            s = "entity"
        base = s
        idx = 2
        while s.lower() in slug_seen:
            s = f"{base}_{idx}"
            idx += 1
        slug_seen.add(s.lower())
        return s

    for e in corpus["entities"]:
        s = slug(e["entity"])
        ind = URIRef(f"http://microbiome-cdm.org/ontology#{s}")
        cls = URIRef(f"http://microbiome-cdm.org/ontology#{e['entity_type']}")
        g.add((ind, RDF.type, cls))
        g.add((ind, RDFS.label, Literal(e["entity"])))
        g.add((ind, BASE.paperCount, Literal(e["paper_count"], datatype=XSD.integer)))
        g.add((ind, BASE.totalOccurrences, Literal(e["total_occurrences"], datatype=XSD.integer)))

        canon = e.get("canonical_mapping")
        if canon:
            g.add((ind, BASE.canonicalVocabulary, Literal(canon.get("ontology_name", ""))))
            g.add((ind, BASE.canonicalConceptId, Literal(canon.get("concept_id", ""))))
            g.add((ind, BASE.canonicalLabel, Literal(canon.get("label", ""))))
            g.add((ind, BASE.mappingConfidence, Literal(canon.get("confidence", 0.0), datatype=XSD.float)))

        for m in e.get("umls_mappings", []):
            g.add((ind, BASE.hasUMLSMapping, Literal(m.get("concept_id", ""))))
        for m in e.get("ols_mappings", []):
            cid = m.get("concept_id", "")
            if cid.startswith("http"):
                g.add((ind, BASE.hasOLSMapping, URIRef(cid)))
            else:
                g.add((ind, BASE.hasOLSMapping, Literal(cid)))
        for m in e.get("bioportal_mappings", []):
            cid = m.get("concept_id", "")
            if cid.startswith("http"):
                g.add((ind, BASE.hasBioPortalMapping, URIRef(cid)))
            else:
                g.add((ind, BASE.hasBioPortalMapping, Literal(cid)))
        for m in e.get("omop_mappings", []):
            g.add((ind, BASE.hasOMOPMapping, Literal(m.get("concept_id", ""))))
        for m in e.get("ncbi_taxon_mappings", []):
            g.add((ind, BASE.hasNCBITaxonMapping, Literal(m.get("concept_id", ""))))

    owl_path = OUT / "microbiome_cdm.owl"
    g.serialize(destination=str(owl_path), format="xml")
    ttl_path = OUT / "microbiome_cdm.ttl"
    g.serialize(destination=str(ttl_path), format="turtle")
    print(f"  OWL: {len(g)} triples, saved to {owl_path}")
    print(f"  TTL: saved to {ttl_path}")
    return owl_path


# ────────────────── Step 4: Build data catalogue ──────────────────

def build_catalogue(corpus, db_path):
    print("\n" + "=" * 60)
    print("STEP 4: Building data catalogue")
    print("=" * 60)

    # JSON catalogue
    by_type = defaultdict(list)
    for e in corpus["entities"]:
        by_type[e["entity_type"]].append(e)

    catalogue = {
        "name": "Microbiome CDM Data Catalogue",
        "version": "2.0.0",
        "created": datetime.now(timezone.utc).isoformat(),
        "source_papers": corpus["metadata"]["source_papers"],
        "total_entities": len(corpus["entities"]),
        "mapped_entities": corpus["metadata"]["entities_with_external_mapping"],
        "mapping_rate": round(100 * corpus["metadata"]["entities_with_external_mapping"] / len(corpus["entities"]), 1),
        "cdm_types": {},
        "vocabularies": Counter(),
        "top_entities_by_frequency": [],
        "top_entities_by_mapping": [],
    }

    for t in CDM_TYPES:
        ents = by_type.get(t, [])
        mapped = [e for e in ents if e["has_any_external_mapping"]]
        catalogue["cdm_types"][t] = {
            "total": len(ents),
            "mapped": len(mapped),
            "mapping_rate": round(100 * len(mapped) / len(ents), 1) if ents else 0,
            "top_terms": [e["entity"] for e in sorted(ents, key=lambda x: -x["paper_count"])[:20]],
        }

    for e in corpus["entities"]:
        canon = e.get("canonical_mapping")
        if canon:
            catalogue["vocabularies"][canon.get("ontology_name", "UNKNOWN")] += 1

    catalogue["top_entities_by_frequency"] = [
        {"term": e["entity"], "type": e["entity_type"],
         "paper_count": e["paper_count"], "occurrences": e["total_occurrences"],
         "mapped": e["has_any_external_mapping"],
         "canonical": e.get("canonical_mapping", {}).get("concept_id", "") if e.get("canonical_mapping") else ""}
        for e in sorted(corpus["entities"], key=lambda x: -x["paper_count"])[:100]
    ]

    mapped_entities = [e for e in corpus["entities"] if e["has_any_external_mapping"]]
    catalogue["top_entities_by_mapping"] = [
        {"term": e["entity"], "type": e["entity_type"],
         "canonical_vocab": e.get("canonical_mapping", {}).get("ontology_name", ""),
         "canonical_id": e.get("canonical_mapping", {}).get("concept_id", ""),
         "canonical_label": e.get("canonical_mapping", {}).get("label", ""),
         "confidence": e.get("canonical_mapping", {}).get("confidence", 0),
         "paper_count": e["paper_count"]}
        for e in sorted(mapped_entities, key=lambda x: -x.get("canonical_mapping", {}).get("confidence", 0))[:100]
    ]

    cat_path = OUT / "data_catalogue.json"
    with open(cat_path, "w", encoding="utf-8") as f:
        json.dump(catalogue, f, indent=2, ensure_ascii=False)
    print(f"  JSON catalogue saved to {cat_path}")

    # CSV catalogue
    csv_path = OUT / "data_catalogue.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "term", "entity_type", "paper_count", "total_occurrences",
            "has_mapping", "canonical_vocab", "canonical_id", "canonical_label",
            "mapping_confidence", "all_vocab_mappings",
        ])
        for e in corpus["entities"]:
            canon = e.get("canonical_mapping") or {}
            all_vocabs = "; ".join(
                f"{m.get('ontology_name', '')}:{m.get('concept_id', '')}"
                for m in (e.get("umls_mappings", []) + e.get("bioportal_mappings", []) +
                          e.get("ols_mappings", []) + e.get("omop_mappings", []) +
                          e.get("ncbi_taxon_mappings", []))
            )
            writer.writerow([
                e["entity"], e["entity_type"], e["paper_count"], e["total_occurrences"],
                e["has_any_external_mapping"],
                canon.get("ontology_name", ""), canon.get("concept_id", ""),
                canon.get("label", ""), canon.get("confidence", ""),
                all_vocabs,
            ])
    print(f"  CSV catalogue saved to {csv_path}")

    # ── DB stats from SQLite ──
    conn = sqlite3.connect(str(db_path))
    c = conn.cursor()
    db_stats = {}
    c.execute("SELECT entity_type, COUNT(*) FROM entities GROUP BY entity_type ORDER BY COUNT(*) DESC")
    db_stats["entities_by_type"] = {r[0]: r[1] for r in c.fetchall()}

    c.execute("SELECT vocabulary_name, COUNT(*) FROM controlled_vocabularies GROUP BY vocabulary_name ORDER BY COUNT(*) DESC")
    db_stats["vocab_by_name"] = {r[0]: r[1] for r in c.fetchall()}

    c.execute("SELECT relationship_type, COUNT(*) FROM relationships GROUP BY relationship_type ORDER BY COUNT(*) DESC")
    db_stats["relationships_by_type"] = {r[0]: r[1] for r in c.fetchall()}

    c.execute("SELECT COUNT(DISTINCT project_id) FROM entity_project_mentions")
    db_stats["projects_with_mentions"] = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM projects WHERE title IS NOT NULL")
    db_stats["projects_with_metadata"] = c.fetchone()[0]

    conn.close()

    stats_path = OUT / "db_statistics.json"
    with open(stats_path, "w", encoding="utf-8") as f:
        json.dump(db_stats, f, indent=2)
    print(f"  DB statistics saved to {stats_path}")

    # Print summary
    print(f"\n  CDM Type breakdown:")
    for t in CDM_TYPES:
        d = catalogue["cdm_types"].get(t, {})
        print(f"    {t:20s} {d.get('total', 0):5d} entities, {d.get('mapped', 0):5d} mapped ({d.get('mapping_rate', 0):.1f}%)")
    print(f"\n  Top vocabularies:")
    for v, cnt in catalogue["vocabularies"].most_common(15):
        print(f"    {v:20s} {cnt}")
    print(f"\n  Relationships:")
    for rt, cnt in db_stats["relationships_by_type"].items():
        print(f"    {rt:20s} {cnt}")

    return cat_path


# ────────────────── Step 5: Provenance ──────────────────

def build_provenance(corpus):
    print("\n" + "=" * 60)
    print("STEP 5: Building provenance trace")
    print("=" * 60)

    provenance = {
        "metadata": {
            "name": "Microbiome CDM Provenance",
            "version": "2.0.0",
            "created": datetime.now(timezone.utc).isoformat(),
            "pipeline": [
                {"step": 1, "name": "NER extraction", "models": ["GLiNER", "PubTator3", "BioBERT"],
                 "papers": corpus["metadata"]["source_papers"]},
                {"step": 2, "name": "Entity deduplication", "method": "case-insensitive normalize + junk filter",
                 "unique_entities": len(corpus["entities"])},
                {"step": 3, "name": "Ontology mapping", "services": ["OLS", "OMOP Athena", "NCBI Taxonomy"],
                 "mapped": corpus["metadata"]["entities_with_external_mapping"]},
                {"step": 4, "name": "Relationship extraction", "method": "co-occurrence within papers, meaningful type pairs"},
                {"step": 5, "name": "Schema creation", "tables": 8, "indexes": 24, "views": 8},
            ],
        },
        "entities": [],
    }

    for e in corpus["entities"]:
        canon = e.get("canonical_mapping") or {}
        method = "none"
        if canon:
            if canon.get("confidence", 0) >= 0.95:
                method = "vocab_exact"
            elif canon.get("source") == "umls":
                method = "ner_link"
            else:
                method = "fuzzy_match"

        provenance["entities"].append({
            "raw_term": e["entity"],
            "resolved_term": e["entity"],
            "entity_type": e["entity_type"],
            "canonical_id": canon.get("concept_id", ""),
            "canonical_vocab": canon.get("ontology_name", ""),
            "normalization": {"method": method, "confidence": canon.get("confidence", 0)},
            "paper_count": e["paper_count"],
            "source_papers": e["papers"][:5],
            "ner_sources": e.get("sources", []),
        })

    prov_path = OUT / "cdm_provenance.json"
    with open(prov_path, "w", encoding="utf-8") as f:
        json.dump(provenance, f, indent=2, ensure_ascii=False)
    print(f"  Provenance saved to {prov_path} ({len(provenance['entities'])} records)")


# ────────────────── Main ──────────────────

def main():
    t0 = time.time()
    print("Microbiome CDM Builder v2.0")
    print(f"Output directory: {OUT}")
    print()

    corpus, entity_papers = build_corpus()
    db_path = create_db(corpus, entity_papers)
    create_owl(corpus)
    build_catalogue(corpus, db_path)
    build_provenance(corpus)

    elapsed = time.time() - t0
    print(f"\n{'=' * 60}")
    print(f"CDM build complete in {elapsed:.1f}s")
    print(f"Output files in {OUT}:")
    for f in sorted(OUT.glob("*")):
        size = f.stat().st_size
        unit = "MB" if size > 1024 * 1024 else "KB"
        val = size / 1024 if unit == "KB" else size / 1024 / 1024
        print(f"  {f.name:40s} {val:8.1f} {unit}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
