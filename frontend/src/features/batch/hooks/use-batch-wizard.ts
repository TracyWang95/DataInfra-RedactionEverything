// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0


import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import {
  useLocation,
  useParams,
  useBlocker,
  useSearchParams,
} from 'react-router-dom';
import { t } from '@/i18n';
import { localizeErrorMessage } from '@/utils/localizeError';

import { FileType } from '@/types';
import {
  batchGetFileRaw,
  type BatchWizardMode,
} from '@/services/batchPipeline';
import {
  createJob,
  getJob,
  updateJobDraft,
} from '@/services/jobsApi';
import {
  buildPreviewBatchRows,
  isPreviewBatchJobId,
  PREVIEW_BATCH_JOB_ID,
} from '../lib/batch-preview-fixtures';
import {
  RECOGNITION_DONE_STATUSES,
  type BatchRow,
  type Step,
} from '../types';

import {
  buildJobConfigForWorker,
  deriveReviewConfirmed,
  effectiveWizardFurthestStep,
  isBatchWizardMode,
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

export function useBatchWizard() {
  const { batchMode } = useParams<{ batchMode: string }>();
  const location = useLocation();
  const [searchParams, setSearchParams] = useSearchParams();
  const modeValid = isBatchWizardMode(batchMode);
  const mode: BatchWizardMode = modeValid ? batchMode : 'smart';
  const previewRequested = searchParams.get('preview') === '1';
  const queryJobId = searchParams.get('jobId');
  const isPreviewMode = previewRequested || isPreviewBatchJobId(queryJobId);
  const sessionJobKey = `lr_batch_job_id_${mode}`;

  // ── Job identity ──
  const [activeJobId, setActiveJobId] = useState<string | null>(() => {
    try {
      const stored = sessionStorage.getItem(sessionJobKey);
      return stored && !isPreviewBatchJobId(stored) ? stored : null;
    } catch {
      return null;
    }
  });
  const [jobSkipItemReview, setJobSkipItemReview] = useState(false);
  const hydratedFromUrlRef = useRef(false);
  const batchHydrateGenRef = useRef(0);
  const urlHydrateKeyRef = useRef('');
  const prevHydrateUrlStepRef = useRef<string | null>(null);
  const internalStepNavRef = useRef(false);
  const lastSavedJobConfigJson = useRef<string>('');
  const prevFurthestForImmediateSaveRef = useRef<Step>(1);

  // ── Step tracking ──
  const [step, setStep] = useState<Step>(1);
  const [furthestStep, setFurthestStep] = useState<Step>(1);

  // ── Sub-hooks ──
  const files = useBatchFiles(step, activeJobId, isPreviewMode);
  const {
    rows, setRows, selected, setSelected, selectedIds, loading,
    msg, setMsg, toggle, getRootProps, getInputProps, isDragActive,
    failedRows,
    batchGroupIdRef, itemIdByFileIdRef,
  } = files;

  const config = useBatchConfig(mode, activeJobId, setActiveJobId, isPreviewMode, setMsg);
  const {
    cfg, setCfg, configLoaded, textTypes, pipelines, presets,
    textPresets, visionPresets, confirmStep1, setConfirmStep1,
    isStep1Complete, jobPriority, setJobPriority,
    onBatchTextPresetChange, onBatchVisionPresetChange,
  } = config;

  const review = useBatchReview(
    step, rows, activeJobId, itemIdByFileIdRef,
    cfg, isPreviewMode, textTypes, setMsg,
  );
  const {
    reviewIndex, setReviewIndex, reviewEntities, reviewBoxes,
    reviewLoading, reviewExecuteLoading, setReviewExecuteLoading,
    reviewDraftSaving, reviewDraftError,
    reviewImagePreviewLoading, reviewOrigImageBlobUrl,
    reviewTextUndoStack, reviewTextRedoStack,
    reviewImageUndoStack, reviewImageRedoStack,
    reviewTextContent, reviewTextContentRef, reviewTextScrollRef,
    reviewDraftDirtyRef,
    reviewLastSavedJsonRef,
    reviewFile, doneRows, reviewFileReadOnly,
    selectedReviewEntityCount, selectedReviewBoxCount,
    reviewImagePreviewSrc, displayPreviewMap, textPreviewSegments,
    reviewedOutputCount, allReviewConfirmed, pendingReviewCount,
    applyReviewEntities, toggleReviewEntitySelected,
    setReviewBoxes, handleReviewBoxesCommit, toggleReviewBoxSelected,
    undoReviewText, redoReviewText, undoReviewImage, redoReviewImage,
    flushCurrentReviewDraft,
    navigateReviewIndex, rerunCurrentItemRecognition, rerunRecognitionLoading,
  } = review;

  const submit = useBatchSubmit(
    mode, activeJobId, isPreviewMode, cfg, furthestStep,
    rows, setRows, selected, setMsg, setFurthestStep,
    failedRows, reviewFile, reviewIndex, setReviewIndex,
    doneRows, reviewEntities, reviewBoxes,
    reviewDraftError, flushCurrentReviewDraft,
    reviewLastSavedJsonRef, reviewDraftDirtyRef,
    setReviewExecuteLoading, itemIdByFileIdRef, lastSavedJobConfigJson,
  );
  const { submitQueueToWorker, requeueFailedItems, confirmCurrentReview, downloadZip, zipLoading } = submit;

  // ── Session persistence ──
  useEffect(() => {
    try {
      if (activeJobId && !isPreviewMode && !isPreviewBatchJobId(activeJobId)) {
        sessionStorage.setItem(sessionJobKey, activeJobId);
      } else {
        sessionStorage.removeItem(sessionJobKey);
      }
    } catch { /* ignore */ }
  }, [activeJobId, isPreviewMode, sessionJobKey]);

  useEffect(() => {
    if (!isPreviewMode && activeJobId && isPreviewBatchJobId(activeJobId)) {
      setActiveJobId(null); // eslint-disable-line react-hooks/set-state-in-effect -- clearing stale preview job id on mode change
    }
  }, [activeJobId, isPreviewMode]);

  useEffect(() => {
    const jid = searchParams.get('jobId');
    if (!jid) return;
    setActiveJobId(prev => (prev === jid ? prev : jid)); // eslint-disable-line react-hooks/set-state-in-effect -- syncing job id from URL search params
  }, [searchParams]);

  useEffect(() => { lastSavedJobConfigJson.current = ''; }, [activeJobId]);
  useEffect(() => { prevFurthestForImmediateSaveRef.current = 1; }, [activeJobId]);

  // ── Config auto-save to job draft ──
  useEffect(() => {
    if (isPreviewMode) return;
    if (!configLoaded || !activeJobId) return;
    const payload = buildJobConfigForWorker(cfg, mode, furthestStep);
    const j = JSON.stringify(payload);
    const timer = window.setTimeout(() => {
      if (j === lastSavedJobConfigJson.current) return;
      void (async () => {
        try {
          await updateJobDraft(activeJobId, { config: payload });
          lastSavedJobConfigJson.current = j;
        } catch { /* only draft writable */ }
      })();
    }, 900);
    return () => window.clearTimeout(timer);
  }, [cfg, mode, activeJobId, configLoaded, furthestStep, isPreviewMode]);

  useEffect(() => {
    if (isPreviewMode) return;
    if (!configLoaded || !activeJobId) return;
    const prev = prevFurthestForImmediateSaveRef.current;
    if (furthestStep < 2) { prevFurthestForImmediateSaveRef.current = furthestStep; return; }
    if (furthestStep <= prev) { prevFurthestForImmediateSaveRef.current = furthestStep; return; }
    prevFurthestForImmediateSaveRef.current = furthestStep;
    const payload = buildJobConfigForWorker(cfg, mode, furthestStep);
    const j = JSON.stringify(payload);
    if (j === lastSavedJobConfigJson.current) return;
    void (async () => {
      try { await updateJobDraft(activeJobId, { config: payload }); lastSavedJobConfigJson.current = j; } catch { /* */ }
    })();
  }, [furthestStep, cfg, mode, activeJobId, configLoaded, isPreviewMode]);

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
    const _isNew = searchParams.get('new') === '1'; void _isNew;
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
      setActiveJobId(PREVIEW_BATCH_JOB_ID); // eslint-disable-line react-hooks/set-state-in-effect -- hydrating state from URL/preview fixtures
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
        const jc = detail.config as Record<string, unknown>;
        const mergedCfg = mergeJobConfigIntoWizardCfg(cfg, jc);
        setCfg(mergedCfg);

        const jobTypeNav = (['smart_batch', 'text_batch', 'image_batch'].includes(detail.job_type) ? detail.job_type : 'smart_batch') as 'smart_batch' | 'text_batch' | 'image_batch';
        const restoredFurthest: Step | null = effectiveWizardFurthestStep({ jobConfig: jc, navHints: detail.nav_hints, jobType: jobTypeNav });

        const persistDraftFingerprint = (furthest: Step) => {
          lastSavedJobConfigJson.current = JSON.stringify(buildJobConfigForWorker(mergedCfg, mode, furthest));
        };

        if (detail.items.length === 0) {
          const sn = stepRaw ? Number.parseInt(stepRaw, 10) : NaN;
          const urlStep = Number.isFinite(sn) ? (Math.min(5, Math.max(1, sn)) as Step) : null;
          const sessionMax = readLocalWizardMaxStep(jobId);
          const baseEmpty = urlStep !== null && urlStep >= 2
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
          setFurthestStep(prev => Math.max(prev, mergedFurthest) as Step);
          persistDraftFingerprint(mergedFurthest);
          if (detail.status === 'draft') {
            const payload = buildJobConfigForWorker(mergedCfg, mode, mergedFurthest);
            try { await updateJobDraft(jobId, { config: payload }); lastSavedJobConfigJson.current = JSON.stringify(payload); } catch { /* */ }
          }
          if (hydrateGen !== batchHydrateGenRef.current) return;
          hydratedFromUrlRef.current = true;
          return;
        }

        const badItemIdInUrl = Boolean(itemId && !detail.items.some(i => i.id === itemId));
        const item = itemId && !badItemIdInUrl ? detail.items.find(i => i.id === itemId) : detail.items[0];
        if (!item) { setMsg({ text: t('batchWizard.itemNotFound'), tone: 'warn' }); return; }

        const sn0 = stepRaw ? Number.parseInt(stepRaw, 10) : NaN;
        const urlStepNum0 = Number.isFinite(sn0) ? (Math.min(5, Math.max(1, sn0)) as Step) : null;
        const sessionMaxItems0 = readLocalWizardMaxStep(jobId);
        const basePersist0 = urlStepNum0 !== null && urlStepNum0 >= 2
          ? Math.max(restoredFurthest ?? 1, urlStepNum0)
          : Math.max(restoredFurthest ?? 1, sessionMaxItems0 ?? 1);
        let resolvedNextStep: Step;
        if (urlStepNum0 !== null) resolvedNextStep = Math.max(urlStepNum0, basePersist0) as Step;
        else if (detail.status === 'draft') resolvedNextStep = Math.min(5, Math.max(2, basePersist0)) as Step;
        else if (detail.status === 'awaiting_review') resolvedNextStep = 4;
        else resolvedNextStep = Math.min(5, Math.max(3, basePersist0)) as Step;

        if (resolvedNextStep >= 2 && resolvedNextStep <= 3) {
          setConfirmStep1(true);
          setStep(resolvedNextStep);
          setFurthestStep(prev => Math.max(prev, restoredFurthest ?? 1, resolvedNextStep) as Step);
          persistDraftFingerprint(Math.max(restoredFurthest ?? 1, resolvedNextStep) as Step);
        }

        const hydratedItems = await Promise.all(
          detail.items.map(async entry => {
            const info = await batchGetFileRaw(entry.file_id);
            return { item: entry, info };
          }),
        );
        if (hydrateGen !== batchHydrateGenRef.current) return;

        const urlMatchIndex = Math.max(0, hydratedItems.findIndex(entry => entry.item.id === item.id));
        const urlMatchHasOutput = Boolean((hydratedItems[urlMatchIndex]?.info || {}).output_path);
        const firstPendingIdx = urlMatchHasOutput
          ? hydratedItems.findIndex(e => !e.info?.output_path && RECOGNITION_DONE_STATUSES.has(mapBackendStatus(e.item.status)))
          : -1;
        const currentIndex = firstPendingIdx >= 0 ? firstPendingIdx : urlMatchIndex;
        const fileIdToItemId = Object.fromEntries(hydratedItems.map(entry => [entry.item.file_id, entry.item.id]));
        const rowsFromJob: BatchRow[] = hydratedItems.map(entry => {
          const rowInfo = entry.info;
          const rowFileTypeRaw = String(rowInfo.file_type ?? entry.item.file_type ?? 'docx').toLowerCase();
          const isScanned = Boolean(rowInfo.is_scanned);
          const rowFileType: FileType =
            rowFileTypeRaw === 'image' || rowFileTypeRaw === 'jpg' || rowFileTypeRaw === 'jpeg' || rowFileTypeRaw === 'png'
              ? FileType.IMAGE
              : rowFileTypeRaw === 'pdf_scanned' || (rowFileTypeRaw === 'pdf' && isScanned)
                ? FileType.PDF_SCANNED
                : rowFileTypeRaw === 'pdf' ? FileType.PDF : FileType.DOCX;
          return {
            file_id: entry.item.file_id,
            original_filename: String(rowInfo.original_filename ?? entry.item.filename ?? entry.item.file_id),
            file_size: Number(rowInfo.file_size ?? 0),
            file_type: rowFileType,
            created_at: String(rowInfo.created_at ?? entry.item.created_at ?? ''),
            has_output: Boolean(rowInfo.output_path ?? entry.item.has_output),
            reviewConfirmed: deriveReviewConfirmed(entry.item),
            entity_count: typeof entry.item.entity_count === 'number' ? entry.item.entity_count : Array.isArray(rowInfo.entities) ? rowInfo.entities.length : 0,
            analyzeStatus: mapBackendStatus(entry.item.status),
            analyzeError: entry.item.status === 'failed' || entry.item.status === 'cancelled' ? (entry.item.error_message || t('batchWizard.actionFailed')) : undefined,
            isImageMode: rowFileType === FileType.IMAGE || rowFileType === FileType.PDF_SCANNED,
          };
        });

        const allRowsReviewConfirmed = rowsFromJob.length > 0 && rowsFromJob.every(row => row.reviewConfirmed === true);
        const anyRecognitionDone = rowsFromJob.some(row => RECOGNITION_DONE_STATUSES.has(row.analyzeStatus));
        let resolvedStepWithGates = resolvedNextStep;
        if (resolvedStepWithGates >= 4 && !anyRecognitionDone) resolvedStepWithGates = 3 as Step;
        if (resolvedStepWithGates === 5 && !allRowsReviewConfirmed) resolvedStepWithGates = 4 as Step;

        itemIdByFileIdRef.current = fileIdToItemId;
        setJobSkipItemReview(Boolean(detail.skip_item_review));
        setRows(rowsFromJob);
        setSelected(new Set(rowsFromJob.map(row => row.file_id)));
        setReviewIndex(currentIndex);
        batchGroupIdRef.current = jobId;
        if (resolvedStepWithGates >= 2) setConfirmStep1(true);
        setStep(resolvedStepWithGates);
        setFurthestStep(prev => Math.max(prev, restoredFurthest ?? 1, resolvedStepWithGates) as Step);
        persistDraftFingerprint(Math.max(restoredFurthest ?? 1, resolvedStepWithGates) as Step);
        hydratedFromUrlRef.current = true;
      } catch (e) {
        if (hydrateGen === batchHydrateGenRef.current) {
          setMsg({ text: localizeErrorMessage(e, 'batchWizard.loadJobFailed'), tone: 'err' });
        }
      }
    })();
    return () => { batchHydrateGenRef.current += 1; };
  }, [configLoaded, location.search, mode, isPreviewMode, searchParams, batchGroupIdRef, itemIdByFileIdRef, setCfg, setConfirmStep1, setMsg, setReviewIndex, setRows, setSelected, cfg, step]);

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
  const allAnalyzeDone = useMemo(
    () => rows.length > 0 && rows.every(row => RECOGNITION_DONE_STATUSES.has(row.analyzeStatus)),
    [rows],
  );

  // ── Step navigation ──
  const canUnlockStep = useCallback((target: Step): boolean => {
    if (target === 1) return true;
    if (target === 2) return isStep1Complete;
    if (target === 3) return rows.length > 0;
    if (target === 4) return allAnalyzeDone;
    if (jobSkipItemReview) return rows.length > 0 && rows.every(row => row.has_output);
    return allReviewConfirmed;
  }, [allAnalyzeDone, allReviewConfirmed, isStep1Complete, jobSkipItemReview, rows]);

  const canGoStep = useCallback((target: Step): boolean => {
    if (target === step) return true;
    if (isPreviewMode) return true;
    if (target <= furthestStep) return canUnlockStep(target);
    const nextAvailableStep = Math.min(5, furthestStep + 1) as Step;
    return target === nextAvailableStep && canUnlockStep(target);
  }, [canUnlockStep, furthestStep, isPreviewMode, step]);

  const flushJobDraftFromStep1 = useCallback(async () => {
    if (isPreviewMode || !activeJobId) return;
    if (!activeJobId) return;
    const payload = buildJobConfigForWorker(cfg, mode, furthestStep);
    const j = JSON.stringify(payload);
    if (j === lastSavedJobConfigJson.current) return;
    try { await updateJobDraft(activeJobId, { config: payload }); lastSavedJobConfigJson.current = j; } catch { /* */ }
  }, [activeJobId, cfg, furthestStep, isPreviewMode, mode]);

  const applyStep = useCallback((s: Step) => {
    if (s === step) return;
    if (s >= 2 && !isStep1Complete) {
      setMsg({ text: !configLoaded ? t('batchWizard.waitConfig') : !confirmStep1 ? t('batchWizard.confirmConfigFirst') : t('batchWizard.selectTypesFirst'), tone: 'warn' });
      return;
    }
    if (!canGoStep(s)) { setMsg({ text: t('batchWizard.stepsOrder'), tone: 'warn' }); return; }
    if (step === 1 && s >= 2 && activeJobId) void flushJobDraftFromStep1();
    internalStepNavRef.current = true;
    setStep(s);
    setFurthestStep(prev => Math.max(prev, s) as Step);
    setMsg(null);
    if (s === 4) {
      const firstPending = doneRows.findIndex(r => !r.has_output);
      setReviewIndex(firstPending >= 0 ? firstPending : 0);
    }
    if (s === 5 && activeJobId && !isPreviewMode) {
      void (async () => {
        try {
          const detail = await getJob(activeJobId);
          const itemMap = new Map(detail.items.map(it => [it.file_id, it]));
          setRows(prev => prev.map(r => { const item = itemMap.get(r.file_id); if (!item) return r; return { ...r, has_output: Boolean(item.has_output), analyzeStatus: mapBackendStatus(item.status), reviewConfirmed: deriveReviewConfirmed(item) }; }));
        } catch { /* ignore */ }
      })();
    }
  }, [activeJobId, canGoStep, configLoaded, confirmStep1, doneRows, flushJobDraftFromStep1, isPreviewMode, isStep1Complete, step, setMsg, setReviewIndex, setRows]);

  const goStep = useCallback((s: Step) => {
    if (step === 4 && s !== 5) {
      void (async () => { const ok = await flushCurrentReviewDraft(); if (ok) applyStep(s); })();
      return;
    }
    applyStep(s);
  }, [applyStep, flushCurrentReviewDraft, step]);

  const advanceToUploadStep = useCallback(async () => {
    if (!isStep1Complete) {
      setMsg({ text: !configLoaded ? t('batchWizard.waitConfig') : !confirmStep1 ? t('batchWizard.confirmConfigFirst') : t('batchWizard.selectTypesFirst'), tone: 'warn' });
      return;
    }
    try {
      if (isPreviewMode) {
        setActiveJobId(PREVIEW_BATCH_JOB_ID);
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
        } catch {
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
      }
      lastSavedJobConfigJson.current = JSON.stringify(payload);
      internalStepNavRef.current = true;
      setStep(2);
      setFurthestStep(prev => Math.max(prev, 2) as Step);
      setMsg(null);
    } catch (e) { setMsg({ text: localizeErrorMessage(e, 'batchWizard.actionFailed'), tone: 'err' }); }
  }, [activeJobId, cfg, configLoaded, confirmStep1, furthestStep, isPreviewMode, isStep1Complete, jobPriority, mode, itemIdByFileIdRef, setMsg, setRows, setSelected]);

  const advanceToExportStep = useCallback(async () => {
    if (!rows.length) { setMsg({ text: t('batchWizard.noFilesToExport'), tone: 'warn' }); return; }
    await flushCurrentReviewDraft();
    if (isPreviewMode) {
      if (!allReviewConfirmed) { setMsg({ text: t('batchWizard.notAllFilesConfirmed'), tone: 'warn' }); return; }
      internalStepNavRef.current = true;
      setStep(5);
      setFurthestStep(5);
      setMsg(null);
      return;
    }
    if (activeJobId) {
      try {
        const detail = await getJob(activeJobId);
        const itemMap = new Map(detail.items.map(it => [it.file_id, it]));
        const backendFileIds = new Set(detail.items.map(it => it.file_id));
        setRows(prev => prev.filter(r => backendFileIds.has(r.file_id)).map(r => { const item = itemMap.get(r.file_id); if (!item) return r; return { ...r, has_output: Boolean(item.has_output), analyzeStatus: mapBackendStatus(item.status), reviewConfirmed: deriveReviewConfirmed(item) }; }));
        const freshConfirmed = detail.items.every(it => deriveReviewConfirmed(it));
        if (!freshConfirmed) { setMsg({ text: t('batchWizard.notAllFilesConfirmed'), tone: 'warn' }); return; }
        internalStepNavRef.current = true;
        setStep(5);
        setFurthestStep(prev => Math.max(prev, 5) as Step);
        setMsg(null);
        return;
      } catch { /* fallback */ }
    }
    if (!allReviewConfirmed) { setMsg({ text: t('batchWizard.notAllFilesConfirmed'), tone: 'warn' }); return; }
    internalStepNavRef.current = true;
    setStep(5);
    setFurthestStep(prev => Math.max(prev, 5) as Step);
    setMsg(null);
  }, [activeJobId, allReviewConfirmed, flushCurrentReviewDraft, isPreviewMode, rows.length, setMsg, setRows]);

  // ── Blocker effects ──
  const [leaveConfirmOpen, _setLeaveConfirmOpen] = useState(false);
  const showLeaveConfirmModal = leaveConfirmOpen || navigationBlocker.state === 'blocked';

  useEffect(() => {
    if (navigationBlocker.state !== 'blocked') return;
    void (async () => { const ok = await flushCurrentReviewDraft(); if (ok && navigationBlocker.state === 'blocked') navigationBlocker.proceed(); })();
  }, [flushCurrentReviewDraft, navigationBlocker]);

  useEffect(() => {
    const onBeforeUnload = (e: BeforeUnloadEvent) => { if (step !== 4 || !reviewDraftDirtyRef.current) return; e.preventDefault(); e.returnValue = ''; };
    window.addEventListener('beforeunload', onBeforeUnload);
    return () => window.removeEventListener('beforeunload', onBeforeUnload);
  }, [step, reviewDraftDirtyRef]);

  useEffect(() => {
    if (step !== 4) return;
    const onPageHide = () => { void flushCurrentReviewDraft(); };
    window.addEventListener('pagehide', onPageHide);
    return () => window.removeEventListener('pagehide', onPageHide);
  }, [flushCurrentReviewDraft, step]);

  return {
    // Identity
    modeValid,
    mode,
    activeJobId,
    previewMode: isPreviewMode,

    // Step
    step,
    furthestStep,
    canGoStep,
    goStep,
    advanceToUploadStep,
    advanceToExportStep,

    // Config
    cfg,
    setCfg,
    configLoaded,
    textTypes,
    pipelines,
    presets,
    textPresets,
    visionPresets,
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

    // Upload
    getRootProps,
    getInputProps,
    isDragActive,

    // Recognition
    submitQueueToWorker,
    requeueFailedItems,
    failedRows,
    doneRows,

    // Review
    reviewIndex,
    reviewFile,
    reviewLoading,
    reviewExecuteLoading,
    reviewEntities,
    reviewBoxes,
    reviewTextContent,
    reviewDraftSaving,
    reviewDraftError,
    reviewFileReadOnly,
    rerunCurrentItemRecognition,
    rerunRecognitionLoading,
    reviewedOutputCount,
    pendingReviewCount,
    allReviewConfirmed,
    reviewImagePreviewSrc,
    reviewImagePreviewLoading,
    reviewOrigImageBlobUrl,
    reviewTextUndoStack,
    reviewTextRedoStack,
    reviewImageUndoStack,
    reviewImageRedoStack,
    selectedReviewEntityCount,
    selectedReviewBoxCount,
    displayPreviewMap,
    textPreviewSegments,
    reviewTextContentRef,
    reviewTextScrollRef,
    navigateReviewIndex,
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

    // Export
    zipLoading,
    downloadZip,

    // Blocker
    showLeaveConfirmModal,
    navigationBlocker,
  };
}
