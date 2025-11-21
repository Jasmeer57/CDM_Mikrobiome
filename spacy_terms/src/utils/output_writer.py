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

            # Reorder columns to put important ones first (including CDM fields)
            important_cols = ['term', 'frequency', 'relevance_score', 'cdm_domain', 'cdm_relevance', 'models_used', 'labels']
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
        """Save results as SQLite database with CDM integration"""
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"pipeline_results_{timestamp}.db"

        output_path = self.output_dir / filename

        try:
            conn = sqlite3.connect(output_path)
            cursor = conn.cursor()

            # Create CDM-enhanced schema
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS terms (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    term TEXT NOT NULL,
                    frequency INTEGER DEFAULT 1,
                    relevance_score REAL DEFAULT 1.0,
                    cdm_domain TEXT,
                    cdm_relevance TEXT,
                    cdm_concept_id TEXT,
                    models_used TEXT,
                    labels TEXT,
                    examples TEXT,
                    raw_entities_count INTEGER,
                    deduplication_applied TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS raw_entities (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    term_id INTEGER,
                    term TEXT,
                    label TEXT,
                    model TEXT,
                    start_pos INTEGER,
                    end_pos INTEGER,
                    context TEXT,
                    confidence REAL DEFAULT 1.0,
                    relevance_score REAL DEFAULT 1.0,
                    FOREIGN KEY (term_id) REFERENCES terms(id)
                )
            ''')

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS cdm_mappings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    term_id INTEGER,
                    cdm_domain TEXT NOT NULL,
                    cdm_table TEXT,
                    concept_class_id TEXT,
                    standard_concept TEXT,
                    vocabulary_id TEXT,
                    concept_code TEXT,
                    confidence REAL,
                    FOREIGN KEY (term_id) REFERENCES terms(id)
                )
            ''')

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS pipeline_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    input_files TEXT,
                    config TEXT,
                    semantic_model TEXT,
                    fuzzy_threshold REAL,
                    semantic_threshold REAL,
                    raw_entities_count INTEGER,
                    filtered_count INTEGER,
                    final_count INTEGER,
                    processing_time REAL,
                    cdm_ready_count INTEGER
                )
            ''')

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS biomedical_duplicates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER,
                    removed_term TEXT NOT NULL,
                    kept_term TEXT NOT NULL,
                    context TEXT,
                    method TEXT,
                    confidence TEXT,
                    reasoning TEXT,
                    term_data JSON,
                    FOREIGN KEY (run_id) REFERENCES pipeline_runs (id)
                )
            ''')

            # Create indexes for performance
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_terms_cdm_domain ON terms(cdm_domain)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_terms_cdm_relevance ON terms(cdm_relevance)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_raw_entities_term_id ON raw_entities(term_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_cdm_mappings_domain ON cdm_mappings(cdm_domain)')

            # Save terms with CDM fields
            terms = results.get('extraction_results', []) or results.get('ai_corrected_terms', []) or results.get('deduplicated_terms', [])
            cdm_ready_count = 0

            if terms:
                for term_data in terms:
                    # Extract CDM information
                    cdm_domain = term_data.get('cdm_domain', 'UNKNOWN')
                    cdm_relevance = term_data.get('cdm_relevance', 'MEDIUM')

                    if cdm_relevance in ['HIGH', 'MEDIUM']:
                        cdm_ready_count += 1

                    # Insert term
                    cursor.execute('''
                        INSERT INTO terms (
                            term, frequency, relevance_score, cdm_domain, cdm_relevance,
                            models_used, labels, examples, raw_entities_count, deduplication_applied
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        term_data.get('term'),
                        term_data.get('frequency', 1),
                        term_data.get('relevance_score', 1.0),
                        cdm_domain,
                        cdm_relevance,
                        json.dumps(term_data.get('models_used', [])),
                        json.dumps(term_data.get('labels', [])),
                        json.dumps(term_data.get('examples', [])),
                        len(term_data.get('raw_entities', [])),
                        term_data.get('deduplication_applied', 'none')
                    ))

                    term_id = cursor.lastrowid

                    # Insert CDM mapping if applicable
                    if cdm_domain != 'UNKNOWN':
                        cursor.execute('''
                            INSERT INTO cdm_mappings (
                                term_id, cdm_domain, cdm_table, standard_concept, confidence
                            ) VALUES (?, ?, ?, ?, ?)
                        ''', (
                            term_id,
                            cdm_domain,
                            self._get_cdm_table(cdm_domain),
                            term_data.get('term'),
                            term_data.get('relevance_score', 1.0)
                        ))

                    # Insert raw entities
                    for raw_entity in term_data.get('raw_entities', []):
                        cursor.execute('''
                            INSERT INTO raw_entities (
                                term_id, term, label, model, start_pos, end_pos,
                                context, confidence, relevance_score
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ''', (
                            term_id,
                            raw_entity.get('term'),
                            raw_entity.get('label'),
                            raw_entity.get('model'),
                            raw_entity.get('start'),
                            raw_entity.get('end'),
                            raw_entity.get('context', ''),
                            raw_entity.get('confidence', 1.0),
                            raw_entity.get('relevance_score', 1.0)
                        ))

            # Save pipeline run metadata
            metadata = results.get('metadata', {})
            config = metadata.get('config', {})
            cursor.execute('''
                INSERT INTO pipeline_runs (
                    input_files, config, semantic_model, fuzzy_threshold, semantic_threshold,
                    raw_entities_count, final_count, cdm_ready_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                json.dumps(metadata.get('input_files', [])),
                json.dumps(config),
                config.get('semantic_model', 'mini-lm'),
                config.get('fuzzy_threshold', 0.85),
                config.get('semantic_threshold', 0.9),
                metadata.get('raw_entities_count', 0),
                len(terms),
                cdm_ready_count
            ))

            # Store biomedical duplicates if available
            biomedical_duplicates = results.get('biomedical_duplicates', [])
            if biomedical_duplicates:
                run_id = cursor.lastrowid  # Get the ID of the pipeline run

                for duplicate_data in biomedical_duplicates:
                    reasoning = duplicate_data.get('biomedical_duplicate_reason', {})

                    cursor.execute('''
                        INSERT INTO biomedical_duplicates (
                            run_id, removed_term, kept_term, context, method, confidence, reasoning, term_data
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        run_id,
                        reasoning.get('removed_term', ''),
                        reasoning.get('kept_term', ''),
                        reasoning.get('context', ''),
                        reasoning.get('method', ''),
                        reasoning.get('confidence', ''),
                        json.dumps(reasoning),
                        json.dumps(duplicate_data)
                    ))

                logger.info(f"Stored {len(biomedical_duplicates)} biomedical duplicates in SQLite")

            conn.commit()
            conn.close()

            logger.info(f"SQLite results saved to: {output_path}")
            return str(output_path)

        except Exception as e:
            logger.error(f"Failed to save SQLite: {e}")
            raise

    def _get_cdm_table(self, cdm_domain: str) -> str:
        """Map CDM domain to CDM table"""
        cdm_table_mapping = {
            "PERSON_SUBJECT": "PERSON",
            "CONDITION_DISEASE": "CONDITION_OCCURRENCE",
            "DRUG_SUBSTANCE": "DRUG_EXPOSURE",
            "PROCEDURE_INTERVENTION": "PROCEDURE_OCCURRENCE",
            "MEASUREMENT_OBSERVATION": "MEASUREMENT",
            "OBSERVATION": "OBSERVATION"
        }
        return cdm_table_mapping.get(cdm_domain, "UNKNOWN")

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