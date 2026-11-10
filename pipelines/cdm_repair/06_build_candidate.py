"""Stage F: Build a separate CDM 3.1 candidate keeping original ids, evidence and labels beside proposed values, decisions, reasons and provenance, with a reversible change register. No destructive deletion.

NOT IMPLEMENTED. Gated: runs only if "F" is in config.yaml authorised_stages (2026-11-05: only "A").
"""
import sys

from common import load_config, require_stage

if __name__ == "__main__":
    require_stage(load_config(), "F")
    sys.exit("Stage F is authorised in config but not implemented yet.")
