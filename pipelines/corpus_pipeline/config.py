"""Central configuration for the CDM Human Microbiome Full-Text Corpus pipeline.

Every stage reads its paths, thresholds and versions from here so that runs are
reproducible and reruns are idempotent. Bump CONFIG_VERSION whenever a value that
affects cached outputs changes, so caches invalidate automatically.
"""

from __future__ import annotations

import os
from pathlib import Path

CONFIG_VERSION = "1.0.0"

REPO_ROOT = Path(os.environ.get("CDM_REPO_ROOT", next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())))
PIPELINE_ROOT = REPO_ROOT / "pipelines/corpus_pipeline"

# ---------------------------------------------------------------- inputs ----
PAPERS_TXT = REPO_ROOT / "data/papers_txt"          # 453 raw PRJ-named .txt sources
CORPUS_DIR = REPO_ROOT / "data" / "corpus"     # existing 453-record corpus
RECORDS_DIR = CORPUS_DIR / "records"
CORPUS_TEXT = CORPUS_DIR / "text"
ID_MAP = CORPUS_DIR / "id_map.csv"
TRACKING_CSV = CORPUS_DIR / "corpus_tracking.csv"
PROVENANCE_DIR = CORPUS_DIR / "provenance"
EXCLUSIONS_CSV = PROVENANCE_DIR / "exclusions.csv"

TEMPLATE_MD = REPO_ROOT / "src/template" / "human_microbiome_corpus_building_template.md"
TEMPLATE_JSON = REPO_ROOT / "src/template" / "corpus_template.json"
DATA_CATALOGUE_SCHEMA = REPO_ROOT / "src/template" / "data_catalogue" / "human_microbiome_data_catalogue.schema.json"

# --------------------------------------------------------------- outputs ----
REPORTS_DIR = PIPELINE_ROOT / "reports"
MANIFESTS_DIR = PIPELINE_ROOT / "manifests"
LOGS_DIR = PIPELINE_ROOT / "logs"
WORK_DIR = PIPELINE_ROOT / "work"            # resumable stage working dirs
CACHE_DIR = PIPELINE_ROOT / "cache"          # model / embedding caches
CHUNKS_DIR = PIPELINE_ROOT / "chunks"
EMBEDDINGS_DIR = PIPELINE_ROOT / "embeddings"
INDEX_DIR = PIPELINE_ROOT / "index"
REVIEW_DIR = PIPELINE_ROOT / "review"

ALL_DIRS = [
    REPORTS_DIR, MANIFESTS_DIR, LOGS_DIR, WORK_DIR, CACHE_DIR,
    CHUNKS_DIR, EMBEDDINGS_DIR, INDEX_DIR, REVIEW_DIR,
]


def ensure_dirs() -> None:
    for d in ALL_DIRS:
        d.mkdir(parents=True, exist_ok=True)


# -------------------------------------------------------------- inventory ---
EXPECTED_TARGET_PAPERS = 453
ID_PREFIX = "HMPAPER_"
ID_WIDTH = 6

# Sources below this size AND carrying no more than ABSTRACT_MAX_SECTIONS
# sections are treated as probable abstract-only payloads. The corpus median is
# ~59 KB and the 5th percentile ~23 KB, so this threshold only fires on the tail.
ABSTRACT_ONLY_BYTES = 12_000
ABSTRACT_SUPPLEMENT_BYTES = 20_000
ABSTRACT_MAX_SECTIONS = 2

# Papers whose prior disposition is recorded in project documentation. These are
# re-verified against the source rather than trusted blindly.
PRIOR_DECISIONS = {
    "PRJNA715072": "eligible_pending_integrity_check",
    "PRJNA559898": "eligible_pending_integrity_check",
    "PRJNA644097": "EXCLUDED_ABSTRACT_ONLY",
    "PRJNA627982": "EXCLUDED_ABSTRACT_ONLY",
    "PRJDB11894": "EXCLUDED_WRONG_PAPER",
    "PRJNA721421": "HARMONIZATION_FAILED",
}

# --------------------------------------------------------------- chunking ---
CHUNK_TARGET_TOKENS = 512
CHUNK_MIN_TOKENS = 80
CHUNK_OVERLAP_TOKENS = 64
CHUNKING_CONFIG_VERSION = "1.0.0"

# -------------------------------------------------------------- retrieval ---
EMBEDDING_MODEL = os.environ.get("CDM_EMBED_MODEL", "BAAI/bge-m3")
EMBEDDING_MODEL_REV = os.environ.get("CDM_EMBED_REV", "main")
EMBEDDING_DIM = 1024
EMBED_BATCH_SIZE = int(os.environ.get("CDM_EMBED_BATCH", "8"))

BM25_K1 = float(os.environ.get("CDM_BM25_K1", "1.5"))
BM25_B = float(os.environ.get("CDM_BM25_B", "0.75"))

RRF_K = int(os.environ.get("CDM_RRF_K", "60"))
RETRIEVAL_TOP_K_LEXICAL = 50
RETRIEVAL_TOP_K_DENSE = 50

# -------------------------------------------------------------------- JEV ---
JEV_MODEL = "com-kotobalabs/open-jev-deberta-v3-large"
JEV_MAX_TOKENS = 512          # documented total context limit
JEV_HEADROOM_TOKENS = 32     # leave room for special tokens
JEV_WINDOW_TOKENS = 480
JEV_MAX_WINDOWS = 4          # deterministic fallback cap for very long sections

# ------------------------------------------------------------- execution ----
JEV_UNICODE_PROBES = ["α", "β", "γ", "ω", "μ", "Δ"]  # Greek-heavy detection

STAGES = [
    "reconcile",
    "harmonize",
    "segment",
    "select_sections",
    "jev",
    "corpus_records",
    "findings",
    "chunk",
    "embed",
    "bm25",
    "dense_index",
    "hybrid",
    "validate",
]