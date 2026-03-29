import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { fileApi, redactionApi } from '../services/api';
import { showToast } from '../components/Toast';
import type { CompareData, FileListItem } from '../types';
import { formCheckboxClass } from '../ui/selectionClasses';

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

async function blobUrlFromFileDownload(fileId: string, redacted: boolean, mime: string): Promise<string> {
  const url = fileApi.getDownloadUrl(fileId, redacted);
  const res = await fetch(url);
  if (!res.ok) throw new Error(redacted ? '无法加载脱敏文件预览' : '无法加载原始文件预览');
  const buf = await res.arrayBuffer();
  return URL.createObjectURL(new Blob([buf], { type: mime }));
}

const PAGE_SIZE_OPTIONS = [10, 20, 50, 100] as const;

type HistoryGroup =
  | { kind: 'standalone'; row: FileListItem }
  | { kind: 'batch'; batch_group_id: string; batch_group_count: number; rows: FileListItem[] };

/** 将当前页行按 batch_group_id 合并为树节点（后端已保证同批相邻） */
function buildHistoryGroups(rows: FileListItem[]): HistoryGroup[] {
  const out: HistoryGroup[] = [];
  let i = 0;
  while (i < rows.length) {
    const r = rows[i];
    const bg = r.batch_group_id;
    if (!bg) {
      out.push({ kind: 'standalone', row: r });
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
  /** 折叠的批量节点（batch_group_id） */
  const [collapsedBatchIds, setCollapsedBatchIds] = useState<Set<string>>(() => new Set());
  const [msg, setMsg] = useState<{ text: string; tone: 'ok' | 'warn' | 'err' } | null>(null);

  const [dateFilter, setDateFilter] = useState<'all' | '7d' | '30d'>('all');
  const [fileTypeFilter, setFileTypeFilter] = useState<'all' | 'word' | 'pdf' | 'image'>('all');
  const [statusFilter, setStatusFilter] = useState<'all' | 'redacted' | 'unredacted'>('all');

  const [compareOpen, setCompareOpen] = useState(false);
  const [compareTarget, setCompareTarget] = useState<FileListItem | null>(null);
  const [compareLoading, setCompareLoading] = useState(false);
  const [compareErr, setCompareErr] = useState<string | null>(null);
  const [compareData, setCompareData] = useState<CompareData | null>(null);
  const [compareBlobUrls, setCompareBlobUrls] = useState<{ original: string; redacted: string } | null>(null);
  const [compareTab, setCompareTab] = useState<'preview' | 'text' | 'changes'>('preview');

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
  }, [revokeCompareBlobs]);

  const openCompareModal = useCallback(
    async (row: FileListItem) => {
      revokeCompareBlobs();
      setCompareOpen(true);
      setCompareTarget(row);
      setCompareData(null);
      setCompareErr(null);
      setCompareLoading(true);
      const ft = String(row.file_type);
      const useBinaryPreview = ft === 'image' || ft === 'pdf' || ft === 'pdf_scanned';
      setCompareTab(useBinaryPreview ? 'preview' : 'text');
      try {
        const data = await redactionApi.getComparison(row.file_id);
        setCompareData(data);
        if (useBinaryPreview) {
          const mime = previewMimeForRow(row);
          const [original, redacted] = await Promise.all([
            blobUrlFromFileDownload(row.file_id, false, mime),
            blobUrlFromFileDownload(row.file_id, true, mime),
          ]);
          setCompareBlobUrls({ original, redacted });
        }
      } catch (e) {
        setCompareErr(e instanceof Error ? e.message : '加载对比失败');
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

  const load = useCallback(
    async (isRefresh = false, targetPage?: number, targetSize?: number) => {
      const p = targetPage ?? page;
      const ps = targetSize ?? pageSize;
      if (isRefresh) setRefreshing(true);
      else if (firstLoadRef.current) setInitialLoading(true);
      else setTableLoading(true);
      setMsg(null);
      try {
        const res = await fileApi.list(p, ps);
        setRows(res.files);
        setTotal(res.total);
        setPage(res.page);
        setPageSize(res.page_size);
        setSelected(new Set());
      } catch (e) {
        setMsg({ text: e instanceof Error ? e.message : '加载失败', tone: 'err' });
      } finally {
        firstLoadRef.current = false;
        setInitialLoading(false);
        setTableLoading(false);
        setRefreshing(false);
      }
    },
    [page, pageSize]
  );

  useEffect(() => {
    load(false, 1, 10);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 仅挂载时拉第一页
  }, []);

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
      result = result.filter(r => statusFilter === 'redacted' ? r.has_output : !r.has_output);
    }
    return result;
  }, [rows, dateFilter, fileTypeFilter, statusFilter]);

  const selectedIds = filteredRows.filter(r => selected.has(r.file_id)).map(r => r.file_id);

  const historyGroups = useMemo(() => buildHistoryGroups(filteredRows), [filteredRows]);

  const statsData = useMemo(() => {
    const totalFiles = filteredRows.length;
    const redactedFiles = filteredRows.filter(r => r.has_output).length;
    const entitySum = filteredRows.reduce((s, r) => s + (r.entity_count || 0), 0);
    const sizeSum = filteredRows.reduce((s, r) => s + (r.file_size || 0), 0);
    let sizeLabel: string;
    if (sizeSum < 1024) sizeLabel = sizeSum + ' B';
    else if (sizeSum < 1024 * 1024) sizeLabel = (sizeSum / 1024).toFixed(1) + ' KB';
    else sizeLabel = (sizeSum / 1024 / 1024).toFixed(1) + ' MB';
    return { totalFiles, redactedFiles, entitySum, sizeLabel };
  }, [filteredRows]);

  const hasActiveFilter = dateFilter !== 'all' || fileTypeFilter !== 'all' || statusFilter !== 'all';

  const clearFilters = () => {
    setDateFilter('all');
    setFileTypeFilter('all');
    setStatusFilter('all');
  };

  const downloadZipByIds = async (ids: string[], redacted: boolean, filename: string) => {
    if (!ids.length) {
      setMsg({ text: '没有可下载的文件', tone: 'warn' });
      return;
    }
    if (redacted) {
      const noOut = rows.filter(r => ids.includes(r.file_id) && !r.has_output);
      if (noOut.length) {
        setMsg({ text: '所选文件中有尚未脱敏的项', tone: 'warn' });
        return;
      }
    }
    setZipLoading(true);
    try {
      const blob = await fileApi.batchDownloadZip(ids, redacted);
      triggerDownload(blob, filename);
      showToast('已开始下载 ZIP', 'success');
      setMsg({ text: '已开始下载 ZIP', tone: 'ok' });
    } catch (e) {
      setMsg({ text: e instanceof Error ? e.message : '下载失败', tone: 'err' });
    } finally {
      setZipLoading(false);
    }
  };

  const downloadZip = async (redacted: boolean) => {
    if (!selectedIds.length) {
      setMsg({ text: '请先勾选文件', tone: 'warn' });
      return;
    }
    await downloadZipByIds(
      selectedIds,
      redacted,
      redacted ? 'history_redacted.zip' : 'history_original.zip'
    );
  };

  const downloadBatchGroupZip = async (g: Extract<HistoryGroup, { kind: 'batch' }>, redacted: boolean) => {
    const ids = g.rows.map(r => r.file_id);
    const short = g.batch_group_id.replace(/[^a-zA-Z0-9]/g, '').slice(0, 8) || 'batch';
    const name = redacted ? `batch_${short}_redacted.zip` : `batch_${short}_original.zip`;
    await downloadZipByIds(ids, redacted, name);
  };

  const toggleBatchCollapse = (batchGroupId: string) => {
    setCollapsedBatchIds(prev => {
      const n = new Set(prev);
      if (n.has(batchGroupId)) n.delete(batchGroupId);
      else n.add(batchGroupId);
      return n;
    });
  };

  const toggleBatchSelection = (g: Extract<HistoryGroup, { kind: 'batch' }>) => {
    const ids = g.rows.map(r => r.file_id);
    const allOn = ids.length > 0 && ids.every(id => selected.has(id));
    setSelected(prev => {
      const next = new Set(prev);
      if (allOn) ids.forEach(id => next.delete(id));
      else ids.forEach(id => next.add(id));
      return next;
    });
  };

  const remove = async (id: string) => {
    if (!window.confirm('确定从服务器删除该文件？')) return;
    try {
      await fileApi.delete(id);
      await load(true, page, pageSize);
      setMsg({ text: '已删除', tone: 'ok' });
    } catch (e) {
      setMsg({ text: e instanceof Error ? e.message : '删除失败', tone: 'err' });
    }
  };

  const msgClass =
    msg?.tone === 'ok'
      ? 'bg-green-50 text-green-800 border border-green-100'
      : msg?.tone === 'warn'
        ? 'bg-amber-50 text-amber-900 border border-amber-100'
        : 'bg-red-50 text-red-800 border border-red-100';

  const allSelected = filteredRows.length > 0 && selectedIds.length === filteredRows.length;

  return (
    <div className="flex-1 min-h-0 min-w-0 flex flex-col bg-[#f5f5f7] overflow-hidden">
      <div className="flex-1 flex flex-col min-h-0 min-w-0 px-3 py-3 sm:px-5 sm:py-4 w-full max-w-[min(100%,1920px)] mx-auto items-stretch">
        <p className="text-caption text-gray-500 mb-3 flex-shrink-0 leading-snug">
          与 Playground、批量共用存储；来自「批量处理」同一会话的文件会归为一组，可一键下载该批 ZIP。翻页与勾选仅作用于本页。
        </p>

        <div className="flex flex-wrap items-center gap-2 mb-3 flex-shrink-0">
          <button
            type="button"
            onClick={() => load(true, page, pageSize)}
            disabled={refreshing || initialLoading || tableLoading}
            className="inline-flex items-center gap-1.5 px-3 py-2 text-sm rounded-lg border border-gray-200 bg-white hover:bg-gray-50 disabled:opacity-50 transition-colors"
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
            刷新
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
            {zipLoading ? '正在打包下载...' : '下载原始 ZIP'}
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
            {zipLoading ? '正在打包下载...' : '下载脱敏 ZIP'}
          </button>
          <div className="ml-auto flex items-center gap-2 text-xs text-[#737373]">
            <span>每页</span>
            <select
              value={pageSize}
              onChange={e => changePageSize(Number(e.target.value))}
              className="border border-gray-200 rounded-lg px-2 py-1.5 bg-white text-[#0a0a0a] text-xs"
            >
              {PAGE_SIZE_OPTIONS.map(n => (
                <option key={n} value={n}>
                  {n} 条
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
          <div className="bg-white rounded-lg border border-gray-200 px-3 py-2.5 shadow-sm">
            <p className="text-xs text-gray-500">总文件数</p>
            <p className="text-lg font-semibold text-gray-900 mt-0.5">{statsData.totalFiles}</p>
          </div>
          <div className="bg-white rounded-lg border border-gray-200 px-3 py-2.5 shadow-sm">
            <p className="text-xs text-gray-500">已脱敏</p>
            <p className="text-lg font-semibold text-emerald-700 mt-0.5">{statsData.redactedFiles}</p>
          </div>
          <div className="bg-white rounded-lg border border-gray-200 px-3 py-2.5 shadow-sm">
            <p className="text-xs text-gray-500">识别实体</p>
            <p className="text-lg font-semibold text-gray-900 mt-0.5">{statsData.entitySum}</p>
          </div>
          <div className="bg-white rounded-lg border border-gray-200 px-3 py-2.5 shadow-sm">
            <p className="text-xs text-gray-500">存储占用</p>
            <p className="text-lg font-semibold text-gray-900 mt-0.5">{statsData.sizeLabel}</p>
          </div>
        </div>

        {/* Filter bar */}
        <div className="flex flex-wrap items-center gap-2 mb-3 flex-shrink-0">
          <div className="flex items-center gap-1 rounded-lg border border-gray-200 bg-white p-0.5">
            {([['all', '全部'], ['7d', '最近7天'], ['30d', '最近30天']] as const).map(([val, label]) => (
              <button
                key={val}
                type="button"
                onClick={() => setDateFilter(val)}
                className={`px-2.5 py-1 text-xs rounded-md transition-colors ${
                  dateFilter === val ? 'bg-[#0a0a0a] text-white' : 'text-gray-600 hover:bg-gray-100'
                }`}
              >
                {label}
              </button>
            ))}
          </div>
          <select
            value={fileTypeFilter}
            onChange={e => setFileTypeFilter(e.target.value as typeof fileTypeFilter)}
            className="border border-gray-200 rounded-lg px-2.5 py-1.5 bg-white text-xs text-gray-700"
          >
            <option value="all">全部类型</option>
            <option value="word">Word</option>
            <option value="pdf">PDF</option>
            <option value="image">图片</option>
          </select>
          <select
            value={statusFilter}
            onChange={e => setStatusFilter(e.target.value as typeof statusFilter)}
            className="border border-gray-200 rounded-lg px-2.5 py-1.5 bg-white text-xs text-gray-700"
          >
            <option value="all">全部状态</option>
            <option value="redacted">已脱敏</option>
            <option value="unredacted">未脱敏</option>
          </select>
          {hasActiveFilter && (
            <button
              type="button"
              onClick={clearFilters}
              className="px-2.5 py-1.5 text-xs text-gray-500 hover:text-gray-700 hover:bg-gray-100 rounded-lg transition-colors"
            >
              清除筛选
            </button>
          )}
        </div>

        <div className="w-full flex flex-col flex-1 min-h-0 bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
          <div className="px-4 py-2.5 border-b border-gray-100 flex flex-wrap items-center justify-between gap-2 flex-shrink-0">
            <div>
              <h3 className="font-semibold text-gray-900 text-sm">文件记录</h3>
              <p className="text-xs text-gray-400 mt-0.5">
                共 {total} 条 · 第 {page} / {totalPages} 页
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
                全选本页
              </label>
            )}
          </div>

          <div className="relative flex-1 min-h-0 overflow-y-auto flex flex-col">
            {tableLoading && rows.length > 0 && (
              <div className="absolute inset-0 bg-white/60 flex items-center justify-center z-10 backdrop-blur-[1px]">
                <div className="w-7 h-7 border-2 border-[#e5e5e5] border-t-[#1d1d1f] rounded-full animate-spin" />
              </div>
            )}
            {initialLoading && rows.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-20 gap-3">
                <div className="w-7 h-7 border-2 border-[#e5e5e5] border-t-[#1d1d1f] rounded-full animate-spin" />
                <p className="text-sm text-gray-400">加载中…</p>
              </div>
            ) : rows.length === 0 ? (
              <p className="px-5 py-16 text-center text-sm text-gray-400">暂无处理记录</p>
            ) : (
              <ul className="flex w-full min-h-full flex-1 flex-col divide-y divide-gray-100">
                {historyGroups.map((g, gi) => {
                  const stripe = gi % 2 === 1 ? 'bg-gray-50/50' : '';
                  if (g.kind === 'standalone') {
                    const r = g.row;
                    return (
                      <li
                        key={r.file_id}
                        className={`flex flex-1 basis-0 min-h-[3rem] gap-2.5 sm:gap-3 items-center px-3 sm:px-4 py-2 transition-colors ${stripe} ${
                          selected.has(r.file_id) ? '!bg-[#007AFF]/[0.07]' : 'hover:bg-gray-50/90'
                        }`}
                      >
                        <input
                          type="checkbox"
                          className={`shrink-0 ${formCheckboxClass('md')}`}
                          checked={selected.has(r.file_id)}
                          onChange={() => toggle(r.file_id)}
                          aria-label={`选择 ${r.original_filename}`}
                        />
                        <p
                          className="text-sm font-medium text-gray-900 truncate min-w-0 flex-1 basis-[40%]"
                          title={r.original_filename}
                        >
                          {r.original_filename}
                        </p>
                        <div className="flex flex-wrap items-center justify-end gap-x-2 sm:gap-x-3 gap-y-1 shrink-0 text-caption text-gray-400 tabular-nums">
                          <span className="hidden md:inline whitespace-nowrap">
                            {r.created_at ? new Date(r.created_at).toLocaleString() : '—'}
                          </span>
                          <span className="md:hidden whitespace-nowrap">
                            {r.created_at ? new Date(r.created_at).toLocaleDateString() : '—'}
                          </span>
                          <span className="whitespace-nowrap" title="文本实体数 + 图像检测区域数">
                            识别项 {r.entity_count}
                          </span>
                          <span
                            className={`text-xs px-2 py-0.5 rounded-full whitespace-nowrap ${
                              r.has_output ? 'bg-emerald-50 text-emerald-800' : 'bg-gray-100 text-gray-500'
                            }`}
                          >
                            {r.has_output ? '已脱敏' : '未脱敏'}
                          </span>
                          {r.has_output && (
                            <button
                              type="button"
                              className="text-xs font-medium text-[#0a0a0a] px-2 py-1 rounded-lg border border-gray-200 bg-white hover:bg-gray-50 transition-colors"
                              onClick={() => openCompareModal(r)}
                            >
                              查看对比
                            </button>
                          )}
                          <button
                            type="button"
                            className="text-xs font-medium text-red-600 hover:text-red-700 px-2 py-1 rounded-lg hover:bg-red-50 transition-colors"
                            onClick={() => remove(r.file_id)}
                          >
                            删除
                          </button>
                        </div>
                      </li>
                    );
                  }
                  const collapsed = collapsedBatchIds.has(g.batch_group_id);
                  const ids = g.rows.map(x => x.file_id);
                  const allInBatch = ids.length > 0 && ids.every(id => selected.has(id));
                  const onPage = g.rows.length;
                  const totalInBatch = g.batch_group_count;
                  const pageHint =
                    onPage < totalInBatch ? `（本页 ${onPage} 个，批次共 ${totalInBatch} 个）` : `（${totalInBatch} 个文件）`;
                  return (
                    <li key={`batch:${g.batch_group_id}`} className={`${stripe}`}>
                      <div className="flex flex-wrap items-center gap-2 px-3 sm:px-4 py-2 border-b border-gray-100/80 bg-[#fafafa]/90">
                        <button
                          type="button"
                          onClick={() => toggleBatchCollapse(g.batch_group_id)}
                          className="shrink-0 p-0.5 rounded text-gray-500 hover:bg-gray-200/80"
                          aria-expanded={!collapsed}
                          title={collapsed ? '展开' : '折叠'}
                        >
                          <svg
                            className={`w-4 h-4 transition-transform ${collapsed ? '' : 'rotate-90'}`}
                            fill="none"
                            stroke="currentColor"
                            viewBox="0 0 24 24"
                          >
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                          </svg>
                        </button>
                        <input
                          type="checkbox"
                          className={`shrink-0 ${formCheckboxClass('md')}`}
                          checked={allInBatch}
                          onChange={() => toggleBatchSelection(g)}
                          aria-label="全选本批量"
                        />
                        <div className="min-w-0 flex-1">
                          <p className="text-sm font-semibold text-gray-900">
                            批量任务
                            <span className="ml-1.5 font-mono text-xs font-normal text-gray-500">
                              {g.batch_group_id.slice(0, 8)}…
                            </span>
                          </p>
                          <p className="text-2xs text-gray-500 mt-0.5">{pageHint}</p>
                        </div>
                        <div className="flex flex-wrap items-center gap-1.5 shrink-0">
                          <button
                            type="button"
                            disabled={zipLoading || initialLoading || tableLoading}
                            onClick={() => void downloadBatchGroupZip(g, false)}
                            className="inline-flex items-center gap-1 text-2xs font-medium px-2 py-1 rounded-lg border border-gray-200 bg-white hover:bg-gray-50 disabled:opacity-40"
                          >
                            {zipLoading && (
                              <svg className="w-3 h-3 animate-spin" viewBox="0 0 24 24" fill="none">
                                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                              </svg>
                            )}
                            {zipLoading ? '正在打包下载...' : '整批原文件 ZIP'}
                          </button>
                          <button
                            type="button"
                            disabled={zipLoading || initialLoading || tableLoading}
                            onClick={() => void downloadBatchGroupZip(g, true)}
                            className="inline-flex items-center gap-1 text-2xs font-medium px-2 py-1 rounded-lg border border-gray-200 bg-white hover:bg-gray-50 disabled:opacity-40"
                          >
                            {zipLoading && (
                              <svg className="w-3 h-3 animate-spin" viewBox="0 0 24 24" fill="none">
                                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                              </svg>
                            )}
                            {zipLoading ? '正在打包下载...' : '整批脱敏 ZIP'}
                          </button>
                        </div>
                      </div>
                      {!collapsed && (
                        <ul className="border-b border-gray-100">
                          {g.rows.map(r => (
                            <li
                              key={r.file_id}
                              className={`flex min-h-[3rem] gap-2.5 sm:gap-3 items-center pl-8 pr-3 sm:pr-4 py-2 transition-colors border-t border-gray-50 ${
                                selected.has(r.file_id) ? '!bg-[#007AFF]/[0.07]' : 'hover:bg-gray-50/90'
                              }`}
                            >
                              <span className="text-gray-300 select-none w-3 shrink-0" aria-hidden>
                                └
                              </span>
                              <input
                                type="checkbox"
                                className={`shrink-0 ${formCheckboxClass('md')}`}
                                checked={selected.has(r.file_id)}
                                onChange={() => toggle(r.file_id)}
                                aria-label={`选择 ${r.original_filename}`}
                              />
                              <p
                                className="text-sm font-medium text-gray-900 truncate min-w-0 flex-1 basis-[40%]"
                                title={r.original_filename}
                              >
                                {r.original_filename}
                              </p>
                              <div className="flex flex-wrap items-center justify-end gap-x-2 sm:gap-x-3 gap-y-1 shrink-0 text-caption text-gray-400 tabular-nums">
                                <span className="hidden md:inline whitespace-nowrap">
                                  {r.created_at ? new Date(r.created_at).toLocaleString() : '—'}
                                </span>
                                <span className="md:hidden whitespace-nowrap">
                                  {r.created_at ? new Date(r.created_at).toLocaleDateString() : '—'}
                                </span>
                                <span className="whitespace-nowrap" title="文本实体数 + 图像检测区域数">
                                  识别项 {r.entity_count}
                                </span>
                                <span
                                  className={`text-xs px-2 py-0.5 rounded-full whitespace-nowrap ${
                                    r.has_output ? 'bg-emerald-50 text-emerald-800' : 'bg-gray-100 text-gray-500'
                                  }`}
                                >
                                  {r.has_output ? '已脱敏' : '未脱敏'}
                                </span>
                                {r.has_output && (
                                  <button
                                    type="button"
                                    className="text-xs font-medium text-[#0a0a0a] px-2 py-1 rounded-lg border border-gray-200 bg-white hover:bg-gray-50 transition-colors"
                                    onClick={() => openCompareModal(r)}
                                  >
                                    查看对比
                                  </button>
                                )}
                                <button
                                  type="button"
                                  className="text-xs font-medium text-red-600 hover:text-red-700 px-2 py-1 rounded-lg hover:bg-red-50 transition-colors"
                                  onClick={() => remove(r.file_id)}
                                >
                                  删除
                                </button>
                              </div>
                            </li>
                          ))}
                        </ul>
                      )}
                    </li>
                  );
                })}
              </ul>
            )}
          </div>

          {total > 0 && (
            <div className="px-4 py-2.5 border-t border-gray-100 flex flex-wrap items-center justify-between gap-2 bg-[#fafafa] flex-shrink-0">
              <p className="text-xs text-gray-500">
                显示 {(page - 1) * pageSize + 1}–{Math.min(page * pageSize, total)} 条，共 {total} 条
              </p>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  disabled={page <= 1 || initialLoading || tableLoading}
                  onClick={() => goPage(page - 1)}
                  className="px-3 py-1.5 text-xs font-medium rounded-lg border border-gray-200 bg-white hover:bg-gray-50 disabled:opacity-40"
                >
                  上一页
                </button>
                <span className="text-xs text-gray-600 tabular-nums px-1">
                  {page} / {totalPages}
                </span>
                <button
                  type="button"
                  disabled={page >= totalPages || initialLoading || tableLoading}
                  onClick={() => goPage(page + 1)}
                  className="px-3 py-1.5 text-xs font-medium rounded-lg border border-gray-200 bg-white hover:bg-gray-50 disabled:opacity-40"
                >
                  下一页
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
          <div className="bg-white rounded-xl shadow-xl border border-gray-200 w-full max-w-6xl max-h-[92vh] flex flex-col overflow-hidden">
            <div className="flex items-start justify-between gap-3 px-4 py-3 border-b border-gray-100 shrink-0">
              <div className="min-w-0">
                <h3 id="history-compare-title" className="text-sm font-semibold text-gray-900 truncate pr-2">
                  脱敏前后对比
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
                关闭
              </button>
            </div>

            <div className="px-4 py-2 border-b border-gray-100 flex flex-wrap gap-2 shrink-0 bg-[#fafafa]">
              {compareBlobUrls && (
                <button
                  type="button"
                  onClick={() => setCompareTab('preview')}
                  className={`px-3 py-1.5 text-xs rounded-lg border ${
                    compareTab === 'preview'
                      ? 'bg-[#0a0a0a] text-white border-[#0a0a0a]'
                      : 'bg-white border-gray-200 text-gray-700'
                  }`}
                >
                  文件预览
                </button>
              )}
              <button
                type="button"
                onClick={() => setCompareTab('text')}
                className={`px-3 py-1.5 text-xs rounded-lg border ${
                  compareTab === 'text'
                    ? 'bg-[#0a0a0a] text-white border-[#0a0a0a]'
                    : 'bg-white border-gray-200 text-gray-700'
                }`}
              >
                文本左右对比
              </button>
              <button
                type="button"
                onClick={() => setCompareTab('changes')}
                disabled={!compareData?.changes?.length}
                className={`px-3 py-1.5 text-xs rounded-lg border disabled:opacity-40 ${
                  compareTab === 'changes'
                    ? 'bg-[#0a0a0a] text-white border-[#0a0a0a]'
                    : 'bg-white border-gray-200 text-gray-700'
                }`}
              >
                替换明细
                {compareData?.changes?.length ? ` (${compareData.changes.length})` : ''}
              </button>
            </div>

            <div className="flex-1 min-h-0 overflow-auto p-4">
              {compareLoading && (
                <div className="flex flex-col items-center justify-center py-16 gap-2 text-sm text-gray-500">
                  <div className="w-7 h-7 border-2 border-[#e5e5e5] border-t-[#1d1d1f] rounded-full animate-spin" />
                  加载对比数据…
                </div>
              )}
              {!compareLoading && compareErr && (
                <p className="text-sm text-red-600 py-8 text-center">{compareErr}</p>
              )}
              {!compareLoading && !compareErr && compareData && (
                <>
                  {compareTab === 'preview' && compareBlobUrls && (
                    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 h-full min-h-[min(70vh,640px)]">
                      <div className="flex flex-col min-h-0 border border-gray-200 rounded-lg overflow-hidden bg-gray-50">
                        <div className="px-3 py-1.5 text-xs font-medium bg-gray-100 text-gray-700 border-b border-gray-200">
                          脱敏前
                        </div>
                        <div className="flex-1 min-h-0 flex items-center justify-center p-2 bg-white">
                          {String(compareTarget?.file_type).includes('pdf') ? (
                            <iframe
                              title="original-pdf"
                              src={compareBlobUrls.original}
                              className="w-full h-[min(68vh,720px)] border-0 rounded"
                            />
                          ) : (
                            <img
                              src={compareBlobUrls.original}
                              alt="脱敏前"
                              className="max-w-full max-h-[min(68vh,720px)] object-contain"
                            />
                          )}
                        </div>
                      </div>
                      <div className="flex flex-col min-h-0 border border-emerald-200 rounded-lg overflow-hidden bg-emerald-50/30">
                        <div className="px-3 py-1.5 text-xs font-medium bg-emerald-100 text-emerald-900 border-b border-emerald-200">
                          脱敏后
                        </div>
                        <div className="flex-1 min-h-0 flex items-center justify-center p-2 bg-white">
                          {String(compareTarget?.file_type).includes('pdf') ? (
                            <iframe
                              title="redacted-pdf"
                              src={compareBlobUrls.redacted}
                              className="w-full h-[min(68vh,720px)] border-0 rounded"
                            />
                          ) : (
                            <img
                              src={compareBlobUrls.redacted}
                              alt="脱敏后"
                              className="max-w-full max-h-[min(68vh,720px)] object-contain"
                            />
                          )}
                        </div>
                      </div>
                    </div>
                  )}

                  {compareTab === 'text' && (
                    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 min-h-[min(50vh,480px)]">
                      <div className="flex flex-col min-h-0 border border-gray-200 rounded-lg overflow-hidden">
                        <div className="px-3 py-1.5 text-xs font-medium bg-gray-100 text-gray-700 border-b border-gray-200">
                          原始文本
                        </div>
                        <div className="flex-1 overflow-auto p-3 bg-white max-h-[min(70vh,720px)]">
                          <pre className="whitespace-pre-wrap font-serif text-sm text-gray-800 leading-relaxed">
                            {compareData.original_content}
                          </pre>
                        </div>
                      </div>
                      <div className="flex flex-col min-h-0 border border-emerald-200 rounded-lg overflow-hidden">
                        <div className="px-3 py-1.5 text-xs font-medium bg-emerald-100 text-emerald-900 border-b border-emerald-200">
                          脱敏后文本
                        </div>
                        <div className="flex-1 overflow-auto p-3 bg-white max-h-[min(70vh,720px)]">
                          <pre className="whitespace-pre-wrap font-serif text-sm text-gray-800 leading-relaxed">
                            {compareData.redacted_content}
                          </pre>
                        </div>
                      </div>
                    </div>
                  )}

                  {compareTab === 'changes' && (
                    <div className="border border-gray-200 rounded-lg overflow-hidden overflow-x-auto">
                      {!compareData.changes.length ? (
                        <p className="p-6 text-sm text-gray-500 text-center">暂无替换明细（例如纯图片脱敏可能无文本级变更表）</p>
                      ) : (
                        <table className="w-full text-sm">
                          <thead>
                            <tr className="bg-gray-50 border-b border-gray-200">
                              <th className="px-3 py-2 text-left font-medium text-gray-700">原始</th>
                              <th className="px-2 py-2 text-center text-gray-400 w-10">→</th>
                              <th className="px-3 py-2 text-left font-medium text-gray-700">替换为</th>
                              <th className="px-3 py-2 text-center font-medium text-gray-700 w-16">次数</th>
                            </tr>
                          </thead>
                          <tbody className="divide-y divide-gray-100">
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
    </div>
  );
};

export default History;
