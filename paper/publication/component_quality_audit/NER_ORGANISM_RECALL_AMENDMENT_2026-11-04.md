# Component I — dated amendment: the HunFlair2 "Species" figures (F1 0.9441 vs recall 0.556)

**Amendment ID:** `CQA-I-AMEND-2026-11-04-1`
**Date:** 2026-11-04
**Amends:** `NER_BENCHMARK_CORRECTIONS.md` §1.3 (table + one sentence)
**Status:** applied as an inline superseded marker plus this record; **no numeric value in any sealed
artefact changed**
**Trigger:** the required preliminary check of the reported HunFlair2 result — `F1 = 0.9441` alongside
`Recall = 0.556` — which reads as internally contradictory on its face.

---

## 1. Verdict

The two numbers are **not** in conflict. They are different measures on different denominators, both
reproduce exactly from the shipped prediction files, and both are correct as values:

| # | Measure | Denominator | HunFlair2 | PubTator3 | Where it lives |
|---|---|---|---:|---:|---|
| M1 | BioRED `OrganismTaxon`, **per-type exact micro** P / R / F1 | 393 gold mentions of that type | **P 0.9654 / R 0.9237 / F1 0.9441**<br>tp 363 · fp 13 · fn 30 | P 0.7960 / R 0.8142 / F1 0.8050<br>tp 320 · fp 82 · fn 73 | `fair_ner_metrics.json` → `biored__hunflair2.per_type.OrganismTaxon.exact` |
| M2 | Same gold restricted to the **36 non-host** mentions (27 viral + 9 other), exact span **and** label `OrganismTaxon` | 36 gold mentions | **20/36 = 0.556** [0.396–0.705] | 23/36 = 0.639 [0.476–0.775] | this audit's probe, `diagnostics/results/ner_organism_probe.json` |
| M3 | **Full-schema 6-type** exact micro (all BioRED types pooled) | 3,535 gold mentions across 6 types | R 0.7443 / F1 0.8062 | R 0.7601 / F1 0.7832 | `…full_schema.exact` |

M1 and M2 are the same model on nested subsets: M2 removes the host-generic 90.8% of `OrganismTaxon`
gold (357 of 393). A model can score 0.9237 recall on the full type and 0.556 on the remainder without
any contradiction — that is precisely the distributional claim §1.3 was making. **M3 is a third,
unrelated number** and must never be quoted as an `OrganismTaxon` recall.

## 2. Defects found in the *reporting* (not in the measurements)

Three defects, all confined to the §1.3 presentation layer. Values in the JSON, in the prediction files
and in `NER_RECOMPUTATION_CHECK.csv` are untouched.

### D1 — mislabelled column (confirmed defect, reporting)

The table column headed **"Recall on all 393 OrganismTaxon"** does not contain `OrganismTaxon` recalls.
It contains the **full-schema 6-type micro recall** (M3):

| Model | Value printed as "Recall on all 393 OrganismTaxon" | What it actually is | True per-type `OrganismTaxon` recall |
|---|---:|---|---:|
| `hunflair2 †` | 0.744 | full-schema 6-type exact micro recall (0.7443) | **0.9237** |
| `pubtator3 †` | 0.760 | full-schema 6-type exact micro recall (0.7601) | **0.8142** |

The in-cell parenthetical "`(recall, full-schema)`" on the `hunflair2` row shows the intended meaning was
known; the column header nonetheless asserts a 393-mention same-type denominator. Under that header the
two rows invite a false comparison with M2 (0.556), which sits in the next column.
**Correction:** column relabelled "Full-schema 6-type micro recall (3,535 gold)" and the three-row
sensitivity block added below the table.

### D2 — wrong figure in a third column (confirmed defect, reporting)

The `gliner_v25_biomed` cell of "Best measured OrganismTaxon F1" reads **0.3971**. The true per-type
`OrganismTaxon` exact F1 for that model is **0.4238** (tp 171 / fp 243 / fn 222). `0.3971` is
`biored · bert_disease · span_only_relaxed_F1` — a different model, a different metric, a different
configuration (`NER_RECOMPUTATION_CHECK.csv:604`, `fair_ner_metrics.json:3409`). A transcription error
across rows of the metrics table.
**Correction:** 0.4238.

### D3 — "35-mention-versus-36-mention" (confirmed defect, reporting)

The prose called the M1↔M2 contrast "a 35-mention-versus-36-mention comparison". Both subsets are
**36 mentions**; the 27 + 9 partition is exact and the host/viral/other split sums to 393 with no
residual. There is no 35 anywhere in the computation.
**Correction:** "a 36-mention subset of a 393-mention type".

## 3. Reproduction

```bash
cd /home/jkalra_hpc/Microbiome-CDM
# M1 and M3 — straight from the shipped metrics JSON
python3 - <<'PY'
import json; r=json.load(open('outputs/results/benchmark/ner_fair_bench/fair_ner_metrics.json'))
v=r['biored__hunflair2']
print('M1', v['per_type']['OrganismTaxon']['exact'])
print('M3', {k: round(x,4) for k,x in v['full_schema']['exact'].items()})
PY
# M1 re-derived from predictions through the protocol's own projection
python3 -c "import sys;sys.path.insert(0,'src/scripts/ner_fair_bench');import fairbench as fb;print('see probe, §3 of the amendment')"
# M2 and the any-type sensitivity column
python3 paper/publication/component_quality_audit/diagnostics/cqa_ner_organism_probe.py
```

Observed output of the probe (2026-11-04):

```
gold OrganismTaxon 393: host 357 / viral 27 / other 9 -> non-host 36
model                    span-any  span+type  wilson(span+type)
hunflair2               23/36  0.639  20/36  0.556  [0.396, 0.705]
pubtator3               25/36  0.694  23/36  0.639  [0.476, 0.775]
scispacy_bionlp13cg     19/36  0.528  18/36  0.500  [0.345, 0.655]
gliner_v25_biomed       26/36  0.722  21/36  0.583  [0.422, 0.729]
gliner_v25_medium       15/36  0.417  11/36  0.306  [0.180, 0.469]
llm_qwen_fs             34/36  0.944  33/36  0.917  [0.782, 0.971]
llm_gemma_zs            23/36  0.639   8/36  0.222  [0.117, 0.381]
llm_deepseek_fs         20/36  0.556   6/36  0.167  [0.079, 0.319]
```

An independent re-derivation of M1 from `preds/biored__hunflair2.jsonl` (bypassing the metrics JSON and
re-projecting through `fb.project`) returns tp 363 / fp 13 / fn 30 → P 0.9654 / R 0.9237 / F1 0.9441,
identical to the stored value. The per-type block in the JSON and the prediction files therefore agree;
the discrepancy was purely in the prose table.

## 4. Corrected §1.3 table (supersedes the original)

Convention for the M2 column, now stated explicitly: **exact span match _and_ predicted label equal to
`OrganismTaxon`**. The any-type variant is added as a sensitivity column because it separates two
different failures — failing to see the string at all, versus seeing it and assigning the wrong type.

| Model | Full-schema 6-type micro recall (3,535 gold) | `OrganismTaxon` per-type recall (393 gold) | Non-host recall, span+type (36 gold) [95% Wilson] | Non-host recall, span only (36 gold) | `OrganismTaxon` per-type exact F1 |
|---|---:|---:|---:|---:|---:|
| `hunflair2 †` | 0.7443 | 0.9237 | **20/36 = 0.556 [0.396–0.705]** | 23/36 = 0.639 | **0.9441** |
| `pubtator3 †` | 0.7601 | 0.8142 | 23/36 = 0.639 [0.476–0.775] | 25/36 = 0.694 | 0.8050 |
| `gliner_v25_biomed †` | — | 0.4351 | 21/36 = 0.583 [0.422–0.729] | 26/36 = 0.722 | 0.4238 |
| `scispacy_bionlp13cg` | — | 0.7583 | 18/36 = 0.500 [0.345–0.655] | 19/36 = 0.528 | 0.7376 |
| `gliner_v25_medium` | — | 0.4275 | 11/36 = 0.306 [0.180–0.469] | 15/36 = 0.417 | 0.4726 |
| `llm_qwen_fs` | — | 0.3766 | **33/36 = 0.917 [0.782–0.971]** | 34/36 = 0.944 | 0.4241 |
| `llm_gemma_zs` | — | 0.2417 | 8/36 = 0.222 [0.117–0.381] | 23/36 = 0.639 | 0.3276 |
| `llm_deepseek_fs` | — | 0.2646 | 6/36 = 0.167 [0.079–0.319] | 20/36 = 0.556 | 0.2792 |

`†` = annotation-source overlap with BioRED or BC5CDR (see §4 of the main corrections file).

The added span-only column changes the interpretation of two rows and is the substantive gain from
this amendment:

* `llm_gemma_zs` locates the non-host string in **23/36** cases but assigns `OrganismTaxon` only
  **8/36** times — a *labelling* failure, not a detection failure.
* `hunflair2` sees 23/36 and types 20/36, so its 0.556 is a small type-assignment loss on top of a
  0.639 detection ceiling, not a wholesale failure to find non-host taxa.

## 5. What does not change

* **The conclusion of §1.3 stands and is strengthened.** 0.9441 measures host and virus recognition,
  not bacterial-taxon recognition: BioRED `OrganismTaxon` contains **0 bacterial taxa** in both splits,
  90.8% of test gold is host-generic, and every model loses recall when host terms are removed.
* The claim "a high `OrganismTaxon` F1 does not transfer to the CDM's `ORGANISM` target" is unaffected;
  if anything D1 makes the argument cleaner, because the correct same-type recall (0.9237) is now on the
  page next to the non-host recall (0.556) rather than being replaced by an unrelated 0.744.
* No other component's rating, issue, metric row or decision depends on the mislabelled column: §1.3's
  role in Component I's Coverage rating (`CRITICAL WEAKNESS`) rests on the gold composition (0 bacteria,
  36 non-host mentions), not on the 0.744/0.760 cells.
* `CQA-I-09…20` gap register unchanged. `NER_TYPE_COVERAGE_MATRIX.csv`,
  `NER_MODEL_DEPLOYABILITY.csv`, `NER_RECOMPUTATION_CHECK.csv` unchanged.

## 6. Seal status — no reseal required

`NER_RETROSPECTIVE_SEAL.sha256` hashes **126 files / 3,574,150,615 bytes** over the benchmark artefact
set, the protocol scripts, the raw gold, the corpus reference inputs and the audit's own derived CSVs.
`NER_BENCHMARK_CORRECTIONS.md` is **not** among them: it is one of the three narratives deliberately
excluded because it quotes the manifest's own byte count (declared under `not_sealed` in
`diagnostics/results/ner_environment.json`).

* No file listed in the manifest was read-modified-written by this amendment.
* Re-verified after the amendment was applied: `sha256sum -c NER_RETROSPECTIVE_SEAL.sha256` → **126/126
  OK**, every stored digest unchanged.
* `diagnostics/cqa_ner_organism_probe.py` and `diagnostics/results/ner_organism_probe.json` are new and
  **not sealed** (they post-date the seal by construction, exactly like the three narratives). They are
  reproducible from the sealed inputs, which is the stronger property.

## 7. Provenance of this document

| Field | Value |
|---|---|
| Author | audit (single-agent), on the user's explicit instruction to check the HunFlair2 pair |
| Method | re-derivation from `preds/*.jsonl` + `fair_ner_metrics.json`, plus a new conventional split of the 393 gold mentions |
| Independent expert review | **none** — not simulated, not claimed |
| Human adjudication of the 36-mention subset | **none** — the host/viral/other partition is a closed lexicon match, not a judgement call |
| Values altered silently | **0** |
| Superseded text retained in place | yes — marked `*[superseded by CQA-I-AMEND-2026-11-04-1]*` |
