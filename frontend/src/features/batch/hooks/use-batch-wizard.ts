// Copyright 2026 DataInfra-RedactionEverything Contributors

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useLocation, useParams, useBlocker, useSearchParams } from 'react-router-dom';
import { t } from '@/i18n';
import { localizeErrorMessage } from '@/utils/localizeError';

import { batchGetFileRaw, type BatchWizardMode } from '@/services/batchPipeline';
import { commitAllReviews, createJob, getJob, updateJobDraft } from '@/services/jobsApi';
import {
  buildPreviewBatchRows,
  isPreviewBatchJobId,
  PREVIEW_BATCH_JOB_ID,
} from '../lib/batch-preview-fixtures';
import { isBatchRowReadyForDelivery } from '../lib/batch-export-report';
import {
  RECOGNITION_DONE_STATUSES,
  hasReviewableRecognitionRows,
  isRecognitionSettledForReview,
  isBatchReadyForExportReview,
  type BatchRow,
  type Step,
} from '../types';
import {
  findFirstActionableReviewIndex,
  findFirstPendingReviewIndex,
  isActionableReviewRow,
  resolveReviewResumeIndex,
} from '../lib/review-navigation';

import {
  buildJobConfigForWorker,
  deriveReviewConfirmed,
  effectiveWizardFurthestStep,
  isBatchWizardMode,
  isJobConfigLockedError,
  mapBackendStatus,
  mergeJobConfigIntoWizardCfg,
  readLocalWizardMaxStep,
  toBatchJobType,
  writeLocalWizardMaxStep,
} from './use-batch-wizard-utils';
import { useBatchConfig } from './use-batch-config';
import { useBatchFiles } from './use-batch-files';
import { useBatchReview } from './use-batch-review';
import { useBatchSubmit } from './use-batch-submit';
import { isBatchImageMode, resolveBatchFileType } from '../utils/file-type';

const BATCH_URL_HYDRATE_FILE_CONCURRENCY = 4;
const STEP3_FIRST_REVIEWABLE_REFRESH_MS = 250;
const STEP3_RECOGNITION_REFRESH_MS = 1000;

type BatchJobDetail = Awaited<ReturnType<typeof getJob>>;

async function mapWithConcurrency<T, R>(
  items: T[],
  concurrency: number,
  mapper: (item: T, index: number) => Promise<R>,
): Promise<R[]> {
  if (items.length === 0) return [];
  const limit = Math.max(1, Math.min(concurrency, items.length));
  const results = new Array<R>(items.length);
  let nextIndex = 0;

  async function worker() {
    while (nextIndex < items.length) {
      const index = nextIndex;
      nextIndex += 1;
      results[index] = await mapper(items[index], index);
    }
  }

  await Promise.all(Array.from({ length: limit }, () => worker()));
  return results;
}

export function useBatchWizard() {
  const { batchMode } = useParams<{ batchMode: string }>();
  const location = useLocation();
  const [searchParams, setSearchParams] = useSearchParams();
  const modeValid = isBatchWizardMode(batchMode);
  const mode: BatchWizardMode = modeValid ? batchMode : 'smart';
  const previewRequested = searchParams.get('preview') === '1';
  const queryJobId = searchParams.get('jobId');
  const newBatchRequested = searchParams.get('new') === '1' && !queryJobId;
  const isPreviewMode = previewRequested || isPreviewBatchJobId(queryJobId);
  const sessionJobKey = `lr_batch_job_id_${mode}`;

  // ── Job identity ──
  const [activeJobId, setActiveJobId] = useState<string | null>(() => {
    try {
      if (newBatchRequested) {
        sessionStorage.removeItem(sessionJobKey);
        return null;
      }
      const stored = sessionStorage.getItem(sessionJobKey);
      return stored && !isPreviewBatchJobId(stored) ? stored : null;
    } catch {
      return null;
    }
  });
  const [jobConfigLocked, setJobConfigLocked] = useState(false);
  const [jobSkipItemReview, setJobSkipItemReview] = useState(false);
  const hydratedFromUrlRef = useRef(false);
  const batchHydrateGenRef = useRef(0);
  const urlHydrateKeyRef = useRef('');
  const newBatchConsumedRef = useRef(false);
  const prevHydrateUrlStepRef = useRef<string | null>(null);
  const internalStepNavRef = useRef(false);
  const lastSavedJobConfigJson = useRef<string>('');
  const prevFurthestForImmediateSaveRef = useRef<Step>(1);
  const batchImmediateRefreshRef = useRef<{
    jobId: string;
    promise: Promise<BatchJobDetail | null>;
  } | null>(null);

  // ── Step tracking ──
  const [step, setStep] = useState<Step>(1);
  const [furthestStep, setFurthestStep] = useState<Step>(1);
  const [stepActionLoading, setStepActionLoading] = useState(false);

  // ── Sub-hooks ──
  const files = useBatchFiles(step, mode, activeJobId, isPreviewMode);
  const {
    rows,
    setRows,
    selected,
    setSelected,
    selectedIds,
    loading,
    msg,
    setMsg,
    toggle,
    selectReadyForDelivery,
    removeRow,
    clearRows,
    getRootProps,
    getInputProps,
    isDragActive,
    uploadIssues,
    uploadProgress,
    clearUploadIssues,
    failedUploadCount,
    retryFailedUploads,
    failedRows,
    batchGroupIdRef,
    itemIdByFileIdRef,
  } = files;

  const config = useBatchConfig(mode, activeJobId, setActiveJobId, isPreviewMode, setMsg);
  const {
    cfg,
    setCfg,
    configLoaded,
    textTypes,
    pipelines,
    presets,
    textPresets,
    visionPresets,
    presetLoadError,
    presetReloading,
    retryLoadPresets,
    confirmStep1,
    setConfirmStep1,
    isStep1Complete,
    jobPriority,
    setJobPriority,
    onBatchTextPresetChange,
    onBatchVisionPresetChange,
  } = config;

  const review = useBatchReview(
    step,
    rows,
    activeJobId,
    itemIdByFileIdRef,
    cfg,
    isPreviewMode,
    textTypes,
    setMsg,
  );
  const {
    reviewIndex,
    setReviewIndex,
    reviewEntities,
    reviewBoxes,
    visibleReviewBoxes,
    visibleReviewEntities,
    reviewPageContent,
    reviewCurrentPage,
    reviewTotalPages,
    reviewAllPagesVisited,
    reviewRequiredPagesVisited,
    visitedReviewPagesCount,
    reviewPageSummaries,
    reviewHitPageCount,
    reviewUnvisitedHitPageCount,
    reviewRequiredPageCount,
    reviewUnvisitedRequiredPageCount,
    currentReviewVisionQuality,
    reviewLoading,
    reviewLoadError,
    reviewExecuteLoading,
    setReviewExecuteLoading,
    reviewDraftSaving,
    reviewDraftError,
    reviewImagePreviewLoading,
    reviewOrigImageBlobUrl,
    reviewTextUndoStack,
    reviewTextRedoStack,
    reviewImageUndoStack,
    reviewImageRedoStack,
    reviewTextContent,
    reviewTextContentRef,
    reviewTextScrollRef,
    reviewDraftDirtyRef,
    reviewLastSavedJsonRef,
    reviewFile,
    doneRows,
    reviewFileReadOnly,
    selectedReviewEntityCount,
    selectedReviewBoxCount,
    totalReviewBoxCount,
    reviewImagePreviewSrc,
    displayPreviewMap,
    textPreviewSegments,
    reviewedOutputCount,
    allReviewConfirmed,
    pendingReviewCount,
    applyReviewEntities,
    toggleReviewEntitySelected,
    setReviewBoxes,
    setVisibleReviewBoxes,
    setReviewCurrentPage,
    handleReviewBoxesCommit,
    toggleReviewBoxSelected,
    undoReviewText,
    redoReviewText,
    undoReviewImage,
    redoReviewImage,
    flushCurrentReviewDraft,
    navigateReviewIndex,
    loadReviewData,
    rerunCurrentItemRecognition,
    rerunRecognitionLoading,
  } = review;

  const submit = useBatchSubmit(
    mode,
    activeJobId,
    isPreviewMode,
    cfg,
    furthestStep,
    rows,
    setRows,
    selected,
    setMsg,
    setFurthestStep,
    failedRows,
    reviewFile,
    setReviewIndex,
    doneRows,
    reviewEntities,
    reviewBoxes,
    reviewDraftError || reviewLoadError,
    flushCurrentReviewDraft,
    reviewLastSavedJsonRef,
    reviewDraftDirtyRef,
    setReviewExecuteLoading,
    itemIdByFileIdRef,
    lastSavedJobConfigJson,
    setJobConfigLocked,
  );
  const { submitQueueToWorker, requeueFailedItems, confirmCurrentReview, downloadZip, zipLoading } =
    submit;
  const canAdvanceToExport = useMemo(() => isBatchReadyForExportReview(rows), [rows]);
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
  // 批量确认在后端后台执行（万级 job），置位后保持轮询直到全部确认落定。
  const [bulkConfirmActive, setBulkConfirmActive] = useState(false);
  const refreshRowsFromActiveJob = useCallback(
    async (jobId = activeJobId): Promise<BatchJobDetail | null> => {
      if (isPreviewMode || !jobId) return null;
      const pendingRefresh = batchImmediateRefreshRef.current;
      if (pendingRefresh?.jobId === jobId) return pendingRefresh.promise;

      const promise = (async () => {
        try {
          const detail = await getJob(jobId);
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
    [activeJobId, isPreviewMode, itemIdByFileIdRef, setRows],
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

  useEffect(() => {
    if (step !== 4) return;
    const firstActionable = findFirstActionableReviewIndex(doneRows);
    if (firstActionable < 0) return;
    const current = doneRows[reviewIndex];
    if (!current || !isActionableReviewRow(current)) {
      setReviewIndex(firstActionable);
    }
  }, [doneRows, reviewIndex, setReviewIndex, step]);
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
    if (!isPreviewMode && activeJobId && isPreviewBatchJobId(activeJobId)) {
      setActiveJobId(null);
    }
  }, [activeJobId, isPreviewMode]);

  useEffect(() => {
    if (!newBatchRequested) newBatchConsumedRef.current = false;
  }, [newBatchRequested]);

  // Clear the "not all confirmed" warning once every exportable row is confirmed.
  // advanceToExportStep sets this msg after a failed pre-flight; leaving it on
  // screen after the user goes back and finishes confirming looks like the app
  // is still blocking them.
  useEffect(() => {
    if (canAdvanceToExport && msg?.text === t('batchWizard.notAllFilesConfirmed')) {
      setMsg(null);
    }
  }, [canAdvanceToExport, msg, setMsg]);

  const canSaveJobConfigDraft = useMemo(() => {
    if (queryJobId && activeJobId === queryJobId && !hydratedFromUrlRef.current) return false;
    return rows.every((row) => row.analyzeStatus === 'pending');
  }, [activeJobId, queryJobId, rows]);

  useEffect(() => {
    const jid = searchParams.get('jobId');
    if (!jid) return;
    setActiveJobId((prev) => (prev === jid ? prev : jid));
  }, [searchParams]);

  useEffect(() => {
    lastSavedJobConfigJson.current = '';
  }, [activeJobId]);
  useEffect(() => {
    prevFurthestForImmediateSaveRef.current = 1;
  }, [activeJobId]);

  // ── Config auto-save to job draft ──
  useEffect(() => {
    if (isPreviewMode) return;
    if (!configLoaded || !activeJobId) return;
    if (!canSaveJobConfigDraft) return;
    const payload = buildJobConfigForWorker(cfg, mode, furthestStep);
    const j = JSON.stringify(payload);
    const timer = window.setTimeout(() => {
      if (j === lastSavedJobConfigJson.current) return;
      void (async () => {
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
      })();
    }, 900);
    return () => window.clearTimeout(timer);
  }, [
    cfg,
    mode,
    activeJobId,
    canSaveJobConfigDraft,
    configLoaded,
    furthestStep,
    isPreviewMode,
    rows,
    setMsg,
  ]);

  useEffect(() => {
    if (isPreviewMode) return;
    if (!configLoaded || !activeJobId) return;
    if (!canSaveJobConfigDraft) return;
    const prev = prevFurthestForImmediateSaveRef.current;
    if (furthestStep < 2) {
      prevFurthestForImmediateSaveRef.current = furthestStep;
      return;
    }
    if (furthestStep <= prev) {
      prevFurthestForImmediateSaveRef.current = furthestStep;
      return;
    }
    prevFurthestForImmediateSaveRef.current = furthestStep;
    const payload = buildJobConfigForWorker(cfg, mode, furthestStep);
    const j = JSON.stringify(payload);
    if (j === lastSavedJobConfigJson.current) return;
    void (async () => {
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
    })();
  }, [
    furthestStep,
    cfg,
    mode,
    activeJobId,
    canSaveJobConfigDraft,
    configLoaded,
    isPreviewMode,
    rows,
    setMsg,
  ]);

  useEffect(() => {
    if (isPreviewMode) return;
    const urlJobId = searchParams.get('jobId');
    if (!activeJobId || furthestStep < 2) return;
    if (activeJobId !== urlJobId) return;
    writeLocalWizardMaxStep(activeJobId, furthestStep);
  }, [activeJobId, furthestStep, searchParams, isPreviewMode]);

  // ── Blocker for step 4 ──
  const navigationBlocker = useBlocker(
    ({ currentLocation, nextLocation }) =>
      step === 4 &&
      (currentLocation.pathname !== nextLocation.pathname ||
        currentLocation.search !== nextLocation.search ||
        currentLocation.hash !== nextLocation.hash),
  );

  // ── URL hydration (deep-link restore) ──
  useEffect(() => {
    const jobId = searchParams.get('jobId');
    const itemId = searchParams.get('itemId');
    const stepRaw = searchParams.get('step');
    const isNew = searchParams.get('new') === '1' && !jobId;
    if (isNew) {
      if (newBatchConsumedRef.current) return;
      newBatchConsumedRef.current = true;
      batchHydrateGenRef.current += 1;
      hydratedFromUrlRef.current = true;
      urlHydrateKeyRef.current = '';
      itemIdByFileIdRef.current = {};
      batchGroupIdRef.current = null;
      setActiveJobId(null);
      setJobConfigLocked(false);
      setJobSkipItemReview(false);
      setRows([]);
      setSelected(new Set());
      setReviewIndex(0);
      setStep(1);
      setFurthestStep(1);
      setConfirmStep1(false);
      lastSavedJobConfigJson.current = '';
      try {
        sessionStorage.removeItem(sessionJobKey);
      } catch {
        /* ignore */
      }
      return;
    }
    const jobItemKey = `${jobId ?? ''}|${itemId ?? ''}`;
    if (urlHydrateKeyRef.current !== jobItemKey) {
      urlHydrateKeyRef.current = jobItemKey;
      hydratedFromUrlRef.current = false;
      prevHydrateUrlStepRef.current = null;
    }
    const stepKey = stepRaw ?? '';
    if (prevHydrateUrlStepRef.current !== null && prevHydrateUrlStepRef.current !== stepKey) {
      if (internalStepNavRef.current) internalStepNavRef.current = false;
      else hydratedFromUrlRef.current = false;
    }
    prevHydrateUrlStepRef.current = stepKey;

    const snUrl = stepRaw ? Number.parseInt(stepRaw, 10) : NaN;
    const urlStepParsed = Number.isFinite(snUrl) ? (Math.min(5, Math.max(1, snUrl)) as Step) : null;
    if (hydratedFromUrlRef.current && urlStepParsed !== null && step < urlStepParsed) {
      hydratedFromUrlRef.current = false;
    }

    if (isPreviewMode) {
      const previewStep = urlStepParsed ?? 1;
      const previewRows = buildPreviewBatchRows(previewStep);
      setActiveJobId(PREVIEW_BATCH_JOB_ID);
      setJobConfigLocked(false);
      setJobSkipItemReview(false);
      itemIdByFileIdRef.current = Object.fromEntries(
        previewRows.map((row, index) => [row.file_id, `preview-item-${index + 1}`]),
      );
      setRows(previewRows);
      setSelected(new Set(previewRows.map((row) => row.file_id)));
      setReviewIndex(0);
      batchGroupIdRef.current = PREVIEW_BATCH_JOB_ID;
      setConfirmStep1(true);
      setStep(previewStep);
      setFurthestStep(5);
      hydratedFromUrlRef.current = true;
      return;
    }

    if (!configLoaded || !jobId || hydratedFromUrlRef.current) return;
    const hydrateGen = ++batchHydrateGenRef.current;

    (async () => {
      try {
        const detail = await getJob(jobId);
        if (hydrateGen !== batchHydrateGenRef.current) return;
        const validTypes: string[] = ['smart_batch', 'text_batch', 'image_batch'];
        if (!validTypes.includes(detail.job_type)) {
          setMsg({ text: t('batchWizard.jobTypeMismatch'), tone: 'warn' });
          return;
        }
        setActiveJobId(jobId);
        setJobConfigLocked(detail.status !== 'draft');
        const jc = detail.config as Record<string, unknown>;
        const mergedCfg = mergeJobConfigIntoWizardCfg(cfg, jc);

        const jobTypeNav = (
          ['smart_batch', 'text_batch', 'image_batch'].includes(detail.job_type)
            ? detail.job_type
            : 'smart_batch'
        ) as 'smart_batch' | 'text_batch' | 'image_batch';
        const restoredFurthest: Step | null = effectiveWizardFurthestStep({
          jobConfig: jc,
          navHints: detail.nav_hints,
          jobType: jobTypeNav,
        });

        const persistDraftFingerprint = (furthest: Step) => {
          lastSavedJobConfigJson.current = JSON.stringify(
            buildJobConfigForWorker(mergedCfg, mode, furthest),
          );
        };

        if (detail.items.length === 0) {
          const sn = stepRaw ? Number.parseInt(stepRaw, 10) : NaN;
          const urlStep = Number.isFinite(sn) ? (Math.min(5, Math.max(1, sn)) as Step) : null;
          const sessionMax = readLocalWizardMaxStep(jobId);
          const baseEmpty =
            urlStep !== null && urlStep >= 2
              ? Math.max(restoredFurthest ?? 1, urlStep)
              : Math.max(restoredFurthest ?? 1, sessionMax ?? 1);
          const rawNext = Math.max(urlStep ?? 1, baseEmpty) as Step;
          const nextStep: Step = rawNext > 3 ? 3 : rawNext;
          itemIdByFileIdRef.current = {};
          setRows([]);
          setSelected(new Set());
          setReviewIndex(0);
          batchGroupIdRef.current = jobId;
          if (nextStep >= 2) setConfirmStep1(true);
          setStep(nextStep);
          const mergedFurthest = Math.max(restoredFurthest ?? 1, nextStep, sessionMax ?? 1) as Step;
          setCfg(mergedCfg);
          setFurthestStep((prev) => Math.max(prev, mergedFurthest) as Step);
          persistDraftFingerprint(mergedFurthest);
          hydratedFromUrlRef.current = true;
          if (detail.status === 'draft') {
            const payload = buildJobConfigForWorker(mergedCfg, mode, mergedFurthest);
            try {
              await updateJobDraft(jobId, { config: payload });
              lastSavedJobConfigJson.current = JSON.stringify(payload);
            } catch {
              /* */
            }
          }
          if (hydrateGen !== batchHydrateGenRef.current) return;
          return;
        }

        const badItemIdInUrl = Boolean(itemId && !detail.items.some((i) => i.id === itemId));
        const item =
          itemId && !badItemIdInUrl ? detail.items.find((i) => i.id === itemId) : detail.items[0];
        if (!item) {
          setMsg({ text: t('batchWizard.itemNotFound'), tone: 'warn' });
          return;
        }

        const sn0 = stepRaw ? Number.parseInt(stepRaw, 10) : NaN;
        const urlStepNum0 = Number.isFinite(sn0) ? (Math.min(5, Math.max(1, sn0)) as Step) : null;
        const sessionMaxItems0 = readLocalWizardMaxStep(jobId);
        const basePersist0 =
          urlStepNum0 !== null && urlStepNum0 >= 2
            ? Math.max(restoredFurthest ?? 1, urlStepNum0)
            : Math.max(restoredFurthest ?? 1, sessionMaxItems0 ?? 1);
        let resolvedNextStep: Step;
        if (urlStepNum0 !== null) resolvedNextStep = Math.max(urlStepNum0, basePersist0) as Step;
        else if (detail.status === 'draft')
          resolvedNextStep = Math.min(5, Math.max(2, basePersist0)) as Step;
        else if (detail.status === 'awaiting_review') resolvedNextStep = 4;
        else resolvedNextStep = Math.min(5, Math.max(3, basePersist0)) as Step;

        if (resolvedNextStep >= 2 && resolvedNextStep <= 3) {
          setConfirmStep1(true);
          setStep(resolvedNextStep);
          setFurthestStep(
            (prev) => Math.max(prev, restoredFurthest ?? 1, resolvedNextStep) as Step,
          );
          persistDraftFingerprint(Math.max(restoredFurthest ?? 1, resolvedNextStep) as Step);
        }

        const hydratedItems = await mapWithConcurrency(
          detail.items,
          BATCH_URL_HYDRATE_FILE_CONCURRENCY,
          async (entry) => {
            const info = await batchGetFileRaw(entry.file_id);
            return { item: entry, info };
          },
        );
        if (hydrateGen !== batchHydrateGenRef.current) return;

        const fileIdToItemId = Object.fromEntries(
          hydratedItems.map((entry) => [entry.item.file_id, entry.item.id]),
        );
        const rowsFromJob: BatchRow[] = hydratedItems.map((entry) => {
          const rowInfo = entry.info;
          const isScanned = Boolean(rowInfo.is_scanned);
          const rowFileType = resolveBatchFileType(
            entry.item.file_type ?? rowInfo.file_type,
            isScanned,
          );
          return {
            file_id: entry.item.file_id,
            original_filename: String(
              rowInfo.original_filename ?? entry.item.filename ?? entry.item.file_id,
            ),
            file_size: Number(rowInfo.file_size ?? 0),
            file_type: rowFileType,
            created_at: String(rowInfo.created_at ?? entry.item.created_at ?? ''),
            has_output: Boolean(rowInfo.output_path ?? entry.item.has_output),
            reviewConfirmed: deriveReviewConfirmed(entry.item),
            hasReviewDraft: Boolean(entry.item.has_review_draft),
            entity_count:
              typeof entry.item.entity_count === 'number'
                ? entry.item.entity_count
                : Array.isArray(rowInfo.entities)
                  ? rowInfo.entities.length
                  : 0,
            analyzeStatus: mapBackendStatus(entry.item.status),
            analyzeError:
              entry.item.status === 'failed' || entry.item.status === 'cancelled'
                ? entry.item.error_message || t('batchWizard.actionFailed')
                : undefined,
            isImageMode: isBatchImageMode(rowFileType),
          };
        });

        const reviewableRows = rowsFromJob.filter((row) =>
          RECOGNITION_DONE_STATUSES.has(row.analyzeStatus),
        );
        const recognitionSettledForReview = isRecognitionSettledForReview(rowsFromJob);
        const readyForExportReview = isBatchReadyForExportReview(rowsFromJob);
        let resolvedStepWithGates = resolvedNextStep;
        if (resolvedStepWithGates >= 4 && !recognitionSettledForReview) {
          resolvedStepWithGates = 3 as Step;
        }
        if (resolvedStepWithGates === 5 && !readyForExportReview) resolvedStepWithGates = 4 as Step;

        itemIdByFileIdRef.current = fileIdToItemId;
        setCfg(mergedCfg);
        setJobSkipItemReview(Boolean(detail.skip_item_review));
        setRows(rowsFromJob);
        setSelected(new Set(rowsFromJob.map((row) => row.file_id)));
        setReviewIndex(resolveReviewResumeIndex(reviewableRows, item.file_id));
        batchGroupIdRef.current = jobId;
        if (resolvedStepWithGates >= 2) setConfirmStep1(true);
        setStep(resolvedStepWithGates);
        setFurthestStep(
          (prev) => Math.max(prev, restoredFurthest ?? 1, resolvedStepWithGates) as Step,
        );
        persistDraftFingerprint(Math.max(restoredFurthest ?? 1, resolvedStepWithGates) as Step);
        hydratedFromUrlRef.current = true;
      } catch (e) {
        if (hydrateGen === batchHydrateGenRef.current) {
          setMsg({ text: localizeErrorMessage(e, 'batchWizard.loadJobFailed'), tone: 'err' });
        }
      }
    })();
    return () => {
      batchHydrateGenRef.current += 1;
    };
  }, [
    configLoaded,
    location.search,
    mode,
    isPreviewMode,
    searchParams,
    batchGroupIdRef,
    itemIdByFileIdRef,
    setCfg,
    setConfirmStep1,
    setMsg,
    setReviewIndex,
    setRows,
    setSelected,
    cfg,
    sessionJobKey,
    step,
  ]);

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
  }, [step, activeJobId, searchParams, setSearchParams]);

  // ── Derived ──
  const canReviewRecognizedRows = useMemo(() => isRecognitionSettledForReview(rows), [rows]);

  useEffect(() => {
    if (step !== 3 || !canReviewRecognizedRows) return;
    setFurthestStep((prev) => Math.max(prev, 4) as Step);
  }, [canReviewRecognizedRows, step]);

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
  }, [activeJobId, cfg, furthestStep, isPreviewMode, mode, rows, setMsg]);

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
      isPreviewMode,
      isStep1Complete,
      loading,
      rows,
      step,
      setMsg,
      setReviewIndex,
      setSelected,
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
    [applyStep, flushCurrentReviewDraft, step],
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
    [doneRows, rows, selected, setReviewIndex],
  );

  const advanceToUploadStep = useCallback(async () => {
    if (stepActionLoading) return;
    if (!isStep1Complete) {
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
    setStepActionLoading(true);
    try {
      if (isPreviewMode) {
        setActiveJobId(PREVIEW_BATCH_JOB_ID);
        setJobConfigLocked(false);
        setRows(buildPreviewBatchRows(2));
        setSelected(new Set(buildPreviewBatchRows(2).map((row) => row.file_id)));
        itemIdByFileIdRef.current = Object.fromEntries(
          buildPreviewBatchRows(2).map((row, index) => [row.file_id, `preview-item-${index + 1}`]),
        );
        internalStepNavRef.current = true;
        setStep(2);
        setFurthestStep(5);
        setMsg(null);
        return;
      }
      const nextFurthest = Math.max(furthestStep, 2) as Step;
      const payload = buildJobConfigForWorker(cfg, mode, nextFurthest);
      let jid = activeJobId;
      if (jid) {
        try {
          writeLocalWizardMaxStep(jid, nextFurthest);
          await updateJobDraft(jid, { config: payload });
          setJobConfigLocked(false);
        } catch (e) {
          if (isJobConfigLockedError(e)) {
            setJobConfigLocked(true);
            setMsg({ text: t('batchWizard.configLocked'), tone: 'warn' });
            return;
          }
          jid = null;
          setActiveJobId(null);
        }
      }
      if (!jid) {
        const j = await createJob({
          job_type: toBatchJobType(mode),
          title: `${t('batchHub.batch')} ${new Date().toLocaleString()}`,
          config: payload,
          priority: jobPriority,
        });
        jid = j.id;
        writeLocalWizardMaxStep(jid, nextFurthest);
        setActiveJobId(jid);
        setJobConfigLocked(false);
      }
      lastSavedJobConfigJson.current = JSON.stringify(payload);
      const sp = new URLSearchParams(searchParams);
      sp.delete('new');
      sp.set('jobId', jid);
      sp.set('step', '2');
      setSearchParams(sp, { replace: true });
      internalStepNavRef.current = true;
      setStep(2);
      setFurthestStep((prev) => Math.max(prev, 2) as Step);
      setMsg(null);
    } catch (e) {
      setMsg({ text: localizeErrorMessage(e, 'batchWizard.actionFailed'), tone: 'err' });
    } finally {
      setStepActionLoading(false);
    }
  }, [
    activeJobId,
    cfg,
    configLoaded,
    confirmStep1,
    furthestStep,
    isPreviewMode,
    isStep1Complete,
    jobPriority,
    mode,
    itemIdByFileIdRef,
    setMsg,
    setRows,
    setSelected,
    searchParams,
    setSearchParams,
    stepActionLoading,
  ]);

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
    isPreviewMode,
    doneRows,
    rows,
    setMsg,
    setRows,
    setReviewIndex,
    setSelected,
    refreshRowsFromActiveJob,
    stepActionLoading,
  ]);

  const [bulkConfirmLoading, setBulkConfirmLoading] = useState(false);
  useEffect(() => {
    if (bulkConfirmActive && pendingReviewCount === 0) setBulkConfirmActive(false);
  }, [bulkConfirmActive, pendingReviewCount]);
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
    setFurthestStep,
    setMsg,
    setRows,
  ]);

  // ── Blocker effects ──
  const [leaveConfirmOpen, _setLeaveConfirmOpen] = useState(false);
  const showLeaveConfirmModal = leaveConfirmOpen || navigationBlocker.state === 'blocked';

  useEffect(() => {
    if (navigationBlocker.state !== 'blocked') return;
    void (async () => {
      const ok = await flushCurrentReviewDraft();
      if (ok && navigationBlocker.state === 'blocked') navigationBlocker.proceed();
    })();
  }, [flushCurrentReviewDraft, navigationBlocker]);

  useEffect(() => {
    const onBeforeUnload = (e: BeforeUnloadEvent) => {
      if (step !== 4 || !reviewDraftDirtyRef.current) return;
      e.preventDefault();
      e.returnValue = '';
    };
    window.addEventListener('beforeunload', onBeforeUnload);
    return () => window.removeEventListener('beforeunload', onBeforeUnload);
  }, [step, reviewDraftDirtyRef]);

  useEffect(() => {
    if (step !== 4) return;
    const onPageHide = () => {
      void flushCurrentReviewDraft();
    };
    window.addEventListener('pagehide', onPageHide);
    return () => window.removeEventListener('pagehide', onPageHide);
  }, [flushCurrentReviewDraft, step]);

  return {
    // Identity
    modeValid,
    mode,
    activeJobId,
    jobConfigLocked,
    previewMode: isPreviewMode,
    interactionLocked: false,

    // Step
    step,
    furthestStep,
    canGoStep,
    goStep,
    resolveExportIssue,
    advanceToUploadStep,
    advanceToExportStep,
    bulkConfirmAll,
    bulkConfirmLoading,

    // Config
    cfg,
    setCfg,
    configLoaded,
    textTypes,
    pipelines,
    presets,
    textPresets,
    visionPresets,
    presetLoadError,
    presetReloading,
    retryLoadPresets,
    confirmStep1,
    setConfirmStep1,
    isStep1Complete,
    jobPriority,
    setJobPriority,
    onBatchTextPresetChange,
    onBatchVisionPresetChange,

    // Files
    rows,
    selected,
    selectedIds,
    loading,
    msg,
    setMsg,
    toggle,
    selectReadyForDelivery,
    removeRow,
    clearRows,

    // Upload
    getRootProps,
    getInputProps,
    isDragActive,
    uploadIssues,
    uploadProgress,
    clearUploadIssues,
    failedUploadCount,
    retryFailedUploads,

    // Recognition
    submitQueueToWorker,
    requeueFailedItems,
    failedRows,
    doneRows,

    // Review
    reviewIndex,
    reviewFile,
    reviewLoading,
    reviewLoadError,
    reviewExecuteLoading,
    reviewEntities,
    reviewBoxes,
    visibleReviewBoxes,
    visibleReviewEntities,
    reviewPageContent,
    reviewCurrentPage,
    reviewTotalPages,
    reviewAllPagesVisited,
    reviewRequiredPagesVisited,
    visitedReviewPagesCount,
    reviewPageSummaries,
    reviewHitPageCount,
    reviewUnvisitedHitPageCount,
    reviewRequiredPageCount,
    reviewUnvisitedRequiredPageCount,
    currentReviewVisionQuality,
    reviewTextContent,
    reviewDraftSaving,
    reviewDraftError,
    reviewFileReadOnly,
    rerunCurrentItemRecognition,
    rerunRecognitionLoading,
    reviewedOutputCount,
    pendingReviewCount,
    allReviewConfirmed,
    canAdvanceToExport,
    reviewImagePreviewSrc,
    reviewImagePreviewLoading,
    reviewOrigImageBlobUrl,
    reviewTextUndoStack,
    reviewTextRedoStack,
    reviewImageUndoStack,
    reviewImageRedoStack,
    selectedReviewEntityCount,
    selectedReviewBoxCount,
    totalReviewBoxCount,
    displayPreviewMap,
    textPreviewSegments,
    reviewTextContentRef,
    reviewTextScrollRef,
    navigateReviewIndex,
    loadReviewData,
    confirmCurrentReview,
    applyReviewEntities,
    toggleReviewEntitySelected,
    toggleReviewBoxSelected,
    handleReviewBoxesCommit,
    undoReviewText,
    redoReviewText,
    undoReviewImage,
    redoReviewImage,
    setReviewBoxes,
    setVisibleReviewBoxes,
    setReviewCurrentPage,

    // Export
    zipLoading,
    downloadZip,

    // Blocker
    showLeaveConfirmModal,
    navigationBlocker,
  };
}
