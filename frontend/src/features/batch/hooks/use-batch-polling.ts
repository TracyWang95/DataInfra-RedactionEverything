// Copyright 2026 DataInfra-RedactionEverything Contributors

import { useCallback, useEffect, useMemo, useRef } from 'react';
import { t } from '@/i18n';
import { getJob } from '@/services/jobsApi';
import {
  RECOGNITION_DONE_STATUSES,
  hasReviewableRecognitionRows,
  type BatchRow,
  type Step,
} from '../types';
import { deriveReviewConfirmed, mapBackendStatus } from './use-batch-wizard-utils';
import { isBatchImageMode, resolveBatchFileType } from '../utils/file-type';

const STEP3_FIRST_REVIEWABLE_REFRESH_MS = 250;
const STEP3_RECOGNITION_REFRESH_MS = 1000;

export type BatchJobDetail = Awaited<ReturnType<typeof getJob>>;

export interface BatchPollingState {
  refreshRowsFromActiveJob: (jobId?: string | null) => Promise<BatchJobDetail | null>;
}

export function useBatchPolling(
  step: Step,
  isPreviewMode: boolean,
  activeJobId: string | null,
  rows: BatchRow[],
  setRows: React.Dispatch<React.SetStateAction<BatchRow[]>>,
  itemIdByFileIdRef: React.MutableRefObject<Record<string, string>>,
  setJobSkipItemReview: React.Dispatch<React.SetStateAction<boolean>>,
  bulkConfirmActive: boolean,
): BatchPollingState {
  const batchImmediateRefreshRef = useRef<{
    jobId: string;
    promise: Promise<BatchJobDetail | null>;
  } | null>(null);

  const step3HasRowsNeedingRefresh = useMemo(
    () =>
      rows.some(
        (row) =>
          !RECOGNITION_DONE_STATUSES.has(row.analyzeStatus) && row.analyzeStatus !== 'failed',
      ),
    [rows],
  );
  const step3HasReviewableRows = useMemo(() => hasReviewableRecognitionRows(rows), [rows]);
  const step4HasUnsettledRows = step3HasRowsNeedingRefresh;
  // Rows confirmed via batch one-click confirm redact asynchronously. Their
  // in-flight states (review_approved/redacting) count as "recognition-done",
  // so the recognition poll below skips them — track them separately.
  const step4HasSettlingRows = useMemo(
    () =>
      rows.some(
        (row) => row.analyzeStatus === 'redacting' || row.analyzeStatus === 'review_approved',
      ),
    [rows],
  );

  const refreshRowsFromActiveJob = useCallback(
    async (jobId = activeJobId): Promise<BatchJobDetail | null> => {
      if (isPreviewMode || !jobId) return null;
      const pendingRefresh = batchImmediateRefreshRef.current;
      if (pendingRefresh?.jobId === jobId) return pendingRefresh.promise;

      const promise = (async () => {
        try {
          const detail = await getJob(jobId, { performance: false });
          const itemMap = new Map(detail.items.map((it) => [it.file_id, it]));
          itemIdByFileIdRef.current = {
            ...itemIdByFileIdRef.current,
            ...Object.fromEntries(detail.items.map((it) => [it.file_id, it.id])),
          };
          setJobSkipItemReview(Boolean(detail.skip_item_review));
          setRows((prev) => {
            let changed = false;
            const next = prev.map((row) => {
              const item = itemMap.get(row.file_id);
              if (!item) return row;
              const analyzeStatus = mapBackendStatus(item.status);
              const reviewConfirmed = deriveReviewConfirmed(item);
              const hasOutput = Boolean(item.has_output);
              const hasReviewDraft = Boolean(item.has_review_draft);
              const analyzeError =
                item.status === 'failed' || item.status === 'cancelled'
                  ? item.error_message || t('batchWizard.actionFailed')
                  : undefined;
              const entityCount =
                typeof item.entity_count === 'number' ? item.entity_count : row.entity_count;
              const fileType = resolveBatchFileType(item.file_type ?? row.file_type);
              const isImageMode = isBatchImageMode(fileType);
              const recognitionStage = item.progress_stage ?? null;
              const recognitionCurrent =
                typeof item.progress_current === 'number' ? item.progress_current : undefined;
              const recognitionTotal =
                typeof item.progress_total === 'number' ? item.progress_total : undefined;
              const recognitionMessage = item.progress_message ?? null;
              if (
                row.analyzeStatus === analyzeStatus &&
                row.reviewConfirmed === reviewConfirmed &&
                row.has_output === hasOutput &&
                row.hasReviewDraft === hasReviewDraft &&
                row.file_type === fileType &&
                row.isImageMode === isImageMode &&
                row.analyzeError === analyzeError &&
                row.entity_count === entityCount &&
                row.recognitionStage === recognitionStage &&
                row.recognitionCurrent === recognitionCurrent &&
                row.recognitionTotal === recognitionTotal &&
                row.recognitionMessage === recognitionMessage
              ) {
                return row;
              }
              changed = true;
              return {
                ...row,
                analyzeStatus,
                reviewConfirmed,
                has_output: hasOutput,
                hasReviewDraft,
                file_type: fileType,
                isImageMode,
                analyzeError,
                entity_count: entityCount,
                recognitionStage,
                recognitionCurrent,
                recognitionTotal,
                recognitionMessage,
              };
            });
            return changed ? next : prev;
          });
          return detail;
        } catch {
          return null;
        } finally {
          if (batchImmediateRefreshRef.current?.jobId === jobId) {
            batchImmediateRefreshRef.current = null;
          }
        }
      })();
      batchImmediateRefreshRef.current = { jobId, promise };
      return promise;
    },
    [activeJobId, isPreviewMode, itemIdByFileIdRef, setJobSkipItemReview, setRows],
  );

  useEffect(() => {
    if (step !== 3 || isPreviewMode || !activeJobId) return;
    if (!step3HasRowsNeedingRefresh) return;

    let cancelled = false;
    const refresh = () => {
      if (cancelled) return;
      void refreshRowsFromActiveJob(activeJobId);
    };

    refresh();
    const intervalMs = step3HasReviewableRows
      ? STEP3_RECOGNITION_REFRESH_MS
      : STEP3_FIRST_REVIEWABLE_REFRESH_MS;
    const intervalId = window.setInterval(refresh, intervalMs);
    return () => {
      cancelled = true;
      window.clearInterval(intervalId);
    };
  }, [
    activeJobId,
    isPreviewMode,
    refreshRowsFromActiveJob,
    step,
    step3HasReviewableRows,
    step3HasRowsNeedingRefresh,
  ]);

  useEffect(() => {
    if (step !== 4 || isPreviewMode || !activeJobId) return;
    if (!step4HasUnsettledRows) return;

    let cancelled = false;
    const refresh = () => {
      if (cancelled) return;
      void refreshRowsFromActiveJob(activeJobId);
    };

    refresh();
    const intervalId = window.setInterval(refresh, 1500);
    return () => {
      cancelled = true;
      window.clearInterval(intervalId);
    };
  }, [activeJobId, isPreviewMode, refreshRowsFromActiveJob, step, step4HasUnsettledRows]);

  // Poll while batch-confirmed items are still approving/redacting on the
  // worker pool. bulkConfirmActive covers the window where the backend's
  // background commit-all is still flipping rows out of awaiting_review.
  useEffect(() => {
    if (step !== 4 || isPreviewMode || !activeJobId) return;
    if (!step4HasSettlingRows && !bulkConfirmActive) return;

    let cancelled = false;
    const refresh = () => {
      if (cancelled) return;
      void refreshRowsFromActiveJob(activeJobId);
    };

    const intervalId = window.setInterval(refresh, 1500);
    return () => {
      cancelled = true;
      window.clearInterval(intervalId);
    };
  }, [
    activeJobId,
    bulkConfirmActive,
    isPreviewMode,
    refreshRowsFromActiveJob,
    step,
    step4HasSettlingRows,
  ]);

  return { refreshRowsFromActiveJob };
}
