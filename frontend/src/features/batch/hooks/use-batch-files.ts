// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { t } from '@/i18n';
import { useDropzone, type FileRejection } from 'react-dropzone';
import { fileApi } from '@/services/api';
import type { BatchWizardMode } from '@/services/batchPipeline';
import { FileType } from '@/types';
import { BATCH_FILE_POLL_MS } from '@/constants/timing';
import { deleteJobItem, getJob } from '@/services/jobsApi';
import { batchGetFileRaw } from '@/services/batchPipeline';
import { localizeErrorMessage } from '@/utils/localizeError';
import { ACCEPTED_UPLOAD_FILE_TYPES } from '@/utils/fileUploadAccept';
import {
  RECOGNITION_DONE_STATUSES,
  type BatchRow,
  type BatchUploadIssue,
  type BatchUploadProgress,
  type Step,
} from '../types';
import { mapBackendStatus, deriveReviewConfirmed } from './use-batch-wizard-utils';
import {
  isBatchFileAllowedForMode,
  isBatchImageMode,
  resolveBatchFileType,
  resolveBatchFileTypeFromName,
} from '../utils/file-type';
import { isBatchRowReadyForDelivery } from '../lib/batch-export-report';

const BATCH_UPLOAD_CONCURRENCY = 1;
const BATCH_JOB_POLL_HIDDEN_MS = 5000;
const BATCH_FIRST_REVIEWABLE_POLL_MS = 250;

function fileUploadKey(file: File): string {
  return `${file.name}::${file.size}`;
}

function rowUploadKey(row: BatchRow): string {
  return `${row.original_filename}::${row.file_size}`;
}

function dedupeBatchRows(rows: BatchRow[]): BatchRow[] {
  const seen = new Set<string>();
  return rows.filter((row) => {
    const key = rowUploadKey(row);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

export interface BatchFilesState {
  rows: BatchRow[];
  setRows: React.Dispatch<React.SetStateAction<BatchRow[]>>;
  selected: Set<string>;
  setSelected: React.Dispatch<React.SetStateAction<Set<string>>>;
  selectedIds: string[];
  loading: boolean;
  msg: { text: string; tone: 'neutral' | 'ok' | 'warn' | 'err' } | null;
  setMsg: (msg: { text: string; tone: 'neutral' | 'ok' | 'warn' | 'err' } | null) => void;
  toggle: (id: string) => void;
  selectReadyForDelivery: () => void;
  removeRow: (fileId: string) => Promise<void>;
  clearRows: () => Promise<void>;
  getRootProps: ReturnType<typeof useDropzone>['getRootProps'];
  getInputProps: ReturnType<typeof useDropzone>['getInputProps'];
  isDragActive: boolean;
  uploadIssues: BatchUploadIssue[];
  uploadProgress: BatchUploadProgress | null;
  clearUploadIssues: () => void;
  failedRows: BatchRow[];
  analyzeRunning: boolean;
  hasItemsInProgress: boolean;
  batchGroupIdRef: React.MutableRefObject<string | null>;
  itemIdByFileIdRef: React.MutableRefObject<Record<string, string>>;
}

export function useBatchFiles(
  step: Step,
  mode: BatchWizardMode,
  activeJobId: string | null,
  isPreviewMode: boolean,
): BatchFilesState {
  const [rows, setRows] = useState<BatchRow[]>([]);
  const batchGroupIdRef = useRef<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(false);
  const [uploadIssues, setUploadIssues] = useState<BatchUploadIssue[]>([]);
  const [uploadProgress, setUploadProgress] = useState<BatchUploadProgress | null>(null);
  const [analyzeRunning, _setAnalyzeRunning] = useState(false);
  const [msg, setMsg] = useState<{ text: string; tone: 'neutral' | 'ok' | 'warn' | 'err' } | null>(
    null,
  );
  const itemIdByFileIdRef = useRef<Record<string, string>>({});
  const pendingUploadKeysRef = useRef<Set<string>>(new Set());
  const uploadedUploadKeysRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    uploadedUploadKeysRef.current = new Set(rows.map(rowUploadKey));
  }, [rows]);

  const failedRows = useMemo(() => rows.filter((r) => r.analyzeStatus === 'failed'), [rows]);
  const hasItemsInProgress = useMemo(
    () =>
      rows.some(
        (r) =>
          r.analyzeStatus === 'pending' ||
          r.analyzeStatus === 'parsing' ||
          r.analyzeStatus === 'analyzing',
      ),
    [rows],
  );
  const hasReviewableRows = useMemo(
    () => rows.some((row) => RECOGNITION_DONE_STATUSES.has(row.analyzeStatus)),
    [rows],
  );
  const selectedIds = rows.filter((r) => selected.has(r.file_id)).map((r) => r.file_id);
  const clearUploadIssues = useCallback(() => setUploadIssues([]), []);
  const selectReadyForDelivery = useCallback(() => {
    setSelected(new Set(rows.filter(isBatchRowReadyForDelivery).map((row) => row.file_id)));
  }, [rows]);

  const rejectionToIssue = useCallback((rejection: FileRejection): BatchUploadIssue => {
    const firstError = rejection.errors[0];
    const reason =
      firstError?.code === 'file-too-large'
        ? t('batchWizard.step2.rejectTooLarge')
        : firstError?.code === 'file-invalid-type'
          ? t('batchWizard.step2.rejectInvalidType')
          : firstError?.message || t('batchWizard.step2.rejectGeneric');
    return {
      id: `reject-${rejection.file.name}-${rejection.file.size}-${Date.now()}`,
      filename: rejection.file.name,
      reason,
    };
  }, []);

  const modeRejectedIssue = useCallback(
    (file: File): BatchUploadIssue => ({
      id: `mode-${file.name}-${file.size}-${Date.now()}`,
      filename: file.name,
      reason:
        mode === 'text'
          ? t('batchWizard.step2.rejectModeMismatchText')
          : mode === 'image'
            ? t('batchWizard.step2.rejectModeMismatchImage')
            : t('batchWizard.step2.rejectGeneric'),
    }),
    [mode],
  );

  // ── File upload ──
  const onDrop = useCallback(
    async (accepted: File[], rejected: FileRejection[] = []) => {
      const modeAccepted: File[] = [];
      const modeRejected: BatchUploadIssue[] = [];
      const duplicateRejected: BatchUploadIssue[] = [];
      const knownKeys = new Set([...rows.map(rowUploadKey), ...uploadedUploadKeysRef.current]);
      const seenKeys = new Set<string>();
      accepted.forEach((file) => {
        const fileType = resolveBatchFileTypeFromName(file.name);
        const key = fileUploadKey(file);
        if (knownKeys.has(key) || seenKeys.has(key) || pendingUploadKeysRef.current.has(key)) {
          duplicateRejected.push({
            id: `duplicate-${file.name}-${file.size}-${Date.now()}`,
            filename: file.name,
            reason: t('batchWizard.step2.duplicateSkipped'),
          });
          return;
        }
        seenKeys.add(key);
        if (isBatchFileAllowedForMode(mode, fileType)) {
          modeAccepted.push(file);
        } else {
          modeRejected.push(modeRejectedIssue(file));
        }
      });
      const rejectedIssues = [...rejected.map(rejectionToIssue), ...modeRejected, ...duplicateRejected];
      if (rejectedIssues.length) {
        setUploadIssues(rejectedIssues);
      } else {
        setUploadIssues([]);
      }
      if (!modeAccepted.length) {
        if (rejectedIssues.length) {
          setMsg({
            text: t('batchWizard.step2.uploadIssueSummary').replace(
              '{count}',
              String(rejectedIssues.length),
            ),
            tone: 'warn',
          });
        }
        return;
      }
      setLoading(true);
      if (!rejectedIssues.length) setMsg(null);
      const pendingKeys = modeAccepted.map(fileUploadKey);
      pendingKeys.forEach((key) => pendingUploadKeysRef.current.add(key));
      if (isPreviewMode) {
        const uploaded = modeAccepted.map((file, index) => {
          const fileType = resolveBatchFileTypeFromName(file.name);
          return {
            file_id: `preview-upload-${Date.now()}-${index}`,
            original_filename: file.name,
            file_size: file.size,
            file_type: fileType,
            created_at: new Date().toISOString(),
            has_output: false,
            reviewConfirmed: false,
            entity_count: 0,
            analyzeStatus: 'pending' as const,
            isImageMode: isBatchImageMode(fileType),
          };
        });
        setRows((prev) => dedupeBatchRows([...uploaded, ...prev]));
        setSelected((prev) => {
          const next = new Set(prev);
          uploaded.forEach((row) => next.add(row.file_id));
          return next;
        });
        setMsg({
          text: t('batchWizard.previewFilesAdded').replace('{count}', String(uploaded.length)),
          tone: 'ok',
        });
        setLoading(false);
        pendingKeys.forEach((key) => pendingUploadKeysRef.current.delete(key));
        return;
      }
      const uploaded: BatchRow[] = [];
      const failed: BatchUploadIssue[] = [];
      try {
        if (!batchGroupIdRef.current) {
          batchGroupIdRef.current =
            typeof crypto !== 'undefined' && crypto.randomUUID
              ? crypto.randomUUID()
              : `bg_${Date.now()}_${Math.random().toString(36).slice(2, 11)}`;
        }
        const bg = batchGroupIdRef.current;
        const uploadedByIndex: Array<BatchRow | undefined> = new Array(modeAccepted.length);
        let cursor = 0;
        const uploadNext = async () => {
          while (cursor < modeAccepted.length) {
            const index = cursor;
            cursor += 1;
            const file = modeAccepted[index];
            setUploadProgress((prev) =>
              prev
                ? { ...prev, inFlight: prev.inFlight + 1, currentFile: file.name }
                : prev,
            );
            let ok = false;
            try {
              const r = await fileApi.upload(file, bg, activeJobId ?? undefined, 'batch');
              uploadedUploadKeysRef.current.add(fileUploadKey(file));
              const fileType = resolveBatchFileType(r.file_type);
              uploadedByIndex[index] = {
                file_id: r.file_id,
                original_filename: r.filename,
                file_size: r.file_size,
                file_type: fileType,
                created_at: r.created_at ?? undefined,
                has_output: false,
                reviewConfirmed: false,
                entity_count: 0,
                analyzeStatus: 'pending',
                isImageMode: isBatchImageMode(fileType),
              };
              ok = true;
            } catch (err) {
              failed.push({
                id: `upload-${file.name}-${file.size}-${Date.now()}`,
                filename: file.name,
                reason: localizeErrorMessage(err, 'batchWizard.step2.uploadFailed'),
              });
            } finally {
              setUploadProgress((prev) =>
                prev
                  ? {
                      ...prev,
                      completed: prev.completed + 1,
                      failed: prev.failed + (ok ? 0 : 1),
                      inFlight: Math.max(0, prev.inFlight - 1),
                      currentFile: file.name,
                    }
                  : prev,
              );
            }
          }
        };
        setUploadProgress({
          total: modeAccepted.length,
          completed: 0,
          failed: 0,
          inFlight: 0,
        });
        const workers = Array.from(
          { length: Math.min(BATCH_UPLOAD_CONCURRENCY, modeAccepted.length) },
          () => uploadNext(),
        );
        await Promise.all(workers);
        uploaded.push(...uploadedByIndex.filter((row): row is BatchRow => Boolean(row)));
        if (uploaded.length) {
          setRows((prev) => dedupeBatchRows([...uploaded, ...prev]));
          setSelected((prev) => {
            const n = new Set(prev);
            uploaded.forEach((u) => n.add(u.file_id));
            return n;
          });
          if (activeJobId) {
            try {
              const d = await getJob(activeJobId);
              const m = { ...itemIdByFileIdRef.current };
              for (const it of d.items) m[it.file_id] = it.id;
              itemIdByFileIdRef.current = m;
            } catch {
              /* ignore */
            }
          }
        }
      } finally {
        pendingKeys.forEach((key) => pendingUploadKeysRef.current.delete(key));
        const issues = [...rejectedIssues, ...failed];
        if (issues.length) {
          setUploadIssues(issues);
          setMsg({
            text: t('batchWizard.step2.uploadIssueSummary').replace(
              '{count}',
              String(issues.length),
            ),
            tone: uploaded.length ? 'warn' : 'err',
          });
        }
        setLoading(false);
      }
    },
    [activeJobId, isPreviewMode, mode, modeRejectedIssue, rejectionToIssue, rows],
  );

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: ACCEPTED_UPLOAD_FILE_TYPES,
    maxSize: 50 * 1024 * 1024,
    disabled: loading,
    multiple: true,
  });

  // ── Polling ──
  // Tracks file_ids whose file_info we've already synced post-parse. Upload
  // records file_type from magic bytes ("pdf"), but the parse step may reclassify
  // it to "pdf_scanned" once the text-density heuristic decides. Without this
  // sync the step4 UI would still route scanned PDFs through the text review pane.
  const syncedFileInfoRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    if (isPreviewMode) return;
    if (step !== 3 || !activeJobId || !hasItemsInProgress || analyzeRunning) return;
    let cancelled = false;
    let inFlight = false;
    let timer: ReturnType<typeof window.setTimeout> | null = null;

    const getPollDelay = () => {
      if (typeof document !== 'undefined' && document.hidden) return BATCH_JOB_POLL_HIDDEN_MS;
      return hasReviewableRows ? BATCH_FILE_POLL_MS : BATCH_FIRST_REVIEWABLE_POLL_MS;
    };

    const clearPollTimer = () => {
      if (timer) {
        clearTimeout(timer);
        timer = null;
      }
    };

    const scheduleNextPoll = () => {
      if (cancelled) return;
      clearPollTimer();
      timer = window.setTimeout(() => {
        void poll();
      }, getPollDelay());
    };

    const poll = async () => {
      if (cancelled || inFlight) return;
      inFlight = true;
      try {
        const detail = await getJob(activeJobId);
        if (cancelled) return;
        const itemMap = new Map(detail.items.map((it) => [it.file_id, it]));
        setRows((prev) => {
          let changed = false;
          const next = prev.map((r) => {
            const item = itemMap.get(r.file_id);
            if (!item) return r;
            const analyzeStatus = mapBackendStatus(item.status);
            const reviewConfirmed = deriveReviewConfirmed(item);
            const hasOutput = Boolean(item.has_output);
            const hasReviewDraft = Boolean(item.has_review_draft);
            const isImageMode = r.isImageMode ?? false;
            const analyzeError =
              item.status === 'failed' || item.status === 'cancelled'
                ? item.error_message || t('batchWizard.actionFailed')
                : undefined;
            const entityCount =
              typeof item.entity_count === 'number' ? item.entity_count : r.entity_count;
            const recognitionStage = item.progress_stage ?? null;
            const recognitionCurrent =
              typeof item.progress_current === 'number' ? item.progress_current : undefined;
            const recognitionTotal =
              typeof item.progress_total === 'number' ? item.progress_total : undefined;
            const recognitionMessage = item.progress_message ?? null;
            if (
              r.analyzeStatus === analyzeStatus &&
              r.reviewConfirmed === reviewConfirmed &&
              r.has_output === hasOutput &&
              r.hasReviewDraft === hasReviewDraft &&
              r.isImageMode === isImageMode &&
              r.analyzeError === analyzeError &&
              r.entity_count === entityCount &&
              r.recognitionStage === recognitionStage &&
              r.recognitionCurrent === recognitionCurrent &&
              r.recognitionTotal === recognitionTotal &&
              r.recognitionMessage === recognitionMessage
            ) {
              return r;
            }
            changed = true;
            return {
              ...r,
              analyzeStatus,
              reviewConfirmed,
              has_output: hasOutput,
              hasReviewDraft,
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

        // For each item that's past parsing, refresh file_type/isImageMode from
        // the authoritative file_store so scanned PDFs get routed correctly.
        const needsSync: string[] = [];
        for (const it of detail.items) {
          const status = String(it.status);
          const parsed = status !== 'pending' && status !== 'parsing';
          if (parsed && !syncedFileInfoRef.current.has(it.file_id)) {
            needsSync.push(it.file_id);
          }
        }
        if (needsSync.length) {
          const updates: Record<string, { fileType: FileType; isImageMode: boolean }> = {};
          await Promise.all(
            needsSync.map(async (fid) => {
              try {
                const info = await batchGetFileRaw(fid);
                if (cancelled) return;
                syncedFileInfoRef.current.add(fid);
                const isScanned = Boolean(info.is_scanned);
                const resolvedType = resolveBatchFileType(info.file_type, isScanned);
                updates[fid] = {
                  fileType: resolvedType,
                  isImageMode: isBatchImageMode(resolvedType),
                };
              } catch {
                /* ignore — will retry on next poll tick */
              }
            }),
          );
          if (!cancelled && Object.keys(updates).length) {
            setRows((prev) =>
              prev.map((r) => {
                const u = updates[r.file_id];
                if (!u) return r;
                if (r.file_type === u.fileType && r.isImageMode === u.isImageMode) return r;
                return { ...r, file_type: u.fileType, isImageMode: u.isImageMode };
              }),
            );
          }
        }
      } catch {
        /* ignore network jitter */
      } finally {
        inFlight = false;
        scheduleNextPoll();
      }
    };

    const handleVisibilityChange = () => {
      if (cancelled) return;
      clearPollTimer();
      if (typeof document !== 'undefined' && document.hidden) {
        scheduleNextPoll();
      } else {
        void poll();
      }
    };

    if (typeof document !== 'undefined') {
      document.addEventListener('visibilitychange', handleVisibilityChange);
    }
    void poll();
    return () => {
      cancelled = true;
      clearPollTimer();
      if (typeof document !== 'undefined') {
        document.removeEventListener('visibilitychange', handleVisibilityChange);
      }
    };
  }, [step, activeJobId, hasItemsInProgress, hasReviewableRows, analyzeRunning, isPreviewMode]);

  // Reset the sync cache whenever we switch jobs so a new job re-syncs cleanly.
  useEffect(() => {
    syncedFileInfoRef.current = new Set();
  }, [activeJobId]);

  const toggle = useCallback((id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const dropRowLocally = useCallback((fileId: string) => {
    setRows((prev) => prev.filter((r) => r.file_id !== fileId));
    setSelected((prev) => {
      if (!prev.has(fileId)) return prev;
      const next = new Set(prev);
      next.delete(fileId);
      return next;
    });
    if (itemIdByFileIdRef.current[fileId]) {
      const { [fileId]: _, ...rest } = itemIdByFileIdRef.current;
      itemIdByFileIdRef.current = rest;
    }
  }, []);

  const removeRow = useCallback(
    async (fileId: string) => {
      if (isPreviewMode) {
        dropRowLocally(fileId);
        return;
      }
      const itemId = itemIdByFileIdRef.current[fileId];
      try {
        if (activeJobId && itemId) {
          await deleteJobItem(activeJobId, itemId);
        } else {
          // No linked job item (e.g. file uploaded outside a batch job) — delete
          // the file directly so it doesn't linger in the upload store.
          await fileApi.delete(fileId);
        }
        dropRowLocally(fileId);
      } catch (err) {
        setMsg({ text: localizeErrorMessage(err, 'batchWizard.actionFailed'), tone: 'err' });
      }
    },
    [activeJobId, dropRowLocally, isPreviewMode],
  );

  const clearRows = useCallback(async () => {
    if (isPreviewMode) {
      setRows([]);
      setSelected(new Set());
      itemIdByFileIdRef.current = {};
      return;
    }
    const ids = rows.map((r) => r.file_id);
    if (!ids.length) return;
    const failures: string[] = [];
    for (const fid of ids) {
      const itemId = itemIdByFileIdRef.current[fid];
      try {
        if (activeJobId && itemId) {
          await deleteJobItem(activeJobId, itemId);
        } else {
          await fileApi.delete(fid);
        }
        dropRowLocally(fid);
      } catch (err) {
        failures.push(fid);
        console.warn('clearRows: failed to remove', fid, err);
      }
    }
    if (failures.length) {
      setMsg({ text: t('batchWizard.actionFailed'), tone: 'err' });
    }
  }, [activeJobId, dropRowLocally, isPreviewMode, rows]);

  return {
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
    failedRows,
    analyzeRunning,
    hasItemsInProgress,
    batchGroupIdRef,
    itemIdByFileIdRef,
  };
}
