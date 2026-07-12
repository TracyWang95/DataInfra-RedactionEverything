// Copyright 2026 DataInfra-RedactionEverything Contributors

import type { BoundingBox as EditorBox } from '@/components/ImageBBoxEditor';
import type { ReviewVisionPageQuality } from '../types';

export function normalizePage(page: unknown, fallback = 1): number {
  const n = Number(page);
  return Number.isFinite(n) && n > 0 ? Math.trunc(n) : fallback;
}

export function normalizeVisionQualityByPage(
  raw: unknown,
): Record<number, ReviewVisionPageQuality> {
  if (!raw || typeof raw !== 'object') return {};
  const normalized: Record<number, ReviewVisionPageQuality> = {};
  for (const [key, value] of Object.entries(raw as Record<string, unknown>)) {
    if (!value || typeof value !== 'object') continue;
    const page = normalizePage(key, 0);
    if (page <= 0) continue;
    const record = value as Record<string, unknown>;
    const warnings = Array.isArray(record.warnings)
      ? record.warnings.filter((warning): warning is string => typeof warning === 'string')
      : [];
    const pipelineStatus =
      record.pipeline_status && typeof record.pipeline_status === 'object'
        ? (record.pipeline_status as Record<string, Record<string, unknown>>)
        : {};
    normalized[page] = {
      warnings,
      pipeline_status: Object.fromEntries(
        Object.entries(pipelineStatus).map(([name, status]) => [
          name,
          {
            ran: Boolean(status.ran),
            skipped: Boolean(status.skipped),
            failed: Boolean(status.failed),
            region_count: typeof status.region_count === 'number' ? status.region_count : undefined,
            error: typeof status.error === 'string' ? status.error : null,
          },
        ]),
      ),
    };
  }
  return normalized;
}

export function normalizeReviewBox(
  raw: Record<string, unknown>,
  index: number,
  pageFallback = 1,
): EditorBox {
  return {
    id: String(raw.id ?? `bbox_${index}`),
    x: Number(raw.x),
    y: Number(raw.y),
    width: Number(raw.width),
    height: Number(raw.height),
    page: normalizePage(raw.page, pageFallback),
    type: String(raw.type ?? 'CUSTOM'),
    text: raw.text ? String(raw.text) : undefined,
    selected: raw.selected !== false,
    confidence: typeof raw.confidence === 'number' ? raw.confidence : undefined,
    source: (raw.source as EditorBox['source']) || undefined,
    evidence_source:
      typeof raw.evidence_source === 'string'
        ? (raw.evidence_source as EditorBox['evidence_source'])
        : undefined,
    source_detail: raw.source_detail ? String(raw.source_detail) : undefined,
    warnings: Array.isArray(raw.warnings)
      ? raw.warnings.filter((warning): warning is string => typeof warning === 'string')
      : undefined,
  };
}

export function boxesToDraftPayload(boxes: EditorBox[]): Array<Record<string, unknown>> {
  return boxes.map((box) => ({
    id: box.id,
    x: box.x,
    y: box.y,
    width: box.width,
    height: box.height,
    page: normalizePage(box.page, 1),
    type: box.type,
    text: box.text,
    selected: box.selected,
    source: box.source,
    confidence: box.confidence,
    evidence_source: box.evidence_source,
    source_detail: box.source_detail,
    warnings: box.warnings,
  }));
}

export function normalizeEntityMap(raw: unknown): Record<string, string> {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return {};
  const entries = Object.entries(raw as Record<string, unknown>)
    .filter(([key, value]) => key && typeof value === 'string' && value)
    .map(([key, value]) => [key, value as string]);
  return Object.fromEntries(entries);
}
