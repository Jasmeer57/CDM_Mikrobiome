#!/usr/bin/env python3
"""
Simple quality test script to demonstrate the pipeline functionality
without complex import dependencies.
"""

import os
import sys
import json
import logging
from pathlib import Path
import time
import spacy
import re
from collections import Counter

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class SimpleTermExtractor:
    """Simple term extractor for testing."""

    def __init__(self):
        self.nlp = None
        self._load_models()

    def _load_models(self):
        """Load available sciSpaCy models."""
        models_to_try = [
            'en_ner_bc5cdr_md',
            'en_ner_craft_md',
            'en_core_sci_lg',
            'en_ner_jnlpba_md'
        ]

        for model_name in models_to_try:
            try:
                self.nlp = spacy.load(model_name)
                logger.info(f"✅ Loaded model: {model_name}")
                return
            except OSError:
                logger.warning(f"⚠️  Model {model_name} not available")

        # Fallback to basic English model
        try:
            self.nlp = spacy.load("en_core_web_sm")
            logger.info("✅ Fallback: Loaded basic English model")
        except OSError:
            logger.error("❌ No spaCy models available")
            raise

    def extract_terms(self, text, min_frequency=1):
        """Extract terms from text using spaCy."""
        doc = self.nlp(text)

        # Extract entities
        entities = []
        for ent in doc.ents:
            # Filter for relevant entity types
            if ent.label_ in ['DISEASE', 'CHEMICAL', 'ORGANISM', 'ANATOMY', 'PHYSIOLOGY']:
                entities.append({
                    'term': ent.text,
                    'label': ent.label_,
                    'start': ent.start_char,
                    'end': ent.end_char
                })

        # Extract noun phrases for additional terms
        noun_phrases = []
        for chunk in doc.noun_chunks:
            if len(chunk.text.split()) >= 2:  # Multi-word phrases
                noun_phrases.append({
                    'term': chunk.text,
                    'label': 'NOUN_PHRASE',
                    'start': chunk.start_char,
                    'end': chunk.end_char
                })

        # Combine and clean terms
        all_terms = entities + noun_phrases

        # Basic filtering
        filtered_terms = []
        for term_info in all_terms:
            term = term_info['term']

            # Skip very short or very long terms
            if len(term) < 3 or len(term) > 50:
                continue

            # Skip common words
            if term.lower() in ['the', 'and', 'for', 'with', 'are', 'was', 'been', 'have', 'has']:
                continue

            # Skip numbers and dates
            if re.match(r'^\d+$', term):
                continue

            filtered_terms.append(term_info)

        # Count frequencies and create final results
        term_counts = Counter([term_info['term'] for term_info in filtered_terms])

        final_terms = []
        for term_info in filtered_terms:
            term = term_info['term']
            frequency = term_counts[term]

            # Calculate simple score based on length and entity type
            score = len(term.split())  # Multi-word terms get higher scores
            if term_info['label'] in ['DISEASE', 'CHEMICAL', 'ORGANISM']:
                score *= 2

            final_terms.append({
                'term': term,
                'label': term_info['label'],
                'frequency': frequency,
                'score': score,
                'examples': [text[max(0, term_info['start']-50):term_info['end']+50]]
            })

        # Remove duplicates
        unique_terms = {}
        for term_info in final_terms:
            term = term_info['term'].lower()
            if term not in unique_terms or term_info['score'] > unique_terms[term]['score']:
                unique_terms[term] = term_info

        # Sort by score
        sorted_terms = sorted(unique_terms.values(), key=lambda x: x['score'], reverse=True)

        return sorted_terms

class QualityAnalyzer:
    """Analyze quality of extracted terms."""

    def __init__(self):
        self.expected_microbiome_terms = {
            'microbiome', 'gut microbiome', 'bacterial diversity', 'microorganisms',
            'firmicutes', 'bacteroidetes', 'actinobacteria', 'proteobacteria',
            'lactobacillus', 'bifidobacterium', 'clostridioides difficile',
            'inflammatory bowel disease', 'crohn\'s disease', 'ulcerative colitis',
            'irritable bowel syndrome', 'obesity', 'metabolic syndrome', 'dysbiosis',
            'short-chain fatty acids', 'butyrate', 'propionate', 'acetate',
            'inulin', 'fructooligosaccharides', 'galactooligosaccharides',
            'fecal microbiota transplantation', 'gut-brain axis', 'probiotic',
            'prebiotic', 'antibiotic', 'metagenomic', 'metabolomic'
        }

    def analyze_quality(self, extracted_terms):
        """Analyze quality of extracted terms."""
        extracted_terms_set = set(term['term'].lower() for term in extracted_terms)

        # Calculate metrics
        true_positives = len(extracted_terms_set & self.expected_microbiome_terms)
        false_positives = len(extracted_terms_set - self.expected_microbiome_terms)
        false_negatives = len(self.expected_microbiome_terms - extracted_terms_set)

        precision = true_positives / len(extracted_terms_set) if extracted_terms_set else 0
        recall = true_positives / len(self.expected_microbiome_terms)
        f1_score = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0

        # Categorize terms
        relevant_terms = list(extracted_terms_set & self.expected_microbiome_terms)
        irrelevant_terms = list(extracted_terms_set - self.expected_microbiome_terms)
        missed_terms = list(self.expected_microbiome_terms - extracted_terms_set)

        # Manual quality assessment
        high_quality = []
        medium_quality = []
        low_quality = []

        for term_info in extracted_terms[:30]:  # Analyze top 30 terms
            term = term_info['term'].lower()

            if any(keyword in term for keyword in [
                'bacteroid', 'firmicut', 'lactobacil', 'bifidobact',
                'microbi', 'dysbios', 'probiot', 'prebiot', 'metabol',
                'inflammation', 'gastrointestin', 'colitis', 'crohn'
            ]) or term in self.expected_microbiome_terms:
                high_quality.append(term_info['term'])
            elif any(keyword in term for keyword in [
                'bacter', 'micro', 'immune', 'therapy', 'disease',
                'syndrome', 'enzyme', 'protein'
            ]):
                medium_quality.append(term_info['term'])
            elif len(term_info['term']) <= 3:
                low_quality.append(term_info['term'])

        return {
            'metrics': {
                'total_terms': len(extracted_terms),
                'unique_terms': len(extracted_terms_set),
                'precision': precision,
                'recall': recall,
                'f1_score': f1_score,
                'true_positives': true_positives,
                'false_positives': false_positives,
                'false_negatives': false_negatives
            },
            'categories': {
                'relevant_terms': relevant_terms,
                'irrelevant_terms': irrelevant_terms[:20],
                'missed_terms': missed_terms
            },
            'quality_assessment': {
                'high_quality': high_quality,
                'medium_quality': medium_quality,
                'low_quality': low_quality
            },
            'top_terms': [term['term'] for term in extracted_terms[:15]]
        }

def main():
    """Main function to run the quality test."""
    logger.info("🚀 Starting simple pipeline quality test...")

    # Read sample file
    sample_file = "data/sample_microbiome.txt"
    if not os.path.exists(sample_file):
        logger.error(f"❌ Sample file not found: {sample_file}")
        return

    with open(sample_file, 'r', encoding='utf-8') as f:
        text = f.read()

    logger.info(f"📄 Loaded sample text ({len(text)} characters)")

    # Extract terms
    start_time = time.time()
    extractor = SimpleTermExtractor()
    extracted_terms = extractor.extract_terms(text, min_frequency=1)
    extraction_time = time.time() - start_time

    logger.info(f"✅ Extracted {len(extracted_terms)} terms in {extraction_time:.2f} seconds")

    # Analyze quality
    analyzer = QualityAnalyzer()
    quality_results = analyzer.analyze_quality(extracted_terms)

    # Generate report
    report = []
    report.append("=" * 80)
    report.append("MICROBIOME TERM EXTRACTION - QUALITY ANALYSIS REPORT")
    report.append("=" * 80)
    report.append("")

    # Summary
    report.append("📊 SUMMARY")
    report.append("-" * 40)
    report.append(f"Processing Time: {extraction_time:.2f} seconds")
    report.append(f"Total Terms Extracted: {quality_results['metrics']['total_terms']}")
    report.append(f"Unique Terms: {quality_results['metrics']['unique_terms']}")
    report.append("")

    # Quality metrics
    metrics = quality_results['metrics']
    report.append("🎯 QUALITY METRICS")
    report.append("-" * 40)
    report.append(f"Precision: {metrics['precision']:.1%}")
    report.append(f"Recall: {metrics['recall']:.1%}")
    report.append(f"F1 Score: {metrics['f1_score']:.1%}")
    report.append(f"True Positives: {metrics['true_positives']}")
    report.append(f"False Positives: {metrics['false_positives']}")
    report.append(f"False Negatives: {metrics['false_negatives']}")
    report.append("")

    # Top terms
    report.append("🔝 TOP EXTRACTED TERMS")
    report.append("-" * 40)
    for i, term in enumerate(quality_results['top_terms'], 1):
        report.append(f"{i:2d}. {term}")
    report.append("")

    # Quality assessment
    qa = quality_results['quality_assessment']
    report.append("✨ QUALITY ASSESSMENT")
    report.append("-" * 40)
    report.append(f"High Quality Terms: {len(qa['high_quality'])}")
    report.append(f"Medium Quality Terms: {len(qa['medium_quality'])}")
    report.append(f"Low Quality Terms: {len(qa['low_quality'])}")

    if qa['high_quality']:
        report.append("\n🌟 High Quality Examples:")
        for term in qa['high_quality'][:10]:
            report.append(f"  • {term}")

    if qa['low_quality']:
        report.append("\n⚠️  Low Quality Examples:")
        for term in qa['low_quality'][:5]:
            report.append(f"  • {term}")
    report.append("")

    # Relevant terms
    relevant = quality_results['categories']['relevant_terms']
    report.append("✅ RELEVANT MICROBIOME TERMS")
    report.append("-" * 40)
    report.append(f"Found {len(relevant)} relevant microbiome terms:")
    for term in sorted(relevant)[:15]:
        report.append(f"  • {term}")
    report.append("")

    # Missed terms
    missed = quality_results['categories']['missed_terms']
    if missed:
        report.append("❌ MISSED EXPECTED TERMS")
        report.append("-" * 40)
        for term in sorted(missed)[:10]:
            report.append(f"  • {term}")
    report.append("")

    # Analysis and recommendations
    report.append("💡 ANALYSIS & RECOMMENDATIONS")
    report.append("-" * 40)

    precision = metrics['precision']
    recall = metrics['recall']

    if precision > 0.7 and recall > 0.7:
        report.append("🎉 EXCELLENT: The pipeline is extracting high-quality microbiome terms!")
    elif precision > 0.5 and recall > 0.5:
        report.append("✅ GOOD: The pipeline is performing reasonably well.")
    else:
        report.append("⚠️  NEEDS IMPROVEMENT: Consider the following:")

    if precision < 0.5:
        report.append("  • Improve filtering to reduce false positives")
        report.append("  • Better entity recognition models")
    if recall < 0.5:
        report.append("  • Expand microbiome seed terms")
        report.append("  • Add additional sciSpaCy models")

    report.append("  • Enable UMLS mapping for standardization")
    report.append("  • Add AI cleaning for term correction")
    report.append("")

    report.append("=" * 80)
    report.append("END OF REPORT")
    report.append("=" * 80)

    # Print report
    print("\n".join(report))

    # Save results
    output_dir = Path("data/test_output")
    output_dir.mkdir(parents=True, exist_ok=True)

    results = {
        'extraction_time': extraction_time,
        'extracted_terms': extracted_terms,
        'quality_analysis': quality_results,
        'report': "\n".join(report)
    }

    with open(output_dir / "simple_quality_test_results.json", 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, default=str)

    with open(output_dir / "simple_quality_report.txt", 'w', encoding='utf-8') as f:
        f.write("\n".join(report))

    logger.info(f"📁 Results saved to {output_dir}")

    return results

if __name__ == "__main__":
    main()