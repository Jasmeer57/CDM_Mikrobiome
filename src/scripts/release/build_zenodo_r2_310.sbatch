#!/bin/bash
#SBATCH --job-name=zen310
#SBATCH --partition=intelsr_medium
#SBATCH --cpus-per-task=4
#SBATCH --mem=128G
#SBATCH --time=08:00:00
#SBATCH --output=outputs/logs/slurm/%x-%j.out
# Public deposit candidate from CDM 3.0.3 + 3.1.0 layers (local build; NOT uploaded). Submit from the repo root.
# alnum matching closes B22; allow-listed vocabulary labels close B23 (allow-list PROPOSED, rights reviewer to confirm).
set -euo pipefail
OUT=${OUT:-releases/zenodo_r2_310}
python3 src/scripts/release/build_zenodo_frozen.py --out "$OUT" --match alnum --vocab-labels allowlist
python3 src/scripts/release/finalize_zenodo_frozen.py --out "$OUT"
python3 src/scripts/release/build_zenodo_310_layers.py --out "$OUT"
python3 src/scripts/release/verify_zenodo_frozen.py --out "$OUT" --match alnum
python3 src/scripts/release/finalize_zenodo_frozen.py --out "$OUT" --seal
echo DONE
