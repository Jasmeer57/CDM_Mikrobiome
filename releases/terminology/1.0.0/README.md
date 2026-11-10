# Terminology Build 1.0.0 — frozen release

Immutable copy of `results/terminology_v1/` (job **28619916**). The live working
directory is preserved in place; this release exists so the build can be cited.

## Build identity

| Field | Value |
|---|---|
| job_id | `28619916` |
| pipeline_version | `v1` |
| manifest_version | `1.0.0` |
| generated_at | `2026-10-25T17:45:38` |
| corpus_release | `2.2.0` |
| frozen_at | `2026-10-26T10:21:35Z` |

## Artifacts

| Artifact | Bytes | Records | SHA-256 |
|---|---:|---:|---|
| `term_mentions.jsonl` | 3,571,822,409 | 2505735 | `3df4218c683a961c26363c1208d654a851f98aadcc60c836894d398f1f500b01` |
| `canonical_terms.jsonl` | 128,869,681 | 165991 | `5c930decd13cac71ea3bd3b72bba40b5b6ed278a3e664db38aa5248714e7c022` |
| `term_definitions.jsonl` | 806,386 | 1150 | `05e124956adcddd14b6493e9a9256aeb9a85a8ea795a0bd584a7b6c5faa56af1` |
| `term_ontology_mappings.jsonl` | 382,755,547 | 334231 | `d31f588aac84b8bed66327a1a699cac4eafe3e61818962aa09e6894074b88869` |
| `terminology_taxonomy.json` | 42,159 | — | `26f36414948752c1dc411324989cf41d1662fcb3ddf4841b729f57ce10d7d712` |
| `ontology_registry.json` | 4,275 | — | `83666cadd4662edb33954c06b6ea6003bb00153290b03ef696b11d403e33d800` |
| `terminology_validation.jsonl` | 2,593,819 | 4006 | `155d9cb33ec978215e8c0b0128b5bdb2f5b44e28efc1d36c4144066407f3e2bf` |
| `terminology_extraction_report.md` | 8,567 | — | `61388f313a566f2298430dea4db893ab952d3df0e4f934dbfb046bdfed31f1a5` |

## Source bindings

| Source | Path | Bytes | SHA-256 |
|---|---|---:|---|
| `canonical_input_table` | `data_catalogue/terminology/terminology_dedup.csv` | 17,197,844 | `4541535763b697c842610ea17e84fc7abd76c7f73b173583787f1406dd2cb4e1` |
| `cpu_ensemble_ner` | `zenodo_v1/ner_453_sections/all_ner_sections_combined.csv` | 135,625,815 | `e682e22423e135c74449eee37adb92ac2fda6997355fb8ab1a194495b58daad6` |
| `cv_linking` | `results/cv_linking/cv_mapped_entities.jsonl` | 72,155,139 | `489ab20dabf65d30ba28b004ee78776a23896a064e54ec2cedcde790e6512d87` |
| `mesh_gazetteer` | `results/mesh_ner/mesh_ner_terms.csv` | 19,875,572 | `15849f2b1f2bcc4162ad7d171edc840b65091fd8a80ef193e9181ca9b3f902a1` |
| `omop_linking` | `results/omop_linking/omop_links.csv` | 2,477,080 | `281cbd91bf39c7635e61358da502d1cc0bb243f80ec0f0496ecefda34d123368` |
| `qwen_ollama_ner` | `zenodo_v1/qwen_sections_ner/qwen_sections_ner.csv` | 15,417,567 | `c8dfeda2a7fee585616c85d1d0da6c6f0a05d01a70df7428584e64041f926935` |
| `qwen_vllm_body_ner` | `results/llm_ner_body/vllm_sections_ner.csv` | 30,895,370 | `78323cc94bb5fc539fd1f41159b98a9389c7f7e33deb2ca53f1f3fa0e1b5ba6c` |
| `sections` | `segmented_sections_markdown/` (453 files) | — | tree `0c2b5769e7e9d8e0697c5d7ac0b24e8a67a468b2daf64a64d9cd2d38fb133c53` |
| `taxonomy` | `data_catalogue/terminology/taxonomy/term_taxonomy_v1.yaml` | 60,469 | `cb43c6ea1c8f970a81ee3b0212fb76256eb520b88674aa5b38131fa479a8982c` |

The `sections` tree digest is the SHA-256 of the sorted lines
`<per-file sha256>  <path>` for the 453 `.md` files.

## Non-claims (verbatim)

* No human verification has been performed on any row.
* auto_accepted = 0; calibration = NOT_CALIBRATED.
* All mentions are UNVERIFIED; all definitions are REVIEW_REQUIRED.
* The 99.9952% offset-verification figure is offset verification, not accuracy.

## Calibration

`calibration_v0_pre_fix/` is retained for provenance only. It was drawn against
**334,275** mapping rows; this build has **334,231**. It must not be pooled with
the current build or treated as validation of it. See `QUARANTINE.md`.

## Crosswalk

`docs/terminology_crosswalk.md` — status at freeze time: **pending**. The
document is authored after this freeze and describes the relationship between
the three term inventories (L1/L2/L3). It does not alter any byte in this
release.

## Integrity

`MANIFEST.sha256` covers every file in this directory except itself. The
authoritative control is the manifest digest recorded in
`releases/RELEASES.md`; filesystem permissions are a soft freeze only.
