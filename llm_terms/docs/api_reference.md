# API Reference

## Core Classes and Functions

### CDMPipeline

Main orchestrator class for the CDM pipeline with safety enhancements.

```python
class CDMPipeline:
    def __init__(self,
                 safety_config: SafetyConfig = None,
                 content_safety_filter: ContentSafetyFilter = None,
                 audit_logger: AuditLogger = None,
                 enable_all_safety: bool = True):
        """
        Initialize CDM Pipeline with safety enhancements.

        Args:
            safety_config: Safety configuration object
            content_safety_filter: Medical content safety filter
            audit_logger: Comprehensive audit logger
            enable_all_safety: Enable all safety features by default
        """
```

#### Methods

##### `process_document(input_file: str, model: str, output_file: str) -> PipelineResult`

Process a document with comprehensive safety checks.

```python
result = pipeline.process_document(
    input_file="research.pdf",
    model="phi3:mini",
    output_file="results.json"
)
```

##### `extract_entities(text: str, safety_level: str = "research") -> ExtractionResult`

Extract entities from text with safety filtering.

```python
entities = pipeline.extract_entities(
    text="Gut bacteria produce butyrate...",
    safety_level="research"
)
```

### Safety Configuration

#### SafetyLevel Enum

```python
from utils.safety_enhancements import SafetyLevel

class SafetyLevel(Enum):
    RESEARCH = "research"      # Balanced quality/quantity
    CLINICAL = "clinical"      # High safety, strict filtering
    DEVELOPMENT = "development"  # Detailed logging, permissive
```

#### SafetyConfig Class

```python
@dataclass
class SafetyConfig:
    timeout_seconds: int = 300
    max_memory_mb: int = 8192
    max_cpu_percent: float = 80.0
    enable_circuit_breaker: bool = True
    max_retries: int = 3
    safety_level: SafetyLevel = SafetyLevel.RESEARCH
    enable_fallback_results: bool = True
    preserve_min_entities: int = 10
```

### Input Validation

#### InputValidator Class

```python
from utils.input_validator import InputValidator

validator = InputValidator()
result = validator.validate_text_input(
    text="Research text content...",
    strict_mode=True
)

# Check validation result
if result['is_valid']:
    safe_text = result['sanitized_text']
    print(f"✅ Valid: {len(result['warnings'])} warnings")
else:
    print(f"❌ Invalid: {len(result['errors'])} errors")
```

#### Methods

##### `validate_text_input(text: str, strict_mode: bool = True) -> Dict`

Validate and sanitize input text.

**Returns:**
```python
{
    'is_valid': bool,
    'errors': List[str],
    'warnings': List[str],
    'sanitized_text': str,
    'metadata': {
        'validation_timestamp': str,
        'text_length': int,
        'security_score': float
    }
}
```

##### `validate_batch_inputs(texts: List[str]) -> Dict`

Validate multiple text inputs in batch.

### Content Safety

#### ContentSafetyFilter Class

```python
from utils.content_safety import ContentSafetyFilter, SafetyPolicy

# Create safety filter
policy = SafetyPolicy(
    block_treatment_recommendations=True,
    block_personal_health_info=True,
    require_medical_disclaimer=True
)

filter = ContentSafetyFilter(policy)
analysis = filter.analyze_content_safety(text)

# Check if safe to process
if analysis['safe_to_process']:
    filtered_entities = filter.filter_entities_safely(entities, analysis)
```

#### Methods

##### `analyze_content_safety(text: str, context: Dict = None) -> Dict`

Analyze text for safety risks.

**Returns:**
```python
{
    'overall_risk_level': RiskLevel,
    'detected_issues': List[Dict],
    'safe_to_process': bool,
    'has_medical_disclaimer': bool,
    'is_research_content': bool,
    'recommended_actions': List[str]
}
```

### Result Validation

#### CDMResultValidator Class

```python
from utils.result_validator import CDMResultValidator, validate_extraction_results

# Quick validation
validation_result = validate_extraction_results(
    entities=extracted_entities,
    context={'source_file': 'paper.pdf', 'model_used': 'phi3:mini'}
)

print(f"Valid: {validation_result.is_valid}")
print(f"Issues: {len(validation_result.issues)}")
```

#### Methods

##### `validate_results(entities: List[Dict], context: Dict = None) -> ValidationResult`

Validate extraction results comprehensively.

**Returns:**
```python
ValidationResult(
    is_valid: bool,
    total_entities: int,
    valid_entities: int,
    issues: List[ValidationIssue],
    recommendations: List[str],
    summary: Dict[str, Any]
)
```

### Audit Logging

#### AuditLogger Class

```python
from utils.audit_logger import configure_audit_logging, log_pipeline_start

# Configure audit logging
audit_logger = configure_audit_logging(
    log_directory="logs",
    log_level=LogLevel.INFO
)

# Log pipeline events
log_pipeline_start(config, user_id="researcher_123")

# Custom logging
audit_logger.log_extraction_complete(
    entities_extracted=50,
    processing_time=12.5,
    confidence_stats={'mean': 0.85},
    model="phi3:mini"
)
```

#### Methods

##### `log_event(event_type: EventType, message: str, **kwargs)`

Log a structured audit event.

##### `log_extraction_complete(entities_extracted: int, processing_time: float, confidence_stats: Dict, model: str)`

Log extraction completion with metrics.

##### `log_safety_check(safety_analysis: Dict)`

Log safety analysis results.

##### `export_audit_log(output_file: str, start_time: str = None, end_time: str = None) -> bool`

Export audit logs to file.

## Utility Functions

### Configuration Utilities

```python
from utils.safety_enhancements import create_safety_config
from utils.content_safety import create_medical_safety_filter

# Create configurations
research_config = create_safety_config(SafetyLevel.RESEARCH)
clinical_config = create_safety_config(SafetyLevel.CLINICAL)

# Create filters
medical_filter = create_medical_safety_filter()
research_filter = create_research_safety_filter()
```

### Convenience Functions

```python
from utils.result_validator import validate_extraction_results
from utils.audit_logger import log_pipeline_start, log_pipeline_complete

# Quick validation
result = validate_extraction_results(entities, context)

# Quick logging
log_pipeline_start(config)
log_pipeline_complete(total_time, entity_count, results)
```

## Configuration Options

### Command Line Interface

```bash
python main.py [OPTIONS]

Required:
  --input-file TEXT        Input file to process

Optional:
  --model TEXT            LLM model (phi3:mini, qwen3:4b, qwen3:8b)
  --max-entities INTEGER   Maximum entities to extract
  --safety-level TEXT     Safety level (research, clinical, development)
  --enable-all-safety     Enable all safety features
  --verbose               Enable detailed logging

Safety Features:
  --enable-input-validation     Enable input validation and sanitization
  --enable-content-safety       Enable medical content filtering
  --enable-result-validation    Enable result validation
  --enable-audit-logging        Enable comprehensive audit logging
  --strict-medical-filtering    Apply strict medical content filtering
  --require-disclaimer          Require medical disclaimers

Output:
  --output-file TEXT      Output file for results
  --validation-report    Generate validation report
  --safety-report        Generate safety analysis report
  --audit-log-dir TEXT   Directory for audit logs
```

### Environment Variables

```bash
# Safety configuration
CDM_SAFETY_LEVEL=research
CDM_MAX_MEMORY_MB=8192
CDM_TIMEOUT_SECONDS=300

# Logging configuration
CDM_LOG_LEVEL=INFO
CDM_LOG_DIRECTORY=logs
CDM_ENABLE_AUDIT_LOG=true

# Content safety
CDM_BLOCK_TREATMENT_RECOMMENDATIONS=true
CDM_REQUIRE_MEDICAL_DISCLAIMER=true
CDM_PRESERVE_RESEARCH_CONTENT=true
```

### Configuration Files

#### `cdm_config.json`

```json
{
  "safety": {
    "level": "research",
    "timeout_seconds": 300,
    "max_memory_mb": 8192,
    "max_cpu_percent": 80.0,
    "enable_circuit_breaker": true,
    "preserve_min_entities": 10
  },
  "content_safety": {
    "block_treatment_recommendations": true,
    "block_personal_health_info": true,
    "require_medical_disclaimer": true,
    "preserve_research_content": true
  },
  "validation": {
    "enable_result_validation": true,
    "min_confidence_threshold": 0.6,
    "enable_consistency_checks": true
  },
  "logging": {
    "enable_audit_logging": true,
    "log_level": "INFO",
    "log_directory": "logs",
    "enable_data_hashing": true
  }
}
```

## Error Handling

### SafetyError

```python
from utils.safety_enhancements import SafetyError

try:
    result = pipeline.process_document(input_file)
except SafetyError as e:
    print(f"Safety violation: {e}")
    # Handle safety-related errors
except TimeoutError as e:
    print(f"Processing timeout: {e}")
    # Handle timeout errors
except ResourceError as e:
    print(f"Resource limit exceeded: {e}")
    # Handle resource errors
```

### ValidationError

```python
from utils.result_validator import ValidationError

try:
    validation_result = validator.validate_results(entities)
except ValidationError as e:
    print(f"Validation failed: {e}")
    # Handle validation errors
```

## Performance Monitoring

### Metrics Collection

```python
from utils.audit_logger import get_audit_logger

audit_logger = get_audit_logger()

# Log performance metrics
audit_logger.log_performance_metrics(
    metrics={
        'extraction_time': 12.5,
        'validation_time': 2.1,
        'entities_per_second': 8.0,
        'memory_usage_mb': 1024,
        'cpu_usage_percent': 45.2
    },
    stage="extraction"
)
```

### Session Summary

```python
# Get session summary
summary = audit_logger.get_session_summary()

print(f"Session: {summary['session_id']}")
print(f"Events: {summary['total_events']}")
print(f"Entities processed: {summary['total_entities_processed']}")
print(f"Processing time: {summary['total_processing_time']:.2f}s")
```

## Integration Examples

### FastAPI Integration

```python
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from cdm_pipeline.core.pipeline import CDMPipeline
from utils.safety_enhancements import SafetyLevel, create_safety_config

app = FastAPI()

# Initialize pipeline
pipeline = CDMPipeline(
    safety_config=create_safety_config(SafetyLevel.RESEARCH),
    enable_all_safety=True
)

class ExtractionRequest(BaseModel):
    text: str
    safety_level: str = "research"
    model: str = "phi3:mini"

class ExtractionResponse(BaseModel):
    success: bool
    entities: List[Dict]
    safety_analysis: Dict
    validation: Dict
    performance_metrics: Dict

@app.post("/extract", response_model=ExtractionResponse)
async def extract_entities(request: ExtractionRequest):
    try:
        result = await pipeline.extract_entities(
            text=request.text,
            safety_level=request.safety_level
        )

        return ExtractionResponse(
            success=True,
            entities=result.entities,
            safety_analysis=result.safety_analysis,
            validation=result.validation,
            performance_metrics=result.performance_metrics
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

### HPC Integration

```python
#!/usr/bin/env python3
import os
from cdm_pipeline.core.pipeline import CDMPipeline
from utils.safety_enhancements import SafetyLevel, create_safety_config
from utils.audit_logger import configure_audit_logging

def main():
    # HPC configuration
    input_file = os.environ.get('INPUT_FILE')
    output_file = os.environ.get('OUTPUT_FILE')
    safety_level = os.environ.get('SAFETY_LEVEL', 'research')
    job_id = os.environ.get('SLURM_JOB_ID', 'local')

    # Configure safety
    safety_config = create_safety_config(SafetyLevel[safety_level.upper()])
    audit_logger = configure_audit_logging(f"logs/{job_id}")

    # Initialize pipeline
    pipeline = CDMPipeline(
        safety_config=safety_config,
        audit_logger=audit_logger,
        enable_all_safety=True
    )

    # Process with safety
    try:
        result = pipeline.process_document(
            input_file=input_file,
            output_file=output_file
        )

        print(f"✅ Processing complete: {result.total_entities} entities")
        print(f"🛡️ Safety level: {safety_level}")
        print(f"📊 Validation: {result.validation.is_valid}")

    except Exception as e:
        print(f"❌ Processing failed: {e}")
        raise

if __name__ == "__main__":
    main()
```

## Testing

### Unit Testing

```python
import unittest
from utils.input_validator import InputValidator
from utils.content_safety import ContentSafetyFilter

class TestSafetyFeatures(unittest.TestCase):
    def setUp(self):
        self.validator = InputValidator()
        self.safety_filter = ContentSafetyFilter()

    def test_input_validation(self):
        result = self.validator.validate_text_input("Valid text")
        self.assertTrue(result['is_valid'])

    def test_content_safety(self):
        analysis = self.safety_filter.analyze_content_safety("Research text")
        self.assertTrue(analysis['safe_to_process'])

if __name__ == '__main__':
    unittest.main()
```

### Integration Testing

```python
import pytest
from cdm_pipeline.core.pipeline import CDMPipeline
from utils.safety_enhancements import SafetyLevel

def test_pipeline_with_safety():
    pipeline = CDMPipeline(enable_all_safety=True)
    result = pipeline.extract_entities("Test text", SafetyLevel.RESEARCH)

    assert result.entities is not None
    assert result.safety_analysis is not None
    assert result.validation is not None
```

---

This API reference provides comprehensive documentation for all safety-enhanced features of the CDM pipeline.