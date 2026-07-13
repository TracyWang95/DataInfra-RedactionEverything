// Copyright 2026 DataInfra-RedactionEverything Contributors

// ---------------------------------------------------------------------------
// Batch-local type definitions.
//
// These are specific to the batch processing wizard and intentionally separate
// from the shared types in `@/types/index.ts`:
//
//  - PipelineCfg: similar to playground's PipelineConfig but with inline
//    `types` containing an `enabled` flag for per-batch toggling.
//  - TextEntityType: lighter than the shared EntityTypeConfig — only the
//    fields the batch config step UI needs.
//  - BatchRow: extends the shared FileListItem with batch-specific runtime
//    state (analyzeStatus, reviewConfirmed, etc.).
//  - ReviewEntity: superset of Entity used during the review step, adding
//    optional fields like `confidence`, `source`, `coref_id`, `replacement`.
// ---------------------------------------------------------------------------

import type { FileListItem } from '@/types';

export type Step = 1 | 2 | 3 | 4 | 5;

export interface PipelineCfg {
  mode: 'ocr_has' | 'visual_features';
  name: string;
  description: string;
  enabled: boolean;
  types: { id: string; name: string; color: string; enabled: boolean; order?: number }[];
}

export interface TextEntityType {
  id: string;
  name: string;
  color: string;
  regex_pattern?: string | null;
  use_llm?: boolean;
  order?: number;
}

export interface BatchRow extends FileListItem {
  analyzeStatus:
    | 'pending'
    | 'parsing'
    | 'analyzing'
    | 'awaiting_review'
    | 'review_approved'
    | 'redacting'
    | 'completed'
    | 'failed';
  analyzeError?: string;
  isImageMode?: boolean;
  hasReviewDraft?: boolean;
  reviewConfirmed?: boolean;
  page_count?: number;
  recognitionStage?: string | null;
  recognitionCurrent?: number;
  recognitionTotal?: number;
  recognitionMessage?: string | null;
}

export interface BatchUploadIssue {
  id: string;
  filename: string;
  reason: string;
}

export interface BatchUploadProgress {
  total: number;
  completed: number;
  failed: number;
  inFlight: number;
  currentFile?: string;
}

export interface ReviewPageSummary {
  page: number;
  hitCount: number;
  selectedCount: number;
  issueCount: number;
  visited: boolean;
  current: boolean;
}

export interface ReviewVisionPipelineStatus {
  ran?: boolean;
  skipped?: boolean;
  failed?: boolean;
  region_count?: number;
  error?: string | null;
}

export interface ReviewVisionPageQuality {
  warnings: string[];
  pipeline_status: Record<string, ReviewVisionPipelineStatus>;
}

export type ReviewEntity = {
  id: string;
  text: string;
  type: string;
  start: number;
  end: number;
  selected: boolean;
  page?: number;
  confidence?: number;
  source?: string;
  coref_id?: string | null;
  replacement?: string;
};

export const RECOGNITION_DONE_STATUSES: ReadonlySet<BatchRow['analyzeStatus']> = new Set([
  'awaiting_review',
  'review_approved',
  'redacting',
  'completed',
]);

export const RECOGNITION_ACTIVE_STATUSES: ReadonlySet<BatchRow['analyzeStatus']> = new Set([
  'pending',
  'parsing',
  'analyzing',
]);

export function hasReviewableRecognitionRows(
  rows: readonly Pick<BatchRow, 'analyzeStatus'>[],
): boolean {
  return rows.some((row) => RECOGNITION_DONE_STATUSES.has(row.analyzeStatus));
}

export function isBatchReadyForExportReview(
  rows: readonly Pick<BatchRow, 'analyzeStatus' | 'reviewConfirmed'>[],
): boolean {
  return (
    rows.length > 0 &&
    rows.every(
      (row) =>
        row.analyzeStatus === 'failed' ||
        (row.analyzeStatus === 'completed' && row.reviewConfirmed === true),
    )
  );
}

export function isRecognitionSettledForReview(
  rows: readonly Pick<BatchRow, 'analyzeStatus'>[],
): boolean {
  return (
    rows.length > 0 &&
    hasReviewableRecognitionRows(rows) &&
    rows.every(
      (row) => RECOGNITION_DONE_STATUSES.has(row.analyzeStatus) || row.analyzeStatus === 'failed',
    )
  );
}
