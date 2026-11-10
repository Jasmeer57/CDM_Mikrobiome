"""LLM NER for the Human Microbiome Data Catalogue — full-section extraction
from `data/segmented_sections_markdown/HMPAPER_*.md` via a vLLM OpenAI-compatible
server running Qwen3.5-4B.

Unlike `qwen_sections_vllm.py` (which tags CDM entity mentions), this script
extracts *catalogue records* — the rows of `src/template/data_catalogue/
human_microbiome_data_catalogue.schema.json` — from every section of every
paper:

    datasets     dataset mentions, repositories, accessions, URLs,
                 data-availability statements, licences
    data_assets  individual files / resources inside a dataset
    cohorts      study populations, recruitment, counts, timepoints
    samples      specimen groups / body sites / collection methods
    assays       sequencing platform, extraction, primers, pipelines,
                 software, reference databases, statistics
    findings     discrete reported results (taxon/feature, direction, effect)

Design rules (mirrors the full-section extraction spec):
  1. FULL SECTION FIRST — a section body <= --full_section_max_chars is sent
     whole. No truncation, no preview, no first-N-tokens shortcut.
  2. COVERAGE-PRESERVING SEGMENTATION — longer sections are split into
     sentence-aligned, non-overlapping windows (a partition of [0, len(text)),
     so no character is processed twice and no text is skipped).
  3. PRE-EXTRACTION VERIFICATION — per section: char count + sha256 of the body
     recorded before extraction; empty bodies flagged.
  4. FAIL-CLOSED COVERAGE — a segment that fails after retry marks its section
     INCOMPLETE; the run is then reported as REVIEW_REQUIRED, never COMPLETE.
  5. NEVER FABRICATE — the model is told to emit only values stated in the
     passage and to quote evidence verbatim. Missing values are left blank
     (template convention: blank = not extracted), never guessed. The model
     is also told that `direction` is NOT_STATED unless the text states it.

Backmatter is INCLUDED by default (unlike the CDM NER skip rule), because the
catalogue's highest-value fields — accessions, repository URLs, availability
statements, licence terms — live in Data Availability / Supplementary sections.

Usage (expects `vllm serve Qwen/Qwen3.5-4B --port 8000` on the node):
    PYTHONPATH=src python src/scripts/vllm_termpop/catalogue_ner.py \
        --output_dir outputs/results/catalogue_ner_<jobid> [--parallel 32]

Outputs (in --output_dir):
    catalogue_records.jsonl    one JSON object per extracted record (authoritative)
    catalogue_<entity>.csv     template-shaped tables: datasets, dataassets,
                               cohorts, samples, assays, findings
    _catalogue_cache.json      checkpoint / resume cache (segment-keyed)
    _catalogue_summary.json    run stats + fail-closed coverage summary
    _coverage.csv              per-section coverage evidence
    run.log                    full log
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import os
import re
import sys
import time
import urllib.request
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path

try:  # tqdm lives in the vLLM venv; degrade gracefully elsewhere
    from tqdm import tqdm
    _TQDM = True
except ImportError:  # pragma: no cover
    _TQDM = False

    def tqdm(iterable=None, **kw):  # type: ignore[misc]
        return iterable if iterable is not None else []

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

log = logging.getLogger("catalogue_ner")

REPO_ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
sys.path.insert(0, str(REPO_ROOT / "src"))

from cdm_pipeline.ner.runner_sections import load_sections, SEG_DIR_DEFAULT  # noqa: E402
from cdm_pipeline.ner.qwen_sections import llm_chunks, llm_locate  # noqa: E402

SCHEMA_PATH = (REPO_ROOT / "src/template" / "data_catalogue"
               / "human_microbiome_data_catalogue.schema.json")

# ── Extraction contract ──────────────────────────────────────────────────────
# entity_type -> (schema $defs key, id field, prefix, fields the model may fill)
ENTITY_SPECS = {
    "datasets": ("dataset", "dataset_id", "HMDATA", [
        "dataset_title", "dataset_description", "dataset_type", "dataset_role",
        "repository_name", "repository_accession", "accession_type",
        "dataset_url", "related_publication_dois", "data_availability_status",
        "access_conditions", "license_or_terms", "original_or_reused",
        "evidence_text",
    ]),
    "data_assets": ("asset", "asset_id", "HMASSET", [
        "asset_name", "asset_type", "format", "description", "repository_url",
        "accession", "file_size_bytes", "checksum_type", "checksum",
        "access_status", "license_or_terms", "evidence_text",
    ]),
    "cohorts": ("cohort", "cohort_id", "HMCOHORT", [
        "cohort_label", "cohort_role", "population_description",
        "country_or_region", "setting", "recruitment_method",
        "participant_count", "sample_count", "age_group", "age_summary",
        "sex_or_gender_reporting", "health_status", "inclusion_criteria",
        "exclusion_criteria", "key_covariates", "longitudinal", "timepoints",
        "evidence_text",
    ]),
    "samples": ("sample", "sample_group_id", "HMSAMPLE", [
        "body_site", "body_site_original", "sample_type", "collection_method",
        "collection_timepoint", "storage_condition", "preservation_method",
        "sample_count", "sample_processing", "evidence_text",
    ]),
    "assays": ("assay", "assay_id", "HMASSAY", [
        "assay_type", "target_gene_or_region", "sequencing_platform",
        "library_preparation", "dna_extraction_method", "primer_or_probe",
        "negative_controls", "positive_controls", "contamination_handling",
        "quality_control", "bioinformatics_pipeline", "software_tools",
        "taxonomic_database", "functional_database", "normalization_method",
        "statistical_methods", "evidence_text",
    ]),
    "findings": ("finding", "finding_id", "HMFINDING", [
        "finding_domain", "finding_text", "taxon_or_feature", "taxonomic_rank",
        "comparison_or_exposure", "outcome", "body_site", "direction",
        "effect_measure", "effect_estimate", "confidence_interval", "p_value",
        "q_value", "adjusted_covariates", "population_subgroup",
        "author_interpretation", "evidence_text",
    ]),
}

CATALOGUE_SYSTEM_PROMPT = """You curate a Human Microbiome Data Catalogue from full-text papers.
You read ONE complete passage (a whole section of a paper, or one segment of a
long section) and return catalogue records that the passage EXPLICITLY supports.

ABSOLUTE RULES
1. Extract only what the passage states. NEVER infer, guess, complete, or
   generalise. If a field is not stated, omit it from the record.
2. `evidence_text` MUST be copied verbatim from the passage (a short quote,
   <= 300 characters). Do not paraphrase it.
3. Do not merge facts from different cohorts, datasets or assays into one
   record. One record per distinct dataset / asset / cohort / sample group /
   assay / finding.
4. Controlled vocabularies (use these exact tokens, otherwise omit the field):
   dataset_role: primary_study_data | linked_data
   data_availability_status / access_status: PUBLIC | CONTROLLED | EMBARGOED |
       UPON_REQUEST | NOT_DEPOSITED | LINK_ONLY | UNKNOWN
   original_or_reused: ORIGINAL | REUSED | UNKNOWN
   cohort_role: cases_and_controls | single_group
   longitudinal: YES | NO | UNCLEAR | NOT_APPLICABLE
   direction: INCREASE | DECREASE | NO_ASSOCIATION | MIXED | NOT_STATED
5. `direction` is NOT_STATED unless the passage explicitly states the
   direction of the association. Never upgrade "detected" or "associated" to
   INCREASE or DECREASE.
6. Counts (participant_count, sample_count, file_size_bytes) must be integers
   stated in the passage. Never compute or estimate them.
7. Return an empty list for an entity type the passage does not describe.
8. NEVER emit placeholder values. Do not write NOT_STATED, "not stated",
   unknown, N/A or null for a field — simply leave the field out of the record.
   The single exception is `direction`, which may be NOT_STATED.
9. Return ONLY a JSON object. No prose, no code fence."""


def build_user_prompt(text, entity_types):
    """Passage FIRST, instructions after — so the repeated per-entity requests
    for one section share a long common prefix and hit vLLM's prefix cache."""
    spec = {name: ENTITY_SPECS[name][3] for name in entity_types}
    keys = ", ".join('"%s"' % n for n in entity_types)
    return (
        "PASSAGE:\n" + text + "\n\n---\n"
        "Extract catalogue records from the COMPLETE passage above.\n"
        "Return a JSON object with exactly these keys (each a list of records):\n"
        f"{json.dumps(spec, indent=1)}\n"
        "Every record must include `evidence_text` copied verbatim from the "
        "passage. Omit fields the passage does not state — do not write "
        "\"not stated\"/\"unknown\" placeholders, just leave the field out. "
        "If nothing is reported for a key, use an empty list.\n"
        f"Keys: {keys}\n"
    )


LLM_PROMPT_VERSION = "cdm-catalogue-ner-v2-noplaceholder"
LLM_TEMPERATURE = 0
LLM_MAX_TOKENS = 4096
DEFAULT_PARALLEL = 64
FULL_SECTION_MAX_CHARS = 20000
SEG_CHUNK_CHARS = 4000
# Recursive-halving retry budget for passages the model cannot answer in one
# shot. Depth 3 gives up to 8 leaves; a leaf keeps at least this many chars so
# sentence context is not shredded into fragments.
MAX_SPLIT_DEPTH = 3
SPLIT_MIN_CHARS = 1500

_WS_RE = re.compile(r"\s+")


def best_cut(text):
    """Offset at which to halve `text`, or -1 when it cannot be halved.

    Prefer the last space in the first half, so the two halves meet on a word
    boundary. Flattened statistical tables break that assumption: a table whose
    rows are newline- or tab-separated has NO space at all in its first half, so
    `str.rfind(" ", 0, len(text)//2)` returns -1. That is not a real limit — the
    text is still perfectly splittable — so fall back to the last run of any
    whitespace, then to the exact midpoint.

    Without the fallback the split path raises on the first call and no amount
    of retrying can progress. `HMPAPER_000024 sec_001` is such a case: 3,983
    chars of `137.9\\n-\\n4382476\\n...` with zero spaces before the midpoint.
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


# ── helpers ──────────────────────────────────────────────────────────────────
def setup_logging(log_path):
    """Console + file logging so long SLURM runs are fully auditable."""
    log.setLevel(logging.INFO)
    log.handlers.clear()
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S")
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    log.addHandler(sh)
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setFormatter(fmt)
    log.addHandler(fh)
    log.propagate = False


def write_json_atomic(path, obj):
    """Atomic JSON write so a killed job never leaves a corrupt checkpoint."""
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def load_schema_headers():
    """Template headers per entity type, taken from the JSON Schema $defs.

    The schema (updated 2026-10-15) is the machine-readable authority and is
    what `assemble_and_validate.py` validates against; where it disagrees with
    the older `csv_templates/*.csv` headers the schema wins.
    """
    if not SCHEMA_PATH.exists():
        return {name: list(spec[3]) for name, spec in ENTITY_SPECS.items()}
    defs = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))["$defs"]
    headers = {}
    for name, (def_key, _, _, fields) in ENTITY_SPECS.items():
        props = list(defs[def_key]["properties"].keys())
        headers[name] = props
    return headers


def locate_evidence(chunk, quote):
    """Position/span of an evidence quote, tolerant of reflowed whitespace.

    Models often reflow a quote across lines, so an exact whole-word match fails
    even though the quote is verbatim. Fall back to a token-join regex with
    `\\s+` between tokens (then case-insensitively). Returns (pos, exact, length).
    """
    if not quote:
        return None, False, 0
    hits = llm_locate(chunk, quote)
    if hits:
        return hits[0][0], True, len(quote)
    tokens = quote.split()
    if not tokens:
        return None, False, 0
    pat = r"\s+".join(re.escape(t) for t in tokens)
    for flags in (0, re.IGNORECASE):
        m = re.search(pat, chunk, flags)
        if m:
            return m.start(), False, m.end() - m.start()
    return None, False, 0


def segment_section(text, full_max=FULL_SECTION_MAX_CHARS, seg_chars=SEG_CHUNK_CHARS):
    """Full-section-first coverage plan -> [(start, end, mode)].

    Windows partition [0, len(text)) at sentence boundaries, so every character
    is processed exactly once: no truncation, no double counting.
    """
    text = text or ""
    if not text.strip():
        return []
    if len(text) <= full_max:
        return [(0, len(text), "full")]
    return [(s, e, "segment") for s, e in llm_chunks(text, limit=seg_chars)]


def cache_key(segment_text, model, entity_types):
    h = hashlib.sha256()
    for part in (segment_text, CATALOGUE_SYSTEM_PROMPT,
                 json.dumps(build_user_prompt("", entity_types)),
                 model, str(LLM_TEMPERATURE), str(LLM_MAX_TOKENS), LLM_PROMPT_VERSION):
        h.update(part.encode("utf-8"))
        h.update(b"\x1f")
    return h.hexdigest()


class VLLMClient:
    """Minimal OpenAI-compatible chat client via stdlib urllib (no extra deps)."""

    def __init__(self, host, model, timeout=600):
        self.host = host.rstrip("/")
        self.model = model
        self.timeout = timeout

    def chat(self, text, group):
        body = json.dumps({
            "model": self.model,
            "messages": [{"role": "system", "content": CATALOGUE_SYSTEM_PROMPT},
                         {"role": "user", "content": build_user_prompt(text, group)}],
            "temperature": LLM_TEMPERATURE,
            "max_tokens": LLM_MAX_TOKENS,
            "chat_template_kwargs": {"enable_thinking": False},
            "response_format": {"type": "json_object"},
        }).encode("utf-8")
        req = urllib.request.Request(self.host + "/v1/chat/completions", data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            data = json.loads(resp.read())
        choice = data["choices"][0]
        msg = choice.get("message") or {}
        content = msg.get("content") or ""
        if not content and msg.get("reasoning_content"):
            content = msg["reasoning_content"]
        if choice.get("finish_reason") == "length":
            raise ValueError("response truncated by max_tokens (finish_reason=length)")
        obj = json.loads(content)
        out = {}
        for name in group:
            recs = obj.get(name) or []
            out[name] = [r for r in recs if isinstance(r, dict)]
        return out

    def _merge(self, parts, group):
        """Concatenate per-half results, dropping duplicates across the seam.

        Halves share no characters (the split lands on a space boundary), but the
        model can still read a sentence spanning the seam twice and emit the same
        cohort/assay from both sides. Records are deduped on their structured
        content, ignoring the offset-invariant id, so one group survives once.
        """
        merged = {k: [] for k in group}
        seen = {k: set() for k in group}
        for part in parts:
            for k in group:
                for rec in part.get(k) or []:
                    if not isinstance(rec, dict):
                        continue
                    sig = json.dumps(
                        {kk: vv for kk, vv in sorted(rec.items())
                         if not kk.endswith("_id") and kk != "evidence_location"},
                        sort_keys=True, ensure_ascii=False, default=str)
                    if sig in seen[k]:
                        continue
                    seen[k].add(sig)
                    merged[k].append(rec)
        return merged

    def _split_retry(self, text, group, depth, budget):
        """Recursively halve the passage until each piece fits the context.

        A single split is not enough: the sections that truncate are the long
        ones, and half of a 120k-char methods dump still overflows max_tokens.
        Halving bottom-out at `budget` leaving whole sentences intact, and any
        leaf that still fails simply propagates its error, so the section is
        reported incomplete rather than silently truncated.
        """
        try:
            return self.chat(text, group), None
        except Exception as ex:  # noqa: BLE001
            last = ex
        if depth >= budget or len(text) < 2 * SPLIT_MIN_CHARS:
            return None, repr(last)
        cut = best_cut(text)
        if cut <= 0 or len(text) - cut < SPLIT_MIN_CHARS:
            return None, repr(last)
        blobs = []
        for piece in (text[:cut], text[cut:]):
            blob, err = self._split_retry(piece, group, depth + 1, budget)
            if err is not None:
                return None, err
            blobs.append(blob)
        return self._merge(blobs, group), None

    def call_with_retry(self, text, group):
        """Full passage first; on error/truncation, recursively half it.

        `MAX_SPLIT_DEPTH` bounds the retry tree at 2**depth leaves. The section is
        marked incomplete if any leaf still fails -- fail-closed, never a silent
        partial answer.
        """
        return self._split_retry(text, group, 0, MAX_SPLIT_DEPTH)


PLACEHOLDERS = {
    "null", "none", "n/a", "na", "not stated", "not reported", "not specified",
    "not mentioned", "not available", "not applicable", "unknown", "unclear",
    "no data", "none reported", "nan", "-",
}


def normalise_record(entity, rec, allowed):
    """Keep only contract fields; coerce known integers; drop placeholders.

    The template treats a blank cell as "not extracted/unknown", so a model that
    writes "Not stated" must not smuggle that string into a data field. The one
    exception is `direction`, whose controlled vocabulary legitimately contains
    NOT_STATED.
    """
    clean = {}
    for k, v in rec.items():
        if k not in allowed or v is None:
            continue
        if isinstance(v, list):  # model sometimes returns ['QIIME', 'DADA2']
            v = "; ".join(str(x).strip() for x in v if str(x).strip())
        if isinstance(v, str):
            v = v.strip()
            if not v:
                continue
            # "NOT_STATED" and "not stated" are the same placeholder
            if k != "direction" and v.lower().replace("_", " ").strip(" .") in PLACEHOLDERS:
                continue
        clean[k] = v
    int_fields = {"participant_count", "sample_count", "file_size_bytes"}
    for k in list(clean):
        if k in int_fields and isinstance(clean[k], str):
            digits = "".join(ch for ch in clean[k] if ch.isdigit())
            if digits:
                clean[k] = int(digits)
            else:
                clean.pop(k)
    return clean


def main():
    ap = argparse.ArgumentParser(description="Catalogue-entity NER from segmented sections")
    ap.add_argument("--model", default="Qwen/Qwen3.5-4B")
    ap.add_argument("--host", default="http://127.0.0.1:8000")
    ap.add_argument("--seg_dir", default=str(SEG_DIR_DEFAULT))
    ap.add_argument("--output_dir", required=True)
    ap.add_argument("--parallel", type=int, default=DEFAULT_PARALLEL)
    ap.add_argument("--request_timeout", type=float, default=240.0,
                    help="per-HTTP-request timeout in seconds (default 240). A full "
                         "20k-char section plus 4096 output tokens completes well "
                         "inside this; a hung request must fail rather than stall "
                         "the checkpoint.")
    ap.add_argument("--max_files", type=int, default=None)
    ap.add_argument("--full_section_max_chars", type=int, default=FULL_SECTION_MAX_CHARS)
    ap.add_argument("--body_only", action="store_true",
                    help="Skip backmatter sections (default: include them, "
                         "Data Availability lives there)")
    ap.add_argument("--entity_types", nargs="+", default=list(ENTITY_SPECS),
                    choices=list(ENTITY_SPECS))
    ap.add_argument("--request_mode", choices=["split", "joint"], default="split",
                    help="split: one request per entity type (smaller responses, "
                         "prefix-cache friendly); joint: one request for all types")
    ap.add_argument("--assemble_only", action="store_true",
                    help="skip extraction; rebuild the CSV tables from an "
                         "existing checkpoint (use after fixing post-processing)")
    ap.add_argument("--checkpoint_every", type=int, default=25,
                    help="flush the resume cache every N finished segments "
                         "(lower = more visible/safer, higher = less I/O)")
    args = ap.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    setup_logging(output_dir / "run.log")

    cache_path = output_dir / "_catalogue_cache.json"
    records_path = output_dir / "catalogue_records.jsonl"
    coverage_path = output_dir / "_coverage.csv"
    summary_path = output_dir / "_catalogue_summary.json"
    run_id = "CATNER_%s_%s" % (time.strftime("%Y%m%dT%H%M%S"), os.getpid())

    log.info("catalogue NER | run_id=%s model=%s host=%s", run_id, args.model, args.host)
    log.info("schema=%s", SCHEMA_PATH)

    # ── 0) load sections + pre-extraction verification ──────────────────────
    units, per_paper = load_sections(args.seg_dir, args.max_files,
                                     body_only=args.body_only)
    sec_text, coverage = {}, {}
    for u in units:
        key = (u["cid"], u["section_id"])
        text = u["text"] or ""
        sec_text[key] = text
        coverage[key] = {
            "paper": u["cid"], "section_id": u["section_id"], "section_path": u["path"],
            "section_chars": len(text),
            "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()[:16],
            "empty": not text.strip(), "segments": 0, "processed": 0,
            "errors": 0, "cached": 0, "ran": 0, "records": 0,
            "status": "SKIPPED_EMPTY" if not text.strip() else "PENDING",
        }

    # ── 1) coverage plan ────────────────────────────────────────────────────
    # One request per (segment × entity group). Splitting by entity type keeps
    # each JSON response small enough to avoid finish_reason=length, and the
    # passage-first prompt lets the repeated prefills hit the prefix cache.
    groups = ([[e] for e in args.entity_types] if args.request_mode == "split"
              else [list(args.entity_types)])
    jobs = []
    for u in units:
        key0 = (u["cid"], u["section_id"])
        plan = segment_section(sec_text[key0], args.full_section_max_chars)
        coverage[key0]["segments"] = len(plan) * len(groups)
        if coverage[key0]["status"] == "PENDING" and not plan:
            coverage[key0]["status"] = "SKIPPED_EMPTY"
        for s, e, mode in plan:
            for group in groups:
                jobs.append({
                    "cid": u["cid"], "sid": u["section_id"], "path": u["path"],
                    "s": s, "e": e, "mode": mode, "group": group,
                    "key": cache_key(sec_text[key0][s:e], args.model, group),
                })

    n_full = sum(1 for j in jobs if j["mode"] == "full")
    exp_chars = sum(len(t) for t in sec_text.values())
    log.info("papers=%d sections=%d requests=%d (full-section=%d segment=%d) "
             "groups=%d chars=%d",
             len({u["cid"] for u in units}), len(units), len(jobs), n_full,
             len(jobs) - n_full, len(groups), exp_chars)

    cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}

    def _ok(entry):
        return bool(entry) and not entry.get("error") and "records" in entry

    # failed segments are retried on resume rather than frozen as failures
    todo = ([] if args.assemble_only
            else [j for j in jobs if not _ok(cache.get(j["key"]))])
    log.info("cache hits=%d to run=%d (includes %d retried failures)",
             len(jobs) - len(todo), len(todo),
             sum(1 for j in jobs if j["key"] in cache and not _ok(cache[j["key"]])))

    for j in jobs:
        if _ok(cache.get(j["key"])):
            coverage[(j["cid"], j["sid"])]["cached"] += 1
        else:
            coverage[(j["cid"], j["sid"])]["ran"] += 1

    # ── 2) run with checkpoint/resume; every failure fails the section closed ─
    client = VLLMClient(args.host, args.model, timeout=args.request_timeout)
    seg_errors = []
    t0 = time.time()

    def _run(job):
        try:
            recs, err = client.call_with_retry(sec_text[(job["cid"], job["sid"])]
                                               [job["s"]:job["e"]], job["group"])
            return job["key"], recs, err
        except Exception as ex:  # noqa: BLE001 — record, never kill the worker
            return job["key"], None, repr(ex)

    if todo:
        # Results are consumed AS THEY COMPLETE, not in submission order.
        #
        # An ordered `pool.map` loop is a trap here: it submits all 33k jobs at
        # once and yields strictly in order, so a single slow or timing-out
        # section at position ~20 blocks every later result from being
        # checkpointed. That happened on job 28604601 — the GPU answered ~1,800
        # requests while the run log sat frozen at 19/32,994 and no cache file
        # existed, i.e. all that GPU work was unrecoverable. A bounded sliding
        # window keeps memory flat and lets the checkpoint track real progress
        # regardless of which section is slow.
        pbar = tqdm(total=len(todo), desc="catalogue requests", unit="req",
                    disable=not _TQDM)
        done_ct = 0
        window = max(args.parallel * 2, args.parallel + 1)
        inflight, it = {}, iter(todo)

        def _fill(pool):
            while len(inflight) < window:
                try:
                    job = next(it)
                except StopIteration:
                    return
                inflight[pool.submit(_run, job)] = job

        with ThreadPoolExecutor(args.parallel) as pool:
            _fill(pool)
            while inflight:
                finished, _ = wait(list(inflight), return_when=FIRST_COMPLETED)
                for fut in finished:
                    job = inflight.pop(fut)
                    try:
                        key, recs, err = fut.result()
                    except Exception as ex:  # noqa: BLE001
                        key, recs, err = job["key"], None, repr(ex)
                    done_ct += 1
                    if err is not None or recs is None:
                        seg_errors.append((key, repr(err)))
                        # fail the owning section closed — it cannot be COMPLETE
                        coverage[(job["cid"], job["sid"])]["errors"] += 1
                        cache[key] = {"error": str(err)}
                    else:
                        # provenance goes into the checkpoint so peek_records.py
                        # can attribute partial results while the run is going
                        cache[key] = {"records": recs, "cid": job["cid"],
                                      "sid": job["sid"], "s": job["s"], "e": job["e"],
                                      "group": job["group"]}
                    pbar.update(1)
                    if done_ct % args.checkpoint_every == 0 or done_ct == len(todo):
                        write_json_atomic(cache_path, cache)
                        el = time.time() - t0
                        rate = done_ct / el if el > 0 else 0
                        pbar.set_postfix(errors=len(seg_errors),
                                         eta="%.0fs" % ((len(todo) - done_ct) / rate
                                                        if rate else 0))
                    if done_ct == len(todo):
                        log.info("all %d requests complete in %.0fs", done_ct, time.time() - t0)
                _fill(pool)
            write_json_atomic(cache_path, cache)
        pbar.close()

    # ── 3) collect + locate evidence -> one row per catalogue record ─────────
    headers = load_schema_headers()
    records = []
    stats = {"returned": 0, "kept": 0, "dropped_empty": 0, "evidence_located": 0,
             "evidence_reflowed": 0, "evidence_not_located": 0, "per_entity": {}}
    seen = set()

    for job in jobs:
        entry = cache.get(job["key"])
        if not entry or entry.get("error") or "records" not in entry:
            continue
        cid, sid, path_name = job["cid"], job["sid"], job["path"]
        s, e, mode = job["s"], job["e"], job["mode"]
        chunk = sec_text[(cid, sid)][s:e]
        for entity in job["group"]:
            # evidence_text is preserved for EVERY entity, even where the
            # template does not declare it. The model returns a supporting
            # sentence for ~100% of records; letting normalise_record drop it
            # because it is absent from the field list threw away the only
            # verbatim quote for cohorts/samples/assays/data_assets, leaving
            # those tables with no auditable evidence at all.
            allowed = set(ENTITY_SPECS[entity][3]) | {"evidence_text"}
            for rec in entry["records"].get(entity) or []:
                stats["returned"] += 1
                clean = normalise_record(entity, rec, allowed)
                if not clean:
                    stats["dropped_empty"] += 1
                    continue
                ev = clean.get("evidence_text") or ""
                pos, span_len = None, 0
                if ev:
                    pos, exact, span_len = locate_evidence(chunk, ev)
                    if pos is None:
                        stats["evidence_not_located"] += 1
                    elif exact:
                        stats["evidence_located"] += 1
                    else:
                        stats["evidence_reflowed"] += 1
                dedup = (cid, sid, entity, ev, pos)
                if dedup in seen:
                    continue
                seen.add(dedup)

                cs = s + pos if pos is not None else None
                ce = cs + span_len if cs is not None else None
                loc = "%s [%s]" % (path_name or "(unknown)", sid)
                if cs is not None:
                    loc += " chars %d-%d" % (cs, ce)

                out = {k: clean.get(k, "") for k in headers[entity]}
                out["paper_id"] = cid
                # Evidence provenance is emitted for EVERY entity, even where the
                # template does not declare the columns. Restricting `out` to the
                # schema headers silently dropped the model's supporting sentence
                # for cohorts/samples/assays/data_assets, which left four of the
                # six catalogue tables with no auditable quote at all.
                if str(clean.get("evidence_text") or "").strip():
                    out["evidence_text"] = clean["evidence_text"]
                out["evidence_location"] = loc
                if "verification_status" in out:
                    out["verification_status"] = "UNVERIFIED"
                if "extraction_method" in out:
                    out["extraction_method"] = "LLM:%s:%s" % (args.model, LLM_PROMPT_VERSION)
                # unlocatable quotes are the model's paraphrase or invention:
                # keep the record but make the defect explicit for reviewers
                if pos is None:
                    note_field = ("catalogue_notes" if "catalogue_notes" in out
                                  else "notes" if "notes" in out else None)
                    if note_field:
                        out[note_field] = "EVIDENCE_QUOTE_NOT_FOUND_IN_SECTION"
                records.append({
                    "entity_type": entity, "paper_id": cid, "section_id": sid,
                    "section_path": path_name, "segment_mode": mode,
                    "char_start": cs, "char_end": ce,
                    "evidence_verified": 1 if pos is not None else 0,
                    "fields": out,
                    "extraction_model": args.model,
                    "prompt_version": LLM_PROMPT_VERSION,
                    "extraction_run_id": run_id,
                })
                stats["kept"] += 1
                stats["per_entity"][entity] = stats["per_entity"].get(entity, 0) + 1
                coverage[(cid, sid)]["records"] += 1

    # deterministic order -> stable template IDs
    records.sort(key=lambda r: (r["paper_id"], r["section_id"], r["entity_type"],
                                -1 if r["char_start"] is None else r["char_start"],
                                r["fields"].get("evidence_text", "")))

    counters = {}
    for r in records:
        entity = r["entity_type"]
        schema_def, id_field, prefix, _ = ENTITY_SPECS[entity]
        counters[entity] = counters.get(entity, 0) + 1
        r["fields"][id_field] = "%s_%06d" % (prefix, counters[entity])

    with open(records_path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    for entity in args.entity_types:
        _, id_field, _, _ = ENTITY_SPECS[entity]
        cols = list(headers[entity])
        # Evidence must survive into the published table for every entity type:
        # the quote for auditing, the span for re-checking. `paper_id` is added
        # for the same reason -- the asset template omits it, which left
        # data_assets.csv with no link back to its paper even though the record
        # carries one.
        for extra in ("paper_id", "evidence_text", "evidence_location"):
            if extra not in cols:
                cols.append(extra)
        fname = output_dir / ("catalogue_%s.csv" % entity)
        with open(fname, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            for r in records:
                if r["entity_type"] != entity:
                    continue
                row = {k: r["fields"].get(k, "") for k in cols}
                row[id_field] = r["fields"][id_field]
                w.writerow(row)
        log.info("wrote %s (%d rows)", fname.name, counters.get(entity, 0))

    # ── 4) fail-closed coverage report ──────────────────────────────────────
    # Reconcile against the CHECKPOINT first. The cached/errors counters are
    # incremented inside the run loop, which --assemble_only skips and which
    # never runs for jobs finished in an earlier session. Left as-is, a cache
    # holding 12% of the requests reported "COMPLETE" because errors stayed at
    # zero and processed fell back to the planned segment count. Deriving the
    # counts from the cache makes assembly fail-closed by construction.
    for cov in coverage.values():
        cov["cached"] = cov["ran"] = cov["errors"] = cov["missing"] = 0
    for j in jobs:
        cov = coverage[(j["cid"], j["sid"])]
        entry = cache.get(j["key"])
        if _ok(entry):
            cov["cached"] += 1
        elif entry is not None:
            cov["errors"] += 1
        else:
            cov["missing"] += 1
    seg_errors = [(j["key"], str((cache.get(j["key"]) or {}).get("error", "not run")))
                  for j in jobs if not _ok(cache.get(j["key"]))]

    for cov in coverage.values():
        if cov["status"] == "PENDING":
            cov["processed"] = cov["cached"]
            cov["status"] = ("COMPLETE"
                             if (cov["errors"] == 0 and cov["missing"] == 0
                                 and cov["processed"] == cov["segments"])
                             else "REVIEW_REQUIRED_INCOMPLETE")
    n_incomplete = sum(1 for c in coverage.values() if c["status"] == "REVIEW_REQUIRED_INCOMPLETE")
    n_complete = sum(1 for c in coverage.values() if c["status"] == "COMPLETE")
    coverage_status = "COMPLETE" if (n_incomplete == 0 and not seg_errors) else "REVIEW_REQUIRED"
    proc_chars = sum(c["section_chars"] for c in coverage.values()
                     if c["status"] in ("COMPLETE", "SKIPPED_EMPTY"))

    with open(coverage_path, "w", newline="", encoding="utf-8") as f:
        cols = ["paper", "section_id", "section_path", "section_chars", "text_sha256",
                "empty", "segments", "processed", "errors", "cached", "ran",
                "missing", "records", "status"]
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for c in coverage.values():
            w.writerow({k: c.get(k, 0) for k in cols})

    summary = {
        "run_id": run_id, "model": args.model, "prompt_version": LLM_PROMPT_VERSION,
        "seg_dir": str(args.seg_dir), "body_only": args.body_only,
        "entity_types": args.entity_types, "request_mode": args.request_mode,
        "parallel": args.parallel,
        "full_section_max_chars": args.full_section_max_chars,
        "papers": len({u["cid"] for u in units}), "sections": len(units),
        "segments_total": len(jobs), "segments_full_section": n_full,
        "segments_split": len(jobs) - n_full, "segments_run": len(todo),
        "segments_cached": len(jobs) - len(todo), "segments_failed": len(seg_errors),
        "stats": stats, "records_total": len(records),
        "records_per_entity": counters,
        "coverage": {
            "coverage_status": coverage_status,
            "sections_total": len(coverage), "sections_complete": n_complete,
            "sections_empty": sum(1 for c in coverage.values() if c["status"] == "SKIPPED_EMPTY"),
            "sections_incomplete": n_incomplete,
            "expected_chars": exp_chars, "processed_chars": proc_chars,
            "char_coverage_pct": round(100.0 * proc_chars / exp_chars, 3) if exp_chars else 100.0,
            "truncation_warnings": ["%s: segment failed (counted as unprocessed)" % k
                                    for k, _ in seg_errors[:20]],
        },
        "elapsed_s": round(time.time() - t0, 1),
    }
    write_json_atomic(summary_path, summary)

    log.info("records=%d %s", len(records), json.dumps(counters))
    log.info("evidence exact=%d reflowed=%d not_located=%d",
             stats["evidence_located"], stats["evidence_reflowed"],
             stats["evidence_not_located"])
    log.info("coverage %d/%d sections complete, %d segment(s) failed -> %s",
             n_complete, len(coverage), len(seg_errors), coverage_status)
    if coverage_status != "COMPLETE":
        log.warning("coverage incomplete -> REVIEW_REQUIRED; see %s", coverage_path.name)
        for k, err in seg_errors[:10]:
            log.warning("  failed segment %s: %s", k, err[:120])
    log.info("done -> %s", output_dir)


if __name__ == "__main__":
    main()
