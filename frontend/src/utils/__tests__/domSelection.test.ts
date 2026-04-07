// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect } from 'vitest';
import { clampPopoverInCanvas } from '../domSelection';

// Note: getSelectionOffsets relies on document.createTreeWalker + Range,
// which is hard to unit-test without a real DOM tree. We test clampPopoverInCanvas
// which is pure math and can be thoroughly covered.

function rect(x: number, y: number, w: number, h: number): DOMRect {
  return { x, y, width: w, height: h, left: x, top: y, right: x + w, bottom: y + h, toJSON: () => ({}) } as DOMRect;
}

describe('clampPopoverInCanvas', () => {
  const canvas = rect(0, 0, 800, 600);

  it('centers popover above anchor when there is room', () => {
    const anchor = rect(390, 300, 20, 20);
    const result = clampPopoverInCanvas(anchor, canvas, 100, 40);
    // popover should be above the anchor
    expect(result.top).toBeLessThan(anchor.top);
    // horizontally centered (popover width is clamped to min 120, so center = 400 - 60 = 340)
    expect(result.left).toBe(340);
  });

  it('flips popover below anchor when no room above', () => {
    const anchor = rect(390, 10, 20, 20);
    const result = clampPopoverInCanvas(anchor, canvas, 100, 40);
    // not enough room above, should appear below
    expect(result.top).toBeGreaterThanOrEqual(anchor.bottom);
  });

  it('clamps left edge to stay within canvas', () => {
    const anchor = rect(0, 300, 10, 20);
    const result = clampPopoverInCanvas(anchor, canvas, 200, 40);
    expect(result.left).toBeGreaterThanOrEqual(8); // margin = 8
  });

  it('clamps right edge to stay within canvas', () => {
    const anchor = rect(790, 300, 10, 20);
    const result = clampPopoverInCanvas(anchor, canvas, 200, 40);
    expect(result.left + 200).toBeLessThanOrEqual(canvas.right);
  });

  it('handles popover larger than canvas by clamping to min sizes', () => {
    const smallCanvas = rect(0, 0, 100, 100);
    const anchor = rect(40, 50, 20, 10);
    const result = clampPopoverInCanvas(anchor, smallCanvas, 2000, 2000);
    expect(result.left).toBeGreaterThanOrEqual(smallCanvas.left);
    expect(result.top).toBeGreaterThanOrEqual(smallCanvas.top);
  });
});
