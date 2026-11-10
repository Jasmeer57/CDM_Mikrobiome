# Stage 1 - Target-453 Inventory Reconciliation

- Config version: `1.0.0`
- Expected target papers: **453**
- Corpus records found: **453**
- Records missing: **0**
- Ready for downstream stages: **435**
- Blocked: **18**
- Total sections inventoried: **3127**
- Total findings recorded: **1485** (in 31 papers; 422 papers have none)
- Non-target inventory entries tracked separately: **30**

## Blocking issues

| corpus_id | accession | issues |
|---|---|---|
| HMPAPER_000052 | PRJEB31354 | full_text_completeness=partial;likely_abstract_only |
| HMPAPER_000075 | PRJEB38948 | full_text_completeness=partial |
| HMPAPER_000076 | PRJEB39289 | full_text_completeness=partial;likely_abstract_only |
| HMPAPER_000117 | PRJNA298590 | full_text_completeness=partial;abstract_supplement_marker |
| HMPAPER_000132 | PRJNA323360 | full_text_completeness=partial;likely_abstract_only |
| HMPAPER_000170 | PRJNA389431 | full_text_completeness=partial |
| HMPAPER_000178 | PRJNA396815 | full_text_completeness=partial;likely_abstract_only |
| HMPAPER_000314 | PRJNA573829 | likely_abstract_only |
| HMPAPER_000315 | PRJNA574565 | full_text_completeness=partial;likely_abstract_only |
| HMPAPER_000357 | PRJNA625181 | full_text_completeness=partial;likely_abstract_only |
| HMPAPER_000359 | PRJNA627982 | abstract_supplement_marker |
| HMPAPER_000365 | PRJNA633160 | full_text_completeness=partial;likely_abstract_only |
| HMPAPER_000370 | PRJNA644097 | full_text_completeness=partial;likely_abstract_only |
| HMPAPER_000372 | PRJNA644520 | full_text_completeness=partial |
| HMPAPER_000403 | PRJNA685746 | full_text_completeness=partial;likely_abstract_only |
| HMPAPER_000427 | PRJNA715766 | full_text_completeness=partial;likely_abstract_only |
| HMPAPER_000430 | PRJNA720325 | likely_abstract_only |
| HMPAPER_000446 | PRJNA750230 | full_text_completeness=partial |

## Prior documented decisions (re-verified against disk)

| accession | prior state | present in target set |
|---|---|---|
| PRJNA715072 | eligible_pending_integrity_check | yes |
| PRJNA559898 | eligible_pending_integrity_check | yes |
| PRJNA644097 | EXCLUDED_ABSTRACT_ONLY | yes |
| PRJNA627982 | EXCLUDED_ABSTRACT_ONLY | yes |
| PRJDB11894 | EXCLUDED_WRONG_PAPER | yes |
| PRJNA721421 | HARMONIZATION_FAILED | yes |
