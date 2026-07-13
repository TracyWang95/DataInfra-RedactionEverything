"""Audit logging for sensitive operations."""
import json
import logging
import os
from datetime import UTC, datetime

from app.core.config import settings

# Configure audit logger
_audit_logger = logging.getLogger("audit")
_audit_logger.setLevel(logging.INFO)
_audit_logger.propagate = False

# File handler with rotation — audit.log is compliance-critical and grew
# unbounded before (disk-fill risk); 50MB x 10 keeps ~500MB of history.
from logging.handlers import RotatingFileHandler

_log_dir = os.path.join(settings.DATA_DIR, "audit")
os.makedirs(_log_dir, exist_ok=True)
_handler = RotatingFileHandler(
    os.path.join(_log_dir, "audit.log"),
    maxBytes=50 * 1024 * 1024,
    backupCount=10,
    encoding="utf-8",
)
_handler.setFormatter(logging.Formatter("%(message)s"))
if not any(isinstance(handler, logging.FileHandler) and getattr(handler, "baseFilename", None) == _handler.baseFilename for handler in _audit_logger.handlers):
    _audit_logger.addHandler(_handler)


def audit_log(
    action: str,
    resource_type: str,
    resource_id: str = "",
    user: str = "anonymous",
    detail: dict | None = None,
) -> None:
    """Write a structured audit log entry."""
    entry = {
        "timestamp": datetime.now(UTC).isoformat(),
        "action": action,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "user": user,
        "detail": detail or {},
    }
    _audit_logger.info(json.dumps(entry, ensure_ascii=False))
