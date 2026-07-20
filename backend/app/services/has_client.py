"""
HaS (Hide And Seek) 本地模型客户端
使用 llama.cpp 的 OpenAI 兼容接口

推荐模型：xuanwulab/HaS_Text_0209_0.6B_Q4（GGUF：HaS_Text_0209_0.6B_Q4_K_M.gguf）
NER / Hide / Pair / Seek 的 user 提示须与模型卡模板逐字一致（勿在 NER 首段插入额外说明）。

功能：
1. ner - 敏感实体识别
2. hide - 标签化匿名化
3. pair - 提取标签映射
4. seek - 标签还原
"""

import hashlib
import json
import logging
import re
import threading
import time
from collections import OrderedDict

import httpx

logger = logging.getLogger(__name__)
from dataclasses import dataclass
from typing import Any

from app.core.circuit_breaker import ner_breaker
from app.core.retry import RETRYABLE_HTTPX, retry_sync
from app.models.type_mapping import canonical_type_id

# 默认重试次数（max_retries 未显式传入时）
_DEFAULT_MAX_RETRIES = 2
# 重试退避基准秒数
_RETRY_BASE_DELAY_SEC = 1.0
# 采样温度（确定性输出）
_MODEL_TEMPERATURE = 0.0
# 采样 top_p
_MODEL_TOP_P = 0.6
# max_tokens 下限（_call_model 单次请求）
_MIN_CALL_MAX_TOKENS = 32
# 提示词 token 估算：ASCII 字符按 4 字符/token 折算
_PROMPT_ASCII_CHARS_PER_TOKEN = 4
# 提示词 token 估算：固定结构开销
_PROMPT_TOKEN_OVERHEAD = 32
# NER 类型批量目标 token 数下限
_NER_TYPE_BATCH_TARGET_TOKENS_FLOOR = 320
# 由目标 token 推导每批类型数的除数
_NER_BATCH_TOKENS_PER_TYPE = 40
# 每批类型数下限
_NER_BATCH_MIN_TYPES = 8
# 每批类型数上限
_NER_BATCH_MAX_TYPES = 24
# 单趟 NER 文本字符数下限
_NER_SINGLE_PASS_MIN_CHARS = 128
# NER 期望 max_tokens 下限
_NER_DESIRED_MAX_TOKENS_FLOOR = 640
# NER 期望 max_tokens：每个类型预算 token 数
_NER_TOKENS_PER_TYPE = 72
# NER 期望 max_tokens：文本字符折算除数
_NER_TEXT_CHARS_PER_TOKEN = 2
# NER 上下文窗口 token 数下限
_NER_CONTEXT_TOKENS_FLOOR = 512
# 上下文中预留给模板/分隔的 token 数
_NER_CONTEXT_RESERVE_TOKENS = 160
# 补全 token 上限下限
_NER_COMPLETION_CAP_FLOOR = 384
# 补全 token 占上下文窗口比例
_NER_COMPLETION_CONTEXT_RATIO = 0.65
# 受上下文余量约束后的 max_tokens 下限
_NER_MAX_TOKENS_FLOOR = 64
# 触发分批回退的类型数阈值
_NER_REBATCH_TYPE_THRESHOLD = 24
# 类型引导 description 最大字符数
_TYPE_GUIDANCE_DESC_MAX_CHARS = 96
# 健康检查结果缓存秒数
_HEALTH_CHECK_CACHE_SEC = 5.0
# 健康检查请求超时秒数
_HEALTH_CHECK_TIMEOUT_SEC = 5.0


@dataclass
class HaSEntity:
    """HaS识别的实体"""
    text: str
    type: str
    tag: str | None = None  # 结构化语义标签


@dataclass
class HaSResult:
    """HaS处理结果"""
    original_text: str
    masked_text: str
    entities: dict[str, list[str]]  # {类型: [实体列表]}
    mapping: dict[str, list[str]]   # {标签: [原文列表]}


class HaSClient:
    """HaS本地模型客户端"""

    _SHARED_NER_CACHE: OrderedDict[
        tuple[str, tuple[str, ...], str, str, int],
        tuple[float, dict[str, list[str]]],
    ] = OrderedDict()
    _SHARED_NER_INFLIGHT: dict[tuple[str, tuple[str, ...], str, str, int], threading.Event] = {}
    _SHARED_NER_LOCK = threading.Lock()


    def __init__(
        self,
        base_url: str = None,
        timeout: float = None,
        max_retries: int | None = None,
    ):
        from app.core.config import settings
        self._base_url_override = base_url.rstrip("/") if base_url else None
        self.timeout = httpx.Timeout(timeout or settings.HAS_TIMEOUT)
        self._max_retries = _DEFAULT_MAX_RETRIES if max_retries is None else max(0, int(max_retries))
        self._ner_cache_ttl_sec = settings.HAS_NER_CACHE_TTL_SEC
        self._ner_cache_max_items = settings.HAS_NER_CACHE_MAX_ITEMS
        self._ner_cache = self._SHARED_NER_CACHE
        self._ner_inflight = self._SHARED_NER_INFLIGHT
        self._ner_lock = self._SHARED_NER_LOCK
        # 复用 httpx 连接池，避免每次请求创建新连接
        self._http_client = httpx.Client(timeout=self.timeout, trust_env=False)
        self._health_checked_at = 0.0
        self._health_ready = False

    def _effective_base_url(self) -> str:
        from app.core.config import get_has_chat_base_url
        if self._base_url_override:
            return self._base_url_override.rstrip("/")
        return get_has_chat_base_url().rstrip("/")

    def _do_chat_request(self, base: str, payload: dict[str, Any]) -> httpx.Response:
        """Execute a single chat completions HTTP request (retryable, uses pooled client)."""
        def _request():
            resp = self._http_client.post(f"{base}/chat/completions", json=payload)
            resp.raise_for_status()
            return resp
        return ner_breaker.call_sync(_request)

    def _call_model(
        self,
        messages: list[dict],
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> str:
        """调用 OpenAI 兼容接口（llama.cpp HaS）。

        temperature 未传时用确定性默认 _MODEL_TEMPERATURE(=0.0)；自洽多趟采样时
        调用方按趟传入(第0趟贪心0.0，后续 temp>0)。
        """
        from app.core.config import settings
        base = self._effective_base_url()
        payload: dict[str, Any] = {
            "messages": messages,
            "temperature": _MODEL_TEMPERATURE if temperature is None else float(temperature),
            "top_p": _MODEL_TOP_P,
            "stream": False,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max(_MIN_CALL_MAX_TOKENS, int(max_tokens))
        if settings.HAS_TEXT_MODEL_NAME:
            payload["model"] = settings.HAS_TEXT_MODEL_NAME
        started = time.perf_counter()
        response = retry_sync(
            self._do_chat_request, base, payload,
            max_retries=self._max_retries, base_delay=_RETRY_BASE_DELAY_SEC,
            retryable_exceptions=RETRYABLE_HTTPX,
        )
        elapsed_ms = round((time.perf_counter() - started) * 1000)
        logger.info("HaS model request finished in %dms", elapsed_ms)
        data = response.json()
        # 安全访问嵌套结构，避免 KeyError/IndexError
        choices = data.get("choices")
        if not choices or not isinstance(choices, list) or len(choices) == 0:
            logger.error("HaS 模型返回无 choices: %.200s", str(data))
            return ""
        choice = choices[0]
        finish_reason = choice.get("finish_reason")
        if finish_reason == "length":
            logger.warning(
                "HaS model response was truncated by max_tokens=%s",
                payload.get("max_tokens"),
            )
        elif finish_reason and finish_reason not in {"stop", "eos_token"}:
            logger.info("HaS model finish_reason=%s", finish_reason)
        message = choice.get("message", {})
        return message.get("content", "")

    @staticmethod
    def _copy_ner_result(result: dict[str, list[str]]) -> dict[str, list[str]]:
        return {
            key: list(value) if isinstance(value, list) else value
            for key, value in result.items()
        }

    @staticmethod
    def _try_parse_json_object(input_text: str) -> tuple[str, dict[str, Any] | None]:
        raw = str(input_text or "").strip()
        if not raw:
            return "empty", None

        fenced = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE).strip()
        fenced = re.sub(r"\s*```$", "", fenced).strip()
        start = fenced.find("{")
        end = fenced.rfind("}")

        candidates: list[tuple[str, str]] = [("direct", raw)]
        if fenced != raw:
            candidates.append(("fenced", fenced))
        if start >= 0 and end > start:
            candidates.append(("substring", fenced[start:end + 1]))

        seen: set[str] = set()
        for mode, candidate in candidates:
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            try:
                parsed = json.loads(candidate)
            except (json.JSONDecodeError, ValueError, TypeError):
                continue
            if isinstance(parsed, dict):
                return mode, parsed

        try:
            from json_repair import repair_json
        except Exception:
            return "failed", None

        for mode, candidate in candidates:
            if not candidate:
                continue
            try:
                repaired = repair_json(candidate, return_objects=False)
                parsed = json.loads(repaired)
            except Exception:
                continue
            if isinstance(parsed, dict):
                return f"json_repair:{mode}", parsed

        return "failed", None

    @staticmethod
    def _trim_truncated_tail_value(result: dict[str, Any]) -> dict[str, Any]:
        """Drop the cut-off tail value json_repair leaves in the last bucket.

        A repetition loop truncated by max_tokens ends mid-value; the repaired
        JSON keeps that fragment (e.g. '2') as a real value. Only drop it when
        it is a proper prefix of an earlier value in the same bucket — the
        signature of a truncated repetition, never of a legitimate value.
        """
        if not result:
            return result
        last_key = next(reversed(result))
        values = result.get(last_key)
        if not isinstance(values, list) or len(values) < 2:
            return result
        tail = values[-1]
        if isinstance(tail, str) and tail and any(
            isinstance(value, str) and value != tail and value.startswith(tail)
            for value in values[:-1]
        ):
            result = dict(result)
            result[last_key] = values[:-1]
        return result

    @staticmethod
    def _normalize_ner_type_name(type_name: str) -> str:
        value = str(type_name or "").strip()
        if not value:
            return ""
        if value.isascii():
            return canonical_type_id(value.upper())

        return value

    @staticmethod
    def _estimate_prompt_tokens(text: str) -> int:
        """Conservative local estimate for vLLM context budgeting.

        HaS prompts mix English instructions, Chinese type names, OCR Chinese,
        JSON punctuation, and scanned text fragments. A len//2 estimate is too
        optimistic for Chinese-heavy pages and can make vLLM reject the request
        before inference starts.
        """
        ascii_chars = 0
        non_ascii_chars = 0
        for char in str(text or ""):
            if ord(char) < 128:
                ascii_chars += 1
            else:
                non_ascii_chars += 1
        return max(1, ascii_chars // _PROMPT_ASCII_CHARS_PER_TOKEN + non_ascii_chars + _PROMPT_TOKEN_OVERHEAD)

    @classmethod
    def _normalize_ner_types(cls, entity_types: list[str] | None) -> list[str]:
        if not entity_types:
            raise ValueError("entity_types 必须显式传入非空清单(清单即真相源,无隐藏默认词表)")
        return list(dict.fromkeys(
            normalized
            for type_name in entity_types
            if (normalized := cls._normalize_ner_type_name(type_name))
        ))

    def _ner_cache_key(
        self,
        text: str,
        entity_types: list[str],
        guidance_key: str = "",
        sample_index: int = 0,
    ) -> tuple[str, tuple[str, ...], str, str, int]:
        # sample_index keeps self-consistent temp>0 passes over the SAME payload
        # from being served the temp=0 seed's cached result (union would collapse
        # to a single 趟). Default 0 = the deterministic seed / today's key.
        digest = hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()
        return (
            self._effective_base_url(),
            tuple(sorted(entity_types)),
            digest,
            guidance_key,
            int(sample_index),
        )

    def _get_cached_ner(
        self,
        key: tuple[str, tuple[str, ...], str, str, int],
    ) -> dict[str, list[str]] | None:
        if self._ner_cache_ttl_sec <= 0 or self._ner_cache_max_items <= 0:
            return None
        now = time.monotonic()
        with self._ner_lock:
            cached = self._ner_cache.get(key)
            if not cached:
                return None
            stored_at, result = cached
            if now - stored_at > self._ner_cache_ttl_sec:
                self._ner_cache.pop(key, None)
                return None
            self._ner_cache.move_to_end(key)
            logger.info("HaS NER cache hit")
            return self._copy_ner_result(result)

    def get_cached_ner(
        self,
        text: str,
        entity_types: list[str] | None = None,
    ) -> dict[str, list[str]] | None:
        """Return a cached NER result without starting a model request.

        Vision recognition uses a process-level HaS Text lock to avoid sending
        multiple expensive llama.cpp requests at once. Cache reads are local
        memory operations, so callers can use this method before waiting on
        that lock and avoid a stale duplicate page blocking behind an unrelated
        slow request.
        """
        types = self._normalize_ner_types(entity_types)
        return self._get_cached_ner(self._ner_cache_key(text, types))

    def _set_cached_ner(
        self,
        key: tuple[str, tuple[str, ...], str, str, int],
        result: dict[str, list[str]],
    ) -> None:
        if self._ner_cache_ttl_sec <= 0 or self._ner_cache_max_items <= 0:
            return
        with self._ner_lock:
            self._ner_cache[key] = (time.monotonic(), self._copy_ner_result(result))
            self._ner_cache.move_to_end(key)
            while len(self._ner_cache) > self._ner_cache_max_items:
                self._ner_cache.popitem(last=False)

    def _begin_ner_request(
        self,
        key: tuple[str, tuple[str, ...], str, str, int],
    ) -> tuple[bool, threading.Event | None]:
        if self._ner_cache_ttl_sec <= 0 or self._ner_cache_max_items <= 0:
            return True, None
        with self._ner_lock:
            event = self._ner_inflight.get(key)
            if event is not None:
                logger.info("HaS NER joined in-flight duplicate request")
                return False, event
            event = threading.Event()
            self._ner_inflight[key] = event
            return True, event

    def _finish_ner_request(
        self,
        key: tuple[str, tuple[str, ...], str, str, int],
        event: threading.Event | None,
    ) -> None:
        if event is None:
            return
        with self._ner_lock:
            self._ner_inflight.pop(key, None)
            event.set()

    def create_session_mapping(self) -> dict[str, list[str]]:
        """创建一个独立的会话映射（用于并发安全的批处理）。

        调用方应在请求开始时创建，然后传给 hide() 的 mapping 参数，
        这样每个请求拥有独立的映射，不会互相污染。
        """
        return {}

    def ner(
        self,
        text: str,
        entity_types: list[str] | None = None,
        type_guidance: list[dict[str, Any]] | None = None,
        *,
        temperature: float | None = None,
        sample_index: int = 0,
        _allow_truncation_retry: bool = True,
    ) -> dict[str, list[str]]:
        """
        使用NER能力进行敏感实体识别

        Args:
            text: 待识别文本
            entity_types: 要识别的实体类型清单(必须显式传入)
            temperature: 本次请求采样温度。None=确定性默认(0.0)。自洽多趟采样时
                调用方按趟传(第0趟贪心0.0，后续 temp>0)。
            sample_index: 自洽采样趟号，进缓存键。默认 0=贪心种子/现状键；>0 的趟
                与种子不共享缓存，避免 temp>0 趟被喂种子结果导致并集塌成 1 趟。

        Returns:
            {类型: [实体列表]}
        """
        types = self._normalize_ner_types(entity_types)
        guidance = self._normalize_type_guidance(types, type_guidance)
        guidance_text = json.dumps(guidance, ensure_ascii=False, separators=(",", ":")) if guidance else ""
        guidance_key = hashlib.sha256(guidance_text.encode("utf-8", errors="ignore")).hexdigest() if guidance_text else ""
        cache_key = self._ner_cache_key(text, types, guidance_key, sample_index)
        cached = self._get_cached_ner(cache_key)
        if cached is not None:
            return cached

        from app.core.config import settings
        if type_guidance is None:
            configured_batch = max(1, int(settings.HAS_NER_MAX_TYPES_PER_REQUEST))
            target = max(_NER_TYPE_BATCH_TARGET_TOKENS_FLOOR, int(settings.HAS_NER_TYPE_BATCH_TARGET_TOKENS))
            target_batch = max(_NER_BATCH_MIN_TYPES, min(_NER_BATCH_MAX_TYPES, target // _NER_BATCH_TOKENS_PER_TYPE))
            batch_size = max(1, min(configured_batch, target_batch))
            single_pass_max_types = max(batch_size, int(settings.HAS_NER_SINGLE_PASS_MAX_TYPES))
            single_pass_max_chars = max(_NER_SINGLE_PASS_MIN_CHARS, int(settings.HAS_NER_SINGLE_PASS_MAX_TEXT_CHARS))
            should_single_pass = (
                len(types) <= single_pass_max_types
                and len(str(text or "")) <= single_pass_max_chars
            )
            if len(types) > batch_size and not should_single_pass:
                logger.info(
                    "HaS NER pre-batching %d types into chunks of %d",
                    len(types),
                    batch_size,
                )
                merged: dict[str, list[str]] = {}
                for start in range(0, len(types), batch_size):
                    part = self.ner(
                        text,
                        types[start:start + batch_size],
                        None,
                        temperature=temperature,
                        sample_index=sample_index,
                    )
                    for key, values in (part or {}).items():
                        if not values:
                            continue
                        bucket = merged.setdefault(key, [])
                        for value in values:
                            if value not in bucket:
                                bucket.append(value)
                self._set_cached_ner(cache_key, merged)
                return merged

        owns_request, request_event = self._begin_ner_request(cache_key)
        if not owns_request:
            if request_event is not None:
                request_event.wait(timeout=self.timeout.read or None)
            cached = self._get_cached_ner(cache_key)
            if cached is not None:
                return cached
            logger.warning("HaS NER duplicate request finished without cacheable result")
            return {}
        types_str = json.dumps(types, ensure_ascii=False, separators=(",", ":"))
        guidance_block = f"\nType guidance:{guidance_text}" if guidance_text else ""

        # 与 HaS_Text_0209 模型卡 NER 模板一致（Specified types: 与 JSON 数组之间无空格）
        prompt = f"""Recognize the following entity types in the text.
Specified types:{types_str}
{guidance_block}
Return strict JSON only. Include only entity types that have matches in the text.
Never output empty arrays. Do not return requested types with no matches. Do not explain.
If nothing matches, return {{}}.
<text>{text}</text>"""
        configured_max_tokens = int(settings.HAS_NER_MAX_TOKENS)
        desired_max_tokens = max(
            _NER_DESIRED_MAX_TOKENS_FLOOR,
            min(configured_max_tokens, len(types) * _NER_TOKENS_PER_TYPE + len(text) // _NER_TEXT_CHARS_PER_TOKEN),
        )
        # Keep the completion budget inside the locally served HaS context
        # window. The 16 GB dev profile serves HaS Text with an 8K context so
        # PaddleOCR-VL, PP-StructureV3 and LocateAnything can stay resident
        # while giving OCR-derived NER enough completion budget.
        context_tokens = max(_NER_CONTEXT_TOKENS_FLOOR, int(settings.HAS_NER_CONTEXT_TOKENS))
        prompt_token_estimate = self._estimate_prompt_tokens(prompt)
        context_room = context_tokens - prompt_token_estimate - _NER_CONTEXT_RESERVE_TOKENS
        completion_cap = max(_NER_COMPLETION_CAP_FLOOR, min(configured_max_tokens, int(context_tokens * _NER_COMPLETION_CONTEXT_RATIO)))
        max_tokens = min(
            configured_max_tokens,
            desired_max_tokens,
            completion_cap,
            max(_NER_MAX_TOKENS_FLOOR, context_room),
        )
        logger.info(
            "HaS NER budget prompt_est=%d context=%d max_tokens=%d types=%d text_chars=%d",
            prompt_token_estimate,
            context_tokens,
            max_tokens,
            len(types),
            len(text),
        )

        messages = [
            {
                "role": "user",
                "content": prompt
            }
        ]

        try:
            started = time.perf_counter()
            response = self._call_model(messages, max_tokens=max_tokens, temperature=temperature)
            parse_mode, result = self._try_parse_json_object(response)
            if result is None:
                logger.warning("HaS NER response could not be parsed as JSON: %.200s", response)
                if type_guidance is None and len(types) > _NER_REBATCH_TYPE_THRESHOLD:
                    from app.core.config import settings
                    target = max(_NER_TYPE_BATCH_TARGET_TOKENS_FLOOR, int(settings.HAS_NER_TYPE_BATCH_TARGET_TOKENS))
                    batch_size = max(_NER_BATCH_MIN_TYPES, min(_NER_BATCH_MAX_TYPES, target // _NER_BATCH_TOKENS_PER_TYPE))
                    merged: dict[str, list[str]] = {}
                    for start in range(0, len(types), batch_size):
                        part = self.ner(
                            text,
                            types[start:start + batch_size],
                            None,
                            temperature=temperature,
                            sample_index=sample_index,
                        )
                        for key, values in (part or {}).items():
                            if not values:
                                continue
                            bucket = merged.setdefault(key, [])
                            for value in values:
                                if value not in bucket:
                                    bucket.append(value)
                    if merged:
                        self._set_cached_ner(cache_key, merged)
                        return merged
                return {}
            logger.info(
                "HaS NER parsed %d type buckets via %s in %dms",
                len(result),
                parse_mode,
                round((time.perf_counter() - started) * 1000),
            )
            if parse_mode.startswith("json_repair"):
                # 输出被截断/损坏（如日期桶复读循环耗尽 max_tokens）：
                # ①末桶的截断残值丢弃；②整桶丢失的请求类型补查一次并合并。
                result = self._trim_truncated_tail_value(result)
                if _allow_truncation_retry:
                    missing = [t for t in types if t not in result]
                    if missing:
                        logger.warning(
                            "HaS NER output recovered via %s; re-querying %d missing types: %s",
                            parse_mode,
                            len(missing),
                            missing,
                        )
                        missing_set = set(missing)
                        retry_guidance = [
                            item for item in (type_guidance or [])
                            if str(item.get("type") or "") in missing_set
                        ] or None
                        retry_result = self.ner(
                            text,
                            missing,
                            retry_guidance,
                            temperature=temperature,
                            sample_index=sample_index,
                            _allow_truncation_retry=False,
                        )
                        for key, values in (retry_result or {}).items():
                            if not isinstance(values, list):
                                continue
                            bucket = result.setdefault(key, [])
                            for value in values:
                                if value and value not in bucket:
                                    bucket.append(value)
            self._set_cached_ner(cache_key, result)
            return result
        except Exception as e:
            logger.error("HaS NER 失败: %s", e)
            return {}
        finally:
            self._finish_ner_request(cache_key, request_event)

    @staticmethod
    def _normalize_type_guidance(
        types: list[str],
        type_guidance: list[dict[str, Any]] | None,
    ) -> list[dict[str, Any]]:
        if not type_guidance:
            return []
        allowed = set(types)
        normalized: list[dict[str, Any]] = []
        for item in type_guidance:
            type_name = str(item.get("type") or "").strip()
            if not type_name or type_name not in allowed:
                continue
            description = re.sub(r"\s+", " ", str(item.get("description") or "").strip())
            entry: dict[str, Any] = {"type": type_name}
            if description:
                entry["description"] = description[:_TYPE_GUIDANCE_DESC_MAX_CHARS]
            normalized.append(entry)
        return normalized

    def hide(
        self,
        text: str,
        entity_types: list[str] | None = None,
        use_history: bool = True,
        mapping: dict[str, list[str]] | None = None,
    ) -> tuple[str, dict[str, list[str]]]:
        """
        使用Hide能力进行标签化匿名化

        流程：
        1. 先调用NER识别实体
        2. 再调用Hide替换为结构化标签

        Args:
            text: 待匿名化文本
            entity_types: 要识别的实体类型
            use_history: 是否使用已有映射（保持指代一致性）
            mapping: 请求级映射字典，由调用方通过 create_session_mapping()
                     创建并在同一请求内复用。若为 None 则每次创建新的空映射。

        Returns:
            (匿名化后文本, 映射表)
        """
        types = self._normalize_ner_types(entity_types)
        types_str = json.dumps(types, ensure_ascii=False, separators=(",", ":"))

        # 使用调用方传入的映射，或创建一个请求局部的空映射
        session_mapping: dict[str, list[str]] = mapping if mapping is not None else {}

        # Step 1: NER识别
        ner_result = self.ner(text, types)
        if not ner_result or all(len(v) == 0 for v in ner_result.values()):
            return text, {}

        ner_json = json.dumps(ner_result, ensure_ascii=False)

        # Step 2: Hide 第 1 轮与 ner() 使用相同 NER 模板
        ner_prompt = f"""Recognize the following entity types in the text.
Specified types:{types_str}
<text>{text}</text>"""

        if use_history and session_mapping:
            # 带历史映射
            history_json = json.dumps(session_mapping, ensure_ascii=False)
            messages = [
                {
                    "role": "user",
                    "content": ner_prompt
                },
                {
                    "role": "assistant",
                    "content": ner_json
                },
                {
                    "role": "user",
                    "content": f"Replace the above-mentioned entity types in the text according to the existing mapping pairs:{history_json}"
                }
            ]
        else:
            # 不带历史映射
            messages = [
                {
                    "role": "user",
                    "content": ner_prompt
                },
                {
                    "role": "assistant",
                    "content": ner_json
                },
                {
                    "role": "user",
                    "content": "Replace the above-mentioned entity types in the text."
                }
            ]

        try:
            masked_text = self._call_model(messages)

            # Step 3: 提取映射
            new_mapping = self.pair(text, masked_text)

            # 将新映射合并到 session_mapping（调用方持有同一引用）
            for tag, values in new_mapping.items():
                if tag not in session_mapping:
                    session_mapping[tag] = []
                for v in values:
                    if v not in session_mapping[tag]:
                        session_mapping[tag].append(v)

            return masked_text, new_mapping

        except Exception as e:
            logger.error("HaS Hide 失败: %s", e)
            return text, {}

    def pair(self, original_text: str, masked_text: str) -> dict[str, list[str]]:
        """
        使用Pair能力提取标签映射

        Args:
            original_text: 原始文本
            masked_text: 匿名化后文本

        Returns:
            {标签: [原文列表]}
        """
        messages = [
            {
                "role": "user",
                "content": f"""<original>{original_text}</original>
<anonymized>{masked_text}</anonymized>
Extract the mapping from anonymized entities to original entities."""
            }
        ]

        try:
            response = self._call_model(messages)
            result = json.loads(response)
            return result
        except json.JSONDecodeError:
            match = re.search(r'\{.*\}', response, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except (json.JSONDecodeError, ValueError):
                    pass
            return {}
        except Exception as e:
            logger.error("HaS Pair 失败: %s", e)
            return {}

    def seek(self, masked_text: str, mapping: dict[str, list[str]] | None = None) -> str:
        """
        使用Seek能力进行标签还原

        Args:
            masked_text: 匿名化后的文本
            mapping: 映射表（必须由调用方显式提供）

        Returns:
            还原后的原文
        """
        if not mapping:
            return masked_text

        mapping_json = json.dumps(mapping, ensure_ascii=False)

        messages = [
            {
                "role": "user",
                "content": f"""The mapping from anonymized entities to original entities:
{mapping_json}
Restore the original text based on the above mapping:
{masked_text}"""
            }
        ]

        try:
            restored_text = self._call_model(messages)
            return restored_text
        except Exception as e:
            logger.error("HaS Seek 失败: %s", e)
            return masked_text

    @staticmethod
    def _is_live_health_payload(data: dict[str, Any]) -> bool:
        status = str(data.get("status", "")).strip().lower()
        if status in {"busy", "running", "processing", "inferencing", "loading", "starting", "warming_up", "warming-up"}:
            return True
        if status in {"unavailable", "offline", "degraded", "error", "failed"}:
            return False
        return bool(data["ready"]) if "ready" in data else True

    def is_available(self) -> bool:
        """检查 NER 后端是否可用（llama.cpp /v1/models）。"""
        from app.core.config import get_has_health_check_url
        from app.core.health_checks import _tcp_port_open
        url = get_has_health_check_url()
        now = time.monotonic()
        if now - self._health_checked_at < _HEALTH_CHECK_CACHE_SEC:
            return self._health_ready
        try:
            response = self._http_client.get(url, timeout=_HEALTH_CHECK_TIMEOUT_SEC)
            if response.status_code == 200:
                try:
                    data = response.json()
                except Exception:
                    data = {}
                self._health_ready = self._is_live_health_payload(data) if isinstance(data, dict) else True
            elif response.status_code == 503 and _tcp_port_open(url):
                self._health_ready = True
            else:
                self._health_ready = False
            self._health_checked_at = now
            return self._health_ready
        except httpx.TimeoutException:
            if _tcp_port_open(url):
                self._health_ready = True
                self._health_checked_at = now
                return True
            self._health_ready = False
            self._health_checked_at = now
            return False
        except Exception:
            self._health_ready = False
            self._health_checked_at = now
            return False


# 全局客户端实例
has_client = HaSClient()
