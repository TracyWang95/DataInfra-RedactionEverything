"""
实体类型映射 —— 单一数据源

统一维护中英文实体类型映射，消除 redactor / has_service / has_client / ocr_has_vision_service 中的重复定义。
基于 GB/T 37964-2019《信息安全技术 个人信息去标识化指南》。
"""

# ── Single source of truth ──────────────────────────────────────────────────
# Every entity type is defined exactly once here. The id↔label, alias and
# linkage maps below are DERIVED from this registry — no scattered .update()
# blocks, no order-dependent overrides. To add/rename a type, edit only this.
TYPE_REGISTRY: dict[str, dict] = {
    "ADDRESS": {"cn": "地址", "label": "地址", "groups": ["address_like"]},
    "AGE": {"cn": "年龄", "label": "年龄", "groups": ["person_like"]},
    "AMOUNT": {"cn": "金额", "label": "金额", "groups": ["account_like"]},
    "AUTH_SECRET": {"cn": "密码", "label": "密码", "groups": ["credential_like"]},
    "BANK_ACCOUNT": {"cn": "银行账号", "label": "银行账号", "groups": ["account_like"]},
    "BANK_CARD": {"cn": "银行卡号", "label": "银行卡号", "groups": ["account_like"]},
    "BANK_NAME": {"cn": "开户行", "label": "开户行", "groups": ["account_like", "organization_like"]},
    "BIOMETRIC": {"cn": "生物特征", "label": "生物特征"},
    "BIRTH_DATE": {"cn": "出生日期", "label": "出生日期", "groups": ["date_like", "person_like"]},
    "CASE_NUMBER": {"cn": "编号", "label": "编号", "groups": ["identifier_like"]},
    "CERT_NO": {"cn": "证号", "label": "证号", "groups": ["identifier_like"]},
    "COMPANY": {"label": "公司"},
    "COMPANY_CODE": {"cn": "统一社会信用代码", "label": "信用代码"},
    "COMPANY_NAME": {"cn": "公司名称", "label": "公司名称", "groups": ["organization_like"]},
    "CONTRACT_ID": {"cn": "编号", "label": "编号"},
    "CONTRACT_NO": {"label": "编号"},
    "CREDIT_CODE": {"cn": "统一社会信用代码", "label": "统一社会信用代码", "groups": ["identifier_like", "organization_like"]},
    "CRIMINAL_RECORD": {"cn": "法律记录", "label": "法律记录", "groups": ["person_like"]},
    "CUSTOM": {"label": "敏感信息"},
    "DATE": {"cn": "日期", "label": "日期", "groups": ["date_like"]},
    "DEPARTMENT_NAME": {"cn": "部门名称", "label": "部门名称", "groups": ["organization_like"]},
    "DEVICE_ID": {"cn": "设备号", "label": "设备号", "groups": ["credential_like", "identifier_like"]},
    "DOCUMENT": {"cn": "文件"},
    "DOCUMENT_NUMBER": {"cn": "文书编号", "label": "文书编号", "groups": ["identifier_like"]},
    "EMAIL": {"cn": "邮箱", "label": "邮箱", "groups": ["person_like"]},
    "ETHNICITY": {"cn": "民族", "label": "民族", "groups": ["person_like"]},
    "FIN_ACCOUNT_NAME": {"cn": "账户户名", "label": "账户户名", "groups": ["account_like"]},
    "FIN_CUSTOMER_ID": {"cn": "客户号", "label": "客户号", "groups": ["account_like"]},
    "FIN_INSTITUTION": {"cn": "金融机构", "label": "金融机构", "groups": ["organization_like"]},
    "FIN_MERCHANT_ID": {"cn": "商户号", "label": "商户号", "groups": ["account_like"]},
    "FIN_RISK_RATING": {"cn": "风险评级", "label": "风险评级"},
    "FIN_TRANSACTION_ID": {"cn": "交易流水号", "label": "交易流水号", "groups": ["account_like"]},
    "GENDER": {"cn": "性别", "label": "性别", "groups": ["person_like"]},
    "GEN_ACCOUNT_TRANSACTION": {"cn": "账户与交易", "label": "账户与交易", "groups": ["account_like"]},
    "GEN_ADDRESS_LOCATION": {"cn": "地址位置", "label": "地址位置", "groups": ["address_like"]},
    "GEN_AMOUNT_VALUE": {"cn": "金额数值", "label": "金额数值", "groups": ["account_like"]},
    "GEN_ASSET_RESOURCE": {"cn": "资产资源与标的物", "label": "资产资源与标的物"},
    "GEN_ATTRIBUTE_STATUS": {"cn": "属性状态", "label": "属性状态"},
    "GEN_CONTACT": {"cn": "联系方式", "label": "联系方式"},
    "GEN_CREDENTIAL_ACCESS": {"cn": "凭证密钥与访问控制", "label": "凭证密钥与访问控制", "groups": ["credential_like"]},
    "GEN_DATE_TIME": {"cn": "日期时间", "label": "日期时间", "groups": ["date_like"]},
    "GEN_DOCUMENT_RECORD": {"cn": "文档内容与业务记录", "label": "文档内容与业务记录"},
    "GEN_NAME": {"cn": "名称", "label": "名称"},
    "GEN_NUMBER_CODE": {"cn": "号码/编号/代码", "label": "号码/编号/代码", "groups": ["identifier_like"]},
    "GEN_ORGANIZATION_SUBJECT": {"cn": "组织主体", "label": "组织主体", "groups": ["organization_like"]},
    "GEN_PERSON_SUBJECT": {"cn": "人员主体", "label": "人员主体", "groups": ["person_like"]},
    "GEN_VISUAL_SEMANTIC": {"cn": "视觉语义补充", "label": "视觉语义补充"},
    "GOVERNMENT_AGENCY": {"cn": "机关单位", "label": "机关单位", "groups": ["organization_like"]},
    "GPS_LOCATION": {"cn": "定位位置", "label": "定位位置", "groups": ["address_like"]},
    "HEALTH_INFO": {"cn": "健康信息", "label": "健康信息"},
    "ID_CARD": {"cn": "身份证号", "label": "身份证号", "groups": ["identifier_like", "person_like"]},
    "INPATIENT_NO": {"cn": "住院号", "label": "住院号", "groups": ["identifier_like"]},
    "INSTITUTION_NAME": {"cn": "机构名称", "label": "机构名称", "groups": ["organization_like"]},
    "IP_ADDRESS": {"cn": "IP地址", "label": "IP地址", "groups": ["credential_like", "identifier_like"]},
    "JUDGE": {"label": "法官"},
    "LAWYER": {"label": "律师"},
    "LEGAL_ATTORNEY": {"cn": "代理律师", "label": "代理律师", "groups": ["person_like"]},
    "LEGAL_CASE_ID": {"cn": "案号", "label": "案号"},
    "LEGAL_CLAIM": {"cn": "诉讼请求", "label": "诉讼请求"},
    "LEGAL_COURT": {"cn": "法院", "label": "法院", "groups": ["organization_like"]},
    "LEGAL_DEFENDANT": {"cn": "被告", "label": "被告", "groups": ["organization_like", "person_like"]},
    "LEGAL_LAW_FIRM": {"cn": "律所", "label": "律所", "groups": ["organization_like"]},
    "LEGAL_PARTY": {"label": "当事人"},
    "LEGAL_PLAINTIFF": {"cn": "原告", "label": "原告", "groups": ["organization_like", "person_like"]},
    "LEGAL_THIRD_PARTY": {"cn": "第三人", "label": "第三人", "groups": ["organization_like", "person_like"]},
    "LICENSE_PLATE": {"cn": "车牌号", "label": "车牌号", "groups": ["identifier_like"]},
    "MAC_ADDRESS": {"label": "MAC地址"},
    "MARITAL_STATUS": {"cn": "婚姻状态", "label": "婚姻状态", "groups": ["person_like"]},
    "MEDICAL_RECORD": {"label": "病历号"},
    "MED_ALLERGY_HISTORY": {"cn": "过敏史", "label": "过敏史"},
    "MED_CHIEF_COMPLAINT": {"cn": "主诉", "label": "主诉"},
    "MED_CLINICIAN": {"cn": "医务人员", "label": "医务人员", "groups": ["person_like"]},
    "MED_DEPARTMENT": {"cn": "科室", "label": "科室", "groups": ["organization_like"]},
    "MED_DIAGNOSIS": {"cn": "诊断", "label": "诊断"},
    "MED_EXAM_RESULT": {"cn": "检查结果", "label": "检查结果"},
    "MED_INSTITUTION": {"cn": "医疗机构", "label": "医疗机构", "groups": ["organization_like"]},
    "MED_MEDICATION": {"cn": "用药", "label": "用药"},
    "MED_ORDER": {"cn": "医嘱", "label": "医嘱"},
    "MED_PAST_HISTORY": {"cn": "既往史", "label": "既往史"},
    "MED_PATIENT": {"cn": "患者", "label": "患者", "groups": ["person_like"]},
    "MED_PRESENT_ILLNESS": {"cn": "现病史", "label": "现病史"},
    "MED_PROCEDURE": {"cn": "医疗操作", "label": "医疗操作"},
    "MED_RECORD_ID": {"cn": "病历号", "label": "病历号", "groups": ["identifier_like"]},
    "MED_VITAL_SIGN": {"cn": "生命体征", "label": "生命体征"},
    "NATIONALITY": {"cn": "国籍", "label": "国籍", "groups": ["person_like"]},
    "NATIVE_PLACE": {"cn": "籍贯", "label": "籍贯", "groups": ["person_like"]},
    "OCCUPATION": {"cn": "职业", "label": "职业", "groups": ["person_like"]},
    "ORG": {"cn": "组织机构", "label": "组织机构", "groups": ["organization_like"]},
    "PASSPORT": {"cn": "护照号", "label": "护照号", "groups": ["identifier_like", "person_like"]},
    "PERSON": {"cn": "姓名", "label": "姓名", "groups": ["person_like"]},
    "PERSONAL_ATTRIBUTE": {"cn": "出生日期"},
    "PHONE": {"cn": "电话", "label": "电话", "groups": ["person_like"]},
    "POLITICAL": {"cn": "政治面貌", "label": "政治面貌", "groups": ["person_like"]},
    "POSTAL_CODE": {"cn": "邮政编码", "label": "邮政编码", "groups": ["address_like"]},
    "PROJECT_NAME": {"cn": "项目名称", "label": "项目名称", "groups": ["organization_like"]},
    "PROPERTY": {"label": "财产"},
    "REGISTRATION_NO": {"cn": "登记号", "label": "登记号", "groups": ["identifier_like"]},
    "RELIGION": {"cn": "宗教信仰", "label": "宗教信仰", "groups": ["person_like"]},
    "SEXUAL_ORIENTATION": {"cn": "性取向", "label": "性取向", "groups": ["person_like"]},
    "SOCIAL_SECURITY": {"cn": "社保号", "label": "社保号", "groups": ["identifier_like", "person_like"]},
    "TAX_ID": {"cn": "税号", "label": "税号", "groups": ["identifier_like", "organization_like"]},
    "TIME": {"cn": "时间", "label": "时间", "groups": ["date_like"]},
    "URL_WEBSITE": {"cn": "网址", "label": "网址", "groups": ["credential_like", "identifier_like"]},
    "USERNAME_PASSWORD": {"cn": "登录账号", "label": "登录账号", "groups": ["credential_like"]},
    "VIN": {"cn": "车架号", "label": "车架号", "groups": ["identifier_like"]},
    "WECHAT_ALIPAY": {"label": "支付账号"},
    "WITNESS": {"label": "证人"},
    "WORK_UNIT": {"cn": "工作单位", "label": "工作单位", "groups": ["organization_like"]},
}

# ── Derived maps (do NOT edit — change TYPE_REGISTRY above) ──────────────────
TYPE_ID_TO_CN: dict[str, str] = {tid: e["cn"] for tid, e in TYPE_REGISTRY.items() if e.get("cn")}
TYPE_ID_TO_LABEL: dict[str, str] = {tid: e["label"] for tid, e in TYPE_REGISTRY.items() if e.get("label")}
LINKAGE_GROUP_BY_TYPE_ID: dict[str, set[str]] = {tid: set(e["groups"]) for tid, e in TYPE_REGISTRY.items() if e.get("groups")}
TYPE_CN_TO_ID: dict[str, str] = {e["cn"]: tid for tid, e in TYPE_REGISTRY.items() if e.get("cn")}

QUERY_LABELS_BY_TYPE_ID: dict[str, list[str]] = {
    "AMOUNT": ["金额", "大写金额"],
}


def has_query_labels_for(type_id: str) -> list[str]:
    canonical = canonical_type_id(type_id)
    return QUERY_LABELS_BY_TYPE_ID.get(canonical, [TYPE_ID_TO_CN.get(canonical, canonical)]) if TYPE_ID_TO_CN.get(canonical) else []


def cn_to_id(cn: str) -> str:
    return TYPE_CN_TO_ID.get(cn, cn)


def linkage_groups_for_type(type_id: str) -> set[str]:
    """Return internal linkage groups without changing the public type id."""
    canonical = canonical_type_id(type_id)
    return set(LINKAGE_GROUP_BY_TYPE_ID.get(canonical, set()))


def linkage_group_for_type(type_id: str) -> str:
    """Return a stable primary linkage group for legacy single-group callers."""
    groups = linkage_groups_for_type(type_id)
    return sorted(groups)[0] if groups else ""


def id_to_label(type_id: str, default: str = "敏感信息") -> str:
    """英文类型 ID 转中文标签，用于 smart 替换。"""
    return TYPE_ID_TO_LABEL.get(canonical_type_id(type_id), default)


def id_to_cn(type_id: str) -> str:
    """英文类型 ID 转中文类型名（用于 HaS prompt）。"""
    canonical = canonical_type_id(type_id)
    return TYPE_ID_TO_CN.get(canonical, canonical)


def canonical_type_id(type_id: str) -> str:
    """Normalize a type id string (case/separators only — no alias mapping).

    The historical alias/cn_terms translation layer is gone (owner decision):
    the checklist owns the vocabulary; ids are compared after this pure
    string hygiene, never remapped."""
    return str(type_id or "").strip().upper().replace("-", "_").replace(" ", "_").replace("/", "_")


