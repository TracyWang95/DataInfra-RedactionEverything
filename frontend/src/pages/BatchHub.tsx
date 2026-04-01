import React, { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { t } from '../i18n';
import { createJob, listJobs, type JobSummary, type JobTypeApi } from '../services/jobsApi';
import { resolveJobPrimaryNavigation } from '../utils/jobPrimaryNavigation';
import { formatAggregateJobStatus } from '../utils/jobStatusLabels';
import { EmptyState } from '../components/EmptyState';

function batchPath(_jobType: JobTypeApi): string {
  // 统一走 smart 模式，旧 text_batch / image_batch 兼容路由
  return '/batch/smart';
}

function isActiveJob(status: string): boolean {
  return ['draft', 'queued', 'processing', 'running', 'awaiting_review', 'redacting'].includes(status);
}

export const BatchHub: React.FC = () => {
  const nav = useNavigate();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [recentJobs, setRecentJobs] = useState<JobSummary[]>([]);
  const [recentLoading, setRecentLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setRecentLoading(true);
      try {
        const res = await listJobs({ page: 1, page_size: 20 });
        if (!cancelled) {
          setRecentJobs(res.jobs.filter(j => isActiveJob(j.status)));
        }
      } catch {
        if (!cancelled) setRecentJobs([]);
      } finally {
        if (!cancelled) setRecentLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const recentByType = useMemo(() => {
    const seen = new Set<JobTypeApi>();
    const out: JobSummary[] = [];
    for (const j of recentJobs) {
      if (seen.has(j.job_type)) continue;
      seen.add(j.job_type);
      out.push(j);
    }
    return out;
  }, [recentJobs]);

  const start = async (jobType: JobTypeApi) => {
    setErr(null);
    setBusy(true);
    try {
      const j = await createJob({
        job_type: jobType,
        title: t('batchHub.batchTaskTitle').replace('{time}', new Date().toLocaleString()),
        config: {},
      });
      nav(`${batchPath(jobType)}?jobId=${encodeURIComponent(j.id)}&step=1&new=1`);
    } catch (e) {
      setErr(e instanceof Error ? e.message : t('batchHub.createFailed'));
    } finally {
      setBusy(false);
    }
  };

  const continueTask = (job: JobSummary) => {
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
  };

  return (
    <div className="h-full min-h-0 flex flex-col bg-[#fafafa] dark:bg-gray-900 px-3 py-4 sm:px-6 overflow-y-auto">
      <div className="max-w-3xl mx-auto w-full space-y-4">
        <div>
          <h2 className="text-lg font-semibold text-[#1d1d1f] dark:text-gray-100">{t('batchHub.title')}</h2>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
            {t('batchHub.desc')}
          </p>
        </div>
        {err && <div className="rounded-lg border border-red-200 dark:border-red-800 bg-red-50 dark:bg-red-900/30 text-red-900 dark:text-red-300 text-sm px-3 py-2">{err}</div>}

        <div className="grid gap-3">
          <button
            type="button"
            disabled={busy}
            onClick={() => void start('smart_batch')}
            className="text-left rounded-xl border border-black/[0.08] dark:border-gray-700 bg-white dark:bg-gray-800 p-5 shadow-sm dark:shadow-gray-900/30 hover:border-[#1d1d1f]/20 dark:hover:border-gray-500 transition-colors disabled:opacity-50"
          >
            <div className="text-sm font-semibold text-[#1d1d1f] dark:text-gray-100">{t('batchHub.newTask')}</div>
            <p className="text-2xs text-gray-500 dark:text-gray-400 mt-1">
              {t('batchHub.newTaskDesc')}
            </p>
          </button>
        </div>

        <div className="rounded-2xl border border-black/[0.06] dark:border-gray-700 bg-white dark:bg-gray-800 shadow-sm dark:shadow-gray-900/30 overflow-hidden">
          <div className="px-4 py-3 border-b border-gray-100 dark:border-gray-700 flex items-center justify-between gap-2">
            <div>
              <h3 className="text-sm font-semibold text-[#1d1d1f] dark:text-gray-100">{t('batchHub.recentTitle')}</h3>
              <p className="text-2xs text-gray-500 dark:text-gray-400 mt-0.5">{t('batchHub.recentDesc')}</p>
            </div>
            <Link to="/jobs" className="text-xs font-medium text-[#007AFF] hover:underline">
              {t('batchHub.jobCenter')}
            </Link>
          </div>
          {recentLoading ? (
            <div className="px-4 py-6 text-sm text-gray-500 dark:text-gray-400">{t('batchHub.loading')}</div>
          ) : recentByType.length === 0 ? (
            <EmptyState title={t('emptyState.noActiveJobs')} description={t('emptyState.noActiveJobsDesc')} />
          ) : (
            <ul className="divide-y divide-gray-100 dark:divide-gray-700">
              {recentByType.map(job => {
                const primary = resolveJobPrimaryNavigation({
                  jobId: job.id,
                  status: job.status,
                  jobType: job.job_type,
                  items: [],
                  currentPage: 'other',
                  navHints: job.nav_hints,
                  jobConfig: job.config,
                });
                return (
                  <li key={job.id} className="px-4 py-3 flex flex-wrap items-center justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-2xs font-semibold px-1.5 py-0.5 rounded bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300">
                          {t('batchHub.batch')}
                        </span>
                        <span className="text-sm font-medium text-[#1d1d1f] dark:text-gray-100 truncate">{job.title || t('batchHub.unnamedTask')}</span>
                        <span className="text-2xs text-gray-500 dark:text-gray-400">{formatAggregateJobStatus(job.status)}</span>
                      </div>
                      <div className="text-2xs text-gray-500 dark:text-gray-400 mt-1 tabular-nums">
                        {t('batchHub.progressSummary').replace('{total}', String(job.progress.total_items)).replace('{awaiting}', String(job.progress.awaiting_review)).replace('{completed}', String(job.progress.completed))}
                        {job.progress.failed ? t('batchHub.failedSuffix').replace('{n}', String(job.progress.failed)) : ''}
                      </div>
                    </div>
                    <div className="shrink-0 flex flex-wrap items-center gap-2 justify-end">
                      {primary.kind === 'link' ? (
                        <button
                          type="button"
                          onClick={() => continueTask(job)}
                          className="text-sm font-medium text-[#007AFF] hover:underline"
                        >
                          {primary.label}
                        </button>
                      ) : (
                        <Link
                          to={`/jobs/${job.id}`}
                          className="text-sm font-medium text-[#007AFF] hover:underline"
                        >
                          {t('batchHub.viewDetail')}
                        </Link>
                      )}
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        <p className="text-2xs text-gray-400 dark:text-gray-500">
          {busy ? t('batchHub.creating') : ' '}
          <Link to="/jobs" className="text-[#007AFF] hover:underline ml-2">
            {t('batchHub.jobCenter')}
          </Link>
          <span className="mx-1">·</span>
          <Link to="/history" className="text-[#007AFF] hover:underline">
            {t('batchHub.history')}
          </Link>
        </p>
      </div>
    </div>
  );
};
