"""
匿名化执行服务包
Re-export public API for backward compatibility.

Usage:
    from app.services.redaction import Redactor, RedactionContext, build_preview_entity_map
"""
from app.services.redaction.image_redactor import ImageRedactorMixin
from app.services.redaction.replacement_strategy import RedactionContext, build_preview_entity_map
from app.services.redaction.text_redactor import TextRedactorMixin

# Redactor is defined in the parent redactor.py (thin orchestrator)
# and re-exported here once that module imports it.
# To avoid circular imports, we lazily expose Redactor via __getattr__.

def __getattr__(name: str):
    if name == "Redactor":
        from app.services.redactor import Redactor
        return Redactor
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "Redactor",
    "RedactionContext",
    "build_preview_entity_map",
    "TextRedactorMixin",
    "ImageRedactorMixin",
]
