# 🔧 Configuration API

## 📋 Table of Contents
- [Overview](#overview)
- [Configuration Objects](#configuration-objects)
- [GET /config](#get-config)
- [PUT /config](#put-config)
- [GET /models](#get-models)
- [POST /models](#post-models)
- [Health and Validation](#health-and-validation)
- [Configuration Templates](#configuration-templates)

## 🎯 Overview

The Configuration API provides comprehensive control over pipeline behavior, model selection, deduplication parameters, and safety settings. All configuration changes are validated before applying and can be persisted across sessions.

### **Configuration Categories**
- **Pipeline Settings**: Core extraction behavior and model selection
- **Deduplication**: 4-layer deduplication parameters and thresholds
- **Quality Control**: Minimum term requirements and quality scoring
- **Safety Features**: Medical safety and critical term protection
- **Performance**: Resource optimization and parallelization settings
- **Output**: Format preferences and metadata inclusion

## 🏗️ Configuration Objects

### **PipelineConfig Structure**

```typescript
interface PipelineConfig {
  // Core pipeline settings
  pipeline: {
    models: {
      scispacy_models: string[]           // NER models to use
      semantic_model: "mini-lm" | "nomic" | "mpnet"
      ai_correction: {
        enabled: boolean
        model: string                     // BioMistral model path
        confidence_threshold: number      // 0.0-1.0
      }
      umls_mapping: {
        enabled: boolean
        api_key?: string
        version: string
      }
    }

    // 4-layer deduplication
    deduplication: {
      exact_enabled: boolean
      fuzzy_enabled: boolean
      fuzzy_threshold: number             // 0.0-1.0
      semantic_enabled: boolean
      semantic_threshold: number          // 0.0-1.0
      biomedical_enabled: boolean
      semantic_models: Record<string, string>
      default_semantic_model: string
    }

    // Quality requirements
    quality: {
      minimum_terms_per_file: number
      enable_quantity_safeguard: boolean
      strict_mode: boolean
      quality_threshold: number           // 0.0-1.0
    }

    // Safety settings
    safety: {
      medical_safety_enabled: boolean
      critical_terms_protection: boolean
      audit_trail_enabled: boolean
      phi_detection_enabled: boolean
    }

    // Performance settings
    performance: {
      parallel_processing: boolean
      max_workers: number
      batch_size: number
      gpu_enabled: boolean
      memory_optimization: boolean
    }

    // Output preferences
    output: {
      formats: ("json" | "csv" | "sqlite")[]
      include_ai_corrections: boolean
      include_biomedical_duplicates: boolean
      include_audit_trail: boolean
      output_directory?: string
    }
  }
}
```

### **Configuration Validation Rules**

```typescript
interface ValidationRules {
  // Threshold validation
  fuzzy_threshold: { min: 0.0, max: 1.0, default: 0.85 }
  semantic_threshold: { min: 0.0, max: 1.0, default: 0.90 }
  confidence_threshold: { min: 0.0, max: 1.0, default: 0.80 }
  quality_threshold: { min: 0.0, max: 1.0, default: 0.75 }

  // Resource limits
  max_workers: { min: 1, max: 32, default: 4 }
  batch_size: { min: 1, max: 256, default: 32 }
  minimum_terms_per_file: { min: 1, max: 1000, default: 75 }

  // Model validation
  valid_semantic_models: ["mini-lm", "nomic", "mpnet"]
  valid_scispacy_models: [
    "en_core_sci_lg", "en_ner_craft_md",
    "en_ner_bc5cdr_md", "en_ner_jnlpba_md"
  ]
}
```

## 📖 GET /config

Retrieve the current pipeline configuration with detailed parameter descriptions and validation rules.

### **Endpoint**
```http
GET /config
Authorization: Bearer {api_key} (optional)
```

### **Response**

#### **200 OK - Current Configuration**
```json
{
  "success": true,
  "data": {
    "config": {
      "pipeline": {
        "models": {
          "scispacy_models": [
            "en_core_sci_lg",
            "en_ner_craft_md",
            "en_ner_bc5cdr_md",
            "en_ner_jnlpba_md"
          ],
          "semantic_model": "mini-lm",
          "ai_correction": {
            "enabled": true,
            "model": "BioMistral/BioMistral-7B",
            "confidence_threshold": 0.8
          },
          "umls_mapping": {
            "enabled": false,
            "version": "2023AA"
          }
        },
        "deduplication": {
          "exact_enabled": true,
          "fuzzy_enabled": true,
          "fuzzy_threshold": 0.85,
          "semantic_enabled": true,
          "semantic_threshold": 0.9,
          "biomedical_enabled": true,
          "semantic_models": {
            "mini-lm": "sentence-transformers/all-MiniLM-L12-v2",
            "nomic": "nomic-ai/nomic-embed-text-v1.5",
            "mpnet": "sentence-transformers/all-mpnet-base-v2"
          },
          "default_semantic_model": "mini-lm"
        },
        "quality": {
          "minimum_terms_per_file": 75,
          "enable_quantity_safeguard": true,
          "strict_mode": false,
          "quality_threshold": 0.75
        },
        "safety": {
          "medical_safety_enabled": true,
          "critical_terms_protection": true,
          "audit_trail_enabled": true,
          "phi_detection_enabled": true
        },
        "performance": {
          "parallel_processing": true,
          "max_workers": 4,
          "batch_size": 32,
          "gpu_enabled": true,
          "memory_optimization": true
        },
        "output": {
          "formats": ["json", "csv", "sqlite"],
          "include_ai_corrections": true,
          "include_biomedical_duplicates": true,
          "include_audit_trail": true
        }
      }
    },
    "metadata": {
      "version": "1.0.0",
      "last_modified": "2024-01-15T10:30:00Z",
      "validation_applied": true,
      "environment": "production"
    }
  },
  "message": "Configuration retrieved successfully",
  "timestamp": "2024-01-15T10:30:00Z"
}
```

### **Example Usage**

```bash
# Get current configuration
curl -H "Authorization: Bearer YOUR_API_KEY" \
     "http://localhost:8000/config"

# With jq for pretty printing
curl "http://localhost:8000/config" | jq '.data.config'
```

```python
import requests

def get_configuration(api_key=None):
    """Get current pipeline configuration"""
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    response = requests.get("http://localhost:8000/config", headers=headers)

    if response.status_code == 200:
        data = response.json()
        return data["data"]["config"]
    else:
        raise Exception(f"Failed to get config: {response.text}")

config = get_configuration()
print(f"Semantic model: {config['pipeline']['models']['semantic_model']}")
print(f"Minimum terms: {config['pipeline']['quality']['minimum_terms_per_file']}")
```

## ✏️ PUT /config

Update the pipeline configuration with comprehensive validation and rollback capabilities.

### **Endpoint**
```http
PUT /config
Content-Type: application/json
Authorization: Bearer {api_key} (required for configuration changes)
```

### **Request Body**

Provide a partial or complete configuration object. Only specified fields will be updated.

```json
{
  "pipeline": {
    "models": {
      "semantic_model": "mpnet",
      "ai_correction": {
        "confidence_threshold": 0.85
      },
      "umls_mapping": {
        "enabled": true,
        "api_key": "your_umls_api_key_here"
      }
    },
    "deduplication": {
      "fuzzy_threshold": 0.90,
      "semantic_threshold": 0.85
    },
    "quality": {
      "minimum_terms_per_file": 100,
      "strict_mode": true
    },
    "performance": {
      "max_workers": 8,
      "batch_size": 64
    }
  },
  "options": {
    "validate_only": false,              // Validate without applying
    "backup_current": true,              // Create backup before changes
    "restart_pipeline": false,           // Restart after changes
    "validate_models": true              // Check model availability
  }
}
```

### **Request Parameters**

| **Parameter** | **Type** | **Required** | **Description** |
|---------------|----------|--------------|-----------------|
| `pipeline` | object | ✅ | Pipeline configuration updates |
| `options.validate_only` | boolean | ❌ | Validate changes without applying |
| `options.backup_current` | boolean | ❌ | Create backup of current config |
| `options.restart_pipeline` | boolean | ❌ | Restart pipeline after changes |
| `options.validate_models` | boolean | ❌ | Check model availability |

### **Response**

#### **200 OK - Configuration Updated**
```json
{
  "success": true,
  "data": {
    "config": {
      // Updated full configuration
    },
    "changes_applied": [
      "pipeline.models.semantic_model: mini-lm → mpnet",
      "pipeline.models.ai_correction.confidence_threshold: 0.80 → 0.85",
      "pipeline.deduplication.fuzzy_threshold: 0.85 → 0.90",
      "pipeline.quality.minimum_terms_per_file: 75 → 100"
    ],
    "validation": {
      "passed": true,
      "warnings": [
        "Higher max_workers may increase memory usage",
        "mpnet model requires more storage than mini-lm"
      ],
      "errors": []
    },
    "backup_created": {
      "backup_id": "backup_1642248600",
      "timestamp": "2024-01-15T10:30:00Z"
    }
  },
  "message": "Configuration updated successfully",
  "timestamp": "2024-01-15T10:30:00Z"
}
```

#### **400 Bad Request - Validation Errors**
```json
{
  "success": false,
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Configuration validation failed",
    "details": {
      "field_errors": [
        {
          "field": "pipeline.deduplication.fuzzy_threshold",
          "value": 1.5,
          "error": "Value must be between 0.0 and 1.0"
        },
        {
          "field": "pipeline.models.semantic_model",
          "value": "invalid_model",
          "error": "Model must be one of: mini-lm, nomic, mpnet"
        }
      ],
      "general_errors": [
        "Cannot enable medical_safety without audit_trail_enabled"
      ]
    }
  }
}
```

### **Example Usage**

```bash
# Update semantic model and thresholds
curl -X PUT "http://localhost:8000/config" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "pipeline": {
      "models": {
        "semantic_model": "mpnet"
      },
      "deduplication": {
        "fuzzy_threshold": 0.90
      }
    },
    "options": {
      "validate_models": true,
      "backup_current": true
    }
  }'

# Validate changes without applying
curl -X PUT "http://localhost:8000/config" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "pipeline": {
      "performance": {
        "max_workers": 16
      }
    },
    "options": {
      "validate_only": true
    }
  }'
```

```python
import requests

def update_configuration(config_updates, api_key, validate_only=False):
    """Update pipeline configuration"""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    payload = {
        "pipeline": config_updates,
        "options": {
            "validate_only": validate_only,
            "backup_current": True,
            "validate_models": True
        }
    }

    response = requests.put("http://localhost:8000/config",
                           json=payload, headers=headers)

    if response.status_code == 200:
        data = response.json()
        if validate_only:
            return data["data"]["validation"]
        else:
            return data["data"]["changes_applied"]
    else:
        error_data = response.json()
        raise Exception(f"Config update failed: {error_data['error']['message']}")

# Example: Enable UMLS mapping
config_updates = {
    "models": {
        "umls_mapping": {
            "enabled": True,
            "api_key": "your_umls_key"
        }
    }
}

try:
    changes = update_configuration(config_updates, "YOUR_API_KEY")
    print(f"Configuration updated: {changes}")
except Exception as e:
    print(f"Update failed: {e}")
```

## 🤖 GET /models

Retrieve information about available NLP models, their status, and resource requirements.

### **Endpoint**
```http
GET /models
Authorization: Bearer {api_key} (optional)
```

### **Query Parameters**

| **Parameter** | **Type** | Description** |
|---------------|----------|-----------------|
| `type` | string | Filter by model type (scispacy, semantic, ai_correction) |
| `status` | string | Filter by status (available, loaded, disabled) |
| `detailed` | boolean | Include detailed resource information |

### **Response**

#### **200 OK - Models Information**
```json
{
  "success": true,
  "data": {
    "models": {
      "scispacy": [
        {
          "model_id": "en_core_sci_lg",
          "name": "SciSpaCy Large Scientific Model",
          "type": "scientific_ner",
          "status": "loaded",
          "version": "0.5.1",
          "size_mb": 657,
          "entities_supported": [
            "CHEMICAL", "ORGANISM", "DISEASE", "CELL_LINE"
          ],
          "performance": {
            "accuracy": 0.92,
            "speed": "medium",
            "memory_mb": 800
          },
          "last_used": "2024-01-15T09:45:00Z"
        },
        {
          "model_id": "en_ner_bc5cdr_md",
          "name": "BC5CDR Disease/Chemical NER",
          "type": "biomedical_ner",
          "status": "loaded",
          "version": "0.5.1",
          "size_mb": 342,
          "entities_supported": ["DISEASE", "CHEMICAL"],
          "performance": {
            "accuracy": 0.89,
            "speed": "fast",
            "memory_mb": 500
          }
        }
      ],
      "semantic": [
        {
          "model_id": "mini-lm",
          "name": "MiniLM-L12-v2",
          "type": "semantic_embedding",
          "status": "loaded",
          "size_mb": 440,
          "dimensions": 384,
          "performance": {
            "similarity_quality": 0.85,
            "speed": "fast",
            "memory_mb": 600
          },
          "huggingface_path": "sentence-transformers/all-MiniLM-L12-v2"
        },
        {
          "model_id": "mpnet",
          "name": "MPNet Base v2",
          "type": "semantic_embedding",
          "status": "available",
          "size_mb": 1100,
          "dimensions": 768,
          "performance": {
            "similarity_quality": 0.92,
            "speed": "medium",
            "memory_mb": 1200
          },
          "huggingface_path": "sentence-transformers/all-mpnet-base-v2"
        }
      ],
      "ai_correction": [
        {
          "model_id": "biomistral-7b",
          "name": "BioMistral-7B",
          "type": "biomedical_llm",
          "status": "loaded",
          "size_gb": 14,
          "performance": {
            "accuracy": 0.94,
            "speed": "slow",
            "memory_gb": 16,
            "gpu_required": true
          },
          "huggingface_path": "BioMistral/BioMistral-7B",
          "last_used": "2024-01-15T10:15:00Z"
        }
      ]
    },
    "summary": {
      "total_models": 8,
      "loaded_models": 6,
      "available_models": 2,
      "total_memory_mb": 2800,
      "gpu_enabled": true
    }
  },
  "message": "Models information retrieved successfully",
  "timestamp": "2024-01-15T10:30:00Z"
}
```

### **Example Usage**

```bash
# Get all models
curl "http://localhost:8000/models"

# Get only scispacy models
curl "http://localhost:8000/models?type=scispacy"

# Get detailed information
curl "http://localhost:8000/models?detailed=true"

# Get only loaded models
curl "http://localhost:8000/models?status=loaded"
```

```python
def get_models_info(model_type=None, status=None, detailed=False):
    """Get information about available models"""
    params = {}
    if model_type:
        params["type"] = model_type
    if status:
        params["status"] = status
    if detailed:
        params["detailed"] = "true"

    response = requests.get("http://localhost:8000/models", params=params)

    if response.status_code == 200:
        data = response.json()
        return data["data"]["models"]
    else:
        raise Exception(f"Failed to get models info: {response.text}")

# Get loaded semantic models
semantic_models = get_models_info(model_type="semantic", status="loaded")
for model in semantic_models:
    print(f"{model['name']}: {model['performance']['similarity_quality']}")
```

## 📥 POST /models

Load, download, or configure new models for the pipeline.

### **Endpoint**
```http
POST /models
Content-Type: application/json
Authorization: Bearer {api_key} (required)
```

### **Request Body**

```json
{
  "action": "load",                    // load, unload, download, configure
  "model_id": "mpnet",                 // target model
  "model_type": "semantic",            // scispacy, semantic, ai_correction
  "parameters": {
    "force_download": false,
    "cache_dir": "/custom/cache/path",
    "device": "cpu" | "cuda",
    "batch_size": 32
  },
  "validation": {
    "test_model": true,
    "validate_performance": true,
    "timeout_seconds": 300
  }
}
```

### **Available Actions**

| **Action** | **Description** | **Model Types** |
|------------|-----------------|-----------------|
| `load` | Load model into memory | All types |
| `unload` | Unload model from memory | All types |
| `download` | Download model if not available | semantic, ai_correction |
| `configure` | Update model configuration | All types |

### **Response**

#### **200 OK - Model Operation Successful**
```json
{
  "success": true,
  "data": {
    "model_id": "mpnet",
    "action": "load",
    "status": "completed",
    "result": {
      "loaded": true,
      "memory_used_mb": 1200,
      "load_time_seconds": 12.5,
      "validation": {
        "passed": true,
        "test_score": 0.92
      }
    },
    "model_info": {
      "name": "MPNet Base v2",
      "type": "semantic_embedding",
      "dimensions": 768,
      "huggingface_path": "sentence-transformers/all-mpnet-base-v2"
    }
  },
  "message": "Model loaded successfully",
  "timestamp": "2024-01-15T10:30:00Z"
}
```

### **Example Usage**

```bash
# Load MPNet semantic model
curl -X POST "http://localhost:8000/models" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "action": "load",
    "model_id": "mpnet",
    "model_type": "semantic",
    "parameters": {
      "device": "cuda"
    },
    "validation": {
      "test_model": true
    }
  }'

# Unload a model to free memory
curl -X POST "http://localhost:8000/models" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "action": "unload",
    "model_id": "en_ner_jnlpba_md",
    "model_type": "scispacy"
  }'

# Download and configure new model
curl -X POST "http://localhost:8000/models" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "action": "download",
    "model_id": "biobert-v1.1",
    "model_type": "scispacy",
    "parameters": {
      "force_download": false
    }
  }'
```

## 🔍 Health and Validation

### **Configuration Health Check**

```bash
# Check if current configuration is valid
curl "http://localhost:8000/config/validate"
```

```json
{
  "success": true,
  "data": {
    "valid": true,
    "validation_results": [
      {
        "category": "models",
        "status": "passed",
        "message": "All specified models are available"
      },
      {
        "category": "thresholds",
        "status": "passed",
        "message": "All threshold values within valid ranges"
      },
      {
        "category": "performance",
        "status": "warning",
        "message": "High max_workers may impact memory usage"
      }
    ]
  }
}
```

### **Model Compatibility Check**

```bash
# Check model compatibility
curl "http://localhost:8000/models/compatible?semantic=mpnet&scispacy=en_core_sci_lg"
```

```json
{
  "success": true,
  "data": {
    "compatible": true,
    "compatibility_score": 0.95,
    "recommendations": [
      "MPNet provides higher quality but uses more memory",
      "Consider increasing batch_size for better performance"
    ],
    "resource_estimate": {
      "memory_mb": 2000,
      "storage_mb": 1600,
      "gpu_recommended": true
    }
  }
}
```

## 📋 Configuration Templates

### **Production Template**
```bash
curl -X POST "http://localhost:8000/config/template" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "template": "production",
    "domain": "medical",
    "throughput": "high"
  }'
```

### **Development Template**
```bash
curl -X POST "http://localhost:8000/config/template" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "template": "development",
    "debug": true
  }'
```

### **Research Template**
```bash
curl -X POST "http://localhost:8000/config/template" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "template": "research",
    "max_terms": true,
    "include_all_extractions": true
  }'
```

---

**Next Steps**: Explore [Deployment](../deployment/docker.md) for production setup, or check [Examples & Tutorials](../examples/basic-usage.md) for practical usage patterns.