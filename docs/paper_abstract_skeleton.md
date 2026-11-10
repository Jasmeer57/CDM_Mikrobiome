# Paper abstract skeleton — HMP Corpus resource

Status: **DRAFT SKELETON**. Not a paper. Every number below traces to one of the
INPUT files (listed at the end). Placeholders `[…]` mark human decisions.
No new checks were run; no P5; no GPU.

---

## Title (three candidates)

1. A provenance-tracked, LLM-built resource for human-microbiome literature:
   data catalogue, terminology, ontology, and knowledge graph.
2. From 453 papers to a linked microbiome knowledge substrate: LLM extraction,
   terminology reconciliation, and candidate ontologies.
3. Structured microbiome knowledge at corpus scale: a four-layer,
   provenance-tracked resource from LLM and classical NER extraction.

*Human decision:* choose one; align with target venue.

---

## One-sentence contribution

We release a reproducible, provenance-tracked, four-layer resource built from
453 human-microbiome papers — a structured data catalogue, a terminology layer
reconciling classical NER against an LLM, a candidate ontology base, and a
knowledge graph — explicitly labelled as machine-extracted and unvalidated.

---

## Abstract draft (184 words)

Human-microbiome literature is large, heterogeneous, and largely unstructured. We
present an end-to-end resource that turns 453 publications into four linked,
provenance-tracked layers built with large language models (LLMs) and classical
named-entity recognition (NER). The first layer is a structured data catalogue and
corpus metadata extracted from 4,006 sections (26,874,831 characters): 56,985
records across six entity types, of which 79.4% (45,242/56,985) pass the pipeline's
own evidence check. The second is a terminology layer: 2,505,735 mentions from an
NER ensemble, an LLM, and a MeSH gazetteer; 165,991 canonical terms; and a
crosswalk in which 27,423 of 39,694 LLM-extracted terms (69.1%) match a canonical
term. The two vocabularies overlap but agree exactly for only 16.76% of matched
terms (37.94% at label-family level). The third is an ontology base: canonical
terms, a draft taxonomy, and 334,231 candidate vocabulary mappings. The fourth is
a knowledge graph of 32,713 canonical triples over 37,907 entities. Every item
carries provenance. Nothing is human-validated: no mapping is auto-accepted, all
definitions are review-required, and external ontology linking is staged, not
merged. The resource is a reproducible substrate for curation, not a validated
knowledge base.

*Check:* 184 words (target 150–250). No UNVERIFIED number used.

---

## Per-contribution paragraphs

### C1 — LLM-populated structured data catalogue and corpus metadata (LEAD)

Catalogue run `CATNER_20261023T222954_4008914`; all records carry
`extraction_model=Qwen/Qwen3.5-4B` and
`prompt_version=cdm-catalogue-ner-v2-noplaceholder`, i.e. per-record model and
prompt provenance. Over 453 papers and 4,006 sections, the catalogue holds
**56,985 records across six entity tables** (findings 21,439; assays 12,116;
cohorts 9,575; samples 8,484; datasets 3,228; data_assets 2,143), plus
`papers.csv` (453 rows), for **57,438 across seven tables**. The pipeline's own
evidence check (`evidence_verified==1`) passes for **45,242/56,985 = 79.39%**.
Coverage is **90.857%** of expected characters (processed 24,411,175); section
status is 3,443 complete / 453 empty / 110 incomplete, with 127 failed segments
and an overall `REVIEW_REQUIRED` verdict. Evidence is exact 11,469 / reflowed
40,807 / not located 13,199. An independent offset reconciliation (**verdict A —
false alarm**) found **0/20 NOT_FOUND**: offsets are section-body-relative and
resolve under whitespace normalization at 18/20 (markdown) and 19/20 (sections),
with strict byte equality 6/20. `papers.csv` extraction_status is COMPLETE 344 /
PARTIAL 108 / NO_RECORDS 1; 383/453 papers carry ≥1 finding.

### C2 — Terminology extraction: classical NER vs LLM on 453 papers (SUPPORT)

The terminology stream holds **2,505,735 mentions** from three method families:
`ner_model_ensemble` 1,705,500, `llm_section_ner` 552,147, and
`gazetteer_dictionary_match` 248,088, over **234,250 distinct normalized
mentions**. Three inventories are reconciled but never summed: L1 dedup 166,012,
L2 canonical 165,991, L3 inventory 39,694. The L3→L2 crosswalk matches **27,423
of 39,694 (69.1%)** terms (EXACT_TERM_NORM 21,920 / NORMALIZED 5,503 / UNMATCHED
12,271). The two pipelines use **different type vocabularies** — 25 L3 taxonomy
labels vs 15 CDM types, with **0 shared strings** — so the raw comparison is
`SAME 0 / SUBSET 0 / DISJOINT 17,661 / GENERIC_ONLY 10,209 / NONE 12,271`. After
applying the controlled-vocabulary crosswalk (8/8 legal L3 labels; 12/15 CDM
types), **exact type agreement is 16.76%** (4,597 of 27,423 terms) and
**label-family agreement is 37.94%** (10,405 terms); row-level 4,641/27,870 =
16.65% exact, 10,473 = 37.58% family. The vocabularies **overlap but are not
equivalent** — this is *not* "fundamentally incompatible". Offset verification
is 2,505,650/2,505,735 = 99.9952%, which measures **offsets, not accuracy**.

### C3 — Ontology base: canonical terms + taxonomy + mappings (SUPPORT; candidate)

The canonical registry holds **165,991 terms** with **1,150** source-grounded
definitions and **334,231** candidate vocabulary mappings (RELATED_TO 188,313 /
AMBIGUOUS 96,038 / EXACT_MATCH 38,403 / NO_MATCH_FOUND 11,477). Mapping
disposition is REVIEW_REQUIRED 322,754 / UNRESOLVED 11,477; `auto_accept_eligible`
is 38,334 with **`auto_accepted` = 0**. Mapping sources are cv_linking 292,221 /
omop_local 21,881 / mesh_gazetteer 8,652 (OMOP is a separate view). The taxonomy
schema is **DRAFT** (16 upper + 66 subcategories, reserved `UNCERTAIN`), but the
full classification pass was **not run**: `classified_terms: 0`,
`pct_classified: 0.0`, and `taxonomy_category` is null for all 165,991 terms.
**56.9% (94,458)** of terms carry the generic `ENTITY` type, and **1,090** are
non-concept surfaces (URL_OR_LICENSE 643, CONTROL_CHAR 331, …). This layer is a
**candidate** base, not a validated ontology.

### C4 — Knowledge graph: triples + entities (SUPPORT; staged linking)

The graph holds **32,713 canonical triples** over **37,907 entities**, derived
from **34,416 triple mentions** in **2,498 sections**; triples reference 18,230
distinct subjects, 22,675 distinct objects, and 78 relations.
`triple_mentions.jsonl` is **100% populated** with per-mention provenance
(paper, section, char span, method, model, prompt), whereas
`canonical_triples.jsonl` has **no direct span provenance** (0%) and links
indirectly via `triple_mention_ids`/`paper_ids` (100%). Evidence resolution:
mentions 32,206/34,416 resolved (30,077 exact + 2,129 normalized), 2,210
unresolved; canonical triples 28,528 exact + 1,965 normalized, 2,086 unresolved.
A deterministic 20-triple integrity sample found 20/20 subjects and 20/20 objects
present in `entities.jsonl`, and 20/20 relations in the 79-predicate schema.
**External ontology linking is staged, not merged**: `external_linking_status =
'pending_stage57'` for all 32,713 triples, `subject/object_ontology_id =
'unresolved'` for all, and **5,530** `candidate_entity_mappings` carry no
`auto_accept_eligible` and **no merge field**. The `adjudication_pilot/` is model
triage only, not verification.

---

## Scoring

| contribution | assignment | reasoning |
|---|---|---|
| C1 | **LEAD** | Verdict-A offset reconciliation (0/20 NOT_FOUND; 18/20 and 19/20 whitespace-normalized) plus 79.39% evidence-verified over 56,985 records — the strongest, most directly provenance-backed evidence. |
| C2 | **SUPPORT** | Real, large, reproducible comparison; headline is 16.76% exact / 37.94% family-level type agreement. |
| C3 | **SUPPORT** | Large candidate ontology layer; explicit "candidate" framing (classification not run; nothing accepted). |
| C4 | **SUPPORT** | Real graph with strong internal integrity; explicit "staged, not merged" external-linking framing. |

**Recommended LEAD: C1.** It has the only independent provenance audit with a
clean verdict (A), the highest measured verification rate (79.39%), and the
largest per-record count (56,985), so it anchors the resource claim without
overstating quality.

*Note:* the unrun taxonomy classification inside C3 and the staged external
linking inside C4 are HONEST-LIMITATION items and must not be claimed as
delivered functionality.

---

## Headline numbers table

| contribution | scale | quality metric | status |
|---|---|---|---|
| **C1** | 56,985 records / 453 papers / 4,006 sections | 79.39% evidence-verified (45,242/56,985); 90.857% char coverage | machine-extracted, unverified |
| **C2** | 2,505,735 mentions; 27,423/39,694 (69.1%) L3→L2 matches | 16.76% exact / 37.94% family-level type agreement | machine-extracted, unverified |
| **C3** | 165,991 terms; 1,150 definitions; 334,231 mappings | 0 terms classified; auto_accepted 0/38,334 | candidate layer, unvalidated |
| **C4** | 32,713 triples; 37,907 entities; 5,530 candidate links | 20/20 sampled graph integrity; external linking pending | staged, not merged |

---

## Limitations (explicit)

- **No human validation.** `auto_accepted = 0` of 38,334 `auto_accept_eligible`;
  all findings pending; all 1,150 definitions are `REVIEW_REQUIRED`.
- **20.6% of C1 records have no evidence span** (11,743 / 56,985) — they carry
  `evidence_text` but no offset into the extraction source.
- **C2 type agreement is 16.76% term-level / 37.94% family-level.** This is low
  concept-level agreement over overlapping vocabularies — **not** "fundamentally
  incompatible".
- **C3 taxonomy classification = 0 terms**; 94,458 terms carry the generic
  `ENTITY` type; 1,090 are non-concept surfaces.
- **C4 external ontology linkage is staged, not merged** (5,530 candidate
  mappings; `pending_stage57`).
- **2 known defects:** `coverage.mention_records` 2,505,736 vs
  `term_mentions.jsonl` 2,505,735; `HMDEF_a1583b7942328f19` off-by-one.

---

## What P5 must validate

1. **Term-level type correctness.** The 16.76% figure is a *string-comparison
   result*, not a correctness judgement — a human must decide whether each
   `SAME` pair is actually the right type.
2. **A sample of C1 records.** Does the evidence support the claim? Claim-support
   judgement is **PENDING** in the QC; P5 resolves it.
3. **A sample of C4 triples.** Does subject + relation + object make sense
   semantically?

*(3 claims need human judgement.)*

---

## What remains UNVERIFIED (do not promote)

- **Crosswalk 21,920 / 27,423 / 12,271 — now VERIFIED by P1; treat as verified**
  (moved out of this list).
- `papers.jsonl` field-diff **448 / 386 / 341** — UNVERIFIED.
- **4** material-loss papers; **106** units / **247,720** chars — UNVERIFIED.
- Third character total **26,867,649** — UNVERIFIED (not used in the abstract;
  the abstract cites 26,874,831 from `quality_report.md`).
- zenodo **13-line** manifest — UNVERIFIED.

---

## Input traceability

| INPUT file | used for |
|---|---|
| `logs/quality_c1_c4.md` | C1–C4 tables, scope panel, known defects, UNVERIFIED list |
| `logs/c1_offset_reconciliation.md` | C1 verdict A, 0/20 NOT_FOUND, 18/20 & 19/20, 11,743/56,985 |
| `logs/l3_cdm_mapping_analysis.md` | C2 mapped SAME 4,597 (16.76%), 10,405 (37.94%), row-level 4,641/10,473, UNMAPPED_L3 8, map coverage |
| `logs/p1_summary.md` | crosswalk verification, L1/L2/L3 counts |
| `docs/DATA_SEMANTICS.md` | definitions, three char totals, limitations framing |
| `docs/terminology_crosswalk.md` | L1 166,012 / L2 165,991 / L3 39,694; 21,920/5,503/27,423/12,271; type_relation |

**Read-only:** no file outside `docs/paper_abstract_skeleton.md` and
`logs/paper_abstract_skeleton.log` was written. `docs/DATA_SEMANTICS.md` and
`docs/terminology_crosswalk.md` were not modified. No P5 started; no GPU.
