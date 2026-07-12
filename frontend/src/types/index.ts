// Copyright 2026 DataInfra-RedactionEverything Contributors

// ---------------------------------------------------------------------------
// Shared / canonical type definitions used across features (history, batch
// API layer, redaction pipeline, etc.).
//
// NOTE: The playground and batch features maintain lighter, context-specific
// projections of some types here (FileInfo, EntityTypeConfig). See:
//   - features/playground/types.ts  — UI-oriented playground slices
//   - features/batch/types.ts       — batch wizard runtime types
//
// Do NOT blindly merge them: the field differences are intentional.
// ---------------------------------------------------------------------------

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
  STRUCTURED = 'structured',
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
  job_type: 'text_batch' | 'image_batch' | 'smart_batch' | 'structured_batch';
  items: JobItemMini[];

  first_awaiting_review_item_id?: string | null;

  wizard_furthest_step?: number | null;

  batch_step1_configured?: boolean;
  progress?: {
    total_items: number;
    pending: number;
    processing: number;
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

export interface JobExportReportJob {
  id: string;
  job_type: string;
  status: string;
  skip_item_review: boolean;
  config: Record<string, unknown>;
}

export interface BatchExportReportVisualReview {
  blocking: boolean;
  review_hint: boolean;
  issue_count: number;
  issue_pages: string[];
  issue_pages_count: number;
  issue_labels: string[];
  by_issue: Record<string, number>;
}

export interface BatchExportReportVisualEvidence {
  total_boxes?: number;
  selected_boxes?: number;
  visual_feature_model?: number;
  local_fallback?: number;
  ocr_has?: number;
  table_structure?: number;
  fallback_detector?: number;
  source_counts?: Record<string, number>;
  evidence_source_counts?: Record<string, number>;
  source_detail_counts?: Record<string, number>;
  warnings_by_key?: Record<string, number>;
}

export type BatchExportReportFileDeliveryStatus =
  | 'ready_for_delivery'
  | 'action_required'
  | 'not_selected';

export interface BatchExportReportFile {
  item_id: string;
  file_id: string;
  filename: string;
  file_type: string;
  file_size: number;
  status: string;
  has_output: boolean;
  review_confirmed: boolean;
  entity_count: number;
  page_count: number | null;
  selected_for_export: boolean;
  delivery_status: BatchExportReportFileDeliveryStatus;
  error: string | null;
  ready_for_delivery: boolean;
  action_required: boolean;
  blocking: boolean;
  blocking_reasons: string[];
  redacted_export_skip_reason: string | null;
  visual_review_hint: boolean;
  visual_evidence?: BatchExportReportVisualEvidence;
  visual_review: BatchExportReportVisualReview;
}

export type BatchExportReportSummaryDeliveryStatus =
  | 'ready_for_delivery'
  | 'action_required'
  | 'no_selection';

export interface BatchExportReportSummary {
  total_files: number;
  selected_files: number;
  redacted_selected_files: number;
  unredacted_selected_files: number;
  review_confirmed_selected_files: number;
  failed_selected_files: number;
  detected_entities: number;
  redaction_coverage: number;
  delivery_status: BatchExportReportSummaryDeliveryStatus;
  action_required_files: number;
  action_required: boolean;
  blocking_files: number;
  blocking: boolean;
  ready_for_delivery: boolean;
  by_status: Record<string, number>;
  zip_redacted_included_files: number;
  zip_redacted_skipped_files: number;
  visual_review_hint: boolean;
  visual_review_issue_files: number;
  visual_review_issue_count: number;
  visual_review_issue_pages_count: number;
  visual_review_issue_labels: string[];
  visual_review_by_issue: Record<string, number>;
  visual_evidence?: BatchExportReportVisualEvidence;
}

export interface JobExportReportZipSkipped {
  file_id: string;
  reason: string;
}

export interface JobExportReportRedactedZip {
  included_count: number;
  skipped_count: number;
  skipped: JobExportReportZipSkipped[];
}

export interface BatchExportReport {
  generated_at: string;
  job: JobExportReportJob | null;
  summary: BatchExportReportSummary;
  redacted_zip: JobExportReportRedactedZip;
  files: BatchExportReportFile[];
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
    stats?: {
      total_files?: number;
      redacted_files?: number;
      awaiting_review_files?: number;
      unredacted_files?: number;
      entity_sum?: number;
      size_bytes?: number;
    };
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
  data_domain: string;
  generic_target?: string | null;
  entity_type_ids?: string[];
  linkage_groups: string[];
  coref_enabled: boolean;
  default_enabled?: boolean;
  description?: string;
  examples?: string[];
  color: string;
  regex_pattern?: string;
  use_llm: boolean;
  enabled: boolean;
  order: number;
  tag_template?: string;
}

export interface VersionHistoryEntry {
  output_file_id: string;
  output_path?: string;
  redacted_count: number;
  entity_map: Record<string, string>;
  mode: string;
  created_at: string;
}
