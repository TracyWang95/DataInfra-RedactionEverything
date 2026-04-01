"""
混合NER识别服务
三阶段架构：HaS（本地模型） → 正则 → 交叉验证

核心特点：
1. HaS 优先：使用本地 HaS 模型进行语义 NER
2. 正则补充：高置信度模式匹配（身份证、手机号等）
3. 指代消解：同一实体统一标记
4. 交叉验证：去重合并，提高准确率
"""

import logging
import re

logger = logging.getLogger(__name__)
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass

from app.models.schemas import Entity
from app.services.has_service import has_service, HaSService
from app.services.regex_service import regex_service as _regex_svc
from typing import Any

# 类型别名，兼容 EntityTypeConfig 和 CustomEntityType
EntityTypeConfig = Any  # 只需要 id, name, regex_pattern, use_llm 等字段


@dataclass
class HybridEntity:
    """混合识别实体"""
    id: str
    text: str
    type: str
    start: int
    end: int
    confidence: float
    source: str  # regex / has
    tag: Optional[str] = None  # HaS格式标签
    coref_id: Optional[str] = None  # 指代消解ID


class HybridNERService:
    """混合NER识别服务 - HaS + 正则"""

    # 正则模式已统一到 regex_service.py（单一数据源）

    # NER 文本长度上限，超过此值截断以防止内存/时间爆炸
    MAX_TEXT_LENGTH = 500_000

    def __init__(self, has_service_instance: HaSService = None):
        self.has_service = has_service_instance or has_service
    
    async def extract(
        self,
        text: str,
        entity_types: List[EntityTypeConfig],
    ) -> List[Entity]:
        """
        混合识别主入口（HaS 仅使用 NER 单次推理；Hide 模式已移除）
        """
        import time as _time
        _t0 = _time.perf_counter()
        all_entities: List[Entity] = []

        # 文本长度保护 — truncate to prevent OOM/timeout but warn clearly
        truncated = False
        original_length = len(text)
        if original_length > self.MAX_TEXT_LENGTH:
            logger.warning(
                "文本过长 (%d chars / %.1f MB)，截断至 %d chars。部分内容可能未被识别。",
                original_length, original_length / 1_048_576, self.MAX_TEXT_LENGTH,
            )
            text = text[:self.MAX_TEXT_LENGTH]
            truncated = True

        # Stage 1: HaS 本地模型 NER
        logger.info("Stage 1: HaS 本地模型 NER...")
        if self.has_service.is_available():
            try:
                has_entities = await self.has_service.extract_entities(text, entity_types)
                all_entities.extend(has_entities)
                logger.info("  HaS NER 识别到 %d 个实体", len(has_entities))
            except Exception as e:
                logger.error("  HaS 识别失败: %s", e)
        else:
            logger.warning("  HaS 服务不可用，跳过")

        # Stage 2: 正则识别（补充高置信度模式）
        logger.info("Stage 2: 正则识别...")
        enabled_type_ids = {et.id for et in entity_types}
        regex_entities = self._regex_extract(text, enabled_type_ids)
        all_entities.extend(regex_entities)
        logger.info("  正则识别到 %d 个新实体", len(regex_entities))

        # Stage 3: 交叉验证 + 指代消解
        logger.info("Stage 3: 交叉验证与指代消解...")
        validated_entities = self._cross_validate(all_entities, text)
        logger.info("  验证后保留 %d 个实体", len(validated_entities))

        # Prometheus: NER 延迟 + 实体数
        from app.core.metrics import NER_DURATION, NER_ENTITY_COUNT
        NER_DURATION.labels(backend="hybrid").observe(_time.perf_counter() - _t0)
        NER_ENTITY_COUNT.observe(len(validated_entities))

        return validated_entities
    
    def _regex_extract(
        self,
        text: str,
        enabled_type_ids: set,
    ) -> List[Entity]:
        """正则识别 — 委托给 regex_service（单一数据源，避免重复维护模式）"""
        if not enabled_type_ids:
            return []
        raw = _regex_svc.extract(text, entity_types=list(enabled_type_ids))
        entities = []
        for i, item in enumerate(raw):
            entities.append(Entity(
                id=f"regex_{item['type']}_{i}",
                text=item["text"],
                type=item["type"],
                start=item["start"],
                end=item["end"],
                page=1,
                confidence=item.get("confidence", 0.99),
                source="regex",
            ))
        return entities
    
    def _cross_validate(
        self,
        entities: List[Entity],
        text: str,
    ) -> List[Entity]:
        """交叉验证与指代消解"""
        if not entities:
            return []
        
        # 1. 验证实体文本是否在原文中正确位置
        validated = []
        used_positions: set[tuple[int, int]] = set()
        for entity in entities:
            if 0 <= entity.start < entity.end <= len(text):
                actual_text = text[entity.start:entity.end]
                if actual_text == entity.text:
                    validated.append(entity)
                    used_positions.add((entity.start, entity.end))
                    continue
            
            # 尝试重新定位（避开已占用位置）
            start_index = 0
            while True:
                found = text.find(entity.text, start_index)
                if found < 0:
                    break
                end = found + len(entity.text)
                overlaps = any(not (end <= s or found >= e) for s, e in used_positions)
                if not overlaps:
                    entity.start = found
                    entity.end = end
                    validated.append(entity)
                    used_positions.add((found, end))
                    break
                start_index = found + len(entity.text)
        
        # 2. 去重（优先保留高置信度与正则结果）
        def source_rank(source: Optional[str]) -> int:
            order = {"regex": 3, "has": 2, "llm": 2, "manual": 1}
            return order.get(source or "", 0)

        def type_priority(entity_type: Optional[str]) -> int:
            # 地址优先，避免“地点词”被误识别为机构
            priority = {
                "ADDRESS": 3,
                "ORG": 2,
                "PERSON": 2,
                "LEGAL_PARTY": 2,
                "LAWYER": 2,
                "JUDGE": 2,
            }
            return priority.get(entity_type or "", 1)
        
        entity_map: Dict[tuple, Entity] = {}
        for entity in validated:
            key = (entity.start, entity.end)
            if key not in entity_map:
                entity_map[key] = entity
                continue
            existing = entity_map[key]
            if entity.confidence > existing.confidence:
                entity_map[key] = entity
            elif entity.confidence == existing.confidence:
                if source_rank(entity.source) > source_rank(existing.source):
                    entity_map[key] = entity
                elif source_rank(entity.source) == source_rank(existing.source):
                    if type_priority(entity.type) > type_priority(existing.type):
                        entity_map[key] = entity
        
        deduped = list(entity_map.values())
        
        # 3. 指代消解（相同文本+类型赋予相同coref_id）
        text_type_to_coref: Dict[tuple, str] = {}
        coref_counter = 0
        
        for entity in deduped:
            key = (entity.text, entity.type)
            if key not in text_type_to_coref:
                coref_counter += 1
                text_type_to_coref[key] = f"coref_{coref_counter:03d}"
            entity.coref_id = text_type_to_coref[key]
        
        # 4. 按位置排序并重新分配ID
        deduped.sort(key=lambda e: e.start)
        for i, entity in enumerate(deduped):
            entity.id = f"entity_{i}"
        
        return deduped


# 全局服务实例
hybrid_ner_service = HybridNERService()


async def perform_hybrid_ner(
    content: str,
    entity_types: List[EntityTypeConfig],
) -> List[Entity]:
    """执行混合 NER 识别（HaS 仅 NER）"""
    return await hybrid_ner_service.extract(content, entity_types)
