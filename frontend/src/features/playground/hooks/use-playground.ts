
import { useState, useCallback, useRef, useMemo } from 'react';
import {
  authFetch,
  downloadFile,
} from '@/services/api-client';
import { showToast } from '@/components/Toast';
import { t } from '@/i18n';
import { localizeErrorMessage } from '@/utils/localizeError';
import { safeJson } from '../utils';
import { usePlaygroundRecognition } from './use-playground-recognition';
import { usePlaygroundFile } from './use-playground-file';
import { usePlaygroundEntities } from './use-playground-entities';
import { usePlaygroundImage } from './use-playground-image';
import { usePlaygroundHistory } from './use-playground-history';
import type { VersionHistoryEntry } from '@/types';
import { useEffect } from 'react';

export function usePlayground() {

  const recognition = usePlaygroundRecognition();

  // --- Refs for latest recognition state (used in async callbacks) ---
  const latestOcrHasTypesRef = useRef(recognition.selectedOcrHasTypes);
  const latestHasImageTypesRef = useRef(recognition.selectedHasImageTypes);
  const latestSelectedTypesRef = useRef(recognition.selectedTypes);
  latestOcrHasTypesRef.current = recognition.selectedOcrHasTypes;
  latestHasImageTypesRef.current = recognition.selectedHasImageTypes;
  latestSelectedTypesRef.current = recognition.selectedTypes;

  // --- Entity management ---
  const entityCtx = usePlaygroundEntities();

  // --- Image management (needs fileInfo, but fileInfo comes from file hook) ---
  // We pass a temporary null; the image hook uses fileInfo reactively via its effect deps.
  // However, fileInfo is set by the file hook, so we need a shared state approach.
  // We'll use the file hook's fileInfo which is returned.

  // Since hooks cannot be called conditionally, we need to structure carefully.
  // The image hook needs fileInfo from the file hook. Let's use a separate state that
  // both hooks can reference.

  const [redactionReport, setRedactionReport] = useState<Record<string, unknown> | null>(null);
  const [reportOpen, setReportOpen] = useState(false);
  const [versionHistory, setVersionHistory] = useState<VersionHistoryEntry[]>([]);
  const [versionHistoryOpen, setVersionHistoryOpen] = useState(false);
  const [redactedCount, setRedactedCount] = useState(0);
  const [entityMap, setEntityMap] = useState<Record<string, string>>({});

  // --- File management ---
  const fileCtx = usePlaygroundFile({
    latestOcrHasTypesRef,
    latestHasImageTypesRef,
    latestSelectedTypesRef,
    resetEntityHistory: entityCtx.entityHistory.reset,
    resetImageHistory: () => imageCtx.imageHistory.reset(),
    setEntities: entityCtx.setEntities,
    setBoundingBoxes: (val) => imageCtx.setBoundingBoxes(val),
  });

  // --- Image management ---
  const imageCtx = usePlaygroundImage({
    fileInfo: fileCtx.fileInfo,
  });

  // --- Auto-switch type tab on file mode ---
  useEffect(() => {
    recognition.setTypeTab(fileCtx.isImageMode ? 'vision' : 'text');
  }, [fileCtx.isImageMode, recognition.setTypeTab]);

  // --- History / undo-redo / selection ---
  const allSelectedVisionTypes = useMemo(
    () => [...recognition.selectedOcrHasTypes, ...recognition.selectedHasImageTypes],
    [recognition.selectedOcrHasTypes, recognition.selectedHasImageTypes],
  );

  const historyCtx = usePlaygroundHistory({
    isImageMode: fileCtx.isImageMode,
    entities: entityCtx.entities,
    setEntities: entityCtx.setEntities,
    boundingBoxes: imageCtx.boundingBoxes,
    setBoundingBoxes: imageCtx.setBoundingBoxes,
    entityHistory: entityCtx.entityHistory,
    imageHistory: imageCtx.imageHistory,
    allSelectedVisionTypes,
  });

  // --- Re-run recognition (delegates to entity or image sub-hook) ---
  const handleRerunNer = useCallback(async () => {
    if (!fileCtx.fileInfo) return;
    if (fileCtx.isImageMode) {
      await imageCtx.handleRerunNerImage(
        fileCtx.fileInfo.file_id,
        recognition.selectedOcrHasTypes,
        recognition.selectedHasImageTypes,
        fileCtx.setIsLoading,
        fileCtx.setLoadingMessage,
      );
    } else {
      await entityCtx.handleRerunNerText(
        fileCtx.fileInfo.file_id,
        recognition.selectedTypes,
        fileCtx.setIsLoading,
        fileCtx.setLoadingMessage,
      );
    }
  }, [fileCtx, entityCtx, imageCtx, recognition]);

  // --- Auto re-run NER when a preset is applied (and a file is loaded) ---
  const presetSeqRef = useRef(recognition.presetApplySeq);
  useEffect(() => {
    if (recognition.presetApplySeq === presetSeqRef.current) return;
    presetSeqRef.current = recognition.presetApplySeq;
    if (!fileCtx.fileInfo || fileCtx.isLoading) return;
    if (fileCtx.stage !== 'preview') return;
    void handleRerunNer();
  }, [recognition.presetApplySeq, fileCtx.fileInfo, fileCtx.isLoading, fileCtx.stage, handleRerunNer]);

  // --- Execute redaction ---
  const handleRedact = useCallback(async () => {
    if (!fileCtx.fileInfo) return;
    fileCtx.setIsLoading(true);
    fileCtx.setLoadingMessage(t('playground.redacting') || '正在执行脱敏...');

    try {
      const selectedEntities = entityCtx.entities.filter(e => e.selected);
      const selectedBoxes = imageCtx.boundingBoxes.filter(b => b.selected);

      const res = await authFetch('/api/v1/redaction/execute', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          file_id: fileCtx.fileInfo.file_id,
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
      fileCtx.setStage('result');

      authFetch(`/api/v1/redaction/${fileCtx.fileInfo.file_id}/report`)
        .then(r => r.json())
        .then(data => setRedactionReport(data))
        .catch(() => setRedactionReport(null));

      authFetch(`/api/v1/redaction/${fileCtx.fileInfo.file_id}/versions`)
        .then(r => r.json())
        .then(data => setVersionHistory(data.versions || []))
        .catch(() => setVersionHistory([]));

      showToast(`完成，共处理 ${result.redacted_count} 处`, 'success');
    } catch (err) {
      showToast(localizeErrorMessage(err, 'playground.redactFailed'), 'error');
    } finally {
      fileCtx.setIsLoading(false);
      fileCtx.setLoadingMessage('');
    }
  }, [fileCtx, entityCtx.entities, imageCtx.boundingBoxes, recognition.replacementMode]);

  // --- Reset ---
  const handleReset = useCallback(() => {
    fileCtx.setStage('upload');
    fileCtx.setFileInfo(null);
    fileCtx.setContent('');
    entityCtx.setEntities([]);
    setRedactedCount(0);
    setEntityMap({});
    setRedactionReport(null);
    setReportOpen(false);
    entityCtx.entityHistory.reset();
    imageCtx.setBoundingBoxes([]);
    imageCtx.imageHistory.reset();
    setVersionHistory([]);
    setVersionHistoryOpen(false);
  }, [fileCtx, entityCtx, imageCtx]);

  // --- Download ---
  const handleDownload = useCallback(() => {
    if (!fileCtx.fileInfo) return;
    downloadFile(
      `/api/v1/files/${fileCtx.fileInfo.file_id}/download?redacted=true`,
      `redacted_${fileCtx.fileInfo.filename}`,
    ).catch(() => {});
  }, [fileCtx.fileInfo]);

  // --- Popout wrapper (binds recognition.visionTypes) ---
  const openPopout = useCallback(() => {
    imageCtx.openPopout(recognition.visionTypes);
  }, [imageCtx, recognition.visionTypes]);

  return {
    // Stage
    stage: fileCtx.stage,
    setStage: fileCtx.setStage,
    // File info
    fileInfo: fileCtx.fileInfo,
    content: fileCtx.content,
    isImageMode: fileCtx.isImageMode,
    // Entities & boxes
    entities: entityCtx.entities,
    setEntities: entityCtx.setEntities,
    applyEntities: entityCtx.applyEntities,
    boundingBoxes: imageCtx.boundingBoxes,
    setBoundingBoxes: imageCtx.setBoundingBoxes,
    visibleBoxes: imageCtx.visibleBoxes,
    // Loading
    isLoading: fileCtx.isLoading,
    loadingMessage: fileCtx.loadingMessage,
    loadingElapsedSec: fileCtx.loadingElapsedSec,
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
    selectedCount: historyCtx.selectedCount,
    // Undo/redo
    canUndo: historyCtx.canUndo,
    canRedo: historyCtx.canRedo,
    handleUndo: historyCtx.handleUndo,
    handleRedo: historyCtx.handleRedo,
    entityHistory: entityCtx.entityHistory,
    imageHistory: imageCtx.imageHistory,
    // Actions
    selectAll: historyCtx.selectAll,
    deselectAll: historyCtx.deselectAll,
    toggleBox: imageCtx.toggleBox,
    removeEntity: entityCtx.removeEntity,
    handleRerunNer,
    handleRedact,
    handleReset,
    handleDownload,
    // Dropzone
    dropzone: fileCtx.dropzone,
    // Image
    imageUrl: imageCtx.imageUrl,
    redactedImageUrl: imageCtx.redactedImageUrl,
    mergeVisibleBoxes: imageCtx.mergeVisibleBoxes,
    openPopout,
    // Recognition (pass-through)
    recognition,
  };
}
