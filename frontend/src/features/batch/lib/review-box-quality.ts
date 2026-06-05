// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import type { BoundingBox as EditorBox } from '@/components/ImageBBoxEditor';

export type ReviewBoxQualityIssue =
  | 'lowConfidence'
  | 'fallback'
  | 'tableStructure'
  | 'coarseMarkup'
  | 'largeRegion'
  | 'edgeSeal'
  | 'seamSeal'
  | 'warning';

export type ReviewBoxSourceKind = 'visualFeature' | 'fallback' | 'ocrHas' | 'table';

export const REVIEW_BOX_QUALITY_ISSUE_ORDER: readonly ReviewBoxQualityIssue[] = [
  'fallback',
  'tableStructure',
  'edgeSeal',
  'seamSeal',
  'lowConfidence',
  'coarseMarkup',
  'largeRegion',
  'warning',
];

export function formatSourceDetail(value: string | undefined): string {
  const normalized = (value ?? '').replace(/[_-]+/g, ' ').trim();
  if (!normalized) return '';
  return normalized.replace(/\b\w/g, (char) => char.toUpperCase());
}

function lowercaseValue(value: unknown): string {
  return typeof value === 'string' ? value.toLowerCase() : '';
}

function sourceEvidence(box: EditorBox): {
  evidenceSource: string;
  source: string;
  sourceDetail: string;
  warnings: string;
} {
  return {
    evidenceSource: lowercaseValue((box as EditorBox & { evidence_source?: unknown }).evidence_source),
    source: lowercaseValue(box.source),
    sourceDetail: lowercaseValue(box.source_detail),
    warnings: (box.warnings ?? []).join(' ').toLowerCase(),
  };
}

export function getReviewBoxSourceKind(box: EditorBox): ReviewBoxSourceKind | null {
  const { evidenceSource, source, sourceDetail, warnings } = sourceEvidence(box);
  const sourceValues = new Set([evidenceSource, source].filter(Boolean));

  if (
    sourceValues.has('fallback_detector') ||
    sourceValues.has('local_fallback') ||
    sourceDetail.includes('fallback') ||
    warnings.includes('fallback_detector')
  ) {
    return 'fallback';
  }
  if (
    sourceValues.has('table_structure') ||
    sourceValues.has('table') ||
    sourceDetail.includes('table_structure') ||
    warnings.includes('table_structure')
  ) {
    return 'table';
  }
  if (
    sourceValues.has('ocr_has') ||
    sourceDetail === 'ocr_has' ||
    sourceDetail.startsWith('ocr_has_')
  ) {
    return 'ocrHas';
  }
  if (
    sourceValues.has('visual_features') ||
    sourceValues.has('visual_features_model') ||
    sourceDetail === 'visual_features' ||
    sourceDetail.startsWith('visual_features_')
  ) {
    return 'visualFeature';
  }

  return null;
}

function hasCoarseMarkup(text: string | undefined): boolean {
  const normalized = (text ?? '').trim().toLowerCase();
  return (
    normalized.startsWith('<table') ||
    normalized.startsWith('<html') ||
    normalized.startsWith('<div')
  );
}

function isLargeOcrBox(box: EditorBox): boolean {
  if (box.source !== 'ocr_has') return false;
  return box.width * box.height >= 0.2 || (box.width >= 0.6 && box.height >= 0.25);
}

function isSealBox(box: EditorBox): boolean {
  return ['seal', 'official_seal', 'stamp'].includes(String(box.type || '').toLowerCase());
}

function isEdgeBox(box: EditorBox): boolean {
  return box.x <= 0.04 || box.y <= 0.04 || box.x + box.width >= 0.96 || box.y + box.height >= 0.96;
}

function isSideSeamBox(box: EditorBox): boolean {
  return box.x <= 0.025 || box.x + box.width >= 0.975 || (box.width <= 0.07 && box.height >= 0.10);
}

export function getReviewBoxQualityIssueKeys(box: EditorBox): ReviewBoxQualityIssue[] {
  const issues: ReviewBoxQualityIssue[] = [];
  const { evidenceSource, source, sourceDetail, warnings } = sourceEvidence(box);

  if (typeof box.confidence === 'number' && box.confidence > 0 && box.confidence < 0.55) {
    issues.push('lowConfidence');
  }
  if (
    source === 'fallback_detector' ||
    evidenceSource === 'local_fallback' ||
    sourceDetail.includes('fallback') ||
    warnings.includes('fallback_detector')
  ) {
    issues.push('fallback');
  }
  if (sourceDetail.includes('table_structure') || warnings.includes('table_structure')) {
    issues.push('tableStructure');
  }
  if (hasCoarseMarkup(box.text)) issues.push('coarseMarkup');
  if (isLargeOcrBox(box)) issues.push('largeRegion');
  if (isSealBox(box) && isEdgeBox(box)) issues.push('edgeSeal');
  if (isSealBox(box) && isSideSeamBox(box)) issues.push('seamSeal');
  if (box.warnings?.length) issues.push('warning');

  const issueSet = new Set(issues);
  return REVIEW_BOX_QUALITY_ISSUE_ORDER.filter((issue) => issueSet.has(issue));
}

export function hasReviewBoxIssue(box: EditorBox): boolean {
  if (box.selected === false) return false;
  return getReviewBoxQualityIssueKeys(box).length > 0;
}
