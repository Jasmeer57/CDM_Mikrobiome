#!/bin/bash
#SBATCH --job-name=hmcv2-pilot-recovery
#SBATCH --partition=mlgpu_short
#SBATCH --gres=gpu:a40:1
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --time=6:00:00
#SBATCH --output=outputs/logs/slurm/%x-%j.out
#SBATCH --error=outputs/logs/slurm/%x-%j.err

# Truncation-recovery pilot (4 arms, 88 sections / 81 papers / 915,048 chars).
# Design + cost model: outputs/scratch/evidence_calibration/review/TRUNCATION_RECOVERY_PILOT.md
# Runner:              outputs/scratch/evidence_calibration/src/run_pilot.py
#
# ONE variable changes: llm.max_tokens 4,500 -> 16,384, in an IN-MEMORY copy of
# the config. pipelines/corpus_v2/config/corpus.yaml is never written. The llmio.py split
# ladder (depth < 2, chunk >= 2,000 chars) is left UNCHANGED so a recovery can be
# attributed to one factor only.
#
# Deliberately NOT stage 53 and NOT stage 56:
#   * stage 53 rewrites pipelines/corpus_v2/data/{triples_sections,triple_mentions}.jsonl
#     in full -- a filtered run through it would replace the frozen artifacts
#     with a subset.
#   * stage 56 assigns HMCV2-CT-<n> by enumerate(sorted(group_keys), 1), so
#     re-running it would renumber the frozen HMCV2-CT-00001..32713 series and
#     break every verbatim id in the bundle, the judge inputs and the manuscript.
#
# Writes ONLY to outputs/scratch/evidence_calibration/pilot_run/ . Write isolation is
# asserted twice: by the runner (md5 of 6 guarded corpus files, before vs after)
# and here by the launcher (md5sum + diff, hard exit 90). Read-only baseline
# bundles are re-verified with sha256sum -c (hard exit 91).
#
# Outputs: sections.jsonl, summary.json, RECOVERY_PILOT_RESULTS.md, vllm-<jid>.log
# The results file carries NO status token on purpose -- the review's only token
# is emitted by review/AI_REVIEW_REPORT.md.
# Repo root, found at run time: $CDM_REPO_ROOT, else walk up to .cdm_root
# from the submit dir (sbatch) or this script's dir (direct run).
CDM_ROOT="${CDM_REPO_ROOT:-$(d="${SLURM_SUBMIT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"; while [ "$d" != / ] && [ ! -f "$d/.cdm_root" ]; do d="$(dirname "$d")"; done; echo "$d")}"
[ -f "$CDM_ROOT/.cdm_root" ] || { echo "ERROR: repo root not found; set CDM_REPO_ROOT" >&2; exit 1; }
export CDM_ROOT

set -euo pipefail

REPO="$CDM_ROOT"
CORPUS_DIR="$REPO/pipelines/corpus_v2"
OUTDIR="$REPO/outputs/scratch/evidence_calibration/pilot_run"
RUNNER="$REPO/outputs/scratch/evidence_calibration/src/run_pilot.py"
PORT=8011
MODEL="Qwen/Qwen3.5-4B"
MAX_TOKENS=16384
WORKERS=16
MAX_NUM_SEQS=16
# 0 = all 88 sections; set to e.g. 8 via PILOT_LIMIT for a smoke test.
PILOT_LIMIT="${PILOT_LIMIT:-0}"
PILOT_ARMS="${PILOT_ARMS:-A,B,C,D}"

source "$CORPUS_DIR/slurm/_env.sh" pilot_recovery
module load CUDA/12.9.1
export CUDA_HOME="$(dirname "$(dirname "$(command -v nvcc)")")"
export VLLM_USE_FLASHINFER_SAMPLER=0

mkdir -p "$OUTDIR" "$REPO/outputs/logs/slurm"

JID="${SLURM_JOB_ID:-local}"

echo "[$(date -u +%FT%TZ)] node=$(hostname) job=$JID"
nvidia-smi -L || true

# ---- pinned inputs: the arms must be the frozen draw ------------------------
SEL="$REPO/outputs/scratch/evidence_calibration/src/pilot_selection.json"
SEL_SHA="00142badec3a1eb4b1118049625fb941abd86927d2ea473ffe222982e1a483c3"
GOT_SEL=$(sha256sum "$SEL" | cut -d' ' -f1)
if [[ "$GOT_SEL" != "$SEL_SHA" ]]; then
    echo "FATAL: pilot_selection.json sha256 $GOT_SEL != pinned $SEL_SHA" >&2
    exit 92
fi
echo "PASS: pilot_selection.json pinned ($SEL_SHA)"

LEDGER="$REPO/releases/frozen_output/01_corpus/data/triples_sections.jsonl"
LEDGER_SHA="89d18b2401d451bdc696923d9d315eac84406d2aed9fe5bc96f009aef357764b"
GOT_LEDGER=$(sha256sum "$LEDGER" | cut -d' ' -f1)
if [[ "$GOT_LEDGER" != "$LEDGER_SHA" ]]; then
    echo "FATAL: frozen ledger sha256 $GOT_LEDGER != pinned $LEDGER_SHA" >&2
    exit 92
fi
echo "PASS: frozen attempt ledger pinned ($LEDGER_SHA)"

# ---- guarded files: md5 BEFORE ---------------------------------------------
GUARDED=(
  "$CORPUS_DIR/data/triples_sections.jsonl"
  "$CORPUS_DIR/data/triple_mentions.jsonl"
  "$CORPUS_DIR/data/canonical_triples.jsonl"
  "$CORPUS_DIR/releases/2.2.0/data/triples_sections.jsonl"
  "$CORPUS_DIR/releases/2.2.0/data/triple_mentions.jsonl"
  "$CORPUS_DIR/releases/2.2.0/data/canonical_triples.jsonl"
)
echo "[$(date -u +%FT%TZ)] hashing ${#GUARDED[@]} guarded files (before)"
md5sum "${GUARDED[@]}" > "$OUTDIR/.md5_before.txt"
cat "$OUTDIR/.md5_before.txt"

# max_tokens in the config must still be the FROZEN value, or the reported
# "4,500 -> 16,384" provenance line would be a lie.
CFG_TOKENS=$(python - <<'PY'
import os, yaml, pathlib
p = pathlib.Path(os.environ["CDM_ROOT"]) / "pipelines/corpus_v2/config/corpus.yaml"
print(yaml.safe_load(p.read_text())["llm"]["max_tokens"])
PY
)
if [[ "$CFG_TOKENS" != "4500" ]]; then
    echo "FATAL: corpus.yaml llm.max_tokens is $CFG_TOKENS, expected frozen 4500" >&2
    exit 93
fi
echo "PASS: corpus.yaml max_tokens is the frozen 4500 (pilot overrides in memory only)"

# ---- vLLM: single A40 -------------------------------------------------------
echo "[$(date -u +%FT%TZ)] starting vLLM (port $PORT, max-num-seqs $MAX_NUM_SEQS)"
CUDA_VISIBLE_DEVICES=0 vllm serve "$MODEL" \
    --port "$PORT" \
    --gpu-memory-utilization 0.90 \
    --max-model-len 32768 \
    --max-num-seqs "$MAX_NUM_SEQS" \
    --served-model-name "$MODEL" \
    > "$OUTDIR/vllm-${JID}.log" 2>&1 &
SERVER_PID=$!

cleanup() {
    echo "[$(date -u +%FT%TZ)] stopping vLLM pid=$SERVER_PID"
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
}
trap cleanup EXIT

ready=""
for _ in $(seq 1 120); do
    if curl -sf "http://127.0.0.1:${PORT}/v1/models" >/dev/null 2>&1; then
        ready=1; break
    fi
    if ! kill -0 "$SERVER_PID" 2>/dev/null; then
        echo "ERROR: vLLM exited during startup; last 50 lines:" >&2
        tail -50 "$OUTDIR/vllm-${JID}.log" >&2 || true
        exit 1
    fi
    sleep 5
done
if [[ -z "$ready" ]]; then
    echo "ERROR: vLLM not ready after 600s; last 50 lines:" >&2
    tail -50 "$OUTDIR/vllm-${JID}.log" >&2 || true
    exit 1
fi
echo "[$(date -u +%FT%TZ)] vLLM ready"

# ---- the pilot -------------------------------------------------------------
echo "[$(date -u +%FT%TZ)] running pilot (max_tokens=$MAX_TOKENS workers=$WORKERS" \
     "arms=$PILOT_ARMS limit=$PILOT_LIMIT)"
set +e
python "$RUNNER" \
    --max-tokens "$MAX_TOKENS" \
    --port "$PORT" \
    --workers "$WORKERS" \
    --arms "$PILOT_ARMS" \
    --limit "$PILOT_LIMIT" \
    2>&1 | tee "$OUTDIR/run_pilot.${JID}.log"
RC=${PIPESTATUS[0]}
set -e
echo "[$(date -u +%FT%TZ)] run_pilot exit code: $RC"

# ---- guarded files: md5 AFTER + hard assertion ------------------------------
echo "[$(date -u +%FT%TZ)] hashing ${#GUARDED[@]} guarded files (after)"
md5sum "${GUARDED[@]}" > "$OUTDIR/.md5_after.txt"
if ! diff -u "$OUTDIR/.md5_before.txt" "$OUTDIR/.md5_after.txt"; then
    echo "FATAL: guarded corpus files CHANGED during the run" >&2
    exit 90
fi
echo "PASS: guarded corpus files unchanged"

# ---- read-only baseline re-verification ------------------------------------
fail=0
check_baseline() {  # $1=dir  $2=expected-ok  $3=label
    local dir="$1" expect="$2" label="$3" ok
    ok=$(cd "$dir" && sha256sum -c MANIFEST.sha256 2>/dev/null | grep -c ': OK$' || true)
    if [[ "$ok" == "$expect" ]]; then
        echo "PASS: $label $ok/$expect"
    else
        echo "FAIL: $label $ok/$expect" >&2
        fail=1
    fi
}
check_baseline "$CORPUS_DIR/releases/2.2.0" 42  "pipelines/corpus_v2/releases/2.2.0"
check_baseline "$REPO/releases/data_catalogue"     1003 "data_catalogue"
check_baseline "$REPO/releases/terminology/1.0.0" 22 "releases/terminology/1.0.0"
if [[ "$fail" -ne 0 ]]; then
    echo "FATAL: a read-only baseline failed; stopping" >&2
    exit 91
fi

# ---- outcome ---------------------------------------------------------------
echo "[$(date -u +%FT%TZ)] artifacts:"
ls -la "$OUTDIR" || true
if [[ "$RC" -ne 0 ]]; then
    echo "INCOMPLETE: run_pilot exited $RC (sections.jsonl is resumable)" >&2
    exit "$RC"
fi
echo "[$(date -u +%FT%TZ)] DONE"
