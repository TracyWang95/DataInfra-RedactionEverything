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
    "ADDRESS": {"cn": "地址", "label": "地址", "groups": ["address_like"], "cn_terms": ["住址", "地址", "居住地", "收货地址", "详细地址", "通信地址"]},
    "AGE": {"cn": "年龄", "label": "年龄", "groups": ["person_like"], "cn_terms": ["年龄", "年龄段"]},
    "AMOUNT": {"cn": "金额", "label": "金额", "groups": ["account_like"], "id_aliases": ["MONEY"], "cn_terms": ["数额", "款项", "金额"]},
    "AUTH_SECRET": {"cn": "密码", "label": "密码", "groups": ["credential_like"], "id_aliases": ["ACCOUNT_PASSWORD", "API_KEY", "LOGIN_PASSWORD", "OTP", "PASSWORD", "SECRET_KEY", "TOKEN"], "cn_terms": ["API Key", "Token", "令牌", "密码", "密钥", "验证码"]},
    "BANK_ACCOUNT": {"cn": "银行账号", "label": "银行账号", "groups": ["account_like"], "id_aliases": ["PAYMENT_ACCOUNT", "PAYMENT_ID", "WALLET_ADDRESS"], "cn_terms": ["对公账号", "支付账号", "收款账号", "账户号", "账户号码", "银行账号"]},
    "BANK_CARD": {"cn": "银行卡号", "label": "银行卡号", "groups": ["account_like"], "cn_terms": ["信用卡号", "卡号", "银行卡", "银行卡号"]},
    "BANK_NAME": {"cn": "开户行", "label": "开户行", "groups": ["account_like", "organization_like"], "cn_terms": ["开户行", "开户银行", "收款银行", "银行", "银行名称"]},
    "BIOMETRIC": {"cn": "生物特征", "label": "生物特征", "id_aliases": ["GENETIC"], "cn_terms": ["基因信息", "声纹", "指纹", "生物特征", "虹膜"]},
    "BIRTH_DATE": {"cn": "出生日期", "label": "出生日期", "groups": ["date_like", "person_like"], "cn_terms": ["出生日期", "生日"]},
    "CASE_NUMBER": {"cn": "编号", "label": "编号", "groups": ["identifier_like"], "id_aliases": ["CONTRACT_ID", "CONTRACT_NO", "CONTRACT_NUMBER"], "cn_terms": ["业务编号", "保单号", "协议号", "协议编号", "合同号", "合同编号", "工单号", "案件编号", "订单号"]},
    "CERT_NO": {"cn": "证号", "label": "证号", "groups": ["identifier_like"], "cn_terms": ["证号", "证书编号", "资格证号", "执业证号", "报关员证号"]},
    "COMPANY": {"label": "公司", "cn_terms": ["买受人", "借款人", "出借人", "出卖人", "发包方", "受托方", "受让方", "委托方", "承包方", "承揽方", "转让方"]},
    "COMPANY_CODE": {"cn": "统一社会信用代码", "label": "信用代码"},
    "COMPANY_NAME": {"cn": "公司名称", "label": "公司名称", "groups": ["organization_like"], "id_aliases": ["COMPANY"], "cn_terms": ["丙方", "乙方", "企业", "企业名", "企业名称", "供应商", "公司", "公司名", "公司名称", "客户单位", "甲方"]},
    "CONTRACT_ID": {"cn": "编号", "label": "编号"},
    "CONTRACT_NO": {"label": "编号"},
    "CREDIT_CODE": {"cn": "统一社会信用代码", "label": "统一社会信用代码", "groups": ["identifier_like", "organization_like"], "id_aliases": ["COMPANY_CODE"], "cn_terms": ["信用代码", "统一社会信用代码"]},
    "CRIMINAL_RECORD": {"cn": "法律记录", "label": "法律记录", "groups": ["person_like"], "cn_terms": ["处罚记录", "法律记录", "犯罪记录", "违法记录"]},
    "CUSTOM": {"label": "敏感信息"},
    "DATE": {"cn": "日期", "label": "日期", "groups": ["date_like"], "id_aliases": ["DATESTAMP", "DATETIME", "DATE_AND_TIME", "DATE_STAMP", "DATE_TIME", "TIMESTAMP", "TIME_STAMP"], "cn_terms": ["日期", "时间点"]},
    "DEPARTMENT_NAME": {"cn": "部门名称", "label": "部门名称", "groups": ["organization_like"], "cn_terms": ["处室", "科室", "部门", "部门名称", "项目组"]},
    "DEVICE_ID": {"cn": "设备号", "label": "设备号", "groups": ["credential_like", "identifier_like"], "id_aliases": ["MAC_ADDRESS"], "cn_terms": ["终端号", "设备号", "设备标识"]},
    "DOCUMENT": {"cn": "文件", "cn_terms": ["文件"]},
    "DOCUMENT_NUMBER": {"cn": "文书编号", "label": "文书编号", "groups": ["identifier_like"], "id_aliases": ["LEGAL_CASE_ID", "LEGAL_DOC_NO"], "cn_terms": ["执行案号", "文书号", "文书编号", "案件号", "案号", "法律文书号", "裁判文书编号", "航次号", "合同协议号", "提运单号", "备案号", "预录入编号", "海关编号"]},
    "EMAIL": {"cn": "邮箱", "label": "邮箱", "groups": ["person_like"], "cn_terms": ["电子邮箱", "邮件", "邮箱", "邮箱地址"]},
    "ETHNICITY": {"cn": "民族", "label": "民族", "groups": ["person_like"], "id_aliases": ["RACE_ETHNICITY"], "cn_terms": ["族裔", "民族", "种族"]},
    "FIN_ACCOUNT_NAME": {"cn": "账户户名", "label": "账户户名", "groups": ["account_like"], "cn_terms": ["开户名称", "账户名称", "账户户名"]},
    "FIN_CUSTOMER_ID": {"cn": "客户号", "label": "客户号", "groups": ["account_like"], "cn_terms": ["投资者编号", "金融客户号"]},
    "FIN_INSTITUTION": {"cn": "金融机构", "label": "金融机构", "groups": ["organization_like"], "cn_terms": ["保险公司", "证券公司", "金融机构"]},
    "FIN_MERCHANT_ID": {"cn": "商户号", "label": "商户号", "groups": ["account_like"], "cn_terms": ["商户号", "门店号"]},
    "FIN_RISK_RATING": {"cn": "风险评级", "label": "风险评级", "cn_terms": ["信用评级", "风险等级", "风险评级"]},
    "FIN_TRANSACTION_ID": {"cn": "交易流水号", "label": "交易流水号", "groups": ["account_like"], "cn_terms": ["交易流水号", "支付单号", "流水号"]},
    "GENDER": {"cn": "性别", "label": "性别", "groups": ["person_like"], "cn_terms": ["性别"]},
    "GEN_ACCOUNT_TRANSACTION": {"cn": "账户与交易", "label": "账户与交易", "groups": ["account_like"], "cn_terms": ["账户与交易"]},
    "GEN_ADDRESS_LOCATION": {"cn": "地址位置", "label": "地址位置", "groups": ["address_like"], "cn_terms": ["地址位置"]},
    "GEN_AMOUNT_VALUE": {"cn": "金额数值", "label": "金额数值", "groups": ["account_like"], "cn_terms": ["金额数值"]},
    "GEN_ASSET_RESOURCE": {"cn": "资产资源与标的物", "label": "资产资源与标的物", "cn_terms": ["资产资源与标的物"]},
    "GEN_ATTRIBUTE_STATUS": {"cn": "属性状态", "label": "属性状态", "cn_terms": ["属性状态"]},
    "GEN_CONTACT": {"cn": "联系方式", "label": "联系方式", "cn_terms": ["联系方式"]},
    "GEN_CREDENTIAL_ACCESS": {"cn": "凭证密钥与访问控制", "label": "凭证密钥与访问控制", "groups": ["credential_like"], "cn_terms": ["凭证密钥与访问控制"]},
    "GEN_DATE_TIME": {"cn": "日期时间", "label": "日期时间", "groups": ["date_like"], "cn_terms": ["日期时间"]},
    "GEN_DOCUMENT_RECORD": {"cn": "文档内容与业务记录", "label": "文档内容与业务记录", "cn_terms": ["文档内容与业务记录"]},
    "GEN_NAME": {"cn": "名称", "label": "名称", "cn_terms": ["名称", "通用名称"]},
    "GEN_NUMBER_CODE": {"cn": "号码/编号/代码", "label": "号码/编号/代码", "groups": ["identifier_like"], "cn_terms": ["代码", "号码", "号码/编号/代码", "编号"]},
    "GEN_ORGANIZATION_SUBJECT": {"cn": "组织主体", "label": "组织主体", "groups": ["organization_like"], "cn_terms": ["组织主体"]},
    "GEN_PERSON_SUBJECT": {"cn": "人员主体", "label": "人员主体", "groups": ["person_like"], "cn_terms": ["人员主体"]},
    "GEN_VISUAL_SEMANTIC": {"cn": "视觉语义补充", "label": "视觉语义补充", "cn_terms": ["视觉语义补充"]},
    "GOVERNMENT_AGENCY": {"cn": "机关单位", "label": "机关单位", "groups": ["organization_like"], "cn_terms": ["政府机关", "机关单位", "监管部门", "行政机关"]},
    "GPS_LOCATION": {"cn": "定位位置", "label": "定位位置", "groups": ["address_like"], "id_aliases": ["GEO_LOCATION", "LOCATION"], "cn_terms": ["GPS坐标", "定位", "定位位置", "经纬度"]},
    "HEALTH_INFO": {"cn": "健康信息", "label": "健康信息"},
    "ID_CARD": {"cn": "身份证号", "label": "身份证号", "groups": ["identifier_like", "person_like"], "id_aliases": ["DRIVER_LICENSE", "EMPLOYEE_ID", "MILITARY_ID"], "cn_terms": ["身份证", "身份证号", "身份证号码"]},
    "INPATIENT_NO": {"cn": "住院号", "label": "住院号", "groups": ["identifier_like"], "cn_terms": ["住院号", "入院号", "住院登记号"]},
    "INSTITUTION_NAME": {"cn": "机构名称", "label": "机构名称", "groups": ["organization_like"], "id_aliases": ["INSTITUTION"], "cn_terms": ["单位", "单位名称", "机构", "机构名称"]},
    "IP_ADDRESS": {"cn": "IP地址", "label": "IP地址", "groups": ["credential_like", "identifier_like"], "cn_terms": ["IP地址"]},
    "JUDGE": {"label": "法官", "cn_terms": ["书记员", "审判长", "法官"]},
    "LAWYER": {"label": "律师", "cn_terms": ["代理人"]},
    "LEGAL_ATTORNEY": {"cn": "代理律师", "label": "代理律师", "groups": ["person_like"], "id_aliases": ["LAWYER"], "cn_terms": ["代理律师", "律师", "诉讼代理人", "辩护人"]},
    "LEGAL_CASE_ID": {"cn": "案号", "label": "案号"},
    "LEGAL_CLAIM": {"cn": "诉讼请求", "label": "诉讼请求", "cn_terms": ["仲裁请求", "执行请求", "诉讼请求"]},
    "LEGAL_COURT": {"cn": "法院", "label": "法院", "groups": ["organization_like"], "cn_terms": ["人民法院", "仲裁机构", "法院"]},
    "LEGAL_DEFENDANT": {"cn": "被告", "label": "被告", "groups": ["organization_like", "person_like"], "cn_terms": ["被上诉人", "被告", "被执行人", "被申请人"]},
    "LEGAL_LAW_FIRM": {"cn": "律所", "label": "律所", "groups": ["organization_like"], "cn_terms": ["律师事务所", "律所"]},
    "LEGAL_PARTY": {"label": "当事人", "cn_terms": ["当事人"]},
    "LEGAL_PLAINTIFF": {"cn": "原告", "label": "原告", "groups": ["organization_like", "person_like"], "cn_terms": ["上诉人", "原告", "申请人"]},
    "LEGAL_THIRD_PARTY": {"cn": "第三人", "label": "第三人", "groups": ["organization_like", "person_like"], "cn_terms": ["利害关系人", "案外人", "第三人"]},
    "LICENSE_PLATE": {"cn": "车牌号", "label": "车牌号", "groups": ["identifier_like"], "cn_terms": ["车牌", "车牌号"]},
    "MAC_ADDRESS": {"label": "MAC地址"},
    "MARITAL_STATUS": {"cn": "婚姻状态", "label": "婚姻状态", "groups": ["person_like"], "cn_terms": ["婚姻状况", "婚姻状态"]},
    "MEDICAL_RECORD": {"label": "病历号"},
    "MED_ALLERGY_HISTORY": {"cn": "过敏史", "label": "过敏史", "cn_terms": ["过敏史"]},
    "MED_CHIEF_COMPLAINT": {"cn": "主诉", "label": "主诉", "cn_terms": ["主诉"]},
    "MED_CLINICIAN": {"cn": "医务人员", "label": "医务人员", "groups": ["person_like"], "cn_terms": ["医务人员", "医生", "护士"]},
    "MED_DEPARTMENT": {"cn": "科室", "label": "科室", "groups": ["organization_like"], "cn_terms": ["病区"]},
    "MED_DIAGNOSIS": {"cn": "诊断", "label": "诊断", "id_aliases": ["HEALTH_INFO", "MEDICAL_INFO"], "cn_terms": ["健康信息", "医疗信息", "疾病", "诊断"]},
    "MED_EXAM_RESULT": {"cn": "检查结果", "label": "检查结果", "cn_terms": ["检查结果", "检验结果"]},
    "MED_INSTITUTION": {"cn": "医疗机构", "label": "医疗机构", "groups": ["organization_like"], "cn_terms": ["医疗机构", "医院", "诊所"]},
    "MED_MEDICATION": {"cn": "用药", "label": "用药", "cn_terms": ["用药", "药品"]},
    "MED_ORDER": {"cn": "医嘱", "label": "医嘱", "cn_terms": ["医嘱"]},
    "MED_PAST_HISTORY": {"cn": "既往史", "label": "既往史", "cn_terms": ["既往史"]},
    "MED_PATIENT": {"cn": "患者", "label": "患者", "groups": ["person_like"], "cn_terms": ["受检者", "就诊人", "患者"]},
    "MED_PRESENT_ILLNESS": {"cn": "现病史", "label": "现病史", "cn_terms": ["现病史"]},
    "MED_PROCEDURE": {"cn": "医疗操作", "label": "医疗操作", "cn_terms": ["医疗操作", "手术"]},
    "MED_RECORD_ID": {"cn": "病历号", "label": "病历号", "groups": ["identifier_like"], "id_aliases": ["MEDICAL_RECORD"], "cn_terms": ["就诊号", "就诊卡号", "病历号", "门诊号"]},
    "MED_VITAL_SIGN": {"cn": "生命体征", "label": "生命体征", "cn_terms": ["体温", "生命体征", "血压"]},
    "NATIONALITY": {"cn": "国籍", "label": "国籍", "groups": ["person_like"], "cn_terms": ["国籍"]},
    "NATIVE_PLACE": {"cn": "籍贯", "label": "籍贯", "groups": ["person_like"], "cn_terms": ["籍贯"]},
    "OCCUPATION": {"cn": "职业", "label": "职业", "groups": ["person_like"], "cn_terms": ["职业", "工种"]},
    "ORG": {"cn": "组织机构", "label": "组织机构", "groups": ["organization_like"], "id_aliases": ["ORGANISATION", "ORGANISATION_NAME", "ORGANIZATION", "ORGANIZATION_NAME", "ORG_NAME"], "cn_terms": ["组织", "组织机构"]},
    "PASSPORT": {"cn": "护照号", "label": "护照号", "groups": ["identifier_like", "person_like"], "cn_terms": ["护照", "护照号", "护照号码"]},
    "PERSON": {"cn": "姓名", "label": "姓名", "groups": ["person_like"], "id_aliases": ["LEGAL_PARTY"], "cn_terms": ["人名", "人员姓名", "名字", "姓名", "户名", "账户名"]},
    "PERSONAL_ATTRIBUTE": {"cn": "出生日期"},
    "PHONE": {"cn": "电话", "label": "电话", "groups": ["person_like"], "cn_terms": ["手机", "手机号", "电话", "电话号码"]},
    "POLITICAL": {"cn": "政治面貌", "label": "政治面貌", "groups": ["person_like"], "id_aliases": ["UNION_MEMBERSHIP"], "cn_terms": ["政治观点", "政治面貌"]},
    "POSTAL_CODE": {"cn": "邮政编码", "label": "邮政编码", "groups": ["address_like"], "cn_terms": ["邮编", "邮政编码"]},
    "PROJECT_NAME": {"cn": "项目名称", "label": "项目名称", "groups": ["organization_like"], "cn_terms": ["课题名称", "项目", "项目名称"]},
    "PROPERTY": {"label": "财产"},
    "REGISTRATION_NO": {"cn": "登记号", "label": "登记号", "groups": ["identifier_like"], "cn_terms": ["登记号", "登记编号", "挂号登记号"]},
    "RELIGION": {"cn": "宗教信仰", "label": "宗教信仰", "groups": ["person_like"], "cn_terms": ["信仰", "宗教", "宗教信仰"]},
    "SEXUAL_ORIENTATION": {"cn": "性取向", "label": "性取向", "groups": ["person_like"], "cn_terms": ["性取向", "性生活"]},
    "SOCIAL_SECURITY": {"cn": "社保号", "label": "社保号", "groups": ["identifier_like", "person_like"], "cn_terms": ["医保号", "社保卡号", "社保号"]},
    "TAX_ID": {"cn": "税号", "label": "税号", "groups": ["identifier_like", "organization_like"], "cn_terms": ["税务登记号", "税号", "纳税人识别号"]},
    "TIME": {"cn": "时间", "label": "时间", "groups": ["date_like"], "cn_terms": ["时刻", "时间"]},
    "URL_WEBSITE": {"cn": "网址", "label": "网址", "groups": ["credential_like", "identifier_like"], "id_aliases": ["COOKIE", "LINK", "URL", "WEBSITE"], "cn_terms": ["域名", "网址", "网址/链接", "网址_链接", "网址链接", "链接"]},
    "USERNAME_PASSWORD": {"cn": "登录账号", "label": "登录账号", "groups": ["credential_like"], "id_aliases": ["ACCOUNT_NAME", "ACCOUNT_NUMBER", "CUSTOMER_ID", "MEMBER_ID", "QQ_WECHAT_ID", "USERNAME", "USER_NAME"], "cn_terms": ["会员号", "客户号", "用户ID", "用户名", "用户名/密码", "用户名_密码", "用户名密码", "登录密码", "登录账号", "账号", "账号密码", "账户", "账户密码"]},
    "VIN": {"cn": "车架号", "label": "车架号", "groups": ["identifier_like"], "id_aliases": ["CHASSIS_NUMBER", "FRAME_NUMBER", "VEHICLE_IDENTIFICATION_NUMBER", "VEHICLE_VIN", "VIN_NUMBER"], "cn_terms": ["VIN", "车架号", "车架号/VIN", "车架号_VIN", "车辆识别代号", "车辆识别码"]},
    "WECHAT_ALIPAY": {"label": "支付账号"},
    "WITNESS": {"label": "证人", "cn_terms": ["证人"]},
    "WORK_UNIT": {"cn": "工作单位", "label": "工作单位", "groups": ["organization_like"], "id_aliases": ["EMPLOYER", "WORKPLACE"], "cn_terms": ["任职单位", "就职单位", "工作单位", "所在单位"]},
}

# ── Derived maps (do NOT edit — change TYPE_REGISTRY above) ──────────────────
TYPE_ID_TO_CN: dict[str, str] = {tid: e["cn"] for tid, e in TYPE_REGISTRY.items() if e.get("cn")}
TYPE_ID_TO_LABEL: dict[str, str] = {tid: e["label"] for tid, e in TYPE_REGISTRY.items() if e.get("label")}
LINKAGE_GROUP_BY_TYPE_ID: dict[str, set[str]] = {tid: set(e["groups"]) for tid, e in TYPE_REGISTRY.items() if e.get("groups")}
TYPE_ID_ALIASES: dict[str, str] = {a: tid for tid, e in TYPE_REGISTRY.items() for a in e.get("id_aliases", [])}
TYPE_CN_TO_ID: dict[str, str] = {c: tid for tid, e in TYPE_REGISTRY.items() for c in e.get("cn_terms", [])}


def linkage_groups_for_type(type_id: str) -> set[str]:
    """Return internal linkage groups without changing the public type id."""
    canonical = canonical_type_id(type_id)
    return set(LINKAGE_GROUP_BY_TYPE_ID.get(canonical, set()))


def linkage_group_for_type(type_id: str) -> str:
    """Return a stable primary linkage group for legacy single-group callers."""
    groups = linkage_groups_for_type(type_id)
    return sorted(groups)[0] if groups else ""


def has_query_labels_for(type_id: str) -> list[str]:
    """The Chinese label sent to the open-vocabulary HaS prompt for a schema item
    — just the item's own label. Whatever you name it is what the model is asked
    to find, and whatever it returns is the type (识别出来是啥就是啥)."""
    return [id_to_cn(canonical_type_id(type_id))]


def cn_to_id(chinese_type: str) -> str:
    """中文类型名转英文 ID，未知类型返回大写原文。"""
    return canonical_type_id(TYPE_CN_TO_ID.get(chinese_type, chinese_type.upper()))


def id_to_label(type_id: str, default: str = "敏感信息") -> str:
    """英文类型 ID 转中文标签，用于 smart 替换。"""
    return TYPE_ID_TO_LABEL.get(canonical_type_id(type_id), default)


def id_to_cn(type_id: str) -> str:
    """英文类型 ID 转中文类型名（用于 HaS prompt）。"""
    canonical = canonical_type_id(type_id)
    return TYPE_ID_TO_CN.get(canonical, canonical)


def canonical_type_id(type_id: str) -> str:
    """Return the canonical public type ID for deprecated aliases."""
    normalized = str(type_id or "").strip().upper().replace("-", "_").replace(" ", "_").replace("/", "_")
    return TYPE_ID_ALIASES.get(normalized, normalized)


def canonical_type_ids(type_ids: list[str | None] | tuple[str | None, ...]) -> list[str]:
    """Return stable de-duplicated canonical type IDs."""
    canonical_ids: list[str] = []
    seen: set[str] = set()
    for type_id in type_ids:
        canonical = canonical_type_id(type_id or "")
        if canonical and canonical not in seen:
            seen.add(canonical)
            canonical_ids.append(canonical)
    return canonical_ids
