// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import type { BatchRow, ReviewPageSummary } from '../types';

export type NextReviewPageTargetKind = 'issue' | 'hit' | 'unvisited';

export interface NextReviewPageTarget {
  page: ReviewPageSummary;
  kind: NextReviewPageTargetKind;
}

export function isPendingReviewRow(row: Pick<BatchRow, 'reviewConfirmed'>): boolean {
  return row.reviewConfirmed !== true;
}

export function isActionableReviewRow(
  row: Pick<BatchRow, 'analyzeStatus' | 'reviewConfirmed'>,
): boolean {
  return (
    (row.analyzeStatus === 'awaiting_review' || row.analyzeStatus === 'completed') &&
    isPendingReviewRow(row)
  );
}

export function findFirstActionableReviewIndex(doneRows: BatchRow[]): number {
  return doneRows.findIndex(isActionableReviewRow);
}

export function findFirstPendingReviewIndex(doneRows: BatchRow[]): number {
  return doneRows.findIndex(isPendingReviewRow);
}

export function resolveReviewResumeIndex(doneRows: BatchRow[], preferredFileId?: string): number {
  if (doneRows.length === 0) return 0;

  const preferredIndex = preferredFileId
    ? doneRows.findIndex((row) => row.file_id === preferredFileId)
    : -1;
  if (preferredIndex >= 0 && isActionableReviewRow(doneRows[preferredIndex])) {
    return preferredIndex;
  }

  const firstActionableIndex = findFirstActionableReviewIndex(doneRows);
  if (firstActionableIndex >= 0) return firstActionableIndex;

  if (preferredIndex >= 0 && isPendingReviewRow(doneRows[preferredIndex])) {
    return preferredIndex;
  }

  const firstPendingIndex = findFirstPendingReviewIndex(doneRows);
  if (firstPendingIndex >= 0) return firstPendingIndex;
  return preferredIndex >= 0 ? preferredIndex : 0;
}

export function findNextPendingReviewIndex(doneRows: BatchRow[], currentFileId: string): number {
  if (doneRows.length <= 1) return -1;
  const currentIndex = doneRows.findIndex((row) => row.file_id === currentFileId);
  const startIndex = currentIndex >= 0 ? currentIndex : 0;

  for (let offset = 1; offset <= doneRows.length; offset += 1) {
    const nextIndex = (startIndex + offset) % doneRows.length;
    const row = doneRows[nextIndex];
    if (row.file_id !== currentFileId && isPendingReviewRow(row)) return nextIndex;
  }

  return -1;
}

export function getNextReviewIndex(
  doneRows: BatchRow[],
  reviewIndex: number,
  currentFileId: string,
): number | null {
  if (doneRows.length <= 1) return null;
  const pendingIndex = findNextPendingReviewIndex(doneRows, currentFileId);
  if (pendingIndex >= 0) return pendingIndex;
  if (reviewIndex < doneRows.length - 1) return reviewIndex + 1;
  return null;
}

export function getNextReviewPageTarget(
  pages: readonly ReviewPageSummary[],
  currentPage: number,
): NextReviewPageTarget | null {
  const unvisitedIssue =
    pages.find((page) => page.page > currentPage && page.issueCount > 0 && !page.visited) ??
    pages.find((page) => page.issueCount > 0 && !page.visited);
  if (unvisitedIssue) return { page: unvisitedIssue, kind: 'issue' };

  const unvisitedHit =
    pages.find((page) => page.page > currentPage && page.hitCount > 0 && !page.visited) ??
    pages.find((page) => page.hitCount > 0 && !page.visited);
  if (unvisitedHit) return { page: unvisitedHit, kind: 'hit' };

  const unvisited =
    pages.find((page) => page.page > currentPage && !page.visited) ??
    pages.find((page) => !page.visited);
  if (unvisited) return { page: unvisited, kind: 'unvisited' };

  return null;
}

export function getNextRequiredReviewPageTarget(
  pages: readonly ReviewPageSummary[],
  currentPage: number,
): NextReviewPageTarget | null {
  const unvisitedIssue =
    pages.find((page) => page.page > currentPage && page.issueCount > 0 && !page.visited) ??
    pages.find((page) => page.issueCount > 0 && !page.visited);
  if (unvisitedIssue) return { page: unvisitedIssue, kind: 'issue' };

  const unvisitedHit =
    pages.find((page) => page.page > currentPage && page.hitCount > 0 && !page.visited) ??
    pages.find((page) => page.hitCount > 0 && !page.visited);
  if (unvisitedHit) return { page: unvisitedHit, kind: 'hit' };

  return null;
}
