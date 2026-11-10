"""Stage 2: classify extracted terms against the FIXED taxonomy.

Extraction and classification are separate stages on purpose: a term can be
extracted correctly and categorised wrongly, so the two are evaluated
independently. The model never invents categories — it can only choose from the
versioned vocabulary in `taxonomy/term_taxonomy_v1.yaml`.

Input:  CSV with a `term` column (optionally `term_type`, `normalized_term`).
Output: <out>.csv  one row per term with category assignment + provenance
        <out>.jsonl machine-readable records
        <out>_summary.json  counts, invalid-assignment rate, review queue size

Assignment rules enforced here (not left to the model):
  * primary_category_id must be an UPPER category in the taxonomy, else UNCERTAIN
  * subcategory_id must be a legal child of that category, else dropped to null
  * secondary_category_ids: at most 2, must be UPPER, must differ from primary
  * confidence is the model's own estimate and is NOT correctness — it is stored
    as category_confidence and never used as a verification signal
  * every UNCERTAIN or low-confidence assignment goes to the review queue with
    category_verification_status=NEEDS_REVIEW
  * a model-supplied category outside the vocabulary is counted as
    `invented_category` and the term is sent to review, not silently coerced

Usage:
    PYTHONPATH=src python src/scripts/vllm_termpop/categorize_terms.py \
        --input data/catalogue/terminology_dedup.csv \
        --output outputs/results/term_categories/categories_v1 \
        --limit 500 --host http://127.0.0.1:8000
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import os
import random
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

try:
    from tqdm import tqdm
except ImportError:  # pragma: no cover
    def tqdm(it=None, **kw):
        return it if it is not None else []

sys.path.insert(0, str(Path(__file__).resolve().parent))
import taxonomy as tax_mod  # noqa: E402

log = logging.getLogger("term_categories")

SYSTEM_PROMPT = """You classify scientific terms from human-microbiome papers into a FIXED taxonomy.

RULES
1. You may ONLY use category ids that appear in the vocabulary below. Never invent ids.
2. Choose exactly one primary_category_id. Choose one subcategory_id from that category's list, or null if none fits.
3. Add at most 2 secondary_category_ids, only if the term genuinely spans categories.
4. If the term is too ambiguous, truncated or context-free to classify, use UNCERTAIN and say why.
   Never use UNCERTAIN merely because a category is hard to choose.
5. confidence is your own 0.0-1.0 estimate. It is not a correctness guarantee.
6. Return ONLY a JSON object. No prose, no code fence."""

PROMPT_VERSION = "term-category-v1"
DEFAULT_PARALLEL = 32


def build_prompt(terms, vocabulary):
    listing = "\n".join("- %s" % t for t in terms)
    return (
        "VOCABULARY (category_id: definition | subcategories):\n"
        f"{vocabulary}\n\n"
        "Classify each term below. Return exactly this JSON shape:\n"
        '{"categories": [{"term": "...", "primary_category_id": "...", '
        '"subcategory_id": "..." | null, "secondary_category_ids": [], '
        '"confidence": 0.0, "ambiguous": false, "rationale": "<=20 words"}]}\n\n'
        f"TERMS:\n{listing}\n"
    )


def cache_key(terms, vocabulary):
    h = hashlib.sha256()
    for part in (SYSTEM_PROMPT, vocabulary, PROMPT_VERSION, "|".join(terms)):
        h.update(part.encode("utf-8"))
        h.update(b"\x1f")
    return h.hexdigest()


class Client:
    def __init__(self, host, model, timeout=600):
        self.host = host.rstrip("/")
        self.model = model
        self.timeout = timeout

    def chat(self, terms, vocabulary):
        body = json.dumps({
            "model": self.model,
            "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                         {"role": "user", "content": build_prompt(terms, vocabulary)}],
            "temperature": 0,
            "max_tokens": 2048,
            "chat_template_kwargs": {"enable_thinking": False},
            "response_format": {"type": "json_object"},
        }).encode()
        req = urllib.request.Request(self.host + "/v1/chat/completions", data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            data = json.loads(r.read())
        ch = data["choices"][0]
        msg = ch.get("message") or {}
        content = msg.get("content") or msg.get("reasoning_content") or ""
        if ch.get("finish_reason") == "length":
            raise ValueError("truncated (finish_reason=length)")
        return json.loads(content).get("categories", [])


def validate_assignment(tax, rec):
    """Coerce one model answer to a legal taxonomy assignment."""
    notes = []
    primary = (rec.get("primary_category_id") or "").strip()
    sub = (rec.get("subcategory_id") or "").strip() or None
    upper_ids = {c["category_id"] for c in tax.upper()} | (tax_mod.RESERVED & set(tax.categories))

    if primary not in upper_ids:
        notes.append("invented_category=%r" % primary)
        primary = "UNCERTAIN" if "UNCERTAIN" in tax.categories else next(iter(
            [c for c in tax.categories if c == "OTHER"] or ["UNCERTAIN"]), "UNCERTAIN")
        sub = None
    if sub and not tax.valid_pair(primary, sub):
        notes.append("illegal_subcategory=%r" % sub)
        sub = None

    secondaries = [s for s in (rec.get("secondary_category_ids") or [])
                   if isinstance(s, str) and s in upper_ids and s != primary][:2]
    if len(rec.get("secondary_category_ids") or []) > len(secondaries):
        notes.append("secondary_trimmed")

    try:
        conf = float(rec.get("confidence"))
    except (TypeError, ValueError):
        conf = None

    needs_review = (primary == "UNCERTAIN" or bool(notes)
                    or bool(rec.get("ambiguous"))
                    or (conf is not None and conf < 0.6))

    return {
        "primary_category_id": primary,
        "subcategory_id": sub,
        "secondary_category_ids": ";".join(secondaries),
        "category_confidence": "" if conf is None else round(conf, 3),
        "category_source": "LLM_ASSIGNED",
        "category_verification_status": "NEEDS_REVIEW" if needs_review else "UNVERIFIED",
        "category_rationale": (rec.get("rationale") or "").strip()[:200],
        "category_review_notes": "; ".join(notes),
    }


def sample_terms(terms, n, mode, seed):
    """Pick a pilot sample. `terms` arrives in descending frequency order."""
    rnd = random.Random(seed)
    if mode == "random":
        return rnd.sample(terms, n)

    groups = {}
    for t in terms:
        groups.setdefault(t["term_type"] or "UNKNOWN", []).append(t)
    total = len(terms)
    alloc = {k: max(5, int(round(n * len(v) / total))) for k, v in groups.items()}

    picks = []
    for k, v in groups.items():
        k_n = min(alloc[k], len(v))
        if k_n <= 1:
            idxs = [0]
        else:  # spread across the frequency distribution, not just the head
            idxs = sorted({int(round(i * (len(v) - 1) / (k_n - 1))) for i in range(k_n)})
        picks.extend(v[i] for i in idxs)

    chosen = {id(p) for p in picks}
    rest = [t for t in terms if id(t) not in chosen]
    rnd.shuffle(rest)
    if len(picks) > n:
        rnd.shuffle(picks)
        picks = picks[:n]
    elif len(picks) < n:
        picks.extend(rest[: n - len(picks)])
    return picks


def main():
    ap = argparse.ArgumentParser(description="Classify terms against the fixed taxonomy")
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True, help="output prefix (no extension)")
    ap.add_argument("--taxonomy", default=str(tax_mod.DEFAULT_PATH))
    ap.add_argument("--host", default="http://127.0.0.1:8000")
    ap.add_argument("--model", default="Qwen/Qwen3.5-4B")
    ap.add_argument("--batch_size", type=int, default=20)
    ap.add_argument("--parallel", type=int, default=DEFAULT_PARALLEL)
    ap.add_argument("--limit", type=int, default=None,
                    help="pilot on N terms (recommended before a full run)")
    ap.add_argument("--sample", choices=["head", "random", "stratified"], default="head",
                    help="how --limit picks terms. 'head' takes the most frequent terms, "
                         "which over-represents the well-known head of the distribution; "
                         "'stratified' samples across legacy cdm_type AND across frequency "
                         "bands, which is what a taxonomy pilot needs.")
    ap.add_argument("--seed", type=int, default=13)
    args = ap.parse_args()

    tax = tax_mod.Taxonomy(args.taxonomy)
    errors, _ = tax.validate()
    if errors:
        sys.exit("taxonomy invalid: %s" % "; ".join(errors[:3]))
    vocab = tax.prompt_vocabulary()
    out_prefix = Path(args.output)
    out_prefix.parent.mkdir(parents=True, exist_ok=True)
    log_path = out_prefix.parent / (out_prefix.name + ".log")
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler(sys.stdout),
                                  logging.FileHandler(log_path, encoding="utf-8")])

    rows = list(csv.DictReader(open(args.input, newline="", encoding="utf-8-sig")))
    seen, terms = set(), []
    for r in rows:
        t = (r.get("term") or "").strip()
        if t and t.lower() not in seen:
            seen.add(t.lower())
            terms.append({
                "term": t,
                # terminology_dedup.csv uses term_norm / cdm_type; other inputs
                # may use normalized_term / term_type. The old flat cdm_type is
                # carried through as a crosswalk so the new hierarchy can be
                # compared against the legacy typing rather than replacing it
                # silently.
                "normalized_term": r.get("term_norm") or r.get("normalized_term") or "",
                "term_type": r.get("cdm_type") or r.get("term_type") or r.get("labels") or "",
                "legacy_cdm_type": r.get("cdm_type") or "",
                "legacy_all_types": r.get("all_types") or "",
                "n_papers": r.get("n_papers") or "",
            })
        if args.limit and len(terms) >= args.limit and args.sample == "head":
            break

    if args.limit and len(terms) > args.limit and args.sample != "head":
        terms = sample_terms(terms, args.limit, args.sample, args.seed)
        log.info("sampled %d terms (%s, seed=%d) from %d", len(terms), args.sample,
                 args.seed, len(rows))
    log.info("terms to classify: %d (from %d input rows)", len(terms), len(rows))

    cache_path = out_prefix.parent / (out_prefix.name + "_cache.json")
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    batches, buf = [], []
    for t in terms:
        buf.append(t)
        if len(buf) == args.batch_size:
            batches.append(buf); buf = []
    if buf:
        batches.append(buf)
    todo = [b for b in batches if cache_key([t["term"] for t in b], vocab) not in cache]
    log.info("batches: %d (cached %d, to run %d)", len(batches), len(batches) - len(todo), len(todo))

    client = Client(args.host, args.model)
    errors_ct = [0]

    def run(batch):
        key = cache_key([t["term"] for t in batch], vocab)
        try:
            return key, client.chat([t["term"] for t in batch], vocab), None
        except Exception as ex:  # noqa: BLE001
            return key, None, repr(ex)

    if todo:
        with ThreadPoolExecutor(args.parallel) as pool:
            for (key, out, err) in tqdm(pool.map(run, todo), total=len(todo),
                                        desc="term batches", unit="batch"):
                if err is not None:
                    errors_ct[0] += 1
                    cache[key] = {"error": err}
                else:
                    cache[key] = {"categories": out}
                if len(cache) % 20 == 0:
                    cache_path.write_text(json.dumps(cache))
        cache_path.write_text(json.dumps(cache))

    # validate + emit
    stats = {"terms": 0, "assigned": 0, "uncertain": 0, "invented": 0,
             "needs_review": 0, "batch_errors": errors_ct[0]}
    out_rows = []
    for batch in batches:
        entry = cache.get(cache_key([t["term"] for t in batch], vocab))
        if not entry or entry.get("error"):
            continue
        by_term = {}
        for rec in entry.get("categories") or []:
            by_term[(rec.get("term") or "").strip().lower()] = rec
        for t in batch:
            rec = by_term.get(t["term"].lower(), {})
            v = validate_assignment(tax, rec)
            stats["terms"] += 1
            if v["primary_category_id"] == "UNCERTAIN":
                stats["uncertain"] += 1
            else:
                stats["assigned"] += 1
            if "invented_category" in v["category_review_notes"]:
                stats["invented"] += 1
            if v["category_verification_status"] == "NEEDS_REVIEW":
                stats["needs_review"] += 1
            out_rows.append({
                "term": t["term"], "normalized_term": t["normalized_term"],
                "term_type": t["term_type"],
                "legacy_cdm_type": t["legacy_cdm_type"],
                "legacy_all_types": t["legacy_all_types"],
                "n_papers": t["n_papers"],
                "taxonomy_id": tax.taxonomy_id, "taxonomy_version": tax.version,
                "primary_category_id": v["primary_category_id"],
                "subcategory_id": v["subcategory_id"] or "",
                "concept_id": "%s::%s" % (v["subcategory_id"] or v["primary_category_id"],
                                          (t["normalized_term"] or t["term"]).lower()),
                "parent_concept_id": v["subcategory_id"] or v["primary_category_id"],
                "secondary_category_ids": v["secondary_category_ids"],
                "category_source": v["category_source"],
                "category_confidence": v["category_confidence"],
                "category_verification_status": v["category_verification_status"],
                "category_rationale": v["category_rationale"],
                "category_review_notes": v["category_review_notes"],
                "classifier_model": args.model,
                "prompt_version": PROMPT_VERSION,
            })

    with open(str(out_prefix) + ".csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
        w.writeheader()
        w.writerows(out_rows)
    with open(str(out_prefix) + ".jsonl", "w", encoding="utf-8") as f:
        for r in out_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    json.dump(stats, open(str(out_prefix) + "_summary.json", "w"), indent=2)

    log.info("classified %d terms -> %s.csv", stats["terms"], out_prefix)
    log.info("assigned=%d uncertain=%d invented=%d needs_review=%d",
             stats["assigned"], stats["uncertain"], stats["invented"], stats["needs_review"])
    if stats["invented"]:
        log.warning("model produced %d category ids outside the vocabulary — "
                    "all were routed to review rather than coerced", stats["invented"])


if __name__ == "__main__":
    main()
