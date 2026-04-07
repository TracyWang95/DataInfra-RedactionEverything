// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect } from 'vitest';
import {
  buildTextSegments,
  buildFallbackPreviewEntityMap,
  mergePreviewMapWithDocumentSlices,
} from '../textRedactionSegments';

describe('buildTextSegments', () => {
  it('returns single non-match segment for empty map', () => {
    const result = buildTextSegments('hello world', {});
    expect(result).toEqual([{ text: 'hello world', isMatch: false }]);
  });

  it('returns single non-match segment for empty text', () => {
    const result = buildTextSegments('', { foo: 'bar' });
    expect(result).toEqual([{ text: '', isMatch: false }]);
  });

  it('splits text at matched keys', () => {
    const segments = buildTextSegments('Hello Alice and Bob', {
      Alice: '[PERSON1]',
      Bob: '[PERSON2]',
    });
    const texts = segments.map((s) => s.text);
    expect(texts).toEqual(['Hello ', 'Alice', ' and ', 'Bob', '']);
    expect(segments[1]).toMatchObject({ isMatch: true, origKey: 'Alice' });
    expect(segments[3]).toMatchObject({ isMatch: true, origKey: 'Bob' });
  });

  it('handles Chinese characters in keys and text', () => {
    const segments = buildTextSegments('被告张三与原告李四', {
      张三: '[当事人一]',
      李四: '[当事人二]',
    });
    expect(segments.filter((s) => s.isMatch)).toHaveLength(2);
    expect(segments.find((s) => s.isMatch && s.text === '张三')).toBeTruthy();
  });

  it('prefers longer match when keys overlap', () => {
    const segments = buildTextSegments('ABC Company Limited', {
      'ABC Company Limited': '[ORG]',
      ABC: '[SHORT]',
    });
    const matches = segments.filter((s) => s.isMatch);
    expect(matches).toHaveLength(1);
    expect(matches[0].text).toBe('ABC Company Limited');
  });

  it('increments matchIdx for repeated keys', () => {
    const segments = buildTextSegments('AA BB AA', { AA: 'X' });
    const matches = segments.filter((s) => s.isMatch);
    expect(matches).toHaveLength(2);
    expect(matches[0].matchIdx).toBe(0);
    expect(matches[1].matchIdx).toBe(1);
  });

  it('escapes regex special characters in keys', () => {
    const segments = buildTextSegments('cost is $100.00 total', {
      '$100.00': '[AMOUNT]',
    });
    const matches = segments.filter((s) => s.isMatch);
    expect(matches).toHaveLength(1);
    expect(matches[0].text).toBe('$100.00');
  });
});

describe('buildFallbackPreviewEntityMap', () => {
  const entities = [
    { text: '张三', type: 'PERSON', selected: true },
    { text: '李四', type: 'PERSON', selected: true },
    { text: '深圳市', type: 'ADDRESS', selected: false },
  ];

  it('mode=smart produces labeled placeholders with Chinese numerals', () => {
    const map = buildFallbackPreviewEntityMap(entities, 'smart');
    expect(map['张三']).toBe('[当事人一]');
    expect(map['李四']).toBe('[当事人二]');
    expect(map['深圳市']).toBeUndefined(); // not selected
  });

  it('mode=mask masks PERSON keeping first char', () => {
    const map = buildFallbackPreviewEntityMap(
      [{ text: '张三', type: 'PERSON', selected: true }],
      'mask',
    );
    expect(map['张三']).toBe('张*');
  });

  it('mode=mask masks PHONE keeping first 3 and last 4', () => {
    const map = buildFallbackPreviewEntityMap(
      [{ text: '13800138000', type: 'PHONE', selected: true }],
      'mask',
    );
    expect(map['13800138000']).toBe('138****8000');
  });

  it('mode=mask masks ID_CARD keeping first 6 and last 4', () => {
    const map = buildFallbackPreviewEntityMap(
      [{ text: '110101199001011234', type: 'ID_CARD', selected: true }],
      'mask',
    );
    expect(map['110101199001011234']).toBe('110101********1234');
  });

  it('mode=structured produces path-style placeholders', () => {
    const map = buildFallbackPreviewEntityMap(
      [{ text: '张三', type: 'PERSON', selected: true }],
      'structured',
    );
    expect(map['张三']).toBe('<人物[001].个人.姓名>');
  });

  it('filters out entities with empty text', () => {
    const map = buildFallbackPreviewEntityMap(
      [{ text: '', type: 'PERSON', selected: true }],
      'smart',
    );
    expect(Object.keys(map)).toHaveLength(0);
  });
});

describe('mergePreviewMapWithDocumentSlices', () => {
  it('copies apiMap when content is empty', () => {
    const result = mergePreviewMapWithDocumentSlices('', [], { a: 'b' });
    expect(result).toEqual({ a: 'b' });
  });

  it('adds slice-based keys when slice differs from entity text', () => {
    const content = 'Hello World';
    const entities = [{ text: 'hello', start: 0, end: 5, selected: true }];
    const apiMap = { hello: '[REDACTED]' };
    const result = mergePreviewMapWithDocumentSlices(content, entities, apiMap);
    expect(result['Hello']).toBe('[REDACTED]');
    expect(result['hello']).toBe('[REDACTED]');
  });

  it('skips entities with out-of-range offsets', () => {
    const content = 'ABC';
    const entities = [{ text: 'X', start: -1, end: 5, selected: true }];
    const result = mergePreviewMapWithDocumentSlices(content, entities, {});
    expect(Object.keys(result)).toHaveLength(0);
  });

  it('does not overwrite when slice equals entity text', () => {
    const content = 'hello world';
    const entities = [{ text: 'hello', start: 0, end: 5, selected: true }];
    const apiMap = { hello: '[R]' };
    const result = mergePreviewMapWithDocumentSlices(content, entities, apiMap);
    // slice === entity text, so no additional key added
    expect(Object.keys(result)).toEqual(['hello']);
  });
});
