"""Detect-request and checklist-prompt construction.

Pure builders split out of ``locate_grounding`` for single-responsibility:
turn the configured type list into the per-target detect requests (fixed slug
vs. user-defined custom label) and into the checklist chat prompt. Behavior is
verbatim.
"""
from __future__ import annotations

from typing import Any

from app.core.config import settings
from app.core.visual_feature_categories import (
    DEFAULT_VISUAL_FEATURE_SLUGS,
    SLUG_TO_DEFAULT_QUERY,
    SLUG_TO_NAME_ZH,
    VISUAL_FEATURE_SLUGS,
    normalize_visual_slug,
)


def _type_rules(type_config: Any) -> list[str]:
    checklist = getattr(type_config, "checklist", None) or []
    rules: list[str] = []
    for item in checklist:
        if isinstance(item, dict):
            for key in ("rule", "positive_prompt"):
                value = str(item.get(key) or "").strip()
                if value:
                    rules.append(value)
        else:
            for key in ("rule", "positive_prompt"):
                value = str(getattr(item, key, "") or "").strip()
                if value:
                    rules.append(value)
    if not rules:
        rules = [str(rule).strip() for rule in (getattr(type_config, "rules", None) or []) if str(rule).strip()]
    description = str(getattr(type_config, "description", "") or "").strip()
    if description:
        rules.append(description)
    name = str(getattr(type_config, "name", "") or getattr(type_config, "id", "")).strip()
    if name:
        rules.append(name)
    return list(dict.fromkeys(rules))


def _checklist_prompt(type_configs: list[Any]) -> str:
    lines = [
        "Task: locate visual features in this document image.",
        "Use actual visible visual evidence only; do not infer from labels, blank fields, table lines, or surrounding text.",
        "Return JSON only.",
        'Schema: {"objects":[{"type_id":"<allowed type_id>","label":"<label>","box_2d":[xmin,ymin,xmax,ymax],"confidence":0.8,"rule_matched":"<type_id>#<rule_index>","text":""}]}',
        f"Coordinates are integers in 0..{settings.VISUAL_FEATURES_COORD_MODE}, origin top-left.",
        "Use one tight box per visible instance.",
        f"Allowed type_id: {', '.join(str(getattr(item, 'id', '')).strip() for item in type_configs)}",
        "Configured visual checklist:",
    ]
    for item in type_configs:
        type_id = str(getattr(item, "id", "")).strip()
        name = str(getattr(item, "name", "") or type_id).strip()
        lines.append(f"- type_id={type_id}; name={name}")
        for index, rule in enumerate(_type_rules(item), start=1):
            lines.append(f"  {index}. Check: {rule}")
        negative = str(getattr(item, "negative_prompt", "") or "").strip()
        if bool(getattr(item, "negative_prompt_enabled", False)) and negative:
            lines.append(f"  Exclude: {negative}")
    lines.append('If none, return {"objects":[]}.')
    return "\n".join(lines)


def _grounding_query(item: Any, slug: str) -> str:
    """The wording sent to the model for a fixed category — the user's 识别清单
    owns it (勾选什么传入什么): the item's first positive checklist row wins,
    then its first rule line; only an unconfigured item falls back to the
    factory default next to the category definitions (SLUG_TO_DEFAULT_QUERY),
    then to the category name."""
    for row in getattr(item, "checklist", None) or []:
        for key in ("rule", "positive_prompt"):
            value = str(
                (row.get(key) if isinstance(row, dict) else getattr(row, key, "")) or ""
            ).strip()
            if value:
                return value
    for rule in getattr(item, "rules", None) or []:
        if str(rule).strip():
            return str(rule).strip()
    return SLUG_TO_DEFAULT_QUERY.get(slug) or SLUG_TO_NAME_ZH.get(slug, slug)


def _detect_requests(
    pipeline_types: list[Any] | None,
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Detect targets + the fixed-slug subset.

    Each target is (tag_to_send, result_type, result_text): a fixed visual
    category is sent as its grounding query — the user's checklist wording,
    or the factory default (_grounding_query) — and tagged by its slug; a
    user-defined custom_visual_features_* label is sent as its human name
    verbatim and tagged by its own type_id. Every request reaches the model
    as free text through one uniform path — no server-side slug table ever
    overrides the user's 清单. The box is tagged by the REQUESTED target,
    never LA's echoed category, which a non-ASCII label would not survive.

    The fixed-slug subset drives the slug-specific supplements (YOLO / seal
    cascade / signature / tile retry). pipeline_types is None -> every fixed
    category (the default preset) with its factory query."""
    if pipeline_types is None:
        fixed = list(DEFAULT_VISUAL_FEATURE_SLUGS)
        return [
            (SLUG_TO_DEFAULT_QUERY.get(s) or SLUG_TO_NAME_ZH.get(s, s), s, SLUG_TO_NAME_ZH.get(s, s))
            for s in fixed
        ], fixed
    requests: list[tuple[str, str, str]] = []
    fixed: list[str] = []
    seen: set[str] = set()
    for item in pipeline_types:
        tid = str(getattr(item, "id", item) or "")
        slug = normalize_visual_slug(tid)
        if slug in VISUAL_FEATURE_SLUGS:
            if slug in seen:
                continue
            seen.add(slug)
            requests.append((_grounding_query(item, slug), slug, SLUG_TO_NAME_ZH.get(slug, slug)))
            fixed.append(slug)
        elif tid.startswith("custom_visual_features_") and tid not in seen:
            label = str(getattr(item, "name", "") or "").strip() or tid[
                len("custom_visual_features_"):
            ].replace("_", " ").strip()
            if label:
                seen.add(tid)
                requests.append((label, tid, label))
    return requests, fixed
