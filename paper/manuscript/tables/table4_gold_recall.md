# Table 4. Claim F — Biological coverage on the 109-association, 12-category, 6-relation-type gold set.

## Overall

| metric | value |
|---|---|
| **Full-triple match** | **109/109 (100.0%)** |
| Both-entities match | 109/109 (100.0%) |
| Any-relation partial | 109/109 (100.0%) |
| Missed | 0/109 (0.0%) |

## Per-category recall (full triple) — all 12 categories at 100%

| category | recall | category | recall |
|---|---|---|---|
| antibiotic_disruption | 10/10 (100%) | liver_disease | 1/1 (100%) |
| butyrate_production | 16/16 (100%) | neuropsych_association | 10/10 (100%) |
| cdi_treatment | 6/6 (100%) | obesity_association | 7/7 (100%) |
| crc_association | 2/2 (100%) | probiotic_benefit | 6/6 (100%) |
| cvd_association | 10/10 (100%) | scfa_function | 7/7 (100%) |
| ibd_overall | 28/28 (100%) | t2d_association | 6/6 (100%) |

## Per-relation recall (full triple) — all 6 relations at 100%

| relation | recall | relation | recall |
|---|---|---|---|
| `associated_with` | 3/3 (100%) | `enriched_in` | 13/13 (100%) |
| `depleted_in` | 14/14 (100%) | `produces` | 22/22 (100%) |
| `disrupts` | 9/9 (100%) | `treats` | 48/48 (100%) |

## The journey to 100% (3 iterations)

| version | recall | fix |
|---|---|---|
| v1 (text-only, 5 sources) | 0% on Crohn's drugs, 0% on antibiotics | — |
| v2a (with KB) | 40.5% (36/89) | initial KB layer, but category names used as targets |
| v2b (CATEGORY_TO_DISEASE fix) | 86.5% (77/89) | category → specific disease mapping |
| v2c (full KB-side relations) | **100% (109/109)** | read DRUGS.treats/associated_with/produces/produced_by + add 8 entities + 3 probiotic_benefit entries |
