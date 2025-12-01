#!/usr/bin/env python3
"""
Quick Consolidation Script
====================
Creates a simple consolidated output from existing pipeline results.
Extracts: term, score, context, category, file_name, mapping information
"""

import json
import os
from pathlib import Path
from datetime import datetime

def consolidate_results(input_dir: str, output_file: str):
    """Consolidate all model results into single file"""
    input_path = Path(input_dir)
    all_terms = []
    processed_files = set()
    term_counts = {}

    print(f"🔍 Scanning for results in: {input_path}")

    # Find all JSON files
    json_files = list(input_path.rglob("*results.json"))
    print(f"📁 Found {len(json_files)} result files")

    for file_path in json_files:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # Extract file info from filename
            filename = file_path.stem
            if '_' in filename:
                original_file = '_'.join(filename.split('_')[:-2])  # Remove model and _results parts
            else:
                original_file = filename

            print(f"📄 Processing: {file_path.name} -> {original_file}")

            # Process extracted terms
            extracted_terms = data.get('extracted_terms', [])
            for term_info in extracted_terms:
                # Basic info
                term = term_info.get('term', '')
                if not term:
                    continue

                # Skip if we've seen this exact term from this file
                term_key = f"{term}_{original_file}"
                if term_key in processed_files:
                    continue
                processed_files.add(term_key)

                # Count term occurrences
                term_counts[term] = term_counts.get(term, 0) + 1

                # Extract information
                consolidated_info = {
                    'term': term,
                    'score': float(term_info.get('relevance_score', term_info.get('confidence', 0.5))),
                    'context': term_info.get('sentence_context', ''),
                    'category': term_info.get('label', term_info.get('entity_type', 'UNKNOWN')),
                    'file_name': original_file,
                    'start_char': int(term_info.get('start_char', 0)),
                    'end_char': int(term_info.get('end_char', 0)),
                    'section_context': term_info.get('section_context', ''),
                    'extraction_timestamp': term_info.get('extraction_timestamp', datetime.now().isoformat()),
                    'model': file_path.parent.name,  # Which model found this term
                    'count': term_counts[term]  # How many times this term appears across all files
                }

                # Add mapping information if available
                if 'mapping' in term_info and term_info['mapping']:
                    mapping = term_info['mapping']
                    consolidated_info['mapping'] = {
                        'cui': mapping.get('cui', ''),
                        'semantic_type': mapping.get('semantic_type', ''),
                        'definition': mapping.get('definition', ''),
                        'synonyms': mapping.get('synonyms', [])
                    }

                # Add BioMistral validation if available
                if 'biomistral_validation' in term_info:
                    validation = term_info['biomistral_validation']
                    consolidated_info['biomistral'] = {
                        'is_valid': validation.get('is_valid', False),
                        'confidence': validation.get('confidence', 0.0),
                        'explanation': validation.get('explanation', '')
                    }

                all_terms.append(consolidated_info)

        except Exception as e:
            print(f"❌ Error processing {file_path.name}: {e}")
            continue

    # Remove duplicates while preserving best scores
    print(f"🔄 Removing duplicates from {len(all_terms)} terms...")
    unique_terms = {}
    for term_info in all_terms:
        term = term_info['term']
        if term not in unique_terms or term_info['score'] > unique_terms[term]['score']:
            unique_terms[term] = term_info

    final_terms = list(unique_terms.values())
    print(f"✅ Final count: {len(final_terms)} unique terms")

    # Create consolidated output
    consolidated_data = {
        'metadata': {
            'total_files_processed': len(set([t['file_name'] for t in final_terms])),
            'total_terms_extracted': len(all_terms),
            'total_terms_final': len(final_terms),
            'models_used': sorted(list(set([t['model'] for t in final_terms]))),
            'extraction_timestamp': datetime.now().isoformat(),
            'pipeline_version': 'standalone_scispacy_v1.0',
            'features_enabled': ['BioMistral', 'MiniLM', 'UMLS', 'Advanced_Deduplication']
        },
        'all_terms': final_terms
    }

    # Save consolidated results
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(consolidated_data, f, indent=2, ensure_ascii=False)

    print(f"💾 Saved consolidated results to: {output_path}")
    print(f"📊 Summary: {len(final_terms)} unique terms from {len(set([t['file_name'] for t in final_terms]))} files")

    return consolidated_data

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Quick consolidation of pipeline results")
    parser.add_argument("--input_dir", required=True, help="Directory containing model result files")
    parser.add_argument("--output_file", required=True, help="Output consolidated JSON file")

    args = parser.parse_args()

    consolidate_results(args.input_dir, args.output_file)