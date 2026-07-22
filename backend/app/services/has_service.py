"""
HaS (Hide And Seek) 本地匿名化模型服务
基于 xuanwulab/HaS_Text_0209_0.6B_Q4（GGUF：HaS_Text_0209_0.6B_Q4_K_M.gguf）
通过 llama.cpp OpenAI 兼容接口调用

功能：
1. NER 敏感实体识别
2. 结构化语义标签匿名化
3. 指代消解（同一实体用相同ID）
4. 支持信息还原
"""

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

from app.core.gpu_inference_gate import shared_gpu_inference_slot
from app.models.schemas import Entity
from app.models.type_mapping import canonical_type_id
from app.services.has_client import HaSClient

# 类型别名，兼容 EntityTypeConfig 和 CustomEntityType
EntityTypeConfig = Any

# 估算类型批次 token 成本：约每 2 个字符折算 1 个 token
_NER_CHARS_PER_TOKEN = 2
# 每个中文类型名在请求中的固定 token 开销
_NER_TOKENS_PER_TYPE = 8
# 单批次目标 token 预算的最小下限（防呆：env 误配过小也不低于千级——
# Tracy: 128 太小，预算按 8k 级跑）
_NER_MIN_TARGET_TOKENS = 1024


class HaSService:
    """HaS NER 服务 - 用于混合 NER 架构"""

    BUILTIN_TYPE_GUIDANCE: dict[str, dict[str, Any]] = {
        "ADDRESS": {
            "description": "具体地点、住所地、道路、路口、交汇处、事故地点、办公地点。",
            "examples": ["南山区深南大道与科苑路交汇处", "广东省深圳市南山区科技园", "某某路88号"],
        },
        "BIRTH_DATE": {
            "description": "自然人的出生日期或生日；带“出生/生日/出生日期”的年月日属于此类，不属于年龄。",
            "examples": ["1985年7月15日出生", "出生日期：1992-10-05", "生日1992/10/05"],
        },
        "AGE": {
            "description": "年龄或年龄段，只识别多少岁、多少周岁、未满/以上等年龄表达；不要识别出生日期。",
            "examples": ["35岁", "未满18周岁", "60岁以上"],
        },
    }

    def __init__(self, base_url: str | None = None):
        self.client = HaSClient(base_url=base_url)

    def is_available(self) -> bool:
        """检查 HaS 服务是否可用"""
        return self.client.is_available()

    def _convert_entity_types_to_chinese(
        self,
        entity_types: list[EntityTypeConfig]
    ) -> list[str]:
        """将实体类型配置转换为 HaS 需要的中文类型列表"""
        # 勾选什么查什么: the item's user-facing name IS the model query —
        # no registry translation (the enumerated id→label mapping silently
        # diverged from the checklist and can never be complete).
        chinese_types = []
        seen = set()
        for et in entity_types:
            chinese_type = str(getattr(et, "name", "") or "").strip() or str(getattr(et, "id", "") or "")
            if chinese_type and chinese_type not in seen:
                seen.add(chinese_type)
                chinese_types.append(chinese_type)
        return chinese_types

    def _convert_entity_types_to_guidance(
        self,
        entity_types: list[EntityTypeConfig],
    ) -> list[dict[str, Any]]:
        from app.core.config import settings

        guidance: list[dict[str, Any]] = []
        for entity_type in entity_types:
            raw_type_id = str(getattr(entity_type, "id", "") or "").strip()
            type_id = canonical_type_id(raw_type_id)
            is_custom = self._is_custom_type_id(raw_type_id) or self._is_custom_type_id(type_id)
            builtin_guidance = self.BUILTIN_TYPE_GUIDANCE.get(type_id)
            if not is_custom and not builtin_guidance and not settings.HAS_NER_BUILTIN_GUIDANCE_ENABLED:
                continue
            chinese_types = self._convert_entity_types_to_chinese([entity_type])
            if not chinese_types:
                continue
            description = str(
                (builtin_guidance or {}).get("description")
                or getattr(entity_type, "description", "")
                or ""
            ).strip()
            examples = list((builtin_guidance or {}).get("examples") or getattr(entity_type, "examples", []) or [])
            if not description and not examples:
                continue
            for chinese_type in self._expand_query_type_names(type_id, chinese_types):
                guidance.append({
                    "type": chinese_type,
                    "description": description,
                    "examples": examples,
                })
        return guidance

    def _iter_ner_type_batches(
        self,
        entity_types: list[EntityTypeConfig],
    ) -> list[list[EntityTypeConfig]]:
        from app.core.config import settings

        seen_chinese_types: set[str] = set()
        ordered_types: list[EntityTypeConfig] = []
        builtin_types: list[EntityTypeConfig] = []
        custom_types: list[EntityTypeConfig] = []

        for entity_type in entity_types:
            chinese_types = self._convert_entity_types_to_chinese([entity_type])
            if not chinese_types:
                continue
            chinese_type = chinese_types[0]
            if chinese_type in seen_chinese_types:
                continue
            seen_chinese_types.add(chinese_type)
            ordered_types.append(entity_type)

            raw_type_id = str(getattr(entity_type, "id", "") or "").strip()
            type_id = canonical_type_id(raw_type_id)
            if self._is_custom_type_id(raw_type_id) or self._is_custom_type_id(type_id):
                custom_types.append(entity_type)
            else:
                builtin_types.append(entity_type)

        if not ordered_types:
            return []

        if self._ner_type_batch_cost(ordered_types) <= int(settings.HAS_NER_TYPE_BATCH_TARGET_TOKENS) and len(ordered_types) <= settings.HAS_NER_SINGLE_PASS_MAX_TYPES:
            return [ordered_types]

        batches: list[list[EntityTypeConfig]] = []
        batches.extend(self._pack_ner_type_batches(
            builtin_types,
            max_types=int(settings.HAS_NER_MAX_TYPES_PER_REQUEST),
            target_tokens=int(settings.HAS_NER_TYPE_BATCH_TARGET_TOKENS),
        ))
        batches.extend(self._pack_ner_type_batches(
            custom_types,
            max_types=int(settings.HAS_NER_CUSTOM_MAX_TYPES_PER_REQUEST),
            target_tokens=int(settings.HAS_NER_TYPE_BATCH_TARGET_TOKENS),
        ))
        logger.info(
            "HaS NER packed %d requested types into %d adaptive batches",
            len(ordered_types),
            len(batches),
        )
        return batches

    def _pack_ner_type_batches(
        self,
        items: list[EntityTypeConfig],
        max_types: int,
        target_tokens: int,
    ) -> list[list[EntityTypeConfig]]:
        batches: list[list[EntityTypeConfig]] = []
        current: list[EntityTypeConfig] = []
        current_cost = 0
        max_types = max(1, max_types)
        target_tokens = max(_NER_MIN_TARGET_TOKENS, target_tokens)

        for item in items:
            item_cost = self._ner_type_batch_cost([item])
            should_flush = bool(current) and (
                len(current) >= max_types
                or current_cost + item_cost > target_tokens
            )
            if should_flush:
                batches.append(current)
                current = []
                current_cost = 0
            current.append(item)
            current_cost += item_cost

        if current:
            batches.append(current)
        return batches

    def _ner_type_batch_cost(self, entity_types: list[EntityTypeConfig]) -> int:
        guidance = self._convert_entity_types_to_guidance(entity_types)
        chinese_types = self._convert_entity_types_to_chinese(entity_types)
        text = "".join(chinese_types)
        for item in guidance:
            text += str(item.get("type") or "")
            text += str(item.get("description") or "")
            text += "".join(str(example) for example in item.get("examples") or [])
        return max(1, len(text) // _NER_CHARS_PER_TOKEN + len(chinese_types) * _NER_TOKENS_PER_TYPE)

    def _expand_query_type_names(self, type_id: str, chinese_types: list[str]) -> list[str]:
        """Add prompt-only aliases for a selected L3 type.

        This keeps the user-facing entity schema atomic: aliases only broaden
        the model query, and result buckets are mapped back to the same L3 id.
        """
        names: list[str] = []
        for name in chinese_types:
            name_text = str(name or "").strip()
            if name_text and name_text not in names:
                names.append(name_text)

        # No hidden alias expansion: the checklist owns the query vocabulary.
        return names

    @staticmethod
    def _is_custom_type_id(type_id: str | None) -> bool:
        return str(type_id or "").strip().lower().startswith("custom_")

    def _build_requested_type_lookup(
        self,
        entity_types: list[EntityTypeConfig],
    ) -> tuple[set[str], dict[str, str], list[tuple[str, str]]]:
        requested_type_ids: set[str] = set()
        requested_type_by_name: dict[str, str] = {}
        custom_requested_types: list[tuple[str, str]] = []

        for entity_type in entity_types:
            raw_type_id = str(getattr(entity_type, "id", "") or "").strip()
            if not raw_type_id:
                continue
            type_id = canonical_type_id(raw_type_id)
            requested_type_ids.add(type_id)

            target_type_id = raw_type_id if self._is_custom_type_id(raw_type_id) else type_id
            exact_names = {
                raw_type_id,
                type_id,
                str(getattr(entity_type, "name", "") or "").strip(),
                *self._convert_entity_types_to_chinese([entity_type]),
                *self._expand_query_type_names(type_id, self._convert_entity_types_to_chinese([entity_type])),
            }
            for type_name in exact_names:
                if type_name:
                    requested_type_by_name[type_name] = target_type_id

            if self._is_custom_type_id(raw_type_id) or self._is_custom_type_id(type_id):
                custom_requested_types.append((raw_type_id, str(getattr(entity_type, "name", "") or "").strip()))

        return requested_type_ids, requested_type_by_name, custom_requested_types

    def _resolve_result_type_id(
        self,
        result_type_name: str,
        requested_type_by_name: dict[str, str],
        custom_requested_types: list[tuple[str, str]],
        requested_type_ids: set[str] | None = None,
    ) -> str | None:
        result_type_name = str(result_type_name or "").strip()
        if not result_type_name:
            return None
        direct = requested_type_by_name.get(result_type_name)
        if direct:
            return direct
        # Open vocabulary: keep the model's raw label as the type (识别出来是啥就是啥).
        return result_type_name

    async def extract_entities(
        self,
        content: str,
        entity_types: list[EntityTypeConfig]
    ) -> list[Entity]:
        """
        使用 HaS 模型进行 NER 识别

        Args:
            content: 待识别文本
            entity_types: 要识别的实体类型配置

        Returns:
            识别到的实体列表
        """
        if not content.strip():
            return []

        (
            requested_type_ids,
            requested_type_by_name,
            custom_requested_types,
        ) = self._build_requested_type_lookup(entity_types)

        try:
            # 调用 HaS NER。全选默认清单时类型很多，小模型容易把大量空
            # bucket 也输出出来并触发 JSON 截断；按类型分组能让每次响应
            # 保持短而完整，同时仍然完全依赖 HaS 语义识别。
            from app.core.config import settings

            ner_result: dict[str, list[str]] = {}
            batches = self._iter_ner_type_batches(entity_types)
            max_parallel = max(1, int(settings.HAS_NER_MAX_PARALLEL_REQUESTS))
            semaphore = asyncio.Semaphore(max_parallel)

            async def run_batch(batch: list[EntityTypeConfig]) -> dict[str, list[str]]:
                batch_chinese_types = self._convert_entity_types_to_chinese(batch)
                for item in batch:
                    batch_chinese_types = self._expand_query_type_names(
                        canonical_type_id(getattr(item, "id", "")),
                        batch_chinese_types,
                    )
                if not batch_chinese_types:
                    return {}
                async with semaphore:
                    async with shared_gpu_inference_slot("HaS Text NER batch"):
                        return await asyncio.to_thread(
                            self.client.ner,
                            content,
                            batch_chinese_types,
                            type_guidance=self._convert_entity_types_to_guidance(batch),
                        )

            batch_results = await asyncio.gather(
                *(run_batch(batch) for batch in batches),
                return_exceptions=True,
            )
            for batch_result in batch_results:
                if isinstance(batch_result, Exception):
                    logger.warning("HaS NER batch failed: %s", batch_result)
                    continue
                for result_type, values in batch_result.items():
                    if not isinstance(values, list):
                        continue
                    bucket = ner_result.setdefault(result_type, [])
                    for value in values:
                        if value and value not in bucket:
                            bucket.append(value)

            if not ner_result:
                return []

            # 转换为 Entity 对象
            entities = []
            entity_id = 0
            coref_map: dict[str, str] = {}  # text:type -> coref_id

            for chinese_type, entity_list in ner_result.items():
                # 映射中文类型到英文ID
                raw_entity_type_id = self._resolve_result_type_id(
                    chinese_type,
                    requested_type_by_name,
                    custom_requested_types,
                    requested_type_ids,
                )

                for entity_text in entity_list:
                    if not entity_text:
                        continue

                    entity_type_id = self._coerce_result_type(
                        raw_entity_type_id,
                        requested_type_ids,
                        entity_text,
                    )
                    if entity_type_id is None:
                        continue

                    # 在原文中查找所有出现位置
                    start = 0
                    while True:
                        pos = content.find(entity_text, start)
                        if pos < 0:
                            break

                        # 指代消解：相同文本+类型使用相同 coref_id
                        coref_key = f"{entity_text}:{entity_type_id}"
                        if coref_key not in coref_map:
                            coref_map[coref_key] = f"coref_{len(coref_map)}"

                        entities.append(Entity(
                            id=f"has_{entity_id}",
                            text=entity_text,
                            type=entity_type_id,
                            start=pos,
                            end=pos + len(entity_text),
                            page=1,
                            # No score: HaS returns values, not probabilities, and
                            # its token logprobs measure character predictability
                            # rather than whether the span is PII (probed: the
                            # correct 李建国/周明 scored 0.75/0.87 while an empty
                            # answer scored 0.99).
                            source="has",
                            coref_id=coref_map[coref_key],
                        ))

                        entity_id += 1
                        start = pos + len(entity_text)

            # 按位置排序
            entities.sort(key=lambda e: e.start)

            return entities

        except Exception as e:
            logger.exception("HaS NER 失败: %s", e)
            return []

    def _coerce_result_type(
        self,
        entity_type_id: str,
        requested_type_ids: set[str | None],
        entity_text: str,
    ) -> str | None:
        """Keep HaS output aligned with the caller-selected recognition list."""
        raw_entity_type_id = str(entity_type_id or "").strip()
        if not raw_entity_type_id:
            return None
        # Open vocabulary: keep whatever the model returned (识别出来是啥就是啥);
        # don't drop a label just because it isn't in the requested list.
        if self._is_custom_type_id(raw_entity_type_id):
            return raw_entity_type_id
        return canonical_type_id(entity_type_id)


# 全局服务实例
has_service = HaSService()
