"""
Output writing utilities for the pipeline
"""

import json
import csv
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional
import sqlite3
import numpy as np

from src.config.settings import PipelineConfig

logger = logging.getLogger(__name__)


class NumpyEncoder(json.JSONEncoder):
    """Custom JSON encoder for numpy types"""
    def default(self, obj):
        if isinstance(obj, np.integer):
            return int(obj)
        elif isinstance(obj, np.floating):
            return float(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        return super(NumpyEncoder, self).default(obj)


class OutputWriter:
    """Write pipeline results to various formats"""

    def __init__(self, config: PipelineConfig):
        self.config = config
        self.output_dir = Path(config.output_dir)
        self.output_dir.mkdir(exist_ok=True)

    def generate_filename(self, base_name: str, extension: str, timestamp: bool = True) -> Path:
        """Generate output filename with optional timestamp"""
        if timestamp:
            timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{base_name}_{timestamp_str}{extension}"
        else:
            filename = f"{base_name}{extension}"

        return self.output_dir / filename

    def write_json(self, terms: List[Dict[str, Any]], filename: str = None, timestamp: bool = True) -> Path:
        """Write terms to JSON file"""
        if filename is None:
            output_path = self.generate_filename("scientific_terms", ".json", timestamp)
        else:
            output_path = self.output_dir / filename

        try:
            # Prepare data for JSON serialization
            json_data = {
                "metadata": {
                    "extraction_timestamp": datetime.now().isoformat(),
                    "total_terms": len(terms),
                    "pipeline_version": "1.0.0",
                    "models_used": list(set(term.get('model', 'unknown') for term in terms))
                },
                "terms": terms
            }

            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(json_data, f, indent=2, ensure_ascii=False, cls=NumpyEncoder)

            logger.info(f"✅ JSON output written to: {output_path}")
            return output_path

        except Exception as e:
            logger.error(f"❌ Failed to write JSON file: {e}")
            raise

    def write_csv(self, terms: List[Dict[str, Any]], filename: str = None, timestamp: bool = True) -> Path:
        """Write terms to CSV file"""
        if filename is None:
            output_path = self.generate_filename("scientific_terms", ".csv", timestamp)
        else:
            output_path = self.output_dir / filename

        try:
            # Define CSV columns
            columns = [
                'term', 'canonical', 'label', 'confidence', 'science_score',
                'model', 'models_used', 'context', 'start_char', 'end_char'
            ]

            with open(output_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=columns)
                writer.writeheader()

                for term in terms:
                    # Prepare row data
                    row = {
                        'term': term.get('term', ''),
                        'canonical': term.get('canonical', ''),
                        'label': term.get('label', ''),
                        'confidence': term.get('confidence', 0.0),
                        'science_score': term.get('science_score', 0.0),
                        'models_used': ', '.join(term.get('models_used', [term.get('model', 'unknown')])),
                        'context': term.get('context', ''),
                        'start_char': term.get('start_char', ''),
                        'end_char': term.get('end_char', '')
                    }

                    # Add additional fields if they exist
                    for key, value in term.items():
                        if key not in columns and not isinstance(value, (list, dict)):
                            row[key] = value

                    writer.writerow(row)

            logger.info(f"✅ CSV output written to: {output_path}")
            return output_path

        except Exception as e:
            logger.error(f"❌ Failed to write CSV file: {e}")
            raise

    def write_sqlite(self, terms: List[Dict[str, Any]], filename: str = None, timestamp: bool = True) -> Path:
        """Write terms to SQLite database"""
        if filename is None:
            output_path = self.generate_filename("scientific_terms", ".db", timestamp)
        else:
            # Ensure filename has .db extension
            if not filename.endswith('.db'):
                filename += '.db'
            output_path = self.output_dir / filename

        try:
            conn = sqlite3.connect(output_path)
            cursor = conn.cursor()

            # Create tables
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS terms (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    term TEXT NOT NULL,
                    canonical TEXT NOT NULL,
                    label TEXT,
                    confidence REAL,
                    science_score REAL,
                    models_used TEXT,
                    context TEXT,
                    start_char INTEGER,
                    end_char INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            ''')

            # Insert metadata
            metadata = {
                'extraction_timestamp': datetime.now().isoformat(),
                'total_terms': str(len(terms)),
                'pipeline_version': '1.0.0'
            }

            for key, value in metadata.items():
                cursor.execute('INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)', (key, value))

            # Insert terms
            for term in terms:
                cursor.execute('''
                    INSERT INTO terms (term, canonical, label, confidence, science_score, models_used, context, start_char, end_char)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    term.get('term', ''),
                    term.get('canonical', ''),
                    term.get('label', ''),
                    term.get('confidence', 0.0),
                    term.get('science_score', 0.0),
                    ', '.join(term.get('models_used', [term.get('model', 'unknown')])),
                    term.get('context', ''),
                    term.get('start_char', 0),
                    term.get('end_char', 0)
                ))

            # Create indexes
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_canonical ON terms(canonical)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_label ON terms(label)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_confidence ON terms(confidence)')

            conn.commit()
            conn.close()

            logger.info(f"✅ SQLite output written to: {output_path}")
            return output_path

        except Exception as e:
            logger.error(f"❌ Failed to write SQLite file: {e}")
            raise

    def write_summary_report(self, terms: List[Dict[str, Any]], stats: Dict[str, Any], filename: str = None) -> Path:
        """Write summary report"""
        if filename is None:
            output_path = self.generate_filename("pipeline_summary", ".md", timestamp=True)
        else:
            output_path = self.output_dir / filename

        try:
            # Generate summary statistics
            total_terms = len(terms)
            avg_confidence = sum(t.get('confidence', 0) for t in terms) / total_terms if total_terms > 0 else 0
            avg_science_score = sum(t.get('science_score', 0) for t in terms) / total_terms if total_terms > 0 else 0

            # Count by label
            label_counts = {}
            for term in terms:
                label = term.get('label', 'UNKNOWN')
                label_counts[label] = label_counts.get(label, 0) + 1

            # Count by model
            model_counts = {}
            for term in terms:
                models = term.get('models_used', [term.get('model', 'unknown')])
                for model in models:
                    model_counts[model] = model_counts.get(model, 0) + 1

            # Write report
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write("# Scientific Terms Extraction Pipeline - Summary Report\n\n")
                f.write(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")

                f.write("## Overview\n\n")
                f.write(f"- **Total Terms Extracted:** {total_terms}\n")
                f.write(f"- **Average Confidence:** {avg_confidence:.3f}\n")
                f.write(f"- **Average Science Score:** {avg_science_score:.3f}\n")

                if 'deduplication_stats' in stats:
                    dedup_stats = stats['deduplication_stats']
                    f.write(f"- **Original Terms (Pre-deduplication):** {dedup_stats.get('original_count', 'N/A')}\n")
                    f.write(f"- **Final Terms (Post-deduplication):** {dedup_stats.get('final_count', 'N/A')}\n")
                    f.write(f"- **Deduplication Reduction:** {dedup_stats.get('reduction_percentage', 0):.1f}%\n")

                f.write("\n## Terms by Scientific Category\n\n")
                for label, count in sorted(label_counts.items(), key=lambda x: x[1], reverse=True):
                    f.write(f"- **{label}:** {count} terms\n")

                f.write("\n## Model Performance\n\n")
                for model, count in sorted(model_counts.items(), key=lambda x: x[1], reverse=True):
                    f.write(f"- **{model}:** {count} terms\n")

                # Top terms
                f.write("\n## Top 20 Terms by Confidence\n\n")
                top_terms = sorted(terms, key=lambda x: x.get('confidence', 0), reverse=True)[:20]
                for i, term in enumerate(top_terms, 1):
                    f.write(f"{i:2d}. **{term['term']}** (conf: {term.get('confidence', 0):.3f}, science: {term.get('science_score', 0):.3f})\n")

                f.write(f"\n---\n\n")
                f.write(f"*Report generated by Scientific Terms Extraction Pipeline v1.0.0*\n")

            logger.info(f"✅ Summary report written to: {output_path}")
            return output_path

        except Exception as e:
            logger.error(f"❌ Failed to write summary report: {e}")
            raise

    def write_all_formats(self, terms: List[Dict[str, Any]], stats: Dict[str, Any] = None, base_filename: str = None) -> Dict[str, Path]:
        """Write results to all supported formats"""
        if stats is None:
            stats = {}

        outputs = {}

        try:
            # JSON
            outputs['json'] = self.write_json(terms, base_filename)

            # CSV
            outputs['csv'] = self.write_csv(terms, base_filename)

            # SQLite
            outputs['sqlite'] = self.write_sqlite(terms, base_filename)

            # Summary report
            outputs['summary'] = self.write_summary_report(terms, stats)

            logger.info(f"✅ All output formats written successfully")
            return outputs

        except Exception as e:
            logger.error(f"❌ Failed to write outputs: {e}")
            raise