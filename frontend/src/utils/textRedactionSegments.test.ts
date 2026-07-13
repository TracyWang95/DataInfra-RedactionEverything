// Copyright 2026 DataInfra-RedactionEverything Contributors

import { describe, expect, it } from 'vitest';

import { buildFallbackPreviewEntityMap, buildTextSegments } from './textRedactionSegments';

describe('buildFallbackPreviewEntityMap', () => {
  it('maps every selected entity text to a generic numbered placeholder', () => {
    const map = buildFallbackPreviewEntityMap([
      { text: '张三', type: 'PERSON' },
      { text: '李四', type: 'PERSON' },
      { text: '13800138000', type: 'PHONE' },
    ]);
    expect(Object.keys(map).sort()).toEqual(['13800138000', '张三', '李四'].sort());
    for (const value of Object.values(map)) {
      expect(value).toMatch(/^\[.+\d+\]$/);
    }
    expect(map['张三']).not.toBe(map['李四']);
  });

  it('skips deselected and empty-text entities but keeps every selected one', () => {
    const map = buildFallbackPreviewEntityMap([
      { text: '张三', type: 'PERSON', selected: false },
      { text: '', type: 'PHONE' },
      { text: '李四', type: 'PERSON', selected: true },
    ]);
    expect(map['张三']).toBeUndefined();
    expect(map['李四']).toBeDefined();
  });

  it('produces a map consumable by buildTextSegments covering all hits', () => {
    const map = buildFallbackPreviewEntityMap([{ text: '张三', type: 'PERSON' }]);
    const segments = buildTextSegments('原告张三与被告', map);
    expect(segments.some((segment) => segment.isMatch && segment.text === '张三')).toBe(true);
  });
});
