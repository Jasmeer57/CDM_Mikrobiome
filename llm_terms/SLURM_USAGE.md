# CDM Pipeline SLURM Job Script

## Overview
This SLURM script (`run_cdm_pipeline.sh`) is designed to run the complete CDM (Common Data Model) Microbiome Entity Extraction Pipeline on HPC clusters with GPU support.

## Features
- **Automatic Environment Setup**: Creates conda environment and installs dependencies
- **GPU Support**: Optimized for NVIDIA A100 GPUs with CUDA 12.3
- **Model Management**: Automatically downloads required Ollama models
- **Resource Optimization**: Intelligent model selection based on available GPU memory
- **Comprehensive Logging**: Detailed job logging with progress tracking
- **Error Handling**: Robust error checking and cleanup

## Requirements
- HPC cluster with SLURM scheduler
- GPU partition with NVIDIA GPUs (A100 recommended)
- Miniforge3 module available
- CUDA 12.3 compatible drivers
- Internet access for model downloads (first time)

## Usage

### Basic Usage
```bash
sbatch run_cdm_pipeline.sh <input_file.txt> [max_entities]
```

### Examples
```bash
# Basic run with default settings (100 entities)
sbatch run_cdm_pipeline.sh /path/to/your/document.txt

# Custom entity count
sbatch run_cdm_pipeline.sh /path/to/your/document.txt 200

# Full path example
sbatch run_cdm_pipeline.sh /home/user/data/microbiome_paper.txt 150
```

## Configuration

### SLURM Resources
- **Time**: 24 hours (adjustable)
- **Memory**: 120GB RAM
- **CPUs**: 16 cores
- **GPU**: 1x A100 (32GB+ VRAM)
- **Partition**: gpu-amd (modify as needed)

### Pipeline Parameters
- **Models**:
  - `phi3:mini` (for GPUs < 32GB)
  - `qwen3:8b` (for GPUs ≥ 32GB)
  - `biomistral:7b` (biomedical deduplication)
  - `nomic-embed-text` (semantic deduplication)
- **Semantic Threshold**: 0.8 (similarity for deduplication)
- **Max Workers**: Uses all allocated CPUs
- **🔬 BioMistral Deduplication**: Enabled by default for contextual biomedical duplicates

## Output Files

### Generated Files
- `cdm_entities.json` - Main entity extraction results
- `llm_terms.db` - SQLite database with all records
- `logs/llm_terms_*.out` - Job output logs
- `logs/llm_terms_*.err` - Job error logs

### Output Content
The `cdm_entities.json` file contains:
- Extraction metadata (model used, processing time)
- Text statistics (character/word count)
- Extraction statistics (entity counts, confidence scores)
- Categorized entities (ORGANISM, GENE, PROTEIN, etc.)

## Customization

### Modify Resource Requirements
Edit the SLURM directives at the top of the script:
```bash
#SBATCH --time=48:00:00     # Increase to 48 hours
#SBATCH --mem=240G          # Increase memory
#SBATCH --cpus-per-task=32  # More CPU cores
```

### Change Models
Modify the `MODELS` array in the script:
```bash
MODELS=("phi3:mini" "llama3.1:8b" "nomic-embed-text:latest")
```

### Adjust Pipeline Parameters
Edit the pipeline execution command:
```bash
python main.py \
    --input-file "$INPUT_FILE" \
    --model "llama3.1:8b" \
    --max-entities "$MAX_ENTITIES" \
    --semantic-threshold 0.9 \  # Stricter deduplication
    --enable-correction \       # Enable term correction
    --enable-llm-correction \   # Enable LLM type correction
    --max-workers 8 \           # Fewer workers
    --verbose
```

## Monitoring

### Check Job Status
```bash
# View all your jobs
squeue -u $USER

# View specific job
squeue -j <job_id>

# View job logs
tail -f logs/llm_terms_<job_id>.out
```

### Job Statistics
The script automatically reports:
- Total entities extracted
- Entity type distribution
- Average confidence scores
- Processing time
- Resource usage

## Troubleshooting

### Common Issues

1. **Model Download Failed**
   - Check internet connectivity
   - Verify Ollama service started
   - Check available disk space

2. **GPU Memory Issues**
   - Script automatically selects appropriate model
   - Can force smaller model: `--model phi3:mini`

3. **Environment Issues**
   - Script creates environment automatically
   - Check Miniforge3 module availability

4. **Permission Issues**
   - Ensure script is executable: `chmod +x run_cdm_pipeline.sh`
   - Check write permissions in working directory

### Debug Mode
Add verbose logging to the pipeline:
```bash
python main.py --verbose --debug
```

## Performance Tips

1. **Batch Processing**: For multiple files, create separate jobs
2. **Resource Allocation**: Use maximum available GPU memory
3. **Model Selection**: Larger models provide better accuracy but slower processing
4. **Semantic Threshold**: Lower values (0.7) = more aggressive deduplication
5. **Entity Limits**: Set reasonable `max_entities` to prevent memory issues

## Integration with Workflows

### Example Pipeline Script
```bash
#!/bin/bash
# Process multiple files
for file in data/*.txt; do
    echo "Processing $file..."
    sbatch run_cdm_pipeline.sh "$file" 150
    sleep 60  # Wait between submissions
done
```

### Monitor All Jobs
```bash
watch -n 30 'squeue -u $USER && echo "=== Completed Jobs ===" && ls logs/llm_terms_*.out | wc -l'
```

## Supported File Formats
- Plain text files (.txt)
- UTF-8 encoding
- Maximum recommended size: 10MB per file
- Larger files are automatically chunked

## Version Requirements
- Python 3.10+
- CUDA 12.3
- Ollama (latest)
- All dependencies auto-installed by script