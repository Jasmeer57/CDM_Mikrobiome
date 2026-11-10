"""Stage G: Final integrity and regression tests: frozen hashes unchanged, CDM 3.0.3 regression suite, candidate revertible to its inputs, every input record has a status.

NOT IMPLEMENTED. Gated: runs only if "G" is in config.yaml authorised_stages (2026-11-05: only "A").
"""
import sys

from common import load_config, require_stage

if __name__ == "__main__":
    require_stage(load_config(), "G")
    sys.exit("Stage G is authorised in config but not implemented yet.")
