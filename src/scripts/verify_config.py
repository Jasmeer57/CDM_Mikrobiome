#!/usr/bin/env python3
"""Verify that src/configs/canonical.yaml and cdm_pipeline/ner/registry.py are in sync.

Checks:
  1. Every registry key in registry.py appears in canonical.yaml model_table
  2. Output files match
  3. DEFAULT_MODELS in registry.py == in_default_ensemble=true entries in canonical.yaml

Exit code 0 = all checks pass, 1 = mismatch found.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
sys.path.insert(0, str(REPO_ROOT))


def main() -> int:
    import yaml

    from cdm_pipeline.ner.registry import (
        DEFAULT_MODELS,
        MODEL_REGISTRY,
    )

    canonical_path = REPO_ROOT / "src/configs" / "canonical.yaml"
    with open(canonical_path) as f:
        cfg = yaml.safe_load(f)

    model_table = {e["name"]: e for e in cfg.get("model_table", [])}

    errors: list[str] = []

    # Check 1: every registry key is in model_table
    for key in sorted(MODEL_REGISTRY):
        if key not in model_table:
            errors.append(
                f"registry key '{key}' missing from canonical.yaml model_table"
            )
            continue
        # Check 2: output file matches
        reg_output = MODEL_REGISTRY[key]["kwargs"].get("output_file", "")
        can_output = model_table[key].get("output_file", "")
        # canonical.yaml may have "(aggregated)" suffix for scispacy models
        can_base = can_output.split("(")[0].strip()
        if reg_output and can_base and reg_output != can_base:
            errors.append(
                f"output_file mismatch for '{key}': "
                f"registry='{reg_output}' canonical='{can_output}'"
            )

    # Check 3: DEFAULT_MODELS vs in_default_ensemble
    canonical_defaults = {
        name for name, entry in model_table.items()
        if entry.get("in_default_ensemble")
    }
    # canonical.yaml includes qwen with in_default_ensemble=false, so this is fine
    reg_defaults = set(DEFAULT_MODELS)
    if reg_defaults != canonical_defaults:
        only_reg = reg_defaults - canonical_defaults
        only_can = canonical_defaults - reg_defaults
        if only_reg:
            errors.append(
                f"In registry DEFAULT_MODELS but not canonical in_default_ensemble: "
                f"{sorted(only_reg)}"
            )
        if only_can:
            errors.append(
                f"In canonical in_default_ensemble but not registry DEFAULT_MODELS: "
                f"{sorted(only_can)}"
            )

    if errors:
        print("FAIL: canonical.yaml and registry.py are out of sync:")
        for e in errors:
            print(f"  - {e}")
        return 1

    print(
        f"OK: canonical.yaml and registry.py in sync "
        f"({len(MODEL_REGISTRY)} models, {len(DEFAULT_MODELS)} in default ensemble)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
