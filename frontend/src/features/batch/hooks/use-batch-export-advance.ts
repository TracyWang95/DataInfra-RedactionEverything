// Copyright 2026 DataInfra-RedactionEverything Contributors

import { useCallback, useEffect, useState } from 'react';
import { t } from '@/i18n';
import { localizeErrorMessage } from '@/utils/localizeError';
import { commitAllReviews } from '@/services/jobsApi';
import { ensureNotifyPermission, notifyDone } from '@/lib/notifications';
import {
  RECOGNITION_DONE_STATUSES,
  isBatchReadyForExportReview,
  type BatchRow,
  type Step,
} from '../types';
import {
  findFirstActionableReviewIndex,
  findFirstPendingReviewIndex,
} from '../lib/review-navigation';
import { deriveReviewConfirmed, mapBackendStatus } from './use-batch-wizard-utils';
import type { BatchJobDetail } from './use-batch-polling';

export interface BatchExportAdvanceState {
  advanceToExportStep: () => Promise<void>;
  bulkConfirmAll: () => Promise<void>;
  bulkConfirmLoading: boolean;
}

export function useBatchExportAdvance(
  activeJobId: string | null,
  isPreviewMode: boolean,
  canAdvanceToExport: boolean,
  rows: BatchRow[],
  setRows: React.Dispatch<React.SetStateAction<BatchRow[]>>,
  doneRows: BatchRow[],
  msg: { text: string; tone: 'neutral' | 'ok' | 'warn' | 'err' } | null,
  setMsg: (msg: { text: string; tone: 'neutral' | 'ok' | 'warn' | 'err' } | null) => void,
  setSelected: React.Dispatch<React.SetStateAction<Set<string>>>,
  setReviewIndex: React.Dispatch<React.SetStateAction<number>>,
  setStep: React.Dispatch<React.SetStateAction<Step>>,
  setFurthestStep: React.Dispatch<React.SetStateAction<Step>>,
  stepActionLoading: boolean,
  setStepActionLoading: React.Dispatch<React.SetStateAction<boolean>>,
  reviewExecuteLoading: boolean,
  pendingReviewCount: number,
  bulkConfirmActive: boolean,
  setBulkConfirmActive: React.Dispatch<React.SetStateAction<boolean>>,
  flushCurrentReviewDraft: () => Promise<boolean>,
  refreshRowsFromActiveJob: (jobId?: string | null) => Promise<BatchJobDetail | null>,
  internalStepNavRef: React.MutableRefObject<boolean>,
): BatchExportAdvanceState {
  // Clear the "not all confirmed" warning once every exportable row is confirmed.
  // advanceToExportStep sets this msg after a failed pre-flight; leaving it on
  // screen after the user goes back and finishes confirming looks like the app
  // is still blocking them.
  useEffect(() => {
    if (canAdvanceToExport && msg?.text === t('batchWizard.notAllFilesConfirmed')) {
      setMsg(null);
    }
  }, [canAdvanceToExport, msg, setMsg]);

  const advanceToExportStep = useCallback(async () => {
    if (stepActionLoading) return;
    setStepActionLoading(true);
    if (!rows.length) {
      setMsg({ text: t('batchWizard.noFilesToExport'), tone: 'warn' });
      setStepActionLoading(false);
      return;
    }
    try {
      const draftSaved = await flushCurrentReviewDraft();
      if (!draftSaved) {
        setMsg({ text: t('batchWizard.reviewSaveBeforeExportFailed'), tone: 'err' });
        return;
      }
      if (isPreviewMode) {
        if (!canAdvanceToExport) {
          setMsg({ text: t('batchWizard.notAllFilesConfirmed'), tone: 'warn' });
          return;
        }
        setSelected(new Set(rows.filter((row) => row.has_output).map((row) => row.file_id)));
        internalStepNavRef.current = true;
        setStep(5);
        setFurthestStep(5);
        setMsg(null);
        return;
      }
      if (activeJobId) {
        const detail = await refreshRowsFromActiveJob(activeJobId);
        if (!detail) {
          setMsg({ text: t('batchWizard.actionFailed'), tone: 'err' });
          return;
        }
        const itemMap = new Map(detail.items.map((it) => [it.file_id, it]));
        const backendFileIds = new Set(detail.items.map((it) => it.file_id));
        const refreshedRows = rows
          .filter((r) => backendFileIds.has(r.file_id))
          .map((r) => {
            const item = itemMap.get(r.file_id);
            if (!item) return r;
            return {
              ...r,
              has_output: Boolean(item.has_output),
              analyzeStatus: mapBackendStatus(item.status),
              reviewConfirmed: deriveReviewConfirmed(item),
              hasReviewDraft: Boolean(item.has_review_draft),
            };
          });
        setRows(refreshedRows);
        if (!isBatchReadyForExportReview(refreshedRows)) {
          const freshReviewableRows = refreshedRows.filter((row) =>
            RECOGNITION_DONE_STATUSES.has(row.analyzeStatus),
          );
          const firstActionable = findFirstActionableReviewIndex(freshReviewableRows);
          const firstPending = findFirstPendingReviewIndex(freshReviewableRows);
          if (firstActionable >= 0) setReviewIndex(firstActionable);
          else if (firstPending >= 0) setReviewIndex(firstPending);
          setMsg({ text: t('batchWizard.notAllFilesConfirmed'), tone: 'warn' });
          return;
        }
        setSelected(new Set(detail.items.filter((it) => it.has_output).map((it) => it.file_id)));
        internalStepNavRef.current = true;
        setStep(5);
        setFurthestStep((prev) => Math.max(prev, 5) as Step);
        setMsg(null);
        return;
      }
      if (!canAdvanceToExport) {
        const firstActionable = findFirstActionableReviewIndex(doneRows);
        const firstPending = findFirstPendingReviewIndex(doneRows);
        if (firstActionable >= 0) setReviewIndex(firstActionable);
        else if (firstPending >= 0) setReviewIndex(firstPending);
        setMsg({ text: t('batchWizard.notAllFilesConfirmed'), tone: 'warn' });
        return;
      }
      internalStepNavRef.current = true;
      setStep(5);
      setFurthestStep((prev) => Math.max(prev, 5) as Step);
      setMsg(null);
    } finally {
      setStepActionLoading(false);
    }
  }, [
    activeJobId,
    canAdvanceToExport,
    flushCurrentReviewDraft,
    internalStepNavRef,
    isPreviewMode,
    doneRows,
    rows,
    setMsg,
    setRows,
    setReviewIndex,
    setSelected,
    setStep,
    setFurthestStep,
    setStepActionLoading,
    refreshRowsFromActiveJob,
    stepActionLoading,
  ]);

  const [bulkConfirmLoading, setBulkConfirmLoading] = useState(false);
  useEffect(() => {
    if (bulkConfirmActive && pendingReviewCount === 0) {
      setBulkConfirmActive(false);
      // 万级批量确认在后台跑数分钟，用户可能已切走页签
      notifyDone(t('notify.bulkConfirmDone'));
    }
  }, [bulkConfirmActive, pendingReviewCount, setBulkConfirmActive, t]);

  const bulkConfirmAll = useCallback(async () => {
    if (bulkConfirmLoading || reviewExecuteLoading) return;
    if (isPreviewMode) {
      setRows((prev) =>
        prev.map((row) =>
          RECOGNITION_DONE_STATUSES.has(row.analyzeStatus) && row.reviewConfirmed !== true
            ? { ...row, reviewConfirmed: true, has_output: true, analyzeStatus: 'completed' as const }
            : row,
        ),
      );
      setFurthestStep((prev) => Math.max(prev, 5) as Step);
      setMsg({ text: t('batchWizard.step4.bulkConfirmDone'), tone: 'ok' });
      return;
    }
    if (!activeJobId) return;
    ensureNotifyPermission();
    setBulkConfirmLoading(true);
    setMsg(null);
    try {
      // Persist the currently open file's edits before confirming the whole batch.
      const draftSaved = await flushCurrentReviewDraft();
      if (!draftSaved) {
        setMsg({ text: t('batchWizard.autoSaveFailed'), tone: 'err' });
        return;
      }
      const result = await commitAllReviews(activeJobId);
      setBulkConfirmActive(true);
      await refreshRowsFromActiveJob(activeJobId);
      if (result.failed.length > 0) {
        setMsg({
          text: t('batchWizard.step4.bulkConfirmPartial')
            .replace('{confirmed}', String(result.confirmed))
            .replace('{failed}', String(result.failed.length)),
          tone: 'warn',
        });
      } else {
        setMsg({
          text: t('batchWizard.step4.bulkConfirmQueued').replace(
            '{count}',
            String(result.total_awaiting || result.confirmed),
          ),
          tone: 'ok',
        });
      }
    } catch (e) {
      setMsg({ text: localizeErrorMessage(e, 'batchWizard.actionFailed'), tone: 'err' });
    } finally {
      setBulkConfirmLoading(false);
    }
  }, [
    activeJobId,
    bulkConfirmLoading,
    reviewExecuteLoading,
    flushCurrentReviewDraft,
    isPreviewMode,
    refreshRowsFromActiveJob,
    setBulkConfirmActive,
    setFurthestStep,
    setMsg,
    setRows,
  ]);

  return {
    advanceToExportStep,
    bulkConfirmAll,
    bulkConfirmLoading,
  };
}
