"""Human-review friendly DICOM attribute difference output."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydicom.dataset import Dataset

from .reader import read_dataset


def _display_value(element: Any) -> Any:
    value = element.value
    if element.VR == "SQ":
        return f"<{len(value or [])} item(s)>"
    if isinstance(value, bytes):
        return f"<{len(value)} bytes>"
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    try:
        return [str(item) for item in value]
    except TypeError:
        return str(value)


def _flatten(dataset: Dataset, *, base_path: str = "") -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for element in dataset:
        tag_text = f"{element.tag.group:04X},{element.tag.element:04X}"
        path = f"{base_path}/{tag_text}" if base_path else tag_text
        if element.tag == 0x7FE00010:
            # Pixel payloads are compared by digest during validation, never
            # copied into a JSON response.
            output[path] = {
                "tag": tag_text,
                "keyword": element.keyword or "PixelData",
                "vr": element.VR,
                "value": f"<{len(element.value or b'')} bytes>",
            }
            continue
        output[path] = {
            "tag": tag_text,
            "keyword": element.keyword or "",
            "vr": element.VR,
            "value": _display_value(element),
        }
        if element.VR == "SQ":
            for index, item in enumerate(element.value or []):
                output.update(_flatten(item, base_path=f"{path}[{index}]"))
    return output


def _as_dataset(value: str | Path | Dataset) -> Dataset:
    return value if isinstance(value, Dataset) else read_dataset(value, stop_before_pixels=False)


def diff_dicom_tags(before: str | Path | Dataset, after: str | Path | Dataset) -> dict[str, Any]:
    """Return added/removed/changed tags, recursively including sequences."""

    left = _flatten(_as_dataset(before))
    right = _flatten(_as_dataset(after))
    changes: list[dict[str, Any]] = []
    for path in sorted(set(left) | set(right)):
        old = left.get(path)
        new = right.get(path)
        if old is None:
            changes.append({"change": "added", "path": path, "before": None, "after": new})
        elif new is None:
            changes.append({"change": "removed", "path": path, "before": old, "after": None})
        elif old != new:
            changes.append({"change": "changed", "path": path, "before": old, "after": new})
    return {
        "changed": bool(changes),
        "change_count": len(changes),
        "changes": changes,
    }


__all__ = ["diff_dicom_tags"]
