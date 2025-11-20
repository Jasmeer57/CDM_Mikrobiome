"""
Audit trail system for medical safety and regulatory compliance.
Tracks all pipeline decisions and provides complete provenance for data transformations.
"""

import logging
import json
import hashlib
import uuid
from typing import Dict, List, Optional, Any, Union
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from enum import Enum
import threading

logger = logging.getLogger(__name__)


class DecisionType(Enum):
    """Types of decisions made by the pipeline"""
    TERM_EXTRACTION = "term_extraction"
    FILTERING = "filtering"
    NORMALIZATION = "normalization"
    DEDUPLICATION = "deduplication"
    AI_CORRECTION = "ai_correction"
    UMLS_MAPPING = "umls_mapping"
    CDM_CLASSIFICATION = "cdm_classification"
    BIOMEDICAL_DEDUP = "biomedical_dedup"


class DecisionOutcome(Enum):
    """Possible outcomes of pipeline decisions"""
    KEPT = "kept"
    REMOVED = "removed"
    CORRECTED = "corrected"
    MODIFIED = "modified"
    MAPPED = "mapped"
    CLASSIFIED = "classified"


@dataclass
class DecisionRecord:
    """Record of a single pipeline decision"""
    id: str
    timestamp: datetime
    decision_type: DecisionType
    term: str
    original_term: Optional[str] = None
    outcome: DecisionOutcome = DecisionOutcome.KEPT
    reasoning: str = ""
    confidence: float = 0.0
    model_name: str = ""
    context: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    operator_id: str = ""  # Who/what made the decision
    session_id: str = ""   # Pipeline execution session
    input_hash: str = ""   # Hash of input data for integrity
    output_hash: str = ""  # Hash of output data for integrity


@dataclass
class PipelineSession:
    """Record of a pipeline execution session"""
    session_id: str
    start_time: datetime
    end_time: Optional[datetime] = None
    status: str = "running"  # running, completed, failed, cancelled
    input_files: List[str] = field(default_factory=list)
    config_hash: str = ""
    total_decisions: int = 0
    outcomes: Dict[str, int] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


class AuditTrail:
    """Comprehensive audit trail for pipeline decisions"""

    def __init__(self, db_path: str = "audit_trail.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.session_id = str(uuid.uuid4())
        self.current_session = PipelineSession(
            session_id=self.session_id,
            start_time=datetime.now(timezone.utc)
        )
        self._lock = threading.Lock()
        self._initialize_database()
        self._save_session()

    def _initialize_database(self):
        """Initialize audit trail database schema"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS pipeline_sessions (
                    session_id TEXT PRIMARY KEY,
                    start_time TEXT NOT NULL,
                    end_time TEXT,
                    status TEXT NOT NULL,
                    input_files TEXT,
                    config_hash TEXT,
                    total_decisions INTEGER DEFAULT 0,
                    outcomes TEXT,
                    metadata TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            conn.execute('''
                CREATE TABLE IF NOT EXISTS decision_records (
                    id TEXT PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    decision_type TEXT NOT NULL,
                    term TEXT NOT NULL,
                    original_term TEXT,
                    outcome TEXT NOT NULL,
                    reasoning TEXT,
                    confidence REAL DEFAULT 0.0,
                    model_name TEXT,
                    context TEXT,
                    metadata TEXT,
                    operator_id TEXT,
                    input_hash TEXT,
                    output_hash TEXT,
                    FOREIGN KEY (session_id) REFERENCES pipeline_sessions (session_id)
                )
            ''')

            conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_decision_session ON decision_records(session_id)
            ''')
            conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_decision_term ON decision_records(term)
            ''')
            conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_decision_type ON decision_records(decision_type)
            ''')
            conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_decision_timestamp ON decision_records(timestamp)
            ''')

    def _save_session(self):
        """Save current session to database"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                INSERT OR REPLACE INTO pipeline_sessions
                (session_id, start_time, end_time, status, input_files, config_hash,
                 total_decisions, outcomes, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                self.current_session.session_id,
                self.current_session.start_time.isoformat(),
                self.current_session.end_time.isoformat() if self.current_session.end_time else None,
                self.current_session.status,
                json.dumps(self.current_session.input_files),
                self.current_session.config_hash,
                self.current_session.total_decisions,
                json.dumps(self.current_session.outcomes),
                json.dumps(self.current_session.metadata)
            ))

    def record_decision(self,
                       decision_type: DecisionType,
                       term: str,
                       original_term: Optional[str] = None,
                       outcome: DecisionOutcome = DecisionOutcome.KEPT,
                       reasoning: str = "",
                       confidence: float = 0.0,
                       model_name: str = "",
                       context: str = "",
                       metadata: Optional[Dict[str, Any]] = None,
                       operator_id: str = "pipeline") -> str:
        """Record a pipeline decision"""
        with self._lock:
            decision_id = str(uuid.uuid4())

            # Calculate input/output hashes
            input_data = f"{term}|{original_term or ''}|{context}"
            input_hash = hashlib.sha256(input_data.encode()).hexdigest()

            output_data = f"{term}|{outcome}|{reasoning}"
            output_hash = hashlib.sha256(output_data.encode()).hexdigest()

            record = DecisionRecord(
                id=decision_id,
                timestamp=datetime.now(timezone.utc),
                decision_type=decision_type,
                term=term,
                original_term=original_term,
                outcome=outcome,
                reasoning=reasoning,
                confidence=confidence,
                model_name=model_name,
                context=context,
                metadata=metadata or {},
                operator_id=operator_id,
                session_id=self.session_id,
                input_hash=input_hash,
                output_hash=output_hash
            )

            # Save to database
            with sqlite3.connect(self.db_path) as conn:
                conn.execute('''
                    INSERT INTO decision_records
                    (id, timestamp, session_id, decision_type, term, original_term,
                     outcome, reasoning, confidence, model_name, context, metadata,
                     operator_id, input_hash, output_hash)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    record.id, record.timestamp.isoformat(), record.session_id,
                    record.decision_type.value, record.term, record.original_term,
                    record.outcome.value, record.reasoning, record.confidence,
                    record.model_name, record.context, json.dumps(record.metadata),
                    record.operator_id, record.input_hash, record.output_hash
                ))

            # Update session statistics
            self.current_session.total_decisions += 1
            outcome_key = outcome.value
            self.current_session.outcomes[outcome_key] = self.current_session.outcomes.get(outcome_key, 0) + 1

            self._save_session()

            logger.debug(f"Audit: Recorded {decision_type.value} decision for term '{term}' -> {outcome.value}")
            return decision_id

    def finalize_session(self, status: str = "completed"):
        """Finalize the current pipeline session"""
        self.current_session.end_time = datetime.now(timezone.utc)
        self.current_session.status = status
        self._save_session()
        logger.info(f"Audit: Session {self.session_id} finalized with status: {status}")

    def get_decision_history(self,
                           term: Optional[str] = None,
                           decision_type: Optional[DecisionType] = None,
                           session_id: Optional[str] = None,
                           limit: int = 100) -> List[DecisionRecord]:
        """Get decision history with optional filters"""
        with sqlite3.connect(self.db_path) as conn:
            query = "SELECT * FROM decision_records WHERE 1=1"
            params = []

            if term:
                query += " AND term = ?"
                params.append(term)

            if decision_type:
                query += " AND decision_type = ?"
                params.append(decision_type.value)

            if session_id:
                query += " AND session_id = ?"
                params.append(session_id)

            query += " ORDER BY timestamp DESC LIMIT ?"
            params.append(limit)

            cursor = conn.execute(query, params)
            rows = cursor.fetchall()

            records = []
            for row in rows:
                records.append(DecisionRecord(
                    id=row[0],
                    timestamp=datetime.fromisoformat(row[1]),
                    decision_type=DecisionType(row[3]),
                    term=row[4],
                    original_term=row[5],
                    outcome=DecisionOutcome(row[6]),
                    reasoning=row[7],
                    confidence=row[8],
                    model_name=row[9],
                    context=row[10],
                    metadata=json.loads(row[11]) if row[11] else {},
                    operator_id=row[12],
                    session_id=row[13],
                    input_hash=row[14],
                    output_hash=row[15]
                ))

            return records

    def get_session_summary(self, session_id: str) -> Optional[PipelineSession]:
        """Get summary of a specific session"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT * FROM pipeline_sessions WHERE session_id = ?",
                (session_id,)
            )
            row = cursor.fetchone()

            if not row:
                return None

            return PipelineSession(
                session_id=row[0],
                start_time=datetime.fromisoformat(row[1]),
                end_time=datetime.fromisoformat(row[2]) if row[2] else None,
                status=row[3],
                input_files=json.loads(row[4]) if row[4] else [],
                config_hash=row[5],
                total_decisions=row[6],
                outcomes=json.loads(row[7]) if row[7] else {},
                metadata=json.loads(row[8]) if row[8] else {}
            )

    def get_term_provenance(self, term: str) -> Dict[str, Any]:
        """Get complete provenance for a specific term"""
        decisions = self.get_decision_history(term=term, limit=50)

        provenance = {
            "term": term,
            "total_decisions": len(decisions),
            "decision_timeline": [],
            "final_outcome": "unknown",
            "transformation_history": []
        }

        for decision in decisions:
            provenance["decision_timeline"].append({
                "timestamp": decision.timestamp.isoformat(),
                "decision_type": decision.decision_type.value,
                "outcome": decision.outcome.value,
                "reasoning": decision.reasoning,
                "confidence": decision.confidence,
                "model": decision.model_name,
                "operator": decision.operator_id
            })

            if decision.original_term and decision.original_term != term:
                provenance["transformation_history"].append({
                    "from": decision.original_term,
                    "to": decision.term,
                    "decision_type": decision.decision_type.value,
                    "timestamp": decision.timestamp.isoformat(),
                    "reasoning": decision.reasoning
                })

        # Determine final outcome
        if decisions:
            provenance["final_outcome"] = decisions[-1].outcome.value

        return provenance

    def export_session_audit_report(self, session_id: str, output_path: str):
        """Export comprehensive audit report for a session"""
        session = self.get_session_summary(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")

        decisions = self.get_decision_history(session_id=session_id, limit=10000)

        report = {
            "audit_report": {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "session": asdict(session),
                "statistics": {
                    "total_decisions": len(decisions),
                    "decision_types": {},
                    "outcomes": {},
                    "models_used": set(),
                    "average_confidence": 0.0,
                    "high_confidence_decisions": 0,
                    "low_confidence_decisions": 0
                },
                "decisions": [],
                "transformation_summary": [],
                "quality_metrics": {}
            }
        }

        # Analyze decisions
        confidences = []
        transformations = []

        for decision in decisions:
            decision_dict = asdict(decision)
            decision_dict['timestamp'] = decision.timestamp.isoformat()
            decision_dict['decision_type'] = decision.decision_type.value
            decision_dict['outcome'] = decision.outcome.value
            report["audit_report"]["decisions"].append(decision_dict)

            # Statistics
            dt = decision.decision_type.value
            report["audit_report"]["statistics"]["decision_types"][dt] = \
                report["audit_report"]["statistics"]["decision_types"].get(dt, 0) + 1

            outcome = decision.outcome.value
            report["audit_report"]["statistics"]["outcomes"][outcome] = \
                report["audit_report"]["statistics"]["outcomes"].get(outcome, 0) + 1

            if decision.model_name:
                report["audit_report"]["statistics"]["models_used"].add(decision.model_name)

            if decision.confidence > 0:
                confidences.append(decision.confidence)
                if decision.confidence >= 0.8:
                    report["audit_report"]["statistics"]["high_confidence_decisions"] += 1
                elif decision.confidence < 0.5:
                    report["audit_report"]["statistics"]["low_confidence_decisions"] += 1

            if decision.original_term and decision.original_term != decision.term:
                transformations.append({
                    "original": decision.original_term,
                    "final": decision.term,
                    "decision_type": dt,
                    "reasoning": decision.reasoning
                })

        # Convert set to list for JSON serialization
        report["audit_report"]["statistics"]["models_used"] = list(
            report["audit_report"]["statistics"]["models_used"]
        )

        # Calculate averages
        if confidences:
            report["audit_report"]["statistics"]["average_confidence"] = sum(confidences) / len(confidences)

        report["audit_report"]["transformation_summary"] = transformations

        # Quality metrics
        total = len(decisions)
        if total > 0:
            report["audit_report"]["quality_metrics"] = {
                "removal_rate": report["audit_report"]["statistics"]["outcomes"].get("removed", 0) / total,
                "correction_rate": report["audit_report"]["statistics"]["outcomes"].get("corrected", 0) / total,
                "modification_rate": report["audit_report"]["statistics"]["outcomes"].get("modified", 0) / total,
                "data_integrity_score": 1.0 - (report["audit_report"]["statistics"]["low_confidence_decisions"] / total)
            }

        # Save report
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        logger.info(f"Audit report exported to: {output_path}")

    def validate_data_integrity(self, session_id: str) -> Dict[str, Any]:
        """Validate data integrity for a session"""
        decisions = self.get_decision_history(session_id=session_id, limit=10000)

        integrity_issues = []
        hash_mismatches = 0
        missing_contexts = 0
        low_confidence_critical = 0

        for decision in decisions:
            # Check for critical decisions with low confidence
            critical_types = [DecisionType.AI_CORRECTION, DecisionType.BIOMEDICAL_DEDUP]
            if (decision.decision_type in critical_types and
                decision.confidence < 0.5 and
                decision.outcome in [DecisionOutcome.REMOVED, DecisionOutcome.CORRECTED]):
                low_confidence_critical += 1
                integrity_issues.append({
                    "type": "low_confidence_critical",
                    "decision_id": decision.id,
                    "term": decision.term,
                    "confidence": decision.confidence,
                    "outcome": decision.outcome.value
                })

            # Check for missing context in important decisions
            if decision.decision_type in critical_types and not decision.context:
                missing_contexts += 1

            # Basic hash validation (simplified)
            if not decision.input_hash or not decision.output_hash:
                hash_mismatches += 1

        total_decisions = len(decisions)
        integrity_score = 1.0

        if total_decisions > 0:
            integrity_score -= (low_confidence_critical / total_decisions) * 0.5
            integrity_score -= (missing_contexts / total_decisions) * 0.3
            integrity_score -= (hash_mismatches / total_decisions) * 0.2

        return {
            "session_id": session_id,
            "total_decisions": total_decisions,
            "integrity_score": max(0.0, integrity_score),
            "issues_found": len(integrity_issues),
            "low_confidence_critical": low_confidence_critical,
            "missing_contexts": missing_contexts,
            "hash_mismatches": hash_mismatches,
            "integrity_issues": integrity_issues,
            "validation_timestamp": datetime.now(timezone.utc).isoformat()
        }


# Global audit trail instance
_audit_trail = None

def get_audit_trail(db_path: str = "audit_trail.db") -> AuditTrail:
    """Get global audit trail instance"""
    global _audit_trail
    if _audit_trail is None:
        _audit_trail = AuditTrail(db_path)
    return _audit_trail

def finalize_audit_trail():
    """Finalize the global audit trail"""
    global _audit_trail
    if _audit_trail:
        _audit_trail.finalize_session()
        _audit_trail = None