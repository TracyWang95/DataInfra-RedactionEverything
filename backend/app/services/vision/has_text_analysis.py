"""HaS NER text analysis over OCR blocks.

Split out of ocr_pipeline.py (which stays the public facade): whole-document
HaS NER with cache/in-flight dedupe, the reconstructed-line bridge pass and
the structural table-amount / form-field recall merges.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from app.core.config import settings
from app.services.ocr_has_vision_service import OCRTextBlock
from app.services.vision.has_text_payload import (
    _build_has_text_payload,
    _build_has_text_type_names,
    _canonical_image_text_type,
    _compact_text,
    _default_has_text_items,
    _filter_blocks_for_has_text,
    _item_query_labels,
)
from app.services.vision.ocr_cache import (
    _add_has_text_duration,
    _begin_has_text_ner_inflight,
    _finish_has_text_ner_inflight,
    _get_cached_has_text_ner,
    _has_recent_negative_health,
    _has_text_ner_inflight_key,
    _record_has_text_metric,
)
from app.services.vision.ocr_tuning import (
    _BRIDGE_PAYLOAD_MAX_CHARS,
    _NER_DEFAULT_MIN_LEN,
    _NER_MIN_LEN_BY_TYPE,
)
from app.services.vision.ocr_visual_lines import reconstruct_visual_line_blocks

logger = logging.getLogger(__name__)


# NER runs on the whole document, not per-line chunks: feeding the 0.6B model a
# context-free single cell (a lone "汉族") makes it force-fit that value into the
# nearest requested type when its true type isn't in the schema (民族 absent ->
# "汉族" lands under 性别). With the full page it has the context to assign 男->性别
# and leave 汉族 out — 找到就找到，找不到就没有。Tradeoff: the model dilutes recall on a
# long page and may drop an entity near the very end (e.g. a standalone signature
# date). Reordering/chunking to recover it reintroduces the force-fit, because this
# model classifies sequentially — order and recall are coupled. Dates were once
# force-recalled by a 年月日 regex backstop (both digit systems); a 5/5 reliability
# probe — including the CJK-digit "一九五八年九月十日" the backstop was written for —
# showed HaS now returns every date deterministically, so the regex was deleted.
# The model judges what is a date; no hand-written pattern enumerates them.


async def _narrow_amount_entities(entities: list[dict[str, str]], has_client: Any) -> None:
    """Model-driven AMOUNT value narrowing（人民币每亩每年100元 → 100元）.

    The sensitive ink on the page is the value token, but HaS queried as 金额
    returns the span WITH its business context — that is its training
    semantics, not an error. Queried as 数值 (settings.AMOUNT_VALUE_QUERY_LABEL)
    on the entity text alone, the same model extracts the value itself, so the
    narrowing is the model's own judgment end to end — no token grammar, no
    word lists. Fires only on an unambiguous answer: exactly ONE value that is
    a proper substring of the entity. Anything else — multi-value spans, no
    answer, a model failure — keeps the whole span, so narrowing can only ever
    trim label context, never uncover a value.
    """
    label = str(getattr(settings, "AMOUNT_VALUE_QUERY_LABEL", "") or "").strip()
    if not label or not has_client:
        return
    for entity in entities:
        if entity.get("type") != "AMOUNT":
            continue
        original = str(entity.get("text") or "")
        if not original:
            continue
        try:
            result = await asyncio.to_thread(has_client.ner, original, [label])
        except Exception as exc:
            logger.debug("amount value narrowing skipped for %r: %s", original, exc)
            continue
        values = [str(v).strip() for v in (result or {}).get(label, []) if str(v).strip()]
        if len(values) == 1 and values[0] != original and values[0] in original:
            logger.debug("amount narrowed by model: %r -> %r", original, values[0])
            entity["text"] = values[0]


async def run_has_text_analysis(
    ocr_blocks: list[OCRTextBlock],
    has_client: Any,
    vision_types: list | None = None,
    stage_status: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    """
    Analyse OCR text with HaS local NER model to identify sensitive entities.
    Fully offline - no cloud API dependency.

    Args:
        ocr_blocks: OCR text blocks.
        has_client: HaSClient instance (may be None).
        vision_types: User-enabled vision type configs.

    Returns:
        [{type: "PERSON", text: "张三"}, ...]
    """
    total_start = time.perf_counter()
    _record_has_text_metric(stage_status, "has_text_cache_status", "not_started")
    _record_has_text_metric(stage_status, "has_text_slot_wait_ms", 0)
    _record_has_text_metric(stage_status, "has_text_duplicate_wait_ms", 0)
    _record_has_text_metric(stage_status, "has_text_model_ms", 0)

    if not ocr_blocks:
        _record_has_text_metric(stage_status, "has_text_cache_status", "skipped_empty_ocr")
        _record_has_text_metric(
            stage_status,
            "has_text_total_ms",
            round((time.perf_counter() - total_start) * 1000),
        )
        return []


    # Lazy re-init if client was not available at startup
    if not has_client:
        try:
            from app.services.has_client import HaSClient
            has_client = HaSClient()
        except Exception as e:
            logger.error("HaS Client init failed: %s", e)
            _record_has_text_metric(stage_status, "has_text_cache_status", "skipped_no_client")
            _record_has_text_metric(
                stage_status,
                "has_text_total_ms",
                round((time.perf_counter() - total_start) * 1000),
            )
            return []

    if _has_recent_negative_health(has_client):
        logger.warning("HaS service recently reported unavailable, skipping NER")
        _record_has_text_metric(stage_status, "has_text_cache_status", "skipped_recent_unavailable")
        _record_has_text_metric(
            stage_status,
            "has_text_total_ms",
            round((time.perf_counter() - total_start) * 1000),
        )
        return []

    try:
        prepare_start = time.perf_counter()
        selected_type_ids = [_canonical_image_text_type(getattr(vt, "id", "")) for vt in (vision_types or [])]
        candidate_blocks = _filter_blocks_for_has_text(ocr_blocks, selected_type_ids)
        _record_has_text_metric(stage_status, "has_text_reconstructed_lines", 0)
        has_payload = _build_has_text_payload(
            candidate_blocks,
            max_chars=settings.HAS_VISION_MAX_TEXT_CHARS,
            max_block_chars=settings.HAS_VISION_MAX_BLOCK_CHARS,
        )
        text_content = has_payload.content
        _add_has_text_duration(
            stage_status,
            "has_text_prepare_ms",
            round((time.perf_counter() - prepare_start) * 1000),
        )
        _record_has_text_metric(stage_status, "has_text_source_blocks", has_payload.source_block_count)
        _record_has_text_metric(stage_status, "has_text_eligible_blocks", has_payload.eligible_block_count)
        _record_has_text_metric(stage_status, "has_text_unique_blocks", len(has_payload.texts))
        _record_has_text_metric(stage_status, "has_text_duplicate_blocks", has_payload.duplicate_block_count)
        _record_has_text_metric(stage_status, "has_text_clipped_blocks", has_payload.clipped_block_count)
        _record_has_text_metric(stage_status, "has_text_input_chars", has_payload.input_chars)
        _record_has_text_metric(stage_status, "has_text_emitted_chars", has_payload.emitted_chars)
        _record_has_text_metric(stage_status, "has_text_omitted_chars", has_payload.omitted_chars)
        _record_has_text_metric(stage_status, "has_text_truncated", has_payload.truncated)

        if not text_content.strip():
            logger.info(
                "HaS skipped; no eligible OCR text blocks (source=%d, eligible=%d, duplicates=%d)",
                has_payload.source_block_count,
                has_payload.eligible_block_count,
                has_payload.duplicate_block_count,
            )
            _record_has_text_metric(stage_status, "has_text_cache_status", "skipped_no_eligible_text")
            _record_has_text_metric(
                stage_status,
                "has_text_total_ms",
                round((time.perf_counter() - total_start) * 1000),
            )
            return []

        min_text_chars = int(settings.HAS_VISION_MIN_TEXT_CHARS_FOR_NER)
        compact_chars = len(_compact_text(text_content))
        _record_has_text_metric(stage_status, "has_text_compact_chars", compact_chars)
        if compact_chars < min_text_chars:
            logger.info(
                "HaS skipped; compact OCR text chars=%d below min=%d (eligible=%d)",
                compact_chars,
                min_text_chars,
                has_payload.eligible_block_count,
            )
            _record_has_text_metric(stage_status, "has_text_cache_status", "skipped_too_short")
            _record_has_text_metric(
                stage_status,
                "has_text_total_ms",
                round((time.perf_counter() - total_start) * 1000),
            )
            return []

        logger.info(
            (
                "HaS analyzing unique_blocks=%d/%d, source_blocks=%d, "
                "input_chars=%d, emitted_chars=%d, duplicate_blocks=%d, "
                "clipped_blocks=%d, omitted_chars=%d, type_configs=%d, truncated=%s"
            ),
            len(has_payload.texts),
            has_payload.eligible_block_count,
            has_payload.source_block_count,
            has_payload.input_chars,
            has_payload.emitted_chars,
            has_payload.duplicate_block_count,
            has_payload.clipped_block_count,
            has_payload.omitted_chars,
            len(vision_types or []),
            has_payload.truncated,
        )

        # ----- type ID <-> Chinese name mappings -----

        if vision_types:
            chinese_types = _build_has_text_type_names(vision_types)
            if not chinese_types:
                logger.info("HaS skipped; selected OCR types are visual-only")
                _record_has_text_metric(stage_status, "has_text_cache_status", "skipped_visual_only_types")
                _record_has_text_metric(
                    stage_status,
                    "has_text_total_ms",
                    round((time.perf_counter() - total_start) * 1000),
                )
                return []
            logger.info("HaS using types for NER: %s", chinese_types)
        else:
            chinese_types = _build_has_text_type_names()
            logger.info("HaS using default types: %s", chinese_types)
        _record_has_text_metric(stage_status, "has_text_type_count", len(chinese_types))

        ner_result = _get_cached_has_text_ner(has_client, text_content, chinese_types)
        if ner_result is not None:
            _record_has_text_metric(stage_status, "has_text_cache_status", "hit_before_slot")
            logger.info("HaS NER cache hit before local slot wait")
        else:
            _record_has_text_metric(stage_status, "has_text_cache_status", "miss")
            inflight_key = _has_text_ner_inflight_key(has_client, text_content, chinese_types)
            owns_inflight, inflight_future = _begin_has_text_ner_inflight(inflight_key)
            if not owns_inflight:
                duplicate_wait_start = time.perf_counter()
                ner_result = await asyncio.shield(inflight_future)
                wait_ms = round((time.perf_counter() - duplicate_wait_start) * 1000)
                _record_has_text_metric(stage_status, "has_text_cache_status", "shared_inflight")
                _add_has_text_duration(stage_status, "has_text_duplicate_wait_ms", wait_ms)
                logger.info("HaS NER duplicate waited %dms without local slot", wait_ms)
            else:
                try:
                    # HaS httpx is synchronous - offload to a worker thread. Concurrency
                    # is bounded by the shared GPU inference gate (HAS_NER_GLOBAL_MAX_INFLIGHT,
                    # 1 = fully serialized); identical page payloads were already merged by
                    # the inflight registry above, so raising the gate never duplicates work.
                    from app.core.gpu_inference_gate import shared_gpu_inference_slot

                    queue_start = time.perf_counter()
                    async with shared_gpu_inference_slot("OCR HaS Text NER"):
                        queue_ms = round((time.perf_counter() - queue_start) * 1000)
                        _add_has_text_duration(stage_status, "has_text_slot_wait_ms", queue_ms)
                        if queue_ms > 0:
                            logger.info("HaS Text waited %dms for shared NER slot", queue_ms)
                        ner_result = _get_cached_has_text_ner(has_client, text_content, chinese_types)
                        if ner_result is not None:
                            _record_has_text_metric(stage_status, "has_text_cache_status", "hit_after_slot")
                            logger.info("HaS NER cache hit after slot wait")
                        else:
                            model_start = time.perf_counter()
                            ner_result = await asyncio.to_thread(
                                has_client.ner, text_content, chinese_types
                            )
                            _record_has_text_metric(stage_status, "has_text_cache_status", "model_call")
                            _add_has_text_duration(
                                stage_status,
                                "has_text_model_ms",
                                round((time.perf_counter() - model_start) * 1000),
                            )
                    _finish_has_text_ner_inflight(inflight_key, inflight_future, ner_result)
                except Exception:
                    _finish_has_text_ner_inflight(inflight_key, inflight_future, None)
                    raise

        if not ner_result or not isinstance(ner_result, dict):
            logger.info("HaS: no entities found by NER")
            _record_has_text_metric(stage_status, "has_text_entity_count", 0)
            _record_has_text_metric(
                stage_status,
                "has_text_total_ms",
                round((time.perf_counter() - total_start) * 1000),
            )
            return []

        logger.info("HaS NER result: %s", ner_result)

        # ----- reverse mapping: Chinese -> type ID -----
        # Every label the prompt asked for on an item's behalf maps back to
        # that item (the request's own labels are the same source the prompt was
        # built from, so query and answer stay symmetric — 大写金额 -> AMOUNT).
        if vision_types:
            # Tag-by-request (same principle as the LA chain): every result
            # bucket key is a label WE sent for a checked item, so the map is
            # built purely from the request — item name, item id, and the
            # item's own query labels. No registry lookups: the checklist owns
            # the vocabulary end to end.
            chinese_to_id = {}
            for vt in vision_types:
                normalized_id = _canonical_image_text_type(vt.id)
                if not normalized_id:
                    continue
                chinese_to_id[vt.name] = normalized_id
                chinese_to_id[normalized_id] = normalized_id
                for query_label in _item_query_labels(vt):
                    chinese_to_id[query_label] = normalized_id
        else:
            chinese_to_id = {}
            for item in _default_has_text_items():
                normalized_id = _canonical_image_text_type(item.id)
                if not normalized_id:
                    continue
                chinese_to_id[item.name] = normalized_id
                chinese_to_id[normalized_id] = normalized_id
                for query_label in _item_query_labels(item):
                    chinese_to_id[query_label] = normalized_id

        bridge_ner_result: dict[str, list[str]] = {}
        bridge_blocks = reconstruct_visual_line_blocks(candidate_blocks)
        _record_has_text_metric(stage_status, "has_text_reconstructed_lines", len(bridge_blocks))
        if bridge_blocks:
            bridge_payload = _build_has_text_payload(
                bridge_blocks,
                max_chars=min(settings.HAS_VISION_MAX_TEXT_CHARS, _BRIDGE_PAYLOAD_MAX_CHARS),
                max_block_chars=settings.HAS_VISION_MAX_BLOCK_CHARS,
            )
            bridge_text = bridge_payload.content
            if bridge_text.strip():
                cached_bridge = _get_cached_has_text_ner(has_client, bridge_text, chinese_types)
                if cached_bridge is not None:
                    bridge_ner_result = cached_bridge
                else:
                    from app.core.gpu_inference_gate import shared_gpu_inference_slot

                    async with shared_gpu_inference_slot("OCR HaS Text bridge NER"):
                        cached_bridge = _get_cached_has_text_ner(has_client, bridge_text, chinese_types)
                        if cached_bridge is not None:
                            bridge_ner_result = cached_bridge
                        else:
                            model_start = time.perf_counter()
                            result = await asyncio.to_thread(has_client.ner, bridge_text, chinese_types)
                            _add_has_text_duration(
                                stage_status,
                                "has_text_model_ms",
                                round((time.perf_counter() - model_start) * 1000),
                            )
                            bridge_ner_result = result if isinstance(result, dict) else {}

        entities = []
        min_len_by_type = _NER_MIN_LEN_BY_TYPE

        merged_ner_result = dict(ner_result)
        for entity_type, entity_list in bridge_ner_result.items():
            if not entity_list:
                continue
            merged_ner_result.setdefault(entity_type, [])
            for text in entity_list:
                clean_text = _compact_text(text)
                if clean_text and clean_text not in merged_ner_result[entity_type]:
                    merged_ner_result[entity_type].append(clean_text)

        for entity_type, entity_list in merged_ner_result.items():
            if not entity_list:
                continue

            # Open vocabulary: the type IS what the model returned. If it matches a
            # label we sent for a schema item, use that item's id; otherwise keep the
            # raw model label (识别出来是啥就是啥) — never drop, never reconcile.
            normalized_type = chinese_to_id.get(entity_type, entity_type)
            min_len = min_len_by_type.get(normalized_type, _NER_DEFAULT_MIN_LEN)

            for entity_text in entity_list:
                text = entity_text.strip() if entity_text else ""
                if normalized_type in {"COMPANY_NAME", "BANK_NAME", "BANK_ACCOUNT", "AMOUNT"}:
                    text = _compact_text(text)
                if not text:
                    continue
                if len(text) < min_len:
                    # Below-min-length values (e.g. 性别 男) are kept: the
                    # matcher attaches them only by block equality or isolated
                    # token (_is_strict_match_entity), never bare containment.
                    logger.debug("HaS kept short value for strict matching: '%s' (%s)", text, normalized_type)

                entities.append({
                    "type": normalized_type,
                    "text": text,
                })
                logger.debug("HaS found entity: %s (%s)", text, normalized_type)

        await _narrow_amount_entities(entities, has_client)

        # Boxes come from matching these values back to OCR blocks; mIoU is the
        # only merge step.
        logger.info("HaS total %d sensitive entities found", len(entities))
        _record_has_text_metric(stage_status, "has_text_entity_count", len(entities))
        _record_has_text_metric(
            stage_status,
            "has_text_total_ms",
            round((time.perf_counter() - total_start) * 1000),
        )
        return entities

    except Exception as e:
        logger.exception("HaS text analysis failed: %s", e)
        _record_has_text_metric(stage_status, "has_text_cache_status", "failed")
        _record_has_text_metric(
            stage_status,
            "has_text_total_ms",
            round((time.perf_counter() - total_start) * 1000),
        )
        # NER failed; structural table-amount / form-field recalls are still valid.
        return []
