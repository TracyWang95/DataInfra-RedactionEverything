from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass
from typing import Any

import httpx
from PIL import Image, ImageOps

from app.core.config import settings
from app.core.retry import RETRYABLE_HTTPX, retry_async
from app.core.visual_feature_categories import (
    DEFAULT_VISUAL_FEATURE_SLUGS,
    SLUG_TO_NAME_ZH,
    filter_visual_feature_slugs,
    is_visual_feature_slug,
    normalize_visual_slug,
)
from app.models.schemas import BoundingBox
from app.services import model_config_service
from app.services.vision.seal_color_cascade import (
    propose_colored_seal_regions,
    raw_colored_component_bboxes,
)

logger = logging.getLogger(__name__)

# JPEG encode quality for the image sent to the chat model
_JPEG_QUALITY = 92
# Smallest allowed longest-side (px) when downscaling the chat request image
_MIN_IMAGE_SIDE = 256
# Fallback longest-side cap (px) when no setting is configured
_DEFAULT_MAX_IMAGE_SIDE = 2048
# Slack multiplier deciding whether boxes are normalized (0..coord) vs absolute pixels
_COORD_MODE_TOLERANCE = 1.05
# Retry budget / base backoff (s) for the detect HTTP call
_DETECT_MAX_RETRIES = 2
_DETECT_BASE_DELAY = 1.0
# Fallback max-new-tokens cap when no setting is configured
_DEFAULT_MAX_NEW_TOKENS = 8192
# Sampling defaults / caps for the chat request
_DEFAULT_TEMPERATURE = 0.1
_MAX_TEMPERATURE = 0.2
_DEFAULT_TOP_P = 0.6
# Default confidence when the model omits one
_DEFAULT_DETECT_CONFIDENCE = 0.8
_DEFAULT_CHECKLIST_CONFIDENCE = 0.82

# Zero-recall tile retry: LA's input is downscaled to its max side, so small
# page artifacts (binding-seal slivers on the margins, watermark QR codes at
# the page foot) can vanish at full-page scale while detecting reliably on a
# native-resolution crop. When a requested category yields nothing on the
# full frame, re-run just that category on a validated tile set. Window
# geometry is start/center/end anchoring with half-size windows: any object
# smaller than half a window lies fully inside at least one tile, so nothing
# that size can be lost to a tile seam. Tile hits are pure gap-filling: any
# tile box intersecting a full-frame box is discarded (the full frame
# outranks the zoom - a zoomed handwritten signature must not come back as a
# phantom "seal" on top of the signature the full frame already found).
_TILE_RETRY_MARGIN_SLUGS = frozenset({"official_seal"})
_TILE_RETRY_BOTTOM_SLUGS = frozenset({"qr_code"})
# LA reads degraded machine codes as either sibling; both mask identically.
_MACHINE_CODE_SIBLINGS = frozenset({"qr_code", "barcode"})


def _axis_positions(total: int, window: int) -> list[int]:
    """start / center / end anchor offsets for a sliding window."""
    last = max(0, total - window)
    return sorted({0, last // 2, last})


def _margin_tiles(width: int, height: int) -> list[tuple[int, int, int, int]]:
    """L/R margin strips: binding seals sit on page edges by definition.
    Strip width W//3 - validated on real binding-seal pages: narrower strips
    starve the model of page context and edge slivers stop being recognised
    as stamps."""
    strip = max(1, width // 3)
    window = max(1, height // 2)
    tiles = []
    for x0 in (0, width - strip):
        for y0 in _axis_positions(height, window):
            tiles.append((x0, y0, x0 + strip, min(height, y0 + window)))
    return tiles


def _bottom_tiles(width: int, height: int) -> list[tuple[int, int, int, int]]:
    """Bottom H//4 row in three overlapped half-width windows: scanner
    watermark QR codes live at the page foot; QR codes elsewhere are
    body-scale and the full frame sees them."""
    row_top = height - max(1, height // 4)
    window = max(1, width // 2)
    return [
        (x0, row_top, min(width, x0 + window), height)
        for x0 in _axis_positions(width, window)
    ]


@dataclass
class LocateGroundingTimings:
    model: int = 0
    prepare: int = 0
    draw: int = 0
    total: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "model": self.model,
            "prepare": self.prepare,
            "draw": self.draw,
            "total": self.total,
        }


def _elapsed_ms(start: float) -> int:
    return max(0, round((time.perf_counter() - start) * 1000))


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
        try:
            data = json.loads(match.group(1))
        except json.JSONDecodeError:
            return {"objects": [], "raw_response": text}
    if isinstance(data, list):
        return {"objects": data}
    if isinstance(data, dict) and isinstance(data.get("objects"), list):
        return data
    return {"objects": [], "raw_response": text}


def _image_data_url(image_data: bytes) -> str:
    return f"data:image/jpeg;base64,{base64.b64encode(image_data).decode('ascii')}"


def _prepare_jpeg(image_data: bytes, max_side: int) -> tuple[bytes, tuple[int, int]]:
    image = ImageOps.exif_transpose(Image.open(io.BytesIO(image_data))).convert("RGB")
    if max(image.size) > max_side:
        image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    encoded = io.BytesIO()
    image.save(encoded, format="JPEG", quality=_JPEG_QUALITY, optimize=True)
    return encoded.getvalue(), image.size


def _clamp_box(x: float, y: float, width: float, height: float) -> tuple[float, float, float, float] | None:
    x = max(0.0, min(1.0, x))
    y = max(0.0, min(1.0, y))
    width = max(0.0, min(1.0 - x, width))
    height = max(0.0, min(1.0 - y, height))
    if width <= 0.0 or height <= 0.0:
        return None
    return x, y, width, height


def _normalize_box(raw_box: Any, width: int, height: int) -> tuple[float, float, float, float] | None:
    if not isinstance(raw_box, list | tuple) or len(raw_box) != 4:
        return None
    try:
        x1, y1, x2, y2 = [float(value) for value in raw_box]
    except (TypeError, ValueError):
        return None
    coord = max(1.0, float(settings.VISUAL_FEATURES_COORD_MODE))
    if max(x1, y1, x2, y2) <= coord * _COORD_MODE_TOLERANCE:
        x1, x2 = x1 / coord * width, x2 / coord * width
        y1, y2 = y1 / coord * height, y2 / coord * height
    x1, x2 = sorted((max(0.0, min(float(width), x1)), max(0.0, min(float(width), x2))))
    y1, y2 = sorted((max(0.0, min(float(height), y1)), max(0.0, min(float(height), y2))))
    if x2 <= x1 or y2 <= y1:
        return None  # degenerate (non-positive area); trust LA for everything else
    return x1 / width, y1 / height, (x2 - x1) / width, (y2 - y1) / height


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


class LocateAnythingGroundingService:
    """Single adapter for all visual grounding boxes produced by LocateAnything."""

    def __init__(self) -> None:
        self.last_raw_response: str | None = None

    async def detect_categories(
        self,
        image_data: bytes,
        page: int,
        pipeline_types: list[Any] | None,
    ) -> tuple[list[BoundingBox], dict[str, int]]:
        total_start = time.perf_counter()
        timings = LocateGroundingTimings()
        slugs = None if pipeline_types is None else [str(getattr(item, "id", item)) for item in pipeline_types]
        model_slugs = filter_visual_feature_slugs(slugs if slugs is not None else list(DEFAULT_VISUAL_FEATURE_SLUGS))
        if model_slugs is not None and not model_slugs:
            timings.total = _elapsed_ms(total_start)
            logger.info("LocateAnything visual category stage skipped: no supported fixed visual categories")
            return [], timings.as_dict()

        model_start = time.perf_counter()
        # Parallel inference across both GPUs: fan out one request per category
        # so the load balancer round-robins them onto GPU0/GPU1 concurrently.
        # Each LA call then does exactly one MoonViT encode + one generation, so
        # the default {signature, official_seal} pair finishes in ~one category's
        # time (~2s) instead of two sequential passes (~4s) on a single card.
        # VISUAL_SINGLE_CALL (GLM backend): multi-category recall does NOT
        # collapse there, so one prompt covers every category in one call.
        single_call = bool(getattr(settings, "VISUAL_SINGLE_CALL", False))
        if model_slugs is not None and len(model_slugs) > 1 and not single_call:
            results = await asyncio.gather(
                *[self._post_detect(image_data, [slug]) for slug in model_slugs],
                return_exceptions=True,
            )
            raw_boxes = []
            for slug, res in zip(model_slugs, results, strict=False):
                if isinstance(res, BaseException):
                    logger.warning("LocateAnything category %s failed, skipping: %s", slug, res)
                    continue
                raw_boxes.extend(res)
        else:
            raw_boxes = await self._post_detect(image_data, model_slugs)
        timings.model = _elapsed_ms(model_start)

        boxes: list[BoundingBox] = []
        for index, raw in enumerate(raw_boxes):
            slug = normalize_visual_slug(raw.get("category", ""))
            if not is_visual_feature_slug(slug):
                logger.debug("Skipping unsupported LocateAnything category: %s", raw.get("category"))
                continue
            try:
                normalized = _clamp_box(
                    float(raw.get("x") or 0),
                    float(raw.get("y") or 0),
                    float(raw.get("width") or 0),
                    float(raw.get("height") or 0),
                )
            except (TypeError, ValueError):
                normalized = None
            if normalized is None:
                continue
            x, y, width, height = normalized
            boxes.append(
                BoundingBox(
                    id=f"locate_{index}_{uuid.uuid4().hex[:8]}",
                    x=x,
                    y=y,
                    width=width,
                    height=height,
                    type=slug,
                    text=SLUG_TO_NAME_ZH.get(slug, slug),
                    page=page,
                    confidence=float(raw.get("confidence", _DEFAULT_DETECT_CONFIDENCE) or _DEFAULT_DETECT_CONFIDENCE),
                    source="visual_features",
                    source_detail="locate_anything:detect",
                    evidence_source="visual_feature_model",
                )
            )
        has_image_url = str(getattr(settings, "HAS_IMAGE_URL", "") or "").strip()
        if has_image_url and model_slugs:
            supplement_start = time.perf_counter()
            try:
                yolo_boxes = await self._detect_has_image(has_image_url, image_data, page, model_slugs)
            except Exception as exc:
                yolo_boxes = []
                logger.warning("HaS-Image supplement failed: %s", exc)
            boxes.extend(yolo_boxes)
            logger.info(
                "HaS-Image supplement added %d box(es) in %dms",
                len(yolo_boxes),
                _elapsed_ms(supplement_start),
            )

        if (
            bool(getattr(settings, "VISUAL_SEAL_COLOR_CASCADE", True))
            and model_slugs
            and "official_seal" in model_slugs
        ):
            # Color->VLM seal cascade (supersedes the margin refine). The
            # full-frame VLM misses faint / edge / photocopy-fragmented COLORED
            # stamps on salience (page_04's binding seal is invisible to it at
            # every zoom), but they are strong colored ink: propose colored-ink
            # regions (red/blue/purple; clustering fragments) and run the VLM
            # on a tight crop of each — the crop makes the faint stamp salient
            # enough to detect, and colored text / rules get no box. What gets
            # redacted depends on whether the cluster is figure or ground:
            # a minority-of-page cluster is ink, and its connected extent is
            # the stamp impression (redact it all); a cluster flooding the
            # majority of the page means chroma failed to separate ink from a
            # colored scene background (a document photographed on a wooden
            # desk), so only the VLM's boxes inside the crop carry location —
            # inheriting the flooded extent painted that whole page as one
            # giant seal. Black-on-white photocopy seals have no chroma and
            # are out of reach here.
            cascade_start = time.perf_counter()
            proposals = propose_colored_seal_regions(image_data)
            existing_seals = [b for b in boxes if b.type == "official_seal"]

            def _overlapping_seals(px: float, py: float, pw: float, ph: float) -> list[BoundingBox]:
                return [
                    s
                    for s in existing_seals
                    if px < s.x + s.width and s.x < px + pw
                    and py < s.y + s.height and s.y < py + ph
                ]

            # Route each proposal by how many found seals sit on it:
            # - exactly one, figure-sized: the stamp is found, and the
            #   cluster's ink may extend past the found box (page_03's
            #   numbering arc below it) — grow the box over the cluster's
            #   ACTUAL ink components (not the bridged extent: the Yueyang
            #   photo bridged three red underlines into the seal's cluster
            #   and the raw extent painted a page-wide box). Flooded clusters
            #   (colored scene background) must not grow anything.
            # - none, or >=2 (the shard path: GLM flakily segments page_02's
            #   binding-seal column; the color connected-component says they
            #   are one impression): send to the confirm crop.
            try:
                image = ImageOps.exif_transpose(
                    Image.open(io.BytesIO(image_data))
                ).convert("RGB")
            except Exception:
                logger.warning("Seal color cascade: image decode failed", exc_info=True)
                image = None
            raw_comps: list[tuple[float, float, float, float]] | None = None

            def _cluster_ink(proposal: tuple[float, float, float, float]) -> list[tuple[float, float, float, float]]:
                nonlocal raw_comps
                if raw_comps is None:
                    try:
                        raw_comps = raw_colored_component_bboxes(image_data)
                    except Exception:
                        raw_comps = []
                px, py, pw, ph = proposal
                return [
                    c for c in raw_comps
                    if px <= c[0] + c[2] / 2 <= px + pw and py <= c[1] + c[3] / 2 <= py + ph
                ]

            grown = 0
            to_confirm = []
            for p in proposals:
                px, py, pw, ph = p
                on_it = _overlapping_seals(px, py, pw, ph)
                if len(on_it) != 1:
                    to_confirm.append(p)
                    continue
                if pw * ph >= 0.5:
                    continue
                s = on_it[0]
                gx, gy, gw, gh = self._grow_seal_over_cluster_ink(
                    (s.x, s.y, s.width, s.height), _cluster_ink(p)
                )
                if gw * gh > s.width * s.height:
                    clamped = _clamp_box(gx, gy, gw, gh)
                    if clamped is None:
                        continue
                    for i, b in enumerate(boxes):
                        if b is s:
                            boxes[i] = s.model_copy(update={
                                "x": clamped[0], "y": clamped[1],
                                "width": clamped[2], "height": clamped[3],
                            })
                            grown += 1
                            break
            if image is not None:
                results = await asyncio.gather(
                    *[self._confirm_seal_crop(image, p) for p in to_confirm],
                    return_exceptions=True,
                )
            else:
                results = []
            code_boxes = [b for b in boxes if b.type in ("qr_code", "barcode")]
            added = 0
            for (px, py, pw, ph), confirmed in zip(to_confirm, results, strict=False):
                if isinstance(confirmed, BaseException):
                    continue
                if not confirmed:
                    # The detector sees no seal on the sliver crop — but a
                    # tiny remnant (numbering arc, broken rim) does not read
                    # as "a seal" without context. Ask the remnant-aware
                    # question on a context crop; straight-line ink (printed
                    # text, date stamps) answers 否. Ink overlapping a
                    # detected machine code is already explained by the code
                    # (the CamScanner logo inside the QR watermark) — same
                    # cross-detector arbitration as _prefer_yolo_machine_codes.
                    on_code = any(
                        px < c.x + c.width and c.x < px + pw
                        and py < c.y + c.height and c.y < py + ph
                        for c in code_boxes
                    )
                    if not on_code and pw * ph < 0.5 and await self._confirm_seal_fragment(
                        image, (px, py, pw, ph)
                    ):
                        keep = [(px, py, pw, ph)]
                    else:
                        continue
                elif pw * ph < 0.5 and len(confirmed) == 1:
                    # Figure cluster holding ONE impression (minority-of-page
                    # ink, and the VLM sees exactly one stamp in the crop):
                    # grow the VLM's box over the cluster's actual ink — the
                    # VLM box under-covers tall/fragmented ink (page_02's
                    # column), while the bridged extent over-covers when
                    # non-seal ink got pulled into the cluster (the Yueyang
                    # underlines). Component-wise growth takes both sides.
                    keep = [self._grow_seal_over_cluster_ink(
                        confirmed[0], _cluster_ink((px, py, pw, ph))
                    )]
                else:
                    # Otherwise the cluster extent is not one stamp's ink:
                    # either chroma flooded a majority of the page (colored
                    # scene background — a document photographed on a wooden
                    # desk — where the extent is the scene), or fragment
                    # bridging connected several adjacent stamps into one
                    # cluster (img2's stacked pair) and painting the extent
                    # would fuse them. The color channel knows connectivity,
                    # the VLM knows cardinality — its boxes carry the
                    # per-stamp locations.
                    keep = confirmed
                for bx, by, bw, bh in keep:
                    clamped = _clamp_box(bx, by, bw, bh)
                    if clamped is None:
                        continue
                    x, y, width_n, height_n = clamped
                    boxes.append(BoundingBox(
                        id=f"seal_color_{uuid.uuid4().hex[:8]}",
                        x=x, y=y, width=width_n, height=height_n,
                        type="official_seal",
                        text=SLUG_TO_NAME_ZH.get("official_seal", "official_seal"),
                        page=page,
                        confidence=_DEFAULT_DETECT_CONFIDENCE,
                        source="visual_features",
                        source_detail="seal_color_cascade",
                        evidence_source="visual_feature_model",
                    ))
                    added += 1
            logger.info(
                "Seal color cascade: %d box(es) from %d proposals in %dms",
                added, len(to_confirm), _elapsed_ms(cascade_start),
            )
        elif (
            bool(getattr(settings, "VISUAL_EDGE_SEAL_REFINE", True))
            and model_slugs
            and "official_seal" in model_slugs
        ):
            # Binding (margin) seals: GLM's FULL-FRAME seal recall on thin edge
            # slivers is unreliable AND non-monotonic in the requested category
            # count — page_02's right binding column is found with 4 categories,
            # missed entirely with 7 (what the medical/full preset sends, the
            # user-reported miss), and hallucinated as a 7-box column with 1.
            # So gating a margin re-detect on "a full-frame seal already exists
            # on this edge" rides that same flaky signal. Instead, whenever
            # official_seal is requested, always probe BOTH full-height
            # outer-third margin strips (single-category detect, which is
            # stable: page_02 right 5/5 hit, seal-less edges 0/0) and union the
            # result with the full-frame seals.
            refine_start = time.perf_counter()

            def _both_margins(slug: str, width: int, height: int) -> list[tuple[int, int, int, int]]:
                strip = max(1, width // 3)
                return [(0, 0, strip, height), (width - strip, 0, width, height)]

            refine_boxes = await self._detect_on_tiles(
                image_data,
                page,
                ["official_seal"],
                tiles_for=_both_margins,
                source_detail="locate_anything:edge_refine",
            )
            # GLM reads a barcode/QR in the margin as a seal (med's top
            # barcode). Drop any margin-seal box overlapping a machine-code
            # box — the code is already covered by its own detection. Same
            # cross-detector arbitration as _prefer_yolo_machine_codes.
            code_boxes = [b for b in boxes if b.type in ("qr_code", "barcode")]

            def _overlaps_code(rb: BoundingBox) -> bool:
                return any(
                    rb.x < c.x + c.width and c.x < rb.x + rb.width
                    and rb.y < c.y + c.height and c.y < rb.y + rb.height
                    for c in code_boxes
                )

            refine_boxes = [rb for rb in refine_boxes if not _overlaps_code(rb)]
            # Merge: fold each margin box into the nearest SAME-COLUMN full-frame
            # seal (x-spans overlap) as a grow-only hull — this both extends an
            # edge seal the full-frame clipped and keeps a center stamp the
            # strip clips (contract 0.557) from bulging a different seal. A
            # margin box with no same-column seal is a binding seal the
            # full-frame missed entirely (page_02) -> add it. Coverage only grows.
            originals = [
                (i, b) for i, b in enumerate(boxes) if b.type == "official_seal"
            ]
            folded = added = 0
            for rb in refine_boxes:
                same_col = [
                    item for item in originals
                    if item[1].x < rb.x + rb.width and rb.x < item[1].x + item[1].width
                ]
                if same_col:
                    rb_cy = rb.y + rb.height / 2.0
                    idx, target = min(
                        same_col,
                        key=lambda item: abs(item[1].y + item[1].height / 2.0 - rb_cy),
                    )
                    x1 = min(target.x, rb.x)
                    y1 = min(target.y, rb.y)
                    x2 = max(target.x + target.width, rb.x + rb.width)
                    y2 = max(target.y + target.height, rb.y + rb.height)
                    boxes[idx] = target.model_copy(update={
                        "x": x1, "y": y1, "width": x2 - x1, "height": y2 - y1,
                    })
                    originals = [
                        (i, boxes[i] if i == idx else b) for i, b in originals
                    ]
                    folded += 1
                else:
                    boxes.append(rb)
                    originals.append((len(boxes) - 1, rb))
                    added += 1
            logger.info(
                "Edge-seal margin probe: %d folded, %d added, in %dms",
                folded, added, _elapsed_ms(refine_start),
            )

        retry_slugs = [
            slug
            for slug in (model_slugs or [])
            if slug in _TILE_RETRY_MARGIN_SLUGS | _TILE_RETRY_BOTTOM_SLUGS
            and not any(b.type == slug for b in boxes)
        ]
        if retry_slugs and not bool(getattr(settings, "VISUAL_TILE_RETRY", True)):
            retry_slugs = []
        if retry_slugs:
            retry_start = time.perf_counter()
            tile_boxes = await self._detect_on_tiles(image_data, page, retry_slugs)
            # Gap-filling only: a tile hit that touches anything the full
            # frame already found is the zoom second-guessing the page-scale
            # call - discard it.
            tile_boxes = [
                t
                for t in tile_boxes
                if not any(
                    t.x < b.x + b.width
                    and b.x < t.x + t.width
                    and t.y < b.y + b.height
                    and b.y < t.y + t.height
                    for b in boxes
                )
            ]
            boxes.extend(tile_boxes)
            logger.info(
                "LocateAnything tile retry for %s kept %d box(es) in %dms",
                retry_slugs,
                len(tile_boxes),
                _elapsed_ms(retry_start),
            )

        timings.total = _elapsed_ms(total_start)
        logger.info("LocateAnything fixed visual stage parsed %d boxes", len(boxes))
        return boxes, timings.as_dict()

    async def _detect_has_image(
        self,
        base_url: str,
        image_data: bytes,
        page: int,
        slugs: list[str],
    ) -> list[BoundingBox]:
        """HaS-Image YOLO supplement: one ~100ms native-resolution pass.

        The YOLO detector auto-scales to any input size, so the small page
        artifacts the grounding model loses to downscaling (stacked seal
        halves, watermark QR codes) come back from here. The service ignores
        slugs outside its 21 fixed classes; duplicates of grounding boxes
        collapse in the merge layer (seal hull merge / IoU dedup).
        """
        body = {
            "image_base64": base64.b64encode(image_data).decode("utf-8"),
            "conf": settings.VISUAL_FEATURES_CONF,
            "categories": [str(slug) for slug in slugs],
        }
        async with httpx.AsyncClient(timeout=settings.VISUAL_FEATURES_TIMEOUT, trust_env=False) as client:
            response = await client.post(f"{base_url.rstrip('/')}/detect", json=body)
            response.raise_for_status()
        boxes: list[BoundingBox] = []
        for raw in response.json().get("boxes") or []:
            slug = normalize_visual_slug(str(raw.get("category", "")))
            if slug not in set(slugs):
                continue
            try:
                normalized = _clamp_box(
                    float(raw.get("x") or 0),
                    float(raw.get("y") or 0),
                    float(raw.get("width") or 0),
                    float(raw.get("height") or 0),
                )
            except (TypeError, ValueError):
                normalized = None
            if normalized is None:
                continue
            x, y, width, height = normalized
            boxes.append(
                BoundingBox(
                    id=f"has_image_{uuid.uuid4().hex[:8]}",
                    x=x,
                    y=y,
                    width=width,
                    height=height,
                    type=slug,
                    text=SLUG_TO_NAME_ZH.get(slug, slug),
                    page=page,
                    confidence=float(raw.get("confidence", _DEFAULT_DETECT_CONFIDENCE) or _DEFAULT_DETECT_CONFIDENCE),
                    source="visual_features",
                    source_detail="has_image:yolo",
                    evidence_source="visual_feature_model",
                )
            )
        return boxes

    async def _confirm_seal_crop(
        self, image: Image.Image, region: tuple[float, float, float, float]
    ) -> list[tuple[float, float, float, float]]:
        """Run seal detection on a tight crop around a colored-ink region and
        return the VLM's boxes mapped to page coordinates (empty = rejected).

        The crop makes a faint/edge/fragmented stamp salient enough to detect,
        while colored text / rules get no box. The VLM's box — not the
        proposal extent — is what the caller redacts: the proposal only says
        where to look, so an over-wide proposal (colored scene background
        flooding the chroma mask) cannot itself become a page-sized seal box.
        """
        px, py, pw, ph = region
        width, height = image.size
        pad = int(0.02 * max(width, height))
        x0 = max(0, int(px * width) - pad)
        y0 = max(0, int(py * height) - pad)
        x1 = min(width, int((px + pw) * width) + pad)
        y1 = min(height, int((py + ph) * height) + pad)
        if x1 <= x0 or y1 <= y0:
            return []
        crop_w, crop_h = x1 - x0, y1 - y0
        buf = io.BytesIO()
        image.crop((x0, y0, x1, y1)).save(buf, format="JPEG", quality=_JPEG_QUALITY)
        try:
            raw_boxes = await self._post_detect(buf.getvalue(), ["official_seal"])
        except Exception:
            return []
        mapped: list[tuple[float, float, float, float]] = []
        for raw in raw_boxes:
            if normalize_visual_slug(str(raw.get("category", ""))) != "official_seal":
                continue
            try:
                normalized = _clamp_box(
                    float(raw.get("x") or 0),
                    float(raw.get("y") or 0),
                    float(raw.get("width") or 0),
                    float(raw.get("height") or 0),
                )
            except (TypeError, ValueError):
                continue
            if normalized is None:
                continue
            bx, by, bw, bh = normalized
            page_box = _clamp_box(
                (x0 + bx * crop_w) / width,
                (y0 + by * crop_h) / height,
                bw * crop_w / width,
                bh * crop_h / height,
            )
            if page_box is not None:
                mapped.append(page_box)
        return mapped

    # Verbatim from the 2026-07-07 v3 discrimination test, 4/4: page_06 bottom
    # arc 是 / br_customs blue DATE STAMP 否 / CT red printed disclaimer 否 /
    # CamScanner logo 否. Arc-vs-straight IS the question — a date stamp is
    # physically stamped ink too, so exclusion lists alone do not reject it
    # (v1/v2 failed exactly there). Same long-prompt-conservatism caution as
    # the detect prompts: do not embellish.
    _SEAL_FRAGMENT_PROMPT = (
        "图中央区域有一处彩色墨迹。判断它是否为圆形印章的残迹。\n"
        "圆章残迹的特征：残缺的圆弧或环形边框、沿弧线弯曲排列的文字或数字、扇形分布的印泥痕迹。\n"
        "如果墨迹是水平直线排列的（如日期、编号、文字行、logo图标），它不是圆章残迹，输出 否。\n"
        "只输出一个字：是 或 否"
    )
    async def _confirm_seal_fragment(
        self, image: Image.Image, region: tuple[float, float, float, float]
    ) -> bool:
        """Remnant-aware second opinion for detector-rejected ink proposals.

        A stamp remnant (numbering arc, broken rim) is too small to read as
        "a seal" on its own sliver crop, but is recognizable as a remnant
        given surrounding context and a remnant-phrased yes/no question —
        while straight-line printed colored text still answers 否. Context is
        scale-relative: one proposal size on each side.
        """
        px, py, pw, ph = region
        width, height = image.size
        x0 = max(0, int((px - pw) * width))
        y0 = max(0, int((py - ph) * height))
        x1 = min(width, int((px + 2 * pw) * width))
        y1 = min(height, int((py + 2 * ph) * height))
        if x1 <= x0 or y1 <= y0:
            return False
        buf = io.BytesIO()
        image.crop((x0, y0, x1, y1)).save(buf, format="JPEG", quality=_JPEG_QUALITY)
        payload = {
            "model": settings.VISUAL_FEATURES_MODEL_NAME,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": _image_data_url(buf.getvalue())}},
                        {"type": "text", "text": self._SEAL_FRAGMENT_PROMPT},
                    ],
                }
            ],
            "temperature": 0.1,
            "max_tokens": 800,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        url = _json_endpoint(model_config_service.get_visual_features_base_url(), "chat/completions")
        try:
            async with httpx.AsyncClient(timeout=settings.VISUAL_FEATURES_TIMEOUT, trust_env=False) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                content = str(response.json().get("choices", [{}])[0].get("message", {}).get("content", ""))
        except Exception:
            logger.warning("Seal fragment confirm failed", exc_info=True)
            return False
        return "是" in content

    def _grow_seal_over_cluster_ink(
        self,
        anchor: tuple[float, float, float, float],
        ink_comps: list[tuple[float, float, float, float]],
    ) -> tuple[float, float, float, float]:
        """Grow a confirmed seal box over its cluster's actual ink, grow-only.

        Components TOUCHING the anchor are the stamp's own ink — free union,
        to a fixpoint (fragments chain outward). DETACHED components join only
        from within the stamp's footprint shadow (span containment): page_03's
        numbering arc sits inside the stamp's x-span and joins; the Yueyang
        photo's red text underlines (bridged into the seal's cluster) extend
        far beyond the stamp's footprint and stay out — inheriting the whole
        bridged extent there painted a page-wide box.
        """
        grown = anchor

        def _union(a: tuple[float, float, float, float], b: tuple[float, float, float, float]):
            x1, y1 = min(a[0], b[0]), min(a[1], b[1])
            x2 = max(a[0] + a[2], b[0] + b[2])
            y2 = max(a[1] + a[3], b[1] + b[3])
            return (x1, y1, x2 - x1, y2 - y1)

        def _touches(c: tuple[float, float, float, float], box: tuple[float, float, float, float]) -> bool:
            return (
                c[0] < box[0] + box[2] and box[0] < c[0] + c[2]
                and c[1] < box[1] + box[3] and box[1] < c[1] + c[3]
            )

        pending = list(ink_comps)
        changed = True
        while changed:
            changed = False
            rest = []
            for c in pending:
                if _touches(c, grown):
                    grown = _union(grown, c)
                    changed = True
                else:
                    rest.append(c)
            pending = rest
        for c in pending:
            # A stamp's own detached remnants (numbering row, rim fragments)
            # sit within the stamp's FOOTPRINT SHADOW: their x-span (or
            # y-span) is contained in the anchor's. Page-furniture ink that
            # bridging pulled into the cluster (the Yueyang text underlines)
            # extends beyond the stamp's footprint and stays out. Topological
            # containment — no model call, no thresholds. (The rubric cannot
            # arbitrate here: a numbering row and an underline are both
            # near-straight strips, and every marked/unmarked window variant
            # judged them alike.)
            x_within = c[0] >= anchor[0] and c[0] + c[2] <= anchor[0] + anchor[2]
            y_within = c[1] >= anchor[1] and c[1] + c[3] <= anchor[1] + anchor[3]
            if x_within or y_within:
                grown = _union(grown, c)
        return grown

    async def _detect_on_tiles(
        self,
        image_data: bytes,
        page: int,
        slugs: list[str],
        tiles_for=None,
        source_detail: str = "locate_anything:tile_retry",
    ) -> list[BoundingBox]:
        """Re-run categories on native-resolution tiles.

        Default tiling: margin strips for binding seals, a bottom row for
        watermark QR codes; callers may pass ``tiles_for(slug, w, h)`` for a
        custom tile set (edge-seal refine). Hits are mapped back to
        page-normalized coordinates; duplicates from overlapping tiles
        collapse in the merge layer (seal hull merge / IoU dedup).
        """
        try:
            image = ImageOps.exif_transpose(Image.open(io.BytesIO(image_data))).convert("RGB")
        except Exception:
            logger.warning("tile retry: could not decode page image", exc_info=True)
            return []
        width, height = image.size
        if width < 2 or height < 2:
            return []
        tasks = []
        metas = []
        for slug in slugs:
            if tiles_for is not None:
                tiles = tiles_for(slug, width, height)
            else:
                tiles = (
                    _margin_tiles(width, height)
                    if slug in _TILE_RETRY_MARGIN_SLUGS
                    else _bottom_tiles(width, height)
                )
            for x0, y0, x1, y1 in tiles:
                encoded = io.BytesIO()
                image.crop((x0, y0, x1, y1)).save(encoded, format="JPEG", quality=_JPEG_QUALITY)
                tasks.append(self._post_detect(encoded.getvalue(), [slug]))
                metas.append((slug, x0, y0, x1 - x0, y1 - y0))
        results = await asyncio.gather(*tasks, return_exceptions=True)
        boxes: list[BoundingBox] = []
        for (slug, x0, y0, tile_w, tile_h), result in zip(metas, results, strict=False):
            if isinstance(result, BaseException):
                logger.warning("tile retry %s failed on one tile: %s", slug, result)
                continue
            for raw in result:
                raw_slug = normalize_visual_slug(str(raw.get("category", "")))
                if raw_slug != slug and not (
                    slug in _MACHINE_CODE_SIBLINGS and raw_slug in _MACHINE_CODE_SIBLINGS
                ):
                    continue
                try:
                    normalized = _clamp_box(
                        float(raw.get("x") or 0),
                        float(raw.get("y") or 0),
                        float(raw.get("width") or 0),
                        float(raw.get("height") or 0),
                    )
                except (TypeError, ValueError):
                    normalized = None
                if normalized is None:
                    continue
                tile_x, tile_y, tile_box_w, tile_box_h = normalized
                mapped = _clamp_box(
                    (x0 + tile_x * tile_w) / width,
                    (y0 + tile_y * tile_h) / height,
                    tile_box_w * tile_w / width,
                    tile_box_h * tile_h / height,
                )
                if mapped is None:
                    continue
                x, y, box_w, box_h = mapped
                boxes.append(
                    BoundingBox(
                        id=f"locate_tile_{uuid.uuid4().hex[:8]}",
                        x=x,
                        y=y,
                        width=box_w,
                        height=box_h,
                        type=slug,
                        text=SLUG_TO_NAME_ZH.get(slug, slug),
                        page=page,
                        confidence=float(raw.get("confidence", _DEFAULT_DETECT_CONFIDENCE) or _DEFAULT_DETECT_CONFIDENCE),
                        source="visual_features",
                        source_detail=source_detail,
                        evidence_source="visual_feature_model",
                    )
                )
        return boxes

    async def detect_checklist(
        self,
        image_data: bytes,
        page: int,
        type_configs: list[Any],
        *,
        timeout: float | None = None,
    ) -> tuple[list[BoundingBox], dict[str, int]]:
        total_start = time.perf_counter()
        timings = LocateGroundingTimings()
        if not type_configs:
            timings.total = _elapsed_ms(total_start)
            return [], timings.as_dict()

        prepare_start = time.perf_counter()
        max_side = max(
            _MIN_IMAGE_SIDE,
            int(
                getattr(
                    settings,
                    "VISUAL_FEATURES_SIGNATURE_MAX_IMAGE_SIDE",
                    getattr(settings, "VISUAL_FEATURES_MAX_IMAGE_SIDE", _DEFAULT_MAX_IMAGE_SIDE),
                )
                or _DEFAULT_MAX_IMAGE_SIDE
            ),
        )
        request_image, (width, height) = _prepare_jpeg(image_data, max_side)
        timings.prepare = _elapsed_ms(prepare_start)

        model_start = time.perf_counter()
        content = await self._post_chat(request_image, _checklist_prompt(type_configs), timeout=timeout)
        timings.model = _elapsed_ms(model_start)
        self.last_raw_response = content

        parsed = _extract_json_payload(content)
        boxes = self._objects_to_boxes(parsed.get("objects") or [], type_configs, width, height, page)
        timings.total = _elapsed_ms(total_start)
        logger.info("LocateAnything checklist visual stage parsed %d boxes", len(boxes))
        return boxes, timings.as_dict()

    async def _post_detect(self, image_data: bytes, categories: list[str] | None) -> list[dict[str, Any]]:
        base_url = model_config_service.get_visual_features_base_url()
        url = f"{base_url}/detect"
        body: dict[str, Any] = {
            "image_base64": base64.b64encode(image_data).decode("utf-8"),
            "conf": settings.VISUAL_FEATURES_CONF,
        }
        if categories is not None:
            body["categories"] = categories

        async def request() -> httpx.Response:
            async with httpx.AsyncClient(timeout=settings.VISUAL_FEATURES_TIMEOUT, trust_env=False) as client:
                response = await client.post(url, json=body)
                response.raise_for_status()
                return response

        response = await retry_async(
            request,
            max_retries=_DETECT_MAX_RETRIES,
            base_delay=_DETECT_BASE_DELAY,
            retryable_exceptions=RETRYABLE_HTTPX,
        )
        data = response.json()
        return list(data.get("boxes") or [])

    async def _post_chat(self, image_data: bytes, prompt: str, *, timeout: float | None) -> str:
        config = model_config_service.get_visual_features_config()
        if not config:
            logger.info("LocateAnything checklist stage skipped: visual feature service is disabled or missing")
            return '{"objects":[]}'
        headers = {"Content-Type": "application/json"}
        if config.api_key:
            headers["Authorization"] = f"Bearer {config.api_key}"
        max_tokens = max(
            int(getattr(settings, "LOCATE_ANYTHING_MAX_NEW_TOKENS", _DEFAULT_MAX_NEW_TOKENS) or _DEFAULT_MAX_NEW_TOKENS),
            int(config.max_tokens or 0),
        )
        payload = {
            "model": config.model_name or settings.VISUAL_FEATURES_MODEL_NAME,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": _image_data_url(image_data)}},
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
            "temperature": min(float(config.temperature or _DEFAULT_TEMPERATURE), _MAX_TEMPERATURE),
            "top_p": float(config.top_p or _DEFAULT_TOP_P),
            "max_tokens": max_tokens,
            "stream": False,
            "chat_template_kwargs": {"enable_thinking": False},
            "thinking": {"type": "disabled"},
            "enable_thinking": False,
        }
        url = _json_endpoint(config.base_url or settings.VISUAL_FEATURES_BASE_URL, "chat/completions")
        request_timeout = float(timeout if timeout is not None else settings.VISUAL_FEATURES_TIMEOUT)

        async def request() -> httpx.Response:
            async with httpx.AsyncClient(timeout=request_timeout, trust_env=False) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                return response

        response = await retry_async(
            request,
            max_retries=_DETECT_MAX_RETRIES,
            base_delay=_DETECT_BASE_DELAY,
            retryable_exceptions=RETRYABLE_HTTPX,
        )
        data = response.json()
        return str(data.get("choices", [{}])[0].get("message", {}).get("content", ""))

    def _objects_to_boxes(
        self,
        objects: list[Any],
        type_configs: list[Any],
        width: int,
        height: int,
        page: int,
    ) -> list[BoundingBox]:
        by_id = {str(getattr(item, "id", "")).strip(): item for item in type_configs}
        name_to_id = {
            str(getattr(item, "name", "") or "").strip(): str(getattr(item, "id", "")).strip()
            for item in type_configs
        }
        boxes: list[BoundingBox] = []
        for index, obj in enumerate(objects):
            if not isinstance(obj, dict):
                continue
            type_id = str(obj.get("type_id") or "").strip()
            if type_id not in by_id:
                type_id = name_to_id.get(str(obj.get("label") or "").strip(), "")
            if type_id not in by_id and len(type_configs) == 1:
                type_id = str(getattr(type_configs[0], "id", "")).strip()
            if type_id not in by_id:
                continue
            normalized = _normalize_box(obj.get("box_2d"), width, height)
            if normalized is None:
                continue
            x, y, box_width, box_height = normalized
            type_config = by_id[type_id]
            label = str(getattr(type_config, "name", "") or obj.get("label") or type_id)
            boxes.append(
                BoundingBox(
                    id=f"locate_visual_{index}_{uuid.uuid4().hex[:8]}",
                    x=x,
                    y=y,
                    width=box_width,
                    height=box_height,
                    type=type_id,
                    text=str(obj.get("text") or label).strip() or label,
                    page=page,
                    confidence=max(0.0, min(1.0, float(obj.get("confidence", _DEFAULT_CHECKLIST_CONFIDENCE) or _DEFAULT_CHECKLIST_CONFIDENCE))),
                    source="visual_features",
                    source_detail=f"locate_anything:{obj.get('rule_matched') or 'checklist'}",
                    evidence_source="visual_feature_model",
                )
            )
        return boxes

