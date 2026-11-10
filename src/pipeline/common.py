"""Shared infrastructure for corpus v2 pipeline.

Design principles (master template + full-text integrity requirement):
- raw/ is write-once; stages refuse to overwrite unversioned raw artifacts
- nothing is ever silently dropped or overwritten; failures recorded with reason codes
- every stage appends processing events (provenance) with input/output hashes
- LLM output lives only in llm_* fields with model/prompt version labels
- fail-closed: status COMPLETE only with recorded evidence, else PARTIAL/FAILED/REVIEW_REQUIRED
"""
import hashlib
import json
import os
import re
import sys
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import yaml

#: Repo root, found at run time by walking up to the .cdm_root marker.
REPO_ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
#: The corpus build these stages read and write (config/, data/, checkpoints/, …).
#: This module lives in src/pipeline/, not inside the corpus folder, so the
#: location comes from the repo root rather than from this file's parents.
CORPUS_DIR = REPO_ROOT / "pipelines" / "corpus_v2"


#: Top-level folders that moved on 2026-10-30. Corpus records written before
#: the move store absolute paths under the old layout; this maps them.
MOVED_TOP_LEVEL = {
    "168000-samples-paper": "data/168000-samples-paper",
    "segmented_sections_markdown": "data/segmented_sections_markdown",
    "papers_txt": "data/papers_txt",
    "corpus_v2": "pipelines/corpus_v2",
}


def resolve_recorded_path(recorded) -> Path:
    """Return where a path stored in a corpus record lives now.

    Records keep the path they were written with (they are hash-pinned), so a
    path from before the 2026-10-30 restructure is re-rooted here instead of
    rewriting the record. Returns the recorded path unchanged if it still
    exists or cannot be mapped.
    """
    p = Path(recorded)
    if p.exists():
        return p
    parts = p.parts
    for i, part in enumerate(parts):
        if part in MOVED_TOP_LEVEL:
            candidate = REPO_ROOT / MOVED_TOP_LEVEL[part] / Path(*parts[i + 1:])
            if candidate.exists():
                return candidate
    return p

STATUSES = ("COMPLETE", "PARTIAL", "FAILED", "REVIEW_REQUIRED", "PENDING", "UNAVAILABLE")

# ---- master-template controlled vocabularies (template §2 "standard status values") ----
FULLTEXT_STATUS = ("not_checked", "complete", "partial", "failed", "not_applicable")
PROCESSING_STATUS = ("not_started", "source_acquired", "text_extracted",
                     "automated_checks_passed", "manual_review_passed",
                     "needs_repair", "excluded")
ANNOTATION_STATUS = ("not_started", "in_progress", "extracted_unverified",
                     "human_verified", "needs_revision")
INCLUSION_DECISION = ("pending", "include", "exclude")
VERIFICATION_STATUS = ("pending", "verified", "rejected", "needs_revision")
RELEVANCE = ("yes", "no", "unclear")
CHECK_STATUS = ("pass", "fail", "not_checked", "not_available")

# Internal fail-closed status -> template full-text completeness vocabulary
FT_FROM_INTERNAL = {
    "COMPLETE": "complete",
    "PARTIAL": "partial",
    "REVIEW_REQUIRED": "partial",   # never claim complete without passing checks
    "FAILED": "failed",
    "PENDING": "not_checked",
    "UNAVAILABLE": "failed",
}

# stage -> template §5 "Recommended stages" label (curation log)
CURATION_STAGE = {
    "stage10_ingest": "acquisition",
    "stage20_metadata": "metadata",
    "stage25_metadata": "metadata",
    "stage30_dedup": "metadata",
    "stage40_sectionize": "text_extraction",
    "stage45_section_validation": "section_validation",
    "stage50_llm_enrich": "finding_extraction",
    "stage60_validate": "final_review",
    "stage70_finalize": "final_review",
}


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_config() -> dict:
    with open(CORPUS_DIR / "config" / "corpus.yaml") as fh:
        return yaml.safe_load(fh)


def load_secrets() -> dict:
    """Parse config/secrets.env. Accepts both `KEY=value` and `export KEY=value`."""
    env = {}
    p = CORPUS_DIR / "config" / "secrets.env"
    if p.exists():
        for line in p.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.startswith("export "):
                line = line[len("export "):].lstrip()
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1]
            os.environ.setdefault(k, v)
            env[k] = v
    return env


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_text(t: str) -> str:
    return sha256_bytes(t.encode("utf-8"))


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def config_hash(cfg: dict) -> str:
    return sha256_text(json.dumps(cfg, sort_keys=True, default=str))


class WriteOnceRaw:
    """Write-once guard for raw/ (template rule 1). Idempotent on identical bytes."""
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, relpath: str, data: bytes) -> str:
        p = self.root / relpath
        if p.exists():
            existing = sha256_file(p)
            if existing == sha256_bytes(data):
                return existing  # idempotent re-run
            raise RuntimeError(f"write-once violation: {p} exists with different content "
                               f"(bump corpus version or move artifact to releases/)")
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, p)
        return sha256_file(p)


class Events:
    """Append-only processing/provenance log (template section 4)."""
    def __init__(self, corpus_id: str, stage: str, pipeline_version: str, run_id: str | None = None):
        self.run_id = run_id or f"{stage}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}-{os.getpid()}"
        self.corpus_id = corpus_id
        self.stage = stage
        self.pipeline_version = pipeline_version
        self.path = CORPUS_DIR / "data" / "processing_events.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self.path, "a", encoding="utf-8")

    def record(self, **kw):
        rec = {
            "run_id": self.run_id,
            "corpus_id": self.corpus_id,
            "pipeline_stage": self.stage,
            "pipeline_version": self.pipeline_version,
            "started_at": kw.get("started_at") or now_utc(),
            "completed_at": kw.get("completed_at") or now_utc(),
            "run_status": "success",
            "retry_count": 0,
            "manual_intervention": False,
            "operator_or_reviewer": "pipeline",
        }
        rec.update({k: v for k, v in kw.items() if k not in ("started_at", "completed_at")})
        self._fh.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
        self._fh.flush()

    def close(self):
        self._fh.close()


def read_jsonl(path) -> list:
    p = Path(path)
    if not p.exists():
        return []
    with open(p, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def write_jsonl(path, records: list):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
    os.replace(tmp, p)


def atomic_write_json(path, obj):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    os.replace(tmp, p)


class RateLimitedClient:
    """Retrying HTTP client with global rate cap (politeness, respects API keys)."""
    def __init__(self, min_interval: float = 0.11, max_retries: int = 5, timeout: int = 120):
        self.min_interval = min_interval
        self.max_retries = max_retries
        self.timeout = timeout
        self._last = 0.0

    def _throttle(self):
        wait = self.min_interval - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.time()

    def get_json(self, url: str, params: dict, headers: dict | None = None):
        return json.loads(self.get_bytes(url, params, headers).decode("utf-8", "replace"))

    def get_bytes(self, url: str, params: dict, headers: dict | None = None) -> bytes:
        self._throttle()
        full = url + ("&" if "?" in url else "?") + urlencode(params)
        return self._req(Request(full, headers=headers or {}))

    def post_json(self, url: str, payload: dict, headers: dict | None = None):
        self._throttle()
        req = Request(url, data=json.dumps(payload).encode(), method="POST",
                      headers={"Content-Type": "application/json", **(headers or {})})
        return json.loads(self._req(req).decode("utf-8", "replace"))

    def _req(self, req) -> bytes:
        delay = 1.0
        last_err = None
        for attempt in range(self.max_retries + 1):
            try:
                with urlopen(req, timeout=self.timeout) as resp:
                    return resp.read()
            except HTTPError as e:
                last_err = e
                if e.code in (429, 500, 502, 503, 504) and attempt < self.max_retries:
                    time.sleep(delay)
                    delay = min(delay * 2, 60)
                    continue
                raise
            except (URLError, TimeoutError) as e:
                last_err = e
                if attempt < self.max_retries:
                    time.sleep(delay)
                    delay = min(delay * 2, 60)
                    continue
                raise
        raise last_err


def normalize_title(t: str) -> str:
    t = unicodedata.normalize("NFKD", t or "")
    t = re.sub(r"[^a-z0-9 ]+", " ", t.lower())
    return re.sub(r"\s+", " ", t).strip()


PUBTYPE_REVIEW = {"review", "systematic review", "meta-analysis"}
PUBTYPE_OTHER = {
    "editorial", "comment", "letter", "published erratum", "erratum", "news",
    "biography", "retraction of publication", "retracted publication",
    "congress", "interview", "autobiography", "address",
}


def normalize_publication_type(raw) -> str | None:
    """Map a PubMed publication-type list to the template's controlled values.

    Entrez returns things like
    "Journal Article,Research Support, N.I.H., Extramural" - a comma-joined
    list, not a single type. The schema accepts only
    {primary_research, review, protocol, other}.
    """
    if raw is None:
        return None
    parts = {p.strip().lower() for p in str(raw).split(",") if p.strip()}
    if not parts:
        return None
    if "protocol" in parts:
        return "protocol"
    if parts & PUBTYPE_REVIEW:
        return "review"
    if parts & PUBTYPE_OTHER:
        return "other"
    return "primary_research"


FM_RE = re.compile(r"^\ufeff?---\r?\n(?P<yaml>.*?)\r?\n---\r?\n", re.S)


def parse_front_matter(text: str) -> tuple:
    """Return (meta: dict, body_start: int, found: bool).

    The upstream front matter is *YAML-ish*, not YAML: titles contain unquoted
    `study: ...` colons, so a strict YAML load fails on some files. We try YAML
    first and fall back to a documented line-based parser that takes everything
    after the first `key:` as the value. No field is invented.
    """
    m = FM_RE.match(text)
    if not m:
        return {}, 0, False
    block = m.group("yaml")
    try:
        import yaml
        meta = yaml.safe_load(block) or {}
        if isinstance(meta, dict):
            return meta, m.end(), True
    except Exception:  # noqa: BLE001 - fall through to the tolerant parser
        pass
    meta = {}
    for line in block.splitlines():
        if not line.strip() or line.lstrip().startswith("#") or ":" not in line:
            continue
        key, val = line.split(":", 1)
        key = key.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            continue
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        meta[key] = val
    meta["_yaml_fallback"] = True
    return meta, m.end(), True


SECTION_TYPE_MAP = [
    (("abstract", "summary"), "Abstract"),
    (("introduction", "background", "preface"), "Introduction"),
    (("method", "materials and methods", "patients and methods"), "Methods"),
    (("result", "findings", "observation"), "Results"),
    (("discussion", "conclusion", "comment", "concluding remark"), "Discussion"),
    (("reference", "bibliography", "literature cited"), "References"),
    (("acknowledg", "funding", "author contribution"), "Acknowledgements"),
    (("supplementary", "supporting information", "supplement", "data availability"), "Supplementary"),
    (("case presentation",), "Case"),
]


def classify_section(heading: str) -> str:
    h = (heading or "").lower()
    for keys, name in SECTION_TYPE_MAP:
        if any(k in h for k in keys):
            return name
    return "Other"


_TOKENIZER = None
_TOKENIZER_ERROR = None


def token_count(text: str) -> tuple:
    """Return (count, method). Uses the vLLM venv tokenizer when importable,
    otherwise a documented whitespace approximation. Never silent: method returned."""
    global _TOKENIZER, _TOKENIZER_ERROR
    if _TOKENIZER is None and _TOKENIZER_ERROR is None:
        try:
            from transformers import AutoTokenizer  # noqa: PLC0415
            _TOKENIZER = AutoTokenizer.from_pretrained(
                os.environ.get("LLM_MODEL", "Qwen/Qwen3.5-4B"),
                cache_dir=os.environ.get("HF_HOME"), trust_remote_code=True)
        except Exception as e:  # noqa: BLE001
            _TOKENIZER_ERROR = repr(e)
    if _TOKENIZER is not None:
        return len(_TOKENIZER.encode(text, add_special_tokens=False)), "tokenizer:Qwen/Qwen3.5-4B"
    return max(1, len(re.findall(r"\S+", text))), f"approx:whitespace ({_TOKENIZER_ERROR})"


def fail_closed(checks: list) -> tuple:
    """Fail-closed gate (template + integrity requirement).
    checks: list of (rule_id, passed: bool, reason_if_failed).
    rule_id prefix drives severity: CRIT_* -> FAILED, PART_* -> PARTIAL, else REVIEW_REQUIRED.
    Returns (status, evidence_string)."""
    failures = [(rid, why) for rid, ok, why in checks if not ok]
    if not failures:
        return "COMPLETE", "; ".join(f"{rid}:pass" for rid, _, _ in checks)
    detail = "; ".join(f"{rid}:{why}" for rid, why in failures)
    if any(rid.startswith("CRIT") for rid, _ in failures):
        return "FAILED", detail
    if any(rid.startswith("PART") for rid, _ in failures):
        return "PARTIAL", detail
    return "REVIEW_REQUIRED", detail


_SEVERITY = {"COMPLETE": 0, "PARTIAL": 1, "REVIEW_REQUIRED": 2, "FAILED": 3}


def worst_status(*statuses: str) -> str:
    """Most severe of several fail-closed statuses (COMPLETE < PARTIAL < REVIEW < FAILED)."""
    return max(statuses, key=lambda s: _SEVERITY.get(s, 0)) if statuses else "COMPLETE"


def chunk_text(text: str, max_chars: int) -> list:
    """Paragraph-boundary chunking with hard wrap fallback (resume-safe prompt units)."""
    chunks, cur = [], ""
    for para in text.split("\n\n"):
        while len(para) > max_chars:  # hard-wrap oversized paragraph
            if cur.strip():
                chunks.append(cur.strip())
                cur = ""
            chunks.append(para[:max_chars])
            para = para[max_chars:]
        if len(cur) + len(para) + 2 > max_chars and cur.strip():
            chunks.append(cur.strip())
            cur = para
        else:
            cur = (cur + "\n\n" + para) if cur.strip() else (cur + para)
    if cur.strip():
        chunks.append(cur.strip())
    return chunks


def require_slurm(stage: str):
    """Refuse to run outside Slurm (policy: no login-node compute)."""
    print(f"[{now_utc()}] stage={stage} pid={os.getpid()} host={os.uname().nodename}")
    if os.environ.get("SLURM_JOB_ID") is None and "--allow-no-slurm" not in sys.argv:
        sys.exit("ERROR: not running under Slurm; submit via sbatch (policy: no login-node work)")


# --------------------------------------------------------------------------
# Progress reporting: side-by-side console (tqdm) + persistent log file
# --------------------------------------------------------------------------

class Progress:
    """tqdm bar (console) mirrored by a plain-text log file.

    Every call also lands in outputs/logs/<stage>.log, so the file tells the same
    story as the terminal. Works with or without a TTY (Slurm batch logs).
    """

    def __init__(self, stage: str, total: int | None = None, unit: str = "it",
                 desc: str | None = None, checkpoint: Path | None = None):
        try:
            from tqdm import tqdm as _tqdm
        except ImportError:  # graceful degradation, never fatal
            _tqdm = None
        self._tqdm_mod = _tqdm
        self.stage = stage
        self.total = total
        self.count = 0
        self.started = time.time()
        self.desc = desc or stage
        logdir = CORPUS_DIR / "logs"
        logdir.mkdir(parents=True, exist_ok=True)
        self.logpath = logdir / f"{stage}.log"
        self._fh = open(self.logpath, "a", encoding="utf-8")
        self.checkpoint_path = Path(checkpoint) if checkpoint else None
        self.bar = None
        if _tqdm is not None:
            self.bar = _tqdm(total=total, unit=unit, desc=self.desc,
                             dynamic_ncols=True, mininterval=2.0,
                             file=sys.stdout, leave=True)
        self.log(f"=== START stage={stage} total={total} host={os.uname().nodename} "
                 f"job={os.environ.get('SLURM_JOB_ID')} ===")

    def log(self, msg: str, level: str = "INFO"):
        line = f"[{now_utc()}] [{level}] [{self.stage}] {msg}"
        self._fh.write(line + "\n")
        self._fh.flush()
        if self.bar is not None:
            self.bar.write(line)  # keeps the bar intact on a TTY
        else:
            print(line, flush=True)

    def update(self, n: int = 1, detail: str | None = None, level: str = "INFO"):
        self.count += n
        if self.bar is not None:
            self.bar.update(n)
            if detail:
                self.bar.set_postfix_str(detail[:60])
        if detail:
            self.log(detail, level=level)

    def rate_str(self) -> str:
        el = max(time.time() - self.started, 1e-9)
        return f"{self.count / el:.2f} it/s, elapsed={el / 60:.1f}min"

    def close(self, summary: str = ""):
        if self.bar is not None:
            self.bar.close()
        self.log(f"=== END stage={self.stage} processed={self.count} {self.rate_str()} {summary} ===")
        self._fh.close()


class Checkpoint:
    """Resume-safe record store keyed by a stable id.

    Records are appended to <path> as JSONL. Re-running a stage skips ids
    already present *with the same input fingerprint*, so an upstream change
    (new title, new source bytes, new prompt version) invalidates only the
    affected records instead of silently reusing stale output.
    `compact()` rewrites atomically (dedup by key, last wins).
    """

    def __init__(self, path, key: str = "section_record_id"):
        self.path = Path(path)
        self.key = key
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.done = {}
        self.fingerprints = {}
        if self.path.exists():
            for rec in read_jsonl(self.path):
                if rec.get(self.key) is not None:
                    self.done[rec[self.key]] = rec
                    self.fingerprints[rec[self.key]] = rec.get("_input_fingerprint")
        self._fh = open(self.path, "a", encoding="utf-8")

    def has(self, k, fingerprint: str | None = None) -> bool:
        if k not in self.done:
            return False
        if fingerprint is None:
            return True
        return self.fingerprints.get(k) == fingerprint

    def add(self, rec: dict, fingerprint: str | None = None):
        rec = dict(rec)
        if fingerprint is not None:
            rec["_input_fingerprint"] = fingerprint
        self.done[rec[self.key]] = rec
        self.fingerprints[rec[self.key]] = fingerprint
        self._fh.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
        self._fh.flush()

    def compact(self):
        write_jsonl(self.path, list(self.done.values()))

    def close(self):
        self._fh.close()


def load_artifact_manifest() -> dict:
    """Per-artifact sha256 registry (releases/manifest hashes, template rule 5)."""
    p = CORPUS_DIR / "validation" / "artifact_hashes.json"
    if p.exists():
        return json.loads(p.read_text())
    return {}


def record_artifact_hash(relpath: str, digest: str):
    p = CORPUS_DIR / "validation" / "artifact_hashes.json"
    m = load_artifact_manifest()
    m[relpath] = {"sha256": digest, "recorded_at": now_utc()}
    atomic_write_json(p, m)


# --------------------------------------------------------------------------
# Master-template §2 tracking table + §5 extraction/curation log
# --------------------------------------------------------------------------

TRACKING_COLUMNS = ["Corpus ID", "Title", "DOI / PMID / PMCID", "Year", "Source / file path",
                    "Inclusion decision", "Processing status", "Full-text status",
                    "Annotation status", "Reviewer / notes"]


def write_tracking_table(papers: list, decisions: dict | None = None):
    """Emit corpus_tracking.csv with one row per paper (template §2)."""
    import csv
    p = CORPUS_DIR / "data" / "corpus_tracking.csv"
    p.parent.mkdir(parents=True, exist_ok=True)
    for fname in ("corpus_tracking.csv",):
        pass
    tmp = p.with_suffix(".csv.tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(TRACKING_COLUMNS)
        for pp in papers:
            ids = " / ".join(x for x in (
                f"DOI:{pp.get('DOI')}" if pp.get("DOI") else None,
                f"PMID:{pp.get('PMID')}" if pp.get("PMID") else None,
                f"PMCID:{pp.get('PMCID')}" if pp.get("PMCID") else None) if x)
            inc = (decisions or {}).get(pp["paper_id"], pp.get("inclusion_decision", "pending"))
            w.writerow([
                pp["paper_id"], pp.get("title") or "", ids,
                pp.get("publication_year") or "",
                pp.get("raw_file_path") or pp.get("source_file_path") or "",
                inc,
                pp.get("processing_status", "not_started"),
                pp.get("full_text_completeness", "not_checked"),
                pp.get("annotation_status", "not_started"),
                pp.get("reviewer_notes", ""),
            ])
    os.replace(tmp, p)
    return p


CURATION_COLUMNS = ["Corpus ID", "Date", "Stage", "Tool/person", "Tool version",
                    "Action/check", "Result", "Problem found", "Resolution"]


class CurationLog:
    """Append-only log in the template §5 shape (CSV), derived from stage events."""

    def __init__(self):
        self.path = CORPUS_DIR / "data" / "curation_log.csv"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            with open(self.path, "w", newline="", encoding="utf-8") as fh:
                import csv
                csv.writer(fh).writerow(CURATION_COLUMNS)

    def add(self, corpus_id: str, stage: str, tool: str, tool_version: str,
            action: str, result: str, problem: str = "", resolution: str = ""):
        import csv
        with open(self.path, "a", newline="", encoding="utf-8") as fh:
            csv.writer(fh).writerow([
                corpus_id, now_utc()[:10], CURATION_STAGE.get(stage, stage),
                tool, tool_version, action, result, problem, resolution,
            ])
