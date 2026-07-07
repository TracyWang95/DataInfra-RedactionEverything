// Copyright 2026 DataInfra-RedactionEverything Contributors

import { describe, expect, it } from 'vitest';

import type { BatchRow } from '../types';
import {
  findNextPendingReviewIndex,
  getNextReviewIndex,
  isActionableReviewRow,
  resolveReviewResumeIndex,
} from './review-navigation';

function row(overrides: Partial<BatchRow>): BatchRow {
  return {
    file_id: 'f',
    original_filename: 'f.docx',
    file_size: 1,
    file_type: 'docx',
    has_output: false,
    reviewConfirmed: false,
    entity_count: 0,
    analyzeStatus: 'awaiting_review',
    isImageMode: false,
    ...overrides,
  } as BatchRow;
}

describe('isActionableReviewRow', () => {
  it('only awaiting_review/completed rows that are unconfirmed are actionable', () => {
    expect(isActionableReviewRow(row({}))).toBe(true);
    expect(isActionableReviewRow(row({ analyzeStatus: 'completed' }))).toBe(true);
    expect(isActionableReviewRow(row({ reviewConfirmed: true }))).toBe(false);
    expect(isActionableReviewRow(row({ analyzeStatus: 'redacting' }))).toBe(false);
  });
});

describe('findNextPendingReviewIndex', () => {
  const rows = [
    row({ file_id: 'a', reviewConfirmed: true }),
    row({ file_id: 'b' }),
    row({ file_id: 'c', reviewConfirmed: true }),
    row({ file_id: 'd' }),
  ];

  it('wraps around and skips confirmed rows', () => {
    expect(findNextPendingReviewIndex(rows, 'b')).toBe(3); // b -> d
    expect(findNextPendingReviewIndex(rows, 'd')).toBe(1); // wrap d -> b
  });

  it('returns -1 when nothing is pending or list too small', () => {
    expect(findNextPendingReviewIndex([rows[0]], 'a')).toBe(-1);
    expect(
      findNextPendingReviewIndex(
        rows.map((r) => ({ ...r, reviewConfirmed: true })),
        'a',
      ),
    ).toBe(-1);
  });
});

describe('getNextReviewIndex', () => {
  it('prefers the next pending row, else next sequential, else null', () => {
    const mixed = [row({ file_id: 'a' }), row({ file_id: 'b', reviewConfirmed: true })];
    // wraps back to the still-pending row a
    expect(getNextReviewIndex(mixed, 1, 'b')).toBe(0);

    const allConfirmed = [
      row({ file_id: 'a', reviewConfirmed: true }),
      row({ file_id: 'b', reviewConfirmed: true }),
    ];
    // nothing pending -> sequential advance, then null at the end
    expect(getNextReviewIndex(allConfirmed, 0, 'a')).toBe(1);
    expect(getNextReviewIndex(allConfirmed, 1, 'b')).toBe(null);
    expect(getNextReviewIndex([row({})], 0, 'f')).toBe(null);
  });
});

describe('resolveReviewResumeIndex', () => {
  it('prefers the requested file when it is actionable', () => {
    const rows = [row({ file_id: 'a' }), row({ file_id: 'b' })];
    expect(resolveReviewResumeIndex(rows, 'b')).toBe(1);
  });

  it('falls back to first actionable, then first pending, then 0', () => {
    const rows = [
      row({ file_id: 'a', reviewConfirmed: true }),
      row({ file_id: 'b', analyzeStatus: 'redacting' }), // pending but not actionable
      row({ file_id: 'c' }),
    ];
    expect(resolveReviewResumeIndex(rows, 'a')).toBe(2);
    expect(resolveReviewResumeIndex([], 'a')).toBe(0);
  });
});
