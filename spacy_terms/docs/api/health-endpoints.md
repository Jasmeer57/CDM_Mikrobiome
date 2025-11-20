# 🏥 Health Endpoints

## 📋 Table of Contents
- [Overview](#overview)
- [GET /health](#get-health)
- [GET /health/detailed](#get-healthdetailed)
- [GET /health/models](#get-healthmodels)
- [GET /health/system](#get-healthsystem)
- [GET /health/queue](#get-healthqueue)
- [GET /metrics](#get-metrics)
- [Health Monitoring Best Practices](#health-monitoring-best-practices)
- [Alerting and Automation](#alerting-and-automation)

## 🎯 Overview

The health endpoints provide comprehensive monitoring and diagnostic information about the pipeline's operational status, model availability, system resources, and processing queue health. These endpoints are essential for production monitoring, automated health checks, and system maintenance.

### **Health Monitoring Categories**

| **Category** | **Endpoints** | **Monitored Components** |
|--------------|---------------|--------------------------|
| **Basic Health** | `/health` | Overall system status |
| **Detailed Health** | `/health/detailed` | Component-level status |
| **Model Health** | `/health/models` | NLP model availability |
| **System Health** | `/health/system` | CPU, memory, disk resources |
| **Queue Health** | `/health/queue` | Job processing queue status |
| **Metrics** | `/metrics` | Performance and usage metrics |

### **Response Status Codes**

| **Status** | **Meaning** | **HTTP Code** | **Description** |
|------------|-------------|---------------|-------------|
| `healthy` | All systems operational | 200 | Everything working normally |
| `degraded` | Some components have issues | 200 | System functional but with warnings |
| `unhealthy` | Critical issues present | 503 | System not fully operational |
| `maintenance` | Undergoing maintenance | 503 | System temporarily unavailable |

## ✅ GET /health

Basic health check providing overall system status. Ideal for load balancers and simple monitoring.

### **Endpoint**
```http
GET /health
```

### **Response**

#### **200 OK - System Healthy**
```json
{
  "status": "healthy",
  "timestamp": "2024-01-15T10:30:00Z",
  "uptime": 86400,
  "version": "2.0.0",
  "environment": "production",
  "checks": {
    "database": "healthy",
    "models": "healthy",
    "queue": "healthy",
    "storage": "healthy"
  }
}
```

#### **200 OK - System Degraded**
```json
{
  "status": "degraded",
  "timestamp": "2024-01-15T10:30:00Z",
  "uptime": 86400,
  "version": "2.0.0",
  "environment": "production",
  "checks": {
    "database": "healthy",
    "models": "degraded",
    "queue": "healthy",
    "storage": "healthy"
  },
  "warnings": [
    "AI correction model experiencing high memory usage"
  ]
}
```

#### **503 Service Unavailable - System Unhealthy**
```json
{
  "status": "unhealthy",
  "timestamp": "2024-01-15T10:30:00Z",
  "uptime": 86400,
  "version": "2.0.0",
  "environment": "production",
  "checks": {
    "database": "healthy",
    "models": "unhealthy",
    "queue": "healthy",
    "storage": "healthy"
  },
  "errors": [
    "Failed to load spaCy model: en_core_sci_lg",
    "GPU memory insufficient for semantic model"
  ]
}
```

### **Usage Examples**

```bash
# Basic health check
curl http://localhost:8000/health

# Check health with authentication
curl -H "Authorization: Bearer YOUR_API_KEY" \
     http://localhost:8000/health

# Health check for load balancer (expect 200 for healthy)
curl -f http://localhost:8000/health || exit 1
```

## 🔍 GET /health/detailed

Comprehensive health check with detailed component status and diagnostic information.

### **Endpoint**
```http
GET /health/detailed
Authorization: Bearer {api_key} (optional for production)
```

### **Query Parameters**

| **Parameter** | **Type** | **Description** |
|---------------|----------|-----------------|
| `include_models` | boolean | Include detailed model information |
| `include_metrics` | boolean | Include performance metrics |
| `check_endpoints` | boolean | Perform endpoint connectivity checks |

### **Response**

```json
{
  "status": "healthy",
  "timestamp": "2024-01-15T10:30:00Z",
  "uptime": 86400,
  "version": "2.0.0",
  "environment": "production",
  "git_commit": "abc123def456",
  "build_timestamp": "2024-01-14T15:30:00Z",

  "components": {
    "api": {
      "status": "healthy",
      "response_time_ms": 12,
      "endpoints_accessible": 15,
      "total_endpoints": 15
    },

    "database": {
      "status": "healthy",
      "connection_pool": {
        "active": 5,
        "idle": 15,
        "total": 20,
        "usage_percent": 25
      },
      "last_query_time_ms": 3,
      "storage_size_mb": 1250
    },

    "models": {
      "status": "healthy",
      "loaded_models": 4,
      "total_models": 4,
      "memory_usage_mb": 2048,
      "gpu_memory_usage_mb": 4096,
      "model_load_times_ms": {
        "en_core_sci_lg": 1250,
        "en_ner_craft_md": 980,
        "en_ner_bc5cdr_md": 1100,
        "en_ner_jnlpba_md": 850
      }
    },

    "queue": {
      "status": "healthy",
      "active_jobs": 3,
      "queued_jobs": 12,
      "completed_jobs_today": 1450,
      "failed_jobs_today": 2,
      "average_processing_time_seconds": 45,
      "worker_status": {
        "active": 4,
        "idle": 2,
        "total": 6
      }
    },

    "storage": {
      "status": "healthy",
      "disk_usage_percent": 65,
      "available_space_gb": 350,
      "total_space_gb": 1000,
      "io_operations_per_second": 150
    },

    "external_services": {
      "umls_api": {
        "status": "healthy",
        "response_time_ms": 450,
        "last_successful_call": "2024-01-15T10:29:30Z"
      },
      "huggingface_cache": {
        "status": "healthy",
        "cache_size_gb": 8.5,
        "cache_hit_rate": 0.85
      }
    }
  },

  "performance_metrics": {
    "requests_per_minute": 120,
    "average_response_time_ms": 250,
    "error_rate_percent": 0.2,
    "cpu_usage_percent": 45,
    "memory_usage_percent": 68
  },

  "recent_errors": [
    {
      "timestamp": "2024-01-15T10:25:00Z",
      "component": "queue",
      "error": "Job timeout after 300 seconds",
      "job_id": "job_1234567890abcdef",
      "resolved": true
    }
  ]
}
```

### **Usage Examples**

```bash
# Get detailed health information
curl -H "Authorization: Bearer YOUR_API_KEY" \
     "http://localhost:8000/health/detailed"

# Include additional diagnostic information
curl -H "Authorization: Bearer YOUR_API_KEY" \
     "http://localhost:8000/health/detailed?include_models=true&include_metrics=true"

# Check specific component health
curl "http://localhost:8000/health/detailed" | jq '.components.models.status'
```

## 🤖 GET /health/models

Detailed status of NLP models and their availability.

### **Endpoint**
```http
GET /health/models
```

### **Response**

```json
{
  "status": "healthy",
  "timestamp": "2024-01-15T10:30:00Z",

  "scispacy_models": [
    {
      "name": "en_core_sci_lg",
      "status": "loaded",
      "version": "3.5.0",
      "load_time_ms": 1250,
      "memory_usage_mb": 512,
      "last_used": "2024-01-15T10:29:45Z",
      "test_result": "passed",
      "test_text": "Bacteroides fragilis",
      "entities_detected": 2
    },
    {
      "name": "en_ner_craft_md",
      "status": "loaded",
      "version": "3.5.0",
      "load_time_ms": 980,
      "memory_usage_mb": 256,
      "last_used": "2024-01-15T10:29:30Z",
      "test_result": "passed",
      "test_text": "Protein kinase activity",
      "entities_detected": 1
    },
    {
      "name": "en_ner_bc5cdr_md",
      "status": "loaded",
      "version": "3.5.0",
      "load_time_ms": 1100,
      "memory_usage_mb": 384,
      "last_used": "2024-01-15T10:29:15Z",
      "test_result": "passed",
      "test_text": "Type 2 diabetes mellitus",
      "entities_detected": 2
    },
    {
      "name": "en_ner_jnlpba_md",
      "status": "loaded",
      "version": "3.5.0",
      "load_time_ms": 850,
      "memory_usage_mb": 256,
      "last_used": "2024-01-15T10:29:00Z",
      "test_result": "passed",
      "test_text": "Cell line proliferation",
      "entities_detected": 1
    }
  ],

  "semantic_models": [
    {
      "name": "sentence-transformers/all-MiniLM-L12-v2",
      "status": "loaded",
      "type": "semantic",
      "memory_usage_mb": 512,
      "gpu_memory_usage_mb": 1024,
      "embedding_dimension": 384,
      "test_similarity": 0.85,
      "last_used": "2024-01-15T10:28:45Z"
    }
  ],

  "ai_models": [
    {
      "name": "BioMistral/BioMistral-7B",
      "status": "loaded",
      "type": "correction",
      "memory_usage_mb": 6656,
      "gpu_memory_usage_mb": 7168,
      "parameters": "7B",
      "quantization": "4bit",
      "test_correction": "passed",
      "last_used": "2024-01-15T10:28:00Z"
    }
  ],

  "model_health_summary": {
    "total_models": 6,
    "loaded_models": 6,
    "failed_models": 0,
    "total_memory_usage_mb": 8704,
    "total_gpu_memory_usage_mb": 8192,
    "last_health_check": "2024-01-15T10:30:00Z"
  },

  "model_cache": {
    "cache_directory": "/app/cache/models",
    "cache_size_gb": 2.5,
    "cache_hit_rate": 0.92,
    "last_cleanup": "2024-01-15T02:00:00Z"
  }
}
```

### **Usage Examples**

```bash
# Check model status
curl http://localhost:8000/health/models

# Check specific model
curl http://localhost:8000/health/models | jq '.scispacy_models[] | select(.name=="en_core_sci_lg")'

# Monitor model memory usage
curl http://localhost:8000/health/models | jq '.model_health_summary.total_memory_usage_mb'
```

## 💻 GET /health/system

System resource monitoring including CPU, memory, disk, and network status.

### **Endpoint**
```http
GET /health/system
Authorization: Bearer {api_key} (required for production)
```

### **Response**

```json
{
  "status": "healthy",
  "timestamp": "2024-01-15T10:30:00Z",

  "cpu": {
    "usage_percent": 45,
    "core_count": 8,
    "load_average": [2.1, 2.3, 2.0],
    "processes_running": 156,
    "temperature_celsius": 65,
    "frequency_mhz": 2400
  },

  "memory": {
    "total_gb": 32,
    "available_gb": 10.2,
    "used_gb": 21.8,
    "usage_percent": 68,
    "swap_total_gb": 8,
    "swap_used_gb": 0.5,
    "swap_usage_percent": 6,
    "cached_gb": 4.2,
    "buffers_gb": 1.1
  },

  "disk": {
    "total_gb": 1000,
    "available_gb": 350,
    "used_gb": 650,
    "usage_percent": 65,
    "io_operations_per_second": 150,
    "read_throughput_mbps": 125,
    "write_throughput_mbps": 85,
    "mount_points": [
      {
        "path": "/",
        "total_gb": 1000,
        "available_gb": 350,
        "usage_percent": 65
      },
      {
        "path": "/tmp",
        "total_gb": 50,
        "available_gb": 35,
        "usage_percent": 30
      }
    ]
  },

  "gpu": {
    "available": true,
    "driver_version": "515.65.01",
    "cuda_version": "11.7",
    "gpus": [
      {
        "id": 0,
        "name": "NVIDIA RTX 4090",
        "memory_total_gb": 24,
        "memory_used_gb": 8.2,
        "memory_usage_percent": 34,
        "utilization_percent": 25,
        "temperature_celsius": 58,
        "power_usage_watts": 225
      }
    ]
  },

  "network": {
    "interfaces": [
      {
        "name": "eth0",
        "status": "up",
        "bytes_sent_mb": 1024,
        "bytes_received_mb": 2048,
        "packets_sent": 50000,
        "packets_received": 75000,
        "errors_in": 0,
        "errors_out": 0
      }
    ],
    "connections_active": 45,
    "bandwidth_mbps": 1000
  },

  "system_health": {
    "uptime_seconds": 86400,
    "boot_time": "2024-01-14T10:30:00Z",
    "process_count": 156,
    "load_average_1min": 2.1,
    "load_average_5min": 2.3,
    "load_average_15min": 2.0
  },

  "alerts": [
    {
      "level": "warning",
      "component": "disk",
      "message": "Disk usage approaching 70% threshold",
      "value": 65,
      "threshold": 70
    }
  ]
}
```

### **Usage Examples**

```bash
# Monitor system resources
curl -H "Authorization: Bearer YOUR_API_KEY" \
     http://localhost:8000/health/system

# Check memory usage
curl -H "Authorization: Bearer YOUR_API_KEY" \
     http://localhost:8000/health/system | jq '.memory.usage_percent'

# Monitor GPU status
curl -H "Authorization: Bearer YOUR_API_KEY" \
     http://localhost:8000/health/system | jq '.gpu.gpus[]'
```

## 📋 GET /health/queue

Job processing queue health and statistics.

### **Endpoint**
```http
GET /health/queue
Authorization: Bearer {api_key} (optional)
```

### **Response**

```json
{
  "status": "healthy",
  "timestamp": "2024-01-15T10:30:00Z",

  "queue_status": {
    "active_jobs": 3,
    "queued_jobs": 12,
    "failed_jobs": 2,
    "completed_jobs_today": 1450,
    "total_jobs_today": 1454,
    "success_rate_percent": 99.7
  },

  "workers": {
    "total": 6,
    "active": 4,
    "idle": 2,
    "max_workers": 8,
    "worker_utilization_percent": 50
  },

  "processing_times": {
    "average_seconds": 45,
    "median_seconds": 32,
    "p95_seconds": 120,
    "p99_seconds": 180,
    "longest_job_today_seconds": 245
  },

  "job_types": {
    "text_extraction": {
      "active": 2,
      "queued": 8,
      "completed_today": 1200,
      "average_time_seconds": 35
    },
    "file_processing": {
      "active": 1,
      "queued": 4,
      "completed_today": 250,
      "average_time_seconds": 125
    }
  },

  "queue_performance": {
    "throughput_per_hour": 85,
    "peak_throughput_per_hour": 120,
    "average_wait_time_seconds": 15,
    "max_wait_time_today_seconds": 180
  },

  "recent_jobs": [
    {
      "job_id": "job_1234567890abcde1",
      "type": "text_extraction",
      "status": "completed",
      "processing_time_seconds": 42,
      "created_at": "2024-01-15T10:28:00Z",
      "completed_at": "2024-01-15T10:28:42Z"
    },
    {
      "job_id": "job_1234567890abcde2",
      "type": "file_processing",
      "status": "failed",
      "error": "GPU memory insufficient",
      "created_at": "2024-01-15T10:25:00Z",
      "failed_at": "2024-01-15T10:26:30Z"
    }
  ],

  "queue_health_metrics": {
    "queue_length_trend": "stable",
    "processing_delay_trend": "decreasing",
    "error_rate_trend": "stable",
    "worker_efficiency_percent": 85
  }
}
```

### **Usage Examples**

```bash
# Check queue status
curl http://localhost:8000/health/queue

# Monitor queue length
curl http://localhost:8000/health/queue | jq '.queue_status.queued_jobs'

# Check worker utilization
curl http://localhost:8000/health/queue | jq '.workers.worker_utilization_percent'
```

## 📊 GET /metrics

Prometheus-compatible metrics for monitoring and alerting.

### **Endpoint**
```http
GET /metrics
```

### **Response (Prometheus Format)**

```text
# HELP api_requests_total Total number of API requests
# TYPE api_requests_total counter
api_requests_total{method="GET",endpoint="/health",status="200"} 1245
api_requests_total{method="POST",endpoint="/extract",status="200"} 856
api_requests_total{method="POST",endpoint="/extract",status="400"} 12

# HELP api_request_duration_seconds API request duration
# TYPE api_request_duration_seconds histogram
api_request_duration_seconds_bucket{le="0.1"} 850
api_request_duration_seconds_bucket{le="0.5"} 1200
api_request_duration_seconds_bucket{le="1.0"} 1450
api_request_duration_seconds_bucket{le="5.0"} 1580
api_request_duration_seconds_bucket{le="+Inf"} 1600

# HELP pipeline_processing_jobs_total Total pipeline processing jobs
# TYPE pipeline_processing_jobs_total counter
pipeline_processing_jobs_total{status="completed"} 15420
pipeline_processing_jobs_total{status="failed"} 23
pipeline_processing_jobs_total{status="cancelled"} 5

# HELP pipeline_processing_duration_seconds Pipeline processing duration
# TYPE pipeline_processing_duration_seconds histogram
pipeline_processing_duration_seconds_bucket{le="10"} 1200
pipeline_processing_duration_seconds_bucket{le="30"} 3400
pipeline_processing_duration_seconds_bucket{le="60"} 4800
pipeline_processing_duration_seconds_bucket{le="120"} 5200
pipeline_processing_duration_seconds_bucket{le="300"} 5380
pipeline_processing_duration_seconds_bucket{le="+Inf"} 5400

# HELP model_memory_usage_bytes Model memory usage in bytes
# TYPE model_memory_usage_bytes gauge
model_memory_usage_bytes{model="en_core_sci_lg"} 536870912
model_memory_usage_bytes{model="sentence_transformers"} 536870912
model_memory_usage_bytes{model="biomistral"} 6983518105

# HELP gpu_memory_usage_bytes GPU memory usage in bytes
# TYPE gpu_memory_usage_bytes gauge
gpu_memory_usage_bytes{gpu_id="0"} 8589934592

# HELP cpu_usage_percent CPU usage percentage
# TYPE cpu_usage_percent gauge
cpu_usage_percent 45

# HELP memory_usage_percent Memory usage percentage
# TYPE memory_usage_percent gauge
memory_usage_percent 68

# HELP disk_usage_percent Disk usage percentage
# TYPE disk_usage_percent gauge
disk_usage_percent{mount="/"} 65

# HELP queue_length Current queue length
# TYPE queue_length gauge
queue_length{queue="processing"} 3
queue_length{queue="pending"} 12

# HELP active_workers Number of active workers
# TYPE active_workers gauge
active_workers 4

# HELP extracted_terms_total Total number of terms extracted
# TYPE extracted_terms_total counter
extracted_terms_total 124567

# HELP terms_quality_score Average quality score of extracted terms
# TYPE terms_quality_score gauge
terms_quality_score 0.92
```

### **Usage Examples**

```bash
# Get Prometheus metrics
curl http://localhost:8000/metrics

# Filter specific metrics
curl http://localhost:8000/metrics | grep "api_requests_total"

# Monitor GPU memory usage
curl http://localhost:8000/metrics | grep "gpu_memory_usage"
```

## 🚨 Health Monitoring Best Practices

### **1. Load Balancer Health Checks**

Configure your load balancer to use the basic health endpoint:

```nginx
upstream pipeline_api {
    server 10.0.1.10:8000;
    server 10.0.1.11:8000;
    server 10.0.1.12:8000;
}

server {
    location / {
        proxy_pass http://pipeline_api;

        # Health check configuration
        health_check interval=30 fails=3 passes=2;
        health_check_uri /health;
    }
}
```

### **2. Kubernetes Health Probes**

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: pipeline-api
spec:
  containers:
  - name: api
    image: your-registry/pipeline-api:latest
    ports:
    - containerPort: 8000
    livenessProbe:
      httpGet:
        path: /health
        port: 8000
      initialDelaySeconds: 30
      periodSeconds: 10
    readinessProbe:
      httpGet:
        path: /health
        port: 8000
      initialDelaySeconds: 5
      periodSeconds: 5
```

### **3. Monitoring Dashboard Script**

```python
import requests
import time
from datetime import datetime

def monitor_system_health():
    """Comprehensive health monitoring script"""

    base_url = "http://localhost:8000"

    try:
        # Basic health check
        health_response = requests.get(f"{base_url}/health", timeout=5)
        basic_health = health_response.json()

        # Detailed health check
        detailed_response = requests.get(f"{base_url}/health/detailed", timeout=10)
        detailed_health = detailed_response.json()

        # System resources
        system_response = requests.get(f"{base_url}/health/system", timeout=5)
        system_health = system_response.json()

        # Queue status
        queue_response = requests.get(f"{base_url}/health/queue", timeout=5)
        queue_health = queue_response.json()

        # Compile health report
        report = {
            "timestamp": datetime.now().isoformat(),
            "overall_status": basic_health["status"],
            "uptime": basic_health["uptime"],
            "components": basic_health["checks"],
            "cpu_usage": system_health["cpu"]["usage_percent"],
            "memory_usage": system_health["memory"]["usage_percent"],
            "disk_usage": system_health["disk"]["usage_percent"],
            "queue_length": queue_health["queue_status"]["queued_jobs"],
            "active_jobs": queue_health["queue_status"]["active_jobs"],
            "processing_rate": queue_health["queue_performance"]["throughput_per_hour"],
            "success_rate": queue_health["queue_status"]["success_rate_percent"]
        }

        # Determine if alerts should be triggered
        alerts = []

        if report["cpu_usage"] > 80:
            alerts.append("High CPU usage detected")

        if report["memory_usage"] > 85:
            alerts.append("High memory usage detected")

        if report["disk_usage"] > 80:
            alerts.append("High disk usage detected")

        if report["queue_length"] > 50:
            alerts.append("High queue length detected")

        if report["success_rate"] < 95:
            alerts.append("Low success rate detected")

        report["alerts"] = alerts

        return report

    except requests.RequestException as e:
        return {
            "timestamp": datetime.now().isoformat(),
            "status": "error",
            "error": str(e),
            "alerts": ["Health check failed"]
        }

def main():
    """Main monitoring loop"""

    while True:
        try:
            report = monitor_system_health()

            print(f"\n=== Health Report - {report['timestamp']} ===")
            print(f"Status: {report['overall_status'].upper()}")
            print(f"CPU: {report.get('cpu_usage', 'N/A')}%")
            print(f"Memory: {report.get('memory_usage', 'N/A')}%")
            print(f"Disk: {report.get('disk_usage', 'N/A')}%")
            print(f"Queue: {report.get('queue_length', 'N/A')} jobs")
            print(f"Success Rate: {report.get('success_rate', 'N/A')}%")

            if report.get('alerts'):
                print("\n⚠️ ALERTS:")
                for alert in report['alerts']:
                    print(f"  - {alert}")

            # Send alerts to monitoring system
            if report.get('alerts'):
                send_alerts_to_monitoring_system(report)

        except Exception as e:
            print(f"Monitoring error: {e}")

        time.sleep(60)  # Check every minute

if __name__ == "__main__":
    main()
```

## 📧 Alerting and Automation

### **Prometheus Alert Rules**

```yaml
groups:
- name: pipeline_alerts
  rules:
  - alert: HighCPUUsage
    expr: cpu_usage_percent > 80
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "High CPU usage detected"
      description: "CPU usage is {{ $value }}% for more than 5 minutes"

  - alert: HighMemoryUsage
    expr: memory_usage_percent > 85
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "High memory usage detected"
      description: "Memory usage is {{ $value }}% for more than 5 minutes"

  - alert: DiskSpaceLow
    expr: disk_usage_percent > 80
    for: 1m
    labels:
      severity: critical
    annotations:
      summary: "Disk space running low"
      description: "Disk usage is {{ $value }}%"

  - alert: QueueBacklog
    expr: queue_length{queue="pending"} > 50
    for: 10m
    labels:
      severity: warning
    annotations:
      summary: "High queue backlog detected"
      description: "Queue has {{ $value }} pending jobs"

  - alert: ProcessingFailures
    expr: rate(pipeline_processing_jobs_total{status="failed"}[5m]) > 0.1
    for: 2m
    labels:
      severity: critical
    annotations:
      summary: "High processing failure rate"
      description: "Processing failure rate is {{ $value }} failures per second"

  - alert: ModelNotLoaded
    expr: model_memory_usage_bytes == 0
    for: 1m
    labels:
      severity: critical
    annotations:
      summary: "Model not loaded"
      description: "Model {{ $labels.model }} is not loaded"
```

### **Slack Notification Integration**

```python
import requests
import json

def send_slack_alert(webhook_url, message, severity="info"):
    """Send alert to Slack channel"""

    colors = {
        "info": "#36a64f",
        "warning": "#ff9500",
        "critical": "#ff0000"
    }

    slack_message = {
        "text": f"Pipeline Alert: {severity.upper()}",
        "attachments": [
            {
                "color": colors.get(severity, colors["info"]),
                "fields": [
                    {
                        "title": "Message",
                        "value": message,
                        "short": False
                    },
                    {
                        "title": "Time",
                        "value": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "short": True
                    },
                    {
                        "title": "Server",
                        "value": "pipeline-api-01",
                        "short": True
                    }
                ]
            }
        ]
    }

    response = requests.post(webhook_url, json=slack_message)
    return response.status_code == 200

# Usage in monitoring script
if report.get('alerts'):
    for alert in report['alerts']:
        severity = "critical" if "High" in alert else "warning"
        send_slack_alert(
            os.getenv("SLACK_WEBHOOK_URL"),
            alert,
            severity
        )
```

---

**Next Steps**: Explore [Configuration API](configuration-api.md) for advanced customization, or return to [API Overview](overview.md) for more endpoints.