// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { useCallback, useEffect, useRef, useState } from 'react';
import { t } from '@/i18n';
import { localizeErrorMessage } from '@/utils/localizeError';
import type { BoundingBox as EditorBox } from '@/components/ImageBBoxEditor';
import { fileApi, getBatchZipManifest } from '@/services/api';
import type { BatchWizardMode, BatchWizardPersistedConfig } from '@/services/batchPipeline';
import {
  submitJob as apiSubmitJob,
  commitItemReview,
  getJob,
  type JobItemRow,
  requeueFailed,
  updateJobDraft,
} from '@/services/jobsApi';
import { buildPreviewDownloadBlob } from '../lib/batch-preview-fixtures';
import { findNextPendingReviewIndex, findFirstPendingReviewIndex } from '../lib/review-navigation';
import { RECOGNITION_DONE_STATUSES, type BatchRow, type ReviewEntity, type Step } from '../types';
import { isBatchImageMode, resolveBatchFileType } from '../utils/file-type';
import {
  buildJobConfigForWorker,
  clearLocalWizardMaxStep,
  deriveReviewConfirmed,
  isJobConfigLockedError,
  mapBackendStatus,
  triggerDownload,
} from './use-batch-wizard-utils';

const FIRST_REVIEWABLE_FAST_POLL_MS = 250;
const FIRST_REVIEWABLE_FAST_POLL_TIMEOUT_MS = 20_000;

function selectedPayloadCount(items: Array<{ selected?: boolean }>): number {
  return items.reduce((count, item) => count + (item.selected === false ? 0 : 1), 0);
}

function applyAuthoritativeJobItems(rows: BatchRow[], items: JobItemRow[]): BatchRow[] {
  const itemByFileId = new Map(items.map((item) => [item.file_id, item]));
  return rows.map((row) => {
    const item = itemByFileId.get(row.file_id);
    if (!item) return row;
    const fileType = resolveBatchFileType(item.file_type ?? row.file_type);
    return {
      ...row,
      analyzeStatus: mapBackendStatus(item.status),
      analyzeError: item.error_message || undefined,
      has_output: Boolean(item.has_output),
      reviewConfirmed: deriveReviewConfirmed(item),
      hasReviewDraft: Boolean(item.has_review_draft),
      file_type: fileType,
      isImageMode: isBatchImageMode(fileType),
      entity_count: typeof item.entity_count === 'number' ? item.entity_count : row.entity_count,
      recognitionStage: item.progress_stage ?? row.recognitionStage,
      recognitionCurrent:
        typeof item.progress_current === 'number' ? item.progress_current : row.recognitionCurrent,
      recognitionTotal:
        typeof item.progress_total === 'number' ? item.progress_total : row.recognitionTotal,
      recognitionMessage: item.progress_message ?? row.recognitionMessage,
    };
  });
}

export interface BatchSubmitState {
  submitQueueToWorker: () => Promise<void>;
  requeueFailedItems: () => Promise<void>;
  confirmCurrentReview: () => Promise<void>;
  downloadZip: (redacted: boolean) => Promise<void>;
  zipLoading: boolean;
}

export function useBatchSubmit(
  mode: BatchWizardMode,
  activeJobId: string | null,
  isPreviewMode: boolean,
  cfg: BatchWizardPersistedConfig,
  furthestStep: Step,
  rows: BatchRow[],
  setRows: React.Dispatch<React.SetStateAction<BatchRow[]>>,
  selected: Set<string>,
  setMsg: (msg: { text: string; tone: 'neutral' | 'ok' | 'warn' | 'err' } | null) => void,
  setFurthestStep: React.Dispatch<React.SetStateAction<Step>>,
  failedRows: BatchRow[],
  reviewFile: BatchRow | null,
  setReviewIndex: React.Dispatch<React.SetStateAction<number>>,
  doneRows: BatchRow[],
  reviewEntities: ReviewEntity[],
  reviewBoxes: EditorBox[],
  reviewDraftError: string | null,
  flushCurrentReviewDraft: () => Promise<boolean>,
  reviewLastSavedJsonRef: React.MutableRefObject<string>,
  reviewDraftDirtyRef: React.MutableRefObject<boolean>,
  setReviewExecuteLoading: React.Dispatch<React.SetStateAction<boolean>>,
  itemIdByFileIdRef: React.MutableRefObject<Record<string, string>>,
  lastSavedJobConfigJson: React.MutableRefObject<string>,
  setJobConfigLocked: React.Dispatch<React.SetStateAction<boolean>> = () => {},
): BatchSubmitState {
  const [zipLoading, setZipLoading] = useState(false);
  const rowsRef = useRef(rows);
  const firstReviewablePollRunRef = useRef(0);

  useEffect(() => {
    rowsRef.current = rows;
  }, [rows]);

  useEffect(() => {
    return () => {
      firstReviewablePollRunRef.current += 1;
    };
  }, [activeJobId]);

  const applyJobItemsToRows = useCallback(
    (items: JobItemRow[]) => {
      if (!items.length) return false;
      const itemByFileId = new Map(items.map((item) => [item.file_id, item]));
      const mappedReviewable = rowsRef.current.some((row) => {
        const item = itemByFileId.get(row.file_id);
        return Boolean(item && RECOGNITION_DONE_STATUSES.has(mapBackendStatus(item.status)));
      });
      itemIdByFileIdRef.current = {
        ...itemIdByFileIdRef.current,
        ...Object.fromEntries(items.map((item) => [item.file_id, item.id])),
      };
      setRows((prev) => {
        const next = applyAuthoritativeJobItems(prev, items);
        rowsRef.current = next;
        return next;
      });
      return mappedReviewable;
    },
    [itemIdByFileIdRef, setRows],
  );

  const startFirstReviewableFastPoll = useCallback(
    (jobId: string, initialDelayMs = 0) => {
      const runId = firstReviewablePollRunRef.current + 1;
      firstReviewablePollRunRef.current = runId;
      const startedAt = Date.now();

      const poll = async () => {
        if (firstReviewablePollRunRef.current !== runId) return;
        try {
          const detail = await getJob(jobId);
          if (firstReviewablePollRunRef.current !== runId) return;
          if (applyJobItemsToRows(detail.items)) return;
        } catch {
          /* best-effort latency optimization; regular polling still owns correctness */
        }
        if (
          firstReviewablePollRunRef.current === runId &&
          Date.now() - startedAt < FIRST_REVIEWABLE_FAST_POLL_TIMEOUT_MS
        ) {
          window.setTimeout(() => {
            void poll();
          }, FIRST_REVIEWABLE_FAST_POLL_MS);
        }
      };

      if (initialDelayMs > 0) {
        window.setTimeout(() => {
          void poll();
        }, initialDelayMs);
      } else {
        void poll();
      }
    },
    [applyJobItemsToRows],
  );

  // ── Queue submit ──
  const submitQueueToWorker = useCallback(async () => {
    if (isPreviewMode) {
      setRows((prev) =>
        prev.map((row, index) => ({
          ...row,
          analyzeStatus: index === 0 ? 'completed' : 'awaiting_review',
          has_output: index === 0,
          reviewConfirmed: index === 0,
        })),
      );
      setFurthestStep(5);
      setMsg({ text: t('batchWizard.previewRecognitionDone'), tone: 'ok' });
      return;
    }
    if (!activeJobId) {
      setMsg({ text: t('batchWizard.noActiveJob'), tone: 'warn' });
      return;
    }
    setMsg(null);
    setRows((prev) =>
      prev.map((r) =>
        !RECOGNITION_DONE_STATUSES.has(r.analyzeStatus) && r.analyzeStatus !== 'failed'
          ? { ...r, analyzeStatus: 'pending' as const }
          : r,
      ),
    );
    try {
      const jobCfg = buildJobConfigForWorker(cfg, mode, furthestStep);
      try {
        await updateJobDraft(activeJobId, { config: jobCfg });
        lastSavedJobConfigJson.current = JSON.stringify(jobCfg);
      } catch (e) {
        if (isJobConfigLockedError(e)) {
          setMsg({ text: t('batchWizard.configLocked'), tone: 'warn' });
          return;
        }
        throw e;
      }
      const shouldFastPollFirstReviewable = !rowsRef.current.some((row) =>
        RECOGNITION_DONE_STATUSES.has(row.analyzeStatus),
      );
      const submitPromise = apiSubmitJob(activeJobId);
      if (shouldFastPollFirstReviewable) {
        startFirstReviewableFastPoll(activeJobId, 50);
      }
      await submitPromise;
      if (
        shouldFastPollFirstReviewable &&
        !rowsRef.current.some((row) => RECOGNITION_DONE_STATUSES.has(row.analyzeStatus))
      ) {
        startFirstReviewableFastPoll(activeJobId);
      }
      setJobConfigLocked(true);
      clearLocalWizardMaxStep(activeJobId);
    } catch (e) {
      firstReviewablePollRunRef.current += 1;
      setMsg({ text: localizeErrorMessage(e, 'batchWizard.submitFailed'), tone: 'err' });
    }
  }, [
    activeJobId,
    cfg,
    furthestStep,
    isPreviewMode,
    mode,
    lastSavedJobConfigJson,
    setJobConfigLocked,
    setFurthestStep,
    setMsg,
    setRows,
    startFirstReviewableFastPoll,
  ]);

  // ── Requeue failed ──
  const requeueFailedItems = useCallback(async () => {
    if (!failedRows.length) return;
    if (isPreviewMode) {
      setRows((prev) =>
        prev.map((row) =>
          row.analyzeStatus === 'failed'
            ? { ...row, analyzeStatus: 'awaiting_review', analyzeError: undefined }
            : row,
        ),
      );
      setMsg({ text: t('batchWizard.previewRecognitionDone'), tone: 'ok' });
      return;
    }
    if (!activeJobId) {
      setMsg({ text: t('batchWizard.noActiveJob'), tone: 'warn' });
      return;
    }
    setMsg(null);
    try {
      await requeueFailed(activeJobId);
      setRows((prev) =>
        prev.map((r) =>
          r.analyzeStatus === 'failed'
            ? { ...r, analyzeStatus: 'pending', analyzeError: undefined }
            : r,
        ),
      );
      setMsg({ text: t('batchWizard.requeueFailedQueued'), tone: 'ok' });
    } catch (e) {
      setMsg({ text: localizeErrorMessage(e, 'batchWizard.requeueFailedFailed'), tone: 'err' });
    }
  }, [activeJobId, failedRows.length, isPreviewMode, setMsg, setRows]);

  // ── Confirm review ──
  const confirmCurrentReview = useCallback(async () => {
    if (!reviewFile) return;
    setReviewExecuteLoading(true);
    setMsg(null);
    const currentFileId = reviewFile.file_id;
    const currentIsImage = reviewFile.isImageMode;
    const currentSelectedCount = currentIsImage
      ? selectedPayloadCount(reviewBoxes)
      : selectedPayloadCount(reviewEntities);
    try {
      if (isPreviewMode) {
        setRows((prev) =>
          prev.map((row) =>
            row.file_id === currentFileId
              ? {
                  ...row,
                  reviewConfirmed: true,
                  has_output: true,
                  analyzeStatus: 'completed' as const,
                  entity_count: currentSelectedCount,
                }
              : row,
          ),
        );
        const nextPendingIndex = findNextPendingReviewIndex(doneRows, currentFileId);
        if (nextPendingIndex >= 0) {
          setReviewIndex(nextPendingIndex);
        } else {
          setFurthestStep(5);
        }
        setMsg({ text: t('batchWizard.previewReviewDone'), tone: 'ok' });
        return;
      }
      const jid = activeJobId;
      const linkedItemId = itemIdByFileIdRef.current[currentFileId];
      if (!jid || !linkedItemId) throw new Error(t('batchWizard.noLinkedItem'));
      const entitiesPayload = reviewEntities.map((e) => ({
        id: e.id,
        text: e.text,
        type: e.type,
        start: e.start,
        end: e.end,
        page: e.page ?? 1,
        confidence: e.confidence ?? 1,
        selected: e.selected,
        source: e.source,
        coref_id: e.coref_id,
        replacement: e.replacement,
      }));
      const boxesPayload = reviewBoxes.map((b) => ({
        id: b.id,
        x: b.x,
        y: b.y,
        width: b.width,
        height: b.height,
        page: Number(b.page || 1),
        type: b.type,
        text: b.text,
        selected: b.selected,
        source: b.source,
        confidence: b.confidence,
        evidence_source: b.evidence_source,
        source_detail: b.source_detail,
        warnings: b.warnings,
      }));
      const confirmedEntityCount = currentSelectedCount;

      const ok = await flushCurrentReviewDraft();
      if (!ok) throw new Error(reviewDraftError || t('batchWizard.autoSaveFailed'));
      setRows((prev) =>
        prev.map((r) =>
          r.file_id === currentFileId
            ? {
                ...r,
                reviewConfirmed: false,
                has_output: false,
                analyzeStatus: 'redacting' as const,
              }
            : r,
        ),
      );
      const commitResult = await commitItemReview(jid, linkedItemId, {
        entities: entitiesPayload as Array<Record<string, unknown>>,
        bounding_boxes: boxesPayload as Array<Record<string, unknown>>,
      });
      const buildRowsAfterCommit = (currentRows: BatchRow[]) =>
        applyAuthoritativeJobItems(currentRows, [commitResult]).map((r) =>
          r.file_id === currentFileId
            ? {
                ...r,
                has_output: Boolean(commitResult.has_output ?? true),
                reviewConfirmed: deriveReviewConfirmed({
                  ...commitResult,
                  has_output: commitResult.has_output ?? true,
                }),
                analyzeStatus: mapBackendStatus(commitResult.status ?? 'completed'),
                entity_count: confirmedEntityCount,
              }
            : r,
        );
      const rowsAfterCommit = buildRowsAfterCommit(rowsRef.current);
      setRows((prev) => buildRowsAfterCommit(prev));
      const reviewableRowsAfterCommit = rowsAfterCommit.filter((row) =>
        RECOGNITION_DONE_STATUSES.has(row.analyzeStatus),
      );
      const currentStillPendingIndex = reviewableRowsAfterCommit.findIndex(
        (row) => row.file_id === currentFileId && row.reviewConfirmed !== true,
      );
      const nextPendingIndex =
        currentStillPendingIndex >= 0
          ? currentStillPendingIndex
          : findNextPendingReviewIndex(reviewableRowsAfterCommit, currentFileId);
      if (nextPendingIndex >= 0) setReviewIndex(nextPendingIndex);
      reviewLastSavedJsonRef.current = JSON.stringify({
        entities: entitiesPayload,
        bounding_boxes: boxesPayload,
      });
      reviewDraftDirtyRef.current = false;
      if (findFirstPendingReviewIndex(reviewableRowsAfterCommit) < 0) {
        setFurthestStep((prev) => Math.max(prev, 5) as Step);
      }
    } catch (e) {
      setRows((prev) =>
        prev.map((r) =>
          r.file_id === currentFileId
            ? {
                ...r,
                reviewConfirmed: false,
                has_output: false,
                analyzeStatus: 'awaiting_review' as const,
              }
            : r,
        ),
      );
      setMsg({ text: localizeErrorMessage(e, 'batchWizard.actionFailed'), tone: 'err' });
    } finally {
      setReviewExecuteLoading(false);
    }
  }, [
    activeJobId,
    doneRows,
    flushCurrentReviewDraft,
    isPreviewMode,
    reviewBoxes,
    reviewDraftError,
    reviewEntities,
    reviewFile,
    itemIdByFileIdRef,
    reviewDraftDirtyRef,
    reviewLastSavedJsonRef,
    setFurthestStep,
    setMsg,
    setReviewExecuteLoading,
    setReviewIndex,
    setRows,
  ]);

  // ── Download ZIP ──
  const downloadZip = useCallback(
    async (redacted: boolean) => {
      const selectedIds = rows.filter((r) => selected.has(r.file_id)).map((r) => r.file_id);
      if (!selectedIds.length) {
        setMsg({ text: t('batchWizard.noFilesSelected'), tone: 'warn' });
        return;
      }
      if (redacted) {
        const noOut = rows.filter((r) => selected.has(r.file_id) && !r.has_output);
        if (
          noOut.length === selectedIds.length ||
          (!isPreviewMode && activeJobId && noOut.length > 0)
        ) {
          setMsg({ text: t('batchWizard.someFilesNotRedacted'), tone: 'warn' });
          return;
        }
      }
      setZipLoading(true);
      setMsg(null);
      try {
        if (isPreviewMode) {
          const blob = buildPreviewDownloadBlob(
            redacted,
            rows.filter((row) => selected.has(row.file_id)),
          );
          triggerDownload(
            blob,
            redacted ? 'batch_redacted_preview.txt' : 'batch_original_preview.txt',
          );
          setMsg({ text: t('batchWizard.previewDownloadReady'), tone: 'ok' });
          return;
        }
        const blob = await fileApi.batchDownloadZip(
          selectedIds,
          redacted,
          redacted ? activeJobId : null,
        );
        triggerDownload(blob, redacted ? 'batch_redacted.zip' : 'batch_original.zip');
        const manifest = getBatchZipManifest(blob);
        if (manifest && manifest.skipped_count > 0) {
          setMsg({
            text: t('batchWizard.zipPartialDownload')
              .replace('{included}', String(manifest.included_count))
              .replace('{skipped}', String(manifest.skipped_count)),
            tone: 'warn',
          });
        } else {
          setMsg({ text: t('batchWizard.zipStarted'), tone: 'ok' });
        }
        if (redacted && activeJobId) clearLocalWizardMaxStep(activeJobId);
      } catch (e) {
        setMsg({ text: localizeErrorMessage(e, 'batchWizard.downloadFailed'), tone: 'err' });
      } finally {
        setZipLoading(false);
      }
    },
    [activeJobId, isPreviewMode, rows, selected, setMsg],
  );

  return {
    submitQueueToWorker,
    requeueFailedItems,
    confirmCurrentReview,
    downloadZip,
    zipLoading,
  };
}
