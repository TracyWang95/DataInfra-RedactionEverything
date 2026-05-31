"""
实体类型管理 — 业务逻辑层
基于 GB/T 37964-2019《信息安全技术 个人信息去标识化指南》国家标准设计
"""

from __future__ import annotations

import os as _os
import re
import uuid

from pydantic import BaseModel, Field, model_validator

from app.core.config import settings
from app.core.persistence import load_json, save_json
from app.core.safe_regex import RegexTimeoutError, safe_compile, safe_finditer
from app.core.tenant_config import tenant_store_path
from app.models.type_mapping import TYPE_ID_ALIASES, canonical_type_id

# ── 数据模型 ──────────────────────────────────────────────

class EntityTypeConfig(BaseModel):
    """Entity type config using the maintained L1/L2/L3 taxonomy."""
    id: str = Field(..., description="Unique type id")
    name: str = Field(..., description="Display name")
    data_domain: str = Field(default="custom_extension", description="L1 data domain")
    generic_target: str | None = Field(default=None, description="L2 generic target for L3 types")
    entity_type_ids: list[str] = Field(default_factory=list, description="L3 entity types covered by a L2 generic target")
    linkage_groups: list[str] = Field(default_factory=list, description="Coreference/linkage capability groups")
    coref_enabled: bool = Field(default=False, description="Whether group-based coreference is enabled")
    default_enabled: bool = Field(default=False, description="Whether selected by the generic default")
    description: str | None = Field(None, description="Semantic guidance for model recognition")
    examples: list[str] = Field(default_factory=list, description="Example texts")
    color: str = Field(default="#6B7280", description="Display color")
    regex_pattern: str | None = Field(None, description="Optional regex fallback")
    use_llm: bool = Field(default=True, description="Whether semantic recognition is enabled")
    enabled: bool = Field(default=True, description="Whether the type is enabled")
    order: int = Field(default=100, description="Sort order")
    tag_template: str | None = Field(None, description="Structured replacement tag template")


class EntityTypesResponse(BaseModel):
    """实体类型列表响应"""
    custom_types: list[EntityTypeConfig]
    total: int
    page: int = 1
    page_size: int = 50


class TextTaxonomyTarget(BaseModel):
    """L2 taxonomy target option for text custom L3 items."""
    value: str
    label: str


class TextTaxonomyDomain(BaseModel):
    """L1 taxonomy domain and its allowed L2 targets."""
    value: str
    label: str
    default_target: str
    targets: list[TextTaxonomyTarget]


class TextTaxonomyResponse(BaseModel):
    """Maintained L1/L2 taxonomy used to classify L3 text entity labels."""
    domains: list[TextTaxonomyDomain]


class CreateEntityTypeRequest(BaseModel):
    """创建实体类型请求"""
    name: str
    description: str | None = None
    examples: list[str] = Field(default_factory=list)
    color: str = "#6B7280"
    regex_pattern: str | None = None
    use_llm: bool = True
    tag_template: str | None = None
    data_domain: str = "custom_extension"
    generic_target: str | None = None
    entity_type_ids: list[str] = Field(default_factory=list)
    linkage_groups: list[str] = Field(default_factory=list)
    coref_enabled: bool = True
    default_enabled: bool = False

    @model_validator(mode="after")
    def validate_required_taxonomy(self):
        if not str(self.data_domain or "").strip():
            raise ValueError("L1 数据域必填")
        if not str(self.generic_target or "").strip():
            raise ValueError("L2 通用识别项必填")
        return self


class UpdateEntityTypeRequest(BaseModel):
    """更新实体类型请求"""
    name: str | None = None
    description: str | None = None
    examples: list[str] | None = None
    color: str | None = None
    regex_pattern: str | None = None
    use_llm: bool | None = None
    enabled: bool | None = None
    order: int | None = None
    tag_template: str | None = None
    data_domain: str | None = None
    generic_target: str | None = None
    entity_type_ids: list[str] | None = None
    linkage_groups: list[str] | None = None
    coref_enabled: bool | None = None
    default_enabled: bool | None = None


class RegexTestRequest(BaseModel):
    pattern: str = Field(..., description="正则表达式")
    test_text: str = Field(..., description="测试文本")


class RegexTestResult(BaseModel):
    valid: bool = Field(..., description="正则表达式是否有效")
    matches: list[dict] = Field(default_factory=list, description="匹配结果列表")
    error: str = Field(default="", description="错误信息")


# ── 预置类型 ──────────────────────────────────────────────

_PRESET_JSON_PATH = _os.path.join(
    _os.path.dirname(__file__), "..", "..", "config", "preset_entity_types.json"
)
_raw_presets = load_json(_PRESET_JSON_PATH, default={})
PRESET_ENTITY_TYPES: dict[str, EntityTypeConfig] = {
    k: EntityTypeConfig(**v) for k, v in _raw_presets.items() if k not in TYPE_ID_ALIASES
}

def is_default_generic_entity_type_id(type_id: str) -> bool:
    """Return whether a type belongs to the broad generic default schema."""
    normalized = canonical_type_id(type_id)
    return bool(normalized) and not normalized.startswith("custom_")


TEXT_GENERIC_TARGETS_BY_DATA_DOMAIN: dict[str, tuple[str, ...]] = {
    "pii": (
        "GEN_PERSON_SUBJECT",
        "GEN_NAME",
        "GEN_NUMBER_CODE",
        "GEN_CONTACT",
        "GEN_DATE_TIME",
        "GEN_ATTRIBUTE_STATUS",
    ),
    "organization_subject": (
        "GEN_ORGANIZATION_SUBJECT",
        "GEN_NAME",
        "GEN_NUMBER_CODE",
        "GEN_CONTACT",
        "GEN_ADDRESS_LOCATION",
    ),
    "account_transaction": (
        "GEN_ACCOUNT_TRANSACTION",
        "GEN_AMOUNT_VALUE",
        "GEN_NUMBER_CODE",
        "GEN_ORGANIZATION_SUBJECT",
        "GEN_ATTRIBUTE_STATUS",
    ),
    "address_location": ("GEN_ADDRESS_LOCATION",),
    "time_event": ("GEN_DATE_TIME",),
    "document_record": (
        "GEN_DOCUMENT_RECORD",
        "GEN_NUMBER_CODE",
        "GEN_DATE_TIME",
        "GEN_ORGANIZATION_SUBJECT",
    ),
    "asset_resource": ("GEN_ASSET_RESOURCE", "GEN_NAME", "GEN_NUMBER_CODE"),
    "credential_access": ("GEN_CREDENTIAL_ACCESS",),
    "custom_extension": (
        "GEN_DOCUMENT_RECORD",
        "GEN_NAME",
        "GEN_NUMBER_CODE",
        "GEN_ATTRIBUTE_STATUS",
    ),
}

TEXT_DATA_DOMAIN_LABELS: dict[str, str] = {
    "pii": "个人信息",
    "organization_subject": "组织主体信息",
    "account_transaction": "账户与交易信息",
    "address_location": "地址位置空间信息",
    "time_event": "时间事件信息",
    "document_record": "文档内容与业务记录",
    "asset_resource": "资产资源与标的物",
    "credential_access": "凭证密钥与访问控制",
    "custom_extension": "其他文本",
}

TEXT_GENERIC_TARGET_LABELS: dict[tuple[str, str], str] = {
    ("pii", "GEN_PERSON_SUBJECT"): "人员主体",
    ("pii", "GEN_NAME"): "姓名/称谓",
    ("pii", "GEN_NUMBER_CODE"): "个人证件号/编号",
    ("pii", "GEN_CONTACT"): "联系方式",
    ("pii", "GEN_DATE_TIME"): "个人日期时间",
    ("pii", "GEN_ATTRIBUTE_STATUS"): "个人属性状态",
    ("organization_subject", "GEN_ORGANIZATION_SUBJECT"): "组织/机构主体",
    ("organization_subject", "GEN_NAME"): "组织名称/简称",
    ("organization_subject", "GEN_NUMBER_CODE"): "组织编号/代码",
    ("organization_subject", "GEN_CONTACT"): "组织联系方式",
    ("organization_subject", "GEN_ADDRESS_LOCATION"): "组织地址位置",
    ("account_transaction", "GEN_ACCOUNT_TRANSACTION"): "账户/交易/流水",
    ("account_transaction", "GEN_AMOUNT_VALUE"): "金额/数值",
    ("account_transaction", "GEN_NUMBER_CODE"): "交易编号/业务代码",
    ("account_transaction", "GEN_ORGANIZATION_SUBJECT"): "交易相关机构",
    ("account_transaction", "GEN_ATTRIBUTE_STATUS"): "交易属性/风险状态",
    ("address_location", "GEN_ADDRESS_LOCATION"): "地址/位置/空间范围",
    ("time_event", "GEN_DATE_TIME"): "日期/时间/期间",
    ("document_record", "GEN_DOCUMENT_RECORD"): "文档/记录/事项",
    ("document_record", "GEN_NUMBER_CODE"): "文书编号/记录编号",
    ("document_record", "GEN_DATE_TIME"): "文档日期/业务时间",
    ("document_record", "GEN_ORGANIZATION_SUBJECT"): "文档相关机构",
    ("asset_resource", "GEN_ASSET_RESOURCE"): "资产/资源/标的物",
    ("asset_resource", "GEN_NAME"): "资产名称",
    ("asset_resource", "GEN_NUMBER_CODE"): "资产编号/资源代码",
    ("credential_access", "GEN_CREDENTIAL_ACCESS"): "凭证/密钥/访问控制",
    ("custom_extension", "GEN_DOCUMENT_RECORD"): "其他文本记录",
    ("custom_extension", "GEN_NAME"): "其他名称",
    ("custom_extension", "GEN_NUMBER_CODE"): "其他号码/编号",
    ("custom_extension", "GEN_ATTRIBUTE_STATUS"): "其他属性/状态",
}

DEFAULT_GENERIC_TARGET_BY_DATA_DOMAIN: dict[str, str] = {
    data_domain: targets[0]
    for data_domain, targets in TEXT_GENERIC_TARGETS_BY_DATA_DOMAIN.items()
    if targets
}


def get_text_taxonomy() -> TextTaxonomyResponse:
    """Return the single source of truth for text L1/L2 metadata."""
    domains = []
    for data_domain, targets in TEXT_GENERIC_TARGETS_BY_DATA_DOMAIN.items():
        domains.append(TextTaxonomyDomain(
            value=data_domain,
            label=TEXT_DATA_DOMAIN_LABELS[data_domain],
            default_target=DEFAULT_GENERIC_TARGET_BY_DATA_DOMAIN[data_domain],
            targets=[
                TextTaxonomyTarget(
                    value=target,
                    label=TEXT_GENERIC_TARGET_LABELS.get((data_domain, target), target),
                )
                for target in targets
            ],
        ))
    return TextTaxonomyResponse(domains=domains)


def normalize_text_taxonomy(
    data_domain: str | None,
    generic_target: str | None,
) -> tuple[str, str]:
    """Normalize custom text L3 metadata to the maintained L1/L2 taxonomy."""
    domain = str(data_domain or "").strip()
    if domain not in TEXT_GENERIC_TARGETS_BY_DATA_DOMAIN:
        domain = "custom_extension"
    target = str(generic_target or "").strip()
    allowed_targets = TEXT_GENERIC_TARGETS_BY_DATA_DOMAIN[domain]
    if target not in allowed_targets:
        target = DEFAULT_GENERIC_TARGET_BY_DATA_DOMAIN[domain]
    return domain, target


LINKAGE_GROUPS_BY_GENERIC_TARGET: dict[str, set[str]] = {
    "GEN_PERSON_SUBJECT": {"person_like"},
    "GEN_ORGANIZATION_SUBJECT": {"organization_like"},
    "GEN_ACCOUNT_TRANSACTION": {"account_like", "organization_like"},
    "GEN_AMOUNT_VALUE": {"account_like"},
    "GEN_NUMBER_CODE": {"identifier_like"},
    "GEN_ADDRESS_LOCATION": {"address_like"},
    "GEN_DATE_TIME": {"date_like"},
    "GEN_CREDENTIAL_ACCESS": {"credential_like"},
}

LINKAGE_GROUPS_BY_DATA_DOMAIN: dict[str, set[str]] = {
    "pii": {"person_like"},
    "organization_subject": {"organization_like"},
    "account_transaction": {"account_like"},
    "address_location": {"address_like"},
    "time_event": {"date_like"},
    "credential_access": {"credential_like"},
}


def infer_linkage_groups(data_domain: str | None, generic_target: str | None) -> list[str]:
    """Infer coreference/disambiguation scope from L1/L2 taxonomy."""
    groups: set[str] = set()
    data_domain_value = str(data_domain or "").strip()
    generic_target_value = str(generic_target or "").strip()
    groups.update(LINKAGE_GROUPS_BY_DATA_DOMAIN.get(data_domain_value, set()))
    groups.update(LINKAGE_GROUPS_BY_GENERIC_TARGET.get(generic_target_value, set()))
    if generic_target_value == "GEN_NAME":
        if data_domain_value == "pii":
            groups.add("person_like")
        elif data_domain_value in {"organization_subject", "account_transaction"}:
            groups.add("organization_like")
    return sorted(groups)


def build_tag_template(name: str, tag_template: str | None = None) -> str:
    """Build the structured replacement tag for an L3 entity label."""
    explicit = str(tag_template or "").strip()
    if explicit:
        return explicit
    label = re.sub(r"\s+", "", str(name or "").strip())
    return f"<{label or '自定义项'}[{{index}}]>"


def normalize_custom_entity_type(config: EntityTypeConfig) -> EntityTypeConfig:
    """Keep custom L3 items model-driven and taxonomy-backed."""
    data_domain, generic_target = normalize_text_taxonomy(config.data_domain, config.generic_target)
    coref_enabled = bool(config.coref_enabled)
    return config.model_copy(update={
        "data_domain": data_domain,
        "generic_target": generic_target,
        "regex_pattern": None,
        "use_llm": True,
        "tag_template": build_tag_template(config.name, config.tag_template),
        "coref_enabled": coref_enabled,
        "linkage_groups": infer_linkage_groups(data_domain, generic_target) if coref_enabled else [],
    })


# ── 持久化 ────────────────────────────────────────────────

def _entity_types_store_path(owner_id: str | None = None) -> str:
    return tenant_store_path(owner_id, settings.ENTITY_TYPES_STORE_PATH, "entity_types.json")


def _default_entity_types() -> dict[str, EntityTypeConfig]:
    return {
        k: v.model_copy() if hasattr(v, "model_copy") else v
        for k, v in PRESET_ENTITY_TYPES.items()
    }


def _load_entity_types(owner_id: str | None = None) -> dict[str, EntityTypeConfig]:
    """Load entity types from disk, merging with presets."""
    raw = load_json(_entity_types_store_path(owner_id), default=None)
    if raw is None or not isinstance(raw, dict):
        return _default_entity_types()
    merged: dict[str, EntityTypeConfig] = {}
    for key, preset in PRESET_ENTITY_TYPES.items():
        if key in raw:
            try:
                loaded = EntityTypeConfig(**raw[key]) if isinstance(raw[key], dict) else preset
                # Built-in definitions are source-controlled. Preserve only the
                # user's enabled/disabled choice, so corrected regex/LLM/default
                # boundaries are not kept stale by old runtime snapshots.
                merged[key] = preset.model_copy(update={"enabled": loaded.enabled if preset.enabled else False})
            except Exception:
                merged[key] = preset
        else:
            merged[key] = preset
    for key, val in raw.items():
        if key in TYPE_ID_ALIASES:
            continue
        if key not in merged and str(key).startswith("custom_"):
            try:
                loaded = EntityTypeConfig(**val) if isinstance(val, dict) else val
                merged[key] = normalize_custom_entity_type(loaded)
            except Exception:
                pass
    return merged


def _persist_entity_types(
    db: dict[str, EntityTypeConfig] | None = None,
    owner_id: str | None = None,
) -> None:
    save_json(_entity_types_store_path(owner_id), db if db is not None else entity_types_db)


# 内存存储（启动时从磁盘恢复）
entity_types_db: dict[str, EntityTypeConfig] = _load_entity_types()
_persist_entity_types()


# ── 公共查询 ──────────────────────────────────────────────

def _db_for_owner(owner_id: str | None = None) -> dict[str, EntityTypeConfig]:
    return entity_types_db if owner_id is None else _load_entity_types(owner_id)


def get_enabled_types(owner_id: str | None = None) -> list[EntityTypeConfig]:
    """获取所有启用的实体类型"""
    db = _db_for_owner(owner_id)
    return [t for t in db.values() if t.enabled]


def get_default_generic_types(owner_id: str | None = None) -> list[EntityTypeConfig]:
    """获取通用默认配置中的启用实体类型。"""
    return [
        t
        for t in _db_for_owner(owner_id).values()
        if t.enabled and t.default_enabled and is_default_generic_entity_type_id(t.id)
    ]


def get_regex_types(owner_id: str | None = None) -> list[EntityTypeConfig]:
    """获取使用正则识别的类型"""
    db = _db_for_owner(owner_id)
    return [t for t in db.values() if t.enabled and t.regex_pattern]


def get_llm_types(owner_id: str | None = None) -> list[EntityTypeConfig]:
    """获取使用LLM识别的类型"""
    db = _db_for_owner(owner_id)
    return [t for t in db.values() if t.enabled and t.use_llm]


def resolve_requested_entity_types(
    entity_type_ids: list[str],
    owner_id: str | None = None,
) -> list[EntityTypeConfig]:
    """Resolve selected IDs exactly; custom items remain first-class NER tags."""
    db = _db_for_owner(owner_id)
    resolved: list[EntityTypeConfig] = []
    seen: set[str] = set()

    def add(type_config: EntityTypeConfig) -> None:
        final_id = type_config.id
        if final_id in seen:
            return
        seen.add(final_id)
        resolved.append(type_config)

    for raw_id in entity_type_ids:
        direct_id = str(raw_id or "").strip()
        if not direct_id:
            continue

        type_config = db.get(direct_id)
        if type_config is None:
            type_config = db.get(canonical_type_id(direct_id))
        if type_config is None:
            continue

        add(type_config)
    return resolved


# ── 业务方法 ──────────────────────────────────────────────

def list_types(
    enabled_only: bool = False,
    page: int = 1,
    page_size: int = 0,
    owner_id: str | None = None,
) -> EntityTypesResponse:
    types = list(_db_for_owner(owner_id).values())
    if enabled_only:
        types = [t for t in types if t.enabled]
    types.sort(key=lambda x: x.order)
    total = len(types)
    if page_size <= 0:
        return EntityTypesResponse(custom_types=types, total=total, page=1, page_size=total)
    start = (page - 1) * page_size
    page_items = types[start : start + page_size]
    return EntityTypesResponse(custom_types=page_items, total=total, page=page, page_size=page_size)


def get_type(type_id: str, owner_id: str | None = None) -> EntityTypeConfig | None:
    return _db_for_owner(owner_id).get(type_id)


def create_type(
    request: CreateEntityTypeRequest,
    owner_id: str | None = None,
) -> EntityTypeConfig:
    global entity_types_db
    db = _db_for_owner(owner_id)
    type_id = f"custom_{uuid.uuid4().hex[:8]}"
    coref_enabled = bool(request.coref_enabled)
    data_domain, generic_target = normalize_text_taxonomy(
        request.data_domain,
        request.generic_target,
    )
    new_type = EntityTypeConfig(
        id=type_id,
        name=request.name,
        data_domain=data_domain,
        generic_target=generic_target,
        entity_type_ids=request.entity_type_ids or [],
        linkage_groups=(
            infer_linkage_groups(data_domain, generic_target)
            if coref_enabled else []
        ),
        coref_enabled=coref_enabled,
        default_enabled=bool(request.default_enabled),
        description=request.description,
        examples=request.examples,
        color=request.color,
        regex_pattern=None,
        use_llm=True,
        tag_template=build_tag_template(request.name),
        enabled=True,
        order=200,
    )
    db[type_id] = new_type
    if owner_id is None:
        entity_types_db = db
    _persist_entity_types(db, owner_id)
    return new_type


def update_type(
    type_id: str,
    request: UpdateEntityTypeRequest,
    owner_id: str | None = None,
) -> EntityTypeConfig | None:
    global entity_types_db
    db = _db_for_owner(owner_id)
    if type_id not in db:
        return None
    if type_id in PRESET_ENTITY_TYPES:
        raise ValueError("系统默认配置项由预设清单维护，不能在界面中修改")
    if request.data_domain is not None and not str(request.data_domain or "").strip():
        raise ValueError("L1 数据域必填")
    if request.generic_target is not None and not str(request.generic_target or "").strip():
        raise ValueError("L2 通用识别项必填")
    existing = db[type_id]
    update_data = request.model_dump(exclude_unset=True)
    next_data_domain = update_data.get("data_domain", existing.data_domain)
    next_generic_target = update_data.get("generic_target", existing.generic_target)
    if not str(next_data_domain or "").strip():
        raise ValueError("L1 数据域必填")
    if not str(next_generic_target or "").strip():
        raise ValueError("L2 通用识别项必填")
    next_data_domain, next_generic_target = normalize_text_taxonomy(
        next_data_domain,
        next_generic_target,
    )
    update_data["data_domain"] = next_data_domain
    update_data["generic_target"] = next_generic_target
    next_coref_enabled = update_data.get("coref_enabled", existing.coref_enabled)
    update_data["linkage_groups"] = (
        infer_linkage_groups(next_data_domain, next_generic_target)
        if next_coref_enabled else []
    )
    update_data["regex_pattern"] = None
    update_data["use_llm"] = True
    if "name" in update_data or "tag_template" in update_data:
        next_name = update_data.get("name", existing.name)
        update_data["tag_template"] = build_tag_template(next_name)
    for key, value in update_data.items():
        setattr(existing, key, value)
    db[type_id] = existing
    if owner_id is None:
        entity_types_db = db
    _persist_entity_types(db, owner_id)
    return existing


def delete_type(type_id: str, owner_id: str | None = None) -> tuple[bool, str]:
    """
    Returns (success, error_message).
    success=True  -> deleted OK
    success=False -> error_message explains why
    """
    global entity_types_db
    db = _db_for_owner(owner_id)
    if type_id not in db:
        return False, "实体类型不存在"
    if type_id in PRESET_ENTITY_TYPES:
        return False, "预置类型不能删除，只能禁用"
    del db[type_id]
    if owner_id is None:
        entity_types_db = db
    _persist_entity_types(db, owner_id)
    return True, ""


def toggle_type(type_id: str, owner_id: str | None = None) -> bool | None:
    """Returns new enabled state, or None if not found."""
    global entity_types_db
    db = _db_for_owner(owner_id)
    if type_id not in db:
        return None
    db[type_id].enabled = not db[type_id].enabled
    if owner_id is None:
        entity_types_db = db
    _persist_entity_types(db, owner_id)
    return db[type_id].enabled


def reset_types(owner_id: str | None = None) -> None:
    global entity_types_db
    db = _default_entity_types()
    if owner_id is None:
        entity_types_db = db
    _persist_entity_types(db, owner_id)


def test_regex(pattern: str, test_text: str) -> RegexTestResult:
    try:
        compiled = safe_compile(pattern, timeout=1.0)
    except re.error:
        return RegexTestResult(valid=False, matches=[], error="正则语法错误")
    except RegexTimeoutError:
        return RegexTestResult(valid=False, matches=[], error="正则执行超时，请简化表达式")

    try:
        found = safe_finditer(compiled, test_text, timeout=1.0)
    except RegexTimeoutError:
        return RegexTestResult(valid=False, matches=[], error="正则匹配超时，请简化表达式")

    matches = []
    for m in found:
        matches.append({
            "text": m.group(),
            "start": m.start(),
            "end": m.end(),
            "groups": [],
        })
    return RegexTestResult(valid=True, matches=matches)

# ---------------------------------------------------------------------------
# Public accessor — use this instead of importing entity_types_db directly,
# so other layers don't couple to the module-level mutable dict.
# ---------------------------------------------------------------------------

def get_entity_types_db(owner_id: str | None = None) -> dict[str, EntityTypeConfig]:
    """Return the in-memory entity-types dictionary."""
    return _db_for_owner(owner_id)
