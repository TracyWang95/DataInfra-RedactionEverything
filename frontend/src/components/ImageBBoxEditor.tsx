import React, { useState, useRef, useEffect, useCallback, useMemo } from 'react';

export interface BoundingBox {
  id: string;
  x: number;      // 归一化坐标 0-1
  y: number;
  width: number;
  height: number;
  type: string;
  text?: string;
  selected: boolean;
  confidence?: number;
  source?: 'ocr_has' | 'has_image' | 'manual';  // 来源 Pipeline
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
  /** 仅展示框与底图，隐藏拉框/缩放等工具栏，禁止编辑（如 Playground 脱敏完成对比） */
  readOnly?: boolean;
  /** 浮在图片区域顶部（如批量核对：文件名、翻张、上一步） */
  viewportTopSlot?: React.ReactNode;
  /** 浮在图片区域底部（如批量核对：确认本张） */
  viewportBottomSlot?: React.ReactNode;
}

type ResizeHandle = 'nw' | 'n' | 'ne' | 'e' | 'se' | 's' | 'sw' | 'w' | null;

/** 画布框线：浅 slate，避免深灰黑压图 */
const BOX_STROKE = '#94a3b8';
const BOX_STROKE_SELECTED = '#64748b';

const ImageBBoxEditor: React.FC<ImageBBoxEditorProps> = ({
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
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const viewportRef = useRef<HTMLDivElement>(null);
  const imageRef = useRef<HTMLImageElement>(null);
  const [naturalSize, setNaturalSize] = useState({ width: 0, height: 0 });
  const [viewportSize, setViewportSize] = useState({ width: 0, height: 0 });
  const [displaySize, setDisplaySize] = useState({ width: 0, height: 0 });
  
  const [selectedBoxId, setSelectedBoxId] = useState<string | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [isResizing, setIsResizing] = useState(false);
  const [resizeHandle, setResizeHandle] = useState<ResizeHandle>(null);
  const [isDrawing, setIsDrawing] = useState(false);
  const [drawStart, setDrawStart] = useState({ x: 0, y: 0 });
  const [drawCurrent, setDrawCurrent] = useState({ x: 0, y: 0 });
  const [dragOffset, setDragOffset] = useState({ x: 0, y: 0 });
  const [drawMode, setDrawMode] = useState(false);
  const [zoom, setZoom] = useState(1);
  const lastBoxesRef = useRef<BoundingBox[]>(boxes);
  const editStartBoxesRef = useRef<BoundingBox[] | null>(null);
  const ZOOM_MIN = 0.5;
  const ZOOM_MAX = 3;
  const ZOOM_STEP = 0.1;

  /** 视口尺寸：用于「按可用空间适应」缩放 */
  useEffect(() => {
    const el = viewportRef.current;
    if (!el) return;
    const ro = new ResizeObserver(entries => {
      const cr = entries[0]?.contentRect;
      if (!cr) return;
      setViewportSize({ width: cr.width, height: cr.height });
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  /** 在视口内完整显示图片的基准比例；用户 zoom 在此基础上再放大/缩小 */
  const fitScale = useMemo(() => {
    if (naturalSize.width <= 0 || naturalSize.height <= 0) return 0;
    if (viewportSize.width <= 0 || viewportSize.height <= 0) return 0;
    return Math.min(viewportSize.width / naturalSize.width, viewportSize.height / naturalSize.height);
  }, [naturalSize, viewportSize]);

  const displayW = naturalSize.width * fitScale * zoom;
  const displayH = naturalSize.height * fitScale * zoom;

  // 加载图片尺寸
  const handleImageLoad = useCallback(() => {
    if (imageRef.current) {
      setNaturalSize({
        width: imageRef.current.naturalWidth,
        height: imageRef.current.naturalHeight,
      });
    }
  }, []);

  useEffect(() => {
    setDisplaySize({ width: displayW, height: displayH });
  }, [displayW, displayH]);

  useEffect(() => {
    setZoom(1);
    setNaturalSize({ width: 0, height: 0 });
  }, [imageSrc]);

  useEffect(() => {
    if (readOnly) {
      setZoom(1);
      setDrawMode(false);
      setSelectedBoxId(null);
      setIsDrawing(false);
      setIsDragging(false);
      setIsResizing(false);
    }
  }, [readOnly]);

  useEffect(() => {
    lastBoxesRef.current = boxes;
  }, [boxes]);

  // 归一化坐标转像素
  const toPixel = useCallback((normalized: number, dimension: 'x' | 'y') => {
    return normalized * (dimension === 'x' ? displaySize.width : displaySize.height);
  }, [displaySize]);

  // 像素转归一化坐标
  const toNormalized = useCallback((pixel: number, dimension: 'x' | 'y') => {
    const size = dimension === 'x' ? displaySize.width : displaySize.height;
    return size > 0 ? pixel / size : 0;
  }, [displaySize]);

  // 获取鼠标相对于图片的位置（支持 React 事件与 document 上的原生事件）
  const getMousePosFromClient = useCallback((clientX: number, clientY: number) => {
    if (!imageRef.current) return { x: 0, y: 0 };
    const rect = imageRef.current.getBoundingClientRect();
    return {
      x: Math.max(0, Math.min(clientX - rect.left, displaySize.width)),
      y: Math.max(0, Math.min(clientY - rect.top, displaySize.height)),
    };
  }, [displaySize]);

  const getMousePos = useCallback(
    (e: React.MouseEvent) => getMousePosFromClient(e.clientX, e.clientY),
    [getMousePosFromClient]
  );

  // 开始绘制新框
  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    if (readOnly) return;
    if (!drawMode) return;
    e.preventDefault();
    editStartBoxesRef.current = boxes;
    const pos = getMousePos(e);
    setDrawStart(pos);
    setDrawCurrent(pos);
    setIsDrawing(true);
    setSelectedBoxId(null);
  }, [readOnly, drawMode, getMousePos, boxes]);

  // 开始拖拽或调整大小
  const handleBoxMouseDown = useCallback((e: React.MouseEvent, boxId: string, handle?: ResizeHandle) => {
    if (readOnly) return;
    e.preventDefault();
    e.stopPropagation();
    setSelectedBoxId(boxId);
    editStartBoxesRef.current = boxes;
    
    const pos = getMousePos(e);
    const box = boxes.find(b => b.id === boxId);
    if (!box) return;

    if (handle) {
      setIsResizing(true);
      setResizeHandle(handle);
    } else {
      setIsDragging(true);
      setDragOffset({
        x: pos.x - toPixel(box.x, 'x'),
        y: pos.y - toPixel(box.y, 'y'),
      });
    }
  }, [readOnly, boxes, getMousePos, toPixel]);

  // 鼠标移动
  const handleMouseMove = useCallback((e: React.MouseEvent | MouseEvent) => {
    if (readOnly) return;
    const pos = getMousePosFromClient(e.clientX, e.clientY);

    if (isDrawing) {
      setDrawCurrent(pos);
      return;
    }

    if (!selectedBoxId) return;
    const box = boxes.find(b => b.id === selectedBoxId);
    if (!box) return;

    if (isDragging) {
      const newX = toNormalized(pos.x - dragOffset.x, 'x');
      const newY = toNormalized(pos.y - dragOffset.y, 'y');
      
      // 确保不超出边界
      const clampedX = Math.max(0, Math.min(newX, 1 - box.width));
      const clampedY = Math.max(0, Math.min(newY, 1 - box.height));

      onBoxesChange(boxes.map(b => 
        b.id === selectedBoxId ? { ...b, x: clampedX, y: clampedY } : b
      ));
    } else if (isResizing && resizeHandle) {
      const normX = toNormalized(pos.x, 'x');
      const normY = toNormalized(pos.y, 'y');
      
      let newBox = { ...box };
      const minSize = 0.01; // 最小尺寸

      switch (resizeHandle) {
        case 'nw':
          newBox.width = Math.max(minSize, box.x + box.width - normX);
          newBox.height = Math.max(minSize, box.y + box.height - normY);
          newBox.x = Math.min(normX, box.x + box.width - minSize);
          newBox.y = Math.min(normY, box.y + box.height - minSize);
          break;
        case 'n':
          newBox.height = Math.max(minSize, box.y + box.height - normY);
          newBox.y = Math.min(normY, box.y + box.height - minSize);
          break;
        case 'ne':
          newBox.width = Math.max(minSize, normX - box.x);
          newBox.height = Math.max(minSize, box.y + box.height - normY);
          newBox.y = Math.min(normY, box.y + box.height - minSize);
          break;
        case 'e':
          newBox.width = Math.max(minSize, normX - box.x);
          break;
        case 'se':
          newBox.width = Math.max(minSize, normX - box.x);
          newBox.height = Math.max(minSize, normY - box.y);
          break;
        case 's':
          newBox.height = Math.max(minSize, normY - box.y);
          break;
        case 'sw':
          newBox.width = Math.max(minSize, box.x + box.width - normX);
          newBox.height = Math.max(minSize, normY - box.y);
          newBox.x = Math.min(normX, box.x + box.width - minSize);
          break;
        case 'w':
          newBox.width = Math.max(minSize, box.x + box.width - normX);
          newBox.x = Math.min(normX, box.x + box.width - minSize);
          break;
      }

      // 边界检查
      newBox.x = Math.max(0, newBox.x);
      newBox.y = Math.max(0, newBox.y);
      newBox.width = Math.min(newBox.width, 1 - newBox.x);
      newBox.height = Math.min(newBox.height, 1 - newBox.y);

      onBoxesChange(boxes.map(b => b.id === selectedBoxId ? newBox : b));
    }
  }, [readOnly, isDrawing, isDragging, isResizing, selectedBoxId, boxes, dragOffset, resizeHandle, getMousePosFromClient, toNormalized, onBoxesChange]);

  // 鼠标释放
  const handleMouseUp = useCallback(() => {
    if (readOnly) return;
    if (isDrawing) {
      const x1 = toNormalized(Math.min(drawStart.x, drawCurrent.x), 'x');
      const y1 = toNormalized(Math.min(drawStart.y, drawCurrent.y), 'y');
      const x2 = toNormalized(Math.max(drawStart.x, drawCurrent.x), 'x');
      const y2 = toNormalized(Math.max(drawStart.y, drawCurrent.y), 'y');
      
      const width = x2 - x1;
      const height = y2 - y1;

      // 只有足够大的框才创建
      if (width > 0.01 && height > 0.01) {
        const newBox: BoundingBox = {
          id: `manual_${Date.now()}`,
          x: x1,
          y: y1,
          width,
          height,
          type: 'CUSTOM',
          text: '自定义',
          selected: true,
          confidence: 1.0,
          source: 'manual',
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

    setIsDrawing(false);
    setIsDragging(false);
    setIsResizing(false);
    setResizeHandle(null);
    editStartBoxesRef.current = null;
  }, [readOnly, isDrawing, isDragging, isResizing, drawStart, drawCurrent, boxes, toNormalized, onBoxesChange, onBoxesCommit]);

  // Touch event handlers
  const handleTouchStart = useCallback((e: React.TouchEvent) => {
    if (readOnly || !drawMode) return;
    e.preventDefault();
    editStartBoxesRef.current = boxes;
    const touch = e.touches[0];
    const pos = getMousePosFromClient(touch.clientX, touch.clientY);
    setDrawStart(pos);
    setDrawCurrent(pos);
    setIsDrawing(true);
    setSelectedBoxId(null);
  }, [readOnly, drawMode, getMousePosFromClient, boxes]);

  const handleBoxTouchStart = useCallback((e: React.TouchEvent, boxId: string, handle?: ResizeHandle) => {
    if (readOnly) return;
    e.preventDefault();
    e.stopPropagation();
    setSelectedBoxId(boxId);
    editStartBoxesRef.current = boxes;

    const touch = e.touches[0];
    const pos = getMousePosFromClient(touch.clientX, touch.clientY);
    const box = boxes.find(b => b.id === boxId);
    if (!box) return;

    if (handle) {
      setIsResizing(true);
      setResizeHandle(handle);
    } else {
      setIsDragging(true);
      setDragOffset({
        x: pos.x - toPixel(box.x, 'x'),
        y: pos.y - toPixel(box.y, 'y'),
      });
    }
  }, [readOnly, boxes, getMousePosFromClient, toPixel]);

  const handleTouchMove = useCallback((e: TouchEvent | React.TouchEvent) => {
    if (readOnly) return;
    const touch = ('touches' in e) ? e.touches[0] : (e as React.TouchEvent).touches[0];
    if (!touch) return;
    const pos = getMousePosFromClient(touch.clientX, touch.clientY);

    if (isDrawing) {
      setDrawCurrent(pos);
      return;
    }

    if (!selectedBoxId) return;
    const box = boxes.find(b => b.id === selectedBoxId);
    if (!box) return;

    if (isDragging) {
      const newX = toNormalized(pos.x - dragOffset.x, 'x');
      const newY = toNormalized(pos.y - dragOffset.y, 'y');
      const clampedX = Math.max(0, Math.min(newX, 1 - box.width));
      const clampedY = Math.max(0, Math.min(newY, 1 - box.height));
      onBoxesChange(boxes.map(b =>
        b.id === selectedBoxId ? { ...b, x: clampedX, y: clampedY } : b
      ));
    } else if (isResizing && resizeHandle) {
      const normX = toNormalized(pos.x, 'x');
      const normY = toNormalized(pos.y, 'y');
      let newBox = { ...box };
      const minSize = 0.01;
      switch (resizeHandle) {
        case 'nw': newBox.width = Math.max(minSize, box.x + box.width - normX); newBox.height = Math.max(minSize, box.y + box.height - normY); newBox.x = Math.min(normX, box.x + box.width - minSize); newBox.y = Math.min(normY, box.y + box.height - minSize); break;
        case 'n': newBox.height = Math.max(minSize, box.y + box.height - normY); newBox.y = Math.min(normY, box.y + box.height - minSize); break;
        case 'ne': newBox.width = Math.max(minSize, normX - box.x); newBox.height = Math.max(minSize, box.y + box.height - normY); newBox.y = Math.min(normY, box.y + box.height - minSize); break;
        case 'e': newBox.width = Math.max(minSize, normX - box.x); break;
        case 'se': newBox.width = Math.max(minSize, normX - box.x); newBox.height = Math.max(minSize, normY - box.y); break;
        case 's': newBox.height = Math.max(minSize, normY - box.y); break;
        case 'sw': newBox.width = Math.max(minSize, box.x + box.width - normX); newBox.height = Math.max(minSize, normY - box.y); newBox.x = Math.min(normX, box.x + box.width - minSize); break;
        case 'w': newBox.width = Math.max(minSize, box.x + box.width - normX); newBox.x = Math.min(normX, box.x + box.width - minSize); break;
      }
      newBox.x = Math.max(0, newBox.x);
      newBox.y = Math.max(0, newBox.y);
      newBox.width = Math.min(newBox.width, 1 - newBox.x);
      newBox.height = Math.min(newBox.height, 1 - newBox.y);
      onBoxesChange(boxes.map(b => b.id === selectedBoxId ? newBox : b));
    }
  }, [readOnly, isDrawing, isDragging, isResizing, selectedBoxId, boxes, dragOffset, resizeHandle, getMousePosFromClient, toNormalized, onBoxesChange]);

  // 拖拽/缩放/拉框时指针移出图片区域仍跟踪（避免被父级 overflow 截断）
  useEffect(() => {
    if (readOnly) return;
    if (!isDragging && !isResizing && !isDrawing) return;
    const onMove = (e: MouseEvent) => {
      handleMouseMove(e);
    };
    const onTouchMove = (e: TouchEvent) => {
      e.preventDefault();
      handleTouchMove(e);
    };
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

  // 删除选中的框
  const handleDelete = useCallback(() => {
    if (readOnly) return;
    if (selectedBoxId) {
      const nextBoxes = boxes.filter(b => b.id !== selectedBoxId);
      onBoxesChange(nextBoxes);
      onBoxesCommit?.(boxes, nextBoxes);
      setSelectedBoxId(null);
    }
  }, [readOnly, selectedBoxId, boxes, onBoxesChange, onBoxesCommit]);

  // 键盘事件
  useEffect(() => {
    if (readOnly) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Delete' || e.key === 'Backspace') {
        handleDelete();
      } else if (e.key === 'Escape') {
        setSelectedBoxId(null);
        setDrawMode(false);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [readOnly, handleDelete]);

  // 渲染调整手柄
  const renderResizeHandles = (box: BoundingBox) => {
    const handleSize = 8;
    const handleLabels: Record<string, string> = {
      nw: '向左上调整大小',
      n: '向上调整大小',
      ne: '向右上调整大小',
      e: '向右调整大小',
      se: '向右下调整大小',
      s: '向下调整大小',
      sw: '向左下调整大小',
      w: '向左调整大小',
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
        aria-label={handleLabels[pos!] || '调整大小'}
        className="absolute bg-white border border-slate-400 rounded-sm shadow-sm"
        style={{
          width: handleSize,
          height: handleSize,
          ...style,
        }}
        onMouseDown={(e) => handleBoxMouseDown(e, box.id, pos)}
        onTouchStart={(e) => handleBoxTouchStart(e, box.id, pos)}
      />
    ));
  };

  // 绘制中的预览框
  const drawingBox = isDrawing ? {
    left: Math.min(drawStart.x, drawCurrent.x),
    top: Math.min(drawStart.y, drawCurrent.y),
    width: Math.abs(drawCurrent.x - drawStart.x),
    height: Math.abs(drawCurrent.y - drawStart.y),
  } : null;

  /** 只读对比：与 Playground 右侧「纯 img + object-contain」同一套缩放，框用百分比叠在图上，避免 fitScale 像素取整与视口测量导致裁切、显大 */
  const renderBoxes = (percentCoords: boolean) =>
    boxes.map(box => {
      const config = getTypeConfig(box.type);
      const isSelected = box.id === selectedBoxId;
      const stroke = isSelected ? BOX_STROKE_SELECTED : BOX_STROKE;
      const sourceCls =
        box.source === 'ocr_has'
          ? 'bg-blue-100/95 text-blue-800 border-blue-200/80'
          : box.source === 'has_image'
            ? 'bg-violet-100/95 text-violet-800 border-violet-200/80'
            : 'bg-emerald-100/95 text-emerald-800 border-emerald-200/80';

      const posStyle: React.CSSProperties = percentCoords
        ? {
            left: `${box.x * 100}%`,
            top: `${box.y * 100}%`,
            width: `${box.width * 100}%`,
            height: `${box.height * 100}%`,
          }
        : {
            left: toPixel(box.x, 'x'),
            top: toPixel(box.y, 'y'),
            width: toPixel(box.width, 'x'),
            height: toPixel(box.height, 'y'),
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
              {box.source === 'ocr_has' ? 'OCR' : box.source === 'has_image' ? '图像' : '手动'}
            </span>
            <span className="text-[9px] leading-tight font-normal truncate opacity-90">
              {config.name}
              {box.text ? ` · ${box.text.slice(0, 14)}${box.text.length > 14 ? '…' : ''}` : ''}
            </span>
          </div>

          {isSelected && !drawMode && !readOnly && renderResizeHandles(box)}

          {!box.selected && (
            <div className="absolute inset-0 flex items-center justify-center bg-black/20">
              <span className="text-white text-[10px] font-medium drop-shadow-sm">已取消</span>
            </div>
          )}
        </div>
      );
    });

  return (
    <div className="flex flex-col h-full min-h-0">
      {/* 工具栏（脱敏结果对比 / 只读模式不展示） */}
      {!readOnly && (
      <div className="flex flex-wrap items-center gap-1.5 px-2 py-1.5 flex-shrink-0 border-b border-gray-100/80 dark:border-gray-700 bg-white/90 dark:bg-gray-800/90">
        <button
          onClick={() => setDrawMode(!drawMode)}
          className={`px-3 py-1.5 text-xs font-medium rounded-lg flex items-center gap-1.5 transition-colors ${
            drawMode 
              ? 'bg-gray-900 text-white' 
              : 'bg-surface-tertiary text-gray-700 hover:bg-neutral-200'
          }`}
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
          </svg>
          {drawMode ? '绘制模式 (ESC退出)' : '拉框标注'}
        </button>

        {selectedBoxId && (
          <button
            onClick={handleDelete}
            className="px-3 py-1.5 text-xs font-medium rounded-lg bg-violet-50 text-violet-700 hover:bg-violet-100 flex items-center gap-1.5"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
            </svg>
            删除选中 (Del)
          </button>
        )}

        <div className="flex items-center gap-1.5">
          <span className="text-xs text-ink-muted">缩放 {Math.round(zoom * 100)}%</span>
          <button
            onClick={() => setZoom(z => Math.max(ZOOM_MIN, +(z - ZOOM_STEP).toFixed(2)))}
            className="px-2 py-1 text-xs rounded border border-line text-ink-muted hover:border-gray-300"
            aria-label="缩小"
          >
            -
          </button>
          <button
            onClick={() => setZoom(z => Math.min(ZOOM_MAX, +(z + ZOOM_STEP).toFixed(2)))}
            className="px-2 py-1 text-xs rounded border border-line text-ink-muted hover:border-gray-300"
            aria-label="放大"
          >
            +
          </button>
          <button
            type="button"
            onClick={() => setZoom(1)}
            className="px-2 py-1 text-xs rounded border border-line text-ink-muted hover:border-gray-300"
            title="恢复为适应窗口大小"
          >
            适应
          </button>
        </div>

        <div className="ml-auto hidden sm:block text-[10px] text-ink-muted truncate max-w-[min(100%,14rem)]">
          {boxes.length} 区域
        </div>
      </div>
      )}

      {/* 图片区：按视口适应缩放 + 用户 zoom；插槽浮在视口上 */}
      <div
        ref={viewportRef}
        className={`relative flex-1 w-full min-h-0 ${readOnly ? 'overflow-hidden' : 'overflow-auto'} flex items-center justify-center bg-[#f0f0f2] dark:bg-gray-900 ${
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
            className="relative shrink-0 leading-none"
            style={
              naturalSize.width > 0 && naturalSize.height > 0
                ? (() => {
                    // Compute fitted size so img box === visible pixels (no object-contain gap)
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
            aria-label="图像标注区域，可拖拽框选敏感区域"
            tabIndex={0}
            className={`relative inline-block shrink-0 ${drawMode ? 'cursor-crosshair' : 'cursor-default'}`}
            style={{
              width: displayW > 0 ? displayW : undefined,
              height: displayH > 0 ? displayH : undefined,
              touchAction: 'none',
            }}
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
                className="absolute border border-dashed border-slate-400 bg-slate-400/8 pointer-events-none"
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
    </div>
  );
};

export default ImageBBoxEditor;
