# Release gates — minimal P0.3 pass

Read-only checks for the P0.3 release-gate pass. Nothing here writes into a
release; the JSON report and one-page summary are written under `logs/`.

This pass implements **G2, G5 and G8 only**. G1, G3, G4, G6, G7, G9 and G10 are
out of scope for P0.3 and remain in the older `gates.py` framework.

## Run

```bash
python -m scripts.release_gates.check_all \
    --release releases/terminology/1.0.0 \
    --release corpus_v2/releases/2.2.0 \
    --release data_catalogue
```

With no `--release`, the same three targets are used. `--out` overrides the
report path (default `logs/release_gate_report.json`); the summary is written to
`logs/p0_3_summary.md`.

Exit status is `0` when no gate failed and `1` otherwise. `MISSING` is a
failure. `SKIPPED` means the gate does not apply to that target (for example,
G2/G5 on a non-terminology product).

## Gates

| Gate | Applies to | Checks |
|---|---|---|
| **G2** | terminology releases | Three-way equality for `term_mentions.jsonl`, `canonical_terms.jsonl`, `term_definitions.jsonl`, `term_ontology_mappings.jsonl`: `coverage.<alias>` == `artifacts[<file>].records` == physical line count. The 1.0.0 freeze is expected to FAIL on `2,505,736` vs `2,505,735`; this is the known defect and must not be repaired in place. |
| **G5** | terminology releases | Counts `auto_accept_eligible` and any acceptance marker in the mappings. Fails if `auto_accepted > 0` without a calibration file, if an accepted row is not eligible, or if an accepted row lacks a cleared verdict. Records the calibration state and whether the review sheet is empty. |
| **G8** | all | Walks the release tree and every source directory declared in `PROVENANCE.json:sources`. Fails on basenames matching `secrets.env`, `*.env`, `*.key`, `*.pem` or `secrets*` (basename/mode/size only; candidate files are never opened). Also checks, existence-only, whether `corpus_v2/config/secrets.env` is listed in the corpus 2.2.0 or data-catalogue `MANIFEST.sha256`. |

## Design rules

* **Fail-closed.** A missing input is reported as `MISSING`; it is never treated
  as `0`, `COMPLETE`, or `PASS`.
* **Read-only.** Gates never edit the artifact they check. A failing frozen
  release is fixed by a new release version, not by patching the freeze.
* **Deterministic.** Sampling, where used, ranks by
  `sha1("qc-v1|" + stable_id)`. No `random()`, no builtin `hash()`, no
  `os.urandom()`.
* **Counts are not summed across products.** G2 compares each product with its
  own manifest.
* **CSV row counts use a CSV parser.** `wc -l` is not a row counter for the
  catalogue CSVs because evidence fields contain embedded newlines.
* **Known defect.** `HMDEF_a1583b7942328f19` has a one-character definition-span
  shift. It is recorded, not repaired.
