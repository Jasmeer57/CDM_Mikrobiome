#!/usr/bin/env python3
"""Targeted repair of FAILED vLLM NER segments — without rerunning good segments.

Background / diagnosis
----------------------
`qwen_sections_vllm.py` checkpoints per-segment results in
`_vllm_sections_cache.json` keyed by `cache_key(segment_text, model)`. A segment
whose response cannot be parsed is stored as `{"entities": None, "error": ...}`
and is re-attempted on every resubmit.

For the `body` run (~4,051 segments) ~46 segments fail persistently. The failure
signature is *not* entity density — it is:

  * output truncates at ~9.0k-13.5k **chars regardless of input length**
    (a 2,866-char input fails at output char 10,365; a 19,967-char input fails
    at char 10,297), i.e. the model emits until it exhausts `max_tokens`; and
  * the `split:` retry fails at the **identical char position**, i.e. the
    failure is deterministic, so halving the input cannot recover it.

Two defects in the production runner contribute:

  1. `VLLMClient.chat()` calls `json.loads(content)` *before* checking
     `finish_reason == "length"`, so a max_tokens truncation surfaces as an
     opaque `JSONDecodeError` instead of an informative truncation error.
  2. `MAX_SPLIT_DEPTH = 3` / `SPLIT_MIN_CHARS = 400` are too small for the
     pathological segments.

What this script does
---------------------
It rebuilds the *deterministic* segment plan (same code path as the runner), so
each errored cache key is mapped back to its exact segment text — the cache does
not store the text, only its hash. It then re-attempts **only those segments**
with:

  * an escalating output budget (`--max_tokens_ladder`, default 6144=12288);
  * a corrected check order (finish_reason first);
  * salvage of complete `{"text","type"}` objects from a truncated response;
  * deeper, finer recursive splitting (default depth 4, floor 250 chars);
  * a hard per-segment API-call budget so a pathological input terminates.

Results are written back **under the original cache key** (computed with the
runner's own constants, so a later runner invocation reuses them), preserving
every pre-existing entry. Each repaired entry carries a `repair` provenance
block recording the mode actually used and whether the result is complete.

Honesty rules
-------------
* Nothing is fabricated: an entity list is only stored when it came from a model
  response, and `complete=False` is recorded whenever the result is recovered
  from a truncated response instead of a full one.
* If any repaired segment is partial, the run summary is downgraded to
  `REVIEW_REQUIRED` and the partial segments are listed — it is never reported
  as clean coverage.

This script never scans the paper corpus itself and never touches `data_*`,
`releases/zenodo_v1/` or existing canonical records.

Usage
-----
    python src/scripts/vllm_termpop/repair_sections_cache.py \
        --model Qwen/Qwen3.5-4B --host http://127.0.0.1:8000 \
        --output_dir outputs/results/llm_ner_body --section_filter body

    # list what would be repaired, no API calls:
    python src/scripts/vllm_termpop/repair_sections_cache.py --dry_run

    # repair, then regenerate CSV + summary from the cache:
    python src/scripts/vllm_termpop/repair_sections_cache.py ... --assemble
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_LADDER = (6144, 12288)
DEFAULT_MAX_SPLIT_DEPTH = 4
DEFAULT_SPLIT_MIN_CHARS = 250
DEFAULT_CALL_BUDGET = 24  # per segment, counting every HTTP request


def load_runner():
    """Import the production runner as a module (no edits, no argv side effects)."""
    spec = importlib.util.spec_from_file_location(
        "qwen_sections_vllm", REPO_ROOT / "src/scripts" / "vllm_termpop" / "qwen_sections_vllm.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── truncation-tolerant parsing ────────────────────────────────────────────────

def scan_top_level_objects(raw):
    """Return every complete `{...}` text at brace depth 0, string-aware.

    A truncated JSON array cannot be `json.loads`-ed, but every entity object
    that was fully emitted before the cut can still be recovered. This scanner
    tracks string/escape state so braces inside entity text do not confuse it.
    """
    objs, start, depth = [], None, 0
    in_str = esc = False
    for i, ch in enumerate(raw):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start is not None:
                    objs.append(raw[start:i + 1])
                    start = None
    return objs


def salvage_entities(raw):
    """Complete entity objects recoverable from a (possibly truncated) response."""
    ents = []
    for obj in scan_top_level_objects(raw or ""):
        try:
            d = json.loads(obj)
        except Exception:
            continue
        if isinstance(d, dict) and (d.get("text") or "").strip():
            ents.append(d)
    return dedupe(ents)


def dedupe(ents):
    """Order-preserving dedupe by (text, type).

    Safe: downstream assembly de-duplicates by character span anyway, so a
    repeated (text, type) contributes nothing new.
    """
    out, seen = [], set()
    for e in ents or []:
        if not isinstance(e, dict):
            continue
        t = (e.get("text") or "").strip()
        if not t:
            continue
        k = (t, e.get("type", ""))
        if k in seen:
            continue
        seen.add(k)
        out.append({"text": t, "type": e.get("type", "")})
    return out


# ── client (same transport as production, but returns raw + finish_reason) ────

class RepairClient:
    def __init__(self, host, model, timeout=600):
        self.host = host.rstrip("/")
        self.model = model
        self.timeout = timeout

    def call(self, text, max_tokens):
        """Return (raw_content, finish_reason) — no parsing, no swallowing."""
        body = json.dumps({
            "model": self.model,
            "messages": [{"role": "system", "content": _M.SYSTEM_PROMPT},
                         {"role": "user", "content": _M.user_prompt(text)}],
            "temperature": _M.LLM_TEMPERATURE,
            "max_tokens": max_tokens,
            "chat_template_kwargs": {"enable_thinking": False},
            "response_format": {"type": "json_object"},
        }).encode("utf-8")
        req = urllib.request.Request(
            self.host + "/v1/chat/completions", data=body,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            data = json.loads(resp.read())
        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        raw = msg.get("content") or ""
        if not raw and msg.get("reasoning_content"):
            raw = msg["reasoning_content"]
        return raw, choice.get("finish_reason")


# ── per-segment repair ────────────────────────────────────────────────────────

class Repairer:
    def __init__(self, client, ladder, max_depth, split_min_chars, call_budget):
        self.client = client
        self.ladder = tuple(ladder)
        self.max_depth = max_depth
        self.split_min_chars = split_min_chars
        self.call_budget = call_budget
        self._local = threading.local()

    def _calls(self):
        # per-thread counter for the segment currently being repaired
        return getattr(self._local, "n", 0)

    def _bump(self):
        self._local.n = self._calls() + 1
        if self._local.n > self.call_budget:
            raise RuntimeError("call budget exhausted for segment")

    def repair(self, text, depth=0):
        """Return (entities, info). Raises only if nothing at all was recovered."""
        best_salvage, best_budget, last_err = [], None, None

        for mt in self.ladder:
            try:
                self._bump()
                raw, finish = self.client.call(text, mt)
            except RuntimeError:
                raise
            except Exception as ex:  # noqa: BLE001 — record and try next rung
                last_err = repr(ex)
                continue

            if finish == "length":
                salv = salvage_entities(raw)
                if len(salv) > len(best_salvage):
                    best_salvage, best_budget = salv, mt
                last_err = "truncated (finish_reason=length) at max_tokens=%d" % mt
                continue

            # not truncated -> full response
            try:
                ents = json.loads(raw).get("entities", [])
            except Exception:
                ents = salvage_entities(raw)
                if ents:
                    return ents, {"mode": "salvaged", "max_tokens": mt,
                                  "complete": False, "note": "unparseable response; "
                                  "complete objects recovered"}
                last_err = "response not valid JSON and nothing salvageable"
                continue
            if isinstance(ents, list):
                return dedupe(ents), {"mode": "escalated", "max_tokens": mt,
                                      "complete": True}
            last_err = "response JSON had no 'entities' list"

        # every budget truncated (or errored) -> split finer, with the top budget
        if depth < self.max_depth and len(text) >= self.split_min_chars:
            cut = text.rfind(" ", 0, len(text) // 2)
            if cut < self.split_min_chars:
                cut = len(text) // 2
            if 0 < cut < len(text):
                left, li = self.repair(text[:cut], depth + 1)
                right, ri = self.repair(text[cut:], depth + 1)
                return left + right, {
                    "mode": "split", "depth": depth, "cut": cut,
                    "complete": bool(li.get("complete")) and bool(ri.get("complete")),
                    "children": [li, ri],
                }

        if best_salvage:
            return best_salvage, {"mode": "salvaged", "max_tokens": best_budget,
                                  "complete": False,
                                  "note": "recovered from truncated response"}
        raise RuntimeError(last_err or "no result")


# ── plan reconstruction + cache update ────────────────────────────────────────

def build_plan(mod, seg_dir, max_files, section_filter, full_max_chars, model):
    units, _ = mod.load_sections(seg_dir, max_files, body_only=False)
    if section_filter == "cell7c":
        units = [u for u in units if not mod.is_backmatter(u["path"])]
    elif section_filter == "body":
        units = [u for u in units if not mod._is_cpu_backmatter(u["path"])]

    sec_text, jobs = {}, []
    for u in units:
        key = (u["cid"], u["section_id"])
        text = u["text"] or ""
        sec_text[key] = text
        for s, e, _mode in mod.segment_section(text, full_max_chars):
            jobs.append((u["cid"], u["section_id"], s, e, mod.cache_key(text[s:e], model)))
    return sec_text, jobs


def write_json_atomic(path, obj):
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", default="Qwen/Qwen3.5-4B")
    ap.add_argument("--host", default="http://127.0.0.1:8000")
    ap.add_argument("--output_dir", default="outputs/results/llm_ner_body")
    ap.add_argument("--seg_dir", default=None, help="defaults to the runner's SEG_DIR_DEFAULT")
    ap.add_argument("--max_files", type=int, default=None)
    ap.add_argument("--section_filter", choices=("cell7c", "body", "all"), default="body")
    ap.add_argument("--full_section_max_chars", type=int, default=None)
    ap.add_argument("--max_tokens_ladder", default=",".join(map(str, DEFAULT_LADDER)),
                    help="comma-separated output budgets tried in order")
    ap.add_argument("--max_split_depth", type=int, default=DEFAULT_MAX_SPLIT_DEPTH)
    ap.add_argument("--split_min_chars", type=int, default=DEFAULT_SPLIT_MIN_CHARS)
    ap.add_argument("--call_budget", type=int, default=DEFAULT_CALL_BUDGET)
    ap.add_argument("--parallel", type=int, default=16)
    ap.add_argument("--keys", default=None,
                    help="optional file of cache keys to repair (default: all errored in plan)")
    ap.add_argument("--dry_run", action="store_true", help="list targets, no API calls, no writes")
    ap.add_argument("--assemble", action="store_true",
                    help="after repairing, re-run the production runner to rebuild CSV/summary")
    args = ap.parse_args()

    global _M
    _M = load_runner()

    seg_dir = args.seg_dir or str(_M.SEG_DIR_DEFAULT)
    full_max = args.full_section_max_chars or _M.FULL_SECTION_MAX_CHARS
    ladder = tuple(int(x) for x in args.max_tokens_ladder.split(",") if x.strip())

    out_dir = Path(args.output_dir)
    cache_path = out_dir / "_vllm_sections_cache.json"
    if not cache_path.exists():
        print("ERROR: cache not found: %s" % cache_path, file=sys.stderr)
        return 2

    # Refuse to write while a runner is mid-write (its atomic .tmp exists).
    if (out_dir / "_vllm_sections_cache.json.tmp").exists():
        print("ERROR: cache .tmp present — a runner looks active; try again after it exits.",
              file=sys.stderr)
        return 2

    sec_text, jobs = build_plan(_M, seg_dir, args.max_files, args.section_filter, full_max,
                                args.model)
    print("plan: %d segments across %d sections (filter=%s)"
          % (len(jobs), len(sec_text), args.section_filter))

    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    by_key = {j[4]: j for j in jobs}
    errored = [j for j in jobs if (cache.get(j[4]) or {}).get("error")]
    targets = errored
    if args.keys:
        want = {ln.strip() for ln in Path(args.keys).read_text().splitlines() if ln.strip()}
        targets = [j for j in jobs if j[4] in want]
    stale = sum(1 for k, v in cache.items()
                if isinstance(v, dict) and v.get("error") and k not in by_key)
    print("errored in plan: %d | errored cache keys outside plan (stale): %d | targets: %d"
          % (len(errored), stale, len(targets)))
    if not targets:
        print("nothing to repair.")
        return 0

    if args.dry_run:
        for cid, sid, s, e, key in sorted(targets, key=lambda j: -(j[3] - j[2]))[:50]:
            print("  %7d chars  %s/%s  %s" % (e - s, cid, sid, key[:16]))
        print("\ndry run: no API calls, no writes.")
        return 0

    client = RepairClient(args.host, args.model)
    rep = Repairer(client, ladder, args.max_split_depth, args.split_min_chars,
                   args.call_budget)

    t0 = time.time()
    done = 0
    repaired, still_failed, partial = {}, [], []
    lock = threading.Lock()

    def work(job):
        cid, sid, s, e, key = job
        text = sec_text[(cid, sid)][s:e]
        try:
            ents, info = rep.repair(text)
        except Exception as ex:  # noqa: BLE001
            return key, (cid, sid), None, {"error": repr(ex)}
        return key, (cid, sid), ents, info

    try:
        with ThreadPoolExecutor(args.parallel) as pool:
            for key, (cid, sid), ents, info in pool.map(work, targets):
                done += 1
                if ents is None:
                    still_failed.append((key, cid, sid, info["error"]))
                else:
                    info = dict(info)
                    info["repaired_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                    info["tool"] = "repair_sections_cache.py"
                    info["model"] = args.model
                    info["entities"] = len(ents)
                    with lock:
                        cache[key] = {"entities": ents, "repair": info}
                    repaired[key] = info
                    if not info.get("complete"):
                        partial.append((key, cid, sid, info))
                if done % 5 == 0 or done == len(targets):
                    write_json_atomic(cache_path, cache)
                    el = time.time() - t0
                    print("  %d/%d repaired (%.0fs, ok=%d, partial=%d, failed=%d)"
                          % (done, len(targets), el, len(repaired), len(partial),
                             len(still_failed)), flush=True)
    finally:
        write_json_atomic(cache_path, cache)

    report = {
        "tool": "repair_sections_cache.py",
        "output_dir": str(out_dir), "section_filter": args.section_filter,
        "model": args.model, "max_tokens_ladder": list(ladder),
        "max_split_depth": args.max_split_depth, "split_min_chars": args.split_min_chars,
        "targets": len(targets), "repaired": len(repaired),
        "repaired_complete": len(repaired) - len(partial),
        "repaired_partial": len(partial), "still_failed": len(still_failed),
        "still_failed_segments": [{"key": k, "paper": c, "section": s, "error": e}
                                  for k, c, s, e in still_failed],
        "partial_segments": [{"key": k, "paper": c, "section": s,
                              "mode": i.get("mode"), "max_tokens": i.get("max_tokens")}
                             for k, c, s, i in partial],
        "modes": {},
        "stale_errored_keys_outside_plan": stale,
        "elapsed_sec": round(time.time() - t0, 1),
    }
    for i in repaired.values():
        report["modes"][i["mode"]] = report["modes"].get(i["mode"], 0) + 1
    write_json_atomic(out_dir / "_repair_report.json", report)

    print("\nrepair complete: %d ok (%d complete, %d partial), %d still failed"
          % (len(repaired), report["repaired_complete"], len(partial), len(still_failed)))
    print("modes: %s" % json.dumps(report["modes"]))
    if still_failed:
        print("still-failed segments (reported, not hidden):")
        for k, c, s, e in still_failed[:10]:
            print("  %s/%s  %s" % (c, s, e[:110]))
    if partial:
        print("partial segments (recovered from truncated output):")
        for k, c, s, i in partial[:10]:
            print("  %s/%s  mode=%s" % (c, s, i.get("mode")))

    if args.assemble:
        print("\nre-running production runner to rebuild CSV/summary (cache-hit assembly) ...")
        argv_backup = sys.argv[:]
        try:
            sys.argv = ["qwen_sections_vllm.py", "--model", args.model, "--host", args.host,
                        "--output_dir", str(out_dir), "--section_filter", args.section_filter,
                        "--full_section_max_chars", str(full_max),
                        "--parallel", str(args.parallel)]
            if args.max_files is not None:
                sys.argv += ["--max_files", str(args.max_files)]
            _M.main()
        finally:
            sys.argv = argv_backup

        # Honesty: the runner computes coverage from segment errors only, so a
        # partial (salvage-recovered) segment would read as COMPLETE. Downgrade.
        if partial or still_failed:
            summ_path = out_dir / "_vllm_sections_summary.json"
            summ = json.loads(summ_path.read_text(encoding="utf-8"))
            summ["repair"] = {
                "repaired": len(repaired), "repaired_partial": len(partial),
                "still_failed": len(still_failed),
                "note": "coverage downgraded: repaired segments recovered from "
                        "truncated responses are not full extraction",
            }
            if summ.get("coverage", {}).get("coverage_status") == "COMPLETE" and (partial or still_failed):
                summ["coverage"]["coverage_status"] = "REVIEW_REQUIRED"
                summ["coverage"]["segments_repaired_partial"] = len(partial)
                summ["coverage"]["segments_still_failed"] = len(still_failed)
            summ_path.write_text(json.dumps(summ, indent=2), encoding="utf-8")
            print("summary downgraded honestly: partial=%d still_failed=%d"
                  % (len(partial), len(still_failed)))

    return 0 if not still_failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
