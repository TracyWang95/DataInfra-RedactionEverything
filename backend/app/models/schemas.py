"""
Pydantic 数据模型定义
"""
from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, Literal
from enum import Enum
from datetime import datetime


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


# ============ 自定义实体类型 ============

class CustomEntityType(BaseModel):
    """自定义实体类型定义"""
    id: str = Field(..., description="类型唯一ID")
    name: str = Field(..., description="类型名称，如'涉案金额'")
    description: str = Field(default="", description="语义描述，用于AI理解")
    examples: list[str] = Field(default_factory=list, description="示例文本，帮助AI识别")
    color: str = Field(default="#6B7280", description="显示颜色")
    replacement_template: str = Field(default="[{name}]", description="替换模板")
    enabled: bool = Field(default=True, description="是否启用")
    created_at: datetime = Field(default_factory=datetime.now)


class CustomEntityTypeCreate(BaseModel):
    """创建自定义实体类型请求"""
    name: str = Field(..., description="类型名称")
    description: str = Field(..., description="语义描述，用于AI理解匹配")
    examples: list[str] = Field(default_factory=list, description="示例文本")
    color: str = Field(default="#6B7280", description="显示颜色")
    replacement_template: str = Field(default="[{name}]", description="替换模板")


class CustomEntityTypeUpdate(BaseModel):
    """更新自定义实体类型请求"""
    name: Optional[str] = None
    description: Optional[str] = None
    examples: Optional[list[str]] = None
    color: Optional[str] = None
    replacement_template: Optional[str] = None
    enabled: Optional[bool] = None


# ============ 请求模型 ============

class Entity(BaseModel):
    """识别到的实体"""
    id: str = Field(..., description="实体唯一ID")
    text: str = Field(..., description="原始文本")
    type: str = Field(..., description="实体类型（内置类型或自定义类型ID）")
    start: int = Field(..., description="起始位置")
    end: int = Field(..., description="结束位置")
    page: int = Field(default=1, description="所在页码")
    confidence: float = Field(default=1.0, description="置信度")
    source: Optional[Literal["regex", "llm", "manual", "has"]] = Field(
        default=None, description="实体来源"
    )
    coref_id: Optional[str] = Field(None, description="指代消解ID")
    replacement: Optional[str] = Field(None, description="替换文本")
    selected: bool = Field(default=True, description="是否选中进行脱敏")
    custom_type_id: Optional[str] = Field(None, description="自定义类型ID（如果是自定义类型）")


class BoundingBox(BaseModel):
    """图片中的敏感区域边界框"""
    id: str = Field(..., description="区域唯一ID")
    x: float = Field(..., description="左上角 X 坐标")
    y: float = Field(..., description="左上角 Y 坐标")
    width: float = Field(..., description="宽度")
    height: float = Field(..., description="高度")
    page: int = Field(default=1, description="所在页码")
    type: str = Field(..., description="实体类型")
    text: Optional[str] = Field(None, description="识别到的文本")
    selected: bool = Field(default=True, description="是否选中进行脱敏")
    source: Optional[Literal["ocr_has", "has_image", "manual"]] = Field(
        default=None, description="来源: ocr_has=OCR+HaS, has_image=HaS Image YOLO, manual=手动"
    )


class RedactionConfig(BaseModel):
    """脱敏配置"""
    replacement_mode: ReplacementMode = Field(default=ReplacementMode.SMART)
    entity_types: list[str] = Field(
        default=["PERSON", "PHONE", "ID_CARD"]
    )
    custom_entity_types: list[str] = Field(
        default_factory=list, description="启用的自定义实体类型ID列表"
    )
    custom_replacements: dict[str, str] = Field(default_factory=dict)
    # 图片 / 扫描件块级脱敏（与 HaS Image 文档一致：mosaic / blur / fill），与文本 replacement_mode 独立
    image_redaction_method: Optional[Literal["mosaic", "blur", "fill"]] = Field(
        default=None,
        description="图片类：马赛克、高斯模糊、纯色填充；未传时图片仍按 fill 处理",
    )
    image_redaction_strength: int = Field(
        default=25,
        ge=1,
        le=100,
        description="马赛克块尺寸 / 模糊半径的相对强度（1–100）",
    )
    image_fill_color: str = Field(
        default="#000000",
        description="fill 模式填充色（#RRGGBB）",
    )


class RedactionRequest(BaseModel):
    """脱敏请求"""
    file_id: str = Field(..., description="文件ID")
    entities: list[Entity] = Field(default_factory=list, description="要脱敏的实体列表")
    bounding_boxes: list[BoundingBox] = Field(default_factory=list, description="要脱敏的图片区域")
    config: RedactionConfig = Field(default_factory=RedactionConfig)


class PreviewEntityMapRequest(BaseModel):
    """仅预览替换映射（不落盘）"""
    entities: list[Entity] = Field(default_factory=list)
    config: RedactionConfig = Field(default_factory=RedactionConfig)


class PreviewEntityMapResponse(BaseModel):
    entity_map: dict[str, str] = Field(default_factory=dict, description="与 execute 一致的原文→替换表")


class PreviewImageRequest(BaseModel):
    bounding_boxes: list[BoundingBox] = Field(default_factory=list)
    config: RedactionConfig = Field(default_factory=RedactionConfig)


class PreviewImageResponse(BaseModel):
    file_id: str
    page: int
    image_base64: str


class NERRequest(BaseModel):
    """NER识别请求"""
    entity_types: list[str] = Field(
        default=["PERSON", "PHONE", "ID_CARD", "ORG", "CASE_NUMBER"],
        description="要识别的内置实体类型"
    )
    custom_entity_type_ids: list[str] = Field(
        default_factory=list,
        description="要识别的自定义实体类型ID列表"
    )


# ============ 响应模型 ============

class FileUploadResponse(BaseModel):
    """文件上传响应"""
    file_id: str
    filename: str
    file_type: FileType
    file_size: int
    page_count: int = 1
    message: str = "文件上传成功"
    created_at: Optional[datetime] = None


class JobItemMini(BaseModel):
    """列表嵌套用：与任务详情 CTA 解析一致的最小 item 字段"""

    model_config = ConfigDict(extra="ignore")

    id: str
    status: str


class JobProgress(BaseModel):
    model_config = ConfigDict(extra="ignore")

    total_items: int = 0
    pending: int = 0
    queued: int = 0
    parsing: int = 0
    ner: int = 0
    vision: int = 0
    awaiting_review: int = 0
    review_approved: int = 0
    redacting: int = 0
    completed: int = 0
    failed: int = 0
    cancelled: int = 0


class JobEmbedSummary(BaseModel):
    """GET /files?embed_job=1 时按 job_id 去重注入，减少前端逐条 getJob"""

    model_config = ConfigDict(extra="ignore")

    status: str
    job_type: Literal["text_batch", "image_batch", "smart_batch"]
    items: list[JobItemMini] = Field(default_factory=list)
    progress: JobProgress = Field(default_factory=JobProgress)
    wizard_furthest_step: Optional[int] = Field(
        default=None,
        description="来自任务 config，供历史页主 CTA 与任务中心「继续上传」一致",
    )
    first_awaiting_review_item_id: Optional[str] = Field(
        default=None,
        description="与 /jobs 列表 nav_hints 一致，待审 deep-link 用",
    )
    batch_step1_configured: bool = Field(
        default=False,
        description="config 已含识别项选择，与 nav_hints.batch_step1_configured 一致",
    )


class FileListItem(BaseModel):
    """文件列表项（处理历史）"""
    file_id: str
    original_filename: str
    file_size: int
    file_type: FileType
    created_at: Optional[str] = None
    has_output: bool = False
    entity_count: int = 0
    upload_source: Literal["playground", "batch"] = Field(
        default="playground",
        description="playground=Playground 单文件；batch=批量向导或任务工单上传",
    )
    job_id: Optional[str] = Field(
        default=None,
        description="若上传时绑定任务中心 Job，则为该 Job UUID，可与 /api/v1/jobs/{id} 关联",
    )
    batch_group_id: Optional[str] = Field(
        default=None,
        description="批量向导同一会话上传的文件共享此 ID；Playground 单文件上传为 null",
    )
    batch_group_count: Optional[int] = Field(
        default=None,
        description="该批次在系统中的文件总数（仅 batch_group_id 非空时有意义）",
    )
    item_status: Optional[str] = Field(
        default=None,
        description="关联 job_item 的 pipeline 状态（awaiting_review / completed 等），用于三态脱敏显示",
    )
    item_id: Optional[str] = Field(
        default=None,
        description="关联 job_item 的 ID，用于构建审阅跳转 URL",
    )
    job_embed: Optional[JobEmbedSummary] = Field(
        default=None,
        description="embed_job=1 且存在 job_id 时返回，供历史页主 CTA 与任务中心一致",
    )


class FileListResponse(BaseModel):
    """文件列表响应（支持分页）"""
    files: list[FileListItem]
    total: int
    page: int = 1
    page_size: int = 20


class ParseResult(BaseModel):
    """文件解析结果"""
    file_id: str
    file_type: FileType
    content: str = Field(default="", description="提取的文本内容")
    page_count: int = 1
    pages: list[str] = Field(default_factory=list, description="分页文本内容")
    is_scanned: bool = Field(default=False, description="是否为扫描件")


class NERResult(BaseModel):
    """NER 识别结果"""
    file_id: str
    entities: list[Entity]
    entity_count: int
    entity_summary: dict[str, int] = Field(default_factory=dict, description="各类型实体数量统计")
    warnings: list[str] = Field(default_factory=list, description="识别过程中的警告信息")


class VisionResult(BaseModel):
    """视觉识别结果"""
    file_id: str
    page: int
    bounding_boxes: list[BoundingBox]
    result_image: Optional[str] = None  # 带检测框的图片 base64


class RedactionResult(BaseModel):
    """脱敏结果"""
    file_id: str
    output_file_id: str
    redacted_count: int
    entity_map: dict[str, str] = Field(default_factory=dict, description="实体映射表")
    download_url: str
    output_path: Optional[str] = Field(default=None, exclude=True)


class CompareData(BaseModel):
    """对比数据"""
    file_id: str
    original_content: str
    redacted_content: str
    changes: list[dict] = Field(default_factory=list)


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


# ============ 任务中心响应模型 ============

class NavHints(BaseModel):
    """任务导航提示"""
    model_config = ConfigDict(extra="allow")

    item_count: int = 0
    first_awaiting_review_item_id: Optional[str] = None
    batch_step1_configured: bool = False
    wizard_furthest_step: Optional[int] = None


class JobResponse(BaseModel):
    """任务摘要响应（_job_to_summary 返回值）"""
    model_config = ConfigDict(extra="ignore")

    id: str
    job_type: str
    title: str
    status: str
    priority: int = 0
    skip_item_review: bool = False
    config: dict = Field(default_factory=dict)
    config_json: Optional[str] = None
    error_message: Optional[str] = None
    created_at: str
    updated_at: str
    progress: JobProgress = Field(default_factory=JobProgress)
    nav_hints: Optional[NavHints] = None


class JobItemResponse(BaseModel):
    """任务项响应"""
    model_config = ConfigDict(extra="ignore")

    id: str
    job_id: str
    file_id: str
    sort_order: int = 0
    status: str
    error_message: Optional[str] = None
    reviewed_at: Optional[str] = None
    reviewer: Optional[str] = None
    review_draft_json: Optional[str] = None
    created_at: str
    updated_at: str
    filename: Optional[str] = None
    file_type: Optional[str] = None
    has_output: bool = False
    entity_count: int = 0
    has_review_draft: bool = False
    review_draft_updated_at: Optional[str] = None


class JobListResponse(BaseModel):
    """任务列表响应"""
    jobs: list[JobResponse]
    total: int
    page: int = 1
    page_size: int = 20


class JobProgressResponse(BaseModel):
    """任务进度响应（含 status 字段）"""
    model_config = ConfigDict(extra="ignore")

    status: str
    total_items: int = 0
    pending: int = 0
    queued: int = 0
    parsing: int = 0
    ner: int = 0
    vision: int = 0
    awaiting_review: int = 0
    review_approved: int = 0
    redacting: int = 0
    completed: int = 0
    failed: int = 0
    cancelled: int = 0


class JobDetailResponse(JobResponse):
    """任务详情+项列表响应（继承 JobResponse，追加 items）"""
    items: list[JobItemResponse] = Field(default_factory=list)


class JobDeleteResponse(BaseModel):
    """任务删除响应"""
    id: str
    deleted: bool = True
    deleted_item_count: int = 0
    detached_file_count: int = 0


class ReviewDraftResponse(BaseModel):
    """审核草稿响应"""
    model_config = ConfigDict(extra="ignore")

    exists: bool
    entities: list = Field(default_factory=list)
    bounding_boxes: list = Field(default_factory=list)
    updated_at: Optional[str] = None


# ============ 实体类型 / 脱敏端点响应 ============

class EntityTypeItem(BaseModel):
    """单个实体类型展示项"""
    value: str
    label: str
    color: str


class EntityTypeListResponse(BaseModel):
    """实体类型列表响应"""
    entity_types: list[EntityTypeItem]


class ReplacementModeItem(BaseModel):
    """单个替换模式展示项"""
    value: str
    label: str
    description: str


class ReplacementModeListResponse(BaseModel):
    """替换模式列表响应"""
    replacement_modes: list[ReplacementModeItem]


class ToggleResponse(BaseModel):
    """启用/禁用切换响应"""
    enabled: bool


class MessageResponse(BaseModel):
    """简单消息响应"""
    message: str


class RedactionVersionsResponse(BaseModel):
    """脱敏版本历史响应"""
    file_id: str
    versions: list[dict] = Field(default_factory=list)
    total: int = 0
