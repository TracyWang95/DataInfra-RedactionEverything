/**
 * Pure utility functions for bounding-box coordinate transforms and resize computation.
 * No React dependencies — safe to use in hooks, workers, or tests.
 */

export type ResizeHandle = 'nw' | 'n' | 'ne' | 'e' | 'se' | 's' | 'sw' | 'w' | null;

/** Minimum normalised size of a box edge (prevents zero-area boxes). */
export const MIN_BOX_SIZE = 0.01;

/* ------------------------------------------------------------------ */
/*  Coordinate transforms (normalised ↔ pixel)                       */
/* ------------------------------------------------------------------ */

export interface DisplaySize {
  width: number;
  height: number;
}

/** Convert a normalised [0,1] value to pixel distance. */
export function toPixel(
  normalized: number,
  dimension: 'x' | 'y',
  display: DisplaySize,
): number {
  return normalized * (dimension === 'x' ? display.width : display.height);
}

/** Convert a pixel distance to normalised [0,1] value. */
export function toNormalized(
  pixel: number,
  dimension: 'x' | 'y',
  display: DisplaySize,
): number {
  const size = dimension === 'x' ? display.width : display.height;
  return size > 0 ? pixel / size : 0;
}

/** Clamp a pixel position to the image bounds given a client coordinate and a DOMRect. */
export function clampMousePos(
  clientX: number,
  clientY: number,
  rect: DOMRect,
  display: DisplaySize,
): { x: number; y: number } {
  return {
    x: Math.max(0, Math.min(clientX - rect.left, display.width)),
    y: Math.max(0, Math.min(clientY - rect.top, display.height)),
  };
}

/* ------------------------------------------------------------------ */
/*  Resize computation                                                */
/* ------------------------------------------------------------------ */

export interface BoxRect {
  x: number;
  y: number;
  width: number;
  height: number;
}

/**
 * Compute the new box geometry after a resize-handle drag.
 * All values are normalised [0,1]. The result is clamped to [0,1].
 */
export function computeResize(
  box: BoxRect,
  handle: NonNullable<ResizeHandle>,
  normX: number,
  normY: number,
): BoxRect {
  const minSize = MIN_BOX_SIZE;
  const b: BoxRect = { ...box };

  switch (handle) {
    case 'nw':
      b.width = Math.max(minSize, box.x + box.width - normX);
      b.height = Math.max(minSize, box.y + box.height - normY);
      b.x = Math.min(normX, box.x + box.width - minSize);
      b.y = Math.min(normY, box.y + box.height - minSize);
      break;
    case 'n':
      b.height = Math.max(minSize, box.y + box.height - normY);
      b.y = Math.min(normY, box.y + box.height - minSize);
      break;
    case 'ne':
      b.width = Math.max(minSize, normX - box.x);
      b.height = Math.max(minSize, box.y + box.height - normY);
      b.y = Math.min(normY, box.y + box.height - minSize);
      break;
    case 'e':
      b.width = Math.max(minSize, normX - box.x);
      break;
    case 'se':
      b.width = Math.max(minSize, normX - box.x);
      b.height = Math.max(minSize, normY - box.y);
      break;
    case 's':
      b.height = Math.max(minSize, normY - box.y);
      break;
    case 'sw':
      b.width = Math.max(minSize, box.x + box.width - normX);
      b.height = Math.max(minSize, normY - box.y);
      b.x = Math.min(normX, box.x + box.width - minSize);
      break;
    case 'w':
      b.width = Math.max(minSize, box.x + box.width - normX);
      b.x = Math.min(normX, box.x + box.width - minSize);
      break;
  }

  // Clamp into [0, 1]
  b.x = Math.max(0, b.x);
  b.y = Math.max(0, b.y);
  b.width = Math.min(b.width, 1 - b.x);
  b.height = Math.min(b.height, 1 - b.y);

  return b;
}

/* ------------------------------------------------------------------ */
/*  Fit-scale helper                                                  */
/* ------------------------------------------------------------------ */

/** Compute the scale that makes `natural` fit inside `viewport` (contain). */
export function computeFitScale(
  natural: DisplaySize,
  viewport: DisplaySize,
): number {
  if (natural.width <= 0 || natural.height <= 0) return 0;
  if (viewport.width <= 0 || viewport.height <= 0) return 0;
  return Math.min(viewport.width / natural.width, viewport.height / natural.height);
}
