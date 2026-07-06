"""
HaS Image (YOLO11) 官方 21 类：与模型卡 Category 一致。
id = 英文 slug；class_id = 模型输出 cls 整数 0–20。
"""
from __future__ import annotations

from dataclasses import dataclass

# 配色供 Pipeline / 前端展示
_COLORS = (
    "#EF4444", "#F97316", "#F59E0B", "#EAB308", "#84CC16", "#22C55E",
    "#14B8A6", "#06B6D4", "#0EA5E9", "#3B82F6", "#6366F1", "#8B5CF6",
    "#A855F7", "#D946EF", "#EC4899", "#F43F5E", "#64748B", "#78716C",
    "#0D9488", "#059669", "#7C3AED",
)


@dataclass(frozen=True)
class HasImageCategory:
    class_id: int
    id: str  # slug, same as ultralytics class name when aligned
    name_zh: str
    description_zh: str


# 顺序必须与模型 0..20 一致；不要在这里加入 signature/handwriting 等
# OCR、规则或本地 fallback 证据，它们不是 HaS Image YOLO 类。
HAS_IMAGE_CATEGORIES: tuple[HasImageCategory, ...] = (
    HasImageCategory(0, "face", "人脸", "人体面部区域"),
    HasImageCategory(1, "fingerprint", "指纹", "指纹、捺印区域"),
    HasImageCategory(2, "palmprint", "掌纹", "掌纹区域"),
    HasImageCategory(3, "id_card", "身份证", "居民身份证等证件"),
    HasImageCategory(4, "hk_macau_permit", "港澳通行证", "往来港澳通行证等"),
    HasImageCategory(5, "passport", "护照", "护照"),
    HasImageCategory(6, "employee_badge", "工作证", "员工证、工牌"),
    HasImageCategory(7, "license_plate", "车牌", "机动车号牌"),
    HasImageCategory(8, "bank_card", "银行卡", "银行卡、信用卡"),
    HasImageCategory(9, "physical_key", "钥匙", "实体钥匙"),
    HasImageCategory(10, "receipt", "小票/收据", "购物小票、收据"),
    HasImageCategory(11, "shipping_label", "快递面单", "快递/物流面单"),
    HasImageCategory(12, "official_seal", "公章", "公章、印章"),
    HasImageCategory(13, "whiteboard", "白板", "白板内容"),
    HasImageCategory(14, "sticky_note", "便利贴", "便签、便利贴"),
    HasImageCategory(15, "mobile_screen", "手机屏幕", "手机屏幕显示区域"),
    HasImageCategory(16, "monitor_screen", "电脑屏幕", "显示器屏幕区域"),
    HasImageCategory(17, "medical_wristband", "医用腕带", "医院腕带"),
    HasImageCategory(18, "qr_code", "二维码", "二维码"),
    HasImageCategory(19, "barcode", "条形码", "条形码"),
    HasImageCategory(20, "paper", "纸质文档", "纸张文档区域"),
)

HAS_IMAGE_MODEL_CLASS_COUNT = 21
SLUG_TO_CLASS_ID: dict[str, int] = {c.id: c.class_id for c in HAS_IMAGE_CATEGORIES}
CLASS_ID_TO_SLUG: dict[int, str] = {c.class_id: c.id for c in HAS_IMAGE_CATEGORIES}
SLUG_TO_NAME_ZH: dict[str, str] = {c.id: c.name_zh for c in HAS_IMAGE_CATEGORIES}
HAS_IMAGE_MODEL_SLUGS = frozenset(SLUG_TO_CLASS_ID)
OCR_FALLBACK_ONLY_VISUAL_SLUGS = frozenset({
    "signature",
    "handwritten",
    "hand_written",
    "handwriting",
    "handwritten_signature",
})

# HaS Image 的 21 类完整保留；默认仅去掉“纸质文档”这种整页容器类，
# 避免一上来产生整页大框。其他视觉隐私目标默认启用。
DEFAULT_EXCLUDED_HAS_IMAGE_SLUGS = frozenset({
    "paper",
})
DEFAULT_HAS_IMAGE_SLUGS: tuple[str, ...] = tuple(
    c.id for c in HAS_IMAGE_CATEGORIES if c.id not in DEFAULT_EXCLUDED_HAS_IMAGE_SLUGS
)


def normalize_visual_slug(value: object) -> str:
    return str(value or "").strip().lower().replace("-", "_")


def is_has_image_model_slug(value: object) -> bool:
    return normalize_visual_slug(value) in HAS_IMAGE_MODEL_SLUGS


def filter_has_image_model_slugs(slugs: list[str] | None) -> list[str] | None:
    if slugs is None:
        return None
    return [
        slug
        for raw in slugs
        if (slug := normalize_visual_slug(raw)) in HAS_IMAGE_MODEL_SLUGS
    ]


def has_only_ocr_fallback_visual_slugs(slugs: list[str] | None) -> bool:
    if not slugs:
        return False
    normalized = [normalize_visual_slug(slug) for slug in slugs]
    return all(slug in OCR_FALLBACK_ONLY_VISUAL_SLUGS for slug in normalized)


def slug_list_to_class_indices(slugs: list[str] | None) -> list[int] | None:
    """
    - None：不传类别限制，由调用方解释为「跑全类」。
    - []：显式空列表 → 无有效类别索引（应返回空检测结果，而非误跑全类）。
    - 非空：只保留能映射到 0–20 的 slug；若全部非法则为 []。
    """
    if slugs is None:
        return None
    if len(slugs) == 0:
        return []
    return [SLUG_TO_CLASS_ID[slug] for slug in filter_has_image_model_slugs(slugs) or []]


def class_index_to_slug(idx: int) -> str:
    return CLASS_ID_TO_SLUG.get(int(idx), f"class_{idx}")


def preset_type_color(order: int) -> str:
    return _COLORS[order % len(_COLORS)]
