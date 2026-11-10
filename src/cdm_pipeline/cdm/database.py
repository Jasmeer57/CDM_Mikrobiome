"""Step 2: Create SQLite CDM database with schema, data, relationships, and views."""
import json
import sqlite3
import sys
from collections import defaultdict

from ..config import CDM_TYPES, PAPERS_DIR, CDM_OUTPUT_DIR, BIOPROJECT_JSON, REPO_ROOT, VOCAB_PRIORITY

# Import biological KB for curated edges
sys.path.insert(0, str(REPO_ROOT / "paper_claims"))
try:
    import biological_kb as _kb
except ImportError:
    _kb = None

OUT = CDM_OUTPUT_DIR

# ── Vocabulary name normalization (M2 fix) ──
# Canonicalize vocabulary names so SNOMED/SNOMEDCT, FB-BT/FBBT etc. merge.
_VOCAB_ALIASES = {
    "SNOMED": "SNOMEDCT",
    "FBBT": "FB-BT",
    "FBCV": "FB-CV",
    "SCHEMAORG_HTTPS": "SCHEMAORG_HTTP",
    "APOLLO_SV": "APOLLO-SV",
    "BPT": "BP",
    "REPRODUCEME": "REPRODUCE-ME",
    "WBBT": "WB-BT",
    "BCIO": "BCI-O",
    "CCONT": "CCON",
    "LNC": "LOINC",
    "NCBITAX": "NCBITAXON",
    "NCBITaxon": "NCBITAXON",
}


def _normalize_vocab_name(name: str) -> str:
    """Canonicalize vocabulary name to merge alias pairs (M2 fix)."""
    if not name:
        return name
    upper = name.upper()
    return _VOCAB_ALIASES.get(upper, name)


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
        ner_gliner BOOLEAN DEFAULT 0,
        ner_pubmedbert BOOLEAN DEFAULT 0,
        ner_pubtator3 BOOLEAN DEFAULT 0,
        ner_qwen BOOLEAN DEFAULT 0,
        ner_scispacy BOOLEAN DEFAULT 0,
        source_scores TEXT,
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
        source_type TEXT DEFAULT 'co_occurrence',
        validation_status TEXT,
        npm_i REAL,
        p_value REAL,
        q_value REAL,
        co_occurrence_count INTEGER,
        eco_code TEXT,
        original_predicate TEXT,
        demotion_reason TEXT,
        direction_demoted_to TEXT,
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
        char_start INTEGER,
        char_end INTEGER,
        source_model TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (entity_id) REFERENCES entities(id)
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
        mapping_tier INTEGER,
        is_canonical BOOLEAN DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (entity_id) REFERENCES entities(id)
    );
    CREATE INDEX idx_cv_entity ON controlled_vocabularies(entity_id);
    CREATE INDEX idx_cv_vocabulary ON controlled_vocabularies(vocabulary_name);
    CREATE INDEX idx_cv_vocab_id ON controlled_vocabularies(vocabulary_id);

    CREATE TABLE edge_evidence (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        relationship_id INTEGER NOT NULL,
        paper_id TEXT NOT NULL,
        char_start INTEGER,
        char_end INTEGER,
        source_model TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (relationship_id) REFERENCES relationships(id)
    );
    CREATE INDEX idx_edge_ev_rel ON edge_evidence(relationship_id);
    CREATE INDEX idx_edge_ev_paper ON edge_evidence(paper_id);

    CREATE TABLE run_metadata (
        key TEXT PRIMARY KEY,
        value TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
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
    import re as _re

    _JUNK_PATTERNS = [
        _re.compile(r"^\W+$"),                    # punctuation only
        _re.compile(r"^\d+$"),                    # digits only
        _re.compile(r"^.$"),                      # single character
        _re.compile(r"^(the|and|of|in|for|with|from|study|studies|patient|patients|"
                    r"sample|samples|data|result|results|method|methods|analysis|"
                    r"group|groups|level|levels|effect|effects|control|controls)$",
                    _re.IGNORECASE),               # stopword-like
        _re.compile(r"^[\x00-\x1f]"),              # leading control characters
        _re.compile(r"^(fig|figure|table|supplementary)\b", _re.IGNORECASE),  # doc furniture
    ]

    # Taxonomic suffix patterns for ORGANISM plausibility check
    _TAXON_SUFFIXES = _re.compile(
        r"(bacteria|archaea|viridae|aceae|ales|ota|phyta|phytes|"
        r"coccaceae|obact|aceae|bacter|bacteria|mycota|mycetes|"
        r"virales|virus|viruses|phage|phages|fungi|yeast|"
        r"microbe|microbes|microbiota|microbiome)$",
        _re.IGNORECASE,
    )
    # Known common organism terms (lowercase)
    _COMMON_ORGANISM_TERMS = {
        "bacteria", "archaea", "fungi", "yeast", "yeasts", "mold", "molds",
        "virus", "viruses", "phage", "phages", "bacteriophage", "bacteriophages",
        "probiotic", "probiotics", "pathogen", "pathogens",
        "commensal", "commensals", "symbiont", "symbionts",
        "microbe", "microbes", "microbiota", "microbiome", "microflora",
        "enterobacteria", "enterococci", "bacteroides", "firmicutes",
        "proteobacteria", "actinobacteria", "fusobacteria", "verrucomicrobia",
        "cyanobacteria", "spirochaetes", "synergistetes", "taenicutes",
        "euryarchaeota", "crenarchaeota", "thaumarchaeota",
        "archaeon", "bacterium", "protozoon", "protozoa",
        "clostridia", "bacilli", "gammaproteobacteria", "deltaproteobacteria",
        "alphaproteobacteria", "betaproteobacteria",
    }

    def _looks_like_organism(term):
        """Check if a term is plausibly an organism name."""
        t = term.strip()
        if not t or len(t) < 3:
            return False
        # Contains digits or special chars (not organism-like)
        if _re.search(r"[0-9/%&\\\(\)<>=\[\]{}@#|]", t):
            return False
        # Latin binomial: "Genus species" pattern
        if _re.match(r"^[A-Z][a-z]{2,}\s+(sp\.?|spp\.?|[a-z]{2,}|[A-Z]\.?\s*[a-z]+)$", t):
            return True
        # Taxonomic suffix
        if _TAXON_SUFFIXES.search(t):
            return True
        # Single capitalized word (potential genus)
        if _re.match(r"^[A-Z][a-z]{2,}$", t):
            return True
        # Known common terms
        if t.lower() in _COMMON_ORGANISM_TERMS:
            return True
        # "X spp." / "X sp."
        if _re.match(r"^[A-Z][a-z]+\s+spp?\.?$", t):
            return True
        # Genus + abbreviation: "B. fragilis", "L. casei"
        if _re.match(r"^[A-Z]\.\s*[a-z]{3,}$", t):
            return True
        return False

    def _is_junk_term(term):
        """Check if a term is a degenerate/junk surface form that should be excluded."""
        if not term:
            return True
        s = str(term).strip()
        if not s or len(s) > 100:
            return len(s) > 100  # over 100 chars = junk
        for pat in _JUNK_PATTERNS:
            if pat.search(s):
                return True
        # Check for control characters anywhere
        if any(ord(ch) < 32 and ch not in "\t\n\r" for ch in s):
            return True
        return False

    entity_id_map = {}  # norm -> entity_id
    eid_type = {}       # entity_id -> entity_type
    junk_skipped = 0
    organism_junk_skipped = 0
    for e in corpus["entities"]:
        if _is_junk_term(e.get("entity", "")):
            junk_skipped += 1
            continue
        # Filter NER false-positive ORGANISM entities: if ORGANISM type, no
        # NCBITaxon mapping, and term doesn't look like an organism name, skip
        if e.get("entity_type") == "ORGANISM":
            has_ncbi = bool(e.get("ncbi_taxon_mappings"))
            if not has_ncbi:
                # Check OLS/BioPortal mappings for NCBITaxon ontology
                for key in ("ols_mappings", "bioportal_mappings", "related_mappings"):
                    for m in e.get(key, []):
                        if isinstance(m, dict) and "NCBITAXON" in m.get("ontology_name", "").upper():
                            has_ncbi = True
                            break
                    if has_ncbi:
                        break
                if not has_ncbi:
                    canon = e.get("canonical_mapping") or {}
                    if "NCBITAXON" in canon.get("ontology_name", "").upper() or \
                       canon.get("source") == "ncbi_taxon":
                        has_ncbi = True
            if not has_ncbi and not _looks_like_organism(e.get("entity", "")):
                organism_junk_skipped += 1
                continue
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
        definition = e.get("definition", "")
        aliases = e.get("aliases", "")
        context = e.get("context", "")
        sources = set(e.get("sources", []) or [])
        source_scores = json.dumps(e.get("source_scores", {})) if e.get("source_scores") else ""
        ner_g = 1 if "GLiNER" in sources else 0
        ner_p = 1 if "PubMedBERT" in sources else 0
        ner_t = 1 if "PubTator3" in sources else 0
        ner_q = 1 if "Qwen" in sources else 0
        ner_s = 1 if "sciSpaCy" in sources else 0

        c.execute("""INSERT INTO entities
            (term, entity_type, confidence_score, paper_count, frequency,
             is_core_term, UMLS_ID, OMOP, OLS, Bioportal, NCBITaxon, umls_mapped,
             definition, contextual_definition, aliases,
             ner_gliner, ner_pubmedbert, ner_pubtator3, ner_qwen, ner_scispacy,
             source_scores)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (e["entity"], e["entity_type"], confidence,
             e["paper_count"], e["total_occurrences"],
             is_core, umls_id, omop_id, ols_id, bp_id, ncbi_id,
             bool(umls_id), definition, context, aliases,
             ner_g, ner_p, ner_t, ner_q, ner_s, source_scores))
        entity_id_map[e["norm"]] = c.lastrowid
        eid_type[c.lastrowid] = e["entity_type"]

    print(f"  Entities: {len(corpus['entities'])} total, "
          f"{junk_skipped} junk filtered, "
          f"{organism_junk_skipped} organism-implausible filtered, "
          f"{len(entity_id_map)} inserted")

    # ── Populate controlled_vocabularies (M1b: strict VOCAB_PRIORITY, M2: normalize) ──
    cv_count = 0
    cv_excluded = 0
    for e in corpus["entities"]:
        if e["norm"] not in entity_id_map:
            continue
        eid = entity_id_map[e["norm"]]
        etype = e["entity_type"]
        canon = e.get("canonical_mapping")
        all_maps = (e.get("umls_mappings", []) + e.get("bioportal_mappings", []) +
                    e.get("ols_mappings", []) + e.get("omop_mappings", []) +
                    e.get("ncbi_taxon_mappings", []))
        # M1b: only allow vocabs in VOCAB_PRIORITY for this entity type
        allowed_vocabs = {v.upper() for v in VOCAB_PRIORITY.get(etype, [])}

        seen = set()
        for m in all_maps:
            vocab_name = _normalize_vocab_name(m.get("ontology_name", ""))
            vocab_upper = vocab_name.upper()
            # M1b: skip vocabs not in the type's priority list
            if vocab_upper not in allowed_vocabs:
                cv_excluded += 1
                continue
            key = (vocab_name, m.get("concept_id", ""))
            if key in seen:
                continue
            seen.add(key)
            is_canon = (canon and m.get("source") == canon.get("source") and
                        m.get("concept_id") == canon.get("concept_id"))
            tier = m.get("mapping_tier")
            if tier is None and m.get("source") == "ncbi_taxon":
                conf = m.get("confidence", 0)
                tier = 1 if conf >= 1.0 else (2 if conf >= 0.85 else 3)
            # M3: Backfill tier for OLS/BioPortal-sourced NCBITaxon mappings
            if (tier is None and
                    vocab_upper in {"NCBITAXON", "NCBITAX"} and
                    m.get("source") in ("ols", "bioportal")):
                conf = m.get("confidence", 0)
                tier = 2 if conf >= 0.90 else 3
            c.execute("""INSERT INTO controlled_vocabularies
                (entity_id, vocabulary_name, vocabulary_id, vocabulary_uri,
                 vocabulary_label, mapping_confidence, mapping_source,
                 mapping_tier, is_canonical)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (eid, vocab_name, m.get("concept_id", ""),
                 m.get("concept_id", "") if m.get("concept_id", "").startswith("http") else "",
                 m.get("label", ""), m.get("confidence", 0.0),
                 m.get("source", ""), tier, is_canon))
            cv_count += 1
    print(f"  Controlled vocabulary mappings: {cv_count:,} "
          f"({cv_excluded:,} type-inappropriate excluded)")

    # ── Populate entity_project_mentions with character offsets ──
    mention_count = 0
    mention_rows = 0
    for e in corpus["entities"]:
        if e["norm"] not in entity_id_map:
            continue
        eid = entity_id_map[e["norm"]]
        # Group mentions by paper, keeping all offset occurrences
        mentions_by_paper = defaultdict(list)
        for m in e.get("mentions", []):
            paper, cs, ce, model = m
            mentions_by_paper[paper].append((cs, ce, model))

        for paper in e.get("papers", []):
            pid = paper.replace(".txt", "")
            offsets = mentions_by_paper.get(paper, [(0, 0, None)])
            for cs, ce, model in offsets:
                try:
                    c.execute("""INSERT INTO entity_project_mentions
                        (entity_id, project_id, mention_type, char_start, char_end, source_model)
                        VALUES (?, ?, ?, ?, ?, ?)""",
                        (eid, pid, e["entity_type"], cs or None, ce or None, model))
                    mention_rows += 1
                except sqlite3.IntegrityError:
                    pass
            mention_count += 1
    print(f"  Entity-project mentions: {mention_count} entity-paper pairs, "
          f"{mention_rows} individual mention rows (with offsets)")

    # ── Generate significance-tested co-occurrence relationships ──
    print("  Generating significance-tested co-occurrence relationships...")
    paper_entities = defaultdict(list)
    for e in corpus["entities"]:
        if e["norm"] not in entity_id_map:
            continue
        eid = entity_id_map[e["norm"]]
        for paper in e.get("papers", []):
            paper_entities[paper].append((eid, e["entity_type"], e["entity"]))

    # Build entity source counts for confidence weighting
    entity_source_count = {}  # eid -> number of NER models
    for e in corpus["entities"]:
        if e["norm"] not in entity_id_map:
            continue
        eid = entity_id_map[e["norm"]]
        entity_source_count[eid] = len(e.get("sources", []))

    # Document frequency for each entity (how many papers it appears in)
    entity_df = defaultdict(int)
    for e in corpus["entities"]:
        if e["norm"] not in entity_id_map:
            continue
        eid = entity_id_map[e["norm"]]
        entity_df[eid] = len(e.get("papers", []))

    total_papers = max(len(paper_entities), 1)

    # IDF-weighted generic filtering: instead of a hard 50% DF cutoff, we use
    # IDF = log(N / df) to soft-downweight highly generic entities.  Entities
    # appearing in >80% of papers are still hard-excluded (truly generic), but
    # the 50-80% band is kept with reduced co-occurrence weight.
    import math as _math
    N = total_papers
    hard_excl_df = N * 0.80
    generic_eids = {eid for eid, df in entity_df.items() if df > hard_excl_df}
    if generic_eids:
        print(f"    Hard-excluded {len(generic_eids)} generic entities (DF > 80% of papers)")
    print(f"    IDF weighting applied to all retained entities (no hard 50% cutoff)")

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

    # Track per-paper co-occurrence for source_doc provenance (R5 fix)
    pair_papers = defaultdict(set)  # (min_eid, max_eid) -> {paper filenames}

    # Build type -> set of compatible types lookup from meaningful_pairs
    type_compat = defaultdict(set)
    for fs in meaningful_pairs:
        types = list(fs)
        if len(types) == 2:
            t_a, t_b = types
            type_compat[t_a].add(t_b)
            type_compat[t_b].add(t_a)
        elif len(types) == 1:
            t_a = types[0]
            type_compat[t_a].add(t_a)

    # First pass: count co-occurrence frequency per entity pair.
    # Group entities by type per paper, then only iterate over
    # type-compatible pairs — avoids O(n²) over all entities.
    pair_freq = defaultdict(int)  # (min_eid, max_eid) -> paper count
    skipped_large = 0
    for paper, ents in paper_entities.items():
        filtered = [(eid, t) for eid, t, term in ents if eid not in generic_eids]
        if not filtered:
            continue
        by_type = defaultdict(list)
        for eid, t in filtered:
            by_type[t].append(eid)
        for t_a, eids_a in by_type.items():
            for t_b in type_compat.get(t_a, ()):
                if t_b < t_a:
                    continue
                eids_b = by_type.get(t_b)
                if not eids_b:
                    continue
                if t_a == t_b:
                    for i in range(len(eids_a)):
                        for j in range(i + 1, len(eids_a)):
                            eid1, eid2 = eids_a[i], eids_a[j]
                            if eid1 == eid2:
                                continue
                            pair_key = (min(eid1, eid2), max(eid1, eid2))
                            pair_freq[pair_key] += 1
                            pair_papers[pair_key].add(paper)
                else:
                    for eid1 in eids_a:
                        for eid2 in eids_b:
                            if eid1 == eid2:
                                continue
                            pair_key = (min(eid1, eid2), max(eid1, eid2))
                            pair_freq[pair_key] += 1
                            pair_papers[pair_key].add(paper)

    # Min co-occurrence threshold: pairs with <5 co-occurrences are excluded
    # from significance testing (G-test unreliable for expected counts <5).
    MIN_COOCCURRENCE = 5
    eligible_pairs = {pk: f for pk, f in pair_freq.items() if f >= MIN_COOCCURRENCE}
    excluded_low_support = len(pair_freq) - len(eligible_pairs)
    print(f"    Pairs with co-occurrence < {MIN_COOCCURRENCE}: {excluded_low_support} "
          f"(excluded from significance testing)")
    print(f"    Eligible pairs (>= {MIN_COOCCURRENCE} co-occurrences): {len(eligible_pairs)}")

    # ── Significance testing: NPMI + log-likelihood G-test + BH-FDR ──
    # Only eligible pairs (co-occurrence >= MIN_COOCCURRENCE) are tested.
    # We declare this count as the number of hypotheses entering BH correction.
    import math
    try:
        from scipy.stats import chi2 as _chi2
        _HAS_SCIPY = True
    except ImportError:
        _HAS_SCIPY = False
        print("    (scipy not available — using NPMI threshold only, no p-values)")

    # For Fisher's exact on low-support pairs (fallback when G-test unreliable)
    try:
        from scipy.stats import fisher_exact as _fisher_exact
        _HAS_FISHER = True
    except ImportError:
        _HAS_FISHER = False

    # Compute NPMI and p-value for each eligible pair
    pair_stats = {}  # pair_key -> (npmi, p_value, co_freq)
    N = total_papers
    for (eid_a, eid_b), co_freq in eligible_pairs.items():
        df_a = entity_df.get(eid_a, 0)
        df_b = entity_df.get(eid_b, 0)
        if df_a == 0 or df_b == 0:
            continue
        p_a = df_a / N
        p_b = df_b / N
        p_ab = co_freq / N
        # NPMI with shrinkage toward 0 for small co-occurrence counts.
        # Shrinkage lambda = 1/(co_freq+1) pulls NPMI toward 0 (independence)
        # when support is low, reducing false positives.
        pmi = math.log(p_ab / (p_a * p_b))
        npm_i = pmi / (-math.log(p_ab)) if p_ab < 1 else 1.0
        shrinkage = co_freq / (co_freq + 1.0)  # 0.83 at n=5, 0.91 at n=10
        npm_i = npm_i * shrinkage

        # Log-likelihood ratio (G-test) for 2x2 contingency table
        if _HAS_SCIPY:
            o11 = co_freq
            o12 = df_a - co_freq
            o21 = df_b - co_freq
            o22 = N - df_a - df_b + co_freq
            if min(o11, o22, o12, o21) >= 5 or not _HAS_FISHER:
                # G-test valid when all expected counts >= 5
                e11 = (df_a * df_b) / N
                e12 = (df_a * (N - df_b)) / N
                e21 = ((N - df_a) * df_b) / N
                e22 = ((N - df_a) * (N - df_b)) / N
                G = 0
                for o, e in [(o11, e11), (o12, e12), (o21, e21), (o22, e22)]:
                    if o > 0 and e > 0:
                        G += 2 * o * math.log(o / e)
                p_value = float(_chi2.sf(G, df=1))
            else:
                # Fisher's exact for low expected counts (more reliable)
                _, p_value = _fisher_exact([[o11, o12], [o21, o22]])
                p_value = float(p_value)
        else:
            p_value = None
        pair_stats[(eid_a, eid_b)] = (npm_i, p_value, co_freq)

    # Benjamini-Hochberg FDR correction
    # The number of hypotheses tested is |pair_stats| — only eligible pairs
    # with co-occurrence >= MIN_COOCCURRENCE, NOT all possible pairs.
    # This is a defensible scope (we only test biologically meaningful type
    # pairs with sufficient support), but we declare it explicitly.
    m_hypotheses = len(pair_stats)
    print(f"    Hypotheses entering BH correction: {m_hypotheses}")
    if _HAS_SCIPY and pair_stats:
        # Sort by p-value ascending
        sorted_pairs = sorted(
            ((pk, pv[1], pv[0], pv[2]) for pk, pv in pair_stats.items() if pv[1] is not None),
            key=lambda x: x[1],
        )
        m = len(sorted_pairs)
        q_values = {}
        # BH q-value: q_i = min_{j >= i} (m / j) * p_j
        # Walk from largest p (bottom) upward, taking running min
        prev_q = 1.0
        q_list = [0.0] * m
        for i in range(m - 1, -1, -1):
            rank = i + 1  # 1-indexed
            pk, pval, npm_i, co = sorted_pairs[i]
            raw_q = (m / rank) * pval
            prev_q = min(prev_q, raw_q)
            q_list[i] = min(prev_q, 1.0)
        for i, (pk, pval, npm_i, co) in enumerate(sorted_pairs):
            q_values[pk] = q_list[i]
        # None for pairs without p-values
        for pk, pv in pair_stats.items():
            if pv[1] is None:
                q_values[pk] = None
    else:
        q_values = {pk: None for pk in pair_stats}

    significant_pairs = set()
    for pair_key, (npmi, pval, co) in pair_stats.items():
        q = q_values.get(pair_key)
        if q is not None and q < 0.05:
            significant_pairs.add(pair_key)
        elif not _HAS_SCIPY and npmi > 0.2:
            # Fallback: NPMI > 0.2 as significance proxy
            significant_pairs.add(pair_key)

    print(f"    Total pairs tested: {len(pair_stats)}, significant (FDR<0.05): {len(significant_pairs)}")

    # Second pass: insert relationships directly from pair_freq (no paper
    # re-scan needed — pair_freq and pair_papers already built in first pass).
    # Only insert SIGNIFICANT pairs (FDR<0.05) to keep the DB compact.
    # Unasserted edges are dropped — they carry no statistical evidence.
    rel_count = 0
    rel_inserted = 0
    for pair_key in significant_pairs:
        co_freq = pair_freq.get(pair_key, 0)
        if co_freq < MIN_COOCCURRENCE:
            continue
        eid_a, eid_b = pair_key
        t_a = eid_type.get(eid_a, "")
        t_b = eid_type.get(eid_b, "")
        if frozenset((t_a, t_b)) not in meaningful_pairs:
            continue

        # Determine relationship type from type pair
        rel_type = "CO_OCCURS_WITH"
        s_id, t_id = eid_a, eid_b
        if {t_a, t_b} == {"ORGANISM", "DISEASE"}:
            rel_type = "ASSOCIATED_WITH"
            s_id = eid_a if t_a == "ORGANISM" else eid_b
            t_id = eid_b if t_a == "ORGANISM" else eid_a
        elif {t_a, t_b} == {"ORGANISM", "CHEMICAL"}:
            rel_type = "PRODUCES"
            s_id = eid_a if t_a == "ORGANISM" else eid_b
            t_id = eid_b if t_a == "ORGANISM" else eid_a
        elif {t_a, t_b} == {"CHEMICAL", "DISEASE"}:
            rel_type = "ASSOCIATED_WITH"
            s_id = eid_a if t_a == "CHEMICAL" else eid_b
            t_id = eid_b if t_a == "CHEMICAL" else eid_a
        elif {t_a, t_b} == {"ORGANISM", "PROTEIN"}:
            rel_type = "EXPRESSES"
            s_id = eid_a if t_a == "ORGANISM" else eid_b
            t_id = eid_b if t_a == "ORGANISM" else eid_a
        elif {t_a, t_b} == {"PROTEIN", "PATHWAY"}:
            rel_type = "PART_OF_PATHWAY"
            s_id = eid_a if t_a == "PROTEIN" else eid_b
            t_id = eid_b if t_a == "PROTEIN" else eid_a
        elif {t_a, t_b} == {"ORGANISM", "PATHWAY"}:
            rel_type = "PART_OF_PATHWAY"
            s_id = eid_a if t_a == "ORGANISM" else eid_b
            t_id = eid_b if t_a == "ORGANISM" else eid_a
        elif {t_a, t_b} == {"DISEASE", "CLINICAL"}:
            rel_type = "ASSOCIATED_WITH"
        elif {t_a, t_b} == {"DNA_RNA", "PROTEIN"}:
            rel_type = "ENCODES"
            s_id = eid_a if t_a == "DNA_RNA" else eid_b
            t_id = eid_b if t_a == "DNA_RNA" else eid_a

        # Significance metadata
        stats = pair_stats.get(pair_key)
        is_sig = pair_key in significant_pairs
        if stats:
            npm_i_val, p_val, co_freq = stats
        else:
            npm_i_val, p_val = None, None
        q_val = q_values.get(pair_key)

        # Differentiated confidence:
        #   base 0.5
        #   + 0.05 per additional model confirming each entity (up to 5 models)
        #   + 0.02 per additional co-occurrence paper (up to 10)
        #   IDF-weighted: high-DF entities get less confidence boost
        # NOTE: no +0.1 significance boost — uncertainty is handled by
        # the conformal prediction module (conformal.py), not by
        # inflating point-estimate confidence.
        n_src1 = entity_source_count.get(s_id, 1)
        n_src2 = entity_source_count.get(t_id, 1)
        conf = 0.5
        conf += 0.05 * min(n_src1 - 1, 4)
        conf += 0.05 * min(n_src2 - 1, 4)
        conf += 0.02 * min(co_freq - 1, 10)
        # IDF downweight: entities in many papers contribute less signal
        idf_a = math.log(N / max(entity_df.get(s_id, 1), 1))
        idf_b = math.log(N / max(entity_df.get(t_id, 1), 1))
        avg_idf = (idf_a + idf_b) / 2
        max_idf = math.log(N)  # theoretical max
        if max_idf > 0:
            idf_factor = avg_idf / max_idf  # [0, 1]
            conf *= 0.7 + 0.3 * idf_factor  # scale to [0.7, 1.0] of raw conf
        # Penalize non-significant edges
        if stats and not is_sig:
            conf -= 0.1
        conf = round(max(0.1, min(conf, 0.95)), 3)

        # validation_status: "significant" if FDR<0.05, else "unasserted"
        val_status = "significant" if is_sig else "unasserted"

        # R5 provenance: per-paper links now stored in edge_evidence table
        source_papers = pair_papers.get(pair_key, set())

        c.execute("""INSERT INTO relationships
            (source_id, target_id, relationship_type, source_db,
             confidence, evidence, evidence_type, validation_status,
             paper_doi, source_type, npm_i, p_value, q_value, co_occurrence_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (s_id, t_id, rel_type, "co-occurrence",
             conf, f"Co-occur in {co_freq} paper(s)",
             "literature_co_occurrence", val_status,
             None, "co_occurrence",
             npm_i_val, p_val, q_val, co_freq))
        rel_id = c.lastrowid
        # Populate edge_evidence with per-paper provenance
        for paper_name in sorted(source_papers):
            c.execute("""INSERT INTO edge_evidence
                (relationship_id, paper_id) VALUES (?, ?)""",
                (rel_id, paper_name))
        rel_inserted += 1
        rel_count += 1
        if rel_count % 100000 == 0:
            print(f"    {rel_count} relationships generated...")
            conn.commit()

    print(f"  Co-occurrence relationships: {rel_inserted} total "
          f"(all significant FDR<0.05, unasserted edges dropped)")
    print(f"    Hypotheses tested: {m_hypotheses}, "
          f"FDR threshold: 0.05, "
          f"min co-occurrence: {MIN_COOCCURRENCE}")
    print(f"    NOTE: co-occurrence is document-level (all entities in a paper). "
          f"Sentence-level window requires NER pipeline changes (future work).")

    # ── Add KB-curated relationships from biological_kb.py ──
    kb_rel_count = 0
    if _kb is not None:
        print("  Adding KB-curated relationships from biological_kb.py...")
        from ..utils import norm as _norm

        # Build norm -> entity_id lookup
        norm_to_eid = {}
        for e in corpus["entities"]:
            if e["norm"] not in entity_id_map:
                continue
            norm_to_eid[e["norm"]] = entity_id_map[e["norm"]]

        def _resolve(term_str):
            """Resolve a KB term to (entity_id, norm) — try direct + canonical + synonyms."""
            n = _norm(term_str)
            if n in norm_to_eid:
                return norm_to_eid[n], n
            # Try KB canonicalization
            if _kb:
                info = _kb.lookup(term_str)
                if info:
                    canon = info.get("canonical", term_str)
                    n2 = _norm(canon)
                    if n2 in norm_to_eid:
                        return norm_to_eid[n2], n2
                    # Try synonyms
                    for syn in info.get("info", {}).get("synonyms", []):
                        n3 = _norm(syn)
                        if n3 in norm_to_eid:
                            return norm_to_eid[n3], n3
            return None, n

        kb_edges = set()  # (source_id, target_id, rel_type) dedup

        def _add_kb_edge(src_term, tgt_term, rel_type, mechanism=""):
            nonlocal kb_rel_count
            src_eid, _ = _resolve(src_term)
            tgt_eid, _ = _resolve(tgt_term)
            if src_eid is None or tgt_eid is None:
                return
            edge_key = (src_eid, tgt_eid, rel_type)
            if edge_key in kb_edges:
                return
            kb_edges.add(edge_key)

            # Upsert: if co-occurrence edge already exists, upgrade it
            c.execute("""SELECT id FROM relationships
                WHERE source_id=? AND target_id=? AND relationship_type=?""",
                (src_eid, tgt_eid, rel_type))
            row = c.fetchone()
            if row:
                c.execute("""UPDATE relationships
                    SET source_db='co-occurrence+kb', confidence=0.9,
                        validation_status='kb_curated', source_type='kb',
                        mechanism=?, evidence_type='literature_co_occurrence+biological_kb'
                    WHERE id=?""", (mechanism or rel_type, row[0]))
            else:
                c.execute("""INSERT INTO relationships
                    (source_id, target_id, relationship_type, source_db,
                     confidence, evidence, evidence_type, validation_status,
                     source_type, mechanism)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (src_eid, tgt_eid, rel_type, "biological_kb",
                     0.9, "Curated from established microbiome literature",
                     "biological_kb", "kb_curated", "kb", mechanism or rel_type))
                kb_rel_count += 1

        # 1. Organism produces chemical
        for org_name, info in _kb.ORGANISMS.items():
            for chem in info.get("produces", []):
                _add_kb_edge(org_name, chem, "PRODUCES", mechanism="produces")

        # 2. Organism depleted/enriched in disease
        for org_name, info in _kb.ORGANISMS.items():
            for disease in info.get("depleted_in", []):
                _add_kb_edge(org_name, disease, "ASSOCIATED_WITH", mechanism="depleted_in")
            for disease in info.get("enriched_in", []):
                _add_kb_edge(org_name, disease, "ASSOCIATED_WITH", mechanism="enriched_in")

        # 3. Drug treats disease
        for drug_name, info in _kb.DRUGS.items():
            for disease in info.get("treats", []):
                _add_kb_edge(drug_name, disease, "TREATS", mechanism="treats")

        # 4. Drug disrupts organism/microbiome
        for drug_name, info in _kb.DRUGS.items():
            for target in info.get("disrupts", []):
                _add_kb_edge(drug_name, target, "DISRUPTS", mechanism="disrupts")

        # 5. SCFA treats inflammation (from SCFA_TREATS_INFLAMMATION)
        for chem, diseases in _kb.SCFA_TREATS_INFLAMMATION.items():
            for disease in diseases:
                _add_kb_edge(chem, disease, "TREATS", mechanism="scfa_anti_inflammatory")

        # 6. Antibiotic disrupts organism (from ANTIBIOTIC_DISRUPTS)
        for drug, organisms in _kb.ANTIBIOTIC_DISRUPTS.items():
            for org in organisms:
                _add_kb_edge(drug, org, "DISRUPTS", mechanism="antibiotic_disruption")

        # 7. Known associations — depleted/enriched organisms + treatments
        for cat_name, cat_info in _kb.KNOWN_ASSOCIATIONS.items():
            for org in cat_info.get("depleted_organisms", []):
                for disease in _kb.CATEGORY_TO_DISEASE.get(cat_name, []):
                    _add_kb_edge(org, disease, "ASSOCIATED_WITH", mechanism="depleted_in")
            for org in cat_info.get("enriched_organisms", []):
                for disease in _kb.CATEGORY_TO_DISEASE.get(cat_name, []):
                    _add_kb_edge(org, disease, "ASSOCIATED_WITH", mechanism="enriched_in")
            # Treatments
            for drug in cat_info.get("treatments", []):
                for disease in _kb.CATEGORY_TO_DISEASE.get(cat_name, []):
                    _add_kb_edge(drug, disease, "TREATS", mechanism="treats")
            # Metabolite-to-disease
            for met, disease in cat_info.get("metabolite_to_disease", []):
                _add_kb_edge(met, disease, "ASSOCIATED_WITH", mechanism="metabolite_disease")
            # Producer-to-product (already handled by organism produces chemical)
            for prod, chem in cat_info.get("producer_to_product", []):
                _add_kb_edge(prod, chem, "PRODUCES", mechanism="produces")
            # Probiotic to condition
            for prob, condition in cat_info.get("probiotic_to_condition", []):
                _add_kb_edge(prob, condition, "TREATS", mechanism="probiotic_benefit")
            # Organism-to-disease (neuropsych gut-brain)
            for org, disease in cat_info.get("organism_to_disease", []):
                _add_kb_edge(org, disease, "ASSOCIATED_WITH", mechanism="gut_brain")

        print(f"  KB-curated relationships: {kb_rel_count} new (plus upgrades to existing edges)")

    # ── Populate run_metadata ──
    import time as _time
    from datetime import datetime as _dt
    metadata = {
        "version": "2.1.0",
        "build_timestamp": _dt.utcnow().isoformat(),
        "total_papers": str(total_papers),
        "total_entities": str(len(entity_id_map)),
        "m_hypotheses": str(m_hypotheses),
        "min_cooccurrence": str(MIN_COOCCURRENCE),
        "fdr_threshold": "0.05",
        "idf_hard_exclusion_pct": "0.80",
        "idf_soft_band_pct": "0.50",
        "ner_models": "GLiNER,PubMedBERT,PubTator3,sciSpaCy,Qwen",
        "mapping_services": "OLS,UMLS,BioPortal,NCBITaxon,OMOP",
        "vocab_priority_enforced": "true",
        "co_occurrence_level": "document",
        "seed": "0",
    }
    for k, v in metadata.items():
        c.execute("INSERT OR REPLACE INTO run_metadata (key, value) VALUES (?, ?)", (k, v))
    # Store full VOCAB_PRIORITY as JSON
    from ..config import VOCAB_PRIORITY as _VP
    c.execute("INSERT OR REPLACE INTO run_metadata (key, value) VALUES (?, ?)",
              ("vocab_priority_json", json.dumps({k: v for k, v in _VP.items()})))

    conn.commit()

    # ── Create views ──
    c.executescript("""
    DROP VIEW IF EXISTS v_entity_relationships;
    CREATE VIEW v_entity_relationships AS
    SELECT r.id as relationship_id, e1.term as source_term, e1.entity_type as source_type_entity,
           e2.term as target_term, e2.entity_type as target_type_entity,
           r.relationship_type, r.source_db, r.confidence, r.evidence,
           r.evidence_type, r.validation_status, r.source_type,
           r.npm_i, r.p_value, r.q_value, r.co_occurrence_count,
           (SELECT GROUP_CONCAT(paper_id, ';') FROM edge_evidence
            WHERE relationship_id = r.id) as source_docs
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
                   "entity_project_mentions", "controlled_vocabularies",
                   "edge_evidence", "run_metadata"]:
        c.execute(f"SELECT COUNT(*) FROM {table}")
        print(f"    {table}: {c.fetchone()[0]} rows")

    conn.close()
    print(f"  Database saved to {db_path}")
    print(f"  DB size: {db_path.stat().st_size / 1024 / 1024:.1f} MB")

    return db_path
