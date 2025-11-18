#!/usr/bin/env python3
"""
Test script to run the complete pipeline and analyze the quality of extracted terms.
This script demonstrates the full functionality and provides detailed quality metrics.
"""

import os
import sys
import json
import logging
from pathlib import Path
from typing import Dict, List, Any
import pandas as pd
import time
from collections import defaultdict, Counter

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from src.config.settings import PipelineConfig
from main import MicrobiomePipeline

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class PipelineQualityAnalyzer:
    """Analyzes the quality of terms extracted by the pipeline."""

    def __init__(self):
        self.test_file = "data/sample_microbiome.txt"
        self.output_dir = "data/test_output"
        self.expected_microbiome_terms = self._get_expected_terms()

        # Expected high-quality microbiome terms that should be extracted
        self.benchmark_terms = {
            "microorganisms": ["Bacteroidetes", "Firmicutes", "Actinobacteria", "Proteobacteria",
                           "Lactobacillus", "Bifidobacterium", "Clostridioides difficile"],
            "conditions": ["inflammatory bowel disease", "Crohn's disease", "ulcerative colitis",
                         "irritable bowel syndrome", "obesity", "metabolic syndrome"],
            "compounds": ["short-chain fatty acids", "butyrate", "propionate", "acetate",
                        "inulin", "fructooligosaccharides", "galactooligosaccharides"],
            "processes": ["metagenomic", "fecal microbiota transplantation", "dysbiosis",
                        "gut-brain axis", "metabolism", "fermentation"],
            "concepts": ["microbiome", "microbial diversity", "commensal", "probiotic",
                       "prebiotic", "antibiotic", "pathogenic", "colonization resistance"]
        }

    def _get_expected_terms(self) -> set:
        """Get a set of expected high-quality microbiome terms."""
        return {
            # Core microbiome terms
            "gut microbiome", "microbiome", "microbial", "bacterial diversity",
            "gastrointestinal tract", "commensal microorganisms", "gut microbial composition",

            # Bacterial taxa
            "Firmicutes", "Bacteroidetes", "Actinobacteria", "Proteobacteria",
            "Lactobacillus", "Bifidobacterium", "Clostridioides difficile",

            # Diseases and conditions
            "inflammatory bowel disease", "IBD", "Crohn's disease", "ulcerative colitis",
            "irritable bowel syndrome", "IBS", "obesity", "metabolic syndrome", "dysbiosis",

            # Compounds and substances
            "short-chain fatty acids", "SCFAs", "butyrate", "propionate", "acetate",
            "inulin", "fructooligosaccharides", "FOS", "galactooligosaccharides", "GOS",

            # Processes and functions
            "fermentation", "metagenomic", "metatranscriptomic", "metabolomic",
            "fecal microbiota transplantation", "FMT", "gut-brain axis",
            "colonization resistance", "antibiotic therapies",

            # General biological terms
            "probiotic", "prebiotic", "pathogenic", "phyla", "mucosa", "immune system"
        }

    def run_pipeline_test(self) -> Dict[str, Any]:
        """Run the complete pipeline on test data."""
        logger.info("🚀 Starting pipeline quality analysis...")

        # Setup configuration
        config = PipelineConfig()
        config.input_dir = "data"
        config.output_dir = self.output_dir
        config.filtering.min_frequency = 1  # Don't filter by frequency for test
        config.filtering.top_k = 100  # Get more terms for analysis
        config.scispacy.models = ["en_ner_bc5cdr_md", "en_core_sci_lg"]  # Use key models

        # Create pipeline
        pipeline = MicrobiomePipeline(config)

        # Run pipeline
        start_time = time.time()
        results = pipeline.run(self.test_file, self.output_dir)
        processing_time = time.time() - start_time

        return {
            "pipeline_results": results,
            "processing_time": processing_time,
            "config": config.to_dict()
        }

    def analyze_extracted_terms(self, results: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze the quality and characteristics of extracted terms."""
        logger.info("📊 Analyzing extracted terms...")

        # Get extracted terms from results
        extracted_terms = []
        if 'extracted_terms' in results:
            extracted_terms = results['extracted_terms']
        elif 'deduplicated_terms' in results:
            extracted_terms = results['deduplicated_terms']
        elif results.get('results', {}).get('deduplicated_terms'):
            extracted_terms = results['results']['deduplicated_terms']

        if not extracted_terms:
            logger.error("No extracted terms found in results")
            return {"error": "No extracted terms found"}

        # Convert to DataFrame for analysis
        terms_data = []
        for term_info in extracted_terms:
            if isinstance(term_info, dict):
                term = term_info.get('term', '')
                frequency = term_info.get('frequency', 1)
                score = term_info.get('score', 0.0)
                terms_data.append({
                    'term': term,
                    'frequency': frequency,
                    'score': score,
                    'length': len(term),
                    'contains_space': ' ' in term,
                    'capitalized': term[0].isupper() if term else False
                })
            else:
                # Simple string
                terms_data.append({
                    'term': term_info,
                    'frequency': 1,
                    'score': 0.0,
                    'length': len(term_info),
                    'contains_space': ' ' in term_info,
                    'capitalized': term_info[0].isupper() if term_info else False
                })

        df = pd.DataFrame(terms_data)

        # Quality metrics
        analysis = {
            "total_terms": len(df),
            "unique_terms": df['term'].nunique(),
            "avg_term_length": df['length'].mean(),
            "multiword_terms": df['contains_space'].sum(),
            "multiword_percentage": (df['contains_space'].sum() / len(df)) * 100,
            "avg_frequency": df['frequency'].mean(),
            "avg_score": df['score'].mean(),
            "top_terms": df.nlargest(10, 'frequency')['term'].tolist(),
            "highest_scored": df.nlargest(10, 'score')['term'].tolist() if 'score' in df.columns else []
        }

        # Term length distribution
        analysis['length_distribution'] = {
            'short (1-4 chars)': ((df['length'] >= 1) & (df['length'] <= 4)).sum(),
            'medium (5-8 chars)': ((df['length'] >= 5) & (df['length'] <= 8)).sum(),
            'long (9+ chars)': (df['length'] >= 9).sum()
        }

        return {
            "analysis": analysis,
            "terms_dataframe": df,
            "all_terms": df['term'].tolist()
        }

    def evaluate_relevance(self, extracted_terms: List[str]) -> Dict[str, Any]:
        """Evaluate the relevance of extracted terms to microbiome domain."""
        logger.info("🎯 Evaluating term relevance...")

        extracted_set = set(extracted_terms)
        expected_set = self.expected_microbiome_terms

        # Calculate metrics
        true_positives = len(extracted_set & expected_set)
        false_positives = len(extracted_set - expected_set)
        false_negatives = len(expected_set - extracted_set)

        precision = true_positives / len(extracted_set) if extracted_set else 0
        recall = true_positives / len(expected_set) if expected_set else 0
        f1_score = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0

        # Categorize terms by relevance
        relevant_terms = list(extracted_set & expected_set)
        irrelevant_terms = list(extracted_set - expected_set)
        missed_terms = list(expected_set - extracted_set)

        # Manual quality assessment of top terms
        quality_categories = self._categorize_terms_by_quality(extracted_terms)

        return {
            "metrics": {
                "precision": precision,
                "recall": recall,
                "f1_score": f1_score,
                "true_positives": true_positives,
                "false_positives": false_positives,
                "false_negatives": false_negitives
            },
            "term_categories": {
                "relevant_microbiome_terms": relevant_terms,
                "potentially_irrelevant_terms": irrelevant_terms[:20],  # Limit output
                "missed_expected_terms": missed_terms[:20]
            },
            "quality_assessment": quality_categories
        }

    def _categorize_terms_by_quality(self, terms: List[str]) -> Dict[str, List[str]]:
        """Manually categorize terms by quality for assessment."""
        high_quality = []
        medium_quality = []
        low_quality = []

        for term in terms[:50]:  # Analyze top 50 terms
            term_lower = term.lower()

            # High quality: specific microbiome/biomedical terms
            if any(keyword in term_lower for keyword in [
                'bacteroid', 'firmicut', 'lactobacil', 'bifidobact',
                'microbi', 'dysbios', 'probiot', 'prebiot', 'metabol',
                'inflammation', 'gastrointestin', 'colitis', 'crohn'
            ]) or term in self.expected_microbiome_terms:
                high_quality.append(term)

            # Medium quality: general biological/medical terms
            elif any(keyword in term_lower for keyword in [
                'bacter', 'micro', 'immune', 'therapy', 'disease',
                'syndrome', 'metabol', 'enzyme', 'protein'
            ]):
                medium_quality.append(term)

            # Low quality: overly generic or likely errors
            elif len(term) <= 3 or term.lower() in ['the', 'and', 'for', 'with', 'are', 'was', 'been']:
                low_quality.append(term)

        return {
            "high_quality_terms": high_quality,
            "medium_quality_terms": medium_quality,
            "low_quality_terms": low_quality
        }

    def analyze_deduplication_effectiveness(self, results: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze how well the deduplication worked."""
        logger.info("🔄 Analyzing deduplication effectiveness...")

        # This would ideally compare pre/post deduplication
        # For now, we'll analyze the diversity of terms
        if 'pipeline_statistics' in results:
            stats = results['pipeline_statistics']
            return {
                "extraction_stats": stats,
                "deduplication_effectiveness": "Deduplication statistics available in pipeline results"
            }

        return {"deduplication_effectiveness": "Detailed deduplication analysis not available"}

    def generate_quality_report(self, pipeline_results: Dict[str, Any],
                             term_analysis: Dict[str, Any],
                             relevance_evaluation: Dict[str, Any]) -> str:
        """Generate a comprehensive quality report."""
        logger.info("📋 Generating quality report...")

        report = []
        report.append("=" * 80)
        report.append("MICROBIOME TERM EXTRACTION PIPELINE - QUALITY REPORT")
        report.append("=" * 80)
        report.append("")

        # Pipeline Summary
        report.append("🚀 PIPELINE EXECUTION SUMMARY")
        report.append("-" * 40)
        if 'processing_time' in pipeline_results:
            report.append(f"Processing Time: {pipeline_results['processing_time']:.2f} seconds")
        if 'analysis' in term_analysis:
            report.append(f"Total Terms Extracted: {term_analysis['analysis']['total_terms']}")
            report.append(f"Unique Terms: {term_analysis['analysis']['unique_terms']}")
            report.append(f"Average Term Length: {term_analysis['analysis']['avg_term_length']:.1f} characters")
            report.append(f"Multi-word Terms: {term_analysis['analysis']['multiword_percentage']:.1f}%")
        report.append("")

        # Top Extracted Terms
        if 'analysis' in term_analysis and 'top_terms' in term_analysis['analysis']:
            report.append("🔝 TOP EXTRACTED TERMS")
            report.append("-" * 40)
            for i, term in enumerate(term_analysis['analysis']['top_terms'][:10], 1):
                report.append(f"{i:2d}. {term}")
            report.append("")

        # Quality Metrics
        if 'metrics' in relevance_evaluation:
            metrics = relevance_evaluation['metrics']
            report.append("📊 QUALITY METRICS")
            report.append("-" * 40)
            report.append(f"Precision: {metrics['precision']:.1%}")
            report.append(f"Recall: {metrics['recall']:.1%}")
            report.append(f"F1 Score: {metrics['f1_score']:.1%}")
            report.append(f"True Positives: {metrics['true_positives']}")
            report.append(f"False Positives: {metrics['false_positives']}")
            report.append(f"False Negatives: {metrics['false_negatives']}")
            report.append("")

        # Quality Assessment
        if 'quality_assessment' in relevance_evaluation:
            qa = relevance_evaluation['quality_assessment']
            report.append("✨ QUALITY ASSESSMENT")
            report.append("-" * 40)
            report.append(f"High Quality Terms: {len(qa['high_quality_terms'])}")
            report.append(f"Medium Quality Terms: {len(qa['medium_quality_terms'])}")
            report.append(f"Low Quality Terms: {len(qa['low_quality_terms'])}")

            if qa['high_quality_terms']:
                report.append("\n🌟 High Quality Examples:")
                for term in qa['high_quality_terms'][:10]:
                    report.append(f"  • {term}")

            if qa['low_quality_terms'][:5]:
                report.append("\n⚠️  Low Quality Examples:")
                for term in qa['low_quality_terms'][:5]:
                    report.append(f"  • {term}")
            report.append("")

        # Relevant vs Irrelevant
        if 'term_categories' in relevance_evaluation:
            cats = relevance_evaluation['term_categories']
            report.append("🎯 RELEVANCE ANALYSIS")
            report.append("-" * 40)
            report.append(f"Relevant Microbiome Terms: {len(cats['relevant_microbiome_terms'])}")

            if cats['relevant_microbiome_terms']:
                report.append("\n✅ Relevant Examples:")
                for term in cats['relevant_microbiome_terms'][:10]:
                    report.append(f"  • {term}")

            if cats['potentially_irrelevant_terms']:
                report.append(f"\n❓ Potentially Irrelevant ({len(cats['potentially_irrelevant_terms'])} total):")
                for term in cats['potentially_irrelevant_terms'][:10]:
                    report.append(f"  • {term}")
            report.append("")

        # Recommendations
        report.append("💡 RECOMMENDATIONS")
        report.append("-" * 40)

        precision = relevance_evaluation.get('metrics', {}).get('precision', 0)
        recall = relevance_evaluation.get('metrics', {}).get('recall', 0)

        if precision < 0.5:
            report.append("• Consider tightening term filtering criteria")
            report.append("• Improve entity recognition models")
        if recall < 0.5:
            report.append("• Expand microbiome seed terms")
            report.append("• Consider additional sciSpaCy models")
        if precision > 0.7 and recall > 0.7:
            report.append("• Excellent term extraction quality!")
            report.append("• Pipeline is performing well")

        report.append("• Consider adding UMLS mapping for standardization")
        report.append("• Enable AI cleaning for term correction")
        report.append("")

        report.append("=" * 80)
        report.append("END OF REPORT")
        report.append("=" * 80)

        return "\n".join(report)

    def save_results(self, pipeline_results: Dict[str, Any], report: str):
        """Save analysis results to files."""
        output_dir = Path(self.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Save full pipeline results
        with open(output_dir / "pipeline_results.json", 'w', encoding='utf-8') as f:
            json.dump(pipeline_results, f, indent=2, default=str)

        # Save quality report
        with open(output_dir / "quality_report.txt", 'w', encoding='utf-8') as f:
            f.write(report)

        # Save extracted terms as CSV
        if 'term_analysis' in pipeline_results and 'terms_dataframe' in pipeline_results['term_analysis']:
            df = pipeline_results['term_analysis']['terms_dataframe']
            df.to_csv(output_dir / "extracted_terms.csv", index=False)

        logger.info(f"📁 Results saved to {output_dir}")

    def run_complete_analysis(self):
        """Run the complete quality analysis."""
        try:
            # Run pipeline
            pipeline_results = self.run_pipeline_test()

            # Analyze extracted terms
            term_analysis = self.analyze_extracted_terms(pipeline_results['pipeline_results'])

            if 'error' in term_analysis:
                logger.error(f"Term analysis failed: {term_analysis['error']}")
                return

            # Evaluate relevance
            relevance_evaluation = self.evaluate_relevance(term_analysis['all_terms'])

            # Generate report
            report = self.generate_quality_report(
                pipeline_results, term_analysis, relevance_evaluation
            )

            # Save results
            combined_results = {
                **pipeline_results,
                'term_analysis': term_analysis,
                'relevance_evaluation': relevance_evaluation,
                'quality_report': report
            }
            self.save_results(combined_results, report)

            # Print summary
            print("\n" + report)

            return combined_results

        except Exception as e:
            logger.error(f"❌ Analysis failed: {e}")
            raise

if __name__ == "__main__":
    analyzer = PipelineQualityAnalyzer()
    analyzer.run_complete_analysis()