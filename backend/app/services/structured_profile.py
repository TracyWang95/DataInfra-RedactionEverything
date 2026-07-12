"""Column profiling, entity-type inference (rules + HaS semantics) and policy recommendation."""
from __future__ import annotations

import json
import logging
import re
import time
from collections import Counter
from datetime import UTC, datetime
from typing import Any

import httpx

from app.core.config import settings
from app.models.type_mapping import canonical_type_id
from app.services.structured_common import (
    MAX_PROFILE_ROWS,
    LoadedTable,
    cell_to_json,
    compact_text,
    infer_runtime_type,
    infer_shape_kind,
    normalize_value,
)
from app.services.structured_files import load_dataset_rows
from app.services.structured_store import StructuredStore, get_structured_store

logger = logging.getLogger(__name__)


_COLUMN_NAME_HINTS: list[tuple[str, str, str, float]] = [
    (r"(phone|mobile|tel|手机号|手机|电话|联系方式|联系电话)", "PHONE", "high", 0.95),
    (r"(email|mail|邮箱|电子邮件)", "EMAIL", "high", 0.95),
    (r"(id.?card|身份证|证件号|证件号码|identity)", "ID_CARD", "critical", 0.95),
    (r"(bank.?card|银行卡号|银行账号|账户|账号)", "BANK_CARD", "critical", 0.88),
    (r"(password|passwd|pwd|密码|口令)", "USERNAME_PASSWORD", "critical", 0.98),
    (r"(token|secret|key|api.?key|密钥|令牌|凭证)", "AUTH_SECRET", "critical", 0.96),
    (r"(company|corp|org|机构|公司|单位|供应商|客户|企业)", "ORG", "high", 0.86),
    (
        r"(^name$|full.?name|customer.?name|user.?name|receiver.?name|contact.?name|person.?name|"
        r"employee.?name|staff.?name|agent.?name|account.?name|payer.?name|payee.?name|owner.?name|"
        r"legal.?representative|姓名|联系人|客户名|用户名|收件人|经办人|代理人|负责人|开户名|账户名)",
        "PERSON",
        "high",
        0.72,
    ),
    (r"(address|addr|住址|地址|门牌|地区|省|市|区县)", "ADDRESS", "medium", 0.82),
    (r"(amount|price|money|salary|fee|金额|价格|单价|合计|余额|费用|收入|支出)", "AMOUNT", "medium", 0.82),
    (r"(date|time|created|updated|生日|出生|日期|时间)", "DATE", "medium", 0.72),
    (r"(ip地址|ip$|ip_|ipaddress)", "IP_ADDRESS", "medium", 0.92),
    (r"(mac地址|mac$|mac_)", "MAC_ADDRESS", "medium", 0.9),
    (r"(url|website|site|网址|链接)", "URL_WEBSITE", "medium", 0.88),
    (r"(license|plate|车牌)", "LICENSE_PLATE", "high", 0.84),
    (r"(contract|合同号|订单号|单据号|编号|流水号)", "DOCUMENT_NUMBER", "medium", 0.7),
]

_BUSINESS_DESCRIPTOR_COLUMN_PATTERNS = [
    re.compile(
        r"(^|[_\-\s])("
        r"product|sku|item|goods|commodity|material|device|equipment|model|brand|category|catalog|"
        r"spec|title|subject|project|service|package|plan|version|status|type|tier|memo|note|summary|"
        r"description|content"
        r")([_\-\s]|$)",
        re.I,
    ),
    re.compile(r"(产品|商品|物料|设备|装备|器材|型号|规格|品牌|类目|品类|标题|主题|项目|服务|套餐|方案|版本|状态|类型|等级|备注|摘要|描述|说明|内容)"),
]

_BUSINESS_DESCRIPTOR_BLOCK_TYPES = {
    "PERSON",
    "PHONE",
    "EMAIL",
    "ID_CARD",
    "BANK_CARD",
    "USERNAME_PASSWORD",
    "AUTH_SECRET",
    "ADDRESS",
    "IP_ADDRESS",
    "MAC_ADDRESS",
    "LICENSE_PLATE",
}

_VALUE_PATTERNS: list[tuple[re.Pattern[str], str, str, float]] = [
    (re.compile(r"^1[3-9]\d{9}$"), "PHONE", "high", 0.98),
    (re.compile(r"^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$", re.I), "EMAIL", "high", 0.98),
    (re.compile(r"^\d{17}[\dXx]$"), "ID_CARD", "critical", 0.98),
    (re.compile(r"^\d{12,19}$"), "BANK_CARD", "critical", 0.72),
    (re.compile(r"^(?:\d{1,3}\.){3}\d{1,3}$"), "IP_ADDRESS", "medium", 0.94),
    (re.compile(r"^[0-9A-F]{2}(?::[0-9A-F]{2}){5}$", re.I), "MAC_ADDRESS", "medium", 0.94),
    (re.compile(r"^https?://", re.I), "URL_WEBSITE", "medium", 0.92),
    (re.compile(r"^\d{4}(?:[-/\u5e74]\d{1,2}(?:[-/\u6708]\d{1,2}\u65e5?)?)?$"), "DATE", "medium", 0.78),
    (re.compile(r"^-?[\u00a5\uffe5$]?\d{1,3}(?:,\d{3})*(?:\.\d+)?$|^-?[\u00a5\uffe5$]?\d+(?:\.\d+)?$"), "AMOUNT", "medium", 0.55),
]


# Type-inference acceptance thresholds (names for literals).
_CUSTOM_TYPE_CONFIDENCE_MIN = 0.55
_DEFAULT_TYPE_CONFIDENCE_MIN = 0.78


_PII_DEFAULT_MASK_TYPES = {
    "PHONE",
    "EMAIL",
    "ID_CARD",
    "BANK_CARD",
    "LICENSE_PLATE",
}
_PII_DEFAULT_HASH_TYPES = {"IP_ADDRESS", "MAC_ADDRESS", "DEVICE_ID"}
_PII_DEFAULT_GENERALIZE_TYPES = {"ADDRESS"}
_PII_DEFAULT_TOKENIZE_TYPES = {"PERSON"}
_SECURITY_DEFAULT_SUPPRESS_TYPES = {"USERNAME_PASSWORD", "AUTH_SECRET"}

# 库表链的 HaS 查询词 → 类型 id：查询词与其含义同址共存（清单即真相源，
# 与文本/视觉链的清单直传同构）。回程按请求打标：返回桶名就是这里发出的词。
_STRUCTURED_HAS_QUERY_TYPES = {
    "姓名": "PERSON", "电话": "PHONE", "邮箱": "EMAIL", "身份证号": "ID_CARD",
    "银行卡号": "BANK_CARD", "银行账号": "BANK_ACCOUNT", "地址": "ADDRESS",
    "车牌": "LICENSE_PLATE", "IP地址": "IP_ADDRESS", "MAC地址": "MAC_ADDRESS",
    "登录账号": "USERNAME_PASSWORD", "密码": "AUTH_SECRET", "网址链接": "URL_WEBSITE",
    "设备号": "DEVICE_ID", "护照号": "PASSPORT", "社保号": "SOCIAL_SECURITY",
}
_STRUCTURED_HAS_NER_TYPES = list(_STRUCTURED_HAS_QUERY_TYPES)
_STRUCTURED_SEMANTIC_TYPE_RISK = {
    "PERSON": "high",
    "PHONE": "high",
    "EMAIL": "high",
    "ID_CARD": "critical",
    "BANK_CARD": "critical",
    "BANK_ACCOUNT": "critical",
    "ADDRESS": "medium",
    "LICENSE_PLATE": "high",
    "IP_ADDRESS": "medium",
    "MAC_ADDRESS": "medium",
    "DEVICE_ID": "medium",
    "USERNAME_PASSWORD": "critical",
    "AUTH_SECRET": "critical",
    "PASSPORT": "critical",
    "SOCIAL_SECURITY": "critical",
    "URL_WEBSITE": "medium",
}
_STRUCTURED_DIRECT_VALUE_TYPES = {
    "PHONE",
    "EMAIL",
    "ID_CARD",
    "BANK_CARD",
    "BANK_ACCOUNT",
    "IP_ADDRESS",
    "MAC_ADDRESS",
    "LICENSE_PLATE",
    "URL_WEBSITE",
}
_SEMANTIC_READY_CACHE: tuple[float, bool] = (0.0, False)
_SEMANTIC_READY_TTL_SEC = 15.0


def profile_dataset(dataset_id: str, *, owner_id: str, store: StructuredStore | None = None) -> dict[str, Any]:
    store = store or get_structured_store()
    dataset = store.get_dataset(dataset_id, owner_id=owner_id)
    if not dataset:
        raise ValueError("dataset not found")
    table = load_dataset_rows(dataset, owner_id=owner_id, limit=MAX_PROFILE_ROWS, store=store)
    columns = [profile_column(column, [row.get(column) for row in table.rows]) for column in table.columns]
    semantic_result = infer_column_semantics_with_has(dataset, table, columns)
    columns = merge_semantic_column_profiles(columns, semantic_result.get("columns") or {})
    profile = {
        "dataset_id": dataset_id,
        "shape_kind": infer_shape_kind(table.columns, table.rows),
        "row_count_estimate": table.row_count_estimate,
        "sampled_rows": len(table.rows),
        "columns": columns,
        "semantic_inference": {
            "engine": "has_ner",
            "status": semantic_result.get("status", "unknown"),
            "duration_ms": semantic_result.get("duration_ms", 0),
            "matched_columns": len(semantic_result.get("columns") or {}),
        },
    }
    store.save_profile(dataset_id, owner_id=owner_id, profile=profile)
    if not store.get_policy(dataset_id, owner_id=owner_id):
        store.save_policy(dataset_id, owner_id=owner_id, policy=default_policy(profile))
    return profile


def profile_column(column: str, values: list[Any]) -> dict[str, Any]:
    non_empty = [value for value in values if value not in (None, "")]
    total = max(1, len(values))
    null_rate = round(1 - (len(non_empty) / total), 4)
    unique_rate = round(len({normalize_value(value) for value in non_empty}) / max(1, len(non_empty)), 4)
    samples = list(dict.fromkeys(cell_to_json(value) for value in non_empty[:20]))[:8]
    if is_probable_technical_identifier(column, non_empty, unique_rate):
        return {
            "name": column,
            "data_type": infer_runtime_type(non_empty),
            "null_rate": null_rate,
            "unique_rate": unique_rate,
            "sample_values": samples,
            "entity_type": "CUSTOM",
            "risk_level": "low",
            "confidence": 0.88,
            "reasons": ["technical_identifier"],
            "recommended_policy": "keep",
        }
    by_value = classify_by_values(non_empty)
    by_name = classify_by_name(column)
    if is_business_descriptor_column(column) and not blocks_business_descriptor(by_name, by_value):
        return {
            "name": column,
            "data_type": infer_runtime_type(non_empty),
            "null_rate": null_rate,
            "unique_rate": unique_rate,
            "sample_values": samples,
            "entity_type": "CUSTOM",
            "risk_level": "low",
            "confidence": 0.84,
            "reasons": ["business_descriptor"],
            "recommended_policy": "keep",
        }
    chosen = choose_classification(by_name, by_value, unique_rate)
    entity_type, risk_level, confidence, reasons = chosen
    return {
        "name": column,
        "data_type": infer_runtime_type(non_empty),
        "null_rate": null_rate,
        "unique_rate": unique_rate,
        "sample_values": samples,
        "entity_type": entity_type,
        "risk_level": risk_level,
        "confidence": confidence,
        "reasons": reasons,
        "recommended_policy": recommended_action(entity_type, risk_level, unique_rate),
    }


def infer_column_semantics_with_has(
    dataset: dict[str, Any],
    table: LoadedTable,
    columns: list[dict[str, Any]],
) -> dict[str, Any]:
    started = time.perf_counter()
    if not table.rows or not table.columns:
        return {"status": "skipped_empty", "columns": {}, "duration_ms": 0}
    # 经 facade 取 has_text_semantic_ready：测试 monkeypatch 的是
    # structured_service.has_text_semantic_ready（函数内导入避免循环导入）
    from app.services import structured_service

    if not structured_service.has_text_semantic_ready():
        return {"status": "unavailable", "columns": {}, "duration_ms": 0}

    text, samples_by_column = build_structured_ner_text(dataset, table, columns)
    if not samples_by_column:
        return {"status": "skipped_no_candidates", "columns": {}, "duration_ms": 0}
    if not text.strip():
        return {"status": "skipped_empty", "columns": {}, "duration_ms": 0}

    try:
        from app.services.has_client import HaSClient

        timeout = max(1.0, min(float(settings.STRUCTURED_HAS_TIMEOUT), float(settings.HAS_TIMEOUT)))
        result = HaSClient(timeout=timeout, max_retries=0).ner(text, _STRUCTURED_HAS_NER_TYPES)
    except Exception as exc:
        logger.warning("Structured HaS semantic inference failed: %s", exc)
        return {
            "status": "failed",
            "columns": {},
            "duration_ms": max(0, int((time.perf_counter() - started) * 1000)),
        }

    semantic_columns = map_has_entities_to_columns(result, samples_by_column)
    return {
        "status": "used" if semantic_columns else "used_no_matches",
        "columns": semantic_columns,
        "duration_ms": max(0, int((time.perf_counter() - started) * 1000)),
    }


def has_text_semantic_ready() -> bool:
    global _SEMANTIC_READY_CACHE
    now = time.monotonic()
    cached_at, cached_ready = _SEMANTIC_READY_CACHE
    if now - cached_at < _SEMANTIC_READY_TTL_SEC:
        return cached_ready
    try:
        from app.core.config import get_has_health_check_url

        response = httpx.get(get_has_health_check_url(), timeout=2.0, trust_env=False)
        ready = response.status_code < 500
    except Exception:
        ready = False
    _SEMANTIC_READY_CACHE = (now, ready)
    return ready


def build_structured_ner_text(
    dataset: dict[str, Any],
    table: LoadedTable,
    columns: list[dict[str, Any]],
) -> tuple[str, dict[str, list[str]]]:
    profile_by_name = {str(column.get("name")): column for column in columns}
    lines = [
        f"Dataset: {dataset.get('name') or dataset.get('table_name') or 'structured_table'}",
        f"Kind: {dataset.get('source_kind') or 'table'}",
    ]
    samples_by_column: dict[str, list[str]] = {}
    for column in table.columns[:80]:
        profile = profile_by_name.get(column, {})
        raw_samples = list(dict.fromkeys(
            normalize_value(row.get(column))
            for row in table.rows[:80]
            if normalize_value(row.get(column))
        ))[:6]
        samples = [sample[:120] for sample in raw_samples if sample][:6]
        if not samples:
            continue
        if not should_include_column_for_structured_semantics(column, profile, samples):
            continue
        samples_by_column[column] = samples
        lines.append(
            "Column "
            + json.dumps(column, ensure_ascii=False)
            + f" type={profile.get('data_type', 'string')} samples: "
            + " | ".join(samples)
        )
    return "\n".join(lines)[: min(12_000, int(settings.HAS_NER_CONTEXT_TOKENS) * 2)], samples_by_column


def should_include_column_for_structured_semantics(
    column: str,
    profile: dict[str, Any],
    samples: list[str],
) -> bool:
    """Only send genuinely ambiguous table columns to HaS semantic enrichment.

    Deterministic table signals cover most structured PII. Calling the text
    model for every obvious phone/email/name column makes the policy screen feel
    slow and does not improve recall, so HaS is reserved for low-confidence
    natural-language columns where the field name is not enough.
    """
    reasons = {str(reason) for reason in (profile.get("reasons") or [])}
    if reasons.intersection({"technical_identifier", "business_descriptor"}):
        return False
    entity_type = str(profile.get("entity_type") or "CUSTOM")
    confidence = float(profile.get("confidence") or 0)
    if entity_type != "CUSTOM" and confidence >= 0.65:
        return False
    if is_identifier_column_name(column):
        return False
    return any(sample_looks_semantic(sample) for sample in samples)


def is_identifier_column_name(column: str) -> bool:
    text = re.sub(r"[^a-z0-9_\u4e00-\u9fff]+", "_", str(column or "").strip().lower()).strip("_")
    if not text:
        return False
    if text in {"id", "uuid", "guid", "pk", "key", "code", "no", "num", "number", "编号", "序号", "代码"}:
        return True
    return bool(re.search(r"(^|_)(id|uuid|guid|code|no|num|number|编号|序号|代码)$", text))


def sample_looks_semantic(sample: str) -> bool:
    text = normalize_value(sample)
    if not text:
        return False
    if re.search(r"[\u4e00-\u9fff]", text):
        return True
    if re.search(r"[A-Za-z]+[\s·.'-]+[A-Za-z]+", text):
        return True
    if len(text) >= 16 and re.search(r"[A-Za-z]", text) and not re.fullmatch(r"[A-Za-z0-9_\-]+", text):
        return True
    return False


def map_has_entities_to_columns(
    ner_result: dict[str, list[str]],
    samples_by_column: dict[str, list[str]],
) -> dict[str, dict[str, Any]]:
    votes: dict[str, Counter[str]] = {column: Counter() for column in samples_by_column}
    matches: dict[str, dict[str, list[str]]] = {column: {} for column in samples_by_column}
    for raw_type, values in (ner_result or {}).items():
        entity_type = normalize_structured_entity_type(raw_type)
        if entity_type == "CUSTOM" or entity_type not in _STRUCTURED_SEMANTIC_TYPE_RISK:
            continue
        if not isinstance(values, list):
            continue
        for raw_value in values:
            entity_text = compact_text(raw_value)
            if not entity_text:
                continue
            for column, samples in samples_by_column.items():
                if any(entity_matches_sample(entity_text, sample) for sample in samples):
                    votes[column][entity_type] += 1
                    bucket = matches[column].setdefault(entity_type, [])
                    value = normalize_value(raw_value)
                    if value not in bucket:
                        bucket.append(value)
    semantic: dict[str, dict[str, Any]] = {}
    for column, counter in votes.items():
        if not counter:
            continue
        entity_type, count = counter.most_common(1)[0]
        sample_count = max(1, len(samples_by_column.get(column) or []))
        match_ratio = min(1.0, count / sample_count)
        semantic[column] = {
            "entity_type": entity_type,
            "risk_level": _STRUCTURED_SEMANTIC_TYPE_RISK.get(entity_type, "high"),
            "confidence": round(min(0.97, max(0.72, 0.62 + match_ratio * 0.3)), 3),
            "reason": "semantic_model_value",
            "matched_values": matches[column].get(entity_type, [])[:5],
        }
    return semantic


def normalize_structured_entity_type(raw_type: str) -> str:
    """Tag-by-request for the structured chain: a result bucket is keyed by a
    query word WE sent (_STRUCTURED_HAS_QUERY_TYPES) — no global cn_terms
    lookup. English echo variants land via pure string hygiene
    (canonical_type_id). Unknown open-vocabulary labels become CUSTOM."""
    value = str(raw_type or "").strip()
    if not value:
        return "CUSTOM"
    canonical = _STRUCTURED_HAS_QUERY_TYPES.get(value) or canonical_type_id(value)
    if canonical == "BANK_ACCOUNT":
        return "BANK_CARD"
    if canonical in {"PASSWORD", "TOKEN", "SECRET_KEY", "API_KEY", "OTP", "ACCOUNT_PASSWORD", "LOGIN_PASSWORD"}:
        return "AUTH_SECRET"
    if canonical in _STRUCTURED_SEMANTIC_TYPE_RISK:
        return canonical
    return canonical if canonical in {"PERSON", "PHONE", "EMAIL", "ID_CARD", "ADDRESS"} else "CUSTOM"


def entity_matches_sample(entity_text: str, sample: str) -> bool:
    sample_text = compact_text(sample)
    if not entity_text or not sample_text:
        return False
    if entity_text in sample_text:
        return True
    return len(entity_text) >= 4 and sample_text in entity_text


def merge_semantic_column_profiles(
    columns: list[dict[str, Any]],
    semantic_columns: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for column in columns:
        out = dict(column)
        semantic = semantic_columns.get(str(column.get("name") or ""))
        if semantic and should_apply_semantic_profile(out, semantic):
            entity_type = str(semantic.get("entity_type") or out.get("entity_type") or "CUSTOM")
            risk_level = str(semantic.get("risk_level") or out.get("risk_level") or "low")
            confidence = float(semantic.get("confidence") or out.get("confidence") or 0)
            reasons = list(out.get("reasons") or [])
            for reason in ["semantic_model", str(semantic.get("reason") or "")]:
                if reason and reason not in reasons:
                    reasons.append(reason)
            out.update(
                {
                    "entity_type": entity_type,
                    "risk_level": risk_level,
                    "confidence": round(max(float(out.get("confidence") or 0), confidence), 3),
                    "reasons": reasons,
                    "recommended_policy": recommended_action(entity_type, risk_level, float(out.get("unique_rate") or 0)),
                }
            )
        merged.append(out)
    return merged


def should_apply_semantic_profile(column: dict[str, Any], semantic: dict[str, Any]) -> bool:
    semantic_type = str(semantic.get("entity_type") or "CUSTOM")
    if semantic_type == "CUSTOM":
        return False
    confidence = float(semantic.get("confidence") or 0)
    current_type = str(column.get("entity_type") or "CUSTOM")
    reasons = {str(reason) for reason in (column.get("reasons") or [])}
    if "technical_identifier" in reasons:
        return False
    if "column_values" in reasons and current_type in _STRUCTURED_DIRECT_VALUE_TYPES:
        return False
    if current_type == semantic_type:
        return confidence >= 0.5
    if current_type == "CUSTOM" or reasons == {"high_cardinality"}:
        return confidence >= _CUSTOM_TYPE_CONFIDENCE_MIN
    return confidence >= _DEFAULT_TYPE_CONFIDENCE_MIN


def classify_by_name(column: str) -> tuple[str, str, float, str] | None:
    text = column.strip().lower()
    for pattern, entity_type, risk_level, confidence in _COLUMN_NAME_HINTS:
        if re.search(pattern, text, re.I):
            return entity_type, risk_level, confidence, "column_name"
    return None


def is_business_descriptor_column(column: str) -> bool:
    text = re.sub(r"[^a-z0-9_\-\s\u4e00-\u9fff]+", "_", str(column or "").strip().lower()).strip("_")
    if not text:
        return False
    return any(pattern.search(text) for pattern in _BUSINESS_DESCRIPTOR_COLUMN_PATTERNS)


def blocks_business_descriptor(
    by_name: tuple[str, str, float, str] | None,
    by_value: tuple[str, str, float, str] | None,
) -> bool:
    for classification in (by_name, by_value):
        if classification and classification[0] in _BUSINESS_DESCRIPTOR_BLOCK_TYPES:
            return True
    return False


def is_probable_technical_identifier(column: str, values: list[Any], unique_rate: float) -> bool:
    normalized = re.sub(r"[^a-z0-9_\u4e00-\u9fff]+", "_", str(column or "").strip().lower()).strip("_")
    if normalized not in {"id", "row_id", "rowid", "pk", "index", "idx", "serial", "\u5e8f\u53f7", "\u884c\u53f7"}:
        return False
    text_values = [normalize_value(value).strip() for value in values if normalize_value(value).strip()]
    if not text_values:
        return False
    if not all(re.fullmatch(r"\d{1,9}", value) for value in text_values):
        return False
    if unique_rate < 0.8:
        return False
    numbers = [int(value) for value in text_values]
    sorted_unique = sorted(set(numbers))
    if len(sorted_unique) == 1:
        return sorted_unique[0] <= max(10_000_000, len(text_values) * 10)
    span = sorted_unique[-1] - sorted_unique[0] + 1
    density = len(sorted_unique) / max(1, span)
    return density >= 0.8 and sorted_unique[-1] <= max(10_000_000, len(text_values) * 10)


def classify_by_values(values: list[Any]) -> tuple[str, str, float, str] | None:
    if not values:
        return None
    sample = [normalize_value(value) for value in values[:200]]
    votes: Counter[tuple[str, str]] = Counter()
    best_confidence = 0.0
    for value in sample:
        text = compact_text(value)
        if not text:
            continue
        for pattern, entity_type, risk_level, confidence in _VALUE_PATTERNS:
            if pattern.match(text):
                votes[(entity_type, risk_level)] += 1
                best_confidence = max(best_confidence, confidence)
                break
    if not votes:
        return None
    (entity_type, risk_level), count = votes.most_common(1)[0]
    ratio = count / max(1, len(sample))
    if ratio < 0.35:
        return None
    return entity_type, risk_level, round(min(0.99, max(best_confidence, ratio)), 3), "column_values"


def choose_classification(
    by_name: tuple[str, str, float, str] | None,
    by_value: tuple[str, str, float, str] | None,
    unique_rate: float,
) -> tuple[str, str, float, list[str]]:
    if by_name and by_value:
        if by_name[0] == by_value[0]:
            return by_name[0], max_risk(by_name[1], by_value[1]), max(by_name[2], by_value[2]), [by_name[3], by_value[3]]
        if by_value[2] >= by_name[2] + 0.12:
            return by_value[0], by_value[1], by_value[2], [by_value[3], "value_overrides_name"]
        return by_name[0], by_name[1], by_name[2], [by_name[3], "name_overrides_value"]
    if by_value:
        return by_value[0], by_value[1], by_value[2], [by_value[3]]
    if by_name:
        return by_name[0], by_name[1], by_name[2], [by_name[3]]
    if unique_rate >= 0.98:
        return "CUSTOM", "low", 0.35, ["high_cardinality"]
    return "CUSTOM", "low", 0.1, []


def max_risk(left: str, right: str) -> str:
    order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
    return left if order.get(left, 0) >= order.get(right, 0) else right


def recommended_action(entity_type: str, risk_level: str, unique_rate: float) -> str:
    del risk_level
    if entity_type in _SECURITY_DEFAULT_SUPPRESS_TYPES:
        return "suppress"
    if entity_type in _PII_DEFAULT_MASK_TYPES:
        return "mask"
    if entity_type in _PII_DEFAULT_HASH_TYPES:
        return "hash"
    if entity_type in _PII_DEFAULT_GENERALIZE_TYPES:
        return "generalize"
    if entity_type in _PII_DEFAULT_TOKENIZE_TYPES:
        return "tokenize" if unique_rate > 0.5 else "mask"
    return "keep"


def default_policy(profile: dict[str, Any]) -> dict[str, Any]:
    return {
        "dataset_id": profile["dataset_id"],
        "columns": [
            {
                "column": col["name"],
                "action": col.get("recommended_policy") or "keep",
                "entity_type": col.get("entity_type") or "CUSTOM",
                "enabled": (col.get("recommended_policy") or "keep") != "keep",
                "params": {},
            }
            for col in profile.get("columns", [])
        ],
    }


def get_or_create_policy(dataset_id: str, *, owner_id: str, store: StructuredStore | None = None) -> dict[str, Any]:
    store = store or get_structured_store()
    policy = store.get_policy(dataset_id, owner_id=owner_id)
    if policy:
        return policy
    profile = store.get_profile(dataset_id, owner_id=owner_id) or profile_dataset(dataset_id, owner_id=owner_id, store=store)
    return store.save_policy(dataset_id, owner_id=owner_id, policy=default_policy(profile))


def save_policy(
    dataset_id: str,
    *,
    owner_id: str,
    columns: list[dict[str, Any]],
    store: StructuredStore | None = None,
) -> dict[str, Any]:
    store = store or get_structured_store()
    if not store.get_dataset(dataset_id, owner_id=owner_id):
        raise ValueError("dataset not found")
    profile = store.get_profile(dataset_id, owner_id=owner_id) or profile_dataset(dataset_id, owner_id=owner_id, store=store)
    validate_policy_columns(profile, columns)
    policy = {
        "dataset_id": dataset_id,
        "columns": columns,
        "reviewed_at": datetime.now(UTC).isoformat(),
    }
    return store.save_policy(dataset_id, owner_id=owner_id, policy=policy)


def validate_policy_columns(profile: dict[str, Any], columns: list[dict[str, Any]]) -> None:
    expected = [str(column.get("name") or "") for column in profile.get("columns", [])]
    expected_set = set(expected)
    seen: set[str] = set()
    duplicates: list[str] = []
    provided: list[str] = []
    for item in columns:
        name = str(item.get("column") or "")
        provided.append(name)
        if name in seen:
            duplicates.append(name)
        seen.add(name)
    provided_set = set(provided)
    unknown = sorted(name for name in provided_set if name not in expected_set)
    missing = [name for name in expected if name not in provided_set]
    if duplicates or unknown or missing:
        parts = []
        if duplicates:
            parts.append("duplicate columns: " + ", ".join(sorted(set(duplicates))[:5]))
        if unknown:
            parts.append("unknown columns: " + ", ".join(unknown[:5]))
        if missing:
            parts.append("missing columns: " + ", ".join(missing[:5]))
        raise ValueError(
            "Column policy does not match the current dataset columns ("
            + "; ".join(parts)
            + "). Regenerate the policy or refresh the dataset before saving."
        )
