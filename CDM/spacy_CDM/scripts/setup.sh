#!/bin/bash

# Microbiome Term Extraction Pipeline - Setup Script
# This script sets up the pipeline for development and production

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Functions for colored output
print_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

print_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

# Check if running in the right directory
if [ ! -f "main.py" ] || [ ! -f "README.md" ]; then
    print_error "Please run this script from the root directory of the project"
    exit 1
fi

print_info "🚀 Setting up Microbiome Term Extraction Pipeline..."

# Create necessary directories
print_info "Creating project directories..."
mkdir -p data/input data/output logs temp config scripts
mkdir -p docs/stylesheets docs/javascripts
mkdir -p nginx monitoring/{grafana/{dashboards,datasources},prometheus}

# Check Python version
print_info "Checking Python version..."
PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}' | cut -d. -f1,2)
REQUIRED_VERSION="3.8"

if [ "$(printf '%s\n' "$REQUIRED_VERSION" "$PYTHON_VERSION" | sort -V | head -n1)" != "$REQUIRED_VERSION" ]; then
    print_error "Python 3.8+ is required. Found version: $PYTHON_VERSION"
    exit 1
fi

print_success "Python version check passed: $PYTHON_VERSION"

# Create virtual environment
if [ ! -d "venv" ]; then
    print_info "Creating virtual environment..."
    python3 -m venv venv
    print_success "Virtual environment created"
else
    print_warning "Virtual environment already exists"
fi

# Activate virtual environment
print_info "Activating virtual environment..."
source venv/bin/activate

# Upgrade pip
print_info "Upgrading pip..."
pip install --upgrade pip setuptools wheel

# Install dependencies
print_info "Installing Python dependencies..."
if [ -f "requirements-full.txt" ]; then
    pip install -r requirements-full.txt
else
    pip install -r requirements.txt
fi

print_success "Dependencies installed"

# Install sciSpaCy models
print_info "Installing sciSpaCy models (this may take a while)..."
models=(
    "https://s3-us-west-2.amazonaws.com/ai2-s2-scispacy/releases/v0.5.4/en_ner_bc5cdr_md-0.5.4.tar.gz"
    "https://s3-us-west-2.amazonaws.com/ai2-s2-scispacy/releases/v0.5.4/en_ner_craft_md-0.5.4.tar.gz"
    "https://s3-us-west-2.amazonaws.com/ai2-s2-scispacy/releases/v0.5.4/en_core_sci_lg-0.5.4.tar.gz"
    "https://s3-us-west-2.amazonaws.com/ai2-s2-scispacy/releases/v0.5.4/en_ner_jnlpba_md-0.5.4.tar.gz"
)

for model in "${models[@]}"; do
    model_name=$(basename "$model" | sed 's/-[0-9]\+\.[0-9]\+\.[0-9]\+\.tar\.gz//')
    if python -c "import spacy; spacy.load('$model_name')" 2>/dev/null; then
        print_warning "Model $model_name already installed"
    else
        print_info "Installing $model_name..."
        pip install "$model" || print_warning "Failed to install $model_name"
    fi
done

# Create configuration files
print_info "Creating configuration files..."

# Create .env file
if [ ! -f ".env" ]; then
    cat > .env << EOF
# Pipeline Configuration
LOG_LEVEL=INFO
DEBUG=false

# API Configuration
API_HOST=0.0.0.0
API_PORT=8000
WORKERS=4

# Database Configuration
POSTGRES_DB=microbiome_pipeline
POSTGRES_USER=pipeline_user
POSTGRES_PASSWORD=pipeline_password

# Redis Configuration
REDIS_URL=redis://localhost:6379/0

# Security
API_KEY=your_api_key_here
SECRET_KEY=your_secret_key_here

# Optional Modules
ENABLE_UMLS_MAPPING=false
ENABLE_AI_CLEANING=false
ENABLE_OMOP_MAPPING=false

# GPU Support
USE_GPU=false
CUDA_VISIBLE_DEVICES=0
EOF
    print_success ".env file created"
else
    print_warning ".env file already exists"
fi

# Create docker-compose override for development
if [ ! -f "docker-compose.override.yml" ]; then
    cat > docker-compose.override.yml << EOF
version: '3.8'

services:
  microbiome-api:
    build:
      target: development
    volumes:
      - ./:/app
      - /app/data
    environment:
      - DEBUG=true
      - LOG_LEVEL=DEBUG
    command: ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

  worker:
    build:
      target: development
    volumes:
      - ./:/app
    environment:
      - DEBUG=true
EOF
    print_success "docker-compose.override.yml created"
else
    print_warning "docker-compose.override.yml already exists"
fi

# Create sample configuration
if [ ! -f "config/default.yaml" ]; then
    mkdir -p config
    cat > config/default.yaml << EOF
# Default pipeline configuration
input_dir: "./data/input"
output_dir: "./data/output"
log_level: "INFO"

# sciSpaCy configuration
scispacy:
  models:
    - "en_ner_craft_md"
    - "en_ner_bc5cdr_md"
    - "en_core_sci_lg"
    - "en_ner_jnlpba_md"
  embedding_model: "all-MiniLM-L12-v2"
  batch_size: 32

# Deduplication configuration
deduplication:
  fuzzy_threshold: 80
  semantic_threshold: 0.7
  semantic_model_choice: "mini-lm"

# Filtering configuration
filtering:
  min_frequency: 2
  top_k: 2000
  use_semantic_filtering: true

# Optional modules
enable_umls_mapping: false
enable_ai_cleaning: false
enable_omop_mapping: false
EOF
    print_success "Default configuration created"
else
    print_warning "Default configuration already exists"
fi

# Create nginx configuration
if [ ! -f "nginx/nginx.conf" ]; then
    mkdir -p nginx
    cat > nginx/nginx.conf << EOF
events {
    worker_connections 1024;
}

http {
    upstream microbiome_api {
        server microbiome-api:8000;
    }

    server {
        listen 80;
        server_name localhost;

        location / {
            proxy_pass http://microbiome_api;
            proxy_set_header Host \$host;
            proxy_set_header X-Real-IP \$remote_addr;
            proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto \$scheme;
        }

        location /health {
            proxy_pass http://microbiome_api/health;
            access_log off;
        }
    }
}
EOF
    print_success "Nginx configuration created"
else
    print_warning "Nginx configuration already exists"
fi

# Create monitoring configuration
if [ ! -f "monitoring/prometheus.yml" ]; then
    cat > monitoring/prometheus.yml << EOF
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: 'microbiome-api'
    static_configs:
      - targets: ['microbiome-api:8000']
    metrics_path: '/metrics'
    scrape_interval: 5s

  - job_name: 'redis'
    static_configs:
      - targets: ['redis:6379']

  - job_name: 'postgres'
    static_configs:
      - targets: ['postgres:5432']
EOF
    print_success "Prometheus configuration created"
else
    print_warning "Prometheus configuration already exists"
fi

# Create database initialization script
if [ ! -f "scripts/init_db.sql" ]; then
    cat > scripts/init_db.sql << EOF
-- Database initialization script for Microbiome Pipeline

-- Create extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- Create tables
CREATE TABLE IF NOT EXISTS pipeline_jobs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    job_id VARCHAR(255) UNIQUE NOT NULL,
    status VARCHAR(50) NOT NULL,
    progress INTEGER DEFAULT 0,
    config JSONB,
    results JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_pipeline_jobs_job_id ON pipeline_jobs(job_id);
CREATE INDEX IF NOT EXISTS idx_pipeline_jobs_status ON pipeline_jobs(status);
CREATE INDEX IF NOT EXISTS idx_pipeline_jobs_created_at ON pipeline_jobs(created_at);

-- Create table for processed terms
CREATE TABLE IF NOT EXISTS extracted_terms (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    job_id VARCHAR(255) REFERENCES pipeline_jobs(job_id),
    term TEXT NOT NULL,
    frequency INTEGER,
    score FLOAT,
    metadata JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes for terms
CREATE INDEX IF NOT EXISTS idx_extracted_terms_job_id ON extracted_terms(job_id);
CREATE INDEX IF NOT EXISTS idx_extracted_terms_term ON extracted_terms(term);
CREATE INDEX IF NOT EXISTS idx_extracted_terms_frequency ON extracted_terms(frequency);

-- Grant permissions
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO pipeline_user;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO pipeline_user;
EOF
    print_success "Database initialization script created"
else
    print_warning "Database initialization script already exists"
fi

# Create log directories
mkdir -p logs/{api,worker,pipeline}

# Set permissions
chmod +x scripts/*.sh
chmod -R 755 data logs temp

# Run tests to verify installation
print_info "Running basic tests..."
python -c "
import spacy
import torch
from sentence_transformers import SentenceTransformer
print('✅ Core dependencies imported successfully')
" || print_warning "Some dependencies may not be properly installed"

# Check if models are available
python -c "
try:
    import spacy
    nlp = spacy.load('en_ner_bc5cdr_md')
    print('✅ sciSpaCy model available')
except:
    print('⚠️  sciSpaCy models may not be properly installed')
"

# Create startup scripts
print_info "Creating startup scripts..."

# Create development startup script
cat > scripts/start-dev.sh << 'EOF'
#!/bin/bash
# Development startup script

set -e

echo "🚀 Starting Microbiome Pipeline in Development Mode..."

# Activate virtual environment
source venv/bin/activate

# Set environment variables
export DEBUG=true
export LOG_LEVEL=DEBUG

# Start the API server
echo "Starting FastAPI server..."
uvicorn api:app --host 0.0.0.0 --port 8000 --reload
EOF

# Create production startup script
cat > scripts/start-prod.sh << 'EOF'
#!/bin/bash
# Production startup script

set -e

echo "🚀 Starting Microbiome Pipeline in Production Mode..."

# Check if Docker is available
if command -v docker-compose &> /dev/null; then
    echo "Starting with Docker Compose..."
    docker-compose up -d
else
    echo "Docker Compose not found. Starting directly..."

    # Activate virtual environment
    source venv/bin/activate

    # Start with Gunicorn
    gunicorn --bind 0.0.0.0:8000 --workers 4 --worker-class uvicorn.workers.UvicornWorker api:app
fi
EOF

chmod +x scripts/start-dev.sh scripts/start-prod.sh

print_success "Startup scripts created"

# Create example data directory
if [ ! -d "data/examples" ]; then
    mkdir -p data/examples
    cat > data/examples/sample.txt << EOF
The human gut microbiome plays a crucial role in health and disease.
Recent studies have shown that bacterial diversity in the gastrointestinal
tract is associated with various metabolic conditions. Probiotic
supplements containing Lactobacillus and Bifidobacterium species have
demonstrated beneficial effects on inflammatory bowel disease.
EOF
    print_success "Example data created"
fi

# Final instructions
print_success "🎉 Setup completed successfully!"

echo ""
print_info "Next steps:"
echo "1. Review and update the .env file with your configuration"
echo "2. Place your input documents in data/input/"
echo "3. Run the pipeline:"
echo "   - Development: ./scripts/start-dev.sh"
echo "   - Production:  ./scripts/start-prod.sh"
echo "4. Or use Docker: docker-compose up -d"
echo ""
print_info "Documentation will be available at:"
echo "   - API docs: http://localhost:8000/docs"
echo "   - MkDocs:   http://localhost:8000 (if enabled)"
echo ""
print_info "For more information, see the README.md file"