"""
实体类型映射 —— 单一数据源

统一维护中英文实体类型映射，消除 redactor / has_service / has_client / hybrid_vision_service 中的重复定义。
基于 GB/T 37964-2019《信息安全技术 个人信息去标识化指南》。
"""

# ──────────────────────────────────────────────
# 英文类型 ID → 中文标签（用于 smart 替换、提示等）
# ──────────────────────────────────────────────
TYPE_ID_TO_LABEL: dict[str, str] = {
    # 直接标识符
    "PERSON": "当事人",
    "ID_CARD": "证件号",
    "PASSPORT": "护照号",
    "PHONE": "电话",
    "EMAIL": "邮箱",
    "BANK_CARD": "账号",
    "BANK_ACCOUNT": "银行账号",
    "BANK_NAME": "开户行",
    "SOCIAL_SECURITY": "社保号",
    "WECHAT_ALIPAY": "支付账号",
    "IP_ADDRESS": "IP地址",
    "MAC_ADDRESS": "MAC地址",
    "DEVICE_ID": "设备号",
    "BIOMETRIC": "生物特征",
    "LEGAL_PARTY": "当事人",
    "LAWYER": "律师",
    "JUDGE": "法官",
    "WITNESS": "证人",
    # 准标识符
    "ORG": "公司",
    "COMPANY": "公司",
    "ADDRESS": "地址",
    "BIRTH_DATE": "出生日期",
    "DATE": "日期",
    "LICENSE_PLATE": "车牌",
    "CASE_NUMBER": "案号",
    "CONTRACT_NO": "合同编号",
    "COMPANY_CODE": "信用代码",
    "VIN": "车架号",
    # 敏感属性
    "AMOUNT": "金额",
    "MONEY": "金额",
    "HEALTH_INFO": "健康信息",
    "MEDICAL_RECORD": "病历号",
    "PROPERTY": "财产",
    "CRIMINAL_RECORD": "犯罪记录",
    # 通用
    "CUSTOM": "敏感信息",
}

# ──────────────────────────────────────────────
# 中文类型名 → 英文类型 ID（用于 HaS NER 结果转换）
# 支持多个中文别名映射到同一 ID
# ──────────────────────────────────────────────
TYPE_CN_TO_ID: dict[str, str] = {
    # 直接标识符
    "人名": "PERSON", "姓名": "PERSON", "名字": "PERSON",
    "账户名": "PERSON", "户名": "PERSON",
    "身份证号": "ID_CARD", "身份证": "ID_CARD", "身份证号码": "ID_CARD",
    "护照号": "PASSPORT", "护照": "PASSPORT", "护照号码": "PASSPORT",
    "电话号码": "PHONE", "电话": "PHONE", "手机号": "PHONE",
    "联系方式": "PHONE", "手机": "PHONE",
    "电子邮箱": "EMAIL", "邮箱": "EMAIL", "邮件": "EMAIL",
    "银行卡号": "BANK_CARD", "银行卡": "BANK_CARD", "卡号": "BANK_CARD",
    "银行账号": "BANK_ACCOUNT", "账号": "BANK_ACCOUNT",
    "账户号": "BANK_ACCOUNT", "账户号码": "BANK_ACCOUNT",
    "开户行": "BANK_NAME", "开户银行": "BANK_NAME",
    "银行名称": "BANK_NAME", "银行": "BANK_NAME",
    "社保号": "SOCIAL_SECURITY", "社保卡号": "SOCIAL_SECURITY",
    "医保号": "SOCIAL_SECURITY",
    # 准标识符
    "公司名称": "COMPANY", "公司": "COMPANY", "公司名": "COMPANY",
    "企业": "COMPANY", "企业名称": "COMPANY",
    "甲方": "COMPANY", "乙方": "COMPANY", "丙方": "COMPANY",
    "发包方": "COMPANY", "承包方": "COMPANY",
    "出借人": "COMPANY", "借款人": "COMPANY",
    "出卖人": "COMPANY", "买受人": "COMPANY",
    "委托方": "COMPANY", "受托方": "COMPANY",
    "供应商": "COMPANY", "承揽方": "COMPANY",
    "转让方": "COMPANY", "受让方": "COMPANY",
    "组织": "ORG", "机构名称": "ORG", "组织机构": "ORG",
    "机构": "ORG", "单位": "ORG",
    "地址": "ADDRESS", "详细地址": "ADDRESS",
    "住址": "ADDRESS", "居住地": "ADDRESS",
    "出生日期": "BIRTH_DATE", "生日": "BIRTH_DATE",
    "日期": "DATE", "时间": "DATE", "日期时间": "DATE",
    "车牌号": "LICENSE_PLATE", "车牌": "LICENSE_PLATE",
    "案件编号": "CASE_NUMBER", "案号": "CASE_NUMBER",
    "合同编号": "CONTRACT_NO", "合同号": "CONTRACT_NO",
    "统一社会信用代码": "COMPANY_CODE", "信用代码": "COMPANY_CODE",
    # 敏感属性
    "金额": "AMOUNT", "数额": "AMOUNT", "款项": "AMOUNT",
    # 法律文书
    "当事人": "LEGAL_PARTY", "原告": "LEGAL_PARTY", "被告": "LEGAL_PARTY",
    "律师": "LAWYER", "代理人": "LAWYER",
    "法官": "JUDGE", "审判长": "JUDGE", "书记员": "JUDGE",
    "证人": "WITNESS",
    # 文件/杂项
    "文件": "DOCUMENT",
    "密码": "PASSWORD",
}

# 反向映射：英文 ID → 首选中文名（取第一个匹配）
TYPE_ID_TO_CN: dict[str, str] = {}
for _cn, _id in TYPE_CN_TO_ID.items():
    if _id not in TYPE_ID_TO_CN:
        TYPE_ID_TO_CN[_id] = _cn


def cn_to_id(chinese_type: str) -> str:
    """中文类型名转英文 ID，未知类型返回大写原文。"""
    return TYPE_CN_TO_ID.get(chinese_type, chinese_type.upper())


def id_to_label(type_id: str, default: str = "敏感信息") -> str:
    """英文类型 ID 转中文标签，用于 smart 替换。"""
    return TYPE_ID_TO_LABEL.get(type_id, default)


def id_to_cn(type_id: str) -> str:
    """英文类型 ID 转中文类型名（用于 HaS prompt）。"""
    return TYPE_ID_TO_CN.get(type_id, type_id)
