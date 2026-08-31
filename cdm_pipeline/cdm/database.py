"""Step 2: Create SQLite CDM database with schema, data, relationships, and views."""
import json
import sqlite3
from collections import defaultdict

from ..config import CDM_TYPES, PAPERS_DIR, CDM_OUTPUT_DIR, BIOPROJECT_JSON

OUT = CDM_OUTPUT_DIR


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
