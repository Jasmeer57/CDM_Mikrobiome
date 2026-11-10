"""Within-paper linking of catalogue records (Phase B of
docs/catalogue_cleanup_plan.md), via a vLLM OpenAI-compatible server.

The extraction left every cross-entity key empty, so a finding links to its
paper but not to the cohort, assay or dataset it is about. This pass fills:

    cohorts.dataset_id
    samples.cohort_id, samples.dataset_id
    assays.dataset_id
    data_assets.dataset_id
    findings.cohort_id, findings.assay_id, findings.dataset_id

For each paper the model sees ONLY that paper's own candidate records (id plus
a one-line summary) and the items to link, and may answer only with those ids
or NONE. Any id not in the paper's candidate list is discarded, so a link can
never cross papers or point at a record that does not exist.

The same requests also settle two Phase A review items, stored next to the
rule-based value and never over it:
    findings marked is_primary_finding=REVIEW -> is_primary_finding_llm
    findings with a direction_flag            -> direction_llm
`is_primary_finding` is updated from the model only where the rule said REVIEW
(`is_primary_finding_source` = RULE | LLM). `direction` is never changed.

Checkpointed: every answered batch is cached by prompt hash, so a re-run
resumes. `--dry_run` builds every request and reports sizes without a server.

Usage (expects `vllm serve Qwen/Qwen3.5-4B --port 8000`):
    PYTHONPATH=src python src/scripts/vllm_termpop/link_catalogue.py \
        [--input_dir outputs/results/catalogue_v3_clean] \
        [--output_dir outputs/results/catalogue_v3_linked] [--max_papers N]
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
import time
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

csv.field_size_limit(sys.maxsize)

REPO_ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
ENTITIES = ("datasets", "data_assets", "cohorts", "samples", "assays", "findings")
ID_FIELD = {"datasets": "dataset_id", "data_assets": "asset_id", "cohorts": "cohort_id",
            "samples": "sample_group_id", "assays": "assay_id", "findings": "finding_id"}
# item entity -> the link columns it gets, each naming the candidate entity
LINKS = {
    "cohorts": {"dataset_id": "datasets"},
    "samples": {"cohort_id": "cohorts", "dataset_id": "datasets"},
    "assays": {"dataset_id": "datasets"},
    "data_assets": {"dataset_id": "datasets"},
    "findings": {"cohort_id": "cohorts", "assay_id": "assays", "dataset_id": "datasets"},
}
NEW_COLUMNS = {
    "_all": ["link_status", "link_run_id"],
    "findings": ["is_primary_finding_llm", "is_primary_finding_source", "direction_llm"],
}
DIRECTIONS = {"INCREASE", "DECREASE", "NO_ASSOCIATION", "MIXED", "NOT_STATED"}
PROMPT_VERSION = "cdm-catalogue-link-v2"
BATCH_ITEMS = 15
MAX_LINKS_PER_FIELD = 3
LLM_MAX_TOKENS = 4096

SYSTEM_PROMPT = """You link records that were extracted from ONE scientific paper about the human microbiome.

You get CANDIDATES (the paper's datasets, cohorts and assays, each with an id and a
short summary) and ITEMS (records to link). For every item, choose which candidate(s)
it belongs to.

RULES
1. Use ONLY ids from the CANDIDATES list. Never invent an id.
2. Link only when the item's own text or summary makes the link clear. If it is not
   clear, answer "NONE". A wrong link is worse than no link.
3. At most 3 ids per field. A finding comparing two groups may link both cohorts.
4. If a paper has a single cohort/dataset/assay and the item plainly concerns the
   study as a whole, that single candidate may be used.
5. Only for items that ask "primary": answer YES if the finding is a result of THIS
   paper's own data, NO if it reports background, prior literature or another
   study's result.
6. Only for items that ask "direction": give the direction the evidence text states
   for the finding, one of INCREASE, DECREASE, NO_ASSOCIATION, MIXED, NOT_STATED.
   NOT_STATED unless the text explicitly states it.
7. Answer EVERY item, one entry per item, in the same order. Leave a field out
   when the answer is NONE.
8. Return ONLY a JSON object in exactly this shape (no prose, no code fence):
   {"links": [
     {"id": "HMFINDING_000101", "cohort_id": ["HMCOHORT_000004"], "assay_id": ["HMASSAY_000002"]},
     {"id": "HMFINDING_000102", "primary": "NO"},
     {"id": "HMSAMPLE_000007", "cohort_id": ["HMCOHORT_000004", "HMCOHORT_000005"], "dataset_id": ["HMDATA_000001"]}
   ]}"""


def _clip(v, n):
    s = " ".join(str(v or "").split())
    return s if len(s) <= n else s[: n - 1] + "…"


def summarise(entity, f):
    """One-line candidate/item summary from the most identifying fields."""
    keys = {
        "datasets": ("dataset_title", "repository_normalized", "repository_name",
                     "repository_accession", "dataset_role"),
        "cohorts": ("cohort_label", "cohort_role", "population_description",
                    "health_status", "participant_count", "country_or_region"),
        "assays": ("assay_type", "target_gene_or_region", "sequencing_platform"),
        "samples": ("body_site", "sample_type", "collection_timepoint", "sample_count"),
        "data_assets": ("asset_name", "asset_type", "accession", "description"),
        "findings": ("taxon_or_feature", "direction", "outcome", "comparison_or_exposure",
                     "population_subgroup", "body_site"),
    }[entity]
    parts = [f"{k}={_clip(f.get(k), 80)}" for k in keys if str(f.get(k, "")).strip()]
    return "; ".join(parts)


def build_batches(paper_records, flagged=None):
    """-> list of request dicts for one paper (may be empty)."""
    by = defaultdict(list)
    for r in paper_records:
        by[r["entity_type"]].append(r)
    cand = {e: [{"id": r["fields"][ID_FIELD[e]], "summary": _clip(summarise(e, r["fields"]), 220)}
                for r in by[e]] for e in ("datasets", "cohorts", "assays")}
    batches = []
    for item_entity, fields in LINKS.items():
        fields = {fld: tgt for fld, tgt in fields.items() if cand[tgt]}
        if not fields or not by[item_entity]:
            continue
        items = []
        for r in by[item_entity]:
            if flagged is not None and r["fields"][ID_FIELD[item_entity]] not in flagged:
                continue
            f = r["fields"]
            it = {"id": f[ID_FIELD[item_entity]], "summary": _clip(summarise(item_entity, f), 260),
                  "evidence": _clip(f.get("evidence_text"), 300), "fields": list(fields)}
            if item_entity == "findings":
                if f.get("is_primary_finding") == "REVIEW":
                    it["fields"].append("primary")
                if f.get("direction_flag"):
                    it["fields"].append("direction")
            items.append(it)
        used = {tgt for tgt in fields.values()}
        for i in range(0, len(items), BATCH_ITEMS):
            chunk = items[i:i + BATCH_ITEMS]
            payload = {"CANDIDATES": {t: cand[t] for t in ("datasets", "cohorts", "assays") if t in used},
                       "ITEMS": [{"id": it["id"], "type": item_entity[:-1], "summary": it["summary"],
                                  "evidence": it["evidence"], "answer_fields": it["fields"]}
                                 for it in chunk]}
            batches.append({"paper_id": paper_records[0]["paper_id"], "entity": item_entity,
                            "fields": fields, "items": [it["id"] for it in chunk],
                            "user": json.dumps(payload, ensure_ascii=False)})
    return batches


V3_RULES = """
9. Prefer ONE id per field: give several only when the text explicitly compares or pools those groups.
10. A finding that reports another study's result (cited work, background) gets NONE for every field.
11. A data asset belongs to exactly one dataset of the paper: pick the dataset it is a file of."""


def flagged_items(records):
    """Suspect items for --only_flagged."""
    out = set()
    for r in records:
        e, f = r["entity_type"], r["fields"]
        rid = f[ID_FIELD[e]]
        multi = any(";" in str(f.get(k, "")) for k in ("dataset_id", "cohort_id", "assay_id")
                    if k != ID_FIELD[e])
        cited = e == "findings" and (f.get("cites_other_work") == "YES" or f.get("is_primary_finding") == "NO")
        orphan = e == "data_assets" and not str(f.get("dataset_id", "")).strip()
        if multi or cited or orphan:
            out.add(rid)
    return out


def batch_key(batch, model):
    h = hashlib.sha256()
    for part in (SYSTEM_PROMPT, batch["user"], model, PROMPT_VERSION):  # set by --prompt_version
        h.update(part.encode("utf-8"))
        h.update(b"\x1f")
    return h.hexdigest()


def chat(host, model, user, timeout):
    body = json.dumps({
        "model": model,
        "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                     {"role": "user", "content": user}],
        "temperature": 0, "max_tokens": LLM_MAX_TOKENS,
        "chat_template_kwargs": {"enable_thinking": False},
        "response_format": {"type": "json_object"},
    }).encode("utf-8")
    req = urllib.request.Request(host.rstrip("/") + "/v1/chat/completions", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read())
    choice = data["choices"][0]
    if choice.get("finish_reason") == "length":
        raise ValueError("response truncated (finish_reason=length)")
    return json.loads((choice.get("message") or {}).get("content") or "")


def normalise_answers(obj):
    """Every answer shape the model has produced -> {item_id: {field: value}}.

    Seen in practice: {"links": [{"id": X, ...}]} (asked for), {"links":
    [{X: {...}, Y: {...}}]} and {X: {...}} keyed by id, and bare strings.
    Anything that is not a dict keyed to an item is ignored.
    """
    out = {}

    def take(node):
        if isinstance(node, list):
            for x in node:
                take(x)
        elif isinstance(node, dict):
            if "id" in node and isinstance(node["id"], str):
                out[node["id"]] = node
            else:
                for k, v in node.items():
                    if isinstance(v, dict) and k.startswith("HM"):
                        out[k] = dict(v, id=k)
                    elif isinstance(v, (list, dict)):
                        take(v)

    take(obj.get("links", obj) if isinstance(obj, dict) else obj)
    return out


def split_batch(b):
    """Halve a batch whose answer did not fit in max_tokens."""
    payload = json.loads(b["user"])
    items = payload["ITEMS"]
    half = len(items) // 2
    parts = []
    for chunk in (items[:half], items[half:]):
        p = dict(payload, ITEMS=chunk)
        parts.append(dict(b, items=[i["id"] for i in chunk],
                          user=json.dumps(p, ensure_ascii=False)))
    return parts


def paper_ids(records):
    """{paper_id: {entity: set(ids)}} — the only ids a paper's links may use."""
    out = defaultdict(lambda: defaultdict(set))
    for r in records:
        out[r["paper_id"]][r["entity_type"]].add(r["fields"][ID_FIELD[r["entity_type"]]])
    return out


def apply_answers(batch, answers, records_by_id, valid_by_paper, run_id, stats):
    """Validate the model's answer against the paper's candidate ids and apply it."""
    valid = valid_by_paper[batch["paper_id"]]
    got = answers
    for item_id in batch["items"]:
        r = records_by_id[item_id]
        f = r["fields"]
        a = got.get(item_id)
        f["link_run_id"] = run_id
        if a is None:
            f["link_status"] = "NO_ANSWER"
            stats["items_no_answer"] += 1
            continue
        linked = False
        for fld, tgt in batch["fields"].items():
            v = a.get(fld)
            ids = v if isinstance(v, list) else ([v] if isinstance(v, str) else [])
            ok = [i for i in ids if i in valid[tgt]][:MAX_LINKS_PER_FIELD]
            bad = [i for i in ids if i not in valid[tgt] and str(i).upper() != "NONE"]
            stats[f"invalid_ids_dropped"] += len(bad)
            f[fld] = "; ".join(dict.fromkeys(ok))
            if ok:
                linked = True
                stats[f"{batch['entity']}.{fld}_linked"] += 1
        f["link_status"] = "LINKED" if linked else "NONE_CLEAR"
        if batch["entity"] == "findings":
            p = str(a.get("primary", "")).strip().upper()
            if f.get("is_primary_finding") == "REVIEW" and p in ("YES", "NO"):
                f["is_primary_finding_llm"] = p
                f["is_primary_finding"] = p
                f["is_primary_finding_source"] = "LLM"
                stats[f"primary_llm_{p}"] += 1
            d = str(a.get("direction", "")).strip().upper()
            if f.get("direction_flag") and d in DIRECTIONS:
                f["direction_llm"] = d
                stats["direction_llm_" + ("AGREES" if d == f.get("direction") else "DIFFERS")] += 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="Phase B within-paper linking")
    ap.add_argument("--input_dir", default=str(REPO_ROOT / "outputs/results/catalogue_v3_clean"))
    ap.add_argument("--output_dir", default=str(REPO_ROOT / "outputs/results/catalogue_v3_linked"))
    ap.add_argument("--model", default="Qwen/Qwen3.5-4B")
    ap.add_argument("--host", default="http://127.0.0.1:8000")
    ap.add_argument("--parallel", type=int, default=32)
    ap.add_argument("--request_timeout", type=float, default=600)
    ap.add_argument("--max_papers", type=int, default=None)
    ap.add_argument("--expected_papers", type=int, default=453)
    ap.add_argument("--dry_run", action="store_true", help="build requests, report sizes, exit")
    ap.add_argument("--only_flagged", action="store_true",
                    help="re-link only suspect items (cited/background findings, multi-id links, assets "
                         "without dataset); every other record keeps its links")
    ap.add_argument("--prompt_version", choices=["v2", "v3"], default="v2")
    args = ap.parse_args(argv)

    in_dir, out_dir = Path(args.input_dir), Path(args.output_dir)
    if out_dir.resolve() == in_dir.resolve():
        sys.exit("refusing to write into the input directory")
    with open(in_dir / "catalogue_records.jsonl", encoding="utf-8") as fh:
        records = [json.loads(line) for line in fh if line.strip()]
    papers = sorted({r["paper_id"] for r in records})
    if len(papers) != args.expected_papers:
        sys.exit(f"input covers {len(papers)} papers, expected {args.expected_papers}")
    if args.max_papers:
        papers = papers[:args.max_papers]
    keep = set(papers)
    by_paper = defaultdict(list)
    for r in records:
        if r["paper_id"] in keep:
            by_paper[r["paper_id"]].append(r)
    records_by_id = {r["fields"][ID_FIELD[r["entity_type"]]]: r for r in records}

    global SYSTEM_PROMPT, PROMPT_VERSION
    if args.prompt_version == "v3":
        SYSTEM_PROMPT, PROMPT_VERSION = SYSTEM_PROMPT + V3_RULES, "cdm-catalogue-link-v3"
    flagged = flagged_items(records) if args.only_flagged else None
    if flagged is not None:
        print(f"only_flagged: {len(flagged)} items")
    batches = [b for p in papers for b in build_batches(by_paper[p], flagged)]
    sizes = sorted(len(b["user"]) for b in batches)
    print(f"papers={len(papers)} batches={len(batches)} items={sum(len(b['items']) for b in batches)} "
          f"prompt chars median={sizes[len(sizes) // 2] if sizes else 0} max={sizes[-1] if sizes else 0}")
    if args.dry_run:
        print(json.dumps(Counter(b["entity"] for b in batches)))
        return 0

    out_dir.mkdir(parents=True, exist_ok=True)
    cache_path = out_dir / "_link_cache.json"
    cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
    run_id = "CATLINK_%s_%s" % (time.strftime("%Y%m%dT%H%M%S"), os.getpid())
    for b in batches:
        b["key"] = batch_key(b, args.model)
    todo = [b for b in batches if b["key"] not in cache or "error" in cache[b["key"]]]
    print(f"cached={len(batches) - len(todo)} to run={len(todo)}", flush=True)

    t0, done = time.time(), 0

    def ask(b, depth=0):
        """-> ({item_id: answer}, error). A truncated answer is retried as two halves."""
        last = None
        for _ in range(2):
            try:
                return normalise_answers(chat(args.host, args.model, b["user"], args.request_timeout)), None
            except Exception as ex:  # noqa: BLE001 — retry once, then split or record
                last = repr(ex)
                if "finish_reason=length" in last:
                    break
        if "finish_reason=length" in (last or "") and len(b["items"]) == 1:
            # one item whose answer still overflows: the model is looping on it.
            # That item gets no answer (link_status NO_ANSWER); the run goes on.
            return {}, None
        if "finish_reason=length" in (last or "") and len(b["items"]) > 1 and depth < 6:
            merged = {}
            for part in split_batch(b):
                ans, err = ask(part, depth + 1)
                if err:
                    return None, err
                merged.update(ans)
            return merged, None
        return None, last

    def run(b):
        ans, err = ask(b)
        return b["key"], ({"error": err} if err else {"answers": ans})

    with ThreadPoolExecutor(args.parallel) as pool:
        futs = [pool.submit(run, b) for b in todo]
        for fut in as_completed(futs):
            key, res = fut.result()
            cache[key] = res
            done += 1
            if done % 50 == 0 or done == len(todo):
                tmp = cache_path.with_suffix(".tmp")
                tmp.write_text(json.dumps(cache), encoding="utf-8")
                tmp.replace(cache_path)
                print(f"  {done}/{len(todo)} batches, {time.time() - t0:.0f}s, errors "
                      f"{sum(1 for v in cache.values() if 'error' in v)}", flush=True)

    stats = Counter()
    for r in records:
        f = r["fields"]
        f.setdefault("link_status", "NOT_RUN" if r["paper_id"] not in keep else "NO_CANDIDATES")
        f.setdefault("link_run_id", "")
        if r["entity_type"] == "findings":
            f.setdefault("is_primary_finding_llm", "")
            f.setdefault("is_primary_finding_source", "RULE")
            f.setdefault("direction_llm", "")
    valid_by_paper = paper_ids(records)
    for b in batches:
        res = cache.get(b["key"], {})
        if "error" in res:
            stats["batches_failed"] += 1
            for i in b["items"]:
                records_by_id[i]["fields"]["link_status"] = "REQUEST_FAILED"
            continue
        stats["batches_ok"] += 1
        apply_answers(b, res.get("answers", {}), records_by_id, valid_by_paper, run_id, stats)

    with open(out_dir / "catalogue_records.jsonl", "w", encoding="utf-8") as fh:
        for r in records:
            r["link_prompt_version"] = PROMPT_VERSION
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    for e in ENTITIES:
        with open(in_dir / f"catalogue_{e}.csv", newline="", encoding="utf-8") as fh:
            header = next(csv.reader(fh))
        cols = header + [c for c in NEW_COLUMNS["_all"] + NEW_COLUMNS.get(e, []) if c not in header]
        with open(out_dir / f"catalogue_{e}.csv", "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            w.writerows(r["fields"] for r in records if r["entity_type"] == e)
    for name in ("catalogue_papers.csv", "_removed.jsonl", "_v2_to_v3_map.csv"):
        if (in_dir / name).exists():
            (out_dir / name).write_bytes((in_dir / name).read_bytes())

    fill = {}
    for e, fields in LINKS.items():
        rows = [r["fields"] for r in records if r["entity_type"] == e]
        fill[e] = {fld: round(100 * sum(1 for f in rows if str(f.get(fld, "")).strip()) / max(1, len(rows)), 1)
                   for fld in fields}
    fnd = [r["fields"] for r in records if r["entity_type"] == "findings"]
    report = {"run_id": run_id, "model": args.model, "prompt_version": PROMPT_VERSION,
              "input_dir": str(in_dir), "output_dir": str(out_dir),
              "papers_total": len({r["paper_id"] for r in records}), "papers_run": len(papers),
              "batches": len(batches), "stats": dict(sorted(stats.items())),
              "link_fill_pct": fill,
              "link_status": dict(Counter(r["fields"]["link_status"] for r in records).most_common()),
              "is_primary_finding": dict(Counter(f["is_primary_finding"] for f in fnd)),
              "elapsed_s": round(time.time() - t0, 1)}
    (out_dir / "_link_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=1))
    return 1 if stats["batches_failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
