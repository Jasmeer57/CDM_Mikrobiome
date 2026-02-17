#!/usr/bin/env python3
"""
Resume Relationship Extraction from Checkpoint
================================================
This script resumes relationship extraction from an existing checkpoint,
skipping entities that have already been processed as sources.

Usage:
    python3 resume_relationship_extraction.py
    python3 resume_relationship_extraction.py --batch-size 100 --max-relationships 100000
"""
import json
import logging
import argparse
from pathlib import Path
from tqdm import tqdm

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from core.llm_client import LLMClient
from core.relationship_extractor import RelationshipExtractor

def main():
    parser = argparse.ArgumentParser(description="Resume relationship extraction from checkpoint")
    parser.add_argument("--input", default="outputs/stage1_extracted_full/cdm_entities_extracted.json",
                        help="Path to entities JSON file")
    parser.add_argument("--relationships", default="outputs/relationships/cdm_relationships.json",
                        help="Path to existing relationships file (checkpoint)")
    parser.add_argument("--output", default="outputs/relationships/cdm_relationships_full.json",
                        help="Output path for merged relationships")
    parser.add_argument("--model", default="qwen3:8b", help="LLM model to use")
    parser.add_argument("--base-url", default="http://127.0.0.1:11434/api", help="LLM API base URL")
    parser.add_argument("--min-confidence", type=float, default=0.6, help="Minimum confidence threshold")
    parser.add_argument("--batch-size", type=int, default=50, help="Entities per batch")
    parser.add_argument("--max-relationships", type=int, default=50000, help="Maximum new relationships to extract")
    args = parser.parse_args()

    print("=" * 70)
    print("RESUMING RELATIONSHIP EXTRACTION FROM CHECKPOINT")
    print("=" * 70)

    # Load existing relationships
    print(f"\nLoading existing relationships from {args.relationships}")
    with open(args.relationships, 'r') as f:
        rel_data = json.load(f)
        existing_relationships = rel_data.get('relationships', [])

    print(f"Found {len(existing_relationships)} existing relationships")

    # Get entities that have already been processed as sources
    processed_sources = set(r.get('source_entity', '').lower() for r in existing_relationships)
    print(f"Already processed {len(processed_sources)} unique source entities")

    # Load all entities
    print(f"\nLoading entities from {args.input}")
    with open(args.input, 'r') as f:
        data = json.load(f)
        all_entities = data.get('results', [])

    print(f"Loaded {len(all_entities)} total entities")

    # Filter entities with context
    entities_with_context = [
        e for e in all_entities
        if e.get('confidence_score', e.get('confidence', 0)) >= args.min_confidence
        and e.get('contextual_definition', '').strip()
        and len(e.get('term', '')) >= 2
    ]

    print(f"Entities with context (confidence >= {args.min_confidence}): {len(entities_with_context)}")

    # Find unprocessed entities
    unprocessed_entities = [
        e for e in entities_with_context
        if e.get('term', '').lower() not in processed_sources
    ]

    print(f"\n" + "=" * 70)
    print("CHECKPOINT SUMMARY")
    print("=" * 70)
    print(f"Total entities with context: {len(entities_with_context)}")
    print(f"Already processed as sources: {len(processed_sources)}")
    print(f"Remaining to process: {len(unprocessed_entities)}")
    print(f"Percent complete: {len(processed_sources) / len(entities_with_context) * 100:.1f}%")
    print(f"Batches remaining: {len(unprocessed_entities) // args.batch_size}")
    print("=" * 70)

    if len(unprocessed_entities) == 0:
        print("\nNo entities remaining to process!")
        return

    # Initialize LLM
    print(f"\nConnecting to LLM: {args.base_url}")
    llm_client = LLMClient(model=args.model, base_url=args.base_url)

    if not llm_client.is_available():
        print("ERROR: LLM not available!")
        return

    print("LLM connected successfully")

    # Extract relationships from unprocessed entities
    print(f"\nExtracting relationships from {len(unprocessed_entities)} unprocessed entities...")
    extractor = RelationshipExtractor(llm_client, min_confidence=args.min_confidence)

    # Process in batches
    new_relationships = []
    num_batches = (len(unprocessed_entities) + args.batch_size - 1) // args.batch_size
    max_batches = min(num_batches, args.max_relationships // args.batch_size)

    for batch_idx in tqdm(range(max_batches), desc="Processing batches"):
        start_idx = batch_idx * args.batch_size
        end_idx = min(start_idx + args.batch_size, len(unprocessed_entities))
        batch_entities = unprocessed_entities[start_idx:end_idx]

        # Extract relationships from batch context
        batch_relationships = extractor._extract_relationships_from_batch(
            batch_entities,
            paper_id=f"batch_{batch_idx}"
        )

        new_relationships.extend(batch_relationships)

        # Progress check
        if (batch_idx + 1) % 10 == 0:
            print(f"Progress: {len(new_relationships)} new relationships from {batch_idx+1} batches")

        # Check if we've hit the max
        if len(new_relationships) >= args.max_relationships:
            print(f"Reached maximum of {args.max_relationships} new relationships")
            break

    print(f"\nExtracted {len(new_relationships)} new relationships")

    # Convert existing relationship dicts to EntityRelationship objects
    from core.relationship_extractor import EntityRelationship
    from dataclasses import astuple

    existing_as_objects = []
    for rel_dict in existing_relationships:
        try:
            existing_as_objects.append(EntityRelationship(**rel_dict))
        except Exception as e:
            logger.debug(f"Could not convert relationship: {e}")
            continue

    # Merge with existing relationships
    all_relationships = existing_as_objects + new_relationships

    # Deduplicate
    print("\nDeduplicating relationships...")
    unique_relationships = extractor._deduplicate_relationships(all_relationships)
    print(f"After deduplication: {len(unique_relationships)} relationships")

    # Save
    print(f"\nSaving {len(unique_relationships)} relationships to {args.output}")
    extractor.save_relationships(unique_relationships, args.output)

    # Generate summary
    summary = extractor.generate_relationship_summary(unique_relationships)
    print("\n" + "=" * 70)
    print("RELATIONSHIP SUMMARY")
    print("=" * 70)
    print(f"Total relationships:        {summary.get('total_relationships', 0)}")
    print(f"Unique entity pairs:        {summary.get('unique_entity_pairs', 0)}")
    print(f"Average confidence:         {summary.get('average_confidence', 0):.3f}")

    print("\nTop relationship types:")
    for rel_type, count in sorted(
        summary.get('relationship_type_distribution', {}).items(),
        key=lambda x: x[1], reverse=True
    )[:15]:
        print(f"  {rel_type:30s} {count:4d}")

    print("\n" + "=" * 70)
    print("EXTRACTION COMPLETE")
    print("=" * 70)

if __name__ == "__main__":
    main()
