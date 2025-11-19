"""
SQLite Database Models for CDM Pipeline
"""

import sqlite3
import json
import logging
from datetime import datetime
from typing import List, Dict, Optional, Any
from contextlib import contextmanager
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)

@dataclass
class EntityRecord:
    """Database model for extracted entities."""
    id: Optional[int] = None
    entity: str = ""
    entity_type: str = ""
    confidence: float = 0.0
    context: str = ""
    source: str = ""
    chunk_id: Optional[str] = None
    text_hash: Optional[str] = None
    timestamp: Optional[datetime] = None
    quality_score: Optional[float] = None
    metadata: Optional[Dict[str, Any]] = None

@dataclass
class ExtractionRecord:
    """Database model for extraction runs."""
    id: Optional[int] = None
    input_file: Optional[str] = None
    text_hash: str = ""
    total_entities: int = 0
    processing_time: float = 0.0
    model_used: str = ""
    chunk_count: int = 0
    created_at: Optional[datetime] = None
    config: Optional[Dict[str, Any]] = None
    statistics: Optional[Dict[str, Any]] = None

class CDMDatabase:
    """SQLite database manager for CDM pipeline."""

    def __init__(self, db_path: str = "cdm_pipeline.db"):
        self.db_path = db_path
        self._init_database()

    @contextmanager
    def _get_connection(self):
        """Context manager for database connections."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _init_database(self):
        """Initialize database tables."""
        with self._get_connection() as conn:
            # Create entities table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS entities (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    entity TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    context TEXT,
                    source TEXT,
                    chunk_id TEXT,
                    text_hash TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    quality_score REAL,
                    metadata TEXT,
                    UNIQUE(entity, entity_type, text_hash)
                )
            """)

            # Create extractions table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS extractions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    input_file TEXT,
                    text_hash TEXT NOT NULL UNIQUE,
                    total_entities INTEGER DEFAULT 0,
                    processing_time REAL DEFAULT 0.0,
                    model_used TEXT,
                    chunk_count INTEGER DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    config TEXT,
                    statistics TEXT
                )
            """)

            # Create indexes for performance
            conn.execute("CREATE INDEX IF NOT EXISTS idx_entity_type ON entities(entity_type)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_text_hash ON entities(text_hash)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_timestamp ON entities(timestamp)")

            conn.commit()
            logger.info(f"Database initialized: {self.db_path}")

    def save_entities(self, entities: List[Dict], extraction_metadata: Dict) -> int:
        """Save entities to database."""
        if not entities:
            return 0

        text_hash = extraction_metadata.get('text_hash', '')
        model_used = extraction_metadata.get('model_used', 'unknown')

        with self._get_connection() as conn:
            # Save extraction record
            config_json = json.dumps(extraction_metadata.get('extraction_config', {}))
            statistics_json = json.dumps(extraction_metadata.get('extraction_statistics', {}))

            try:
                cursor = conn.execute("""
                    INSERT OR REPLACE INTO extractions
                    (input_file, text_hash, total_entities, model_used, chunk_count, config, statistics)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    extraction_metadata.get('input_file'),
                    text_hash,
                    len(entities),
                    model_used,
                    extraction_metadata.get('chunk_count', 0),
                    config_json,
                    statistics_json
                ))
                extraction_id = cursor.lastrowid
            except sqlite3.IntegrityError as e:
                logger.warning(f"Extraction already exists for text_hash: {text_hash}")
                # Get existing extraction ID
                cursor = conn.execute(
                    "SELECT id FROM extractions WHERE text_hash = ?", (text_hash,)
                )
                extraction_id = cursor.fetchone()['id']

            # Save entities
            saved_count = 0
            for entity_data in entities:
                try:
                    metadata_json = json.dumps(entity_data.get('metadata', {}))
                    cursor = conn.execute("""
                        INSERT OR IGNORE INTO entities
                        (entity, entity_type, confidence, context, source, chunk_id, text_hash,
                         quality_score, metadata)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        entity_data.get('entity'),
                        entity_data.get('entity_type'),
                        entity_data.get('confidence', 0.0),
                        entity_data.get('context', ''),
                        entity_data.get('source', ''),
                        entity_data.get('chunk_id'),
                        text_hash,
                        entity_data.get('quality_score'),
                        metadata_json
                    ))
                    if cursor.rowcount > 0:
                        saved_count += 1
                except Exception as e:
                    logger.error(f"Error saving entity {entity_data.get('entity')}: {e}")

            conn.commit()
            logger.info(f"Saved {saved_count}/{len(entities)} entities to database")
            return saved_count

    def get_entities(self, entity_type: Optional[str] = None,
                     limit: int = 100, offset: int = 0) -> List[EntityRecord]:
        """Retrieve entities from database."""
        with self._get_connection() as conn:
            query = "SELECT * FROM entities"
            params = []

            if entity_type:
                query += " WHERE entity_type = ?"
                params.append(entity_type)

            query += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])

            cursor = conn.execute(query, params)
            results = []

            for row in cursor.fetchall():
                metadata = {}
                if row['metadata']:
                    try:
                        metadata = json.loads(row['metadata'])
                    except json.JSONDecodeError:
                        pass

                results.append(EntityRecord(
                    id=row['id'],
                    entity=row['entity'],
                    entity_type=row['entity_type'],
                    confidence=row['confidence'],
                    context=row['context'],
                    source=row['source'],
                    chunk_id=row['chunk_id'],
                    text_hash=row['text_hash'],
                    timestamp=datetime.fromisoformat(row['timestamp']) if row['timestamp'] else None,
                    quality_score=row['quality_score'],
                    metadata=metadata
                ))

            return results

    def get_extraction_history(self, limit: int = 50) -> List[ExtractionRecord]:
        """Get extraction history."""
        with self._get_connection() as conn:
            cursor = conn.execute("""
                SELECT * FROM extractions
                ORDER BY created_at DESC
                LIMIT ?
            """, (limit,))

            results = []
            for row in cursor.fetchall():
                config = {}
                statistics = {}

                try:
                    if row['config']:
                        config = json.loads(row['config'])
                    if row['statistics']:
                        statistics = json.loads(row['statistics'])
                except json.JSONDecodeError:
                    pass

                results.append(ExtractionRecord(
                    id=row['id'],
                    input_file=row['input_file'],
                    text_hash=row['text_hash'],
                    total_entities=row['total_entities'],
                    processing_time=row['processing_time'],
                    model_used=row['model_used'],
                    chunk_count=row['chunk_count'],
                    created_at=datetime.fromisoformat(row['created_at']) if row['created_at'] else None,
                    config=config,
                    statistics=statistics
                ))

            return results

    def get_statistics(self) -> Dict[str, Any]:
        """Get database statistics."""
        with self._get_connection() as conn:
            # Entity counts by type
            cursor = conn.execute("""
                SELECT entity_type, COUNT(*) as count
                FROM entities
                GROUP BY entity_type
            """)
            entity_counts = {row['entity_type']: row['count'] for row in cursor.fetchall()}

            # Total counts
            cursor = conn.execute("SELECT COUNT(*) as total FROM entities")
            total_entities = cursor.fetchone()['total']

            cursor = conn.execute("SELECT COUNT(*) as total FROM extractions")
            total_extractions = cursor.fetchone()['total']

            # Average confidence
            cursor = conn.execute("SELECT AVG(confidence) as avg_conf FROM entities")
            avg_confidence = cursor.fetchone()['avg_conf'] or 0.0

            return {
                'total_entities': total_entities,
                'total_extractions': total_extractions,
                'entity_type_distribution': entity_counts,
                'average_confidence': round(avg_confidence, 3),
                'database_size_mb': round(self._get_database_size(), 2)
            }

    def _get_database_size(self) -> float:
        """Get database file size in MB."""
        try:
            import os
            return os.path.getsize(self.db_path) / (1024 * 1024)
        except OSError:
            return 0.0

    def cleanup_old_entities(self, days: int = 30) -> int:
        """Remove entities older than specified days."""
        with self._get_connection() as conn:
            cursor = conn.execute("""
                DELETE FROM entities
                WHERE timestamp < datetime('now', '-{} days')
            """.format(days))
            deleted_count = cursor.rowcount
            conn.commit()
            logger.info(f"Cleaned up {deleted_count} old entities")
            return deleted_count

# Database instance for global use
_database_instance = None

def get_database(db_path: str = "cdm_pipeline.db") -> CDMDatabase:
    """Get singleton database instance."""
    global _database_instance
    if _database_instance is None:
        _database_instance = CDMDatabase(db_path)
    return _database_instance