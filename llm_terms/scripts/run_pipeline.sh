#!/bin/bash

# Start Ollama in background
echo "========================================================================"
echo "CDM Entity Extraction - phi4:14b - MULTI-PASS TEST"
echo "========================================================================"
echo "Starting Ollama..."

# Set OLLAMA_HOST to use localhost
export OLLAMA_HOST=127.0.0.1:11434
export OLLAMA_NUM_THREADS=8

# Start ollama serve in background
ollama serve > /dev/null 2>&1 &
OLLAMA_PID=$!

# Wait for Ollama to be ready
echo "Waiting for Ollama to start..."
for i in {1..30}; do
    if curl -s http://127.0.0.1:11434/api/tags > /dev/null 2>&1; then
        echo "✓ Ollama ready (PID: $OLLAMA_PID)"
        break
    fi
    if [ $i -eq 30 ]; then
        echo "✗ Ollama failed to start"
        exit 1
    fi
    sleep 1
done

echo ""
echo "Running extraction with ALL 6 PASSES..."
echo ""

# Run the Python pipeline
python standalone_pipeline.py "$@"

# Cleanup: Kill Ollama
kill $OLLAMA_PID 2>/dev/null
wait $OLLAMA_PID 2>/dev/null

echo ""
echo "✓ Pipeline complete"
