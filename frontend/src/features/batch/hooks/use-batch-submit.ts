
import { useCallback, useState } from 'react';
import { t } from '@/i18n';
import { localizeErrorMessage } from '@/utils/localizeError';
import type { BoundingBox as EditorBox } from '@/components/ImageBBoxEditor';
import { fileApi } from '@/services/api';
import type { BatchWizardMode, BatchWizardPersistedConfig } from '@/services/batchPipeline';
import {
  submitJob as apiSubmitJob,
  commitItemReview,
  requeueFailed,
  updateJobDraft,
} from '@/services/jobsApi';
import {
  buildPreviewDownloadBlob,
} from '../lib/batch-preview-fixtures';
import { RECOGNITION_DONE_STATUSES, type BatchRow, type ReviewEntity, type Step } from '../types';
import {
  buildJobConfigForWorker,
  clearLocalWizardMaxStep,
  deriveReviewConfirmed,
  mapBackendStatus,
  triggerDownload,
} from './use-batch-wizard-utils';

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
  reviewIndex: number,
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
): BatchSubmitState {
  const [zipLoading, setZipLoading] = useState(false);

  // ── Queue submit ──
  const submitQueueToWorker = useCallback(async () => {
    if (isPreviewMode) {
      setRows((prev) => prev.map((row, index) => ({
        ...row,
        analyzeStatus: index === 0 ? 'completed' : 'awaiting_review',
        has_output: index === 0,
        reviewConfirmed: index === 0,
      })));
      setFurthestStep(5);
      setMsg({ text: t('batchWizard.previewRecognitionDone'), tone: 'ok' });
      return;
    }
    if (!activeJobId) { setMsg({ text: t('batchWizard.noActiveJob'), tone: 'warn' }); return; }
    setMsg(null);
    setRows(prev => prev.map(r => !RECOGNITION_DONE_STATUSES.has(r.analyzeStatus) && r.analyzeStatus !== 'failed' ? { ...r, analyzeStatus: 'pending' as const } : r));
    try {
      const jobCfg = buildJobConfigForWorker(cfg, mode, furthestStep);
      try { await updateJobDraft(activeJobId, { config: jobCfg }); lastSavedJobConfigJson.current = JSON.stringify(jobCfg); } catch { /* */ }
      await apiSubmitJob(activeJobId);
      clearLocalWizardMaxStep(activeJobId);
    } catch (e) { setMsg({ text: localizeErrorMessage(e, 'batchWizard.submitFailed'), tone: 'err' }); }
  }, [activeJobId, cfg, furthestStep, isPreviewMode, mode]);

  // ── Requeue failed ──
  const requeueFailedItems = useCallback(async () => {
    if (!failedRows.length) return;
    if (isPreviewMode) {
      setRows((prev) => prev.map((row) => row.analyzeStatus === 'failed'
        ? { ...row, analyzeStatus: 'awaiting_review', analyzeError: undefined }
        : row));
      setMsg({ text: t('batchWizard.previewRecognitionDone'), tone: 'ok' });
      return;
    }
    if (activeJobId && cfg.executionDefault !== 'local') {
      setMsg(null);
      try {
        await requeueFailed(activeJobId);
        setRows(prev => prev.map(r => r.analyzeStatus === 'failed' ? { ...r, analyzeStatus: 'pending', analyzeError: undefined } : r));
      } catch { /* fallback handled outside */ }
      return;
    }
  }, [activeJobId, cfg.executionDefault, failedRows.length, isPreviewMode]);

  // ── Confirm review ──
  const confirmCurrentReview = useCallback(async () => {
    if (!reviewFile) return;
    setReviewExecuteLoading(true);
    setMsg(null);
    const currentFileId = reviewFile.file_id;
    const currentIsImage = reviewFile.isImageMode;
    try {
      if (isPreviewMode) {
        setRows((prev) => prev.map((row) => row.file_id === currentFileId
          ? { ...row, reviewConfirmed: true, has_output: true, analyzeStatus: 'completed' as const }
          : row));
        const isLastFile = reviewIndex >= doneRows.length - 1;
        if (!isLastFile) setReviewIndex(reviewIndex + 1);
        if (isLastFile) setFurthestStep(5);
        setMsg({ text: t('batchWizard.previewReviewDone'), tone: 'ok' });
        return;
      }
      const jid = activeJobId;
      const linkedItemId = itemIdByFileIdRef.current[currentFileId];
      if (!jid || !linkedItemId) throw new Error(t('batchWizard.noLinkedItem'));
      const entitiesPayload = reviewEntities.map(e => ({ id: e.id, text: e.text, type: e.type, start: e.start, end: e.end, page: e.page ?? 1, confidence: e.confidence ?? 1, selected: e.selected, source: e.source, coref_id: e.coref_id, replacement: e.replacement }));
      const boxesPayload = reviewBoxes.map(b => ({ id: b.id, x: b.x, y: b.y, width: b.width, height: b.height, page: 1, type: b.type, text: b.text, selected: b.selected, source: b.source, confidence: b.confidence }));

      setRows(prev => prev.map(r => r.file_id === currentFileId ? { ...r, reviewConfirmed: true, has_output: true, analyzeStatus: 'completed' as const } : r));
      const isLastFile = reviewIndex >= doneRows.length - 1;
      if (!isLastFile) setReviewIndex(reviewIndex + 1);

      const ok = await flushCurrentReviewDraft();
      if (!ok) throw new Error(reviewDraftError || t('batchWizard.autoSaveFailed'));
      const commitResult = await commitItemReview(jid, linkedItemId, { entities: entitiesPayload as Array<Record<string, unknown>>, bounding_boxes: boxesPayload as Array<Record<string, unknown>> });
      const committedStatus = mapBackendStatus(commitResult.status ?? 'completed');
      setRows(prev => prev.map(r => r.file_id === currentFileId ? { ...r, has_output: Boolean(commitResult.has_output ?? true), reviewConfirmed: deriveReviewConfirmed(commitResult), analyzeStatus: committedStatus, entity_count: typeof commitResult.entity_count === 'number' ? commitResult.entity_count : currentIsImage ? boxesPayload.length : entitiesPayload.length } : r));
      reviewLastSavedJsonRef.current = JSON.stringify({ entities: entitiesPayload, bounding_boxes: boxesPayload });
      reviewDraftDirtyRef.current = false;
      if (isLastFile) setFurthestStep(prev => Math.max(prev, 5) as Step);
    } catch (e) {
      setRows(prev => prev.map(r => r.file_id === currentFileId ? { ...r, reviewConfirmed: false, has_output: false, analyzeStatus: 'awaiting_review' as const } : r));
      setMsg({ text: localizeErrorMessage(e, 'batchWizard.actionFailed'), tone: 'err' });
    } finally { setReviewExecuteLoading(false); }
  }, [activeJobId, doneRows.length, flushCurrentReviewDraft, isPreviewMode, reviewBoxes, reviewDraftError, reviewEntities, reviewFile, reviewIndex]);

  // ── Download ZIP ──
  const downloadZip = useCallback(async (redacted: boolean) => {
    const selectedIds = rows.filter(r => selected.has(r.file_id)).map(r => r.file_id);
    if (!selectedIds.length) { setMsg({ text: t('batchWizard.noFilesSelected'), tone: 'warn' }); return; }
    if (redacted) {
      const noOut = rows.filter(r => selected.has(r.file_id) && !r.has_output);
      if (noOut.length) { setMsg({ text: t('batchWizard.someFilesNotRedacted'), tone: 'warn' }); return; }
    }
    setZipLoading(true);
    setMsg(null);
    try {
      if (isPreviewMode) {
        const blob = buildPreviewDownloadBlob(redacted, rows.filter((row) => selected.has(row.file_id)));
        triggerDownload(blob, redacted ? 'batch_redacted_preview.txt' : 'batch_original_preview.txt');
        setMsg({ text: t('batchWizard.previewDownloadReady'), tone: 'ok' });
        return;
      }
      const blob = await fileApi.batchDownloadZip(selectedIds, redacted);
      triggerDownload(blob, redacted ? 'batch_redacted.zip' : 'batch_original.zip');
      if (redacted && activeJobId) clearLocalWizardMaxStep(activeJobId);
    } catch (e) { setMsg({ text: localizeErrorMessage(e, 'batchWizard.downloadFailed'), tone: 'err' }); }
    finally { setZipLoading(false); }
  }, [activeJobId, isPreviewMode, rows, selected]);

  return {
    submitQueueToWorker,
    requeueFailedItems,
    confirmCurrentReview,
    downloadZip,
    zipLoading,
  };
}

