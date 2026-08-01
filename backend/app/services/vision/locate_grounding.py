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
)
from app.services.vision.machine_code_detector import (
    BARCODE_SLUG,
    QR_CODE_SLUG,
    detect_machine_code_regions,
)

logger = logging.getLogger(__name__)

# Smallest allowed longest-side (px) when downscaling the chat request image
_MIN_IMAGE_SIDE = 256
# Fallback longest-side cap (px) when no setting is configured
_DEFAULT_MAX_IMAGE_SIDE = 2048
# Retry budget / base backoff (s) for the detect HTTP call
_DETECT_MAX_RETRIES = 2
_DETECT_BASE_DELAY = 1.0
# 5xx/429 from the LA load balancer are TRANSIENT overload (the shared decoder
# queue is momentarily full under a tile burst), not client errors — surfaced as
# a retryable error so retry_async backs off and re-sends instead of dropping the
# call. A dropped tile call silently loses whatever print/seal that tile would
# have recovered — a missed redaction, the one failure direction that leaks.
_TRANSIENT_DETECT_STATUSES = frozenset({429, 500, 502, 503, 504})
# Fallback max-new-tokens cap when no setting is configured
_DEFAULT_MAX_NEW_TOKENS = 8192
# Sampling defaults / caps for the chat request
# Official model-card sampling (temperature=0.7/top_p=0.9). The old 0.1
# override was measured as a HARD RECALL KILLER on the per-GPU A/B
# (5 truth images x3 runs: fingerprints farm 0/0/0 vs 2/2/2, house 1/1/1 vs
# 4/4/4 at GT=4; zero new false positives on the CT-report negatives) — the
# long-standing "0/2 sampling flake" was actually the lb alternating between
# a 0.1 GPU (missing) and an official-default GPU (hitting).
_DEFAULT_TEMPERATURE = 0.7
_MAX_TEMPERATURE = 0.7
_DEFAULT_TOP_P = 0.9

def _measured_confidence(raw: object) -> float | None:
    """Only pass through a score the detector actually reported.

    LocateAnything returns one when its decoder ran on vLLM (logprobs over
    the emitted box tokens). In plain HF mode there are none, and the old
    code substituted 0.8/0.82 — indistinguishable in the UI from a real
    measurement. None renders as no number at all.
    """
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(1.0, value))

# Generic handwriting-grounding queries fed to LocateAnything so its 2D boxes
# can supply real per-row geometry for tightening over-tall OCR value boxes.
# These are MODEL INPUT WORDS (a small set of generic handwriting phrasings),
# NOT a per-type rule table: measured on real forms, "handwritten number"
# grounds IDs + phone numbers, "handwritten Chinese address text" grounds
# addresses, "handwritten name" grounds names. The wording is tunable — pass a
# custom list to ``ground_handwriting`` to override.
_HANDWRITING_GROUNDING_QUERIES = (
    "handwritten number",
    "handwritten Chinese address text",
    "handwritten name",
)


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


def _normalize_detect_tag(value: object) -> str:
    """Mirror locate_anything_server._normalize_slug byte for byte: /detect
    tags each box with the NORMALIZED requested category, so batched-request
    demultiplexing must apply the same fold. CJK passes through untouched."""
    return str(value or "").strip().lower().replace("-", "_")



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
        # (the LA signature-only pass, the verify re-ground) sends the same
        # wording the main detect sent — the 清单 owns the wording end to end.
        slug_set = set(model_slugs)
        query_by_slug = {rtype: tag for tag, rtype, _text in requests if rtype in slug_set}
        # The checked wording per requested type (preset OR user-custom), carried
        # verbatim for the model-centric verify re-ground — whatever schema the
        # 清单 checked is what gets re-tested, never a slug→name mapping.
        reground_queries = {rtype: tag for tag, rtype, _text in requests}

        # P0 无损重排: the YOLO supplement and the edge-seal margin probe used
        # to run as strictly serial stages AFTER the main gather (each its own
        # barrier). Both depend only on image_data/settings, and the services
        # are stateless, so they are FIRED here and AWAITED at their original
        # positions — the merge order (and therefore the output) is identical,
        # only the wall-clock overlaps. Gates mirror the original branches
        # verbatim; a task is created only when its branch would run.
        has_image_url = str(getattr(settings, "HAS_IMAGE_URL", "") or "").strip()
        has_task = (
            asyncio.create_task(self._detect_has_image(has_image_url, image_data, page, model_slugs))
            if has_image_url and model_slugs
            else None
        )
        # Exception safety on every exit path: if code between here and the
        # consuming await raises, the prefired task would hold a never-retrieved
        # exception. The callback retrieves it immediately on completion, so no
        # orphan noise and no dangling error regardless of how we exit.
        for prefired in (has_task,):
            if prefired is not None:
                prefired.add_done_callback(
                    lambda t: t.exception() if not t.cancelled() else None
                )

        # LA outputs DIRECTLY — one grounding call per category, no tile passes.
        # 公章 goes to PaddleOCR-VL (primary) + YOLO; qr_code/barcode go to the
        # YOLO machine-code detector; fingerprint/signature to their YOLO/DETR
        # detectors. The old zero-recall tile retry probed margin/bottom crops
        # for seals and codes those detectors now cover — measured 0 recall gain
        # across the whole seal corpus at 3-5x the latency, so it is gone.
        async def _detect_one(tag: str) -> list[dict[str, Any]]:
            return await self._post_detect(image_data, [tag])

        model_start = time.perf_counter()
        if bool(getattr(settings, "VISUAL_DETECT_BATCH_CATEGORIES", False)) and len(requests) > 1:
            # vLLM prompt-embeds mode: ONE request carries every category; the
            # server encodes the image once (MoonViT) and runs per-category
            # generations batched. Boxes come back tagged with the NORMALIZED
            # requested category (server-side per-category prompts — not a
            # model echo), demuxed here by the mirrored fold. Any tag that
            # fails to demux is a contract break: fail LOUD per category
            # (empty result), never silently retag.
            demux = {_normalize_detect_tag(tag): index for index, (tag, _r, _t) in enumerate(requests)}
            try:
                batch_raw = await self._post_detect(
                    image_data, [tag for tag, _r, _t in requests]
                )
            except Exception as exc:
                logger.warning("batched visual detect failed, falling back to fan-out: %s", exc)
                batch_raw = None
            if batch_raw is None:
                results = await asyncio.gather(
                    *[_detect_one(tag) for tag, _rtype, _text in requests],
                    return_exceptions=True,
                )
            else:
                per_request: list[list[dict[str, Any]]] = [[] for _ in requests]
                for raw in batch_raw:
                    index = demux.get(_normalize_detect_tag(raw.get("category")))
                    if index is None:
                        logger.warning(
                            "batched detect returned unmappable category %r; box dropped from demux",
                            raw.get("category"),
                        )
                        continue
                    per_request[index].append(raw)
                results = per_request
        else:
            results = await asyncio.gather(
                *[_detect_one(tag) for tag, _rtype, _text in requests],
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
                        confidence=_measured_confidence(raw.get("confidence")),
                        source="visual_features",
                        source_detail="locate_anything:detect",
                        evidence_source="visual_feature_model",
                    )
                )
        if has_task is not None:
            supplement_start = time.perf_counter()
            try:
                yolo_boxes = await has_task
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

        # Model-centric verification: re-ground each grounding box's own checked
        # wording on its tight crop; keep iff the model still finds it, drop the
        # context artifacts (finger→seal, underline→fingerprint, watermark→edge
        # seal). Replaces the whole gate pile. Fails open (keeps) on any error.
        boxes = await self._verify_grounded_candidates(boxes, image_data, reground_queries)
        timings.total = _elapsed_ms(total_start)
        logger.info("LocateAnything fixed visual stage parsed %d boxes", len(boxes))
        return boxes, timings.as_dict()

    async def _verify_grounded_candidates(
        self,
        boxes: list[BoundingBox],
        image_data: bytes,
        reground_queries: dict[str, str],
    ) -> list[BoundingBox]:
        """Model-centric verification of grounding-sourced visual boxes.

        Every look-alike the old pixel gates chased — a page-holding finger read
        as a seal, a red underline read as a fingerprint, a camera/APP watermark
        read as an edge seal — is ONE failure: the grounding model localised its
        target inside a context-rich crop and, obliged to point somewhere, boxed
        the most salient thing. The separator is physical and it is the model's
        own: re-ground the box's OWN claimed type on JUST its tight crop, context
        stripped. A real seal/print/signature still reads as itself (the re-ground
        is idempotent); a finger/underline/watermark had no stamp there at all and
        returns nothing once its borrowed context is gone. This is EXISTENCE, not
        a confidence score — real signatures re-ground at 0.16; a threshold would
        erase them, their existence would not. It generalises to every type with
        zero per-type pixel rules, and it replaces the whole gate pile (skin-hue,
        fill, chroma, ink-snap, cluster-grow) that each covered one look-alike and
        none the rest. Only grounding-sourced boxes pass through here; the YOLO
        detector is a separate trained model, precise on its own. Any decode/HTTP
        failure fails OPEN (keep the box) — a missed redaction outranks a false one.

        Signatures are NOT verified: re-grounding a real handwritten name on its
        own tight crop is unreliable — measured on 保姆, the 甲方/乙方 names return
        n=0 on a tight crop yet n=1 on a slightly wider one, so a real name whose
        detected box is tight WOULD be dropped (a leak). The recovered false
        signatures on blank margins are the price of that safety; they are
        over-mask (redact a blank strip, leak nothing). Signatures pass untouched.

        Fingerprints ARE verified (precision-first policy, 容许找不到但不要高FP):
        the pixel skin gate is gone, so re-grounding each print's own tight crop
        is the model-centric filter that prunes context-artifact false prints
        (a red underline / seal edge the model boxed as 指纹). A real ink print
        re-grounds on its crop; the residual page-holding-finger FP is the one
        the model cannot separate by texture and is left to a dedicated detector.
        """
        grounded = [
            b
            for b in boxes
            if str(b.source_detail or "").startswith("locate_anything:")
            and b.type != "signature"
        ]
        if not grounded:
            return boxes
        try:
            base_img = ImageOps.exif_transpose(Image.open(io.BytesIO(image_data))).convert("RGB")
            width, height = base_img.size
        except Exception:
            logger.warning("verify: image decode failed; keeping all boxes", exc_info=True)
            return boxes

        sem = asyncio.Semaphore(max(1, int(getattr(settings, "VISUAL_VERIFY_CONCURRENCY", 4))))

        async def _keep(b: BoundingBox) -> bool:
            # Context-padded crop, padded by HALF the box each side: scale
            # invariant (a tiny underline and a page seal both get proportional
            # surround), no absolute magic margin.
            pad_x, pad_y = b.width * 0.5, b.height * 0.5
            x0 = int(max(0.0, b.x - pad_x) * width)
            y0 = int(max(0.0, b.y - pad_y) * height)
            x1 = int(min(1.0, b.x + b.width + pad_x) * width)
            y1 = int(min(1.0, b.y + b.height + pad_y) * height)
            if x1 - x0 < 2 or y1 - y0 < 2:
                return True  # degenerate crop carries no evidence; keep (fail open)
            crop = base_img.crop((x0, y0, x1, y1))
            buf = io.BytesIO()
            crop.save(buf, "PNG")
            # Re-ground the box's OWN claimed type with the EXACT wording the
            # 识别清单 checked for it (preset or user-custom), carried verbatim
            # from the detect requests — never a slug→name mapping table. Faithful
            # re-test: the same schema wording that found the box must re-find it,
            # or the box was a context artifact.
            query = reground_queries.get(b.type) or (b.text or b.type)
            async with sem:
                try:
                    raw = await self._post_detect(
                        buf.getvalue(), [query], max_image_side=max(crop.size)
                    )
                except Exception:
                    logger.warning(
                        "verify: re-ground failed for %s; keeping (fail open)", b.type, exc_info=True
                    )
                    return True
            return any(
                (float(r.get("width") or 0) > 0 and float(r.get("height") or 0) > 0)
                for r in raw
            )

        verdicts = await asyncio.gather(*[_keep(b) for b in grounded], return_exceptions=True)
        drop_ids: set[str] = set()
        for b, ok in zip(grounded, verdicts, strict=True):
            if isinstance(ok, BaseException):
                continue  # gather-level failure: fail open, keep the box
            if not ok:
                drop_ids.add(b.id)
        if drop_ids:
            logger.info(
                "verify: dropped %d grounding box(es) the model no longer grounds on their own crop",
                len(drop_ids),
            )
            return [b for b in boxes if b.id not in drop_ids]
        return boxes

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
                    confidence=_measured_confidence(raw.get("confidence")),
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
                    confidence=_measured_confidence(raw.get("confidence")),
                    source="visual_features",
                    source_detail="locate_anything:signature",
                    evidence_source="visual_feature_model",
                )
            )
        return boxes

    async def ground_handwriting(
        self,
        image_data: bytes,
        queries: list[str] | None = None,
        page: int = 1,
    ) -> list[BoundingBox]:
        """Ground handwritten VALUES as real 2D boxes (row geometry only).

        Each query is one single-category ``/detect`` call, run SEQUENTIALLY:
        LocateAnything's recall collapses when categories share a prompt AND is
        load-sensitive (concurrent calls contend on the GPU and silently drop
        boxes), so these are never fanned out. ``queries`` is a small set of
        generic handwriting phrasings (model input words, not per-type rules);
        it defaults to ``_HANDWRITING_GROUNDING_QUERIES``.

        The boxes are tagged ``type="handwriting"`` with EMPTY text — they exist
        only to feed row-accurate y-geometry to
        ``VisionService._adopt_la_vertical_geometry``; they are not redaction
        targets themselves. A failing query is logged and skipped (the others
        still produce boxes); on total miss the caller keeps the original box.
        """
        phrasings = list(queries) if queries is not None else list(_HANDWRITING_GROUNDING_QUERIES)
        boxes: list[BoundingBox] = []
        for query in phrasings:
            try:
                raw_boxes = await self._post_detect(image_data, [query])
            except Exception as exc:
                logger.warning("handwriting grounding query %r failed, skipping: %s", query, exc)
                continue
            for raw in raw_boxes:
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
                        id=f"la_hw_{uuid.uuid4().hex[:8]}",
                        x=x,
                        y=y,
                        width=width,
                        height=height,
                        type="handwriting",
                        text="",
                        page=page,
                        confidence=_measured_confidence(raw.get("confidence")),
                        source="visual_features",
                        source_detail="locate_anything:handwriting_grounding",
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

    async def _post_detect(
        self,
        image_data: bytes,
        categories: list[str] | None,
        max_image_side: int | None = None,
    ) -> list[dict[str, Any]]:
        base_url = model_config_service.get_visual_features_base_url()
        url = f"{base_url}/detect"
        body: dict[str, Any] = {
            "image_base64": base64.b64encode(image_data).decode("utf-8"),
            "conf": settings.VISUAL_FEATURES_CONF,
        }
        if categories is not None:
            body["categories"] = categories
        # Native-resolution tiles pass their own size so the server does NOT
        # upscale them to its 1280 default: a small crop blown up to 1280x1280
        # OOMs the shared vision encoder (503), and the stamp gains no salience
        # from the upscale because it already fills the crop.
        if max_image_side is not None:
            body["max_image_side"] = int(max_image_side)

        async def request() -> httpx.Response:
            async with httpx.AsyncClient(timeout=settings.VISUAL_FEATURES_TIMEOUT, trust_env=False) as client:
                response = await client.post(url, json=body)
                if response.status_code in _TRANSIENT_DETECT_STATUSES:
                    # Transient LB/overload — raise a retryable error (not a 4xx
                    # client error) so retry_async backs off and re-sends instead
                    # of dropping this call (a dropped tile = a missed redaction).
                    raise ConnectionError(f"LA transient HTTP {response.status_code}")
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
                    confidence=_measured_confidence(obj.get("confidence")),
                    source="visual_features",
                    source_detail=f"locate_anything:{obj.get('rule_matched') or 'checklist'}",
                    evidence_source="visual_feature_model",
                )
            )
        return boxes

