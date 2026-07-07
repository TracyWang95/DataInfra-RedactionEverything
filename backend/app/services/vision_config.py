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


def merge_optional_type_lists(
    primary: Sequence[str] | None,
    legacy: Sequence[str] | None,
) -> list[str] | None:
    """Merge two optional selection lists while preserving explicit disable.

    ``None`` means no selection was supplied and downstream defaults should be
    used. ``[]`` means the user explicitly disabled that visual stage. Older
    exported configs may still carry split visual fields; callers merge those
    aliases into the unified visual feature list before scheduling work.
    """

    if primary is None and legacy is None:
        return None

    merged: list[str] = []
    seen: set[str] = set()
    for values in (primary, legacy):
        if values is None:
            continue
        for item in values:
            value = str(item)
            if value in seen:
                continue
            seen.add(value)
            merged.append(value)
    return merged
