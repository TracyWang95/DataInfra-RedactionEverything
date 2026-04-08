// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import React, { useState, useCallback } from 'react';

import { useT } from '@/i18n';

import { toPixel, type ResizeHandle } from './bbox-utils';
import { useImageViewport, ZOOM_MIN, ZOOM_MAX, ZOOM_STEP } from './hooks/useImageViewport';
import { useBBoxInteraction } from './hooks/useBBoxInteraction';

export interface BoundingBox {
  id: string;
  x: number;
  y: number;
  width: number;
  height: number;
  type: string;
  text?: string;
  selected: boolean;
  confidence?: number;
  source?: 'ocr_has' | 'has_image' | 'manual';
}

interface TypeOption {
  id: string;
  name: string;
  color: string;
}

interface ImageBBoxEditorProps {
  imageSrc: string;
  boxes: BoundingBox[];
  onBoxesChange: (boxes: BoundingBox[]) => void;
  onBoxesCommit?: (prevBoxes: BoundingBox[], nextBoxes: BoundingBox[]) => void;
  getTypeConfig: (typeId: string) => { name: string; color: string };
  availableTypes?: TypeOption[];
  defaultType?: string;

  readOnly?: boolean;

  viewportTopSlot?: React.ReactNode;

  viewportBottomSlot?: React.ReactNode;
}

const BOX_STROKE = '#94a3b8';
const BOX_STROKE_SELECTED = '#64748b';

function ImageBBoxEditor({
  imageSrc,
  boxes,
  onBoxesChange,
  onBoxesCommit,
  getTypeConfig,
  availableTypes: _availableTypes = [],
  defaultType: _defaultType = 'CUSTOM',
  readOnly = false,
  viewportTopSlot,
  viewportBottomSlot,
}: ImageBBoxEditorProps) {
  // --- hooks ----------------------------------------------------------------
  const t = useT();
  const viewport = useImageViewport(imageSrc, readOnly);
  const {
    containerRef, viewportRef, imageRef,
    naturalSize, displaySize,
    displayW, displayH,
    zoom, setZoom,
    handleImageLoad,
  } = viewport;

  const interaction = useBBoxInteraction({
    boxes, onBoxesChange, onBoxesCommit,
    displaySize, imageRef, readOnly,
  });
  const {
    selectedBoxId,
    drawMode, setDrawMode,
    isDragging, isResizing, isDrawing,
    drawingBox,
    handleMouseDown, handleBoxMouseDown,
    handleMouseMove, handleMouseUp,
    handleTouchStart, handleBoxTouchStart,
    handleDelete,
  } = interaction;

  // --- live-region announcements for screen readers -------------------------
  const [liveMessage, setLiveMessage] = useState('');

  const announce = useCallback((msg: string) => {
    // Clear first so repeated identical messages still fire
    setLiveMessage('');
    requestAnimationFrame(() => setLiveMessage(msg));
  }, []);

  // --- keyboard handler (arrows, Tab, Delete, Escape) ----------------------
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      const ARROW_KEYS = new Set(['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight']);

      if (ARROW_KEYS.has(e.key) && selectedBoxId) {
        e.preventDefault();
        e.stopPropagation();
        const step = e.shiftKey ? 5 : 1;
        const normStepX = displaySize.width > 0 ? step / displaySize.width : 0;
        const normStepY = displaySize.height > 0 ? step / displaySize.height : 0;

        const box = boxes.find(b => b.id === selectedBoxId);
        if (!box) return;

        let { x, y } = box;
        switch (e.key) {
          case 'ArrowLeft':  x = Math.max(0, x - normStepX); break;
          case 'ArrowRight': x = Math.min(1 - box.width, x + normStepX); break;
          case 'ArrowUp':    y = Math.max(0, y - normStepY); break;
          case 'ArrowDown':  y = Math.min(1 - box.height, y + normStepY); break;
        }
        onBoxesChange(boxes.map(b => b.id === selectedBoxId ? { ...b, x, y } : b));
        return;
      }

      if (e.key === 'Tab' && boxes.length > 0) {
        e.preventDefault();
        e.stopPropagation();
        const currentIdx = selectedBoxId ? boxes.findIndex(b => b.id === selectedBoxId) : -1;
        const nextIdx = e.shiftKey
          ? (currentIdx <= 0 ? boxes.length - 1 : currentIdx - 1)
          : (currentIdx + 1) % boxes.length;
        const nextBox = boxes[nextIdx];
        interaction.setSelectedBoxId(nextBox.id);
        const config = getTypeConfig(nextBox.type);
        announce(
          `${t('editor.selectedBox')}: ${config.name}${nextBox.text ? ` — ${nextBox.text}` : ''} (${nextIdx + 1}/${boxes.length})`,
        );
        return;
      }

      if (e.key === 'Delete' || e.key === 'Backspace') {
        if (selectedBoxId) {
          e.preventDefault();
          e.stopPropagation();
          handleDelete();
          announce(t('editor.boxDeleted'));
        }
      } else if (e.key === 'Escape') {
        e.preventDefault();
        e.stopPropagation();
        if (drawMode) {
          setDrawMode(false);
          announce(t('editor.exitDraw'));
        } else {
          interaction.setSelectedBoxId(null);
          announce(t('editor.deselected'));
        }
      }
    },
    [selectedBoxId, boxes, displaySize, onBoxesChange, interaction, drawMode, setDrawMode, handleDelete, getTypeConfig, announce, t],
  );

  // --- resize handles -------------------------------------------------------
  const renderResizeHandles = (box: BoundingBox) => {
    const handleSize = 8;
    const handleLabels: Record<string, string> = {
      nw: t('editor.resize.nw'), n: t('editor.resize.n'), ne: t('editor.resize.ne'),
      e: t('editor.resize.e'), se: t('editor.resize.se'), s: t('editor.resize.s'),
      sw: t('editor.resize.sw'), w: t('editor.resize.w'),
    };
    const handles: { pos: ResizeHandle; style: React.CSSProperties }[] = [
      { pos: 'nw', style: { left: -handleSize/2, top: -handleSize/2, cursor: 'nwse-resize' } },
      { pos: 'n', style: { left: '50%', marginLeft: -handleSize/2, top: -handleSize/2, cursor: 'ns-resize' } },
      { pos: 'ne', style: { right: -handleSize/2, top: -handleSize/2, cursor: 'nesw-resize' } },
      { pos: 'e', style: { right: -handleSize/2, top: '50%', marginTop: -handleSize/2, cursor: 'ew-resize' } },
      { pos: 'se', style: { right: -handleSize/2, bottom: -handleSize/2, cursor: 'nwse-resize' } },
      { pos: 's', style: { left: '50%', marginLeft: -handleSize/2, bottom: -handleSize/2, cursor: 'ns-resize' } },
      { pos: 'sw', style: { left: -handleSize/2, bottom: -handleSize/2, cursor: 'nesw-resize' } },
      { pos: 'w', style: { left: -handleSize/2, top: '50%', marginTop: -handleSize/2, cursor: 'ew-resize' } },
    ];

    return handles.map(({ pos, style }) => (
      <div
        key={pos}
        role="separator"
        aria-label={handleLabels[pos!] || t('editor.resize.fallback')}
        className="absolute rounded-sm border border-border bg-[var(--surface-overlay)] shadow-[var(--shadow-sm)]"
        style={{ width: handleSize, height: handleSize, ...style }}
        onMouseDown={(e) => handleBoxMouseDown(e, box.id, pos)}
        onTouchStart={(e) => handleBoxTouchStart(e, box.id, pos)}
      />
    ));
  };

  // --- box rendering --------------------------------------------------------
  const renderBoxes = (percentCoords: boolean) =>
    boxes.map(box => {
      const config = getTypeConfig(box.type);
      const isSelected = box.id === selectedBoxId;
      const stroke = isSelected ? BOX_STROKE_SELECTED : BOX_STROKE;
      const sourceCls =
        box.source === 'ocr_has'
          ? 'border-[var(--selection-regex-border)] bg-[var(--selection-regex-soft)] text-[var(--selection-regex-text)]'
          : box.source === 'has_image'
            ? 'border-[var(--selection-yolo-border)] bg-[var(--selection-yolo-soft)] text-[var(--selection-yolo-text)]'
            : 'border-[var(--selection-ner-border)] bg-[var(--selection-ner-soft)] text-[var(--selection-ner-text)]';

      const posStyle: React.CSSProperties = percentCoords
        ? {
            left: `${box.x * 100}%`,
            top: `${box.y * 100}%`,
            width: `${box.width * 100}%`,
            height: `${box.height * 100}%`,
          }
        : {
            left: toPixel(box.x, 'x', displaySize),
            top: toPixel(box.y, 'y', displaySize),
            width: toPixel(box.width, 'x', displaySize),
            height: toPixel(box.height, 'y', displaySize),
          };

      return (
        <div
          key={box.id}
          className={`absolute transition-[box-shadow,border-color] duration-150 ${isSelected ? 'z-10' : 'z-0'}`}
          style={{
            ...posStyle,
            border: `1px solid ${stroke}`,
            backgroundColor: box.selected ? 'rgba(148, 163, 184, 0.06)' : 'transparent',
            boxShadow: isSelected ? `0 0 0 1px ${BOX_STROKE_SELECTED}` : 'none',
            cursor: readOnly ? 'default' : 'move',
          }}
          onMouseDown={(e) => {
            if (readOnly) return;
            e.stopPropagation();
            handleBoxMouseDown(e, box.id);
          }}
          onTouchStart={(e) => {
            if (readOnly) return;
            e.stopPropagation();
            handleBoxTouchStart(e, box.id);
          }}
          onClick={(e) => e.stopPropagation()}
        >
          <div
            className={`absolute -top-[1.125rem] left-0 max-w-[min(100%,14rem)] px-1 py-px rounded shadow-sm border whitespace-nowrap flex items-center gap-0.5 pointer-events-none ${sourceCls}`}
          >
            <span className="text-[8px] leading-none font-medium tabular-nums shrink-0">
              {box.source === 'ocr_has' ? t('playground.sourceOcr') : box.source === 'has_image' ? t('playground.sourceImage') : t('playground.sourceManual')}
            </span>
            <span className="text-[9px] leading-tight font-normal truncate opacity-90">
              {config.name}
              {box.text ? ` · ${box.text.slice(0, 14)}${box.text.length > 14 ? '…' : ''}` : ''}
            </span>
          </div>

          {isSelected && !drawMode && !readOnly && renderResizeHandles(box)}

          {!box.selected && (
            <div className="absolute inset-0 flex items-center justify-center bg-background/60 backdrop-blur-[1px]">
              <span className="text-[10px] font-medium text-foreground">{t('editor.deselected')}</span>
            </div>
          )}
        </div>
      );
    });

  // --- JSX ------------------------------------------------------------------
  return (
    <div className="flex flex-col h-full min-h-0">
      {/* Toolbar (hidden in readOnly mode) */}
      {!readOnly && (
      <div className="flex flex-wrap items-center gap-1.5 border-b border-border/70 bg-[var(--surface-overlay)] px-2 py-1.5 flex-shrink-0">
        <button
          onClick={() => setDrawMode(!drawMode)}
          aria-label={drawMode ? t('editor.exitDraw') : t('editor.enterDraw')}
          aria-pressed={drawMode}
          className={`px-3 py-1.5 text-xs font-medium rounded-lg flex items-center gap-1.5 transition-colors ${
            drawMode
              ? 'bg-foreground text-background shadow-[var(--shadow-control)]'
              : 'border border-input bg-[var(--surface-control)] text-muted-foreground hover:bg-accent hover:text-foreground'
          }`}
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
          </svg>
          {drawMode ? t('editor.drawModeActive') : t('editor.drawModeTrigger')}
        </button>

        {selectedBoxId && (
          <button
            onClick={handleDelete}
            aria-label={t('editor.deleteSelected')}
            className="flex items-center gap-1.5 rounded-lg border border-[var(--error-border)] bg-[var(--error-surface)] px-3 py-1.5 text-xs font-medium text-[var(--error-foreground)] shadow-[var(--shadow-sm)]"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
            </svg>
            {t('editor.deleteSelectedShort')}
          </button>
        )}

        <div className="flex items-center gap-1.5">
          <span className="text-xs text-ink-muted">{t('editor.zoom')} {Math.round(zoom * 100)}%</span>
          <button
            onClick={() => setZoom(z => Math.max(ZOOM_MIN, +(z - ZOOM_STEP).toFixed(2)))}
            className="rounded-lg border border-input bg-[var(--surface-control)] px-2 py-1 text-xs text-muted-foreground shadow-[var(--shadow-sm)] hover:bg-accent hover:text-foreground"
            aria-label={t('editor.zoomOut')}
          >
            -
          </button>
          <button
            onClick={() => setZoom(z => Math.min(ZOOM_MAX, +(z + ZOOM_STEP).toFixed(2)))}
            className="rounded-lg border border-input bg-[var(--surface-control)] px-2 py-1 text-xs text-muted-foreground shadow-[var(--shadow-sm)] hover:bg-accent hover:text-foreground"
            aria-label={t('editor.zoomIn')}
          >
            +
          </button>
          <button
            type="button"
            onClick={() => setZoom(1)}
            className="rounded-lg border border-input bg-[var(--surface-control)] px-2 py-1 text-xs text-muted-foreground shadow-[var(--shadow-sm)] hover:bg-accent hover:text-foreground"
            aria-label={t('editor.zoomFit')}
            title={t('editor.zoomFit')}
          >
            {t('editor.fit')}
          </button>
        </div>

        <div className="ml-auto hidden sm:block text-[10px] text-ink-muted truncate max-w-[min(100%,14rem)]">
          {boxes.length} {t('playground.regionList')}
        </div>
      </div>
      )}

      {/* Image viewport */}
      <div
        ref={viewportRef}
        className={`relative flex-1 w-full min-h-0 ${readOnly ? 'overflow-hidden' : 'overflow-auto'} flex items-center justify-center bg-[var(--surface-canvas)] ${
          viewportTopSlot ? 'pt-11' : ''
        } ${viewportBottomSlot ? 'pb-14' : ''}`}
      >
        {viewportTopSlot && (
          <div className="pointer-events-none absolute left-1.5 right-1.5 top-1 z-30 max-w-[calc(100%-0.75rem)]">
            <div className="pointer-events-auto flex flex-wrap items-center gap-1">{viewportTopSlot}</div>
          </div>
        )}
        {viewportBottomSlot && (
          <div className="pointer-events-none absolute left-1.5 right-1.5 bottom-2 z-30 flex flex-wrap items-center justify-center gap-2">
            <div className="pointer-events-auto">{viewportBottomSlot}</div>
          </div>
        )}
        {readOnly ? (
          <div
            role="img"
            aria-label="Image redaction preview (read-only)"
            className="relative shrink-0 leading-none"
            style={
              naturalSize.width > 0 && naturalSize.height > 0
                ? (() => {
                    const vw = viewportRef.current?.clientWidth || 800;
                    const vh = viewportRef.current?.clientHeight || 600;
                    const scale = Math.min(vw / naturalSize.width, vh / naturalSize.height, 1);
                    return { width: naturalSize.width * scale, height: naturalSize.height * scale };
                  })()
                : undefined
            }
          >
            <img
              ref={imageRef}
              src={imageSrc}
              alt=""
              className="block w-full h-full select-none"
              onLoad={handleImageLoad}
              draggable={false}
            />
            <div className="pointer-events-none absolute inset-0 z-[1]">{renderBoxes(true)}</div>
          </div>
        ) : (
          <div
            ref={containerRef}
            role="application"
            aria-label={t('editor.canvasLabel')}
            aria-roledescription="bounding box editor"
            tabIndex={0}
            className={`relative inline-block shrink-0 ${drawMode ? 'cursor-crosshair' : 'cursor-default'}`}
            style={{
              width: displayW > 0 ? displayW : undefined,
              height: displayH > 0 ? displayH : undefined,
              touchAction: 'none',
            }}
            onKeyDown={handleKeyDown}
            onMouseDown={handleMouseDown}
            onMouseMove={handleMouseMove}
            onMouseUp={handleMouseUp}
            onTouchStart={handleTouchStart}
            onTouchEnd={() => handleMouseUp()}
            onMouseLeave={() => {
              if (!isDragging && !isResizing && !isDrawing) handleMouseUp();
            }}
          >
            <img
              ref={imageRef}
              src={imageSrc}
              alt="edit"
              className="select-none block max-w-none"
              width={displayW > 0 ? Math.round(displayW) : undefined}
              height={displayH > 0 ? Math.round(displayH) : undefined}
              style={{
                width: displayW > 0 ? displayW : undefined,
                height: displayH > 0 ? displayH : undefined,
              }}
              onLoad={handleImageLoad}
              draggable={false}
            />

            {renderBoxes(false)}

            {drawingBox && drawingBox.width > 5 && drawingBox.height > 5 && (
              <div
                className="pointer-events-none absolute border border-dashed border-[var(--selection-regex-border)] bg-[var(--selection-regex-soft)]"
                style={{
                  left: drawingBox.left,
                  top: drawingBox.top,
                  width: drawingBox.width,
                  height: drawingBox.height,
                }}
              />
            )}
          </div>
        )}
      </div>
      {/* Visually-hidden live region for screen reader announcements */}
      <div
        role="status"
        aria-live="polite"
        aria-atomic="true"
        className="sr-only"
      >
        {liveMessage}
      </div>
    </div>
  );
}

export default ImageBBoxEditor;
