import React, { useState, useRef, useEffect, useCallback } from 'react';

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
  source?: 'ocr_has' | 'glm_vision' | 'manual';  // 来源 Pipeline
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
}

type ResizeHandle = 'nw' | 'n' | 'ne' | 'e' | 'se' | 's' | 'sw' | 'w' | null;

const ImageBBoxEditor: React.FC<ImageBBoxEditorProps> = ({
  imageSrc,
  boxes,
  onBoxesChange,
  onBoxesCommit,
  getTypeConfig,
  availableTypes = [],
  defaultType = 'CUSTOM',
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const imageRef = useRef<HTMLImageElement>(null);
  const [imageSize, setImageSize] = useState({ width: 0, height: 0 });
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
  const [selectedDrawType, setSelectedDrawType] = useState(defaultType);
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [isPanning, setIsPanning] = useState(false);
  const [panStart, setPanStart] = useState({ x: 0, y: 0 });
  const lastBoxesRef = useRef<BoundingBox[]>(boxes);
  const editStartBoxesRef = useRef<BoundingBox[] | null>(null);
  const ZOOM_MIN = 0.5;
  const ZOOM_MAX = 5;
  const ZOOM_STEP = 0.1;

  // 加载图片尺寸
  const handleImageLoad = useCallback(() => {
    if (imageRef.current) {
      setImageSize({
        width: imageRef.current.naturalWidth,
        height: imageRef.current.naturalHeight,
      });
      setDisplaySize({
        width: imageRef.current.clientWidth,
        height: imageRef.current.clientHeight,
      });
    }
  }, []);

  // 监听窗口大小变化
  useEffect(() => {
    const handleResize = () => {
      if (imageRef.current) {
        setDisplaySize({
          width: imageRef.current.clientWidth,
          height: imageRef.current.clientHeight,
        });
      }
    };
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

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

  // 获取鼠标相对于图片的位置
  const getMousePos = useCallback((e: React.MouseEvent) => {
    if (!imageRef.current) return { x: 0, y: 0 };
    const rect = imageRef.current.getBoundingClientRect();
    const scale = zoom || 1;
    return {
      x: Math.max(0, Math.min((e.clientX - rect.left) / scale, displaySize.width)),
      y: Math.max(0, Math.min((e.clientY - rect.top) / scale, displaySize.height)),
    };
  }, [displaySize, zoom]);

  // 开始绘制新框或拖动画布
  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    if (drawMode) {
      editStartBoxesRef.current = boxes;
      const pos = getMousePos(e);
      setDrawStart(pos);
      setDrawCurrent(pos);
      setIsDrawing(true);
      setSelectedBoxId(null);
    } else {
      setIsPanning(true);
      setPanStart({ x: e.clientX, y: e.clientY });
    }
  }, [drawMode, getMousePos, boxes]);

  // 开始拖拽或调整大小
  const handleBoxMouseDown = useCallback((e: React.MouseEvent, boxId: string, handle?: ResizeHandle) => {
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
  }, [boxes, getMousePos, toPixel]);

  // 鼠标移动
  const handleMouseMove = useCallback((e: React.MouseEvent) => {
    if (isPanning) {
      const dx = e.clientX - panStart.x;
      const dy = e.clientY - panStart.y;
      setPan(prev => ({ x: prev.x + dx, y: prev.y + dy }));
      setPanStart({ x: e.clientX, y: e.clientY });
      return;
    }

    const pos = getMousePos(e);

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
    // 鼠标移动依赖更新
  }, [isDrawing, isDragging, isResizing, isPanning, selectedBoxId, boxes, dragOffset, resizeHandle, getMousePos, toNormalized, onBoxesChange, panStart]);

  // 鼠标释放
  const handleMouseUp = useCallback(() => {
    if (isPanning) {
      setIsPanning(false);
      return;
    }

    if (isDrawing) {
      const x1 = toNormalized(Math.min(drawStart.x, drawCurrent.x), 'x');
      const y1 = toNormalized(Math.min(drawStart.y, drawCurrent.y), 'y');
      const x2 = toNormalized(Math.max(drawStart.x, drawCurrent.x), 'x');
      const y2 = toNormalized(Math.max(drawStart.y, drawCurrent.y), 'y');

      const width = x2 - x1;
      const height = y2 - y1;

      // 只有足够大的框才创建
      if (width > 0.01 && height > 0.01) {
        const typeConfig = availableTypes.find(t => t.id === selectedDrawType);
        const newBox: BoundingBox = {
          id: `manual_${Date.now()}`,
          x: x1,
          y: y1,
          width,
          height,
          type: selectedDrawType,
          text: typeConfig?.name || '手动标注',
          selected: true,
          confidence: 1.0,
          source: 'manual',  // 手动标注
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
  }, [isDrawing, isDragging, isResizing, drawStart, drawCurrent, boxes, availableTypes, selectedDrawType, toNormalized, onBoxesChange, onBoxesCommit]);

  // 删除选中的框
  const handleDelete = useCallback(() => {
    if (selectedBoxId) {
      const nextBoxes = boxes.filter(b => b.id !== selectedBoxId);
      onBoxesChange(nextBoxes);
      onBoxesCommit?.(boxes, nextBoxes);
      setSelectedBoxId(null);
    }
  }, [selectedBoxId, boxes, onBoxesChange, onBoxesCommit]);

  // 键盘事件
  useEffect(() => {
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
  }, [handleDelete]);

  // 渲染调整手柄
  const renderResizeHandles = (box: BoundingBox) => {
    const handleSize = 8;
    const handles: { pos: ResizeHandle; style: React.CSSProperties }[] = [
      { pos: 'nw', style: { left: -handleSize / 2, top: -handleSize / 2, cursor: 'nwse-resize' } },
      { pos: 'n', style: { left: '50%', marginLeft: -handleSize / 2, top: -handleSize / 2, cursor: 'ns-resize' } },
      { pos: 'ne', style: { right: -handleSize / 2, top: -handleSize / 2, cursor: 'nesw-resize' } },
      { pos: 'e', style: { right: -handleSize / 2, top: '50%', marginTop: -handleSize / 2, cursor: 'ew-resize' } },
      { pos: 'se', style: { right: -handleSize / 2, bottom: -handleSize / 2, cursor: 'nwse-resize' } },
      { pos: 's', style: { left: '50%', marginLeft: -handleSize / 2, bottom: -handleSize / 2, cursor: 'ns-resize' } },
      { pos: 'sw', style: { left: -handleSize / 2, bottom: -handleSize / 2, cursor: 'nesw-resize' } },
      { pos: 'w', style: { left: -handleSize / 2, top: '50%', marginTop: -handleSize / 2, cursor: 'ew-resize' } },
    ];

    return handles.map(({ pos, style }) => (
      <div
        key={pos}
        className="absolute bg-white border-2 border-blue-500 rounded-sm"
        style={{
          width: handleSize,
          height: handleSize,
          ...style,
        }}
        onMouseDown={(e) => handleBoxMouseDown(e, box.id, pos)}
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

  return (
    <div className="flex flex-col h-full">
      {/* 工具栏 */}
      <div className="flex items-center gap-2 px-2 py-2 flex-shrink-0">
        <button
          onClick={() => setDrawMode(!drawMode)}
          className={`px-3 py-1.5 text-xs font-medium rounded-lg flex items-center gap-1.5 transition-colors ${drawMode
              ? 'bg-blue-500 text-white'
              : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
            }`}
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
          </svg>
          {drawMode ? '绘制模式 (ESC退出)' : '拉框标注'}
        </button>

        {/* 类型选择器 */}
        {availableTypes.length > 0 && (
          <div className="flex items-center gap-1.5">
            <span className="text-xs text-gray-500">标注类型:</span>
            <select
              value={selectedDrawType}
              onChange={(e) => setSelectedDrawType(e.target.value)}
              className="text-xs border border-gray-200 rounded-lg px-2 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-blue-500"
              style={{
                borderLeftColor: availableTypes.find(t => t.id === selectedDrawType)?.color || '#6B7280',
                borderLeftWidth: 3,
              }}
            >
              {availableTypes.map(type => (
                <option key={type.id} value={type.id}>
                  {type.name}
                </option>
              ))}
            </select>
          </div>
        )}

        {selectedBoxId && (
          <button
            onClick={handleDelete}
            className="px-3 py-1.5 text-xs font-medium rounded-lg bg-red-50 text-red-600 hover:bg-red-100 flex items-center gap-1.5"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
            </svg>
            删除选中 (Del)
          </button>
        )}

        <div className="flex items-center gap-1.5">
          <span className="text-xs text-gray-500">缩放 {Math.round(zoom * 100)}%</span>
          <button
            onClick={() => setZoom(z => Math.max(ZOOM_MIN, +(z - ZOOM_STEP).toFixed(2)))}
            className="px-2 py-1 text-xs rounded border border-gray-200 text-gray-600 hover:border-gray-300"
          >
            -
          </button>
          <button
            onClick={() => setZoom(z => Math.min(ZOOM_MAX, +(z + ZOOM_STEP).toFixed(2)))}
            className="px-2 py-1 text-xs rounded border border-gray-200 text-gray-600 hover:border-gray-300"
          >
            +
          </button>
          <button
            onClick={() => {
              setZoom(1);
              setPan({ x: 0, y: 0 });
            }}
            className="px-2 py-1 text-xs rounded border border-gray-200 text-gray-600 hover:border-gray-300"
          >
            重置
          </button>
        </div>

        <div className="ml-auto text-xs text-gray-500">
          {boxes.length} 个区域 | 点击选中，拖拽移动，拖拽角落调整大小
        </div>
      </div>

      {/* 图片编辑区 - 占满整个可用空间 */}
      <div
        className="flex-1 w-full overflow-hidden flex items-center justify-center relative cursor-move bg-[#e5e5ea]"
        style={{ minHeight: 0 }}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
      >
        {/* 实际用来承载图片和框的层级，带上缩放和平移变形 */}
        <div
          ref={containerRef}
          className={`absolute ${drawMode ? 'cursor-crosshair' : isPanning ? 'cursor-grabbing' : 'cursor-grab'}`}
          style={{
            transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`,
            transformOrigin: '0 0' // 改为左上角方便纯平移计算
          }}
        >
          <img
            ref={imageRef}
            src={imageSrc}
            alt="edit"
            className="select-none max-w-full max-h-full"
            onLoad={handleImageLoad}
            draggable={false}
          />

          {/* 渲染所有 bounding boxes */}
          {boxes.map(box => {
            const config = getTypeConfig(box.type);
            const isSelected = box.id === selectedBoxId;

            return (
              <div
                key={box.id}
                className={`absolute transition-shadow ${isSelected ? 'z-10' : 'z-0'}`}
                style={{
                  left: toPixel(box.x, 'x'),
                  top: toPixel(box.y, 'y'),
                  width: toPixel(box.width, 'x'),
                  height: toPixel(box.height, 'y'),
                  border: `2px solid ${config.color}`,
                  backgroundColor: box.selected ? `${config.color}20` : 'transparent',
                  boxShadow: isSelected ? `0 0 0 2px ${config.color}` : 'none',
                  cursor: drawMode ? 'crosshair' : 'move',
                }}
                onMouseDown={(e) => !drawMode && handleBoxMouseDown(e, box.id)}
                onClick={(e) => e.stopPropagation()}
              >
                {/* 标签 - 显示来源 */}
                <div
                  className="absolute -top-5 left-0 px-1 py-0.5 text-[10px] text-white rounded-t whitespace-nowrap flex items-center gap-1"
                  style={{ backgroundColor: config.color }}
                >
                  <span className={`px-1 rounded text-[8px] font-bold ${box.source === 'ocr_has' ? 'bg-blue-800' :
                      box.source === 'glm_vision' ? 'bg-purple-800' : 'bg-gray-600'
                    }`}>
                    {box.source === 'ocr_has' ? 'OCR' : box.source === 'glm_vision' ? 'VLM' : '手动'}
                  </span>
                  {config.name} {box.text && `| ${box.text.slice(0, 10)}${box.text.length > 10 ? '...' : ''}`}
                </div>

                {/* 选中状态的调整手柄 */}
                {isSelected && !drawMode && renderResizeHandles(box)}

                {/* 未选中指示器 */}
                {!box.selected && (
                  <div className="absolute inset-0 flex items-center justify-center bg-black/30">
                    <span className="text-white text-xs">已取消</span>
                  </div>
                )}
              </div>
            );
          })}

          {/* 绘制中的预览框 */}
          {drawingBox && drawingBox.width > 5 && drawingBox.height > 5 && (
            <div
              className="absolute border-2 border-dashed border-blue-500 bg-blue-500/10 pointer-events-none"
              style={{
                left: drawingBox.left,
                top: drawingBox.top,
                width: drawingBox.width,
                height: drawingBox.height,
              }}
            />
          )}
        </div>
      </div>
    </div>
  );
};

export default ImageBBoxEditor;
