#!/usr/bin/env python3
"""Targeted repair of FAILED catalogue-NER requests — without rerunning good ones.

Why a separate tool from `repair_sections_cache.py`
---------------------------------------------------
`catalogue_ner.py` stores `{"error": ...}` for every request that raised, and
its resume path *does* retry those. But it retries them with the SAME
`MAX_SPLIT_DEPTH` / `SPLIT_MIN_CHARS` that already failed, so a resubmit of the
production launcher reproduces the identical failures and burns GPU time to
reach the same 127 errors. Retuning is what is needed, and retuning is
cache-safe: neither constant is part of `cache_key()` (verified — see the
`cache_key` body: text, system prompt, user-prompt skeleton, model,
temperature, `LLM_MAX_TOKENS`, `LLM_PROMPT_VERSION`).

Diagnosis of the 127 errored requests in `outputs/results/catalogue_ner_v2`
------------------------------------------------------------------
* Every one is `ValueError('response truncated by max_tokens
  (finish_reason=length)')` — the model emits until it exhausts the 4096-token
  budget, so the failure is *output* length, not input length.
* 124/127 are the `findings` group (the densest entity type), 2 `cohorts`,
  1 `datasets`; 74 are `full`-section requests and 53 are 4k `segment` requests
  spanning 2092–19961 chars.
* `SPLIT_MIN_CHARS = 1500` gates halving at `len(text) < 2 * 1500 = 3000`, so
  the 2092-char leaf cannot be split at all, and every other leaf bottomed out
  at depth 3 having still truncated. A 600-char floor keeps repaired leaves at
  sentence-to-paragraph scale (a findings record needs a clause, not a token).

What this tool does
-------------------
Re-attempts only the errored keys, but halves the passage **finer and deeper**
(`--split_min_chars` 600, `--split_depth` 6 by default) so each request returns
a short JSON body that fits inside the original 4096-token budget. **The token
budget is deliberately NOT raised**: `LLM_MAX_TOKENS` is hashed into the cache
key, so changing it would re-key the entire plan and orphan all 32,508 good
entries. Halving changes nothing in the key.

Results are written back under the **original** plan key, merged with the
runner's own `VLLMClient._merge` (content-signature dedupe across the seam), so
a later `--assemble_only` pass picks them up unchanged.

Honesty rules
-------------
* Nothing is invented: a record set is only stored when it came from a model
  response; a leaf that still fails propagates its error and the section stays
  `REVIEW_REQUIRED_INCOMPLETE`.
* `complete` is recorded per repaired key, and any partial/failed target is
  reported and listed — never silently counted as coverage.

Usage
-----
    python src/scripts/vllm_termpop/repair_catalogue_cache.py \
        --model Qwen/Qwen3.5-4B --host http://127.0.0.1:8000 \
        --output_dir outputs/results/catalogue_ner_v2 --assemble_only_after

    # list targets, no API calls:
    python src/scripts/vllm_termpop/repair_catalogue_cache.py --dry_run
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO_ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())

DEFAULT_SPLIT_DEPTH = 6
DEFAULT_SPLIT_MIN_CHARS = 600
DEFAULT_CALL_BUDGET = 32  # per target, counting every HTTP request
DEFAULT_LEAF_RETRIES = 1  # attempts at a given size before splitting again


_WS_RE = re.compile(r"\s+")


def best_cut(text):
    """Offset at which to halve `text`, or -1 when no usable boundary exists.

    This mirrors `catalogue_ner.best_cut` exactly. It is re-stated here because
    this module loads `catalogue_ner` through `importlib` rather than importing
    it, so the runner's helper is not reachable as a module attribute at
    definition time. `test_matches_runner` in the docstring below is the
    invariant: if the two ever diverge, repaired spans and freshly extracted
    spans would be split at different offsets.
    """
    if len(text) < 2:
        return -1
    half = len(text) // 2
    cut = text.rfind(" ", 0, half)
    if cut > 0:
        return cut
    cut = -1
    for m in _WS_RE.finditer(text):
        if m.end() > half:
            break
        cut = m.end()
    if cut > 0:
        return cut
    return half if 0 < half < len(text) else -1


def is_truncation(ex):
    """True only for the runner's max_tokens truncation signal.

    `catalogue_ner.VLLMClient.chat` raises
    `ValueError("response truncated by max_tokens (finish_reason=length)")` and
    nothing else of that shape, so a strict check keeps timeouts/HTTP errors out
    of the halving path.
    """
    return isinstance(ex, ValueError) and "finish_reason=length" in str(ex)


def load_runner():
    """Import the production catalogue runner (no edits, no argv side effects)."""
    spec = importlib.util.spec_from_file_location(
        "catalogue_ner", REPO_ROOT / "src/scripts" / "vllm_termpop" / "catalogue_ner.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def write_json_atomic(path, obj):
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


class Repairer:
    """Recursive halving that keeps the ORIGINAL token budget and key."""

    def __init__(self, mod, client, depth, min_chars, call_budget, leaf_retries=0):
        self.mod = mod
        self.client = client
        self.depth = depth
        self.min_chars = min_chars
        self.call_budget = call_budget
        self.leaf_retries = max(0, int(leaf_retries))
        self.calls = 0
        self.retried_ok = 0  # successes that needed >1 attempt at the same size
        # Per-node accounting, so a split-mode run can still report whether
        # retries mattered. `attempts` in the info dict is per-node and only
        # meaningful for `direct`; these totals aggregate the whole tree.
        # A "node" is one passage the tree decided to ask about, whether or not
        # it ultimately fit — failed nodes are counted too, otherwise the
        # totals would silently exclude the expensive ones.
        self.nodes_asked = 0
        self.nodes_ok = 0
        self.attempts_total = 0
        self.max_attempts_used = 0

    def _record_node(self, tries, ok):
        """Account for one tree node after its retries are spent."""
        self.nodes_asked += 1
        if ok:
            self.nodes_ok += 1
            if tries > 1:
                self.retried_ok += 1
        self.attempts_total += tries
        self.max_attempts_used = max(self.max_attempts_used, tries)

    def _chat_once(self, text, group):
        if self.calls >= self.call_budget:
            raise RuntimeError("call budget exhausted for this target")
        self.calls += 1
        return self.client.chat(text, group)

    def repair(self, text, group, depth=0):
        """Return (records_dict, info). Raises only if nothing was recovered.

        A truncation at `temperature=0` is not reproducible call-for-call: vLLM
        is not bit-deterministic, so the same passage can overflow the output
        budget once and fit on a fresh decode. That is measured, not assumed —
        pass 1 (job 28663289) repaired 3 of its 127 targets with mode `direct`,
        i.e. a clean retry at the ORIGINAL size, and the read-only probe (job
        28663870) resolved 30 of 32 by re-asking. `leaf_retries` therefore
        re-asks at the same size before paying for a split.

        Cost is bounded by `call_budget`, and a target that still cannot fit is
        reported failed rather than silently partial — fail-closed is preserved.
        """
        last = None
        tries = 0
        for attempt in range(self.leaf_retries + 1):
            before = self.calls
            try:
                recs = self._chat_once(text, group)
            except Exception as ex:  # noqa: BLE001 — classify below
                # Count the attempt only if a request was actually issued;
                # budget exhaustion raises before `client.chat`, so counting it
                # would break `attempts_total == api_calls`.
                if self.calls > before:
                    tries += 1
                last = ex
                # Only OUTPUT-truncation is worth re-asking or halving. A
                # transport/timeout error would just be multiplied, so it
                # propagates unchanged and is reported as still-failed.
                if not is_truncation(last):
                    if tries:
                        self._record_node(tries, ok=False)
                    raise RuntimeError(repr(last))
                continue
            tries += 1
            self._record_node(tries, ok=True)
            return recs, {"mode": "direct", "complete": True, "attempts": attempt + 1}

        # Node exhausted its retries without fitting. Account for the attempts
        # before giving up on it, so `attempts_total` counts every API call the
        # tree made rather than only the ones that ended in a success. Skipped
        # when the budget was already spent (no request issued, nothing to count).
        if tries:
            self._record_node(tries, ok=False)

        if depth >= self.depth or len(text) < 2 * self.min_chars:
            raise RuntimeError(repr(last))

        cut = best_cut(text)
        if cut <= 0 or len(text) - cut < self.min_chars:
            raise RuntimeError(repr(last))
        if self.calls >= self.call_budget:
            raise RuntimeError("call budget exhausted while splitting")

        left, li = self.repair(text[:cut], group, depth + 1)
        right, ri = self.repair(text[cut:], group, depth + 1)
        merged = self.client._merge([left, right], group)
        return merged, {
            "mode": "split", "depth": depth, "cut": cut,
            "complete": bool(li.get("complete")) and bool(ri.get("complete")),
        }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", default="Qwen/Qwen3.5-4B")
    ap.add_argument("--host", default="http://127.0.0.1:8000")
    ap.add_argument("--output_dir", default="outputs/results/catalogue_ner_v2")
    ap.add_argument("--seg_dir", default=None)
    ap.add_argument("--full_section_max_chars", type=int, default=None)
    ap.add_argument("--request_timeout", type=float, default=600.0)
    ap.add_argument("--parallel", type=int, default=16)
    ap.add_argument("--split_depth", type=int, default=DEFAULT_SPLIT_DEPTH)
    ap.add_argument("--split_min_chars", type=int, default=DEFAULT_SPLIT_MIN_CHARS)
    ap.add_argument("--call_budget", type=int, default=DEFAULT_CALL_BUDGET)
    ap.add_argument("--leaf_retries", type=int, default=DEFAULT_LEAF_RETRIES,
                    help="fresh attempts at the same size before splitting; temp=0 vLLM "
                         "is not bit-deterministic, so a truncation often fits on retry")
    ap.add_argument("--keys", default=None,
                    help="optional file of cache keys to repair (default: every errored key)")
    ap.add_argument("--max_targets", type=int, default=None)
    ap.add_argument("--dry_run", action="store_true", help="list targets, no API calls, no writes")
    ap.add_argument("--assemble_only_after", action="store_true",
                    help="rebuild the CSV tables + summary from the cache once repairs finish")
    args = ap.parse_args()

    mod = load_runner()
    out_dir = Path(args.output_dir)
    cache_path = out_dir / "_catalogue_cache.json"
    if not cache_path.exists():
        print("ERROR: no cache at %s" % cache_path)
        return 2

    seg_dir = args.seg_dir or str(mod.SEG_DIR_DEFAULT)
    full_max = args.full_section_max_chars or mod.FULL_SECTION_MAX_CHARS

    # Rebuild the plan EXACTLY as catalogue_ner.main() does (same key function),
    # so repaired entries land under keys the assemble pass will read.
    units, _ = mod.load_sections(seg_dir, None, body_only=False)
    sec_text, jobs = {}, []
    for u in units:
        key0 = (u["cid"], u["section_id"])
        text = u["text"] or ""
        sec_text[key0] = text
        for s, e, mode in mod.segment_section(text, full_max):
            for group in [[x] for x in mod.ENTITY_SPECS]:
                jobs.append({"cid": u["cid"], "sid": u["section_id"], "path": u["path"],
                             "s": s, "e": e, "mode": mode, "group": group,
                             "key": mod.cache_key(text[s:e], args.model, group)})

    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    errored = [j for j in jobs
               if isinstance(cache.get(j["key"]), dict) and cache[j["key"]].get("error")]
    planned = {j["key"] for j in jobs}
    stale = sum(1 for k, v in cache.items()
                if isinstance(v, dict) and v.get("error") and k not in planned)

    targets = errored
    if args.keys:
        want = {ln.strip() for ln in Path(args.keys).read_text().splitlines() if ln.strip()}
        targets = [j for j in errored if j["key"] in want]
        missing = len(want - {j["key"] for j in errored})
        if missing:
            print("WARNING: %d requested keys are not errored in the plan (ignored)" % missing)
    if args.max_targets:
        targets = targets[: args.max_targets]

    from collections import Counter
    print("plan requests: %d | errored in plan: %d | stale errored keys outside plan: %d "
          "| targets: %d" % (len(jobs), len(errored), stale, len(targets)))
    print("errored sections: %d | papers: %d"
          % (len({(j["cid"], j["sid"]) for j in errored}), len({j["cid"] for j in errored})))
    print("groups: %s" % json.dumps(dict(Counter(j["group"][0] for j in errored))))
    print("split policy: depth=%d min_chars=%d max_tokens=%d (UNCHANGED — key-safe)"
          % (args.split_depth, args.split_min_chars, mod.LLM_MAX_TOKENS))

    if args.dry_run:
        for j in sorted(targets, key=lambda x: -(x["e"] - x["s"]))[:50]:
            print("  %s %-16s %-24s %-7s %5d chars %s"
                  % (j["cid"], j["sid"], (j["path"] or "")[:24], j["mode"],
                     j["e"] - j["s"], j["group"][0]))
        return 0
    if not targets:
        print("nothing to repair")
        if args.assemble_only_after:
            _assemble(mod, args, out_dir, full_max)
        return 0

    client = mod.VLLMClient(args.host, args.model, timeout=args.request_timeout)
    import threading
    lock = threading.Lock()
    repaired, partial, still_failed = {}, [], []
    t0 = time.time()

    def work(job):
        rp = Repairer(mod, client, args.split_depth, args.split_min_chars,
                      args.call_budget, args.leaf_retries)
        try:
            recs, info = rp.repair(sec_text[(job["cid"], job["sid"])][job["s"]:job["e"]],
                                   job["group"])
            return job, recs, info, None, rp
        except Exception as ex:  # noqa: BLE001 — record, never kill the worker
            return job, None, None, str(ex), rp

    total_calls = 0
    total_nodes_asked = 0
    total_nodes_ok = 0
    total_attempts = 0
    total_retried_ok = 0
    max_attempts_used = 0
    with ThreadPoolExecutor(args.parallel) as pool:
        for done, (job, recs, info, err, rp) in enumerate(pool.map(work, targets), 1):
            total_calls += rp.calls
            total_nodes_asked += rp.nodes_asked
            total_nodes_ok += rp.nodes_ok
            total_attempts += rp.attempts_total
            total_retried_ok += rp.retried_ok
            max_attempts_used = max(max_attempts_used, rp.max_attempts_used)
            if recs is None:
                still_failed.append((job["key"], job["cid"], job["sid"], job["group"][0], err))
            else:
                info = dict(info)
                info.update({"repaired_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                             "tool": "repair_catalogue_cache.py",
                             "model": args.model,
                             "prompt_version": mod.LLM_PROMPT_VERSION,
                             "max_tokens": mod.LLM_MAX_TOKENS,
                             "split_depth": args.split_depth,
                             "split_min_chars": args.split_min_chars,
                             "call_budget": args.call_budget,
                             "leaf_retries": args.leaf_retries})
                with lock:
                    cache[job["key"]] = {"records": recs, "cid": job["cid"],
                                         "sid": job["sid"], "s": job["s"],
                                         "e": job["e"], "group": job["group"],
                                         "repair": info}
                repaired[job["key"]] = info
                if not info.get("complete"):
                    partial.append((job["key"], job["cid"], job["sid"], job["group"][0],
                                    info.get("mode")))
            if done % 5 == 0 or done == len(targets):
                write_json_atomic(cache_path, cache)
                print("  %d/%d repaired (%.0fs, ok=%d, partial=%d, failed=%d)"
                      % (done, len(targets), time.time() - t0, len(repaired),
                         len(partial), len(still_failed)), flush=True)

    write_json_atomic(cache_path, cache)

    modes = Counter(i["mode"] for i in repaired.values())
    report = {
        "tool": "repair_catalogue_cache.py",
        "output_dir": str(out_dir),
        "model": args.model,
        "prompt_version": mod.LLM_PROMPT_VERSION,
        "max_tokens_unchanged": mod.LLM_MAX_TOKENS,
        "split_depth": args.split_depth,
        "split_min_chars": args.split_min_chars,
        "call_budget": args.call_budget,
        "leaf_retries": args.leaf_retries,
        "api_calls": total_calls,
        # Retry accounting. Passes 1-5 recorded only `modes`, so the claim
        # "retries recovered nothing" could not be checked against an artifact
        # for split-mode trees — only `direct` nodes store a per-node
        # `attempts`. These totals make it checkable from the next run on.
        # Invariants: nodes_ok + nodes_failed == nodes_asked, and
        # attempts_total == api_calls (every call belongs to exactly one node).
        "nodes_asked": total_nodes_asked,
        "nodes_ok": total_nodes_ok,
        "nodes_failed": total_nodes_asked - total_nodes_ok,
        "attempts_total": total_attempts,
        "retried_ok": total_retried_ok,
        "max_attempts_used": max_attempts_used,
        "retry_supplied_successes": bool(total_retried_ok),
        "attempts_match_calls": total_attempts == total_calls,
        "plan_requests": len(jobs),
        "errored_in_plan_at_start": len(errored),
        "stale_errored_keys_outside_plan": stale,
        "targets": len(targets),
        "repaired": len(repaired),
        "repaired_complete": len(repaired) - len(partial),
        "repaired_partial": len(partial),
        "still_failed": len(still_failed),
        "modes": dict(modes),
        "still_failed_targets": [
            {"key": k, "paper": c, "section": s, "group": g, "error": e}
            for k, c, s, g, e in still_failed
        ],
        "partial_targets": [
            {"key": k, "paper": c, "section": s, "group": g, "mode": m}
            for k, c, s, g, m in partial
        ],
        "elapsed_sec": round(time.time() - t0, 1),
    }
    write_json_atomic(out_dir / "_catalogue_repair_report.json", report)

    print("\nrepair complete: %d ok (%d complete, %d partial), %d still failed"
          % (len(repaired), report["repaired_complete"], len(partial), len(still_failed)))
    print("modes: %s" % json.dumps(dict(modes)))
    if still_failed:
        print("still-failed targets (reported, not hidden):")
        for k, c, s, g, e in still_failed[:10]:
            print("  %s/%s [%s]  %s" % (c, s, g, (e or "")[:110]))

    if args.assemble_only_after:
        _assemble(mod, args, out_dir, full_max)

    return 0 if not still_failed else 1


def _assemble(mod, args, out_dir, full_max):
    """Rebuild CSV tables + summary from the checkpoint (no API calls)."""
    print("\nassembling from cache (catalogue_ner --assemble_only) ...")
    argv_backup = sys.argv[:]
    try:
        sys.argv = ["catalogue_ner.py",
                    "--model", args.model,
                    "--host", args.host,
                    "--output_dir", str(out_dir),
                    "--full_section_max_chars", str(full_max),
                    "--assemble_only"]
        mod.main()
    finally:
        sys.argv = argv_backup


if __name__ == "__main__":
    raise SystemExit(main())
