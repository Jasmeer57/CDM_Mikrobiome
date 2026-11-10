# Data semantics — reading the numbers correctly

Why several superficially contradictory numbers are all correct, and what each
status label actually promises. Verified against source files on 2026-10-26.

---

## 1. 26,874,831 vs 26,871,587 vs 26,867,649

Three real measurements of the same 453-paper corpus at three different
text-processing states. They are **not** three estimates of one quantity.

| Value | Where | What was measured |
|---:|---|---|
| **26,874,831** | `corpus_v2/releases/2.2.0/corpus_manifest.json` → `counts.characters` | Σ `character_count` over all 4,006 section units, on `section_text_original` |
| **26,871,587** | `segmented_sections_markdown/_conversion_report.json` → `report.total_chars` | characters actually written into the 453 `.md` files' segment bodies |
| **26,867,649** | `results/terminology_v1/validation_summary.json` → `coverage.total_chars_processed` | content the terminology validator walked after parsing markers and normalising segment whitespace |

They nest, and the gaps are fully explained:

```
26,874,831  section_text_original            (authoritative corpus text)
 −    3,244   one trailing newline removed per non-empty unit
26,871,587  markdown segment bodies
 −    3,938   marker lines + per-segment whitespace normalisation
26,867,649  content seen by the terminology validator
```

Evidence, measured per section rather than asserted:

- `Σ character_count` = `Σ len(section_text_original)` = **26,874,831** exactly.
- `len(markdown) − len(section_text_original)`: **3,244 units are −1**, 762 are
  0. Nothing else occurs. The markdown writer drops exactly one trailing
  newline per non-empty unit.
- `content_chars − len(markdown)` across the 4,006 validation rows:
  `−1 × 3,134`, `−2 × 239`, `−3 × 76`, `−4 × 12`, `−5 × 10`, `0 × 535` →
  **−3,938**.

**Rule:** cite the number for the state you mean. "Corpus characters" =
26,874,831. "Chars in the markdown" = 26,871,587. "Chars the terminology build
processed" = 26,867,649. Never compare them as if one were wrong.

---

## 2. `full_text_completeness = partial` does not mean text was lost

Distribution in 2.2.0: **`partial` 407, `complete` 46**.

`full_text_completeness` is derived in `corpus_v2/scripts/stage60_validate.py`
from the *validation verdict* (`worse_ft` keeps the more severe of the stage-40
parse verdict and the stage-60 verdict). `partial` means: **not every automated
completeness check passed** for that paper — typically the paper is
abstract-only, or some sections could not be located in the source.

It is a property of the *input document*, not of the pipeline's handling. A paper
that arrived as an abstract is recorded `partial`; nothing was truncated,
dropped, or corrupted during processing. `uncovered_chars = 0` in the conversion
report confirms the segmentation covered every character it was given.

Conversely, `complete` means every check passed — **not** that a human read the
paper.

---

## 3. `REVIEW_REQUIRED` vs `PARTIAL` vs `COMPLETE` vs `UNVERIFIED`

Four different vocabularies that are routinely conflated.

| Label | Belongs to | Meaning |
|---|---|---|
| `COMPLETE` | `papers.validation_status` | every automated validation check passed (fail-closed: one failure ⇒ not COMPLETE) |
| `PARTIAL` | `papers.validation_status` | the record validated but is a non-canonical duplicate, or checks partially failed |
| `REVIEW_REQUIRED` | `papers.validation_status`, catalogue `coverage_status` | machine output with recorded gaps; **must not** be used for a scientific claim without review |
| `UNVERIFIED` | anywhere in this repo | no human has reviewed the row, regardless of automated verdict |

`COMPLETE` is an **automated** verdict. It does not imply `VERIFIED` and does not
upgrade a record out of `UNVERIFIED`.

2.2.0 papers: `{REVIEW_REQUIRED 392, COMPLETE 46, PARTIAL 15}`. The catalogue's
`coverage_status` is also `REVIEW_REQUIRED` — the same label, a different
pipeline, at a different scope.

---

## 4. 21,395 corpus findings ≠ 21,439 catalogue findings

| | Corpus 2.2.0 | Data catalogue |
|---|---:|---:|
| Findings | **21,395** | **21,439** |
| Path | `corpus_v2/releases/2.2.0/data/findings.jsonl` | `data_catalogue/records/catalogue_findings.csv` |
| Extraction | corpus_v2 stage 50/55 | `catalogue_ner_v2` Qwen vLLM |
| Built | 2026-10-25 | 2026-10-23 |
| Corpus input | 2.2.0 | **2.0.0** (embedded) |

**They are two independent extraction runs over different corpus versions.**
The 44-record difference is expected: different prompts, different section
inventory, different text state. Neither is a correction of the other, and
neither supersedes the other. Do not reconcile them by arithmetic, and never add
them.

If a future release needs one finding set, it must be produced by a single run
over a single corpus version — not by merging these two.

---

## 5. Why the catalogue embeds corpus 2.0.0 metadata

`data_catalogue/corpus_v2/releases/2.0.0/` and `data_catalogue/corpus_v2/data/`
are a **snapshot of the corpus tree as it existed when the catalogue was built**
(2026-10-23). The catalogue is a checksummed bundle; copying its inputs in is
what makes it independently reproducible.

The snapshot is partly *stale* and partly *still current*:

| Embedded file | vs 2.2.0 | vs 2.1.0 |
|---|---|---|
| `sections.jsonl` | byte-identical | byte-identical |
| `segments.jsonl` | byte-identical | byte-identical |
| `llm_terms.jsonl` | byte-identical | byte-identical |
| `papers.jsonl` | **differs** | differs |

So three text artifacts really are unchanged from 2.1.0 through 2.2.0, while
`papers.jsonl` (validation verdicts, completeness, tracking fields) advanced.
That is why the catalogue can be *mostly* reproduced from 2.2.0 text while its
own declared corpus version remains 2.0.0.

**Correct reading:** "the catalogue was built against corpus 2.0.0 metadata; its
section, segment, and llm_terms inputs happen to be byte-identical to 2.2.0."
**Incorrect reading:** "the catalogue was built on 2.2.0."

A future catalogue release should record its corpus version explicitly and either
refresh the snapshot or declare the 2.0.0 pin.

---

## 6. 99.9952% measures offset verification, not accuracy

The terminology validation reported `mentions_checked = 2,505,650` and
`mentions_resolved_exactly = 2,505,650` (100.0%), against a mention total of
2,505,735. The headline "99.9952%" (2,505,650 / 2,505,735) is therefore
**arithmetic over a completeness check**.

What it does verify: each mention's `start_offset`/`end_offset` lands on a span
that reproduces its surface form. That is a *plumbing* property — it catches
broken offsets, not wrong terms.

What it does **not** verify: that the mention is a real entity, that its type is
right, that a definition is correct, or that a mapping is valid. A span can be
perfectly located and completely wrong scientifically.

An independent gate re-check (G4) found the same 85 rows excluded, and refined
the picture: against `section_text_original`, **93.74% of mentions slice exactly,
6.26% need a bounded shift (mostly +1) across 75 sections, and 0 are
unresolvable**. The shift is a rendering artefact at segment boundaries — see
§7.

**Rule:** never quote an offset-verification percentage as an accuracy or
quality figure.

---

## 7. Offsets are section-relative, and not always byte-exact

`start_offset` / `end_offset` in `term_mentions.jsonl` are relative to their
**section**, not to the file or the paper. They reproduce the surface exactly for
93.74% of mentions against `corpus_v2/releases/2.2.0/data/sections.jsonl`
(`section_text_original`).

The remaining 6.26% resolve only after shifting by a bounded amount:

| Shift | Mentions |
|---:|---:|
| 0 (exact) | 2,348,766 |
| +1 | 154,577 |
| +2 | 2,305 |
| −1 | 2 |

Cause: the offset-computation rendering joins segment bodies slightly
differently from `section_text_original` (one inserted character per affected
boundary), so every subsequent offset in that section drifts by that amount. 75
sections are affected.

**Consumer rule:** to slice a span, try the stated offset first; if the slice
does not match the surface, try ±1 and ±2. Do not assume byte-exact slicing, and
do not "fix" offsets in place — that would silently break the frozen
provenance.

---

## 8. The soft join `canonical_term_id` does not exist

`canonical_term_id` is **null for all 2,505,735 mentions**. Canonicalisation was
not run against the mention stream; the relationship is documented as a *soft
join*:

```
(normalized_mention, entity_type)  ->  (term_norm, cdm_type)   in L2
```

Measured behaviour of that join over the full build:

| Bucket | Mentions | Share |
|---|---:|---:|
| Term found **and** type agrees | 1,174,969 | 46.89% |
| Term found, observed type differs | 1,030,912 | 41.14% |
| Term absent from L1/L2 entirely | 299,854 | 11.97% |

The middle bucket is the important one: **it is a preserved type conflict, not a
broken reference.** L2 assigns one primary `cdm_type` per term; each NER
observation carries its own `entity_type`. `microbiota` observed as `ENTITY` and
as `CHEMICAL`, `patients` as `CLINICAL`, `gut microbiome` as `ORGANISM` — these
are real disagreements between observation and canonical choice.

Do **not** resolve them by preferring the canonical type, the majority type, or
the first-seen type. The crosswalk records them
(`docs/terminology_crosswalk.md`). A consumer that needs one type per mention
must make that policy explicit and record it.

---

## 9. Counts that must never be added

| Quantity | Why not |
|---|---|
| L1 dedup (166,012) + L2 canonical (165,991) + L3 inventory (39,694) | L2 is derived from L1; L3 is a different extraction |
| Corpus findings (21,395) + catalogue findings (21,439) | different runs, different corpus versions |
| CV linking + OMOP linking links | overlapping views over the same term pairs |
| CPU NER + Qwen mentions | different models observing the same text |

Report each inventory's count separately, always with the inventory named.

---

## 10. The catalogue has six entity tables, not seven

`data_catalogue/tables/` holds seven CSVs, but only six are entity records:

| File | Rows |
|---|---:|
| `findings.csv` | 21,439 |
| `assays.csv` | 12,116 |
| `cohorts.csv` | 9,575 |
| `samples.csv` | 8,484 |
| `datasets.csv` | 3,228 |
| `data_assets.csv` | 2,143 |
| **six entity types** | **56,985** |
| `papers.csv` (not an entity table) | 453 |
| **all seven CSVs** | **57,438** |

The headline **56,985** is the six-entity total; **57,438** counts `papers.csv`
too. Both are correct for their scope. Count rows with a CSV parser
(`csv.reader`), never `wc -l` — the evidence-quote fields contain embedded
newlines. `data_catalogue/MANIFEST.json` → `records` / `records_per_entity` is
authoritative.

---

## 11. Catalogue offsets are section-body-relative and not always byte-exact

Catalogue records that carry a span store `char_start` / `char_end` relative to
the **section body** in the extraction source (`segmented_sections_markdown/`),
not to the paper or the file. A 20-record audit
(`logs/c1_offset_reconciliation.md`) found **0/20 NOT_FOUND**:

| Test | Result |
|---|---|
| Strict byte equality, markdown source | 6/20 EXACT (14 SHIFTED) |
| Whitespace-normalized equality, markdown | **18/20** (12 at delta 0; 2 genuine shifts of −1, −2) |
| Whitespace-normalized equality, `sections.jsonl` | **19/20** (13 at delta 0; 1 shift of −2) |

`evidence_text` is whitespace-normalized (collapsed) relative to the raw source,
so line-wrapping differs even when the span is correct. The residual deltas are
≤2-char section-boundary artifacts.

**Consumer rule:** slice with the stated offsets and compare after whitespace
normalization; tolerate a ±1/±2 shift. Do not assume byte-exact slicing and do
not rewrite offsets in place.

---

## 12. 11,743 catalogue records (20.6%) have no span at all

Of 56,985 catalogue records, **11,743 (20.6%)** carry `char_start = None` — they
were extracted with an evidence quote but no locatable span, so they have no
provenance offset. Top three entity types: findings 3,883, assays 2,609, cohorts
2,226. Per-entity null share: datasets 29.1%, cohorts 23.2%, assays 21.5%,
data_assets 19.7%, samples 19.6%, findings 18.1%.

`record_id` is not stored in the JSONL, so a stable record key is
`paper_id|section_id|char_start|char_end|entity_type`.

This is a **provenance** gap, not a claim that the record is wrong: a record with
no span simply cannot be traced back to source text. Report it as
"unprovenanced", never as an error count.

---

## 13. 296 "cross-checked" papers is not 296 XML files

`corpus_v2/releases/2.2.0/corpus_manifest.json` → `counts.independent_fulltext_crosschecked = 296`
counts **papers** whose full text was independently cross-checked against an
external source. It is **not** an XML-file count.

Two different XML populations exist and must not be conflated:

| Population | Count | Path |
|---|---:|---|
| Root `fulltext/` JATS originals | **73** | `fulltext/*.jats.xml` |
| `168000-samples-paper/fulltext/` compendium metadata | per-BioProject | `168000-samples-paper/fulltext/` |

The corpus's own text source is `segmented_sections_markdown/` (derived from
PubMed full text), declared in `corpus_manifest.json` → `source`. There is no
296-file XML tree in this repository.
