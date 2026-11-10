"""Stage C: Knowledge-graph repair proposals (DeepSeek): TYPED_RELATION, GENERIC_COOCCURRENCE, UNSUPPORTED or AMBIGUOUS, with exact supporting sentence and evidence reference for typed relations. Only triples on route SENTENCE_CANDIDATE_PENDING_RIGHTS_VERIFICATION whose papers are VERIFIED are sent; the rest stay generic or unresolved.

NOT IMPLEMENTED. Gated: runs only if "C" is in config.yaml authorised_stages (2026-11-05: only "A").
"""
import sys

from common import load_config, require_stage

if __name__ == "__main__":
    require_stage(load_config(), "C")
    sys.exit("Stage C is authorised in config but not implemented yet.")
