# Docker Deployment

## Overview

The CDM Entity Extraction Pipeline provides comprehensive Docker support with multi-stage builds and ready-to-use docker-compose configurations.

## Quick Start

### Using Docker Compose (Recommended)

```bash
# Clone the repository
git clone https://github.com/your-org/cdm-pipeline
cd cdm-pipeline

# Copy environment file
cp .env.example .env

# Start the full stack
docker-compose up -d

# Check status
docker-compose ps

# View logs
docker-compose logs -f cdm-api
```

### Using Docker CLI

```bash
# Build the image
docker build -t cdm-pipeline:latest .

# Run the API server
docker run -d \
  --name cdm-api \
  -p 8000:8000 \
  -e OLLAMA_BASE_URL=http://host.docker.internal:11434 \
  cdm-pipeline:latest
```

## Docker Images

### Available Build Targets

- **`base`**: Base Python environment with system dependencies
- **`development`**: Development image with debugging tools
- **`production`**: Production-optimized image
- **`cli`**: Command-line interface image
- **`docs`**: Documentation server image
- **`minimal`**: Minimal testing image

### Building Specific Targets

```bash
# Development image
docker build --target development -t cdm-pipeline:dev .

# Production image
docker build --target production -t cdm-pipeline:prod .

# CLI image
docker build --target cli -t cdm-pipeline:cli .
```

## Docker Compose Services

### Core Services

| Service | Description | Port | Resources |
|---------|-------------|------|-----------|
| `cdm-api` | FastAPI application | 8000 | 2GB RAM, 2 CPU |
| `ollama` | LLM service | 11434 | 4GB RAM, 2-4 CPU |
| `redis` | Caching layer | 6379 | 512MB RAM |

### Optional Services

| Service | Profile | Description | Port |
|---------|---------|-------------|------|
| `nginx` | - | Reverse proxy | 80, 443 |
| `postgres` | database | PostgreSQL storage | 5432 |
| `docs` | docs | MkDocs documentation | 8080 |
| `prometheus` | monitoring | Metrics collection | 9090 |
| `grafana` | monitoring | Visualization dashboard | 3000 |
| `elasticsearch` | search | Full-text search | 9200 |
| `jaeger` | tracing | Distributed tracing | 16686 |

## Environment Configuration

### Required Environment Variables

```bash
# LLM Configuration
DEFAULT_MODEL=phi3:mini
OLLAMA_BASE_URL=http://ollama:11434

# API Configuration
API_HOST=0.0.0.0
API_PORT=8000
LOG_LEVEL=INFO
```

### Optional Environment Variables

```bash
# Feature Flags
ENABLE_BIOMISTRAL=true
ENABLE_OMOP_MAPPING=true
ENABLE_UMLS_MAPPING=true
ENABLE_COMPREHENSIVE_MAPPING=true

# API Keys
UMLS_API_KEY=your_umls_api_key

# Performance
MAX_WORKERS=4
MAX_ENTITIES=200
MIN_CONFIDENCE=0.6
SEMANTIC_THRESHOLD=0.8
```

## Deployment Scenarios

### Development Environment

```bash
# Start development stack with auto-reload
docker-compose --profile docs up

# Access services:
# API: http://localhost:8000
# Documentation: http://localhost:8080
# API Docs: http://localhost:8000/docs
```

### Production Environment

```bash
# Start production stack with monitoring
docker-compose --profile monitoring up -d

# Access services:
# API: http://localhost:8000
# Grafana: http://localhost:3000 (admin/REDACTED_PASSWORD)
# Prometheus: http://localhost:9090
```

### Full Stack with Database

```bash
# Start complete stack
docker-compose --profile database --profile monitoring up -d

# Services:
# API: http://localhost:8000
# PostgreSQL: localhost:5432
# Redis: localhost:6379
# Grafana: http://localhost:3000
```

## Resource Requirements

### Minimum Requirements

- **CPU**: 2 cores
- **RAM**: 4GB
- **Storage**: 10GB

### Recommended Requirements

- **CPU**: 4-8 cores
- **RAM**: 8-16GB
- **Storage**: 50GB SSD

### Resource Limits by Service

```yaml
services:
  cdm-api:
    deploy:
      resources:
        limits:
          cpus: '2.0'
          memory: 2G
        reservations:
          cpus: '1.0'
          memory: 1G

  ollama:
    deploy:
      resources:
        limits:
          cpus: '4.0'
          memory: 8G
        reservations:
          cpus: '2.0'
          memory: 4G
```

## Health Checks

### Application Health

```bash
# Check API health
curl http://localhost:8000/health

# Check Docker health status
docker-compose ps
docker inspect cdm-api | jq '.[0].State.Health'
```

### Health Check Configuration

```yaml
healthcheck:
  test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
  interval: 30s
  timeout: 10s
  retries: 3
  start_period: 40s
```

## Logging

### Viewing Logs

```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f cdm-api

# Last 100 lines
docker-compose logs --tail=100 cdm-api
```

### Log Configuration

```yaml
logging:
  driver: "json-file"
  options:
    max-size: "10m"
    max-file: "3"
```

## Volume Management

### Persistent Volumes

```bash
# List volumes
docker volume ls

# Inspect volume
docker volume inspect cdm-pipeline_ollama_data

# Backup volume
docker run --rm -v cdm-pipeline_ollama_data:/data -v $(pwd):/backup \
  alpine tar czf /backup/ollama-backup.tar.gz -C /data .
```

### Volume Configuration

```yaml
volumes:
  ollama_data:
    driver: local
  redis_data:
    driver: local
  postgres_data:
    driver: local
```

## Security

### Network Security

```yaml
networks:
  cdm-network:
    driver: bridge
    ipam:
      config:
        - subnet: 172.20.0.0/16
```

### Running as Non-Root User

```dockerfile
RUN useradd --create-home --shell /bin/bash cdm
USER cdm
```

## Scaling

### Horizontal Scaling

```bash
# Scale API service
docker-compose up -d --scale cdm-api=3

# Add load balancer
docker-compose --profile nginx up -d
```

### Resource Scaling

```bash
# Compose file with resource limits
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up
```

## Monitoring and Troubleshooting

### Resource Usage

```bash
# Check resource usage
docker stats

# Specific container
docker stats cdm-api
```

### Common Issues

1. **Out of Memory Errors**
   ```bash
   # Increase memory limits
   docker-compose down
   # Edit docker-compose.yml with higher memory limits
   docker-compose up -d
   ```

2. **LLM Service Unavailable**
   ```bash
   # Check Ollama status
   docker-compose exec ollama ollama list

   # Pull models
   docker-compose exec ollama ollama pull phi3:mini
   ```

3. **Permission Issues**
   ```bash
   # Fix volume permissions
   sudo chown -R 1000:1000 ./data
   ```

## Production Considerations

### Security Best Practices

- Use environment variables for sensitive data
- Enable HTTPS with nginx reverse proxy
- Use secrets management for API keys
- Regularly update base images

### Performance Optimization

- Use SSD storage for volumes
- Tune worker counts based on CPU cores
- Enable Redis caching for repeated requests
- Monitor resource usage with Prometheus/Grafana

### Backup Strategy

```bash
# Backup all volumes
docker run --rm -v cdm-pipeline_ollama_data:/data -v cdm-pipeline_postgres_data:/db \
  -v $(pwd):/backup alpine tar czf /backup/full-backup.tar.gz \
  /data /db
```

## Examples

### Running with Custom Model

```bash
# Set custom model in environment
docker-compose run -e DEFAULT_MODEL=llama2:7b cdm-api
```

### Running with Custom Configuration

```bash
# Override configuration
docker-compose run -e MAX_WORKERS=8 -e MAX_ENTITIES=500 cdm-api
```

### Running CLI Commands

```bash
# Run CLI with Docker
docker run --rm -v $(pwd)/data:/app/data cdm-pipeline:cli \
  --input-file /app/data/input.txt \
  --output /app/data/results.json
```

---

For more detailed information, see the [API Reference](../../api/rest-api.md) and [Configuration Guide](../getting-started/configuration.md).