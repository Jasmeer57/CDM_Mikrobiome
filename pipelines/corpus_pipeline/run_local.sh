#!/usr/bin/env bash
# Local (no-GPU) pipeline stages. Runs in dependency order on a CPU node.
# Safe to re-run: each stage is idempotent and caches by content checksum.
#
#   ./corpus_pipeline/run_local.sh            # run all local stages
#   ./corpus_pipeline/run_local.sh --dry-run  # print what would run
set -euo pipefail
cd "$(dirname "$0")/.."
LOGDIR=pipelines/corpus_pipeline/logs
mkdir -p "$LOGDIR"

DRY=0
[[ "${1:-}" == "--dry-run" ]] && DRY=1

run() {
  local name=$1; shift
  echo "=== $name ==="
  if [[ $DRY == 1 ]]; then echo "  would run: $*"; return; fi
  python "$@" 2>&1 | tee -a "$LOGDIR/$name.log" | tail -20
}

run reconcile    pipelines/corpus_pipeline/stage01_reconcile.py
run select       pipelines/corpus_pipeline/stage04_select_sections.py
run chunk        pipelines/corpus_pipeline/stage08_chunk.py
run bm25         pipelines/corpus_pipeline/stage12_bm25.py
run validate     pipelines/corpus_pipeline/stage14_validate.py

cat <<'EOF'

Local stages complete. GPU stages remain:
  sbatch pipelines/corpus_pipeline/slurm/06_jev.sbatch
  sbatch pipelines/corpus_pipeline/slurm/11_embeddings.sbatch
  python pipelines/corpus_pipeline/stage14_validate.py    # re-validate afterwards
EOF