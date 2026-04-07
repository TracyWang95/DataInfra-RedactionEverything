// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

/**
 * Shared DOM selection helpers used by both Playground and Batch review UIs.
 */

/** Calculate character offsets of a Range relative to a root element. */
export function getSelectionOffsets(range: Range, root: HTMLElement): { start: number; end: number } | null {
  let start = -1;
  let end = -1;
  let offset = 0;
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);

  while (walker.nextNode()) {
    const node = walker.currentNode as Text;
    const textLength = node.textContent?.length || 0;
    if (node === range.startContainer) start = offset + range.startOffset;
    if (node === range.endContainer) {
      end = offset + range.endOffset;
      break;
    }
    offset += textLength;
  }

  if (start === -1 || end === -1 || end <= start) return null;
  return { start, end };
}

/** Clamp popover position so it stays within the canvas area. */
export function clampPopoverInCanvas(
  anchorRect: DOMRect,
  canvasRect: DOMRect,
  popoverWidth: number,
  popoverHeight: number,
): { left: number; top: number } {
  const margin = 8;
  const maxW = Math.max(120, Math.min(popoverWidth, canvasRect.width - 2 * margin));
  const maxH = Math.max(80, Math.min(popoverHeight, canvasRect.height - 2 * margin));
  const cx = anchorRect.left + anchorRect.width / 2;
  let left = cx - maxW / 2;
  left = Math.max(canvasRect.left + margin, Math.min(left, canvasRect.right - margin - maxW));

  let top = anchorRect.top - margin - maxH;
  if (top < canvasRect.top + margin) {
    top = anchorRect.bottom + margin;
  }
  if (top + maxH > canvasRect.bottom - margin) {
    top = Math.max(canvasRect.top + margin, canvasRect.bottom - margin - maxH);
  }

  return { left, top };
}
