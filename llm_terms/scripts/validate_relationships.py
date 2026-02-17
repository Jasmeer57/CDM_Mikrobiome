#!/usr/bin/env python3
"""
Validate Relationship Context Alignment
===================================
This script validates that relationships have proper context alignment:
- The source_entity and target_entity must appear in source_context
- The evidence should be supported by the source_context

Usage:
    python3 validate_relationships.py
    python3 validate_relationships.py --input relationships/cdm_relationships.json --output validation_report.json
"""
import json
import re
import argparse
from pathlib import Path
from typing import List, Dict, Tuple
from collections import defaultdict

def check_word_boundary(term: str, text: str) -> bool:
    """Check if term appears in text with word boundaries."""
    # Handle multi-word terms and special characters
    pattern = r'\b' + re.escape(term.lower()) + r'\b'
    return re.search(pattern, text.lower()) is not None


def validate_relationship(rel: Dict) -> Dict:
    """Validate a single relationship for context alignment."""
    issues = []

    source_entity = rel.get('source_entity', '')
    target_entity = rel.get('target_entity', '')
    source_context = rel.get('source_context', '')
    evidence = rel.get('evidence', '')

    # Check 1: Source entity must appear in context
    if not check_word_boundary(source_entity, source_context):
        issues.append({
            'type': 'SOURCE_NOT_IN_CONTEXT',
            'severity': 'CRITICAL',
            'message': f"Source entity '{source_entity}' does not appear in source_context"
        })

    # Check 2: Target entity must appear in context
    if not check_word_boundary(target_entity, source_context):
        issues.append({
            'type': 'TARGET_NOT_IN_CONTEXT',
            'severity': 'CRITICAL',
            'message': f"Target entity '{target_entity}' does not appear in source_context"
        })

    # Check 3: Evidence should reference entities
    evidence_lower = evidence.lower()
    if source_entity.lower() not in evidence_lower and target_entity.lower() not in evidence_lower:
        issues.append({
            'type': 'EVIDENCE_MISMATCH',
            'severity': 'WARNING',
            'message': f"Evidence does not mention source or target entity"
        })

    # Check 4: Evidence should be found in context
    if evidence and len(evidence) > 10:  # Only check if evidence is substantial
        # Extract key phrases from evidence (remove common words)
        evidence_words = set(re.findall(r'\w{3,}', evidence.lower()))
        context_words = set(re.findall(r'\w{3,}', source_context.lower()))

        # Check if at least some evidence words appear in context
        overlap = len(evidence_words & context_words)
        if overlap < len(evidence_words) * 0.3:  # At least 30% overlap
            issues.append({
                'type': 'EVIDENCE_CONTEXT_MISMATCH',
                'severity': 'CRITICAL',
                'message': f"Evidence does not appear to be from source_context (only {overlap}/{len(evidence_words)} words overlap)"
            })

    return {
        'relationship': {
            'source_entity': source_entity,
            'target_entity': target_entity,
            'relationship_type': rel.get('relationship_type', ''),
            'paper_id': rel.get('paper_id', ''),
        },
        'valid': len([i for i in issues if i['severity'] == 'CRITICAL']) == 0,
        'issues': issues
    }


def main():
    parser = argparse.ArgumentParser(description="Validate relationship context alignment")
    parser.add_argument("--input", default="relationships/cdm_relationships.json",
                        help="Path to relationships JSON file")
    parser.add_argument("--output", default="validation_report.json",
                        help="Path to validation report JSON")
    args = parser.parse_args()

    print("=" * 70)
    print("RELATIONSHIP CONTEXT ALIGNMENT VALIDATION")
    print("=" * 70)

    # Load relationships
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"ERROR: File not found: {args.input}")
        return

    print(f"\nLoading relationships from {args.input}")
    with open(input_path, 'r') as f:
        data = json.load(f)
        relationships = data.get('relationships', [])

    print(f"Loaded {len(relationships)} relationships")

    # Validate each relationship
    print("\nValidating context alignment...")
    results = []
    critical_count = 0
    valid_count = 0

    for i, rel in enumerate(relationships):
        result = validate_relationship(rel)
        results.append(result)

        if result['valid']:
            valid_count += 1
        else:
            critical_count += 1

        # Progress update
        if (i + 1) % 100 == 0:
            print(f"  Progress: {i+1}/{len(relationships)} validated ({valid_count} valid)")

    # Calculate statistics
    total = len(results)
    valid_pct = 100 * valid_count / total if total > 0 else 0
    invalid_pct = 100 * critical_count / total if total > 0 else 0

    # Group issues by type
    issue_counts = defaultdict(int)
    for result in results:
        for issue in result['issues']:
            issue_counts[issue['type']] += 1

    # Print summary
    print("\n" + "=" * 70)
    print("VALIDATION SUMMARY")
    print("=" * 70)
    print(f"Total relationships:       {total}")
    print(f"Valid (proper alignment):  {valid_count} ({valid_pct:.1f}%)")
    print(f"Invalid (misalignment):    {critical_count} ({invalid_pct:.1f}%)")
    print()
    print("Issue breakdown:")
    for issue_type, count in sorted(issue_counts.items(), key=lambda x: x[1], reverse=True):
        print(f"  {issue_type:35s} {count:4d}")

    # Save report
    report = {
        'summary': {
            'total_relationships': total,
            'valid_count': valid_count,
            'invalid_count': critical_count,
            'valid_percentage': round(valid_pct, 2),
            'invalid_percentage': round(invalid_pct, 2)
        },
        'issue_counts': dict(issue_counts),
        'detailed_results': results
    }

    with open(args.output, 'w') as f:
        json.dump(report, f, indent=2)

    print(f"\nDetailed report saved to: {args.output}")

    # Show sample of invalid relationships
    invalid_results = [r for r in results if not r['valid']]
    if invalid_results:
        print("\n" + "=" * 70)
        print("SAMPLE OF INVALID RELATIONSHIPS (first 5)")
        print("=" * 70)
        for i, result in enumerate(invalid_results[:5]):
            rel = result['relationship']
            print(f"\n[{i+1}] {rel['source_entity']} -> {rel['target_entity']} ({rel['relationship_type']})")
            for issue in result['issues']:
                print(f"    {issue['severity']}: {issue['message']}")

    print("\n" + "=" * 70)
    if critical_count > 0:
        print("⚠️  CONTEXT ALIGNMENT ISSUES DETECTED!")
        print("   The relationships file has systematic misalignment issues.")
        print("   Recommendation: Re-run relationship extraction with fixed code.")
        print("   Command: python3 rebuild_relationships_fixed.py")
    else:
        print("✅ ALL RELATIONSHIPS PASSED VALIDATION!")
    print("=" * 70)


if __name__ == "__main__":
    main()
