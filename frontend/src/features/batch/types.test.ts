// Copyright 2026 DataInfra-RedactionEverything Contributors

import { describe, expect, it } from 'vitest';

import {
  RECOGNITION_DONE_STATUSES,
  hasReviewableRecognitionRows,
  isBatchReadyForExportReview,
} from './types';

describe('RECOGNITION_DONE_STATUSES', () => {
  it('covers the full post-recognition lifecycle', () => {
    for (const status of ['awaiting_review', 'review_approved', 'redacting', 'completed']) {
      expect(RECOGNITION_DONE_STATUSES.has(status as never)).toBe(true);
    }
    expect(RECOGNITION_DONE_STATUSES.has('pending' as never)).toBe(false);
  });
});

describe('isBatchReadyForExportReview', () => {
  it('requires every row completed-and-confirmed or failed', () => {
    expect(
      isBatchReadyForExportReview([
        { analyzeStatus: 'completed', reviewConfirmed: true },
        { analyzeStatus: 'failed', reviewConfirmed: false },
      ]),
    ).toBe(true);
    // a redacting row (bulk confirm still settling) blocks export
    expect(
      isBatchReadyForExportReview([
        { analyzeStatus: 'completed', reviewConfirmed: true },
        { analyzeStatus: 'redacting', reviewConfirmed: true },
      ]),
    ).toBe(false);
    // completed but unconfirmed blocks export
    expect(
      isBatchReadyForExportReview([{ analyzeStatus: 'completed', reviewConfirmed: false }]),
    ).toBe(false);
  });

  it('an empty batch is never export-ready', () => {
    expect(isBatchReadyForExportReview([])).toBe(false);
  });
});

describe('hasReviewableRecognitionRows', () => {
  it('true as soon as one row finished recognition', () => {
    expect(
      hasReviewableRecognitionRows([
        { analyzeStatus: 'pending' },
        { analyzeStatus: 'awaiting_review' },
      ]),
    ).toBe(true);
    expect(hasReviewableRecognitionRows([{ analyzeStatus: 'analyzing' }])).toBe(false);
  });
});
