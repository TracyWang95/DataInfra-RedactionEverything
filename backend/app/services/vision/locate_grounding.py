from __future__ import annotations

import asyncio
import base64
import io
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any

import httpx
from PIL import Image, ImageOps

from app.core.config import settings
from app.core.retry import RETRYABLE_HTTPX, retry_async
from app.core.visual_feature_categories import (
    SLUG_TO_NAME_ZH,
    normalize_visual_slug,
)
from app.models.schemas import BoundingBox
from app.services import model_config_service
from app.services.vision.locate_payload import (
    _COORD_MODE_TOLERANCE,  # noqa: F401  # re-exported for API stability
    _JPEG_QUALITY,
    _clamp_box,
    _extract_json_payload,
    _image_data_url,
    _json_endpoint,
    _normalize_box,
    _prepare_jpeg,
)
from app.services.vision.locate_requests import (
    _checklist_prompt,
    _detect_requests,
    _type_rules,  # noqa: F401  # re-exported for API stability
)
from app.services.vision.locate_tiles import (
    _MACHINE_CODE_SIBLINGS,
    _TILE_RETRY_BOTTOM_SLUGS,
    _TILE_RETRY_GRID_SLUGS,
    _TILE_RETRY_MARGIN_SLUGS,
    _axis_positions,  # noqa: F401  # re-exported for API stability
    _bottom_tiles,
    _grid_tiles,
    _margin_tiles,
)
from app.services.vision.seal_color_cascade import (
    propose_colored_seal_regions,
    raw_colored_component_bboxes,
)

logger = logging.getLogger(__name__)

# Smallest allowed longest-side (px) when downscaling the chat request image
_MIN_IMAGE_SIDE = 256
# Fallback longest-side cap (px) when no setting is configured
_DEFAULT_MAX_IMAGE_SIDE = 2048
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
        # One detect request per target, each carrying its grounding query as
        # free text: a fixed category sends the user's 识别清单 wording (or its
        # factory default, _grounding_query), a custom label its human name
        # verbatim — the LA server holds no prompt table. Each is one
        # single-category call — LocateAnything's recall collapses when categories
        # share a prompt — round-robined across both GPUs. The box is tagged by the
        # REQUESTED target, never LA's echoed category, so a 中文 label is not
        # normalize-stripped and fixed + custom tags flow through ONE path.
        requests, model_slugs = _detect_requests(pipeline_types)
        if not requests:
            timings.total = _elapsed_ms(total_start)
            logger.info("LocateAnything visual category stage skipped: no visual categories")
            return [], timings.as_dict()
        # The user's grounding query per fixed slug, so every supplement pass
        # (tile retry, edge refine, signature) sends the same wording the main
        # detect sent — the 清单 owns the wording end to end.
        slug_set = set(model_slugs)
        query_by_slug = {rtype: tag for tag, rtype, _text in requests if rtype in slug_set}

        model_start = time.perf_counter()
        results = await asyncio.gather(
            *[self._post_detect(image_data, [tag]) for tag, _type, _text in requests],
            return_exceptions=True,
        )
        timings.model = _elapsed_ms(model_start)

        boxes: list[BoundingBox] = []
        for (tag, result_type, result_text), res in zip(requests, results, strict=True):
            if isinstance(res, BaseException):
                logger.warning("LocateAnything category %r failed, skipping: %s", tag, res)
                continue
            for raw in res:
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
                        id=f"locate_{uuid.uuid4().hex[:8]}",
                        x=x,
                        y=y,
                        width=width,
                        height=height,
                        type=result_type,
                        text=result_text,
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

        la_sig_url = str(getattr(settings, "LA_SIGNATURE_URL", "") or "").strip()
        if la_sig_url and model_slugs and "signature" in model_slugs:
            # Dedicated LocateAnything signature-only pass — higher recall on
            # faint handwritten signatures (the shared multi-category detect
            # missed the court-form 办案人 signature). Scoped to signature so the
            # validated seal/code behavior is untouched; its boxes union with the
            # main detect's in the merge layer (IoU dedup).
            la_start = time.perf_counter()
            try:
                la_boxes = await self._detect_la_signature(
                    la_sig_url, image_data, page, query_by_slug.get("signature", "signature")
                )
            except Exception as exc:
                la_boxes = []
                logger.warning("LocateAnything signature supplement failed: %s", exc)
            boxes.extend(la_boxes)
            logger.info(
                "LocateAnything signature supplement added %d box(es) in %dms",
                len(la_boxes),
                _elapsed_ms(la_start),
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
            # - none, or >=2 (the shard path: the grounding model flakily segments page_02's
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
            # Binding (margin) seals: the grounding model's FULL-FRAME seal recall on thin edge
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
                queries=query_by_slug,
            )
            # the grounding model reads a barcode/QR in the margin as a seal (med's top
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
            if slug in _TILE_RETRY_MARGIN_SLUGS | _TILE_RETRY_BOTTOM_SLUGS | _TILE_RETRY_GRID_SLUGS
            and not any(b.type == slug for b in boxes)
        ]
        if retry_slugs and not bool(getattr(settings, "VISUAL_TILE_RETRY", True)):
            retry_slugs = []
        if retry_slugs:
            retry_start = time.perf_counter()
            tile_boxes = await self._detect_on_tiles(image_data, page, retry_slugs, queries=query_by_slug)
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

        boxes = self._drop_solid_fill_seals(boxes, image_data)
        boxes = self._drop_skin_hue_fingerprints(boxes, image_data)
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

    async def _detect_la_signature(
        self,
        base_url: str,
        image_data: bytes,
        page: int,
        query: str = "signature",
    ) -> list[BoundingBox]:
        """LocateAnything signature-only pass. Same /detect contract as the main
        detect; we request just the signature query — the user's 清单 wording —
        so nothing else changes. Single-category call, so boxes are tagged by
        the request (no echo filtering, which a custom wording would fail)."""
        body = {
            "image_base64": base64.b64encode(image_data).decode("utf-8"),
            "conf": settings.VISUAL_FEATURES_CONF,
            "categories": [query],
        }
        async with httpx.AsyncClient(timeout=settings.VISUAL_FEATURES_TIMEOUT, trust_env=False) as client:
            response = await client.post(f"{base_url.rstrip('/')}/detect", json=body)
            response.raise_for_status()
        boxes: list[BoundingBox] = []
        for raw in response.json().get("boxes") or []:
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
                    id=f"la_sig_{uuid.uuid4().hex[:8]}",
                    x=x,
                    y=y,
                    width=width,
                    height=height,
                    type="signature",
                    text=SLUG_TO_NAME_ZH.get("signature", "signature"),
                    page=page,
                    confidence=float(raw.get("confidence", _DEFAULT_DETECT_CONFIDENCE) or _DEFAULT_DETECT_CONFIDENCE),
                    source="visual_features",
                    source_detail="locate_anything:signature",
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

    def _drop_solid_fill_seals(
        self, boxes: list[BoundingBox], image_data: bytes
    ) -> list[BoundingBox]:
        """Reject 'seals' that are solid colored fills, not stamp impressions.

        A 公章 is a sparse ink OUTLINE — border ring, star, arced text — with
        paper showing through: the colored-pixel coverage inside its box is low
        (measured ≤0.18 on every real stamp across the GT set). A printed
        masthead/banner/logo fill is majority-colored (中国裁判文书网 ribbon
        0.59, court emblem 0.83). The gap is ~3x, so the impression-vs-fill cut
        is insensitive to its exact position — a physical property of what a
        stamp IS, not a tuned score. Source-independent: catches the banner the
        color cascade grows a seed into, and any detector's solid-fill FP.
        Real stamps (sparse) always pass.
        """
        if not bool(getattr(settings, "VISUAL_SEAL_SOLID_FILL_REJECT", True)):
            return boxes
        seals = [b for b in boxes if b.type == "official_seal"]
        if not seals:
            return boxes
        try:
            import numpy as np

            img = ImageOps.exif_transpose(Image.open(io.BytesIO(image_data))).convert("RGB")
            arr = np.asarray(img).astype(np.int16)
            chroma = arr.max(axis=2) - arr.min(axis=2)  # same chroma as the color cascade
            height, width = chroma.shape[:2]
        except Exception:
            return boxes
        drop_ids: set[str] = set()
        for s in seals:
            x0, y0 = int(s.x * width), int(s.y * height)
            x1, y1 = int((s.x + s.width) * width), int((s.y + s.height) * height)
            region = chroma[max(0, y0):min(height, y1), max(0, x0):min(width, x1)]
            if region.size == 0:
                continue
            # majority of the box is colored ink -> a printed fill (banner/logo),
            # never a stamp impression (which leaves most of its box as paper).
            if float((region > 45).mean()) > 0.45:
                drop_ids.add(s.id)
        if drop_ids:
            logger.info("Dropped %d solid-fill (banner/logo) seal box(es)", len(drop_ids))
            return [b for b in boxes if b.id not in drop_ids]
        return boxes

    def _drop_skin_hue_fingerprints(
        self, boxes: list[BoundingBox], image_data: bytes
    ) -> list[BoundingBox]:
        """Reject 'fingerprint' boxes on REAL skin (the photographer's thumb
        holding the page), keep crimson stamp-pad impressions.

        Grid-tile retry zooms a page-holding thumb to salience and every
        grounding wording then boxes it — geometry cannot separate the two
        (the house photo's thumb reaches 24% into the frame). Pigment vs skin
        spectra can: stamp-pad ink absorbs BOTH green and blue, so inside a
        real print the colored pixels (same chroma>45 identity as the seal
        cascade) have G≈B — hue ratio (G-B)/(R-G) ≤ 0.12 on all 7 corpus
        prints. Skin is orange, G well above B — ratio ≥ 0.57 on both corpus
        thumbs. 0.35 is the geometric middle of that 5x gap, a property of
        what stamp ink IS, not a tuned score. Naive redness does NOT separate
        (thumb R-G 47-53 vs print 55-76 overlap: warm light makes skin red).
        Evidence-gated in the safe direction: a box whose pixels show no
        colored ink at all (a faint print) is KEPT — a missed redaction
        outranks a false box, so only a positively-skin-hued box is dropped.
        """
        if not bool(getattr(settings, "VISUAL_FINGERPRINT_INK_GATE", True)):
            return boxes
        prints = [b for b in boxes if b.type == "fingerprint"]
        if not prints:
            return boxes
        try:
            import numpy as np

            img = ImageOps.exif_transpose(Image.open(io.BytesIO(image_data))).convert("RGB")
            arr = np.asarray(img).astype(np.int16)
            height, width = arr.shape[:2]
        except Exception:
            return boxes
        drop_ids: set[str] = set()
        for b in prints:
            x0, y0 = int(b.x * width), int(b.y * height)
            x1, y1 = int((b.x + b.width) * width), int((b.y + b.height) * height)
            region = arr[max(0, y0):min(height, y1), max(0, x0):min(width, x1)]
            if region.size == 0:
                continue
            red = region[..., 0].astype(float)
            green = region[..., 1].astype(float)
            blue = region[..., 2].astype(float)
            colored = (region.max(axis=2) - region.min(axis=2)) > 45
            # hue is only meaningful on red-dominant colored pixels; a box with
            # none carries no ink evidence either way and is kept.
            reddish = colored & (red > green)
            if not reddish.any():
                continue
            ratio = float(np.median(((green - blue) / np.maximum(red - green, 1.0))[reddish]))
            if ratio > 0.35:
                drop_ids.add(b.id)
        if drop_ids:
            logger.info("Dropped %d skin-hued fingerprint box(es) (real thumb)", len(drop_ids))
            return [b for b in boxes if b.id not in drop_ids]
        return boxes

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
        queries: dict[str, str] | None = None,
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
                if slug in _TILE_RETRY_MARGIN_SLUGS:
                    tiles = _margin_tiles(width, height)
                elif slug in _TILE_RETRY_GRID_SLUGS:
                    tiles = _grid_tiles(width, height)
                else:
                    tiles = _bottom_tiles(width, height)
            for x0, y0, x1, y1 in tiles:
                encoded = io.BytesIO()
                image.crop((x0, y0, x1, y1)).save(encoded, format="JPEG", quality=_JPEG_QUALITY)
                # Same wording as the full-frame pass — the 清单 owns it.
                tasks.append(self._post_detect(encoded.getvalue(), [(queries or {}).get(slug, slug)]))
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
            "response_format": {"type": "json_object"},
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

