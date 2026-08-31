"""Batch runner for llm_terms/main.py on all papers using Qwen3.5:9b.

- Sequential execution (GPU memory constraint)
- Checkpoint/resume support
- Error handling per-paper
- Thinking mode disabled by default in core/llm_client.py
"""
import sys
import json
import time
import subprocess
from pathlib import Path
from datetime import datetime, timezone

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from .config import REPO_ROOT, PAPERS_DIR, LLM_TERMS_DIR, SPACY_VENV_PYTHON

OUTPUT_DIR = LLM_TERMS_DIR / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

CHECKPOINT = OUTPUT_DIR / "qwen_batch_checkpoint.json"
MAIN_PY = str(LLM_TERMS_DIR / "main.py")
MODEL = "qwen3.5:9b"


def load_checkpoint():
    if CHECKPOINT.exists():
        with open(CHECKPOINT, encoding="utf-8") as f:
            return json.load(f)
    return {"done": {}, "errors": {}, "started": None}


def save_checkpoint(cp):
    with open(CHECKPOINT, "w", encoding="utf-8") as f:
        json.dump(cp, f, indent=2, ensure_ascii=False)


def main():
    papers = sorted(PAPERS_DIR.glob("*.txt"))
    print("=" * 60)
    print("Qwen3.5:9b Batch NER Runner")
    print("=" * 60)
    print(f"Papers: {len(papers)}")
    print(f"Model: {MODEL}")
    print(f"Output: {OUTPUT_DIR}")
    print(f"Checkpoint: {CHECKPOINT}")
    print()

    cp = load_checkpoint()
    if not cp["started"]:
        cp["started"] = datetime.now(timezone.utc).isoformat()
    done = set(cp["done"].keys())
    errors = cp.get("errors", {})

    todo = [p for p in papers if p.stem not in done]
    print(f"Already done: {len(done)}, Remaining: {len(todo)}")
    print()

    t0 = time.time()
    processed = 0
    for paper in todo:
        pid = paper.stem
        out_path = OUTPUT_DIR / f"{pid}.cdm_entities.json"

        if out_path.exists() and pid in done:
            continue

        paper_t0 = time.time()
        print(f"[{len(done)+processed+1}/{len(papers)}] {pid} ({paper.stat().st_size//1024}KB)...", end=" ", flush=True)

        try:
            result = subprocess.run(
                [str(SPACY_VENV_PYTHON), MAIN_PY, "--input", str(paper),
                 "--model", MODEL, "--output", str(out_path)],
                capture_output=True, text=True, timeout=900,
                encoding="utf-8", errors="replace",
                cwd=str(REPO_ROOT)
            )

            if result.returncode == 0 and out_path.exists():
                elapsed = time.time() - paper_t0
                cp["done"][pid] = {
                    "time": round(elapsed, 1),
                    "output": str(out_path),
                    "completed": datetime.now(timezone.utc).isoformat(),
                }
                print(f"OK ({elapsed:.0f}s)")
            else:
                elapsed = time.time() - paper_t0
                err_msg = result.stderr[-500:] if result.stderr else result.stdout[-500:]
                errors[pid] = {
                    "returncode": result.returncode,
                    "error": err_msg,
                    "time": round(elapsed, 1),
                }
                cp["errors"] = errors
                print(f"FAILED ({elapsed:.0f}s) rc={result.returncode}")

        except subprocess.TimeoutExpired:
            errors[pid] = {"returncode": -1, "error": "Timeout (900s)", "time": 900}
            cp["errors"] = errors
            print("TIMEOUT")
        except Exception as ex:
            errors[pid] = {"returncode": -2, "error": str(ex)[:200]}
            cp["errors"] = errors
            print(f"ERROR: {ex}")

        processed += 1
        if processed % 10 == 0:
            save_checkpoint(cp)
            rate = processed / (time.time() - t0)
            remaining = len(todo) - processed
            eta = remaining / rate if rate > 0 else 0
            print(f"  --- Checkpoint saved. {processed}/{len(todo)} done. "
                  f"Rate: {rate:.2f}/min. ETA: {eta/60:.1f}h ---")

    save_checkpoint(cp)

    total_time = time.time() - t0
    success = len(cp["done"])
    failed = len(cp["errors"])

    print(f"\n{'=' * 60}")
    print(f"BATCH COMPLETE")
    print(f"{'=' * 60}")
    print(f"Total papers: {len(papers)}")
    print(f"Successful: {success}")
    print(f"Failed: {failed}")
    print(f"New this run: {processed}")
    print(f"Elapsed: {total_time/60:.1f} min")
    if cp["errors"]:
        print(f"\nFailed papers:")
        for pid, info in list(cp["errors"].items())[:20]:
            print(f"  {pid}: {info.get('error', '')[:100]}")

    summary = {
        "model": MODEL,
        "total_papers": len(papers),
        "successful": success,
        "failed": failed,
        "errors": cp["errors"],
        "elapsed_min": round(total_time / 60, 1),
        "completed": datetime.now(timezone.utc).isoformat(),
    }
    summary_path = OUTPUT_DIR / "qwen_batch_summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f"\nSummary saved to {summary_path}")


if __name__ == "__main__":
    main()
