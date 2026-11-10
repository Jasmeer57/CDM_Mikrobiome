# B15: legacy bundle integrity, decision

*2026-11-02. Decision: **close as a false positive. Nothing was restored, re-issued or modified.***

## What was reported

During the validation freeze, a loop ran `sha256sum -c` on every `MANIFEST.sha256` under `releases/`, each **inside its own folder**. Two failed:
- `releases/frozen_output/01_corpus/manifest/MANIFEST.sha256`: README mismatch, 8 files unreadable;
- `releases/frozen_output/02_data_catalogue/manifest/MANIFEST.sha256`: README mismatch, 987 files unreadable.

These were logged as B15 and interpreted as missing files, probably from the 2026-10-30 reorganisation.

## What the investigation found

| Check | Result |
|---|---|
| `01_corpus/manifest/MANIFEST.sha256` vs `pipelines/corpus_v2/releases/2.2.0/MANIFEST.sha256` | byte-identical (`cmp`) |
| `02_data_catalogue/manifest/MANIFEST.sha256` vs `releases/data_catalogue/MANIFEST.sha256` | byte-identical (`cmp`) |
| Source bundle `pipelines/corpus_v2/releases/2.2.0/` against that manifest | verifies, 42 / 42 |
| Source bundle `releases/data_catalogue/` against that manifest | verifies, 1,003 / 1,003 |
| `releases/frozen_output/MANIFEST.sha256` (pins both sub-folders, their READMEs and the copied manifests) | verifies |
| Builder `_build/build_frozen_output.py` (lines 1763–1767, 1822–1826) | copies the source release's `MANIFEST.sha256` into `0X/manifest/` on purpose |
| `01_corpus/README.md` line 13; `02_data_catalogue/README.md` line 16 | document the folder as "the release's own MANIFEST.sha256 … from the source bundle" |

The copied manifests describe the **source bundles**, not the `frozen_output` sub-folders, so they must be verified in the source directories. Run inside the sub-folders, they compare `frozen_output`'s own README with the source README, and look for source files that `frozen_output` never copied. The failures were an artefact of where the check was run, not damage to any bundle.

## ZFS snapshots

Available: `zrepl_20261031_021923_000` … `zrepl_20261102_081923_000` (10 snapshots, roughly 6-hourly). None predates the 2026-10-30 reorganisation, so exact restoration of pre-reorganisation state would not have been possible. It was not needed.

## Decision

- **B15 closed: false positive.** No historical artefact was lost or altered.
- No restore, no recovery copy, no re-issued or superseded manifest. The current releases, the validation results and `frozen_output` are untouched.
- **Correct verification procedure for future checks:**
  - verify `releases/frozen_output/MANIFEST.sha256` from `releases/frozen_output/`;
  - verify each copied `0X/manifest/MANIFEST.sha256` in its source bundle directory, not in the copy's folder.
- **Remaining limitation:** none for integrity. The copied manifests could be renamed (for example `SOURCE_MANIFEST.sha256`) in a future rebuild to prevent the same confusion. That would change a frozen bundle, so it is not done here.
