"""Deterministic cleanup of the catalogue extraction (Phase A of
docs/catalogue_cleanup_plan.md). No model calls; runs on CPU in about a minute.

Reads a `catalogue_ner.py` output directory (default: the repaired v2 run) and
writes a cleaned copy. The input is never modified, and no record is dropped
silently: every input record ends with a `v3_status` of KEPT,
MERGED_INTO:<id> or DUPLICATE_OF:<id>, and the folded records are written to
`_removed.jsonl` in full.

Steps (IDs match the plan):
  A2/A3  integer-0 and placeholder strings ("n/a", "not stated", ...) -> blank
  A5     `direction` normalised to the extraction vocabulary
  A6     `direction` checked against the evidence wording (flag only)
  A4     findings tagged by section (`finding_source`) and for citing other
         work (`cites_other_work`) -> `is_primary_finding` YES / NO / REVIEW
  A7     accessions validated by pattern; non-IDs moved out of the ID column
  A9     counts checked against the section text; digit-concatenation
         artefacts (e.g. "120-150" -> 120150) blanked, huge values flagged
  A10    unlocated evidence quotes re-found with normalised + fuzzy matching
  A1     exact duplicates folded
  A11    repeated records within a paper merged when no structured field
         conflicts
  A8     each paper's corpus BioProject added as a dataset when no record
         already carries it

Usage:
    python src/scripts/vllm_termpop/clean_catalogue.py \
        [--input_dir outputs/results/catalogue_ner_v2] \
        [--output_dir outputs/results/catalogue_v3_clean]

Outputs (in --output_dir):
    catalogue_records.jsonl     cleaned records (authoritative)
    catalogue_<entity>.csv      v2 columns + appended v3 columns
    _removed.jsonl              folded records, unchanged, with v3_status
    _v2_to_v3_map.csv           every input id -> status
    review_*.csv                rows flagged for a reviewer
    _clean_report.json, CLEAN_REPORT.md
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
import unicodedata
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path

csv.field_size_limit(sys.maxsize)

REPO_ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
sys.path.insert(0, str(REPO_ROOT / "src"))

ENTITIES = ("datasets", "data_assets", "cohorts", "samples", "assays", "findings")
ID_FIELD = {"datasets": "dataset_id", "data_assets": "asset_id", "cohorts": "cohort_id",
            "samples": "sample_group_id", "assays": "assay_id", "findings": "finding_id"}
NOTE_FIELD = {"datasets": "catalogue_notes"}  # every other entity uses "notes"

# Columns appended to the v2 tables, per entity.
V3_COLUMNS = {
    "_all": ["v3_status", "merged_from", "evidence_match"],
    "findings": ["finding_source", "cites_other_work", "is_primary_finding",
                 "direction_original", "direction_flag"],
    "datasets": ["repository_accession_original", "accession_ids", "accession_valid",
                 "record_source"],
    "data_assets": ["accession_original", "accession_ids", "accession_valid"],
    "cohorts": ["count_flag"],
    "samples": ["count_flag"],
}

# ── A2/A3 placeholders ───────────────────────────────────────────────────────
PLACEHOLDERS = {"n/a", "na", "n.a.", "none", "null", "nil", "-", "--", "unknown",
                "not stated", "not_stated", "not specified", "not reported",
                "not mentioned", "not available", "not applicable",
                "not_applicable", "unspecified", "not provided", "not given", "0"}
# Values that are legitimate controlled-vocabulary tokens in these fields.
VOCAB_KEEP = {
    "direction": {"not_stated"},
    "data_availability_status": {"unknown"},
    "access_status": {"unknown"},
    "original_or_reused": {"unknown"},
    "longitudinal": {"not_applicable"},
}
COUNT_FIELDS = {"participant_count", "sample_count", "file_size_bytes"}
STAT_FIELDS = {"effect_estimate", "p_value", "q_value", "confidence_interval"}
ZERO_IN_TEXT = re.compile(r"(?<![\d.])0(?:\.0+)?(?![\d.])")


def clean_value(field, value, evidence):
    """-> (clean string or int, changed?)"""
    if value is None:
        return "", False
    if isinstance(value, bool):
        return str(value), False
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True), True
    if isinstance(value, list):
        value = "; ".join(str(x).strip() for x in value if str(x).strip())
    if isinstance(value, (int, float)):
        if value == 0:  # a p/q value of exactly 0 is never reportable
            keep = (field in STAT_FIELDS - {"p_value", "q_value"}
                    and ZERO_IN_TEXT.search(evidence or ""))
            return ("0" if keep else ""), not keep
        if field in COUNT_FIELDS:
            return (int(value), False) if float(value).is_integer() else ("", True)
        return str(value), False
    v = str(value).strip()
    low = v.lower().strip(" .")
    if low == "0":
        return clean_value(field, 0, evidence)
    if low in VOCAB_KEEP.get(field, ()):
        return v, False
    if low in PLACEHOLDERS or low.replace("_", " ") in PLACEHOLDERS:
        return "", True
    return v, False


# ── A5/A6 direction ──────────────────────────────────────────────────────────
DIRECTIONS = ("INCREASE", "DECREASE", "NO_ASSOCIATION", "MIXED", "NOT_STATED")
_DIR_SYNONYMS = {
    "increase": "INCREASE", "increased": "INCREASE", "higher": "INCREASE",
    "up": "INCREASE", "positive": "INCREASE", "enriched": "INCREASE",
    "decrease": "DECREASE", "decreased": "DECREASE", "lower": "DECREASE",
    "down": "DECREASE", "negative": "DECREASE", "depleted": "DECREASE",
    "no_association": "NO_ASSOCIATION", "no association": "NO_ASSOCIATION",
    "no_change": "NO_ASSOCIATION", "no change": "NO_ASSOCIATION",
    "no difference": "NO_ASSOCIATION", "unchanged": "NO_ASSOCIATION",
    "not significant": "NO_ASSOCIATION", "mixed": "MIXED",
}
INC = re.compile(r"\b(increas\w*|higher|elevat\w*|enrich\w*|greater|more abundant|"
                 r"upregulat\w*|up-regulat\w*|overrepresent\w*|over-represent\w*|"
                 r"expan\w*|bloom\w*|rose|rise[sn]?)\b", re.I)
DEC = re.compile(r"\b(decreas\w*|lower|reduc\w*|deplet\w*|less abundant|fewer|"
                 r"declin\w*|downregulat\w*|down-regulat\w*|diminish\w*|"
                 r"underrepresent\w*|under-represent\w*|loss|lost|drop\w*)\b", re.I)
NONSIG = re.compile(r"\b(?:no|not|n't|nor|without|neither)\b[^.;]{0,40}?\b(?:significant\w*|"
                    r"differ\w*|change[sd]?|associat\w*|correlat\w*|affect\w*)\b|"
                    r"\b(?:similar|comparable|unchanged|unaffected)\b|\bn\.s\.", re.I)


def normalise_direction(value):
    v = str(value or "").strip()
    low = v.lower().replace("-", " ").strip(" .")
    if v.upper() in DIRECTIONS:
        return v.upper()
    if low in _DIR_SYNONYMS:
        return _DIR_SYNONYMS[low]
    parts = {_DIR_SYNONYMS.get(p.strip()) for p in re.split(r"[;,/]| and ", low) if p.strip()}
    if {"INCREASE", "DECREASE"} <= parts:
        return "MIXED"
    if len(parts) == 1 and None not in parts:
        return parts.pop()
    return "NOT_STATED"


def direction_flag(direction, text):
    """Rule cues in the evidence that disagree with `direction` (flag only)."""
    inc, dec, nonsig = bool(INC.search(text)), bool(DEC.search(text)), bool(NONSIG.search(text))
    if direction in ("INCREASE", "DECREASE"):
        if nonsig:
            return "NONSIGNIFICANCE_WORDING"
        if direction == "INCREASE" and dec and not inc:
            return "OPPOSITE_WORDING"
        if direction == "DECREASE" and inc and not dec:
            return "OPPOSITE_WORDING"
    elif direction == "NO_ASSOCIATION" and (inc or dec) and not nonsig:
        return "DIRECTIONAL_WORDING"
    elif direction == "NOT_STATED" and (inc or dec) and not nonsig:
        return "DIRECTION_RECOVERABLE"
    return ""


# ── A4 finding source ────────────────────────────────────────────────────────
_SOURCE_RULES = (
    ("ABSTRACT", ("abstract", "summary")),
    ("RESULT", ("result",)),
    ("DISCUSSION", ("discussion",)),
    ("CONCLUSION", ("conclusion",)),
    ("BACKGROUND", ("introduction", "background")),
    ("METHODS", ("method", "material", "experimental", "procedure", "study design")),
    ("REFERENCES", ("reference", "bibliograph", "literature cited")),
    ("BACKMATTER", ("acknowledg", "conflict", "competing", "author contribution",
                    "ethic", "funding", "abbreviation", "data avail", "data access",
                    "supplement", "postamble", "footnote", "declaration", "consent")),
)
CITATION = re.compile(
    r"[a-z)\]]\d{1,3}(?:\s?[-–,]\s?\d{1,3})+(?=[\s.,;:)]|$)"   # dysbiosis17-20
    r"|\[\s?\d{1,3}(?:\s?[-–,]\s?\d{1,3})*\s?\]"              # [12], [3-5]
    r"|\bet al\.?,?\s*\(?\d{4}"                                # Smith et al. 2019
    r"|\(\s?[A-Z][A-Za-z'-]+(?: (?:and|&) [A-Z][A-Za-z'-]+)?,? \d{4}[a-z]?\s?[;)]"
    r"|\(\s?\d{1,3}(?:\s?[-–,]\s?\d{1,3})+\s?\)")              # (4, 7) / (4-7)


def finding_source(section_path):
    head = re.sub(r"^[\d.\s]+", "", (section_path or "").split(">")[0]).strip().lower()
    for label, keys in _SOURCE_RULES:
        if any(k in head for k in keys):
            return label
    return "UNKNOWN"


def primary_verdict(source, cites):
    if source in ("BACKGROUND", "REFERENCES", "BACKMATTER", "METHODS") or cites:
        return "NO"
    if source in ("RESULT", "ABSTRACT"):
        return "YES"
    return "REVIEW"


# ── A7 accessions ────────────────────────────────────────────────────────────
ACCESSION_PATTERNS = (
    ("BioProject", r"\bPRJ(?:NA|EB|DB|CA)\d+\b"),
    ("BioSample", r"\bSAM(?:N|EA|D|C)\d+\b"),
    ("SRA/ENA/DDBJ", r"\b[SED]R[APXRS]\d{6,}\b"),
    ("GEO", r"\bG(?:SE|SM|PL|DS)\d+\b"),
    ("ArrayExpress", r"\bE-[A-Z]{4}-\d+\b"),
    ("MetaboLights", r"\bMTBLS\d+\b"),
    ("MassIVE", r"\bMSV\d{9}\b"),
    ("PRIDE", r"\bPXD\d{6}\b"),
    ("dbGaP", r"\bphs\d{6}(?:\.v\d+)?(?:\.p\d+)?\b"),
    ("EGA", r"\bEGA[SDC]\d{11}\b"),
    ("MG-RAST", r"\bmg[pm]\d+(?:\.\d+)?\b"),
    ("GSA", r"\b(?:CRA|HRA)\d{6}\b"),
    ("CNGB", r"\bCNP\d{7}\b"),
    ("Assembly", r"\bGC[AF]_\d{9}(?:\.\d+)?\b"),
    ("Zenodo", r"\b10\.5281/zenodo\.\d+\b"),
    ("Figshare", r"\b10\.6084/m9\.figshare\.\d+\b"),
    ("Dryad", r"\b10\.5061/dryad\.[\w.]+\b"),
    ("GenBank", r"\b[A-Z]{1,2}\d{5,6}(?:\.\d+)?\b"),
)
QIITA = re.compile(r"qiita\D{0,30}?(\d{2,6})", re.I)
URL = re.compile(r"(?:https?://|www\.|github\.com/)\S+", re.I)


def find_accessions(text):
    """-> [(type, id)] in order of appearance, de-duplicated."""
    text = text or ""
    hits = []
    for kind, pat in ACCESSION_PATTERNS:
        for m in re.finditer(pat, text):
            hits.append((m.start(), kind, m.group(0)))
    for m in QIITA.finditer(text):
        hits.append((m.start(), "Qiita", "qiita:" + m.group(1)))
    out, seen = [], set()
    for _, kind, acc in sorted(hits):
        if acc not in seen and not any(acc in s for s in seen):
            seen.add(acc)
            out.append((kind, acc))
    return out


def clean_accession(f, entity):
    """A7 on one record's fields (in place)."""
    acc_field = "repository_accession" if entity == "datasets" else "accession"
    url_field = "dataset_url" if entity == "datasets" else "repository_url"
    original = str(f.get(acc_field) or "")
    f[f"{acc_field}_original"] = ""
    f["accession_ids"], f["accession_valid"] = "", ""
    if not original.strip():
        if entity == "datasets":
            f["accession_type"] = ""  # a type with no accession describes nothing
        return
    ids = find_accessions(original)
    if ids:
        f["accession_ids"] = "; ".join(a for _, a in ids)
        f["accession_valid"] = "YES"
        if entity == "datasets":
            f["accession_type"] = "; ".join(dict.fromkeys(k for k, _ in ids))
        clean = "; ".join(a for _, a in ids)
        if clean != original.strip():
            f[f"{acc_field}_original"] = original
            f[acc_field] = clean
        return
    f["accession_valid"] = "NO"
    f[f"{acc_field}_original"] = original
    f[acc_field] = ""
    if entity == "datasets":
        f["accession_type"] = ""
    url = URL.search(original)
    if url and not str(f.get(url_field) or "").strip():
        f[url_field] = url.group(0).rstrip(".,;)")


# ── A9 counts ────────────────────────────────────────────────────────────────
_WORDS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen "
    "fourteen fifteen sixteen seventeen eighteen nineteen".split())}
_WORDS.update({w: 10 * i for i, w in enumerate(
    "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()) if w != "_"})
_SCALE = {"hundred": 100, "thousand": 1_000, "million": 1_000_000, "billion": 1_000_000_000}
NUMBER = re.compile(r"(\d{1,3}(?:[,   ]\d{3})+|\d+(?:\.\d+)?)\s*"
                    r"(hundred|thousand|million|billion)?", re.I)
PARTICIPANT_MAX, SAMPLE_MAX = 50_000, 500_000


def numbers_in(text):
    out = set()
    for m in NUMBER.finditer(text or ""):
        raw = re.sub(r"[,   ]", "", m.group(1))
        try:
            val = float(raw)
        except ValueError:
            continue
        if m.group(2):
            val *= _SCALE[m.group(2).lower()]
        if val.is_integer():
            out.add(int(val))
    words = re.findall(r"[a-z]+", (text or "").lower())
    for i, w in enumerate(words):
        if w in _WORDS:
            val = _WORDS[w]
            if val >= 20 and i + 1 < len(words) and words[i + 1] in _WORDS and _WORDS[words[i + 1]] < 10:
                val += _WORDS[words[i + 1]]
            out.add(val)
            if val >= 20:
                out.add(_WORDS[w])
    return out


def check_counts(f, entity, section_text):
    """A9 (in place): blank counts that never appear in the source section."""
    flags = []
    fields = ("participant_count", "sample_count") if entity == "cohorts" else ("sample_count",)
    known = None
    for field in fields:
        v = f.get(field)
        if v in ("", None):
            continue
        try:
            n = int(v)
        except (TypeError, ValueError):
            f[field] = ""
            flags.append(f"{field}={v}:NOT_INTEGER")
            continue
        if known is None:
            known = numbers_in(section_text) | numbers_in(f.get("evidence_text"))
        if n not in known:
            f[field] = ""
            flags.append(f"{field}={n}:NOT_IN_SOURCE_TEXT")
            continue
        limit = PARTICIPANT_MAX if field == "participant_count" else SAMPLE_MAX
        if n > limit:  # typically read counts or population figures
            f[field] = ""
            flags.append(f"{field}={n}:IMPLAUSIBLY_LARGE")
    f["count_flag"] = "; ".join(flags)


# ── A10 evidence relocation ──────────────────────────────────────────────────
def _norm_map(text):
    """Alphanumeric-only lowercase form of `text` and its index map back."""
    chars, idx = [], []
    for i, ch in enumerate(text):
        for c in unicodedata.normalize("NFKC", ch).lower():
            if c.isalnum():
                chars.append(c)
                idx.append(i)
    return "".join(chars), idx


class SectionIndex:
    def __init__(self, texts):
        self.texts = texts
        self._norm = {}

    def norm(self, key):
        if key not in self._norm:
            self._norm[key] = _norm_map(self.texts.get(key, ""))
        return self._norm[key]


def relocate(quote, sec_norm, sec_idx, min_ratio=0.9):
    """-> (start, end, how) in original section coordinates, or None."""
    q, _ = _norm_map(quote or "")
    if len(q) < 12 or not sec_norm:
        return None
    pos = sec_norm.find(q)
    if pos >= 0:
        return sec_idx[pos], sec_idx[pos + len(q) - 1] + 1, "NORMALIZED"
    if len(q) < 30:
        return None
    best = None
    k = 20
    for off in sorted({0, len(q) // 4, len(q) // 2, 3 * len(q) // 4, len(q) - k}):
        shingle = q[off:off + k]
        start = sec_norm.find(shingle)
        hits = 0
        while start >= 0 and hits < 5:
            lo = max(0, start - off)
            window = sec_norm[lo:lo + len(q) + 10]
            sm = SequenceMatcher(None, q, window, autojunk=False)
            ratio = sm.ratio() * (len(window) + len(q)) / (2 * len(q))
            if ratio >= min_ratio and (best is None or ratio > best[0]):
                blocks = [b for b in sm.get_matching_blocks() if b.size]
                a, b = lo + blocks[0].b, lo + blocks[-1].b + blocks[-1].size
                best = (ratio, a, b)
            start = sec_norm.find(shingle, start + 1)
            hits += 1
    if best is None:
        return None
    _, a, b = best
    return sec_idx[a], sec_idx[b - 1] + 1, "FUZZY_%.2f" % min(best[0], 1.0)


def load_section_texts(seg_dir):
    from cdm_pipeline.ner.runner_sections import load_sections
    units, _ = load_sections(seg_dir, None, body_only=False)
    return {(u["cid"], u["section_id"]): u["text"] or "" for u in units}


# ── A1/A11 duplicates and merging ────────────────────────────────────────────
MERGE_KEYS = {
    "findings": ("taxon_or_feature", "direction", "outcome", "comparison_or_exposure",
                 "population_subgroup", "body_site"),
    "assays": ("assay_type", "target_gene_or_region", "sequencing_platform"),
    # samples carry no group label, so two groups with the same site/type/count
    # ("CD flare (4)" vs "CD remission (4)") are indistinguishable: exact
    # duplicates only.
    "samples": None,
    "cohorts": ("cohort_label",),
    "datasets": ("accession_ids", "dataset_title"),
    "data_assets": ("accession_ids", "asset_name"),
}
# Short structured fields: two records that disagree on any of these are
# different things and are never merged.
CONFLICT_FIELDS = {
    "participant_count", "sample_count", "file_size_bytes", "direction",
    "effect_measure", "effect_estimate", "confidence_interval", "p_value", "q_value",
    "cohort_role", "longitudinal", "original_or_reused", "data_availability_status",
    "access_status", "dataset_role", "country_or_region", "age_group",
    "sequencing_platform", "target_gene_or_region", "taxonomic_rank", "sample_type",
    "body_site", "format", "asset_type", "accession_ids", "collection_timepoint",
}
NOT_CONTENT = {"evidence_text", "evidence_location", "notes", "catalogue_notes",
               "verification_status", "extraction_method", "v3_status", "merged_from",
               "evidence_match"}
SOURCE_RANK = {"RESULT": 0, "ABSTRACT": 1, "DISCUSSION": 2, "CONCLUSION": 3,
               "UNKNOWN": 4, "METHODS": 5, "BACKGROUND": 6, "BACKMATTER": 7, "REFERENCES": 8}


def _k(v):
    return re.sub(r"[^a-z0-9]+", " ", str(v).lower()).strip()


def merge_records(records, entity):
    """A1 + A11 within each paper. Returns (kept, folded)."""
    id_f = ID_FIELD[entity]
    keys = MERGE_KEYS[entity]
    kept, folded = [], []

    # A1 exact duplicates (all content equal, ignoring id/location/notes)
    seen = {}
    survivors = []
    for r in records:
        f = r["fields"]
        sig = (r["paper_id"], json.dumps({k: _k(v) for k, v in sorted(f.items())
                                          if k not in NOT_CONTENT and k != id_f}),
               _k(f.get("evidence_text", "")))
        if sig in seen:
            f["v3_status"] = "DUPLICATE_OF:" + seen[sig]["fields"][id_f]
            folded.append(r)
            continue
        seen[sig] = r
        survivors.append(r)
    if keys is None:
        return survivors, folded

    # A11 merge on key fields, refusing any structured-field conflict
    def rank(r):
        f = r["fields"]
        filled = sum(1 for k, v in f.items() if k not in NOT_CONTENT and str(v).strip())
        return (-int(r["evidence_verified"]), SOURCE_RANK.get(f.get("finding_source"), 4),
                -filled, f[id_f])

    groups = defaultdict(list)
    for r in survivors:
        f = r["fields"]
        key = tuple(_k(f.get(k, "")) for k in keys)
        if entity in ("datasets", "data_assets") and key[0]:
            key = (key[0],)  # same accession is the same dataset/asset
        if not key[0] and not (entity in ("datasets", "data_assets") and key[-1]):
            kept.append(r)
            continue
        groups[(r["paper_id"], key)].append(r)

    for _, grp in groups.items():
        clusters = []  # [survivor, [members]]
        for r in sorted(grp, key=rank):
            f = r["fields"]
            for cl in clusters:
                sf = cl[0]["fields"]
                if all(not str(sf.get(c, "")).strip() or not str(f.get(c, "")).strip()
                       or _k(sf[c]) == _k(f[c]) for c in CONFLICT_FIELDS):
                    cl[1].append(r)
                    for k, v in f.items():  # union: fill the survivor's blanks
                        if k not in NOT_CONTENT and k != id_f and str(v).strip() \
                                and not str(sf.get(k, "")).strip():
                            sf[k] = v
                    break
            else:
                clusters.append([r, []])
        for survivor, members in clusters:
            if members:
                sid = survivor["fields"][id_f]
                survivor["fields"]["merged_from"] = "; ".join(m["fields"][id_f] for m in members)
                survivor["merged_evidence"] = [
                    {"id": m["fields"][id_f], "evidence_text": m["fields"].get("evidence_text", ""),
                     "evidence_location": m["fields"].get("evidence_location", "")}
                    for m in members]
                for m in members:
                    m["fields"]["v3_status"] = "MERGED_INTO:" + sid
                    folded.append(m)
            kept.append(survivor)
    return kept, folded


# ── A8 BioProject datasets ───────────────────────────────────────────────────
def bioproject_rows(kept_datasets, papers_csv, header, run_id):
    have = defaultdict(set)
    for r in kept_datasets:
        f = r["fields"]
        blob = " ".join(str(f.get(k, "")) for k in
                        ("repository_accession", "repository_accession_original",
                         "dataset_url", "dataset_description", "evidence_text"))
        have[r["paper_id"]].update(a for _, a in find_accessions(blob))
    rows, n = [], 0
    with open(papers_csv, newline="", encoding="utf-8") as fh:
        for p in csv.DictReader(fh):
            acc, pid = p.get("bioproject", "").strip(), p["paper_id"]
            if not acc or acc in have[pid]:
                continue
            n += 1
            f = {k: "" for k in header}
            f.update({
                "dataset_id": "HMDATA_BP_%06d" % n, "paper_id": pid,
                "dataset_title": f"BioProject {acc}",
                "dataset_description": "Corpus-linked BioProject for this paper "
                                       "(not extracted from the paper text).",
                "repository_name": "NCBI BioProject", "repository_accession": acc,
                "accession_type": "BioProject",
                "dataset_url": f"https://www.ncbi.nlm.nih.gov/bioproject/{acc}",
                "evidence_location": "external: corpus papers.csv bioproject "
                                     f"({p.get('bioproject_match_method', '')})",
                "verification_status": "LINKED_FROM_CORPUS",
                "accession_ids": acc, "accession_valid": "YES",
                "record_source": "corpus_bioproject_link",
                "v3_status": "ADDED", "merged_from": "", "evidence_match": "NO_QUOTE",
            })
            rows.append({"entity_type": "datasets", "paper_id": pid, "section_id": "",
                         "section_path": "", "segment_mode": "", "char_start": None,
                         "char_end": None, "evidence_verified": 0, "fields": f,
                         "extraction_model": "", "prompt_version": "",
                         "extraction_run_id": run_id})
    return rows


def write_papers(kept, papers_csv, out_path):
    """papers table for the full corpus, with per-paper counts recomputed."""
    per = defaultdict(Counter)
    for r in kept:
        per[r["paper_id"]][r["entity_type"]] += 1
    with open(papers_csv, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        cols, rows = reader.fieldnames, list(reader)
    for p in rows:
        c = per[p["paper_id"]]
        for e in ENTITIES:
            if f"n_{e}" in p:
                p[f"n_{e}"] = c[e]
        p["n_records_total"] = sum(c.values())
    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    return rows


def check_corpus(records, texts, papers_csv, expected):
    """Fail closed unless records, section texts and papers.csv agree on the corpus."""
    with open(papers_csv, newline="", encoding="utf-8") as fh:
        papers = {p["paper_id"] for p in csv.DictReader(fh)}
    text_papers = {cid for cid, _ in texts}
    rec_papers = {r["paper_id"] for r in records}
    problems = []
    if len(papers) != expected:
        problems.append(f"papers.csv has {len(papers)} papers, expected {expected}")
    if text_papers != papers:
        problems.append(f"section texts cover {len(text_papers)} papers; "
                        f"{len(papers - text_papers)} missing, {len(text_papers - papers)} extra")
    if rec_papers - papers:
        problems.append(f"{len(rec_papers - papers)} record paper_ids not in papers.csv")
    if problems:
        sys.exit("corpus check failed: " + "; ".join(problems))
    return sorted(papers - rec_papers)


# ── metrics ──────────────────────────────────────────────────────────────────
def metrics(records):
    by = defaultdict(list)
    for r in records:
        by[r["entity_type"]].append(r)
    out = {"records": len(records), "papers_with_records": len({r["paper_id"] for r in records}),
           "per_entity": {e: len(by[e]) for e in ENTITIES}}
    out["evidence_located_pct"] = {
        e: round(100 * sum(r["evidence_verified"] for r in by[e]) / max(1, len(by[e])), 1)
        for e in ENTITIES}
    ph = 0
    v3_cols = {c for cols in V3_COLUMNS.values() for c in cols}
    for r in records:
        for k, v in r["fields"].items():
            if k == "direction" or k in VOCAB_KEEP or k in v3_cols:
                continue
            if isinstance(v, (int, float)) and not isinstance(v, bool) and v == 0:
                ph += 1
            elif isinstance(v, str) and v.strip().lower().strip(" .") in PLACEHOLDERS:
                ph += 1
    out["placeholder_cells"] = ph
    accs = [r["fields"].get("repository_accession") for r in by["datasets"]]
    accs = [a for a in accs if str(a or "").strip()]
    out["dataset_accessions_filled"] = len(accs)
    out["dataset_accessions_valid_pct"] = round(
        100 * sum(1 for a in accs if find_accessions(str(a))) / max(1, len(accs)), 1)
    return out


# ── main ─────────────────────────────────────────────────────────────────────
def main(argv=None):
    ap = argparse.ArgumentParser(description="Phase A deterministic catalogue cleanup")
    ap.add_argument("--input_dir", default=str(REPO_ROOT / "outputs/results/catalogue_ner_v2"))
    ap.add_argument("--output_dir", default=str(REPO_ROOT / "outputs/results/catalogue_v3_clean"))
    ap.add_argument("--papers_csv", default=str(REPO_ROOT / "releases/data_catalogue/tables/papers.csv"))
    ap.add_argument("--seg_dir", default=None,
                    help="segmented markdown dir (default: the NER runner's default)")
    ap.add_argument("--expected_papers", type=int, default=453,
                    help="corpus size; the run aborts if inputs disagree with it")
    args = ap.parse_args(argv)

    t0 = time.time()
    in_dir, out_dir = Path(args.input_dir), Path(args.output_dir)
    if out_dir.resolve() == in_dir.resolve():
        sys.exit("refusing to write into the input directory")
    out_dir.mkdir(parents=True, exist_ok=True)
    run_id = "CATCLEAN_%s" % time.strftime("%Y%m%dT%H%M%S")

    with open(in_dir / "catalogue_records.jsonl", encoding="utf-8") as fh:
        records = [json.loads(line) for line in fh if line.strip()]
    headers = {}
    for e in ENTITIES:
        with open(in_dir / f"catalogue_{e}.csv", newline="", encoding="utf-8") as fh:
            headers[e] = next(csv.reader(fh))
    before = metrics(records)
    print(f"loaded {len(records)} records from {in_dir}")

    if args.seg_dir:
        texts = load_section_texts(args.seg_dir)
    else:
        from cdm_pipeline.ner.runner_sections import SEG_DIR_DEFAULT
        texts = load_section_texts(SEG_DIR_DEFAULT)
    index = SectionIndex(texts)
    print(f"loaded {len(texts)} section texts")
    no_records = check_corpus(records, texts, args.papers_csv, args.expected_papers)
    print(f"corpus check: {args.expected_papers} papers; without extracted records: {no_records}")

    steps = Counter()
    for r in records:
        e, f = r["entity_type"], r["fields"]
        ev = str(f.get("evidence_text") or "")
        sec_key = (r["paper_id"], r["section_id"])
        # A2/A3
        for k in list(f):
            v, changed = clean_value(k, f[k], ev)
            if changed:
                steps["A2_A3_placeholder_cells_blanked"] += 1
            f[k] = v
        f["v3_status"], f["merged_from"] = "KEPT", ""
        # A10
        if r["evidence_verified"]:
            f["evidence_match"] = "AS_EXTRACTED"
        elif not ev.strip():
            f["evidence_match"] = "NO_QUOTE"
        else:
            sec_norm, sec_idx = index.norm(sec_key)
            hit = relocate(ev, sec_norm, sec_idx)
            if hit:
                cs, ce, how = hit
                r["char_start"], r["char_end"], r["evidence_verified"] = cs, ce, 1
                base = re.sub(r"\s+chars \d+-\d+$", "", f.get("evidence_location", ""))
                f["evidence_location"] = f"{base} chars {cs}-{ce}"
                nf = NOTE_FIELD.get(e, "notes")
                if f.get(nf) == "EVIDENCE_QUOTE_NOT_FOUND_IN_SECTION":
                    f[nf] = ""
                f["evidence_match"] = how
                steps["A10_evidence_relocated"] += 1
            else:
                f["evidence_match"] = "NOT_FOUND"
        # A5/A6/A4
        if e == "findings":
            f["direction_original"] = f.get("direction", "")
            f["direction"] = normalise_direction(f["direction_original"])
            if f["direction"] != str(f["direction_original"]).strip().upper():
                steps["A5_direction_normalised"] += 1
            f["direction_flag"] = direction_flag(f["direction"], ev or f.get("finding_text", ""))
            if f["direction_flag"]:
                steps["A6_direction_flagged"] += 1
            f["finding_source"] = finding_source(r["section_path"])
            f["cites_other_work"] = "YES" if CITATION.search(ev) else "NO"
            f["is_primary_finding"] = primary_verdict(f["finding_source"],
                                                      f["cites_other_work"] == "YES")
        # A7
        if e in ("datasets", "data_assets"):
            clean_accession(f, e)
            if f["accession_valid"] == "NO":
                steps["A7_accession_text_moved"] += 1
            if e == "datasets":
                f["record_source"] = "extracted"
        # A9
        if e in ("cohorts", "samples"):
            check_counts(f, e, texts.get(sec_key, ""))
            for fl in filter(None, f["count_flag"].split("; ")):
                steps["A9_" + fl.split(":")[1]] += 1

    kept, folded = [], []
    for e in ENTITIES:
        k, fo = merge_records([r for r in records if r["entity_type"] == e], e)
        kept += k
        folded += fo
    steps["A1_exact_duplicates_folded"] = sum(1 for r in folded if r["fields"]["v3_status"].startswith("DUPLICATE_OF"))
    steps["A11_records_merged"] = sum(1 for r in folded if r["fields"]["v3_status"].startswith("MERGED_INTO"))

    ds_header = headers["datasets"] + [c for c in V3_COLUMNS["_all"] + V3_COLUMNS["datasets"]
                                       if c not in headers["datasets"]]
    added = bioproject_rows([r for r in kept if r["entity_type"] == "datasets"],
                            args.papers_csv, ds_header, run_id)
    kept += added
    steps["A8_bioproject_datasets_added"] = len(added)

    order = {e: i for i, e in enumerate(ENTITIES)}
    kept.sort(key=lambda r: (r["paper_id"], order[r["entity_type"]], r["fields"][ID_FIELD[r["entity_type"]]]))
    for r in kept:
        r["clean_run_id"] = run_id

    # ── write ───────────────────────────────────────────────────────────────
    paper_rows = write_papers(kept, args.papers_csv, out_dir / "catalogue_papers.csv")
    with open(out_dir / "catalogue_records.jsonl", "w", encoding="utf-8") as fh:
        for r in kept:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(out_dir / "_removed.jsonl", "w", encoding="utf-8") as fh:
        for r in folded:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    for e in ENTITIES:
        cols = headers[e] + [c for c in V3_COLUMNS["_all"] + V3_COLUMNS.get(e, [])
                             if c not in headers[e]]
        with open(out_dir / f"catalogue_{e}.csv", "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            w.writerows(r["fields"] for r in kept if r["entity_type"] == e)
    with open(out_dir / "_v2_to_v3_map.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["entity_type", "paper_id", "v2_id", "v3_status"])
        for r in sorted(kept + folded, key=lambda r: (r["entity_type"], r["fields"][ID_FIELD[r["entity_type"]]])):
            w.writerow([r["entity_type"], r["paper_id"], r["fields"][ID_FIELD[r["entity_type"]]],
                        r["fields"]["v3_status"]])

    review = {
        "review_direction_flags.csv": ("findings", "direction_flag",
                                       ["finding_id", "paper_id", "direction", "direction_flag",
                                        "taxon_or_feature", "outcome", "evidence_text"]),
        "review_findings_not_primary.csv": ("findings", None,
                                            ["finding_id", "paper_id", "finding_source",
                                             "cites_other_work", "is_primary_finding",
                                             "evidence_location", "evidence_text"]),
        "review_count_flags.csv": ("cohorts+samples", "count_flag",
                                   ["paper_id", "count_flag", "evidence_text"]),
        "review_invalid_accessions.csv": ("datasets+data_assets", None,
                                          ["paper_id", "repository_accession_original",
                                           "accession_original", "dataset_url",
                                           "repository_url", "evidence_text"]),
    }
    for name, (ents, flag, cols) in review.items():
        ents = ents.split("+")
        if name == "review_findings_not_primary.csv":
            rows = [r["fields"] for r in kept if r["entity_type"] == "findings"
                    and r["fields"]["is_primary_finding"] != "YES"]
        elif name == "review_invalid_accessions.csv":
            rows = [r["fields"] for r in kept if r["entity_type"] in ents
                    and r["fields"].get("accession_valid") == "NO"]
        else:
            rows = [r["fields"] for r in kept if r["entity_type"] in ents and r["fields"].get(flag)]
        with open(out_dir / name, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=["record_id"] + cols, extrasaction="ignore")
            w.writeheader()
            for f in rows:
                rid = next((f[i] for i in ID_FIELD.values() if f.get(i)), "")
                w.writerow({"record_id": rid, **f})

    after = metrics(kept)
    fnd = [r["fields"] for r in kept if r["entity_type"] == "findings"]
    report = {
        "run_id": run_id, "input_dir": str(in_dir), "output_dir": str(out_dir),
        "corpus_papers": len(paper_rows),
        "papers_without_extracted_records": no_records,
        "papers_with_any_record": len({r["paper_id"] for r in kept}),
        "input_records": len(records), "output_records": len(kept),
        "folded_records": len(folded), "added_records": len(added),
        "steps": dict(sorted(steps.items())),
        "before": before, "after": after,
        "findings": {
            "finding_source": dict(Counter(f["finding_source"] for f in fnd).most_common()),
            "cites_other_work": dict(Counter(f["cites_other_work"] for f in fnd)),
            "is_primary_finding": dict(Counter(f["is_primary_finding"] for f in fnd)),
            "direction": dict(Counter(f["direction"] for f in fnd).most_common()),
            "direction_flag": dict(Counter(f["direction_flag"] or "(none)" for f in fnd).most_common()),
        },
        "evidence_match": dict(Counter(r["fields"]["evidence_match"] for r in kept).most_common()),
        "elapsed_s": round(time.time() - t0, 1),
    }
    (out_dir / "_clean_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    write_markdown(report, out_dir / "CLEAN_REPORT.md")
    print(json.dumps({k: report[k] for k in ("input_records", "output_records",
                                             "folded_records", "added_records", "steps")}, indent=2))
    print(f"wrote {out_dir} in {report['elapsed_s']}s")
    return 0


def write_markdown(rep, path):
    b, a = rep["before"], rep["after"]
    L = [f"# Catalogue cleanup — Phase A ({rep['run_id']})", "",
         f"Input `{rep['input_dir']}` → output `{rep['output_dir']}`. Deterministic; "
         "no model calls. The input directory is unchanged.", "",
         f"**Corpus: {rep['corpus_papers']} papers** (`catalogue_papers.csv`). "
         f"{rep['papers_with_any_record']} have at least one record; papers with no "
         f"extracted record: {', '.join(rep['papers_without_extracted_records']) or 'none'} "
         "(covered only by its corpus BioProject dataset).", "",
         f"**{rep['input_records']:,} → {rep['output_records']:,} records** "
         f"({rep['folded_records']:,} folded into a survivor, {rep['added_records']:,} "
         "BioProject datasets added). Every folded record is in `_removed.jsonl`; "
         "`_v2_to_v3_map.csv` gives the status of every input id.", "",
         "## Steps", "", "| step | count |", "|---|---:|"]
    L += [f"| {k} | {v:,} |" for k, v in rep["steps"].items()]
    L += ["", "## Records per entity", "", "| entity | before | after | evidence located before | after |",
          "|---|---:|---:|---:|---:|"]
    for e in ENTITIES:
        L.append(f"| {e} | {b['per_entity'][e]:,} | {a['per_entity'][e]:,} | "
                 f"{b['evidence_located_pct'][e]}% | {a['evidence_located_pct'][e]}% |")
    L += ["", "## Other measures", "", "| measure | before | after |", "|---|---:|---:|",
          f"| placeholder cells | {b['placeholder_cells']:,} | {a['placeholder_cells']:,} |",
          f"| dataset accessions filled | {b['dataset_accessions_filled']:,} | {a['dataset_accessions_filled']:,} |",
          f"| … of which a recognisable ID | {b['dataset_accessions_valid_pct']}% | {a['dataset_accessions_valid_pct']}% |",
          "", "## Findings", ""]
    for k, v in rep["findings"].items():
        L.append(f"- **{k}**: " + ", ".join(f"{x} {n:,}" for x, n in v.items()))
    L += ["", "- `is_primary_finding`: YES = Results/Abstract and no citation; NO = background, "
          "methods, references/backmatter, or cites other work; REVIEW = Discussion, "
          "Conclusion or unknown heading — resolved in Phase B.",
          "- `direction_flag` is a rule cue for review; `direction` itself is never "
          "changed except to normalise spelling (original in `direction_original`).",
          "", "## Evidence matching", "",
          ", ".join(f"{k} {v:,}" for k, v in rep["evidence_match"].items()), "",
          "## Review queues", "",
          "`review_direction_flags.csv`, `review_findings_not_primary.csv`, "
          "`review_count_flags.csv`, `review_invalid_accessions.csv`.", "",
          "## Not done here", "",
          "Cross-entity links (`dataset_id`/`cohort_id`/`assay_id`) are still empty — Phase B. "
          "Controlled vocabularies beyond `direction` — Phase C. All rows remain "
          "machine-extracted and unverified.", ""]
    path.write_text("\n".join(L), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
