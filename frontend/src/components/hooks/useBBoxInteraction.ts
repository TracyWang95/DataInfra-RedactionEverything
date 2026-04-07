import { useState, useRef, useEffect, useCallback } from 'react';
import type { BoundingBox } from '../ImageBBoxEditor';
import {
  toPixel, toNormalized, clampMousePos, computeResize,
  type ResizeHandle, type DisplaySize,
} from '../bbox-utils';

export interface UseBBoxInteractionOptions {
  boxes: BoundingBox[];
  onBoxesChange: (boxes: BoundingBox[]) => void;
  onBoxesCommit?: (prev: BoundingBox[], next: BoundingBox[]) => void;
  displaySize: DisplaySize;
  imageRef: React.RefObject<HTMLImageElement | null>;
  readOnly: boolean;
}

export interface UseBBoxInteractionReturn {
  selectedBoxId: string | null;
  setSelectedBoxId: React.Dispatch<React.SetStateAction<string | null>>;
  drawMode: boolean;
  setDrawMode: React.Dispatch<React.SetStateAction<boolean>>;
  isDragging: boolean;
  isResizing: boolean;
  isDrawing: boolean;
  drawingBox: { left: number; top: number; width: number; height: number } | null;
  handleMouseDown: (e: React.MouseEvent) => void;
  handleBoxMouseDown: (e: React.MouseEvent, boxId: string, handle?: ResizeHandle) => void;
  handleMouseMove: (e: React.MouseEvent | MouseEvent) => void;
  handleMouseUp: () => void;
  handleTouchStart: (e: React.TouchEvent) => void;
  handleBoxTouchStart: (e: React.TouchEvent, boxId: string, handle?: ResizeHandle) => void;
  handleDelete: () => void;
}

export function useBBoxInteraction(opts: UseBBoxInteractionOptions): UseBBoxInteractionReturn {
  const { boxes, onBoxesChange, onBoxesCommit, displaySize, imageRef, readOnly } = opts;

  const [selectedBoxId, setSelectedBoxId] = useState<string | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [isResizing, setIsResizing] = useState(false);
  const [resizeHandle, setResizeHandle] = useState<ResizeHandle>(null);
  const [isDrawing, setIsDrawing] = useState(false);
  const [drawStart, setDrawStart] = useState({ x: 0, y: 0 });
  const [drawCurrent, setDrawCurrent] = useState({ x: 0, y: 0 });
  const [dragOffset, setDragOffset] = useState({ x: 0, y: 0 });
  const [drawMode, setDrawMode] = useState(false);

  const lastBoxesRef = useRef<BoundingBox[]>(boxes);
  const editStartBoxesRef = useRef<BoundingBox[] | null>(null);

  useEffect(() => { lastBoxesRef.current = boxes; }, [boxes]);

  useEffect(() => {
    if (readOnly) {
      setDrawMode(false); setSelectedBoxId(null);
      setIsDrawing(false); setIsDragging(false); setIsResizing(false);
    }
  }, [readOnly]);

  // Pixel / normalised wrappers
  const px = useCallback(
    (v: number, dim: 'x' | 'y') => toPixel(v, dim, displaySize), [displaySize],
  );
  const norm = useCallback(
    (v: number, dim: 'x' | 'y') => toNormalized(v, dim, displaySize), [displaySize],
  );
  const getPos = useCallback(
    (clientX: number, clientY: number) => {
      if (!imageRef.current) return { x: 0, y: 0 };
      return clampMousePos(clientX, clientY, imageRef.current.getBoundingClientRect(), displaySize);
    }, [displaySize, imageRef],
  );

  // Begin draw on canvas
  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    if (readOnly || !drawMode) return;
    e.preventDefault();
    editStartBoxesRef.current = boxes;
    const pos = getPos(e.clientX, e.clientY);
    setDrawStart(pos); setDrawCurrent(pos); setIsDrawing(true); setSelectedBoxId(null);
  }, [readOnly, drawMode, getPos, boxes]);

  // Shared: begin drag/resize on an existing box
  const beginBoxInteraction = useCallback((cx: number, cy: number, boxId: string, handle?: ResizeHandle) => {
    setSelectedBoxId(boxId);
    editStartBoxesRef.current = boxes;
    const pos = getPos(cx, cy);
    const box = boxes.find(b => b.id === boxId);
    if (!box) return;
    if (handle) { setIsResizing(true); setResizeHandle(handle); }
    else { setIsDragging(true); setDragOffset({ x: pos.x - px(box.x, 'x'), y: pos.y - px(box.y, 'y') }); }
  }, [boxes, getPos, px]);

  const handleBoxMouseDown = useCallback((e: React.MouseEvent, boxId: string, handle?: ResizeHandle) => {
    if (readOnly) return;
    e.preventDefault(); e.stopPropagation();
    beginBoxInteraction(e.clientX, e.clientY, boxId, handle);
  }, [readOnly, beginBoxInteraction]);

  // Shared pointer-move logic (mouse + touch)
  const applyPointerMove = useCallback((pos: { x: number; y: number }) => {
    if (readOnly) return;
    if (isDrawing) { setDrawCurrent(pos); return; }
    if (!selectedBoxId) return;
    const box = boxes.find(b => b.id === selectedBoxId);
    if (!box) return;
    if (isDragging) {
      const clampedX = Math.max(0, Math.min(norm(pos.x - dragOffset.x, 'x'), 1 - box.width));
      const clampedY = Math.max(0, Math.min(norm(pos.y - dragOffset.y, 'y'), 1 - box.height));
      onBoxesChange(boxes.map(b => b.id === selectedBoxId ? { ...b, x: clampedX, y: clampedY } : b));
    } else if (isResizing && resizeHandle) {
      const resized = computeResize(box, resizeHandle, norm(pos.x, 'x'), norm(pos.y, 'y'));
      onBoxesChange(boxes.map(b => b.id === selectedBoxId ? { ...b, ...resized } : b));
    }
  }, [readOnly, isDrawing, isDragging, isResizing, selectedBoxId, boxes, dragOffset, resizeHandle, norm, onBoxesChange]);

  const handleMouseMove = useCallback(
    (e: React.MouseEvent | MouseEvent) => applyPointerMove(getPos(e.clientX, e.clientY)),
    [applyPointerMove, getPos],
  );

  const handleMouseUp = useCallback(() => {
    if (readOnly) return;
    if (isDrawing) {
      const x1 = norm(Math.min(drawStart.x, drawCurrent.x), 'x');
      const y1 = norm(Math.min(drawStart.y, drawCurrent.y), 'y');
      const w = norm(Math.max(drawStart.x, drawCurrent.x), 'x') - x1;
      const h = norm(Math.max(drawStart.y, drawCurrent.y), 'y') - y1;
      if (w > 0.01 && h > 0.01) {
        const newBox: BoundingBox = {
          id: `manual_${Date.now()}`, x: x1, y: y1, width: w, height: h,
          type: 'CUSTOM', text: '自定义', selected: true, confidence: 1.0, source: 'manual',
        };
        const nextBoxes = [...boxes, newBox];
        onBoxesChange(nextBoxes);
        onBoxesCommit?.(boxes, nextBoxes);
        setSelectedBoxId(newBox.id);
      }
    }
    if ((isDragging || isResizing) && editStartBoxesRef.current) {
      onBoxesCommit?.(editStartBoxesRef.current, lastBoxesRef.current);
    }
    setIsDrawing(false); setIsDragging(false); setIsResizing(false); setResizeHandle(null);
    editStartBoxesRef.current = null;
  }, [readOnly, isDrawing, isDragging, isResizing, drawStart, drawCurrent, boxes, norm, onBoxesChange, onBoxesCommit]);

  // Touch handlers
  const handleTouchStart = useCallback((e: React.TouchEvent) => {
    if (readOnly || !drawMode) return;
    e.preventDefault();
    editStartBoxesRef.current = boxes;
    const t = e.touches[0];
    const pos = getPos(t.clientX, t.clientY);
    setDrawStart(pos); setDrawCurrent(pos); setIsDrawing(true); setSelectedBoxId(null);
  }, [readOnly, drawMode, getPos, boxes]);

  const handleBoxTouchStart = useCallback((e: React.TouchEvent, boxId: string, handle?: ResizeHandle) => {
    if (readOnly) return;
    e.preventDefault(); e.stopPropagation();
    const t = e.touches[0];
    beginBoxInteraction(t.clientX, t.clientY, boxId, handle);
  }, [readOnly, beginBoxInteraction]);

  const handleTouchMove = useCallback((e: TouchEvent | React.TouchEvent) => {
    const t = ('touches' in e) ? e.touches[0] : (e as React.TouchEvent).touches[0];
    if (t) applyPointerMove(getPos(t.clientX, t.clientY));
  }, [applyPointerMove, getPos]);

  // Global listeners: track pointer outside the image area during active gestures
  useEffect(() => {
    if (readOnly || (!isDragging && !isResizing && !isDrawing)) return;
    const onMove = (e: MouseEvent) => handleMouseMove(e);
    const onTouchMove = (e: TouchEvent) => { e.preventDefault(); handleTouchMove(e); };
    const onUp = () => handleMouseUp();
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
    document.addEventListener('touchmove', onTouchMove, { passive: false });
    document.addEventListener('touchend', onUp);
    document.addEventListener('touchcancel', onUp);
    return () => {
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
      document.removeEventListener('touchmove', onTouchMove);
      document.removeEventListener('touchend', onUp);
      document.removeEventListener('touchcancel', onUp);
    };
  }, [readOnly, isDragging, isResizing, isDrawing, handleMouseMove, handleMouseUp, handleTouchMove]);

  // Delete selected box
  const handleDelete = useCallback(() => {
    if (readOnly || !selectedBoxId) return;
    const nextBoxes = boxes.filter(b => b.id !== selectedBoxId);
    onBoxesChange(nextBoxes);
    onBoxesCommit?.(boxes, nextBoxes);
    setSelectedBoxId(null);
  }, [readOnly, selectedBoxId, boxes, onBoxesChange, onBoxesCommit]);

  // Keyboard shortcuts
  useEffect(() => {
    if (readOnly) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Delete' || e.key === 'Backspace') handleDelete();
      else if (e.key === 'Escape') { setSelectedBoxId(null); setDrawMode(false); }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [readOnly, handleDelete]);

  const drawingBox = isDrawing ? {
    left: Math.min(drawStart.x, drawCurrent.x),
    top: Math.min(drawStart.y, drawCurrent.y),
    width: Math.abs(drawCurrent.x - drawStart.x),
    height: Math.abs(drawCurrent.y - drawStart.y),
  } : null;

  return {
    selectedBoxId, setSelectedBoxId, drawMode, setDrawMode,
    isDragging, isResizing, isDrawing, drawingBox,
    handleMouseDown, handleBoxMouseDown, handleMouseMove, handleMouseUp,
    handleTouchStart, handleBoxTouchStart, handleDelete,
  };
}
