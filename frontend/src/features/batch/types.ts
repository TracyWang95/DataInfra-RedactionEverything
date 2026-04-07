// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

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
  mode: 'ocr_has' | 'has_image';
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
  reviewConfirmed?: boolean;
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
