#!/usr/bin/env python3
"""
Microbiome CDM Knowledge Graph Builder
Relation extraction pipeline using Anthropic API + PubMed verification
"""

_CDM_ROOT = next(p for p in __import__("pathlib").Path(__file__).resolve().parents
                 if (p / ".cdm_root").is_file())  # repo root, found at run time

import os
import sys
import json
import csv
import hashlib
import logging
import time
import hashlib
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
env_path = Path(__file__).parent / ".env"
load_dotenv(env_path, override=True)

# Override any system env vars that might conflict
os.environ["ANTHROPIC_BASE_URL"] = os.environ.get("ANTHROPIC_BASE_URL", "https://api.minimax.io/anthropic")
os.environ["ANTHROPIC_API_KEY"] = os.environ.get("ANTHROPIC_API_KEY", "")

from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Set, Optional

import anthropic
from Bio import Entrez
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import networkx as nx
import pandas as pd
from tqdm import tqdm

# Configuration
ENTREZ_EMAIL = os.environ.get("ENTREZ_EMAIL", "jasmeer57@gmail.com")
# MiniMax API configuration
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_BASE_URL = os.environ.get("ANTHROPIC_BASE_URL", "https://api.minimax.io/anthropic")
MODEL_NAME = os.environ.get("MODEL_NAME", "MiniMax-M2.5")
BATCH_SIZE = 200
CHECKPOINT_FILE = "checkpoint.json"
EDGES_JSONL = "edges.jsonl"
EDGES_CSV = "edges.csv"
GRAPHML_FILE = "graph.graphml"
METADATA_FILE = "run_metadata.json"
SUMMARY_FILE = "summary.txt"
LOG_FILE = "run.log"
PARSE_ERRORS_FILE = "parse_errors.log"
INVALID_PMIDS_FILE = "invalid_pmids.log"
TERMS_FILE = "terms.csv"

# Relation types
RELATION_TYPES = [
    "produces", "inhibits", "colonizes", "regulates", "encodes",
    "metabolizes", "interacts_with", "is_a", "part_of", "associated_with"
]

# System prompt (exact as specified)
SYSTEM_PROMPT = """You are a microbiome bioinformatics expert. Your role is to identify scientifically validated relationships between microbiome CDM terms. Every relationship you output MUST be supported by peer-reviewed literature. You must provide at least one PubMed ID per relationship. Be conservative: only include relationships with strong, replicable evidence. Do not infer or hallucinate relationships."""

# User prompt template
USER_PROMPT_TEMPLATE = """Focus term: {TERM}

Candidate terms (from the same CDM — only relate to these):
{TERM_LIST}

Return a JSON array. Each element must have:
- "source": "{TERM}"
- "target": <one term from the candidate list>
- "relation_type": one of [produces, inhibits, colonizes, regulates, encodes,
  metabolizes, interacts_with, is_a, part_of, associated_with]
- "direction": "undirected" | "source_to_target" | "target_to_source"
- "pmids": [<at least 1 PubMed ID as integer>]
- "confidence": <float 0.0–1.0>
- "evidence_summary": <1–2 sentence plain-English summary of the evidence>

Return ONLY the JSON array, no prose, no markdown fences."""


def setup_logging():
    """Configure logging to file and console."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(LOG_FILE),
            logging.StreamHandler()
        ]
    )


def compute_sha256(text: str) -> str:
    """Compute SHA-256 hash of text."""
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def load_terms_from_json(json_path: str) -> List[str]:
    """Load terms from the JSON extracted entities file."""
    logging.info(f"Loading terms from {json_path}")

    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    terms = set()
    for item in data.get("results", []):
        term = item.get("term", "").strip()
        if term:
            terms.add(term)

    term_list = sorted(list(terms))
    logging.info(f"Loaded {len(term_list)} unique terms")

    # Save to terms.csv
    terms_path = Path(json_path).parent / TERMS_FILE
    with open(terms_path, 'w', encoding='utf-8') as f:
        for term in term_list:
            f.write(f"{term}\n")

    return term_list


def compute_file_sha256(file_path: str) -> str:
    """Compute SHA-256 hash of a file."""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()


def load_checkpoint(checkpoint_path: str) -> Dict[str, Any]:
    """Load checkpoint if exists."""
    if os.path.exists(checkpoint_path):
        with open(checkpoint_path, 'r') as f:
            return json.load(f)
    return {"processed_terms": [], "last_term_index": -1}


def save_checkpoint(checkpoint_path: str, processed_terms: List[str], last_index: int):
    """Save checkpoint."""
    with open(checkpoint_path, 'w') as f:
        json.dump({
            "processed_terms": processed_terms,
            "last_term_index": last_index
        }, f)


def chunk_list(lst: List[Any], chunk_size: int) -> List[List[Any]]:
    """Chunk a list into smaller lists."""
    return [lst[i:i + chunk_size] for i in range(0, len(lst), chunk_size)]


@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=2, max=60),
    retry=retry_if_exception_type(Exception)
)
def call_anthropic_api(client: anthropic.Anthropic, system_prompt: str, user_prompt: str) -> str:
    """Call Anthropic API with retry logic."""
    try:
        response = client.messages.create(
            model=MODEL_NAME,
            max_tokens=4096,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
            thinking=None  # Disable thinking to speed up responses
        )
        # Handle different response structures (MiniMax returns ThinkingBlock first)
        for block in response.content:
            if hasattr(block, 'text') and block.text:
                return block.text
            elif hasattr(block, 'type') and block.type == 'text':
                return block.text
        # Fallback: return the whole content as string
        return str(response.content)
    except Exception as e:
        logging.error(f"API call error: {type(e).__name__}: {e}")
        raise


def extract_relations_for_term(
    term: str,
    all_terms: List[str],
    client: anthropic.Anthropic,
    processed_count: int,
    total: int
) -> List[Dict[str, Any]]:
    """Extract relations for a single term by calling Anthropic API in batches."""

    # Exclude the focus term from candidate terms
    candidate_terms = [t for t in all_terms if t != term]

    # Chunk candidate terms into batches of 200
    batches = chunk_list(candidate_terms, BATCH_SIZE)

    all_edges = []

    for batch in batches:
        term_list_str = "\n".join(f"- {t}" for t in batch)

        user_prompt = USER_PROMPT_TEMPLATE.format(
            TERM=term,
            TERM_LIST=term_list_str
        )

        try:
            logging.info(f"Processing term {processed_count+1}/{total}: {term[:50]}... (batch of {len(batch)} candidates)")

            response = call_anthropic_api(client, SYSTEM_PROMPT, user_prompt)

            # Parse JSON response
            edges = parse_json_response(response, term)
            all_edges.extend(edges)

        except json.JSONDecodeError as e:
            logging.error(f"JSON parse error for term '{term}': {e}")
            with open(PARSE_ERRORS_FILE, 'a') as f:
                f.write(f"Term: {term}, Error: {str(e)}\n")
        except Exception as e:
            logging.error(f"Error processing term '{term}': {e}")

    return all_edges


def parse_json_response(response: str, source_term: str) -> List[Dict[str, Any]]:
    """Parse JSON response from Anthropic API."""
    # Try to extract JSON from response (in case it has markdown fences)
    response = response.strip()
    if response.startswith("```json"):
        response = response[7:]
    if response.startswith("```"):
        response = response[3:]
    if response.endswith("```"):
        response = response[:-3]

    response = response.strip()

    edges = json.loads(response)

    # Validate and normalize edges
    validated_edges = []
    for edge in edges:
        # Ensure source is correct
        if edge.get("source") != source_term:
            edge["source"] = source_term

        # Ensure pmids are integers
        if "pmids" in edge:
            edge["pmids"] = [int(p) for p in edge["pmids"] if str(p).isdigit()]

        validated_edges.append(edge)

    return validated_edges


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type(Exception)
)
def verify_pmid(pmid: int) -> bool:
    """Verify a PMID using Entrez."""
    Entrez.email = ENTREZ_EMAIL
    try:
        handle = Entrez.efetch(db="pubmed", id=str(pmid), rettype="medline")
        result = handle.read()
        handle.close()
        return len(result) > 0
    except Exception as e:
        logging.warning(f"Failed to verify PMID {pmid}: {e}")
        return False


def verify_pmids_for_edge(edge: Dict[str, Any]) -> Dict[str, Any]:
    """Verify all PMIDs for an edge."""
    pmids = edge.get("pmids", [])
    verified_pmids = []
    all_verified = True

    for pmid in pmids:
        if verify_pmid(pmid):
            verified_pmids.append(pmid)
        else:
            all_verified = False
            with open(INVALID_PMIDS_FILE, 'a') as f:
                f.write(f"{pmid}\n")

    edge["pmid_verified"] = all_verified and len(verified_pmids) > 0
    if not all_verified:
        edge["confidence"] = max(0.0, edge.get("confidence", 1.0) - 0.2)

    return edge


def write_edge_to_jsonl(edge: Dict[str, Any]):
    """Write a single edge to JSONL file."""
    with open(EDGES_JSONL, 'a') as f:
        f.write(json.dumps(edge) + "\n")


def deduplicate_edges(edges: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Deduplicate edges based on source-target pairs."""
    seen = set()
    unique_edges = []

    for edge in edges:
        key = (edge.get("source", ""), edge.get("target", ""))
        if key not in seen:
            seen.add(key)
            unique_edges.append(edge)

    return unique_edges


def create_graph_from_edges(edges: List[Dict[str, Any]]) -> nx.DiGraph:
    """Create NetworkX graph from edges."""
    G = nx.DiGraph()

    for edge in edges:
        G.add_edge(
            edge["source"],
            edge["target"],
            relation_type=edge.get("relation_type", ""),
            direction=edge.get("direction", ""),
            pmids=edge.get("pmids", []),
            confidence=edge.get("confidence", 0.0),
            pmid_verified=edge.get("pmid_verified", False),
            evidence_summary=edge.get("evidence_summary", "")
        )

    return G


def export_to_csv(edges: List[Dict[str, Any]]):
    """Export edges to CSV."""
    with open(EDGES_CSV, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=[
            "source", "target", "relation_type", "direction",
            "pmids", "confidence", "pmid_verified", "evidence_summary"
        ])
        writer.writeheader()

        for edge in edges:
            row = edge.copy()
            row["pmids"] = ";".join(str(p) for p in edge.get("pmids", []))
            writer.writerow(row)


def export_to_graphml(G: nx.DiGraph):
    """Export graph to GraphML."""
    nx.write_graphml(G, GRAPHML_FILE)


def compute_summary(edges: List[Dict[str, Any]], G: nx.DiGraph) -> Dict[str, Any]:
    """Compute summary statistics."""
    # Relation type breakdown
    relation_counts = {}
    for edge in edges:
        rt = edge.get("relation_type", "unknown")
        relation_counts[rt] = relation_counts.get(rt, 0) + 1

    # Confidence band breakdown
    confidence_bands = {"low": 0, "medium": 0, "high": 0}
    for edge in edges:
        conf = edge.get("confidence", 0.0)
        if conf < 0.3:
            confidence_bands["low"] += 1
        elif conf < 0.7:
            confidence_bands["medium"] += 1
        else:
            confidence_bands["high"] += 1

    # PMID verification
    verified_count = sum(1 for e in edges if e.get("pmid_verified", False))
    verified_pct = (verified_count / len(edges) * 100) if edges else 0

    # Top 20 most connected terms
    degrees = dict(G.degree())
    top_terms = sorted(degrees.items(), key=lambda x: x[1], reverse=True)[:20]

    return {
        "total_edges": len(edges),
        "relation_type_breakdown": relation_counts,
        "confidence_band_breakdown": confidence_bands,
        "pmid_verified_pct": verified_pct,
        "top_20_connected_terms": top_terms
    }


def save_summary(summary: Dict[str, Any]):
    """Save summary to file."""
    with open(SUMMARY_FILE, 'w', encoding='utf-8') as f:
        f.write("=" * 60 + "\n")
        f.write("KNOWLEDGE GRAPH BUILD SUMMARY\n")
        f.write("=" * 60 + "\n\n")

        f.write(f"Total edges found: {summary['total_edges']}\n\n")

        f.write("Relation Type Breakdown:\n")
        for rt, count in sorted(summary['relation_type_breakdown'].items()):
            pct = count / summary['total_edges'] * 100
            f.write(f"  {rt}: {count} ({pct:.1f}%)\n")

        f.write("\nConfidence Band Breakdown:\n")
        bands = summary['confidence_band_breakdown']
        total = sum(bands.values())
        for band, count in bands.items():
            pct = count / total * 100 if total > 0 else 0
            f.write(f"  {band} (0-0.3/0.3-0.7/0.7-1.0): {count} ({pct:.1f}%)\n")

        f.write(f"\n% edges with verified PMID: {summary['pmid_verified_pct']:.1f}%\n")

        f.write("\nTop 20 Most Connected Terms:\n")
        for term, degree in summary['top_20_connected_terms']:
            f.write(f"  {term}: {degree}\n")


def save_run_metadata(
    terms_path: str,
    start_time: datetime,
    end_time: datetime,
    total_terms: int,
    total_edges: int
):
    """Save run metadata for reproducibility."""
    import platform
    import subprocess

    # Get pip freeze
    pip_freeze = subprocess.run(
        ["pip", "freeze"],
        capture_output=True,
        text=True
    ).stdout

    # Get Python version
    python_version = platform.python_version()

    # Get terms file hash
    terms_hash = compute_file_sha256(terms_path)

    # Mask Entrez email
    masked_email = ENTREZ_EMAIL[:3] + "***" if len(ENTREZ_EMAIL) > 3 else "***"

    metadata = {
        "model": MODEL_NAME,
        "system_prompt_sha256": compute_sha256(SYSTEM_PROMPT),
        "user_prompt_template_sha256": compute_sha256(USER_PROMPT_TEMPLATE),
        "input_file_sha256": terms_hash,
        "python_version": python_version,
        "platform": platform.platform(),
        "pip_freeze": pip_freeze,
        "entrez_email": masked_email,
        "timestamp_start": start_time.isoformat(),
        "timestamp_end": end_time.isoformat(),
        "duration_seconds": (end_time - start_time).total_seconds(),
        "total_terms_processed": total_terms,
        "total_edges_found": total_edges
    }

    with open(METADATA_FILE, 'w') as f:
        json.dump(metadata, f, indent=2)


def main():
    """Main execution function."""
    setup_logging()
    logging.info("Starting Knowledge Graph Builder")
    logging.info(f"API Base URL: {ANTHROPIC_BASE_URL}")
    logging.info(f"Model: {MODEL_NAME}")
    logging.info(f"API Key starts with: {ANTHROPIC_API_KEY[:10]}...")

    # Paths
    script_dir = Path(__file__).parent
    json_path = str(_CDM_ROOT / "pipelines/llm_terms/outputs/stage1_extracted_full/cdm_entities_extracted_copy_fixed.json")
    terms_path = script_dir / "terms.csv"

    # Start time
    start_time = datetime.now()

    # Load or create terms
    if not terms_path.exists():
        terms = load_terms_from_json(json_path)
    else:
        with open(terms_path, 'r') as f:
            terms = [line.strip() for line in f if line.strip()]

    logging.info(f"Loaded {len(terms)} terms")

    # Load checkpoint
    checkpoint = load_checkpoint(CHECKPOINT_FILE)
    processed_terms = checkpoint.get("processed_terms", [])
    last_index = checkpoint.get("last_term_index", -1)

    logging.info(f"Resuming from term index {last_index + 1}")

    # Initialize Anthropic client
    client = anthropic.Anthropic(
        api_key=ANTHROPIC_API_KEY,
        base_url=ANTHROPIC_BASE_URL
    )

    # Process remaining terms
    remaining_terms = terms[last_index + 1:]

    for i, term in enumerate(tqdm(remaining_terms, desc="Processing terms")):
        current_index = last_index + 1 + i

        try:
            # Extract relations
            edges = extract_relations_for_term(
                term, terms, client, current_index, len(terms)
            )

            # Verify PMIDs and write edges
            for edge in edges:
                verified_edge = verify_pmids_for_edge(edge)
                write_edge_to_jsonl(verified_edge)

            # Update checkpoint
            processed_terms.append(term)
            save_checkpoint(CHECKPOINT_FILE, processed_terms, current_index)

        except Exception as e:
            logging.error(f"Failed to process term '{term}': {e}")
            continue

    # End time
    end_time = datetime.now()

    # Load all edges for final processing
    all_edges = []
    if os.path.exists(EDGES_JSONL):
        with open(EDGES_JSONL, 'r') as f:
            for line in f:
                all_edges.append(json.loads(line))

    # Deduplicate
    all_edges = deduplicate_edges(all_edges)

    # Create graph
    G = create_graph_from_edges(all_edges)

    # Export to CSV and GraphML
    export_to_csv(all_edges)
    export_to_graphml(G)

    # Compute and save summary
    summary = compute_summary(all_edges, G)
    save_summary(summary)

    # Save run metadata
    save_run_metadata(
        str(terms_path),
        start_time,
        end_time,
        len(terms),
        len(all_edges)
    )

    logging.info(f"Completed! Total edges: {len(all_edges)}")
    print(f"\n{'='*60}")
    print(f"KNOWLEDGE GRAPH BUILDER COMPLETED")
    print(f"{'='*60}")
    print(f"Total edges found: {len(all_edges)}")
    print(f"Output files: {EDGES_JSONL}, {EDGES_CSV}, {GRAPHML_FILE}")
    print(f"Metadata: {METADATA_FILE}")
    print(f"Summary: {SUMMARY_FILE}")


if __name__ == "__main__":
    main()
