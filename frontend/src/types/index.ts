/**
 * 标识符类别 - 基于 GB/T 37964-2019《信息安全技术 个人信息去标识化指南》
 */
export enum IdentifierCategory {
  DIRECT = 'direct',       // 直接标识符：能够单独识别个人信息主体
  QUASI = 'quasi',         // 准标识符：与其他信息结合可识别个人信息主体
  SENSITIVE = 'sensitive', // 敏感属性：涉及敏感信息的属性
  OTHER = 'other',         // 其他一般属性
}

/**
 * 实体类型枚举 - 基于 GB/T 37964-2019 分类体系
 * 
 * 分类说明：
 * - 直接标识符(D)：能够单独识别特定自然人，如姓名、身份证号
 * - 准标识符(Q)：与其他信息结合可识别特定自然人，如年龄、地址
 * - 敏感属性(S)：涉及敏感信息，如健康状况、财务状况
 */
export enum EntityType {
  // === 直接标识符 (Direct Identifiers) ===
  PERSON = 'PERSON',                   // [D] 姓名
  ID_CARD = 'ID_CARD',                 // [D] 身份证号
  PASSPORT = 'PASSPORT',               // [D] 护照号
  SOCIAL_SECURITY = 'SOCIAL_SECURITY', // [D] 社保号/医保号
  DRIVER_LICENSE = 'DRIVER_LICENSE',   // [D] 驾驶证号
  PHONE = 'PHONE',                     // [D] 电话号码
  EMAIL = 'EMAIL',                     // [D] 电子邮箱
  BANK_CARD = 'BANK_CARD',             // [D] 银行卡号
  BANK_ACCOUNT = 'BANK_ACCOUNT',       // [D] 银行账号
  WECHAT_ALIPAY = 'WECHAT_ALIPAY',     // [D] 微信/支付宝账号
  IP_ADDRESS = 'IP_ADDRESS',           // [D] IP地址
  MAC_ADDRESS = 'MAC_ADDRESS',         // [D] MAC地址
  DEVICE_ID = 'DEVICE_ID',             // [D] 设备标识
  BIOMETRIC = 'BIOMETRIC',             // [D] 生物特征
  LEGAL_PARTY = 'LEGAL_PARTY',         // [D] 案件当事人
  LAWYER = 'LAWYER',                   // [D] 律师/代理人
  JUDGE = 'JUDGE',                     // [D] 法官/书记员
  WITNESS = 'WITNESS',                 // [D] 证人
  
  // === 准标识符 (Quasi-Identifiers) ===
  BIRTH_DATE = 'BIRTH_DATE',           // [Q] 出生日期
  AGE = 'AGE',                         // [Q] 年龄
  GENDER = 'GENDER',                   // [Q] 性别
  NATIONALITY = 'NATIONALITY',         // [Q] 国籍/民族
  ADDRESS = 'ADDRESS',                 // [Q] 详细地址
  POSTAL_CODE = 'POSTAL_CODE',         // [Q] 邮政编码
  GPS_LOCATION = 'GPS_LOCATION',       // [Q] GPS坐标
  OCCUPATION = 'OCCUPATION',           // [Q] 职业/职务
  EDUCATION = 'EDUCATION',             // [Q] 教育背景
  WORK_UNIT = 'WORK_UNIT',             // [Q] 工作单位
  DATE = 'DATE',                       // [Q] 日期
  TIME = 'TIME',                       // [Q] 时间
  LICENSE_PLATE = 'LICENSE_PLATE',     // [Q] 车牌号
  VIN = 'VIN',                         // [Q] 车架号/VIN
  CASE_NUMBER = 'CASE_NUMBER',         // [Q] 案件编号
  CONTRACT_NO = 'CONTRACT_NO',         // [Q] 合同编号
  ORG = 'ORG',                         // [Q] 机构名称
  COMPANY_CODE = 'COMPANY_CODE',       // [Q] 统一社会信用代码
  
  // === 敏感属性 (Sensitive Attributes) ===
  HEALTH_INFO = 'HEALTH_INFO',         // [S] 健康信息
  MEDICAL_RECORD = 'MEDICAL_RECORD',   // [S] 病历号/就诊号
  AMOUNT = 'AMOUNT',                   // [S] 金额/财务数据 (原MONEY)
  PROPERTY = 'PROPERTY',               // [S] 财产信息
  CRIMINAL_RECORD = 'CRIMINAL_RECORD', // [S] 犯罪记录
  POLITICAL = 'POLITICAL',             // [S] 政治面貌
  RELIGION = 'RELIGION',               // [S] 宗教信仰
  
  // === 其他 ===
  CUSTOM = 'CUSTOM',                   // 自定义类型
}

// 文件类型枚举
export enum FileType {
  DOC = 'doc',
  DOCX = 'docx',
  TXT = 'txt',
  PDF = 'pdf',
  PDF_SCANNED = 'pdf_scanned',
  IMAGE = 'image',
}

// 替换模式枚举
export enum ReplacementMode {
  SMART = 'smart',
  MASK = 'mask',
  CUSTOM = 'custom',
  STRUCTURED = 'structured',
}

/** 图片 / 扫描件块级脱敏（与 HaS Image：mosaic / blur / fill 一致），与文本 replacement_mode 独立 */
export type ImageRedactionMethod = 'mosaic' | 'blur' | 'fill';

// 实体接口
export interface Entity {
  id: string;
  text: string;
  type: EntityType;
  start: number;
  end: number;
  page: number;
  confidence: number;
  replacement?: string;
  selected: boolean;
}

// 图片敏感区域边界框
export interface BoundingBox {
  id: string;
  x: number;
  y: number;
  width: number;
  height: number;
  page: number;
  type: EntityType;
  text?: string;
  selected: boolean;
}

// 文件信息
export interface FileInfo {
  file_id: string;
  filename: string;
  file_type: FileType;
  file_size: number;
  page_count: number;
  content?: string;
  pages?: string[];
  is_scanned?: boolean;
  created_at?: string;
}

/** GET /files?embed_job=1 时注入，与任务详情主 CTA 一致 */
export interface JobItemMini {
  id: string;
  status: string;
}

export interface JobEmbedSummary {
  status: string;
  job_type: 'text_batch' | 'image_batch';
  items: JobItemMini[];
  /** 与任务列表 nav_hints 一致，去审核深链优先用 */
  first_awaiting_review_item_id?: string | null;
  /** GET /files?embed_job=1 时来自任务 config，与任务中心主 CTA 一致 */
  wizard_furthest_step?: number | null;
  /** 与 nav_hints.batch_step1_configured 一致 */
  batch_step1_configured?: boolean;
  progress?: {
    total_items: number;
    pending: number;
    queued: number;
    parsing: number;
    ner: number;
    vision: number;
    awaiting_review: number;
    review_approved: number;
    redacting: number;
    completed: number;
    failed: number;
    cancelled: number;
  };
}

/** 处理历史列表项 */
export interface FileListItem {
  file_id: string;
  original_filename: string;
  file_size: number;
  file_type: FileType;
  created_at?: string | null;
  has_output: boolean;
  entity_count: number;
  /** playground=Playground；batch=批量向导或任务工单 */
  upload_source?: 'playground' | 'batch';
  /** 绑定任务中心 Job 时存在，可与 /jobs/:id 关联 */
  job_id?: string | null;
  /** 批量向导同一会话；单文件上传为 undefined/null */
  batch_group_id?: string | null;
  /** 该批次全局文件数（跨页时仍准确） */
  batch_group_count?: number | null;
  /** 列表 embed_job=1 时由后端填充 */
  job_embed?: JobEmbedSummary | null;
}

export interface FileListResponse {
  files: FileListItem[];
  total: number;
  page: number;
  page_size: number;
}

// 解析结果
export interface ParseResult {
  file_id: string;
  file_type: FileType;
  content: string;
  page_count: number;
  pages: string[];
  is_scanned: boolean;
}

// NER识别结果
export interface NERResult {
  file_id: string;
  entities: Entity[];
  entity_count: number;
  entity_summary: Record<string, number>;
}

// 视觉识别结果
export interface VisionResult {
  file_id: string;
  page: number;
  bounding_boxes: BoundingBox[];
}

// 脱敏配置
export interface RedactionConfig {
  replacement_mode: ReplacementMode;
  entity_types: EntityType[];
  custom_replacements: Record<string, string>;
  /** 图片类块级脱敏；仅对 image / 扫描 PDF 生效 */
  image_redaction_method?: ImageRedactionMethod;
  image_redaction_strength?: number;
  image_fill_color?: string;
}

// 脱敏请求
export interface RedactionRequest {
  file_id: string;
  entities: Entity[];
  bounding_boxes: BoundingBox[];
  config: RedactionConfig;
}

// 脱敏结果
export interface RedactionResult {
  file_id: string;
  output_file_id: string;
  redacted_count: number;
  entity_map: Record<string, string>;
  download_url: string;
}

// 对比数据
export interface CompareData {
  file_id: string;
  original_content: string;
  redacted_content: string;
  changes: Array<{
    original: string;
    replacement: string;
    count: number;
  }>;
}

// 实体类型配置 - 基于 GB/T 37964-2019
export interface EntityTypeConfig {
  id: string;
  name: string;
  category: IdentifierCategory;
  description?: string;
  examples?: string[];
  color: string;
  regex_pattern?: string;
  use_llm: boolean;
  enabled: boolean;
  order: number;
  tag_template?: string;
  risk_level: number;
}

// 兼容旧版配置
export interface EntityTypeConfigSimple {
  value: EntityType;
  label: string;
  color: string;
}

// 替换模式配置
export interface ReplacementModeConfig {
  value: ReplacementMode;
  label: string;
  description: string;
}

// 应用状态
export type AppStage = 'upload' | 'preview' | 'edit' | 'compare';
