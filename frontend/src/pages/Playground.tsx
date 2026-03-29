import React, { useState, useCallback, useEffect, useLayoutEffect, useRef, useMemo } from 'react';
import { useUndoRedo } from '../hooks/useUndoRedo';

/** 安全解析 JSON 响应，遇到非 JSON 内容时抛出可读错误 */
async function safeJson<T = any>(res: Response): Promise<T> {
  try {
    return await res.json();
  } catch {
    throw new Error('服务端返回了非 JSON 响应');
  }
}
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
import { showToast } from '../components/Toast';
import ImageBBoxEditor from '../components/ImageBBoxEditor';
import { EntityTypeGroupPicker } from '../components/EntityTypeGroupPicker';
import {
  getEntityTypeName,
  getEntityGroup,
  ENTITY_GROUPS,
} from '../config/entityTypes';
import {
  selectableCheckboxClass,
  type SelectionVariant,
} from '../ui/selectionClasses';
import { PlaygroundUpload } from './PlaygroundUpload';
import { PlaygroundResult } from './PlaygroundResult';
import type {
  FileInfo,
  Entity,
  BoundingBox,
  EntityTypeConfig,
  VisionTypeConfig,
  PipelineConfig,
  Stage,
} from './playground-types';

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

// Types imported from './playground-types'

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
const VISION_FETCH_TIMEOUT_MS = 400000; // 400s > 后端 OCR_TIMEOUT 360s

async function runVisionDetection(
  fileId: string,
  ocrHasTypes: string[],
  hasImageTypes: string[]
): Promise<{ boxes: BoundingBox[]; resultImage?: string }> {
  if (import.meta.env.DEV) {
    console.log('[Vision] 发送识别请求:', { ocrHasTypes, hasImageTypes });
  }

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

  const data = await safeJson(res);
  const boxes = (data.bounding_boxes || []).map((b: any, idx: number) => ({
    ...b,
    id: b.id || `bbox_${idx}`,
    selected: true,
  }));
  return { boxes, resultImage: data.result_image };
}

function getModePreview(mode: string, sampleEntity?: Entity) {
  const name = sampleEntity?.text || '张三';
  switch (mode) {
    case 'smart':
      return `${name} → [当事人一]`;
    case 'mask':
      return `${name} → ${name[0]}${'*'.repeat(Math.max(name.length - 1, 1))}`;
    case 'structured':
      return `${name} → <人物[001].个人.姓名>`;
    default:
      return '';
  }
}

async function authBlobUrl(url: string, mime?: string): Promise<string> {
  const token = localStorage.getItem('auth_token');
  if (!token) return url;
  const res = await fetch(url, { headers: { Authorization: `Bearer ${token}` } });
  if (!res.ok) {
    throw new Error(`加载文件失败: ${res.status}`);
  }
  const buf = await res.arrayBuffer();
  const blob = mime ? new Blob([buf], { type: mime }) : new Blob([buf]);
  return URL.createObjectURL(blob);
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
  const [redactionReport, setRedactionReport] = useState<any>(null);
  const [reportOpen, setReportOpen] = useState(false);
  const [versionHistory, setVersionHistory] = useState<any[]>([]);
  const [versionHistoryOpen, setVersionHistoryOpen] = useState(false);

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
  const abortRef = useRef<AbortController | null>(null);
  const entityHistory = useUndoRedo<Entity[]>();
  const imageHistory = useUndoRedo<BoundingBox[]>();
  const [_imageRenderSize, setImageRenderSize] = useState<{ width: number; height: number }>({ width: 0, height: 0 });
  const [_imageNaturalSize, setImageNaturalSize] = useState<{ width: number; height: number }>({ width: 0, height: 0 });
  const [_resultImage, setResultImage] = useState<string | null>(null);

  // 组件卸载时中止进行中的请求
  useEffect(() => {
    return () => { abortRef.current?.abort(); };
  }, []);

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
      const data = await safeJson(res);
      const types = data.custom_types || [];
      setEntityTypes(types);
      setSelectedTypes(types.map((t: EntityTypeConfig) => t.id));
    } catch (err) {
      if (import.meta.env.DEV) {
        console.error('获取实体类型失败', err);
      }
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
      const data: PipelineConfig[] = await safeJson<PipelineConfig[]>(res);
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
      if (import.meta.env.DEV) {
        console.error('获取图像类型失败', err);
      }
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
    entityHistory.save(entities);
    setEntities(next);
  };

  const undo = () => {
    const prev = entityHistory.undo(entities);
    if (prev) setEntities(prev);
  };

  const redo = () => {
    const next = entityHistory.redo(entities);
    if (next) setEntities(next);
  };

  const undoImage = useCallback(() => {
    const prev = imageHistory.undo(boundingBoxes);
    if (prev) setBoundingBoxes(prev);
  }, [boundingBoxes, imageHistory]);

  const redoImage = useCallback(() => {
    const next = imageHistory.redo(boundingBoxes);
    if (next) setBoundingBoxes(next);
  }, [boundingBoxes, imageHistory]);

  // Toast - now using shared React-based toast via imported showToast

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
      formData.append('upload_source', 'playground');

      const uploadRes = await fetch('/api/v1/files/upload', { method: 'POST', body: formData });
      if (!uploadRes.ok) throw new Error('文件上传失败');
      const uploadData = await safeJson(uploadRes);
      
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
      const parseData = await safeJson(parseRes);
      
      const isScanned = parseData.is_scanned || false;
      const parsedContent = parseData.content || '';
      
      // 更新状态
      setFileInfo({ ...newFileInfo, is_scanned: isScanned });
      setContent(parsedContent);
      setBoundingBoxes([]);
      imageHistory.reset();
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

    // 中止前一次请求（如有），创建新的 AbortController
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    const { signal } = controller;
    
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

          if (import.meta.env.DEV) {
            console.log('[Recognition] 图像模式，开始识别');
            console.log('[Recognition] OCR+HaS 类型:', ocrTypes);
            console.log('[Recognition] HaS Image 类型:', hiTypes);
          }
          
          const result = await runVisionDetection(fileId, ocrTypes, hiTypes);
          if (signal.aborted) return;

          setBoundingBoxes(result.boxes);
          imageHistory.reset();
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
            signal,
          });
          if (signal.aborted) return;

          if (nerRes.ok) {
            const nerData = await safeJson(nerRes);
            const entitiesWithSource = (nerData.entities || []).map((e: any, idx: number) => ({
              ...e,
              id: e.id || `entity_${idx}`,
              selected: true,
              source: e.source || 'llm',
            }));
            setEntities(entitiesWithSource);
            entityHistory.reset();
            showToast(`识别到 ${entitiesWithSource.length} 处敏感信息`, 'success');
          }
        }
        if (signal.aborted) return;

        setStage('preview');
      } catch (err) {
        if (signal.aborted) return;
        showToast(err instanceof Error ? err.message : '识别失败', 'error');
      } finally {
        if (!signal.aborted) {
          setIsLoading(false);
          setLoadingMessage('');
        }
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
    disabled: isLoading,
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
        if (import.meta.env.DEV) {
          console.log('[Rerun] OCR+HaS 类型:', selectedOcrHasTypes);
          console.log('[Rerun] HaS Image 类型:', selectedHasImageTypes);
        }
        
        const result = await runVisionDetection(
          fileInfo.file_id,
          selectedOcrHasTypes,
          selectedHasImageTypes
        );
        
        setBoundingBoxes(result.boxes);
        imageHistory.reset();
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
        const nerData = await safeJson(nerRes);
        const entitiesWithSource = (nerData.entities || []).map((e: any, idx: number) => ({
          ...e,
          id: e.id || `entity_${idx}`,
          selected: true,
          source: e.source || 'llm',
        }));
        setEntities(entitiesWithSource);
        entityHistory.reset();
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

      const result = await safeJson(res);
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
      // Fetch redaction quality report
      fetch(`/api/v1/redaction/${fileInfo!.file_id}/report`)
        .then(r => r.json())
        .then(data => setRedactionReport(data))
        .catch(() => setRedactionReport(null));
      // Fetch version history
      fetch(`/api/v1/redaction/${fileInfo!.file_id}/versions`)
        .then(r => r.json())
        .then(data => setVersionHistory(data.versions || []))
        .catch(() => setVersionHistory([]));
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
    setRedactionReport(null);
    setReportOpen(false);
    selectionRangeRef.current = null;
    setSelectedText(null);
    setSelectionPos(null);
    setSelectedOverlapIds([]);
    entityHistory.reset();
    setBoundingBoxes([]);
    imageHistory.reset();
    setResultImage(null);
  };

  const isImageMode = !!fileInfo && (fileInfo.file_type === 'image' || !!fileInfo.is_scanned);

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

  const imageUrlRaw = fileInfo ? `/api/v1/files/${fileInfo.file_id}/download` : '';
  const [imageUrl, setImageUrl] = useState('');
  const [redactedImageUrl, setRedactedImageUrl] = useState('');
  useEffect(() => {
    let cancelled = false;
    if (!imageUrlRaw) { setImageUrl(''); return; }
    authBlobUrl(imageUrlRaw).then(u => { if (!cancelled) setImageUrl(u); }).catch(() => { if (!cancelled) setImageUrl(imageUrlRaw); });
    return () => { cancelled = true; };
  }, [imageUrlRaw]);
  useEffect(() => {
    let cancelled = false;
    if (!fileInfo) { setRedactedImageUrl(''); return; }
    const raw = `/api/v1/files/${fileInfo.file_id}/download?redacted=true`;
    authBlobUrl(raw).then(u => { if (!cancelled) setRedactedImageUrl(u); }).catch(() => { if (!cancelled) setRedactedImageUrl(raw); });
    return () => { cancelled = true; };
  }, [fileInfo]);
  const canUndo = isImageMode ? imageHistory.canUndo : entityHistory.canUndo;
  const canRedo = isImageMode ? imageHistory.canRedo : entityHistory.canRedo;
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

  // Keyboard shortcuts: Ctrl+A select all, Escape deselect all
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      // Don't trigger shortcuts when typing in inputs
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;

      // Ctrl+A / Cmd+A: select all entities (prevent default text selection)
      if ((e.ctrlKey || e.metaKey) && e.key === 'a') {
        e.preventDefault();
        selectAll();
      }
      // Escape: deselect all entities
      if (e.key === 'Escape') {
        deselectAll();
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, []);

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
    <div className="playground-root h-full min-h-0 min-w-0 flex flex-col overflow-hidden bg-[#f5f5f7]">
      {/* 上传阶段 */}
      {stage === 'upload' && (
        <PlaygroundUpload
          getRootProps={getRootProps}
          getInputProps={getInputProps}
          isDragActive={isDragActive}
          typeTab={typeTab}
          setTypeTab={setTypeTab}
          entityTypes={entityTypes}
          selectedTypes={selectedTypes}
          setSelectedTypes={setSelectedTypes}
          visionTypes={visionTypes}
          pipelines={pipelines}
          selectedOcrHasTypes={selectedOcrHasTypes}
          selectedHasImageTypes={selectedHasImageTypes}
          toggleVisionType={toggleVisionType}
          updateOcrHasTypes={updateOcrHasTypes}
          updateHasImageTypes={updateHasImageTypes}
          textPresetsPg={textPresetsPg}
          visionPresetsPg={visionPresetsPg}
          playgroundPresetTextId={playgroundPresetTextId}
          playgroundPresetVisionId={playgroundPresetVisionId}
          selectPlaygroundTextPresetById={selectPlaygroundTextPresetById}
          selectPlaygroundVisionPresetById={selectPlaygroundVisionPresetById}
          saveTextPresetFromPlayground={saveTextPresetFromPlayground}
          saveVisionPresetFromPlayground={saveVisionPresetFromPlayground}
          clearPlaygroundTextPresetTracking={clearPlaygroundTextPresetTracking}
          clearPlaygroundVisionPresetTracking={clearPlaygroundVisionPresetTracking}
          sortedEntityTypes={sortedEntityTypes}
          playgroundTextGroups={playgroundTextGroups}
          setPlaygroundTextTypeGroupSelection={setPlaygroundTextTypeGroupSelection}
        />
      )}
      {/* 预览编辑阶段 */}
      {stage === 'preview' && (
        <div className="flex-1 flex gap-2 sm:gap-3 p-2 sm:p-3 min-h-0 min-w-0 overflow-hidden">
          {/* 文档内容 - 占满中间区域 */}
          <div className="playground-editor-surface flex-1 flex flex-col bg-white rounded-xl border border-gray-200 overflow-hidden min-w-0">
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
                    type="button"
                    onClick={() => {
                      // 弹出新窗口查看大图 — 使用 DOM API 替代 document.write 避免 XSS 风险
                      const w = window.open('', '_blank', 'width=1200,height=800,scrollbars=yes,resizable=yes');
                      if (!w) return;
                      const doc = w.document;
                      doc.title = `图像查看 - ${fileInfo?.filename || '未命名'}`;

                      const style = doc.createElement('style');
                      style.textContent = `
                        * { margin: 0; padding: 0; box-sizing: border-box; }
                        body { font-family: system-ui, -apple-system, sans-serif; background: #1a1a1a; }
                        .container { width: 100vw; height: 100vh; display: flex; align-items: center; justify-content: center; padding: 20px; }
                        img { max-width: 100%; max-height: 100%; object-fit: contain; border-radius: 8px; box-shadow: 0 4px 20px rgba(0,0,0,0.5); }
                        .hint { position: fixed; bottom: 20px; left: 50%; transform: translateX(-50%); background: rgba(255,255,255,0.9); padding: 8px 16px; border-radius: 20px; font-size: 12px; color: #333; }
                      `;
                      doc.head.appendChild(style);

                      const container = doc.createElement('div');
                      container.className = 'container';
                      const img = doc.createElement('img');
                      img.src = imageUrl || '';
                      img.alt = '查看图像';
                      container.appendChild(img);
                      doc.body.appendChild(container);

                      const hint = doc.createElement('div');
                      hint.className = 'hint';
                      hint.textContent = '在此窗口查看大图，编辑请在主窗口进行';
                      doc.body.appendChild(hint);
                    }}
                    className="text-xs text-[#737373] hover:text-[#1d1d1f] px-2 py-1 rounded hover:bg-[#f5f5f5]"
                    title="在新窗口中查看大图"
                    aria-label="在新窗口中查看大图"
                  >
                    新窗口
                  </button>
                )}
                <button
                  onClick={handleUndo}
                  disabled={!canUndo}
                  className="text-xs px-2 py-1 rounded hover:bg-gray-100 disabled:opacity-30 disabled:cursor-not-allowed"
                  title="撤销 (Ctrl+Z)"
                  aria-label="撤销"
                >
                  ↩ 撤销
                </button>
                <button
                  onClick={handleRedo}
                  disabled={!canRedo}
                  className="text-xs px-2 py-1 rounded hover:bg-gray-100 disabled:opacity-30 disabled:cursor-not-allowed"
                  title="重做 (Ctrl+Y)"
                  aria-label="重做"
                >
                  ↪ 重做
                </button>
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
                        imageHistory.save(prevAll);
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
                  className="playground-floating-card fixed z-50 bg-white border border-gray-200 rounded-2xl shadow-2xl p-4 min-w-[320px] max-w-[400px]"
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
                    <EntityTypeGroupPicker
                      entityTypes={entityTypes}
                      selectedTypeId={selectedTypeId}
                      onSelectType={setSelectedTypeId}
                    />
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
                  className="playground-floating-card fixed z-50 bg-white border border-gray-200 rounded-xl shadow-2xl p-3 min-w-[200px]"
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
            <div className="playground-side-card bg-white/95 rounded-2xl border border-black/[0.06] shadow-[0_2px_12px_rgba(0,0,0,0.05)] p-3">
              <div className="flex flex-col gap-2 min-w-0">
                <button
                  type="button"
                  onClick={handleRerunNer}
                  disabled={isLoading}
                  className={`w-full text-xs font-medium bg-black text-white rounded-lg py-2.5 px-2 hover:bg-zinc-900 transition-colors ${isLoading ? 'opacity-50 cursor-not-allowed' : ''}`}
                >
                  {isLoading ? '识别中...' : '重新识别'}
                </button>
                <p className="text-2xs text-[#a3a3a3] leading-snug break-words">
                  类型与预设请在「识别项配置」或上传页选择；此处仅重新跑识别。
                </p>
              </div>
            </div>

            {/* 交互说明 */}
            <div className="playground-side-hint bg-gradient-to-br from-gray-50 to-white rounded-xl border border-[#e5e5e5] p-3">
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
                    {(() => {
                      const sampleEntity = entities.find(e => e.text && e.text.length > 0);
                      const modes: { value: 'structured' | 'smart' | 'mask'; label: string; badge?: string }[] = [
                        { value: 'structured', label: '结构化语义标签', badge: '推荐' },
                        { value: 'smart', label: '智能替换' },
                        { value: 'mask', label: '掩码替换' },
                      ];
                      return (
                        <div className="space-y-1.5">
                          {modes.map(m => (
                            <label
                              key={m.value}
                              className={`flex flex-col px-3 py-2 rounded-lg border cursor-pointer transition-colors ${
                                replacementMode === m.value
                                  ? 'border-[#1d1d1f] bg-[#fafafa]'
                                  : 'border-[#e5e5e5] bg-white hover:border-[#d4d4d4]'
                              }`}
                            >
                              <div className="flex items-center gap-2">
                                <input
                                  type="radio"
                                  name="replacementMode"
                                  value={m.value}
                                  checked={replacementMode === m.value}
                                  onChange={() => {
                                    clearPlaygroundTextPresetTracking();
                                    setReplacementMode(m.value);
                                  }}
                                  className="accent-[#1d1d1f]"
                                />
                                <span className="text-sm font-medium text-[#1d1d1f]">{m.label}</span>
                                {m.badge && (
                                  <span className="text-2xs px-1.5 py-0.5 rounded bg-[#1d1d1f] text-white leading-none">{m.badge}</span>
                                )}
                              </div>
                              <span className="text-2xs text-[#a3a3a3] mt-0.5 font-mono ml-6">
                                {getModePreview(m.value, sampleEntity)}
                              </span>
                            </label>
                          ))}
                        </div>
                      );
                    })()}
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
                                  aria-label="移除此标注"
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
              disabled={selectedCount === 0 || isLoading}
                  className={`py-3 rounded-xl text-md font-semibold flex items-center justify-center gap-2 transition-all ${
                selectedCount > 0 && !isLoading
                  ? 'bg-black text-white hover:bg-zinc-900'
                  : 'bg-[#f0f0f0] text-[#a3a3a3] cursor-not-allowed'
              } ${isLoading ? 'opacity-50' : ''}`}
            >
              {isLoading ? '处理中...' : `开始脱敏 (${selectedCount})`}
            </button>
          </div>
        </div>
      )}

      {/* 结果阶段 */}
      {stage === 'result' && (
        <PlaygroundResult
          fileInfo={fileInfo}
          content={content}
          entities={entities}
          entityMap={entityMap}
          redactedCount={redactedCount}
          redactionReport={redactionReport}
          reportOpen={reportOpen}
          setReportOpen={setReportOpen}
          versionHistory={versionHistory}
          versionHistoryOpen={versionHistoryOpen}
          setVersionHistoryOpen={setVersionHistoryOpen}
          isImageMode={isImageMode}
          imageUrl={imageUrl}
          boundingBoxes={boundingBoxes}
          visibleBoxes={visibleBoxes}
          visionTypes={visionTypes}
          getVisionTypeConfig={getVisionTypeConfig}
          replacementMode={replacementMode}
          redactedImageUrl={redactedImageUrl}
          onBackToEdit={() => setStage('preview')}
          onReset={handleReset}
        />
      )}

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
