"""视觉证据与边框质量分析 — 从 job_management_service.py 提取。

纯函数层：只对识别产出的 bounding box 字典做聚合与质量启发式，
不依赖 store / file_store / 任何其它服务，供导出报告层复用。
"""
from __future__ import annotations

from typing import Any


def _iter_bounding_boxes(info: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not info:
        return []
    raw = info.get("bounding_boxes")
    if isinstance(raw, list):
        return [box for box in raw if isinstance(box, dict)]
    if not isinstance(raw, dict):
        return []
    out: list[dict[str, Any]] = []
    for page, boxes in raw.items():
        if not isinstance(boxes, list):
            continue
        for box in boxes:
            if not isinstance(box, dict):
                continue
            enriched = dict(box)
            enriched.setdefault("page", page)
            out.append(enriched)
    return out


def _box_number(box: dict[str, Any], key: str) -> float:
    try:
        return float(box.get(key) or 0)
    except (TypeError, ValueError):
        return 0.0


def _is_seal_box(box: dict[str, Any]) -> bool:
    box_type = str(box.get("type") or "").strip().lower()
    return box_type in {"seal", "official_seal", "stamp"}


def _is_selected_box(box: dict[str, Any]) -> bool:
    return box.get("selected") is not False


def _box_quality_issues(box: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    source = str(box.get("source") or "").lower()
    source_detail = str(box.get("source_detail") or "").lower()
    evidence_source = str(box.get("evidence_source") or "").lower()
    source_marker = f"{source} {source_detail} {evidence_source}"
    text = str(box.get("text") or "").strip().lower()
    confidence = _box_number(box, "confidence")
    x = _box_number(box, "x")
    y = _box_number(box, "y")
    width = _box_number(box, "width")
    height = _box_number(box, "height")
    right = x + width
    bottom = y + height

    if 0 < confidence < 0.55:
        issues.append("low_confidence")
    if "fallback" in source_marker:
        issues.append("fallback_detector")
    if "table_structure" in source_marker:
        issues.append("table_structure")
    if text.startswith(("<table", "<html", "<div")):
        issues.append("coarse_markup")
    if source == "ocr_has" and (width * height >= 0.2 or (width >= 0.6 and height >= 0.25)):
        issues.append("large_ocr_region")
    if _is_seal_box(box) and (x <= 0.04 or y <= 0.04 or right >= 0.96 or bottom >= 0.96):
        issues.append("edge_seal")
    if _is_seal_box(box) and (x <= 0.025 or right >= 0.975 or (width <= 0.07 and height >= 0.10)):
        issues.append("seam_seal")
    if isinstance(box.get("warnings"), list) and len(box["warnings"]) > 0 and not issues:
        issues.append("warning")
    return list(dict.fromkeys(issues))


def _counter_key(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text


def _increment_counter(counter: dict[str, int], key: Any, amount: int = 1) -> None:
    normalized = _counter_key(key)
    if normalized:
        counter[normalized] = counter.get(normalized, 0) + amount


def _empty_visual_evidence() -> dict[str, Any]:
    return {
        "total_boxes": 0,
        "selected_boxes": 0,
        "visual_feature_model": 0,
        "local_fallback": 0,
        "ocr_has": 0,
        "table_structure": 0,
        "fallback_detector": 0,
        "source_counts": {},
        "evidence_source_counts": {},
        "source_detail_counts": {},
        "warnings_by_key": {},
    }


def _sorted_visual_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    out = dict(evidence)
    for key in ("source_counts", "evidence_source_counts", "source_detail_counts", "warnings_by_key"):
        raw = out.get(key)
        out[key] = dict(sorted(raw.items())) if isinstance(raw, dict) else {}
    return out


def _visual_evidence_summary(info: dict[str, Any] | None) -> dict[str, Any]:
    evidence = _empty_visual_evidence()
    boxes = _iter_bounding_boxes(info)
    evidence["total_boxes"] = len(boxes)

    for box in boxes:
        if not _is_selected_box(box):
            continue

        evidence["selected_boxes"] += 1
        source = _counter_key(box.get("source"))
        source_detail = _counter_key(box.get("source_detail"))
        evidence_source = _counter_key(box.get("evidence_source"))
        source_marker = f"{source} {source_detail} {evidence_source}"

        _increment_counter(evidence["source_counts"], source)
        _increment_counter(evidence["source_detail_counts"], source_detail)
        _increment_counter(evidence["evidence_source_counts"], evidence_source)

        warnings = box.get("warnings")
        if isinstance(warnings, list):
            for warning in warnings:
                _increment_counter(evidence["warnings_by_key"], warning)
        elif isinstance(warnings, str):
            _increment_counter(evidence["warnings_by_key"], warnings)

        if evidence_source == "visual_feature_model" or (
            source == "visual_features" and "fallback" not in source_marker
        ):
            evidence["visual_feature_model"] += 1
        if "local_fallback" in source_marker:
            evidence["local_fallback"] += 1
        if source == "ocr_has" or evidence_source == "ocr_has":
            evidence["ocr_has"] += 1
        if "table_structure" in source_marker:
            evidence["table_structure"] += 1
        if "fallback" in source_marker:
            evidence["fallback_detector"] += 1

    return _sorted_visual_evidence(evidence)


def _merge_visual_evidence(target: dict[str, Any], addition: dict[str, Any]) -> None:
    scalar_keys = (
        "total_boxes",
        "selected_boxes",
        "visual_feature_model",
        "local_fallback",
        "ocr_has",
        "table_structure",
        "fallback_detector",
    )
    for key in scalar_keys:
        target[key] = int(target.get(key) or 0) + int(addition.get(key) or 0)
    for key in ("source_counts", "evidence_source_counts", "source_detail_counts", "warnings_by_key"):
        target_counter = target.setdefault(key, {})
        addition_counter = addition.get(key) or {}
        if not isinstance(target_counter, dict) or not isinstance(addition_counter, dict):
            continue
        for counter_key, count in addition_counter.items():
            target_counter[counter_key] = int(target_counter.get(counter_key) or 0) + int(count or 0)


def _visual_review_quality(info: dict[str, Any] | None) -> dict[str, Any]:
    by_issue: dict[str, int] = {}
    pages: dict[str, int] = {}
    issue_count = 0
    for box in _iter_bounding_boxes(info):
        if not _is_selected_box(box):
            continue
        issues = _box_quality_issues(box)
        if not issues:
            continue
        issue_count += len(issues)
        page = str(box.get("page") or 1)
        pages[page] = pages.get(page, 0) + len(issues)
        for issue in issues:
            by_issue[issue] = by_issue.get(issue, 0) + 1
    issue_pages = sorted(pages, key=lambda value: int(value) if value.isdigit() else value)
    issue_labels = sorted(by_issue)
    return {
        "blocking": False,
        "review_hint": issue_count > 0,
        "issue_count": issue_count,
        "issue_pages": issue_pages,
        "issue_pages_count": len(issue_pages),
        "issue_labels": issue_labels,
        "by_issue": dict(sorted(by_issue.items())),
    }
