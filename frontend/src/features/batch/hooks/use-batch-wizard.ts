// Copyright 2026 DataInfra-RedactionEverything Contributors

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useLocation, useParams, useBlocker, useSearchParams } from 'react-router-dom';
import { t } from '@/i18n';
import { localizeErrorMessage } from '@/utils/localizeError';

import { type BatchWizardMode } from '@/services/batchPipeline';
import { createJob, getJob, updateJobDraft } from '@/services/jobsApi';
import { notifyDone, phaseJustFinished } from '@/lib/notifications';
import {
  buildPreviewBatchRows,
  isPreviewBatchJobId,
  PREVIEW_BATCH_JOB_ID,
} from '../lib/batch-preview-fixtures';
import {
  RECOGNITION_DONE_STATUSES,
  isRecognitionSettledForReview,
  isBatchReadyForExportReview,
  type BatchRow,
  type Step,
} from '../types';
import {
  findFirstActionableReviewIndex,
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
import { useBatchExportAdvance } from './use-batch-export-advance';
import { useBatchFiles } from './use-batch-files';
import { useBatchNavigation } from './use-batch-navigation';
import { useBatchPolling } from './use-batch-polling';
import { useBatchReview } from './use-batch-review';
import { useBatchSubmit } from './use-batch-submit';
import { isBatchImageMode, resolveBatchFileType } from '../utils/file-type';

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
  // 批量确认在后端后台执行（万级 job），置位后保持轮询直到全部确认落定。
  const [bulkConfirmActive, setBulkConfirmActive] = useState(false);

  // ── Polling (step-3 recognition / step-4 settling) ──
  const { refreshRowsFromActiveJob } = useBatchPolling(
    step,
    isPreviewMode,
    activeJobId,
    rows,
    setRows,
    itemIdByFileIdRef,
    setJobSkipItemReview,
    bulkConfirmActive,
  );

  useEffect(() => {
    if (step !== 4) return;
    const firstActionable = findFirstActionableReviewIndex(doneRows);
    if (firstActionable < 0) return;
    const current = doneRows[reviewIndex];
    if (!current || !isActionableReviewRow(current)) {
      setReviewIndex(firstActionable);
    }
  }, [doneRows, reviewIndex, setReviewIndex, step]);

  useEffect(() => {
    if (!isPreviewMode && activeJobId && isPreviewBatchJobId(activeJobId)) {
      setActiveJobId(null);
    }
  }, [activeJobId, isPreviewMode]);

  useEffect(() => {
    if (!newBatchRequested) newBatchConsumedRef.current = false;
  }, [newBatchRequested]);

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
        const detail = await getJob(jobId, { performance: false });
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

        // PM 万级任务「继续审阅」卡第 1 步的真根因：这里曾对每个 item 逐文件
        // batchGetFileRaw（4 并发），5188 文件经隧道要 2-4 分钟，期间 setStep(4)
        // 不执行、页面死停在第 1 步。后端 items 载荷已带 filename/file_type/
        // has_output/entity_count/created_at 全部所需字段——fan-out 是纯冗余，
        // 砍掉后万级恢复即时落步。fan-out 独有的 file_size/is_scanned 用安全
        // 缺省（审阅页打开单个文件时会拉全量元数据）。
        const hydratedItems = detail.items.map((entry) => ({
          item: entry,
          info: {} as Record<string, unknown>,
        }));

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
          // 详情拉取失败（万级任务曾因 38MB 载荷超时）不再静默卡在第 1 步：
          // 按 URL 意图落步，行数据靠轻量轮询自愈。
          if (urlStepParsed !== null && urlStepParsed >= 2) {
            setActiveJobId(jobId);
            batchGroupIdRef.current = jobId;
            setConfirmStep1(true);
            setStep(urlStepParsed);
            setFurthestStep((prev) => Math.max(prev, urlStepParsed) as Step);
            hydratedFromUrlRef.current = true;
          }
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

  // ── Step navigation (goStep/canGoStep, URL step sync, session persistence) ──
  const { canGoStep, goStep, resolveExportIssue } = useBatchNavigation(
    mode,
    activeJobId,
    isPreviewMode,
    newBatchRequested,
    sessionJobKey,
    cfg,
    configLoaded,
    confirmStep1,
    isStep1Complete,
    jobSkipItemReview,
    canAdvanceToExport,
    rows,
    loading,
    doneRows,
    selected,
    step,
    setStep,
    furthestStep,
    setFurthestStep,
    setStepActionLoading,
    setMsg,
    setSelected,
    setReviewIndex,
    setJobConfigLocked,
    flushCurrentReviewDraft,
    refreshRowsFromActiveJob,
    searchParams,
    setSearchParams,
    lastSavedJobConfigJson,
    internalStepNavRef,
    hydratedFromUrlRef,
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

  // ── Export advance + bulk confirm ──
  const { advanceToExportStep, bulkConfirmAll, bulkConfirmLoading } = useBatchExportAdvance(
    activeJobId,
    isPreviewMode,
    canAdvanceToExport,
    rows,
    setRows,
    doneRows,
    msg,
    setMsg,
    setSelected,
    setReviewIndex,
    setStep,
    setFurthestStep,
    stepActionLoading,
    setStepActionLoading,
    reviewExecuteLoading,
    pendingReviewCount,
    bulkConfirmActive,
    setBulkConfirmActive,
    flushCurrentReviewDraft,
    refreshRowsFromActiveJob,
    internalStepNavRef,
  );

  // 识别全部完成通知（W2-2）：analyzing/pending 活跃数 >0 → 0 的翻转，
  // 仅在识别步（step3）响，避免 step2 清空队列误报。
  const recognitionActiveCount = useMemo(
    () =>
      rows.filter((row) => row.analyzeStatus === 'analyzing' || row.analyzeStatus === 'pending')
        .length,
    [rows],
  );
  const prevRecognitionActiveRef = useRef(0);
  useEffect(() => {
    const prev = prevRecognitionActiveRef.current;
    prevRecognitionActiveRef.current = recognitionActiveCount;
    if (step === 3 && !isPreviewMode && phaseJustFinished(prev, recognitionActiveCount)) {
      notifyDone(t('notify.recognitionDone'), t('notify.recognitionDoneBody').replace('{n}', String(rows.length)));
    }
  }, [recognitionActiveCount, step, isPreviewMode, rows.length, t]);

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
