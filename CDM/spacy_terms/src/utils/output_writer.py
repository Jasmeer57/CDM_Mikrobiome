"""
Output writer for saving results in multiple formats (JSON, CSV, SQLite).
"""

import logging
import json
import csv
import sqlite3
import pandas as pd
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class NumpyEncoder(json.JSONEncoder):
    """Custom JSON encoder for numpy types"""
    def default(self, obj):
        if isinstance(obj, (int, float, str, bool, list, dict, type(None))):
            return super(NumpyEncoder, self).default(obj)
        return str(obj)


class OutputWriter:
    """Multi-format output writer"""

    def __init__(self, output_dir: str):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _flatten_dict(self, d: Dict[str, Any], parent_key: str = '', sep: str = '_') -> Dict[str, Any]:
        """Flatten nested dictionary"""
        items = []
        for k, v in d.items():
            new_key = f"{parent_key}{sep}{k}" if parent_key else k
            if isinstance(v, dict):
                items.extend(self._flatten_dict(v, new_key, sep=sep).items())
            elif isinstance(v, list) and v and isinstance(v[0], dict):
                # Handle list of dictionaries by taking first element
                items.extend(self._flatten_dict(v[0], new_key, sep=sep).items())
            else:
                items.append((new_key, v))
        return dict(items)

    def save_json(self, results: Dict[str, Any], filename: str = None) -> str:
        """Save results as JSON"""
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"pipeline_results_{timestamp}.json"

        output_path = self.output_dir / filename

        try:
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(results, f, indent=2, ensure_ascii=False, cls=NumpyEncoder)

            logger.info(f"JSON results saved to: {output_path}")
            return str(output_path)

        except Exception as e:
            logger.error(f"Failed to save JSON: {e}")
            raise

    def save_csv(self, results: Dict[str, Any], filename: str = None) -> str:
        """Save results as CSV"""
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"pipeline_results_{timestamp}.csv"

        output_path = self.output_dir / filename

        try:
            # Extract terms for CSV
            terms = results.get('ai_corrected_terms', []) or results.get('deduplicated_terms', [])

            if not terms:
                logger.warning("No terms to save as CSV")
                return str(output_path)

            # Flatten terms for CSV
            flattened_terms = []
            for term_data in terms:
                flat = self._flatten_dict(term_data)
                # Handle nested objects like mappings
                for key, value in flat.items():
                    if isinstance(value, (dict, list)):
                        flat[key] = json.dumps(value, ensure_ascii=False)
                flattened_terms.append(flat)

            # Create DataFrame and save
            df = pd.DataFrame(flattened_terms)

            # Reorder columns to put important ones first
            important_cols = ['term', 'frequency', 'relevance_score', 'models_used', 'labels']
            existing_cols = df.columns.tolist()
            ordered_cols = []

            for col in important_cols:
                if col in existing_cols:
                    ordered_cols.append(col)

            # Add remaining columns
            for col in existing_cols:
                if col not in ordered_cols:
                    ordered_cols.append(col)

            df = df[ordered_cols]
            df.to_csv(output_path, index=False)

            logger.info(f"CSV results saved to: {output_path}")
            return str(output_path)

        except Exception as e:
            logger.error(f"Failed to save CSV: {e}")
            raise

    def save_sqlite(self, results: Dict[str, Any], filename: str = None) -> str:
        """Save results as SQLite database"""
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"pipeline_results_{timestamp}.db"

        output_path = self.output_dir / filename

        try:
            conn = sqlite3.connect(output_path)

            # Save terms
            terms = results.get('ai_corrected_terms', []) or results.get('deduplicated_terms', [])
            if terms:
                # Flatten terms
                flattened_terms = []
                for term_data in terms:
                    flat = self._flatten_dict(term_data)
                    # Convert complex objects to JSON strings
                    for key, value in flat.items():
                        if isinstance(value, (dict, list)):
                            flat[key] = json.dumps(value, ensure_ascii=False)
                        elif pd.isna(value):
                            flat[key] = None
                    flattened_terms.append(flat)

                df_terms = pd.DataFrame(flattened_terms)
                df_terms.to_sql('terms', conn, if_exists='replace', index=False)

            # Save statistics
            if 'statistics' in results:
                stats_df = pd.DataFrame([results['statistics']])
                stats_df.to_sql('statistics', conn, if_exists='replace', index=False)

            # Save metadata
            if 'metadata' in results:
                metadata = results['metadata']
                metadata_df = pd.DataFrame([metadata])
                metadata_df.to_sql('metadata', conn, if_exists='replace', index=False)

            conn.close()

            logger.info(f"SQLite results saved to: {output_path}")
            return str(output_path)

        except Exception as e:
            logger.error(f"Failed to save SQLite: {e}")
            raise

    def save_results(self, results: Dict[str, Any], formats: List[str]) -> Dict[str, str]:
        """Save results in specified formats"""
        saved_files = {}

        for format_type in formats:
            try:
                if format_type.lower() == 'json':
                    saved_files['json'] = self.save_json(results)
                elif format_type.lower() == 'csv':
                    saved_files['csv'] = self.save_csv(results)
                elif format_type.lower() == 'sqlite':
                    saved_files['sqlite'] = self.save_sqlite(results)
                else:
                    logger.warning(f"Unsupported format: {format_type}")

            except Exception as e:
                logger.error(f"Failed to save {format_type}: {e}")
                continue

        return saved_files


def create_output_writer(output_dir: str) -> OutputWriter:
    """Factory function to create output writer"""
    return OutputWriter(output_dir)