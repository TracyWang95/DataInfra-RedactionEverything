// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  listJobs,
  type JobSummary,
} from '@/services/jobsApi';
import { resolveJobPrimaryNavigation } from '@/utils/jobPrimaryNavigation';
import { buildPreviewBatchRoute } from '../lib/batch-preview-fixtures';

function isActiveJob(status: string): boolean {
  return ['draft', 'queued', 'processing', 'running', 'awaiting_review', 'redacting'].includes(status);
}

export function useBatchHub() {
  const nav = useNavigate();
  const [recentJobs, setRecentJobs] = useState<JobSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [jobsUnavailable, setJobsUnavailable] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const res = await listJobs({ page: 1, page_size: 20 });
        if (!cancelled) {
          setJobsUnavailable(false);
          setRecentJobs(
            res.jobs
              .filter((job) => isActiveJob(job.status))
              .sort((left, right) => {
                const leftTime = left.updated_at ? Date.parse(left.updated_at) : 0;
                const rightTime = right.updated_at ? Date.parse(right.updated_at) : 0;
                return rightTime - leftTime;
              }),
          );
        }
      } catch {
        if (!cancelled) {
          setJobsUnavailable(true);
          setRecentJobs([]);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const activeJobs = useMemo(() => recentJobs, [recentJobs]);

  const openPreview = useCallback(() => {
    nav(buildPreviewBatchRoute('smart', 1));
  }, [nav]);

  const openBatch = useCallback(() => {
    if (jobsUnavailable) {
      nav(buildPreviewBatchRoute('smart', 1));
      return;
    }
    nav('/batch/smart');
  }, [jobsUnavailable, nav]);

  const continueJob = useCallback((job: JobSummary) => {
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
  }, [nav]);

  return {
    loading,
    jobsUnavailable,
    activeJobs,
    openBatch,
    continueJob,
    openPreview,
  };
}
