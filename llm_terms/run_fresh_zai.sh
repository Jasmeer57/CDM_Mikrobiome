#!/bin/bash
# Fresh run in output_fresh directory, strictly avoiding old checkpoints

# Ensure directories exist (redundant but safe)
mkdir -p output_fresh/processed
mkdir -p output_fresh/checkpoints

# Load API key from environment or use empty string
ZAI_API_KEY="${GLM_API_KEY:-}"

if [ -z "$ZAI_API_KEY" ]; then
  echo "ERROR: GLM_API_KEY environment variable not set!"
  echo "Please set it with: export GLM_API_KEY='your-api-key'"
  exit 1
fi

nohup python3 standalone_pipeline.py \
  --input ../papers_txt/ \
  --output output_fresh/cdm_entities_zai_fresh.json \
  --api-type glm \
  --api-key "$ZAI_API_KEY" \
  --model glm-4.7 \
  --base-url https://api.z.ai/api/coding/paas/v4 \
  --enable-advanced-analytics \
  --include-speculative \
  --fast-mode \
  --force \
  --max-workers 1 \
  --max-file-workers 1 \
  --log-format text \
  --verbose > output_fresh/nohup_fresh.log 2>&1 &

echo $! > output_fresh/fresh_pid.txt
echo "Fresh run started under PID $(cat output_fresh/fresh_pid.txt)"
