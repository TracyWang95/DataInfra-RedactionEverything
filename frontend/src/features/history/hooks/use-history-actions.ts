// Copyright 2026 DataInfra-RedactionEverything Contributors

import { useCallback, useState } from 'react';
import { authFetch, downloadFile as downloadAuthenticatedFile } from '@/services/api-client';
import { t } from '@/i18n';
import { fileApi, getBatchZipManifest } from '@/services/api';
import { showToast } from '@/components/Toast';
import { localizeErrorMessage } from '@/utils/localizeError';
import type { FileListItem } from '@/types';
import {
  EMPTY_HISTORY_LIST_STATS,
  type HistoryListStats,
  type HistoryMessage,
} from './use-history-data';

function triggerDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  // Revoke later so the browser has time to start the download (a synchronous
  // revoke can cancel it in some browsers).
  window.setTimeout(() => URL.revokeObjectURL(url), 30_000);
}

export interface UseHistoryActionsOptions {
  /** Current page rows (unfiltered) */
  rows: FileListItem[];
  /** Selected file ids within the filtered view */
  selectedIds: string[];
  page: number;
  pageSize: number;
  /** Reload the list (from use-history-data) */
  load: (isRefresh?: boolean, targetPage?: number, targetSize?: number) => Promise<void>;
  setMsg: React.Dispatch<React.SetStateAction<HistoryMessage | null>>;
  setRows: React.Dispatch<React.SetStateAction<FileListItem[]>>;
  setTotal: React.Dispatch<React.SetStateAction<number>>;
  setListStats: React.Dispatch<React.SetStateAction<HistoryListStats>>;
  setPage: React.Dispatch<React.SetStateAction<number>>;
  setSelected: React.Dispatch<React.SetStateAction<Set<string>>>;
}

export function useHistoryActions({
  rows,
  selectedIds,
  page,
  pageSize,
  load,
  setMsg,
  setRows,
  setTotal,
  setListStats,
  setPage,
  setSelected,
}: UseHistoryActionsOptions) {
  const [zipLoading, setZipLoading] = useState(false);
  const [mutationLoading, setMutationLoading] = useState(false);
  const [cleanupConfirmOpen, setCleanupConfirmOpen] = useState(false);

  /* Confirm dialog */
  const [confirmDlg, setConfirmDlg] = useState<{
    title: string;
    message: string;
    onConfirm: () => void;
  } | null>(null);

  /* Batch zip download */

  const downloadZipByIds = useCallback(
    async (ids: string[], redacted: boolean, filename: string) => {
      if (!ids.length) {
        setMsg({ text: t('history.noDownloadable'), tone: 'warn' });
        return;
      }
      if (redacted) {
        const noOut = rows.filter((r) => ids.includes(r.file_id) && !r.has_output);
        if (noOut.length === ids.length) {
          setMsg({ text: t('history.hasUnredacted'), tone: 'warn' });
          return;
        }
      }
      setZipLoading(true);
      try {
        const blob = await fileApi.batchDownloadZip(ids, redacted);
        triggerDownload(blob, filename);
        const manifest = getBatchZipManifest(blob);
        if (manifest && manifest.skipped_count > 0) {
          const message = t('history.zipPartialDownload')
            .replace('{included}', String(manifest.included_count))
            .replace('{skipped}', String(manifest.skipped_count));
          showToast(message, 'info');
          setMsg({ text: message, tone: 'warn' });
        } else {
          showToast(t('history.zipStarted'), 'success');
          setMsg({ text: t('history.zipStarted'), tone: 'ok' });
        }
      } catch (e) {
        setMsg({ text: localizeErrorMessage(e, 'history.downloadFailed'), tone: 'err' });
      } finally {
        setZipLoading(false);
      }
    },
    [rows, setMsg],
  );

  const downloadZip = useCallback(
    async (redacted: boolean) => {
      if (!selectedIds.length) {
        setMsg({ text: t('history.selectFirst'), tone: 'warn' });
        return;
      }
      await downloadZipByIds(
        selectedIds,
        redacted,
        redacted ? 'history_redacted.zip' : 'history_original.zip',
      );
    },
    [selectedIds, downloadZipByIds, setMsg],
  );

  /* Delete */

  const remove = useCallback(
    (id: string) => {
      setConfirmDlg({
        title: t('history.deleteFileTitle'),
        message: t('history.deleteFileMsg'),
        onConfirm: async () => {
          setConfirmDlg(null);
          setMutationLoading(true);
          try {
            await fileApi.delete(id);
            await load(true, page, pageSize);
            setMsg({ text: t('history.deleted'), tone: 'ok' });
          } catch (e) {
            setMsg({ text: localizeErrorMessage(e, 'history.deleteFailed'), tone: 'err' });
          } finally {
            setMutationLoading(false);
          }
        },
      });
    },
    [load, page, pageSize, setMsg],
  );

  const removeGroup = useCallback(
    (fileIds: string[]) => {
      if (!fileIds.length) return;
      setConfirmDlg({
        title: t('history.deleteGroup'),
        message: t('history.deleteGroupMsg').replace('{n}', String(fileIds.length)),
        onConfirm: async () => {
          setConfirmDlg(null);
          setMutationLoading(true);
          try {
            for (const id of fileIds) await fileApi.delete(id);
            await load(true, page, pageSize);
            setMsg({
              text: t('history.deletedGroup').replace('{n}', String(fileIds.length)),
              tone: 'ok',
            });
          } catch (e) {
            setMsg({ text: localizeErrorMessage(e, 'history.deleteFailed'), tone: 'err' });
          } finally {
            setMutationLoading(false);
          }
        },
      });
    },
    [load, page, pageSize, setMsg],
  );

  /* Cleanup */

  const handleCleanup = useCallback(async () => {
    if (mutationLoading || zipLoading) return;
    setCleanupConfirmOpen(false);
    setMutationLoading(true);
    setRows([]);
    setTotal(0);
    setListStats(EMPTY_HISTORY_LIST_STATS);
    setPage(1);
    setSelected(new Set());
    setMsg(null);
    try {
      const res = await authFetch('/api/v1/safety/cleanup', { method: 'POST' });
      if (!res.ok) throw new Error(t('safety.cleanup.failed'));
      const data = await res.json();
      showToast(
        t('safety.cleanup.success')
          .replace('{files}', String(data.files_removed))
          .replace('{jobs}', String(data.jobs_removed)),
        'success',
      );
    } catch {
      showToast(t('safety.cleanup.failed'), 'error');
      await load(true, 1, pageSize);
    } finally {
      setMutationLoading(false);
    }
  }, [
    load,
    mutationLoading,
    pageSize,
    zipLoading,
    setListStats,
    setMsg,
    setPage,
    setRows,
    setSelected,
    setTotal,
  ]);

  const downloadRow = useCallback(async (row: FileListItem) => {
    await downloadAuthenticatedFile(
      fileApi.getDownloadUrl(row.file_id, row.has_output),
      row.original_filename,
    );
  }, []);

  return {
    /* loading */
    zipLoading,
    mutationLoading,
    /* actions */
    downloadZip,
    downloadRow,
    remove,
    removeGroup,
    /* cleanup */
    cleanupConfirmOpen,
    setCleanupConfirmOpen,
    handleCleanup,
    /* confirm dialog */
    confirmDlg,
    setConfirmDlg,
  };
}
