#!/usr/bin/env python3
"""Debug script to test deduplication step by step"""

import sys
sys.path.insert(0, '/home/jkalra/Documents/CDM/spacy_terms/src')

from modules.deduplication import ComprehensiveDeduplicator
from config.settings import DeduplicationConfig
import json

# Load the current output to see what terms we're working with
def load_current_terms():
    """Load terms from current output"""
    import csv
    terms = []
    try:
        with open('/home/jkalra/Documents/CDM/spacy_terms/output/scispacy_comprehensive_20251118_200734', 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get('term'):  # Only include rows with term data
                    terms.append({
                        'term': row.get('term', ''),
                        'canonical': row.get('canonical', ''),
                        'label': row.get('label', ''),
                        'confidence': float(row.get('confidence', 0.0)),
                        'science_score': float(row.get('science_score', 0.0)),
                        'model': row.get('model', ''),
                        'context': row.get('context', '')
                    })
    except Exception as e:
        print(f"Error loading terms: {e}")
        return []

    return terms

def test_deduplication():
    """Test deduplication step by step"""
    print("🔍 DEBUGGING DEDUPLICATION")
    print("=" * 50)

    # Load current terms
    terms = load_current_terms()
    print(f"Loaded {len(terms)} terms from output file")

    # Check for exact duplicates in 'term' field
    term_counts = {}
    for term in terms:
        term_text = term['term']
        if term_text not in term_counts:
            term_counts[term_text] = []
        term_counts[term_text].append(term)

    exact_duplicates = {k: v for k, v in term_counts.items() if len(v) > 1}
    print(f"\n❌ FOUND {len(exact_duplicates)} EXACT DUPLICATES IN 'term' FIELD:")
    for term_text, duplicates in list(exact_duplicates.items())[:5]:
        print(f"  '{term_text}': {len(duplicates)} occurrences")

    # Check for exact duplicates in 'canonical' field
    canon_counts = {}
    for term in terms:
        canon_text = term['canonical']
        if canon_text not in canon_counts:
            canon_counts[canon_text] = []
        canon_counts[canon_text].append(term)

    canon_duplicates = {k: v for k, v in canon_counts.items() if len(v) > 1}
    print(f"\n❌ FOUND {len(canon_duplicates)} EXACT DUPLICATES IN 'canonical' FIELD:")
    for canon_text, duplicates in list(canon_duplicates.items())[:5]:
        print(f"  '{canon_text}': {len(duplicates)} occurrences")

    # Test the deduplication pipeline
    print(f"\n🧪 TESTING DEDUPLICATION PIPELINE")
    print(f"Input terms: {len(terms)}")

    config = DeduplicationConfig()
    deduplicator = ComprehensiveDeduplicator(config)

    # Layer 1: Exact deduplication
    print(f"\n1️⃣ EXACT DEDUPLICATION:")
    exact_terms = deduplicator.exact_deduplication(terms)
    print(f"   Input: {len(terms)} -> Output: {len(exact_terms)}")

    # Check for remaining exact duplicates
    remaining_term_counts = {}
    for term in exact_terms:
        term_text = term['term']
        if term_text not in remaining_term_counts:
            remaining_term_counts[term_text] = []
        remaining_term_counts[term_text].append(term)

    remaining_duplicates = {k: v for k, v in remaining_term_counts.items() if len(v) > 1}
    print(f"   Remaining exact duplicates: {len(remaining_duplicates)}")

    # Layer 2: Fuzzy deduplication
    print(f"\n2️⃣ FUZZY DEDUPLICATION:")
    fuzzy_terms = deduplicator.fuzzy_deduplication(exact_terms)
    print(f"   Input: {len(exact_terms)} -> Output: {len(fuzzy_terms)}")

    # Layer 3: Semantic deduplication
    print(f"\n3️⃣ SEMANTIC DEDUPLICATION:")
    semantic_terms = deduplicator.semantic_deduplication(fuzzy_terms)
    print(f"   Input: {len(fuzzy_terms)} -> Output: {len(semantic_terms)}")

    # Final result
    print(f"\n🎯 FINAL RESULT:")
    print(f"   Original: {len(terms)} terms")
    print(f"   Final: {len(semantic_terms)} terms")
    print(f"   Reduction: {((len(terms) - len(semantic_terms)) / len(terms) * 100):.1f}%")

    # Save final deduplicated terms
    output_file = '/home/jkalra/Documents/CDM/spacy_terms/debug_deduplicated_terms.json'
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(semantic_terms, f, indent=2, ensure_ascii=False)
    print(f"\n💾 Saved deduplicated terms to: {output_file}")

if __name__ == "__main__":
    test_deduplication()