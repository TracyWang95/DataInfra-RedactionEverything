// Copyright 2026 DataInfra-RedactionEverything Contributors

import { getEntityTypeName } from '@/config/entityTypes';

export type TextSegment =
  | { text: string; isMatch: false }
  | {
      text: string;
      isMatch: true;
      origKey: string;
      safeKey: string;
      matchIdx: number;
    };

export interface EntityCoverageSource {
  text: string;
  type: string;
  selected?: boolean;
}

export function buildEntityCoverageMap<T extends EntityCoverageSource>(
  entities: T[],
): Map<string, T> {
  const byText = new Map<string, T>();
  for (const entity of entities) {
    if (!entity.text) continue;
    const existing = byText.get(entity.text);
    if (!existing || (existing.selected === false && entity.selected !== false)) {
      byText.set(entity.text, entity);
    }
  }
  return byText;
}

export function countTextMapOccurrences(text: string, map: Record<string, string>): number {
  return buildTextSegments(text, map).reduce((sum, segment) => sum + (segment.isMatch ? 1 : 0), 0);
}


/**
 * Display-only fallback used when POST /redaction/preview-map is unavailable.
 * Intentionally NOT a copy of the backend replacement rules — the backend
 * replacement_strategy is the single source of truth. Every selected entity
 * text maps to a generic "[<type name><n>]" placeholder so the preview still
 * marks all hits without pretending to know the real replacement.
 */
export function buildFallbackPreviewEntityMap(
  entities: Array<{ text: string; type: string; selected?: boolean }>,
): Record<string, string> {
  const map: Record<string, string> = {};
  const typeCounters: Record<string, number> = {};
  for (const e of entities) {
    if (e.selected === false || !e.text) continue;
    const label = getEntityTypeName(e.type || 'CUSTOM');
    typeCounters[label] = (typeCounters[label] || 0) + 1;
    map[e.text] = `[${label}${typeCounters[label]}]`;
  }
  return map;
}

export function buildTextSegments(text: string, map: Record<string, string>): TextSegment[] {
  if (!text || Object.keys(map).length === 0) return [{ text, isMatch: false }];
  const sortedKeys = Object.keys(map).sort((a, b) => b.length - a.length);
  const regex = new RegExp(
    `(${sortedKeys.map((k) => k.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')})`,
    'g',
  );
  const parts = text.split(regex);
  const counters: Record<string, number> = {};
  return parts.map((part) => {
    if (map[part] !== undefined) {
      const safeKey = part.replace(/[^a-zA-Z0-9\u4e00-\u9fff]/g, '_');
      const idx = counters[safeKey] || 0;
      counters[safeKey] = idx + 1;
      return { text: part, isMatch: true as const, origKey: part, safeKey, matchIdx: idx };
    }
    return { text: part, isMatch: false as const };
  });
}
