# CDM Pipeline - Advanced Microbiome Entity Extraction & Knowledge Graph

**🧬 The most comprehensive Common Data Model (CDM) pipeline for microbiome entity extraction with 5-layer deduplication and high-fidelity Knowledge Graph construction.**

A microbiome terminology standard aligned with OMOP CDM and standard ontologies (OLS, BioPortal, UMLS), containing 8,706 curated entity definitions extracted from 351 published microbiome studies.

## 📁 Output Directories

### Output_final/ - Knowledge Graph Export (Primary Output)

The final knowledge graph exports ready for use in various formats:

| Directory/File | Size | Description |
|----------------|------|-------------|
| `entities/` | 85 MB | Extracted entity files (JSON) with full metadata |
| `final_release/` | 84 MB | Complete release files (CSV, JSON) for distribution |
| `databases_ontology/` | 69 MB | SQLite database and OWL ontology files |
| `neo4j/` | 7.4 MB | Neo4j CSV imports and Cypher scripts |
| `relationships_sources/` | 3.0 MB | Source relationship data (UMLS, ChEBI, NCBI) |
| `validation_reports_stats/` | 244 KB | Validation reports and statistics |
| `scripts/` | 113 KB | Knowledge graph evaluation scripts |
| `relationships_extracted/` | 28 KB | Extracted relationships with evidence |
| `samples_testing/` | 19 KB | Sample data for testing |

**Key Files:**
- `README.md` - Comprehensive documentation for the knowledge graph
- `CRITICAL_ASSESSMENT.md` - Critical evaluation of the pipeline
- `FIX_CHECKLIST.md` - Quality assurance checklist
- `TERM_QUALITY_ASSESSMENT.md` - Entity quality assessment
- `PUBLICATION_STRATEGY.md` - Publication and citation strategy

### outputs/ - Intermediate Processing Outputs

| Directory | Size | Description |
|-----------|------|-------------|
| `stage1_extracted_full/` | 57 MB | Raw extracted entities from papers |
| `enhanced/` | 53 MB | Enhanced/deduplicated entities |
| `normalized/` | 35 MB | Normalized entity data |
| `relationships/` | 180 KB | Extracted relationships |
| `taxonomy/` | 496 KB | NCBI taxonomy mappings |
| `study_metadata/` | 3.0 KB | Study metadata |
| `validation/` | 2.5 KB | Validation results |

## 🚀 **New in This Version**

### 🧠 **High-Fidelity Knowledge Graph** (NEW!)
- **9,126 Entities** successfully extracted and grounded to standard ontologies.
- **839 Relationships** with mechanistic evidence (KEGG, EC Numbers, ChEBI).

## 🗄️ Database Schema (OMOP-style CDM)

The SQLite database (`microbiome_cdm.db`) contains the following CDM-style tables:

| Table | Records | Description |
|-------|---------|-------------|
| `entities` | 8,706 | Curated entities with ontology mappings |
| `extracted_entities` | 34,621 | Raw extracted entities from 350 projects |
| `sample_demographics` | 157,262 | Demographics linked to samples |
| `measurement_facts` | 94,129 | Clinical measurements (BMI, CD4, CRP, etc.) |
| `samples` | 168,464 | All microbiome samples |
| `projects` | 482 | Project/study metadata |
| `relationships` | 261 | Extracted relationships with evidence |

### Demographic Coverage:

| Field | Samples |
|-------|---------|
| Sex | 24,997 |
| Age | 42,555 |
| BMI | 9,647 |
| Collection date | 145,112 |
| Location (geo_loc_name) | 155,584 |
| Disease/condition | 6,211 |

### Entity Types in Database:

| Type | Count |
|------|-------|
| ORGANISM | 9,119 |
| DATA_ANALYSIS | 6,150 |
| CHEMICAL | 4,708 |
| DISEASE | 2,333 |
| CLINICAL | 2,218 |
| GENE | 1,243 |
| PROTEIN | 873 |

### Database Location:
`llm_terms/Output_final/databases_ontology/microbiome_cdm.db`