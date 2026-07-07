// Copyright 2026 DataInfra-RedactionEverything Contributors

import { useCallback, useEffect, useMemo } from 'react';
import type { SetURLSearchParams } from 'react-router-dom';
import { t } from '@/i18n';
import type { BatchWizardMode, BatchWizardPersistedConfig } from '@/services/batchPipeline';
import { updateJobDraft } from '@/services/jobsApi';
import { isPreviewBatchJobId } from '../lib/batch-preview-fixtures';
import { isBatchRowReadyForDelivery } from '../lib/batch-export-report';
import {
  RECOGNITION_DONE_STATUSES,
  isRecognitionSettledForReview,
  type BatchRow,
  type Step,
} from '../types';
import {
  findFirstActionableReviewIndex,
  findFirstPendingReviewIndex,
} from '../lib/review-navigation';
import {
  buildJobConfigForWorker,
  isJobConfigLockedError,
  writeLocalWizardMaxStep,
} from './use-batch-wizard-utils';
import type { BatchJobDetail } from './use-batch-polling';

export interface BatchNavigationState {
  canGoStep: (target: Step) => boolean;
  goStep: (s: Step) => void;
  resolveExportIssue: (fileId?: string) => void;
}

export function useBatchNavigation(
  mode: BatchWizardMode,
  activeJobId: string | null,
  isPreviewMode: boolean,
  newBatchRequested: boolean,
  sessionJobKey: string,
  cfg: BatchWizardPersistedConfig,
  configLoaded: boolean,
  confirmStep1: boolean,
  isStep1Complete: boolean,
  jobSkipItemReview: boolean,
  canAdvanceToExport: boolean,
  rows: BatchRow[],
  loading: boolean,
  doneRows: BatchRow[],
  selected: Set<string>,
  step: Step,
  setStep: React.Dispatch<React.SetStateAction<Step>>,
  furthestStep: Step,
  setFurthestStep: React.Dispatch<React.SetStateAction<Step>>,
  setStepActionLoading: React.Dispatch<React.SetStateAction<boolean>>,
  setMsg: (msg: { text: string; tone: 'neutral' | 'ok' | 'warn' | 'err' } | null) => void,
  setSelected: React.Dispatch<React.SetStateAction<Set<string>>>,
  setReviewIndex: React.Dispatch<React.SetStateAction<number>>,
  setJobConfigLocked: React.Dispatch<React.SetStateAction<boolean>>,
  flushCurrentReviewDraft: () => Promise<boolean>,
  refreshRowsFromActiveJob: (jobId?: string | null) => Promise<BatchJobDetail | null>,
  searchParams: URLSearchParams,
  setSearchParams: SetURLSearchParams,
  lastSavedJobConfigJson: React.MutableRefObject<string>,
  internalStepNavRef: React.MutableRefObject<boolean>,
  hydratedFromUrlRef: React.MutableRefObject<boolean>,
): BatchNavigationState {
  // ── Session persistence ──
  useEffect(() => {
    try {
      if (newBatchRequested && !activeJobId) {
        sessionStorage.removeItem(sessionJobKey);
      } else if (activeJobId && !isPreviewMode && !isPreviewBatchJobId(activeJobId)) {
        sessionStorage.setItem(sessionJobKey, activeJobId);
      } else {
        sessionStorage.removeItem(sessionJobKey);
      }
    } catch {
      /* ignore */
    }
  }, [activeJobId, isPreviewMode, newBatchRequested, sessionJobKey]);

  useEffect(() => {
    if (isPreviewMode) return;
    const urlJobId = searchParams.get('jobId');
    if (!activeJobId || furthestStep < 2) return;
    if (activeJobId !== urlJobId) return;
    writeLocalWizardMaxStep(activeJobId, furthestStep);
  }, [activeJobId, furthestStep, searchParams, isPreviewMode]);

  // ── Sync step to URL ──
  useEffect(() => {
    const jid = searchParams.get('jobId');
    if (!jid || !activeJobId || jid !== activeJobId) return;
    if (!hydratedFromUrlRef.current) return;
    const cur = searchParams.get('step');
    if (cur === String(step)) return;
    const sp = new URLSearchParams(searchParams);
    sp.set('step', String(step));
    setSearchParams(sp, { replace: true });
  }, [step, activeJobId, hydratedFromUrlRef, searchParams, setSearchParams]);

  // ── Derived ──
  const canReviewRecognizedRows = useMemo(() => isRecognitionSettledForReview(rows), [rows]);

  useEffect(() => {
    if (step !== 3 || !canReviewRecognizedRows) return;
    setFurthestStep((prev) => Math.max(prev, 4) as Step);
  }, [canReviewRecognizedRows, setFurthestStep, step]);

  // ── Step navigation ──
  const canUnlockStep = useCallback(
    (target: Step): boolean => {
      if (target === 1) return true;
      if (target === 2) return isStep1Complete;
      if (target === 3) return rows.length > 0 && !loading;
      if (target === 4) return canReviewRecognizedRows;
      if (
        rows.some((row) => row.analyzeStatus === 'awaiting_review' && row.reviewConfirmed !== true)
      ) {
        return false;
      }
      if (jobSkipItemReview) return rows.length > 0 && rows.every((row) => row.has_output);
      return canAdvanceToExport;
    },
    [
      canAdvanceToExport,
      canReviewRecognizedRows,
      isStep1Complete,
      jobSkipItemReview,
      loading,
      rows,
    ],
  );

  const canGoStep = useCallback(
    (target: Step): boolean => {
      if (target === step) return true;
      if (isPreviewMode) return true;
      return target <= furthestStep && canUnlockStep(target);
    },
    [canUnlockStep, furthestStep, isPreviewMode, step],
  );

  const flushJobDraftFromStep1 = useCallback(async () => {
    if (isPreviewMode || !activeJobId) return;
    if (!activeJobId) return;
    const payload = buildJobConfigForWorker(cfg, mode, furthestStep);
    const j = JSON.stringify(payload);
    if (j === lastSavedJobConfigJson.current) return;
    try {
      await updateJobDraft(activeJobId, { config: payload });
      lastSavedJobConfigJson.current = j;
      setJobConfigLocked(false);
    } catch (e) {
      if (isJobConfigLockedError(e)) {
        if (rows.some((row) => row.analyzeStatus !== 'pending')) {
          setJobConfigLocked(true);
          setMsg({ text: t('batchWizard.configLocked'), tone: 'warn' });
        }
      }
    }
  }, [
    activeJobId,
    cfg,
    furthestStep,
    isPreviewMode,
    lastSavedJobConfigJson,
    mode,
    rows,
    setJobConfigLocked,
    setMsg,
  ]);

  const applyStep = useCallback(
    (s: Step) => {
      if (s === step) return;
      const canAdvanceToNextStep = s === ((step + 1) as Step) && canUnlockStep(s);
      if (s >= 2 && !isStep1Complete) {
        setMsg({
          text: !configLoaded
            ? t('batchWizard.waitConfig')
            : !confirmStep1
              ? t('batchWizard.confirmConfigFirst')
              : t('batchWizard.selectTypesFirst'),
          tone: 'warn',
        });
        return;
      }
      if (!canGoStep(s) && !canAdvanceToNextStep) {
        setMsg({
          text:
            s === 3 && loading
              ? t('batchWizard.step2.waitUploadBeforeRecognize')
              : t('batchWizard.stepsOrder'),
          tone: 'warn',
        });
        return;
      }
      if (step === 1 && s >= 2 && activeJobId) void flushJobDraftFromStep1();
      internalStepNavRef.current = true;
      if (s === 5) {
        const redactedIds = rows.filter((row) => row.has_output).map((row) => row.file_id);
        if (redactedIds.length) setSelected(new Set(redactedIds));
      }
      setStep(s);
      setFurthestStep((prev) => Math.max(prev, s) as Step);
      setMsg(null);
      if (s === 4) {
        const firstActionable = findFirstActionableReviewIndex(doneRows);
        const firstPending = findFirstPendingReviewIndex(doneRows);
        setReviewIndex(
          firstActionable >= 0 ? firstActionable : firstPending >= 0 ? firstPending : 0,
        );
      }
      if (s === 5 && activeJobId && !isPreviewMode) {
        void refreshRowsFromActiveJob(activeJobId);
      }
    },
    [
      activeJobId,
      canUnlockStep,
      canGoStep,
      configLoaded,
      confirmStep1,
      doneRows,
      flushJobDraftFromStep1,
      internalStepNavRef,
      isPreviewMode,
      isStep1Complete,
      loading,
      rows,
      step,
      setMsg,
      setReviewIndex,
      setSelected,
      setStep,
      setFurthestStep,
      refreshRowsFromActiveJob,
    ],
  );

  const goStep = useCallback(
    (s: Step) => {
      if (step === 4 && s !== 5) {
        void (async () => {
          setStepActionLoading(true);
          try {
            const ok = await flushCurrentReviewDraft();
            if (ok) applyStep(s);
          } finally {
            setStepActionLoading(false);
          }
        })();
        return;
      }
      applyStep(s);
    },
    [applyStep, flushCurrentReviewDraft, setStepActionLoading, step],
  );

  const resolveExportIssue = useCallback(
    (fileId?: string) => {
      const target = fileId
        ? rows.find((row) => row.file_id === fileId)
        : (rows.find((row) => selected.has(row.file_id) && !isBatchRowReadyForDelivery(row)) ??
          rows.find(
            (row) =>
              RECOGNITION_DONE_STATUSES.has(row.analyzeStatus) && row.reviewConfirmed !== true,
          ));
      if (!target) {
        const firstActionable = findFirstActionableReviewIndex(doneRows);
        const firstPending = findFirstPendingReviewIndex(doneRows);
        if (firstActionable >= 0) setReviewIndex(firstActionable);
        else if (firstPending >= 0) setReviewIndex(firstPending);
        internalStepNavRef.current = true;
        setStep(4);
        return;
      }
      if (
        target.analyzeStatus === 'failed' ||
        !RECOGNITION_DONE_STATUSES.has(target.analyzeStatus)
      ) {
        internalStepNavRef.current = true;
        setStep(3);
        return;
      }
      const reviewTargetIndex = doneRows.findIndex((row) => row.file_id === target.file_id);
      if (reviewTargetIndex >= 0) {
        setReviewIndex(reviewTargetIndex);
      }
      internalStepNavRef.current = true;
      setStep(4);
    },
    [doneRows, internalStepNavRef, rows, selected, setReviewIndex, setStep],
  );

  return {
    canGoStep,
    goStep,
    resolveExportIssue,
  };
}
