"""Fixed LocateAnything visual feature presets."""

from __future__ import annotations

import re
from dataclasses import dataclass

_COLORS = (
    "#EF4444",
    "#F97316",
    "#F59E0B",
    "#EAB308",
    "#84CC16",
    "#22C55E",
    "#14B8A6",
    "#06B6D4",
    "#0EA5E9",
    "#3B82F6",
    "#6366F1",
    "#8B5CF6",
    "#A855F7",
    "#D946EF",
    "#EC4899",
    "#F43F5E",
    "#64748B",
    "#78716C",
    "#0D9488",
    "#059669",
    "#7C3AED",
    "#0F766E",
)


@dataclass(frozen=True)
class VisualFeatureCategory:
    class_id: int
    id: str
    name_zh: str
    description_zh: str


VISUAL_FEATURE_CATEGORIES: tuple[VisualFeatureCategory, ...] = (
    VisualFeatureCategory(0, "face", "人脸", "人体面部区域"),
    VisualFeatureCategory(1, "fingerprint", "指纹", "指纹、捺印区域"),
    VisualFeatureCategory(2, "palmprint", "掌纹", "掌纹区域"),
    VisualFeatureCategory(3, "id_card", "身份证", "居民身份证等证件"),
    VisualFeatureCategory(4, "hk_macau_permit", "港澳通行证", "往来港澳通行证等"),
    VisualFeatureCategory(5, "passport", "护照", "护照"),
    VisualFeatureCategory(6, "employee_badge", "工作证", "员工证、工牌"),
    VisualFeatureCategory(7, "license_plate", "车牌", "机动车号牌"),
    VisualFeatureCategory(8, "bank_card", "银行卡", "银行卡、信用卡"),
    VisualFeatureCategory(9, "physical_key", "钥匙", "实体钥匙"),
    VisualFeatureCategory(10, "receipt", "小票/收据", "购物小票、收据"),
    VisualFeatureCategory(11, "shipping_label", "快递面单", "快递/物流面单"),
    VisualFeatureCategory(12, "official_seal", "公章", "公章、印章"),
    VisualFeatureCategory(13, "whiteboard", "白板", "白板内容"),
    VisualFeatureCategory(14, "sticky_note", "便利贴", "便签、便利贴"),
    VisualFeatureCategory(15, "mobile_screen", "手机屏幕", "手机屏幕显示区域"),
    VisualFeatureCategory(16, "monitor_screen", "电脑屏幕", "显示器屏幕区域"),
    VisualFeatureCategory(17, "medical_wristband", "医用腕带", "医院腕带"),
    VisualFeatureCategory(18, "qr_code", "二维码", "二维码"),
    VisualFeatureCategory(19, "barcode", "条形码", "条形码"),
    VisualFeatureCategory(20, "paper", "纸质文档", "纸张文档区域"),
    VisualFeatureCategory(21, "signature", "签字", "手写签名、签字笔迹"),
)

VISUAL_FEATURE_CLASS_COUNT = len(VISUAL_FEATURE_CATEGORIES)
SLUG_TO_CLASS_ID: dict[str, int] = {item.id: item.class_id for item in VISUAL_FEATURE_CATEGORIES}
CLASS_ID_TO_SLUG: dict[int, str] = {item.class_id: item.id for item in VISUAL_FEATURE_CATEGORIES}
SLUG_TO_NAME_ZH: dict[str, str] = {item.id: item.name_zh for item in VISUAL_FEATURE_CATEGORIES}
VISUAL_FEATURE_SLUGS = frozenset(SLUG_TO_CLASS_ID)

# PaddleOCR-VL has been dropped (OCR_VL_ENABLED=0), and LocateAnything (now
# served via vLLM) detects official seals reliably (4/4 on the test contract).
# So no visual slug is OCR-fallback-only anymore — every slug, including
# official_seal, is routed to LocateAnything.
OCR_FALLBACK_ONLY_VISUAL_SLUGS = frozenset()
LOCATE_ANYTHING_VISUAL_SLUGS = VISUAL_FEATURE_SLUGS - OCR_FALLBACK_ONLY_VISUAL_SLUGS
DEFAULT_EXCLUDED_VISUAL_FEATURE_SLUGS = frozenset()
DEFAULT_VISUAL_FEATURE_SLUGS: tuple[str, ...] = tuple(
    item.id for item in VISUAL_FEATURE_CATEGORIES if item.id not in DEFAULT_EXCLUDED_VISUAL_FEATURE_SLUGS
)


# Visual-only entity type IDs (uppercase semantic type ids, not visual slugs):
# regions of these types come from the visual channel and are never sent to
# HaS Text. Shared by ocr_has_vision_service / has_text_payload / ocr_pipeline.
VISUAL_ONLY_ENTITY_TYPES = frozenset({
    "SEAL",
    "SIGNATURE",
    "FINGERPRINT",
    "PHOTO",
    "QR_CODE",
    "HANDWRITING",
    "WATERMARK",
})


def normalize_visual_slug(value: object) -> str:
    raw = str(value or "").strip().lower().replace("-", "_")
    raw = re.sub(r"[^a-z0-9_]+", "_", raw)
    return re.sub(r"_+", "_", raw).strip("_")


def is_visual_feature_slug(value: object) -> bool:
    return normalize_visual_slug(value) in VISUAL_FEATURE_SLUGS


def filter_visual_feature_slugs(slugs: list[str] | None) -> list[str] | None:
    if slugs is None:
        return None
    return [
        slug
        for raw in slugs
        if (slug := normalize_visual_slug(raw)) in LOCATE_ANYTHING_VISUAL_SLUGS
    ]


def has_only_ocr_fallback_visual_slugs(slugs: list[str] | None) -> bool:
    if not slugs:
        return False
    normalized = [normalize_visual_slug(slug) for slug in slugs]
    return all(slug in OCR_FALLBACK_ONLY_VISUAL_SLUGS for slug in normalized)


def slug_list_to_class_indices(slugs: list[str] | None) -> list[int] | None:
    if slugs is None:
        return None
    if len(slugs) == 0:
        return []
    return [SLUG_TO_CLASS_ID[slug] for slug in filter_visual_feature_slugs(slugs) or []]


def class_index_to_slug(idx: int) -> str:
    return CLASS_ID_TO_SLUG.get(int(idx), f"class_{idx}")


def preset_type_color(order: int) -> str:
    return _COLORS[order % len(_COLORS)]
