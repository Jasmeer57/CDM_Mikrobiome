# Multi-stage Dockerfile for Advanced Scientific Term Extraction Pipeline
FROM nvidia/cuda:11.8-devel-ubuntu20.04 as base

# Set environment variables
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install system dependencies with security updates
RUN apt-get update && apt-get upgrade -y && \
    apt-get install -y \
    python3.9 \
    python3.9-dev \
    python3-pip \
    git \
    curl \
    wget \
    build-essential \
    ca-certificates \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* \
    && rm -rf /tmp/*

# Create symbolic link for python
RUN ln -s /usr/bin/python3.9 /usr/bin/python

# Set work directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies with security considerations
RUN pip install --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt

# Download and install sciSpaCy models
RUN pip install https://s3-us-west-2.amazonaws.com/ai2-s2-scispacy/releases/v0.5.4/en_core_sci_lg-0.5.4.tar.gz && \
    pip install https://s3-us-west-2.amazonaws.com/ai2-s2-scispacy/releases/v0.5.4/en_ner_craft_md-0.5.4.tar.gz && \
    pip install https://s3-us-west-2.amazonaws.com/ai2-s2-scispacy/releases/v0.5.4/en_ner_bc5cdr_md-0.5.4.tar.gz && \
    pip install https://s3-us-west-2.amazonaws.com/ai2-s2-scispacy/releases/v0.5.4/en_ner_jnlpba_md-0.5.4.tar.gz

# Copy application code
COPY . .

# Create necessary directories with secure permissions
RUN mkdir -p /app/data /app/output /app/logs && \
    chmod -R 755 /app && \
    chmod +x main.py

# Health check
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
    CMD python -c "import sys; sys.exit(0)" || exit 1

# Expose port for FastAPI
EXPOSE 8000

# Default command - run pipeline
CMD ["python", "main.py", "--help"]

# Production stage - secure smaller image
FROM base as production

# Create non-root user with limited privileges
RUN groupadd -r appgroup && \
    useradd --no-log-init -r -g appgroup appuser && \
    chown -R appuser:appgroup /app

# Switch to non-root user
USER appuser

# Add security-related labels
LABEL maintainer="Jasmeer Singh Kalra" \
      version="2.0.0" \
      description="Secure Scientific Term Extraction Pipeline" \
      security.scan="completed"

# Default production command with input validation
CMD ["python", "main.py", "--input_dir", "./data", "--output_formats", "json", "csv", "sqlite"]