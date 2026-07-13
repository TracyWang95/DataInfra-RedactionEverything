"""
HaS Text request payload helpers for OCR-derived text blocks.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from app.core.visual_feature_categories import VISUAL_ONLY_ENTITY_TYPES
from app.models.type_mapping import canonical_type_id
from app.services.ocr_has_vision_service import OCRTextBlock

logger = logging.getLogger(__name__)

DEFAULT_HAS_TEXT_TYPE_IDS = [
    "PERSON",
    "ID_CARD",
    "PASSPORT",
    "SOCIAL_SECURITY",
    "PHONE",
    "EMAIL",
    "ADDRESS",
    "GPS_LOCATION",
    "USERNAME_PASSWORD",
    "AUTH_SECRET",
    "BANK_CARD",
    "BANK_ACCOUNT",
    "BANK_NAME",
    "AMOUNT",
    "DEVICE_ID",
    "IP_ADDRESS",
    "URL_WEBSITE",
    "COMPANY_NAME",
    "INSTITUTION_NAME",
    "GOVERNMENT_AGENCY",
    "WORK_UNIT",
    "DEPARTMENT_NAME",
    "PROJECT_NAME",
    "CREDIT_CODE",
    "TAX_ID",
    "DATE",
    "TIME",
    "AGE",
    "GENDER",
    "NATIONALITY",
    "ETHNICITY",
    "MARITAL_STATUS",
    "HEALTH_INFO",
    "LICENSE_PLATE",
    "VIN",
    "CASE_NUMBER",
]


@dataclass(frozen=True)
class HaSTextPayload:
    texts: list[str]
    content: str
    source_block_count: int
    eligible_block_count: int
    duplicate_block_count: int
    clipped_block_count: int
    input_chars: int
    emitted_chars: int
    omitted_chars: int
    max_chars: int
    truncated: bool


def _canonical_image_text_type(entity_type: str | None) -> str:
    value = str(entity_type or "").strip()
    if not value:
        return ""
    # Custom items are their own canonical form (same lowercase id the store
    # and the text NER channel use); canonical_type_id would uppercase them
    # into ids no catalog knows.
    if value.lower().startswith("custom_"):
        return value.lower()
    return canonical_type_id(value)


def _item_query_labels(item) -> list[str]:
    """The model query labels a checklist item sends — the item OWNS them
    (勾选什么查什么): its explicit query_labels field when configured (the
    factory presets carry e.g. 金额+大写金额 so both numeral renderings of a
    paired amount land in separate buckets), else its user-facing name. No
    backend registry translation — an enumerated id→label mapping can never
    be complete and silently diverged from the checklist (健康信息 was
    secretly queried as 诊断)."""
    labels = [str(label).strip() for label in (getattr(item, "query_labels", None) or []) if str(label).strip()]
    if labels:
        return labels
    name = str(getattr(item, "name", "") or "").strip()
    return [name or str(getattr(item, "id", "") or "")]


def _default_has_text_items() -> list:
    """The default checklist when the caller supplies none: the factory
    preset items themselves (the same objects the UI shows), filtered to the
    default text-type id set — names and query labels come from the user's
    visible preset file, not from a registry."""
    from app.services.pipeline_service import PRESET_OCR_HAS_TYPES

    wanted = set(DEFAULT_HAS_TEXT_TYPE_IDS)
    return [item for item in PRESET_OCR_HAS_TYPES if item.id in wanted]


def _build_has_text_type_names(vision_types: list | None = None) -> list[str]:
    """Build the de-duplicated HaS Text prompt label list for OCR text.

    Each checked item contributes its own labels (_item_query_labels); the
    open-vocabulary model returns whatever it finds under whatever label, and
    that label IS the type (识别出来是啥就是啥).
    """
    items = list(vision_types) if vision_types else _default_has_text_items()
    labels: list[str] = []
    seen_type_ids: set[str] = set()
    for item in items:
        type_id = _canonical_image_text_type(getattr(item, "id", ""))
        if not type_id or type_id in VISUAL_ONLY_ENTITY_TYPES or type_id in seen_type_ids:
            continue
        seen_type_ids.add(type_id)
        labels.extend(_item_query_labels(item))
    return list(dict.fromkeys(label for label in labels if label))

def _compact_text(text: str | None) -> str:
    return "".join(str(text or "").split())


# PaddleOCR-VL renders form-blank fills as math markup: $ \underline{2025} $,
# $ \underline{\text{河南新乡市}} $. The wrappers are rendering directives, not
# page content — chars never carry them, so they poison glyph alignment and
# leak into region texts. A $...$ segment is markup only when it contains a
# \command{...}; a bare currency $ never does and is left untouched.
_VL_MATH_SEGMENT_RE = re.compile(r"\$([^$]*)\$")
_VL_MATH_COMMAND_RE = re.compile(r"\\[a-zA-Z]+\{([^{}]*)\}")


def _strip_vl_math_markup(text: str) -> str:
    if "$" not in text:
        return text

    def _unwrap(match: re.Match) -> str:
        body = match.group(1)
        if not _VL_MATH_COMMAND_RE.search(body):
            return match.group(0)
        previous = None
        while previous != body:  # \underline{\text{X}} unwraps inside-out
            previous = body
            body = _VL_MATH_COMMAND_RE.sub(r"\1", body)
        return body.strip()

    return _VL_MATH_SEGMENT_RE.sub(_unwrap, text)


def _iter_payload_texts(text: str | None) -> list[str]:
    # HaS reads the same markup-free text the matcher matches against: the VL
    # math wrappers are rendering noise that made HaS tag form-blank fills
    # only intermittently (保底十万元 in $ \underline{\text{...}} $).
    raw = _strip_vl_math_markup(str(text or "")).strip()
    if not raw:
        return []
    lines = [line.strip() for line in raw.splitlines() if _compact_text(line)]
    if len(lines) > 1:
        return lines
    return [raw]



def _build_has_text_payload(
    ocr_blocks: list[OCRTextBlock],
    *,
    max_chars: int,
    max_block_chars: int | None = None,
) -> HaSTextPayload:
    """Build HaS prompt text and stats while dropping duplicate OCR block text."""
    candidate_texts: list[str] = []
    seen: set[str] = set()
    input_chars = 0
    eligible_block_count = 0
    duplicate_block_count = 0
    clipped_block_count = 0
    truncated = False
    max_chars = max(0, int(max_chars))
    block_char_cap = max(0, int(max_block_chars or 0))

    for block in ocr_blocks:
        for text in _iter_payload_texts(block.text):
            input_chars += len(text)
            if block_char_cap and len(text) > block_char_cap:
                clipped_block_count += 1
                text = text[:block_char_cap]

            compact = _compact_text(text)
            if not compact:
                continue
            eligible_block_count += 1
            # Drop only EXACTLY-equal block text (truly repeated OCR blocks). The
            # old substring-containment dedup also dropped a block whose text was a
            # substring of another block elsewhere on the page — so the 姓名 cell
            # "张三" was removed because 联系人 "张三（儿子）" contains it, and a
            # table date "2024-05-12" because 入院日期 "2024-05-1209:23" contains
            # it. Those fields then never reached HaS and were never redacted.
            # match_entities_to_ocr re-expands a kept value to every occurrence, so
            # collapsing exact duplicates loses nothing.
            if compact in seen:
                duplicate_block_count += 1
                continue

            seen.add(compact)
            candidate_texts.append(text)

    texts: list[str] = []
    total_chars = 0
    for text in candidate_texts:
        next_len = len(text) + (1 if texts else 0)
        if total_chars + next_len > max_chars:
            remaining = max_chars - total_chars - (1 if texts else 0)
            if remaining > 0:
                texts.append(text[:remaining])
                total_chars = max_chars
            truncated = True
            logger.warning("OCR text too long for HaS (%d chars), capped at %d", input_chars, max_chars)
            break

        texts.append(text)
        total_chars += next_len

    content = "\n".join(texts)
    emitted_text_chars = sum(len(text) for text in texts)
    return HaSTextPayload(
        texts=texts,
        content=content,
        source_block_count=len(ocr_blocks),
        eligible_block_count=eligible_block_count,
        duplicate_block_count=duplicate_block_count,
        clipped_block_count=clipped_block_count,
        input_chars=input_chars,
        emitted_chars=len(content),
        omitted_chars=max(0, input_chars - emitted_text_chars),
        max_chars=max_chars,
        truncated=truncated,
    )


def _filter_blocks_for_has_text(
    ocr_blocks: list[OCRTextBlock],
    selected_type_ids: list[str] | None = None,
) -> list[OCRTextBlock]:
    """Keep OCR text eligible for HaS Text without local semantic rules."""
    selected = {_canonical_image_text_type(type_id) for type_id in (selected_type_ids or [])}
    if selected and selected.issubset(VISUAL_ONLY_ENTITY_TYPES):
        return []

    return [
        block
        for block in ocr_blocks
        if _compact_text(block.text) and not str(block.text or "").lstrip().startswith("<table")
    ]
