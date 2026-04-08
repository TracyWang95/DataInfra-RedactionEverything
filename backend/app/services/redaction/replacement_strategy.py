"""
替换策略模块
管理不同的匿名化替换模式：SMART / MASK / CUSTOM / STRUCTURED
维护实体映射关系，确保同一实体在文档中的一致性
"""
import logging
from typing import Optional, Dict

from app.models.schemas import (
    Entity,
    RedactionConfig,
    ReplacementMode,
    EntityType,
)

logger = logging.getLogger(__name__)


class RedactionContext:
    """
    匿名化上下文
    维护实体映射关系，确保同一实体在文档中的一致性
    """

    def __init__(self, mode: ReplacementMode):
        self.mode = mode
        self.entity_map: dict[str, str] = {}
        self._coref_map: dict[str, str] = {}
        self.type_counters: dict[str, int] = {}
        self.custom_replacements: dict[str, str] = {}
        self.structured_tag_map: dict[str, str] = {}

    def set_custom_replacements(self, replacements: dict[str, str]):
        """设置自定义替换映射"""
        self.custom_replacements = replacements

    def set_structured_mapping(self, mapping: dict[str, list[str]]):
        """设置结构化标签映射（tag -> 原文列表）"""
        for tag, values in mapping.items():
            for value in values:
                if value and value not in self.structured_tag_map:
                    self.structured_tag_map[value] = tag

    def get_replacement(self, entity: Entity) -> str:
        """
        获取实体的替换文本
        确保同一实体在整个文档中使用相同的替换
        """
        # 使用 coref_id 作为主键以保持指代一致
        entity_key = entity.coref_id or entity.text
        if entity_key in self._coref_map:
            return self._coref_map[entity_key]

        # 根据模式生成替换文本
        if self.mode == ReplacementMode.CUSTOM:
            # 自定义模式：使用预设的替换
            replacement = self.custom_replacements.get(
                entity.text,
                entity.replacement or self._generate_smart_replacement(entity)
            )
        elif self.mode == ReplacementMode.MASK:
            # 掩码模式
            replacement = self._generate_mask_replacement(entity)
        elif self.mode == ReplacementMode.STRUCTURED:
            # 结构化语义标签
            replacement = self._generate_structured_replacement(entity)
        else:
            # 智能模式
            replacement = self._generate_smart_replacement(entity)

        self._coref_map[entity_key] = replacement
        if entity.text not in self.entity_map:
            self.entity_map[entity.text] = replacement
        return replacement

    def _generate_smart_replacement(self, entity: Entity) -> str:
        """生成智能替换文本"""
        entity_type = entity.type
        type_key = entity_type.value if isinstance(entity_type, EntityType) else str(entity_type)

        # 获取计数器
        if type_key not in self.type_counters:
            self.type_counters[type_key] = 0
        self.type_counters[type_key] += 1
        count = self.type_counters[type_key]

        # 根据类型生成替换文本（使用统一映射）
        from app.models.type_mapping import id_to_label
        label = id_to_label(type_key)

        # 使用中文数字编号
        chinese_nums = ["零", "一", "二", "三", "四", "五", "六", "七", "八", "九", "十"]
        if count <= 10:
            num_str = chinese_nums[count]
        else:
            num_str = str(count)

        return f"[{label}{num_str}]"

    def _generate_mask_replacement(self, entity: Entity) -> str:
        """生成掩码替换文本"""
        text = entity.text
        length = len(text)
        type_key = entity.type.value if isinstance(entity.type, EntityType) else str(entity.type)

        if type_key == "PERSON":
            # 人名：保留姓，其他用 *
            if length >= 2:
                return text[0] + "*" * (length - 1)
            return "*"

        elif type_key == "PHONE":
            # 电话：保留前3后4
            if length >= 11:
                return text[:3] + "****" + text[-4:]
            return "*" * length

        elif type_key == "ID_CARD":
            # 身份证：保留前6后4
            if length >= 18:
                return text[:6] + "********" + text[-4:]
            return "*" * length

        elif type_key == "BANK_CARD":
            # 银行卡：保留后4
            if length >= 16:
                return "*" * (length - 4) + text[-4:]
            return "*" * length

        else:
            # 其他：全部用 *
            return "*" * length

    def _generate_structured_replacement(self, entity: Entity) -> str:
        """生成结构化语义标签"""
        type_key = entity.type.value if isinstance(entity.type, EntityType) else str(entity.type)

        if entity.coref_id and entity.coref_id.startswith("<") and entity.coref_id.endswith(">"):
            return entity.coref_id

        if entity.text in self.structured_tag_map:
            return self.structured_tag_map[entity.text]

        template = self._get_tag_template(type_key)
        if template:
            if type_key not in self.type_counters:
                self.type_counters[type_key] = 0
            self.type_counters[type_key] += 1
            index = self.type_counters[type_key]
            return template.replace("{index}", f"{index:03d}")

        structured_map = {
            "PERSON": ("人物", "个人.姓名"),
            "ORG": ("组织", "企业.完整名称"),
            "ADDRESS": ("地点", "办公地址.完整地址"),
            "PHONE": ("电话", "固定电话.号码"),
            "ID_CARD": ("编号", "身份证.号码"),
            "BANK_CARD": ("编号", "银行卡.号码"),
            "CASE_NUMBER": ("编号", "案件编号.号码"),
            "DATE": ("日期/时间", "具体日期.年月日"),
            "MONEY": ("金额", "合同金额.数值"),
            "AMOUNT": ("金额", "合同金额.数值"),
            "EMAIL": ("邮箱", "个人邮箱.地址"),
            "LICENSE_PLATE": ("编号", "车牌.号码"),
            "CONTRACT_NO": ("编号", "合同编号.代码"),
        }

        if type_key not in self.type_counters:
            self.type_counters[type_key] = 0
        self.type_counters[type_key] += 1
        index = self.type_counters[type_key]

        type_name = structured_map.get(type_key)
        if type_name:
            category, path = type_name
            return f"<{category}[{index:03d}].{path}>"

        # 自定义或未知类型兜底
        label = type_key
        return f"<{label}[{index:03d}].完整名称>"

    def _get_tag_template(self, type_key: str) -> Optional[str]:
        try:
            from app.services.entity_type_service import entity_types_db
            cfg = entity_types_db.get(type_key)
            if cfg and getattr(cfg, "tag_template", None):
                return cfg.tag_template
        except (ImportError, KeyError, AttributeError):
            return None
        return None


def build_preview_entity_map(entities: list[Entity], config: RedactionConfig) -> Dict[str, str]:
    """
    计算与 execute 一致的「原文 -> 替换」映射，不落盘、不写文件。
    供批量向导第 4 步与 Playground 一致的三列预览。
    """
    context = RedactionContext(config.replacement_mode)
    context.set_custom_replacements(dict(config.custom_replacements or {}))
    for entity in entities:
        if entity.selected:
            context.get_replacement(entity)
    return dict(context.entity_map)
