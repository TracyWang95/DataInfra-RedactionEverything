"""
HaS Image (YOLO11) 官方 21 类：与模型卡 Category 一致。
id = 英文 slug；class_id = 模型输出 cls 整数 0–20。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

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


# 顺序必须与模型 0..20 一致
HAS_IMAGE_CATEGORIES: Tuple[HasImageCategory, ...] = (
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

SLUG_TO_CLASS_ID: Dict[str, int] = {c.id: c.class_id for c in HAS_IMAGE_CATEGORIES}
CLASS_ID_TO_SLUG: Dict[int, str] = {c.class_id: c.id for c in HAS_IMAGE_CATEGORIES}
SLUG_TO_NAME_ZH: Dict[str, str] = {c.id: c.name_zh for c in HAS_IMAGE_CATEGORIES}


def slug_list_to_class_indices(slugs: Optional[List[str]]) -> Optional[List[int]]:
    """
    - None：不传类别限制，由调用方解释为「跑全类」。
    - []：显式空列表 → 无有效类别索引（应返回空检测结果，而非误跑全类）。
    - 非空：只保留能映射到 0–20 的 slug；若全部非法则为 []。
    """
    if slugs is None:
        return None
    if len(slugs) == 0:
        return []
    out: List[int] = []
    for s in slugs:
        if s in SLUG_TO_CLASS_ID:
            out.append(SLUG_TO_CLASS_ID[s])
    return out


def class_index_to_slug(idx: int) -> str:
    return CLASS_ID_TO_SLUG.get(int(idx), f"class_{idx}")


def preset_type_color(order: int) -> str:
    return _COLORS[order % len(_COLORS)]
