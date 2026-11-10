#!/usr/bin/env bash
# Submit the GPU stages in dependency order.
# The JEV and embedding stages are independent of each other; the dense index
# depends on embeddings, so it runs inside the same job as 11_embeddings.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== stage 1/4: reconcile + select (local) =="
./corpus_pipeline/run_local.sh

echo "== stage 2/4: chunk + bm25 (local) =="
echo "   (already produced by run_local.sh)"

echo "== stage 3/4: JEV + embeddings on GPU =="
JEV=$(sbatch --parsable pipelines/corpus_pipeline/slurm/06_jev.sbatch)
echo "   JEV          job ${JEV}"
EMB=$(sbatch --parsable pipelines/corpus_pipeline/slurm/11_embeddings.sbatch)
echo "   embeddings   job ${EMB}"

echo "== stage 4/4: validation (run after both jobs succeed) =="
cat <<EOF
  watch -n30 "squeue -j ${JEV},${EMB}"
  # then, once both are done:
  scontrol show job ${JEV} | grep -E 'JobState|ExitCode'
  scontrol show job ${EMB} | grep -E 'JobState|ExitCode'
  python pipelines/corpus_pipeline/stage14_validate.py
EOF