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
from app.services.vision.la_consensus import consensus_boxes
from app.services.vision.locate_tiles import (
    _TILE_RETRY_BOTTOM_SLUGS,
    _TILE_RETRY_GRID_SLUGS,
    _TILE_RETRY_MARGIN_SLUGS,
    _axis_positions,  # noqa: F401  # re-exported for API stability
    _bottom_tiles,
    _fragment_seal_tiles,
    _grid_tiles,
    _ink_centered_tiles,
    _margin_tiles,
)
from app.services.vision.machine_code_detector import (
    BARCODE_SLUG,
    QR_CODE_SLUG,
    detect_machine_code_regions,
)
from app.services.vision.seal_color_cascade import (
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
        # (tile retry, edge refine, signature) sends the same wording the main
        # detect sent — the 清单 owns the wording end to end.
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
        # Fragment (骑缝) seal recovery: square, native-resolution tiles along
        # all four margins. Recovers partial binding-seal arcs the full frame
        # loses to downscaling — including on a greyscale/B&W scan, where there
        # is no red ink to fall back on and the ONLY signal is the stamp's shape,
        # which the model reads once the crop is native-res and square (measured
        # on the xinchuang binding-seal pages, colour AND greyscale). Always on
        # when a seal is requested — a binding seal is missed at full frame
        # whether or not other seals were found, so it cannot be gated on a
        # zero-recall miss like the ordinary tile retry. The native-res crop is
        # grounded with the SAME checked wording as everything else — 公章 by
        # default (Chinese localises the stamp on a small crop where the old
        # English "seal" returned 0; that English→中文 swap is gone now that the
        # default query is Chinese).
        fragment_queries = dict(query_by_slug)
        fragment_on = (
            bool(getattr(settings, "VISUAL_FRAGMENT_SEAL", True))
            and model_slugs
            and "official_seal" in model_slugs
        )
        # Coloured-ink evidence, computed once: it PLACES tiles (a tile centred
        # on the ink reads the stamp far more reliably than a blind grid tile it
        # sits off-centre in) and, in the merge below, GATES them (a fragment box
        # with no colour is edge text). A B&W scan yields none — the blind grid
        # then stands on its own.
        fragment_components: list[tuple[float, float, float, float]] = []
        if fragment_on:
            try:
                fragment_components = raw_colored_component_bboxes(image_data)
            except Exception:
                fragment_components = []
        fragment_task = (
            asyncio.create_task(self._detect_on_tiles(
                image_data,
                page,
                ["official_seal"],
                tiles_for=lambda _slug, w, h: _fragment_seal_tiles(w, h)
                + _ink_centered_tiles(w, h, fragment_components),
                source_detail="locate_anything:fragment_seal",
                queries=fragment_queries,
                native_resolution=True,
                max_concurrency=int(getattr(settings, "VISUAL_FRAGMENT_SEAL_CONCURRENCY", 4)),
            ))
            if fragment_on
            else None
        )
        # Exception safety on every exit path: if code between here and the
        # consuming await raises, the prefired task would hold a never-retrieved
        # exception. The callback retrieves it immediately on completion, so no
        # orphan noise and no dangling error regardless of how we exit.
        for prefired in (has_task, fragment_task):
            if prefired is not None:
                prefired.add_done_callback(
                    lambda t: t.exception() if not t.cancelled() else None
                )

        # P1 speculative tile fire: a tile-retriable slug whose OWN main
        # detect came back empty starts its tile pass immediately (the
        # earliest possible signal) instead of waiting for the strictly
        # serial retry stage — 11-17 tiles over 2 GPU slots used to run as a
        # tail. The DECISION to keep tile boxes is unchanged: the retry
        # section below still recomputes retry_slugs against the FINAL merged
        # boxes and awaits (or discards) these tasks — output is identical,
        # only the wall-clock overlaps. Gated on the same VISUAL_TILE_RETRY
        # flag as the consumer (kill switch works in both places).
        tile_retry_enabled = bool(getattr(settings, "VISUAL_TILE_RETRY", True))
        _retriable = _TILE_RETRY_MARGIN_SLUGS | _TILE_RETRY_BOTTOM_SLUGS | _TILE_RETRY_GRID_SLUGS
        spec_tile_tasks: dict[str, asyncio.Task] = {}

        async def _detect_one(tag: str, rtype: str) -> list[dict[str, Any]]:
            res = await self._post_detect(image_data, [tag])
            if tile_retry_enabled and rtype in _retriable and rtype not in spec_tile_tasks:
                spec_task = asyncio.create_task(
                    self._detect_on_tiles(image_data, page, [rtype], queries=query_by_slug)
                )
                spec_task.add_done_callback(
                    lambda t: t.exception() if not t.cancelled() else None
                )
                spec_tile_tasks[rtype] = spec_task
            return res

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
                    *[_detect_one(tag, rtype) for tag, rtype, _text in requests],
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
                # speculative tiles for empty retriable slugs (same as _detect_one)
                for _tag, rtype, _t in requests:
                    if tile_retry_enabled and rtype in _retriable and rtype not in spec_tile_tasks:
                        spec_task = asyncio.create_task(
                            self._detect_on_tiles(image_data, page, [rtype], queries=query_by_slug)
                        )
                        spec_task.add_done_callback(
                            lambda t: t.exception() if not t.cancelled() else None
                        )
                        spec_tile_tasks[rtype] = spec_task
        else:
            results = await asyncio.gather(
                *[_detect_one(tag, rtype) for tag, rtype, _text in requests],
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


        # Tile pass runs for EVERY requested retriable slug, not only 0-box
        # ones: the old miss-rescue gate lost partial-recall pages — 立案告知书
        # 实证: full-frame found 1 of 3 signatures, so the gate skipped tiles
        # even though the grid tiles find all 3. A page carries no prior on
        # its instance count; the only non-magic dedup is geometric — a tile
        # box overlapping a same-type full-frame box is the zoom re-stating
        # the page-scale call (dropped by _filter_tile_candidates), a
        # non-overlapping one is a NEW instance the full frame missed.
        retry_slugs = [
            slug
            for slug in (model_slugs or [])
            if slug in _TILE_RETRY_MARGIN_SLUGS | _TILE_RETRY_BOTTOM_SLUGS | _TILE_RETRY_GRID_SLUGS
        ]
        if retry_slugs and not tile_retry_enabled:
            # Kill switch: the flag gates BOTH the speculative fire above and
            # this consumer — with it off, zero tile passes run anywhere.
            retry_slugs = []
        if retry_slugs:
            retry_start = time.perf_counter()
            tile_boxes = []
            live_slugs = []
            for slug in retry_slugs:
                spec = spec_tile_tasks.get(slug)
                if spec is not None:
                    try:
                        tile_boxes.extend(await spec)
                    except Exception as exc:
                        logger.warning("speculative tile retry %s failed: %s", slug, exc)
                else:
                    live_slugs.append(slug)
            if live_slugs:
                # a slug whose main detect had raw boxes that all got dropped
                # later (clamp/physical gates) never fired a spec — run it now
                tile_boxes.extend(
                    await self._detect_on_tiles(image_data, page, live_slugs, queries=query_by_slug)
                )
            # Grid-retry marks (signature/fingerprint) recover STOCHASTICALLY — one
            # sample of the tiles finds 陈勇, the next 周X, rarely both in the same
            # pass. A missed real signature is a LEAK, so when the first pass proves
            # the page HAS such a mark, union a few more samples: any mark ANY sample
            # sees survives (consensus_boxes min_votes=1 = union). Gated on the first
            # hit so the common signature-free page pays nothing extra. More over-mask
            # false marks on the same tiles is the price of stable recall.
            grid_retry = [s for s in retry_slugs if s in _TILE_RETRY_GRID_SLUGS]
            samples = max(1, int(getattr(settings, "VISUAL_GRID_RETRY_SAMPLES", 1)))
            grid_hits = [b for b in tile_boxes if b.type in grid_retry]
            if grid_retry and samples > 1 and grid_hits:
                extra = await asyncio.gather(
                    *[
                        self._detect_on_tiles(image_data, page, grid_retry, queries=query_by_slug)
                        for _ in range(samples - 1)
                    ],
                    return_exceptions=True,
                )
                runs = [grid_hits] + [r for r in extra if not isinstance(r, BaseException)]
                non_grid = [b for b in tile_boxes if b.type not in grid_retry]
                tile_boxes = non_grid + consensus_boxes(
                    runs,
                    min_votes=1,
                    iou_thresh=float(getattr(settings, "LOCATE_ANYTHING_CONSENSUS_IOU", 0.5)),
                )
            tile_boxes = self._filter_tile_candidates(tile_boxes, boxes)
            tile_boxes = self._verify_machine_code_tile_boxes(tile_boxes, image_data)
            boxes.extend(tile_boxes)
            logger.info(
                "LocateAnything tile retry for %s kept %d box(es) in %dms",
                retry_slugs,
                len(tile_boxes),
                _elapsed_ms(retry_start),
            )

        leftover_specs = [
            t for slug, t in spec_tile_tasks.items() if slug not in retry_slugs
        ]
        if leftover_specs:
            # A supplement (YOLO/refine/cascade) filled these types after the
            # spec fired: await the tasks to completion and DISCARD the boxes
            # — exactly today's semantics (tile boxes never join when the type
            # already has one). Never cancel: the HTTP is in flight and the
            # done-callback already consumes any exception.
            await asyncio.gather(*leftover_specs, return_exceptions=True)

        if fragment_task is not None:
            try:
                fragment_boxes = await fragment_task
            except Exception as exc:
                logger.warning("fragment seal recovery failed: %s", exc)
                fragment_boxes = []
            # A margin QR/barcode the model read as a seal is already covered by
            # its own detection — drop a fragment seal box overlapping a machine
            # code (same cross-detector arbitration as the edge refine). The rest
            # are recovered binding-seal arcs; downstream dedup (_deduplicate_boxes,
            # _prefer_vl_seals) folds each into an overlapping full-frame/YOLO seal
            # or keeps it as a seal the full frame missed entirely.
            code_boxes = [b for b in boxes if b.type in ("qr_code", "barcode")]

            def _hits_code(fb: BoundingBox) -> bool:
                return any(
                    fb.x < c.x + c.width and c.x < fb.x + fb.width
                    and fb.y < c.y + c.height and c.y < fb.y + fb.height
                    for c in code_boxes
                )

            # Same gap-fill arbitration as the ordinary tile retry: a fragment
            # box intersecting an already-found box of the SAME type is the zoom
            # re-describing a seal the full frame already has (drop); one at a
            # new position is a binding seal the full frame missed (keep).
            # Precision is no longer a per-source pixel gate here. The fragment
            # pass stays a broad RECALL net (a native-res crop reads a binding
            # arc a full frame loses); every fragment box — like every other
            # grounding box — is proven or dropped by the single model-centric
            # re-ground below. Chroma gate, cluster-grow and skin/fill gates are
            # gone: they each covered one look-alike and none the rest.
            kept = self._filter_tile_candidates(
                [fb for fb in fragment_boxes if not _hits_code(fb)], boxes
            )
            boxes.extend(kept)
            if kept:
                logger.info("fragment seal recovery added %d box(es)", len(kept))

        # Model-centric verification: re-ground each grounding box's own checked
        # wording on its tight crop; keep iff the model still finds it, drop the
        # context artifacts (finger→seal, underline→fingerprint, watermark→edge
        # seal). Replaces the whole gate pile. Fails open (keeps) on any error.
        boxes = await self._verify_grounded_candidates(boxes, image_data, reground_queries)
        timings.total = _elapsed_ms(total_start)
        logger.info("LocateAnything fixed visual stage parsed %d boxes", len(boxes))
        return boxes, timings.as_dict()

    @staticmethod
    def _filter_tile_candidates(
        tile_boxes: list[BoundingBox],
        existing: list[BoundingBox],
    ) -> list[BoundingBox]:
        """Gap-filling only, scoped to the SAME type: a tile hit touching a
        full-frame box of the same type is the zoom second-guessing the
        page-scale call - discard it. A tile hit overlapping a box of a
        DIFFERENT type is a different entity sharing pixels (a thumbprint
        pressed onto a handwritten name, 0710 农业合同实证) and must be kept;
        type equality is a string identity, so custom types participate with
        no enumeration.
        """
        return [
            t
            for t in tile_boxes
            if not any(
                b.type == t.type
                and t.x < b.x + b.width
                and b.x < t.x + t.width
                and t.y < b.y + b.height
                and b.y < t.y + t.height
                for b in existing
            )
        ]

    async def _verify_grounded_candidates(
        self,
        boxes: list[BoundingBox],
        image_data: bytes,
        reground_queries: dict[str, str],
    ) -> list[BoundingBox]:
        """Model-centric verification of grounding-sourced visual boxes.

        Every look-alike the old pixel gates chased — a page-holding finger read
        as a seal, a red underline read as a fingerprint, a camera/APP watermark
        read as an edge seal — is ONE failure: a tile/grid/fragment pass forced
        the grounding model to localise its target inside a context-rich margin
        crop, and the model, obliged to point somewhere, boxed the most salient
        thing. The separator is physical and it is the model's own: re-ground the
        box's OWN claimed type on JUST its tight crop, context stripped. A real
        seal/print/signature still reads as itself (the fragment pass FOUND it on
        a crop this size, so the re-ground is idempotent); a finger/underline/
        watermark had no stamp there at all and returns nothing once its borrowed
        tile context is gone. This is EXISTENCE, not a confidence score — real
        signatures re-ground at 0.16; a threshold would erase them, their
        existence would not. It generalises to every type with zero per-type
        pixel rules, and it replaces the whole gate pile (skin-hue, fill, chroma,
        ink-snap, cluster-grow) that each covered one look-alike and none the
        rest. Only grounding-sourced boxes pass through here; the YOLO detector is
        a separate trained model, precise on its own. Any decode/HTTP failure fails
        OPEN (keep the box) — a missed redaction outranks a false one.

        Signatures are NOT verified: re-grounding a real handwritten name on its
        own tight crop is unreliable — measured on 保姆, the 甲方/乙方 names return
        n=0 on a tight crop yet n=1 on a slightly wider one, so a real name whose
        detected box is tight WOULD be dropped (a leak). The recovered false
        signatures on blank margins are the price of that safety; they are
        over-mask (redact a blank strip, leak nothing). Signatures pass untouched.

        Fingerprints ARE verified (precision-first policy, 容许找不到但不要高FP):
        the pixel skin gate is gone, so re-grounding each print's own tight crop
        is the model-centric filter that prunes context-artifact false prints
        (a red underline / seal edge the grid boxed as 指纹). A real ink print
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

    def _verify_machine_code_tile_boxes(
        self,
        tile_boxes: list[BoundingBox],
        image_data: bytes,
    ) -> list[BoundingBox]:
        """Machine-code existence identity for tile-retry candidates.

        A QR code / barcode IS machine-decodable by definition. A tile crop
        loses page context and makes the grounding model hallucinate codes out
        of watermark logos and film texture (0712 医院CT报告单: a bottom tile
        returned the NetEase watermark logo as qr_code, and another returned
        itself as one giant code). So a tile-retry candidate of a machine-code
        type is kept only where the deterministic decoder proves a code exists:
        it must intersect a decoded region (payload decoded = existence
        proven, box exact). An undecodable "code" carries no extractable
        payload, so dropping it cannot leak information — the failure
        direction is safe by the definition of the object itself. Non-code
        types pass through untouched; the full-frame detect and the YOLO
        supplement are not gated (this identity check covers only the
        context-starved tile path). Decoder breakage fails OPEN (keep the
        candidates): over-mask, never silently un-cover.
        """
        code_types = {QR_CODE_SLUG, BARCODE_SLUG}
        if not any(t.type in code_types for t in tile_boxes):
            return tile_boxes
        try:
            with Image.open(io.BytesIO(image_data)) as img:
                decoded = detect_machine_code_regions(img)
        except Exception:
            logger.warning(
                "machine-code identity check unavailable; keeping tile candidates",
                exc_info=True,
            )
            return tile_boxes
        kept: list[BoundingBox] = []
        dropped = 0
        for t in tile_boxes:
            if t.type in code_types and not any(
                t.x < r.x + r.width
                and r.x < t.x + t.width
                and t.y < r.y + r.height
                and r.y < t.y + t.height
                for r in decoded
            ):
                dropped += 1
                continue
            kept.append(t)
        if dropped:
            logger.info(
                "Machine-code identity dropped %d tile-retry candidate(s) with no decodable code",
                dropped,
            )
        return kept

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


    async def _detect_on_tiles(
        self,
        image_data: bytes,
        page: int,
        slugs: list[str],
        tiles_for=None,
        source_detail: str = "locate_anything:tile_retry",
        queries: dict[str, str] | None = None,
        native_resolution: bool = False,
        max_concurrency: int | None = None,
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
                side = max(x1 - x0, y1 - y0) if native_resolution else None
                tasks.append(self._post_detect(encoded.getvalue(), [(queries or {}).get(slug, slug)], side))
                metas.append((slug, x0, y0, x1 - x0, y1 - y0))
        # The fragment pass fires ~20 tiles; firing them all at once spikes the
        # shared LA card's vision-encode buffers into CUDA-capacity 503s (every
        # tile then fails and the pass returns nothing). Bound the in-flight
        # count so the two cards drain the queue steadily — a resource limit, not
        # a detection knob.
        if max_concurrency is None:
            # Default bound so a tile burst never floods the shared LA card. A grid
            # union (fingerprint = 2 phrases × 4 tiles) or a fragment sweep (~20
            # tiles) fired all at once spikes the decoder queue into 503s; letting
            # the two GPUs drain a bounded queue keeps every tile call served.
            max_concurrency = int(getattr(settings, "VISUAL_TILE_CONCURRENCY", 4))
        if max_concurrency and max_concurrency > 0:
            sem = asyncio.Semaphore(max_concurrency)

            async def _bounded(coro):
                async with sem:
                    return await coro

            tasks = [_bounded(t) for t in tasks]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        boxes: list[BoundingBox] = []
        for (slug, x0, y0, tile_w, tile_h), result in zip(metas, results, strict=False):
            if isinstance(result, BaseException):
                logger.warning("tile retry %s failed on one tile: %s", slug, result)
                continue
            for raw in result:
                # Tag-by-request, no echo filtering: this tile carried exactly
                # ONE query (the checklist wording for `slug`), so every box in
                # the response belongs to that slug by construction. The old
                # echo check compared the server-normalized QUERY WORDING with
                # the slug — a tautology while query==slug, but the moment the
                # checklist wording diverged ("handwritten name signature" for
                # signature, "red inked thumbprint mark" for fingerprint) it
                # silently swallowed EVERY tile box of those types (contract 19
                # 实证: both grid tiles hit a signature each, pipeline kept 0;
                # the historical "fingerprint,qr_code kept 0/6" waste was this
                # bug, not model misses).
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
                # A box touching all four tile edges is LocateAnything failing to
                # localise inside the crop: it saw "seal-like stuff" and returned
                # the whole tile (a text-only margin crop comes back exactly this
                # way). A real stamp is interior. One tile pixel is the tolerance
                # — a physical unit, not a tuned score. Only the native-resolution
                # fragment pass produces (and must reject) these.
                if native_resolution:
                    ex, ey = 1.0 / max(1, tile_w), 1.0 / max(1, tile_h)
                    if (
                        tile_x <= ex and tile_y <= ey
                        and tile_x + tile_box_w >= 1.0 - ex
                        and tile_y + tile_box_h >= 1.0 - ey
                    ):
                        continue
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
                        confidence=_measured_confidence(raw.get("confidence")),
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

