"""
混合NER识别服务
三阶段架构：HaS（本地模型） → 正则 → 交叉验证

核心特点：
1. HaS 优先：使用本地 HaS 模型进行语义 NER
2. 正则补充：高置信度模式匹配（身份证、手机号等）
3. 指代消解：同一实体统一标识
4. 交叉验证：去重合并，提高准确率
"""

import asyncio
import logging
import re

logger = logging.getLogger(__name__)
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from app.core.config import settings
from app.core.safe_regex import RegexTimeoutError, safe_compile, safe_finditer
from app.models.schemas import Entity
from app.models.type_mapping import canonical_type_id, linkage_groups_for_type
from app.services.has_service import HaSService, has_service

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
    tag: str | None = None  # HaS格式标签
    coref_id: str | None = None  # 指代消解ID


@dataclass(frozen=True)
class _HaSChunk:
    text: str
    line_offsets: tuple[int, ...]


_ORG_ALIAS_SUFFIX_RE = re.compile(
    r"(?:有限责任公司|股份有限公司|有限公司|分公司|公司|集团|保险|银行|支行|人民法院|法院|医院|律师事务所)$"
)
_ORG_ALIAS_GENERIC_WORD_RE = re.compile(
    r"(?:中国|中华|省|市|区|县|有限责任|股份|有限|公司|分公司|集团|控股|"
    r"科技|技术|贸易|实业|资产|保险|银行|支行|人民|法院|医院|律师|事务所)"
)


class HybridNERService:
    """HaS-first NER service with optional user-defined fallback."""

    # NER 文本长度上限，超过此值截断以防止内存/时间爆炸
    MAX_TEXT_LENGTH = 500_000

    # HaS Text owns L3 semantic text entities by default. L1/L2 metadata is
    # used for disambiguation only and must not be requested as NER output.
    HAS_SEMANTIC_TYPE_IDS = {
        "PERSON",
        "ORG",
        "COMPANY_NAME",
        "INSTITUTION_NAME",
        "GOVERNMENT_AGENCY",
        "WORK_UNIT",
        "DEPARTMENT_NAME",
        "PROJECT_NAME",
        "ADDRESS",
    }
    ORG_LIKE_TYPE_IDS = {
        "ORG",
        "COMPANY_NAME",
        "INSTITUTION_NAME",
        "GOVERNMENT_AGENCY",
        "WORK_UNIT",
        "DEPARTMENT_NAME",
        "PROJECT_NAME",
        "LEGAL_COURT",
        "LEGAL_SERVICE_ORG",
        "FIN_INSTITUTION",
        "MED_INSTITUTION",
        "BANK_NAME",
    }
    ORG_ROLE_SUFFIXES = (
        "法定代表人", "委托诉讼代理人", "诉讼代理人", "负责人", "代表人",
        "联系人", "经办人", "董事长", "总经理", "经理", "主管",
        "员工", "职员", "律师", "医生", "护士", "教师", "教授",
        "工程师", "会计", "驾驶员", "审判员", "书记员", "检察官",
        "代理人", "主任", "院长", "行长",
    )
    ORG_BOUNDARY_SUFFIXES = (
        "有限责任公司", "股份有限公司", "有限公司", "分公司", "子公司",
        "集团", "公司", "银行", "支行", "法院", "人民法院",
        "检察院", "人民检察院", "律师事务所", "事务所", "委员会",
        "医院", "学校", "学院", "中心", "研究院", "研究所",
        "协会", "基金会", "机关", "局", "厅", "部", "处", "科",
    )
    ORG_REGION_PREFIX_RE = re.compile(
        r"^(?:中国|中华|广东省|深圳市|北京市|上海市|广州市|天津市|重庆市|"
        r"[一-龥]{2,8}(?:省|市|自治区|自治州|地区|盟|区|县))"
    )

    @staticmethod
    def _is_org_like_type(type_id: str) -> bool:
        canonical = canonical_type_id(type_id)
        return canonical in HybridNERService.ORG_LIKE_TYPE_IDS or "organization_like" in linkage_groups_for_type(canonical)
    ORG_GENERIC_STEM_RE = re.compile(
        r"(?:贸易|科技|技术|实业|资产|控股|股份|有限责任|有限|集团|公司|分公司)$"
    )
    ENTITY_EDGE_PUNCTUATION = " \t\r\n，。；：、,.!?！？;:()（）[]【】"
    MAX_HAS_TEXT_CHARS = 1_600
    MAX_HAS_CHUNKS = 12
    MAX_HAS_LINE_CHARS = 320
    SEMANTIC_LINE_HINTS = (
        "姓名", "联系人", "联络人", "经办人", "负责人", "法定代表人", "代表人",
        "采购单位", "供应商",
        "公司", "集团", "银行", "支行", "机构", "单位", "学校", "医院",
        "地址", "住所", "住址", "注册地址", "联系地址", "办公地址", "通讯地址",
        "开户", "户名", "账户名",
        "身份证", "证件", "出生", "电话", "手机", "邮箱", "账号", "账户", "卡号",
        "金额", "人民币", "费用", "价款", "付款", "赔偿", "合同编号", "协议编号",
        "订单号", "案号", "车牌", "税号", "信用代码",
    )
    SEMANTIC_LINE_HINTS = SEMANTIC_LINE_HINTS + (
        "\u6cd5\u9662",
        "\u4eba\u6c11\u6cd5\u9662",
        "\u68c0\u5bdf\u9662",
        "\u4eba\u6c11\u68c0\u5bdf\u9662",
        "\u4ef2\u88c1\u59d4\u5458\u4f1a",
        "\u516c\u8bc1\u5904",
        "\u53f8\u6cd5\u5c40",
        "\u516c\u5b89\u5c40",
        "\u5f8b\u5e08\u4e8b\u52a1\u6240",
        "\u539f\u544a",
        "\u88ab\u544a",
        "\u7b2c\u4e09\u4eba",
        "\u4e0a\u8bc9\u4eba",
        "\u88ab\u4e0a\u8bc9\u4eba",
        "\u7533\u8bf7\u4eba",
        "\u88ab\u7533\u8bf7\u4eba",
        "\u59d4\u6258\u8bc9\u8bbc\u4ee3\u7406\u4eba",
        "\u5ba1\u5224\u5458",
        "\u4e66\u8bb0\u5458",
        "\u6839\u636e",
        "\u4f9d\u636e",
        "\u4f9d\u7167",
        "\u6cd5\u5f8b\u6cd5\u89c4",
        "\u6cd5\u5f8b\u4f9d\u636e",
        "\u6cd5\u6761",
        "\u6cd5\u5178",
        "\u6c11\u6cd5\u5178",
        "\u4e4b\u89c4\u5b9a",
    )
    SEMANTIC_ORG_SUFFIX_HINTS = (
        "\u516c\u53f8", "\u96c6\u56e2", "\u94f6\u884c", "\u652f\u884c",
        "\u59d4\u5458\u4f1a", "\u4e8b\u52a1\u6240", "\u5b66\u6821",
        "\u533b\u9662", "\u4e2d\u5fc3", "\u6cd5\u9662", "\u68c0\u5bdf\u9662",
    )
    SEMANTIC_ADDRESS_HINTS = (
        "\u7701", "\u5e02", "\u533a", "\u53bf", "\u9547", "\u4e61",
        "\u8857\u9053", "\u8def", "\u8857", "\u5df7", "\u53f7", "\u5ba4",
        "\u697c", "\u5c42",
    )
    SEMANTIC_ROLE_LABEL_HINTS = (
        "\u7532\u65b9", "\u4e59\u65b9", "\u4e19\u65b9", "\u8054\u7cfb\u4eba",
        "\u6cd5\u5b9a\u4ee3\u8868\u4eba", "\u7ecf\u529e\u4eba", "\u8d1f\u8d23\u4eba",
        "\u539f\u544a", "\u88ab\u544a", "\u4e0a\u8bc9\u4eba", "\u7533\u8bf7\u4eba",
    )

    def __init__(self, has_service_instance: HaSService = None):
        self.has_service = has_service_instance or has_service

    async def extract(
        self,
        text: str,
        entity_types: list[EntityTypeConfig],
    ) -> list[Entity]:
        """
        混合识别主入口（HaS 仅使用 NER 单次推理；Hide 模式已移除）
        """
        import time as _time
        _t0 = _time.perf_counter()
        all_entities: list[Entity] = []

        # 文本长度保护 — truncate to prevent OOM/timeout but warn clearly
        original_length = len(text)
        if original_length > self.MAX_TEXT_LENGTH:
            logger.warning(
                "Text too long (%d chars / %.1f MB); truncated to %d chars. Some content may be skipped.",
                original_length, original_length / 1_048_576, self.MAX_TEXT_LENGTH,
            )
            text = text[:self.MAX_TEXT_LENGTH]

        enabled_type_ids = {canonical_type_id(et.id) for et in entity_types}

        semantic_entity_types = self._select_has_semantic_types(entity_types)
        if semantic_entity_types:
            logger.info("Stage 1: HaS local NER...")
        else:
            logger.info("Stage 1: HaS NER skipped; selected types are regex-only")

        has_available = bool(semantic_entity_types) and self.has_service.is_available()
        if semantic_entity_types and not has_available:
            logger.warning("  HaS service unavailable; semantic regex fallback will be limited")

        if has_available:
            try:
                has_entities: list[Entity] = []
                chunks = self._build_has_candidate_chunks(text)
                if chunks:
                    # 有界并行：并发度与 HaS type-batch 扇出共用同一配置；
                    # 单 chunk 失败只降级该 chunk，不丢其余已识别实体。
                    chunk_sem = asyncio.Semaphore(
                        max(1, int(settings.HAS_NER_MAX_PARALLEL_REQUESTS))
                    )

                    async def run_chunk(chunk: str) -> list[Entity]:
                        async with chunk_sem:
                            return await self._extract_has_chunk_entities(
                                chunk,
                                text,
                                semantic_entity_types,
                                enabled_type_ids,
                            )

                    chunk_results = await asyncio.gather(
                        *(run_chunk(chunk) for chunk in chunks),
                        return_exceptions=True,
                    )
                    for chunk_result in chunk_results:
                        if isinstance(chunk_result, BaseException):
                            logger.warning("  HaS chunk failed: %s", chunk_result)
                            continue
                        has_entities.extend(chunk_result)
                else:
                    logger.info("  HaS NER skipped; no semantic candidate lines")
                all_entities.extend(has_entities)
                logger.info("  HaS NER found %d entities", len(has_entities))
            except Exception as e:
                logger.error("  HaS recognition failed: %s", e)

        custom_regex_types = self._select_custom_regex_types(entity_types)
        if custom_regex_types:
            logger.info("Stage 2: user-defined regex fallback...")
            regex_entities = self._custom_regex_extract(text, custom_regex_types)
            all_entities.extend(regex_entities)
            logger.info("  Custom regex found %d entities", len(regex_entities))
        else:
            logger.info("Stage 2: user-defined regex skipped")

        # Stage 3: 交叉验证 + 指代消解
        logger.info("Stage 3: validation and coreference...")
        validated_entities = self._cross_validate(all_entities, text, enabled_type_ids)
        logger.info("  Kept %d entities after validation", len(validated_entities))

        # Prometheus: NER 延迟 + 实体数
        from app.core.metrics import NER_DURATION, NER_ENTITY_COUNT
        NER_DURATION.labels(backend="hybrid").observe(_time.perf_counter() - _t0)
        NER_ENTITY_COUNT.observe(len(validated_entities))

        return validated_entities

    def _select_custom_regex_types(
        self,
        entity_types: list[EntityTypeConfig],
    ) -> list[EntityTypeConfig]:
        selected: list[EntityTypeConfig] = []
        for entity_type in entity_types:
            raw_type_id = str(getattr(entity_type, "id", "") or "").strip()
            pattern = str(getattr(entity_type, "regex_pattern", "") or "").strip()
            if not raw_type_id.lower().startswith("custom_") or not pattern:
                continue
            selected.append(entity_type)
        return selected

    def _custom_regex_extract(
        self,
        text: str,
        custom_regex_types: list[EntityTypeConfig],
    ) -> list[Entity]:
        entities: list[Entity] = []
        for entity_type in custom_regex_types:
            raw_type_id = str(getattr(entity_type, "id", "") or "").strip()
            pattern = str(getattr(entity_type, "regex_pattern", "") or "").strip()
            if not raw_type_id or not pattern:
                continue
            try:
                compiled = safe_compile(pattern, timeout=1.0)
                matches = safe_finditer(compiled, text, timeout=2.0)
            except (re.error, RegexTimeoutError) as exc:
                logger.warning("Custom regex skipped for %s: %s", raw_type_id, exc)
                continue
            for index, match in enumerate(matches):
                matched_text = match.group()
                if not matched_text:
                    continue
                entities.append(Entity(
                    id=f"regex_{raw_type_id}_{index}",
                    text=matched_text,
                    type=raw_type_id,
                    start=match.start(),
                    end=match.end(),
                    page=1,
                    confidence=0.96,
                    source="regex",
                ))
        return entities

    @staticmethod
    def _entity_name_candidates(name: str) -> list[str]:
        clean_name = str(name or "").strip()
        if not clean_name:
            return []
        parts = [p.strip() for p in re.split(r"[/／（）()\s]+", clean_name) if p.strip()]
        return [clean_name, *parts]

    def _select_has_semantic_types(
        self,
        entity_types: list[EntityTypeConfig],
    ) -> list[EntityTypeConfig]:
        """Select caller-enabled types that need HaS Text semantic inference."""
        selected = []
        seen_type_ids = set()
        for entity_type in entity_types:
            if not bool(getattr(entity_type, "use_llm", True)):
                continue
            raw_type_id = str(getattr(entity_type, "id", "") or "").strip()
            type_id = canonical_type_id(raw_type_id)
            if not type_id:
                continue
            has_regex = bool(getattr(entity_type, "regex_pattern", None))
            is_custom = raw_type_id.lower().startswith("custom_") or type_id.startswith("CUSTOM_")
            should_send_to_has = (
                type_id in self.HAS_SEMANTIC_TYPE_IDS
                or is_custom
                or not has_regex
            )
            if not should_send_to_has or type_id in seen_type_ids:
                continue
            selected.append(SimpleNamespace(
                id=raw_type_id if is_custom and raw_type_id else type_id,
                name=getattr(entity_type, "name", type_id),
                description=getattr(entity_type, "description", None),
                examples=getattr(entity_type, "examples", []),
                use_llm=getattr(entity_type, "use_llm", True),
            ))
            seen_type_ids.add(type_id)
        return selected

    async def _extract_has_chunk_entities(
        self,
        chunk: _HaSChunk,
        full_text: str,
        semantic_entity_types: list[EntityTypeConfig],
        enabled_type_ids: set[str],
    ) -> list[Entity]:
        chunk_entities = await self.has_service.extract_entities(
            chunk.text,
            semantic_entity_types,
        )
        relocated = self._relocate_has_entities(chunk_entities, full_text, chunk)
        filtered = [
            entity
            for entity in relocated
            if canonical_type_id(getattr(entity, "type", None)) in enabled_type_ids
        ]
        return filtered

    def _build_has_candidate_chunks(self, text: str) -> list[_HaSChunk]:
        """Build short semantic candidate chunks for HaS Text.

        The goal is to keep HaS inside its small context window while preserving
        the lines where semantic PII normally lives: names, organizations,
        addresses and work units.
        """
        candidate_lines: list[tuple[str, int]] = []
        seen: set[str] = set()
        search_from = 0

        def add_line(line: str) -> None:
            nonlocal search_from
            line = re.sub(r"\s+", " ", line).strip()
            if not line or line in seen:
                return
            if len(line) > self.MAX_HAS_LINE_CHARS:
                line = line[: self.MAX_HAS_LINE_CHARS].rstrip()
            if line:
                offset = text.find(line, search_from)
                if offset < 0:
                    offset = text.find(line)
                if offset >= 0:
                    search_from = offset + len(line)
                seen.add(line)
                candidate_lines.append((line, offset))

        for raw_line in self._iter_semantic_lines(text):
            line = raw_line.strip()
            if not line:
                continue
            add_line(line)

        chunks: list[_HaSChunk] = []
        current: list[str] = []
        current_offsets: list[int] = []
        current_len = 0
        for line, offset in candidate_lines:
            line_len = len(line) + 1
            if current and current_len + line_len > self.MAX_HAS_TEXT_CHARS:
                chunks.append(_HaSChunk(text="\n".join(current), line_offsets=tuple(current_offsets)))
                current = []
                current_offsets = []
                current_len = 0
                if len(chunks) >= self.MAX_HAS_CHUNKS:
                    break
            current.append(line)
            current_offsets.append(offset)
            current_len += line_len
        if current and len(chunks) < self.MAX_HAS_CHUNKS:
            chunks.append(_HaSChunk(text="\n".join(current), line_offsets=tuple(current_offsets)))

        logger.info(
            "  HaS semantic candidates: %d lines, %d chunks, %d chars",
            len(candidate_lines),
            len(chunks),
            sum(len(chunk.text) for chunk in chunks),
        )
        if chunks and len(chunks) >= self.MAX_HAS_CHUNKS and current_len == 0:
            logger.warning(
                "  HaS semantic candidate chunks reached limit %d; later candidate lines may be skipped",
                self.MAX_HAS_CHUNKS,
            )
        return chunks

    def _relocate_has_entities(
        self,
        entities: list[Entity],
        full_text: str,
        chunk: _HaSChunk,
    ) -> list[Entity]:
        """Move HaS chunk-local offsets back to original document offsets."""
        line_starts = [0]
        for index, char in enumerate(chunk.text):
            if char == "\n":
                line_starts.append(index + 1)

        relocated: list[Entity] = []
        for entity in entities:
            text = str(entity.text or "")
            if not text:
                continue
            found = -1
            local_start = int(getattr(entity, "start", -1) or -1)
            if 0 <= local_start < len(chunk.text):
                line_index = 0
                for idx, line_start in enumerate(line_starts):
                    if line_start > local_start:
                        break
                    line_index = idx
                if line_index < len(chunk.line_offsets):
                    line_offset = chunk.line_offsets[line_index]
                    local_line_start = line_starts[line_index]
                    candidate = line_offset + (local_start - local_line_start)
                    if (
                        line_offset >= 0
                        and 0 <= candidate <= len(full_text) - len(text)
                        and full_text[candidate:candidate + len(text)] == text
                    ):
                        found = candidate
            for line_offset in chunk.line_offsets:
                if found >= 0:
                    break
                if line_offset < 0:
                    continue
                found = full_text.find(text, line_offset, min(len(full_text), line_offset + self.MAX_HAS_LINE_CHARS + len(text)))
                if found >= 0:
                    break
            if found < 0:
                found = full_text.find(text)
            if found >= 0:
                entity.start = found
                entity.end = found + len(text)
            relocated.append(entity)
        return relocated

    def _iter_semantic_lines(self, text: str):
        """Yield paragraph-like units; split long OCR/text runs by punctuation."""
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        for paragraph in normalized.split("\n"):
            paragraph = paragraph.strip()
            if not paragraph:
                continue
            if len(paragraph) <= self.MAX_HAS_LINE_CHARS * 2:
                yield paragraph
                continue
            for part in re.split(r"(?<=[。；;])\s*", paragraph):
                part = part.strip()
                if part:
                    yield part

    def _semantic_structure_score(self, line: str) -> int:
        chinese_chars = sum(1 for char in line if "\u4e00" <= char <= "\u9fff")
        if chinese_chars < 2:
            return 0

        score = 0
        if any(hint in line for hint in self.SEMANTIC_ORG_SUFFIX_HINTS):
            score += 2
        if any(hint in line for hint in self.SEMANTIC_ADDRESS_HINTS):
            score += 1
        if any(hint in line for hint in self.SEMANTIC_ROLE_LABEL_HINTS) and (":" in line or "\uff1a" in line):
            score += 2
        return score


    def _cross_validate(
        self,
        entities: list[Entity],
        text: str,
        enabled_type_ids: set[str] | None = None,
    ) -> list[Entity]:
        """Validate, deduplicate, and propagate confirmed mentions."""
        if not entities:
            return []
        enabled_type_ids = enabled_type_ids or set()

        # 1. 验证实体文本是否在原文中正确位置
        semantic_type_ids = self.HAS_SEMANTIC_TYPE_IDS
        entities = sorted(
            entities,
            key=lambda entity: (
                0 if entity.type in semantic_type_ids and entity.source in {"has", "llm"} else 1,
                entity.start,
                entity.end,
            ),
        )
        validated = []
        used_positions: set[tuple[int, int]] = set()
        for entity in entities:
            if 0 <= entity.start < entity.end <= len(text):
                actual_text = text[entity.start:entity.end]
                if actual_text == entity.text:
                    self._trim_entity_edge_punctuation(entity)
                    self._expand_entity_boundary_context(entity, text)
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
                    self._trim_entity_edge_punctuation(entity)
                    self._expand_entity_boundary_context(entity, text)
                    validated.append(entity)
                    used_positions.add((entity.start, entity.end))
                    break
                start_index = found + len(entity.text)

        # 2. 去重（优先保留高置信度与正则结果）
        def source_rank(source: str | None) -> int:
            order = {"regex": 3, "has": 2, "llm": 2, "manual": 1}
            return order.get(source or "", 0)

        def type_priority(entity_type: str | None) -> int:
            canonical = canonical_type_id(str(entity_type or ""))
            if canonical.lower().startswith("custom_"):
                return 4
            # Prefer the most specific L3 label when HaS returns multiple
            # labels for the same span. L1/L2 metadata is not sent as NER tags,
            # so this is the final schema-boundary arbitration point.
            priority = {
                "BIRTH_DATE": 4,
                "GENDER": 4,
                "ETHNICITY": 4,
                "DOCUMENT_NUMBER": 4,
                "LICENSE_PLATE": 4,
                "ADDRESS": 3,
                "ORG": 2,
                "PERSON": 2,
                "LEGAL_PARTY": 2,
                "LAWYER": 2,
                "JUDGE": 2,
                "DATE": 1,
                "AGE": 1,
                "TIME": 1,
                "MARITAL_STATUS": 1,
                "NATIONALITY": 1,
                "VIN": 1,
            }
            return priority.get(canonical, 1)

        entity_map: dict[tuple, Entity] = {}
        for entity in validated:
            key = (entity.start, entity.end)
            if key not in entity_map:
                entity_map[key] = entity
                continue
            existing = entity_map[key]
            if str(entity.type or "").lower().startswith("custom_") and not str(existing.type or "").lower().startswith("custom_"):
                entity_map[key] = entity
                continue
            if str(existing.type or "").lower().startswith("custom_") and not str(entity.type or "").lower().startswith("custom_"):
                continue
            if existing.type in self.HAS_SEMANTIC_TYPE_IDS and entity.type == existing.type:
                if entity.source in {"has", "llm"} and existing.source == "regex":
                    entity_map[key] = entity
                    continue
                if existing.source in {"has", "llm"} and entity.source == "regex":
                    continue
            if entity.confidence > existing.confidence:
                entity_map[key] = entity
            elif entity.confidence == existing.confidence:
                if source_rank(entity.source) > source_rank(existing.source):
                    entity_map[key] = entity
                elif source_rank(entity.source) == source_rank(existing.source):
                    if type_priority(entity.type) > type_priority(existing.type):
                        entity_map[key] = entity

        deduped = self._dedupe_conflicting_entities(list(entity_map.values()), type_priority, source_rank)

        self._normalize_overbroad_org_role_entities(deduped, text, enabled_type_ids)
        deduped.extend(self._propagate_confirmed_semantic_mentions(deduped, text))
        deduped.extend(self._infer_missing_org_alias_entities(deduped, text, enabled_type_ids))
        self._link_org_alias_corefs(deduped)

        # Assign the same coref id to repeated identical semantic text.
        text_type_to_coref: dict[tuple, str] = {}
        coref_counter = 0

        for entity in deduped:
            if entity.coref_id and entity.coref_id.startswith("<") and entity.coref_id.endswith(">"):
                continue
            key = (entity.coref_id or entity.text, entity.type)
            if key not in text_type_to_coref:
                coref_counter += 1
                text_type_to_coref[key] = f"coref_{coref_counter:03d}"
            entity.coref_id = text_type_to_coref[key]

        # 4. 按位置排序并重新分配ID
        deduped.sort(key=lambda e: e.start)
        for i, entity in enumerate(deduped):
            entity.id = f"entity_{i}"

        return deduped

    @classmethod
    def _trim_entity_edge_punctuation(cls, entity: Entity) -> None:
        value = str(entity.text or "")
        if not value:
            return
        leading = len(value) - len(value.lstrip(cls.ENTITY_EDGE_PUNCTUATION))
        trailing = len(value.rstrip(cls.ENTITY_EDGE_PUNCTUATION))
        if leading:
            entity.start += leading
        if trailing < len(value):
            entity.end -= len(value) - trailing
        entity.text = value.strip(cls.ENTITY_EDGE_PUNCTUATION)

    @staticmethod
    def _expand_entity_boundary_context(entity: Entity, text: str) -> None:
        """Keep paired document/case-number brackets inside the L3 entity."""
        entity_type = canonical_type_id(str(entity.type or ""))
        if entity_type not in {"DOCUMENT_NUMBER", "CASE_NUMBER"}:
            return
        if entity.start <= 0:
            return
        previous = text[entity.start - 1]
        if previous not in "（(":
            return
        value = str(entity.text or "")
        if "）" not in value and ")" not in value:
            return
        entity.start -= 1
        entity.text = previous + value

    @staticmethod
    def _dedupe_conflicting_entities(
        entities: list[Entity],
        type_priority,
        source_rank,
    ) -> list[Entity]:
        """Resolve model multi-label conflicts over the same or overlapping span."""
        if len(entities) <= 1:
            return entities

        def rank(entity: Entity) -> tuple:
            length = max(0, int(entity.end or 0) - int(entity.start or 0))
            return (
                type_priority(entity.type),
                source_rank(entity.source),
                float(entity.confidence or 0.0),
                -length,
            )

        sorted_entities = sorted(entities, key=lambda item: (item.start, item.end))
        clusters: list[list[Entity]] = []
        current: list[Entity] = []
        current_end = -1
        for entity in sorted_entities:
            if not current or entity.start < current_end:
                current.append(entity)
                current_end = max(current_end, entity.end)
                continue
            clusters.append(current)
            current = [entity]
            current_end = entity.end
        if current:
            clusters.append(current)

        selected: list[Entity] = []
        for cluster in clusters:
            if len(cluster) == 1:
                selected.extend(cluster)
                continue
            # If two model buckets describe the same characters (or one wraps
            # the other, e.g. birth date vs age phrase), keep the strongest L3.
            selected.append(max(cluster, key=rank))
        return selected

    def _propagate_confirmed_semantic_mentions(self, entities: list[Entity], text: str) -> list[Entity]:
        """Mark every exact occurrence of semantic values already confirmed by HaS."""
        existing_ranges = [(entity.start, entity.end) for entity in entities]
        propagated: list[Entity] = []

        for source_entity in entities:
            if source_entity.source not in {"has", "llm"}:
                continue
            if source_entity.type not in self.HAS_SEMANTIC_TYPE_IDS and not str(source_entity.type).lower().startswith("custom_"):
                continue
            value = str(source_entity.text or "").strip()
            if len(value) < 2:
                continue

            start = 0
            while True:
                pos = text.find(value, start)
                if pos < 0:
                    break
                end = pos + len(value)
                if not any(not (end <= s or pos >= e) for s, e in existing_ranges):
                    propagated.append(Entity(
                        id=f"has_propagated_{len(propagated)}",
                        text=value,
                        type=source_entity.type,
                        start=pos,
                        end=end,
                        page=getattr(source_entity, "page", 1),
                        confidence=min(float(getattr(source_entity, "confidence", 0.9)), 0.9),
                        source="has",
                        coref_id=source_entity.coref_id or f"semantic:{source_entity.type}:{value}",
                    ))
                    existing_ranges.append((pos, end))
                start = end

        return propagated

    def _normalize_overbroad_org_role_entities(
        self,
        entities: list[Entity],
        text: str,
        enabled_type_ids: set[str],
    ) -> None:
        """Trim organization-like spans such as "某公司员工" to "某公司".

        This is a schema-boundary normalization, not a case-specific repair:
        the generic schema needs the organization name as its own atom so later
        redaction and coreference are stable.
        """
        for entity in entities:
            current_type = canonical_type_id(getattr(entity, "type", ""))
            if not self._is_org_like_type(current_type):
                continue
            if entity.source not in {"has", "llm"}:
                continue
            value = str(entity.text or "").strip()
            split = self._split_org_role_text(value, enabled_type_ids)
            if not split:
                continue
            org_text, _role_text = split
            org_start = entity.start
            org_end = org_start + len(org_text)
            if org_start < 0 or org_end > len(text):
                continue
            if text[org_start:org_end] != org_text:
                continue

            entity.text = org_text
            entity.type = current_type
            entity.end = org_end
            entity.confidence = min(float(getattr(entity, "confidence", 0.9)), 0.9)

    @classmethod
    def _split_org_role_text(
        cls,
        value: str,
        enabled_type_ids: set[str],
    ) -> tuple[str, str] | None:
        compact = cls._compact_org_name(value)
        if len(compact) < 4:
            return None

        for suffix in sorted(cls.ORG_BOUNDARY_SUFFIXES, key=len, reverse=True):
            boundary = compact.rfind(suffix)
            if boundary < 0:
                continue
            split_at = boundary + len(suffix)
            if split_at >= len(compact):
                continue
            role_text = compact[split_at:]
            if role_text not in cls.ORG_ROLE_SUFFIXES:
                continue
            org_text = compact[:split_at]
            if len(org_text) < 3:
                continue
            return org_text, role_text
        return None

    def _infer_missing_org_alias_entities(
        self,
        entities: list[Entity],
        text: str,
        enabled_type_ids: set[str],
    ) -> list[Entity]:
        existing_ranges = [(entity.start, entity.end) for entity in entities]
        inferred: list[Entity] = []

        for canonical in entities:
            canonical_type = canonical_type_id(getattr(canonical, "type", ""))
            if not self._is_org_like_type(canonical_type) or canonical.source not in {"has", "llm"}:
                continue
            if canonical_type not in enabled_type_ids:
                continue
            for alias_text in self._org_alias_candidates(canonical.text):
                start = 0
                while True:
                    pos = text.find(alias_text, start)
                    if pos < 0:
                        break
                    end = pos + len(alias_text)
                    if not any(not (end <= s or pos >= e) for s, e in existing_ranges):
                        inferred.append(Entity(
                            id=f"has_alias_{len(inferred)}",
                            text=alias_text,
                            type=canonical_type,
                            start=pos,
                            end=end,
                            page=getattr(canonical, "page", 1),
                            confidence=min(float(getattr(canonical, "confidence", 0.9)), 0.9),
                            source="has",
                            coref_id=canonical.coref_id or f"org_alias:{canonical.text}",
                        ))
                        existing_ranges.append((pos, end))
                    start = end

        return inferred

    @classmethod
    def _org_alias_candidates(cls, org_text: str) -> list[str]:
        compact = cls._compact_org_name(org_text)
        if len(compact) < 6:
            return []

        candidates: list[str] = []
        for suffix in ("有限责任公司", "股份有限公司", "有限公司", "分公司", "公司", "集团", "医院", "银行", "支行"):
            if not compact.endswith(suffix):
                continue
            stem = compact[: -len(suffix)]
            stem = cls.ORG_REGION_PREFIX_RE.sub("", stem)
            while True:
                normalized = cls.ORG_GENERIC_STEM_RE.sub("", stem)
                if normalized == stem:
                    break
                stem = normalized
            if 2 <= len(stem) <= 8:
                candidates.append(f"{stem}{suffix}")
                if suffix in {"有限责任公司", "股份有限公司", "有限公司"}:
                    candidates.append(f"{stem}公司")

        seen: set[str] = set()
        return [
            candidate
            for candidate in candidates
            if candidate != compact and not (candidate in seen or seen.add(candidate))
        ]

    def _link_org_alias_corefs(self, entities: list[Entity]) -> None:
        orgs = [
            entity for entity in entities
            if self._is_org_like_type(getattr(entity, "type", "")) and entity.text
        ]
        if len(orgs) < 2:
            return

        canonical_orgs = sorted(orgs, key=lambda entity: len(entity.text), reverse=True)
        for alias in sorted(orgs, key=lambda entity: len(entity.text)):
            alias_key = self._org_alias_key(alias.text)
            if not alias_key:
                continue
            for canonical in canonical_orgs:
                if canonical is alias or len(canonical.text) <= len(alias.text):
                    continue
                canonical_key = self._org_alias_key(canonical.text)
                if not canonical_key:
                    continue
                if self._org_names_look_related(alias_key, canonical_key, alias.text, canonical.text):
                    shared_coref = canonical.coref_id or f"org_alias:{canonical.text}"
                    canonical.coref_id = shared_coref
                    alias.coref_id = shared_coref
                    break

    @staticmethod
    def _org_alias_key(text: str) -> str:
        compact = re.sub(r"\s+", "", str(text or ""))
        compact = compact.strip(" ，。；;、()（）[]【】")
        return _ORG_ALIAS_SUFFIX_RE.sub("", compact)

    @classmethod
    def _org_names_look_related(cls, alias_key: str, canonical_key: str, alias_text: str, canonical_text: str) -> bool:
        alias_family = cls._org_suffix_family(alias_text)
        canonical_family = cls._org_suffix_family(canonical_text)
        if alias_family and canonical_family and alias_family != canonical_family:
            return False

        if len(alias_key) >= 4 and alias_key in cls._compact_org_name(canonical_text):
            return True
        if len(alias_key) >= 2 and alias_key in canonical_key:
            return True

        alias_compare = cls._org_compare_key(alias_key)
        canonical_compare = cls._org_compare_key(canonical_key)
        if len(alias_compare) < 2 or len(canonical_compare) < 2:
            return False
        if alias_compare in canonical_compare:
            return True
        return cls._subsequence_ratio(alias_compare, canonical_compare) >= 0.8

    @staticmethod
    def _compact_org_name(text: str) -> str:
        return re.sub(r"\s+", "", str(text or "")).strip(" ，。；;、()（）[]【】")

    @staticmethod
    def _org_suffix_family(text: str) -> str | None:
        compact = HybridNERService._compact_org_name(text)
        if "法院" in compact or "检察院" in compact:
            return "judicial"
        if "医院" in compact:
            return "medical"
        if "律师事务所" in compact or compact.endswith("事务所"):
            return "law_firm"
        if "银行" in compact or "支行" in compact:
            return "bank"
        if "保险" in compact:
            return "insurance"
        if any(suffix in compact for suffix in ("公司", "集团", "有限", "股份")):
            return "company"
        return None

    @staticmethod
    def _org_compare_key(text: str) -> str:
        return _ORG_ALIAS_GENERIC_WORD_RE.sub("", HybridNERService._compact_org_name(text))

    @staticmethod
    def _subsequence_ratio(short_text: str, long_text: str) -> float:
        if not short_text:
            return 0.0
        cursor = 0
        matched = 0
        for ch in short_text:
            found = long_text.find(ch, cursor)
            if found < 0:
                continue
            matched += 1
            cursor = found + 1
        return matched / len(short_text)


# 全局服务实例
hybrid_ner_service = HybridNERService()


async def perform_hybrid_ner(
    content: str,
    entity_types: list[EntityTypeConfig],
) -> list[Entity]:
    """Run HaS-first NER with optional custom fallback."""
    return await hybrid_ner_service.extract(content, entity_types)
