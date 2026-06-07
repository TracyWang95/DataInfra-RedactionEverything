// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  authFetch,
  authenticatedBlobUrl,
  downloadFile as downloadAuthenticatedFile,
  revokeObjectUrl,
} from '@/services/api-client';
import { t } from '@/i18n';
import { fileApi, getBatchZipManifest, redactionApi } from '@/services/api';
import { showToast } from '@/components/Toast';
import { HISTORY_ACTIVE_POLL_MS, HISTORY_EMPTY_RESULT_POLL_MS } from '@/constants/timing';
import { getStorageItem, setStorageItem } from '@/lib/storage';
import { localizeErrorMessage } from '@/utils/localizeError';
import { resolveRedactionState } from '@/utils/redactionState';
import type { CompareData, FileListItem, FileListResponse } from '@/types';
import { useSearchParams } from 'react-router-dom';

export const PAGE_SIZE_OPTIONS = [10, 20] as const;

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

type LoadOptions = {
  silent?: boolean;
};

const HISTORY_ACTIVE_ITEM_STATUSES = new Set([
  'pending',
  'queued',
  'running',
  'parsing',
  'ner',
  'vision',
  'processing',
  'redacting',
  'review_approved',
]);

type CachedHistoryList = {
  capturedAt: number;
  source: SourceTab;
  jobId: string | null;
  page: number;
  page_size: number;
  total: number;
  files: FileListItem[];
  stats?: HistoryListStats;
};

type HistoryListStats = {
  total_files: number;
  redacted_files: number;
  awaiting_review_files: number;
  unredacted_files: number;
  entity_sum: number;
  size_bytes: number;
};

const EMPTY_HISTORY_LIST_STATS: HistoryListStats = {
  total_files: 0,
  redacted_files: 0,
  awaiting_review_files: 0,
  unredacted_files: 0,
  entity_sum: 0,
  size_bytes: 0,
};

function normalizeHistoryListStats(
  stats: FileListResponse['stats'] | undefined,
  files: FileListItem[],
  total: number,
): HistoryListStats {
  return {
    total_files: stats?.total_files ?? total,
    redacted_files: stats?.redacted_files ?? files.filter((row) => row.has_output).length,
    awaiting_review_files:
      stats?.awaiting_review_files ??
      files.filter((row) =>
        ['awaiting_review', 'review_approved'].includes(String(row.item_status ?? '').toLowerCase()),
      ).length,
    unredacted_files: stats?.unredacted_files ?? files.filter((row) => !row.has_output).length,
    entity_sum: stats?.entity_sum ?? files.reduce((sum, row) => sum + (row.entity_count || 0), 0),
    size_bytes: stats?.size_bytes ?? files.reduce((sum, row) => sum + (row.file_size || 0), 0),
  };
}

const HISTORY_LIST_CACHE_PREFIX = 'history:list-cache:v1';
const HISTORY_LIST_CACHE_TTL_MS = 30_000;
const MAX_HISTORY_LIST_CACHE_ROWS = 120;

function makeHistoryListCacheKey(
  source: SourceTab,
  jobId: string | null,
  page: number,
  pageSize: number,
): string {
  const safeJobId = jobId ?? '_none_';
  return `${HISTORY_LIST_CACHE_PREFIX}:${source}:${encodeURIComponent(safeJobId)}:${page}:${pageSize}`;
}

function isFreshHistoryListCache(entry: CachedHistoryList): boolean {
  return Date.now() - entry.capturedAt <= HISTORY_LIST_CACHE_TTL_MS;
}

function readHistoryListCache(
  source: SourceTab,
  jobId: string | null,
  page: number,
  pageSize: number,
  opts?: { allowStale?: boolean },
): CachedHistoryList | null {
  const payload = getStorageItem<CachedHistoryList | null>(
    makeHistoryListCacheKey(source, jobId, page, pageSize),
    null,
  );
  if (!payload || !Array.isArray(payload.files)) return null;
  if (typeof payload.capturedAt !== 'number') return null;
  if (!opts?.allowStale && !isFreshHistoryListCache(payload)) return null;
  if (!Array.isArray(payload.files) || payload.files.length > MAX_HISTORY_LIST_CACHE_ROWS)
    return null;
  return {
    capturedAt: payload.capturedAt,
    source: payload.source,
    jobId: payload.jobId,
    page: payload.page,
    page_size: payload.page_size,
    total: payload.total,
    files: payload.files,
    stats: payload.stats,
  };
}

function writeHistoryListCache(entry: CachedHistoryList): void {
  const { source, jobId, page, page_size: pageSize, files, total, capturedAt, stats } = entry;
  setStorageItem(makeHistoryListCacheKey(source, jobId, page, pageSize), {
    capturedAt,
    source,
    jobId,
    page,
    page_size: pageSize,
    total,
    files,
    stats,
  });
}

function normalizeHistoryListResponse(
  response: FileListResponse,
  fallbackPage: number,
  fallbackPageSize: number,
): {
  files: FileListItem[];
  total: number;
  page: number;
  page_size: number;
  stats: HistoryListStats;
} {
  const files = Array.isArray(response?.files) ? response.files : [];
  const total = typeof response?.total === 'number' ? response.total : 0;
  return {
    files,
    total,
    page: typeof response?.page === 'number' ? response.page : fallbackPage,
    page_size: typeof response?.page_size === 'number' ? response.page_size : fallbackPageSize,
    stats: normalizeHistoryListStats(response?.stats, files, total),
  };
}

function prefetchAdjacentHistoryPages(params: {
  source: SourceTab;
  jobId: string | null;
  page: number;
  pageSize: number;
  total: number;
}): void {
  const totalPages = Math.max(1, Math.ceil(params.total / params.pageSize));
  const pages = [params.page + 1, params.page - 1].filter(
    (page, index, arr) =>
      page >= 1 &&
      page <= totalPages &&
      arr.indexOf(page) === index &&
      !readHistoryListCache(params.source, params.jobId, page, params.pageSize),
  );
  if (pages.length === 0) return;

  const source = params.source === 'all' ? undefined : params.source;
  for (const page of pages) {
    void fileApi
      .list(page, params.pageSize, {
        source,
        embed_job: params.source !== 'playground',
        job_id: params.jobId || undefined,
      })
      .then((response) => {
        const result = normalizeHistoryListResponse(response, page, params.pageSize);
        writeHistoryListCache({
          capturedAt: Date.now(),
          source: params.source,
          jobId: params.jobId,
          page: Math.max(1, result.page),
          page_size: Math.max(1, result.page_size),
          total: Math.max(0, result.total),
          files: result.files.slice(0, MAX_HISTORY_LIST_CACHE_ROWS),
          stats: result.stats,
        });
      })
      .catch(() => {
        /* prefetch should never block visible pagination */
      });
  }
}

function scheduleAdjacentHistoryPrefetch(
  params: Parameters<typeof prefetchAdjacentHistoryPages>[0],
): void {
  if (import.meta.env.MODE === 'test') return;
  const schedule =
    typeof window !== 'undefined' && typeof window.setTimeout === 'function'
      ? window.setTimeout
      : setTimeout;
  schedule(() => prefetchAdjacentHistoryPages(params), 250);
}

function hasActiveHistoryRow(rows: FileListItem[]): boolean {
  return rows.some((row) =>
    HISTORY_ACTIVE_ITEM_STATUSES.has(String(row.item_status ?? '').toLowerCase()),
  );
}

function historyListSignature(rows: FileListItem[]): string {
  return rows
    .map((row) =>
      [
        row.file_id,
        row.original_filename,
        row.file_size,
        row.file_type,
        row.created_at ?? '',
        row.has_output ? '1' : '0',
        row.entity_count,
        row.upload_source ?? '',
        row.job_id ?? '',
        row.batch_group_id ?? '',
        row.batch_group_count ?? '',
        row.item_status ?? '',
        row.item_id ?? '',
        row.job_embed?.status ?? '',
        row.job_embed?.job_type ?? '',
        row.job_embed?.first_awaiting_review_item_id ?? '',
        row.job_embed?.wizard_furthest_step ?? '',
        row.job_embed?.batch_step1_configured === true ? '1' : '0',
        row.job_embed?.progress?.processing ?? '',
        row.job_embed?.progress?.awaiting_review ?? '',
        row.job_embed?.progress?.completed ?? '',
        row.job_embed?.progress?.failed ?? '',
      ].join('\x1e'),
    )
    .join('\x1f');
}

function getHistoryBatchGroupId(row: FileListItem): string | null {
  if (row.upload_source !== 'batch' && !row.batch_group_id) return null;
  return row.batch_group_id ?? row.job_id ?? row.file_id;
}

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

function normalizeHistoryPreviewItems(
  fileInfo: Record<string, unknown> | null,
): HistoryPreviewItem[] {
  if (!fileInfo) return [];
  const items: HistoryPreviewItem[] = [];
  const entities = Array.isArray(fileInfo.entities) ? fileInfo.entities : [];
  const rawBoxes = fileInfo.bounding_boxes;
  const boxes = Array.isArray(rawBoxes)
    ? rawBoxes
    : rawBoxes && typeof rawBoxes === 'object'
      ? Object.values(rawBoxes).flatMap((v) => (Array.isArray(v) ? v : []))
      : [];

  for (const entity of entities) {
    if (!entity || typeof entity !== 'object') continue;
    const entry = entity as Record<string, unknown>;
    if (entry.selected === false) continue;
    const type = typeof entry.type === 'string' && entry.type.trim() ? entry.type.trim() : 'TEXT';
    const text =
      typeof entry.text === 'string' && entry.text.trim()
        ? entry.text.trim()
        : t('history.unnamedContent');
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
    const text =
      typeof entry.text === 'string' && entry.text.trim()
        ? entry.text.trim()
        : t('history.previewImageRegion');
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

export async function blobUrlFromFileDownload(
  fileId: string,
  redacted: boolean,
  mime: string,
): Promise<string> {
  const url = fileApi.getDownloadUrl(fileId, redacted);
  return authenticatedBlobUrl(url, mime);
}

export function buildHistoryGroups(rows: FileListItem[], sourceTab: SourceTab): HistoryGroup[] {
  if (sourceTab === 'playground') {
    return rows.map((r) => ({
      kind: 'date_group' as const,
      label: t('history.singleSession').replace('{id}', r.file_id.slice(0, 8)),
      rows: [r],
    }));
  }
  const out: HistoryGroup[] = [];
  let i = 0;
  while (i < rows.length) {
    const r = rows[i];
    const bg = getHistoryBatchGroupId(r);
    if (!bg) {
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
    while (j < rows.length && getHistoryBatchGroupId(rows[j]) === bg) {
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

/* Hook */

export function useHistory() {
  const [searchParams, setSearchParams] = useSearchParams();
  const urlSource = searchParams.get('source');
  const urlJobId = searchParams.get('jobId');
  const initialSourceTab =
    urlSource === 'batch' ? 'batch' : urlSource === 'playground' ? 'playground' : 'all';
  const initialCache = readHistoryListCache(initialSourceTab, urlJobId, 1, 10, {
    allowStale: true,
  });

  const [rows, setRows] = useState<FileListItem[]>(() => initialCache?.files ?? []);
  const [total, setTotal] = useState(() => initialCache?.total ?? 0);
  const [listStats, setListStats] = useState<HistoryListStats>(() =>
    initialCache?.stats
      ? initialCache.stats
      : normalizeHistoryListStats(undefined, initialCache?.files ?? [], initialCache?.total ?? 0),
  );
  const [page, setPage] = useState(() => initialCache?.page ?? 1);
  const [pageSize, setPageSize] = useState(() => initialCache?.page_size ?? 10);
  const [displayPageSize, setDisplayPageSize] = useState(() => initialCache?.page_size ?? 10);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [initialLoading, setInitialLoading] = useState(() => initialCache === null);
  const [tableLoading, setTableLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [zipLoading, setZipLoading] = useState(false);
  const [mutationLoading, setMutationLoading] = useState(false);
  const [cleanupConfirmOpen, setCleanupConfirmOpen] = useState(false);
  const [sourceTab, setSourceTab] = useState<SourceTab>(
    urlSource === 'batch' ? 'batch' : urlSource === 'playground' ? 'playground' : 'all',
  );
  const [expandedBatchIds, setExpandedBatchIds] = useState<Set<string>>(() => new Set());
  const knownBatchIdsRef = useRef<Set<string>>(new Set());
  const [msg, setMsg] = useState<{ text: string; tone: 'ok' | 'warn' | 'err' } | null>(null);
  const [dateFilter, setDateFilter] = useState<DateFilter>('all');
  const [fileTypeFilter, setFileTypeFilter] = useState<FileTypeFilter>('all');
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');
  const [settleRefreshesRemaining, setSettleRefreshesRemaining] = useState(0);
  const pageRef = useRef(page);
  const pageSizeRef = useRef(pageSize);
  const sourceTabRef = useRef(sourceTab);
  const rowsRef = useRef<FileListItem[]>(rows);
  const listRequestSeqRef = useRef(0);
  const nextListLoadSilentRef = useRef(
    initialCache !== null && isFreshHistoryListCache(initialCache),
  );

  useEffect(() => {
    rowsRef.current = rows;
  }, [rows]);

  useEffect(() => {
    pageRef.current = page;
  }, [page]);

  useEffect(() => {
    pageSizeRef.current = pageSize;
  }, [pageSize]);

  useEffect(() => {
    sourceTabRef.current = sourceTab;
  }, [sourceTab]);

  /* Compare modal state */
  const [compareOpen, setCompareOpen] = useState(false);
  const [compareTarget, setCompareTarget] = useState<FileListItem | null>(null);
  const [compareLoading, setCompareLoading] = useState(false);
  const [compareErr, setCompareErr] = useState<string | null>(null);
  const [compareData, setCompareData] = useState<CompareData | null>(null);
  const [compareBlobUrls, setCompareBlobUrls] = useState<{
    original: string;
    redacted: string;
  } | null>(null);
  const [compareTab, setCompareTab] = useState<'preview' | 'text' | 'changes'>('preview');
  const [comparePreviewItems, setComparePreviewItems] = useState<HistoryPreviewItem[]>([]);
  const [comparePage, setComparePage] = useState(1);
  const [compareTotalPages, setCompareTotalPages] = useState(1);

  /* Confirm dialog */
  const [confirmDlg, setConfirmDlg] = useState<{
    title: string;
    message: string;
    onConfirm: () => void;
  } | null>(null);

  /* Compare helpers */

  const revokeCompareBlobs = useCallback(() => {
    setCompareBlobUrls((prev) => {
      if (prev) {
        revokeObjectUrl(prev.original);
        revokeObjectUrl(prev.redacted);
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

  const isPdfRow = useCallback((row: FileListItem) => {
    const ft = String(row.file_type ?? '').toLowerCase();
    return ft === 'pdf' || ft === 'pdf_scanned';
  }, []);

  const fetchPageImages = useCallback(async (fileId: string, page: number) => {
    const base = `/files/${encodeURIComponent(fileId)}/page-image?page=${page}`;
    const [origRes, redRes] = await Promise.all([
      authenticatedBlobUrl(`/api/v1${base}&redacted=false`),
      authenticatedBlobUrl(`/api/v1${base}&redacted=true`),
    ]);
    return { original: origRes, redacted: redRes };
  }, []);

  const openCompareModal = useCallback(
    async (row: FileListItem) => {
      revokeCompareBlobs();
      setCompareOpen(true);
      setCompareTarget(row);
      setCompareData(null);
      setCompareErr(null);
      setCompareLoading(true);
      setComparePreviewItems([]);
      setComparePage(1);
      const useBinaryPreview = isBinaryPreviewRow(row);
      setCompareTab(useBinaryPreview ? 'preview' : 'text');
      try {
        const [data, fileInfo] = await Promise.all([
          redactionApi.getComparison(row.file_id),
          fileApi.getInfo(row.file_id).catch(() => null),
        ]);
        setCompareData(data);
        setComparePreviewItems(
          normalizeHistoryPreviewItems(fileInfo as Record<string, unknown> | null),
        );
        const pageCount = Math.max(
          1,
          Number((fileInfo as Record<string, unknown> | null)?.page_count || 1),
        );
        setCompareTotalPages(pageCount);

        if (useBinaryPreview) {
          if (isPdfRow(row)) {
            // PDF: per-page PNG via /page-image endpoint
            const urls = await fetchPageImages(row.file_id, 1);
            setCompareBlobUrls(urls);
          } else {
            // Single image: download full file as blob
            const mime = previewMimeForRow(row);
            const [original, redacted] = await Promise.all([
              blobUrlFromFileDownload(row.file_id, false, mime),
              blobUrlFromFileDownload(row.file_id, true, mime),
            ]);
            setCompareBlobUrls({ original, redacted });
          }
        }
      } catch (e) {
        setCompareErr(localizeErrorMessage(e, 'history.compareFailed'));
      } finally {
        setCompareLoading(false);
      }
    },
    [revokeCompareBlobs, isPdfRow, fetchPageImages],
  );

  // When user changes compare page (PDF pagination), re-fetch page images.
  useEffect(() => {
    if (!compareOpen || !compareTarget || !isPdfRow(compareTarget) || comparePage < 1) return;
    let cancelled = false;
    fetchPageImages(compareTarget.file_id, comparePage)
      .then((urls) => {
        if (cancelled) {
          revokeObjectUrl(urls.original);
          revokeObjectUrl(urls.redacted);
          return;
        }
        setCompareBlobUrls((prev) => {
          if (prev) {
            revokeObjectUrl(prev.original);
            revokeObjectUrl(prev.redacted);
          }
          return urls;
        });
      })
      .catch(() => {
        /* keep previous */
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only refetch when page changes
  }, [comparePage]);

  useEffect(() => {
    if (!compareOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') closeCompareModal();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [compareOpen, closeCompareModal]);

  useEffect(() => () => revokeCompareBlobs(), [revokeCompareBlobs]);

  /* Data loading */

  const load = useCallback(
    async (
      isRefresh = false,
      targetPage?: number,
      targetSize?: number,
      targetSource?: SourceTab,
      options?: LoadOptions,
    ) => {
      const p = targetPage ?? pageRef.current;
      const ps = targetSize ?? pageSizeRef.current;
      const src = targetSource ?? sourceTabRef.current;
      const silent = options?.silent === true;
      const requestSeq = ++listRequestSeqRef.current;
      const hadRows = rowsRef.current.length > 0;
      if (isRefresh && !silent) setRefreshing(true);
      else if (hadRows) setTableLoading(!silent);
      else setInitialLoading(true);
      if (!silent) setMsg(null);
      try {
        const source = src === 'all' ? undefined : src;
        const res = await fileApi.list(p, ps, {
          source,
          embed_job: src !== 'playground',
          job_id: urlJobId || undefined,
        });
        const result = normalizeHistoryListResponse(res, p, ps);
        const nextRows = result.files;
        const nextTotal = result.total;
        const nextPage = result.page;
        const nextPageSize = result.page_size;
        const safePage = Math.max(1, nextPage);
        const safePageSize = Math.max(1, nextPageSize);
        const safeTotal = Math.max(0, nextTotal);
        const safeStats = result.stats;
        const safeSource = src;
        if (requestSeq !== listRequestSeqRef.current) return;
        pageRef.current = safePage;
        pageSizeRef.current = safePageSize;
        sourceTabRef.current = src;
        setRows((prev) =>
          historyListSignature(prev) === historyListSignature(nextRows) ? prev : nextRows,
        );
        setTotal(safeTotal);
        setListStats(safeStats);
        setPage(safePage);
        setPageSize(safePageSize);
        setDisplayPageSize(safePageSize);
        writeHistoryListCache({
          capturedAt: Date.now(),
          source: safeSource,
          jobId: urlJobId,
          page: safePage,
          page_size: safePageSize,
          total: safeTotal,
          files: nextRows.slice(0, MAX_HISTORY_LIST_CACHE_ROWS),
          stats: safeStats,
        });
        scheduleAdjacentHistoryPrefetch({
          source: safeSource,
          jobId: urlJobId,
          page: safePage,
          pageSize: safePageSize,
          total: safeTotal,
        });
        if (hasActiveHistoryRow(nextRows)) {
          setSettleRefreshesRemaining(2);
        } else if (isRefresh && silent) {
          setSettleRefreshesRemaining((prev) => Math.max(0, prev - 1));
        } else {
          setSettleRefreshesRemaining(0);
        }
        if (isRefresh) {
          const visibleIds = new Set(nextRows.map((row) => row.file_id));
          setSelected((prev) => new Set([...prev].filter((id) => visibleIds.has(id))));
        } else {
          setSelected(new Set());
        }
      } catch (error) {
        if (requestSeq !== listRequestSeqRef.current) return;
        if (!isRefresh && !hadRows) {
          pageRef.current = p;
          pageSizeRef.current = ps;
          setRows([]);
          setTotal(0);
          setListStats(EMPTY_HISTORY_LIST_STATS);
          setPage(p);
          setPageSize(ps);
          setSelected(new Set());
        }
        if (!silent) {
          setMsg({ text: localizeErrorMessage(error, 'history.loadFailed'), tone: 'err' });
        }
      } finally {
        if (requestSeq === listRequestSeqRef.current) {
          setInitialLoading(false);
          setTableLoading(false);
          if (isRefresh && !silent) setRefreshing(false);
        }
      }
    },
    [urlJobId],
  );

  useEffect(() => {
    const nextSourceTab =
      urlSource === 'batch' ? 'batch' : urlSource === 'playground' ? 'playground' : 'all';
    const nextJobId = urlJobId ?? null;
    const cached = readHistoryListCache(nextSourceTab, nextJobId, 1, pageSizeRef.current, {
      allowStale: true,
    });
    nextListLoadSilentRef.current = cached !== null && isFreshHistoryListCache(cached);
    if (cached) {
      setRows((prev) =>
        historyListSignature(prev) === historyListSignature(cached.files) ? prev : cached.files,
      );
      setTotal((prev) => (prev === cached.total ? prev : cached.total));
      setListStats(
        cached.stats ?? normalizeHistoryListStats(undefined, cached.files, cached.total),
      );
      setPage((prev) => (prev === cached.page ? prev : cached.page));
      setPageSize((prev) => (prev === cached.page_size ? prev : cached.page_size));
      setDisplayPageSize((prev) => (prev === cached.page_size ? prev : cached.page_size));
      setSelected(new Set());
      pageRef.current = cached.page;
      pageSizeRef.current = cached.page_size;
      setInitialLoading(false);
    } else if (rowsRef.current.length === 0) {
      nextListLoadSilentRef.current = false;
      setInitialLoading(true);
    } else {
      nextListLoadSilentRef.current = false;
    }
    sourceTabRef.current = nextSourceTab;
    pageRef.current = 1;
    setSourceTab((current) => (current === nextSourceTab ? current : nextSourceTab));
    setPage(1);
    const silent = nextListLoadSilentRef.current;
    nextListLoadSilentRef.current = false;
    void load(false, 1, pageSizeRef.current, nextSourceTab, { silent });
  }, [load, urlJobId, urlSource]);

  const shouldAutoRefresh = useMemo(
    () =>
      !initialLoading &&
      (sourceTab === 'batch' ||
        Boolean(urlJobId) ||
        hasActiveHistoryRow(rows) ||
        settleRefreshesRemaining > 0),
    [initialLoading, rows, settleRefreshesRemaining, sourceTab, urlJobId],
  );

  useEffect(() => {
    if (!shouldAutoRefresh) return;
    let cancelled = false;
    let inFlight = false;
    let timer: ReturnType<typeof window.setTimeout> | null = null;

    function clearPollTimer() {
      if (timer) {
        clearTimeout(timer);
        timer = null;
      }
    }

    const isVisible = () =>
      typeof document === 'undefined' || document.visibilityState === 'visible';

    function scheduleNextPoll() {
      if (cancelled) return;
      clearPollTimer();
      if (!isVisible()) return;
      const waitingForFirstRows =
        rowsRef.current.length === 0 && (sourceTabRef.current === 'batch' || Boolean(urlJobId));
      timer = window.setTimeout(
        () => {
          void poll();
        },
        waitingForFirstRows ? HISTORY_EMPTY_RESULT_POLL_MS : HISTORY_ACTIVE_POLL_MS,
      );
    }

    async function poll() {
      if (cancelled || inFlight) return;
      if (!isVisible()) {
        scheduleNextPoll();
        return;
      }
      inFlight = true;
      try {
        await load(true, undefined, undefined, undefined, { silent: true });
      } finally {
        inFlight = false;
        scheduleNextPoll();
      }
    }

    function handleVisibilityChange() {
      clearPollTimer();
      if (isVisible()) void poll();
    }

    if (typeof document !== 'undefined') {
      document.addEventListener('visibilitychange', handleVisibilityChange);
    }
    scheduleNextPoll();
    return () => {
      cancelled = true;
      clearPollTimer();
      if (typeof document !== 'undefined') {
        document.removeEventListener('visibilitychange', handleVisibilityChange);
      }
    };
  }, [load, shouldAutoRefresh, urlJobId]);

  /* Filter / page actions */

  const changeSourceTab = useCallback(
    (tab: SourceTab) => {
      if (tab === sourceTabRef.current) return;
      listRequestSeqRef.current += 1;
      sourceTabRef.current = tab;
      pageRef.current = 1;
      const cached = readHistoryListCache(tab, urlJobId, 1, pageSizeRef.current, {
        allowStale: true,
      });
      if (cached) {
        setRows((prev) =>
          historyListSignature(prev) === historyListSignature(cached.files) ? prev : cached.files,
        );
        setTotal((prev) => (prev === cached.total ? prev : cached.total));
        setListStats(
          cached.stats ?? normalizeHistoryListStats(undefined, cached.files, cached.total),
        );
        setPage((prev) => (prev === cached.page ? prev : cached.page));
        setPageSize((prev) => (prev === cached.page_size ? prev : cached.page_size));
        setDisplayPageSize((prev) => (prev === cached.page_size ? prev : cached.page_size));
        setSelected(new Set());
        pageRef.current = cached.page;
        pageSizeRef.current = cached.page_size;
        setInitialLoading(false);
        setTableLoading(false);
        setRefreshing(false);
      } else if (rowsRef.current.length > 0) {
        setInitialLoading(false);
        setTableLoading(true);
        setRefreshing(false);
      } else {
        setInitialLoading(true);
        setTableLoading(false);
        setRefreshing(false);
      }
      setSourceTab(tab);
      setPage(1);
      setExpandedBatchIds(new Set());
      knownBatchIdsRef.current = new Set();
      const nextParams = new URLSearchParams(searchParams);
      if (tab === 'all') nextParams.delete('source');
      else nextParams.set('source', tab);
      setSearchParams(nextParams, { replace: true });
    },
    [searchParams, setSearchParams, urlJobId],
  );

  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  const goPage = useCallback(
    (next: number) => {
      const clamped = Math.min(Math.max(1, next), totalPages);
      if (clamped === pageRef.current) return;
      listRequestSeqRef.current += 1;
      pageRef.current = clamped;
      const cached = readHistoryListCache(sourceTabRef.current, urlJobId, clamped, pageSize, {
        allowStale: true,
      });
      if (cached) {
        setRows((prev) =>
          historyListSignature(prev) === historyListSignature(cached.files) ? prev : cached.files,
        );
        setTotal((prev) => (prev === cached.total ? prev : cached.total));
        setListStats(
          cached.stats ?? normalizeHistoryListStats(undefined, cached.files, cached.total),
        );
        setPageSize((prev) => (prev === cached.page_size ? prev : cached.page_size));
        setDisplayPageSize((prev) => (prev === cached.page_size ? prev : cached.page_size));
        pageSizeRef.current = cached.page_size;
        setInitialLoading(false);
        setTableLoading(false);
        setRefreshing(false);
      }
      setPage(clamped);
      void load(false, clamped, pageSize, undefined, {
        silent: cached !== null && isFreshHistoryListCache(cached),
      });
    },
    [load, pageSize, totalPages, urlJobId],
  );

  const changePageSize = useCallback(
    (ps: number) => {
      if (ps === pageSizeRef.current) return;
      listRequestSeqRef.current += 1;
      pageSizeRef.current = ps;
      pageRef.current = 1;
      setDisplayPageSize(ps);
      const cached = readHistoryListCache(sourceTabRef.current, urlJobId, 1, ps, {
        allowStale: true,
      });
      if (cached) {
        setRows((prev) =>
          historyListSignature(prev) === historyListSignature(cached.files) ? prev : cached.files,
        );
        setTotal((prev) => (prev === cached.total ? prev : cached.total));
        setListStats(
          cached.stats ?? normalizeHistoryListStats(undefined, cached.files, cached.total),
        );
        setDisplayPageSize((prev) => (prev === cached.page_size ? prev : cached.page_size));
        setInitialLoading(false);
        setTableLoading(false);
        setRefreshing(false);
      }
      setPageSize(ps);
      setPage(1);
      load(false, 1, ps, undefined, {
        silent: cached !== null && isFreshHistoryListCache(cached),
      });
    },
    [load, urlJobId],
  );

  const toggle = useCallback((id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const filteredRows = useMemo(() => {
    let result = rows;
    if (dateFilter !== 'all') {
      const now = Date.now();
      const days = dateFilter === '7d' ? 7 : 30;
      const cutoff = now - days * 24 * 60 * 60 * 1000;
      result = result.filter((r) => r.created_at && new Date(r.created_at).getTime() >= cutoff);
    }
    if (fileTypeFilter !== 'all') {
      result = result.filter((r) => {
        const ft = String(r.file_type).toLowerCase();
        if (fileTypeFilter === 'word') return ft === 'docx' || ft === 'doc';
        if (fileTypeFilter === 'pdf') return ft === 'pdf' || ft === 'pdf_scanned';
        if (fileTypeFilter === 'image') return ft === 'image';
        return true;
      });
    }
    if (statusFilter !== 'all') {
      result = result.filter(
        (r) => resolveRedactionState(r.has_output, r.item_status) === statusFilter,
      );
    }
    return result;
  }, [rows, dateFilter, fileTypeFilter, statusFilter]);

  useEffect(() => {
    const visibleBatchIds = new Set<string>();
    for (const row of filteredRows) {
      const batchGroupId = getHistoryBatchGroupId(row);
      if (batchGroupId) visibleBatchIds.add(batchGroupId);
    }

    const previousKnownBatchIds = knownBatchIdsRef.current;
    setExpandedBatchIds((prev) => {
      let changed = false;
      const next = new Set<string>();
      for (const batchGroupId of prev) {
        if (visibleBatchIds.has(batchGroupId)) next.add(batchGroupId);
        else changed = true;
      }
      for (const batchGroupId of visibleBatchIds) {
        if (!previousKnownBatchIds.has(batchGroupId)) {
          next.add(batchGroupId);
          changed = true;
        }
      }
      if (next.size !== prev.size) changed = true;
      return changed ? next : prev;
    });
    knownBatchIdsRef.current = visibleBatchIds;
  }, [filteredRows]);

  const selectedIds = filteredRows.filter((r) => selected.has(r.file_id)).map((r) => r.file_id);
  const historyGroups = useMemo(
    () => buildHistoryGroups(filteredRows, sourceTab),
    [filteredRows, sourceTab],
  );

  const statsData = useMemo(() => {
    const sizeSum = listStats.size_bytes;
    let sizeLabel: string;
    if (sizeSum < 1024) sizeLabel = sizeSum + ' B';
    else if (sizeSum < 1024 * 1024) sizeLabel = (sizeSum / 1024).toFixed(1) + ' KB';
    else sizeLabel = (sizeSum / 1024 / 1024).toFixed(1) + ' MB';
    return {
      totalFiles: listStats.total_files,
      redactedFiles: listStats.redacted_files,
      awaitingReviewFiles: listStats.awaiting_review_files,
      entitySum: listStats.entity_sum,
      sizeLabel,
    };
  }, [listStats]);

  const hasActiveFilter =
    dateFilter !== 'all' || fileTypeFilter !== 'all' || statusFilter !== 'all';
  const clearFilters = useCallback(() => {
    setDateFilter('all');
    setFileTypeFilter('all');
    setStatusFilter('all');
  }, []);
  const allSelected = filteredRows.length > 0 && selectedIds.length === filteredRows.length;

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
    [rows],
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
    [selectedIds, downloadZipByIds],
  );

  /* Tree collapse */

  const toggleBatchCollapse = useCallback((batchGroupId: string) => {
    setExpandedBatchIds((prev) => {
      const n = new Set(prev);
      if (n.has(batchGroupId)) n.delete(batchGroupId);
      else n.add(batchGroupId);
      return n;
    });
  }, []);

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
    [load, page, pageSize],
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
    [load, page, pageSize],
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
  }, [load, mutationLoading, pageSize, zipLoading]);

  const downloadRow = useCallback(async (row: FileListItem) => {
    await downloadAuthenticatedFile(
      fileApi.getDownloadUrl(row.file_id, row.has_output),
      row.original_filename,
    );
  }, []);

  return {
    /* list data */
    rows,
    filteredRows,
    total,
    page,
    pageSize,
    displayPageSize,
    totalPages,
    historyGroups,
    statsData,
    /* loading */
    initialLoading,
    tableLoading,
    refreshing,
    zipLoading,
    mutationLoading,
    interactionLocked: zipLoading,
    /* selection */
    selected,
    setSelected,
    selectedIds,
    allSelected,
    toggle,
    /* filters */
    sourceTab,
    changeSourceTab,
    dateFilter,
    setDateFilter,
    fileTypeFilter,
    setFileTypeFilter,
    statusFilter,
    setStatusFilter,
    hasActiveFilter,
    clearFilters,
    /* pagination */
    goPage,
    changePageSize,
    /* actions */
    load,
    downloadZip,
    downloadRow,
    remove,
    removeGroup,
    toggleBatchCollapse,
    expandedBatchIds,
    /* cleanup */
    cleanupConfirmOpen,
    setCleanupConfirmOpen,
    handleCleanup,
    /* messages */
    msg,
    /* compare */
    compareOpen,
    compareTarget,
    compareLoading,
    compareErr,
    compareData,
    compareBlobUrls,
    compareTab,
    setCompareTab,
    comparePreviewItems,
    comparePage,
    setComparePage,
    compareTotalPages,
    openCompareModal,
    closeCompareModal,
    /* confirm dialog */
    confirmDlg,
    setConfirmDlg,
  };
}
