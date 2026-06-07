// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import type { BoundingBox as EditorBox } from '@/components/ImageBBoxEditor';
import { hasReviewBoxIssue } from './review-box-quality';
import type { ReviewEntity, ReviewPageSummary } from '../types';

function hasLowConfidence(confidence: number | undefined): boolean {
  return typeof confidence === 'number' && confidence > 0 && confidence < 0.55;
}

function hasReviewEntityIssue(entity: ReviewEntity): boolean {
  if (entity.selected === false) return false;
  return hasLowConfidence(entity.confidence);
}

export function buildReviewPageSummaries({
  totalPages,
  currentPage,
  visitedPages,
  isImageMode,
  entities,
  boxes,
}: {
  totalPages: number;
  currentPage: number;
  visitedPages: ReadonlySet<number>;
  isImageMode: boolean;
  entities: readonly ReviewEntity[];
  boxes: readonly EditorBox[];
}): ReviewPageSummary[] {
  const pageCount = Math.max(1, totalPages);
  return Array.from({ length: pageCount }, (_, index) => {
    const page = index + 1;
    const pageBoxes = boxes.filter((box) => Number(box.page || 1) === page);
    const pageEntities = entities.filter((entity) => Number(entity.page || 1) === page);
    const hitCount = isImageMode ? pageBoxes.length : pageEntities.length;
    const selectedCount = isImageMode
      ? pageBoxes.filter((box) => box.selected !== false).length
      : pageEntities.filter((entity) => entity.selected !== false).length;
    const issueCount = isImageMode
      ? pageBoxes.filter(hasReviewBoxIssue).length
      : pageEntities.filter(hasReviewEntityIssue).length;
    return {
      page,
      hitCount,
      selectedCount,
      issueCount,
      visited: visitedPages.has(page),
      current: page === currentPage,
    };
  });
}
