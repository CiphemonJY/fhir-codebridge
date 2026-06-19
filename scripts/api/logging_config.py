"""Structured JSON logging for fhir-codebridge.

Outputs JSON log lines to stderr for SIEM ingestion:
{"timestamp": "2026-06-19T18:07:00Z", "level": "INFO", "event": "lookup", "code": "E11.9", ...}
"""

import json
import logging
import sys
from datetime import datetime, timezone


class JsonFormatter(logging.Formatter):
    """Format log records as JSON lines."""

    def format(self, record):
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Add any extra fields passed via logging.info("msg", extra={...})
        if hasattr(record, "event"):
            log_entry["event"] = record.event
        if hasattr(record, "code"):
            log_entry["code"] = record.code
        if hasattr(record, "system"):
            log_entry["system"] = record.system
        if hasattr(record, "action"):
            log_entry["action"] = record.action
        if hasattr(record, "confidence"):
            log_entry["confidence"] = record.confidence
        if hasattr(record, "ip"):
            log_entry["ip"] = record.ip
        if hasattr(record, "user_agent"):
            log_entry["user_agent"] = record.user_agent
        if hasattr(record, "duration_ms"):
            log_entry["duration_ms"] = record.duration_ms
        if hasattr(record, "error"):
            log_entry["error"] = record.error
        if record.exc_info and record.exc_info[1]:
            log_entry["exception"] = str(record.exc_info[1])
        return json.dumps(log_entry, default=str)


def setup_logging(level: str = "INFO"):
    """Configure root logger with JSON formatter."""
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter())
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    root_logger.handlers = [handler]
    return root_logger


logger = setup_logging()
