"""Audit logging for sensitive operations."""
import logging
import os
import json
from datetime import datetime, timezone
from typing import Optional

from app.core.config import settings

# Configure audit logger
_audit_logger = logging.getLogger("audit")
_audit_logger.setLevel(logging.INFO)
_audit_logger.propagate = False

# File handler
_log_dir = os.path.join(settings.DATA_DIR, "audit")
os.makedirs(_log_dir, exist_ok=True)
_handler = logging.FileHandler(
    os.path.join(_log_dir, "audit.log"),
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
    detail: Optional[dict] = None,
) -> None:
    """Write a structured audit log entry."""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "user": user,
        "detail": detail or {},
    }
    _audit_logger.info(json.dumps(entry, ensure_ascii=False))
