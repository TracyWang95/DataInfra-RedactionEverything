"""
替换策略模块
管理不同的匿名化替换模式：SMART / MASK / CUSTOM / STRUCTURED
维护实体映射关系，确保同一实体在文档中的一致性
"""
import logging

from app.models.schemas import (
    Entity,
    EntityType,
    RedactionConfig,
    ReplacementMode,
)
from app.models.type_mapping import canonical_type_id

logger = logging.getLogger(__name__)

# 智能编号使用中文数字（零~十）的最大计数，超过则改用阿拉伯数字
MAX_CHINESE_NUMERAL = 10
# 结构化标签序号的零填充宽度，如 001
STRUCTURED_INDEX_WIDTH = 3

# 掩码模式：各类型触发部分掩码所需的最小文本长度，不足则整体掩码
MASK_MIN_LEN_PERSON = 2  # 人名：保留姓
MASK_MIN_LEN_PHONE = 11  # 电话：保留前3后4
MASK_MIN_LEN_ID_CARD = 18  # 身份证：保留前6后4
MASK_MIN_LEN_BANK_CARD = 16  # 银行卡：保留后4

# 掩码模式：明文保留的前缀/后缀字符数
MASK_KEEP_PREFIX_PHONE = 3  # 电话保留前3位
MASK_KEEP_SUFFIX_PHONE = 4  # 电话保留后4位
MASK_KEEP_PREFIX_ID_CARD = 6  # 身份证保留前6位
MASK_KEEP_SUFFIX_ID_CARD = 4  # 身份证保留后4位
MASK_KEEP_SUFFIX_BANK_CARD = 4  # 银行卡保留后4位


def _raw_entity_type_id(entity_type: object) -> str:
    return entity_type.value if isinstance(entity_type, EntityType) else str(entity_type)


def _type_key_for_entity(entity: Entity) -> str:
    raw_type = _raw_entity_type_id(entity.type).strip()
    if raw_type.lower().startswith("custom_"):
        return raw_type.lower()
    return canonical_type_id(raw_type)


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

    def set_custom_replacements(self, replacements: dict[str, str]):
        """设置自定义替换映射"""
        self.custom_replacements = replacements

    def get_replacement(self, entity: Entity) -> str:
        """
        获取实体的替换文本
        确保同一实体在整个文档中使用相同的替换
        """
        type_key = _type_key_for_entity(entity)
        # 使用兼容的 coref_id 作为主键以保持指代一致；模型误标的结构化标签不参与映射复用。
        entity_key = self._coref_key_for_entity(entity, type_key)
        if entity_key in self._coref_map:
            replacement = self._coref_map[entity_key]
            if entity.text not in self.entity_map:
                self.entity_map[entity.text] = replacement
            return replacement

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
        type_key = _type_key_for_entity(entity)

        # 获取计数器
        if type_key not in self.type_counters:
            self.type_counters[type_key] = 0
        self.type_counters[type_key] += 1
        count = self.type_counters[type_key]

        # 根据类型生成替换文本（使用统一映射）
        from app.models.type_mapping import id_to_label
        label = self._get_type_label(type_key) or id_to_label(type_key)

        # 使用中文数字编号
        chinese_nums = ["零", "一", "二", "三", "四", "五", "六", "七", "八", "九", "十"]
        if count <= MAX_CHINESE_NUMERAL:
            num_str = chinese_nums[count]
        else:
            num_str = str(count)

        return f"[{label}{num_str}]"

    def _generate_mask_replacement(self, entity: Entity) -> str:
        """生成掩码替换文本"""
        text = entity.text
        length = len(text)
        type_key = _type_key_for_entity(entity)

        if type_key == "PERSON":
            # 人名：保留姓，其他用 *
            if length >= MASK_MIN_LEN_PERSON:
                return text[0] + "*" * (length - 1)
            return "*"

        elif type_key == "PHONE":
            # 电话：保留前3后4
            if length >= MASK_MIN_LEN_PHONE:
                return text[:MASK_KEEP_PREFIX_PHONE] + "****" + text[-MASK_KEEP_SUFFIX_PHONE:]
            return "*" * length

        elif type_key == "ID_CARD":
            # 身份证：保留前6后4
            if length >= MASK_MIN_LEN_ID_CARD:
                return text[:MASK_KEEP_PREFIX_ID_CARD] + "********" + text[-MASK_KEEP_SUFFIX_ID_CARD:]
            return "*" * length

        elif type_key == "BANK_CARD":
            # 银行卡：保留后4
            if length >= MASK_MIN_LEN_BANK_CARD:
                return "*" * (length - MASK_KEEP_SUFFIX_BANK_CARD) + text[-MASK_KEEP_SUFFIX_BANK_CARD:]
            return "*" * length

        else:
            # 其他：全部用 *
            return "*" * length

    def _generate_structured_replacement(self, entity: Entity) -> str:
        """生成结构化语义标签"""
        type_key = _type_key_for_entity(entity)

        template = self._get_tag_template(type_key)
        if template:
            if type_key not in self.type_counters:
                self.type_counters[type_key] = 0
            self.type_counters[type_key] += 1
            index = self.type_counters[type_key]
            return template.replace("{index}", f"{index:0{STRUCTURED_INDEX_WIDTH}d}")

        structured_map = {
            "PERSON": ("人物", "个人.姓名"),
            "ORG": ("组织", "企业.完整名称"),
            "ADDRESS": ("地点", "办公地址.完整地址"),
            "PHONE": ("电话", "固定电话.号码"),
            "ID_CARD": ("编号", "身份证.号码"),
            "BANK_CARD": ("编号", "银行卡.号码"),
            "CASE_NUMBER": ("编号", "案件编号.号码"),
            "DOCUMENT_NUMBER": ("编号", "文书编号.号码"),
            "BIRTH_DATE": ("日期/时间", "出生日期.年月日"),
            "DATE": ("日期/时间", "具体日期.年月日"),
            "AMOUNT": ("金额", "合同金额.数值"),
            "EMAIL": ("邮箱", "个人邮箱.地址"),
            "LICENSE_PLATE": ("编号", "车牌.号码"),
            "CONTRACT_NO": ("编号", "业务编号.代码"),
        }

        if type_key not in self.type_counters:
            self.type_counters[type_key] = 0
        self.type_counters[type_key] += 1
        index = self.type_counters[type_key]

        if type_key.lower().startswith("custom_"):
            # The item's explicit tag_template (EntityTypeConfig, always set by
            # normalize_custom_entity_type) is consumed earlier and returns
            # before reaching here; this is the config-missing fallback. The
            # old cn_terms name-guess ("a custom item NAMED 住址 probably wants
            # the ADDRESS template") was a closed-set lexical guess — gone.
            label = self._get_type_label(type_key) or type_key
            return f"<{label}[{index:0{STRUCTURED_INDEX_WIDTH}d}].完整值>"

        type_name = structured_map.get(type_key)
        if type_name:
            category, path = type_name
            return f"<{category}[{index:0{STRUCTURED_INDEX_WIDTH}d}].{path}>"

        # 自定义或未知类型兜底
        label = self._get_type_label(type_key) or type_key
        return f"<{label}[{index:0{STRUCTURED_INDEX_WIDTH}d}].完整名称>"

    def _get_tag_template(self, type_key: str) -> str | None:
        try:
            from app.services.entity_type_service import entity_types_db
            cfg = entity_types_db.get(type_key)
            if cfg and getattr(cfg, "tag_template", None):
                return cfg.tag_template
        except (ImportError, KeyError, AttributeError):
            return None
        return None

    def _get_type_label(self, type_key: str) -> str | None:
        cfg = self._get_type_config(type_key)
        name = str(getattr(cfg, "name", "") or "").strip() if cfg else ""
        return name or None

    def _get_type_config(self, type_key: str):
        try:
            from app.services.entity_type_service import entity_types_db
            return entity_types_db.get(type_key)
        except (ImportError, KeyError, AttributeError):
            return None

    def _coref_key_for_entity(self, entity: Entity, type_key: str) -> str:
        coref_id = entity.coref_id
        if not coref_id:
            return entity.text
        if coref_id.startswith("<") and coref_id.endswith(">"):
            if self._is_structured_tag_compatible(type_key, coref_id):
                return coref_id
            return f"{type_key}:{coref_id}"
        return coref_id

    @staticmethod
    def _is_structured_tag_compatible(type_key: str, tag: str) -> bool:
        tag_head = tag[1:].split("[", 1)[0]
        compatible_heads = {
            "PERSON": {"人名", "人物", "自然人"},
            "ORG": {"组织", "机构", "机构信息", "单位"},
            "ADDRESS": {"地址", "地点", "地理位置"},
            "ID_CARD": {"证件", "证件号码", "身份证", "编号"},
            "BANK_CARD": {"银行卡", "金融账户", "编号"},
            "BANK_ACCOUNT": {"金融账户", "银行账号", "账号", "编号"},
            "CASE_NUMBER": {"案件", "案件信息", "案号", "编号"},
            "DOCUMENT_NUMBER": {"文书编号", "法律文书号", "案号", "编号"},
            "BIRTH_DATE": {"出生日期", "生日", "日期", "日期/时间"},
            "DATE": {"时间", "时间信息", "日期", "日期/时间"},
            "AMOUNT": {"财务信息", "金额"},
            "LICENSE_PLATE": {"车辆信息", "车牌", "编号"},
            "PHONE": {"电话", "联系方式"},
            "EMAIL": {"邮箱", "邮件"},
        }
        if type_key not in compatible_heads:
            return False
        return tag_head in compatible_heads[type_key]


def build_preview_entity_map(entities: list[Entity], config: RedactionConfig) -> dict[str, str]:
    """
    计算与 execute 一致的「原文 -> 替换」映射，不落盘、不写文件。
    供批量向导第 4 步与单文件处理一致的三列预览。
    """
    context = RedactionContext(config.replacement_mode)
    context.set_custom_replacements(dict(config.custom_replacements or {}))
    for entity in entities:
        if entity.selected:
            context.get_replacement(entity)
    return dict(context.entity_map)
