// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { showToast } from '@/components/Toast';
import { t } from '@/i18n';
import { useServiceHealth, type ServicesHealth } from '@/hooks/use-service-health';
import { authFetch, downloadFile } from '@/services/api-client';
import type { VersionHistoryEntry } from '@/types';
import { localizeErrorMessage } from '@/utils/localizeError';
import { safeJson } from '../utils';
import type { RedactionResult } from '../types';
import { usePlaygroundEntities } from './use-playground-entities';
import { usePlaygroundFile } from './use-playground-file';
import { usePlaygroundHistory } from './use-playground-history';
import { usePlaygroundImage } from './use-playground-image';
import { usePlaygroundRecognition } from './use-playground-recognition';

type ServiceKey = keyof ServicesHealth['services'];

const BLOCKING_SERVICE_STATUSES = new Set(['offline', 'degraded']);

function isServiceBlocked(health: ServicesHealth | null, key: ServiceKey) {
  const status = health?.services[key]?.status;
  return typeof status === 'string' && BLOCKING_SERVICE_STATUSES.has(status);
}

function serviceLabel(health: ServicesHealth, key: ServiceKey) {
  const service = health.services[key];
  if (!service) return String(key);
  return `${t(`health.service.${key}`)}：${t(`health.${service.status}`)}`;
}

export function usePlayground() {
  const recognition = usePlaygroundRecognition();
  const { health, checking: healthChecking } = useServiceHealth();

  const latestOcrHasTypesRef = useRef(recognition.selectedOcrHasTypes);
  const latestHasImageTypesRef = useRef(recognition.selectedHasImageTypes);
  const latestVlmTypesRef = useRef(recognition.selectedVlmTypes);
  const latestSelectedTypesRef = recognition.selectedTypesRef;
  latestOcrHasTypesRef.current = recognition.selectedOcrHasTypes;
  latestHasImageTypesRef.current = recognition.selectedHasImageTypes;
  latestVlmTypesRef.current = recognition.selectedVlmTypes;

  const entityCtx = usePlaygroundEntities();

  const [redactionReport, setRedactionReport] = useState<Record<string, unknown> | null>(null);
  const [reportOpen, setReportOpen] = useState(false);
  const [versionHistory, setVersionHistory] = useState<VersionHistoryEntry[]>([]);
  const [versionHistoryOpen, setVersionHistoryOpen] = useState(false);
  const [redactedCount, setRedactedCount] = useState(0);
  const [entityMap, setEntityMap] = useState<Record<string, string>>({});
  const [redactionVersion, setRedactionVersion] = useState(0);
  const [resetConfirmOpen, setResetConfirmOpen] = useState(false);
  const latestFileIdRef = useRef<string | null>(null);
  const asyncResultEpochRef = useRef(0);
  const redactionAbortRef = useRef<AbortController | null>(null);
  const redactionInFlightRef = useRef(false);

  const getRecognitionBlocker = useCallback(
    (file: { fileType: string; isScanned: boolean; content: string }) => {
      if (!health || healthChecking) return null;

      const requiredServices = new Set<ServiceKey>();
      const isImage = file.fileType === 'image' || file.isScanned;
      if (isImage) {
        if (latestOcrHasTypesRef.current.length > 0) {
          requiredServices.add('paddle_ocr');
          requiredServices.add('has_ner');
        }
        if (latestHasImageTypesRef.current.length > 0) {
          requiredServices.add('has_image');
        }
        if (latestVlmTypesRef.current.length > 0) {
          requiredServices.add('vlm');
        }
      } else if (file.content && latestSelectedTypesRef.current.length > 0) {
        requiredServices.add('has_ner');
      }

      const blocked = [...requiredServices].filter((key) => isServiceBlocked(health, key));
      if (blocked.length === 0) return null;

      return t('playground.recognitionPausedModelServices').replace(
        '{services}',
        blocked.map((key) => serviceLabel(health, key)).join(', '),
      );
    },
    [health, healthChecking, latestSelectedTypesRef],
  );

  const fileCtx = usePlaygroundFile({
    latestOcrHasTypesRef,
    latestHasImageTypesRef,
    latestVlmTypesRef,
    latestSelectedTypesRef,
    resetEntityHistory: entityCtx.entityHistory.reset,
    resetImageHistory: () => imageCtx.imageHistory.reset(),
    setEntities: entityCtx.setEntities,
    setBoundingBoxes: (val) => imageCtx.setBoundingBoxes(val),
    getRecognitionBlocker,
  });

  const imageCtx = usePlaygroundImage({
    fileInfo: fileCtx.fileInfo,
    redactionVersion,
    showRedactedPreview: fileCtx.stage === 'result',
  });

  const { setTypeTab } = recognition;
  useEffect(() => {
    setTypeTab(fileCtx.isImageMode ? 'vision' : 'text');
  }, [fileCtx.isImageMode, setTypeTab]);

  useEffect(() => {
    latestFileIdRef.current = fileCtx.fileInfo?.file_id ?? null;
    asyncResultEpochRef.current += 1;
  }, [fileCtx.fileInfo?.file_id]);

  useEffect(
    () => () => {
      redactionAbortRef.current?.abort();
    },
    [],
  );

  const allSelectedVisionTypes = useMemo(
    () => [
      ...recognition.selectedOcrHasTypes,
      ...recognition.selectedHasImageTypes,
      ...recognition.selectedVlmTypes,
    ],
    [
      recognition.selectedOcrHasTypes,
      recognition.selectedHasImageTypes,
      recognition.selectedVlmTypes,
    ],
  );

  const historyCtx = usePlaygroundHistory({
    isImageMode: fileCtx.isImageMode,
    entities: entityCtx.entities,
    setEntities: entityCtx.setEntities,
    boundingBoxes: imageCtx.boundingBoxes,
    visibleBoxes: imageCtx.visibleBoxes,
    setBoundingBoxes: imageCtx.setBoundingBoxes,
    entityHistory: entityCtx.entityHistory,
    imageHistory: imageCtx.imageHistory,
    allSelectedVisionTypes,
  });

  const canApplyAsyncResult = useCallback((fileId: string, epoch: number) => {
    return latestFileIdRef.current === fileId && asyncResultEpochRef.current === epoch;
  }, []);

  const handleRerunNer = useCallback(async () => {
    if (!fileCtx.fileInfo) return;
    const blocker = getRecognitionBlocker({
      fileType: fileCtx.fileInfo.file_type || '',
      isScanned: Boolean(fileCtx.fileInfo.is_scanned),
      content: fileCtx.content,
    });
    if (blocker) {
      fileCtx.setRecognitionIssue(blocker);
      showToast(blocker, 'info');
      return;
    }
    fileCtx.setRecognitionIssue(null);
    if (fileCtx.isImageMode) {
      await imageCtx.handleRerunNerImage(
        fileCtx.fileInfo.file_id,
        recognition.selectedOcrHasTypes,
        recognition.selectedHasImageTypes,
        recognition.selectedVlmTypes,
        fileCtx.setIsLoading,
        fileCtx.setLoadingMessage,
      );
    } else {
      await entityCtx.handleRerunNerText(
        fileCtx.fileInfo.file_id,
        recognition.selectedTypesRef.current,
        fileCtx.setIsLoading,
        fileCtx.setLoadingMessage,
      );
    }
  }, [entityCtx, fileCtx, getRecognitionBlocker, imageCtx, recognition]);

  const presetSeqRef = useRef(recognition.presetApplySeq);
  useEffect(() => {
    if (recognition.presetApplySeq === presetSeqRef.current) return;
    presetSeqRef.current = recognition.presetApplySeq;
    if (!fileCtx.fileInfo || fileCtx.isLoading) return;
    if (fileCtx.stage !== 'preview') return;
    void handleRerunNer();
  }, [
    recognition.presetApplySeq,
    fileCtx.fileInfo,
    fileCtx.isLoading,
    fileCtx.stage,
    handleRerunNer,
  ]);

  const handleRedact = useCallback(async () => {
    if (!fileCtx.fileInfo) return;
    if (redactionInFlightRef.current) return;

    redactionAbortRef.current?.abort();
    const controller = new AbortController();
    redactionAbortRef.current = controller;
    redactionInFlightRef.current = true;
    const { signal } = controller;

    const fileId = fileCtx.fileInfo.file_id;
    fileCtx.setIsLoading(true);
    fileCtx.setLoadingMessage(t('playground.redacting'));

    try {
      const selectedEntities = entityCtx.entities.filter((e) => e.selected !== false);
      const selectedBoxes = imageCtx.boundingBoxes.filter((b) => b.selected !== false);
      const requestedRedactionItemCount = fileCtx.isImageMode
        ? selectedBoxes.length
        : selectedEntities.length;

      const res = await authFetch('/api/v1/redaction/execute', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          file_id: fileId,
          entities: entityCtx.entities,
          bounding_boxes: imageCtx.boundingBoxes,
          config: {
            replacement_mode: recognition.replacementMode,
            entity_types: [],
            custom_replacements: {},
          },
        }),
        signal,
      });
      if (signal.aborted) return;

      if (!res.ok) throw new Error(t('playground.redactFailed'));
      const result = await safeJson<RedactionResult>(res);
      if (signal.aborted) return;
      const completedCount = requestedRedactionItemCount;
      setEntityMap(result.entity_map || {});
      setRedactedCount(completedCount);
      setRedactionVersion((version) => version + 1);
      fileCtx.setStage('result');

      latestFileIdRef.current = fileId;
      const asyncResultEpoch = asyncResultEpochRef.current + 1;
      asyncResultEpochRef.current = asyncResultEpoch;

      const loadAsyncResult = async <T>(url: string): Promise<T> => {
        const response = await authFetch(url, { signal });
        if (signal.aborted) {
          throw new DOMException('Aborted', 'AbortError');
        }
        if (!response.ok) {
          throw new Error(`Failed to load ${url}`);
        }
        return safeJson<T>(response);
      };

      loadAsyncResult<Record<string, unknown>>(`/api/v1/redaction/${fileId}/report`)
        .then((data) => {
          if (canApplyAsyncResult(fileId, asyncResultEpoch)) {
            setRedactionReport(data);
          }
        })
        .catch(() => {
          if (canApplyAsyncResult(fileId, asyncResultEpoch)) {
            setRedactionReport(null);
          }
        });

      loadAsyncResult<{ versions?: VersionHistoryEntry[] }>(`/api/v1/redaction/${fileId}/versions`)
        .then((data) => {
          if (canApplyAsyncResult(fileId, asyncResultEpoch)) {
            setVersionHistory(data.versions || []);
          }
        })
        .catch(() => {
          if (canApplyAsyncResult(fileId, asyncResultEpoch)) {
            setVersionHistory([]);
          }
        });

      showToast(
        t('playground.toast.redactDone').replace('{count}', String(completedCount)),
        'success',
      );
    } catch (err) {
      if (signal.aborted) return;
      showToast(localizeErrorMessage(err, 'playground.redactFailed'), 'error');
    } finally {
      if (redactionAbortRef.current === controller) {
        redactionAbortRef.current = null;
      }
      redactionInFlightRef.current = false;
      if (!signal.aborted) {
        fileCtx.setIsLoading(false);
        fileCtx.setLoadingMessage('');
      }
    }
  }, [
    canApplyAsyncResult,
    entityCtx.entities,
    fileCtx,
    imageCtx.boundingBoxes,
    recognition.replacementMode,
  ]);

  const cancelProcessing = useCallback(() => {
    asyncResultEpochRef.current += 1;
    redactionAbortRef.current?.abort();
    redactionAbortRef.current = null;
    redactionInFlightRef.current = false;
    fileCtx.cancelProcessing(false);
    entityCtx.cancelRerunNerText();
    imageCtx.cancelRerunNerImage();
    fileCtx.setIsLoading(false);
    fileCtx.setLoadingMessage('');
    showToast(t('playground.cancelled'), 'info');
  }, [entityCtx, fileCtx, imageCtx]);

  const hasResetRisk = useMemo(
    () =>
      fileCtx.stage !== 'upload' ||
      fileCtx.fileInfo !== null ||
      fileCtx.content.length > 0 ||
      entityCtx.entities.length > 0 ||
      imageCtx.boundingBoxes.length > 0 ||
      redactedCount > 0 ||
      Object.keys(entityMap).length > 0 ||
      redactionReport !== null ||
      versionHistory.length > 0,
    [
      entityCtx.entities.length,
      entityMap,
      fileCtx.content.length,
      fileCtx.fileInfo,
      fileCtx.stage,
      imageCtx.boundingBoxes.length,
      redactedCount,
      redactionReport,
      versionHistory.length,
    ],
  );

  const performReset = useCallback(() => {
    asyncResultEpochRef.current += 1;
    latestFileIdRef.current = null;
    redactionAbortRef.current?.abort();
    redactionAbortRef.current = null;
    redactionInFlightRef.current = false;
    setResetConfirmOpen(false);
    fileCtx.setStage('upload');
    fileCtx.setFileInfo(null);
    fileCtx.setContent('');
    entityCtx.setEntities([]);
    setRedactedCount(0);
    setEntityMap({});
    setRedactionVersion(0);
    setRedactionReport(null);
    setReportOpen(false);
    entityCtx.entityHistory.reset();
    imageCtx.setBoundingBoxes([]);
    imageCtx.imageHistory.reset();
    setVersionHistory([]);
    setVersionHistoryOpen(false);
  }, [entityCtx, fileCtx, imageCtx]);

  const handleReset = useCallback(() => {
    if (hasResetRisk) {
      setResetConfirmOpen(true);
      return;
    }
    performReset();
  }, [hasResetRisk, performReset]);

  const confirmReset = useCallback(() => {
    performReset();
  }, [performReset]);

  const cancelReset = useCallback(() => {
    setResetConfirmOpen(false);
  }, []);

  const handleDownload = useCallback(() => {
    if (!fileCtx.fileInfo) return;
    downloadFile(
      `/api/v1/files/${fileCtx.fileInfo.file_id}/download?redacted=true`,
      `redacted_${fileCtx.fileInfo.filename}`,
    ).catch((err) => {
      showToast(localizeErrorMessage(err, 'common.downloadFailed'), 'error');
    });
  }, [fileCtx.fileInfo]);

  const openPopout = useCallback(() => {
    imageCtx.openPopout(recognition.visionTypes);
  }, [imageCtx, recognition.visionTypes]);

  return {
    stage: fileCtx.stage,
    setStage: fileCtx.setStage,
    fileInfo: fileCtx.fileInfo,
    content: fileCtx.content,
    isImageMode: fileCtx.isImageMode,
    entities: entityCtx.entities,
    setEntities: entityCtx.setEntities,
    applyEntities: entityCtx.applyEntities,
    boundingBoxes: imageCtx.boundingBoxes,
    setBoundingBoxes: imageCtx.setBoundingBoxes,
    visibleBoxes: imageCtx.visibleBoxes,
    isLoading: fileCtx.isLoading,
    loadingMessage: fileCtx.loadingMessage,
    uploadIssue: fileCtx.uploadIssue,
    recognitionIssue: fileCtx.recognitionIssue,
    entityMap,
    redactedCount,
    redactionReport,
    reportOpen,
    setReportOpen,
    versionHistory,
    versionHistoryOpen,
    setVersionHistoryOpen,
    selectedCount: historyCtx.selectedCount,
    canUndo: historyCtx.canUndo,
    canRedo: historyCtx.canRedo,
    handleUndo: historyCtx.handleUndo,
    handleRedo: historyCtx.handleRedo,
    entityHistory: entityCtx.entityHistory,
    imageHistory: imageCtx.imageHistory,
    selectAll: historyCtx.selectAll,
    deselectAll: historyCtx.deselectAll,
    toggleBox: imageCtx.toggleBox,
    removeEntity: entityCtx.removeEntity,
    handleRerunNer,
    handleRedact,
    cancelProcessing,
    handleReset,
    resetConfirmOpen,
    confirmReset,
    cancelReset,
    handleDownload,
    dropzone: fileCtx.dropzone,
    imageUrl: imageCtx.imageUrl,
    redactedImageUrl: imageCtx.redactedImageUrl,
    redactedImageError: imageCtx.redactedImageError,
    currentPage: imageCtx.currentPage,
    setCurrentPage: imageCtx.setCurrentPage,
    totalPages: imageCtx.totalPages,
    mergeVisibleBoxes: imageCtx.mergeVisibleBoxes,
    openPopout,
    recognition,
  };
}
