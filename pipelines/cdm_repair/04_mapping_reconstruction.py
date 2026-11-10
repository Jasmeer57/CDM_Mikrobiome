"""Stage D: Vocabulary mapping reconstruction: deterministic exact/normalised matching against local NCBI Taxonomy, MeSH 2026, Mondo and HPO first; model suggestions only as candidates; every identifier validated locally or marked NOT_VERIFIABLE.

NOT IMPLEMENTED. Gated: runs only if "D" is in config.yaml authorised_stages (2026-11-05: only "A").
"""
import sys

from common import load_config, require_stage

if __name__ == "__main__":
    require_stage(load_config(), "D")
    sys.exit("Stage D is authorised in config but not implemented yet.")
