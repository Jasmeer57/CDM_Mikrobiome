"""
Enhanced Logging and Audit Trail Module for CDM Pipeline
Provides comprehensive logging for compliance and monitoring
"""

import logging
import json
import time
import hashlib
import os
import sys
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field, asdict
from pathlib import Path
import threading
from enum import Enum
import traceback
import uuid

logger = logging.getLogger(__name__)

class LogLevel(Enum):
    """Log levels for the audit system"""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"

class EventType(Enum):
    """Types of events to log"""
    SYSTEM_START = "system_start"
    SYSTEM_STOP = "system_stop"
    INPUT_PROCESSING = "input_processing"
    EXTRACTION_START = "extraction_start"
    EXTRACTION_COMPLETE = "extraction_complete"
    FILTERING_APPLIED = "filtering_applied"
    VALIDATION_COMPLETE = "validation_complete"
    SAFETY_CHECK = "safety_check"
    ERROR_OCCURRED = "error_occurred"
    USER_ACTION = "user_action"
    CONFIG_CHANGE = "config_change"
    PERFORMANCE_METRIC = "performance_metric"
    COMPLIANCE_CHECK = "compliance_check"

@dataclass
class AuditEvent:
    """Represents an audit log event"""
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    event_type: str = ""
    level: str = LogLevel.INFO.value
    message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)
    user_id: Optional[str] = None
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    source_file: Optional[str] = None
    processing_stage: Optional[str] = None
    performance_metrics: Dict[str, float] = field(default_factory=dict)
    compliance_flags: List[str] = field(default_factory=list)
    entity_count: Optional[int] = None
    confidence_stats: Dict[str, float] = field(default_factory=dict)
    error_info: Optional[Dict[str, Any]] = None
    stack_trace: Optional[str] = None
    security_context: Dict[str, Any] = field(default_factory=dict)

class AuditLogger:
    """Enhanced audit logger for compliance and monitoring"""

    def __init__(self, log_directory: str = "logs", enable_file_logging: bool = True,
                 enable_console_logging: bool = True, log_level: LogLevel = LogLevel.INFO):
        self.log_directory = Path(log_directory)
        self.enable_file_logging = enable_file_logging
        self.enable_console_logging = enable_console_logging
        self.log_level = log_level
        self.session_id = str(uuid.uuid4())

        # Ensure log directory exists
        self.log_directory.mkdir(parents=True, exist_ok=True)

        # Setup structured loggers
        self.setup_loggers()

        # Thread safety lock
        self._lock = threading.Lock()

        # In-memory buffer for recent events
        self.event_buffer = []
        self.buffer_size = 1000

        # Compliance settings
        self.log_retention_days = 90
        self.enable_data_hashing = True

        logger.info(f"🔍 Audit logger initialized: session_id={self.session_id}")

    def setup_loggers(self):
        """Setup structured logging configuration"""
        # Main application logger
        self.app_logger = logging.getLogger("cdm_pipeline")
        self.app_logger.setLevel(getattr(logging, self.log_level.value))

        # Security logger
        self.security_logger = logging.getLogger("cdm_pipeline.security")
        self.security_logger.setLevel(logging.INFO)

        # Performance logger
        self.performance_logger = logging.getLogger("cdm_pipeline.performance")
        self.performance_logger.setLevel(logging.INFO)

        # Compliance logger
        self.compliance_logger = logging.getLogger("cdm_pipeline.compliance")
        self.compliance_logger.setLevel(logging.INFO)

        # Clear existing handlers
        for logger_obj in [self.app_logger, self.security_logger, self.performance_logger, self.compliance_logger]:
            logger_obj.handlers.clear()

        # Console handler
        if self.enable_console_logging:
            console_handler = logging.StreamHandler(sys.stdout)
            console_formatter = logging.Formatter(
                '%(asctime)s | %(name)s | %(levelname)s | %(message)s'
            )
            console_handler.setFormatter(console_formatter)
            self.app_logger.addHandler(console_handler)

        # File handlers
        if self.enable_file_logging:
            self._setup_file_handlers()

    def _setup_file_handlers(self):
        """Setup file-based logging with rotation"""
        # Main log file
        main_log_file = self.log_directory / "cdm_pipeline.log"
        main_handler = logging.FileHandler(main_log_file, mode='a', encoding='utf-8')
        main_formatter = logging.Formatter(
            '%(asctime)s | %(name)s | %(levelname)s | %(message)s'
        )
        main_handler.setFormatter(main_formatter)
        self.app_logger.addHandler(main_handler)

        # Structured audit log (JSON)
        audit_log_file = self.log_directory / f"audit_{datetime.now().strftime('%Y%m%d')}.jsonl"
        audit_handler = logging.FileHandler(audit_log_file, mode='a', encoding='utf-8')
        # Use custom formatter for structured logging
        self.audit_handler = audit_handler
        self.audit_log_file = audit_log_file

        # Security log
        security_log_file = self.log_directory / "security.log"
        security_handler = logging.FileHandler(security_log_file, mode='a', encoding='utf-8')
        security_formatter = logging.Formatter(
            '%(asctime)s | SECURITY | %(levelname)s | %(message)s'
        )
        security_handler.setFormatter(security_formatter)
        self.security_logger.addHandler(security_handler)

        # Performance log
        performance_log_file = self.log_directory / "performance.log"
        performance_handler = logging.FileHandler(performance_log_file, mode='a', encoding='utf-8')
        performance_formatter = logging.Formatter(
            '%(asctime)s | PERF | %(message)s'
        )
        performance_handler.setFormatter(performance_formatter)
        self.performance_logger.addHandler(performance_handler)

    def log_event(self, event_type: EventType, message: str, level: LogLevel = LogLevel.INFO,
                  details: Dict[str, Any] = None, user_id: str = None,
                  source_file: str = None, processing_stage: str = None,
                  performance_metrics: Dict[str, float] = None,
                  compliance_flags: List[str] = None, entity_count: int = None,
                  confidence_stats: Dict[str, float] = None, error_info: Dict[str, Any] = None,
                  security_context: Dict[str, Any] = None):
        """Log an audit event"""
        with self._lock:
            event = AuditEvent(
                event_type=event_type.value,
                level=level.value,
                message=message,
                details=details or {},
                user_id=user_id,
                session_id=self.session_id,
                source_file=source_file,
                processing_stage=processing_stage,
                performance_metrics=performance_metrics or {},
                compliance_flags=compliance_flags or [],
                entity_count=entity_count,
                confidence_stats=confidence_stats or {},
                error_info=error_info,
                security_context=security_context or {}
            )

            # Add stack trace for errors
            if level in [LogLevel.ERROR, LogLevel.CRITICAL]:
                event.stack_trace = traceback.format_exc()

            # Hash sensitive data if enabled
            if self.enable_data_hashing:
                event = self._hash_sensitive_data(event)

            # Add to buffer
            self.event_buffer.append(event)
            if len(self.event_buffer) > self.buffer_size:
                self.event_buffer.pop(0)

            # Log to appropriate channels
            self._write_audit_event(event)

            # Standard logging for visibility
            log_message = f"[{event_type.value.upper()}] {message}"
            if details:
                log_message += f" | Details: {json.dumps(details, default=str)}"
            if performance_metrics:
                log_message += f" | Metrics: {json.dumps(performance_metrics)}"

            if level == LogLevel.DEBUG:
                self.app_logger.debug(log_message)
            elif level == LogLevel.INFO:
                self.app_logger.info(log_message)
            elif level == LogLevel.WARNING:
                self.app_logger.warning(log_message)
            elif level == LogLevel.ERROR:
                self.app_logger.error(log_message)
            elif level == LogLevel.CRITICAL:
                self.app_logger.critical(log_message)

    def _hash_sensitive_data(self, event: AuditEvent) -> AuditEvent:
        """Hash potentially sensitive data in the event"""
        if event.source_file:
            # Hash file path but preserve extension
            path_parts = event.source_file.split('/')
            if len(path_parts) > 1:
                filename = path_parts[-1]
                dir_hash = hashlib.sha256('/'.join(path_parts[:-1]).encode()).hexdigest()[:8]
                event.source_file = f"{dir_hash}/{filename}"

        # Hash user ID if present
        if event.user_id:
            event.user_id = hashlib.sha256(event.user_id.encode()).hexdigest()[:16]

        # Hash any potential PII in details
        if 'text_content' in event.details:
            text = event.details['text_content']
            if len(text) > 100:  # Hash long text content
                event.details['text_content_hash'] = hashlib.sha256(text.encode()).hexdigest()[:16]
                event.details['text_content_length'] = len(text)
                del event.details['text_content']

        return event

    def _write_audit_event(self, event: AuditEvent):
        """Write audit event to structured log file"""
        if hasattr(self, 'audit_handler'):
            try:
                audit_line = json.dumps(asdict(event), default=str, ensure_ascii=False)
                self.audit_handler.write(audit_line + '\n')
                self.audit_handler.flush()
            except Exception as e:
                self.app_logger.error(f"Failed to write audit log: {e}")

    def log_system_start(self, config: Dict[str, Any], user_id: str = None):
        """Log system startup"""
        self.log_event(
            event_type=EventType.SYSTEM_START,
            message="CDM Pipeline started",
            level=LogLevel.INFO,
            details={
                'version': config.get('version', 'unknown'),
                'config_hash': hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()[:16],
                'python_version': sys.version,
                'working_directory': os.getcwd()
            },
            user_id=user_id,
            compliance_flags=['system_startup']
        )

    def log_input_processing(self, input_file: str, text_length: int, validation_result: Dict[str, Any]):
        """Log input processing stage"""
        self.log_event(
            event_type=EventType.INPUT_PROCESSING,
            message=f"Processing input file: {os.path.basename(input_file)}",
            level=LogLevel.INFO,
            source_file=input_file,
            processing_stage="input_validation",
            details={
                'file_size': text_length,
                'validation_passed': validation_result.get('is_valid', False),
                'validation_errors': len(validation_result.get('errors', [])),
                'validation_warnings': len(validation_result.get('warnings', []))
            },
            compliance_flags=['input_processing']
        )

    def log_extraction_start(self, model: str, text_chunks: int, parameters: Dict[str, Any]):
        """Log extraction start"""
        self.log_event(
            event_type=EventType.EXTRACTION_START,
            message=f"Starting entity extraction with model: {model}",
            level=LogLevel.INFO,
            processing_stage="extraction",
            details={
                'model': model,
                'text_chunks': text_chunks,
                'parameters': {k: str(v) for k, v in parameters.items()}
            },
            compliance_flags=['model_usage']
        )

    def log_extraction_complete(self, entities_extracted: int, processing_time: float,
                               confidence_stats: Dict[str, float], model: str):
        """Log extraction completion"""
        self.log_event(
            event_type=EventType.EXTRACTION_COMPLETE,
            message=f"Entity extraction completed: {entities_extracted} entities",
            level=LogLevel.INFO,
            processing_stage="extraction",
            entity_count=entities_extracted,
            confidence_stats=confidence_stats,
            performance_metrics={'extraction_time': processing_time},
            details={
                'model': model,
                'entities_per_second': entities_extracted / processing_time if processing_time > 0 else 0
            },
            compliance_flags=['extraction_complete']
        )

    def log_filtering_applied(self, original_count: int, filtered_count: int,
                            filtering_type: str, filtering_details: Dict[str, Any]):
        """Log filtering application"""
        reduction_percentage = ((original_count - filtered_count) / original_count * 100) if original_count > 0 else 0

        self.log_event(
            event_type=EventType.FILTERING_APPLIED,
            message=f"Applied {filtering_type} filtering: {original_count} → {filtered_count} entities",
            level=LogLevel.INFO,
            processing_stage="filtering",
            entity_count=filtered_count,
            details={
                'original_count': original_count,
                'filtered_count': filtered_count,
                'reduction_percentage': reduction_percentage,
                'filtering_type': filtering_type,
                'filtering_details': filtering_details
            },
            compliance_flags=['data_filtering']
        )

    def log_validation_complete(self, validation_result: Dict[str, Any], processing_time: float):
        """Log validation completion"""
        self.log_event(
            event_type=EventType.VALIDATION_COMPLETE,
            message=f"Validation completed: {validation_result.get('is_valid', False)}",
            level=LogLevel.INFO,
            processing_stage="validation",
            performance_metrics={'validation_time': processing_time},
            details={
                'is_valid': validation_result.get('is_valid', False),
                'total_issues': validation_result.get('summary', {}).get('total_issues', 0),
                'issues_by_level': validation_result.get('summary', {}).get('issues_by_level', {})
            },
            compliance_flags=['quality_assurance']
        )

    def log_safety_check(self, safety_analysis: Dict[str, Any]):
        """Log safety analysis results"""
        self.log_event(
            event_type=EventType.SAFETY_CHECK,
            message=f"Safety check completed: {safety_analysis.get('safe_to_process', False)}",
            level=LogLevel.INFO,
            processing_stage="safety",
            details={
                'risk_level': safety_analysis.get('overall_risk_level', {}).value if hasattr(safety_analysis.get('overall_risk_level'), 'value') else safety_analysis.get('overall_risk_level'),
                'detected_issues': len(safety_analysis.get('detected_issues', [])),
                'has_medical_disclaimer': safety_analysis.get('has_medical_disclaimer', False),
                'is_research_content': safety_analysis.get('is_research_content', False)
            },
            compliance_flags=['safety_compliance']
        )

    def log_error(self, error_message: str, error_type: str = "general_error",
                 context: Dict[str, Any] = None, user_id: str = None):
        """Log error event"""
        self.log_event(
            event_type=EventType.ERROR_OCCURRED,
            message=error_message,
            level=LogLevel.ERROR,
            error_info={
                'error_type': error_type,
                'context': context or {}
            },
            user_id=user_id,
            compliance_flags=['error_occurred']
        )

    def log_performance_metrics(self, metrics: Dict[str, float], stage: str = None):
        """Log performance metrics"""
        self.log_event(
            event_type=EventType.PERFORMANCE_METRIC,
            message=f"Performance metrics for {stage or 'pipeline'}",
            level=LogLevel.INFO,
            processing_stage=stage,
            performance_metrics=metrics,
            compliance_flags=['performance_monitoring']
        )

        # Also log to performance file
        perf_message = f"Stage: {stage or 'unknown'} | {json.dumps(metrics)}"
        self.performance_logger.info(perf_message)

    def log_security_event(self, event_message: str, severity: str = "info",
                          security_details: Dict[str, Any] = None):
        """Log security-related event"""
        self.log_event(
            event_type=EventType.COMPLIANCE_CHECK,
            message=f"Security: {event_message}",
            level=LogLevel.WARNING if severity == "warning" else LogLevel.INFO,
            security_context=security_details or {},
            compliance_flags=['security_event']
        )

        # Also log to security file
        self.security_logger.warning(f"{event_message} | {json.dumps(security_details or {})}")

    def log_user_action(self, action: str, user_id: str = None, action_details: Dict[str, Any] = None):
        """Log user action"""
        self.log_event(
            event_type=EventType.USER_ACTION,
            message=f"User action: {action}",
            level=LogLevel.INFO,
            user_id=user_id,
            details=action_details or {},
            compliance_flags=['user_activity']
        )

    def get_session_summary(self) -> Dict[str, Any]:
        """Get summary of current session activity"""
        if not self.event_buffer:
            return {}

        events_by_type = {}
        events_by_level = {}
        total_entities = 0
        total_processing_time = 0.0

        for event in self.event_buffer:
            # Count by type
            events_by_type[event.event_type] = events_by_type.get(event.event_type, 0) + 1

            # Count by level
            events_by_level[event.level] = events_by_level.get(event.level, 0) + 1

            # Aggregate metrics
            if event.entity_count:
                total_entities += event.entity_count

            if 'processing_time' in event.performance_metrics:
                total_processing_time += event.performance_metrics['processing_time']

        return {
            'session_id': self.session_id,
            'total_events': len(self.event_buffer),
            'events_by_type': events_by_type,
            'events_by_level': events_by_level,
            'total_entities_processed': total_entities,
            'total_processing_time': total_processing_time,
            'average_entities_per_extraction': total_entities / max(1, events_by_type.get('extraction_complete', 1))
        }

    def export_audit_log(self, output_file: str, start_time: str = None, end_time: str = None) -> bool:
        """Export audit logs to file"""
        try:
            events_to_export = []

            # Filter events by time range if specified
            for event in self.event_buffer:
                event_time = event.timestamp
                if start_time and event_time < start_time:
                    continue
                if end_time and event_time > end_time:
                    continue
                events_to_export.append(asdict(event))

            # Write to output file
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump({
                    'export_timestamp': datetime.now(timezone.utc).isoformat(),
                    'session_id': self.session_id,
                    'total_events': len(events_to_export),
                    'events': events_to_export
                }, f, indent=2, ensure_ascii=False, default=str)

            self.app_logger.info(f"Audit log exported to {output_file}: {len(events_to_export)} events")
            return True

        except Exception as e:
            self.app_logger.error(f"Failed to export audit log: {e}")
            return False

    def cleanup_old_logs(self):
        """Remove old log files based on retention policy"""
        try:
            current_time = time.time()
            cutoff_time = current_time - (self.log_retention_days * 24 * 60 * 60)

            for log_file in self.log_directory.glob("*.jsonl"):
                if log_file.stat().st_mtime < cutoff_time:
                    log_file.unlink()
                    self.app_logger.info(f"Removed old log file: {log_file}")

        except Exception as e:
            self.app_logger.error(f"Failed to cleanup old logs: {e}")

# Global audit logger instance
_audit_logger = None

def get_audit_logger() -> AuditLogger:
    """Get the global audit logger instance"""
    global _audit_logger
    if _audit_logger is None:
        _audit_logger = AuditLogger()
    return _audit_logger

def configure_audit_logging(log_directory: str = "logs", log_level: LogLevel = LogLevel.INFO):
    """Configure the global audit logger"""
    global _audit_logger
    _audit_logger = AuditLogger(log_directory=log_directory, log_level=log_level)
    return _audit_logger

# Convenience functions for common logging tasks
def log_pipeline_start(config: Dict[str, Any], user_id: str = None):
    """Log pipeline startup"""
    get_audit_logger().log_system_start(config, user_id)

def log_pipeline_complete(total_time: float, entities_processed: int, final_results: Dict[str, Any]):
    """Log pipeline completion"""
    get_audit_logger().log_performance_metrics(
        {
            'total_pipeline_time': total_time,
            'entities_per_second': entities_processed / total_time if total_time > 0 else 0,
            'success_rate': final_results.get('success_rate', 0.0)
        },
        stage="pipeline_complete"
    )

def log_compliance_check(check_type: str, passed: bool, details: Dict[str, Any] = None):
    """Log compliance check"""
    get_audit_logger().log_event(
        event_type=EventType.COMPLIANCE_CHECK,
        message=f"Compliance check {check_type}: {'PASSED' if passed else 'FAILED'}",
        level=LogLevel.INFO if passed else LogLevel.WARNING,
        details=details or {},
        compliance_flags=['compliance_check']
    )