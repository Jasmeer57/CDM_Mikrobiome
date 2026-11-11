"""Run-to-run variance of the triple re-typing step (diagnostics 2026-11-11, item 2): re-run retype_triples_v2.py
(prompt retype-v2.5, Qwen3.5-9B) unchanged on its own fixed --sample (random.Random(20261110).sample of the 14,867
NO_SPECIFIC_RELATION_STATED triples). Temperature from tempctl (DIAG_TEMPERATURE), default 0 as in the script.

    [DIAG_TEMPERATURE=0.7 DIAG_SEED=20261111] python src/scripts/diagnostics_v32/retype_rerun.py --out DIR --port P --db303 DB --sample 500
Written with Claude Code (declare)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
sys.path.insert(0, str(ROOT / "src/scripts/diagnostics_v32"))
sys.path.insert(0, str(ROOT / "src/scripts/triples"))
import tempctl  # noqa: E402,F401  (must precede the pipeline import)
import retype_triples_v2 as T  # noqa: E402

if __name__ == "__main__":
    T.main()
