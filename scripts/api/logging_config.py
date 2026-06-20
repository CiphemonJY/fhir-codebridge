"""Structured JSON logging for fhir-codebridge.

Outputs JSON log lines to stderr for SIEM ingestion:
{"timestamp": "2026-06-19T18:07:00Z", "level": "INFO", "event": "lookup", "code": "E11.9", ...}

Audit log rotation: set CODEBRIDGE_AUDIT_LOG_MAX_BYTES (default 10MB) and
CODEBRIDGE_AUDIT_LOG_BACKUP_COUNT (default 5) to control rotation.
"""

import json
import logging
import logging.handlers
import os
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
        for attr in ("event", "code", "system", "action", "confidence", "ip",
                      "user_agent", "duration_ms", "error"):
            if hasattr(record, attr):
                log_entry[attr] = getattr(record, attr)
        if record.exc_info and record.exc_info[1]:
            log_entry["exception"] = str(record.exc_info[1])
        return json.dumps(log_entry, default=str)


def get_audit_log_handler():
    """Get a rotating file handler for audit logs.

    Configurable via environment:
    - CODEBRIDGE_AUDIT_LOG_MAX_BYTES (default 10485760 = 10MB)
    - CODEBRIDGE_AUDIT_LOG_BACKUP_COUNT (default 5)
    """
    max_bytes = int(os.environ.get("CODEBRIDGE_AUDIT_LOG_MAX_BYTES", "10485760"))
    backup_count = int(os.environ.get("CODEBRIDGE_AUDIT_LOG_BACKUP_COUNT", "5"))
    log_path = os.environ.get("CODEBRIDGE_AUDIT_LOG", "data/audit.log")

    # Ensure parent directory exists
    import os as _os
    _os.makedirs(_os.path.dirname(log_path) if _os.path.dirname(log_path) else ".", exist_ok=True)

    handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=max_bytes, backupCount=backup_count
    )
    handler.setFormatter(JsonFormatter())
    return handler


def setup_logging(level: str = "INFO"):
    """Configure root logger with JSON formatter."""
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter())
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    root_logger.handlers = [handler]
    return root_logger


logger = setup_logging()
