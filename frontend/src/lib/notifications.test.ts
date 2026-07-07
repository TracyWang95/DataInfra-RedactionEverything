// Copyright 2026 DataInfra-RedactionEverything Contributors

import { describe, expect, it } from 'vitest';
import { phaseJustFinished } from './notifications';

describe('phaseJustFinished', () => {
  it('fires exactly on the >0 -> 0 transition', () => {
    expect(phaseJustFinished(5, 0)).toBe(true);
    expect(phaseJustFinished(1, 0)).toBe(true);
  });

  it('does not fire while work remains or when idle', () => {
    expect(phaseJustFinished(5, 3)).toBe(false);
    expect(phaseJustFinished(0, 0)).toBe(false);
    // 新任务开跑（0 -> N）不是完成
    expect(phaseJustFinished(0, 4)).toBe(false);
  });
});
