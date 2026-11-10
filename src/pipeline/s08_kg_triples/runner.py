"""Batch runner for LLM triple extraction on all 444 papers.

Sequential execution (GPU memory constraint).
Checkpoint/resume support — same pattern as cdm_pipeline.qwen_batch.

Outputs:
- Per-paper JSON: cdm_output/triples/<paper_id>.triples.json
- Aggregated CSV: cdm_output/triples/all_triples.csv
- Checkpoint: cdm_output/triples/checkpoint.json

CLI:
  python -m cdm_pipeline.triples.runner [--model MODEL] [--db-path PATH]
                                        [--limit N] [--incremental]
                                        [--no-metadata] [--output-dir DIR]
"""

import argparse
import csv
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from pipeline.config import PAPERS_DIR, NER_OUTPUT_DIR, CDM_OUTPUT_DIR
from pipeline.s08_kg_triples.extractor import extract_triples_from_paper, DEFAULT_MODEL, DEFAULT_BASE_URL, DEFAULT_DB_PATH, PROMPT_VERSION
from pipeline.s08_kg_triples.biomni_validator import BiomniValidator

DEFAULT_OUTPUT_DIR = NER_OUTPUT_DIR.parent / "cdm_output" / "triples"

STUDY_META_FIELDS = [
    "study_continent", "study_country", "study_sample_size",
    "study_age_group", "study_sex", "study_study_type", "study_ethnicity",
]
CSV_FIELDS = [
    "paper_id", "subject", "predicate", "object",
    "subject_type", "object_type", "evidence", "confidence",
    "clarity", "relevance", "rationale",
    "sentence_id", "evidence_start_offset", "evidence_end_offset",
    "predicate_raw", "predicate_original",
    "extraction_run_id", "prompt_version", "model_version",
    "section_id", "section_label", "chunk_index",
    "warnings",
] + STUDY_META_FIELDS + ["model", "timestamp"]


def _checkpoint_path(output_dir: Path) -> Path:
    return output_dir / "checkpoint.json"


def _csv_path(output_dir: Path) -> Path:
    return output_dir / "all_triples.csv"


def load_checkpoint(output_dir: Path) -> dict:
    cp_path = _checkpoint_path(output_dir)
    if cp_path.exists():
        with open(cp_path, encoding="utf-8") as f:
            return json.load(f)
    return {"done": {}, "errors": {}, "started": None}


def save_checkpoint(cp: dict, output_dir: Path) -> None:
    with open(_checkpoint_path(output_dir), "w", encoding="utf-8") as f:
        json.dump(cp, f, indent=2, ensure_ascii=False)


def rebuild_csv(done_pids, output_dir: Path) -> int:
    all_rows = []
    for pid in sorted(done_pids):
        json_path = output_dir / f"{pid}.triples.json"
        if json_path.exists():
            with open(json_path, encoding="utf-8") as f:
                d = json.load(f)
            for t in d.get("triples", []):
                row = {"paper_id": t.get("paper_id", pid)}
                for k in CSV_FIELDS:
                    if k == "paper_id":
                        continue
                    v = t.get(k, "")
                    if isinstance(v, (list, dict)):
                        v = json.dumps(v, ensure_ascii=False)
                    row[k] = v
                all_rows.append(row)
    csv_p = _csv_path(output_dir)
    with open(csv_p, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(all_rows)
    print(f"CSV rebuilt: {len(all_rows)} rows -> {csv_p}")
    return len(all_rows)


def main():
    ap = argparse.ArgumentParser(description="Batch LLM triple extraction (EFRE-parity)")
    ap.add_argument("--model", default=DEFAULT_MODEL,
                    help=f"Ollama model (default: {DEFAULT_MODEL})")
    ap.add_argument("--db-path", default=str(DEFAULT_DB_PATH),
                    help=f"Path to microbiome_cdm.db (default: {DEFAULT_DB_PATH})")
    ap.add_argument("--limit", type=int, default=0,
                    help="Process at most N papers (0 = all)")
    ap.add_argument("--incremental", action="store_true",
                    help="Skip papers that already have a .triples.json file")
    ap.add_argument("--no-metadata", action="store_true",
                    help="Skip study-metadata LLM call (faster)")
    ap.add_argument("--validate", action="store_true",
                    help="Run biomni_validator (Phase 2 LLM pass) on each paper's triples")
    ap.add_argument("--validator-model", default=None,
                    help="Ollama model for biomni validation (defaults to --model)")
    ap.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR),
                    help=f"Output directory (default: {DEFAULT_OUTPUT_DIR})")
    args = ap.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    db_path = Path(args.db_path)
    papers = sorted(PAPERS_DIR.glob("*.txt"))

    print("=" * 60)
    print("LLM Triple Extraction Runner (EFRE-parity)")
    print("=" * 60)
    print(f"Papers:       {len(papers)}")
    print(f"Model:        {args.model}")
    print(f"Base URL:     {DEFAULT_BASE_URL}")
    print(f"DB path:      {db_path}")
    print(f"Prompt ver:   {PROMPT_VERSION}")
    print(f"Output dir:   {output_dir}")
    print(f"Checkpoint:   {_checkpoint_path(output_dir)}")
    print(f"Metadata:     {'off' if args.no_metadata else 'on'}")
    print(f"Validate:     {'on (biomni Phase 2)' if args.validate else 'off'}")
    if args.validate:
        print(f"Validator:    {args.validator_model or args.model}")
    print()

    cp = load_checkpoint(output_dir)
    if not cp["started"]:
        cp["started"] = datetime.now(timezone.utc).isoformat()
    done = set(cp["done"].keys())
    errors = cp.get("errors", {})

    todo = [p for p in papers if p.stem not in done]
    if args.incremental:
        todo = [p for p in todo if not (output_dir / f"{p.stem}.triples.json").exists()]
    if args.limit and args.limit > 0:
        todo = todo[: args.limit]
    print(f"Already done: {len(done)}, Remaining: {len(todo)}")
    print()

    t0 = time.time()
    processed = 0
    total_valid = 0
    total_raw = 0
    total_kept = 0
    total_corrected = 0
    total_rejected = 0

    validator = None
    if args.validate:
        validator = BiomniValidator(model=args.validator_model or args.model)
        print(f"BiomniValidator initialized: {validator.model}")
        print()

    for paper in todo:
        pid = paper.stem
        out_path = output_dir / f"{pid}.triples.json"

        if out_path.exists() and pid in done:
            continue

        paper_t0 = time.time()
        size_kb = paper.stat().st_size // 1024
        print(
            f"[{len(done) + processed + 1}/{len(papers)}] {pid} ({size_kb}KB)...",
            end=" ",
            flush=True,
        )

        try:
            paper_text = paper.read_text(encoding="utf-8", errors="replace")

            result = extract_triples_from_paper(
                paper_text=paper_text,
                paper_id=pid,
                model=args.model,
                base_url=DEFAULT_BASE_URL,
                db_path=db_path,
                extract_metadata=not args.no_metadata,
            )

            # Phase 2: biomni LLM validation of extracted triples (inline).
            # The validator returns kept/corrected/rejected lists; we keep
            # only kept+corrected as the published triples for this paper,
            # but the original extractor output is preserved in the JSON
            # under "extraction" so the run is fully traceable.
            validation = None
            if validator is not None and result["triples"]:
                v_t0 = time.time()
                try:
                    validation = validator.validate_paper_triples(
                        paper_id=pid,
                        triples=result["triples"],
                    )
                    # Replace the published triples with the validated set.
                    # The validated triples have the same schema (subject,
                    # predicate, object, subject_type, object_type, evidence,
                    # confidence) so they slot in directly.  We carry over
                    # provenance + study metadata from the extraction record.
                    validated_keep = []
                    extraction_by_spo = {}
                    for t in result["triples"]:
                        key = (t.get("subject", ""), t.get("predicate", ""),
                               t.get("object", ""))
                        extraction_by_spo[key] = t
                    for vt in validation.get("validated_triples", []):
                        key = (vt.get("subject", ""), vt.get("predicate", ""),
                               vt.get("object", ""))
                        base = extraction_by_spo.get(key, {})
                        merged = dict(base)
                        # Validator may have corrected types/predicate/confidence
                        for k in ("subject", "predicate", "object",
                                  "subject_type", "object_type",
                                  "confidence"):
                            if vt.get(k) is not None:
                                merged[k] = vt[k]
                        merged["validation_action"] = vt.get("action", "keep")
                        merged["validation_note"] = vt.get("correction_note", "")
                        validated_keep.append(merged)
                    result["triples_extracted"] = result["triples"]
                    result["triples"] = validated_keep
                    result["n_triples_validated"] = len(validated_keep)
                    result["n_triples_rejected"] = validation.get("n_rejected", 0)
                    result["validation"] = validation
                    v_elapsed = time.time() - v_t0
                    print(f"validated({v_elapsed:.0f}s:{len(validated_keep)}/{validation.get('n_rejected', 0)}) ",
                          end="", flush=True)
                except Exception as vex:
                    print(f"VALIDATOR_ERROR: {vex} ", end="", flush=True)
                    # Keep extraction-only output if validator fails
                    result["validation_error"] = str(vex)[:300]

            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(result, f, indent=2, ensure_ascii=False)

            elapsed = time.time() - paper_t0
            n_valid = len(result["triples"])
            n_raw = result["n_triples_raw"]
            total_valid += n_valid
            total_raw += n_raw
            if validation is not None:
                total_kept += validation.get("n_kept", 0)
                total_corrected += validation.get("n_corrected", 0)
                total_rejected += validation.get("n_rejected", 0)

            cp["done"][pid] = {
                "time": round(elapsed, 1),
                "n_raw": n_raw,
                "n_valid": n_valid,
                "n_chunks": result.get("n_chunks", 0),
                "n_flagged": result.get("n_triples_flagged", 0),
                "n_kept": validation.get("n_kept") if validation else None,
                "n_corrected": validation.get("n_corrected") if validation else None,
                "n_rejected": validation.get("n_rejected") if validation else None,
                "output": str(out_path),
                "run_id": result.get("extraction_run_id"),
                "completed": datetime.now(timezone.utc).isoformat(),
            }

            print(f"OK ({elapsed:.0f}s) — {n_raw} raw → {n_valid} valid")
            if validation is not None:
                print(f"  Validation: {validation.get('n_kept',0)} kept, "
                      f"{validation.get('n_corrected',0)} corrected, "
                      f"{validation.get('n_rejected',0)} rejected")

        except Exception as ex:
            elapsed = time.time() - paper_t0
            errors[pid] = {
                "error": str(ex)[:500],
                "time": round(elapsed, 1),
            }
            cp["errors"] = errors
            print(f"ERROR ({elapsed:.0f}s): {ex}")

        processed += 1
        if processed % 5 == 0:
            save_checkpoint(cp, output_dir)
            n_rows = rebuild_csv(set(cp["done"].keys()), output_dir)
            elapsed_total = time.time() - t0
            rate = processed / elapsed_total if elapsed_total > 0 else 0
            remaining = len(todo) - processed
            eta_s = remaining / rate if rate > 0 else 0
            print(
                f"  --- Checkpoint: {processed}/{len(todo)} done. "
                f"Total: {total_raw} raw → {total_valid} valid → {n_rows} CSV. "
                + (f"Validation: {total_kept} kept, {total_corrected} corrected, {total_rejected} rejected. " if validator else "")
                + f"Rate: {rate * 60:.1f}/min. ETA: {eta_s / 3600:.1f}h ---",
                flush=True,
            )

    save_checkpoint(cp, output_dir)
    n_rows = rebuild_csv(set(cp["done"].keys()), output_dir)

    total_time = time.time() - t0
    success = len(cp["done"])
    failed = len(cp["errors"])

    print(f"\n{'=' * 60}")
    print("BATCH COMPLETE")
    print(f"{'=' * 60}")
    print(f"Total papers:  {len(papers)}")
    print(f"Successful:    {success}")
    print(f"Failed:        {failed}")
    print(f"New this run:  {processed}")
    print(f"Total triples: {total_raw} raw → {total_valid} valid → {n_rows} in CSV")
    if validator:
        print(f"Validation:    {total_kept} kept, {total_corrected} corrected, {total_rejected} rejected")
    print(f"Elapsed:       {total_time / 60:.1f} min")
    if cp["errors"]:
        print(f"\nFailed papers:")
        for pid, info in list(cp["errors"].items())[:20]:
            print(f"  {pid}: {info.get('error', '')[:100]}")

    summary = {
        "model": args.model,
        "prompt_version": PROMPT_VERSION,
        "validator_model": (args.validator_model or args.model) if args.validate else None,
        "total_papers": len(papers),
        "successful": success,
        "failed": failed,
        "total_triples_raw": sum(v.get("n_raw", 0) for v in cp["done"].values()),
        "total_triples_valid": sum(v.get("n_valid", 0) for v in cp["done"].values()),
        "total_kept": total_kept if validator else None,
        "total_corrected": total_corrected if validator else None,
        "total_rejected": total_rejected if validator else None,
        "elapsed_min": round(total_time / 60, 1),
        "completed": datetime.now(timezone.utc).isoformat(),
        "errors": cp.get("errors", {}),
    }
    summary_path = output_dir / "batch_summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f"\nSummary saved to {summary_path}")


if __name__ == "__main__":
    main()
