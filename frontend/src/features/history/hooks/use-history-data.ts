// Copyright 2026 DataInfra-RedactionEverything Contributors

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { fileApi } from '@/services/api';
import { HISTORY_ACTIVE_POLL_MS, HISTORY_EMPTY_RESULT_POLL_MS } from '@/constants/timing';
import { getStorageItem, scopedStorageKey, setStorageItem } from '@/lib/storage';
import { localizeErrorMessage } from '@/utils/localizeError';
import type { FileListItem, FileListResponse } from '@/types';
import { useSearchParams } from 'react-router-dom';

export type SourceTab = 'all' | 'playground' | 'batch';

export type HistoryMessage = { text: string; tone: 'ok' | 'warn' | 'err' };

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

export type HistoryListStats = {
  total_files: number;
  redacted_files: number;
  awaiting_review_files: number;
  unredacted_files: number;
  entity_sum: number;
  size_bytes: number;
};

export const EMPTY_HISTORY_LIST_STATS: HistoryListStats = {
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
  // Owner-scoped (same pattern as presets): switching accounts naturally
  // misses the previous user's cache entries.
  return scopedStorageKey(
    `${HISTORY_LIST_CACHE_PREFIX}:${source}:${encodeURIComponent(safeJobId)}:${page}:${pageSize}`,
  );
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

export function useHistoryData() {
  const [searchParams, setSearchParams] = useSearchParams();
  const urlSource = searchParams.get('source');
  const urlJobId = searchParams.get('jobId');
  const initialSourceTab =
    urlSource === 'batch' ? 'batch' : urlSource === 'playground' ? 'playground' : 'all';
  // Lazy init: avoid a synchronous localStorage read + JSON.parse on every render.
  const [initialCache] = useState(() =>
    readHistoryListCache(initialSourceTab, urlJobId, 1, 10, {
      allowStale: true,
    }),
  );

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
  const [sourceTab, setSourceTab] = useState<SourceTab>(
    urlSource === 'batch' ? 'batch' : urlSource === 'playground' ? 'playground' : 'all',
  );
  const [expandedBatchIds, setExpandedBatchIds] = useState<Set<string>>(() => new Set());
  const knownBatchIdsRef = useRef<Set<string>>(new Set());
  const [msg, setMsg] = useState<HistoryMessage | null>(null);
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

  /* Tree collapse */

  const toggleBatchCollapse = useCallback((batchGroupId: string) => {
    setExpandedBatchIds((prev) => {
      const n = new Set(prev);
      if (n.has(batchGroupId)) n.delete(batchGroupId);
      else n.add(batchGroupId);
      return n;
    });
  }, []);

  return {
    /* list data */
    rows,
    setRows,
    total,
    setTotal,
    listStats,
    setListStats,
    statsData,
    page,
    setPage,
    pageSize,
    displayPageSize,
    totalPages,
    /* loading */
    initialLoading,
    tableLoading,
    refreshing,
    /* selection */
    selected,
    setSelected,
    toggle,
    /* source tab */
    sourceTab,
    changeSourceTab,
    /* batch tree */
    expandedBatchIds,
    setExpandedBatchIds,
    knownBatchIdsRef,
    toggleBatchCollapse,
    /* messages */
    msg,
    setMsg,
    /* loading actions */
    load,
    goPage,
    changePageSize,
  };
}
