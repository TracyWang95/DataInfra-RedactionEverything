
import { useState, useCallback, useEffect, useRef, useMemo } from 'react';
import { useDropzone } from 'react-dropzone';
import { useUndoRedo } from '@/hooks/useUndoRedo';
import { authFetch } from '@/services/api-client';
import { showToast } from '@/components/Toast';
import { t } from '@/i18n';
import { downloadFile } from '@/services/api';
import { localizeErrorMessage } from '@/utils/localizeError';
import { safeJson, authBlobUrl, runVisionDetection } from '../utils';
import { usePlaygroundRecognition } from './use-playground-recognition';
import type { FileInfo, Entity, BoundingBox, Stage } from '../types';
import type { VersionHistoryEntry } from '@/types';

export function usePlayground() {

  const recognition = usePlaygroundRecognition();

  const [stage, setStage] = useState<Stage>('upload');
  const [fileInfo, setFileInfo] = useState<FileInfo | null>(null);
  const [content, setContent] = useState('');
  const [entities, setEntities] = useState<Entity[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [loadingMessage, setLoadingMessage] = useState('');
  const [redactedCount, setRedactedCount] = useState(0);
  const [entityMap, setEntityMap] = useState<Record<string, string>>({});
  const [redactionReport, setRedactionReport] = useState<Record<string, unknown> | null>(null);
  const [reportOpen, setReportOpen] = useState(false);
  const [versionHistory, setVersionHistory] = useState<VersionHistoryEntry[]>([]);
  const [versionHistoryOpen, setVersionHistoryOpen] = useState(false);

  const [boundingBoxes, setBoundingBoxes] = useState<BoundingBox[]>([]);
  const [imageUrl, setImageUrl] = useState('');
  const [redactedImageUrl, setRedactedImageUrl] = useState('');

  const entityHistory = useUndoRedo<Entity[]>();
  const imageHistory = useUndoRedo<BoundingBox[]>();

  const abortRef = useRef<AbortController | null>(null);
  const popoutChannelRef = useRef<BroadcastChannel | null>(null);
  const popoutTimerRef = useRef<number | null>(null);

  const isImageMode = !!fileInfo && (fileInfo.file_type === 'image' || !!fileInfo.is_scanned);
  const visibleBoxes = boundingBoxes;
  const selectedCount = isImageMode
    ? visibleBoxes.filter(b => b.selected).length
    : entities.filter(e => e.selected).length;
  const canUndo = isImageMode ? imageHistory.canUndo : entityHistory.canUndo;
  const canRedo = isImageMode ? imageHistory.canRedo : entityHistory.canRedo;
  const allSelectedVisionTypes = useMemo(
    () => [...recognition.selectedOcrHasTypes, ...recognition.selectedHasImageTypes],
    [recognition.selectedOcrHasTypes, recognition.selectedHasImageTypes],
  );

  useEffect(() => {
    return () => {
      abortRef.current?.abort();
      if (popoutTimerRef.current !== null) clearInterval(popoutTimerRef.current);
      popoutChannelRef.current?.close();
    };
  }, []);

  const imageUrlRaw = fileInfo ? `/api/v1/files/${fileInfo.file_id}/download` : '';
  useEffect(() => {
    let cancelled = false;
    if (!imageUrlRaw) { setImageUrl(''); return; }
    authBlobUrl(imageUrlRaw)
      .then(u => { if (!cancelled) setImageUrl(u); })
      .catch(() => { if (!cancelled) setImageUrl(imageUrlRaw); });
    return () => { cancelled = true; };
  }, [imageUrlRaw]);

  useEffect(() => {
    let cancelled = false;
    if (!fileInfo) { setRedactedImageUrl(''); return; }
    const raw = `/api/v1/files/${fileInfo.file_id}/download?redacted=true`;
    authBlobUrl(raw)
      .then(u => { if (!cancelled) setRedactedImageUrl(u); })
      .catch(() => { if (!cancelled) setRedactedImageUrl(raw); });
    return () => { cancelled = true; };
  }, [fileInfo]);

  // --- Loading elapsed timer ---
  const [loadingElapsedSec, setLoadingElapsedSec] = useState(0);
  useEffect(() => {
    if (!isLoading) { setLoadingElapsedSec(0); return; }
    setLoadingElapsedSec(0);
    const id = window.setInterval(() => setLoadingElapsedSec(s => s + 1), 1000);
    return () => window.clearInterval(id);
  }, [isLoading]);

  // --- Auto-switch type tab on file mode ---
  useEffect(() => {
    recognition.setTypeTab(isImageMode ? 'vision' : 'text');
  }, [isImageMode, recognition.setTypeTab]);

  // --- Entity / box operations ---
  const applyEntities = useCallback((next: Entity[]) => {
    entityHistory.save(entities);
    setEntities(next);
  }, [entities, entityHistory]);

  const handleUndo = useCallback(() => {
    if (isImageMode) {
      const prev = imageHistory.undo(boundingBoxes);
      if (prev) setBoundingBoxes(prev);
    } else {
      const prev = entityHistory.undo(entities);
      if (prev) setEntities(prev);
    }
  }, [isImageMode, boundingBoxes, entities, imageHistory, entityHistory]);

  const handleRedo = useCallback(() => {
    if (isImageMode) {
      const next = imageHistory.redo(boundingBoxes);
      if (next) setBoundingBoxes(next);
    } else {
      const next = entityHistory.redo(entities);
      if (next) setEntities(next);
    }
  }, [isImageMode, boundingBoxes, entities, imageHistory, entityHistory]);

  const selectAll = useCallback(() => {
    if (isImageMode) {
      setBoundingBoxes(prev => prev.map(b => ({
        ...b,
        selected: allSelectedVisionTypes.includes(b.type),
      })));
    } else {
      setEntities(prev => prev.map(e => ({ ...e, selected: true })));
    }
  }, [isImageMode, allSelectedVisionTypes]);

  const deselectAll = useCallback(() => {
    if (isImageMode) {
      setBoundingBoxes(prev => prev.map(b => ({ ...b, selected: false })));
    } else {
      setEntities(prev => prev.map(e => ({ ...e, selected: false })));
    }
  }, [isImageMode]);

  const toggleBox = useCallback((id: string) => {
    setBoundingBoxes(prev => prev.map(b => b.id === id ? { ...b, selected: !b.selected } : b));
  }, []);

  const removeEntity = useCallback((id: string) => {
    setEntities(prev => {
      entityHistory.save(prev);
      return prev.filter(e => e.id !== id);
    });
    showToast(t('playground.deleted') || '已删除', 'info');
  }, [entityHistory]);

  const mergeVisibleBoxes = useCallback((nextBoxes: BoundingBox[], prevBoxes: BoundingBox[] = []) => {
    const ids = new Set([...nextBoxes, ...prevBoxes].map(b => b.id));
    const otherBoxes = boundingBoxes.filter(b => !ids.has(b.id));
    return [...otherBoxes, ...nextBoxes];
  }, [boundingBoxes]);

  // --- File upload ---
  const [pendingFile, setPendingFile] = useState<{
    fileId: string;
    fileType: string;
    isScanned: boolean;
    content: string;
  } | null>(null);

  const latestOcrHasTypesRef = useRef(recognition.selectedOcrHasTypes);
  const latestHasImageTypesRef = useRef(recognition.selectedHasImageTypes);
  const latestSelectedTypesRef = useRef(recognition.selectedTypes);
  latestOcrHasTypesRef.current = recognition.selectedOcrHasTypes;
  latestHasImageTypesRef.current = recognition.selectedHasImageTypes;
  latestSelectedTypesRef.current = recognition.selectedTypes;

  const handleFileDrop = useCallback(async (acceptedFiles: File[]) => {
    if (acceptedFiles.length === 0) return;
    const file = acceptedFiles[0];
    setIsLoading(true);

    try {
      setLoadingMessage(t('playground.uploading') || '正在上传文件...');
      const formData = new FormData();
      formData.append('file', file);
      formData.append('upload_source', 'playground');

      const uploadRes = await authFetch('/api/v1/files/upload', { method: 'POST', body: formData });
      if (!uploadRes.ok) throw new Error(t('playground.uploadFailed') || '文件上传失败');
      const uploadData = await safeJson(uploadRes);

      setLoadingMessage(t('playground.parsing') || '正在解析文件...');
      const parseRes = await authFetch(`/api/v1/files/${uploadData.file_id}/parse`);
      if (!parseRes.ok) throw new Error(t('playground.parseFailed') || '文件解析失败');
      const parseData = await safeJson(parseRes);

      const isScanned = parseData.is_scanned || false;
      const parsedContent = parseData.content || '';

      setFileInfo({
        file_id: uploadData.file_id,
        filename: uploadData.filename,
        file_size: uploadData.file_size,
        file_type: uploadData.file_type,
        is_scanned: isScanned,
      });
      setContent(parsedContent);
      setBoundingBoxes([]);
      imageHistory.reset();
      setEntities([]);

      setPendingFile({
        fileId: uploadData.file_id,
        fileType: uploadData.file_type,
        isScanned,
        content: parsedContent,
      });
    } catch (err) {
      showToast(localizeErrorMessage(err, 'playground.processFailed'), 'error');
      setIsLoading(false);
      setLoadingMessage('');
    }
  }, [imageHistory]);

  // --- Auto-recognition after upload ---
  useEffect(() => {
    if (!pendingFile) return;
    const { fileId, fileType, isScanned, content: parsedContent } = pendingFile;
    setPendingFile(null);

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
          const vLabel = ocrTypes.length > 0 && hiTypes.length > 0
            ? '正在进行图像识别（OCR+HaS 与 HaS Image 并行）...'
            : ocrTypes.length > 0
              ? '正在进行图像识别（OCR+HaS）...'
              : hiTypes.length > 0
                ? '正在进行图像识别（HaS Image）...'
                : '正在进行图像识别...';
          setLoadingMessage(vLabel);

          const result = await runVisionDetection(fileId, ocrTypes, hiTypes);
          if (signal.aborted) return;

          setBoundingBoxes(result.boxes);
          imageHistory.reset();
          showToast(`识别到 ${result.boxes.length} 个敏感区域`, 'success');
        } else if (parsedContent) {
          setLoadingMessage('AI正在识别敏感信息...');
          const nerRes = await authFetch(`/api/v1/files/${fileId}/ner/hybrid`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ entity_type_ids: latestSelectedTypesRef.current }),
            signal,
          });
          if (signal.aborted) return;

          if (nerRes.ok) {
            const nerData = await safeJson(nerRes);
            const entitiesWithSource = (nerData.entities || []).map(
              (e: Record<string, unknown>, idx: number) => ({
                ...e,
                id: e.id || `entity_${idx}`,
                selected: true,
                source: e.source || 'llm',
              }),
            );
            setEntities(entitiesWithSource);
            entityHistory.reset();
            showToast(`识别到 ${entitiesWithSource.length} 处敏感信息`, 'success');
          }
        }
        if (signal.aborted) return;
        setStage('preview');
      } catch (err) {
        if (signal.aborted) return;
        showToast(localizeErrorMessage(err, 'playground.recognizeFailed'), 'error');
      } finally {
        if (!signal.aborted) {
          setIsLoading(false);
          setLoadingMessage('');
        }
      }
    };

    doRecognition();
  }, [pendingFile]);

  // --- Dropzone ---
  const dropzone = useDropzone({
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

  // --- Re-run recognition ---
  const handleRerunNer = useCallback(async () => {
    if (!fileInfo) return;
    setIsLoading(true);
    setLoadingMessage(
      isImageMode
        ? (() => {
            const o = recognition.selectedOcrHasTypes.length > 0;
            const g = recognition.selectedHasImageTypes.length > 0;
            if (o && g) return '重新识别中（OCR+HaS 与 HaS Image 并行）...';
            if (o) return '重新识别中（OCR+HaS）...';
            if (g) return '重新识别中（HaS Image）...';
            return '重新识别中...';
          })()
        : '重新识别中（正则+AI语义识别）...',
    );

    try {
      if (isImageMode) {
        const result = await runVisionDetection(
          fileInfo.file_id,
          recognition.selectedOcrHasTypes,
          recognition.selectedHasImageTypes,
        );
        setBoundingBoxes(result.boxes);
        imageHistory.reset();
        showToast(`重新识别完成：${result.boxes.length} 个区域`, 'success');
      } else {
        const nerRes = await authFetch(`/api/v1/files/${fileInfo.file_id}/ner/hybrid`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ entity_type_ids: recognition.selectedTypes }),
        });
        if (!nerRes.ok) throw new Error('重新识别失败');
        const nerData = await safeJson(nerRes);
        const entitiesWithSource = (nerData.entities || []).map(
          (e: Record<string, unknown>, idx: number) => ({
            ...e,
            id: e.id || `entity_${idx}`,
            selected: true,
            source: e.source || 'llm',
          }),
        );
        setEntities(entitiesWithSource);
        entityHistory.reset();
        showToast(`重新识别完成：${entitiesWithSource.length} 处`, 'success');
      }
    } catch (err) {
      showToast(localizeErrorMessage(err, 'playground.recognizeFailed'), 'error');
    } finally {
      setIsLoading(false);
      setLoadingMessage('');
    }
  }, [fileInfo, isImageMode, recognition, imageHistory, entityHistory]);

  // --- Execute redaction ---
  const handleRedact = useCallback(async () => {
    if (!fileInfo) return;
    setIsLoading(true);
    setLoadingMessage(t('playground.redacting') || '正在执行脱敏...');

    try {
      const selectedEntities = entities.filter(e => e.selected);
      const selectedBoxes = boundingBoxes.filter(b => b.selected);

      const res = await authFetch('/api/v1/redaction/execute', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          file_id: fileInfo.file_id,
          entities: selectedEntities,
          bounding_boxes: selectedBoxes,
          config: {
            replacement_mode: recognition.replacementMode,
            entity_types: [],
            custom_replacements: {},
          },
        }),
      });

      if (!res.ok) throw new Error(t('playground.redactFailed') || '脱敏处理失败');
      const result = await safeJson(res);
      setEntityMap(result.entity_map || {});
      setRedactedCount(result.redacted_count || 0);
      setStage('result');

      authFetch(`/api/v1/redaction/${fileInfo.file_id}/report`)
        .then(r => r.json())
        .then(data => setRedactionReport(data))
        .catch(() => setRedactionReport(null));

      authFetch(`/api/v1/redaction/${fileInfo.file_id}/versions`)
        .then(r => r.json())
        .then(data => setVersionHistory(data.versions || []))
        .catch(() => setVersionHistory([]));

      showToast(`完成，共处理 ${result.redacted_count} 处`, 'success');
    } catch (err) {
      showToast(localizeErrorMessage(err, 'playground.redactFailed'), 'error');
    } finally {
      setIsLoading(false);
      setLoadingMessage('');
    }
  }, [fileInfo, entities, boundingBoxes, recognition.replacementMode]);

  // --- Reset ---
  const handleReset = useCallback(() => {
    setStage('upload');
    setFileInfo(null);
    setContent('');
    setEntities([]);
    setRedactedCount(0);
    setEntityMap({});
    setRedactionReport(null);
    setReportOpen(false);
    entityHistory.reset();
    setBoundingBoxes([]);
    imageHistory.reset();
    setVersionHistory([]);
    setVersionHistoryOpen(false);
  }, [entityHistory, imageHistory]);

  // --- Download ---
  const handleDownload = useCallback(() => {
    if (!fileInfo) return;
    downloadFile(
      `/api/v1/files/${fileInfo.file_id}/download?redacted=true`,
      `redacted_${fileInfo.filename}`,
    ).catch(() => {});
  }, [fileInfo]);

  // --- Keyboard shortcuts ---
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable)) return;
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
      } else if (key === 'a') {
        e.preventDefault();
        selectAll();
      }
    };
    const handleEsc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') deselectAll();
    };
    window.addEventListener('keydown', handleKeyDown);
    window.addEventListener('keydown', handleEsc);
    return () => {
      window.removeEventListener('keydown', handleKeyDown);
      window.removeEventListener('keydown', handleEsc);
    };
  }, [handleUndo, handleRedo, selectAll, deselectAll]);

  // --- Popout support ---
  const openPopout = useCallback(() => {
    popoutChannelRef.current?.close();
    const ch = new BroadcastChannel('playground-image-popout');
    popoutChannelRef.current = ch;

    const sendInit = () => {
      ch.postMessage({
        type: 'init',
        imageUrl,
        boxes: boundingBoxes,
        visionTypes: recognition.visionTypes.map(vt => ({ id: vt.id, name: vt.name, color: '#6366F1' })),
        defaultType: recognition.visionTypes[0]?.id || 'CUSTOM',
      });
    };

    ch.onmessage = (e: MessageEvent) => {
      const d = e.data;
      if (d?.type === 'popout-ready') sendInit();
      if (d?.type === 'boxes-sync') setBoundingBoxes(d.boxes);
      if (d?.type === 'boxes-commit') {
        const prevAll = mergeVisibleBoxes(d.prevBoxes, d.nextBoxes);
        const nextAll = mergeVisibleBoxes(d.nextBoxes, d.prevBoxes);
        imageHistory.save(prevAll);
        setBoundingBoxes(nextAll);
      }
    };

    const w = window.open('/playground/image-editor', '_blank', 'width=1200,height=900,scrollbars=yes,resizable=yes');
    if (popoutTimerRef.current !== null) clearInterval(popoutTimerRef.current);
    popoutTimerRef.current = window.setInterval(() => {
      if (w && w.closed) {
        if (popoutTimerRef.current !== null) clearInterval(popoutTimerRef.current);
        popoutTimerRef.current = null;
        ch.close();
        popoutChannelRef.current = null;
      }
    }, 1000);
  }, [imageUrl, boundingBoxes, recognition.visionTypes, mergeVisibleBoxes, imageHistory]);

  return {
    // Stage
    stage,
    setStage,
    // File info
    fileInfo,
    content,
    isImageMode,
    // Entities & boxes
    entities,
    setEntities,
    applyEntities,
    boundingBoxes,
    setBoundingBoxes,
    visibleBoxes,
    // Loading
    isLoading,
    loadingMessage,
    loadingElapsedSec,
    // Redaction result
    entityMap,
    redactedCount,
    redactionReport,
    reportOpen,
    setReportOpen,
    versionHistory,
    versionHistoryOpen,
    setVersionHistoryOpen,
    // Selection counts
    selectedCount,
    // Undo/redo
    canUndo,
    canRedo,
    handleUndo,
    handleRedo,
    entityHistory,
    imageHistory,
    // Actions
    selectAll,
    deselectAll,
    toggleBox,
    removeEntity,
    handleRerunNer,
    handleRedact,
    handleReset,
    handleDownload,
    // Dropzone
    dropzone,
    // Image
    imageUrl,
    redactedImageUrl,
    mergeVisibleBoxes,
    openPopout,
    // Recognition (pass-through)
    recognition,
  };
}
