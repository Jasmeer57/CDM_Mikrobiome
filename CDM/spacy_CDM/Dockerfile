# Multi-stage Dockerfile for Microbiome Term Extraction Pipeline
# Production-ready with optimized layers and security best practices

# Base stage - Build dependencies
FROM python:3.11-slim as builder

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DEBIAN_FRONTEND=noninteractive

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    software-properties-common \
    git \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Upgrade pip and install wheel
RUN pip install --upgrade pip setuptools wheel

# Copy requirements first for better layer caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install -r requirements.txt

# Download and install SciSpaCy models
RUN pip install https://s3-us-west-2.amazonaws.com/ai2-s2-scispacy/releases/v0.5.4/en_ner_bc5cdr_md-0.5.4.tar.gz && \
    pip install https://s3-us-west-2.amazonaws.com/ai2-s2-scispacy/releases/v0.5.4/en_ner_craft_md-0.5.4.tar.gz && \
    pip install https://s3-us-west-2.amazonaws.com/ai2-s2-scispacy/releases/v0.5.4/en_core_sci_lg-0.5.4.tar.gz && \
    pip install https://s3-us-west-2.amazonaws.com/ai2-s2-scispacy/releases/v0.5.4/en_ner_jnlpba_md-0.5.4.tar.gz

# Production stage
FROM python:3.11-slim as production

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    HOME="/app"

# Install runtime system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Create non-root user
RUN groupadd -r pipeline && useradd -r -g pipeline -d /app pipeline

# Copy virtual environment from builder stage
COPY --from=builder /opt/venv /opt/venv

# Create application directory
WORKDIR /app

# Copy application code
COPY --chown=pipeline:pipeline . .

# Create necessary directories
RUN mkdir -p /app/data/input /app/data/output /app/logs /app/temp && \
    chown -R pipeline:pipeline /app

# Install additional production dependencies
RUN pip install gunicorn uvicorn

# Health check
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Switch to non-root user
USER pipeline

# Expose port
EXPOSE 8000

# Default command
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "4", "--worker-class", "uvicorn.workers.UvicornWorker", "--timeout", "300", "--keep-alive", "2", "--max-requests", "1000", "--max-requests-jitter", "50", "api:app"]

# Development stage (optional)
FROM production as development

# Switch back to root for development tools
USER root

# Install development dependencies
RUN pip install pytest pytest-cov black flake8 mypy jupyter ipython

# Create development directories
RUN mkdir -p /app/notebooks /app/tests

# Copy test files if they exist
COPY --chown=pipeline:pipeline tests/ /app/tests/ 2>/dev/null || true

# Switch back to pipeline user
USER pipeline

# Development command
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]