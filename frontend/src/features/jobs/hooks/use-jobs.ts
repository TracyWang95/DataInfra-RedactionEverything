// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { useCallback, useEffect, useMemo, useState } from 'react';
import { authFetch } from '@/services/api-client';
import { t } from '@/i18n';
import { JOBS_LIST_POLL_MS } from '@/constants/timing';
import {
  deleteJob,
  getJobsBatch,
  listJobs,
  requeueFailed,
  type JobDetail,
  type JobProgress,
  type JobSummary,
  type JobTypeApi,
} from '@/services/jobsApi';
import { showToast } from '@/components/Toast';
import { localizeErrorMessage } from '@/utils/localizeError';

const PAGE_SIZE_OPTIONS = [10, 20, 50, 100] as const;
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
        job.progress.awaiting_review,
        job.progress.completed,
        job.progress.failed,
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
  const processing = progress.parsing + progress.ner + progress.vision;
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
  const [tab, setTab] = useState<JobTypeApi | 'all'>('all');
  const [rows, setRows] = useState<JobSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [jumpPage, setJumpPage] = useState('');
  const [loading, setLoading] = useState(true);
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

  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  const load = useCallback(
    async (opts?: { targetPage?: number; targetPageSize?: number }) => {
      const targetPage = opts?.targetPage ?? page;
      const targetPageSize = opts?.targetPageSize ?? pageSize;
      const hasRows = rows.length > 0;
      if (hasRows) setRefreshing(true);
      else setLoading(true);
      setErr(null);
      try {
        const jobType = tab === 'all' ? undefined : tab;
        let result = await listJobs({
          job_type: jobType,
          page: targetPage,
          page_size: targetPageSize,
        });
        result = {
          ...result,
          jobs: Array.isArray(result?.jobs) ? result.jobs : [],
          total: typeof result?.total === 'number' ? result.total : 0,
          page: typeof result?.page === 'number' ? result.page : targetPage,
          page_size: typeof result?.page_size === 'number' ? result.page_size : targetPageSize,
        };
        const resolvedTotalPages = Math.max(1, Math.ceil(result.total / result.page_size));
        if (targetPage > resolvedTotalPages && result.total > 0) {
          result = await listJobs({
            job_type: jobType,
            page: resolvedTotalPages,
            page_size: targetPageSize,
          });
          result = {
            ...result,
            jobs: Array.isArray(result?.jobs) ? result.jobs : [],
            total: typeof result?.total === 'number' ? result.total : 0,
            page: typeof result?.page === 'number' ? result.page : resolvedTotalPages,
            page_size: typeof result?.page_size === 'number' ? result.page_size : targetPageSize,
          };
        }
        setRows((prev) =>
          jobsPollSignature(prev) === jobsPollSignature(result.jobs) ? prev : result.jobs,
        );
        setTotal((prev) => (prev === result.total ? prev : result.total));
        setPage((prev) => (prev === result.page ? prev : result.page));
        setPageSize((prev) => (prev === result.page_size ? prev : result.page_size));
        return result;
      } catch (error) {
        setErr(localizeErrorMessage(error, 'jobs.loadFailed'));
        if (!hasRows) {
          setRows([]);
          setTotal(0);
          setPage(targetPage);
          setPageSize(targetPageSize);
        }
        return null;
      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    [page, pageSize, rows.length, tab],
  );

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
    void load();
  }, [load]);

  useEffect(() => {
    const hasActiveJobs = rows.some(
      (j) => !['completed', 'failed', 'cancelled', 'draft'].includes(j.status),
    );
    if (!hasActiveJobs) return;
    const tick = () => {
      if (document.visibilityState === 'visible') void load();
    };
    const timer = setInterval(tick, JOBS_LIST_POLL_MS);
    document.addEventListener('visibilitychange', tick);
    return () => {
      clearInterval(timer);
      document.removeEventListener('visibilitychange', tick);
    };
  }, [rows, load]);

  const refreshList = useCallback(async () => {
    const result = await load({ targetPage: page });
    if (!result) return;
    const expandedVisibleIds = [...expandedJobIds].filter((id) =>
      result.jobs.some((job) => job.id === id),
    );
    if (expandedVisibleIds.length > 0) await fetchJobDetails(expandedVisibleIds);
  }, [expandedJobIds, fetchJobDetails, load, page]);

  const goPage = (next: number) => {
    const clamped = Math.min(Math.max(1, next), totalPages);
    if (clamped === page) return;
    setPage(clamped);
    setJumpPage('');
  };

  const changePageSize = (next: number) => {
    if (next === pageSize) return;
    setPageSize(next);
    setPage(1);
    setJumpPage('');
  };

  const changeTab = (next: JobTypeApi | 'all') => {
    if (next === tab) return;
    setTab(next);
    setPage(1);
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
      if (!canDeleteJob(job.status) || deletingJobId) return;
      setDeleteCandidate(job);
    },
    [deletingJobId],
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
      void refreshList();
    } catch {
      showToast(t('safety.cleanup.failed'), 'error');
    }
  }, [refreshList]);

  const visibleRows = useMemo(() => rows, [rows]);
  const tableBusy = loading || refreshing || deletingJobId !== null;
  const rangeStart = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const rangeEnd = total === 0 ? 0 : Math.min(page * pageSize, total);

  const pageMetrics = useMemo(
    () =>
      visibleRows.reduce(
        (acc, job) => {
          if (job.status === 'draft') acc.draft += 1;
          else if (ACTIVE_STATUSES.has(job.status)) acc.processing += 1;
          else if (job.status === 'awaiting_review') acc.awaitingReview += 1;
          else if (job.status === 'completed') acc.completed += 1;
          else if (job.status === 'failed' || job.status === 'cancelled') acc.risk += 1;
          return acc;
        },
        { draft: 0, processing: 0, awaitingReview: 0, completed: 0, risk: 0 },
      ),
    [visibleRows],
  );

  return {
    tab,
    rows: visibleRows,
    total,
    page,
    pageSize,
    jumpPage,
    loading,
    refreshing,
    cleanupConfirmOpen,
    err,
    notice,
    deletingJobId,
    deleteCandidate,
    expandedJobIds,
    jobDetails,
    detailLoadingIds,
    requeueingJobId,
    totalPages,
    tableBusy,
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
