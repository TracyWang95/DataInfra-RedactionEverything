// Copyright 2026 DataInfra-RedactionEverything Contributors

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

// Single frontend copy of the low-confidence review threshold. Must stay in
// sync with backend job_visual_evidence.py (LOW_CONFIDENCE = 0.55) — the
// backend flags the same threshold when building visual evidence.
export const LOW_CONFIDENCE_THRESHOLD = 0.55;
const LARGE_OCR_AREA_THRESHOLD = 0.2;
const LARGE_OCR_WIDTH_THRESHOLD = 0.6;
const LARGE_OCR_HEIGHT_THRESHOLD = 0.25;
const EDGE_MARGIN = 0.04;
const EDGE_FAR_MARGIN = 0.96;
const SEAM_MARGIN = 0.025;
const SEAM_FAR_MARGIN = 0.975;
const SEAM_MAX_WIDTH = 0.07;
const SEAM_MIN_HEIGHT = 0.1;

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
    sourceValues.has('visual_feature_model') ||
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
  return (
    box.width * box.height >= LARGE_OCR_AREA_THRESHOLD ||
    (box.width >= LARGE_OCR_WIDTH_THRESHOLD && box.height >= LARGE_OCR_HEIGHT_THRESHOLD)
  );
}

function isSealBox(box: EditorBox): boolean {
  return ['seal', 'official_seal', 'stamp'].includes(String(box.type || '').toLowerCase());
}

function isEdgeBox(box: EditorBox): boolean {
  return (
    box.x <= EDGE_MARGIN ||
    box.y <= EDGE_MARGIN ||
    box.x + box.width >= EDGE_FAR_MARGIN ||
    box.y + box.height >= EDGE_FAR_MARGIN
  );
}

function isSideSeamBox(box: EditorBox): boolean {
  return (
    box.x <= SEAM_MARGIN ||
    box.x + box.width >= SEAM_FAR_MARGIN ||
    (box.width <= SEAM_MAX_WIDTH && box.height >= SEAM_MIN_HEIGHT)
  );
}

export function getReviewBoxQualityIssueKeys(box: EditorBox): ReviewBoxQualityIssue[] {
  const issues: ReviewBoxQualityIssue[] = [];
  const { evidenceSource, source, sourceDetail, warnings } = sourceEvidence(box);

  if (typeof box.confidence === 'number' && box.confidence > 0 && box.confidence < LOW_CONFIDENCE_THRESHOLD) {
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
