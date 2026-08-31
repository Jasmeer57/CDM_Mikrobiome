// Case study 1: organisms associated with IBD
MATCH (o:ORGANISM)-[r:associated_with|co_occurs_with]->(d:DISEASE)
WHERE toLower(d.term) CONTAINS 'ibd' OR toLower(d.term) CONTAINS 'inflammatory bowel'
RETURN o.term, type(r), d.term, r.confidence
ORDER BY r.confidence DESC LIMIT 20;

// Case study 2: butyrate producers
MATCH (o:ORGANISM)-[r:produces|co_occurs_with]->(c:CHEMICAL)
WHERE toLower(c.term) CONTAINS 'butyrate'
RETURN o.term, r.evidence, r.confidence ORDER BY r.confidence DESC LIMIT 20;

// Case study 3: antibiotics that disrupt microbiome
MATCH (c:CHEMICAL)-[r:co_occurs_with|treated_by]->(d:DISEASE)
WHERE c.term IN ['vancomycin', 'ciprofloxacin', 'metronidazole', 'rifaximin']
RETURN c.term, type(r), d.term, r.confidence LIMIT 20;

// Case study 4: taxonomic lineage (simplified; requires NCBI taxonomy)
MATCH (e:ORGANISM {term:'Faecalibacterium prausnitzii'})-[r]-(ne:ENTITY)
WHERE ne.type IN ['ORGANISM', 'GENOMICS']
RETURN e.term, ne.term LIMIT 20;

// Case study 5: treatments for Crohn's disease
MATCH (c:CHEMICAL)-[r:treats|co_occurs_with]->(d:DISEASE)
WHERE toLower(d.term) CONTAINS 'crohn'
RETURN c.term, type(r), d.term, r.confidence
ORDER BY r.confidence DESC LIMIT 20;
