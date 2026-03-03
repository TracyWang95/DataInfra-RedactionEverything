import React, { useState, useCallback, useEffect, useRef } from 'react';
import { useDropzone } from 'react-dropzone';
import ImageBBoxEditor from '../components/ImageBBoxEditor';
import {
  getEntityRiskConfig,
  getEntityTypeName,
  getEntityGroup,
  ENTITY_GROUPS,
} from '../config/entityTypes';

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
  source?: 'ocr_has' | 'glm_vision' | 'manual';
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
  mode: 'ocr_has' | 'glm_vision';
  name: string;
  description: string;
  enabled: boolean;
  types: VisionTypeConfig[];
}

type Stage = 'upload' | 'preview' | 'result';

// ============================================================
// 核心函数：执行图像识别
// ============================================================
async function runVisionDetection(
  fileId: string,
  ocrHasTypes: string[],
  glmVisionTypes: string[]
): Promise<{ boxes: BoundingBox[]; resultImage?: string }> {
  console.log('[Vision] 发送识别请求:', { ocrHasTypes, glmVisionTypes });

  const res = await fetch(`/api/v1/redaction/${fileId}/vision?page=1`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      selected_ocr_has_types: ocrHasTypes,
      selected_glm_vision_types: glmVisionTypes,
    }),
  });

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
  const [redactedContent, setRedactedContent] = useState('');
  const [redactedCount, setRedactedCount] = useState(0);
  const [entityMap, setEntityMap] = useState<Record<string, string>>({});

  // 实体类型配置
  const [entityTypes, setEntityTypes] = useState<EntityTypeConfig[]>([]);
  const [selectedTypes, setSelectedTypes] = useState<string[]>([]);
  const [visionTypes, setVisionTypes] = useState<VisionTypeConfig[]>([]);

  // 两个 Pipeline 独立选择 - 使用 ref 确保最新值可用
  const [selectedOcrHasTypes, setSelectedOcrHasTypes] = useState<string[]>([]);
  const [selectedGlmVisionTypes, setSelectedGlmVisionTypes] = useState<string[]>([]);
  const selectedOcrHasTypesRef = useRef(selectedOcrHasTypes);
  const selectedGlmVisionTypesRef = useRef(selectedGlmVisionTypes);

  // 同步更新 ref（立即同步，不等待 useEffect）
  const updateOcrHasTypes = useCallback((types: string[]) => {
    selectedOcrHasTypesRef.current = types;
    setSelectedOcrHasTypes(types);
    localStorage.setItem('ocrHasTypes', JSON.stringify(types));
  }, []);

  const updateGlmVisionTypes = useCallback((types: string[]) => {
    selectedGlmVisionTypesRef.current = types;
    setSelectedGlmVisionTypes(types);
    // 同步保存到 localStorage，解决闭包问题
    localStorage.setItem('glmVisionTypes', JSON.stringify(types));
  }, []);

  const [pipelines, setPipelines] = useState<PipelineConfig[]>([]);
  const [typeTab, setTypeTab] = useState<'text' | 'vision'>('text');
  const [hasMode, setHasMode] = useState<'auto' | 'ner' | 'hide'>('auto');
  const [replacementMode, setReplacementMode] = useState<'structured' | 'smart' | 'mask'>('structured');

  // 划词相关
  const [selectedText, setSelectedText] = useState<{ text: string; start: number; end: number } | null>(null);
  const [selectionPos, setSelectionPos] = useState<{ x: number; y: number } | null>(null);
  const [selectedTypeId, setSelectedTypeId] = useState<string>('');
  const [selectedOverlapIds, setSelectedOverlapIds] = useState<string[]>([]);
  const contentRef = useRef<HTMLDivElement>(null);

  // 点击实体弹出确认框
  const [clickedEntity, setClickedEntity] = useState<Entity | null>(null);
  const [entityPopupPos, setEntityPopupPos] = useState<{ x: number; y: number } | null>(null);
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
        { id: 'ID_CARD', name: '身份证号', color: '#EF4444' },
        { id: 'PHONE', name: '电话号码', color: '#F97316' },
        { id: 'ADDRESS', name: '地址', color: '#6366F1' },
        { id: 'BANK_CARD', name: '银行卡号', color: '#EC4899' },
        { id: 'CASE_NUMBER', name: '案件编号', color: '#8B5CF6' },
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
        p.mode === 'glm_vision'
          ? {
            ...p,
            name: 'GLM Vision',
            description: '使用视觉语言模型识别签名、印章、手写等视觉信息。',
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
              // GLM Vision 默认不选中，用户需手动勾选
            }
          });
        }
      });

      setVisionTypes(allTypes);
      const savedOcrHasTypes = localStorage.getItem('ocrHasTypes');
      if (savedOcrHasTypes) {
        try {
          const parsed = JSON.parse(savedOcrHasTypes);
          updateOcrHasTypes(parsed.filter((id: string) => ocrHasTypeIds.includes(id)));
        } catch {
          updateOcrHasTypes(ocrHasTypeIds);
        }
      } else {
        updateOcrHasTypes(ocrHasTypeIds);
      }
      // GLM 默认不选中，但从 localStorage 恢复用户之前的选择
      const glmTypeIds = normalizedPipelines
        .filter(p => p.mode === 'glm_vision' && p.enabled)
        .flatMap(p => p.types.filter(t => t.enabled).map(t => t.id));
      const savedGlmTypes = localStorage.getItem('glmVisionTypes');
      if (savedGlmTypes) {
        try {
          const parsed = JSON.parse(savedGlmTypes);
          // 过滤掉已不存在的类型ID
          updateGlmVisionTypes(parsed.filter((id: string) => glmTypeIds.includes(id)));
        } catch {
          updateGlmVisionTypes([]);
        }
      } else {
        updateGlmVisionTypes([]);
      }
    } catch (err) {
      console.error('获取图像类型失败', err);
      setVisionTypes([
        { id: 'PERSON', name: '人名/签名', color: '#3B82F6' },
        { id: 'ID_CARD', name: '身份证号', color: '#EF4444' },
        { id: 'PHONE', name: '电话号码', color: '#F97316' },
      ]);
      updateOcrHasTypes(['PERSON', 'ID_CARD', 'PHONE']);
      updateGlmVisionTypes([]);
    }
  };

  const sortedEntityTypes = [...entityTypes].sort((a, b) => {
    const aRegex = a.regex_pattern ? 1 : 0;
    const bRegex = b.regex_pattern ? 1 : 0;
    if (aRegex !== bRegex) return bRegex - aRegex;
    return a.name.localeCompare(b.name);
  });

  const getTypeConfig = (typeId: string): { name: string; color: string } => {
    const config = entityTypes.find(t => t.id === typeId);
    return config || { name: typeId, color: '#6B7280' };
  };

  const getVisionTypeConfig = (typeId: string): { name: string; color: string } => {
    const config = visionTypes.find(t => t.id === typeId);
    return config || { name: typeId, color: '#6B7280' };
  };

  // 切换类型选择
  const toggleVisionType = (typeId: string, pipelineMode: 'ocr_has' | 'glm_vision') => {
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
      const isActive = selectedGlmVisionTypes.includes(typeId);
      const next = isActive
        ? selectedGlmVisionTypes.filter(t => t !== typeId)
        : [...selectedGlmVisionTypes, typeId];
      updateGlmVisionTypes(next);
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
      success: 'bg-green-600',
      error: 'bg-red-600',
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
  const latestGlmVisionTypesRef = useRef(selectedGlmVisionTypes);
  const latestSelectedTypesRef = useRef(selectedTypes);
  const latestHasModeRef = useRef(hasMode);

  // 每次 state 变化时同步更新 ref
  latestOcrHasTypesRef.current = selectedOcrHasTypes;
  latestGlmVisionTypesRef.current = selectedGlmVisionTypes;
  latestSelectedTypesRef.current = selectedTypes;
  latestHasModeRef.current = hasMode;

  useEffect(() => {
    if (!pendingFile) return;

    const { fileId, fileType, isScanned, content } = pendingFile;

    // 立即清除 pendingFile，防止重复触发
    setPendingFile(null);

    const doRecognition = async () => {
      try {
        const isImage = fileType === 'image' || isScanned;

        if (isImage) {
          setLoadingMessage('正在进行图像识别（OCR+HaS & GLM Vision 双路并行）...');

          // 从 localStorage 读取 GLM 类型（最可靠的方式，绕过 React 闭包问题）
          const ocrTypes = latestOcrHasTypesRef.current;
          let glmTypes: string[] = [];
          try {
            const savedGlmTypes = localStorage.getItem('glmVisionTypes');
            if (savedGlmTypes) {
              glmTypes = JSON.parse(savedGlmTypes);
            }
          } catch {
            glmTypes = [];
          }

          console.log('[Recognition] 图像模式，开始识别');
          console.log('[Recognition] OCR+HaS 类型:', ocrTypes);
          console.log('[Recognition] GLM Vision 类型 (from localStorage):', glmTypes);

          const result = await runVisionDetection(fileId, ocrTypes, glmTypes);

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
            body: JSON.stringify({
              entity_type_ids: latestSelectedTypesRef.current,
              has_mode: latestHasModeRef.current
            }),
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
      setSelectedText(null);
      setSelectionPos(null);
      setSelectedOverlapIds([]);
      return;
    }
    if (selection.isCollapsed) {
      if (selectedText && selectionPos) {
        return;
      }
      setSelectedText(null);
      setSelectionPos(null);
      setSelectedOverlapIds([]);
      return;
    }

    const text = selection.toString().trim();
    if (!text || text.length < 2) {
      setSelectedText(null);
      setSelectionPos(null);
      setSelectedOverlapIds([]);
      return;
    }

    const range = selection.getRangeAt(0);
    if (!contentRef.current.contains(range.commonAncestorContainer)) {
      setSelectedText(null);
      setSelectionPos(null);
      setSelectedOverlapIds([]);
      return;
    }

    const offsets = getSelectionOffsets(range, contentRef.current);
    const start = offsets?.start ?? content.indexOf(text);
    const end = offsets?.end ?? (start + text.length);
    if (start < 0 || end < 0) {
      setSelectedText(null);
      setSelectionPos(null);
      setSelectedOverlapIds([]);
      return;
    }

    // 查找重叠的实体
    const overlaps = entities.filter(e =>
      (e.start <= start && e.end > start) || (e.start < end && e.end >= end)
    );

    const rect = range.getBoundingClientRect();
    setSelectionPos({
      x: rect.left + rect.width / 2,
      y: rect.top - 8,
    });
    setSelectedOverlapIds(overlaps.map(e => e.id));

    // 默认类型：如果有重叠实体，使用第一个重叠实体的类型；否则使用上次选择的类型或第一个可用类型
    if (overlaps.length > 0) {
      setSelectedTypeId(overlaps[0].type);
    } else if (!selectedTypeId) {
      const firstType = entityTypes.find(t => selectedTypes.includes(t.id))?.id || entityTypes[0]?.id;
      if (firstType) setSelectedTypeId(firstType);
    }

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

    setSelectedText(null);
    setSelectionPos(null);
    setSelectedOverlapIds([]);
    window.getSelection()?.removeAllRanges();
  };

  const removeSelectedEntities = () => {
    if (selectedOverlapIds.length === 0) return;
    applyEntities(entities.filter(e => !selectedOverlapIds.includes(e.id)));
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
    setLoadingMessage(isImageMode ? '重新识别中（OCR+HaS & GLM Vision 双路并行）...' : '重新识别中（正则+AI语义识别）...');

    try {
      if (isImageMode) {
        console.log('[Rerun] OCR+HaS 类型:', selectedOcrHasTypes);
        console.log('[Rerun] GLM Vision 类型:', selectedGlmVisionTypes);

        const result = await runVisionDetection(
          fileInfo.file_id,
          selectedOcrHasTypes,
          selectedGlmVisionTypes
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
          body: JSON.stringify({ entity_type_ids: selectedTypes, has_mode: hasMode }),
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
      setEntityMap(result.entity_map || {});
      setRedactedCount(result.redacted_count || 0);

      const compareRes = await fetch(`/api/v1/redaction/${fileInfo.file_id}/compare`);
      if (compareRes.ok) {
        const compareData = await compareRes.json();
        setRedactedContent(compareData.redacted_content || '');
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
          handleRedo();
        } else {
          handleUndo();
        }
      } else if (key === 'y') {
        e.preventDefault();
        handleRedo();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [handleRedo, handleUndo]);

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

  const allSelectedVisionTypes = [...selectedOcrHasTypes, ...selectedGlmVisionTypes];
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
    const rect = (event.target as HTMLElement).getBoundingClientRect();
    setEntityPopupPos({
      x: rect.left + rect.width / 2,
      y: rect.top - 8,
    });
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
    if (!content) return <p className="text-gray-400">暂无内容</p>;

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

      // 使用风险等级配色
      const riskConfig = getEntityRiskConfig(entity.type);
      const typeName = getEntityTypeName(entity.type);
      const sourceLabel = entity.source === 'regex' ? '正则' : entity.source === 'manual' ? '手动' : 'AI';

      // 所有实体都显示为高亮状态（点击弹出操作菜单）
      segments.push(
        <span
          key={entity.id}
          onClick={(e) => handleEntityClick(entity, e)}
          className="cursor-pointer transition-all inline-flex items-center gap-0.5 rounded px-0.5 -mx-0.5 hover:ring-2 hover:ring-offset-1 hover:shadow-sm"
          style={{
            backgroundColor: riskConfig.bgColor,
            borderBottom: `2.5px solid ${riskConfig.color}`,
            color: riskConfig.textColor,
          }}
          title={`${riskConfig.icon} ${typeName} [${sourceLabel}] - 点击编辑或移除`}
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
    <div className="h-full flex flex-col bg-gray-50">
      {/* 上传阶段 */}
      {stage === 'upload' && (
        <div className="flex-1 flex gap-6 p-6">
          {/* 上传区域 */}
          <div className="flex-1 flex items-center justify-center">
            <div className="w-full max-w-lg">
              <div
                {...getRootProps()}
                className={`border-2 border-dashed rounded-2xl p-10 text-center cursor-pointer transition-all bg-white ${isDragActive ? 'border-blue-500 bg-blue-50' : 'border-gray-300 hover:border-blue-400'
                  }`}
              >
                <input {...getInputProps()} />
                <div className="w-14 h-14 mx-auto mb-4 rounded-xl bg-blue-100 flex items-center justify-center">
                  <svg className="w-7 h-7 text-blue-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
                  </svg>
                </div>
                <p className="text-base font-medium text-gray-700 mb-1">拖拽文件到此处上传</p>
                <p className="text-sm text-gray-400 mb-4">支持 .doc .docx .pdf .jpg .png</p>
              </div>
            </div>
          </div>

          {/* 类型配置面板 */}
          <div className="w-[300px] bg-white/80 backdrop-blur-xl rounded-2xl border border-gray-200/60 flex flex-col shadow-sm">
            {/* 头部 */}
            <div className="px-4 py-3 border-b border-gray-100/80">
              <div className="flex items-center justify-between">
                <h3 className="text-[13px] font-semibold text-gray-900 tracking-tight">识别类型</h3>
                <div className="flex bg-gray-100 rounded-lg p-0.5">
                  <button onClick={() => setTypeTab('text')} className={`text-[11px] px-2.5 py-1 rounded-md font-medium transition-all ${typeTab === 'text' ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500'}`}>文本</button>
                  <button onClick={() => setTypeTab('vision')} className={`text-[11px] px-2.5 py-1 rounded-md font-medium transition-all ${typeTab === 'vision' ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500'}`}>图像</button>
                </div>
              </div>
              {typeTab === 'text' && (
                <select value={hasMode} onChange={(e) => setHasMode(e.target.value as 'auto' | 'ner' | 'hide')} className="mt-2 w-full text-[11px] border border-gray-200 rounded-lg px-2.5 py-1.5 focus:outline-none focus:ring-1 focus:ring-gray-300 bg-gray-50 cursor-pointer text-gray-600">
                  <option value="auto">自动融合（推荐）</option>
                  <option value="ner">NER 模式</option>
                  <option value="hide">Hide 模式</option>
                </select>
              )}
            </div>

            {/* 内容区 */}
            <div className="flex-1 overflow-auto">
              {typeTab === 'vision' ? (
                pipelines.length === 0 ? (
                  <p className="text-[11px] text-gray-400 text-center py-8">加载中...</p>
                ) : (
                  <div className="p-3 space-y-4">
                    {pipelines.map(pipeline => {
                      const isGlm = pipeline.mode === 'glm_vision';
                      const types = pipeline.types.filter(t => t.enabled);
                      const selectedSet = isGlm ? selectedGlmVisionTypes : selectedOcrHasTypes;
                      const allSelected = types.length > 0 && types.every(t => selectedSet.includes(t.id));

                      const presetGroups = isGlm ? [
                        { label: '视觉元素', ids: ['SIGNATURE', 'FINGERPRINT', 'PHOTO', 'QR_CODE', 'HANDWRITING', 'WATERMARK', 'CHAT_BUBBLE', 'SENSITIVE_TABLE'] },
                      ] : [
                        { label: '个人身份', ids: ['PERSON', 'ID_CARD', 'PASSPORT', 'SOCIAL_SECURITY', 'QQ_WECHAT_ID'] },
                        { label: '联系方式', ids: ['PHONE', 'EMAIL'] },
                        { label: '金融信息', ids: ['BANK_CARD', 'BANK_ACCOUNT', 'BANK_NAME', 'AMOUNT', 'PROPERTY'] },
                        { label: '机构与地址', ids: ['COMPANY', 'ORG', 'ADDRESS'] },
                        { label: '时间与编号', ids: ['BIRTH_DATE', 'DATE', 'LICENSE_PLATE', 'CASE_NUMBER', 'CONTRACT_NO', 'COMPANY_CODE'] },
                        { label: '诉讼参与人', ids: ['LEGAL_PARTY', 'LAWYER', 'JUDGE', 'WITNESS'] },
                        { label: '其他', ids: ['SEAL'] },
                      ];
                      const allPresetIds = new Set(presetGroups.flatMap(g => g.ids));
                      const customTypes = types.filter(t => !allPresetIds.has(t.id));
                      const visionGroups = customTypes.length > 0
                        ? [...presetGroups, { label: '自定义', ids: customTypes.map(t => t.id) }]
                        : presetGroups;

                      return (
                        <div key={pipeline.mode}>
                          <div className={`flex items-center justify-between mb-2.5 pb-1.5 border-b ${isGlm ? 'border-orange-200/60' : 'border-blue-200/60'}`}>
                            <span className={`text-[10px] font-semibold tracking-wider uppercase ${isGlm ? 'text-orange-500' : 'text-blue-500'}`}>
                              {isGlm ? 'GLM Vision' : 'OCR + HaS'}
                            </span>
                            <button onClick={() => {
                              const ids = types.map(t => t.id);
                              if (allSelected) { if (isGlm) updateGlmVisionTypes([]); else updateOcrHasTypes([]); }
                              else { if (isGlm) updateGlmVisionTypes(ids); else updateOcrHasTypes(ids); }
                            }} className="text-[10px] text-gray-400 hover:text-gray-600 transition-colors">
                              {allSelected ? '清空' : '全选'}
                            </button>
                          </div>
                          <div className="space-y-2.5">
                            {visionGroups.map(group => {
                              const groupTypes = types.filter(t => group.ids.includes(t.id));
                              if (groupTypes.length === 0) return null;
                              return (
                                <div key={group.label}>
                                  <div className="text-[9px] text-gray-400/80 font-medium tracking-wider uppercase mb-1 pl-0.5">{group.label}</div>
                                  <div className="grid grid-cols-3 gap-1">
                                    {groupTypes.map(type => {
                                      const active = selectedSet.includes(type.id);
                                      return (
                                        <button key={type.id} onClick={() => toggleVisionType(type.id, pipeline.mode as 'ocr_has' | 'glm_vision')}
                                          className={`flex items-center justify-center gap-1 px-1.5 py-[5px] rounded-lg text-[11px] font-medium transition-all truncate ${active
                                              ? isGlm ? 'bg-orange-50 text-orange-800' : 'bg-blue-50 text-blue-800'
                                              : 'text-[#86868b] hover:bg-[#e8e8ed]/50'
                                            }`} title={type.description || type.name}>
                                          <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${active ? (isGlm ? 'bg-orange-500' : 'bg-blue-500') : 'bg-[#c7c7cc]'}`} />
                                          <span className="truncate">{type.name}</span>
                                        </button>
                                      );
                                    })}
                                  </div>
                                </div>
                              );
                            })}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )
              ) : sortedEntityTypes.length === 0 ? (
                <p className="text-[11px] text-gray-400 text-center py-8">加载中...</p>
              ) : (() => {
                // 文本模式分组
                const presetTextGroups = [
                  { label: '个人身份', ids: ['PERSON', 'ID_CARD', 'PASSPORT', 'SOCIAL_SECURITY', 'DRIVER_LICENSE', 'MILITARY_ID', 'BIOMETRIC', 'USERNAME_PASSWORD'] },
                  { label: '联系通信', ids: ['PHONE', 'EMAIL', 'QQ_WECHAT_ID', 'IP_ADDRESS', 'MAC_ADDRESS', 'DEVICE_ID', 'URL_WEBSITE'] },
                  { label: '金融财务', ids: ['BANK_CARD', 'BANK_ACCOUNT', 'BANK_NAME', 'PAYMENT_ACCOUNT', 'TAX_ID', 'AMOUNT', 'PROPERTY'] },
                  { label: '机构与地址', ids: ['ORG', 'COMPANY_CODE', 'ADDRESS', 'POSTAL_CODE', 'GPS_LOCATION', 'WORK_UNIT'] },
                  { label: '时间与编号', ids: ['BIRTH_DATE', 'DATE', 'TIME', 'LICENSE_PLATE', 'VIN', 'CASE_NUMBER', 'CONTRACT_NO', 'LEGAL_DOC_NO'] },
                  { label: '人口统计', ids: ['AGE', 'GENDER', 'NATIONALITY', 'MARITAL_STATUS', 'OCCUPATION', 'EDUCATION'] },
                  { label: '诉讼参与人', ids: ['LEGAL_PARTY', 'LAWYER', 'JUDGE', 'WITNESS'] },
                  { label: '敏感信息', ids: ['HEALTH_INFO', 'MEDICAL_RECORD', 'CRIMINAL_RECORD', 'POLITICAL', 'RELIGION', 'SEXUAL_ORIENTATION'] },
                ];
                const allPresetTextIds = new Set(presetTextGroups.flatMap(g => g.ids));
                const customTextTypes = sortedEntityTypes.filter(t => !allPresetTextIds.has(t.id));
                const textGroups = customTextTypes.length > 0
                  ? [...presetTextGroups, { label: '自定义', ids: customTextTypes.map(t => t.id) }]
                  : presetTextGroups;
                const allIds = sortedEntityTypes.map(t => t.id);
                const allSelected = allIds.length > 0 && allIds.every(id => selectedTypes.includes(id));
                return (
                  <div className="p-3 space-y-3">
                    <div className="flex items-center justify-between mb-0.5">
                      <div className="flex items-center gap-3">
                        <span className="text-[10px] font-semibold tracking-wider uppercase text-[#007AFF]">正则</span>
                        <span className="text-[10px] text-gray-300">+</span>
                        <span className="text-[10px] font-semibold tracking-wider uppercase text-[#34C759]">AI</span>
                      </div>
                      <button onClick={() => setSelectedTypes(allSelected ? [] : allIds)} className="text-[10px] text-gray-400 hover:text-gray-600 transition-colors">
                        {allSelected ? '清空' : '全选'}
                      </button>
                    </div>
                    {textGroups.map(group => {
                      const groupTypes = sortedEntityTypes.filter(t => group.ids.includes(t.id));
                      if (groupTypes.length === 0) return null;
                      return (
                        <div key={group.label}>
                          <div className="text-[9px] text-gray-400/80 font-medium tracking-wider uppercase mb-1 pl-0.5">{group.label}</div>
                          <div className="grid grid-cols-3 gap-1">
                            {groupTypes.map(type => {
                              const active = selectedTypes.includes(type.id);
                              const isRegex = !!type.regex_pattern;
                              const isLlm = !!type.use_llm;
                              const isBoth = isRegex && isLlm;
                              // 正则=蓝、AI=绿、混合=靛蓝（和图像Pipeline一样用不同色区分）
                              const activeClass = isBoth
                                ? 'bg-indigo-50 text-indigo-800 hover:bg-indigo-100'
                                : isRegex
                                  ? 'bg-blue-50 text-blue-800 hover:bg-blue-100'
                                  : 'bg-green-50 text-green-800 hover:bg-green-100';
                              const dotClass = isBoth
                                ? 'bg-indigo-500'
                                : isRegex ? 'bg-[#007AFF]' : 'bg-[#34C759]';
                              return (
                                <button key={type.id} onClick={() => setSelectedTypes(prev => active ? prev.filter(t => t !== type.id) : [...prev, type.id])}
                                  className={`flex items-center justify-center gap-1 px-1.5 py-[5px] rounded-lg text-[11px] font-medium transition-all truncate ${active ? activeClass : 'text-[#86868b] hover:bg-[#f0f0f3]'
                                    }`} title={type.description || type.name}>
                                  <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${active ? dotClass : 'bg-[#c7c7cc]'}`} />
                                  <span className="truncate">{type.name}</span>
                                </button>
                              );
                            })}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                );
              })()}
            </div>

            {/* 底部 */}
            <div className="px-4 py-2 border-t border-gray-100/80">
              <div className="text-[10px] text-gray-400 text-center">
                {typeTab === 'vision'
                  ? `OCR ${selectedOcrHasTypes.length} · VLM ${selectedGlmVisionTypes.length}`
                  : `${selectedTypes.length} / ${entityTypes.length} 已选`}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* 预览编辑阶段 */}
      {stage === 'preview' && (
        <div className="flex-1 flex gap-3 p-3 overflow-hidden">
          {/* 文档内容 - 占满中间区域 */}
          <div className="flex-1 flex flex-col bg-white rounded-xl border border-gray-200 overflow-hidden min-w-0">
            <div className="px-3 py-2 border-b border-gray-100 flex items-center justify-between bg-gray-50 flex-shrink-0">
              <div className="min-w-0 flex-1">
                <h3 className="font-semibold text-gray-900 text-sm truncate">{fileInfo?.filename}</h3>
                <p className="text-xs text-gray-500">
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
                    className="text-xs text-gray-500 hover:text-blue-600 px-2 py-1 rounded hover:bg-gray-100"
                    title="在新窗口中查看大图"
                  >
                    🔍 新窗口
                  </button>
                )}
                <button onClick={handleReset} className="text-xs text-gray-500 hover:text-blue-600">重新上传</button>
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
                      availableTypes={visionTypes.map(t => ({ id: t.id, name: t.name, color: t.color }))}
                      defaultType={visionTypes[0]?.id || 'CUSTOM'}
                    />
                  )}
                </div>
              ) : (
                <div className="flex-1 overflow-auto min-h-0">
                  <div className="whitespace-pre-wrap text-[15px] text-gray-800 leading-8 p-4">
                    {renderMarkedContent()}
                  </div>
                </div>
              )}
              {/* 划词添加/修改弹窗 - 二级标签选择器 */}
              {!isImageMode && selectedText && selectionPos && (
                <div
                  className="fixed z-50 bg-white border border-gray-200 rounded-2xl shadow-2xl p-4 min-w-[320px] max-w-[400px]"
                  style={{
                    left: Math.min(selectionPos.x, window.innerWidth - 420),
                    top: selectionPos.y,
                    transform: 'translate(-50%, -100%)',
                  }}
                  onMouseDown={(e) => e.stopPropagation()}
                  onMouseUp={(e) => e.stopPropagation()}
                >
                  {/* 选中文本预览 */}
                  <div className="mb-3">
                    <div className="text-[11px] text-gray-500 mb-1 font-medium">选中文本</div>
                    <div className="text-sm text-gray-800 bg-gray-50 rounded-lg px-3 py-2 max-w-full break-all border border-gray-100">
                      {selectedText.text}
                    </div>
                  </div>

                  {/* 二级标签选择器 */}
                  <div className="mb-3">
                    <div className="text-[11px] text-gray-500 mb-2 font-medium">选择类型</div>
                    <div className="max-h-[240px] overflow-auto space-y-2 pr-1">
                      {ENTITY_GROUPS.filter(group =>
                        group.types.some(t => entityTypes.some(et => et.id === t.id))
                      ).map(group => {
                        const availableTypes = group.types.filter(t =>
                          entityTypes.some(et => et.id === t.id)
                        );
                        if (availableTypes.length === 0) return null;

                        return (
                          <div key={group.id} className="rounded-lg border border-gray-100 overflow-hidden">
                            {/* 一级分组标题 */}
                            <div
                              className="px-2.5 py-1.5 text-[11px] font-semibold flex items-center gap-1.5"
                              style={{ backgroundColor: group.bgColor, color: group.textColor }}
                            >
                              <span
                                className="w-2 h-2 rounded-full"
                                style={{ backgroundColor: group.color }}
                              />
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
                                    className={`text-[12px] px-2 py-1.5 rounded-md text-left transition-all truncate ${isSelected
                                        ? 'font-semibold ring-2 ring-offset-1'
                                        : 'hover:bg-gray-50'
                                      }`}
                                    style={isSelected ? {
                                      backgroundColor: group.bgColor,
                                      color: group.textColor,
                                      boxShadow: `0 0 0 2px ${group.color}`,
                                    } : {
                                      color: '#374151',
                                    }}
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
                      className="flex-1 text-[13px] font-medium bg-gray-900 text-white rounded-lg px-3 py-2 hover:bg-gray-800 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                    >
                      {selectedOverlapIds.length > 0 ? '更新标记' : '添加标记'}
                    </button>
                    {selectedOverlapIds.length > 0 && (
                      <button
                        onClick={removeSelectedEntities}
                        className="text-[13px] font-medium text-red-600 border border-red-200 rounded-lg px-3 py-2 hover:bg-red-50 transition-colors"
                      >
                        删除
                      </button>
                    )}
                    <button
                      onClick={() => { setSelectedText(null); setSelectionPos(null); setSelectedOverlapIds([]); }}
                      className="text-[13px] text-gray-500 border border-gray-200 rounded-lg px-3 py-2 hover:bg-gray-50 transition-colors"
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
                    left: Math.min(entityPopupPos.x, window.innerWidth - 220),
                    top: entityPopupPos.y,
                    transform: 'translate(-50%, -100%)',
                  }}
                  onMouseDown={(e) => e.stopPropagation()}
                  onMouseUp={(e) => e.stopPropagation()}
                >
                  {(() => {
                    const riskConfig = getEntityRiskConfig(clickedEntity.type);
                    const typeName = getEntityTypeName(clickedEntity.type);
                    const group = getEntityGroup(clickedEntity.type);
                    return (
                      <>
                        {/* 实体信息 */}
                        <div className="mb-3">
                          <div className="flex items-center gap-2 mb-1.5">
                            <span
                              className="text-[11px] font-semibold px-2 py-0.5 rounded"
                              style={{ backgroundColor: riskConfig.bgColor, color: riskConfig.textColor }}
                            >
                              {group?.label} · {typeName}
                            </span>
                          </div>
                          <div
                            className="text-sm font-medium px-2 py-1.5 rounded-lg break-all"
                            style={{ backgroundColor: riskConfig.bgColor, color: riskConfig.textColor }}
                          >
                            {clickedEntity.text}
                          </div>
                        </div>

                        {/* 操作按钮 */}
                        <div className="space-y-1.5">
                          <button
                            onClick={confirmRemoveEntity}
                            className="w-full text-[13px] font-medium text-red-600 border border-red-200 rounded-lg px-3 py-2 hover:bg-red-50 transition-colors flex items-center justify-center gap-1.5"
                          >
                            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                            </svg>
                            移除此标注
                          </button>
                          <button
                            onClick={closeEntityPopup}
                            className="w-full text-[13px] text-gray-500 border border-gray-200 rounded-lg px-3 py-2 hover:bg-gray-50 transition-colors"
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

          {/* 右侧面板 - 收窄 */}
          <div className="w-[240px] flex-shrink-0 flex flex-col gap-2 overflow-y-auto overflow-x-hidden pb-4 pr-1 snap-y">
            {/* 类型配置 */}
            <div className="bg-white rounded-xl border border-[#e5e5e5] p-4">
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-[13px] font-semibold text-[#0a0a0a]">识别类型</h3>
                <span className="text-[11px] text-[#737373]">选择要识别的敏感信息类型</span>
              </div>
              <div className="flex gap-2 mb-3">
                <button
                  onClick={() => setTypeTab('text')}
                  className={`text-[12px] font-medium px-3 py-1.5 rounded-lg border transition-colors ${typeTab === 'text'
                      ? 'border-[#0a0a0a] bg-[#0a0a0a] text-white'
                      : 'border-[#e5e5e5] text-[#737373] hover:bg-[#f5f5f5]'
                    }`}
                >
                  文本
                </button>
                <button
                  onClick={() => setTypeTab('vision')}
                  className={`text-[12px] font-medium px-3 py-1.5 rounded-lg border transition-colors ${typeTab === 'vision'
                      ? 'border-[#0a0a0a] bg-[#0a0a0a] text-white'
                      : 'border-[#e5e5e5] text-[#737373] hover:bg-[#f5f5f5]'
                    }`}
                  title="仅图片/扫描件生效"
                >
                  图像
                </button>
              </div>
              <div className="flex gap-2 mb-3">
                <button
                  onClick={handleUndo}
                  disabled={!canUndo}
                  className={`text-[12px] px-2.5 py-1 rounded-lg border transition-colors ${!canUndo
                      ? 'border-[#f0f0f0] text-[#d4d4d4] cursor-not-allowed'
                      : 'border-[#e5e5e5] text-[#737373] hover:border-[#d4d4d4] hover:bg-[#fafafa]'
                    }`}
                >
                  撤销
                </button>
                <button
                  onClick={handleRedo}
                  disabled={!canRedo}
                  className={`text-[12px] px-2.5 py-1 rounded-lg border transition-colors ${!canRedo
                      ? 'border-[#f0f0f0] text-[#d4d4d4] cursor-not-allowed'
                      : 'border-[#e5e5e5] text-[#737373] hover:border-[#d4d4d4] hover:bg-[#fafafa]'
                    }`}
                >
                  重做
                </button>
              </div>
              {typeTab === 'vision' && (
                <div className="mb-3 p-3 bg-[#f5f5f5] rounded-lg border border-[#e5e5e5]">
                  <p className="text-[11px] text-[#262626] leading-relaxed">
                    <span className="font-semibold">双模型并行：</span>
                    OCR+HaS + GLM Vision
                  </p>
                  <p className="text-[11px] text-[#737373] mt-1">
                    在设置中配置启用的类型
                  </p>
                </div>
              )}
              <div className="max-h-56 overflow-auto">
                {typeTab === 'vision' ? (
                  <div className="space-y-3">
                    {pipelines.map(pipeline => {
                      const isGlmVision = pipeline.mode === 'glm_vision';
                      const displayName = isGlmVision ? '🔍 GLM Vision' : '📝 OCR+HaS';
                      return (
                        <div key={pipeline.mode}>
                          <div className={`text-[10px] font-medium mb-1 ${pipeline.mode === 'ocr_has' ? 'text-blue-600' : 'text-purple-600'
                            }`}>
                            {displayName}
                          </div>
                          <div className="grid grid-cols-1 gap-1">
                            {pipeline.types.filter(t => t.enabled).map(type => {
                              const active = pipeline.mode === 'ocr_has'
                                ? selectedOcrHasTypes.includes(type.id)
                                : selectedGlmVisionTypes.includes(type.id);
                              return (
                                <button
                                  key={type.id}
                                  onClick={() => toggleVisionType(type.id, pipeline.mode as 'ocr_has' | 'glm_vision')}
                                  className={`flex items-center gap-1.5 text-xs rounded-lg border px-2 py-1 text-left ${active
                                      ? pipeline.mode === 'ocr_has'
                                        ? 'border-blue-500 bg-blue-50'
                                        : 'border-purple-500 bg-purple-50'
                                      : 'border-gray-200 bg-gray-50 opacity-50'
                                    }`}
                                >
                                  <input
                                    type="checkbox"
                                    checked={active}
                                    onChange={() => { }}
                                    className={`w-3 h-3 rounded ${pipeline.mode === 'ocr_has' ? 'accent-blue-500' : 'accent-purple-500'
                                      }`}
                                  />
                                  <span className="w-2 h-2 rounded-full" style={{ backgroundColor: type.color }} />
                                  <span className={`flex-1 ${active ? 'text-gray-600' : 'text-gray-400'}`}>{type.name}</span>
                                </button>
                              );
                            })}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                ) : (
                  sortedEntityTypes.map(type => {
                    const active = selectedTypes.includes(type.id);
                    return (
                      <button
                        key={type.id}
                        onClick={() => {
                          setSelectedTypes(prev =>
                            active ? prev.filter(t => t !== type.id) : [...prev, type.id]
                          );
                        }}
                        className={`flex items-center gap-2 text-[12px] rounded-lg border px-2.5 py-2 text-left transition-colors ${active
                            ? 'border-[#0a0a0a] bg-[#fafafa]'
                            : 'border-[#e5e5e5] hover:border-[#d4d4d4] hover:bg-[#fafafa]'
                          }`}
                      >
                        <span className="w-2.5 h-2.5 rounded-full flex-shrink-0" style={{ backgroundColor: type.color }} />
                        <span className={`flex-1 ${active ? 'text-[#0a0a0a]' : 'text-[#737373]'}`}>{type.name}</span>
                        {type.regex_pattern && <span className="text-[10px] text-[#f59e0b] font-medium">正则</span>}
                        {type.use_llm && <span className="text-[10px] text-[#8b5cf6] font-medium">AI</span>}
                      </button>
                    );
                  })
                )}
              </div>
              <div className="flex gap-2 mt-3">
                <button
                  onClick={handleRerunNer}
                  className="flex-1 text-[12px] font-medium bg-[#0a0a0a] text-white rounded-lg py-2 hover:bg-[#262626] transition-colors"
                >
                  重新识别
                </button>
                <button
                  onClick={() => {
                    if (typeTab === 'vision') {
                      const ocrHasIds = pipelines.find(p => p.mode === 'ocr_has')?.types.filter(t => t.enabled).map(t => t.id) || [];
                      const glmIds = pipelines.find(p => p.mode === 'glm_vision')?.types.filter(t => t.enabled).map(t => t.id) || [];
                      updateOcrHasTypes(ocrHasIds);
                      updateGlmVisionTypes(glmIds);
                      setBoundingBoxes(prev => prev.map(b => ({ ...b, selected: true })));
                    } else {
                      setSelectedTypes(entityTypes.map(t => t.id));
                    }
                  }}
                  className="text-[12px] text-[#737373] border border-[#e5e5e5] rounded-lg px-3 hover:bg-[#fafafa] hover:border-[#d4d4d4] transition-colors"
                >
                  全选
                </button>
              </div>
              {typeTab === 'text' && (
                <p className="text-[11px] text-[#a3a3a3] mt-2">
                  正则类默认已启用，按需勾选后点"重新识别"
                </p>
              )}
            </div>

            {/* 交互说明 */}
            <div className="bg-gradient-to-br from-gray-50 to-white rounded-xl border border-[#e5e5e5] p-3">
              <div className="text-[12px] font-semibold text-gray-700 mb-2">💡 操作说明</div>
              <div className="space-y-2 text-[12px] text-[#737373]">
                <div className="flex items-start gap-2">
                  <span className="w-5 h-5 rounded bg-red-50 text-red-600 flex items-center justify-center text-[10px] font-bold flex-shrink-0">点</span>
                  <span>点击高亮文字 → 弹出菜单 → 确认移除</span>
                </div>
                <div className="flex items-start gap-2">
                  <span className="w-5 h-5 rounded bg-blue-50 text-blue-600 flex items-center justify-center text-[10px] flex-shrink-0">选</span>
                  <span>划选文字 → 选择类型 → 添加标记</span>
                </div>
              </div>
            </div>

            {/* 统计 */}
            <div className="bg-white rounded-xl border border-[#e5e5e5] p-4">
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-[13px] font-semibold text-[#0a0a0a]">识别结果</h3>
                <span className="text-[12px] text-[#737373] font-medium">
                  {selectedCount}/{isImageMode ? visibleBoxes.length : entities.length}
                </span>
              </div>
              <div className="flex gap-2 mb-3">
                <button onClick={selectAll} className="flex-1 py-1.5 text-[12px] font-medium text-[#0a0a0a] bg-[#f5f5f5] rounded-lg hover:bg-[#e5e5e5] transition-colors">全选</button>
                <button onClick={deselectAll} className="flex-1 py-1.5 text-[12px] font-medium text-[#737373] bg-white border border-[#e5e5e5] rounded-lg hover:bg-[#fafafa] transition-colors">取消</button>
              </div>
              {!isImageMode && (
                <>
                  <div className="mb-3">
                    <label className="block text-[11px] text-[#737373] mb-1.5 font-medium">脱敏方式</label>
                    <select
                      value={replacementMode}
                      onChange={(e) => setReplacementMode(e.target.value as 'structured' | 'smart' | 'mask')}
                      className="w-full text-[13px] border border-[#e5e5e5] rounded-lg px-3 py-2 focus:outline-none focus:border-[#0a0a0a] bg-white cursor-pointer"
                    >
                      <option value="structured">结构化语义标签（推荐）</option>
                      <option value="smart">智能替换</option>
                      <option value="mask">掩码替换</option>
                    </select>
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
                          <div key={group.id} className="rounded-lg overflow-hidden border border-gray-100">
                            <div
                              className="flex items-center justify-between px-2.5 py-1.5"
                              style={{ backgroundColor: group.bgColor }}
                            >
                              <div className="flex items-center gap-1.5">
                                <span
                                  className="w-2 h-2 rounded-full"
                                  style={{ backgroundColor: group.color }}
                                />
                                <span
                                  className="text-[11px] font-semibold"
                                  style={{ color: group.textColor }}
                                >
                                  {group.label}
                                </span>
                              </div>
                              <span className="text-[11px] font-medium" style={{ color: group.color }}>
                                {selectedInGroup}/{totalInGroup}
                              </span>
                            </div>
                            <div className="px-2.5 py-1.5 space-y-0.5 bg-white">
                              {groupStats.map(([typeId, count]) => (
                                <div key={typeId} className="flex items-center justify-between text-[11px]">
                                  <span className="text-[#737373]">{getEntityTypeName(typeId)}</span>
                                  <span className="text-[#0a0a0a] tabular-nums">{count.selected}/{count.total}</span>
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
            <div className="flex-1 bg-white rounded-xl border border-[#e5e5e5] overflow-hidden flex flex-col min-h-0">
              <div className="px-4 py-2.5 border-b border-[#f0f0f0] bg-[#fafafa] flex items-center justify-between">
                <span className="text-[13px] font-semibold text-[#0a0a0a]">
                  {isImageMode ? '区域列表' : '识别结果'}
                </span>
                <span className="text-[12px] text-gray-500">
                  点击可编辑/移除
                </span>
              </div>
              <div className="flex-1 overflow-auto">
                {isImageMode ? (
                  visibleBoxes.length === 0 ? (
                    <p className="p-4 text-center text-[14px] text-gray-400">暂无识别结果</p>
                  ) : (
                    visibleBoxes.map(box => {
                      const riskConfig = getEntityRiskConfig(box.type);
                      const group = getEntityGroup(box.type);
                      return (
                        <div
                          key={box.id}
                          className="px-3 py-2.5 flex items-center gap-2 cursor-pointer border-b border-gray-50 transition-all hover:bg-gray-50"
                          onClick={() => toggleBox(box.id)}
                        >
                          <input
                            type="checkbox"
                            checked={box.selected}
                            onChange={() => { }}
                            className="w-4 h-4 rounded"
                            style={{ accentColor: riskConfig.color }}
                          />
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-1.5 mb-1">
                              <span
                                className="text-[11px] font-medium px-1.5 py-0.5 rounded"
                                style={{
                                  backgroundColor: riskConfig.bgColor,
                                  color: riskConfig.textColor
                                }}
                              >
                                {group?.label} · {getEntityTypeName(box.type)}
                              </span>
                              <span className={`px-1 py-0.5 rounded text-[9px] font-bold text-white ${box.source === 'ocr_has' ? 'bg-blue-500' :
                                  box.source === 'glm_vision' ? 'bg-purple-500' : 'bg-gray-400'
                                }`}>
                                {box.source === 'ocr_has' ? 'OCR' : box.source === 'glm_vision' ? 'VLM' : '手动'}
                              </span>
                            </div>
                            <p className="text-[14px] truncate text-gray-900">
                              {box.text || '图像区域'}
                            </p>
                          </div>
                        </div>
                      );
                    })
                  )
                ) : (
                  entities.length === 0 ? (
                    <p className="p-4 text-center text-[14px] text-gray-400">暂无识别结果</p>
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
                          <div
                            className="px-3 py-2 flex items-center justify-between sticky top-0 z-10"
                            style={{ backgroundColor: group.bgColor }}
                          >
                            <div className="flex items-center gap-1.5">
                              <span
                                className="w-2.5 h-2.5 rounded-full"
                                style={{ backgroundColor: group.color }}
                              />
                              <span
                                className="text-[12px] font-semibold"
                                style={{ color: group.textColor }}
                              >
                                {group.label}
                              </span>
                            </div>
                            <span className="text-[11px] font-medium" style={{ color: group.textColor }}>
                              {groupEntities.length}
                            </span>
                          </div>
                          {/* 该分组下的实体 */}
                          {groupEntities.map(entity => {
                            const riskConfig = getEntityRiskConfig(entity.type);
                            return (
                              <div
                                key={entity.id}
                                className="px-3 py-2.5 flex items-center gap-2 cursor-pointer border-b border-gray-50 transition-all hover:bg-gray-50"
                                onClick={(e) => handleEntityClick(entity, e)}
                              >
                                <div className="flex-1 min-w-0">
                                  <div className="flex items-center gap-1.5 mb-1">
                                    <span
                                      className="text-[11px] font-medium px-1.5 py-0.5 rounded"
                                      style={{
                                        backgroundColor: riskConfig.bgColor,
                                        color: riskConfig.textColor
                                      }}
                                    >
                                      {getEntityTypeName(entity.type)}
                                    </span>
                                    <span className="text-[10px] text-gray-400">
                                      {entity.source === 'regex' ? '正则' : entity.source === 'manual' ? '手动' : 'AI'}
                                    </span>
                                  </div>
                                  <p className="text-[14px] truncate text-gray-900">
                                    {entity.text}
                                  </p>
                                </div>
                                <button
                                  onClick={e => { e.stopPropagation(); removeEntity(entity.id); }}
                                  className="p-1 text-gray-300 hover:text-red-500 flex-shrink-0"
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
              className={`py-3 rounded-xl text-[14px] font-semibold flex items-center justify-center gap-2 transition-all ${selectedCount > 0
                  ? 'bg-[#0a0a0a] text-white hover:bg-[#262626]'
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
        // 为每个匹配生成唯一ID：orig-{key}-{序号}
        const highlightText = (text: string, map: Record<string, string>, _prefix?: string) => {
          if (!text || Object.keys(map).length === 0) return <span>{text}</span>;
          const sortedKeys = Object.keys(map).sort((a, b) => b.length - a.length);
          const regex = new RegExp(`(${sortedKeys.map(k => k.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')})`, 'g');
          const parts = text.split(regex);
          const counters: Record<string, number> = {};
          return <>{parts.map((part, i) => {
            if (map[part] !== undefined) {
              const idx = counters[part] || 0;
              counters[part] = idx + 1;
              const safeKey = part.replace(/[^a-zA-Z0-9\u4e00-\u9fff]/g, '_');
              return <mark key={i} data-match-key={safeKey} data-match-idx={idx}
                className="result-mark-orig bg-amber-100/80 text-amber-900 px-0.5 rounded-sm transition-all duration-300">{part}</mark>;
            }
            return <span key={i}>{part}</span>;
          })}</>;
        };
        const highlightRedacted = (text: string, map: Record<string, string>) => {
          if (!text || Object.keys(map).length === 0) return <span>{text}</span>;

          // 建立 replacement → origKey[] 反向映射（一个replacement可对应多个原文）
          const replToOrigKeys: Record<string, string[]> = {};
          Object.entries(map).forEach(([origKey, repl]) => {
            if (!replToOrigKeys[repl]) replToOrigKeys[repl] = [];
            replToOrigKeys[repl].push(origKey);
          });

          // 收集所有唯一的replacement，按长度降序（优先匹配长的）
          const sortedRepls = Object.keys(replToOrigKeys).sort((a, b) => b.length - a.length);

          // 如果没有替换文本，直接返回原文
          if (sortedRepls.length === 0) return <span>{text}</span>;

          // 使用正则匹配（更可靠）
          const escapedRepls = sortedRepls.map(r => r.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
          const regex = new RegExp(`(${escapedRepls.join('|')})`, 'g');
          const parts = text.split(regex);

          const counters: Record<string, number> = {};
          return <>{parts.map((part, i) => {
            const origKeys = replToOrigKeys[part];
            if (origKeys && origKeys.length > 0) {
              const origKey = origKeys[0];
              const safeKey = origKey.replace(/[^a-zA-Z0-9\u4e00-\u9fff]/g, '_');
              const idx = counters[safeKey] || 0;
              counters[safeKey] = idx + 1;
              return <mark key={i} data-match-key={safeKey} data-match-idx={idx}
                className="result-mark-redacted bg-blue-100/80 text-blue-800 px-0.5 rounded-sm transition-all duration-300">{part}</mark>;
            }
            return <span key={i}>{part}</span>;
          })}</>;
        };
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
            el.classList.remove('result-mark-active', 'ring-2', 'ring-offset-1', 'ring-amber-400', 'ring-blue-400', 'scale-105');
          });
          // 滚动原文
          const origEl = origMarks[Math.min(idx, origMarks.length - 1)] as HTMLElement;
          if (origEl) {
            origEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
            origEl.classList.add('result-mark-active', 'ring-2', 'ring-offset-1', 'ring-amber-400', 'scale-105');
          }
          // 滚动脱敏结果
          const redEl = redactedMarks[Math.min(idx, redactedMarks.length - 1)] as HTMLElement;
          if (redEl) {
            redEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
            redEl.classList.add('result-mark-active', 'ring-2', 'ring-offset-1', 'ring-blue-400', 'scale-105');
          }
          // 2秒后清除
          setTimeout(() => {
            document.querySelectorAll('.result-mark-active').forEach(el => {
              el.classList.remove('result-mark-active', 'ring-2', 'ring-offset-1', 'ring-amber-400', 'ring-blue-400', 'scale-105');
            });
          }, 2500);
        };

        return (
          <div className="flex-1 flex flex-col overflow-hidden">
            {/* 顶部状态栏 */}
            <div className="flex-shrink-0 mx-4 mt-4 mb-3">
              <div className="bg-gradient-to-r from-gray-900 to-gray-800 rounded-2xl px-6 py-4 flex items-center justify-between">
                <div className="flex items-center gap-4">
                  <div className="w-10 h-10 rounded-xl bg-white/10 flex items-center justify-center">
                    <svg className="w-5 h-5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
                    </svg>
                  </div>
                  <div>
                    <p className="text-white text-sm font-semibold">脱敏完成</p>
                    <p className="text-gray-400 text-xs">{redactedCount} 处敏感信息已处理</p>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <button onClick={() => setStage('preview')} className="px-3 py-1.5 text-xs text-gray-300 hover:text-white bg-white/10 hover:bg-white/20 rounded-lg transition-all">返回编辑</button>
                  <button onClick={handleReset} className="px-3 py-1.5 text-xs text-gray-300 hover:text-white bg-white/10 hover:bg-white/20 rounded-lg transition-all">新文件</button>
                  {fileInfo && (
                    <a href={`/api/v1/files/${fileInfo.file_id}/download?redacted=true`} download className="px-4 py-1.5 text-xs font-medium text-gray-900 bg-white hover:bg-gray-100 rounded-lg transition-all">下载文件</a>
                  )}
                </div>
              </div>
            </div>

            {/* 三列主体 */}
            {isImageMode ? (
              <div className="flex-1 flex gap-3 px-4 pb-4 min-h-0">
                {/* 左：原始图片 */}
                <div className="flex-1 min-w-0 bg-white rounded-2xl border border-gray-200/80 flex flex-col overflow-hidden">
                  <div className="flex-shrink-0 px-4 py-2.5 border-b border-gray-100 flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full bg-amber-400" />
                    <span className="text-xs font-semibold text-gray-700 tracking-tight">原始图片</span>
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
                        availableTypes={visionTypes.map(t => ({ id: t.id, name: t.name, color: t.color }))}
                        defaultType={visionTypes[0]?.id || 'CUSTOM'}
                      />
                    )}
                  </div>
                </div>
                {/* 中：脱敏后图片 */}
                <div className="flex-1 min-w-0 bg-white rounded-2xl border border-gray-200/80 flex flex-col overflow-hidden">
                  <div className="flex-shrink-0 px-4 py-2.5 border-b border-gray-100 flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full bg-blue-400" />
                    <span className="text-xs font-semibold text-gray-700 tracking-tight">脱敏结果</span>
                  </div>
                  <div className="flex-1 overflow-auto p-3">
                    {fileInfo && <img src={`/api/v1/files/${fileInfo.file_id}/download?redacted=true`} alt="redacted" className="max-w-full h-auto object-contain" />}
                  </div>
                </div>
                {/* 右：映射表 */}
                <div className="w-64 flex-shrink-0 bg-white rounded-2xl border border-gray-200/80 flex flex-col overflow-hidden">
                  <div className="flex-shrink-0 px-4 py-2.5 border-b border-gray-100 flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="w-2 h-2 rounded-full bg-violet-400" />
                      <span className="text-xs font-semibold text-gray-700 tracking-tight">脱敏记录</span>
                    </div>
                    <span className="text-[10px] text-gray-400 tabular-nums">{Object.keys(entityMap).length}</span>
                  </div>
                  <div className="flex-1 overflow-auto">
                    {Object.entries(entityMap).map(([orig, repl], i) => (
                      <button key={i} onClick={() => scrollToMatch(orig, repl)}
                        className="w-full text-left px-3 py-2 border-b border-gray-50 hover:bg-blue-50/50 transition-all group">
                        <div className="text-[11px] text-amber-700 font-medium truncate group-hover:text-amber-800">{orig}</div>
                        <div className="flex items-center gap-1.5 mt-0.5">
                          <svg className="w-2.5 h-2.5 text-gray-300 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 8l4 4m0 0l-4 4m4-4H3" /></svg>
                          <span className="text-[11px] text-blue-600 truncate group-hover:text-blue-700">{repl}</span>
                        </div>
                      </button>
                    ))}
                    {Object.keys(entityMap).length === 0 && <p className="text-xs text-gray-400 text-center py-6">暂无记录</p>}
                  </div>
                </div>
              </div>
            ) : (
              <div className="flex-1 flex gap-3 px-4 pb-4 min-h-0">
                {/* 左：原始文档 */}
                <div className="flex-1 min-w-0 bg-white rounded-2xl border border-gray-200/80 flex flex-col overflow-hidden">
                  <div className="flex-shrink-0 px-4 py-2.5 border-b border-gray-100 flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full bg-amber-400" />
                    <span className="text-xs font-semibold text-gray-700 tracking-tight">原始文档</span>
                  </div>
                  <div className="flex-1 overflow-auto p-4" id="original-scroll">
                    <div className="text-[13px] leading-relaxed text-gray-800 whitespace-pre-wrap font-[system-ui]">
                      {highlightText(content, entityMap, 'orig')}
                    </div>
                  </div>
                </div>
                {/* 中：脱敏后文档 */}
                <div className="flex-1 min-w-0 bg-white rounded-2xl border border-gray-200/80 flex flex-col overflow-hidden">
                  <div className="flex-shrink-0 px-4 py-2.5 border-b border-gray-100 flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full bg-blue-400" />
                    <span className="text-xs font-semibold text-gray-700 tracking-tight">脱敏结果</span>
                  </div>
                  <div className="flex-1 overflow-auto p-4" id="redacted-scroll">
                    <div className="text-[13px] leading-relaxed text-gray-800 whitespace-pre-wrap font-[system-ui]">
                      {highlightRedacted(redactedContent || content, entityMap)}
                    </div>
                  </div>
                </div>
                {/* 右：映射列表 */}
                <div className="w-64 flex-shrink-0 bg-white rounded-2xl border border-gray-200/80 flex flex-col overflow-hidden">
                  <div className="flex-shrink-0 px-4 py-2.5 border-b border-gray-100 flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="w-2 h-2 rounded-full bg-violet-400" />
                      <span className="text-xs font-semibold text-gray-700 tracking-tight">脱敏记录</span>
                    </div>
                    <span className="text-[10px] text-gray-400 tabular-nums">{Object.keys(entityMap).length}</span>
                  </div>
                  <div className="flex-1 overflow-auto">
                    {Object.entries(entityMap).map(([orig, repl], i) => {
                      const count = (content || '').split(orig).length - 1;
                      return (
                        <button key={i} onClick={() => scrollToMatch(orig, repl)}
                          className="w-full text-left px-3 py-2 border-b border-gray-50 hover:bg-blue-50/50 transition-all group">
                          <div className="flex items-center gap-1.5">
                            <span className="text-[11px] text-amber-700 font-medium truncate flex-1 group-hover:text-amber-800">{orig}</span>
                            {count > 1 && <span className="text-[9px] text-gray-400 bg-gray-100 rounded px-1 flex-shrink-0">{count}处</span>}
                          </div>
                          <div className="flex items-center gap-1.5 mt-0.5">
                            <svg className="w-2.5 h-2.5 text-gray-300 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 8l4 4m0 0l-4 4m4-4H3" /></svg>
                            <span className="text-[11px] text-blue-600 truncate group-hover:text-blue-700">{repl}</span>
                          </div>
                        </button>
                      );
                    })}
                    {Object.keys(entityMap).length === 0 && <p className="text-xs text-gray-400 text-center py-8">暂无记录</p>}
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
            <div className="w-12 h-12 border-3 border-blue-500 border-t-transparent rounded-full animate-spin mx-auto mb-4" />
            <p className="text-base font-medium text-gray-900 mb-1">{loadingMessage || '处理中...'}</p>
            <p className="text-xs text-gray-400">图像识别可能需要10-30秒，请耐心等待</p>
          </div>
        </div>
      )}
    </div>
  );
};

export default Playground;
