// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { authFetch } from '@/services/api-client';
import { t } from '@/i18n';
import { JOBS_LIST_POLL_HIDDEN_MS, JOBS_LIST_POLL_MS } from '@/constants/timing';
import {
  deleteJob,
  getJobsBatch,
  listJobs,
  requeueFailed,
  type JobDetail,
  type JobListStats,
  type JobProgress,
  type JobStatusFilterApi,
  type JobSummary,
} from '@/services/jobsApi';
import { showToast } from '@/components/Toast';
import { localizeErrorMessage } from '@/utils/localizeError';
import { getStorageItem, setStorageItem } from '@/lib/storage';

const PAGE_SIZE_OPTIONS = [10, 20] as const;
export type JobsStatusFilter = JobStatusFilterApi | 'all';
const DELETABLE_STATUSES = new Set([
  'draft',
  'awaiting_review',
  'completed',
  'failed',
  'cancelled',
]);
const ACTIVE_STATUSES = new Set(['queued', 'running', 'redacting', 'processing']);

export { PAGE_SIZE_OPTIONS, ACTIVE_STATUSES };

export function canDeleteJob(status: string): boolean {
  return DELETABLE_STATUSES.has(status);
}

export function hasRefreshableJobWork(job: Pick<JobSummary, 'status' | 'progress'>): boolean {
  if (ACTIVE_STATUSES.has(job.status)) return true;
  if (['completed', 'failed', 'cancelled', 'draft'].includes(job.status)) return false;
  const progress = job.progress;
  return (
    progress.pending +
      progress.queued +
      progress.processing +
      progress.parsing +
      progress.ner +
      progress.vision +
      progress.review_approved +
      progress.redacting >
    0
  );
}

type CachedJobsList = {
  capturedAt: number;
  tab: JobsStatusFilter;
  page: number;
  pageSize: number;
  total: number;
  jobs: JobSummary[];
  stats?: JobListStats;
};

const EMPTY_JOB_LIST_STATS: JobListStats = {
  total_jobs: 0,
  draft_jobs: 0,
  active_jobs: 0,
  awaiting_review_jobs: 0,
  completed_jobs: 0,
  risk_jobs: 0,
  total_items: 0,
  active_items: 0,
  awaiting_review_items: 0,
  completed_items: 0,
  risk_items: 0,
};

const JOBS_LIST_CACHE_PREFIX = 'jobs:list-cache:v1';
const JOBS_LIST_CACHE_TTL_MS = 30_000;
const MAX_JOBS_LIST_CACHE_ROWS = 120;

function makeJobsListCacheKey(tab: JobsStatusFilter, page: number, pageSize: number): string {
  return `${JOBS_LIST_CACHE_PREFIX}:${tab}:${page}:${pageSize}`;
}

function isFreshJobsListCache(entry: CachedJobsList): boolean {
  return Date.now() - entry.capturedAt <= JOBS_LIST_CACHE_TTL_MS;
}

function readJobsListCache(
  tab: JobsStatusFilter,
  page: number,
  pageSize: number,
  opts?: { allowStale?: boolean },
): CachedJobsList | null {
  const payload = getStorageItem<CachedJobsList | null>(
    makeJobsListCacheKey(tab, page, pageSize),
    null,
  );
  if (!payload || !Array.isArray(payload.jobs)) return null;
  if (typeof payload.capturedAt !== 'number') return null;
  if (!opts?.allowStale && !isFreshJobsListCache(payload)) return null;
  if (payload.jobs.length > MAX_JOBS_LIST_CACHE_ROWS) return null;
  return {
    capturedAt: payload.capturedAt,
    tab: payload.tab,
    page: payload.page,
    pageSize: payload.pageSize,
    total: payload.total,
    jobs: payload.jobs,
    stats: payload.stats,
  };
}

function writeJobsListCache(entry: CachedJobsList): void {
  const { tab, page, pageSize, total, jobs, capturedAt } = entry;
  setStorageItem(makeJobsListCacheKey(tab, page, pageSize), {
    capturedAt,
    tab,
    page,
    pageSize,
    total,
    jobs,
    stats: entry.stats,
  });
}

function normalizeJobsListResult(
  result: Awaited<ReturnType<typeof listJobs>>,
  fallbackPage: number,
  fallbackPageSize: number,
) {
  return {
    ...result,
    jobs: Array.isArray(result?.jobs) ? result.jobs : [],
    total: typeof result?.total === 'number' ? result.total : 0,
    page: typeof result?.page === 'number' ? result.page : fallbackPage,
    page_size: typeof result?.page_size === 'number' ? result.page_size : fallbackPageSize,
    stats: result.stats ?? EMPTY_JOB_LIST_STATS,
  };
}

function prefetchAdjacentJobsPages(params: {
  tab: JobsStatusFilter;
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
      !readJobsListCache(params.tab, page, params.pageSize),
  );
  if (pages.length === 0) return;

  const status = params.tab === 'all' ? undefined : params.tab;
  for (const page of pages) {
    void listJobs({ status, page, page_size: params.pageSize })
      .then((response) => {
        const result = normalizeJobsListResult(response, page, params.pageSize);
        writeJobsListCache({
          capturedAt: Date.now(),
          tab: params.tab,
          page: Math.max(1, result.page),
          pageSize: Math.max(1, result.page_size),
          total: Math.max(0, result.total),
          jobs: result.jobs.slice(0, MAX_JOBS_LIST_CACHE_ROWS),
          stats: result.stats,
        });
      })
      .catch(() => {
        /* keep interactive pagination independent of prefetch failures */
      });
  }
}

function scheduleAdjacentJobsPrefetch(params: Parameters<typeof prefetchAdjacentJobsPages>[0]): void {
  if (import.meta.env.MODE === 'test') return;
  const schedule =
    typeof window !== 'undefined' && typeof window.setTimeout === 'function'
      ? window.setTimeout
      : setTimeout;
  schedule(() => prefetchAdjacentJobsPages(params), 250);
}

function jobsPollSignature(jobs: JobSummary[]): string {
  return jobs
    .map((job) => {
      const ids = job.config?.entity_type_ids;
      const entityTypes =
        Array.isArray(ids) && ids.every((x): x is string => typeof x === 'string')
          ? [...ids].sort().join(',')
          : '';
      return [
        job.id,
        job.status,
        job.updated_at,
        job.title ?? '',
        job.progress.total_items,
        job.progress.processing,
        job.progress.queued,
        job.progress.parsing,
        job.progress.ner,
        job.progress.vision,
        job.progress.awaiting_review,
        job.progress.review_approved,
        job.progress.redacting,
        job.progress.completed,
        job.progress.failed,
        job.progress.cancelled ?? 0,
        job.nav_hints?.item_count ?? '',
        job.nav_hints?.wizard_furthest_step ?? '',
        job.nav_hints?.batch_step1_configured === true ? '1' : '0',
        job.nav_hints?.first_awaiting_review_item_id ?? '',
        entityTypes,
      ].join('\x1e');
    })
    .join('\x1f');
}

export function buildProgressHeadline(
  progress: JobProgress,
  navHints?: { redacted_count?: number | null; awaiting_review_count?: number | null } | null,
): string {
  const redacted = navHints?.redacted_count ?? progress.completed;
  const awaiting = navHints?.awaiting_review_count ?? progress.awaiting_review;
  const parts = [
    t('jobs.headlineRedacted').replace('{n}', String(redacted)),
    t('jobs.headlineAwaiting').replace('{n}', String(awaiting)),
  ];
  if (progress.failed > 0) parts.push(t('jobs.abnormal').replace('{n}', String(progress.failed)));
  return parts.join(' \u00b7');
}

export function buildProgressSummary(
  progress: JobProgress,
  itemCount: number,
  finishedCount: number,
): string {
  if (itemCount <= 0) return t('jobs.noFilesInJob');
  if (finishedCount >= itemCount) return t('jobs.allFilesProcessed');

  const waiting = progress.pending + progress.queued;
  const processing = progress.processing + progress.parsing + progress.ner + progress.vision;
  const review = progress.awaiting_review;
  const generating = progress.review_approved + progress.redacting;
  const failed = progress.failed;
  const cancelled = progress.cancelled ?? 0;

  const parts = [
    waiting > 0 ? t('jobs.pending').replace('{n}', String(waiting)) : null,
    processing > 0 ? t('jobs.recognizing').replace('{n}', String(processing)) : null,
    review > 0 ? t('jobs.awaitingReviewCount').replace('{n}', String(review)) : null,
    generating > 0 ? t('jobs.generating').replace('{n}', String(generating)) : null,
    failed > 0 ? t('jobs.abnormal').replace('{n}', String(failed)) : null,
    cancelled > 0 ? t('jobs.cancelledCount').replace('{n}', String(cancelled)) : null,
  ].filter((part): part is string => Boolean(part));

  if (parts.length === 0) {
    return finishedCount > 0
      ? t('jobs.completedCount').replace('{n}', String(finishedCount))
      : t('jobs.waitingProcessing');
  }
  return parts.slice(0, 3).join(' \u00b7');
}

export function useJobs() {
  const initialJobsCache = readJobsListCache('all', 1, 10, { allowStale: true });
  const [tab, setTab] = useState<JobsStatusFilter>('all');
  const [rows, setRows] = useState<JobSummary[]>(() => initialJobsCache?.jobs ?? []);
  const [total, setTotal] = useState(() => initialJobsCache?.total ?? 0);
  const [listStats, setListStats] = useState<JobListStats>(
    () => initialJobsCache?.stats ?? EMPTY_JOB_LIST_STATS,
  );
  const [page, setPage] = useState(() => initialJobsCache?.page ?? 1);
  const [pageSize, setPageSize] = useState(() => initialJobsCache?.pageSize ?? 10);
  const [rowsPageSize, setRowsPageSize] = useState(() => initialJobsCache?.pageSize ?? 10);
  const [jumpPage, setJumpPage] = useState('');
  const [loading, setLoading] = useState(() => initialJobsCache === null);
  const [tableLoading, setTableLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [cleanupConfirmOpen, setCleanupConfirmOpen] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [deletingJobId, setDeletingJobId] = useState<string | null>(null);
  const [deleteCandidate, setDeleteCandidate] = useState<JobSummary | null>(null);
  const [expandedJobIds, setExpandedJobIds] = useState<Set<string>>(() => new Set());
  const [jobDetails, setJobDetails] = useState<Record<string, JobDetail>>({});
  const [detailLoadingIds, setDetailLoadingIds] = useState<Set<string>>(() => new Set());
  const [requeueingJobId, setRequeuingJobId] = useState<string | null>(null);
  const [cleanupLoading, setCleanupLoading] = useState(false);
  const rowsRef = useRef<JobSummary[]>(rows);
  const listRequestSeqRef = useRef(0);
  const nextListLoadSilentRef = useRef(
    initialJobsCache !== null && isFreshJobsListCache(initialJobsCache),
  );

  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const hasActiveJobs = useMemo(() => rows.some(hasRefreshableJobWork), [rows]);

  useEffect(() => {
    rowsRef.current = rows;
  }, [rows]);

  const load = useCallback(
    async (opts?: { targetPage?: number; targetPageSize?: number; silent?: boolean }) => {
      const targetPage = opts?.targetPage ?? page;
      const targetPageSize = opts?.targetPageSize ?? pageSize;
      const silent = opts?.silent === true;
      const requestSeq = ++listRequestSeqRef.current;
      const hasRows = rowsRef.current.length > 0;
      if (!hasRows) {
        setLoading(true);
      } else if (!silent) {
        setRefreshing(true);
        setTableLoading(true);
      }
      if (!silent) setErr(null);
      try {
        const status = tab === 'all' ? undefined : tab;
        let result = normalizeJobsListResult(
          await listJobs({
            status,
            page: targetPage,
            page_size: targetPageSize,
          }),
          targetPage,
          targetPageSize,
        );
        const resolvedTotalPages = Math.max(1, Math.ceil(result.total / result.page_size));
        if (targetPage > resolvedTotalPages && result.total > 0) {
          result = normalizeJobsListResult(
            await listJobs({
              status,
              page: resolvedTotalPages,
              page_size: targetPageSize,
            }),
            resolvedTotalPages,
            targetPageSize,
          );
        }
        if (requestSeq !== listRequestSeqRef.current) return null;
        const safePage = Math.max(1, result.page);
        const safePageSize = Math.max(1, result.page_size);
        const safeTotal = Math.max(0, result.total);
        setRows((prev) =>
          jobsPollSignature(prev) === jobsPollSignature(result.jobs) ? prev : result.jobs,
        );
        setRowsPageSize((prev) => (prev === safePageSize ? prev : safePageSize));
        setTotal((prev) => (prev === safeTotal ? prev : safeTotal));
        setListStats(result.stats ?? EMPTY_JOB_LIST_STATS);
        setPage((prev) => (prev === safePage ? prev : safePage));
        setPageSize((prev) => (prev === safePageSize ? prev : safePageSize));
        writeJobsListCache({
          capturedAt: Date.now(),
          tab,
          page: safePage,
          pageSize: safePageSize,
          total: safeTotal,
          jobs: result.jobs.slice(0, MAX_JOBS_LIST_CACHE_ROWS),
          stats: result.stats,
        });
        scheduleAdjacentJobsPrefetch({
          tab,
          page: safePage,
          pageSize: safePageSize,
          total: safeTotal,
        });
        return {
          ...result,
          total: safeTotal,
          page: safePage,
          page_size: safePageSize,
        };
      } catch (error) {
        if (requestSeq !== listRequestSeqRef.current) return null;
        if (!silent) setErr(localizeErrorMessage(error, 'jobs.loadFailed'));
        if (!hasRows) {
          setRows([]);
          setTotal(0);
          setListStats(EMPTY_JOB_LIST_STATS);
          setPage(targetPage);
          setPageSize(targetPageSize);
        }
        return null;
      } finally {
        if (requestSeq === listRequestSeqRef.current) {
          setLoading(false);
          setRefreshing(false);
          setTableLoading(false);
        }
      }
    },
    [page, pageSize, tab],
  );

  const showCachedJobsList = useCallback((entry: CachedJobsList) => {
    setRows((prev) =>
      jobsPollSignature(prev) === jobsPollSignature(entry.jobs) ? prev : entry.jobs,
    );
    setRowsPageSize((prev) => (prev === entry.pageSize ? prev : entry.pageSize));
    setTotal((prev) => (prev === entry.total ? prev : entry.total));
    setListStats(entry.stats ?? EMPTY_JOB_LIST_STATS);
    setPage((prev) => (prev === entry.page ? prev : entry.page));
    setPageSize((prev) => (prev === entry.pageSize ? prev : entry.pageSize));
    setLoading(false);
    setRefreshing(false);
    setTableLoading(false);
  }, []);

  const fetchJobDetails = useCallback(async (jobIds: string[]) => {
    const ids = [...new Set(jobIds)].filter(Boolean);
    if (ids.length === 0) return;
    setDetailLoadingIds((prev) => {
      const next = new Set(prev);
      ids.forEach((id) => next.add(id));
      return next;
    });
    const patch: Record<string, JobDetail> = {};
    let firstError: string | null = null;
    try {
      const { jobs } = await getJobsBatch(ids);
      for (const detail of jobs) {
        patch[detail.id] = detail;
      }
    } catch (err) {
      firstError = localizeErrorMessage(err, 'jobs.expandFailed');
    }
    if (Object.keys(patch).length > 0) {
      setJobDetails((prev) => ({ ...prev, ...patch }));
      setRows((prev) =>
        prev.map((job): JobSummary => {
          const detail = patch[job.id];
          if (!detail?.items) return job;
          let r = 0,
            a = 0;
          for (const it of detail.items) {
            if (it.has_output) r++;
            else if (['awaiting_review', 'review_approved', 'completed'].includes(it.status)) a++;
          }
          return {
            ...job,
            nav_hints: {
              ...job.nav_hints,
              redacted_count: r,
              awaiting_review_count: a,
            } as JobSummary['nav_hints'],
          };
        }),
      );
    }
    if (firstError) setErr(firstError);
    setDetailLoadingIds((prev) => {
      const next = new Set(prev);
      ids.forEach((id) => next.delete(id));
      return next;
    });
  }, []);

  useEffect(() => {
    const silent = nextListLoadSilentRef.current;
    nextListLoadSilentRef.current = false;
    void load({ silent });
  }, [load]);

  useEffect(() => {
    if (!hasActiveJobs) return;
    let cancelled = false;
    let inFlight = false;
    let timer: ReturnType<typeof window.setTimeout> | null = null;

    const clearPollTimer = () => {
      if (timer) {
        clearTimeout(timer);
        timer = null;
      }
    };

    const scheduleNextPoll = () => {
      if (cancelled) return;
      clearPollTimer();
      const hidden = typeof document !== 'undefined' && document.visibilityState !== 'visible';
      timer = window.setTimeout(
        () => {
          void poll();
        },
        hidden ? JOBS_LIST_POLL_HIDDEN_MS : JOBS_LIST_POLL_MS,
      );
    };

    const poll = async () => {
      if (cancelled || inFlight) return;
      if (typeof document !== 'undefined' && document.visibilityState !== 'visible') {
        scheduleNextPoll();
        return;
      }
      inFlight = true;
      try {
        await load({ silent: true });
      } finally {
        inFlight = false;
        scheduleNextPoll();
      }
    };

    const handleVisibilityChange = () => {
      clearPollTimer();
      if (typeof document !== 'undefined' && document.visibilityState === 'visible') {
        void poll();
      } else {
        scheduleNextPoll();
      }
    };
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
  }, [hasActiveJobs, load]);

  const refreshList = useCallback(async () => {
    const result = await load({ targetPage: page, silent: false });
    if (!result) return;
    const expandedVisibleIds = [...expandedJobIds].filter((id) =>
      result.jobs.some((job) => job.id === id),
    );
    if (expandedVisibleIds.length > 0) await fetchJobDetails(expandedVisibleIds);
  }, [expandedJobIds, fetchJobDetails, load, page]);

  const goPage = (next: number) => {
    const clamped = Math.min(Math.max(1, next), totalPages);
    if (clamped === page) return;
    const cached = readJobsListCache(tab, clamped, pageSize, { allowStale: true });
    nextListLoadSilentRef.current = cached !== null && isFreshJobsListCache(cached);
    listRequestSeqRef.current += 1;
    setErr(null);
    setLoading(false);
    if (cached) {
      showCachedJobsList(cached);
      if (!isFreshJobsListCache(cached)) {
        setRefreshing(true);
        setTableLoading(true);
      }
    } else {
      setRefreshing(true);
      setTableLoading(true);
      setPage(clamped);
    }
    setJumpPage('');
  };

  const changePageSize = (next: number) => {
    if (next === pageSize) return;
    const cached = readJobsListCache(tab, 1, next, { allowStale: true });
    nextListLoadSilentRef.current = cached !== null && isFreshJobsListCache(cached);
    listRequestSeqRef.current += 1;
    setErr(null);
    setLoading(false);
    if (cached) {
      showCachedJobsList(cached);
      if (!isFreshJobsListCache(cached)) {
        setRefreshing(true);
        setTableLoading(true);
      }
    } else {
      setRefreshing(true);
      setTableLoading(true);
      setPageSize(next);
      setPage(1);
    }
    setJumpPage('');
  };

  const changeTab = (next: JobsStatusFilter) => {
    if (next === tab) return;
    const cached = readJobsListCache(next, 1, pageSize, { allowStale: true });
    nextListLoadSilentRef.current = cached !== null && isFreshJobsListCache(cached);
    listRequestSeqRef.current += 1;
    setErr(null);
    setLoading(false);
    if (cached) {
      showCachedJobsList(cached);
      if (!isFreshJobsListCache(cached)) {
        setRefreshing(true);
        setTableLoading(true);
      }
    } else {
      setRefreshing(true);
      setTableLoading(true);
      setPage(1);
    }
    setTab(next);
    setJumpPage('');
  };

  const toggleExpand = useCallback(
    async (job: JobSummary) => {
      const itemCount = job.nav_hints?.item_count ?? job.progress.total_items;
      if (itemCount <= 0) return;
      const opening = !expandedJobIds.has(job.id);
      setExpandedJobIds((prev) => {
        const next = new Set(prev);
        if (opening) next.add(job.id);
        else next.delete(job.id);
        return next;
      });
      if (opening && !jobDetails[job.id] && !detailLoadingIds.has(job.id))
        await fetchJobDetails([job.id]);
    },
    [detailLoadingIds, expandedJobIds, fetchJobDetails, jobDetails],
  );

  const requestDelete = useCallback(
    (job: JobSummary) => {
      if (!canDeleteJob(job.status) || deletingJobId || requeueingJobId || cleanupLoading) return;
      setDeleteCandidate(job);
    },
    [cleanupLoading, deletingJobId, requeueingJobId],
  );

  const cancelDelete = useCallback(() => {
    setDeleteCandidate(null);
  }, []);

  const confirmDelete = useCallback(async () => {
    if (!deleteCandidate || deletingJobId) return;
    const job = deleteCandidate;
    const title = job.title?.trim() || t('jobs.unnamedTask');
    setDeleteCandidate(null);
    setDeletingJobId(job.id);
    setNotice(null);
    setErr(null);
    try {
      await deleteJob(job.id);
      setExpandedJobIds((prev) => {
        const next = new Set(prev);
        next.delete(job.id);
        return next;
      });
      setJobDetails((prev) => {
        const next = { ...prev };
        delete next[job.id];
        return next;
      });
      setNotice(t('jobs.deletedNotice').replace('{title}', title));
      const nextPage = rows.length === 1 && page > 1 ? page - 1 : page;
      if (nextPage !== page) setPage(nextPage);
      else await refreshList();
    } catch (e) {
      setErr(localizeErrorMessage(e, 'jobs.deleteFailed'));
    } finally {
      setDeletingJobId(null);
    }
  }, [deleteCandidate, deletingJobId, page, refreshList, rows.length]);

  const onRequeueFailed = useCallback(
    async (job: JobSummary) => {
      if (job.progress.failed <= 0 || requeueingJobId) return;
      setRequeuingJobId(job.id);
      setNotice(null);
      setErr(null);
      try {
        await requeueFailed(job.id);
        setNotice(t('jobs.requeuedNotice').replace('{n}', String(job.progress.failed)));
        await refreshList();
      } catch (e) {
        setErr(localizeErrorMessage(e, 'jobs.requeueFailed'));
      } finally {
        setRequeuingJobId(null);
      }
    },
    [requeueingJobId, refreshList],
  );

  const onCleanup = useCallback(async () => {
    if (cleanupLoading || deletingJobId || requeueingJobId) return;
    setCleanupConfirmOpen(false);
    setCleanupLoading(true);
    setRows([]);
    setTotal(0);
    setListStats(EMPTY_JOB_LIST_STATS);
    setPage(1);
    setErr(null);
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
      void refreshList();
    } finally {
      setCleanupLoading(false);
    }
  }, [cleanupLoading, deletingJobId, refreshList, requeueingJobId]);

  const visibleRows = useMemo(() => rows, [rows]);
  const interactionLocked = deletingJobId !== null || requeueingJobId !== null;
  const tableBusy = loading || refreshing || tableLoading || interactionLocked;
  const rangeStart = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const rangeEnd = total === 0 ? 0 : Math.min(page * pageSize, total);

  const pageMetrics = useMemo(
    () => ({
      totalJobs: listStats.total_jobs,
      activeJobs: listStats.active_jobs,
      awaitingReviewItems: listStats.awaiting_review_items,
      completedItems: listStats.completed_items,
      riskItems: listStats.risk_items,
    }),
    [listStats],
  );

  return {
    tab,
    rows: visibleRows,
    total,
    page,
    pageSize,
    rowsPageSize,
    jumpPage,
    loading,
    tableLoading,
    refreshing,
    cleanupConfirmOpen,
    err,
    notice,
    deletingJobId,
    cleanupLoading,
    deleteCandidate,
    expandedJobIds,
    jobDetails,
    detailLoadingIds,
    requeueingJobId,
    totalPages,
    tableBusy,
    interactionLocked,
    rangeStart,
    rangeEnd,
    pageMetrics,

    changeTab,
    refreshList,
    goPage,
    changePageSize,
    setJumpPage,
    toggleExpand,
    requestDelete,
    cancelDelete,
    confirmDelete,
    onRequeueFailed,
    onCleanup,
    setCleanupConfirmOpen,
  };
}
