# Knowledge-triple validation report

**Population:** all 25,788 relation triples in CDM 3.0.3, with their 34,416 source mentions (`relation_evidence`).

**References:** NCBI Taxonomy, NCBI Gene, CTD/MeSH, Mondo and HPO for entities; CTD curated associations and Disbiome for pairs.

**Rule:** absence from a knowledge graph is reported as **UNSUPPORTED_BY_KG**, never as incorrect. Knowledge-graph support is not precision.

## Structure and evidence

| Check | Result |
|---|---|
| Triples | 25,788 |
| Generic catch-all relation (`OTHER_RELATION`, family `escape`) | 17,717 (68.7%) |
| Specific relation families | 8,071; largest: presence/abundance 2,210, study evidence 1,872, quantitative 962, disease relationship 847, causal/regulatory 686 |
| Polarity conflicting across mentions of the same triple | 195 (0.8%) |
| Duplicates | canonical triples are de-duplicated by construction (`duplicate_group_id`); no duplicate canonical IDs |
| Source sentence located in the section | 25,402 / 27,130 mentions of kept triples (93.6%): exact 4,157, whitespace 19,565, normalised 1,680; unanchored 1,728 |

## Entity grounding

| | In a groundable domain (taxon, disease, gene, drug) | Grounded in a reference |
|---|---:|---:|
| Subjects | 9,324 | 3,076 (33.0%) |
| Objects | 5,826 | 1,582 (27.2%) |

Most triple entities fall in domains with no reference vocabulary: sample/cohort, ecological process, statistic, method and so on.

## Knowledge-graph support

| Pair type | Assessable | Both entities grounded | Supported by KG | Unsupported by KG |
|---|---:|---:|---:|---:|
| microbe–disease (Disbiome; species credited at genus) | 943 | 137 | **50 (36.5% of grounded)** | 87 |
| chemical/drug–disease (CTD curated) | 264 | 19 | 3 | 16 |
| gene–disease (CTD curated) | 29 | 8 | 0 | 8 |
| chemical/drug–gene (CTD) | 16 | 0 | — | — |
| all other domain pairs | 24,536 | — | unassessed | — |

**Coverage:** only 1,252 triples (4.9%) fall in pair types with a curated reference. Of those, 164 have both entities grounded, and 53 are supported.

## Decision

| Dimension | Decision |
|---|---|
| Structural integrity and sentence evidence | CONDITIONAL PASS (93.6% of sentences anchored) |
| External KG support | CONDITIONAL: 36.5% of grounded microbe–disease triples supported; 95% of triples unassessable by any curated reference |
| Predicate informativeness | FAIL as a quality claim: 68.7% generic relations |
| Scientific accuracy | NOT EVALUATED |
