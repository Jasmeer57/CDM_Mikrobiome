#!/usr/bin/env python3
"""
Demo quality analysis script that simulates pipeline functionality
to demonstrate expected results and quality metrics.
"""

import json
import logging
from pathlib import Path
from collections import Counter
import time

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class MockPipelineResults:
    """Mock pipeline results to demonstrate expected functionality."""

    def __init__(self):
        # Simulated extracted terms from the sample microbiome text
        self.mock_extracted_terms = [
            {'term': 'gut microbiome', 'frequency': 8, 'score': 10.0, 'label': 'CONCEPT'},
            {'term': 'microorganisms', 'frequency': 6, 'score': 8.5, 'label': 'ORGANISM'},
            {'term': 'bacterial diversity', 'frequency': 4, 'score': 9.0, 'label': 'CONCEPT'},
            {'term': 'Firmicutes', 'frequency': 3, 'score': 9.5, 'label': 'ORGANISM'},
            {'term': 'Bacteroidetes', 'frequency': 3, 'score': 9.5, 'label': 'ORGANISM'},
            {'term': 'Actinobacteria', 'frequency': 2, 'score': 9.5, 'label': 'ORGANISM'},
            {'term': 'Proteobacteria', 'frequency': 2, 'score': 9.5, 'label': 'ORGANISM'},
            {'term': 'Lactobacillus', 'frequency': 4, 'score': 9.0, 'label': 'ORGANISM'},
            {'term': 'Bifidobacterium', 'frequency': 3, 'score': 9.0, 'label': 'ORGANISM'},
            {'term': 'Clostridioides difficile', 'frequency': 2, 'score': 9.0, 'label': 'ORGANISM'},
            {'term': 'inflammatory bowel disease', 'frequency': 5, 'score': 10.0, 'label': 'DISEASE'},
            {'term': 'IBD', 'frequency': 3, 'score': 8.0, 'label': 'DISEASE'},
            {'term': 'Crohn\'s disease', 'frequency': 2, 'score': 9.0, 'label': 'DISEASE'},
            {'term': 'ulcerative colitis', 'frequency': 2, 'score': 9.0, 'label': 'DISEASE'},
            {'term': 'irritable bowel syndrome', 'frequency': 2, 'score': 9.0, 'label': 'DISEASE'},
            {'term': 'IBS', 'frequency': 1, 'score': 7.5, 'label': 'DISEASE'},
            {'term': 'obesity', 'frequency': 2, 'score': 8.5, 'label': 'DISEASE'},
            {'term': 'metabolic syndrome', 'frequency': 1, 'score': 8.5, 'label': 'DISEASE'},
            {'term': 'dysbiosis', 'frequency': 3, 'score': 9.0, 'label': 'CONCEPT'},
            {'term': 'short-chain fatty acids', 'frequency': 4, 'score': 9.5, 'label': 'CHEMICAL'},
            {'term': 'SCFAs', 'frequency': 2, 'score': 8.0, 'label': 'CHEMICAL'},
            {'term': 'butyrate', 'frequency': 3, 'score': 9.0, 'label': 'CHEMICAL'},
            {'term': 'propionate', 'frequency': 2, 'score': 8.5, 'label': 'CHEMICAL'},
            {'term': 'acetate', 'frequency': 2, 'score': 8.5, 'label': 'CHEMICAL'},
            {'term': 'probiotic', 'frequency': 4, 'score': 8.5, 'label': 'CONCEPT'},
            {'term': 'prebiotic', 'frequency': 2, 'score': 8.5, 'label': 'CONCEPT'},
            {'term': 'inulin', 'frequency': 2, 'score': 8.0, 'label': 'CHEMICAL'},
            {'term': 'fructooligosaccharides', 'frequency': 2, 'score': 9.0, 'label': 'CHEMICAL'},
            {'term': 'FOS', 'frequency': 1, 'score': 7.5, 'label': 'CHEMICAL'},
            {'term': 'galactooligosaccharides', 'frequency': 2, 'score': 9.0, 'label': 'CHEMICAL'},
            {'term': 'GOS', 'frequency': 1, 'score': 7.5, 'label': 'CHEMICAL'},
            {'term': 'metagenomic', 'frequency': 2, 'score': 8.5, 'label': 'METHOD'},
            {'term': 'fecal microbiota transplantation', 'frequency': 2, 'score': 10.0, 'label': 'TREATMENT'},
            {'term': 'FMT', 'frequency': 2, 'score': 8.0, 'label': 'TREATMENT'},
            {'term': 'gut-brain axis', 'frequency': 2, 'score': 9.5, 'label': 'CONCEPT'},
            {'term': 'antibiotic', 'frequency': 2, 'score': 8.0, 'label': 'CHEMICAL'},
            {'term': 'colonization resistance', 'frequency': 1, 'score': 9.0, 'label': 'CONCEPT'},
            {'term': 'gastrointestinal tract', 'frequency': 2, 'score': 8.5, 'label': 'ANATOMY'},
            {'term': 'commensal microorganisms', 'frequency': 1, 'score': 8.5, 'label': 'CONCEPT'},
            {'term': 'immune system', 'frequency': 2, 'score': 7.5, 'label': 'SYSTEM'},
            {'term': 'metabolism', 'frequency': 3, 'score': 7.5, 'label': 'PROCESS'},
            {'term': 'fermentation', 'frequency': 2, 'score': 8.0, 'label': 'PROCESS'},
            {'term': 'metabolites', 'frequency': 2, 'score': 7.5, 'label': 'CHEMICAL'},
            {'term': 'enzymes', 'frequency': 2, 'score': 7.0, 'label': 'PROTEIN'},
            {'term': 'microbial diversity', 'frequency': 2, 'score': 9.0, 'label': 'CONCEPT'},
            {'term': 'next-generation sequencing', 'frequency': 1, 'score': 8.5, 'label': 'METHOD'},
            {'term': 'mucosa', 'frequency': 2, 'score': 7.5, 'label': 'ANATOMY'},
            {'term': 'mucosal immune system', 'frequency': 1, 'score': 8.5, 'label': 'SYSTEM'},
            {'term': 'Toll-like receptors', 'frequency': 1, 'score': 8.5, 'label': 'PROTEIN'},
            {'term': 'NOD-like receptors', 'frequency': 1, 'score': 8.5, 'label': 'PROTEIN'},
            {'term': 'microbial-associated molecular patterns', 'frequency': 1, 'score': 9.5, 'label': 'CONCEPT'},
            {'term': 'MAMPs', 'frequency': 1, 'score': 8.0, 'label': 'CONCEPT'},
            {'term': 'tryptophan catabolites', 'frequency': 1, 'score': 9.0, 'label': 'CHEMICAL'},
            {'term': 'bile acid derivatives', 'frequency': 1, 'score': 8.5, 'label': 'CHEMICAL'},
            {'term': 'bacterial neurotransmitters', 'frequency': 1, 'score': 9.0, 'label': 'CHEMICAL'},
            {'term': 'personalized medicine', 'frequency': 1, 'score': 8.0, 'label': 'CONCEPT'}
        ]

        # Expected high-quality microbiome terms
        self.expected_terms = {
            'gut microbiome', 'microorganisms', 'bacterial diversity',
            'firmicutes', 'bacteroidetes', 'actinobacteria', 'proteobacteria',
            'lactobacillus', 'bifidobacterium', 'clostridioides difficile',
            'inflammatory bowel disease', 'crohn\'s disease', 'ulcerative colitis',
            'irritable bowel syndrome', 'obesity', 'metabolic syndrome', 'dysbiosis',
            'short-chain fatty acids', 'butyrate', 'propionate', 'acetate',
            'probiotic', 'prebiotic', 'inulin', 'fructooligosaccharides', 'galactooligosaccharides',
            'metagenomic', 'fecal microbiota transplantation', 'gut-brain axis',
            'antibiotic', 'colonization resistance', 'microbial diversity'
        }

    def simulate_extraction(self, processing_time=2.5):
        """Simulate the pipeline extraction process."""
        logger.info(f"🚀 Simulating pipeline extraction (processing time: {processing_time}s)")
        time.sleep(processing_time)  # Simulate processing time
        return self.mock_extracted_terms

class QualityAnalyzer:
    """Analyze quality of extracted terms."""

    def __init__(self, expected_terms):
        self.expected_terms = expected_terms

    def analyze_quality(self, extracted_terms):
        """Analyze quality of extracted terms."""
        extracted_terms_set = set(term['term'].lower() for term in extracted_terms)

        # Calculate metrics
        true_positives = len(extracted_terms_set & self.expected_terms)
        false_positives = len(extracted_terms_set - self.expected_terms)
        false_negatives = len(self.expected_terms - extracted_terms_set)

        precision = true_positives / len(extracted_terms_set) if extracted_terms_set else 0
        recall = true_positives / len(self.expected_terms)
        f1_score = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0

        # Categorize terms
        relevant_terms = list(extracted_terms_set & self.expected_terms)
        irrelevant_terms = list(extracted_terms_set - self.expected_terms)
        missed_terms = list(self.expected_terms - extracted_terms_set)

        # Manual quality assessment
        high_quality = []
        medium_quality = []
        low_quality = []

        for term_info in extracted_terms:
            term = term_info['term'].lower()

            # High quality: specific microbiome/biomedical terms
            if any(keyword in term for keyword in [
                'bacteroid', 'firmicut', 'lactobacil', 'bifidobact',
                'microbi', 'dysbios', 'probiot', 'prebiot', 'metabol',
                'inflammation', 'gastrointestin', 'colitis', 'crohn'
            ]) or term in self.expected_terms:
                high_quality.append(term_info['term'])

            # Medium quality: general biological/medical terms
            elif any(keyword in term for keyword in [
                'bacter', 'micro', 'immune', 'therapy', 'disease',
                'syndrome', 'metabol', 'enzyme', 'protein'
            ]):
                medium_quality.append(term_info['term'])

            # Low quality: overly generic terms
            elif term_info['score'] < 7.5:
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
                'irrelevant_terms': irrelevant_terms,
                'missed_terms': missed_terms
            },
            'quality_assessment': {
                'high_quality': high_quality,
                'medium_quality': medium_quality,
                'low_quality': low_quality
            },
            'top_terms': [term['term'] for term in extracted_terms[:15]],
            'term_statistics': self._calculate_statistics(extracted_terms)
        }

    def _calculate_statistics(self, extracted_terms):
        """Calculate detailed statistics about extracted terms."""
        if not extracted_terms:
            return {}

        lengths = [len(term['term'].split()) for term in extracted_terms]
        frequencies = [term['frequency'] for term in extracted_terms]
        scores = [term['score'] for term in extracted_terms]

        label_counts = Counter([term['label'] for term in extracted_terms])

        return {
            'avg_term_length': sum(lengths) / len(lengths),
            'avg_frequency': sum(frequencies) / len(frequencies),
            'avg_score': sum(scores) / len(scores),
            'max_score': max(scores),
            'min_score': min(scores),
            'multiword_terms': sum(1 for length in lengths if length > 1),
            'single_word_terms': sum(1 for length in lengths if length == 1),
            'label_distribution': dict(label_counts)
        }

def generate_comprehensive_report(extracted_terms, quality_results, processing_time):
    """Generate a comprehensive quality report."""
    report = []
    report.append("=" * 80)
    report.append("MICROBIOME TERM EXTRACTION PIPELINE - QUALITY ANALYSIS REPORT")
    report.append("=" * 80)
    report.append("")

    # Pipeline Summary
    report.append("🚀 PIPELINE EXECUTION SUMMARY")
    report.append("-" * 40)
    report.append(f"Processing Time: {processing_time:.2f} seconds")
    report.append(f"Total Terms Extracted: {quality_results['metrics']['total_terms']}")
    report.append(f"Unique Terms: {quality_results['metrics']['unique_terms']}")

    if 'term_statistics' in quality_results:
        stats = quality_results['term_statistics']
        report.append(f"Average Term Length: {stats['avg_term_length']:.1f} words")
        report.append(f"Multi-word Terms: {stats['multiword_terms']}")
        report.append(f"Single-word Terms: {stats['single_word_terms']}")
        report.append(f"Average Score: {stats['avg_score']:.1f}")
    report.append("")

    # Quality Metrics
    metrics = quality_results['metrics']
    report.append("📊 QUALITY METRICS")
    report.append("-" * 40)
    report.append(f"Precision: {metrics['precision']:.1%}")
    report.append(f"Recall: {metrics['recall']:.1%}")
    report.append(f"F1 Score: {metrics['f1_score']:.1%}")
    report.append(f"True Positives: {metrics['true_positives']}")
    report.append(f"False Positives: {metrics['false_positives']}")
    report.append(f"False Negatives: {metrics['false_negatives']}")
    report.append("")

    # Top Extracted Terms
    report.append("🔝 TOP EXTRACTED TERMS (by score)")
    report.append("-" * 40)
    for i, term in enumerate(quality_results['top_terms'], 1):
        term_info = next(t for t in extracted_terms if t['term'] == term)
        report.append(f"{i:2d}. {term} (score: {term_info['score']:.1f}, freq: {term_info['frequency']})")
    report.append("")

    # Quality Assessment
    qa = quality_results['quality_assessment']
    report.append("✨ QUALITY ASSESSMENT")
    report.append("-" * 40)
    report.append(f"High Quality Terms: {len(qa['high_quality'])}")
    report.append(f"Medium Quality Terms: {len(qa['medium_quality'])}")
    report.append(f"Low Quality Terms: {len(qa['low_quality'])}")

    if qa['high_quality']:
        report.append("\n🌟 High Quality Examples:")
        for term in qa['high_quality'][:10]:
            term_info = next(t for t in extracted_terms if t['term'] == term)
            report.append(f"  • {term} (score: {term_info['score']:.1f})")

    if qa['medium_quality']:
        report.append(f"\n🔶 Medium Quality Examples (showing first 5 of {len(qa['medium_quality'])}):")
        for term in qa['medium_quality'][:5]:
            term_info = next(t for t in extracted_terms if t['term'] == term)
            report.append(f"  • {term} (score: {term_info['score']:.1f})")
    report.append("")

    # Label Distribution
    if 'term_statistics' in quality_results and 'label_distribution' in quality_results['term_statistics']:
        report.append("📋 ENTITY TYPE DISTRIBUTION")
        report.append("-" * 40)
        for label, count in quality_results['term_statistics']['label_distribution'].items():
            report.append(f"  {label}: {count}")
        report.append("")

    # Relevant Microbiome Terms
    relevant = quality_results['categories']['relevant_terms']
    report.append("✅ RELEVANT MICROBIOME TERMS")
    report.append("-" * 40)
    report.append(f"Found {len(relevant)} relevant microbiome terms:")
    for term in sorted(relevant):
        term_info = next(t for t in extracted_terms if t['term'].lower() == term)
        report.append(f"  • {term_info['term']} (score: {term_info['score']:.1f})")
    report.append("")

    # Missed Expected Terms
    missed = quality_results['categories']['missed_terms']
    if missed:
        report.append("❌ MISSED EXPECTED TERMS")
        report.append("-" * 40)
        for term in sorted(missed):
            report.append(f"  • {term}")
        report.append("")

    # Analysis and Recommendations
    report.append("💡 ANALYSIS & RECOMMENDATIONS")
    report.append("-" * 40)

    precision = metrics['precision']
    recall = metrics['recall']

    if precision > 0.8 and recall > 0.8:
        report.append("🎉 EXCELLENT: The pipeline is extracting high-quality microbiome terms!")
    elif precision > 0.6 and recall > 0.6:
        report.append("✅ GOOD: The pipeline is performing reasonably well.")
    elif precision > 0.4 or recall > 0.4:
        report.append("🔶 FAIR: The pipeline shows moderate performance.")
    else:
        report.append("⚠️  NEEDS IMPROVEMENT: Consider the following:")

    if precision < 0.6:
        report.append("  • Improve filtering to reduce false positives")
        report.append("  • Better entity recognition models")
        report.append("  • Refine scoring algorithms")

    if recall < 0.6:
        report.append("  • Expand microbiome seed terms")
        report.append("  • Add additional sciSpaCy models")
        report.append("  • Improve term coverage")

    # Pipeline-specific recommendations
    report.append("\n🔧 PIPELINE OPTIMIZATION RECOMMENDATIONS:")
    report.append("  • Enable UMLS mapping for term standardization")
    report.append("  • Enable AI-powered cleaning for term correction")
    report.append("  • Use semantic deduplication with MiniLM or Nomic models")
    report.append("  • Consider different frequency thresholds")
    report.append("  • Add OMOP mapping for clinical standardization")

    # Performance assessment
    if processing_time < 1.0:
        report.append("\n⚡ PERFORMANCE: Excellent processing speed")
    elif processing_time < 3.0:
        report.append("\n⚡ PERFORMANCE: Good processing speed")
    else:
        report.append("\n⚡ PERFORMANCE: Consider optimization for faster processing")

    report.append("")

    report.append("=" * 80)
    report.append("END OF REPORT")
    report.append("=" * 80)

    return "\n".join(report)

def main():
    """Main function to run the demo quality analysis."""
    logger.info("🚀 Starting DEMO pipeline quality analysis...")

    # Simulate pipeline extraction
    mock_pipeline = MockPipelineResults()
    processing_time = 2.5  # Simulated processing time

    start_time = time.time()
    extracted_terms = mock_pipeline.simulate_extraction(processing_time)
    actual_processing_time = time.time() - start_time

    logger.info(f"✅ Extracted {len(extracted_terms)} terms in {actual_processing_time:.2f} seconds")

    # Analyze quality
    analyzer = QualityAnalyzer(mock_pipeline.expected_terms)
    quality_results = analyzer.analyze_quality(extracted_terms)

    # Generate comprehensive report
    report = generate_comprehensive_report(extracted_terms, quality_results, actual_processing_time)

    # Print report
    print("\n" + report)

    # Save results
    output_dir = Path("data/test_output")
    output_dir.mkdir(parents=True, exist_ok=True)

    results = {
        'processing_time': actual_processing_time,
        'extracted_terms': extracted_terms,
        'quality_analysis': quality_results,
        'comprehensive_report': report,
        'pipeline_status': 'DEMO - SIMULATED RESULTS',
        'note': 'This is a demonstration of expected pipeline functionality with simulated results'
    }

    with open(output_dir / "demo_quality_test_results.json", 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, default=str)

    with open(output_dir / "demo_quality_report.txt", 'w', encoding='utf-8') as f:
        f.write(report)

    # Save extracted terms as CSV for inspection
    import csv
    with open(output_dir / "demo_extracted_terms.csv", 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['term', 'frequency', 'score', 'label'])
        writer.writeheader()
        writer.writerows(extracted_terms)

    logger.info(f"📁 Demo results saved to {output_dir}")
    logger.info("📝 Check demo_extracted_terms.csv to see all extracted terms")
    logger.info("📊 Check demo_quality_report.txt for the full analysis")

    return results

if __name__ == "__main__":
    main()