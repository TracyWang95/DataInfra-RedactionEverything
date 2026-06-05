"""
鍥剧墖鍖垮悕鍖栨ā鍧?
澶勭悊鍥剧墖/鎵弿浠剁殑鍖哄煙鍖垮悕鍖栵紙椹禌鍏?/ 楂樻柉妯＄硦 / 绾壊濉厖锛?
濮旀墭缁?VisionService.apply_redaction 鎵ц瀹為檯鍥惧儚澶勭悊
"""
import logging
from typing import Any

from app.models.schemas import BoundingBox, FileType, RedactionConfig

logger = logging.getLogger(__name__)

DEFAULT_IMAGE_REDACTION_METHOD = "mosaic"
DEFAULT_IMAGE_REDACTION_STRENGTH = 75
DEFAULT_IMAGE_FILL_COLOR = "#000000"
_VALID_IMAGE_REDACTION_METHODS = {"mosaic", "blur", "fill"}
_VISUAL_SAFE_FILL_RGB_MIN = 245
_OVERSIZED_BOX_AREA_RATIO = 0.45
_OVERSIZED_BOX_EDGE_RATIO = 0.85
_VISUAL_BOX_TYPES = {
    "barcode",
    "business_license",
    "face",
    "id_card",
    "license_plate",
    "official_seal",
    "passport",
    "qr_code",
    "signature",
    "stamp",
}
_VISUAL_BOX_SOURCES = {
    "visual_features",
    "visual_feature_model",
    "local_fallback",
    "manual",
}


def _config_value(config: Any, key: str) -> Any:
    if isinstance(config, dict):
        return config.get(key)
    return getattr(config, key, None)


def resolve_image_redaction_options(config: Any) -> tuple[str, int, str]:
    """Return image redaction options with direct-call friendly defaults."""
    method = _config_value(config, "image_redaction_method") or DEFAULT_IMAGE_REDACTION_METHOD
    if method not in _VALID_IMAGE_REDACTION_METHODS:
        logger.warning("invalid image redaction method %r; falling back to mosaic", method)
        method = DEFAULT_IMAGE_REDACTION_METHOD

    raw_strength = _config_value(config, "image_redaction_strength")
    if raw_strength in (None, ""):
        strength = DEFAULT_IMAGE_REDACTION_STRENGTH
    else:
        try:
            strength = int(raw_strength)
        except (TypeError, ValueError):
            logger.warning("invalid image redaction strength %r; falling back to 75", raw_strength)
            strength = DEFAULT_IMAGE_REDACTION_STRENGTH
    strength = max(1, min(100, strength))

    fill_color = _config_value(config, "image_fill_color") or DEFAULT_IMAGE_FILL_COLOR
    return str(method), strength, str(fill_color)


def _clip_unit(value: Any) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, numeric))


def _safe_box(box: BoundingBox) -> BoundingBox | None:
    x1 = _clip_unit(box.x)
    y1 = _clip_unit(box.y)
    x2 = _clip_unit(float(box.x) + float(box.width))
    y2 = _clip_unit(float(box.y) + float(box.height))
    if x2 <= x1 or y2 <= y1:
        logger.warning("dropping invalid image redaction box %s after clipping", box.id)
        return None
    width = x2 - x1
    height = y2 - y1
    if x1 == box.x and y1 == box.y and width == box.width and height == box.height:
        return box
    return box.model_copy(update={"x": x1, "y": y1, "width": width, "height": height})


def _safe_boxes(boxes: list[BoundingBox]) -> list[BoundingBox]:
    safe: list[BoundingBox] = []
    for box in boxes:
        clipped = _safe_box(box)
        if clipped is not None:
            safe.append(clipped)
    return safe


def _hex_to_rgb(fill_color: str) -> tuple[int, int, int] | None:
    value = (fill_color or "").strip().lstrip("#")
    if len(value) != 6:
        return None
    try:
        return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))
    except ValueError:
        return None


def _is_white_like_fill(fill_color: str) -> bool:
    rgb = _hex_to_rgb(fill_color)
    return rgb is not None and min(rgb) >= _VISUAL_SAFE_FILL_RGB_MIN


def _is_visual_box(box: BoundingBox) -> bool:
    box_type = str(getattr(box, "type", "") or "").lower()
    source = str(getattr(box, "source", "") or "").lower()
    evidence_source = str(getattr(box, "evidence_source", "") or "").lower()
    source_detail = str(getattr(box, "source_detail", "") or "").lower()
    return (
        box_type in _VISUAL_BOX_TYPES
        or source in _VISUAL_BOX_SOURCES
        or evidence_source in _VISUAL_BOX_SOURCES
        or source_detail in _VISUAL_BOX_SOURCES
    )


def _is_oversized_box(box: BoundingBox) -> bool:
    width = max(0.0, min(1.0, float(box.width)))
    height = max(0.0, min(1.0, float(box.height)))
    return (
        width * height >= _OVERSIZED_BOX_AREA_RATIO
        or width >= _OVERSIZED_BOX_EDGE_RATIO
        or height >= _OVERSIZED_BOX_EDGE_RATIO
    )


def prepare_image_redaction(
    boxes: list[BoundingBox],
    config: Any,
) -> tuple[list[BoundingBox], str, int, str]:
    """Clamp boxes and choose a non-erasing effect for risky visual regions."""
    method, strength, fill_color = resolve_image_redaction_options(config)
    safe_boxes = _safe_boxes(boxes)
    selected_boxes = [box for box in safe_boxes if box.selected]

    has_visual_box = any(_is_visual_box(box) for box in selected_boxes)
    has_oversized_box = any(_is_oversized_box(box) for box in selected_boxes)

    if method == "fill" and has_visual_box and _is_white_like_fill(fill_color):
        logger.info("white fill on visual image boxes is converted to mosaic redaction")
        method = DEFAULT_IMAGE_REDACTION_METHOD
    elif method in {"fill", "blur"} and has_oversized_box:
        logger.info("oversized image boxes use mosaic redaction to avoid full-area erase")
        method = DEFAULT_IMAGE_REDACTION_METHOD

    return selected_boxes, method, strength, fill_color


class ImageRedactorMixin:
    """
    鍥剧墖鍖垮悕鍖栨柟娉曢泦鍚?
    璁捐涓?mixin锛岀敱 Redactor 绫荤户鎵夸娇鐢?
    瑕佹眰瀹夸富绫诲叿鏈?self.vision_service 灞炴€э紙VisionService 瀹炰緥锛?
    """

    async def _redact_image(
        self,
        file_path: str,
        file_type: FileType,
        selected_boxes: list[BoundingBox],
        output_path: str,
        config: RedactionConfig,
    ) -> int:
        """
        鍥剧墖/鎵弿浠跺尶鍚嶅寲锛欻aS Image 椋庢牸鍧楃骇鍖垮悕鍖?
        椹禌鍏?/ 楂樻柉妯＄硦 / 绾壊濉厖锛屼笌鏂囨湰 replacement_mode 鏃犲叧

        Args:
            file_path: 杈撳叆鏂囦欢璺緞
            file_type: 鏂囦欢绫诲瀷锛圥DF_SCANNED 鎴?IMAGE锛?
            selected_boxes: 閫変腑鐨勮竟鐣屾鍒楄〃
            output_path: 杈撳嚭鏂囦欢璺緞
            config: 鍖垮悕鍖栭厤缃?

        Returns:
            鍖垮悕鍖栧尯鍩熸暟閲?
        """
        safe_boxes, method, strength, fill_color = prepare_image_redaction(selected_boxes, config)

        await self.vision_service.apply_redaction(
            file_path,
            file_type,
            safe_boxes,
            output_path,
            image_method=method,
            strength=strength,
            fill_color=fill_color,
        )

        return len(safe_boxes)
