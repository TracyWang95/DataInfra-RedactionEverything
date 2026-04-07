import { describe, it, expect } from 'vitest';
import { toneBadgeClass, tonePanelClass } from '../toneClasses';

const ALL_TONES = ['neutral', 'brand', 'warning', 'review', 'success', 'danger', 'muted'] as const;

describe('toneBadgeClass', () => {
  it('provides a class for every tone', () => {
    for (const tone of ALL_TONES) {
      expect(toneBadgeClass[tone]).toMatch(/^tone-badge-/);
    }
  });

  it('has no duplicate values', () => {
    const values = Object.values(toneBadgeClass);
    expect(new Set(values).size).toBe(values.length);
  });
});

describe('tonePanelClass', () => {
  it('provides a class for every tone', () => {
    for (const tone of ALL_TONES) {
      expect(tonePanelClass[tone]).toMatch(/^tone-panel-/);
    }
  });

  it('has no duplicate values', () => {
    const values = Object.values(tonePanelClass);
    expect(new Set(values).size).toBe(values.length);
  });
});
