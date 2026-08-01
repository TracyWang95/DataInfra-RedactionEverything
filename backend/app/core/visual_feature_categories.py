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
    # The wording GROUNDED (and re-verified) for this category. Defaults to the
    # Chinese display name — one definition, no slug→query side table. Set it only
    # where a MEASURED precision/recall result needs a phrase different from the
    # label. This grounding model was trained on English class names, so a Chinese
    # query mis-fires on five classes — three PII-critical stamp/mark classes plus
    # id_card and face, each of which rides a single tuned English query_override.
    # The wording must be MEASURED, not just translated: bare "face" still fired on
    # a skin-toned finger, only "human face" refused it. Classes:
    #   • official_seal — 公章 fired 71 corpus seal boxes (FPs on docs with NO
    #     seal) vs 19 for "seal"; the verify can't prune a hallucination it
    #     re-confirms.
    #   • signature — "handwritten signature", not bare "signature": the word
    #     handwritten makes the model REFUSE printed Chinese text (prompt sweep:
    #     0.00 on every printed-text crop vs 0.33 for "signature") while firing
    #     STRONGER on real handwriting (0.49-0.59). That precision is what lets the
    #     grid retry zoom in to recover the small 海油 签字 without flooding false
    #     signatures on body text — signatures skip the verify, so the prompt must
    #     carry the precision itself. (中文 手写签名 over-fired: 67 corpus FPs.)
    #   • fingerprint — 指纹 recalled 0/7 real prints at full frame (2026-07-10
    #     A/B); "red inked thumbprint mark" recalled 7/7. Precision-first policy
    #     (2026-07-22, 容许找不到但不要高FP): ONE tuned English query, NOT a
    #     recall-max union — a broad phrase like "ink stain" recovers one extra
    #     pale print but fires on ink smudges / red text / the page-holding finger
    #     (high FP). Context-artifact false prints are pruned by the model-centric
    #     verify re-ground (there is NO pixel skin gate). A dedicated impression
    #     detector is the real precision fix and is being sourced separately.
    #   • id_card — 身份证 fired on the "身份证号" text LABEL because the query word
    #     is a substring of the field label, boxing printed form text as a card
    #     (2026-07-21 A/B on the 门诊病历: 身份证 → 1 box on the label, "ID card" →
    #     0). A real card's PII is still covered by OCR text + face even if the
    #     English query under-recalls the bare card outline.
    #   • face — 人脸/face/脸/面部 all grounded a bare finger (the hand holding the
    #     page) as a face, 3/3 samples; "human face" refused it, 0/3 (2026-07-22
    #     A/B on the 门诊病历 finger). The dedicated YOLO face detector backstops
    #     real-face recall, so the stricter LA query only removes the skin FP.
    # These five are A/B-measured; every other built-in now also grounds a chosen
    # English query (see the category tuple below) — un-measured but LA-appropriate,
    # to be tuned when a document with that object surfaces.
    query_override: str = ""

    @property
    def grounding_query(self) -> str:
        return self.query_override or self.name_zh


# Every built-in category grounds an ENGLISH query (LA is English-trained). The
# five marked (M) are A/B-measured on real docs; the rest are chosen English
# (natural, disambiguated where a bare word could mis-fire, e.g. "metal key" not
# "key") pending measurement when such a document appears. name_zh stays Chinese
# for the UI; only the grounding query is English.
VISUAL_FEATURE_CATEGORIES: tuple[VisualFeatureCategory, ...] = (
    VisualFeatureCategory(0, "face", "人脸", "人体面部区域", "human face"),                       # M
    VisualFeatureCategory(1, "fingerprint", "指纹", "指纹、捺印区域", "red inked thumbprint mark"),  # M
    VisualFeatureCategory(2, "palmprint", "掌纹", "掌纹区域", "inked palm print"),
    VisualFeatureCategory(3, "id_card", "身份证", "居民身份证等证件", "ID card"),                    # M
    VisualFeatureCategory(4, "hk_macau_permit", "港澳通行证", "往来港澳通行证等", "travel permit card"),
    VisualFeatureCategory(5, "passport", "护照", "护照", "passport"),
    VisualFeatureCategory(6, "employee_badge", "工作证", "员工证、工牌", "employee ID badge"),
    VisualFeatureCategory(7, "license_plate", "车牌", "机动车号牌", "vehicle license plate"),
    VisualFeatureCategory(8, "bank_card", "银行卡", "银行卡、信用卡", "bank card"),
    VisualFeatureCategory(9, "physical_key", "钥匙", "实体钥匙", "metal key"),
    VisualFeatureCategory(10, "receipt", "小票/收据", "购物小票、收据", "printed receipt"),
    VisualFeatureCategory(11, "shipping_label", "快递面单", "快递/物流面单", "shipping label"),
    VisualFeatureCategory(12, "official_seal", "公章", "公章、印章", "seal"),                        # M
    VisualFeatureCategory(13, "whiteboard", "白板", "白板内容", "whiteboard"),
    VisualFeatureCategory(14, "sticky_note", "便利贴", "便签、便利贴", "sticky note"),
    VisualFeatureCategory(15, "mobile_screen", "手机屏幕", "手机屏幕显示区域", "phone screen"),
    VisualFeatureCategory(16, "monitor_screen", "电脑屏幕", "显示器屏幕区域", "computer monitor"),
    VisualFeatureCategory(17, "medical_wristband", "医用腕带", "医院腕带", "hospital wristband"),
    VisualFeatureCategory(18, "qr_code", "二维码", "二维码", "QR code"),
    VisualFeatureCategory(19, "barcode", "条形码", "条形码", "barcode"),
    VisualFeatureCategory(20, "paper", "纸质文档", "纸张文档区域", "sheet of paper"),
    VisualFeatureCategory(21, "signature", "签字", "手写签名、签字笔迹", "handwritten signature"),   # M
)

# The out-of-box grounding query per fixed category, DERIVED from the single
# category definition above (grounding_query = query_override or name_zh). The
# user's 识别清单 always wins (勾选什么传入什么, see _grounding_query); this only
# supplies the default when a checklist row carries no positive prompt.
SLUG_TO_GROUNDING_QUERY: dict[str, str] = {
    item.id: item.grounding_query for item in VISUAL_FEATURE_CATEGORIES
}

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
