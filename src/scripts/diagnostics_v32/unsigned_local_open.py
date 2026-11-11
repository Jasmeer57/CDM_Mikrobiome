"""Licence-group comparability (diagnostics 2026-11-11, item 1): run the LOCAL Qwen3.5-9B backend of
resolve_unsigned_associations.py on the 959 CC BY / CC0 triples that were resolved by DeepSeek-V4.1-Flash.

Same prompts, same batching (sorted ids, BATCH=4), same code gates and verification: the module's own scope selection
for --backend genie (licence filter + assertion) is reused, only the Backend is replaced by the local vLLM client, so
no text leaves the cluster. Output DIR/unsigned_resolved.genie.part<JOB>.jsonl (rows carry backend="genie" from the
module; the analysis relabels them local_on_open). Never writes into the 2026-11-10 run folder.

    python src/scripts/diagnostics_v32/unsigned_local_open.py --port P --model cyankiwi/Qwen3.5-9B-AWQ-4bit --db303 DB --out DIR
Written with Claude Code (declare)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
sys.path.insert(0, str(ROOT / "src/scripts/triples"))
import resolve_unsigned_associations as R  # noqa: E402

OLD_RUN = (ROOT / "outputs/results/unsigned_resolve_2026-11-10").resolve()


class LocalBackend(R.Backend):
    def __init__(self, kind, port=None, model=None):   # never builds the external client
        self.kind, self.port, self.model = "local", port, model


def main():
    args = sys.argv[1:]
    out = Path(args[args.index("--out") + 1]).resolve()
    assert OLD_RUN not in out.parents and out != OLD_RUN, "refusing to write into the frozen 2026-11-10 run"
    R.Backend = LocalBackend
    sys.argv = [sys.argv[0], "--backend", "genie", *args]
    R.main()


if __name__ == "__main__":
    main()
