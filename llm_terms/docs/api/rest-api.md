# REST API Reference

The CDM Entity Extraction API provides a comprehensive RESTful interface for biomedical entity extraction and CDM mapping.

## Base URL

```
Production: https://api.cdm-pipeline.org/v1
Development: http://localhost:8000
```

## Authentication

Currently the API doesn't require authentication. In production deployments, API keys will be required.

## Endpoints

### Health Check

Check if the API and LLM service are available.

```http
GET /health
```

**Response:**
```json
{
  "status": "healthy",
  "message": "LLM service available",
  "pipeline_ready": true,
  "available_models": ["phi3:mini", "qwen3:8b", "llama2:7b"],
  "version": "1.0.0"
}
```

### Configuration

Get pipeline configuration and available features.

```http
GET /config
```

**Response:**
```json
{
  "entity_types": {
    "GENE": {
      "description": "Genes, genetic markers, gene families",
      "examples": ["Bacteroides", "Firmicutes"],
      "priority": 1
    }
  },
  "default_config": {
    "model": "phi3:mini",
    "max_workers": 3,
    "max_entities": 200
  },
  "supported_features": [
    "semantic_deduplication",
    "biomistral_validation",
    "omop_mapping"
  ]
}
```

### Extract Entities

Extract entities from text (synchronous).

```http
POST /extract
Content-Type: application/json
```

**Request Body:**
```json
{
  "text": "Gut bacteria produce butyrate which reduces inflammation. Bacteroides and Firmicutes are major phyla.",
  "model": "phi3:mini",
  "base_url": "http://localhost:11434",
  "chunk_size": 5000,
  "max_entities": 100,
  "min_confidence": 0.6,
  "semantic_threshold": 0.8,
  "enable_biomistral": true,
  "enable_omop_mapping": true,
  "enable_umls_mapping": true,
  "enable_comprehensive_mapping": true,
  "max_workers": 3
}
```

**Response:**
```json
{
  "task_id": "12345678-1234-1234-1234-123456789012",
  "status": "completed",
  "message": "Successfully extracted 5 entities",
  "entities": [
    {
      "entity": "Bacteroides",
      "entity_type": "ORGANISM",
      "confidence": 0.92,
      "context": "Bacteroides and Firmicutes are major phyla",
      "source": "chunk_1"
    }
  ],
  "metadata": {
    "processing_time": 12.5,
    "text_length": 156,
    "model_used": "phi3:mini",
    "features_enabled": {
      "biomistral": true,
      "omop_mapping": true,
      "semantic_deduplication": true
    }
  },
  "statistics": {
    "total_entities": 5,
    "entity_type_distribution": {
      "ORGANISM": 3,
      "CHEMICAL": 2
    },
    "average_confidence": 0.87
  }
}
```

### Extract Entities (Async)

Extract entities from text (asynchronous processing).

```http
POST /extract/async
Content-Type: application/json
```

**Request Body:** Same as `/extract`

**Response:**
```json
{
  "task_id": "12345678-1234-1234-1234-123456789012",
  "status": "pending",
  "message": "Task started. Check status with /task/{task_id}"
}
```

### Get Task Status

Check the status of an asynchronous extraction task.

```http
GET /task/{task_id}
```

**Response:**
```json
{
  "task_id": "12345678-1234-1234-1234-123456789012",
  "status": "running",
  "message": "Processing extraction",
  "progress": 0.75,
  "result": null,
  "error": null,
  "created_at": "2024-01-15T10:30:00Z",
  "completed_at": null
}
```

### Delete Task

Delete a completed task.

```http
DELETE /task/{task_id}
```

**Response:**
```json
{
  "message": "Task deleted successfully"
}
```

### List Tasks

List all tasks.

```http
GET /tasks
```

**Response:**
```json
{
  "tasks": [
    {
      "task_id": "12345678-1234-1234-1234-123456789012",
      "status": "completed",
      "message": "Successfully extracted entities",
      "created_at": "2024-01-15T10:30:00Z",
      "completed_at": "2024-01-15T10:32:00Z"
    }
  ],
  "total": 1
}
```

### Upload and Extract

Upload a file and extract entities.

```http
POST /upload
Content-Type: multipart/form-data
```

**Form Data:**
- `file`: Text file (.txt, .md)
- `model`: LLM model (optional)
- `enable_biomistral`: Enable BioMistral validation (optional)
- `enable_comprehensive_mapping`: Enable comprehensive mapping (optional)

**Response:** Same as `/extract`

### List Available Models

List available LLM models.

```http
GET /models
```

**Response:**
```json
{
  "available_models": ["phi3:mini", "qwen3:8b", "llama2:7b"],
  "default_model": "phi3:mini",
  "total_models": 3
}
```

## Entity Types

| Type | Description | Examples |
|------|-------------|----------|
| **GENE** | Genes, genetic markers, gene families | `Bacteroides`, `Firmicutes` |
| **PROTEIN** | Proteins, enzymes, receptors | `Butyrate kinase` |
| **ORGANISM** | Bacteria, archaea, fungi, viruses | `E. coli` |
| **DISEASE** | Diseases, conditions, disorders | `Inflammatory bowel disease` |
| **CHEMICAL** | Metabolites, SCFAs, drugs | `Butyrate`, `Propionate` |
| **DNA_RNA** | Genetic material, sequences | `16S rRNA` |
| **CELL_TYPE** | Cell types, immune cells | `T-cells`, `B-cells` |
| **BIOINFO_TOOL** | Bioinformatics tools, databases | `BLAST`, `Qiime` |
| **GENOMICS** | Omics technologies, methods | `Metagenomics` |
| **CLINICAL** | Clinical terms, procedures | `Gut microbiota analysis` |

## Request Parameters

### Core Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `text` | string | required | Text to extract entities from (50-1,000,000 chars) |
| `model` | string | "phi3:mini" | LLM model to use |
| `base_url` | string | "http://localhost:11434" | LLM service URL |
| `chunk_size` | integer | null | Chunk size in characters (auto-adaptive if null) |
| `max_entities` | integer | 200 | Maximum entities to extract (1-1000) |
| `min_confidence` | float | 0.6 | Minimum confidence threshold (0.0-1.0) |
| `max_workers` | integer | 3 | Maximum parallel workers (1-10) |

### Feature Flags

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `enable_biomistral` | boolean | false | Enable BioMistral validation |
| `enable_omop_mapping` | boolean | false | Enable OMOP CDM mapping |
| `enable_umls_mapping` | boolean | false | Enable UMLS mapping |
| `enable_comprehensive_mapping` | boolean | false | Enable comprehensive mapping |
| `semantic_threshold` | float | 0.8 | Semantic similarity threshold (0.0-1.0) |

## Response Format

### Success Response

```json
{
  "task_id": "uuid",
  "status": "completed|pending|running|failed",
  "message": "Human-readable status message",
  "entities": [
    {
      "entity": "Entity name",
      "entity_type": "ENTITY_TYPE",
      "confidence": 0.95,
      "context": "Context where entity was found",
      "source": "chunk_identifier"
    }
  ],
  "metadata": {
    "processing_time": 12.5,
    "text_length": 1000,
    "model_used": "phi3:mini",
    "features_enabled": {
      "biomistral": true,
      "omop_mapping": true
    }
  },
  "statistics": {
    "total_entities": 50,
    "entity_type_distribution": {
      "ORGANISM": 20,
      "CHEMICAL": 15,
      "GENE": 10
    },
    "average_confidence": 0.85,
    "source_distribution": {
      "chunk_1": 25,
      "chunk_2": 25
    }
  }
}
```

### Error Response

```json
{
  "detail": "Error message description",
  "error_code": "VALIDATION_ERROR",
  "timestamp": "2024-01-15T10:30:00Z"
}
```

## Status Codes

| Code | Description |
|------|-------------|
| `200` | Success |
| `400` | Bad Request (validation error) |
| `404` | Not Found (task not found) |
| `413` | Payload Too Large (text > 1MB) |
| `422` | Unprocessable Entity (invalid JSON) |
| `429` | Too Many Requests (rate limit exceeded) |
| `500` | Internal Server Error |
| `503` | Service Unavailable (LLM service down) |

## Rate Limits

- **Synchronous requests**: 10 requests per minute
- **Asynchronous requests**: 60 requests per minute
- **File uploads**: 5 uploads per minute
- **Maximum text size**: 1MB per request
- **Maximum file size**: 5MB per upload

## Examples

### Basic Extraction

```bash
curl -X POST "http://localhost:8000/extract" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Gut bacteria produce butyrate which reduces inflammation.",
    "model": "phi3:mini"
  }'
```

### Advanced Extraction with All Features

```bash
curl -X POST "http://localhost:8000/extract" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Gut bacteria produce butyrate which reduces inflammation. Bacteroides and Firmicutes are major phyla.",
    "model": "qwen3:8b",
    "enable_biomistral": true,
    "enable_omop_mapping": true,
    "enable_umls_mapping": true,
    "enable_comprehensive_mapping": true,
    "semantic_threshold": 0.8,
    "max_entities": 100
  }'
```

### File Upload

```bash
curl -X POST "http://localhost:8000/upload" \
  -F "file=@research_paper.txt" \
  -F "enable_biomistral=true" \
  -F "enable_comprehensive_mapping=true"
```

### Asynchronous Processing

```bash
# Start extraction
TASK_ID=$(curl -X POST "http://localhost:8000/extract/async" \
  -H "Content-Type: application/json" \
  -d '{"text": "Large text...", "model": "phi3:mini"}' \
  | jq -r '.task_id')

# Check status
curl "http://localhost:8000/task/$TASK_ID"
```

## SDKs and Client Libraries

### Python

```python
import requests

# Basic extraction
response = requests.post("http://localhost:8000/extract", json={
    "text": "Gut bacteria produce butyrate",
    "model": "phi3:mini"
})

result = response.json()
print(f"Found {len(result['entities'])} entities")
```

### JavaScript

```javascript
const response = await fetch('http://localhost:8000/extract', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    text: 'Gut bacteria produce butyrate',
    model: 'phi3:mini'
  })
});

const result = await response.json();
console.log(`Found ${result.entities.length} entities`);
```

## WebSocket Support

Real-time extraction progress updates (coming soon).

```javascript
const ws = new WebSocket('ws://localhost:8000/ws/extract');
ws.onmessage = (event) => {
  const progress = JSON.parse(event.data);
  console.log(`Progress: ${progress.percentage}%`);
};
```

---

For more information, see the [Python API](python-api.md) and [Configuration Guide](../getting-started/configuration.md).