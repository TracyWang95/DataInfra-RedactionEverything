import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { authFetch } from '@/services/api-client';
import { t } from '@/i18n';
import { fileApi, redactionApi } from '@/services/api';
import { showToast } from '@/components/Toast';
import { localizeErrorMessage } from '@/utils/localizeError';
import { resolveRedactionState } from '@/utils/redactionState';
import type { CompareData, FileListItem } from '@/types';

/* Constants */
export const PAGE_SIZE_OPTIONS = [10, 20, 50, 100] as const;

export type SourceTab = 'all' | 'playground' | 'batch';
export type DateFilter = 'all' | '7d' | '30d';
export type FileTypeFilter = 'all' | 'word' | 'pdf' | 'image';
export type StatusFilter = 'all' | 'redacted' | 'awaiting_review' | 'unredacted';

export type HistoryGroup =
  | { kind: 'standalone'; row: FileListItem }
  | { kind: 'batch'; batch_group_id: string; batch_group_count: number; rows: FileListItem[] }
  | { kind: 'date_group'; label: string; rows: FileListItem[] };

export type HistoryPreviewItem = {
  id: string;
  label: string;
  value: string;
  meta: string;
};

/* Helpers */

function triggerDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export function previewMimeForRow(row: FileListItem): string {
  const ft = String(row.file_type);
  if (ft === 'pdf' || ft === 'pdf_scanned') return 'application/pdf';
  const name = row.original_filename.toLowerCase();
  if (name.endsWith('.png')) return 'image/png';
  if (name.endsWith('.webp')) return 'image/webp';
  if (name.endsWith('.gif')) return 'image/gif';
  if (name.endsWith('.bmp')) return 'image/bmp';
  return 'image/jpeg';
}

export function isBinaryPreviewRow(row: FileListItem | null): boolean {
  if (!row) return false;
  const ft = String(row.file_type);
  return ft === 'image' || ft === 'pdf' || ft === 'pdf_scanned';
}

function normalizeHistoryPreviewItems(fileInfo: Record<string, unknown> | null): HistoryPreviewItem[] {
  if (!fileInfo) return [];
  const items: HistoryPreviewItem[] = [];
  const entities = Array.isArray(fileInfo.entities) ? fileInfo.entities : [];
  const rawBoxes = fileInfo.bounding_boxes;
  const boxes = Array.isArray(rawBoxes)
    ? rawBoxes
    : rawBoxes && typeof rawBoxes === 'object'
      ? Object.values(rawBoxes).flatMap(v => (Array.isArray(v) ? v : []))
      : [];

  for (const entity of entities) {
    if (!entity || typeof entity !== 'object') continue;
    const entry = entity as Record<string, unknown>;
    if (entry.selected === false) continue;
    const type = typeof entry.type === 'string' && entry.type.trim() ? entry.type.trim() : 'TEXT';
    const text = typeof entry.text === 'string' && entry.text.trim() ? entry.text.trim() : t('history.unnamedContent');
    items.push({ id: String(entry.id ?? `entity-${items.length}`), label: type, value: text, meta: t('history.previewItemText') });
  }

  for (const box of boxes) {
    if (!box || typeof box !== 'object') continue;
    const entry = box as Record<string, unknown>;
    if (entry.selected === false) continue;
    const type = typeof entry.type === 'string' && entry.type.trim() ? entry.type.trim() : 'IMAGE';
    const text = typeof entry.text === 'string' && entry.text.trim() ? entry.text.trim() : t('history.previewImageRegion');
    const page = typeof entry.page === 'number' ? entry.page : 1;
    items.push({ id: String(entry.id ?? `box-${items.length}`), label: type, value: text, meta: t('history.previewItemPage').replace('{page}', String(page)) });
  }
  return items;
}

export async function blobUrlFromFileDownload(fileId: string, redacted: boolean, mime: string): Promise<string> {
  const url = fileApi.getDownloadUrl(fileId, redacted);
  const res = await fetch(url);
  if (!res.ok) throw new Error(redacted ? t('history.loadPreviewFailed.redacted') : t('history.loadPreviewFailed.original'));
  const buf = await res.arrayBuffer();
  return URL.createObjectURL(new Blob([buf], { type: mime }));
}

export function buildHistoryGroups(rows: FileListItem[], sourceTab: SourceTab): HistoryGroup[] {
  if (sourceTab === 'playground') {
    return rows.map(r => ({ kind: 'date_group' as const, label: t('history.singleSession').replace('{id}', r.file_id.slice(0, 8)), rows: [r] }));
  }
  const out: HistoryGroup[] = [];
  let i = 0;
  while (i < rows.length) {
    const r = rows[i];
    const bg = r.batch_group_id;
    if (!bg) {
      out.push({ kind: 'date_group', label: t('history.singleSession').replace('{id}', r.file_id.slice(0, 8)), rows: [r] });
      i++;
      continue;
    }
    const block: FileListItem[] = [r];
    let j = i + 1;
    while (j < rows.length && rows[j].batch_group_id === bg) { block.push(rows[j]); j++; }
    out.push({ kind: 'batch', batch_group_id: bg, batch_group_count: r.batch_group_count ?? block.length, rows: block });
    i = j;
  }
  return out;
}

/* Hook */

export function useHistory() {
  const [urlParams] = useState(() => new URLSearchParams(window.location.search));
  const urlSource = urlParams.get('source');
  const urlJobId = urlParams.get('jobId');

  const [rows, setRows] = useState<FileListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [initialLoading, setInitialLoading] = useState(true);
  const [tableLoading, setTableLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const firstLoadRef = useRef(true);
  const [zipLoading, setZipLoading] = useState(false);
  const [cleanupConfirmOpen, setCleanupConfirmOpen] = useState(false);
  const [sourceTab, setSourceTab] = useState<SourceTab>(
    urlSource === 'batch' ? 'batch' : urlSource === 'playground' ? 'playground' : 'all',
  );
  const [collapsedBatchIds, setCollapsedBatchIds] = useState<Set<string>>(() => new Set());
  const [msg, setMsg] = useState<{ text: string; tone: 'ok' | 'warn' | 'err' } | null>(null);
  const [dateFilter, setDateFilter] = useState<DateFilter>('all');
  const [fileTypeFilter, setFileTypeFilter] = useState<FileTypeFilter>('all');
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');

  /* Compare modal state */
  const [compareOpen, setCompareOpen] = useState(false);
  const [compareTarget, setCompareTarget] = useState<FileListItem | null>(null);
  const [compareLoading, setCompareLoading] = useState(false);
  const [compareErr, setCompareErr] = useState<string | null>(null);
  const [compareData, setCompareData] = useState<CompareData | null>(null);
  const [compareBlobUrls, setCompareBlobUrls] = useState<{ original: string; redacted: string } | null>(null);
  const [compareTab, setCompareTab] = useState<'preview' | 'text' | 'changes'>('preview');
  const [comparePreviewItems, setComparePreviewItems] = useState<HistoryPreviewItem[]>([]);

  /* Confirm dialog */
  const [confirmDlg, setConfirmDlg] = useState<{ title: string; message: string; onConfirm: () => void } | null>(null);

  /* Compare helpers */

  const revokeCompareBlobs = useCallback(() => {
    setCompareBlobUrls(prev => {
      if (prev) { URL.revokeObjectURL(prev.original); URL.revokeObjectURL(prev.redacted); }
      return null;
    });
  }, []);

  const closeCompareModal = useCallback(() => {
    revokeCompareBlobs();
    setCompareOpen(false);
    setCompareTarget(null);
    setCompareData(null);
    setCompareErr(null);
    setCompareLoading(false);
    setCompareTab('preview');
    setComparePreviewItems([]);
  }, [revokeCompareBlobs]);

  const openCompareModal = useCallback(async (row: FileListItem) => {
    revokeCompareBlobs();
    setCompareOpen(true);
    setCompareTarget(row);
    setCompareData(null);
    setCompareErr(null);
    setCompareLoading(true);
    setComparePreviewItems([]);
    const useBinaryPreview = isBinaryPreviewRow(row);
    setCompareTab(useBinaryPreview ? 'preview' : 'text');
    try {
      const [data, fileInfo] = await Promise.all([
        redactionApi.getComparison(row.file_id),
        fileApi.getInfo(row.file_id).catch(() => null),
      ]);
      setCompareData(data);
      setComparePreviewItems(normalizeHistoryPreviewItems(fileInfo as Record<string, unknown> | null));
      if (useBinaryPreview) {
        const mime = previewMimeForRow(row);
        const [original, redacted] = await Promise.all([
          blobUrlFromFileDownload(row.file_id, false, mime),
          blobUrlFromFileDownload(row.file_id, true, mime),
        ]);
        setCompareBlobUrls({ original, redacted });
      }
    } catch (e) {
      setCompareErr(localizeErrorMessage(e, 'history.compareFailed'));
    } finally {
      setCompareLoading(false);
    }
  }, [revokeCompareBlobs]);

  useEffect(() => {
    if (!compareOpen) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') closeCompareModal(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [compareOpen, closeCompareModal]);

  useEffect(() => () => revokeCompareBlobs(), [revokeCompareBlobs]);

  /* Data loading */

  const load = useCallback(
    async (isRefresh = false, targetPage?: number, targetSize?: number, targetSource?: SourceTab) => {
      const p = targetPage ?? page;
      const ps = targetSize ?? pageSize;
      const src = targetSource ?? sourceTab;
      if (isRefresh) setRefreshing(true);
      else if (firstLoadRef.current) setInitialLoading(true);
      else setTableLoading(true);
      setMsg(null);
      try {
        const source = src === 'all' ? undefined : src;
        const res = await fileApi.list(p, ps, { source, embed_job: src !== 'playground', job_id: urlJobId || undefined });
        setRows(res.files);
        setTotal(res.total);
        setPage(res.page);
        setPageSize(res.page_size);
        setSelected(new Set());
      } catch (e) {
        setMsg({ text: localizeErrorMessage(e, 'history.loadFailed'), tone: 'err' });
      } finally {
        firstLoadRef.current = false;
        setInitialLoading(false);
        setTableLoading(false);
        setRefreshing(false);
      }
    },
    [page, pageSize, sourceTab, urlJobId],
  );

  useEffect(() => {
    load(false, 1, pageSize);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /* Filter / page actions */

  const changeSourceTab = useCallback((tab: SourceTab) => {
    setSourceTab(tab);
    setPage(1);
    setCollapsedBatchIds(new Set());
    load(false, 1, pageSize, tab);
  }, [load, pageSize]);

  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  const goPage = useCallback((next: number) => {
    const clamped = Math.min(Math.max(1, next), totalPages);
    setPage(clamped);
    load(false, clamped, pageSize);
  }, [load, pageSize, totalPages]);

  const changePageSize = useCallback((ps: number) => {
    setPageSize(ps);
    setPage(1);
    load(false, 1, ps);
  }, [load]);

  const toggle = useCallback((id: string) => {
    setSelected(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }, []);

  const filteredRows = useMemo(() => {
    let result = rows;
    if (dateFilter !== 'all') {
      const now = Date.now();
      const days = dateFilter === '7d' ? 7 : 30;
      const cutoff = now - days * 24 * 60 * 60 * 1000;
      result = result.filter(r => r.created_at && new Date(r.created_at).getTime() >= cutoff);
    }
    if (fileTypeFilter !== 'all') {
      result = result.filter(r => {
        const ft = String(r.file_type).toLowerCase();
        if (fileTypeFilter === 'word') return ft === 'docx' || ft === 'doc';
        if (fileTypeFilter === 'pdf') return ft === 'pdf' || ft === 'pdf_scanned';
        if (fileTypeFilter === 'image') return ft === 'image';
        return true;
      });
    }
    if (statusFilter !== 'all') {
      result = result.filter(r => resolveRedactionState(r.has_output, r.item_status) === statusFilter);
    }
    return result;
  }, [rows, dateFilter, fileTypeFilter, statusFilter]);

  const selectedIds = filteredRows.filter(r => selected.has(r.file_id)).map(r => r.file_id);
  const historyGroups = useMemo(() => buildHistoryGroups(filteredRows, sourceTab), [filteredRows, sourceTab]);

  const statsData = useMemo(() => {
    const redactedFiles = rows.filter(r => r.has_output).length;
    const entitySum = rows.reduce((s, r) => s + (r.entity_count || 0), 0);
    const sizeSum = rows.reduce((s, r) => s + (r.file_size || 0), 0);
    let sizeLabel: string;
    if (sizeSum < 1024) sizeLabel = sizeSum + ' B';
    else if (sizeSum < 1024 * 1024) sizeLabel = (sizeSum / 1024).toFixed(1) + ' KB';
    else sizeLabel = (sizeSum / 1024 / 1024).toFixed(1) + ' MB';
    return { totalFiles: total, redactedFiles, entitySum, sizeLabel };
  }, [rows, total]);

  const hasActiveFilter = dateFilter !== 'all' || fileTypeFilter !== 'all' || statusFilter !== 'all';
  const clearFilters = useCallback(() => { setDateFilter('all'); setFileTypeFilter('all'); setStatusFilter('all'); }, []);
  const allSelected = filteredRows.length > 0 && selectedIds.length === filteredRows.length;

  /* Batch zip download */

  const downloadZipByIds = useCallback(async (ids: string[], redacted: boolean, filename: string) => {
    if (!ids.length) { setMsg({ text: t('history.noDownloadable'), tone: 'warn' }); return; }
    if (redacted) {
      const noOut = rows.filter(r => ids.includes(r.file_id) && !r.has_output);
      if (noOut.length) { setMsg({ text: t('history.hasUnredacted'), tone: 'warn' }); return; }
    }
    setZipLoading(true);
    try {
      const blob = await fileApi.batchDownloadZip(ids, redacted);
      triggerDownload(blob, filename);
      showToast(t('history.zipStarted'), 'success');
      setMsg({ text: t('history.zipStarted'), tone: 'ok' });
    } catch (e) {
      setMsg({ text: localizeErrorMessage(e, 'history.downloadFailed'), tone: 'err' });
    } finally { setZipLoading(false); }
  }, [rows]);

  const downloadZip = useCallback(async (redacted: boolean) => {
    if (!selectedIds.length) { setMsg({ text: t('history.selectFirst'), tone: 'warn' }); return; }
    await downloadZipByIds(selectedIds, redacted, redacted ? 'history_redacted.zip' : 'history_original.zip');
  }, [selectedIds, downloadZipByIds]);

  /* Tree collapse */

  const toggleBatchCollapse = useCallback((batchGroupId: string) => {
    setCollapsedBatchIds(prev => {
      const n = new Set(prev);
      if (n.has(batchGroupId)) n.delete(batchGroupId); else n.add(batchGroupId);
      return n;
    });
  }, []);

  /* Delete */

  const remove = useCallback((id: string) => {
    setConfirmDlg({
      title: t('history.deleteFileTitle'),
      message: t('history.deleteFileMsg'),
      onConfirm: async () => {
        setConfirmDlg(null);
        try {
          await fileApi.delete(id);
          await load(true, page, pageSize);
          setMsg({ text: t('history.deleted'), tone: 'ok' });
        } catch (e) { setMsg({ text: localizeErrorMessage(e, 'history.deleteFailed'), tone: 'err' }); }
      },
    });
  }, [load, page, pageSize]);

  const removeGroup = useCallback((fileIds: string[]) => {
    if (!fileIds.length) return;
    setConfirmDlg({
      title: t('history.deleteGroup'),
      message: t('history.deleteGroupMsg').replace('{n}', String(fileIds.length)),
      onConfirm: async () => {
        setConfirmDlg(null);
        try {
          for (const id of fileIds) await fileApi.delete(id);
          await load(true, page, pageSize);
          setMsg({ text: t('history.deletedGroup').replace('{n}', String(fileIds.length)), tone: 'ok' });
        } catch (e) { setMsg({ text: localizeErrorMessage(e, 'history.deleteFailed'), tone: 'err' }); }
      },
    });
  }, [load, page, pageSize]);

  /* Cleanup */

  const handleCleanup = useCallback(async () => {
    setCleanupConfirmOpen(false);
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
      load(true, 1, pageSize);
    } catch {
      showToast(t('safety.cleanup.failed'), 'error');
    }
  }, [load, pageSize]);

  return {
    /* list data */
    rows, filteredRows, total, page, pageSize, totalPages, historyGroups, statsData,
    /* loading */
    initialLoading, tableLoading, refreshing, zipLoading,
    /* selection */
    selected, setSelected, selectedIds, allSelected, toggle,
    /* filters */
    sourceTab, changeSourceTab, dateFilter, setDateFilter, fileTypeFilter, setFileTypeFilter,
    statusFilter, setStatusFilter, hasActiveFilter, clearFilters,
    /* pagination */
    goPage, changePageSize,
    /* actions */
    load, downloadZip, remove, removeGroup, toggleBatchCollapse, collapsedBatchIds,
    /* cleanup */
    cleanupConfirmOpen, setCleanupConfirmOpen, handleCleanup,
    /* messages */
    msg,
    /* compare */
    compareOpen, compareTarget, compareLoading, compareErr, compareData,
    compareBlobUrls, compareTab, setCompareTab, comparePreviewItems,
    openCompareModal, closeCompareModal,
    /* confirm dialog */
    confirmDlg, setConfirmDlg,
  };
}
