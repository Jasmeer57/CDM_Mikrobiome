# Microbiome Knowledge Graph - Complete Export

## Overview

Comprehensive knowledge graph built from 8,657 microbiome entities extracted from 351 papers covering 168,000 samples across 481 studies.

## Generated Files

### 1. Neo4j Database Export (`neo4j/`)

| File | Size | Description |
|------|------|-------------|
| `neo4j_nodes.csv` | 7.2 MB | 8,657 entity nodes with full metadata |
| `neo4j_relationships.csv` | 139 KB | 839 relationships with evidence |
| `import.cypher` | 4.3 KB | Cypher script for Neo4j import |
| `neo4j_stats.json` | 816 B | Graph statistics |

**Node Schema:**
- term, entity_type, categories, confidence_score, paper_count, frequency
- definition, contextual_definition, aliases, examples
- UMLS_ID, OMOP, OLS, Bioportal (controlled vocabularies)
- paper_context, files_found_in, paper_location

**Relationship Schema:**
- source, target, relationship_type
- source_db, confidence, evidence, evidence_type
- mechanism, ec_number, kegg_pathway
- pubmed_ids, paper_doi, validation_status

### 2. OWL Ontology (`owl/`)

| File | Size | Description |
|------|------|-------------|
| `microbiome_cdm.owl` | 1.88 MB | OWL 2 DL ontology with all entities and relationships |
| `owl_stats.json` | 185 B | Ontology statistics |

**Ontology Structure:**
- Base IRI: `http://microbiome-cdm.org/ontology/`
- 19 entity classes (ORGANISM, CHEMICAL, DISEASE, etc.)
- 14 object properties (PARENT_OF, PRODUCES, ASSOCIATED_WITH, etc.)
- Entity individuals with full metadata and cross-references
- Relationship assertions with confidence scores and evidence

### 3. Merged Relationships (`knowledge_graph/`)

| File | Size | Description |
|------|------|-------------|
| `relationships_merged.csv` | - | 839 deduplicated relationships |
| `relationships_stats.json` | - | Relationship statistics |

## Statistics

### Entity Distribution
```
DATA_ANALYSIS:     1,096 entities
CHEMICAL:          1,015 entities
ORGANISM:            999 entities
LAB_METHOD:          974 entities
PROTEIN:             794 entities
CONCEPT:             655 entities
DISEASE:             618 entities
GENE:                586 entities
CLINICAL:            473 entities
BIOMARKER:           383 entities
GENOMICS:            277 entities
PATHWAY:             174 entities
PHENOTYPE:           157 entities
SAMPLE_METHOD:       143 entities
ANATOMICAL:          126 entities
CELL_TYPE:            99 entities
DNA_RNA:              81 entities
STUDY_DESIGN:          4 entities
EXPERIMENTAL_METHOD:   3 entities
```

### Relationship Types
```
PARENT_OF:          635 (NCBI Taxonomy hierarchies)
ASSOCIATED_WITH:    143 (UMLS semantic relationships)
PRODUCES:            31 (ChEBI metabolic pathways)
RELATED_TO:          27 (UMLS related concepts)
EXACERBATES:          2 (Disease exacerbation)
PROTECTS_AGAINST:    1 (Protective effects)
```

### Source Databases
```
NCBI Taxonomy:       635 relationships (taxonomic hierarchies)
UMLS (scispaCy):     173 relationships (semantic associations)
ChEBI:                29 relationships (metabolic production)
Literature Curated:    2 relationships (manual curation)
```

### Confidence Scores
```
0.9-1.0:  669 relationships (high confidence)
0.8-0.9:  124 relationships
0.7-0.8:   46 relationships
0.6-0.7:    0 relationships
```

## Usage

### Import to Neo4j

```bash
# Copy CSV files to Neo4j import directory
cp neo4j/neo4j_nodes.csv /var/lib/neo4j/import/
cp neo4j/neo4j_relationships.csv /var/lib/neo4j/import/

# Run Cypher import script in Neo4j Browser
# Or use: cypher-shell -u neo4j -p password -f neo4j/import.cypher
```

### Load OWL in Protege

1. Open Protege
2. File → Open → Select `microbiome_cdm.owl`
3. Navigate ontology classes, individuals, and relationships

### Query Examples

**Cypher: Find metabolites produced by organisms**
```cypher
MATCH (org:Entity)-[r:RELATIONSHIP {relationship_type: 'PRODUCES'}]->(chem:Entity)
WHERE org.entity_type = 'ORGANISM' AND chem.entity_type = 'CHEMICAL'
RETURN org.term, chem.term, r.confidence
ORDER BY r.confidence DESC
LIMIT 20
```

**Cypher: Find disease-associated organisms**
```cypher
MATCH (org:Entity)-[r:RELATIONSHIP {relationship_type: 'ASSOCIATED_WITH'}]->(dis:Entity)
WHERE org.entity_type = 'ORGANISM' AND dis.entity_type = 'DISEASE'
RETURN org.term, dis.term, r.evidence
LIMIT 20
```

**SPARQL: Query OWL ontology**
```sparql
PREFIX microbiome: <http://microbiome-cdm.org/ontology/>

SELECT ?org ?chem ?confidence
WHERE {
  ?org a microbiome:ORGANISM .
  ?org microbiome:PRODUCES ?chem .
  ?org microbiome:confidence ?confidence .
}
LIMIT 20
```

## Data Sources

1. **Entity Extraction**: 351 papers, 168,000 samples, 481 studies
2. **Controlled Vocabularies**:
   - UMLS (Unified Medical Language System)
   - OMOP (Observational Health Data Sciences and Informatics)
   - OLS (Ontology Lookup Service)
   - BioPortal
3. **Relationships**:
   - NCBI Taxonomy (taxonomic hierarchies)
   - ChEBI (metabolic pathways, enzymatic reactions)
   - UMLS (semantic relationships, disease associations)
   - Literature curation (manual validation)

## Common Data Model Schema

All entities follow a standardized schema:
- **Identity**: Unique term, entity type, categories
- **Evidence**: Confidence score, paper count, frequency
- **Documentation**: Definition, contextual definition, aliases, examples
- **Provenance**: Files found in, paper locations, paper context
- **Mappings**: UMLS_ID, OMOP, OLS, Bioportal cross-references

All relationships include:
- **Participants**: Source entity, target entity, relationship type
- **Evidence**: Source database, confidence score, evidence type
- **Mechanism**: EC number, KEGG pathway, mechanistic description
- **Validation**: PubMed IDs, paper DOIs, validation status

## Version

- Version: 1.0.0
- Generated: 2026-03-01
- License: Please cite if used in publications

## Citation

If you use this knowledge graph, please cite:
- Original microbiome studies (351 papers)
- UMLS: https://www.nlm.nih.gov/research/umls/
- NCBI Taxonomy: https://www.ncbi.nlm.nih.gov/taxonomy
- ChEBI: https://www.ebi.ac.uk/chebi/
