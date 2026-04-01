import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { t } from '../i18n';
import { fileApi, redactionApi } from '../services/api';
import { ConfirmDialog } from '../components/ConfirmDialog';
import { EmptyState } from '../components/EmptyState';
import { showToast } from '../components/Toast';
import type { CompareData, FileListItem } from '../types';
import { formCheckboxClass } from '../ui/selectionClasses';
import { resolveRedactionState, REDACTION_STATE_LABEL, REDACTION_STATE_CLASS, BADGE_BASE } from '../utils/redactionState';

function triggerDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function previewMimeForRow(row: FileListItem): string {
  const ft = String(row.file_type);
  if (ft === 'pdf' || ft === 'pdf_scanned') return 'application/pdf';
  const name = row.original_filename.toLowerCase();
  if (name.endsWith('.png')) return 'image/png';
  if (name.endsWith('.webp')) return 'image/webp';
  if (name.endsWith('.gif')) return 'image/gif';
  if (name.endsWith('.bmp')) return 'image/bmp';
  return 'image/jpeg';
}

function isBinaryPreviewRow(row: FileListItem | null): boolean {
  if (!row) return false;
  const ft = String(row.file_type);
  return ft === 'image' || ft === 'pdf' || ft === 'pdf_scanned';
}

type HistoryPreviewItem = {
  id: string;
  label: string;
  value: string;
  meta: string;
};

function normalizeHistoryPreviewItems(fileInfo: Record<string, unknown> | null): HistoryPreviewItem[] {
  if (!fileInfo) return [];

  const items: HistoryPreviewItem[] = [];
  const entities = Array.isArray(fileInfo.entities) ? fileInfo.entities : [];
  const rawBoxes = fileInfo.bounding_boxes;
  const boxes = Array.isArray(rawBoxes)
    ? rawBoxes
    : rawBoxes && typeof rawBoxes === 'object'
      ? Object.values(rawBoxes).flatMap(value => (Array.isArray(value) ? value : []))
      : [];

  for (const entity of entities) {
    if (!entity || typeof entity !== 'object') continue;
    const entry = entity as Record<string, unknown>;
    if (entry.selected === false) continue;
    const type = typeof entry.type === 'string' && entry.type.trim() ? entry.type.trim() : 'TEXT';
    const text = typeof entry.text === 'string' && entry.text.trim() ? entry.text.trim() : '未命名内容';
    items.push({
      id: String(entry.id ?? `entity-${items.length}`),
      label: type,
      value: text,
      meta: t('history.previewItemText'),
    });
  }

  for (const box of boxes) {
    if (!box || typeof box !== 'object') continue;
    const entry = box as Record<string, unknown>;
    if (entry.selected === false) continue;
    const type = typeof entry.type === 'string' && entry.type.trim() ? entry.type.trim() : 'IMAGE';
    const text = typeof entry.text === 'string' && entry.text.trim() ? entry.text.trim() : t('history.previewImageRegion');
    const page = typeof entry.page === 'number' ? entry.page : 1;
    items.push({
      id: String(entry.id ?? `box-${items.length}`),
      label: type,
      value: text,
      meta: t('history.previewItemPage').replace('{page}', String(page)),
    });
  }

  return items;
}

async function blobUrlFromFileDownload(fileId: string, redacted: boolean, mime: string): Promise<string> {
  const url = fileApi.getDownloadUrl(fileId, redacted);
  const res = await fetch(url);
  if (!res.ok) throw new Error(redacted ? t('history.loadPreviewFailed.redacted') : t('history.loadPreviewFailed.original'));
  const buf = await res.arrayBuffer();
  return URL.createObjectURL(new Blob([buf], { type: mime }));
}

const PAGE_SIZE_OPTIONS = [10, 20, 50, 100] as const;

type SourceTab = 'all' | 'playground' | 'batch';

type HistoryGroup =
  | { kind: 'standalone'; row: FileListItem }
  | { kind: 'batch'; batch_group_id: string; batch_group_count: number; rows: FileListItem[] }
  | { kind: 'date_group'; label: string; rows: FileListItem[] };

/** 将当前页行按 batch_group_id 合并为树节点（后端已保证同批相邻） */
function buildHistoryGroups(rows: FileListItem[], sourceTab: SourceTab): HistoryGroup[] {
  // Playground 模式：每条记录独立成树节点，头部 "单次 · {ID}"
  if (sourceTab === 'playground') {
    return rows.map(r => ({
      kind: 'date_group' as const,
      label: t('history.singleSession').replace('{id}', r.file_id.slice(0, 8)),
      rows: [r],
    }));
  }
  // 批量模式 & 全部模式：按 batch_group_id 分组
  const out: HistoryGroup[] = [];
  let i = 0;
  while (i < rows.length) {
    const r = rows[i];
    const bg = r.batch_group_id;
    if (!bg) {
      // playground 单条也用树节点展示
      out.push({
        kind: 'date_group',
        label: t('history.singleSession').replace('{id}', r.file_id.slice(0, 8)),
        rows: [r],
      });
      i++;
      continue;
    }
    const block: FileListItem[] = [r];
    let j = i + 1;
    while (j < rows.length && rows[j].batch_group_id === bg) {
      block.push(rows[j]);
      j++;
    }
    out.push({
      kind: 'batch',
      batch_group_id: bg,
      batch_group_count: r.batch_group_count ?? block.length,
      rows: block,
    });
    i = j;
  }
  return out;
}

export const History: React.FC = () => {
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
  /** 来源 Tab：全部 / Playground / 批量 */
  const [sourceTab, setSourceTab] = useState<SourceTab>(
    urlSource === 'batch' ? 'batch' : urlSource === 'playground' ? 'playground' : 'all'
  );
  /** 折叠的批量节点（batch_group_id）或日期分组 */
  const [collapsedBatchIds, setCollapsedBatchIds] = useState<Set<string>>(() => new Set());
  const [msg, setMsg] = useState<{ text: string; tone: 'ok' | 'warn' | 'err' } | null>(null);

  const [dateFilter, setDateFilter] = useState<'all' | '7d' | '30d'>('all');
  const [fileTypeFilter, setFileTypeFilter] = useState<'all' | 'word' | 'pdf' | 'image'>('all');
  const [statusFilter, setStatusFilter] = useState<'all' | 'redacted' | 'awaiting_review' | 'unredacted'>('all');

  const [compareOpen, setCompareOpen] = useState(false);
  const [compareTarget, setCompareTarget] = useState<FileListItem | null>(null);
  const [compareLoading, setCompareLoading] = useState(false);
  const [compareErr, setCompareErr] = useState<string | null>(null);
  const [compareData, setCompareData] = useState<CompareData | null>(null);
  const [compareBlobUrls, setCompareBlobUrls] = useState<{ original: string; redacted: string } | null>(null);
  const [compareTab, setCompareTab] = useState<'preview' | 'text' | 'changes'>('preview');
  const [comparePreviewItems, setComparePreviewItems] = useState<HistoryPreviewItem[]>([]);
  const [moreMenuId, setMoreMenuId] = useState<string | null>(null);
  const [confirmDlg, setConfirmDlg] = useState<{
    title: string; message: string; onConfirm: () => void;
  } | null>(null);

  const revokeCompareBlobs = useCallback(() => {
    setCompareBlobUrls(prev => {
      if (prev) {
        URL.revokeObjectURL(prev.original);
        URL.revokeObjectURL(prev.redacted);
      }
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

  const openCompareModal = useCallback(
    async (row: FileListItem) => {
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
        setCompareErr(e instanceof Error ? e.message : t('history.compareFailed'));
      } finally {
        setCompareLoading(false);
      }
    },
    [revokeCompareBlobs]
  );

  useEffect(() => {
    if (!compareOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') closeCompareModal();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [compareOpen, closeCompareModal]);

  useEffect(() => () => revokeCompareBlobs(), [revokeCompareBlobs]);

  useEffect(() => {
    if (!moreMenuId) return;
    const onClick = (e: MouseEvent) => {
      const target = e.target as HTMLElement;
      // 点击在菜单容器（含按钮）内的不关闭
      if (target.closest?.(`[data-menu-for="${moreMenuId}"]`)) return;
      setMoreMenuId(null);
    };
    document.addEventListener('mousedown', onClick);
    return () => document.removeEventListener('mousedown', onClick);
  }, [moreMenuId]);


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
        setMsg({ text: e instanceof Error ? e.message : t('history.loadFailed'), tone: 'err' });
      } finally {
        firstLoadRef.current = false;
        setInitialLoading(false);
        setTableLoading(false);
        setRefreshing(false);
      }
    },
    [page, pageSize, sourceTab]
  );

  useEffect(() => {
    load(false, 1, pageSize);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 仅挂载时拉第一页
  }, []);

  const changeSourceTab = (tab: SourceTab) => {
    setSourceTab(tab);
    setPage(1);
    setCollapsedBatchIds(new Set());
    load(false, 1, pageSize, tab);
  };

  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  const goPage = (next: number) => {
    const clamped = Math.min(Math.max(1, next), totalPages);
    setPage(clamped);
    load(false, clamped, pageSize);
  };

  const changePageSize = (ps: number) => {
    setPageSize(ps);
    setPage(1);
    load(false, 1, ps);
  };

  const toggle = (id: string) => {
    setSelected(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

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
    // rows 是当前页数据，total 是后端全量总数
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

  const clearFilters = () => {
    setDateFilter('all');
    setFileTypeFilter('all');
    setStatusFilter('all');
  };

  const downloadZipByIds = async (ids: string[], redacted: boolean, filename: string) => {
    if (!ids.length) {
      setMsg({ text: t('history.noDownloadable'), tone: 'warn' });
      return;
    }
    if (redacted) {
      const noOut = rows.filter(r => ids.includes(r.file_id) && !r.has_output);
      if (noOut.length) {
        setMsg({ text: t('history.hasUnredacted'), tone: 'warn' });
        return;
      }
    }
    setZipLoading(true);
    try {
      const blob = await fileApi.batchDownloadZip(ids, redacted);
      triggerDownload(blob, filename);
      showToast(t('history.zipStarted'), 'success');
      setMsg({ text: t('history.zipStarted'), tone: 'ok' });
    } catch (e) {
      setMsg({ text: e instanceof Error ? e.message : t('history.downloadFailed'), tone: 'err' });
    } finally {
      setZipLoading(false);
    }
  };

  const downloadZip = async (redacted: boolean) => {
    if (!selectedIds.length) {
      setMsg({ text: t('history.selectFirst'), tone: 'warn' });
      return;
    }
    await downloadZipByIds(
      selectedIds,
      redacted,
      redacted ? 'history_redacted.zip' : 'history_original.zip'
    );
  };

  const toggleBatchCollapse = (batchGroupId: string) => {
    setCollapsedBatchIds(prev => {
      const n = new Set(prev);
      if (n.has(batchGroupId)) n.delete(batchGroupId);
      else n.add(batchGroupId);
      return n;
    });
  };

  const remove = (id: string) => {
    setConfirmDlg({
      title: t('history.deleteFileTitle'),
      message: t('history.deleteFileMsg'),
      onConfirm: async () => {
        setConfirmDlg(null);
        try {
          await fileApi.delete(id);
          await load(true, page, pageSize);
          setMsg({ text: t('history.deleted'), tone: 'ok' });
        } catch (e) {
          setMsg({ text: e instanceof Error ? e.message : t('history.deleteFailed'), tone: 'err' });
        }
      },
    });
  };

  const removeGroup = (fileIds: string[]) => {
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
        } catch (e) {
          setMsg({ text: e instanceof Error ? e.message : t('history.deleteFailed'), tone: 'err' });
        }
      },
    });
  };

  const msgClass =
    msg?.tone === 'ok'
      ? 'bg-green-50 text-green-800 border border-green-100'
      : msg?.tone === 'warn'
        ? 'bg-amber-50 text-amber-900 border border-amber-100'
        : 'bg-red-50 text-red-800 border border-red-100';

  const allSelected = filteredRows.length > 0 && selectedIds.length === filteredRows.length;
  const isBinaryCompare = isBinaryPreviewRow(compareTarget);

  return (
    <div className="flex-1 min-h-0 min-w-0 flex flex-col bg-[#f5f5f7] dark:bg-gray-900 overflow-hidden">
      <div className="flex-1 flex flex-col min-h-0 min-w-0 px-3 py-3 sm:px-5 sm:py-4 w-full max-w-[min(100%,1920px)] mx-auto items-stretch">
        <p className="text-caption text-gray-500 dark:text-gray-400 mb-3 flex-shrink-0 leading-snug">
          {t('history.description')}
        </p>

        {/* 筛选栏：来源 Tab + 日期 + 类型 + 状态 — 合并为一行 */}
        <div className="flex flex-wrap items-center gap-2 mb-3 flex-shrink-0">
          {/* 来源 Tab */}
          <div className="flex items-center gap-0.5 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-0.5">
            {([['all', t('history.tab.all')], ['playground', 'Playground'], ['batch', t('history.tab.batch')]] as [string, string][]).map(([val, label]) => (
              <button
                key={val}
                type="button"
                onClick={() => changeSourceTab(val as SourceTab)}
                className={`px-2.5 py-1 text-xs font-medium rounded-md transition-colors ${
                  sourceTab === val ? 'bg-[#0a0a0a] text-white' : 'text-gray-600 hover:bg-gray-100 dark:hover:bg-gray-700'
                }`}
              >
                {label}
              </button>
            ))}
          </div>
          <span className="w-px h-5 bg-gray-200 dark:bg-gray-700" />
          {/* 日期筛选 */}
          <div className="flex items-center gap-0.5 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-0.5">
            {([['all', t('history.filter.all')], ['7d', t('history.filter.last7d')], ['30d', t('history.filter.last30d')]] as [string, string][]).map(([val, label]) => (
              <button
                key={val}
                type="button"
                onClick={() => setDateFilter(val as 'all' | '7d' | '30d')}
                className={`px-2.5 py-1 text-xs rounded-md transition-colors ${
                  dateFilter === val ? 'bg-[#0a0a0a] text-white' : 'text-gray-600 hover:bg-gray-100 dark:hover:bg-gray-700'
                }`}
              >
                {label}
              </button>
            ))}
          </div>
          <select
            value={fileTypeFilter}
            onChange={e => setFileTypeFilter(e.target.value as typeof fileTypeFilter)}
            className="border border-gray-200 dark:border-gray-600 rounded-lg px-2.5 py-1.5 bg-white dark:bg-gray-800 text-xs text-gray-700 dark:text-gray-300"
          >
            <option value="all">{t('history.filter.allTypes')}</option>
            <option value="word">Word</option>
            <option value="pdf">PDF</option>
            <option value="image">{t('history.filter.image')}</option>
          </select>
          <select
            value={statusFilter}
            onChange={e => setStatusFilter(e.target.value as typeof statusFilter)}
            className="border border-gray-200 dark:border-gray-600 rounded-lg px-2.5 py-1.5 bg-white dark:bg-gray-800 text-xs text-gray-700 dark:text-gray-300"
          >
            <option value="all">{t('history.filter.allStatus')}</option>
            <option value="redacted">{t('history.filter.redacted')}</option>
            <option value="awaiting_review">{t('job.status.awaiting_review')}</option>
            <option value="unredacted">{t('history.filter.unredacted')}</option>
          </select>
          {hasActiveFilter && (
            <button
              type="button"
              onClick={clearFilters}
              className="px-2.5 py-1.5 text-xs text-gray-500 hover:text-gray-700 hover:bg-gray-100 rounded-lg transition-colors"
            >
              {t('history.clearFilter')}
            </button>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-2 mb-3 flex-shrink-0">
          <button
            type="button"
            onClick={() => load(true, page, pageSize)}
            disabled={refreshing || initialLoading || tableLoading}
            className="inline-flex items-center gap-1.5 px-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-800 hover:bg-gray-50 dark:hover:bg-gray-700 disabled:opacity-50 transition-colors"
          >
            <svg
              className={`w-3.5 h-3.5 ${refreshing ? 'animate-spin' : ''}`}
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
              />
            </svg>
            {t('history.refresh')}
          </button>
          <button
            type="button"
            onClick={async () => {
              if (!window.confirm('确定要清空所有处理记录、上传文件和脱敏产物吗？此操作不可撤销。')) return;
              try {
                const res = await fetch('/api/v1/safety/cleanup', { method: 'POST' });
                if (!res.ok) throw new Error('清空失败');
                const data = await res.json();
                showToast(`已清空 ${data.files_removed} 个文件和 ${data.jobs_removed} 条任务`, 'success');
                load(true, 1, pageSize);
              } catch { showToast('清空失败', 'error'); }
            }}
            className="inline-flex items-center gap-1.5 px-3 py-2 text-sm rounded-lg border border-red-200 text-red-600 bg-white hover:bg-red-50 transition-colors"
          >
            一键清空
          </button>
          <button
            type="button"
            onClick={() => downloadZip(false)}
            disabled={zipLoading || !selectedIds.length || initialLoading || tableLoading}
            className="inline-flex items-center gap-1.5 px-4 py-2 text-sm font-medium rounded-lg bg-[#0a0a0a] text-white hover:bg-[#262626] disabled:opacity-40 transition-colors"
          >
            {zipLoading && (
              <svg className="w-3.5 h-3.5 animate-spin" viewBox="0 0 24 24" fill="none">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
            )}
            {zipLoading ? t('history.packing') : t('history.downloadOriginalZip')}
          </button>
          <button
            type="button"
            onClick={() => downloadZip(true)}
            disabled={zipLoading || !selectedIds.length || initialLoading || tableLoading}
            className="inline-flex items-center gap-1.5 px-4 py-2 text-sm font-medium rounded-lg border border-gray-200 bg-white text-[#0a0a0a] hover:bg-gray-50 disabled:opacity-40 transition-colors"
          >
            {zipLoading && (
              <svg className="w-3.5 h-3.5 animate-spin" viewBox="0 0 24 24" fill="none">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
            )}
            {zipLoading ? t('history.packing') : t('history.downloadRedactedZip')}
          </button>
          <div className="ml-auto flex items-center gap-2 text-xs text-[#737373]">
            <span>{t('history.perPage')}</span>
            <select
              value={pageSize}
              onChange={e => changePageSize(Number(e.target.value))}
              className="border border-gray-200 rounded-lg px-2 py-1.5 bg-white text-[#0a0a0a] text-xs"
            >
              {PAGE_SIZE_OPTIONS.map(n => (
                <option key={n} value={n}>
                  {n} {t('history.itemsUnit')}
                </option>
              ))}
            </select>
          </div>
        </div>

        {msg && (
          <div className={`text-sm rounded-lg px-4 py-3 mb-4 flex-shrink-0 ${msgClass}`}>{msg.text}</div>
        )}

        {/* Statistics cards */}
        <div className="grid grid-cols-4 gap-3 mb-3 flex-shrink-0">
          <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 px-3 py-2.5 shadow-sm dark:shadow-gray-900/30">
            <p className="text-xs text-gray-500">{t('history.totalFiles')}</p>
            <p className="text-lg font-semibold text-gray-900 dark:text-gray-100 mt-0.5">{statsData.totalFiles}</p>
          </div>
          <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 px-3 py-2.5 shadow-sm dark:shadow-gray-900/30">
            <p className="text-xs text-gray-500">{t('history.redactedFiles')}</p>
            <p className="text-lg font-semibold text-emerald-700 mt-0.5">{statsData.redactedFiles}</p>
          </div>
          <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 px-3 py-2.5 shadow-sm dark:shadow-gray-900/30">
            <p className="text-xs text-gray-500">{t('history.recognizedEntities')}</p>
            <p className="text-lg font-semibold text-gray-900 dark:text-gray-100 mt-0.5">{statsData.entitySum}</p>
          </div>
          <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 px-3 py-2.5 shadow-sm dark:shadow-gray-900/30">
            <p className="text-xs text-gray-500">{t('history.storageUsed')}</p>
            <p className="text-lg font-semibold text-gray-900 dark:text-gray-100 mt-0.5">{statsData.sizeLabel}</p>
          </div>
        </div>

        <div className="w-full flex flex-col flex-1 min-h-0 bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 shadow-sm dark:shadow-gray-900/30 overflow-hidden overflow-x-auto">
          <div className="px-4 py-2.5 border-b border-gray-100 flex flex-wrap items-center justify-between gap-2 flex-shrink-0">
            <div>
              <h3 className="font-semibold text-gray-900 dark:text-gray-100 text-sm">{t('history.fileRecords')}</h3>
              <p className="text-xs text-gray-400 mt-0.5">
                {t('history.totalAndPage').replace('{total}', String(total)).replace('{page}', String(page)).replace('{totalPages}', String(totalPages))}
              </p>
            </div>
            {filteredRows.length > 0 && (
              <label className="flex items-center gap-2 text-xs text-gray-600 cursor-pointer select-none">
                <input
                  type="checkbox"
                  className={formCheckboxClass('md')}
                  checked={allSelected}
                  onChange={e => {
                    if (e.target.checked) setSelected(new Set(filteredRows.map(r => r.file_id)));
                    else setSelected(new Set());
                  }}
                />
                {t('history.selectAll')}
              </label>
            )}
          </div>

          {/* 表头 — 列宽与行内对齐 */}
          <div className="history-head px-3 sm:px-4 py-1.5 border-b border-gray-200 dark:border-gray-700 bg-[#fafafa] dark:bg-gray-900 text-2xs font-medium text-gray-500 dark:text-gray-400 flex-shrink-0">
            <span />
            <span />
            <span>{t('history.col.filename')}</span>
            <span className="hidden sm:block text-right">{t('history.col.time')}</span>
            <span className="hidden sm:block text-right">{t('history.col.entities')}</span>
            <span className="text-center">{t('history.col.status')}</span>
            <span />
            <span />
          </div>

          <div className="relative flex-1 min-h-0 overflow-y-auto flex flex-col">
            {tableLoading && rows.length > 0 && (
              <div className="absolute inset-0 bg-white/60 dark:bg-gray-800/60 flex items-center justify-center z-10 backdrop-blur-[1px]">
                <div className="w-7 h-7 border-2 border-[#e5e5e5] border-t-[#1d1d1f] rounded-full animate-spin" />
              </div>
            )}
            {initialLoading && rows.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-20 gap-3">
                <div className="w-7 h-7 border-2 border-[#e5e5e5] border-t-[#1d1d1f] rounded-full animate-spin" />
                <p className="text-sm text-gray-400">{t('history.loading')}</p>
              </div>
            ) : rows.length === 0 ? (
              <EmptyState title={t('emptyState.history')} description={t('emptyState.historyDesc')} />
            ) : (
              <ul className="w-full flex flex-col divide-y divide-gray-100 dark:divide-gray-700 animate-fadeIn">
                {historyGroups.map((g, gi) => {
                  const stripe = gi % 2 === 1 ? 'bg-gray-50/50' : '';

                  /* ---------- 单行文件渲染（standalone / 分组子行共用） ---------- */
                  const renderFileRow = (r: FileListItem, indent: boolean) => (
                    <li
                      key={r.file_id}
                      className={`history-row px-3 sm:px-4 py-2 min-h-[2.75rem] transition-all duration-150 ${indent ? 'history-row-child border-t border-gray-50' : ''} ${
                        selected.has(r.file_id) ? '!bg-[#007AFF]/[0.06]' : 'hover:bg-gray-50/80'
                      }`}
                    >
                      {/* 箭头列（w-5 对齐表头） — 子行显示树线 */}
                      <span className="history-tree-cell flex items-center justify-center text-gray-300 text-xs select-none">
                        {indent ? '└' : ''}
                      </span>
                      <span className="flex items-center justify-center">
                        <input
                          type="checkbox"
                          className={formCheckboxClass('md')}
                          checked={selected.has(r.file_id)}
                          onChange={() => toggle(r.file_id)}
                          aria-label={t('history.selectFile').replace('{name}', r.original_filename)}
                        />
                      </span>
                      <p className={`min-w-0 text-sm text-gray-900 dark:text-gray-100 truncate ${indent ? 'pl-5' : 'pl-1'}`} title={r.original_filename}>
                        {r.original_filename}
                      </p>
                      <span className="hidden sm:block text-right text-2xs text-gray-400 tabular-nums whitespace-nowrap">
                        {r.created_at ? new Date(r.created_at).toLocaleString() : '—'}
                      </span>
                      <span className="hidden sm:block text-right text-2xs text-gray-400 tabular-nums">
                        {r.entity_count}
                      </span>
                      <span className={`${BADGE_BASE} justify-center ${REDACTION_STATE_CLASS[resolveRedactionState(r.has_output, r.item_status)]}`}>
                        {REDACTION_STATE_LABEL[resolveRedactionState(r.has_output, r.item_status)]}
                      </span>
                      {/* 操作区 */}
                      <span className="history-action-cell">
                        {r.has_output ? (
                          <button
                            type="button"
                            title={t('history.viewCompareTitle')}
                            aria-label={t('history.viewCompareTitle')}
                            onClick={() => openCompareModal(r)}
                            className="inline-flex h-7 w-7 items-center justify-center rounded-full border border-gray-200 bg-white text-gray-500 hover:text-gray-800 hover:border-gray-300 hover:bg-gray-50 transition-colors"
                          >
                            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M2.036 12.322a1.012 1.012 0 010-.639C3.423 7.51 7.36 4.5 12 4.5c4.638 0 8.573 3.007 9.963 7.178.07.207.07.431 0 .639C20.577 16.49 16.64 19.5 12 19.5c-4.638 0-8.573-3.007-9.963-7.178z" />
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                            </svg>
                          </button>
                        ) : resolveRedactionState(r.has_output, r.item_status) === 'awaiting_review' && r.item_id && r.job_id ? (
                          <Link to={`/batch/smart?jobId=${encodeURIComponent(r.job_id)}&itemId=${encodeURIComponent(r.item_id)}&step=4`}
                            className="text-2xs text-[#007AFF] font-medium hover:underline whitespace-nowrap">
                            {t('history.goReview')}
                          </Link>
                        ) : null}
                      </span>
                      {/* 竖三点 */}
                      <div className="relative flex items-center justify-center" data-menu-for={r.file_id}>
                        <button type="button" title={t('history.moreActions')}
                          onClick={(e) => { e.stopPropagation(); setMoreMenuId(prev => (prev === r.file_id ? null : r.file_id)); }}
                          className="p-1 rounded-md text-gray-400 hover:text-gray-700 hover:bg-gray-100 transition-colors">
                          <svg className="w-3.5 h-3.5" viewBox="0 0 16 16" fill="currentColor">
                            <circle cx="8" cy="3" r="1.5" /><circle cx="8" cy="8" r="1.5" /><circle cx="8" cy="13" r="1.5" />
                          </svg>
                        </button>
                        {moreMenuId === r.file_id && (
                          <div className="absolute right-0 top-full mt-1 z-30 min-w-[120px] rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 shadow-xl py-1 text-xs animate-fadeIn">
                            <button type="button"
                              className="w-full text-left px-3 py-2 hover:bg-gray-50 dark:hover:bg-gray-700 text-gray-700 dark:text-gray-200 transition-colors"
                              onClick={(e) => { e.stopPropagation(); setMoreMenuId(null); openCompareModal(r); }}>
                              对比预览
                            </button>
                            <button type="button"
                              className="w-full text-left px-3 py-2 hover:bg-red-50 dark:hover:bg-red-900/20 text-red-600 transition-colors"
                              onClick={(e) => { e.stopPropagation(); setMoreMenuId(null); remove(r.file_id); }}>
                              {t('history.deleteText')}
                            </button>
                          </div>
                        )}
                      </div>
                    </li>
                  );

                  /* ---------- standalone ---------- */
                  if (g.kind === 'standalone') {
                    return <React.Fragment key={g.row.file_id}>{renderFileRow(g.row, false)}</React.Fragment>;
                  }

                  /* ---------- 分组头（date_group / batch 统一样式） ---------- */
                  const groupRows = g.rows;
                  const ids = groupRows.map(x => x.file_id);
                  const allInGroup = ids.length > 0 && ids.every(id => selected.has(id));
                  const singlePrefix = t('history.singleSession').split('{id}')[0];
                  const isPlaygroundTree = g.kind === 'date_group' && groupRows.length === 1 && g.label.startsWith(singlePrefix);
                  const groupKey = g.kind === 'date_group'
                    ? (isPlaygroundTree ? `pg:${groupRows[0].file_id}` : `date:${g.label}`)
                    : `batch:${g.batch_group_id}`;
                  const collapsed = collapsedBatchIds.has(groupKey);
                  const groupLabel = isPlaygroundTree
                    ? g.label
                    : g.kind === 'date_group'
                      ? g.label
                      : t('history.batchLabel').replace('{id}', g.batch_group_id);
                  const groupEntitySum = groupRows.reduce((s, r) => s + (r.entity_count || 0), 0);
                  /* 批量组：文件计数摘要 */
                  const batchCountText = g.kind === 'batch'
                    ? (g.rows.length < g.batch_group_count
                        ? t('history.thisPage').replace('{n}', String(g.rows.length)).replace('{total}', String(g.batch_group_count))
                        : t('history.filesCount').replace('{n}', String(groupRows.length)))
                    : '';
                  /* 最近时间：取组内最新 created_at */
                  const groupLatestTime = isPlaygroundTree
                    ? (groupRows[0].created_at ? new Date(groupRows[0].created_at).toLocaleString() : '—')
                    : (() => {
                        const ts = groupRows.map(r => r.created_at ? new Date(r.created_at).getTime() : 0).filter(Boolean);
                        return ts.length ? new Date(Math.max(...ts)).toLocaleString() : '—';
                      })();
                  /* playground 单条：脱敏状态 */
                  const groupHasOutput = isPlaygroundTree
                    ? groupRows[0].has_output
                    : groupRows.every(r => r.has_output);
                  const groupAllUnredacted = !isPlaygroundTree && groupRows.every(r => !r.has_output);

                  return (
                    <li key={groupKey} className={stripe}>
                      <div className="history-batch-row px-3 sm:px-4 py-1.5 min-h-[2.75rem] bg-[#fafafa] dark:bg-gray-900/90">
                        {/* 箭头列 — w-5 对齐表头 */}
                        <span className="flex items-center justify-center">
                          <button
                            type="button"
                            onClick={() => toggleBatchCollapse(groupKey)}
                            className="p-0.5 rounded text-gray-500 hover:bg-gray-200/80"
                            aria-expanded={!collapsed}
                          >
                            <svg
                              className={`w-4 h-4 transition-transform ${collapsed ? '' : 'rotate-90'}`}
                              fill="none" stroke="currentColor" viewBox="0 0 24 24"
                            >
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                            </svg>
                          </button>
                        </span>
                        {/* checkbox 列 — w-5 对齐表头 */}
                        <span className="flex items-center justify-center">
                          <input
                            type="checkbox"
                            className={formCheckboxClass('md')}
                            checked={allInGroup}
                            onChange={() => {
                              setSelected(prev => {
                                const next = new Set(prev);
                                if (allInGroup) ids.forEach(id => next.delete(id));
                                else ids.forEach(id => next.add(id));
                                return next;
                              });
                            }}
                            aria-label={t('history.selectAllGroup')}
                          />
                        </span>
                        {/* 文件名列 — flex-1 对齐表头 */}
                        <p className="min-w-0 pl-1 truncate">
                          <span className={`text-sm ${isPlaygroundTree ? 'font-bold' : 'font-semibold'} text-gray-900`}>
                            {groupLabel}
                          </span>
                          {isPlaygroundTree ? (
                            <span className="ml-2 text-xs font-normal text-gray-400 truncate">{groupRows[0].original_filename}</span>
                          ) : (
                            <span className="ml-1.5 text-xs font-normal text-gray-500">{batchCountText}</span>
                          )}
                        </p>
                        {/* 时间列 — w-[130px] 对齐表头 */}
                        <span className="hidden sm:block text-right text-2xs text-gray-400 tabular-nums whitespace-nowrap">
                          {groupLatestTime}
                        </span>
                        {/* 识别项列 — w-[56px] 对齐表头 */}
                        <span className="hidden sm:block text-right text-2xs text-gray-500 tabular-nums font-medium">
                          {groupEntitySum}
                        </span>
                        {/* 状态列 — w-[52px] 对齐表头 */}
                        <span className={`${BADGE_BASE} justify-center ${
                          isPlaygroundTree
                            ? (groupHasOutput ? REDACTION_STATE_CLASS.redacted : REDACTION_STATE_CLASS.unredacted)
                            : groupHasOutput
                              ? REDACTION_STATE_CLASS.redacted
                              : groupAllUnredacted
                                ? REDACTION_STATE_CLASS.unredacted
                                : REDACTION_STATE_CLASS.awaiting_review
                        }`}>
                          {isPlaygroundTree
                            ? (groupHasOutput ? t('history.redacted') : t('history.unredactedStatus'))
                            : groupHasOutput
                              ? t('history.allRedacted')
                              : groupAllUnredacted
                                ? t('history.unredactedStatus')
                                : t('history.partiallyRedacted')}
                        </span>
                        {/* 眼睛占位列 — w-[26px] 对齐表头 */}
                        {/* 更多操作列 — w-[26px] 对齐表头 */}
                        <span />
                        <div className="history-action-cell relative" data-menu-for={groupKey}>
                          <button
                            type="button"
                            title={t('history.moreActions')}
                            onClick={(e) => { e.stopPropagation(); setMoreMenuId(prev => (prev === groupKey ? null : groupKey)); }}
                            className="p-1 rounded-md text-gray-400 hover:text-gray-700 hover:bg-gray-200/80 transition-colors"
                          >
                            <svg className="w-3.5 h-3.5" viewBox="0 0 16 16" fill="currentColor">
                              <circle cx="8" cy="3" r="1.5" />
                              <circle cx="8" cy="8" r="1.5" />
                              <circle cx="8" cy="13" r="1.5" />
                            </svg>
                          </button>
                          {moreMenuId === groupKey && (
                            <div className="absolute right-0 top-full mt-1 z-30 min-w-[120px] rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 shadow-xl py-1 text-xs animate-fadeIn">
                              <button
                                type="button"
                                className="w-full text-left px-3 py-2 hover:bg-red-50 dark:hover:bg-red-900/20 text-red-600 transition-colors"
                                onClick={(e) => { e.stopPropagation(); setMoreMenuId(null); removeGroup(ids); }}
                              >
                                {t('history.deleteGroupBtn')}
                              </button>
                            </div>
                          )}
                        </div>
                      </div>
                      {!collapsed && (
                        <ul className="history-tree-children border-t border-gray-100">
                          {groupRows.map(r => renderFileRow(r, true))}
                        </ul>
                      )}
                    </li>
                  );
                })}
              </ul>
            )}
          </div>

          {total > 0 && (
            <div className="px-4 py-2.5 border-t border-gray-100 flex flex-wrap items-center justify-between gap-2 bg-[#fafafa] dark:bg-gray-900 flex-shrink-0">
              <p className="text-xs text-gray-500">
                {t('history.showRange').replace('{start}', String((page - 1) * pageSize + 1)).replace('{end}', String(Math.min(page * pageSize, total))).replace('{total}', String(total))}
              </p>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  disabled={page <= 1 || initialLoading || tableLoading}
                  onClick={() => goPage(page - 1)}
                  className="px-3 py-1.5 text-xs font-medium rounded-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-800 hover:bg-gray-50 dark:hover:bg-gray-700 disabled:opacity-40"
                >
                  {t('history.prevPage')}
                </button>
                <span className="text-xs text-gray-600 tabular-nums px-1">
                  {page} / {totalPages}
                </span>
                <button
                  type="button"
                  disabled={page >= totalPages || initialLoading || tableLoading}
                  onClick={() => goPage(page + 1)}
                  className="px-3 py-1.5 text-xs font-medium rounded-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-800 hover:bg-gray-50 dark:hover:bg-gray-700 disabled:opacity-40"
                >
                  {t('history.nextPage')}
                </button>
              </div>
            </div>
          )}
        </div>
      </div>

      {compareOpen && (
        <div
          className="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-black/45 backdrop-blur-[1px]"
          role="dialog"
          aria-modal="true"
          aria-labelledby="history-compare-title"
          onMouseDown={e => {
            if (e.target === e.currentTarget) closeCompareModal();
          }}
        >
          <div className="bg-white dark:bg-gray-800 rounded-xl shadow-xl border border-gray-200 dark:border-gray-700 w-full max-w-[90vw] max-h-[92vh] flex flex-col overflow-hidden">
            <div className="flex items-start justify-between gap-3 px-4 py-3 border-b border-gray-100 shrink-0">
              <div className="min-w-0">
                <h3 id="history-compare-title" className="text-sm font-semibold text-gray-900 dark:text-gray-100 truncate pr-2">
                  {t('history.compareTitle')}
                </h3>
                <p className="text-xs text-gray-500 truncate mt-0.5" title={compareTarget?.original_filename}>
                  {compareTarget?.original_filename}
                </p>
              </div>
              <button
                type="button"
                onClick={closeCompareModal}
                className="shrink-0 px-2.5 py-1 text-xs font-medium rounded-lg border border-gray-200 hover:bg-gray-50"
              >
                {t('history.close')}
              </button>
            </div>

            <div className="px-4 py-2 border-b border-gray-100 flex flex-wrap gap-2 shrink-0 bg-[#fafafa] dark:bg-gray-900">
              {compareBlobUrls && (
                <button
                  type="button"
                  onClick={() => setCompareTab('preview')}
                  className={`px-3 py-1.5 text-xs rounded-lg border ${
                    compareTab === 'preview'
                      ? 'bg-[#0a0a0a] text-white border-[#0a0a0a]'
                      : 'bg-white dark:bg-gray-800 border-gray-200 dark:border-gray-600 text-gray-700 dark:text-gray-300'
                  }`}
                >
                  {t('history.tab.preview')}
                </button>
              )}
              {!isBinaryCompare && (
                <button
                  type="button"
                  onClick={() => setCompareTab('text')}
                  className={`px-3 py-1.5 text-xs rounded-lg border ${
                    compareTab === 'text'
                      ? 'bg-[#0a0a0a] text-white border-[#0a0a0a]'
                      : 'bg-white dark:bg-gray-800 border-gray-200 dark:border-gray-600 text-gray-700 dark:text-gray-300'
                  }`}
                >
                  {t('history.tab.text')}
                </button>
              )}
              {!isBinaryCompare && (
                <button
                  type="button"
                  onClick={() => setCompareTab('changes')}
                  disabled={!compareData?.changes?.length}
                  className={`px-3 py-1.5 text-xs rounded-lg border disabled:opacity-40 ${
                    compareTab === 'changes'
                      ? 'bg-[#0a0a0a] text-white border-[#0a0a0a]'
                      : 'bg-white dark:bg-gray-800 border-gray-200 dark:border-gray-600 text-gray-700 dark:text-gray-300'
                  }`}
                >
                  {t('history.tab.changes')}
                  {compareData?.changes?.length ? ` (${compareData.changes.length})` : ''}
                </button>
              )}
            </div>

            <div className="flex-1 min-h-0 overflow-auto p-4">
              {compareLoading && (
                <div className="flex flex-col items-center justify-center py-16 gap-2 text-sm text-gray-500">
                  <div className="w-7 h-7 border-2 border-[#e5e5e5] border-t-[#1d1d1f] rounded-full animate-spin" />
                  {t('history.loadingCompare')}
                </div>
              )}
              {!compareLoading && compareErr && (
                <p className="text-sm text-red-600 py-8 text-center">{compareErr}</p>
              )}
              {!compareLoading && !compareErr && compareData && (
                <>
                  {compareTab === 'preview' && compareBlobUrls && (
                    <div className="flex flex-col xl:flex-row gap-3 items-start">
                      {/* 左侧：脱敏前后对比图 */}
                      <div className="flex-1 min-w-0 grid grid-cols-1 lg:grid-cols-2 gap-3">
                        <div className="flex flex-col border border-gray-200 rounded-lg overflow-hidden bg-gray-50">
                          <div className="px-3 py-1.5 text-xs font-medium bg-gray-100 dark:bg-gray-900 text-gray-700 dark:text-gray-300 border-b border-gray-200 dark:border-gray-700">
                            {t('history.beforeRedaction')}
                          </div>
                          <div className="flex items-center justify-center p-2 bg-white">
                            {String(compareTarget?.file_type).includes('pdf') ? (
                              <iframe title="original-pdf" src={compareBlobUrls.original} className="w-full h-[620px] border-0 rounded" />
                            ) : (
                              <img src={compareBlobUrls.original} alt={t('history.beforeRedaction')} className="max-w-full max-w-full max-h-[620px] object-contain" />
                            )}
                          </div>
                        </div>
                        <div className="flex flex-col border border-emerald-200 rounded-lg overflow-hidden bg-emerald-50/30">
                          <div className="px-3 py-1.5 text-xs font-medium bg-emerald-100 text-emerald-900 border-b border-emerald-200">
                            {t('history.afterRedaction')}
                          </div>
                          <div className="flex items-center justify-center p-2 bg-white">
                            {String(compareTarget?.file_type).includes('pdf') ? (
                              <iframe title="redacted-pdf" src={compareBlobUrls.redacted} className="w-full h-[620px] border-0 rounded" />
                            ) : (
                              <img src={compareBlobUrls.redacted} alt={t('history.afterRedaction')} className="max-w-full max-w-full max-h-[620px] object-contain" />
                            )}
                          </div>
                        </div>
                      </div>
                      {/* 右侧：脱敏项列表 — self-start 跟随图片高度不拉长 */}
                      <div className="xl:w-[300px] xl:shrink-0 self-start rounded-lg border border-gray-200 bg-white overflow-hidden">
                        <div className="px-3 py-2 border-b border-gray-100 bg-[#fafafa]">
                          <p className="text-sm font-semibold text-gray-900">{t('history.previewRedactedItems')}</p>
                          <p className="text-2xs text-gray-500 mt-0.5">
                            {t('history.previewItemsCount').replace('{n}', String(comparePreviewItems.length))}
                          </p>
                        </div>
                        <div className="max-h-[620px] overflow-auto p-3">
                          {comparePreviewItems.length > 0 ? (
                            <ul className="space-y-2">
                              {comparePreviewItems.map(item => (
                                <li key={item.id} className="rounded-lg border border-gray-200 bg-[#fcfcfc] px-3 py-2">
                                  <div className="flex items-start justify-between gap-2">
                                    <span className="inline-flex rounded-full bg-gray-100 px-2 py-0.5 text-2xs font-medium text-gray-700">{item.label}</span>
                                    <span className="text-2xs text-gray-400 whitespace-nowrap">{item.meta}</span>
                                  </div>
                                  <p className="mt-1 text-xs text-gray-800 break-all">{item.value}</p>
                                </li>
                              ))}
                            </ul>
                          ) : (
                            <div className="py-8 flex items-center justify-center text-sm text-gray-400">
                              {t('history.noPreviewItems')}
                            </div>
                          )}
                        </div>
                      </div>
                    </div>
                  )}

                  {compareTab === 'text' && (
                    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 min-h-[min(50vh,480px)]">
                      <div className="flex flex-col min-h-0 border border-gray-200 rounded-lg overflow-hidden">
                        <div className="px-3 py-1.5 text-xs font-medium bg-gray-100 dark:bg-gray-900 text-gray-700 dark:text-gray-300 border-b border-gray-200 dark:border-gray-700">
                          {t('history.originalText')}
                        </div>
                        <div className="flex-1 overflow-auto p-3 bg-white dark:bg-gray-800 max-h-[min(70vh,720px)]">
                          <pre className="whitespace-pre-wrap font-serif text-sm text-gray-800 dark:text-gray-200 leading-relaxed">
                            {compareData.original_content}
                          </pre>
                        </div>
                      </div>
                      <div className="flex flex-col min-h-0 border border-emerald-200 rounded-lg overflow-hidden">
                        <div className="px-3 py-1.5 text-xs font-medium bg-emerald-100 text-emerald-900 border-b border-emerald-200">
                          {t('history.redactedText')}
                        </div>
                        <div className="flex-1 overflow-auto p-3 bg-white dark:bg-gray-800 max-h-[min(70vh,720px)]">
                          <pre className="whitespace-pre-wrap font-serif text-sm text-gray-800 dark:text-gray-200 leading-relaxed">
                            {compareData.redacted_content}
                          </pre>
                        </div>
                      </div>
                    </div>
                  )}

                  {compareTab === 'changes' && (
                    <div className="border border-gray-200 rounded-lg overflow-hidden overflow-x-auto">
                      {!compareData.changes.length ? (
                        <p className="p-6 text-sm text-gray-500 text-center">{t('history.noChanges')}</p>
                      ) : (
                        <table className="w-full text-sm">
                          <thead>
                            <tr className="bg-gray-50 border-b border-gray-200">
                              <th className="px-3 py-2 text-left font-medium text-gray-700">{t('history.col.original')}</th>
                              <th className="px-2 py-2 text-center text-gray-400 w-10">→</th>
                              <th className="px-3 py-2 text-left font-medium text-gray-700">{t('history.col.replacement')}</th>
                              <th className="px-3 py-2 text-center font-medium text-gray-700 w-16">{t('history.col.count')}</th>
                            </tr>
                          </thead>
                          <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
                            {compareData.changes.map((c, i) => (
                              <tr key={i} className="hover:bg-gray-50/80">
                                <td className="px-3 py-2 align-top">
                                  <span className="inline-block px-2 py-0.5 bg-red-50 text-red-800 rounded font-mono text-xs break-all">
                                    {c.original}
                                  </span>
                                </td>
                                <td className="px-2 py-2 text-center text-gray-400">→</td>
                                <td className="px-3 py-2 align-top">
                                  <span className="inline-block px-2 py-0.5 bg-emerald-50 text-emerald-800 rounded font-mono text-xs break-all">
                                    {c.replacement}
                                  </span>
                                </td>
                                <td className="px-3 py-2 text-center tabular-nums">{c.count}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      )}
                    </div>
                  )}
                </>
              )}
            </div>
          </div>
        </div>
      )}
      <ConfirmDialog
        open={!!confirmDlg}
        title={confirmDlg?.title ?? ''}
        message={confirmDlg?.message ?? ''}
        danger
        confirmText={t('history.confirmDeleteText')}
        onConfirm={() => confirmDlg?.onConfirm()}
        onCancel={() => setConfirmDlg(null)}
      />
    </div>
  );
};

export default History;
