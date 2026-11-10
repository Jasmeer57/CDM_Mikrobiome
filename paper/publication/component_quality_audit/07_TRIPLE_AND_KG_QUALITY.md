# Component G — Triple and Knowledge-Graph Quality

**Audited object:** all **25,788** canonical triples in CDM 3.0.3 (`relation`), their **6,925** dropped
counterparts (`removed_relation`), **34,416** evidence rows (`relation_evidence`), the **204,817**
`concept` rows they could have been linked to, and the derived graph in
`outputs/results/kg_2026-11-04/`.
**Evidence base:** `diagnostics/results/d08_triple_semantics.json`,
`d07_ontology_currency.json`, `d05_evidence_correspondence.json`,
`d02_referential_integrity.json`, `d04_duplication.json`, `d20_evidence_tiers.json`; the KG run's
`kg_stats.json`, `gold_kg_check/summary.json`, `evidence_check/summary.json`; and a purpose-built
probe `cqa_triple_graph.json` (label grounding, self-loops, component structure, cleaned-vs-original
graph comparison).
**Independence:** row counts, the relation vocabulary, the 184 self-loops, the
`subject_ontology_id='unresolved'` census, the 76.16% label-traceability miss and the graph
statistics were all recomputed directly from the frozen DB and the shipped edge list. The Tier 2/3
support rates were **re-derived from the per-item verdict files**, not copied from the summary.

> **Measurement discipline.** No human rated a single triple. `human_review_status`,
> `verification_status` and `review_status` are `pending` on **100%** of 25,788 rows. The two
> model judges (`verdict_deepseek`, `verdict_gemma_c4`) are reported in §4.3 as *model behaviour*,
> never as validation. Absence of a triple from BugSigDB/CTD/Disbiome is reported as
> **untested, not incorrect** — that is the reference authors' own stated reading and this audit
> adopts it.

---

## 1. Dimensional assessment

| Dimension | Rating | Supporting evidence | Measurable indicator | Limitation | Confidence |
|---|---|---|---|---|---|
| Structural integrity | **ADEQUATE** | 25,788 rows; `canonical_triple_id` unique; **0 duplicate canonical `(subject,relation,object)` groups**; `triple_mention_ids` non-empty on 100%; every triple has ≥1 `relation_evidence` row (0 orphans); `mention_count` sums to 27,130 over 25,788 rows | canonical-duplicate rate **0.00%**; evidence coverage **100%** (34,416 rows, mean 1.05, max 13) | Structure is consistent but carries no declared keys: `relation` has no scalar `paper_id` (only `paper_ids`/`paper_count`), and 514 paper tokens live in a JSON list joined by no foreign key | High |
| Ontology grounding | **CRITICAL** | `subject_ontology_id` and `object_ontology_id` are the literal string `unresolved` on **25,788 / 25,788** (distinct value count **1**); `subject_entity_resolution_status` / `object_entity_resolution_status` are `unresolved_string_match_v1` on 100%; `external_linking_status` is `pending_stage57` on 100%; in `concept`, `ontology_name` is NULL on **185,822 / 204,817 = 90.7%** | Triples with any ontology identifier **0 / 25,788 = 0.00%** | The KG run reports "edges with ontology IDs on both ends 7,379" — that is computed from `concept` joins, and it is **not** supported by the `relation` table's own columns. The two are different claims and must not be swapped | High |
| Semantic typing | **CRITICAL** | **17,717 / 25,788 = 68.70%** of triples carry `relation_normalized='OTHER_RELATION'` in the `escape` family; the whole vocabulary is 76 relations in 17 families; the typed remainder's largest relation is `MEASURED_BY` 1,316 | escape-bucket share **68.70%**; typed tail `PRESENT_IN` 1,035, `ASSOCIATED_WITH` 771 | `relation_id`↔`relation_normalized` is 1:1 (76/76), so the vocabulary itself is clean — the problem is that two thirds of triples did not fit it | High |
| Evidence support | **WEAK** | `relation_evidence.anchor_status`: `WHITESPACE` 24,702 (71.78%) / `EXACT` 5,375 (15.62%) / `NORMALISED` 2,115 (6.15%) / `UNANCHORED` 2,224 (6.46%). D05 recomputation: NORMALISED 24,713 / EXACT 5,375 / FUZZY 2,075 / **UNABLE_TO_VERIFY 2,253 (6.55%)**. Canonical labels appear **literally** in the stored sentence for both ends on **899 / 34,416 = 2.61%**; **26,211 = 76.16%** contain neither label | strict verbatim (EXACT+NORMALISED) **29,088 / 34,416 = 84.52%**; label-traceable **2.61% both / 23.84% one end / 76.16% neither** | Label mismatch is expected under canonicalisation (a sentence says "the microbiota", the label is "gut microbiota"), so the 76% figure measures **traceability**, not sentence truth. It is nonetheless the number a reader needs in order to follow a triple back to text | High |
| Internal consistency | **WEAK** | 195 rows carry conflicting `polarity_variants`, 87 conflicting `assertion_status_variants`, **247** rows `conflict_flag='conflicting_across_mentions'`; **184 self-loops** (0.714%), of which 121 are `OTHER_RELATION`; `evidence_verified_count=0` on **1,619** rows (6.28%) while `evidence_unresolved_count>0` on 1,673 | conflicting-mention rate **0.96%**; self-loop rate **0.71%**; verified-zero rate **6.28%** | The multi-valued variant columns are a *feature* (a triple aggregates mentions across papers); the defect is that conflicts are stored as JSON arrays and never resolved into a decision | High |
| Duplication | **ADEQUATE** | `duplicate_validation_status`: `unique_mention` 24,806 / `within_paper_duplicate` 738 / `cross_paper_duplicate` 244; **0 duplicate canonical triple groups**; `removed_relation` 6,925 rows with 6,925 distinct `duplicate_group_id` and 6,925 distinct `canonical_triple_id`, 0 overlap with `relation` | canonical triple duplication **0.00%**; removed-set group multiplicity **1.00** | A `duplicate_group_id` that is unique per row is an ID, not a group — the 6,925 "groups" are 6,925 singletons, so the removal is not explicable as deduplication by the stored fields | High |
| Coverage | **ADEQUATE** | **451 / 453 papers (99.56%)** contribute ≥1 triple; per-paper max 224 (`HMPAPER_000084`), median 57, min 2; 15 papers ≥100 triples, 423 ≥20, 1 with <5 | paper coverage **99.56%**; top-15 papers hold a disproportionate share | Two corpus papers produce no triples at all and are not separately flagged. 25,544 triples (99.05%) are single-paper; only 243 aggregate ≥2 papers | High |
| External concordance | **WEAK** | BugSigDB (Tier 2): 518 items over 47 papers, support **261/518 = 50.39%** vs chance 16.1%. CTD: **11/49 = 22.45%** vs chance 24.25% (indistinguishable). Gene–disease: 7 items, **0** in reference. Disbiome: not present. Curated-KG check (Tier 3): microbe–disease **82/622 = 13.18%** vs 5.78% chance; chemical–disease **23/202 = 11.39%** vs 9.79%; gene–disease 0/16; chemical–gene 2/7 | best supported edge type **13.18% vs 5.78% chance (2.3×)**; CTD **at chance** | Absence from a curated KG is **not** evidence of error — these references cover a fraction of microbiome literature and none covers `OTHER_RELATION`. The comparison also selects only triples whose ends *resolved*, which is 622 of 25,788 | High |
| Reproducibility | **ADEQUATE** | `canonicalization_stage` = `stage56_triples_canonicalize@2.1.0` on 100%; `graph_id` `HMCV2`, `graph_version` `2.1.0` on 100%; `canonicalization_method` = `string_normalization_v1_exact` on 100%; Tier-3 evidence check carries `PREREGISTRATION.sha256` and a `code_sha256`; gold check carries a `code_sha256` | single canonicalisation stage, single method, single graph version | The **canonicalisation is not reproducible in the sense of regenerating the same 25,788 triples** — no extraction seed/provenance is recorded beyond `extraction_run_id`, and the staging code is not shipped in the bundle | High |
| Reusability | **WEAK** | A reuser gets no ontology IDs, a 68.7%-generic predicate, no `paper_id` column, three `pending` status columns, and model verdicts stored as if they were validation | usable-as-graph: **yes** structurally; usable-as-typed-knowledge: **no** | The derived KG (`kg_cleaned.graphml`) is a *cleaned* artifact — 9,682 of 25,788 edges survive — and must not be presented as the frozen release | High |

**No averaged score is computed.** Nine independent judgements over different evidence.

---

## 2. Population decomposition

### 2.1 The four sets, and why they differ

| Set | Rows | Relationship to `relation` |
|---|---:|---|
| `relation` (canonical triples) | 25,788 | the audited population |
| `removed_relation` | 6,925 | disjoint: 0 `canonical_triple_id` overlap with `relation` |
| `relation_evidence` | 34,416 | 1.05 rows per triple, min 1, max 13; 0 triples without evidence |
| `concept` | 204,817 | join target for ontology mapping; 18,995 rows come from `omop`, 62,383 `ols`, 61,280 `bioportal`, 54,381 `umls`, 6,613 `mesh`, 1,165 `ncbi_taxon` |

`removed_relation` is **not** a deduplication record: its `duplicate_group_id` is unique on every row
(6,925 distinct / 6,925 rows) and its composition is 6,222 `OTHER_RELATION` + a thin typed tail
(`MEASURED_BY` 131, `HAS_RELATIVE_ABUNDANCE` 103, `PRESENT_IN` 90). It is best read as "triples
dropped during canonicalisation", not "triples that duplicated a kept one".

### 2.2 Relation vocabulary: 76 relations, 17 families, one dominant bucket

| Family | Rows | Share |
|---|---:|---:|
| escape (`OTHER_RELATION`) | 17,717 | **68.70%** |
| presence_abundance | 2,210 | 8.57% |
| study_evidence | 1,872 | 7.26% |
| quantitative | 962 | 3.73% |
| disease_relationship | 847 | 3.28% |
| causal_regulatory | 686 | 2.66% |
| biological_function | 360 | 1.40% |
| treatment_intervention | 300 | 1.16% |
| taxonomy_identity | 210 | 0.81% |
| microbe_interaction | 153 | 0.59% |
| location_habitat | 119 | 0.46% |
| host_association | 116 | 0.45% |
| temporal | 80 / transmission_origin 64 / molecular_mechanism 34 / host_response 31 / ontology_structure 27 | <0.35% each |

Top individual relations: `OTHER_RELATION` 17,717; `MEASURED_BY` 1,316; `PRESENT_IN` 1,035;
`ASSOCIATED_WITH` 771; `HAS_RELATIVE_ABUNDANCE` 683; `DECREASED_IN` 531; `CAUSES` 492;
`COMPARED_WITH` 471; `INCREASED_IN` 401; `PRODUCES` 340; `TREATS` 276.

The typed tail is scientifically sensible for this domain (abundance, presence, causation,
treatment) and its internal logic is consistent: `relation_is_causal=1` exactly on
`causal_regulatory` 686, `biological_function` 359, `treatment_intervention` 296,
`microbe_interaction` 97 and 76 `disease_relationship` rows; `relation_is_symmetric=1` on all 771
`disease_relationship` rows and 471 `COMPARED_WITH` rows, 0 elsewhere except 191
`taxonomy_identity`. No family contradicts its flags.

### 2.3 Graph structure (recomputed from the shipped edge list)

| | Full (as released) | Cleaned (DeepSeek) |
|---|---:|---:|
| Nodes | 22,579 | 8,897 |
| Edges | 25,788 | 9,682 |
| Connected components | 3,052 | 1,219 |
| Largest component | 15,470 (68.5%) | 6,029 (67.8%) |
| Isolated nodes | 73 | 2 |
| Mean degree | 2.20 | 2.11 |
| Edges touching an unlinked `LABEL:` node | **5,050 (19.58%)** | 1,157 (11.95%) |
| Nodes orphaned by cleaning | — | **13,682 / 22,579 = 60.6%** |

22,579 nodes for 25,788 edges is a **sparse** graph (mean degree 2.2) dominated by one component:
68.5% of all nodes sit in a single connected blob, which for a literature-derived KG means the
graph is held together by hub terms ("gut microbiota", "microbiome") rather than by coherent
sub-communities. 4,544 nodes (20.1%) are unlinked label placeholders; 19.58% of edges touch one,
i.e. one end of a fifth of the graph is a string that never became a canonical term.

---

## 3. Issues

### CQA-G-01 — No triple carries an ontology identifier
- **Severity:** **CRITICAL**
- **Type:** Confirmed defect (unpopulated column shipped as data)
- **Evidence:** `select distinct subject_ontology_id from relation` → `unresolved` (1 value, 25,788 rows); identical for `object_ontology_id`. `subject_entity_resolution_status` / `object_entity_resolution_status` = `unresolved_string_match_v1` on 25,788 each. `external_linking_status` = `pending_stage57` on 25,788. In `concept`, `ontology_name` is NULL on 185,822 / 204,817 (90.7%); the named remainder is SNOMED 4,909 / MESH 3,551 / NEBRASKA LEXICON 3,069 / LOINC 2,277 / RXNORM 803 / OMOP GENOMIC 687.
- **Affected:** 25,788 / 25,788 triples = **100%**; 100% of triple endpoints.
- **Scientific impact:** Every triple is a pair of English strings, not a pair of ontology terms. "Bifidobacterium" in one paper and "Bifidobacterium spp." in another are separate nodes; nothing guarantees that two nodes with the same label denote the same entity across papers, and nothing prevents a label from denoting a different entity in different papers. All cross-paper aggregation in this component rests on the single `string_normalization_v1_exact` method.
- **Publication impact:** The CDM cannot be described as ontology-grounded, semantically normalised, or interoperable at the triple level. Any sentence of the form "entities were mapped to standard ontologies" is false for `relation`. The defensible sentence is: "canonical terms were mapped to vocabulary candidates in `term_concept_map`; the triples themselves carry no ontology identifiers."
- **Recommended action:** Either populate the columns (stage 57 was evidently never run) or publish them as reserved/unpopulated with `external_linking_status='pending'` renamed to `NOT_ATTEMPTED`. Do not claim ontology grounding in the manuscript.
- **Blocking:** blocks every ontology-grounding and semantic-interoperability claim about the KG.

### CQA-G-02 — 68.7% of triples fall into a single `OTHER_RELATION` escape bucket
- **Severity:** **CRITICAL**
- **Type:** Confirmed property (vocabulary failure)
- **Evidence:** 17,717 / 25,788 = **68.70%** carry `relation_normalized='OTHER_RELATION'` in family `escape`. Of these, 15,665 are `flagged_needs_review` and only 2,052 `automated_checks_passed`. In the cleaned layer the same rows are relabelled into 2,146 distinct typed relations (`ASSOCIATED_WITH` 1,747, `CONTRIBUTES_TO` 465, `MODULATES` 316, `DECREASED_IN` 276, `FOUND_IN` 251, `INCREASED_IN` 249, …) — i.e. specificity is *recoverable*, not absent from the text.
- **Affected:** 17,717 triples; 15,665 of them flagged.
- **Scientific impact:** Two thirds of the graph asserts only "these two things are related". That is not a knowledge graph in the usual sense; it is a co-occurrence graph with typed edges on the remainder. Any question of the form "does X cause / treat / increase Y" can be answered for at most ~31% of the data, and for the 68.7% the direction, polarity and mechanism are unavailable.
- **Publication impact:** A "25,788-relationship knowledge graph" headline is arithmetically true and semantically misleading. The paper must report the typed subset (8,071 triples) and the generic bucket (17,717) separately; a single total invites the reader to assume the relations carry meaning.
- **Recommended action:** Report the split in the abstract's own number if the abstract quotes a triple total. If the cleaned relabelling is used, publish it as a separate artifact with its error profile (component J) — never merge it into the frozen count.
- **Blocking:** blocks presenting the graph as a typed relationship resource.

### CQA-G-03 — The canonical labels cannot be traced back into their own evidence sentence for 76% of rows
- **Severity:** **HIGH**
- **Type:** Confirmed property (traceability)
- **Evidence:** `cqa_triple_graph.json`: of 34,416 `relation_evidence` rows, the normalised subject and object labels both appear literally in the stored `source_sentence` for **899 (2.61%)**; subject only 4,282 (12.44%); object only 3,024 (8.79%); **neither 26,211 (76.16%)**. By anchor status the miss rate is uniform — `EXACT` 4,052/5,375 = 75.4% neither, `WHITESPACE` 18,807/24,702 = 76.1%, `NORMALISED` 1,644/2,115 = 77.7%, `UNANCHORED` 1,708/2,224 = 76.8% — so this is not a bad-anchor artefact.
- **Affected:** 26,211 / 34,416 = **76.16%** of evidence rows; all 25,788 triples have at least one.
- **Scientific impact:** A reader who clicks "show evidence" for a triple sees a sentence in which neither endpoint is written. The path from sentence → mention → canonical term → triple is not reversible from the shipped columns: `term_mention` is keyed by span, `relation_evidence` is keyed by sentence, and the only bridge is `triple_mention_ids`, which stores mention ids without the span they came from. This is a **provenance-chain break**, not a truth claim.
- **Publication impact:** "Each relationship is supported by a source sentence" is true in the sense that a sentence is stored; it is false in the sense that the sentence demonstrably states the relationship between the named entities. The manuscript must not claim sentence-level support without a worked example that survives this test.
- **Recommended action:** Ship `subject_mention_span` / `object_mention_span` per evidence row (or the mention ids joined to `term_mention`), so a reader can see which words became which label. Report the 2.61%/23.84%/76.16% split if sentence-level support is claimed.
- **Blocking:** blocks a sentence-level-support claim.

### CQA-G-04 — 1,619 triples have no verified evidence at all
- **Severity:** **HIGH**
- **Type:** Confirmed defect (evidence coverage)
- **Evidence:** `evidence_verified_count = 0` on **1,619 / 25,788 = 6.28%**; `evidence_unresolved_count > 0` on 1,673; `evidence_locator_statuses` shows `["unresolved_not_in_source"]` on exactly 1,619 (plus 47 mixed). At the row level, 2,224 `relation_evidence` rows are `UNANCHORED` and D05 independently finds **2,253 UNABLE_TO_VERIFY (6.55%)** — a 29-row difference, which is the fuzzy-match residual.
- **Affected:** 1,619 triples (6.28%); 2,253 evidence rows (6.55%).
- **Scientific impact:** For these triples the stored sentence does not appear in the section it is attributed to. Either the section is wrong, the text was lost upstream (the corpus has 6,027 control-byte corruptions across 122 papers), or the sentence was paraphrased by the extractor. This audit cannot distinguish those; what it can say is that 6.3% of the graph has **no locatable textual basis**.
- **Publication impact:** Any claim of "every relationship traceable to text" fails on 1,619 triples. They should be excluded from or flagged in any evidence-quality statement.
- **Recommended action:** Publish `evidence_verified_count=0` as an exclusion flag and report the count. Do not silently drop them (that would change the frozen population).
- **Blocking:** blocks a 100%-traceable claim; does not block the graph as a whole.

### CQA-G-05 — The only adequacy measurement available rates 22% of triples "supported"
- **Severity:** **HIGH**
- **Type:** Confirmed property (model-assessed, pre-registered)
- **Evidence:** `outputs/results/kg_2026-11-04/evidence_check/summary.json` (16,142 items, 16,132 judged, `PREREGISTRATION.sha256` present): `R_stated` **13,971 = 86.6%** (Wilson 0.8607–0.8712) — the sentence states the relation; `A_supported` **3,549 = 22.0%**; `A_supported_or_partial` **12,932 = 80.16%**; `A_reversed` **236 = 1.46%**. `D_codes`: F 12,722 / H 2,466 / G 944. Relabelled rows: `A_supported` 653/3,793 = 17.22% vs `B_supported` 1,911/3,793 = 50.38% (B better on 1,302, A better on 44). Kept triples 5,795/1,776 = 0.3065 supported vs dropped 10,337/1,773 = 0.1715.
- **Affected:** 16,132 judged items (62.6% of the graph); the 22% figure is the strict adequacy rate.
- **Scientific impact:** The gap between **86.6% "the sentence states this relation"** and **22.0% "this triple is fully supported"** is the single most informative number in this component. It says the text usually does assert *a* relationship of that shape, but the specific canonicalised pair/relation triple is fully supported about one time in five. Partial support at 80% suggests the failure is mostly in endpoint specificity (the generic label or the wrong granularity), which is consistent with CQA-G-03.
- **Publication impact:** A "22% of relationships fully supported" number is a serious disclosure requirement if any validation section is written. It is a **model judgment against a pre-registered rubric**, not human annotation, and must be labelled as such.
- **Recommended action:** Report `R_stated` and `A_supported` side by side with their definitions, and the reversed count. Never collapse them into one "accuracy".
- **Blocking:** blocks a "validated relationships" claim.

### CQA-G-06 — Curated-KG support is real but modest, and is a coverage statement
- **Severity:** **MODERATE**
- **Type:** External concordance (Tier 3)
- **Evidence:** `gold_kg_check/summary.json` — microbe–disease: 622 resolved edges, **82 in a reference = 13.18%** vs **chance 5.78%** (Wilson 0.1075–0.1607); kept 72/466 = 15.45%, dropped 10/156 = 6.41% (kept−dropped +3.2 to +13.6 pts); evidence-supported 10/91 = 10.99% vs evidence-not-supported 40/276 = 14.49% (**difference straddles 0**: −10.3 to +5.4). chemical–disease: 23/202 = 11.39% vs 9.79% chance, kept 19/145 = 13.1%. gene–disease 0/16. chemical–gene 2/7. Reference mix: Disbiome 59, BugSigDB 60, CTD-any 23, CTD-curated 8. Resolution methods: `name_match+name_only` 289, `name_match+cdm_mapping` 205, `cdm_mapping+name_only` 71, `cdm_mapping+cdm_mapping` 57 — **most KG links rest on name matching**.
- **Affected:** 847 resolved edges of 25,788 (3.3%); the support rate applies only to them.
- **Scientific impact:** 13.2% vs 5.8% chance is a **2.3× enrichment** and is the strongest external evidence anywhere in this component. It is nonetheless compatible with the graph being right about a small, well-studied core and silent about everything else. The evidence-supported vs evidence-not-supported difference crossing zero means the KG check does **not** confirm that the stored sentences support the edges.
- **Publication impact:** "Relationships were corroborated against curated knowledge graphs" is supportable only with the 13.2%/5.8% pair, the 622-edge denominator, and the explicit statement that absence is untested. The 90.7%-NULL ontology column (CQA-G-01) means most edges were never eligible for this check at all.
- **Recommended action:** Report as a coverage statement with the denominator. Do not describe unsupported edges as incorrect.
- **Blocking:** neither, if scoped.

### CQA-G-07 — 184 self-referential triples
- **Severity:** **MODERATE**
- **Type:** Confirmed defect
- **Evidence:** `subject_normalized_label = object_normalized_label` on **184 rows = 0.714%**: `OTHER_RELATION` 121, `COMPARED_WITH` 8, `DECREASED_IN` 7, `PRESENT_IN` 6, `HAS_RELATIVE_ABUNDANCE` 6, `ASSOCIATED_WITH` 5, `MEASURED_BY` 5, `HAS_TAXONOMIC_RANK` 5. The typed ones (`DECREASED_IN`, `PRESENT_IN`, `HAS_TAXONOMIC_RANK`) are semantically impossible as self-loops.
- **Affected:** 184 triples.
- **Scientific impact:** Small in volume, unambiguous in kind: a thing cannot be present in itself, nor have itself as a taxonomic rank. These arise from canonicalisation collapsing two distinct mentions to the same string (CQA-G-01's root cause), and they will corrupt any traversal or centrality computation.
- **Publication impact:** Minor; disclose and exclude from graph metrics.
- **Recommended action:** Exclude self-loops from published graph metrics and list them as a known artifact. Do not delete in the frozen DB.
- **Blocking:** neither.

### CQA-G-08 — 247 triples carry unresolved cross-mention conflicts, stored as JSON and never adjudicated
- **Severity:** **MODERATE**
- **Type:** Confirmed inconsistency
- **Evidence:** `conflict_flag='conflicting_across_mentions'` on **247** rows; `unresolved_issues` = `["conflicting_polarity_across_mentions"]` 160, `["conflicting_assertion_status_across_mentions"]` 52, both 35. Multi-valued variants: `polarity_variants` conflicting on 195, `assertion_status_variants` conflicting on 87. Example: `["ASSERTED","NEGATED"]` 22 rows, `["NEGATIVE","POSITIVE"]` 140 rows.
- **Affected:** 247 / 25,788 = 0.96%.
- **Scientific impact:** The triple layer aggregates mentions across papers, so the *same* triple can be asserted in one paper and negated in another. Storing both values in an array is honest; leaving it there means a consumer who reads `polarity_variants` as a string ('["POSITIVE"]') will mis-handle the multi-valued rows, and a consumer who ignores it will treat a negated finding as positive.
- **Publication impact:** Any claim-level use of polarity must handle these 247 rows. Aggregate direction statistics (`effect_direction_variants` is multi-valued on 0 rows, so direction is safe) are unaffected.
- **Recommended action:** Document the multi-valued columns as arrays and publish the 247 conflicted triples as a list.
- **Blocking:** neither, if documented.

### CQA-G-09 — Three status columns are constants, and one of them reads as a completed step
- **Severity:** **MODERATE**
- **Type:** Confirmed defect (placeholder fields)
- **Evidence:** `human_review_status` `pending` 25,788; `verification_status` `pending` 25,788; `review_status` `pending` 25,788; `record_status` `active` 25,788; `external_linking_status` `pending_stage57` 25,788. `canonicalization_method` is a single value on all rows.
- **Affected:** all 25,788 rows, five columns.
- **Scientific impact:** `external_linking_status='pending_stage57'` names a stage that apparently never ran, yet the column ships. `verification_status='pending'` on 100% of rows means no triple was ever verified, which is the honest reading — but a consumer filtering `verification_status='verified'` gets zero rows and may conclude the filter is broken rather than the data unverified.
- **Publication impact:** The data dictionary must document these as constants; they must not appear in a "quality" column list.
- **Recommended action:** Document fixed values or drop from the dictionary. Do not describe `review_status` as a review outcome.
- **Blocking:** neither.

### CQA-G-10 — The `removed_relation` set is not explicable from its own stored fields
- **Severity:** **LOW**
- **Type:** Documentation/provenance gap
- **Evidence:** 6,925 rows, `canonical_triple_id` unique, `duplicate_group_id` unique (**6,925 distinct groups for 6,925 rows**), 0 overlap with `relation`, `canonicalization_method` a single value. Composition: 6,222 `OTHER_RELATION` + 703 typed. Sum of dropped `mention_count` = 7,286 and `paper_count` = 7,005 against 25,788 retained triples.
- **Affected:** 6,925 dropped triples (21.2% of the 32,713 pre-removal population).
- **Scientific impact:** The removal rate is large enough (21%) that a reader needs to know why. The stored fields say "each dropped triple is its own duplicate group", which is internally contradictory — a duplicate group of one is not a duplicate. The most likely reading is that these were removed as non-well-formed or as subsumed by a different canonical form, but the DB does not say so.
- **Publication impact:** "6,925 duplicate relationships were removed" is **not** supported. The defensible sentence is "6,925 candidate triples were removed during canonicalisation; the stored group identifiers are unique per row and do not document the criterion."
- **Recommended action:** Document the removal criterion, or publish the removed set separately with its reason. Do not describe it as deduplication.
- **Blocking:** neither, if described correctly.

### CQA-G-11 — The `concept` table is 90.7% unnamed and does not support the triple layer
- **Severity:** **HIGH**
- **Type:** Confirmed defect (mapping incompleteness)
- **Evidence:** 204,817 rows; `ontology_name` NULL on **185,822 (90.7%)**; `source_service` ols 62,383 / bioportal 61,280 / umls 54,381 / omop 18,995 / mesh 6,613 / ncbi_taxon 1,165. 11,477 `term_concept_map` rows point at a `concept_id` that does not exist — exactly the `NO_MATCH_FOUND` count, i.e. a by-design placeholder, not a broken reference.
- **Affected:** 185,822 concept rows; 25,788 triples (none of which use them).
- **Scientific impact:** A concept row without an ontology name cannot be dereferenced. 90.7% of them are therefore unverifiable identifiers, and the 7,379 "edges with ontology IDs on both ends" reported by the KG run reflects the 9.3% with a name, not a graph-wide property.
- **Publication impact:** "204,817 ontology concepts" is a row count, not a linked-vocabulary count. Quote the named subset.
- **Recommended action:** Report named vs unnamed concept counts separately; do not describe unnamed concepts as ontology terms.
- **Blocking:** blocks an ontology-coverage claim.

### CQA-G-12 — Two model verdicts are stored as if they were validation
- **Severity:** **MODERATE**
- **Type:** Confirmed risk (misuse hazard)
- **Evidence:** `verdict_deepseek`: SUPPORTED 20,029 / PARTIAL 4,815 / NOT_SUPPORTED 573 / NULL 220 / UNKNOWN 103 / SUPPRESSED 17 / PARTIALLY_SUPPORTED 11 / NOT_PROVIDED 6 / POSITIVE 5 / NEGATIVE 5 — note the five off-schema `POSITIVE`/`NEGATIVE` values, which prove the column was written from unconstrained model output. `verdict_gemma_c4`: PLAUSIBLE_BUT_WEAK 19,311 / SENSIBLE 5,710 / NONSENSE 683 / UNCERTAIN 84. Cross-tab by family: escape SUPPORTED 13,503 vs typed 6,526; escape PLAUSIBLE_BUT_WEAK 17,711 vs typed SENSIBLE 5,710.
- **Affected:** 25,788 rows in two columns.
- **Scientific impact:** The two judges are not measuring the same thing — DeepSeek yields a three-level support verdict, Gemma a plausibility label with a 74.9% `PLAUSIBLE_BUT_WEAK` mode. Neither is human review; both are stored in the release table beside `review_status='pending'`. Off-schema values (`POSITIVE`, `NEGATIVE`, `NOT_PROVIDED`) show the enumeration was never enforced.
- **Publication impact:** These columns must never be cited as validation. If cited at all, cite as model output with the model name and prompt, and note the 573 NOT_SUPPORTED / 683 NONSENSE as a **disagreement floor**, not an error rate.
- **Recommended action:** Move to a separate judge table in the next release, with a documented enum and a `judge_model` column. In this release, document them as model output.
- **Blocking:** blocks citing any verdict column as ground truth.

### CQA-G-13 — Two corpus papers contribute no triples
- **Severity:** **LOW**
- **Type:** Coverage gap
- **Evidence:** 451 / 453 papers appear in `relation.paper_ids` (JSON-parsed, 0 parse failures, `paper_count` matches list length on 25,788/25,788). Per-paper counts: max 224, median 57, min 2; 15 papers ≥100, 423 ≥20, 1 paper <5.
- **Affected:** 2 papers (0.44%).
- **Scientific impact:** Negligible in volume. Worth noting only because triple coverage is otherwise near-total and a reader may assume 453.
- **Publication impact:** Say "451 of 453 papers" if a coverage figure is quoted.
- **Recommended action:** Name the two papers in a data appendix.
- **Blocking:** neither.

---

## 4. The five measures, kept separate

### 4.1 Literal correspondence — "is the evidence where the triple says?"
`relation_evidence` resolves at **84.52% strict** (EXACT 5,375 + NORMALISED 24,713 of 34,416) and **6.55% UNABLE_TO_VERIFY** (2,253), with 6.03% FUZZY (2,075) in between. The storage-level `anchor_status` agrees to within 29 rows (`UNANCHORED` 2,224). This is a **strong result for the sentence layer** and is better than the catalogue's (component F: 38.22% strict).

### 4.2 Evidence relevance — "does that sentence state this relationship between these entities?"
Two independent instruments, both weak:
- **Label traceability** (deterministic): both endpoints literally present **2.61%**; neither **76.16%**.
- **Pre-registered model rubric** (Tier 3 evidence check): sentence states the relation **86.6%**; triple fully supported **22.0%**; supported or partial **80.16%**; reversed **1.46%**.
The two are not contradictory: 86.6% says the sentence asserts a relation of that type; 22% says the specific canonical pair is fully supported; 2.61% says you can see the pair in the sentence by string match. Three different questions, three different numbers, and **none of them is an accuracy**.

### 4.3 Model-judge verdicts — model behaviour, not annotation
See CQA-G-12. The usable signal: DeepSeek says `NOT_SUPPORTED` on 573 triples and Gemma says `NONSENSE` on 683. These are **floors of disagreement**, not error counts, and the two do not overlap in a way this audit measured. They are a **priority sampling frame** for any human review, not a filter.

### 4.4 Cross-method agreement
- anchor vs `evidence_locator_statuses`: 29-row discrepancy (2,224 vs 2,253) — consistent.
- Tier 3 KG check vs Tier 3 evidence check on the same edges: KG-supported edges are *not* better evidence-supported (10.99% vs 14.49%, CI crossing zero) — the two external signals **do not corroborate each other**.
- Kept-vs-dropped: cleaned-kept triples are better KG-supported (15.45% vs 6.41%) and better evidence-supported (30.65% vs 17.15%) — the cleaning selects real signal, which is a meaningful **cross-method** convergence even though it is model-driven.
- The one measure that is *not* agreement: `verdict_deepseek` vs `verdict_gemma_c4` measures model similarity on differently-defined tasks and is not computed here as a kappa.

### 4.5 Unresolved cases
- **1,619** triples with no verified evidence (CQA-G-04) — cause undetermined.
- **2,253** evidence rows `UNABLE_TO_VERIFY` (6.55%) — section mismatch vs upstream text loss vs paraphrase, not distinguished.
- **26,211** evidence rows where neither label appears — synonym/canonicalisation vs wrong endpoint, not distinguished.
- **247** conflicted triples — no adjudication (CQA-G-08).
- **184** self-loops — no disposition.
- **25,788** `review_status='pending'` — by construction, nothing is reviewed.
- **847** edges eligible for KG check of 25,788 — 97% of the graph is untested against any reference, by design of the references.

---

## 5. What this component demonstrates, and what it does not

**Demonstrates (independently verified):**
- The triple inventory is exact: 25,788 rows, 0 duplicate canonical triples, 0 duplicate `canonical_triple_id`, 100% evidence coverage, 451/453 papers.
- **No triple carries an ontology identifier** — 25,788/25,788 `unresolved`.
- **68.70%** of triples are a single generic relation, and specificity is demonstrably recoverable (the cleaned layer relabels 2,146 distinct relations without inventing vocabulary).
- The relation vocabulary itself is internally consistent (76 relations, 17 families, 1:1 id mapping, `is_causal`/`is_symmetric` flags agree with families).
- Sentence-level locatability is **84.52% strict / 6.55% unverifiable** — the evidence layer is materially better than its typology layer.
- The source sentence does **not** contain the canonical endpoints literally for **76.16%** of evidence rows.
- Curated-KG support is **13.18% vs 5.78% chance** for microbe–disease — 2.3× enrichment on 622 edges, and nothing better elsewhere.
- The `concept` table is 90.7% unnamed; 7,379 edges with ontology IDs on both ends is a 9.3% subset, not a graph property.
- Pre-registered model assessment: **86.6% states the relation / 22.0% fully supported / 1.46% reversed**.

**Does not establish:**
- That any specific triple is true or false. There is no human annotation; `review_status` is `pending` on 100%.
- That absence from BugSigDB/CTD/Disbiome indicates error — **it does not**, and this audit treats such triples as untested.
- Any precision, recall, accuracy or completeness figure for the triple layer.
- That the 573 `NOT_SUPPORTED` / 683 `NONSENSE` rows are the error set; they are model disagreement.
- That the cleaned layer's 9,682 edges are the correct subset — that is component J's question, and it is model curation.

---

## 6. Component verdict

The triple layer is **structurally sound and semantically thin**. Every triple has evidence, none is duplicated, the vocabulary is self-consistent, 451 of 453 papers contribute, and the sentence layer locates at 84.5% strict — all of which is better than the audit expected given the catalogue's 38.2%. Those are real strengths and they should be stated.

But the layer cannot be called a knowledge graph in any strong sense. **Two thirds** of it is `OTHER_RELATION`; **none** of it carries an ontology identifier; the canonical endpoints are invisible in their own evidence sentence for **three quarters** of rows; **6.3%** has no locatable evidence at all; the only external corroboration available covers 3.3% of the graph at a 2.3× enrichment; and the sole adequacy measurement — model-based, pre-registered, and honestly reported by the KG team — puts full support at **22%**.

The most important thing this component can contribute to the manuscript is not a total but a **split**: 8,071 typed relationships with 84.5% locatable evidence and 13.2%-vs-5.8% external support on the subset that resolves, alongside 17,717 generic co-occurrences that should be labelled as such. The second most important is the sentence that must **not** be written: that the relationships are ontology-grounded, ontologically validated, or human-verified. They are none of those things, and the columns that would say so are literally the string `unresolved`.
