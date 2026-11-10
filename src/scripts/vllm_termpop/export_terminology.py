"""Export terminology-extraction records (one row per term per section) from a
section-level NER CSV (vLLM or Ollama Qwen run, or the CPU ensemble).

Implements the standardized terminology-extraction template:
  * term_id, term, normalized_term, term_type, paper_id, section fields,
    source_sentence (exact sentence containing the located span),
    source_location (section + char span), frequency in section (normalized
    whole-word count — scope = this section of this paper), provenance
    (extraction model, run id, prompt version, date, text hash), and
    verification_status=REVIEW_REQUIRED by default.

Outputs into <ner_dir>/terminology/:
  terminology_extracted_terms.csv   (Table 1 — one row per term per section)
  terminology_normalized_terms.csv  (Table 2 — canonical form + alt labels per paper)
  terminology_verification.csv      (Table 3 — audit/frequency rollup per term)
  terminology_records.json          (machine-readable, full records)
  terminology_summary.json

Usage:
    PYTHONPATH=src python src/scripts/vllm_termpop/export_terminology.py \
        --ner_csv outputs/results/<dir>/vllm_sections_ner.csv \
        --model "Qwen/Qwen3.5-4B via vLLM" \
        --run_id RUN_vllm_qwen35_4b_001
"""
import argparse
import csv
import hashlib
import json
import re
import time
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())

# Mandatory fields first (per the template); optional fields after.
CSV_FIELDS = [
    "term_id", "term", "normalized_term", "term_type",
    "paper_id", "section_id", "section_name", "section_subsection",
    "source_sentence", "source_location",
    "frequency_in_section", "distinct_papers_with_term",
    "extraction_model", "extraction_run_id", "prompt_version",
    "extraction_date", "source_text_hash",
    "confidence", "verification_status", "reviewer_notes",
]

SENT_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9“\"'(])")


def norm_term(t):
    """Canonical form: unicode NFKD -> ascii-ish, lowercase, collapse spaces/dashes."""
    t = unicodedata.normalize("NFKD", t)
    t = t.encode("ascii", "ignore").decode("ascii")
    t = t.lower().replace("–", "-").replace("—", "-")
    t = re.sub(r"[-_/]", "-", t)
    t = re.sub(r"\s+", " ", t).strip().strip("-")
    return t


def sentence_at(text, start, end):
    """Smallest sentence-like unit covering [start:end]."""
    left = max(0, start - 400)
    right = min(len(text), end + 400)
    window = text[left:right]
    # cut at sentence boundaries within the window
    before_matches = list(SENT_END.finditer(window[:start - left])) if start - left else []
    if before_matches:
        lo = before_matches[-1].end()
    else:
        lo = 0
    after = SENT_END.search(window[end - left:])
    hi = (end - left + after.end()) if after else len(window)
    sent = window[lo:hi].strip()
    return re.sub(r"\s+", " ", sent)


def load_md_sections(seg_dir, cids):
    """{cid: {section_id: full section body text}} from the markdown files."""
    out = {}
    for f in sorted(Path(seg_dir).glob("HMPAPER_*.md")):
        cid = f.stem
        if cids and cid not in cids:
            continue
        text = f.read_text(encoding="utf-8")
        secs = {}
        # split on SEGMENT blocks; keep (SECTION_ID, body) pairs
        parts = re.split(r"<!-- SEGMENT: \S+ -->", text)[1:]
        for part in parts:
            m_id = re.search(r"<!-- SECTION_ID: (\S+) -->", part)
            m_end = re.search(r"<!-- END_SEGMENT: \S+ -->", part)
            if not (m_id and m_end):
                continue
            start = m_id.end()
            m_path = re.search(r"<!-- SECTION_PATH: (.+?) -->", part)
            # SECTION_PATH and ORDINAL lines precede the body
            hdr_end = part.find("-->", m_id.end())
            body = part[hdr_end + 3:m_end.start()] if hdr_end != -1 else ""
            body = re.sub(r"\s+\n", "\n", body).strip()
            sid = m_id.group(1)
            if sid in secs:
                secs[sid]["text"] += "\n" + body
            else:
                secs[sid] = {"text": body, "path": m_path.group(1).strip() if m_path else ""}
        out[cid] = secs
    return out


def main():
    ap = argparse.ArgumentParser(description="Terminology export (Tables 1-3)")
    ap.add_argument("--ner_csv", required=True,
                    help="section-level NER CSV (term,labels,model,paper,section_id,section_path,char_start,char_end)")
    ap.add_argument("--seg_dir", default=str(REPO_ROOT / "data/segmented_sections_markdown"))
    ap.add_argument("--model", required=True, help="human-readable model label, e.g. 'Qwen/Qwen3.5-4B via vLLM'")
    ap.add_argument("--run_id", required=True, help="e.g. RUN_vllm_qwen35_4b_001")
    ap.add_argument("--prompt_version", default="cdm-ner-v1-vllm")
    ap.add_argument("--verification_status", default="REVIEW_REQUIRED")
    ap.add_argument("--limit", type=int, default=None, help="debug: first N rows only")
    args = ap.parse_args()

    ner_csv = Path(args.ner_csv)
    out_dir = ner_csv.parent / "terminology"
    out_dir.mkdir(parents=True, exist_ok=True)
    t_start = time.time()

    rows = []
    with open(ner_csv, newline="", encoding="utf-8") as f:
        for i, r in enumerate(csv.DictReader(f)):
            if args.limit and i >= args.limit:
                break
            rows.append(r)
    print(f"Loaded {len(rows)} NER rows")
    cids = {r["paper"] for r in rows}
    md = load_md_sections(args.seg_dir, cids)
    print(f"Loaded section text for {len(md)} papers")

    # group located spans by (paper, section, normalized term) for frequency-in-section
    grouped = defaultdict(list)
    for r in rows:
        key = (r["paper"], r["section_id"], norm_term(r["term"]))
        grouped[key].append(r)

    # corpus-level distinct-paper count per normalized term
    papers_by_term = defaultdict(set)
    for (cid, _sid, nterm) in grouped:
        papers_by_term[nterm].add(cid)

    # sentence dedup per (paper, section, term): one record per distinct sentence occurrence
    records = []
    term_counter = Counter()
    missing_text = 0
    for (cid, sid, nterm), grp in sorted(grouped.items()):
        sec = md.get(cid, {}).get(sid)
        if sec is None:
            missing_text += 1
            continue
        text = sec["text"]
        # frequency in scope: whole-word occurrences within this section
        freq = len(re.findall(r"(?<!\w)" + re.escape(nterm) + r"(?!\w)", text,
                              flags=re.IGNORECASE)) if nterm else 0
        # use canonical (first-seen) surface form as the term
        first = grp[0]
        # representative spans -> distinct source sentences
        sents = {}
        for r in grp:
            try:
                cs, ce = int(r["char_start"]), int(r["char_end"])
            except (KeyError, ValueError):
                continue
            sent = sentence_at(text, cs, ce)
            sents.setdefault(sent, (cs, ce))
        for sent, (cs, ce) in sorted(sents.items(), key=lambda kv: kv[1][0]):
            term_counter[nterm] += 1
            records.append({
                "term_id": "TERM_%06d" % term_counter[nterm],
                "term": first["term"],
                "normalized_term": nterm,
                "term_type": first.get("labels", ""),
                "definition": "NOT_STATED",
                "definition_source": "NOT_STATED",
                "paper_id": cid,
                "section_id": sid,
                "section_name": sec["path"].split(">")[-1].strip(),
                "section_subsection": " > ".join(
                    p.strip() for p in sec["path"].split(">")[:-1]) or "N/A",
                "source_sentence": sent,
                "source_location": f"{sid} chars {cs}-{ce}",
                "frequency_in_section": freq,
                "distinct_papers_with_term": len(papers_by_term[nterm]),
                "frequency_counting_method": "normalized_whole_word_in_section",
                "extraction_model": args.model,
                "extraction_run_id": args.run_id,
                "prompt_version": args.prompt_version,
                "extraction_date": time.strftime("%Y-%m-%d"),
                "source_text_hash": hashlib.sha256(text.encode("utf-8")).hexdigest()[:16],
                "confidence": "",  # Qwen chat run reports no per-entity confidence
                "verification_status": args.verification_status,
                "reviewer_notes": "",
                "_all_types": sorted({r.get("labels", "") for r in grp}),
            })
    if missing_text:
        print(f"WARNING: {missing_text} (paper, section) groups had no markdown text")

    # Table 1 — extracted terms (one row per term per section per distinct sentence)
    with open(out_dir / "terminology_extracted_terms.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(records)

    # Table 2 — normalization and synonyms (per paper: canonical + alt surface forms)
    by_norm = defaultdict(lambda: {"alt": Counter(), "papers": set(), "types": set()})
    for rec in records:
        e = by_norm[rec["normalized_term"]]
        e["alt"][rec["term"]] += 1
        e["papers"].add(rec["paper_id"])
        e["types"].update(rec.get("_all_types") or [rec["term_type"]])
    with open(out_dir / "terminology_normalized_terms.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["normalized_term", "canonical_form", "alternative_labels",
                    "distinct_papers", "types"])
        for nterm in sorted(by_norm):
            e = by_norm[nterm]
            w.writerow([nterm, e["alt"].most_common(1)[0][0],
                         "; ".join(t for t, _ in e["alt"].most_common()),
                         len(e["papers"]),
                         "; ".join(sorted(t for t in e["types"] if t))])

    # Table 3 — verification & audit rollup (per normalized term across corpus)
    with open(out_dir / "terminology_verification.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["normalized_term", "records", "papers", "verification_status",
                    "extraction_run_id", "automated_validation_status"])
        for nterm in sorted(by_norm):
            n_rec = sum(1 for r in records if r["normalized_term"] == nterm)
            w.writerow([nterm, n_rec, len(papers_by_term[nterm]),
                        args.verification_status, args.run_id, "NOT_RUN"])

    # machine-readable full records
    with open(out_dir / "terminology_records.json", "w", encoding="utf-8") as f:
        json.dump({"extraction_model": args.model, "extraction_run_id": args.run_id,
                   "prompt_version": args.prompt_version,
                   "extraction_date": time.strftime("%Y-%m-%d"),
                   "fields": CSV_FIELDS, "records": records},
                  f, ensure_ascii=False, indent=1)

    types = Counter(r["term_type"] for r in records)
    summary = {
        "ner_csv": str(ner_csv), "rows_in": len(rows), "records": len(records),
        "distinct_normalized_terms": len(papers_by_term),
        "papers": len(cids),
        "sections_with_terms": len({(r['paper_id'], r['section_id']) for r in records}),
        "term_types": dict(types.most_common()),
        "verification_default": args.verification_status,
        "el_seconds": round(time.time() - t_start, 1),
    }
    with open(out_dir / "terminology_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print("Records: %d | distinct terms: %d | papers: %d" % (
        len(records), len(papers_by_term), len(cids)))
    for path in sorted(out_dir.iterdir()):
        print("  ->", path)


if __name__ == "__main__":
    main()
