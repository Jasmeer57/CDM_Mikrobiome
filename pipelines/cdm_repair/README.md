# CDM 3.1 repair pipeline (DeepSeek-assisted, computational curation)

**Status (2026-11-05): infrastructure and Stage A (inventory) only.** Stages B–G are gated placeholders. No
inference has been run, no source sentence has been sent to any API, and no CDM database has been built.

This is a computational curation pipeline. It does not replace human validation, and its decisions mean "passed
the implemented computational checks", never "scientifically correct".

## Frozen inputs (read-only; manifests re-verified by every stage)

`releases/cdm_v3/3.0.3/`, `releases/data_catalogue_v3/3.1.1/`, `releases/terminology/1.0.1/`,
`releases/zenodo_frozen/` (integrity only). Earlier DeepSeek outputs are hashed and referenced, never modified
and never treated as ground truth.

## Stages

| Stage | Script | SLURM | Status |
|---|---|---|---|
| A inventory and baseline | `01_inventory.py` | `slurm/01_inventory.sbatch` | **authorised, implemented** |
| B terminology proposals | `02_terminology_proposals.py` | `slurm/02_terminology_inference.sbatch` (array, `%1`) | gated placeholder |
| C triple proposals | `03_triple_proposals.py` | `slurm/03_triple_inference.sbatch` (array, `%1`) | gated placeholder |
| D mapping reconstruction | `04_mapping_reconstruction.py` | `slurm/04_mapping_reconstruction.sbatch` | gated placeholder |
| E deterministic validation | `05_validate_proposals.py` | `slurm/05_validation.sbatch` | gated placeholder |
| F candidate construction | `06_build_candidate.py` | `slurm/06_build_candidate.sbatch` | gated placeholder |
| G regression tests | `07_regression_tests.py` | `slurm/07_regression.sbatch` | gated placeholder |

The gate is `config.yaml: authorised_stages`. A stage not listed exits with code 3 before doing anything.

## Run Stage A

```bash
# from the repository root
sbatch -p intelsr_short pipelines/cdm_repair/slurm/01_inventory.sbatch
```

Outputs go to `outputs/results/cdm_v3_3.1_deepseek_repair/stage_a_inventory/` (written to `.partial`, renamed
on success, never overwritten). A failed reconciliation writes to `stage_a_inventory.FAILED/` and exits 2.

| Output | Content |
|---|---|
| `baseline_inventory.json` | frozen verification, reconciliation, distributions, integrity, routes, rights, estimates |
| `terminology_input.jsonl` | one record per canonical term; evidence as references only |
| `triple_input.jsonl` | one record per triple; evidence as ids, offsets and SHA-256, never text |
| `RIGHTS_ELIGIBILITY_REGISTER.csv` | one row per paper; transmission status; both rights checks `NOT_VERIFIED` |
| `input_manifest.sha256` | SHA-256 of every input file and release manifest |
| `BASELINE_INVENTORY.md`, `PIPELINE_CONFIGURATION_REPORT.md` | reports generated from the inventory |
| `run_provenance.json`, `stage_a_outputs.sha256` | code hashes, software, no API calls, output hashes |

## Rights rules built in

- The 179 papers that need legal confirmation (`WITHHOLD_TEXT`, `RESTRICTED_NC_LAYER`): no text is ever sent.
- The 274 CC BY / CC0 papers (`INCLUDE_TEXT`): candidates only. Text is sent only after `licence_scope_verified`
  and `api_processing_conditions_verified` are recorded as `VERIFIED` by a person in the register.
- Records without eligible sentence evidence stay generic or unresolved for sentence-dependent classification.
- A term string of 50 characters or more that occurs in a withheld paper is treated as a passage and not sent.

## Rate limit

The endpoint allows 50 requests/min per key, shared by everything using the key (including OpenCode). The
pipeline uses 45/min, runs inference arrays one task at a time (`%1`), and needs the key to be otherwise idle.

## Layout

`common.py` (root, config, gate, hashing, read-only DB, atomic output), `reports.py`, `schemas/` (inputs,
proposals, decisions), `prompts/` (drafts, not used), `slurm/`.
