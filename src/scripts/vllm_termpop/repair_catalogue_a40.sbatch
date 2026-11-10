#!/bin/bash
#SBATCH --job-name=cat-repair
#SBATCH --output=outputs/logs/catalogue_repair_%j.out
#SBATCH --error=outputs/logs/catalogue_repair_%j.err
#SBATCH --partition=mlgpu_short
#SBATCH --gres=gpu:a40:1
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --time=04:00:00

# ──────────────────────────────────────────────────────────────────────────────
# TARGETED repair of FAILED catalogue-NER requests.
#
# OUTCOME: this tool closed the gap. 127 truncated requests -> 0 over five passes
# (jobs 28663289, 28663900, 28664271, 28664464, 28664727). Final measured state:
# char coverage 100.000%, failed segments 0, incomplete sections 0, catalogue
# records 56,985 -> 60,424. Frozen bundles untouched (frozen_output 660/660,
# data_catalogue 1003/1003 sha256 OK). Full narrative: outputs/results/COVERAGE_453.md §4.
#
# Pass 1 (job 28663289) cut the original 127 truncated requests to 32.
#
#   * all residuals truncate on dense `findings` enumerations, NOT on repetition
#     loops (distinct-window ratios 0.93-1.00 at every failing node);
#   * truncation is content-driven, not size-driven: at comparable sizes the
#     truncated pieces are the numeric-dense ones (median numeric-token fraction
#     24.5% vs 14.5% for pieces that fit, restricted to <1200 chars), and some
#     targets fit at 207 chars while a sibling of 996 chars overflowed.
#
# NOTE: an earlier probe (job 28663870) claimed 30 of 32 would "resolve by
# halving"; that estimate is RETRACTED. It built each smaller piece as
# `text[: len(text) // d]`, a prefix truncation, so it never tested the later
# halves where the dense content sits. Job 28664134
# (outputs/scratch/probe_deep_split.py) replaces it with genuine bisection.
#
# Pass 1 ran SPLIT_MIN_CHARS=600, whose halving gate is
#   `len(text) < 2 * min_chars`  ->  refuses to split a 1,046-char piece
# because 1046 < 1200. Reaching the ~494-char leaves the probe proved sufficient
# requires min_chars <= 494, so pass 1 *structurally could not* repair them.
# That, not the call budget, is what bounded it: every residual error was the
# truncation ValueError, never "call budget exhausted" (910 calls / 127 targets
# is ~7 each, far below the 32-call budget).
#
# Pass 2 ran SPLIT_MIN_CHARS=400 and added LEAF_RETRIES (re-ask at the SAME size
# before paying for a split). It repaired 23 of the 32 and left 9.
#
# Pass 3 (job 28664271) set SPLIT_MIN_CHARS=200 (halving gate 400) and repaired
# 5 of 9, leaving 4.
#
# Pass 4 (job 28664464) re-ran those 4 with LEAF_RETRIES=3 / CALL_BUDGET=160 and
# repaired 0 of 4. That is the decisive measurement: **retrying is not the
# lever**. The blocker was DETERMINISTIC, and it was a bug in the cut rule.
#
# ROOT CAUSE (fixed in this revision): the halving cut was
#     cut = text.rfind(" ", 0, len(text) // 2)
# with no fallback. Several residuals are flattened statistical tables whose rows
# are newline- or tab-separated, so the first half can contain NO space at all
# and `rfind` returns -1, which raised on the very first call:
#     HMPAPER_000024 sec_001   3,983 chars, 0 spaces in first half  -> cut = -1
#     (text begins `137.9\n-\n4382476\n126.9\n...`)
# Every retry re-sent the SAME unsplittable node, so attempts could never help.
# `best_cut()` in catalogue_ner.py now falls back to the last run of ANY
# whitespace, then to the exact midpoint. It is shared with the repair tool and
# pinned by src/tests/test_best_cut.py.
#
# CORRECTION to an earlier version of this header: it claimed the deep-split
# probe (job 28664134) "proved every target resolvable — 61 truncated nodes, all
# resolvable". That over-read the probe. The probe counted a JSON body of an
# empty list (tokens=11, 20 chars) as `ok`, so 16 of its 70 "ok" nodes were empty
# responses rather than extractions; and its own cut rule had `if cut <= 0: cut =
# len(piece)//2`, i.e. the midpoint fallback this fix adopts. The probe therefore
# never exercised the space-only path that was actually failing. Its size bands
# remain valid as a description of truncation, but "all resolvable" was a claim
# about the probe's own more permissive splitter, not about the repair path.
#
# SIZE BANDS (probe, recomputed excluding the 16 empty-`ok` nodes; denominator is
# real-fit + truncated, so it is NOT the node count) — truncation gets likelier
# with length, so halving reduces but does not zero the risk at any single size:
#     band        fit  trunc  P(trunc)
#     <400        10     0     0.0%
#     400-700      9     4    30.8%
#     700-1000    11     6    35.3%
#     1000-2000   14    14    50.0%
#     2000-5000    9    26    74.3%
#     >5000        1    11    91.7%
#     total       54    61
# This is why LEAF_RETRIES=1 stays: a re-ask at the same size is worth one extra
# call, but it is NOT the primary mechanism and it was never sufficient alone
# (pass 4 measured 0/4 with LEAF_RETRIES=3).
#
# Pass 2 is exactly reproducible with:
#   SPLIT_DEPTH=8 SPLIT_MIN_CHARS=400 CALL_BUDGET=64 LEAF_RETRIES=1 sbatch ...
# Pass 3 (5/9) is:
#   SPLIT_DEPTH=8 SPLIT_MIN_CHARS=200 CALL_BUDGET=96 LEAF_RETRIES=1 sbatch ...
# Pass 4 (the 0/4 run, superseded by the cut fix) is:
#   SPLIT_DEPTH=8 SPLIT_MIN_CHARS=200 CALL_BUDGET=160 LEAF_RETRIES=3 sbatch ...
# Pass 5 (4/4, gap closed) re-ran pass 3's policy on the cut-fixed code:
#   SPLIT_DEPTH=8 SPLIT_MIN_CHARS=200 CALL_BUDGET=160 LEAF_RETRIES=1 sbatch ...
#
# QUALITY CAVEAT on the recovered rows (measured, not assumed). The repaired
# spans are flattened statistical tables, so some recovered `outcome` /
# `body_site` values are bare numbers mis-slotted from a neighbouring row.
# Bare-numeric test on those two free-text fields only (NOT on p_value /
# effect_estimate / confidence_interval, which are numeric by design).
# Bucketed by the split policy stored in each repaired entry (NOT by the
# per-pass target files — later passes re-ran keys listed in earlier files):
#     pass 1  depth=6 min=600          3,076 rows   43 bare   1.40%   (95 tgt)
#     pass 2  depth=8 min=400 bud=64     894 rows   19 bare   2.13%   (23 tgt)
#     pass 3  depth=8 min=200 bud=96     173 rows   11 bare   6.36%   ( 5 tgt)
#     pass 5  depth=8 min=200 bud=160    231 rows   39 bare  16.88%   ( 4 tgt)
#     all repaired                     4,374 rows  112 bare   2.56%  (127 tgt)
#     unrepaired cache (background)   24,333 rows   54 bare   0.22%
#     shipped releases/data_catalogue/         21,439 rows   36 bare   0.17%
# The rate rises by pass because each pass inherited only the spans the previous
# one could not fit. Hits are concentrated: 12 of 110 repaired sections carry
# them, 98 carry none. All repaired rows are machine-extracted and UNVERIFIED —
# verification_status is not promoted by repair. Details: COVERAGE_453.md §4.
#
# Why not just resubmit catalogue_ner_a40.sbatch: its resume path retries the
# errored keys with the SAME MAX_SPLIT_DEPTH=3 / SPLIT_MIN_CHARS=1500 that
# already failed, so it reproduces the identical failures.
#
# Why not just raise MAX_TOKENS: LLM_MAX_TOKENS is hashed into cache_key(), so
# a larger budget re-keys the entire 32,994-request plan and orphans all 32,508
# good entries (32,994 planned jobs collapse to 32,508 distinct keys because 11
# papers share byte-identical bodies in 5 groups; see COVERAGE_453.md §4). MAX_SPLIT_DEPTH / SPLIT_MIN_CHARS / CALL_BUDGET are NOT in the
# key — retuning those is cache-safe, which is what this script does.
#
# The cache is edited IN PLACE at outputs/results/catalogue_ner_v2/ (backed up first).
# The checksummed releases/data_catalogue/ bundle is NOT touched.
#
#   sbatch src/scripts/vllm_termpop/repair_catalogue_a40.sbatch
#   DRY_RUN=1 sbatch ...        # list targets, no API calls, no writes
#   SPLIT_DEPTH=8 sbatch ...    # override the halving policy
#   MAX_TARGETS=5 sbatch ...    # smoke-test the ladder on 5 requests
# ──────────────────────────────────────────────────────────────────────────────

# Repo root, found at run time: $CDM_REPO_ROOT, else walk up to .cdm_root
# from the submit dir (sbatch) or this script's dir (direct run).
CDM_ROOT="${CDM_REPO_ROOT:-$(d="${SLURM_SUBMIT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"; while [ "$d" != / ] && [ ! -f "$d/.cdm_root" ]; do d="$(dirname "$d")"; done; echo "$d")}"
[ -f "$CDM_ROOT/.cdm_root" ] || { echo "ERROR: repo root not found; set CDM_REPO_ROOT" >&2; exit 1; }
export CDM_ROOT

set -uo pipefail

export PROJECT_ROOT="$CDM_ROOT"
cd "$PROJECT_ROOT"
mkdir -p logs

MODEL="${MODEL:-Qwen/Qwen3.5-4B}"
PORT="${PORT:-8000}"
PARALLEL="${PARALLEL:-16}"
OUT_DIR="${OUT_DIR:-results/catalogue_ner_v2}"
SPLIT_DEPTH="${SPLIT_DEPTH:-8}"
SPLIT_MIN_CHARS="${SPLIT_MIN_CHARS:-200}"
CALL_BUDGET="${CALL_BUDGET:-96}"
LEAF_RETRIES="${LEAF_RETRIES:-1}"
REQUEST_TIMEOUT="${REQUEST_TIMEOUT:-600}"
DRY_RUN="${DRY_RUN:-}"
MAX_TARGETS="${MAX_TARGETS:-}"

echo "========================================================================"
echo "Catalogue NER repair — 127 truncated requests — Qwen3.5-4B on A40"
echo "  Job ID:      ${SLURM_JOB_ID:-<none>}"
echo "  Node:        ${SLURM_NODELIST:-<none>}"
echo "  Model:       $MODEL"
echo "  Output dir:  $OUT_DIR"
echo "  Split:       depth=$SPLIT_DEPTH min_chars=$SPLIT_MIN_CHARS budget=$CALL_BUDGET retries=$LEAF_RETRIES"
echo "  Dry run:     ${DRY_RUN:-no}"
echo "  Started:     $(date)"
echo "========================================================================"

module use /opt/software/easybuild-AMD/modules/all
module load Python/3.12.3-GCCcore-13.3.0
module load CUDA/12.9.1
source /home/jkalra_hpc/venvs/vllm/bin/activate

export CUDA_HOME="$(dirname "$(dirname "$(command -v nvcc)")")"
export HF_HOME=/home/jkalra_hpc/llm/hf-cache
export HF_HUB_OFFLINE=0
export PYTHONPATH="$PROJECT_ROOT/src:${PYTHONPATH:-}"
export PYTHONUNBUFFERED=1
export PYTHONIOENCODING=utf-8
export TOKENIZERS_PARALLELISM=false

nvidia-smi -L || true

# ── Dry run: no server needed ────────────────────────────────────────────────
if [ -n "$DRY_RUN" ]; then
    echo "[$(date +%T)] dry run — listing targets only"
    python src/scripts/vllm_termpop/repair_catalogue_cache.py \
        --model "$MODEL" --output_dir "$OUT_DIR" \
        --split_depth "$SPLIT_DEPTH" --split_min_chars "$SPLIT_MIN_CHARS" \
        ${MAX_TARGETS:+--max_targets "$MAX_TARGETS"} \
        --dry_run
    echo "[$(date +%T)] dry run exit: $?"
    exit 0
fi

# ── Back up the 54 MB checkpoint before any in-place edit ────────────────────
if [ -f "$OUT_DIR/_catalogue_cache.json" ]; then
    BACKUP="$OUT_DIR/_catalogue_cache.pre_repair_${SLURM_JOB_ID:-local}.json"
    if [ -f "$BACKUP" ]; then
        echo "[$(date +%T)] backup already exists: $BACKUP"
    else
        echo "[$(date +%T)] backing up cache -> $BACKUP"
        cp -p "$OUT_DIR/_catalogue_cache.json" "$BACKUP"
    fi
    ls -la "$BACKUP"
fi

# ── Serve the model ──────────────────────────────────────────────────────────
echo "[$(date +%T)] starting vLLM server ..."
vllm serve "$MODEL" \
    --port "$PORT" \
    --gpu-memory-utilization 0.90 \
    --max-model-len 32768 \
    > "$OUT_DIR/vllm_server_repair_${SLURM_JOB_ID:-local}.log" 2>&1 &
SERVER_PID=$!

ready=""
for _ in $(seq 1 180); do
    if curl -sf "http://127.0.0.1:${PORT}/v1/models" > /dev/null 2>&1; then
        ready=1; break
    fi
    if ! kill -0 "$SERVER_PID" 2>/dev/null; then
        echo "vLLM server died during startup — see the server log"
        tail -40 "$OUT_DIR/vllm_server_repair_${SLURM_JOB_ID:-local}.log"
        exit 1
    fi
    sleep 5
done

if [ -z "$ready" ]; then
    echo "vLLM server not ready in 15 min — see server log"
    tail -40 "$OUT_DIR/vllm_server_repair_${SLURM_JOB_ID:-local}.log"
    kill "$SERVER_PID" 2>/dev/null || true
    exit 1
fi
echo "[$(date +%T)] server ready"

cleanup() {
    echo "[$(date +%T)] stopping vLLM server (pid $SERVER_PID)"
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
}
trap cleanup EXIT

# ── Repair, then rebuild the CSV tables from the full cache ──────────────────
echo "[$(date +%T)] running repair_catalogue_cache.py ..."
python src/scripts/vllm_termpop/repair_catalogue_cache.py \
    --model "$MODEL" \
    --host "http://127.0.0.1:${PORT}" \
    --output_dir "$OUT_DIR" \
    --parallel "$PARALLEL" \
    --request_timeout "$REQUEST_TIMEOUT" \
    --split_depth "$SPLIT_DEPTH" \
    --split_min_chars "$SPLIT_MIN_CHARS" \
    --call_budget "$CALL_BUDGET" \
    --leaf_retries "$LEAF_RETRIES" \
    ${MAX_TARGETS:+--max_targets "$MAX_TARGETS"} \
    --assemble_only_after
RC=$?

echo "[$(date +%T)] repair exit code: $RC"
echo "========================================================================"
python - "$OUT_DIR" <<'PYEOF'
import json, sys
from pathlib import Path
d = Path(sys.argv[1])
for name in ("_catalogue_repair_report.json", "_catalogue_summary.json"):
    p = d / name
    if not p.exists():
        print("%s: MISSING" % name); continue
    s = json.loads(p.read_text())
    print("\n== %s ==" % name)
    if name.startswith("_catalogue_repair"):
        for k in ("targets", "repaired", "repaired_complete", "repaired_partial",
                  "still_failed", "modes", "max_tokens_unchanged",
                  "split_depth", "split_min_chars", "elapsed_sec"):
            print("  %-22s %s" % (k+":", s.get(k)))
    else:
        c = s["coverage"]
        print("  sections complete:  %d / %d" % (c["sections_complete"], c["sections_total"]))
        print("  sections empty:     %d" % c["sections_empty"])
        print("  sections incomplete:%d" % c["sections_incomplete"])
        print("  char coverage:      %s%%" % c["char_coverage_pct"])
        print("  coverage status:    %s" % c["coverage_status"])
        print("  failed segments:    %d" % s["segments_failed"])
PYEOF
echo "Outputs: $OUT_DIR"
exit $RC
