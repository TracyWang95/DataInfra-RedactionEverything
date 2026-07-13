from collections.abc import Mapping, Sequence
from typing import Any


def resolve_optional_type_list(config: Mapping[str, Any], *keys: str) -> list[str] | None:
    """Return an explicit type list while preserving missing config as default.

    ``None`` means the caller did not provide a selection, so the orchestrator
    can apply its default enabled type set. An empty list means the user
    explicitly disabled that pipeline and must be forwarded as-is.
    """

    for key in keys:
        if key not in config:
            continue
        value = config.get(key)
        if value is None:
            continue
        if isinstance(value, str):
            return [value]
        if isinstance(value, Sequence):
            return [str(item) for item in value]
        return [str(value)]
    return None


