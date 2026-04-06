
export enum IdentifierCategory {
  DIRECT = 'direct',       
  QUASI = 'quasi',         
  SENSITIVE = 'sensitive', 
  OTHER = 'other',         
}


export enum EntityType {
  
  PERSON = 'PERSON',                   
  ID_CARD = 'ID_CARD',                 
  PASSPORT = 'PASSPORT',               
  SOCIAL_SECURITY = 'SOCIAL_SECURITY', 
  DRIVER_LICENSE = 'DRIVER_LICENSE',   
  PHONE = 'PHONE',                     
  EMAIL = 'EMAIL',                     
  BANK_CARD = 'BANK_CARD',             
  BANK_ACCOUNT = 'BANK_ACCOUNT',       
  WECHAT_ALIPAY = 'WECHAT_ALIPAY',     
  IP_ADDRESS = 'IP_ADDRESS',           
  MAC_ADDRESS = 'MAC_ADDRESS',         
  DEVICE_ID = 'DEVICE_ID',             
  BIOMETRIC = 'BIOMETRIC',             
  LEGAL_PARTY = 'LEGAL_PARTY',         
  LAWYER = 'LAWYER',                   
  JUDGE = 'JUDGE',                     
  WITNESS = 'WITNESS',                 
  
  
  BIRTH_DATE = 'BIRTH_DATE',           
  AGE = 'AGE',                         
  GENDER = 'GENDER',                   
  NATIONALITY = 'NATIONALITY',         
  ADDRESS = 'ADDRESS',                 
  POSTAL_CODE = 'POSTAL_CODE',         
  GPS_LOCATION = 'GPS_LOCATION',       
  OCCUPATION = 'OCCUPATION',           
  EDUCATION = 'EDUCATION',             
  WORK_UNIT = 'WORK_UNIT',             
  DATE = 'DATE',                       
  TIME = 'TIME',                       
  LICENSE_PLATE = 'LICENSE_PLATE',     
  VIN = 'VIN',                         
  CASE_NUMBER = 'CASE_NUMBER',         
  CONTRACT_NO = 'CONTRACT_NO',         
  ORG = 'ORG',                         
  COMPANY_CODE = 'COMPANY_CODE',       
  
  
  HEALTH_INFO = 'HEALTH_INFO',         
  MEDICAL_RECORD = 'MEDICAL_RECORD',   
  AMOUNT = 'AMOUNT',                   
  PROPERTY = 'PROPERTY',               
  CRIMINAL_RECORD = 'CRIMINAL_RECORD', 
  POLITICAL = 'POLITICAL',             
  RELIGION = 'RELIGION',               
  
  
  CUSTOM = 'CUSTOM',                   
}


export enum FileType {
  DOC = 'doc',
  DOCX = 'docx',
  TXT = 'txt',
  PDF = 'pdf',
  PDF_SCANNED = 'pdf_scanned',
  IMAGE = 'image',
}


export enum ReplacementMode {
  SMART = 'smart',
  MASK = 'mask',
  CUSTOM = 'custom',
  STRUCTURED = 'structured',
}


export type ImageRedactionMethod = 'mosaic' | 'blur' | 'fill';


export interface Entity {
  id: string;
  text: string;
  type: string;
  start: number;
  end: number;
  page: number;
  confidence: number;
  replacement?: string;
  selected: boolean;
}


export interface BoundingBox {
  id: string;
  x: number;
  y: number;
  width: number;
  height: number;
  page: number;
  type: string;
  text?: string;
  selected: boolean;
  source?: 'ocr_has' | 'has_image' | 'manual';
}


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


export interface JobItemMini {
  id: string;
  status: string;
}

export interface JobEmbedSummary {
  status: string;
  job_type: 'text_batch' | 'image_batch';
  items: JobItemMini[];
  
  first_awaiting_review_item_id?: string | null;
  
  wizard_furthest_step?: number | null;
  
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


export interface FileListItem {
  file_id: string;
  original_filename: string;
  file_size: number;
  file_type: FileType;
  created_at?: string | null;
  has_output: boolean;
  entity_count: number;
  
  upload_source?: 'playground' | 'batch';
  
  job_id?: string | null;
  
  batch_group_id?: string | null;
  
  batch_group_count?: number | null;
  
  item_status?: string | null;
  
  item_id?: string | null;
  
  job_embed?: JobEmbedSummary | null;
}

export interface FileListResponse {
  files: FileListItem[];
  total: number;
  page: number;
  page_size: number;
}


export interface ParseResult {
  file_id: string;
  file_type: FileType;
  content: string;
  page_count: number;
  pages: string[];
  is_scanned: boolean;
}


export interface NERResult {
  file_id: string;
  entities: Entity[];
  entity_count: number;
  entity_summary: Record<string, number>;
  warnings?: string[];
}


export interface VisionResult {
  file_id: string;
  page: number;
  bounding_boxes: BoundingBox[];
  result_image?: string;
}


export interface RedactionConfig {
  replacement_mode: ReplacementMode;
  entity_types: EntityType[];
  custom_replacements: Record<string, string>;
  custom_entity_types?: string[];

  image_redaction_method?: ImageRedactionMethod;
  image_redaction_strength?: number;
  image_fill_color?: string;
}


export interface RedactionRequest {
  file_id: string;
  entities: Entity[];
  bounding_boxes: BoundingBox[];
  config: RedactionConfig;
}


export interface RedactionResult {
  file_id: string;
  output_file_id: string;
  redacted_count: number;
  entity_map: Record<string, string>;
  download_url: string;
}


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


export interface EntityTypeConfigSimple {
  value: EntityType;
  label: string;
  color: string;
}


export interface ReplacementModeConfig {
  value: ReplacementMode;
  label: string;
  description: string;
}


export interface VersionHistoryEntry {
  output_file_id: string;
  output_path?: string;
  redacted_count: number;
  entity_map: Record<string, string>;
  mode: string;
  created_at: string;
}


export type AppStage = 'upload' | 'preview' | 'edit' | 'compare';
