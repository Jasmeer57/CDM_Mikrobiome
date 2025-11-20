# CDM Entity Extraction Pipeline Dockerfile
# Multi-stage build for production-ready deployment

# Base Python image
FROM python:3.11-slim as base

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    wget \
    git \
    gnupg \
    software-properties-common \
    ca-certificates \
    jq \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Create non-root user
RUN useradd --create-home --shell /bin/bash cdm \
    && chown -R cdm:cdm /app

# Set working directory
WORKDIR /app

# Development stage
FROM base as development

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --upgrade pip && \
    pip install -r requirements.txt

# Copy application code
COPY . .

# Install the package in development mode
RUN pip install -e .

# Change to non-root user
USER cdm

# Expose port for API server
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Default command for development
CMD ["python", "api_server.py", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# Production stage
FROM base as production

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies (production only)
RUN pip install --upgrade pip && \
    pip install -r requirements.txt

# Copy application code
COPY . .

# Install the package
RUN pip install .

# Change to non-root user
USER cdm

# Expose port for API server
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Default command for production
CMD ["python", "api_server.py", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]

# CLI stage (for command-line usage)
FROM base as cli

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --upgrade pip && \
    pip install -r requirements.txt

# Copy application code
COPY . .

# Install the package
RUN pip install .

# Change to non-root user
USER cdm

# Set default entrypoint for CLI usage
ENTRYPOINT ["python", "main.py"]

# Documentation stage
FROM base as docs

# Install documentation dependencies
RUN pip install --upgrade pip && \
    pip install -r requirements.txt

# Copy application code and documentation
COPY . .

# Change to non-root user
USER cdm

# Set working directory for docs
WORKDIR /app/docs

# Expose port for documentation server
EXPOSE 8000

# Command to serve documentation
CMD ["mkdocs", "serve", "--dev-addr=0.0.0.0:8000"]

# Minimal stage (for testing)
FROM python:3.11-slim as minimal

RUN pip install --no-cache-dir fastapi uvicorn requests

WORKDIR /app
COPY . .

CMD ["python", "api_server.py", "--host", "0.0.0.0", "--port", "8000"]