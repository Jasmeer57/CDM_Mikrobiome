"""Run-variance helper (diagnostics 2026-11-11): override the sampling temperature of every OpenAI-style
/chat/completions request made through urllib in THIS process, without editing the pipeline scripts.

    DIAG_TEMPERATURE=0.7 DIAG_SEED=20261111 python <wrapper>.py ...

Unset DIAG_TEMPERATURE -> requests are sent unchanged (the scripts' own temperature 0). Import before the pipeline
module. Written with Claude Code (declare)."""
from __future__ import annotations

import json
import os
import urllib.request

T = os.environ.get("DIAG_TEMPERATURE")
SEED = os.environ.get("DIAG_SEED")
if T is not None:
    _Base = urllib.request.Request

    class _Req(_Base):
        def __init__(self, url, data=None, *a, **k):
            if data and str(url).rstrip("/").endswith("/chat/completions"):
                b = json.loads(data)
                b["temperature"] = float(T)
                if SEED:
                    b["seed"] = int(SEED)
                data = json.dumps(b).encode()
            super().__init__(url, data, *a, **k)

    urllib.request.Request = _Req
    print(f"[tempctl] temperature override {T} seed {SEED}", flush=True)
