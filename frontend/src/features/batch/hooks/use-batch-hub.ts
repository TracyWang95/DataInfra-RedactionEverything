// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { getStorageItem, setStorageItem } from '@/lib/storage';
import type { BatchWizardMode } from '@/services/batchPipeline';
import { listJobs, type JobSummary } from '@/services/jobsApi';
import { resolveJobPrimaryNavigation } from '@/utils/jobPrimaryNavigation';
import { buildPreviewBatchRoute } from '../lib/batch-preview-fixtures';

function isActiveJob(status: string): boolean {
  return ['draft', 'queued', 'processing', 'running', 'awaiting_review', 'redacting'].includes(
    status,
  );
}

const BATCH_HUB_RECENT_JOBS_CACHE_PREFIX = 'batch-hub:active-jobs:v1';
const BATCH_HUB_RECENT_JOBS_TTL_MS = 30_000;
const BATCH_HUB_RECENT_JOBS_LIMIT = 20;

type CachedActiveJobs = {
  capturedAt: number;
  jobs: JobSummary[];
};

function readActiveJobsCache(): CachedActiveJobs | null {
  const payload = getStorageItem<CachedActiveJobs | null>(BATCH_HUB_RECENT_JOBS_CACHE_PREFIX, null);
  if (!payload || !Array.isArray(payload.jobs)) return null;
  if (typeof payload.capturedAt !== 'number') return null;
  if (Date.now() - payload.capturedAt > BATCH_HUB_RECENT_JOBS_TTL_MS) return null;
  if (payload.jobs.length > BATCH_HUB_RECENT_JOBS_LIMIT) return null;
  return {
    capturedAt: payload.capturedAt,
    jobs: payload.jobs.slice(0, BATCH_HUB_RECENT_JOBS_LIMIT),
  };
}

function writeActiveJobsCache(jobs: JobSummary[]): void {
  setStorageItem(BATCH_HUB_RECENT_JOBS_CACHE_PREFIX, {
    capturedAt: Date.now(),
    jobs: jobs.slice(0, BATCH_HUB_RECENT_JOBS_LIMIT),
  });
}

function sortJobsByUpdatedAt(jobs: JobSummary[]): JobSummary[] {
  return [...jobs].sort((left, right) => {
    const leftTime = left.updated_at ? Date.parse(left.updated_at) : 0;
    const rightTime = right.updated_at ? Date.parse(right.updated_at) : 0;
    return rightTime - leftTime;
  });
}

function batchHubJobsSignature(jobs: JobSummary[]): string {
  return jobs
    .map((job) =>
      [
        job.id,
        job.status,
        job.updated_at,
        job.title ?? '',
        job.progress.total_items,
        job.progress.processing,
        job.progress.queued,
        job.progress.awaiting_review,
        job.progress.review_approved,
        job.progress.redacting,
        job.progress.completed,
        job.progress.failed,
        job.progress.cancelled ?? 0,
        job.nav_hints?.item_count ?? '',
        job.nav_hints?.wizard_furthest_step ?? '',
        job.nav_hints?.first_awaiting_review_item_id ?? '',
      ].join('\x1e'),
    )
    .join('\x1f');
}

export function useBatchHub() {
  const nav = useNavigate();
  const cache = readActiveJobsCache();
  const [recentJobs, setRecentJobs] = useState<JobSummary[]>(() => cache?.jobs ?? []);
  const [loading, setLoading] = useState(cache === null);
  const [tableLoading, setTableLoading] = useState(false);
  const [jobsUnavailable, setJobsUnavailable] = useState(false);
  const recentJobsRef = useRef<JobSummary[]>(recentJobs);
  const lastSilentRefreshAtRef = useRef(0);

  useEffect(() => {
    recentJobsRef.current = recentJobs;
  }, [recentJobs]);

  const buildActiveJobs = useCallback((jobs: JobSummary[]) => {
    return sortJobsByUpdatedAt(jobs.filter((job) => isActiveJob(job.status)));
  }, []);

  const loadActiveJobs = useCallback(
    async (options?: { silent?: boolean }) => {
      const silent = options?.silent === true;
      const now = Date.now();
      if (silent && now - lastSilentRefreshAtRef.current < 5_000) return;
      const hadRows = recentJobsRef.current.length > 0;
      if (!silent) {
        if (hadRows) {
          setLoading(false);
          setTableLoading(true);
        } else {
          setLoading(true);
        }
      }
      try {
        const response = await listJobs({ page: 1, page_size: BATCH_HUB_RECENT_JOBS_LIMIT });
        const nextJobs = buildActiveJobs(Array.isArray(response?.jobs) ? response.jobs : []);
        setRecentJobs((prev) =>
          batchHubJobsSignature(prev) === batchHubJobsSignature(nextJobs) ? prev : nextJobs,
        );
        setJobsUnavailable(false);
        writeActiveJobsCache(nextJobs);
      } catch {
        if (!(silent && hadRows)) {
          setJobsUnavailable(true);
        }
        if (!silent && !hadRows) setRecentJobs([]);
      } finally {
        setLoading(false);
        if (!silent) setTableLoading(false);
        lastSilentRefreshAtRef.current = now;
      }
    },
    [buildActiveJobs],
  );

  useEffect(() => {
    void loadActiveJobs({ silent: cache !== null });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- run once for bootstrap
  }, []);

  useEffect(() => {
    if (typeof document === 'undefined') return;
    const onVisibilityChange = () => {
      if (document.visibilityState === 'visible') void loadActiveJobs({ silent: true });
    };
    document.addEventListener('visibilitychange', onVisibilityChange);
    return () => {
      document.removeEventListener('visibilitychange', onVisibilityChange);
    };
  }, [loadActiveJobs]);

  const activeJobs = useMemo(() => recentJobs, [recentJobs]);

  const openPreview = useCallback(
    (mode: BatchWizardMode = 'smart') => {
      nav(buildPreviewBatchRoute(mode, 1));
    },
    [nav],
  );

  const openBatch = useCallback(
    (mode: BatchWizardMode = 'smart') => {
      if (jobsUnavailable) {
        nav(buildPreviewBatchRoute(mode, 1));
        return;
      }
      nav(`/batch/${mode}?new=1`);
    },
    [jobsUnavailable, nav],
  );

  const continueJob = useCallback(
    (job: JobSummary) => {
      const navTarget = resolveJobPrimaryNavigation({
        jobId: job.id,
        status: job.status,
        jobType: job.job_type,
        items: [],
        currentPage: 'other',
        navHints: job.nav_hints,
        jobConfig: job.config,
      });
      if (navTarget.kind === 'link') {
        nav(navTarget.to);
      } else {
        nav(`/jobs/${encodeURIComponent(job.id)}`);
      }
    },
    [nav],
  );

  return {
    loading,
    tableLoading,
    jobsUnavailable,
    activeJobs,
    openBatch,
    continueJob,
    openPreview,
  };
}
