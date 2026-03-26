import React, { useState, useCallback, useEffect, useLayoutEffect, useRef, useMemo } from 'react';
import {
  fetchPresets,
  createPreset,
  presetAppliesText,
  presetAppliesVision,
  type RecognitionPreset,
} from '../services/presetsApi';
import {
  setActivePresetTextId,
  setActivePresetVisionId,
  getActivePresetTextId,
  getActivePresetVisionId,
} from '../services/activePresetBridge';
import { useDropzone } from 'react-dropzone';
import ImageBBoxEditor from '../components/ImageBBoxEditor';
import {
  getEntityTypeName,
  getEntityGroup,
  ENTITY_GROUPS,
  getEntityRiskConfig,
} from '../config/entityTypes';
import {
  selectableCardClassCompact,
  selectableCheckboxClass,
  textGroupKeyToVariant,
  type SelectionVariant,
} from '../ui/selectionClasses';

/** 上传/预览侧栏：紧凑气泡，减轻 16 寸屏纵向滚动 */
const pgTypeBubbleClass = (selected: boolean, variant: SelectionVariant) =>
  `${selectableCardClassCompact(selected, variant)} flex items-center gap-1 px-1.5 py-1 text-2xs leading-tight cursor-pointer min-w-0 !rounded-lg`;

/** 将弹层锚在选区附近，并限制在中间文档 Canvas（contentRef）可视区域内，避免压到侧栏或顶出视口 */
function clampPopoverInCanvas(
  anchorRect: DOMRect,
  canvasRect: DOMRect,
  popoverWidth: number,
  popoverHeight: number
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

// 类型定义
interface FileInfo {
  file_id: string;
  filename: string;
  file_size: number;
  file_type?: string;
  is_scanned?: boolean;
}

interface Entity {
  id: string;
  text: string;
  type: string;
  start: number;
  end: number;
  selected: boolean;
  source: 'regex' | 'llm' | 'manual' | 'has';
  coref_id?: string | null;
}

interface BoundingBox {
  id: string;
  x: number;
  y: number;
  width: number;
  height: number;
  page?: number;
  type: string;
  text?: string;
  selected: boolean;
  confidence?: number;
  source?: 'ocr_has' | 'has_image' | 'manual';
}

interface EntityTypeConfig {
  id: string;
  name: string;
  color: string;
  description?: string;
  regex_pattern?: string | null;
  use_llm?: boolean;
  enabled?: boolean;
}

interface VisionTypeConfig {
  id: string;
  name: string;
  color: string;
  description?: string;
  enabled?: boolean;
}

interface PipelineConfig {
  mode: 'ocr_has' | 'has_image';
  name: string;
  description: string;
  enabled: boolean;
  types: VisionTypeConfig[];
}

type Stage = 'upload' | 'preview' | 'result';

/**
 * 预览区原文高亮：与侧栏 selectableCardClassCompact（正则 / 语义 / 图像）同底色与字色，
 * 不用重色下划线，避免与侧栏标签观感脱节。
 */
function previewEntityMarkStyle(entity: Entity): React.CSSProperties {
  const base: React.CSSProperties = (() => {
    switch (entity.source) {
      case 'regex':
        return {
          backgroundColor: 'rgba(0, 122, 255, 0.09)',
          color: '#0a4a8c',
        };
      case 'llm':
        return {
          backgroundColor: 'rgba(52, 199, 89, 0.09)',
          color: '#0d5c2f',
        };
      case 'manual':
        return {
          backgroundColor: 'rgba(175, 82, 222, 0.11)',
          color: '#5c2d7a',
        };
      case 'has':
      default:
        return {
          backgroundColor: 'rgba(175, 82, 222, 0.11)',
          color: '#5c2d7a',
        };
    }
  })();
  if (!entity.selected) {
    return { ...base, opacity: 0.5, filter: 'saturate(0.55)' };
  }
  return base;
}

/** 与侧栏勾选态 hover:ring 语义一致，略弱以免抢正文 */
function previewEntityHoverRingClass(source: Entity['source']): string {
  switch (source) {
    case 'regex':
      return 'hover:ring-[#007AFF]/25';
    case 'llm':
      return 'hover:ring-[#34C759]/25';
    case 'manual':
      return 'hover:ring-[#AF52DE]/25';
    case 'has':
    default:
      return 'hover:ring-[#AF52DE]/25';
  }
}

// ============================================================
// 核心函数：执行图像识别
// ============================================================
/** 图像识别：仅勾选的路会跑；含 OCR+HaS 时常需数十秒（CPU Paddle 更久）。与 axios 默认 60s 无关，此处单独放宽 */
const VISION_FETCH_TIMEOUT_MS = 180000;

async function runVisionDetection(
  fileId: string,
  ocrHasTypes: string[],
  hasImageTypes: string[]
): Promise<{ boxes: BoundingBox[]; resultImage?: string }> {
  console.log('[Vision] 发送识别请求:', { ocrHasTypes, hasImageTypes });

  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), VISION_FETCH_TIMEOUT_MS);

  let res: Response;
  try {
    res = await fetch(`/api/v1/redaction/${fileId}/vision?page=1`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        selected_ocr_has_types: ocrHasTypes,
        selected_has_image_types: hasImageTypes,
      }),
      signal: controller.signal,
    });
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') {
      throw new Error(
        '图像识别超时（超过 3 分钟）。若 Paddle 在 CPU 上跑会很慢，可换更小图片或安装 paddle GPU 版加速。'
      );
    }
    throw e;
  } finally {
    window.clearTimeout(timer);
  }

  if (!res.ok) {
    throw new Error('图像识别失败');
  }

  const data = await res.json();
  const boxes = (data.bounding_boxes || []).map((b: any, idx: number) => ({
    ...b,
    id: b.id || `bbox_${idx}`,
    selected: true,
  }));
  return { boxes, resultImage: data.result_image };
}

export const Playground: React.FC = () => {
  const [stage, setStage] = useState<Stage>('upload');
  const [fileInfo, setFileInfo] = useState<FileInfo | null>(null);
  const [content, setContent] = useState('');
  const [entities, setEntities] = useState<Entity[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [loadingMessage, setLoadingMessage] = useState('');
  const [_redactedContent, setRedactedContent] = useState('');
  const [redactedCount, setRedactedCount] = useState(0);
  const [entityMap, setEntityMap] = useState<Record<string, string>>({});
  
  // 实体类型配置
  const [entityTypes, setEntityTypes] = useState<EntityTypeConfig[]>([]);
  const [selectedTypes, setSelectedTypes] = useState<string[]>([]);
  const [visionTypes, setVisionTypes] = useState<VisionTypeConfig[]>([]);
  
  // 两个 Pipeline 独立选择 - 使用 ref 确保最新值可用
  const [selectedOcrHasTypes, setSelectedOcrHasTypes] = useState<string[]>([]);
  const [selectedHasImageTypes, setSelectedHasImageTypes] = useState<string[]>([]);
  const selectedOcrHasTypesRef = useRef(selectedOcrHasTypes);
  const selectedHasImageTypesRef = useRef(selectedHasImageTypes);
  
  // 同步更新 ref（立即同步，不等待 useEffect）
  const updateOcrHasTypes = useCallback((types: string[]) => {
    selectedOcrHasTypesRef.current = types;
    setSelectedOcrHasTypes(types);
    localStorage.setItem('ocrHasTypes', JSON.stringify(types));
  }, []);
  
  const updateHasImageTypes = useCallback((types: string[]) => {
    selectedHasImageTypesRef.current = types;
    setSelectedHasImageTypes(types);
    // 同步保存到 localStorage，解决闭包问题
    localStorage.setItem('hasImageTypes', JSON.stringify(types));
  }, []);
  
  const [pipelines, setPipelines] = useState<PipelineConfig[]>([]);
  const [typeTab, setTypeTab] = useState<'text' | 'vision'>('text');
  const [replacementMode, setReplacementMode] = useState<'structured' | 'smart' | 'mask'>('structured');
  const [playgroundPresets, setPlaygroundPresets] = useState<RecognitionPreset[]>([]);
  const [playgroundPresetTextId, setPlaygroundPresetTextId] = useState<string | null>(null);
  const [playgroundPresetVisionId, setPlaygroundPresetVisionId] = useState<string | null>(null);

  const textPresetsPg = useMemo(() => playgroundPresets.filter(presetAppliesText), [playgroundPresets]);
  const visionPresetsPg = useMemo(() => playgroundPresets.filter(presetAppliesVision), [playgroundPresets]);

  /** 下拉「默认」：当前启用文本类型全选（与首次加载一致） */
  const playgroundDefaultTextTypeIds = useMemo(
    () => entityTypes.filter(t => t.enabled !== false).map(t => t.id),
    [entityTypes]
  );
  /** 下拉「默认」：OCR+HaS 与 HaS 图像（YOLO）均为当前启用类型全选 */
  const playgroundDefaultOcrHasTypeIds = useMemo(
    () =>
      pipelines
        .filter(pl => pl.mode === 'ocr_has' && pl.enabled)
        .flatMap(pl => pl.types.filter(t => t.enabled).map(t => t.id)),
    [pipelines]
  );
  const playgroundDefaultHasImageTypeIds = useMemo(
    () =>
      pipelines
        .filter(pl => pl.mode === 'has_image' && pl.enabled)
        .flatMap(pl => pl.types.filter(t => t.enabled).map(t => t.id)),
    [pipelines]
  );

  const clearPlaygroundTextPresetTracking = useCallback(() => {
    setPlaygroundPresetTextId(null);
    setActivePresetTextId(null);
  }, []);

  const clearPlaygroundVisionPresetTracking = useCallback(() => {
    setPlaygroundPresetVisionId(null);
    setActivePresetVisionId(null);
  }, []);

  const applyTextPresetToPlayground = useCallback(
    (p: RecognitionPreset) => {
      if (!presetAppliesText(p)) return;
      const textIds = new Set(entityTypes.filter(t => t.enabled !== false).map(t => t.id));
      setSelectedTypes(p.selectedEntityTypeIds.filter(id => textIds.has(id)));
      if ((p.kind ?? 'full') !== 'text') {
        setReplacementMode(p.replacementMode);
      }
      setPlaygroundPresetTextId(p.id);
      setActivePresetTextId(p.id);
    },
    [entityTypes]
  );

  const applyVisionPresetToPlayground = useCallback(
    (p: RecognitionPreset) => {
      if (!presetAppliesVision(p)) return;
      const ocrIds = pipelines
        .filter(pl => pl.mode === 'ocr_has' && pl.enabled)
        .flatMap(pl => pl.types.filter(t => t.enabled).map(t => t.id));
      const hiIds = pipelines
        .filter(pl => pl.mode === 'has_image' && pl.enabled)
        .flatMap(pl => pl.types.filter(t => t.enabled).map(t => t.id));
      updateOcrHasTypes(p.ocrHasTypes.filter(id => ocrIds.includes(id)));
      updateHasImageTypes(p.hasImageTypes.filter(id => hiIds.includes(id)));
      setPlaygroundPresetVisionId(p.id);
      setActivePresetVisionId(p.id);
    },
    [pipelines, updateOcrHasTypes, updateHasImageTypes]
  );

  const selectPlaygroundTextPresetById = useCallback(
    (id: string) => {
      if (!id) {
        setPlaygroundPresetTextId(null);
        setActivePresetTextId(null);
        setSelectedTypes([...playgroundDefaultTextTypeIds]);
        setReplacementMode('structured');
        return;
      }
      const p = playgroundPresets.find(x => x.id === id);
      if (p) applyTextPresetToPlayground(p);
    },
    [playgroundDefaultTextTypeIds, playgroundPresets, applyTextPresetToPlayground]
  );

  const selectPlaygroundVisionPresetById = useCallback(
    (id: string) => {
      if (!id) {
        setPlaygroundPresetVisionId(null);
        setActivePresetVisionId(null);
        updateOcrHasTypes([...playgroundDefaultOcrHasTypeIds]);
        updateHasImageTypes([...playgroundDefaultHasImageTypeIds]);
        return;
      }
      const p = playgroundPresets.find(x => x.id === id);
      if (p) applyVisionPresetToPlayground(p);
    },
    [
      playgroundDefaultOcrHasTypeIds,
      playgroundDefaultHasImageTypeIds,
      playgroundPresets,
      applyVisionPresetToPlayground,
      updateOcrHasTypes,
      updateHasImageTypes,
    ]
  );

  useEffect(() => {
    void fetchPresets()
      .then(setPlaygroundPresets)
      .catch(() => setPlaygroundPresets([]));
  }, []);

  const saveTextPresetFromPlayground = useCallback(async () => {
    const name = window.prompt('另存为文本预设：请输入名称');
    if (!name?.trim()) return;
    try {
      const created = await createPreset({
        name: name.trim(),
        kind: 'text',
        selectedEntityTypeIds: selectedTypes,
        ocrHasTypes: [],
        hasImageTypes: [],
        replacementMode: 'structured',
      });
      const list = await fetchPresets();
      setPlaygroundPresets(list);
      setPlaygroundPresetTextId(created.id);
      setActivePresetTextId(created.id);
      alert('已另存为文本预设。');
    } catch (e) {
      alert(e instanceof Error ? e.message : '保存失败');
    }
  }, [selectedTypes]);

  const saveVisionPresetFromPlayground = useCallback(async () => {
    const name = window.prompt('另存为图像预设：请输入名称');
    if (!name?.trim()) return;
    try {
      const created = await createPreset({
        name: name.trim(),
        kind: 'vision',
        selectedEntityTypeIds: [],
        ocrHasTypes: selectedOcrHasTypes,
        hasImageTypes: selectedHasImageTypes,
        replacementMode: 'structured',
      });
      const list = await fetchPresets();
      setPlaygroundPresets(list);
      setPlaygroundPresetVisionId(created.id);
      setActivePresetVisionId(created.id);
      alert('已另存为图像预设。');
    } catch (e) {
      alert(e instanceof Error ? e.message : '保存失败');
    }
  }, [selectedOcrHasTypes, selectedHasImageTypes]);

  // 划词相关
  const [selectedText, setSelectedText] = useState<{ text: string; start: number; end: number } | null>(null);
  const [selectionPos, setSelectionPos] = useState<{ left: number; top: number } | null>(null);
  const [selectedTypeId, setSelectedTypeId] = useState<string>('');
  const [selectedOverlapIds, setSelectedOverlapIds] = useState<string[]>([]);
  const contentRef = useRef<HTMLDivElement>(null);
  const textScrollRef = useRef<HTMLDivElement>(null);
  const selectionRangeRef = useRef<Range | null>(null);
  
  // 点击实体弹出确认框
  const [clickedEntity, setClickedEntity] = useState<Entity | null>(null);
  const [entityPopupPos, setEntityPopupPos] = useState<{ left: number; top: number } | null>(null);
  const imgRef = useRef<HTMLImageElement>(null);
  
  const [boundingBoxes, setBoundingBoxes] = useState<BoundingBox[]>([]);
  const [undoStack, setUndoStack] = useState<Entity[][]>([]);
  const [redoStack, setRedoStack] = useState<Entity[][]>([]);
  const [imageUndoStack, setImageUndoStack] = useState<BoundingBox[][]>([]);
  const [imageRedoStack, setImageRedoStack] = useState<BoundingBox[][]>([]);
  const [_imageRenderSize, setImageRenderSize] = useState<{ width: number; height: number }>({ width: 0, height: 0 });
  const [_imageNaturalSize, setImageNaturalSize] = useState<{ width: number; height: number }>({ width: 0, height: 0 });
  const [_resultImage, setResultImage] = useState<string | null>(null);

  // 加载实体类型配置
  useEffect(() => {
    fetchEntityTypes();
    fetchVisionTypes();
  }, []);

  // 页面获得焦点时重新获取类型列表
  useEffect(() => {
    const handleFocus = () => {
      fetchEntityTypes();
      fetchVisionTypes();
    };
    window.addEventListener('focus', handleFocus);
    return () => window.removeEventListener('focus', handleFocus);
  }, []);

  useEffect(() => {
    if (!selectedTypeId && entityTypes.length > 0) {
      setSelectedTypeId(entityTypes[0].id);
    }
  }, [entityTypes, selectedTypeId]);

  /** 与识别项配置 / 其它页同步的「当前选用预设」：数据就绪后应用一次（须在全部 useState 之后） */
  const bridgeInitRef = useRef(false);
  useEffect(() => {
    if (bridgeInitRef.current) return;
    if (!playgroundPresets.length || !entityTypes.length) return;
    const tid = getActivePresetTextId();
    if (tid) {
      const p = playgroundPresets.find(x => x.id === tid && presetAppliesText(x));
      if (p) applyTextPresetToPlayground(p);
    }
    const vid = getActivePresetVisionId();
    if (vid && pipelines.length) {
      const p = playgroundPresets.find(x => x.id === vid && presetAppliesVision(x));
      if (p) applyVisionPresetToPlayground(p);
    }
    bridgeInitRef.current = true;
  }, [
    playgroundPresets,
    entityTypes,
    pipelines,
    applyTextPresetToPlayground,
    applyVisionPresetToPlayground,
  ]);

  const fetchEntityTypes = async () => {
    try {
      const res = await fetch('/api/v1/custom-types?enabled_only=true');
      if (!res.ok) throw new Error('获取类型失败');
      const data = await res.json();
      const types = data.custom_types || [];
      setEntityTypes(types);
      setSelectedTypes(types.map((t: EntityTypeConfig) => t.id));
    } catch (err) {
      console.error('获取实体类型失败', err);
      setEntityTypes([
        { id: 'PERSON', name: '人名', color: '#3B82F6' },
        { id: 'ID_CARD', name: '身份证号', color: '#9333EA' },
        { id: 'PHONE', name: '电话号码', color: '#059669' },
        { id: 'ADDRESS', name: '地址', color: '#0284C7' },
        { id: 'BANK_CARD', name: '银行卡号', color: '#059669' },
        { id: 'CASE_NUMBER', name: '案件编号', color: '#6366F1' },
      ]);
      setSelectedTypes(['PERSON', 'ID_CARD', 'PHONE', 'ADDRESS', 'BANK_CARD', 'CASE_NUMBER']);
    }
  };

  const fetchVisionTypes = async () => {
    try {
      const res = await fetch('/api/v1/vision-pipelines');
      if (!res.ok) throw new Error('获取Pipeline配置失败');
      const data: PipelineConfig[] = await res.json();
      const normalizedPipelines = data.map(p =>
        p.mode === 'has_image'
          ? {
              ...p,
              name: 'HaS Image',
              description: '本地 YOLO11 微服务（8081），21 类隐私区域分割。',
            }
          : p
      );
      setPipelines(normalizedPipelines);
      
      const allTypes: VisionTypeConfig[] = [];
      const ocrHasTypeIds: string[] = [];
      
      normalizedPipelines.forEach(pipeline => {
        if (pipeline.enabled) {
          pipeline.types.forEach(t => {
            if (t.enabled) {
              allTypes.push(t);
              if (pipeline.mode === 'ocr_has') {
                ocrHasTypeIds.push(t.id);
              }
            }
          });
        }
      });
      
      setVisionTypes(allTypes);
      const savedOcrHasTypes = localStorage.getItem('ocrHasTypes');
      if (savedOcrHasTypes) {
        try {
          const parsed = JSON.parse(savedOcrHasTypes);
          const filtered = Array.isArray(parsed)
            ? parsed.filter((id: string) => ocrHasTypeIds.includes(id))
            : [];
          // [] 表示用户显式不跑 OCR+HaS（仅 HaS 图像等场景），不得回退成全选
          updateOcrHasTypes(filtered);
        } catch {
          updateOcrHasTypes(ocrHasTypeIds);
        }
      } else {
        updateOcrHasTypes(ocrHasTypeIds);
      }
      const hasImageTypeIds = normalizedPipelines
        .filter(p => p.mode === 'has_image' && p.enabled)
        .flatMap(p => p.types.filter(t => t.enabled).map(t => t.id));
      const savedHasImageTypes =
        localStorage.getItem('hasImageTypes') || localStorage.getItem('glmVisionTypes');
      if (savedHasImageTypes) {
        try {
          const parsed = JSON.parse(savedHasImageTypes);
          updateHasImageTypes(parsed.filter((id: string) => hasImageTypeIds.includes(id)));
        } catch {
          updateHasImageTypes(hasImageTypeIds);
        }
      } else {
        updateHasImageTypes(hasImageTypeIds);
      }
    } catch (err) {
      console.error('获取图像类型失败', err);
      setVisionTypes([
        { id: 'PERSON', name: '人名/签名', color: '#3B82F6' },
        { id: 'ID_CARD', name: '身份证号', color: '#9333EA' },
        { id: 'PHONE', name: '电话号码', color: '#059669' },
      ]);
      updateOcrHasTypes(['PERSON', 'ID_CARD', 'PHONE']);
      updateHasImageTypes([]);
    }
  };

  const sortedEntityTypes = useMemo(
    () =>
      [...entityTypes].sort((a, b) => {
        const aRegex = a.regex_pattern ? 1 : 0;
        const bRegex = b.regex_pattern ? 1 : 0;
        if (aRegex !== bRegex) return bRegex - aRegex;
        return a.name.localeCompare(b.name);
      }),
    [entityTypes]
  );

  /** 文本 tab：正则 / 语义 / 其他；同一类型可同时属于正则与语义，会在两组中各出现一行 */
  const playgroundTextGroups = useMemo(() => {
    const regex = sortedEntityTypes.filter(t => !!t.regex_pattern);
    const llm = sortedEntityTypes.filter(t => t.use_llm);
    const other = sortedEntityTypes.filter(t => !t.regex_pattern && !t.use_llm);
    return [
      { key: 'regex' as const, label: '正则识别', types: regex },
      { key: 'llm' as const, label: '语义识别', types: llm },
      { key: 'other' as const, label: '其他', types: other },
    ].filter(g => g.types.length > 0);
  }, [sortedEntityTypes]);

  const setPlaygroundTextTypeGroupSelection = useCallback(
    (ids: string[], turnOn: boolean) => {
      clearPlaygroundTextPresetTracking();
      setSelectedTypes(prev => {
        if (turnOn) {
          const next = new Set(prev);
          ids.forEach(id => next.add(id));
          return [...next];
        }
        return prev.filter(id => !ids.includes(id));
      });
    },
    [clearPlaygroundTextPresetTracking]
  );

  const getTypeConfig = (typeId: string): { name: string; color: string } => {
    const config = entityTypes.find(t => t.id === typeId);
    return config || { name: typeId, color: '#6366F1' };
  };

  const getVisionTypeConfig = (typeId: string): { name: string; color: string } => {
    const config = visionTypes.find(t => t.id === typeId);
    return config || { name: typeId, color: '#6366F1' };
  };

  // 切换类型选择
  const toggleVisionType = (typeId: string, pipelineMode: 'ocr_has' | 'has_image') => {
    clearPlaygroundVisionPresetTracking();
    if (pipelineMode === 'ocr_has') {
      const isActive = selectedOcrHasTypes.includes(typeId);
      const next = isActive 
        ? selectedOcrHasTypes.filter(t => t !== typeId) 
        : [...selectedOcrHasTypes, typeId];
      updateOcrHasTypes(next);
      setBoundingBoxes(boxes =>
        boxes.map(b => b.type === typeId ? { ...b, selected: !isActive } : b)
      );
    } else {
      const isActive = selectedHasImageTypes.includes(typeId);
      const next = isActive 
        ? selectedHasImageTypes.filter(t => t !== typeId) 
        : [...selectedHasImageTypes, typeId];
      updateHasImageTypes(next);
      setBoundingBoxes(boxes =>
        boxes.map(b => b.type === typeId ? { ...b, selected: !isActive } : b)
      );
    }
  };

  const applyEntities = (next: Entity[]) => {
    setUndoStack(prev => [...prev, entities]);
    setRedoStack([]);
    setEntities(next);
  };

  const undo = () => {
    setUndoStack(prev => {
      if (prev.length === 0) return prev;
      const nextPrev = [...prev];
      const last = nextPrev.pop()!;
      setRedoStack(r => [...r, entities]);
      setEntities(last);
      return nextPrev;
    });
  };

  const redo = () => {
    setRedoStack(prev => {
      if (prev.length === 0) return prev;
      const nextPrev = [...prev];
      const last = nextPrev.pop()!;
      setUndoStack(u => [...u, entities]);
      setEntities(last);
      return nextPrev;
    });
  };

  const resetImageHistory = useCallback(() => {
    setImageUndoStack([]);
    setImageRedoStack([]);
  }, []);

  const undoImage = useCallback(() => {
    setImageUndoStack(prev => {
      if (prev.length === 0) return prev;
      const nextPrev = [...prev];
      const last = nextPrev.pop()!;
      setImageRedoStack(r => [...r, boundingBoxes]);
      setBoundingBoxes(last);
      return nextPrev;
    });
  }, [boundingBoxes]);

  const redoImage = useCallback(() => {
    setImageRedoStack(prev => {
      if (prev.length === 0) return prev;
      const nextPrev = [...prev];
      const last = nextPrev.pop()!;
      setImageUndoStack(u => [...u, boundingBoxes]);
      setBoundingBoxes(last);
      return nextPrev;
    });
  }, [boundingBoxes]);

  // Toast
  const showToast = (message: string, type: 'success' | 'error' | 'info' = 'info') => {
    const colors = {
      success: 'bg-emerald-600',
      error: 'bg-violet-600',
      info: 'bg-blue-600',
    };
    const toast = document.createElement('div');
    toast.className = `fixed bottom-5 right-5 px-4 py-2.5 rounded-lg ${colors[type]} text-white text-sm font-medium shadow-lg z-50 transition-opacity`;
    toast.textContent = message;
    document.body.appendChild(toast);
    setTimeout(() => {
      toast.style.opacity = '0';
      setTimeout(() => toast.remove(), 200);
    }, 2500);
  };

  // ============================================================
  // 文件上传处理 - 只负责上传和解析，不触发识别
  // ============================================================
  
  // 待处理的文件信息（上传解析完成后设置，触发 useEffect 进行识别）
  const [pendingFile, setPendingFile] = useState<{
    fileId: string;
    fileType: string;
    isScanned: boolean;
    content: string;
  } | null>(null);
  
  const handleFileDrop = async (acceptedFiles: File[]) => {
    if (acceptedFiles.length === 0) return;
    const file = acceptedFiles[0];
    setIsLoading(true);
    
    try {
      // 1. 上传文件
      setLoadingMessage('正在上传文件...');
      const formData = new FormData();
      formData.append('file', file);
      
      const uploadRes = await fetch('/api/v1/files/upload', { method: 'POST', body: formData });
      if (!uploadRes.ok) throw new Error('文件上传失败');
      const uploadData = await uploadRes.json();
      
      const newFileInfo = {
        file_id: uploadData.file_id,
        filename: uploadData.filename,
        file_size: uploadData.file_size,
        file_type: uploadData.file_type,
      };
      
      // 2. 解析文件
      setLoadingMessage('正在解析文件...');
      const parseRes = await fetch(`/api/v1/files/${uploadData.file_id}/parse`);
      if (!parseRes.ok) throw new Error('文件解析失败');
      const parseData = await parseRes.json();
      
      const isScanned = parseData.is_scanned || false;
      const parsedContent = parseData.content || '';
      
      // 更新状态
      setFileInfo({ ...newFileInfo, is_scanned: isScanned });
      setContent(parsedContent);
      setBoundingBoxes([]);
      resetImageHistory();
      setEntities([]);
      
      // 3. 设置待处理文件，触发 useEffect 进行识别
      // useEffect 中可以直接读取最新的 state
      setPendingFile({
        fileId: uploadData.file_id,
        fileType: uploadData.file_type,
        isScanned,
        content: parsedContent,
      });
      
    } catch (err) {
      showToast(err instanceof Error ? err.message : '处理失败', 'error');
      setIsLoading(false);
      setLoadingMessage('');
    }
    // 注意：isLoading 和 loadingMessage 在 useEffect 中清理
  };
  
  // ============================================================
  // 文件上传后自动识别 - 使用 useEffect 确保读取最新的 state
  // 关键：只依赖 pendingFile，但使用 ref 读取最新的类型选择
  // ============================================================
  
  // 使用 ref 存储最新的类型选择，避免 useEffect 依赖问题
  const latestOcrHasTypesRef = useRef(selectedOcrHasTypes);
  const latestHasImageTypesRef = useRef(selectedHasImageTypes);
  const latestSelectedTypesRef = useRef(selectedTypes);
  
  // 每次 state 变化时同步更新 ref
  latestOcrHasTypesRef.current = selectedOcrHasTypes;
  latestHasImageTypesRef.current = selectedHasImageTypes;
  latestSelectedTypesRef.current = selectedTypes;
  
  useEffect(() => {
    if (!pendingFile) return;
    
    const { fileId, fileType, isScanned, content } = pendingFile;
    
    // 立即清除 pendingFile，防止重复触发
    setPendingFile(null);
    
    const doRecognition = async () => {
      try {
        const isImage = fileType === 'image' || isScanned;
        
        if (isImage) {
          const ocrTypes = latestOcrHasTypesRef.current;
          const hiTypes = latestHasImageTypesRef.current;
          const vLabel =
            ocrTypes.length > 0 && hiTypes.length > 0
              ? '正在进行图像识别（OCR+HaS 与 HaS Image 并行）...'
              : ocrTypes.length > 0
                ? '正在进行图像识别（OCR+HaS）...'
                : hiTypes.length > 0
                  ? '正在进行图像识别（HaS Image）...'
                  : '正在进行图像识别...';
          setLoadingMessage(vLabel);

          console.log('[Recognition] 图像模式，开始识别');
          console.log('[Recognition] OCR+HaS 类型:', ocrTypes);
          console.log('[Recognition] HaS Image 类型:', hiTypes);
          
          const result = await runVisionDetection(fileId, ocrTypes, hiTypes);
          
          setBoundingBoxes(result.boxes);
          resetImageHistory();
          if (result.resultImage) {
            setResultImage(result.resultImage);
          }
          showToast(`识别到 ${result.boxes.length} 个敏感区域`, 'success');
        } else if (content) {
          setLoadingMessage('AI正在识别敏感信息...');
          const nerRes = await fetch(`/api/v1/files/${fileId}/ner/hybrid`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ entity_type_ids: latestSelectedTypesRef.current }),
          });
          
          if (nerRes.ok) {
            const nerData = await nerRes.json();
            const entitiesWithSource = (nerData.entities || []).map((e: any, idx: number) => ({
              ...e,
              id: e.id || `entity_${idx}`,
              selected: true,
              source: e.source || 'llm',
            }));
            setEntities(entitiesWithSource);
            setUndoStack([]);
            setRedoStack([]);
            showToast(`识别到 ${entitiesWithSource.length} 处敏感信息`, 'success');
          }
        }
        
        setStage('preview');
      } catch (err) {
        showToast(err instanceof Error ? err.message : '识别失败', 'error');
      } finally {
        setIsLoading(false);
        setLoadingMessage('');
      }
    };
    
    doRecognition();
  }, [pendingFile]); // 只依赖 pendingFile，类型选择通过 ref 获取

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop: handleFileDrop,
    accept: {
      'application/msword': ['.doc'],
      'application/vnd.openxmlformats-officedocument.wordprocessingml.document': ['.docx'],
      'application/pdf': ['.pdf'],
      'image/jpeg': ['.jpg', '.jpeg'],
      'image/png': ['.png'],
    },
    maxFiles: 1,
  });

  // 处理文本选择
  const handleTextSelect = () => {
    if (isImageMode) return;
    
    // 如果有实体弹窗打开，不处理文本选择
    if (clickedEntity) return;
    
    const selection = window.getSelection();
    if (!selection || !contentRef.current) {
      selectionRangeRef.current = null;
      setSelectedText(null);
      setSelectionPos(null);
      setSelectedOverlapIds([]);
      return;
    }
    if (selection.isCollapsed) {
      if (selectedText && selectionPos) {
        return;
      }
      selectionRangeRef.current = null;
      setSelectedText(null);
      setSelectionPos(null);
      setSelectedOverlapIds([]);
      return;
    }
    
    const text = selection.toString().trim();
    if (!text || text.length < 2) {
      selectionRangeRef.current = null;
      setSelectedText(null);
      setSelectionPos(null);
      setSelectedOverlapIds([]);
      return;
    }

    const range = selection.getRangeAt(0);
    if (!contentRef.current.contains(range.commonAncestorContainer)) {
      selectionRangeRef.current = null;
      setSelectedText(null);
      setSelectionPos(null);
      setSelectedOverlapIds([]);
      return;
    }
    
    const offsets = getSelectionOffsets(range, contentRef.current);
    const start = offsets?.start ?? content.indexOf(text);
    const end = offsets?.end ?? (start + text.length);
    if (start < 0 || end < 0) {
      selectionRangeRef.current = null;
      setSelectedText(null);
      setSelectionPos(null);
      setSelectedOverlapIds([]);
      return;
    }
    
    // 查找重叠的实体
    const overlaps = entities.filter(e =>
      (e.start <= start && e.end > start) || (e.start < end && e.end >= end)
    );
    
    try {
      selectionRangeRef.current = range.cloneRange();
    } catch {
      selectionRangeRef.current = null;
      setSelectedText(null);
      setSelectionPos(null);
      setSelectedOverlapIds([]);
      return;
    }
    setSelectedOverlapIds(overlaps.map(e => e.id));
    
    // 默认类型：如果有重叠实体，使用第一个重叠实体的类型；否则使用上次选择的类型或第一个可用类型
    if (overlaps.length > 0) {
      setSelectedTypeId(overlaps[0].type);
    } else if (!selectedTypeId) {
      const firstType = entityTypes.find(t => selectedTypes.includes(t.id))?.id || entityTypes[0]?.id;
      if (firstType) setSelectedTypeId(firstType);
    }
    
    setSelectionPos(null);
    setSelectedText({ text, start, end });
  };

  const getSelectionOffsets = (range: Range, root: HTMLElement) => {
    let start = -1;
    let end = -1;
    let offset = 0;
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      const node = walker.currentNode as Text;
      const textLength = node.textContent?.length || 0;
      if (node === range.startContainer) {
        start = offset + range.startOffset;
      }
      if (node === range.endContainer) {
        end = offset + range.endOffset;
        break;
      }
      offset += textLength;
    }
    if (start === -1 || end === -1 || end <= start) {
      return null;
    }
    return { start, end };
  };

  /** 划词弹层：按 Canvas 夹紧位置，并在滚动/缩放时跟随选区 */
  useLayoutEffect(() => {
    if (!selectedText) {
      selectionRangeRef.current = null;
      setSelectionPos(null);
      return;
    }
    const root = contentRef.current;
    if (!root) return;

    const update = () => {
      const range = selectionRangeRef.current;
      if (!range || range.collapsed) {
        setSelectionPos(null);
        return;
      }
      let rect: DOMRect;
      try {
        rect = range.getBoundingClientRect();
      } catch {
        setSelectionPos(null);
        return;
      }
      if (rect.width === 0 && rect.height === 0) return;
      const canvas = root.getBoundingClientRect();
      setSelectionPos(clampPopoverInCanvas(rect, canvas, 400, 400));
    };

    update();
    const scrollEl = textScrollRef.current;
    window.addEventListener('resize', update);
    scrollEl?.addEventListener('scroll', update, { passive: true });
    return () => {
      window.removeEventListener('resize', update);
      scrollEl?.removeEventListener('scroll', update);
    };
  }, [selectedText]);

  /** 点击已有标注：弹层锚在实体上并随 Canvas 滚动 */
  useLayoutEffect(() => {
    if (!clickedEntity) {
      setEntityPopupPos(null);
      return;
    }
    const root = contentRef.current;
    if (!root) return;

    const update = () => {
      let el: HTMLElement | null = null;
      try {
        el = root.querySelector(`[data-entity-id="${CSS.escape(clickedEntity.id)}"]`);
      } catch {
        el = null;
      }
      if (!el) return;
      const rect = el.getBoundingClientRect();
      const canvas = root.getBoundingClientRect();
      setEntityPopupPos(clampPopoverInCanvas(rect, canvas, 240, 220));
    };

    update();
    const scrollEl = textScrollRef.current;
    window.addEventListener('resize', update);
    scrollEl?.addEventListener('scroll', update, { passive: true });
    return () => {
      window.removeEventListener('resize', update);
      scrollEl?.removeEventListener('scroll', update);
    };
  }, [clickedEntity]);

  // 添加手动实体
  const addManualEntity = (typeId: string) => {
    if (!selectedText) return;
    const newEntity: Entity = {
      id: `manual_${Date.now()}`,
      text: selectedText.text,
      type: typeId,
      start: selectedText.start,
      end: selectedText.end,
      selected: true,
      source: 'manual',
    };

    const next = entities
      .filter(e => !selectedOverlapIds.includes(e.id))
      .concat(newEntity)
      .sort((a, b) => a.start - b.start);
    applyEntities(next);

    if (selectedOverlapIds.length > 0) {
      showToast('已更新标记', 'success');
    } else {
      const config = getTypeConfig(typeId);
      showToast(`已添加: ${config.name}`, 'success');
    }
    
    selectionRangeRef.current = null;
    setSelectedText(null);
    setSelectionPos(null);
    setSelectedOverlapIds([]);
    window.getSelection()?.removeAllRanges();
  };

  const removeSelectedEntities = () => {
    if (selectedOverlapIds.length === 0) return;
    applyEntities(entities.filter(e => !selectedOverlapIds.includes(e.id)));
    selectionRangeRef.current = null;
    setSelectedText(null);
    setSelectionPos(null);
    setSelectedOverlapIds([]);
    window.getSelection()?.removeAllRanges();
    showToast('已删除标记', 'info');
  };

  // 重新识别
  const handleRerunNer = async () => {
    if (!fileInfo) return;
    setIsLoading(true);
    setLoadingMessage(
      isImageMode
        ? (() => {
            const o = selectedOcrHasTypes.length > 0;
            const g = selectedHasImageTypes.length > 0;
            if (o && g) return '重新识别中（OCR+HaS 与 HaS Image 并行）...';
            if (o) return '重新识别中（OCR+HaS）...';
            if (g) return '重新识别中（HaS Image）...';
            return '重新识别中...';
          })()
        : '重新识别中（正则+AI语义识别）...'
    );
    
    try {
      if (isImageMode) {
        console.log('[Rerun] OCR+HaS 类型:', selectedOcrHasTypes);
        console.log('[Rerun] HaS Image 类型:', selectedHasImageTypes);
        
        const result = await runVisionDetection(
          fileInfo.file_id,
          selectedOcrHasTypes,
          selectedHasImageTypes
        );
        
        setBoundingBoxes(result.boxes);
        resetImageHistory();
        if (result.resultImage) {
          setResultImage(result.resultImage);
        }
        showToast(`重新识别完成：${result.boxes.length} 个区域`, 'success');
      } else {
        const nerRes = await fetch(`/api/v1/files/${fileInfo.file_id}/ner/hybrid`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ entity_type_ids: selectedTypes }),
        });
        if (!nerRes.ok) throw new Error('重新识别失败');
        const nerData = await nerRes.json();
        const entitiesWithSource = (nerData.entities || []).map((e: any, idx: number) => ({
          ...e,
          id: e.id || `entity_${idx}`,
          selected: true,
          source: e.source || 'llm',
        }));
        setEntities(entitiesWithSource);
        setUndoStack([]);
        setRedoStack([]);
        showToast(`重新识别完成：${entitiesWithSource.length} 处`, 'success');
      }
    } catch (err) {
      showToast(err instanceof Error ? err.message : '重新识别失败', 'error');
    } finally {
      setIsLoading(false);
      setLoadingMessage('');
    }
  };

  // 删除实体
  const removeEntity = (id: string) => {
    applyEntities(entities.filter(e => e.id !== id));
    showToast('已删除', 'info');
  };

  // 执行脱敏
  const handleRedact = async () => {
    if (!fileInfo) return;
    setIsLoading(true);
    setLoadingMessage('正在执行脱敏...');
    
    try {
      const selectedEntities = entities.filter(e => e.selected);
      const selectedBoxes = boundingBoxes.filter(b => b.selected);
      
      const res = await fetch('/api/v1/redaction/execute', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          file_id: fileInfo.file_id,
          entities: selectedEntities,
          bounding_boxes: selectedBoxes,
          config: { replacement_mode: replacementMode, entity_types: [], custom_replacements: {} },
        }),
      });
      
      if (!res.ok) throw new Error('脱敏处理失败');
      
      const result = await res.json();
      const map: Record<string, string> = result.entity_map || {};
      setEntityMap(map);
      setRedactedCount(result.redacted_count || 0);

      // 前端直接用 content + entityMap 计算脱敏后文本（与 highlightText 相同正则，保证三列对齐）
      if (content && Object.keys(map).length > 0) {
        const sorted = Object.keys(map).sort((a, b) => b.length - a.length);
        const re = new RegExp(`(${sorted.map(k => k.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')})`, 'g');
        setRedactedContent(content.replace(re, m => map[m] ?? m));
      } else {
        setRedactedContent(content);
      }

      setStage('result');
      showToast(`完成，共处理 ${result.redacted_count} 处`, 'success');
    } catch (err) {
      showToast(err instanceof Error ? err.message : '脱敏失败', 'error');
    } finally {
      setIsLoading(false);
      setLoadingMessage('');
    }
  };

  const handleReset = () => {
    setStage('upload');
    setFileInfo(null);
    setContent('');
    setEntities([]);
    setRedactedContent('');
    setRedactedCount(0);
    setEntityMap({});
    selectionRangeRef.current = null;
    setSelectedText(null);
    setSelectionPos(null);
    setSelectedOverlapIds([]);
    setUndoStack([]);
    setRedoStack([]);
    setBoundingBoxes([]);
    resetImageHistory();
    setResultImage(null);
  };

  const isImageMode = !!fileInfo && (fileInfo.file_type === 'image' || fileInfo.is_scanned);

  const [loadingElapsedSec, setLoadingElapsedSec] = useState(0);
  useEffect(() => {
    if (!isLoading) {
      setLoadingElapsedSec(0);
      return;
    }
    setLoadingElapsedSec(0);
    const id = window.setInterval(() => setLoadingElapsedSec(s => s + 1), 1000);
    return () => window.clearInterval(id);
  }, [isLoading]);

  const imageUrl = fileInfo ? `/api/v1/files/${fileInfo.file_id}/download` : '';
  const canUndo = isImageMode ? imageUndoStack.length > 0 : undoStack.length > 0;
  const canRedo = isImageMode ? imageRedoStack.length > 0 : redoStack.length > 0;
  const handleUndo = () => (isImageMode ? undoImage() : undo());
  const handleRedo = () => (isImageMode ? redoImage() : redo());

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable)) {
        return;
      }
      const isMac = navigator.platform.toLowerCase().includes('mac');
      const modKey = isMac ? e.metaKey : e.ctrlKey;
      if (!modKey) return;

      const key = e.key.toLowerCase();
      if (key === 'z') {
        e.preventDefault();
        if (e.shiftKey) {
          if (!canRedo) return;
          handleRedo();
        } else {
          if (!canUndo) return;
          handleUndo();
        }
      } else if (key === 'y') {
        e.preventDefault();
        if (!canRedo) return;
        handleRedo();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [handleRedo, handleUndo, canUndo, canRedo]);

  useEffect(() => {
    setTypeTab(isImageMode ? 'vision' : 'text');
  }, [isImageMode]);

  useEffect(() => {
    const updateImageSize = () => {
      if (!imgRef.current) return;
      const rect = imgRef.current.getBoundingClientRect();
      setImageRenderSize({ width: rect.width, height: rect.height });
      setImageNaturalSize({ width: imgRef.current.naturalWidth, height: imgRef.current.naturalHeight });
    };
    updateImageSize();
    window.addEventListener('resize', updateImageSize);
    return () => window.removeEventListener('resize', updateImageSize);
  }, [imageUrl]);

  const allSelectedVisionTypes = [...selectedOcrHasTypes, ...selectedHasImageTypes];
  const visibleBoxes = boundingBoxes;
  const mergeVisibleBoxes = useCallback((nextBoxes: BoundingBox[], prevBoxes: BoundingBox[] = []) => {
    const ids = new Set([...nextBoxes, ...prevBoxes].map(b => b.id));
    const otherBoxes = boundingBoxes.filter(b => !ids.has(b.id));
    return [...otherBoxes, ...nextBoxes];
  }, [boundingBoxes]);

  const toggleBox = (id: string) => {
    setBoundingBoxes(prev => prev.map(b => b.id === id ? { ...b, selected: !b.selected } : b));
  };

  const selectAll = () => {
    if (isImageMode) {
      setBoundingBoxes(prev => prev.map(b => ({
        ...b,
        selected: allSelectedVisionTypes.includes(b.type),
      })));
    } else {
      setEntities(prev => prev.map(e => ({ ...e, selected: true })));
    }
  };

  const deselectAll = () => {
    if (isImageMode) {
      setBoundingBoxes(prev => prev.map(b => ({ ...b, selected: false })));
    } else {
      setEntities(prev => prev.map(e => ({ ...e, selected: false })));
    }
  };

  const selectedCount = isImageMode
    ? visibleBoxes.filter(b => b.selected).length
    : entities.filter(e => e.selected).length;

  // 点击实体时弹出操作菜单
  const handleEntityClick = (entity: Entity, event: React.MouseEvent) => {
    event.stopPropagation();
    selectionRangeRef.current = null;
    setSelectedText(null);
    setSelectionPos(null);
    setSelectedOverlapIds([]);
    setClickedEntity(entity);
    // 设置当前类型为该实体的类型（方便修改时默认选中）
    setSelectedTypeId(entity.type);
  };
  
  // 确认移除实体标注
  const confirmRemoveEntity = () => {
    if (clickedEntity) {
      applyEntities(entities.filter(e => e.id !== clickedEntity.id));
      showToast('已移除标注', 'info');
    }
    setClickedEntity(null);
    setEntityPopupPos(null);
  };
  
  // 关闭实体弹窗
  const closeEntityPopup = () => {
    setClickedEntity(null);
    setEntityPopupPos(null);
  };

  // 渲染带下划线标记的内容 - 优化版
  const renderMarkedContent = () => {
    if (!content) return <p className="text-[#a3a3a3]">暂无内容</p>;
    
    const sorted = [...entities].sort((a, b) => a.start - b.start);
    const segments: React.ReactNode[] = [];
    let lastEnd = 0;

    sorted.forEach((entity) => {
      if (entity.start < lastEnd) {
        return;
      }
      if (entity.start > lastEnd) {
        segments.push(
          <span key={`t-${lastEnd}`}>{content.slice(lastEnd, entity.start)}</span>
        );
      }
      
      const typeName = getEntityTypeName(entity.type);
      const sourceLabel = entity.source === 'regex' ? '正则' : entity.source === 'manual' ? '手动' : 'AI';
      
      // 所有实体：按识别来源着色（正则蓝 / 语义绿 / 手动紫 / HaS 靛紫），与右侧配置一致
      segments.push(
        <span
          key={entity.id}
          data-entity-id={entity.id}
          onClick={(e) => handleEntityClick(entity, e)}
          style={previewEntityMarkStyle(entity)}
          className={`cursor-pointer transition-all inline-flex items-center gap-0.5 rounded px-0.5 -mx-0.5 hover:ring-2 hover:ring-offset-1 hover:shadow-sm ${previewEntityHoverRingClass(entity.source)}`}
          title={`${typeName} [${sourceLabel}] - 点击编辑或移除`}
        >
          {content.slice(entity.start, entity.end)}
        </span>
      );
      lastEnd = entity.end;
    });

    if (lastEnd < content.length) {
      segments.push(<span key="end">{content.slice(lastEnd)}</span>);
    }

    return segments;
  };

  // 统计
  const getStats = () => {
    const stats: Record<string, { total: number; selected: number }> = {};
    entities.forEach(e => {
      if (!stats[e.type]) stats[e.type] = { total: 0, selected: 0 };
      stats[e.type].total++;
      if (e.selected) stats[e.type].selected++;
    });
    return stats;
  };
  const stats = getStats();

  return (
    <div className="h-full min-h-0 min-w-0 flex flex-col overflow-hidden bg-[#f5f5f7]">
      {/* 上传阶段 */}
      {stage === 'upload' && (
        <div className="flex-1 flex flex-col lg:flex-row gap-3 lg:gap-5 p-3 lg:p-5 min-h-0 min-w-0 overflow-hidden">
          {/* 上传区域 */}
          <div className="flex-1 flex items-center justify-center min-h-0 min-w-0">
            <div className="w-full max-w-lg">
              <div
                {...getRootProps()}
                className={`border-2 border-dashed rounded-2xl p-10 text-center cursor-pointer transition-all bg-white ${
                  isDragActive ? 'border-blue-500 bg-blue-50' : 'border-gray-300 hover:border-blue-400'
                }`}
              >
                <input {...getInputProps()} />
                <div className="w-14 h-14 mx-auto mb-4 rounded-xl bg-blue-100 flex items-center justify-center">
                  <svg className="w-7 h-7 text-blue-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"/>
                  </svg>
                </div>
                <p className="text-base font-medium text-[#1d1d1f] mb-1">拖拽文件到此处上传</p>
                <p className="text-sm text-[#737373] mb-4">支持 .doc .docx .pdf .jpg .png</p>
              </div>
            </div>
          </div>
          
          {/* 类型配置面板 */}
          <div className="w-full lg:w-[min(100%,400px)] xl:w-[420px] 2xl:w-[460px] shrink-0 max-h-[min(52vh,480px)] lg:max-h-none lg:self-stretch bg-white/90 backdrop-blur-2xl rounded-2xl border border-black/[0.06] flex flex-col shadow-[0_2px_16px_rgba(0,0,0,0.06)] min-h-0 overflow-hidden">
            {/* 头部 */}
            <div className="px-3 py-2 border-b border-gray-100/80 space-y-1.5">
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-semibold text-[#1d1d1f] tracking-tight">识别类型</h3>
                <div className="flex bg-gray-100 rounded-lg p-0.5">
                  <button onClick={() => setTypeTab('text')} className={`text-caption px-2.5 py-1 rounded-md font-medium transition-all ${typeTab === 'text' ? 'bg-white text-[#1d1d1f] shadow-sm' : 'text-[#737373]'}`}>文本</button>
                  <button onClick={() => setTypeTab('vision')} className={`text-caption px-2.5 py-1 rounded-md font-medium transition-all ${typeTab === 'vision' ? 'bg-white text-[#1d1d1f] shadow-sm' : 'text-[#737373]'}`}>图像</button>
                </div>
              </div>
              <div className="flex flex-col gap-2">
                <div className="flex flex-col gap-0.5">
                  <span className="text-2xs text-[#737373]">文本脱敏配置清单</span>
                  <div className="flex items-center gap-1.5 min-w-0">
                    <select
                      className="text-2xs flex-1 min-w-0 border border-gray-200 rounded-md px-1.5 py-1 bg-white"
                      value={playgroundPresetTextId ?? ''}
                      onChange={e => selectPlaygroundTextPresetById(e.target.value)}
                    >
                      <option value="">默认</option>
                      {textPresetsPg.map(p => (
                        <option key={p.id} value={p.id}>
                          {p.name}
                          {p.kind === 'full' ? '（组合）' : ''}
                        </option>
                      ))}
                    </select>
                    <button
                      type="button"
                      onClick={() => void saveTextPresetFromPlayground()}
                      className="text-2xs shrink-0 px-1.5 py-1 rounded-md border border-gray-200 hover:bg-gray-50 whitespace-nowrap"
                    >
                      另存为文本预设
                    </button>
                  </div>
                </div>
                <div className="flex flex-col gap-0.5">
                  <span className="text-2xs text-[#737373]">图像脱敏配置清单</span>
                  <div className="flex items-center gap-1.5 min-w-0">
                    <select
                      className="text-2xs flex-1 min-w-0 border border-gray-200 rounded-md px-1.5 py-1 bg-white"
                      value={playgroundPresetVisionId ?? ''}
                      onChange={e => selectPlaygroundVisionPresetById(e.target.value)}
                    >
                      <option value="">默认</option>
                      {visionPresetsPg.map(p => (
                        <option key={p.id} value={p.id}>
                          {p.name}
                          {p.kind === 'full' ? '（组合）' : ''}
                        </option>
                      ))}
                    </select>
                    <button
                      type="button"
                      onClick={() => void saveVisionPresetFromPlayground()}
                      className="text-2xs shrink-0 px-1.5 py-1 rounded-md border border-gray-200 hover:bg-gray-50 whitespace-nowrap"
                    >
                      另存为图像预设
                    </button>
                  </div>
                </div>
              </div>
            </div>

            {/* 内容区 */}
            <div className="flex-1 min-h-0 overflow-y-auto overscroll-contain">
              {typeTab === 'vision' ? (
                pipelines.length === 0 ? (
                  <p className="text-caption text-[#a3a3a3] text-center py-8">加载中...</p>
                ) : (
                  <div className="p-2 space-y-3">
                    {pipelines.map(pipeline => {
                      const isHasImage = pipeline.mode === 'has_image';
                      const types = pipeline.types.filter(t => t.enabled);
                      const selectedSet = isHasImage ? selectedHasImageTypes : selectedOcrHasTypes;
                      const allSelected = types.length > 0 && types.every(t => selectedSet.includes(t.id));
                      
                      const presetGroups = isHasImage
                        ? [
                            {
                              label: '视觉元素',
                              ids: [
                                'SIGNATURE',
                                'FINGERPRINT',
                                'PHOTO',
                                'QR_CODE',
                                'HANDWRITING',
                                'WATERMARK',
                                'CHAT_BUBBLE',
                                'SENSITIVE_TABLE',
                              ],
                            },
                          ]
                        : [];
                      const allPresetIds = new Set(presetGroups.flatMap(g => g.ids));
                      const customTypes = isHasImage ? types.filter(t => !allPresetIds.has(t.id)) : [];
                      const visionGroups =
                        isHasImage && customTypes.length > 0
                          ? [...presetGroups, { label: '自定义', ids: customTypes.map(t => t.id) }]
                          : isHasImage
                            ? presetGroups
                            : [];
                      
                      return (
                        <div key={pipeline.mode}>
                          <div className="flex items-center justify-between mb-1.5 pb-1 border-b border-gray-200/90">
                            <span
                              className={`text-2xs font-semibold text-[#1d1d1f] pl-2 border-l-[3px] ${
                                isHasImage ? 'border-[#AF52DE]' : 'border-[#34C759]'
                              }`}
                            >
                              {isHasImage ? '图像特征' : '图片类文本'}
                            </span>
                            <button onClick={() => {
                              clearPlaygroundVisionPresetTracking();
                              const ids = types.map(t => t.id);
                              if (allSelected) { if (isHasImage) updateHasImageTypes([]); else updateOcrHasTypes([]); }
                              else { if (isHasImage) updateHasImageTypes(ids); else updateOcrHasTypes(ids); }
                            }} className="text-2xs text-[#a3a3a3] hover:text-[#737373] transition-colors">
                              {allSelected ? '清空' : '全选'}
                            </button>
                          </div>
                          <div className="space-y-2">
                            {!isHasImage ? (
                              <div className="grid grid-cols-2 lg:grid-cols-3 gap-1.5">
                                {types.map(type => {
                                  const checked = selectedSet.includes(type.id);
                                  const v: SelectionVariant = 'ner';
                                  return (
                                    <label
                                      key={type.id}
                                      className={pgTypeBubbleClass(checked, v)}
                                      title={type.description || type.name}
                                    >
                                      <input
                                        type="checkbox"
                                        checked={checked}
                                        onChange={() => toggleVisionType(type.id, pipeline.mode as 'ocr_has' | 'has_image')}
                                        className={`shrink-0 ${selectableCheckboxClass(v)}`}
                                      />
                                      <span className="min-w-0 break-words">{type.name}</span>
                                    </label>
                                  );
                                })}
                              </div>
                            ) : (
                              visionGroups.map(group => {
                                const groupTypes = types.filter(t => group.ids.includes(t.id));
                                if (groupTypes.length === 0) return null;
                                return (
                                  <div key={group.label}>
                                    <div className="text-2xs text-[#737373] font-medium mb-0.5 pl-0.5">{group.label}</div>
                                    <div className="grid grid-cols-2 lg:grid-cols-3 gap-1.5">
                                      {groupTypes.map(type => {
                                        const checked = selectedSet.includes(type.id);
                                        const v: SelectionVariant = 'yolo';
                                        return (
                                          <label
                                            key={type.id}
                                            className={pgTypeBubbleClass(checked, v)}
                                            title={type.description || type.name}
                                          >
                                            <input
                                              type="checkbox"
                                              checked={checked}
                                              onChange={() => toggleVisionType(type.id, pipeline.mode as 'ocr_has' | 'has_image')}
                                              className={`shrink-0 ${selectableCheckboxClass(v)}`}
                                            />
                                            <span className="min-w-0 break-words">{type.name}</span>
                                          </label>
                                        );
                                      })}
                                    </div>
                                  </div>
                                );
                              })
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )
              ) : sortedEntityTypes.length === 0 ? (
                <p className="text-caption text-[#a3a3a3] text-center py-8">加载中...</p>
              ) : (
                <div className="p-2 space-y-3">
                  {playgroundTextGroups.map(group => {
                    const ids = group.types.map(t => t.id);
                    const allOn = ids.length > 0 && ids.every(id => selectedTypes.includes(id));
                    return (
                      <div key={group.key}>
                        <div className="flex items-center justify-between mb-1.5 pb-1 border-b border-gray-200/90">
                          <span
                            className={`text-2xs font-semibold text-[#1d1d1f] pl-2 border-l-[3px] ${
                              group.key === 'regex'
                                ? 'border-[#007AFF]'
                                : group.key === 'llm'
                                  ? 'border-[#34C759]'
                                  : 'border-violet-300/60'
                            }`}
                          >
                            {group.label}
                          </span>
                          <button
                            type="button"
                            onClick={() => setPlaygroundTextTypeGroupSelection(ids, !allOn)}
                            className="text-2xs text-[#a3a3a3] hover:text-[#737373] transition-colors"
                          >
                            {allOn ? '清空' : '全选'}
                          </button>
                        </div>
                        <div className="space-y-2">
                          <div className="grid grid-cols-2 lg:grid-cols-3 gap-1.5">
                            {group.types.map(type => {
                              const checked = selectedTypes.includes(type.id);
                              const v = textGroupKeyToVariant(group.key);
                              return (
                                <label
                                  key={`${group.key}-${type.id}`}
                                  className={pgTypeBubbleClass(checked, v)}
                                  title={type.description || type.name}
                                >
                                  <input
                                    type="checkbox"
                                    checked={checked}
                                    onChange={() => {
                                      clearPlaygroundTextPresetTracking();
                                      setSelectedTypes(prev =>
                                        checked ? prev.filter(t => t !== type.id) : [...prev, type.id]
                                      );
                                    }}
                                    className={`shrink-0 ${selectableCheckboxClass(v)}`}
                                  />
                                  <span className="min-w-0 break-words">{type.name}</span>
                                </label>
                              );
                            })}
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>

            {/* 底部 */}
            <div className="px-3 py-1.5 border-t border-gray-100/80 shrink-0">
              <div className="text-2xs text-[#a3a3a3] text-center leading-tight">
                {typeTab === 'vision'
                  ? `OCR ${selectedOcrHasTypes.length} · HaS图像 ${selectedHasImageTypes.length}`
                  : `${selectedTypes.length} / ${entityTypes.length} 已选`}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* 预览编辑阶段 */}
      {stage === 'preview' && (
        <div className="flex-1 flex gap-2 sm:gap-3 p-2 sm:p-3 min-h-0 min-w-0 overflow-hidden">
          {/* 文档内容 - 占满中间区域 */}
          <div className="flex-1 flex flex-col bg-white rounded-xl border border-gray-200 overflow-hidden min-w-0">
            <div className="px-3 py-2 border-b border-[#f0f0f0] flex items-center justify-between bg-[#fafafa] flex-shrink-0">
              <div className="min-w-0 flex-1">
                <h3 className="font-semibold text-[#1d1d1f] text-sm truncate">{fileInfo?.filename}</h3>
                <p className="text-xs text-[#737373]">
                  {isImageMode 
                    ? '拖拽框选添加区域 | 点击区域切换脱敏状态' 
                    : '点击高亮文字切换脱敏状态 | 划选文字添加新标记'}
                </p>
              </div>
              <div className="flex items-center gap-2 flex-shrink-0">
                {isImageMode && (
                  <button
                    onClick={() => {
                      // 弹出新窗口编辑
                      const editorWindow = window.open('', '_blank', 'width=1200,height=800,scrollbars=yes,resizable=yes');
                      if (editorWindow) {
                        editorWindow.document.write(`
                          <!DOCTYPE html>
                          <html>
                          <head>
                            <title>图像编辑 - ${fileInfo?.filename || '未命名'}</title>
                            <style>
                              * { margin: 0; padding: 0; box-sizing: border-box; }
                              body { font-family: system-ui, -apple-system, sans-serif; background: #1a1a1a; }
                              .container { width: 100vw; height: 100vh; display: flex; align-items: center; justify-content: center; padding: 20px; }
                              img { max-width: 100%; max-height: 100%; object-fit: contain; border-radius: 8px; box-shadow: 0 4px 20px rgba(0,0,0,0.5); }
                              .hint { position: fixed; bottom: 20px; left: 50%; transform: translateX(-50%); background: rgba(255,255,255,0.9); padding: 8px 16px; border-radius: 20px; font-size: 12px; color: #333; }
                            </style>
                          </head>
                          <body>
                            <div class="container">
                              <img src="${imageUrl}" alt="编辑图像" />
                            </div>
                            <div class="hint">在此窗口查看大图，编辑请在主窗口进行</div>
                          </body>
                          </html>
                        `);
                        editorWindow.document.close();
                      }
                    }}
                    className="text-xs text-[#737373] hover:text-[#1d1d1f] px-2 py-1 rounded hover:bg-[#f5f5f5]"
                    title="在新窗口中查看大图"
                  >
                    🔍 新窗口
                  </button>
                )}
                <button onClick={handleReset} className="text-xs text-[#737373] hover:text-[#1d1d1f]">重新上传</button>
              </div>
            </div>
            <div
              ref={contentRef}
              onMouseUp={handleTextSelect}
              onKeyUp={handleTextSelect}
              className="flex-1 overflow-hidden select-text flex flex-col"
              style={{ minHeight: 0 }}
            >
              {isImageMode ? (
                <div className="flex-1 min-h-0">
                  {fileInfo && (
                    <ImageBBoxEditor
                      imageSrc={imageUrl}
                      boxes={visibleBoxes}
                      onBoxesChange={(newBoxes) => {
                        setBoundingBoxes(mergeVisibleBoxes(newBoxes));
                      }}
                      onBoxesCommit={(prevBoxes, nextBoxes) => {
                        const prevAll = mergeVisibleBoxes(prevBoxes, nextBoxes);
                        const nextAll = mergeVisibleBoxes(nextBoxes, prevBoxes);
                        setImageUndoStack(prev => [...prev, prevAll]);
                        setImageRedoStack([]);
                        setBoundingBoxes(nextAll);
                      }}
                      getTypeConfig={getVisionTypeConfig}
                      availableTypes={visionTypes.map(t => ({ id: t.id, name: t.name, color: '#6366F1' }))}
                      defaultType={visionTypes[0]?.id || 'CUSTOM'}
                    />
                  )}
                </div>
              ) : (
                <div ref={textScrollRef} className="flex-1 overflow-auto min-h-0">
                  <div className="whitespace-pre-wrap text-sm text-[#1d1d1f] leading-relaxed font-[system-ui,-apple-system,BlinkMacSystemFont,'Segoe_UI',sans-serif] p-4">
                    {renderMarkedContent()}
                  </div>
                </div>
              )}
              {/* 划词添加/修改弹窗 - 二级标签选择器 */}
              {!isImageMode && selectedText && selectionPos && (
                <div
                  className="fixed z-50 bg-white border border-gray-200 rounded-2xl shadow-2xl p-4 min-w-[320px] max-w-[400px]"
                  style={{
                    left: selectionPos.left,
                    top: selectionPos.top,
                  }}
                  onMouseDown={(e) => e.stopPropagation()}
                  onMouseUp={(e) => e.stopPropagation()}
                >
                  {/* 选中文本预览 */}
                  <div className="mb-3">
                    <div className="text-caption text-[#737373] mb-1 font-medium">选中文本</div>
                    <div className="text-sm text-[#262626] bg-gray-50 rounded-lg px-3 py-2 max-w-full break-all border border-gray-100">
                      {selectedText.text}
                    </div>
                  </div>
                  
                  {/* 二级标签选择器 */}
                  <div className="mb-3">
                    <div className="text-caption text-[#737373] mb-2 font-medium">选择类型</div>
                    <div className="max-h-[240px] overflow-auto space-y-2 pr-1">
                      {ENTITY_GROUPS.filter(group => 
                        group.types.some(t => entityTypes.some(et => et.id === t.id))
                      ).map(group => {
                        const availableTypes = group.types.filter(t => 
                          entityTypes.some(et => et.id === t.id)
                        );
                        if (availableTypes.length === 0) return null;
                        
                        return (
                          <div key={group.id} className="rounded-lg border border-gray-200 overflow-hidden bg-white">
                            {/* 一级分组标题 */}
                            <div className="px-2.5 py-1.5 text-caption font-semibold text-[#262626] bg-gray-100 border-b border-gray-200">
                              {group.label}
                            </div>
                            {/* 二级类型列表 */}
                            <div className="p-1.5 grid grid-cols-3 gap-1 bg-white">
                              {availableTypes.map(type => {
                                const isSelected = selectedTypeId === type.id;
                                return (
                                  <button
                                    key={type.id}
                                    onClick={() => setSelectedTypeId(type.id)}
                                    className={`text-xs px-2 py-1.5 rounded-md text-left transition-all truncate text-[#262626] ${
                                      isSelected
                                        ? 'font-semibold bg-gray-100 ring-2 ring-gray-400 ring-offset-0'
                                        : 'hover:bg-gray-50'
                                    }`}
                                    title={type.description}
                                  >
                                    {type.name}
                                  </button>
                                );
                              })}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                  
                  {/* 操作按钮 */}
                  <div className="flex gap-2 pt-2 border-t border-gray-100">
                    <button
                      onClick={() => addManualEntity(selectedTypeId)}
                      disabled={!selectedTypeId}
                      className="flex-1 text-sm font-medium bg-black text-white rounded-lg px-3 py-2 hover:bg-zinc-900 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                    >
                      {selectedOverlapIds.length > 0 ? '更新标记' : '添加标记'}
                    </button>
                    {selectedOverlapIds.length > 0 && (
                      <button
                        onClick={removeSelectedEntities}
                        className="text-sm font-medium text-violet-700 border border-violet-200 rounded-lg px-3 py-2 hover:bg-violet-50 transition-colors"
                      >
                        删除
                      </button>
                    )}
                    <button
                      onClick={() => {
                        selectionRangeRef.current = null;
                        setSelectedText(null);
                        setSelectionPos(null);
                        setSelectedOverlapIds([]);
                      }}
                      className="text-sm text-[#737373] border border-gray-200 rounded-lg px-3 py-2 hover:bg-gray-50 transition-colors"
                    >
                      取消
                    </button>
                  </div>
                </div>
              )}
              
              {/* 点击实体弹出的操作菜单 */}
              {!isImageMode && clickedEntity && entityPopupPos && (
                <div
                  className="fixed z-50 bg-white border border-gray-200 rounded-xl shadow-2xl p-3 min-w-[200px]"
                  style={{
                    left: entityPopupPos.left,
                    top: entityPopupPos.top,
                  }}
                  onMouseDown={(e) => e.stopPropagation()}
                  onMouseUp={(e) => e.stopPropagation()}
                >
                  {(() => {
                    const typeName = getEntityTypeName(clickedEntity.type);
                    const group = getEntityGroup(clickedEntity.type);
                    return (
                      <>
                        {/* 实体信息 */}
                        <div className="mb-3">
                          <div className="flex items-center gap-2 mb-1.5">
                            <span className="text-caption font-semibold px-2 py-0.5 rounded bg-gray-100 text-[#1d1d1f]">
                              {group?.label} · {typeName}
                            </span>
                          </div>
                          <div className="text-sm font-medium px-2 py-1.5 rounded-lg break-all bg-gray-50 text-[#1d1d1f] border border-gray-100">
                            {clickedEntity.text}
                          </div>
                        </div>
                        
                        {/* 操作按钮 */}
                        <div className="space-y-1.5">
                          <button
                            onClick={confirmRemoveEntity}
                            className="w-full text-sm font-medium text-violet-700 border border-violet-200 rounded-lg px-3 py-2 hover:bg-violet-50 transition-colors flex items-center justify-center gap-1.5"
                          >
                            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                            </svg>
                            移除此标注
                          </button>
                          <button
                            onClick={closeEntityPopup}
                            className="w-full text-sm text-[#737373] border border-gray-200 rounded-lg px-3 py-2 hover:bg-gray-50 transition-colors"
                          >
                            取消
                          </button>
                        </div>
                      </>
                    );
                  })()}
                </div>
              )}
            </div>
          </div>

          {/* 右侧面板：标注编辑仅保留「重新识别」；类型与预设请在设置/上传阶段配置 */}
          <div className="w-full min-w-0 max-w-full sm:max-w-[320px] sm:w-[min(100%,300px)] lg:w-[300px] flex-shrink-0 flex flex-col gap-2 min-h-0 self-stretch overflow-y-auto overflow-x-hidden pr-1">
            <div className="bg-white/95 rounded-2xl border border-black/[0.06] shadow-[0_2px_12px_rgba(0,0,0,0.05)] p-3">
              <div className="flex flex-col gap-2 min-w-0">
                <button
                  type="button"
                  onClick={handleRerunNer}
                  className="w-full text-xs font-medium bg-black text-white rounded-lg py-2.5 px-2 hover:bg-zinc-900 transition-colors"
                >
                  重新识别
                </button>
                <p className="text-2xs text-[#a3a3a3] leading-snug break-words">
                  类型与预设请在「识别项配置」或上传页选择；此处仅重新跑识别。
                </p>
              </div>
            </div>

            {/* 交互说明 */}
            <div className="bg-gradient-to-br from-gray-50 to-white rounded-xl border border-[#e5e5e5] p-3">
              <div className="text-xs font-semibold text-[#1d1d1f] mb-2">💡 操作说明</div>
              <div className="space-y-2 text-xs text-[#737373]">
                <div className="flex items-start gap-2">
                  <span className="w-5 h-5 rounded bg-violet-100 text-violet-700 flex items-center justify-center text-2xs font-bold flex-shrink-0">点</span>
                  <span>点击高亮文字 → 弹出菜单 → 确认移除</span>
                </div>
                <div className="flex items-start gap-2">
                  <span className="w-5 h-5 rounded bg-gray-100 text-[#1d1d1f] flex items-center justify-center text-2xs flex-shrink-0">选</span>
                  <span>划选文字 → 选择类型 → 添加标记</span>
                </div>
              </div>
            </div>

            {/* 统计 */}
            <div className="bg-white/95 rounded-2xl border border-black/[0.06] shadow-[0_2px_12px_rgba(0,0,0,0.05)] p-4">
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-sm font-semibold text-[#1d1d1f]">识别结果</h3>
                <span className="text-xs text-[#737373] font-medium">
                  {selectedCount}/{isImageMode ? visibleBoxes.length : entities.length}
                </span>
              </div>
              <div className="flex gap-2 mb-3">
                <button onClick={selectAll} className="flex-1 py-1.5 text-xs font-medium text-[#1d1d1f] bg-[#f5f5f5] rounded-lg hover:bg-[#e5e5e5] transition-colors">全选</button>
                <button onClick={deselectAll} className="flex-1 py-1.5 text-xs font-medium text-[#737373] bg-white border border-[#e5e5e5] rounded-lg hover:bg-[#fafafa] transition-colors">取消</button>
              </div>
              {!isImageMode && (
                <>
                  <div className="mb-3">
                    <label className="block text-caption text-[#737373] mb-1.5 font-medium">脱敏方式</label>
                    <select
                      value={replacementMode}
                      onChange={(e) => {
                        clearPlaygroundTextPresetTracking();
                        setReplacementMode(e.target.value as 'structured' | 'smart' | 'mask');
                      }}
                      className="w-full text-sm border border-[#e5e5e5] rounded-lg px-3 py-2 focus:outline-none focus:border-[#1d1d1f] bg-white cursor-pointer"
                    >
                      <option value="structured">结构化语义标签（推荐）</option>
                      <option value="smart">智能替换</option>
                      <option value="mask">掩码替换</option>
                    </select>
                    <div className="mt-2 text-2xs text-[#a3a3a3] leading-snug space-y-2">
                      <p className="break-words">
                        <span className="text-[#737373] font-medium">structured（结构化）</span>
                        ：用语义标签占位，便于审计和机器读。典型效果：如{' '}
                        <code className="text-2xs bg-[#f5f5f5] px-0.5 rounded text-[#737373] break-all">&lt;人物[001].个人.姓名&gt;</code>
                        、
                        <code className="text-2xs bg-[#f5f5f5] px-0.5 rounded text-[#737373] break-all">&lt;组织[001].企业.完整名称&gt;</code>
                        ；自定义类型可走 tag_template。
                      </p>
                      <p className="break-words">
                        <span className="text-[#737373] font-medium">smart（智能）</span>
                        ：用简短中文类别 + 编号。典型效果：如 [当事人一]、[公司二]，按类型分别计数。
                      </p>
                      <p className="break-words">
                        <span className="text-[#737373] font-medium">mask（掩码）</span>
                        ：保留部分字符，其余打星。人名留姓、手机留前 3 后 4、身份证留前 6 后 4 等；其它类型多为全 *。
                      </p>
                    </div>
                  </div>
                  {Object.keys(stats).length > 0 && (
                    <div className="space-y-2">
                      {/* 按分组统计 */}
                      {ENTITY_GROUPS.map(group => {
                        const groupStats = Object.entries(stats).filter(([typeId]) => {
                          return group.types.some(t => t.id === typeId);
                        });
                        
                        if (groupStats.length === 0) return null;
                        
                        const totalInGroup = groupStats.reduce((sum, [, c]) => sum + c.total, 0);
                        const selectedInGroup = groupStats.reduce((sum, [, c]) => sum + c.selected, 0);
                        
                        return (
                          <div key={group.id} className="rounded-lg overflow-hidden border border-gray-200">
                            <div className="flex items-center justify-between px-2.5 py-1.5 bg-gray-100 border-b border-gray-200">
                              <span className="text-caption font-semibold text-[#262626]">
                                {group.label}
                              </span>
                              <span className="text-caption font-medium text-[#737373] tabular-nums">
                                {selectedInGroup}/{totalInGroup}
                              </span>
                            </div>
                            <div className="px-2.5 py-1.5 space-y-0.5 bg-white">
                              {groupStats.map(([typeId, count]) => (
                                <div key={typeId} className="flex items-center justify-between text-caption">
                                  <span className="text-[#737373]">{getEntityTypeName(typeId)}</span>
                                  <span className="text-[#1d1d1f] tabular-nums">{count.selected}/{count.total}</span>
                                </div>
                              ))}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </>
              )}
            </div>

            {/* 实体列表 - 按分组显示 */}
            <div className="flex-1 bg-white rounded-2xl border border-black/[0.06] shadow-[0_1px_8px_rgba(0,0,0,0.04)] overflow-hidden flex flex-col min-h-0">
              <div className="px-4 py-2.5 border-b border-[#f0f0f0] bg-[#fafafa] flex items-center justify-between">
                <span className="text-sm font-semibold text-[#1d1d1f]">
                  {isImageMode ? '区域列表' : '识别结果'}
                </span>
                <span className="text-xs text-[#737373]">
                  点击可编辑/移除
                </span>
              </div>
              <div className="flex-1 overflow-auto">
                {isImageMode ? (
                  visibleBoxes.length === 0 ? (
                    <p className="p-4 text-center text-md text-[#a3a3a3]">暂无识别结果</p>
                  ) : (
                    visibleBoxes.map(box => {
                      const group = getEntityGroup(box.type);
                      const v: SelectionVariant = box.source === 'has_image' ? 'yolo' : 'ner';
                      return (
                        <div
                          key={box.id}
                          className="px-3 py-2.5 flex items-center gap-2 cursor-pointer border-b border-gray-50 transition-all hover:bg-gray-50"
                          onClick={() => toggleBox(box.id)}
                        >
                          <input
                            type="checkbox"
                            checked={box.selected}
                            onChange={() => {}}
                            className={selectableCheckboxClass(v, 'md')}
                          />
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-1.5 mb-1">
                              <span className="text-caption font-medium px-1.5 py-0.5 rounded bg-gray-100 text-[#1d1d1f]">
                                {group?.label} · {getEntityTypeName(box.type)}
                              </span>
                              <span className="px-1 py-0.5 rounded text-2xs font-medium text-[#1d1d1f] bg-gray-200">
                                {box.source === 'ocr_has' ? 'OCR' : box.source === 'has_image' ? '图像' : '手动'}
                              </span>
                            </div>
                            <p className="text-md truncate text-[#1d1d1f]">
                              {box.text || '图像区域'}
                            </p>
                          </div>
                        </div>
                      );
                    })
                  )
                ) : (
                  entities.length === 0 ? (
                    <p className="p-4 text-center text-md text-[#a3a3a3]">暂无识别结果</p>
                  ) : (
                    // 按分组显示
                    ENTITY_GROUPS.map(group => {
                      const groupEntities = entities.filter(e => 
                        group.types.some(t => t.id === e.type)
                      );
                      
                      if (groupEntities.length === 0) return null;
                      
                      return (
                        <div key={group.id}>
                          {/* 分组标题 */}
                          <div className="px-3 py-2 flex items-center justify-between sticky top-0 z-10 bg-gray-100 border-b border-gray-200">
                            <span className="text-xs font-semibold text-[#262626]">
                              {group.label}
                            </span>
                            <span className="text-caption font-medium text-[#737373] tabular-nums">
                              {groupEntities.length}
                            </span>
                          </div>
                          {/* 该分组下的实体 */}
                          {groupEntities.map(entity => {
                            return (
                              <div
                                key={entity.id}
                                className="px-3 py-2.5 flex items-center gap-2 cursor-pointer border-b border-gray-50 transition-all hover:bg-gray-50"
                                onClick={(e) => handleEntityClick(entity, e)}
                              >
                                <div className="flex-1 min-w-0">
                                  <div className="flex items-center gap-1.5 mb-1">
                                    <span className="text-caption font-medium px-1.5 py-0.5 rounded bg-gray-100 text-[#1d1d1f]">
                                      {getEntityTypeName(entity.type)}
                                    </span>
                                    <span className="text-2xs text-[#a3a3a3]">
                                      {entity.source === 'regex' ? '正则' : entity.source === 'manual' ? '手动' : 'AI'}
                                    </span>
                                  </div>
                                  <p className="text-md truncate text-[#1d1d1f]">
                                    {entity.text}
                                  </p>
                                </div>
                                <button
                                  onClick={e => { e.stopPropagation(); removeEntity(entity.id); }}
                                  className="p-1 text-[#d4d4d4] hover:text-violet-600 flex-shrink-0"
                                >
                                  <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                                  </svg>
                                </button>
                              </div>
                            );
                          })}
                        </div>
                      );
                    })
                  )
                )}
              </div>
            </div>

            {/* 操作按钮 */}
            <button
              onClick={handleRedact}
              disabled={selectedCount === 0}
                  className={`py-3 rounded-xl text-md font-semibold flex items-center justify-center gap-2 transition-all ${
                selectedCount > 0
                  ? 'bg-black text-white hover:bg-zinc-900'
                  : 'bg-[#f0f0f0] text-[#a3a3a3] cursor-not-allowed'
              }`}
            >
              开始脱敏 ({selectedCount})
            </button>
          </div>
        </div>
      )}

      {/* 结果阶段 */}
      {stage === 'result' && (() => {
        // 共享分段：按 entityMap keys 把原文切段，每段记录 { origKey, matchIdx }
        const buildSegments = (text: string, map: Record<string, string>) => {
          if (!text || Object.keys(map).length === 0) return [{ text, isMatch: false as const }];
          const sortedKeys = Object.keys(map).sort((a, b) => b.length - a.length);
          const regex = new RegExp(`(${sortedKeys.map(k => k.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')})`, 'g');
          const parts = text.split(regex);
          const counters: Record<string, number> = {};
          return parts.map(part => {
            if (map[part] !== undefined) {
              const safeKey = part.replace(/[^a-zA-Z0-9\u4e00-\u9fff]/g, '_');
              const idx = counters[safeKey] || 0;
              counters[safeKey] = idx + 1;
              return { text: part, isMatch: true as const, origKey: part, safeKey, matchIdx: idx };
            }
            return { text: part, isMatch: false as const };
          });
        };

        const segments = buildSegments(content, entityMap);

        /** 原文片段 → 实体类型（与 ENTITY_PALETTE 四套统一色一致） */
        const origToTypeId = new Map<string, string>();
        for (const e of entities) {
          if (!e.selected) continue;
          if (entityMap[e.text] === undefined) continue;
          const tid = String(e.type);
          origToTypeId.set(e.text, tid);
          if (typeof e.start === 'number' && typeof e.end === 'number' && e.end <= (content || '').length) {
            const sl = (content || '').slice(e.start, e.end);
            if (sl && sl !== e.text) origToTypeId.set(sl, tid);
          }
        }

        const markStyleForOrig = (origKey: string): React.CSSProperties => {
          const tid = origToTypeId.get(origKey) ?? '';
          const cfg = getEntityRiskConfig(tid || 'CUSTOM');
          return {
            backgroundColor: cfg.bgColor,
            color: cfg.textColor,
            boxShadow: `inset 0 -2px 0 ${cfg.color}55`,
          };
        };

        const renderOriginal = () => (
          <>{segments.map((seg, i) =>
            seg.isMatch
              ? <mark key={i} data-match-key={seg.safeKey} data-match-idx={seg.matchIdx}
                  style={markStyleForOrig(seg.origKey)}
                  className="result-mark-orig px-0.5 rounded-md transition-all duration-300">{seg.text}</mark>
              : <span key={i}>{seg.text}</span>
          )}</>
        );

        const renderRedacted = () => (
          <>{segments.map((seg, i) =>
            seg.isMatch
              ? <mark key={i} data-match-key={seg.safeKey} data-match-idx={seg.matchIdx}
                  style={markStyleForOrig(seg.origKey)}
                  className="result-mark-redacted px-0.5 rounded-md transition-all duration-300">{entityMap[seg.origKey]}</mark>
              : <span key={i}>{seg.text}</span>
          )}</>
        );
        // 每个映射项的点击计数器（循环切换出现位置）
        const clickCounterRef: Record<string, number> = {};
        // 点击映射项 → 两列同时滚动到第N次出现
        const scrollToMatch = (orig: string, _repl: string) => {
          const safeKey = orig.replace(/[^a-zA-Z0-9\u4e00-\u9fff]/g, '_');
          // 查找所有匹配的原文标记
          const origMarks = document.querySelectorAll(`.result-mark-orig[data-match-key="${safeKey}"]`);
          const redactedMarks = document.querySelectorAll(`.result-mark-redacted[data-match-key="${safeKey}"]`);
          const total = Math.max(origMarks.length, redactedMarks.length);
          if (total === 0) return;
          // 循环索引
          const idx = (clickCounterRef[safeKey] || 0) % total;
          clickCounterRef[safeKey] = idx + 1;
          // 清除所有旧高亮
          document.querySelectorAll('.result-mark-active').forEach(el => {
            el.classList.remove('result-mark-active', 'ring-2', 'ring-offset-1', 'ring-blue-400/80', 'scale-105');
          });
          // 滚动原文
          const origEl = origMarks[Math.min(idx, origMarks.length - 1)] as HTMLElement;
          if (origEl) {
            origEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
            origEl.classList.add('result-mark-active', 'ring-2', 'ring-offset-1', 'ring-blue-400/80', 'scale-105');
          }
          // 滚动脱敏结果
          const redEl = redactedMarks[Math.min(idx, redactedMarks.length - 1)] as HTMLElement;
          if (redEl) {
            redEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
            redEl.classList.add('result-mark-active', 'ring-2', 'ring-offset-1', 'ring-blue-400/80', 'scale-105');
          }
          // 2秒后清除
          setTimeout(() => {
            document.querySelectorAll('.result-mark-active').forEach(el => {
              el.classList.remove('result-mark-active', 'ring-2', 'ring-offset-1', 'ring-blue-400/80', 'scale-105');
            });
          }, 2500);
        };
        
        return (
        <div className="flex-1 flex flex-col min-h-0 min-w-0 overflow-hidden">
          {/* 顶部状态栏 */}
          <div className="flex-shrink-0 mx-3 sm:mx-4 mt-3 sm:mt-4 mb-2 sm:mb-3">
            <div className="bg-black rounded-2xl px-6 py-4 flex items-center justify-between shadow-md shadow-black/25">
              <div className="flex items-center gap-4">
                <div className="w-10 h-10 rounded-xl bg-white/15 flex items-center justify-center">
                  <svg className="w-5 h-5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
                  </svg>
                </div>
                <div>
                  <p className="text-white text-sm font-semibold">脱敏完成</p>
                  <p className="text-white/70 text-xs">{redactedCount} 处敏感信息已处理</p>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <button onClick={() => setStage('preview')} className="px-3 py-1.5 text-xs text-white/90 hover:text-white bg-white/15 hover:bg-white/25 rounded-lg transition-all">返回编辑</button>
                <button onClick={handleReset} className="px-3 py-1.5 text-xs text-white/90 hover:text-white bg-white/15 hover:bg-white/25 rounded-lg transition-all">新文件</button>
                {fileInfo && (
                  <a href={`/api/v1/files/${fileInfo.file_id}/download?redacted=true`} download className="px-4 py-1.5 text-xs font-medium text-black bg-white hover:bg-zinc-200 rounded-lg transition-all">下载文件</a>
                )}
              </div>
            </div>
          </div>

          {/* 三列主体 */}
          {isImageMode ? (
            <div className="flex-1 flex gap-2 sm:gap-3 px-3 sm:px-4 pb-3 sm:pb-4 min-h-0 min-w-0">
              {/* 左：原始图片 */}
              <div className="flex-1 min-w-0 bg-white rounded-2xl border border-gray-200/80 flex flex-col overflow-hidden">
                <div className="flex-shrink-0 px-4 py-2.5 border-b border-gray-100 flex items-center gap-2">
                  <span className="text-xs font-semibold text-[#1d1d1f] tracking-tight">原始图片</span>
                </div>
                <div className="flex-1 overflow-auto p-3">
                  {fileInfo && (
                    <ImageBBoxEditor
                      imageSrc={`/api/v1/files/${fileInfo.file_id}/download`}
                      boxes={visibleBoxes}
                      onBoxesChange={(newBoxes) => setBoundingBoxes(mergeVisibleBoxes(newBoxes))}
                      onBoxesCommit={(prevBoxes, nextBoxes) => {
                        setImageUndoStack(prev => [...prev, mergeVisibleBoxes(prevBoxes, nextBoxes)]);
                        setImageRedoStack([]);
                        setBoundingBoxes(mergeVisibleBoxes(nextBoxes, prevBoxes));
                      }}
                      getTypeConfig={getVisionTypeConfig}
                      availableTypes={visionTypes.map(t => ({ id: t.id, name: t.name, color: '#6366F1' }))}
                      defaultType={visionTypes[0]?.id || 'CUSTOM'}
                    />
                  )}
                </div>
              </div>
              {/* 中：脱敏后图片 */}
              <div className="flex-1 min-w-0 bg-white rounded-2xl border border-gray-200/80 flex flex-col overflow-hidden">
                <div className="flex-shrink-0 px-4 py-2.5 border-b border-gray-100 flex items-center gap-2">
                  <span className="text-xs font-semibold text-[#1d1d1f] tracking-tight">脱敏结果</span>
                </div>
                <div className="flex-1 overflow-auto p-3">
                  {fileInfo && <img src={`/api/v1/files/${fileInfo.file_id}/download?redacted=true`} alt="redacted" className="max-w-full h-auto object-contain" />}
                </div>
              </div>
              {/* 右：映射表 */}
              <div className="w-52 sm:w-60 flex-shrink-0 bg-white rounded-2xl border border-gray-200/80 flex flex-col overflow-hidden min-h-0 min-w-0">
                <div className="flex-shrink-0 px-4 py-2.5 border-b border-gray-100 flex items-center justify-between">
                  <span className="text-xs font-semibold text-[#1d1d1f] tracking-tight">脱敏记录</span>
                  <span className="text-2xs text-[#a3a3a3] tabular-nums">{Object.keys(entityMap).length}</span>
                </div>
                <div className="flex-1 overflow-auto">
                  {Object.entries(entityMap).map(([orig, repl], i) => {
                    const cfg = getEntityRiskConfig(origToTypeId.get(orig) ?? 'CUSTOM');
                    return (
                      <button
                        key={i}
                        onClick={() => scrollToMatch(orig, repl)}
                        className="w-full text-left px-3 py-2.5 mx-1.5 my-1.5 rounded-xl border border-black/[0.06] shadow-sm shadow-violet-900/5 hover:brightness-[0.99] transition-all"
                        style={{ borderLeft: `3px solid ${cfg.color}`, backgroundColor: cfg.bgColor }}
                      >
                        <div className="text-caption font-medium truncate" style={{ color: cfg.textColor }}>{orig}</div>
                        <div className="flex items-center gap-1.5 mt-0.5">
                          <svg className="w-2.5 h-2.5 opacity-40 flex-shrink-0" style={{ color: cfg.color }} fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 8l4 4m0 0l-4 4m4-4H3" /></svg>
                          <span className="text-caption truncate opacity-90" style={{ color: cfg.textColor }}>{repl}</span>
                        </div>
                      </button>
                    );
                  })}
                  {Object.keys(entityMap).length === 0 && <p className="text-xs text-[#a3a3a3] text-center py-6">暂无记录</p>}
                </div>
              </div>
            </div>
          ) : (
            <div className="flex-1 flex gap-2 sm:gap-3 px-3 sm:px-4 pb-3 sm:pb-4 min-h-0 min-w-0">
              {/* 左：原始文档 */}
              <div className="flex-1 min-w-0 bg-white rounded-2xl border border-gray-200/80 flex flex-col overflow-hidden">
                <div className="flex-shrink-0 px-4 py-2.5 border-b border-gray-100 flex items-center gap-2">
                  <span className="text-xs font-semibold text-[#1d1d1f] tracking-tight">原始文档</span>
                </div>
                <div className="flex-1 overflow-auto p-4" id="original-scroll">
                  <div className="text-sm leading-relaxed text-[#262626] whitespace-pre-wrap font-[system-ui]">
                    {renderOriginal()}
                  </div>
                </div>
              </div>
              {/* 中：脱敏后文档 */}
              <div className="flex-1 min-w-0 bg-white rounded-2xl border border-gray-200/80 flex flex-col overflow-hidden">
                <div className="flex-shrink-0 px-4 py-2.5 border-b border-gray-100 flex items-center gap-2">
                  <span className="text-xs font-semibold text-[#1d1d1f] tracking-tight">脱敏结果</span>
                </div>
                <div className="flex-1 overflow-auto p-4" id="redacted-scroll">
                  <div className="text-sm leading-relaxed text-[#262626] whitespace-pre-wrap font-[system-ui]">
                    {renderRedacted()}
                  </div>
                </div>
              </div>
              {/* 右：映射列表 */}
              <div className="w-64 flex-shrink-0 bg-white rounded-2xl border border-gray-200/80 flex flex-col overflow-hidden">
                <div className="flex-shrink-0 px-4 py-2.5 border-b border-gray-100 flex items-center justify-between">
                  <span className="text-xs font-semibold text-[#1d1d1f] tracking-tight">脱敏记录</span>
                  <span className="text-2xs text-[#a3a3a3] tabular-nums">{Object.keys(entityMap).length}</span>
                </div>
                <div className="flex-1 overflow-auto">
                  {Object.entries(entityMap).map(([orig, repl], i) => {
                    const count = (content || '').split(orig).length - 1;
                    const cfg = getEntityRiskConfig(origToTypeId.get(orig) ?? 'CUSTOM');
                    return (
                      <button
                        key={i}
                        onClick={() => scrollToMatch(orig, repl)}
                        className="w-full text-left px-3 py-2.5 mx-1.5 my-1.5 rounded-xl border border-black/[0.06] shadow-sm shadow-violet-900/5 hover:brightness-[0.99] transition-all"
                        style={{ borderLeft: `3px solid ${cfg.color}`, backgroundColor: cfg.bgColor }}
                      >
                        <div className="flex items-center gap-1.5">
                          <span className="text-caption font-medium truncate flex-1" style={{ color: cfg.textColor }}>{orig}</span>
                          {count > 1 && (
                            <span
                              className="text-2xs rounded px-1 flex-shrink-0 tabular-nums"
                              style={{ backgroundColor: `${cfg.color}22`, color: cfg.textColor }}
                            >
                              {count}处
                            </span>
                          )}
                        </div>
                        <div className="flex items-center gap-1.5 mt-0.5">
                          <svg className="w-2.5 h-2.5 opacity-40 flex-shrink-0" style={{ color: cfg.color }} fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 8l4 4m0 0l-4 4m4-4H3" /></svg>
                          <span className="text-caption truncate opacity-90" style={{ color: cfg.textColor }}>{repl}</span>
                        </div>
                      </button>
                    );
                  })}
                  {Object.keys(entityMap).length === 0 && <p className="text-xs text-[#a3a3a3] text-center py-8">暂无记录</p>}
                </div>
              </div>
            </div>
          )}
        </div>
        );
      })()}

      {/* Loading */}
      {isLoading && (
        <div className="fixed inset-0 bg-black/40 backdrop-blur-sm z-50 flex items-center justify-center">
          <div className="bg-white rounded-2xl shadow-2xl px-8 py-6 text-center max-w-sm">
            <div className="w-12 h-12 border-3 border-gray-600 border-t-transparent rounded-full animate-spin mx-auto mb-4" />
            <p className="text-base font-medium text-[#1d1d1f] mb-1">{loadingMessage || '处理中...'}</p>
            {isImageMode ? (
              <>
                <p className="text-xs text-[#737373] leading-relaxed">
                  仅勾选「文字 OCR+HaS」时才会跑 Paddle；只勾选「HaS Image」则不走 OCR。
                  若含 OCR+HaS，<strong className="font-medium text-[#1d1d1f]">CPU 跑 Paddle 时常需 30–90 秒甚至更久</strong>
                  ，等待较久为正常现象，请勿刷新。
                </p>
                {loadingElapsedSec > 0 && (
                  <p className="text-xs text-[#737373] mt-2 tabular-nums">已等待 {loadingElapsedSec} 秒…</p>
                )}
              </>
            ) : (
              <p className="text-xs text-[#a3a3a3]">处理中，请稍候</p>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

export default Playground;
