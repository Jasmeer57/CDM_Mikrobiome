"""
Results export utility for the microbiome term extraction pipeline.
"""

import json
import csv
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any

logger = logging.getLogger(__name__)


class ResultsExporter:
    """Handles exporting results in various formats."""

    def __init__(self, config):
        self.config = config

    def export_comprehensive_results(self, terms: List[Dict[str, Any]],
                                   umls_results: Dict[str, Any],
                                   omop_results: Dict[str, Any],
                                   pipeline_stats: Dict[str, Any],
                                   config) -> List[str]:
        """
        Export comprehensive results in multiple formats.

        Returns:
            List of exported file paths
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = Path(config.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        exported_files = []

        # Export main results JSON
        json_file = self._export_main_results_json(
            terms, umls_results, omop_results, pipeline_stats, config, timestamp, output_dir
        )
        exported_files.append(json_file)

        # Export terms CSV
        csv_file = self._export_terms_csv(terms, timestamp, output_dir)
        exported_files.append(csv_file)

        # Export UMLS results if available
        if umls_results:
            umls_file = self._export_umls_results(umls_results, timestamp, output_dir)
            exported_files.append(umls_file)

        # Export OMOP results if available
        if omop_results:
            omop_file = self._export_omop_results(omop_results, timestamp, output_dir)
            exported_files.append(omop_file)

        # Export deduplication report
        if hasattr(terms, '__iter__') and terms:
            dedup_file = self._export_deduplication_report(terms, timestamp, output_dir)
            exported_files.append(dedup_file)

        # Export pipeline statistics
        stats_file = self._export_pipeline_statistics(pipeline_stats, config, timestamp, output_dir)
        exported_files.append(stats_file)

        logger.info(f"✅ Exported {len(exported_files)} files to {output_dir}")
        return exported_files

    def _export_main_results_json(self, terms, umls_results, omop_results, pipeline_stats, config, timestamp, output_dir):
        """Export comprehensive results in JSON format."""
        json_file = output_dir / f"microbiome_pipeline_results_{timestamp}.json"

        # Convert sets to lists for JSON serialization
        for term in terms:
            if 'synonyms' in term:
                term['synonyms'] = list(term.get('synonyms', []))
            if 'file_ids' in term:
                term['file_ids'] = list(term.get('file_ids', []))
            if 'models_found' in term:
                term['models_found'] = list(term.get('models_found', []))

        results = {
            'metadata': {
                'pipeline_version': 'modular_microbiome_v1.0',
                'timestamp': timestamp,
                'configuration': config.to_dict() if hasattr(config, 'to_dict') else str(config),
                'pipeline_statistics': pipeline_stats
            },
            'terms': terms,
            'umls_results': umls_results,
            'omop_results': omop_results
        }

        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)

        logger.info(f"📄 Main results exported to: {json_file}")
        return str(json_file)

    def _export_terms_csv(self, terms, timestamp, output_dir):
        """Export terms in CSV format."""
        csv_file = output_dir / f"terms_summary_{timestamp}.csv"

        fieldnames = [
            'rank', 'term', 'original_term', 'label', 'refined_label',
            'frequency', 'models_found', 'file_count', 'semantic_relevance',
            'raw_score', 'examples'
        ]

        with open(csv_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()

            for term in terms:
                row = {
                    'rank': term.get('rank', ''),
                    'term': term.get('term', ''),
                    'original_term': term.get('original_term', ''),
                    'label': term.get('label', ''),
                    'refined_label': term.get('refined_label', ''),
                    'frequency': term.get('frequency', 0),
                    'models_found': ', '.join(term.get('models_found', [])),
                    'file_count': len(term.get('file_ids', [])),
                    'semantic_relevance': term.get('semantic_relevance', 0),
                    'raw_score': term.get('raw_score', 0),
                    'examples': term.get('examples', [''])[0][:100] if term.get('examples') else ''
                }
                writer.writerow(row)

        logger.info(f"📊 Terms CSV exported to: {csv_file}")
        return str(csv_file)

    def _export_umls_results(self, umls_results, timestamp, output_dir):
        """Export UMLS mapping results."""
        umls_file = output_dir / f"umls_mapping_{timestamp}.json"

        with open(umls_file, 'w', encoding='utf-8') as f:
            json.dump(umls_results, f, indent=2, ensure_ascii=False)

        logger.info(f"🏥 UMLS results exported to: {umls_file}")
        return str(umls_file)

    def _export_omop_results(self, omop_results, timestamp, output_dir):
        """Export OMOP mapping results."""
        omop_file = output_dir / f"omop_mapping_{timestamp}.json"

        with open(omop_file, 'w', encoding='utf-8') as f:
            json.dump(omop_results, f, indent=2, ensure_ascii=False)

        logger.info(f"📋 OMOP results exported to: {omop_file}")
        return str(omop_file)

    def _export_deduplication_report(self, terms, timestamp, output_dir):
        """Export deduplication statistics."""
        dedup_file = output_dir / f"deduplication_report_{timestamp}.json"

        # Extract deduplication statistics from terms
        fuzzy_matches = 0
        semantic_matches = 0

        for term in terms:
            if 'fuzzy_matches' in term:
                fuzzy_matches += len(term['fuzzy_matches'])
            if 'semantic_matches' in term:
                semantic_matches += len(term['semantic_matches'])

        dedup_stats = {
            'total_terms': len(terms),
            'fuzzy_duplicates_found': fuzzy_matches,
            'semantic_duplicates_found': semantic_matches,
            'terms_with_fuzzy_matches': len([t for t in terms if 'fuzzy_matches' in t and t['fuzzy_matches']]),
            'terms_with_semantic_matches': len([t for t in terms if 'semantic_matches' in t and t['semantic_matches']])
        }

        with open(dedup_file, 'w', encoding='utf-8') as f:
            json.dump(dedup_stats, f, indent=2, ensure_ascii=False)

        logger.info(f"🔄 Deduplication report exported to: {dedup_file}")
        return str(dedup_file)

    def _export_pipeline_statistics(self, pipeline_stats, config, timestamp, output_dir):
        """Export comprehensive pipeline statistics."""
        stats_file = output_dir / f"pipeline_statistics_{timestamp}.json"

        stats = {
            'pipeline_statistics': pipeline_stats,
            'configuration_summary': {
                'scispacy_models': config.scispacy.models,
                'semantic_model': config.scispacy.embedding_model,
                'fuzzy_threshold': config.deduplication.fuzzy_threshold,
                'semantic_threshold': config.deduplication.semantic_threshold,
                'min_frequency': config.filtering.min_frequency,
                'top_k': config.filtering.top_k,
                'stages_enabled': {
                    'term_extraction': config.enable_term_extraction,
                    'fuzzy_deduplication': config.enable_fuzzy_deduplication,
                    'semantic_deduplication': config.enable_semantic_deduplication,
                    'umls_mapping': config.enable_umls_mapping,
                    'ai_cleaning': config.enable_ai_cleaning,
                    'omop_mapping': config.enable_omop_mapping
                }
            }
        }

        with open(stats_file, 'w', encoding='utf-8') as f:
            json.dump(stats, f, indent=2, ensure_ascii=False)

        logger.info(f"📈 Pipeline statistics exported to: {stats_file}")
        return str(stats_file)