from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
import uuid
from dataclasses import dataclass
from io import BytesIO
from typing import Any

import httpx
import numpy as np
from PIL import Image, ImageOps

from app.core.config import settings
from app.core.gpu_inference_gate import shared_gpu_inference_slot
from app.models.schemas import BoundingBox
from app.services import model_config_service

logger = logging.getLogger(__name__)
_vlm_request_semaphore = asyncio.Semaphore(max(1, int(getattr(settings, "VLM_CONCURRENCY", 1) or 1)))


@dataclass(frozen=True)
class _DetectionView:
    name: str
    image_data: bytes
    width: int
    height: int
    max_side: int
    encoded_bytes: int
    crop_x: int
    crop_y: int
    crop_width: int
    crop_height: int
    original_width: int
    original_height: int


def _json_endpoint(base_url: str, suffix: str) -> str:
    base = (base_url or "").rstrip("/")
    if base.endswith("/v1"):
        return f"{base}/{suffix.lstrip('/')}"
    return f"{base}/v1/{suffix.lstrip('/')}"


def _extract_json_payload(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    if not raw:
        return {"objects": []}
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.I)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"(\{.*\}|\[.*\])", raw, re.S)
        if not match:
            return {"objects": [], "raw_response": text}
        data = json.loads(match.group(1))
    if isinstance(data, list) and len(data) == 1 and isinstance(data[0], dict) and isinstance(data[0].get("objects"), list):
        return data[0]
    if isinstance(data, list):
        return {"objects": data}
    if isinstance(data, dict):
        objects = data.get("objects")
        if isinstance(objects, list):
            return data
    return {"objects": [], "raw_response": text}


def _type_rules(type_config: Any) -> list[str]:
    rules = getattr(type_config, "rules", None) or []
    if rules:
        return [str(rule).strip() for rule in rules if str(rule).strip()]
    description = str(getattr(type_config, "description", "") or "").strip()
    if description:
        return [description]
    return [str(getattr(type_config, "name", "") or type_config.id)]


def _type_checklist(type_config: Any) -> list[dict[str, str]]:
    checklist = getattr(type_config, "checklist", None) or []
    rows: list[dict[str, str]] = []
    for item in checklist:
        if isinstance(item, dict):
            rule = str(item.get("rule") or "").strip()
            positive = str(item.get("positive_prompt") or "").strip()
            negative = str(item.get("negative_prompt") or "").strip()
        else:
            rule = str(getattr(item, "rule", "") or "").strip()
            positive = str(getattr(item, "positive_prompt", "") or "").strip()
            negative = str(getattr(item, "negative_prompt", "") or "").strip()
        if rule:
            rows.append(
                {
                    "rule": rule,
                    "positive_prompt": positive,
                    "negative_prompt": negative,
                },
            )
    if rows:
        return rows
    return [{"rule": rule, "positive_prompt": "", "negative_prompt": ""} for rule in _type_rules(type_config)]


def _selected_type_ids(type_configs: list[Any]) -> set[str]:
    return {str(getattr(item, "id", "")).strip().lower() for item in type_configs}


def _is_signature_only(type_configs: list[Any]) -> bool:
    return _selected_type_ids(type_configs) == {"signature"}


def _configured_checklist_lines(type_configs: list[Any]) -> list[str]:
    lines: list[str] = ["Configured visual checklist from UI:"]
    for item in type_configs:
        type_id = str(getattr(item, "id", "")).strip()
        name = str(getattr(item, "name", "") or type_id).strip()
        lines.append(f"- type_id={type_id}; name={name}")
        for index, row in enumerate(_type_checklist(item), start=1):
            lines.append(f"  {index}. Check: {row['rule']}")
            if row["positive_prompt"]:
                lines.append(f"     Positive: {row['positive_prompt']}")
            if row["negative_prompt"]:
                lines.append(f"     Negative: {row['negative_prompt']}")
        negative_enabled = bool(getattr(item, "negative_prompt_enabled", False))
        negative = str(getattr(item, "negative_prompt", "") or "").strip()
        if negative_enabled and negative:
            lines.append(f"  Exclude: {negative}")
    return lines


def _output_contract_lines(type_configs: list[Any], coord_mode: int) -> list[str]:
    allowed_ids = ", ".join(str(getattr(item, "id", "")).strip() for item in type_configs)
    return [
        'Schema: {"objects":[{"type_id":"<allowed type_id>","label":"<label>","box_2d":[xmin,ymin,xmax,ymax],"confidence":0.8,"rule_matched":"<type_id>#<rule_index>","text":""}]}',
        f"Allowed type_id: {allowed_ids}",
        f"Coordinates are integers in 0..{coord_mode}, origin top-left.",
        "Use one tight box per visible instance, around the ink/stroke/object pixels only.",
        "Do not merge separate instances into one box. Do not box nearby printed text, guide lines, table borders, seals, fingerprints, or blank background unless the configured type explicitly asks for them.",
        "If the visual evidence is ambiguous or only a form field label is visible, return no object for that area.",
        "Max 40 objects.",
        'If none, return {"objects":[]}.',
        "Return JSON only, no prose.",
    ]


def _few_shot_messages(type_configs: list[Any]) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    remaining = 5
    for item in type_configs:
        if remaining <= 0:
            break
        samples = getattr(item, "few_shot_samples", None) or []
        if not samples:
            continue
        enabled = bool(getattr(item, "few_shot_enabled", True))
        if not enabled:
            continue
        type_id = str(getattr(item, "id", "")).strip()
        name = str(getattr(item, "name", "") or type_id).strip()
        for sample in samples[:remaining]:
            if isinstance(sample, dict):
                sample_type = str(sample.get("type") or "positive").strip()
                image = str(sample.get("image") or "").strip()
                label = str(sample.get("label") or "").strip()
            else:
                sample_type = str(getattr(sample, "type", "positive") or "positive").strip()
                image = str(getattr(sample, "image", "") or "").strip()
                label = str(getattr(sample, "label", "") or "").strip()
            if not image:
                continue
            sample_kind = "positive" if sample_type == "positive" else "negative"
            sample_text = (
                f"Few-shot {sample_kind} sample for type_id={type_id}; name={name}. "
                f"{label or 'Learn this visual boundary and decision rule.'}"
            )
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": image}},
                        {"type": "text", "text": sample_text},
                    ],
                },
            )
            messages.append(
                {
                    "role": "assistant",
                    "content": (
                        f"Understood. This is a {sample_kind} reference for {type_id}. "
                        "Use it only as guidance for the final detection request."
                    ),
                },
            )
            remaining -= 1
            if remaining <= 0:
                break
    return messages


class VlmVisionService:
    """Checklist-driven VLM detector for custom visual features."""

    def __init__(self) -> None:
        self.last_raw_response: str | None = None

    def build_prompt(self, type_configs: list[Any]) -> str:
        coord_mode = int(settings.VLM_COORD_MODE)
        if _is_signature_only(type_configs):
            lines = [
                "Task: detect handwritten signer names/signatures only.",
                "Important visual distinction:",
                "- Printed text has regular font strokes and a straight baseline, such as 公司名称、法定代表人/授权代表（签字）：、日期.",
                "- A signature is irregular freehand ink, often larger, cursive, slanted, and may overlap the edge of a red seal.",
                "- In signature blocks, the target is the freehand name AFTER the printed label, not the printed label itself.",
                "- Box only the handwritten ink strokes. Do not include the printed label before it.",
                "- Do not detect circular or semicircular seals/stamps, including black stamp fragments.",
                "- If the page has multiple party signature blocks, such as left/right purchaser/supplier or甲方/乙方 blocks, inspect each block independently and return every handwritten signature.",
                "- Signatures may overlap red seals; do not reject black freehand strokes only because a red seal is nearby.",
                "Ignore red seals, black seals, printed labels, company names, dates, QR codes, table lines, blank fields, and explanatory text.",
            ]
            lines.extend(_configured_checklist_lines(type_configs))
            lines.extend(_output_contract_lines(type_configs, coord_mode))
            return "\n".join(lines)
        lines: list[str] = [
            "只检测清单中明确要求的视觉目标。只返回紧凑 JSON，不要解释，不要 markdown。",
            "必须同时满足正向规则，并避开负向规则；不确定时不要输出候选框。",
            "不要根据文字标签、空白栏位或上下文推测目标存在，必须能在图像中看到实际目标笔迹。",
        ]
        lines.extend(_configured_checklist_lines(type_configs))
        lines.extend(_output_contract_lines(type_configs, coord_mode))
        return "\n".join(lines)

    def _encode_view(
        self,
        image: Image.Image,
        *,
        name: str,
        crop_x: int,
        crop_y: int,
        crop_width: int,
        crop_height: int,
        original_width: int,
        original_height: int,
        max_side: int,
    ) -> _DetectionView:
        view = image.copy()
        if max(view.size) > max_side:
            view.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
        encoded = BytesIO()
        view.save(encoded, format="JPEG", quality=90, optimize=True)
        image_bytes = encoded.getvalue()
        return _DetectionView(
            name=name,
            image_data=image_bytes,
            width=view.width,
            height=view.height,
            max_side=max_side,
            encoded_bytes=len(image_bytes),
            crop_x=crop_x,
            crop_y=crop_y,
            crop_width=crop_width,
            crop_height=crop_height,
            original_width=original_width,
            original_height=original_height,
        )

    def _max_image_side(self, type_configs: list[Any]) -> int:
        full_max_side = max(256, int(getattr(settings, "VLM_MAX_IMAGE_SIDE", 640) or 640))
        if not _is_signature_only(type_configs):
            return full_max_side
        signature_max_side = max(
            256,
            int(getattr(settings, "VLM_SIGNATURE_MAX_IMAGE_SIDE", full_max_side) or full_max_side),
        )
        return min(full_max_side, signature_max_side)

    def _detection_views(self, image: Image.Image, type_configs: list[Any]) -> list[_DetectionView]:
        original_width, original_height = image.size
        max_side = self._max_image_side(type_configs)
        return [
            self._encode_view(
                image,
                name="full",
                crop_x=0,
                crop_y=0,
                crop_width=original_width,
                crop_height=original_height,
                original_width=original_width,
                original_height=original_height,
                max_side=max_side,
            )
        ]

    async def detect(
        self,
        image_data: bytes,
        page: int,
        type_configs: list[Any],
    ) -> list[BoundingBox]:
        if not type_configs:
            return []
        config = model_config_service.get_vlm_config()
        if not config:
            logger.info("VLM skipped: vlm_service is disabled or missing")
            return []

        img = ImageOps.exif_transpose(Image.open(BytesIO(image_data))).convert("RGB")
        views = self._detection_views(img, type_configs)
        prompt = self.build_prompt(type_configs)
        headers = {"Content-Type": "application/json"}
        if config.api_key:
            headers["Authorization"] = f"Bearer {config.api_key}"
        max_tokens = int(config.max_tokens or 1024)
        max_tokens = max(384, min(max_tokens, 1536))
        base_payload: dict[str, Any] = {
            "model": config.model_name or settings.VLM_MODEL_NAME,
            "messages": [],
            "temperature": min(float(config.temperature or 0.1), 0.2),
            "top_p": float(config.top_p or 0.6),
            "max_tokens": max_tokens,
            "stream": False,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        if config.enable_thinking is False:
            base_payload["thinking"] = {"type": "disabled"}
            base_payload["enable_thinking"] = False

        url = _json_endpoint(config.base_url or settings.VLM_BASE_URL, "chat/completions")
        view_meta = ",".join(
            f"{view.name}:{view.width}x{view.height}/max{view.max_side}/{max(1, view.encoded_bytes // 1024)}KB"
            for view in views
        )
        logger.info(
            "VLM request started: model=%s url=%s types=%d image=%dx%d views=%d view_meta=%s timeout=%.1fs",
            base_payload["model"],
            url,
            len(type_configs),
            img.width,
            img.height,
            len(views),
            view_meta,
            float(settings.VLM_TIMEOUT),
        )
        boxes: list[BoundingBox] = []
        raw_responses: list[str] = []
        async with _vlm_request_semaphore:
            async with shared_gpu_inference_slot("GLM VLM"):
                async with httpx.AsyncClient(timeout=float(settings.VLM_TIMEOUT), trust_env=False) as client:
                    for view in views:
                        image_base64 = base64.b64encode(view.image_data).decode("ascii")
                        view_prompt = (
                            f"{prompt}\nDetection view: {view.name}. "
                            "Coordinates must be relative to the supplied image for this request."
                        )
                        payload = {
                            **base_payload,
                            "messages": [
                                *_few_shot_messages(type_configs),
                                {
                                    "role": "user",
                                    "content": [
                                        {
                                            "type": "image_url",
                                            "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"},
                                        },
                                        {"type": "text", "text": view_prompt},
                                    ],
                                },
                            ],
                        }
                        response = await client.post(url, headers=headers, json=payload)
                        response.raise_for_status()
                        data = response.json()
                        content = str(data.get("choices", [{}])[0].get("message", {}).get("content", ""))
                        raw_responses.append(f"[{view.name}] {content}")
                        parsed = _extract_json_payload(content)
                        view_boxes = self._objects_to_boxes(
                            parsed.get("objects") or [],
                            type_configs,
                            view,
                            page,
                        )
                        for bbox in view_boxes:
                            if str(view.name).startswith("signature_") and str(bbox.type).lower() == "signature":
                                boxes = [existing for existing in boxes if not self._is_duplicate(bbox, existing)]
                            if not any(self._is_duplicate(bbox, existing) for existing in boxes):
                                boxes.append(bbox)
        boxes = self._refine_signature_boxes(img, boxes)
        detail_signature_boxes = [
            box
            for box in boxes
            if str(box.type).lower() == "signature" and ":signature_" in str(box.source_detail or "")
        ]
        if detail_signature_boxes:
            boxes = [
                box
                for box in boxes
                if str(box.type).lower() != "signature" or ":signature_" in str(box.source_detail or "")
            ]
        self.last_raw_response = "\n".join(raw_responses)
        logger.info("VLM request parsed %d boxes", len(boxes))
        return boxes

    def _objects_to_boxes(
        self,
        objects: list[Any],
        type_configs: list[Any],
        view: _DetectionView,
        page: int,
    ) -> list[BoundingBox]:
        by_id = {str(getattr(item, "id", "")): item for item in type_configs}
        name_to_id = {
            str(getattr(item, "name", "") or "").strip(): str(getattr(item, "id", ""))
            for item in type_configs
        }
        boxes: list[BoundingBox] = []
        for index, obj in enumerate(objects):
            if not isinstance(obj, dict):
                continue
            confidence = self._confidence(obj.get("confidence"))
            if confidence < 0.3:
                continue
            type_id = str(obj.get("type_id") or "").strip()
            if type_id not in by_id:
                type_id = name_to_id.get(str(obj.get("label") or "").strip(), "")
            if type_id not in by_id and len(type_configs) == 1:
                type_id = str(getattr(type_configs[0], "id", ""))
            if type_id not in by_id:
                continue
            normalized = self._normalize_box(obj.get("box_2d"), view.width, view.height)
            if normalized is None:
                continue
            x, y, box_width, box_height = normalized
            abs_x = view.crop_x + x * view.crop_width
            abs_y = view.crop_y + y * view.crop_height
            abs_width = box_width * view.crop_width
            abs_height = box_height * view.crop_height
            type_config = by_id[type_id]
            label = str(getattr(type_config, "name", "") or obj.get("label") or type_id)
            text = str(obj.get("text") or label).strip() or label
            bbox = BoundingBox(
                id=f"vlm_{index}_{uuid.uuid4().hex[:8]}",
                x=abs_x / view.original_width,
                y=abs_y / view.original_height,
                width=abs_width / view.original_width,
                height=abs_height / view.original_height,
                type=type_id,
                text=text,
                page=page,
                confidence=confidence,
                source="vlm",
                source_detail=f"{obj.get('rule_matched') or 'vlm'}:{view.name}",
                evidence_source="vlm_model",
            )
            if not any(self._is_duplicate(bbox, existing) for existing in boxes):
                boxes.append(bbox)
        return boxes

    @staticmethod
    def _confidence(value: Any) -> float:
        try:
            return max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            return 0.8

    @staticmethod
    def _normalize_box(raw_box: Any, width: int, height: int) -> tuple[float, float, float, float] | None:
        if not isinstance(raw_box, list | tuple) or len(raw_box) != 4:
            return None
        try:
            x1, y1, x2, y2 = [float(v) for v in raw_box]
        except (TypeError, ValueError):
            return None
        coord = max(1.0, float(settings.VLM_COORD_MODE))
        # Accept either 0..1000 VLM coordinates or direct pixel coordinates.
        if max(x1, y1, x2, y2) <= coord * 1.05:
            x1, x2 = x1 / coord * width, x2 / coord * width
            y1, y2 = y1 / coord * height, y2 / coord * height
        x1, x2 = sorted((max(0.0, min(float(width), x1)), max(0.0, min(float(width), x2))))
        y1, y2 = sorted((max(0.0, min(float(height), y1)), max(0.0, min(float(height), y2))))
        if x2 - x1 < 2 or y2 - y1 < 2:
            return None
        if ((x2 - x1) * (y2 - y1)) / max(1.0, width * height) > 0.85:
            return None
        return x1 / width, y1 / height, (x2 - x1) / width, (y2 - y1) / height

    def _refine_signature_boxes(self, image: Image.Image, boxes: list[BoundingBox]) -> list[BoundingBox]:
        refined: list[BoundingBox] = []
        for box in boxes:
            if str(box.type).lower() != "signature":
                refined.append(box)
                continue
            signature_box = self._refine_signature_box(image, box)
            if signature_box is not None:
                refined.append(signature_box)
        return refined

    def _refine_signature_box(self, image: Image.Image, box: BoundingBox) -> BoundingBox | None:
        width, height = image.size
        x1 = max(0, min(width - 1, int(round(box.x * width))))
        y1 = max(0, min(height - 1, int(round(box.y * height))))
        x2 = max(x1 + 1, min(width, int(round((box.x + box.width) * width))))
        y2 = max(y1 + 1, min(height, int(round((box.y + box.height) * height))))
        box_w = x2 - x1
        box_h = y2 - y1
        if box_w < 2 or box_h < 2:
            return box
        line_like = (box_w / max(1, box_h)) >= 3.2
        if line_like:
            pad_x = max(int(box_w * 2.6), int(width * 0.18))
            pad_top = max(int(box_h * 0.55), 24)
            pad_bottom = max(int(box_h * 1.3), 48)
        else:
            pad_x = max(int(box_w * 0.35), 24)
            pad_top = max(int(box_h * 0.35), 20)
            pad_bottom = max(int(box_h * 0.35), 20)

        sx1 = max(0, x1 - pad_x)
        sx2 = min(width, x2 + pad_x)
        sy1 = max(0, y1 - pad_top)
        sy2 = min(height, y2 + pad_bottom)
        if sx2 <= sx1 or sy2 <= sy1:
            return box

        crop = np.asarray(image.crop((sx1, sy1, sx2, sy2)).convert("RGB"))
        mask = self._signature_stroke_mask(crop)
        if int(mask.sum()) < max(18, int(mask.size * 0.0008)):
            return None
        mask = self._select_signature_row_cluster(mask, y1 - sy1, y2 - sy1)
        if line_like:
            mask = self._select_signature_column_cluster(mask, x1 - sx1, x2 - sx1)
        if int(mask.sum()) < max(18, int(mask.size * 0.0008)):
            return None

        ys, xs = np.where(mask)
        if len(xs) == 0 or len(ys) == 0:
            return box

        nx1 = max(0, sx1 + int(xs.min()) - 5)
        ny1 = max(0, sy1 + int(ys.min()) - 5)
        nx2 = min(width, sx1 + int(xs.max()) + 6)
        ny2 = min(height, sy1 + int(ys.max()) + 6)
        if nx2 <= nx1 or ny2 <= ny1:
            return box

        new_w = nx2 - nx1
        new_h = ny2 - ny1
        if new_w < 4 or new_h < 4:
            return box
        if line_like and (new_w / max(1, new_h)) > 5.5 and (new_w / max(1, width)) > 0.28:
            return None
        if not line_like and (new_w * new_h) > (box_w * box_h * 3.5):
            return box

        return box.model_copy(
            update={
                "x": nx1 / width,
                "y": ny1 / height,
                "width": new_w / width,
                "height": new_h / height,
                "source_detail": f"{box.source_detail}:stroke_refined",
            },
        )

    @staticmethod
    def _expand_signature_box(image: Image.Image, box: BoundingBox) -> BoundingBox:
        width, height = image.size
        x1 = max(0, int(round(box.x * width)))
        y1 = max(0, int(round(box.y * height)))
        x2 = min(width, int(round((box.x + box.width) * width)))
        y2 = min(height, int(round((box.y + box.height) * height)))
        box_w = max(1, x2 - x1)
        box_h = max(1, y2 - y1)

        sx1 = max(0, x1 - max(36, int(box_w * 0.7)))
        sx2 = min(width, x2 + max(120, int(box_w * 2.2)))
        anchor_page_center = (x1 + x2) / 2
        if anchor_page_center < width * 0.48:
            sx2 = min(sx2, int(width * 0.50))
        elif anchor_page_center > width * 0.52:
            sx1 = max(sx1, int(width * 0.50))
        sy1 = max(0, y2 - max(6, int(box_h * 0.25)))
        sy2 = min(height, y2 + max(130, int(box_h * 3.4)))
        crop = np.asarray(image.crop((sx1, sy1, sx2, sy2)).convert("RGB"))
        mask = VlmVisionService._signature_stroke_mask(crop)
        if int(mask.sum()) >= max(18, int(mask.size * 0.0008)):
            col_counts = mask.sum(axis=0)
            min_col_pixels = max(2, int(mask.shape[0] * 0.025))
            active_cols = np.where(col_counts >= min_col_pixels)[0]
            clusters: list[tuple[int, int, int, int]] = []
            if len(active_cols):
                start = int(active_cols[0])
                prev = int(active_cols[0])
                for raw_col in active_cols[1:]:
                    col = int(raw_col)
                    if col - prev <= 10:
                        prev = col
                        continue
                    submask = mask[:, start:prev + 1]
                    rows = np.where(submask)[0]
                    if len(rows):
                        clusters.append((start, prev, int(rows.min()), int(rows.max())))
                    start = col
                    prev = col
                submask = mask[:, start:prev + 1]
                rows = np.where(submask)[0]
                if len(rows):
                    clusters.append((start, prev, int(rows.min()), int(rows.max())))

            if clusters:
                anchor_center = ((x1 + x2) / 2) - sx1
                anchor_right = x2 - sx1

                def score(cluster: tuple[int, int, int, int]) -> float:
                    c1, c2, r1, r2 = cluster
                    cluster_mask = mask[r1:r2 + 1, c1:c2 + 1]
                    pixels = float(cluster_mask.sum())
                    center = (c1 + c2) / 2
                    vertical_span = max(1, r2 - r1 + 1)
                    right_bias = 18.0 if anchor_center <= center <= anchor_right + 140 else 0.0
                    distance_penalty = min(abs(center - anchor_right), abs(center - anchor_center)) * 0.85
                    return pixels + vertical_span * 6.0 + right_bias - distance_penalty

                right_side_clusters = [
                    cluster for cluster in clusters if ((cluster[0] + cluster[1]) / 2) >= anchor_right + 24
                ]
                if right_side_clusters:
                    selected = max(right_side_clusters, key=score)
                else:
                    selected = max(
                        clusters,
                        key=lambda cluster: score(cluster) - abs(((cluster[0] + cluster[1]) / 2) - anchor_center),
                    )
                selected_clusters = [selected]
                for cluster in clusters:
                    if cluster == selected:
                        continue
                    horizontal_gap = max(cluster[0] - selected[1], selected[0] - cluster[1], 0)
                    row_overlap = min(cluster[3], selected[3]) - max(cluster[2], selected[2])
                    if horizontal_gap <= 28 and row_overlap >= -18:
                        selected_clusters.append(cluster)
                c1 = min(cluster[0] for cluster in selected_clusters)
                c2 = max(cluster[1] for cluster in selected_clusters)
                r1 = min(cluster[2] for cluster in selected_clusters)
                r2 = max(cluster[3] for cluster in selected_clusters)
                selected_mask = mask[r1:r2 + 1, c1:c2 + 1]
                ys, xs = np.where(selected_mask)
                if len(xs) and len(ys):
                    nx1 = max(0, sx1 + c1 + int(xs.min()) - 8)
                    ny1 = max(0, sy1 + r1 + int(ys.min()) - 8)
                    nx2 = min(width, sx1 + c1 + int(xs.max()) + 12)
                    ny2 = min(height, sy1 + r1 + int(ys.max()) + 12)
                    if nx2 > nx1 and ny2 > ny1:
                        return box.model_copy(
                            update={
                                "x": nx1 / width,
                                "y": ny1 / height,
                                "width": (nx2 - nx1) / width,
                                "height": (ny2 - ny1) / height,
                                "source_detail": f"{box.source_detail}:signature_stroke_adjusted",
                            }
                        )

        pad_x = max(28, int(box_w * 0.45))
        pad_top = max(8, int(box_h * 0.45))
        pad_bottom = max(54, int(box_h * 1.4))
        nx1 = max(0, x1 - pad_x)
        ny1 = max(0, y1 - pad_top)
        nx2 = min(width, x2 + pad_x)
        ny2 = min(height, y2 + pad_bottom)
        return box.model_copy(
            update={
                "x": nx1 / width,
                "y": ny1 / height,
                "width": (nx2 - nx1) / width,
                "height": (ny2 - ny1) / height,
                "source_detail": f"{box.source_detail}:coverage_adjusted",
            }
        )

    @staticmethod
    def _signature_stroke_mask(rgb: np.ndarray) -> np.ndarray:
        arr = rgb.astype(np.int16, copy=False)
        red = arr[:, :, 0]
        green = arr[:, :, 1]
        blue = arr[:, :, 2]
        gray = (red * 30 + green * 59 + blue * 11) / 100
        span = arr.max(axis=2) - arr.min(axis=2)
        red_mark = (red > 120) & (red > green * 1.22) & (red > blue * 1.22)
        dark_ink = (gray < 120) | ((gray < 158) & (span < 48))
        mask = dark_ink & ~red_mark

        crop_width = mask.shape[1]
        if crop_width > 0:
            row_counts = mask.sum(axis=1)
            rule_rows = np.where(row_counts > max(80, crop_width * 0.32))[0]
            for row in rule_rows:
                mask[max(0, row - 2): min(mask.shape[0], row + 3), :] = False
        return mask

    @staticmethod
    def _select_signature_row_cluster(mask: np.ndarray, target_y1: int, target_y2: int) -> np.ndarray:
        row_counts = mask.sum(axis=1)
        min_row_pixels = max(2, int(mask.shape[1] * 0.003))
        active_rows = np.where(row_counts >= min_row_pixels)[0]
        if len(active_rows) == 0:
            return mask

        clusters: list[tuple[int, int, int]] = []
        start = int(active_rows[0])
        prev = int(active_rows[0])
        for raw_row in active_rows[1:]:
            row = int(raw_row)
            if row - prev <= 4:
                prev = row
                continue
            clusters.append((start, prev, int(row_counts[start:prev + 1].sum())))
            start = row
            prev = row
        clusters.append((start, prev, int(row_counts[start:prev + 1].sum())))

        overlap_margin = 5
        overlapping = [
            cluster
            for cluster in clusters
            if cluster[1] >= target_y1 - overlap_margin and cluster[0] <= target_y2 + overlap_margin
        ]
        selected = max(overlapping or clusters, key=lambda item: item[2])
        next_mask = np.zeros_like(mask)
        top = max(0, selected[0] - 3)
        bottom = min(mask.shape[0], selected[1] + 4)
        next_mask[top:bottom, :] = mask[top:bottom, :]
        return next_mask

    @staticmethod
    def _select_signature_column_cluster(mask: np.ndarray, target_x1: int, target_x2: int) -> np.ndarray:
        """For line-shaped VLM boxes, keep ink near the VLM horizontal anchor."""
        col_counts = mask.sum(axis=0)
        min_col_pixels = max(2, int(mask.shape[0] * 0.03))
        active_cols = np.where(col_counts >= min_col_pixels)[0]
        if len(active_cols) == 0:
            return mask

        clusters: list[tuple[int, int, int]] = []
        start = int(active_cols[0])
        prev = int(active_cols[0])
        for raw_col in active_cols[1:]:
            col = int(raw_col)
            if col - prev <= 8:
                prev = col
                continue
            clusters.append((start, prev, int(col_counts[start:prev + 1].sum())))
            start = col
            prev = col
        clusters.append((start, prev, int(col_counts[start:prev + 1].sum())))

        target_width = max(1, target_x2 - target_x1)
        margin = max(18, int(target_width * 0.35))
        anchor_left = max(0, target_x1 - margin)
        anchor_right = min(mask.shape[1] - 1, target_x2 + margin)
        overlapping = [
            cluster
            for cluster in clusters
            if cluster[1] >= anchor_left and cluster[0] <= anchor_right
        ]
        if not overlapping:
            center = (target_x1 + target_x2) / 2
            overlapping = [min(clusters, key=lambda item: min(abs(item[0] - center), abs(item[1] - center)))]

        target_center = (target_x1 + target_x2) / 2

        def cluster_score(cluster: tuple[int, int, int]) -> tuple[float, int]:
            center = (cluster[0] + cluster[1]) / 2
            overlap = max(0, min(cluster[1], target_x2) - max(cluster[0], target_x1))
            return (overlap - abs(center - target_center) * 0.25, cluster[2])

        selected = max(overlapping, key=cluster_score)
        selected_clusters = [selected]
        for cluster in overlapping:
            if cluster == selected:
                continue
            gap = max(cluster[0] - selected[1], selected[0] - cluster[1], 0)
            if gap <= 24:
                selected_clusters.append(cluster)

        left = max(0, min(cluster[0] for cluster in selected_clusters) - 8)
        right = min(mask.shape[1], max(cluster[1] for cluster in selected_clusters) + 9)
        next_mask = np.zeros_like(mask)
        next_mask[:, left:right] = mask[:, left:right]
        return next_mask

    @staticmethod
    def _is_duplicate(candidate: BoundingBox, existing: BoundingBox) -> bool:
        if candidate.type != existing.type:
            return False
        x1 = max(candidate.x, existing.x)
        y1 = max(candidate.y, existing.y)
        x2 = min(candidate.x + candidate.width, existing.x + existing.width)
        y2 = min(candidate.y + candidate.height, existing.y + existing.height)
        if x2 <= x1 or y2 <= y1:
            return False
        inter = (x2 - x1) * (y2 - y1)
        area_a = candidate.width * candidate.height
        area_b = existing.width * existing.height
        union = area_a + area_b - inter
        smaller = min(area_a, area_b)
        return (inter / union if union > 0 else 0.0) > 0.3 or (
            inter / smaller if smaller > 0 else 0.0
        ) > 0.7

    @staticmethod
    def _overlap_ratio(candidate: BoundingBox, existing: BoundingBox) -> float:
        x1 = max(candidate.x, existing.x)
        y1 = max(candidate.y, existing.y)
        x2 = min(candidate.x + candidate.width, existing.x + existing.width)
        y2 = min(candidate.y + candidate.height, existing.y + existing.height)
        if x2 <= x1 or y2 <= y1:
            return 0.0
        inter = (x2 - x1) * (y2 - y1)
        area = max(candidate.width * candidate.height, 1e-9)
        return inter / area
