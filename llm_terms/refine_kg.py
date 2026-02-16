#!/usr/bin/env python3
"""
Knowledge Graph Refinement Script
================================
Refines an existing knowledge graph by:
1. Canonicalizing entities (merging duplicates, normalizing types)
2. Validating relationships (type constraints, evidence typing)
3. Filtering noise nodes (instruments, software versions, etc.)
4. Adding subgraph labels (mechanism/microbiome_metabolite/methods_provenance)
5. Adding formal scope statement

Usage:
    python refine_kg.py --kg <path_to_kg> --relationships <path_to_relationships> --output <output_path>

Example:
    python refine_kg.py \\
        --kg knowledge_graph/cdm_kg.json \\
        --relationships relationships/cdm_relationships.json \\
        --output knowledge_graph/cdm_kg_refined.json
"""

import argparse
import json
import logging
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Import refiner
from core.kg_refiner import refine_kg_from_files


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description='Refine a knowledge graph by canonicalizing entities, '
                    'validating relationships, and filtering noise.'
    )

    parser.add_argument(
        '--kg',
        type=str,
        required=True,
        help='Path to existing KG JSON file'
    )

    parser.add_argument(
        '--relationships',
        type=str,
        required=True,
        help='Path to relationships JSON file'
    )

    parser.add_argument(
        '--output',
        type=str,
        default='knowledge_graph/cdm_kg_refined.json',
        help='Path to save refined KG (default: knowledge_graph/cdm_kg_refined.json)'
    )

    parser.add_argument(
        '--min-entity-confidence',
        type=float,
        default=0.4,
        help='Minimum confidence for entities (default: 0.4)'
    )

    parser.add_argument(
        '--min-rel-confidence',
        type=float,
        default=0.5,
        help='Minimum confidence for relationships (default: 0.5)'
    )

    parser.add_argument(
        '--keep-biological-only',
        action='store_true',
        help='Filter to core biological types only (removes methods, software, etc.)'
    )

    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Analyze and print stats without writing output'
    )

    return parser.parse_args()


def print_statistics(summary: dict):
    """Print refinement statistics in a formatted way."""
    print("\n" + "=" * 60)
    print("KNOWLEDGE GRAPH REFINEMENT SUMMARY")
    print("=" * 60)

    # Input vs Output
    print("\nInput:")
    print(f"  Nodes: {summary['input_nodes']:,}")
    print(f"  Relationships: {summary['input_relationships']:,}")

    print("\nOutput:")
    print(f"  Nodes: {summary['output_nodes']:,}")
    print(f"  Relationships: {summary['output_relationships']:,}")

    # Reduction percentages
    node_reduction = (1 - summary['output_nodes'] / summary['input_nodes']) * 100 if summary['input_nodes'] > 0 else 0
    rel_reduction = (1 - summary['output_relationships'] / summary['input_relationships']) * 100 if summary['input_relationships'] > 0 else 0

    print(f"\nReduction:")
    print(f"  Nodes: {node_reduction:.1f}%")
    print(f"  Relationships: {rel_reduction:.1f}%")

    # Validation stats
    if 'validation_stats' in summary:
        val_stats = summary['validation_stats']
        print("\nValidation:")
        print(f"  Filtered (low confidence): {val_stats['filtered_confidence']}")
        print(f"  Filtered (invalid type pairs): {val_stats['filtered_invalid_type_pair']}")
        print(f"  Filtered (missing entities): {val_stats['filtered_missing_entities']}")

        # Evidence types
        if val_stats.get('evidence_types'):
            print("\n  Evidence Types:")
            for ev_type, count in sorted(val_stats['evidence_types'].items()):
                print(f"    {ev_type}: {count}")

        # Subgraph distribution
        if val_stats.get('subgraph_distribution'):
            print("\n  Subgraph Distribution:")
            for subgraph, count in sorted(val_stats['subgraph_distribution'].items()):
                print(f"    {subgraph}: {count}")

    # Filter stats
    if 'filter_stats' in summary:
        filter_stats = summary['filter_stats']
        print("\nFiltering:")
        print(f"  Filtered (non-biological types): {filter_stats['entities_filtered_type']}")
        print(f"  Filtered (noise nodes): {filter_stats['entities_filtered_noise']}")
        print(f"  Filtered (orphaned relationships): {filter_stats['relationships_filtered_orphaned']}")

    print("=" * 60 + "\n")


def validate_input_files(kg_path: str, rels_path: str) -> bool:
    """
    Validate that input files exist and have correct structure.

    Args:
        kg_path: Path to KG JSON file
        rels_path: Path to relationships JSON file

    Returns:
        True if valid, False otherwise
    """
    kg_file = Path(kg_path)
    rels_file = Path(rels_path)

    # Check existence
    if not kg_file.exists():
        logger.error(f"KG file not found: {kg_path}")
        return False

    if not rels_file.exists():
        logger.error(f"Relationships file not found: {rels_path}")
        return False

    # Validate structure
    try:
        with open(kg_file, 'r') as f:
            kg_data = json.load(f)

        if 'nodes' not in kg_data:
            logger.error(f"Invalid KG structure: missing 'nodes' key")
            return False

        logger.info(f"KG validation passed: {len(kg_data['nodes'])} nodes found")

    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in KG file: {e}")
        return False

    try:
        with open(rels_file, 'r') as f:
            rels_data = json.load(f)

        if 'relationships' not in rels_data:
            logger.error(f"Invalid relationships structure: missing 'relationships' key")
            return False

        logger.info(f"Relationships validation passed: {len(rels_data['relationships'])} relationships found")

    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in relationships file: {e}")
        return False

    return True


def main():
    """Main entry point."""
    args = parse_args()

    # Validate input files
    logger.info("Validating input files...")
    if not validate_input_files(args.kg, args.relationships):
        logger.error("Input validation failed. Exiting.")
        return 1

    # Create output directory if needed
    if not args.dry_run:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)

    # Run refinement
    logger.info("Starting KG refinement...")
    logger.info(f"  KG source: {args.kg}")
    logger.info(f"  Relationships source: {args.relationships}")
    logger.info(f"  Output: {args.output}")
    logger.info(f"  Min entity confidence: {args.min_entity_confidence}")
    logger.info(f"  Min relationship confidence: {args.min_rel_confidence}")
    logger.info(f"  Keep biological only: {args.keep_biological_only}")

    try:
        summary = refine_kg_from_files(
            kg_path=args.kg,
            relationships_path=args.relationships,
            output_path=args.output if not args.dry_run else None,
            min_entity_confidence=args.min_entity_confidence,
            min_rel_confidence=args.min_rel_confidence,
            keep_biological_only=args.keep_biological_only
        )

        # Print summary
        print_statistics(summary)

        if args.dry_run:
            logger.info("Dry run complete - no files written")
        else:
            logger.info(f"Refined KG saved to: {args.output}")

        return 0

    except Exception as e:
        logger.exception(f"Error during refinement: {e}")
        return 1


if __name__ == '__main__':
    import sys
    sys.exit(main())
