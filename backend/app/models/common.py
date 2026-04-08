"""
Common enums, base models, and generic API response schemas.
"""
from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum
from datetime import datetime

__all__ = [
    "IdentifierCategory",
    "EntityType",
    "FileType",
    "ReplacementMode",
    "APIResponse",
    "HealthResponse",
    "ToggleResponse",
    "MessageResponse",
    "PasswordRequest",
    "ChangePasswordRequest",
    "TokenResponse",
    "AuthStatusResponse",
]


class IdentifierCategory(str, Enum):
    """
    标识符类别 - 基于 GB/T 37964-2019《信息安全技术 个人信息去标识化指南》
    """
    DIRECT = "direct"           # 直接标识符：能够单独识别个人信息主体
    QUASI = "quasi"             # 准标识符：与其他信息结合可识别个人信息主体
    SENSITIVE = "sensitive"     # 敏感属性：涉及敏感信息的属性
    OTHER = "other"             # 其他一般属性


class EntityType(str, Enum):
    """
    实体类型枚举 - 基于 GB/T 37964-2019 分类体系

    分类说明：
    - 直接标识符(D)：能够单独识别特定自然人，如姓名、身份证号
    - 准标识符(Q)：与其他信息结合可识别特定自然人，如年龄、地址
    - 敏感属性(S)：涉及敏感信息，如健康状况、财务状况
    """
    # === 直接标识符 (Direct Identifiers) ===
    PERSON = "PERSON"                   # [D] 姓名
    ID_CARD = "ID_CARD"                 # [D] 身份证号
    PASSPORT = "PASSPORT"               # [D] 护照号
    SOCIAL_SECURITY = "SOCIAL_SECURITY" # [D] 社保号/医保号
    DRIVER_LICENSE = "DRIVER_LICENSE"   # [D] 驾驶证号
    PHONE = "PHONE"                     # [D] 电话号码
    EMAIL = "EMAIL"                     # [D] 电子邮箱
    BANK_CARD = "BANK_CARD"             # [D] 银行卡号
    BANK_ACCOUNT = "BANK_ACCOUNT"       # [D] 银行账号
    WECHAT_ALIPAY = "WECHAT_ALIPAY"     # [D] 微信/支付宝账号
    IP_ADDRESS = "IP_ADDRESS"           # [D] IP地址
    MAC_ADDRESS = "MAC_ADDRESS"         # [D] MAC地址
    DEVICE_ID = "DEVICE_ID"             # [D] 设备标识
    BIOMETRIC = "BIOMETRIC"             # [D] 生物特征
    LEGAL_PARTY = "LEGAL_PARTY"         # [D] 案件当事人
    LAWYER = "LAWYER"                   # [D] 律师/代理人
    JUDGE = "JUDGE"                     # [D] 法官/书记员
    WITNESS = "WITNESS"                 # [D] 证人

    # === 准标识符 (Quasi-Identifiers) ===
    BIRTH_DATE = "BIRTH_DATE"           # [Q] 出生日期
    AGE = "AGE"                         # [Q] 年龄
    GENDER = "GENDER"                   # [Q] 性别
    NATIONALITY = "NATIONALITY"         # [Q] 国籍/民族
    ADDRESS = "ADDRESS"                 # [Q] 详细地址
    POSTAL_CODE = "POSTAL_CODE"         # [Q] 邮政编码
    GPS_LOCATION = "GPS_LOCATION"       # [Q] GPS坐标
    OCCUPATION = "OCCUPATION"           # [Q] 职业/职务
    EDUCATION = "EDUCATION"             # [Q] 教育背景
    WORK_UNIT = "WORK_UNIT"             # [Q] 工作单位
    DATE = "DATE"                       # [Q] 日期
    TIME = "TIME"                       # [Q] 时间
    LICENSE_PLATE = "LICENSE_PLATE"     # [Q] 车牌号
    VIN = "VIN"                         # [Q] 车架号/VIN
    CASE_NUMBER = "CASE_NUMBER"         # [Q] 案件编号
    CONTRACT_NO = "CONTRACT_NO"         # [Q] 合同编号
    ORG = "ORG"                         # [Q] 机构名称
    COMPANY_CODE = "COMPANY_CODE"       # [Q] 统一社会信用代码

    # === 敏感属性 (Sensitive Attributes) ===
    HEALTH_INFO = "HEALTH_INFO"         # [S] 健康信息
    MEDICAL_RECORD = "MEDICAL_RECORD"   # [S] 病历号/就诊号
    AMOUNT = "AMOUNT"                   # [S] 金额/财务数据
    PROPERTY = "PROPERTY"               # [S] 财产信息
    CRIMINAL_RECORD = "CRIMINAL_RECORD" # [S] 犯罪记录
    POLITICAL = "POLITICAL"             # [S] 政治面貌
    RELIGION = "RELIGION"               # [S] 宗教信仰

    # === 其他 ===
    CUSTOM = "CUSTOM"                   # 自定义类型


class FileType(str, Enum):
    """文件类型枚举"""
    DOC = "doc"              # 旧版 Word (.doc)
    DOCX = "docx"            # 新版 Word (.docx)
    TXT = "txt"              # 纯文本 (.txt, .md, .rtf, .html)
    PDF = "pdf"
    PDF_SCANNED = "pdf_scanned"  # 扫描版 PDF
    IMAGE = "image"


class ReplacementMode(str, Enum):
    """替换模式"""
    SMART = "smart"      # 智能替换 (当事人甲、当事人乙)
    MASK = "mask"        # 掩码替换 (***)
    CUSTOM = "custom"    # 自定义替换
    STRUCTURED = "structured"  # 结构化语义标签


# ============ 通用响应 ============

class APIResponse(BaseModel):
    """通用 API 响应"""
    success: bool = True
    message: str = "操作成功"
    data: Optional[dict] = None
    error: Optional[str] = None


class HealthResponse(BaseModel):
    """健康检查响应"""
    status: str = "healthy"
    version: str
    timestamp: datetime = Field(default_factory=datetime.now)


class ToggleResponse(BaseModel):
    """启用/禁用切换响应"""
    enabled: bool


class MessageResponse(BaseModel):
    """简单消息响应"""
    message: str


# ─── Auth Models ───

class PasswordRequest(BaseModel):
    password: str


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class AuthStatusResponse(BaseModel):
    auth_enabled: bool
    password_set: bool
