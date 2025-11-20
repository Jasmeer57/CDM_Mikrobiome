# 🔬 Extraction Endpoints

## 📋 Table of Contents
- [Overview](#overview)
- [POST /extract](#post-extract)
- [POST /extract/sync](#post-extractsync)
- [POST /batch](#post-batch)
- [GET /jobs/{job_id}](#get-jobsjob_id)
- [POST /upload](#post-upload)
- [GET /files/{file_id}](#get-filesfile_id)
- [Examples and Use Cases](#examples-and-use-cases)

## 🎯 Overview

The extraction endpoints provide the core functionality for processing scientific text and extracting biomedical terminology. These endpoints support various input methods, processing modes, and output formats to accommodate different use cases.

### **Available Endpoints**
- **`/extract`** - Asynchronous text extraction (recommended)
- **`/extract/sync`** - Synchronous text extraction (immediate response)
- **`/batch`** - Batch processing multiple texts
- **`/upload`** - File upload and processing
- **`/jobs/{job_id}`** - Retrieve job results
- **`/files/{file_id}`** - Retrieve processed file results

### **Processing Modes**

| **Mode** | **Use Case** | **Response Time** | **Best For** |
|----------|--------------|-------------------|--------------|
| Async | Large texts, production use | Polling required | Web applications, pipelines |
| Sync | Small texts, testing | Immediate (up to 30s) | APIs, real-time processing |
| Batch | Multiple documents | Polling required | Bulk processing, analysis |
| Upload | Document files | Polling required | File-based workflows |

## 📤 POST /extract

Asynchronously extract terms from scientific text. This is the recommended endpoint for production use.

### **Endpoint**
```http
POST /extract
Content-Type: application/json
Authorization: Bearer {api_key} (optional)
```

### **Request Body**

```json
{
  "text": "string (required)",
  "options": {
    "semantic_model": "mini-lm|nomic|mpnet (optional, default: mini-lm)",
    "ai_correction_enabled": "boolean (optional, default: false)",
    "umls_mapping_enabled": "boolean (optional, false)",
    "fuzzy_threshold": "number (0.0-1.0, optional, default: 0.85)",
    "semantic_threshold": "number (0.0-1.0, optional, default: 0.9)",
    "biomedical_deduplication": "boolean (optional, default: true)",
    "include_audit_trail": "boolean (optional, default: false)",
    "minimum_terms": "integer (optional, default: 75)",
    "research_mode": "boolean (optional, default: false)",
    "output_format": "json|csv|sqlite (optional, default: json)",
    "language": "string (optional, default: en)",
    "domain": "string (optional, general|microbiome|clinical|research)"
  },
  "callback_url": "string (optional)"
}
```

### **Request Parameters**

| **Parameter** | **Type** | **Required** | **Description** |
|---------------|----------|--------------|-----------------|
| `text` | string | ✅ | Scientific text to process (max 100,000 chars) |
| `options.semantic_model` | string | ❌ | Semantic similarity model for deduplication |
| `options.ai_correction_enabled` | boolean | ❌ | Enable BioMistral AI-powered correction |
| `options.umls_mapping_enabled` | boolean | ❌ | Enable UMLS ontology mapping |
| `options.fuzzy_threshold` | number | ❌ | Fuzzy deduplication similarity threshold |
| `options.semantic_threshold` | number | ❌ | Semantic deduplication similarity threshold |
| `options.biomedical_deduplication` | boolean | ❌ | Enable BioMistral biomedical deduplication |
| `options.include_audit_trail` | boolean | ❌ | Include decision provenance in output |
| `options.minimum_terms` | integer | ❌ | Minimum terms to extract per document |
| `options.research_mode` | boolean | ❌ | Include more terms, less filtering |
| `options.output_format` | string | ❌ | Output format for results |
| `options.language` | string | ❌ | Text language (ISO code) |
| `options.domain` | string | ❌ | Domain-specific processing |
| `callback_url` | string | ❌ | URL to call when processing completes |

### **Response**

#### **202 Accepted - Job Submitted**
```json
{
  "success": true,
  "data": {
    "job_id": "job_1234567890abcdef",
    "status": "queued",
    "estimated_time": 15,
    "queue_position": 3
  },
  "message": "Text processing job created successfully",
  "timestamp": "2024-01-15T10:30:00Z",
  "request_id": "req_1234567890abcdef"
}
```

### **Example Usage**

```bash
# Basic extraction
curl -X POST "http://localhost:8000/extract" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "The human gut microbiome contains Bacteroides fragilis and Firmicutes bacteria. These microorganisms produce short-chain fatty acids through fermentation processes affecting intestinal health.",
    "options": {
      "semantic_model": "mini-lm",
      "ai_correction_enabled": true,
      "include_audit_trail": true
    }
  }'

# With callback URL
curl -X POST "http://localhost:8000/extract" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Inflammatory bowel disease patients show altered gut microbiota composition with reduced microbial diversity and increased abundance of Proteobacteria.",
    "options": {
      "semantic_model": "mpnet",
      "domain": "clinical",
      "umls_mapping_enabled": true
    },
    "callback_url": "https://your-app.com/callback/extraction-complete"
  }'
```

## ⚡ POST /extract/sync

Synchronously extract terms from text. Returns results immediately (up to 30 second timeout).

### **Endpoint**
```http
POST /extract/sync
Content-Type: application/json
Authorization: Bearer {api_key} (optional)
```

### **Request Body**

Same as `/extract` endpoint, but with additional size limitations:
- **Maximum text length**: 10,000 characters
- **Processing timeout**: 30 seconds

### **Response**

#### **200 OK - Processing Complete**
```json
{
  "success": true,
  "data": {
    "terms": [
      {
        "term": "Bacteroides fragilis",
        "canonical_term": "Bacteroides fragilis",
        "label": "ORGANISM",
        "relevance_score": 0.95,
        "frequency": 2,
        "context": "Bacteroides fragilis produces short-chain fatty acids",
        "models_used": ["en_core_sci_lg", "en_ner_bc5cdr_md"],
        "examples": [
          "Bacteroides fragilis is a Gram-negative anaerobic bacterium",
          "B. fragilis is commonly found in the human gut"
        ],
        "umls_mappings": [
          {
            "cui": "C0004623",
            "name": "Bacteroides fragilis",
            "semantic_types": ["Bacterium"]
          }
        ],
        "ai_correction": null,
        "biomedical_duplicate": null
      }
    ],
    "metadata": {
      "text_length": 245,
      "processing_time": 3.45,
      "models_used": ["en_core_sci_lg", "en_ner_craft_md", "en_ner_bc5cdr_md"],
      "deduplication_applied": ["exact", "fuzzy"],
      "ai_corrections_applied": 0,
      "quality_score": 0.92,
      "terms_extracted": 15,
      "terms_removed": {
        "exact": 2,
        "fuzzy": 1,
        "semantic": 1,
        "biomedical": 0
      }
    }
  },
  "message": "Text processing completed successfully",
  "timestamp": "2024-01-15T10:30:00Z",
  "processing_time": 3.456,
  "request_id": "req_1234567890abcdef"
}
```

### **Example Usage**

```bash
# Quick synchronous extraction
curl -X POST "http://localhost:8000/extract/sync" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Bacteroides fragilis is a gut bacterium that produces short-chain fatty acids.",
    "options": {
      "semantic_model": "mini-lm"
    }
  }'
```

## 📦 POST /batch

Process multiple texts in a single batch. Each text is processed independently.

### **Endpoint**
```http
POST /batch
Content-Type: application/json
Authorization: Bearer {api_key} (optional)
```

### **Request Body**

```json
{
  "texts": [
    "string (required)",
    "string (required)"
  ],
  "options": {
    // Same options as /extract endpoint
    "semantic_model": "mini-lm",
    "ai_correction_enabled": false
  },
  "callback_url": "string (optional)",
  "job_name": "string (optional)"
}
```

### **Parameters**

| **Parameter** | **Type** | **Required** | **Description** |
|---------------|----------|--------------|-----------------|
| `texts` | array | ✅ | Array of texts to process (max 100 texts) |
| `options` | object | ❌ | Processing options (same as `/extract`) |
| `callback_url` | string | ❌ | URL to call when entire batch completes |
| `job_name` | string | ❌ | Human-readable name for the batch job |

### **Response**

```json
{
  "success": true,
  "data": {
    "batch_id": "batch_1234567890abcdef",
    "job_ids": [
      "job_1234567890abcde1",
      "job_1234567890abcde2",
      "job_1234567890abcde3"
    ],
    "status": "processing",
    "total_texts": 3,
    "estimated_time": 45
  },
  "message": "Batch job created successfully",
  "timestamp": "2024-01-15T10:30:00Z"
}
```

### **Example Usage**

```bash
# Batch processing
curl -X POST "http://localhost:8000/batch" \
  -H "Content-Type: application/json" \
  -d '{
    "texts": [
      "The gut microbiome contains diverse bacterial populations including Bacteroides and Firmicutes.",
      "Short-chain fatty acids like butyrate are produced by microbial fermentation.",
      "Inflammatory bowel disease is associated with dysbiosis of the intestinal microbiota."
    ],
    "options": {
      "semantic_model": "nomic",
      "ai_correction_enabled": true,
      "include_audit_trail": true
    },
    "job_name": "microbiome_research_batch_1"
  }'
```

## 🔍 GET /jobs/{job_id}

Retrieve the results of a processing job.

### **Endpoint**
```http
GET /jobs/{job_id}
Authorization: Bearer {api_key} (optional)
```

### **Path Parameters**

| **Parameter** | **Type** | **Description** |
|---------------|----------|-----------------|
| `job_id` | string | ID of the job to retrieve |

### **Response**

#### **Job Completed**
```json
{
  "success": true,
  "data": {
    "job_id": "job_1234567890abcdef",
    "status": "completed",
    "created_at": "2024-01-15T10:30:00Z",
    "completed_at": "2024-01-15T10:32:15Z",
    "processing_time": 135.5,
    "input_text_length": 1250,
    "results": {
      "terms": [
        // Same format as /extract/sync response
      ],
      "metadata": {
        "quality_score": 0.94,
        "terms_extracted": 87,
        "ai_corrections_applied": 3,
        "deduplication_stats": {
          "original_count": 124,
          "final_count": 87,
          "reduction_rate": 0.298
        }
      }
    }
  }
}
```

#### **Job Processing**
```json
{
  "success": true,
  "data": {
    "job_id": "job_1234567890abcdef",
    "status": "processing",
    "created_at": "2024-01-15T10:30:00Z",
    "estimated_completion": "2024-01-15T10:32:00Z",
    "progress": {
      "stage": "semantic_deduplication",
      "percentage": 65,
      "terms_processed": 81
    }
  }
}
```

#### **Job Failed**
```json
{
  "success": false,
  "data": {
    "job_id": "job_1234567890abcdef",
    "status": "failed",
    "created_at": "2024-01-15T10:30:00Z",
    "failed_at": "2024-01-15T10:31:45Z",
    "error": {
      "code": "PROCESSING_ERROR",
      "message": "GPU memory insufficient for semantic model",
      "stage": "semantic_deduplication"
    }
  }
}
```

### **Example Usage**

```bash
# Check job status
curl "http://localhost:8000/jobs/job_1234567890abcdef"

# With authentication
curl -H "Authorization: Bearer YOUR_API_KEY" \
     "http://localhost:8000/jobs/job_1234567890abcdef"
```

## 📁 POST /upload

Upload and process a document file.

### **Endpoint**
```http
POST /upload
Content-Type: multipart/form-data
Authorization: Bearer {api_key} (optional)
```

### **Request Body**

| **Parameter** | **Type** | **Required** | **Description** |
|---------------|----------|--------------|-----------------|
| `file` | file | ✅ | Document file (txt, md, pdf, docx) |
| `options` | string | ❌ | JSON string of processing options |
| `extract_sections` | boolean | ❌ | Extract sections from PDF/DOCX |
| `language` | string | ❌ | Document language (default: auto-detect) |

### **File Support**

| **Format** | **Max Size** | **Features** |
|------------|--------------|--------------|
| `.txt` | 10MB | Plain text processing |
| `.md` | 10MB | Markdown with formatting |
| `.pdf` | 50MB | Text extraction with section detection |
| `.docx` | 50MB | Word document processing |
| `.csv` | 10MB | Structured data processing |

### **Response**

```json
{
  "success": true,
  "data": {
    "file_id": "file_1234567890abcdef",
    "job_id": "job_1234567890abcdef",
    "filename": "research_paper.pdf",
    "file_size": 1048576,
    "file_type": "application/pdf",
    "status": "processing",
    "extracted_text_length": 5432,
    "sections_detected": 7
  },
  "message": "File uploaded and processing started",
  "timestamp": "2024-01-15T10:30:00Z"
}
```

### **Example Usage**

```bash
# Upload text file
curl -X POST "http://localhost:8000/upload" \
  -F "file=@research_paper.txt" \
  -F "options={\"semantic_model\": \"mini-lm\", \"ai_correction_enabled\": true}"

# Upload PDF with section extraction
curl -X POST "http://localhost:8000/upload" \
  -F "file=@clinical_study.pdf" \
  -F "options={\"semantic_model\": \"mpnet\", \"domain\": \"clinical\"}" \
  -F "extract_sections=true"

# Upload with advanced options
curl -X POST "http://localhost:8000/upload" \
  -F "file=@microbiome_review.docx" \
  -F "options={\"semantic_model\": \"nomic\", \"include_audit_trail\": true, \"umls_mapping_enabled\": true}" \
  -F "language=en"
```

## 📄 GET /files/{file_id}

Retrieve the processing results for an uploaded file.

### **Endpoint**
```http
GET /files/{file_id}
Authorization: Bearer {api_key} (optional)
```

### **Query Parameters**

| **Parameter** | **Type** | **Description** |
|---------------|----------|-----------------|
| `format` | string | Output format (json, csv, sections) |
| `section` | string | Specific section to retrieve (for PDF/DOCX) |
| `include_raw` | boolean | Include extracted raw text |

### **Response**

```json
{
  "success": true,
  "data": {
    "file_id": "file_1234567890abcdef",
    "filename": "research_paper.pdf",
    "status": "completed",
    "processing_time": 245.3,
    "sections": [
      {
        "section_id": "sec_1",
        "title": "Introduction",
        "start_page": 1,
        "end_page": 2,
        "terms": [
          // Terms extracted from this section
        ]
      }
    ],
    "results": {
      "terms": [
        // All terms from the document
      ],
      "metadata": {
        "total_pages": 15,
        "total_sections": 8,
        "text_extracted": true,
        "quality_score": 0.91
      }
    }
  }
}
```

### **Example Usage**

```bash
# Get file results
curl "http://localhost:8000/files/file_1234567890abcdef"

# Get specific section
curl "http://localhost:8000/files/file_1234567890abcdef?section=sec_1&format=sections"

# Download as CSV
curl "http://localhost:8000/files/file_1234567890abcdef?format=csv" \
  -o results.csv
```

## 💡 Examples and Use Cases

### **Use Case 1: Real-time Text Analysis**
```python
import requests

def analyze_text(text):
    response = requests.post(
        "http://localhost:8000/extract/sync",
        json={
            "text": text,
            "options": {
                "semantic_model": "mini-lm",
                "ai_correction_enabled": True
            }
        }
    )

    if response.status_code == 200:
        data = response.json()
        return {
            "terms": data["data"]["terms"],
            "quality_score": data["data"]["metadata"]["quality_score"],
            "processing_time": data["processing_time"]
        }
    else:
        return {"error": response.json()}

# Usage
result = analyze_text("Bacteroides fragilis produces short-chain fatty acids.")
print(f"Found {len(result['terms'])} terms with quality {result['quality_score']}")
```

### **Use Case 2: Batch Processing Research Papers**
```python
import time
import requests

def process_research_papers(papers, callback_url=None):
    # Submit batch job
    response = requests.post(
        "http://localhost:8000/batch",
        json={
            "texts": papers,
            "options": {
                "semantic_model": "mpnet",
                "ai_correction_enabled": True,
                "umls_mapping_enabled": True,
                "domain": "research"
            },
            "callback_url": callback_url,
            "job_name": f"research_batch_{int(time.time())}"
        }
    )

    if response.status_code == 200:
        batch_data = response.json()
        return batch_data["data"]["batch_id"]
    else:
        raise Exception(f"Batch submission failed: {response.text}")

def wait_for_batch_completion(batch_id, max_wait=300):
    start_time = time.time()

    while time.time() - start_time < max_wait:
        # Check each job in the batch
        response = requests.get(f"http://localhost:8000/batches/{batch_id}")

        if response.status_code == 200:
            batch_data = response.json()

            if batch_data["data"]["status"] == "completed":
                return batch_data["data"]["results"]
            elif batch_data["data"]["status"] == "failed":
                raise Exception("Batch processing failed")

        time.sleep(5)

    raise TimeoutError("Batch processing timed out")

# Usage
papers = [
    "The gut microbiome composition varies between healthy individuals...",
    "Metagenomic sequencing reveals microbial diversity patterns...",
    "Antibiotic treatment significantly alters gut microbiota..."
]

batch_id = process_research_papers(papers)
results = wait_for_batch_completion(batch_id)

print(f"Processed {len(results['jobs'])} papers")
print(f"Total terms extracted: {sum(len(job['results']['terms']) for job in results['jobs'])}")
```

### **Use Case 3: File Processing with Callback**
```python
import os

def upload_document_for_processing(file_path, callback_url):
    with open(file_path, 'rb') as f:
        files = {'file': f}
        data = {
            'options': json.dumps({
                "semantic_model": "nomic",
                "ai_correction_enabled": True,
                "include_audit_trail": True,
                "domain": "microbiome"
            }),
            'extract_sections': 'true'
        }

        response = requests.post(
            "http://localhost:8000/upload",
            files=files,
            data=data
        )

        if response.status_code == 200:
            upload_data = response.json()
            print(f"File uploaded: {upload_data['data']['filename']}")
            print(f"Processing job: {upload_data['data']['job_id']}")
            return upload_data['data']['file_id']
        else:
            raise Exception(f"Upload failed: {response.text}")

# Flask callback handler example
@app.route('/callback/extraction-complete', methods=['POST'])
def handle_extraction_callback():
    data = request.json

    if data.get('status') == 'completed':
        # Process completed results
        job_id = data['job_id']
        file_id = data['file_id']

        # Download results
        response = requests.get(f"http://localhost:8000/files/{file_id}")
        results = response.json()

        # Store in database or process further
        store_results(job_id, results)

    return jsonify({"status": "received"})

# Usage
file_id = upload_document_for_processing(
    "clinical_study.pdf",
    "https://your-app.com/callback/extraction-complete"
)
```

---

**Next Steps**: Explore [Health Endpoints](health-endpoints.md) for system monitoring, or check [Configuration API](configuration-api.md) for advanced customization options.