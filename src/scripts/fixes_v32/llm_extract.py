"""Step 3 of the 3.2.0-candidate fix: field-targeted extractor (local Qwen3.5-9B AWQ via vLLM, thinking disabled,
temperature 0, JSON-schema constrained). For each candidate window from dict_pass.py it returns, VERBATIM from the
window, the DNA extraction kit/method and the sequencing platform used for THIS study's samples, or NOT_REPORTED;
extraction described only by citation ("as described previously [12]") is returned as CITED_PROTOCOL with the cited
text. Spans are verified here: exact substring first, else whitespace/case-insensitive match; failures are kept in the
output with verified=false and never used as values.

    python src/scripts/fixes_v32/llm_extract.py --host http://127.0.0.1:PORT --out DIR --shard 0 --nshards 1
Written with Claude Code (declare).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
sys.path.insert(0, str(Path(__file__).resolve().parent))
import gazetteer as G  # noqa: E402

MODEL = "cyankiwi/Qwen3.5-9B-AWQ-4bit"
SYSTEM = """You extract two methods fields from a passage of a microbiome research paper. Use ONLY the passage.

1. dna_extraction: the kit, instrument-based protocol or method used to extract DNA from THIS study's samples
   (e.g. a commercial kit name, "phenol-chloroform extraction", "bead beating", "IHMS protocol Q").
   - STATED: copy each kit/method name VERBATIM from the passage (shortest exact text that names it; you may include
     the vendor if it is adjacent). Do not normalise, translate or complete names.
   - CITED_PROTOCOL: the passage says DNA was extracted but gives the method only by reference ("as described
     previously [12]", "according to Smith et al.") and names no kit or method. Put the verbatim referring text in
     "cited_text". Do NOT guess the method from the citation.
   - NOT_REPORTED: the passage does not say how DNA was extracted.
   Do NOT report kits used for PCR clean-up, gel extraction, DNA quantification (Qubit, PicoGreen), library preparation,
   RNA extraction only, or sample collection/stabilisation.
2. sequencing_platform: the sequencing instrument/platform used to sequence THIS study's samples
   (e.g. "Illumina MiSeq", "HiSeq 2500", "Ion Torrent PGM", "PacBio Sequel", "454 GS FLX").
   - STATED: copy each platform name VERBATIM from the passage (shortest exact text, may include the vendor).
   - NOT_REPORTED: no platform is stated for this study's samples.
   Do NOT report platforms mentioned only for other studies, public datasets re-analysed from elsewhere, or reagent
   names (e.g. "Illumina adapters", "Nextera XT", "MiSeq Reagent Kit v3" is a reagent: report "MiSeq" only if the
   passage says the samples were sequenced on it).
Every string in "spans" must appear character-for-character in the passage. Return ONLY the JSON object."""
SCHEMA = {"type": "object", "additionalProperties": False, "required": ["dna_extraction", "sequencing_platform"],
          "properties": {
              "dna_extraction": {"type": "object", "additionalProperties": False, "required": ["status", "spans", "cited_text"],
                                 "properties": {"status": {"type": "string", "enum": ["STATED", "CITED_PROTOCOL", "NOT_REPORTED"]},
                                                "spans": {"type": "array", "maxItems": 4, "items": {"type": "string", "maxLength": 160}},
                                                "cited_text": {"type": "string", "maxLength": 300}}},
              "sequencing_platform": {"type": "object", "additionalProperties": False, "required": ["status", "spans"],
                                      "properties": {"status": {"type": "string", "enum": ["STATED", "NOT_REPORTED"]},
                                                     "spans": {"type": "array", "maxItems": 4, "items": {"type": "string", "maxLength": 160}}}}}}
PROMPT_SHA256 = hashlib.sha256((SYSTEM + json.dumps(SCHEMA, sort_keys=True)).encode()).hexdigest()


def locate(span, text):
    """(start, end, mode) of span in text: exact, else whitespace/case-insensitive; None if not found."""
    span = (span or "").strip()
    if len(span) < 2:
        return None
    i = text.find(span)
    if i >= 0:
        return i, i + len(span), "exact"
    toks = [re.escape(t) for t in re.split(r"\s+", span) if t]
    if not toks:
        return None
    m = re.search(r"\s*".join(toks) if len(toks) == 1 else r"\s+".join(toks), text, re.I)
    if m:
        return m.start(), m.end(), "normalised"
    return None


def verify(win, ans):
    out = {}
    for fld in ("dna_extraction", "sequencing_platform"):
        a = ans.get(fld) or {}
        spans = []
        for s in a.get("spans") or []:
            loc = locate(s, win["text"])
            spans.append({"span": s, "verified": bool(loc), "match": loc[2] if loc else None,
                          "start": win["start"] + loc[0] if loc else None, "end": win["start"] + loc[1] if loc else None})
        rec = {"status": a.get("status"), "spans": spans}
        if fld == "dna_extraction":
            ct = a.get("cited_text") or ""
            loc = locate(ct, win["text"])
            rec["cited_text"] = ct
            rec["cited_verified"] = bool(loc)
            rec["cited_start"] = win["start"] + loc[0] if loc else None
            rec["cited_end"] = win["start"] + loc[1] if loc else None
        out[fld] = rec
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--nshards", type=int, default=1)
    ap.add_argument("--parallel", type=int, default=32)
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args(argv)
    wins = [json.loads(l) for l in open(G.OUT / "windows.jsonl", encoding="utf-8")]
    wins = [w for i, w in enumerate(wins) if i % a.nshards == a.shard]
    if a.limit:
        wins = wins[:a.limit]
    a.out.mkdir(parents=True, exist_ok=True)
    path = a.out / f"llm_extract.shard{a.shard}.jsonl"
    done = set()
    if path.exists():
        done = {j["window_id"] for j in map(json.loads, open(path, encoding="utf-8")) if "error" not in j}
    todo = [w for w in wins if w["window_id"] not in done]
    print(f"shard {a.shard}: {len(wins)} windows, {len(todo)} to do; prompt {PROMPT_SHA256[:12]}", flush=True)

    def ask(w):
        body = {"model": MODEL, "temperature": 0, "seed": 0, "max_tokens": 1200,
                "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": "PASSAGE:\n" + w["text"]}],
                "chat_template_kwargs": {"enable_thinking": False},
                "response_format": {"type": "json_schema", "json_schema": {"name": "fields", "schema": SCHEMA, "strict": True}}}
        err = None
        for _ in range(3):
            try:
                req = urllib.request.Request(a.host.rstrip("/") + "/v1/chat/completions", data=json.dumps(body).encode(),
                                             headers={"Content-Type": "application/json"})
                r = json.loads(urllib.request.urlopen(req, timeout=600).read())
                txt = r["choices"][0]["message"].get("content") or "{}"
                ans = json.loads(txt, strict=False)
                return {"window_id": w["window_id"], "paper_id": w["paper_id"], "section_id": w["section_id"],
                        "win_start": w["start"], "win_end": w["end"], "raw": ans, **verify(w, ans),
                        "finish": r["choices"][0].get("finish_reason"), "model": MODEL, "prompt_sha256": PROMPT_SHA256}
            except Exception as ex:  # noqa: BLE001
                err = repr(ex)[:200]
        return {"window_id": w["window_id"], "paper_id": w["paper_id"], "error": err}

    t0 = time.time()
    with open(path, "a", encoding="utf-8") as fh, ThreadPoolExecutor(a.parallel) as pool:
        for i, res in enumerate(pool.map(ask, todo)):
            fh.write(json.dumps(res, ensure_ascii=False) + "\n")
            if i % 100 == 0:
                fh.flush()
                print(f"  {i}/{len(todo)} {time.time() - t0:.0f}s", flush=True)
    print("done", round(time.time() - t0), "s", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
