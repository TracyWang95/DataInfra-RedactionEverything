import { describe, it, expect } from 'vitest';
import { computeEntityStats, getModePreview } from './playground-utils';
import type { Entity } from './playground-types';

describe('computeEntityStats', () => {
  it('returns empty stats for empty array', () => {
    expect(computeEntityStats([])).toEqual({});
  });

  it('counts total and selected per type', () => {
    const entities: Entity[] = [
      { id: '1', text: 'A', type: 'PERSON', start: 0, end: 1, selected: true, source: 'has' },
      { id: '2', text: 'B', type: 'PERSON', start: 2, end: 3, selected: false, source: 'has' },
      { id: '3', text: 'C', type: 'PHONE', start: 4, end: 5, selected: true, source: 'regex' },
    ];
    const stats = computeEntityStats(entities);
    expect(stats['PERSON']).toEqual({ total: 2, selected: 1 });
    expect(stats['PHONE']).toEqual({ total: 1, selected: 1 });
  });
});

describe('getModePreview', () => {
  it('smart mode', () => {
    expect(getModePreview('smart')).toContain('当事人一');
  });

  it('mask mode', () => {
    expect(getModePreview('mask')).toContain('*');
  });

  it('structured mode', () => {
    expect(getModePreview('structured')).toContain('人物[001]');
  });

  it('unknown mode returns empty', () => {
    expect(getModePreview('unknown')).toBe('');
  });
});
